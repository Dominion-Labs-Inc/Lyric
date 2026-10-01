#!/usr/bin/env python3
"""Re-runnable evidence for the evidence-source wiring and the defects it exposed.

Every claim below is produced by executing the real code path, not by reading
it. Writes experiments/WIRING_EVIDENCE.json and prints the same content.
"""
from __future__ import annotations

import asyncio, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database.unified_database_postgres import get_unified_database  # noqa: E402


async def store_state(db):
    async def rows(sql):
        return [dict(r) for r in (await db.execute_query(sql, fetch_all=True) or [])]
    return {
        "envelopes_by_source": await rows(
            "SELECT source_type, producer, count(*) n FROM unified.evidence_envelopes "
            "GROUP BY 1,2 ORDER BY 1,2"),
        "concepts_by_extractor": await rows(
            "SELECT provenance->>'first_source_type' source_type, "
            "provenance->>'extractor' extractor, count(*) n "
            "FROM unified.concepts GROUP BY 1,2 ORDER BY 3 DESC"),
        "relations_by_extractor": await rows(
            "SELECT extractor, count(*) n FROM unified.concept_relations "
            "GROUP BY 1 ORDER BY 2 DESC"),
        "reasoning_pattern_rules": await rows(
            "SELECT rule_id, rendered_formula, epistemic_status FROM unified.learned_rules "
            "WHERE rule_kind='reasoning_pattern' ORDER BY rule_id"),
    }


async def check_perception():
    from core.perception.perception_faculty import get_perception_faculty
    faculty = get_perception_faculty()
    before = faculty.awareness()["admitted"]
    from core.memory import Origin
    p = await faculty.admit_percept(
        "health_monitoring", "component_degraded",
        {"component": "learning_system", "severity": "degraded",
         "message": "learning subsystem reported degraded health"},
        origin=Origin.own("health monitoring"))
    aware = [q for q in faculty.recent_percepts(3) if q.source == "health_monitoring"]
    admitted = faculty.awareness()["admitted"] - before
    return {
        "perceived": bool(p),
        "admitted_as_evidence": admitted,
        "in_awareness": len(aware),
        "passed": bool(p and admitted == 1 and aware),
    }


async def check_tool_projection():
    from core.tools.tool_registry import get_tool_registry
    registry = get_tool_registry()
    result = await registry.execute_tool(
        "list_directory", {"directory_path": str(Path(__file__).resolve().parent)})
    projection = await registry.project_capabilities()
    return {"tool_invocation_succeeded": result.success,
            "projection": projection,
            "passed": result.success and projection["projected"] > 0
                      and projection["failed"] == 0}


async def main() -> int:
    db = await get_unified_database()
    await db.initialize()

    checks = {
        "perception_admission": await check_perception(),
        "tool_observation_and_projection": await check_tool_projection(),
    }
    evidence = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "store_state": await store_state(db),
        "all_passed": all(c["passed"] for c in checks.values()),
    }

    out = Path(__file__).resolve().parent / "WIRING_EVIDENCE.json"
    out.write_text(json.dumps(evidence, indent=2, default=str))

    for name, check in checks.items():
        print(f"{'PASS' if check['passed'] else 'FAIL'}  {name}")
    print(f"\nALL: {'PASS' if evidence['all_passed'] else 'FAIL'}")
    print(f"evidence -> {out}")
    return 0 if evidence["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
