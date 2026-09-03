"""Remedy B (staleness) against the REAL system — no stubs.

Creates a GENUINE stale baseline in the live store, runs the remedy, and asserts
the health monitor actually re-measured and persisted a current value (and the
false regression it caused cleared). The component ends at its true, current
reading, which is the correct state regardless of the test.
"""
import asyncio
import io
import contextlib
import logging

_COMPONENT = "memory"  # a live-healthy component that carries a health_score baseline


def test_remedy_b_refreshes_a_real_stale_baseline():
    async def _impl():
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from core.main import get_system
            s = get_system(); await s.initialize()
            from core.database import get_database_manager
            from core.health.health_monitor import get_health_monitor
            from core.learning.enhanced_asi_self_improvement import (
                get_asi_self_improvement, ImprovementTarget, RemedyFamily,
                classify_defect)
            db = get_database_manager()
            if not getattr(db, "initialized", False):
                await db.initialize()
            hm = get_health_monitor()
            asi = get_asi_self_improvement()

            async def last_cycle():
                r = await db.execute_query(
                    "SELECT last_cycle_value, updated_at FROM unified.long_term_baselines "
                    "WHERE component_name=$1 AND metric_name='health_score'",
                    (_COMPONENT,), fetch_all=True)
                return dict(r[0]) if r else None

            # live reading — the truth the stale value should be refreshed to
            h = await hm.check_component_health(_COMPONENT)
            live = round(float((getattr(h, "metrics", {}) or {}).get("_health_score", 0)) * 100, 1)
            assert live > 0, f"{_COMPONENT} not measurable; test needs a live-healthy component"

            # create a genuine stale baseline: frozen at 0, 10 days old
            if await last_cycle() is None:
                await db.execute_query(
                    "INSERT INTO unified.long_term_baselines (component_name, metric_name, "
                    "baseline_value, established_date, cycles_tracked, last_cycle_value, "
                    "trend_status, created_at, updated_at) VALUES "
                    "($1,'health_score',100,CURRENT_DATE,1,0,'degrading',NOW(),NOW()-INTERVAL '10 days')",
                    (_COMPONENT,), commit=True)
            else:
                await db.execute_query(
                    "UPDATE unified.long_term_baselines SET last_cycle_value=0, "
                    "trend_status='degrading', updated_at=NOW()-INTERVAL '10 days' "
                    "WHERE component_name=$1 AND metric_name='health_score'",
                    (_COMPONENT,), commit=True)
            stale = await last_cycle()
            assert float(stale["last_cycle_value"]) == 0.0

            # the finding classifies as STALENESS
            issues = [f"Capability regression (CRITICAL): {_COMPONENT}.health_score "
                      f"lost 100.0% against a baseline"]
            assert classify_defect(issues, _COMPONENT) is RemedyFamily.STALENESS

            target = ImprovementTarget(
                target_id="staletest", component=_COMPONENT, metric="health_score",
                current_value=0.0, target_value=100.0, improvement_potential=100.0,
                difficulty="easy", risk_level="low",
                context={"issues": issues, "status": "degrading"},
                remedy_family=RemedyFamily.STALENESS)

            # run remedy B
            outcome = await asi._refresh_stale_targets([target])
            after = await last_cycle()

            assert _COMPONENT in outcome["refreshed"], outcome
            assert not outcome["failed"], outcome
            # the stored value was actually re-measured and persisted current
            assert abs(float(after["last_cycle_value"]) - live) < 1.0, (after, live)
            assert str(after["updated_at"]) > str(stale["updated_at"])

    asyncio.run(_impl())
