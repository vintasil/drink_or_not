"""入口:平台预检 -> 单实例 -> 起界面。

平台预检必须在 QApplication 构造之前跑完。Wayland 下客户端不能自行设置窗口坐标,
move() 只会被合成器忽略,宠物就拖不动;所以只要 DISPLAY 可用就强制走 xcb(XWayland),
那里窗口定位和 globalPos() 都是正常的。DISPLAY 为空时只能退回 Wayland 原生,
功能会明显降级,启动时明确告警而不是静默失灵。
"""

import argparse
import logging
import os
import sys
import time

log = logging.getLogger("drink_or_not")

LOG_MAX_BYTES = 1_000_000


def prepare_platform() -> list:
    """必须在 QApplication 构造之前落定。

    返回值是给自检用的一行人话说明,正常启动时忽略。script/check_env.py 也调这一份 ——
    自检报告的头几行必须反映真启动时的实际决策,不能各写各的。
    """
    notes = []
    if sys.platform.startswith("linux"):
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        notes.append(f"会话类型 {session},DISPLAY={os.environ.get('DISPLAY') or '(空)'}")
        current = os.environ.get("QT_QPA_PLATFORM")
        if current:
            notes.append(f"QT_QPA_PLATFORM 已被外部设为 {current},不覆盖")
        elif os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"
            notes.append("已强制 QT_QPA_PLATFORM=xcb(走 XWayland),这样窗口才能自行定位")
        else:
            log.warning(
                "没有 DISPLAY,只能跑在 Wayland 原生模式:宠物无法被拖动定位,"
                "也无法读取全局光标位置。装上 XWayland 后重启即可恢复正常。"
            )
            notes.append("没有 DISPLAY,只能留在 Wayland 原生模式:宠物将无法被拖动定位")
    elif sys.platform == "darwin":
        # macOS 不做干预:Qt 只有一个可用的平台插件(cocoa)。被外部设成 xcb 是灾难
        # ——那得走 XQuartz,窗口层级和托盘全都不对,所以自检里会判 FAIL。
        current = os.environ.get("QT_QPA_PLATFORM")
        if current:
            notes.append(f"QT_QPA_PLATFORM 已被外部设为 {current},这在本平台上是可疑的")
        else:
            notes.append("macOS:不干预 QT_QPA_PLATFORM,由 Qt 自己选 cocoa")
    return notes


def setup_logging(verbose: bool, log_file) -> None:
    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > LOG_MAX_BYTES:
            log_file.replace(log_file.with_suffix(".log.1"))
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def debug_idle() -> int:
    """打印命中的空闲检测来源并连采几次,用来排查"判定为什么一直不通过"。"""
    from PyQt5.QtWidgets import QApplication

    from .activity import IdleDetector

    # 这个引用必须留在变量里:不接住的话 Python 侧引用计数立刻归零,Qt 那边跟着析构,
    # QApplication.instance() 就变成 None 了。QtDBus 需要一个存活的 application 实例。
    qapp = QApplication(sys.argv)
    detector = IdleDetector()
    print(f"平台插件      : {qapp.platformName()}")
    print(f"空闲检测来源  : {detector.provider}")
    if not detector.available:
        print("没有任何可用来源,完成判定会一直记为未完成。")
        return 1
    print("接下来 6 秒每秒采一次。别碰鼠标,数值应该稳步上涨:")
    previous = None
    for _ in range(6):
        value = detector.idle_seconds()
        arrow = ""
        if previous is not None:
            arrow = " ↑" if value > previous else (" =" if value == previous else " ↓ 有输入!")
        print(f"  {value:7.2f}s{arrow}", flush=True)
        previous = value
        time.sleep(1)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="drink-or-not", description="桌面宠物:定时提醒你照顾自己")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印调试日志")
    parser.add_argument("--debug-idle", action="store_true", help="打印空闲检测来源并采样后退出")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="跑环境自检(平台插件/透明/遮罩/空闲检测)后退出",
    )
    parser.add_argument("--hold", action="store_true", help="配合 --self-check:自检完不自动退出")
    args = parser.parse_args()

    # 预检要在任何 Qt 导入之前
    notes = prepare_platform()

    from .config import config_dir

    setup_logging(args.verbose, config_dir() / "drink_or_not.log")

    if args.self_check:
        from .selfcheck import main as selfcheck_main

        return selfcheck_main(notes, args.hold)

    if args.debug_idle:
        return debug_idle()

    from PyQt5.QtCore import QLockFile, Qt
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from . import config as config_mod
    from .app import Application
    from .resources import assets_dir

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName("drink_or_not")
    qapp.setQuitOnLastWindowClosed(False)  # 关掉设置窗口不该把宠物也关了

    lock_path = config_dir() / "instance.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        QMessageBox.information(None, "drink_or_not", "宠物已经在跑了,别养两只。")
        return 0

    log.info("平台插件 %s,Python %s", qapp.platformName(), sys.version.split()[0])
    if not (assets_dir() / "manifest.json").exists():
        QMessageBox.critical(
            None,
            "drink_or_not",
            f"缺少 assets,应用起不来。找的是:\n\n  {assets_dir()}\n\n"
            "源码运行:先跑 script/prepare_assets.py 和 script/generate_frames.py\n"
            "打包产物:说明打包时 assets 没被带进去,跑 --self-check 看详情",
        )
        return 1

    cfg = config_mod.load()
    application = Application(qapp, cfg)
    application.start()
    return qapp.exec_()


if __name__ == "__main__":
    sys.exit(main())
