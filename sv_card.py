# 影之诗·超凡世界（Shadowverse: Worlds Beyond）卡牌查询模块
# 用户发「查卡 卡名」→ 从内存缓存的全卡表里按名字匹配 → 汇总文本 + 卡图 URL。
#
# 数据来自官方网站内部接口（免 key，逆向自 shadowverse-wb.com 官网卡查页面 JS，
# 参考实现: https://github.com/mhmkhlrdn/WBGDB）：
#   GET https://shadowverse-wb.com/web/CardList/cardList
#       ?offset={N}&class=0,1,2,3,4,5,6,7&cost=0,1,...,10&include_token=1
#       Header: lang: chs（简体中文；也支持 cht/jp/en 等）
# 该接口按 offset 分页，每页 30 张，需翻页拉完整卡表（约 800+ 张），故本地缓存。
#
# 卡图直链：https://shadowverse-wb.com/uploads/card_image/{lang_seg}/card/{hash}.png
# lang_seg 取值取决于拉表时用的 lang（chs→chs, en→eng, jp→jpn...），
# 且 hash 是该语言版本专属的（卡图上的文字随语言变化），两者必须配对使用。
#
# 注意：本作「进化」不再像初代那样让每张卡单独变化攻击力/生命值，
# 而是全从者统一 +2/+2（超进化 +3/+3，参见官方 2025 special update 说明），
# 故不展示逐卡数值。进化/超进化触发的额外效果已内嵌在 skill_text 的
# <ev>/<sev> 标签里，不用再看 evo.skill_text（内容和 common 完全重复）。
import difflib
import random
import re
import time

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TIMEOUT = 15
_LANG = "chs"
_LANG_IMG_SEG = "chs"  # 卡图路径里的语言段，需与 _LANG 拉到的 hash 配对
_LIST_URL = "https://shadowverse-wb.com/web/CardList/cardList"
_LIST_PARAMS = {
    "class": "0,1,2,3,4,5,6,7",
    "cost": "0,1,2,3,4,5,6,7,8,9,10",
    "include_token": "1",
}
_PAGE_SIZE = 30
_IMG_TMPL = "https://shadowverse-wb.com/uploads/card_image/{lang}/card/{hash}.png"

_CLASS_NAME = {
    0: "中立", 1: "精灵", 2: "皇家护卫", 3: "巫师",
    4: "龙族", 5: "梦魇", 6: "主教", 7: "超越者",
}
_TYPE_NAME = {1: "从者", 2: "护符", 3: "倒计时护符", 4: "法术"}
_RARITY_NAME = {1: "普通", 2: "白银", 3: "黄金", 4: "传说"}

_CACHE_TTL = 86400  # 卡池不会频繁变动，一天刷新一次即可
_cache: dict = {"cards": None, "ts": 0}

_session = requests.Session()
_session.headers.update(_HEADERS)

# 富文本标记清洗：<color=xxx>词</color> 只保留文字；<hr> 转成分隔线；
# <ridx=N>...</ridx> 是多选分支，保留内容去标记；<ev>/<sev> 单独处理成前缀
_RE_COLOR = re.compile(r"<color=[^>]*>(.*?)</color>", re.S)
_RE_RIDX = re.compile(r"<ridx=\d+>(.*?)</ridx>", re.S)
_RE_EV = re.compile(r"<ev>(.*?)</ev>", re.S)
_RE_SEV = re.compile(r"<sev>(.*?)</sev>", re.S)


def _clean_skill_text(text: str) -> str:
    """清洗 skill_text 里的富文本标记，转成纯文字，保留换行结构。"""
    if not text:
        return ""
    text = _RE_EV.sub(lambda m: f"\n✨进化时：{m.group(1)}", text)
    text = _RE_SEV.sub(lambda m: f"\n🌟超进化时：{m.group(1)}", text)
    text = _RE_RIDX.sub(lambda m: f"· {m.group(1)}", text)
    text = _RE_COLOR.sub(lambda m: m.group(1), text)
    text = text.replace("<hr>", "\n")
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _fetch_cards():
    """翻页拉全量卡表。返回 {card_id: card_detail} 字典，失败抛异常交给上层处理。"""
    cards = {}
    offset = 0
    total = None
    while total is None or offset < total:
        resp = _session.get(
            _LIST_URL,
            params={**_LIST_PARAMS, "offset": offset},
            headers={"lang": _LANG},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        if total is None:
            total = data.get("count") or 0
        page_cards = data.get("card_details") or {}
        if not page_cards and not cards:
            raise RuntimeError("接口返回空卡表")
        cards.update(page_cards)
        offset += _PAGE_SIZE
    return cards


def _get_cards():
    """带缓存地拿全量卡表。缓存过期或为空时刷新；刷新失败则沿用旧缓存（若有）。"""
    now = time.time()
    if _cache["cards"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["cards"]
    try:
        cards = _fetch_cards()
        _cache["cards"] = cards
        _cache["ts"] = now
        return cards
    except Exception as e:
        print(f"[影之诗] 拉取卡表失败: {e}")
        if _cache["cards"]:
            return _cache["cards"]  # 刷新失败但有旧缓存，先用着
        raise


def _search(cards: dict, keyword: str):
    """
    按卡名找卡，返回 (命中卡, 同名候选数, 是否为模糊匹配)：
      - 精确匹配（大小写不敏感）优先；再试包含匹配；都没有则用相似度找最接近的卡名
      - 同一张卡可能有多个「异画」版本（card_id 不同但 name 相同），
        优先选 card_id == base_card_id 的原画版本
      - 找不到返回 (None, 0, False)
    """
    kw = keyword.strip().lower()
    named = [v for v in cards.values() if v.get("common", {}).get("name")]
    is_fuzzy = False

    exact = [v for v in named if v["common"]["name"].lower() == kw]
    candidates = exact if exact else [v for v in named if kw in v["common"]["name"].lower()]

    if not candidates:
        all_names = list({v["common"]["name"] for v in named})
        close = difflib.get_close_matches(kw, [n.lower() for n in all_names], n=1, cutoff=0.4)
        if close:
            matched_name = next(n for n in all_names if n.lower() == close[0])
            candidates = [v for v in named if v["common"]["name"] == matched_name]
            is_fuzzy = True

    if not candidates:
        return None, 0, False

    names = {v["common"]["name"] for v in candidates}
    picked = next(
        (v for v in candidates if v["common"]["card_id"] == v["common"]["base_card_id"]),
        candidates[0],
    )
    return picked, len(names), is_fuzzy


def _format_card(card: dict) -> str:
    c = card["common"]
    cls = _CLASS_NAME.get(c["class"], "未知")
    ctype = _TYPE_NAME.get(c["type"], "未知")
    rarity = _RARITY_NAME.get(c["rarity"], "未知")
    cost = c.get("cost", 0)
    cost_str = str(cost) if cost is not None and cost >= 0 else "-"

    lines = [
        f"🃏 {c['name']}",
        "━━━━━━━━━━",
        f"🏷 {cls} / {ctype} / {rarity}　消费 {cost_str}",
    ]

    if c["type"] == 1:  # 从者：进化统一 +2/+2，不逐卡展示数值
        lines.append(f"⚔ 攻击/生命：{c['atk']}/{c['life']}　（进化后 +2/+2）")

    skill_text = _clean_skill_text(c.get("skill_text") or "")
    if skill_text:
        lines.append(f"📜 {skill_text}")

    evo = card.get("evo")
    evo_flavour = (evo.get("flavour_text") or "").strip() if isinstance(evo, dict) else ""
    if evo_flavour:
        lines.append(f"✨ 进化后台词：{evo_flavour}")

    lines.append("━━━━━━━━━━")
    return "\n".join(lines)


def _card_image_url(card: dict) -> str:
    return _IMG_TMPL.format(lang=_LANG_IMG_SEG, hash=card["common"]["card_image_hash"])


def query_random_card():
    """
    随机抽一张卡。返回 (文本, 卡图URL)：
      - 成功：(卡牌信息文本, 卡图URL)
      - 失败：(提示文本, None)
    调用方用 asyncio.to_thread 包装。
    """
    try:
        cards = _get_cards()
    except Exception:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    named = [v for v in cards.values() if v.get("common", {}).get("name")]
    if not named:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    card = random.choice(named)
    text = _format_card(card)
    return text, _card_image_url(card)


def query_card(keyword: str):
    """
    查询入口。返回 (文本, 卡图URL)：
      - 成功：(卡牌信息文本, 卡图URL)
      - 失败：(提示文本, None)
    调用方用 asyncio.to_thread 包装。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return "汝想查哪张卡呀？试试「查卡 骑士」。", None

    try:
        cards = _get_cards()
    except Exception:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    card, hit_count, is_fuzzy = _search(cards, keyword)
    if not card:
        return f"咱没找到「{keyword}」这张卡，换个名字试试？", None

    text = _format_card(card)
    if is_fuzzy:
        text += f"\n（没找到「{keyword}」，这是咱猜汝想查的～）"
    elif hit_count > 1:
        text += f"\n（有 {hit_count} 张同名卡，给汝找的是其中一张～）"

    return text, _card_image_url(card)
