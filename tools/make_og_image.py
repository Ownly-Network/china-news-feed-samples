#!/usr/bin/env python3
"""Generate docs/og-image.png (1200x630), the link-preview image for Open Graph / Twitter cards.
Run once by hand after cloning fonts change; not part of the hourly build.
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "og-image.png")
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
W, H = 1200, 630
BG = (15, 15, 17)
RED = (255, 107, 107)
MUTED = (160, 160, 168)


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(FONT, 68)
    sub = ImageFont.truetype(FONT, 30)
    small = ImageFont.truetype(FONT, 26)
    pub = ImageFont.truetype(FONT, 24)

    d.text((80, 130), "Dropped off today", font=title, fill="white")
    d.text((80, 215), "今日下榜", font=title, fill=RED)
    d.text((80, 340), "Topics that vanished from China's hot lists while still trending",
           font=sub, fill=MUTED)
    d.text((80, 400), "Weibo · Baidu · Zhihu · Toutiao · Bilibili", font=small, fill=MUTED)
    d.text((80, 540), "Ownly Network", font=pub, fill="white")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print(f"wrote {OUT} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
