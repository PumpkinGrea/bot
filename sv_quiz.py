# Shadowverse: Worlds Beyond card-image guessing game state and image cropper.
from dataclasses import dataclass
from io import BytesIO
import random
import re
import threading
import time

from PIL import Image, ImageOps
import requests

from sv_card import get_random_quiz_card, is_similar_card_name


_QUIZ_TTL = 600
_DOWNLOAD_TIMEOUT = 30
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_HEADERS = {
    "User-Agent": "HoloQQBot/1.0 (Shadowverse card quiz)",
}
_states = {}
_lock = threading.Lock()


@dataclass
class _QuizState:
    answer: str
    image_url: str
    hints: tuple[str, ...]
    expires_at: float
    attempts: int = 0
    hint_index: int = 0


@dataclass
class QuizAction:
    text: str
    active: bool = False
    correct: bool = False
    image_url: str | None = None


def _active_state(scope_id: str) -> tuple[_QuizState | None, bool]:
    state = _states.get(scope_id)
    if not state:
        return None, False
    if time.monotonic() < state.expires_at:
        return state, False
    _states.pop(scope_id, None)
    return state, True


def _crop_card_art(image_url: str) -> tuple[bytes | None, str | None]:
    """Crop a random detail from the illustration area, excluding the card UI text."""
    try:
        with requests.get(image_url, headers=_HEADERS, timeout=_DOWNLOAD_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_IMAGE_BYTES:
                return None, "卡图文件过大，换一张再试试吧。"
            image_bytes = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                image_bytes.extend(chunk)
                if len(image_bytes) > _MAX_IMAGE_BYTES:
                    return None, "卡图文件过大，换一张再试试吧。"

        image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGB")
        width, height = image.size
        # The title/cost occupy the top band and effects/stats occupy the lower band.
        left, top = int(width * 0.10), int(height * 0.16)
        right, bottom = int(width * 0.90), int(height * 0.62)
        art_width, art_height = right - left, bottom - top
        if art_width < 40 or art_height < 40:
            return None, "卡图尺寸异常，换一张再试试吧。"

        crop_width = max(40, int(art_width * 0.65))
        crop_height = max(40, int(art_height * 0.65))
        crop_left = random.randint(left, right - crop_width)
        crop_top = random.randint(top, bottom - crop_height)
        cropped = image.crop((crop_left, crop_top, crop_left + crop_width, crop_top + crop_height))

        if max(cropped.size) < 560:
            scale = 560 / max(cropped.size)
            cropped = cropped.resize(
                (round(cropped.width * scale), round(cropped.height * scale)), Image.Resampling.LANCZOS
            )
        output = BytesIO()
        cropped.save(output, format="JPEG", quality=90, optimize=True)
        return output.getvalue(), None
    except Exception as e:
        print(f"[猜卡] 卡图裁切失败 {image_url}: {e}")
        return None, "题目图片生成失败，换一张再试试吧。"


def start_card_quiz(scope_id: str, replace: bool = False) -> tuple[tuple[bytes, str] | None, str | None]:
    """Start or replace one 10-minute quiz round for a group or private chat."""
    with _lock:
        state, _ = _active_state(scope_id)
        if state and not replace:
            return None, "当前题目仍在进行中。发送「猜 卡名」作答，或发送「换一张猜卡」换题。"

    card, error = get_random_quiz_card()
    if not card:
        return None, error
    image_bytes, error = _crop_card_art(card["image_url"])
    if not image_bytes:
        return None, error

    with _lock:
        _states[scope_id] = _QuizState(
            answer=card["answer"],
            image_url=card["image_url"],
            hints=card["hints"],
            expires_at=time.monotonic() + _QUIZ_TTL,
        )
    return (image_bytes, "quiz.jpg"), None


def guess_card(scope_id: str, guess: str) -> QuizAction:
    """Check one explicit guess without consuming normal chat messages."""
    guess = (guess or "").strip()
    if not guess:
        return QuizAction("请在「猜」后面写卡名，例如「猜 哥布林」。")

    with _lock:
        state, expired = _active_state(scope_id)
        if not state:
            return QuizAction("当前没有进行中的题目，发送「猜卡」开始一题。")
        if expired:
            return QuizAction(f"本题已超时，答案是「{state.answer}」。发送「猜卡」开始下一题。")

        state.attempts += 1
        if is_similar_card_name(guess, state.answer):
            _states.pop(scope_id, None)
            return QuizAction(
                f"答对了！答案是「{state.answer}」，本题共猜了 {state.attempts} 次。",
                correct=True,
                image_url=state.image_url,
            )
        return QuizAction(
            f"不对，再猜一次。当前已猜 {state.attempts} 次；可发送「猜卡提示」获取提示。",
            active=True,
        )


def get_card_quiz_hint(scope_id: str) -> QuizAction:
    """Return progressive hints for the active quiz round."""
    with _lock:
        state, expired = _active_state(scope_id)
        if not state:
            return QuizAction("当前没有进行中的题目，发送「猜卡」开始一题。")
        if expired:
            return QuizAction(f"本题已超时，答案是「{state.answer}」。发送「猜卡」开始下一题。")

        index = min(state.hint_index, len(state.hints) - 1)
        state.hint_index += 1
        return QuizAction(state.hints[index], active=True)
