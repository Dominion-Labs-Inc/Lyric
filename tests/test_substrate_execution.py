"""Acting on a real world and checking the learned model against it.

THE INVARIANT these exist to protect:

    Predictions may define WHAT to test, but may never construct the
    observation used to confirm themselves.

The observation is produced by reading the actual filesystem, never by applying
the rule's own add/delete effects to a symbolic state. The contradiction test is
the proof: if observations were built from predictions, a contradiction could
not occur.

`runtime_confirmation` must also not be the generic success branch. A tool that
returns cleanly while the world does not move is INDETERMINATE, and a world
that moves the wrong way is CONTRADICTION.
"""
import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
from core.agents.autonomous.shared_types import Task, TaskType
from core.intelligence.effect_verification import (
    EffectVerdict, Polarity, RuntimeOutcome, ToolObservation, verify_effects,
)
from core.tools.tool_registry import OperatorBinding, get_binding_registry
from core.learning.rule_induction import Fact, RuleEffects, TrainingExample, get_rule_inducer
from core.learning.rule_store import EpistemicStatus, RuleStore
F = Fact.parse
DOMAIN = "test_substrate_exec"


# The substrate execution path is model-free BY CONSTRUCTION: core/model_policy.py
# was removed and no model handle exists on this path to call. The old autouse
# `strict` fixture asserted model-freeness through that now-deleted guard; it is
# obsolete, not weakened — there is nothing left that could reach a model here.


class World:
    """Rooms are directories, the agent is a file, MOVE is the move_file tool."""

    def __init__(self, root, rooms, paths):
        self.root, self.rooms, self.paths = root, list(rooms), list(paths)
        self.readable = True
        for r in self.rooms:
            (self.root / r).mkdir(parents=True, exist_ok=True)

    def place(self, agent, room):
        (self.root / room / agent).write_text("")

    def observe(self):
        """Reads the FILESYSTEM. Never consults a rule or a prediction."""
        if not self.readable or not self.root.exists():
            return None
        facts = set()
        for room in self.rooms:
            d = self.root / room
            if not d.is_dir():
                continue
            facts.add(Fact("SBOPEN", (room,)))
            for entry in d.iterdir():
                if entry.is_file():
                    facts.add(Fact("SBAT", (entry.name, room)))
        for a, b in self.paths:
            facts.add(Fact("SBPATH", (a, b)))
        return frozenset(facts)

    def binding(self, destination_override=None):
        def parameters(args):
            agent, origin, destination = args
            return {
                "source_path": str(self.root / origin / agent),
                "destination_path": str(
                    self.root / (destination_override or destination) / agent),
                "create_dirs": False,
            }

        return OperatorBinding(predicate="SBMOVE", tool_name="move_file",
                               parameters=parameters, observe=self.observe)


def move(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
    before = []
    if at:
        before.append(F(f"SBAT({who},{a})"))
    if path:
        before.append(F(f"SBPATH({a},{b})"))
    if opened:
        before.append(F(f"SBOPEN({b})"))
    before = tuple(before)
    ok = opened and path and acted and at
    after = (tuple(f for f in before if f != F(f"SBAT({who},{a})"))
             + (F(f"SBAT({who},{b})"),)) if ok else before
    return TrainingExample(
        before=before, action=F(f"SBMOVE({who},{a},{b})") if acted else None,
        after=after, positive=ok, evidence_id=evidence_id)


TEACHING = [
    move("a", "R1", "R2", "t1"), move("b", "R3", "R4", "t2"),
    move("c", "R5", "R6", "n1", opened=False),
    move("d", "R7", "R8", "n2", path=False),
    move("e", "R9", "R10", "n3", acted=False),
    move("h", "R15", "R16", "n4", at=False),
]
HELD_OUT = [move("f", "R11", "R12", "h1"), move("g", "R13", "R14", "h2")]


async def purge_domain(store):
    """Remove what a test's runs wrote under DOMAIN. Every test is its own world under one domain name, and what one
    left must not judge the next one's rule: re-judgement holds a rule against every demonstration of its act in its
    domain, so the demonstrations a test's acts kept go, with the pending marks, the rules and their evidence. The
    induction passes those acts woke finish first: one still running writes a rule's evidence while it is deleted."""
    drains = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()
              and getattr(task.get_coro(), "__name__", "") == "_coalesced_induction_drain"]
    await asyncio.gather(*drains)
    for table in ("unified.rule_authority_events", "unified.learned_rule_evidence"):
        await store.db().execute_query(
            f"DELETE FROM {table} WHERE rule_id IN"
            " (SELECT rule_id FROM unified.learned_rules WHERE domain_id = $1)", (DOMAIN,))
    await store.db().execute_query("DELETE FROM unified.learned_rules WHERE domain_id = $1", (DOMAIN,))
    for table in ("unified.operator_demonstrations", "unified.operator_induction_pending"):
        await store.db().execute_query(f"DELETE FROM {table} WHERE domain_id = $1", (DOMAIN,))


@pytest_asyncio.fixture
async def world_and_rule():
    root = Path(tempfile.mkdtemp(prefix="lyric_test_world_"))
    world = World(root, ["HALL", "LAB", "VAULT"], [("HALL", "LAB"), ("LAB", "VAULT")])
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
    await purge_domain(store)


async def task_for(rule_id, operator, domain=DOMAIN):
    """One step of a proved plan, shaped the way the planner shapes one.

    THE INTENT IS NOT DECORATION IN THE PROVENANCE. `state_plan_to_tasks` stamps
    `intent_id` onto every step it makes, and the constitution reads it at the
    gate: Law 2 replans an act nothing can explain, and Law 4 checks the act is
    the one the proved route named. This fixture predates the constitution going
    live and assembled a task the substrate never produces -- a grounded
    operator with no account behind it -- so every test here was refused before
    the executor ran, and the whole module reported `KeyError: 'runtime_outcome'`
    for an act that never happened.

    The account is RECORDED, not asserted: `judge` fetches the intent by id from
    the authority and a name pointing at nothing is judged as no intent at all.
    So this forms a real one, with the goal state the rule's effect reaches --
    which is what makes the task legible to Law 4's operator check too.
    """
    from core.reasoning.intent_authority import (
        SUBSTRATE_ACTOR, continuity_goal, get_intent_authority)

    who, _origin, destination = [
        arg.strip() for arg in operator.split("(", 1)[1].rstrip(")").split(",")]
    intent = await get_intent_authority().form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"{domain}:{uuid4().hex}"),
        shape={
            # True for the same reason the planner records it: the route was
            # found over an operator the rule store attests is executable.
            "proved": True,
            "operator": operator, "operators": [operator], "steps": 1,
            # What the act is FOR. The proved destination, not wherever a
            # misbehaving world actually puts the file -- a world that moves the
            # wrong way contradicts the rule, which is the point of that test.
            "goal_conditions": [f"SBAT({who}, {destination})"],
            "rule_ids": [rule_id], "domain": domain,
        })
    return Task(id=f"task_{operator}", type=TaskType.EXECUTION, description=operator,
                provenance={"learned_rule_id": rule_id, "grounded_operator": operator,
                            "domain_id": domain, "intent_id": intent.intent_id})


# ------------------------------------------------------------ non-circularity

@pytest.mark.asyncio
async def test_the_observation_comes_from_the_world_not_the_prediction(world_and_rule):
    world, _, stored = world_and_rule
    result = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    assert result["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
    # The physical check, independent of anything the substrate believes.
    assert (world.root / "LAB" / "z").exists()
    assert not (world.root / "HALL" / "z").exists()
    assert Fact("SBAT", ("z", "LAB")) in world.observe()


@pytest.mark.asyncio
async def test_a_world_that_moves_the_wrong_way_contradicts(world_and_rule):
    """The proof of non-circularity: if the observation were constructed from
    the rule's own effects, this could not fail."""
    world, _, stored = world_and_rule
    # The tool succeeds, but sends the agent somewhere the rule did not predict.
    get_binding_registry().register(DOMAIN, world.binding(destination_override="VAULT"))

    result = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    assert result["runtime_outcome"] == RuntimeOutcome.CONTRADICTION.value
    assert result["success"] is False, "a clean tool call is not a confirmed model"
    added = [e for e in result["effects"] if e["polarity"] == "add"][0]
    assert added["verdict"] == EffectVerdict.CONTRADICTED.value
    assert (world.root / "VAULT" / "z").exists()


@pytest.mark.asyncio
async def test_an_unobservable_world_is_indeterminate_not_confirmation(world_and_rule):
    """Execution occurred; whether the model held cannot be established."""
    world, _, stored = world_and_rule
    executor = AutonomousCoordinator()

    original = world.observe
    calls = {"n": 0}

    def observe():
        calls["n"] += 1
        return original() if calls["n"] == 1 else None

    get_binding_registry().register(
        DOMAIN, OperatorBinding(predicate="SBMOVE", tool_name="move_file",
                                parameters=world.binding().parameters, observe=observe))

    result = await executor.execute_task(await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert result["runtime_outcome"] == RuntimeOutcome.INDETERMINATE.value
    assert result["success"] is False
    assert all(e["verdict"] == EffectVerdict.UNKNOWN.value for e in result["effects"])


# ---------------------------------------------------------------- refusals

@pytest.mark.asyncio
async def test_absent_preconditions_prevent_any_tool_call(world_and_rule):
    """Authorization is re-checked against the OBSERVED world, and a refusal
    must not touch it."""
    world, _, stored = world_and_rule
    result = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, LAB, VAULT)"))  # z is in HALL

    assert result["success"] is False
    # The refusal names the literal that failed rather than the set that did
    # not match: the preconditions are matched against the observed world one
    # at a time, so which one is absent is known and worth saying.
    assert "SBAT(z, LAB)" in result["refused"]
    assert "does not hold in the observed world" in result["refused"]
    assert (world.root / "HALL" / "z").exists(), "the world was touched on a refusal"
    assert not (world.root / "VAULT" / "z").exists()


@pytest.mark.asyncio
async def test_a_rule_demoted_after_planning_does_not_execute(world_and_rule):
    """t0 VALIDATED and planned, t1 demoted, t2 executes. The plan's
    authorization is not an argument at t2."""
    world, store, stored = world_and_rule
    await store.db().execute_query(
        "UPDATE unified.learned_rules SET epistemic_status = $1 WHERE rule_id = $2",
        (EpistemicStatus.SUPPORTED.value, stored.rule_id))

    result = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))

    # It fails CLOSED. Falling through to the model would let a step the
    # substrate refused be carried out by generation instead.
    assert result["success"] is False
    assert "not validated" in result["refused"]
    assert (world.root / "HALL" / "z").exists()


# -------------------------------------------------------------- composition

@pytest.mark.asyncio
async def test_two_steps_compose_through_the_real_world(world_and_rule):
    """Step B must be authorized from the OBSERVED S1, not the planner's
    predicted S1."""
    world, _, stored = world_and_rule
    executor = AutonomousCoordinator()

    first = await executor.execute_task(await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert first["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
    assert Fact("SBAT", ("z", "LAB")) in world.observe()

    second = await executor.execute_task(await task_for(stored.rule_id, "SBMOVE(z, LAB, VAULT)"))
    assert second["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value

    final = world.observe()
    assert Fact("SBAT", ("z", "VAULT")) in final
    assert Fact("SBAT", ("z", "HALL")) not in final
    assert Fact("SBAT", ("z", "LAB")) not in final
    assert (world.root / "VAULT" / "z").exists()


@pytest.mark.asyncio
async def test_the_second_step_survives_a_restart(world_and_rule):
    """A fresh executor and a fresh rule store between A and B. The authority
    for B is recovered from persistence and re-derived from the world."""
    world, _, stored = world_and_rule

    first = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert first["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value

    reloaded = [r for r in await RuleStore().executable_rules(domain_id=DOMAIN)
                if r.rule_id == stored.rule_id]
    assert reloaded, "the rule did not survive to authorize the second step"

    second = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, LAB, VAULT)"))
    assert second["runtime_outcome"] == RuntimeOutcome.CONFIRMATION.value
    assert (world.root / "VAULT" / "z").exists()


# ------------------------------------------------------- verification units

def test_a_successful_tool_call_alone_confirms_nothing():
    """The distinction that stops a rule accumulating support from its own
    invocation."""
    observation = ToolObservation(
        observation_id="o1", tool_name="t", invoked=True,
        tool_reported_success=True, observed=False)
    evidence = verify_effects(
        RuleEffects(add={Fact("SBAT", ("z", "LAB"))}), observation)
    assert evidence.outcome is RuntimeOutcome.INDETERMINATE


def test_add_and_delete_are_verified_independently():
    """ADD confirmed / DELETE contradicted is a different fact from either
    alone, and must not flatten to one boolean."""
    observation = ToolObservation(
        observation_id="o2", tool_name="t", invoked=True,
        tool_reported_success=True, observed=True,
        facts=frozenset({Fact("SBAT", ("z", "LAB")), Fact("SBAT", ("z", "HALL"))}))
    evidence = verify_effects(RuleEffects(
        add={Fact("SBAT", ("z", "LAB"))}, delete={Fact("SBAT", ("z", "HALL"))}), observation)

    verdicts = {v.polarity: v.verdict for v in evidence.verifications}
    assert verdicts[Polarity.ADD] is EffectVerdict.CONFIRMED
    assert verdicts[Polarity.DELETE] is EffectVerdict.CONTRADICTED
    assert evidence.outcome is RuntimeOutcome.CONTRADICTION


# ------------------------------------------------- autonomous epistemic loop

class LockedWorld(World):
    """A world with a condition the rule was never taught: locked rooms refuse
    entry, and the actuator reports success anyway."""

    def __init__(self, root, rooms, paths, locked):
        super().__init__(root, rooms, paths)
        self.locked = set(locked)

    def observe(self):
        facts = super().observe()
        if facts is None:
            return None
        return facts | {Fact("LOCKED", (r,)) for r in self.locked
                        if (self.root / r).is_dir()}

    def binding(self, destination_override=None):
        def parameters(args):
            agent, origin, destination = args
            target = origin if destination in self.locked else destination
            return {"source_path": str(self.root / origin / agent),
                    "destination_path": str(self.root / target / agent),
                    "create_dirs": False}
        return OperatorBinding("SBMOVE", "move_file", parameters, self.observe)


@pytest_asyncio.fixture
async def locked_world():
    root = Path(tempfile.mkdtemp(prefix="lyric_locked_"))
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
    await purge_domain(store)


@pytest.mark.asyncio
async def test_the_executor_itself_closes_the_loop(locked_world):
    """One execute_task call. Nothing else touches evidence or status.

    Reality violates a prediction, the contradiction becomes durable evidence,
    attribution charges it to the rule, and the rule loses execution authority
    -- without anything outside the executor intervening.
    """
    from core.intelligence.effect_verification import Attribution, RuntimeOutcome
    from core.learning.rule_store import EvidenceRole

    world, store, stored = locked_world
    task = await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)")

    result = await AutonomousCoordinator().execute_task(task)

    assert result["runtime_outcome"] == RuntimeOutcome.CONTRADICTION.value
    assert result["attribution"] == Attribution.RULE_EVIDENCE.value
    assert result["rule_status_after"] == EpistemicStatus.REFUTED.value

    reloaded = [r for r in await store.load(domain_id=DOMAIN)
                if r.rule_id == stored.rule_id][0]
    assert reloaded.status is EpistemicStatus.REFUTED
    roots = await store.evidence_roots(
        stored.rule_id, {EvidenceRole.RUNTIME_CONTRADICTION})
    assert result["observation_id"] in roots, "the contradiction was not persisted"


@pytest.mark.asyncio
async def test_a_refuted_rule_stops_being_operational_knowledge(locked_world):
    """The assertion that matters most: a logged contradiction must not leave
    the same VALIDATED rule executing forever."""
    from core.learning.rule_grounding import ground_for_problem

    world, store, stored = locked_world
    state = world.observe()
    goal = [Fact("SBAT", ("z", "LAB"))]
    task = await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)")

    before = ground_for_problem(
        await store.executable_rules(domain_id=DOMAIN), state, goal)
    assert before.operators, "the rule should be operational before the contradiction"

    await AutonomousCoordinator().execute_task(task)

    after = ground_for_problem(
        await store.executable_rules(domain_id=DOMAIN), state, goal)
    assert after.operators == [], "planning still offers a refuted rule"
    # A FRESH attempt at the same act, under its own pursuit. Retrying the task
    # that was contradicted stops earlier and rightly — its pursuit concluded —
    # so it would never reach the question this test asks: does a refuted rule
    # still execute for anyone?
    retry = await AutonomousCoordinator().execute_task(
        await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)"))
    assert retry["success"] is False
    assert "refuted" in retry["refused"]


@pytest.mark.asyncio
async def test_lyric_does_not_invent_the_condition_it_was_never_taught(locked_world):
    """One contradiction reduces certainty; it does not determine a replacement.

    LOCKED is not even in the rule's vocabulary. Manufacturing `NOT LOCKED(B)`
    here would be contradiction -> invent explanation, which is the failure mode
    the whole attribution path exists to avoid.
    """
    world, store, stored = locked_world
    task = await task_for(stored.rule_id, "SBMOVE(z, HALL, LAB)")
    await AutonomousCoordinator().execute_task(task)

    rules = await store.load(domain_id=DOMAIN)
    assert len(rules) == 1, "a replacement hypothesis was invented from one observation"
    assert not any("LOCKED" in str(f) for f in rules[0].rule.body)


def test_a_mismatch_is_not_charged_to_the_rule_unless_everything_held():
    """The credit invariant at runtime: never debit a strategy for an
    infrastructure failure."""
    from core.intelligence.effect_verification import (
        Attribution, AttributionContext, RuntimeOutcome, ToolObservation,
        attribute, verify_effects,
    )

    observation = ToolObservation(
        observation_id="o", tool_name="t", invoked=True,
        tool_reported_success=True, observed=True, facts=frozenset())
    evidence = verify_effects(
        RuleEffects(add={Fact("SBAT", ("z", "LAB"))}), observation, rule_id="r")
    assert evidence.outcome is RuntimeOutcome.CONTRADICTION

    everything_held = AttributionContext(
        preconditions_observed=True, rule_validated_at_execution=True,
        action_matches_rule=True, arguments_verified=True,
        invocation_occurred=True, observer_available=True,
        post_state_observed=True, external_interference=False)
    assert attribute(evidence, everything_held)[0] is Attribution.RULE_EVIDENCE

    misbound = AttributionContext(**{**vars(everything_held), "action_matches_rule": False})
    assert attribute(evidence, misbound)[0] is Attribution.EXECUTION_FAILURE

    interfered = AttributionContext(**{**vars(everything_held), "external_interference": True})
    assert attribute(evidence, interfered)[0] is Attribution.EXTERNAL_FAILURE


# ------------------------------------------------ expectations of the world

def _expectation(due_in_s: float, *, add=(), delete=()):
    from datetime import datetime, timedelta, timezone
    from core.intelligence.effect_verification import Expectation
    now = datetime.now(timezone.utc)
    return Expectation(expectation_id="e", rule_id="r", domain_id="d",
                       effects=RuleEffects(add=set(add), delete=set(delete)),
                       held=frozenset(), since=now, due=now + timedelta(seconds=due_in_s))


def _reading(facts):
    from datetime import datetime, timezone
    from core.intelligence.effect_verification import WorldReading
    return WorldReading(reading_id="read", domain_id="d", facts=frozenset(facts),
                        at=datetime.now(timezone.utc), mark=(0, False))


def test_an_expectation_is_not_unmet_before_it_is_due():
    """Absence before the due time is the world not having had its time yet."""
    from core.intelligence.effect_verification import ExpectationOutcome, verify_expectation
    moved = Fact("AT", ("f", "DONE"))
    waiting = Fact("AT", ("f", "INBOX"))

    early = verify_expectation(_expectation(60, add=[moved], delete=[waiting]), _reading([waiting]))
    late = verify_expectation(_expectation(-1, add=[moved], delete=[waiting]), _reading([waiting]))
    met = verify_expectation(_expectation(-1, add=[moved], delete=[waiting]), _reading([moved]))

    assert early.outcome is ExpectationOutcome.PENDING
    assert late.outcome is ExpectationOutcome.CONTRADICTION
    assert {v.polarity for v in late.unmet} == {Polarity.ADD, Polarity.DELETE}
    assert met.outcome is ExpectationOutcome.CONFIRMATION


def test_an_unmet_expectation_is_charged_by_what_tells_it_apart():
    """Separable: the substrate was wrong. Not separable: the world departed.
    The substrate acting meanwhile: neither."""
    from core.intelligence.effect_verification import (
        Attribution, attribute_expectation, verify_expectation)
    unmet = verify_expectation(
        _expectation(-1, add=[Fact("AT", ("f", "DONE"))]), _reading([Fact("AT", ("f", "INBOX"))]))

    assert attribute_expectation(unmet, acted=False, separable=True)[0] is Attribution.RULE_EVIDENCE
    assert attribute_expectation(unmet, acted=False, separable=False)[0] is Attribution.EXTERNAL_FAILURE
    assert attribute_expectation(unmet, acted=True, separable=False)[0] is Attribution.EXECUTION_FAILURE
    assert attribute_expectation(unmet, acted=False, separable=None)[0] is Attribution.INDETERMINATE


def _office(*, inbox=(), done=(), kinds=None):
    kinds = kinds or {}
    facts = {Fact("OPEN", ("INBOX",)), Fact("OPEN", ("DONE",)), Fact("PATH", ("INBOX", "DONE"))}
    facts |= {Fact("AT", (f, "INBOX")) for f in inbox} | {Fact("AT", (f, "DONE")) for f in done}
    facts |= {Fact("KIND", (f, k)) for f, k in kinds.items()}
    return frozenset(facts)


def test_a_world_change_is_cut_to_each_thing_that_changed():
    """Two files moved between the same rooms at once are two changes, each cut
    to what bears on it -- the other files waiting in the room are left out."""
    from core.learning.unified_learning_system import world_change_examples
    kinds = {"a": "pdf", "b": "pdf", "c": "pdf"}
    before = _office(inbox=["a", "b", "c"], kinds=kinds)
    after = _office(inbox=["c"], done=["a", "b"], kinds=kinds)

    examples = world_change_examples(before, after, evidence_stem="s")

    assert len(examples) == 2
    for example, things in examples:
        moved = example.observed_effects
        assert len(moved.add) == 1 and len(moved.delete) == 1
        assert not any("c" in f.args for f in example.before)
        assert example.action is None and example.positive
        assert things in ({"a"}, {"b"})
    assert len({e.evidence_id for e, _ in examples}) == 2


def test_in_a_sparse_world_the_change_is_still_the_file_s():
    """One file in the inbox, one file from its sender: the inbox and the sender
    are each in fewer facts than the file, and the change is still the file's.
    Its arrival is one change of it, and so is its move."""
    from core.learning.demonstration_store import regularity_signature
    from core.learning.unified_learning_system import world_change_examples
    empty = frozenset({Fact("OPEN", ("INBOX",)), Fact("OPEN", ("DONE",))})
    arrived = empty | {Fact("AT", ("f", "INBOX")), Fact("KIND", ("f", "pdf")), Fact("FROM", ("f", "alice"))}
    moved = (arrived - {Fact("AT", ("f", "INBOX"))}) | {Fact("AT", ("f", "DONE"))}

    arrival = world_change_examples(empty, arrived, evidence_stem="a")
    move = world_change_examples(arrived, moved, evidence_stem="m")

    assert [things for _, things in arrival] == [{"f"}]
    assert [things for _, things in move] == [{"f"}]
    learned = RuleEffects(add={Fact("AT", ("?X0", "DONE"))}, delete={Fact("AT", ("?X0", "INBOX"))})
    assert regularity_signature(move[0][0].observed_effects, move[0][1]) == regularity_signature(learned)


def test_a_body_holds_no_literal_twice_over():
    """Facts true of every place pair off whichever way the places' roles fell:
    rooms open in every move, the moves swapping source and destination. The
    body keeps what bears on the act and nothing it holds twice over, so the
    move is learned instead of outgrowing the body bound."""
    from core.learning.rule_induction import InductionStatus, TrainingExample
    rooms = {Fact("OPEN", ("DONE",)), Fact("OPEN", ("ARCHIVE",))}
    examples = []
    for i, (thing, src, dst) in enumerate([("a", "DONE", "ARCHIVE"), ("a", "ARCHIVE", "DONE"),
                                           ("b", "DONE", "ARCHIVE"), ("b", "ARCHIVE", "DONE"),
                                           ("c", "DONE", "ARCHIVE"), ("c", "ARCHIVE", "DONE")]):
        examples.append(TrainingExample(
            before=tuple(sorted(rooms | {Fact("AT", (thing, src))})), action=Fact("MOVE", (thing, src, dst)),
            after=tuple(sorted(rooms | {Fact("AT", (thing, dst))})), positive=True, evidence_id=f"m{i}"))

    result = get_rule_inducer().induce(examples)

    assert result.status is InductionStatus.RULE_LEARNED, result.detail
    assert sum(1 for f in result.rule.body if f.predicate == "OPEN") <= 2


def test_a_file_left_alone_differs_from_one_dealt_with_otherwise():
    """What the predictive intelligence system reads to tell a departure from a
    thing dealt with otherwise: left where it was, the unmet case is the same
    before and after; filed somewhere else, it is not."""
    from core.learning.unified_learning_system import expectation_case
    held = _office(inbox=["p"], kinds={"p": "pdf"})
    moved = RuleEffects(add={Fact("AT", ("p", "DONE"))}, delete={Fact("AT", ("p", "INBOX"))})
    elsewhere = (held - {Fact("AT", ("p", "INBOX"))}) | {Fact("AT", ("p", "ARCHIVE"))}

    left = expectation_case(held, held, moved, evidence_id="l")
    filed = expectation_case(held, elsewhere, moved, evidence_id="f")

    assert set(left.before) == set(left.after)
    assert set(filed.before) != set(filed.after)
    assert Fact("AT", ("p", "ARCHIVE")) in filed.after


def test_a_miss_told_apart_by_what_had_been_seen_is_not_once_more_is_seen():
    """With only alice's files moved, erin's left behind is told apart by its
    sender: the substrate's mistake, then. Once erin's have moved too, nothing
    tells it apart, and the same question answers that the world departed."""
    from core.learning.rule_induction import InductionStatus
    from core.learning.unified_learning_system import expectation_case, world_change_examples

    def office(name, sender, room):
        return _office(inbox=[name] if room == "INBOX" else [], done=[name] if room == "DONE" else [],
                       kinds={name: "pdf"}) | {Fact("FROM", (name, sender))}

    def moved(name, sender):
        return [e for e, _ in world_change_examples(office(name, sender, "INBOX"), office(name, sender, "DONE"),
                                                    evidence_stem=name)]
    effects = RuleEffects(add={Fact("AT", ("e", "DONE"))}, delete={Fact("AT", ("e", "INBOX"))})
    left = expectation_case(office("e", "erin", "INBOX"), office("e", "erin", "INBOX"), effects, evidence_id="u")

    alices = moved("a1", "alice") + moved("a2", "alice") + moved("a3", "alice")
    then = get_rule_inducer().induce(alices + [left])
    now = get_rule_inducer().induce(alices + moved("e1", "erin") + moved("e2", "erin") + [left])

    assert then.status in (InductionStatus.RULE_LEARNED, InductionStatus.MULTIPLE_HYPOTHESES)
    assert now.status is InductionStatus.NO_RULE and now.negative_coverage


def test_the_basis_spans_what_the_changes_were_like_not_only_the_first():
    """Fifteen of alice's files moved first, then others': the bounded basis a
    miss is compared with holds others' too, so erin's file left behind is not
    told apart by its sender."""
    from core.learning.rule_induction import InductionStatus
    from core.learning.unified_learning_system import (_bounded_basis, expectation_case,
                                                       world_change_examples)

    def office(name, sender, room):
        return _office(inbox=[name] if room == "INBOX" else [], done=[name] if room == "DONE" else [],
                       kinds={name: "pdf"}) | {Fact("FROM", (name, sender))}

    positives = []
    for i, sender in enumerate(["alice"] * 15 + ["bob", "erin", "dan", "carol", "erin", "bob"]):
        name = f"f{i}"
        positives += [e for e, _ in world_change_examples(office(name, sender, "INBOX"),
                                                          office(name, sender, "DONE"), evidence_stem=name)]
    basis = _bounded_basis(positives, ())
    effects = RuleEffects(add={Fact("AT", ("e", "DONE"))}, delete={Fact("AT", ("e", "INBOX"))})
    left = expectation_case(office("e", "erin", "INBOX"), office("e", "erin", "INBOX"), effects, evidence_id="u")

    senders = {f.args[1] for e in basis for f in e.before if f.predicate == "FROM"}
    result = get_rule_inducer().induce(basis + [left])

    assert senders > {"alice"}
    assert result.status is InductionStatus.NO_RULE and result.negative_coverage


def test_a_habit_is_relied_on_by_how_often_it_held():
    """Relied on when it is more likely than not to hold at least four times in
    five: nine of ten is, eight of ten is not, and a step kept three times in
    four or every other time never is, however long it runs."""
    from core.learning.unified_learning_system import relied_on_rate
    assert not relied_on_rate(0, 0)
    assert not relied_on_rate(1, 1) and not relied_on_rate(4, 4) and relied_on_rate(5, 5)
    assert relied_on_rate(9, 10) and not relied_on_rate(8, 10)
    assert relied_on_rate(90, 100)
    assert not relied_on_rate(75, 100) and not relied_on_rate(750, 1000)
    assert not relied_on_rate(50, 100) and not relied_on_rate(500, 1000)


def test_a_success_nothing_it_held_explains_is_the_world_departing():
    """A press works where the button is ready. One worked where it was only
    lit, and two presses where it was only lit were refused: the world leaked
    there. Refusals that held something no press that worked held (the button
    jammed) could be refused for that, and say nothing of the lit press; and
    one refusal can be the world departing the other way."""
    from core.learning.unified_learning_system import _leaks

    def press(i, *held, worked):
        thing = f"b{i}"
        before = tuple(sorted(Fact(p, (thing,)) for p in held))
        after = before + ((Fact("PRESSED", (thing,)),) if worked else ())
        return TrainingExample(before=before, action=Fact("PRESS", (thing,)), after=tuple(sorted(after)),
                               positive=worked, evidence_id=f"p{i}")
    worked = [press(i, "READY", *(("LIT",) if i % 2 else ()), worked=True) for i in range(4)]
    leak = press(4, "LIT", worked=True)
    lit = [press(5, "LIT", worked=False), press(6, "LIT", worked=False)]
    jammed = [press(7, "LIT", "JAMMED", worked=False), press(8, "LIT", "JAMMED", worked=False)]

    assert _leaks(worked + [leak] + lit, set(), lambda basis: basis) == {"p4"}
    assert _leaks(worked + [leak] + jammed, set(), lambda basis: basis) == set()
    assert _leaks(worked + [leak] + lit[:1] + jammed, set(), lambda basis: basis) == set()
    assert _leaks(worked + [leak] + lit, {"p5"}, lambda basis: basis) == set()


def test_a_miss_the_bounded_basis_left_out_still_refutes():
    """A press works where the button is ready and lit. The first eight refusals
    were of buttons only lit, which READY alone tells apart; the ninth was ready
    and not lit. Induced from the first eight alone, the rule needs no LIT."""
    from core.learning.unified_learning_system import UnifiedLearningSystem, _bounded_basis

    def press(i, *held, worked):
        thing = f"b{i}"
        before = tuple(sorted(Fact(p, (thing,)) for p in held))
        after = before + ((Fact("PRESSED", (thing,)),) if worked else ())
        return TrainingExample(before=before, action=Fact("PRESS", (thing,)), after=tuple(sorted(after)),
                               positive=worked, evidence_id=f"p{i}")
    examples = ([press(i, "READY", "LIT", worked=True) for i in range(3)]
                + [press(i, "LIT", worked=False) for i in range(3, 11)]
                + [press(11, "READY", worked=False)])
    learning = UnifiedLearningSystem.__new__(UnifiedLearningSystem)
    learning._inducer = None

    capped = asyncio.run(learning.induce_on_thread(_bounded_basis(examples, ())))
    assert "LIT" not in {f.predicate for f in capped.rule.body}
    result, basis = asyncio.run(learning.induce_bounded(examples))
    assert {"READY", "LIT"} <= {f.predicate for f in result.rule.body}
    assert "p11" in {e.evidence_id for e in basis}


def test_a_condition_never_seen_unneeded_stays_in_the_rule():
    """A press worked three times, each time ready and lit; the refusals were
    all unready. "Ready" alone excludes every refusal, but lit held in every
    press: the act has not been seen to work unlit, so "ready" alone does not
    act. Once a press works unlit, it does."""
    from core.learning.unified_learning_system import _unshown
    from core.learning.rule_induction import CandidateRule

    def press(i, *held, worked):
        thing = f"b{i}"
        before = tuple(sorted(Fact(p, (thing,)) for p in held))
        after = before + ((Fact("PRESSED", (thing,)),) if worked else ())
        return TrainingExample(before=before, action=Fact("PRESS", (thing,)), after=tuple(sorted(after)),
                               positive=worked, evidence_id=f"p{i}")
    act = Fact("PRESS", ("?X0",))
    ready = CandidateRule(body=frozenset({act, Fact("READY", ("?X0",))}),
                          effects=RuleEffects(add=frozenset({Fact("PRESSED", ("?X0",))})), action=act)
    seen = ([press(i, "READY", "LIT", worked=True) for i in range(3)]
            + [press(i, "LIT", worked=False) for i in range(3, 6)])

    assert "LIT(0)" in _unshown(ready, seen)
    assert _unshown(ready, seen + [press(6, "READY", worked=True)]) is None


def test_a_stand_in_the_evidence_has_decided_against_loses_authority():
    """A press works where the button is ready and not jammed. Lit happened to
    hold in the first successes and in none of the jammed refusals, so "ready
    and lit" was learned; a success unlit lies outside it, and "ready, with
    jammed absent" explains every press. "Ready and lit" is not the rule. A
    rule every press lies inside, or one no absent condition outdoes, stays."""
    from core.learning.unified_learning_system import UnifiedLearningSystem
    from core.learning.rule_induction import CandidateRule

    def press(i, *held, worked):
        thing = f"b{i}"
        before = tuple(sorted(Fact(p, (thing,)) for p in held))
        after = before + ((Fact("PRESSED", (thing,)),) if worked else ())
        return TrainingExample(before=before, action=Fact("PRESS", (thing,)), after=tuple(sorted(after)),
                               positive=worked, evidence_id=f"p{i}")
    act = Fact("PRESS", ("?X0",))
    lit = CandidateRule(body=frozenset({act, Fact("READY", ("?X0",)), Fact("LIT", ("?X0",))}),
                        effects=RuleEffects(add=frozenset({Fact("PRESSED", ("?X0",))})), action=act)
    seen = ([press(i, "READY", "LIT", worked=True) for i in range(3)]
            + [press(i, "READY", "JAMMED", worked=False) for i in range(3, 5)]
            + [press(5, "LIT", worked=False)])
    unlit = press(6, "READY", worked=True)

    assert UnifiedLearningSystem._outexplained(lit, seen) is None
    assert "JAMMED" in UnifiedLearningSystem._outexplained(lit, seen + [unlit])
    either = seen + [unlit, press(7, "LIT", "JAMMED", worked=True)]
    assert UnifiedLearningSystem._outexplained(lit, either) is None


def test_what_the_substrate_touched_is_told_apart_per_thing():
    """An act that says what it changed names those things, and the world's own
    change of anything else is still the world's; one that does not say, or one
    still under way, counts as having touched everything."""
    from core.intelligence.effect_verification import (act_mark, acts_touched,
                                                       concurrent_execution_guard)
    domain = f"touch_{uuid.uuid4().hex[:6]}"
    before = frozenset({Fact("AT", ("pdf026", "INBOX")), Fact("AT", ("pdf027", "INBOX"))})
    after = frozenset({Fact("AT", ("pdf026", "DONE")), Fact("AT", ("pdf027", "INBOX"))})

    start = act_mark(domain)
    with concurrent_execution_guard(domain) as act:
        assert acts_touched(domain, start, act_mark(domain)) is None      # under way
        act.changed(before, after)
    told = act_mark(domain)
    with concurrent_execution_guard(domain):
        pass                                                              # says nothing
    untold = act_mark(domain)

    assert acts_touched(domain, start, told) == {"pdf026", "INBOX", "DONE"}
    assert "pdf027" not in acts_touched(domain, start, told)
    assert acts_touched(domain, told, untold) is None
    assert acts_touched(domain, told, told) == frozenset()


def test_an_act_among_others_is_its_own_where_they_touched_other_things():
    """A goal pursuit presses o7a while a near miss is tried on o11a in the same
    world: the near miss's refusal is its own. The pursuit still under way is
    waited for; one that ends without saying what it changed leaves the near
    miss unattributable."""
    from core.intelligence.effect_verification import (act_window, concurrent_execution_guard,
                                                       touched_by)
    domain = f"overlap_{uuid.uuid4().hex[:6]}"
    lit = frozenset({Fact("READY", ("o7a",))})
    pressed = lit | {Fact("PRESSED", ("o7a",))}

    async def pursuit(says):
        with concurrent_execution_guard(domain) as act:
            await asyncio.sleep(0.05)
            if says:
                act.changed(lit, pressed)

    async def near_miss(says):
        window = act_window(domain)
        running = asyncio.create_task(pursuit(says))
        await asyncio.sleep(0.01)
        with concurrent_execution_guard(domain) as act:
            act.changed(frozenset(), frozenset())
            others = act.others_since(window)
        assert others
        theirs = await touched_by(domain, others)
        await running
        return theirs

    assert asyncio.run(near_miss(True)) == {"o7a"}
    assert asyncio.run(near_miss(False)) is None


def test_what_an_act_names_is_what_it_acted_on():
    """A goal pursuit on o0a and o6b saw a new group arrive while it waited on
    its own request; what it acted on is still o0a and o6b, not the group the
    near miss beside it then tried. One that does not say what it names counts
    as naming everything."""
    from core.intelligence.effect_verification import (act_window, concurrent_execution_guard,
                                                       named_by)
    domain = f"names_{uuid.uuid4().hex[:6]}"
    offered = frozenset({Fact("LUMA", ("o12b", "o12a"))})
    window = act_window(domain)
    with concurrent_execution_guard(domain, names=("o0a", "o6b")) as pursuit:
        with concurrent_execution_guard(domain, names=("o12a", "o12b")) as near_miss:
            near_miss.changed(offered, offered)
            others = near_miss.others_since(window)
        pursuit.changed(frozenset(), offered)
    assert named_by(domain, others) == {"o0a", "o6b"}

    window = act_window(domain)
    with concurrent_execution_guard(domain):
        with concurrent_execution_guard(domain, names=("o12a", "o12b")) as near_miss:
            others = near_miss.others_since(window)
    assert named_by(domain, others) is None


def test_a_kind_of_change_names_its_places_and_leaves_the_thing_open():
    """Inbox-to-done and done-to-archive are two kinds of change; two files
    moved inbox-to-done are one."""
    from core.learning.demonstration_store import regularity_signature
    from core.learning.unified_learning_system import world_change_examples
    examples = world_change_examples(_office(inbox=["a", "b"]), _office(done=["a", "b"]),
                                     evidence_stem="s")
    kinds = {regularity_signature(e.observed_effects, things) for e, things in examples}
    learned = RuleEffects(add={Fact("AT", ("?X0", "DONE"))}, delete={Fact("AT", ("?X0", "INBOX"))})
    archived = RuleEffects(add={Fact("AT", ("?X0", "ARCHIVE"))}, delete={Fact("AT", ("?X0", "DONE"))})

    assert kinds == {regularity_signature(learned)}
    assert regularity_signature(archived) != regularity_signature(learned)


def test_an_unmet_case_is_told_apart_only_by_what_was_observed():
    """The question attribution rests on, put to the inducer: a pdf left in the
    inbox is like every pdf that moved, so the world departed; a txt left there
    differs in its kind, so the regularity was too broad."""
    from core.learning.rule_induction import InductionStatus
    from core.learning.unified_learning_system import expectation_case, world_change_examples

    positives = []
    for name in ("a", "b", "c"):
        kinds = {name: "pdf"}
        positives += [e for e, _ in world_change_examples(_office(inbox=[name], kinds=kinds),
                                                          _office(done=[name], kinds=kinds),
                                                          evidence_stem=name)]
    moved = lambda f: RuleEffects(add={Fact("AT", (f, "DONE"))}, delete={Fact("AT", (f, "INBOX"))})

    left_pdf = _office(inbox=["p"], kinds={"p": "pdf"})
    like_the_rest = expectation_case(left_pdf, left_pdf, moved("p"), evidence_id="u1")
    left_txt = _office(inbox=["t"], kinds={"t": "txt"})
    of_another_kind = expectation_case(left_txt, left_txt, moved("t"), evidence_id="u2")

    inseparable = get_rule_inducer().induce(positives + [like_the_rest])
    separable = get_rule_inducer().induce(positives + [of_another_kind])

    assert inseparable.status is InductionStatus.NO_RULE and inseparable.negative_coverage
    assert separable.status in (InductionStatus.RULE_LEARNED, InductionStatus.MULTIPLE_HYPOTHESES)
    assert all(any(f.predicate == "KIND" for f in c.body) for c in separable.candidates)


def test_a_workspace_task_has_the_substrate_take_it_up():
    """A task that declares a workspace has the substrate LOOK at it the first
    time it engages the task (_derive_goal_spec): what is there enters the
    domain's world through the self's own perception, and the domain becomes
    explorable with practice bounded to the directory. Taking it up again
    changes nothing; a directory that is not there is declined; a task with no
    workspace takes nothing up.
    """
    from types import SimpleNamespace
    from core.learning.exploration import take_up_workspace
    from core.perception.perception_faculty import sensed_fact, world_of
    from core.learning.exploration import (
        explorable_domains, get_proposer, unregister_explorable_domain)

    def wtask(domain_id, root, conds):
        return SimpleNamespace(id="t_enc", provenance={
            "domain_id": domain_id, "workspace_root": str(root),
            "goal_conditions": conds})

    ex = AutonomousCoordinator()
    domain = "test_encounter_fs"
    unregister_explorable_domain(domain)

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "alpha").mkdir()
        (root / "beta").mkdir()
        (root / "alpha" / "doc").write_text("x")
        conds = [sensed_fact("kind", "path", str(root / "beta" / "doc"), "file").to_formula()]

        assert domain not in explorable_domains()

        # ENGAGING the task takes the workspace up: it is perceived and observed.
        spec = ex._derive_goal_spec(wtask(domain, root, conds))
        assert spec is not None and spec["domain_id"] == domain
        assert (sensed_fact("kind", "path", str(root / "alpha" / "doc"), "file").to_formula()
                in spec["world_state"]), "the world is what the self perceived there"
        assert domain in explorable_domains()      # now the drive handler can ACT
        proposer = get_proposer(domain)
        assert proposer is not None

        # Taking it up again changes nothing: the same proposer.
        take_up_workspace(domain, str(root))
        assert get_proposer(domain) is proposer

        # Practice is bounded to the directory, and never acts on the directory itself.
        world = world_of(domain)
        assert world.practisable("path", str(root / "alpha" / "doc"))
        assert not world.practisable("path", str(root))
        assert not world.practisable("path", "/etc/hosts")

        unregister_explorable_domain(domain)

    # A directory that is not there is declined — no practice invented over nothing.
    missing = "test_encounter_missing"
    unregister_explorable_domain(missing)
    assert take_up_workspace(missing, "/no/such/dir/xyz_nope") == 0
    assert missing not in explorable_domains()

    # A task with no workspace installs nothing (backward-compatible).
    spec_none = ex._derive_goal_spec(SimpleNamespace(
        id="t_nofs", provenance={"domain_id": "nofs_x", "goal_conditions": ["P(a)"]}))
    assert spec_none is None
    assert "nofs_x" not in explorable_domains()
