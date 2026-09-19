#!/usr/bin/env python3
"""Naming an instance from the rules the substrate induced — the ONE authority.

The substrate could already recognise things and did not, and the reason was not
a missing mechanism. It holds induced classification rules (`circle(?X) ∧
vivid_red(?X) → stopsign(?X)`), it holds the features it measured off the pixels,
and asked "is this blob a stopsign?" it answers correctly. Nothing ever asked.
Recognition existed as a question-answering capability and not as a consequence
of seeing, so sight produced structure and no name — the same shape of gap as
having to switch your eyes on.

So this module holds the decision, and BOTH callers use it:

  * the reasoner, answering a question about one named category
    (`_answer_over_induced_rules`), and
  * sight, naming what it just saw without being asked (`Coordinator.see`).

Writing the sweep separately would have made two authorities for one judgement,
and they would have drifted — the version-space discipline below is exactly the
kind of rule that gets reimplemented slightly wrong.

WHAT IS AND IS NOT A NAMING RULE. A rule NAMES when it concludes a category OF AN
INSTANCE, which is what `induce_category` records as `rule_kind="classification"`.
An action rule such as ` → TEXT(?X0) ⟨?X0 := READ()⟩` also has an `add` effect
and no preconditions, because its variable is bound by the ACTION's output rather
than by matching an instance. Swept in as a naming rule it is vacuously true and
names everything ever seen `TEXT`. The kind is the discriminator, and it is
recorded at induction — this does not re-derive it from the rule's shape.

AGREEMENT. Induction keeps every surviving hypothesis on purpose: the store holds
a version space that a later demonstration collapses. So a category whose
hypotheses disagree about THIS instance names nothing, and says which
demonstration would decide it. Grouping is by (domain, category): two domains
that happen to use one category word are not one version space, and two
categories induced in one domain are not either.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.learning.rule_induction import (Fact, TrainingExample, applies,
                                          predicate_name)

logger = logging.getLogger(__name__)

#: The rule_kind `induce_category` records. A rule of any other kind concludes
#: something other than "this instance is a category" and is not swept.
NAMING_RULE_KIND = "classification"

#: How much a name is worth by how validated the rule behind it is. These are the
#: same numbers the reasoner answered questions with, kept here so one change
#: moves both.
_CONFIDENCE: Dict[str, float] = {"validated": 0.9, "supported": 0.8,
                                 "candidate": 0.7}
_RANK: Dict[str, int] = {"validated": 3, "supported": 2, "candidate": 1}
_REFUTED = "refuted"


@dataclass(frozen=True)
class Naming:
    """A name the substrate is licensed to give this instance, and what licensed
    it. The derivation travels WITH the name: a recognition that cannot say why
    is not defensible, and the substrate has to be able to show its evidence."""

    category: str
    domain: str
    confidence: float
    status: str
    #: The rule body that fired, rendered ("circle & vivid_red"), so the name can
    #: be explained without going back to the store.
    body: str
    rule_id: str
    #: Every hypothesis in this version space agreed. Kept explicit because the
    #: count is the strength of the licence, not decoration.
    hypotheses: int


@dataclass(frozen=True)
class Undetermined:
    """A category whose hypotheses DISAGREE about this instance. Not a name and
    not silence: this instance is precisely the demonstration that would collapse
    the version space, which is worth reporting rather than guessing at."""

    category: str
    domain: str
    firing: int
    hypotheses: int
    #: The bodies that did NOT fire — what the instance would have to have.
    silent: Tuple[str, ...]
    #: The strongest status in this version space. Carried for the same reason
    #: `Naming` carries one: a caller choosing between spaces ranks them by how
    #: validated they are, and a disagreeing VALIDATED space outranks a clean
    #: CANDIDATE one.
    status: str = ""


@dataclass(frozen=True)
class NamingReading:
    """What the induced rules say about one instance. `names` may be empty, and
    empty is an answer: the substrate has no rule that licenses a name here."""

    subject: str
    features: Tuple[str, ...]
    names: Tuple[Naming, ...] = ()
    undetermined: Tuple[Undetermined, ...] = ()
    #: How many naming rules were weighed. Separates "nothing fired" from
    #: "nothing was there to fire" — a substrate that has learned no categories
    #: yet is not the same as one that looked and declined.
    considered: int = 0

    @property
    def named(self) -> bool:
        return bool(self.names)


def _body(rule: Any) -> str:
    return " & ".join(sorted(f.predicate for f in rule.preconditions))


def _status(stored: Any) -> str:
    return str(getattr(getattr(stored, "status", None), "value", ""))


def _rank_of(stored: Any) -> int:
    return _RANK.get(_status(stored), 0)


def rank(status: str) -> int:
    """How validated a status is, for a caller choosing between version spaces.
    Exposed so the ordering lives in one place rather than being re-tabulated."""
    return _RANK.get(str(status), 0)


def naming_rules(stored: Iterable[Any], *, category: Optional[str] = None
                 ) -> List[Any]:
    """The stored rules that NAME an instance — classification kind, not refuted,
    and concluding `category` when one is asked for.

    A rule is found by what it CONCLUDES, not by the domain it was filed under:
    the question names a category, not a domain, and a rule induced in one domain
    legitimately names an instance perceived in another."""
    want = predicate_name(category) if category else None
    out: List[Any] = []
    for s in stored:
        if getattr(s, "rule_kind", None) != NAMING_RULE_KIND:
            continue
        if str(getattr(getattr(s, "status", None), "value", "")) == _REFUTED:
            continue
        adds = getattr(getattr(s.rule, "effects", None), "add", ()) or ()
        if not adds:
            continue
        if want is not None and not any(f.predicate == want for f in adds):
            continue
        out.append(s)
    return out


def read_names(subject: str, features: Sequence[str], stored: Iterable[Any], *,
               category: Optional[str] = None) -> NamingReading:
    """Which categories these features license for `subject`, under agreement.

    `features` are the instance's own atomic predicates as the concept graph
    holds them (`instance_predicates`) — what was measured, not what is being
    claimed. `stored` is the rule store's loaded rules; the caller loads them
    because the caller knows how often it can afford to.

    With `category` given this decides that one category (the reasoner's
    question). With it omitted this sweeps every category the substrate has
    induced a rule for — which is recognition: "what is this?" rather than "is
    this a Y?". The judgement is identical in both cases; only the candidate set
    differs, so the answer to a question and the name that arrives with a
    sighting can never disagree."""
    feats = [p for p in (predicate_name(f) for f in features) if p]
    rules = naming_rules(stored, category=category)
    if not feats or not rules:
        return NamingReading(subject=str(subject), features=tuple(feats),
                             considered=len(rules))

    example = TrainingExample(before=tuple(Fact(p, (str(subject),)) for p in feats))

    # Grouped into VERSION SPACES: one (domain, category) is one space, and the
    # hypotheses within it must agree before anything is named.
    spaces: Dict[Tuple[str, str], List[Any]] = {}
    for s in rules:
        for f in s.rule.effects.add:
            spaces.setdefault((str(s.domain_id or ""), str(f.predicate)), []).append(s)

    names: List[Naming] = []
    undetermined: List[Undetermined] = []
    for (domain, cat), group in spaces.items():
        goal = Fact(cat, (str(subject),))
        firing = [s for s in group
                  if goal in {f for inst in applies(s.rule, example) for f in inst.add}]
        if not firing:
            continue
        if len(firing) != len(group):
            undetermined.append(Undetermined(
                category=cat, domain=domain, firing=len(firing),
                hypotheses=len(group),
                silent=tuple(sorted(_body(s.rule) for s in group
                                    if s not in firing)),
                status=_status(max(group, key=_rank_of))))
            continue
        # Licensed by every hypothesis in the space. The STRONGEST of them sets
        # the confidence and is cited as the derivation — the weakest agreeing
        # would understate a licence that all of them grant.
        best = max(firing, key=_rank_of)
        status = _status(best)
        names.append(Naming(
            category=cat, domain=domain,
            confidence=_CONFIDENCE.get(status, 0.7), status=status,
            body=_body(best.rule), rule_id=str(getattr(best, "rule_id", "")),
            hypotheses=len(group)))

    names.sort(key=lambda n: (-n.confidence, n.category))
    undetermined.sort(key=lambda u: u.category)
    return NamingReading(subject=str(subject), features=tuple(feats),
                         names=tuple(names), undetermined=tuple(undetermined),
                         considered=len(rules))
