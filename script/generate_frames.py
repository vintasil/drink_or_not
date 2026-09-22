"""把 assets/cat.png 生成一组"晃来晃去"的待机帧。

摇摆算法在 `drink_or_not.sprite_convert` 里 —— 运行时用户导入自己的形象走的是同一份。
这里只负责指定仓库内的路径,并写出随包的那份 manifest.json(它比用户素材的 manifest
少几个字段,渲染侧只认 actions/canvas/bbox)。

将来用 AI 画好逐帧图,直接覆盖 assets/frames/ 并改 assets/manifest.json 即可。

    uv run python script/generate_frames.py
"""

import json
from pathlib import Path

from PIL import Image

from drink_or_not import sprite_convert

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "cat.png"
OUT_DIR = ROOT / "assets" / "frames"
MANIFEST = ROOT / "assets" / "manifest.json"


def main():
    if not SRC.exists():
        raise SystemExit(f"找不到 {SRC.relative_to(ROOT)},请先运行 script/prepare_assets.py")

    cat = Image.open(SRC).convert("RGBA")
    frames, size, anchor = sprite_convert.build_frames(cat)
    print(f"源图 {cat.width}x{cat.height} -> {len(frames)} 帧,画布 {size[0]}x{size[1]},pivot {anchor}")

    sprite_convert.write_frames(frames, OUT_DIR)
    box = sprite_convert.union_bbox(frames)
    MANIFEST.write_text(
        json.dumps(
            {
                "actions": {
                    "idle": {
                        "count": len(frames),
                        "fps": sprite_convert.FPS,
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
