"""把 assets/cat.png 生成一组"晃来晃去"的待机帧。

单张静态图也能做出自然的飘浮感,靠三个正弦叠加,全部绕底部中心 pivot:

    旋转  ±4°      摆动主体
    浮动  ±4px     上下漂浮
    呼吸  1±0.02   轻微缩放,让动作不死板

所有帧共用同一块画布、同一个 pivot 位置,应用侧只要按固定坐标贴图就能得到连续动画。
将来用 AI 画好逐帧图,直接覆盖 assets/frames/ 并改 assets/manifest.json 即可,
应用代码不用动。
"""

import json
import math
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "cat.png"
OUT_DIR = ROOT / "assets" / "frames"
MANIFEST = ROOT / "assets" / "manifest.json"

COUNT = 36  # 帧数
FPS = 20  # 播放帧率 -> 36/20 = 1.8s 一个完整摇摆周期
SWAY_DEG = 4.0  # 最大摆角
BOB_PX = 4  # 最大垂直浮动
BREATH = 0.02  # 呼吸缩放幅度
MARGIN = 34  # 画布留白,要够容纳旋转时角点的位移
PALETTE_COLORS = 256  # 打包时量化到 256 色,体积降到约 1/4


def build_frames(cat):
    w, h = cat.size
    cw, ch = w + 2 * MARGIN, h + 2 * MARGIN
    # pivot 取原图底部中心;加 MARGIN 后它在画布里的位置
    ax, ay = MARGIN + w // 2, MARGIN + h

    frames = []
    for i in range(COUNT):
        theta = 2 * math.pi * i / COUNT
        rot = math.sin(theta) * SWAY_DEG
        bob = math.sin(theta) * BOB_PX
        breath = 1.0 + math.sin(2 * theta) * BREATH

        spr = cat
        if abs(breath - 1.0) > 1e-6:
            size = (max(1, round(w * breath)), max(1, round(h * breath)))
            spr = cat.resize(size, Image.LANCZOS)

        # 让缩放后的底部中心仍然落在 pivot 上,否则呼吸会让整体上下跳
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.alpha_composite(spr, (ax - spr.width // 2, ay - spr.height))

        if rot:
            canvas = canvas.rotate(rot, resample=Image.BICUBIC, center=(ax, ay))

        if bob:
            shifted = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            shifted.alpha_composite(canvas, (0, round(bob)))
            canvas = shifted

        frames.append(canvas)
    return frames, (cw, ch), (ax, ay)


def union_bbox(frames):
    """所有帧 alpha 的并集包围盒,应用侧用它定位宠物实际占用的区域。"""
    union = frames[0].getchannel("A")
    for f in frames[1:]:
        union = ImageChops.lighter(union, f.getchannel("A"))
    return union.getbbox()


def main():
    if not SRC.exists():
        raise SystemExit(f"找不到 {SRC.relative_to(ROOT)},请先运行 script/prepare_assets.py")

    cat = Image.open(SRC).convert("RGBA")
    frames, size, anchor = build_frames(cat)
    print(f"源图 {cat.width}x{cat.height} -> {len(frames)} 帧,画布 {size[0]}x{size[1]},pivot {anchor}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.png"):
        old.unlink()
    for i, f in enumerate(frames):
        # FASTOCTREE 处理 RGBA 时会把 alpha 编码进调色板项,PNG 的 tRNS 支持逐项 alpha,
        # 所以软边能保住;不开抖动是因为抖动噪声既压不动体积,又会糊掉平整的色块。
        packed = f.quantize(colors=PALETTE_COLORS, method=Image.FASTOCTREE, dither=Image.NONE)
        packed.save(OUT_DIR / f"idle_{i:02d}.png", optimize=True)

    box = union_bbox(frames)
    MANIFEST.write_text(
        json.dumps(
            {
                "actions": {
                    "idle": {
                        "count": len(frames),
                        "fps": FPS,
                        "dir": "frames",
                        "pattern": "idle_{:02d}.png",
                    }
                },
                "canvas": [size[0], size[1]],
                "anchor": [anchor[0], anchor[1]],
                "bbox": [box[0], box[1], box[2], box[3]],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"已写出 {OUT_DIR.relative_to(ROOT)}/idle_00..{len(frames) - 1:02d}.png 与 {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
