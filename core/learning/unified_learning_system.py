#!/usr/bin/env python3
"""
Lyric Unified Learning System
Integrated learning system combining all learning components
"""

from statistics import NormalDist
import hashlib
import itertools
import logging
import asyncio
import json
from contextvars import ContextVar
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Callable, Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple
from core.database.logging_database import LoggingDatabase

logger = logging.getLogger(__name__)


from ..memory import MemoryManager, CognitiveExperience, MemoryType, MemoryPriority
from .meta_learning import MetaLearner, get_meta_learner
from .learning_interfaces import (
    ILearningSystem,
    LearningType,
    LearningExample,
    LearningResult,
)
from .meta_learning import TaskFamily, task_family_for_task_type
# THE ONE LEARNING AUTHORITY. UnifiedLearningSystem was once the DECLARED
# authority; a correct model-free ILearningAuthority was then built in a
# separate learning_authority.py instead of fixing THIS class, leaving two
# owners of the one concept "learning". That file is now deleted and its whole
# implementation lives here: UnifiedLearningSystem IS the learning authority
# (propose -> evidence attests, model-free, one boundary on what may propose,
# induction + rule store), with the meta-learning strategies as first-class
# parts of it. These are the imports that implementation needs.
from core.structural_defects import raise_if_structural
from core.learning.learning_interfaces import ILearningAuthority
from core.utils.give_way import GiveWay
from core.learning.rule_induction import (CandidateRule, InductionResult,
                                          InductionStatus, TrainingExample,
                                          get_rule_inducer)
from core.learning.rule_store import EpistemicStatus, get_rule_store

# LearningType (how we are learning) -> TaskFamily (what kind of task it is).
# meta_learning registers and selects strategies by TaskFamily; this system
# speaks LearningType. Passing a LearningType through matched nothing, so
# select_strategy() returned None and its caller dereferenced it.
# HOW SOMETHING WAS LEARNED -> WHAT KIND OF PROBLEM IT IS.
#
# This covered 6 of LearningType's 10 members and was read with a
# `.get(learning_type, TaskFamily.CLASSIFICATION)` default, so the four
# substrate types -- the ones naming how the substrate ACTUALLY learns -- were
# silently filed as classification. Combined with the same default catching
# every unstated family, 10,601 of 11,720 recorded decisions were scored
# against the classification arms without anything deciding they were
# classification problems. `classification_transfer` reached 519 trials at
# confidence 1.000 on work that was largely not classification.
#
# CONTRIBUTION is deliberately absent. Admitting a proposal against evidence is
# not a learning problem with strategy alternatives to choose between, so there
# is no honest family for it, and inventing one would put a strategy's credit
# on an event no strategy influenced. Unmapped is stated below, not defaulted.
_LEARNING_TYPE_TO_TASK_FAMILY = {
    LearningType.SUPERVISED: TaskFamily.CLASSIFICATION,
    LearningType.UNSUPERVISED: TaskFamily.PERCEPTION,
    LearningType.REINFORCEMENT: TaskFamily.REINFORCEMENT,
    LearningType.TRANSFER: TaskFamily.CLASSIFICATION,
    LearningType.CONTINUAL: TaskFamily.SEQUENCE,
    LearningType.META: TaskFamily.REASONING,
    # A rule generalised from demonstrations is a reasoning problem.
    LearningType.INDUCTION: TaskFamily.REASONING,
    # A procedure derived from I/O pairs produces a program.
    LearningType.SYNTHESIS: TaskFamily.GENERATION,
    LearningType.CAUSAL: TaskFamily.REASONING,
}

# Import domain knowledge system for transfer learning
from core.domain import (
    CrossDomainReasoner, DomainRegistry, UniversalOntology, UnknownDomain,
    UnresolvedDomainReference)
from core.structural_defects import raise_if_structural
from core.learning.rule_induction import Fact, as_constant
from typing import FrozenSet

#: How deep learning has recurred WITHIN THE CURRENT TASK.
#:
#: This replaces `self._learning_in_progress` + `self._current_nesting_depth`,
#: two instance attributes shared by every caller of the singleton. They could
#: not tell recursion from concurrency, and `learn_from_example` awaits
#: repeatedly, so any two parallel tasks interleaved through them. Measured
#: with five concurrent (NOT nested) calls: one was rejected outright with
#: "Circular dependency detected", and the guard was left at
#: `in_progress=True, depth=0` afterwards -- stuck, so every later call counted
#: as nested and the system would refuse all learning after three more.
#:
#: A ContextVar is per-task and inherited by awaited callees, which is exactly
#: the distinction the guard needs: a nested call sees its caller's depth, a
#: sibling task starts at zero. Nothing to reset, so it cannot be left corrupt.
_learning_depth: "ContextVar[int]" = ContextVar("learning_depth", default=0)


def _json_safe(value: Any) -> Any:
    """Coerce a value into something the memory store can serialise.

    source_context carries the producer's example verbatim under
    'example_data', so it holds whatever a caller put there -- an enum, a
    dataclass, a datetime. The hot tier serialises that column as JSON and a
    single non-serialisable object fails the WHOLE insert: the memory is lost
    and the lane reports nothing but "Memory agent rejected: None", which is
    indistinguishable from the worthiness filter declining it.

    Observed by putting a LearningType on the example so the strategy could be
    selected by task family -- a correct change that silently stopped every
    learning memory from persisting. Whether an outcome is recorded must not
    depend on which Python types a producer happened to use.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return str(value)


# ── INDUCTION BASIS BOUNDS (moved from the deleted learning_authority.py) ──────
# The induction basis is BOUNDED so the hypothesis search stays tractable as
# demonstrations accumulate (measured: ~0.03s at 12 examples, ~0.9s at 16, ~17s
# at 20, non-terminating past that), while the information LGG needs saturates
# early. Held-out validation (reserved separately) remains the correctness guard.
#: A habit of a person's world is relied on -- what Lyric does when the world does
#: not keep it is then theirs to have answered -- when it is more likely than not
#: that it holds at least this often: its rate's lower bound, half a standard
#: error below it (one-sided 69%), is at least this (`regularity_relied_on`).
#: Chosen over 84% and 95%, which answered 83% and 59% of a
#: 90% habit's misses where this answers 93%, a 75% one's 9%, a 50% one's none.
RELIED_ON_RATE = 0.8
#: The two-sided level whose lower bound is the one-sided 69% above (z = 0.5).
RELIED_ON_CONFIDENCE = 2 * NormalDist().cdf(0.5) - 1
#: And never on fewer outcomes than this: so lenient a bound relied on a habit at
#: its first confirmation, and a step kept every other time was answered twice
#: before its rate showed it (EXPECT-01, section E).
RELIED_ON_MIN_OUTCOMES = 5


def relied_on_rate(held: int, expected: int) -> bool:
    """Whether a habit that held `held` times of `expected` is more likely than
    not to hold at least `RELIED_ON_RATE` of the time, on at least
    `RELIED_ON_MIN_OUTCOMES` outcomes. Five of five is; one of one is not yet;
    nine of ten is; eight of ten is not; seventy-five of a hundred never will be."""
    from core.learning.meta_learning import wilson_interval
    if expected < RELIED_ON_MIN_OUTCOMES:
        return False
    lower, _upper = wilson_interval(held, expected, confidence_level=RELIED_ON_CONFIDENCE)
    return lower >= RELIED_ON_RATE


def _relied_on(examples, departed) -> Optional[str]:
    """Why an act's rules may not be acted on yet, or None when they may.

    The world departing from an act (`_departures`) refutes none of its rules,
    and an act is relied on as a habit is (`relied_on_rate`): from how often it
    did what it does, its successes against the misses nothing observed tells
    apart from them. An act the world never departed from is judged by
    validation alone, as before; one it departed from waits until it holds
    often enough, which is also what keeps a world whose rule no conjunction
    can say (it works on either of two groups) from being acted on as though
    its misses were noise.

    COUNTED FOR THE ACT, NOT FOR ONE RULE. Counted over the acts a rule applied
    to, a narrower rule validated before the misses came did not fall under
    them and kept its authority while the act failed two times in seven
    (RULE-AUTHORITY-02 world 3993: it acted where the world refuses).

    A leak (`_leaks`) is neither a time it held nor a miss: the world did more
    there than the act does, not less."""
    missed = sum(1 for e in examples if not e.positive and e.evidence_id in departed)
    if not missed:
        return None
    held = sum(1 for e in examples if e.positive and e.evidence_id not in departed)
    if relied_on_rate(held, held + missed):
        return None
    return (f"the world departed from this act in {missed} of {held + missed} attempts; "
            f"relied on once it holds at least {RELIED_ON_RATE:.0%} of the time")


def _leaks(examples, departed, frame) -> Set[str]:
    """The successes nothing they held can explain: the world doing what an act
    does where it does not do it, not the act's rule being wrong.

    A success is put to the refusals as a miss is put to the successes
    (`_departures`): can a body hold of it and of none of them? A body is made
    of what the success held, so a refusal that held all of that holds every
    such body, unless it held something no success held (that could be the
    condition that must be absent, as in a world that refuses where one
    condition holds). Two such refusals are the world refusing there; one can be
    the world departing the other way. Only a success that lacked something
    every other success held is asked: one that did not is explained by what
    explains them.

    Without it a leak stood among the successes for good. A body has to hold of
    every success, and whatever held of the leak held of refusals too, so no
    rule was ever learned for the act (RULE-AUTHORITY-02's noisy arm: two of the
    thirteen settled conjunction worlds where Lyric held no rule)."""
    positives = [e for e in examples if e.positive and e.action is not None]
    refusals = [e for e in examples if not e.positive and e.action is not None
                and e.evidence_id not in departed]
    if len(positives) < 3 or len(refusals) < 2:
        return set()
    framed = frame(positives + refusals)
    seen, refused = framed[:len(positives)], framed[len(positives):]
    named = lambda e: frozenset(c for c in _conditions(e) if "_" not in c)
    held_by_a_success = frozenset().union(*(_conditions(e) for e in seen))
    plain = [named(e) for e in refused if not _conditions(e) - held_by_a_success]
    leaked: Set[str] = set()
    for index, success in enumerate(seen):
        others = seen[:index] + seen[index + 1:]
        if not frozenset.intersection(*(named(e) for e in others)) - named(success):
            continue
        if sum(1 for held in plain if named(success) <= held) >= 2:
            leaked.add(positives[index].evidence_id)
    return leaked


_BASIS_POSITIVES = 8
_BASIS_NEGATIVES = 8
_BASIS_CONTRASTIVE = 6


def _description(example: "TrainingExample") -> Tuple[str, ...]:
    """What a change the world made on its own says about the thing it changed,
    the thing's own name aside: a pdf from alice and another from alice are
    alike, one from erin is not.

    THE BASIS IS SPREAD OVER THESE, as an operator's is over its acts. A change
    the world made has no act, so every one fell in one bucket and the cap kept
    the earliest: the first eight, all alice's while only alice's had come. Every
    later miss of another sender's was then told apart by its sender -- "the
    substrate was wrong" -- however many of theirs had moved since (EXPECT-02:
    a habit of six senders lost to the first fifteen files).

    THE THING IS THE ONE THE CHANGE IS ABOUT, decided as the frame decided it
    (`_changed_things`). Counted over everything held before instead, the
    relation between the two rooms (PATH(INBOX, DONE)), kept once the frame
    kept relations among the things a change names, tied INBOX with the file,
    INBOX sorted first, and every file's change became its own bucket: the cap
    kept the first eight again, all alice's. Counting stays for a case with no
    change to read, an expectation that went unmet."""
    from collections import Counter
    before, after = frozenset(example.before), frozenset(example.after)
    changed = (after - before) | (before - after)
    about = {t for _facts, things in _changed_things(changed, before | after) for t in things} if changed else set()
    if not about:
        counts = Counter(t for f in example.before for t in f.args)
        if not counts:
            return ()
        about = {max(sorted(counts), key=lambda t: counts[t])}
    return tuple(sorted(f"{f.predicate}({','.join('_' if a in about else a for a in f.args)})"
                        for f in example.before))


def _bounded_basis(
    signature_basis: List["TrainingExample"],
    contrastive: "Sequence[TrainingExample]",
) -> List["TrainingExample"]:
    """A bounded, constant-diverse subset of the evidence for one induction.

    Exact-duplicate demonstrations are dropped; among the rest, selection
    round-robins over distinct ground ACTIONS so a capped sample spans different
    constants (what LGG needs to variabilise an argument position). Positives,
    negatives and contrastives are bounded independently.
    """
    def _fingerprint(example: "TrainingExample"):
        return (example.positive, example.action,
                tuple(sorted((f.predicate, f.args) for f in example.before)),
                tuple(sorted((f.predicate, f.args) for f in example.after)))

    def _spread(examples: List["TrainingExample"], cap: int) -> List["TrainingExample"]:
        seen: set = set()
        unique: List["TrainingExample"] = []
        for example in examples:
            key = _fingerprint(example)
            if key in seen:
                continue
            seen.add(key)
            unique.append(example)
        if len(unique) <= cap:
            return unique
        buckets: Dict[Any, List["TrainingExample"]] = {}
        order: List[Any] = []
        for example in unique:
            key = example.action if example.action is not None else _description(example)
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(example)
        selected: List["TrainingExample"] = []
        depth = 0
        while len(selected) < cap and any(len(buckets[a]) > depth for a in order):
            for action in order:
                if depth < len(buckets[action]):
                    selected.append(buckets[action][depth])
                    if len(selected) >= cap:
                        break
            depth += 1
        return selected

    positives = _spread([e for e in signature_basis if e.positive], _BASIS_POSITIVES)
    negatives = _spread([e for e in signature_basis if not e.positive], _BASIS_NEGATIVES)
    contrastives = _spread(list(contrastive), _BASIS_CONTRASTIVE)
    return positives + negatives + contrastives


def _relevant_frame(basis: List["TrainingExample"]) -> List["TrainingExample"]:
    """Scope each demonstration to what the action MENTIONS.

    A full-world observation makes Plotkin LGG explode (w facts of a predicate
    over n positives -> w**n body literals), so the learning state is cut down
    to what could bear on this action. Held-out validation is left on the FULL
    world, so a scoped rule must still fire in reality.

    WHAT AN OPERATOR CHANGES IS NOT WHAT IT DEPENDS ON, and this scoped to the
    first while the rule needs the second. The anchor was the object transformed
    -- the term shared by the ADD and DELETE effects -- so for
    MOVE_FILE(file, src, dst) it was `file`, and every literal that did not
    mention the file was dropped before induction ever saw it. `DIR(dst)` is
    exactly such a literal, and it is exactly the precondition that decides
    whether the move works: moving into a directory that is not there fails.
    So the destination's existence was structurally unlearnable -- not missing
    from the vocabulary, but discarded by the frame -- and the learner was left
    inducing a rule whose only body literal was the action itself.

    An argument the action NAMES can bear on it; a literal sharing no argument
    with the action cannot. That is the relevance restriction, and it is still
    bounded: the arity is small and fixed, so the frame stays a handful of
    literals rather than the world. Measured on the filesystem domain: the
    unscoped LGG retained 4098 literals and reported `insufficient_evidence`;
    anchored on every argument it retains 3.
    """
    tallies: Dict[int, int] = {}
    acted_positives = 0
    #: The relations the act was seen to change, over every positive.
    changed: set = set()
    for example in basis:
        if example.action is None or not example.positive:
            continue
        acted_positives += 1
        added = set(example.after) - set(example.before)
        deleted = set(example.before) - set(example.after)
        changed |= {fact.predicate for fact in added | deleted}
        persistent = ({t for fact in added for t in fact.args}
                      & {t for fact in deleted for t in fact.args})
        for index, arg in enumerate(example.action.args):
            if arg in persistent:
                tallies[index] = tallies.get(index, 0) + 1
    if not tallies:
        # NOTHING THE ACT MOVES KEEPS ITS NAME. Where a thing's name is where it
        # is -- a path -- moving it makes a different term, so no argument is
        # shared by what was added and what was taken away, and there is no
        # transformed object to anchor on. The frame is then what the action
        # NAMES: every fact about one of its arguments. Leaving the
        # demonstration unscoped instead hands the generalizer the whole observed
        # world, which is what every plan step and every practised act records.
        from dataclasses import replace

        def about_what_it_names(example: "TrainingExample") -> "TrainingExample":
            if example.action is None or not example.action.args:
                return example          # it names nothing, so nothing to scope to
            named = set(example.action.args)
            return replace(
                example,
                before=tuple(f for f in example.before if set(f.args) & named),
                after=tuple(f for f in example.after if set(f.args) & named))

        return [about_what_it_names(example) for example in basis]
    object_positions = {i for i, count in tallies.items()
                        if count * 2 >= acted_positives}
    if not object_positions:
        object_positions = {max(tallies, key=lambda i: tallies[i])}

    def scoped(example: "TrainingExample") -> "TrainingExample":
        if example.action is None:
            return example
        anchors = {example.action.args[i] for i in object_positions
                   if i < len(example.action.args)}
        if not anchors:
            return example
        # THE OBJECT'S OWN FACTS, plus what is true of the action's OTHER
        # arguments — bounded to UNARY facts, which is what keeps this from
        # being the full-world frame that makes LGG explode.
        #
        # Anchoring on the transformed object alone discards every precondition
        # about anything else the action names, and some of those decide whether
        # it works at all: a move into a directory that is not there fails, and
        # `DIR(dst)` mentions the destination, never the file. Widening the
        # anchor to EVERY argument was measured and is not viable — it kept
        # binary facts about the source and destination too, and
        # `test_substrate_execution` went from 33s to not finishing.
        #
        # A unary fact says something about ONE named thing, so at most one
        # survives per argument: the frame grows by the action's arity, which is
        # small and fixed, rather than by the world.
        #
        # So does a fact ABOUT a named thing -- it is the fact's first argument --
        # in a relation the act changes. A copy transforms only its destination,
        # which is the one anchor, yet what the destination becomes is the
        # source's KIND and SIZE; dropped, the effect has nothing to take its
        # values from and no rule can be formed. A relation the act never
        # changes stays out, and so does a fact that only mentions a named
        # thing, which is what a room's many paths or a directory's many files
        # are.
        #
        # A RELATION AMONG THE THINGS THE ACT NAMES IS IN, whatever its order.
        # Cut, it was unlearnable whenever the act transforms one argument and
        # the condition holds between two others: RULE-AUTHORITY-02 world 264
        # (the act consumes RINMIR(x), its rule needs VORDRAGOR(y, z)) left the
        # near miss lacking VORDRAGOR looking like a success, and no rule was
        # learned in 20 such worlds; world 3847 lost POLSOL(z, x), the rival
        # that would have left the evidence undecided, and gave authority to a
        # rule acting in 12 situations the world refuses. Such a fact names
        # nothing outside the act, so there are at most a predicate's worth per
        # tuple of its arguments, never the world's many.
        named = set(example.action.args)
        before = tuple(f for f in example.before if _bears_on(f, anchors, named, changed))
        after = tuple(f for f in example.after if _bears_on(f, anchors, named, changed))
        if not before and not after:
            return example
        from dataclasses import replace
        return replace(example, before=before, after=after)

    return [scoped(example) for example in basis]


def _conditions(example: "TrainingExample") -> FrozenSet[str]:
    """What held before an act, of the things it names by their place in it:
    `TOMATAV(1)` for TOMATAV(y) when y is the act's second argument, and
    `FEDRA(1,_)` for FEDRA(y, something it does not name). The terms the causal
    structure is learned over (`induce_causal_structure`), so a condition is the
    same condition in every demonstration of the act.

    A THING THE ACT NAMES TWICE IS AT BOTH PLACES. JOBA(o6a, o6a, o6c) names o6a
    as x and as y, so GORGADO(o6a, o6c) is GORGADO(x, z) and GORGADO(y, z). Read
    at one place only, a success held a condition it seemed to lack: in
    RULE-AUTHORITY-02 a goal pursued on one thing in two places made a needed
    condition look unneeded, and a condition that must be absent look like
    one of the other thing's."""
    return _by_place(example.before, example.action)


from core.learning.rule_induction import _by_place  # noqa: E402  (its one owner)


def _rule_conditions(rule: "CandidateRule") -> FrozenSet[str]:
    """A rule's body as `_conditions` reads a demonstration."""
    return _by_place(rule.body, rule.action)


async def untested_conditions(domain_id: str, action: "Fact", state) -> FrozenSet[str]:
    """What makes the case an act is about to meet one none of its recorded
    successes covered, said in words: a condition of the things it names that
    holds now and held in no success, or two conditions of which every success
    held one and neither holds now.

    A RULE IS AS GOOD AS WHAT IT HAS SEEN. Where something the act's successes
    never held holds now, the rule cannot say whether that matters: "the door
    opens with the key" was never tried on a bolted door. And where every
    success had one of two things, the act has never been seen to work with
    neither: a world that works on either of two groups of conditions gave
    each group's successes one of them, and the rule they shared acted where
    both are missing. The constitution reads this at the gate (Law 2) and sends
    such an act back to planning, and the planner plans no route through it.
    Nothing yet directs an experiment at such a case."""
    from core.learning.demonstration_store import get_demonstration_store
    from core.learning.rule_induction import TrainingExample
    examples = await get_demonstration_store().load(
        domain_id=domain_id, predicate=action.predicate, arity=len(action.args))
    successes = [e for e in examples if e.positive and e.action is not None]
    if not successes:
        return frozenset()
    state = tuple(state)
    now = TrainingExample(before=state, action=action, after=state, positive=False,
                          evidence_id="now")
    framed = _relevant_frame(successes + [now])
    named = lambda e: frozenset(c for c in _conditions(e) if "_" not in c)
    return frozenset(_uncovered(named(framed[-1]), [named(e) for e in framed[:-1]]))


def _uncovered(present: FrozenSet[str], successes: List[FrozenSet[str]]) -> List[str]:
    """Why `present` is a case `successes` did not cover (`untested_conditions`)."""
    if not successes:
        return []
    held = frozenset().union(*successes)
    always = frozenset.intersection(*successes)
    why = [f"{c}, which held in no success" for c in sorted(present - held)]
    sometimes = sorted(held - always)
    for first, second in itertools.combinations(sometimes, 2):
        if all(first in s or second in s for s in successes) and first not in present \
                and second not in present:
            why.append(f"neither {first} nor {second}, one of which every success held")
    return why


def success_conditions(rule: "CandidateRule", examples) -> List[List["Fact"]]:
    """Each success of the rule's act, as the conditions of the things the act
    names that held in it, written over the rule's own variables: the cases
    its evidence covers, as `untested_conditions` reads them at the act."""
    from core.learning.rule_induction import Fact
    if rule.action is None:
        return []
    out = []
    for e in _relevant_frame(list(examples)):
        if not (e.positive and e.action is not None and e.action.predicate == rule.action.predicate):
            continue
        literals = []
        for condition in sorted(c for c in _conditions(e) if "_" not in c):
            name, inner = condition.split("(", 1)
            places = [p for p in inner[:-1].split(",") if p != ""]
            literals.append(Fact(name, tuple(rule.action.args[int(p)] for p in places)))
        out.append(literals)
    return out


def _unshown(rule: "CandidateRule", examples) -> Optional[str]:
    """What a rule leaves out that every success of its act held: a condition
    the act has never been seen to work without.

    NEVER SEEN TO MATTER IS NOT SEEN NOT TO MATTER. Induction keeps the fewest
    conditions that exclude every miss, so a condition no miss happened to lack
    was left out of the rule, and the rule acted where it is missing, which no
    demonstration had shown: in RULE-AUTHORITY-02's 2,000 worlds, 117 of the 250
    worlds whose evidence pointed to a broader rule held one acting somewhere the
    world refuses. A condition leaves the rule's authority only once a success
    without it has been seen; until then the rule waits for that success."""
    if rule.action is None:
        return None
    seen = [_conditions(e) for e in _relevant_frame(list(examples))
            if e.positive and e.action is not None and e.action.predicate == rule.action.predicate]
    if not seen:
        return None
    left_out = frozenset.intersection(*seen) - _rule_conditions(rule)
    if not left_out:
        return None
    return (f"it leaves out {', '.join(sorted(left_out))}, which held in every success: "
            f"the act has not been seen to work without it")


def _bears_on(fact: "Fact", anchors, named, changed) -> bool:
    """Whether a fact can bear on a change: it is about a thing the change
    transformed (an anchor), or it says something about one thing the change
    names -- of that thing alone, or in a relation the change moved -- or it
    relates only things the change names. The relevance restriction every
    frame here is cut by (`_relevant_frame`, `world_change_examples`)."""
    return bool(set(fact.args) & set(anchors)) or (
        bool(fact.args) and fact.args[0] in named
        and (len(fact.args) == 1 or fact.predicate in changed
             or set(fact.args) <= set(named)))


def _changed_things(changed, world) -> List[Tuple[frozenset, frozenset]]:
    """The changed facts, grouped by the thing each is about.

    A fact names places and things; what changed in it is the thing the change
    is most about -- named in the most of the facts that changed: a file that
    moved is in both the fact taken away and the fact added, each room in one;
    a file that arrived is in every fact that appeared. Where the change names
    several equally, as two files moved between the same rooms at once name
    the rooms as often as the files, it is the one least connected in the world
    it was seen in: each room is in many facts. Facts sharing such a thing are
    one change; those two files are two.

    The world alone decided it before, and a sparse world decided it wrong: an
    inbox holding one file is in fewer facts than the file, and a sender of one
    file in fewer still, so a file's arrival was filed as a change of the inbox,
    of its sender and of its kind, and never of the file. Returns (the facts,
    the things they are about) per change."""
    from collections import Counter
    counts = Counter(t for f in world for t in f.args)
    shared = Counter(t for f in changed for t in set(f.args))
    groups: List[Tuple[set, set]] = []
    for fact in sorted(changed, key=str):
        if not fact.args:
            continue
        best = min((-shared[t], counts[t]) for t in fact.args)
        about = {t for t in fact.args if (-shared[t], counts[t]) == best}
        joined = [g for g in groups if g[1] & about]
        facts, things = {fact}, set(about)
        for g in joined:
            facts |= g[0]
            things |= g[1]
            groups.remove(g)
        groups.append((facts, things))
    return [(frozenset(f), frozenset(t)) for f, t in groups]


def world_change_examples(before, after, *, evidence_stem: str
                          ) -> List[Tuple["TrainingExample", frozenset]]:
    """What a change the world made on its own teaches: one actionless positive
    demonstration per thing that changed (`_changed_things`), its before and
    after cut to what bears on that thing (`_bears_on`), with the things it is
    about (what its signature leaves open, `regularity_signature`). Nothing is
    filed for a world that did not change.

    Cut per thing and not to the whole world, because a regularity takes time:
    the other files waiting in the same room were not expected to have moved
    yet, and leaving them in would make every move a counter-example to itself.
    `evidence_stem` identifies the two readings; each example's id adds what
    changed, so the same change read twice is one observation."""
    before, after = frozenset(before), frozenset(after)
    changed = (after - before) | (before - after)
    examples: List[Tuple[TrainingExample, frozenset]] = []
    for facts, things in _changed_things(changed, before | after):
        named = {t for f in facts for t in f.args}
        relations = {f.predicate for f in facts}
        frame_before = tuple(sorted(f for f in before if _bears_on(f, things, named, relations)))
        frame_after = tuple(sorted(f for f in after if _bears_on(f, things, named, relations)))
        digest = hashlib.sha1(
            (evidence_stem + "|" + "|".join(sorted(str(f) for f in facts))).encode()).hexdigest()
        examples.append((TrainingExample(before=frame_before, action=None, after=frame_after,
                                         positive=True, evidence_id=f"world_{digest[:16]}"),
                         things))
    return examples


def expected_things(effects, world) -> frozenset:
    """The things an expected change is about -- the file that should move, not
    the rooms it moves between -- by the same cut its changes are learned by."""
    predicted = effects.add | effects.delete
    return frozenset(t for _facts, about in _changed_things(predicted, frozenset(world))
                     for t in about)


def expectation_case(held, now, effects, *, evidence_id: str) -> "TrainingExample":
    """An unmet expectation as a counter-example: what held about its terms when
    it was formed, and what holds of them now, with the effects it predicted
    absent. Cut by the same restriction as the changes it is compared with."""
    predicted = effects.add | effects.delete
    things = expected_things(effects, frozenset(held) | frozenset(now))
    named = {t for f in predicted for t in f.args}
    relations = {f.predicate for f in predicted}
    return TrainingExample(
        before=tuple(sorted(f for f in held if _bears_on(f, things, named, relations))),
        action=None,
        after=tuple(sorted(f for f in now if _bears_on(f, things, named, relations))),
        positive=False, evidence_id=evidence_id)


#: What shared learning is divided into, each with its own switch (`UnifiedLearningSystem.shared_learning`). How a
#: piece of work was carried out -- its steps, what succeeded or failed, how each failure was overcome -- goes by where
#: the work came from: a task asked for on its own, a project's work, a workflow's runs (`work_category`). What Lyric's
#: single actions taught it -- how the tools it ran performed, what its research found -- is `actions`, wherever they
#: were done.
SHARED_LEARNING_CATEGORIES = ("tasks", "actions", "projects", "workflows")


def work_category(metadata: Optional[Dict[str, Any]]) -> str:
    """Which kind of work a task is, as the request that started it says: a workflow's run (`workflow`), a project's
    work (`project`), or a task asked for on its own."""
    meta = metadata or {}
    if meta.get("workflow"):
        return "workflows"
    if meta.get("project"):
        return "projects"
    return "tasks"


class ContributionKind(Enum):
    """What a contributor is offering. None of these are evidence."""
    HYPOTHESIS = "hypothesis"          # a candidate rule to consider
    SITUATION = "situation"            # an experiment worth running
    FORMALIZATION = "formalization"    # a structure read out of unstructured input
    LESSON = "lesson"                  # teaching material


from dataclasses import dataclass as _dataclass, field as _field


@_dataclass(frozen=True)
class Evidence:
    """What vouches for a claim about the world (docs/research/SEPARATION_MAP.md §11.4).

    `source` is who or what said it ("person:ana", a page's address, "sense:sight", a run); `key` is what makes it
    independent of other evidence -- the person, the site, the sensor, the lesson -- and the same key counts once
    however often it says the claim; `source_type` is its kind, an `EvidenceSourceType` name; `quality` is how good
    it is. Being a person neither proves nor disqualifies a claim."""
    source: str
    key: str
    source_type: str
    quality: float
    producer: str = "learning"
    #: What a derived claim was derived from: the observations a rule named an instance from. A derivative with no
    #: lineage is refused by the ingress (`concept_ingestion._ROOT_SOURCES`).
    derived_from: Tuple[str, ...] = ()

    @classmethod
    def from_provenance(cls, provenance: Any, quality: float) -> "Evidence":
        """Evidence from where a claim came from (`cognitive_ingress.Provenance`): its source as the source and the
        key -- one lesson, one sense of one place, one experiment run counts once -- its kind, and how good it is."""
        return cls(source=f"{provenance.producer}:{provenance.source_id}", key=str(provenance.source_id),
                   source_type=str(provenance.source_type), quality=float(quality),
                   producer=str(provenance.producer), derived_from=tuple(provenance.derived_from or ()))


@_dataclass(frozen=True)
class Naming:
    """What a learned classifier named an instance, and the evidence for it (`name_instance`): a claim for memory to
    take in, not yet held anywhere."""
    instance: str
    category: str
    evidence: Evidence

    @property
    def claim(self) -> str:
        return f"{self.instance} isa {self.category}"


@_dataclass
class Decision:
    """What the gate decided of one claim (`UnifiedLearningSystem.consider`).

    `standing` is one of:
      settled    held, and the belief in it is settled (the belief system's own bar);
      candidate  held, and used, with its belief not yet settled;
      theirs     about a person's own things, held in their context and not the world's (`MemoryAgent.hold_for_person`);
      doubted    not held: what is held says otherwise, and this was counted against it;
      refused    not held, and why is in `reasons`."""
    claim: str
    positive: bool
    standing: str
    reasons: List[str] = _field(default_factory=list)
    admission: Any = None
    posterior: Optional[float] = None

    @property
    def admitted(self) -> bool:
        return self.standing in ("settled", "candidate", "theirs")


@_dataclass(frozen=True)
class Contribution:
    """An offer from a proposer. Carries no confidence, deliberately: a
    proposer's certainty about its own output is not a measurement of the world,
    and admitting one would let a fluent contributor grade its own work."""
    contributor: str
    kind: ContributionKind
    payload: Any
    rationale: str = ""
    domain_id: Optional[str] = None


@_dataclass
class Admission:
    """What the authority did with a contribution, and why."""
    accepted: bool
    reason: str
    contributor: str
    kind: ContributionKind
    #: Always CANDIDATE when accepted. A contribution cannot arrive validated.
    status: Optional["EpistemicStatus"] = None
    rule_id: Optional[str] = None

    @property
    def is_knowledge(self) -> bool:
        """Never true on admission. Present so callers cannot forget to ask."""
        return self.status is EpistemicStatus.VALIDATED


class FeatureEncoder:
    """Symbolic features → the boolean vector a clause machine reads.

    An OBJECT rather than a closure, deliberately: the encoder has to survive the
    process, and a lambda over a captured vocabulary does not. A classifier that
    comes back from disk without its encoder is not a degraded classifier, it is a
    broken one — it gets handed whatever its route passes (a file path, for a
    vision route) and asked to treat that as features.

    The vocabulary is FIXED at training time and the order is the contract: bit k
    is `vocabulary[k]`. A feature the classifier never trained on is dropped
    rather than appended, because appending would shift every later bit and quietly
    re-map every clause the machine learned.
    """

    __slots__ = ("vocabulary", "_index")

    def __init__(self, vocabulary: Sequence[str]) -> None:
        self.vocabulary: Tuple[str, ...] = tuple(str(v) for v in vocabulary)
        self._index = {v: i for i, v in enumerate(self.vocabulary)}

    def __len__(self) -> int:
        return len(self.vocabulary)

    def __call__(self, features) -> "Any":
        import numpy as np
        bits = np.zeros(len(self.vocabulary), dtype=np.int8)
        for f in (features or ()):
            k = self._index.get(str(f))
            if k is not None:
                bits[k] = 1
        return bits

    def unknown(self, features) -> Tuple[str, ...]:
        """Features this encoder has no bit for — what the machine cannot see
        about this instance. Surfaced so a caller can tell a confident vote over
        a well-covered instance from one over an instance it is half blind to."""
        return tuple(sorted({str(f) for f in (features or ())
                             if str(f) not in self._index}))


def _operator_residue(rule: Any, basis: Sequence[Any], owners: Dict[str, Optional[str]]) -> List[str]:
    """The constants of an induced operator whose only source is people's work, by the one rule
    (`person_residue`): each demonstration it was induced from is a case, a person's when `owners` names one,
    and what that case supplied is every term in it. One demonstration of the substrate's own work makes every
    constant the world's."""
    effects = getattr(rule, "effects", None)
    facts = [*getattr(rule, "body", ()), *getattr(effects, "add", ()), *getattr(effects, "delete", ())]
    held = {arg for fact in facts for arg in fact.args if arg not in fact.variables}
    instances = [{arg for fact in (*e.before, *((e.action,) if e.action is not None else ()), *e.after)
                  for arg in fact.args}
                 if owners.get(getattr(e, "evidence_id", None) or "") else None
                 for e in basis]
    return person_residue(held, instances)


class UnifiedLearningSystem(ILearningAuthority, ILearningSystem):
    """Unified learning system that coordinates all learning components"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None, domain_master=None):
        # The authority core: what owns the rule store, the inducer, and the
        # propose/attest boundary. This class IS the learning authority (its
        # induction/contribute methods are below), so these back its own state.
        self._store: Any = None
        self._inducer: Any = None
        self._contributors: Dict[str, str] = {}
        self._admissions: List["Admission"] = []
        #: Parametric perceptual learners (Convolutional Tsetlin Machines) OWNED
        #: by the authority: {name: {"model": CTM, "labels": [class->category],
        #: "encode": callable|None}}. The model is a MECHANISM; its recognitions
        #: are knowledge only once they pass the gate via `recognize` -> `consider`.
        self._clause_classifiers: Dict[str, Dict[str, Any]] = {}
        self.config = config or {}
        self.domain_master = domain_master
        self.initialized = False

        # Initialize components
        self.memory_system = None  # Will be injected by main.py
        meta_db_path = config.get('meta_learning_db_path', 'meta_learning.db') if config else 'meta_learning.db'
        # Use global MetaLearner singleton so meta-learning is shared
        self.meta_learning = get_meta_learner(config=self.config.get("meta_learning_config"))

        # Domain knowledge integration for transfer learning (use singletons)
        self.domain_registry = None
        self.universal_ontology = None
        self.cross_domain_reasoner = None  # Will be initialized in initialize() method - needs domain_registry and universal_ontology

        self.domain_learning_stats = {
            "cross_domain_transfers": 0,
            "domain_specific_learning": 0,
            "transfer_learning_successes": 0
        }

        # Logging Database - For comprehensive learning activity logging (compliance & accountability)
        self.log_db = LoggingDatabase()
        # Note: Will be initialized in async start() method

        # System state. The queue is bounded: it used to grow for the life of
        # the process because nothing ever removed from it.
        self.active_learning_tasks = []
        self._max_queued_events = 200
        #: Strong references to in-flight event tasks. Without these, asyncio
        #: only holds a weak reference and a task can be garbage-collected
        #: mid-flight, losing the learning silently.
        self._event_tasks: set = set()
        # PER-PROCESS COUNTERS ONLY. These reset on restart, which is fine for
        # what they are, but they must not be confused with the recorded totals
        # -- `get_learning_metrics` reports both, labelled.
        #
        # `knowledge_base_size` was removed from here: nothing ever assigned it,
        # so it was reported as 0 forever. It is measured now, from the stores
        # that actually hold knowledge.
        self.system_metrics = {
            "total_learning_sessions": 0,
            "successful_adaptations": 0,
            "cross_domain_insights": 0
        }

        # Exploration quota tracking (for MetaLearner hard gate)
        self.recent_strategy_usage = []  # Track last 100 strategy selections
        self.max_recent_strategies = 100

        # Circular dependency guard. The depth itself lives in the
        # `_learning_depth` ContextVar so it is per-task; only the limit is
        # configurable state on the instance.
        self._max_nesting_depth = 3
    
    async def start(self) -> None:
        """Start the unified learning system

        Raises:
            RuntimeError: If critical learning components fail to initialize
        """
        try:
            # Initialize logging database
            await self.log_db.initialize()
            logger.info("✅ Logging database initialized for learning activity tracking")

            # The learning system holds no model handle. A language model is the
            # TEACHER's alone; learning here is substrate-native (it proposes
            # candidates; evidence attests). Nothing in this file generates.

            # CRITICAL: Get memory system if not already set
            if self.memory_system is None:
                logger.info("Getting memory system from global singleton...")
                from core.memory import get_memory_agent
                self.memory_system = await get_memory_agent()

            # "CONNECTED" WAS ASSERTED, NOT CHECKED.
            #
            # get_memory_agent() returns the singleton WITHOUT initialising it
            # -- its own docstring tells the caller to await initialize()
            # next -- and this logged the tick regardless. Verified:
            # get_learning_state() reported memory_system_active=False right
            # after start() said the memory system was connected. It worked
            # anyway only because store_memory initialises lazily on first use,
            # so the first learning call of every process paid that cost and
            # any failure surfaced there instead of here.
            #
            # initialize() is idempotent (it returns early when already
            # initialised), so calling it is safe whoever else has.
            if hasattr(self.memory_system, "initialize"):
                await self.memory_system.initialize()

            if not getattr(self.memory_system, "initialized", False):
                raise RuntimeError(
                    "Memory system did not initialise; learning would be "
                    "recorded against a store that is not ready")

            logger.info("✅ Memory system connected and initialised")

            # Get domain systems if not already set
            if self.domain_registry is None:
                logger.info("Getting domain registry from global singleton...")
                from core.domain.domain_registry import get_domain_registry
                self.domain_registry = get_domain_registry()

            if self.universal_ontology is None:
                logger.info("Getting universal ontology from global singleton...")
                from core.domain.universal_ontology import get_universal_ontology
                self.universal_ontology = get_universal_ontology()

            if self.cross_domain_reasoner is None:
                logger.info("Getting cross-domain reasoner from global singleton...")
                from core.domain.cross_domain_reasoner import get_cross_domain_reasoner
                self.cross_domain_reasoner = get_cross_domain_reasoner()

            logger.info("✅ Domain systems connected")
            
            # CRITICAL: Initialize meta-learning system
            logger.info("Initializing meta-learning system...")

            await self.meta_learning.initialize()  # This raises on failure

            if not self.meta_learning.active:
                raise RuntimeError("MetaLearningSystem is not active after initialization")

            logger.info("✅ Meta-learning system initialized")

            # The authority's own recognised proposers. contribute() (and
            # admit_projection) admit a proposal ONLY from a registered
            # contributor -- an anonymous proposal has no traceable origin and
            # is rejected. Registration is provenance, not permission to attest:
            # what is admitted enters as a CANDIDATE with zero evidence, and only
            # the world attests.
            #
            # Only faculties that propose a RULE HYPOTHESIS are named here. The
            # analogy engine is the one such proposer today: it used to write
            # projected operators straight into the store, and now proposes them
            # through admit_projection(). The causal analyzer is NOT here: it is
            # a diagnostic that reasons via
            # the neural bridge and writes no rules. Neither bypasses the store,
            # so neither is a rule contributor.
            self._contributors.setdefault(
                "analogical_projection", "structural-analogy operator proposer")
            logger.info("✅ Learning contributors registered: %s",
                        ", ".join(sorted(self._contributors)))

            # Reload any persisted clause classifiers so a trained perceptual
            # learner survives a restart (its recognitions already persist as
            # beliefs; this restores the MECHANISM that produces them).
            try:
                restored = await self.load_classifiers()
                if restored:
                    logger.info("Restored %d persisted clause classifier(s)", restored)
            except Exception as error:
                logger.error("clause classifiers could not be read from the store: %s — "
                             "recognition starts without what it was trained on", error)

            self.initialized = True
            logger.info("✅ Unified learning system started successfully")

        except RuntimeError as re:
            # RuntimeError we raised - just re-raise
            self.initialized = False

            raise

        except Exception as e:
            logger.error(f"Unexpected error starting unified learning system: {e}")
            self.initialized = False

            raise RuntimeError(
                f"Unexpected error during learning system initialization: {e}\n"
                f"Check logs for full stack trace."
            ) from e
    
    async def _report_unmapped_learning_type(self, learning_type_name: str) -> None:
        """Record that a learning type has no family, on the failure record.

        A warning in a log file is what the CLASSIFICATION default effectively
        was -- invisible to every consumer. This puts it where the systems that
        watch for gaps can read it.
        """
        try:
            from core.observability import failure_record

            await failure_record.report(
                component="learning.unified_learning_system",
                failure_type="unmapped_learning_type",
                description=(f"Learning type {learning_type_name!r} has no "
                             f"TaskFamily; the example could not be scored "
                             f"against any strategy pool"),
                source_system="unified_learning_system",
                severity="medium",
                metadata={"learning_type": learning_type_name})
        except Exception as error:
            logger.error("Could not report unmapped learning type %r: %s",
                         learning_type_name, error)

    async def learn_from_example(self, example: Dict[str, Any]):
        """Learn from example - route to memory system + meta-learning

        This method NO LONGER uses learning_engine (deleted).
        Instead, it routes to:
        1. Meta-learning for strategy selection
        2. Memory system for persistent storage
        3. Meta-learning for outcome tracking

        Raises:
            RuntimeError: If circular dependency detected (learning calling learning)
        """
        if not self.initialized:
            await self.start()

        # CIRCULAR DEPENDENCY GUARD. Counts recursion within THIS task only, so
        # parallel learning is not mistaken for a cycle. See _learning_depth.
        depth = _learning_depth.get() + 1
        if depth > self._max_nesting_depth:
            logger.error(
                "🛑 CIRCULAR DEPENDENCY DETECTED: learning recursed %d levels "
                "within one task (limit %d)", depth, self._max_nesting_depth)
            raise RuntimeError(
                f"Circular dependency detected: learning called itself {depth} "
                f"levels deep within a single task. This prevents deadlock. "
                f"Check for autonomous_coordinator <-> learning circular calls."
            )
        if depth > 1:
            logger.warning("Learning nested call within one task (depth %d)", depth)

        depth_token = _learning_depth.set(depth)

        start_time = time.time()
        learning_id = str(uuid.uuid4())

        try:
            # THIS LANE CREDITS STRATEGIES. What an example says about the world
            # reaches the world only through the one door, from whoever says it,
            # judged by whether it is true (`consider`); never as a side effect of
            # crediting a strategy (docs/research/SEPARATION_MAP.md §11.6).

            # Extract learning type.
            #
            # Accepted as either the enum or its value, because the mapping
            # below is keyed by the ENUM: a producer that states
            # 'type': 'continual' would otherwise miss the lookup and fall to
            # the CLASSIFICATION default while appearing to have declared
            # itself. An unrecognised name is reported rather than silently
            # becoming SUPERVISED.
            learning_type = example.get('type') or LearningType.SUPERVISED
            if not isinstance(learning_type, LearningType):
                try:
                    learning_type = LearningType(str(learning_type).lower())
                except ValueError:
                    logger.warning(
                        "Unknown learning type %r; treating as SUPERVISED",
                        learning_type)
                    learning_type = LearningType.SUPERVISED
            learning_type_name = learning_type.value

            # 🧠 Use meta-learning to select optimal strategy with HARD GATE
            logger.info(f"📚 Learning from example (type: {learning_type_name})")

            # Calculate exploration quota used
            exploration_quota = self._calculate_exploration_quota()

            # Two different taxonomies meet here. This layer describes HOW it is
            # learning (LearningType: supervised/unsupervised/...); meta_learning
            # keys its strategies by WHAT KIND of task it is (TaskFamily:
            # classification/perception/...). Passing a LearningType straight
            # through never matched any registered strategy, so select_strategy
            # returned None and the next line dereferenced it.
            # The map is a LOSSY BRIDGE and the producer often knows better.
            # Six LearningTypes fan into eight TaskFamilies, so REASONING is
            # reachable only via META and CONTROL/GENERATION/REGRESSION not at
            # all. A reasoning engine reporting a derivation had to arrive as
            # CONTINUAL and be scored against the sequence arms, which say
            # nothing about reasoning. A stated family is used as given; the map
            # remains the fallback for callers that only speak LearningType.
            stated_family = example.get('task_family')
            task_family = None
            if stated_family is not None:
                if isinstance(stated_family, TaskFamily):
                    task_family = stated_family
                else:
                    try:
                        task_family = TaskFamily(str(stated_family).lower())
                    except ValueError:
                        logger.warning(
                            "Unknown task_family %r; deriving from learning type",
                            stated_family)
            if task_family is None:
                task_family = _LEARNING_TYPE_TO_TASK_FAMILY.get(learning_type)
            if task_family is None:
                # NO DEFAULT FAMILY. A learning type with no family has no arm
                # pool to be scored against, and choosing one anyway credits a
                # strategy for work it did not do -- which is exactly how the
                # classification arms accumulated 10,601 decisions.
                #
                # This returns rather than continuing, matching the existing
                # `strategy is None` path a few lines down: everything after
                # this point is written around a selected strategy (usage
                # tracking, memory tags, outcome credit), so there is no
                # "learn anyway" branch to fall into. The caller gets a named
                # reason instead of a silent mis-filing.
                logger.warning(
                    "No task family for learning type %r; no strategy pool "
                    "exists for it (add it to _LEARNING_TYPE_TO_TASK_FAMILY "
                    "if it has one)", learning_type_name)
                await self._report_unmapped_learning_type(learning_type_name)
                return {'success': False, 'error': 'unmapped_learning_type',
                        'learning_type': learning_type_name}

            # CAPTURE THE DECISION so the outcome can be joined back onto it.
            #
            # select_strategy writes the decision row (chosen arm, propensity,
            # candidates, context) and hands back its id through _decision_sink;
            # track_learning_outcome closes that row with what actually
            # happened. This lane passed neither, so every decision it made was
            # written open and never closed: 1,891 of 1,894 rows sat at
            # outcome_known=false with performance_score NULL. The propensity
            # needed for off-policy estimation was being recorded faithfully and
            # the reward beside it never was, which is the half that cannot be
            # reconstructed afterwards.
            decision_sink: Dict[str, Any] = {}
            strategy = await self.meta_learning.select_strategy(
                task_type=task_family,
                prefer_fast=False,
                min_confidence=0.5,
                enable_hard_gate=True,  # HARD GATE: Block unreliable strategies
                exploration_quota_used=exploration_quota,
                # The BASE decision problem. Namespaced arms in the same family
                # (executor:*, tasktype:*) belong to the coordinator's own
                # decisions and are not alternatives to a learning strategy.
                exclude_namespaced=True,
                decision_context={'learning_type': learning_type_name,
                                  'domain': example.get('domain'),
                                  'source': example.get('source')},
                _decision_sink=decision_sink,
            )
            decision_id = decision_sink.get("decision_id")

            gate_blocked = decision_sink.get("gate_blocked")
            if strategy is None and gate_blocked is None:
                logger.error(
                    f"No learning strategy available for {learning_type} "
                    f"(mapped to {task_family}). Registered families: "
                    f"{sorted({s.task_type.value for s in self.meta_learning.strategies.values()})}"
                )
                return {'success': False, 'error': 'no_strategy_available'}

            # Every arm failed the production gate. The example is still
            # learned from -- stored, and its domain still consulted for
            # transfer -- but no arm is credited with it, because none was fit
            # to be chosen. The selection is recorded so the exploration budget
            # counts it as a decision that spent none.
            self._track_strategy_usage(strategy)

            if strategy is not None:
                logger.info(
                    f"🎯 Meta-learning selected strategy: {strategy.strategy_type} "
                    f"(trials={strategy.trials}, success_rate={strategy.success_rate:.1%}, "
                    f"exploration_quota={exploration_quota:.1%})"
                )

            # 💾 ASK memory agent to store (it handles categorization, weighting, type)
            memory_id = None
            if self.memory_system:
                # Memory agent decides: memory_type, priority, worthiness, categorization
                # We just provide content + source_context (raw metadata)
                from core.memory import Origin
                # WHOSE EXAMPLE THIS IS. A reasoning outcome learned from names
                # the premises it ran over, and for a user those include their
                # own context -- written unowned, the summary put one speaker's
                # tellings in everyone's recall (measured 2026-09-26,
                # SYSTEM-CONVERSATION-01). An example that does not say is
                # refused, not filed as the substrate's own.
                if 'actor' not in example:
                    raise ValueError("a learning example must say whose experience it is "
                                     "('actor'); the substrate's own is SUBSTRATE_ACTOR")
                success, memory_id = await self.memory_system.store_memory(
                    content=f"Learning: {example.get('content', str(example)[:200])}",
                    origin=Origin.of(example['actor'], "learning example"),
                    # strategy.strategy_id, not the dataclass. Memory lowercases
                    # every tag, so passing the object raised
                    # "'LearningStrategy' object has no attribute 'lower'" and
                    # the memory was rejected -- which surfaced only as
                    # "Memory agent rejected: None".
                    tags=['learning', learning_type_name, 'unified_learning_system']
                         + ([strategy.strategy_id] if strategy is not None else []),
                    # JSON-safe at the boundary. 'example_data' is the
                    # producer's payload verbatim and this column is serialised
                    # as JSON, so one enum or dataclass in it loses the whole
                    # memory.
                    source_context=_json_safe({
                        'learning_id': learning_id,
                        'learning_type': learning_type_name,
                        'strategy': strategy.strategy_id if strategy is not None else None,
                        'strategy_type': (str(strategy.strategy_type)
                                          if strategy is not None else None),
                        'strategy_gate_blocked': gate_blocked,
                        # The OUTCOME AS STATED, not defaulted to a win. This
                        # read `example.get('success', True)`, so an example
                        # that said nothing was persisted as a success while the
                        # credit path below correctly recorded it as unknown --
                        # the stored record and the posterior disagreed.
                        'success': example.get('success'),
                        'accuracy': example.get('accuracy', 0.0),
                        'timestamp': time.time(),
                        'source': 'unified_learning_system',
                        'example_data': example
                    })
                )

                if success:
                    logger.info(f"💾 Memory agent stored learning: {memory_id}")
                else:
                    logger.warning(f"⚠️  Memory agent rejected: {memory_id}")

            else:
                logger.warning("⚠️  Memory system not available - learning NOT persisted!")

            # 📊 Track outcome in meta-learning for strategy optimization
            #
            # `example.get('success', True)` defaulted an unknown outcome to a
            # win, so any example lacking the key silently rewarded whatever
            # strategy was selected. Absent means unknown, and unknown earns no
            # credit.
            from core.learning.meta_learning import OutcomeClass, is_credit_eligible
            raw_success = example.get('success')
            if isinstance(raw_success, bool):
                success = raw_success
                outcome_class = (
                    OutcomeClass.SUCCESS if success else OutcomeClass.STRATEGY_FAILURE
                )
            else:
                success = False
                outcome_class = OutcomeClass.INSUFFICIENT_EVIDENCE
            metrics = {
                'accuracy': example.get('accuracy', 0.0),
                'confidence': example.get('confidence', 0.0),
                # The duration of the WORK, when the producer states it.
                # Measuring locally times this method's own bookkeeping -- 0.12s
                # against a 43s reasoning operation in the observed case -- and
                # that number becomes strategy.avg_time_ms and the efficiency
                # term of effectiveness_score, so the score would rank
                # strategies by how fast their paperwork was.
                'latency': float(
                    example.get('duration_s') or (time.time() - start_time)),
            }

            # Signature is (task_type, strategy_type, success, performance_score,
            # time_ms). It was called with strategy=/metrics=, which raised
            # TypeError on every invocation — so the bandit's successes/failures
            # never incremented and Thompson sampling drew from Beta(1,1) forever.
            if strategy is not None:
                await self.meta_learning.track_learning_outcome(
                    task_type=task_family,
                    strategy_type=strategy.strategy_type,
                    success=success,
                    performance_score=float(metrics.get('accuracy') or 0.0),
                    time_ms=float(metrics.get('latency') or 0.0) * 1000.0,
                    outcome_class=outcome_class,
                    context={'confidence': metrics.get('confidence'),
                             'learning_type': learning_type_name},
                    decision_id=decision_id,
                )

            # Update system metrics
            self.system_metrics['total_learning_sessions'] += 1
            if success:
                self.system_metrics['successful_adaptations'] += 1

            logger.info(f"✅ Learning complete in {metrics['latency']:.2f}s - Success: {success}")

            # CRITICAL: Log learning activity for compliance.
            #
            # This called log_activity(activity_type=, details=), which is not on
            # LoggingDatabase -- the class exposes log_operation(operation_type,
            # component, message, level, metadata). It sits in the SUCCESS path,
            # directly after "Learning complete", so every successful
            # learn_from_example raised AttributeError here; the except handler
            # then called the same missing method and raised again, so the
            # original outcome was never reported either. learn_from_example is
            # the one learning entry point the coordinator invokes.
            await self.log_db.log_operation(
                operation_type='learning',
                component='unified_learning_system',
                message=f"learning {learning_id} success={success}",
                level='INFO',
                metadata={
                    'learning_id': learning_id,
                    'learning_type': learning_type_name,
                    'strategy': strategy.strategy_id if strategy is not None else None,
                    'strategy_type': (str(strategy.strategy_type)
                                      if strategy is not None else None),
                    'strategy_gate_blocked': gate_blocked,
                    'success': success,
                    'accuracy': example.get('accuracy', 0.0),
                    'latency': metrics['latency'],
                    'memory_id': memory_id,
                    'source': example.get('source', 'user_interaction')
                }
            )

            # CROSS-DOMAIN: learning in a domain looks for what it already
            # knows elsewhere.
            #
            # Every part of this existed and none of it was reachable:
            # self.cross_domain_reasoner was assigned at :169 and never read,
            # transfer_learning_across_domains (:822) had zero callers,
            # learn_with_domain_context (:897) had zero callers, and the
            # cross_domain_transfers / cross_domain_insights counters were
            # incremented by code nothing invoked. learn_from_example is the one
            # entry point the coordinator actually calls, so the transfer path
            # attaches here rather than to a new lane beside it.
            transfer = None
            domain = example.get('domain') or example.get('domain_id')
            if domain:
                # Gated on the DOMAIN, not on `success`. `success` here is the
                # credit signal -- it reports whether the selected strategy
                # earned credit, and an example that does not state its outcome
                # is INSUFFICIENT_EVIDENCE (:378-385) rather than a failure.
                # Whether a strategy earned credit is a different question from
                # whether Lyric already holds a structure that applies here, and
                # an attempt that went badly is if anything MORE reason to ask
                # it. Gating on success meant the transfer path could not fire
                # for any example lacking an explicit outcome.
                transfer = await self._transfer_from_known_domains(
                    str(domain), task_id=example.get('task_id'))

            return {
                'success': success,
                # The IDENTIFIER. Returning the dataclass leaked an internal
                # object into every caller's payload, and anything that tried to
                # serialise the result failed on it.
                'strategy_used': strategy.strategy_id if strategy is not None else None,
                # Present when no arm passed the production gate: per-arm reasons.
                'strategy_gate_blocked': gate_blocked,
                'stored_in_memory': memory_id is not None,
                'memory_id': memory_id,
                'learning_id': learning_id,
                'metrics': metrics,
                'cross_domain': transfer,
                # WHY the outcome was what it was, and whether it moved a
                # posterior. `success` alone cannot separate "the strategy
                # failed" from "nothing could be concluded": both are False, and
                # only the first is evidence about the strategy. Callers that
                # need that distinction were reduced to guessing from it.
                'outcome_class': outcome_class.value,
                'credit_applied': strategy is not None and is_credit_eligible(outcome_class),
            }

        except Exception as e:
            logger.error(f"❌ Learning from example failed: {e}")

            # Log error with full stack trace
            import traceback
            try:
                await self.log_db.log_operation(
                    operation_type='learning_error',
                    component='unified_learning_system',
                    message=f"{type(e).__name__}: {e}",
                    level='ERROR',
                    metadata={
                        'error_type': type(e).__name__,
                        'error_message': str(e),
                        'example_type': example.get('type', 'unknown'),
                        'stack_trace': traceback.format_exc()
                    }
                )
            except Exception as log_error:
                # An error handler that raises destroys the error it was handling.
                # This one called a missing method and replaced every real
                # learning failure with AttributeError: log_activity.
                logger.error("Could not record learning failure %r: %s", e, log_error)

            return {
                "success": False,
                "error": str(e),
                "strategy_used": None,
                "stored_in_memory": False
            }

        finally:
            # Restore this task's depth exactly as it was. A token reset cannot
            # leave the guard in a state that rejects future work, which the
            # previous flag-and-counter pair demonstrably could.
            _learning_depth.reset(depth_token)


    def _calculate_exploration_quota(self) -> float:
        """
        Calculate % of recent cycles that used exploration strategies

        Returns:
            Float 0.0-1.0 representing exploration quota used
        """
        if not self.recent_strategy_usage:
            return 0.0

        # Count strategies with < 20 trials (exploration threshold). A decision
        # in which no arm passed the gate (None) chose nothing and spent no
        # exploration; it still counts as a decision, or a budget exhausted once
        # would never recover.
        exploration_count = sum(
            1 for strategy in self.recent_strategy_usage
            if strategy is not None and strategy.trials < 20
        )

        return exploration_count / len(self.recent_strategy_usage)

    def _track_strategy_usage(self, strategy):
        """
        Track strategy usage for exploration quota calculation

        Args:
            strategy: LearningStrategy that was just used
        """
        # Add to recent usage
        self.recent_strategy_usage.append(strategy)

        # Keep only last N strategies
        if len(self.recent_strategy_usage) > self.max_recent_strategies:
            self.recent_strategy_usage.pop(0)

        if strategy is None:
            return
        logger.debug(
            f"Strategy usage tracked: {strategy.strategy_id} "
            f"(recent={len(self.recent_strategy_usage)}, "
            f"exploration={self._calculate_exploration_quota():.1%})"
        )

    async def process_interaction(self, user_input: str, system_response: str) -> None:
        """Process a user interaction for learning"""
        interaction_example = {
            "input": user_input,
            "output": system_response,
            "context": {"interaction_type": "chat", "timestamp": asyncio.get_event_loop().time()}
        }
        
        await self.learn_from_example(interaction_example)
    
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        return {
            "initialized": self.initialized,
            "components": {
                "memory_system": getattr(self.memory_system, 'initialized', False),
                "meta_learning": getattr(self.meta_learning, 'initialized', False),
            },
            "metrics": self.system_metrics,
            "active_tasks": len(self.active_learning_tasks)
        }
    
    # ILearningSystem interface implementations
    async def initialize(self) -> bool:
        """Initialize the unified learning system
        
        Raises:
            RuntimeError: If initialization fails
        """
        await self.start()  # This raises on failure
        return True
    
    async def learn_from_data(self, data: Dict[str, Any], learning_type) -> Any:
        """Learn from provided data"""
        # The caller's learning_type has to travel INTO the example.
        #
        # It was only echoed back in the envelope below, while
        # learn_from_example reads example['type'] -- a key nothing ever set --
        # and so defaulted every event to SUPERVISED, which the table at :46
        # maps to CLASSIFICATION. learn_from_experience declares CONTINUAL and
        # the outcome was still recorded against CLASSIFICATION; the other five
        # TaskFamily branches were unreachable no matter what a caller asked
        # for. A payload that names its own type is the more specific statement
        # and still wins.
        result = await self.learn_from_example({'type': learning_type, **data})
        return {
            'event_id': f"unified_{int(time.time())}",
            'event_type': learning_type,
            'data': data,
            'outcome': result,
            'timestamp': time.time(),
            # The example's OWN stated confidence, or None. This was a literal
            # 0.8 on every envelope regardless of what happened -- including
            # for a learning call that failed -- so a caller reading it learned
            # only that someone had typed 0.8.
            'confidence': data.get('confidence'),
        }
    
    async def learn_from_experience(self, experience: Dict[str, Any]) -> Any:
        """Learn from experience data"""
        return await self.learn_from_data(experience, LearningType.CONTINUAL)
    
    async def learn_from_feedback(self, feedback: Dict[str, Any]) -> Any:
        """A verdict on a claim the substrate already made and already remembers.

        IT DOES NOT STORE A MEMORY OF ITS OWN. The interaction it is about
        already made one (the ingress `_remember`); a second record of the same
        thing would double-count it and split its evidence. This FLAGS that
        existing memory -- annotating it, never overwriting it -- and routes the
        verdict to the right owner.

        It also does NOT push a taught-fact verdict through the strategy-credit
        lane. A user agreeing or disagreeing with a fact is not evidence about
        which LEARNING STRATEGY was a good choice, and crediting an arm for it
        would teach the meta-learner a false relation (the exact defect the
        credit invariant exists to prevent). A strategy is credited only when
        the feedback is about a DECIDED action -- it carries a `decision_id`,
        and then the verdict is that decision's outcome.

        `feedback` keys: `memory_id` (the memory to flag), `success`
        (True confirms / False corrects), optional `content`/`about`, and --
        for action feedback only -- `decision_id`, `task_type`, `strategy_type`.
        """
        if not isinstance(feedback, dict):
            return {"event_type": "feedback", "memory_flagged": False,
                    "error": "feedback must be a dict carrying a memory_id"}

        memory_id = feedback.get("memory_id")
        verdict = bool(feedback.get("success"))

        # 1. FLAG THE EXISTING MEMORY -- merge only, so the claim's content and
        #    any prior metadata are untouched. `metadata` without merge, and
        #    `tags`, both REPLACE their column, so neither is used here.
        flagged = False
        if memory_id and self.memory_system and hasattr(self.memory_system, "update_memory"):
            try:
                flagged = await self.memory_system.update_memory(memory_id, {
                    "metadata": {"feedback": {
                        "verdict": "confirmed" if verdict else "corrected",
                        "surface": feedback.get("content"),
                        "about": feedback.get("about"),
                        "at": time.time(),
                    }},
                    "metadata.merge": True,
                })
            except Exception as error:
                raise_if_structural(error, "unified_learning_system.learn_from_feedback")
                logger.warning("feedback flag failed for %s: %s", memory_id, error)

        # NOTE: importance is a PROTECTED field (MemoryAgent gates
        # importance_score/confidence_score/memory_type behind a capability
        # token), so a correction does not silently rewrite the memory's weight
        # here -- that write would be refused and return False, a silent no-op.
        # The verdict lives in the flag; making a corrected memory actually
        # recall LESS is recall's job, reading metadata.feedback.verdict, and is
        # done there deliberately rather than smuggled through the gate.

        # 2. ACTION feedback (a decision was made) credits that decision's
        #    strategy; taught-fact feedback does not touch the meta-learner.
        credited = False
        decision_id = feedback.get("decision_id")
        task_type = feedback.get("task_type")
        strategy_type = feedback.get("strategy_type")
        if decision_id and task_type and strategy_type and self.meta_learning:
            from core.learning.meta_learning import OutcomeClass, TaskFamily
            try:
                family = task_type if isinstance(task_type, TaskFamily) else TaskFamily(str(task_type).lower())
                await self.meta_learning.track_learning_outcome(
                    task_type=family, strategy_type=strategy_type,
                    success=verdict,
                    performance_score=1.0 if verdict else 0.0,
                    time_ms=0.0, decision_id=decision_id,
                    outcome_class=(OutcomeClass.SUCCESS if verdict
                                   else OutcomeClass.STRATEGY_FAILURE))
                credited = True
            except Exception as error:
                raise_if_structural(error, "unified_learning_system.learn_from_feedback")
                logger.warning("feedback strategy credit failed: %s", error)

        # 3. WHAT THE VERDICT SAYS OF THE WORLD is a claim like any other: the
        #    conversation that heard it hands it to the one door as that person's
        #    evidence on the claim judged (`Conversation._take_feedback`,
        #    `consider`). Moving a belief here, on whatever text came with the
        #    verdict, moved one on the verdict sentence itself ("That's right.").
        belief_moved = False

        return {
            "event_type": "feedback",
            "memory_id": memory_id,
            "memory_flagged": flagged,
            "verdict": "confirmed" if verdict else "corrected",
            "strategy_credited": credited,
            "belief_moved": belief_moved,
        }
    
    async def transfer_learning(self, source_domain: str, target_domain: str) -> bool:
        """Transfer learning between domains.

        Delegates to the real implementation. This returned a bare ``True``
        unconditionally -- reporting a transfer that was never attempted, while
        transfer_learning_across_domains sat 200 lines below doing the actual
        work of proposing, validating and persisting the mappings.
        """
        result = await self.transfer_learning_across_domains(
            source_domain, target_domain, {"trigger": "transfer_learning"})
        return bool(result.get("success"))
    
    async def knowledge_base_size(self) -> Optional[Dict[str, int]]:
        """What the substrate actually holds, by store. None if unreadable.

        There was a `knowledge_base_size` counter in `system_metrics` that
        nothing ever wrote to, so every consumer reported 0. A count of what is known is measurable; it was
        just never measured.
        """
        try:
            from core.database import get_database_manager

            db = get_database_manager()
            # The model's: the substrate's own memories, never a person's
            # (in development they share the table).
            rows = await db.execute_query(
                """SELECT (SELECT count(*) FROM unified.concepts)            AS concepts,
                          (SELECT count(*) FROM unified.learned_rules)       AS rules,
                          (SELECT count(*) FROM memory_hot.memory_hot
                            WHERE user_id IS NULL OR user_id IN ('', '__substrate__'))
                                                                             AS memories""",
                None, fetch_all=True, store="model")
        except Exception as error:
            logger.error("Knowledge base size unavailable: %s", error)
            return None
        if not rows:
            return None
        row = rows[0]
        return {"concepts": int(row["concepts"]), "rules": int(row["rules"]),
                "memories": int(row["memories"]),
                "total": int(row["concepts"]) + int(row["rules"]) + int(row["memories"])}

    async def get_learning_metrics(self) -> Dict[str, Any]:
        """Learning metrics: this process's counters, and the recorded totals.

        Returned `self.system_metrics` alone -- three counters that start at
        zero every run. A caller asking a long-lived system how much it had
        learned got whatever had happened since the last restart, with nothing
        saying so.
        """
        try:
            recorded = await self.get_experience_count()
        except RuntimeError as error:
            # None, not 0: an unreadable store is not an empty one.
            logger.error("Recorded experience count unavailable: %s", error)
            recorded = None
        try:
            tool_usage = await self.tool_usage()
        except Exception as error:
            raise_if_structural(error, "unified_learning_system.get_learning_metrics")
            logger.error("Tool runs could not be read from experience: %s", error)
            tool_usage = {"available": False,
                          "reason": f"tool runs could not be read from experience: {error}"}
        return {
            "this_process": dict(self.system_metrics),
            "recorded_experiences": recorded,
            "knowledge_base": await self.knowledge_base_size(),
            "tool_usage": tool_usage,
        }

    # ── WHAT GOES INTO SHARED LEARNING ───────────────────────────────────────
    #
    # Whether what Lyric learns from an owner's work may go into what it learns for everyone, one switch for each
    # kind of work (`SHARED_LEARNING_CATEGORIES`), set in Context and privacy: a person's for their own work and an
    # organization's for its Work Context (the world decides who may set which, and hands it over). What goes in is
    # how Lyric carried the work out -- the steps and tools, what succeeded or failed, how it overcame each failure --
    # never anyone's context. Off stops what goes in from then on; nothing already learned is taken back, and Lyric
    # goes on learning from the work for its owner alone. Until a switch is set it is on, as it always was. Every flip
    # is kept, with who flipped it. A setting, not memory: kept in the running store beside the operating modes and
    # the reward allowances.

    _SHARED_LEARNING_DDL = [
        """CREATE TABLE IF NOT EXISTS unified.shared_learning (
               owner     TEXT NOT NULL,
               category  TEXT NOT NULL,
               shares    BOOLEAN NOT NULL,
               set_by    TEXT NOT NULL,
               set_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
               PRIMARY KEY (owner, category))""",
        """CREATE TABLE IF NOT EXISTS unified.shared_learning_history (
               seq       BIGSERIAL PRIMARY KEY,
               owner     TEXT NOT NULL,
               category  TEXT NOT NULL,
               shares    BOOLEAN NOT NULL,
               set_by    TEXT NOT NULL,
               set_at    TIMESTAMPTZ NOT NULL DEFAULT now())""",
    ]

    async def shared_learning(self, owner: str) -> Dict[str, Any]:
        """Where each of `owner`'s switches is: whether that kind of their work goes into shared learning, and who
        set it when (None until someone has)."""
        from core.database import get_database_manager
        db = get_database_manager()
        await db.ensure_schema("shared_learning", self._SHARED_LEARNING_DDL, store="runtime")
        rows = await db.execute_query(
            "SELECT category, shares, set_by, set_at FROM unified.shared_learning WHERE owner = $1",
            (str(owner),), fetch_all=True, store="runtime") or []
        held = {row["category"]: row for row in rows}
        categories = {}
        for category in SHARED_LEARNING_CATEGORIES:
            row = held.get(category)
            categories[category] = ({"shares": True, "set_by": None, "set_at": None} if row is None else
                                    {"shares": bool(row["shares"]), "set_by": row["set_by"],
                                     "set_at": row["set_at"].isoformat()})
        return {"owner": str(owner), "categories": categories}

    async def set_shared_learning(self, owner: str, shares: bool, *, by: str,
                                  category: Optional[str] = None) -> Dict[str, Any]:
        """Set one of `owner`'s switches, or every one of them when no `category` is named (the switch over them
        all), flipped by the person `by`, and keep each flip. Refused for Lyric's own work, which is shared learning,
        for anything but on or off, and for a kind of work there is no switch for. Returns where they are now."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        from core.database import get_database_manager
        if is_substrate_actor(owner):
            raise ValueError("shared learning is a person's or an organization's to set; Lyric's own work is shared")
        if is_substrate_actor(by):
            raise ValueError("a shared learning switch is flipped by a person")
        if not isinstance(shares, bool):
            raise ValueError("shared learning is on or off")
        if category is not None and category not in SHARED_LEARNING_CATEGORIES:
            raise ValueError(f"there is no shared learning switch for {category!r}; there is one for each of "
                             f"{', '.join(SHARED_LEARNING_CATEGORIES)}")
        db = get_database_manager()
        await db.ensure_schema("shared_learning", self._SHARED_LEARNING_DDL, store="runtime")
        async with db.get_connection(store="runtime") as conn:
            async with conn.transaction():
                for each in ((category,) if category else SHARED_LEARNING_CATEGORIES):
                    await conn.execute(
                        "INSERT INTO unified.shared_learning (owner, category, shares, set_by) "
                        "VALUES ($1, $2, $3, $4) ON CONFLICT (owner, category) DO UPDATE SET "
                        "shares = EXCLUDED.shares, set_by = EXCLUDED.set_by, set_at = now()",
                        str(owner), each, shares, str(by))
                    await conn.execute(
                        "INSERT INTO unified.shared_learning_history (owner, category, shares, set_by) "
                        "VALUES ($1, $2, $3, $4)", str(owner), each, shares, str(by))
        return await self.shared_learning(owner)

    async def shares_learning(self, owner: Optional[str], category: str) -> bool:
        """Whether what Lyric learns from this kind of `owner`'s work may go into shared learning. Lyric's own work
        always does."""
        from core.agents.autonomous.shared_types import is_substrate_actor
        if category not in SHARED_LEARNING_CATEGORIES:
            raise ValueError(f"there is no shared learning switch for {category!r}")
        if is_substrate_actor(owner):
            return True
        return (await self.shared_learning(owner))["categories"][category]["shares"]

    @staticmethod
    def method_claim(method_memory_id: str) -> str:
        """The claim that a lifted method works, named by the memory that keeps
        it (MemoryAgent's method memory)."""
        return f"the substrate's method {method_memory_id} works"

    async def observe_method_outcome(self, method_memory_id: str, *, worked: bool,
                                     observation: str, owner: Optional[str], category: str) -> float:
        """One outcome of a lifted method that is world knowledge, as one witness of whether it works.

        The memory agent lifts a method from experiences and hands each counted outcome here (only outcomes the
        credit gate counts: a failure the world or the infrastructure caused moves nothing); a person's own belief
        in it, how it goes in their work, memory holds in their context. The shared belief rests on the method's
        memory, and `observation` (the occurrence it came from) keeps one outcome from counting twice.

        `owner` is whose work the outcome came from (None for Lyric's own), and `category` what kind of work it was
        (`work_category`). The shared belief is everyone's, so an outcome of work whose owner has turned shared
        learning off for its kind is refused (ValueError): it moves their own belief only, which the memory agent
        holds in their context.

        Each outcome is one weak witness, with the weight one cycle of domain competence carries
        (`COMPETENCE_EVIDENCE_QUALITY`): a method is believed to work only after several outcomes agree, and a
        later failure moves it back. Returns the posterior it moved to."""
        from core.integration.universal_domain_master import UniversalDomainMaster
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        if not await self.shares_learning(owner, category):
            raise ValueError(f"the {category} of {owner} do not go into shared learning")
        unc = get_uncertainty_system()
        belief = unc.observe_claim(self.method_claim(method_memory_id), "methods", supports=worked,
                                   quality=UniversalDomainMaster.COMPETENCE_EVIDENCE_QUALITY, source="experience",
                                   observation=observation, memory_id=method_memory_id)
        await unc.flush_belief(belief.belief_id)
        return float(belief.posterior_probability)

    async def tool_usage(self) -> Dict[str, Any]:
        """How the substrate's tools have performed, from what its experiences
        hold (the tool-run parts of its task and pursuit memories, read by the
        memory agent): per tool, the success rate over the runs with a verdict
        and the mean time over the runs that were timed; overall, the success
        rate and the number of runs.

        A rate or a time with nothing under it is None, never a number standing
        in for one, and `available` is False with the reason when no tool run is
        held at all."""
        from core.agents.memory_agent import memory_agent
        held = await memory_agent().tool_runs()
        if not held:
            return {"available": False, "reason": "no tool run is held in experience"}
        by_tool = []
        succeeded = failed = runs = 0
        for name in sorted(held):
            tally = held[name]
            judged = tally["succeeded"] + tally["failed"]
            by_tool.append({
                "tool": name,
                "runs": tally["runs"],
                "succeeded": tally["succeeded"],
                "failed": tally["failed"],
                "success_rate": (tally["succeeded"] / judged) if judged else None,
                "timed": tally["timed"],
                "avg_latency_ms": (1000.0 * tally["seconds"] / tally["timed"]
                                   if tally["timed"] else None),
            })
            succeeded += tally["succeeded"]
            failed += tally["failed"]
            runs += tally["runs"]
        judged = succeeded + failed
        return {"available": True, "by_tool": by_tool, "runs": runs,
                "success_rate": (succeeded / judged) if judged else None}

    async def get_learning_state(self) -> Dict[str, Any]:
        """Get current learning system state for self-improvement analysis"""
        return {
            'initialized': self.initialized,
            'active_tasks': len(self.active_learning_tasks),
            'total_learning_sessions': self.system_metrics.get('total_learning_sessions', 0),
            'successful_adaptations': self.system_metrics.get('successful_adaptations', 0),
            'knowledge_base': await self.knowledge_base_size(),
            # `x is not None` was true by construction for meta_learning (set
            # unconditionally in __init__) and for the other two after start(),
            # so all three reported "active" without checking anything. Each is
            # now asked whether it is actually initialised, and None means the
            # component is absent rather than inactive.
            'memory_system_active': (None if self.memory_system is None
                                     else bool(getattr(self.memory_system, 'initialized', False))),
            'meta_learning_active': (None if self.meta_learning is None
                                     else bool(getattr(self.meta_learning, 'active', False))),
            'recent_tasks': self.active_learning_tasks[-5:] if self.active_learning_tasks else []
        }
    
    async def consolidate_learning(self) -> Dict[str, Any]:
        """Settle what learning has left open, on the learning authority's own
        schedule (the `idle_learning_consolidation` tier). Induction is not
        here -- it is event-driven and drains the moment there is work. What
        accumulates without an event to close it is:

          * KNOWN UNKNOWNS whose answer has since been learned -- every open one
            goes through the resolution gate (knowledge, belief, domain), so a
            competence belief that settled after the closure that earned it
            still resolves what it answers;
          * DECISIONS whose outcome will never arrive -- a process that exited
            mid-task leaves the meta-learner's decision row open forever; they
            are closed as INDETERMINATE, credit-ineligible, never as failures;
          * TRAINED CLAUSE CLASSIFIERS -- persisted, so a recognizer trained
            since the last pass survives a crash, not only a clean shutdown.

        It begins by refreshing this instance's copies from the one store, so an
        instance settles what the MODEL has learned, not only what it did.

        Returns what each step did. (This raised NotImplementedError, after
        returning {'consolidated': True} having consolidated nothing.)"""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        report: Dict[str, Any] = {}
        # ONE STORE, MANY INSTANCES: first bring this instance's copies in line
        # with it -- the open unknowns others registered or resolved, and the
        # strategy arms others have recorded outcomes for.
        report["refreshed"] = {
            "known_unknowns": await get_uncertainty_system().refresh_known_unknowns(),
            "strategy_arms": await self.meta_learning.load_strategies()}
        report["known_unknowns"] = await self.resolve_open_unknowns()
        report["abandoned_decisions_closed"] = await self.meta_learning.reap_abandoned_decisions()
        report["classifiers_saved"] = await self.save_classifiers()
        logger.info("learning consolidated: %s", report)
        return report

    def learn_from_event(self, event: Dict[str, Any]) -> bool:
        """Learn from an autonomous system event. Returns whether learning began.

        THIS RETURNED True HAVING LEARNED NOTHING. It appended the event to
        `active_learning_tasks` -- a list that is only ever appended to, never
        drained and never learned from -- and reported success. The interface
        documents the return as "learning success", so every caller was told
        the event had been learned from when it had merely been remembered.
        The list also grew without bound for the life of the process.

        The method is synchronous and cannot await, so the event is handed to
        the real learning path as a task. The return value now states what
        actually happened: True when learning was started, False when there is
        no running loop to start it on -- in which case the event is queued and
        the queue is bounded.
        """
        record = {'type': 'event', 'data': event, 'timestamp': time.time()}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop: nothing can be learned right now. Say so rather than
            # reporting success, and keep the queue bounded.
            self.active_learning_tasks.append(record)
            del self.active_learning_tasks[:-self._max_queued_events]
            logger.warning(
                "learn_from_event called with no running event loop; the event "
                "was queued (%d held) but nothing has been learned from it",
                len(self.active_learning_tasks))
            return False

        # The event's own fields travel into the example, so an event that
        # states its outcome earns or loses credit like any other example.
        example = {k: v for k, v in event.items() if k != 'type'}
        example.setdefault('type', event.get('type', LearningType.CONTINUAL))
        example.setdefault('source', 'autonomous_event')

        task = loop.create_task(self.learn_from_example(example))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

        record['task_scheduled'] = True
        self.active_learning_tasks.append(record)
        del self.active_learning_tasks[:-self._max_queued_events]
        return True

    async def process_experience(self, experience: Dict[str, Any]) -> Dict[str, Any]:
        """Process experience data for learning"""
        result = await self.learn_from_example(experience)
        return {'processed': True, 'unified_result': result}
    
    @staticmethod
    def _task_family(value: Any):
        """A TaskFamily from a TaskFamily or its value -- refused otherwise."""
        from core.learning.meta_learning import TaskFamily
        if isinstance(value, TaskFamily):
            return value
        try:
            return TaskFamily(str(value))
        except ValueError:
            raise ValueError(f"{value!r} is not a task family; "
                             f"one of {[f.value for f in TaskFamily]}") from None

    async def update_strategy_effectiveness(
            self, task_family: Any, strategy_type: str, *, success: bool,
            performance_score: float, time_ms: float, outcome_class: Any,
            context: Optional[Dict[str, Any]] = None,
            decision_id: Optional[str] = None,
            predicted_success: Optional[float] = None) -> Any:
        """Record how a strategy ACTUALLY performed, so its effectiveness moves
        -- through the meta-learner, which persists the posterior and applies
        the credit gate (an infrastructure failure never charges a strategy).

        When the decision carried a prediction (`predict_outcome` at decision
        time), the prediction is checked against what happened: that is what
        calibrates it. A prediction never checked could not be wrong.

        (This raised NotImplementedError, after writing a second, unpersisted
        copy of a number the meta-learner already owns.)"""
        from core.learning.meta_learning import is_credit_eligible
        family = self._task_family(task_family)
        record = await self.meta_learning.track_learning_outcome(
            task_type=family, strategy_type=strategy_type, success=success,
            performance_score=performance_score, time_ms=time_ms,
            context=context, decision_id=decision_id, outcome_class=outcome_class)
        if predicted_success is not None and is_credit_eligible(outcome_class):
            from core.reasoning.bayesian_uncertainty import get_uncertainty_system
            get_uncertainty_system().record_prediction(
                f"strategy:{family.value}", float(predicted_success), bool(success))
        return record

    def _arms(self, family, strategy_prefix: str = "") -> List[Any]:
        return [self.meta_learning.strategies[sid]
                for sid in self.meta_learning.task_strategy_map.get(family, [])
                if str(self.meta_learning.strategies[sid].strategy_type).startswith(strategy_prefix)]

    async def recommend_strategies(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The strategies the EVIDENCE recommends for `context["task_family"]`
        (optionally only those whose type starts with
        `context["strategy_prefix"]`), best first: ranked by the lower bound of
        each arm's measured success rate (Wilson, 95%), so an arm that has won
        once is not ranked above one that has won ninety times in a hundred.
        Arms with no recorded outcome come last, with no rate -- untried is not
        a number. Empty when the family has no arms.

        (This raised NotImplementedError, after returning a fixed list of four
        subsystem names that were not strategies.)"""
        family = self._task_family(context.get("task_family"))
        ranked = []
        for arm in self._arms(family, str(context.get("strategy_prefix") or "")):
            tried = arm.trials > 0
            low, high = (self.meta_learning._calculate_confidence_interval(arm.successes, arm.trials)
                         if tried else (None, None))
            ranked.append({"strategy_id": arm.strategy_id,
                           "strategy_type": str(arm.strategy_type),
                           "trials": arm.trials, "successes": arm.successes,
                           "success_rate": arm.success_rate if tried else None,
                           "lower": low, "upper": high})
        ranked.sort(key=lambda r: (r["lower"] is not None, r["lower"] or 0.0, r["trials"]),
                    reverse=True)
        return ranked

    async def drain_events(self, timeout: float = 30.0) -> Dict[str, int]:
        """Wait for event-driven learning to finish. Call before shutting down.

        `learn_from_event` is synchronous and hands the work to a task, so if
        the process exits first that learning is abandoned mid-flight: the
        decision row was written when the arm was selected and the outcome
        never arrives. Verified -- one such row was left open by a test process
        that exited before its task completed.

        Returns what happened, so a caller can see whether the wait was enough
        rather than assuming it was.
        """
        pending = [t for t in self._event_tasks if not t.done()]
        if not pending:
            return {"pending": 0, "completed": 0, "timed_out": 0}

        logger.info("Draining %d in-flight learning task(s)", len(pending))
        done, not_done = await asyncio.wait(pending, timeout=timeout)
        if not_done:
            # Stated, not silently dropped: these will need reaping.
            logger.warning(
                "%d learning task(s) did not finish within %.0fs; their "
                "decisions will be closed as INDETERMINATE by the reaper",
                len(not_done), timeout)
        return {"pending": len(pending), "completed": len(done),
                "timed_out": len(not_done)}

    async def query_experiences(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search recorded learning experiences.

        THE QUERY WAS IGNORED. This returned the last ten entries of an
        in-process list regardless of what was asked for, so every query got
        the same answer and none of it survived a restart.

        `unified.operation_logs` is where `learn_from_example` records each
        completed experience (595 of them, all written by this component), so
        that is what a query searches. Supported keys: `learning_type`,
        `strategy`, `success`, `source`, `since_minutes`, `limit`.
        """
        clauses = ["component = 'unified_learning_system'",
                   "operation_type = 'learning'"]
        params: List[Any] = []

        for key in ("learning_type", "strategy", "source"):
            if query.get(key) is not None:
                params.append(str(query[key]))
                clauses.append(f"metadata->>'{key}' = ${len(params)}")
        if isinstance(query.get("success"), bool):
            clauses.append(
                f"(metadata->>'success')::boolean IS {str(query['success']).upper()}")
        if query.get("since_minutes"):
            clauses.append(
                f"created_at > NOW() - INTERVAL '{int(query['since_minutes'])} minutes'")

        limit = max(1, min(int(query.get("limit", 50)), 500))
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                f"SELECT log_id, message, metadata, created_at FROM unified.operation_logs "
                f"WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT {limit}",
                tuple(params) or None, fetch_all=True) or []
        except Exception as error:
            # Empty would read as "no experience matches", which is a different
            # answer from "the store could not be searched".
            logger.error("Experience query failed: %s", error)
            raise RuntimeError(
                f"Could not search recorded experiences: {error}") from error

        out: List[Dict[str, Any]] = []
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (TypeError, ValueError):
                    metadata = {}
            out.append({"log_id": row["log_id"], "message": row["message"],
                        "recorded_at": row["created_at"], **(metadata or {})})
        return out

    async def get_experience_count(self) -> int:
        """How many learning experiences have been recorded, in total.

        Counted `len(self.active_learning_tasks)` -- an in-process list that
        holds queued events rather than experiences, and starts empty every
        run. The recorded count is 595 and survives restarts.
        """
        try:
            from core.database import get_database_manager

            rows = await get_database_manager().execute_query(
                "SELECT count(*) AS n FROM unified.operation_logs "
                "WHERE component = 'unified_learning_system' "
                "  AND operation_type = 'learning'", None, fetch_all=True)
        except Exception as error:
            logger.error("Experience count unavailable: %s", error)
            raise RuntimeError(
                f"Could not count recorded experiences: {error}") from error
        return int(rows[0]["n"]) if rows else 0
    
    async def predict_outcome(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """What the evidence predicts for a decision: the probability that
        `context["strategy_type"]` (or, without one, any arm of the family)
        succeeds on a `context["task_family"]` task -- the mean of the same
        Beta(successes+1, failures+1) posterior the bandit samples from, with
        its Wilson interval and how many outcomes it rests on. With no outcome
        recorded the prediction is None: there is nothing to predict from.

        Checked afterwards: pass it as `predicted_success` to
        `update_strategy_effectiveness` with the outcome.

        (This raised NotImplementedError, after returning 0.85/0.8 for every
        context.)"""
        family = self._task_family(context.get("task_family"))
        wanted = context.get("strategy_type")
        arms = [a for a in self._arms(family)
                if wanted is None or str(a.strategy_type) == str(wanted)]
        trials = sum(a.trials for a in arms)
        successes = sum(a.successes for a in arms)
        subject = str(wanted) if wanted is not None else f"any {family.value} strategy"
        if trials == 0:
            return {"predicted_success": None, "interval": None, "evidence": 0,
                    "basis": f"no outcome recorded for {subject}"}
        low, high = self.meta_learning._calculate_confidence_interval(successes, trials)
        return {"predicted_success": (successes + 1) / (trials + 2),
                "interval": (low, high), "evidence": trials,
                "basis": f"{successes}/{trials} outcomes for {subject}"}

    async def _transfer_from_known_domains(self, target_domain: str,
                                           max_sources: int = 3,
                                           task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """When learning in a domain, ask what already-learned domain applies.

        This is the call site transfer_learning_across_domains never had. It
        answers the question the cross-domain layer exists for -- "does a
        structure I already hold fit this?" -- at the moment new learning
        arrives, which is when the answer can still change what is stored.

        Sources are ranked by the registry's own similarity so a transfer is
        attempted against the domains most likely to carry a correspondence,
        rather than every domain in the store. A domain never transfers from
        itself.
        """
        registry = self.domain_registry
        if registry is None:
            from core.domain.domain_registry import get_domain_registry
            registry = get_domain_registry()
            self.domain_registry = registry
        # Initialize REGARDLESS of who assigned it. start() (:156-159) sets
        # self.domain_registry from the singleton accessor and never awaits
        # initialize(), so registry.domains is empty and every domain reads as
        # "not registered" -- an assigned handle that is not a loaded registry.
        if not registry.initialized:
            await registry.initialize()

        # RESOLVE the reference; do not coerce it.
        #
        # This built `f"domain_{target_domain}"` by hand -- the exact coercion
        # resolve_domain_reference exists to replace. The live producer
        # (_infer_domain_from_task) classifies work into CATEGORIES
        # ("scientific", "technical"), and `domain_scientific` is a registered
        # domain holding ZERO concepts, so the coercion resolved to a real-but-
        # empty node and every transfer came back "nothing similar". The
        # concepts were never in the category; they are in the fields beneath
        # it, which is what the resolver returns.
        try:
            resolved = registry.resolve_domain_reference(
                target_domain, require_concepts=True)
        except UnresolvedDomainReference:
            # Naming something that does not exist is a different fact from
            # naming a real domain with nothing in it, and is kept separate.
            logger.info(
                "Cross-domain transfer skipped: %r resolves to no registered domain",
                target_domain)
            return {"attempted": False, "reason": "target domain not registered"}

        if not resolved:
            logger.info(
                "Cross-domain transfer skipped: %r resolves only to domains "
                "holding no concepts", target_domain)
            return {"attempted": False, "reason": "target domain holds no concepts"}

        # A category names many fields. Transfer INTO the best-attested one:
        # the resolver already ranks by concept count, and reasoning into every
        # member would multiply one observation into many transfers that share
        # a single piece of evidence.
        canonical = resolved[0].domain_id
        if len(resolved) > 1:
            logger.info(
                "%r resolved to %d populated field(s); transferring into %s",
                target_domain, len(resolved), canonical)

        from core.integration.universal_domain_master import get_universal_domain_master
        udm = get_universal_domain_master()
        try:
            # Through the Master -- the authority for the domain system.
            similar = await udm.similar_domains(canonical, threshold=0.0)
        except Exception as e:
            raise_if_structural(e, "UnifiedLearningSystem._transfer_from_known_domains")
            logger.warning("Similarity ranking unavailable: %s", e)
            return {"attempted": False, "reason": f"similarity unavailable: {e}"}

        # TWO-STAGE SELECTION: cheap filter, then rank on the real signal.
        #
        # Ranking by domain similarity alone correlates only 0.209 with the
        # concept-level mapping strength transfer actually consumes — they
        # answer different questions ("are these fields alike?" versus "do these
        # two concepts correspond?"). Ranking on the proxy put a domain with
        # ZERO mappings in the top three while domains at 0.80 were skipped.
        #
        # Concept-level mappings are the ground truth and cost a scoring pass per
        # domain pair, so similarity is used for what it is good for --
        # narrowing the field -- and the shortlist is then ordered by what will
        # actually be transferred.
        shortlist = [d.domain_id for d, _score in similar
                     if d.domain_id != canonical and d.concepts][:max_sources * 3]

        scored = []
        probe_failures = []
        for candidate in shortlist:
            try:
                mappings = await udm.suggest_mappings(candidate, canonical)
            except Exception as e:
                raise_if_structural(e, "UnifiedLearningSystem._transfer_from_known_domains")
                logger.error("Mapping probe %s -> %s failed: %s", candidate, canonical, e)
                probe_failures.append((candidate, f"{type(e).__name__}: {e}"))
                continue
            if mappings:
                scored.append((max(m.strength for m in mappings), len(mappings), candidate))

        scored.sort(reverse=True)
        sources = [c for _s, _n, c in scored[:max_sources]]
        if scored:
            logger.info(
                "Transfer sources for %s ranked by mapping strength: %s",
                canonical, [(c, round(s, 3)) for s, _n, c in scored[:max_sources]])
        if not sources:
            # Two different real negatives, kept apart. "No other populated
            # domain" is a statement about coverage; "populated domains exist
            # but none share a mapping" is a statement about correspondence, and
            # only the second says anything about this domain's relationship to
            # what Lyric knows.
            if probe_failures:
                reason = (f"{len(probe_failures)} of {len(shortlist)} mapping probe(s) "
                          f"failed; the rest share no mapping")
            elif not shortlist:
                reason = "no other populated domain"
            else:
                reason = f"{len(shortlist)} domain(s) searched, none share a mapping"
            return {"attempted": True, "sources_considered": len(shortlist),
                    "transfers": [], "reason": reason, "probe_failures": probe_failures}

        transfers = []
        for src in sources:
            result = await self.transfer_learning_across_domains(
                src, canonical,
                {"trigger": "learn_from_example", "task_id": task_id})
            if result and result.get("success"):
                # "mapping_count" is the key transfer_learning_across_domains
                # actually returns. Reading "mappings_found" with a .get default
                # reported 0 mappings on every SUCCESSFUL transfer -- the same
                # source that had just been ranked first on 10 real mappings.
                # A default silently supplies a plausible value for a key that
                # does not exist, which is why the contradiction survived.
                #
                # It counts VALIDATED mappings. The candidate total is reported
                # beside it rather than in place of it, so a transfer can never
                # be read as larger than what survived validation.
                transfers.append({"source": src,
                                  "validated": result["mapping_count"],
                                  "candidates": result["candidates_considered"]})

        logger.info(
            "Cross-domain: learning in %s consulted %d known domain(s), %d transferred",
            canonical, len(sources), len(transfers))
        return {"attempted": True, "sources_considered": len(sources),
                "transfers": transfers, "probe_failures": probe_failures}

    async def transfer_learning_across_domains(self, source_domain: str, target_domain: str,
                                               knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """Transfer learned knowledge from one domain to another"""
        try:
            logger.info(f"Transfer learning: {source_domain} -> {target_domain}")

            # THE ATTEMPT IS COUNTED HERE, THE SUCCESS BELOW.
            #
            # Both counters were incremented on the same line in the success
            # branch, so `transfer_learning_successes` was always exactly equal
            # to `cross_domain_transfers` and one of the two carried no
            # information -- while get_domain_learning_stats reported them side
            # by side as if they were independent facts. A success rate could
            # never be anything but 100%.
            self.domain_learning_stats["cross_domain_transfers"] += 1

            # Cross-domain mapping is owned by the Universal Domain Master: it
            # proposes the candidates and is the one writer of mappings,
            # transfers and their usage.
            from core.integration.universal_domain_master import get_universal_domain_master
            udm = get_universal_domain_master()

            # start() assigns the ontology handle without initialising it, the
            # same defect the registry had; validation would then run against an
            # unloaded ontology.
            if self.universal_ontology is None:
                from core.domain.universal_ontology import get_universal_ontology
                self.universal_ontology = get_universal_ontology()
            if not getattr(self.universal_ontology, "initialized", False):
                await self.universal_ontology.initialize()

            # A domain is named under either spelling of its field -- a learned
            # one is registered bare, a caller may write `domain_<field>` -- and
            # the Master reads the registry by the id it is held under. A name
            # nothing holds stays as given, for the Master to report unknown.
            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = get_domain_registry()
                self.domain_registry = registry
            if not registry.initialized:
                await registry.initialize()
            source_domain = getattr(registry.domain_for_field(source_domain),
                                    "domain_id", source_domain)
            target_domain = getattr(registry.domain_for_field(target_domain),
                                    "domain_id", target_domain)
            mappings = await udm.suggest_mappings(source_domain, target_domain)

            # VALIDATE, then PERSIST WITH THE VERDICT.
            #
            # The suggestion is a fresh proposal, and before this path stored
            # them nothing did, which is why unified.domain_mappings
            # held 0 rows while 29 candidates were being found. add_cross_domain_
            # mapping and create_knowledge_transfer both existed with zero
            # callers; each takes exactly the dataclass produced here.
            #
            # Every candidate is stored WITH what was decided about it:
            #   validated=True   structure survived the test -> knowledge
            #   validated=False  structure was measurable and did not correspond
            #   validated=None   too little structure to judge -> still a candidate
            # All three are persisted, because the readers of this table
            # (_load_mappings, UniversalDomainMaster._find_cross_domain_mappings)
            # select `verified IS NULL OR verified IS TRUE` -- they are built to
            # tell an untested proposal from a refuted one. Dropping the
            # indeterminate rows would throw away that distinction, and storing
            # any of them without a verdict is how a proposal silently becomes
            # knowledge.
            accepted, rejected, indeterminate = [], [], []
            for candidate in mappings:
                verdict = await self.universal_ontology.validate_cross_domain_mapping({
                    "source_concept_id": candidate.source_concept_id,
                    "target_concept_id": candidate.target_concept_id,
                })
                candidate.validation_score = float(verdict.get("confidence", 0.0) or 0.0)
                # A VERDICT WAS REACHED, whichever of the three it is. Recorded
                # so the store's writer can tell an INDETERMINATE ruling from a
                # candidate nobody put to the test; both leave `validated` None.
                candidate.judged = True
                if verdict["verdict"] == "ACCEPTED":
                    candidate.validated = True
                    accepted.append(candidate)
                elif verdict["verdict"] == "REJECTED":
                    candidate.validated = False
                    rejected.append(candidate)
                else:
                    indeterminate.append(candidate)
                if not await udm.record_mapping(candidate):
                    raise RuntimeError(
                        f"Cross-domain mapping {candidate.mapping_id} could not be "
                        f"stored; refusing to report a transfer that was not recorded")

            logger.info(
                "Cross-domain %s -> %s: %d candidate(s) -> %d accepted, %d rejected, "
                "%d indeterminate",
                source_domain, target_domain, len(mappings),
                len(accepted), len(rejected), len(indeterminate))

            # Only a VALIDATED mapping may carry a transfer. This is the line
            # between transfer proposed and transfer learned.
            mapping = accepted[0] if accepted else None
            if mapping is not None:
                from core.domain.domain_types import KnowledgeTransfer
                # Identified by WHAT IS TRANSFERRED, not by when it ran. A uuid4
                # here wrote a fresh row on every pass, so re-deriving the same
                # transfer accumulated identical rows that a reader would count
                # as repeated independent transfers. Re-running now updates the
                # one row the transfer corresponds to.
                digest = hashlib.sha256("\x1f".join(
                    [source_domain, target_domain, "structural_analogy"]
                    + sorted(m.mapping_id for m in accepted)).encode()).hexdigest()[:32]
                transfer = KnowledgeTransfer(
                    transfer_id=f"xfer_{digest}",
                    source_domain_id=source_domain,
                    target_domain_id=target_domain,
                    source_knowledge_ids=[m.source_concept_id for m in accepted],
                    target_knowledge_ids=[m.target_concept_id for m in accepted],
                    transfer_type="structural_analogy",
                    success_probability=mapping.validation_score,
                    # mapping_ids -- the field is List[str], and the mappings are
                    # already persisted rows, so the transfer references them
                    # rather than restating the concept pairs.
                    concept_mappings=[m.mapping_id for m in accepted],
                    transferred_concepts=[m.target_concept_id for m in accepted],
                    validation_results={
                        "accepted": len(accepted), "rejected": len(rejected),
                        "indeterminate": len(indeterminate),
                    },
                    effectiveness_score=mapping.validation_score,
                )
                if not await udm.record_knowledge_transfer(transfer):
                    raise RuntimeError(
                        f"Knowledge transfer {transfer.transfer_id} could not be "
                        f"stored; refusing to report an unrecorded transfer")
                # APPLIED, not merely discovered. usage_count is what separates a
                # correspondence Lyric keeps relying on from one it derived once,
                # and nothing had ever incremented it.
                # ATTRIBUTABLE. A usage event names the task it was applied to,
                # which is what lets transfer evaluation later ask "did the tasks
                # this mapping touched differ from the ones it did not?" rather
                # than only "did the domain improve afterwards?". Without a task
                # the application is unattributable, so it is not recorded as a
                # use at all.
                task_id = (knowledge or {}).get("task_id")
                if task_id:
                    await udm.record_mapping_usage(
                        [m.mapping_id for m in accepted],
                        task_id=str(task_id),
                        transfer_id=transfer.transfer_id,
                        provenance={"trigger": (knowledge or {}).get("trigger"),
                                    "source_domain": source_domain,
                                    "target_domain": target_domain})
                else:
                    logger.info(
                        "Transfer %s applied with no task identity; usage not "
                        "recorded (it could not be attributed to an outcome)",
                        transfer.transfer_id)

            if mapping:
                # Apply the mapping to transfer knowledge
                transferred_knowledge = {
                    "source_domain": source_domain,
                    "target_domain": target_domain,
                    "original_knowledge": knowledge,
                    "transferred_knowledge": (
                        mapping.to_dict() if hasattr(mapping, "to_dict")
                        else str(mapping)
                    ),
                    # The counts are kept APART. "mapping_count" previously
                    # reported every candidate the similarity scan produced, so a
                    # transfer in which the validator accepted 2 of 10 was
                    # reported to the caller as 10 mappings -- the eight refuted
                    # ones counted as transferred knowledge.
                    "mapping_count": len(accepted),
                    "candidates_considered": len(mappings),
                    "rejected": len(rejected),
                    "indeterminate": len(indeterminate),
                    # The mapping's OWN confidence, or None. The default was
                    # 0.7, and `or 0.7` additionally rewrote a genuine 0.0 --
                    # so a mapping the validator had no confidence in was
                    # reported at 0.7, the same figure as one that was never
                    # measured.
                    "confidence": (float(mapping.confidence)
                                   if getattr(mapping, "confidence", None) is not None
                                   else None),
                    "success": True
                }

                self.domain_learning_stats["transfer_learning_successes"] += 1
                self.system_metrics["cross_domain_insights"] += 1

                logger.info(f"Transfer learning successful: {source_domain} -> {target_domain}")
                return transferred_knowledge
            else:
                # Two different negatives. "Nothing looked similar enough to
                # propose" and "things were proposed and the validator refuted
                # them" say opposite things about these two domains, and only
                # the second is evidence about their correspondence.
                if not mappings:
                    error, error_class = ("No candidate mapping proposed",
                                          "no_candidate")
                else:
                    error = (f"{len(mappings)} candidate(s) proposed, none validated "
                             f"({len(rejected)} refuted, {len(indeterminate)} unjudgeable)")
                    error_class = "no_validated_mapping"
                logger.info("Transfer learning %s -> %s: %s",
                            source_domain, target_domain, error)
                return {
                    "success": False,
                    "error": error,
                    "error_class": error_class,
                    "candidates_considered": len(mappings),
                    "rejected": len(rejected),
                    "indeterminate": len(indeterminate),
                }

        except UnknownDomain as e:
            logger.warning(f"Transfer learning on unregistered domain(s): {e}")
            return {
                "success": False,
                "error": str(e),
                "error_class": "unknown_domain",
                "unregistered_domains": e.missing,
            }
        except Exception as e:
            # A defect here must not come back as "no mapping found" -- that is
            # exactly how the missing find_cross_domain_mapping() stayed hidden.
            raise_if_structural(e, "UnifiedLearningSystem.transfer_learning_across_domains")
            logger.error(f"Error in transfer learning: {e}", exc_info=True)
            return {"success": False, "error": str(e), "error_class": "operational"}

    async def learn_with_domain_context(self, example: LearningExample,
                                        domain: str) -> LearningResult:
        """Learn from example with domain-specific context"""
        try:
            logger.info(f"Domain-specific learning in domain: {domain}")

            registry = self.domain_registry
            if registry is None:
                from core.domain.domain_registry import get_domain_registry
                registry = self.domain_registry = get_domain_registry()
            if not registry.initialized:
                await registry.initialize()

            # RESOLVE the reference. Do not create a domain from it.
            #
            # This did `get_domain(domain)` and, on a miss, REGISTERED a new
            # empty Domain named after the reference. The caller's references
            # are CATEGORIES ('scientific', 'technical') produced by
            # _infer_domain_from_task, so what it created were empty
            # category-level domains -- which is where the 15 concept-less
            # domains beside the 18 real fields came from. Each one then made
            # the category look registered and populated-by-zero, so every
            # lookup through it returned a well-formed empty answer.
            #
            # A domain is something Lyric has learned, not something minted on
            # first mention. The registry already resolves a category to the
            # fields beneath it; the reference is answered, never invented.
            #
            # A WORLD LYRIC ACTS IN IS NOT YET A FIELD. A task names the domain
            # it acted in (`knowledge_domain_of`), and a world met by acting is
            # registered only once discovery crystallizes what was learned there
            # (`_idle_domain_discovery_work`). Until then the reference resolves
            # to nothing, which is this method's own `domain_empty` state --
            # handed again once the domain is learned -- and not a failure: it
            # raised here and was logged as an error with its traceback on every
            # pass, 107 times over 100 worlds of RULE-AUTHORITY-02's live arm.
            from core.domain.domain_registry import UnresolvedDomainReference
            try:
                resolved = registry.resolve_domain_reference(domain, require_concepts=True)
            except UnresolvedDomainReference:
                resolved = []
            if not resolved:
                logger.info(
                    "Domain-specific learning skipped: %r holds no learned concepts",
                    domain)
                return LearningResult(
                    result_id=str(uuid.uuid4()),
                    success=False,
                    learned_knowledge={},
                    error=f"domain reference {domain!r} holds no learned concepts",
                    metadata={"domain": domain, "domain_specific": True,
                              # Both facts present on EVERY path. A caller that
                              # has to check which keys exist before reading
                              # them is back to guessing what a result means.
                              "learning_recorded": False,
                              "strategy_earned_credit": False,
                              "error_class": "domain_empty"},
                )

            # The FIELD is what carries concepts and what the transfer path
            # reasons over. The caller's original reference is kept in metadata
            # so a category-level question stays distinguishable from a
            # field-level one.
            field = resolved[0].domain_id
            if field != domain:
                logger.info("Domain reference %r resolved to field %s", domain, field)

            # Perform learning using unified learning system.
            #
            # A fourth defect in the same method: `{**example}` was spreading a
            # LearningExample dataclass, which is not a mapping ->
            # TypeError: 'LearningExample' object is not a mapping. TypeError is
            # in STRUCTURAL_DEFECT_TYPES, so raise_if_structural below re-raises
            # it and even the except-branch LearningResult never returns.
            # learn_from_example takes Dict[str, Any]; convert at the boundary.
            # Resolved before the payload so an unknown task type simply
            # leaves the family unstated rather than raising here.
            _stated_family = task_family_for_task_type(example.task_type)

            payload = {
                **asdict(example),
                'domain': field,
                'domain_specific': True,
                # STATED, not defaulted. Without a 'type' this fell to
                # SUPERVISED -> CLASSIFICATION, so every task outcome was scored
                # against the classification arms by omission rather than by any
                # decision. A completed task is experience accumulated over
                # time, which is what CONTINUAL names, and the existing table at
                # :48 maps it to SEQUENCE. This lane earned no credit at all
                # before the outcome was readable, so nothing it built up is
                # being moved.
                'type': LearningType.CONTINUAL,
                # THE FAMILY THE WORK ACTUALLY BELONGS TO.
                #
                # Without this the family came from LearningType.CONTINUAL ->
                # SEQUENCE, so a completed execution task was scored
                # against the sequence arms. The example already carries the
                # coordinator's task type; TASK_TYPE_TO_FAMILY is the authority
                # on what family that is, and two task types (execution,
                # planning) are CONTROL work -- the family whose arms choose
                # between APPROACHES and
                # which had never once been selected.
                #
                # Omitted when the task type is absent or unknown, so the
                # CONTINUAL mapping still applies rather than a guess.
                **({'task_family': _stated_family} if _stated_family else {}),
                # Lifted to the top level because the transfer path reads it
                # there. Without the task identity a mapping application cannot
                # be tied to the outcome it may have influenced, which is the
                # difference between counting uses and attributing them.
                'task_id': (example.inputs or {}).get('task_id'),
            }

            # THE OUTCOME THE PRODUCER RECORDED, LIFTED TO WHERE IT IS READ.
            #
            # TaskOutcomeRecord states the result as targets['outcome'] --
            # "success" or "failure" -- and its confidence as quality_score.
            # asdict() puts both one level down from where learn_from_example
            # looks (it reads top-level 'success' and 'accuracy'), so every task
            # outcome arrived stating nothing about how it went and was
            # correctly classified INSUFFICIENT_EVIDENCE. 269 consecutive
            # outcomes were recorded that way, 4 of the 5 underlying tasks
            # having actually succeeded: the strategy could never earn or lose
            # credit from the one signal this tier exists to deliver.
            #
            # Only an outcome that is actually stated is lifted. An example that
            # says nothing about how it went stays INSUFFICIENT_EVIDENCE, which
            # is the honest reading and the case the test at
            # test_domain_expansion_chain.py pins as (recorded=True,
            # credit=False).
            outcome = (example.targets or {}).get('outcome')
            if isinstance(outcome, str) and outcome.lower() in ('success', 'failure'):
                succeeded = outcome.lower() == 'success'
                quality = float(example.quality_score or 0.0)
                payload['success'] = succeeded
                # performance_score measures HOW WELL the work went, not how
                # sure we are that it went badly -- so a confident failure
                # scores 0.0, not 0.9.
                payload['accuracy'] = quality if succeeded else 0.0
                payload['confidence'] = quality

            learning_result = await self.learn_from_example(payload)

            # LEARNED and EARNED CREDIT are different facts.
            #
            # learn_from_example's 'success' is the CREDIT signal: whether the
            # selected strategy earned credit for this example. An example that
            # states no outcome is INSUFFICIENT_EVIDENCE, not a failure. This
            # returned that flag as its own `success`, so an example that was
            # learned from perfectly well -- including one whose cross-domain
            # transfer ran and produced validated mappings -- came back as
            # success=False with no error and no error_class. A caller cannot
            # tell that from a real failure, and the only honest reading of a
            # bare False is "it did not work".
            #
            # `error` present means learn_from_example actually failed. Its
            # absence means the example WAS learned from, and the credit
            # question is reported separately.
            failure = learning_result.get('error')
            recorded = failure is None
            # A success no arm was credited with (none passed the production
            # gate) earned no strategy credit.
            earned_credit = (bool(learning_result.get('success', False))
                             and bool(learning_result.get('credit_applied', False)))

            if recorded:
                self.domain_learning_stats["domain_specific_learning"] += 1
                logger.info(
                    "Domain-specific learning recorded for %s (strategy credit: %s)",
                    field, "earned" if earned_credit else "not earned")

            metrics = learning_result.get('metrics', {}) or {}
            return LearningResult(
                result_id=learning_result.get('memory_id') or str(uuid.uuid4()),
                success=recorded,
                learned_knowledge=learning_result.get('learned_knowledge', {}) or {},
                accuracy=float(metrics.get('accuracy', 0.0) or 0.0),
                confidence=float(metrics.get('confidence', 0.0) or 0.0),
                error=failure,
                metadata={
                    "domain": field,
                    "domain_reference": domain,
                    "domain_specific": True,
                    # The two facts, named separately and always both present.
                    # `success` IS learning_recorded -- stated here so the
                    # relationship is checkable rather than conventional. The
                    # state the old interface could not represent at all is
                    # (recorded=True, credit=False): an example learned from
                    # whose strategy earned no credit. That is the normal case
                    # for an outcome carrying no accuracy signal, and it used to
                    # arrive at every caller as a bare success=False.
                    "learning_recorded": recorded,
                    "strategy_earned_credit": earned_credit,
                    # strategy_earned_credit=False meant two opposite things:
                    # "the posterior did not move because nothing could be
                    # concluded" and "the posterior moved, recording a failure".
                    # Those are the difference between no evidence and negative
                    # evidence, so the class and the credit decision are stated
                    # rather than left to be inferred from a single False.
                    "outcome_class": learning_result.get('outcome_class'),
                    "credit_applied": learning_result.get('credit_applied', False),
                    "cross_domain": learning_result.get('cross_domain'),
                    "metrics": metrics,
                    **({} if recorded else {"error_class": "learn_from_example_failed"}),
                },
            )

        except Exception as e:
            raise_if_structural(e, "UnifiedLearningSystem.learn_with_domain_context")
            logger.error(f"Error in domain-specific learning: {e}", exc_info=True)
            return LearningResult(
                result_id=str(uuid.uuid4()),
                success=False,
                learned_knowledge={},
                error=str(e),
                metadata={"domain": domain, "domain_specific": True,
                          "learning_recorded": False,
                          "strategy_earned_credit": False,
                          "error_class": type(e).__name__},
            )

    def get_domain_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about domain knowledge usage in learning"""
        return {
            "cross_domain_transfers": self.domain_learning_stats["cross_domain_transfers"],
            "domain_specific_learning": self.domain_learning_stats["domain_specific_learning"],
            "transfer_learning_successes": self.domain_learning_stats["transfer_learning_successes"],
            "total_cross_domain_insights": self.system_metrics["cross_domain_insights"],
            # Meaningful only now that attempts and successes are counted
            # separately. None with no attempts: a rate over zero tries is
            # undefined, and 0.0 would read as "every transfer failed".
            "transfer_success_rate": (
                self.domain_learning_stats["transfer_learning_successes"]
                / self.domain_learning_stats["cross_domain_transfers"]
                if self.domain_learning_stats["cross_domain_transfers"] else None),
        }

    # ═══════════════════════════════════════════════════════════════════════
    # CAPABILITY BASELINES + REGRESSION (owned by the authority — learning is
    # what changes competence, so "is a capability improving or regressing over
    # the long horizon?" is the authority's question). Generic over
    # (component, metric, value): a caller records a measurement each cycle; the
    # authority holds the durable baseline and reports which capabilities are
    # degrading. A caller that can confirm a degradation against a live reading
    # verifies it itself — this owns the baseline store + the degrading query and
    # nothing that couples it back to a specific consumer.
    # ═══════════════════════════════════════════════════════════════════════

    #: A capability counts as improving/degrading only past this ± percent change
    #: from its baseline; smaller moves are stable (noise, not a trend).
    _CAPABILITY_TREND_PCT = 5.0

    async def _ensure_capability_schema(self) -> None:
        if getattr(self, "_capability_schema_ready", False):
            return
        from core.database import get_database_manager
        await get_database_manager().execute_query(
            """
            CREATE TABLE IF NOT EXISTS unified.long_term_baselines (
                component_name         TEXT NOT NULL,
                metric_name            TEXT NOT NULL,
                baseline_value         DOUBLE PRECISION NOT NULL,
                established_date       DATE NOT NULL DEFAULT CURRENT_DATE,
                cycles_tracked         INTEGER NOT NULL DEFAULT 1,
                last_cycle_value       DOUBLE PRECISION,
                trend_status           TEXT NOT NULL DEFAULT 'baseline_established',
                statistical_confidence DOUBLE PRECISION,
                created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (component_name, metric_name)
            )
            """,
            commit=True)
        self._capability_schema_ready = True

    async def track_capability_baseline(self, component_name: str, metric_name: str,
                                        current_value: float, *,
                                        establish: bool = True) -> Dict[str, Any]:
        """Track a capability metric against its long-term baseline.

        Establishes a baseline on first sight; on each later call compares the
        current value to it and records the trend (improving / degrading / stable
        by ±`_CAPABILITY_TREND_PCT`). Because the baseline persists across the whole
        lifetime, a capability that erodes over many cycles reads `degrading` even
        while each single cycle looked fine. No fabrication: a zero baseline yields
        a direction-only verdict, never a fake 0%.

        `establish=False` lets a caller that judges this reading unfit to BE a first
        baseline (e.g. a zero taken while the component was down — a zero baseline is
        a floor nothing can fall through, masking all later regression) record an
        update to an EXISTING baseline while refusing to create a new one from it.
        """
        from core.database import get_database_manager
        await self._ensure_capability_schema()
        db = get_database_manager()
        current_value = float(current_value)
        row = await db.execute_query(
            "SELECT baseline_value, cycles_tracked, last_cycle_value, trend_status "
            "FROM unified.long_term_baselines "
            "WHERE component_name = $1 AND metric_name = $2",
            params=(component_name, metric_name), fetch_one=True)

        if not row:
            if not establish:
                return {"status": "skipped_no_baseline"}
            await db.execute_query(
                "INSERT INTO unified.long_term_baselines "
                "(component_name, metric_name, baseline_value, established_date, "
                " cycles_tracked, last_cycle_value, trend_status) "
                "VALUES ($1, $2, $3, CURRENT_DATE, 1, $3, 'baseline_established')",
                params=(component_name, metric_name, current_value), commit=True)
            return {"status": "baseline_established", "baseline_value": current_value,
                    "cycles_tracked": 1, "trend_status": "baseline_established"}

        # Postgres returns NUMERIC as Decimal -- float() both sides before arithmetic,
        # or `current - baseline` raises on every comparison after the first.
        baseline_value = float(row["baseline_value"])
        cycles_tracked = int(row["cycles_tracked"]) + 1
        # Undefined (not 0) against a zero baseline: a percentage of zero has no
        # value, and 0.0 would read as "stable" on a comparison that cannot be made.
        pct_change = (((current_value - baseline_value) / baseline_value) * 100.0
                      if baseline_value != 0 else None)
        if pct_change is None:
            trend_status = ("improving" if current_value > baseline_value
                            else "degrading" if current_value < baseline_value else "stable")
        elif pct_change > self._CAPABILITY_TREND_PCT:
            trend_status = "improving"
        elif pct_change < -self._CAPABILITY_TREND_PCT:
            trend_status = "degrading"
        else:
            trend_status = "stable"

        await db.execute_query(
            "UPDATE unified.long_term_baselines "
            "SET cycles_tracked = $1, last_cycle_value = $2, trend_status = $3, updated_at = NOW() "
            "WHERE component_name = $4 AND metric_name = $5",
            params=(cycles_tracked, current_value, trend_status, component_name, metric_name),
            commit=True)
        return {"status": "updated", "baseline_value": baseline_value,
                "last_cycle_value": current_value, "cycles_tracked": cycles_tracked,
                "trend_status": trend_status,
                "pct_change": None if pct_change is None else round(pct_change, 2)}

    async def get_capability_regressions(self) -> List[Dict[str, Any]]:
        """Every capability whose long-term baseline is currently `degrading`.

        Returns the raw degrading rows (component, metric, baseline, last value,
        cycles tracked, days tracked). It does NOT judge operational noise vs real
        capability loss — a caller with a live reading verifies that against its
        own current data, which keeps the authority free of consumer coupling.
        """
        from core.database import get_database_manager
        await self._ensure_capability_schema()
        rows = await get_database_manager().execute_query(
            "SELECT component_name, metric_name, baseline_value, last_cycle_value, "
            "cycles_tracked, (CURRENT_DATE - established_date) AS days_tracked "
            "FROM unified.long_term_baselines WHERE trend_status = 'degrading'",
            fetch_all=True) or []
        out = []
        for r in rows:
            d = dict(r)
            for col in ("baseline_value", "last_cycle_value"):
                if d.get(col) is not None:
                    d[col] = float(d[col])
            out.append(d)
        return out

    async def record_metric(self, component_name: str, metric_name: str, value: float, *,
                            metric_type: str = "meta", baseline_value: Optional[float] = None,
                            target_value: Optional[float] = None,
                            metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Record a measured quantity: upsert the metric's definition (latest value +
        trend vs its baseline) and APPEND the value to its time series. This is the
        durable, queryable record of a metric over time, re-homed onto the authority
        so contributors (e.g. the meta-metrics monitor mirroring the meta-learner's
        standards) persist their metrics through the one owner. No fabrication: a
        zero/absent baseline gives a direction-only or no trend, never a fake 0%.
        """
        import json as _json
        from core.database import get_database_manager
        db = get_database_manager()
        value = float(value)
        base = None if baseline_value is None else float(baseline_value)
        # improvement % is undefined (not 0) against a zero/absent baseline.
        pct = (((value - base) / abs(base)) * 100.0) if base not in (None, 0) else None
        if pct is None:
            trend = ("improving" if base is not None and value > base
                     else "degrading" if base is not None and value < base else "stable")
        elif pct > self._CAPABILITY_TREND_PCT:
            trend = "improving"
        elif pct < -self._CAPABILITY_TREND_PCT:
            trend = "degrading"
        else:
            trend = "stable"
        meta_json = _json.dumps(metadata or {}, default=str)
        row = await db.execute_query(
            "INSERT INTO improvement_metrics "
            "(component_name, metric_type, metric_name, baseline_value, current_value, "
            " target_value, improvement_percentage, trend, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
            "ON CONFLICT (component_name, metric_name) DO UPDATE SET "
            "  baseline_value = EXCLUDED.baseline_value, current_value = EXCLUDED.current_value, "
            "  target_value = EXCLUDED.target_value, "
            "  improvement_percentage = EXCLUDED.improvement_percentage, "
            "  trend = EXCLUDED.trend, metadata = EXCLUDED.metadata, updated_at = NOW() "
            "RETURNING metric_id",
            params=(component_name, metric_type, metric_name, base, value, target_value,
                    pct, trend, meta_json), fetch_one=True, commit=True)
        metric_id = row["metric_id"]
        await db.execute_query(
            "INSERT INTO metric_measurements (metric_id, value, metadata) VALUES ($1, $2, $3)",
            params=(metric_id, value, meta_json), commit=True)
        return {"metric_id": int(metric_id), "current_value": value, "trend": trend,
                "improvement_percentage": None if pct is None else round(pct, 2)}

    async def benchmark_capability(self, *, cycle_id: Optional[str] = None,
                                   domains: Optional[List[str]] = None,
                                   sample_size: Optional[int] = None) -> Dict[str, Any]:
        """Measure the substrate's capability on the frozen benchmark suite, and track
        each domain's score as a long-term capability baseline.

        The authority owns capability measurement: it runs the suite (substrate-first,
        answered by the neural bridge, graded by a frozen grader — so it measures the
        substrate, not a model) and feeds the resulting domain + overall scores into
        `track_capability_baseline`, so a benchmark that shows the substrate getting
        WORSE over cycles surfaces as a real capability regression. Returns the cycle's
        report. No fabrication: an unmeasured domain is None, not zero.
        """
        from core.learning.capability_benchmark import get_capability_benchmark_suite
        suite = get_capability_benchmark_suite()
        cid = cycle_id or f"benchmark_{int(time.time())}"
        report = await suite.run_benchmarks(cid, domains=domains, sample_size=sample_size)
        # Each measured domain score (and the overall) becomes a tracked capability
        # baseline on 0-100, so regression detection rides on real benchmark movement.
        for dom in ("reasoning", "coding", "analysis", "comprehension"):
            s = getattr(report, f"{dom}_score", None)
            if s is not None:
                await self.track_capability_baseline("learning_benchmark", dom, float(s) * 100.0)
        if report.overall_score is not None:
            await self.track_capability_baseline(
                "learning_benchmark", "overall", float(report.overall_score) * 100.0)
        return {
            "cycle_id": report.cycle_id,
            "overall_score": report.overall_score,
            "reasoning_score": report.reasoning_score,
            "coding_score": report.coding_score,
            "analysis_score": report.analysis_score,
            "comprehension_score": report.comprehension_score,
            "tests_passed": report.tests_passed,
            "tests_failed": report.tests_failed,
            "confidence_interval": report.confidence_interval,
        }

    # ═══════════════════════════════════════════════════════════════════════
    # LEARNING AUTHORITY (moved in from the deleted learning_authority.py).
    # This class IS the authority: it owns the substrate's learners and the
    # boundary around what may propose. A contributor may PROPOSE (a hypothesis,
    # a situation, a formalization); it may NOT ATTEST -- nothing it offers is
    # evidence. Everything admitted through contribute() enters as CANDIDATE with
    # zero evidence roots; only world-supplied outcomes move it.
    # ═══════════════════════════════════════════════════════════════════════

    @property
    def store(self):
        if self._store is None:
            self._store = get_rule_store()
        return self._store

    @property
    def inducer(self):
        if self._inducer is None:
            self._inducer = get_rule_inducer()
        return self._inducer

    def register_contributor(self, name: str, role: str) -> None:
        """Named so provenance survives. An anonymous proposal is untraceable."""
        self._contributors[name] = role
        logger.info(f"learning contributor registered: {name} ({role})")

    @property
    def contributors(self) -> Dict[str, str]:
        return dict(self._contributors)

    async def train_clause_classifier(
            self, name: str, members: Dict[str, Sequence[str]], *,
            others: Sequence[str] = (), domain: str = "perception",
            epochs: int = 40, reject_label: str = "none_of_these",
            config: Any = None) -> Dict[str, Any]:
        """Grow a CLAUSE POPULATION for these categories, from the same labelled
        instances `induce_category` generalises from — the second of the two
        recognition paths, learned by the one teaching.

        The two are the same family at different scales, which is why they live
        side by side on this authority. Anti-unification keeps ONE conjunction
        per category: exact, legible, learnable from two examples, and unable to
        represent a category that is a DISJUNCTION of conditions ("a red circle
        OR a blue square") — it reports `multiple_hypotheses` and waits for the
        demonstration that would decide it. A Tsetlin population keeps many
        weighted clauses arguing for and against, so it represents disjunction,
        improves with more data, and abstains when the vote is not decisive. It
        needs more examples to say anything. Neither replaces the other, and
        keeping both is what lets either be removed without vision losing the
        ability to name what it sees.

        Trained over OBSERVED features only, the same restriction naming and
        induction carry: a classifier fitted on what the substrate concluded
        would be learning from its own output.

        `members` maps category → instance ids. `others` are instances that
        belong to none of them, and become an explicit REJECTION class — without
        one a vote always has a winner, so every blob ever seen would be named
        something. A refusal has to be a class the machine can argue FOR.

        Returns what was learned: the vocabulary, the classes, training accuracy,
        and the clauses themselves, because a recognition that cannot say why is
        not worth having."""
        import numpy as np
        from core.learning.tsetlin_gpu import BatchTsetlinMachine
        from core.reasoning.concept_graph_reasoning import observed_instance_features
        from core.database import get_database_manager

        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        labels = [str(c) for c in members]
        if len(labels) < 2 and not others:
            raise ValueError(
                f"a clause classifier votes BETWEEN classes; {len(labels)} class "
                f"and no rejection examples leaves nothing to vote on")

        rows: List[Tuple[int, List[str]]] = []
        per_class: Dict[str, int] = {}
        for index, category in enumerate(labels):
            for subject in members[category]:
                feats, _ev = await observed_instance_features(db, str(subject))
                if not feats:
                    raise ValueError(
                        f"{subject!r} has no observed features to learn from — "
                        f"it was never seen, or everything it holds was concluded")
                rows.append((index, feats))
                per_class[category] = per_class.get(category, 0) + 1
        reject_index = len(labels)
        for subject in others:
            feats, _ev = await observed_instance_features(db, str(subject))
            if feats:
                rows.append((reject_index, feats))
                per_class[reject_label] = per_class.get(reject_label, 0) + 1
        if others:
            labels = labels + [reject_label]

        vocabulary = sorted({f for _c, feats in rows for f in feats})
        if not vocabulary:
            raise ValueError("no observed features across any example")
        encoder = FeatureEncoder(tuple(vocabulary))
        X = np.stack([encoder(feats) for _c, feats in rows]).astype(np.int8)
        y = np.asarray([c for c, _f in rows], dtype=np.int64)

        model = BatchTsetlinMachine(len(labels), len(vocabulary), config=config)
        model.fit(X, y, epochs=int(epochs))
        predicted = model.predict(X)
        accuracy = float((predicted == y).mean())

        self.register_clause_classifier(
            name, model, labels, encode=encoder, vocabulary=vocabulary,
            reject_label=reject_label if others else None)
        clauses = {
            labels[c]: [" & ".join(lits) for lits in (
                model.clause_literals(c, j, vocabulary) for j in range(0, model.m, 2))
                if lits][:6]
            for c in range(len(labels))}
        logger.info("🧠 clause classifier %r trained: %d class(es), %d feature(s), "
                    "%d example(s), training accuracy %.3f",
                    name, len(labels), len(vocabulary), len(rows), accuracy)
        return {"name": name, "classes": labels, "vocabulary": vocabulary,
                "examples": len(rows), "per_class": per_class,
                "training_accuracy": round(accuracy, 4), "domain": domain,
                "clauses": clauses, "reject_label": reject_label if others else None}

    def register_clause_classifier(self, name: str, model: Any, labels,
                                   *, encode: Any = None,
                                   vocabulary: Optional[Sequence[str]] = None,
                                   reject_label: Optional[str] = None) -> None:
        """Own a trained clause classifier (a Tsetlin Machine) on the ONE
        authority. `labels` maps class index → category name; `encode` turns a raw
        input into the model's boolean feature array (None if the caller passes
        already-encoded features). The model is a MECHANISM and learns nothing by
        being registered — it is a recognizer whose findings become knowledge only
        through `name_instance`, whose naming memory takes in. No classifier
        reaches the ingress / beliefs / domain itself.

        `vocabulary` is the feature order the boolean array is in. Held because a
        model without it is unreadable AND unusable after a restart: the encoder
        is a live object that does not survive `torch.save`, so a reloaded
        classifier came back with `encode=None` and was then handed whatever its
        route passes — a file path, for a vision route — and asked to treat it as
        features. Persisting the vocabulary is what lets the encoder be rebuilt
        instead of silently lost.

        `reject_label` names the class that means NONE OF THESE. A vote always
        has a winner, so without a class the machine can argue FOR when nothing
        fits, every instance it ever sees gets named something. When that class
        wins, `recognize` returns None — the machine declining, not failing."""
        self._clause_classifiers[name] = {
            "model": model, "labels": list(labels), "encode": encode,
            "vocabulary": list(vocabulary) if vocabulary else None,
            "reject_label": str(reject_label) if reject_label else None,
            # Newly trained here: `save_classifiers` writes it, and the stamp is
            # what lets the newest training win across instances.
            "registered_at": datetime.now(timezone.utc), "saved": False}
        self.register_contributor(f"clause_classifier:{name}", "perception")

    def clause_classifier_vocabulary(self, name: str) -> Optional[List[str]]:
        """The feature order a registered classifier reads, or None if it was
        registered without one (a pixel-level model, or a caller that encodes
        for itself)."""
        entry = self._clause_classifiers.get(name) or {}
        vocab = entry.get("vocabulary")
        return list(vocab) if vocab else None

    def has_clause_classifier(self, name: str) -> bool:
        """Whether a clause classifier is registered under `name` — the public
        predicate a perception route checks before attaching it (so nothing reaches
        into the private registry)."""
        return name in self._clause_classifiers

    #: A TRAINED CLASSIFIER IS LEARNED STATE, SO IT LIVES IN THE STORE. It was a
    #: `.pt` file per classifier under the repo's data/: a wipe of the store left
    #: it behind, an instance of the model run from another checkout never saw it,
    #: and every instance re-saved its own copy at each consolidation. One row
    #: per classifier; the mechanism as `torch.save` bytes, the labels and
    #: vocabulary as columns anything can read.
    _CLASSIFIERS_DDL = """
    CREATE TABLE IF NOT EXISTS unified.clause_classifiers (
        name           TEXT PRIMARY KEY,
        mechanism      BYTEA NOT NULL,
        labels         JSONB NOT NULL,
        vocabulary     JSONB,
        reject_label   TEXT,
        registered_at  TIMESTAMPTZ NOT NULL,
        saved_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )"""

    async def _classifier_store(self):
        from core.database import get_database_manager
        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()
        if not getattr(self, "_classifier_schema_ready", False):
            await db.execute_query(self._CLASSIFIERS_DDL, (), commit=True)
            self._classifier_schema_ready = True
        return db

    async def save_classifiers(self) -> int:
        """Persist every clause classifier registered in THIS process since it was
        last saved -- its MECHANISM (TA state, weights, polarity, shape, via
        `torch.save` of the model object) with its labels and vocabulary -- so a
        trained recognizer survives process death. Returns the count written.

        The VOCABULARY is persisted with it, and that is what makes the restored
        classifier usable rather than merely present. The encoder itself is a live
        object; saving it would pickle a class reference and break on any rename.
        Saving the feature order instead lets `load_classifiers` rebuild an
        equivalent encoder.

        A classifier this process only LOADED is not written back, and a write
        never replaces a classifier registered later elsewhere: with many
        instances of the model, the newest training wins, not the last process
        to consolidate."""
        import io
        import torch
        from core.agents.memory_agent import memory_agent
        await self._classifier_store()
        saved = 0
        for name, entry in self._clause_classifiers.items():
            if entry.get("saved"):
                continue
            buffer = io.BytesIO()
            torch.save(entry["model"], buffer)
            await memory_agent().hold_clause_classifier(
                name=name, mechanism=buffer.getvalue(),
                labels=json.dumps(list(entry["labels"])),
                vocabulary=(json.dumps(entry.get("vocabulary"))
                            if entry.get("vocabulary") else None),
                reject_label=entry.get("reject_label"),
                registered_at=entry["registered_at"])
            entry["saved"] = True
            saved += 1
        return saved

    async def load_classifiers(self) -> int:
        """Restore the stored clause classifiers (see save_classifiers). Tensors
        are mapped back onto the working device, and the ENCODER is rebuilt from
        the persisted vocabulary -- so a symbolic-feature classifier comes back
        able to read an instance, not just able to exist. One stored without a
        vocabulary comes back with `encode=None`: it expects pre-encoded
        features, which is said out loud here rather than discovered when it
        mis-reads its first input."""
        import io
        import torch
        from core.learning.tsetlin_gpu import pick_device
        db = await self._classifier_store()
        rows = await db.execute_query(
            "SELECT name, mechanism, labels, vocabulary, reject_label, registered_at "
            "FROM unified.clause_classifiers", (), fetch_all=True) or []
        dev = pick_device("mps")
        restored = 0
        for row in rows:
            name = str(row["name"])
            m = torch.load(io.BytesIO(bytes(row["mechanism"])), map_location=str(dev),
                           weights_only=False)
            # re-home the state tensors on the working device
            for attr in ("ta", "w", "pol", "_pos"):
                if hasattr(m, attr):
                    setattr(m, attr, getattr(m, attr).to(dev))
            if hasattr(m, "dev"):
                m.dev = dev
            labels = row["labels"] if isinstance(row["labels"], list) else json.loads(row["labels"])
            vocab = row["vocabulary"]
            if isinstance(vocab, str):
                vocab = json.loads(vocab)
            self._clause_classifiers[name] = {
                "model": m, "labels": list(labels),
                "encode": FeatureEncoder(vocab) if vocab else None,
                "vocabulary": list(vocab) if vocab else None,
                "reject_label": row["reject_label"],
                "registered_at": row["registered_at"], "saved": True}
            if not vocab:
                logger.warning(
                    "clause classifier %r restored WITHOUT a vocabulary — it "
                    "can only be given pre-encoded features; a route that "
                    "hands it raw input will mis-read it", name)
            restored += 1
        return restored

    async def name_instance(self, name: str, instance: Any, instance_id: str, *,
                            threshold: float = 0.0,
                            lineage: Optional[Sequence[str]] = None) -> Optional["Naming"]:
        """What the named clause classifier calls `instance`, and the evidence for it: a reading of what was
        learned, writing nothing. The model predicts a class and a margin-based confidence in (0,1), carried as the
        evidence's quality, so the classifier never decides what sticks: memory takes the naming in
        (`MemoryAgent.take_in_recognised`). Returns None when no such classifier is registered, the confidence is
        below `threshold`, or the machine declined.

        `lineage` is the observation the instance's features rest on, when the caller holds it: a person's seeing is
        not in the shared graph to be read back."""
        entry = self._clause_classifiers.get(name)
        if entry is None:
            logger.warning("name_instance: no clause classifier %r registered", name)
            return None
        import numpy as np
        import torch
        model, labels, encode = entry["model"], entry["labels"], entry["encode"]
        x = np.asarray(encode(instance) if encode else instance)
        # add the batch axis if a single example was passed (image: H,W,B -> 1,H,W,B;
        # flat features: F -> 1,F).
        single_ndim = 3 if getattr(model, "H", None) else 1
        if x.ndim == single_ndim:
            x = x[None, ...]
        s = model.scores(x)[0].to(torch.float32)          # (C,)
        cls = int(s.argmax())
        top2 = torch.topk(s, k=min(2, s.numel())).values
        margin = float(top2[0] - (top2[1] if top2.numel() > 1 else 0.0))
        denom = float(s.abs().max()) or 1.0
        confidence = max(0.0, min(1.0, 0.5 + 0.5 * margin / denom))
        if confidence < threshold or cls >= len(labels):
            return None
        # THE MACHINE DECLINING IS AN ANSWER. A vote always has a winner, so the
        # rejection class is how "none of these" gets to win; naming an instance
        # after it would turn an abstention into a claim.
        if entry.get("reject_label") and str(labels[cls]) == entry["reject_label"]:
            logger.info("name_instance: %r declined to name %s — the rejection class "
                        "won at %.3f", name, instance_id, confidence)
            return None
        from core.semantics.cognitive_ingress import Provenance

        # WHAT KIND OF CLAIM A CLASSIFIER MAKES depends on what it read.
        #
        # A model reading PIXELS is making an observation: there is no earlier
        # claim between the sensor and its answer, so it introduces root evidence
        # like any other sensor. A model reading the substrate's own SYMBOLIC
        # features is drawing a conclusion FROM claims already held — the same
        # act an induced rule performs, at a different scale — and entering that
        # as a fresh observation would let it corroborate the features it was
        # read from, and let `observed_instance_features` hand its own output
        # back to it as a premise. The vocabulary is the discriminator, and it is
        # present exactly when the classifier reads symbols.
        vocabulary = entry.get("vocabulary")
        if vocabulary:
            if lineage is None:
                from core.reasoning.concept_graph_reasoning import (
                    observed_instance_features)
                from core.database import get_database_manager
                db = get_database_manager()
                if not getattr(db, "initialized", False):
                    await db.initialize()
                feats, lineage = await observed_instance_features(db, str(instance_id))
            else:
                feats = list(instance) if isinstance(instance, (list, tuple)) else []
            if not lineage:
                logger.warning(
                    "name_instance: %r would name %s a %s, but %s carries no observed "
                    "evidence — a conclusion with no lineage is not admitted",
                    name, instance_id, labels[cls], instance_id)
                return None
            blind = encode.unknown(feats) if isinstance(encode, FeatureEncoder) else ()
            if blind:
                logger.info(
                    "name_instance: %r read %s with %d feature(s) it never trained on "
                    "(%s) — the vote is over what it CAN see",
                    name, instance_id, len(blind), ", ".join(blind))
            evidence = Evidence(source=f"classifier:{name}", key=f"classifier:{name}",
                                source_type="INDUCED_RULE", quality=confidence,
                                producer=f"clause_classifier:{name}", derived_from=tuple(lineage))
        else:
            evidence = Evidence(source=f"classifier:{name}", key=f"classifier:{name}",
                                source_type="PERCEPTION", quality=confidence,
                                producer=f"clause_classifier:{name}")
        return Naming(str(instance_id), str(labels[cls]), evidence)

    def induce(self, examples, target_predicate: Optional[str] = None, cases: bool = False):
        """Learn a rule from demonstrations. The world is the only teacher here."""
        return self.inducer.induce(examples, target_predicate=target_predicate, cases=cases)

    async def induce_on_thread(self, examples, target_predicate: Optional[str] = None,
                               cases: bool = False):
        """`induce` on a worker thread, for the coroutines that learn.

        Induction is CPU work with no await in it. On the event loop, one long
        induction froze every other coroutine in the process: measured 2026-10-27
        (RULE-AUTHORITY-02), a world whose demonstrations related one thing to
        several others held the loop for minutes, and every other worker's
        database query timed out waiting behind it."""
        return await asyncio.to_thread(self.induce, examples, target_predicate, cases)

    async def induce_bounded(self, examples, contrastive=(), frame=lambda basis: basis,
                             cases: bool = False):
        """Induce from a bounded basis (`_bounded_basis`) that leaves out no miss
        what was induced applies to. Returns the result and the framed basis.

        A MISS THE BASIS LEFT OUT STILL REFUTES. The basis keeps the first eight
        misses, and the one that tells a needed condition apart can come later:
        RULE-AUTHORITY-02 world 117's first refusal lacking only LUGORSU(z, x)
        was its ninth, so the rule without it was induced from the eight;
        `rejudge` refuted it on everything, and the next induction, from the
        same eight, recorded it again with authority. Every miss what was
        induced applies to joins the basis, and induction runs again until none
        is left out; each round adds one at least, so it ends."""
        from core.learning.rule_induction import judged_by
        chosen = _bounded_basis(examples, contrastive)
        while True:
            result = await self.induce_on_thread(frame(chosen), cases=cases)
            kept = {id(e) for e in chosen}
            missed = [e for e in examples if not e.positive and id(e) not in kept
                      and any(judged_by(c, e) is False for c in result.candidates)]
            if not missed:
                return result, frame(chosen)
            chosen = chosen + missed

    async def record(self, result, examples, *, domain_id: str,
                     rule_kind: str = "state_transition"):
        """Persist what induction produced, against the demonstrations that
        produced it (keyed on the demonstrations, not a bare list of ids)."""
        return await self.store.record_induction(
            result, examples, domain_id=domain_id, rule_kind=rule_kind)

    async def induce_category(self, category: str, positives, negatives=(), *,
                              domain: str = "perception"):
        """Learn a rule that NAMES `category`, from labeled example instances.

        Each example is a subject whose atomic feature facts already live in the
        concept graph -- taught, or perceived through the vision faculty and
        admitted as `blobN isa red`, `blobN isa circular`. A positive IS a
        `category`; a negative is not, and refutes an overgeneral rule.
        Anti-unification over the positives' features yields a rule such as
        red(?X) & circular(?X) -> category(?X); it is persisted (CANDIDATE) in the
        one induced-rule authority, where the reasoner applies it to name new
        instances. Returns the InductionResult (`.rule` when one was learned).

        Raises with fewer than two positives (one case cannot be generalized) or
        when an example carries no feature facts to generalize from -- refusing,
        never inventing a rule from nothing."""
        from core.learning.rule_induction import (
            Fact, TrainingExample, predicate_name)
        from core.reasoning.concept_graph_reasoning import observed_instance_features
        from core.database import get_database_manager

        head = predicate_name(category)
        if not head:
            raise ValueError(f"category {category!r} is not a usable predicate name")
        positives = list(positives)
        if len(positives) < 2:
            raise ValueError(
                f"category induction needs >= 2 positive examples; got "
                f"{len(positives)}: one example is a case, not a generalization")

        db = get_database_manager()
        if not getattr(db, "initialized", False):
            await db.initialize()

        async def _example(subject: str, is_positive: bool):
            # INDUCTION GENERALISES OVER WHAT WAS OBSERVED, not over what was
            # concluded. Once naming became a reflex (`recognise_sensed`), every
            # blob the substrate recognises carries the names it was given as
            # ordinary `isa` edges, and reading those back as features would let
            # a rule be induced whose premise is another rule's conclusion --
            # `circle & vivid_red & stopsign -> newcat`, resting on a `stopsign`
            # nothing ever saw. Measured: with the reflex live and all edges
            # read, induction over the same stimuli stopped producing a rule at
            # all, because the shared derived names swamped the real features.
            #
            # So the premises come from root-sourced evidence only. A feature the
            # substrate was TAUGHT is USER_SUPPLIED and still counts; only a
            # conclusion it drew is excluded. The cost is real and stated: a
            # category cannot be induced from a premise that is itself derived,
            # which is a relation between CATEGORIES and belongs in the taxonomy,
            # not in instance-level induction.
            #
            # The category being learned is the LABEL, never a feature. A positive
            # named by an earlier induction (the naming fan-out below writes
            # `subject isa category`) would otherwise carry the head in its own
            # `before`, so labelling it "adds" nothing and induction finds no
            # effect to explain -- every re-teach of a category failed that way.
            observed, _evidence = await observed_instance_features(db, subject)
            feats = [p for p in (predicate_name(f) for f in observed)
                     if p and p != head]
            before = tuple(sorted({Fact(p, (subject,)) for p in feats}))
            if not before:
                return None
            after = before + ((Fact(head, (subject,)),) if is_positive else ())
            return TrainingExample(before=before, after=after, positive=is_positive,
                                   evidence_id=f"cat_{head}_{subject}")

        examples = []
        for subject in positives:
            ex = await _example(subject, True)
            if ex is None:
                raise ValueError(
                    f"example {subject!r} has no feature facts to generalize from")
            examples.append(ex)
        for subject in negatives:
            ex = await _example(subject, False)
            if ex is not None:
                examples.append(ex)

        result = await self.induce_on_thread(examples, target_predicate=head)
        # EVERY SURVIVING HYPOTHESIS IS KEPT, and that is deliberate: the store
        # holds a version space for a later demonstration to collapse. What used
        # to go wrong was downstream -- naming fired on the FIRST hypothesis that
        # matched, so an undetermined category still produced confident names
        # (two `small` positives against `medium` negatives yielded
        # `small(?X) -> greentriangle(?X)` beside the conjunction, and a small
        # violet circle was named a green triangle). Ambiguity is resolved where
        # it is answerable: naming requires the hypotheses to AGREE, and an
        # undetermined category reports the demonstration that would decide it.
        if result.candidates:
            await self.record(result, examples, domain_id=domain,
                              rule_kind="classification")
            # The induction's CONCLUSION goes through the one gate, not only into
            # the rule store: each positive IS the category, so `subject isa
            # category` is considered (`consider`) -- the ingress resolves identity,
            # the belief layer moves a posterior, the domain crystallizes. Without
            # this the named category exists only as a CANDIDATE rule the
            # belief/domain stores never see.
            # The positives were SUPPLIED as labeled members of the category, so
            # the per-instance naming is supplied ground truth, not a self-derived
            # root that would corroborate itself; the induction is one source.
            evidence = Evidence(source=f"induction:{head}", key=f"induction:{head}",
                                source_type="USER_SUPPLIED", quality=0.9)
            for subject in positives:
                try:
                    decision = await self.consider(str(subject), "isa", str(category),
                                                   domain=domain, evidence=evidence)
                except Exception as error:
                    raise_if_structural(error, "unified_learning_system.induce_category")
                    logger.warning("induce_category could not name %r a %s: %s",
                                   subject, category, error)
                    continue
                if not decision.admitted:
                    logger.info("induce_category: %r isa %s not held: %s", subject, category,
                                "; ".join(decision.reasons) or decision.standing)
        return result

    # ── The one door for TOLD knowledge ──────────────────────────────────────
    #
    # Every KIND of learning is a method on this authority, and each fans out to
    # the SAME systems, so nothing that depends on learning has to reach a second
    # door: a fact and a rule both update REASONING (the concept graph the
    # reasoner chains over), BELIEFS (a posterior), the LEXICON (parts of speech),
    # the DOMAIN (crystallization, via the emitted event), MEMORY (a recallable
    # claim, through the ingress), and METRICS. Callers stop reaching into the
    # ingress / belief system / lexicon directly and come here.

    @staticmethod
    def _refused_while_frozen(what: str) -> Optional[str]:
        """Where the model is a frozen release (staging, production), the
        substrate's own learning is refused HERE, at the door, before anything
        in the process moves: production answers only from its release, and
        what it would learn waits for development. Counted with the database
        manager's other frozen refusals.
        Returns the reason, or None where the model learns. A person's context
        is not the model: it is never refused here."""
        from core.database import get_database_manager
        db = get_database_manager()
        if not getattr(db, "frozen", False):
            return None
        reason = str(db.frozen_refusal(what))
        logger.info("learning refused: %s", reason)
        return reason

    #: How many new claims about the world one person's word may put in an hour. A flood of tellings from one
    #: source is how a poisoner works (Carlini et al., IEEE S&P 2024); what one person tells beyond this waits.
    PERSON_CLAIMS_PER_HOUR = 120

    async def consider(self, subject: str, relation: str, obj: Optional[str], *, evidence: Evidence,
                       domain: str, positive: bool = True, surface: Optional[str] = None,
                       description: str = "", word_class_of: Any = None, emit: Any = None) -> Decision:
        """THE ONE DOOR INTO WORLD KNOWLEDGE (docs/research/SEPARATION_MAP.md §11.4). Whatever says a claim about
        the world -- a person, a page, Lyric's senses, the outcome of its work, a lesson -- it is judged by whether
        it is true, and nothing else writes the world.

          1. Its shape and its evidence's quality: what the store cannot hold, or what is too weakly supported, is
             refused.
          2. A person's word beyond `PERSON_CLAIMS_PER_HOUR` in the hour waits.
          3. What is held against it (`_held_against`): the same claim held the other way, or, for a kind, a
             denial it inherits. It is counted either way, and held only once its independent witnesses outweigh
             the ones holding the other side (`witness_weight`): until then it is refused where that side is
             settled and doubted where it is not. Many sources take many to overturn; a flood of one source's
             word is one witness.
          4. Held: written to the world through the one admission (`_admit_to_world`), the belief moved by this
             evidence once (`evidence.key`), and its standing read from the belief."""
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY, shape_proposition
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        claim = " ".join(str(p) for p in (subject, relation, obj) if p)
        surface = surface or claim
        frozen = self._refused_while_frozen(f"consider {claim}")
        if frozen:
            return Decision(claim, positive, "refused", [frozen])
        subject_term, relation_term, obj_term, refusal = shape_proposition(subject, relation, obj)
        if refusal:
            return Decision(claim, positive, "refused", [refusal])
        # ONE CLAIM, ONE BELIEF, HOWEVER IT WAS SPELLED: named in the store's own terms, so "Flippers" and
        # "flipper", "fire truck" and "fire_truck", told by two sources, are two witnesses of one claim.
        claim = " ".join(str(p) for p in (subject_term, relation_term, obj_term) if p)
        if evidence.quality < MIN_ADMIT_QUALITY:
            return Decision(claim, positive, "refused", [
                f"insufficient support: quality {evidence.quality:.3f} < floor {MIN_ADMIT_QUALITY}"])
        if evidence.source_type == "USER_SUPPLIED" and await self._claims_this_hour(evidence.key) \
                >= self.PERSON_CLAIMS_PER_HOUR:
            return Decision(claim, positive, "refused", [
                f"{self.PERSON_CLAIMS_PER_HOUR} new claims from one person in the hour; this one waits"])
        against = await self._held_against(subject_term, relation_term, obj_term, positive) if obj_term else None
        beliefs = get_uncertainty_system()
        if against:
            said, held_claim, held_holds = against
            held = beliefs.belief_for_claim(held_claim)
            was_settled = held is not None and self._settled_on(held, positive=held_holds)
            self.observe_claim(claim, domain, supports=positive, quality=evidence.quality,
                               source=evidence.source, observation=evidence.key)
            if not self._outweighs(claim, positive, held_claim, held_holds):
                side = self._side(beliefs.belief_for_claim(claim), positive=positive)
                if was_settled:
                    return Decision(claim, positive, "refused", [f"contradicts what is settled: {said}"],
                                    posterior=side)
                return Decision(claim, positive, "doubted", [f"held otherwise ({said}); counted against it"],
                                posterior=side)
        admission = await self._admit_to_world(
            subject, relation, obj, positive=positive, surface=surface, domain=domain, description=description,
            word_class_of=word_class_of, emit=emit, quality=evidence.quality,
            provenance=self._provenance(evidence), terms=(subject_term, relation_term, obj_term))
        if not admission.admitted and not getattr(admission, "already_present", False):
            return Decision(claim, positive, "refused", list(admission.refusals) or ["the store did not take it"],
                            admission=admission)
        belief = beliefs.belief_for_claim(claim)
        return Decision(claim, positive, "settled" if self._settled_on(belief, positive=positive) else "candidate",
                        admission=admission, posterior=self._side(belief, positive=positive))

    @staticmethod
    def _provenance(evidence: Evidence) -> Any:
        from core.semantics.cognitive_ingress import Provenance
        return Provenance(producer=evidence.producer, source_id=evidence.key, source_type=evidence.source_type,
                          derived_from=tuple(evidence.derived_from))

    @staticmethod
    def _side(belief: Any, *, positive: bool) -> Optional[float]:
        """How likely the claim is on the side asked: the belief's posterior, or one minus it for a denial."""
        if belief is None:
            return None
        posterior = float(getattr(belief, "posterior_probability", 0.5))
        return posterior if positive else 1.0 - posterior

    #: SETTLED NEEDS CORROBORATION. One witness at a telling's quality already carries a new belief past the belief
    #: system's own bar, so a claim is settled only when that bar is passed on its side AND this many independent
    #: witnesses' latest word is on it: one source, however sure, makes a candidate
    #: (docs/research/SEPARATION_MAP.md §11.4, §11.9 1).
    SETTLED_WITNESSES = 2

    def _settled_on(self, belief: Any, *, positive: bool) -> bool:
        """Whether a belief is settled on the side asked: past the belief system's own bar for settled
        (`capabilities.settled_in_favour`), with `SETTLED_WITNESSES` independent witnesses on that side."""
        from core.capabilities import settled_in_favour
        from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem
        if belief is None or not settled_in_favour(self._side(belief, positive=positive)):
            return False
        return BayesianUncertaintySystem.witnesses(belief, supports=positive) >= self.SETTLED_WITNESSES

    @staticmethod
    def _outweighs(claim: str, positive: bool, held_claim: str, held_holds: bool) -> bool:
        """Whether a claim's independent witnesses now outweigh the ones holding what is held against it
        (`BayesianUncertaintySystem.witness_weight`): each witness once, by its latest word, its quality its
        weight. Every source weighs the same until the sources' own records are kept (§11.9, 3)."""
        from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem, get_uncertainty_system
        beliefs = get_uncertainty_system()
        mine, held = beliefs.belief_for_claim(claim), beliefs.belief_for_claim(held_claim)
        weight = 0.0 if mine is None else BayesianUncertaintySystem.witness_weight(mine, supports=positive)
        against = 0.0 if held is None else BayesianUncertaintySystem.witness_weight(held, supports=held_holds)
        return weight > against

    async def _held_against(self, subject: str, relation: str, obj: str,
                            positive: bool) -> Optional[Tuple[str, str, bool]]:
        """What the world holds against a claim: `(said, the claim it is held in, whether that claim holding is
        what is against it)`, or None when nothing is. The same claim held the other way; and, for a kind or a
        thing's kind asserted, a denial the graph's reasoner finds it inheriting ("no mammal is a bird", against "a
        dog is a bird"), held in the denial's own claim. Kinds nothing held is both of are no denial
        (`disjoint`): being told something is both is how memory learns it is."""
        from core.database import get_database_manager
        db = get_database_manager()
        claim = f"{subject} {relation} {obj}"
        rows = await db.execute_query(
            "SELECT r.polarity FROM unified.concept_relations r "
            "JOIN unified.concepts c ON c.concept_id = r.source_concept_id "
            "WHERE c.name = $1 AND r.relation = $2 AND r.target_surface = $3 "
            "AND COALESCE(r.polarity, 'positive') = $4 LIMIT 1",
            (subject, relation, obj, "negative" if positive else "positive"), fetch_all=True) or []
        if rows:
            return f"{subject} {'not ' if positive else ''}{relation} {obj} is held", claim, not positive
        if positive and relation in ("isa", "instance of"):
            from core.reasoning.concept_graph_reasoning import answer_over_graph, load_denials, load_subgraph
            from core.reasoning.relation_algebra import FALSE, INSTANCE_OF, ISA
            from core.semantics.relation_types import SemanticRelation
            kind = SemanticRelation.ISA if relation == "isa" else SemanticRelation.INSTANCE_OF
            answer = await answer_over_graph(db, subject, kind, obj)
            if getattr(answer, "verdict", None) == FALSE and getattr(answer, "basis", "") != "disjoint":
                # WHICH HELD DENIAL: the one on the subject or a kind it is, by the reasoner's own rule (`answer`).
                edges = await load_subgraph(db, [subject])
                kinds = {subject} | {e.obj for e in edges if e.relation in (ISA, INSTANCE_OF)}
                denier = next((n.subject for n in await load_denials(db, sorted(kinds))
                               if n.relation is kind and n.obj == obj and n.subject in kinds), subject)
                return (f"the world holds {subject} is no {obj} ({getattr(answer, 'basis', '')})",
                        f"{denier} {relation} {obj}", False)
        return None

    async def _claims_this_hour(self, key: str) -> int:
        """The claims one source's word put in the world in the last hour, as the knowledge ledger recorded them
        (`_record_knowledge_update`: its actor is the evidence's key). A claim is put in whether its terms were new
        (`new`) or already held (`updated`): a flood in words the world knows is a flood. What the source had
        already said (`unchanged`) and what was refused put nothing in."""
        from core.database import get_database_manager
        from datetime import timedelta
        from core.memory import knowledge_ledger
        return await knowledge_ledger.claims_put_in(get_database_manager(), str(key), within=timedelta(hours=1))

    async def _admit_to_world(self, subject: str, relation: str, obj: Optional[str], *, positive: bool,
                              surface: str, provenance: Any, domain: str, terms: Tuple[Any, Any, Any],
                              description: str = "", word_class_of: Any = None, emit: Any = None,
                              quality: float = 0.9) -> Any:
        """The one admission into the world, for `consider` alone: the concept graph the reasoner walks, through
        the ingress, then the fan-out of the learning to beliefs, the lexicon, the domain, memory and metrics.
        `terms` are the claim in the store's own terms, which its belief is named by.
        Returns the ingress `Admission`."""
        from core.semantics.cognitive_ingress import get_cognitive_ingress
        admission = await get_cognitive_ingress().admit_relation(
            subject=subject, relation=relation, obj=obj, surface=surface,
            provenance=provenance, positive=positive, description=description,
            domain=domain, word_class_of=word_class_of, quality=quality)
        if admission.admitted:
            await self._fan_out_learning(
                surface=surface, claim=" ".join(str(p) for p in terms if p),
                # The memory the ingress just wrote for this fact — the thing
                # the belief will be ABOUT.
                clauses=[(*terms, getattr(admission, "memory_id", None))],
                positive=positive, domain=domain, quality=quality,
                # The evidence's independence key: the same source saying the same
                # thing again is one witness, however often and wherever it says it.
                observation=getattr(provenance, "source_id", None),
                emit=emit, emit_payload={"subject": subject, "relation": relation,
                                         "obj": obj, "domain": domain})
        await self._record_knowledge_update(admission, domain=domain,
                                            provenance=provenance)
        return admission

    @staticmethod
    def _ledger_disposition(admission: Any) -> Tuple[Any, str]:
        """What one admission did, for the knowledge ledger: ONE rule, used by the
        single-fact and the bulk path alike (they had drifted -- the bulk path
        recorded every admission as NEW, a reinforcement and a re-teach included).

        ALREADY PRESENT IS CHECKED FIRST, and that ordering is the point. The
        ingress returns a duplicate as `admitted=False` with NO refusal, because
        a sentence read twice is one fact -- so testing `admitted` first recorded
        every re-teach as "refused without a stated reason", which is a false
        negative about the substrate's own dedup working correctly."""
        from core.memory import knowledge_ledger as ledger
        if getattr(admission, "already_present", False):
            disposition = ledger.Disposition.UNCHANGED
            detail = "seen before from this source; not counted twice"
        elif not getattr(admission, "admitted", False):
            disposition = ledger.Disposition.REJECTED
            detail = "; ".join(getattr(admission, "refusals", None) or
                               ["refused without a stated reason"])
        elif getattr(admission, "concepts_created", None):
            disposition = ledger.Disposition.NEW
            detail = (f"+{len(admission.concepts_created)} concept(s), "
                      f"~{len(admission.concepts_reinforced or [])} reinforced")
        else:
            disposition = ledger.Disposition.UPDATED
            detail = (f"~{len(getattr(admission, 'concepts_reinforced', None) or [])}"
                      f" reinforced")
        if getattr(admission, "contradicts", None):
            detail += " CONTRADICTS PRIOR CLAIM"
        return disposition, detail

    async def _record_knowledge_update(self, admission: Any, *, domain: str,
                                       provenance: Any) -> None:
        """Write down WHAT THIS ADMISSION DID, so the store can be asked later.

        `Admission` already carries the disposition -- concepts_created (new),
        concepts_reinforced (updated), refusals (rejected), contradicts -- and
        every caller returned it to be read once and dropped. Nothing durable
        recorded whether a taught claim had been accepted or refused, so a
        refusal left no trace at all: the store could not distinguish "never
        taught" from "taught and declined".

        The provenance is NOT copied here. `evidence_id` points at the envelope
        that already holds the producer, the surface observed and what was
        inferred from it; two accounts of the same thing is the defect this
        avoids, not the feature.
        """
        from core.database import get_database_manager
        from core.memory import knowledge_ledger as ledger
        try:
            db = get_database_manager()
            disposition, detail = self._ledger_disposition(admission)
            await ledger.record(db, ledger.KnowledgeUpdate(
                subject_kind="proposition",
                subject_id=str(getattr(admission, "proposition", "") or "")[:500],
                disposition=disposition, domain=domain,
                evidence_id=getattr(admission, "evidence_id", None) or None,
                detail=detail,
                cause=f"learning.{getattr(provenance, 'producer', 'unknown')}",
                actor=getattr(provenance, "source_id", None)))
        except Exception as error:
            from core.structural_defects import raise_if_structural
            raise_if_structural(
                error, "unified_learning_system._record_knowledge_update")
            logger.debug("knowledge update not recorded: %s", error)

    #: The classes the substrate can hold. OPEN classes are learned from the
    #: sentences it reads; CLOSED classes are finite and are told to it. Both
    #: live in memory as taught knowledge -- there is no lexicon.
    WORD_CLASSES = ("NOUN", "VERB", "ADJECTIVE", "ADVERB", "PRONOUN",
                    "DETERMINER", "PREPOSITION", "CONJUNCTION", "SUBORDINATOR",
                    "AUXILIARY", "MODAL", "NEGATOR", "COPULA", "RELATIVE",
                    "QUANTIFIER", "NUMERAL", "INTERJECTION", "PARTICLE",
                    # Punctuation is part of written language, not scenery: a
                    # full stop is where one claim ends and the next begins, and
                    # a comma is where a clause is set off. The reader acts on
                    # these marks in a dozen places and the substrate could not
                    # say what any of them are.
                    "PUNCTUATION")

    async def learn_word_classes(self, classes, *, provenance: Any = None,
                                 quality: float = 0.9,
                                 progress: Optional[Callable[[int, int], Any]] = None) -> Dict[str, int]:
        """Teach what CLASS a word has, into memory, as knowledge.

        `classes` is an iterable of `(word, CLASS)`.

        THIS IS NOT A LEXICON. It writes the same kind of memory every other
        taught thing writes -- semantic, provenanced, recallable, and taken by a
        wipe like everything else -- and `warm_word_classes` derives the view
        from it. What it replaces is a set of frozensets compiled into the
        reader: a second authority beside memory that no teaching could change,
        no wipe could clear, and no evidence could ever argue with.

        A word class stated here is EVIDENCE, not a decree: it lands as one
        observation, and a reading that fails because of it argues it back down
        exactly as it does for a class derived from a sentence.

        `progress(done, total)`, when given, hears how far it is every thousand
        words: a dictionary's tens of thousands take hours, and a run that says
        nothing for them cannot be watched.

        Returns {told, skipped, total}.
        """
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType, Origin
        from core.learning.teaching_sources import _article

        counts = {"told": 0, "skipped": 0, "total": 0, "already": 0}
        classes = list(classes)
        if self._refused_while_frozen(f"learn_word_classes ({len(classes)})"):
            counts.update(total=len(classes), skipped=len(classes))
            return counts
        agent = await get_memory_agent()
        allowed = set(self.WORD_CLASSES)

        # WHAT IS ALREADY KNOWN, IN ONE QUESTION.
        #
        # Teaching is not an epoch: the same pair arriving twice is one thing
        # the source says, not two witnesses to it, and counting it twice is
        # the double-count defect that left beliefs 0.999999 certain of a
        # single assertion. The identity of a stated class is the PAIR, so it
        # is looked up exactly rather than by resemblance.
        # Read, or the pass stops: with nothing known, every pair taught again
        # would be counted again -- the double count this read exists to stop.
        rows = await agent.stated_word_classes()
        known = {(w, c) for w, c in rows}

        for word, word_class in classes:
            counts["total"] += 1
            if progress is not None and counts["total"] % 1000 == 0:
                progress(counts["total"], len(classes))
            word = str(word or "").strip().lower()
            word_class = str(word_class or "").strip().upper()
            if not word or word_class not in allowed:
                counts["skipped"] += 1
                continue
            if (word, word_class) in known:
                counts["already"] += 1
                continue
            known.add((word, word_class))
            stored, _memory_id = await agent.store_memory(
                origin=Origin.own("teaching"),
                content=f"{word!r} is used as {_article(word_class)} {word_class.lower()}.",
                memory_type=MemoryType.SEMANTIC,
                confidence_score=float(quality),
                tags=["language", agent.WORD_CLASS_TAG],
                source_context={
                    "producer": getattr(provenance, "producer", "learning"),
                    "source_id": getattr(provenance, "source_id", "you"),
                    "word": word,
                    "word_class": word_class,
                },
            )
            if stored:
                agent._word_class_index.setdefault(word, {})
                agent._word_class_index[word][word_class] = (
                    agent._word_class_index[word].get(word_class, 0) + 1)
                counts["told"] += 1
            else:
                counts["skipped"] += 1
        return counts

    async def learn_pronunciations(self, said, *, provenance: Any = None,
                                   quality: float = 0.9) -> Dict[str, int]:
        """Teach how words are said, into memory, as knowledge: `said` is an iterable of `(word, phones, how often
        real text uses the word)`, the phones as a pronouncing dictionary writes them ("D AO1 G").

        The same kind of memory a word class is (`learn_word_classes`): semantic, provenanced, recallable, taken by
        a wipe. The ear hears a word by these sounds (`speech.SaidAs`), whoever says it. A pair told before is not
        told again. Returns {told, already, skipped, total}."""
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType, Origin

        counts = {"told": 0, "already": 0, "skipped": 0, "total": 0}
        said = list(said)
        if self._refused_while_frozen(f"learn_pronunciations ({len(said)})"):
            counts.update(total=len(said), skipped=len(said))
            return counts
        agent = await get_memory_agent()
        known = {(w, p) for w, p, _ in await agent.stated_pronunciations()}
        for word, phones, used in said:
            counts["total"] += 1
            word = str(word or "").strip().lower()
            phones = " ".join(str(phones or "").upper().split())
            if not word or not phones:
                counts["skipped"] += 1
                continue
            if (word, phones) in known:
                counts["already"] += 1
                continue
            known.add((word, phones))
            stored, _memory_id = await agent.store_memory(
                origin=Origin.own("teaching"),
                content=f"{word!r} is said {phones}.",
                memory_type=MemoryType.SEMANTIC,
                confidence_score=float(quality),
                tags=["language", agent.PRONUNCIATION_TAG],
                source_context={
                    "producer": getattr(provenance, "producer", "learning"),
                    "source_id": getattr(provenance, "source_id", "you"),
                    "word": word,
                    "said_as": phones,
                    "used": int(used or 0),
                },
            )
            if stored:
                agent.pronunciations_told = getattr(agent, "pronunciations_told", 0) + 1
                counts["told"] += 1
            else:
                counts["skipped"] += 1
        return counts

    async def learn_patterns(self, pairs, *, provenance: Any = None,
                             quality: float,
                             progress: Optional[Callable[..., None]] = None) -> Dict[str, int]:
        """Learn how English says things, from sentences taught WITH their meaning: the constructions found between
        taught pairs (`derived_reader`), one pair at a time, as the Leuven method learns them.

        `pairs` is an iterable of `(sentence, Meaning)`, in the order they were said, or `(sentence, Meaning, names)`
        where the teacher says how it wrote a concept (`{concept: word}`, WordNet's "electronic computer" for
        `computer`): a run so written is that concept's name, never a frame's word and a filler. Each pair is read first with
        what is held. If a reading gives its meaning, the pair is understood and only the scores move. If not, the
        repairs are tried in the paper's order (`derived_reader.REPAIRS`); the first that can handle the pair says
        what to create, that is stored, and the pair is read again.

        THE SCORES MOVE AFTER EVERY PAIR. The constructions of the best reading, and its links, are observed FOR;
        every other construction that could also have read the pair to its meaning -- a competitor -- is observed
        AGAINST. An observation is identified by the source and the pair, so the same lesson from the same source
        again moves nothing, and each different pair is a use.

        The owners: MEMORY holds each construction and link (one semantic memory each, tagged `PATTERN_TAG`,
        identified by its key); BELIEFS hold their scores, grounded in that memory; THE DOMAIN SYSTEM holds meaning,
        and English is a domain. The facts a meaning states are not admitted here: the teaching pass teaches them
        through `consider_many`.

        Returns counts: `learned` (constructions created), `linked` (links created), `already` (pairs understood
        as they came), `understood` (understood as they came or by adding links only: the paper's communicative
        success), `refused`, `total`, and `repair_<name>` for each repair that ran. `progress(done, total)`, when
        given, hears how far it is every thousand pairs.
        """
        import hashlib
        from core.memory import knowledge_ledger as _ledger
        from core.memory import get_memory_agent
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        from core.semantics.sentence_machine import form_of

        pairs = list(pairs)
        counts = {"learned": 0, "linked": 0, "already": 0, "understood": 0, "refused": 0, "total": 0}
        if self._refused_while_frozen(f"learn_patterns ({len(pairs)})"):
            counts.update(refused=len(pairs), total=len(pairs))
            return counts
        if quality < MIN_ADMIT_QUALITY:
            logger.info("patterns REFUSED for %d pair(s): evidence quality %.3f < floor %.2f",
                        len(pairs), quality, MIN_ADMIT_QUALITY)
            counts.update(refused=len(pairs), total=len(pairs))
            return counts
        agent = await get_memory_agent()
        view = await agent.language_view()
        held = await agent.stated_patterns()
        producer = getattr(provenance, "producer", "learning")
        source_id = getattr(provenance, "source_id", None) or "you"
        cause = f"learning.patterns.{producer}"
        us = get_uncertainty_system()
        updates: List[Any] = []
        said: List[Tuple[str, str, str, str, int, str, str]] = []
        heard: List[Tuple[str, ...]] = []
        created_any = False

        def subject_kind(item) -> str:
            return "language_link" if isinstance(item, dr.Link) else "language_pattern"

        def observe(item, supports: bool, observation: str):
            """One observation of a construction or link; whether it moved the belief is read from the belief."""
            before = us.belief_for_claim(item.claim())
            seen = (len(before.evidence_for) + len(before.evidence_against)) if before is not None else 0
            after = us.observe_claim(item.claim(), dr.ENGLISH_DOMAIN, supports=supports, quality=quality,
                                     source="taught", observation=observation, memory_id=held.get(item.key))
            return after is not None and len(after.evidence_for) + len(after.evidence_against) > seen

        batch = _ledger.begin_batch(cause)
        try:
            # A SENTENCE WITH A QUOTATION IS TWO PAIRS TO LEARN (`dr.quoted_pairs`): the sentence around it, and the
            # quoted sentence. It is still one sentence taught: counted once, and refused if either part is.
            parts = [(index, part) for index, pair in enumerate(pairs)
                     for part in (dr.quoted_pairs(*pair) if len(pair) > 1 and isinstance(pair[1], dr.Meaning)
                                  else [pair])]
            counted: set = set()
            refused_at: set = set()
            # EACH SENTENCE IS READ ON THE SUBSTRATE'S LOOP, and a sentence a known pattern reads awaits nothing:
            # WordNet's 133,748 said sentences would hold it for the whole pass (`GiveWay`).
            give_way = GiveWay()
            for index, (sentence, meaning, *written) in parts:
                await give_way()
                names = written[0] if written else {}
                if index not in counted:
                    counted.add(index)
                    counts["total"] += 1
                    if progress is not None and counts["total"] % 1000 == 0:
                        progress(counts["total"], len(pairs))
                try:
                    if not isinstance(meaning, dr.Meaning):
                        raise TypeError("a taught meaning is a derived_reader.Meaning")
                    form = form_of(sentence)
                    if not form:
                        raise ValueError("an empty sentence says nothing")
                except (TypeError, ValueError) as refusal:
                    refused_at.add(index)
                    updates.append(_ledger.KnowledgeUpdate(
                        subject_kind="language_pattern", subject_id=str(sentence)[:500],
                        disposition=_ledger.Disposition.REJECTED, domain=dr.ENGLISH_DOMAIN,
                        detail=str(refusal), cause=cause))
                    continue
                words = tuple(p.text for p in form)
                pair = hashlib.sha256(f"{sentence}\x1e{meaning.canonical()}".encode("utf-8")).hexdigest()[:16]
                observation = f"{source_id}:{pair}"
                readings = dr.readings_of(words, meaning, view)
                repair = None
                created = set()
                if not readings:
                    for step in dr.REPAIRS:
                        repair = step(form, meaning, view, names=names)
                        if repair is not None:
                            break
                    counts[f"repair_{repair.name}"] = counts.get(f"repair_{repair.name}", 0) + 1
                    stored_all = True
                    for item in repair.constructions + repair.links:
                        memory_id = await self._store_language_item(agent, item, producer, source_id, quality)
                        if not memory_id:
                            stored_all = False
                            updates.append(_ledger.KnowledgeUpdate(
                                subject_kind=subject_kind(item), subject_id=item.key,
                                disposition=_ledger.Disposition.REJECTED, domain=dr.ENGLISH_DOMAIN,
                                detail="memory did not store it", cause=cause))
                            continue
                        held[item.key] = memory_id
                        agent.note_pattern(item)
                        created.add(item.key)
                        created_any = True
                        counts["linked" if isinstance(item, dr.Link) else "learned"] += 1
                        # Its belief starts with the pair that made it.
                        observe(item, True, observation)
                        updates.append(_ledger.KnowledgeUpdate(
                            subject_kind=subject_kind(item), subject_id=item.key,
                            disposition=_ledger.Disposition.NEW, domain=dr.ENGLISH_DOMAIN,
                            detail=f"{dr.REPAIR_NAMES[repair.name]}: "
                                   f"{getattr(item, 'surface', None) or item.claim()}"[:500],
                            cause=cause))
                    for item in repair.revived:
                        observe(item, True, observation)
                        created.add(item.key)
                        updates.append(_ledger.KnowledgeUpdate(
                            subject_kind=subject_kind(item), subject_id=item.key,
                            disposition=_ledger.Disposition.UPDATED, domain=dr.ENGLISH_DOMAIN,
                            detail=f"revived: no longer believed, supported again by {sentence!r}",
                            cause=cause))
                    if not stored_all:
                        refused_at.add(index)
                        continue
                    readings = dr.readings_of(words, meaning, view)
                if not readings:
                    refused_at.add(index)
                    updates.append(_ledger.KnowledgeUpdate(
                        subject_kind="language_pattern", subject_id=pair,
                        disposition=_ledger.Disposition.REJECTED, domain=dr.ENGLISH_DOMAIN,
                        detail=f"{sentence!r} does not read after {repair.name if repair else 'no repair'}",
                        cause=cause))
                    continue
                if repair is None:
                    counts["already"] += 1
                if repair is None or repair.name == "add_links":
                    counts["understood"] += 1
                chosen = readings[0]
                # WHAT WAS HEARD AFTER WHAT: each word of the sentence learned, right after the one before it.
                heard.append(words)
                # WHAT EACH WORD WAS SAID OF, the thing itself, as the meaning was given: "The table is red." says red
                # of the table that is furniture. That a thing is a kind of another is held, not said of it.
                for fact in dr.listening_facts(meaning):
                    if fact.relation not in ("isa", "instance_of"):
                        said.append((fact.relation, fact.obj, "object", fact.subject, 1, observation, "thing"))
                        said.append((fact.relation, fact.subject, "subject", fact.obj, 1, observation, "thing"))
                used = {item.key for item in chosen.constructions + chosen.links}
                for item in chosen.constructions + chosen.links:
                    if item.key in created:
                        continue
                    moved = observe(item, True, observation)
                    updates.append(_ledger.KnowledgeUpdate(
                        subject_kind=subject_kind(item), subject_id=item.key,
                        disposition=(_ledger.Disposition.UPDATED if moved else _ledger.Disposition.UNCHANGED),
                        domain=dr.ENGLISH_DOMAIN,
                        detail=(f"read {sentence!r}; {source_id} observed it" if moved else
                                "held already from this source; not counted twice"),
                        cause=cause))
                competitors = {c.key: c for r in readings[1:] for c in r.constructions if c.key not in used}
                for item in competitors.values():
                    if observe(item, False, observation):
                        updates.append(_ledger.KnowledgeUpdate(
                            subject_kind=subject_kind(item), subject_id=item.key,
                            disposition=_ledger.Disposition.UPDATED, domain=dr.ENGLISH_DOMAIN,
                            detail=f"a competitor: another reading of {sentence!r} was chosen", cause=cause))
            counts["refused"] += len(refused_at)
            # What was gathered is written after the sentences, one memory a word, and is told as its own phase.
            def stage(phase: str):
                return None if progress is None else (lambda done, of: progress(done, of, phase))
            if said:
                counts["said"] = (await agent.remember_said(
                    said, progress=stage("remembering what words are said of")))["remembered"]
            if heard:
                counts["heard"] = (await agent.remember_heard(
                    heard, progress=stage("remembering what was heard after")))["heard"]
            if created_any:
                # English is a domain: ensured, and the running substrate told what was learned.
                await self._fan_out_learning(
                    surface="taught constructions", claim="", clauses=[], positive=True,
                    domain=dr.ENGLISH_DOMAIN, emit=None,
                    emit_payload={"kind": "language_patterns", "domain": dr.ENGLISH_DOMAIN,
                                  "count": counts["learned"] + counts["linked"]},
                    quality=quality, observation=source_id)
            if updates:
                # The ledger is what the substrate can say about what it learned; an update it could not record is
                # an error of the run, not a note.
                from core.database import get_database_manager
                await _ledger.record_many(get_database_manager(), updates)
        finally:
            _ledger.end_batch(batch)
        return counts

    async def withdraw_pairs(self, observations: Iterable[str], *, cause: str, apply: bool = True) -> Dict[str, int]:
        """THE TEACHER WITHDREW THESE TAUGHT PAIRS: what they vouched for no longer rests on them.

        `learn_patterns` keys each observation by its source and its pair, the sentence with its meaning. A lesson
        rewritten no longer teaches the pairs it was: english_01-39 were rewritten after main learned them, so "the X"
        is a known thing (docs/TEACHING.md §12d), and the constructions the old pairs made still read "The valve is
        closed." as valves being closed, at full belief, beside the ones the rewritten lessons teach. Nothing the
        method does (Doumen, Beuls & Van Eecke 2024, §4.2.8: a use +0.1, a competitor -0.3) ever lowers them: they
        read the new pairs to another meaning, so they are no competitors.

        Each word the pairs gave is withdrawn (`BayesianUncertaintySystem.withdraw_observation`). What nothing else
        ever vouched for is let go: its belief, and its memory, a construction or a link no reading uses again. What
        other evidence holds up keeps it, and keeps only that. Each change goes to the ledger.

        Never while a substrate reads or teaches the store: its language view would hold what was let go until it
        warms again. Returns counts: `withdrawn` (words taken back), `moved` (beliefs that keep other evidence),
        `removed`, `not_language` (beliefs the pairs vouched for that hold no construction or link: left as they
        are, and counted), and `refused` where the model is a frozen release. `apply` False changes nothing and
        counts what it would do."""
        from core.database import get_database_manager
        from core.memory import knowledge_ledger as _ledger
        from core.memory import get_memory_agent
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr

        withdrawn = {str(o) for o in observations}
        counts = {"withdrawn": 0, "moved": 0, "removed": 0, "not_language": 0, "refused": 0}
        if not withdrawn:
            return counts
        if self._refused_while_frozen(f"withdraw_pairs ({len(withdrawn)})"):
            counts["refused"] = len(withdrawn)
            return counts
        agent = await get_memory_agent()
        view = await agent.language_view()
        us = get_uncertainty_system()
        key_of = type(us)._claim_key
        items = {key_of(item.claim()): item for item in view.items()
                 if isinstance(item, (dr.Pattern, dr.Phrase, dr.Lexical, dr.Link))}
        held = await agent.stated_patterns()
        updates: List[Any] = []
        let_go: List[Tuple[Any, int]] = []

        def subject(belief) -> Tuple[str, str]:
            item = items.get(key_of(belief.claim))
            if item is None:
                return "belief", belief.belief_id
            return ("language_link" if isinstance(item, dr.Link) else "language_pattern"), item.key

        def word_of(entry) -> str:
            return str(entry.get("observation") or "") if isinstance(entry, dict) else ""

        batch = _ledger.begin_batch(cause)
        try:
            for belief in us.held_in_domain(dr.ENGLISH_DOMAIN):
                entries = list(belief.evidence_for) + list(belief.evidence_against)
                hit = {word_of(e) for e in entries if word_of(e) in withdrawn and not e.get("withdraws")}
                if not hit:
                    continue
                if all(word_of(e) in withdrawn for e in entries):
                    let_go.append((belief, len(hit)))
                    continue
                # A WORD ALREADY WITHDRAWN IS NOT WITHDRAWN AGAIN, nor counted: the pairs a lesson stopped teaching
                # once are among those it no longer teaches every time after, and each was counted and written to
                # the ledger as an update that changed nothing (506 on main, 2026-10-12, of which 239 withdrew).
                hit = {observation for observation in hit if us._witness_word(belief, observation) is not None}
                if not hit:
                    continue
                if not apply:
                    counts["withdrawn"] += len(hit)
                    counts["moved"] += 1
                    continue
                for observation in sorted(hit):
                    if us.withdraw_observation(belief.claim, observation, source="taught") is not None:
                        counts["withdrawn"] += 1
                counts["moved"] += 1
                kind, subject_id = subject(belief)
                updates.append(_ledger.KnowledgeUpdate(
                    subject_kind=kind, subject_id=subject_id, disposition=_ledger.Disposition.UPDATED,
                    domain=dr.ENGLISH_DOMAIN,
                    detail=f"{len(hit)} pair(s) it rested on are no longer taught; kept on its other evidence"))
            # Every write the withdrawals scheduled lands before any row is deleted.
            if apply:
                await us.drain_writes()
            for belief, pairs in let_go:
                item = items.get(key_of(belief.claim))
                if item is None:
                    counts["not_language"] += 1
                    continue
                if not apply:
                    counts["removed"] += 1
                    counts["withdrawn"] += pairs
                    continue
                memory_id = held.get(item.key)
                if memory_id and not await agent.delete_memory(
                        memory_id, reason=f"{cause}: it rested only on pairs no longer taught"):
                    raise RuntimeError(f"memory {memory_id} of {item.claim()[:80]!r} could not be forgotten")
                await us.let_go(belief.belief_id)
                counts["removed"] += 1
                counts["withdrawn"] += pairs
                updates.append(_ledger.KnowledgeUpdate(
                    subject_kind="language_link" if isinstance(item, dr.Link) else "language_pattern",
                    subject_id=item.key, disposition=_ledger.Disposition.REMOVED, domain=dr.ENGLISH_DOMAIN,
                    detail=f"rested only on {pairs} pair(s) no longer taught: {item.claim()}"[:500]))
            if updates:
                await _ledger.record_many(get_database_manager(), updates)
        finally:
            _ledger.end_batch(batch)
        logger.info("withdrew %d taught pair word(s): %d belief(s) kept on other evidence, %d let go (%d not a "
                    "construction or link)", counts["withdrawn"], counts["moved"], counts["removed"],
                    counts["not_language"])
        return counts

    async def learn_said(self, said, *, provenance: Any = None, quality: float,
                         progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """What words are said of, from a source that counted them in real use (the Brown corpus): `said` is an
        iterable of `(relation, word, side, other, times)`: "red" said of "wine" 16 times is
        `("has_property", "red", "object", "wine", 16)`. Not facts about wine: how English uses "red", which a
        listener goes by to tell which thing a word names (`MemoryAgent.said_selection`). Held by memory, one
        memory for each word, relation and side; the same source again moves nothing.

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        from core.memory import get_memory_agent
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        said = list(said)
        if self._refused_while_frozen(f"learn_said ({len(said)})"):
            return {"remembered": 0, "already": 0, "refused": len(said), "total": len(said)}
        if quality < MIN_ADMIT_QUALITY:
            logger.info("what words are said of REFUSED for %d use(s): evidence quality %.3f < floor %.2f",
                        len(said), quality, MIN_ADMIT_QUALITY)
            return {"remembered": 0, "already": 0, "refused": len(said), "total": len(said)}
        source_id = getattr(provenance, "source_id", None) or "you"
        agent = await get_memory_agent()
        counts = await agent.remember_said(
            ((relation, word, side, other, times, f"{source_id}:said", "word")
             for relation, word, side, other, times in said), progress=progress)
        return {**counts, "refused": 0}

    async def learn_structure(self, analysed, *, provenance: Any = None, quality: float,
                              progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """How the words of a sentence go together, from sentences analysed by hand (a treebank): `analysed` is an
        iterable of `structure.Analysed`, each word's class and the word it depends on and as what. Each is held by
        memory whole, as it was analysed (`MemoryAgent.remember_analysed`), and read as memory-based learning reads
        them (`structure.StructureView`). No belief is made of it and it is in no domain (`_learn_held`).

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        from core.memory import knowledge_ledger as _ledger
        from core.memory import get_memory_agent
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        analysed = list(analysed)
        if self._refused_while_frozen(f"learn_structure ({len(analysed)})"):
            return {"remembered": 0, "already": 0, "refused": len(analysed), "total": len(analysed)}
        if quality < MIN_ADMIT_QUALITY:
            logger.info("sentences analysed REFUSED for %d sentence(s): evidence quality %.3f < floor %.2f",
                        len(analysed), quality, MIN_ADMIT_QUALITY)
            return {"remembered": 0, "already": 0, "refused": len(analysed), "total": len(analysed)}
        producer = getattr(provenance, "producer", "learning")
        source_id = getattr(provenance, "source_id", None) or "you"
        agent = await get_memory_agent()
        held = await agent.remember_analysed(analysed, progress=progress)
        cause = f"learning.structure.{producer}"
        batch = _ledger.begin_batch(cause)
        updates: List[Any] = []
        try:
            for item, _ in held["kept"]:
                updates.append(_ledger.KnowledgeUpdate(
                    subject_kind="analysed_sentence", subject_id=item.key(), disposition=_ledger.Disposition.NEW,
                    detail=f"{item.text!r} as analysed ({item.said_in}, {source_id})"[:500], cause=cause))
            if updates:
                from core.database import get_database_manager
                await _ledger.record_many(get_database_manager(), updates)
        finally:
            _ledger.end_batch(batch)
        return {"remembered": held["remembered"], "already": held["already"], "refused": 0,
                "total": held["total"]}

    async def _learn_held(self, items, *, what: str, remember: str, subject_kind: str, provenance: Any,
                          quality: float, progress: Optional[Callable[[int, int], None]]) -> Dict[str, int]:
        """Hold items of language knowledge whole in memory (`remember`, a `MemoryAgent` method returning `kept`), each
        recorded in the knowledge ledger as taught. Each item has `key()` and `claim()`.

        LANGUAGE IS HOW TO READ, NOT KNOWLEDGE OF THE WORLD: no belief is made of an item and it is in no domain. Each
        had been a belief in the `english` domain that nothing read (no reader weighs a word record, a derivation or a
        sentence analysed by its belief), and each correction left one more (eight for "paint" on lyric_dev2,
        2026-10-27); memory holding the item, corrected in place (`MemoryAgent._remember_whole`), is its standing."""
        from core.memory import knowledge_ledger as _ledger
        from core.memory import get_memory_agent
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        # NOT MATERIALISED. `items` is the source's own iterable and each item is built as it is taught; this held
        # every one of them first (2.4 hours and 19.5 GB for 144,612 word records, 2026-11-10). How many there will
        # be is taken where the source says so cheaply (`Built`), and is 0 -- unknown -- otherwise. A pass refused
        # here builds nothing at all, which is the point of refusing before teaching.
        how_many = len(items) if hasattr(items, "__len__") else 0
        if self._refused_while_frozen(f"{remember} ({how_many or 'streamed'})"):
            return {"remembered": 0, "already": 0, "refused": how_many, "total": how_many}
        if quality < MIN_ADMIT_QUALITY:
            logger.info("%s REFUSED for %s item(s): evidence quality %.3f < floor %.2f", what,
                        f"{how_many:,}" if how_many else "streamed", quality, MIN_ADMIT_QUALITY)
            return {"remembered": 0, "already": 0, "refused": how_many, "total": how_many}
        producer = getattr(provenance, "producer", "learning")
        source_id = getattr(provenance, "source_id", None) or "you"
        agent = await get_memory_agent()
        held = await getattr(agent, remember)(items, progress=progress)
        cause = f"learning.{subject_kind}.{producer}"
        batch = _ledger.begin_batch(cause)
        updates: List[Any] = []
        try:
            for item, _ in held["kept"]:
                updates.append(_ledger.KnowledgeUpdate(
                    subject_kind=subject_kind, subject_id=item.key(), disposition=_ledger.Disposition.NEW,
                    detail=f"{item.claim()} ({source_id})"[:500], cause=cause))
            for item, _, was in held.get("corrected_items", ()):
                updates.append(_ledger.KnowledgeUpdate(
                    subject_kind=subject_kind, subject_id=item.key(), disposition=_ledger.Disposition.UPDATED,
                    detail=f"corrected: {item.claim()[:240]}; was {was.claim()[:240]} ({source_id})"[:500],
                    cause=cause))
            if updates:
                from core.database import get_database_manager
                await _ledger.record_many(get_database_manager(), updates)
        finally:
            _ledger.end_batch(batch)
        # AN ITEM MEMORY REFUSED IS COUNTED REFUSED, and why said: a sentence recorded whole whose layers do not hold
        # together (`MemoryAgent.remember_records`) was reported as nothing refused.
        for item_id, why in held.get("refused") or ():
            logger.warning("%s: %s refused: %s", what, item_id, "; ".join(why)[:500])
        counts = {"remembered": held["remembered"], "already": held["already"],
                  "corrected": held.get("corrected", 0), "refused": len(held.get("refused") or ()),
                  "total": held["total"] + len(held.get("refused") or ())}
        # AND HOW MANY WERE NOT MADE AT ALL, memory holding them under the same stamp (`MemoryAgent._remember_whole`):
        # a pass that says only `already` cannot be told from one that rebuilt every word to find that out.
        if held.get("not_made"):
            counts["not made"] = held["not_made"]
        if held.get("reviewed"):
            counts["reviewed"] = held["reviewed"]
        return counts

    async def learn_arguments(self, argued, *, provenance: Any = None, quality: float,
                              progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """Which phrases are a happening's arguments and what each is, from sentences whose happenings' arguments
        were annotated by hand (PropBank): `argued` is an iterable of `argument_structure.Argued`. Each is held by
        memory whole (`MemoryAgent.remember_argued`) and read as
        memory-based learning reads them (`argument_structure.ArgumentStructureView`).

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(argued, what="arguments annotated", remember="remember_argued",
                                      subject_kind="argued_sentence", provenance=provenance, quality=quality,
                                      progress=progress)

    async def learn_taught_sentences(self, taught, *, provenance: Any = None, quality: float,
                                     progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """How a sentence's meaning is composed from how its words go together, from the lessons' sentences each with
        the meaning it was taught to have: `taught` is an iterable of `composition.TaughtSentence`. Each is held by
        memory whole (`MemoryAgent.remember_taught_sentences`), and the
        composer learns from them as each is read with the structure memory holds (`composition.CompositionView`).

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(taught, what="sentences taught with their meanings",
                                      remember="remember_taught_sentences", subject_kind="taught_sentence",
                                      provenance=provenance, quality=quality, progress=progress)

    async def learn_word_groups(self, groups, *, provenance: Any = None, quality: float,
                                progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """Which words keep the same company, from words grouped by counting a great deal of text: `groups` is an
        iterable of `word_groups.WordGroup`. Each is held by memory whole (`MemoryAgent.remember_word_groups`), its
        standing a belief on that memory, and the structure reader stands each word's groups beside it.

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(groups, what="word groups", remember="remember_word_groups",
                                      subject_kind="word_group", provenance=provenance, quality=quality,
                                      progress=progress)

    async def learn_word_forms(self, forms, *, provenance: Any = None, quality: float,
                               progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """The forms words are written in, from treebanks whose analysts gave each word its base form: `forms` is an
        iterable of `word_forms.WordForms`. Each is held by memory whole (`MemoryAgent.remember_word_forms`), its
        standing a belief on that memory, and the reader reads a word it holds nothing of by them ("hired", `hire`).

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(forms, what="word forms", remember="remember_word_forms",
                                      subject_kind="word_forms", provenance=provenance, quality=quality,
                                      progress=progress)

    async def learn_derived(self, derived, *, provenance: Any = None, quality: float,
                            progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """What each word takes beside the words around it, from sentences derived by hand in a categorial grammar
        (the PMB's CCG derivations checked by hand): `derived` is an iterable of `grammar.Derived`. Each is held by
        memory whole (`MemoryAgent.remember_derived`), and English's grammar
        chooses each word's category by them (`Lexicon.hear_derived`).

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(derived, what="sentences derived by hand", remember="remember_derived",
                                      subject_kind="derived_sentence", provenance=provenance, quality=quality,
                                      progress=progress)

    async def learn_word_records(self, records, *, provenance: Any = None, quality: float,
                                 progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """Words recorded whole (`teaching_sources.WordRecord`: every form, every sense, how a verb is used): each held
        by memory as one memory (`MemoryAgent.remember_word_records`), each layer learned by the part of reading that
        learns from it. Taught before the sentences they are in.

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(records, what="words recorded whole", remember="remember_word_records",
                                      subject_kind="word_record", provenance=provenance, quality=quality,
                                      progress=progress)

    async def learn_records(self, records, *, provenance: Any = None, quality: float,
                            progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, int]:
        """Sentences recorded whole (`teaching_sources.SentenceRecord`: every layer of each sentence by word
        position): each held by memory as one memory (`MemoryAgent.remember_records`), each layer learned by the part of reading that learns from it.

        Returns counts: `remembered`, `already`, `refused`, `total`."""
        return await self._learn_held(records, what="sentences recorded whole", remember="remember_records",
                                      subject_kind="sentence_record", provenance=provenance, quality=quality,
                                      progress=progress)

    #: How many things taught a review asks itself about, by default.
    REVIEW_SAMPLE = 200
    #: How many facts a review looks at for each question it means to ask, at most.
    _REVIEW_TRIES = 20

    async def review_learned(self, domain: str, *, sample: Optional[int] = None, seed: Optional[int] = None,
                             progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
        """REVIEW WHAT WAS LEARNED: ask itself about things it was taught in `domain`, and let how it does move its
        competence there.

        Taught by telling, a domain's competence never moved: it rose only for an operator learned, so English, taught
        all of WordNet, stayed at 0.5 with no update (2026-10-10). A review is the substrate's own outcome in the
        domain. For each fact sampled from what it holds as learned there (its beliefs, each on the memory of being
        told), it SAYS the question in the English it was taught (`derived_reader.say` of the fact asked), READS its
        own question back with the one reader, checks it read what it meant to ask, and ANSWERS it by reasoning over
        what it holds (`answer_over_graph`). Right is evidence it is competent there; a fact it holds but cannot
        ask, read back or answer is evidence it is not, and a miss to work on. Each is recorded on the domain's
        competence belief (`record_competence_evidence`, `source="review"`).

        It writes no memory for each question: a conversation turn remembers what was said, and a sentence it could
        not read argues down the word classes it blamed, neither of which a question it put to itself should do. The
        review is remembered once, whole.

        Returns counts: `reviewed` (facts looked at), `asked` (questions put, each an outcome), `right`, the misses
        by why (`unread`, `misread`, `denied`, `not_derived`), `cannot_ask` (looked at, no question taught for it:
        no outcome), `skipped` (a belief whose memory claims no fact), `by_relation`, and competence
        `before`/`after`."""
        import random as _random
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_database_manager
        from core.integration.universal_domain_master import get_universal_domain_master
        from core.memory.utils.interfaces import MemoryType, Origin
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.reasoning.concept_graph_reasoning import answer_over_graph
        from core.reasoning.relation_algebra import FALSE, TRUE
        from core.semantics import derived_reader as dr
        from core.semantics.relation_types import SemanticRelation
        from core.utils.give_way import GiveWay

        if self._refused_while_frozen(f"review_learned ({domain})"):
            return {"reviewed": 0, "refused": "frozen"}
        agent = await get_memory_agent()
        if not agent._word_classes_warm:
            await agent.warm_word_classes()
        dm = self.domain_master or get_universal_domain_master()
        unc = get_uncertainty_system()
        db = get_database_manager()
        rng = _random.Random(seed)

        def competence():
            belief = dm.competence_belief(domain)
            return None if belief is None else (round(belief.posterior_probability, 4), belief.update_count)

        # WHAT IT HOLDS AS LEARNED THERE: the domain's beliefs on a memory, held, that are facts (a construction's
        # claim is a quoted sentence, and is reviewed by reading, not here).
        held = [b for b in list(unc.beliefs.values())
                if b.domain == domain and b.memory_id and b.posterior_probability > 0.5
                and not str(b.claim).startswith('"') and not str(b.claim).startswith(dm.COMPETENCE_CLAIM)]
        # ASKED, NOT LOOKED AT. A fact the substrate cannot put as a question in the English it was taught (a
        # definition's word links, "perch defined with spiny-finned", are three in four of what WordNet taught) says
        # nothing of how it does at what it can ask: counted against it, one review of 30 took English's competence
        # from 0.5 to 0.0001 on 26 facts it had no question for (2026-10-11). So it reviews until it has ASKED
        # `sample` questions, each a competence outcome; what it could not ask is kept by relation, a gap in what was
        # taught, and moves nothing. Drawn in a fixed order from all it holds there, at most `_REVIEW_TRIES` looks a
        # question.
        target = min(sample or self.REVIEW_SAMPLE, len(held))
        order = rng.sample(held, len(held))
        counts: Dict[str, Any] = {"held": len(held), "reviewed": 0, "asked": 0, "right": 0, "cannot_ask": 0,
                                  "unread": 0, "misread": 0, "denied": 0, "not_derived": 0, "skipped": 0,
                                  "by_relation": {}, "before": competence()}
        missed: List[Dict[str, str]] = []

        def key(fact) -> Tuple[str, str, str, bool]:
            return (fact.relation, " ".join(str(fact.subject).lower().replace("_", " ").split()),
                    " ".join(str(fact.obj).lower().replace("_", " ").split()), bool(fact.positive))

        give_way = GiveWay()
        chunk = max(50, 4 * target)
        for start in range(0, min(len(order), self._REVIEW_TRIES * max(1, target)), chunk):
            if counts["asked"] >= target:
                break
            batch = order[start:start + chunk]
            claims = await agent.claims_of([b.memory_id for b in batch])
            for belief in batch:
                if counts["asked"] >= target:
                    break
                await give_way()
                made = claims.get(belief.memory_id) or []
                try:
                    facts = tuple(dr.MeaningFact.from_list(f) for f in made)
                except (TypeError, ValueError):
                    facts = ()
                if len(facts) != 1:
                    counts["skipped"] += 1
                    continue
                fact = facts[0]
                counts["reviewed"] += 1
                # BY RELATION, because they are different knowledge: what a thing is a kind of is asked in English
                # every day; a definition's word links ("squash racket defined with small") have no question taught.
                per = counts["by_relation"].setdefault(fact.relation, {"reviewed": 0, "asked": 0, "right": 0})
                per["reviewed"] += 1
                # Named before it is said: a question that does not come back says which fact it was.
                logger.info("review of %s: saying %s", domain, fact.render())
                began = time.perf_counter()
                said = dr.say(dr.Meaning("ask", facts))
                if not said:
                    counts["cannot_ask"] += 1
                    continue
                counts["asked"] += 1
                per["asked"] += 1
                if progress is not None and counts["asked"] % 50 == 0:
                    progress(counts["asked"], target)
                why, question = None, said[0]
                utterances = dr.read_text(question)
                reading = await dr.heard(utterances[0].readings) if len(utterances) == 1 else None
                if reading is None:
                    why = "unread"
                elif reading.meaning.act != "ask" or [key(f) for f in reading.meaning.facts] != [key(fact)]:
                    why = "misread"
                else:
                    try:
                        relation = SemanticRelation(fact.relation)
                    except ValueError:
                        relation = None
                    answer = (await answer_over_graph(db, fact.subject, relation, fact.obj, max_hops=4)
                              if relation is not None else None)
                    verdict = getattr(answer, "verdict", None)
                    if verdict == TRUE and fact.positive or verdict == FALSE and not fact.positive:
                        counts["right"] += 1
                        per["right"] += 1
                    elif verdict in (TRUE, FALSE):
                        why = "denied"
                    else:
                        why = "not_derived"
                logger.info("review of %s: %r %s in %.1fs", domain, question, why or "right",
                            time.perf_counter() - began)
                if why:
                    counts[why] += 1
                    if len(missed) < 24:
                        missed.append({"fact": fact.render(), "asked": question, "why": why})
                # ONE REVIEW IS ONE OUTCOME, its questions sharing it: each carries 1/`target` of the weight one
                # outcome has (`COMPETENCE_EVIDENCE_QUALITY`). Each counted whole, a review of 200 that went 120 to
                # 80 moved English from 0.0007 to 0.99998, the difference counted forty times over; now a review
                # moves competence by at most one outcome, toward how it went, by how far it went.
                await dm.record_competence_evidence(domain, learned=why is None, source="review",
                                                    quality=dm.COMPETENCE_EVIDENCE_QUALITY / target)

        counts["after"] = competence()
        if counts["reviewed"]:
            await agent.store_memory(
                origin=Origin.own("learning"),
                content=(f"I reviewed {counts['reviewed']} things I was taught in {domain}: I could ask myself about "
                         f"{counts['asked']} of them, and answered {counts['right']} rightly."),
                memory_type=MemoryType.META, confidence_score=0.9,
                tags=["review", "self_assessment", domain],
                source_context={"review": {k: v for k, v in counts.items()}, "missed": missed, "domain": domain})
        logger.info("review of %s: %s", domain, counts)
        return {**counts, "missed": missed}

    async def learn_usage(self, usage, *, provenance: Any = None, quality: float) -> Dict[str, int]:
        """How often each word is met naming each thing, from a source that counted it in real use (WordNet's
        tagged corpus): `usage` is an iterable of `(word, concept, times)`.

        What a person learns from hearing English used, and what a listener goes by when nothing it knows tells
        two meanings of a word apart (`derived_reader.meant`): "fish" is met naming the animal more often than the
        food. Each count lands on the belief of each construction that says the word names the thing, as ONE
        observation from the source carrying how many uses it witnessed, so the same source again moves nothing:
        the word, and the phrases naming a thing of the kind in one of the word's forms (`(word, concept, times,
        forms)`: "had them" and "is having them", for "have"). Landed on the word alone, a verb held only in its
        forms was met in none of them, and "Tom had them." was the receiving "have" names 7 times, not the having it
        names 1,202 (2026-10-14). A word that names the thing through no construction yet (never read naming it) has
        nowhere to land, and is counted, not held elsewhere.

        Returns counts: `observed`, `already` (this source's count held already), `no_construction`, `total`.
        """
        from core.memory import knowledge_ledger as _ledger
        from core.memory import get_memory_agent
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        from core.semantics.sentence_machine import form_of

        usage = list(usage)
        counts = {"observed": 0, "already": 0, "no_construction": 0, "refused": 0, "total": len(usage)}
        if self._refused_while_frozen(f"learn_usage ({len(usage)})"):
            counts["refused"] = len(usage)
            return counts
        if quality < MIN_ADMIT_QUALITY:
            logger.info("usage REFUSED for %d word(s): evidence quality %.3f < floor %.2f",
                        len(usage), quality, MIN_ADMIT_QUALITY)
            counts["refused"] = len(usage)
            return counts
        agent = await get_memory_agent()
        view = await agent.language_view()
        held = await agent.stated_patterns()
        producer = getattr(provenance, "producer", "learning")
        source_id = getattr(provenance, "source_id", None) or "you"
        cause = f"learning.usage.{producer}"
        us = get_uncertainty_system()
        updates: List[Any] = []
        batch = _ledger.begin_batch(cause)
        # Every sense a source counted is looked up and observed on the substrate's loop (`GiveWay`).
        give_way = GiveWay()
        try:
            for word, concept, times, forms in usage:
                await give_way()
                saying = view.saying(tuple(p.text for p in form_of(str(word))), concept, forms)
                if not saying:
                    counts["no_construction"] += 1
                    continue
                landed = False
                for construction in saying:
                    before = us.belief_for_claim(construction.claim())
                    seen = len(before.evidence_for) if before is not None else 0
                    after = us.observe_claim(construction.claim(), dr.ENGLISH_DOMAIN, supports=True, quality=quality,
                                             source="taught", observation=f"{source_id}:usage",
                                             memory_id=held.get(construction.key), uses=int(times))
                    if after is None or len(after.evidence_for) <= seen:
                        continue
                    landed = True
                    updates.append(_ledger.KnowledgeUpdate(
                        subject_kind="language_pattern", subject_id=construction.key,
                        disposition=_ledger.Disposition.UPDATED, domain=dr.ENGLISH_DOMAIN,
                        detail=f"{word!r} met {int(times)} times naming {concept!r} ({source_id})"[:500],
                        cause=cause))
                counts["observed" if landed else "already"] += 1
            if updates:
                from core.database import get_database_manager
                await _ledger.record_many(get_database_manager(), updates)
        finally:
            _ledger.end_batch(batch)
        return counts

    async def learn_listening(self, counts, *, provenance: Any = None, quality: float) -> Dict[str, int]:
        """What the listener's evidence is worth, as it counted it on sentences whose meaning it was taught
        (`derived_reader.listening_counts`): for each piece of evidence at each level, how many readings showing it
        were the one meant and how many were not. Each count is held as the belief `derived_reader.listening_claim`
        names, ONE observation from the source carrying how many readings it counted, and the listener reads its
        worths from them (`derived_reader.listening_worths`). Counted again by the same source, its earlier word is
        withdrawn first: a belief holds what was last counted, not every count added up.

        Returns counts: `observed`, `withdrawn` (an earlier count taken back), `refused`, `total`."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY

        report = {"observed": 0, "withdrawn": 0, "refused": 0, "total": 0}
        if self._refused_while_frozen("learn_listening"):
            report["refused"] = 1
            return report
        if quality < MIN_ADMIT_QUALITY:
            logger.info("listening counts REFUSED: evidence quality %.3f < floor %.2f", quality, MIN_ADMIT_QUALITY)
            report["refused"] = 1
            return report
        source_id = getattr(provenance, "source_id", None) or "you"
        # THE MEMORY THE COUNTS ARE ABOUT, held once: a belief names the memory it is a stance on, or it is not stored,
        # and the listener's counts, about none, were each refused without a word in the pass's report (2026-10-14).
        from core.agents.memory_agent import get_memory_agent
        from core.memory.utils.interfaces import MemoryType, Origin
        agent = await get_memory_agent()
        memory_id = await agent.listening_memory()
        if memory_id is None:
            stored, memory_id = await agent.store_memory(
                origin=Origin.own("teaching"),
                content="What the listener's evidence is worth: how many readings at each level of each were the one "
                        "meant, counted on sentences whose meaning it was taught",
                memory_type=MemoryType.SEMANTIC, confidence_score=float(quality),
                tags=["language", agent.LISTENING_TAG],
                source_context={"producer": getattr(provenance, "producer", "learning"), "source_id": source_id})
            if not stored or not memory_id:
                raise RuntimeError("the memory of what the listener counted could not be stored")
        # EACH COUNT ITS OWN WITNESS, the earlier ones withdrawn by name: a word given at the moment its witness
        # withdrew is not its word, and the same witness withdrawn and counting again at once could be both.
        counted = f"{source_id}:listening"
        observation = f"{counted}:{time.time():.6f}"
        us = get_uncertainty_system()
        for evidence, levels in dr.LISTENING_LEVELS.items():
            for level in range(levels):
                for meant in (True, False):
                    claim = dr.listening_claim(evidence, level, meant)
                    report["total"] += 1
                    belief = us.belief_for_claim(claim)
                    earlier = {str(entry.get("observation")) for entry in (belief.evidence_for if belief else ())
                               if isinstance(entry, dict) and str(entry.get("observation") or "").startswith(counted)}
                    for witness in sorted(earlier):
                        if us.withdraw_observation(claim, witness) is not None:
                            report["withdrawn"] += 1
                    readings = int(counts.get((evidence, level, meant), 0))
                    if readings:
                        us.observe_claim(claim, dr.ENGLISH_DOMAIN, supports=True, quality=quality, source="taught",
                                         observation=observation, memory_id=memory_id, uses=readings)
                        report["observed"] += 1
        return report

    async def _store_language_item(self, agent: Any, item: Any, producer: str, source_id: str,
                                   quality: float) -> Optional[str]:
        """One construction or link as the semantic memory that holds it; its memory id, or None."""
        from core.memory.utils.interfaces import MemoryType, Origin
        from core.semantics import derived_reader as dr
        if isinstance(item, dr.Link):
            content, kind, data = (f'"{item.pattern_surface}" {item.slot} takes "{item.lexical_surface}"',
                                   "link", {"link": item.to_dict()})
        elif isinstance(item, dr.Lexical):
            content, kind, data = item.surface, "lexical", {"lexical": item.to_dict()}
        elif isinstance(item, dr.Phrase):
            content, kind, data = item.surface, "phrase", {"phrase": item.to_dict()}
        else:
            content, kind, data = item.surface, item.kind, {"pattern": item.to_dict()}
        stored, memory_id = await agent.store_memory(
            origin=Origin.own("teaching"),
            content=content,
            memory_type=MemoryType.SEMANTIC,
            confidence_score=float(quality),
            tags=["language", dr.PATTERN_TAG],
            source_context={"producer": producer, "source_id": source_id, "pattern_key": item.key,
                            "construction": kind, **data})
        return memory_id if stored and memory_id else None

    async def consider_many(self, facts, *, evidence: Evidence, domain: str, positive: bool = True,
                            progress: Any = None) -> Dict[str, int]:
        """Many claims from one source -- a lesson, a corpus -- each judged as `consider` judges one (its shape,
        what the world holds against it), with the fan-out to beliefs, the lexicon, the domain and metrics done
        ONCE over what was held: a reference-sized teach fact by fact re-ran it tens of thousands of times. Each
        fact is `(subject, relation, obj[, the sentence it was said in])`, all asserted or all denied (`positive`).
        Returns {admitted, already, doubted, refused, total}.

        THE EPISODE IS NOT OPTIONAL: the ingress remembers every fact it takes, as it does one considered alone,
        so a fact taught from a corpus is recalled by meaning as a fact taught in a sentence is."""
        from core.memory import knowledge_ledger as _ledger
        _batch = _ledger.begin_batch(f"learning.bulk_teach.{evidence.producer}", actor=None)
        try:
            return await self._consider_many(facts, evidence=evidence, domain=domain, positive=positive,
                                              progress=progress)
        finally:
            _ledger.end_batch(_batch)

    async def _consider_many(self, facts, *, evidence: Evidence, domain: str, positive: bool,
                             progress: Any) -> Dict[str, int]:
        from core.memory import knowledge_ledger as _ledger
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY, get_cognitive_ingress, shape_proposition
        facts = list(facts)
        counts = {"admitted": 0, "already": 0, "doubted": 0, "refused": 0, "total": 0}
        if self._refused_while_frozen(f"consider_many ({len(facts)})") or evidence.quality < MIN_ADMIT_QUALITY:
            counts["refused"] = counts["total"] = len(facts)
            return counts
        prov = self._provenance(evidence)
        ingress = get_cognitive_ingress()
        # ONE PERSON'S WORD HAS THE SAME HOUR HOWEVER IT ARRIVES: what `consider` lets one source put in the world
        # in an hour, a lesson or a corpus from that source does not exceed.
        budget = (self.PERSON_CLAIMS_PER_HOUR - await self._claims_this_hour(evidence.key)
                  if evidence.source_type == "USER_SUPPLIED" else None)
        held_clauses = []
        # WHAT EACH FACT DID, collected and written once at the end: at corpus scale one INSERT per fact is the cost
        # that once made the writer a bare bulk statement with no record at all.
        _updates: List[Any] = []
        for fact in facts:
            # A fact may carry THE SENTENCE IT WAS SAID IN; where it does not, the surface is the triple.
            subject, relation, obj = fact[0], fact[1], fact[2]
            said = fact[3] if len(fact) > 3 else None
            counts["total"] += 1
            subject_term, relation_term, obj_term, refusal = shape_proposition(subject, relation, obj)
            # Named in the store's own terms, as `consider` names it: one claim, one belief.
            claim = " ".join(str(p) for p in ((subject_term, relation_term, obj_term) if not refusal
                                              else (subject, relation, obj)) if p)
            against = None if refusal or not obj_term else await self._held_against(
                subject_term, relation_term, obj_term, positive)
            if refusal:
                counts["refused"] += 1
                logger.info("fact %r refused: %s", claim, refusal)
                continue
            if against:
                # COUNTED AGAINST WHAT IS HELD, not written over it: a lesson that contradicts the world moves the
                # belief, and is held only once its witnesses outweigh what holds the other side (`consider`).
                self.observe_claim(claim, domain, supports=positive, quality=evidence.quality,
                                   source=evidence.source, observation=evidence.key)
                if not self._outweighs(claim, positive, against[1], against[2]):
                    counts["doubted"] += 1
                    logger.info("fact %r not held: %s", claim, against[0])
                    continue
            if budget is not None and budget <= 0:
                counts["refused"] += 1
                logger.info("fact %r waits: %d new claims from one person in the hour", claim,
                            self.PERSON_CLAIMS_PER_HOUR)
                continue
            # A FAILURE IS NOT A REFUSAL. Counted as refused, a fact the store could not take (a timeout, a lost
            # connection) read as one the gate decided against, and a run with errors reported itself clean.
            admission = await ingress.admit_relation(
                subject=subject, relation=relation, obj=obj, surface=said or claim,
                provenance=prov, positive=positive, domain=domain, quality=evidence.quality)
            # Already held from this source is checked FIRST: a re-teach is not a second witness.
            if getattr(admission, "already_present", False):
                counts["already"] += 1
            elif getattr(admission, "admitted", False):
                counts["admitted"] += 1
                held_clauses.append((subject_term, relation_term, obj_term, getattr(admission, "memory_id", None)))
            else:
                counts["refused"] += 1
                logger.info("fact %r refused: %s", claim,
                            "; ".join(getattr(admission, "refusals", ()) or ()) or "no reason given")
            _disposition, _detail = self._ledger_disposition(admission)
            if budget is not None and _disposition in (_ledger.Disposition.NEW, _ledger.Disposition.UPDATED):
                budget -= 1
            _updates.append(_ledger.KnowledgeUpdate(
                subject_kind="proposition",
                subject_id=str(getattr(admission, "proposition", "") or f"{subject}|{relation}|{obj}")[:500],
                disposition=_disposition, domain=domain,
                evidence_id=getattr(admission, "evidence_id", None) or None,
                detail=_detail, cause=f"learning.bulk_teach.{evidence.producer}", actor=evidence.key))
            if progress and counts["total"] % 1000 == 0:
                progress(counts)
        # Fan out ONCE over everything newly held, as one source's word: re-running a pass makes nothing truer.
        if held_clauses:
            await self._fan_out_learning(
                surface=f"{len(held_clauses)} taught facts", claim=f"{len(held_clauses)} taught facts",
                clauses=held_clauses, positive=positive, domain=domain, emit=None,
                emit_payload={"kind": "bulk_facts", "domain": domain, "count": len(held_clauses)},
                quality=evidence.quality, observation=evidence.key)
        if _updates:
            from core.database import get_database_manager
            await _ledger.record_many(get_database_manager(), _updates)
        return counts

    async def learn_concept(self, name: str, *, domain: str, evidence: Evidence,
                            description: str = "", relationships: Any = None, emit: Any = None) -> list:
        """Learn a CONCEPT -- a node and its relationships -- through the ONE door (`consider`).

        A concept with edges is considered per edge (subject = `name`); a concept with none is admitted as a bare
        node so it still exists in the graph. This is the method a discoverer of concepts (analogy) calls INSTEAD of
        writing `unified.concepts` directly, so a derived concept goes through the same judgement, identity
        resolution, aliasing, domain membership and fan-out as a taught one. `relationships` is an iterable of
        (relation, object) pairs. Returns the per-edge `Decision`s."""
        rels = [tuple(r) for r in (relationships or []) if r and len(tuple(r)) >= 2]
        decisions = []
        if rels:
            first = True
            for rel, obj in ((r[0], r[1]) for r in rels):
                decisions.append(await self.consider(
                    name, str(rel), (str(obj) if obj is not None else None), evidence=evidence, domain=domain,
                    description=(description if first else ""), emit=emit))
                first = False
        else:
            # Bare node: a valid relation is required by the ingress even though no edge is created when the
            # object is None, so `is` names the copula and the admission is the node alone.
            decisions.append(await self.consider(name, "is", None, evidence=evidence, domain=domain,
                                                 description=description, emit=emit))
        return decisions

    async def consider_rule(self, antecedent: Dict[str, Any], consequent: Dict[str, Any], *, surface: str,
                            evidence: Evidence, domain: str, emit: Any = None) -> Decision:
        """A rule about the world ("if the valve is closed then the tank overflows", of kinds), judged as a claim is
        (`consider`): its clauses' shape and its evidence's quality; what is held against it -- the same condition
        held to lead to the opposite -- refuses it where that rule is settled and is counted against it where not;
        held, it lands in the held-conditional store the reasoner chains over, its clauses feed the lexicon, its
        implication moves a posterior, the domain crystallizes, and it is counted. A person's own rule is theirs
        (`MemoryAgent.hold_rule_for_person`), never this."""
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY, get_cognitive_ingress, shape_proposition
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system

        def said(clause: Dict[str, Any], positive: Optional[bool] = None) -> str:
            held = bool(clause.get("positive", True)) if positive is None else positive
            return ("" if held else "not ") + " ".join(
                str(clause.get(k) or "") for k in ("subject", "relation", "obj")).strip()
        claim = " ".join(f"if {said(antecedent)} then {said(consequent)}".split())
        frozen = self._refused_while_frozen(f"consider_rule {claim}")
        if frozen:
            return Decision(claim, True, "refused", [frozen])
        if evidence.quality < MIN_ADMIT_QUALITY:
            return Decision(claim, True, "refused", [
                f"insufficient support: quality {evidence.quality:.3f} < floor {MIN_ADMIT_QUALITY}"])
        if evidence.source_type == "USER_SUPPLIED" and await self._claims_this_hour(evidence.key) \
                >= self.PERSON_CLAIMS_PER_HOUR:
            return Decision(claim, True, "refused", [
                f"{self.PERSON_CLAIMS_PER_HOUR} new claims from one person in the hour; this one waits"])
        shaped = []
        for tag, clause in (("antecedent", antecedent), ("consequent", consequent)):
            subject, relation, obj, refusal = shape_proposition(clause.get("subject"), clause.get("relation"),
                                                                clause.get("obj"))
            if refusal:
                return Decision(claim, True, "refused", [f"{tag} {refusal}"])
            shaped.append((subject, relation, obj, bool(clause.get("positive", True))))
        (a_s, a_r, a_o, a_p), (c_s, c_r, c_o, c_p) = shaped

        def stated(s: Any, r: Any, o: Any, p: bool) -> str:
            return ("" if p else "not ") + " ".join(str(x) for x in (s, r, o) if x)
        # Named in the store's own terms, as a claim is (`consider`): one rule, one belief.
        claim = f"if {stated(a_s, a_r, a_o, a_p)} then {stated(c_s, c_r, c_o, c_p)}"
        from core.database import get_database_manager
        rows = await get_database_manager().execute_query(
            "SELECT surface FROM unified.held_conditionals WHERE ant_subject = $1 AND ant_relation = $2 "
            "AND ant_object IS NOT DISTINCT FROM $3 AND ant_positive = $4 AND cons_subject = $5 "
            "AND cons_relation = $6 AND cons_object IS NOT DISTINCT FROM $7 AND cons_positive = $8 LIMIT 1",
            (a_s, a_r, a_o, a_p, c_s, c_r, c_o, not c_p), fetch_all=True) or []
        beliefs = get_uncertainty_system()
        if rows:
            # THE SAME CONDITION HELD TO LEAD TO THE OPPOSITE: counted, and held only once this rule's independent
            # witnesses outweigh that one's, as a claim is (`consider`).
            held = rows[0].get("surface") or "the opposite rule"
            opposite = f"if {stated(a_s, a_r, a_o, a_p)} then {stated(c_s, c_r, c_o, not c_p)}"
            was_settled = self._settled_on(beliefs.belief_for_claim(opposite), positive=True)
            self.observe_claim(claim, domain, supports=True, quality=evidence.quality, source=evidence.source,
                               observation=evidence.key)
            if not self._outweighs(claim, True, opposite, True):
                side = self._side(beliefs.belief_for_claim(claim), positive=True)
                if was_settled:
                    return Decision(claim, True, "refused", [f"contradicts what is settled: {held}"], posterior=side)
                return Decision(claim, True, "doubted", [f"held otherwise ({held}); counted against it"],
                                posterior=side)
        prov = self._provenance(evidence)
        admission = await get_cognitive_ingress().admit_conditional(
            antecedent, consequent, surface=surface, provenance=prov, domain=domain)
        await self._record_knowledge_update(admission, domain=domain, provenance=prov)
        if admission.admitted:
            await self._fan_out_learning(
                surface=surface, claim=claim,
                clauses=[(antecedent.get("subject"), antecedent.get("relation"), antecedent.get("obj")),
                         (consequent.get("subject"), consequent.get("relation"), consequent.get("obj"))],
                positive=True, domain=domain, emit=emit,
                emit_payload={"kind": "conditional", "surface": surface, "domain": domain},
                observation=evidence.key, quality=evidence.quality)
        elif not getattr(admission, "already_present", False):
            return Decision(claim, True, "refused", list(admission.refusals) or ["the store did not take it"],
                            admission=admission)
        belief = beliefs.belief_for_claim(claim)
        return Decision(claim, True, "settled" if self._settled_on(belief, positive=True) else "candidate",
                        admission=admission, posterior=self._side(belief, positive=True))

    def create_belief(self, claim: str, domain: str, prior: float = 0.5,
                      evidence: Any = None, *, source: str = "derived") -> Any:
        """Record a belief THROUGH the one authority.

        A belief is a knowledge write like any other: a reasoning conclusion, a
        taught fact, and a perception all move the SAME belief store, so they
        enter by one door instead of each reaching the substrate directly. This
        delegates to the belief substrate (bayesian_uncertainty) and tags the
        source, so `create_belief` on the authority and on the substrate return
        the identical object -- the reasoners keep their contract, the writes
        gain one owner. Beliefs are revisable: what is created today `update_belief`
        can move tomorrow."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        # Source is PROVENANCE, not evidence. Only tag+apply an observation when
        # the caller actually supplied evidence; with no evidence the belief must
        # stand at its prior (the belief substrate applies any non-empty evidence
        # dict as a supporting observation, so a source-only dict would silently
        # nudge every no-evidence belief up from its prior — e.g. a completion
        # belief minted low would drift toward done before any real evidence).
        if isinstance(evidence, dict) and evidence:
            ev = dict(evidence)
            ev.setdefault("source", source)
        else:
            ev = None
        return get_uncertainty_system().create_belief(
            claim, domain, prior=prior, evidence=ev)

    def update_belief(self, belief_id: str, evidence: Dict[str, Any],
                      evidence_supports: bool = True) -> Any:
        """Revise a held belief THROUGH the one authority (see create_belief).
        A Bayesian update on the single belief store -- what was believed can
        change as evidence arrives."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().update_belief(
            belief_id, evidence, evidence_supports=evidence_supports)

    def get_belief(self, belief_id: str) -> Any:
        """The held belief for an id (or None) THROUGH the one authority — the
        completion decision reads its posterior."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().get_belief(belief_id)

    def belief_for_claim(self, claim: str) -> Any:
        """A held belief matching a claim (or None) THROUGH the one authority — a
        fresh retrieval by proposition, for completion SAW."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().belief_for_claim(claim)

    def beliefs_for_domain(self, domain: str, limit: int = 8) -> Any:
        """The specific beliefs held in a domain (claim + posterior) THROUGH the one
        authority — for stamping a memory with its pertinent beliefs."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return get_uncertainty_system().beliefs_for_domain(domain, limit=limit)

    async def flush_belief(self, belief_id: str) -> bool:
        """Durably persist a belief (awaited, committed) THROUGH the one authority —
        for decision-critical beliefs that MUST survive a restart, such as a task's
        completion belief. Also replays any writes buffered while the DB was down."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        return await get_uncertainty_system().flush_belief(belief_id)

    def observe_claim(self, claim: str, domain: str = "language", *,
                      supports: bool = True, quality: float = 0.9,
                      source: str = "observed",
                      observation: Optional[str] = None,
                      memory_id: Optional[str] = None) -> Any:
        """Record ONE observation of a claim THROUGH the one authority, idempotently.

        The find-or-create-by-claim door (see create_belief): the first
        observation of a claim mints its belief; each later observation moves the
        SAME posterior, so repeated evidence about one claim reinforces or
        contradicts a single belief instead of spawning parallels. This is the door
        the COMPLETION belief uses -- the substrate observes "this task's goal
        holds" as execution produces evidence, and the one belief accumulates
        toward (or away from) done. Delegates to the belief substrate; beliefs are
        revisable."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        # `memory_id`: what was met that this observation is of. A belief names a
        # memory or it is not stored (`BayesianUncertaintySystem.is_grounded`).
        return get_uncertainty_system().observe_claim(
            claim, domain, supports=supports, quality=quality, source=source,
            observation=observation, memory_id=memory_id)

    # ── Resolving what the substrate knew it did not know ───────────────────
    #
    # A known unknown is RESOLVED BY LEARNING, never because a caller decided
    # it was done. Three things must all be learned enough: the KNOWLEDGE the
    # unknown asks for is held (a producing rule, a graph edge, a remembered
    # grounding), the BELIEF in it is settled -- below the belief store's
    # UNSTABLE_ENTROPY -- and grounded in something met, and the DOMAIN holds
    # it. Until then it stays open and the attempt is counted. The belief
    # store records a resolution only from these grounds.

    _NO_TARGET = "the unknown states nothing that would satisfy it"

    async def resolve_known_unknown(self, unknown_id: str, *, attempt: bool = True):
        """Put one open known unknown through the gate; resolve it if and only
        if everything it asks for is learned enough. Returns the grounds
        (`.satisfied` says whether it was resolved). Raises LookupError when
        `unknown_id` is not open.

        `attempt` says whether this is an ATTEMPT to resolve it -- learning was
        just done toward it (a deficit closure) -- which is counted when it
        falls short. A periodic sweep only checks, and counts nothing: counting
        every check would grow every open unknown's attempts on a timer."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        unc = get_uncertainty_system()
        unknown = unc.known_unknowns.get(unknown_id)
        if unknown is None:
            raise LookupError(f"{unknown_id} is not an open known unknown")
        grounds = await self.resolution_grounds(unknown)
        if grounds.satisfied:
            unc.resolve_known_unknown(unknown_id, grounds)
        elif attempt:
            unc.note_resolution_attempt(unknown_id)
        return grounds

    async def resolve_open_unknowns(self) -> Dict[str, int]:
        """Every open known unknown through the gate. Returns how many were
        open, resolved, not yet learned enough, and stated no target."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        unc = get_uncertainty_system()
        counts = {"open": 0, "resolved": 0, "not_yet": 0, "no_target": 0}
        for unknown_id in list(unc.known_unknowns):
            if unknown_id not in unc.known_unknowns:
                continue
            counts["open"] += 1
            grounds = await self.resolve_known_unknown(unknown_id, attempt=False)
            if grounds.satisfied:
                counts["resolved"] += 1
            elif grounds.knowledge[1] == self._NO_TARGET:
                counts["no_target"] += 1
            else:
                counts["not_yet"] += 1
        return counts

    async def resolution_grounds(self, unknown):
        """The gate's verdict on one unknown, without acting on it."""
        from core.reasoning.bayesian_uncertainty import ResolutionGrounds
        target = await self._unknown_target(unknown)
        kind = target.get("kind")
        if kind == "operator":
            return await self._operator_grounds(unknown, target)
        if kind == "relation":
            return await self._relation_grounds(unknown, target)
        if kind == "settled":
            return await self._settled_grounds(unknown, target)
        missing = (False, self._NO_TARGET)
        return ResolutionGrounds(unknown.unknown_id, missing, missing, missing)

    async def _unknown_target(self, unknown) -> Dict[str, Any]:
        """What would satisfy `unknown`. Unknowns registered before targets
        existed carry none; for those it is read ONCE from the question each
        registrant wrote (the only three shapes in core/) and recorded, marked
        as derived. A question in no known shape has no target and cannot be
        resolved by the gate."""
        if unknown.target:
            return dict(unknown.target)
        import re
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        question = (unknown.question or "").strip()
        target: Optional[Dict[str, Any]] = None
        produce = re.fullmatch(r"how to produce (\S+) in (\S+)", question)
        resolve = re.fullmatch(r"how to resolve an? (\S+) in (\S+)", question)
        relation = re.fullmatch(r"what does (.+)\?", question)
        about = re.fullmatch(r"what is unresolved about (.+)\?", question)
        if produce and produce.group(2) == unknown.domain:
            target = {"kind": "operator", "predicate": produce.group(1)}
        elif resolve and resolve.group(2) == unknown.domain:
            target = {"kind": "operator", "predicate": None}
        elif about:
            target = {"kind": "settled", "about": about.group(1)}
        elif relation:
            # "what does <subject> <relation>?" -- the subject is one of the
            # domain's concept names, which is how the domain master wrote it.
            from core.integration.universal_domain_master import get_universal_domain_master
            rest = relation.group(1)
            names = sorted(await get_universal_domain_master().concept_names(unknown.domain),
                           key=len, reverse=True)
            subject = next((n for n in names if rest.startswith(n + " ")), None)
            if subject:
                target = {"kind": "relation", "subject": subject,
                          "relation": rest[len(subject) + 1:].strip()}
        if target is None:
            return {}
        target["derived_from"] = "question"
        get_uncertainty_system().set_target(unknown.unknown_id, target)
        return target

    @staticmethod
    def _settled(belief, *, supporting: bool, what: str) -> Tuple[bool, str]:
        """Whether `belief` is learned enough: grounded in something met, and
        settled (entropy at or below the belief store's UNSTABLE_ENTROPY) --
        on the supporting side when `supporting`, either way otherwise."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        unc = get_uncertainty_system()
        if belief is None:
            return False, f"no belief about {what}"
        p, h = float(belief.posterior_probability), float(belief.entropy)
        if not unc.is_grounded(belief):
            return False, f"belief {belief.belief_id} about {what} rests on nothing met"
        if h > unc.UNSTABLE_ENTROPY:
            return False, (f"belief {belief.belief_id} about {what} is unsettled "
                           f"(posterior {p:.2f}, entropy {h:.2f})")
        if supporting and p <= 0.5:
            return False, f"belief {belief.belief_id} about {what} is settled AGAINST ({p:.2f})"
        return True, f"belief {belief.belief_id} about {what} settled at {p:.2f}"

    async def executable_producers(self, domain_id: str,
                                   predicate: Optional[str]) -> List[Any]:
        """The executable rules in `domain_id` whose effects PRODUCE `predicate`
        (any executable rule when `predicate` is None) -- the world's answer to
        whether an operator gap is closed, read from the rule store."""
        executable = await self.store.executable_rules(domain_id=domain_id)
        return [stored for stored in executable
                if predicate is None or any(getattr(f, "predicate", None) == predicate
                                            for f in stored.rule.effects.add)]

    async def _operator_grounds(self, unknown, target):
        from core.reasoning.bayesian_uncertainty import ResolutionGrounds
        from core.tools.tool_registry import get_binding_registry
        from core.integration.universal_domain_master import get_universal_domain_master
        domain, predicate = unknown.domain, target.get("predicate")
        producers = await self.executable_producers(domain, predicate)
        knowledge = (bool(producers),
                     f"{len(producers)} executable rule(s) in {domain} produce "
                     f"{predicate or 'an effect'}"
                     + (f": {', '.join(p.rule_id for p in producers[:3])}" if producers else ""))
        competence = get_universal_domain_master().competence_belief(domain)
        belief = self._settled(competence, supporting=True, what=f"competence in {domain}")
        actions = sorted({p.rule.action.predicate for p in producers
                          if p.rule.action is not None})
        bound = [a for a in actions if get_binding_registry().get(domain, a) is not None]
        domain_ok = (bool(bound),
                     f"{domain} can act on it through {bound}" if bound else
                     f"no producing operator is bound to act in {domain} ({actions or 'none'})")
        answer = (f"{predicate or 'an effect'} is produced in {domain} by "
                  f"{producers[0].rule_id}" if producers else None)
        return ResolutionGrounds(unknown.unknown_id, knowledge, belief, domain_ok,
                                 answer=answer,
                                 belief_id=getattr(competence, "belief_id", None))

    def _belief_in_relation(self, subject: str, relation: str):
        """The best-held belief whose claim says `<subject> <relation> ...`
        (a leading article tolerated), preferring grounded and settled ones."""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        unc = get_uncertainty_system()
        head = subject.replace("_", " ").lower().split() + relation.lower().split()
        found = []
        for belief in list(unc.beliefs.values()):
            words = str(belief.claim).lower().split()
            if words and words[0] in ("a", "an", "the"):
                words = words[1:]
            if len(words) > len(head) and words[:len(head)] == head:
                found.append(belief)
        found.sort(key=lambda b: (unc.is_grounded(b),
                                  b.entropy <= unc.UNSTABLE_ENTROPY,
                                  b.posterior_probability), reverse=True)
        return found[0] if found else None

    async def _relation_grounds(self, unknown, target):
        from core.reasoning.bayesian_uncertainty import ResolutionGrounds
        from core.database import get_database_manager
        from core.integration.universal_domain_master import get_universal_domain_master
        from core.semantics.cognitive_ingress import normalize_term
        domain, subject, relation = unknown.domain, target["subject"], target["relation"]
        rel = " ".join(str(relation).replace("_", " ").split())
        rows = await get_database_manager().execute_query(
            "SELECT DISTINCT c2.name AS obj FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE c1.name = $1 AND cr.relation = $2 "
            "AND COALESCE(cr.polarity, 'positive') = 'positive'",
            (normalize_term(subject), rel), fetch_all=True) or []
        objects = [r["obj"] for r in rows]
        knowledge = (bool(objects),
                     f"the concept graph holds {subject} {rel} {objects[:3]}" if objects else
                     f"the concept graph holds nothing for {subject} {rel}")
        held = self._belief_in_relation(subject, rel)
        belief = self._settled(held, supporting=True, what=f"{subject} {rel} ...")
        carries = await get_universal_domain_master().holds_relation(domain, subject, relation)
        domain_ok = (carries is True,
                     f"{domain}'s concept {subject} carries {relation}" if carries else
                     (f"{domain}'s concept {subject} does not carry {relation}"
                      if carries is False else f"{subject} is not a concept of {domain}"))
        answer = held.claim if held is not None else (
            f"{subject} {rel} {objects[0]}" if objects else None)
        return ResolutionGrounds(unknown.unknown_id, knowledge, belief, domain_ok,
                                 answer=answer, belief_id=getattr(held, "belief_id", None))

    async def _settled_grounds(self, unknown, target):
        import re
        from core.reasoning.bayesian_uncertainty import (ResolutionGrounds,
                                                         get_uncertainty_system)
        from core.integration.universal_domain_master import get_universal_domain_master
        unc = get_uncertainty_system()
        domain, about = unknown.domain, str(target["about"])
        names = re.compile(r"(?<![a-z0-9_])" + re.escape(about.lower()) + r"(?![a-z0-9_])")
        candidates = [b for b in list(unc.beliefs.values())
                      if b.domain == domain and names.search(str(b.claim).lower())]
        candidates.sort(key=lambda b: (unc.is_grounded(b),
                                       b.entropy <= unc.UNSTABLE_ENTROPY, -b.entropy),
                        reverse=True)
        held = candidates[0] if candidates else None
        belief = self._settled(held, supporting=False, what=about)
        memory_id = None
        if held is not None:
            memory_id = getattr(held, "memory_id", None) or next(
                (e.get("memory_id") for e in (*held.evidence_for, *held.evidence_against)
                 if isinstance(e, dict) and e.get("memory_id")), None)
        remembered = None
        if memory_id:
            from core.memory import get_memory_agent
            remembered = await (await get_memory_agent()).retrieve_memory(memory_id)
        knowledge = (remembered is not None,
                     f"what settles it is remembered ({memory_id})" if remembered is not None
                     else f"nothing remembered settles {about}")
        has = await get_universal_domain_master().has_domain(domain)
        domain_ok = (has, f"{domain} is a domain the substrate holds" if has
                     else f"{domain} is not a domain the substrate holds")
        answer = (f"{held.claim} ({'held' if held.posterior_probability > 0.5 else 'not held'}, "
                  f"posterior {held.posterior_probability:.2f})" if held is not None else None)
        return ResolutionGrounds(unknown.unknown_id, knowledge, belief, domain_ok,
                                 answer=answer, belief_id=getattr(held, "belief_id", None))

    async def consider_envelope(self, service: Any, envelope: Any, *, domain: str, quality: float,
                                memory_id: Optional[str] = None) -> Any:
        """Structured evidence -- what a sense, a tool, a page or a demonstration gives in one envelope: concepts and
        the links between them -- judged as a claim is (`consider`), link by link. A link the world holds against
        (`_held_against`) stays out of what is written, and is counted against what is held, by the envelope's
        source, once; the rest is ingested whole through the one writer of the concept graph (`service`) and fanned
        out to beliefs and the lexicon (`_fan_out_ingested`). Returns the `IngestionResult`."""
        from dataclasses import replace
        from core.semantics.cognitive_ingress import shape_proposition
        data = dict(getattr(envelope, "structured_data", None) or {})
        concepts = []
        for concept in data.get("concepts") or []:
            kept = []
            for edge in concept.get("relationships") or []:
                relation, obj = str(edge[0]), edge[1]
                positive = len(edge) < 3 or str(edge[2]) != "negative"
                subject_term, relation_term, obj_term, refusal = shape_proposition(
                    str(concept.get("label")), relation, str(obj) if obj is not None else None)
                against = None if refusal or not obj_term else await self._held_against(
                    subject_term, relation_term, obj_term, positive)
                if against:
                    support = edge[3] if len(edge) > 3 and edge[3] is not None else quality
                    claim = " ".join(str(p) for p in (subject_term, relation_term, obj_term) if p)
                    self.observe_claim(claim, domain, supports=positive, quality=float(support),
                                       source=str(getattr(envelope, "producer", "") or "evidence"),
                                       observation=str(getattr(envelope, "source_id", "") or claim))
                    if not self._outweighs(claim, positive, against[1], against[2]):
                        logger.info("evidence %s: %r not held: %s", getattr(envelope, "evidence_id", "?"), claim,
                                    against[0])
                        continue
                kept.append(edge)
            concepts.append({**concept, "relationships": kept} if "relationships" in concept else concept)
        if "concepts" in data:
            envelope = replace(envelope, structured_data={**data, "concepts": concepts})
        result = await service.ingest(envelope)
        # Written to the graph and never fanned out, evidence moved no belief and taught no word, and the run said
        # only a warning: the fan-out's failure is the envelope's.
        await self._fan_out_ingested(result, domain=domain, surface=getattr(envelope, "content", "") or "",
                                     quality=quality, memory_id=memory_id)
        return result

    async def _fan_out_ingested(self, result: Any, *, domain: str = "researched",
                                surface: str = "", quality: float,
                                memory_id: Optional[str] = None) -> int:
        """Run the learning fan-out over what an ingestion ALREADY admitted.

        A producer that writes through `concept_ingestion.ingest` directly
        (research, a tool capability, a perception) lands the concept graph but
        skips the lexicon and beliefs. This closes that gap WITHOUT a second
        write path: it takes the `IngestionResult.admitted_relations` and runs
        them through the SAME `_fan_out_learning` every learn_* method uses, so
        the vocabulary is learned and every observation moves a posterior. Idempotent
        and isolated -- a producer never fails because a fan-out arm did. Returns
        the number of relations fanned out.

        `quality` IS THE PRODUCER'S OWN EVIDENCE QUALITY, and is required. It
        used to be omitted, so every produced observation -- a perception above
        all -- took `_fan_out_learning`'s 0.9 default no matter what the producer
        knew. Measured on the live store: a detection reported at 0.01 and one
        reported at 0.99 both became beliefs at prior 0.900, because the
        detector's confidence reached a string attribute on a concept and went no
        further. The producer is the only party that knows how good its evidence
        is, so it is the party that has to say."""
        rels = getattr(result, "admitted_relations", None) or []
        n = 0
        for edge in rels:
            subj, rel, obj, positive = edge[0], edge[1], edge[2], edge[3]
            if not subj or not rel:
                continue
            # THE EDGE'S OWN SUPPORT WINS over the envelope's, where the producer
            # stated one. An observation is not uniform: a blob's colour is read
            # off the pixels and its shape is inferred from a lossy polygon
            # approximation, and both arrived at one envelope quality as though
            # equally well founded. None means the producer stated nothing for
            # this edge -- not that it is unsupported -- so the envelope's
            # quality stands rather than a number being invented for it.
            edge_quality = edge[4] if len(edge) > 4 and edge[4] is not None else None
            claim = " ".join(str(p) for p in (subj, rel, obj) if p)
            await self._fan_out_learning(
                surface=surface or claim, claim=claim,
                # THE MEMORY THE PRODUCER MET THIS IN, when it has one.
                # This path ingests EDGES from an evidence envelope, and a
                # producer that never met anything (a tool signature read
                # off a registry) passes None, and no belief is offered for
                # it (`_fan_out_learning`): a belief is about a memory.
                #
                # A PERCEPTION IS NOT THAT CASE, and it was being treated as
                # if it were. The substrate does meet an image: it looks at
                # a real file and measures real structure. Measured on the
                # live store, one `see()` of a photograph admitted 146
                # concept-graph edges, formed 0 memories and wrote 0
                # beliefs, every one refused here for naming no memory --
                # SEE-LOOP-01 fell 23/23 to 20/23 and FRAME-01 14/14 to
                # 13/14 on exactly that. The perception pipeline now forms
                # the memory of having perceived and names it here.
                clauses=[(subj, rel, obj, memory_id)],
                positive=bool(positive),
                domain=domain, emit=None,
                emit_payload={"kind": "ingested", "domain": domain,
                              "subject": subj, "relation": rel, "obj": obj},
                quality=(edge_quality if edge_quality is not None else quality),
                # THE ENVELOPE ID, WHICH WAS ALREADY STABLE AND ALREADY
                # DROPPED HERE. `submit_tool_declaration` stamps
                # `evidence_id=_stable_id("toolcap", name)` -- identical on
                # every boot -- and the comment beside it says "the envelope
                # id already collapses them in the store". It collapsed them
                # in the CONCEPT store; this fan-out never passed it on, so
                # every boot re-registering 371 tools appended another
                # evidence entry to each capability belief. That is the 674.
                observation=getattr(result, "evidence_id", None),
                )
            n += 1
        return n

    async def _fan_out_learning(self, *, memory_id: Optional[str] = None,
                                surface: str, claim: str,
                                clauses: List[tuple], positive: bool,
                                domain: str, emit: Any,
                                emit_payload: Dict[str, Any],
                                quality: float,
                                observation: Optional[str] = None) -> None:
        """The shared fan-out every learn_* method runs after admission, so a
        fact and a rule touch the SAME systems: LEXICON, BELIEFS, METRICS, and
        the DOMAIN (via the emitted event). Each arm is isolated — one failing
        never rolls back what already landed, and never breaks the caller.

        `quality` IS REQUIRED, and was a `= 0.9` default until it was measured.
        Three of the four callers relied on it — bulk teaching, taught rules, and
        every evidence producer — so the number that became the PRIOR of
        204,865 of the substrate's 205,861 beliefs was one nobody had stated.
        The worst of it was on the perception path: a detector's confidence
        travelled as far as a string attribute on a concept and was dropped
        here, so a recognition reported at 0.01 and one reported at 0.99 landed
        as byte-identical beliefs at prior 0.900.
        A default cannot be told apart from a judgement once it is in the store,
        which is exactly why there is no longer one: a caller that cannot say how
        good its evidence is has to say so at the call site, in front of a
        reader, rather than inherit an answer.

        BELIEFS ARE UNIVERSAL AND REVISABLE. Every write is an observation that
        moves a posterior -- a tool capability, a perception, a research finding,
        a taught fact all update what the substrate holds to be true, and what it
        believes today it can revise tomorrow. So there is no "this kind does not
        touch beliefs": everything does.

"""
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        # NO WORD-CLASS WRITE HERE. Teaching a fact taught parts of speech by
        # writing them to a second store, which then had to be kept in step
        # with the first and was not: it ended up holding 199 words, every one
        # a NOUN, because this arm recorded the subject and the object and
        # discarded the relation -- the verb.
        #
        # The memory of the sentence already says everything its words' classes
        # follow from, and `MemoryAgent.warm_word_classes` works them out from
        # exactly that. So there is nothing to write, nothing to flush, and
        # nothing that can survive a wipe to contradict what is remembered.
        # BELIEFS: every admitted clause moves a UNIVERSAL posterior. This fan-out
        # runs only for what the gate admitted to the world: what is about a
        # person is split off by the memory agent before it reaches the gate
        # (docs/research/SEPARATION_MAP.md §11.3), so nothing in this fan-out is
        # per-person. One belief PER admitted clause, named by the clause's own
        # terms; the surface claim only when no structured clauses were supplied.
        # THE ADMISSION FLOOR, ON EVERY PATH THAT MOVES A BELIEF.
        #
        # `MIN_ADMIT_QUALITY` guarded `cognitive_ingress.admit` — the taught
        # path — and nothing else. Produced evidence reaches beliefs through
        # `concept_ingestion.ingest` instead, and both modules describe
        # themselves as "the only write path", so a perception was admitted at
        # any quality at all while a taught fact at 0.30 was refused. Measured
        # before this: a detection reported at confidence 0.01 became a held
        # belief; the same claim, taught, could not.
        #
        # One floor, asked once, where every caller already has to state its
        # quality. Below it the substrate holds NOTHING rather than a belief it
        # barely credits: "I do not know what this is" is absence, not a weak
        # posterior that has already entered the graph and will be reasoned over
        # like any other. That is the product's stated rule, and it was true of
        # one door out of two.
        from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
        us = get_uncertainty_system()
        # A CLAUSE MAY CARRY THE MEMORY IT WAS ADMITTED AS. Three elements is
        # the long-standing shape (subject, relation, object); a fourth, when
        # present, is the id of the memory `_remember` wrote for it. The belief
        # is ABOUT that memory — without it `_persist` refuses, because a belief
        # with no subject is just another copy of the claim.
        subjected = [(" ".join(str(p) for p in c[:3] if p),
                      c[3] if len(c) > 3 else None)
                     for c in clauses if c and c[0] and c[1]]
        if quality < MIN_ADMIT_QUALITY:
            logger.info(
                "belief fan-out REFUSED for %d proposition(s) in %s: evidence "
                "quality %.3f < floor %.2f — held as absence, not as a weak "
                "belief", len(subjected or ([claim] if claim else [])),
                domain, quality, MIN_ADMIT_QUALITY)
            # THE FLOOR CLEARS WHAT THE LOOP BELOW ACTUALLY READS.
            #
            # It used to empty a separate `propositions` list, built from
            # `subjected` and read by nothing else — so the floor logged a
            # refusal and then the loop wrote every belief anyway. The floor had
            # no effect on this path at all. Invisible until now because
            # `_persist` was refusing these beliefs for a different reason
            # (they named no memory); with perception's memory supplied, a
            # detection reported at confidence 0.02 was held as a belief
            # against a stated floor of 0.50. SEE-LOOP-01 case C is the check
            # that could not fail, and now can.
            subjected = []
            claim = ""
        # `observation` IDENTIFIES THE WITNESS, and it was dropped right here.
        # The producer knows which observation this is -- a taught corpus knows
        # its source, an ingested envelope has a stable `evidence_id` -- and
        # none of it reached the belief store, which saw only
        # `{quality, source: "taught"}`. So a standing fact re-read at every
        # boot appended evidence and moved the posterior every time: 2,588
        # beliefs observed more than a hundred times, one of them 674 times.
        # Same shape as the quality default this fan-out already documents --
        # something the producer knew, computed upstream and discarded at the
        # seam.
        # A BELIEF IS ABOUT A MEMORY (`_persist`). A proposition that names none -- a tool's signature read off the
        # registry, which nothing met -- is not offered as one: offered, it was refused at the store, thousands of
        # times a boot, and the refusals buried every warning a run had to show. Counted, so it is seen.
        # A corpus fans out every fact it held in one call, each observed on the substrate's loop (`GiveWay`).
        give_way = GiveWay()
        for proposition, mid in (subjected or ([(claim, memory_id)] if claim else [])):
            await give_way()
            if mid is None:
                self.system_metrics["beliefs_with_no_memory"] = \
                    self.system_metrics.get("beliefs_with_no_memory", 0) + 1
                continue
            us.observe_claim(proposition, domain=domain, supports=positive,
                             quality=quality, source="taught",
                             observation=observation, memory_id=mid)
        # METRICS: the learning is counted.
        self.system_metrics["total_learning_sessions"] = \
            self.system_metrics.get("total_learning_sessions", 0) + 1
        # DOMAIN: crystallize the taught domain. On the conversational path an
        # emitter is wired, so the crystallization is deferred off the reply path
        # (Phase 3 reaction). A standalone caller (bulk teach, tests) has no event
        # bus -- rather than leave the domain to the idle tier, crystallize it
        # immediately through the SINGLE domain authority, so bulk teaching affects
        # the domain on the spot. Either way it is the one owner (`ensure_domain`),
        # never a second registrar; `ensure_domain` is idempotent.
        # A DOMAIN MUST EXIST TO BE REASONED ABOUT. This is registration, and
        # it is idempotent -- `ensure_domain` returns an already-registered
        # domain UNCHANGED. It is NOT the reaction, which is the mistake the
        # comment above recorded for months: "crystallize it immediately through
        # the SINGLE domain authority" was believed of a call that, for every
        # domain a corpus teaches into, does nothing at all.
        if domain:
            from core.integration.universal_domain_master import (
                get_universal_domain_master)
            dm = self.domain_master or get_universal_domain_master()
            await dm.ensure_domain(domain)
        # THEN TELL THE SUBSTRATE. Unconditionally.
        await self._announce(emit, emit_payload, domain)

    async def _announce(self, emit: Any, payload: Dict[str, Any],
                        domain: str) -> None:
        """Knowledge was admitted: say so, on every path.

        THIS WAS A CALLER'S OPTION AND IT SHOULD NEVER HAVE BEEN ONE. The fan-out
        branched on whether the caller passed an emitter, and only the
        conversational path ever did. So a fact told in conversation woke the
        domain authority -- crystallization, expansion, discovery -- and the SAME
        fact taught from a corpus woke nothing. Measured before this: `lexical`
        holds over 300,000 taught facts and the substrate's belief that it has
        learned that domain sits at its 0.5000 prior, never once updated.

        Knowledge entering the substrate is a fact ABOUT the substrate, so the
        authority states it rather than hoping its caller will. A caller that
        holds its own transport (the conversation) still supplies it; everything
        else reaches the live coordinator through the runtime registry, which
        exists precisely so a component can find it without a circular import.

        NO SILENT NO-OP. If there is no live substrate to hear this, knowledge is
        being admitted into something that is not running -- the exact condition
        this fixes -- so it is counted and said out loud rather than swallowed.
        """
        def unheard(reason: str) -> None:
            """The substrate was not told. Count it where a run can see it.

            This swallowed its exception into a warning, and the first thing it
            swallowed was my own bug -- `announce_evidence` added to the wrong
            class -- which then read as a clean run with the reactions silently
            absent. An announcement that fails is not a degraded success, it is
            knowledge admitted into a substrate that does not know about it, so
            it lands on the SAME counter as having no substrate at all and a
            teaching pass reports it.
            """
            self.system_metrics["admissions_unannounced"] = (
                self.system_metrics.get("admissions_unannounced", 0) + 1)
            logger.error(
                "learning: %s admitted into domain %r was NOT announced (%s). "
                "The domain authority will not crystallize, expand or discover "
                "from it. %d unannounced so far.",
                payload.get("kind", "knowledge"), domain, reason,
                self.system_metrics["admissions_unannounced"])

        if emit is not None:
            try:
                await emit(payload)
            except Exception as error:
                unheard(f"caller's emitter raised {type(error).__name__}: {error}")
            return

        from core.agents.autonomous.runtime_registry import (
            get_autonomous_coordinator)
        coordinator = get_autonomous_coordinator()
        if coordinator is None:
            unheard("no live substrate is registered — a teaching process must "
                    "START the substrate, not only construct it")
            return
        try:
            await coordinator.announce_evidence(payload)
        except Exception as error:
            unheard(f"{type(error).__name__}: {error}")

    async def record_demonstration(self, example, *, domain_id: str, owner: Optional[str] = None) -> bool:
        """Keep one executed demonstration; do NOT induce here.

        The hot-path half of learning: the executor calls it right after acting,
        so it must be cheap. Induction (a hypothesis search) is left to the
        always-online learner (`reinduce_operator`). `owner` is whose work it
        was, None for the substrate's own: a person's holds their particulars
        (`_operator_residue`). Returns whether a new demonstration was written
        (False if already recorded).
        """
        from core.learning.demonstration_store import get_demonstration_store
        return await get_demonstration_store().append(example, domain_id=domain_id, owner=owner)

    async def reinduce_operator(self, *, domain_id: str, predicate: str,
                                arity: int) -> Dict[str, Any]:
        """Re-induce one operator from its accumulated demonstrations, off the
        hot path, and promote it to executable when independent experience
        confirms it. The always-online half of learning."""
        return await self._induce_signature(
            domain_id=domain_id, predicate=predicate, arity=arity)

    async def drain_pending_induction(self, *, limit: int = 50) -> Dict[str, Any]:
        """Induce every signature that gathered demonstrations since it was last
        induced. Acting only RECORDS (and enqueues); this drains the queue. A
        pending CONTRASTIVE expands to all the domain's signatures. Returns which
        domains gained a newly executable operator (learning is what changes
        competence, not the acting that fed it)."""
        from core.learning.demonstration_store import (get_demonstration_store,
                                                       is_regularity_signature)

        demos = get_demonstration_store()
        pending = await demos.pending_signatures(limit=limit, with_marks=True)
        induced: List[Dict[str, Any]] = []
        by_domain: Dict[str, bool] = {}

        async def run(domain_id: str, predicate: str, arity: int):
            if is_regularity_signature(predicate):
                # A REGULARITY OF THE WORLD, not an operator: judged by its own
                # door, and it never makes a domain more competent to act.
                async with self._judging(domain_id, predicate, arity):
                    induced.append(await self._judge_regularity(
                        domain_id=domain_id, predicate=predicate, arity=arity))
                return
            outcome = await self._induce_signature(
                domain_id=domain_id, predicate=predicate, arity=arity)
            induced.append(outcome)
            by_domain[domain_id] = by_domain.get(domain_id, False) or bool(
                outcome.get("executable"))

        for domain_id, predicate, arity, marked in pending:
            try:
                if (predicate, arity) == demos.CONTRASTIVE:
                    # A contrastive negative sharpens the domain's OPERATORS: it
                    # says their effects need their act. A regularity's effects
                    # need none, so it is not among them.
                    for p, a in await demos.signatures(domain_id=domain_id):
                        if (p, a) != demos.CONTRASTIVE and not is_regularity_signature(p):
                            await run(domain_id, p, a)
                else:
                    await run(domain_id, predicate, arity)
            finally:
                await demos.clear_pending(
                    domain_id=domain_id, predicate=predicate, arity=arity, marked=marked)

        return {"drained": len(pending), "induced": induced, "by_domain": by_domain}

    def _judging(self, domain_id: str, predicate: str, arity: int) -> asyncio.Lock:
        """The one judgement of a signature at a time.

        Several paths drain pending induction (the coordinator's coalesced
        drain, a deficit's closure, practice re-inducing), and nothing kept two
        of them off one signature: a judgement that loaded the demonstrations
        before a refusal was recorded validated the rule again after another had
        seen the refusal, and the rule kept its authority with the refusal on
        record (RULE-AUTHORITY-02's live arm: 3 of 227 rules, only with worlds
        running side by side). Taken in turn, each judgement reads what the one
        before it left."""
        locks = self.__dict__.setdefault("_judgement_locks", {})
        return locks.setdefault((domain_id, predicate, arity), asyncio.Lock())

    async def _induce_signature(self, *, domain_id: str, predicate: str,
                                arity: int) -> Dict[str, Any]:
        """Load a signature's demonstrations, judge and re-induce its operator,
        and project an executable one into the concept graph. Off the hot path
        by construction: this is the expensive half."""
        async with self._judging(domain_id, predicate, arity):
            summary, promoted, basis = await self._judge_signature(
                domain_id=domain_id, predicate=predicate, arity=arity)
            if promoted is not None:
                summary["projected_to_concepts"] = await self._project_operator_to_concepts(
                    promoted, basis, domain_id=domain_id)
        return summary

    async def _judge_signature(self, *, domain_id: str, predicate: str,
                               arity: int) -> Tuple[Dict[str, Any], Optional[Any], List]:
        """Everything that decides a signature's authority, and nothing else:
        re-judge the rules it already holds, hold back the latest success and
        failure, induce from the rest, record, validate. Contrastive negatives
        from the whole domain enter the basis.

        Returns the summary, the record now executable (or None) and the basis
        it was induced from. Kept apart from the concept projection so the
        decision can be measured at scale without writing to the concept graph.
        """
        from core.learning.demonstration_store import get_demonstration_store

        rule_kind = predicate.lower()
        demos = get_demonstration_store()
        signature_examples = await demos.load(
            domain_id=domain_id, predicate=predicate, arity=arity)
        contrastive = await demos.load_contrastive(domain_id=domain_id)

        # THE WORLD DEPARTING IS NOT THE RULE BEING WRONG. A miss nothing
        # observed tells apart from the act's successes (`_departures`) refuted
        # the rule it fell under and stayed in every basis after, so in a world
        # where a right act sometimes fails no rule survived and the act was
        # never learned. It is what a regularity's miss already was: it leaves
        # what refutes and what is induced from, and it counts against how often
        # the rule holds (`_relied_on`), which decides its authority. A miss
        # something does tell apart still refutes at once.
        departed = await self._departures(signature_examples, frame=_relevant_frame)
        judged = [e for e in signature_examples if e.evidence_id not in departed]

        # Authority already granted answers to what has been shown since. A rule
        # validated early in a teaching run must not outlive the case that
        # refutes it just because a narrower rule was induced after it.
        for held in await self.store.executable_rules(domain_id=domain_id):
            act = getattr(held.rule, "action", None)
            if act is None or act.predicate != predicate or len(act.args) != arity:
                continue
            try:
                await self.store.rejudge(held, judged)
                if held.status is EpistemicStatus.VALIDATED:
                    reason = (_relied_on(signature_examples, departed)
                              or self._outexplained(held.rule, judged)
                              or await self._unshown_held(held, judged))
                    if reason:
                        await self.store.withhold(held, reason)
            except Exception as e:
                raise_if_structural(e, "unified_learning_system._judge_signature")
                logger.info("re-judgement of %s deferred: %s", held.rule_id, e)

        positives = [e for e in judged if e.positive]
        summary: Dict[str, Any] = {
            "status": "insufficient_evidence",
            "demonstrations": len(signature_examples),
            "contrastive": len(contrastive),
            "positives": len(positives),
            "domain_id": domain_id,
            "signature": f"{predicate}/{arity}",
            "rule_id": None,
            "executable": False,
        }
        if len(positives) < 2:
            return summary, None, []

        # Validation holds back the most recent SUCCESS. Holding back the latest
        # demonstrations whatever they were gave the teachers' rules two failures
        # their bodies did not match, and a case a rule says nothing about cannot
        # confirm it: validation has to see the rule produce its effect.
        #
        # Every failure stays in the basis. Holding the latest one back too was
        # tried and measured (RULE-AUTHORITY-01): it removed the counterexample
        # that forced a precondition into the body, the rule induced without it
        # was refuted by it, and a teaching set that determined the rule ended
        # with no operator. A failure that arrives later is answered by
        # `rejudge`. The basis keeps at least two successes, so with only two
        # nothing is held back and the rule waits, unvalidated, for a third.
        signature_basis = list(judged)
        held_out: List = []
        if sum(1 for e in signature_basis if e.positive) >= 3:
            latest = max(i for i, e in enumerate(signature_basis) if e.positive)
            held_out.append(signature_basis.pop(latest))

        result, basis = await self.induce_bounded(
            signature_basis, contrastive, frame=_relevant_frame, cases=True)
        summary["status"] = result.status.value
        if result.status is not InductionStatus.RULE_LEARNED:
            return summary, None, []
        if result.cases:
            return await self._judge_cases(
                result, basis, held_out, summary, signature_examples=signature_examples,
                departed=departed, domain_id=domain_id, predicate=predicate,
                rule_kind=rule_kind)
        # NOTHING OF A PERSON IS LEFT IN IT (docs/research/SEPARATION_MAP.md
        # §10.2 and §11.6). An operator induced only from people's work, holding a
        # constant every one of them supplied, holds their particulars: it waits
        # for demonstrations that differ there to lift it into a variable, and is
        # not the world's operator before.
        owners = await demos.owners([e.evidence_id for e in basis if e.evidence_id])
        residue = _operator_residue(result.rule, basis, owners)
        if residue:
            summary["status"] = "awaiting_lift"
            summary["residue"] = residue
            return summary, None, []
        acted = getattr(result.rule, "action", None)
        if acted is None or acted.predicate != predicate:
            # NOT THIS ACT'S OPERATOR. The demonstrations were explained without
            # the act: the hypothesis that the effect happens whether or not the
            # substrate acts, which only a still world showing otherwise can
            # refute. A rule that does not name the act cannot be performed, so
            # it is neither recorded as this signature's operator nor reported
            # as one.
            summary["status"] = "effect_without_act"
            summary["detail"] = str(result.rule)
            return summary, None, []
        rival = await self._absent_condition_rival(result.rule, basis)
        if rival:
            summary["status"] = InductionStatus.MULTIPLE_HYPOTHESES.value
            summary["detail"] = rival
            return summary, None, []
        untested = _unshown(result.rule, judged)
        if untested:
            summary["status"] = "awaiting_evidence"
            summary["detail"] = untested
            return summary, None, []

        stored = await self.record(
            result, basis, domain_id=domain_id, rule_kind=rule_kind)
        if not stored:
            return summary, None, []
        record = stored[0]
        summary["rule_id"] = record.rule_id

        unreliable = _relied_on(signature_examples, departed)
        if unreliable:
            summary["detail"] = unreliable
            if record.status is EpistemicStatus.VALIDATED:
                await self.store.withhold(record, unreliable)
        elif held_out:
            try:
                await self.store.validate(record, held_out)
            except Exception as e:
                raise_if_structural(e, "unified_learning_system._judge_signature")
                logger.info("validation of %s deferred: %s", record.rule_id, e)

        promoted = [r for r in await self.store.executable_rules(domain_id=domain_id)
                    if r.rule_id == record.rule_id]
        summary["executable"] = bool(promoted)
        summary["status"] = "operator_executable" if promoted else "operator_candidate"
        return summary, (promoted[0] if promoted else None), basis

    async def _judge_cases(self, result, basis, held_out, summary, *, signature_examples,
                           departed, domain_id: str, predicate: str, rule_kind: str):
        """A rule given as cases (`RuleInducer._by_cases`), judged as one rule is,
        case by case. Each must name the act, hold nothing of a person, and keep
        every condition the successes it explains all held (`_unshown`); each is
        recorded against those successes and every miss, and holds authority once
        a success it was not induced from confirms it: the held-out one now, a
        later one at a later judgement."""
        from core.learning.demonstration_store import get_demonstration_store
        from core.learning.rule_induction import judged_by
        misses = [e for e in basis if not e.positive]
        for rule, group in zip(result.candidates, result.cases):
            acted = getattr(rule, "action", None)
            if acted is None or acted.predicate != predicate:
                summary["status"] = "effect_without_act"
                summary["detail"] = str(rule)
                return summary, None, []
            case_basis = list(group) + misses
            owners = await get_demonstration_store().owners(
                [e.evidence_id for e in case_basis if e.evidence_id])
            residue = _operator_residue(rule, case_basis, owners)
            if residue:
                summary["status"] = "awaiting_lift"
                summary["residue"] = residue
                return summary, None, []
            untested = _unshown(rule, group)
            if untested:
                summary["status"] = "awaiting_evidence"
                summary["detail"] = untested
                return summary, None, []

        records = []
        for rule, group in zip(result.candidates, result.cases):
            stored = await self.record(
                InductionResult(status=InductionStatus.RULE_LEARNED, candidates=[rule],
                                detail=result.detail),
                list(group) + misses, domain_id=domain_id, rule_kind=rule_kind)
            records += stored[:1]
        if not records:
            return summary, None, []
        summary["rule_id"] = records[0].rule_id
        summary["cases"] = [r.rule_id for r in records]

        unreliable = _relied_on(signature_examples, departed)
        if unreliable:
            summary["detail"] = unreliable
            for record in records:
                if record.status is EpistemicStatus.VALIDATED:
                    await self.store.withhold(record, unreliable)
        elif held_out:
            for record in records:
                if judged_by(record.rule, held_out[0]) is not True:
                    continue
                try:
                    await self.store.validate(record, held_out)
                except Exception as e:
                    raise_if_structural(e, "unified_learning_system._judge_cases")
                    logger.info("validation of %s deferred: %s", record.rule_id, e)

        executable = {r.rule_id for r in await self.store.executable_rules(domain_id=domain_id)}
        promoted = [r for r in records if r.rule_id in executable]
        summary["executable"] = bool(promoted)
        summary["status"] = "operator_executable" if promoted else "operator_candidate"
        return summary, (promoted[0] if promoted else None), basis

    # ── REGULARITIES OF THE WORLD ────────────────────────────────────────────
    #
    # What the world does on its own, learned the way an operator is learned
    # from what an act does: from demonstrations, by the same inducer, judged by
    # the same held-out validation. A regularity has no act, so it can never be
    # performed (`REGULARITY_KIND`); what it gives the substrate is something to
    # EXPECT (the predictive intelligence system's world expectations).

    async def record_world_change(self, example, *, domain_id: str,
                                  regularity: Tuple[str, int],
                                  owner: Optional[str] = None,
                                  before_at: Optional[datetime] = None,
                                  after_at: Optional[datetime] = None) -> bool:
        """Keep one change the world made on its own (positive), or one case
        where it did not do what a regularity says and the case is told apart
        from its confirmations (negative), under the regularity's signature.
        Recording only: induction is the drain's (`drain_pending_induction`)."""
        from core.learning.demonstration_store import get_demonstration_store
        return await get_demonstration_store().append(
            example, domain_id=domain_id, owner=owner, regularity=regularity,
            before_at=before_at, after_at=after_at)

    async def _regularity_basis(self, *, domain_id: str, predicate: str, arity: int
                                ) -> List["TrainingExample"]:
        """A kind's changes, and the cases where it was wrong that still are.

        A COUNTER-EXAMPLE IS JUDGED AGAIN as the changes of its kind accumulate.
        A miss told apart from the confirmations was the substrate's mistake on
        what had been seen THEN: with only alice's pdfs moved, erin's left behind
        differed by its sender. Once erin's move too, nothing tells that miss
        apart any more, and it was the world departing, seen in hindsight. Kept as
        a counter-example it contradicted every hypothesis that explained the
        changes, induction found none, and the habit was gone for good (EXPECT-02:
        45 of 47 departures unanswered, four of five such worlds with no
        regularity left). The question is the one `separates` asked when the miss
        happened, put again to everything seen since."""
        from core.learning.demonstration_store import get_demonstration_store
        examples = await get_demonstration_store().load(
            domain_id=domain_id, predicate=predicate, arity=arity)
        departed = await self._departures(examples)
        return [e for e in examples if e.evidence_id not in departed]

    async def _departures(self, examples, frame=lambda basis: basis) -> Set[str]:
        """The misses nothing observed tells apart from the confirmations: the
        world departing from what it does, not the rule being wrong.

        A miss is put to the confirmations it stands among: can a body explain
        all of them and exclude it (`separates`' question)? If none can, and,
        for an act, no condition held in the miss that held in none of the
        confirmations (a condition that must be absent tells it apart as surely
        as one that must hold), nothing observed tells it apart. A regularity
        and an act ask it the same way; an act's demonstrations are cut by its
        frame first, as its induction's are.

        An act's success nothing it held explains departs the other way
        (`_leaks`) and leaves the basis the same way. The misses are then put
        again to the successes without it: it lacked what they need, and kept
        among them it made that look unneeded."""
        departed = await self._misses_departed(examples, frame)
        leaked = _leaks(examples, departed, frame)
        if leaked:
            departed = await self._misses_departed(
                [e for e in examples if e.evidence_id not in leaked], frame)
        return departed | leaked

    async def _misses_departed(self, examples, frame) -> Set[str]:
        """The misses `_departures` finds the world departing in."""
        positives = [e for e in examples if e.positive]
        if len(positives) < 2 or all(e.positive for e in examples):
            return set()
        negatives = [e for e in examples if not e.positive]
        framed = frame(positives + negatives)
        named = lambda e: frozenset(c for c in _conditions(e) if "_" not in c)
        departed: Set[str] = set()
        for index, negative in enumerate(negatives):
            basis = frame(_bounded_basis(positives, ()) + [negative])
            result = await self.induce_on_thread(basis)
            if result.status is not InductionStatus.NO_RULE or not result.negative_coverage:
                continue
            *confirmations, miss = basis
            if miss.action is not None and _conditions(miss) - frozenset().union(
                    *(_conditions(e) for e in confirmations)):
                continue
            # SEEN TO WORK, TWICE, WITH NOTHING THE MISS LACKED. Only then can
            # nothing it lacked explain it. Without this, a world that works on
            # either of two groups of conditions, whose misses lack both, read as
            # noise to rules that cannot say "either" (210 rules in the noisy arm
            # of RULE-AUTHORITY-02 acted where the world refuses); and a near miss
            # beside the one success the world let through where it should not
            # have (a leak) read as noise too, so the leak widened the rule (67
            # of 73 unsafe settled worlds). One such success can be that leak;
            # two are the world working.
            #
            # AND THE WORLD WORKING THERE MORE OFTEN THAN IT REFUSED. Counted
            # alone, two successes outweighed any number of refusals where the
            # same nothing-it-lacked held: the noise leaked twice in one world of
            # RULE-AUTHORITY-02's live arm, the rule dropped the condition both
            # leaks lacked, and when Lyric then acted three times without it and
            # the world refused all three, each refusal read as noise beside the
            # two leaks and the rule kept its authority. What Lyric sees by
            # acting again must be able to outweigh what it saw before. The
            # refusals counted are the ones the successes do not explain: misses
            # that held everything every success held, as this one did.
            #
            # ASKED OF EACH CONDITION THE MISS LACKED, AND OF EACH TWO. Asked of
            # everything it lacked at once, it needed successes lacking all of it
            # together, which a miss lacking four or five conditions almost never
            # has: in the live arm Lyric held no rule in 5 of 7 noisy worlds the
            # evidence settled, with 13 to 24 successes, its noise read as
            # refutation. A world working on either of two groups is caught by
            # the two (no success lacks one condition of each group), a leak by
            # the one (the refusals lacking it outweigh the leaks).
            if miss.action is not None:
                seen, missed = framed[:len(positives)], framed[len(positives) + index]
                held = named(missed)
                core = frozenset.intersection(*(named(e) for e in seen))
                unexplained = [e for e in framed[len(positives):] if core <= named(e)]
                lacked = sorted(frozenset().union(*(named(e) for e in seen)) - held)

                def outweighs(absent: FrozenSet[str]) -> bool:
                    worked = sum(1 for e in seen if not absent & named(e))
                    refused = sum(1 for e in unexplained if not absent & named(e))
                    return worked >= 2 and worked >= refused

                if not all(outweighs(frozenset(pair))
                           for pair in itertools.combinations_with_replacement(lacked, 2)):
                    continue
            departed.add(negative.evidence_id)
        return departed

    async def _absent_condition_rival(self, rule, basis) -> Optional[str]:
        """A structure needing a condition ABSENT that explains this act's
        demonstrations at least as well as `rule` and is no larger than it: the
        evidence does not decide between them, and the rule waits.

        The inducer has no absent condition, so where the world's rule needs one
        it took whatever else held in every success and not in the near miss: a
        relation to some other object (RULE-AUTHORITY-02 world 4313: "TOMATAV(y)
        and y is FEDRA of something" for "TOMATAV(y) and not MIRHI(x)"; 8 of
        1,393 such worlds acted where the world refuses). The causal structure
        (`induce_causal_structure`) has one. It is asked only about what tells
        the demonstrations apart: the rule's own conditions, what held in every
        success, and what held in a miss and in no success, the only conditions
        that could be forbidden."""
        from core.learning.probabilistic_version_space import StructuralHypothesis
        if rule.action is None or rule.absent:
            # A rule that says what must be absent has answered this question.
            return None
        trials = [(_conditions(e), e.positive) for e in basis
                  if e.action is not None and e.action.predicate == rule.action.predicate]
        if not any(ok for _, ok in trials) or all(ok for _, ok in trials):
            return None
        successes = [c for c, ok in trials if ok]
        varies = lambda c: any(c not in t for t, _ in trials)
        required = frozenset(c for c in _rule_conditions(rule) if varies(c))
        forbiddable = frozenset(c for t, ok in trials if not ok for c in t) - frozenset().union(*successes)
        requirable = sorted(c for c in frozenset.intersection(*successes) if varies(c))
        rivals = [StructuralHypothesis(frozenset(r), frozenset(f))
                  for k in range(1, len(required) + 1)
                  for f in itertools.combinations(sorted(forbiddable), k)
                  for j in range(len(required) - k + 1)
                  for r in itertools.combinations(requirable, j)]
        if not rivals:
            return None
        space = self.induce_causal_structure(
            [{"conditions": sorted(t), "outcome": ok} for t, ok in trials],
            hypotheses=[StructuralHypothesis(required, frozenset())] + rivals)
        # ONLY A RULE THAT LEANS ON SOMETHING THE ACT DOES NOT NAME YIELDS. A
        # condition that holds in every success and in no miss can be a
        # coincidence either way, present or absent, and asked of every rule the
        # question withheld 25 of 48 settled conjunction rules for a condition
        # that happened to hold in each miss ("nothing needed, with RINFE(0)
        # absent"). What the act names can bear on it; a relation to something
        # it does not name is what a distractor is (`_relevant_frame`), and each
        # of the 8 rules that acted where the world refuses rested on one.
        unnamed = lambda h: sum("_" in c for c in h.requires | h.forbids)
        posterior = space.posterior()
        mine = space.hypotheses[0]
        for h, p in zip(space.hypotheses[1:], posterior[1:]):
            if p >= posterior[0] and unnamed(h) < unnamed(mine):
                return (f"the evidence explains as well a rule needing "
                        f"{', '.join(sorted(h.requires)) or 'nothing else'} with "
                        f"{', '.join(sorted(h.forbids))} absent")
        return None

    async def _unshown_held(self, held, judged) -> Optional[str]:
        """`_unshown` of a rule already held, asked only where everything it
        was induced from is among the demonstrations judged here. A rule taught
        from demonstrations kept elsewhere would be read against the few acts
        seen since, and a condition holding in all of those would read as one it
        never worked without."""
        from core.learning.rule_store import INDUCTION_ROLES
        roots = await self.store.evidence_roots(held.rule_id, INDUCTION_ROLES)
        if not roots or not roots <= {e.evidence_id for e in judged}:
            return None
        return _unshown(held.rule, judged)

    @staticmethod
    def _outexplained(rule, examples) -> Optional[str]:
        """A held rule some success of its act lies outside, where a structure
        needing a condition ABSENT, no larger than the rule, explains every
        demonstration of the act.

        THE EVIDENCE HAS DECIDED, NOT LEFT IT OPEN. `_absent_condition_rival`
        asks, when a rule is induced, whether such a structure explains the
        demonstrations as well, and yields only for a rule leaning on something
        the act does not name, since a condition among its own things can be a
        coincidence either way. Once a success the rule cannot produce has been
        seen and the absent-condition structure produces every one, it is no
        longer either way: RULE-AUTHORITY-02 world 1168 held "VETO(y, x)" for
        "LUGAHI(y) absent", two successes without VETO did not contradict it,
        induction from everything found no rule, and it kept authority to act
        where the world refuses. Its authority is withheld, not refuted."""
        from core.learning.rule_induction import judged_by
        if rule.action is None:
            return None
        if not any(e.positive and e.action is not None and e.action.predicate == rule.action.predicate
                   and judged_by(rule, e) is not True for e in examples):
            return None
        trials = [(_conditions(e), e.positive) for e in _relevant_frame(list(examples))
                  if e.action is not None and e.action.predicate == rule.action.predicate]
        successes = [c for c, ok in trials if ok]
        if not successes or all(ok for _, ok in trials):
            return None
        varies = lambda c: any(c not in t for t, _ in trials)
        size = sum(1 for c in _rule_conditions(rule) if varies(c))
        forbiddable = sorted(frozenset(c for t, ok in trials if not ok for c in t) - frozenset().union(*successes))
        requirable = sorted(c for c in frozenset.intersection(*successes) if varies(c))
        for k in range(1, size + 1):
            for forbids in itertools.combinations(forbiddable, k):
                for j in range(size - k + 1):
                    for requires in itertools.combinations(requirable, j):
                        if all((set(requires) <= t and not set(forbids) & t) == ok for t, ok in trials):
                            return (f"a success lies outside it, and every demonstration is explained by "
                                    f"{', '.join(requires) or 'nothing else'} with {', '.join(forbids)} absent")
        return None

    async def _judge_regularity(self, *, domain_id: str, predicate: str,
                                arity: int) -> Dict[str, Any]:
        """Re-judge the regularities a signature holds, induce from its
        demonstrations, record and validate: `_judge_signature` for what the
        world does on its own.

        THE DEMONSTRATIONS ARE ALREADY CUT to the thing that changed
        (`world_change_examples`), and validation reads them so cut. An
        operator is validated on the full world because its act is instant and
        everything its body matches should have changed; a regularity takes
        time, and the other things waiting in the same place were not expected
        to have changed yet.

        SEVERAL HYPOTHESES ARE KEPT, not refused. With no act to anchor on, a
        change is often explained equally well by more than one body ("what is
        in the inbox moves", "a pdf moves"). Every one is recorded and validated:
        where they all expect a change it is a commitment, where only some do it
        is a question the world answers (the predictive intelligence system's world expectations)."""
        from core.learning.rule_store import REGULARITY_KIND

        examples = await self._regularity_basis(
            domain_id=domain_id, predicate=predicate, arity=arity)
        summary: Dict[str, Any] = {
            "status": "insufficient_evidence", "demonstrations": len(examples),
            "positives": sum(1 for e in examples if e.positive), "domain_id": domain_id,
            "signature": predicate, "rule_ids": [], "regularities": 0,
        }
        for held in await self.store.expectation_rules(domain_id=domain_id):
            if self._regularity_signature_of(held) == (predicate, arity):
                try:
                    await self.store.rejudge(held, examples)
                except Exception as e:
                    raise_if_structural(e, "unified_learning_system._judge_regularity")
                    logger.info("re-judgement of %s deferred: %s", held.rule_id, e)

        if summary["positives"] < 2:
            return summary
        basis = list(examples)
        held_out: List = []
        if summary["positives"] >= 3:
            latest = max(i for i, e in enumerate(basis) if e.positive)
            held_out.append(basis.pop(latest))

        result, _ = await self.induce_bounded(basis)
        summary["status"] = result.status.value
        if result.status not in (InductionStatus.RULE_LEARNED,
                                 InductionStatus.MULTIPLE_HYPOTHESES) or not result.candidates:
            summary["detail"] = result.detail
            return summary
        if any(c.action is not None for c in result.candidates):
            # Cannot happen from actionless demonstrations; refused rather than
            # filed as a regularity that names an act.
            raise ValueError(f"a regularity of {predicate} was induced with an act in it")

        stored = await self.record(result, basis, domain_id=domain_id, rule_kind=REGULARITY_KIND)
        summary["rule_ids"] = [r.rule_id for r in stored]
        # A HYPOTHESIS THAT NO LONGER EXPLAINS EVERY CHANGE OF ITS KIND is not one
        # of the kind's any more. "A pdf from alice moves", induced while only
        # alice's had moved, is still true of hers once erin's moves too, so
        # nothing refutes it; but it no longer accounts for the kind, and kept
        # beside the hypotheses that do, it made every case outside it a question
        # rather than a commitment, so the world departing there was never
        # answered (EXPECT-02's pilot). It is superseded by what the kind's
        # changes, all of them, are now explained by.
        from core.learning.rule_induction import derives
        positives = [e for e in examples if e.positive]
        for held in await self.store.expectation_rules(domain_id=domain_id):
            if (held.rule_id in summary["rule_ids"]
                    or self._regularity_signature_of(held) != (predicate, arity)
                    or all(derives(held.rule, e) for e in positives)):
                continue
            accounts = [r for r in stored if all(derives(r.rule, e) for e in positives)]
            if accounts:
                await self.store.supersede(held, accounts[0])
                logger.info("regularity %s no longer explains every change of its kind; "
                            "superseded by %s", held.rule_id, accounts[0].rule_id)
        for record in stored:
            if held_out:
                try:
                    await self.store.validate(record, held_out)
                except Exception as e:
                    raise_if_structural(e, "unified_learning_system._judge_regularity")
                    logger.info("validation of %s deferred: %s", record.rule_id, e)
        summary["regularities"] = len([
            r for r in await self.store.expectation_rules(domain_id=domain_id)
            if r.rule_id in summary["rule_ids"]])
        summary["status"] = "regularity_validated" if summary["regularities"] else "regularity_candidate"
        return summary

    @staticmethod
    def _regularity_signature_of(record) -> Tuple[str, int]:
        from core.learning.demonstration_store import regularity_signature
        return regularity_signature(record.rule.effects)

    async def separates(self, record, case: "TrainingExample", *,
                        domain_id: str) -> Optional[bool]:
        """Whether something observed tells `case` -- an unmet expectation, as a
        counter-example (`expectation_case`) -- apart from every change that
        confirmed the regularity: can a body still explain all of them and
        exclude it?

        True: the regularity was too broad, and the substrate was wrong.
        False: no body does; the case is like the confirmations in everything
        observed, and the world did not do what it does. None: the question
        could not be put -- fewer than two confirmations, or an induction that
        settled nothing either way."""
        predicate, arity = self._regularity_signature_of(record)
        positives = [e for e in await self._regularity_basis(
            domain_id=domain_id, predicate=predicate, arity=arity) if e.positive]
        if len(positives) < 2:
            return None
        result = await self.induce_on_thread(_bounded_basis(positives, ()) + [case])
        if result.status in (InductionStatus.RULE_LEARNED,
                             InductionStatus.MULTIPLE_HYPOTHESES) and result.candidates:
            return True
        if result.status is InductionStatus.NO_RULE and result.negative_coverage:
            return False
        return None

    @classmethod
    def regularity_claim(cls, record, domain_id: str) -> str:
        """The claim that a kind of change a world makes on its own can be relied
        on: the habit, in its world, and not one hypothesis about its conditions.

        It was one belief per rule, and the rules of a kind are what the learner
        currently thinks its conditions are: each counter-example that narrowed
        them ("what is in the inbox moves" refuted, "a pdf moves" induced) made a
        new rule, and its belief started from nothing, though every confirmation
        of the old rule was one of the new. Departures went unanswered while it
        caught up (EXPECT-02's pilot). Lyric's own mistakes never move it (only a
        confirmation or the world departing does), so it measures the habit."""
        signature = cls._regularity_signature_of(record)
        return f"the world regularity {signature[0]} holds in {domain_id}"

    async def regularity_belief(self, record, *, domain_id: str,
                                owner: Optional[str]) -> Optional[float]:
        """How far a regularity can be relied on, now: in its owner's context
        for a person's world, in the substrate's own beliefs for its own."""
        claim = self.regularity_claim(record, domain_id)
        if owner:
            from core.learning.scoped_context_store import get_scoped_context_store
            held = await get_scoped_context_store().belief(str(owner), claim)
            return None if held is None else float(held["posterior"])
        belief = self.belief_for_claim(claim)
        return None if belief is None else float(belief.posterior_probability)

    async def regularity_record(self, record, *, domain_id: str) -> Tuple[int, int]:
        """How the kind of change `record` is of has fared in its world, as
        (held, expected): read from how each expectation of it ended, counted as
        its reliability is moved -- a confirmation, or the world departing or
        dealing with the thing otherwise. The substrate's own mistakes, and what
        its own acts left unjudgeable, say nothing about the habit. `domain_id`
        is the world the expectations were held of."""
        from core.agents.memory_agent import memory_agent
        signature = self._regularity_signature_of(record)
        kinds: Dict[str, Optional[Tuple[str, int]]] = {}
        held = expected = 0
        for row in await memory_agent().expectation_outcomes(domain_id=domain_id):
            rule_id = row["rule_id"]
            if rule_id not in kinds:
                rule = await self.store.get(rule_id)
                kinds[rule_id] = self._regularity_signature_of(rule) if rule is not None else None
            if kinds[rule_id] != signature:
                continue
            n = int(row["n"])
            if row["status"] == "confirmed" and row["attribution"] == "rule_evidence":
                held += n
                expected += n
            elif row["status"] == "unmet" and row["attribution"] == "external_failure":
                expected += n
        return held, expected

    async def regularity_relied_on(self, record, *, domain_id: str) -> bool:
        """Whether a person's habit (a kind of change in their world) is relied
        on: shown, by how its expectations ended, to hold at least
        `RELIED_ON_RATE` of the time.

        It was the belief's posterior, settled in favour. That belief is a
        log-odds walk, a fixed step per outcome, and a walk climbs to certainty
        for anything kept more often than not: a step kept three times in four was
        relied on, and every miss answered (316 of 322); one kept every other
        time wandered past the line 45 times in 585 (EXPECT-02). The belief still
        moves with each outcome, as what is held in their context; whether to
        answer for them reads the rate."""
        held, expected = await self.regularity_record(record, domain_id=domain_id)
        return relied_on_rate(held, expected)

    async def observe_regularity(self, record, *, domain_id: str, held: bool, owner: Optional[str],
                                 observation: str, memory_id: Optional[str]) -> Optional[float]:
        """One settled expectation as one witness of whether a regularity can be
        relied on. A person's world is theirs: its regularity's belief is held
        in their context and never in the shared one. Each witness carries the
        weight one outcome of a method does (`COMPETENCE_EVIDENCE_QUALITY`), so
        a regularity is relied on only after several agree, and a departure
        moves it back. Returns the posterior it moved to."""
        from core.integration.universal_domain_master import UniversalDomainMaster
        claim = self.regularity_claim(record, domain_id)
        quality = UniversalDomainMaster.COMPETENCE_EVIDENCE_QUALITY
        if owner:
            from core.learning.scoped_context_store import get_scoped_context_store
            state = await get_scoped_context_store().observe_claim(
                str(owner), claim, domain="regularities", supports=held,
                quality=quality, source="experience")
            return float(state["posterior"]) if state and "posterior" in state else None
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        unc = get_uncertainty_system()
        belief = unc.observe_claim(claim, "regularities", supports=held, quality=quality,
                                   source="experience", observation=observation,
                                   memory_id=memory_id)
        await unc.flush_belief(belief.belief_id)
        return float(belief.posterior_probability)

    async def _project_operator_to_concepts(self, record, basis, *,
                                            domain_id: str) -> bool:
        """Record the operator's induction roots in the concept graph, then
        project the operator itself as a derivative of them, so the operator and
        concept learning systems meet. Never fatal to learning."""
        try:
            from core.domain.concept_ingestion import EvidenceSourceType
            from core.domain.evidence_producers import (
                submit_demonstration, submit_learned_rule)

            # THE ROOTS ARE THE WORLD'S EVIDENCE: the substrate's own
            # demonstrations. A person's is theirs, and is never written into the
            # concept graph as a root; an operator learned from people's work
            # alone is executable and stays out of the concept graph.
            from core.learning.demonstration_store import get_demonstration_store
            owners = await get_demonstration_store().owners(
                [e.evidence_id for e in basis if e.evidence_id])
            roots: List[str] = []
            for example in basis:
                if example.action is None or not example.evidence_id or owners.get(example.evidence_id):
                    continue
                await submit_demonstration(
                    example, domain_id=domain_id,
                    source_type=EvidenceSourceType.TASK_ARTIFACT,
                    producer="operator_learning",
                    source_id=f"{domain_id}:{example.action.predicate}")
                roots.append(example.evidence_id)

            if not roots:
                return False
            await submit_learned_rule(record, roots, producer="operator_learning")
            return True
        except Exception as e:
            raise_if_structural(e, "unified_learning_system._project_operator_to_concepts")
            logger.info("operator->concept projection deferred for %s: %s",
                        getattr(record, "rule_id", "?"), e)
            return False

    def derive_procedure(self, operators, guards, examples, terminal: str = "RESULT",
                         max_rules: Optional[int] = None):
        """Derive a length-general procedure from input/output evidence alone --
        a SECOND ACQUISITION MODE, not a second learner. It can only compose
        operators already learned, so nothing derived here widens what the
        substrate can do -- only what it can do in sequence."""
        from core.learning.procedure_synthesis import (DEFAULT_MAX_RULES,
                                                       derive_procedure)
        return derive_procedure(
            operators, guards, examples, terminal=terminal,
            max_rules=DEFAULT_MAX_RULES if max_rules is None else max_rules)

    def induce_causal_structure(self, observations, hypotheses=None):
        """Learn which conditions gate an outcome, from trials. Owns
        ProbabilisticVersionSpace (the learner EDU-10/EDU-11 measured). Returns
        the fitted version space, or None if the trials are unusable.

        With `hypotheses`, the space holds those structures alone: the rivals a
        question is about (`_absent_condition_rival`), not every structure over
        every condition, which is 3^n of them."""
        from itertools import product

        from core.learning.probabilistic_version_space import (
            ProbabilisticVersionSpace, StructuralHypothesis)

        trials = [o for o in (observations or [])
                  if isinstance(o, dict) and isinstance(o.get("conditions"), (list, tuple))
                  and "outcome" in o]
        if not trials:
            return None
        if hypotheses is not None:
            space = ProbabilisticVersionSpace(hypotheses=list(hypotheses))
            for trial in trials:
                outcome = trial["outcome"]
                space.observe(frozenset(trial["conditions"]), "unknown" if outcome is None
                              else "success" if outcome else "failure")
            return space

        conditions: List[str] = []
        for trial in trials:
            for condition in trial["conditions"]:
                if condition not in conditions:
                    conditions.append(condition)
        conditions.sort()
        if not conditions:
            return None

        space = ProbabilisticVersionSpace(hypotheses=[
            StructuralHypothesis(
                frozenset(c for c, a in zip(conditions, assignment) if a == 1),
                frozenset(c for c, a in zip(conditions, assignment) if a == 2))
            for assignment in product((0, 1, 2), repeat=len(conditions))])

        for trial in trials:
            outcome = trial["outcome"]
            if outcome is None:
                space.observe(frozenset(trial["conditions"]), "unknown")
            else:
                space.observe(frozenset(trial["conditions"]),
                              "success" if outcome else "failure")
        return space

    def induce_sequence_rule(self, terms):
        """Learn the rule behind a numeric sequence, and what comes next.
        Delegates to RuleInducer (no second numeric learner). Returns
        (InductionResult, next_value); next_value is None whenever the induced
        rule does not determine one (MULTIPLE_HYPOTHESES is a real answer)."""
        from core.learning.rule_induction import (Fact, InductionStatus,
                                                  TrainingExample,
                                                  arithmetic_background,
                                                  canonical_term, is_number)
        from core.reasoning.unification import match_body

        values = [canonical_term(str(t)) for t in (terms or [])]
        if len(values) < 3 or not all(is_number(v) for v in values):
            return None, None

        examples = []
        for before, after in zip(values, values[1:]):
            background = tuple(arithmetic_background([before, after]))
            examples.append(TrainingExample(
                before=(Fact("CURRENT", (before,)), Fact("ADVANCE", ())) + background,
                action=Fact("ADVANCE", ()),
                after=(Fact("CURRENT", (after,)),) + background,
                positive=True))
            wrong = canonical_term(str(float(after) + 1))
            examples.append(TrainingExample(
                before=(Fact("CURRENT", (before,)), Fact("ADVANCE", ()))
                       + tuple(arithmetic_background([before, wrong])),
                action=Fact("ADVANCE", ()),
                after=(Fact("CURRENT", (after,)),),
                positive=False))

        result = self.inducer.induce(examples)
        if result.status is not InductionStatus.RULE_LEARNED or not result.rule:
            return result, None

        last = values[-1]
        state = set(arithmetic_background([last])) | {
            Fact("CURRENT", (last,)), Fact("ADVANCE", ())}
        for literal in result.rule.body:
            if literal.predicate in ("PLUS", "TIMES") and len(literal.args) == 3:
                step = literal.args[1]
                if not is_number(step):
                    continue
                base, factor = float(last), float(step)
                nxt = base + factor if literal.predicate == "PLUS" else base * factor
                state.add(Fact(literal.predicate,
                               (last, step, canonical_term(str(nxt)))))

        for bindings in match_body(result.rule.body, frozenset(state)):
            for effect in result.rule.effects.substitute(bindings).add:
                if effect.predicate == "CURRENT" and effect.is_ground:
                    return result, effect.args[0]
        return result, None

    # ---- the contribution boundary --------------------------------------

    async def contribute(self, contribution: "Contribution") -> "Admission":
        """Admit a proposal -- as a CANDIDATE carrying no evidence, or not at
        all. A rejected contribution is not an error; declining is the common
        case. What must never happen is a contribution arriving with any status
        other than CANDIDATE."""
        if contribution.contributor not in self._contributors:
            admission = Admission(
                False, "contributor is not registered; a proposal with no "
                       "traceable origin cannot be admitted",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        if contribution.kind is not ContributionKind.HYPOTHESIS:
            admission = Admission(
                True, "accepted as a proposal; not stored as knowledge",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        rule = contribution.payload
        if not isinstance(rule, CandidateRule):
            admission = Admission(
                False, f"hypothesis payload is {type(rule).__name__}, not a CandidateRule",
                contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        try:
            stored = await self.store.record_induction(
                rule,
                domain_id=contribution.domain_id or "unassigned",
                evidence_ids=[],
            )
        except Exception as e:
            raise_if_structural(e, "unified_learning_system.contribute")
            admission = Admission(False, f"could not record proposal: {e}",
                                  contribution.contributor, contribution.kind)
            self._admissions.append(admission)
            return admission

        admission = Admission(
            True, "admitted as CANDIDATE with no evidence roots",
            contribution.contributor, contribution.kind,
            status=EpistemicStatus.CANDIDATE,
            rule_id=getattr(stored, "rule_id", None))
        self._admissions.append(admission)
        return admission

    async def admit_projection(self, projection, *, contributor: str,
                               rule_kind: str = "projected") -> "Admission":
        """Admit an analogically-projected operator through the ONE boundary.

        A projection is a HYPOTHESIS like any other contribution -- analogy
        proposes, only target-domain evidence attests -- so it enters as a
        CANDIDATE with zero evidence roots and cannot reach executable authority
        except through `validate()`. It gets its own entry point rather than
        going through `contribute()` for one reason: `record_projection` also
        writes the element-level provenance (`rule_projections`) that lets a
        later contradiction be blamed on the specific correspondence that was
        wrong. A bare CandidateRule contribution would drop that, so the
        authority delegates to the projection recorder while still enforcing the
        same rule it enforces for contribute(): the proposer must be registered,
        and nothing arrives above CANDIDATE.
        """
        if contributor not in self._contributors:
            admission = Admission(
                False, "contributor is not registered; a projection with no "
                       "traceable origin cannot be admitted",
                contributor, ContributionKind.HYPOTHESIS)
            self._admissions.append(admission)
            return admission

        if not getattr(projection, "is_proposable", False):
            admission = Admission(
                False, f"{getattr(projection, 'outcome', '?')} is not proposable; "
                       "a partial operator would be tested and the world's answer "
                       "attributed to a rule the analogy never claimed",
                contributor, ContributionKind.HYPOTHESIS)
            self._admissions.append(admission)
            return admission

        try:
            stored = await self.store.record_projection(projection, rule_kind=rule_kind)
        except Exception as e:
            raise_if_structural(e, "unified_learning_system.admit_projection")
            admission = Admission(False, f"could not record projection: {e}",
                                  contributor, ContributionKind.HYPOTHESIS)
            self._admissions.append(admission)
            return admission

        admission = Admission(
            True, "projection admitted as CANDIDATE with no evidence roots",
            contributor, ContributionKind.HYPOTHESIS,
            status=EpistemicStatus.CANDIDATE,
            rule_id=getattr(stored, "rule_id", None))
        self._admissions.append(admission)
        return admission

    @property
    def admissions(self) -> List["Admission"]:
        """The full record, accepted and rejected alike."""
        return list(self._admissions)

    async def rules(self, domain_id: Optional[str] = None):
        return await self.store.load(domain_id=domain_id)

    async def metrics(self) -> Dict[str, Any]:
        accepted = [a for a in self._admissions if a.accepted]
        return {
            "contributors": self.contributors,
            "contributions_seen": len(self._admissions),
            "contributions_accepted": len(accepted),
            "contributions_promoted_to_knowledge": sum(
                1 for a in accepted if a.is_knowledge),
        }

    async def shutdown(self) -> Dict[str, Any]:
        """Lifecycle teardown: finish what this authority has in flight and
        persist what only it holds, before the database pool closes.

          * event-driven learning (`learn_from_event` hands work to tasks) is
            drained, so an in-flight outcome is not abandoned mid-write;
          * trained clause classifiers are persisted (main.py used to do this
            itself, reaching past the authority that owns them).

        Beliefs, rules and demonstrations are persisted by their own stores as
        they are written. Returns what was done."""
        report = {"event_learning": await self.drain_events(),
                  "classifiers_saved": await self.save_classifiers()}
        logger.info("learning authority shut down: %s", report)
        return report


# Singleton instance
_unified_learning_system = None


def get_unified_learning_system() -> UnifiedLearningSystem:
    """Get global unified learning system instance (singleton)"""
    global _unified_learning_system
    if _unified_learning_system is None:
        _unified_learning_system = UnifiedLearningSystem()
    return _unified_learning_system


def get_learning_authority() -> UnifiedLearningSystem:
    """The one learning authority. `UnifiedLearningSystem` IS the authority now
    (the model-free ILearningAuthority implementation was folded into this class
    and learning_authority.py deleted), so this and `get_unified_learning_system`
    return the same object."""
    return get_unified_learning_system()


# =============================================================================
# WATCHING AN ACT: THE WORLD BEFORE IT AND AFTER IT, FILED AS A DEMONSTRATION
# =============================================================================



#: (domain_id, predicate, arity) -> the predicates that were observed to change.
#: Memoised because it is read before every act; refreshed when that signature
#: gains a demonstration (`note_demonstration`).
_DISCRIMINATING: Dict[Tuple[str, str, int], FrozenSet[str]] = {}


def note_demonstration(domain_id: str, predicate: str, arity: int) -> None:
    """Forget the memo for a signature that just gained evidence, so the next
    act re-reads what discriminates instead of trusting a stale answer."""
    _DISCRIMINATING.pop((domain_id, predicate, arity), None)


async def discriminating_predicates(domain_id: str, predicate: str,
                                    arity: int) -> FrozenSet[str]:
    """Which predicates this operator was OBSERVED to move.

    THE FRAME IS LEARNED, NOT CHOSEN. Pointed at a file, 14 of 19 observations
    answer -- `find_dead_code`, `find_todos`, `trace_dependencies` and
    `security_scan` all report happily on a file that was moved, and none of it
    is what the move did. Keeping all of them would put the induction back where
    an unscoped generalisation retained 4098 literals and the suite stopped
    finishing.

    So an observation earns its place in the frame by having reported something
    that CHANGED when this operator ran. That is read from the demonstrations
    already stored for the signature, which is why it survives a restart with no
    table of its own: the evidence is the calibration.

    Empty while a signature has no demonstrations yet -- the bootstrap, where
    the substrate watches everything it can once in order to find out what is
    worth watching.
    """
    key = (domain_id, predicate, arity)
    memo = _DISCRIMINATING.get(key)
    if memo is not None:
        return memo

    from core.learning.demonstration_store import get_demonstration_store
    try:
        examples = await get_demonstration_store().load(
            domain_id=domain_id, predicate=predicate, arity=arity)
    except Exception as e:
        # An unreadable store is not an empty one. Returning "nothing
        # discriminates" would silently narrow every future frame to nothing.
        logger.warning("could not read demonstrations for %s/%d in %s: %s",
                       predicate, arity, domain_id, e)
        return frozenset()

    moved: set = set()
    for example in examples:
        before = {f.predicate for f in example.before}
        after = {f.predicate for f in example.after}
        moved |= before ^ after
        # A predicate present on both sides may still have MOVED -- the same
        # relation about different arguments. Compared as whole facts, not as
        # bare names, or a rename inside one predicate reads as no change.
        moved |= {f.predicate for f in set(example.before) ^ set(example.after)}

    result = frozenset(moved)
    _DISCRIMINATING[key] = result
    return result


class ActFrame:
    """The world one act touches, read before it and again after it.

    This is the before/action/after triple for an act nobody planned, in a
    domain nobody declared. It is opened from the call's own arguments, so the
    substrate can watch itself do something it has never done, in an environment
    it was never told about.

    THE SAME QUESTIONS BOTH TIMES. The readings are fixed when the frame opens
    and re-run unchanged when it closes. A frame that asked different questions
    either side of the act would report the difference between two questions as
    an effect of the act.
    """

    def __init__(self, *, tool_name: str, action: Fact, domain_id: str,
                 readings: List[Tuple[str, str, str]],
                 before: Dict[Tuple[str, str], Optional[FrozenSet[Fact]]]) -> None:
        self.tool_name = tool_name
        self.action = action
        self.domain_id = domain_id
        self._readings = readings
        self._before = before

    @classmethod
    async def open(cls, tool_name: str,
                   parameters: Dict[str, Any]) -> Optional["ActFrame"]:
        """Read the world this call is about to touch, or decline to watch.

        Declines (None), never guesses, when:
          - the tool is not registered, or declares no typed parameters;
          - no argument names anything the substrate can look at, so there is
            no world here to have a before and an after;
          - nothing could be read at all, which is not the same as an empty
            world and must not be planned or learned from as if it were.
        """
        from core.perception.perception_faculty import SELF_SENSE, _senses, identity, observe_resources, observer_index, resource_kind
        from core.tools.tool_registry import ACTING_CLASSES, derived_domain_id, payload_parameters, payload_term, predicate_for, resource_parameters
        from core.agents.autonomous.autonomous_coordinator import classify_action
        from core.tools import get_tool_registry

        tool = get_tool_registry().get_tool(tool_name)
        if tool is None:
            return None

        # ONLY AN ACT HAS AN EFFECT TO LEARN. An investigation changes nothing,
        # so watching one would spend two readings to observe that the world
        # stayed as it was -- and would file that as a demonstration that the
        # investigation does nothing, which is true and useless.
        try:
            action_class, _ = classify_action(tool_name, parameters or {})
        except Exception as e:
            logger.debug("%s could not be classified; not watching it: %s",
                         tool_name, e)
            return None
        if getattr(action_class, "value", str(action_class)) not in ACTING_CLASSES:
            return None

        resources: List[Tuple[str, str]] = []
        for parameter in resource_parameters(tool):
            value = parameters.get(parameter.name)
            if isinstance(value, str) and value.strip():
                kind = resource_kind(parameter.name)
                resources.append((kind, identity(kind, value)))
        if not resources:
            return None

        # WHAT THE ACT WAS ASKED TO PUT INTO THE WORLD follows the places it
        # names, as the payload's fingerprint, so the act and the self's reading
        # of the file can be compared (`payload_term`). Not a resource: nothing
        # here looks at it, and it adds no kind to the domain.
        payloads = [payload_term(parameters.get(p.name)) for p in payload_parameters(tool)]
        action = Fact(predicate_for(tool_name),
                      tuple(as_constant(value) for _kind, value in resources)
                      + tuple(as_constant(digest) for digest in payloads))
        domain_id = derived_domain_id(kind for kind, _ in resources)

        # A kind the self senses is read by that sense alone; any other kind by
        # the tools that can be pointed at it.
        senses = _senses()
        index = observer_index()
        candidates: List[Tuple[str, str, str]] = []
        for kind, value in resources:
            if kind in senses:
                candidates.append((SELF_SENSE, kind, value))
            else:
                candidates.extend((observer, parameter, value)
                                  for observer, parameter in index.get(kind, ()))
        readings = await cls._earned(domain_id, action, candidates)
        if not readings:
            return None

        before = await observe_resources(readings)
        if all(facts is None for facts in before.values()):
            logger.info("%s: the world could not be read before acting; "
                        "not watching this act", tool_name)
            return None
        return cls(tool_name=tool_name, action=action, domain_id=domain_id,
                   readings=readings, before=before)

    @staticmethod
    async def _earned(domain_id: str, action: Fact,
                      candidates: List[Tuple[str, str, str]]
                      ) -> List[Tuple[str, str, str]]:
        """Narrow the candidates to the observations that have EARNED a place.

        An observation earns it by having reported something this operator was
        seen to move. Until that is known -- a signature with no demonstrations,
        or a process that has not yet learned which observation produces which
        predicate -- everything pointable is read, which is the bootstrap that
        produces the evidence the narrowing is made of.

        NARROWED BY OBSERVATION, NOT BY FACT. A discriminating observation is
        one watching the right ASPECT of the world; its UNCHANGED facts are
        exactly the preconditions. Keeping only facts that moved would throw the
        preconditions away and leave an operator that names its effects and
        nothing it needs.
        """
        from core.perception.perception_faculty import SELF_SENSE, _OBSERVER_PREDICATES
        discriminating = await discriminating_predicates(
            domain_id, action.predicate, action.arity)
        if not discriminating:
            return candidates
        earned = [observer for observer, produced in _OBSERVER_PREDICATES.items()
                  if produced & discriminating]
        if not earned:
            return candidates
        narrowed = [c for c in candidates if c[0] == SELF_SENSE or c[0] in earned]
        return narrowed or candidates

    async def close(self) -> Optional[Tuple[FrozenSet[Fact], FrozenSet[Fact]]]:
        """Re-read the world and return (before, after) over the readings that
        answered BOTH times.

        A reading that did not complete on either side is dropped from both,
        because an unknown is not a state and the difference between a known and
        an unknown is not an effect. Returns None when nothing survives -- the
        world was not legible around this act, and `_record_execution_
        demonstration` already refuses to file a demonstration in that case.
        """
        from core.perception.perception_faculty import observe_resources
        after = await observe_resources(self._readings)
        agreed = [key for key, facts in after.items()
                  if facts is not None and self._before.get(key) is not None]
        if not agreed:
            logger.info("%s: no reading answered both before and after; "
                        "nothing observed about this act", self.tool_name)
            return None

        before_facts: set = set()
        after_facts: set = set()
        for key in agreed:
            before_facts |= self._before[key]
            after_facts |= after[key]
        return frozenset(before_facts), frozenset(after_facts)


async def domain_discriminating(domain_id: str) -> FrozenSet[str]:
    """Every predicate any operator of this domain was observed to move."""
    from core.learning.demonstration_store import get_demonstration_store

    demos = get_demonstration_store()
    try:
        signatures = await demos.signatures(domain_id=domain_id)
    except Exception as e:
        logger.warning("could not read the signatures of %s: %s", domain_id, e)
        return frozenset()
    moved: set = set()
    for predicate, arity in signatures:
        if (predicate, arity) == demos.CONTRASTIVE:
            continue
        moved |= await discriminating_predicates(domain_id, predicate, arity)
    return frozenset(moved)


async def refresh_earned(domain_id: str) -> FrozenSet[str]:
    """Recompute which observations this domain's world is worth reading through.

    Called after a demonstration is filed -- new evidence can only be turned
    into a narrower world from a context that can reach the store.
    """
    from core.perception.perception_faculty import _EARNED_OBSERVERS, _OBSERVER_PREDICATES
    moved = await domain_discriminating(domain_id)
    earned = frozenset(observer for observer, produced
                       in _OBSERVER_PREDICATES.items() if produced & moved)
    if earned:
        _EARNED_OBSERVERS[domain_id] = earned
    else:
        _EARNED_OBSERVERS.pop(domain_id, None)
    return earned


# =============================================================================
# METHODS LIFTED FROM TASKS
# =============================================================================
#
# MEMORY_AGENT_MAP §10.2, SEPARATION_MAP §11.4. A method that worked for one
# person is world knowledge once nothing of that person is left in it; a
# person's design and content stay theirs. These are the pure parts of that, no
# store and no belief; the memory agent keeps what they produce (`_lift`).
#
#   shape         what a method does, whoever it was done for: its steps'
#                 tools, in order, each with the names of the arguments it was
#                 given.
#   facts         the method as logic atoms, one per step: the tool's own name,
#                 upper-cased (`tool_registry.predicate_for`), over its argument
#                 values encoded as constants (`rule_induction.as_constant`).
#   vocabulary    the values a method gives its tools that are the tools' own
#                 words, so no one's particular.
#   lift_one      the first task of a shape that worked, as a method: every
#                 value not kept becomes a variable.
#   generalizing  two methods of one shape, anti-unified
#                 (`rule_induction.generalize_sequence`).
#   residue       the constants a generalization keeps whose only source is
#                 people's material (`person_residue`): such a term makes the
#                 lesson theirs.

#: Punctuation a word carries at its edges in a sentence: "report.txt." is the
#: word report.txt at the end of a sentence.
_EDGE_PUNCTUATION = ".,;:!?\"'()[]{}"


def value_text(value: Any) -> str:
    """An argument's value as the text a constant encodes. A structured value is
    its canonical JSON, so two equal structures are one constant."""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _method_steps(method: Any) -> Optional[List[Tuple[str, Dict[str, Any]]]]:
    """A method's steps as (tool, arguments), or None when it is not a method:
    no steps, or a step that names no tool."""
    if not isinstance(method, list) or not method:
        return None
    steps = []
    for step in method:
        if not isinstance(step, dict) or not step.get("tool"):
            return None
        args = step.get("args") or {}
        if not isinstance(args, dict):
            return None
        steps.append((str(step["tool"]), args))
    return steps


def shape_of(method: Any) -> Optional[str]:
    """What the method does, whoever it was done for, or None if it is not one."""
    from core.tools.tool_registry import predicate_for
    steps = _method_steps(method)
    if steps is None:
        return None
    return "|".join(f"{predicate_for(tool)}({','.join(sorted(args))})" for tool, args in steps)


def method_facts(method: Any) -> Optional[List[Fact]]:
    """The method as ground facts, one per step, arguments in name order."""
    from core.tools.tool_registry import predicate_for
    from core.learning.rule_induction import as_constant
    steps = _method_steps(method)
    if steps is None:
        return None
    return [Fact(predicate_for(tool), tuple(as_constant(value_text(args[name])) for name in sorted(args)))
            for tool, args in steps]


def vocabulary(method: Any, declared: Callable[[str], Dict[str, Any]]) -> Set[str]:
    """The values a method gives its tools that are the tools' own words, so no
    one's particular: a truth value given to an argument the tool declares
    boolean, or one of the values it declares the argument takes (`enum`).
    `declared(tool)` gives a tool's declared parameters by name."""
    words: Set[str] = set()
    for tool, args in _method_steps(method) or []:
        params = declared(tool)
        for name, value in args.items():
            param = params.get(name)
            if param is None:
                continue
            boolean = str(getattr(param, "type", "")).lower() == "boolean" and isinstance(value, bool)
            if boolean or value in (getattr(param, "enum", None) or ()):
                words.add(value_text(value))
    return words


def lift_one(facts: Sequence[Fact], kept: Set[str]) -> List[Fact]:
    """One task's method, lifted: every value not in `kept` (values as text,
    `value_text`) becomes a variable, the same value the same variable
    everywhere, numbered as `generalize` numbers them, so a later task is an
    instance of it exactly when `is_instance` says so."""
    from core.learning.rule_induction import from_constant
    from core.reasoning.unification import VARIABLE_PREFIX, is_variable
    named: Dict[str, str] = {}
    lifted = []
    for fact in facts:
        args = []
        for arg in fact.args:
            if is_variable(arg) or from_constant(arg) in kept:
                args.append(arg)
            else:
                args.append(named.setdefault(arg, f"{VARIABLE_PREFIX}V{len(named)}"))
        lifted.append(Fact(fact.predicate, tuple(args)))
    return lifted


def person_terms(parts: Iterable[Dict[str, Any]], *also: str) -> Set[str]:
    """Every value a person supplied in an experience: each text in the parts
    that came from the person, whole and word by word, and any further texts
    given (`also`, the request that started the work)."""
    texts: List[str] = list(also)

    def walk(value: Any) -> None:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif value is not None:
            texts.append(str(value))

    for part in parts:
        if isinstance(part, dict) and part.get("source") == "person":
            walk(part.get("content"))
    terms: Set[str] = set()
    for text in texts:
        if not text:
            continue
        terms.add(text)
        for word in text.split():
            stripped = word.strip(_EDGE_PUNCTUATION)
            if stripped:
                terms.add(stripped)
    return terms


def person_residue(kept: Iterable[str], instances: Sequence[Optional[set]]) -> List[str]:
    """The kept constants whose only source is people's material: the one rule
    for operators induced from demonstrations (`_operator_residue`) and for
    methods lifted from tasks.

    `instances` holds, for each case the knowledge was learned from, the values
    its person supplied, or None when the case was the substrate's own work. A
    constant is a person's only when every case was a person's work and each of
    them supplied it: if the substrate's own work used the same value, or any
    person's work used it without that person supplying it, it has a source that
    is not a person. Such a constant makes what was learned theirs."""
    if not instances or any(terms is None for terms in instances):
        return []
    return sorted(value for value in set(kept) if all(value in terms for terms in instances))
