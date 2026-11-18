"""Tray app: hotkeys, selection -> prompt -> agent run, settings, updates."""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from .screens import set_dpi_awareness

set_dpi_awareness()  # must happen before Qt or mss touch the screen

from PySide6.QtCore import QObject, QRect, QThread, QTimer, Qt, Signal, Slot  # noqa: E402
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSpinBox,
    QSystemTrayIcon,
)

from . import settings as settings_mod  # noqa: E402
from . import updater  # noqa: E402
from .actions import Executor  # noqa: E402
from .agent import Agent, RunResult, StepEvent  # noqa: E402
from .capture import grab  # noqa: E402
from .geometry import Box, fit_scale  # noqa: E402
from .llm import AuthError, OpenRouterClient  # noqa: E402
from .overlay import Outline, PromptBar, SelectionOverlay  # noqa: E402
from .panel import Panel  # noqa: E402
from .screens import box_to_logical, cursor_pos, screen_rect_logical  # noqa: E402
from .version import __version__  # noqa: E402

log = logging.getLogger("box_agent")
UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000


def to_pynput_hotkey(combo: str) -> str:
    """'ctrl+shift+space' -> '<ctrl>+<shift>+<space>'; single letters stay bare."""
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    return "+".join(p if len(p) == 1 else f"<{p}>" for p in parts)


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(80, 160, 255), 6, Qt.DashLine))
    p.drawRoundedRect(8, 8, 48, 48, 6, 6)
    p.setBrush(QColor(80, 160, 255))
    p.setPen(Qt.NoPen)
    p.drawEllipse(26, 26, 12, 12)
    p.end()
    return QIcon(pm)


class AgentWorker(QObject):
    step = Signal(object)
    point = Signal(int, int)
    finished = Signal(object)
    auth_failed = Signal()

    def __init__(self, agent: Agent, task: str):
        super().__init__()
        self.agent, self.task = agent, task

    @Slot()
    def run(self):
        try:
            result = self.agent.run(self.task)
        except AuthError:
            self.auth_failed.emit()
            result = RunResult("error", "OpenRouter rejected the API key.")
        except Exception as e:  # never kill the app from the worker
            log.exception("Agent crashed")
            result = RunResult("error", f"Unexpected error: {e}")
        self.finished.emit(result)


class RunHandle(QObject):
    """Owns one agent run's worker + thread.

    Results reach `ended` on the GUI thread: the worker's signals are connected to
    bound slots of this object (which lives on the GUI thread), so Qt queues them.
    Lambdas would run on the worker thread and touch widgets from it.
    """

    step = Signal(object)
    point = Signal(int, int)
    ended = Signal(object)
    auth_failed = Signal()

    def __init__(self, agent: Agent, task: str):
        super().__init__()
        self.handled_on_main = False
        self.thread = QThread()
        self.worker = AgentWorker(agent, task)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.step.connect(self._on_step)
        self.worker.point.connect(self._on_point)
        self.worker.auth_failed.connect(self._on_auth_failed)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)

    def start(self) -> None:
        self.thread.start()

    @Slot(object)
    def _on_step(self, ev):
        self.step.emit(ev)

    @Slot(int, int)
    def _on_point(self, x, y):
        self.point.emit(x, y)

    @Slot()
    def _on_auth_failed(self):
        self.auth_failed.emit()

    @Slot(object)
    def _on_finished(self, result):
        self.handled_on_main = threading.current_thread() is threading.main_thread()
        self.thread.wait(2000)
        self.ended.emit(result)


class SettingsDialog(QDialog):
    def __init__(self, s: settings_mod.Settings, message: str = ""):
        super().__init__()
        self.setWindowTitle("Box Agent settings")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.s = s
        form = QFormLayout(self)
        if message:
            msg = QLabel(message)
            msg.setStyleSheet("color:#d9534f")
            form.addRow(msg)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("saved" if settings_mod.get_api_key() else "sk-or-...")
        self.model = QLineEdit(s.model)
        self.steps = QSpinBox()
        self.steps.setRange(1, 200)
        self.steps.setValue(s.max_steps)
        self.dry = QCheckBox("Dry run (show actions, don't click/type)")
        self.dry.setChecked(s.dry_run)
        self.updates = QCheckBox("Check for updates automatically")
        self.updates.setChecked(s.check_updates)
        form.addRow("OpenRouter API key", self.key)
        form.addRow("Model", self.model)
        form.addRow("Max steps", self.steps)
        form.addRow(self.dry)
        form.addRow(self.updates)
        form.addRow("Hotkeys", QLabel(f"Select: {s.hotkey_select}    Stop: {s.hotkey_stop}"))
        form.addRow("Version", QLabel(__version__))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self) -> settings_mod.Settings:
        if self.key.text().strip():
            settings_mod.set_api_key(self.key.text().strip())
        self.s.model = self.model.text().strip() or settings_mod.DEFAULT_MODEL
        self.s.max_steps = self.steps.value()
        self.s.dry_run = self.dry.isChecked()
        self.s.check_updates = self.updates.isChecked()
        settings_mod.save(self.s)
        return self.s


class Controller(QObject):
    select_requested = Signal()
    stop_requested = Signal()
    update_found = Signal(object)

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = settings_mod.load()
        self.panel = Panel()
        self.panel.stop_clicked.connect(self.stop)
        self.panel.update_clicked.connect(self.apply_update)
        self.stop_event = threading.Event()
        self.running = False
        self.pending_release: updater.Release | None = None
        self.run_handle: RunHandle | None = None
        self.outline: Outline | None = None
        self._keep: list = []  # strong refs to transient windows/threads

        self.select_requested.connect(self.start_selection)
        self.stop_requested.connect(self.stop)
        self.update_found.connect(self._on_update_found)

        self.tray = QSystemTrayIcon(make_icon())
        self.tray.setToolTip(f"Box Agent {__version__} — {self.settings.hotkey_select} to select")
        menu = QMenu()
        for text, fn in [
            ("Select box", self.start_selection),
            ("Show panel", self.panel.show),
            ("Settings…", lambda: self.open_settings()),
            ("Check for updates", lambda: self.check_updates(manual=True)),
            ("Quit", self.quit),
        ]:
            act = QAction(text, menu)
            act.triggered.connect(fn)
            menu.addAction(act)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.show()

        self._start_hotkeys()
        if self.settings.check_updates:
            QTimer.singleShot(3000, self.check_updates)
            self._update_timer = QTimer(self)
            self._update_timer.timeout.connect(self.check_updates)
            self._update_timer.start(UPDATE_INTERVAL_MS)
        if not settings_mod.get_api_key():
            QTimer.singleShot(300, lambda: self.open_settings("Enter your OpenRouter API key to start."))
        else:
            self.tray.showMessage("Box Agent", f"Press {self.settings.hotkey_select} to select a box.")

    # --- hotkeys -------------------------------------------------------------
    def _start_hotkeys(self):
        from pynput.keyboard import GlobalHotKeys

        self.hotkeys = GlobalHotKeys({
            to_pynput_hotkey(self.settings.hotkey_select): self.select_requested.emit,
            to_pynput_hotkey(self.settings.hotkey_stop): self.stop_requested.emit,
        })
        self.hotkeys.daemon = True
        self.hotkeys.start()

    # --- flow ----------------------------------------------------------------
    @Slot()
    def start_selection(self):
        if self.running:
            self.tray.showMessage("Box Agent", "Already running. Press the stop hotkey first.")
            return
        ov = SelectionOverlay(cursor_pos)
        ov.selected.connect(self._on_selected)
        ov.cancelled.connect(lambda: self._keep.remove(ov) if ov in self._keep else None)
        self._keep.append(ov)
        ov.start()

    def _on_selected(self, box: Box):
        self._keep = [k for k in self._keep if not isinstance(k, SelectionOverlay)]
        logical = box_to_logical(box.left, box.top, box.width, box.height)
        bar = PromptBar(logical)
        bar.submitted.connect(lambda text: self._start_run(box, logical, text))
        self._keep.append(bar)
        bar.show()

    def _start_run(self, box: Box, logical: QRect, task: str):
        key = settings_mod.get_api_key()
        if not key:
            self.open_settings("Enter your OpenRouter API key first.")
            return
        self.settings = settings_mod.load()
        s = self.settings
        scale = fit_scale(box.width, box.height)
        outline = Outline(logical, logical.width() / max(1, round(box.width * scale)))
        outline.show()
        holder = {}
        self.stop_event.clear()
        executor = Executor(
            box, scale, dry_run=s.dry_run, stop=self.stop_event,
            on_point=lambda x, y: holder["h"].worker.point.emit(x, y),
        )

        def on_step(ev: StepEvent):
            holder["h"].worker.step.emit(ev)

        agent = Agent(
            OpenRouterClient(key, s.model),
            lambda: grab(box),
            executor,
            self.stop_event,
            on_step,
            max_steps=s.max_steps,
            settle_delay=s.settle_delay,
        )
        handle = RunHandle(agent, task)
        holder["h"] = handle
        handle.step.connect(self.panel.add_step)
        handle.point.connect(outline.mark)
        handle.auth_failed.connect(self._on_auth_failed)
        handle.ended.connect(self._on_finished)
        self.run_handle, self.outline = handle, outline

        self.panel.dock_beside(
            Box(logical.x(), logical.y(), logical.width(), logical.height()),
            _rect_tuple(screen_rect_logical(logical.center())),
        )
        self.panel.start_run(task)
        self.panel.show()
        self.running = True
        handle.start()

    @Slot()
    def _on_auth_failed(self):
        self.open_settings("OpenRouter rejected your API key.")

    @Slot(object)
    def _on_finished(self, result: RunResult):
        self.running = False
        if self.outline is not None:
            self.outline.close()
            self.outline = None
        self.run_handle = None
        self.panel.show_result(result)
        self.panel.show()
        if self.pending_release:
            self.panel.show_update(self.pending_release)

    @Slot()
    def stop(self):
        self.stop_event.set()

    # --- settings / updates --------------------------------------------------
    def open_settings(self, message: str = ""):
        dlg = SettingsDialog(settings_mod.load(), message)
        if dlg.exec() == QDialog.Accepted:
            self.settings = dlg.apply()

    def check_updates(self, manual: bool = False):
        def work():
            rel = updater.check_latest()
            if rel:
                self.update_found.emit(rel)
            elif manual:
                self.update_found.emit(None)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_found(self, rel):
        if rel is None:
            self.tray.showMessage("Box Agent", f"You're on the latest version ({__version__}).")
            return
        self.pending_release = rel
        self.panel.show_update(rel)
        self.tray.showMessage("Box Agent", f"Update to v{rel.version} is ready. Open the panel to install.")

    def apply_update(self):
        if self.running:
            QMessageBox.information(None, "Box Agent", "Wait for the current task to finish first.")
            return
        if not self.pending_release:
            return
        try:
            if updater.apply_update(self.pending_release):
                self.quit()
        except Exception as e:
            log.exception("Update failed")
            QMessageBox.warning(None, "Box Agent", f"Update failed: {e}")

    def quit(self):
        self.stop_event.set()
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.tray.hide()
        self.app.quit()


def _rect_tuple(r: QRect) -> tuple[int, int, int, int]:
    return r.x(), r.y(), r.width(), r.height()


def _setup_logging():
    log_dir = settings_mod.default_path().parent
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_dir / "log.txt"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    _setup_logging()
    import keyring

    log.info("Box Agent %s starting; keyring backend: %s", __version__, keyring.get_keyring())
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon())
    controller = Controller(app)  # noqa: F841 - kept alive by this frame
    sys.exit(app.exec())
