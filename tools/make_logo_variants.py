# SPDX-License-Identifier: AGPL-3.0-or-later
"""Make the dashboard's transparent logo variants from the original artwork.

The original logo is a JPEG on an off-white background. This writes two
transparent WebP files next to the dashboard's static assets:

- ``logo-light.webp``: the artwork without its background, for light pages.
- ``logo-dark.webp``: the same, with the dark lettering lightened so it reads
  on dark pages.

Run it (Pillow and NumPy are not project dependencies)::

    uv run --no-project --with pillow --with numpy python -I \\
        tools/make_logo_variants.py path/to/logo.jpeg src/vitals_on_fhir/dashboard/static

How the background is removed:

1. The background is the region reachable from the image border through
   pixels close to the border colour. Its colour is estimated locally (it
   darkens towards the corners) by a masked blur.
2. Near that region, opacity follows each pixel's distance from the local
   background colour, and the background's share is subtracted from partly
   transparent pixels so no pale fringe remains on dark pages. A neutral
   brightening (JPEG ringing, the white glow around the stack) does not count
   as content.
3. The light, neutral region reachable from the border (the background, the
   stack's drop shadow, the glass panel) is treated as shadow: darker than the
   background becomes black at partial opacity, which is exact over the
   original background and invisible on a dark one.

The lettering areas and inks in ``LETTERING`` are specific to this artwork;
check them if the artwork changes.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

#: Border-colour distance below which a pixel can belong to the background fill.
FILL_DISTANCE = 22.0
#: Distance from the background at which opacity starts, and where it is full.
ALPHA_FROM, ALPHA_FULL = 8.0, 40.0
#: Blur radius (box, three passes) for the background colour and the edge band.
BG_RADIUS, BAND_RADIUS = 12, 6
#: Neutral-light region treated as shadow: chroma below, mean level above.
SHADOW_MAX_CHROMA, SHADOW_MIN_LEVEL = 16, 185
#: Dark variant: (rows, columns, new ink) for each lettering area.
LETTERING = [
    ((0, 105), (0, 345), (232, 238, 243)),  # "VITALS"
    ((100, 175), (0, 345), (176, 196, 210)),  # "on-FHIR"
    ((575, None), (0, None), (190, 196, 201)),  # "INTEROPERABLE HEALTH DATA"
]


def box_blur(x: np.ndarray, r: int) -> np.ndarray:
    """Edge-clamped separable box blur over the first two axes."""
    for axis in (0, 1):
        pad = [(0, 0)] * x.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(x, pad, mode="edge"), axis=axis)
        n = x.shape[axis]
        hi = np.take(c, range(2 * r + 1, 2 * r + 1 + n), axis=axis)
        lo = np.take(c, range(n), axis=axis)
        x = (hi - lo) / (2 * r + 1)
    return x


def blur(x: np.ndarray, r: int) -> np.ndarray:
    """Approximate Gaussian blur: three box passes."""
    for _ in range(3):
        x = box_blur(x, r)
    return x


def shift(x: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Colour distance from *ref*, ignoring a neutral brightening."""
    diff = x - ref
    lum = diff.mean(axis=-1, keepdims=True)
    return np.linalg.norm(np.where(lum > 0, diff - lum, diff), axis=-1)


def fill_from_border(passable: np.ndarray) -> np.ndarray:
    """Pixels reachable from the image border through *passable* pixels (4-connected)."""
    h, w = passable.shape
    seen = np.zeros((h, w), bool)
    edge = [(y, x) for y in range(h) for x in (0, w - 1)]
    edge += [(y, x) for x in range(w) for y in (0, h - 1)]
    queue: deque[tuple[int, int]] = deque()
    for y, x in edge:
        if passable[y, x] and not seen[y, x]:
            seen[y, x] = True
            queue.append((y, x))
    while queue:
        y, x = queue.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and passable[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                queue.append((ny, nx))
    return seen


def make_variants(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (light, dark) RGBA arrays for the RGB artwork *rgb*."""
    a = rgb.astype(np.float64)
    strips = (a[:3], a[-3:], a[:, :3], a[:, -3:])
    c0 = np.concatenate([strip.reshape(-1, 3) for strip in strips]).mean(0)

    # Background region and its local colour.
    bgmask = fill_from_border(shift(a, c0) < FILL_DISTANCE)
    m = bgmask.astype(float)
    weight = blur(m, BG_RADIUS)
    bg = blur(a * m[..., None], BG_RADIUS) / np.maximum(weight, 1e-6)[..., None]
    bg[weight < 1e-3] = c0

    # Opacity near the background, then unmix the background from edge pixels.
    alpha = np.clip((shift(a, bg) - ALPHA_FROM) / (ALPHA_FULL - ALPHA_FROM), 0, 1)
    alpha[blur(m, BAND_RADIUS) <= 1e-3] = 1.0
    fg = np.clip((a - (1 - alpha[..., None]) * bg) / np.maximum(alpha, 1e-3)[..., None], 0, 255)
    # A pixel darker than the background cannot come out brighter than it was.
    lum_a, lum_bg, lum_fg = a.mean(2), bg.mean(2), fg.mean(2)
    cap = (lum_a < lum_bg) & (lum_fg > lum_a)
    fg[cap] *= (lum_a[cap] / np.maximum(lum_fg[cap], 1e-6))[:, None]

    # Shadows and glows: black at partial opacity, or transparent.
    chroma = a.max(2) - a.min(2)
    soft = fill_from_border((chroma < SHADOW_MAX_CHROMA) & (lum_a > SHADOW_MIN_LEVEL))
    alpha[soft] = np.clip(1 - lum_a / np.maximum(lum_bg, 1e-6), 0, 1)[soft]
    fg[soft] = 0
    fg[alpha < 1e-3] = 0

    # Dark variant: lettering takes a light ink (the red/orange flame is left alone).
    dark = fg.copy()
    for (y0, y1), (x0, x1), ink in LETTERING:
        area = (slice(y0, y1), slice(x0, x1))
        not_flame = a[area][..., 2] >= a[area][..., 0] - 20
        hit = (alpha[area] > 0) & not_flame
        dark[area][hit] = ink

    def rgba(colour: np.ndarray) -> np.ndarray:
        return np.dstack([colour, alpha * 255]).round().astype(np.uint8)

    return rgba(fg), rgba(dark)


def main() -> None:
    """Read the artwork, write ``logo-light.webp`` and ``logo-dark.webp``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the original logo (any format Pillow reads)")
    parser.add_argument("out_dir", type=Path, help="directory for the two WebP files")
    args = parser.parse_args()

    light, dark = make_variants(np.asarray(Image.open(args.source).convert("RGB")))
    for name, pixels in (("logo-light.webp", light), ("logo-dark.webp", dark)):
        path = args.out_dir / name
        Image.fromarray(pixels, "RGBA").save(path, "WEBP", quality=90, alpha_quality=100, method=6)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
