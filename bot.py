import os
import asyncio

import botpy
from botpy import logging
from botpy.ext.cog_yaml import read
from botpy.message import GroupMessage, C2CMessage

# 功能模块
from fortune import get_fortune          # 今日运势
from ai_module import ai_response        # 智谱 GLM 对话 + 识图
from acg_pic import get_acg_pic          # 随机二次元图片（返回公网 URL）
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
    "  @咱 画图 + 描述 → AI 生成图片（如：画图 戴帽子的猫）\n"
    "  @咱 镜像 + 图片 → 左右对称镜像（支持 GIF）\n"
    "  @咱 幻影坦克 + 2张图 → 黑白背景切换显示\n"
    "🔮 趣味\n"
    "  @咱 今日运势 → 看汝今天的专属运势\n"
    "🎲 小工具\n"
    "  随机数 / 掷骰子 / 抛硬币 / 选择 / 复读 / 在吗\n"
    "━━━━━━━━━━\n"
    "💡 群里要先 @咱 才听得见哦。"
)

HELP_TEXT = (
    "汝想让咱做什么？发个「菜单」看看咱会的全部本事吧。\n"
    "・菜单 / 帮助 —— 看完整说明\n"
    "・今日运势 —— 看汝今天的运势\n"
    "・来张图 / 二次元 —— 随机二次元图片\n"
    "・画图 描述 —— AI 生成图片\n"
    "・随机数 / 掷骰子 / 抛硬币 / 选择 / 复读 / 在吗"
)


# ============================================================
# 纯文本指令：返回字符串则直接回文本；返回 None 表示交给后续图片/AI 逻辑处理
# ============================================================
def handle_text_command(text: str, user_id) -> str | None:
    text = (text or "").strip()
    if not text:
        return None

    parts = text.split()
    cmd = parts[0]
    args = parts[1:]

    if cmd in ("帮助", "help"):
        return HELP_TEXT

    if cmd in ("菜单", "menu"):
        return MENU_TEXT

    if cmd in ("在吗", "ping", "在不在"):
        return "咱一直都在呢，贤狼赫萝在此。"

    if cmd in ("今日运势", "抽签", "运势"):
        return get_fortune(user_id)

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

    async def _send_c2c_image(self, message: C2CMessage, img_url: str, tip: str = ""):
        media = await self.api.post_c2c_file(
            openid=message.author.user_openid,
            file_type=FILE_TYPE_IMAGE,
            url=img_url,
        )
        await message.reply(msg_type=7, media=media, content=tip or " ")

    # ============================================================
    # 统一处理一条消息，返回 None（已自行回复）或文本（由调用方回复）
    # img_urls: 消息里的图片 URL 列表；send_image 决定走群/私聊上传
    # ============================================================
    async def _dispatch(self, message, content: str, session_id, user_id,
                        img_urls: list[str], send_image):
        text = (content or "").strip()
        img_url = img_urls[0] if img_urls else None

        # 1. 纯文本指令
        reply = handle_text_command(text, user_id)
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
            img_gen_url, err = await asyncio.to_thread(get_gpt_draw, draw_prompt)
            if img_gen_url:
                await send_image(message, img_gen_url, "咱给汝画好啦～")
                return None
            return err

        # 6. AI 兜底（文本对话 / 识图）
        ai_reply = await asyncio.to_thread(ai_response, session_id, text, img_url)
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
        except Exception as e:
            _log.error(f"私聊消息处理失败: {e}")
            await message.reply(content="咱这边出了点岔子，稍后再试试吧。")


if __name__ == "__main__":
    # public_messages 意图覆盖：群@消息、C2C私聊消息（QQ机器人最常用）
    intents = botpy.Intents(public_messages=True)
    client = MyClient(intents=intents)
    client.run(appid=config["appid"], secret=config["secret"])
