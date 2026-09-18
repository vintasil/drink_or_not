"""把原图 pic/cat/magic_cat.png 抠成透明底的 assets/cat.png。

抠图算法在 `drink_or_not.sprite_convert` 里 —— 运行时用户导入自己的形象走的是同一份,
这里只负责指定仓库内的路径,免得两份实现各自演化。原图只读,不会被修改。

    uv run python script/prepare_assets.py
"""

from pathlib import Path

from drink_or_not import sprite_convert

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pic" / "cat" / "magic_cat.png"
DST = ROOT / "assets" / "cat.png"


def main():
    if not SRC.exists():
        raise SystemExit(f"找不到原图:{SRC}")

    print(f"原图 {SRC.relative_to(ROOT)}")
    out = sprite_convert.cutout_image(SRC, progress=print)
    print(f"成品 {out.width}x{out.height} {out.mode}")

    DST.parent.mkdir(parents=True, exist_ok=True)
    out.save(DST)
    print(f"已写出 {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
