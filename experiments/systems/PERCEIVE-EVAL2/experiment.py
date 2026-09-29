#!/usr/bin/env python3
"""PERCEIVE-EVAL2 — how far the perceive-and-name loop goes, and where it stops.

PERCEIVE-EVAL established the loop on three categories. This measures its
OPERATING RANGE, which is what a reader needs in order to trust or refuse the
earlier result. Four studies, all on the real substrate, no model anywhere:

  A  SCALE            eight categories over seven colour families and three
                      shapes, each taught from two labelled examples and two
                      discriminating counter-examples, then tested on held-out
                      positives and near-miss negatives.
  B  DATA EFFICIENCY  the same protocol at k = 1, 2, 3, 4 labelled positives.
                      How many examples does a category cost?
  C  SUPERVISION      0, 1 or 2 counter-examples, with the positives sharing an
                      INCIDENTAL feature (all the same size). What the negatives
                      buy is the removal of that accident from the rule.
  D  OPERATING RANGE  perception under noise, blur, occlusion, desaturation and
                      small apparent size, including the minimum blob area the
                      faculty reports at all (a configured parameter, not a
                      failure): where measurement stops being reliable.

Everything is written to manifest.json. Domain `perceval2`, cleaned before and
after, so no other domain's learned state is touched.

    PYTHONPATH="$PWD" TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-EVAL2/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, sys, time
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"

import numpy as np
import cv2

DOMAIN = "perceval2"

COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 170, 0),
           "yellow": (0, 215, 255), "violet": (160, 32, 160),
           "orange": (0, 140, 255), "cyan": (200, 200, 0)}

#: category -> (shape, colour). Eight categories across seven colour families
#: and three shapes, so neither colour nor shape alone identifies a class.
CATS = {
    "redcircle": ("circle", "red"), "bluesquare": ("square", "blue"),
    "greentri": ("triangle", "green"), "yellowsquare": ("square", "yellow"),
    "violetcircle": ("circle", "violet"), "orangetri": ("triangle", "orange"),
    "cyansquare": ("square", "cyan"), "redtri": ("triangle", "red"),
}
SIZES = [58, 44, 70, 52, 64, 40, 48, 66]


def draw(path, shape, colour, size=55, angle=0, cx=150, cy=150,
         noise=0, bg=255, blur=0, alpha=1.0, occl=0):
    """One real image file with real pixels."""
    img = np.full((300, 300, 3), bg, np.uint8)
    layer = img.copy()
    bgr = COLOURS[colour] if isinstance(colour, str) else colour
    if shape == "circle":
        cv2.circle(layer, (cx, cy), size, bgr, -1)
    else:
        unit = (np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
                if shape == "square" else
                np.array([[0, -1], [-1, 1], [1, 1]], np.float32))
        pts = unit * size
        th = np.deg2rad(angle)
        rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]], np.float32)
        cv2.fillPoly(layer, [((pts @ rot.T) + [cx, cy]).astype(np.int32)], bgr)
    img = cv2.addWeighted(layer, alpha, img, 1 - alpha, 0)
    if occl:
        cv2.rectangle(img, (cx - size, cy - size), (cx - size + occl, cy + size),
                      (int(bg),) * 3, -1)
    if blur:
        img = cv2.GaussianBlur(img, (blur | 1, blur | 1), 0)
    if noise:
        rng = np.random.RandomState(7)
        img = np.clip(img.astype(np.int16) + rng.normal(0, noise, img.shape),
                      0, 255).astype(np.uint8)
    cv2.imwrite(str(path), img)
    return path


def yes_no(answer):
    a = (answer or "").strip().lower()
    if a.startswith("yes") or a.startswith("true"):
        return True
    if a.startswith("no") or a.startswith("false"):
        return False
    return None


async def clean(db):
    # The STORE forgets its own rules: it is what knows every table that
    # references one. The hand-rolled version here deleted the evidence and
    # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
    # table does not have -- leaving the rule standing with its evidence gone.
    from core.learning.rule_store import get_rule_store
    await get_rule_store().forget_domain(DOMAIN)


async def main() -> int:
    STIM.mkdir(exist_ok=True)
    t_start = time.perf_counter()
    buf = io.StringIO()
    out = {}

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.perception import vision
        from core.database import get_database_manager
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager(); await db.initialize()
        await clean(db)

        # EVERY SUBJECT NAME IS UNIQUE TO THIS RUN. Names are concept-graph
        # identities and the graph is shared across experiments, so a fixed
        # scheme silently merges this run's features onto an earlier run's
        # subject (and inherits its labels). A first version of this experiment
        # did exactly that, and three categories failed to induce because their
        # examples carried two images' features at once.
        RUN = uuid4().hex[:6]
        counter = [0]
        timings = {"perceive_ms": [], "teach_ms": [], "induce_ms": [], "name_ms": []}
        fidelity = []

        async def stimulus(shape, colour, prefix, size=None):
            """Draw, perceive, and teach one blob's perceived features."""
            counter[0] += 1
            name = f"{prefix}_{RUN}_{counter[0]}"
            path = STIM / f"{name}.png"
            draw(path, shape, colour, size or SIZES[counter[0] % len(SIZES)])
            t0 = time.perf_counter()
            described = vision.describe_image(str(path))
            timings["perceive_ms"].append((time.perf_counter() - t0) * 1000)
            regions = [r for r in described["regions"] if r["area_fraction"] <= 0.9]
            region = regions[0]
            fidelity.append({"drawn_shape": shape, "drawn_colour": colour,
                             "perceived_shape": region["shape"],
                             "perceived_colour": region["color"]})
            t0 = time.perf_counter()
            await coord.learning.learn_facts(
                [(name, "isa", f) for f in (region["color"], region["shape"], region["size"])],
                domain=DOMAIN)
            timings["teach_ms"].append((time.perf_counter() - t0) * 1000)
            return name

        async def induce(cat, positives, negatives):
            t0 = time.perf_counter()
            result = await coord.learning.induce_category(
                cat, positives=positives, negatives=negatives, domain=DOMAIN)
            timings["induce_ms"].append((time.perf_counter() - t0) * 1000)
            return result

        async def ask(subject, cat):
            from core.memory import Origin
            t0 = time.perf_counter()
            res = await coord.reason_about(f"is {subject} a {cat}?", origin=Origin.own("PERCEIVE-EVAL2"))
            timings["name_ms"].append((time.perf_counter() - t0) * 1000)
            md = dict(getattr(res, "metadata", {}) or {})
            return yes_no(getattr(res, "answer", "")), int(md.get("model_calls") or 0)

        model_calls = 0

        async def score(cat, positives, negatives):
            """Held-out recall and abstention for one category."""
            nonlocal model_calls
            named = 0
            for s in positives:
                verdict, calls = await ask(s, cat); model_calls += calls
                named += verdict is True
            declined = false_named = 0
            for s in negatives:
                verdict, calls = await ask(s, cat); model_calls += calls
                if verdict is True:
                    false_named += 1
                else:
                    declined += 1
            return {"recall": round(named / max(1, len(positives)), 3),
                    "abstention": round(declined / max(1, len(negatives)), 3),
                    "false_namings": false_named,
                    "n_pos": len(positives), "n_neg": len(negatives)}

        # ── A. SCALE: eight categories ─────────────────────────────────────
        per_cat, rules = {}, {}
        for base_cat, (shape, colour) in CATS.items():
            cat = f"{base_cat}{RUN}"
            pos = [await stimulus(shape, colour, f"{cat}_p") for _ in range(2)]
            negs = []
            for ns, nc in ((shape, "blue" if colour != "blue" else "red"),
                           ("circle" if shape != "circle" else "square", colour)):
                negs.append(await stimulus(ns, nc, f"{cat}_n"))
            result = await induce(cat, pos, negs)
            rules[base_cat] = str(getattr(result, "rule", None))
            test_pos = [await stimulus(shape, colour, f"{cat}_tp") for _ in range(3)]
            test_neg = []
            for ns, nc in ((shape, "yellow" if colour != "yellow" else "green"),
                           ("triangle" if shape != "triangle" else "square", colour),
                           ("circle" if shape != "circle" else "square",
                            "violet" if colour != "violet" else "orange")):
                test_neg.append(await stimulus(ns, nc, f"{cat}_tn"))
            per_cat[base_cat] = await score(cat, test_pos, test_neg)
        out["scale"] = {"categories": len(CATS), "per_category": per_cat,
                        "induced_rules": rules}

        # ── B. DATA EFFICIENCY: k labelled positives ───────────────────────
        efficiency = {}
        for k in (1, 2, 3, 4):
            await clean(db)
            cat = f"effcat{RUN}{k}"
            pos = [await stimulus("circle", "red", f"{cat}_p") for _ in range(k)]
            negs = [await stimulus("square", "red", f"{cat}_n"),
                    await stimulus("circle", "blue", f"{cat}_n")]
            try:
                result = await induce(cat, pos, negs)
                rule = str(getattr(result, "rule", None))
                refused = None
            except ValueError as e:      # fewer than two positives is refused
                rule, refused = None, str(e)
            test_pos = [await stimulus("circle", "red", f"{cat}_tp") for _ in range(3)]
            test_neg = [await stimulus("square", "red", f"{cat}_tn"),
                        await stimulus("circle", "blue", f"{cat}_tn"),
                        await stimulus("triangle", "red", f"{cat}_tn")]
            scored = await score(cat, test_pos, test_neg)
            efficiency[k] = {"rule": rule, "refused": refused, **scored}
        out["data_efficiency"] = efficiency

        # ── C. SUPERVISION: what the counter-examples buy ──────────────────
        # Every positive is drawn at the SAME size, so "medium" is an accident of
        # the sample. A counter-example that shares it is what removes it.
        supervision = {}
        for n_neg in (0, 1, 2):
            await clean(db)
            cat = f"supcat{RUN}{n_neg}"
            pos = [await stimulus("circle", "red", f"{cat}_p", size=58) for _ in range(3)]
            negs = []
            if n_neg >= 1:                                    # shares the colour
                negs.append(await stimulus("square", "red", f"{cat}_n", size=58))
            if n_neg >= 2:                                    # shares the shape
                negs.append(await stimulus("circle", "blue", f"{cat}_n", size=58))
            result = await induce(cat, pos, negs)
            rule = getattr(result, "rule", None)
            body = sorted(str(f.predicate) for f in getattr(rule, "body", []) or [])
            # held-out positives at DIFFERENT sizes: an over-specific rule misses them
            test_pos = [await stimulus("circle", "red", f"{cat}_tp", size=s)
                        for s in (30, 44, 86)]
            test_neg = [await stimulus("square", "red", f"{cat}_tn", size=58),
                        await stimulus("circle", "blue", f"{cat}_tn", size=58)]
            supervision[n_neg] = {"rule": str(rule), "body": body,
                                  **await score(cat, test_pos, test_neg)}
        out["supervision"] = supervision

        # ── D. OPERATING RANGE of the perceptual stage ─────────────────────
        def measure(label, **kw):
            shape_ok = colour_ok = reported = 0
            for shape in ("circle", "square", "triangle"):
                path = STIM / f"range_{label.replace(' ', '_').replace('%','pct')}_{shape}.png"
                draw(path, shape, "red", **kw)
                regions = [r for r in vision.describe_image(str(path))["regions"]
                           if r["area_fraction"] <= 0.9]
                if regions:
                    reported += 1
                    shape_ok += regions[0]["shape"] == shape
                    colour_ok += "red" in regions[0]["color"]
            return {"reported": reported, "shape": shape_ok, "colour": colour_ok, "n": 3}

        operating = {
            "baseline": measure("baseline"),
            "noise": {s: measure(f"noise{s}", noise=s) for s in (16, 48, 96, 128, 160)},
            "blur": {b: measure(f"blur{b}", blur=b) for b in (9, 21, 41, 61)},
            "rotation": {a: measure(f"rot{a}", angle=a) for a in (10, 30, 45)},
            "desaturation": {a: measure(f"alpha{a}", alpha=a) for a in (1.0, 0.7, 0.5, 0.3)},
            "occlusion": {o: measure(f"occl{o}", occl=o) for o in (30, 55, 80)},
            "apparent_size_px": {s: measure(f"size{s}", size=s) for s in (70, 40, 20, 18, 16, 12)},
        }
        # the minimum reported blob area is a PARAMETER; record it and what the
        # faculty reports when it is lowered.
        small = {}
        for radius in (20, 18, 16, 12, 8, 6, 4):
            path = draw(STIM / f"small_{radius}.png", "circle", "red", size=radius)
            img = cv2.imread(str(path)); gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            area_pct = round(100 * np.pi * radius * radius / (300 * 300), 3)
            default = [r for r in vision.describe_image(str(path))["regions"]
                       if r["area_fraction"] <= 0.9]
            lowered = [r for r in vision._regions(img, gray, min_area_frac=0.001)
                       if r["area_fraction"] <= 0.9]
            small[radius] = {
                "area_pct_of_frame": area_pct,
                "default_1pct": (default[0]["shape"] + "/" + default[0]["color"]) if default else None,
                "lowered_0p1pct": (lowered[0]["shape"] + "/" + lowered[0]["color"]) if lowered else None,
            }
        operating["minimum_blob_area"] = {
            "default_min_area_frac": 0.01, "lowered_min_area_frac": 0.001, "by_radius": small}
        out["operating_range"] = operating

        await clean(db)

    shape_ok = sum(1 for f in fidelity if f["perceived_shape"] == f["drawn_shape"])
    colour_ok = sum(1 for f in fidelity if f["drawn_colour"] in f["perceived_colour"])
    n = len(fidelity)
    mean = lambda d, key: round(sum(c[key] for c in d.values()) / len(d), 3)
    out["overall"] = {
        "images_taught": n,
        "perception_shape_accuracy": round(shape_ok / n, 3),
        "perception_colour_accuracy": round(colour_ok / n, 3),
        "scale_mean_recall": mean(out["scale"]["per_category"], "recall"),
        "scale_mean_abstention": mean(out["scale"]["per_category"], "abstention"),
        "scale_false_namings": sum(c["false_namings"] for c in out["scale"]["per_category"].values()),
        "model_calls": model_calls,
        "median_ms": {k: round(float(np.median(v)), 1) for k, v in timings.items() if v},
        "wall_clock_s": round(time.perf_counter() - t_start, 1),
    }
    manifest = {"experiment": "PERCEIVE-EVAL2",
                "run_at": datetime.now(timezone.utc).isoformat(), **out}
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps({k: out[k] for k in ("overall", "data_efficiency", "supervision")},
                     indent=2, default=str), flush=True)
    print("scale:", json.dumps(out["scale"]["per_category"], default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
