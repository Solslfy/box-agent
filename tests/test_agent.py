import json
import threading

import pytest

from box_agent.actions import FailsafeTriggered
from box_agent.agent import Agent, RunResult, prune_images
from box_agent.capture import Shot
from box_agent.llm import AuthError, LLMError


def call(name, args, id="c1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)}}]}


class FakeLLM:
    def __init__(self, replies, on_chat=None):
        self.replies = list(replies)
        self.calls = []
        self.on_chat = on_chat

    def chat(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        if self.on_chat:
            self.on_chat()
        r = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(r, Exception):
            raise r
        return r


class FakeExecutor:
    def __init__(self, raise_exc=None):
        self.ran = []
        self.released = False
        self.raise_exc = raise_exc

    def run(self, action):
        if self.raise_exc:
            raise self.raise_exc
        self.ran.append(action)
        return f"did {action.name}"

    def release_all(self):
        self.released = True


def shot():
    return Shot(b"\x89PNGx", 100, 100, 1.0)


def make(replies, max_steps=25, executor=None, sleep=None, on_chat=None):
    stop = threading.Event()
    events = []
    llm = FakeLLM(replies, on_chat)
    ex = executor or FakeExecutor()
    agent = Agent(llm, shot, ex, stop, events.append, max_steps=max_steps,
                  settle_delay=0.0, sleep=sleep or (lambda s: None))
    return agent, llm, ex, stop, events


def images_in(messages):
    return [p for m in messages if isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "image_url"]


def test_done_first_step():
    agent, llm, ex, _, _ = make([call("done", {"answer": "42"})])
    assert agent.run("solve") == RunResult("done", "42")
    assert ex.ran == []


def test_first_message_has_task_and_image():
    agent, llm, _, _, _ = make([call("done", {"answer": "x"})])
    agent.run("")
    first_user = llm.calls[0][1]
    assert "Look at this" in first_user["content"][0]["text"]
    assert "100x100" in first_user["content"][0]["text"]
    assert len(images_in(llm.calls[0])) == 1


def test_click_then_done():
    agent, llm, ex, _, events = make([call("click", {"x": 1, "y": 2}), call("done", {"answer": "ok"})])
    assert agent.run("t").status == "done"
    assert [a.name for a in ex.ran] == ["click"]
    second = llm.calls[1]
    assert second[-2]["role"] == "tool" and second[-2]["tool_call_id"] == "c1"
    assert second[-1]["role"] == "user" and images_in([second[-1]])
    assert any(e.kind == "action" for e in events)


def test_invalid_call_counts_as_step_and_continues():
    agent, llm, ex, _, events = make([call("click", {"x": 500, "y": 2}), call("done", {"answer": "ok"})])
    assert agent.run("t").status == "done"
    assert ex.ran == []
    assert any(e.kind == "error" for e in events)
    assert llm.calls[1][-1]["role"] == "tool"
    assert llm.calls[1][-1]["content"].startswith("Error:")


def test_no_tool_call_gets_reminder():
    agent, llm, _, _, _ = make([{"role": "assistant", "content": "hmm"}, call("done", {"answer": "ok"})])
    agent.run("t")
    assert llm.calls[1][-1]["role"] == "user"
    assert "Call exactly one tool" in llm.calls[1][-1]["content"]


def test_extra_tool_calls_get_responses():
    reply = call("click", {"x": 1, "y": 1}, "a")
    reply["tool_calls"].append(call("click", {"x": 2, "y": 2}, "b")["tool_calls"][0])
    agent, llm, ex, _, _ = make([reply, call("done", {"answer": "ok"})])
    agent.run("t")
    tool_ids = [m["tool_call_id"] for m in llm.calls[1] if m["role"] == "tool"]
    assert tool_ids == ["a", "b"]
    assert len(ex.ran) == 1


def test_step_limit():
    agent, llm, ex, _, _ = make([call("click", {"x": 1, "y": 1})], max_steps=3)
    assert agent.run("t").status == "limit"
    assert len(llm.calls) == 3


def test_stop_while_llm_in_flight():
    holder = {}
    agent, llm, ex, stop, _ = make([call("click", {"x": 1, "y": 1})],
                                   on_chat=lambda: holder["stop"].set())
    holder["stop"] = stop
    assert agent.run("t") == RunResult("stopped", "Stopped by user")
    assert ex.ran == [] and ex.released


def test_stop_during_wait():
    slept = []
    holder = {}

    def sleep(s):
        slept.append(s)
        holder["stop"].set()

    agent, llm, ex, stop, _ = make([call("wait", {"seconds": 5})], sleep=sleep)
    holder["stop"] = stop
    assert agent.run("t").status == "stopped"
    assert sum(slept) < 0.5


def test_failsafe_stops():
    agent, _, ex, _, _ = make([call("click", {"x": 1, "y": 1})],
                              executor=FakeExecutor(FailsafeTriggered("corner")))
    assert agent.run("t").status == "stopped"
    assert ex.released


def test_llm_error_returns_error():
    agent, _, _, _, _ = make([LLMError("boom")])
    assert agent.run("t") == RunResult("error", "boom")


def test_auth_error_propagates():
    agent, _, _, _, _ = make([AuthError("bad key")])
    with pytest.raises(AuthError):
        agent.run("t")


def test_type_before_click_refused():
    agent, llm, ex, _, events = make([call("type", {"text": "hi"}), call("click", {"x": 1, "y": 1}),
                                      call("type", {"text": "hi"}), call("done", {"answer": "ok"})])
    assert agent.run("t").status == "done"
    assert [a.name for a in ex.ran] == ["click", "type"]
    assert "Click inside the box first" in llm.calls[1][-1]["content"]


def test_key_before_click_refused():
    agent, _, ex, _, _ = make([call("key", {"combo": "enter"}), call("done", {"answer": "ok"})])
    agent.run("t")
    assert ex.ran == []


def test_missing_tool_call_id_is_synthesized():
    reply = call("click", {"x": 1, "y": 1})
    del reply["tool_calls"][0]["id"]
    agent, llm, ex, _, _ = make([reply, call("done", {"answer": "ok"})])
    assert agent.run("t").status == "done"
    msgs = llm.calls[1]
    assistant = [m for m in msgs if m["role"] == "assistant"][0]
    tool = [m for m in msgs if m["role"] == "tool"][0]
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"]
    assert tool["tool_call_id"]


def test_prune_images_keeps_latest_3():
    msgs = [{"role": "user", "content": [{"type": "text", "text": str(i)},
                                         {"type": "image_url", "image_url": {"url": f"u{i}"}}]}
            for i in range(5)]
    prune_images(msgs, keep=3)
    urls = [p["image_url"]["url"] for p in images_in(msgs)]
    assert urls == ["u2", "u3", "u4"]
    assert msgs[0]["content"][1] == {"type": "text", "text": "[earlier screenshot removed]"}
