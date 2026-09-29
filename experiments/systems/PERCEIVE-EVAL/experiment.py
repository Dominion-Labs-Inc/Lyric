#!/usr/bin/env python3
"""PERCEIVE-EVAL — quantitative evaluation of perceive-and-name, for the paper.

Three categories (red circle, blue square, green triangle). For each: the
substrate perceives a small set of real images, is shown a few LABELLED examples,
induces a naming rule, and is then tested on HELD-OUT images -- positives it
should name and negatives it should decline. We measure:

  * perception fidelity: does the substrate recover the drawn shape and colour?
  * naming recall: held-out positives correctly named,
  * abstention: held-out negatives correctly declined (no hallucination),
  * model calls: must be zero throughout.

Every image is a real file with real pixels; no answers are given to the reasoner.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-EVAL/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, sys
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"

import numpy as np
import cv2

RED, BLUE, GREEN = (0, 0, 255), (255, 0, 0), (0, 170, 0)
COLOR_FAMILY = {"red": RED, "blue": BLUE, "green": GREEN}
DRAWN_FAMILY = {id(RED): "red", id(BLUE): "blue", id(GREEN): "green"}

# category -> the (shape, colour) that IS the class, and two discriminating
# negatives (each shares exactly one feature) that force a conjunctive rule.
CATS = {
    "redcircle":  {"pos": ("circle", RED),
                   "negtrain": [("square", RED), ("circle", BLUE)]},
    "bluesquare": {"pos": ("square", BLUE),
                   "negtrain": [("circle", BLUE), ("square", RED)]},
    "greentri":   {"pos": ("triangle", GREEN),
                   "negtrain": [("circle", GREEN), ("triangle", RED)]},
}
# held-out negatives: combinations that are NOT the category.
HELD_NEG = [("square", RED), ("circle", BLUE), ("triangle", GREEN), ("square", BLUE)]
SIZES = [58, 44, 70, 52, 64, 40]


def _draw(path, shape, color, size):
    img = np.full((300, 300, 3), 255, np.uint8)
    if shape == "circle":
        cv2.circle(img, (150, 150), size, color, -1)
    elif shape == "square":
        cv2.rectangle(img, (150 - size, 150 - size),
                      (150 + size, 150 + size), color, -1)
    else:  # triangle
        pts = np.array([[150, 150 - size], [150 - size, 150 + size],
                        [150 + size, 150 + size]], np.int32)
        cv2.fillPoly(img, [pts], color)
    cv2.imwrite(str(path), img)


def _yes_no(answer):
    a = (answer or "").strip().lower()
    if a.startswith("yes") or a.startswith("true"):
        return True
    if a.startswith("no") or a.startswith("false"):
        return False
    return None


async def main() -> int:
    STIM.mkdir(exist_ok=True)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.perception import vision
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        # The STORE forgets its own rules: it is what knows every table that
        # references one. The hand-rolled version here deleted the evidence and
        # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
        # table does not have -- leaving the rule standing with its evidence gone.
        from core.learning.rule_store import get_rule_store
        await get_rule_store().forget_domain('perceval')

        # SUBJECT NAMES ARE UNIQUE PER RUN. A concept-graph name is an identity,
        # and the graph outlives the run: a fixed scheme merges this run's
        # perceived features onto the previous run's subject. Measured on
        # 2026-09-17, a second experiment reusing this scheme left subjects
        # carrying two images' features at once (a red square that was also a
        # blue triangle), and this evaluation then reported 0.778 recall with
        # three hallucinations that were nothing to do with the substrate.
        RUN = uuid4().hex[:6]
        counter = [0]

        async def make_and_teach(shape, color, prefix):
            counter[0] += 1
            name = f"{prefix}{RUN}_{counter[0]}"
            path = STIM / f"{name}.png"
            _draw(path, shape, color, SIZES[counter[0] % len(SIZES)])
            d = vision.describe_image(str(path))
            regions = [r for r in d["regions"] if r["area_fraction"] <= 0.9]
            r = regions[0]
            feats = [r["color"], r["shape"], r["size"]]
            await coord.learning.learn_facts(
                [(name, "isa", f) for f in feats], domain="perceval")
            return name, {"drawn_shape": shape, "drawn_color": DRAWN_FAMILY[id(color)],
                          "perceived_color": r["color"], "perceived_shape": r["shape"]}

        fidelity = []
        induced_rules = {}
        tests = {}
        model_calls = [0]

        # Build stimuli, teach perceived features, induce, and collect held-out
        # test sets for each category.
        for base_cat, spec in CATS.items():
            cat = f"{base_cat}{RUN}"
            pos_shape, pos_color = spec["pos"]
            pos_names, neg_names = [], []
            for _ in range(2):
                nm, fid = await make_and_teach(pos_shape, pos_color, f"{cat}_p")
                pos_names.append(nm); fidelity.append(fid)
            for (ns, nc) in spec["negtrain"]:
                nm, fid = await make_and_teach(ns, nc, f"{cat}_ntr")
                neg_names.append(nm); fidelity.append(fid)

            result = await coord.learning.induce_category(
                cat, positives=pos_names, negatives=neg_names, domain="perceval")
            induced_rules[base_cat] = str(getattr(result, "rule", None))

            test_pos, test_neg = [], []
            for _ in range(3):
                nm, fid = await make_and_teach(pos_shape, pos_color, f"{cat}_tp")
                test_pos.append(nm); fidelity.append(fid)
            for (ns, nc) in HELD_NEG:
                if (ns, nc) == (pos_shape, pos_color):
                    continue
                nm, fid = await make_and_teach(ns, nc, f"{cat}_tn")
                test_neg.append(nm); fidelity.append(fid)
            tests[base_cat] = {"pos": test_pos, "neg": test_neg}

        async def ask(subject, base_cat):
            from core.memory import Origin
            cat = f"{base_cat}{RUN}"
            res = await coord.reason_about(f"is {subject} a {cat}?", origin=Origin.own("PERCEIVE-EVAL"))
            md = dict(getattr(res, "metadata", {}) or {})
            model_calls[0] += int(md.get("model_calls") or 0)
            return _yes_no(getattr(res, "answer", ""))

        async def measure():
            out = {}
            for cat, t in tests.items():
                named = 0
                for s in t["pos"]:
                    if (await ask(s, cat)) is True:
                        named += 1
                hallucinated = abstained = 0
                for s in t["neg"]:
                    if (await ask(s, cat)) is True:
                        hallucinated += 1
                    else:
                        abstained += 1
                out[cat] = {
                    "recall": round(named / len(t["pos"]), 3),
                    "abstention": round(abstained / len(t["neg"]), 3),
                    "hallucinations": hallucinated,
                    "n_pos": len(t["pos"]), "n_neg": len(t["neg"])}
            return out

        # PHASE 1: with the learned rules present.
        per_cat = await measure()

        # PHASE 2 (ABLATION): remove the learned naming rules and measure again.
        # If the capability is carried by what was learned, naming vanishes into
        # honest abstention -- not into wrong guesses.
        # The STORE forgets its own rules: it is what knows every table that
        # references one. The hand-rolled version here deleted the evidence and
        # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
        # table does not have -- leaving the rule standing with its evidence gone.
        from core.learning.rule_store import get_rule_store
        await get_rule_store().forget_domain('perceval')
        per_cat_ablated = await measure()
        model_calls = model_calls[0]

    shape_ok = sum(1 for f in fidelity if f["perceived_shape"] == f["drawn_shape"])
    color_ok = sum(1 for f in fidelity
                   if f["drawn_color"] in f["perceived_color"])
    n = len(fidelity)
    def _mean(d, key):
        return round(sum(c[key] for c in d.values()) / len(d), 3)

    overall = {
        "perception_shape_accuracy": round(shape_ok / n, 3),
        "perception_color_accuracy": round(color_ok / n, 3),
        "mean_naming_recall": _mean(per_cat, "recall"),
        "mean_abstention": _mean(per_cat, "abstention"),
        "total_hallucinations": sum(c["hallucinations"] for c in per_cat.values()),
        "ablated_mean_naming_recall": _mean(per_cat_ablated, "recall"),
        "ablated_mean_abstention": _mean(per_cat_ablated, "abstention"),
        "ablated_total_hallucinations": sum(c["hallucinations"] for c in per_cat_ablated.values()),
        "model_calls": model_calls,
        "images": n,
    }
    manifest = {
        "experiment": "PERCEIVE-EVAL", "run_at": datetime.now(timezone.utc).isoformat(),
        "categories": list(CATS), "induced_rules": induced_rules,
        "per_category": per_cat, "per_category_ablated": per_cat_ablated,
        "overall": overall}
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps({"induced_rules": induced_rules, "per_category": per_cat,
                      "per_category_ablated": per_cat_ablated,
                      "overall": overall}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
