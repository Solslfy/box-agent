import json

import pytest

from box_agent.tools import TOOLS, Action, ToolError, parse_tool_call

W, H = 400, 300


def msg(name, args, id="c1"):
    raw = args if isinstance(args, str) else json.dumps(args)
    return {"tool_calls": [{"id": id, "function": {"name": name, "arguments": raw}}]}


def test_tools_cover_all_names():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == {"click", "double_click", "drag", "type", "key", "scroll", "wait", "done"}


def test_click_ok():
    assert parse_tool_call(msg("click", {"x": 10, "y": 20}), W, H) == Action(
        "click", {"x": 10, "y": 20, "button": "left"}, "c1"
    )


def test_coords_numeric_string_and_float():
    a = parse_tool_call(msg("click", {"x": "120", "y": 119.6}), W, H)
    assert a.args["x"] == 120 and a.args["y"] == 120


def test_coords_non_numeric():
    with pytest.raises(ToolError):
        parse_tool_call(msg("click", {"x": "left", "y": 5}), W, H)


def test_out_of_box():
    with pytest.raises(ToolError):
        parse_tool_call(msg("click", {"x": W, "y": 5}), W, H)


def test_drag_second_point_out_of_box():
    with pytest.raises(ToolError):
        parse_tool_call(msg("drag", {"x1": 1, "y1": 1, "x2": 5, "y2": H}), W, H)


def test_malformed_json():
    with pytest.raises(ToolError) as e:
        parse_tool_call(msg("click", "{x:1"), W, H)
    assert e.value.call_id == "c1"


def test_no_tool_call():
    with pytest.raises(ToolError) as e:
        parse_tool_call({"content": "hi"}, W, H)
    assert e.value.call_id is None


def test_unknown_tool():
    with pytest.raises(ToolError):
        parse_tool_call(msg("explode", {}), W, H)


def test_multiple_calls_uses_first():
    m = msg("done", {"answer": "a"}, "c1")
    m["tool_calls"].append(msg("done", {"answer": "b"}, "c2")["tool_calls"][0])
    assert parse_tool_call(m, W, H).args["answer"] == "a"


@pytest.mark.parametrize(
    "combo", ["win", "win+r", "alt+tab", "alt+f4", "ctrl+alt+del", "ctrl+w", "ctrl+shift+esc"]
)
def test_blocked_keys(combo):
    with pytest.raises(ToolError):
        parse_tool_call(msg("key", {"combo": combo}), W, H)


def test_unknown_key():
    with pytest.raises(ToolError):
        parse_tool_call(msg("key", {"combo": "ctrl+banana"}), W, H)


def test_key_ok():
    assert parse_tool_call(msg("key", {"combo": "Ctrl+A"}), W, H).args["combo"] == "ctrl+a"


@pytest.mark.parametrize("dy", [0, 11, -11])
def test_scroll_bounds(dy):
    with pytest.raises(ToolError):
        parse_tool_call(msg("scroll", {"x": 1, "y": 1, "dy": dy}), W, H)


def test_wait_bounds():
    for bad in (0.1, 6):
        with pytest.raises(ToolError):
            parse_tool_call(msg("wait", {"seconds": bad}), W, H)
    assert parse_tool_call(msg("wait", {"seconds": 1}), W, H).args["seconds"] == 1.0


def test_type_requires_string():
    with pytest.raises(ToolError):
        parse_tool_call(msg("type", {"text": 5}), W, H)


def test_done():
    assert parse_tool_call(msg("done", {"answer": "42"}), W, H) == Action(
        "done", {"answer": "42"}, "c1"
    )
