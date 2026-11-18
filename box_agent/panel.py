"""Side panel: live step log, final answer, stop button, update banner."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .agent import RunResult, StepEvent
from .geometry import Box
from .updater import Release

GAP = 8
MIN_W = 220

_STATUS = {
    "done": "Done",
    "stopped": "Stopped",
    "limit": "Step limit reached",
    "error": "Error",
}


def dock_rect(box: Box, screen: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    """Place a w*h panel beside `box` inside `screen` (x, y, sw, sh), never overlapping the box.

    Prefers the right side, then the left; if neither fits, shrinks to the wider side.
    """
    sx, sy, sw, sh = screen
    right_room = (sx + sw) - (box.left + box.width) - GAP
    left_room = box.left - sx - GAP
    if right_room >= w:
        x = box.left + box.width + GAP
    elif left_room >= w:
        x = box.left - GAP - w
    elif max(right_room, left_room) >= MIN_W:
        if right_room >= left_room:
            w, x = right_room, box.left + box.width + GAP
        else:
            w, x = left_room, sx
    else:  # box fills the screen: no side fits, float in the top-right corner
        x = sx + sw - w
    h = min(h, sh)
    y = min(max(box.top, sy), sy + sh - h)
    return x, y, w, h


class Panel(QWidget):
    stop_clicked = Signal()
    update_clicked = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowTitle("Box Agent")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(360, 500)

        self._status = QLabel("Idle")
        self._status.setStyleSheet("font-weight:600")
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._result = QLabel("")
        self._result.setWordWrap(True)
        self._result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._copy = QPushButton("Copy answer")
        self._copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._result.text()))
        self._copy.hide()
        self._stop = QPushButton("Stop  (Ctrl+Shift+X)")
        self._stop.clicked.connect(self.stop_clicked)
        self._stop.hide()

        self._update_label = QLabel("")
        self._update_btn = QPushButton("Update")
        self._update_btn.clicked.connect(self.update_clicked)
        self._update_row = QWidget()
        row = QHBoxLayout(self._update_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._update_label, 1)
        row.addWidget(self._update_btn)
        self._update_row.hide()

        lay = QVBoxLayout(self)
        lay.addWidget(self._update_row)
        lay.addWidget(self._status)
        lay.addWidget(self._log, 1)
        lay.addWidget(self._result)
        lay.addWidget(self._copy)
        lay.addWidget(self._stop)

    # --- state -------------------------------------------------------------
    def start_run(self, task: str) -> None:
        self._log.clear()
        self._result.setText("")
        self._copy.hide()
        self._log.appendPlainText(f"Task: {task or '(figure it out)'}")
        self.set_running(True)

    def set_running(self, running: bool) -> None:
        self._stop.setVisible(running)
        if running:
            self._status.setText("Working…")

    def add_step(self, ev: StepEvent) -> None:
        prefix = {"action": "▶", "error": "⚠", "info": "•"}[ev.kind]
        self._log.appendPlainText(f"{ev.step:>2} {prefix} {ev.text}")

    def show_result(self, r: RunResult) -> None:
        self.set_running(False)
        self._status.setText(_STATUS[r.status])
        self._result.setText(r.answer)
        self._copy.setVisible(r.status == "done" and bool(r.answer))

    def show_update(self, rel: Release) -> None:
        self._update_label.setText(f"Update to v{rel.version} available")
        self._update_row.show()

    def dock_beside(self, box_logical: Box, screen: tuple[int, int, int, int]) -> None:
        x, y, w, h = dock_rect(box_logical, screen, 360, 500)
        self.setGeometry(x, y, w, h)

    # --- for tests ---------------------------------------------------------
    def log_text(self) -> str:
        return self._log.toPlainText()

    def result_text(self) -> str:
        return self._result.text()

    def update_text(self) -> str:
        return self._update_label.text()
