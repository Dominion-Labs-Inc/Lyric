"""CAPABILITY-BASELINE-01 — long-term capability baseline + regression tracking on the authority.

Proves the genuine (non-LLM) capability re-homed from the retired improvement_monitor onto the
UnifiedLearningSystem: a component's capability metric is baselined once, then each later reading is
compared to the baseline and a long-horizon trend recorded, and `get_capability_regressions()` reports
the degrading ones. Real Postgres, no stubs. Self-cleaning.

  1. First reading establishes a baseline (no fabricated trend).
  2. A reading within ±5% reads `stable`; a >5% drop reads `degrading`; a >5% rise `improving`.
  3. get_capability_regressions() surfaces a degrading capability and drops it once it recovers.
  4. establish=False refuses to CREATE a baseline from an unfit reading but still UPDATES an existing one.
  5. Decimal/float mismatch is handled (every comparison after the first actually runs).

Run: ./venv_lyric/bin/python3 experiments/CAPABILITY-BASELINE-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))

_COMP = "__captest_component__"
_COMP2 = "__captest_component2__"


async def _clean(db):
    await db.execute_query(
        "DELETE FROM unified.long_term_baselines WHERE component_name = ANY($1)",
        params=([_COMP, _COMP2],), commit=True)


async def main() -> int:
    from core.database import get_database_manager
    from core.learning.unified_learning_system import get_unified_learning_system
    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    authority = get_unified_learning_system()
    await authority._ensure_capability_schema()
    await _clean(db)

    print("\n== 1. First reading establishes a baseline ==")
    r = await authority.track_capability_baseline(_COMP, "health_score", 100.0)
    check("baseline established", r["status"] == "baseline_established" and r["baseline_value"] == 100.0, str(r))

    print("\n== 2. Trend classification against the baseline ==")
    r = await authority.track_capability_baseline(_COMP, "health_score", 100.0)
    check("within ±5% reads stable", r["trend_status"] == "stable", str(r))
    r = await authority.track_capability_baseline(_COMP, "health_score", 80.0)
    check("a >5% drop reads degrading (Decimal/float compare works)",
          r["trend_status"] == "degrading" and r["pct_change"] == -20.0, str(r))

    print("\n== 3. get_capability_regressions surfaces then drops it ==")
    regs = await authority.get_capability_regressions()
    mine = [x for x in regs if x["component_name"] == _COMP]
    check("degrading component surfaced", len(mine) == 1 and mine[0]["baseline_value"] == 100.0, str(mine))
    r = await authority.track_capability_baseline(_COMP, "health_score", 115.0)
    check("recovery reads improving", r["trend_status"] == "improving", str(r))
    regs = await authority.get_capability_regressions()
    check("recovered component no longer reported",
          not any(x["component_name"] == _COMP for x in regs))

    print("\n== 4. establish=False: no create, but updates existing ==")
    r = await authority.track_capability_baseline(_COMP2, "health_score", 0.0, establish=False)
    check("refuses to establish a baseline from an unfit reading", r["status"] == "skipped_no_baseline", str(r))
    regs = await authority.get_capability_regressions()
    check("nothing created for the skipped component",
          not any(x["component_name"] == _COMP2 for x in regs))
    # an existing baseline still updates under establish=False
    r = await authority.track_capability_baseline(_COMP, "health_score", 50.0, establish=False)
    check("existing baseline updates under establish=False (degrades)",
          r["status"] == "updated" and r["trend_status"] == "degrading", str(r))

    await _clean(db)
    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
