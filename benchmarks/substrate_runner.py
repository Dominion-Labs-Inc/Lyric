"""The substrate side: run each task through the real completion path and read
back the substrate's OWN verdict — the grounded completion belief, not a proxy.

The task is built with the suite's fixed steps as its declared tool_plan, so the
substrate executes exactly what the LLM is asked to, in its own isolated world.
We capture the verdict `_execute_and_validate_task` actually computes by recording
`_decide_completion`'s return (for these tasks the downstream uncertainty gate is
inert — no target_component — so what we record is final). The post-decision code
may raise because the task was not enqueued; that is expected and harmless, the
belief and decision are already formed by then.
"""
from __future__ import annotations

from typing import Any, Dict

from core.agents.autonomous.shared_types import Task, TaskType, TaskSource


async def run_episode(coord, task, world_root: str) -> Dict[str, Any]:
    steps = task.steps(world_root)
    t = Task(
        id=f"bench-{task.id}",
        type=TaskType.EXECUTION,
        description=task.description,
        source=TaskSource.AUTONOMOUS,
        max_retries=0,
        metadata={"parameters": {"tool_plan": steps}},
    )

    captured: Dict[str, Any] = {}
    orig = coord._decide_completion

    def _capture(tk, result, verify_bar):
        verdict = orig(tk, result, verify_bar)
        # only the decision for THIS task
        if getattr(tk, "id", None) == t.id:
            captured["verdict"] = verdict
        return verdict

    coord._decide_completion = _capture
    try:
        await coord._execute_and_validate_task(t)
    except Exception:
        # expected: mark_completed/failed on a non-enqueued task raises AFTER the
        # decision. The verdict we need is already captured.
        pass
    finally:
        coord.__dict__.pop("_decide_completion", None)

    belief = None
    bid = (t.metadata or {}).get("completion_belief_id")
    if bid:
        belief = coord.learning.get_belief(bid)

    if "verdict" in captured:
        is_complete, confidence, issues = captured["verdict"]
        declared = bool(is_complete)
    else:
        # No decision reached (blocked before completion, e.g. safety). Report
        # honestly as no-verdict — never a silent pass.
        declared, confidence, issues = None, 0.0, ["no completion decision reached"]

    return {
        "declared": declared,
        "posterior": (float(belief.posterior_probability) if belief else None),
        "confidence": confidence,
        "issues": issues,
        "evidence": (t.metadata or {}).get("completion_evidence"),
        "anchor": (t.metadata or {}).get("completion_anchor"),
    }
