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


def prepare_platform() -> None:
    if not sys.platform.startswith("linux"):
        return
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    else:
        log.warning(
            "没有 DISPLAY,只能跑在 Wayland 原生模式:宠物无法被拖动定位,"
            "也无法读取全局光标位置。装上 XWayland 后重启即可恢复正常。"
        )


CONSOLE_FLAGS = ("-h", "--help", "-v", "--verbose", "--debug-idle")


def attach_console(argv) -> None:
    """Windows 上把 GUI 程序的输出接回控制台。

    console=False 打的 exe 属于 GUI 子系统,系统不给它控制台,sys.stdout/sys.stderr 是
    None —— print() 和 StreamHandler 都是静默丢弃,`--debug-idle` 会一句不输出地退出。
    从 cmd 里启动时挂到父进程已有控制台(AttachConsole),双击启动则自己开一个,这样
    --debug-idle/-v 两条路都能看到东西。没带这些参数启动(正常双击养猫)就什么都不做。

    开发模式(非 frozen)不处理:管道重定向本来就好使,多余开个黑窗口反而碍事。
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if not any(a in CONSOLE_FLAGS for a in argv):
        return
    if sys.stdout is not None and sys.stderr is not None:
        return

    import ctypes

    kernel32 = ctypes.windll.kernel32
    if not kernel32.AttachConsole(-1):  # -1 = ATTACH_PARENT_PROCESS
        kernel32.AllocConsole()
    try:
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except OSError:
        pass  # 接不上就只能算这次没输出,别为此拦住宠物启动


def setup_logging(verbose: bool, log_file) -> None:
    handlers = [logging.StreamHandler(sys.stderr)] if sys.stderr is not None else []
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > LOG_MAX_BYTES:
            log_file.replace(log_file.with_suffix(".log.1"))
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        pass
    if not handlers:
        handlers = [logging.NullHandler()]
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
    # 要在 argparse 解析之前:--debug-idle 和错误提示都得有地方可写
    attach_console(sys.argv)

    parser = argparse.ArgumentParser(prog="drink-or-not", description="桌面宠物:定时提醒你照顾自己")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印调试日志")
    parser.add_argument("--debug-idle", action="store_true", help="打印空闲检测来源并采样后退出")
    args = parser.parse_args()

    # 预检要在任何 Qt 导入之前
    prepare_platform()

    from .config import config_dir

    setup_logging(args.verbose, config_dir() / "drink_or_not.log")

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
            "缺少 assets,请先运行:\n\n"
            "  uv run python script/prepare_assets.py\n"
            "  uv run python script/generate_frames.py",
        )
        return 1

    cfg = config_mod.load()
    application = Application(qapp, cfg)
    application.start()
    return qapp.exec_()


if __name__ == "__main__":
    sys.exit(main())
