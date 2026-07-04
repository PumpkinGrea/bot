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
import os
import re
import time
import html

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}
_TIMEOUT = 12
# 跨境访问 Steam 常间歇性抖动（连接重置/超时），失败重试几次通常就能救回来
_RETRIES = 3
_RETRY_WAIT = 1.0


def _load_proxy() -> str:
    """
    从 config.yaml 读 steam_proxy（如 http://127.0.0.1:7890）。
    只让 Steam 请求走代理，不依赖 systemd 环境变量（那个作用域坑多）。
    没配则留空 = 直连。读取失败也安静降级为直连。
    """
    try:
        from botpy.ext.cog_yaml import read
        cfg = read(os.path.join(os.path.dirname(__file__), "config.yaml"))
        return (cfg.get("steam_proxy") or "").strip()
    except Exception as e:
        print(f"[Steam] 读取 steam_proxy 失败，按直连处理：{e}")
        return ""


# 复用连接，减少每次重新握手的开销与失败概率
_session = requests.Session()
_session.headers.update(_HEADERS)

# 只给 Steam 请求单独挂代理（若 config.yaml 配了 steam_proxy）。
# 这样智谱/QQ 等国内请求完全不受影响，也不用碰 systemd 环境变量。
_proxy = _load_proxy()
_PROXIES = {"http": _proxy, "https": _proxy} if _proxy else None
if _proxy:
    print(f"[Steam] 已启用 Steam 专用代理：{_proxy}")

# 简单内存缓存：appid -> (结果文本, 封面URL, 时间戳)。同一游戏 10 分钟内不重复查。
_CACHE_TTL = 600
_cache: dict = {}


def _get(url: str, params: dict):
    """带重试的 GET。全部尝试失败才抛出最后一次异常，供上层区分网络失败。"""
    last_err = None
    for attempt in range(1, _RETRIES + 1):
        try:
            resp = _session.get(url, params=params, timeout=_TIMEOUT, proxies=_PROXIES)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            print(f"[Steam] 请求失败(第{attempt}/{_RETRIES}次) {url}: {e}")
            if attempt < _RETRIES:
                time.sleep(_RETRY_WAIT)
    raise last_err


def _strip_html(text: str) -> str:
    """去掉简介里的 HTML 标签，还原实体，压掉多余空白。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _search_appid(name: str):
    """
    按游戏名搜，返回 (appid, 搜索命中项, 错误)：
      - 命中：(appid, item字典, None)  item 含 name/price/tiny_image 等，供降级兜底用
      - 零结果：(None, None, None)
      - 网络异常：(None, None, 错误字符串)
    """
    url = "https://store.steampowered.com/api/storesearch/"
    params = {"term": name, "cc": "cn", "l": "zh"}
    try:
        resp = _get(url, params)
        items = resp.json().get("items") or []
        if items:
            top = items[0]
            return top.get("id"), top, None
        # 请求成功但零结果 → 确实没这游戏（或中文名匹配不上）
        return None, None, None
    except Exception as e:
        print(f"[Steam] 搜索失败 {name}: {e}")
        # 网络/接口异常 → 回传错误，供上层区分"连不上"和"没找到"
        return None, None, str(e)


def _brief_from_search(appid, item) -> tuple:
    """详情拉不下来时，用搜索命中项拼一个简版信息（名字/价格/评分/平台/封面）。"""
    name = item.get("name") or "未知"
    price_node = item.get("price") or {}
    if not price_node:
        price = "免费或暂无价格"
    else:
        final = price_node.get("final")
        initial = price_node.get("initial")
        cur = price_node.get("currency", "CNY")
        symbol = "¥" if cur == "CNY" else ""
        if final is not None:
            price = f"{symbol}{final / 100:.2f}"
            if initial and initial > final:
                disc = round((1 - final / initial) * 100)
                price += f"（原价 {symbol}{initial / 100:.2f}，↓{disc}%）"
        else:
            price = "暂无价格"

    metascore = item.get("metascore")
    meta_str = f"\n📊 Metacritic：{metascore}" if metascore else ""

    plats = item.get("platforms") or {}
    plat_list = [n for n, ok in (("Windows", plats.get("windows")),
                                 ("Mac", plats.get("mac")),
                                 ("Linux", plats.get("linux"))) if ok]
    platform_str = " / ".join(plat_list) or "未知"

    # 用搜索接口返回的真实封面（tiny_image）。别硬拼 header.jpg——有些游戏封面带哈希
    # 子目录，固定拼法会 404，导致 QQ 富媒体下载失败(850026)。
    cover = item.get("tiny_image") or None

    text = (
        f"🎮 {name}\n"
        f"━━━━━━━━━━\n"
        f"💰 国区价格：{price}\n"
        f"👥 当前在线：{{players}}"
        f"{meta_str}\n"
        f"💻 平台：{platform_str}\n"
        f"━━━━━━━━━━\n"
        f"（详情接口这会儿没拉全，先给汝个简版～）\n"
        f"🔗 https://store.steampowered.com/app/{appid}/"
    )
    return text, cover


def _get_player_count(appid) -> int | None:
    """查当前在线人数。失败返回 None（非核心，不影响主流程）。"""
    url = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
    try:
        resp = _get(url, {"appid": appid})
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
    """
    查游戏详情，返回 (文本, 封面URL, 状态)：
      状态 = "ok"          → 成功
             "unavailable" → 接口返回 success:false（多为国区不可售/已下架）
             "network"     → 网络/接口异常（可重试）
    """
    url = "https://store.steampowered.com/api/appdetails"
    params = {"appids": appid, "cc": "cn", "l": "zh"}
    try:
        resp = _get(url, params)
        node = resp.json().get(str(appid)) or {}
        if not node.get("success"):
            return None, None, "unavailable"
        d = node.get("data") or {}
    except Exception as e:
        print(f"[Steam] 详情获取失败 {appid}: {e}")
        return None, None, "network"

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
    return text, cover, "ok"


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

    appid, item, err = _search_appid(name)
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
        text, cover, status = _get_detail(appid)
        if status == "ok":
            _cache[appid] = (text, cover, time.time())
        elif status == "unavailable":
            # 接口明确说这游戏不可售/已下架（多为国区限制），用搜索信息给简版，不缓存
            text, cover = _brief_from_search(appid, item)
        else:
            # 网络问题：详情这一跳没拉下来。用搜索信息兜个简版，别让用户空手而归，不缓存
            print(f"[Steam] 详情拉取失败，降级为搜索简版 {appid}")
            text, cover = _brief_from_search(appid, item)

    # 在线人数是实时数据，每次现查填入占位符（失败只影响这一项，不缓存脏结果）
    players = _get_player_count(appid)
    players_str = f"{players:,} 人" if players is not None else "暂时查不到"
    text = text.replace("{players}", players_str)

    return text, cover
