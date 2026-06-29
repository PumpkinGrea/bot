# 本地图片服务：托管「本地生成的图片字节」，对外提供公网可拉取的 URL。
# 官方 QQ 机器人发图只接受公网 URL，镜像/幻影坦克是本地 PIL 生成的，无现成公网地址，
# 故在 bot 进程内起一个 aiohttp 静态服务对外暴露。
#
# 两种部署：
#   1) 有公网 IP 的服务器（推荐）：无需内网穿透。不填 img_public_base 时会自动探测
#      服务器公网 IP，拼成 http://<公网IP>:<端口>。记得在安全组/防火墙放行该端口。
#   2) 本地开发机：用 cpolar/frp 等内网穿透，把拿到的公网域名填到 img_public_base。
#
# 用法：
#   host = ImageHost(public_base, host, port)
#   await host.start()                       # 在 botpy 的事件循环里启动
#   url = host.publish(img_bytes, "x.png")   # 注册一张图，拿回公网 URL
#
# 图片只存内存，带数量上限与 TTL，自动淘汰，避免内存无限增长。
import time
import uuid
from collections import OrderedDict

import requests
from aiohttp import web

# 单张图最长保留时间（秒）。QQ 富媒体上传时会立即来拉，几分钟足够。
_TTL = 600
# 内存里最多同时保留的图片数，超出按最早淘汰
_MAX_ITEMS = 50

_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}

# 探测公网 IP 的服务（按序尝试）
_IP_APIS = ("https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip")


def _detect_public_ip() -> str | None:
    """探测本机公网 IP（部署在有公网 IP 的服务器时用）。失败返回 None。"""
    for api in _IP_APIS:
        try:
            ip = requests.get(api, timeout=5).text.strip()
            # 粗校验：形如 a.b.c.d
            if ip.count(".") == 3 and all(p.isdigit() for p in ip.split(".")):
                return ip
        except Exception:
            continue
    return None


class ImageHost:
    def __init__(self, public_base: str, host: str = "0.0.0.0", port: int = 9900):
        self.public_base = (public_base or "").rstrip("/")
        self.host = host
        self.port = port
        self._store: "OrderedDict[str, tuple[bytes, str, float]]" = OrderedDict()
        self._runner: web.AppRunner | None = None

    @property
    def enabled(self) -> bool:
        """没有可用公网地址就视为关闭，镜像/幻影坦克会优雅降级。"""
        return bool(self.public_base)

    async def start(self):
        # 没显式配公网地址时，自动探测服务器公网 IP（服务器部署免配置）
        if not self.public_base:
            ip = await self._loop_detect_ip()
            if ip:
                self.public_base = f"http://{ip}:{self.port}"
                print(f"[图床] 自动探测到公网 IP，图片地址 base = {self.public_base}")
            else:
                print("[图床] 未配置 img_public_base 且公网 IP 探测失败，"
                      "本地图片服务不启动（镜像/幻影坦克将不可用）")
                return

        app = web.Application()
        app.router.add_get("/img/{token}", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        print(f"[图床] 本地图片服务已启动 → 监听 {self.host}:{self.port}，公网 base {self.public_base}")
        print(f"[图床] 提示：请确保服务器安全组/防火墙已放行 {self.port} 端口")

    async def _loop_detect_ip(self):
        import asyncio
        return await asyncio.to_thread(_detect_public_ip)

    def _gc(self):
        """清理过期项，并把数量压到上限内。"""
        now = time.time()
        expired = [k for k, (_, _, ts) in self._store.items() if now - ts > _TTL]
        for k in expired:
            self._store.pop(k, None)
        while len(self._store) > _MAX_ITEMS:
            self._store.popitem(last=False)

    def publish(self, img_bytes: bytes, filename: str = "image.png") -> str | None:
        """注册一张图，返回公网 URL；服务未启用返回 None。"""
        if not self.enabled:
            return None
        self._gc()
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
        mime = _MIME.get(ext, "image/png")
        token = f"{uuid.uuid4().hex}.{ext}"
        self._store[token] = (img_bytes, mime, time.time())
        return f"{self.public_base}/img/{token}"

    async def _handle(self, request: web.Request) -> web.Response:
        token = request.match_info["token"]
        item = self._store.get(token)
        if not item:
            return web.Response(status=404, text="not found")
        img_bytes, mime, _ = item
        return web.Response(body=img_bytes, content_type=mime)
