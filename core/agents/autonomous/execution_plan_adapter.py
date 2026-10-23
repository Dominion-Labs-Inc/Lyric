#!/usr/bin/env python3
"""Rendering a proved state plan as tasks the existing executor can run, and
decomposing a goal in words into the work it names (GOALS IN WORDS, below).

The planner owns WHY these actions achieve the goal. This owns HOW they are
represented to the executor. Keeping them apart means the search never has to
know about Task fields, and the executor never has to know about operators.

The one thing that must survive the translation is order. In a state plan each
step's preconditions are established by the one before it, so steps reordered or
run in parallel would not be a slowdown, they would be a wrong answer. The
pursuit that proved the route walks its steps in order
(`AutonomousCoordinator._pursue_proved_route`), and order is also carried by an
explicit dependency chain, so nothing that reads the steps can take them as
independent.

No parallelism is inferred. The planner emits a total order; two steps that
could in principle run together are not known to be independent just because
nothing yet says they aren't. When the planner produces genuine partial-order
plans, that information will come from the planner rather than be guessed here.

Validation happens before the steps are handed to anything, because a malformed
chain becomes a plan that cannot be executed and cannot be explained.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple
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

    Each task depends on its predecessor, so whatever reads the chain can only
    ever take the next runnable step.

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
            from core.tools.tool_registry import get_binding_registry
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


# ── GOALS IN WORDS: decomposed into the work they name ────────────────────────
#
# A goal stated over world state is planned by search (temporal reasoning's
# `plan_state_goal`) and its proved route rendered above. A goal stated in words
# names kinds of work instead -- find out, examine, make -- and is decomposed
# here into steps of those kinds, chained in the order the work depends on, each
# carrying what it is about and what it is to make. The substrate pursues such a
# goal (`AutonomousCoordinator._pursue_described_goal`); this says what its
# steps are, what the plan may claim about itself, and what it was formed on.

import re  # noqa: E402

from core.tools import get_tool_registry  # noqa: E402

class PlanInput(Enum):
    """What a KIND of plan needs before it can be formed.

    Not every plan is the same. A state goal needs the world as it is now and the
    operators the substrate has learned; a descriptive one needs what its tools
    have actually done and what the substrate abstracted from past experience.
    Declaring that per kind makes the difference stated rather than implied, and
    each input is obtained through the AUTHORITY that owns it — never by reaching
    into a store behind its owner's back.
    """
    #: The world as it is now. The COORDINATOR perceives; the planner is given it.
    OBSERVED_WORLD = "observed_world"
    #: The operators the substrate has learned — the rule store.
    LEARNED_OPERATORS = "learned_operators"
    #: How the tools have actually performed — the learning authority.
    TOOL_HISTORY = "tool_history"
    #: Principles and schemas — the reasoning authority, which owns abstraction.
    ABSTRACTION = "abstraction"
    #: Specific past experiences, queried within the abstraction's constraints.
    #: Named for what the memory authority calls it — `MemoryType.EPISODIC` —
    #: rather than a term invented here.
    EPISODIC_MEMORY = "episodic_memory"
    #: Earned correctness in a domain — the domain authority.
    OPERATING_RELIABILITY = "operating_reliability"


#: What each kind of plan declares it needs. The engine assembles exactly this.
PLAN_KIND_INPUTS: Dict[str, Tuple[PlanInput, ...]] = {
    "state": (PlanInput.OBSERVED_WORLD, PlanInput.LEARNED_OPERATORS,
              PlanInput.OPERATING_RELIABILITY),
    "template": (PlanInput.TOOL_HISTORY, PlanInput.ABSTRACTION,
                 PlanInput.EPISODIC_MEMORY),
}



#: The kinds of work a descriptive goal can name, in the order the work
#: depends on: what is found gets analysed, what is analysed gets written.
#: Several may be named at once, and then all of them are planned.
_WORK_PHASES = (
    ("research", ("research", "investigate", "find out", "look up", "study",
                  "learn about", "gather")),
    ("analysis", ("analyz", "analys", "examine", "assess", "evaluate",
                  "compare")),
    ("creation", ("create", "write", "produce", "generate", "draft",
                  "build", "compose", "summar", "report")),
)


async def _generate_tasks_for_goal(goal: Goal, context: Dict[str, Any]) -> List[Task]:
    """Decompose a descriptive goal into the work it NAMES — ALL of it.

    FIRST MATCH WINS WAS DROPPING HALF THE GOAL. This was
    `if "research" … elif "analyze" … elif "create" …`, so
    "Research photosynthesis and create a written summary at <path>" planned
    RESEARCH and ANALYSIS and never planned the write at all. Measured in
    RESEARCH-WRITE-01: no file, no act, no demonstration, nothing to verify
    — and because a template plan carries no goal state, the plan reported
    done anyway. The failure read as "the substrate could not do it" when it
    had never been asked to.

    A goal may name several kinds of work. Each named phase is planned, and
    each is CHAINED to the one before it, so the step that writes the
    summary runs after the research it is supposed to be writing up rather
    than beside it.
    """
    tasks = []

    described = goal.description.lower()
    makers = {"research": _generate_research_tasks,
              "analysis": _generate_analysis_tasks,
              "creation": _generate_creation_tasks}
    named = [phase for phase, words in _WORK_PHASES
             if any(word in described for word in words)]

    subject = subject_named_by(goal.description)
    # WRITING UP WHAT IS KNOWN ABOUT SOMETHING NEEDS THAT KNOWLEDGE GATHERED
    # FIRST. The creation step writes up the findings of the steps before it
    # and invents nothing, so "Create a written summary of what you know
    # about centrifugal pumps at <path>" -- a creation with a subject and no
    # step that says anything about it -- wrote nothing and could not.
    # Gathering answers from what is held first and looks further only on a
    # gap, so it is the step that produces the content.
    if subject and "creation" in named and "research" not in named:
        named.insert(0, "research")
    if named:
        previous: List[Task] = []
        for phase in named:
            stage = makers[phase](goal)
            # THE STEPS OF A STAGE HAPPEN IN ORDER TOO. Only stages were
            # chained, so a stage's own steps were all ready at once and the
            # step that checks the file ran beside -- or before -- the step
            # that writes it, and failed on an empty path.
            for before, after in zip(stage, stage[1:]):
                after.dependencies = list(after.dependencies or []) + [before.id]
            if subject:
                # WHAT THE WORK IS ABOUT travels with every step of it, so
                # no step has to recover it from its own instruction.
                for step in stage:
                    step.provenance = dict(step.provenance or {})
                    step.provenance["subject"] = subject
            if previous and stage:
                # THE ORDER IS THE POINT. Without it the writer can run
                # before the research and write up nothing.
                stage[0].dependencies = list(stage[0].dependencies or []) + [previous[-1].id]
            tasks.extend(stage)
            previous = stage or previous
    else:
        # Default task breakdown
        tasks.append(Task(
            id=str(uuid4()),
            type=TaskType.RESEARCH,
            description=f"Research requirements for: {goal.description}",
            priority=goal.priority,
            estimated_duration=30.0,
            created_at=datetime.now()
        ))

        tasks.append(Task(
            id=str(uuid4()),
            type=TaskType.ANALYSIS,
            description=f"Analyze approach for: {goal.description}",
            priority=goal.priority,
            estimated_duration=20.0,
            created_at=datetime.now(),
            dependencies=[tasks[0].id]
        ))

        tasks.append(Task(
            id=str(uuid4()),
            type=TaskType.EXECUTION,
            description=f"Execute: {goal.description}",
            priority=goal.priority,
            estimated_duration=60.0,
            created_at=datetime.now(),
            dependencies=[tasks[1].id]
        ))

    # Enhance all tasks with tool suggestions
    enhanced_tasks = [_enhance_task_with_tools(task) for task in tasks]

    return enhanced_tasks


def _generate_research_tasks(goal: Goal) -> List[Task]:
    """Generate research-specific tasks"""
    return [
        Task(
            id=str(uuid4()),
            type=TaskType.RESEARCH,
            description=f"Information gathering for: {goal.description}",
            priority=goal.priority,
            estimated_duration=45.0,
            created_at=datetime.now()
        ),
        Task(
            id=str(uuid4()),
            type=TaskType.ANALYSIS,
            description=f"Analyze research findings for: {goal.description}",
            priority=goal.priority,
            estimated_duration=30.0,
            created_at=datetime.now()
        )
    ]


def _generate_analysis_tasks(goal: Goal) -> List[Task]:
    """Generate analysis-specific tasks"""
    return [
        Task(
            id=str(uuid4()),
            type=TaskType.ANALYSIS,
            description=f"Data analysis for: {goal.description}",
            priority=goal.priority,
            estimated_duration=40.0,
            created_at=datetime.now()
        ),
        Task(
            id=str(uuid4()),
            type=TaskType.SYNTHESIS,
            description=f"Synthesize analysis results for: {goal.description}",
            priority=goal.priority,
            estimated_duration=25.0,
            created_at=datetime.now()
        )
    ]


def artefact_named_by(description: str) -> Optional[str]:
    """The thing this goal says to CREATE, if it names one.

    THE PLANNER IS THE GOAL-READER. "create a written summary at
    /tmp/x/findings.md" names its own product, and the step that makes it
    cannot make it without knowing what it is. Reading that here — once,
    where the goal is already being read — is what lets the executor act on
    a target instead of guessing one, and what lets VALIDATION check the
    right thing afterwards.

    Returns None when the goal names no artefact, and a creation step then
    says so honestly rather than inventing a destination.
    """
    # A path-shaped token: at least one separator and a final segment. Not a
    # guess about filesystems -- it is the only thing in the sentence that
    # could be a destination, and if there is none there is no destination.
    candidates = re.findall(r"(?:/|~/)[\w./~-]*[\w-]", str(description or ""))
    return candidates[-1] if candidates else None


def subject_named_by(description: str) -> Optional[str]:
    """WHAT this goal is about, as distinct from what it says to do.

    A step's description is an INSTRUCTION — "Information gathering for:
    Research photosynthesis and create a written summary at <path>" — and
    asking the knowledge loop about the whole sentence asks about the
    sentence. Measured: the loop took `summary` for the topic and the
    substrate wrote a correct, verified file that said "summary is a
    written or spoken work". A file about nothing, passing every check
    except the one that reads it.

    So the subject is read once, here, where the goal is already being read:
    what follows the instruction verb, up to where the instruction turns to
    what to DO with it. Returns None when the goal names no subject, and the
    loop then falls back to its own reading of the description.
    """
    text = " ".join(str(description or "").split())
    after = re.sub(
        r"^(?:please\s+)?(?:research|investigate|study|look\s+up|find\s+out"
        r"(?:\s+about)?|learn\s+about|gather\s+information\s+(?:on|about))\s+",
        "", text, flags=re.IGNORECASE)
    if after == text:
        # A GOAL TO MAKE SOMETHING NAMES ITS SUBJECT AFTER WHAT IT MAKES:
        # "a written summary of what you know ABOUT centrifugal pumps", "a
        # report ON cavitation", "a summary OF photosynthesis". The first
        # `about` wins; failing that, what a summary/report/note is of or on.
        found = (re.search(r"\babout\s+(.+)", text, flags=re.IGNORECASE)
                 or re.search(r"\b(?:summary|report|overview|description|notes?|"
                              r"write-?up)\s+(?:of|on)\s+(?!what\b)(.+)",
                              text, flags=re.IGNORECASE))
        if not found:
            return None
        after = found.group(1)
    # The subject ends where the goal starts saying what to do with it, or
    # where it names the destination ("... at /tmp/x/summary.md").
    subject = re.split(
        r"\s+(?:and|then|,|;|so\s+that|in\s+order\s+to)\s+"
        r"|\s+(?:at|to|in|into)\s+(?=[/~])",
        after, maxsplit=1, flags=re.IGNORECASE)[0]
    subject = subject.strip(" .:;")
    return subject or None


def _generate_creation_tasks(goal: Goal) -> List[Task]:
    """Generate creation-specific tasks"""
    artefact = artefact_named_by(goal.description)
    # WHAT IS TO BE MADE TRAVELS WITH THE STEPS THAT MAKE AND CHECK IT.
    # Without it the creation step has a sentence and no target, and the
    # validation step has nothing to verify -- which is how a plan came to
    # report done with no file anywhere.
    made = {"artefact": artefact} if artefact else {}
    # No "plan the creation" step: this plan IS that, and the step that
    # asked for it again had no path that could carry it out, so every
    # creation plan held a step that could only fail.
    return [
        Task(
            id=str(uuid4()),
            type=TaskType.EXECUTION,
            description=f"Create: {goal.description}",
            priority=goal.priority,
            estimated_duration=90.0,
            created_at=datetime.now(),
            provenance=dict(made),
        ),
        Task(
            id=str(uuid4()),
            type=TaskType.VALIDATION,
            description=f"Validate creation: {goal.description}",
            priority=goal.priority,
            estimated_duration=15.0,
            created_at=datetime.now(),
            provenance=dict(made),
        )
    ]


def _estimate_plan_duration(tasks: List[Task]) -> float:
    """Estimate total duration for plan execution"""
    return sum(task.estimated_duration for task in tasks)


#: A schema must be this strong before it constrains planning. Below it, the
#: regularity is not established enough to shape what the substrate does.
SCHEMA_STRENGTH_FLOOR: float = 0.7

# ── the proved route, recorded as intent ─────────────────────────────────


async def assemble_inputs(kind: str, goal: Goal,
                          context: Dict[str, Any]) -> Dict[str, Any]:
    """Gather exactly the inputs this KIND of plan declares it needs.

    Each is obtained through the authority that OWNS it, and what could not
    be obtained is reported as missing with a reason rather than quietly
    skipped — a plan formed without an input it declared is a plan formed on
    less than it said it needed.
    """
    required = PLAN_KIND_INPUTS.get(kind, ())
    gathered: Dict[str, Any] = {}
    missing: List[Dict[str, Any]] = []
    for need in required:
        obtained = await _obtain_input(need, goal, context)
        if obtained.get("available"):
            gathered[need.value] = obtained
        else:
            missing.append({"input": need.value,
                            "reason": obtained.get("reason")})
    return {"kind": kind,
            "required": [need.value for need in required],
            "gathered": gathered,
            "missing": missing}


async def _obtain_input(need: PlanInput, goal: Goal,
                        context: Dict[str, Any]) -> Dict[str, Any]:
    """One declared input, from its owner. Absence is reported, never filled."""
    try:
        if need is PlanInput.OBSERVED_WORLD:
            # The COORDINATOR perceives the environment; the planner is given
            # what it saw. The planner does not go and look for itself.
            world = context.get("world_state")
            if world is None:
                return {"available": False,
                        "reason": "no observed world supplied by the coordinator"}
            return {"available": True, "source": "coordinator (perception)",
                    "facts": len(world)}

        if need is PlanInput.LEARNED_OPERATORS:
            from core.learning.rule_store import get_rule_store
            domain_id = context.get("domain_id")
            rules = await get_rule_store().executable_rules(domain_id=domain_id)
            if not rules:
                return {"available": False,
                        "reason": f"the rule store holds no executable "
                                  f"operator for domain {domain_id!r}"}
            return {"available": True, "source": "rule store",
                    "operators": len(rules)}

        if need is PlanInput.TOOL_HISTORY:
            metrics = await _measured_tool_metrics()
            if not metrics.get("available"):
                return {"available": False, "reason": metrics.get("reason")
                        or "no tool history recorded"}
            return {"available": True, "source": "learning authority",
                    "runs": metrics.get("runs"),
                    "success_rate": metrics.get("success_rate")}

        if need in (PlanInput.ABSTRACTION, PlanInput.EPISODIC_MEMORY):
            hierarchical = await _hierarchical_context(
                goal, domain=context.get("domain_id") or "general")
            if not hierarchical.get("available"):
                return {"available": False,
                        "reason": hierarchical.get("reason")}
            if need is PlanInput.ABSTRACTION:
                return {"available": True, "source": "reasoning authority",
                        "principles": len(hierarchical.get("principles_applied") or []),
                        "schemas": len(hierarchical.get("schemas_considered") or []),
                        "constraints": hierarchical.get("strategy_constraints") or []}
            return {"available": True, "source": "memory, within abstraction",
                    "memories": hierarchical.get("supporting_memories") or []}

        if need is PlanInput.OPERATING_RELIABILITY:
            domain_id = context.get("domain_id")
            if not domain_id:
                return {"available": False,
                        "reason": "no domain to read earned reliability for"}
            from core.integration.universal_domain_master import (
                get_universal_domain_master)
            reliability = await get_universal_domain_master(
                ).operating_reliability(domain_id)
            return {"available": True, "source": "domain authority",
                    **reliability}

        return {"available": False, "reason": f"unknown input {need!r}"}
    except Exception as e:
        logger.debug("planning input %s unavailable: %s", need.value, e)
        return {"available": False, "reason": str(e)}


def _constrained_query(description: str, constraints: List[Dict[str, Any]]) -> str:
    """The memory query, narrowed by what the strongest schemas prefer."""
    parts = [description]
    for constraint in constraints[:3]:
        for key, value in (constraint.get("prefer") or {}).items():
            parts.append(f"{key}:{value}")
    return " ".join(parts)


async def _memories_within(description: str,
                          constraints: List[Dict[str, Any]],
                          pipeline: Any) -> List[str]:
    """EPISODIC memories queried WITHIN the strategy constraints — ids only.

    Scoped to `MemoryType.EPISODIC` — specific past experiences — because that
    is what this step claims to consult. The planner this came from said
    "episodic" in its docstring while querying every memory type, so the claim
    and the query disagreed.

    `search_memories` returns either a list or a (ok, list) pair depending on
    the interface a caller uses; both are handled, because assuming one was a
    second latent bug in that planner.
    """
    from core.memory.utils.interfaces import MemoryType
    found = await pipeline.memory.search_memories(
        query_text=_constrained_query(description, constraints),
        memory_types=[MemoryType.EPISODIC], limit=20)
    if isinstance(found, tuple):
        found = found[1] if len(found) > 1 else []
    return [m for m in
            (getattr(item, "memory_id", "") for item in (found or [])) if m]


async def _hierarchical_context(goal: Goal,
                                domain: str = "general") -> Dict[str, Any]:
    """Abstraction UPSTREAM of planning: the principles and schemas that bear
    on this goal, and the past experience falling WITHIN those constraints.

    Absorbed from the orphaned `HierarchicalPlanner`, which had no callers.
    Its METHOD is what is kept — principles → schemas beneath them → strategy
    constraints → episodic memory queried within those constraints — because
    that is what makes planning hierarchical, and it is how a plan draws on
    past memories rather than on the goal's wording alone.

    ITS FINAL STEP IS DELIBERATELY NOT KEPT. That emitted prose steps
    ("Apply strategy: {when} → {prefer}", "Based on past: {action}") — output
    shaped like a plan that proves nothing. Steps come from proved operators;
    this supplies the CONTEXT a plan is formed in, recorded as real ids.
    """
    from core.reasoning.hierarchical_abstraction import AbstractionLevel
    from core.reasoning.neural_bridge import get_neural_bridge
    # THROUGH THE REASONING AUTHORITY, which owns abstraction — not the
    # module-level global behind it.
    pipeline = getattr(get_neural_bridge(), "abstraction", None)
    if pipeline is None:
        return {"available": False,
                "reason": "the reasoning authority has not brought up "
                          "abstraction yet"}
    try:
        hierarchy = pipeline.concept_hierarchy
        principles = hierarchy.find_principles_for_domain(domain)
        schemas = []
        for principle in principles:
            for node in hierarchy.get_descendants(principle.concept_id,
                                                  max_depth=1):
                if node.level is AbstractionLevel.SCHEMA and node.schema_id:
                    schema = pipeline.active_schemas.get(node.schema_id)
                    if schema is not None:
                        schemas.append(schema)
        constraints = [
            {"when": s.condition, "prefer": s.outcome,
             "confidence": s.probability, "schema_id": s.schema_id,
             "evidence_count": s.evidence_count}
            for s in schemas if s.probability > SCHEMA_STRENGTH_FLOOR
        ]
        return {
            "available": True,
            "domain": domain,
            "principles_applied": [p.concept_id for p in principles],
            "schemas_considered": [s.schema_id for s in schemas],
            "strategy_constraints": constraints,
            "supporting_memories": await _memories_within(
                goal.description, constraints, pipeline),
        }
    except Exception as e:
        logger.debug("hierarchical context unavailable: %s", e)
        return {"available": False, "reason": str(e)}


#: Neutral confidence, used ONLY when nothing relevant has been measured.
#: Withheld both ways until earned — the same discipline as
#: `operating_reliability`, which reports 0.5 rather than guessing until it
#: has enough outcomes. It is paired with provenance saying it is unmeasured,
#: so a caller can tell "no evidence yet" from "evidence says 0.5".
UNMEASURED_CONFIDENCE: float = 0.5


def _task_tool_names(task: Task) -> List[str]:
    """The tools this task says it would use."""
    return [str(t) for t in ((task.metadata or {}).get("suggested_tools") or [])]


async def _measured_tool_metrics() -> Dict[str, Any]:
    """What the substrate has actually MEASURED about its tools — per-tool
    success rate and average latency.

    Read THROUGH THE LEARNING AUTHORITY, which owns what the substrate has
    learned and reads tool performance from what its experiences hold (the
    tool runs in its task and pursuit memories). The planner does not read
    memory behind its owner's back. Never invents: when nothing is held it
    says so, and the caller reports the absence."""
    try:
        from core.learning import get_learning_authority
        metrics = await get_learning_authority().get_learning_metrics()
        usage = (metrics or {}).get("tool_usage")
        if not usage:
            return {"available": False,
                    "reason": "the learning authority has no tool usage recorded"}
        return usage
    except Exception as e:
        logger.debug("tool metrics unavailable to the planner: %s", e)
        return {"available": False, "reason": str(e)}


async def _measured_plan_claims(
    tasks: List[Task]
) -> Tuple[float, float, Dict[str, Any]]:
    """(confidence, duration_minutes, provenance) for a template plan, read
    from measured tool history rather than constants.

    Confidence is the mean measured success rate of the tools these tasks
    would use; duration is their summed mean latency. Both report how they
    were derived, and when there is no history the provenance says
    `unmeasured` instead of a number pretending to be evidence.
    """
    metrics = await _measured_tool_metrics()
    provenance: Dict[str, Any] = {"planning_mode": "template"}
    if not metrics.get("available"):
        provenance.update({
            "confidence_source": "unmeasured",
            "duration_source": "unmeasured",
            "reason": metrics.get("reason") or metrics.get("error")
            or "no tool metrics available",
        })
        return UNMEASURED_CONFIDENCE, 0.0, provenance

    by_tool = {row["tool"]: row for row in (metrics.get("by_tool") or [])}
    rates: List[float] = []
    total_ms = 0.0
    measured_tools: List[str] = []
    for task in tasks:
        for name in _task_tool_names(task):
            row = by_tool.get(name)
            if not row:
                continue
            if row.get("success_rate") is not None:
                rates.append(float(row["success_rate"]))
            if row.get("avg_latency_ms") is not None:
                total_ms += float(row["avg_latency_ms"])
            measured_tools.append(name)

    if rates:
        confidence = round(sum(rates) / len(rates), 4)
        provenance["confidence_source"] = "measured_tool_success_rate"
        provenance["tools_measured"] = sorted(set(measured_tools))
    elif metrics.get("success_rate") is not None:
        # No per-tool history for these tools; the substrate's overall
        # measured success rate is still a real reading.
        confidence = float(metrics["success_rate"])
        provenance["confidence_source"] = "measured_overall_success_rate"
        provenance["runs"] = metrics.get("runs")
    else:
        confidence = UNMEASURED_CONFIDENCE
        provenance["confidence_source"] = "unmeasured"

    if total_ms > 0:
        duration = round(total_ms / 60000.0, 4)      # ms -> minutes
        provenance["duration_source"] = "measured_tool_latency"
    else:
        duration = 0.0
        provenance["duration_source"] = "unmeasured"
    return confidence, duration, provenance


def _suggest_tools_for_task(task_type: TaskType) -> List[str]:
    """Suggest appropriate tools for a task type"""
    tool_suggestions = {
        TaskType.RESEARCH: [
            "semantic_search",
            "grep_search",
            "read_file",
            "list_directory"
        ],
        TaskType.ANALYSIS: [
            "analyze_code",
            "grep_search",
            "read_file",
            "semantic_search"
        ],
        TaskType.EXECUTION: [
            "run_python",
            "run_shell_command",
            "execute_sandbox",
            "write_file"
        ],
        TaskType.VALIDATION: [
            "read_file",
            "run_python",
            "analyze_code"
        ],
        TaskType.SYNTHESIS: [
            "read_file",
            "write_file",
            "semantic_search"
        ]
    }

    suggested = tool_suggestions.get(task_type, [])
    available_tools = get_tool_registry().list_tools()

    # Return only tools that are actually registered
    return [tool for tool in suggested if tool in available_tools]


def _enhance_task_with_tools(task: Task) -> Task:
    """Enhance task with appropriate tool metadata"""
    suggested_tools = _suggest_tools_for_task(task.type)

    if suggested_tools:
        if not task.metadata:
            task.metadata = {}
        task.metadata["suggested_tools"] = suggested_tools
        task.metadata["tool_enabled"] = True

        logger.debug(f"Task '{task.description}' enhanced with {len(suggested_tools)} tool suggestions")

    return task


async def plan_described_goal(goal: Goal) -> "tuple[List[Task], Dict[str, Any]]":
    """A goal in words, decomposed: its steps, and what the plan may claim
    about itself -- confidence and duration MEASURED from the tools its steps
    would use, never invented, and the inputs a plan of this kind declares
    (tool history, abstraction, episodic memory), each from its owner, with
    what is missing reported as missing.

    Refused for a goal that states world conditions: that is planned by search,
    not decomposed into a template, and the guard is raised rather than
    returned so a caller can tell a refusal from a failure."""
    if goal.state_conditions:
        raise ValueError(
            f"goal {goal.id} states world conditions and must be planned by "
            f"search, not decomposed into a task template")
    tasks = await _generate_tasks_for_goal(goal, {})
    confidence, duration, claims = await _measured_plan_claims(tasks)
    claims["confidence"] = confidence
    claims["estimated_duration"] = duration
    claims["inputs"] = await assemble_inputs("template", goal, {})
    return tasks, claims
