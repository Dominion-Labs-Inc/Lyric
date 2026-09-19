#!/usr/bin/env python3
"""Identity-preserving transformations — the nuisance variables of real sight.

Every transformation here changes the IMAGE and not the OBJECT. A cup under a
dimmer bulb is the same cup; a cup photographed from closer is the same cup; a
cup half behind a book is the same cup. So a perception layer whose features are
about the object should return the same features, and wherever it does not, the
feature is about the photograph instead.

They are graded, because the interesting number is not "does it break" but
"where". A feature that survives a 10% change and fails at 30% is characterised
by that boundary, and the boundary is predictable from the code: `_color_name`
thresholds on HSV value at 85 and 150, `_size_category` on area fraction at
0.08/0.25/0.55. Those predictions are what this exists to test.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Tuple

import cv2
import numpy as np


# ── photometric ─────────────────────────────────────────────────────────────

def brightness(img: np.ndarray, factor: float) -> np.ndarray:
    """Scale luminance. The same scene under a brighter or dimmer light."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 2] = np.clip(hsv[..., 2] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def saturation(img: np.ndarray, factor: float) -> np.ndarray:
    """Scale colourfulness. A washed-out print, an overcast day, a cheap sensor."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def colour_temperature(img: np.ndarray, shift: float) -> np.ndarray:
    """Warm or cool the illuminant — tungsten vs daylight vs shade.

    A real and very common nuisance: the same object under two bulbs reflects
    different spectra, and a hue-threshold colour namer has no illuminant
    estimate to discount it with."""
    out = img.astype(np.float32)
    out[..., 0] = np.clip(out[..., 0] * (1.0 - shift), 0, 255)   # blue
    out[..., 2] = np.clip(out[..., 2] * (1.0 + shift), 0, 255)   # red
    return out.astype(np.uint8)


def gamma(img: np.ndarray, g: float) -> np.ndarray:
    """Non-linear tone response — a different camera or display curve."""
    table = np.array([((i / 255.0) ** (1.0 / g)) * 255 for i in range(256)],
                     dtype=np.uint8)
    return cv2.LUT(img, table)


# ── geometric ───────────────────────────────────────────────────────────────

def zoom(img: np.ndarray, factor: float) -> np.ndarray:
    """The same object, nearer or further. Framing changes, identity does not.

    Implemented as a centre crop-and-resize (nearer) or a pad-and-resize
    (further) so the output frame is the same size — only the object's share of
    it changes, which is exactly the variable `area_fraction` is sensitive to."""
    h, w = img.shape[:2]
    if factor >= 1.0:
        ch, cw = int(h / factor), int(w / factor)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        crop = img[y0:y0 + ch, x0:x0 + cw]
        return cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)
    nh, nw = int(h * factor), int(w * factor)
    small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    # pad with the image's own border colour, so no artificial frame is added
    border = int(np.median(np.concatenate(
        [img[0, :], img[-1, :], img[:, 0], img[:, -1]]).reshape(-1, 3), axis=0)[0])
    out = np.full_like(img, border)
    canvas = np.zeros((h, w, 3), np.uint8)
    canvas[:] = np.median(np.concatenate(
        [img[0, :], img[-1, :], img[:, 0], img[:, -1]]).reshape(-1, 3),
        axis=0).astype(np.uint8)
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    canvas[y0:y0 + nh, x0:x0 + nw] = small
    return canvas


def translate(img: np.ndarray, frac: float) -> np.ndarray:
    """Shift the object in frame — the photographer stood slightly to the left."""
    h, w = img.shape[:2]
    m = np.float32([[1, 0, frac * w], [0, 1, frac * h * 0.5]])
    edge = np.median(np.concatenate(
        [img[0, :], img[-1, :], img[:, 0], img[:, -1]]).reshape(-1, 3), axis=0)
    return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT,
                          borderValue=[float(c) for c in edge])


def rotate(img: np.ndarray, degrees: float) -> np.ndarray:
    """Turn the object (or the camera). A cup on its side is the same cup."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), degrees, 1.0)
    edge = np.median(np.concatenate(
        [img[0, :], img[-1, :], img[:, 0], img[:, -1]]).reshape(-1, 3), axis=0)
    return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT,
                          borderValue=[float(c) for c in edge])


def perspective(img: np.ndarray, strength: float) -> np.ndarray:
    """View the object off-axis — the single most common real-world nuisance,
    and the one a bounding-box aspect ratio cannot survive."""
    h, w = img.shape[:2]
    d = strength * w
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[d, d * 0.5], [w - d, 0], [w, h], [d * 0.4, h - d * 0.5]])
    m = cv2.getPerspectiveTransform(src, dst)
    edge = np.median(np.concatenate(
        [img[0, :], img[-1, :], img[:, 0], img[:, -1]]).reshape(-1, 3), axis=0)
    return cv2.warpPerspective(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT,
                               borderValue=[float(c) for c in edge])


# ── corruption ──────────────────────────────────────────────────────────────

def blur(img: np.ndarray, sigma: float) -> np.ndarray:
    """Out of focus, or motion. Perimeter smooths; circularity moves."""
    k = int(2 * round(3 * sigma) + 1)
    return cv2.GaussianBlur(img, (k, k), sigma)


def noise(img: np.ndarray, sigma: float) -> np.ndarray:
    """Sensor noise at low light. Inflates contour perimeter, so it attacks
    circularity from the opposite direction to blur."""
    rng = np.random.default_rng(0xC0FFEE)
    out = img.astype(np.float32) + rng.normal(0, sigma, img.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray, quality: int) -> np.ndarray:
    """Lossy compression — what almost every real photograph has been through."""
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def occlude(img: np.ndarray, frac: float) -> np.ndarray:
    """Hide part of the object behind something else. Graded by the fraction of
    the FRAME covered, from the side, as a real occluder would be."""
    h, w = img.shape[:2]
    cut = int(w * frac)
    out = img.copy()
    # A mid-grey occluder: neither figure nor ground under Otsu, so this tests
    # the shape break rather than smuggling in a second high-contrast blob.
    out[:, w - cut:] = 128
    return out


def clutter(img: np.ndarray, n: int) -> np.ndarray:
    """Put distractor objects in the frame. The object is unchanged; what
    changes is that it is no longer the only thing there."""
    rng = np.random.default_rng(0xBEEF + n)
    out = img.copy()
    h, w = out.shape[:2]
    for _ in range(n):
        cx, cy = int(rng.integers(0, w)), int(rng.integers(0, h))
        r = int(rng.integers(int(0.04 * w), int(0.12 * w)))
        colour = tuple(int(c) for c in rng.integers(0, 255, 3))
        if rng.random() < 0.5:
            cv2.circle(out, (cx, cy), r, colour, -1)
        else:
            cv2.rectangle(out, (cx - r, cy - r), (cx + r, cy + r), colour, -1)
    return out


def textured_background(img: np.ndarray, level: float) -> np.ndarray:
    """Replace a plain ground with a textured one, leaving the object alone.

    The object is whatever is NOT near the border colour, so this is only
    applied to synthetic stimuli where that separation is exact."""
    h, w = img.shape[:2]
    edge = np.median(np.concatenate(
        [img[0, :], img[-1, :], img[:, 0], img[:, -1]]).reshape(-1, 3), axis=0)
    dist = np.linalg.norm(img.astype(np.float32) - edge[None, None, :], axis=2)
    ground = dist < 40
    rng = np.random.default_rng(0xFACE)
    tex = rng.integers(0, 256, (h // 8, w // 8, 3), dtype=np.uint8)
    tex = cv2.resize(tex, (w, h), interpolation=cv2.INTER_LINEAR)
    base = np.full_like(img, edge.astype(np.uint8))
    mixed = cv2.addWeighted(base, 1.0 - level, tex, level, 0)
    out = img.copy()
    out[ground] = mixed[ground]
    return out


#: (family, magnitude label, callable). Magnitudes ascend, so a stability curve
#: reads left to right as "how much of this can it take".
Battery = List[Tuple[str, str, Callable[[np.ndarray], np.ndarray]]]


def standard_battery(*, include_background: bool = True) -> Battery:
    b: Battery = []
    for f in (0.55, 0.7, 0.85, 1.15, 1.35, 1.7):
        b.append(("brightness", f"x{f}", lambda im, f=f: brightness(im, f)))
    for f in (0.25, 0.45, 0.65, 0.85):
        b.append(("saturation", f"x{f}", lambda im, f=f: saturation(im, f)))
    for s in (-0.25, -0.12, 0.12, 0.25):
        b.append(("illuminant", f"{s:+.2f}", lambda im, s=s: colour_temperature(im, s)))
    for g in (0.6, 0.8, 1.25, 1.7):
        b.append(("gamma", f"{g}", lambda im, g=g: gamma(im, g)))
    for f in (0.5, 0.7, 1.4, 2.0):
        b.append(("zoom", f"x{f}", lambda im, f=f: zoom(im, f)))
    for f in (0.08, 0.16, 0.28):
        b.append(("translate", f"{int(f*100)}%", lambda im, f=f: translate(im, f)))
    for d in (10, 30, 45, 90):
        b.append(("rotate", f"{d}deg", lambda im, d=d: rotate(im, d)))
    for s in (0.06, 0.12, 0.20):
        b.append(("perspective", f"{s}", lambda im, s=s: perspective(im, s)))
    for s in (1.0, 2.0, 4.0, 8.0):
        b.append(("blur", f"sigma{s}", lambda im, s=s: blur(im, s)))
    for s in (5.0, 12.0, 25.0, 45.0):
        b.append(("noise", f"sigma{s}", lambda im, s=s: noise(im, s)))
    for q in (85, 60, 40, 20):
        b.append(("jpeg", f"q{q}", lambda im, q=q: jpeg(im, q)))
    for f in (0.10, 0.25, 0.40):
        b.append(("occlusion", f"{int(f*100)}%", lambda im, f=f: occlude(im, f)))
    for n in (2, 5, 10):
        b.append(("clutter", f"{n}obj", lambda im, n=n: clutter(im, n)))
    if include_background:
        for lv in (0.3, 0.6, 0.9):
            b.append(("background", f"{lv}",
                      lambda im, lv=lv: textured_background(im, lv)))
    return b
