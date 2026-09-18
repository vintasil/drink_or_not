"""把用户上传的一张图变成一组"晃来晃去"的待机帧。

这是 `script/prepare_assets.py` + `script/generate_frames.py` 的算法内核,搬进包内是为了
运行时也能跑(右键菜单导入自己的形象)。那两个脚本现在只剩一层壳,转调这里,免得两份
实现各自演化。

抠图链路(原样保留,只去掉了写死的路径):

  1. 取四角均值作为背景色
  2. 从图像边界洪水填充(span fill)吃掉所有与边界连通的背景像素
  3. 只保留最大的前景连通域 —— 水印残余和地面投影是孤立的碎块,这一步丢掉
  4. 在输出分辨率上把二值遮罩按覆盖率(BOX)缩放成抗锯齿的软 alpha
  5. 用 alpha 对边缘像素反混合 F = (C - (1-a)*bg) / a,消掉背景色描边

**但输入自带 alpha 时不走上面这套。** 原脚本是 `Image.open(SRC).convert("RGB")`,把 alpha
直接扔了,然后靠"透明区底下的 RGB 恰好是均匀的纯色"侥幸抠对。用户上传的透明底 PNG 未必
这么老实,所以这里先看 alpha:只要它真的不是全不透明,就以它为准,不猜。
"""

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageChops

log = logging.getLogger(__name__)

Progress = Optional[Callable[[str], None]]

MASK_MAX = 1024  # 抠图工作分辨率,够保拓扑又不至于让纯 Python 洪水填充太慢
OUT_MAX = 360  # 输出单帧最大边长
BG_TOL = 42  # 判定"属于背景"的切比雪夫颜色距离
UNMIX_MIN_A = 0.15  # alpha 低于此值不参与反混合(a 太小除出来是噪声)
CORNER_PATCH = 16

COUNT = 36  # 帧数
FPS = 20  # 播放帧率 -> 36/20 = 1.8s 一个完整摇摆周期
SWAY_DEG = 4.0  # 最大摆角
BOB_PX = 4  # 最大垂直浮动
BREATH = 0.02  # 呼吸缩放幅度
MARGIN = 34  # 画布留白,要够容纳旋转时角点的位移
PALETTE_COLORS = 256  # 打包时量化到 256 色,体积降到约 1/4

SOURCE_MAX = 2048  # 原图存档的最大边,够重新转换用,又不至于把配置目录撑爆

# 自检阈值。抠图是启发式的,一定会失败,失败时得让用户知道而不是塞一张黑图给他。
MIN_FG_RATIO = 0.02  # 低于此值:几乎整张图都被当成背景抠掉了
MAX_FG_RATIO = 0.97  # 高于此值:背景根本没被识别出来(复杂背景照片的典型表现)
MIN_LARGEST_RATIO = 0.5  # 最大连通域占比低于此值:前景太碎(噪点/水印)


class ConversionError(Exception):
    """图压根没法处理(打不开、全透明、抠完什么都没有)。"""


@dataclass
class PreparedSprite:
    """转换好但还没落盘的成品。先备好,用户确认了再写。"""

    frames: List[Image.Image]
    canvas: Tuple[int, int]
    anchor: Tuple[int, int]
    bbox: Tuple[int, int, int, int]
    source: Image.Image
    used_alpha: bool
    whole: bool = False  # 用户选了"整图显示",没抠背景
    problems: List[str] = field(default_factory=list)


# ---------- 抠图:背景色 / 洪水填充 / 连通域 ----------


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


# ---------- 两条抠图路径 ----------


def _fit(source: Image.Image, alpha: Image.Image) -> Image.Image:
    """把裁到包围盒的 (RGB, alpha) 一起缩到 OUT_MAX,返回 RGBA。"""
    ratio = OUT_MAX / max(source.size)
    out_size = (max(1, round(source.width * ratio)), max(1, round(source.height * ratio)))
    rgb = source.resize(out_size, Image.LANCZOS)
    # 遮罩要用 BOX:对二值覆盖率来说它才是正解,LANCZOS 的负瓣会让边缘产生振铃
    soft = alpha.resize(out_size, Image.BOX)
    return Image.merge("RGBA", (*rgb.split(), soft))


def _cutout_from_alpha(rgba: Image.Image) -> Image.Image:
    """输入自带可用的 alpha,直接拿它当遮罩。

    不做反混合:真实 alpha 图的 RGB 本来就是前景色,不是"和某个背景色混出来的",
    再解一次只会把颜色算歪。
    """
    alpha = rgba.getchannel("A")
    box = alpha.getbbox()
    if box is None:
        raise ConversionError("这张图整个都是透明的,没有可见内容。")
    return _fit(rgba.convert("RGB").crop(box), alpha.crop(box))


def _cutout_by_chroma(rgb: Image.Image, progress: Progress = None) -> Tuple[Image.Image, dict]:
    """原脚本的抠图链路。返回成品和一份诊断。"""
    ow, oh = rgb.size

    # 在降采样后的小图上做抠图,拓扑足够,纯 Python 洪水填充也跑得动
    scale = MASK_MAX / max(ow, oh)
    mw, mh = max(1, round(ow * scale)), max(1, round(oh * scale))
    work = rgb.resize((mw, mh), Image.LANCZOS)
    wpix = work.load()

    bg = background_color(wpix, mw, mh)
    _say(progress, f"背景色 {bg}")

    dist = color_distance(wpix, mw, mh, bg)
    near = bytearray(1 if d <= BG_TOL else 0 for d in dist)

    bgmask = flood_from_border(near, mw, mh)
    fg = bytearray(0 if bgmask[i] else 1 for i in range(mw * mh))
    _say(progress, f"背景已吃 {sum(bgmask) * 100.0 / (mw * mh):.1f}%")

    # 只留最大前景域 —— 水印残余和地面投影都是孤立碎块
    keep, area = largest_component(fg, mw, mh)
    total_fg = sum(fg)
    _say(progress, f"保留最大连通域 {area} px(丢掉 {total_fg - area} px 碎块)")

    if area == 0:
        raise ConversionError("抠完什么也没剩下,这张图基本是同一种颜色。")

    mask_img = Image.frombytes("L", (mw, mh), bytes(255 if v else 0 for v in keep))
    box = mask_img.getbbox()
    x0, y0, x1, y1 = box

    # 前景贴着画布边,说明主体被裁断,或者它跟背景是连着的(同色)
    touches_border = x0 <= 0 or y0 <= 0 or x1 >= mw or y1 >= mh

    inv = ow / mw
    src_crop = rgb.crop(
        (int(x0 * inv), int(y0 * inv), min(ow, round(x1 * inv)), min(oh, round(y1 * inv)))
    )
    alpha_crop = mask_img.crop(box)

    ratio = OUT_MAX / max(src_crop.size)
    out_size = (max(1, round(src_crop.width * ratio)), max(1, round(src_crop.height * ratio)))
    out_rgb = src_crop.resize(out_size, Image.LANCZOS)
    out_alpha = alpha_crop.resize(out_size, Image.BOX)

    # 反混合:观测色 C = a*F + (1-a)*bg,解出真实前景色 F
    rpix, apix = out_rgb.load(), out_alpha.load()
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

    stats = {
        "fg_ratio": area / float(mw * mh),
        "largest_ratio": area / float(total_fg) if total_fg else 0.0,
        "touches_border": touches_border,
    }
    return Image.merge("RGBA", (*out_rgb.split(), out_alpha)), stats


def _whole_image(rgba: Image.Image) -> Image.Image:
    """兜底:不抠图,整张图连同背景一起当形象。"""
    ratio = OUT_MAX / max(rgba.size)
    out_size = (max(1, round(rgba.width * ratio)), max(1, round(rgba.height * ratio)))
    scaled = rgba.resize(out_size, Image.LANCZOS)
    # alpha 铺满 —— 用户要的就是"整块图",留着原来的半透明反而奇怪
    return Image.merge("RGBA", (*scaled.convert("RGB").split(), Image.new("L", out_size, 255)))


def _judge(stats: dict) -> List[str]:
    """把诊断翻成人话。返回空列表就是抠图结果看起来正常。"""
    problems = []
    if stats["fg_ratio"] < MIN_FG_RATIO:
        problems.append("几乎整张图都被当成背景抠掉了,前景只剩不到 2%。")
    elif stats["fg_ratio"] > MAX_FG_RATIO:
        problems.append("背景没被识别出来(抠完还剩 97% 以上),多半是背景颜色太杂。")
    if stats["largest_ratio"] < MIN_LARGEST_RATIO:
        problems.append("前景太碎,没有一块完整的主体。")
    if stats["touches_border"]:
        problems.append("主体贴着图片边缘,可能被截断了,也可能它和背景颜色太接近。")
    return problems


def _say(progress: Progress, message: str) -> None:
    if progress is not None:
        progress(message)
    else:
        log.info("%s", message)


# ---------- 摇摆动画 ----------


def build_frames(sprite: Image.Image) -> Tuple[List[Image.Image], Tuple[int, int], Tuple[int, int]]:
    """绕底部中心 pivot 摇摆,生成 COUNT 帧。"""
    w, h = sprite.size
    cw, ch = w + 2 * MARGIN, h + 2 * MARGIN
    # pivot 取原图底部中心;加 MARGIN 后它在画布里的位置
    ax, ay = MARGIN + w // 2, MARGIN + h

    frames = []
    for i in range(COUNT):
        theta = 2 * math.pi * i / COUNT
        rot = math.sin(theta) * SWAY_DEG
        bob = math.sin(theta) * BOB_PX
        breath = 1.0 + math.sin(2 * theta) * BREATH

        spr = sprite
        if abs(breath - 1.0) > 1e-6:
            size = (max(1, round(w * breath)), max(1, round(h * breath)))
            spr = sprite.resize(size, Image.LANCZOS)

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


def union_bbox(frames: List[Image.Image]):
    """所有帧 alpha 的并集包围盒,应用侧用它定位宠物实际占用的区域。"""
    union = frames[0].getchannel("A")
    for f in frames[1:]:
        union = ImageChops.lighter(union, f.getchannel("A"))
    return union.getbbox()


def _shrink_source(src: Image.Image) -> Image.Image:
    """原图存档前先缩一下,别让素材库动辄几百 MB。"""
    if max(src.size) <= SOURCE_MAX:
        return src
    ratio = SOURCE_MAX / max(src.size)
    size = (max(1, round(src.width * ratio)), max(1, round(src.height * ratio)))
    return src.resize(size, Image.LANCZOS)


# ---------- 对外流程 ----------


def _analyze(src_path, *, whole: bool, progress: Progress):
    """读图 -> 抠出透明底主体。返回 (RGBA, 是否用了自带 alpha, 自检问题, 原图 RGBA)。"""
    try:
        with Image.open(src_path) as raw:
            raw.load()
            rgba = raw.convert("RGBA")
    except (OSError, ValueError) as exc:
        raise ConversionError(f"这张图读不出来:{exc}") from exc

    if whole:
        # "整图显示"是用户明确选的兜底,自检没有意义 —— 结果长什么样是可以预期的
        _say(progress, "按整图处理,不做抠图")
        return _whole_image(rgba), False, [], rgba

    alpha = rgba.getchannel("A")
    if alpha.getextrema() != (255, 255):
        _say(progress, "输入自带 alpha,直接采用,跳过抠图")
        return _cutout_from_alpha(rgba), True, [], rgba

    _say(progress, "输入没有 alpha,开始抠背景")
    cut, stats = _cutout_by_chroma(rgba.convert("RGB"), progress)
    return cut, False, _judge(stats), rgba


def cutout_image(src_path, *, whole: bool = False, progress: Progress = None) -> Image.Image:
    """只要抠好的那张 RGBA,不管动画。`script/prepare_assets.py` 走这条。"""
    cut, _, _, _ = _analyze(src_path, whole=whole, progress=progress)
    return cut


def prepare(src_path, *, whole: bool = False, progress: Progress = None) -> PreparedSprite:
    """读图 -> 抠图(或整图) -> 生成帧。不落盘,便于用户先看结果再决定要不要。"""
    cut, used_alpha, problems, rgba = _analyze(src_path, whole=whole, progress=progress)

    _say(progress, "生成摇摆动画")
    frames, canvas, anchor = build_frames(cut)
    box = union_bbox(frames)
    if box is None:
        raise ConversionError("生成的每一帧都是空的,这张图可能全透明。")

    return PreparedSprite(
        frames=frames,
        canvas=canvas,
        anchor=anchor,
        bbox=box,
        source=_shrink_source(rgba),
        used_alpha=used_alpha,
        whole=whole,
        problems=problems,
    )


def write_frames(frames: List[Image.Image], frames_dir: Path) -> None:
    """把帧写进 frames_dir,先清掉旧的。"""
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"):
        old.unlink()
    for i, frame in enumerate(frames):
        # FASTOCTREE 处理 RGBA 时会把 alpha 编码进调色板项,PNG 的 tRNS 支持逐项 alpha,
        # 所以软边能保住;不开抖动是因为抖动噪声既压不动体积,又会糊掉平整的色块。
        packed = frame.quantize(colors=PALETTE_COLORS, method=Image.FASTOCTREE, dither=Image.NONE)
        packed.save(frames_dir / f"idle_{i:02d}.png", optimize=True)


def save(prepared: PreparedSprite, out_dir: Path, *, name: str) -> None:
    """把成品写进 out_dir:frames/、manifest.json、source.png。"""
    out_dir = Path(out_dir)
    write_frames(prepared.frames, out_dir / "frames")
    prepared.source.save(out_dir / "source.png")

    manifest = {
        "actions": {
            "idle": {
                "count": len(prepared.frames),
                "fps": FPS,
                "dir": "frames",
                "pattern": "idle_{:02d}.png",
            }
        },
        "canvas": list(prepared.canvas),
        "anchor": list(prepared.anchor),
        "bbox": list(prepared.bbox),
        "name": name,
        # 整图模式存下来的是个矩形;其余都是抠过背景(或本来就带 alpha)的透明形象
        "cutout": not prepared.whole,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
