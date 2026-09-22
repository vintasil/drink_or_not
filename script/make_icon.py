"""把 pic/cat/magic_cat.png 做成打包要用的图标。

Pillow 自带 .icns 编码器(一次写全 macOS 要的那八个尺寸),所以这一步在 Ubuntu 上就能跑完,
顺带写一张同尺寸的 build/icon.png —— 上 Mac 之前就能看图标长什么样,不必等打包出来才发现难看。

仓库里不存图标二进制:它是从这张原图派生的,换了原图或改了形状重跑一遍即可。
build/build_macos.sh 会在打包前自动跑。

**macOS 的 .app 图标不是一张方图**,是"四周留白 + 圆角方块",方块边长约占画布八成;
直接把方图当图标,在 Dock 里就是个贴上去的色块。这里按 Apple 的模板尺寸合成
(1024 画布 / 824 见方的方块 / 圆角 185),方块底下垫一层柔和投影。

    uv run python script/make_icon.py
"""

from pathlib import Path
from typing import Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from drink_or_not import sprite_convert

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pic" / "cat" / "magic_cat.png"
OUT_ICNS = ROOT / "build" / "icon.icns"
OUT_PNG = ROOT / "build" / "icon.png"

CANVAS = 1024  # macOS 图标最大的那张,更小的尺寸由它缩出来
SQUIRCLE = 824  # 圆角方块的边长(Apple 模板)
CORNER = 185  # 方块的圆角半径
MARGIN = (CANVAS - SQUIRCLE) // 2  # 四周留白,投影也画在这块里
INSET = 40  # 主体离方块边缘再让一点:贴着的话,剑尖和书角的棘刺会被圆角切掉一截
SHADOW_BLUR = 18
SHADOW_DY = 10
SHADOW_ALPHA = 80


def build_icon(subject: Image.Image, background: Tuple[int, int, int]) -> Image.Image:
    """把抠好的主体合成成一张 1024 的 macOS 图标。纯函数,便于离线断言。

    主体按"完整放进去"缩放,再拿方块形状裁一刀 —— 不裁的话,主体四个角会飘到圆角外面
    去,在桌面上看就是猫的爪子悬空在图标轮廓之外。
    """
    box = (MARGIN, MARGIN, MARGIN + SQUIRCLE, MARGIN + SQUIRCLE)
    shape = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(shape).rounded_rectangle(box, radius=CORNER, fill=255)

    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    # 投影:方块整体下移一点。不糊的话是硬边,比没有还难看
    soft = shape.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)).point(lambda v: v * SHADOW_ALPHA // 255)
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow.putalpha(soft)
    icon = Image.alpha_composite(icon, ImageChops.offset(shadow, 0, SHADOW_DY))

    # 底色直接取原图自己的背景色 —— 图标看起来就该是"这张画裁成图标形状",不另外配色
    plate = Image.new("RGBA", (CANVAS, CANVAS), (*background, 255))
    plate.putalpha(shape)
    icon = Image.alpha_composite(icon, plate)

    placed = _place_subject(subject)
    placed.putalpha(ImageChops.multiply(placed.getchannel("A"), shape))
    return Image.alpha_composite(icon, placed)


def _place_subject(subject: Image.Image) -> Image.Image:
    inner = SQUIRCLE - 2 * INSET
    ratio = inner / max(subject.size)
    size = (max(1, round(subject.width * ratio)), max(1, round(subject.height * ratio)))
    scaled = subject.resize(size, Image.LANCZOS)
    layer = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    layer.paste(
        scaled,
        (MARGIN + (SQUIRCLE - size[0]) // 2, MARGIN + (SQUIRCLE - size[1]) // 2),
        scaled,
    )
    return layer


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"找不到原图:{SRC}")

    with Image.open(SRC) as raw:
        raw.load()
        background = raw.convert("RGB").getpixel((0, 0))
    print(f"原图 {SRC.relative_to(ROOT)} 背景色 {background}")

    # 遮罩是按 MASK_MAX 算的,所以 1024 是能拿到的最清楚的抠图;再大只是白放大
    subject = sprite_convert.cutout_image(SRC, out_max=CANVAS, progress=print)
    print(f"主体 {subject.width}x{subject.height} {subject.mode}")

    icon = build_icon(subject, background)
    OUT_ICNS.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT_ICNS, format="ICNS")
    icon.save(OUT_PNG)
    print(f"已写出 {OUT_ICNS.relative_to(ROOT)}({OUT_ICNS.stat().st_size // 1024} KiB)")
    print(f"已写出 {OUT_PNG.relative_to(ROOT)}  <- 想先看效果就打开这张")


if __name__ == "__main__":
    main()
