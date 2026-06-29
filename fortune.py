# 今日运势模块：每人每天固定运势
# 核心：用 (用户ID + 当天日期) 做稳定随机种子，保证同一用户同一天结果不变，
# 跨天或换用户才变化。用 hashlib 而非内置 hash()，避免进程重启导致种子漂移。
import hashlib
import random
from datetime import date

# 运势等级（按指数区间从高到低匹配，第一个满足的生效）
_TIERS = [
    (95, "大吉",  "🌟"),
    (80, "吉",    "✨"),
    (60, "中吉",  "🍀"),
    (40, "小吉",  "🌤️"),
    (20, "末吉",  "🌥️"),
    (0,  "凶",    "🌧️"),
]

_LUCKY_COLORS = ["樱花粉", "天空蓝", "薄荷绿", "柠檬黄", "薰衣草紫", "珊瑚橙", "奶茶棕", "雪白", "玫瑰金", "墨黑"]

_BLESSINGS = [
    "今天会有好事发生哦～",
    "保持微笑，好运自然来～",
    "适合大胆尝试新事物～",
    "记得多喝水、早点睡～",
    "今天的汝闪闪发光～",
    "遇到困难别慌，咱陪着汝～",
    "也许会收到意外惊喜～",
    "宜摸鱼，忌内耗～",
    "好运正在路上，耐心等等～",
    "今天适合对喜欢的人主动一点～",
]


def get_fortune(user_id) -> str:
    """生成某用户今日运势文本。同一用户同一天调用结果恒定。"""
    today = date.today().isoformat()  # 例如 2026-06-29
    # 稳定哈希：用户ID + 日期 → 固定整数种子
    seed_str = f"{user_id}-{today}"
    seed = int(hashlib.md5(seed_str.encode("utf-8")).hexdigest(), 16)
    rng = random.Random(seed)

    index = rng.randint(1, 100)
    # 匹配等级
    tier_name, tier_emoji = "凶", "🌧️"
    for threshold, name, emoji in _TIERS:
        if index >= threshold:
            tier_name, tier_emoji = name, emoji
            break

    lucky_color = rng.choice(_LUCKY_COLORS)
    lucky_number = rng.randint(0, 9)
    blessing = rng.choice(_BLESSINGS)

    return (
        f"🔮 今日运势 🔮\n"
        f"━━━━━━━━━━\n"
        f"{tier_emoji} 运势等级：{tier_name}\n"
        f"📊 运势指数：{index} / 100\n"
        f"🎨 幸运色：{lucky_color}\n"
        f"🔢 幸运数字：{lucky_number}\n"
        f"━━━━━━━━━━\n"
        f"💬 赫萝寄语：{blessing}"
    )
