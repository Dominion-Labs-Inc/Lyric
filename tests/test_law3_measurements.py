"""What Law 3 measures the substrate's own work by.

SENSE-01 graded Law 3 at 0.00, "100% of recent work failed", on ONE task: the error rate was failed / finished
over the whole process, and the one task was a capability pursuit in a domain with no operator to sharpen, which
could only fail. Stand-ins only; nothing is read from or written to a store.
"""

import asyncio
from types import SimpleNamespace

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator


def _shell(recent):
    async def recent_outcomes(limit):
        assert limit == AutonomousCoordinator.ERROR_RATE_WINDOW
        if isinstance(recent, Exception):
            raise recent
        return recent
    return SimpleNamespace(
        ERROR_RATE_WINDOW=AutonomousCoordinator.ERROR_RATE_WINDOW,
        ERROR_RATE_MIN_FINISHED=AutonomousCoordinator.ERROR_RATE_MIN_FINISHED,
        system_state=SimpleNamespace(timestamp=None, performance_metrics={}),
        task_queue=SimpleNamespace(recent_outcomes=recent_outcomes))


def _error_rate(recent, before=None):
    shell = _shell(recent)
    if before is not None:
        shell.system_state.performance_metrics["error_rate"] = before
    asyncio.run(AutonomousCoordinator._update_system_state(shell))
    return shell.system_state.performance_metrics.get("error_rate", "absent")


def test_the_error_rate_is_over_recent_work_and_only_once_enough_has_finished():
    assert _error_rate((1, 1)) == "absent", "one failed task is not 100% of recent work failing"
    assert _error_rate((9, 9)) == "absent"
    assert _error_rate((20, 2)) == 0.1
    assert _error_rate((50, 0)) == 0.0
    assert _error_rate((5, 5), before=1.0) == "absent", "a stale rate does not stand in for a measurement"
    assert _error_rate(None, before=0.5) == "absent", "no durable history, no recent rate"
    assert _error_rate(RuntimeError("store down"), before=0.5) == "absent", "unreadable is absent"


def test_a_capability_pursuit_is_made_only_where_there_is_an_operator_to_sharpen(monkeypatch):
    import core.learning.demonstration_store as demonstrations
    import core.learning.exploration as exploration
    import core.reasoning.epistemic_engine as epistemic

    async def with_signatures():
        return {"blocks"}

    monkeypatch.setattr(demonstrations, "get_demonstration_store",
                        lambda: SimpleNamespace(domains_with_signatures=with_signatures))
    monkeypatch.setattr(epistemic, "get_epistemic_engine",
                        lambda: SimpleNamespace(get_unstable_regions=lambda: []))
    monkeypatch.setattr(exploration, "_proposers", {"gridworld": object()})

    ranked = [{"frontier": "capability", "domain": "reading"},
              {"frontier": "capability", "domain": "blocks"},
              {"frontier": "capability", "domain": "gridworld"},
              {"frontier": "knowledge", "domain": "reading"},
              {"frontier": "environment", "domain": "environment_x"}]

    async def development():
        return {"growth_pressure": 0.5}

    async def competence():
        return {}

    shell = SimpleNamespace(
        _development=development, _competence=competence,
        domain_registry=SimpleNamespace(initialized=True, domains={}),
        _score_pursuits=lambda *args, **kwargs: list(ranked))

    kept = asyncio.run(AutonomousCoordinator._intrinsic_pursuits(shell, limit=8))
    assert [(p["frontier"], p["domain"]) for p in kept] == [
        ("capability", "blocks"), ("capability", "gridworld"),
        ("knowledge", "reading"), ("environment", "environment_x")], kept

    async def unreadable():
        raise RuntimeError("store down")

    monkeypatch.setattr(demonstrations, "get_demonstration_store",
                        lambda: SimpleNamespace(domains_with_signatures=unreadable))
    kept = asyncio.run(AutonomousCoordinator._intrinsic_pursuits(shell, limit=8))
    assert all(p["frontier"] != "capability" for p in kept), "unreadable, no capability pursuit is made"
    assert len(kept) == 2
