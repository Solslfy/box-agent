"""Box selection overlay, prompt bar and the click-through outline."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QWidget

from .geometry import Box

MIN_SIZE = 20
ACCENT = QColor(80, 160, 255)


def normalize_selection(x1: int, y1: int, x2: int, y2: int) -> tuple[int, int, int, int] | None:
    """Two corners (physical px) -> (left, top, width, height), or None if smaller than 20x20."""
    left, top = min(x1, x2), min(y1, y2)
    w, h = abs(x2 - x1), abs(y2 - y1)
    if w < MIN_SIZE or h < MIN_SIZE:
        return None
    return left, top, w, h


class _ScreenDim(QWidget):
    """Dims one screen and lets the user drag a rectangle on it."""

    def __init__(self, screen, owner: "SelectionOverlay"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.owner = owner
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen.geometry())
        self.start: QPoint | None = None
        self.end: QPoint | None = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 102))
        if self.start and self.end:
            r = QRect(self.start, self.end).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.fillRect(r, QColor(255, 255, 255, 1))  # keep the area hit-testable
            p.setPen(QPen(ACCENT, 2))
            p.drawRect(r)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.start = self.end = e.position().toPoint()
            self.owner.press()

    def mouseMoveEvent(self, e):
        if self.start:
            self.end = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.start:
            self.owner.release()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.owner.cancel()


class SelectionOverlay(QWidget):
    """Coordinator: one dimming window per screen. Emits `selected(Box)` or `cancelled()`."""

    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, cursor_pos):
        super().__init__()
        self._cursor_pos = cursor_pos  # () -> physical (x, y)
        self._p1 = None
        self._windows = [_ScreenDim(s, self) for s in QGuiApplication.screens()]

    def start(self):
        for w in self._windows:
            w.show()
            w.raise_()
        under = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        if self._windows:
            self._windows[0].activateWindow()

    def press(self):
        self._p1 = self._cursor_pos()

    def release(self):
        p2 = self._cursor_pos()
        rect = normalize_selection(*self._p1, *p2) if self._p1 else None
        if rect is None:  # too small: let them try again
            self._p1 = None
            for w in self._windows:
                w.start = w.end = None
                w.update()
            return
        self._close()
        self.selected.emit(Box(*rect))

    def cancel(self):
        self._close()
        self.cancelled.emit()

    def _close(self):
        for w in self._windows:
            w.close()
        self._windows = []


class PromptBar(QWidget):
    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self, anchor: QRect):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setStyleSheet(
            "QWidget{background:#1e1e24;color:#eee;border-radius:6px}"
            "QLineEdit{border:1px solid #5aa0ff;padding:6px;font-size:14px}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("What should the AI do? (Enter = figure it out, Esc = cancel)")
        lay.addWidget(self.edit)
        width = max(360, min(anchor.width(), 640))
        self.resize(width, 44)
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        y = anchor.bottom() + 8
        if y + 44 > area.bottom():
            y = max(area.top(), anchor.top() - 52)
        x = min(max(anchor.left(), area.left()), area.right() - width)
        self.move(x, y)
        self.edit.returnPressed.connect(self._submit)

    def showEvent(self, e):
        super().showEvent(e)
        self.activateWindow()
        self.edit.setFocus()

    def _submit(self):
        text = self.edit.text()
        self.close()
        self.submitted.emit(text)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()


class Outline(QWidget):
    """A click-through border drawn just outside the box (so screenshots never include it)."""

    BORDER = 3

    def __init__(self, box_logical: QRect, scale_to_logical: float):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        b = self.BORDER
        self.setGeometry(box_logical.adjusted(-b - 1, -b - 1, b + 1, b + 1))
        self._k = scale_to_logical  # image px -> logical px
        self._marks: list[QPoint] = []

    def mark(self, x: int, y: int) -> None:
        """Crosshair at an image coordinate (dry run). Fades after 1.5 s."""
        b = self.BORDER + 1
        pt = QPoint(b + round(x * self._k), b + round(y * self._k))
        self._marks.append(pt)
        self.update()
        QTimer.singleShot(1500, lambda: (self._marks.remove(pt) if pt in self._marks else None, self.update()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QPen(ACCENT, self.BORDER))
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.setPen(QPen(QColor(255, 80, 80), 2))
        for m in self._marks:
            p.drawLine(m.x() - 8, m.y(), m.x() + 8, m.y())
            p.drawLine(m.x(), m.y() - 8, m.x(), m.y() + 8)
