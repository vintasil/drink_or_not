"""把原图抠成透明底的 assets/cat.png。

原图 pic/cat/magic_cat.png 是 2048x2048 的 RGB 图,没有 alpha 通道,米白背景上
还叠着即梦AI 水印和一团地面投影。处理链路:

  1. 取四角均值作为背景色
  2. 从图像边界洪水填充(span fill)吃掉所有与边界连通的背景像素
  3. 只保留最大的前景连通域 —— 水印残余和地面投影是孤立的碎块,这一步丢掉
  4. 在输出分辨率上把二值遮罩按覆盖率(BOX)缩放成抗锯齿的软 alpha
  5. 用 alpha 对边缘像素反混合 F = (C - (1-a)*bg) / a,消掉米白描边

原图只读,不会被修改。
"""

from pathlib import Path
from statistics import median

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "pic" / "fuck" / "labi.png"
DST = ROOT / "assets" / "cat.png"

MASK_MAX = 1024  # 抠图工作分辨率,够保拓扑又不至于让纯 Python 洪水填充太慢
OUT_MAX = 360  # 输出单帧最大边长
BG_TOL = 42  # 判定"属于背景"的切比雪夫颜色距离
UNMIX_MIN_A = 0.15  # alpha 低于此值不参与反混合(a 太小除出来是噪声)
CORNER_PATCH = 16


def background_color(pix, w, h):
    """四角各取一小块,逐通道取中位数当背景色。"""
    corners = [
        (0, 0),
        (w - CORNER_PATCH, 0),
        (0, h - CORNER_PATCH),
        (w - CORNER_PATCH, h - CORNER_PATCH),
    ]
    samples = [[], [], []]
    for ox, oy in corners:
        for y in range(oy, oy + CORNER_PATCH):
            for x in range(ox, ox + CORNER_PATCH):
                p = pix[x, y]
                samples[0].append(p[0])
                samples[1].append(p[1])
                samples[2].append(p[2])
    return tuple(int(median(c)) for c in samples)


def color_distance(pix, w, h, bg):
    """逐像素到背景色的切比雪夫距离(只看最大通道差,抗抗锯齿混色)。"""
    br, bgc, bb = bg
    dist = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            r, g, b = pix[x, y]
            d = abs(r - br)
            dg = abs(g - bgc)
            if dg > d:
                d = dg
            db = abs(b - bb)
            if db > d:
                d = db
            dist[row + x] = d if d < 255 else 255
    return dist


def flood_from_border(near, w, h):
    """在 near 区域内从图像边界做 4 连通 span fill,返回被吃掉的像素标记。"""
    bg = bytearray(w * h)
    stack = []
    for x in range(w):
        if near[x]:
            stack.append((x, 0))
        if near[(h - 1) * w + x]:
            stack.append((x, h - 1))
    for y in range(h):
        if near[y * w]:
            stack.append((0, y))
        if near[y * w + w - 1]:
            stack.append((w - 1, y))

    while stack:
        x, y = stack.pop()
        if bg[y * w + x]:
            continue
        row = y * w
        left = x
        while left > 0 and near[row + left - 1] and not bg[row + left - 1]:
            left -= 1
        right = x
        while right < w - 1 and near[row + right + 1] and not bg[row + right + 1]:
            right += 1
        for i in range(left, right + 1):
            bg[row + i] = 1
        for ny in (y - 1, y + 1):
            if not 0 <= ny < h:
                continue
            nrow = ny * w
            i = left
            while i <= right:
                if near[nrow + i] and not bg[nrow + i]:
                    stack.append((i, ny))
                    while i <= right and near[nrow + i]:
                        i += 1
                else:
                    i += 1
    return bg


def largest_component(fg, w, h):
    """返回最大的 4 连通前景域掩码。

    visited 必须是常驻的:每个前景像素只能被访问一次。若改成每个连通域用完就清空
    标记,外层种子扫描每走过一行都会把横跨该行的大连通域整个重填一遍,N 行下来就是
    O(N^2)。
    """
    visited = bytearray(w * h)
    best_pixels = []
    stack = []
    current = []

    for y0 in range(h):
        base = y0 * w
        for x0 in range(w):
            start = base + x0
            if not fg[start] or visited[start]:
                continue
            current.clear()
            stack.append((x0, y0))
            while stack:
                x, y = stack.pop()
                idx = y * w + x
                if visited[idx]:
                    continue
                row = idx - x
                left = x
                while left > 0 and fg[row + left - 1] and not visited[row + left - 1]:
                    left -= 1
                right = x
                while right < w - 1 and fg[row + right + 1] and not visited[row + right + 1]:
                    right += 1
                for i in range(left, right + 1):
                    visited[row + i] = 1
                    current.append(row + i)
                for ny in (y - 1, y + 1):
                    if not 0 <= ny < h:
                        continue
                    nrow = ny * w
                    i = left
                    while i <= right:
                        if fg[nrow + i] and not visited[nrow + i]:
                            stack.append((i, ny))
                            while i <= right and fg[nrow + i]:
                                i += 1
                        else:
                            i += 1
            if len(current) > len(best_pixels):
                best_pixels = list(current)

    mask = bytearray(w * h)
    for i in best_pixels:
        mask[i] = 1
    return mask, len(best_pixels)


def main():
    if not SRC.exists():
        raise SystemExit(f"找不到原图:{SRC}")

    src = Image.open(SRC).convert("RGB")
    ow, oh = src.size
    print(f"原图 {ow}x{oh} {src.mode}")

    # 1~2. 在降采样后的小图上做抠图,拓扑足够,纯 Python 洪水填充也跑得动
    scale = MASK_MAX / max(ow, oh)
    mw, mh = max(1, round(ow * scale)), max(1, round(oh * scale))
    work = src.resize((mw, mh), Image.LANCZOS)
    wpix = work.load()

    bg = background_color(wpix, mw, mh)
    print(f"背景色 {bg}")

    dist = color_distance(wpix, mw, mh, bg)
    near = bytearray(1 if d <= BG_TOL else 0 for d in dist)

    bgmask = flood_from_border(near, mw, mh)
    fg = bytearray(0 if bgmask[i] else 1 for i in range(mw * mh))
    print(f"背景已吃 {sum(bgmask) * 100.0 / (mw * mh):.1f}%")

    # 3. 只留最大前景域 —— 水印残余和地面投影都是孤立碎块
    keep, area = largest_component(fg, mw, mh)
    print(f"保留最大连通域 {area} px(丢掉 {sum(fg) - area} px 碎块)")

    mask_img = Image.frombytes("L", (mw, mh), bytes(255 if v else 0 for v in keep))
    box = mask_img.getbbox()
    if box is None:
        raise SystemExit("抠图失败:没有找到任何前景像素")
    x0, y0, x1, y1 = box
    print(f"包围盒 {x1 - x0}x{y1 - y0} @ ({x0},{y0})")

    # 裁到包围盒,避免缩放后大而无用
    keep_crop = mask_img.crop(box)

    inv = ow / mw
    src_crop = src.crop(
        (int(x0 * inv), int(y0 * inv), min(ow, round(x1 * inv)), min(oh, round(y1 * inv)))
    )

    # 4. 缩到输出尺寸。RGB 用 LANCZOS;遮罩用 BOX —— 对二值覆盖率来说 BOX 才是正解,
    #    LANCZOS 的负瓣会让边缘产生振铃。
    ratio = OUT_MAX / max(src_crop.size)
    out_size = (max(1, round(src_crop.width * ratio)), max(1, round(src_crop.height * ratio)))
    rgb = src_crop.resize(out_size, Image.LANCZOS)
    alpha = keep_crop.resize(out_size, Image.BOX)
    print(f"输出 {out_size[0]}x{out_size[1]}")

    # 5. 反混合:观测色 C = a*F + (1-a)*bg,解出真实前景色 F
    rpix, apix = rgb.load(), alpha.load()
    for y in range(out_size[1]):
        for x in range(out_size[0]):
            a = apix[x, y] / 255.0
            if a <= UNMIX_MIN_A:
                continue
            r, g, b = rpix[x, y]
            rpix[x, y] = (
                max(0, min(255, round((r - (1 - a) * bg[0]) / a))),
                max(0, min(255, round((g - (1 - a) * bg[1]) / a))),
                max(0, min(255, round((b - (1 - a) * bg[2]) / a))),
            )

    out = Image.merge("RGBA", (*rgb.split(), alpha))
    DST.parent.mkdir(parents=True, exist_ok=True)
    out.save(DST)
    print(f"已写出 {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
