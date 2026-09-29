#!/usr/bin/env python3
"""Does `see()` now admit each blob as an individual with its own features?

Then: taught a category by EXAMPLE over those blobs, can the substrate name a
blob it has never seen? And taught the same category in WORDS, can it?
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, sys
from uuid import uuid4
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent
import numpy as np, cv2

COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0)}


def draw(path, shape, colour, radius=58):
    img = np.full((300, 300, 3), 255, np.uint8)
    if shape == "circle":
        cv2.circle(img, (150, 150), radius, COLOURS[colour], -1)
    else:
        pts = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32) * radius + [150, 150]
        cv2.fillPoly(img, [pts.astype(np.int32)], COLOURS[colour])
    cv2.imwrite(str(path), img)


async def main() -> int:
    from core.memory import Origin
    lines = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.database import get_database_manager
        from core.reasoning.concept_graph_reasoning import instance_predicates
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager(); await db.initialize()
        RUN = uuid4().hex[:6]

        async def seen(shape, colour, tag):
            name = f"pic_{RUN}_{tag}"
            path = HERE / f"{name}.png"
            draw(path, shape, colour)
            await coord.see(str(path), source=name, domain=f"vis{RUN}", actor_identity=None)
            rows = await db.execute_query(
                "SELECT cr.target_surface FROM unified.concept_relations cr "
                "JOIN unified.concepts c ON cr.source_concept_id = c.concept_id "
                "WHERE c.name = $1 AND cr.relation = 'contains'", (name,),
                fetch_all=True) or []
            blob = str(rows[0]["target_surface"]) if rows else ""
            feats = sorted(await instance_predicates(db, blob)) if blob else []
            return blob, feats

        # 1. does a blob exist as an individual, with its features?
        b1, f1 = await seen("circle", "red", "p1")
        lines.append(f"blob individual: {b1}\n  its own features: {f1}")

        # 2. taught by EXAMPLE over blobs admitted by sight alone
        b2, _ = await seen("circle", "red", "p2")
        n1, _ = await seen("square", "red", "n1")
        n2, _ = await seen("circle", "blue", "n2")
        held, _ = await seen("circle", "red", "held")
        cat = f"sunspot{RUN}"
        res = await coord.learning.induce_category(
            cat, positives=[b1, b2], negatives=[n1, n2], domain=f"vis{RUN}")
        lines.append(f"induced from blobs: {res.status.value} rule={res.rule}")
        ans = await coord.reason_about(f"is {held} a {cat}?", origin=Origin.own("TOLD-SEEN-01"))
        lines.append(f"named the held-out blob: {(ans.answer or '')[:40]!r} "
                     f"({dict(getattr(ans, 'metadata', {}) or {}).get('rule_status')})")

        # 3. taught in WORDS, asked about a blob it saw
        told_cat = f"sunspot{RUN}w"
        told = await coord.conversation("toldseen").teach(
            f"if something is a circle and it is vivid red then it is a {told_cat}")
        lines.append(f"told: {[ (a.stored, a.detail) for a in told ]}")
        ans2 = await coord.reason_about(f"is {held} a {told_cat}?", origin=Origin.own("TOLD-SEEN-01"))
        lines.append(f"named from words: {(ans2.answer or '')[:40]!r}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
