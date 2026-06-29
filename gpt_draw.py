# GPT 生图模块（官方平台版）
# 调用中转站的图片生成接口（OpenAI 兼容格式）：文字描述 → 生成图 → 返回公网图片 URL。
# 官方机器人发图只接受公网 URL，中转站本身返回的就是直链，直接返回即可。
# 同步实现，调用方需用 asyncio.to_thread 包装（生图较慢，会阻塞事件循环）。
# key 从 config_secret.py 读取（该文件已被 .gitignore 忽略，不入库）。
import requests
import time
import threading

try:
    from config_secret import DRAW_API_KEY
except ImportError:
    DRAW_API_KEY = ""

# ===================== 配置区 =====================
DRAW_BASE_URL = "https://www.right.codes/draw"
DRAW_MODEL = "gpt-image-2"
DRAW_SIZE = "1024x1024"
DRAW_TIMEOUT = 120          # 生图较慢，给足超时
DRAW_COOLDOWN = 5           # 两次生图最小间隔（秒），防刷烧钱
# ==================================================

_draw_lock = threading.Lock()
_last_draw_time = [0.0]     # 用列表包装以便在锁内修改


def get_gpt_draw(prompt: str) -> tuple[str | None, str | None]:
    """
    根据文字描述生成图片。
    返回 (图片URL, 错误提示)：成功时 (url, None)，失败时 (None, 提示文案)。
    """
    if not prompt or not prompt.strip():
        return None, "汝想画什么呀？@咱 画图 + 描述，比如『画图 一只戴帽子的猫』。"

    if not DRAW_API_KEY or DRAW_API_KEY == "在这里填入你的key":
        return None, "画图功能还没配好 key 呢，等汝填一下吧。"

    with _draw_lock:
        # 简单限流：距上次生图太近则拒绝
        elapsed = time.time() - _last_draw_time[0]
        if elapsed < DRAW_COOLDOWN:
            return None, f"画得太快啦，{DRAW_COOLDOWN - int(elapsed)}秒后再来吧。"
        _last_draw_time[0] = time.time()

    url = f"{DRAW_BASE_URL}/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {DRAW_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": DRAW_MODEL,
        "prompt": prompt.strip(),
        "image": [],
        "size": DRAW_SIZE,
        "response_format": "url",
    }

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=DRAW_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        img_url = result["data"][0]["url"]

        # QQ 富媒体只收 jpg/png，校验一下生成图的格式，避免发送时报 850019
        head = requests.get(img_url, timeout=30, stream=True)
        head.raise_for_status()
        ctype = head.headers.get("Content-Type", "").split(";")[0].strip().lower()
        head.close()
        if ctype not in ("image/jpeg", "image/jpg", "image/png"):
            print(f"[生图] 返回了不支持的格式: {ctype}")
            return None, "画好了，但图片格式 QQ 收不了，待会再试试吧。"

        return img_url, None

    except Exception as e:
        print(f"[生图] 失败: {e}")
        return None, "画图失败了，可能是太忙或描述有问题，待会再试试吧。"
