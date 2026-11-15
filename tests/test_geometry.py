import pytest

from box_agent.geometry import Box, OutOfBox, fit_scale, image_size, to_screen


def test_fit_scale_small_box_is_1():
    assert fit_scale(800, 600) == 1.0


def test_fit_scale_large_box():
    assert fit_scale(2560, 1000) == 0.5


def test_image_size():
    assert image_size(Box(0, 0, 2560, 1000), 0.5) == (1280, 500)


def test_to_screen_maps_scaled_point():
    assert to_screen(100, 50, Box(10, 20, 2560, 1000), 0.5) == (210, 120)


def test_to_screen_negative_monitor():
    assert to_screen(0, 0, Box(-1920, -200, 400, 300), 1.0) == (-1920, -200)


def test_to_screen_rejects_outside():
    with pytest.raises(OutOfBox):
        to_screen(400, 10, Box(0, 0, 400, 300), 1.0)  # x == width
    with pytest.raises(OutOfBox):
        to_screen(-1, 10, Box(0, 0, 400, 300), 1.0)
