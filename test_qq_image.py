import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from botpy.errors import ServerError

from qq_image import ImageUploadError, upload_image


class ImageUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_then_valid_reuses_upload_arguments(self):
        media = {"file_info": "valid"}
        upload = AsyncMock(side_effect=[None, media])
        with patch("qq_image.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await upload_image(upload, url="https://example.com/image.png")
        self.assertIs(result, media)
        self.assertEqual(upload.await_count, 2)
        self.assertEqual(upload.await_args_list[0], upload.await_args_list[1])
        self.assertFalse(upload.await_args.kwargs["srv_send_msg"])
        sleep.assert_awaited_once_with(2)

    async def test_timeout_then_success(self):
        upload = AsyncMock(side_effect=[asyncio.TimeoutError(), {"file_info": "ok"}])
        with patch("qq_image.asyncio.sleep", new_callable=AsyncMock):
            await upload_image(upload)
        self.assertEqual(upload.await_count, 2)

    async def test_invalid_responses_exhaust_retries(self):
        upload = AsyncMock(side_effect=[None, {}, {"file_info": " "}])
        with patch("qq_image.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(ImageUploadError):
                await upload_image(upload)
        self.assertEqual(upload.await_count, 3)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [2, 4])

    async def test_explicit_rejection_is_not_retried(self):
        # SDK also uses ServerError for HTTP 400, so never blindly retry it.
        upload = AsyncMock(side_effect=ServerError("rejected"))
        with patch("qq_image.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(ImageUploadError):
                await upload_image(upload)
        upload.assert_awaited_once()
        sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
