#!/usr/bin/env python3
"""Rendering a proved state plan as tasks the existing executor can run.

The planner owns WHY these actions achieve the goal. This owns HOW they are
represented to the executor. Keeping them apart means the search never has to
know about Task fields, and the executor never has to know about operators.

The one thing that must survive the translation is order. `get_next_tasks`
sorts by priority and returns up to `max_concurrent_tasks` at once, so a state
plan handed over as a flat list would be reordered and run in parallel -- and
in a plan where each step's preconditions are established by the one before it,
that is not a slowdown, it is a wrong answer. Order is therefore carried by an
explicit dependency chain, the one mechanism `_can_execute_task` enforces.

No parallelism is inferred. The planner emits a total order; two steps that
could in principle run together are not known to be independent just because
nothing yet says they aren't. When the planner produces genuine partial-order
plans, that information will come from the planner rather than be guessed here.

Validation happens before anything is persisted, because a malformed chain that
reaches storage becomes a plan that cannot be executed and cannot be explained.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from .shared_types import Goal, Priority, Task, TaskStatus, TaskType

logger = logging.getLogger(__name__)


class PlanValidationError(ValueError):
    """Raised when a task chain would be unexecutable or untraceable."""


def validate_task_chain(tasks: Sequence[Task]) -> None:
    """Refuse duplicate ids, dangling references, self-dependencies and cycles.

    `_can_execute_task` independently fails closed on an unresolvable
    dependency at runtime. This is the other half: the runtime check protects
    against state that was corrupted after the fact, and this prevents a
    corrupt chain being created in the first place. Neither makes the other
    redundant.
    """
    identifiers = [task.id for task in tasks]
    duplicates = {i for i in identifiers if identifiers.count(i) > 1}
    if duplicates:
        raise PlanValidationError(f"duplicate task ids: {sorted(duplicates)}")

    known = set(identifiers)
    for task in tasks:
        for dependency in task.dependencies or []:
            if dependency == task.id:
                raise PlanValidationError(f"task {task.id} depends on itself")
            if dependency not in known:
                raise PlanValidationError(
                    f"task {task.id} depends on {dependency}, which is not in "
                    f"this plan; the executor would treat it as no blocker"
                )

    # Cycle detection over the dependency edges.
    dependencies = {task.id: list(task.dependencies or []) for task in tasks}
    visiting: set = set()
    settled: set = set()

    def walk(node: str, trail: List[str]) -> None:
        if node in settled:
            return
        if node in visiting:
            cycle = " -> ".join(trail + [node])
            raise PlanValidationError(f"dependency cycle: {cycle}")
        visiting.add(node)
        for nxt in dependencies.get(node, []):
            walk(nxt, trail + [node])
        visiting.discard(node)
        settled.add(node)

    for identifier in identifiers:
        walk(identifier, [])


def state_plan_to_tasks(
    result: Any,
    goal: Goal,
    plan_id: str,
    grounding_complete: bool = True,
    domain_id: Optional[str] = None,
    intent_id: Optional[str] = None,
) -> List[Task]:
    """Turn a PLAN_FOUND result into a strictly ordered task chain.

    Each task depends on its predecessor, so `get_next_tasks` can only ever
    offer the next runnable step regardless of how it sorts.

    THE DOMAIN TRAVELS WITH THE TASK. Planning knows which domain its rules
    came from and this dropped it, so the executor -- which looks the action's
    tool up by (domain, predicate) -- searched the unnamed domain and found
    nothing. Every task built from a learned plan refused with "no tool bound",
    whatever was bound.
    """
    from core.reasoning.temporal_reasoning import PlanningStatus

    if result.status is not PlanningStatus.PLAN_FOUND:
        raise PlanValidationError(
            f"cannot build tasks from a {result.status.value} result"
        )

    tasks: List[Task] = []
    previous: Optional[str] = None

    def reading_steps_for(operator: str) -> List[Task]:
        """THE PLANNER READS FIRST.

        Law 2 refuses an act on a file the substrate has no current account of,
        and the answer the law gives is "read it, then plan from what it says".
        That is a planning step, so the planner puts it in the route rather than
        letting execution discover that the act it proved cannot legally run.

        The paths come from the BINDING — the same translation from operator to
        tool arguments the executor will make — and which of them need reading is
        answered by the constitution, so the planner and the judge cannot
        disagree about what the law requires.

        Nothing is guessed: an unbound operator or an unreadable world yields no
        reading steps, and the act is then refused at the gate, which is the
        honest outcome.
        """
        nonlocal previous
        try:
            from core.agents.autonomous.autonomous_coordinator import get_constitution
            from core.execution.operator_binding import get_binding_registry
            from core.learning.rule_induction import Fact

            fact = Fact.parse(operator)
            binding = get_binding_registry().get(domain_id or "", fact.predicate)
            if binding is None:
                return []
            params = binding.parameters(fact.args)
            needed = get_constitution().requires_reading(binding.tool_name, params)
        except Exception:
            # The planner never fabricates a preparatory step it cannot justify.
            return []

        built: List[Task] = []
        for path in needed:
            read_task = Task(
                id=str(uuid4()),
                type=TaskType.EXECUTION,
                description=f"read {path}",
                priority=goal.priority,
                status=TaskStatus.PENDING,
                created_at=datetime.now(),
                estimated_duration=0.1,
                dependencies=[previous] if previous else [],
                provenance={
                    "goal_id": goal.id,
                    "plan_id": plan_id,
                    "domain_id": domain_id,
                    "intent_id": intent_id,
                    "planning_mode": "state",
                    # NOT a grounded operator: this step is not part of the proved
                    # route, it is what the law requires before the route may run.
                    # Saying so plainly keeps it out of the operator path, which
                    # would refuse it for having no rule behind it.
                    "reading_for": operator,
                    "read_path": path,
                    "predecessor_task_id": previous,
                },
            )
            built.append(read_task)
            previous = read_task.id
        return built

    for index, (step, action) in enumerate(zip(result.steps, result.actions)):
        tasks.extend(reading_steps_for(str(step["action"])))
        task = Task(
            id=str(uuid4()),
            type=TaskType.EXECUTION,
            description=step["action"],
            priority=goal.priority,
            status=TaskStatus.PENDING,
            created_at=datetime.now(),
            estimated_duration=float(
                step.get("duration").total_seconds() / 60.0
                if hasattr(step.get("duration"), "total_seconds") else 5.0
            ),
            dependencies=[previous] if previous else [],
            provenance={
                "goal_id": goal.id,
                "plan_id": plan_id,
                "domain_id": domain_id,
                # WHICH INTENT THIS STEP BELONGS TO. The task REFERENCES the
                # intent the reasoning authority holds; it is not itself the
                # account of why the substrate is acting. One goal is one intent,
                # and `step_index` below says which step of its proved route this
                # is.
                "intent_id": intent_id,
                "planning_mode": "state",
                "planning_result": result.status.value,
                "goal_conditions": list(result.goal_conditions),
                "grounding_complete": grounding_complete,
                "grounded_operator": step["action"],
                "learned_rule_id": action.get("rule_id"),
                "bindings": action.get("bindings", {}),
                # What this step will produce that nothing can know yet, and
                # what the planner expected it to be. Recorded so the plan's
                # own account can be compared with what running it produced.
                "pending": list(action.get("deferred") or ()),
                "produced": [dict(p) for p in (action.get("produced") or ())],
                "plan_guarantee": getattr(
                    getattr(result, "guarantee", None), "value", None),
                "step_index": index,
                "predecessor_task_id": previous,
            },
        )
        tasks.append(task)
        previous = task.id

    validate_task_chain(tasks)
    return tasks
