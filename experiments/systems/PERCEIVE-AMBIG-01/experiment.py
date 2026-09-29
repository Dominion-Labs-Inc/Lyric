#!/usr/bin/env python3
"""PERCEIVE-AMBIG-01 — what the substrate does when its examples do not decide.

Induction keeps every surviving hypothesis; a category whose examples share an
accident (two green triangles that are both small, against medium
counter-examples) leaves two rules standing. What happens next is the whole
question, and this measures it end to end THROUGH THE LIVE PATH: every name is
`coordinator.reason_about(...)`, which is the reasoning authority the rest of
the system uses, over rules recorded by the learning authority.

  A  AMBIGUITY AT SCALE   eight categories in two arms, repeated: an ACCIDENTAL
                          arm (positives share a size, counter-examples do not)
                          and a CLEAN arm (positives vary). How often are the
                          examples undetermined, and what does naming then do?
  B  THREE POLICIES        on identical data: FIRST-FIRE (name on any hypothesis,
                          the behaviour before this work), DETERMINED-ONLY
                          (record nothing when undetermined), and UNANIMITY (name
                          only what every hypothesis accepts -- what the
                          substrate now does live). Only UNANIMITY is the live
                          answer; the other two are computed from the same
                          recorded hypotheses, and are labelled as counterfactual.
  C  RESOLUTION            an undetermined induction states the case that would
                          decide it. Supplying THAT example is compared against
                          supplying random further examples: how many does each
                          need to reach a determined rule?

Domain `ambig01`, cleaned between conditions. Subject and category names are
unique per run: a concept-graph name is an identity, and reusing one merges this
run's features onto an earlier run's subject.

    PYTHONPATH="$PWD" LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-AMBIG-01/experiment.py
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

DOMAIN = "ambig01"
REPEATS = 2

COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 170, 0),
           "yellow": (0, 215, 255), "violet": (160, 32, 160),
           "orange": (0, 140, 255), "cyan": (200, 200, 0)}
SHAPES = ("circle", "square", "triangle")
#: radius by perceived size band (the faculty's own bands, measured)
RADIUS = {"small": 40, "medium": 58, "large": 95}

CATS = [("circle", "red"), ("square", "blue"), ("triangle", "green"),
        ("square", "yellow"), ("circle", "violet"), ("triangle", "orange"),
        ("square", "cyan"), ("triangle", "red")]


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
    return path


def yes_no(answer):
    a = (answer or "").strip().lower()
    if a.startswith("yes") or a.startswith("true"):
        return True
    if a.startswith("no") or a.startswith("false"):
        return False
    return None


async def main() -> int:
    STIM.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    rng = random.Random(20260917)
    RUN = uuid4().hex[:6]
    report = {"repeats": REPEATS, "conditions": [], "resolution": [],
              "policies": {p: {"named": 0, "correct_names": 0, "false_names": 0,
                               "abstained": 0, "missed": 0}
                           for p in ("first_fire", "determined_only", "unanimity_live")}}

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.perception import vision
        from core.database import get_database_manager
        from core.learning.rule_induction import (Fact, TrainingExample, applies,
                                                  predicate_name)
        from core.learning.rule_store import EpistemicStatus, get_rule_store
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager(); await db.initialize()
        store = get_rule_store()

        async def clean():
            # The STORE forgets its own rules: it is what knows every table that
            # references one. The hand-rolled version here deleted the evidence and
            # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
            # table does not have -- leaving the rule standing with its evidence gone.
            await store.forget_domain(DOMAIN)

        counter = [0]

        async def stim(shape, colour, band):
            counter[0] += 1
            name = f"amb_{RUN}_{counter[0]}"
            path = draw(STIM / f"{name}.png", shape, colour, RADIUS[band])
            region = [r for r in vision.describe_image(str(path))["regions"]
                      if r["area_fraction"] <= 0.9][0]
            feats = (region["color"], region["shape"], region["size"])
            await coord.learning.learn_facts(
                [(name, "isa", f) for f in feats], domain=DOMAIN)
            return name, feats

        async def ask(subject, cat):
            from core.memory import Origin
            res = await coord.reason_about(f"is {subject} a {cat}?", origin=Origin.own("PERCEIVE-AMBIG-01"))
            md = dict(getattr(res, "metadata", {}) or {})
            return yes_no(getattr(res, "answer", "")), md

        async def hypotheses(cat):
            head = predicate_name(cat)
            return [s for s in await store.load(domain_id=DOMAIN)
                    if s.status is not EpistemicStatus.REFUTED
                    and any(f.predicate == head for f in s.rule.effects.add)]

        def fires(stored, feats, cat):
            head = predicate_name(cat)
            ex = TrainingExample(before=tuple(Fact(predicate_name(f), ("x",)) for f in feats))
            goal = Fact(head, ("x",))
            return goal in {f for inst in applies(stored.rule, ex) for f in inst.add}

        def policy_names(rules, feats, cat, determined):
            """What each policy would answer for this instance."""
            firing = [r for r in rules if fires(r, feats, cat)]
            return {"first_fire": bool(firing),
                    "determined_only": bool(firing) and determined,
                    "unanimity": bool(firing) and len(firing) == len(rules)}

        # ── A / B. ambiguity at scale, three policies on identical data ────
        for repeat in range(REPEATS):
            for arm in ("accidental", "clean"):
                for shape, colour in CATS:
                    await clean()
                    cat = f"c{RUN}{repeat}{arm[0]}{shape[:2]}{colour[:2]}"
                    other_shape = next(s for s in SHAPES if s != shape)
                    other_colour = next(c for c in COLOURS if c != colour)
                    if arm == "accidental":       # both positives small, negatives medium
                        pos = [await stim(shape, colour, "small") for _ in range(2)]
                        negs = [await stim(shape, other_colour, "medium"),
                                await stim(other_shape, colour, "medium")]
                    else:                          # positives vary in size
                        pos = [await stim(shape, colour, "small"),
                               await stim(shape, colour, "large")]
                        negs = [await stim(shape, other_colour, "medium"),
                                await stim(other_shape, colour, "medium")]
                    result = await coord.learning.induce_category(
                        cat, positives=[p[0] for p in pos],
                        negatives=[n[0] for n in negs], domain=DOMAIN)
                    determined = result.rule is not None
                    rules = await hypotheses(cat)

                    # held-out: members of every size, and near-miss non-members
                    tests = []
                    for band in ("small", "medium", "large"):
                        tests.append((await stim(shape, colour, band), True))
                        tests.append((await stim(other_shape, colour, band), False))
                        tests.append((await stim(shape, other_colour, band), False))

                    per_instance = []
                    for (subject, feats), truth in tests:
                        verdict, md = await ask(subject, cat)
                        would = policy_names(rules, feats, cat, determined)
                        per_instance.append({
                            "features": list(feats), "is_member": truth,
                            "live_named": verdict is True,
                            "live_rule_status": md.get("rule_status"),
                            "would": would})
                        for policy, named in (("first_fire", would["first_fire"]),
                                              ("determined_only", would["determined_only"]),
                                              ("unanimity_live", verdict is True)):
                            slot = report["policies"][policy]
                            if named:
                                slot["named"] += 1
                                slot["correct_names" if truth else "false_names"] += 1
                            else:
                                slot["abstained"] += 1
                                if truth:
                                    slot["missed"] += 1

                    report["conditions"].append({
                        "repeat": repeat, "arm": arm, "category": f"{colour} {shape}",
                        "status": result.status.value,
                        "determined": determined,
                        "hypotheses": [str(r.rule) for r in rules],
                        "deciding_request": result.deciding_request,
                        "instances": per_instance})

                    # ── C. RESOLUTION, only where the examples did not decide ──
                    if determined or not result.deciding_request:
                        continue
                    # the requested case: accepted by one hypothesis, refused by
                    # another. Build it from the hypotheses themselves.
                    bodies = [sorted(f.predicate for f in r.rule.preconditions) for r in rules]
                    wanted = None
                    for i, b1 in enumerate(bodies):
                        for b2 in bodies[i + 1:]:
                            missing = [p for p in b2 if p not in b1]
                            if missing:
                                wanted = (b1, missing); break
                        if wanted: break
                    if not wanted:
                        continue
                    accept_body, _missing = wanted
                    # an instance satisfying accept_body, differing elsewhere
                    band = next((p for p in accept_body if p in RADIUS), "small")
                    a_shape = next((p for p in accept_body if p in SHAPES), None)
                    a_colour = next((p[len("vivid_"):] for p in accept_body
                                     if p.startswith("vivid_")), None)
                    d_shape = a_shape or next(s for s in SHAPES if s != shape)
                    d_colour = a_colour or next(c for c in COLOURS if c != colour)
                    deciding = await stim(d_shape, d_colour, band)
                    truth = (d_shape == shape and d_colour == colour)

                    targeted = await coord.learning.induce_category(
                        cat, positives=[p[0] for p in pos] + ([deciding[0]] if truth else []),
                        negatives=[n[0] for n in negs] + ([] if truth else [deciding[0]]),
                        domain=DOMAIN)

                    # baseline: random further examples, up to three
                    random_needed, rand_pos, rand_neg = None, [], []
                    for attempt in range(1, 4):
                        rs = rng.choice(SHAPES); rc = rng.choice(list(COLOURS))
                        rb = rng.choice(list(RADIUS))
                        extra = await stim(rs, rc, rb)
                        if rs == shape and rc == colour:
                            rand_pos.append(extra[0])
                        else:
                            rand_neg.append(extra[0])
                        trial = await coord.learning.induce_category(
                            cat, positives=[p[0] for p in pos] + rand_pos,
                            negatives=[n[0] for n in negs] + rand_neg, domain=DOMAIN)
                        if trial.rule is not None:
                            random_needed = attempt
                            break
                    report["resolution"].append({
                        "category": f"{colour} {shape}", "repeat": repeat,
                        "request": result.deciding_request,
                        "targeted_example": {"shape": d_shape, "colour": d_colour,
                                             "band": band, "labelled": "positive" if truth else "negative"},
                        "targeted_determined": targeted.rule is not None,
                        "targeted_rule": str(targeted.rule),
                        "random_examples_needed": random_needed})
        await clean()

    # ── summary ────────────────────────────────────────────────────────────
    conds = report["conditions"]
    by_arm = {}
    for arm in ("accidental", "clean"):
        rows = [c for c in conds if c["arm"] == arm]
        by_arm[arm] = {
            "categories": len(rows),
            "undetermined": sum(1 for c in rows if not c["determined"]),
            "mean_hypotheses": round(sum(len(c["hypotheses"]) for c in rows) / max(1, len(rows)), 2),
        }
    res = report["resolution"]
    report["summary"] = {
        "by_arm": by_arm,
        "policies": report["policies"],
        "resolution": {
            "undetermined_cases": len(res),
            "resolved_by_requested_example": sum(1 for r in res if r["targeted_determined"]),
            "random_resolved_within_3": sum(1 for r in res if r["random_examples_needed"]),
            "random_examples_needed_mean": (
                round(sum(r["random_examples_needed"] for r in res if r["random_examples_needed"])
                      / max(1, sum(1 for r in res if r["random_examples_needed"])), 2)),
        },
        "images": 0,
        "wall_clock_s": round(time.perf_counter() - t0, 1),
    }
    report["summary"]["images"] = sum(len(c["instances"]) for c in conds) + 4 * len(conds)
    report["run_at"] = datetime.now(timezone.utc).isoformat()
    (HERE / "manifest.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["summary"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
