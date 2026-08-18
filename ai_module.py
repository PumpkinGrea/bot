# DeepSeek chat module through the configured Anthropic-compatible relay.
# Text conversations retain per-session memory. deepseek-v4-flash is used for
# every request; image understanding is intentionally unavailable for this model.
import threading
import time

import requests

try:
    from config_secret import DEEPSEEK_API_KEY
except ImportError:
    DEEPSEEK_API_KEY = ""


DEEPSEEK_BASE_URL = "https://www.rightapi.ai/deepseek/anthropic"
CHAT_MODEL = "deepseek-v4-flash"
MAX_TOKENS = 1024
COOLDOWN = 1.2

_SYSTEM_PROMPT = (
    "你是约伊兹的贤狼赫萝，一只活了数百年、化作少女模样的狼之化身。"
    "自称“咱”，称呼对方“汝”，说话带着几分慵懒、自负与狡黠，偶尔撒娇，"
    "爱吃苹果和蜂蜜酒。"
    "回答口语化、有人情味，不说教也不卖弄学识。"
    "遇到不懂的就坦然承认，别装作什么都懂。"
)

chat_memory = {}
global_lock = threading.Lock()


def _reply_text(response: dict) -> str:
    """Extract all text blocks from an Anthropic Messages API response."""
    parts = [
        block.get("text", "")
        for block in response.get("content", [])
        if block.get("type") == "text"
    ]
    reply = "".join(parts).strip()
    if not reply:
        raise ValueError("中转服务没有返回文本内容")
    return reply


def ai_response(session_id, user_msg: str) -> str:
    """Generate one text reply and preserve independent per-session context."""
    with global_lock:
        time.sleep(COOLDOWN)

        if user_msg.strip() in ["清空", "清空对话", "重置", "忘记"]:
            chat_memory.pop(session_id, None)
            return "好，咱已经把方才的话都忘干净啦～"

        if not DEEPSEEK_API_KEY:
            return "咱还没拿到对话服务的钥匙，先让管理员检查配置吧。"

        if session_id not in chat_memory:
            chat_memory[session_id] = []

        messages = chat_memory[session_id].copy()
        messages.append({"role": "user", "content": user_msg})
        url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/v1/messages"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        data = {
            "model": CHAT_MODEL,
            "system": _SYSTEM_PROMPT,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": 0.7,
        }

        try:
            resp = requests.post(url, json=data, headers=headers, timeout=60)
            resp.raise_for_status()
            reply = _reply_text(resp.json())
            chat_memory[session_id].append({"role": "user", "content": user_msg})
            chat_memory[session_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            return f"咱的脑袋有点转不动了：{e}"
