"""Execute validated actions with real mouse/keyboard input (pynput)."""
from __future__ import annotations

import time
from typing import Callable

from pynput.keyboard import Key
from pynput.mouse import Button

from .geometry import Box, to_screen
from .tools import Action

FAILSAFE_MARGIN = 2

_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}
_SPECIAL = {
    "enter": Key.enter, "tab": Key.tab, "esc": Key.esc, "backspace": Key.backspace,
    "delete": Key.delete, "space": Key.space, "up": Key.up, "down": Key.down,
    "left": Key.left, "right": Key.right, "home": Key.home, "end": Key.end,
    "pageup": Key.page_up, "pagedown": Key.page_down, "insert": Key.insert,
    "ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt,
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}
_MODIFIERS = {"ctrl", "shift", "alt"}


class FailsafeTriggered(Exception):
    """The mouse is parked in a screen corner: the user wants the agent to stop."""


def _default_corners() -> list[tuple[int, int]]:
    import mss

    with mss.mss() as s:
        m = s.monitors[0]  # whole virtual desktop
    l, t, w, h = m["left"], m["top"], m["width"], m["height"]
    return [(l, t), (l + w - 1, t), (l, t + h - 1), (l + w - 1, t + h - 1)]


class Executor:
    def __init__(
        self,
        box: Box,
        scale: float,
        mouse=None,
        keyboard=None,
        dry_run: bool = False,
        corners: list[tuple[int, int]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        on_point: Callable[[int, int], None] | None = None,
    ):
        if mouse is None:
            from pynput.mouse import Controller as MouseController

            mouse = MouseController()
        if keyboard is None:
            from pynput.keyboard import Controller as KeyboardController

            keyboard = KeyboardController()
        self.box = box
        self.scale = scale
        self.mouse = mouse
        self.keyboard = keyboard
        self.dry_run = dry_run
        self.corners = corners if corners is not None else _default_corners()
        self.sleep = sleep
        self.on_point = on_point  # dry run: told the image points it would have used

    def _check_failsafe(self) -> None:
        mx, my = self.mouse.position
        for cx, cy in self.corners:
            if abs(mx - cx) <= FAILSAFE_MARGIN and abs(my - cy) <= FAILSAFE_MARGIN:
                raise FailsafeTriggered("Mouse moved to a screen corner")

    def _pt(self, x: int, y: int) -> tuple[int, int]:
        return to_screen(x, y, self.box, self.scale)

    def run(self, action: Action) -> str:
        a, n = action.args, action.name
        if n in ("click", "double_click", "scroll"):
            sx, sy = self._pt(a["x"], a["y"])
        if n == "click":
            desc = f"click {a['button']} at ({sx}, {sy})"
        elif n == "double_click":
            desc = f"double-click at ({sx}, {sy})"
        elif n == "drag":
            p1, p2 = self._pt(a["x1"], a["y1"]), self._pt(a["x2"], a["y2"])
            desc = f"drag from {p1} to {p2}"
        elif n == "type":
            desc = f"type {a['text']!r}"
        elif n == "key":
            desc = f"press {a['combo']}"
        elif n == "scroll":
            desc = f"scroll {a['dy']:+d} at ({sx}, {sy})"
        else:
            raise ValueError(f"Executor cannot run '{n}'")

        if self.dry_run:
            if self.on_point:
                if n == "drag":
                    self.on_point(a["x1"], a["y1"])
                    self.on_point(a["x2"], a["y2"])
                elif "x" in a:
                    self.on_point(a["x"], a["y"])
            return "[dry run] " + desc
        self._check_failsafe()

        if n == "click":
            self.mouse.position = (sx, sy)
            self.mouse.click(_BUTTONS[a["button"]], 1)
        elif n == "double_click":
            self.mouse.position = (sx, sy)
            self.mouse.click(Button.left, 2)
        elif n == "drag":
            self._drag(p1, p2)
        elif n == "type":
            self._type(a["text"])
        elif n == "key":
            self._key(a["combo"])
        elif n == "scroll":
            self.mouse.position = (sx, sy)
            self.mouse.scroll(0, a["dy"])
        return desc

    def _drag(self, p1, p2, steps: int = 10) -> None:
        self.mouse.position = p1
        self.mouse.press(Button.left)
        try:
            for i in range(1, steps + 1):
                self.sleep(0.02)
                self.mouse.position = (
                    round(p1[0] + (p2[0] - p1[0]) * i / steps),
                    round(p1[1] + (p2[1] - p1[1]) * i / steps),
                )
        finally:
            self.mouse.release(Button.left)

    def _type(self, text: str) -> None:
        for i, part in enumerate(text.split("\n")):
            if i:
                self.keyboard.tap(Key.enter)
            if part:
                self.keyboard.type(part)

    def _key(self, combo: str) -> None:
        parts = combo.split("+")
        *mods, last = parts
        pressed = []
        try:
            for m in mods:
                k = _SPECIAL[m]
                self.keyboard.press(k)
                pressed.append(k)
            self.keyboard.tap(_SPECIAL.get(last, last))
        finally:
            for k in reversed(pressed):
                self.keyboard.release(k)

    def release_all(self) -> None:
        for m in _MODIFIERS:
            try:
                self.keyboard.release(_SPECIAL[m])
            except Exception:
                pass
        for b in _BUTTONS.values():
            try:
                self.mouse.release(b)
            except Exception:
                pass
