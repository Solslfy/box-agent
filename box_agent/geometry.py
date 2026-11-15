"""Pure geometry: the selected box and image<->screen coordinate mapping."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    """A screen rectangle in absolute virtual-desktop physical pixels."""

    left: int
    top: int
    width: int
    height: int


class OutOfBox(ValueError):
    """A coordinate fell outside the screenshot of the box."""


def fit_scale(width: int, height: int, max_edge: int = 1280) -> float:
    """Scale factor (<= 1.0) so the long edge fits within max_edge."""
    long_edge = max(width, height)
    if long_edge <= max_edge:
        return 1.0
    return max_edge / long_edge


def image_size(box: Box, scale: float) -> tuple[int, int]:
    return max(1, round(box.width * scale)), max(1, round(box.height * scale))


def to_screen(x: float, y: float, box: Box, scale: float) -> tuple[int, int]:
    """Map a screenshot coordinate to an absolute screen coordinate.

    Raises OutOfBox if (x, y) is not inside the screenshot. Never clamps.
    """
    img_w, img_h = image_size(box, scale)
    if not (0 <= x < img_w and 0 <= y < img_h):
        raise OutOfBox(f"({x}, {y}) is outside the {img_w}x{img_h} screenshot")
    return box.left + round(x / scale), box.top + round(y / scale)
