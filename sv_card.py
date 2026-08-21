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
_CLASS_ALIASES = {
    "中": 0, "中立": 0,
    "妖": 1, "精": 1, "妖精": 1, "精灵": 1,
    "皇": 2, "皇家": 2, "皇家护卫": 2,
    "巫": 3, "法": 3, "巫师": 3,
    "龙": 4, "龙族": 4,
    "梦": 5, "梦魇": 5,
    "教": 6, "主": 6, "主教": 6,
    "鱼": 7, "超": 7, "超越": 7, "超越者": 7,
}
_TYPE_NAME = {1: "从者", 2: "护符", 3: "倒计时护符", 4: "法术"}
_RARITY_NAME = {1: "普通", 2: "白银", 3: "黄金", 4: "传说"}
# tribe ID → 中文名（from API tribe_names，tribe 0 忽略）
_TRIBE_NAME = {
    2: "士兵", 3: "鲁米那斯", 4: "雷维翁", 5: "妖精", 6: "亡者",
    8: "土之印", 11: "玛纳利亚", 12: "巨像", 13: "式神",
    14: "创造物", 15: "人偶", 17: "海洋", 18: "财宝",
    19: "侵蚀者", 20: "安纳提玛",
}

_CACHE_TTL = 86400  # 卡池不会频繁变动，一天刷新一次即可
_cache: dict = {"cards": None, "effects": None, "ts": 0}

_AMBIGUOUS_LIST_CAP = 20  # 关键词包含匹配到的不同卡名超过这个数就不逐个列出，只提示范围太广

_session = requests.Session()
_session.headers.update(_HEADERS)

# 富文本标记清洗：<color=xxx>词</color> 只保留文字；<hr> 转成分隔线；
# <ridx=N>...</ridx> 是多选分支，保留内容去标记；<ev>/<sev> 单独处理成前缀
_RE_COLOR = re.compile(r"<color=[^>]*>(.*?)</color>", re.S)
_RE_RIDX = re.compile(r"<ridx=\d+>(.*?)</ridx>", re.S)
_RE_EV = re.compile(r"<ev>(.*?)</ev>", re.S)
_RE_SEV = re.compile(r"<sev>(.*?)</sev>", re.S)
_STAT_QUERY_RE = re.compile(
    r"^(.+?)[\s,，/]+(\d{1,2})[\s,，/]+(\d{1,2})[\s,，/]+(\d{1,2})$"
)


def _clean_skill_text(text: str) -> str:
    """清洗 skill_text 里的富文本标记，转成纯文字，保留换行结构。"""
    if not text:
        return ""
    text = _RE_EV.sub(lambda m: f"\n✨进化时：{m.group(1)}", text)
    text = _RE_SEV.sub(lambda m: f"\n🌟超进化时：{m.group(1)}", text)
    text = _RE_RIDX.sub(lambda m: f"· {m.group(1)}", text)
    text = _RE_COLOR.sub(lambda m: m.group(1), text)
    text = text.replace("<hr>", "\n")
    # 清洗「吟唱_5」「连击_3」这类计数标注 → 吟唱 5 / 连击 3
    text = re.sub(r"([^\x00-\x7f])_(\d+)", r"\1 \2", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _fetch_cards():
    """翻页拉全量卡表 + 特殊效果卡（信仰等）。返回 (cards, effects) 元组。"""
    cards = {}
    effects = {}
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
        page_effects = data.get("specific_effect_card_info") or {}
        if not page_cards and not cards:
            raise RuntimeError("接口返回空卡表")
        cards.update(page_cards)
        effects.update(page_effects)
        offset += _PAGE_SIZE
    return cards, effects


def _get_cards():
    """带缓存地拿全量卡表。返回 (cards, effects) 元组。"""
    now = time.time()
    if _cache["cards"] and now - _cache["ts"] < _CACHE_TTL:
        return _cache["cards"], _cache.get("effects", {})
    try:
        cards, effects = _fetch_cards()
        _cache["cards"] = cards
        _cache["effects"] = effects
        _cache["ts"] = now
        return cards, effects
    except Exception as e:
        print(f"[影之诗] 拉取卡表失败: {e}")
        if _cache["cards"]:
            return _cache["cards"], _cache.get("effects", {})
        raise


def get_card_names(card_ids: list[int]) -> dict[int, str]:
    """Return Chinese card names for the requested official card IDs."""
    requested_ids = set()
    for card_id in card_ids:
        try:
            requested_ids.add(int(card_id))
        except (TypeError, ValueError):
            continue

    if not requested_ids:
        return {}

    cards, _ = _get_cards()
    names = {}
    for card in cards.values():
        common = card.get("common") or {}
        try:
            card_id = int(common.get("card_id"))
        except (TypeError, ValueError):
            continue
        name = common.get("name")
        if card_id in requested_ids and name:
            names[card_id] = name
    return names


def _search(cards: dict, keyword: str):
    """
    按卡名找卡，返回 (命中卡, 同名候选数, 是否为模糊匹配, 歧义候选名列表)：
      - 精确匹配（大小写不敏感）优先命中同名（可能有多个异画版本）
      - 精确匹配没有再试包含匹配：若命中了多个不同名字的卡，视为关键词太宽泛，
        不擅自挑一张，改为返回歧义候选名列表交给上层处理
      - 包含匹配也没有则用相似度找最接近的卡名兜底
      - 同一张卡的多个「异画」版本（card_id 不同但 name 相同）优先选
        card_id == base_card_id 的原画版本
      - 找不到返回 (None, 0, False, None)
    """
    kw = keyword.strip().lower()
    named = [v for v in cards.values() if v.get("common", {}).get("name")]
    is_fuzzy = False

    exact = [v for v in named if v["common"]["name"].lower() == kw]
    if exact:
        candidates = exact
    else:
        contains = [v for v in named if kw in v["common"]["name"].lower()]
        distinct_names = sorted({v["common"]["name"] for v in contains})
        if len(distinct_names) > 1:
            return None, 0, False, distinct_names  # 命中多个不同名字：交给上层列出来，不擅自挑
        candidates = contains

    if not candidates:
        all_names = list({v["common"]["name"] for v in named})
        close = difflib.get_close_matches(kw, [n.lower() for n in all_names], n=1, cutoff=0.4)
        if close:
            matched_name = next(n for n in all_names if n.lower() == close[0])
            candidates = [v for v in named if v["common"]["name"] == matched_name]
            is_fuzzy = True

    if not candidates:
        return None, 0, False, None

    names = {v["common"]["name"] for v in candidates}
    picked = next(
        (v for v in candidates if v["common"]["card_id"] == v["common"]["base_card_id"]),
        candidates[0],
    )
    return picked, len(names), is_fuzzy, None


def _parse_stat_query(keyword: str) -> tuple[int, int, int, int] | None:
    """Parse class + cost/attack/life, such as 皇221 or 皇家护卫 10 2 1."""
    compact = keyword.strip().replace(" ", "")
    for alias in sorted(_CLASS_ALIASES, key=len, reverse=True):
        if compact.startswith(alias):
            stats = compact[len(alias):]
            if len(stats) == 3 and stats.isdigit():
                return _CLASS_ALIASES[alias], *(int(value) for value in stats)

    match = _STAT_QUERY_RE.fullmatch(keyword.strip())
    if not match:
        return None
    class_alias, cost, attack, life = match.groups()
    class_id = _CLASS_ALIASES.get(class_alias.strip())
    if class_id is None:
        return None
    return class_id, int(cost), int(attack), int(life)


def _query_cards_by_stats(cards: dict, stat_query: tuple[int, int, int, int]) -> str:
    class_id, cost, attack, life = stat_query
    matches = []
    seen_base_ids = set()
    for card in cards.values():
        common = card.get("common") or {}
        if (
            common.get("class") != class_id
            or common.get("type") != 1
            or common.get("cost") != cost
            or common.get("atk") != attack
            or common.get("life") != life
            or not common.get("name")
        ):
            continue
        base_id = common.get("base_card_id") or common.get("card_id")
        if base_id in seen_base_ids:
            continue
        seen_base_ids.add(base_id)
        matches.append(common)

    class_name = _CLASS_NAME[class_id]
    conditions = f"{class_name} · {cost}费 · {attack}/{life}"
    if not matches:
        return f"咱没找到 {conditions} 的从者。"

    matches.sort(key=lambda common: common["name"])
    lines = [f"{conditions} 从者", f"共找到 {len(matches)} 张："]
    for common in matches:
        rarity = _RARITY_NAME.get(common.get("rarity"), "未知")
        lines.append(f"・{common['name']} · {rarity}")
    lines.append("可继续用「查卡 卡名」查看卡图和效果。")
    return "\n".join(lines)


def _format_card(card: dict, specific_effects: dict = None) -> str:
    c = card["common"]
    cls = _CLASS_NAME.get(c["class"], "未知")
    ctype = _TYPE_NAME.get(c["type"], "未知")
    rarity = _RARITY_NAME.get(c["rarity"], "未知")
    cost = c.get("cost", 0)
    cost_str = str(cost) if cost is not None and cost >= 0 else "-"
    name = c["name"]

    # ╭─ 标题行 ─╮
    lines = [f"╭─ {name} {cost_str}费 ─╮"]

    # 属性行：职业·类型·稀有度  |  攻/命  种族
    meta_parts = [f"{cls}·{ctype}·{rarity}"]
    extras = []
    if c["type"] == 1:  # 从者
        extras.append(f"{c['atk']}/{c['life']}")
    tribes = c.get("tribes") or []
    named_tribes = [_TRIBE_NAME.get(t) for t in tribes if _TRIBE_NAME.get(t)]
    if named_tribes:
        extras.append("/".join(named_tribes))
    if extras:
        meta_parts.append("  ".join(extras))
    lines.append("  " + "  |  ".join(meta_parts))

    # 空行分隔
    lines.append("")

    # 能力文本
    skill_text = _clean_skill_text(c.get("skill_text") or "")
    if skill_text:
        lines.append(skill_text)
        lines.append("")

    # 特殊效果（信仰等）
    if specific_effects:
        effect_card_id = str(c["card_id"] + 2)
        eff = specific_effects.get(effect_card_id)
        if eff:
            eff_text = _clean_skill_text(eff.get("skill_text", ""))
            if eff_text:
                # 提取效果名：取第一行作为标题
                eff_lines = eff_text.split("\n")
                eff_title = eff_lines[0].rstrip("。")
                eff_body = "\n".join(eff_lines[1:]).strip()
                lines.append(f"✦ {eff_title}")
                if eff_body:
                    lines.append(eff_body)
                lines.append("")

    # 背景故事
    evo = card.get("evo")
    evo_flavour = (evo.get("flavour_text") or "").strip() if isinstance(evo, dict) else ""
    if evo_flavour:
        flav = evo_flavour.replace("\n", "  ")
        if len(flav) > 60:
            flav = flav[:57] + "..."
        lines.append(f"· {flav}")

    return "\n".join(lines).strip()


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
        cards, effects = _get_cards()
    except Exception:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    named = [v for v in cards.values() if v.get("common", {}).get("name")]
    if not named:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    card = random.choice(named)
    text = _format_card(card, effects)
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
        cards, effects = _get_cards()
    except Exception:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    stat_query = _parse_stat_query(keyword)
    if stat_query:
        return _query_cards_by_stats(cards, stat_query), None

    card, hit_count, is_fuzzy, ambiguous_names = _search(cards, keyword)

    if ambiguous_names is not None:
        if len(ambiguous_names) > _AMBIGUOUS_LIST_CAP:
            return f"「{keyword}」匹配到的卡太多了（{len(ambiguous_names)} 张），换个更精确的名字试试？", None
        names_str = "、".join(ambiguous_names)
        return f"「{keyword}」匹配到 {len(ambiguous_names)} 张卡，说得更精确点呀：\n{names_str}", None

    if not card:
        return f"咱没找到「{keyword}」这张卡，换个名字试试？", None

    text = _format_card(card, effects)
    if is_fuzzy:
        text += f"\n（没找到「{keyword}」，这是咱猜汝想查的～）"
    elif hit_count > 1:
        text += f"\n（有 {hit_count} 张同名卡，给汝找的是其中一张～）"

    return text, _card_image_url(card)
