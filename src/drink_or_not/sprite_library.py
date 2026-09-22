"""用户形象素材库。

存在 `<配置目录>/sprites/<id>/` 下,每个形象一个目录,结构和随包的 `assets/` 一模一样
(manifest.json + frames/),所以渲染侧只认目录,不关心它来自哪。

内置形象**不复制**进来,id 固定 `default`,直接指向 `resources.assets_dir()`:它是只读的
随包资源,复制一份既占地方,升级时还要同步两处。

这里刻意不碰 Qt —— 纯文件操作,测试和脚本都能直接用。
"""

import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from . import sprite_convert
from .config import config_dir
from .resources import assets_dir

log = logging.getLogger(__name__)

BUILTIN_ID = "default"
BUILTIN_NAME = "魔法猫（内置）"
MANIFEST = "manifest.json"
PART_SUFFIX = ".part"  # 写一半的临时目录,写完才 rename 成正式目录

_UNSAFE = re.compile(r"[^\w\-]+", re.UNICODE)


@dataclass
class SpriteInfo:
    id: str
    name: str
    path: Path
    builtin: bool = False


def sprites_root() -> Path:
    return config_dir() / "sprites"


def sprite_dir(sprite_id: str) -> Path:
    """形象的资源目录。内置的指向随包 assets。"""
    if sprite_id == BUILTIN_ID:
        return assets_dir()
    return sprites_root() / sprite_id


def _read_manifest(path: Path) -> Optional[dict]:
    try:
        return json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _visible_dirs() -> List[Path]:
    root = sprites_root()
    if not root.is_dir():
        return []
    return [
        child
        for child in sorted(root.iterdir())
        if child.is_dir() and not child.name.endswith(PART_SUFFIX)
    ]


def list_sprites() -> List[SpriteInfo]:
    """内置的永远排第一。半截的目录(上次导入中途失败)自动略过。"""
    out = [SpriteInfo(BUILTIN_ID, BUILTIN_NAME, assets_dir(), builtin=True)]
    for child in _visible_dirs():
        manifest = _read_manifest(child)
        if manifest is None:
            log.warning("素材目录 %s 没有可读的 manifest,跳过", child)
            continue
        out.append(SpriteInfo(child.name, manifest.get("name") or child.name, child))
    return out


def ensure_available(sprite_id: str) -> str:
    """配置里记着的形象可能已经被删了,这时退回内置,别让宠物起不来。"""
    if sprite_id == BUILTIN_ID:
        return BUILTIN_ID
    if (sprites_root() / sprite_id / MANIFEST).is_file():
        return sprite_id
    log.info("形象 %s 已经不在了,退回内置", sprite_id)
    return BUILTIN_ID


def _allocate(name: str) -> Tuple[Path, str]:
    """按形象名挑一个没被占用的目录名,返回 (目录, 显示名)。

    重名时目录拿到 `-2` 后缀,显示名跟着一起变 —— 否则菜单里会并排出现两个一模一样的
    条目,用户没法分辨该点哪个。
    """
    root = sprites_root()
    root.mkdir(parents=True, exist_ok=True)
    slug = _UNSAFE.sub("_", name).strip("_") or "sprite"
    target = root / slug
    n = 2
    while target.exists() or target.with_name(target.name + PART_SUFFIX).exists():
        target = root / f"{slug}-{n}"
        n += 1
    return target, (name if target.name == slug else target.name)


def install(prepared: sprite_convert.PreparedSprite, name: str) -> SpriteInfo:
    """把转换好的成品落盘。先写进 .part 目录再整体改名,中途炸了不会留下半个形象。"""
    target, display = _allocate(name)
    staging = target.with_name(target.name + PART_SUFFIX)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        sprite_convert.save(prepared, staging, name=display)
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    log.info("形象 %s 已存入 %s", display, target)
    return SpriteInfo(target.name, display, target)


def rename_sprite(sprite_id: str, new_name: str) -> None:
    """只改显示名,目录名不动 —— 目录名是 id,改了等于让配置里的引用失效。"""
    if sprite_id == BUILTIN_ID:
        raise ValueError("内置形象不能重命名。")
    path = sprites_root() / sprite_id / MANIFEST
    manifest = _read_manifest(path.parent)
    if manifest is None:
        raise ValueError(f"找不到形象 {sprite_id}。")
    manifest["name"] = new_name
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def delete_sprite(sprite_id: str) -> None:
    if sprite_id == BUILTIN_ID:
        raise ValueError("内置形象不能删除。")
    path = sprites_root() / sprite_id
    if path.is_dir():
        shutil.rmtree(path)
        log.info("形象 %s 已删除", sprite_id)
