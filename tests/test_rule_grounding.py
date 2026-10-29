"""Learned rules become planning operators only when they are entitled to.

Grounding is the join between the two halves: rules are lifted, the planner is
propositional. The join is also where the execution gate could be quietly
widened, so admissibility is checked here rather than assumed from the caller.

Every test runs model-free; composition that reached for a model would not be
evidence of anything the substrate owns.
"""
import pytest

from core.learning.rule_grounding import (
    DEFAULT_MAX_OPERATORS, GroundOperator, constants_in, ground_for_problem,
    ground_rule,
)
from core.learning.rule_induction import (
    CandidateRule, Fact, RuleEffects, TrainingExample, get_rule_inducer,
)
from core.learning.rule_store import EpistemicStatus, StoredRule, from_json, to_json
# THE MODEL-FREE GUARD IS GONE, AND SO IS WHAT IT GUARDED AGAINST.
# These tests wrapped themselves in an autouse fixture that set
# `ModelPolicy.STRICT_MODEL_FREE` and asserted afterwards that no model had been
# called. `core.model_policy` was REMOVED when the substrate became model-free by
# CONSTRUCTION -- there is no longer a policy to set, because there is nothing to
# set it against. The guard's subject is gone; the subject of these tests is not,
# and they had been uncollectable ever since.
from core.reasoning.temporal_reasoning import PlanningStatus, TemporalReasoningSystem

F = Fact.parse




def move_example(who, a, b, evidence_id, opened=True, path=True, acted=True, at=True):
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
        after=after, positive=ok, evidence_id=evidence_id,
    )


@pytest.fixture
def move_rule():
    """Includes the counter-demonstration for acting from elsewhere.

    Without it AT(?X,?A) is minimized away as unsupported and the rule lets an
    agent move from a room it is not in -- correct induction from an incomplete
    corpus, and invisible until something composes the rule.
    """
    teaching = [
        move_example("a", "R1", "R2", "t1"), move_example("b", "R3", "R4", "t2"),
        move_example("c", "R5", "R6", "n1", opened=False),
        move_example("d", "R7", "R8", "n2", path=False),
        move_example("e", "R9", "R10", "n3", acted=False),
        move_example("h", "R15", "R16", "n4", at=False),
    ]
    return get_rule_inducer().induce(teaching).rule


WORLD = [F("AT(z,HALL)"), F("PATH(HALL,LAB)"), F("OPEN(LAB)"),
         F("PATH(LAB,VAULT)"), F("OPEN(VAULT)")]
GOAL = [F("AT(z,VAULT)")]


def stored(rule, status=EpistemicStatus.VALIDATED, rule_id="rule_test"):
    return StoredRule(rule_id=rule_id, rule=rule, status=status)


# ------------------------------------------------------------- admissibility

@pytest.mark.parametrize("status", [
    EpistemicStatus.CANDIDATE, EpistemicStatus.SUPPORTED, EpistemicStatus.REFUTED,
])
def test_only_validated_rules_become_operators(move_rule, status):
    """The ablation proved this gate causally controls derivation. Planning must
    not widen it."""
    report = ground_for_problem([stored(move_rule, status)], WORLD, GOAL)
    assert report.operators == []
    assert "not executable" in next(iter(report.rules_skipped.values()))


def test_a_validated_rule_is_grounded(move_rule):
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    assert report.operators
    assert report.rules_used == ["rule_test"]


def test_a_rule_with_no_action_is_not_a_planning_operator():
    """A rule recording what follows is not a rule about what the agent can do.
    Offering it would let the planner 'achieve' a goal by asserting the world
    changes on its own."""
    inference_only = CandidateRule(
        body=frozenset({Fact("NAL", ("?X",))}),
        effects=RuleEffects(add={Fact("ZOR", ("?X",))}),
    )
    report = ground_for_problem([stored(inference_only)], [F("NAL(a)")], [F("ZOR(a)")])
    assert report.operators == []
    assert "no action recorded" in next(iter(report.rules_skipped.values()))


def test_rules_stored_before_action_existed_read_back_and_are_excluded(move_rule):
    """v1 encodings genuinely do not record the action. Reading them is right;
    inferring one would invent provenance."""
    v1 = to_json(move_rule)
    v1["schema_version"] = 1
    v1.pop("action")

    recovered = from_json(v1)
    assert recovered.action is None
    assert recovered.body == move_rule.body

    report = ground_for_problem([stored(recovered)], WORLD, GOAL)
    assert report.operators == []


def test_an_unreadable_schema_version_is_still_refused(move_rule):
    payload = to_json(move_rule)
    payload["schema_version"] = 99
    with pytest.raises(ValueError):
        from_json(payload)


# ------------------------------------------------------------------ grounding

def test_constants_exclude_variables(move_rule):
    assert constants_in(WORLD) == {"z", "HALL", "LAB", "VAULT"}
    assert constants_in(move_rule.body) == set()


def test_the_action_is_separated_from_the_preconditions(move_rule):
    """The gap that blocked planning: MOVE and OPEN were both body literals with
    nothing saying which one the agent performs."""
    assert move_rule.action is not None
    assert move_rule.action.predicate == "MOVE"
    assert {f.predicate for f in move_rule.preconditions} == {"AT", "OPEN", "PATH"}
    assert move_rule.action not in move_rule.preconditions


def test_grounding_truncation_is_reported_not_silent(move_rule):
    """A planner quietly missing operators would report UNREACHABLE for a goal
    it was never given the means to reach.

    The bound is 2 rather than 5 because grounding now enumerates each variable
    over the terms that can stand where it stands rather than over every
    constant, so this rule yields 4 operators instead of 27. What is under test
    is that hitting the bound is reported, not how many operators the rule has.
    """
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL, limit=2)
    assert report.truncated is True
    assert report.complete is False
    assert len(report.operators) <= 2


def test_a_complete_grounding_says_so(move_rule):
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    assert report.complete is True


def test_operators_carry_the_rule_that_produced_them(move_rule):
    report = ground_for_problem([stored(move_rule, rule_id="rule_abc")], WORLD, GOAL)
    assert all(o.rule_id == "rule_abc" for o in report.operators)
    assert all(o.bindings for o in report.operators)


def test_a_problem_with_no_constants_grounds_nothing(move_rule):
    assert ground_for_problem([stored(move_rule)], [], []).operators == []


# ------------------------------------------------------ composition end to end

def test_a_learned_rule_composes_into_a_multi_step_plan(move_rule):
    """The frontier claim: acquire a single-step transition from demonstrations,
    then compose it toward a goal across a map never demonstrated."""
    report = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in GOAL],
        {"conditions": [f.to_formula() for f in WORLD]},
        report.to_actions(),
    )

    assert result.status is PlanningStatus.PLAN_FOUND
    assert [s["action"] for s in result.steps] == [
        "MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"]


def test_the_plan_traces_back_to_the_learned_rule(move_rule):
    report = ground_for_problem([stored(move_rule, rule_id="rule_xyz")], WORLD, GOAL)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in GOAL],
        {"conditions": [f.to_formula() for f in WORLD]},
        report.to_actions(),
    )
    assert {a["rule_id"] for a in result.actions} == {"rule_xyz"}


def test_composition_fails_honestly_when_the_goal_is_unreachable(move_rule):
    """A sealed vault must produce a proof, not a plan."""
    sealed = [f for f in WORLD if f != F("OPEN(VAULT)")]
    report = ground_for_problem([stored(move_rule)], sealed, GOAL)
    result = TemporalReasoningSystem().plan_for_state_goal(
        [f.to_formula() for f in GOAL],
        {"conditions": [f.to_formula() for f in sealed]},
        report.to_actions(),
    )
    assert result.status is PlanningStatus.UNREACHABLE
    assert result.steps == []


def test_an_incomplete_corpus_yields_an_overgeneral_operator():
    """Recorded because composition found it and single-rule evaluation could
    not: without a counter-demonstration of acting from elsewhere, AT is
    minimized away and the agent can move from a room it is not in."""
    without_counter = [
        move_example("a", "R1", "R2", "t1"), move_example("b", "R3", "R4", "t2"),
        move_example("c", "R5", "R6", "n1", opened=False),
        move_example("d", "R7", "R8", "n2", path=False),
        move_example("e", "R9", "R10", "n3", acted=False),
    ]
    rule = get_rule_inducer().induce(without_counter).rule
    assert "AT" not in {f.predicate for f in rule.preconditions}, (
        "this documents the gap; if induction changes, revisit the corpus"
    )


def test_an_argument_nothing_constrains_is_grounded_on_a_thing_the_act_may_be_taken_on():
    """SHARPEN(?T, ?B) needs only READY(?B), so the tool is grounded once. Every
    success had a tool that fits the blade or is sharp: the one kept is t2,
    which fits b, not b itself or the worn t1, cases no success covered and the
    constitution would send back. A tool something the rule needs absent holds
    of is passed over the same way."""
    rule = CandidateRule(body=frozenset({F("SHARPEN(?T,?B)"), F("READY(?B)")}),
                         effects=RuleEffects(add={F("KEEN(?B)")}), action=F("SHARPEN(?T,?B)"))
    world = [F("READY(b)"), F("WORN(t1)"), F("FITS(t2,b)")]
    covered = {("SHARPEN", 2): [["FITS(0,1)", "READY(1)"], ["READY(1)", "SHARP(0)"]]}
    names = lambda report: [o.name for o in report.operators]
    assert names(ground_for_problem([stored(rule)], world, [F("KEEN(b)")])) == ["SHARPEN(b, b)"]
    assert names(ground_for_problem([stored(rule)], world, [F("KEEN(b)")], covered=covered)) == ["SHARPEN(t2, b)"]
    unworn = CandidateRule(body=rule.body, effects=rule.effects, action=rule.action,
                           absent=frozenset({F("WORN(?T)")}))
    world = [F("READY(b)"), F("WORN(b)"), F("FITS(t1,b)")]
    assert names(ground_for_problem([stored(unworn)], world, [F("KEEN(b)")])) == ["SHARPEN(t1, b)"]


def test_grounding_back_from_the_goal_keeps_what_the_planner_keeps(move_rule):
    """Grounded back from the goal, the operators are those the planner's own relevance keeps from everything
    grounded forward: the two moves of the route and any other that bears on it, no plan lost."""
    forward = ground_for_problem([stored(move_rule)], WORLD, GOAL)
    toward = ground_for_problem([stored(move_rule)], WORLD, GOAL, toward=GOAL)
    kept = TemporalReasoningSystem._relevant([g.to_formula() for g in GOAL], forward.to_actions())
    assert sorted(a["name"] for a in kept) == sorted(o.name for o in toward.operators)
    assert {"MOVE(z, HALL, LAB)", "MOVE(z, LAB, VAULT)"} <= {o.name for o in toward.operators}
    result = TemporalReasoningSystem().plan_for_state_goal(
        [g.to_formula() for g in GOAL], {"conditions": [f.to_formula() for f in WORLD]}, toward.to_actions())
    assert result.status is PlanningStatus.PLAN_FOUND and len(result.steps) == 2


def test_grounding_back_from_the_goal_pairs_only_what_the_goal_names():
    """PRESS(?A, ?B) needs only READY(?A) and LIT(?B): grounded forward over sixty ready things and sixty lit ones it
    is every pair, 3,600 operators; back from the goal PRESSED(r7, l3), the one that reaches it."""
    rule = CandidateRule(body=frozenset({F("PRESS(?A,?B)"), F("READY(?A)"), F("LIT(?B)")}),
                         effects=RuleEffects(add={F("PRESSED(?A,?B)")}), action=F("PRESS(?A,?B)"))
    world = [F(f"READY(r{i})") for i in range(60)] + [F(f"LIT(l{i})") for i in range(60)]
    goal = [F("PRESSED(r7,l3)")]
    assert len(ground_for_problem([stored(rule)], world, goal).operators) == 3600
    toward = ground_for_problem([stored(rule)], world, goal, toward=goal)
    assert [o.name for o in toward.operators] == ["PRESS(r7, l3)"] and not toward.truncated


def test_grounding_back_from_the_goal_keeps_each_rule_of_an_act():
    """An act given as two cases has two rules and one name: back from the goal, each is its own operator, and the one
    whose condition holds plans the goal (RULE-AUTHORITY-02 world 646, where the first by name was kept and its
    condition did not hold)."""
    act = F("PRESS(?A)")
    lit = CandidateRule(body=frozenset({act, F("LIT(?A)")}), effects=RuleEffects(add={F("PRESSED(?A)")}), action=act)
    warm = CandidateRule(body=frozenset({act, F("WARM(?A)")}), effects=RuleEffects(add={F("PRESSED(?A)")}), action=act)
    world, goal = [F("WARM(b1)")], [F("PRESSED(b1)")]
    report = ground_for_problem([stored(lit, rule_id="lit"), stored(warm, rule_id="warm")], world, goal, toward=goal)
    assert [(o.rule_id, o.name) for o in report.operators] == [("warm", "PRESS(b1)")]
    result = TemporalReasoningSystem().plan_for_state_goal(
        [g.to_formula() for g in goal], {"conditions": [f.to_formula() for f in world]}, report.to_actions())
    assert result.status is PlanningStatus.PLAN_FOUND
