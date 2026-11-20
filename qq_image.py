"""QQ 图片上传校验和有限重试，不重试生成或发送消息。"""

import asyncio

import aiohttp
from botpy import logging


_log = logging.get_logger()
_RETRY_DELAYS = (2, 4)


class ImageUploadError(RuntimeError):
    """图片未取得有效的 QQ file_info。"""


async def upload_image(upload, **kwargs):
    """上传同一 URL，最多三次；SDK 超时可能返回 None，必须检查结果。"""
    for attempt in range(1, 4):
        try:
            media = await upload(**kwargs, srv_send_msg=False)
        except (asyncio.TimeoutError, aiohttp.ClientConnectionError,
                ConnectionError) as exc:
            cause = exc
            reason = type(exc).__name__
        except Exception as exc:
            # 鉴权、风控等明确拒绝不重试，也不继续发送图片消息。
            raise ImageUploadError("QQ 拒绝图片上传") from exc
        else:
            if (isinstance(media, dict)
                    and isinstance(media.get("file_info"), str)
                    and media["file_info"].strip()):
                return media
            cause = None
            reason = "上传返回为空或缺少有效 file_info"

        _log.warning("QQ 图片上传失败 | 尝试=%d/3 原因=%s", attempt, reason)
        if attempt == 3:
            raise ImageUploadError("QQ 图片上传重试三次仍失败") from cause
        await asyncio.sleep(_RETRY_DELAYS[attempt - 1])
