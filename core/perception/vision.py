#!/usr/bin/env python3
"""Deterministic visual perception: read the structure that is really in an image
or video, with no learned model anywhere in the loop.

This is the "perceive structure" half of sight (the paper: Structure Before
Meaning). Every value returned here is MEASURED from the pixels by a classical
algorithm -- segmentation, contour and blob analysis, dominant-colour clustering
computed on THIS image, edge and keypoint density, optical-flow motion, decoded
QR payloads. Nothing here assigns a semantic category to a novel thing; naming is
the substrate's job, learned downstream. What this guarantees is that the facts
are honest: a width is the real width, a blob is a real region, a dominant colour
is really dominant.

Pure functions over a file path. No substrate imports, so it can be tested and
reasoned about on its own.
"""
from __future__ import annotations

import io
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


# --- colour naming: perceptual, from HSV, no learning --------------------
# The hue circle is named the way people name it; lightness and saturation add
# the qualifier (dark / pale / vivid). The BOUNDARIES are given, the way the
# copula is given to the reader -- a colour's name is derived from its measured
# hue/saturation/value, never guessed. OpenCV hue is 0-179; s,v are 0-255.
_HUE_NAMES: List[Tuple[int, str]] = [
    (8, "red"), (19, "orange"), (32, "yellow"), (44, "chartreuse"),
    (70, "green"), (82, "teal"), (96, "cyan"), (128, "blue"),
    (140, "indigo"), (150, "violet"), (160, "magenta"), (172, "pink"),
    (179, "red"),
]


# --- how much of a reading is about the OBJECT ----------------------------
#
# WHAT THIS EXISTS TO FIX. Every label in this module comes from a threshold
# applied to a measurement, and the measurement is exact. That exactness was
# being read as certainty about the THING, which it is not. `area_fraction
# 0.656 -> "dominant"` is an exact fact about the PHOTOGRAPH; "that object is
# dominant" is a claim about the world, and the same object at half the camera
# distance falsifies it while the measurement stays just as exact.
#
# Measured, not argued -- 1512 live sightings through the substrate (FALSIFY-01):
# under a 0.55x illuminant the colour name survived 0% of the time; under any
# zoom the size band survived 0% of the time; and the substrate ACTED on the
# result in 100% of those conditions, because every claim arrived at the same
# fixed evidence quality of 0.9. The acceptance band reads posteriors, posteriors
# come from evidence quality, and nothing anywhere said how good the LOOK was.
# So the band could only protect against weak evidence, never against wrong
# evidence. The reading was never in doubt. The claim always should have been.
#
# Two INDEPENDENT quantities are needed, because they answer different questions
# and neither substitutes for the other:
#
#   MARGIN    -- given this measurement, how robust is this label? The distance
#                from the measurement to the nearest cut that would have named it
#                something else. Pure arithmetic over numbers already computed
#                and cuts already stated here. It catches a reading that landed
#                a hair inside a band.
#   FIDELITY  -- does this KIND of measurement reflect the object at all, under
#                these conditions of observation? Clipped pixels have lost their
#                chroma; a smoothed contour has lost its perimeter. It catches a
#                reading that sits comfortably mid-band and is still about the
#                bulb rather than the thing.
#
# Both must hold for a claim to be about the object, so they combine as a
# product. Neither is a probability and neither is learned -- they are the two
# ways a deterministic reading can fail to be about what it is reporting on.
#
# WHAT THIS HONESTLY DOES NOT CATCH, stated so it is not mistaken for more than
# it is: a pure hue ROTATION under good exposure and good saturation displaces
# the measurement into the middle of the wrong band, where the margin is wide and
# the fidelity is high. Detecting that needs an illuminant estimate to discount,
# which is a separate piece of work. Doubt is not compensation.

#: How far apart two honest looks at the same object land, per channel. This is
#: the scale at which nearness to a cut becomes doubt: a reading this far from
#: the nearest cut is treated as fully resolved, and one sitting on a cut is
#: treated as naming nothing in particular.
#:
#: MEASURED, not chosen. Over 234 sightings of the same objects under sensor and
#: geometry nuisance -- noise, JPEG, blur, rotation, translation, perspective,
#: zoom -- the region's mean HSV moved by at most 4.7 of hue, 20.2 of saturation
#: and 23.4 of value (p95: 0.4 / 5.0 / 6.1). These cover that worst case, so a
#: reading further than this from a cut cannot be pushed over it by the nuisance
#: the naming is meant to tolerate.
#:
#: The PHOTOMETRIC transforms were deliberately excluded from that measurement,
#: and the exclusion is the honest part. A dimmer bulb moves value by 115 levels;
#: setting the scale from that would make every colour claim worthless, because
#: the real finding is that this naming is not illumination-invariant at all. A
#: margin says how robust a reading is to noise. It cannot say an illuminant has
#: displaced it, and nothing here pretends otherwise -- that needs compensation,
#: not doubt.
_CHROMA_RESOLUTION = 24.0
_HUE_RESOLUTION = 8.0

#: The cuts the colour cascade makes, named once so the naming and the margin
#: read the SAME number. A threshold cannot now move in one without moving in the
#: other, which is the failure mode that let a measured support be computed and
#: thrown away everywhere else in this module.
_S_ACHROMATIC = 28.0      # below this, hue carries no information at all
_V_ACHROMATIC = 24.0
_V_DARK = 85.0
_SHARP_CUT = 100.0        # Laplacian variance at or above which a frame is sharp
_CLIP_LOW, _CLIP_HIGH = 15.0, 240.0   # beyond these a pixel has been crushed/blown
#: The shape cuts, named for the same reason as the colour ones: the label and
#: its margin have to read the same number or they will drift apart.
_CIRCLE_CUT, _ELLIPSE_CUT = 0.80, 0.60
_SQUARE_ASPECT = (0.85, 1.18)
#: The scale at which circularity is resolved, MEASURED the same way as the
#: chroma one: across 528 sightings of the same discs under the whole
#: identity-preserving battery, circularity moved by at most 0.026 (p95 0.006,
#: mean 0.0016). It is a far steadier measurement than colour, and this scale
#: says so. The gap between the two cuts (0.20) was used first and was an order
#: of magnitude too coarse -- it scored a circularity of 0.90 at half support,
#: which dropped an unambiguously round disc below the evidence floor and had the
#: substrate refuse to hold "circle" at all.
_CIRC_RESOLUTION = 0.03
#: How deep into the picture the "edge of the picture" reaches, as a fraction of
#: the short side. Wide enough that a convex hull sitting a pixel or two inside
#: the frame still counts as touching it; narrow enough that it is still the edge
#: and not the scene.
_BORDER_BAND = 0.02
#: How much of a region has to lie inside an already-kept region OF THE SAME
#: COLOUR before it is the same material found twice rather than a second thing.
_SAME_STUFF = 0.8
#: The square-aspect window's own width: a reading a full window away from either
#: side of it is clear of the square/rectangle call.
_ASPECT_RESOLUTION = _SQUARE_ASPECT[1] - _SQUARE_ASPECT[0]


#: The names `_color_name` reaches by way of its achromatic branch -- decided by
#: lightness alone, with hue explicitly not consulted. Kept beside the cascade
#: that produces them so the two cannot drift.
_ACHROMATIC_NAMES = frozenset(
    ("black", "charcoal", "dim_gray", "gray", "light_gray", "white"))


def _margin(value: float, cut: float, scale: float) -> float:
    """How far a reading sits from a cut, as a fraction of the scale at which
    that channel can be resolved. 1.0 is clear of it; 0.0 is sitting on it."""
    return min(1.0, abs(float(value) - float(cut)) / scale)


def _rgb_hex(bgr) -> str:
    return "#%02x%02x%02x" % (int(bgr[2]), int(bgr[1]), int(bgr[0]))


def _hue_name(h: float) -> Tuple[str, float]:
    """The hue's name, and how far it sits from being named something else.

    The margin is the distance to the nearest edge WHERE THE NAME CHANGES, which
    is not simply the band's own edge: the circle wraps and red occupies both
    ends, so hue 0 is interior to red rather than sitting on a boundary."""
    n = len(_HUE_NAMES)
    for i, (hi, name) in enumerate(_HUE_NAMES):
        if h > hi:
            continue
        room: List[float] = []
        if (_HUE_NAMES[i - 1][1] if i else _HUE_NAMES[-1][1]) != name:
            room.append(h - (float(_HUE_NAMES[i - 1][0]) if i else -1.0))
        if (_HUE_NAMES[i + 1][1] if i + 1 < n else _HUE_NAMES[0][1]) != name:
            room.append(float(hi) - h)
        # No room list at all means both neighbours share this name and there is
        # no edge to be near -- fully resolved, not unsupported.
        return name, min(1.0, min(room) / _HUE_RESOLUTION) if room else 1.0
    return "red", 1.0


def _color_name(bgr) -> Tuple[str, float]:
    """A perceptual colour name for one BGR triple, e.g. dark_red, pale_blue,
    brown, white -- derived deterministically from its hue/saturation/value --
    AND the margin by which that name was decided.

    THE MARGIN IS THE WEAKEST DECISIVE COMPARISON. Naming here is a cascade, so
    several tests are jointly responsible for the answer and flipping ANY of them
    changes it. The one closest to flipping is therefore the one that says how
    robust the name is, and `min` over the recorded comparisons is that. Only the
    comparisons actually evaluated are recorded: Python's `or` short-circuits, so
    a test that never ran was never decisive and correctly contributes nothing.
    """
    px = np.uint8([[[int(bgr[0]), int(bgr[1]), int(bgr[2])]]])
    h, s, v = (float(x) for x in cv2.cvtColor(px, cv2.COLOR_BGR2HSV)[0, 0])
    seen: List[float] = []

    def below(value: float, cut: float) -> bool:
        """Answer `value < cut`, recording how near the call was."""
        seen.append(_margin(value, cut, _CHROMA_RESOLUTION))
        return value < cut

    if below(s, _S_ACHROMATIC) or below(v, _V_ACHROMATIC):
        for cut, name in ((32.0, "black"), (72.0, "charcoal"), (120.0, "dim_gray"),
                          (176.0, "gray"), (224.0, "light_gray")):
            if below(v, cut):
                return name, min(seen)
        return "white", min(seen)

    base, hue_margin = _hue_name(h)
    seen.append(hue_margin)
    if base in ("red", "orange") and below(v, 135.0) and not below(s, 55.0):
        return "brown", min(seen)
    if base == "red" and not below(v, 175.0) and below(s, 150.0):
        return "pink", min(seen)
    if below(v, _V_DARK):
        return "dark_" + base, min(seen)
    if below(s, 95.0) and not below(v, 180.0):
        return "pale_" + base, min(seen)
    if not below(s, 185.0) and not below(v, 150.0):
        return "vivid_" + base, min(seen)
    return base, min(seen)


def _colorfulness(img) -> float:
    """Hasler-Suesstrunk colourfulness -- a measured scalar, not a category."""
    b, g, r = (c.astype("float") for c in cv2.split(img))
    rg = r - g
    yb = 0.5 * (r + g) - b
    std = math.sqrt(rg.std() ** 2 + yb.std() ** 2)
    mean = math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return round(std + 0.3 * mean, 1)


def _colorfulness_category(value: float) -> str:
    if value < 15:
        return "grayscale"
    if value < 40:
        return "muted"
    if value < 80:
        return "colorful"
    return "vivid"


def _palette_temperature(img) -> str:
    """Whether the chromatic pixels lean warm, cool, or neither."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    chromatic = (s > 45) & (v > 45)
    if not chromatic.any():
        return "neutral"
    hue = h[chromatic]
    warm = int(((hue <= 45) | (hue >= 150)).sum())
    cool = int(((hue >= 90) & (hue <= 135)).sum())
    if warm > cool * 1.3:
        return "warm"
    if cool > warm * 1.3:
        return "cool"
    return "neutral"


def _region_color(img, mask) -> Tuple[str, float, float]:
    """Dominant colour WITHIN a region (k-means on its masked pixels), which is
    truer than the mean when a region is textured or multi-toned -- with the
    margin by which it was named, and the CHROMA FIDELITY of the region's own
    pixels.

    Fidelity is measured on THIS region and not on the frame, because this is
    where the colour was read: a blown-out sky in the corner says nothing about
    whether the object's chroma survived, and an object that is itself clipped
    has lost its own no matter how well exposed the rest of the picture is.
    """
    pixels = img[mask.astype(bool)]
    if len(pixels) == 0:
        return "gray", 0.0, 0.0
    sample = pixels.astype(np.float32)
    if len(sample) > 4000:
        idx = np.linspace(0, len(sample) - 1, 4000).astype(int)
        sample = sample[idx]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(sample, 3, None, criteria, 2,
                                    cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=3)
    name, margin = _color_name(centers[int(np.argmax(counts))])

    # HOW MUCH OF THIS REGION AGREES WITH THE KIND OF NAME IT WAS GIVEN, by the
    # cascade's OWN test. Below `s < 28 or v < 24` this module already declares a
    # pixel achromatic and names it by lightness alone, so that same test says
    # what fraction of the region is the kind of thing its name claims -- one
    # authority, no new threshold, and it cannot drift from the naming above it.
    #
    # THE TEST HAS TO RUN THE RIGHT WAY ROUND, which cost a live regression to
    # see. Counting "fraction with a hue" unconditionally scored a clean white
    # background at 0.04 and had the substrate ABSTAIN on `isa white` -- but
    # having no hue is not a problem for that claim, it is the entire evidence
    # FOR it. So a chromatic name is supported by the pixels that carry hue, and
    # an achromatic one by the pixels that carry none.
    #
    # WHAT THIS REPLACED EARLIER, for the same reason: a clipping term that
    # counted any pixel at 240+ as blown out. A saturated red drawn at v=255 is
    # not blown out, it is red, and that term drove colour support to EXACTLY
    # 0.000 on readings that were right 9 times out of 9. Genuine blow-out goes
    # toward white and collapses saturation, so this test already catches it.
    hsv = cv2.cvtColor(np.uint8([pixels]), cv2.COLOR_BGR2HSV)[0]
    has_hue = ((hsv[..., 1].astype(np.float32) >= _S_ACHROMATIC) &
               (hsv[..., 2].astype(np.float32) >= _V_ACHROMATIC))
    agreeing = ~has_hue if name in _ACHROMATIC_NAMES else has_hue
    return name, margin, round(float(agreeing.mean()), 3)


#: The size bands, named once so the banding and its margin read the same cuts.
_SIZE_CUTS: Tuple[float, ...] = (0.02, 0.08, 0.25, 0.55)
_SIZE_NAMES: Tuple[str, ...] = ("tiny", "small", "medium", "large", "dominant")
#: The smallest share of a frame this module will call a region at all. It is
#: also the floor of the `tiny` band, so the two cannot drift apart.
_MIN_REGION_FRAC = 0.01


def _size_category(area_fraction: float) -> Tuple[str, float]:
    """Which size band an area fraction falls in, and how far it sits from the
    next one.

    THE MARGIN IS GEOMETRIC, not linear. The bands are spaced by roughly constant
    RATIOS (0.02, 0.08, 0.25, 0.55 -- each about three times the last), and an
    object's share of a frame scales with the square of how far away the camera
    stands. So "how much would the world have to move for this name to change" is
    a ratio question, and a log distance is what answers it. A linear margin
    would call 0.26 and 0.09 equally fragile when the first survives a 4% camera
    move and the second a 12% one.

    NOTE what this margin does NOT rescue: a size band is a property of the
    FRAMING, and a wide margin only says the reading is robust to a small camera
    move, never that the band is a property of the object. Measured: the band
    survived 0% of zooms at either scale. That is a defect in what is being
    claimed, not in how well it is supported, and no support number fixes it."""
    edges = (_MIN_REGION_FRAC,) + _SIZE_CUTS + (1.0,)
    v = min(max(float(area_fraction), 1e-6), 1.0)
    top = len(_SIZE_NAMES) - 1
    for i, name in enumerate(_SIZE_NAMES):
        lo, hi = edges[i], edges[i + 1]
        if v >= hi and i < top:
            continue
        if v <= lo:             # below the detector's own floor: nothing resolved
            return name, 0.0
        # ONLY AN EDGE WHERE THE NAME CHANGES COUNTS, the same rule the hue
        # circle needs. There is no band above `dominant`, so a region filling
        # 0.996 of the frame is not "a hair from being something else" -- it is
        # as dominant as a thing can get. Measured against the top edge instead,
        # it scored 0.013 and read as an almost unsupported claim.
        room = [math.log(v / lo)]
        if i < top:
            room.append(math.log(hi / v))
        span = math.log(hi / lo)
        return name, round(min(1.0, max(0.0, min(room) / (0.5 * span))), 3)
    return _SIZE_NAMES[-1], 0.0


def _position(cx: float, cy: float, w: int, h: int) -> str:
    col = "left" if cx < w / 3 else ("right" if cx > 2 * w / 3 else "center")
    row = "upper" if cy < h / 3 else ("lower" if cy > 2 * h / 3 else "middle")
    if row == "middle" and col == "center":
        return "center"
    return f"{row}-{col}" if col != "center" else row


def _shape_of(contour, area: float) -> Tuple[str, Optional[float]]:
    """The shape a contour has, AND how well the contour supports that claim.

    THE SUPPORT WAS BEING COMPUTED AND THROWN AWAY. `circularity` is a real
    measurement of how circular a region is, and the only thing that survived
    this function was which side of 0.80 it fell on — so "an almost perfect
    disc" and "a rounded blob that barely qualified" reached the belief layer as
    the same claim, with the same standing. That is the defect that let a
    detector's confidence sit unused in an attribute: a number is measured,
    collapsed to a label, and the measurement is discarded at the one point
    where a consumer could have used it.

    WHY SHAPE IS NOT THE ONLY UNCERTAIN ONE -- this docstring used to claim it
    was, and the claim was wrong in a way that cost 1512 sightings to see. It
    argued that the rest is DEFINITIONAL: `area_fraction 0.656 -> "dominant"` is
    not ninety percent likely to be dominant, it IS dominant given an exact
    measurement and a stated threshold, so the uncertainty is in the vocabulary
    and not in the reading. Every word of that is true OF THE PHOTOGRAPH and
    false OF THE OBJECT, and it is the object the substrate goes on to make
    claims about. `blob1 isa dominant` is not a statement about a frame; it is a
    statement about a thing, and moving the camera falsifies it while the
    measurement stays exact. Measured: the size band survived 0% of zooms and the
    colour name 0% of a 0.55x illuminant, and the substrate acted every time,
    because the exactness of the reading had been passed off as confidence in the
    claim. Colour and size now carry a margin and a fidelity of their own (see
    `_color_name`, `_size_category`, `_view_fidelity`); what follows about shape
    remains true, it is simply no longer the only place uncertainty lives.

    Shape's own uncertainty: `approxPolyDP` at a 4% arc-length tolerance is
    a LOSSY approximation of the contour, and circularity is computed from a
    perimeter that noise inflates. So this claim genuinely can be more or less
    supported, and it is the one that should carry a number.

    Returns (label, fit, margin). `fit` is the raw circularity where one decided
    the label and None wherever the decision was DISCRETE — a vertex count after
    approximation — because a triangle is not 0.8 of a triangle, and
    manufacturing a fit for it would be the fabrication this exists to remove.
    None means "no scalar fit", never "poorly fitted".

    `margin` is the separate question every label in this module now answers: how
    far the deciding measurement sits from the cut that would have named it
    something else. THE RESIDUAL CATEGORIES NEEDED IT MOST. `polygon` and `blob`
    mean "none of the above", and with no fit to report they were reaching the
    belief layer unqualified — measured, an occluded circle read as a polygon,
    got the full quality of a confident reading, and was wrong 100% of the time.
    A residual category is supported by how clearly the measurement failed to be
    anything else, which is its distance BELOW the ellipse cut.
    """
    peri = cv2.arcLength(contour, True)
    if peri <= 0:
        return "blob", None, 0.0
    approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
    v = len(approx)
    if v == 3:
        # Discrete: a vertex count is exact, so the reading is fully resolved.
        # What can still be wrong about it is the contour it ran on, and that is
        # `_contour_fidelity`'s to say, not this function's.
        return "triangle", None, 1.0
    if v == 4:
        x, y, w, h = cv2.boundingRect(approx)
        aspect = w / h if h else 0
        label = "square" if _SQUARE_ASPECT[0] <= aspect <= _SQUARE_ASPECT[1] \
            else "rectangle"
        # Square-or-rectangle IS a threshold, on aspect, so it carries a margin:
        # a 1.17 aspect is a square by a hair and should say so.
        near = min(abs(aspect - _SQUARE_ASPECT[0]), abs(aspect - _SQUARE_ASPECT[1]))
        return label, None, round(min(1.0, near / _ASPECT_RESOLUTION), 3)
    circularity = 4 * math.pi * area / (peri * peri)
    circularity = round(max(0.0, min(1.0, float(circularity))), 3)
    if circularity > _CIRCLE_CUT:
        return "circle", circularity, _margin(circularity, _CIRCLE_CUT,
                                              _CIRC_RESOLUTION)
    if circularity > _ELLIPSE_CUT:
        return "ellipse", circularity, min(
            _margin(circularity, _CIRCLE_CUT, _CIRC_RESOLUTION),
            _margin(circularity, _ELLIPSE_CUT, _CIRC_RESOLUTION))
    return "polygon", None, _margin(circularity, _ELLIPSE_CUT, _CIRC_RESOLUTION)


def _view_fidelity(regions: List[Dict[str, Any]]) -> Dict[str, float]:
    """How much the conditions of THIS look let a measurement be about the object.

    A SUMMARY OF THE PER-READING FIDELITIES, not an independent frame statistic.
    That distinction is the whole lesson of this module: a frame-wide photometric
    number keeps mistaking the SUBJECT for a defect. Two versions were tried and
    both failed on real input --

    - a clipped-pixel fraction, which read a clean studio shot on a white ground
      at 0.044, because a white background is not overexposure, it is white;
    - the frame's Laplacian variance against the `sharp` cut, which called all
      four of a set of real 4K videos POOR -- daytime included, scoring 0.361 --
      because a real sky is smooth, and smooth is the subject, not blur.

    Meanwhile the per-contour edge fidelity read 0.96-0.99 on those same frames,
    which is correct: those boundaries genuinely are crisp. So the honest summary
    is the one built from the numbers that already condition each claim, taken as
    MEDIANS so that a region with no measurable boundary at all -- the frame
    itself, which has no contour step -- cannot drag the whole look down.

    `blur_score` and `sharp` remain in the description untouched; they are a
    frame statistic and honest as one. They are simply not a statement about how
    well this look resolved anything."""
    edges = sorted(float(r.get("edge_fidelity") or 0.0) for r in regions)
    chroma = sorted(float(r.get("chroma_fidelity") or 0.0) for r in regions)
    out: Dict[str, float] = {}
    if edges:
        out["contour"] = round(edges[len(edges) // 2], 3)
    if chroma:
        out["chroma"] = round(chroma[len(chroma) // 2], 3)
    return out


def _border_share(gray, mask) -> float:
    """The fraction of the image's outermost ring of pixels that lies inside this
    region.

    WHAT IT IS FOR. Telling the background apart from the things in front of it
    was a single magic number -- `area_fraction > 0.9` -- and a number cannot say
    what a region IS. Measured: under a 10% occlusion the white ground came in at
    area 0.895, missed that cut by five thousandths, was admitted as an OBJECT,
    and then out-ranked the real object by area so the thing being looked at
    moved from blob1 to blob2. A crop does the same thing for a different reason:
    zooming in shrinks the visible ground below 0.9 while leaving it just as much
    the background, which produced 50 spurious relations to `white` in FRAME-01.

    The background is what the edges of a picture are made of. That is a
    property, not a size, and this measures it directly.

    MEASURED OVER A BAND, not the outermost ring of pixels, and that is not a
    detail. The region list is a union of Otsu contours and MSER convex hulls,
    and a hull's vertices land a pixel or two inside the image, so a one-pixel
    ring scored regions covering 99% of the frame at 0.000 -- geometrically
    impossible, and it would have handed every one of those to the substrate as
    an object. The band is a fixed small fraction of the short side, so it scales
    with the picture instead of with the resolution it was tested at."""
    h, w = gray.shape[:2]
    if h < 4 or w < 4:
        return 0.0
    d = max(2, int(round(_BORDER_BAND * min(h, w))))
    d = min(d, h // 2, w // 2)
    m = mask.astype(bool)
    band = np.zeros(m.shape, bool)
    band[:d, :] = band[-d:, :] = True
    band[:, :d] = band[:, -d:] = True
    total = int(band.sum())
    return round(float(m[band].sum()) / total, 3) if total else 0.0


def _contour_fidelity(gray, contour, area: float) -> float:
    """How faithful ONE contour's geometry is, measured on the contour itself.

    WHY NOT THE FRAME'S SHARPNESS. That is what this did first, and measuring it
    refuted it: a Gaussian destroys a whole frame's Laplacian variance while
    leaving a big high-contrast edge perfectly recoverable, so frame sharpness
    drove the support of blurred shape readings to 0.03 when those readings were
    still right 92% of the time. Doubt that extreme is as dishonest as the false
    confidence this exists to remove -- it just fails in the safe direction.

    WHAT ACTUALLY MATTERS is the smear RELATIVE TO THE THING. Blur spreads a
    boundary over some width in pixels; eight pixels of smear on a 400-pixel disc
    leaves the polygon approximation untouched, and on a 20-pixel blob it is
    fatal. So the width is measured and compared against the object's own scale.

    Edge width comes from the gradient. Across a step of height `step` smeared
    over `w` pixels, the peak gradient is about `step / w`, so `w = step / grad`.
    Both terms are measured here: the step from the intensity either side of the
    boundary, the gradient from Sobel on the boundary band."""
    band = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(band, [contour], -1, 255, 3)
    on_edge = band.astype(bool)
    if not on_edge.any() or area <= 0:
        return 0.0
    filled = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(filled, [contour], -1, 255, -1)
    inside = filled.astype(bool) & ~on_edge
    outside = ~filled.astype(bool) & ~on_edge
    if not inside.any() or not outside.any():
        return 0.0
    g = gray.astype(np.float32)
    step = abs(float(g[inside].mean()) - float(g[outside].mean()))
    if step < 1.0:            # no step to measure: the boundary is not one
        return 0.0
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    # Sobel with ksize=3 answers 4x the per-pixel slope for an ideal step.
    slope = float(np.sqrt(gx * gx + gy * gy)[on_edge].mean()) / 4.0
    if slope <= 0:
        return 0.0
    width = step / slope
    scale = math.sqrt(float(area))
    return round(max(0.0, min(1.0, 1.0 - width / scale)), 3)


def _view_category(view: Dict[str, float]) -> str:
    """The conditions of the look as a word, the way brightness and focus are
    already reported as words.

    Stated categorically and not as the raw float on purpose: every other
    property on a percept is a category, and admitting a continuous value would
    mint a fresh literal concept per image for a number whose exact value no rule
    wants to bind to. The scalars stay available on `view_fidelity` and on each
    region's own supports, which is where precision actually matters.

    `_exposure()` DELIBERATELY DOES NOT ENTER HERE. It was tried, and it is the
    same frame-wide mistake this module has now made three separate times: it
    calls anything with more than 12% of its pixels above 240 overexposed, so a
    studio card on a white ground is "overexposed" and every clean test image was
    being held at `fair` by that alone. Genuine blow-out goes toward white and
    collapses saturation, which the chroma term already measures -- per region,
    where the reading was actually taken."""
    worst = min(view.values()) if view else 0.0
    return "clear" if worst >= 0.8 else ("fair" if worst >= 0.4 else "poor")


def _dominant_colors(img, k: int = 6) -> List[Dict[str, Any]]:
    """The palette of one image: each colour named, with its fraction and hex,
    largest first. Computed by k-means on THIS image -- the palette is measured,
    not looked up."""
    small = cv2.resize(img, (96, 96), interpolation=cv2.INTER_AREA)
    pixels = small.reshape(-1, 3).astype(np.float32)
    k = min(k, len(np.unique(pixels, axis=0)))
    if k < 1:
        return []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3,
                                    cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.flatten(), minlength=k)
    total = float(counts.sum()) or 1.0
    merged: Dict[str, Dict[str, Any]] = {}
    for i in np.argsort(-counts):
        name, _margin_unused = _color_name(centers[i])
        frac = float(counts[i]) / total
        if name in merged:
            merged[name]["fraction"] += frac
        else:
            merged[name] = {"name": name, "fraction": frac,
                            "hex": _rgb_hex(centers[i])}
    out = sorted(merged.values(), key=lambda d: -d["fraction"])
    for d in out:
        d["fraction"] = round(d["fraction"], 3)
    return out


def _scaled(im, maxside: int = 900):
    """A working copy no larger than maxside on its long edge. Region/geometry
    analysis runs on this for speed; every reported value is a FRACTION, which is
    scale-invariant, so the description is the same as at full resolution."""
    h, w = im.shape[:2]
    s = maxside / max(h, w)
    if s >= 1:
        return im
    return cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))),
                      interpolation=cv2.INTER_AREA)


def _describe_contour(c, img, gray, W: int, H: int,
                      ) -> Dict[str, Any]:
    area = cv2.contourArea(c)
    x, y, ww, hh = cv2.boundingRect(c)
    hull_area = cv2.contourArea(cv2.convexHull(c)) or area or 1.0
    m = cv2.moments(c)
    cx = m["m10"] / m["m00"] if m["m00"] else x + ww / 2
    cy = m["m01"] / m["m00"] if m["m00"] else y + hh / 2
    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, [c], -1, 255, -1)
    area_frac = area / float(W * H)
    shape_label, shape_fit, shape_margin = _shape_of(c, area)
    size_label, size_margin = _size_category(area_frac)
    color_label, color_margin, chroma = _region_color(img, mask)
    edge = _contour_fidelity(gray, c, area)

    # EACH LABEL'S SUPPORT = HOW ROBUST THE READING IS x HOW MUCH THE LOOK LETS
    # IT BE ABOUT THE OBJECT. Both have to hold, so they multiply; neither alone
    # is enough. A colour dead-centre of its band read off blown-out pixels is
    # not a supported claim about the object, and neither is a well-exposed one
    # sitting a single level from the cut that renames it.
    #
    # The fidelity term is the one measured WHERE THE READING WAS TAKEN: chroma
    # over this region's own pixels, edge sharpness along this contour. A
    # frame-wide number was tried first and was wrong in both directions -- it
    # blamed an object for a blown-out sky in the corner, and it excused a smeared
    # boundary because the rest of the picture was sharp.
    shape_support = edge * shape_margin
    desc: Dict[str, Any] = {
        "area_fraction": round(area_frac, 3),
        "bbox_norm": [round(x / W, 3), round(y / H, 3),
                      round(ww / W, 3), round(hh / H, 3)],
        #: The contour's centroid, normalised. PUBLIC, where it used to be a
        #: private `_cx`/`_cy` stripped before the description left this module.
        #: Relations between regions are the only frame-INVARIANT thing here --
        #: `larger_than` survives every geometric transform measured, 48/48 --
        #: and they cannot be computed by a consumer that was handed the labels
        #: and denied the geometry they come from.
        "center": [round(cx / W, 3), round(cy / H, 3)],
        "position": _position(cx, cy, W, H),
        "size": size_label,
        #: How far the area fraction sits from the next band, geometrically. This
        #: is support for the READING and never for the band being a property of
        #: the object, which it is not -- see `_size_category`.
        "size_support": size_margin,
        "shape": shape_label,
        #: How strongly the contour bears out `shape` under this look. The raw
        #: geometric fit is kept alongside as `shape_fit`, None where the shape
        #: was decided by a vertex count and no fit exists -- None there means
        #: "no scalar fit", never "poorly fitted".
        "shape_support": round(float(shape_support), 3),
        "shape_fit": shape_fit,
        "shape_margin": round(float(shape_margin), 3),
        "edge_fidelity": edge,
        "color": color_label,
        #: Margin x the region's own chroma fidelity. This is the number that was
        #: missing: it is what falls when the bulb dims or the colour washes out,
        #: and it is what the acceptance band needs in order to tell a bad look
        #: from a confident one.
        "color_support": round(float(color_margin * chroma), 3),
        "color_margin": round(float(color_margin), 3),
        "chroma_fidelity": chroma,
        "aspect_ratio": round(ww / hh, 2) if hh else 0.0,
        "solidity": round(area / hull_area, 3),
        "extent": round(area / (ww * hh), 3) if ww * hh else 0.0,
        #: How much of the PICTURE'S OWN EDGE this region is made of. The ground
        #: is what surrounds everything else, and surrounding things is a
        #: property a region either has or does not -- measurable here, where the
        #: mask is, and not guessable downstream from an area fraction.
        "border_share": _border_share(gray, mask),
    }
    if len(c) >= 5:
        (_c, (MA, ma), angle) = cv2.fitEllipse(c)
        desc["orientation_deg"] = round(float(angle), 1)
        desc["elongation"] = round(float(max(MA, ma) / max(1e-3, min(MA, ma))), 2)
    return desc


def _regions(img, gray, *, max_regions: int = 10,
             min_area_frac: float = _MIN_REGION_FRAC) -> List[Dict[str, Any]]:
    """Object-like blobs, each DESCRIBED (never named): size, position, shape,
    dominant colour, aspect, solidity, extent, orientation. Two detectors are
    unioned -- Otsu figure/ground (both polarities) and MSER stable regions --
    so a blob found either way is kept. Largest first, de-duplicated."""
    H, W = gray.shape[:2]
    min_area = min_area_frac * W * H
    candidates: List[Any] = []

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thr = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for polarity in (thr, cv2.bitwise_not(thr)):
        mask = cv2.morphologyEx(polarity, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates.extend(cnts)

    try:
        mser = cv2.MSER_create()
        mser.setMinArea(int(min_area))
        mser.setMaxArea(int(0.9 * W * H))
        points, _ = mser.detectRegions(gray)
        candidates.extend(cv2.convexHull(p.reshape(-1, 1, 2)) for p in points)
    except Exception:
        pass

    usable = [c for c in candidates if cv2.contourArea(c) >= min_area]
    described = [_describe_contour(c, img, gray, W, H) for c in usable]
    order = sorted(range(len(described)),
                   key=lambda i: -described[i]["area_fraction"])

    kept: List[Dict[str, Any]] = []
    kept_masks: List[Any] = []
    for i in order:
        r = described[i]
        if any(r["position"] == k["position"]
               and abs(r["area_fraction"] - k["area_fraction"]) < 0.02
               for k in kept):
            continue
        # THE SAME STUFF, FOUND AGAIN, IS NOT A SECOND THING. Two detectors run
        # here and Otsu runs at both polarities, so one white card comes back as
        # a nest of overlapping white rectangles at 0.826, 0.731, 0.627, 0.592 --
        # measured under a 10% occlusion, where four phantom regions were
        # admitted as objects alongside the one real one.
        #
        # Containment ALONE cannot say this, and getting that wrong would be
        # worse than the defect: the red circle also sits inside the white card,
        # and dropping everything contained by something else would throw away
        # every object that rests on a background. What distinguishes a
        # re-detection is that it is the same MATERIAL -- inside a region already
        # kept AND named the same colour. An object on a background differs in
        # colour from it, which is most of why it was segmented in the first
        # place.
        mask = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(mask, [usable[i]], -1, 255, -1)
        mb = mask.astype(bool)
        own = int(mb.sum()) or 1
        if any(k["color"] == r["color"]
               and int((mb & km).sum()) / own > _SAME_STUFF
               for k, km in zip(kept, kept_masks)):
            continue
        kept.append(r)
        kept_masks.append(mb)
        if len(kept) >= max_regions:
            break
    return kept


#: How far apart two centroids must sit before one is called left of or above
#: the other, and how many times bigger one area must be to be `larger_than`.
#: Named because the relations are now ADMITTED rather than computed and thrown
#: away, so these two numbers decide what the substrate comes to believe.
_SEPARATION = 0.1
_LARGER_RATIO = 1.5


def relations(regions: List[Dict[str, Any]], top: int = 4) -> List[Dict[str, Any]]:
    """Spatial and size relations among the most prominent regions, as
    `{"a": i, "rel": ..., "b": j}` over the list GIVEN -- left_of, above,
    larger_than.

    THE ONLY FRAME-INVARIANT THING THIS MODULE PRODUCES, which is why it stopped
    being private. Every absolute here is a property of the framing wearing the
    costume of a property of the object: measured across geometric transforms of
    the same two-object scenes, the size BAND survived 73% and the position WORD
    52%, while `larger_than` survived **48 of 48** and invented nothing. Move the
    camera closer and a `medium` thing becomes `large`; move it closer and the
    larger of two things is still the larger of two things.

    It is computed over the list it is handed, NOT over the describer's raw
    region list, because the caller decides what counts as an object -- the frame
    itself is a region and is not a thing. Indices refer to that same list, so
    the caller can name the parts without a second numbering to keep in step.

    `left_of` and `above` are invariant under zoom, translation and perspective
    (100% each) and NOT under rotation (81% and 62%, and rotation invented ten
    `above` facts). That is correct rather than a defect -- turning a photograph
    really does reorient what is above what -- and it is why the two kinds are
    reported distinctly instead of as one bag of "relations".

    Each relation carries its own `support`, on the same principle as every other
    thresholded label here: a pair separated by exactly the threshold is not the
    same claim as a pair separated by half the frame, and saying so is the whole
    of D1. Fully resolved at TWICE the threshold, which is the distance at which
    the opposite call stops being reachable by any nuisance measured."""
    rels: List[Dict[str, Any]] = []
    rs = regions[:top]

    def gap(sep: float) -> float:
        return round(min(1.0, max(0.0, (sep - _SEPARATION) / _SEPARATION)), 3)

    def ratio(big: float, small: float) -> float:
        if small <= 0:
            return 1.0
        return round(min(1.0, max(0.0, (big / small) / _LARGER_RATIO - 1.0)), 3)

    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            a, b = rs[i], rs[j]
            (ax, ay), (bx, by) = a["center"], b["center"]
            aa, ba = a["area_fraction"], b["area_fraction"]
            if ax < bx - _SEPARATION:
                rels.append({"a": i, "rel": "left_of", "b": j,
                             "support": gap(bx - ax)})
            elif bx < ax - _SEPARATION:
                rels.append({"a": j, "rel": "left_of", "b": i,
                             "support": gap(ax - bx)})
            if ay < by - _SEPARATION:
                rels.append({"a": i, "rel": "above", "b": j,
                             "support": gap(by - ay)})
            elif by < ay - _SEPARATION:
                rels.append({"a": j, "rel": "above", "b": i,
                             "support": gap(ay - by)})
            if aa > ba * _LARGER_RATIO:
                rels.append({"a": i, "rel": "larger_than", "b": j,
                             "support": ratio(aa, ba)})
            elif ba > aa * _LARGER_RATIO:
                rels.append({"a": j, "rel": "larger_than", "b": i,
                             "support": ratio(ba, aa)})
    return rels


def _geometry(gray) -> Dict[str, int]:
    """Straight lines (by orientation) and circles, via the Hough transform."""
    edges = cv2.Canny(gray, 80, 200)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60,
                            minLineLength=max(20, min(gray.shape[:2]) // 4),
                            maxLineGap=10)
    horiz = vert = diag = 0
    if lines is not None:
        for x1, y1, x2, y2 in lines[:, 0, :]:
            ang = abs(math.degrees(math.atan2(float(y2 - y1), float(x2 - x1))))
            if ang < 20 or ang > 160:
                horiz += 1
            elif 70 < ang < 110:
                vert += 1
            else:
                diag += 1
    n_lines = horiz + vert + diag
    circles = 0
    try:
        found = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, dp=1.2,
                                 minDist=max(10, gray.shape[0] // 8),
                                 param1=100, param2=45, minRadius=0, maxRadius=0)
        circles = 0 if found is None else int(found.shape[1])
    except Exception:
        pass
    return {"lines": n_lines, "horizontal_lines": horiz, "vertical_lines": vert,
            "diagonal_lines": diag, "circles": circles}


def _symmetry(gray) -> Dict[str, float]:
    """Left-right and top-bottom mirror symmetry, 0..1, on a normalised copy."""
    g = cv2.resize(gray, (128, 128)).astype(int)
    lr = 1 - float(np.abs(g - np.fliplr(g)).mean()) / 255
    ud = 1 - float(np.abs(g - np.flipud(g)).mean()) / 255
    return {"horizontal": round(lr, 3), "vertical": round(ud, 3)}


def _texture_energy(gray) -> float:
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1)
    return round(float(np.sqrt(gx * gx + gy * gy).mean()), 1)


def _entropy(gray) -> float:
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
    p = hist / (hist.sum() or 1.0)
    p = p[p > 0]
    return round(float(-(p * np.log2(p)).sum()), 2)


def _brightness_category(v: float) -> str:
    if v < 50:
        return "dark"
    if v < 100:
        return "dim"
    if v < 170:
        return "normal"
    if v < 220:
        return "bright"
    return "very_bright"


def _contrast_category(std: float) -> str:
    return "low" if std < 30 else ("high" if std > 65 else "normal")


def _exposure(gray) -> str:
    over = float((gray > _CLIP_HIGH).mean())
    under = float((gray < _CLIP_LOW).mean())
    if over > 0.12:
        return "overexposed"
    if under > 0.15:
        return "underexposed"
    return "balanced"


def _decode_codes(img) -> List[str]:
    """Any QR payloads present -- exact semantic content, decoded, no model."""
    out: List[str] = []
    try:
        detector = cv2.QRCodeDetector()
        ok, decoded, _pts, _ = detector.detectAndDecodeMulti(img)
        if ok:
            out.extend(t for t in decoded if t)
    except Exception:
        try:
            text, _pts, _ = cv2.QRCodeDetector().detectAndDecode(img)
            if text:
                out.append(text)
        except Exception:
            pass
    return out


def _exif(pil_image) -> Dict[str, Any]:
    """Camera, capture date, orientation, GPS presence -- read from the file's
    own EXIF, when present. Absent EXIF is reported as absent, never invented."""
    info: Dict[str, Any] = {}
    try:
        from PIL import ExifTags
        raw = pil_image.getexif()
        if not raw:
            return info
        tags = {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}
        make = str(tags.get("Make", "") or "").strip()
        model = str(tags.get("Model", "") or "").strip()
        camera = (make + " " + model).strip()
        if camera:
            info["camera"] = camera.lower().replace(" ", "_")
        dt = str(tags.get("DateTimeOriginal") or tags.get("DateTime") or "").strip()
        if dt and ":" in dt:                   # "2026:04:15 10:22:00" -> "2026-04-15"
            info["captured"] = dt.split(" ")[0].replace(":", "-")
        if "Orientation" in tags:
            info["orientation"] = int(tags["Orientation"])
        if tags.get("GPSInfo"):
            info["has_gps"] = True
    except Exception:
        pass
    return info


def _sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def describe_image(path: str) -> Dict[str, Any]:
    """Everything classically knowable about one real image file.

    Raises on a path that names no readable image -- a file that cannot be read
    is a real failure, distinct from an image that simply contains little
    structure."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no image at {path}")
    data = p.read_bytes()

    from PIL import Image
    try:
        pim = Image.open(io.BytesIO(data)); pim.load()
    except Exception as e:
        raise ValueError(f"{path} is not a readable image: {e}")
    fmt = (pim.format or p.suffix.lstrip(".")).lower()
    width, height = pim.size

    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:                            # formats cv2 can't decode (e.g. HEIC)
        img = cv2.cvtColor(np.array(pim.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Region and geometry analysis runs on a bounded working copy (fractions are
    # scale-invariant); global photometrics use the full-resolution grey.
    work_img, work_gray = _scaled(img), _scaled(gray)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    edges = cv2.Canny(gray, 100, 200)
    keypoints = len(cv2.ORB_create(1500).detect(gray, None) or [])
    colorfulness = _colorfulness(img)

    regions = _regions(work_img, work_gray)
    # The look is summarised FROM the regions, because the fidelities that
    # condition each claim are measured where each reading was taken.
    view = _view_fidelity(regions)
    region_relations = relations(regions)

    result: Dict[str, Any] = {
        "kind": "image",
        "path": str(p),
        "sha256": _sha256(data),
        "format": fmt,
        "width": int(width),
        "height": int(height),
        "megapixels": round(width * height / 1e6, 2),
        "orientation": ("square" if width == height else
                        ("portrait" if height > width else "landscape")),
        "aspect_ratio": round(width / height, 2) if height else 0.0,
        "brightness": round(brightness, 1),
        "brightness_category": _brightness_category(brightness),
        "contrast": round(contrast, 1),
        "contrast_category": _contrast_category(contrast),
        "exposure": _exposure(gray),
        "blur_score": round(blur, 1),
        "sharp": bool(blur >= _SHARP_CUT),
        #: How much the conditions of this look let a measurement be about the
        #: object at all -- reported at the top level so a consumer can weigh the
        #: whole observation, not only the per-region supports derived from it.
        "view_fidelity": view,
        "view_category": _view_category(view),
        "edge_density": round(float((edges > 0).mean()), 4),
        "keypoints": int(keypoints),
        "texture_energy": _texture_energy(gray),
        "entropy": _entropy(gray),
        "colorfulness": colorfulness,
        "colorfulness_category": _colorfulness_category(colorfulness),
        "palette_temperature": _palette_temperature(img),
        "symmetry": _symmetry(gray),
        "geometry": _geometry(work_gray),
        "dominant_colors": _dominant_colors(img),
        "regions": regions,
        "region_count": len(regions),
        "region_relations": region_relations,
        "codes": _decode_codes(img),
    }
    result.update(_exif(pim))
    return result


# --- video ---------------------------------------------------------------

def _ffprobe(path: str) -> Dict[str, Any]:
    """Container facts from ffprobe: codec, resolution, duration, fps, frames."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60)
        import json
        meta = json.loads(out.stdout or "{}")
    except Exception:
        return {}
    v = next((s for s in meta.get("streams", [])
              if s.get("codec_type") == "video"), {})
    fps = 0.0
    rate = str(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1")
    if "/" in rate:
        n, d = rate.split("/")
        fps = round(float(n) / float(d), 2) if float(d) else 0.0
    dur = v.get("duration") or meta.get("format", {}).get("duration")
    info: Dict[str, Any] = {}
    if v.get("codec_name"):
        info["codec"] = str(v["codec_name"]).lower()
    if v.get("width"):
        info["width"] = int(v["width"]); info["height"] = int(v["height"])
    if dur:
        info["duration"] = round(float(dur), 2)
    if fps:
        info["fps"] = fps
    if v.get("nb_frames") and str(v["nb_frames"]).isdigit():
        info["frames"] = int(v["nb_frames"])
    return info


def describe_video(path: str, *, sample: int = 24) -> Dict[str, Any]:
    """Everything classically knowable about one real video: container facts plus
    measured motion and scene structure over sampled frames."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no video at {path}")

    result: Dict[str, Any] = {"kind": "video", "path": str(p),
                              "sha256": _sha256(p.read_bytes())}
    result.update(_ffprobe(str(p)))

    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        raise ValueError(f"{path} could not be opened as video")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    result.setdefault("frames", total)

    # SEEK to a bounded set of evenly-spaced frames rather than decoding the whole
    # clip, so the work is the same for a 10-second and a 10-minute video.
    n = max(2, min(sample, total)) if total else sample
    indices = ([int(round(i * (total - 1) / (n - 1))) for i in range(n)]
               if total else list(range(n)))
    mid = indices[len(indices) // 2]

    prev = None
    motions: List[float] = []
    scene_changes = 0
    keyframe: Optional[Dict[str, Any]] = None
    for fi in indices:
        if total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            flow = cv2.calcOpticalFlowFarneback(
                prev, gray, None, 0.5, 2, 15, 2, 5, 1.2, 0)
            motions.append(float(np.linalg.norm(flow, axis=2).mean()))
            if float(np.abs(gray.astype(int) - prev.astype(int)).mean()) > 25:
                scene_changes += 1
        prev = gray
        if keyframe is None and fi >= mid:
            try:
                # The keyframe gets its OWN conditions measured. Inheriting a
                # perfect look would say a blurred frame grabbed mid-motion is as
                # good evidence as a still photograph, which is the exact false
                # confidence the support numbers exist to remove.
                kgray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                kregions = _regions(frame, kgray)
                kview = _view_fidelity(kregions)
                keyframe = {"regions": kregions,
                            "view_fidelity": kview,
                            "view_category": _view_category(kview),
                            "dominant_colors": _dominant_colors(frame)}
            except Exception:
                keyframe = None
    cap.release()

    mean_motion = round(float(np.mean(motions)), 3) if motions else 0.0
    result.update({
        "sampled_frames": len(motions) + (1 if motions else 0),
        "mean_motion": mean_motion,
        "has_motion": bool(mean_motion > 0.3),
        "scene_changes": scene_changes,
    })
    if keyframe:
        result["keyframe"] = keyframe
    return result
