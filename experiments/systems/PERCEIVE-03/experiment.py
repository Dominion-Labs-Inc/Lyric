#!/usr/bin/env python3
"""PERCEIVE-03 — the substrate LEARNS to name what it sees, by its own induction.

The full loop, end to end, with no model:
  1. real images are perceived (the classical describer reads their real pixels),
  2. each blob's perceived features (colour, shape, size) are taught as facts,
  3. a few are LABELLED, and the substrate INDUCES a classification rule from them
     (anti-unification over the labelled cases -- red & circular -> stopsign),
  4. the rule is persisted to the one induced-rule authority, and
  5. the substrate NAMES a held-out perceived blob by APPLYING that rule through
     its ordinary reasoning entry point -- and ABSTAINS on a blob whose category
     it never learned, rather than guessing.

Nothing is told to the reasoner but the question. The rule is not taught; it is
learned from examples. The generated images are real image files with real
pixels, genuinely perceived.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-03/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, re, sys
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"

import numpy as np
import cv2

RED, BLUE = (0, 0, 255), (255, 0, 0)   # BGR: pure red, pure blue

# name -> (shape, colour, radius/half-size). A red circle is the target class.
# The negatives are DISCRIMINATING: a red square (shares colour) refutes
# "red -> stopsign", a blue circle (shares shape) refutes "circle -> stopsign",
# so the only rule that survives is the conjunction red & circle -> stopsign.
# Held-out redc (a NEW red circle) and blusq (a NEW blue square) are never labelled.
STIMULI = {
    "reda": ("circle", RED, 60), "redb": ("circle", RED, 45),
    "redc": ("circle", RED, 75),                       # held-out positive
    "redsq": ("square", RED, 55),                      # negative: red but square
    "blucirc": ("circle", BLUE, 55),                   # negative: circle but blue
    "blusq": ("square", BLUE, 50),                     # held-out negative
}


def _draw(path, shape, color, size):
    img = np.full((300, 300, 3), 255, np.uint8)
    if shape == "circle":
        cv2.circle(img, (150, 150), size, color, -1)
    else:
        cv2.rectangle(img, (150 - size, 150 - size),
                      (150 + size, 150 + size), color, -1)
    cv2.imwrite(str(path), img)


def _yes_no(answer):
    a = (answer or "").strip().lower()
    if a.startswith("yes") or a.startswith("true"):
        return True
    if a.startswith("no") or a.startswith("false"):
        return False
    return None   # refused / unknown / unsupported


async def main() -> int:
    STIM.mkdir(exist_ok=True)
    for name, (shape, color, size) in STIMULI.items():
        _draw(STIM / f"{name}.png", shape, color, size)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.perception import vision
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        # Clean slate: remove any perception classification rules from prior runs,
        # so the store state is exactly what THIS run induces (reproducible).
        # The STORE forgets its own rules: it is what knows every table that
        # references one. The hand-rolled version here deleted the evidence and
        # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
        # table does not have -- leaving the rule standing with its evidence gone.
        from core.learning.rule_store import get_rule_store
        await get_rule_store().forget_domain('perception')

    # 1-2. perceive each image and teach its blob's real features as facts.
    RUN = uuid4().hex[:6]          # subject names are identities; see PERCEIVE-EVAL
    sid = lambda n: f"{n}_{RUN}"
    perceived = {}
    for name in STIMULI:
        d = vision.describe_image(str(STIM / f"{name}.png"))
        regions = [r for r in d["regions"] if r["area_fraction"] <= 0.9]
        r = regions[0]
        feats = [r["color"], r["shape"], r["size"]]
        perceived[name] = feats
        await coord.learning.learn_facts(
            [(sid(name), "isa", f) for f in feats], domain="perception")

    print("=== perceived features (from real pixels) ===", flush=True)
    for name, feats in perceived.items():
        print(f"  {name:7} {STIMULI[name][0]:7} -> {feats}", flush=True)

    # 3-4. LABEL a few and induce the naming rule (red circles are 'stopsign').
    result = await coord.learning.induce_category(
        f"stopsign{RUN}", positives=[sid("reda"), sid("redb")],
        negatives=[sid("redsq"), sid("blucirc")], domain="perception")
    rule = getattr(result, "rule", None)
    print("\n=== induced from labeled examples (reda, redb ; not redsq, blucirc) ===", flush=True)
    print(f"  status: {result.status}", flush=True)
    print(f"  rule:   {rule}", flush=True)

    # 5. NAME a held-out perceived blob, and ABSTAIN on an unlearned one -- via
    #    the ordinary reasoning entry point, question only.
    async def ask(subject):
        res = await coord.reason_about(f"is {sid(subject)} a stopsign{RUN}?")
        md = dict(getattr(res, "metadata", {}) or {})
        return {"answer": str(getattr(res, "answer", "") or ""),
                "verdict": _yes_no(getattr(res, "answer", "")),
                "confidence": round(float(getattr(res, "confidence", 0) or 0), 3),
                "route": md.get("route"), "reason": md.get("reason"),
                "rule_status": md.get("rule_status"),
                "steps": list(getattr(res, "reasoning_steps", []) or [])}

    red_heldout = await ask("redc")     # a NEW red circle -> should be named
    blue_heldout = await ask("blusq")   # a NEW blue square -> should abstain

    print("\n=== naming held-out blobs (no answer given) ===", flush=True)
    for label, subj, r in (("held-out RED circle", "redc", red_heldout),
                           ("held-out BLUE square", "blusq", blue_heldout)):
        print(f"  {label} ({subj}): {r['answer']!r}", flush=True)
        print(f"      route={r['route']} reason={r['reason']} "
              f"rule={r['rule_status']} conf={r['confidence']}", flush=True)
        for s in r["steps"]:
            print(f"        - {s}", flush=True)

    checks = {
        "rule_was_induced": bool(rule is not None),
        "named_the_held_out_red_circle": red_heldout["verdict"] is True,
        # reason_about rewrites metadata["route"]; the durable signature that the
        # answer came from the induced-rule solver is the rule_status it carries.
        "naming_was_via_induced_rule": red_heldout["rule_status"] in
            ("candidate", "supported", "validated"),
        "abstained_on_unlearned_blue_square": blue_heldout["verdict"] is None,
        "did_not_hallucinate_on_blue": blue_heldout["verdict"] is not True,
    }
    summary = {"checks": checks, "all_pass": all(checks.values()),
               "induced_rule": str(rule), "perceived": perceived}
    manifest = {
        "experiment": "PERCEIVE-03",
        "purpose": "perceive -> teach features -> induce naming rule -> name held-out blob / abstain",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "perceived": perceived,
        "induced_rule": str(rule),
        "held_out_red": red_heldout, "held_out_blue": blue_heldout,
        "summary": summary,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("\n=== summary ===", flush=True)
    print(json.dumps(checks, indent=2), flush=True)
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
