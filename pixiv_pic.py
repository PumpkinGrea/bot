# Pixiv tag search through Lolicon API. The API returns proxied Pixiv image URLs.
import os

import requests


_API_URL = "https://api.lolicon.app/setu/v2"
_TIMEOUT = 20
_HEADERS = {
    "User-Agent": "HoloQQBot/1.0 (Pixiv tag image search)",
}
_IMAGE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


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


def download_pixiv_image(url: str) -> tuple[tuple[bytes, str] | None, str | None]:
    """Download a QQ-compatible image through the proxy for local rehosting."""
    try:
        with requests.get(
            url, headers=_HEADERS, timeout=_TIMEOUT, stream=True, proxies=_PROXIES
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            extension = _IMAGE_EXTENSIONS.get(content_type)
            if not extension:
                return None, "这张图不是 QQ 支持的 JPEG 或 PNG 格式。"

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_IMAGE_BYTES:
                return None, "这张图超过 10 MB，没法发送。"

            image_bytes = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                image_bytes.extend(chunk)
                if len(image_bytes) > _MAX_IMAGE_BYTES:
                    return None, "这张图超过 10 MB，没法发送。"
            if not image_bytes:
                return None, "这张图下载为空，换个标签再试试吧。"
            return (bytes(image_bytes), f"pixiv.{extension}"), None
    except Exception as e:
        print(f"[Pixiv 搜图] 图片下载失败 {url}: {e}")
        return None, "P站图片下载失败，稍后再试试吧。"


def search_pixiv_pic(tag: str) -> tuple[dict | None, str | None]:
    """Search one all-ages Pixiv illustration by tag."""
    tag = (tag or "").strip()
    if not tag:
        return None, "汝想搜什么标签？试试「搜索P站 初音未来」。"

    try:
        response = requests.get(
            _API_URL,
            params={"r18": 0, "num": 1, "size": "regular", "tag": tag},
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
        if (artwork.get("urls") or {}).get("regular"):
            return artwork, None

    return None, "这个标签暂时没有可用作品，换个标签再试试吧。"


def format_pixiv_caption(artwork: dict) -> str:
    """Format public attribution and the original Pixiv artwork link."""
    title = artwork.get("title") or "未命名作品"
    author = artwork.get("author") or "未知作者"
    pid = artwork.get("pid")
    tags = artwork.get("tags") or []
    lines = [f"《{title}》", f"作者：{author}"]
    if tags:
        lines.append("标签：" + " / ".join(str(item) for item in tags[:12]))
    if pid:
        lines.append(f"作品：https://www.pixiv.net/artworks/{pid}")
    lines.append("信息来源：Pixiv（经 Lolicon API）")
    return "\n".join(lines)
