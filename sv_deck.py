# Shadowverse: Worlds Beyond high-rated deck lookup from SVWB Meta's public data.
import html
import json
import re
import threading
import time

import requests

from sv_card import get_card_names


_BASE_URL = "https://svwbmeta.com"
_MANIFEST_URL = f"{_BASE_URL}/"
_DATA_URL = f"{_BASE_URL}/data/{{filename}}"
_TIMEOUT = 20
_CACHE_TTL = 600
_RESULT_LIMIT = 3

_HEADERS = {
    "User-Agent": "HoloQQBot/1.0 (public SVWB Meta deck lookup)",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
}
_CLASS_NAMES = {
    "Forest": "精灵",
    "Sword": "皇家护卫",
    "Rune": "巫师",
    "Dragon": "龙族",
    "Abyss": "梦魇",
    "Haven": "主教",
    "Nemesis": "超越者",
    "Neutral": "中立",
}
_FORMAT_NAMES = {"rotation": "轮换", "unlimited": "无限"}
_FORMAT_ALIASES = {
    "轮换": "rotation", "标准": "rotation", "rotation": "rotation",
    "无限": "unlimited", "unlimited": "unlimited",
}
_SOURCE_LINE = "信息来源：https://svwbmeta.com/"
_TREND_MARKS = {"up": "↑", "down": "↓", "new": "NEW"}

_MANIFEST_RE = re.compile(
    r'<script type="application/json" id="svwb-manifest">(.*?)</script>', re.S
)
_cache = {"decks": {}, "tiers": {}, "archetypes": {}, "ts": 0.0}
_lock = threading.Lock()
_session = requests.Session()
_session.headers.update(_HEADERS)


def _fetch_json(filename: str):
    response = _session.get(_DATA_URL.format(filename=filename), timeout=_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _fetch_data():
    response = _session.get(_MANIFEST_URL, timeout=_TIMEOUT)
    response.raise_for_status()
    match = _MANIFEST_RE.search(response.text)
    if not match:
        raise RuntimeError("SVWB Meta 页面中没有找到数据清单")
    manifest = json.loads(html.unescape(match.group(1)))
    files = manifest.get("files") or {}
    archetypes = _fetch_json(files["archetypes"])
    decks = {}
    tiers = {}
    for fmt in _FORMAT_NAMES:
        deck_payload = _fetch_json(files[f"topdecks.{fmt}"])
        tier_payload = _fetch_json(files[f"tierlist.{fmt}"])
        decks[fmt] = deck_payload.get("decks") or []
        tiers[fmt] = tier_payload.get("tiers") or {}
    return decks, tiers, archetypes


def _get_data():
    with _lock:
        now = time.time()
        if _cache["decks"] and now - _cache["ts"] < _CACHE_TTL:
            return _cache["decks"], _cache["tiers"], _cache["archetypes"]
        try:
            decks, tiers, archetypes = _fetch_data()
            _cache.update({"decks": decks, "tiers": tiers, "archetypes": archetypes, "ts": now})
            return decks, tiers, archetypes
        except Exception as e:
            print(f"[SVWB Meta] Deck data fetch failed: {e}")
            if _cache["decks"]:
                return _cache["decks"], _cache["tiers"], _cache["archetypes"]
            raise


def _parse_query(raw: str):
    fmt = "rotation"
    remaining = []
    for token in (raw or "").strip().split():
        normalized = token.lower()
        if normalized in _FORMAT_ALIASES:
            fmt = _FORMAT_ALIASES[normalized]
        else:
            remaining.append(token)
    keyword = " ".join(remaining).strip()
    return fmt, keyword


def _display_archetype(deck: dict, archetypes: dict) -> str:
    name = deck.get("archetype") or "未分类"
    labels = archetypes.get(name) or {}
    return labels.get("zh-Hans") or labels.get("en") or name


def _filter_decks(decks: list[dict], keyword: str, archetypes: dict) -> list[dict]:
    if not keyword:
        return decks
    lowered = keyword.lower()
    matched = []
    for deck in decks:
        fields = (
            _display_archetype(deck, archetypes),
            deck.get("archetype", ""),
            (archetypes.get(deck.get("archetype")) or {}).get("en", ""),
        )
        if any(lowered in str(field).lower() for field in fields):
            matched.append(deck)
    return matched


def _get_deck_card_names(decks: list[dict]) -> dict[int, str]:
    card_ids = []
    for deck in decks:
        for card in deck.get("cards") or []:
            card_ids.append(card.get("cardId"))
    try:
        return get_card_names(card_ids)
    except Exception as e:
        print(f"[SVWB Meta] Card name fetch failed: {e}")
        return {}


def _format_deck_cards(deck: dict, card_names: dict[int, str]) -> list[str]:
    cards = deck.get("cards") or []
    entries = []
    total_count = 0
    for card in cards:
        try:
            card_id = int(card.get("cardId"))
            count = int(card.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total_count += count
        name = card_names.get(card_id, f"卡牌 ID {card_id}")
        entries.append(f"{name} x{count}")

    if not entries:
        return ["   构筑：该卡组没有公开卡表。"]

    lines = [f"   构筑：{total_count} 张 / {len(entries)} 种"]
    for start in range(0, len(entries), 4):
        lines.append("   ・" + " / ".join(entries[start:start + 4]))
    return lines


def query_top_decks(raw: str):
    """Return the highest-rated current decks from SVWB Meta as plain text."""
    fmt, keyword = _parse_query(raw)
    try:
        data, _, archetypes = _get_data()
    except Exception:
        return f"咱这会儿连不上 SVWB Meta，稍后再试试吧。\n\n{_SOURCE_LINE}"

    candidates = _filter_decks(data.get(fmt, []), keyword, archetypes)
    if not candidates:
        scope = f"「{keyword}」" if keyword else "当前环境"
        return f"SVWB Meta 上暂时没找到 {scope} 的{_FORMAT_NAMES[fmt]}高分卡组。\n\n{_SOURCE_LINE}"

    candidates.sort(key=lambda deck: (deck.get("rating") or 0, deck.get("postedAt") or ""), reverse=True)
    title = f"SVWB Meta 高分卡组 · {_FORMAT_NAMES[fmt]}"
    if keyword:
        title += f" · {keyword}"
    lines = [title]
    displayed_decks = candidates[:_RESULT_LIMIT]
    card_names = _get_deck_card_names(displayed_decks)
    for index, deck in enumerate(displayed_decks, start=1):
        archetype = _display_archetype(deck, archetypes)
        class_name = _CLASS_NAMES.get(deck.get("class"), deck.get("class") or "未知职业")
        rating = deck.get("rating") or "-"
        posted_at = deck.get("lastPostedAt") or deck.get("postedAt") or ""
        author = deck.get("authorName") or "匿名"
        lines.append(f"\n{index}. {archetype} · {class_name} · {rating} 分")
        lines.append(f"   作者：{author}" + (f" · {posted_at}" if posted_at else ""))
        lines.extend(_format_deck_cards(deck, card_names))
        if deck.get("deckUrl"):
            lines.append(f"   卡组：{deck['deckUrl']}")
        if deck.get("tweetUrl"):
            lines.append(f"   来源：{deck['tweetUrl']}")
    if len(candidates) > _RESULT_LIMIT:
        lines.append(f"\n共找到 {len(candidates)} 套，已展示评分最高的 {_RESULT_LIMIT} 套。")
    lines.append(f"\n{_SOURCE_LINE}")
    return "\n".join(lines)


def query_tier_list(raw: str):
    """Return SVWB Meta's current archetype tier list as plain text."""
    fmt, _ = _parse_query(raw)
    try:
        _, tiers, archetypes = _get_data()
    except Exception:
        return f"咱这会儿连不上 SVWB Meta，稍后再试试吧。\n\n{_SOURCE_LINE}"

    tier_data = tiers.get(fmt) or {}
    lines = [f"SVWB Meta 卡组梯度表 · {_FORMAT_NAMES[fmt]}"]
    for key in ("t0", "t1", "t2", "t3", "t4"):
        decks = tier_data.get(key) or []
        if not decks:
            continue
        labels = []
        for deck in decks:
            name = _display_archetype(deck, archetypes)
            trend = _TREND_MARKS.get(deck.get("trend"))
            labels.append(f"{name} {trend}" if trend else name)
        lines.append(f"{key.upper()}：" + " / ".join(labels))

    unranked = tier_data.get("unranked") or []
    if unranked:
        labels = [_display_archetype(deck, archetypes) for deck in unranked]
        lines.append("未评级：" + " / ".join(labels))
    if len(lines) == 1:
        lines.append("当前没有可用的梯度数据。")
    lines.append(f"\n{_SOURCE_LINE}")
    return "\n".join(lines)
