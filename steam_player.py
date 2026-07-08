# Steam 玩家查询模块
# 用户发「查玩家 <标识>」→ 解析出 SteamID64 → 查资料 + 最近在玩 → 汇总文本 + 头像图。
#
# 「标识」支持三种（Steam 无法按随手起的中文/花名昵称搜人，故只认下面这些唯一标识）：
#   1) SteamID64：17 位数字，如 76561197960287930
#   2) 个人主页链接：steamcommunity.com/id/xxx 或 /profiles/7656...
#   3) 自定义 URL 名：主页 /id/ 后面那段英文 ID（vanity），如 gabelogannewell
#
# 需要 Steam Web API Key（config_secret.py 的 STEAM_API_KEY）。没配则功能关闭。
# 请求复用 steam_info 的带重试 + 代理的 _get（走 config.yaml 的 steam_proxy）。
import re

from steam_info import _get

try:
    from config_secret import STEAM_API_KEY
except ImportError:
    STEAM_API_KEY = ""

# 在线状态码 → 文案
_PERSONA_STATE = {
    0: "离线", 1: "在线", 2: "忙碌", 3: "离开",
    4: "打盹", 5: "想交易", 6: "想玩游戏",
}

# communityvisibilitystate：3=公开，其余基本等于对外不可见
_VISIBLE_PUBLIC = 3

_ID64_RE = re.compile(r"^\d{17}$")
_PROFILE_ID_RE = re.compile(r"steamcommunity\.com/id/([^/\s?#]+)", re.I)
_PROFILE_NUM_RE = re.compile(r"steamcommunity\.com/profiles/(\d{17})", re.I)


def enabled() -> bool:
    """未配 key 时功能关闭。"""
    return bool(STEAM_API_KEY)


def _resolve_vanity(vanity: str):
    """自定义 URL 名 → SteamID64。解析不到返回 None。"""
    url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
    try:
        resp = _get(url, {"key": STEAM_API_KEY, "vanityurl": vanity})
        data = resp.json().get("response") or {}
        if data.get("success") == 1:
            return data.get("steamid")
    except Exception as e:
        print(f"[Steam玩家] 解析 vanity 失败 {vanity}: {e}")
    return None


def _to_steamid64(raw: str):
    """
    把用户输入统一解析成 SteamID64，返回 (steamid64, 错误状态)：
      - 成功：(id64, None)
      - 网络失败：(None, "network")
      - 解析不到：(None, None)
    """
    raw = (raw or "").strip()
    # 1) 直接就是 17 位 ID64
    if _ID64_RE.match(raw):
        return raw, None
    # 2) 链接 /profiles/数字
    m = _PROFILE_NUM_RE.search(raw)
    if m:
        return m.group(1), None
    # 3) 链接 /id/自定义名 → 取出自定义名再解析
    m = _PROFILE_ID_RE.search(raw)
    vanity = m.group(1) if m else raw  # 没链接就把整个输入当自定义名
    try:
        sid = _resolve_vanity(vanity)
    except Exception:
        return None, "network"
    return (sid, None) if sid else (None, None)


def _get_summary(steamid64):
    """查基础资料。返回 dict 或 None。"""
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
    resp = _get(url, {"key": STEAM_API_KEY, "steamids": steamid64})
    players = (resp.json().get("response") or {}).get("players") or []
    return players[0] if players else None


def _get_recent(steamid64):
    """查最近两周在玩。返回列表（可能空）。"""
    url = "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v1/"
    try:
        resp = _get(url, {"key": STEAM_API_KEY, "steamid": steamid64})
        return (resp.json().get("response") or {}).get("games") or []
    except Exception as e:
        print(f"[Steam玩家] 最近在玩获取失败 {steamid64}: {e}")
        return []


def query_player(raw: str):
    """
    查询入口。返回 (文本, 头像URL)：
      - 成功：(资料文本, 头像URL)
      - 失败：(提示文本, None)
    调用方用 asyncio.to_thread 包装。
    """
    raw = (raw or "").strip()
    if not enabled():
        return "查玩家功能还没配好（缺 Steam API Key），先问问管理员吧。", None
    if not raw:
        return ("汝想查谁呀？给咱一个 Steam 标识：\n"
                "・个人主页链接（steamcommunity.com/id/xxx 或 /profiles/数字）\n"
                "・自定义 URL 名（主页 /id/ 后那段英文）\n"
                "・17 位 SteamID64\n"
                "（Steam 查不了随手起的中文昵称哦～）"), None

    steamid64, err = _to_steamid64(raw)
    if err == "network":
        return "咱这会儿连不上 Steam，稍后再试试吧。", None
    if not steamid64:
        return (f"咱没能认出「{raw}」是谁。\n"
                f"试试发个人主页链接、自定义 URL 名或 17 位 SteamID64？\n"
                f"（随手起的中文/花名昵称 Steam 查不到）"), None

    try:
        p = _get_summary(steamid64)
    except Exception as e:
        print(f"[Steam玩家] 资料获取失败 {steamid64}: {e}")
        return "咱这会儿连不上 Steam，稍后再试试吧。", None

    if not p:
        return "查到了这个 ID，但拿不到资料，可能账号已注销或不存在。", None

    name = p.get("personaname") or "未知"
    avatar = p.get("avatarfull") or None
    profile_url = p.get("profileurl") or f"https://steamcommunity.com/profiles/{steamid64}"

    # 资料是否公开
    if p.get("communityvisibilitystate") != _VISIBLE_PUBLIC:
        text = (
            f"👤 {name}\n"
            f"━━━━━━━━━━\n"
            f"这位的资料设成私密啦，咱只能看到名字和头像～\n"
            f"🔗 {profile_url}"
        )
        return text, avatar

    # 在线状态；若正在玩游戏，gameextrainfo 有值
    state = _PERSONA_STATE.get(p.get("personastate", 0), "未知")
    playing = p.get("gameextrainfo")
    status_line = f"🎮 正在玩：{playing}" if playing else f"📶 状态：{state}"

    # 最近在玩（取前 3，playtime 单位分钟）
    recent = _get_recent(steamid64)
    if recent:
        lines = []
        for g in recent[:3]:
            mins = g.get("playtime_2weeks", 0)
            hrs = mins / 60
            lines.append(f"  · {g.get('name', '未知')}（{hrs:.1f} 小时）")
        recent_str = "🕹 最近两周在玩：\n" + "\n".join(lines)
    else:
        recent_str = "🕹 最近两周：没有公开的游玩记录"

    text = (
        f"👤 {name}\n"
        f"━━━━━━━━━━\n"
        f"{status_line}\n"
        f"{recent_str}\n"
        f"━━━━━━━━━━\n"
        f"🔗 {profile_url}"
    )
    return text, avatar
