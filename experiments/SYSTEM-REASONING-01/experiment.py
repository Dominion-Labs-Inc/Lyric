#!/usr/bin/env python3
"""SYSTEM-REASONING-01 — the reasoning faculty, alone, on the live substrate.

One authority (`NeuralSymbolicBridge`, reached through `get_neural_bridge`),
entered the way the substrate enters it (`coord.reason_about`). It answers what
it holds, refuses what it does not, and calls no model. Then: is every public
method of the authority reached by something, and is any a stub?

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-REASONING-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, outcome, shutdown  # noqa: E402

EV = RunRecord(
    "SYSTEM-REASONING-01",
    claim=("The reasoning faculty is one authority, answers from what the substrate "
           "holds without a model, refuses what it cannot ground, and every public "
           "method of it is reached by something in core."),
    hypothesis=("If a second bridge existed, or a question about nothing it holds came "
                "back with an answer, or a public method had no caller, this would show it."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def _md(r):
    return dict(getattr(r, "metadata", {}) or {})


async def main() -> int:
    from core.memory import Origin
    system, coord = await boot()
    try:
        from core.reasoning.neural_bridge import get_neural_bridge
        bridge = get_neural_bridge()

        print("\n== A. One authority, and it is called ==")
        authority_audit(EV, check, system="reasoning", cls="NeuralSymbolicBridge",
                        path="core/reasoning/neural_bridge.py",
                        held=getattr(coord, "neural_bridge", None), reached=bridge)

        print("\n== B. It answers what the substrate holds ==")
        r = await coord.reason_about("is a robin a bird", origin=Origin.own("SYSTEM-REASONING-01"))
        md = _md(r)
        answer = str(getattr(r, "answer", "") or "")
        check("a held isa question is answered in the affirmative",
              answer.lower().startswith("yes") or "robin isa" in answer.lower(),
              f"answer={answer[:80]!r} confidence={getattr(r, 'confidence', None)} "
              f"mode={getattr(r, 'mode_used', None)}")
        check("the answer came from the substrate, not a model",
              (md.get("model_calls") or 0) == 0,
              f"model_calls={md.get('model_calls')} route={md.get('route')}")
        EV.metric("held_question_confidence", round(float(getattr(r, "confidence", 0.0) or 0.0), 3))

        print("\n== C. It refuses what it cannot ground ==")
        r2 = await coord.reason_about("is a hammer a bird", origin=Origin.own("SYSTEM-REASONING-01"))
        a2 = str(getattr(r2, "answer", "") or "")
        check("a false isa is not affirmed",
              not a2.lower().startswith("yes"),
              f"answer={a2[:80]!r} reason={_md(r2).get('reason')}")
        r3 = await coord.reason_about("is a qzxflorp a blipnorp", origin=Origin.own("SYSTEM-REASONING-01"))
        a3 = str(getattr(r3, "answer", "") or "")
        check("a question about nothing it holds is refused, not invented",
              not a3.lower().startswith("yes") and (
                  _md(r3).get("reason") or not getattr(r3, "success", True)
                  or float(getattr(r3, "confidence", 0.0) or 0.0) < 0.5),
              f"answer={a3[:80]!r} reason={_md(r3).get('reason')} "
              f"confidence={getattr(r3, 'confidence', None)}")

        print("\n== D. It can account for itself ==")
        stats = await bridge.get_statistics()
        check("statistics are a dict with counts", isinstance(stats, dict) and bool(stats),
              f"keys={sorted(stats)[:8]}")
        d = bridge.reasoning_difficulty("deductive")
        check("a reasoning kind has a difficulty, declared or measured",
              isinstance(d, (int, float)) and d >= 1.0, f"deductive={d}")
    finally:
        await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-REASONING-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
