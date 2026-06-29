# 图像处理模块：镜像、幻影坦克。
# 旧版返回 base64 CQ 码（NapCat 用）；官方平台改为返回「图片字节 + 文件名」，
# 由调用方上传图床（image_host）拿公网 URL 再发。同步实现，调用方用 asyncio.to_thread 包装。
import requests
from io import BytesIO
from PIL import Image

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def make_mirror(img_url: str) -> tuple[bytes, str] | None:
    """
    左右镜像：取左半边翻转拼到右边。支持 GIF 逐帧。
    返回 (图片字节, 文件名)，失败返回 None。
    """
    try:
        response = requests.get(img_url, headers=_HEADERS, timeout=15)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))

        # GIF 动图：逐帧镜像后合成新动画
        if img.format == "GIF" and getattr(img, "n_frames", 1) > 1:
            frames = []
            durations = []
            for i in range(img.n_frames):
                img.seek(i)
                frame = img.convert("RGBA")
                width, height = frame.size
                left_half = frame.crop((0, 0, width // 2, height))
                right_half = left_half.transpose(Image.FLIP_LEFT_RIGHT)
                new_frame = Image.new("RGBA", (width, height))
                new_frame.paste(left_half, (0, 0))
                new_frame.paste(right_half, (width // 2, 0))
                frames.append(new_frame)
                durations.append(img.info.get("duration", 100))

            output_buffer = BytesIO()
            frames[0].save(
                output_buffer, format="GIF", save_all=True,
                append_images=frames[1:], duration=durations, loop=0, disposal=2,
            )
            return output_buffer.getvalue(), "mirror.gif"

        # 静态图
        img = img.convert("RGB")
        width, height = img.size
        left_half = img.crop((0, 0, width // 2, height))
        right_half = left_half.transpose(Image.FLIP_LEFT_RIGHT)
        new_img = Image.new("RGB", (width, height))
        new_img.paste(left_half, (0, 0))
        new_img.paste(right_half, (width // 2, 0))

        output_buffer = BytesIO()
        new_img.save(output_buffer, format="JPEG", quality=90)
        return output_buffer.getvalue(), "mirror.jpg"

    except Exception as e:
        print(f"[镜像] 处理失败: {e}")
        return None


def make_phantom_tank(img_url1: str, img_url2: str) -> tuple[bytes, str] | None:
    """
    幻影坦克：白底显示第一张、黑底显示第二张。
    强制灰度区间分离（表层 128-255、里层 0-127）避免失效。
    返回 (图片字节, 文件名)，失败返回 None。
    """
    try:
        r1 = requests.get(img_url1, headers=_HEADERS, timeout=15)
        r1.raise_for_status()
        img1 = Image.open(BytesIO(r1.content)).convert("L")  # 表层（白背景）
        r2 = requests.get(img_url2, headers=_HEADERS, timeout=15)
        r2.raise_for_status()
        img2 = Image.open(BytesIO(r2.content)).convert("L")  # 里层（黑背景）

        width, height = img1.size
        img2 = img2.resize((width, height), Image.Resampling.LANCZOS)

        # 强制灰度区间分离
        pixels1 = img1.load()
        pixels2 = img2.load()
        for y in range(height):
            for x in range(width):
                pixels1[x, y] = int(128 + (pixels1[x, y] / 255) * 127)  # 表层 → 亮区
                pixels2[x, y] = int((pixels2[x, y] / 255) * 127)        # 里层 → 暗区

        # 幻影坦克核心算法（恒满足 light > dark）
        phantom_img = Image.new("RGBA", (width, height))
        phantom_pixels = phantom_img.load()
        for y in range(height):
            for x in range(width):
                light = pixels1[x, y]
                dark = pixels2[x, y]
                alpha = max(255 - (light - dark), 1)
                rgb = int((dark * 255) / alpha)
                phantom_pixels[x, y] = (rgb, rgb, rgb, alpha)

        output_buffer = BytesIO()
        phantom_img.save(output_buffer, format="PNG")
        return output_buffer.getvalue(), "phantom.png"

    except Exception as e:
        print(f"[幻影坦克] 生成失败: {e}")
        return None
