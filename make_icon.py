# make_icon.py —— 生成一个临时 App 图标（蓝底白字“导”）
# 以后要换成真正的组徽，只要把 static/icon-192.png 和 icon-512.png 换掉即可。

from PIL import Image, ImageDraw, ImageFont
import os

STATIC = os.path.join(os.path.dirname(__file__), "static")
BLUE = (13, 110, 253)   # Bootstrap 主题蓝
WHITE = (255, 255, 255)


def find_cjk_font(size):
    # 在 Windows 上找一个能显示中文的字体
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",   # 黑体
        r"C:\Windows\Fonts\simsun.ttc",   # 宋体
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make(size, text="导"):
    img = Image.new("RGB", (size, size), BLUE)
    draw = ImageDraw.Draw(img)
    font = find_cjk_font(int(size * 0.6))
    # 居中画字
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), text, fill=WHITE, font=font)
    path = os.path.join(STATIC, f"icon-{size}.png")
    img.save(path)
    print("已生成", path)


if __name__ == "__main__":
    make(192)
    make(512)
