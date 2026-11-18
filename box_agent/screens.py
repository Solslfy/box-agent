"""Map between Qt logical coordinates and Windows physical pixels (per-monitor DPI)."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def set_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def cursor_pos() -> tuple[int, int]:
    """Physical cursor position (the process is per-monitor DPI aware)."""
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def monitor_rects() -> dict[str, tuple[int, int, int, int]]:
    """Device name -> physical (left, top, right, bottom)."""
    out: dict[str, tuple[int, int, int, int]] = {}
    proc_t = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )

    def cb(hmon, _hdc, _rect, _lp):
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            out[info.szDevice] = (r.left, r.top, r.right, r.bottom)
        return True

    _user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    return out


def _screen_origins():
    """Yield (QScreen, physical_left, physical_top, dpr)."""
    rects = monitor_rects()
    for s in QGuiApplication.screens():
        g, dpr = s.geometry(), s.devicePixelRatio()
        r = rects.get(s.name())
        if r is None:  # fallback: assume logical origin * dpr
            yield s, round(g.x() * dpr), round(g.y() * dpr), dpr
        else:
            yield s, r[0], r[1], dpr


def to_logical(px: int, py: int) -> QPoint:
    """Physical pixel -> Qt logical point, using the monitor that contains it."""
    best = None
    for s, ox, oy, dpr in _screen_origins():
        g = s.geometry()
        w, h = round(g.width() * dpr), round(g.height() * dpr)
        if ox <= px < ox + w and oy <= py < oy + h:
            return QPoint(g.x() + round((px - ox) / dpr), g.y() + round((py - oy) / dpr))
        best = best or (s, ox, oy, dpr)
    s, ox, oy, dpr = best
    g = s.geometry()
    return QPoint(g.x() + round((px - ox) / dpr), g.y() + round((py - oy) / dpr))


def box_to_logical(left: int, top: int, width: int, height: int) -> QRect:
    a = to_logical(left, top)
    b = to_logical(left + width - 1, top + height - 1)
    return QRect(a, b)


def screen_rect_logical(p: QPoint) -> QRect:
    s = QGuiApplication.screenAt(p) or QGuiApplication.primaryScreen()
    return s.availableGeometry()
