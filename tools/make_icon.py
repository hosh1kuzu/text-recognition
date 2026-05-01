"""Generate src/textrecog/resources/textrecog.ico.

Implements the same visual design as ui.py's _make_icon_pixmap so that the
embedded exe icon always matches the runtime-generated icon exactly.

Run from repo root:
    conda run -n textrecog python tools/make_icon.py
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw

_PRIMARY = (37, 99, 235, 255)   # #2563EB
_WHITE = (255, 255, 255, 255)
_TRANSPARENT = (0, 0, 0, 0)

SIZES = [16, 24, 32, 48, 64, 128, 256]


def make_icon_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), _TRANSPARENT)
    d = ImageDraw.Draw(img)

    radius = max(3, round(size * 0.18))
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=_PRIMARY)

    line = max(2, round(size * 0.085))
    pad = round(size * 0.22)
    length = round(size * 0.25)
    cap = max(1, line // 2)

    def rr(x: int, y: int, w: int, h: int) -> None:
        d.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=cap, fill=_WHITE)

    # Top-left corner mark
    rr(pad, pad, length, line)
    rr(pad, pad, line, length)
    # Bottom-right corner mark
    rr(size - pad - length, size - pad - line, length, line)
    rr(size - pad - line, size - pad - length, line, length)

    # Two horizontal text lines
    rr(round(size * 0.36), round(size * 0.42), round(size * 0.32), line)
    rr(round(size * 0.36), round(size * 0.56), round(size * 0.22), line)

    return img


def main() -> None:
    images = [make_icon_image(s) for s in SIZES]

    out = os.path.join(
        os.path.dirname(__file__), "..", "src", "textrecog", "resources", "textrecog.ico"
    )
    out = os.path.normpath(out)

    # Pillow's ICO encoder accepts a list of (w, h) tuples via the `sizes`
    # keyword; pass all images through append_images so every size is embedded.
    # We also include each image at its own canonical size tuple so Windows
    # can pick the best match per context (tray, Explorer, taskbar).
    # Pillow's ICO encoder downscales a single large source image to each
    # requested size. Pass the 256px image as the base; `sizes` lists every
    # target resolution to embed.
    large = images[-1]  # 256×256
    large.save(
        out,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
    )

    # Verify by re-opening and listing the embedded sizes.
    with Image.open(out) as probe:
        embedded = sorted(probe.ico.sizes())

    size_kb = os.path.getsize(out) / 1024
    print(f"Saved {out}  ({size_kb:.1f} KB)")
    print(f"Embedded sizes: {embedded}")


if __name__ == "__main__":
    main()
