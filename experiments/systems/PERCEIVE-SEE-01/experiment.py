#!/usr/bin/env python3
"""PERCEIVE-SEE-01 - the whole loop through the faculty, from pixels only.

The earlier perception studies taught the substrate the features a blob was
measured to have, which measures learning and naming but hands the features over
directly. This runs the same loop with nothing handed over: every fact the
substrate holds about a thing arrives through `coordinator.see`, the one entry
point for sight, which perceives an image and admits each object-like region as
its own individual carrying its own measured features.

  A  ADMISSION   an image is seen; does a thing exist in what was admitted, with
                 the colour, shape and size the faculty measured off the pixels?
  B  NAMING      a category is induced from blobs admitted by sight alone, and
                 held-out blobs are named or declined through the reasoner.
  C  ABSTENTION  blobs of a category never taught must be declined.

    PYTHONPATH="$PWD" TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-SEE-01/experiment.py
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

import numpy as np, cv2

COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 170, 0),
           "yellow": (0, 215, 255), "violet": (160, 32, 160)}
CATS = [("circle", "red"), ("square", "blue"), ("triangle", "green")]
SIZES = (46, 58, 72, 88)


def draw(path, shape, colour, radius):
    img = np.full((300, 300, 3), 255, np.uint8)
    bgr = COLOURS[colour]
    if shape == "circle":
        cv2.circle(img, (150, 150), radius, bgr, -1)
    else:
        unit = (np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
                if shape == "square" else np.array([[0, -1], [-1, 1], [1, 1]], np.float32))
        cv2.fillPoly(img, [(unit * radius + [150, 150]).astype(np.int32)], bgr)
    if not cv2.imwrite(str(path), img):
        raise RuntimeError(f"could not write the stimulus to {path}")


def yes_no(answer):
    a = (answer or "").strip().lower()
    return True if a.startswith("yes") else False if a.startswith("no") else None


async def main() -> int:
    from core.memory import Origin
    STIM.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    RUN = uuid4().hex[:6]
    DOMAIN = f"see{RUN}"
    report = {"experiment": "PERCEIVE-SEE-01", "admission": [], "categories": {}}
    counter = [0]

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.perception import vision
        from core.database import get_database_manager
        from core.reasoning.concept_graph_reasoning import instance_predicates
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager(); await db.initialize()

        async def blob_of(image_name):
            rows = await db.execute_query(
                "SELECT cr.target_surface FROM unified.concept_relations cr "
                "JOIN unified.concepts c ON cr.source_concept_id = c.concept_id "
                "WHERE c.name = $1 AND cr.relation = 'contains'",
                (image_name,), fetch_all=True) or []
            return str(rows[0]["target_surface"]) if rows else ""

        async def see(shape, colour, radius):
            """Draw it, show it to the faculty, and report what was admitted."""
            counter[0] += 1
            name = f"see_{RUN}_{counter[0]}"
            path = STIM / f"{name}.png"
            draw(path, shape, colour, radius)
            drawn = vision.describe_image(str(path))
            measured = [r for r in drawn["regions"] if r["area_fraction"] <= 0.9]
            percept = await coord.see(str(path), source=name, domain=DOMAIN, actor_identity=None)
            # THE PERCEPT NAMES ITSELF FROM THE IMAGE'S CONTENT, not from the
            # label handed in: `name` becomes `<name>x<digest>`, because a
            # caller's label is not an identity. Looking the concept up by the
            # bare label found nothing, so every `blob` was "" and
            # `induce_category` refused with "example '' has no feature facts".
            blob = await blob_of(getattr(percept, "source", None) or name)
            feats = sorted(await instance_predicates(db, blob)) if blob else []
            report["admission"].append({
                "image": name, "drawn": [shape, colour],
                "measured": [measured[0]["color"], measured[0]["shape"],
                             measured[0]["size"]] if measured else [],
                "blob": blob, "blob_holds": feats,
            })
            return blob

        for shape, colour in CATS:
            cat = f"cat{RUN}{shape[:2]}{colour[:2]}"
            other_shape = next(s for s, _ in CATS if s != shape)
            other_colour = next(c for _, c in CATS if c != colour)
            pos = [await see(shape, colour, SIZES[i % len(SIZES)]) for i in range(2)]
            negs = [await see(shape, other_colour, SIZES[2]),
                    await see(other_shape, colour, SIZES[1])]
            result = await coord.learning.induce_category(
                cat, positives=pos, negatives=negs, domain=DOMAIN)
            held_pos = [await see(shape, colour, SIZES[i]) for i in (0, 2, 3)]
            held_neg = [await see(other_shape, colour, SIZES[3]),
                        await see(shape, other_colour, SIZES[0]),
                        await see(other_shape, other_colour, SIZES[2])]
            named, declined = 0, 0
            for blob in held_pos:
                res = await coord.reason_about(f"is {blob} a {cat}?", origin=Origin.own("PERCEIVE-SEE-01"))
                named += int(yes_no(getattr(res, "answer", "")) is True)
            false_namings = 0
            for blob in held_neg:
                res = await coord.reason_about(f"is {blob} a {cat}?", origin=Origin.own("PERCEIVE-SEE-01"))
                verdict = yes_no(getattr(res, "answer", ""))
                declined += int(verdict is not True)
                false_namings += int(verdict is True)
            report["categories"][f"{colour} {shape}"] = {
                "rule": str(result.rule) if result.rule else None,
                "status": result.status.value,
                "recall": round(named / len(held_pos), 3),
                "abstention": round(declined / len(held_neg), 3),
                "false_namings": false_namings,
            }

        # everything the substrate holds about a thing came through sight
        # The STORE forgets its own rules: it is what knows every table that
        # references one. The hand-rolled version here deleted the evidence and
        # then failed on `rule_identity_aliases WHERE rule_id` -- a column that
        # table does not have -- leaving the rule standing with its evidence gone.
        from core.learning.rule_store import get_rule_store
        await get_rule_store().forget_domain(DOMAIN)

    adm = report["admission"]
    exact = sum(1 for a in adm if a["measured"] and set(a["measured"]) <= set(a["blob_holds"]))
    cats = report["categories"]
    report["summary"] = {
        "images_seen": len(adm),
        "blobs_admitted": sum(1 for a in adm if a["blob"]),
        "blobs_holding_every_measured_feature": exact,
        "categories": len(cats),
        "mean_recall": round(sum(c["recall"] for c in cats.values()) / max(1, len(cats)), 3),
        "mean_abstention": round(sum(c["abstention"] for c in cats.values()) / max(1, len(cats)), 3),
        "false_namings": sum(c["false_namings"] for c in cats.values()),
        "wall_clock_s": round(time.perf_counter() - t0, 1),
    }
    report["run_at"] = datetime.now(timezone.utc).isoformat()
    (HERE / "manifest.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report["summary"], indent=2), flush=True)
    print(json.dumps(cats, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
