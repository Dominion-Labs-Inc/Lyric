#!/usr/bin/env python3
"""PERCEIVE-AMBIG-02 - closing an undetermined induction by asking for a case.

AMBIG-01 measured what naming does when the examples leave more than one
hypothesis standing. This measures the other half: how that ambiguity is closed,
and whether the learner's own stated request closes it faster than more data.

An undetermined induction reports the case that would eliminate one of its
hypotheses: "an instance that is small but not circle and vivid_red is accepted
by one hypothesis and refused by the other". One such case eliminates one
hypothesis, so the protocol is a loop: induce, read the request, supply exactly
that case, induce again, until a single rule stands or the round cap is reached.

  TARGETED  each round supplies the case the request names.
  RANDOM    each round supplies a randomly drawn stimulus instead. Same cap,
            same labelling rule, same starting examples.

Every stimulus is drawn and then PERCEIVED before it is used, and is accepted
only if perception reports the features the round requires. A size band is a
property of perceived area, and a circle, a square and a triangle of one radius
do not share it, so nothing here is assumed from a radius. Where a required
case cannot be built from the stimulus space, the case is recorded as
unbuildable and excluded, never substituted.

Every induction is the learning authority's own `induce_category`.

    PYTHONPATH="$PWD" LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-AMBIG-02/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, random, sys, time
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"

import numpy as np
import cv2

DOMAIN = "ambig02"
REPEATS = 2
ROUND_CAP = 4
COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 170, 0),
           "yellow": (0, 215, 255), "violet": (160, 32, 160),
           "orange": (0, 140, 255), "cyan": (200, 200, 0)}
SHAPES = ("circle", "square", "triangle")
CATS = [("circle", "red"), ("square", "blue"), ("triangle", "green"),
        ("square", "yellow"), ("circle", "violet"), ("triangle", "orange"),
        ("square", "cyan"), ("triangle", "red")]
RADII = tuple(range(16, 146, 6))


def draw(path, shape, colour, radius):
    img = np.full((300, 300, 3), 255, np.uint8)
    bgr = COLOURS[colour]
    if shape == "circle":
        cv2.circle(img, (150, 150), radius, bgr, -1)
    else:
        unit = (np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
                if shape == "square" else np.array([[0, -1], [-1, 1], [1, 1]], np.float32))
        cv2.fillPoly(img, [(unit * radius + [150, 150]).astype(np.int32)], bgr)
    cv2.imwrite(str(path), img)


async def main() -> int:
    STIM.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    rng = random.Random(20260917)
    RUN = uuid4().hex[:6]
    cases, counter = [], [0]

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.perception import vision
        from core.database import get_database_manager
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager(); await db.initialize()

        async def clean():
            # The STORE forgets its own rules: it is what knows every table that
            # references one. The hand-rolled version here deleted the evidence and
            # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
            # table does not have -- leaving the rule standing with its evidence gone.
            from core.learning.rule_store import get_rule_store
            await get_rule_store().forget_domain(DOMAIN)

        def perceive(path):
            regions = [r for r in vision.describe_image(str(path))["regions"]
                       if r["area_fraction"] <= 0.9]
            return (regions[0]["color"], regions[0]["shape"], regions[0]["size"]) if regions else None

        # ── the stimulus space, perceived once and used by its perceived features
        catalogue = []          # [(shape, colour, radius, frozenset(features))]
        for shape in SHAPES:
            for colour in COLOURS:
                for radius in RADII:
                    path = STIM / f"cat_{RUN}_{shape}_{colour}_{radius}.png"
                    draw(path, shape, colour, radius)
                    feats = perceive(path)
                    if feats:
                        catalogue.append((shape, colour, radius, frozenset(feats), path))

        async def teach(entry):
            counter[0] += 1
            shape, colour, radius, feats, path = entry
            name = f"a2_{RUN}_{counter[0]}"
            target = STIM / f"{name}.png"
            target.write_bytes(path.read_bytes())
            seen = perceive(target)
            if frozenset(seen) != feats:
                raise RuntimeError(f"{name}: catalogued {sorted(feats)}, perceived {sorted(seen)}")
            await coord.learning.learn_facts(
                [(name, "isa", f) for f in seen], domain=DOMAIN)
            return name

        def body(rule):
            return frozenset(f.predicate for f in rule.preconditions)

        def separating_entry(candidates):
            """A stimulus one hypothesis accepts and another refuses.

            This is the case `deciding_request` names, taken from the same
            hypotheses the request is computed from, and required to be one
            perception actually reports.
            """
            bodies = [body(c) for c in candidates]
            for i, first in enumerate(bodies):
                for second in bodies[i + 1:]:
                    for accept, refuse in ((first, second), (second, first)):
                        if refuse <= accept:
                            continue
                        for entry in catalogue:
                            if accept <= entry[3] and not refuse <= entry[3]:
                                return entry
            return None

        for repeat in range(REPEATS):
            for shape, colour in CATS:
                record = {"category": f"{colour} {shape}", "repeat": repeat}
                cases.append(record)
                await clean()
                cat = f"a{RUN}{repeat}{shape[:2]}{colour[:2]}"
                other_shape = next(s for s in SHAPES if s != shape)
                other_colour = next(c for c in COLOURS if c != colour)

                def pick(want_shape, want_colour, want_band):
                    for entry in catalogue:
                        if (entry[0] == want_shape and entry[1] == want_colour
                                and want_band in entry[3]):
                            return entry
                    return None

                # accidental arm: both positives small, counter-examples not
                wanted = {"positive": pick(shape, colour, "small"),
                          "counter-colour": pick(shape, other_colour, "medium"),
                          "counter-shape": pick(other_shape, colour, "medium")}
                if any(e is None for e in wanted.values()):
                    record.update(built=False,
                                  unbuildable=[k for k, e in wanted.items() if e is None])
                    continue
                base_pos = [await teach(wanted["positive"]) for _ in range(2)]
                base_neg = [await teach(wanted["counter-colour"]),
                            await teach(wanted["counter-shape"])]

                def is_member(entry):
                    return entry[0] == shape and entry[1] == colour

                async def rounds(chooser):
                    """Induce, take an example from `chooser`, induce again."""
                    pos, neg, log = list(base_pos), list(base_neg), []
                    result = await coord.learning.induce_category(
                        cat, positives=pos, negatives=neg, domain=DOMAIN)
                    log.append({"round": 0, "hypotheses": [str(c) for c in result.candidates],
                                "determined": result.rule is not None,
                                "request": result.deciding_request})
                    for n in range(1, ROUND_CAP + 1):
                        if result.rule is not None:
                            break
                        entry = chooser(result)
                        if entry is None:
                            log.append({"round": n, "supplied": None})
                            break
                        name = await teach(entry)
                        (pos if is_member(entry) else neg).append(name)
                        result = await coord.learning.induce_category(
                            cat, positives=pos, negatives=neg, domain=DOMAIN)
                        log.append({
                            "round": n,
                            "supplied": {"shape": entry[0], "colour": entry[1],
                                         "perceived": sorted(entry[3]),
                                         "labelled": "positive" if is_member(entry) else "negative"},
                            "hypotheses": [str(c) for c in result.candidates],
                            "determined": result.rule is not None,
                            "request": result.deciding_request})
                    determined_at = next((e["round"] for e in log
                                          if e.get("determined")), None)
                    return {"log": log, "determined_at": determined_at,
                            "rule": str(result.rule) if result.rule else None}

                targeted = await rounds(lambda r: separating_entry(r.candidates))
                await clean()
                base_pos = [await teach(wanted["positive"]) for _ in range(2)]
                base_neg = [await teach(wanted["counter-colour"]),
                            await teach(wanted["counter-shape"])]
                random_run = await rounds(lambda r: rng.choice(catalogue))
                record.update(built=True,
                              undetermined=targeted["log"][0]["determined"] is False,
                              request=targeted["log"][0]["request"],
                              targeted=targeted, random=random_run)
        await clean()

    built = [c for c in cases if c.get("built")]
    undet = [c for c in built if c.get("undetermined")]
    def closed(kind):
        return [c for c in undet if c[kind]["determined_at"] is not None]
    def mean_rounds(kind):
        rounds = [c[kind]["determined_at"] for c in closed(kind)]
        return round(sum(rounds) / len(rounds), 2) if rounds else None
    report = {
        "experiment": "PERCEIVE-AMBIG-02",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "round_cap": ROUND_CAP,
        "cases": cases,
        "summary": {
            "inductions_attempted": len(cases),
            "inductions_built": len(built),
            "unbuildable": [c for c in cases if not c.get("built")],
            "undetermined_at_start": len(undet),
            "targeted_closed": len(closed("targeted")),
            "targeted_mean_rounds": mean_rounds("targeted"),
            "random_closed": len(closed("random")),
            "random_mean_rounds": mean_rounds("random"),
            "images": counter[0],
            "catalogue": len(catalogue),
            "wall_clock_s": round(time.perf_counter() - t0, 1),
        },
    }
    (HERE / "manifest.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["summary"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
