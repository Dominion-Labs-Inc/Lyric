#!/usr/bin/env python3
"""Probe: can the substrate be TOLD what a thing is, and then SEE one?

Structure Before Meaning, section 5, claims a thing seen and a thing told are
the same kind of knowledge, so a category taught in words should be nameable by
sight afterwards. This probe finds out which sentence forms read, and whether a
perceived blob is then named through the told rule. It reports; it concludes
nothing on its own.
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

DOMAIN = "toldseen01"
SENTENCES = [
    "if something is a circle and it is vivid red then it is a {cat}",
    "if a thing is a circle then the thing is a {cat}",
    "every circle that is vivid red is a {cat}",
    "a {cat} is a circle that is vivid red",
    "if X is a circle and X is vivid_red then X is a {cat}",
]


async def main() -> int:
    from core.memory import Origin
    out = []
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.perception import vision
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator

        RUN = uuid4().hex[:6]
        img = np.full((300, 300, 3), 255, np.uint8)
        cv2.circle(img, (150, 150), 58, (0, 0, 255), -1)
        path = HERE / f"probe_{RUN}.png"
        cv2.imwrite(str(path), img)
        region = [r for r in vision.describe_image(str(path))["regions"]
                  if r["area_fraction"] <= 0.9][0]
        feats = (region["color"], region["shape"], region["size"])

        for i, template in enumerate(SENTENCES):
            cat = f"sunspot{RUN}{i}"
            subject = f"seen_{RUN}_{i}"
            await coord.learning.learn_facts(
                [(subject, "isa", f) for f in feats], domain=DOMAIN)
            sentence = template.format(cat=cat)
            try:
                acquired = await coord.conversation("toldseen").teach(sentence)
                told = [(a.stored, a.description, a.detail) for a in acquired]
            except Exception as e:
                told = [("EXC", type(e).__name__, str(e)[:120])]
            question = f"is {subject} a {cat}?"
            try:
                res = await coord.reason_about(question, origin=Origin.own("TOLD-SEEN-01"))
                answer = (getattr(res, "answer", "") or "")[:80]
                md = dict(getattr(res, "metadata", {}) or {})
                route = md.get("route") or md.get("solver") or md.get("reason")
            except Exception as e:
                answer, route = f"EXC {type(e).__name__}", str(e)[:100]
            try:
                u = await coord.conversation("toldseen").understand(question,
                                                                    look_up=False)
                spoken = (getattr(u, "reply", None) or getattr(u, "text", None)
                          or str(u))[:160]
            except Exception as e:
                spoken = f"EXC {type(e).__name__}: {str(e)[:100]}"
            out.append((sentence, feats, told, answer, route, spoken))
            continue

    print("perceived features:", out[0][1] if out else None)
    for sentence, _feats, told, answer, route, spoken in out:
        print("\nSENTENCE:", sentence)
        print("  told   :", told)
        print("  reasoner:", repr(answer), "|", route)
        print("  spoken  :", repr(spoken))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
