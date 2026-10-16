"""Merge WBGDB Japanese voice clips by official card ID and encode QQ SILK."""
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote

import requests

from sv_card import _get_cards, _search

_ROOT = Path(__file__).resolve().parent
_CACHE = _ROOT / "data" / "sv_voice"
_BASE = "https://raw.githubusercontent.com/mhmkhlrdn/WBGDB/master/Site/"
_SOURCE = "语音来源：WBGDB（社区收录）"
_LOCK = threading.Lock()
_LOG = logging.getLogger(__name__)
_RATE = 24000
_MAX_PCM = _RATE * 2 * 300  # Reject overlong sets rather than silently truncating.


def _session():
    session = requests.Session()
    session.headers["User-Agent"] = "HoloQQBot/1.0 (WBGDB voice lookup)"
    session.trust_env = False
    from botpy.ext.cog_yaml import read
    config = read(str(_ROOT / "config.yaml"))
    proxy = (config.get("card_voice_proxy") or config.get("steam_proxy") or "").strip()
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def _download(session, url, limit):
    body = bytearray()
    with session.get(url, timeout=(10, 30), stream=True) as response:
        response.raise_for_status()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError("语音资源超过下载大小限制")
    if not body:
        raise ValueError("语音资源为空")
    return bytes(body)


def _index(session):
    path = _CACHE / "cards.json"
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = json.loads(_download(session, _BASE + "cards.json", 20 * 1024 * 1024))
        if not isinstance(data, dict) or not data:
            raise ValueError("语音库索引格式异常")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
        return data
    except Exception:
        if path.exists():
            _LOG.warning("WBGDB index refresh failed; using cached index", exc_info=True)
            return json.loads(path.read_text(encoding="utf-8"))
        raise


def _voice_paths(index, common):
    # Match IDs, never fuzzy-match a second time against English directory names.
    for card_id in dict.fromkeys((common.get("card_id"), common.get("base_card_id"))):
        if card_id is None:
            continue
        for entry in index.values():
            metadata = entry.get("metadata") or {}
            for variant in ("common", "alternate"):
                info = metadata.get(variant) or {}
                if str(info.get("card_id")) != str(card_id):
                    continue
                voices = entry.get("voices") if variant == "common" else info.get("voices")
                paths = []
                for voice in voices or []:
                    path = voice.get("url") or ""  # url = Japanese, en_url = English.
                    if (path.startswith("Audio/") and path.endswith(".mp3")
                            and ".." not in path.split("/") and path not in paths):
                        paths.append(path)
                if paths:
                    return paths
    return []


def _encode(session, paths, destination):
    import pilk

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("服务器缺少 FFmpeg，请先安装 ffmpeg")
    with tempfile.TemporaryDirectory(prefix="voice-", dir=_CACHE) as work:
        work = Path(work)
        pcm = work / "merged.pcm"
        total = 0
        with pcm.open("wb") as merged:
            for number, path in enumerate(paths):
                mp3 = work / f"{number}.mp3"
                mp3.write_bytes(_download(session, _BASE + quote(path, safe="/"), 5 * 1024 * 1024))
                clip = work / f"{number}.pcm"
                result = subprocess.run(
                    [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(mp3),
                     "-vn", "-ar", str(_RATE), "-ac", "1", "-f", "s16le", str(clip)],
                    capture_output=True, timeout=30,
                )
                if result.returncode:
                    raise RuntimeError(f"第 {number + 1} 段语音解码失败")
                audio = clip.read_bytes()
                if not audio:
                    raise ValueError("语音解码结果为空")
                if number:
                    audio = bytes(int(_RATE * 2 * 0.35)) + audio
                total += len(audio)
                if total > _MAX_PCM:
                    raise ValueError("这张卡的整套语音超过 5 分钟，暂不发送，未截断语音")
                merged.write(audio)
        silk = work / "merged.silk"
        pilk.encode(str(pcm), str(silk), pcm_rate=_RATE, tencent=True)
        data = silk.read_bytes()
        if not data.startswith(b"\x02#!SILK_V3"):
            raise ValueError("SILK 编码结果异常")
        os.replace(silk, destination)
    return data


def query_card_voice(keyword):
    """Return (SILK bytes or None, caption/error); run in asyncio.to_thread."""
    keyword = (keyword or "").strip()
    if not keyword:
        return None, "请发送：卡牌语音 卡名（默认日语，支持近似卡名）。"
    with _LOCK:
        try:
            cards, _, _ = _get_cards()
            card, _, fuzzy, ambiguous = _search(cards, keyword)
            if ambiguous is not None:
                names = "、".join(ambiguous[:15])
                return None, f"匹配到 {len(ambiguous)} 张卡，请补充卡名：\n{names}"
            if not card:
                return None, f"没有找到「{keyword}」这张卡。"
            common = card["common"]
            name = common["name"]
            _CACHE.mkdir(parents=True, exist_ok=True)
            with _session() as session:
                paths = _voice_paths(_index(session), common)
                if not paths:
                    return None, f"「{name}」在 WBGDB 中暂未收录日语语音。\n{_SOURCE}"
                digest = hashlib.sha256(json.dumps(paths).encode()).hexdigest()[:24]
                destination = _CACHE / f"jp-{digest}.silk"
                if destination.exists():
                    data = destination.read_bytes()
                    if data.startswith(b"\x02#!SILK_V3"):
                        destination.touch()
                    else:
                        data = _encode(session, paths, destination)
                else:
                    data = _encode(session, paths, destination)
                # Bound converted audio storage, keeping most recently used sets.
                used = 0
                for cached in sorted(_CACHE.glob("*.silk"), key=lambda p: p.stat().st_mtime, reverse=True):
                    used += cached.stat().st_size
                    if used > 200 * 1024 * 1024 and cached != destination:
                        cached.unlink()
            matched = "（按近似卡名匹配）" if fuzzy else ""
            return data, f"{name}{matched} · 日语 · 已收录 {len(paths)} 段合辑\n{_SOURCE}"
        except ImportError:
            _LOG.exception("Card voice dependency missing")
            return None, "卡牌语音缺少依赖，请在服务器安装 requirements-voice.txt 中的 pilk。"
        except Exception as error:
            _LOG.exception("Card voice generation failed")
            if isinstance(error, (ValueError, RuntimeError)):
                return None, f"卡牌语音处理失败：{error}"
            return None, "卡牌语音下载或转换失败，请稍后再试；具体原因见机器人日志。"
