"""查询"用户已经多久没碰键鼠了"。

Linux 是这里最麻烦的一环,两条看起来最自然的路都走不通:

  * libXss 的 XScreenSaverQueryInfo —— XWayland 的 X server 根本没编
    MIT-SCREEN-SAVER 扩展,调用"成功"但 idle 恒为 0。所以必须先用
    XQueryExtension 探测扩展是否存在,不能只看返回值。
  * QCursor.pos() 轮询 —— 指针位于别的应用的 Wayland 原生窗口上时,Qt 返回的是
    自己缓存的 lastCursorPosition,不反映桌面级输入,只有指针在本进程窗口上才更新。

真正可靠的来源是合成器自己维护的空闲计时,通过 DBus 暴露:GNOME/mutter 是
org.gnome.Mutter.IdleMonitor,KDE 是 org.freedesktop.ScreenSaver。按可靠性排序
逐个探测,第一个可用的胜出。
"""

import logging
import sys
import time
from typing import Callable, Optional

from PyQt5.QtGui import QCursor

log = logging.getLogger(__name__)

_MUTTER_SERVICE = "org.gnome.Mutter.IdleMonitor"
_MUTTER_PATH = "/org/gnome/Mutter/IdleMonitor/Core"
_MUTTER_IFACE = "org.gnome.Mutter.IdleMonitor"
_SCREENSAVER_IFACES = (
    ("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver"),
    ("org.kde.ScreenSaver", "/ScreenSaver", "org.kde.ScreenSaver"),
    ("org.xfce.ScreenSaver", "/org/xfce/ScreenSaver", "org.xfce.ScreenSaver"),
)

_SS_STATE = 0  # ScreenSaverState: Off / On / Disabled / Failed
_TICK_MS = 1000


def _dbus_uint64(service: str, path: str, iface_name: str, method: str) -> Optional[float]:
    """调一个返回 uint64 毫秒的 DBus 方法,转成秒。失败返回 None。"""
    from PyQt5.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

    if not QDBusConnection.sessionBus().isConnected():
        return None
    iface = QDBusInterface(service, path, iface_name, QDBusConnection.sessionBus())
    if not iface.isValid():
        return None
    reply = iface.call(method)
    if reply.type() != QDBusMessage.ReplyMessage or not reply.arguments():
        return None
    return float(reply.arguments()[0]) / 1000.0


def _make_mutter() -> Optional[Callable[[], float]]:
    if _dbus_uint64(_MUTTER_SERVICE, _MUTTER_PATH, _MUTTER_IFACE, "GetIdletime") is None:
        return None
    return lambda: _dbus_uint64(_MUTTER_SERVICE, _MUTTER_PATH, _MUTTER_IFACE, "GetIdletime")


def _make_screensaver() -> Optional[Callable[[], float]]:
    for service, path, iface_name in _SCREENSAVER_IFACES:
        if _dbus_uint64(service, path, iface_name, "GetSessionIdleTime") is not None:
            return lambda s=service, p=path, i=iface_name: _dbus_uint64(s, p, i, "GetSessionIdleTime")
    return None


def _make_x11() -> Optional[Callable[[], float]]:
    """真 X11 会话下走 XScreenSaver。XWayland 下扩展缺失,直接判不可用。"""
    import ctypes

    try:
        x11 = ctypes.CDLL("libX11.so.6")
        xss = ctypes.CDLL("libXss.so.1")
    except OSError:
        return None

    class XScreenSaverInfo(ctypes.Structure):
        _fields_ = [
            ("window", ctypes.c_ulong),
            ("state", ctypes.c_int),
            ("kind", ctypes.c_int),
            ("til_or_since", ctypes.c_ulong),
            ("idle", ctypes.c_ulong),
            ("event_mask", ctypes.c_ulong),
        ]

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XQueryExtension.restype = ctypes.c_int
    x11.XQueryExtension.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
    xss.XScreenSaverQueryInfo.restype = ctypes.c_int
    xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XScreenSaverInfo)]

    display = x11.XOpenDisplay(None)
    if not display:
        return None

    opcode, event, error = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    has_ss = x11.XQueryExtension(
        display, b"MIT-SCREEN-SAVER", ctypes.byref(opcode), ctypes.byref(event), ctypes.byref(error)
    )
    if not has_ss:
        log.info("X11 display 没有 MIT-SCREEN-SAVER 扩展(XWayland 的典型情况),跳过 libXss")
        x11.XCloseDisplay(display)
        return None

    info = xss.XScreenSaverAllocInfo()
    if not info:
        x11.XCloseDisplay(display)
        return None

    def query() -> float:
        xss.XScreenSaverQueryInfo(display, 0, info)  # 0 = DefaultRootWindow 对绝大多数场景等价
        return info.contents.idle / 1000.0

    return query


def _make_windows() -> Optional[Callable[[], float]]:
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    user32 = ctypes.windll.user32
    lpi = LASTINPUTINFO()
    lpi.cbSize = ctypes.sizeof(LASTINPUTINFO)

    def query() -> float:
        if not user32.GetLastInputInfo(ctypes.byref(lpi)):
            raise OSError("GetLastInputInfo 失败")
        # GetLastInputInfo 配 GetTickCount(32 位);GetTickCount64 没有对应的 64 位字段可配
        elapsed = user32.GetTickCount() - lpi.dwTime
        if elapsed < 0:  # 计数器约 49.7 天回绕一次
            elapsed += 1 << 32
        return elapsed / 1000.0

    user32.GetTickCount.restype = ctypes.c_uint
    return query


def _make_macos() -> Optional[Callable[[], float]]:
    import ctypes

    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    except OSError:
        return None
    # 不声明 argtypes 的话 0xFFFFFFFF 会被符号扩展成 -1,调用直接跑偏
    cg.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
    cg.CGEventSourceSecondsSinceLastEventType.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    k_combined_session_state = 0
    k_any_input_event = 0xFFFFFFFF
    return lambda: float(
        cg.CGEventSourceSecondsSinceLastEventType(k_combined_session_state, k_any_input_event)
    )


def _make_cursor_fallback() -> Callable[[], float]:
    """最后兜底:自己 1Hz 采样全局光标位置。Wayland 原生下不可靠,仅作保底。"""
    state = {"pos": QCursor.pos(), "since": time.monotonic()}

    def query() -> float:
        now = time.monotonic()
        pos = QCursor.pos()
        if pos != state["pos"]:
            state["pos"] = pos
            state["since"] = now
        return now - state["since"]

    return query


def _providers():
    if sys.platform == "win32":
        yield "windows/GetLastInputInfo", _make_windows
        return
    if sys.platform == "darwin":
        yield "macos/CGEventSourceSecondsSinceLastEventType", _make_macos
        return
    yield "linux/mutter-idle-monitor", _make_mutter
    yield "linux/org.freedesktop.ScreenSaver", _make_screensaver
    yield "linux/XScreenSaver(libXss)", _make_x11
    yield "fallback/QCursor-poll", _make_cursor_fallback


class IdleDetector:
    """探测一次可用的空闲时间来源,之后 idle_seconds() 都走它。"""

    def __init__(self):
        self.provider = "unavailable"
        self._query: Optional[Callable[[], float]] = None
        for name, factory in _providers():
            try:
                fn = factory()
            except Exception as exc:  # 探测阶段任何异常都只意味着这个来源不可用
                log.debug("%s 探测失败: %s", name, exc)
                continue
            if fn is None:
                continue
            # 真调一次,确认它不会抛
            try:
                fn()
            except Exception as exc:
                log.debug("%s 首次调用失败: %s", name, exc)
                continue
            self.provider = name
            self._query = fn
            log.info("空闲检测使用 %s", name)
            break
        if self._query is None:
            log.warning("没有可用的空闲检测来源,喝水/上厕所的完成判定会一直记为未完成")

    @property
    def available(self) -> bool:
        return self._query is not None

    def idle_seconds(self) -> Optional[float]:
        if self._query is None:
            return None
        try:
            return self._query()
        except Exception as exc:
            log.warning("查询空闲时间失败(%s): %s", self.provider, exc)
            return None
