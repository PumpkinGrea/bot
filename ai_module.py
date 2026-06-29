# 智谱 GLM 对话模块
# 文本走 CHAT_MODEL，带图走 VISION_MODEL（识图）。按会话 ID 隔离上下文记忆。
# 同步实现，调用方需用 asyncio.to_thread 包装，避免阻塞 botpy 事件循环。
import requests
import time
import threading

try:
    from config_secret import ZHIPU_API_KEY
except ImportError:
    ZHIPU_API_KEY = ""

# ===================== 配置区 =====================
CHAT_MODEL = "glm-4.5-air"
VISION_MODEL = "glm-4.6v"
# ==================================================

# 人设：贤狼赫萝。自称「咱」，称对方「汝」，慵懒自负又温柔。
_SYSTEM_PROMPT = (
    "你是约伊兹的贤狼赫萝，一只活了数百年、化作少女模样的狼之化身。"
    "自称『咱』，称呼对方『汝』，说话带着几分慵懒、自负与狡黠，偶尔撒娇、爱吃苹果和蜂蜂蜜酒。"
    "回答简短、口语化、有人情味，不啰嗦也不卖弄学识。遇到不懂的就坦然承认，别装作什么都懂。"
)

chat_memory = {}
global_lock = threading.Lock()
COOLDOWN = 1.2


def ai_response(session_id, user_msg: str, img_url=None) -> str:
    """生成一条 AI 回复。session_id 用于隔离不同会话的上下文记忆。"""
    with global_lock:
        time.sleep(COOLDOWN)

        # 清空对话
        if user_msg.strip() in ["清空", "清空对话", "重置", "忘记"]:
            chat_memory.pop(session_id, None)
            return "✅ 咱已经把方才的话都忘干净啦～"

        # 初始化上下文
        if session_id not in chat_memory:
            chat_memory[session_id] = [
                {"role": "system", "content": _SYSTEM_PROMPT}
            ]

        # 识图时，把历史文字转为图片兼容格式
        if img_url:
            messages = []
            for msg in chat_memory[session_id]:
                if msg["role"] == "system":
                    messages.append(msg)
                else:
                    messages.append({
                        "role": msg["role"],
                        "content": [{"type": "text", "text": msg["content"]}]
                    })
            # 追加当前图片
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_msg or "看看这张图，说说汝的看法。"},
                    {"type": "image_url", "image_url": {"url": img_url}}
                ]
            })
            use_model = VISION_MODEL
        else:
            # 纯文本正常走
            messages = chat_memory[session_id].copy()
            messages.append({"role": "user", "content": user_msg})
            use_model = CHAT_MODEL

        url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        headers = {
            "Authorization": f"Bearer {ZHIPU_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": use_model,
            "messages": messages,
            "temperature": 0.7
        }

        try:
            resp = requests.post(url, json=data, headers=headers, timeout=60)
            resp.raise_for_status()
            result = resp.json()
            reply = result["choices"][0]["message"]["content"].strip()

            # 只保存文字，不保存图片
            chat_memory[session_id].append({"role": "user", "content": user_msg})
            chat_memory[session_id].append({"role": "assistant", "content": reply})

            return reply

        except Exception as e:
            return f"❌ 咱的脑袋有点转不动了：{str(e)}"
