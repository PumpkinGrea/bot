# Right Code async image-generation module.
# The provider returns a task ID immediately, so this module polls the
# site-level task endpoint until it receives the final public image URL.
import base64
import threading
import time

import requests

try:
    from config_secret import DRAW_API_KEY
except ImportError:
    DRAW_API_KEY = ""


DRAW_GENERATE_URL = "https://www.rightapi.ai/draw/v1/images/generations"
DRAW_TASK_URL = "https://www.rightapi.ai/v1/tasks/{task_id}"
DRAW_MODEL = "gpt-image-2"
DRAW_SIZE = "1:1"
DRAW_TIMEOUT = 300
DRAW_POLL_INTERVAL = 2
DRAW_COOLDOWN = 5
MAX_REFERENCE_IMAGES = 4
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
_REFERENCE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

_draw_lock = threading.Lock()
_last_draw_time = [0.0]


def _image_url(result: dict) -> str:
    """Return the generated image URL from an OpenAI Images-style response."""
    data = result.get("data") or []
    if not data or not data[0].get("url"):
        raise ValueError("任务完成但没有返回图片 URL")
    return data[0]["url"]


def _task_error(result: dict) -> str:
    error = result.get("error")
    if isinstance(error, dict):
        return error.get("message") or str(error)
    return str(error or result.get("message") or "上游生成失败")


def _reference_data_url(url: str) -> str:
    """Download one reference image and encode it as a bounded data URL."""
    response = requests.get(url, timeout=30, stream=True)
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type not in _REFERENCE_CONTENT_TYPES:
            raise ValueError("参考图仅支持 JPG、PNG 或 WebP 格式")

        image_bytes = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            image_bytes.extend(chunk)
            if len(image_bytes) > MAX_REFERENCE_IMAGE_BYTES:
                raise ValueError("参考图不能超过 10 MB")
        if not image_bytes:
            raise ValueError("参考图为空")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    finally:
        response.close()


def _wait_for_image(task_id: str, headers: dict) -> str:
    deadline = time.monotonic() + DRAW_TIMEOUT
    while time.monotonic() < deadline:
        response = requests.get(
            DRAW_TASK_URL.format(task_id=task_id),
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

        # Completed Images responses are returned directly as {"data": [...]}
        # and do not necessarily include a status field.
        if result.get("data"):
            return _image_url(result)

        status = result.get("status")

        if status == "completed":
            return _image_url(result)
        if status == "failed":
            raise RuntimeError(_task_error(result))
        if status not in ("queued", "processing", "in_progress"):
            raise RuntimeError(f"未知绘图任务状态：{status or 'missing'}")

        time.sleep(DRAW_POLL_INTERVAL)

    raise TimeoutError("绘图任务超时")


def get_gpt_draw(
    prompt: str, reference_image_urls: list[str] | None = None
) -> tuple[str | None, str | None]:
    """Generate an image and return its public URL or a user-facing error."""
    if not prompt or not prompt.strip():
        return None, "汝想画什么呀？发“画图 + 描述”，比如“画图 一只戴帽子的猫”。"

    if not DRAW_API_KEY or DRAW_API_KEY == "在这里填入你的key":
        return None, "画图功能还没配好 key 哟，等汝填一下吧。"

    with _draw_lock:
        elapsed = time.time() - _last_draw_time[0]
        if elapsed < DRAW_COOLDOWN:
            return None, f"画得太快啦，{DRAW_COOLDOWN - int(elapsed)} 秒后再来吧。"
        _last_draw_time[0] = time.time()

    headers = {
        "Authorization": f"Bearer {DRAW_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DRAW_MODEL,
        "prompt": prompt.strip(),
        "n": 1,
        "size": DRAW_SIZE,
        "async": True,
    }

    reference_image_urls = (reference_image_urls or [])[:MAX_REFERENCE_IMAGES]
    if reference_image_urls:
        try:
            payload["image"] = [
                _reference_data_url(url) for url in reference_image_urls
            ]
        except (requests.RequestException, ValueError) as e:
            print(f"[Draw] Reference image failed: {e}")
            return None, f"参考图处理失败：{e}"

    try:
        response = requests.post(
            DRAW_GENERATE_URL,
            json=payload,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        submission = response.json()
        task_id = submission.get("task_id")
        img_url = _wait_for_image(task_id, headers) if task_id else _image_url(submission)

        # QQ rich media accepts public JPG/PNG URLs only.
        head = requests.get(img_url, timeout=30, stream=True)
        head.raise_for_status()
        content_type = head.headers.get("Content-Type", "").split(";", 1)[0].lower()
        head.close()
        if content_type not in ("image/jpeg", "image/jpg", "image/png"):
            print(f"[Draw] Unsupported image content type: {content_type}")
            return None, "画好了，但图片格式 QQ 收不了，待会再试试吧。"

        return img_url, None
    except Exception as e:
        print(f"[Draw] Failed: {e}")
        return None, "画图失败了，可能是太忙或描述有问题，待会再试试吧。"
