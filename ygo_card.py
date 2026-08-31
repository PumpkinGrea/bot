# Yu-Gi-Oh! Chinese card lookup backed by YGOCDB's public search endpoint.
from io import BytesIO
import re
import time

from PIL import Image, ImageOps
import requests


_API_URL = "https://ygocdb.com/api/v0/"
_CARD_URL = "https://ygocdb.com/card/{card_id}"
_IMAGE_URL = "https://cdn.233.momobako.com/ygoimg/ygopro/{card_id}.webp"
_TIMEOUT = 15
_CACHE_TTL = 600
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_CACHE = {}
_HEADERS = {
    "User-Agent": "HoloQQBot/1.0 (Yu-Gi-Oh card lookup)",
    "Accept": "application/json",
}
_session = requests.Session()
_session.headers.update(_HEADERS)


def _normalize_name(value: str) -> str:
    return re.sub(r"[\s·・,，。！？!?()（）\[\]【】'\"-]", "", (value or "").casefold())


def _pick_card(cards: list[dict], query: str) -> dict | None:
    """Prefer an exact name in any available language over site ranking."""
    normalized_query = _normalize_name(query)
    for card in cards:
        for field in ("cn_name", "sc_name", "md_name", "cnocg_n", "jp_name", "en_name"):
            if normalized_query and normalized_query == _normalize_name(card.get(field, "")):
                return card
    return cards[0] if cards else None


def _clean_text(value: str) -> str:
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _format_card(card: dict, query: str, result_count: int) -> str:
    text = card.get("text") or {}
    name = card.get("cn_name") or card.get("sc_name") or card.get("jp_name") or "未知卡名"
    types = _clean_text(text.get("types")) or "类型资料暂无"
    description = _clean_text(text.get("desc")) or "暂无效果文本"
    pendulum_description = _clean_text(text.get("pdesc"))

    lines = [f"🃏 {name}", "━━━━━━━━━━", types]
    jp_name = card.get("jp_name")
    en_name = card.get("en_name")
    if jp_name:
        lines.append(f"日文：{jp_name}")
    if en_name:
        lines.append(f"英文：{en_name}")
    password = card.get("id")
    if password:
        lines.append(f"官方密码：{password}")
    if card.get("faqcount") is not None:
        lines.append(f"相关 FAQ：{card['faqcount']} 条")

    lines.extend(["━━━━━━━━━━"])
    if pendulum_description:
        lines.extend(["灵摆效果：", pendulum_description, ""])
    lines.extend(["卡片效果：", description])

    if result_count > 1 and _normalize_name(query) != _normalize_name(name):
        lines.extend(["", f"（「{query}」共匹配 {result_count} 张，以上为最相关结果。）"])
    if password:
        lines.append(f"资料页：{_CARD_URL.format(card_id=password)}")
    lines.append("信息来源：YGOCDB")
    return "\n".join(lines)


def download_ygo_card_image(image_url: str) -> tuple[tuple[bytes, str] | None, str | None]:
    """Convert YGOCDB's WebP card art into a QQ-compatible JPEG."""
    try:
        with _session.get(image_url, timeout=_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_IMAGE_BYTES:
                return None, "卡图文件过大。"

            image_bytes = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                image_bytes.extend(chunk)
                if len(image_bytes) > _MAX_IMAGE_BYTES:
                    return None, "卡图文件过大。"

        image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=90, optimize=True)
        return (output.getvalue(), "ygo-card.jpg"), None
    except Exception as exc:
        print(f"[游戏王] 卡图下载或转换失败 {image_url}: {exc}")
        return None, "卡图暂时无法获取。"


def query_ygo_card(query: str) -> tuple[str, str | None]:
    """Look up one Yu-Gi-Oh! card and return detailed text plus its card-art URL."""
    query = (query or "").strip()
    if not query:
        return "汝想查哪张游戏王卡？试试「查游戏王卡 青眼白龙」。", None

    cache_key = query.casefold()
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        return cached[0], cached[2]

    try:
        response = _session.get(_API_URL, params={"search": query}, timeout=_TIMEOUT)
        response.raise_for_status()
        cards = response.json().get("result") or []
    except (requests.RequestException, ValueError) as exc:
        print(f"[游戏王] 卡牌查询失败 {query}: {exc}")
        return "咱这会儿连不上游戏王卡牌数据库，稍后再试试吧。", None

    card = _pick_card(cards, query)
    if not card:
        return f"咱没找到「{query}」这张游戏王卡，试试中文、日文或英文完整卡名？", None

    result = _format_card(card, query, len(cards))
    card_id = card.get("id")
    image_url = _IMAGE_URL.format(card_id=card_id) if card_id else None
    _CACHE[cache_key] = (result, time.time(), image_url)
    return result, image_url
