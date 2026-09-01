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
# Keep answers substantially longer than the previous brief-response limit.
# The provider still requires an explicit ceiling, so this cannot be unlimited.
MAX_TOKENS = 4096
REQUEST_TIMEOUT = 120
COOLDOWN = 1.2

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
            return "已清空本次对话记录。"

        if not DEEPSEEK_API_KEY:
            return "对话服务尚未配置，请检查 API Key。"

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
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": 0.7,
        }

        try:
            resp = requests.post(url, json=data, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            reply = _reply_text(resp.json())
            chat_memory[session_id].append({"role": "user", "content": user_msg})
            chat_memory[session_id].append({"role": "assistant", "content": reply})
            return reply
        except Exception as e:
            return f"对话服务请求失败：{e}"
