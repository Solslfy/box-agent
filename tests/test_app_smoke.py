import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from box_agent.agent import RunResult, StepEvent
from box_agent.geometry import Box
from box_agent.updater import Release


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_panel_shows_steps_and_result(qapp):
    from box_agent.panel import Panel

    p = Panel()
    p.add_step(StepEvent(1, "action", "click left at (1, 2)"))
    p.show_result(RunResult("done", "42"))
    assert "click left" in p.log_text()
    assert "42" in p.result_text()


def test_panel_update_banner(qapp):
    from box_agent.panel import Panel

    p = Panel()
    p.show_update(Release("0.2.0", "u", "p"))
    assert "0.2.0" in p.update_text()


def test_panel_dock_never_overlaps_box(qapp):
    from box_agent.panel import dock_rect

    screen = (0, 0, 1920, 1080)
    r = dock_rect(Box(1500, 100, 400, 300), screen, 360, 500)  # no room on the right
    assert r[0] + r[2] <= 1500
    r = dock_rect(Box(100, 100, 400, 300), screen, 360, 500)
    assert r[0] >= 500


def test_overlay_ignores_tiny_box(qapp):
    from box_agent.overlay import normalize_selection

    assert normalize_selection(10, 10, 25, 25) is None
    assert normalize_selection(50, 60, 10, 20) == (10, 20, 40, 40)
