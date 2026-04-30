"""mss-backed virtual-desktop screenshot helpers. Qt-free.

DPI awareness is set in main.py before Qt loads, so mss returns true physical
pixels. Coordinates throughout this module are virtual-desktop physical pixels.
"""
from __future__ import annotations

from dataclasses import dataclass

import mss
import numpy as np


@dataclass(frozen=True)
class MonitorRect:
    """A monitor's physical rect in virtual-desktop coordinates."""
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True)
class VirtualDesktop:
    """A single grab of all monitors, in virtual-desktop coordinates.

    `image` is HxWx3 uint8 BGR (PaddleOCR's expected format). `origin_x`/
    `origin_y` are the virtual-desktop coords of the top-left of `image` (can
    be negative if a monitor sits to the left/above the primary).
    """
    image: np.ndarray
    origin_x: int
    origin_y: int
    monitors: tuple[MonitorRect, ...]

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    def crop(self, vx: int, vy: int, vw: int, vh: int) -> np.ndarray:
        x0 = vx - self.origin_x
        y0 = vy - self.origin_y
        x1 = x0 + vw
        y1 = y0 + vh
        x0c = max(0, min(self.width, x0))
        y0c = max(0, min(self.height, y0))
        x1c = max(0, min(self.width, x1))
        y1c = max(0, min(self.height, y1))
        if x1c <= x0c or y1c <= y0c:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        return self.image[y0c:y1c, x0c:x1c].copy()


def grab_virtual_desktop() -> VirtualDesktop:
    with mss.mss() as sct:
        # monitors[0] is the union of all monitors. monitors[1:] are individual.
        m = sct.monitors[0]
        shot = sct.grab(m)
        # `shot.rgb` is RGB without alpha. Flip to BGR for cv2/PaddleOCR.
        rgb = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)
        bgr = rgb[:, :, ::-1].copy()
        mons = tuple(
            MonitorRect(int(d["left"]), int(d["top"]), int(d["width"]), int(d["height"]))
            for d in sct.monitors[1:]
        )
        return VirtualDesktop(
            image=bgr,
            origin_x=int(m["left"]),
            origin_y=int(m["top"]),
            monitors=mons,
        )
