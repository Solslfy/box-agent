"""Tool schemas offered to the model, and strict validation of its tool calls."""
from __future__ import annotations

import json
import string
from dataclasses import dataclass


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


_X = {"type": "integer", "description": "x in screenshot pixels"}
_Y = {"type": "integer", "description": "y in screenshot pixels"}

TOOLS: list[dict] = [
    _fn("click", "Click at a point in the screenshot.",
        {"x": _X, "y": _Y, "button": {"type": "string", "enum": ["left", "right", "middle"]}},
        ["x", "y"]),
    _fn("double_click", "Double-click at a point.", {"x": _X, "y": _Y}, ["x", "y"]),
    _fn("drag", "Press at (x1,y1), move to (x2,y2), release.",
        {"x1": _X, "y1": _Y, "x2": _X, "y2": _Y}, ["x1", "y1", "x2", "y2"]),
    _fn("type", "Type text at the current keyboard focus. Click the field first.",
        {"text": {"type": "string"}}, ["text"]),
    _fn("key", "Press a key or combination, e.g. 'enter', 'ctrl+a'.",
        {"combo": {"type": "string"}}, ["combo"]),
    _fn("scroll", "Scroll the mouse wheel at a point. dy>0 scrolls up, dy<0 down (1-10 notches).",
        {"x": _X, "y": _Y, "dy": {"type": "integer"}}, ["x", "y", "dy"]),
    _fn("wait", "Wait for the screen to update (0.2-5 seconds).",
        {"seconds": {"type": "number"}}, ["seconds"]),
    _fn("done", "Finish the task. Give the final answer or a short summary of what was done.",
        {"answer": {"type": "string"}}, ["answer"]),
]

ALLOWED_KEYS: frozenset[str] = frozenset(
    list(string.ascii_lowercase)
    + list(string.digits)
    + [f"f{i}" for i in range(1, 13)]
    + "enter tab esc backspace delete space up down left right home end pageup pagedown insert ctrl shift alt".split()
)

_BLOCKED = {
    frozenset({"alt", "tab"}),
    frozenset({"alt", "f4"}),
    frozenset({"ctrl", "alt", "delete"}),
    frozenset({"ctrl", "alt", "del"}),
    frozenset({"ctrl", "w"}),
    frozenset({"ctrl", "shift", "esc"}),
}


@dataclass(frozen=True)
class Action:
    name: str
    args: dict
    call_id: str


class ToolError(Exception):
    def __init__(self, message: str, call_id: str | None = None):
        super().__init__(message)
        self.call_id = call_id


def is_blocked(combo: str) -> bool:
    parts = [p.strip() for p in combo.lower().split("+")]
    if any(p in ("win", "windows", "cmd", "super", "meta") for p in parts):
        return True
    return frozenset(parts) in _BLOCKED


def parse_tool_call(message: dict, img_w: int, img_h: int) -> Action:
    calls = message.get("tool_calls") or []
    if not calls:
        raise ToolError("Call exactly one tool.")
    call = calls[0]
    call_id = call.get("id")
    fn = call.get("function") or {}
    name = fn.get("name")

    def fail(msg: str):
        raise ToolError(msg, call_id)

    try:
        raw = fn.get("arguments") or "{}"
        args = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (ValueError, TypeError):
        fail("Tool arguments were not valid JSON.")
    if not isinstance(args, dict):
        fail("Tool arguments must be a JSON object.")

    def num(key: str) -> float:
        if key not in args:
            fail(f"Missing argument '{key}'.")
        try:
            return float(args[key])
        except (TypeError, ValueError):
            fail(f"Argument '{key}' must be a number.")

    def point(kx: str, ky: str) -> tuple[int, int]:
        x, y = round(num(kx)), round(num(ky))
        if not (0 <= x < img_w and 0 <= y < img_h):
            fail(f"({x}, {y}) is outside the {img_w}x{img_h} screenshot. Stay inside it.")
        return x, y

    def text(key: str) -> str:
        v = args.get(key)
        if not isinstance(v, str):
            fail(f"Argument '{key}' must be a string.")
        return v

    if name in ("click", "double_click"):
        x, y = point("x", "y")
        out = {"x": x, "y": y}
        if name == "click":
            button = args.get("button", "left")
            if button not in ("left", "right", "middle"):
                fail("button must be left, right or middle.")
            out["button"] = button
        return Action(name, out, call_id)
    if name == "drag":
        x1, y1 = point("x1", "y1")
        x2, y2 = point("x2", "y2")
        return Action(name, {"x1": x1, "y1": y1, "x2": x2, "y2": y2}, call_id)
    if name == "type":
        return Action(name, {"text": text("text")}, call_id)
    if name == "key":
        combo = text("combo").lower().replace(" ", "")
        parts = combo.split("+")
        if is_blocked(combo):
            fail(f"'{combo}' is blocked. Stay inside the box.")
        bad = [p for p in parts if p not in ALLOWED_KEYS]
        if bad:
            fail(f"Unknown key(s): {', '.join(bad)}.")
        return Action(name, {"combo": combo}, call_id)
    if name == "scroll":
        x, y = point("x", "y")
        dy = round(num("dy"))
        if dy == 0 or abs(dy) > 10:
            fail("dy must be between -10 and 10 and not 0.")
        return Action(name, {"x": x, "y": y, "dy": dy}, call_id)
    if name == "wait":
        s = num("seconds")
        if not (0.2 <= s <= 5):
            fail("seconds must be between 0.2 and 5.")
        return Action(name, {"seconds": s}, call_id)
    if name == "done":
        return Action(name, {"answer": text("answer")}, call_id)
    fail(f"Unknown tool '{name}'.")
