from box_agent.capture import grab
from box_agent.geometry import Box


class FakeShot:
    def __init__(self, w, h):
        self.size = (w, h)
        self.rgb = bytes([200, 10, 10]) * (w * h)


class FakeSct:
    def __init__(self):
        self.asked = None

    def grab(self, region):
        self.asked = region
        return FakeShot(region["width"], region["height"])


def test_capture_scales_down():
    sct = FakeSct()
    shot = grab(Box(-50, 10, 2560, 1000), sct=sct)
    assert sct.asked == {"left": -50, "top": 10, "width": 2560, "height": 1000}
    assert (shot.width, shot.height, shot.scale) == (1280, 500, 0.5)
    assert shot.png.startswith(b"\x89PNG")


def test_capture_small_box_unscaled():
    shot = grab(Box(0, 0, 300, 200), sct=FakeSct())
    assert (shot.width, shot.height, shot.scale) == (300, 200, 1.0)
