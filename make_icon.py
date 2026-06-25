# make_icon.py —— 用现成的"邢门"图（我提供的材料/xingmen-cover.png）生成 App 图标。
# 生成 static/icon-192.png 和 icon-512.png（PWA 装桌面用）。
# 手机桌面会自动给图标套圆角，原图四角的深色包边会被裁掉，所以缩放并四周垫宣纸色留白，
# 让包边与右下"导师组"印章都落在安全区内不被切。
# 要换图只需改 SRC 后重跑：python make_icon.py

from PIL import Image
import os

STATIC = os.path.join(os.path.dirname(__file__), "static")
SRC = os.path.join(os.path.dirname(__file__), "我提供的材料", "xingmen-cover.png")

PAPER = (228, 220, 200)   # 取原图边框附近的宣纸色做留白底，过渡自然
SCALE = 0.88              # 主图占比，四周留白（防手机圆角裁掉包边）


def make(size):
    src = Image.open(SRC).convert("RGBA")
    inner = int(size * SCALE)
    src_resized = src.resize((inner, inner), Image.LANCZOS)

    # 宣纸色底，居中贴主图
    canvas = Image.new("RGBA", (size, size), PAPER + (255,))
    off = (size - inner) // 2
    canvas.alpha_composite(src_resized, (off, off))

    out = canvas.convert("RGB")
    path = os.path.join(STATIC, f"icon-{size}.png")
    out.save(path)
    print("已生成", path)


if __name__ == "__main__":
    make(192)
    make(512)
