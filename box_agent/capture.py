"""Screenshot of the selected box, downscaled for the model."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from .geometry import Box, fit_scale, image_size


@dataclass
class Shot:
    png: bytes
    width: int
    height: int
    scale: float


def grab(box: Box, max_edge: int = 1280, sct=None) -> Shot:
    region = {"left": box.left, "top": box.top, "width": box.width, "height": box.height}
    if sct is None:
        import mss  # mss instances are per-thread on Windows; make one per call

        with mss.mss() as s:
            raw = s.grab(region)
            img = Image.frombytes("RGB", raw.size, raw.rgb)
    else:
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.rgb)

    scale = fit_scale(box.width, box.height, max_edge)
    if scale < 1.0:
        img = img.resize(image_size(box, scale), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Shot(buf.getvalue(), img.width, img.height, scale)
