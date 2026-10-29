#!/usr/bin/env python3
"""Turning learned rules into operators a state planner can search over.

Learned rules are lifted -- MOVE(?X0,?X2,?X1) with variables. The planner is
propositional: its actions carry ground condition strings. Bridging them is
grounding, and it is the only thing standing between "Lyric learned a
transition rule" and "Lyric can compose learned transitions toward a goal".

Two admissibility rules, both consequences of work already done rather than new
policy:

  VALIDATED only. CANDIDATE, SUPPORTED and REFUTED rules are not executable
  cognition. The KITE-17 ablation established that this gate causally controls
  derivation, so planning must not quietly widen it.

  An action is required. A rule with action=None records that something
  followed from conditions, not that the agent can bring it about. Offering it
  as an operator would let the planner "achieve" a goal by asserting that the
  world happens to change. Rules stored before `action` existed read back with
  None and are correctly excluded.

Grounding enumerates variable assignments over the constants present in the
problem. That is exponential in the number of variables per rule, so the bound
is explicit and a run that hits it says so rather than returning a quietly
partial operator set -- a planner that silently lost operators would report
UNREACHABLE for a goal it simply was not given the means to reach.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
from dataclasses import dataclass, field
from typing import (Any, Dict, FrozenSet, Iterable, List, Optional, Sequence,
                    Set, Tuple)

from core.learning.rule_induction import (BindingOrigin, CandidateRule, Fact,
                                          is_variable)
from core.reasoning.value_authority import evaluate

logger = logging.getLogger(__name__)

#: Ceiling on grounded operators. Reached only by rules with several variables
#: over a large constant universe; reported, never silently truncated.
DEFAULT_MAX_OPERATORS = 5000

#: How many times the producible-term closure may widen before it is called
#: unconverged. Each pass admits the values produced by the pass before it, so
#: this is the longest chain of runtime-produced values a plan may thread --
#: read a file, parse what it held, compute from that, is three.
DEFAULT_CLOSURE_PASSES = 6


@dataclass(frozen=True)
class GroundOperator:
    """One concrete action, and the learned rule it came from."""

    name: str
    preconditions: Tuple[str, ...]
    effects: Tuple[str, ...]
    deletes: Tuple[str, ...]
    rule_id: Optional[str] = None
    bindings: Tuple[Tuple[str, str], ...] = ()
    #: True when some argument could only be filled by a term an action invents
    #: at runtime. Such an operator is offered PARTIALLY ground: the planner
    #: binds the rest by matching the state it is actually in.
    #:
    #: Enumerating those arguments here is impossible on purpose -- the term
    #: does not exist yet -- and minting one placeholder per ground action would
    #: give every occurrence of the action the same unknown, so two reads of a
    #: file would be one answer and the search would dedupe the second away.
    open_slots: Tuple[str, ...] = ()
    #: The values this action produces, unresolved. Resolved per APPLICATION, so
    #: each occurrence yields its own unknown and a value computable from the
    #: terms then in hand is computed rather than deferred.
    outputs: Tuple[Dict[str, Any], ...] = ()
    #: What must not hold for the operator to apply (`CandidateRule.absent`),
    #: under its bindings; a variable left in one means "any such fact".
    absent: Tuple[str, ...] = ()

    def to_action(self) -> Dict[str, Any]:
        """The shape TemporalReasoningSystem searches over."""
        return {
            "name": self.name,
            "preconditions": list(self.preconditions),
            "effects": list(self.effects),
            "deletes": list(self.deletes),
            "rule_id": self.rule_id,
            "bindings": dict(self.bindings),
            "open": bool(self.open_slots),
            "open_slots": list(self.open_slots),
            "outputs": [dict(o) for o in self.outputs],
            "absent": list(self.absent),
        }


@dataclass
class GroundingReport:
    """What was offered to the planner, and what was withheld."""

    operators: List[GroundOperator] = field(default_factory=list)
    truncated: bool = False
    rules_used: List[str] = field(default_factory=list)
    rules_skipped: Dict[str, str] = field(default_factory=dict)
    rules_unreachable: Dict[str, str] = field(default_factory=dict)
    #: Rules grounded and yielding no operator, with why.
    rules_unmatched: Dict[str, str] = field(default_factory=dict)
    constants: List[str] = field(default_factory=list)
    closure_converged: bool = True

    def to_actions(self) -> List[Dict[str, Any]]:
        return [operator.to_action() for operator in self.operators]

    @property
    def complete(self) -> bool:
        """False when the operator set is known to be partial.

        A planner given a partial set can still find a plan, but its
        UNREACHABLE verdict is no longer a proof.

        This was `not self.truncated`, which accounts only for the operator
        LIMIT. Rules skipped for any other reason did not count -- so a
        grounding that discarded EVERY rule it was given and produced zero
        operators still reported complete, and the planner's UNREACHABLE was
        certified as a proof of impossibility over an empty operator set.

        Observed: both validated rules skipped as "no action recorded", 0
        operators, complete=True, planner UNREACHABLE. "I know of no way to do
        this" was being presented as "this cannot be done".

        `rules_unreachable` closes the second way the same claim can be false.
        Counting only DROPPED rules assumes an offered rule can fire, and a
        rule whose precondition names a predicate that nothing in the problem
        supplies and no operator produces cannot fire in any state the search
        can construct.

        Observed again, on the composition of two derived folds: three rules
        in, three used, none skipped, 48 operators, complete=True, planner
        UNREACHABLE -- while the world reached the goal in three steps. DIVIDE
        required QUOTIENT, the divider publishes QUOTIENT only after its
        operands are loaded, and no learned rule could predict it. The model
        was blind to a fact the world produces, and the verdict built on it was
        being certified as a proof of impossibility.
        """
        return (not self.truncated and not self.rules_skipped
                and not self.rules_unreachable and self.closure_converged)


def constants_in(facts: Iterable[Fact]) -> Set[str]:
    """Every ground term mentioned. Variables are not constants."""
    return {arg for fact in facts for arg in fact.args if not is_variable(arg)}


def invented_positions(rules: Sequence[Any]) -> Set[Tuple[str, int]]:
    """Argument positions that can hold a term some action invents at runtime.

    A value an action produces has no term until the action runs, so no amount
    of enumeration reaches it and every consumer of one has to bind it by
    matching instead. Which consumers those are is decidable here: a position
    is reachable by an invented term if some rule asserts an output variable
    there, or asserts a variable it bound from a position already reachable.

    The fixpoint is over predicate positions, of which there are finitely many
    and few, rather than over terms -- which is why it settles immediately
    where a closure over the terms themselves cannot settle at all.
    """
    reachable: Set[Tuple[str, int]] = set()
    for _ in range(len(list(rules)) + 1):
        grew = False
        for stored in rules:
            rule = getattr(stored, "rule", stored)
            produced = {o.variable for o in rule.outputs}
            carried = {
                argument
                for fact in rule.preconditions
                for position, argument in enumerate(fact.args)
                if (fact.predicate, position) in reachable and is_variable(argument)
            }
            unknown = produced | carried
            for fact in rule.effects.add:
                for position, argument in enumerate(fact.args):
                    key = (fact.predicate, position)
                    if argument in unknown and key not in reachable:
                        reachable.add(key)
                        grew = True
        if not grew:
            break
    return reachable


def supply_from(facts: Iterable[Fact]) -> Dict[Tuple[str, int], Set[str]]:
    """Which terms can stand at each argument position of each predicate.

    A variable in `NUMBER(?n)` can only ever be a term some `NUMBER` fact
    holds. Enumerating every constant of the problem for it instead is what
    made grounding exponential -- and, once actions began producing values,
    unbounded: every pass minted an operator per candidate answer, and each of
    those widened the universe for the next pass, so the closure never settled.
    Measured: chains of four actions produced thousands of operators and the
    planner exhausted its node bound without leaving the first two steps.

    This is the value half of the supplier graph, at the resolution that makes
    it useful: not "which predicates can exist" but "which terms can appear
    where".
    """
    supply: Dict[Tuple[str, int], Set[str]] = {}
    for fact in facts:
        for position, argument in enumerate(fact.args):
            # A goal may name a variable where any term will do; a variable is
            # not a term that can stand anywhere.
            if not is_variable(argument):
                supply.setdefault((fact.predicate, position), set()).add(argument)
    return supply


def facts_held(facts: Iterable[Fact]) -> Dict[str, Set[Tuple[str, ...]]]:
    """Which argument tuples each predicate can hold: the facts themselves,
    grouped for joining. `supply_from` says which terms can stand at a position;
    this says which terms can stand TOGETHER, which is what a precondition
    naming two variables asks."""
    held: Dict[str, Set[Tuple[str, ...]]] = {}
    for fact in facts:
        held.setdefault(fact.predicate, set()).add(tuple(fact.args))
    return held


def _join(literals: Sequence[Fact], variables: Sequence[str],
          open_slots: Sequence[str],
          held: Dict[str, Set[Tuple[str, ...]]]) -> List[Dict[str, str]]:
    """Every assignment of `variables` under which each literal is a fact that
    can hold. An open slot is bound when the plan runs, so it matches anything
    here and is left unbound."""
    wanted = set(variables)
    # Only a literal naming a variable drawn here constrains the draw. One that
    # names only a value some act will invent has no fact to match until that
    # act runs; it is bound during the search, never here.
    order = sorted((f for f in literals if wanted & set(f.args)),
                   key=lambda f: len(held.get(f.predicate, ())))
    rows: Dict[Tuple[Tuple[str, str], ...], Dict[str, str]] = {}

    def extend(index: int, bound: Dict[str, str]) -> None:
        if index == len(order):
            row = {v: bound[v] for v in variables if v in bound}
            if set(row) == wanted:
                rows.setdefault(tuple(sorted(row.items())), row)
            return
        literal = order[index]
        for args in held.get(literal.predicate, ()):
            if len(args) != len(literal.args):
                continue
            extended = dict(bound)
            for pattern, value in zip(literal.args, args):
                if is_variable(pattern):
                    if pattern in open_slots:
                        continue
                    if extended.setdefault(pattern, value) != value:
                        break
                elif pattern != value:
                    break
            else:
                extend(index + 1, extended)

    extend(0, {})
    return [rows[key] for key in sorted(rows)]


class _OneTerm:
    """The terms for the variables `ground_rule` grounds once: the first, in
    the order they rank, under which the act may be taken in the state the
    problem starts in -- nothing it needs absent holds, and its successes
    covered the case (`untested_conditions`, as the constitution reads it at
    the act). Where none may, the first, which the planner refuses as it would
    any other. Terms no fact names differ in nothing the act could be refused
    for, so one of them stands for all."""

    def __init__(self, rule: CandidateRule, variables: List[str],
                 ranked: List[List[str]],
                 held: Optional[Dict[str, Set[Tuple[str, ...]]]],
                 successes: Optional[Sequence[FrozenSet[str]]]):
        self.rule = rule
        self.variables = variables
        self.ranked = ranked
        self.held = held
        self.successes = [frozenset(s) for s in successes or ()]
        self.facts = [Fact(predicate, tuple(args))
                      for predicate, rows in (held or {}).items() for args in rows]
        self.about: Dict[str, Set[Fact]] = {}
        for fact in self.facts:
            for term in set(fact.args):
                self.about.setdefault(term, set()).add(fact)

    def __call__(self, bindings: Dict[str, str]) -> Dict[str, str]:
        first = {v: ranked[0] for v, ranked in zip(self.variables, self.ranked)}
        if not self.variables or self.held is None or not (self.successes or self.rule.absent):
            return first
        options = []
        for ranked in self.ranked:
            bare = next((t for t in ranked if t not in self.about), None)
            options.append([t for t in ranked if t in self.about or t == bare])
        for values in itertools.product(*options):
            chosen = dict(zip(self.variables, values))
            if self._may({**bindings, **chosen}):
                return chosen
        return first

    def _may(self, bindings: Dict[str, str]) -> bool:
        from core.reasoning.unification import match_literal
        from core.learning.unified_learning_system import _by_place, _uncovered
        action = self.rule.action.substitute(bindings)
        for literal in self.rule.absent:
            literal = literal.substitute(bindings)
            if not literal.variables:
                if tuple(literal.args) in self.held.get(literal.predicate, set()):
                    return False
            elif match_literal(literal, self.facts):
                return False
        if self.successes:
            named = set(action.args)
            here = {f for term in named for f in self.about.get(term, ())
                    if set(f.args) <= named}
            present = frozenset(c for c in _by_place(here, action) if "_" not in c)
            if _uncovered(present, self.successes):
                return False
        return True


def ground_rule(
    rule: CandidateRule,
    supply: Dict[Tuple[str, int], Set[str]],
    universe: Sequence[str] = (),
    rule_id: Optional[str] = None,
    limit: int = DEFAULT_MAX_OPERATORS,
    invented: Optional[Set[Tuple[str, int]]] = None,
    held: Optional[Dict[str, Set[Tuple[str, ...]]]] = None,
    targets: Optional[Dict[Tuple[str, int], Set[str]]] = None,
    relevant: FrozenSet[str] = frozenset(),
    successes: Optional[Sequence[FrozenSet[str]]] = None,
    start: Optional[Dict[str, Set[Tuple[str, ...]]]] = None,
) -> Tuple[List[GroundOperator], bool]:
    """Every instantiation of one rule that could ever apply. (operators, truncated).

    THREE KINDS OF ARGUMENT, AND ONLY ONE OF THEM IS ENUMERATED.

      supplied   a term the problem holds or an action puts there. Enumerated,
                 and only over the terms that can stand where it stands.
      invented   a term some action will produce at runtime. Left OPEN: it has
                 no name yet, so the planner binds it against the state it is
                 actually in, and every occurrence of the action gets its own.
      produced   a value THIS action makes. Neither enumerated nor open --
                 resolved per application, by computing it or by minting an
                 unknown for that occurrence.

    Enumerating the second would mean inventing candidate answers and letting
    the planner keep whichever reached the goal. Enumerating the third would be
    the same mistake one step earlier.

    `successes` are the act's recorded successes as the conditions of the
    things it named (`_conditions`), when the caller has them; `start` is what
    holds where the problem starts (`held` grows with what acts would produce).
    """
    if rule.action is None:
        return [], False

    invented = invented or set()
    origins = rule.binding_origins()
    variables = sorted(v for v, origin in origins.items()
                       if origin in (BindingOrigin.STATE, BindingOrigin.ACTION_INPUT))

    # THE PRECONDITIONS CONSTRAIN, THE ACTION DOES NOT. What terms may stand in
    # the action literal is the question grounding exists to answer: no state
    # contains MOVE(z, HALL, LAB) before anything offers it. So the action's
    # arguments are narrowed by the preconditions they also appear in, and a
    # variable that appears nowhere else is genuinely unconstrained.
    positions: Dict[str, List[Tuple[str, int]]] = {v: [] for v in variables}
    for fact in rule.preconditions:
        for position, argument in enumerate(fact.args):
            if argument in positions:
                positions[argument].append((fact.predicate, position))

    open_slots = sorted(v for v in variables
                        if any(key in invented for key in positions[v]))
    closed = [v for v in variables if v not in open_slots]

    # WHAT A PRECONDITION CONSTRAINS IS CONSTRAINED JOINTLY. Enumerating each
    # variable over the terms its positions can hold, and taking the product,
    # pairs every file with every size when the precondition is SIZE(file,
    # size): operators whose preconditions can never hold, in their thousands,
    # until the bound cuts off the ones that could. Where the facts are known,
    # the variables are drawn from them together.
    joined = [v for v in closed if positions[v]]
    free = [v for v in closed if not positions[v]]
    for variable in joined:
        if not set.intersection(*(supply.get(key, set()) for key in positions[variable])):
            return [], False
    if held is not None:
        rows = _join(rule.preconditions, joined, open_slots, held)
    else:
        rows = [dict(zip(joined, values)) for values in itertools.product(*(
            sorted(set.intersection(*(supply.get(key, set()) for key in positions[v])))
            for v in joined))]
    # A VARIABLE NO PRECONDITION CONSTRAINS is one the act puts somewhere, so it
    # ranges over the terms that somewhere can hold -- in the world, in what the
    # goal asks for, or in what another act produces. Only where its effects
    # name positions nothing holds does it range over every constant.
    effect_positions: Dict[str, List[Tuple[str, int]]] = {v: [] for v in free}
    for fact in list(rule.effects.add) + list(rule.effects.delete):
        for position, argument in enumerate(fact.args):
            if argument in effect_positions:
                effect_positions[argument].append((fact.predicate, position))
    # WHAT THE GOAL NAMES IS GROUNDED FIRST. The set grounded does not change;
    # only its order does, so that when the bound cuts, it cuts what bears on
    # the goal least -- not whatever happened to sort last.
    def first_the_goal(term: str):
        return (term not in relevant, term)

    # A VARIABLE NOTHING READS OR CHANGES is grounded once. Named by no
    # precondition, no effect and no output's inputs, every term it could take
    # gives an operator with the same preconditions and the same effects: the
    # search expands the first and finds every other's successor already seen.
    # Enumerated over every constant, an act with two such arguments in a world
    # of some two hundred things made forty thousand of them, enough to reach
    # the bound and leave the set partial, with every plan the same as from the
    # first.
    #
    # THE ONE KEPT IS ONE THE ACT MAY BE TAKEN ON. The same preconditions and
    # effects are not the same standing: a term something the rule needs absent
    # holds of is blocked, and one in a case none of the act's successes
    # covered is sent back by the constitution (Law 2). Kept as the first term
    # it sorts to, the act in RULE-AUTHORITY-02's world 0 named a thing in
    # neither relation every success had with its third argument, and every
    # goal the world allowed went unplanned. So it is chosen per row, from the
    # state the problem starts in (`_one_term`).
    read_by_outputs = {name for output in rule.outputs for name in output.inputs}
    spread: List[str] = []
    candidates: List[List[str]] = []
    once: List[str] = []
    once_ranked: List[List[str]] = []
    for variable in free:
        pool: Set[str] = set()
        for key in effect_positions[variable]:
            pool |= (targets or {}).get(key, set())
        ranked = sorted(pool or set(universe), key=first_the_goal)
        if not effect_positions[variable] and variable not in read_by_outputs:
            once.append(variable)
            once_ranked.append(ranked)
        else:
            spread.append(variable)
            candidates.append(ranked)
    rows.sort(key=lambda row: (-sum(value in relevant for value in row.values()),
                               tuple(sorted(row.items()))))
    if not all(once_ranked):
        return [], False
    choose = _OneTerm(rule, once, once_ranked, start if start is not None else held, successes)

    produced = tuple({
        "variable": output.variable,
        "origin": output.origin.value,
        "function": output.function,
        "producer": output.producer,
        "inputs": list(output.inputs),
    } for output in rule.outputs)

    operators: List[GroundOperator] = []
    for assignment, row in itertools.product(itertools.product(*candidates), rows):
        if len(operators) >= limit:
            return operators, True

        bindings = {**row, **dict(zip(spread, assignment))}
        bindings.update(choose(bindings))
        action = rule.action.substitute(bindings)
        operators.append(GroundOperator(
            name=action.to_formula(),
            preconditions=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.preconditions
            )),
            effects=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.effects.add
            )),
            deletes=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.effects.delete
            )),
            rule_id=rule_id,
            bindings=tuple(sorted(bindings.items())),
            open_slots=tuple(open_slots),
            outputs=produced,
            absent=tuple(sorted(
                f.substitute(bindings).to_formula() for f in rule.absent
            )),
        ))
    return operators, False


def _admissible(rules: Sequence[Any]) -> List[Tuple[Optional[str], CandidateRule]]:
    """The rules that may become operators: validated, and naming an act."""
    from core.learning.rule_store import EpistemicStatus
    out = []
    for stored in rules:
        status = getattr(stored, "status", None)
        rule = getattr(stored, "rule", stored)
        if (status is None or status is EpistemicStatus.VALIDATED) and rule.action is not None:
            out.append((getattr(stored, "rule_id", None), rule))
    return out


def _toward_fits(rules: Sequence[Any], toward: Sequence[Fact]) -> bool:
    """Whether grounding back from the goal finds every operator forward
    grounding would use: the goal names its things, no act computes a value,
    and every variable of a rule is bound by its act, its effects or a condition
    no rule changes."""
    if not toward or any(f.variables for f in toward):
        return False
    admissible = _admissible(rules)
    produced = {e.predicate for _, rule in admissible for e in rule.effects.add}
    for _, rule in admissible:
        if rule.outputs:
            return False
        bound = set(rule.action.variables) | set(rule.effects.variables)
        for fact in rule.preconditions:
            if fact.predicate not in produced:
                bound |= set(fact.variables)
        if any(not fact.variables <= bound for fact in rule.preconditions):
            return False
    return True


def _ground_toward(rules, toward, held, start, supply, targets, relevant, covered,
                   constants, limit) -> "GroundingReport":
    """Only the operators that bear on the goal, found back from it.

    GROUNDED FORWARD, A RULE WAS ENUMERATED OVER EVERYTHING ITS CONDITIONS HOLD
    OF, whatever the goal. Two arguments each held by its own condition paired
    every thing holding one with every thing holding the other: in
    RULE-AUTHORITY-02, where a world offers all its practice at once, 562
    groundings reached the 5,000-operator bound, the planner then kept only the
    few the goal could use (`TemporalReasoningSystem._relevant`), and the goal's
    own reason for failing was reported as the bound.

    Back from the goal, an effect that is a fact the goal or a step toward it
    wants binds the rule's variables there; the rest are drawn as forward
    grounding draws them (`ground_rule`), joined only over conditions no rule
    changes, which hold now or never. A condition some rule can bring about is
    left to the steps that would bring it: where it does not hold, it is wanted
    in turn. The operators are those the planner's own relevance keeps
    (`_relevant`), so no plan is lost; `_toward_fits` says where this holds."""
    from core.reasoning.unification import unify
    admissible = _admissible(rules)
    built = GroundingReport(constants=list(constants))
    for stored in rules:
        rule = getattr(stored, "rule", stored)
        rule_id = getattr(stored, "rule_id", None)
        if (rule_id, rule) not in admissible:
            built.rules_skipped[rule_id or str(rule)] = "not executable or names no act"
    produced = {e.predicate for _, rule in admissible for e in rule.effects.add}
    holding = {Fact(predicate, tuple(args)).to_formula()
               for predicate, rows in held.items() for args in rows}
    operators: Dict[Tuple[Optional[str], str], GroundOperator] = {}
    used: Set[str] = set()
    wanted = list(toward)
    asked: Set[str] = set()
    while wanted:
        fact = wanted.pop()
        if fact.to_formula() in asked:
            continue
        asked.add(fact.to_formula())
        for rule_id, rule in admissible:
            successes = (covered or {}).get((rule.action.predicate, len(rule.action.args)))
            for effect in rule.effects.add:
                binding = unify(effect, fact, {})
                if binding is None:
                    continue
                fixed = CandidateRule(
                    body=frozenset(f.substitute(binding) for f in rule.body),
                    effects=rule.effects.substitute(binding),
                    action=rule.action.substitute(binding),
                    absent=frozenset(f.substitute(binding) for f in rule.absent))
                static = CandidateRule(
                    body=frozenset({fixed.action} | {f for f in fixed.preconditions
                                                     if f.predicate not in produced}),
                    effects=fixed.effects, action=fixed.action, absent=fixed.absent)
                found, truncated = ground_rule(
                    static, supply, constants, rule_id, limit - len(operators),
                    held=held, targets=targets, relevant=relevant,
                    successes=[frozenset(s) for s in successes] if successes else None,
                    start=start)
                for partial in found:
                    full = {**binding, **dict(partial.bindings)}
                    name = rule.action.substitute(full).to_formula()
                    # One act, one operator PER RULE: two rules for an act's two
                    # cases give it the same name and different conditions, and
                    # keeping the first by name kept one whose condition did not
                    # hold in place of one whose did (RULE-AUTHORITY-02 world
                    # 646). A condition no rule changes either holds now or never.
                    if (rule_id, name) in operators or any(
                            f.predicate not in produced
                            and f.substitute(full).to_formula() not in holding
                            for f in rule.preconditions if not f.substitute(full).variables):
                        continue
                    operator = GroundOperator(
                        name=name,
                        preconditions=tuple(sorted(f.substitute(full).to_formula()
                                                   for f in rule.preconditions)),
                        effects=tuple(sorted(f.substitute(full).to_formula()
                                             for f in rule.effects.add)),
                        deletes=tuple(sorted(f.substitute(full).to_formula()
                                             for f in rule.effects.delete)),
                        rule_id=rule_id,
                        bindings=tuple(sorted(full.items())),
                        absent=tuple(sorted(f.substitute(full).to_formula()
                                            for f in rule.absent)))
                    operators[(rule_id, name)] = operator
                    used.add(rule_id or str(rule))
                    wanted += [Fact.parse(p) for p in operator.preconditions if p not in holding]
                if truncated or len(operators) >= limit:
                    built.truncated = True
                    logger.warning(
                        "grounding hit the %d-operator bound; the operator set is "
                        "partial and an UNREACHABLE verdict from it is not a proof",
                        limit)
                    built.operators = list(operators.values())
                    built.rules_used = sorted(used)
                    return built
    built.operators = list(operators.values())
    built.rules_used = sorted(used)
    return built


def ground_for_problem(
    rules: Sequence[Any],
    state: Iterable[Fact],
    goal: Iterable[Fact] = (),
    limit: int = DEFAULT_MAX_OPERATORS,
    covered: Optional[Dict[Tuple[str, int], Sequence[Sequence[str]]]] = None,
    toward: Optional[Sequence[Fact]] = None,
) -> GroundingReport:
    """Ground admissible rules over the terms this problem can produce.

    `rules` are StoredRule records; each is checked for executability here
    rather than trusted, so a caller cannot widen the gate by passing a
    candidate. `covered` is each act's recorded successes, by its predicate and
    arity, as the conditions of the things it named. `toward` is the facts the
    goal asks to hold, when it asks nothing to be absent: given, and where no
    act computes a value, only the operators that bear on them are grounded
    (`_ground_toward`).
    """
    from core.learning.rule_store import EpistemicStatus

    state_facts = list(state)
    goal_facts = list(goal)
    report = GroundingReport(
        constants=sorted(constants_in(state_facts) | constants_in(goal_facts)))
    if not report.constants:
        return report

    # WHAT THIS PROBLEM CAN EVER CONTAIN: what it starts with, plus what some
    # rule asserts. A precondition outside that set is one no state reachable
    # in the search will satisfy.
    #
    # Effect predicates cover values an action produces as well as facts it
    # moves: an output is a term inside an effect, so a rule that computes a
    # quotient supplies QUOTIENT here exactly as a rule that copies one does.
    supplied = {f.predicate for f in state_facts} | {
        f.predicate
        for stored in rules
        for f in getattr(stored, "rule", stored).effects.add
    }

    invented = invented_positions(rules)

    def build(supply, held, targets) -> GroundingReport:
        built = GroundingReport(constants=list(report.constants))
        remaining = limit
        for stored in rules:
            rule = getattr(stored, "rule", stored)
            rule_id = getattr(stored, "rule_id", None)
            status = getattr(stored, "status", None)

            if status is not None and status is not EpistemicStatus.VALIDATED:
                built.rules_skipped[rule_id or str(rule)] = (
                    f"not executable: {status.value}")
                continue
            if rule.action is None:
                built.rules_skipped[rule_id or str(rule)] = (
                    "no action recorded; the rule describes what follows, not what "
                    "the agent can do")
                continue

            unsatisfiable = sorted(
                {f.predicate for f in rule.preconditions} - supplied)
            if unsatisfiable:
                built.rules_unreachable[rule_id or str(rule)] = (
                    f"requires {', '.join(unsatisfiable)}, which the problem does not "
                    f"supply and no rule asserts; this rule cannot fire in any state "
                    f"the search can reach")

            successes = (covered or {}).get((rule.action.predicate, len(rule.action.args)))
            operators, truncated = ground_rule(rule, supply, report.constants,
                                               rule_id, remaining, invented=invented,
                                               held=held, targets=targets,
                                               relevant=relevant,
                                               successes=[frozenset(s) for s in successes]
                                               if successes else None,
                                               start=start)
            built.operators.extend(operators)
            built.rules_used.append(rule_id or str(rule))
            if not operators:
                built.rules_unmatched[rule_id or str(rule)] = (
                    "its preconditions hold together for no terms this problem "
                    "has or its rules produce")
            remaining -= len(operators)
            if truncated or remaining <= 0:
                built.truncated = True
                logger.warning(
                    "grounding hit the %d-operator bound; the operator set is "
                    "partial and an UNREACHABLE verdict from it is not a proof",
                    limit)
                break
        return built

    # THE CLOSURE OVER PRODUCIBLE TERMS.
    #
    # An action that moves a term puts it somewhere the problem did not have
    # it: nothing starts with AT(z, LAB), and the operator that would use it
    # cannot be enumerated until the term reaches that position. So what one
    # pass produces is admitted to the next, and grounding repeats until
    # nothing new appears.
    #
    # This closes over terms that ALREADY EXIST. Terms an action invents are
    # not admitted here and cannot be: they have no name until the action runs,
    # which is what `open_slots` is for.
    #
    # FACTS, NOT ONLY TERMS. A precondition's variables are drawn from the facts
    # that can hold, so the closure admits produced facts as facts: which terms
    # arrive TOGETHER, not only which positions each term can reach. The goal's
    # terms join the targets an act can put things into, because that is where
    # the plan must put them.
    relevant = frozenset(constants_in(goal_facts))
    supply = supply_from(state_facts)
    held = facts_held(state_facts)
    start = facts_held(state_facts)
    targets = {key: set(terms) for key, terms in supply.items()}
    for key, terms in supply_from(goal_facts).items():
        targets.setdefault(key, set()).update(terms)
    if toward and not invented and _toward_fits(rules, toward):
        report_body = _ground_toward(
            rules, toward, held, start, supply, targets, relevant, covered,
            report.constants, limit)
    else:
        report_body = build(supply, held, targets)
        for _ in range(DEFAULT_CLOSURE_PASSES):
            produced = [Fact.parse(effect)
                        for operator in report_body.operators for effect in operator.effects
                        if not operator.open_slots]
            new = [f for f in produced if tuple(f.args) not in held.get(f.predicate, set())]
            if not new:
                break
            for fact in new:
                held.setdefault(fact.predicate, set()).add(tuple(fact.args))
            for key, terms in supply_from(new).items():
                supply.setdefault(key, set()).update(terms)
                targets.setdefault(key, set()).update(terms)
            report_body = build(supply, held, targets)
        else:
            report_body.closure_converged = False
            logger.warning(
                "the producible-term closure did not settle in %d pass(es); the "
                "operator set may be missing consumers of terms produced late, so "
                "UNREACHABLE from it is not a proof", DEFAULT_CLOSURE_PASSES)

    report_body.constants = report.constants
    report = report_body

    # SAY WHAT THE PLANNER WAS ACTUALLY GIVEN.
    #
    # Grounding returning zero operators is indistinguishable, downstream, from
    # a world in which nothing is possible -- and the planner's verdict
    # inherits that ambiguity silently. Stated here so any UNREACHABLE can be
    # read against the operator set it came from.
    if report.rules_unreachable:
        logger.warning(
            "Grounding: %d rule(s) can never fire — the operator set cannot "
            "predict part of this world, so UNREACHABLE from it is not a proof. "
            "%s",
            len(report.rules_unreachable),
            "; ".join(f"{rid}: {why}" for rid, why in report.rules_unreachable.items()))

    if not rules:
        # NOTHING LEARNED HERE YET is a state, not a fault: the goal was asked of
        # a domain with no executable rule, and the planner is offered nothing.
        # It was a warning with "no reason recorded" every time Lyric pursued a
        # goal before it had learned to act there (931 times over 100 worlds of
        # RULE-AUTHORITY-02's live arm, every one with no rule).
        logger.info(
            "Grounding: no executable rule to ground — nothing learned to act "
            "with here, so UNREACHABLE means 'nothing was offered', not "
            "'nothing is possible'")
    elif not report.operators:
        logger.warning(
            "Grounding produced NO operators from %d rule(s) — the planner "
            "cannot reach any goal from an empty operator set, so UNREACHABLE "
            "means 'nothing was offered', not 'nothing is possible'. Why: %s",
            len(rules),
            "; ".join(f"{rid}: {why}" for rid, why in {
                **report.rules_skipped, **report.rules_unmatched}.items()))
    else:
        logger.info(
            "Grounding: %d rule(s) in, %d used, %d skipped, %d operator(s), "
            "complete=%s%s",
            len(rules), len(report.rules_used), len(report.rules_skipped),
            len(report.operators), report.complete,
            "" if not report.rules_skipped else " | skipped: " + "; ".join(
                f"{rid}: {why}" for rid, why in report.rules_skipped.items()))

    return report
