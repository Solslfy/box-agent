import pytest
from pynput.keyboard import Key
from pynput.mouse import Button

from box_agent.actions import Executor, FailsafeTriggered
from box_agent.geometry import Box
from box_agent.tools import Action


class FakeMouse:
    def __init__(self):
        self.position = (500, 500)
        self.log = []

    def __setattr__(self, k, v):
        if k == "position" and "log" in self.__dict__:
            self.log.append(("move", v))
        object.__setattr__(self, k, v)

    def click(self, button, count=1):
        self.log.append(("click", button, count))

    def press(self, button):
        self.log.append(("press", button))

    def release(self, button):
        self.log.append(("release", button))

    def scroll(self, dx, dy):
        self.log.append(("scroll", dx, dy))


class FakeKeyboard:
    def __init__(self):
        self.log = []

    def press(self, k):
        self.log.append(("press", k))

    def release(self, k):
        self.log.append(("release", k))

    def tap(self, k):
        self.log.append(("tap", k))

    def type(self, s):
        self.log.append(("type", s))


BOX = Box(100, 200, 800, 600)
CORNERS = [(0, 0), (1919, 0), (0, 1079), (1919, 1079)]


def ex(**kw):
    m, k = FakeMouse(), FakeKeyboard()
    return Executor(BOX, 1.0, mouse=m, keyboard=k, corners=CORNERS, **kw), m, k


def act(name, **args):
    return Action(name, args, "c1")


def test_click_maps_coordinates():
    e, m, _ = ex()
    desc = e.run(act("click", x=10, y=20, button="left"))
    assert m.log == [("move", (110, 220)), ("click", Button.left, 1)]
    assert "110, 220" in desc


def test_click_scaled():
    m, k = FakeMouse(), FakeKeyboard()
    e = Executor(Box(0, 0, 2560, 1000), 0.5, mouse=m, keyboard=k, corners=CORNERS)
    e.run(act("click", x=100, y=50, button="right"))
    assert m.log == [("move", (200, 100)), ("click", Button.right, 1)]


def test_double_click():
    e, m, _ = ex()
    e.run(act("double_click", x=1, y=1))
    assert m.log[-1] == ("click", Button.left, 2)


def test_type_unicode_and_newlines():
    e, _, k = ex()
    e.run(act("type", text="héllo 👋\nline2"))
    assert k.log == [("type", "héllo 👋"), ("tap", Key.enter), ("type", "line2")]


def test_key_combo_order():
    e, _, k = ex()
    e.run(act("key", combo="ctrl+shift+t"))
    assert k.log == [
        ("press", Key.ctrl), ("press", Key.shift), ("tap", "t"),
        ("release", Key.shift), ("release", Key.ctrl),
    ]


def test_single_special_key():
    e, _, k = ex()
    e.run(act("key", combo="pagedown"))
    assert k.log == [("tap", Key.page_down)]


def test_scroll():
    e, m, _ = ex()
    e.run(act("scroll", x=5, y=5, dy=-3))
    assert m.log == [("move", (105, 205)), ("scroll", 0, -3)]


def test_drag():
    e, m, _ = ex()
    e.run(act("drag", x1=1, y1=2, x2=30, y2=40))
    assert m.log[0] == ("move", (101, 202))
    assert m.log[1] == ("press", Button.left)
    assert m.log[-2] == ("move", (130, 240))
    assert m.log[-1] == ("release", Button.left)


def test_dry_run_touches_nothing():
    e, m, k = ex(dry_run=True)
    desc = e.run(act("click", x=1, y=1, button="left"))
    e.run(act("type", text="x"))
    assert m.log == [] and k.log == []
    assert desc.startswith("[dry run] ")


def test_dry_run_reports_image_points():
    pts = []
    m, k = FakeMouse(), FakeKeyboard()
    e = Executor(BOX, 1.0, mouse=m, keyboard=k, dry_run=True, corners=CORNERS, on_point=lambda x, y: pts.append((x, y)))
    e.run(act("click", x=7, y=8, button="left"))
    e.run(act("drag", x1=1, y1=2, x2=3, y2=4))
    e.run(act("type", text="x"))
    assert pts == [(7, 8), (1, 2), (3, 4)]
    assert m.log == []


def test_failsafe_corner():
    e, m, _ = ex()
    object.__setattr__(m, "position", (0, 0))
    with pytest.raises(FailsafeTriggered):
        e.run(act("click", x=1, y=1, button="left"))
    assert m.log == []


def test_release_all():
    e, m, k = ex()
    e.release_all()
    assert ("release", Key.ctrl) in k.log and ("release", Key.alt) in k.log
    assert ("release", Button.left) in m.log
