"""The edge from a refuted rule to a pursuit that plans again.

The chain under test, end to end:

    runtime contradiction, attributable to the rule
      -> rule loses VALIDATED status                        (rule store)
      -> RuleAuthorityChanged written durably               (rule store)
      -> a step standing on that rule does not run          (each step re-reads its rule)
      -> the pursuit plans again over what is still validated (the drive)

Each link is checked on its own AND the chain is checked whole, because a
chain that only works when driven by hand is not wired. The two properties
that matter most are negative:

  * a contradiction the credit invariant refuses to charge to the rule must
    produce NO authority event, or infrastructure failure silently rewrites
    learned knowledge;
  * a pursuit plans again only when something is new: a walk that stops with
    its rules held and its world unchanged is not planned again.
"""
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
from core.agents.autonomous.shared_types import Plan, Task, TaskType
from core.intelligence.effect_verification import (
    Attribution, EffectVerdict, EffectVerification, Polarity, RuntimeEvidence,
    RuntimeOutcome, outcome_class_for,
)
from core.tools.tool_registry import get_binding_registry
from core.learning.rule_authority import (
    AuthorityCause, RuleAuthorityChanged, authority_history, record_authority_change,
)
from core.learning.rule_induction import Fact, get_rule_inducer
from core.learning.rule_store import (
    EpistemicStatus, RuleStore, confers_execution_authority,
)
# THE MODEL-FREE GUARD IS GONE, AND SO IS WHAT IT GUARDED AGAINST.
# These tests wrapped themselves in an autouse fixture that set
# `ModelPolicy.STRICT_MODEL_FREE` and asserted afterwards that no model had been
# called. `core.model_policy` was REMOVED when the substrate became model-free by
# CONSTRUCTION -- there is no longer a policy to set, because there is nothing to
# set it against. The guard's subject is gone; the subject of these tests is not,
# and they had been uncollectable ever since.

from tests.test_substrate_execution import (
    DOMAIN, HELD_OUT, LockedWorld, TEACHING, World, purge_domain, task_for,
)

PROBE = "authority_probe"




async def _purge(store):
    await purge_domain(store)


@pytest_asyncio.fixture
async def locked():
    """A world where MOVE into LAB silently does nothing: the rule predicts the
    move, the filesystem disagrees, and the disagreement is the rule's."""
    root = Path(tempfile.mkdtemp(prefix="lyric_authority_"))
    world = LockedWorld(root, ["HALL", "LAB"], [("HALL", "LAB")], locked={"LAB"})
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding())

    store = RuleStore()
    await store.ensure_schema()
    await purge_domain(store)
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    yield world, store, stored

    get_binding_registry().clear(DOMAIN)
    shutil.rmtree(root, ignore_errors=True)
    await _purge(store)


# ─────────────────────────────────────────────────── the event itself

@pytest.mark.asyncio
async def test_a_runtime_contradiction_writes_a_durable_authority_event(locked):
    """The whole point: the status change leaves a record something else can
    find, without the executor telling anyone."""
    world, store, stored = locked
    task = await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)")
    task.provenance["plan_id"] = "plan_probe"
    task.provenance["goal_id"] = "goal_probe"

    await AutonomousCoordinator().execute_task(task)

    events = await authority_history(store.db(), stored.rule_id)
    withdrawal = [e for e in events if e.lost_authority]
    assert len(withdrawal) == 1, f"expected exactly one withdrawal, got {events}"
    e = withdrawal[0]
    assert e.old_status is EpistemicStatus.VALIDATED
    assert e.new_status is EpistemicStatus.REFUTED
    assert e.cause is AuthorityCause.RUNTIME_CONTRADICTION
    assert e.task_id == task.id
    assert e.plan_id == "plan_probe"
    assert e.goal_id == "goal_probe"
    assert e.observation_id, "the event does not say which observation refuted it"


@pytest.mark.asyncio
async def test_validation_is_recorded_as_a_gain_not_a_loss(locked):
    """CANDIDATE -> VALIDATED is an authority change too, and reading it as a
    loss would invalidate plans every time a rule was learned."""
    _, store, stored = locked
    events = await authority_history(store.db(), stored.rule_id)
    promotion = [e for e in events if e.cause is AuthorityCause.VALIDATION]
    assert promotion, "validation emitted no authority event"
    assert promotion[0].gained_authority
    assert not promotion[0].lost_authority
    assert not confers_execution_authority(promotion[0].old_status)


@pytest.mark.asyncio
async def test_the_history_tells_a_gain_from_a_loss(locked):
    """A rule learned and a rule refuted are both on the record, and told apart:
    reading a gain as a loss would have the substrate abandon routes every time
    a rule was learned."""
    _, store, stored = locked
    await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    events = await authority_history(store.db(), stored.rule_id)
    assert [e.cause for e in events if e.gained_authority] == [AuthorityCause.VALIDATION]
    assert [e.cause for e in events if e.lost_authority] == [
        AuthorityCause.RUNTIME_CONTRADICTION]


@pytest.mark.asyncio
async def test_a_transition_to_the_same_status_is_not_an_event(locked):
    _, store, stored = locked
    with pytest.raises(ValueError):
        await record_authority_change(store.db(), RuleAuthorityChanged(
            rule_id=stored.rule_id,
            old_status=EpistemicStatus.VALIDATED,
            new_status=EpistemicStatus.VALIDATED,
            cause=AuthorityCause.VALIDATION,
        ))


@pytest.mark.asyncio
async def test_the_event_outlives_the_object_that_wrote_it(locked):
    """Durability is the reason this is an event and not a method call: a
    reader that was not running at the time must still find it."""
    _, store, stored = locked
    await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    fresh = RuleStore()
    await fresh.ensure_schema()
    found = await authority_history(fresh.db(), stored.rule_id)
    assert [e.rule_id for e in found if e.lost_authority] == [stored.rule_id]


# ─────────────────────────────────────────── the credit invariant holds

@pytest.mark.asyncio
async def test_an_unattributable_contradiction_changes_no_authority(locked):
    """A mismatch the credit invariant refuses to charge to the rule must not
    reach the authority log either. Otherwise a misbound tool rewrites what the
    substrate believes it knows."""
    from core.learning.rule_store import record_runtime_evidence

    _, store, stored = locked
    evidence = RuntimeEvidence(
        outcome=RuntimeOutcome.CONTRADICTION,
        rule_id=stored.rule_id, operator="SBMOVE(z, HALL, LAB)",
        observation_id="obs_infra",
        verifications=[EffectVerification(
            predicted_effect=Fact("AT", ("z", "LAB")), polarity=Polarity.ADD,
            verdict=EffectVerdict.CONTRADICTED, observation_id="obs_infra")],
        detail="tool was misbound",
    )
    status = await record_runtime_evidence(
        store, evidence, Attribution.EXECUTION_FAILURE, "wrong tool")

    assert status is None
    reloaded = next(r for r in await store.load(domain_id=DOMAIN)
                    if r.rule_id == stored.rule_id)
    assert reloaded.status is EpistemicStatus.VALIDATED
    assert not [e for e in await authority_history(store.db(), stored.rule_id)
                if e.cause is AuthorityCause.RUNTIME_CONTRADICTION]


@pytest.mark.parametrize("attribution,outcome,expected", [
    (Attribution.RULE_EVIDENCE, RuntimeOutcome.CONTRADICTION, "strategy_failure"),
    (Attribution.RULE_EVIDENCE, RuntimeOutcome.CONFIRMATION, "success"),
    (Attribution.EXECUTION_FAILURE, RuntimeOutcome.CONTRADICTION, "execution_failure"),
    (Attribution.EXTERNAL_FAILURE, RuntimeOutcome.CONTRADICTION, "external_failure"),
    (Attribution.INDETERMINATE, RuntimeOutcome.INDETERMINATE, "indeterminate"),
])
def test_only_rule_evidence_reaches_the_strategy(attribution, outcome, expected):
    """The translation into credit vocabulary must never let an infrastructure
    failure arrive as a strategy failure — that is what would produce replan
    pressure against a rule that was right."""
    evidence = RuntimeEvidence(outcome=outcome, rule_id="r", operator="MOVE",
                               observation_id="o")
    assert outcome_class_for(evidence, attribution).value == expected


# ─────────────────────────────── a pursuit standing on it plans again

def _route_on(rule_ids, world):
    """A route as the drive holds it for a walk: the rules it stood on and the
    world it was proved from, as the drive read it."""
    return Plan(id=f"route_{uuid4().hex[:8]}", goal_id=f"{PROBE}_goal", tasks=[],
                metadata={"rule_ids": list(rule_ids),
                          "planned_world": sorted(str(f) for f in world.observe())})


@pytest.mark.asyncio
async def test_a_stop_with_nothing_new_is_not_planned_again(locked):
    """Planning again must be driven by something new, not run every time a walk
    stops: the same search over the same rules from the same world would find
    the same route."""
    world, _, stored = locked
    route = _route_on([stored.rule_id], world)

    assert await AutonomousCoordinator()._worth_planning_again(
        route, DOMAIN, {"success": False, "steps": []}) is None


@pytest.mark.asyncio
async def test_a_route_whose_rule_was_refuted_is_planned_again(locked):
    """The far end of the edge. Without this the refutation is correct and the
    goal is stuck forever, which is a worse failure than the one it fixed."""
    world, _, stored = locked
    route = _route_on([stored.rule_id], world)

    await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    again = await AutonomousCoordinator()._worth_planning_again(
        route, DOMAIN, {"success": False, "steps": []})
    assert again is not None, "a route on a refuted rule was not planned again"
    why, refused_act = again
    assert stored.rule_id in why and "lost its authority" in why
    assert refused_act is None, "a refuted rule is gone from the search; no act is left out"


@pytest.mark.asyncio
async def test_a_route_on_other_rules_is_not_planned_again_for_this_loss(locked):
    """One refuted rule must not send back routes that never stood on it."""
    world, store, stored = locked
    await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert stored.rule_id not in {
        r.rule_id for r in await store.executable_rules(domain_id=DOMAIN)}

    route = _route_on([], world)
    assert await AutonomousCoordinator()._worth_planning_again(
        route, DOMAIN, {"success": False, "steps": []}) is None


@pytest.mark.asyncio
async def test_the_pursuit_plans_again_inside_itself_when_its_rule_is_refuted(locked):
    """End to end, through the one pursuer: the drive proves a route, walks it,
    the world refutes the rule, and the same pursuit plans again over what is
    still validated -- which here is nothing, so it ends with an honest verdict
    rather than stopping at the failed step or leaving the goal to anyone else."""
    world, store, stored = locked
    goal = Task(id=f"{PROBE}_{uuid4().hex[:8]}", type=TaskType.EXECUTION,
                description="put z in the lab",
                provenance={"goal_conditions": ["SBAT(z, LAB)"], "domain_id": DOMAIN})

    result = await AutonomousCoordinator().execute_task(goal)

    assert result["success"] is False
    assert [e for e in await authority_history(store.db(), stored.rule_id)
            if e.lost_authority], "the walk never reached the world"
    assert result.get("planning_status") in ("unreachable", "indeterminate"), (
        f"the pursuit did not plan again after its rule was refuted: {result}")
    assert result.get("operators_considered") == 0


# ──────────────────────────────────────────────── appraisal gets the signal

async def _appraise_one_execution(world, store, stored, operator="SBMOVE(z, HALL, LAB)"):
    """Run one substrate execution against a FRESH appraisal and return what it
    left behind. Fresh, because appraisal blends with its previous state and a
    disposition carried in from another test would not be this execution's."""
    from core.agents.autonomous.appraisal import AppraisalSystem
    import core.agents.autonomous.appraisal as appraisal_module

    previous = appraisal_module._appraisal_system
    appraisal_module._appraisal_system = AppraisalSystem()
    try:
        result = await AutonomousCoordinator().execute_task(
            await task_for(stored.rule_id, operator))
        return result, appraisal_module._appraisal_system.current_state
    finally:
        appraisal_module._appraisal_system = previous


@pytest_asyncio.fixture
async def wrong_destination():
    """The tool SUCCEEDS and the world moves — just not where the rule said.

    This is the case the whole design turns on: execution machinery worked
    perfectly and the learned model was wrong. Anything that reads a
    contradiction off tool failure would see nothing here."""
    root = Path(tempfile.mkdtemp(prefix="lyric_authority_wrong_"))
    world = World(root, ["HALL", "LAB", "VAULT"], [("HALL", "LAB"), ("LAB", "VAULT")])
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding(destination_override="VAULT"))

    store = RuleStore()
    await store.ensure_schema()
    await purge_domain(store)
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    yield world, store, stored

    get_binding_registry().clear(DOMAIN)
    shutil.rmtree(root, ignore_errors=True)
    await _purge(store)


@pytest.mark.asyncio
async def test_a_disproved_prediction_raises_replan_pressure(wrong_destination):
    """`should_replan` had no producer on the substrate path at all: acting on
    proved knowledge left disposition untouched, including when the proof was
    wrong.

    The two signals must stay apart here — the tool reported success (we can
    act) while the prediction failed (this route is wrong). That combination is
    exactly what replanning means.
    """
    from core.agents.autonomous.behavior_arbiter import ACT_THRESHOLD, get_behavior_arbiter

    world, store, stored = wrong_destination
    result, state = await _appraise_one_execution(world, store, stored)

    assert result["runtime_outcome"] == "runtime_contradiction"
    assert (world.root / "VAULT" / "z").exists(), "the tool did not actually act"
    assert state is not None, "the substrate path reported nothing to appraisal"
    assert state.attribution == "strategy_failure"
    assert state.controllability == 1.0, "a working tool must not read as no control"

    directive = get_behavior_arbiter().decide(state)
    assert directive.replan >= ACT_THRESHOLD, (
        f"replan pressure {directive.replan:.3f} did not clear {ACT_THRESHOLD}")
    assert directive.should_replan is True
    # Not asserting `mode == "replan"`. With no epistemic measurement on this
    # path, exploration outranks it, and inventing an uncertainty_increase here
    # to change the ranking would fabricate a measurement whose owner is
    # summarize_epistemic_mutations. should_replan is the signal under test.


@pytest.mark.asyncio
async def test_an_action_the_world_refuses_escalates_instead_of_replanning(locked):
    """Both are contradictions; they are not the same situation.

    When the world will not carry out the action at all, planning another route
    through the same operator is not the response — the rule still loses its
    authority, but disposition says escalate rather than replan. Collapsing the
    two would make every contradiction demand a replan.
    """
    from core.agents.autonomous.behavior_arbiter import ACT_THRESHOLD, get_behavior_arbiter

    world, store, stored = locked
    result, state = await _appraise_one_execution(world, store, stored)

    assert result["runtime_outcome"] == "runtime_contradiction"
    assert state.attribution == "strategy_failure"
    assert state.controllability == 0.0, "the tool refused; that is no control"

    directive = get_behavior_arbiter().decide(state)
    assert directive.replan < ACT_THRESHOLD
    assert directive.escalation > directive.replan

    # The rule still loses authority. Disposition decides the response; it does
    # not decide what the evidence established.
    assert [e for e in await authority_history(store.db(), stored.rule_id)
            if e.lost_authority]


@pytest.mark.asyncio
async def test_a_confirmed_rule_does_not_ask_for_replanning():
    """The control: a world that moves as predicted must not produce replan
    pressure, or the signal means nothing."""
    from core.agents.autonomous.appraisal import AppraisalSystem
    from core.agents.autonomous.behavior_arbiter import get_behavior_arbiter
    import core.agents.autonomous.appraisal as appraisal_module

    root = Path(tempfile.mkdtemp(prefix="lyric_authority_ok_"))
    world = World(root, ["HALL", "LAB"], [("HALL", "LAB")])
    world.place("z", "HALL")
    get_binding_registry().register(DOMAIN, world.binding())
    store = RuleStore()
    await store.ensure_schema()
    await purge_domain(store)
    stored = (await store.record_induction(
        get_rule_inducer().induce(TEACHING), TEACHING,
        domain_id=DOMAIN, rule_kind="move"))[0]
    await store.validate(stored, HELD_OUT)

    previous = appraisal_module._appraisal_system
    appraisal_module._appraisal_system = AppraisalSystem()
    try:
        result = await AutonomousCoordinator().execute_task(
            await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
        state = appraisal_module._appraisal_system.current_state
    finally:
        appraisal_module._appraisal_system = previous
        get_binding_registry().clear(DOMAIN)
        shutil.rmtree(root, ignore_errors=True)
        await _purge(store)

    assert result["success"] is True
    assert state.attribution == "success"
    assert get_behavior_arbiter().decide(state).should_replan is False
