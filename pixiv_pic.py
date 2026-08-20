# Pixiv tag search through Lolicon API. The API returns proxied Pixiv image URLs.
import os

import requests


_API_URL = "https://api.lolicon.app/setu/v2"
_TIMEOUT = 20
_HEADERS = {
    "User-Agent": "HoloQQBot/1.0 (Pixiv tag image search)",
}
_OK_TYPES = ("image/jpeg", "image/jpg", "image/png")


def _load_proxy() -> str:
    """Read the dedicated Pixiv proxy without relying on service environment variables."""
    try:
        from botpy.ext.cog_yaml import read
        config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
        config = read(config_path)
        # By default reuse the established Steam proxy. A separate setting can
        # override it when Pixiv needs a different route.
        return (config.get("pixiv_proxy") or config.get("steam_proxy") or "").strip()
    except Exception as e:
        print(f"[Pixiv 搜图] 读取 pixiv_proxy 失败，按直连处理：{e}")
        return ""


_proxy = _load_proxy()
_PROXIES = {"http": _proxy, "https": _proxy} if _proxy else None
if _proxy:
    print(f"[Pixiv 搜图] 已启用 Pixiv 专用代理：{_proxy}")


def _verify_image(url: str) -> bool:
    """Confirm the returned URL is a QQ-compatible image before sending it."""
    try:
        response = requests.get(
            url, headers=_HEADERS, timeout=_TIMEOUT, stream=True, proxies=_PROXIES
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        response.close()
        return content_type in _OK_TYPES
    except Exception as e:
        print(f"[Pixiv 搜图] 图片校验失败 {url}: {e}")
        return False


def search_pixiv_pic(tag: str) -> tuple[dict | None, str | None]:
    """Search one Pixiv illustration by tag. r18=2 keeps both general and R-18 works."""
    tag = (tag or "").strip()
    if not tag:
        return None, "汝想搜什么标签？试试「搜索P站 初音未来」。"

    try:
        response = requests.get(
            _API_URL,
            params={"r18": 2, "num": 1, "size": "regular", "tag": tag},
            headers=_HEADERS,
            timeout=_TIMEOUT,
            proxies=_PROXIES,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"[Pixiv 搜图] 请求失败: {e}")
        return None, "P站图库暂时连不上，稍后再试试吧。"

    if payload.get("error"):
        print(f"[Pixiv 搜图] API 错误: {payload['error']}")
        return None, "这次没找到合适的图，换个标签再试试吧。"

    for artwork in payload.get("data") or []:
        image_url = (artwork.get("urls") or {}).get("regular")
        if image_url and _verify_image(image_url):
            return artwork, None

    return None, "这次没拿到 QQ 能发送的图片，换个标签再试试吧。"


def format_pixiv_caption(artwork: dict) -> str:
    """Format public attribution and the original Pixiv artwork link."""
    title = artwork.get("title") or "未命名作品"
    author = artwork.get("author") or "未知作者"
    pid = artwork.get("pid")
    tags = artwork.get("tags") or []
    r18_label = "R-18" if artwork.get("r18") else "全年龄"
    lines = [f"《{title}》", f"作者：{author} · {r18_label}"]
    if tags:
        lines.append("标签：" + " / ".join(str(item) for item in tags[:12]))
    if pid:
        lines.append(f"作品：https://www.pixiv.net/artworks/{pid}")
    lines.append("信息来源：Pixiv（经 Lolicon API）")
    return "\n".join(lines)
