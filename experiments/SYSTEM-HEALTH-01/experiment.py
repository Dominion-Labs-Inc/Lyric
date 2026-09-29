#!/usr/bin/env python3
"""SYSTEM-HEALTH-01 — health and recovery, alone, on the live substrate.

`HealthMonitor` and `RecoveryManager`, each meant to be one authority. Health
grades a real component from real evidence and refuses to grade with none;
recovery records a failure and can account for its history; the throttle it
hands the tool gate is a number.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-HEALTH-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, db, outcome, shutdown  # noqa: E402

EV = RunRecord(
    "SYSTEM-HEALTH-01",
    claim=("Health and recovery are each one authority: health grades a component from "
           "evidence and refuses to grade with none, recovery records a failure and its "
           "history, and the throttle the tool gate reads is a number."),
    hypothesis=("A health monitor or recovery manager the coordinator holds that is not the one "
                "the accessor returns, a grade with no evidence, or a dead public method would "
                "each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


#: A component name nothing real uses, so its recovery waits are the probe's alone.
RETRY_COMP = "isoprobe_recovery_component"


async def main() -> int:
    system, coord = await boot()
    d = db()
    try:
        from core.health.health_monitor import HealthStatus, get_health_monitor
        from core.health.recovery_manager import FailureType, get_recovery_manager
        H, R = get_health_monitor(), get_recovery_manager()

        print("\n== A. One authority each, and each is called ==")
        authority_audit(EV, check, system="health", cls="HealthMonitor",
                        path="core/health/health_monitor.py", held=coord.health_monitor, reached=H)
        authority_audit(EV, check, system="recovery", cls="RecoveryManager",
                        path="core/health/recovery_manager.py", held=coord.recovery_manager, reached=R)

        HM = coord.health_monitor or H
        print("\n== B. Health grades from evidence, and refuses to grade with none ==")
        none = HM.evaluate("isoprobe", {"n": 1}, [])
        check("no signals yields no score and UNKNOWN",
              none["score"] is None and none["status"] is HealthStatus.UNKNOWN, f"{none}")
        # The Constitution is graded as `safety` ("every act is judged here")
        # and `governance` (its declared policy) -- health's own vocabulary.
        con = await HM.check_component_health("safety")
        check("the Constitution is graded from its own surface",
              con is not None and con.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)
              and bool(con.metrics), f"status={con and con.status} metrics={sorted(con.metrics)[:6] if con else None}")
        refused = None
        try:
            await HM.check_component_health("isoprobe_not_a_component")
        except ValueError as error:
            refused = str(error)
        check("a name health does not know is refused, not graded",
              refused is not None, (refused or "graded")[:90])
        check("and is not registered as a component",
              "isoprobe_not_a_component" not in HM.component_health)
        sysh = await HM.get_system_health()
        check("system health is a dict", isinstance(sysh, dict) and bool(sysh), f"keys={sorted(sysh)[:8]}")

        print("\n== C. Recovery records a failure and its history ==")
        RM = coord.recovery_manager or R
        before = len(await RM.get_failure_history("isoprobe_component", 50))
        res = await RM.handle_failure(FailureType.VALIDATION_ERROR, "isoprobe_component",
                                      "SYSTEM-HEALTH-01 probe failure", "low", {"probe": True})
        after = await RM.get_failure_history("isoprobe_component", 50)
        check("a failure is handled and returns a result", hasattr(res, "success") and hasattr(res, "actions_taken"),
              f"success={getattr(res, 'success', None)} actions={[getattr(a, 'value', a) for a in getattr(res, 'actions_taken', [])]}")
        check("and is in the history", len(after) == before + 1, f"{before} -> {len(after)}")
        delay = RM.tool_throttle_delay()
        check("the throttle the tool gate reads is a non-negative number",
              isinstance(delay, (int, float)) and delay >= 0, f"{delay}")
        stats = await RM.get_statistics()
        check("recovery statistics are a dict", isinstance(stats, dict), f"keys={sorted(stats)[:8]}")

        print("\n== D. The wait before each recovery retry is learned ==")
        # The health tier runs for real; only the READING is the probe's: one
        # component reported unhealthy, then healthy.
        from core.learning import get_learning_authority
        L = get_learning_authority()
        reading = {"status": "unhealthy"}

        async def probe_reading():
            return {"components": {RETRY_COMP: dict(reading)}}

        coord.health_monitor.get_system_health = probe_reading
        await coord._idle_health_work()
        st = coord._component_recovery_state.get(RETRY_COMP) or {}
        check("the first recovery attempt is immediate, and the learner chooses the next wait",
              st.get("attempts") == 1 and st.get("pending_delay") is None
              and st.get("next_delay") in L.RETRY_DELAYS_S, f"{st}")
        wait = st.get("next_delay")
        await coord._idle_health_work()
        check("before that wait has passed, it does not retry", st.get("attempts") == 1)
        st["last_attempt"] -= (wait or 0) + 1          # the wait has passed
        await coord._idle_health_work()
        check("after it, it retries, the retry awaiting that wait's outcome",
              st.get("attempts") == 2 and st.get("pending_delay") == wait, f"{st}")
        reading["status"] = "unknown"
        await coord._idle_health_work()
        check("an unmeasured reading credits nothing and keeps the recovery open",
              RETRY_COMP in coord._component_recovery_state)
        reading["status"] = "healthy"
        await coord._idle_health_work()
        arm = next((a for a in L.meta_learning.strategies.values()
                    if str(a.strategy_type) == f"retry:{RETRY_COMP}:{int(wait)}"), None)
        check("seen healthy, the wait before the retry that recovered it is credited",
              RETRY_COMP not in coord._component_recovery_state
              and arm is not None and arm.successes == 1 and arm.trials == 1,
              f"arm={arm and (arm.successes, arm.trials)}")
    finally:
        try:
            try:
                del coord.health_monitor.get_system_health
            except AttributeError:
                pass
            coord._component_recovery_state.pop(RETRY_COMP, None)
            from core.learning import get_learning_authority as _authority
            ml = _authority().meta_learning
            for sid in [sid for sid, a in ml.strategies.items()
                        if str(a.strategy_type).startswith(f"retry:{RETRY_COMP}:")]:
                a = ml.strategies.pop(sid)
                if sid in ml.task_strategy_map.get(a.task_type, []):
                    ml.task_strategy_map[a.task_type].remove(sid)
                await d.execute_query("DELETE FROM unified.meta_learning_strategies WHERE strategy_id = $1", (sid,))
            await (coord.recovery_manager or R).clear_failure_history("isoprobe_component")
            for t in ("failure_events", "system_failures"):
                try:
                    await d.execute_query(f"DELETE FROM unified.{t} WHERE component = 'isoprobe_component'", ())
                except Exception:
                    pass
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-HEALTH-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
