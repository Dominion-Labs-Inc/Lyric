"""The whole loop, on the production path, with no model involved.

    persistent learned rule -> state goal -> temporal reasoning (grounding ->
    state search) -> the route recorded on its intent -> ordered task chain

Each severance below removes exactly one link and asserts the loop stops in the
way that link's absence should cause -- so a pass is evidence the link carries
the capability rather than merely accompanying it.

The route is planned by `TemporalReasoningSystem.plan_state_goal` and turned into
steps by the drive's own `_route_of`, which records it on the pursuit's intent.
No plan is stored to reload: the intent is the route's durable account, and the
drive walks the steps in order (`_pursue_proved_route`).
"""
import pytest
import pytest_asyncio

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
from core.agents.autonomous.execution_plan_adapter import (
    PlanValidationError, plan_described_goal, validate_task_chain,
)
from core.agents.autonomous.shared_types import Goal, Priority, Task, TaskType
from core.learning.rule_induction import Fact, TrainingExample, get_rule_inducer
from core.learning.rule_store import EpistemicStatus, RuleStore
# THE MODEL-FREE GUARD IS GONE, AND SO IS WHAT IT GUARDED AGAINST.
# These tests wrapped themselves in an autouse fixture that set
# `ModelPolicy.STRICT_MODEL_FREE` and asserted afterwards that no model had been
# called. `core.model_policy` was REMOVED when the substrate became model-free by
# CONSTRUCTION -- there is no longer a policy to set, because there is nothing to
# set it against. The guard's subject is gone; the subject of these tests is not,
# and they had been uncollectable ever since.
from core.reasoning.intent_authority import (
    IntentAuthority, SUBSTRATE_ACTOR, continuity_goal,
)
from core.reasoning.temporal_reasoning import PlanningStatus, TemporalReasoningSystem

F = Fact.parse
DOMAIN = "test_learn_plan_act"
PROBE = "LEARN_PLAN_ACT_TEST"

WORLD = ["AT(z, HALL)", "PATH(HALL, LAB)", "OPEN(LAB)",
         "PATH(LAB, VAULT)", "OPEN(VAULT)"]
GOAL_CONDITIONS = ["AT(z, VAULT)"]




def move(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
    before = []
    if at:
        before.append(F(f"AT({who},{a})"))
    if path:
        before.append(F(f"PATH({a},{b})"))
    if opened:
        before.append(F(f"OPEN({b})"))
    before = tuple(before)
    ok = opened and path and acted and at
    after = (tuple(f for f in before if f != F(f"AT({who},{a})"))
             + (F(f"AT({who},{b})"),)) if ok else before
    return TrainingExample(
        before=before, action=F(f"MOVE({who},{a},{b})") if acted else None,
        after=after, positive=ok, evidence_id=evidence_id)


TEACHING = [
    move("a", "R1", "R2", "t1"), move("b", "R3", "R4", "t2"),
    move("c", "R5", "R6", "n1", opened=False),
    move("d", "R7", "R8", "n2", path=False),
    move("e", "R9", "R10", "n3", acted=False),
    move("h", "R15", "R16", "n4", at=False),
]
HELD_OUT = [move("f", "R11", "R12", "h1"), move("g", "R13", "R14", "h2")]


@pytest_asyncio.fixture
async def substrate():
    """A validated, persisted learned rule, and the planner."""
    store = RuleStore()
    await store.ensure_schema()
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    yield TemporalReasoningSystem(), store, stored

    await store.db().execute_query(
        "DELETE FROM unified.rule_authority_events WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rule_evidence WHERE rule_id IN"
        " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query(
        "DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))


def _pursuit(description=f"{PROBE} reach the vault"):
    from uuid import uuid4
    return Task(id=f"{PROBE}_{uuid4().hex[:8]}", type=TaskType.EXECUTION,
                description=description, priority=Priority.HIGH)


async def _route(world=WORLD):
    """The route the drive would walk for the goal, planned the drive's one way
    (`_plan_route`), and the task pursuing it."""
    pursuing = _pursuit()
    outcome, route = await AutonomousCoordinator()._plan_route(
        pursuing, list(GOAL_CONDITIONS), list(world), DOMAIN)
    assert outcome.status is PlanningStatus.PLAN_FOUND, outcome.reason
    return pursuing, route


# ------------------------------------------------------------------ the loop

@pytest.mark.asyncio
async def test_a_state_goal_is_planned_by_search_not_templates(substrate):
    planner, _, _ = substrate
    _, route = await _route()

    assert route.metadata["planning_mode"] == "state"
    assert [t.description for t in route.tasks] == [
        "MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"]


@pytest.mark.asyncio
async def test_the_route_declares_what_it_was_formed_on(substrate):
    """A state plan says what it was formed on, each from its owner: the world
    it was proved against, the operators learned, and what has been earned in
    the domain. What could not be had is reported as missing, never filled."""
    planner, _, _ = substrate
    _, route = await _route()
    inputs = route.metadata["inputs"]

    assert inputs["kind"] == "state"
    assert inputs["required"] == ["observed_world", "learned_operators",
                                  "operating_reliability"]
    gathered = inputs["gathered"]
    assert gathered["observed_world"]["facts"] >= len(WORLD)
    assert gathered["learned_operators"]["source"] == "rule store"
    assert {m["input"] for m in inputs["missing"]} | set(gathered) == set(inputs["required"])


@pytest.mark.asyncio
async def test_the_task_chain_preserves_the_proof_order(substrate):
    planner, _, _ = substrate
    _, route = await _route()

    assert route.tasks[0].dependencies == []
    assert route.tasks[1].dependencies == [route.tasks[0].id]


@pytest.mark.asyncio
async def test_the_route_and_its_order_survive_on_its_intent(substrate):
    """The route's durable account is its intent. A fresh authority -- what a
    restarted process has -- reads back the operators in proof order and the
    rule that licenses them."""
    planner, _, stored = substrate
    pursuing, route = await _route()

    recorded = route.metadata["intent"]
    assert recorded.get("recorded"), recorded
    held = await IntentAuthority().get(SUBSTRATE_ACTOR,
                                       continuity_goal(f"{pursuing.id}:route"))
    assert held is not None and held.intent_id == recorded["intent_id"]
    assert held.shape["operators"] == ["MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"]
    assert held.shape["goal_conditions"] == GOAL_CONDITIONS
    assert stored.rule_id in held.shape["rule_ids"]
    assert held.proved and held.stated()
    assert all(t.provenance["intent_id"] == held.intent_id for t in route.tasks)


@pytest.mark.asyncio
async def test_provenance_traces_a_task_to_the_learned_rule(substrate):
    """Not only what Lyric did, but which acquired experience authorised it."""
    planner, _, stored = substrate
    pursuing, route = await _route()
    provenance = route.tasks[1].provenance

    assert provenance["learned_rule_id"] == stored.rule_id
    assert provenance["planning_mode"] == "state"
    assert provenance["goal_id"] == pursuing.id
    assert provenance["predecessor_task_id"] == route.tasks[0].id
    assert provenance["grounding_complete"] is True


# ------------------------------------------------------------------ severance

@pytest.mark.asyncio
async def test_demoting_the_rule_removes_the_capability(substrate):
    """The execution gate the ablation proved causal, reached through planning."""
    planner, store, stored = substrate
    await store.db().execute_query(
        "UPDATE unified.learned_rules SET epistemic_status = $1 WHERE rule_id = $2",
        (EpistemicStatus.SUPPORTED.value, stored.rule_id))

    outcome = await planner.plan_state_goal(list(GOAL_CONDITIONS), list(WORLD), DOMAIN)

    assert outcome.status is not PlanningStatus.PLAN_FOUND
    assert outcome.operators_considered == 0


@pytest.mark.asyncio
async def test_a_sealed_vault_is_unreachable_not_replanned_as_a_template(substrate):
    """The defect this whole design exists to prevent: an honest planning
    failure becoming Research -> Analyze -> Execute."""
    planner, _, _ = substrate
    sealed = [c for c in WORLD if c != "OPEN(VAULT)"]

    outcome = await planner.plan_state_goal(list(GOAL_CONDITIONS), sealed, DOMAIN)

    assert outcome.status is PlanningStatus.UNREACHABLE
    assert outcome.route is None


@pytest.mark.asyncio
async def test_truncated_grounding_reports_indeterminate_never_unreachable(substrate):
    """Unreached is not unreachable. Claiming impossibility from an operator set
    Lyric failed to enumerate would be a false proof about the world."""
    planner, _, _ = substrate

    from core.learning import rule_grounding

    real = rule_grounding.ground_for_problem

    def truncated(*args, **kwargs):
        report = real(*args, **kwargs)
        report.operators = []
        report.truncated = True
        return report

    rule_grounding.ground_for_problem = truncated
    try:
        outcome = await planner.plan_state_goal(list(GOAL_CONDITIONS), list(WORLD), DOMAIN)
    finally:
        rule_grounding.ground_for_problem = real

    assert outcome.status is PlanningStatus.INDETERMINATE
    assert outcome.status is not PlanningStatus.UNREACHABLE
    assert "not unreachable" in outcome.reason


@pytest.mark.asyncio
async def test_a_state_goal_is_refused_by_the_template_planner(substrate):
    """Mode is chosen by goal type. The decomposition of a goal in words must be
    unreachable for a state goal even when called directly, and it refuses by
    saying so rather than returning what a broken planner would."""
    goal = Goal(id=f"{PROBE}_state", description=f"{PROBE} reach the vault",
                priority=Priority.HIGH, state_conditions=list(GOAL_CONDITIONS))
    with pytest.raises(ValueError, match="must be planned by search"):
        await plan_described_goal(goal)


@pytest.mark.asyncio
async def test_a_descriptive_goal_still_uses_templates(substrate):
    goal = Goal(id=f"{PROBE}_words", description=f"{PROBE} research widgets",
                priority=Priority.LOW)

    steps, claims = await plan_described_goal(goal)
    assert claims["planning_mode"] == "template"
    assert steps, "a goal in words was decomposed into no work"


@pytest.mark.asyncio
async def test_a_state_goal_without_a_world_is_indeterminate(substrate):
    """Assuming an empty world would make every goal unreachable for a reason
    about the caller rather than the world."""
    planner, _, _ = substrate
    outcome = await planner.plan_state_goal(list(GOAL_CONDITIONS), None, DOMAIN)
    assert outcome.status is PlanningStatus.INDETERMINATE


# ---------------------------------------------------------- chain integrity

def _chain_task(identifier, dependencies):
    return Task(id=identifier, type=TaskType.EXECUTION, description=identifier,
                dependencies=list(dependencies))


def test_a_malformed_chain_is_refused_before_it_is_handed_on():
    with pytest.raises(PlanValidationError, match="duplicate"):
        validate_task_chain([_chain_task("a", []), _chain_task("a", [])])

    with pytest.raises(PlanValidationError, match="not in this plan"):
        validate_task_chain([_chain_task("a", ["ghost"])])

    with pytest.raises(PlanValidationError, match="depends on itself"):
        validate_task_chain([_chain_task("a", ["a"])])

    with pytest.raises(PlanValidationError, match="cycle"):
        validate_task_chain([_chain_task("a", ["b"]), _chain_task("b", ["a"])])


def test_a_valid_chain_passes():
    validate_task_chain([_chain_task("a", []), _chain_task("b", ["a"]),
                         _chain_task("c", ["b"])])
