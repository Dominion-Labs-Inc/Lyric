"""A goal is its intent: it survives the process, it is ranked from what it
says about itself, and a write that fails says so.

Goals used to be rows in a planning engine's own tables, beside the intent and
the task that already said what is being pursued and why. Those tables never
persisted for the module's first lifetime: they declared types the deployed
schema did not have, every INSERT failed, and four `except -> logger.error`
handlers reported success. The engine is gone and the goal is formed through
the intent authority, with how much it matters on its shape
(`AutonomousCoordinator._goal_shape`), where the ranking of the substrate's own
goals reads it (`IntentAuthority.ranked_own_goals`).

The persistence claim and the honesty claim are equally load-bearing. A store
that silently drops writes is survivable if someone notices; one that reports
success while dropping them cannot be noticed at all.
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
from core.agents.autonomous.shared_types import PRIORITY_ORDINAL, Goal, Priority
from core.reasoning.intent_authority import (
    IntentAuthority, IntentStore, SUBSTRATE_ACTOR, continuity_goal,
)

PROBE = "GOAL_INTENTS_TEST"


@pytest_asyncio.fixture
async def formed():
    """Forms the substrate's own goals as intents, and removes them after."""
    made = []
    authority = IntentAuthority()

    async def form(priority, potential=None, *, conditions=None, deadline=None,
                   shape=True):
        values = {} if potential is None else {"intrinsic_reward_potential": potential}
        goal = Goal(id=f"{PROBE}_{uuid4().hex[:8]}", description=f"{PROBE} goal",
                    priority=priority, deadline=deadline,
                    state_conditions=conditions, **values)
        intent = await authority.form(
            "self_goal", SUBSTRATE_ACTOR, continuity_goal(goal.id),
            shape=AutonomousCoordinator._goal_shape(goal) if shape else {"pursuit": "probe"},
            content={"aim": goal.description})
        made.append(intent.intent_id)
        return goal, intent

    yield authority, form

    db = authority.store.db
    await db.execute_query(
        "DELETE FROM unified.scoped_intents WHERE intent_id = ANY($1::text[])",
        (made,), commit=True)
    await db.execute_query(
        "DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])",
        (made,), commit=True)


def _ours(ranked, intents):
    ids = [i.intent_id for i in intents]
    return [i.intent_id for i in ranked if i.intent_id in ids]


# ------------------------------------------------------------------- ordinals

def test_priority_has_one_ordinal_authority():
    """Two independent answers about whether HIGH outranks MEDIUM is a defect
    waiting."""
    assert PRIORITY_ORDINAL[Priority.LOW] < PRIORITY_ORDINAL[Priority.MEDIUM]
    assert PRIORITY_ORDINAL[Priority.MEDIUM] < PRIORITY_ORDINAL[Priority.HIGH]
    assert PRIORITY_ORDINAL[Priority.HIGH] < PRIORITY_ORDINAL[Priority.CRITICAL]
    assert set(PRIORITY_ORDINAL) == set(Priority)


# ---------------------------------------------------------------- persistence

@pytest.mark.asyncio
async def test_a_goal_reaches_the_store_as_its_intent(formed):
    """What the goal says about itself is on the intent a fresh authority --
    what a restarted process has -- reads back."""
    _, form = formed
    by = datetime(2026, 11, 1, 12, 0)
    goal, intent = await form(Priority.HIGH, 0.8, conditions=["AT(z, VAULT)"], deadline=by)

    held = await IntentAuthority().get_by_id(intent.intent_id)
    assert held is not None, "the goal was formed and nothing was written"
    assert held.origin_kind == "self_goal"
    assert held.shape["priority"] == Priority.HIGH.value
    assert held.shape["deadline"] == by.isoformat()
    assert held.goal_conditions == ["AT(z, VAULT)"]
    assert held.shape["intrinsic"]["intrinsic_reward_potential"] == 0.8
    assert held.status in ("forming", "active")
    full = await IntentAuthority().get(SUBSTRATE_ACTOR, continuity_goal(goal.id))
    assert full is not None and full.aim == goal.description


@pytest.mark.asyncio
async def test_a_goal_set_without_an_estimate_carries_the_goal_default(formed):
    """The intrinsic values are the goal's own, defaults included, so the ranking
    never has to invent one."""
    _, form = formed
    goal, intent = await form(Priority.MEDIUM)
    held = await IntentAuthority().get_by_id(intent.intent_id)
    assert held.shape["intrinsic"]["intrinsic_reward_potential"] == \
        goal.intrinsic_reward_potential


# -------------------------------------------------------------------- ranking

@pytest.mark.asyncio
async def test_own_goals_are_ranked_by_priority_and_intrinsic_reward(formed):
    authority, form = formed
    _, low = await form(Priority.LOW, 0.9)
    _, high = await form(Priority.HIGH, 0.1)
    _, critical = await form(Priority.CRITICAL, 0.5)
    mine = [low, high, critical]

    # 0.7 x the priority's rank (a quarter to whole) + 0.3 x intrinsic reward:
    # LOW .445, HIGH .555, CRITICAL .85.
    assert _ours(await authority.ranked_own_goals(), mine) == [
        critical.intent_id, high.intent_id, low.intent_id]
    # Intrinsic motivation alone puts the curious LOW goal first.
    assert _ours(await authority.ranked_own_goals(intrinsic_weight=1.0), mine) == [
        low.intent_id, critical.intent_id, high.intent_id]


@pytest.mark.asyncio
async def test_a_concluded_goal_is_not_ranked(formed):
    authority, form = formed
    _, done = await form(Priority.CRITICAL, 1.0)
    _, open_ = await form(Priority.LOW, 0.1)
    await authority.reconcile(done.intent_id, {"outcome_class": "success"},
                              status="fulfilled")

    assert _ours(await authority.ranked_own_goals(), [done, open_]) == [open_.intent_id]


@pytest.mark.asyncio
async def test_a_pursuit_that_is_no_goal_is_not_ranked(formed):
    """Work the substrate took on with no priority set -- a repair, an answered
    question -- is not one of its goals to rank."""
    authority, form = formed
    _, pursuit = await form(Priority.MEDIUM, shape=False)
    assert _ours(await authority.ranked_own_goals(), [pursuit]) == []


# -------------------------------------------------------------------- honesty

@pytest.mark.asyncio
async def test_a_store_that_rejects_the_write_raises_instead_of_returning():
    """A goal the store rejected must not come back as though it were held."""
    store = IntentStore()

    async def rejected(_intent):
        raise RuntimeError("write rejected")

    store.create = rejected
    with pytest.raises(RuntimeError, match="write rejected"):
        await IntentAuthority(store).form(
            "self_goal", SUBSTRATE_ACTOR, continuity_goal(f"{PROBE}_{uuid4().hex[:8]}"),
            shape=AutonomousCoordinator._goal_shape(
                Goal(id="never", description="never", priority=Priority.LOW,
                     deadline=datetime.now() + timedelta(days=1))))


# ------------------------------------------- carrying out a goal in words

def test_carrying_out_is_earned_only_for_the_pursuit_being_walked(tmp_path):
    """Law 2's CARRY_OUT account is checked against what the acting side does not
    control: a goal in words being walked right now, the account a child of that
    pursuit's intent, and the file it names the one the goal's own words name."""
    from core.agents.autonomous.autonomous_coordinator import get_constitution
    from core.reasoning.intent_authority import Intent

    coord = AutonomousCoordinator()
    target = str(tmp_path / "findings.md")
    coord._walking["plan_walked"] = {
        "description": f"Research pumps and write a summary at {target}",
        "intent_id": "pursuit_walked"}

    def account(parent="pursuit_walked", artefact=target, plan="plan_walked"):
        return Intent(intent_id="account", origin_kind="goal", actor="",
                      continuity_key="", parent_intent_id=parent,
                      shape={"purpose": "carry_out", "plan_id": plan,
                             "artefact": artefact})

    law = get_constitution()
    try:
        assert law._carrying_out_is_earned(account())
        assert law._carrying_out_is_earned(account(artefact=str(tmp_path / "other.md"))) is None
        assert law._carrying_out_is_earned(account(parent="someone_elses")) is None
        assert law._carrying_out_is_earned(account(plan="not_walked")) is None
    finally:
        coord._walking.pop("plan_walked", None)
    assert law._carrying_out_is_earned(account()) is None, (
        "an account outlived the walk it was made for")
