# Steam 游戏查询模块
# 用户发「查游戏 游戏名」→ 先按名字搜到 appid → 查详情 → 拿实时在线人数 → 汇总。
#
# 用到的都是 Steam 免 key 的公开接口（非官方/内部接口，Valve 不保证稳定、有限流）：
#   1) 搜名字：store.steampowered.com/api/storesearch/?term=xxx&cc=cn&l=zh
#   2) 查详情：store.steampowered.com/api/appdetails?appids=id&cc=cn&l=zh
#   3) 在线数：api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/
#
# 全部同步实现，调用方需用 asyncio.to_thread 包装，避免阻塞 botpy 事件循环。
# 带超时兜底 + 短时缓存，接口偶尔慢/抖动也不至于卡死。
import re
import time
import html

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TIMEOUT = 15

# 简单内存缓存：appid -> (结果文本, 封面URL, 时间戳)。同一游戏 10 分钟内不重复查。
_CACHE_TTL = 600
_cache: dict = {}


def _strip_html(text: str) -> str:
    """去掉简介里的 HTML 标签，还原实体，压掉多余空白。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _search_appid(name: str):
    """按游戏名搜，返回 (appid, 标准名)。搜不到返回 (None, None)。"""
    url = "https://store.steampowered.com/api/storesearch/"
    params = {"term": name, "cc": "cn", "l": "zh"}
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if items:
            top = items[0]
            return top.get("id"), top.get("name"), None
        # 请求成功但零结果 → 确实没这游戏（或中文名匹配不上）
        return None, None, None
    except Exception as e:
        print(f"[Steam] 搜索失败 {name}: {e}")
        # 网络/接口异常 → 回传错误，供上层区分"连不上"和"没找到"
        return None, None, str(e)


def _get_player_count(appid) -> int | None:
    """查当前在线人数。失败返回 None（非核心，不影响主流程）。"""
    url = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
    try:
        resp = requests.get(url, params={"appid": appid}, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("response") or {}
        if data.get("result") == 1:
            return data.get("player_count")
    except Exception as e:
        print(f"[Steam] 在线人数获取失败 {appid}: {e}")
    return None


def _format_price(price_overview) -> str:
    """把 price_overview 字段转成好读的价格文本。"""
    if not price_overview:
        return "暂无价格信息"
    final = price_overview.get("final_formatted") or ""
    discount = price_overview.get("discount_percent") or 0
    if discount > 0:
        initial = price_overview.get("initial_formatted") or ""
        return f"{final}（原价 {initial}，↓{discount}%）"
    return final or "暂无价格信息"


def _get_detail(appid):
    """查游戏详情，返回 (文本, 封面URL)。失败返回 (None, None)。"""
    url = "https://store.steampowered.com/api/appdetails"
    params = {"appids": appid, "cc": "cn", "l": "zh"}
    try:
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        node = resp.json().get(str(appid)) or {}
        if not node.get("success"):
            return None, None
        d = node.get("data") or {}
    except Exception as e:
        print(f"[Steam] 详情获取失败 {appid}: {e}")
        return None, None

    name = d.get("name") or "未知"
    is_free = d.get("is_free")
    price = "免费开玩" if is_free else _format_price(d.get("price_overview"))

    # 类型（游戏/DLC 等）
    app_type = {"game": "游戏", "dlc": "DLC", "demo": "试玩", "music": "原声"}.get(
        d.get("type", ""), d.get("type", ""))

    # 发行日期
    release = (d.get("release_date") or {})
    release_date = "未发售" if release.get("coming_soon") else (release.get("date") or "未知")

    # 开发商 / 发行商
    developers = "、".join(d.get("developers") or []) or "未知"
    publishers = "、".join(d.get("publishers") or []) or "未知"

    # 平台
    plats = d.get("platforms") or {}
    plat_list = [n for n, ok in (("Windows", plats.get("windows")),
                                 ("Mac", plats.get("mac")),
                                 ("Linux", plats.get("linux"))) if ok]
    platform_str = " / ".join(plat_list) or "未知"

    # 类别标签（联机、成就等）与流派（动作、独立等）
    genres = "、".join(g.get("description", "") for g in (d.get("genres") or [])[:5]) or "无"
    categories = "、".join(c.get("description", "") for c in (d.get("categories") or [])[:6]) or "无"

    # 好评描述（有则显示）
    metacritic = d.get("metacritic") or {}
    metacritic_str = f"\n📊 Metacritic：{metacritic.get('score')}" if metacritic.get("score") else ""

    # 简介（去 HTML，截断）
    desc = _strip_html(d.get("short_description") or "")
    if len(desc) > 120:
        desc = desc[:120] + "…"

    # 封面图（jpg，QQ 富媒体可直接拉）
    cover = d.get("header_image") or None

    # 在线人数用占位符 {players}，由 query_game 每次实时填入（不随详情缓存）
    text = (
        f"🎮 {name}\n"
        f"━━━━━━━━━━\n"
        f"🏷 类型：{app_type} / {genres}\n"
        f"💰 国区价格：{price}\n"
        f"👥 当前在线：{{players}}"
        f"{metacritic_str}\n"
        f"📅 发行日期：{release_date}\n"
        f"🛠 开发：{developers}\n"
        f"🏢 发行：{publishers}\n"
        f"💻 平台：{platform_str}\n"
        f"🎯 特性：{categories}\n"
        f"━━━━━━━━━━\n"
        f"📝 {desc or '暂无简介'}\n"
        f"🔗 https://store.steampowered.com/app/{appid}/"
    )
    return text, cover


def query_game(name: str):
    """
    查询入口。返回 (文本, 封面URL)：
      - 成功：(详情文本, 封面URL或None)
      - 失败：(错误提示文本, None)
    调用方用 asyncio.to_thread 包装。
    """
    name = (name or "").strip()
    if not name:
        return "汝想查哪款游戏呀？试试「查游戏 双人成行」。", None

    appid, std_name, err = _search_appid(name)
    if err is not None:
        # 网络/接口层面失败：明说连不上，别误导成"没这游戏"
        return ("咱这会儿连不上 Steam 商店呢，可能是网络不通或超时了，稍后再试试吧。\n"
                "（若部署在服务器上，多半是服务器访问不了 store.steampowered.com）"), None
    if not appid:
        return (f"咱在 Steam 上没找着「{name}」。\n"
                f"Steam 搜索对中文名不太灵，试试用英文原名？"
                f"（如「双人成行」→「It Takes Two」）"), None

    # 详情是静态数据，可缓存；命中缓存则复用，否则新查
    cached = _cache.get(appid)
    if cached and time.time() - cached[2] < _CACHE_TTL:
        text, cover = cached[0], cached[1]
    else:
        text, cover = _get_detail(appid)
        if text is None:
            return f"找着「{std_name or name}」了，可详情咱这会儿拉不下来，稍后再试试吧。", None
        _cache[appid] = (text, cover, time.time())

    # 在线人数是实时数据，每次现查填入占位符（失败只影响这一项，不缓存脏结果）
    players = _get_player_count(appid)
    players_str = f"{players:,} 人" if players is not None else "暂时查不到"
    text = text.replace("{players}", players_str)

    return text, cover
