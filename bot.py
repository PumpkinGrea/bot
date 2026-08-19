import os
import asyncio

import botpy
from botpy import logging
from botpy.ext.cog_yaml import read
from botpy.message import GroupMessage, C2CMessage
from botpy.interaction import Interaction

# 功能模块
from fortune import get_fortune          # 今日运势
from ai_module import ai_response        # DeepSeek text conversation
from acg_pic import get_acg_pic          # 随机二次元图片（返回公网 URL）
from steam_info import query_game         # Steam 游戏查询（返回文本 + 封面 URL）
from steam_player import query_player      # Steam 玩家查询（返回文本 + 头像 URL）
from sv_card import query_card, query_random_card  # 影之诗超凡世界 卡牌查询（返回文本 + 卡图 URL）
from sv_deck import query_tier_list, query_top_decks  # SVWB Meta 卡组数据
from gpt_draw import get_gpt_draw        # AI 生图（返回公网 URL）
from pic_handle import make_mirror, make_phantom_tank  # 镜像 / 幻影坦克（返回图片字节）
from image_host import ImageHost          # 本地图片服务，把本地图变公网 URL

# 读取同目录下的 config.yaml
config = read(os.path.join(os.path.dirname(__file__), "config.yaml"))

_log = logging.get_logger()

# 本地图片服务（镜像/幻影坦克用）。未配 img_public_base 时自动降级、不影响其它功能。
image_host = ImageHost(
    public_base=config.get("img_public_base", ""),
    host=config.get("img_host", "0.0.0.0"),
    port=config.get("img_port", 9900),
)

# 富媒体类型：1 图片 png/jpg
FILE_TYPE_IMAGE = 1

MENU_TEXT = (
    "🐺 贤狼赫萝的本事 🐺\n"
    "━━━━━━━━━━\n"
    "🗣 聊天\n"
    "  @咱 + 文字 → 直接和咱说话，咱记得上下文\n"
    "  @咱 + 图片 → 咱看图说话（识图）\n"
    "  @咱 清空对话 → 让咱忘掉之前的话\n"
    "🎨 图片\n"
    "  @咱 来张图 / 二次元 → 随机二次元图片\n"
    "  @咱 画图 + 描述 + 图片 → AI 生成图片（如：画图 戴帽子的猫）\n"
    "  @咱 镜像 + 图片 → 左右对称镜像（支持 GIF）\n"
    "  @咱 幻影坦克 + 2张图 → 黑白背景切换显示\n"
    "🔮 趣味\n"
    "  @咱 今日运势 → 看汝今天的专属运势\n"
    "  @咱 查游戏 + 游戏名 → 查 Steam 游戏价格/在线/简介\n"
    "  @咱 查玩家 + 主页链接/ID → 查 Steam 玩家资料\n"
    "  @咱 查卡 + 卡名 → 查影之诗·超凡世界的卡牌信息\n"
    "  @咱 查卡组 + 轮换/无限/卡组类型 → 查 SVWB Meta 高分构筑\n"
    "  @咱 卡组梯度 + 轮换/无限 → 查 SVWB Meta 卡组梯度表\n"
    "  @咱 随机卡 → 随机抽一张影之诗卡牌\n"
    "🎲 小工具\n"
    "  随机数 / 掷骰子 / 抛硬币 / 选择 / 复读 / 在吗\n"
    "━━━━━━━━━━\n"
    "💡 群里要先 @咱 才听得见哦。"
)

HELP_TEXT = (
    "汝想让咱做什么？发个「菜单」看看咱会的全部本事吧。\n"
    "・菜单 / 帮助 —— 看完整说明\n"
    "・今日运势 —— 看汝今天的运势\n"
    "・查游戏 游戏名 —— 查 Steam 游戏信息（如「查游戏 双人成行」）\n"
    "・查玩家 主页链接/ID —— 查 Steam 玩家资料\n"
    "・查卡 卡名 —— 查影之诗·超凡世界卡牌（如「查卡 哥布林」）\n"
    "・查卡组 [轮换/无限] [卡组类型] —— 查 SVWB Meta 高分构筑（如「查卡组 天晶法」）\n"
    "・卡组梯度 [轮换/无限] —— 查 SVWB Meta 卡组梯度表\n"
    "・随机卡 —— 随机抽一张影之诗卡牌\n"
    "・来张图 / 二次元 —— 随机二次元图片\n"
    "・画图 描述 + 图片 —— AI 生成图片（可带参考图）\n"
    "・随机数 / 掷骰子 / 抛硬币 / 选择 / 复读 / 在吗"
)


# ============================================================
# 内联键盘菜单
# 官方文档：https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html
# keyboard 结构：{content: {rows: [...]}}  按钮用 action.type=2（指令按钮）
# ============================================================
def _build_menu_keyboard():
    """构建菜单内联键盘。指令按钮（type=2）点击后在输入框填入 @bot 命令。
    enter=true → 自动发送；enter=false → 让用户补完参数。"""

    def _btn(btn_id: str, label: str, data: str, enter: bool = True, style: int = 0):
        return {
            "id": btn_id,
            "render_data": {"label": label, "style": style},
            "action": {
                "type": 2,            # 指令按钮：在输入框填入 @bot data
                "permission": {"type": 2},  # 2 = 所有人可点
                "data": data,
                "enter": enter,       # true = 自动发送，false = 等用户补完
            },
        }

    # style: 0=灰线框 1=蓝线框 2=白字 3=蓝底白字
    return {
        "content": {
            "rows": [
                {"buttons": [
                    _btn("btn_fortune", "🔮 运势", "今日运势", style=3),
                    _btn("btn_acg", "🖼 来张图", "来张图", style=3),
                    _btn("btn_draw", "🎨 画图", "画图 ", enter=False, style=1),
                ]},
                {"buttons": [
                    _btn("btn_game", "🎮 查游戏", "查游戏 ", enter=False),
                    _btn("btn_player", "👤 查玩家", "查玩家 ", enter=False),
                ]},
                {"buttons": [
                    _btn("btn_card", "🃏 查卡", "查卡 ", enter=False),
                    _btn("btn_deck", "🏆 查卡组", "查卡组 ", enter=False),
                    _btn("btn_tier", "📊 卡组梯度", "卡组梯度 ", enter=False),
                ]},
                {"buttons": [
                    _btn("btn_randcard", "🎴 随机卡", "随机卡", style=1),
                    _btn("btn_random", "🎯 随机数", "随机数"),
                    _btn("btn_dice", "🎲 掷骰子", "掷骰子"),
                ]},
                {"buttons": [
                    _btn("btn_coin", "🪙 抛硬币", "抛硬币"),
                    _btn("btn_help", "📋 帮助", "帮助", style=1),
                ]},
            ]
        }
    }


MENU_KEYBOARD = _build_menu_keyboard()

# ============================================================
# 纯文本指令：返回字符串则直接回文本；返回 None 表示交给后续图片/AI 逻辑处理
# ============================================================
def handle_text_command(text: str) -> str | None:
    text = (text or "").strip()
    if not text:
        return None

    parts = text.split()
    cmd = parts[0]
    args = parts[1:]

    if cmd in ("在吗", "ping", "在不在"):
        return "咱一直都在呢，贤狼赫萝在此。"

    if cmd in ("随机数", "random"):
        import random
        lo, hi = 1, 100
        try:
            if len(args) == 1:
                hi = int(args[0])
            elif len(args) >= 2:
                lo, hi = int(args[0]), int(args[1])
        except ValueError:
            return "范围得是整数呀，比如「随机数 1 100」。"
        if lo > hi:
            lo, hi = hi, lo
        return f"咱给汝掷出了 {random.randint(lo, hi)}（范围 {lo}~{hi}）。"

    if cmd in ("掷骰子", "骰子", "roll"):
        import random
        faces = 6
        if args:
            try:
                faces = int(args[0])
            except ValueError:
                return "面数得是整数呀，比如「掷骰子 20」。"
        if faces < 2:
            return "这骰子至少得有 2 面吧？"
        return f"🎲 {faces} 面骰子，掷出了 {random.randint(1, faces)}。"

    if cmd in ("抛硬币", "硬币", "coin"):
        import random
        return "🪙 " + random.choice(["正面！", "反面！"])

    if cmd in ("选择", "选", "choice"):
        import random
        if len(args) < 2:
            return "至少给咱两个选项呀，比如「选择 苹果 蜂蜜酒」。"
        return f"咱帮汝选：{random.choice(args)}"

    if cmd in ("复读", "echo"):
        rest = text[len(cmd):].strip()
        return rest if rest else "汝要咱复读什么呢？"

    # 没匹配到指令 → 交给图片/AI 逻辑
    return None


def _normalize_url(url: str) -> str:
    """官方返回的图片 url 可能缺协议头，补全为 https。"""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return "https://" + url


def _all_image_urls(attachments) -> list[str]:
    """取消息附件里所有图片的 URL（幻影坦克需要 2 张）。"""
    urls = []
    for att in attachments or []:
        ctype = att.content_type or ""
        url = att.url
        if url and ("image" in ctype or att.height):
            urls.append(_normalize_url(url))
    return urls


class MyClient(botpy.Client):
    async def on_ready(self):
        await image_host.start()
        _log.info(f"机器人 「{self.robot.name}」 已上线，可以开始接收消息了")

    # ---------- 富媒体：上传图片 URL 拿到 file_info，再发出去 ----------
    async def _send_group_image(self, message: GroupMessage, img_url: str, tip: str = ""):
        media = await self.api.post_group_file(
            group_openid=message.group_openid,
            file_type=FILE_TYPE_IMAGE,
            url=img_url,
        )
        await message.reply(msg_type=7, media=media, content=tip or " ")
        _log.info("群回复(图) | 群=%s 图=%s 附言=%r",
                  message.group_openid, img_url, tip)

    async def _send_c2c_image(self, message: C2CMessage, img_url: str, tip: str = ""):
        media = await self.api.post_c2c_file(
            openid=message.author.user_openid,
            file_type=FILE_TYPE_IMAGE,
            url=img_url,
        )
        await message.reply(msg_type=7, media=media, content=tip or " ")
        _log.info("私聊回复(图) | 用户=%s 图=%s 附言=%r",
                  message.author.user_openid, img_url, tip)

    # ---------- 键盘消息 ----------
    async def _send_group_keyboard(self, group_openid: str, msg_id: str,
                                    content: str, keyboard: dict = None):
        if keyboard is None:
            keyboard = MENU_KEYBOARD
        await self.api.post_group_message(
            group_openid=group_openid,
            msg_type=2,
            markdown={"content": content},
            keyboard=keyboard,
            msg_id=msg_id,
        )
        _log.info("群回复(键盘) | 群=%s", group_openid)

    async def _send_c2c_keyboard(self, openid: str, msg_id: str,
                                  content: str, keyboard: dict = None):
        if keyboard is None:
            keyboard = MENU_KEYBOARD
        await self.api.post_c2c_message(
            openid=openid,
            msg_type=2,
            markdown={"content": content},
            keyboard=keyboard,
            msg_id=msg_id,
        )
        _log.info("私聊回复(键盘) | 用户=%s", openid)

    # ---------- 按钮回调（type=1 回调按钮用；当前菜单用 type=2 指令按钮，不走这里）----------
    async def on_interaction_create(self, interaction: Interaction):
        btn_data = (interaction.data.resolved.button_data or "").strip()
        _log.info("按钮回调 | btn=%s data=%r",
                  interaction.data.resolved.button_id, btn_data)
        await self.api.on_interaction_result(interaction.id, code=0)

    # ============================================================
    # 统一处理一条消息，返回 None（已自行回复）或文本（由调用方回复）
    # img_urls: 消息里的图片 URL 列表；send_image 决定走群/私聊上传
    # ============================================================
    async def _dispatch(self, message, content: str, session_id, user_id,
                        img_urls: list[str], send_image):
        text = (content or "").strip()
        img_url = img_urls[0] if img_urls else None

        # 0. 菜单 / 帮助：发送内联键盘
        if text in ("菜单", "menu", "帮助", "help"):
            keyboard_text = (
                "🐺 贤狼赫萝的本事 🐺\n点下面的按钮就行啦～"
                if text in ("菜单", "menu")
                else HELP_TEXT
            )
            if isinstance(message, GroupMessage):
                await self._send_group_keyboard(
                    message.group_openid, message.id, keyboard_text, MENU_KEYBOARD)
            else:
                await self._send_c2c_keyboard(
                    message.author.user_openid, message.id, keyboard_text, MENU_KEYBOARD)
            return None

        # 1. 今日运势：文字 + 附一张随机二次元图（取图失败则只发文字）
        if text in ("今日运势", "抽签", "运势"):
            fortune_text = get_fortune(user_id)
            pic_url = await asyncio.to_thread(get_acg_pic)
            if pic_url:
                await send_image(message, pic_url, fortune_text)
                return None
            return fortune_text

        # 1. 纯文本指令
        reply = handle_text_command(text)
        if reply is not None:
            return reply

        # 2. 镜像：需带图。本地生成字节 → 图床 → 发送
        if "镜像" in text and img_url:
            if not image_host.enabled:
                return "镜像功能要先配好图片服务（img_public_base）才能用哦。"
            result = await asyncio.to_thread(make_mirror, img_url)
            if not result:
                return "这张图咱处理不了，换一张试试吧。"
            img_bytes, fname = result
            pub_url = image_host.publish(img_bytes, fname)
            await send_image(message, pub_url, "镜像好啦～")
            return None

        # 3. 幻影坦克：需 2 张图
        if "幻影坦克" in text:
            if len(img_urls) < 2:
                return "幻影坦克要两张图哦：@咱 幻影坦克，并一起发两张图片。"
            if not image_host.enabled:
                return "幻影坦克要先配好图片服务（img_public_base）才能用哦。"
            result = await asyncio.to_thread(make_phantom_tank, img_urls[0], img_urls[1])
            if not result:
                return "这两张图咱合不出来，换换试试吧。"
            img_bytes, fname = result
            pub_url = image_host.publish(img_bytes, fname)
            await send_image(message, pub_url, "幻影坦克来啦，点开看看～")
            return None

        # 3.5 Steam 游戏查询：「查游戏 游戏名」，返回详情文本 + 封面图
        if text.startswith("查游戏"):
            game_name = text[len("查游戏"):].strip()
            info_text, cover_url = await asyncio.to_thread(query_game, game_name)
            if cover_url:
                await send_image(message, cover_url, info_text)
                return None
            return info_text

        # 3.6 Steam 玩家查询：「查玩家 <主页链接/自定义名/ID64>」，返回资料 + 头像图
        if text.startswith("查玩家"):
            player_id = text[len("查玩家"):].strip()
            info_text, avatar_url = await asyncio.to_thread(query_player, player_id)
            if avatar_url:
                await send_image(message, avatar_url, info_text)
                return None
            return info_text

        # 3.7 影之诗超凡世界 卡牌查询：「查卡 卡名」，返回卡牌信息 + 卡图
        if text.startswith("查卡"):
            card_name = text[len("查卡"):].strip()
            info_text, img_url_card = await asyncio.to_thread(query_card, card_name)
            if img_url_card:
                await send_image(message, img_url_card, info_text)
                return None
            return info_text

        # 3.8 SVWB Meta 高分卡组：「查卡组 [轮换/无限] [卡组类型]」
        if text.startswith("高分卡组") or text.startswith("查卡组"):
            prefix = "高分卡组" if text.startswith("高分卡组") else "查卡组"
            deck_query = text[len(prefix):].strip()
            return await asyncio.to_thread(query_top_decks, deck_query)

        # 3.9 SVWB Meta 卡组梯度：「卡组梯度 [轮换/无限]」
        if text.startswith("卡组梯度") or text.startswith("梯度表"):
            prefix = "卡组梯度" if text.startswith("卡组梯度") else "梯度表"
            tier_query = text[len(prefix):].strip()
            return await asyncio.to_thread(query_tier_list, tier_query)

        # 3.10 影之诗超凡世界 随机抽卡：「随机卡」，返回卡牌信息 + 卡图
        if text in ("随机卡", "抽卡"):
            info_text, img_url_card = await asyncio.to_thread(query_random_card)
            if img_url_card:
                await send_image(message, img_url_card, info_text)
                return None
            return info_text

        # 4. 随机二次元图片
        if "来张图" in text or "二次元" in text:
            pic_url = await asyncio.to_thread(get_acg_pic)
            if pic_url:
                await send_image(message, pic_url, "汝要的图来啦～")
                return None
            return "呜，图库暂时连不上，待会再试试吧。"

        # 5. AI 生图：以「画图」开头
        if text.startswith("画图"):
            draw_prompt = text[2:].strip()
            img_gen_url, err = await asyncio.to_thread(get_gpt_draw, draw_prompt, img_urls)
            if img_gen_url:
                await send_image(message, img_gen_url, "咱给汝画好啦～")
                return None
            return err

        # 6. AI fallback: text conversation only
        if img_urls and not text:
            return "咱现在只支持文字聊天，发句话再来找咱吧。"
        ai_reply = await asyncio.to_thread(ai_response, session_id, text)
        return ai_reply

    # ========== 群聊：用户 @ 机器人时触发 ==========
    async def on_group_at_message_create(self, message: GroupMessage):
        img_urls = _all_image_urls(message.attachments)
        session_id = message.group_openid
        user_id = message.author.member_openid
        _log.info("群消息 | 群=%s 用户=%s 内容=%r 图=%d",
                  session_id, user_id, (message.content or "").strip(), len(img_urls))
        try:
            reply = await self._dispatch(
                message, message.content, session_id, user_id,
                img_urls, self._send_group_image,
            )
            if reply:
                await message.reply(content=reply)
                _log.info("群回复(文) | 群=%s 内容=%r", session_id, reply)
        except Exception as e:
            _log.error(f"群消息处理失败: {e}")
            await message.reply(content="咱这边出了点岔子，稍后再试试吧。")

    # ========== 单聊（C2C 私聊）：需在开放平台单独开通权限 ==========
    async def on_c2c_message_create(self, message: C2CMessage):
        img_urls = _all_image_urls(message.attachments)
        session_id = f"c2c-{message.author.user_openid}"
        user_id = message.author.user_openid
        _log.info("私聊消息 | 用户=%s 内容=%r 图=%d",
                  user_id, (message.content or "").strip(), len(img_urls))
        try:
            reply = await self._dispatch(
                message, message.content, session_id, user_id,
                img_urls, self._send_c2c_image,
            )
            if reply:
                await message.reply(content=reply)
                _log.info("私聊回复(文) | 用户=%s 内容=%r", user_id, reply)
        except Exception as e:
            _log.error(f"私聊消息处理失败: {e}")
            await message.reply(content="咱这边出了点岔子，稍后再试试吧。")


if __name__ == "__main__":
    # public_messages 意图覆盖：群@消息、C2C私聊消息
    # interaction 意图：接收内联键盘按钮点击回调
    intents = botpy.Intents(public_messages=True, interaction=True)
    client = MyClient(intents=intents)
    client.run(appid=config["appid"], secret=config["secret"])
