"""Refresh public SVWB data using a persistent Chromium session."""
import argparse
import base64
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "svwb"
BASE = "https://svwbmeta.com"


def sync_faces(page):
    """Cache the site's seven leader portraits; failed refreshes keep old files."""
    from io import BytesIO
    from PIL import Image
    from sv_cr_chart import FACE_NAMES

    directory = DATA / "faces"
    directory.mkdir(exist_ok=True)
    for name in FACE_NAMES:
        path = directory / f"{name}.png"
        if path.exists():
            try:
                with Image.open(path) as image:
                    image.verify()
                continue
            except (OSError, ValueError):
                pass
        temporary = None
        try:
            encoded = page.evaluate("""async url => {
                const r = await fetch(url, {signal: AbortSignal.timeout(30000)});
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const blob = await r.blob();
                return await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => resolve(reader.result.split(',')[1]);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
            }""", f"{BASE}/faces/{name}.png")
            data = base64.b64decode(encoded, validate=True)
            with Image.open(BytesIO(data)) as image:
                if image.format != "PNG":
                    raise ValueError("Expected PNG portrait")
                image.verify()
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                handle.write(data)
            os.replace(temporary, path)
            print(f"Loaded portrait: {name}", flush=True)
        except Exception as error:
            print(f"Portrait unavailable ({name}); keeping class color: {error}", flush=True)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def configured_proxy():
    try:
        from botpy.ext.cog_yaml import read
        config = read(str(ROOT / "config.yaml"))
        return (config.get("svwb_proxy") or "").strip()
    except Exception:
        return ""


def sync(headed=False, proxy=None):
    from playwright.sync_api import sync_playwright

    DATA.mkdir(parents=True, exist_ok=True)
    proxy = proxy or configured_proxy()
    with sync_playwright() as p:
        options = {"headless": not headed}
        if proxy:
            options["proxy"] = {"server": proxy}
        context = p.chromium.launch_persistent_context(
            str(DATA / "browser-profile"), **options
        )
        try:
            page = context.new_page()
            page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            page.locator("#svwb-manifest").wait_for(state="attached", timeout=60000)
            manifest = json.loads(page.locator("#svwb-manifest").text_content())
            payload = {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "manifest": manifest, "datasets": {},
            }
            targets = ["archetypes", "topdecks.rotation", "topdecks.unlimited",
                       "tierlist.rotation", "tierlist.unlimited", "rankings"]
            for name in targets:
                filename = manifest["files"][name]
                if not isinstance(filename, str) or "/" in filename or not filename.endswith(".json"):
                    raise ValueError(f"Invalid manifest filename for {name}")
                # Fetch inside the actual browser, retaining its cookies and
                # browser networking rather than using requests/APIRequestContext.
                result = page.evaluate("""async (url) => {
                    const response = await fetch(url, {signal: AbortSignal.timeout(30000)});
                    if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
                    return await response.json();
                }""", f"{BASE}/data/{filename}")
                if not isinstance(result, dict):
                    raise ValueError(f"Invalid JSON object for {name}")
                field = "decks" if name.startswith("topdecks.") else "tiers"
                if name == "rankings":
                    if not isinstance(result.get("rankings"), dict):
                        raise ValueError("Missing or invalid rankings")
                elif name != "archetypes":
                    expected = list if field == "decks" else dict
                    if not isinstance(result.get(field), expected):
                        raise ValueError(f"Missing or invalid {field}: {name}")
                payload["datasets"][name] = result
                print(f"Loaded {name}", flush=True)
            sync_faces(page)
        finally:
            context.close()
    # Publish only after all datasets have been fetched and validated.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=DATA,
                                         suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(temporary, DATA / "snapshot.json")
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Updated {DATA / 'snapshot.json'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true", help="Requires a desktop session")
    parser.add_argument("--proxy", help="Optional browser proxy, e.g. http://127.0.0.1:7890")
    args = parser.parse_args()
    try:
        sync(args.headed, args.proxy)
    except Exception as error:
        parser.exit(1, f"SVWB sync failed; existing snapshot preserved: {error}\n")
