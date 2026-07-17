# 影之诗·超凡世界 卡牌查询模块
# 用户发「查卡 卡名」→ 从内存缓存的全卡表里按名字匹配 → 汇总文本 + 卡图 URL。
#
# 数据来自官方公开接口（免 key，社区文档:
# https://gist.github.com/theabhishek2511/dfd54989013254324cc4d67f1dbc9f7f）：
#   GET https://shadowverse-portal.com/api/v1/cards?format=json&lang=zh-tw
# 该接口一次性返回全部卡牌（约 6000 张，无搜索/分页参数），故本地缓存，避免每次查询都拉全量。
#
# 卡图直链（同域名，无需下载转发，可直接交给 QQ 富媒体上传）：
#   https://shadowverse-portal.com/image/card/phase2/common/C/C_{card_id}.png
# 进化图（.../E/E_{card_id}.png）对无进化形态的卡（法术/护符）会返回错误页，故统一只用基础图。
import difflib
import random
import time

import requests
from zhconv import convert

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TIMEOUT = 15
_CARDS_URL = "https://shadowverse-portal.com/api/v1/cards"
_IMG_TMPL = "https://shadowverse-portal.com/image/card/phase2/common/C/C_{}.png"

_CLAN_NAME = {
    0: "无属性", 1: "精灵", 2: "皇家护卫", 3: "法师",
    4: "龙族", 5: "暗影", 6: "主教", 7: "次元", 8: "吸血鬼",
}
_TYPE_NAME = {1: "从者", 2: "护符", 3: "倒计时护符", 4: "法术"}
_RARITY_NAME = {1: "铜卡", 2: "银卡", 3: "金卡", 4: "虹卡"}

_CACHE_TTL = 86400  # 卡池不会频繁变动，一天刷新一次即可
_cache: dict = {"cards": None, "ts": 0}

_session = requests.Session()
_session.headers.update(_HEADERS)


def _fetch_cards():
    """拉全量卡表。返回卡牌列表，失败抛异常交给上层处理。"""
    resp = _session.get(_CARDS_URL, params={"format": "json", "lang": "zh-tw"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    cards = data.get("cards") or []
    if not cards:
        raise RuntimeError("接口返回空卡表")
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


def _search(cards, keyword: str):
    """
    按卡名找卡，返回 (命中卡, 同名候选数, 是否为模糊匹配)：
      - 精确匹配（大小写不敏感）优先；再试包含匹配；都没有则用相似度找最接近的卡名
      - 同一张卡可能有多个「异画」版本（card_id 不同但 card_name 相同），
        优先选 card_id == base_card_id 的原画版本
      - 找不到返回 (None, 0, False)
    """
    # 卡表只有繁体中文（游戏本身无简中服），转繁体后再匹配，让简体输入也能查到
    kw = convert(keyword.strip(), "zh-tw").lower()
    named = [c for c in cards if c.get("card_name")]  # 过滤掉未实装/占位卡（card_name 为空）
    is_fuzzy = False

    exact = [c for c in named if c["card_name"].lower() == kw]
    candidates = exact if exact else [c for c in named if kw in c["card_name"].lower()]

    if not candidates:
        # 精确/包含都没命中：按字符相似度找最接近的卡名，兜底错字、漏字、字序问题
        all_names = list({c["card_name"] for c in named})
        close = difflib.get_close_matches(kw, [n.lower() for n in all_names], n=1, cutoff=0.4)
        if close:
            matched_name = next(n for n in all_names if n.lower() == close[0])
            candidates = [c for c in named if c["card_name"] == matched_name]
            is_fuzzy = True

    if not candidates:
        return None, 0, False

    names = {c["card_name"] for c in candidates}
    # 同名去重：优先原画版本
    picked = next((c for c in candidates if c["card_id"] == c["base_card_id"]), candidates[0])
    return picked, len(names), is_fuzzy


def _format_card(c: dict) -> str:
    clan = _CLAN_NAME.get(c["clan"], "未知")
    ctype = _TYPE_NAME.get(c["char_type"], "未知")
    rarity = _RARITY_NAME.get(c["rarity"], "未知")
    cost = c.get("cost", 0)
    cost_str = str(cost) if cost is not None and cost >= 0 else "-"

    # 数据源只有繁体，技能描述专有名词多，转简体易出错就不转；
    # 卡名相对简单，转成简体方便阅读
    name_cn = convert(c["card_name"], "zh-cn")

    lines = [
        f"🃏 {name_cn}",
        "━━━━━━━━━━",
        f"🏷 {clan} / {ctype} / {rarity}　消费 {cost_str}",
    ]

    if c["char_type"] == 1:  # 从者：有基础/进化两组数值
        lines.append(f"⚔ 攻击/生命：{c['atk']}/{c['life']}"
                     f"　→ 进化后 {c['evo_atk']}/{c['evo_life']}")

    skill_disc = (c.get("skill_disc") or "").replace("<br>", "\n")
    if skill_disc:
        lines.append(f"📜 {skill_disc}")

    evo_skill_disc = (c.get("evo_skill_disc") or "").replace("<br>", "\n")
    if evo_skill_disc:
        lines.append(f"✨ 进化后：{evo_skill_disc}")

    lines.append("━━━━━━━━━━")
    lines.append(f"🔗 https://shadowverse-portal.com/card/{c['card_id']}")
    return "\n".join(lines)


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

    named = [c for c in cards if c.get("card_name")]  # 过滤掉未实装/占位卡
    if not named:
        return "咱这会儿连不上卡牌数据库，稍后再试试吧。", None

    card = random.choice(named)
    text = _format_card(card)
    img_url = _IMG_TMPL.format(card["card_id"])
    return text, img_url


def query_card(keyword: str):
    """
    查询入口。返回 (文本, 卡图URL)：
      - 成功：(卡牌信息文本, 卡图URL)
      - 失败：(提示文本, None)
    调用方用 asyncio.to_thread 包装。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return "汝想查哪张卡呀？试试「查卡 漫游的哥布林」。", None

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

    img_url = _IMG_TMPL.format(card["card_id"])
    return text, img_url
