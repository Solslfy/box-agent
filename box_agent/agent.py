"""The autonomous loop: screenshot -> model -> validated tool call -> act -> repeat."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

from .actions import FailsafeTriggered
from .capture import Shot
from .llm import AuthError, LLMError, image_part
from .tools import TOOLS, ToolError, parse_tool_call

SYSTEM_PROMPT = (
    "You control the mouse and keyboard, restricted to the screenshot you see. "
    "Achieve the user's task. Click a field before typing into it. After each action "
    "you get a new screenshot - verify the result before moving on. When finished, "
    "or if the task is impossible, call `done` with a short answer/explanation. "
    "If the task is only a question, answer it via `done` without acting. "
    "Always respond with exactly one tool call."
)
DEFAULT_TASK = "Look at this and do whatever it obviously needs (solve it / answer it / complete it)."
REMOVED = {"type": "text", "text": "[earlier screenshot removed]"}
STOPPED = "Stopped by user"


@dataclass
class StepEvent:
    step: int
    kind: Literal["action", "error", "info"]
    text: str


@dataclass
class RunResult:
    status: Literal["done", "stopped", "limit", "error"]
    answer: str


def prune_images(messages: list[dict], keep: int = 3) -> None:
    """Replace all but the latest `keep` screenshots with a placeholder, in place."""
    seen = 0
    for m in reversed(messages):
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for i in range(len(content) - 1, -1, -1):
            if content[i].get("type") == "image_url":
                seen += 1
                if seen > keep:
                    content[i] = dict(REMOVED)


def _screen_message(text: str, shot: Shot) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"{text}\nScreenshot is {shot.width}x{shot.height}px; (0,0) is top-left."},
            image_part(shot.png),
        ],
    }


class Agent:
    def __init__(
        self,
        llm,
        capture: Callable[[], Shot],
        executor,
        stop: threading.Event,
        on_step: Callable[[StepEvent], None],
        max_steps: int = 25,
        settle_delay: float = 0.6,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.llm = llm
        self.capture = capture
        self.executor = executor
        self.stop = stop
        self.on_step = on_step
        self.max_steps = max_steps
        self.settle_delay = settle_delay
        self.sleep = sleep

    def _stopped(self) -> RunResult:
        self.executor.release_all()
        return RunResult("stopped", STOPPED)

    def _wait(self, seconds: float) -> bool:
        """Sleep in small slices; return False if stopped meanwhile."""
        remaining = seconds
        while remaining > 0:
            if self.stop.is_set():
                return False
            chunk = min(0.1, remaining)
            self.sleep(chunk)
            remaining -= chunk
        return not self.stop.is_set()

    def run(self, task: str) -> RunResult:
        shot = self.capture()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            _screen_message(f"Task: {task.strip() or DEFAULT_TASK}", shot),
        ]
        clicked_in_box = False
        for step in range(1, self.max_steps + 1):
            if self.stop.is_set():
                return self._stopped()
            prune_images(messages)
            try:
                reply = self.llm.chat(messages, TOOLS)
            except AuthError:
                raise
            except LLMError as e:
                self.on_step(StepEvent(step, "error", str(e)))
                return RunResult("error", str(e))
            if self.stop.is_set():
                return self._stopped()

            # Some providers omit ids; every tool call needs one so its result can be matched.
            calls = [
                c if c.get("id") else {**c, "id": f"call_{step}_{i}"}
                for i, c in enumerate(reply.get("tool_calls") or [])
            ]
            reply = {**reply, "tool_calls": calls}
            assistant = {"role": "assistant", "content": reply.get("content") or ""}
            if calls:
                assistant["tool_calls"] = calls
            messages.append(assistant)
            extra_ids = [c.get("id") for c in calls[1:]]

            def answer_extras():
                for cid in extra_ids:
                    messages.append({"role": "tool", "tool_call_id": cid,
                                     "content": "Ignored: only one tool call per turn."})

            try:
                action = parse_tool_call(reply, shot.width, shot.height)
                if action.name in ("type", "key") and not clicked_in_box:
                    # keyboard input goes to whatever has focus; make sure that's inside the box
                    raise ToolError(
                        "Click inside the box first so keyboard input goes to the right place.",
                        action.call_id,
                    )
            except ToolError as e:
                self.on_step(StepEvent(step, "error", str(e)))
                if e.call_id is not None:
                    messages.append({"role": "tool", "tool_call_id": e.call_id, "content": f"Error: {e}"})
                    answer_extras()
                else:
                    messages.append({"role": "user", "content": f"Error: {e} Call exactly one tool."})
                continue

            if action.name == "done":
                answer = action.args["answer"]
                self.on_step(StepEvent(step, "info", "Done"))
                return RunResult("done", answer)

            if action.name == "wait":
                if not self._wait(action.args["seconds"]):
                    return self._stopped()
                desc = f"waited {action.args['seconds']:g}s"
            else:
                if self.stop.is_set():
                    return self._stopped()
                try:
                    desc = self.executor.run(action)
                except FailsafeTriggered:
                    return self._stopped()
                if action.name in ("click", "double_click", "drag"):
                    clicked_in_box = True
                if not self._wait(self.settle_delay):
                    return self._stopped()
            self.on_step(StepEvent(step, "action", desc))

            shot = self.capture()
            messages.append({"role": "tool", "tool_call_id": action.call_id, "content": desc})
            answer_extras()
            messages.append(_screen_message("Result of your action:", shot))

        self.on_step(StepEvent(self.max_steps, "info", "Step limit reached"))
        return RunResult("limit", "Step limit reached")
