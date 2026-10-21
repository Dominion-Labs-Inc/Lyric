#!/usr/bin/env python3
"""Deriving a procedure from what it must produce, not from being shown how.

`RuleInducer` acquires ONE rule from demonstrations of a transition: it is
shown the action and generalizes what the action does. That is how the
substrate learns an instruction set. It cannot answer a different question --
WHICH instructions, in what order, under what condition -- because nobody
demonstrated the composition.

This does. The evidence is input/output pairs and nothing else: a list and the
number the procedure must produce. No trace, no hint, no demonstration of the
algorithm. A candidate is accepted only if it produces the required answer on
every example, and it is built out of operators the substrate has already
learned, so it can never do anything it has not learned to do.

WHY NOT THE PLANNER. `plan_for_state_goal` searches ground action sequences
toward a goal in ONE state, and its answer is the length of that problem. A
fold has no fixed length. What is searched here is the space of PROCEDURES --
guard/operator pairs valid across every example at once -- and the planner has
no representation for that. The two are complementary: this derives the loop, a
plan composes procedures whose count is known in advance.

A POLICY, NOT A PROGRAM ENUMERATION. Enumerating guarded programs is
exponential in the flags, so it collapses exactly as the substrate grows more
operators and observations -- the opposite of what a lifelong learner needs.
Instead the search is over a POLICY: an assignment of one operator to each
abstract state (the subset of guards that hold there). All examples are run
under the policy at once, so a wrong assignment breaks SOME example and is
rejected globally -- the same reason a mislabelled rule cannot survive. The
distinct abstract states the examples visit are few and do not multiply with
depth, so cost is polynomial in operators x flags x example-length. A committed
register value is never destructively overwritten, which keeps the readings
canonical, and the policy is then generalised to the fewest guarded rules that
reproduce it.

ALL OF THEM. Every consistent policy is generalised and the results are
deduplicated BY BEHAVIOUR: two that take the same steps on every example are
the same procedure written twice. What survives is genuine underdetermination
-- reported as MULTIPLE_PROCEDURES rather than resolved by picking one, for the
same reason `MULTIPLE_HYPOTHESES` exists in the induction owner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import (Callable, Dict, FrozenSet, List, Optional, Protocol, Sequence, Set,
                    Tuple)

from core.intelligence.effect_verification import (RuntimeOutcome, ToolObservation,
                                                   verify_effects)
from core.learning.learning_policy import guard_learning
from core.learning.rule_induction import (CandidateRule, Fact, RuleEffects,
                                          TrainingExample, applies)

logger = logging.getLogger(__name__)

#: Ceiling on procedure size. A procedure is a decision list with one operator
#: per guard, so this is also the number of distinct conditions it may branch
#: on. Reported when reached, never silently applied: NO_PROCEDURE under a
#: bound is "none this small", not "none exists".
DEFAULT_MAX_RULES = 5


# =============================================================================
# THE PROCEDURE: learned operators, guarded, run until they produce an answer
# =============================================================================
#
# A procedure: learned operators, guarded, run until they produce an answer.
#
# A PLAN IS NOT A PROGRAM. `plan_for_state_goal` returns a ground action sequence
# that reaches a goal FROM ONE STATE. Its length is the length of that problem,
# so a plan found on a four-element list cannot run on a five-element one. That
# is enough to compose operations whose number is known in advance -- which is
# what EDU-12's program-construction run does -- and it is not enough to express
# a fold, where the number of steps is a property of the input.
#
# What makes a procedure length-general is that its steps are LIFTED and
# CONDITIONAL. A step fires whenever its guard holds and its operator's learned
# preconditions match, and the loop is the repeated firing. Nothing here knows
# how long the input is, and nothing here is compiled for a particular one.
#
#     guard      zero-arity observations that must hold -- what the procedure is
#                permitted to branch on, declared by the caller, never inferred
#     operator   the learned rules for one action: what it requires and what it
#                changes. Not a Python function -- the substrate's own model
#     order      first applicable step wins; guarded steps precede unguarded ones
#
# THE WORLD ACTS, THE MODEL PREDICTS, AND THEY ARE COMPARED. Each step executes
# against the real actuator and the result is read back by observation, never
# from the actuator's return value. The learned rule's predicted effect is then
# checked against that observation through `effect_verification` -- the same
# comparison the substrate's execution path already performs. A procedure that
# runs to an answer while its own model was contradicted is reported as
# UNPREDICTED, not as a success: the answer would be the machine's, and the
# substrate would have been carried by a world it had misunderstood.
#
# Every way a run can fail to produce an answer is a distinct outcome. Collapsing
# them into a boolean would make "no step applied" indistinguishable from "the
# machine refused the step" -- the first is an incomplete procedure, the second a
# disagreement between what was learned and what is true.

class Actuator(Protocol):
    """Something that can be acted on and read back, independently."""

    def observe(self) -> Optional[FrozenSet[Fact]]:
        """The world as it is. None when it cannot be read at all."""

    def perform(self, action: Fact) -> bool:
        """Take the action. False when the world refused it."""


@dataclass(frozen=True)
class Operator:
    """One action and everything learned about what it does.

    Several rules per action is the normal case, not a special one: each is
    scoped to the predicate it explains -- what TAKE does to register A, and
    what TAKE does to the cursor -- because a rule may only conclude about
    terms its body binds. Requiring all of them to match is what keeps the
    action's preconditions complete.
    """

    action: Fact
    rules: Tuple[CandidateRule, ...]

    @property
    def name(self) -> str:
        return self.action.predicate

    def instances(self, state: FrozenSet[Fact]) -> Optional[List[RuleEffects]]:
        """The effects the learned model asserts here, or None if it does not apply."""
        example = TrainingExample(before=tuple(state - {self.action}),
                                  action=self.action)
        asserted: List[RuleEffects] = []
        for rule in self.rules:
            found = applies(rule, example)
            if not found:
                return None
            asserted.extend(found)
        return asserted


@dataclass(frozen=True)
class Step:
    """An operator and the condition under which the procedure uses it."""

    guard: Tuple[Fact, ...]
    operator: Operator

    def __post_init__(self):
        for flag in self.guard:
            if flag.args:
                raise ValueError(
                    f"a guard is a zero-arity observation; {flag} carries terms")

    @property
    def is_guarded(self) -> bool:
        return bool(self.guard)

    def holds(self, state: FrozenSet[Fact]) -> bool:
        return all(flag in state for flag in self.guard)

    def __str__(self) -> str:
        condition = " ∧ ".join(str(f) for f in self.guard) if self.guard else "otherwise"
        return f"{condition} → {self.operator.name}"


class RunStatus(Enum):
    """How a run ended. Only the first of these is an answer."""

    COMPLETED = "completed"
    STUCK = "stuck"
    REFUSED = "refused"
    NO_PROGRESS = "no_progress"
    UNPREDICTED = "unpredicted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNREADABLE = "unreadable"


@dataclass
class RunOutcome:
    status: RunStatus
    answer: Optional[Fact] = None
    trace: List[str] = field(default_factory=list)
    steps_taken: int = 0
    contradictions: List[str] = field(default_factory=list)
    detail: str = ""

    @property
    def produced_answer(self) -> bool:
        return self.status is RunStatus.COMPLETED and self.answer is not None


@dataclass(frozen=True)
class Procedure:
    """An ordered decision list over learned operators.

    Guarded steps precede unguarded ones, so a step that applies only in a
    particular condition is never shadowed by the general case. Order within
    each group is the order the steps were added.
    """

    steps: Tuple[Step, ...] = ()
    terminal: str = "RESULT"

    def extended(self, step: Step, position: Optional[int] = None) -> "Procedure":
        """Add a step, optionally at a chosen priority among the guarded ones.

        WHERE a guarded step goes is part of the procedure, not a detail. Two
        guards can both hold in one state -- a word is both the first one and a
        determiner -- and which fires is decided here. Appending always made
        that decision by the order the demands happened to arrive in, which is
        the order the EXAMPLES happened to be listed in.
        """
        guarded = [s for s in self.steps if s.is_guarded]
        plain = [s for s in self.steps if not s.is_guarded]
        if not step.is_guarded:
            plain.append(step)
        elif position is None:
            guarded.append(step)
        else:
            guarded.insert(position, step)
        return Procedure(steps=tuple(guarded + plain), terminal=self.terminal)

    def guards_used(self) -> List[Tuple[Fact, ...]]:
        return [s.guard for s in self.steps]

    def select(self, state: FrozenSet[Fact]) -> Optional[Tuple[Step, List[RuleEffects]]]:
        """The first step whose guard holds and whose operator applies."""
        for step in self.steps:
            if not step.holds(state):
                continue
            asserted = step.operator.instances(state)
            if asserted is None:
                continue
            return step, asserted
        return None

    def run(self, actuator: Actuator, max_steps: int) -> RunOutcome:
        """Execute against a real actuator until it answers or cannot continue."""
        trace: List[str] = []
        contradictions: List[str] = []

        for taken in range(max_steps + 1):
            state = actuator.observe()
            if state is None:
                return RunOutcome(RunStatus.UNREADABLE, trace=trace, steps_taken=taken,
                                  detail="the world could not be read")

            answer = next((f for f in sorted(state) if f.predicate == self.terminal), None)
            if answer is not None:
                return RunOutcome(RunStatus.COMPLETED, answer=answer, trace=trace,
                                  steps_taken=taken, contradictions=contradictions)
            if taken == max_steps:
                return RunOutcome(RunStatus.BUDGET_EXHAUSTED, trace=trace,
                                  steps_taken=taken, contradictions=contradictions,
                                  detail=f"no answer within {max_steps} steps")

            selected = self.select(state)
            if selected is None:
                return RunOutcome(RunStatus.STUCK, trace=trace, steps_taken=taken,
                                  contradictions=contradictions,
                                  detail="no step applies in this state")

            step, asserted = selected
            if not actuator.perform(step.operator.action):
                return RunOutcome(RunStatus.REFUSED, trace=trace, steps_taken=taken,
                                  contradictions=contradictions,
                                  detail=f"the world refused {step.operator.name}, "
                                         f"which the learned model said applied")

            after = actuator.observe()
            if after is None:
                return RunOutcome(RunStatus.UNREADABLE, trace=trace, steps_taken=taken + 1,
                                  detail="the world could not be read after acting")
            if after == state:
                return RunOutcome(RunStatus.NO_PROGRESS, trace=trace, steps_taken=taken + 1,
                                  contradictions=contradictions,
                                  detail=f"{step.operator.name} changed nothing observable")

            trace.append(step.operator.name)
            evidence = _verify_step(step, asserted, after, before=state)
            if evidence is RuntimeOutcome.CONTRADICTION:
                contradictions.append(f"step {taken + 1}: {step.operator.name}")

        return RunOutcome(RunStatus.BUDGET_EXHAUSTED, trace=trace, steps_taken=max_steps,
                          contradictions=contradictions)


def _verify_step(step: Step, asserted: Sequence[RuleEffects], after: FrozenSet[Fact],
            before: Optional[FrozenSet[Fact]] = None) -> RuntimeOutcome:
    """Check the learned model's prediction against what the world now shows.

    A retraction the same step re-asserts is not checked as a retraction: a
    register whose value is overwritten with the value it held retracts and
    adds the same fact, and reading that as a failed delete would report a
    contradiction where the model and the world agree.

    An effect still carrying a variable is one the operator declared it could
    not predict -- a value only running the action produces. It is checked
    against what the step CHANGED rather than looked up in the whole world.
    """
    outcomes = []
    for index, effects in enumerate(asserted):
        predicted = RuleEffects(add=effects.add,
                                delete=effects.delete - effects.add)
        observation = ToolObservation(
            observation_id=f"{step.operator.name}#{index}",
            tool_name=step.operator.name, invoked=True,
            tool_reported_success=True, observed=True, facts=after, before=before)
        outcomes.append(verify_effects(predicted, observation,
                                       operator=step.operator.name).outcome)
    if RuntimeOutcome.CONTRADICTION in outcomes:
        return RuntimeOutcome.CONTRADICTION
    if outcomes and all(o is RuntimeOutcome.CONFIRMATION for o in outcomes):
        return RuntimeOutcome.CONFIRMATION
    return RuntimeOutcome.INDETERMINATE


class SynthesisStatus(Enum):
    PROCEDURE_DERIVED = "procedure_derived"
    MULTIPLE_PROCEDURES = "multiple_procedures"
    NO_PROCEDURE = "no_procedure"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class IOExample:
    """One input the procedure must handle, and what it must produce.

    `build` returns a FRESH actuator every time: a candidate that ran halfway
    and stopped has left the world in a state its successor must not inherit.
    """

    label: str
    build: Callable[[], Actuator]
    #: Every term of the required answer, not only the first. A procedure that
    #: produces a STRUCTURE -- a reading with a subject and an object -- was
    #: scored on its first argument alone, so a procedure that got the subject
    #: right and the object wrong counted as correct.
    expected: Tuple[str, ...]
    max_steps: int

    def __post_init__(self):
        if isinstance(self.expected, str):
            object.__setattr__(self, "expected", (self.expected,))
        else:
            object.__setattr__(self, "expected", tuple(self.expected))


@dataclass
class SynthesisResult:
    status: SynthesisStatus
    procedures: List[Procedure] = field(default_factory=list)
    size: Optional[int] = None
    candidates_run: int = 0
    detail: str = ""

    @property
    def procedure(self) -> Optional[Procedure]:
        """The derived procedure, and only when the evidence determined one."""
        return (self.procedures[0]
                if self.status is SynthesisStatus.PROCEDURE_DERIVED else None)


def _registers(state: FrozenSet[Fact]) -> Dict[str, Tuple[str, ...]]:
    """Single-valued observations -- a register holds one value: predicate -> args.

    A predicate seen with two values in one state is not a register here and is
    left out, so the write-once rule never fires on a genuinely multi-valued
    observation."""
    reg: Dict[str, Tuple[str, ...]] = {}
    multi: Set[str] = set()
    for f in state:
        if len(f.args) != 1:
            continue
        if f.predicate in reg and reg[f.predicate] != f.args:
            multi.add(f.predicate)
        reg[f.predicate] = f.args
    for pred in multi:
        reg.pop(pred, None)
    return reg


def _cursor_predicates(example: "IOExample", operators: Sequence[Operator]) -> FrozenSet[str]:
    """Registers advanced by MOST operators -- cursors/counters that move every
    step by design, so the write-once rule must not apply to them. A value
    register is written by the one or two operators that bind it; a cursor is
    moved by nearly all of them, which tells them apart without naming either."""
    counts: Dict[str, int] = {}
    applicable = 0
    for op in operators:
        m = example.build()
        before = _registers(m.observe() or frozenset())
        if not m.perform(op.action):
            continue
        applicable += 1
        for pred, val in _registers(m.observe() or frozenset()).items():
            if before.get(pred) != val:
                counts[pred] = counts.get(pred, 0) + 1
    if applicable == 0:
        return frozenset()
    return frozenset(p for p, c in counts.items() if c * 2 > applicable)


def _destructive(before: FrozenSet[Fact], after: FrozenSet[Fact],
                 initial: Dict[str, Tuple[str, ...]], cursors: FrozenSet[str]) -> bool:
    """Did the step OVERWRITE a committed VALUE register with an unrelated value?

    A register may be set from its unset value (a bind) or grown so the new
    value still carries the old (an extend). Replacing a committed value with
    one that does not build on it is destructive -- the wasted earlier write is
    the redundant path that makes trace choice ambiguous. Cursors are exempt.

    An extend is textual for a symbolic value ("a" -> "a_b") and NUMERIC for a
    counter or accumulator: TALLY commits A := A_PLUS_ONE, ACCUM commits A :=
    A_PLUS_HEAD. The new value was COMPUTED by the machine and is present as
    another register's value in `before`, so committing it is a derived extend,
    not a wasteful overwrite -- without this, every accumulation past the first
    reads as destructive and no counting or summing procedure can be found."""
    rb, ra = _registers(before), _registers(after)
    computed_before = set(rb.values())
    for pred, old in rb.items():
        if pred in cursors:
            continue
        new = ra.get(pred)
        if new is None or new == old:
            continue
        if old == initial.get(pred):
            continue
        old_tokens = "_".join(old).split("_")
        new_tokens = "_".join(new).split("_")
        if all(tok in new_tokens for tok in old_tokens):
            continue
        if new in computed_before:
            continue
        return True
    return False


def _terminal_fact(state: FrozenSet[Fact], terminal: str) -> Optional[Fact]:
    return next((f for f in sorted(state) if f.predicate == terminal), None)


# ---- the policy CSP: one operator per abstract state ----------------------
def _run_under_policy(example, policy, by_name, terminal, guard_set,
                      initial, cursors):
    """Follow the policy deterministically. Returns 'ok' / 'wrong' / 'dead', or
    ('need', guard_subset, applicable) -- a state the policy has not decided."""
    expected = tuple(example.expected)
    act = example.build()
    for _ in range(example.max_steps + 1):
        state = act.observe()
        if state is None:
            return "dead"
        ans = _terminal_fact(state, terminal)
        if ans is not None:
            return "ok" if tuple(ans.args) == expected else "wrong"
        gs = frozenset(g for g in guard_set if g in state)
        if gs not in policy:
            applicable = tuple(name for name, op in by_name.items()
                               if op.instances(state) is not None)
            return ("need", gs, applicable)
        op = by_name[policy[gs]]
        if op.instances(state) is None:
            return "dead"
        before = state
        if not act.perform(op.action):
            return "dead"
        after = act.observe()
        if after is None or after == before:
            return "dead"
        if _destructive(before, after, initial, cursors):
            return "dead"
    return "dead"


def _search_policies(examples, by_name, terminal, guard_set, max_policies, stats):
    """Backtracking over guard-state -> operator. Collects up to `max_policies`
    distinct consistent policies so underdetermination survives."""
    prep = [( _registers(e.build().observe() or frozenset()),
              _cursor_predicates(e, list(by_name.values())) ) for e in examples]
    found: List[Dict[FrozenSet[Fact], str]] = []
    seen: Set[frozenset] = set()

    def recurse(policy):
        if len(found) >= max_policies:
            return
        need = None
        for example, (initial, cursors) in zip(examples, prep):
            stats["runs"] += 1
            r = _run_under_policy(example, policy, by_name, terminal, guard_set,
                                  initial, cursors)
            if r == "ok":
                continue
            if isinstance(r, tuple):
                need = r
                break
            return  # 'wrong' / 'dead'
        if need is None:
            sig = frozenset(policy.items())
            if sig not in seen:
                seen.add(sig)
                found.append(dict(policy))
            return
        _, gs, applicable = need
        for op_name in applicable:
            policy[gs] = op_name
            recurse(policy)
            del policy[gs]
            if len(found) >= max_policies:
                return

    recurse({})
    return found


# ---- generalise a policy to the fewest guarded rules ----------------------
class _Point:
    __slots__ = ("present", "applicable", "chosen")

    def __init__(self, present, applicable, chosen):
        self.present, self.applicable, self.chosen = present, applicable, chosen


def _points_under_policy(examples, policy, by_name, terminal, guard_set):
    points: List[_Point] = []
    for example in examples:
        act = example.build()
        for _ in range(example.max_steps + 1):
            state = act.observe()
            if state is None or _terminal_fact(state, terminal) is not None:
                break
            gs = frozenset(g for g in guard_set if g in state)
            if gs not in policy:
                break
            applicable = frozenset(name for name, op in by_name.items()
                                   if op.instances(state) is not None)
            points.append(_Point(gs, applicable, policy[gs]))
            act.perform(by_name[policy[gs]].action)
    return points


def _rule_eligible(guard, op_name, p) -> bool:
    return op_name in p.applicable and all(g in p.present for g in guard)


def _greedy_guard(op_name, remaining, guard_pool):
    """The most general guard under which every eligible point chose op_name.

    Built by GREEDY separation instead of enumerating 2**flags subsets: start
    unguarded, and while the rule would misfire (cover a point that chose a
    different operator), add the one flag that is present in every op_name point
    and excludes the most misfiring ones. Polynomial in flags, so the flag
    vocabulary can grow without the generalisation blowing up. Returns
    (guard, covered_points) or None when the flags cannot separate it."""
    guard: Tuple[Fact, ...] = ()
    while True:
        covered = [p for p in remaining if _rule_eligible(guard, op_name, p)]
        good = [p for p in covered if p.chosen == op_name]
        bad = [p for p in covered if p.chosen != op_name]
        if not good:
            return None
        if not bad:
            return guard, good
        # Add the flag that excludes the most misfiring points while keeping some
        # of this operator's points. Dropping some good points is FINE -- they
        # are picked up by a later rule for the same operator under a different
        # guard, which is how one operator that fires in two conditions becomes
        # two rules. For a consistent policy good and bad points always differ in
        # a flag, so a separator always exists.
        best_flag, best_score = None, None
        for flag in guard_pool:
            if flag in guard:
                continue
            kept_good = sum(1 for p in good if flag in p.present)
            excluded_bad = sum(1 for p in bad if flag not in p.present)
            if kept_good == 0 or excluded_bad == 0:
                continue
            score = (excluded_bad, kept_good)
            if best_score is None or score > best_score:
                best_score, best_flag = score, flag
        if best_flag is None:
            return None  # flags cannot separate these (should not happen here)
        guard = guard + (best_flag,)


def _induce_decision_list(points, by_name, guards, max_rules):
    """Ordered rules so at every point the FIRST eligible rule's operator is the
    one chosen. Sequential covering with greedy guard construction -- most
    general first, refined only where it would misfire."""
    guard_pool = list(guards)
    remaining = list(points)
    order: List[Step] = []
    while remaining:
        if len(order) > max_rules:
            return None
        best = None  # (coverage, -guard_len, op_name, guard, covered)
        for op_name in by_name:
            found = _greedy_guard(op_name, remaining, guard_pool)
            if found is None:
                continue
            guard, covered = found
            score = (len(covered), -len(guard))
            if best is None or score > best[:2]:
                best = (len(covered), -len(guard), op_name, guard, covered)
        if best is None:
            return None
        _, _, op_name, guard, covered = best
        order.append(Step(guard=tuple(guard), operator=by_name[op_name]))
        ids = {id(p) for p in covered}
        remaining = [p for p in remaining if id(p) not in ids]
    return order if len(order) <= max_rules else None


def _order_steps(steps: List[Step]) -> Tuple[Step, ...]:
    guarded = [s for s in steps if s.is_guarded]
    plain = [s for s in steps if not s.is_guarded]
    return tuple(guarded + plain)


def _verify(procedure: Procedure, examples) -> bool:
    for example in examples:
        outcome = procedure.run(example.build(), example.max_steps)
        if outcome.status is not RunStatus.COMPLETED or outcome.contradictions:
            return False
        if outcome.answer is None or tuple(outcome.answer.args) != tuple(example.expected):
            return False
    return True


def derive_procedure(
    operators: Sequence[Operator],
    guards: Sequence[Fact],
    examples: Sequence[IOExample],
    terminal: str = "RESULT",
    max_rules: int = DEFAULT_MAX_RULES,
    max_policies: int = 8,
) -> SynthesisResult:
    """Derive a length-general procedure from input/output evidence alone."""
    guard_learning("procedure synthesis")

    if len(examples) < 2:
        return SynthesisResult(
            status=SynthesisStatus.INSUFFICIENT_EVIDENCE,
            detail=(f"{len(examples)} example(s); a procedure that must hold across "
                    f"inputs needs at least 2 to be constrained by more than one"))
    if not operators:
        return SynthesisResult(
            status=SynthesisStatus.INSUFFICIENT_EVIDENCE,
            detail="no learned operators were offered; nothing could be composed")

    by_name: Dict[str, Operator] = {op.action.predicate: op for op in operators}
    guard_set = tuple(guards)
    stats = {"runs": 0}

    policies = _search_policies(examples, by_name, terminal, guard_set,
                                max_policies, stats)
    if not policies:
        return SynthesisResult(
            status=SynthesisStatus.NO_PROCEDURE, candidates_run=stats["runs"],
            detail=("no assignment of one operator per abstract state reads every "
                    f"example with the {len(operators)} operator(s) offered"))

    kept: List[Procedure] = []
    signatures: Set[Tuple] = set()
    size: Optional[int] = None
    for policy in policies:
        points = _points_under_policy(examples, policy, by_name, terminal, guard_set)
        steps = _induce_decision_list(points, by_name, guard_set, max_rules)
        if steps is None:
            continue
        procedure = Procedure(steps=_order_steps(steps), terminal=terminal)
        if not _verify(procedure, examples):
            continue
        sig = tuple((e.label, tuple(procedure.run(e.build(), e.max_steps).trace))
                    for e in examples)
        if sig in signatures:
            continue
        signatures.add(sig)
        kept.append(procedure)
        size = len(steps) if size is None else min(size, len(steps))

    if not kept:
        return SynthesisResult(
            status=SynthesisStatus.NO_PROCEDURE, candidates_run=stats["runs"],
            detail=(f"a consistent policy exists but none states within {max_rules} "
                    f"rule(s); the bound was reached, not proven insufficient"))
    if len(kept) == 1:
        return SynthesisResult(status=SynthesisStatus.PROCEDURE_DERIVED,
                               procedures=kept, size=size,
                               candidates_run=stats["runs"])
    return SynthesisResult(
        status=SynthesisStatus.MULTIPLE_PROCEDURES, procedures=kept, size=size,
        candidates_run=stats["runs"],
        detail=(f"{len(kept)} procedures take different routes to the required "
                f"answers on every example; an input separating them would decide"))


__all__ = ["Actuator", "Operator", "Step", "Procedure", "RunStatus", "RunOutcome",
           "IOExample", "SynthesisResult", "SynthesisStatus", "derive_procedure",
           "DEFAULT_MAX_RULES"]
