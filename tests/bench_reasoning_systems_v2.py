#!/usr/bin/env python3
"""Reasoning benchmark — model-free, through the substrate's own entry point.

Every case runs through `AutonomousCoordinator.reason_about(question,
{premises, rules})` — the substrate's reasoning entry point, which delegates to
the NeuralSymbolicBridge in its default symbolic mode (ZERO model calls). There
is no VLM to load and no legacy engine to initialise.

WHAT WAS WRONG WITH THE OLD SUITE (why this is a rewrite, not an edit):
  * it gated every test on loading a 32GB VLM — backwards for a substrate that
    is model-free by construction;
  * it pointed at `abstract_reasoning_engine` / `advanced_proof_engine`, which
    return `success=False` / `proved=False` on the classic syllogism and the
    identity axiom — dead ends, not the live path;
  * every assertion was `result is not None`, so it printed "PASSED" on engines
    that derived nothing. A benchmark that passes on a return value existing
    measures nothing.

This scores on the VERDICT BEING CORRECT. Ground truth is the logic, not the
substrate's mood: Socrates IS mortal, a salmon is NOT a bird, not every animal
is a robin, and "2 + 2" is a known gap the substrate must NOT fabricate a
verified answer for. A case the substrate gets wrong is reported as FAIL — the
point of the harness is to tell the truth about what reasons and what does not.

Run:
    PYTHONPATH="$PWD" ./venv_torin/bin/python3 tests/bench_reasoning_systems_v2.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# The three verdicts a query can settle to. UNDECIDED is first-class and
# honest: an open-world substrate returns it rather than guessing, and for a
# genuine gap (free arithmetic) UNDECIDED is the CORRECT outcome.
TRUE, FALSE, UNDECIDED = "TRUE", "FALSE", "UNDECIDED"

#: (name, question, context, accepted-verdicts). The accepted set is the set of
#: LOGICALLY CORRECT outcomes -- usually one, but a false universal may be
#: refuted OR left undecided (both are honest; only asserting it TRUE is wrong).
CASES = [
    ("syllogism", "Is Socrates mortal?",
     {"premises": ["Every human is mortal", "Socrates is a human"]}, {TRUE}),
    ("isa_transitive", "Is a robin an animal?",
     {"premises": ["A robin is a bird", "A bird is an animal"]}, {TRUE}),
    ("refutation", "Is a salmon a bird?",
     {"premises": ["A salmon is a fish", "No fish is a bird"]}, {FALSE}),
    ("modus_ponens", "Does the tank overflow?",
     {"premises": ["If the valve is closed then the tank overflows",
                   "The valve is closed"]}, {TRUE}),
    ("no_false_converse", "Is every animal a robin?",
     {"premises": ["A robin is a bird", "A bird is an animal"]},
     {FALSE, UNDECIDED}),
    ("gap_arithmetic", "What is 2 + 2?",
     {"premises": ["Basic arithmetic"]}, {UNDECIDED}),
]


def classify(result) -> str:
    """The verdict a ReasoningResult settled on. Unverified -> UNDECIDED (the
    substrate did not decide it); verified -> read the polarity off the answer,
    the same vocabulary the coordinator's reply path reads (`Proved`/`Yes` vs
    `Disproved`/`No`)."""
    md = result.metadata or {}
    if not md.get("verified"):
        return UNDECIDED
    answer = (result.answer or "").strip()
    if answer.startswith(("Proved", "Yes", "Entailed", "True")):
        return TRUE
    if answer.startswith(("Disproved", "No", "False", "Refuted", "Not entailed")):
        return FALSE
    return UNDECIDED


async def main() -> int:
    from core.memory import Origin
    from core.main import get_system

    t0 = time.time()
    print("Booting substrate (model-free reasoning path)…", flush=True)
    system = get_system()
    await system.initialize()
    coord = system.autonomous_coordinator
    if coord is None or getattr(coord, "neural_bridge", None) is None:
        print("✗ coordinator / neural bridge not initialised — cannot benchmark")
        return 2
    print(f"Booted in {time.time() - t0:.0f}s\n", flush=True)

    rows = []
    passed = 0
    for name, question, context, accepted in CASES:
        s = time.time()
        try:
            result = await coord.reason_about(question, context, origin=Origin.own("bench_reasoning_systems_v2"))
            got = classify(result)
            answer = (result.answer or "").strip() or "—"
            reason = (result.metadata or {}).get("reason", "")
            calls = (result.metadata or {}).get("model_calls", "?")
        except Exception as error:  # a crash is a real failure, reported as one
            got, answer, reason, calls = "ERROR", f"{type(error).__name__}: {error}", "", "?"
        ok = got in accepted
        passed += ok
        rows.append((name, "/".join(sorted(accepted)), got, ok,
                     round(time.time() - s, 2), answer, reason, calls))

    total = len(CASES)
    w = max(len(r[0]) for r in rows)
    print("=" * 78)
    print(f"REASONING BENCHMARK — {passed}/{total} correct  "
          f"(model-free: {sum(1 for r in rows if r[7] in (0, '0'))}/{total} "
          f"cases confirmed 0 model calls)")
    print("=" * 78)
    for name, exp, got, ok, secs, answer, reason, calls in rows:
        mark = "✓" if ok else "✗"
        print(f"{mark} {name:<{w}}  expect={exp:<16} got={got:<9} "
              f"{secs:>5.2f}s  calls={calls}")
        print(f"    answer: {answer[:88]}"
              + (f"   [{reason}]" if reason else ""))
    print("=" * 78)
    print(f"{passed}/{total} correct" + ("" if passed == total
          else "  — failures are real; they say what does not reason yet, "
               "honestly."))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
