"""Render rotation CR charts from the browser-synced SVWB snapshot."""

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from io import BytesIO
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

SNAPSHOT = Path(__file__).parent / "data" / "svwb" / "snapshot.json"
CLASSES = ("精灵", "皇家护卫", "巫师", "龙族", "梦魇", "主教", "超越者")
COLORS = ("#35b04a", "#bd8210", "#3d84ee", "#e0642a", "#d12b4d", "#afa990", "#159caf")
FACE_NAMES = ("elf", "royal", "witch", "dragon", "nightmare", "bishop", "nemesis")
FACES = SNAPSHOT.parent / "faces"
BG, PANEL, TEXT, MUTED, GOLD = "#0a0b11", "#16161e", "#f5f6fb", "#b8bac9", "#e8c15b"


def summarize(snapshot):
    """Match the website: compare current CR at the highest class-board floor."""
    rankings = snapshot["datasets"]["rankings"]
    rows = []
    periods = set()
    for i, name in enumerate(CLASSES):
        board = rankings["rankings"][str(23 + i)]
        periods.add(board["display_ranking"]["ranking_period_id"])
        values = [r["user"]["class_rating"]["rating"] for r in board["ranking"]]
        if not values or any(type(v) not in (int, float) or v <= 0 for v in values):
            raise ValueError("职业 CR 榜尚未完成计算")
        rows.append(dict(name=name, color=COLORS[i], face=FACE_NAMES[i], values=values,
                         low=min(values), high=max(values)))
    if len(periods) != 1 or next(iter(periods)) != rankings["ranking_period_id"]:
        raise ValueError("职业 CR 榜赛季不一致")
    baseline = max(r["low"] for r in rows)
    for row in rows:
        row["count"] = sum(v >= baseline for v in row.pop("values"))
    total = sum(r["count"] for r in rows)
    for row in rows:
        row["pct"] = row["count"] / total * 100
    return rows, baseline, total


@lru_cache(maxsize=12)
def _font(size):
    for path in ("C:/Windows/Fonts/msyh.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError("缺少中文字体，请安装 fonts-noto-cjk 或 fonts-wqy-zenhei")


def render_chart(snapshot):
    rows, baseline, total = summarize(snapshot)
    image = Image.new("RGB", (1200, 1420), BG)
    d = ImageDraw.Draw(image)

    def text(x, y, value, size=24, color=TEXT, anchor=None):
        d.text((x, y), str(value), font=_font(size), fill=color, anchor=anchor)

    text(52, 36, "SVWB META", 23, GOLD)
    text(52, 80, "指定模式 · 职业 CR 统计", 42)
    text(52, 143, "高分榜分布 / 职业评级区间", 23, MUTED)
    d.rounded_rectangle((50, 204, 1150, 782), radius=24, fill=PANEL, outline="#292a36", width=2)
    text(80, 232, f"CR {baseline:g} 以上分布", 30)
    text(80, 281, f"统一门槛以上共 {total} 条职业榜记录", 22, MUTED)

    # Match the site's wedge-clipped portraits, including its centroid placement
    # and slightly enlarged portrait for large shares. Supersample the pie only.
    scale, radius = 3, 190
    side = 2 * radius * scale
    pie = Image.new("RGB", (side, side), PANEL)
    box = (0, 0, side - 1, side - 1)
    angle = -90
    for row in sorted(rows, key=lambda r: -r["count"]):
        sweep = row["pct"] * 3.6
        if sweep:
            gap = min(.7, sweep / 4)
            start, end = angle + gap, angle + sweep - gap
            mask = Image.new("L", (side, side), 0)
            ImageDraw.Draw(mask).pieslice(box, start, end, fill=255)
            layer = Image.new("RGB", (side, side), row["color"])
            try:
                with Image.open(FACES / f'{row["face"]}.png') as source:
                    portrait = source.convert("RGBA")
                half = math.radians(sweep / 2)
                offset = min(radius * .66, 2 / 3 * radius * math.sin(half) / half) * .94
                share = row["pct"] / 100
                large = share > .28
                size = round(radius * 1.42 * (1 + min(share - .28, .4) * 1.9 if large else 1) * scale)
                if large:
                    offset += radius * .05
                middle = math.radians(angle + sweep / 2)
                cx = (radius + offset * math.cos(middle)) * scale
                cy = (radius + offset * math.sin(middle)) * scale
                portrait = ImageOps.fit(portrait, (size, size), method=Image.Resampling.LANCZOS)
                layer.paste(portrait, (round(cx - size * .5), round(cy - size * .52)), portrait)
            except (OSError, ValueError):
                pass  # Keep a readable class-colored wedge if an asset is unavailable.
            pie.paste(layer, (0, 0), mask)
            ImageDraw.Draw(pie).pieslice(box, start, end, outline=row["color"], width=2 * scale)
        angle += sweep
    image.paste(pie.resize((380, 380), Image.Resampling.LANCZOS), (92, 344))
    text(550, 334, "职业", 21, MUTED)
    text(913, 334, "记录数", 21, MUTED, "ra")
    text(1090, 334, "占比", 21, MUTED, "ra")
    for i, row in enumerate(sorted(rows, key=lambda r: -r["count"])):
        y = 393 + i * 48
        d.rounded_rectangle((550, y, 564, y + 24), radius=5, fill=row["color"])
        text(582, y - 5, row["name"], 25)
        text(913, y - 5, row["count"], 25, anchor="ra")
        text(1090, y - 5, f'{row["pct"]:.1f}%', 25, anchor="ra")

    d.rounded_rectangle((50, 810, 1150, 1260), radius=24, fill=PANEL, outline="#292a36", width=2)
    text(80, 836, "职业评级区间", 30)
    text(80, 883, "各职业榜最低至最高 CR · 金色端点为全场最高", 22, MUTED)
    low = int(min(r["low"] for r in rows) // 50 * 50) - 50
    high = int(max(r["high"] for r in rows) // 50 * 50) + 50
    x0, x1 = 310, 970

    def xpos(v):
        return x0 + (v - low) / (high - low) * (x1 - x0)

    for value in range(low, high + 1, 50):
        x = xpos(value)
        d.line((x, 948, x, 1199), fill="#292a36")
        text(x, 1212, value, 18, MUTED, "ma")
    bx = xpos(baseline)
    for y in range(940, 1200, 14):
        d.line((bx, y, bx, y + 7), fill=GOLD, width=2)
    peak = max(r["high"] for r in rows)
    for i, row in enumerate(rows):
        y = 959 + i * 36
        text(80, y - 15, row["name"], 23)
        a, b = xpos(row["low"]), xpos(row["high"])
        d.rounded_rectangle((a, y - 8, b, y + 8), radius=8, fill=row["color"])
        d.ellipse((b - 5, y - 5, b + 5, y + 5), fill=GOLD if row["high"] == peak else TEXT)
        text(1110, y - 13, f'{row["low"]:g}–{row["high"]:g}', 20, MUTED, "ra")

    raw = snapshot.get("manifest", {}).get("rankingsFetchedAt")
    try:
        updated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        stamp = updated.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M") + " UTC+8"
    except (ValueError, AttributeError):
        stamp = "未知"
    text(52, 1283, f"榜单更新：{stamp}", 21, MUTED)
    text(52, 1320, "基准 CR 取七职业榜最低分中的最高值；仅代表榜单样本，非全服使用率或胜率。", 21, MUTED)
    text(52, 1361, "信息来源：https://svwbmeta.com/", 22, GOLD)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@lru_cache(maxsize=1)
def _render_cached(mtime_ns, file_size, face_versions):
    with SNAPSHOT.open(encoding="utf-8") as handle:
        return render_chart(json.load(handle))


def query_cr_chart():
    try:
        stat = SNAPSHOT.stat()
        face_versions = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None
                              for p in (FACES / f"{name}.png" for name in FACE_NAMES))
        return _render_cached(stat.st_mtime_ns, stat.st_size, face_versions), None
    except (OSError, KeyError, TypeError, ValueError):
        return None, "暂无可用的指定 CR 数据，请先更新代码并运行 svwb_sync.py 同步榜单。\n信息来源：https://svwbmeta.com/"
    except RuntimeError as error:
        return None, str(error)
