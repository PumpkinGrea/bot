# 随机二次元图片模块（官方平台版）
# 官方机器人发图只接受公网可访问的 URL，且 QQ 服务器会自己去拉取该 URL，
# 对格式很挑：只支持 jpg/png，webp 等会报「富媒体文件格式不支持」(code 850019)。
# 所以这里：取图源直链 → 校验确实是 jpeg/png → 才返回。
# 同步实现，调用方需用 asyncio.to_thread 包装。
import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# QQ 富媒体支持的图片 MIME
_OK_TYPES = ("image/jpeg", "image/jpg", "image/png")


def _verify_image(url: str) -> bool:
    """确认 URL 指向的是 QQ 能收的 jpg/png（挡掉 webp / 防盗链 / 跳转页）。"""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15, stream=True)
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        r.close()
        return ctype in _OK_TYPES
    except Exception as e:
        print(f"[随机图] 校验失败 {url}: {e}")
        return False


def get_acg_pic() -> str | None:
    """获取一张随机二次元图的公网直链 URL（保证是 jpg/png）；失败返回 None。"""
    # 图源：anosu，json 接口返回 jpeg 直链（百度静态 CDN，无防盗链，QQ 可直接拉取）
    for api_url in ("https://api.anosu.top/img/?type=json",
                    "https://moe.jitsu.top/img/?type=json"):
        try:
            resp = requests.get(api_url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            pics = resp.json().get("pics") or []
            for img_url in pics:
                if img_url and _verify_image(img_url):
                    return img_url
        except Exception as e:
            print(f"[随机图] {api_url} 获取失败: {e}")
            continue

    return None
