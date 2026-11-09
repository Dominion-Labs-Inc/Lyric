#!/usr/bin/env python3
"""Readings learned from what the substrate was taught: sentences and their meanings, and the constructions
found between them.

A CONSTRUCTION is one way English pairs a form with a meaning. There are three kinds (Doumen, Beuls & Van Eecke,
Royal Society Open Science 11:231998, 2024):

  holophrase    a whole sentence and its whole meaning: "This is my shoe."
  item-based    a sentence with open places, and a meaning with a variable for each: "This is my ?slot0."
                means that the shown thing is a ?slot0 and is the speaker's
  lexical       what fills an open place: "shoe", which puts the concept `shoe` where the variable was

A LINK joins an item-based construction's open place (a slot) to a lexical construction that may fill it. A filler
fits a slot only through a link, and the links are what the grammar's categories are: the fillers linked to the
same slots are one kind of word, found from use, never told.

READING a sentence finds the combinations of constructions that cover it: a holophrase on its own, or an item-based
construction with a filler in every slot. SPEAKING a meaning finds the same the other way. Where more than one
combination fits, the one whose constructions score highest on average wins, and different meanings are all
reported, never resolved here. Reading never writes anything.

What may stand in a slot, from the most certain to the least, and a reading is only as good as its least certain
filler:
  linked        a filler linked to that slot.
  same kind     a held filler of the same learned kind as a filler linked to that slot: the paper links a filler to a
                slot at test time, and the kind is what licenses it. The link is proposed, never written.
  new           words no held construction covers, taken as a new concept named by those words, as a child takes a
                new word into a frame it knows. A frame's own words are what anchor such a reading, so a reading
                takes no more new words than its frame has words of its own; words past the store's limit on a term
                are not a name, a new name is no longer than the longest filler the slot's kind has held, and a run
                of several words is not one name when it holds a structure word: a word held constructions use as
                part of a frame and never as a filler on its own.
  loose         when nothing reads as written: letter case folded, a frame's marks allowed to be missing, and a
                final mark set aside, since heard speech and chat come without them. A mark inside what was said is
                never set aside: it still separates what it separates. These are properties of the writing system,
                not of English.
A text is read as the consecutive utterances that cover it, each ending where a held construction ends. An utterance
nothing reads whole is read in parts: the parts that read on their own, as sentences or as held fillers, and the
words nothing held has, so what was not understood is named exactly and nothing that was is thrown away.

LEARNING goes through the learning authority (`learn_patterns`), one taught pair at a time. The pair is read first;
if that gives its meaning, only the scores move. Otherwise the repairs here are tried in the paper's order, and the
first that can handle the pair says what to create. Each repair is a pure function of the pair and the view.

WHO OWNS WHAT:
  * MEMORY holds every construction and link: one semantic memory each, tagged `PATTERN_TAG`, identified exactly by
    its key, warmed into the memory agent's language view.
  * BELIEFS hold the scores: one belief per construction or link, grounded in its memory. A successful use is an
    observation for it; a competitor's is an observation against it. A link's use count is its evidence.
  * THE DOMAIN SYSTEM holds meaning: a meaning is facts in the domain system's own link kinds (`SemanticRelation`),
    and English is a domain of its own.
This module holds none of them. It says what the constructions are, reads and speaks through the view memory
warms, and says what each repair would create.

WHAT A MEANING IS:
  * `act`    tell / ask / request.
  * facts    (relation, subject, object, positive), e.g. `instance_of(?shown, shoe)`. A term is a concept's name or
             a `?variable`. A fact marked `condition` is one that must hold for the others to hold: "If the valve is
             closed, the tank overflows." states no fact outright. Facts marked `alternative` are two or more of
             which one holds: "Is the stove hot or cold?" asks which.
  * `asked`  the variables a question asks for; empty for a yes/no question.
Four variables are bound by the SITUATION, not by the sentence: `?speaker`, `?listener`, `?shown` (what "this" and
"here" point at) and `?previous` (what "it" and "they" point back to). A slot's variable is named by its place in
the form: `?slot0`, `?slot1`, ... A lexical construction supplies one concept, never a variable.

NO MODEL IS INVOLVED AT ANY POINT.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import functools
import heapq
import itertools
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import (AbstractSet, Any, Awaitable, Callable, Collection, Dict, FrozenSet, Iterable, Iterator, List,
                    Mapping, NamedTuple, Optional, Sequence, Set, Tuple, Union)

from core.semantics.relation_types import SemanticRelation, is_worded, worded
from core.semantics.literals import classify_literal

#: `core.observability.channels` routes `core.semantics` to the substrate panel, so reading says what it did beside
#: the rest of Lyric thinking, with no routing to add.
logger = logging.getLogger(__name__)
from core.semantics.sentence_machine import QUOTED, Piece, form_of, surface_of

#: English is a domain like any subject: its constructions are what the substrate knows of it, and its competence
#: is measured the way any domain's is.
ENGLISH_DOMAIN = "english"

#: The tag on a memory that holds a construction or a link.
PATTERN_TAG = "language_pattern"

#: What a speaker can want done with what they say.
ACTS = ("tell", "ask", "request")

#: Bound by the situation a sentence is said in, never by the sentence. `?now` is when it is said: "ran" is an event
#: before it, "will run" one after it, "is running" one during it.
SITUATION_VARIABLES = ("?speaker", "?listener", "?shown", "?previous", "?now", "?here", "?there")

#: What a happening is said to have: what it was done by, or what it was done to. A thing one of a kind that is done
#: by or to something is a happening (`teaching.told_events`), and the kind a doing (`_names_a_doing`).
EVENT_PARTICIPANTS = ("done_by", "done_to")

#: The kinds whose object is a place, where a thing is or where an event goes: the place "there" can point back to
#: (`place_spoken_of`).
PLACE_KINDS = frozenset({"located_at", "located_in", "adjacent_to", "near", "above", "below", "left_of", "right_of",
                         "in_front_of", "behind", "moves_to", "moves_into", "moves_onto", "moves_from",
                         "moves_out_of", "moves_through", "moves_across", "moves_over", "moves_around",
                         "moves_toward", "moves_up", "moves_down"})

#: A verdict on what was just said is `has_property(?previous, true)` or `(?previous, false)`: the logic's own truth
#: values, whatever words said them.
VERDICTS = {"true": True, "false": False}

#: A taught phrase with more unknowns than this is refused (`Phrase`): the reader builds phrases into readings, and
#: a phrase of many unknowns multiplies them. A sentence's meaning has no such limit: it was refused past six
#: unknowns while `canonical` followed every tie (n things of one kind, n! ways), and "We propose a new method for
#: detecting anomalies in network traffic." (seven) could not be held; ties are settled by what is said of the
#: unknowns (`_least_naming`), and forty are written in milliseconds (2026-10-21).
MAX_FREE_VARIABLES = 6

#: The score of a construction nothing has observed yet: where the paper starts a new one.
INITIAL_SCORE = 0.5

_VARIABLE = re.compile(r"^\?[a-z][a-z0-9_]*$")
_SLOT = re.compile(r"^\?slot(0|[1-9][0-9]*)$")

#: The kinds a meaning may be written in: every link kind but the inert one. `related_to` licenses no inference,
#: so a meaning written in it says nothing the substrate could reason with.
_KINDS = frozenset(r.value for r in SemanticRelation
                   if r is not SemanticRelation.RELATED_TO)


def is_variable(term: Any) -> bool:
    return bool(_VARIABLE.match(str(term)))


def is_slot(term: Any) -> bool:
    return bool(_SLOT.match(str(term)))


#: The kinds that build a number from numbers, and how: "twenty-one" is the sum of 20 and 1, "two hundred" the
#: product of 2 and 100.
_ARITHMETIC = {"has_addend": sum, "has_factor": math.prod}


_FRACTION = re.compile(r"-?\d+/\d+")


#: The kinds a phrase that builds a number from numbers states.
_ARITHMETIC_ROLES = frozenset({"has_addend", "has_factor", "has_augend", "has_minuend", "has_subtrahend",
                               "has_multiplicand", "has_dividend", "has_divisor", "has_base", "has_exponent",
                               "has_radicand", "has_index", "has_argument"})


def _filler_mathematical(item: Any) -> Optional[bool]:
    """Whether a held filler is mathematics (True) or a word for something else (False); None for a phrase that
    says neither outright."""
    if isinstance(item, Lexical):
        return _mathematical(item.value)
    if isinstance(item, Phrase):
        kinds = {f.relation for f in item.facts}
        if kinds & _ARITHMETIC_ROLES and kinds <= _ARITHMETIC_ROLES | {"instance_of"}:
            return True
    return None


def _mathematical(concept: str) -> bool:
    """A number, a formula, or one letter standing for an unknown ("x")."""
    concept = str(concept)
    return _quantity(concept) or (len(concept) == 1 and concept.isalpha() and concept.islower())


@functools.lru_cache(maxsize=1 << 14)
def _quantity(concept: str) -> bool:
    """Whether a concept is a number or a formula, as its writing says: 12, 3.5, 1000000, `2 + 3`, and 1/2 -- which,
    as a concept, is the number a sum came to, never the name `9/11` is as a word."""
    literal = classify_literal(concept)
    return (literal is not None and literal.kind in ("cardinal", "decimal", "expression")) \
        or bool(_FRACTION.fullmatch(str(concept)))


def _temporal(concept: str) -> bool:
    """Whether a concept is a day or a time of day, as its writing says: `--10-06` is the sixth of October, `7:30
    p.m.` half past seven in the evening (`literals`)."""
    literal = classify_literal(concept)
    return literal is not None and literal.kind in ("date", "time")


#: The months as they are written, for a day said back.
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


def _temporal_written(concept: str) -> str:
    """A day or a time of day as English writes it: `--10-06` is "October 6", `2010-10-06` "October 6, 2010", `7:00
    p.m.` "7 p.m."; a time held as written ("7:30") is written so."""
    literal = classify_literal(concept)
    if literal is None:
        return concept
    if literal.kind == "date":
        if literal.canonical.startswith("--"):
            month, day = literal.value
            return f"{_MONTH_NAMES[month - 1]} {day}"
        return f"{_MONTH_NAMES[literal.value.month - 1]} {literal.value.day}, {literal.value.year}"
    clock, _, half = literal.canonical.partition(" ")
    if literal.kind == "time" and half and clock.endswith(":00"):
        return f"{clock[:-3]} {half}"                       # "7:00 p.m." is written "7 p.m."
    return literal.canonical


def _size(digits: str) -> int:
    """How many groups of three digits a whole number is written in, less one: 312 is 0, 7000000000312 is 4."""
    return (len(digits.lstrip("0") or "0") - 1) // 3


def _evaluated(facts: Tuple["MeaningFact", ...]) -> Tuple["MeaningFact", ...]:
    """These facts with every number they build from numbers written as its value: an unknown that is the sum of
    20 and 1 ("twenty-one") is 21, as "21" writes it, and the facts that built it are gone. A number built of one
    alone, or of a number not yet known, is left as it is."""
    return _valued(facts)[1]


def _valued(facts: Iterable["MeaningFact"]) -> Tuple[Dict[str, str], Tuple["MeaningFact", ...]]:
    """The numbers these facts build from numbers, each unknown and its value, and the facts with each written as
    its value (`_evaluated`)."""
    facts = tuple(facts)
    values: Dict[str, str] = {}
    while True:
        for number in sorted({f.subject for f in facts if f.relation in _ARITHMETIC}):
            own = [f for f in facts if f.subject == number and f.relation in _ARITHMETIC]
            kinds = {f.relation for f in own}
            if not is_variable(number) or _named(number) or len(kinds) != 1 or len(own) < 2 \
                    or not all(f.positive and not f.alternative and f.obj.isdigit() for f in own):
                continue
            value = str(_ARITHMETIC[own[0].relation](int(f.obj) for f in own))
            values = {v: (value if w == number else w) for v, w in values.items()}
            values[number] = value
            rest = [f.renamed({number: value}) for f in facts if f not in own]
            facts = tuple(dict.fromkeys(rest))
            break
        else:
            return values, facts


@functools.lru_cache(maxsize=1 << 16)
def _canonical(meaning: "Meaning") -> str:
    return _canonical_of(meaning.act, meaning.facts, meaning.asked)


def _least_naming(facts: Sequence["MeaningFact"], free: Collection[str], first: Sequence[str] = (),
                  asked: Sequence[str] = ()) -> Dict[str, str]:
    """The naming of the unknowns `free` to `?v0, ?v1, ...` a meaning is written by, whatever they were called.

    It is built a fact at a time. The first fact is the least any fact can be written, its unknowns given the least
    names not taken, in the order the fact writes them; each next fact likewise, with the names already given kept.
    `first` are named before any fact, in order (a phrase writes its anchor ahead of its facts).

    WHERE FACTS TIE, WHAT IS SAID OF THEIR UNKNOWNS DECIDES. Two facts written alike name different unknowns ("The
    dog barked. The cat ran.": `done_by(?v0, ?v1)` either way). Each unknown is told apart by the facts it is in and,
    round by round, by what the unknowns beside it are told apart as (colour refinement, Weisfeiler and Leman 1968),
    an unknown asked about by its place, and one named by its name, told apart again as each is named: three people
    each in the next are alike until one is named, and then the one it is in is not the one in it. None of it depends
    on what the unknowns were called. Of facts that tie, the one whose unknowns are told apart least is written
    first; unknowns told apart alike are alike in all that is said of them, and either is. Every tie was followed, and
    the least writing of all
    kept: n things of one kind, each doing one thing, were followed n! ways, and a meaning of more than six unknowns
    was refused for it (`MAX_FREE_VARIABLES`, before); then ties of unknowns told apart alike were followed once,
    and n things each told apart, each doing one thing, were still followed n! ways: sixteen unknowns were written
    in 35 seconds, and a page of entries read as one sentence never was (2026-10-21)."""
    pool = sorted(f"?v{i}" for i in range(len(free)))
    unknown = set(free)
    names: Dict[str, str] = {}
    for variable in first:
        if variable in unknown and variable not in names:
            names[variable] = pool[len(names)]
    asking = {v: ("asked", i) for i, v in reversed(list(enumerate(asked))) if v in unknown}
    incident: Dict[str, List["MeaningFact"]] = {v: [] for v in unknown}
    for fact in facts:
        for term in set(fact.terms()) & unknown:
            incident[term].append(fact)
    colour: Dict[str, int] = {}
    told_by = -1
    left = list(facts)
    while left:
        if told_by != len(names):
            colour = _colours(incident, {**asking, **{v: ("named", n) for v, n in names.items()}})
            told_by = len(names)
        least: Optional[Tuple[str, Tuple[int, ...], int, Dict[str, str]]] = None
        for k, fact in enumerate(left):
            trial = dict(names)
            for term in fact.terms():
                if term in unknown and term not in trial:
                    trial[term] = pool[len(trial)]
            written = fact.renamed(trial).render()
            told = tuple(colour[t] for t in sorted(set(trial) - set(names), key=trial.get))
            if least is None or (written, told) < least[:2]:
                least = (written, told, k, trial)
        _, _, k, names = least  # type: ignore[misc]
        del left[k]
    return names


def _colours(incident: Mapping[str, Sequence["MeaningFact"]],
             marked: Mapping[str, Tuple[str, Any]] = {}) -> Dict[str, int]:
    """Each unknown told apart by what is said of it (colour refinement): first by the facts it is in (`incident`),
    as written with every unknown alike, and by its mark (`marked`: asked about and its place, or its name); then,
    round by round, by those and what the unknowns beside it were told apart as, until no round tells more apart."""
    def plain(term: str) -> str:
        return "?" if term in incident else term
    colour: Dict[str, Any] = {}
    for v, facts in incident.items():
        colour[v] = (marked.get(v, ()), tuple(sorted(
            (f.relation, f.subject == v, plain(f.obj if f.subject == v else f.subject),
             f.positive, f.condition, f.alternative, f.unasserted, f.given)
            for f in facts)))
    rounds = 0
    while rounds <= len(colour):
        rounds += 1
        named = {c: k for k, c in enumerate(sorted(set(colour.values()), key=repr))}
        before = {v: named[c] for v, c in colour.items()}
        colour = {v: (before[v], tuple(sorted(
            (f.relation, f.subject == v, before.get(f.obj if f.subject == v else f.subject, -1))
            for f in facts))) for v, facts in incident.items()}
        if len(set(colour.values())) == len(set(before.values())):
            return before
    named = {c: k for k, c in enumerate(sorted(set(colour.values()), key=repr))}
    return {v: named[c] for v, c in colour.items()}


def _canonical_of(act: str, facts: Sequence["MeaningFact"], asked: Sequence[str]) -> str:
    """A meaning's parts written as `Meaning.canonical` writes it, without the meaning having to be one."""
    evaluated = _evaluated(facts)
    free = sorted({t for f in evaluated for t in f.terms() if is_variable(t) and not _named(t)})
    names = _least_naming(evaluated, free, asked=asked)
    rendered = " & ".join(sorted(f.renamed(names).render() for f in evaluated))
    asking = ", ".join(names.get(v, v) for v in asked)
    return f"{act}: {rendered}" + (f" ? {asking}" if asking else "")


def slot_name(index: int) -> str:
    return f"?slot{int(index)}"


def _named(term: str) -> bool:
    """A variable whose name is part of what it means: the situation's, and a slot's."""
    return term in SITUATION_VARIABLES or is_slot(term)


@dataclass(frozen=True)
class MeaningFact:
    """One fact a sentence states, in one of the domain system's link kinds; or, marked `condition`, one that must
    hold for the sentence's other facts to hold; or, marked `alternative`, one of the alternatives on its side of
    an `if`, of which one holds: "Is the stove hot or cold?"; or, marked `unasserted`, one the sentence does not
    tell as so: what someone says, tells, thinks, believes, hopes or asks, what someone wants, likes or tries to do,
    what a doing is for, and what something is or is not enough to do. `Tom said, "The dog barked."` and "Tom said
    that the dog barked." state a saying, done by Tom; that the dog barked is what he said, not that it did. "Tom
    knows that the dog barked." tells the barking as so.

    Marked `given`, what a thing the speaker and listener both know is: "the dog" is `given instance_of(?a, dog)`, the
    dog already known, where "a dog" is a dog not known before (`docs/TEACHING.md` §12d). It is true of the thing,
    and not news."""

    relation: str
    subject: str
    obj: str
    positive: bool = True
    condition: bool = False
    alternative: bool = False
    unasserted: bool = False
    given: bool = False

    def __post_init__(self):
        relation = str(self.relation).strip()
        if relation not in _KINDS and not is_worded(relation):
            raise ValueError(f"{relation!r} is not a link kind the domain system "
                             f"reasons with, nor a link held as its word")
        for role, term in (("subject", self.subject), ("object", self.obj)):
            text = str(term).strip()
            if not text:
                raise ValueError(f"a fact's {role} is empty")
            if text.startswith("?") and not is_variable(text):
                raise ValueError(f"{text!r} is not a variable name")
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "subject", str(self.subject).strip())
        object.__setattr__(self, "obj", str(self.obj).strip())
        object.__setattr__(self, "positive", bool(self.positive))
        object.__setattr__(self, "condition", bool(self.condition))
        object.__setattr__(self, "alternative", bool(self.alternative))
        object.__setattr__(self, "unasserted", bool(self.unasserted))
        object.__setattr__(self, "given", bool(self.given))
        if self.given and (self.relation != "instance_of" or not is_variable(self.subject) or not self.positive):
            raise ValueError("only a particular thing is known: `given` says what a thing both know is "
                             "(instance_of, of a variable)")

    def terms(self) -> Tuple[str, str]:
        return (self.subject, self.obj)

    def renamed(self, names: Mapping[str, str]) -> "MeaningFact":
        """The fact with its terms renamed. A known thing named (`given instance_of(?t0, kelt)` as `kelt_1`) is no
        longer one to find: what it is stays, unmarked."""
        subject = names.get(self.subject, self.subject)
        return MeaningFact(self.relation, subject, names.get(self.obj, self.obj), self.positive, self.condition,
                           self.alternative, self.unasserted, self.given and is_variable(subject))

    def render(self) -> str:
        text = f"{self.relation}({self.subject}, {self.obj})"
        text = text if self.positive else f"not {text}"
        text = f"either {text}" if self.alternative else text
        text = f"if {text}" if self.condition else text
        text = f"given {text}" if self.given else text
        return f"unasserted {text}" if self.unasserted else text

    def to_list(self) -> List[Any]:
        """As memory holds it. A condition, an alternative, a fact not told as so or one taken as known is marked only
        where there is one, so a meaning written before any of them existed is stored, and identified, exactly as it
        was."""
        out = [self.relation, self.subject, self.obj, self.positive]
        if self.given:
            return out + [self.condition, self.alternative, self.unasserted, True]
        if self.unasserted:
            return out + [self.condition, self.alternative, True]
        if self.alternative:
            return out + [self.condition, True]
        return out + [True] if self.condition else out

    @classmethod
    def from_list(cls, data: Iterable[Any]) -> "MeaningFact":
        relation, subject, obj, positive, *rest = list(data)
        return cls(relation, subject, obj, bool(positive), bool(rest[0]) if rest else False,
                   bool(rest[1]) if len(rest) > 1 else False, bool(rest[2]) if len(rest) > 2 else False,
                   bool(rest[3]) if len(rest) > 3 else False)


@dataclass(frozen=True)
class Meaning:
    """What a sentence means: what the speaker wants, the facts, and what is asked."""

    act: str
    facts: Tuple[MeaningFact, ...]
    asked: Tuple[str, ...] = ()

    def __post_init__(self):
        act = str(self.act).strip().lower()
        if act not in ACTS:
            raise ValueError(f"{act!r} is not something a speaker wants done; "
                             f"one of {ACTS}")
        facts = tuple(self.facts)
        if not facts:
            raise ValueError("a meaning states at least one fact")
        if not all(isinstance(f, MeaningFact) for f in facts):
            raise ValueError("a meaning's facts are MeaningFacts")
        if len(set(facts)) != len(facts):
            raise ValueError("a meaning states the same fact twice")
        if any(f.relation in ("isa", "instance_of", "has_property") and _quantity(f.obj) for f in facts):
            raise ValueError("a number is neither a kind nor a quality: nothing is a 7, or 7 as it is red")
        if any(f.relation in ("isa", "instance_of", "has_property") and _temporal(f.obj) for f in facts):
            raise ValueError("a day or a time is neither a kind nor a quality: nothing is a March 12, or 7 p.m. as "
                             "it is red; a thing is during it")
        counted: Dict[Tuple[str, bool, bool], str] = {}
        for f in facts:
            if f.relation == "has_count" and f.positive and not f.alternative:
                if counted.setdefault((f.subject, f.condition, f.alternative, f.unasserted), f.obj) != f.obj:
                    raise ValueError("a group has one count: how many there are is one number")
        timed: Dict[Tuple[str, str, bool], str] = {}
        for f in facts:
            if f.relation in ("precedes", "during", "follows") and f.positive and not f.alternative:
                if timed.setdefault((f.subject, f.obj, f.condition, f.unasserted), f.relation) != f.relation:
                    raise ValueError("a happening is at one time from where it is seen: over, going on or "
                                     "to come, never two of them")
        if all(f.condition for f in facts):
            raise ValueError("a condition alone says nothing; a meaning states what holds when it does")
        for side in (True, False):
            if sum(1 for f in facts if f.alternative and f.condition == side) == 1:
                raise ValueError("an alternative stands beside another: one of at least two holds")
        asked = tuple(str(v).strip() for v in self.asked)
        if asked and act != "ask":
            raise ValueError("only a question asks for something")
        mentioned = {t for f in facts for t in f.terms() if is_variable(t)}
        for variable in asked:
            if not is_variable(variable):
                raise ValueError(f"{variable!r} is not a variable name")
            if variable not in mentioned:
                raise ValueError(f"{variable} is asked for, but no fact mentions it")
            if variable in SITUATION_VARIABLES:
                raise ValueError(f"{variable} is bound by the situation; a question "
                                 f"cannot ask for it")
            if is_slot(variable):
                raise ValueError(f"{variable} is a slot, which a filler fills; a question "
                                 f"cannot ask for it")
        if len(set(asked)) != len(asked):
            raise ValueError("a question asks for the same thing twice")
        object.__setattr__(self, "act", act)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "asked", asked)

    def canonical(self) -> str:
        """This meaning written one way, whatever its unknowns were called.

        The unknowns are renamed `?v0, ?v1, ...` by what is said of them (`_least_naming`), never by what they were
        called, so two meanings that differ only in what their unknowns were named render identically -- and two
        that differ in anything else do not. The situation's variables and the slots keep their names: `?speaker` is not `?listener`, and
        `?slot0` is the first open place in the form. A number built from numbers is written as its value
        (`evaluated`): "twenty-one dogs" and "21 dogs" are one meaning. A meaning never changes, so it is written
        once.
        """
        return _canonical(self)

    def evaluated(self) -> "Meaning":
        """This meaning with every number it builds from numbers written as its value: "twenty-one" as 21."""
        facts = _evaluated(self.facts)
        return self if facts == self.facts else Meaning(self.act, facts, self.asked)

    def constants(self) -> FrozenSet[str]:
        """The concepts this meaning names."""
        return frozenset(t for f in self.facts for t in f.terms() if not is_variable(t))

    def slots(self) -> FrozenSet[str]:
        return frozenset(t for f in self.facts for t in f.terms() if is_slot(t))

    @property
    def condition(self) -> Tuple[MeaningFact, ...]:
        """The facts that must hold for the rest to hold; empty when nothing is conditional."""
        return tuple(f for f in self.facts if f.condition)

    @property
    def asserted(self) -> Tuple[MeaningFact, ...]:
        """The facts that hold, or that hold once the condition does; never what the sentence does not tell as so."""
        return tuple(f for f in self.facts if not f.condition and not f.unasserted)

    @property
    def unasserted(self) -> Tuple[MeaningFact, ...]:
        """The facts the sentence does not tell as so (`MeaningFact.unasserted`): what someone said, thought or
        wants, what a doing is for. Empty when it tells everything it states."""
        return tuple(f for f in self.facts if f.unasserted)

    @property
    def given(self) -> Tuple[MeaningFact, ...]:
        """What the things the sentence takes as known are (`MeaningFact.given`): "the dog", a dog both know."""
        return tuple(f for f in self.facts if f.given)

    def known_kinds(self) -> Dict[str, str]:
        """`{variable: kind}` for each known thing ("the kelt": `?t0`, `kelt`), to be found (`bound`)."""
        return {f.subject: f.obj for f in self.facts if f.given and not is_variable(f.obj)}

    def bound(self, situation: Mapping[str, str],
              known: Optional[Mapping[str, str]] = None) -> Tuple[MeaningFact, ...]:
        """The facts with the situation's variables replaced by what they stand
        for here, and each known thing (`given`) by the particular it was found
        to be (`known`). A fact may still hold a variable afterwards: an unknown
        the sentence introduced, which nothing names."""
        names = {}
        for variable, value in dict(known or {}).items():
            if not any(f.given and f.subject == variable for f in self.facts):
                raise ValueError(f"{variable!r} is not a known thing of this meaning")
            names[variable] = str(value).strip()
        for variable, value in dict(situation or {}).items():
            if variable not in SITUATION_VARIABLES:
                raise ValueError(f"{variable!r} is not a situation variable; one of "
                                 f"{SITUATION_VARIABLES}")
            text = str(value).strip()
            if not text or is_variable(text):
                raise ValueError(f"{variable} must be bound to a thing, not {value!r}")
            names[variable] = text
        return tuple(f.renamed(names) for f in self.facts)

    def to_dict(self) -> Dict[str, Any]:
        return {"act": self.act,
                "facts": [f.to_list() for f in self.facts],
                "asked": list(self.asked)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Meaning":
        return cls(act=data["act"],
                   facts=tuple(MeaningFact.from_list(f) for f in data["facts"]),
                   asked=tuple(data.get("asked") or ()))


def _renamed(meaning: Meaning, names: Mapping[str, str]) -> Optional[Meaning]:
    """`meaning` with terms renamed, or None when that makes it no meaning (a fact stated twice)."""
    try:
        return Meaning(meaning.act, tuple(f.renamed(names) for f in meaning.facts),
                       tuple(names.get(v, v) for v in meaning.asked))
    except ValueError:
        return None


def _key(*parts: str) -> str:
    return hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()[:32]


def _fold(text: str) -> str:
    """A piece with its letter case folded: `Is` and `is` are one word written two ways."""
    return str(text).casefold()


#: The signs mathematics relates two sides with. They have no letter in them, and they are words all the same:
#: "=" says what "equals" says.
_RELATION_SIGNS = frozenset({"=", "==", "<", ">", "<=", ">=", "≤", "≥", "≠", "!="})


def _is_mark(text: str) -> bool:
    """A piece with no letter or digit in it, and no sign of mathematics' relations: a mark of the writing, not a
    word."""
    return not any(ch.isalnum() for ch in str(text)) and str(text) not in _RELATION_SIGNS


def _folded(words: Iterable[str]) -> Tuple[str, ...]:
    """A form's own words, case folded and marks set aside, each piece a word of its own."""
    return tuple(_fold(w) for w in words if not _is_mark(w))


#: The mark that joins two words into one where it stands between them unspaced ("twenty-one").
_HYPHEN = "-"


def _loose(words: Iterable[str]) -> Tuple[str, ...]:
    """A filler's words as a loose reading looks them up: case folded, marks set aside, and the words a hyphen
    joins one word, as they are written ("x-ray")."""
    folded = [_fold(w) for w in words]
    out: List[str] = []
    joining = False
    for k, word in enumerate(folded):
        if _is_mark(word):
            joining = (word == _HYPHEN and k > 0 and not _is_mark(folded[k - 1])
                       and k + 1 < len(folded) and not _is_mark(folded[k + 1]))
            if joining:
                out[-1] += word
            continue
        if joining:
            out[-1] += word
            joining = False
        else:
            out.append(word)
    return tuple(out)


def _joins(pieces: Sequence[Piece], at: int) -> bool:
    """Whether the piece at `at` is a hyphen joining the words on either side of it into one word ("twenty-one")."""
    return (0 < at < len(pieces) - 1 and pieces[at].text == _HYPHEN and not pieces[at - 1].space_after
            and not pieces[at].space_after and not _is_mark(pieces[at - 1].text)
            and not _is_mark(pieces[at + 1].text))


def _parted(pieces: Sequence[Piece]) -> bool:
    """Whether a mark parts these pieces: one among them that is not a hyphen joining two words."""
    return any(_is_mark(p.text) and not _joins(pieces, k) for k, p in enumerate(pieces))


def _written_words(pieces: Sequence[Piece]) -> List[Tuple[Piece, ...]]:
    """These pieces as the words they write: a hyphen and the words it joins are one word ("twenty-one")."""
    out: List[Tuple[Piece, ...]] = []
    for k, piece in enumerate(pieces):
        if out and (_joins(pieces, k) or _joins(pieces, k - 1)):
            out[-1] = out[-1] + (piece,)
        else:
            out.append((piece,))
    return out


def _first_word(words: Iterable[str]) -> str:
    """The first word that is not a mark, case folded: where a loose reading looks for a holophrase."""
    return next((_fold(w) for w in words if not _is_mark(w)), "")


@dataclass(frozen=True)
class Slot:
    """An open place in an item-based construction's form, where a lexical construction linked to it goes."""

    name: str
    space_after: bool = True

    def __post_init__(self):
        if not is_slot(self.name):
            raise ValueError(f"{self.name!r} is not a slot name; slots are ?slot0, ?slot1, ...")
        object.__setattr__(self, "space_after", bool(self.space_after))


FormElement = Union[Piece, Slot]


def _element(entry: Any) -> FormElement:
    if isinstance(entry, Slot):
        return entry
    if isinstance(entry, (list, tuple)) and len(entry) == 3 and entry[2] == "slot":
        return Slot(str(entry[0]), bool(entry[1]))
    return Piece(str(entry[0]), bool(entry[1]))


def _text(element: FormElement) -> str:
    return element.name if isinstance(element, Slot) else element.text


@dataclass(frozen=True)
class Pattern:
    """A holophrase (no slots) or an item-based construction (slots): a form and what it means."""

    form: Tuple[FormElement, ...]
    meaning: Meaning

    def __post_init__(self):
        form = tuple(_element(e) for e in self.form)
        if not form:
            raise ValueError("a pattern has pieces; an empty sentence says nothing")
        if not isinstance(self.meaning, Meaning):
            raise ValueError("a pattern's meaning is a Meaning")
        slots = [e.name for e in form if isinstance(e, Slot)]
        if slots != [slot_name(i) for i in range(len(slots))]:
            raise ValueError(f"slots are named by their place in the form (?slot0, ?slot1, ...), not {slots}")
        if set(slots) != set(self.meaning.slots()):
            raise ValueError("every slot of the form is a variable of the meaning, and every slot variable of "
                             "the meaning is a slot of the form")
        object.__setattr__(self, "form", form)

    @property
    def kind(self) -> str:
        return "item_based" if self.slots else "holophrase"

    @property
    def slots(self) -> Tuple[str, ...]:
        return tuple(e.name for e in self.form if isinstance(e, Slot))

    @property
    def words(self) -> Tuple[str, ...]:
        """The pieces as written, and each slot by its name: what reading matches."""
        return tuple(_text(e) for e in self.form)

    @property
    def surface(self) -> str:
        return "".join(_text(e) + (" " if e.space_after else "") for e in self.form).rstrip()

    @functools.cached_property
    def key(self) -> str:
        """The construction's identity: exactly these pieces and slots with exactly this meaning.

        Memory is asked for it by this key before a construction is stored, and it is what makes teaching the same
        pair twice one construction, not two -- the identity is structural, never a resemblance a vector index
        judged.

        Made once for each construction: the chart is asked by it of every span a covering reaches, and made afresh
        each time, a construction's key was made 1,507,624 times reading one paragraph of prose (lyric_dev,
        2026-10-23)."""
        body = "\x1f".join(self.words) + "\x1e" + self.meaning.canonical()
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]

    def belief_clause(self) -> Tuple[str, str, str]:
        """What the construction's belief is about, as the parts the learning fan-out joins into a claim: this
        form means this."""
        return (f'"{self.surface}"', "means", self.meaning.canonical())

    def claim(self) -> str:
        """The claim the construction's belief holds, exactly as the fan-out writes it."""
        return " ".join(self.belief_clause())

    def to_dict(self) -> Dict[str, Any]:
        return {"form": [[e.name, e.space_after, "slot"] if isinstance(e, Slot) else [e.text, e.space_after]
                         for e in self.form],
                "meaning": self.meaning.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Pattern":
        return cls(form=tuple(_element(e) for e in data["form"]),
                   meaning=Meaning.from_dict(data["meaning"]))


@dataclass(frozen=True)
class Lexical:
    """A lexical construction: the pieces that fill a slot, and the concept they put where the slot's variable was."""

    form: Tuple[Piece, ...]
    value: str

    def __post_init__(self):
        form = tuple(_element(e) for e in self.form)
        if not form:
            raise ValueError("a lexical construction has pieces")
        if any(isinstance(e, Slot) for e in form):
            raise ValueError("a lexical construction has no slots of its own")
        value = str(self.value).strip()
        if not value or value.startswith("?"):
            raise ValueError(f"a lexical construction supplies a concept, not {self.value!r}")
        # Its own last space is not part of it: the slot it fills decides what follows.
        form = form[:-1] + (Piece(form[-1].text, False),)
        object.__setattr__(self, "form", form)
        object.__setattr__(self, "value", value)

    kind = "lexical"

    @property
    def words(self) -> Tuple[str, ...]:
        return tuple(p.text for p in self.form)

    @property
    def surface(self) -> str:
        return surface_of(self.form)

    @functools.cached_property
    def key(self) -> str:
        return _key("lexical", "\x1f".join(self.words), self.value)

    def belief_clause(self) -> Tuple[str, str, str]:
        return (f'"{self.surface}"', "names", self.value)

    def claim(self) -> str:
        return " ".join(self.belief_clause())

    def to_dict(self) -> Dict[str, Any]:
        return {"form": [[p.text, p.space_after] for p in self.form], "value": self.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Lexical":
        return cls(form=tuple(Piece(str(t), bool(s)) for t, s in data["form"]), value=data["value"])


@dataclass(frozen=True)
class Link:
    """A slot of an item-based construction or a phrase joined to what may fill it: a lexical construction or a
    phrase (`lexical` holds the filler's key, whichever it is)."""

    pattern: str
    slot: str
    lexical: str
    pattern_surface: str = ""
    lexical_surface: str = ""

    def __post_init__(self):
        if not is_slot(self.slot):
            raise ValueError(f"{self.slot!r} is not a slot name")

    kind = "link"

    @functools.cached_property
    def key(self) -> str:
        return _key("link", self.pattern, self.slot, self.lexical)

    def belief_clause(self) -> Tuple[str, str, str]:
        return (f'"{self.pattern_surface}" {self.slot}', "takes",
                f'"{self.lexical_surface}" [{self.key[:12]}]')

    def claim(self) -> str:
        return " ".join(self.belief_clause())

    def to_dict(self) -> Dict[str, Any]:
        return {"pattern": self.pattern, "slot": self.slot, "lexical": self.lexical,
                "pattern_surface": self.pattern_surface, "lexical_surface": self.lexical_surface}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Link":
        return cls(pattern=data["pattern"], slot=data["slot"], lexical=data["lexical"],
                   pattern_surface=data.get("pattern_surface", ""),
                   lexical_surface=data.get("lexical_surface", ""))


def _phrase_canonical(anchor: str, facts: Iterable[MeaningFact]) -> str:
    """What a phrase names, written one way whatever its unknowns were called: as `Meaning.canonical` writes a
    meaning, its anchor named first (`_least_naming`), and a number built from numbers written as its value. A phrase
    never changes, so it is written once."""
    return _phrase_written(anchor, tuple(facts))


@functools.lru_cache(maxsize=1 << 16)
def _phrase_written(anchor: str, facts: Tuple[MeaningFact, ...]) -> str:
    values, facts = _valued(facts)
    anchor = values.get(anchor, anchor)
    free = sorted({t for f in facts for t in f.terms()} | {anchor})
    free = [t for t in free if is_variable(t) and not _named(t)]
    names = _least_naming(facts, free, first=(anchor,))
    return names.get(anchor, anchor) + " : " + " & ".join(sorted(f.renamed(names).render() for f in facts))


@dataclass(frozen=True)
class Phrase:
    """A phrase construction: what fills a slot when one word does not.

    Its form is pieces, and slots of its own. What it names is an ANCHOR -- a concept, one of its slots, or a variable
    standing for a thing -- with FACTS about the anchor: "red ?slot0" names a thing that is a `?slot0` and is red,
    `?n` with `instance_of(?n, ?slot0)` and `has_property(?n, red)`. A lexical construction is the simplest phrase: a
    concept, and nothing said about it. Phrases fill slots, their own slots included, so they nest."""

    form: Tuple[FormElement, ...]
    anchor: str
    facts: Tuple[MeaningFact, ...] = ()

    def __post_init__(self):
        form = tuple(_element(e) for e in self.form)
        if not form:
            raise ValueError("a phrase has pieces")
        slots = [e.name for e in form if isinstance(e, Slot)]
        if slots != [slot_name(i) for i in range(len(slots))]:
            raise ValueError(f"slots are named by their place in the form (?slot0, ?slot1, ...), not {slots}")
        if len(form) == 1 and slots:
            raise ValueError("a phrase that is one slot and nothing else is the filler itself")
        anchor = str(self.anchor).strip()
        if not anchor or (anchor.startswith("?") and not is_variable(anchor)):
            raise ValueError(f"a phrase names something, not {self.anchor!r}")
        facts = tuple(self.facts)
        if not all(isinstance(f, MeaningFact) for f in facts):
            raise ValueError("a phrase's facts are MeaningFacts")
        if any(f.condition or f.alternative for f in facts):
            raise ValueError("a phrase says what holds of what it names; an `if` or an `or` belongs to a sentence")
        if len(set(facts)) != len(facts):
            raise ValueError("a phrase states the same fact twice")
        used = {t for f in facts for t in f.terms()} | {anchor}
        if set(slots) != {t for t in used if is_slot(t)}:
            raise ValueError("every slot of the form is used by what the phrase names, and every slot it names is "
                             "a slot of the form")
        if is_variable(anchor) and not _named(anchor) and not any(anchor in f.terms() for f in facts):
            raise ValueError("a thing the phrase stands for is described by its facts")
        if not slots and not facts and not is_variable(anchor):
            raise ValueError("a concept with nothing said about it is a lexical construction")
        if len({t for t in used if is_variable(t) and not _named(t)}) > MAX_FREE_VARIABLES:
            raise ValueError(f"at most {MAX_FREE_VARIABLES} unknowns in one phrase")
        object.__setattr__(self, "form", form)
        object.__setattr__(self, "anchor", anchor)
        object.__setattr__(self, "facts", facts)

    kind = "phrase"

    @property
    def slots(self) -> Tuple[str, ...]:
        return tuple(e.name for e in self.form if isinstance(e, Slot))

    @property
    def words(self) -> Tuple[str, ...]:
        return tuple(_text(e) for e in self.form)

    @property
    def surface(self) -> str:
        return "".join(_text(e) + (" " if e.space_after else "") for e in self.form).rstrip()

    def canonical(self) -> str:
        return _phrase_canonical(self.anchor, self.facts)

    @functools.cached_property
    def key(self) -> str:
        return _key("phrase", "\x1f".join(self.words), self.canonical())

    def belief_clause(self) -> Tuple[str, str, str]:
        return (f'"{self.surface}"', "names", self.canonical())

    def claim(self) -> str:
        return " ".join(self.belief_clause())

    def to_dict(self) -> Dict[str, Any]:
        return {"form": [[e.name, e.space_after, "slot"] if isinstance(e, Slot) else [e.text, e.space_after]
                         for e in self.form],
                "anchor": self.anchor, "facts": [f.to_list() for f in self.facts]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Phrase":
        return cls(form=tuple(_element(e) for e in data["form"]), anchor=data["anchor"],
                   facts=tuple(MeaningFact.from_list(f) for f in data.get("facts") or ()))


Construction = Union[Pattern, Lexical, Phrase]
Item = Union[Pattern, Lexical, Phrase, Link]

#: How a memory names what it holds (`construction` in its source context).
KIND_OF = {"holophrase": Pattern, "item_based": Pattern, "lexical": Lexical, "phrase": Phrase, "link": Link}


def item_from(kind: str, data: Mapping[str, Any]) -> Item:
    """The construction or link a memory holds, from its kind and its data."""
    if kind not in KIND_OF:
        raise ValueError(f"{kind!r} is not a kind of construction")
    return KIND_OF[kind].from_dict(data)


def link(pattern: Union[Pattern, Phrase], slot: str, lexical: Union[Lexical, Phrase]) -> Link:
    """A slot of a construction joined to what may fill it: a lexical construction, or a phrase."""
    if slot not in pattern.slots:
        raise ValueError(f"{pattern.surface!r} has no slot {slot}")
    return Link(pattern.key, slot, lexical.key, pattern.surface, lexical.surface)


def pattern_from(sentence: str, meaning: Meaning) -> Pattern:
    """The holophrase a whole sentence taught with its meaning makes."""
    return Pattern(form_of(sentence), meaning)


#: What an adjunct says of what the words before it stand for: the thing, or the happening.
ADJOINED = "?at"


@dataclass(frozen=True)
class Adjunct:
    """Words that may follow what stands in a slot and say more of it: "on the ?slot1" after "The ?slot0" in "The
    ?slot0 on the ?slot1 is ?slot2.", which says the thing is on something where "The ?slot0 is ?slot1." says nothing
    of where it is. FOUND, NEVER TAUGHT: a held frame that is another held frame with these words added right after
    one of its slots, and whose meaning is the other's with facts added of what that slot stands for. Read after
    anything standing in any slot, the words say the same of it ("the largest animal on Earth"), as a phrase read in
    one frame is read in every frame (`_adjoined`).

    `form` is the added words as the longer frame holds them, its slots among them that frame's own (`frame`), so
    what may stand in them is what may stand there; `facts` is what they add, of `ADJOINED` and of those slots; and
    `shorter` is the frame without them. `happening`: they say what only a happening has (`_HAPPENING`: where it
    moves, when it is, what it is done with or to), so they follow only what names one. `of_happening`: the frames
    said them of a happening ("Tom lives in the city."), so they may be said of what a sentence tells happened, after
    all of it (`_tails`), where "in the house" in "The dog ate the bone in the house." is where the eating was, or
    where the bone was."""

    form: Tuple[FormElement, ...]
    facts: Tuple[MeaningFact, ...]
    frame: str
    shorter: str
    happening: bool
    of_happening: bool

    @property
    def phrase(self) -> Phrase:
        """The adjunct as the phrase it reads as, its slots named in order: what a reading holds it by (`_adjoined`);
        never a phrase memory holds."""
        names = {e.name: slot_name(at) for at, e in enumerate(e for e in self.form if isinstance(e, Slot))}
        return Phrase(tuple(Slot(names[e.name], e.space_after) if isinstance(e, Slot) else e for e in self.form),
                      ADJOINED, tuple(f.renamed(names) for f in self.facts))

    @property
    def key(self) -> str:
        return self.phrase.key


def _adjunct_of(shorter: Pattern, longer: Pattern, start: int, end: int) -> Optional[Adjunct]:
    """The adjunct a pair of held frames shows, when the longer is the shorter with `longer.form[start:end]` added
    right after one of its slots (`Adjunct`); None when what the words add is not said of what that slot stands for.

    The shorter frame's slots are the longer's outside the words, in order. Its meaning must be the longer's with
    facts added (`_embedding`), and the facts added must meet the rest at one term: what the slot before the words
    stands for (the thing it names a kind of, where the frame uses it only so; the slot itself otherwise). A fact
    added of that term alone and the situation ("before now") is the frame's, said beside the words, not theirs: in
    "The ?slot0 ?slot1 onto the ?slot2." the time is the frame's, where "The ?slot0 ?slot1." leaves it to the word
    in its slot ("jumped")."""
    before = longer.form[start - 1]
    if not isinstance(before, Slot):
        return None
    inside = [e.name for e in longer.form[start:end] if isinstance(e, Slot)]
    outside = [e.name for k, e in enumerate(longer.form) if isinstance(e, Slot) and not start <= k < end]
    if len(outside) != len(shorter.slots):
        return None
    try:
        small = Meaning(shorter.meaning.act, tuple(f.renamed(dict(zip(shorter.slots, outside)))
                                                     for f in shorter.meaning.facts), shorter.meaning.asked)
    except ValueError:
        return None
    names = _embedding(small, longer.meaning)
    if names is None:
        return None
    image = {f.renamed(names) for f in small.facts}
    added = [f for f in longer.meaning.facts if f not in image]
    uses = [f for f in longer.meaning.facts if before.name in f.terms()]
    kinds = {f.subject for f in uses if f.relation == "instance_of" and f.obj == before.name and f.positive}
    at = next(iter(kinds)) if len(kinds) == 1 and len(uses) == 1 else before.name
    held = {t for f in image for t in f.terms()}
    added = [f for f in added if any(t != at and t not in held and t not in SITUATION_VARIABLES for t in f.terms())]
    if not added or set(inside) - {t for f in added for t in f.terms()}:
        return None
    if {t for f in added for t in f.terms() if t in held and t not in SITUATION_VARIABLES} != {at}:
        return None
    facts = tuple(f.renamed({at: ADJOINED}) for f in added)
    if any(f.condition or f.alternative for f in facts):
        return None
    happening = any(f.subject == ADJOINED and f.relation in _HAPPENING for f in facts)
    return Adjunct(longer.form[start:end], facts, longer.key, shorter.key, happening,
                   happening or any(f.subject == at and f.relation in _HAPPENING for f in image))


# ── The view ─────────────────────────────────────────────────────────────────────────────────────────────────────

Scorer = Callable[[Item], Tuple[float, int, bool]]


def _held_score(item: Item) -> Tuple[float, int, bool]:
    """A construction's score, use count and standing, from its belief in this process: its posterior; how many uses
    the observations supporting it witnessed (one each, or as many as a corpus counted); and whether a witness's
    latest word on it is still a use, a taught pair still reading through it (`counts`). One nothing has observed
    stands at the initial score, and in use, as the paper's new construction does."""
    from core.reasoning import bayesian_uncertainty as beliefs
    system = beliefs._uncertainty_system
    belief = system.belief_for_claim(item.claim()) if system is not None else None
    if belief is None:
        return INITIAL_SCORE, 0, True
    held = beliefs.BayesianUncertaintySystem
    return float(belief.posterior_probability), held.uses_for(belief), held.witnesses(belief, supports=True) > 0


class PatternInventory:
    """The constructions and links memory holds, indexed for reading, speaking and learning.

    NOT A STORE. Memory is the store; this is memory's view of its own construction memories, rebuilt from them at
    every warm and extended by `add` as one is taught, so it always says what a rebuild would say. Scores are read
    from the beliefs as they stand, never copied here.
    """

    def __init__(self, items: Iterable[Item] = (), score: Optional[Scorer] = None,
                 listened: Optional[Callable[[], Mapping[Tuple[str, int, bool], int]]] = None):
        self._by_key: Dict[str, Item] = {}
        self._holophrase_words: Dict[Tuple[str, ...], List[str]] = {}
        self._holophrase_first: Dict[str, List[str]] = {}
        self._holophrase_meaning: Dict[str, List[str]] = {}
        self._item_based: List[str] = []
        self._phrases: List[str] = []
        # EACH PHRASE UNDER ONE WORD OF ITS OWN (`phrases_reading`), and where it stands among them all.
        self._phrase_at: Dict[str, int] = {}
        self._phrases_by_word: Dict[str, List[str]] = {}
        self._phrases_wordless: List[str] = []
        # Each phrase under the kinds it names a thing of its own as (`phrases_of_kind`).
        self._phrases_of_kind: Dict[str, List[str]] = {}
        # Each phrase by the kinds of fact it states and one concept it names (`phrases_stating`, `within`).
        self._phrases_naming: Dict[Tuple[FrozenSet[Tuple[Tuple[str, bool], int]], Optional[str]], List[str]] = {}
        #: What composes a sentence (`_compositions`): each frame's slot under the kinds of fact the frame states
        #: with a phrase there, and each phrase under the kinds it states.
        self._frames_keeping: Dict[Tuple[str, FrozenSet[Tuple[Tuple[str, bool], int]]], List[Tuple[str, str]]] = {}
        self._phrases_stating: Dict[FrozenSet[Tuple[Tuple[str, bool], int]], List[str]] = {}
        #: The sets of kinds those keep and state, counted (`kinds_kept`, `kinds_stated_of_a_thing`), with how many sets
        #: were held when they were gathered.
        self._kept_by_act: Dict[str, Tuple[int, Dict[FrozenSet[Tuple[Tuple[str, bool], int]], Counter]]] = {}
        self._stated_of_a_thing: Optional[Tuple[int, Dict[FrozenSet[Tuple[Tuple[str, bool], int]], Counter]]] = None
        #: The adjuncts the held frames show (`Adjunct`), under the first word of each, case aside; and what finds them
        #: as frames arrive (`_note_adjuncts`): each frame under its act and its pieces as written, and under each way
        #: of leaving out a run of its pieces that follows a slot.
        self._adjuncts: Dict[str, List[Adjunct]] = {}
        self._frames_written: Dict[Tuple[str, Tuple[str, ...]], List[str]] = {}
        self._frames_cut: Dict[Tuple[str, Tuple[str, ...]], List[Tuple[str, int, int]]] = {}
        self._lexical_words: Dict[Tuple[str, ...], List[str]] = {}
        self._lexical_loose: Dict[Tuple[str, ...], List[str]] = {}
        self._lexical_value: Dict[str, List[str]] = {}
        self._links: Dict[Tuple[str, str, str], str] = {}
        self._linked: Dict[Tuple[str, str], List[str]] = {}
        #: THE ONE KIND A SLOT TAKES, as `admits_there` reads it off everything linked to the slot. `_linked` only
        #: ever grows, so reading it per call made that scan the cost of a whole pass: teaching WordNet's 144,070
        #: pairs spent 6h09m of a 14h run inside it, 65s per thousand pairs at the start and 460s at the end, while
        #: the store it scanned grew from 12,558 constructions to 323,393. Held per slot, dropped for that slot
        #: alone when a link or a filler arrives (`add`). Absent means not worked out yet; None means the slot takes
        #: anything, which is what all but a mathematical slot does.
        self._filler_kind: Dict[Tuple[str, str], Optional[bool]] = {}
        self._standing_at: Dict[Tuple[str, str], Tuple[int, FrozenSet[Tuple[str, str]]]] = {}
        self._sizes_at: Dict[Tuple[str, str], Tuple[int, FrozenSet[int]]] = {}
        self._frame_words: set = set()
        self._filler_words: set = set()
        self._words: set = set()
        self._named: set = set()
        self._shapes: Dict[str, int] = {}
        self._proper: set = set()
        self._needs: Dict[str, Tuple[FrozenSet[str], FrozenSet[str]]] = {}
        self._ends: set = set()
        # The marks held where more can follow them: in a phrase or a lexical, or in a construction before its last
        # piece (`reads_past`).
        self._inner_marks: set = set()
        self._pattern_keys: List[str] = []
        self._holophrase_keys: List[str] = []
        self._lexical_keys: List[str] = []
        self._link_keys: List[str] = []
        self._links_to: Dict[str, List[Tuple[str, str]]] = {}
        # What reading derives from everything held is kept as each construction and link arrives, never rebuilt
        # from all of it: a vocabulary is taught one pair at a time, and a reading between two pairs must not cost
        # what everything held costs.
        # The kinds: a union-find over the fillers linked to slots, each filler once for each part a slot takes it as
        # (`_taken_as`), with each kind's longest filler and the changes its words are written in (`_join`,
        # `_register`); the parts each filler is held in, and each held frame's slots' parts.
        self._parent: Dict[Tuple[str, str], Tuple[str, str]] = {}
        self._kind_size: Dict[Tuple[str, str], int] = {}
        self._kind_longest: Dict[Tuple[str, str], int] = {}
        self._kind_changes: Dict[Tuple[str, str], set] = {}
        self._same_word: Dict[Tuple[Tuple[str, ...], str, str], Tuple[str, str]] = {}
        self._parts_of: Dict[str, Set[str]] = {}
        self._taken: Dict[Tuple[str, str], Tuple[str, ...]] = {}
        # The classes each word was observed in, with their net evidence (`MemoryAgent.word_classes`): given by the
        # memory that holds them, the same mapping it keeps current as it is taught; none in a view made without it.
        self.word_classes: Mapping[str, Mapping[str, int]] = {}
        # The base words a written word is a form of, as memory holds the forms treebanks showed (`word_forms`,
        # `MemoryAgent.remember_word_forms`); none in a view made without memory.
        self.held_forms: Optional[Callable[[str], Sequence[str]]] = None
        # The word shapes (`_shape_word`): each one-word filler's concepts, the changes that read it rightly, the
        # words ending as each written side, and each change's count and standing.
        self._fillers_by_word: Dict[str, set] = {}
        self._rights: Dict[str, set] = {}
        self._read_by: Dict[Tuple[str, str], set] = {}
        self._endings: Dict[str, set] = {}
        self._by_written: Dict[str, set] = {}
        self._shape_counts: Dict[Tuple[str, str], List[int]] = {}
        self._productive_shapes: set = set()
        self._productive_by_written: Dict[str, set] = {}
        # The words heard right after each word in the sentences taught, and after each two (`hear`), and, as of
        # `_added`, how the words heard after each are written among their concepts' forms (`heard_like`).
        self._heard: Dict[str, Set[str]] = {}
        self._heard_two: Dict[Tuple[str, str], Set[str]] = {}
        self._heard_forms: Dict[Tuple[str, ...], Tuple[Tuple[str, FrozenSet[str]], ...]] = {}
        self._word_forms: Dict[Tuple[str, str], FrozenSet[str]] = {}
        self._together: Dict[Tuple[str, str], bool] = {}
        self._forms_at = -1
        # The letters after each word (`letters_after`), how often each, and the words written right before each slot.
        self._after: Dict[str, set] = {}
        self._after_count: Dict[str, Dict[str, int]] = {}
        self._before_slot: Dict[Tuple[str, str], Tuple[str, ...]] = {}
        # Each slot's fillers: [written as named, written otherwise, of one word or none], and the first words of
        # the longer ones.
        self._slot_tally: Dict[Tuple[str, str], List[int]] = {}
        #: The counting words and every frame by its words and slots, as of `_beside_at` (`counted_beside`).
        self._beside: Tuple[FrozenSet[str], Dict[Tuple[str, ...], List["Pattern"]]] = (frozenset(), {})
        self._beside_at = -1
        self._slot_runs: Dict[Tuple[str, str], Dict[str, int]] = {}
        # The changes each slot's own one-word fillers are written in, without their context ("barked": `ed`):
        # "The dog ?slot1." holding "barks" and "The dog ?slot1." holding "barked" are told apart by them.
        self._slot_changes: Dict[Tuple[str, str], Dict[Tuple[str, str], int]] = {}
        #: Places by the part they stand in in their frame's meaning (`_places_in_role`), as of `_added`.
        self._roles: Dict[FrozenSet[Tuple[Any, ...]], List[Tuple[str, str]]] = {}
        self._roles_at = -1
        #: The shapes each slot takes to say a word in (`shape_of_slot`), as of `_added`.
        self._slot_shapes: Dict[Tuple[str, str, bool], Tuple[Tuple[str, str], ...]] = {}
        self._slot_shapes_at = -1
        #: What a word written in a shape says more than its concept (`said_by`, `shaped_phrases`), as of `_added`.
        #: Found over every shape group's phrases, it was found again for each reading a frame offered: on main, 72%
        #: of the eight minutes "The function sorted returns a new list." took (2026-10-19).
        self._said_by_shape: Dict[Tuple[str, str], List[FrozenSet[Tuple[Any, ...]]]] = {}
        self._phrases_of_shape: Dict[str, List[Tuple[str, FrozenSet[Tuple[Any, ...]], Tuple[str, ...]]]] = {}
        self._shape_says_at = -1
        # Each slot's concepts, with the changes their words there are written in: none for a word written as its
        # name ("cut", where "barked" stands), None for an irregular form ("flew"). What saying counts a change over.
        self._slot_stems: Dict[Tuple[str, str], Dict[str, set]] = {}
        # One-word phrases that are a word of their concept written in a shape and say more of it than its kind
        # ("barked": a barking, before now), grouped by what they say more (`_shape_says`): what a shape adds.
        self._shape_groups: Dict[FrozenSet[Tuple[Any, ...]], Dict[str, Tuple[str, str]]] = {}
        # The changes (their context aside) the words of those groups are written in: what says more than a concept;
        # and each group's own.
        self._shapes_saying_more: set = set()
        self._group_changes: Dict[FrozenSet[Tuple[Any, ...]], set] = {}
        # The words held as one-word phrases that say more than their kind, irregular ones too ("ran", "flew").
        self._saying_words: set = set()
        # Words that alternate in one place of frames otherwise the same and meaning the same (`variants_of`): each
        # frame with one of its words left out, and the words held there; and how often two words alternate.
        self._alternation: Dict[Tuple[Tuple[Any, ...], str], set] = {}
        # Each word's shapes (`variants_of`), known until a letter after a word, or an alternation, is added.
        self._shapes_known: Dict[str, FrozenSet[str]] = {}
        self._alternates: Dict[str, Dict[str, int]] = {}
        # The frames at each such place, with their word there; and each frame's places.
        self._alternation_frames: Dict[Tuple[Tuple[Any, ...], str], Dict[str, str]] = {}
        self._frame_places: Dict[str, List[Tuple[Tuple[Tuple[Any, ...], str], str]]] = {}
        # How the held words are used, for placing a word never held (`use_of`, `slot_admits`), kept as items arrive
        # (`_uses_now`): what each slot is (counted, taking a shape, where a sentence begins); the concepts held in
        # counted slots, and held bare where a sentence begins; the fillers in slots taking a shape; for each kind,
        # its fillers of counted concepts and those of concepts held bare; each filler's use, and the uses each slot
        # and each word hold; and how the words ending alike are used (`_end_*`). Found whole again only when a
        # slot changes what it is, as a view warmed from memory does once, when its first word is asked for.
        self._uses_built = False
        self._added = 0
        # How each slot was filled (`slot_filled`) and how often each part's fillers were met (`parts_met`): what the
        # listener weighs a structure by (`_derivation`), found again when anything is added.
        self._slot_filled: Dict[Tuple[str, str], Tuple[float, int]] = {}
        self._slot_filled_at = -1
        self._parts_met: Dict[str, Tuple[float, int]] = {}
        self._parts_met_at = -1
        self._uses_at = -1
        self._use_pending: List[Tuple[str, str, str]] = []
        self._use_done: set = set()
        self._use_dirty: set = set()
        self._use_entered: set = set()
        self._use_new_names: set = set()
        self._use_changed_words: set = set()
        self._use_slot_state: Dict[Tuple[str, str], Tuple[bool, bool, bool]] = {}
        # What can change a slot's state since the uses were last kept up: its own fillers or its frame arriving
        # (`_use_touched`), the letters after words (whether it is counted), and, for a slot whose fillers are
        # written in a shape (`_use_shaped`), its kind and saying's shapes. A slot whose fillers are written as named
        # takes no shape whatever its kind.
        self._use_touched: set = set()
        self._use_shaped: set = set()
        self._use_letters_moved = False
        self._use_counted: Dict[str, int] = {}
        self._use_counted_as: Dict[Tuple[str, str], int] = {}
        self._use_bare: Dict[str, int] = {}
        self._use_plural: Dict[str, int] = {}
        self._use_noun: Dict[Tuple[str, str], int] = {}
        self._use_bare_keys: Dict[Tuple[str, str], set] = {}
        self._use_key: Dict[str, str] = {}
        self._use_slots: Dict[Tuple[str, str], Dict[str, int]] = {}
        self._use_words: Dict[str, Dict[str, int]] = {}
        # The endings: each word's (written with a capital, use) as they count it; the words of each class kept, and
        # the confidence in its default; each ending's words that end there and go no longer, the longer endings
        # under it, what it passes to the shorter ending while it decides nothing, what it decides, and the endings
        # whose most words are used otherwise than the default, which a change of that confidence can move.
        self._end_word: Dict[str, Tuple[bool, str]] = {}
        self._end_kept: Dict[bool, Dict[str, int]] = {False: {}, True: {}}
        self._end_trusted: Dict[bool, float] = {False: 0.0, True: 0.0}
        self._end_term: Dict[Tuple[bool, str], Dict[str, int]] = {}
        self._end_children: Dict[Tuple[bool, str], set] = {}
        self._end_passed: Dict[Tuple[bool, str], Dict[str, int]] = {}
        self._end_decided: Dict[Tuple[bool, str], str] = {}
        self._end_contested: Dict[bool, set] = {False: set(), True: set()}
        # How each change fares in saying (`said_shapes`), and the productive ones by their change without context:
        # found whole once, then moved by each filler counted (`_said_moved`), in the changes whose cells hold its
        # concept. Found again after ANY addition, it was found again for nearly every sentence a teaching pass
        # learns, each time over everything held: 152 ms at 53,716 held, and WordNet's patterns slowed from 0.18 s a
        # sentence to 0.56 s and climbing (2026-10-08). Found again whole for every filler in a slot written in a
        # change, it took 22 s each time on main, and WordNet's verb forms slowed from two minutes a thousand to
        # half an hour and climbing (2026-10-12).
        self._said: Optional[Tuple[Dict[Tuple[str, str], Tuple[int, int]], FrozenSet[Tuple[str, str]]]] = None
        self._said_by_least: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        # What it is found from: the slots written in each change (its context aside), every change by the end it
        # asks of a concept's name, and the concepts of the slots written as named.
        self._said_slots_of: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        self._said_by_name: Dict[str, set] = {}
        self._said_named: set = set()
        self._score = score or _held_score
        # What the listener counted of its evidence on what it was taught (`listening_worths`): memory's, unless given.
        self._listened = listened or _held_listening_counts
        for item in items:
            self.add(item)

    def add(self, item: Item) -> bool:
        """Index one construction or link, and move what it changes. False when it is already here."""
        key = item.key
        if key in self._by_key:
            return False
        self._by_key[key] = item
        self._added += 1
        # WHAT A SLOT TAKES CHANGES when a link arrives on it, and when a filler already linked to it arrives: the
        # kind is read off `_by_key` for every key linked there, so a filler held after its link moves it too.
        if isinstance(item, Link):
            self._filler_kind.pop((item.pattern, item.slot), None)
        else:
            for place in self._links_to.get(key, ()):
                self._filler_kind.pop(place, None)
        if isinstance(item, (Pattern, Lexical, Phrase)):
            self._words.update(_folded(p.text for p in item.form if isinstance(p, Piece)))
            if isinstance(item, Pattern):
                concepts = item.meaning.constants()
            elif isinstance(item, Lexical):
                concepts = (item.value,)
            else:
                concepts = tuple(t for t in {t for f in item.facts for t in f.terms()} | {item.anchor}
                                 if not is_variable(t))
            # A number or a formula names itself, whole: "a + b" does not make "a" a word that names something. A
            # concept names the word that is its whole name: `color` names "color"; `bill of rights` names no "of",
            # as "A robin" is no filler "A" (`is_structure`). Taken word by word, WordNet's names made "of", "the",
            # "to", "and" and "by" words that name things, and each stood as a new name in any slot.
            self._named.update(name for concept in concepts if not _quantity(str(concept))
                               for name in (_fold(str(concept).replace("_", " ").strip()),) if name and " " not in name)
            # A construction's own last piece meets only the last piece said; a phrase's or a lexical's may meet any.
            inner = item.form[:-1] if isinstance(item, Pattern) else item.form
            self._inner_marks.update(_fold(e.text) for e in inner if isinstance(e, Piece) and _is_mark(e.text))
        if isinstance(item, (Pattern, Phrase)):
            self._use_touched.update((key, slot) for slot in item.slots)
        if isinstance(item, Pattern):
            self._pattern_keys.append(key)
            for e in item.form[1:]:
                if isinstance(e, Piece) and e.text[:1].isupper():
                    self._name_noted(_fold(e.text))
            if item.slots:
                self._item_based.append(key)
                self._note_adjuncts(item)
                pieces = [e.text for e in item.form if isinstance(e, Piece)]
                self._needs[key] = (frozenset(pieces), frozenset(_folded(pieces)))
                own = _fact_kinds(item.meaning.facts)
                for slot in item.slots:
                    used = _fact_kinds(f for f in item.meaning.facts if slot in f.terms())
                    for kept in {frozenset(own.items()), frozenset((own - used).items())}:
                        self._frames_keeping.setdefault((item.meaning.act, kept), []).append((key, slot))
            else:
                self._holophrase_keys.append(key)
                self._holophrase_words.setdefault(item.words, []).append(key)
                self._holophrase_first.setdefault(_first_word(item.words), []).append(key)
                self._holophrase_meaning.setdefault(item.meaning.canonical(), []).append(key)
            if item.slots:
                own = {_fold(e.text) for e in item.form if isinstance(e, Piece)}
                self._frame_words.update(own)
                for word in own:
                    self._shapes[word] = self._shapes.get(word, 0) + 1
            # Words said in each other's place with the same meaning show it in holophrases too ("Yes, it is." and
            # "Yes, she is.").
            self._note_alternation(item, item.meaning.canonical())
            self._join_frame(key)
            if isinstance(item.form[-1], Piece):
                self._ends.add(_fold(item.form[-1].text))
            self._letters_of(item)
        elif isinstance(item, Phrase):
            self._phrase_at[key] = len(self._phrases)
            self._phrases.append(key)
            own = _own_words(item)
            if own:
                # Under the word of its own fewest phrases are under yet ("parsed", not "them"), so a word a reading
                # has finds few it cannot use.
                word = min(own, key=lambda w: len(self._phrases_by_word.get(w, ())))
                self._phrases_by_word.setdefault(word, []).append(key)
            else:
                self._phrases_wordless.append(key)
            for kind in _kinds_named(item):
                self._phrases_of_kind.setdefault(kind, []).append(key)
            self._phrases_stating.setdefault(frozenset(_fact_kinds(item.facts).items()), []).append(key)
            named = _named_in(item)
            self._phrases_naming.setdefault((frozenset(_fact_kinds(item.facts).items()), min(named) if named else None),
                                            []).append(key)
            self._note_shape_phrase(item)
            if self._written_as(item):
                for pattern, slot in self._links_to.get(key, ()):
                    self._count_writing(pattern, slot, *self._written_as(item))
            if item.slots:
                pieces = [e.text for e in item.form if isinstance(e, Piece)]
                self._needs[key] = (frozenset(pieces), frozenset(_folded(pieces)))
                own = {_fold(text) for text in pieces}
                self._frame_words.update(own)
                for word in own:
                    self._shapes[word] = self._shapes.get(word, 0) + 1
                self._note_alternation(item, item.canonical())
            self._join_frame(key)
            self._letters_of(item)
        elif isinstance(item, Lexical):
            self._lexical_keys.append(key)
            self._lexical_words.setdefault(item.words, []).append(key)
            self._lexical_loose.setdefault(_loose(item.words), []).append(key)
            self._lexical_value.setdefault(item.value, []).append(key)
            words = _loose(item.words)
            if len(words) == 1:
                self._filler_words.update(words)
                self._shape_word(words[0], _fold(item.value))
            for pattern, slot in self._links_to.get(key, ()):
                self._filled(pattern, slot, item)
                if self._uses_built:
                    self._use_pending.append((pattern, slot, key))
            if key in self._parts_of:
                self._use_enter(key)
                for part in sorted(self._parts_of[key]):
                    self._register((key, part), item)
        else:
            self._link_keys.append(key)
            self._links[(item.pattern, item.slot, item.lexical)] = key
            self._linked.setdefault((item.pattern, item.slot), []).append(item.lexical)
            self._links_to.setdefault(item.lexical, []).append((item.pattern, item.slot))
            self._join(item.pattern, item.slot, item.lexical)
            self._use_touched.add((item.pattern, item.slot))
            filler = self._by_key.get(item.lexical)
            if isinstance(filler, Lexical):
                self._filled(item.pattern, item.slot, filler)
            elif isinstance(filler, Phrase) and self._written_as(filler):
                self._count_writing(item.pattern, item.slot, *self._written_as(filler))
            if self._uses_built:
                self._use_pending.append((item.pattern, item.slot, item.lexical))
        return True

    def _note_adjuncts(self, frame: Pattern) -> None:
        """The adjuncts a frame just held shows with the frames held before it, as the longer of a pair and as the
        shorter (`_adjunct_of`): found as each frame arrives, never from everything held again. The words added follow
        a slot, begin with a word, and end before the frame's last mark."""
        act = frame.meaning.act
        written = tuple("\x00" if isinstance(e, Slot) else e.text for e in frame.form)
        last = len(written) - (1 if isinstance(frame.form[-1], Piece) and _is_mark(frame.form[-1].text) else 0)
        for start in range(1, last):
            here = frame.form[start]
            if not isinstance(frame.form[start - 1], Slot) or not isinstance(here, Piece) or _is_mark(here.text):
                continue
            for end in range(start + 1, last + 1):
                cut = written[:start] + written[end:]
                self._frames_cut.setdefault((act, cut), []).append((frame.key, start, end))
                for shorter in self._frames_written.get((act, cut), ()):
                    self._adjoin(self._by_key[shorter], frame, start, end)  # type: ignore[arg-type]
        for longer, start, end in self._frames_cut.get((act, written), ()):
            self._adjoin(frame, self._by_key[longer], start, end)  # type: ignore[arg-type]
        self._frames_written.setdefault((act, written), []).append(frame.key)

    def _adjoin(self, shorter: Pattern, longer: Pattern, start: int, end: int) -> None:
        adjunct = _adjunct_of(shorter, longer, start, end)
        if adjunct is not None:
            self._adjuncts.setdefault(_fold(adjunct.form[0].text), []).append(adjunct)  # type: ignore[union-attr]

    def begins_adjunct(self, word: str) -> bool:
        """Whether an adjunct the held frames show begins with this word, case aside."""
        return _fold(word) in self._adjuncts

    def adjuncts_after(self, word: str) -> Tuple[Adjunct, ...]:
        """The adjuncts that begin with this word, case aside, whose frames are both still believed (`Adjunct`)."""
        return tuple(a for a in self._adjuncts.get(_fold(word), ())
                     if self.counts(self._by_key[a.frame]) and self.counts(self._by_key[a.shorter]))

    def _note_proper(self, pattern: str, slot: str, filler: Lexical) -> None:
        """A filler written with a capital in a slot where no sentence begins keeps its capital (`is_proper`): noted
        once the frame, the link and the filler are all held, whichever came last. A view warmed from memory meets
        them in any order."""
        frame = self._by_key.get(pattern)
        if isinstance(frame, (Pattern, Phrase)) and filler.words and filler.words[0][:1].isupper() and frame.form \
                and not (isinstance(frame.form[0], Slot) and frame.form[0].name == slot):
            self._name_noted(_fold(filler.words[0]))

    def _name_noted(self, word: str) -> None:
        """A word that keeps its capital (`is_proper`); how its fillers are used, and how it ends, are found again."""
        if word not in self._proper:
            self._proper.add(word)
            if self._uses_built:
                self._use_new_names.add(word)

    def _letters_of(self, item: Union["Pattern", "Phrase"]) -> None:
        """What a form shows of the letters after its words: a word written after a word, and the first letters of
        the fillers of a slot written after a word. Fillers linked before the form came are noted now, their
        capitals too (`_note_proper`)."""
        for here, there in zip(item.form, item.form[1:]):
            if not isinstance(here, Piece) or _is_mark(here.text):
                continue
            if isinstance(there, Piece):
                if there.text[:1].isalpha():
                    self._letter(_fold(here.text), _fold(there.text[:1]))
            else:
                slot = (item.key, there.name)
                self._before_slot[slot] = self._before_slot.get(slot, ()) + (_fold(here.text),)
        for slot in item.slots:
            for key in self._linked.get((item.key, slot), ()):
                filler = self._by_key.get(key)
                if isinstance(filler, Lexical):
                    self._letter_after(item.key, slot, filler)
                    self._note_proper(item.key, slot, filler)

    def _note_alternation(self, item: Union["Pattern", "Phrase"], meaning: str) -> None:
        """Each word of a frame's own, as one that frames otherwise the same and meaning the same hold in its place."""
        shape = tuple(("slot", e.name) if isinstance(e, Slot) else e.text for e in item.form)
        for index, element in enumerate(item.form):
            if not isinstance(element, Piece) or _is_mark(element.text):
                continue
            place = (shape[:index] + (None,) + shape[index + 1:], meaning)
            words = self._alternation.setdefault(place, set())
            word = _fold(element.text)
            self._shapes_known.clear()
            self._use_letters_moved = True
            for other in words - {word}:
                for one, two in ((word, other), (other, word)):
                    counts = self._alternates.setdefault(one, {})
                    counts[two] = counts.get(two, 0) + 1
            words.add(word)
            self._alternation_frames.setdefault(place, {})[item.key] = word
            self._frame_places.setdefault(item.key, []).append((place, word))

    def twins_of(self, frame: str) -> FrozenSet[str]:
        """The frames that are this one with a word of its own written in another of its shapes ("?slot0 is an
        ?slot1." for "?slot0 is a ?slot1."): one construction, written as the word after it asks."""
        out = set()
        for place, word in self._frame_places.get(frame, ()):
            shapes = self.variants_of(word)
            if shapes:
                out.update(other for other, theirs in self._alternation_frames.get(place, {}).items()
                           if other != frame and theirs in shapes)
        return frozenset(out)

    def variants_of(self, word: str) -> FrozenSet[str]:
        """The words that are this word written in another shape, as the word after it asks: "an" for "a". Two words
        are one in two shapes when frames otherwise the same and meaning the same hold one or the other in the same
        place, in two pairs of frames or more, and the letter after them decides which: the letters written after
        both are, for each, within Yang's tolerance of the letters written after it ("an" before a, e, i, o, "a"
        before consonants, "u" after both). Found from what was taught, never told. Words that alternate after
        the same letters ("is" and "'s") are two ways of saying one thing, not shapes of one word.

        A word's shapes share out the letters among them all, and each word says so of the other (`_shapes_with`):
        "every" alternates with "an", before other letters, but also with "a", before the same ones, so it is no
        shape of the word "a" and "an" are."""
        word = _fold(word)
        if word not in self._shapes_known:
            self._shapes_known[word] = frozenset(other for other in self._shapes_with(word)
                                                 if word in self._shapes_with(other))
        return self._shapes_known[word]

    def _shapes_with(self, word: str) -> FrozenSet[str]:
        """The words alternating with this one, in two pairs of frames or more, that the letter after them tells
        apart from it and from each other: the most alternating first, each kept only if the letters tell it apart
        from all kept before it."""
        kept: List[str] = []
        for other, count in sorted(self._alternates.get(word, {}).items(), key=lambda kv: (-kv[1], kv[0])):
            if count >= 2 and self._told_apart(word, other) and all(self._told_apart(other, k) for k in kept):
                kept.append(other)
        return frozenset(kept)

    def _told_apart(self, one: str, two: str) -> bool:
        """Whether the letter after them decides between two words: for each, the times it is written before a
        letter the other is written before too are within Yang's tolerance of the times it is written at all. "a"
        and "an" are almost never written before the same letter; "it" and "she" both before the "i" of "is"."""
        mine, theirs = self._after_count.get(one), self._after_count.get(two)
        if not mine or not theirs:
            return False
        shared = set(mine) & set(theirs)

        def decided(counts: Dict[str, int]) -> bool:
            # At least two times the letter after it is one the other is never written before, as a productive
            # change needs two words it reads rightly (`_tolerated`); and, as Albright & Hayes judge a rule shown by
            # few words, better than even confidence that it is: "he", written four times, twice before the "i" of
            # "is" as "it" is, is not told apart from "it" by the letter after it.
            total = sum(counts.values())
            crossed = sum(counts[letter] for letter in shared)
            return total - crossed >= 2 and crossed <= total / math.log(total) \
                and _confidence(total - crossed, total) > 0.5

        return decided(mine) and decided(theirs)

    def written_for(self, word: str, following: str) -> FrozenSet[str]:
        """The frame words this word stands for: written in the shape the word after it asks ("an" before "ocelot"
        stands for "a", since "an" is written before an "o" and "a" is not), or said in their place with the same
        meaning (`synonyms_of`: "would" for "could" in "Could you ?slot0 me?")."""
        said = self.synonyms_of(word)
        if not following or not following[:1].isalpha():
            return said
        variants = self.variants_of(word)
        if not variants or self.shape_before(word, following[:1]) != _fold(word):
            return said
        return variants | said

    def synonyms_of(self, word: str) -> FrozenSet[str]:
        """The words said in this one's place, in frames otherwise the same and meaning the same, in two pairs of
        frames or more, and not told apart by the letter after them: two ways of saying one thing ("could" and
        "would" in "Could you close the door?" and "Would you close the door?"). Found from what was taught."""
        word = _fold(word)
        shapes = self.variants_of(word)
        return frozenset(other for other, count in self._alternates.get(word, {}).items()
                         if count >= 2 and other not in shapes and not self._told_apart(word, other))

    def shape_before(self, word: str, letter: str) -> str:
        """Which of a word's shapes is written before a word beginning with this letter: the one written before it
        most often, or, before a letter none of them has been written before, the shape written before the most
        letters, as the elsewhere condition has it ("an" before a, e, i, o; "a" everywhere else, so "a jay")."""
        word, letter = _fold(word), _fold(letter)
        shapes = sorted({word} | self.variants_of(word))
        written = [shape for shape in shapes if letter in self._after.get(shape, ())]
        if written:
            return max(written, key=lambda shape: (self._after_count[shape][letter], shape == word, shape))
        return max(shapes, key=lambda shape: (len(self._after.get(shape, ())), shape == word, shape))

    def _letter_after(self, pattern: str, slot: str, filler: Lexical) -> None:
        if filler.words and filler.words[0][:1].isalpha():
            for here in self._before_slot.get((pattern, slot), ()):
                self._letter(here, _fold(filler.words[0][:1]))

    def _letter(self, word: str, letter: str) -> None:
        self._shapes_known.clear()
        self._use_letters_moved = True
        self._after.setdefault(word, set()).add(letter)
        counts = self._after_count.setdefault(word, {})
        counts[letter] = counts.get(letter, 0) + 1

    def _filled(self, pattern: str, slot: str, filler: Lexical) -> None:
        """A held filler linked to a slot: the letter it begins with after the slot's word before it, how the slot's
        fillers are written (`shape_of_slot`, `filler_openings`), and whether it keeps a capital there."""
        self._letter_after(pattern, slot, filler)
        self._note_proper(pattern, slot, filler)
        words = _loose(filler.words)
        if len(words) == 1:
            # Against the word's own name, as every writing is judged (`_written_as`): "wall" for `object wall`, a
            # sense named apart, is written as its name is.
            self._count_writing(pattern, slot, *self._written_as(filler))
            return
        tally = self._slot_tally.setdefault((pattern, slot), [0, 0, 0, 0])
        if not words:
            tally[2] += 1
        else:
            runs = self._slot_runs.setdefault((pattern, slot), {})
            runs[words[0]] = runs.get(words[0], 0) + 1

    @staticmethod
    def _written_as(item: Any) -> Optional[Tuple[str, str]]:
        """How a filler of one word is written, and the name of what it names: a word and its concept ("barks",
        `bark`), or a phrase of one word and the concept it is an instance of ("barked", `bark`, before now).

        A thing named apart from the others its word names, by what it is a kind of first ("food fish": the food
        "fish" names, beside the animal `fish`), is written as its word is: its name's last word is the word's own
        name, so a word's shape is judged alike whichever thing it names."""
        if isinstance(item, Lexical):
            words = _loose(item.words)
            if len(words) != 1:
                return None
            name = _fold(item.value)
            return words[0], name.split()[-1] if " " in name else name
        if isinstance(item, Phrase) and len(item.form) == 1 and isinstance(item.form[0], Piece):
            kinds = [f for f in item.facts if f.relation == "instance_of" and f.subject == item.anchor
                     and f.positive and not is_variable(f.obj)]
            return (_fold(item.form[0].text), _fold(kinds[0].obj)) if len(kinds) == 1 else None
        return None

    def _count_writing(self, pattern: str, slot: str, word: str, name: str) -> None:
        """One filler of one word in a slot: written as its concept's name or otherwise, in what change, and the
        concept it stands for there (`slot_writing`, `said_shapes`)."""
        before = self.changed_writing(pattern, slot)
        # What the concept gives each change's count before it moves (`_said_moved`).
        given = self._said_stem(name) if self._said is not None else None
        tally = self._slot_tally.setdefault((pattern, slot), [0, 0, 0, 0])
        change = self.shape_between(word, name)
        # A WORD OF ITS OWN, NO SHAPE OF THE NAME, that says no more than its thing is kept apart (`tally[3]`): it is
        # another name ("soul" for `person`) or an irregular form ("Geese"), and its writing cannot tell which
        # (`_written_otherwise` decides it by the slot's other words). One that says more than its thing ("third", a
        # rank of 3; "flew") is written otherwise.
        own = word != name and change is None and not self.says_more(word, name)
        tally[3 if own else 0 if word == name else 1] += 1
        tally[2] += 1
        self._use_touched.add((pattern, slot))
        if change is not None:
            changes = self._slot_changes.setdefault((pattern, slot), {})
            least = self._least(change)
            changes[least] = changes.get(least, 0) + 1
        if self._written_otherwise((pattern, slot)):
            self._use_shaped.add((pattern, slot))
        else:
            self._use_shaped.discard((pattern, slot))
        made = self._slot_stems.setdefault((pattern, slot), {}).setdefault(name, set())
        made.update(self.changes_between(word, name))
        if word != name and change is None:
            made.add(None)      # an irregular form ("geese", "flew"): written otherwise, by no change
        if given is not None:
            after = self.changed_writing(pattern, slot)
            if after == before:
                self._said_moved(name, given, (pattern, slot) if after is not None else None)
            elif before is not None and after is not None:
                # Written in one change more ("stopped": `ped`, where "barked" and "walked" stood): its concepts join
                # the cells of that change too.
                (widened,) = after - before
                self._said_moved(name, given, (pattern, slot), widened=widened)
            else:
                # The slot came to be written in a change, or stopped: every concept in it moves between the cells
                # and the names. Found again whole, as it is when nothing has asked yet.
                self._said = None

    def _written_otherwise(self, where: Tuple[str, str]) -> bool:
        """Whether a slot's one-word fillers are written otherwise than by their concepts' names: those written as
        the name are few enough to be exceptions (Yang's Tolerance Principle, `_tolerated`: "Fish" beside "Dogs",
        "Cats" and "Birds"), or none is written as its name ("Geese" alone; "third", "quarter" for 3 and 4).

        A RULE, NOT A MAJORITY. This was once "most fillers are not written as their concept's name". A word that
        is not its concept's name is not always a shape of it: it may be one more word the thing is called by
        ("peril", "risk" and "jeopardy" for `hazard`). Once each sense was a concept of its own and every word a
        sense is written with was taught, those outnumbered the names: in the sandbox 3,730 of the 4,842 words in
        "A ?slot0 is a ?slot1." were not their concept's name, so the frame was taken to take a shape and every
        noun standing in it to be a plural. "dog" was then never said as it is: "I do not know where the domestic
        dog is." Words written as names in numbers no exception reaches say the slot writes names: 2,524 there,
        against 570 tolerated; 9 of 20 where "red cup" and "usually runs" share a phrase, against 6. A slot that
        takes plurals holds few ("?slot0 are ?slot1.": 16 of 115, against 24)."""
        tally = self._slot_tally.get(where)
        if not tally or not tally[1] + tally[3]:
            return False
        named, shaped, own = tally[0], tally[1], tally[3]
        if not named:
            return True        # none written as its name: "Geese" alone, "third" and "quarter" for 3 and 4
        # A WORD OF ITS OWN GOES WITH THE SLOT'S OTHER WORDS. Where most of the words that show it are in a shape, it
        # is an irregular form ("Geese" beside "Dogs" and "Foxes"); where most are written as named, it is one more
        # name ("soul" beside "person"). Counted as a shape everywhere, the other words a source names a thing by
        # made "Every ?slot0 is an ?slot1." a slot that takes plurals, and said "Every assets is a possession.".
        otherwise = shaped + (own if shaped > named else 0)
        return bool(otherwise) and _tolerated(otherwise, named + otherwise)

    def __len__(self) -> int:
        return len(self._by_key)

    def letters_after(self, word: str) -> FrozenSet[str]:
        """The letters the words written right after this one have begun with, in everything held: after "an",
        the "e" of "eagle", the "o" of "owl"; after "a", the "b" of "bird". How a word's form goes with the next
        word's, found from what was taught."""
        return frozenset(self._after.get(_fold(word), ()))

    # ── what was heard after what ─────────────────────────────────────────────────────────────────────────────────
    # A construction holds its slots' fillers each apart: "might open" and "often opens" made one phrase,
    # "?slot0 ?slot1", and which of its second words goes with which first is not in it. Said from it, "Tom might
    # open the box." came out "Tom may opens the box.". What the sentences taught had right after each word is kept
    # here, as each sentence is learned, and saying puts a word only where a word written as it is was heard
    # (`_unheard`).

    def hear(self, words: Iterable[str]) -> List[Tuple[str, ...]]:
        """Each word of a sentence taught heard right after the one before it ("open" after "might" in "Tom might
        open the box."), and after the two before it ("chase" after "did not", where "has not" is followed by
        "opened"); a mark ends a run. What was not heard before: each pair, and each word with the two before it."""
        new: List[Tuple[str, ...]] = []
        earlier: Optional[str] = None
        before: Optional[str] = None
        for word in words:
            if _is_mark(word) or word == QUOTED:
                earlier = before = None
                continue
            word = _fold(word)
            if before is not None and word not in self._heard.get(before, ()):
                self._heard.setdefault(before, set()).add(word)
                new.append((before, word))
            if earlier is not None and word not in self._heard_two.get((earlier, before), ()):
                self._heard_two.setdefault((earlier, before), set()).add(word)
                new.append((earlier, before, word))
            earlier, before = before, word
        if new:
            self._heard_forms.clear()
        return new

    def heard_after(self, word: str, earlier: Optional[str] = None) -> FrozenSet[str]:
        """The words heard right after this one in the sentences taught; with `earlier`, right after the two."""
        if earlier is not None:
            return frozenset(self._heard_two.get((_fold(earlier), _fold(word)), ()))
        return frozenset(self._heard.get(_fold(word), ()))

    def heard_two(self, word: str) -> Dict[str, FrozenSet[str]]:
        """Of the words heard right before this one, each with the words heard right after the two."""
        word = _fold(word)
        return {earlier: frozenset(after) for (earlier, middle), after in self._heard_two.items() if middle == word}

    def word_form(self, word: str, value: str) -> FrozenSet[str]:
        """How a word is written among its concept's forms, the forms sharing its first two letters: `""` for the
        one the others are made from, its stem ("open" of open, opens, opened and opening, whatever the concept is
        named), `"+"` for a word of its own that says more than its concept ("ran", "swam"), else the change from
        the stem, each way the stem's last letter may join it ("kicked" `ed`; "chased" `d` and `ed`; "swimming"
        `ming` and `ing`; "goes" `es` and `s`). Two words are written alike where these meet."""
        word = _fold(word)
        self._forms_now()
        held = self._word_forms.get((word, value))
        if held is not None:
            return held
        family = {_fold(lx.words[0]) for lx in self.lexicals_with_value(value) if len(lx.words) == 1} | {word}
        stem = min((f for f in family if f[:2] == word[:2]), key=lambda f: (len(f), f))
        change = self.shape_between(word, stem) if word != stem else None
        if change is None:
            form = frozenset({"+"}) if self.says_more(word, value) else frozenset({""})
        elif change[1]:
            form = frozenset({f"{change[0]}/{change[1]}"})
        else:
            written = change[0]
            form = frozenset({written, stem[-1] + written, written[1:]}) - {""}
        self._word_forms[(word, value)] = form
        return form

    def heard_like(self, before: str, word: str, value: str, earlier: Optional[str] = None) -> int:
        """How a word stands right after another, as heard: 0 heard there (or nothing was heard after the other, or
        nothing is held of the word); 1 like what was heard, a word of its kind having been heard there, written as
        it is among its concept's forms (`word_form`), its concept having stood in one slot with this one
        (`stood_together`): "open" after "may", where "go" and "fly" were; 2 never: not "opens" there, not "chased"
        where "kick" and "bark" stand after "did not", and not "October" after "the", where only things were.
        With `earlier`, the word before the other, what was heard after the two is what the word is held against,
        where anything was: "opened" is heard after "has not", never after "did not"."""
        context = self._heard_context(before, earlier)
        after = self._heard_two.get(context) if len(context) == 2 else self._heard.get(context[0])
        if not after or _fold(word) in after or not self._lexical_value.get(value):
            return 0
        self._forms_now()
        heard = self._heard_forms.get(context)
        if heard is None:
            heard = tuple({(lexical.value, self.word_form(other, lexical.value))
                           for other in after for lexical in self.lexicals_with_words((other,), loose=True)
                           if len(lexical.words) == 1})
            self._heard_forms[context] = heard
        form = self.word_form(word, value)
        return 1 if any(form & written and self.stood_together(value, concept) for concept, written in heard) else 2

    def heard_there(self, before: Sequence[str], word: str) -> bool:
        """Whether a word was heard right after these words, the last two at most (`_heard_context`)."""
        if not before:
            return False
        context = self._heard_context(before[-1], before[-2] if len(before) > 1 else None)
        after = self._heard_two.get(context) if len(context) == 2 else self._heard.get(context[0])
        return _fold(word) in (after or ())

    def _heard_context(self, before: str, earlier: Optional[str]) -> Tuple[str, ...]:
        """What a word right after `before` is held against: the two words, where anything was heard after them,
        else the one."""
        before = _fold(before)
        if earlier is not None and (_fold(earlier), before) in self._heard_two:
            return (_fold(earlier), before)
        return (before,)

    def stood_together(self, one: str, other: str) -> bool:
        """Whether two concepts have stood in one slot, in any of their words (`_standing`): `opening` and `go`, both
        after "might"; not `2` and `dog`."""
        if one == other:
            return True
        self._forms_now()
        pair = (one, other) if one <= other else (other, one)
        held = self._together.get(pair)
        if held is None:
            held = any(("concept", other) in self._standing(place)
                       for key in self._lexical_value.get(one, ()) for place in self._links_to.get(key, ()))
            self._together[pair] = held
        return held

    def _forms_now(self) -> None:
        """What `word_form`, `heard_like` and `stood_together` worked out, kept until anything more is held."""
        if self._forms_at != self._added:
            self._word_forms, self._heard_forms, self._together, self._forms_at = {}, {}, {}, self._added

    def __contains__(self, key: str) -> bool:
        return key in self._by_key

    def get(self, key: str) -> Optional[Item]:
        return self._by_key.get(key)

    def items(self) -> Tuple[Item, ...]:
        return tuple(self._by_key.values())

    def patterns(self) -> Tuple[Pattern, ...]:
        return tuple(self._by_key[k] for k in self._pattern_keys)

    def holophrases(self) -> Tuple[Pattern, ...]:
        return tuple(self._by_key[k] for k in self._holophrase_keys)

    def item_based(self) -> Tuple[Pattern, ...]:
        return tuple(self._by_key[k] for k in self._item_based)

    def lexicals(self) -> Tuple[Lexical, ...]:
        return tuple(self._by_key[k] for k in self._lexical_keys)

    def phrases(self) -> Tuple[Phrase, ...]:
        return tuple(self._by_key[k] for k in self._phrases)

    def phrases_reading(self, have: Iterable[str]) -> Tuple[Phrase, ...]:
        """The phrases that may read words among `have` (what they are, and what they stand for written in another
        shape), in the order they were held: those with a word of their own among them, case aside, and those with
        none. A phrase reads words only where each word of its own is one of them (`_chunkings`). Every phrase was
        tried for every run of words in every sentence read, and phrases are learned as fast as sentences: WordNet's
        verb forms learned one each, and each sentence took longer than the last (2 minutes a thousand to 28, on
        main, 2026-10-13)."""
        keys = set(self._phrases_wordless)
        for word in {_fold(w) for w in have}:
            keys.update(self._phrases_by_word.get(word, ()))
        return tuple(self._by_key[k] for k in sorted(keys, key=self._phrase_at.__getitem__))

    def phrases_of_kind(self, kind: str) -> Tuple["Phrase", ...]:
        """The phrases naming a thing of their own as of this kind ("compiled them", "is compiling them": a
        compiling), in the order they were held."""
        return tuple(self._by_key[k] for k in self._phrases_of_kind.get(kind, ()) if k in self._by_key)

    def saying(self, words: Tuple[str, ...], concept: str, forms: Iterable[str] = ()) -> Tuple[Construction, ...]:
        """The constructions that say a word names a thing: the word held for it, case aside; the word in one of
        its forms held for it ("ran" for `run`, as the lessons hold it in "Tom ran."); and the phrases naming a thing
        of that kind in one of the word's forms ("had them", "is having them", for "have" naming a having). Where a
        count of the word's uses lands (`learn_usage`): landed on the phrases and not on "ran", "Tom ran." was the
        fleeing "run" names 38 times in real use, counted through its phrase, not the running it names 106."""
        wanted = str(concept).strip().lower()
        lexical = next((lx for lx in self.lexicals_with_words(words)
                        + self.lexicals_with_words(tuple(w.lower() for w in words), loose=True)
                        if lx.value.lower() == wanted), None)
        written = {_fold(form) for form in forms}
        in_forms = [lx for form in sorted(written) for lx in self.lexicals_with_words((form,), loose=True)
                    if lx.value.lower() == wanted]
        phrases = [phrase for phrase in self.phrases_of_kind(str(concept)) if written & set(_own_words(phrase))]
        return tuple({c.key: c for c in ([lexical] if lexical is not None else []) + in_forms + phrases}.values())

    def links(self) -> Tuple[Link, ...]:
        return tuple(self._by_key[k] for k in self._link_keys)

    def with_words(self, words: Tuple[str, ...], loose: bool = False) -> Tuple[Pattern, ...]:
        """The holophrases with exactly these words; or, `loose`, the ones that begin with the same word, for a loose
        reading to compare in full."""
        if loose:
            return tuple(self._by_key[k] for k in self._holophrase_first.get(_first_word(words), ()))
        return tuple(self._by_key[k] for k in self._holophrase_words.get(tuple(words), ()))

    def frames_keeping(self, act: str, kinds: Counter) -> Tuple[Tuple[Pattern, str], ...]:
        """The frames of this act, each with a slot, that state these kinds of fact with a phrase in that slot: all
        their own, or all but those of the slot a phrase standing for a thing describes (`_composed`)."""
        return tuple((self._by_key[k], slot) for k, slot in self._frames_keeping.get((act, frozenset(kinds.items())), ()))

    def kinds_kept(self, act: str) -> Dict[FrozenSet[Tuple[Tuple[str, bool], int]], Counter]:
        """Every set of kinds of fact some frame of this act states with a phrase in a slot (`frames_keeping`), each
        counted; gathered again only once frames keep a set not kept before."""
        cached = self._kept_by_act.get(act)
        if cached is None or cached[0] != len(self._frames_keeping):
            cached = (len(self._frames_keeping), {kept: Counter(dict(kept)) for held, kept in self._frames_keeping
                                                  if held == act})
            self._kept_by_act[act] = cached
        return cached[1]

    def kinds_stated_of_a_thing(self) -> Dict[FrozenSet[Tuple[Tuple[str, bool], int]], Counter]:
        """Every set of kinds of fact a phrase states that says a kind of thing (an `instance_of`), less that one
        (`_phrases_holding_phrases`), each counted; gathered again only once phrases state a set not stated before."""
        if self._stated_of_a_thing is None or self._stated_of_a_thing[0] != len(self._phrases_stating):
            one = Counter({("instance_of", True): 1})
            rests: Dict[FrozenSet[Tuple[Tuple[str, bool], int]], Counter] = {}
            for stated in self._phrases_stating:
                counted = Counter(dict(stated))
                if counted[("instance_of", True)] >= 1:
                    rest = counted - one
                    rests[frozenset(rest.items())] = rest
            self._stated_of_a_thing = (len(self._phrases_stating), rests)
        return self._stated_of_a_thing[1]

    def phrases_stating(self, kinds: Counter, within: Optional[AbstractSet[str]] = None) -> Tuple[Phrase, ...]:
        """The phrases stating exactly these kinds of fact; `within`, of those only the ones every concept they name
        is among (`_named_in`), in the order they were held. A phrase says part of a meaning only where the meaning
        names what it names: "strolled" says no walking. Every phrase of the kinds was composed with every frame, and
        once WordNet's verb forms were learned, saying "To stroll is to walk." tried tens of thousands ("strolls",
        "parses", each a doing of its own) and took minutes (2026-10-13)."""
        kinds_held = frozenset(kinds.items())
        if within is None:
            return tuple(self._by_key[k] for k in self._phrases_stating.get(kinds_held, ()))
        keys = set(self._phrases_naming.get((kinds_held, None), ()))
        for concept in within:
            keys.update(k for k in self._phrases_naming.get((kinds_held, concept), ())
                        if _named_in(self._by_key[k]) <= within)
        return tuple(self._by_key[k] for k in sorted(keys, key=self._phrase_at.__getitem__))

    def with_meaning(self, canonical: str) -> Tuple[Pattern, ...]:
        """The holophrases with exactly this meaning."""
        return tuple(self._by_key[k] for k in self._holophrase_meaning.get(canonical, ()))

    def lexicals_with_words(self, words: Tuple[str, ...], loose: bool = False) -> Tuple[Lexical, ...]:
        index = self._lexical_loose if loose else self._lexical_words
        return tuple(self._by_key[k] for k in index.get(tuple(words), ()))

    def is_structure(self, word: str) -> bool:
        """Whether held constructions use this word as part of a frame and never as a filler on its own: the words
        English builds its frames from, found from use, never told. A word inside a longer filler ("A robin") is
        not a filler on its own."""
        word = _fold(word)
        return word in self._frame_words and word not in self._filler_words

    def builds_more_than_it_names(self, word: str) -> bool:
        """Whether held frames are written with this word more often than it is held naming things: "a", in 158
        frames and naming seven things (the ampere, the angstrom, adenine ...), is English's article first. A
        structure word (`is_structure`) names none; WordNet taught "a", "in", "at" and "I" each a sense, and they
        stopped counting as structure, so "a lockstitch" stood as one new name."""
        word = _fold(word)
        return self._shapes.get(word, 0) > len(self._fillers_by_word.get(word, ()))

    def ends(self) -> FrozenSet[str]:
        """The pieces held constructions end on: where an utterance can end, as far as anything taught says."""
        return frozenset(self._ends)

    def reads_past(self, pieces: Sequence[Piece]) -> bool:
        """Whether a reading can go on past every mark before the last of these pieces: each is a mark some held
        construction holds where more follows it, or a hyphen joining two words into one ("four-group"). No filler
        takes in a mark that parts words (`_parted`), and such a mark said is met only by the same mark in a
        construction, so past one nothing holds so, nothing held reads on."""
        return all(_fold(p.text) in self._inner_marks for k, p in enumerate(pieces[:-1])
                   if _is_mark(p.text) and not _joins(pieces, k))

    def is_proper(self, word: str) -> bool:
        """Whether this word has been written with a capital where no sentence begins ("Monday" in "Tuesday follows
        Monday."): a name that keeps its capital. A capital seen only where a sentence begins ("Milk is white.") is
        the writing's, not the word's."""
        return _fold(word) in self._proper

    def knows(self, word: str) -> bool:
        """Whether any held construction has this word, in any case: as a filler, or as a form's own word."""
        return _fold(word) in self._words

    def names_nothing(self, word: str) -> bool:
        """Whether this word builds sentences and names nothing, as far as what was taught says: held only as part
        of forms (`is_structure`), in more than one shape of sentence, and never the name of a concept any taught
        meaning holds. "the" is such a word. "color", held only inside "What color is the ?slot0?", is not: that
        question's meaning names the concept `color`. Nor is "bats", held only in "Bats are not ?slot0.": one
        shape is one sighting of a word, not evidence that it builds sentences. Nor is a word written in a productive
        change (`written_in_shape`) from the name of a concept a taught meaning holds: "jumped", held only inside
        "The ?slot0 jumped onto the ?slot1." and "The ?slot0 jumped over the ?slot1.", names `jump`. A change
        merely shown by two words is a list of words, and applies to no other: taken so, "of" was "o" written with
        "f", "is" was "i" with "s", and "with" was "wit" with "h"."""
        word = _fold(word)
        if not (self.is_structure(word) and word not in self._named and self._shapes.get(word, 0) > 1):
            return False
        for size in range(1, len(word)):
            for written, names in self._productive_by_written.get(word[len(word) - size:], ()):
                name = word[:len(word) - len(written)] + names
                if name in self._named and self.written_in_shape(word, name):
                    return False
        return True

    def may_read(self, pattern: str, words: FrozenSet[str], loose: bool) -> bool:
        """Whether every word of this item-based construction's own is among these words (case folded and marks
        aside, `loose`): a construction can read words only where its own words are."""
        exact, folded = self._needs[pattern]
        return (folded if loose else exact) <= words

    # ── kinds: fillers linked to a common slot, as the slot takes them, are one kind, and a kind is everything ──────
    #    reachable that way

    def _find(self, node: Tuple[str, str]) -> Tuple[str, str]:
        parent = self._parent
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def _union(self, one: Tuple[str, str], other: Tuple[str, str]) -> None:
        first, second = self._find(one), self._find(other)
        if first == second:
            return
        if self._kind_size[first] < self._kind_size[second]:
            first, second = second, first
        self._parent[second] = first
        self._kind_size[first] += self._kind_size.pop(second)
        self._kind_longest[first] = max(self._kind_longest.get(first, 0), self._kind_longest.pop(second, 0))
        if second in self._kind_changes:
            self._kind_changes.setdefault(first, set()).update(self._kind_changes.pop(second))
        if self._uses_built:
            # One kind now: a kind of counted things for both, when either was, so its fillers held bare are used
            # without "a" (`_use_found`).
            nouns, absorbed = self._use_noun.get(first, 0), self._use_noun.pop(second, 0)
            bare, taken_in = self._use_bare_keys.get(first, set()), self._use_bare_keys.pop(second, set())
            if absorbed and not nouns:
                self._use_dirty |= bare
            if nouns and not absorbed:
                self._use_dirty |= taken_in
            if absorbed:
                self._use_noun[first] = nouns + absorbed
            if taken_in:
                self._use_bare_keys.setdefault(first, set()).update(taken_in)

    def _taken_at(self, pattern: str, slot: str) -> Tuple[str, ...]:
        """What a held frame's slot takes its fillers as (`_taken_as`), kept: a frame never changes; nothing while
        the frame is not held."""
        place = (pattern, slot)
        taken = self._taken.get(place)
        if taken is None:
            frame = self._by_key.get(pattern)
            if not isinstance(frame, (Pattern, Phrase)):
                return ()
            taken = self._taken[place] = _taken_as(frame, slot)
        return taken

    def _join(self, pattern: str, slot: str, lexical: str) -> None:
        """A link puts its filler in the kind of its slot's first filler, in each part the slot takes it as
        (`_taken_as`) -- and of the same slot of every frame that is this one with a word of its own written in another
        shape (`twins_of`): "Every ?slot0 is a ?slot1." and "Every ?slot0 is an ?slot1." are one construction, so
        what fills one fills the other's kind. What a slot takes its fillers as is its frame's to say: a link held
        before its frame joins when the frame comes (`_join_frame`)."""
        self._join_link(pattern, slot, lexical)
        self._join_twins(pattern)

    def _join_link(self, pattern: str, slot: str, lexical: str) -> None:
        first = self._linked[(pattern, slot)][0]
        for part in self._taken_at(pattern, slot):
            for node in ((first, part), (lexical, part)):
                self._enter(node)
            self._union((first, part), (lexical, part))

    def _join_frame(self, frame: str) -> None:
        """A frame now held: the fillers linked to its slots before it came join their kinds."""
        item = self._by_key[frame]
        for slot in item.slots:
            for lexical in self._linked.get((frame, slot), ()):
                self._join_link(frame, slot, lexical)
        self._join_twins(frame)

    def _enter(self, node: Tuple[str, str]) -> None:
        """A filler in a kind of its own, in one part, until a link joins it to another."""
        if node in self._parent:
            return
        self._parent[node] = node
        self._kind_size[node] = 1
        key, part = node
        self._parts_of.setdefault(key, set()).add(part)
        item = self._by_key.get(key)
        if isinstance(item, Lexical):
            if part == "thing" and key in self._use_entered:
                self._use_thing(key)
            else:
                self._use_enter(key)
            self._register(node, item)

    def _join_twins(self, pattern: str) -> None:
        """A frame's slots, one kind with the same slots of its twins, where both hold fillers."""
        item = self._by_key.get(pattern)
        if not isinstance(item, (Pattern, Phrase)):
            return
        for twin in self.twins_of(pattern):
            for slot in item.slots:
                mine, theirs = self._linked.get((pattern, slot)), self._linked.get((twin, slot))
                if not (mine and theirs):
                    continue
                for part in set(self._taken_at(pattern, slot)) & set(self._taken_at(twin, slot)):
                    one, other = (mine[0], part), (theirs[0], part)
                    if one in self._parent and other in self._parent:
                        self._union(one, other)

    def _register(self, node: Tuple[str, str], lexical: Lexical) -> None:
        """A held filler of some kind: its length and the change it is written in count for its kind, and it is one
        word with every filler that names the same concept written with the same letters, in any case ("Birds"
        opening a sentence, "birds" ending one), or written as that concept's name changed at its end ("Robins" and
        "robin", "Children" and "child"), taken as the same part. Whether the change is productive does not matter
        here: that says whether it applies to words never seen, and both of these are held."""
        root = self._find(node)
        words = _loose(lexical.words)
        self._kind_longest[root] = max(self._kind_longest.get(root, 0), len(words))
        if len(words) == 1:
            change = self.shape_between(words[0], lexical.value)
            if change is not None:
                self._kind_changes.setdefault(root, set()).add(change)
                words = (_fold(lexical.value),)
        self._union(self._same_word.setdefault((words, lexical.value, node[1]), node), node)

    def _kinds_of_slot(self, pattern: str, slot: str) -> Tuple[Tuple[str, str], ...]:
        """The kind of a slot's first filler in each part the slot takes it as."""
        linked = self._linked.get((pattern, slot))
        if not linked:
            return ()
        return tuple(self._find((linked[0], part)) for part in self._taken_at(pattern, slot)
                     if (linked[0], part) in self._parent)

    def longest_filler(self, pattern: str, slot: str) -> int:
        """How many words the longest filler of this slot's kind has: the longest a name in that slot has been."""
        return max((self._kind_longest.get(kind, 0) for kind in self._kinds_of_slot(pattern, slot)), default=0)

    def same_kind(self, pattern: str, slot: str, lexical: str) -> bool:
        """Whether this filler is of the same learned kind as a filler linked to this slot, taken as the slot takes
        it (`_taken_as`) -- or, a number, stands where numbers or formulas stand: 12 is the kind of thing 7 is
        wherever 7 stood, whether or not the two ever filled one slot.

        A NUMBER IS ONE WHERE ITS WRITING SAYS SO (`_quantity`: "12", "2 + 3"), OR WHERE ITS WORD IS HELD ONLY AS THE
        NUMBER'S NAME ("Fifteen is a number."): what it names is all it is, and "There are fifteen cats." counts
        fifteen. A word held in a number's place of its own -- a rank ("first", for 1), a power ("cubed", for 3) --
        is what it is there, and stands where its kind does: taken for the number it names, "first amendment" was
        one amendment."""
        linked = self._linked.get((pattern, slot), ())
        if linked and any((lexical, part) in self._parent and (linked[0], part) in self._parent
                          and self._find((lexical, part)) == self._find((linked[0], part))
                          for part in self._taken_at(pattern, slot)):
            return True
        item = self._by_key.get(lexical)
        if not (isinstance(item, Lexical) and _quantity(item.value)
                and any(isinstance(self._by_key.get(key), Lexical) and _quantity(self._by_key[key].value)
                        for key in linked)):
            return False
        return _quantity(item.surface) or self._parts_of.get(lexical, set()) <= {"thing"}

    #: The part of the meaning language each class of English word stands in: an adjective where qualities stand, a
    #: verb where doings do. A noun needs none: WordNet's kinds, said ("A robin is a bird."), put its nouns where
    #: things stand.
    #: AN ADVERB AND AN ADJECTIVE ARE ONE PART. `_role_of_term` takes whatever a thing OR A HAPPENING
    #: `has_property` as a `quality` and names an adverb among its own examples ("red", "warily"): a quality said of
    #: a thing is written as an adjective and one said of a doing as an adverb, and the meaning language knows no
    #: third part. Held with no entry here, `class_parts` answered nothing for a word whose only class is ADVERB,
    #: `of_its_class` ends `return bool(taken) and ...`, and so an adverb could never stand where a quality stands
    #: by its class -- while nothing could say it is no thing either: "Tom walked annoyingly." was read
    #: `done_to(?v0, annoyingly)`, the adverb taken as the thing walked, with its ADVERB evidence held all along
    #: (lyric_db, 2026-11-08).
    CLASS_PARTS = {"ADJECTIVE": "quality", "VERB": "doing", "ADVERB": "quality"}

    def of_its_class(self, pattern: str, slot: str, lexical: str) -> bool:
        """Whether a held one-word filler stands where this slot's fillers do by its word's class: observed an
        ADJECTIVE (net of what refuted it), where the slot takes qualities; a VERB, where it takes doings
        (`CLASS_PARTS`, `_taken_at`).

        A WORD NEVER SEEN IN A SENTENCE OF ITS PART HAS ITS CLASS TO GO BY. Kinds are learned from the slots fillers
        stood in, and WordNet says most of its adjectives in no sentence (no frame says what one is like), or only
        where kinds stand ("Hot is the opposite of cold."): no adjective but the lessons' few could stand where a
        quality does, and "Cars are fast." read as cars being a kind called fast; of 120 never-taught sentences
        saying a quality, 5 found the reading (2026-10-12). Its class is memory, from WordNet's tagged counts and the
        sentences that were said."""
        item = self._by_key.get(lexical)
        if not isinstance(item, Lexical) or len(item.words) != 1:
            return False
        # WHERE THE FRAME RELATES CONCEPTS OF ANY PART ("Is ?slot0 the opposite of ?slot1?": hot and cold, buy and
        # sell, day and night), a word stands as its class is, its kinds left where they are: the slot takes things
        # as kinds join them, and an adjective given its words only where qualities stand ("outgoing") was read in
        # no such question (66 of 100 opposites unread, UNDERSTANDS-WORDNET-01, 2026-10-13).
        here = set(self._taken_at(pattern, slot))
        if self.takes_any_part(pattern, slot):
            here |= set(self.CLASS_PARTS.values())
        # AND A WORD OBSERVED A NOUN STANDS WHERE THINGS DO. `CLASS_PARTS` holds ADJECTIVE and VERB and no NOUN, so
        # `class_parts` could never answer `thing`, and no sense of a noun ever stood in a slot by its word's class.
        # "The note was long." put ONE of the three senses of "note" memory holds to the listener: `comment note`,
        # `musical notation note` and `debt instrument note` were each met, each counted, each marked as having stood
        # as a thing, and all three refused, because "note" is held a noun AND a verb and the verb's `doing` was the
        # whole of what its class could say against a slot taking `thing`. The listener then said "the only meaning
        # the words have", which was true of what it was handed and not of what memory holds (lyric_talk,
        # 2026-11-08). Taken here and not in `CLASS_PARTS`, which `_may_stand_new` also reads: a word never met
        # standing as a thing anywhere is a fan-out over the vocabulary, where this offers only the senses of the
        # words being read -- a word's own, three for "note".
        parts = self.class_parts(item.words[0])
        if self.word_classes.get(_fold(item.words[0]), {}).get("NOUN", 0) > 0:
            parts = parts | {"thing"}
        taken = parts & here
        # A SENSE STANDS BY ITS WORD'S CLASS ONLY IN A PART IT HAS STOOD IN, OR WHERE IT HAS STOOD NOWHERE, OR WHERE THE
        # WORD THAT NAMES IT IS OF THAT CLASS. A class is the word's, not each sense's: "glimpse" is a verb and a noun,
        # and its noun sense, a glance (`look glance`), stood only where things do; through its word's class the
        # glance was a doing, and a telephone exchange ("workplace central") a quality ("Faith is central."). A sense
        # that stood as a doing ("walk", in the lessons' events) is a doing where any slot takes doings, its kind there
        # not yet joined to the slot's: kept out, "To stroll is to walk." could not be said, and no verb WordNet holds
        # could stand where english_41's do. A sense named by an adjective (`surprised`) is that adjective's, wherever
        # it first stood: held only where "Surprised is the opposite of unsurprised." put it, with things, it was kept
        # out of every slot a quality stands in (80 of the 121 rules WordNet's adjectives could not say, 2026-10-12).
        stood = self._parts_of.get(lexical)
        return bool(taken) and (not stood or bool(taken & (stood | self.class_parts(str(item.value)))))

    def slot_filled(self, pattern: str, slot: str) -> Tuple[float, int]:
        """How a slot was filled, as held: the uses of its held links, all told, and how many fillers they put there."""
        if self._slot_filled_at != self._added:
            self._slot_filled, self._slot_filled_at = {}, self._added
        place = (pattern, slot)
        held = self._slot_filled.get(place)
        if held is None:
            uses, fillers = 0.0, 0
            for filler in self._linked.get(place, ()):
                link = self._by_key.get(self._links.get((pattern, slot, filler), ""))
                if link is not None and self.counts(link):
                    uses += self.uses(link)
                    fillers += 1
            held = self._slot_filled[place] = (uses, fillers)
        return held

    def parts_met(self) -> Dict[str, Tuple[float, int]]:
        """For each part of the meaning language, how often its held fillers were met, all told, and how many there
        are: each word in each part it stood in, or that its class stands in (`class_parts`)."""
        if self._parts_met_at != self._added:
            met: Dict[str, List[float]] = {}
            for key in self._lexical_keys:
                lexical = self._by_key.get(key)
                if not isinstance(lexical, Lexical):
                    continue
                parts = set(self._parts_of.get(key, ()))
                if len(lexical.words) == 1:
                    parts |= self.class_parts(lexical.words[0])
                if not parts:
                    continue
                uses = _met(self, lexical)
                for part in parts:
                    held = met.setdefault(part, [0.0, 0])
                    held[0] += uses
                    held[1] += 1
            self._parts_met = {part: (held[0], held[1]) for part, held in met.items()}
            self._parts_met_at = self._added
        return self._parts_met

    def takes_any_part(self, pattern: str, slot: str) -> bool:
        """Whether every fact a frame states of this slot relates concepts of any part (`RelationSpec.of_any_part`:
        opposites, synonyms)."""
        frame = self._by_key.get(pattern)
        facts = frame.meaning.facts if isinstance(frame, Pattern) else frame.facts if isinstance(frame, Phrase) else ()
        uses = [f for f in facts if slot in f.terms()]
        return bool(uses) and all(_of_any_part(f.relation) for f in uses)

    def class_parts(self, word: str) -> Set[str]:
        """The parts of the meaning language a word's class stands in (`CLASS_PARTS`): `quality` for a word observed
        an ADJECTIVE, `doing` for a VERB, net of what refuted it; none for a word of several, or of no such class."""
        classes = self.word_classes.get(_fold(word), {})
        return {self.CLASS_PARTS[c] for c, n in classes.items() if n > 0 and c in self.CLASS_PARTS}

    def lexicals_with_value(self, value: str) -> Tuple[Lexical, ...]:
        return tuple(self._by_key[k] for k in self._lexical_value.get(value, ()))

    def link_between(self, pattern: str, slot: str, lexical: str) -> Optional[Link]:
        key = self._links.get((pattern, slot, lexical))
        return self._by_key.get(key) if key else None  # type: ignore[return-value]

    def fillers(self, pattern: str, slot: str) -> Tuple[Union[Lexical, "Phrase"], ...]:
        """What is linked to one slot: words (`Lexical`) and phrases (`Phrase`) both. A reader of a word's own
        parts (`value`, its one word) checks which it has."""
        return tuple(self._by_key[k] for k in self._linked.get((pattern, slot), ()) if k in self._by_key)

    def score(self, item: Item) -> float:
        return self._score(item)[0]

    def listening_worths(self) -> Dict[Tuple[str, int], float]:
        """What each piece of the listener's evidence is worth, in nats, as it counted it (`listening_worths`)."""
        return listening_worths(self._listened())

    def uses(self, item: Item) -> int:
        return self._score(item)[1]

    def counts(self, item: Item) -> bool:
        """Whether a construction takes part in reading and speaking: while a taught pair still reads through it,
        some witness's latest word on it a use. Its belief ranks it among the readings, a competitor's lower, and
        nothing more.

        The paper keeps a construction until its entrenchment reaches 0, a competition costing three uses, so one that
        lost a little stays, ranked lower (Doumen, Beuls & Van Eecke 2024, §4.2.8). Taken out below even instead, one
        lost competition took a construction out of reading: "squared" names 2, used twice and outcompeted twice,
        read nothing, and "Five squared is twenty-five.", which only it reads, with it (english_01-39 taught again,
        2026-10-11: six sentences taught and understood that no longer read). A holophrase whose every pair is now
        read through a more general construction has no use standing, and drops out as the paper's do. It stays in
        memory, and a pair that needs it again revives it."""
        return self._score(item)[2]

    def reading(self, constructions: Tuple[Construction, ...], links: Tuple[Link, ...],
                meaning: Meaning, *, proposed: Tuple[Link, ...] = (), new: Tuple[Lexical, ...] = (),
                loose: bool = False, said_for: int = 0, sized: int = 0) -> "Reading":
        scores = [self._score(c) for c in constructions]
        misfits, apart = self.fits(constructions, links, proposed)
        return Reading(constructions, links, meaning,
                       sum(s for s, _, _ in scores) / len(scores), sum(u for _, u, _ in scores) / len(scores),
                       proposed=proposed, new=new, loose=loose, misfits=misfits, said_for=said_for,
                       apart=sized + apart)

    def fits(self, constructions: Tuple[Construction, ...], links: Tuple[Link, ...],
             proposed: Tuple[Link, ...]) -> Tuple[int, int]:
        """How the fillers a reading proposed links for fit where they stand: how many are written otherwise than
        the slot's own fillers (`written_against`), and how many held ones never stood beside them (`stood_beside`)."""
        # A filler a taught pair linked stands where it was taught; one a link is only proposed for is judged by
        # how the slot's own fillers are written.
        fillers = {c.key: c for c in constructions if isinstance(c, (Lexical, Phrase))}

        def against(held: Link) -> bool:
            filler = fillers[held.lexical]
            if not isinstance(filler, Phrase) or len(filler.form) == 1:
                return self.written_against(held.pattern, held.slot, filler)
            # A PHRASE OF SEVERAL WORDS IS JUDGED BY THE WORD IT WRITES FIRST, as one word is, and as saying judges
            # it: its own, as the kind of thing it names, or what stands in its first slot here. "kicked the ball",
            # never linked to "?slot0 ?slot1." whose own are "bark" and "run", read "Tom kicked the ball." as a
            # kicking at no time and tied with the reading taught.
            head = filler.form[0]
            if isinstance(head, Slot):
                key = next((l.lexical for l in links + proposed if l.pattern == filler.key and l.slot == head.name),
                           None)
                return key in fillers and self.written_against(held.pattern, held.slot, fillers[key])
            kinds = [f.obj for f in filler.facts if f.relation == "instance_of" and f.subject == filler.anchor
                     and f.positive and not is_variable(f.obj)]
            return len(kinds) == 1 and self.word_against(held.pattern, held.slot, _fold(head.text),
                                                         _fold(kinds[0]).split()[-1])

        misfits = sum(1 for held in proposed if held.lexical in fillers and against(held))
        apart = sum(1 for held in proposed if held.lexical in self._by_key
                    and not self.stood_beside(held.pattern, held.slot, held.lexical))
        return misfits, apart

    def stood_beside(self, pattern: str, slot: str, filler: str) -> bool:
        """Whether a held filler has stood, in some other slot, beside one of this slot's own fillers, as the concept
        they stand for (`_standing`). A kind is everything any slot ever joined, so it grows wide; what has filled a
        place the slot's own fillers fill is like them where a kind alone cannot say: "snow" for `snowing` stood with "rain" in "It will ?slot0.", and
        "snow" the stuff never stood where "rain", "bark" and "go" stand.

        IN A PLACE TAKING IT AS THIS SLOT DOES (`_taken_as`): standing beside a slot's fillers as something else is
        no likeness to them. "amendment" stood beside "three" where things stand ("Three is a number."), and was
        taken for a count where "three" counts ("amendment part": amendment-many parts)."""
        own = self._standing((pattern, slot))
        if not own:
            return False
        parts = set(self._taken_at(pattern, slot))
        # Where the concept has stood, in any of its words: "sleep" stood where "sleeps" did, beside "barks" in
        # "The ?slot0 ?slot1.". Only the bare word's own places looked at, "Cats sleep." did not read.
        item = self._by_key.get(filler)
        keys = {filler} | (set(self._lexical_value.get(item.value, ())) if isinstance(item, Lexical) else set())
        return any(place != (pattern, slot) and not parts.isdisjoint(self._taken_at(*place))
                   and not own.isdisjoint(self._standing(place))
                   for key in keys for place in self._links_to.get(key, ()))

    def admits_there(self, pattern: str, slot: str, value: str) -> bool:
        """Whether a concept may stand in a slot for what the slot has held. A slot that has held two fillers or more,
        all of them mathematics -- numbers, formulas, letters for unknowns, phrases that build a number -- takes only
        mathematics: "What is ?slot0?", taught with "2 + 3" and "x", asks what a quantity comes to, and "water" is no
        quantity. One that has held two or more, none of them mathematics, takes none: "What is ?slot0?", taught
        with "water" and "milk", asks what kind of thing it is, and "7 × 8" comes to a number."""
        place = (pattern, slot)
        if place in self._filler_kind:
            kind = self._filler_kind[place]
        else:
            kinds = [kind for key in self._linked.get(place, ())
                     for kind in (_filler_mathematical(self._by_key.get(key)),) if kind is not None]
            kind = kinds[0] if len(kinds) >= 2 and len(set(kinds)) == 1 else None
            self._filler_kind[place] = kind
        return True if kind is None else _mathematical(value) == kind

    def sized_apart(self, pattern: str, slot: str, value: str) -> bool:
        """Whether a whole number stands apart from what a number phrase's slot is taught: every word linked to the
        slot is a whole number, two sizes of them or more are known -- a size being how many groups of three digits
        it is written in -- and this one is of none of them. English builds numbers in groups of three: the words a
        scale word multiplies ("three", "twelve", "three hundred and twelve") are all under a thousand, so
        "seven trillion three hundred and twelve" never stands there, however the words could be grouped."""
        if not value.isdigit():
            return False
        sizes = self._sizes(pattern, slot)
        return bool(sizes) and _size(value) not in sizes

    def _sizes(self, pattern: str, slot: str) -> FrozenSet[int]:
        place = (pattern, slot)
        kept = self._sizes_at.get(place)
        if kept is not None and kept[0] == self._added:
            return kept[1]
        frame = self._by_key.get(pattern)
        values = [item.value for key in self._linked.get(place, ()) for item in (self._by_key.get(key),)
                  if isinstance(item, Lexical)]
        numbers = isinstance(frame, Phrase) and bool(frame.facts) and all(f.relation in _ARITHMETIC
                                                                           for f in frame.facts)
        sizes = (frozenset(_size(v) for v in values)
                 if numbers and len(set(values)) >= 2 and all(v.isdigit() for v in values) else frozenset())
        self._sizes_at[place] = (self._added, sizes)
        return sizes

    def _standing(self, place: Tuple[str, str]) -> FrozenSet[Tuple[str, str]]:
        """What stands in a slot, as `stood_beside` compares it: a word by its concept, in whatever shape it is
        written ("barked" and "bark" both stand for `bark`), a phrase as itself. Kept until anything more is held.

        A SLOT OF A FRAME'S TWINS IS THE SAME PLACE ("A ?slot0 is an ?slot1." for "A ?slot0 is a ?slot1."): one
        construction, its word written as the word after it asks. Kept apart, what stood there was split by the
        first letter of the next word: "wing", taught in "A wing is an organ.", never stood where "ball" and "door"
        stand, and its readings of "The wing is long." were set aside for supposing more."""
        kept = self._standing_at.get(place)
        if kept is not None and kept[0] == self._added:
            return kept[1]
        pattern, slot = place
        # Twins of twins too: "An ?slot0 is an ?slot1." is "A ?slot0 is a ?slot1." with two words in their other
        # shape, and each twin differs in one.
        frames, frontier = {pattern}, [pattern]
        while frontier:
            for twin in self.twins_of(frontier.pop()):
                if twin not in frames:
                    frames.add(twin)
                    frontier.append(twin)
        places = tuple((frame, slot) for frame in frames)
        standing = frozenset(("concept", item.value) if isinstance(item, Lexical) else ("phrase", key)
                             for where in places
                             for key in self._linked.get(where, ()) for item in (self._by_key.get(key),)
                             if item is not None)
        self._standing_at[place] = (self._added, standing)
        return standing

    # ── word shapes: how a filler's written word differs from its concept's name ──────────────────────────────────

    @staticmethod
    def shape_between(word: str, name: str) -> Optional[Tuple[str, str]]:
        """The change at the end of a word that makes it from a concept's name, `(written, name's)`: "dogs" from
        `dog` is `("s", "")`, "flies" from `fly` is `("ies", "y")`. None when they share no stem of two letters (an
        irregular form, "geese" for `goose`, is a word of its own) or are the same."""
        word, name = _fold(word), _fold(name)
        if word == name or " " in word or " " in name:
            return None
        stem = 0
        while stem < min(len(word), len(name)) and word[stem] == name[stem]:
            stem += 1
        if stem < 2:
            return None
        return word[stem:], name[stem:]

    @classmethod
    def changes_between(cls, word: str, name: str) -> Tuple[Tuple[str, str], ...]:
        """The change that makes this word from this name, and the same change with each run of the letters before
        it, as Albright & Hayes (2003) give a change its context: "boxes" from `box` is `("es", "")`, `("xes", "x")`
        and `("oxes", "ox")`. A context stops one letter short of the word's start."""
        change = cls.shape_between(word, name)
        if change is None:
            return ()
        written, names = change
        folded = _fold(word)
        stem = folded[:len(folded) - len(written)]
        return tuple((stem[len(stem) - k:] + written, stem[len(stem) - k:] + names) for k in range(len(stem)))

    def _one_word_fillers(self) -> Dict[str, set]:
        """Each word a one-word filler is written with (case aside), and the concepts it names."""
        return self._fillers_by_word

    def word_shapes(self) -> Dict[Tuple[str, str], Tuple[int, int]]:
        """Every change at a word's end the held fillers show, in each context of letters before it, with how it
        fares over the words it applies to: `{(written, name's): (words it reads rightly, words it applies to)}`. A
        word applies when it ends as the change's written side; it is read rightly when it is a filler of the concept
        the change makes of it. Found from what was taught, never told (Albright & Hayes 2003: a change, in a
        context, scored over the words it covers).

        The more particular change comes first, as the elsewhere condition orders rules: a word that a productive
        change with a longer written side reads rightly, where this one would misread it, is that change's and is
        not held against this one. "flies" is `ies` → `y`'s and no exception to `s`; "boxes" is `xes` → `x`'s."""
        return {change: (counts[0], counts[1]) for change, counts in self._shape_counts.items()}

    def productive(self, shape: Tuple[str, str]) -> bool:
        """Whether a change is applied to words it was not seen in: shown by at least two words, and misreading no
        more of the words it applies to than Yang's tolerance threshold allows, N / ln N (Yang 2016). Below that it
        is a list of words, each held on its own."""
        return shape in self._productive_shapes

    @staticmethod
    def _counted(change: Tuple[str, str], rights: Collection[Tuple[str, str]], longest: int) -> Tuple[int, int]:
        """What one word the change applies to adds to its count, (read rightly, applies), given the changes that
        read the word rightly and the longest written side of a productive one among them (`_longest`): nothing,
        where a productive change with a longer written side reads it rightly and this one would not."""
        if change in rights:
            return 1, 1
        if longest > len(change[0]):
            return 0, 0
        return 0, 1

    @staticmethod
    def _longest(rights: Iterable[Tuple[str, str]], productive: set, besides: Optional[Tuple[str, str]] = None) -> int:
        """The longest written side of a productive change among those that read a word rightly, `besides` aside;
        -1 where none is. Asked once of each word, not again for each change its endings have: 60 million times
        that was most of main's warm (2026-10-21)."""
        return max((len(change[0]) for change in rights if change in productive and change != besides), default=-1)

    def _shape_word(self, word: str, name: str) -> None:
        """One more one-word filler, written `word` and naming `name`, taken into the word shapes. Only what it
        changes moves: the count of each change the word ends as, the changes it shows for the first time, and,
        where a change becomes productive or stops being so, the words that change reads (`_settle`)."""
        names = self._fillers_by_word.get(word)
        if names is not None and name in names:
            return
        seen = names is not None
        if names is None:
            names = self._fillers_by_word[word] = set()
            for size in range(len(word)):
                self._endings.setdefault(word[len(word) - size:], set()).add(word)
        names.add(name)
        before = frozenset(self._rights.get(word, ()))
        added = set(self.changes_between(word, name)) - before
        if seen and not added:
            return
        after = before | added
        if after:
            self._rights[word] = set(after)
        for change in added:
            self._read_by.setdefault(change, set()).add(word)
        fresh = {change for change in added if change not in self._shape_counts}
        for change in fresh:
            self._by_written.setdefault(change[0], set()).add(change)
            counts = [0, 0]
            for other in self._endings.get(change[0], ()):
                rights = self._rights.get(other, ())
                right, applies = self._counted(change, rights, self._longest(rights, self._productive_shapes))
                counts[0] += right
                counts[1] += applies
            self._shape_counts[change] = counts
        touched = set(fresh)
        longest_before = self._longest(before, self._productive_shapes)
        longest_after = self._longest(after, self._productive_shapes)
        for size in range(len(word)):
            for change in self._by_written.get(word[len(word) - size:], ()):
                if change in fresh:
                    continue
                old = self._counted(change, before, longest_before) if seen else (0, 0)
                new = self._counted(change, after, longest_after)
                if old != new:
                    counts = self._shape_counts[change]
                    counts[0] += new[0] - old[0]
                    counts[1] += new[1] - old[1]
                    touched.add(change)
        self._settle(touched)

    def _settle(self, touched: Iterable[Tuple[str, str]]) -> None:
        """Whether each touched change is productive, decided again, the longest written side first. A change that
        becomes productive, or stops being so, moves the count of each shorter change applying to a word it reads
        rightly: the elsewhere condition gives that word to the longer change only while it is productive."""
        heap = [(-len(change[0]), change) for change in touched]
        heapq.heapify(heap)
        while heap:
            _, change = heapq.heappop(heap)
            now = _tolerated(*self._shape_counts[change])
            was = change in self._productive_shapes
            if now == was:
                continue
            if now:
                self._productive_shapes.add(change)
                self._productive_by_written.setdefault(change[0], set()).add(change)
            else:
                self._productive_shapes.discard(change)
                self._productive_by_written.get(change[0], set()).discard(change)
            for word in self._read_by.get(change, ()):
                rights = self._rights[word]
                longest = self._longest(rights, self._productive_shapes, besides=change)
                for size in range(len(change[0])):
                    other = longest > size
                    if other:
                        continue          # a longer productive change reads the word: this one moves nothing here
                    for shorter in self._by_written.get(word[len(word) - size:], ()):
                        if shorter in rights:
                            continue
                        if now != was:
                            self._shape_counts[shorter][1] += -1 if now else 1
                            heapq.heappush(heap, (-size, shorter))

    def written_in_shape(self, word: str, name: str) -> bool:
        """Whether a productive change makes this word from this name: "Robins" is `robin` written in a shape."""
        return any(self.productive(change) for change in self.changes_between(word, name))

    def names_of_shape(self, word: str) -> List[str]:
        """The held words a word no filler holds is written as: the word itself when it is a held concept's own name
        ("fox", where only "Foxes" is held), then the held words a treebank showed it a form of (`held_forms`), then
        the word written in a productive shape of a held word or name ("tables" is "table" when `s` is a shape), the
        most particular change first."""
        word = _fold(word)
        fillers = self._fillers_by_word

        def held(name: str) -> bool:
            return name in fillers or bool(self._lexical_value.get(name))

        out: List[str] = [word] if word not in fillers and self._lexical_value.get(word) else []
        # A FORM A TREEBANK SHOWED of a held word is that word ("came" `come`, "hired" `hire`), before any change found
        # productive in the fillers held, which "-ed" never was (`word_forms`, 2026-10-19).
        if self.held_forms is not None:
            for base in self.held_forms(word):
                if held(base) and base not in out:
                    out.append(base)
        for size in range(len(word) - 1, -1, -1):
            for written, names in sorted(self._productive_by_written.get(word[len(word) - size:], ())):
                base = word[:len(word) - len(written)] + names
                if held(base) and base not in out:
                    out.append(base)
        return out

    def holding(self, word: str) -> Tuple[Lexical, ...]:
        """The fillers held for a word: those written as it, case aside; with none, those of the concept it names, a
        concept's own name being a way to write it, as saying writes it ("fox", where only "Foxes" is held)."""
        return self.lexicals_with_words((_fold(word),), loose=True) or self.lexicals_with_value(_fold(word))

    def said_shapes(self) -> Tuple[Dict[Tuple[str, str], Tuple[int, int]], FrozenSet[Tuple[str, str]]]:
        """Every change the held fillers show, scored as saying uses it, and those productive so. Yang (2016) counts
        a rule over the stems it applies to, in the forms it makes: a change is scored over the concepts whose words
        stand in the slots written in it (where their own fillers show it, `slot_writing`), and is right for a
        concept whose word there it makes ("dog", "Dogs"; "bark", "barks"; "box" by `es` after an `x`). So words
        that only end as shapes do ("kindness", "grass", "scissors") say nothing of how "dog" is said, nor does a verb
        seen only as "barked" of how "barks" is; an irregular form in those slots ("ran", "geese"), or one written
        as its name ("cut", where "barked" stands) that is seen as its name elsewhere too ("fish"), is an exception.
        A word held only in slots written in a shape, and only as its name ("scissors"), has no form the change
        could be made from, and is none of its business.

        The more particular change comes first, the longer name side first: a concept a productive change with a
        longer name side makes rightly, where this one would not, is that change's ("box" is `xes` after `x`'s and
        no exception to `s`)."""
        if self._said is None:
            self._said_found()
        return self._said

    def _said_found(self) -> None:
        """`said_shapes`, found whole: from the slots written in a change, every change their words show there,
        each scored over its cell, the more particular first."""
        # The slots written in each change (its context aside), and every change their words there show.
        slots_of: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        every: set = set()
        for where, changes in self._slot_changes.items():
            # A slot whose fillers are mostly written as named ("red", "big", and "recently" among them) is not
            # written in a change, whatever one filler there shows.
            if self.changed_writing(*where) is None:
                continue
            if changes:
                for made in self._slot_stems.get(where, {}).values():
                    every.update(made)
            for least in changes:
                slots_of.setdefault(least, []).append(where)
        every.discard(None)
        named = {stem for where, stems in self._slot_stems.items() if self.changed_writing(*where) is None
                 for stem in stems}
        counts: Dict[Tuple[str, str], Tuple[int, int]] = {}
        productive: set = set()
        # EACH CHANGE IS SCORED OVER THE STEMS OF THE SLOTS WRITTEN IN IT THAT END AS ITS NAME SIDE DOES, found in
        # each slot by that ending, never copied. Every stem of those slots was copied into a cell for each change
        # they are written in, and every change scanned its cell: "?slot0 are ?slot1." holds 20,525 plural words
        # written in 2,734 changes, 56 million copies, and on main every word teaching linked there built this again
        # for four minutes (2026-10-11).
        asked: Dict[Tuple[str, str], set] = {}
        for change in every:
            for where in slots_of.get(self._least(change), ()):
                asked.setdefault(where, set()).add(change[1])
        ending: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        for where, ends in asked.items():
            by_end = ending[where] = {}
            sizes = sorted({len(end) for end in ends})
            for stem in self._slot_stems.get(where, {}):
                for size in sizes:
                    if size < len(stem) and stem[len(stem) - size:] in ends:
                        by_end.setdefault(stem[len(stem) - size:], []).append(stem)
        self._said_slots_of, self._said_named = slots_of, named
        for change in sorted(every, key=self._said_order):
            places = slots_of.get(self._least(change), ())
            if len(places) == 1:
                stems = self._slot_stems.get(places[0], {})
                cell = {stem: stems[stem] for stem in ending.get(places[0], {}).get(change[1], ())}
            else:
                # A word standing in several slots written in the change shows there what it shows in any.
                cell = {}
                for where in places:
                    stems = self._slot_stems.get(where, {})
                    for stem in ending.get(where, {}).get(change[1], ()):
                        cell.setdefault(stem, set()).update(stems[stem])
            right = covered = 0
            for stem, made in cell.items():
                one, other = self._said_part(change, stem, made, productive)
                right += one
                covered += other
            counts[change] = (right, covered)
            if _tolerated(right, covered):
                productive.add(change)
        self._said_by_name = {}
        for change in every:
            self._said_by_name.setdefault(change[1], set()).add(change)
        self._said = (counts, frozenset(productive))
        self._said_by_least = {}
        for change in productive:
            self._said_by_least.setdefault(self._least(change), []).append(change)

    @staticmethod
    def _said_order(change: Tuple[str, str]) -> Tuple[int, int, Tuple[str, str]]:
        """The order changes are decided in: the longer name side first, then the longer written side."""
        return -len(change[1]), -len(change[0]), change

    def _said_part(self, change: Tuple[str, str], stem: str, made: Iterable[Optional[Tuple[str, str]]],
                   productive: Collection[Tuple[str, str]]) -> Tuple[int, int]:
        """What one concept in a change's cell gives its count, `(right, applies)`, from the changes its words in the
        cell's slots show (`made`): right where it is one of them; nothing where it shows none and is named in no
        slot written as named ("scissors"); nothing where a productive change with a longer name side makes it
        rightly instead (the elsewhere condition); else one it applies to and misses."""
        made = tuple(made)
        if change in made:
            return 1, 1
        if not made and stem not in self._said_named:
            return 0, 0
        if any(o is not None and len(o[1]) > len(change[1]) and o in productive for o in made):
            return 0, 0
        return 0, 1

    def _said_made(self, change: Tuple[str, str], stem: str) -> Optional[set]:
        """The changes a concept's words show in the slots written in a change (its context aside), or None when it
        stands in none of them."""
        made: Optional[set] = None
        for where in self._said_slots_of.get(self._least(change), ()):
            shown = self._slot_stems.get(where, {}).get(stem)
            if shown is not None:
                made = set(shown) if made is None else made | shown
        return made

    def _said_stem(self, stem: str, shorter: Optional[int] = None) -> Dict[Tuple[str, str], Tuple[int, int]]:
        """What one concept gives the count of each change whose cell holds it (`_said_part`); `shorter`: of the
        changes with a name side shorter than that only."""
        productive = self._said[1] if self._said is not None else frozenset()
        out: Dict[Tuple[str, str], Tuple[int, int]] = {}
        for size in range(len(stem) if shorter is None else min(len(stem), shorter)):
            for change in self._said_by_name.get(stem[len(stem) - size:], ()):
                made = self._said_made(change, stem)
                if made is not None:
                    out[change] = self._said_part(change, stem, made, productive)
        return out

    def _said_cell(self, change: Tuple[str, str]) -> Dict[str, set]:
        """Every concept in a change's cell, with the changes its words there show: those of the slots written in
        it whose names end as its name side does and are longer."""
        cell: Dict[str, set] = {}
        side = change[1]
        for where in self._said_slots_of.get(self._least(change), ()):
            for stem, shown in self._slot_stems.get(where, {}).items():
                if len(stem) > len(side) and stem.endswith(side):
                    cell.setdefault(stem, set()).update(shown)
        return cell

    def _said_moved(self, stem: str, given: Dict[Tuple[str, str], Tuple[int, int]],
                    where: Optional[Tuple[str, str]], *, widened: Optional[Tuple[str, str]] = None) -> None:
        """What one filler counted moves in `said_shapes`: what its concept gives each change, before (`given`) and
        now; a change its words show for the first time, scored over its cell; and each change whose being
        productive that moves decided again (`_said_settle`). `where`: the slot, when it is written in a change;
        None, when it is written as named, where the filler can only name a concept no such slot named before ("dog"
        in "A ?slot0 is a ?slot1.", where "Dogs" stands in "?slot0 bark."). `widened`: a change (its context aside)
        the slot is written in now and was not before; the slot's other concepts join its cells, and what each gives
        the changes of it moves too."""
        counts, productive = self._said
        others: Dict[str, Dict[Tuple[str, str], Tuple[int, int]]] = {}
        if widened is not None:
            others = {other: {change: part for change, part in self._said_stem(other).items()
                              if self._least(change) == widened}
                      for other in self._slot_stems.get(where, {}) if other != stem}
            self._said_slots_of.setdefault(widened, []).append(where)
        fresh: set = set()
        if where is None:
            self._said_named.add(stem)
        else:
            for change in self._slot_stems.get(where, {}).get(stem, ()):
                if change is None or change in counts:
                    continue
                self._said_by_name.setdefault(change[1], set()).add(change)
                right = covered = 0
                for other, made in self._said_cell(change).items():
                    one, two = self._said_part(change, other, made, productive)
                    right += one
                    covered += two
                counts[change] = (right, covered)
                fresh.add(change)
        touched = set(fresh)
        for concept, before in [(stem, given)] + list(others.items()):
            now = self._said_stem(concept)
            if concept != stem:
                now = {change: part for change, part in now.items() if self._least(change) == widened}
            for change in set(before) | set(now):
                if change in fresh:
                    continue
                was, then = before.get(change, (0, 0)), now.get(change, (0, 0))
                if was != then:
                    right, covered = counts[change]
                    counts[change] = (right + then[0] - was[0], covered + then[1] - was[1])
                    touched.add(change)
        self._said_settle(touched)

    def _said_settle(self, touched: Iterable[Tuple[str, str]]) -> None:
        """Whether each touched change is productive, decided again in the order they are decided in, the longer
        name side first (`_said_order`). A change that becomes productive, or stops being so, moves what each
        concept in its cell showing it gives the changes with a shorter name side: the elsewhere condition gives
        that concept to the longer change only while it is productive."""
        counts, decided = self._said
        productive = set(decided)
        heap = [(self._said_order(change), change) for change in touched]
        heapq.heapify(heap)
        moved = False
        while heap:
            _, change = heapq.heappop(heap)
            now = _tolerated(*counts[change])
            if now == (change in productive):
                continue
            moved = True
            before = {stem: self._said_stem(stem, shorter=len(change[1]))
                      for stem, made in self._said_cell(change).items() if change in made}
            if now:
                productive.add(change)
                self._said_by_least.setdefault(self._least(change), []).append(change)
            else:
                productive.discard(change)
                held = self._said_by_least[self._least(change)]
                held.remove(change)
                if not held:
                    del self._said_by_least[self._least(change)]
            self._said = (counts, frozenset(productive))
            for stem, gave in before.items():
                for other, then in self._said_stem(stem, shorter=len(change[1])).items():
                    was = gave.get(other, (0, 0))
                    if was != then:
                        right, covered = counts[other]
                        counts[other] = (right + then[0] - was[0], covered + then[1] - was[1])
                        heapq.heappush(heap, (self._said_order(other), other))
        if moved:
            self._said = (counts, frozenset(productive))

    def shape_of_slot(self, pattern: str, slot: str, *, said: bool = False) -> Tuple[Tuple[str, str], ...]:
        """The shapes a slot takes: when its one-word fillers are written otherwise than their concept's name
        (`_written_otherwise`: "Dogs", "Cats", "Geese" in "?slot0 can ?slot1."), the changes productive in saying
        (`said_shapes`), in any context, of the changes the words of its kind are written in, the most particular
        first (the longest run of a name's letters it asks for, then the change more concepts show); none when they
        are written as the name is. A word the same both ways ("Fish") is written as the name; a word of its own
        ("Geese"; "peril" for `hazard`) says nothing either way beside names."""
        if not self._written_otherwise((pattern, slot)):
            return ()
        if self._slot_shapes_at != self._added:
            self._slot_shapes, self._slot_shapes_at = {}, self._added
        held = self._slot_shapes.get((pattern, slot, said))
        if held is None:
            held = self._slot_shapes[(pattern, slot, said)] = self._shapes_of_slot(pattern, slot, said)
        return held

    def _shapes_of_slot(self, pattern: str, slot: str, said: bool) -> Tuple[Tuple[str, str], ...]:
        """`shape_of_slot`, worked out."""
        # THE PLACE'S OWN WRITING, NOT ITS KIND'S. A kind joins every word that ever shared a slot, and words that are
        # a thing and a doing ("run", "walk") join the things with the doings: their kind is written "barked" and
        # "barking" as well as "dogs", and "reasoning" said as a kind came out "reasoned". So: the changes this
        # slot's fillers show (and its twins'), and those of the frame's other places, where they say nothing more
        # of the thing than it is (not "-ed", a doing before now); to say a word (`said`), those of every place
        # standing in the same part of a meaning too ("All ?slot0 are ?slot1." beside "?slot0 are ?slot1.", both
        # what a kind is said of: "rubies", "ponies"). The kind's only for a slot showing no change at all (only
        # irregular forms, "Geese").
        # Kept as the groups are added to: found here for every slot whose state was asked, over every group, it was
        # most of the time saying took once a pass had learned anything (2026-10-13).
        saying = self._shapes_saying_more
        frames = (pattern, *self.twins_of(pattern))
        written = {c for frame in frames for c in self._slot_changes.get((frame, slot), {})}
        item = self._by_key.get(pattern)
        others = [(frame, other) for frame in frames for other in (item.slots if isinstance(item, Pattern) else ())
                  if other != slot]
        # To say a word, the places in the same part of a meaning as any place of the frame are added to the
        # frame's own: taken instead, the second place of "?slot0 are ?slot1." had only the changes its own fillers
        # showed, "-s", and said "Appendices are processs." beside "Bases are supports."; and "All ?slot0 are
        # ?slot1.", "All chapeaux are headdresss.".
        places = [place for each in ((slot,) + tuple(other for _, other in others))
                  for place in self._places_in_role(pattern, each)] + others if said else others
        # A PLACE IS IN THE SLOT'S SHAPE ONLY WHERE IT WRITES WHAT IT SHARES WITH THE SLOT AS THE SLOT DOES. One in the
        # same part of a meaning writing a concept the slot holds otherwise is another shape: "runs" ("Tom says that
        # the dog ?slot3.") beside "running" ("Tom likes ?slot2."), borrowed, said "Tom wants swims.". One in another
        # part shares the slot's shape only where it shows one of the slot's own changes: the places of "?slot0 are
        # ?slot1." are both plurals, and "likes" in "?slot0 ?slot1 ?slot2." is no shape of "running".
        own = {}
        for frame in frames:
            for filler in self.fillers(frame, slot):
                if isinstance(filler, Lexical) and len(filler.words) == 1:
                    own.setdefault(filler.value, set()).add(_fold(filler.words[0]))
        own_least = {self._least(c) for c in written}
        in_role = set(self._places_in_role(pattern, slot))

        def alike(place: Tuple[str, str]) -> bool:
            if place in in_role:
                return not any(isinstance(filler, Lexical) and len(filler.words) == 1 and filler.value in own
                               and _fold(filler.words[0]) not in own[filler.value]
                               for filler in self.fillers(*place))
            return not own_least or any(self._least(c) in own_least for c in self._slot_changes.get(place, {}))
        written |= {c for place in places if alike(place) for c in self._slot_changes.get(place, {}) if c not in saying}
        if not written:
            written = {c for kind in self._kinds_of_slot(pattern, slot) for c in self._kind_changes.get(kind, ())
                       if self._least(c) not in saying}
        counts, _ = self.said_shapes()
        family = [change for least in written for change in self._said_by_least.get(least, ())]
        return tuple(sorted(family, key=lambda c: (-len(c[1]), -counts[c][0], -len(c[0]), c)))

    def _places_in_role(self, pattern: str, slot: str) -> Tuple[Tuple[str, str], ...]:
        """Every place, in any frame, standing in the same part of a meaning as this one (`_role`)."""
        if self._roles_at != self._added:
            roles: Dict[FrozenSet[Tuple[Any, ...]], List[Tuple[str, str]]] = {}
            for item in self._by_key.values():
                if isinstance(item, Pattern):
                    for place in item.slots:
                        roles.setdefault(self._role(item, place), []).append((item.key, place))
            self._roles, self._roles_at = roles, self._added
        item = self._by_key.get(pattern)
        if not isinstance(item, Pattern):
            return ()
        return tuple(self._roles.get(self._role(item, slot), ()))

    @staticmethod
    def _role(pattern: "Pattern", slot: str) -> FrozenSet[Tuple[Any, ...]]:
        """The part a slot stands in in its frame's meaning: the facts it is a side of, by relation and side; where it
        is the kind of some thing, what is said of that thing too, so a doing's kind (`done_by`, `precedes`) and a
        thing's kind (`has_property`) are told apart."""
        facts = pattern.meaning.facts
        role = set()
        for fact in facts:
            if slot == fact.subject:
                role.add((fact.relation, "subject", fact.positive))
            if slot == fact.obj:
                role.add((fact.relation, "object", fact.positive))
                if fact.relation == "instance_of":
                    role.update(("of", f.relation, "subject" if f.subject == fact.subject else "object")
                                for f in facts if f is not fact and fact.subject in (f.subject, f.obj))
        return frozenset(role)

    def _note_shape_phrase(self, phrase: "Phrase") -> None:
        """A phrase of one word, its concept's word written in a shape, that says more of it than its kind: what it
        says more is kept, with the phrases that say the same (`shaped_phrases`)."""
        if phrase.slots or len(phrase.form) != 1 or not isinstance(phrase.form[0], Piece):
            return
        kinds = [f for f in phrase.facts if f.relation == "instance_of" and f.subject == phrase.anchor
                 and f.positive and not is_variable(f.obj)]
        if len(kinds) != 1:
            return
        word, name = _fold(phrase.form[0].text), _fold(kinds[0].obj)
        says = frozenset((f.relation, "@" if f.subject == phrase.anchor else f.subject,
                          "@" if f.obj == phrase.anchor else f.obj, f.positive)
                         for f in phrase.facts if f is not kinds[0])
        if word == name or not says:
            return
        self._saying_words.add(word)
        change = self.shape_between(word, name)
        if change is not None:
            self._shape_groups.setdefault(says, {})[phrase.key] = (word, name)
            self._shapes_saying_more.add(self._least(change))
            self._group_changes.setdefault(says, set()).add(self._least(change))

    def says_more(self, word: str, name: str, *, doing: bool = True) -> bool:
        """Whether a word, written from this name, is one that says more than its concept: held as a phrase that
        does ("ran": a running, before now), or written in a change that the phrases saying more are written in
        ("closed": `d`, as "chased" and "tied" are). Such a word stands for its bare concept only where it was
        taught to.

        `doing`: whether the concept is a happening. What a change says more of a happening ("before now", "done
        by what was spoken of") it says of happenings only: of a thing (`doing` False) the change says more only
        where phrases naming things say so. Asked of every word alike, WordNet's verbs said of something ("It
        dwindles.", "It incurvates.", 21 of them on the sandbox) made `s` say that something before did it, of
        "pirates" and "concepts" too, and no plural stood for the things its word names (2026-10-14)."""
        word, name = _fold(word), _fold(name)
        if word == name:
            return False
        if word in self._saying_words and doing:
            return True
        change = self.shape_between(word, name)
        if change is None:
            return False
        least = self._least(change)
        return any(len(members) >= 2 and least in self._group_changes.get(says, ()) and _says_of_happening(says) == doing
                   for says, members in self._shape_groups.items())

    def stands_as_doing(self, lexical: Lexical) -> bool:
        """Whether a filler names a happening: it stood where doings do, or, standing nowhere yet, its one word's
        class stands there (`class_parts`)."""
        parts = self._parts_of.get(lexical.key) or (self.class_parts(lexical.words[0]) if len(lexical.words) == 1
                                                    else set())
        return "doing" in parts

    def said_by(self, word: str, name: str) -> List[FrozenSet[Tuple[Any, ...]]]:
        """What a word written from this name says more than its concept, each way it does (`@` for the thing
        named): as the held phrases of its shape show, or as its change would make of it ("walked": before now)."""
        word, name = _fold(word), _fold(name)
        self._shapes_now()
        found = self._said_by_shape.get((word, name))
        if found is None:
            held = [says for says, members in self._shape_groups.items() if (word, name) in members.values()]
            found = self._said_by_shape[(word, name)] = held or [
                says for made, says, _ in self.shaped_phrases(word) if made == name]
        return list(found)

    def _shapes_now(self) -> None:
        """What `said_by` and `shaped_phrases` worked out, kept until anything more is held."""
        if self._shape_says_at != self._added:
            self._said_by_shape, self._phrases_of_shape, self._shape_says_at = {}, {}, self._added

    def said_in_shape(self, word: str, name: str) -> List[FrozenSet[Tuple[Any, ...]]]:
        """What a word written from a name memory holds it for says more than that name: as `said_by`, else what the
        phrases written in the word's own change say of a happening, as `says_more` finds it ("breathes" from
        `breathe` is written in `s`, as "barks" and "heals" are: done by what was spoken of)."""
        found = self.said_by(word, name)
        if found:
            return found
        change = self.shape_between(_fold(word), _fold(name))
        if change is None:
            return []
        least = self._least(change)
        return [says for says, members in self._shape_groups.items()
                if len(members) >= 2 and least in self._group_changes.get(says, ()) and _says_of_happening(says)]

    def shaped_phrases(self, word: str) -> List[Tuple[str, FrozenSet[Tuple[Any, ...]], Tuple[str, ...]]]:
        """For a word none holds, what each shape that says more than a kind would make of it: the name it is written
        from, what the shape says (with `@` for the thing named), and the held phrases that show it ("jumped":
        `jump`, before now, as "barked" and "walked" show). The change is the one Albright & Hayes's confidence
        ranks first over the words of that shape ending as this one does: taking "ed" off is right for "barked",
        "walked" and "helped", "d" only for "closed" and "tied", so "jumped" is `jump`."""
        word = _fold(word)
        self._shapes_now()
        kept = self._phrases_of_shape.get(word)
        if kept is not None:
            return list(kept)
        out = []
        for says, members in self._shape_groups.items():
            if len(members) < 2:
                continue
            shown = {change for w, n in members.values() for change in self.changes_between(w, n)}
            best = None
            for change in shown:
                written, names = change
                if not word.endswith(written) or len(word) - len(written) + len(names) < 2:
                    continue
                scope = [(w, n) for w, n in members.values() if w.endswith(written)]
                hits = sum(1 for w, n in scope if change in self.changes_between(w, n))
                rank = (_confidence(hits, len(scope)), len(written), len(names), change)
                if best is None or rank > best:
                    best = rank
            if best is not None and best[0] > 0:
                written, names = best[3]
                out.append((word[:len(word) - len(written)] + names, says, tuple(members)))
        self._phrases_of_shape[word] = out
        return list(out)

    def slot_writing(self, pattern: str, slot: str) -> Optional[FrozenSet[Tuple[str, str]]]:
        """How a slot's own one-word fillers are written: None when they are written as their concept's name
        (`_written_otherwise`: "dog", "table"), or when it holds none; else the changes they are written in, without context ("barked":
        `ed`; "Dogs": `s`), empty when none shows one (only irregular forms, "Geese"). A slot's own, not its kind's:
        "barks", "barked" and "barking" are one kind, and "The dog ?slot1." is two frames, one holding each."""
        if not self._written_otherwise((pattern, slot)):
            return None
        return frozenset(self._slot_changes.get((pattern, slot), {}))

    def changed_writing(self, pattern: str, slot: str) -> Optional[FrozenSet[Tuple[str, str]]]:
        """A slot's writing as evidence of its changes (`said_shapes`, `unshaped_in`): as `slot_writing`, and None
        besides when most of what stands there written otherwise is written by no change. An irregular form among
        regular ones ("ran" beside "barked", "walked") is an exception to a change; words that are other words for
        their concepts ("could" for `possible`, "should" for `advisable`) beside one "recently" are no writing of the
        slot's in "-ly". They still say the slot is written otherwise than by name ("third", "quarter" for 3 and 4:
        "25%" stands against them)."""
        writing = self.slot_writing(pattern, slot)
        tally = self._slot_tally.get((pattern, slot))
        if writing is None or sum(self._slot_changes.get((pattern, slot), {}).values()) * 2 <= tally[1] + tally[3]:
            return None
        return writing

    def written_against(self, pattern: str, slot: str, filler: Any) -> bool:
        """Whether a filler is written otherwise than a slot's own fillers are: as named where they are written in
        a shape, in a shape where they are written as named (unless one of them is written in it too), or in a
        change none of them shows ("barked" where "barks" stands). An irregular form ("flew") shows no change and is not held against a slot that takes a
        shape; a filler of several words, or a slot holding no one-word filler, is not judged. A phrase of one word
        is judged as its word ("barking", where "barked" stands)."""
        written = self._written_as(filler)
        return written is not None and self.word_against(pattern, slot, *written)

    def word_against(self, pattern: str, slot: str, word: str, name: str) -> bool:
        """`written_against`, for one word written and the name of what it names (both folded): the word a phrase
        writes where a frame's slot stands ("chased", a chasing, of "chased the ?slot0")."""
        tally = self._slot_tally.get((pattern, slot))
        if not tally or not tally[0] + tally[1] + tally[3]:
            return False
        otherwise = word != name
        writing = self.slot_writing(pattern, slot)
        if writing is None:
            # Where most are written as named, one written in a change one of them is written in is written as they
            # are: "snow" for `snowing` where "rain" stands for `raining`.
            change = self.shape_between(word, name) if otherwise else None
            if otherwise and change is None:
                # A WORD OF ITS OWN, NO SHAPE OF THE NAME: written otherwise only where it says more than its
                # concept, as an irregular form does ("flew": a flying, before now). A word that only names the
                # thing ("bank" for `depository financial institution`, "computer" for `calculator`) is written as
                # the slot's words are; held against them, 31 of 70 words' senses in the sandbox never reached the
                # listener, the bank where money is kept among them.
                return self.says_more(word, name)
            return otherwise and self._least(change) not in self._slot_changes.get((pattern, slot), {})
        if not otherwise:
            return True
        change = self.shape_between(word, name)
        if change is None or not writing:
            return False
        least = self._least(change)
        # A change that is one of the slot's with the word's own last letter written again ("swimming": `ing`, the
        # "m" of "swim" doubled) is written as the slot's are.
        return least not in writing and not any(
            least[1] == names and least[0].endswith(written) and len(least[0]) - len(written) == 1
            and name.endswith(least[0][0]) for written, names in writing)

    def takes_names(self, pattern: str, slot: str) -> bool:
        """Whether a slot has held names only: two fillers or more, each written with a capital where no sentence
        begins (`is_proper`). "Tom, the teacher," and "Rex, the dog,": the slot names one thing, as a name does."""
        own = self.fillers(pattern, slot)
        return len(own) >= 2 and all(isinstance(filler, Lexical) and self.is_proper(filler.words[0])
                                     for filler in own)

    def in_a_shape(self, word: str) -> bool:
        """Whether a word ends in a change productive in saying (`said_shapes`) with a name of two letters or more
        left when it is undone: written in a shape ("repeating", "warily"), whatever word it is a shape of."""
        word = _fold(word)
        return any(word.endswith(written) and len(word) - len(written) + len(names) >= 2
                   for written, names in self.said_shapes()[1] if written)

    def unshaped_in(self, pattern: str, slot: str, word: str) -> Optional[str]:
        """The name a word never held has in a slot whose fillers are written in a shape: the word with the most
        particular change of theirs that it ends in undone, of those productive in saying (`said_shapes`: the slot's
        fillers are concepts said in a shape) ("jumps", where "barks" and "climbs" stand, is `jump`); None when the
        slot takes no shape, or the word ends in none of its changes.

        A WORD MEMORY HOLDS IS WHAT IT UNDOES TO, where one of the changes undoes it to one; the most particular
        change only where none does. Undone by the most particular change alone, "breathes" stood as `breathese`, a
        word nothing holds, where `breathe` is held (UNDERSTANDS-PROSE-01, 2026-10-18)."""
        writing = self.changed_writing(pattern, slot)
        if not writing:
            return None
        word = _fold(word)
        undone = [word[:len(word) - len(written)] + names
                  for written, names in sorted(self.said_shapes()[1], key=lambda c: (-len(c[1]), -len(c[0]), c))
                  if self._least((written, names)) in writing and word.endswith(written)
                  and len(word) - len(written) + len(names) >= 2]
        return next((name for name in undone if name in self._fillers_by_word or self._lexical_value.get(name)),
                    undone[0] if undone else None)

    @staticmethod
    def _least(change: Tuple[str, str]) -> Tuple[str, str]:
        """A change without its context: `("xes", "x")` is `("es", "")` after an `x`."""
        written, names = change
        shared = 0
        while shared < min(len(written), len(names)) and written[shared] == names[shared]:
            shared += 1
        return written[shared:], names[shared:]

    # ── how words are used: named, counted, plural, or without "a" ────────────────────────────────────────────────

    def counted_slot(self, pattern: str, slot: str) -> bool:
        """Whether a slot is written right after a word with shapes of its own, the "a" of "A ?slot0 is a ?slot1.":
        a thing counted one at a time goes there. The word is found as `variants_of` finds it, never listed."""
        return any(self.variants_of(word) for word in self._before_slot.get((pattern, slot), ()))

    def _use_model(self) -> Tuple[Dict[Tuple[str, str], FrozenSet[str]], Dict[bool, Dict[str, str]],
                                  Dict[str, Dict[str, int]]]:
        """How each linked one-word filler is used, per slot, per word, and how the words ending alike are used:
        - `name`: written with a capital inside a sentence (`is_proper`), and never counted;
        - `plural`: in a slot that takes a shape ("Dogs" in "?slot0 can ?slot1.");
        - `count`: its concept held in a counted slot ("robin" in "A ?slot0 is a bird."), with a capital too ("an
          American": a kind of people, not a name);
        - `mass`: a word of the same kind as counted things, held alone and as it is named where a sentence begins,
          and never counted ("Water is cold.", "Biology is hard."). A counted thing never begins a sentence so.
        A word only ever held after "the" or "my", or of another kind ("red"), has none of these.

        WHICH ENDINGS DECIDE A WORD'S USE, the longest first, as the elsewhere condition orders them: a word that a
        longer ending decides ("kindness", by "ness") is that ending's, and no evidence for a shorter one ("s"), which
        "lens" and "abacus" end in too. An ending decides a use within Yang's tolerance, and one other than counted
        only where Albright & Hayes's confidence in it is above their confidence in counting over every word held,
        the rule it overrides: two words ending "eat" ("heat", "meat") do not make "feat" uncounted. Words written
        with a capital are ended apart, where a name is the rule an ending overrides: "Canadian", "Italian" and
        "Indian" are counted, so "Bostonian" is, while "Italy" and "Japan" are names. A plural is a word's shape, so
        it decides no ending.

        All of it is kept as items arrive (`_uses_now`); this is the whole of it at once, as `(slots, endings,
        words)`."""
        self._uses_now()
        slots = {where: frozenset(how for how, n in self._use_slots.get(where, {}).items() if n)
                 for where in self._linked}
        endings: Dict[bool, Dict[str, str]] = {False: {}, True: {}}
        for (proper, ending), how in self._end_decided.items():
            endings[proper][ending] = how
        return slots, endings, {word: dict(counts) for word, counts in self._use_words.items()}

    # How the uses are kept. A link, or a filler arriving after its link, waits in `_use_pending` until a use is next
    # asked for; then each slot is looked at again (what it is can turn on items that came since: its frame, the
    # letters after "a", the shapes held), and when one has changed, all is found again (`_uses_build`). Otherwise
    # each waiting link counts once, the fillers whose use may have moved are found again (`_use_dirty`), and the
    # endings of the words whose use moved are counted again (`_end_*`).

    def _slot_state(self, where: Tuple[str, str], shapes: Dict[str, bool]) -> Tuple[bool, bool, bool]:
        """What a slot is: counted (`counted_slot`), taking a shape (`shape_of_slot`), and where a sentence begins."""
        pattern, slot = where
        frame = self._by_key.get(pattern)
        first = isinstance(frame, Pattern) and isinstance(frame.form[0], Slot) and frame.form[0].name == slot
        return self._counted_state(where, shapes), bool(self.shape_of_slot(pattern, slot)), first

    def _counted_state(self, where: Tuple[str, str], shapes: Dict[str, bool]) -> bool:
        counted = False
        for word in self._before_slot.get(where, ()):
            if word not in shapes:
                shapes[word] = bool(self.variants_of(word))
            counted = counted or shapes[word]
        return counted

    def _use_enter(self, key: str) -> None:
        """A filler held in a kind, and held as an item: as a thing (`_use_thing`), its concept counts for its kind."""
        if not self._uses_built or key in self._use_entered:
            return
        item = self._by_key.get(key)
        if key not in self._parts_of or not isinstance(item, Lexical):
            return
        self._use_entered.add(key)
        if (key, "thing") in self._parent:
            self._use_thing(key)
        self._use_dirty.add(key)

    def _use_thing(self, key: str) -> None:
        """A filler held as a thing (`_taken_as`): its concept, counted or held bare, counts for its kind of things.
        Counted and uncounted are what things are; a count or a quality is neither."""
        item = self._by_key[key]
        root = self._find((key, "thing"))
        if self._use_counted.get(item.value):
            self._use_noun_more(root)
        if len(_loose(item.words)) == 1 and self._use_bare.get(item.value):
            self._use_bare_keys.setdefault(root, set()).add(key)
        self._use_dirty.add(key)

    def _use_noun_more(self, root: Tuple[str, str]) -> None:
        self._use_noun[root] = self._use_noun.get(root, 0) + 1
        if self._use_noun[root] == 1:
            self._use_dirty |= self._use_bare_keys.get(root, set())

    def _use_link(self, pattern: str, slot: str, key: str) -> None:
        """One link, counted once its filler is held: its concept counted, held bare, or its filler in a shape."""
        if (pattern, slot, key) in self._use_done:
            return
        filler = self._by_key.get(key)
        if not isinstance(filler, Lexical) or len(_loose(filler.words)) != 1:
            return
        self._use_done.add((pattern, slot, key))
        counted, taken, first = self._use_slot_state[(pattern, slot)]
        value = filler.value
        if counted:
            written = (value, _loose(filler.words)[0])
            self._use_counted_as[written] = self._use_counted_as.get(written, 0) + 1
            if self._use_counted_as[written] == 1:
                for other in self._lexical_value.get(value, ()):
                    self._use_dirty.add(other)
            self._use_counted[value] = self._use_counted.get(value, 0) + 1
            if self._use_counted[value] == 1:
                for other in self._lexical_value.get(value, ()):
                    if other in self._use_entered and (other, "thing") in self._parent:
                        self._use_noun_more(self._find((other, "thing")))
                    self._use_dirty.add(other)
        # A WORDLESS PHRASE'S SLOT MIXES KINDS OF WORDS ("?slot0 ?slot1" holds "red cup" and "ran fast", whose
        # "runs" and "climbed" make it take a shape: GENERALIZING_BY_KIND §4.4). A word written there exactly as its
        # name ("fast") took no shape, and is no plural for standing there; in a sentence's frame it is ("Fish are
        # animals.").
        plain = isinstance(self._by_key.get(pattern), Phrase) and _loose(filler.words)[0] == _fold(str(value))
        # A SLOT NAMING A KIND OF HAPPENING ("?slot0 the ?slot1", holding "kicked") takes the shapes doings are said
        # in, "before now" among them; no word there is a plural for standing there. Held so, "chases" was in the
        # shape of a slot saying a chasing before now ("The kelt chases the blip.").
        if taken and not plain and not _names_a_doing(self._by_key.get(pattern), slot):
            self._use_plural[key] = self._use_plural.get(key, 0) + 1
            self._use_dirty.add(key)
        elif first and self._written_as(filler) is not None and len(set(self._written_as(filler))) == 1:
            # Written as its name, as every writing is judged (`_written_as`): "travel" for `motion travel`, a sense
            # named apart, is its name, and "Travel is a motion." holds the act uncounted.
            self._use_bare[value] = self._use_bare.get(value, 0) + 1
            if self._use_bare[value] == 1:
                for other in self._lexical_value.get(value, ()):
                    item = self._by_key.get(other)
                    if other in self._use_entered and isinstance(item, Lexical) and len(_loose(item.words)) == 1 \
                            and (other, "thing") in self._parent:
                        self._use_bare_keys.setdefault(self._find((other, "thing")), set()).add(other)
                    self._use_dirty.add(other)
        # The slot holds the filler's use as it stands; a use that moves is moved in every slot it is linked to.
        how = self._use_key.get(key)
        if how is not None:
            counts = self._use_slots.setdefault((pattern, slot), {})
            counts[how] = counts.get(how, 0) + 1

    def _use_found(self, key: str) -> Optional[str]:
        filler = self._by_key.get(key)
        if key not in self._use_entered or not isinstance(filler, Lexical):
            return None
        words = _loose(filler.words)
        if len(words) != 1:
            return None
        # COUNTED AS THIS WORD IS: a thing is counted under a word where that word, case aside, stood counted for it
        # ("robin", "Robin"). Its other words do not count it: "chance", counted, said nothing of "luck", which a
        # source names the same thing by, and "Luck is a phenomenon." was held a counted word said bare.
        counted = self._use_counted_as.get((filler.value, words[0]))
        if self.is_proper(words[0]) and not counted:
            return "name"
        if self._use_plural.get(key):
            return "plural"
        if counted:
            return "count"
        if self._use_bare.get(filler.value) and (key, "thing") in self._parent \
                and self._use_noun.get(self._find((key, "thing"))):
            return "mass"
        return None

    def _use_set(self, key: str, how: Optional[str]) -> None:
        was = self._use_key.get(key)
        if was == how:
            return
        if how is None:
            del self._use_key[key]
        else:
            self._use_key[key] = how
        for where in self._links_to.get(key, ()):
            if (where[0], where[1], key) not in self._use_done:
                continue
            counts = self._use_slots.setdefault(where, {})
            if was is not None:
                counts[was] -= 1
            if how is not None:
                counts[how] = counts.get(how, 0) + 1
        word = _loose(self._by_key[key].words)[0]
        counts = self._use_words.setdefault(word, {})
        if was is not None:
            counts[was] -= 1
            if not counts[was]:
                del counts[was]
        if how is not None:
            counts[how] = counts.get(how, 0) + 1
        if not counts:
            del self._use_words[word]
        self._use_changed_words.add(word)

    def _uses_build(self) -> None:
        """All of it found again, from everything held."""
        self._uses_built = True
        self._use_pending.clear()
        self._use_touched.clear()
        self._use_letters_moved = False
        for store in (self._use_done, self._use_dirty, self._use_entered, self._use_new_names,
                      self._use_changed_words):
            store.clear()
        for table in (self._use_slot_state, self._use_counted, self._use_counted_as, self._use_bare, self._use_plural,
                      self._use_noun,
                      self._use_bare_keys, self._use_key, self._use_slots, self._use_words, self._end_word,
                      self._end_term, self._end_children, self._end_passed, self._end_decided):
            table.clear()
        self._end_kept = {False: {}, True: {}}
        self._end_trusted = {False: 0.0, True: 0.0}
        self._end_contested = {False: set(), True: set()}
        shapes: Dict[str, bool] = {}
        self._use_slot_state.update({where: self._slot_state(where, shapes) for where in self._linked})
        for key in self._parts_of:
            self._use_enter(key)
        for pattern, slot, key in self._links:
            self._use_link(pattern, slot, key)
        self._use_settle()
        self._uses_at = self._added

    def _uses_now(self) -> None:
        """The uses kept up with what has arrived since they were last asked for."""
        if not self._uses_built:
            self._uses_build()
            return
        if self._uses_at == self._added:
            return
        shapes: Dict[str, bool] = {}
        recheck = self._use_touched | self._use_shaped
        for where in (self._linked if self._use_letters_moved else recheck):
            if where not in self._linked:
                continue
            was = self._use_slot_state.get(where)
            if was is None or where in recheck:
                state = self._slot_state(where, shapes)
            else:
                state = (self._counted_state(where, shapes), was[1], was[2])
            if self._use_slot_state.setdefault(where, state) != state:
                self._uses_build()
                return
        self._use_touched.clear()
        self._use_letters_moved = False
        for word in self._use_new_names:
            self._use_dirty.update(self._lexical_loose.get((word,), ()))
            self._use_changed_words.add(word)
        self._use_new_names.clear()
        pending, self._use_pending = self._use_pending, []
        for pattern, slot, key in pending:
            self._use_link(pattern, slot, key)
        self._use_settle()
        self._uses_at = self._added

    def _use_settle(self) -> None:
        """The fillers whose use may have moved, found again, and the endings of the words whose use moved."""
        while self._use_dirty:
            key = self._use_dirty.pop()
            if isinstance(self._by_key.get(key), Lexical):
                self._use_set(key, self._use_found(key))
        touched = set()
        for word in self._use_changed_words:
            touched |= self._end_count(word)
        self._use_changed_words.clear()
        for proper, default in ((False, "count"), (True, "name")):
            kept = self._end_kept[proper]
            trusted = _confidence(kept.get(default, 0), sum(kept.values()))
            if trusted != self._end_trusted[proper]:
                self._end_trusted[proper] = trusted
                touched |= self._end_contested[proper]
        self._end_settle(touched)

    def _end_count(self, word: str) -> set:
        """A word counted again where it ends: the endings it no longer ends at, and those it now does."""
        counts = self._use_words.get(word)
        now: Optional[Tuple[bool, str]] = None
        if counts:
            how = max(counts.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))[0]
            if how != "plural":
                now = (self.is_proper(word), how)
        was = self._end_word.get(word)
        if was == now:
            return set()
        touched = set()
        size = min(4, len(word) - 1)
        for side, step in ((was, -1), (now, 1)):
            if side is None:
                continue
            proper, how = side
            kept = self._end_kept[proper]
            kept[how] = kept.get(how, 0) + step
            if not kept[how]:
                del kept[how]
            if size < 1:
                continue
            for longer in range(2, size + 1):
                self._end_children.setdefault((proper, word[len(word) - longer + 1:]), set()).add(
                    (proper, word[len(word) - longer:]))
            node = (proper, word[len(word) - size:])
            term = self._end_term.setdefault(node, {})
            term[how] = term.get(how, 0) + step
            if not term[how]:
                del term[how]
            touched.add(node)
        if now is None:
            del self._end_word[word]
        else:
            self._end_word[word] = now
        return touched

    def _end_settle(self, touched: Iterable[Tuple[bool, str]]) -> None:
        """Each touched ending decided again, the longest first: what it decides, and what it passes to the ending
        one letter shorter while it decides nothing."""
        heap = [(-len(node[1]), node) for node in set(touched)]
        heapq.heapify(heap)
        queued = {node for _, node in heap}
        while heap:
            _, node = heapq.heappop(heap)
            queued.discard(node)
            proper, ending = node
            default = "name" if proper else "count"
            tally = dict(self._end_term.get(node, {}))
            for child in self._end_children.get(node, ()):
                for how, n in self._end_passed.get(child, {}).items():
                    tally[how] = tally.get(how, 0) + n
            total = sum(tally.values())
            decided = None
            if total >= 2:
                how, most = max(tally.items(), key=lambda kv: (kv[1], kv[0] == default, kv[0]))
                if how != default:
                    self._end_contested[proper].add(node)
                else:
                    self._end_contested[proper].discard(node)
                if most * 2 > total and total - most <= total / math.log(total) \
                        and (how == default or _confidence(most, total) > self._end_trusted[proper]):
                    decided = how
            else:
                self._end_contested[proper].discard(node)
            if decided is None:
                self._end_decided.pop(node, None)
            else:
                self._end_decided[node] = decided
            passed = {} if decided is not None else {how: n for how, n in tally.items() if n}
            if passed != self._end_passed.get(node, {}):
                self._end_passed[node] = passed
                parent = (proper, ending[1:])
                if ending[1:] and parent not in queued:
                    queued.add(parent)
                    heapq.heappush(heap, (-len(parent[1]), parent))

    def used_as(self, word: str, value: Optional[str] = None) -> Optional[str]:
        """How a held one-word filler is used, the most of its uses (`_use_model`), or None when none is held.

        `value`: how the word is used for that thing alone. A word names several things, and is used as each is:
        "travel" is counted for a trip and not for the act of travelling."""
        self._uses_now()
        if value is not None:
            mine: Dict[str, int] = {}
            for key in self._lexical_loose.get((_fold(word),), ()):
                how = self._use_key.get(key)
                item = self._by_key.get(key)
                if how is not None and isinstance(item, Lexical) and item.value == value:
                    mine[how] = mine.get(how, 0) + 1
            return max(mine.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))[0] if mine else None
        counts = self._use_words.get(_fold(word))
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))[0]

    def use_of(self, name: str) -> str:
        """How a word no filler holds is used, as its writing and the words held show. Its last word, the one the
        rest describe, decides ("Roman arch" is an arch):
        - as that word is used, when it is held written as it is here ("fire tongs" as "tongs", a plural; "Latin
          American" as "American"), a capital and all: "Golden Horde" is no "horde";
        - else as the held words written as it is (with a capital, or without) and ending as it does are used, the
          longest ending that decides it within Yang's tolerance: "paleoanthropology" is `mass` beside "biology"
          and "geology", "Bostonian" is counted beside "Canadian" and "Italian";
        - else a `name` when written with a capital ("Thiosulfil"), and `count`, a thing counted with "a", when not.
        A plural is never guessed from an ending: "bus" and "lens" end as plurals do."""
        name = str(name).replace("_", " ").strip()
        if not name.split():
            return "count"
        head = name.split()[-1]
        proper = head[:1].isupper()
        last = _fold(head)
        held = self.used_as(last)
        if held is not None and self.is_proper(last) == proper:
            return held
        for size in range(min(4, len(last) - 1), 0, -1):
            decided = self._end_decided.get((proper, last[len(last) - size:]))
            if decided is not None:
                return decided
        return "name" if proper else "count"

    def slot_admits(self, pattern: str, slot: str) -> FrozenSet[str]:
        """The uses of the words a slot holds (`_use_model`), and of those its frame's twins hold in it (`twins_of`),
        and `count` where it is counted: what a word never held may be to stand there.

        A COUNTED THING NEVER BEGINS A SENTENCE BARE (`_use_model`), so a slot where a sentence begins, with nothing
        counting it and no shape taken, admits no counted word, whatever its words are used as elsewhere. A filler's
        use is its concept's everywhere: one said bare here and with "a" in another sentence is `count`, and 179 such
        among the 582 words of "?slot0 is ?slot1." let every counted word stand there ("Soul is organism.").

        HOW A WORD IS COUNTED IS A THING'S. A slot that takes no things, only doings or qualities, admits by no use:
        "walk", counted where it is a thing ("a walk"), was kept out of "To ?slot0 is to ?slot1.", where english_41's
        verbs stood bare, and "bright" out of "To be ?slot0 is to be ?slot1.": 35 of the 121 rules WordNet's verbs and
        adjectives could not say (2026-10-12)."""
        if "thing" not in self._taken_at(pattern, slot):
            return frozenset()
        self._uses_now()
        admits = {how for how, n in self._use_slots.get((pattern, slot), {}).items() if n}
        for twin in self.twins_of(pattern):
            admits |= {how for how, n in self._use_slots.get((twin, slot), {}).items() if n}
        if self.counted_slot(pattern, slot):
            admits.add("count")
        else:
            state = self._use_slot_state.get((pattern, slot))
            if (state is not None and state[2] and not state[1]) or self.counted_beside(pattern, slot):
                admits.discard("count")
                admits.add("mass")
        return frozenset(admits)

    def counted_beside(self, pattern: str, slot: str) -> bool:
        """Whether a held frame says the same thing with this slot counted: this frame with a counting word, one
        written in two shapes as the next letter asks ("a", "an"), right before the slot. "?slot0 is ?slot1." stands
        beside "?slot0 is a ?slot1.", and "A ?slot0 is ?slot1." beside "A ?slot0 is a ?slot1.".

        English says a counted thing with the word, an uncounted one without: where both frames are held, the bare
        one is for what is not counted ("A table is furniture."), and a counted word goes in the other. "The ?slot0
        is in the ?slot1." has no such frame beside it, and takes counted words. Nothing held said so before: a
        slot's uses are its fillers', and the bare frame's fillers, held nowhere else, showed none, so every counted
        word stood there ("A kennel is outbuilding.")."""
        item = self._by_key.get(pattern)
        if not isinstance(item, Pattern):
            return False
        if self._beside_at != self._added:
            counting = frozenset(word for word in self._frame_words if self.variants_of(word))
            skeletons: Dict[Tuple[str, ...], List[Pattern]] = {}
            for held in self._by_key.values():
                if isinstance(held, Pattern) and held.slots:
                    skeletons.setdefault(self._skeleton(held), []).append(held)
            self._beside, self._beside_at = (counting, skeletons), self._added
        counting, skeletons = self._beside
        skeleton = self._skeleton(item)
        if slot not in skeleton:
            return False
        at = skeleton.index(slot)
        meaning = item.meaning.canonical()
        return any(other.meaning.canonical() == meaning
                   for word in counting
                   for other in skeletons.get(skeleton[:at] + (word,) + skeleton[at:], ()))

    @staticmethod
    def _skeleton(pattern: "Pattern") -> Tuple[str, ...]:
        """A frame as its words, case aside, and its slots, in order."""
        return tuple(e.name if isinstance(e, Slot) else _fold(e.text) for e in pattern.form)

    def filler_openings(self, pattern: str, slot: str) -> FrozenSet[bool]:
        """How this slot's fillers begin: True for a filler begun by a word that names nothing ("A dog"), False for
        any other."""
        tally = self._slot_tally.get((pattern, slot))
        openings = {self.names_nothing(word) for word in self._slot_runs.get((pattern, slot), {})}
        if tally and tally[2]:
            openings.add(False)
        return frozenset(openings)

    def word_kinds(self) -> List[FrozenSet[Lexical]]:
        """The lexical constructions grouped by the slots they fill. Two that fill a common slot, as the slot takes
        them (`_taken_as`), are one kind, and a kind is everything reachable that way; a word taken as two things,
        a count and a thing, is in a kind for each. Nothing tells the substrate what the kinds are."""
        groups: Dict[Tuple[str, str], set] = {}
        for node in list(self._parent):
            if node[0] in self._by_key:
                groups.setdefault(self._find(node), set()).add(self._by_key[node[0]])
        return sorted((frozenset(g) for g in groups.values()), key=lambda g: sorted(x.surface for x in g))


def _confidence(hits: int, scope: int) -> float:
    """Albright & Hayes's (2003) confidence in a rule: the lower limit of a 75% confidence interval on its
    reliability, adjusted as (hits + 0.5) / (scope + 1), so a rule shown by few words is trusted less than one shown
    by many with the same rate."""
    if scope < 2:
        return 0.0
    reliability = (hits + 0.5) / (scope + 1)
    return reliability - _t_quantile(scope - 1) * math.sqrt(reliability * (1 - reliability) / scope)


@functools.lru_cache(maxsize=None)
def _t_quantile(freedom: int) -> float:
    """The 87.5th percentile of Student's t with these degrees of freedom: the upper end of a 75% interval."""
    from scipy.stats import t
    return float(t.ppf(0.875, freedom))


def _tolerated(right: int, covered: int) -> bool:
    """Yang's Tolerance Principle (2016): a change over N words is productive while the words it misreads number no
    more than N / ln N, and at least two words show it."""
    return right >= 2 and covered >= 2 and covered - right <= covered / math.log(covered)


def live_view() -> PatternInventory:
    """The view memory warms: what the substrate has been taught of English, as reading sees it now."""
    return _live_inventory()


def _live_inventory() -> PatternInventory:
    """The view memory warms, or an empty one when memory is not up in this process. Empty is the honest answer
    then: nothing learned is visible here."""
    from core.agents import memory_agent as _memory
    agent = _memory._memory_agent
    if agent is None:
        return PatternInventory()
    return agent.pattern_inventory()


# ── Reading and speaking ─────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Reading:
    """A sentence read to a meaning: the constructions that read it (the holophrase or item-based construction
    first, then each slot's filler in slot order), the links used, and their average score and use.

    What the reading had to suppose is carried with it, never written: `proposed`, links from a slot to a filler of
    the same kind that no taught pair linked yet; `new`, fillers for words nothing held covers; `loose`, whether it
    read only with case folded and marks set aside."""

    constructions: Tuple[Construction, ...]
    links: Tuple[Link, ...]
    meaning: Meaning
    score: float = INITIAL_SCORE
    uses: float = 0.0
    proposed: Tuple[Link, ...] = ()
    new: Tuple[Lexical, ...] = ()
    loose: bool = False
    misfits: int = 0
    #: The frame's own words it read through another said in their place (`synonyms_of`): "would" for "could".
    said_for: int = 0
    #: Held fillers it proposed that never stood beside the slot's own fillers anywhere (`stood_beside`).
    apart: int = 0
    #: Read by composing its meaning from how its words go together (`composition`), where no taught frame read the
    #: utterance: it holds no construction and no link.
    composed: bool = False
    #: Its packed words (`Sense`): each stand-in, its senses each with what taking it supposes in this reading
    #: (links proposed and words read as less than they say, fillers written against their slot, fillers apart), and
    #: where its link stands among `links` and among `proposed`. A reading with none is one reading; with some, one for
    #: each choice of their senses (`with_senses`).
    senses: Tuple[Packed, ...] = ()
    #: How many numbers it puts where numbers of their size never stood, of `apart`, its packed words' aside.
    sized: int = 0
    #: HOW PROBABLE ENGLISH'S GRAMMAR MADE THIS READING'S STRUCTURE, in nats, of a reading it composed (`composed`):
    #: its share of every reading of the whole the grammar found, logged (`grammar.Reading.sure`). A composed reading
    #: holds no construction and no link, so `_derivation` has nothing of its own to weigh and every reading handed
    #: up weighed alike; the grammar's own ranking would be thrown away by passing them on without it.
    structure: float = 0.0

    @property
    def pattern(self) -> Pattern:
        return self.constructions[0]  # type: ignore[return-value]

    @property
    def key(self) -> str:
        return "+".join(c.key for c in self.constructions)

    @property
    def supposed(self) -> Tuple[bool, int, int, int, int]:
        """How much the reading had to suppose: read loosely, how many words it took as new names, how many links it
        proposed, and how many fillers it put where they are written otherwise than the slot's own
        (`written_against`), which tells apart readings that suppose the same ("snows" where "rains" stands, not
        "rained"). A frame's word read through another said in its place is supposed as a link is ("would" for
        "could"); one written in another shape, as the letter after it asks ("an" for "a"), is not. Words, not
        names: "blue ball" taken as one new name supposes more than "ball" alone beside the known word "blue".
        Last, how many held fillers it proposed that never stood beside the slot's own (`stood_beside`): "snow",
        the stuff, where "It will ?slot0 soon." holds "rain" for `raining`, supposes more than "snow" for `snowing`,
        which stood beside "rain" before."""
        proposed, misfits, apart = len(self.proposed) + self.said_for, self.misfits, self.apart
        # Of a packed reading, the reading of it that supposes least: what each sense supposes adds to the rest, so
        # each word's least sense makes it.
        for _, options, _, _ in self.senses:
            least = min(cost for _, cost in options)
            proposed, misfits, apart = proposed + least[0], misfits + least[1], apart + least[2]
        return (self.loose, sum(len(_loose(lexical.words)) for lexical in self.new), proposed, misfits, apart)


def _best_first(reading: Reading):
    return reading.supposed + (-reading.score, -reading.uses, reading.key)



def _chunkings(form: Tuple[FormElement, ...], words: Tuple[str, ...],
               same: Callable[[str, str], bool] = str.__eq__,
               missing: Callable[[Piece], bool] = lambda piece: False,
               shaped: Optional[Callable[[int, str], bool]] = None) -> Iterator[Tuple[Tuple[int, int], ...]]:
    """Every way a construction's form covers `words` exactly: each piece matches its word (as `same` compares
    them, or as `shaped` finds the word there written for it in another shape) or, where `missing` allows it, is
    absent; each slot takes one or more words. Yields each slot's span (start, end) in `words`, in slot order."""
    for spans, _ in _coverings(form, words, same, missing, shaped):
        yield spans


def _coverings(form: Tuple[FormElement, ...], words: Tuple[str, ...],
               same: Callable[[str, str], bool] = str.__eq__,
               missing: Callable[[Piece], bool] = lambda piece: False,
               shaped: Optional[Callable[[int, str], bool]] = None,
               fill: Optional[Callable[[int, int, int], Sequence]] = None
               ) -> Iterator[Tuple[Tuple[Tuple[int, int], ...], Tuple[Sequence, ...]]]:
    """Every way a construction's form covers `words` exactly (`_chunkings`), each slot's span with what stands in
    it there: `fill(k, start, end)`, what may stand in the k-th slot over `words[start:end]`. A covering with a slot
    nothing may stand in is never made. Without `fill`, every covering, with nothing for its slots.

    WHERE THE WORDS SPLIT BETWEEN A FORM'S SLOTS IS ASKED OF THE CHART, NOT TRIED. Every split was made, and each
    thrown away at its first slot nothing stands in: reading "Some organisms also perform anoxygenic photosynthesis,
    which does not produce oxygen. ..." (Wikipedia's Photosynthesis, as a page looked up is read) made 1,560,913
    coverings of its runs of words, 786 with something standing in every slot, and half its 24 s went to making them
    (lyric_dev, 2026-10-23). A slot's span is asked of the chart as the covering reaches it, and only where the rest
    of the form can still cover the rest of the words (`row`), so the chart is asked of the same spans, in the same
    order, as when every covering was made and each slot asked in turn: the coverings kept, and what is read, are
    the same."""
    n = len(words)
    rows: Dict[int, List[bool]] = {}

    def matches(element: Piece, at: int) -> bool:
        return same(words[at], element.text) or (shaped is not None and shaped(at, element.text))

    def row(i: int) -> List[bool]:
        """Where `form[i:]` may begin and still cover the rest of the words exactly."""
        if i not in rows:
            out = [False] * (n + 1)
            if i == len(form):
                out[n] = True
            else:
                element, after = form[i], row(i + 1)
                if isinstance(element, Slot):
                    ahead = False
                    for at in range(n - 1, -1, -1):
                        ahead = ahead or after[at + 1]
                        out[at] = ahead
                else:
                    skips = missing(element)
                    for at in range(n + 1):
                        out[at] = (at < n and after[at + 1] and matches(element, at)) or (skips and after[at])
            rows[i] = out
        return rows[i]

    def walk(i: int, at: int, spans: Tuple[Tuple[int, int], ...], options: Tuple[Sequence, ...]):
        if i == len(form):
            if at == n:
                yield spans, options
            return
        element = form[i]
        if isinstance(element, Slot):
            after = row(i + 1)
            for end in range(at + 1, n + 1):
                if not after[end]:
                    continue
                standing = fill(len(spans), at, end) if fill is not None else ()
                if fill is None or standing:
                    yield from walk(i + 1, end, spans + ((at, end),), options + (standing,))
            return
        if at < n and matches(element, at) and row(i + 1)[at + 1]:
            yield from walk(i + 1, at + 1, spans, options)
        if missing(element) and row(i + 1)[at]:
            yield from walk(i + 1, at, spans, options)

    yield from walk(0, 0, (), ())


def _written_shapes(view: "PatternInventory", words: Sequence[str], following: str = "", *,
                    loose: bool = False) -> Tuple[Optional[Callable[[int, str], bool]], FrozenSet[str]]:
    """Where a word stands for a frame's word written in another shape, as the word after it asks ("An ocelot" for
    the "A" of "A ?slot0 is a ?slot1."): a test of (place, frame word) for `_chunkings`, or None when no word here
    is written so, and the frame words so stood for, so a frame needing one may be tried. `following` is the word
    after the last one, where these words are part of a sentence."""
    after = tuple(words[1:]) + (following,)
    standing = [view.written_for(word, next_word) for word, next_word in zip(words, after)]
    if not any(standing):
        return None, frozenset()
    if loose:
        return (lambda at, text: _fold(text) in standing[at]), frozenset(w for ws in standing for w in ws)
    stood = frozenset(w.capitalize() if words[at][:1].isupper() else w
                      for at, ws in enumerate(standing) for w in ws)
    return (lambda at, text: _fold(text) in standing[at] and text[:1].isupper() == words[at][:1].isupper()), stood


def _as_written(pattern: Pattern, words: Sequence[str], spans: Sequence[Tuple[int, int]],
                pieces: Optional[Sequence[Piece]] = None) -> Pattern:
    """The frame as these words write it, where they cover it with these slot spans: a word of its own matched in
    another of its shapes ("An" for the "A" of "A ?slot0 is a ?slot1.") is written as the words have it. The frame
    itself when every word of its own is written as it is. What the learner links, and what it creates, is the frame
    as the sentence wrote it: the words held after a frame's word are the words written after it.

    `pieces`: the sentence's own pieces. A frame written otherwise is then spaced as the sentence spaces it:
    "What's an owl?", read through "What is a ?slot0?", is "What's an ?slot0?", not "What 's an ?slot0?"."""
    form: List[FormElement] = []
    slots = iter(spans)
    at, changed = 0, False
    for element in pattern.form:
        if isinstance(element, Slot):
            at = next(slots)[1]
            form.append(element)
        else:
            changed = changed or words[at] != element.text
            form.append(pieces[at] if pieces is not None
                        else Piece(words[at], element.space_after) if words[at] != element.text else element)
            at += 1
    return Pattern(tuple(form), pattern.meaning) if changed else pattern


def _fill(meaning: Meaning, values: Mapping[str, str]) -> Optional[Meaning]:
    return _renamed(meaning, values)


def _may_be_new(pieces: Tuple[Piece, ...], view: PatternInventory, longest: int, *, given: bool = False) -> bool:
    """Whether these words can be taken as a new concept's name in a slot whose kind's longest filler has `longest`
    words: no more words than that, nor than the store takes in a term; none of them a mark; one word alone not a
    word that names nothing (`names_nothing`); and several, none of them a structure word -- a run of words that
    holds one is structure the substrate has not learned to read, not a name.

    `given`: the run is a name its teacher gave whole ("body of water", "change of location"). Then a structure
    word inside it is the name's own. Only the teacher knows that; taken as structure, "of" went into frames
    ("Every ?slot0 is a body of ?slot1.")."""
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    words = _written_words(pieces)
    if not pieces or len(words) > min(MAX_TERM_WORDS, max(longest, 1)) or _parted(pieces):
        return False
    if len(pieces) == 1:
        # One word is a name unless it is a word that names nothing ("a"); a word held so far only inside forms
        # ("cup" in "That is my cup.") may still name a thing, and a taught meaning names it.
        return not view.names_nothing(pieces[0].text)
    # The words a hyphen joins are one word, whatever they are: "give-and-take" is a name. A word frames are built
    # with more than it names things with is structure here too ("a", which WordNet gave the ampere).
    return given or not any(len(word) == 1 and (view.is_structure(word[0].text)
                                                or view.builds_more_than_it_names(word[0].text)) for word in words)


def _not_offered(pattern: Union[Pattern, "Phrase"], slot: str, pieces: Tuple[Piece, ...],
                 lexical: Lexical, why: str) -> None:
    """WHICH SENSE OF A WORD WAS NOT PUT TO THE LISTENER, AND WHICH TEST DROPPED IT (`_fillers`).

    Every sense of the words read is supposed to reach the listener, which weighs them and says what it weighed
    (`_read_pieces`, `meant`, `_listening_said`). What the listener never receives it cannot say anything about, and
    `_fillers` dropped senses silently: "The note was long." was read ONE way on a store holding `comment note`,
    `musical notation note` and `debt instrument note` for the word, each of them met and counted, and the listener
    reported "the only meaning the words have" -- true of what it was handed, and not of what memory holds
    (lyric_talk, 2026-11-08).

    Said at debug, and built only when debug is on: this runs for every filler of every run of words of every
    sentence read."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    logger.debug("fillers: %r not offered as %r in %s of %s -- %s",
                 " ".join(p.text for p in pieces), lexical.value, slot, str(pattern.key)[:12], why)


def _fillers(view: PatternInventory, pattern: Pattern, slot: str, pieces: Tuple[Piece, ...], *,
             extend: bool, loose: bool, first: bool = False) -> List[Tuple[Lexical, Optional[Link], str]]:
    """What may stand in one slot for these words: (filler, the link it stands through, how). A held link is
    `linked`; with `extend`, a filler of the slot's kind stands through a `kind` link proposed, and words nothing
    held covers stand as a `new` filler through a link proposed. `first`: the words begin the sentence."""
    words = tuple(p.text for p in pieces)
    if loose and _parted(pieces):
        return []          # a mark inside what was said separates; no filler spans it
    held = view.lexicals_with_words(_loose(words) if loose else words, loose=loose)
    out: List[Tuple[Lexical, Optional[Link], str]] = []
    alike = _alike(view, pattern, slot)
    # A WORD FRAMES ARE BUILT WITH MORE THAN IT NAMES THINGS is English's structure here, as in a name
    # (`builds_more_than_it_names`): no slot takes it alone through a link only proposed. Taken for a shape of "be",
    # a doing like the slot's own, "It is in Paris." read as some being during a time called Paris, and the Eiffel
    # Tower was never held in Paris (UNDERSTANDS-PROSE-01 on main, 2026-10-21). A link taught stands.
    structure = len(pieces) == 1 and view.builds_more_than_it_names(words[0])
    for lexical in held:
        if not view.counts(lexical):
            _not_offered(pattern, slot, pieces, lexical, "never met naming it")
            continue
        linked = view.link_between(pattern.key, slot, lexical.key)
        if linked is not None:
            out.append((lexical, linked, "linked"))
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("fillers: %r OFFERED as %r in %s of %s -- linked here",
                             " ".join(p.text for p in pieces), lexical.value, slot, str(pattern.key)[:12])
            continue
        # EACH TEST NAMED, so which one dropped a sense can be read rather than inferred. Asked as one condition,
        # "The note was long." put ONE of the three senses of "note" it holds to the listener -- every one met and
        # counted -- and nothing said which test the other two failed (lyric_talk, 2026-11-08).
        of_the_kind = extend and not structure and alike(lexical.key)
        admitted = of_the_kind and view.admits_there(pattern.key, slot, lexical.value)
        # A word that says more than its concept ("walked": a walking before now) stands as its concept only
        # where the frame says the rest itself: "Only ?slot0 ?slot1." says its events were before now.
        says_more = (admitted and len(lexical.words) == 1
                     and view.says_more(lexical.words[0], lexical.value, doing=view.stands_as_doing(lexical))
                     and not _frame_says(pattern, slot, view.said_by(lexical.words[0], lexical.value)))
        if admitted and not says_more:
            out.append((lexical, link(pattern, slot, lexical), "kind"))
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("fillers: %r OFFERED as %r in %s of %s -- of its kind",
                             " ".join(p.text for p in pieces), lexical.value, slot, str(pattern.key)[:12])
        else:
            _not_offered(pattern, slot, pieces, lexical,
                         "no link held, and none may be proposed here" if not extend
                         else "no link held, and its words build more than they name" if structure
                         else ("no filler of this slot was ever read in a slot like it"
                               f" (same_kind={view.same_kind(pattern.key, slot, lexical.key)}"
                               f" of_its_class={view.of_its_class(pattern.key, slot, lexical.key)}"
                               f" stood_beside={view.stood_beside(pattern.key, slot, lexical.key)}"
                               f" | slot takes={sorted(view._taken_at(pattern.key, slot))}"
                               f" any_part={view.takes_any_part(pattern.key, slot)}"
                               f" word is={sorted(view.class_parts(lexical.words[0])) if len(lexical.words)==1 else '-'}"
                               f" sense stood={sorted(view._parts_of.get(lexical.key) or ())}"
                               f" classes={dict(view.word_classes.get(_fold(lexical.words[0]), {})) if len(lexical.words)==1 else '-'})"
                               if logger.isEnabledFor(logging.DEBUG) else "") if not of_the_kind
                         else "nothing of its kind was ever said in this place" if not admitted
                         else "its word says more than its concept, and the frame does not say the rest")
    as_held = bool(out)
    if extend and len(pieces) == 1 and not structure:
        # A WORD WRITTEN IN A SHAPE LEARNED FROM THE FILLERS ("tables", where "table" is held), or a held concept's
        # own name, stands where that word would, as each thing that word names. Held itself or not: WordNet's
        # kinds said of many held "pirates" for the ship alone, and "stilts" for the bird, and the pirate who
        # plunders, the pole, never reached the listener, who took "Are pirates a kind of plunderer?" to ask about a
        # ship (2026-10-14). Nor only the first thing the word names: "hawks" stood for the board a mason holds.
        named_here = {lexical.value for lexical, _, _ in out}
        for name in view.names_of_shape(words[0]):
            for base in view.holding(name):
                if view.says_more(words[0], name, doing=view.stands_as_doing(base)):
                    continue               # "jumped" is a jumping before now (`shaped_phrases`), not `jump` alone
                if base.value not in named_here and view.counts(base) and (
                        view.link_between(pattern.key, slot, base.key) is not None or alike(base.key)):
                    named_here.add(base.value)
                    shaped = Lexical(pieces, base.value)
                    out.append((shaped, link(pattern, slot, shaped), "kind"))
    # A word held in another case is not a new word: it is read as the word it is, loosely.
    if extend and not held and not view.lexicals_with_words(_loose(words), loose=True):
        named = _named_as(pieces)
        if _temporal(named):
            # A DAY OR A TIME OF DAY WRITTEN AS ONE is no new name: its writing says which ("October 6"). Counted as
            # new words, a day of two words lost to any reading that took fewer ("October" plus 6, a number).
            written = Lexical(pieces, named)
            out.append((written, link(pattern, slot, written), "written"))
        elif _may_be_new(pieces, view, view.longest_filler(pattern.key, slot)) \
                and view.admits_there(pattern.key, slot, named):
            # A WORD NEVER MET STANDS AS ITSELF, IN A ROLE ITS WRITING ALLOWS (`_may_stand_new`). Any role taken,
            # "I am currently using Windows." read as a count of "currently using", and "Hunter is Peter's
            # daughter." as a daughter-ness of a kind called Peter.
            role = _role_of_slot(pattern, slot)
            if view.takes_names(pattern.key, slot):
                role = "name"
            if not _may_stand_new(role, pieces, named, first):
                return out
            # A KIND TOO, AND NOT WHERE A FRAME SAYS WHAT IS A KIND OF WHAT. Asked of `thing` alone, the reading
            # stood the adverb one slot over as a kind instead: "Tom walked annoyingly." came back
            # `done_to(?v0, ?v1) & instance_of(?v1, annoyingly)`, a thing of the kind annoyingly (lyric_db,
            # 2026-11-08). Both sides of `isa` are left alone, which is where a quality IS a kind and is said as
            # one ("Red is a colour.", "Hot is the opposite of cold.").
            if role in ("thing", "kind") and any(_never_a_thing(view, w) for w in words) \
                    and not any(f.relation == "isa" and slot in (f.subject, f.obj)
                                for f in _facts_of(pattern)):
                _not_offered(pattern, slot, pieces, Lexical(pieces, named),
                             "memory holds its word a quality and never a thing")
                return out
            # A word never held, where the slot's fillers are written in a shape, is also the word that shape makes
            # it from: "jumped", where "barked" and "walked" stand, is `jump`.
            name = view.unshaped_in(pattern.key, slot, words[0]) if len(pieces) == 1 else None
            if name and view.is_structure(name):
                # A word that undoes to one English builds frames from, and never puts in a slot, is no shape of it:
                # undone, "only" stood as `on`. "carefully" undoes to `careful`, which stands in slots.
                name = None
            new = Lexical(pieces, named)
            # A QUALITY OR A DOING NEVER MET IS WRITTEN AS THE SLOT'S OWN ARE: as itself where they are written as
            # named ("try" where "open" stands), in their shape where they take one. Written otherwise, the role is
            # a guess its writing denies: "column" where "chased" and "barked" stand, "Repeating" where "Open" does.
            # Not where the word's class stands in the role: an adjective ends as it is written ("astonished",
            # "glaring", "lonely"), in no shape of another word; taken for one, "To be astonished is to be
            # surprised." read nothing, and of WordNet's adjectives said so, 70 in 76 (2026-10-12).
            # Asked in this order, the costly last: whether a word is in a shape is found over every change the held
            # fillers show (`said_shapes`), which each verb form learned changes. Asked of every new word in every
            # slot, every form taught rebuilt it, and WordNet's examples slowed from two minutes a thousand to half
            # an hour (2026-10-12).
            if not (role in ("quality", "doing") and (view.written_against(pattern.key, slot, new) or (
                    view.slot_writing(pattern.key, slot) is None and role not in view.class_parts(words[0])
                    and view.in_a_shape(words[0])))):
                out.append((new, link(pattern, slot, new), "new"))
            if name:
                shaped = Lexical(pieces, name)
                out.append((shaped, link(pattern, slot, shaped), "new"))
    elif extend and held and not as_held and len(pieces) == 1:
        # A WORD HELD ONLY FOR WHAT STANDS ELSEWHERE, OF A CLASS THAT STANDS HERE, is read here as a word never met
        # in this part: "amble", held for a walk (`walk amble`), a thing, is a doing where "To ?slot0 is to ?slot1."
        # takes one, as English makes a verb of a noun ("to fork", "to cache"). Held, it was no new word, and "To
        # amble is to walk." read nothing (2026-10-12).
        role = _role_of_slot(pattern, slot)
        named = _named_as(pieces)
        if role in ("quality", "doing") and role in view.class_parts(words[0]):
            # AND THE SENSES IT IS HELD FOR STAND HERE, BESIDE THAT NAME, NOT INSTEAD OF IT. A word whose class
            # stands here was given a concept named by its spelling and its own senses were dropped, so a word
            # memory holds three meanings of reached the listener as one meaning it had never held: "The note was
            # long." read `instance_of(?v1, long)`, a kind called long, while `agelong long` was held for that very
            # word, met, counted, and of a class that stands where this slot's fillers do (lyric_talk, 2026-11-08).
            # Offered through a link proposed, as a filler of the slot's kind is: the listener weighs the senses
            # against the new name instead of being handed the name alone.
            standing = {lexical.value for lexical, _, _ in out}
            for lexical in held:
                if lexical.value in standing or not view.counts(lexical):
                    continue
                if view.says_more(words[0], lexical.value, doing=view.stands_as_doing(lexical)) \
                        and not _frame_says(pattern, slot, view.said_by(words[0], lexical.value)):
                    continue
                standing.add(lexical.value)
                stands = Lexical(pieces, lexical.value)
                out.append((stands, link(pattern, slot, stands), "kind"))
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("fillers: %r OFFERED as %r in %s of %s -- held, and its class stands here",
                                 " ".join(p.text for p in pieces), lexical.value, slot, str(pattern.key)[:12])
            if _may_be_new(pieces, view, view.longest_filler(pattern.key, slot)) \
                    and view.admits_there(pattern.key, slot, named) and _may_stand_new(role, pieces, named, first):
                new = Lexical(pieces, named)
                if not view.written_against(pattern.key, slot, new):
                    out.append((new, link(pattern, slot, new), "new"))
    return out


def _named_as(pieces: Tuple[Piece, ...]) -> str:
    """What a word never met names where it stands: itself, as written -- or, written as a number or a formula,
    the number or formula it writes, one thing however it is written: `1,000,000` is 1000000, `2+3` is `2 + 3`; or,
    written as a day or a time of day, in one word or several, that day or time: "October 6" is `--10-06`, "19:30"
    is `7:30 p.m.`."""
    surface = surface_of(pieces)
    literal = classify_literal(surface)
    if literal is not None and literal.kind in ("date", "time"):
        return literal.canonical
    if len(pieces) == 1 and literal is not None and literal.kind in ("cardinal", "decimal", "expression"):
        return literal.canonical
    return surface


def _alike(view: PatternInventory, frame: Union[Pattern, Phrase], slot: str) -> Callable[[str], bool]:
    """Whether a held filler may stand in a slot it was never linked to: one of the slot's kind, or one whose word's
    class stands where the slot's fillers do (`of_its_class`). In a construction with no word of its own ("?slot0
    ?slot1"), nothing but its fillers anchors it, so the filler must also have stood beside the slot's own fillers
    somewhere (`stood_beside`): a kind alone reads any two words there ("walked carefully" as a count)."""
    wordless = not any(isinstance(e, Piece) and not _is_mark(e.text) for e in frame.form)
    return lambda key: (view.same_kind(frame.key, slot, key) or view.of_its_class(frame.key, slot, key)) \
        and (not wordless or view.stood_beside(frame.key, slot, key))


#: The relations whose subject is a happening: who does it, what it is done to or with, for whom, who receives
#: what it passes, where it moves, how long it lasts, what it is for, and when it is (`relation_types`, "event
#: participants" and the temporal links).
_HAPPENING = frozenset(EVENT_PARTICIPANTS + (
    "done_with", "done_for", "received_by", "has_purpose", "lasts_until", "lasts_since", "lasts_for",
    "moves_to", "moves_into", "moves_onto", "moves_from", "moves_out_of", "moves_through", "moves_across",
    "moves_over", "moves_around", "moves_toward", "moves_up", "moves_down", "during", "precedes", "follows"))

def _says_of_happening(says: Iterable[Tuple[Any, ...]]) -> bool:
    """Whether what a shape says more of its word's thing (`_note_shape_phrase`) is said of a happening: who does it,
    when it is ("barked": before now; "dwindles": done by what was spoken of)."""
    return any(fact[0] in _HAPPENING for fact in says)


#: Of those, the ones saying only when something is and how long it lasts, which the meaning also says of a thing
#: there was or will be: "There was a dog." places one dog before now, and "a year ago" a year that lasts until now.
_WHEN = frozenset(("during", "precedes", "follows", "lasts_until", "lasts_since", "lasts_for"))


#: The relations whose object is a number: how many, and what a number or an operation is made of
#: (`relation_types`, arithmetic). Their objects are numbers, never a word for something else.
_NUMBERED = frozenset(("has_count", "has_rank", "has_addend", "has_factor", "has_augend", "has_minuend",
                       "has_subtrahend", "has_multiplicand", "has_dividend", "has_divisor", "has_base",
                       "has_exponent", "has_radicand", "has_index"))


def _role_of_term(facts: Iterable["MeaningFact"], term: str) -> str:
    """What a meaning takes a term as, where it is not a thing:

      closed    a count or a number (the object of `_NUMBERED`: "two", "most", the parts of "twenty-one") or a degree's
                own word (what a degree `has_property`: "very"): words of a class English does not add to
      quality   what a thing or a happening `has_property` ("red", "warily"), or the kind of a degree ("big")
      doing     the kind of a happening (`_HAPPENING`)
      kind      the kind of a thing (`instance_of`), or either side of `isa`
      name      what something is `named` ("Tom" in "My name is Tom.", "I am Tom.")
      thing     anything else: a thing, or a kind said of generally ("Tom" in `owns(Tom, ?x)`, "rain" in `causes`)"""
    facts = tuple(facts)
    degrees = {f.obj for f in facts if f.relation == "has_degree"}
    if any(f.relation in _NUMBERED and f.obj == term for f in facts) or any(
            f.relation == "has_property" and f.obj == term and f.subject in degrees for f in facts):
        return "closed"
    if any(f.relation == "has_property" and f.obj == term for f in facts) or any(
            f.relation == "instance_of" and f.obj == term and f.subject in degrees for f in facts):
        return "quality"
    things = {f.subject for f in facts if f.relation == "instance_of" and f.obj == term}
    if any(f.subject in things and f.relation in _HAPPENING for f in facts):
        return "doing"
    if things or any(f.relation == "isa" and term in (f.subject, f.obj) for f in facts):
        return "kind"
    if any(f.relation == "named" and f.obj == term for f in facts):
        return "name"
    return "thing"


def _facts_of(construction: Any) -> Tuple["MeaningFact", ...]:
    """The facts a construction states, whichever kind it is. A `Phrase` keeps them on `facts` and a `Pattern` on its
    meaning's, and `_fillers` is handed either -- its slot's fillers are asked for by `_phrase_fillings` too, for all
    that its own annotation says `Pattern`."""
    if isinstance(construction, Pattern):
        return tuple(construction.meaning.facts)
    if isinstance(construction, Phrase):
        return tuple(construction.facts)
    return ()


def _role_of_slot(construction: Any, slot: str) -> str:
    """What a construction takes what stands in its slot as (`_role_of_term`)."""
    if isinstance(construction, Pattern):
        return _role_of_term(construction.meaning.facts, slot)
    if isinstance(construction, Phrase):
        return _role_of_term(construction.facts, slot)
    return "thing"


def _taken_as(construction: Any, slot: str) -> Tuple[str, ...]:
    """What a construction's slot takes its fillers as, as kinds join them (`PatternInventory._join`): a count, a
    quality, a doing, or a thing -- a kind, a name and a thing (`_role_of_slot`) each name what is, or what is of a
    kind. These are the parts of the meaning language, never of English, and found from each frame's own meaning; the
    kinds inside each are learned from the links alone, so a kind never taught before is a kind of its own.

    A WORD IS IN A KIND FOR EACH PART IT STANDS IN, APART: "three" counts in "three dogs" and is a thing in "Three is
    a number.", and "fly" is done where birds fly and is a thing where a fly is an insect. Joined as one filler,
    every count was a thing and every thing a count: after WordNet's numbers one kind held 139,197 of 139,286 fillers,
    any word stood in any slot, and "Is a first amendment part of a bill of Rights?" never finished reading, with
    "amendment" and "part" read as counts (2026-10-11).

    A KIND OF HAPPENING THE MEANING ONLY PLACES IN TIME (`_WHEN`) IS ALSO A KIND OF THING: the meaning says the same of
    a dog there was ("There was a dog.": one, before now) as of a barking ("?slot0 twice": two, before now), and
    English says the one as a thing and the other as a doing. The slot takes either, each as its fillers stand. A
    happening someone does or something undergoes (`done_by`, `done_to`, ...) is a doing alone. A STATE IS A QUALITY
    PLACED IN TIME (`state_of`, `relation_types`): "The box will be empty." is the box's being empty, after now, as
    "The box is empty." says it holds (`has_property`); the slot takes what qualities are."""
    if isinstance(construction, Pattern):
        facts = construction.meaning.facts
    elif isinstance(construction, Phrase):
        facts = construction.facts
    else:
        return ("thing",)
    role = _role_of_term(facts, slot)
    if role == "doing":
        things = {f.subject for f in facts if f.relation == "instance_of" and f.obj == slot}
        if any(f.relation == "state_of" and f.subject in things for f in facts):
            return ("quality",)
        if all(f.relation in _WHEN for f in facts if f.subject in things and f.relation in _HAPPENING):
            return ("doing", "thing")
        return ("doing",)
    return ("thing",) if role in ("kind", "name", "thing") else (role,)


def _new_stands(meaning: "Meaning", new: Iterable["Lexical"], first_word: str) -> bool:
    """Whether every word never met stands, in the meaning a reading composed, in a role its writing allows
    (`_may_stand_new`). Checked in each slot too (`_fillers`); a phrase can carry what stands in its slot into another
    role: "the word reversed", a kind in "the ?slot0", was made the kind of a happening."""
    for lexical in new:
        first = len(lexical.words) == 1 and _fold(lexical.words[0]) == _fold(first_word)
        role = _role_of_term(meaning.facts, lexical.value)
        if not _may_stand_new(role, lexical.form, lexical.value, first):
            return False
        # A HAPPENING SAID AS "THE X" IS ONE THE LISTENER ALREADY KNOWS OF; a word never met names nothing known:
        # "the dust" stood as what another one did.
        if role == "doing" and any(f.relation == "instance_of" and f.obj == lexical.value and f.given
                                   for f in meaning.facts):
            return False
    return True


def _never_a_thing(view: PatternInventory, word: str) -> bool:
    """Whether memory holds a word as a QUALITY and never as a thing: observed an ADJECTIVE or an ADVERB (net of what
    refuted it) and never a NOUN, a NAME or a NUMERAL.

    `_may_stand_new` judges a word never met by its WRITING alone, and writing allows any word to stand as a thing,
    so a word's class was never asked in the one role that takes anything. "Tom walked annoyingly." was read
    `done_to(?v0, annoyingly)`, the adverb taken as the thing walked, with ADVERB held of it all along -- and the
    verb is no help, since `walk` does take a thing ("walk the dog"). Only where memory POSITIVELY says the word is
    a quality and says nothing of it as a thing: English does make a thing of a quality ("the poor"), and a word
    nothing is held of stands as anything, as it must.

    ASKED OF EVERY WORD OF A RUN, as a structure word is (the run that is no name because it holds one). Asked of a
    run's first word alone, the reading moved one word over and swallowed both: refused "annoyingly" as the thing
    walked, "Tom walked annoyingly." came back `isa(tom, walked annoyingly)` and `instance_of(?v0, snuff out)` with
    "walked annoyingly" minted as one two-word name (lyric_db, 2026-11-08)."""
    classes = view.word_classes.get(_fold(word), {})
    if any(classes.get(c, 0) > 0 for c in ("NOUN", "NAME", "NUMERAL")):
        return False
    return any(classes.get(c, 0) > 0 for c in ("ADJECTIVE", "ADVERB"))


def _may_stand_new(role: str, pieces: Tuple[Piece, ...], named: str, first: bool) -> bool:
    """Whether words never met may stand, as themselves, in a place of this role (`_role_of_term`). A word never met
    stands as itself: "ready" in "Are you ready?" is the quality called ready. What is guessed is its role, and its
    writing must allow that role. How many words a run may have is the slot's kind's (`_may_be_new`).

      - a number or a time written as one is a value, wherever it stands;
      - closed: never; English does not add counts or degree words ("currently using" is no count);
      - doing: one word, not written as a name ("Dear future", "called Family Day" are no doing);
      - quality, kind: not written as a name: a name names one thing ("Peter" is no kind, "Annas" no quality);
      - name: written as one, every word with a capital ("Family Day"): a run of common words is no one's name
        ("I am currently using Windows.");
      - thing: any word.

    Written as a name is a capital on the run's last word, unless the run is one word that begins the sentence,
    whose capital is the writing's and says nothing. How a quality or a doing must be written besides is the
    slot's (`_fillers`)."""
    if _quantity(named) or _temporal(named) or _mathematical(named):
        return True
    if role == "closed":
        return False
    capital = pieces[-1].text[:1].isupper() and not (first and len(pieces) == 1)
    if role == "doing":
        return len(pieces) == 1 and not capital
    if role in ("quality", "kind"):
        return not capital
    if role == "name":
        return all(piece.text[:1].isupper() for piece in pieces if not _is_mark(piece.text))
    return True


def _names_a_doing(construction: Any, slot: str) -> bool:
    """Whether a construction's slot names a kind of happening: what is one of its kind is done by or to something
    (`EVENT_PARTICIPANTS`), as "?slot0 the ?slot1" says of `instance_of(?n, ?slot0)`, done to `?slot1`."""
    if isinstance(construction, Pattern):
        facts = construction.meaning.facts
    elif isinstance(construction, Phrase):
        facts = construction.facts
    else:
        return False
    things = {f.subject for f in facts if f.relation == "instance_of" and f.obj == slot and f.positive}
    return any(f.subject in things and f.relation in EVENT_PARTICIPANTS for f in facts)


def _frame_says(frame: Union[Pattern, Phrase], slot: str, said: Iterable[FrozenSet[Tuple[Any, ...]]]) -> bool:
    """Whether a construction states, of every thing its slot is the kind of, what one of these shapes says (`@` for
    the thing): "Only ?slot0 ?slot1." states that both its events were before now, as "walked" says."""
    facts = frame.meaning.facts if isinstance(frame, Pattern) else frame.facts
    things = {f.subject for f in facts if f.relation == "instance_of" and f.obj == slot}
    stated = {(f.relation, f.subject, f.obj, f.positive) for f in facts}
    return bool(things) and any(
        says and all((relation, thing if subject == "@" else subject, thing if obj == "@" else obj, positive) in stated
                     for thing in things for relation, subject, obj, positive in says)
        for says in said)


#: What a packed word's value begins with (`Sense`): no concept is named so.
_STAND_IN = "\u27e8"


def _stand_in(construction: Any) -> bool:
    """Whether a construction is a packed word: words held for several things, standing for each of them (`Sense`)."""
    return isinstance(construction, Lexical) and construction.value.startswith(_STAND_IN)


@dataclass(frozen=True)
class Sense:
    """One thing a packed word may name where it stands: the word as held for it, the link it stands there through,
    held or only proposed for a filler of the slot's kind, and what taking it supposes there beyond its link: a filler
    written otherwise than the slot's own (`written_against`), a held filler never beside them (`stood_beside`), a
    number of a size never there (`sized_apart`).

    A WORD'S SENSES ARE KEPT TOGETHER, NEVER CROSSED. Read one by one, every sense of every word was crossed with every
    other into whole readings and nearly all were thrown away: "The function sorted returns a new list." built 18,101
    readings of which 168 could reach the listener (a copy of main, 2026-10-19). A word held for several things in one
    slot is one packed word (`_Filling.senses`); which thing it names is chosen over the structure (`meant`)."""

    lexical: Lexical
    link: Link
    held: bool
    sized: int = 0
    misfits: int = 0
    apart: int = 0


#: A packed word as a reading carries it: its stand-in, its senses with what each supposes in the whole reading, and
#: where its link stands among the reading's held links and among its proposed links.
Packed = Tuple[str, Tuple[Tuple[Sense, Tuple[int, int, int]], ...], int, int]


@dataclass(frozen=True)
class _Filling:
    """What stands in one slot, read: the anchor it puts there and the facts it adds, with the constructions and links
    that read it (its own construction first) and what that reading had to suppose."""

    anchor: str
    facts: Tuple[MeaningFact, ...]
    constructions: Tuple[Construction, ...]
    links: Tuple[Link, ...] = ()
    proposed: Tuple[Link, ...] = ()
    new: Tuple[Lexical, ...] = ()
    #: For a phrase none holds, the held ones it stands where they stand (`shaped_phrases`).
    like: Tuple[str, ...] = ()
    #: How many numbers it puts in a number phrase's slot that is taught numbers of other sizes (`sized_apart`).
    apart: int = 0
    #: How many of its phrases' own words it read through another said in their place (`_said_for`), as a frame's are.
    said_for: int = 0
    #: Its packed words (`Sense`): each stand-in, its senses, and where its link stands among these links and among
    #: these proposed links.
    senses: Tuple[Tuple[str, Tuple[Sense, ...], int, int], ...] = ()
    #: For each packed word in the first slot of a phrase proposed for a slot, that proposed link: the phrase is judged
    #: by the word it writes first (`PatternInventory.fits`), which differs sense by sense.
    heads: Tuple[Tuple[str, Link], ...] = ()
    #: The packed word standing in its own construction's first slot, where that is one.
    head: str = ""


def _side_by_side(combo: Sequence[_Filling]) -> Tuple[Tuple[Link, ...], Tuple[Link, ...],
                                                     Tuple[Tuple[str, Tuple[Sense, ...], int, int], ...],
                                                     Tuple[Tuple[str, Link], ...]]:
    """The links, proposed links, packed words and judged heads of fillings standing one after another, each packed
    word's place among the links moved past the links before it."""
    links: Tuple[Link, ...] = ()
    proposed: Tuple[Link, ...] = ()
    senses: Tuple[Tuple[str, Tuple[Sense, ...], int, int], ...] = ()
    heads: Tuple[Tuple[str, Link], ...] = ()
    for filling in combo:
        senses += tuple((stand_in, options, at + len(links), offered + len(proposed))
                        for stand_in, options, at, offered in filling.senses)
        heads += filling.heads
        links += filling.links
        proposed += filling.proposed
    return links, proposed, senses, heads


def _composed(facts: Iterable[MeaningFact], anchor: Optional[str],
              fillings: Mapping[str, _Filling]) -> Optional[Tuple[Optional[str], Tuple[MeaningFact, ...]]]:
    """A construction's facts, and its anchor when it is a phrase, with every slot filled; None when that makes no
    meaning (a fact of its own stated twice).

    A slot's variable becomes its filling's anchor, and the filling's facts join. Where the construction uses a slot
    only as a thing's kind (`instance_of(?x, ?slot0)`) and the filling stands for a thing, the filling describes that
    thing: its facts are said of `?x`, in place of `instance_of(?x, ?slot0)`. A slot a kind is said of (`isa`) takes
    a kind, never a filling that stands for a thing: "a glintbsrtp bird" there is a kind of its own, not some bird
    that is glintbsrtp; nor does one the construction takes as the kind of several things ("Only ?slot0 ?slot1.":
    the event done and the one not done), since a thing describes one thing. These are rules of the meaning language, kinds and their instances, not of English. A
    filling's own unknowns are renamed apart from everything else's, and what it says of a thing named only in a
    condition is said in the condition too; of one the construction does not tell as so (`MeaningFact.unasserted`:
    "Tom says that the dog will bark.", "will bark" in a place held as Tom's), not told as so either."""
    out = list(facts)
    added: List[MeaningFact] = []
    names: Dict[str, str] = {}
    fresh = itertools.count()
    for slot, filling in fillings.items():
        free = {t for f in filling.facts for t in f.terms()} | {filling.anchor}
        apart = {v: f"?u{next(fresh)}" for v in sorted(free) if is_variable(v) and not _named(v)}
        # A number the filling builds from numbers ("twenty-one") stands for its value, as "21" would.
        values, said = _valued(f.renamed(apart) for f in filling.facts)
        thing_of = apart.get(filling.anchor, filling.anchor)
        thing_of = values.get(thing_of, thing_of)
        said = list(said)
        uses = [f for f in out if slot in f.terms()]
        if is_variable(thing_of) and not _named(thing_of) and slot != anchor \
                and any(f.relation == "isa" and slot in (f.subject, f.obj) for f in uses):
            return None
        described = (slot != anchor and uses and is_variable(thing_of) and not _named(thing_of)
                     and all(f.relation == "instance_of" and f.obj == slot and f.subject != slot and f.positive
                             and not f.alternative for f in uses)
                     and len({(f.subject, f.condition, f.unasserted) for f in uses}) == 1)
        if not described and is_variable(thing_of) and not _named(thing_of) and slot != anchor \
                and any(f.relation == "instance_of" and f.obj == slot for f in uses):
            return None        # a thing is never a kind: one standing for a thing describes one thing, or none
        if described:
            thing, condition, unasserted = uses[0].subject, uses[0].condition, uses[0].unasserted
            out = [f for f in out if f not in uses]
            added.extend(MeaningFact(f.relation, thing if f.subject == thing_of else f.subject,
                                     thing if f.obj == thing_of else f.obj, f.positive, condition,
                                     unasserted=unasserted or f.unasserted, given=f.given) for f in said)
        else:
            names[slot] = thing_of
            condition = bool(uses) and all(f.condition for f in uses)
            unasserted = bool(uses) and all(f.unasserted for f in uses)
            added.extend(MeaningFact(f.relation, f.subject, f.obj, f.positive, condition,
                                     unasserted=unasserted or f.unasserted, given=f.given) for f in said)
    own = [f.renamed(names) for f in out]
    if len(set(own)) != len(own):
        return None
    for fact in (f.renamed(names) for f in added):
        if fact not in own:
            own.append(fact)
    return (names.get(anchor, anchor) if anchor is not None else None), tuple(own)


def _composed_meaning(meaning: Meaning, fillings: Mapping[str, _Filling]) -> Optional[Meaning]:
    composed = _composed(meaning.facts, None, fillings)
    if composed is None:
        return None
    try:
        return Meaning(meaning.act, composed[1], meaning.asked)
    except ValueError:
        return None


def _span(pieces: Tuple[Piece, ...], start: int, end: int) -> Tuple[Tuple[Piece, ...], str, bool]:
    """A run of words as a chart keeps what reads it (`_Chart`): its pieces, the word after it, which decides the
    shape a frame's word is written in before it (`_written_shapes`), and whether a word comes before it, which
    decides whether a capital on its first word says anything (`_may_stand_new`). Nothing else of where it stands is
    read: two runs alike in these read alike."""
    return (pieces[start:end], pieces[end].text if end < len(pieces) else "",
            any(not _is_mark(p.text) for p in pieces[:start]))


class _Chart:
    """What one reading of one run of pieces has read so far, so nothing in it is read twice: the phrases read over
    each span (`_phrase_fillings`), and what may stand in each frame's slot over each span (`_slot_fillings`).

    A frame's ways of covering the words share their spans -- the first slot of "?slot0 ?slot1 ?slot2." covers the
    same words for every place the second can end -- so without the second, a long run of words read each slot over
    each span as many times as there are ways to cover the rest: twenty times over on a paragraph of prose, for
    minutes. What stands in a slot over a span whose phrases are being read now (`reading`) is not final until that
    reading ends, and is not kept.

    WHAT A RUN OF WORDS READS TO DEPENDS ON THE RUN, NOT WHERE IT STANDS (`_span`), so one chart serves every stretch
    of an utterance: read in parts, "A prime number is a natural number greater than 1 that has no divisors other
    than 1 and itself." is 252 stretches, each read with a chart of its own, and the phrases inside them were read
    again in every stretch holding them (on main, 2026-10-19).

    `packing`: words held for several things in a slot are one packed word (`Sense`), as a sentence is read
    (`_read_pieces`); learning and repairs look for one meaning and read every sense apart."""

    def __init__(self, packing: bool = False):
        self.packing = packing
        self.stand_ins: Dict[int, str] = {}
        self.phrases: Dict[int, List[_Filling]] = {}
        self.slots: Dict[Tuple, List[_Filling]] = {}
        self.adjuncts: Dict[int, List[Tuple[Adjunct, _Filling]]] = {}
        self.tails: Dict[int, List[Tuple[Tuple[Adjunct, _Filling], ...]]] = {}
        self.reading: set = set()
        self._runs: Dict[Tuple, int] = {}
        self._pieces: Optional[Tuple[Piece, ...]] = None
        self._at: Dict[Tuple[int, int], int] = {}

    def span(self, pieces: Tuple[Piece, ...], start: int, end: int) -> int:
        """The run of words `pieces[start:end]` as this chart keeps what reads it: one number for each run `_span`
        tells apart, found once for each place in the pieces being read. A run's pieces were looked up afresh at
        each place a covering reached, as long as the run is: 1,969,634 times reading one paragraph of prose
        (lyric_dev, 2026-10-23)."""
        if pieces is not self._pieces:
            self._pieces, self._at = pieces, {}
        run = self._at.get((start, end))
        if run is None:
            run = self._at[(start, end)] = self._runs.setdefault(_span(pieces, start, end), len(self._runs))
        return run


def _slot_fillings(view: PatternInventory, frame: Union[Pattern, Phrase], slot: str, pieces: Tuple[Piece, ...],
                   start: int, end: int, chart: _Chart, *, extend: bool, loose: bool) -> List[_Filling]:
    """Everything that may stand in one slot for `pieces[start:end]`: the lexical fillers `_fillers` finds, and the
    phrases read over those pieces (`_phrase_fillings`) that fill this slot through a held link or, with `extend`, a
    proposed link to a phrase of the slot's kind. Read once per chart."""
    span = chart.span(pieces, start, end)
    kept = (frame.key, slot, span)
    if kept in chart.slots:
        return chart.slots[kept]
    out: List[_Filling] = []
    alike = _alike(view, frame, slot)

    def sized(value: str) -> int:
        return 1 if view.sized_apart(frame.key, slot, value) else 0
    senses: List[Sense] = []
    for lexical, held, how in _fillers(view, frame, slot, pieces[start:end], extend=extend, loose=loose,
                                       first=not any(not _is_mark(p.text) for p in pieces[:start])):
        if chart.packing and how in ("linked", "kind") and not _valued_name(lexical.value):
            linked = how == "linked"
            senses.append(Sense(lexical, held, linked, sized(lexical.value),
                                0 if linked else int(view.written_against(frame.key, slot, lexical)),
                                0 if linked or lexical.key not in view._by_key
                                else int(not view.stood_beside(frame.key, slot, lexical.key))))
        elif how == "linked":
            out.append(_Filling(lexical.value, (), (lexical,), links=(held,), apart=sized(lexical.value)))
        else:
            out.append(_Filling(lexical.value, (), (lexical,), proposed=(held,),
                                new=(lexical,) if how == "new" else (), apart=sized(lexical.value)))
    if len(senses) == 1:
        (sense,) = senses
        out.append(_Filling(sense.lexical.value, (), (sense.lexical,), links=(sense.link,) if sense.held else (),
                            proposed=() if sense.held else (sense.link,), apart=sense.sized))
    elif senses:
        # ONE STAND-IN FOR A RUN OF WORDS, wherever it stands: two phrases reading the same words to the same meaning
        # are then alike, and a phrase keeps the first of them, as it keeps the first of two readings one by one.
        stand_in = chart.stand_ins.setdefault(span, f"{_STAND_IN}{len(chart.stand_ins) + 1}{_STAND_IN}"
                                                    f"{surface_of(pieces[start:end])}")
        out.append(_Filling(stand_in, (), (Lexical(pieces[start:end], stand_in),),
                            senses=((stand_in, tuple(senses), 0, 0),)))
    for filling in _phrase_fillings(view, pieces, start, end, chart, extend=extend, loose=loose):
        top = filling.constructions[0]
        held = view.link_between(frame.key, slot, top.key)
        apart = filling.apart + sized(_valued(filling.facts)[0].get(filling.anchor, filling.anchor)
                                      if filling.facts else filling.anchor)
        if held is not None:
            out.append(replace(filling, links=filling.links + (held,), apart=apart, like=(), head=""))
        elif extend and (alike(top.key)
                         or any(view.link_between(frame.key, slot, held) is not None
                                or alike(held) for held in filling.like)):
            offered = link(frame, slot, top)
            out.append(replace(filling, proposed=filling.proposed + (offered,), apart=apart, like=(), head="",
                               heads=filling.heads + (((filling.head, offered),) if filling.head else ())))
    # WHAT STANDS HERE, AND AN ADJUNCT AFTER IT, stand here as one: "the largest animal" and "on Earth", in a slot
    # "the largest animal" may stand in. Only in reading, as a link of a slot's kind is.
    if extend:
        for middle in range(start + 1, end):
            if not view.begins_adjunct(pieces[middle].text):
                continue
            after = _adjunct_fillings(view, pieces, middle, end, chart, loose=loose)
            if not after:
                continue
            for head in _slot_fillings(view, frame, slot, pieces, start, middle, chart, extend=extend, loose=loose):
                for adjunct, said in after:
                    joined = _adjoined(frame, slot, head, adjunct, said)
                    if joined is not None:
                        out.append(joined)
    if span not in chart.reading:
        chart.slots[kept] = out
    return out


def _adjunct_fillings(view: PatternInventory, pieces: Tuple[Piece, ...], start: int, end: int, chart: _Chart, *,
                      loose: bool) -> List[Tuple[Adjunct, _Filling]]:
    """Every adjunct that reads `pieces[start:end]`, with what it says there (of `ADJOINED`): its words matched as a
    phrase's are, and each of its slots filled as that slot of the frame it was found in is (`_slot_fillings`), so
    "in the ?slot1" takes what "The ?slot0 in the ?slot1 is ?slot2." takes there. The same words saying the same
    through several pairs of frames are read once, as they suppose least. Read once per chart."""
    key = chart.span(pieces, start, end)
    if key in chart.adjuncts:
        return chart.adjuncts[key]
    chart.adjuncts[key] = []
    span = pieces[start:end]
    if loose and _parted(span):
        return []
    words = tuple(_fold(p.text) for p in span) if loose else tuple(p.text for p in span)
    same = (lambda word, text: word == _fold(text)) if loose else str.__eq__
    missing = (lambda piece: _is_mark(piece.text)) if loose else (lambda piece: False)
    shaped, _ = _written_shapes(view, words, pieces[end].text if end < len(pieces) else "", loose=loose)
    found: Dict[Tuple[bool, bool, str], List[Tuple[Adjunct, _Filling]]] = {}
    for adjunct in view.adjuncts_after(span[0].text):
        frame = view.get(adjunct.frame)
        slots = [e.name for e in adjunct.form if isinstance(e, Slot)]
        anchors = sum(1 for e in adjunct.form if isinstance(e, Piece) and not _is_mark(e.text))

        def fill(k: int, a: int, b: int) -> List[_Filling]:
            return _slot_fillings(view, frame, slots[k], pieces, start + a, start + b, chart,  # type: ignore[arg-type]
                                  extend=True, loose=loose)
        for spans, options in _coverings(adjunct.form, words, same, missing, shaped, fill):
            said = _said_for(view, adjunct.form, words, spans, same)
            for combo in itertools.product(*options):
                here, held = _new_here(combo)
                if not _anchored(here, anchors + held):
                    continue
                composed = _composed(adjunct.facts, ADJOINED, dict(zip(slots, combo)))
                if composed is None:
                    continue
                links, proposed, packed, heads = _side_by_side(combo)
                filling = _Filling(ADJOINED, composed[1], tuple(x for c in combo for x in c.constructions),
                                   links, proposed, tuple(x for c in combo for x in c.new),
                                   apart=sum(c.apart for c in combo),
                                   said_for=said + sum(c.said_for for c in combo), senses=packed, heads=heads)
                kept = (adjunct.happening, adjunct.of_happening, _phrase_canonical(ADJOINED, filling.facts))
                found.setdefault(kept, []).append((adjunct, filling))
    chart.adjuncts[key] = [read for alike in found.values() for read in _least_claimed(alike, view)]
    return chart.adjuncts[key]


def _least_claimed(alike: Sequence[Tuple[Adjunct, _Filling]],
                   view: PatternInventory) -> List[Tuple[Adjunct, _Filling]]:
    """Of an adjunct's readings saying the same, each meaning once, through the reading that supposes least, else the
    first (`_adjunct_fillings`). Packed, which supposes least is decided for each choice of senses, as one by one, and
    each reading keeps the choices it wins (`_Filling.senses` narrowed)."""
    if len(alike) == 1:
        return list(alike)
    if not alike[0][1].senses:
        return [min(enumerate(alike), key=lambda pair: (_supposes(pair[1][1], view), pair[0]))[1]]
    words = [stand_in for stand_in, _, _, _ in alike[0][1].senses]
    each = [sorted({s.lexical.value for read in alike for w, options, _, _ in read[1].senses if w == word
                    for s in options}) for word in words]
    # SENSES THAT COST THE SAME ARE CHOSEN AS ONE. Which reading supposes least depends on a word's sense only
    # through what that sense costs in each reading (`_supposes`), so senses costing the same in every reading
    # always pick the same reading. Every choice of every sense was tried before: "To handle changes in electric
    # current caused by weather variations, ..." (UNDERSTANDS-PROSE-02) has six words of many senses each on main,
    # and was still being read 14 hours later (2026-10-22). Their cost groups are a few each.
    groups = []
    for i, word in enumerate(words):
        by_cost: Dict[Tuple[FrozenSet[Tuple[bool, int, int]], ...], List[str]] = {}
        for value in each[i]:
            by_cost.setdefault(tuple(
                frozenset((s.lexical.key not in view, 0 if s.held else 1, s.sized)
                          for w, options, _, _ in filling.senses if w == word
                          for s in options if s.lexical.value == value)
                for _, filling in alike), []).append(value)
        groups.append(list(by_cost.values()))
    won: Dict[int, List[Tuple[str, ...]]] = {}
    for chosen in itertools.product(*(range(len(g)) for g in groups)):
        best = None
        for k, (_, filling) in enumerate(alike):
            narrowed = _narrowed(filling, {word: frozenset((groups[i][chosen[i]][0],)) for i, word in enumerate(words)})
            if any(not options for _, options, _, _ in narrowed.senses):
                continue
            rank = (_supposes(narrowed, view), k)
            if best is None or rank < best:
                best = rank
        if best is not None:
            won.setdefault(best[1], []).append(tuple(str(g) for g in chosen))
    out = []
    for k in sorted(won):
        adjunct, filling = alike[k]
        out.extend((adjunct, _narrowed(filling, {word: frozenset(v for g in region[word] for v in groups[i][int(g)])
                                                 for i, word in enumerate(words)}))
                   for region in _regions(words, won[k]))
    return out


def _regions(words: Sequence[str], chosen: Sequence[Tuple[str, ...]]) -> List[Dict[str, FrozenSet[str]]]:
    """Choices of senses (a thing for each packed word) as regions, a set of things for each word, covering exactly
    them."""
    if not chosen:
        return []
    if len(words) == 1:
        return [{words[0]: frozenset(c[0] for c in chosen)}]
    rest: Dict[str, Set[Tuple[str, ...]]] = {}
    for c in chosen:
        rest.setdefault(c[0], set()).add(c[1:])
    by_rest: Dict[FrozenSet[Tuple[str, ...]], Set[str]] = {}
    for first, tails in rest.items():
        by_rest.setdefault(frozenset(tails), set()).add(first)
    return [{words[0]: frozenset(firsts), **region} for tails, firsts in by_rest.items()
            for region in _regions(words[1:], sorted(tails))]


def _adjoined(frame: Union[Pattern, Phrase], slot: str, head: _Filling, adjunct: Adjunct,
              said: _Filling) -> Optional[_Filling]:
    """What stands in a slot, followed by an adjunct, standing there as one: what it stands for, with what the adjunct
    says of it. Where the construction uses the slot only as a thing's kind ("The ?slot0 is red."), what stands there
    names the kind and the adjunct is said of the thing: "the book on the table" is a book, and on the table. Where it
    uses the slot otherwise, the adjunct is said of what stands there ("Tom in the house"). An adjunct saying what
    only a happening has follows only what names one: a slot naming a kind of happening (`_names_a_doing`), or what
    is said to be one ("walked", before now). It stands where what it follows stands, through a link proposed for
    it, as a filling of the slot's kind does: supposed, never held."""
    facts = frame.meaning.facts if isinstance(frame, Pattern) else frame.facts
    uses = [f for f in facts if slot in f.terms()]
    kind_of = bool(uses) and all(f.relation == "instance_of" and f.obj == slot and f.positive for f in uses)
    taken = {t for f in head.facts for t in f.terms()} | {head.anchor}
    fresh = (f"?j{n}" for n in itertools.count() if f"?j{n}" not in taken)
    if kind_of and not is_variable(head.anchor):
        # The thing is known to both, or not, as the construction says of what the slot is the kind of ("the").
        thing = next(fresh)
        own = (MeaningFact("instance_of", thing, head.anchor, given=all(f.given for f in uses)),) + head.facts
    else:
        thing, own = head.anchor, head.facts
    happening = (kind_of and _names_a_doing(frame, slot)) \
        or any(f.subject == thing and f.relation in _HAPPENING for f in own)
    if adjunct.happening and not happening:
        return None
    names = {t: next(fresh) for t in sorted({t for f in said.facts for t in f.terms()})
             if is_variable(t) and not _named(t) and t != ADJOINED}
    names[ADJOINED] = thing
    phrase = adjunct.phrase
    links, proposed, packed, heads = _side_by_side((head, said))
    return _Filling(thing, tuple(dict.fromkeys(own + tuple(f.renamed(names) for f in said.facts))),
                    head.constructions + (phrase,) + said.constructions, links,
                    proposed + (link(frame, slot, phrase),), head.new + said.new,
                    like=head.like, apart=head.apart + said.apart, said_for=head.said_for + said.said_for,
                    senses=packed, heads=heads)


def _phrase_fillings(view: PatternInventory, pieces: Tuple[Piece, ...], start: int, end: int,
                     chart: _Chart, *, extend: bool, loose: bool) -> List[_Filling]:
    """Every phrase that reads `pieces[start:end]`, read once and kept in `chart` for every slot that could take it:
    a phrase with no slots whose form is those words, or one whose slots hold fillers of their own, phrases
    included, so phrases nest."""
    key = chart.span(pieces, start, end)
    if key in chart.phrases:
        return chart.phrases[key]
    chart.phrases[key] = []              # read once; a phrase reading itself finds nothing
    span = pieces[start:end]
    words = tuple(_fold(p.text) for p in span) if loose else tuple(p.text for p in span)
    if not words or (loose and _parted(span)):
        return []
    chart.reading.add(key)
    same =(lambda word, text: word == _fold(text)) if loose else str.__eq__
    missing = (lambda piece: _is_mark(piece.text)) if loose else (lambda piece: False)
    shaped, stood = _written_shapes(view, words, pieces[end].text if end < len(pieces) else "", loose=loose)
    have = frozenset(words) | stood
    out: List[_Filling] = []
    # A word written in a shape that says more than its kind ("jumped", where "barked" and "walked" say a barking and
    # a walking before now), held by no filler that says only its concept: the phrase that shape would make of it.
    held = view.lexicals_with_words((_fold(span[0].text),), loose=True) if len(span) == 1 else ()
    if extend and len(span) == 1 and all(view.says_more(lx.words[0], lx.value) for lx in held) \
            and _may_be_new(span, view, 1):
        # A WORD HELD, SAYING MORE THAN ITS CONCEPT, IS THE CONCEPT IT IS HELD FOR, saying what its own shape says
        # (`said_in_shape`): "breathes", held for `breathe`, is a breathing done by what was spoken of. Undone afresh by each shape's best change,
        # "breathes" was `breathese` before now, by the change "bit" shows of "bite", and `breath` done by what was
        # spoken of (UNDERSTANDS-PROSE-01, 2026-10-18, by `scripts/trace_question.py --word breathes`). Only a word
        # none holds is undone afresh.
        # The held word stands in the reading as itself, met as often as it was, and is no new word: a reading through
        # it was weighed as a guess, and lost to every phrase held for another sense of the word.
        saying = ([(lx.value, says, tuple(view._shape_groups.get(says, ())), lx) for lx in held
                   for says in view.said_in_shape(lx.words[0], lx.value)] if held
                  else [(name, says, like, None) for name, says, like in view.shaped_phrases(span[0].text)])
        for name, says, held, word in saying:
            anchor = "?x"
            facts = (MeaningFact("instance_of", anchor, name),) + tuple(
                MeaningFact(relation, anchor if subject == "@" else subject, anchor if obj == "@" else obj, positive)
                for relation, subject, obj, positive in sorted(says))
            try:
                made = Phrase(span, anchor, facts)
            except ValueError:
                continue
            out.append(_Filling(anchor, facts, (made, word), like=held) if word is not None else
                       _Filling(anchor, facts, (made,), new=(Lexical(span, name),), like=held))
    for phrase in view.phrases_reading(have):
        if not view.counts(phrase) or (phrase.slots and not view.may_read(phrase.key, have, loose)):
            continue
        anchors = sum(1 for e in phrase.form if isinstance(e, Piece) and not _is_mark(e.text))
        slots = phrase.slots

        def fill(k: int, a: int, b: int) -> List[_Filling]:
            return _slot_fillings(view, phrase, slots[k], pieces, start + a, start + b, chart,
                                  extend=extend, loose=loose)
        for spans, options in _coverings(phrase.form, words, same, missing, shaped, fill):
            # A PHRASE'S WORD READ THROUGH ANOTHER SAID IN ITS PLACE is supposed, as a frame's is: "chased the ?slot0"
            # read "chased a cat" for nothing, "a" and "the" being said in each other's place where meanings do not
            # tell them apart, and tied with "The ?slot0 chased a ?slot1.", taught for it.
            said = _said_for(view, phrase.form, words, spans, same)
            if not slots:
                out.append(_Filling(phrase.anchor, phrase.facts, (phrase,), said_for=said))
                break
            for combo in itertools.product(*options):
                here, held = _new_here(combo)
                if not _anchored(here, anchors + held):
                    continue
                composed = _composed(phrase.facts, phrase.anchor, dict(zip(slots, combo)))
                if composed is None:
                    continue
                anchor, facts = composed
                links, proposed, packed, heads = _side_by_side(combo)
                first = combo[0] if isinstance(phrase.form[0], Slot) else None
                out.append(_Filling(anchor, facts, (phrase,) + tuple(x for c in combo for x in c.constructions),
                                    links, proposed, tuple(x for c in combo for x in c.new),
                                    apart=sum(c.apart for c in combo),
                                    said_for=said + sum(c.said_for for c in combo), senses=packed, heads=heads,
                                    head=first.anchor if first is not None and _stand_in(first.constructions[0])
                                    else ""))
    # THESE WORDS, READ THROUGH EACH PHRASE, AS THEY SUPPOSE LEAST. What a reading supposes is the sum of what its
    # parts suppose, and what a phrase reading them adds depends only on which phrase each part is -- so a reading of
    # these words through one phrase that supposes more than another through the same phrase can never be part of a
    # reading that supposes least. Kept, every one would be read again inside every phrase that takes it: as many
    # readings as there are ways to bracket the words, and "seven trillion three hundred and twelve billion five
    # million" has thousands. Readings that suppose as little as each other are all kept, one for each meaning.
    least: Dict[str, Tuple[int, bool, int]] = {}
    for filling in out:
        top = filling.constructions[0].key
        least[top] = min(least.get(top, _supposes(filling, view)), _supposes(filling, view))
    alike: Dict[Tuple[str, str], List[_Filling]] = {}
    for filling in out:
        top = filling.constructions[0].key
        if _supposes(filling, view) != least[top]:
            continue
        # A packed word in a reading that supposes least keeps the senses that suppose as little (`_least_senses`).
        filling = _least_senses(filling, view)
        alike.setdefault((top, _phrase_canonical(filling.anchor, filling.facts)), []).append(filling)
    out = [kept for fillings in alike.values() for kept in _claimed(fillings)]
    chart.reading.discard(key)
    chart.phrases[key] = out
    return out


def _supposes(filling: _Filling, view: PatternInventory) -> Tuple[int, bool, int, int]:
    """How much a reading of a phrase supposes, least first: new words, constructions not held, links proposed and
    words read through another said in their place, and numbers standing where numbers of their size never stood
    (`sized_apart`)."""
    new = sum(len(_loose(lexical.words)) for lexical in filling.new)
    unheld = any(c.key not in view for c in filling.constructions if not _stand_in(c))
    proposed, apart = len(filling.proposed) + filling.said_for, filling.apart
    costs = [[(sense.lexical.key not in view, 0 if sense.held else 1, sense.sized) for sense in options]
             for _, options, _, _ in filling.senses]
    # A sense held as no construction (a word in a shape, `_fillers`) supposes more only where nothing else did.
    unheld = unheld or any(all(cost[0] for cost in word) for word in costs)
    for word in costs:
        least = min(cost[1:] for cost in word if unheld or not cost[0])
        proposed, apart = proposed + least[0], apart + least[1]
    return new, unheld, proposed, apart


def _least_senses(filling: _Filling, view: PatternInventory) -> _Filling:
    """A filling that supposes least, each packed word left with the senses that suppose as little there: a sense that
    supposes more makes a reading that supposes more, which the phrase's readings never keep (`_phrase_fillings`)."""
    if not filling.senses:
        return filling
    new, unheld, _, _ = _supposes(filling, view)
    kept = []
    for stand_in, options, at, offered in filling.senses:
        costs = [((sense.lexical.key not in view), 0 if sense.held else 1, sense.sized) for sense in options]
        least = min(cost[1:] for cost in costs if unheld or not cost[0])
        kept.append((stand_in, tuple(sense for sense, cost in zip(options, costs)
                                     if cost[1:] == least and (unheld or not cost[0])), at, offered))
    return replace(filling, senses=tuple(kept))


def _claimed(fillings: Sequence[_Filling]) -> List[_Filling]:
    """Of readings of one run of words through one phrase saying the same, each meaning once: the reading with fewer
    constructions, else the first, as a phrase keeps one of its readings one by one (`_phrase_fillings`). Packed, two
    such readings are alike for every choice of senses both take, so the later keeps only the choices not already
    taken (`_Filling.senses` narrowed, in as many packed readings as the choices left need)."""
    if len(fillings) == 1:
        return list(fillings)
    order = sorted(range(len(fillings)), key=lambda k: (len(fillings[k].constructions), k))
    if not fillings[0].senses:
        return [fillings[order[0]]]
    taken: List[Dict[str, FrozenSet[str]]] = []
    out: List[Tuple[int, _Filling]] = []
    for k in order:
        filling = fillings[k]
        mine = {stand_in: frozenset(s.lexical.value for s in options) for stand_in, options, _, _ in filling.senses}
        left = [mine]
        for box in taken:
            left = [part for region in left for part in _without(region, box)]
        out.extend((k, _narrowed(filling, region)) for region in left)
        taken.append(mine)
    return [filling for _, filling in sorted(out, key=lambda pair: pair[0])]


def _without(region: Mapping[str, FrozenSet[str]], box: Mapping[str, FrozenSet[str]]) -> List[Dict[str, FrozenSet[str]]]:
    """The choices of senses in `region` (a set of things for each packed word) not in `box`, as regions."""
    if any(not (region[w] & box[w]) for w in region):
        return [dict(region)]
    out, inside = [], dict(region)
    for w in region:
        rest = region[w] - box[w]
        if rest:
            out.append({**inside, w: rest})
        inside[w] = region[w] & box[w]
    return out


def _narrowed(filling: _Filling, region: Mapping[str, FrozenSet[str]]) -> _Filling:
    """A packed filling with each packed word's senses narrowed to the things `region` leaves it."""
    return replace(filling, senses=tuple((stand_in, tuple(s for s in options if s.lexical.value in region[stand_in]),
                                          at, offered) for stand_in, options, at, offered in filling.senses))


def _valued_name(value: str) -> bool:
    """Whether a concept is a number, a formula or a day or a time, whose writing a meaning reads for its value
    (`_valued`): never packed, so what is composed of it is composed of its value."""
    return _quantity(value) or _temporal(value) or _mathematical(value)


def _analyses(words: Tuple[str, ...], view: PatternInventory, *, pieces: Optional[Tuple[Piece, ...]] = None,
              extend: bool = False, loose: bool = False, chart: Optional[_Chart] = None) -> List[Reading]:
    """Every reading of these words through constructions still believed, best first.

    Strict, as the learner reads: every slot holds a filler linked to it, a word or a phrase. `extend` lets a slot
    also hold a filler of its kind or new words (`_slot_fillings`); a reading takes new words only through a frame
    with words of its own, since those words are what anchor it (`_anchored`). A frame's word may be written in
    another of its shapes, as the word after it asks (`_written_shapes`). `loose` compares with case folded, lets a
    form's marks be missing and sets aside a final mark on what was said; a mark inside what was said is never set
    aside. `chart`: what was read of the runs of these words in other stretches of the same utterance, read the same
    way (`_Chart`); a chart of its own where none is given."""
    if pieces is None:
        pieces = tuple(Piece(w, True) for w in words)
    if loose:
        if pieces and _is_mark(pieces[-1].text):
            pieces = pieces[:-1]
        words = tuple(_fold(p.text) for p in pieces)
    same = (lambda word, text: word == _fold(text)) if loose else str.__eq__
    missing = (lambda piece: _is_mark(piece.text)) if loose else (lambda piece: False)
    out: List[Reading] = []
    for holophrase in view.with_words(words, loose=loose):
        if view.counts(holophrase) and (not loose or next(_chunkings(holophrase.form, words, same, missing), None)
                                        is not None):
            out.append(view.reading((holophrase,), (), holophrase.meaning, loose=loose))
    # A holophrase with one of its words said by another said in its place (`synonyms_of`): "Yes, she did." where
    # "Yes, he did." was taught. Supposed, as a frame's word read so is.
    if not loose:
        for at, word in enumerate(words):
            for other in view.synonyms_of(word):
                said = other.capitalize() if word[:1].isupper() else other
                for holophrase in view.with_words(words[:at] + (said,) + words[at + 1:], loose=False):
                    if view.counts(holophrase):
                        out.append(view.reading((holophrase,), (), holophrase.meaning, said_for=1))
    chart = chart if chart is not None else _Chart()

    def through(pattern: Pattern, words: Tuple[str, ...], shaped: Optional[Callable[[int, str], bool]],
                tails: Sequence[Tuple[Tuple[Adjunct, _Filling], ...]] = ((),)) -> None:
        """The readings of these words through one frame, and with each run of adjuncts after them (`tails`)."""
        form = pattern.form
        anchors = sum(1 for e in form if isinstance(e, Piece) and not _is_mark(e.text))
        slots = pattern.slots

        def fill(k: int, start: int, end: int) -> List[_Filling]:
            return _slot_fillings(view, pattern, slots[k], pieces, start, end, chart, extend=extend, loose=loose)
        for spans, options in _coverings(form, words, same, missing, shaped, fill):
            said_for = _said_for(view, form, words, spans, same)
            for combo in itertools.product(*options):
                here, held = _new_here(combo)
                if not _anchored(here, anchors + held):
                    continue
                new = tuple(x for c in combo for x in c.new)
                meaning = _composed_meaning(pattern.meaning, dict(zip(slots, combo)))
                if meaning is None or not _new_stands(meaning, new, words[0] if words else ""):
                    continue
                for tail in tails:
                    whole = _with_tail(pattern, meaning, tail) if tail else meaning
                    if whole is None:
                        continue
                    constructions = (pattern,) + tuple(x for c in combo for x in c.constructions) + tuple(
                        x for adjunct, said in tail for x in (adjunct.phrase,) + said.constructions)
                    held, offered, packed, heads = _side_by_side(tuple(combo) + tuple(
                        replace(said, proposed=said.proposed + (link(pattern, slots[-1], adjunct.phrase),))
                        for adjunct, said in tail))
                    sized = sum(c.apart for c in combo) + sum(s.apart for _, s in tail)
                    reading = view.reading(
                        constructions, held, whole, proposed=offered,
                        new=new + tuple(x for _, said in tail for x in said.new), loose=loose,
                        said_for=said_for + sum(c.said_for for c in combo) + sum(s.said_for for _, s in tail)
                        + _unsaid(view, constructions, held + offered, whole),
                        sized=sized)
                    out.append(_costed(reading, packed, heads, sized, view) if packed else reading)

    shaped, stood = _written_shapes(view, words, loose=loose)
    have = frozenset(words) | stood
    for pattern in view.item_based():
        if view.may_read(pattern.key, have, loose) and view.counts(pattern):
            through(pattern, words, shaped)
    # ADJUNCTS SAID OF WHAT A SENTENCE TELLS HAPPENED, after all its frame reads: "The company hired three engineers
    # in May." is "The company hired three engineers." and, of the hiring, "in May". Only in reading, as a link of a
    # slot's kind is.
    if extend and len(pieces) > 2 and _is_mark(pieces[-1].text):
        for middle in range(1, len(pieces) - 1):
            if not view.begins_adjunct(pieces[middle].text):
                continue
            tails = _tails(view, pieces, middle, len(pieces) - 1, chart, loose=loose)
            if not tails:
                continue
            short = words[:middle] + words[-1:]
            shaped, stood = _written_shapes(view, short, loose=loose)
            have = frozenset(short) | stood
            for pattern in view.item_based():
                if pattern.slots and view.may_read(pattern.key, have, loose) and view.counts(pattern):
                    through(pattern, short, shaped, tails)
    return sorted(out, key=_best_first)


def _tails(view: PatternInventory, pieces: Tuple[Piece, ...], start: int, end: int, chart: _Chart, *,
           loose: bool) -> List[Tuple[Tuple[Adjunct, _Filling], ...]]:
    """Every way `pieces[start:end]` reads as adjuncts said of a happening, one after another: "into the box in the
    morning"."""
    key = chart.span(pieces, start, end)
    if key in chart.tails:
        return chart.tails[key]
    chart.tails[key] = []
    out: List[Tuple[Tuple[Adjunct, _Filling], ...]] = []
    for middle in range(start + 1, end + 1):
        if middle < end and not view.begins_adjunct(pieces[middle].text):
            continue
        firsts = [read for read in _adjunct_fillings(view, pieces, start, middle, chart, loose=loose)
                  if read[0].of_happening]
        if not firsts:
            continue
        rests = [()] if middle == end else _tails(view, pieces, middle, end, chart, loose=loose)
        out.extend((first,) + rest for first in firsts for rest in rests)
    chart.tails[key] = out
    return out


def _with_tail(pattern: Pattern, meaning: Meaning, tail: Sequence[Tuple[Adjunct, _Filling]]) -> Optional[Meaning]:
    """A frame's reading with adjuncts after it said of what it tells happened: the one unknown of its own that is a
    happening in the reading (`_HAPPENING`). None when it tells of none, or of more than one."""
    own = {t for f in pattern.meaning.facts for t in f.terms() if is_variable(t) and not _named(t)}
    happenings = {f.subject for f in meaning.facts if f.relation in _HAPPENING and f.subject in own}
    if len(happenings) != 1:
        return None
    facts = list(meaning.facts)
    taken = {t for f in facts for t in f.terms()}
    fresh = (f"?j{n}" for n in itertools.count() if f"?j{n}" not in taken)
    for _, said in tail:
        names = {t: next(fresh) for t in sorted({t for f in said.facts for t in f.terms()})
                 if is_variable(t) and not _named(t) and t != ADJOINED}
        names[ADJOINED] = next(iter(happenings))
        facts.extend(f.renamed(names) for f in said.facts if f.renamed(names) not in facts)
    try:
        return Meaning(meaning.act, tuple(facts), meaning.asked)
    except ValueError:
        return None


def _costed(reading: Reading, packed: Sequence[Tuple[str, Tuple[Sense, ...], int, int]],
            heads: Sequence[Tuple[str, Link]], sized: int, view: PatternInventory) -> Reading:
    """A reading with packed words, each sense with what taking it supposes in this reading, as a reading of the same
    words with that sense in its place counts it (`Reading.supposed`, `PatternInventory.fits`, `_unsaid`): its link
    proposed, and the word read as less than it says where it stands in a phrase's slot; written against its slot,
    and against the slot of a phrase it writes first; never beside its slot's fillers, or a number of a size never
    there."""
    items = {c.key: c for c in reading.constructions}
    placed = {(f.relation, f.subject, f.positive) for f in reading.meaning.facts}
    costed = []
    for stand_in, options, at, offered in packed:
        judged = [l for word, l in heads if word == stand_in]
        things = {f.subject for f in reading.meaning.facts if f.relation == "instance_of" and f.obj == stand_in}
        costs = []
        for sense in options:
            lexical = sense.lexical
            unsaid = int(isinstance(items.get(sense.link.pattern), Phrase) and len(lexical.words) == 1
                         and view.says_more(lexical.words[0], lexical.value)
                         and not any(says and all((relation, thing, positive) in placed
                                                  for relation, subject, _, positive in says if subject == "@")
                                     for thing in things for says in view.said_by(lexical.words[0], lexical.value)))
            misfits = sense.misfits + sum(1 for l in judged if view.written_against(l.pattern, l.slot, lexical))
            costs.append((sense, ((0 if sense.held else 1) + unsaid, misfits, sense.sized + sense.apart)))
        costed.append((stand_in, tuple(costs), at, offered))
    return replace(reading, senses=tuple(costed), sized=sized)


def _inserted(links: Tuple[Link, ...], placed: Sequence[Tuple[int, Link]]) -> Tuple[Link, ...]:
    """Links with others put in at their places, in order."""
    out: List[Link] = []
    at = 0
    for position, l in placed:
        out.extend(links[at:position])
        at = position
        out.append(l)
    out.extend(links[at:])
    return tuple(out)


def with_senses(reading: Reading, chosen: Mapping[str, Sense], view: PatternInventory) -> Optional[Reading]:
    """A packed reading with a sense chosen for each packed word: the reading the words make with those senses in
    place, as a reading of them one by one makes it; None where those senses make no meaning (two of its facts become
    one)."""
    if not reading.senses:
        return reading
    names = {stand_in: chosen[stand_in].lexical.value for stand_in, _, _, _ in reading.senses}
    facts = tuple(replace(f, subject=names.get(f.subject, f.subject), obj=names.get(f.obj, f.obj))
                  for f in reading.meaning.facts)
    if len(set(facts)) != len(facts):
        return None
    try:
        meaning = Meaning(reading.meaning.act, facts, reading.meaning.asked)
    except ValueError:
        return None
    constructions = tuple(chosen[c.value].lexical if _stand_in(c) else c for c in reading.constructions)
    senses = [(chosen[stand_in], at, offered, dict((id(s), cost) for s, cost in options)[id(chosen[stand_in])])
              for stand_in, options, at, offered in reading.senses]
    links = _inserted(reading.links, [(at, sense.link) for sense, at, _, _ in senses if sense.held])
    proposed = _inserted(reading.proposed, [(offered, sense.link) for sense, _, offered, _ in senses if not sense.held])
    unsaid = sum(cost[0] - (0 if sense.held else 1) for sense, _, _, cost in senses)
    return view.reading(constructions, links, meaning, proposed=proposed, new=reading.new, loose=reading.loose,
                        said_for=reading.said_for + unsaid, sized=reading.sized + sum(s.sized for s, _, _, _ in senses))


def _unsaid(view: PatternInventory, constructions: Iterable[Construction], links: Iterable[Link],
            meaning: Meaning) -> int:
    """How many words standing in a phrase's slots a reading takes as less than they say: a word that says more
    than its concept ("kicked", a kicking before now; `says_more`) where the reading places what it names nowhere by
    what the word says (`said_by`: before something). A phrase is read inside frames other than the one it was
    learned in: "kicked" was linked in "?slot0 the ?slot1" where the frame around said "before now" ("Tom kicked the
    ball into the box."), and read in "?slot0 ?slot1.", which says nothing of time, "Tom kicked the ball." was a
    kicking at no time and tied with the reading taught. A word in a sentence frame's own slot was linked with that
    frame ("If it rained, ..."), and is not judged here. Supposed, as a word read through another is."""
    items = {c.key: c for c in constructions}
    in_phrases = {l.lexical for l in links if isinstance(items.get(l.pattern), Phrase)}
    placed = {(f.relation, f.subject, f.positive) for f in meaning.facts}
    count = 0
    for key in in_phrases:
        item = items.get(key)
        if not isinstance(item, Lexical) or len(item.words) != 1 or not view.says_more(item.words[0], item.value):
            continue
        things = {f.subject for f in meaning.facts if f.relation == "instance_of" and f.obj == item.value}
        if not any(says and all((relation, thing, positive) in placed for relation, subject, _, positive in says
                                if subject == "@")
                   for thing in things for says in view.said_by(item.words[0], item.value)):
            count += 1
    return count


def _said_for(view: PatternInventory, form: Tuple[FormElement, ...], words: Tuple[str, ...],
              spans: Tuple[Tuple[int, int], ...], same: Callable[[str, str], bool]) -> int:
    """How many of a frame's own words these words read through another said in their place: a word that is not
    the frame's, nor one of its shapes the letter after it decides."""
    count, at, slots = 0, 0, iter(spans)
    for element in form:
        if isinstance(element, Slot):
            at = next(slots)[1]
            continue
        if at < len(words) and same(words[at], element.text):
            at += 1
        elif at < len(words) and _fold(element.text) in view.written_for(words[at], words[at + 1] if at + 1 < len(words) else ""):
            count += _fold(element.text) not in view.variants_of(words[at])
            at += 1
    return count


def _anchored(new: Tuple[Lexical, ...], anchors: int) -> bool:
    """Whether the new names standing in one construction's slots are anchored, by its own words and by each slot
    holding something held. A new name of one word stands where the construction puts it, so any number do ("Rain
    causes floods.", neither word ever met, through "?slot0 causes ?slot1."); a run of new words is also a guess at
    where a name begins and ends, so with one among them, no more new names than anchors. With no anchor, none: a
    phrase of slots alone takes a new name only beside something held ("glorpy dogs"). A number written as a number is
    no guess at a name: its writing says what it is (`_quantity`), so it needs no anchor ("$4.25" through "$?slot0",
    whose "$" is a mark)."""
    new = tuple(lexical for lexical in new if not _quantity(str(lexical.value)) and not _temporal(str(lexical.value)))
    if not new:
        return True
    if not anchors:
        return False
    return len(new) <= anchors or all(len(lexical.words) == 1 for lexical in new)


def _new_here(combo: Iterable[_Filling]) -> Tuple[Tuple[Lexical, ...], int]:
    """The new names standing directly in a construction's slots, and how many of its slots hold nothing new; a new
    name inside a phrase is that phrase's to anchor."""
    combo = tuple(combo)
    return (tuple(c.new[0] for c in combo if c.new and c.constructions[0] is c.new[0]),
            sum(1 for c in combo if not c.new))


def readings_of(words: Tuple[str, ...], meaning: Meaning, view: PatternInventory) -> List[Reading]:
    """The readings of these words that give exactly this meaning, best first: strictly, through links only, as
    the learner reads a taught pair."""
    target = meaning.canonical()
    return [r for r in _analyses(tuple(words), view) if r.meaning.canonical() == target]


def _read_pieces(pieces: Tuple[Piece, ...], view: PatternInventory,
                 charts: Optional[Dict[bool, _Chart]] = None) -> Tuple[Reading, ...]:
    """The meanings these pieces read to, best reading of each first, from the readings that had to suppose the
    least: none that had to suppose more is reported beside one that supposed less.

    Pieces with a mark before their last that no reading goes on past (`reads_past`) have no reading, and none is
    searched for: a loose reading sets aside only the last mark. Searched, three sentences of prose taken as one,
    through ends nothing taught runs past, cost minutes.

    `charts`: what was read of runs of words in other stretches of the same utterance, strictly and loosely, shared
    (`_Chart`); what is read here is kept in them."""
    if not view.reads_past(pieces):
        return ()
    words = tuple(p.text for p in pieces)
    charts = {} if charts is None else charts
    for loose in (False, True):
        if loose not in charts:
            charts[loose] = _Chart(packing=True)
    found = (_analyses(words, view, pieces=pieces, extend=True, chart=charts[False])
             or _analyses(words, view, pieces=pieces, extend=True, loose=True, chart=charts[True]))
    if not found:
        return ()
    least = found[0].supposed
    # EVERY SENSE OF THE WORDS READ REACHES THE LISTENER. A reading saying the same words as a best one, of another
    # thing, stays, however much more it supposed of the words' places: whether its word was linked in this frame,
    # stood where the slot's words stand, is written as they are. That is how well the sense fits there, and it is the
    # listener's evidence (`meant`), not a cut: cut, it set aside the computer's mouse ("A mouse is a device.", its
    # word linked in the "an" twin), the bird's wing, and a synonym's every sense, before the listener heard of them.
    # A reading that read loosely, or took more words as new names, is another reading of the words, not another
    # sense, and is still set aside.
    # Structures that supposed as little as each other all go to the listener, who weighs what memory knows of each
    # and how probable each is (`meant`).
    def settled(supposed: Tuple) -> Tuple:
        return supposed[:2]

    worded = {_worded(reading, view) for reading in found if reading.supposed == least}
    if logger.isEnabledFor(logging.DEBUG):
        # WHICH READING WAS CUT BEFORE THE LISTENER, AND BY WHICH TEST. A sense offered as a filler still has to
        # suppose no more of its words' places than the best reading did, or say the same words as one that
        # supposed as little. Of the three senses of "note" offered here, none reached `meant`.
        for reading in found:
            kept = reading.supposed == least or (settled(reading.supposed) == settled(least)
                                                 and _worded(reading, view) in worded)
            logger.debug("pieces: %s %r supposed=%s least=%s settled_alike=%s worded_known=%s",
                         "KEPT " if kept else "CUT  ",
                         reading.meaning.canonical() if reading.meaning is not None else None,
                         reading.supposed, least, settled(reading.supposed) == settled(least),
                         _worded(reading, view) in worded)
    best: Dict[str, Reading] = {}
    packed: List[Reading] = []
    for reading in found:
        if reading.supposed == least or (settled(reading.supposed) == settled(least)
                                         and _worded(reading, view) in worded):
            if reading.senses:
                # A PACKED READING IS KEPT WHOLE: which reading of a meaning is kept is decided for each choice of
                # senses (`unpacked`, `meant`), and two packed readings alike may keep different choices. Less the
                # choices naming one thing with two words, whose wording is their own (`_one_thing_twice`).
                packed.extend(_one_thing_twice(reading, least, worded, view))
            else:
                best.setdefault(reading.meaning.canonical(), reading)
    return tuple(sorted(list(best.values()) + packed, key=_best_first))


def _reading_narrowed(reading: Reading, region: Mapping[str, FrozenSet[str]]) -> Optional[Reading]:
    """A packed reading with each packed word's senses narrowed to the things `region` leaves it; None where one is
    left none."""
    senses = tuple((stand_in, tuple((s, c) for s, c in options if s.lexical.value in region[stand_in]), at, offered)
                   for stand_in, options, at, offered in reading.senses)
    return replace(reading, senses=senses) if all(options for _, options, _, _ in senses) else None


def _one_thing_twice(reading: Reading, least: Tuple, worded: AbstractSet[str],
                     view: PatternInventory) -> List[Reading]:
    """A packed reading `_read_pieces` keeps, less the choices of senses it would not keep one by one: where two of
    its words name one thing ("wheel" the bicycle, "bike" the bicycle), or a word names what a held word in it names,
    the reading is worded with one word for both (`_worded`), so it is kept only where that wording is a reading
    supposing least's, or it supposes least itself. Elsewhere every choice is worded as the packed reading is."""
    words = [stand_in for stand_in, _, _, _ in reading.senses]
    values = {stand_in: frozenset(s.lexical.value for s, _ in options) for stand_in, options, _, _ in reading.senses}
    held = {c.value for c in reading.constructions if isinstance(c, Lexical) and not _stand_in(c)}
    boxes: List[Dict[str, FrozenSet[str]]] = []
    for k, a in enumerate(words):
        for b in words[k + 1:]:
            boxes.extend({a: frozenset((v,)), b: frozenset((v,))} for v in sorted(values[a] & values[b]))
        boxes.extend({a: frozenset((v,))} for v in sorted(values[a] & held))
    if not boxes:
        return [reading]
    regions: List[Dict[str, FrozenSet[str]]] = [dict(values)]
    for box in boxes:
        whole = {w: box.get(w, values[w]) for w in words}
        some = with_senses(reading, {w: next(s for s, _ in options if s.lexical.value in whole[w])
                                     for w, (_, options, _, _) in zip(words, reading.senses)}, view)
        if some is not None and some.supposed[:2] == least[:2] and _worded(some, view) in worded:
            continue
        regions = [part for region in regions for part in _without(region, whole)]
        # Of these choices, those supposing least are kept as such.
        cheapest = {w: frozenset(s.lexical.value for s, c in options if c == min(c for _, c in options)) & whole[w]
                    for w, (_, options, _, _) in zip(words, reading.senses)}
        narrowed = _reading_narrowed(reading, cheapest)
        if narrowed is not None and narrowed.supposed == least:
            regions.append(cheapest)
    return [r for r in (_reading_narrowed(reading, region) for region in regions) if r is not None]


def read(sentence: str, inventory: Optional[PatternInventory] = None) -> Tuple[Reading, ...]:
    """Every meaning this sentence can be read to, best reading of each first; empty when nothing reads it.

    More than one when the same words were taught, or can be combined, to mean different things. That is reported,
    never resolved here: which one is meant is decided by the situation and the scores, by whoever is listening
    (`meant`). Every meaning, each choice of its words' senses made (`unpacked`); a conversation reads with its words'
    senses kept together (`read_text`) and the listener chooses among them over the structure.
    """
    view = inventory if inventory is not None else _live_inventory()
    pieces = form_of(sentence)
    if not pieces:
        return ()
    return unpacked(_read_pieces(pieces, view), view)


@dataclass(frozen=True)
class Stretch:
    """Part of an utterance that read on its own when nothing read the whole of it: where it stands among the
    utterance's pieces, and what it read as -- a sentence (`readings`), or what held fillers name (`fillers`)."""

    start: int
    end: int
    pieces: Tuple[Piece, ...]
    readings: Tuple[Reading, ...] = ()
    fillers: Tuple[Lexical, ...] = ()

    @property
    def text(self) -> str:
        return surface_of(self.pieces)


@dataclass(frozen=True)
class Utterance:
    """One stretch of a text read on its own: its pieces, and its readings -- none when nothing held reads it.

    When nothing reads the whole of it, it is still read as far as it can be: `partial` holds the parts that read
    on their own, as many of its pieces as can be read that way, and `unknown` the words nothing held has at all.
    What a part reads as is what was understood of it, never what was said: the part that did not read may deny
    it or make it conditional ("It is not true that the door is open.")."""

    pieces: Tuple[Piece, ...]
    readings: Tuple[Reading, ...]
    partial: Tuple[Stretch, ...] = ()
    unknown: Tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return surface_of(self.pieces)

    @property
    def understood(self) -> bool:
        return bool(self.readings)

    @property
    def unread(self) -> Tuple[Tuple[Piece, ...], ...]:
        """The runs of pieces between the parts that read, when nothing read the whole utterance."""
        if self.understood:
            return ()
        runs, at = [], 0
        for stretch in self.partial + (Stretch(len(self.pieces), len(self.pieces), ()),):
            if stretch.start > at:
                runs.append(self.pieces[at:stretch.start])
            at = stretch.end
        return tuple(runs)


def _partial(pieces: Tuple[Piece, ...], view: PatternInventory,
             charts: Optional[Dict[bool, _Chart]] = None) -> Tuple[Tuple[Stretch, ...], Tuple[str, ...]]:
    """An utterance nothing reads whole, read in parts: the parts that read on their own covering as many of its
    pieces as they can, and the words outside them that nothing held has.

    A part reads as a sentence, as any utterance reads (a sentence's own words anchor a new name in it as they do
    anywhere), or as what a held filler names. Of the ways to cover the utterance with parts, the one reading the
    most pieces is taken; then the one reading the most of them as sentences, since a sentence says more than the
    names in it; then the one with the fewest parts."""
    n = len(pieces)
    found: Dict[Tuple[int, int], Stretch] = {}
    for i in range(n):
        for j in range(i + 1, n + 1):
            if (i, j) == (0, n):
                continue
            part = pieces[i:j]
            readings = _read_pieces(part, view, charts)
            if readings:
                found[(i, j)] = Stretch(i, j, part, readings=readings)
                continue
            words = tuple(p.text for p in part)
            if _parted(part):
                continue
            fillers = tuple(lx for lx in (view.lexicals_with_words(words)
                                          or view.lexicals_with_words(_loose(words), loose=True)) if view.counts(lx))
            if fillers:
                found[(i, j)] = Stretch(i, j, part, fillers=fillers)
    # best[j] covers pieces[:j]: ((pieces read, pieces read as sentences, -parts), the parts).
    best: List[Tuple[Tuple[int, int, int], Tuple[Stretch, ...]]] = [((0, 0, 0), ())]
    for j in range(1, n + 1):
        options = [best[j - 1]]
        for i in range(j):
            stretch = found.get((i, j))
            if stretch is not None:
                (read, as_sentences, parts), chosen = best[i]
                options.append(((read + j - i, as_sentences + (j - i if stretch.readings else 0), parts - 1),
                                chosen + (stretch,)))
        best.append(max(options, key=lambda option: option[0]))
    parts = best[n][1]
    covered = {k for stretch in parts for k in range(stretch.start, stretch.end)}
    unknown = tuple(dict.fromkeys(p.text for k, p in enumerate(pieces)
                                  if k not in covered and not _is_mark(p.text) and not view.knows(p.text)))
    return parts, unknown


#: The marks a quotation opens with, and the mark that closes each.
_QUOTES = {'"': '"', "“": "”"}


def set_apart(pieces: Tuple[Piece, ...]) -> Tuple[Tuple[Piece, ...], Tuple[Piece, ...]]:
    """A sentence with its quotation set apart: the pieces around it, the quotation standing as one (`QUOTED`), and
    the quoted words as a sentence of their own, ended as a sentence is: a comma where it ends is the end it stands
    for (`"The dog barked," Tom said.`), and an end is written where none is. The first quotation; with none, the
    pieces and nothing."""
    for at, piece in enumerate(pieces):
        closer = _QUOTES.get(piece.text)
        if closer is None:
            continue
        end = next((k for k in range(at + 1, len(pieces)) if pieces[k].text == closer), None)
        if end is None or end == at + 1:
            return pieces, ()
        quoted = pieces[at + 1:end]
        if quoted[-1].text == ",":
            quoted = quoted[:-1] + (Piece(".", False),)
        elif quoted[-1].text not in (".", "?", "!"):
            quoted = quoted[:-1] + (Piece(quoted[-1].text, False), Piece(".", False))
        return pieces[:at] + (Piece(QUOTED, pieces[end].space_after),) + pieces[end + 1:], quoted
    return pieces, ()


def quoted_pairs(sentence: str, meaning: Meaning, *rest: Any) -> List[Tuple[Any, ...]]:
    """A taught pair with a quotation, as the two pairs it is, each English to learn: the sentence around the
    quotation, meaning what the meaning holds outright (`Tom said, “…”`: a saying, done by Tom), and the quoted
    sentence, meaning what was said, here as that sentence's own ("The dog barked."). A pair without one, as it
    is."""
    around, quoted = set_apart(form_of(sentence))
    if not quoted or not meaning.unasserted:
        return [(sentence, meaning, *rest)]
    outright = tuple(f for f in meaning.facts if not f.unasserted)
    inner = tuple(MeaningFact(f.relation, f.subject, f.obj, f.positive, f.condition, f.alternative, given=f.given)
                  for f in meaning.unasserted)
    try:
        return [(surface_of(around), Meaning(meaning.act, outright, meaning.asked), *rest),
                (surface_of(quoted), Meaning("ask" if quoted[-1].text == "?" else "tell", inner), *rest)]
    except ValueError:
        return [(sentence, meaning, *rest)]


def _with_quotation(utterance: "Utterance", quoted: Tuple["Utterance", ...],
                    view: PatternInventory) -> "Utterance":
    """An utterance whose quotation was read apart, read whole: each reading of the words around it, with what the
    quotation was taken to mean (`meant`) as what was said (`MeaningFact.unasserted`), its unknowns its own. Not read
    where the quotation is not."""
    if not any(p.text == QUOTED for p in utterance.pieces):
        return utterance
    taken = [meant(u.readings, view) if u.understood else None for u in quoted]
    if not utterance.readings or not taken or any(t is None for t in taken):
        return Utterance(utterance.pieces, ())
    readings = []
    # The words around a quotation, each reading of them with its words' senses made (`unpacked`): what was said is
    # put into each.
    for reading in unpacked(utterance.readings, view):
        facts = list(reading.meaning.facts)
        for at, said in enumerate(taken):
            own = {t: f"?q{at}_{t[1:]}" for f in said.meaning.facts for t in f.terms()
                   if is_variable(t) and not _named(t)}
            facts.extend(MeaningFact(f.relation, own.get(f.subject, f.subject), own.get(f.obj, f.obj), f.positive,
                                     f.condition, f.alternative, True, f.given) for f in said.meaning.facts)
        try:
            meaning = Meaning(reading.meaning.act, tuple(facts), reading.meaning.asked)
        except ValueError:
            continue
        parts = (reading,) + tuple(taken)
        readings.append(Reading(
            tuple(c for r in parts for c in r.constructions), tuple(x for r in parts for x in r.links), meaning,
            sum(r.score for r in parts) / len(parts), sum(r.uses for r in parts) / len(parts),
            proposed=tuple(x for r in parts for x in r.proposed), new=tuple(x for r in parts for x in r.new),
            loose=any(r.loose for r in parts), misfits=sum(r.misfits for r in parts),
            said_for=sum(r.said_for for r in parts), apart=sum(r.apart for r in parts)))
    return Utterance(utterance.pieces, tuple(readings))


#: How many stretches between held ends one utterance may span. An end a construction ends on can also stand inside
#: an utterance ("Dr. Smith is here."), so a reading may run past it; this bounds how far.
_ENDS_SPANNED = 3


#: Whether an utterance no taught frame reads is read by English's grammar (`grammar.GrammarView`: each word's category
#: and meaning, combined by general rules, what words hold learned from the sentences memory holds with their taught
#: meanings; `MemoryAgent.grammar_view`). Read by the composer before (`composition.CompositionView`), which decided
#: from the taught sentences most like it and, where none was, from coarser situations wrong 9% to 75% of the time;
#: the grammar reads more of the PMB's held-out English right (GRAMMAR-01, 2026-10-21). On since UNDERSTANDS-PROSE-01
#: on main showed reading so right more often than it misleads, with `COMPOSING_FORCED` (2026-10-18).
#: `LYRIC_COMPOSE=0` turns it off; an experiment may set it.
COMPOSING = os.environ.get("LYRIC_COMPOSE", "1") != "0"

#: HOW MANY MEANINGS THE GRAMMAR IS ASKED FOR of an utterance no taught frame read (`_read_by_composing`), for the
#: listener to take one as meant (`meant`). One, and the listener is handed the reader's own choice and weighs
#: nothing. `LYRIC_COMPOSED_READINGS` sets it; an experiment may.
#:
#: ONE, UNTIL A CHOOSER IS MEASURED. Asking for more costs the chart `how_many` squared in the combinations it tries,
#: and buys only what a chooser can make of it: over the PMB's held-out dev part the reader's own choice is right for
#: 52.7% of 150 sentences AT EVERY WIDTH FROM SIX TO FIFTY, flat, while the right reading being among those handed up
#: climbs 54.7%, 55.3%, 57.3%, 58.7% at six, twelve, twenty-five and fifty, for 0.15, 0.36, 1.06 and 2.11 s a
#: sentence (`experiments/GRAMMAR-01/diagnostics/nbest.py`, 2026-11-03). Two thirds of the way to the 61.8% the
#: exhaustive chart holds, so **6.0 points wait on the choosing**, and they arrive within reach: of the nine readings
#: fifty makes newly available, seven rank first. What `meant` would take of them is untested here, because it weighs
#: what memory knows of what each reading says and a files-only reading has no memory.
#:
#: THREE, MEASURED THROUGH THE REAL DOOR WITH MEMORY UP (2026-11-08). Both halves of the reason for one have since
#: changed: the gate that threw the whole chart away when every frame reading was forced is gone, so the listener now
#: weighs the grammar's readings beside the frames' own; and asked of main rather than of files, the FIRST reading
#: handed up is not the same at one as at three. "The note, the rock and the dog were heavy." came back at one as
#: `done_to(?v0, ?v1) & instance_of(?v0, and)`, the joining word made a concept, and at three as the group it is:
#: `has_member(?v1, ?v0) & has_member(?v1, ?v2) & has_member(?v1, ?v3) & state_of(heavy, ?v1)`. The experiment above
#: could not see this, having measured from six upward, where the reader's own choice is flat.
#:
#: THREE AND NOT MORE: at three, five and ten the best reading is the same for three coordinated things, three
#: clauses and three doings, while the reading costs 2.78 s, 4.94 s, 7.16 s and 12.85 s over eight sentences at one,
#: three, five and ten. So three is the least that hands up the right reading, and the 6.0 points the exhaustive
#: chart holds still wait on measuring what `meant` makes of a wider set -- which is now something that can be
#: measured, memory being reachable where it was not.
COMPOSED_READINGS = int(os.environ.get("LYRIC_COMPOSED_READINGS", "1"))

#: HOW MANY THE GRAMMAR IS ASKED FOR OF WHAT A PERSON SAID (`AutonomousCoordinator._read`, through
#: `composing_width`), which is not how many anything else is asked for.
#:
#: WHY THE WIDTH BELONGS AT THIS DOOR AND NOT AT THE DEFAULT. Composing is also how a start reads its 139 tool
#: descriptions (`_tools_by_doing`), and those are not somebody speaking: they are fixed English indexed once, the
#: first sentence of each description read as an order so a tool can be chosen from plain words. A wide chart buys
#: nothing there and costs `how_many` squared on 139 long sentences -- at six, a start that takes 29 s had not
#: finished reading its tools in 20 minutes (2026-11-03). So the default stays at one, and the width is asked for
#: where a person is being read.
#:
#: THREE, measured through the real door with memory up: the FIRST reading handed up is not the same at one as at
#: three ("The note, the rock and the dog were heavy." came back at one as `done_to(?v0, ?v1) &
#: instance_of(?v0, and)`, the joining word made a concept, and at three as the group it is), while at three, five
#: and ten the best reading is the same for three coordinated things, three clauses and three doings. Reading costs
#: 2.78 s, 4.94 s, 7.16 s and 12.85 s over eight sentences at one, three, five and ten (2026-11-08).
SPOKEN_READINGS = int(os.environ.get("LYRIC_SPOKEN_READINGS", "3"))

#: HOW MANY THE GRAMMAR IS ASKED FOR AGAIN, where what it read first MAKES A CONCEPT OF A WORD ENGLISH BUILDS
#: SENTENCES WITH (`_names_a_structure_word`). `LYRIC_COMPOSED_AGAIN` sets it; 0 asks again never.
#:
#: `how_many` is TWO things at once and only one of them is dear. It is how many readings reach the listener, which
#: costs a meaning each; and it is how many signs of a category the chart keeps, which costs `how_many` SQUARED in
#: the combinations tried (`Grammar.charts`). The second is why one was the default -- and the second is also what
#: decides whether the right reading is BUILT AT ALL, so no ranking could recover it: at one, "The note, the rock
#: and the dog were heavy." was read `done_to(?v0, ?v1) & instance_of(?v0, and)`, and the group it is
#: (`has_member` of all three) was pruned mid-chart and never ranked.
#:
#: SO IT IS PAID FOR ONLY WHERE A READING SHOWS IT IS WRONG. A conjunction, a determiner or a preposition standing
#: where a thing goes is no judgement call: English builds sentences with those words and never names things by
#: them, so such a reading has mis-parsed, and asking again with a wider chart is worth its cost. Where the cheap
#: reading names no such word, nothing more is asked and nothing more is paid. A sentence the grammar reads no
#: whole of is NOT asked again either: a wider chart may find a whole, but every long sentence nothing reads would
#: then pay the squared cost, which is the whole of what made three dear (2026-11-08).
#: ABOVE EVERY WIDTH IT RESCUES, OR IT RESCUES NOTHING: the guard is `COMPOSED_AGAIN > width`, so three stopped
#: rescuing anything the moment a person's words began to be read at three (`SPOKEN_READINGS`, 2026-11-09) -- and
#: a person's words are where a mis-parse matters most. Five is the next width measured. That five finds a whole
#: three prunes is NOT measured; what is measured is that three finds what one prunes, and the argument carries up.
#: It is paid only where every reading names a structure word and has therefore provably mis-parsed, which is rare.
COMPOSED_AGAIN = int(os.environ.get("LYRIC_COMPOSED_AGAIN", "5"))

#: HOW MANY THE GRAMMAR IS ASKED FOR INSIDE ONE PIECE OF WORK (`composing_width`), where the work needs THE READINGS
#: AN UTTERANCE HAS and not the one reading the reader would take of it. Unset, `COMPOSED_READINGS` stands, so no
#: other path pays anything for this.
#:
#: WHY IT IS SCOPED AND NOT RAISED. `how_many` costs the chart `how_many` SQUARED in the combinations it tries, and
#: composing is also the path a start reads its 139 tool descriptions by (`ready_to_read` -> `_tools_by_doing` ->
#: `read_text`): at six, a start that takes 29 s had not finished reading its tools in 20 minutes (2026-11-03). The
#: cost belongs to the one pass that needs the width, not to every utterance Lyric ever reads.
_COMPOSED_WIDTH: "contextvars.ContextVar[int]" = contextvars.ContextVar("composed_width", default=0)


@contextlib.contextmanager
def composing_width(how_many: int):
    """The grammar is asked for `how_many` readings of what is read inside this, instead of `COMPOSED_READINGS`
    (`_read_by_composing`). For work that must see what an utterance can mean, where reading everything else that
    wide would cost the squared chart for nothing."""
    token = _COMPOSED_WIDTH.set(int(how_many))
    try:
        yield
    finally:
        _COMPOSED_WIDTH.reset(token)


def _names_a_structure_word(meaning: "Meaning", closed: Any) -> bool:
    """Whether a reading makes a CONCEPT of a word English builds sentences with -- a conjunction, a determiner, a
    preposition, a form of "be" -- which is a mis-parse on its face: those words say how what is said goes together
    and never name a thing. `closed` is what the grammar holds of them (`Lexicon.closed`)."""
    if not closed:
        return False
    for fact in meaning.facts:
        for term in (fact.subject, fact.obj):
            if isinstance(term, str) and term and not is_variable(term) and _fold(term) in closed:
                return True
    return False


def _read_by_composing(utterance: "Utterance", named_before: Sequence[str] = (), width: int = 0) -> "Utterance":
    """An utterance no taught frame read, read by English's grammar (`COMPOSING`): EVERY MEANING THE GRAMMAR READS IT
    TO (`COMPOSED_READINGS`), for the listener to take one as meant (`meant`); unread where memory is not up in this
    process, the grammar reads no whole, or the meaning language cannot say any reading of it.

    HANDED THE GRAMMAR'S ONE CHOICE, THE LISTENER HAD NOTHING TO CHOOSE. A taught frame reading an utterance several
    ways hands all of them up and the listener weighs them by what memory knows of what each says; the grammar handed
    up the reading its own score over words put first, and `meant` returned it without weighing anything (one reading
    is returned before any evidence is counted). Over the PMB's held-out dev part the grammar's own choice was right
    for 54.2% of sentences where a chart keeping every reading held the right one for 61.8% (GRAMMAR-01,
    2026-11-03): what the listener was never shown."""
    from core.agents import memory_agent as _memory
    agent = _memory._memory_agent
    if agent is None or not any(not _is_mark(p.text) for p in utterance.pieces):
        logger.debug("composing: %r left unread (%s)", utterance.text,
                     "memory is not up in this process" if agent is None else "no word to read")
        return utterance
    from core.semantics.composition import ASKING
    first = next((_fold(p.text) for p in utterance.pieces if not _is_mark(p.text)), "")
    made: List[Reading] = []
    offered, refused = 0, Counter()
    width = width or _COMPOSED_WIDTH.get() or COMPOSED_READINGS
    for read in agent.grammar_view().readings(surface_of(utterance.pieces), width, named_before):
        offered += 1
        meaning = read.meaning
        if meaning is None:
            refused[read.why or "the meaning language cannot say what it read"] += 1
            continue
        if all(f.given for f in meaning.facts):
            # A meaning of known things alone says nothing of them: told, nothing is told; asked, nothing is asked.
            refused["says only what is known already"] += 1
            continue
        if meaning.act == "ask" and not meaning.asked and first in ASKING:
            # A QUESTION THAT ASKS FOR SOMETHING, COMPOSED ASKING FOR NOTHING, IS NOT ITS READING: "How many engineers
            # did the company hire?" composed without the count or the engineers asked whether the company hired, and
            # was answered "Yes." once the hiring was held (2026-10-19).
            refused["a question that asks for nothing"] += 1
            continue
        made.append(Reading(_said_by_words(read), (), meaning, composed=True,
                            structure=math.log(read.ranked) if read.ranked > 0 else 0.0))
    # WHY AN UTTERANCE CAME BACK UNREAD, SAID. Each refusal above returned the utterance unchanged and silently, so a
    # sentence the grammar read whole at sureness 1.00 and then could not say was indistinguishable from one no
    # grammar rule reached: seven of the taught set read as nothing for one such refusal, and finding which took a
    # day of bisecting readings by hand (2026-11-03, the possessive's open owner).
    closed = getattr(getattr(agent.grammar_view(), "grammar", None), "lexicon", None)
    closed = getattr(closed, "closed", None)
    if made and COMPOSED_AGAIN > width and all(_names_a_structure_word(r.meaning, closed) for r in made):
        # EVERY READING IT GAVE MAKES A CONCEPT OF A STRUCTURE WORD, so the chart pruned the reading that does not.
        logger.info("composing: %r read %d way%s, every one naming a structure word -- asking again for %d",
                    utterance.text, offered, "" if offered == 1 else "s", COMPOSED_AGAIN)
        again = _read_by_composing(utterance, named_before, COMPOSED_AGAIN)
        if again.readings:
            return again
    if not made:
        logger.info("composing: %r read %d way%s, none said anything: %s", utterance.text, offered,
                    "" if offered == 1 else "s",
                    "; ".join(f"{n} × {r}" for r, n in refused.most_common())
                    or "the grammar read no whole of it")
        return utterance
    logger.debug("composing: %r read %d way%s, %d said something%s", utterance.text, offered,
                 "" if offered == 1 else "s", len(made),
                 "; " + "; ".join(f"{n} × {r}" for r, n in refused.most_common()) if refused else "")
    return Utterance(utterance.pieces, tuple(made), utterance.partial, utterance.unknown)


def _said_by_words(read: Any) -> Tuple["Lexical", ...]:
    """WHAT EACH WORD OF A READING BY ENGLISH'S GRAMMAR NAMED: a thing, a doing, a quality, a name, a number, each
    as the construction saying it (`Lexical`: the words, what they name), as a taught frame's reading holds its
    fillers. Holding none, the conversation knew no word the speaker called anything by: told "Roy fastened the medal
    with a pin." and asked what Roy fastened, it said the thing's own name, "Award decoration." (TRAIN-FORMAT-01,
    lyric_dev2, 2026-10-26), and which words were names (`Conversation._told`)."""
    sign = getattr(read, "sign", None)
    if sign is None:
        return ()
    out: Dict[Tuple[Tuple[str, ...], str], Lexical] = {}
    for p in sign.pieces:
        if p[0] != "word" or p[2] not in ("NOUN", "NAME", "VERB", "ADJECTIVE", "ADVERB", "NUMERAL") or not p[1]:
            continue
        words = tuple(str(w) for w in read.words[p[3]:p[4]])
        if not words or (words, str(p[1])) in out:
            continue
        try:
            out[(words, str(p[1]))] = Lexical(tuple((w, True) for w in words), str(p[1]))
        except ValueError:
            continue
    return tuple(out.values())


#: Whether an utterance the frames read only by supposing more than any lesson read as taught ever supposed is ALSO
#: read by English's grammar (`_read_forced_by_composing`), with `COMPOSING`. On since UNDERSTANDS-PROSE-01 on main
#: (2026-10-18): with it, "Do whales breathe air?" and "Does sorted return a new list?" answered, none wrongly.
#: ALSO, not INSTEAD: the grammar's reading is put beside the frames' and the listener weighs them (2026-11-08).
#: `LYRIC_COMPOSE_FORCED=0` turns it off.
COMPOSING_FORCED = os.environ.get("LYRIC_COMPOSE_FORCED", "1") != "0"
#: How many links never taught a reading of a lesson sentence read as taught proposes, at most: of the 3,054 lesson
#: sentences, 3,037 were read as taught on a copy of main (2026-10-18), 2,895 supposing nothing, 132 one link, 10 two;
#: none read loosely, with a word taken as a new name, a filler written against its slot or one never seen beside the
#: slot's own.
TAUGHT_PROPOSES = 2


def _forced(reading: Reading) -> bool:
    """Whether a reading supposes more than any lesson sentence read as taught supposed (`TAUGHT_PROPOSES`)."""
    loose, new, proposed, misfits, apart = reading.supposed
    return bool(loose or new or misfits or apart or proposed > TAUGHT_PROPOSES)


def _read_forced_by_composing(utterance: "Utterance") -> "Utterance":
    """An utterance every frame reads only by supposing more than the lessons ever did, read by English's grammar
    AS WELL (`COMPOSING_FORCED`): the grammar's readings are put beside the frames' own and the listener weighs
    them all. As it was where a frame reads it as taught reads, or the grammar gives it no meaning.

    "A whale breathes air through a blowhole." fits no taught frame: its 36 readings each propose six links never
    taught and write fillers against their slots ("air through" one new name, the breathing done by the ocean told
    before), and the listener took one. The composer reads it as said, the whale breathing air through a blowhole,
    and "Do whales breathe air?" is answered (UNDERSTANDS-PROSE-01 on a copy of main, 2026-10-18). A question too, as
    the grammar reads it: the composer read questions worse and they stayed the frames'; the grammar reads them by the
    words that ask and where they stand ("When was the Eiffel Tower built?" a building asked when, GRAMMAR-01).

    BESIDE, NOT INSTEAD. This THREW THE FRAMES' READINGS AWAY, every one of them, and handed the listener the
    grammar's alone -- and the grammar is asked for one reading (`COMPOSED_READINGS`), so the listener received one
    meaning and weighed nothing. ONE WORD NOTHING HOLDS WAS ENOUGH TO DO IT: a word no filler holds stands as a new
    name, which is more than any lesson supposed (`_forced`), so every reading of the sentence it stands in supposes
    that much and `all` is true of them. "The note was long." was read by the frames to a packed reading holding
    all three things memory holds for "note" -- a comment, a musical notation, a debt instrument -- and the three
    were thrown away over "long", which that store holds the class of and holds a concept named but holds no filler
    for; the listener was handed one grammar reading and said "the only meaning the words have". "The rock was
    heavy." kept its four readings and chose among them, moving 7.123 -> 9.460 nats as the conversation turned from
    a band to a cliff, for one reason: "heavy" is held, so its least reading supposed nothing new and `all` was
    false. Of 21,195 adjectives whose class that store holds, 4,757 are held as a word that can stand anywhere, and
    212 of 4,393 adverbs (lyric_db, 2026-11-08), so the words that fire this are ordinary ones.

    Weighed instead of thrown away, HOW MUCH A READING SUPPOSED PAST ITS WORDS IS ALREADY EVIDENCE the listener
    counts, at the worth it measured for it on what it was taught (`fit`, `listening_worths`, `Reading.supposed`),
    and a composed reading proposes no link and takes no word as new, so it is weighed as supposing nothing. The
    reader's business is to report every meaning the words can have; which one was meant is the listener's
    (`meant`). A gate here decided it by the structure alone, before any evidence was counted."""
    if not utterance.readings or not all(not r.composed and _forced(r) for r in utterance.readings):
        return utterance
    composed = _read_by_composing(Utterance(utterance.pieces, (), utterance.partial, utterance.unknown))
    if not composed.readings:
        return utterance
    # Best first, as every reading an utterance carries is (`_best_first`): the composed ones suppose nothing, so
    # they stand first, and where the listener weighs one of them alike with a frame's it is theirs that stands.
    return Utterance(utterance.pieces, tuple(sorted(composed.readings + utterance.readings, key=_best_first)),
                     utterance.partial, utterance.unknown)


def _one_sentence(pieces: Tuple[Piece, ...]) -> bool:
    """Whether these pieces are one sentence: nothing closes a sentence before their last piece. A text of several
    is read as the utterances that cover it, one for each, and is not handed to the grammar whole."""
    return not any(p.text in (".", "?", "!") for p in pieces[:-1])


def read_text(text: str, inventory: Optional[PatternInventory] = None, *,
              parts: bool = False, named_before: Sequence[str] = ()) -> Tuple[Utterance, ...]:
    """A text as the consecutive utterances that cover it, each read on its own.

    An utterance can end wherever a held construction ends: that is all the substrate knows of where one ends, and
    it knows it from what it was taught. Of the ways to cut the text there, the one that reads the most of it is
    taken; a stretch nothing reads whole is kept as an utterance with no readings, so nothing said is lost. A mark
    inside it separates what it separates: where every stretch between its marks reads as a sentence, each is an
    utterance of its own ("My dog is not a cat, he is a dog.").

    With `parts`, an utterance nothing reads whole is also read in parts (`Utterance.partial`, `Utterance.unknown`):
    every stretch of it is tried, so it is asked for only where the parts are used -- saying what was understood."""
    view = inventory if inventory is not None else _live_inventory()
    pieces = form_of(text)
    if not pieces:
        return ()
    # A QUOTATION IS A SENTENCE OF ITS OWN, read apart; what it says is what was said (`_with_quotation`).
    pieces, quoted = set_apart(pieces)
    quoted_read = read_text(surface_of(quoted), view, parts=parts, named_before=named_before) if quoted else ()
    ends = view.ends()
    cuts = [0] + [i + 1 for i, p in enumerate(pieces[:-1]) if _fold(p.text) in ends] + [len(pieces)]
    read_at: Dict[Tuple[int, int], Tuple[Reading, ...]] = {}
    charts: Dict[bool, _Chart] = {}

    def readings(a: int, b: int) -> Tuple[Reading, ...]:
        if (a, b) not in read_at:
            read_at[(a, b)] = _read_pieces(pieces[a:b], view, charts)
        return read_at[(a, b)]

    # A SENTENCE THE GRAMMAR READS WHOLE IS ONE UTTERANCE, AND IS ASKED FOR BEFORE IT IS CUT UP.
    #
    # The spans below are chosen by what TAUGHT FRAMES read -- `_read_pieces` returns nothing where no frame reads a
    # stretch -- and English's grammar is asked only afterwards (`COMPOSING`, below), of whatever fragments that
    # choice left. So a sentence no frame covers whole was cut at the ends frames happen to know, and the grammar,
    # which reads it, was never offered it: "The note was long, the rock was heavy and the dog barked." came back as
    # three utterances ('The note was long ,' | 'the rock' | 'was heavy and the dog barked .') whose last reading was
    # `instance_of(?v0, and)` and `isa(barked, dog)`, while the grammar reads the whole of it to all three clauses at
    # sureness 0.128. Three coordinated things and three names went the same way; two of anything read whole, because
    # a frame happened to cover two (lyric_db, 2026-11-08).
    #
    # ASKED ONCE, OF THE WHOLE, and only where this text is ONE sentence and no frame read it whole: a text of
    # several sentences is still read as the utterances that cover it, which is what every caller is given, and the
    # frames' own reading stands wherever there is one. The cost is one composing, in the case that had none.
    if COMPOSING and _one_sentence(pieces) and not readings(0, len(pieces)):
        whole = _read_by_composing(Utterance(pieces, ()), tuple(named_before))
        if COMPOSING_FORCED and whole.readings:
            whole = _read_forced_by_composing(whole)
        if whole.readings:
            return (_with_quotation(whole, quoted_read, view),) if quoted else (whole,)
    # best[k] covers pieces[:cuts[k]]: (pieces read, utterances read, utterances unread, where the last one began).
    # The most pieces read wins; then the fewest utterances reading them, so a reading that runs past an end beats
    # two that stop at it; then the most unread ones, so what nothing reads is still told apart at its ends.
    best: List[Tuple[int, int, int, int]] = [(0, 0, 0, -1)]
    for k in range(1, len(cuts)):
        options = []
        for m in range(max(0, k - _ENDS_SPANNED), k):
            covered, told, untold, _ = best[m]
            if readings(cuts[m], cuts[k]):
                options.append((covered + cuts[k] - cuts[m], -(told + 1), untold, m))
            else:
                options.append((covered, -told, untold + 1, m))
        covered, told, untold, m = max(options)
        best.append((covered, -told, untold, m))
    spans: List[Tuple[int, int]] = []
    k = len(cuts) - 1
    while k > 0:
        m = best[k][3]
        spans.append((cuts[m], cuts[k]))
        k = m
    out = []
    for a, b in reversed(spans):
        found = readings(a, b)
        if found:
            out.append(Utterance(pieces[a:b], found))
            continue
        said = pieces[a:b]
        separated = _separated(said, view, charts)
        if separated:
            out.extend(separated)
            continue
        partial, unknown = _partial(said, view, charts) if parts else ((), ())
        out.append(Utterance(said, (), partial, unknown))
    if COMPOSING:
        # WHAT THE TEXT HAS ALREADY NAMED IS WHAT THE REST OF IT MEANS ITS WORDS BY. The utterances a held
        # construction read are read before any of the rest is composed, so their things are known by the time the
        # rest is read, and a sense is weighed by the kinds it shares with the things around it (`spell_out`'s
        # `around`, Resnik 1995). Offered only the one sentence's own things, a short sentence offered nothing and
        # the sense its word names most often was taken whatever the text had just said.
        named = tuple(dict.fromkeys(
            str(f.obj) for u in out for r in u.readings if r.meaning is not None
            for f in r.meaning.facts if f.relation in ("instance_of", "isa") and isinstance(f.obj, str)))
        out = [u if u.readings else _read_by_composing(u, named + tuple(named_before)) for u in out]
        if COMPOSING_FORCED:
            out = [_read_forced_by_composing(u) for u in out]
    return tuple(_with_quotation(u, quoted_read, view) for u in out) if quoted else tuple(out)


def _separated(said: Tuple[Piece, ...], view: PatternInventory,
               charts: Optional[Dict[bool, _Chart]] = None) -> Tuple[Utterance, ...]:
    """An utterance that does not read whole, as the sentences its inner marks separate, when every stretch between
    them reads as one: each keeps the marks that follow it. Nothing otherwise."""
    inner = [k for k, piece in enumerate(said[:-1]) if k > 0 and _is_mark(piece.text)]
    if not inner:
        return ()
    out: List[Utterance] = []
    start = 0
    for end in inner + [len(said)]:
        if end <= start:
            continue          # a mark already taken as the one before it's own
        stretch = said[start:end]
        found = _read_pieces(stretch, view, charts) if any(not _is_mark(p.text) for p in stretch) else ()
        if not found:
            return ()
        # The marks that follow a sentence are its own; the next one begins at its first word.
        stop = end
        while stop < len(said) and _is_mark(said[stop].text):
            stop += 1
        out.append(Utterance(said[start:stop], found))
        start = stop
        if start >= len(said):
            break
    return tuple(out) if len(out) > 1 else ()


def place_spoken_of(meaning: Optional[Meaning]) -> Optional[str]:
    """The place a meaning last names outright, where a thing is or an event goes ("The dog ran to the house.":
    `house`): what a later "there" points back to. None when it names none, or only an unknown or the situation's."""
    if meaning is None:
        return None
    places = [f.obj for f in meaning.asserted if f.relation in PLACE_KINDS and f.positive
              and not is_variable(f.obj)]
    return places[-1] if places else None


def spoken_of(facts: Iterable[MeaningFact], besides: Collection[str] = ()) -> Tuple[Tuple[str, Optional[bool]], ...]:
    """What a later "it", "she" or "they" can point back to, of what was said with its things named: each thing it
    speaks of, the one it is about first, and whether it is many (True), one (False), or either (None).

    WHAT IT IS ABOUT, FIRST: what its doings were done by, or done to where nothing is said to do them ("The Eiffel
    Tower was built in 1889."); then what else it says is so ("Paris is the capital of France."); then what its
    doings were done to, and the rest, as its facts name them. A doing is none of them, nor a number, nor what is
    `besides` (the speaker, the one spoken to, the moment), nor what a thing is, is like, or how many it is. Taken as
    the first thing a meaning names, it was as often a doing's kind: "They release oxygen." after "Plants take in
    carbon dioxide and water." was done by taking in, and "Two of them work in Berlin." after "The company hired three
    engineers in May." by the company (UNDERSTANDS-PROSE-01 on main, 2026-10-21).

    MANY, a group (`has_member`) or a thing counted more than one; ONE, a thing of a kind (`instance_of`) counted no
    more; EITHER, a thing named or a kind, which "it" and "they" both point back to ("Whales are mammals. They live
    in the ocean.")."""
    facts = [f for f in facts if f.positive and not f.unasserted]
    doings = {f.subject for f in facts if f.relation in EVENT_PARTICIPANTS}
    done_in = {f.obj for f in facts if f.subject in doings}
    first: List[str] = []
    for doing in dict.fromkeys(f.subject for f in facts if f.subject in doings and f.subject not in done_in):
        by = [f.obj for f in facts if f.subject == doing and f.relation == "done_by"]
        first += by or [f.obj for f in facts if f.subject == doing and f.relation == "done_to"]
    first += [f.subject for f in facts if f.subject not in doings and f.relation != "instance_of"]
    # What a thing is, what it is like and how many it is are not things spoken of.
    every = first + [t for f in facts for t in (f.subject, f.obj)
                     if t == f.subject or f.relation not in ("instance_of", "has_property", "has_count")]

    def many(thing: str) -> Optional[bool]:
        if any(f.relation == "has_member" and f.subject == thing for f in facts):
            return True
        counted = [f.obj for f in facts if f.relation == "has_count" and f.subject == thing]
        if counted:
            return int(counted[0]) > 1 if counted[0].isdigit() else None
        return False if any(f.relation == "instance_of" and f.subject == thing for f in facts) else None
    return tuple((thing, many(thing)) for thing in dict.fromkeys(every)
                 if not is_variable(thing) and thing not in doings and thing not in besides
                 and any(ch.isalpha() for ch in thing))


def held_key(fact: MeaningFact) -> Tuple[str, str, str, bool]:
    """A fact between named things as the listener asks memory about it: whether memory holds it."""
    return (fact.relation, fact.subject, fact.obj, fact.positive)


def listening_facts(meaning: Meaning) -> Tuple[MeaningFact, ...]:
    """What a meaning says between named things, as a listener weighs it against what it knows. An event stands
    for its kind: "I ate fish." is an eating done to fish, weighed as `done_to(eat, fish)`; "Tom has a red ball."
    a ball that is red, `has_property(ball, red)`. What still names an unknown or the situation is not weighed.

    A RULE OVER WHAT IS OF ONE KIND SAYS WHAT THAT KIND IS. "To heighten is to increase." (whatever heightening is
    done is an increasing) is weighed as `isa(heighten, increase)`: the event stands for the kind it is supposed to
    be, and what it then is, that kind is. Weighed as nothing, every sense of "increase" was as known as another, and
    the one met most was taken over the one memory holds heightening a kind of (36 of 437 of WordNet's verbs said so,
    2026-10-12)."""
    kinds = {f.subject: f.obj for f in meaning.facts
             if f.relation == "instance_of" and f.positive and is_variable(f.subject) and not is_variable(f.obj)}
    supposed = {f.subject: f.obj for f in meaning.facts
                if f.relation == "instance_of" and f.positive and f.condition and is_variable(f.subject)
                and not is_variable(f.obj)}
    kinds.update(supposed)
    out: List[MeaningFact] = []
    for fact in meaning.facts:
        if fact.relation == "instance_of" and fact.subject in kinds:
            kind = supposed.get(fact.subject)
            if kind is not None and not fact.condition and not is_variable(fact.obj) and fact.obj != kind:
                out.append(MeaningFact("isa", kind, fact.obj, fact.positive))
            continue
        subject, obj = kinds.get(fact.subject, fact.subject), kinds.get(fact.obj, fact.obj)
        if is_variable(subject) or is_variable(obj) or subject == obj:
            continue
        out.append(MeaningFact(fact.relation, subject, obj, fact.positive))
    return tuple(dict.fromkeys(out))


def _worded(reading: Reading, view: PatternInventory) -> str:
    """A reading's meaning with each concept a word named put back as that word: what was said, whichever thing
    each word was taken to name. Two readings that differ only in which thing a word names ("fish", the animal or
    the food) are the same here.

    A WORD A FRAME WRITES ITSELF NAMES ITS THING TOO. "?slot0 , ?slot1 , ?slot2 and cows are ?slot3 ." writes "cows"
    and states a cow; held, "cows" names cow, so the cow is put back as "cows", as the cattle the word "cows" names
    through the general frame is. Put back only for word constructions, the two were two statements, and the
    listener, offered both, chose neither (2026-10-11, once a construction that lost a competition kept reading). A
    thing no word the frame writes is held to name stays as it is: "A robin is a bird." taught to mean an animal
    writes no word for the animal, and is another statement; a number built from numbers is no word's.

    WRITTEN, NOT MADE A MEANING. Put back as its words, a reading can say what no meaning states: two facts of two
    things one word names are one fact twice, and a thing named apart from a date ("day november 5") is the date
    again. Made a Meaning, either was refused, and the refusal ended a teaching pass: reading what WordNet's words
    are said of, as each was stored, at the end of its patterns (2026-10-08). It is only how the reading is written,
    each fact once."""
    names = {c.value: " ".join(_loose(c.words)) for c in reading.constructions if isinstance(c, Lexical)}
    for construction in reading.constructions:
        if isinstance(construction, Lexical):
            continue
        # The words the frame writes, each stretch between its slots apart: a word is never two stretches joined.
        runs: List[Tuple[str, ...]] = []
        run: List[str] = []
        for element in construction.form:
            if isinstance(element, Slot):
                runs.append(_loose(run))
                run = []
            else:
                run.append(element.text)
        runs.append(_loose(run))
        facts = construction.meaning.facts if isinstance(construction, Pattern) else construction.facts
        # A PHRASE NAMES ITS KIND WITH ITS OWN WORDS, as a word does: "saw", held as a seeing before now, writes `see`,
        # and "compiled them" `compile`. Held for each of a verb's senses, its readings were each a statement of their
        # own, never a choice among senses, and the listener chose none: "Tom saw her." and 15 other taught sentences
        # (2026-10-13).
        if isinstance(construction, Phrase):
            own = [e.text for e in construction.form if isinstance(e, Piece) and not _is_mark(e.text)]
            for fact in facts:
                if own and fact.relation == "instance_of" and fact.subject == construction.anchor and fact.positive \
                        and not is_variable(fact.obj):
                    names.setdefault(fact.obj, " ".join(_loose(tuple(own))))
        for thing in {t for f in facts for t in f.terms() if not is_variable(t)} - names.keys():
            for lexical in view.lexicals_with_value(thing):
                words = _loose(lexical.words)
                if any(run[k:k + len(words)] == words for run in runs for k in range(len(run) - len(words) + 1)):
                    names[thing] = " ".join(words)
                    break
    meaning = reading.meaning
    facts = tuple(dict.fromkeys(f.renamed(names) for f in meaning.facts))
    return _canonical_of(meaning.act, facts, meaning.asked)


def sense_choices(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None) -> Tuple[Reading, ...]:
    """The readings a listener chooses among by which thing a word names: the best reading of each meaning, when
    the utterance read to more than one and they all say the same words of the same things but for that. Empty
    when it read to one meaning, or when its meanings differ otherwise (what is said of what), which is the
    listener's to ask about."""
    view = inventory if inventory is not None else _live_inventory()
    if any(reading.senses for reading in readings):
        # Of packed readings, the meanings the listener weighs alike, the choice left to the one who said it.
        readings = _best_packed(readings, view, Heard())
    best: Dict[str, Reading] = {}
    for reading in readings:
        best.setdefault(reading.meaning.canonical(), reading)
    if len(best) < 2:
        return ()
    if len({_worded(r, view) for r in best.values()}) != 1:
        return ()
    return tuple(best.values())


def _senses(choices: Sequence[Reading]) -> Tuple[Dict[str, FrozenSet[str]], FrozenSet[str]]:
    """For readings that differ only in which thing a word names: the things each takes the words to name that the
    others do not (its senses), and the things they all name (the rest of what was said)."""
    named = {r.meaning.canonical(): frozenset(t for f in listening_facts(r.meaning) for t in f.terms())
             for r in choices}
    shared = frozenset.intersection(*named.values()) if named else frozenset()
    return {key: terms - shared for key, terms in named.items()}, shared


class Heard(NamedTuple):
    """What memory was found to hold about the ways an utterance can be taken (`listening`): how firmly it holds
    each fact each way says (`held`), how much what each thing a way takes a word to name is connected to in the
    rest of what was said and what was talked of before raises it (`related`, in nats), how much more likely each
    thing is given what the fact's other word is said of (`selected`, in nats), which things are one coarse
    sense (`together`), and for each fact whether one thing's definition is written with the other (`defined`: 2)
    or with what the other is a kind of (1). Empty when nothing was asked."""
    held: Mapping[Tuple[str, str, str, bool], int] = {}
    related: Mapping[str, float] = {}
    selected: Mapping[Tuple[str, str, str, bool], float] = {}
    together: FrozenSet[FrozenSet[str]] = frozenset()
    defined: Mapping[Tuple[str, str, str, bool], int] = {}


def _met(view: PatternInventory, construction: Construction) -> int:
    """How often a construction's words have been met naming its thing, as the listener weighs a sense: its own uses,
    and for one word the uses of that word in its other shapes naming the same thing. "places" names place as
    "place" does, written in a shape (`written_in_shape`), and was met naming it as often: taught once a sense as a
    plural, every sense of "places" stood at one use, and "Cities are places." could not be told from a city being a
    cognition place (46 uses of "place" naming place, 27 naming that, 2026-10-11). Case aside, a word is itself.

    A phrase naming a thing of its own in a word's form ("had them", a having before now) was met as often as that
    word names that thing in real use: the count lands on it as on the word (`learn_usage`)."""
    uses = view.uses(construction)
    if not isinstance(construction, Lexical) or len(construction.words) != 1:
        return uses
    word = _fold(construction.words[0])
    for other in view.lexicals_with_value(construction.value):
        if other.key == construction.key or len(other.words) != 1:
            continue
        there = _fold(other.words[0])
        if there == word or view.written_in_shape(word, there) or view.written_in_shape(there, word):
            uses += view.uses(other)
    return uses


def _derivation(reading: Reading, view: PatternInventory) -> float:
    """How probable a reading's structure is, as its parts were met (ln): for every slot of every frame and phrase it
    reads through, the chance of its filler there, interpolated Witten-Bell (Witten and Bell 1991): `(k + T P(f)) /
    (n + T)`, `k` the uses of the held link putting this filler there (0 where the link is only proposed), `n` the
    uses of the slot's held links all told, `T` how many fillers they put there, and `P(f)` how often the filler was
    met among everything met in the slot's part (`parts_met`). A slot that has taken many fillers gives a new one its
    share; one that took few, little.

    The frame itself is not weighed by how often it was met: that is how often a source said its facts so ("?slot0
    is ?slot1.", 13,234 of WordNet's kinds), not how English says them, and weighed it took "Faith is central." for a
    kind of telephone exchange. Weighed by its slots alone, a frame learned from one sentence, matching much of
    another word for word, has few slots to fill and outweighs the general frames: "One hundred and twenty-three
    trillion ..." read as another number. So it tells apart only structures that supposed as little as each other
    (`meant`); which structures reach the listener is still the reader's least supposed (2026-10-13).

    A reading English's grammar composed holds no link, so what it carries of the grammar's own ranking is what is
    weighed here (`Reading.structure`): every composed reading of one sentence supposes exactly as little as the
    others (no link proposed, no word read through another), so without it the listener would have nothing of
    structure to tell them apart and would choose on what memory knows alone."""
    if reading.composed:
        return reading.structure
    return _derivation_of(reading.links, reading.proposed, view)


def _derivation_of(links: Iterable[Link], proposed: Iterable[Link], view: PatternInventory) -> float:
    """How probable the structure these held and proposed links make is (`_derivation`), for a reading or a part."""
    # EACH LINK IS ONE SLOT FILLED, the same phrase filled again where it is used again ("?slot0 ?slot1" in "three
    # hundred and twelve billion five million"): looked up by its frame and slot, every use of a phrase took one
    # filler, and two bracketings of a number scored alike.
    parts = view.parts_met()
    total = 0.0
    for link, held in [(link, True) for link in links] + [(link, False) for link in proposed]:
        filler = view._by_key.get(link.lexical)
        uses, fillers = view.slot_filled(link.pattern, link.slot)
        k = view.uses(link) if held else 0.0
        met, count = parts.get((view._taken_at(link.pattern, link.slot) or ("thing",))[0], (0.0, 0))
        share = ((_met(view, filler) if filler is not None else 0) + 1) / (met + count + 1)
        total += math.log((k + fillers * share) / (uses + fillers)) if uses + fillers else math.log(share)
    return total


class Weighed(NamedTuple):
    """One reading as the listener weighs it (`weighed`): what memory knows of its facts (`known`: 2 held of the things
    themselves, 1 of what they are kinds of), what their definitions say (`defined`: 2 one written with the other, 1
    with what it is a kind of), how much it supposed past its words (`fit`: its links proposed, words read through
    another, misfits and fillers apart, `Reading.supposed`), its activation in nats (how often its own senses were
    met, `ln(1 + uses)`, what the other words select of them and what the rest raises), and how probable its
    structure is (`_derivation`, ln)."""
    reading: Reading
    known: int
    defined: int
    fit: int
    activation: float
    derivation: float


#: The listener's evidence it weighs by what it was measured to be worth, with how many levels each has (the last
#: holding all above it): what memory knows, what definitions say, and how much a reading supposed past its words.
LISTENING_LEVELS = {"known": 3, "defined": 3, "fit": 4}

#: HOW MANY READINGS THE COUNTING PASS ASKS FOR (`listening_counts`), which is not how many anything else asks for
#: (`composing_width`).
#:
#: THE CIRCLE THIS BREAKS, every link of it measured. `listening_counts` counts a sentence only where it reads MORE
#: THAN ONE WAY, because what it learns is which evidence told the reading meant from the readings not meant; at
#: `COMPOSED_READINGS` of one no composed sentence reads more than one way, so the pass ran clean over 3,054 lesson
#: sentences and counted nothing ({'observed': 0, 'total': 20}, 2026-11-03). Nothing counted leaves every level
#: worth `ln(1) = 0` (`listening_worths`, Laplace on two zeros), and `known`, `defined` and `fit` are multiplied by
#: nothing, so the listener weighs only the grammar's own structural score and returns the grammar's own first
#: choice. Verified against both stores: zero `listening_claim` beliefs held on either (2026-11-09). The reader
#: hands up one reading, the listener never has a choice, the pass never sees a choice to count, the worths stay
#: zero. Every link breaks at the same place.
#:
#: SIX, where the choices first exist to be counted. Over the PMB's held-out dev part the right reading is available
#: for 54.2% of sentences at one, 56.2% at six and 58.7% at fifty, while the reader's own choice is flat from six to
#: fifty (GRAMMAR-01, 2026-11-03): six is the least width that hands the pass readings to tell apart, and the pass is
#: paid once, on short taught sentences, not on every utterance.
LISTENING_WIDTH = int(os.environ.get("LYRIC_LISTENING_WIDTH", "6"))


def listening_levels(weighed_reading: Weighed) -> Dict[str, int]:
    """The level of each of the listener's evidence a reading shows (`LISTENING_LEVELS`)."""
    return {evidence: min(getattr(weighed_reading, evidence), levels - 1)
            for evidence, levels in LISTENING_LEVELS.items()}


def listening_claim(evidence: str, level: int, meant: bool) -> str:
    """The belief counting the readings heard with this evidence at this level that were, or were not, the one meant."""
    return f"a reading heard with {evidence} at {level} was {'' if meant else 'not '}the one meant"


def listening_worths(counts: Mapping[Tuple[str, int, bool], int]) -> Dict[Tuple[str, int], float]:
    """What each piece of the listener's evidence at each level is worth, in nats: how much more often the readings
    meant showed it than the readings not meant, `ln(P(level | meant) / P(level | not meant))`, each count with one
    added (Laplace). A listener that has counted nothing weighs every level at nothing."""
    worths: Dict[Tuple[str, int], float] = {}
    for evidence, levels in LISTENING_LEVELS.items():
        meant_n = sum(counts.get((evidence, level, True), 0) for level in range(levels))
        other_n = sum(counts.get((evidence, level, False), 0) for level in range(levels))
        for level in range(levels):
            worths[(evidence, level)] = math.log(
                ((counts.get((evidence, level, True), 0) + 1) / (meant_n + levels))
                / ((counts.get((evidence, level, False), 0) + 1) / (other_n + levels)))
    return worths


def _held_listening_counts() -> Dict[Tuple[str, int, bool], int]:
    """The listener's counts as memory holds them: the uses each listening claim's observations witnessed."""
    from core.reasoning import bayesian_uncertainty as beliefs
    system = beliefs._uncertainty_system
    counts: Dict[Tuple[str, int, bool], int] = {}
    if system is None:
        return counts
    for evidence, levels in LISTENING_LEVELS.items():
        for level in range(levels):
            for was_meant in (True, False):
                belief = system.belief_for_claim(listening_claim(evidence, level, was_meant))
                if belief is not None:
                    counts[(evidence, level, was_meant)] = beliefs.BayesianUncertaintySystem.uses_for(belief)
    return counts


def weighed(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None, *,
            heard: Optional[Heard] = None) -> List[Weighed]:
    """Every meaning an utterance read to, its best reading weighed as the listener weighs it (`Weighed`), in the
    order read. What the listener chooses by (`meant`), and what it counts to learn what its evidence is worth
    (`listening_worths`): one function, so what is measured is what is weighed.

    A reading's own senses are what it names that not every reading names: a word's thing where readings differ in
    which thing it names, nothing where they differ only in how the words go together. Counted within its own
    structure, a reading alone in one counted none, and lost to any that shared its structure with another."""
    best: Dict[str, Reading] = {}
    for reading in readings:
        best.setdefault(reading.meaning.canonical(), reading)
    view = inventory if inventory is not None else _live_inventory()
    held, related, selected, _, defined = heard if heard is not None else Heard()
    choices = list(best.values())
    named = {key: frozenset(t for f in r.meaning.facts for t in f.terms() if not is_variable(t))
             for key, r in best.items()}
    common = frozenset.intersection(*named.values()) if named else frozenset()
    senses, _ = _senses(choices) if len(choices) > 1 else ({}, frozenset())

    def naming(construction: Construction, mine: FrozenSet[str]) -> bool:
        # A construction that names one of the reading's own senses: a word for it, a phrase stating it, or a frame
        # that writes it itself ("It's hot.", taught whole: its "hot" was met there, and a sense of "hot" met once
        # elsewhere took it).
        if isinstance(construction, Lexical):
            return construction.value in mine
        if isinstance(construction, Phrase):
            return bool(_named_in(construction) & mine)
        return isinstance(construction, Pattern) and any(
            not is_variable(term) and term in mine for f in construction.meaning.facts for term in f.terms())

    out: List[Weighed] = []
    for key, reading in best.items():
        facts = listening_facts(reading.meaning)
        own = named[key] - common
        # HOW OFTEN EACH SENSE WAS MET, NOT THE SENTENCE AROUND IT: the words and phrases that name the reading's own
        # senses. Counted over every construction, the frame a sense was read through weighed in: "?slot0 her", met
        # 5,951 times holding a phrase, took "saw" for understanding (met once so) over seeing (met 11 times through
        # another "?slot0 her", met 631 times). A construction every reading shares weighs alike in each.
        base = sum(math.log1p(_met(view, c)) for c in reading.constructions if naming(c, own))
        activation = base + sum(selected.get(held_key(f), 0.0) for f in facts) + \
            sum(related.get(term, 0.0) for term in senses.get(key, ()))
        out.append(Weighed(reading, sum(held.get(held_key(f), 0) for f in facts),
                           sum(defined.get(held_key(f), 0) for f in facts), sum(reading.supposed[2:]),
                           activation, _derivation(reading, view)))
    return out


def _one_sense_each(options: Sequence[Tuple[Sense, Tuple[int, int, int]]],
                    view: PatternInventory) -> Tuple[Tuple[Sense, Tuple[int, int, int]], ...]:
    """A packed word's senses, one for each thing it names, as the readings of them one by one keep one: of held words
    naming one thing ("Light" and "light"), in a phrase's slot the first found, as a phrase keeps the first of its
    readings saying the same (`_phrase_fillings`); in a frame's slot the one a reading of them puts first
    (`_best_first`: supposing least, then believed, then used)."""
    best: Dict[str, Tuple[Tuple, Sense, Tuple[int, int, int]]] = {}
    for at, (sense, cost) in enumerate(options):
        in_phrase = isinstance(view.get(sense.link.pattern), Phrase)
        rank = (at,) if in_phrase else (cost, -view.score(sense.lexical), -view.uses(sense.lexical), sense.lexical.key)
        value = sense.lexical.value
        if value not in best or rank < best[value][0]:
            best[value] = (rank, sense, cost)
    return tuple((sense, cost) for _, sense, cost in best.values())


def unpacked(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None) -> Tuple[Reading, ...]:
    """Every reading packed readings stand for, each choice of their words' senses made (`with_senses`), the reading of
    each meaning the reader puts first, best first, as `_read_pieces` hands them. Only where every one is wanted: the listener counting what its evidence
    is worth on taught sentences, a word's senses listed when it is asked which was meant."""
    view = inventory if inventory is not None else _live_inventory()
    made: List[Reading] = []
    for reading in readings:
        if not reading.senses:
            made.append(reading)
            continue
        words = [stand_in for stand_in, _, _, _ in reading.senses]
        each = [[sense for sense, _ in _one_sense_each(options, view)] for _, options, _, _ in reading.senses]
        made.extend(r for r in (with_senses(reading, dict(zip(words, chosen)), view)
                                for chosen in itertools.product(*each)) if r is not None)
    # One reading of each meaning, the one the reader puts first of all of them, as `_read_pieces` keeps it.
    out: Dict[str, Reading] = {}
    for r in sorted(made, key=_best_first):
        out.setdefault(r.meaning.canonical(), r)
    return tuple(out.values())


def _named_consts(reading: Reading) -> FrozenSet[str]:
    """The things a reading's meaning names, its packed words aside."""
    return frozenset(t for f in reading.meaning.facts for t in f.terms()
                     if not is_variable(t) and not t.startswith(_STAND_IN))


def _listened_terms(reading: Reading) -> FrozenSet[str]:
    """The things the facts a listener weighs of a reading name (`listening_facts`), its packed words aside."""
    return frozenset(t for f in listening_facts(reading.meaning) for t in f.terms() if not t.startswith(_STAND_IN))


def _always(reading: Reading, terms: FrozenSet[str], view: PatternInventory, listened: bool) -> FrozenSet[str]:
    """Of the things a reading names, those every reading it stands for names: what it names apart from its packed
    words, and a packed word's thing where all its senses name one (in the facts weighed, where `listened`)."""
    named = set(terms)
    stand_ins = {t for f in (listening_facts(reading.meaning) if listened else reading.meaning.facts)
                 for t in f.terms() if t.startswith(_STAND_IN)}
    for stand_in, options, _, _ in reading.senses:
        values = {sense.lexical.value for sense, _ in options}
        if len(values) == 1 and stand_in in stand_ins:
            named |= values
    return frozenset(named)


class _Weighing(NamedTuple):
    """A reading as the listener weighs it, its packed words' senses still to choose (`_choices`): what does not turn
    on them, in nats and in the evidence counted in levels (known, defined, fit), and, for each packed word, each
    sense's own share and the facts it shares with another."""
    reading: Reading
    words: Tuple[str, ...]
    options: Tuple[Tuple[Tuple[Sense, Tuple[int, int, int]], ...], ...]
    fixed: float
    counted: Tuple[int, int, int]
    own: Tuple[Tuple[Tuple[float, int], ...], ...]
    facts: Tuple[Tuple[Tuple[int, ...], Dict[Tuple[int, ...], Tuple[float, int, int]]], ...]


def _weighing(reading: Reading, view: PatternInventory, heard: "Heard", common: FrozenSet[str],
              shared: FrozenSet[str]) -> _Weighing:
    """What the listener weighs of a reading (`weighed`), split by what turns on which sense each packed word takes:
    how often each sense was met where it names a thing not every reading names (`_met`), what the rest raises
    (`related`), how probable its link is (`_derivation_of`), what it supposes (fit); and each fact weighed
    (`listening_facts`) by the senses it joins: what is said of what (`selected`), what memory holds (`held`), what
    definitions say (`defined`). The things every reading names (`common`, `shared`) weigh alike in each, and are
    not counted, as `weighed` does not count them."""
    held, related, selected, _, defined = heard
    words = tuple(stand_in for stand_in, _, _, _ in reading.senses)
    options = tuple(_one_sense_each(options, view) for _, options, _, _ in reading.senses)
    at = {stand_in: k for k, stand_in in enumerate(words)}
    mine = _named_consts(reading) - common

    def naming(construction: Construction) -> bool:
        if isinstance(construction, Lexical):
            return construction.value in mine
        if isinstance(construction, Phrase):
            return bool(_named_in(construction) & mine)
        return isinstance(construction, Pattern) and any(
            not is_variable(term) and term in mine for f in construction.meaning.facts for term in f.terms())
    fixed = sum(math.log1p(_met(view, c)) for c in reading.constructions if not _stand_in(c) and naming(c))
    fixed += sum(related.get(term, 0.0) for term in _listened_terms(reading) - shared)
    fixed += _derivation_of(reading.links, reading.proposed, view)
    known = defined_count = 0
    listened_words = {t for f in listening_facts(reading.meaning) for t in f.terms() if t in at}
    facts = []
    for fact in listening_facts(reading.meaning):
        scope = tuple(sorted({at[t] for t in fact.terms() if t in at}))
        if not scope:
            fixed += selected.get(held_key(fact), 0.0)
            known += held.get(held_key(fact), 0)
            defined_count += defined.get(held_key(fact), 0)
            continue
        table: Dict[Tuple[int, ...], Tuple[float, int, int]] = {}
        for choice in itertools.product(*(range(len(options[k])) for k in scope)):
            names = {words[k]: options[k][x][0].lexical.value for k, x in zip(scope, choice)}
            subject, obj = names.get(fact.subject, fact.subject), names.get(fact.obj, fact.obj)
            if subject == obj:
                table[choice] = (0.0, 0, 0)
                continue
            key = (fact.relation, subject, obj, fact.positive)
            table[choice] = (selected.get(key, 0.0), held.get(key, 0), defined.get(key, 0))
        facts.append((scope, table))
    own = []
    for stand_in, choices in zip(words, options):
        shares = []
        for sense, cost in choices:
            value = sense.lexical.value
            share = math.log1p(_met(view, sense.lexical)) if value not in common else 0.0
            if stand_in in listened_words and value not in shared:
                share += related.get(value, 0.0)
            share += _derivation_of((sense.link,), (), view) if sense.held else _derivation_of((), (sense.link,), view)
            shares.append((share, sum(cost)))
        own.append(tuple(shares))
    fit = len(reading.proposed) + reading.said_for + reading.misfits + reading.apart
    return _Weighing(reading, words, options, fixed, (known, defined_count, fit), tuple(own), tuple(facts))


#: How many of each count of the listener's evidence tell apart, as its levels do (`LISTENING_LEVELS`): known,
#: defined, fit.
_LEVELS = (LISTENING_LEVELS["known"] - 1, LISTENING_LEVELS["defined"] - 1, LISTENING_LEVELS["fit"] - 1)


def _levelled(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> Tuple[int, int, int]:
    return (min(a[0] + b[0], _LEVELS[0]), min(a[1] + b[1], _LEVELS[1]), min(a[2] + b[2], _LEVELS[2]))


def _choices(weighing: _Weighing, worths: Mapping[Tuple[str, int], float],
             best: int) -> List[Tuple[float, Tuple[int, ...]]]:
    """The `best` choices of senses for a reading's packed words, by the listener's score (`meant`), highest first:
    (score, the sense each word takes). Found word by word over the facts that join them (variable elimination: each
    word's senses weighed against the words it shares facts with, then set aside), never every choice crossed: what
    the listener weighs is a sum over words and over facts between two, and what it counts in levels is a small
    state (known, defined, fit, each capped at its last level), so the best of the whole is made of the best of its
    parts for each state. A few kept for each state, so ties are found and asked about."""
    n = len(weighing.words)
    # A factor: its words, and for each choice of their senses, a few (score, counted, the senses of words set aside).
    Entry = Tuple[float, Tuple[int, int, int], Tuple[Tuple[int, int], ...]]
    factors: List[Tuple[Tuple[int, ...], Dict[Tuple[int, ...], List[Entry]]]] = []
    for k, shares in enumerate(weighing.own):
        factors.append(((k,), {(x,): [(share, (0, 0, min(fit, _LEVELS[2])), ())] for x, (share, fit) in enumerate(shares)}))
    for scope, table in weighing.facts:
        factors.append((scope, {choice: [(value, (min(h, _LEVELS[0]), min(d, _LEVELS[1]), 0), ())]
                                for choice, (value, h, d) in table.items()}))

    def kept(entries: Iterable[Entry]) -> List[Entry]:
        by_state: Dict[Tuple[int, int, int], List[Entry]] = {}
        for entry in entries:
            by_state.setdefault(entry[1], []).append(entry)
        return [e for group in by_state.values() for e in sorted(group, key=lambda e: -e[0])[:best]]

    def joined(a: List[Entry], b: List[Entry]) -> List[Entry]:
        return kept((x[0] + y[0], _levelled(x[1], y[1]), x[2] + y[2]) for x in a for y in b)

    remaining = list(range(n))
    while remaining:
        # The word sharing facts with the fewest others goes first.
        def neighbours(k: int) -> Set[int]:
            return {j for scope, _ in factors if k in scope for j in scope if j != k}
        word = min(remaining, key=lambda k: (len(neighbours(k)), k))
        remaining.remove(word)
        touching = [f for f in factors if word in f[0]]
        factors = [f for f in factors if word not in f[0]]
        scope = tuple(sorted({j for s, _ in touching for j in s if j != word}))
        table: Dict[Tuple[int, ...], List[Entry]] = {}
        for rest in itertools.product(*(range(len(weighing.options[j])) for j in scope)):
            given = dict(zip(scope, rest))
            gathered: List[Entry] = []
            for x in range(len(weighing.options[word])):
                given[word] = x
                entries: List[Entry] = [(0.0, (0, 0, 0), ((word, x),))]
                for s, t in touching:
                    entries = joined(entries, t[tuple(given[j] for j in s)])
                gathered.extend(entries)
            table[rest] = kept(gathered)
        factors.append((scope, table))
    entries: List[Entry] = [(weighing.fixed, (min(weighing.counted[0], _LEVELS[0]), min(weighing.counted[1], _LEVELS[1]),
                                               min(weighing.counted[2], _LEVELS[2])), ())]
    for _, t in factors:
        entries = joined(entries, t[()])
    scored = []
    for value, counted, chosen in entries:
        score = round(value + worths.get(("known", counted[0]), 0.0) + worths.get(("defined", counted[1]), 0.0)
                      + worths.get(("fit", counted[2]), 0.0), 6)
        senses = dict(chosen)
        scored.append((score, tuple(senses[k] for k in range(n))))
    return sorted(scored, key=lambda pair: -pair[0])[:best]


def _score_at(weighing: _Weighing, chosen: Sequence[int], worths: Mapping[Tuple[str, int], float]) -> float:
    """The listener's score of a reading with these senses chosen for its packed words (`_choices`)."""
    value = weighing.fixed + sum(weighing.own[k][x][0] for k, x in enumerate(chosen))
    known, defined, fit = weighing.counted
    fit += sum(weighing.own[k][x][1] for k, x in enumerate(chosen))
    for scope, table in weighing.facts:
        selected, held, said = table[tuple(chosen[k] for k in scope)]
        value, known, defined = value + selected, known + held, defined + said
    return round(value + worths.get(("known", min(known, _LEVELS[0])), 0.0)
                 + worths.get(("defined", min(defined, _LEVELS[1])), 0.0)
                 + worths.get(("fit", min(fit, _LEVELS[2])), 0.0), 6)


def _made(weighing: _Weighing, chosen: Sequence[int], view: PatternInventory) -> Optional[Reading]:
    return with_senses(weighing.reading, {w: weighing.options[k][x][0] for k, (w, x) in
                                          enumerate(zip(weighing.words, chosen))}, view)


def _best_packed(readings: Sequence[Reading], view: PatternInventory, heard: "Heard",
                 ranked_out: Optional[List[Tuple[float, Reading]]] = None) -> List[Reading]:
    """Where some readings are packed, the meanings the listener weighs highest, alike: each reading's best senses
    found over its structure (`_choices`), and the meanings these make weighed as `meant` weighs them, each by the
    reading of it the reader puts first (`_best_first`), as the reader hands the listener one reading of each meaning.

    Searched until nothing unfound can score as high: a meaning's best reading scores at most what its highest
    reading scores, so once every reading's next choice scores below the best found, the best and every meaning tied
    with it are found."""
    concrete: Dict[str, Reading] = {}
    packed = []
    for reading in readings:
        if reading.senses:
            packed.append(reading)
        else:
            concrete.setdefault(reading.meaning.canonical(), reading)
    every = list(concrete.values()) + packed
    common = frozenset.intersection(*(_always(r, _named_consts(r), view, False) for r in every))
    shared = frozenset.intersection(*(_always(r, _listened_terms(r), view, True) for r in every))
    worths = view.listening_worths()
    weighings = [_weighing(r, view, heard, common, shared) for r in every]

    def first_reading(meaning: Meaning) -> Optional[Tuple[float, Reading]]:
        """The reading of this meaning the reader puts first, of every reading, and its score."""
        named = {t for f in meaning.facts for t in f.terms() if not is_variable(t)}
        key = meaning.canonical()
        found: List[Tuple[Tuple, float, Reading]] = []
        for weighing in weighings:
            each = [[x for x, (sense, _) in enumerate(options) if sense.lexical.value in named]
                    for options in weighing.options]
            for chosen in itertools.product(*each):
                made = _made(weighing, chosen, view)
                if made is not None and made.meaning.canonical() == key:
                    found.append((_best_first(made), _score_at(weighing, chosen, worths), made))
        if not found:
            return None
        _, score, made = min(found, key=lambda item: item[0])
        return score, made

    best = 2
    scored: Dict[str, Tuple[float, Reading]] = {}
    while True:
        frontier = -math.inf
        for weighing in weighings:
            found = _choices(weighing, worths, best)
            if len(found) >= best and len(found) < math.prod(len(o) for o in weighing.options):
                frontier = max(frontier, found[-1][0])
            for _, chosen in found:
                made = _made(weighing, chosen, view)
                if made is None:
                    continue
                key = made.meaning.canonical()
                if key not in scored:
                    first = first_reading(made.meaning)
                    if first is not None:
                        scored[key] = first
        top = max((score for score, _ in scored.values()), default=-math.inf)
        if frontier < top or frontier == -math.inf:
            break
        best *= 2
    # Alike, in the order the reader hands them (`_best_first`), as the listener weighs them in that order.
    ranked = sorted(scored.values(), key=lambda pair: (-pair[0], _best_first(pair[1])))
    # WHAT IT WEIGHED, NOT ONLY WHAT IT TOOK: every meaning scored, best first, for a caller that asked
    # (`_meant_packed`). A packed reading stands for many, so this is the only place the runner-up exists.
    if ranked_out is not None:
        ranked_out[:] = ranked
    return [r for score, r in ranked if score == ranked[0][0]]


#: How much of a meaning a trace line carries; the whole of it is kept in `why` for whoever asked.
_SAID_AT_MOST = 220


def _memory_said(heard: Optional["Heard"]) -> str:
    """WHETHER MEMORY WAS ASKED, and whether it answered. Four of the five channels that tell readings apart are
    memory's (`held`, `related`, `selected`, `defined`), so a listener with no memory at hand decides on structure
    alone — and a decision made on structure alone reads exactly like a decision made on evidence."""
    if heard is None:
        return "memory not asked"
    held, related, selected, _, defined = heard
    if not (held or related or selected or defined):
        return "memory asked, knew nothing of any reading"
    return (f"memory holds {len(held)} of their facts, defines {len(defined)}, "
            f"selects {len(selected)}, raises {len(related)} things")


def _listening_said(given: int, rows: Optional[Sequence[Tuple["Weighed", float]]], took: Optional[Reading],
                    how: str, heard: Optional["Heard"], why: Optional[Dict[str, Any]],
                    worths: Optional[Mapping[Tuple[str, int], float]] = None,
                    margin: Optional[float] = None) -> None:
    """WHAT THE LISTENER RECEIVED, WEIGHED AND TOOK, said where it can be read: filled into `why` where a caller
    passed one, and said on the substrate channel.

    THE LISTENER WAS THE SILENT HALF OF READING. Which reading it took, by what margin, over what, and on which of
    its evidence were all worked out and then thrown away, so the only way to see any of it was to infer it from how
    often whole runs came out right. A day went into establishing, from aggregate scores alone, what one line would
    have said outright: that the grammar handed the listener ONE reading and it returned before weighing anything
    (2026-11-03). Every component that decides something silently costs that same day the first time it is wrong.

    One reading is nothing chosen, and is said at debug; a real choice is said at info with the margin over the
    runner-up, which is what tells a flat decision from a confident one. `how` is the one thing that decided, never
    a guess after the fact, as `Grammar.say` fills its own `why`.

    EACH CHANNEL IS SAID BESIDE WHAT IT WAS WORTH (`listening_worths`, learned), because the two come apart and the
    difference is invisible otherwise: memory holding a reading's fact firmly counts for exactly nothing until the
    listener has measured what holding it is worth, and a row reading "known 2" over a total that memory moved not
    at all is the whole of that story in one line."""
    memory = _memory_said(heard)
    if why is not None:
        why.clear()
        why.update({
            "readings": given, "took": took.meaning.canonical() if took is not None else None, "how": how,
            "memory": memory,
            # HOW MUCH THE ONE TAKEN BEAT THE NEXT, in nats: None where nothing was weighed against it. A margin
            # of 0.2 nats and a margin of 20 are the same decision from the outside and are not the same decision.
            "margin": margin,
            "weighed": [{"meaning": w.reading.meaning.canonical(), "known": w.known, "defined": w.defined,
                         "fit": w.fit, "activation": round(w.activation, 4), "structure": round(w.derivation, 4),
                         "total": total, "composed": w.reading.composed,
                         "worth": {evidence: round((worths or {}).get((evidence, level), 0.0), 4)
                                   for evidence, level in listening_levels(w).items()}}
                        for w, total in (rows or ())],
        })
    if given < 2 and not logger.isEnabledFor(logging.DEBUG):
        return
    said = took.meaning.canonical()[:_SAID_AT_MOST] if took is not None else "nothing"
    if given < 2:
        logger.debug("listening: %d reading%s, nothing to weigh (%s): %s", given,
                     "" if given == 1 else "s", memory, said)
        return
    if not rows or len(rows) < 2:
        # A PACKED READING STANDS FOR MANY, so there is no row for each meaning to show; what chose among them is
        # `_best_packed`, over each choice of its words' senses.
        logger.info("listening: %d readings, %s%s (%s): %s", given, how,
                    "" if margin is None else f", by {margin:.3f} nats over the next",
                    memory, said)
        return
    w = rows[0][0]
    worth = {evidence: (worths or {}).get((evidence, level), 0.0) for evidence, level in listening_levels(w).items()}
    moved = sum(worth.values())
    logger.info("listening: %d readings, %s by %.2f nats over the next of %d (known %d worth %.2f, defined %d worth "
                "%.2f, fit %d worth %.2f, met+raised %.2f, structure %.2f%s; %s): %s",
                given, how, rows[0][1] - rows[1][1], len(rows), w.known, worth.get("known", 0.0), w.defined,
                worth.get("defined", 0.0), w.fit, worth.get("fit", 0.0), w.activation, w.derivation,
                "" if moved else " — NOTHING MEMORY KNOWS IS WORTH ANYTHING YET", memory, said)


def _meant_packed(readings: Sequence[Reading], view: PatternInventory, heard: "Heard",
                  why: Optional[Dict[str, Any]] = None) -> Optional[Reading]:
    """`meant`, where some readings are packed: the meaning the listener weighs highest (`_best_packed`); where two
    score alike, asked about, unless they differ only in senses that are one coarse sense. Says what it did
    (`_listening_said`)."""
    order: List[Tuple[float, Reading]] = []

    def said(took: Optional[Reading], how: str) -> Optional[Reading]:
        _listening_said(len(readings), None, took, how, heard, why,
                        margin=(order[0][0] - order[1][0]) if len(order) > 1 else None)
        return took
    tied = _best_packed(readings, view, heard, order)
    if len(tied) <= 1:
        return said(next(iter(tied), None), "took the only meaning weighed highest")
    if len({_worded(r, view) for r in tied}) > 1:
        return said(None, f"could not tell: {len(tied)} weigh alike and say different things")
    senses, _ = _senses(tied)
    things = [senses[r.meaning.canonical()] for r in tied]
    one = all(frozenset((a, b)) in heard.together for i, mine in enumerate(things) for theirs in things[i + 1:]
              for a in mine for b in theirs if a != b)
    return said(tied[0] if one else None,
                f"{len(tied)} weigh alike, of one coarse sense" if one
                else f"could not tell: {len(tied)} weigh alike, of senses not one")


def meant(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None, *,
          heard: Optional[Heard] = None, why: Optional[Dict[str, Any]] = None) -> Optional[Reading]:
    """Which reading of an utterance was meant, as a listener takes it; None when the listener cannot tell.

    The reader reports every meaning the words can have (`read`); this is the listener's half. Every reading is
    weighed as one sum in nats (`weighed`), whether readings differ in which thing a word names or in how the words
    go together:
      - ONE ACTIVATION, ACT-R's: how often the reading's own senses were met (`ln(1 + uses)`, a word in any of its
        shapes, `_met`: "fish" names the animal far more often than the food); how much more likely each thing is
        given what the sentence's other words are said of (`selected`, `MemoryAgent.said_selection`: "The table is
        red." is the table that is furniture); and how much the rest of what is said and what was said before raise
        it (`related`, spreading activation: after "We went to the river.", "the bank" is the bank a river has);
      - how probable its structure is, as its parts were met (`_derivation`);
      - and, each worth what the listener measured it to be worth on what it was taught (`listening_worths`): what
        memory knows of what it says, what one thing's definition says of the other, and how much it supposed past
        its words. "A salmon is a fish." is about the fish memory knows a salmon to be; "It will snow soon." is the
        snowing taught there, not the snow that never stood there.

    EVIDENCE ADDED, NOT RANKED. What memory knew came first, outright, and memory knows things of some senses and
    not others: "A bus is a vehicle." was the old car that is a bus (met 3 times, known a vehicle) over the bus (met
    14 times, filed under public transport); "A window is made of glass." a windowpane. Measured on the taught
    lessons, a reading memory holds of the things themselves was the one meant 4.7 nats more often than not, a
    reading that fit its words 6.3 nats more, and the sum took 2,874 of 2,882 lessons as taught where ranking took
    2,866 (on half of them, worths counted on the other half: 1,439 of 1,441 against 1,433), and 200 of 270
    never-taught sentences' structures where ranking took 197 (2026-10-14).

    Readings that weigh alike are asked about unless they differ only in things that are one coarse sense
    (`together`: one a near kind of the other, or both of one thing), which a listener has understood without
    telling them apart. With no memory at hand (`heard` None), nothing memory would say is weighed.

    WHAT IT WEIGHED AND WHAT DECIDED IT are said on the substrate channel and filled into `why` where a caller
    passes one (`_listening_said`), as `Grammar.say` fills its own: the readings received, each one's evidence and
    total, which was taken, the margin over the next, and whether memory was asked at all."""
    if any(reading.senses for reading in readings):
        view = inventory if inventory is not None else _live_inventory()
        return _meant_packed(readings, view, heard if heard is not None else Heard(), why)
    best: Dict[str, Reading] = {}
    for reading in readings:
        best.setdefault(reading.meaning.canonical(), reading)
    if len(best) < 2:
        # NOTHING WEIGHED, AND SAID SO. One meaning is not a choice, and for an utterance English's grammar composed
        # this was every utterance until 2026-11-03: the reader handed up the one reading its own score put first,
        # and none of the evidence below ever ran.
        one = next(iter(best.values()), None)
        _listening_said(len(best), None, one, "the only meaning the words have", heard, why)
        return one
    view = inventory if inventory is not None else _live_inventory()
    worths = view.listening_worths()

    def score(w: Weighed) -> float:
        return round(w.activation + w.derivation + sum(worths.get((evidence, level), 0.0)
                                                       for evidence, level in listening_levels(w).items()), 6)
    ranked = sorted(weighed(list(best.values()), view, heard=heard), key=score, reverse=True)
    rows = [(w, score(w)) for w in ranked]

    def said(took: Optional[Reading], how: str) -> Optional[Reading]:
        _listening_said(len(best), rows, took, how, heard, why, worths,
                        margin=(rows[0][1] - rows[1][1]) if len(rows) > 1 else None)
        return took
    if score(ranked[0]) != score(ranked[1]):
        return said(ranked[0].reading, "took the one weighed highest")
    tied = [w.reading for w in ranked if score(w) == score(ranked[0])]
    if all(r.composed for r in tied):
        # READINGS THAT DIFFER IN HOW THE WORDS GO TOGETHER ARE NOT ASKED ABOUT: the speaker can say which thing they
        # meant by a word, and not which of two structures the grammar built of their sentence. Weighing them alike,
        # the listener leaves the reader's own first standing, which is the reading it had before the others were
        # handed to it at all (`_read_by_composing`); told None, the conversation learns nothing from the sentence.
        return said(tied[0], f"{len(tied)} weigh alike and differ in structure: the reader's own first stands")
    if len({_worded(r, view) for r in tied}) > 1:
        return said(None, f"could not tell: {len(tied)} weigh alike and say different things")
    together = (heard if heard is not None else Heard()).together
    senses, _ = _senses(tied)
    things = [senses[r.meaning.canonical()] for r in tied]
    one = all(frozenset((a, b)) in together for i, mine in enumerate(things) for theirs in things[i + 1:]
              for a in mine for b in theirs if a != b)
    return said(tied[0] if one else None,
                f"{len(tied)} weigh alike, of one coarse sense" if one
                else f"could not tell: {len(tied)} weigh alike, of senses not one")


async def listening(utterances: Iterable[Sequence[Reading]], context: Iterable[str] = ()) -> Heard:
    """What memory knows that bears on which thing each word was meant to name, for every utterance whose meanings
    differ only in that (`Heard`), against the rest of what was said and `context`, the things talked of before.
    Asked of the memory agent, the one reader of memory. Empty where nothing is to be chosen."""
    facts, senses, around = set(), set(), set(context)
    for readings in utterances:
        # EVERY READING OF AN UTTERANCE THAT READ MORE THAN ONE WAY, as `weighed` weighs them all together: what
        # memory holds of each, and the things each takes a word to name that the others do not.
        best: Dict[str, Reading] = {}
        for reading in readings:
            if not reading.senses:
                best.setdefault(reading.meaning.canonical(), reading)
        packed = [reading for reading in readings if reading.senses]
        if packed:
            # A PACKED READING'S FACTS, EACH PAIRING OF ITS WORDS' SENSES: what memory holds of each fact a choice of
            # senses makes, never of each whole reading.
            every = list(best.values()) + packed
            view = _live_inventory()
            shared = frozenset.intersection(*(_always(r, _listened_terms(r), view, True) for r in every))
            partners: Set[str] = set()
            for reading in every:
                values = {stand_in: [sense.lexical.value for sense, _ in _one_sense_each(options, view)]
                          for stand_in, options, _, _ in reading.senses}
                mine = set(_listened_terms(reading) - shared)
                made = []
                for fact in listening_facts(reading.meaning):
                    words = [t for t in dict.fromkeys(fact.terms()) if t in values]
                    mine.update(v for t in words for v in values[t] if v not in shared)
                    for chosen in itertools.product(*(values[t] for t in words)):
                        names = dict(zip(words, chosen))
                        subject, obj = names.get(fact.subject, fact.subject), names.get(fact.obj, fact.obj)
                        if subject != obj:
                            made.append(MeaningFact(fact.relation, subject, obj, fact.positive))
                for fact in made:
                    facts.add(held_key(fact))
                    if fact.subject in mine:
                        partners.add(fact.obj)
                    if fact.obj in mine:
                        partners.add(fact.subject)
                senses.update(mine)
            around.update(shared - partners)
            continue
        if len(best) < 2:
            continue
        choices = list(best.values())
        own, shared = _senses(choices)
        partners: Set[str] = set()
        for reading in choices:
            mine = own[reading.meaning.canonical()]
            for fact in listening_facts(reading.meaning):
                facts.add(held_key(fact))
                # THE WORD A THING'S OWN FACT PAIRS IT WITH ("long" in "The trunk is long.") is weighed by what that
                # word is said of (`selected`), with counts; counted again here, a definition that happens to use
                # it ("a long flexible snout") made the elephant's trunk as near as the tree's after "A tree is a
                # plant.".
                if fact.subject in mine:
                    partners.add(fact.obj)
                if fact.obj in mine:
                    partners.add(fact.subject)
        for terms in own.values():
            senses.update(terms)
        around.update(shared - partners)
    if not facts and not senses:
        return Heard()
    from core.agents.memory_agent import memory_agent
    agent = memory_agent()
    # ONE SENSE PER DISCOURSE (Yarowsky 1995): a thing talked of before is in the context of the next word that names
    # it, as the river's bank is when "the bank" comes again.
    held, related, defined = await agent.listening_evidence(facts, senses, around)
    return Heard(held, related, await agent.said_selection(facts, senses), await agent.coarse_senses(senses),
                 defined)


async def listening_counts(pairs: Iterable[Tuple[str, Meaning]], inventory: Optional[PatternInventory] = None, *,
                           give_way: Optional[Callable[[], Awaitable[None]]] = None,
                           width: int = 0) -> Counter:
    """What the listener's evidence was, on sentences whose meaning it was taught: for every sentence read one way
    with more than one meaning, the taught one among them, each meaning's level of each piece of evidence
    (`listening_levels`), counted by whether it was the one meant. What `listening_worths` makes worths of, as a
    person learns what to listen for from being told what was meant. `give_way`: awaited after each sentence, so a
    pass on a running substrate keeps its loop."""
    view = inventory if inventory is not None else _live_inventory()
    counts: Counter = Counter()
    for sentence, meaning in pairs:
        # ASKED WIDE HERE AND NOWHERE ELSE (`LISTENING_WIDTH`): a sentence read one way gives the pass nothing to
        # count, and reading everything this wide would cost the squared chart at every start.
        with composing_width(width or LISTENING_WIDTH):
            utterances = read_text(sentence, view)
        if len(utterances) == 1 and utterances[0].understood:
            # Every reading weighed as it is (`unpacked`): what the listener counts is each meaning's evidence.
            readings = unpacked(utterances[0].readings, view)
            found = weighed(readings, view, heard=await listening((readings,)))
            taught = meaning.canonical()
            if len(found) > 1 and any(w.reading.meaning.canonical() == taught for w in found):
                for w in found:
                    for evidence, level in listening_levels(w).items():
                        counts[(evidence, level, w.reading.meaning.canonical() == taught)] += 1
        if give_way is not None:
            await give_way()
    return counts


async def heard(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None, *,
                context: Iterable[str] = ()) -> Optional[Reading]:
    """Which reading was meant, as a listener with memory at hand takes it: memory asked first (`listening`), then
    `meant`. Every place that reads where it can wait for memory listens this way."""
    return meant(readings, inventory, heard=await listening((readings,), context))


async def heard_which(texts: Sequence[str], inventory: Optional[PatternInventory] = None, *,
                      context: Iterable[str] = ()) -> Optional[str]:
    """Which of several ways of hearing what was said was said, as a listener takes it: when words in it sound
    alike ("to", "two", "too"), the ear hands on every way it can be heard, and a person takes the one that makes
    sense. In this order: the ways whose every utterance reads; of those, the one whose meaning memory holds more
    firmly; then the one with the higher activation, as `meant` adds it: how often its words have been met meaning
    that, and how much what it says is connected to the rest of what was said and to `context` (what was talked of
    before). None when no way reads, or the evidence does not tell two apart: then what was said is not all
    understood, and is asked about, never guessed."""
    read: List[Tuple[str, Tuple[Reading, ...]]] = []
    for text in dict.fromkeys(texts):
        utterances = read_text(text, inventory)
        if utterances and all(u.understood for u in utterances):
            read.append((text, tuple(u.readings for u in utterances)))
    if len(read) < 2:
        return read[0][0] if read else None
    heard_all = await listening([r for _, ways in read for r in ways], context)
    view = inventory if inventory is not None else _live_inventory()
    facts: Set[Tuple[str, str, str, bool]] = set()
    terms: Set[str] = set()
    taken: List[Tuple[str, Tuple[Reading, ...]]] = []
    for text, ways in read:
        chosen = tuple(meant(r, inventory, heard=heard_all) for r in ways)
        if any(c is None for c in chosen):
            continue
        taken.append((text, chosen))
        for c in chosen:
            for fact in listening_facts(c.meaning):
                facts.add(held_key(fact))
                terms.update(fact.terms())
    if len(taken) < 2:
        return taken[0][0] if taken else None
    from core.agents.memory_agent import memory_agent
    known, near, _ = await memory_agent().listening_evidence(facts, terms, list(context))

    def evidence(item) -> Tuple[int, float]:
        _, chosen = item
        meant_facts = [f for c in chosen for f in listening_facts(c.meaning)]
        # What the rest is connected to adds to how often the words were met, as in `meant`: one activation.
        return (sum(known.get(held_key(f), 0) for f in meant_facts),
                round(sum(near.get(t, 0.0) for f in meant_facts for t in f.terms())
                      + sum(math.log1p(view.uses(k)) for c in chosen for k in c.constructions
                            if isinstance(k, (Lexical, Phrase))), 6))

    ranked = sorted(taken, key=evidence, reverse=True)
    return ranked[0][0] if evidence(ranked[0]) != evidence(ranked[1]) else None


def stated(text: str, inventory: Optional[PatternInventory] = None) -> Tuple[MeaningFact, ...]:
    """What a text states outright between named things: the asserted facts of each utterance that reads, to one
    meaning, as a telling. A question or a request states nothing; a conditional states none of its facts; of
    alternatives, none is stated, only that one holds; a fact still naming an unknown or the situation has nothing
    here to name it by; and an utterance whose meaning the listener cannot tell (`meant`) states nothing.

    Read with no memory at hand: where a word names several things, only how often each has been met tells them
    apart. Where the reading can wait for memory, `heard_stated` asks it first."""
    return _stated_in(read_text(text, inventory), inventory, None)


async def heard_stated(text: str, inventory: Optional[PatternInventory] = None, *,
                       context: Iterable[str] = ()) -> Tuple[MeaningFact, ...]:
    """What a text states outright, as `stated`, taken as a listener with memory at hand takes it: where a word
    names several things, memory is asked which each was meant to name (`listening`), against the rest of the text
    and `context`."""
    utterances = read_text(text, inventory)
    return _stated_in(utterances, inventory, await listening([u.readings for u in utterances], context))


def _stated_in(utterances, inventory, heard: Optional[Heard]) -> Tuple[MeaningFact, ...]:
    out: List[MeaningFact] = []
    for utterance in utterances:
        chosen = meant(utterance.readings, inventory, heard=heard)
        if chosen is None:
            continue
        meaning = chosen.meaning
        if meaning.act != "tell" or meaning.condition:
            continue
        out.extend(f for f in meaning.asserted
                   if not f.alternative and not is_variable(f.subject) and not is_variable(f.obj))
    return tuple(out)


def _slot_values(pattern: Pattern, meaning: Meaning) -> List[Dict[str, str]]:
    """Every way of putting this meaning's concepts in the pattern's slots that gives exactly this meaning."""
    slots = pattern.slots
    if not slots or pattern.meaning.act != meaning.act or len(pattern.meaning.facts) != len(meaning.facts):
        return []
    target = meaning.canonical()
    out = []
    for combo in itertools.product(sorted(meaning.constants()), repeat=len(slots)):
        values = dict(zip(slots, combo))
        filled = _fill(pattern.meaning, values)
        if filled is not None and filled.canonical() == target:
            out.append(values)
    return out


@dataclass(frozen=True)
class _Placed:
    """A phrase said in a frame's slot, with what stands in its own slots: the reader's composition (`_composed`),
    said."""

    phrase: Phrase
    fillers: Mapping[str, Lexical]


def _spelled_out(form: Tuple[FormElement, ...], fillers: Mapping[str, Union[Lexical, _Placed]],
                 space_after: Optional[bool] = None) -> Iterator[Tuple[FormElement, bool, Optional[Lexical]]]:
    """A form's pieces and slots in order, each slot with its filler, and how each is spaced; a slot a phrase fills
    is the phrase's own pieces and slots, in its place, the last spaced as the slot was."""
    for at, element in enumerate(form):
        spaced = space_after if space_after is not None and at == len(form) - 1 else element.space_after
        filler = fillers[element.name] if isinstance(element, Slot) else None
        if isinstance(filler, _Placed):
            yield from _spelled_out(filler.phrase.form, filler.fillers, spaced)
        else:
            yield element, spaced, filler


def _compositions(view: PatternInventory, meaning: Meaning, *, nested: bool = False
                  ) -> Iterator[Tuple[Pattern, List[Tuple[Union[Pattern, Phrase], str, Phrase]], List[Dict[str, str]]]]:
    """Every way of saying this meaning with a frame and a phrase in one of its slots, composed as reading composes
    them (`_composed`): the frame, where each phrase stands (the frame's slot, and with `nested` a slot of that
    phrase holding another), and the concept for every other slot, the frame's first, then each phrase's. A phrase
    standing for a thing, in a slot the frame uses as a thing's kind, describes that thing: "sleeps in the house" in
    "The ?slot0 ?slot1." is a sleeping, and in the house. With `nested`, as reading reads one phrase inside another:
    "The fip did not chase the kelt.", "chase the ?slot1" in "did not ?slot0", in "The ?slot0 ?slot1.". A phrase is
    tried only where it states the kinds of fact the frame leaves unstated (`frames_keeping`, `phrases_stating`)."""
    wanted = _fact_kinds(meaning.facts)
    kinds = list(wanted.items())
    # A phrase says part of this meaning only where the meaning names all it names (`phrases_stating`).
    within = frozenset(t for f in meaning.facts for t in f.terms() if not is_variable(t))
    for kept in _held_within(view.kinds_kept(meaning.act), wanted, [k for k, _ in kinds]):
        chains = (_phrases_holding_phrases(view, wanted - kept, within) if nested
                  else [(p, None, None) for p in view.phrases_stating(wanted - kept, within) if view.counts(p)])
        if not chains:
            continue
        for frame, slot in view.frames_keeping(meaning.act, kept):
            if not view.counts(frame):
                continue
            for phrase, inside, held in chains:
                shift = {s: slot_name(len(frame.slots) + at) for at, s in enumerate(phrase.slots)}
                filling = _Filling(shift.get(phrase.anchor, phrase.anchor),
                                   tuple(f.renamed(shift) for f in phrase.facts), (phrase,))
                deeper: Dict[str, str] = {}
                if held is not None:
                    deeper = {s: slot_name(len(frame.slots) + len(phrase.slots) + at) for at, s in enumerate(held.slots)}
                    composed = _composed(filling.facts, filling.anchor, {shift[inside]: _Filling(
                        deeper.get(held.anchor, held.anchor), tuple(f.renamed(deeper) for f in held.facts), (held,))})
                    if composed is None:
                        continue
                    filling = _Filling(composed[0], composed[1], (phrase, held))
                template = _composed_meaning(frame.meaning, {slot: filling})
                if template is None:
                    continue
                for values in _template_values(template, meaning):
                    found = [{s: values.get(s) for s in frame.slots if s != slot},
                             {s: values.get(shift[s]) for s in phrase.slots if s != inside}]
                    layers: List[Tuple[Union[Pattern, Phrase], str, Phrase]] = [(frame, slot, phrase)]
                    if held is not None:
                        found.append({s: values.get(deeper[s]) for s in held.slots})
                        layers.append((phrase, inside, held))
                    if all(None not in each.values() for each in found):
                        yield frame, layers, found


def _phrases_holding_phrases(view: PatternInventory, kinds: Counter,
                             within: Optional[AbstractSet[str]] = None) -> List[Tuple[Phrase, str, Phrase]]:
    """The phrases stating some of these kinds of fact, each with a slot it uses only as its thing's kind and a phrase
    linked there, as it was read ("did not ?slot0", its slot, "?slot0 the ?slot1"; "?slot0 ?slot1", "might", the
    same). Whether the two say the rest is the composed meaning's to tell: they may state one fact both, as reading
    reads them ("did not" and "chase the", each a "before now"). Where their words meet is what was heard there
    (`_unheard`): "did not chase", heard, before "did not chased", only like what was heard ("has not barked")."""
    out: List[Tuple[Phrase, str, Phrase]] = []
    seen: Set[str] = set()
    kind = ("instance_of", True)
    counted = list(kinds.items())
    # Each phrase states a kind of thing (one `instance_of` more) and some of these kinds (`_held_within`).
    one = Counter({kind: 1})
    for rest in _held_within(view.kinds_stated_of_a_thing(), kinds, [k for k, _ in counted]):
        outer = rest + one
        for phrase in view.phrases_stating(outer, within):
            if phrase.key in seen or not view.counts(phrase):
                continue
            seen.add(phrase.key)
            for slot in phrase.slots:
                uses = [f for f in phrase.facts if slot in f.terms()]
                if uses and all(f.relation == "instance_of" and f.obj == slot and f.subject == phrase.anchor
                                and f.positive for f in uses):
                    out.extend((phrase, slot, inside) for inside in view.fillers(phrase.key, slot)
                               if isinstance(inside, Phrase) and (within is None or _named_in(inside) <= within)
                               and view.counts(inside))
    return out


@functools.lru_cache(maxsize=None)
def _of_any_part(relation: str) -> bool:
    """Whether a relation relates concepts of any part, each as it is (`RelationSpec.of_any_part`)."""
    from core.semantics.relation_types import get_spec
    try:
        return get_spec(SemanticRelation(relation)).of_any_part
    except ValueError:
        return False


def _named_in(phrase: "Phrase") -> FrozenSet[str]:
    """Every concept a phrase names itself: the terms of its facts, and its anchor, that are no variable or slot."""
    named = {t for f in phrase.facts for t in f.terms() if not is_variable(t)}
    if not is_variable(phrase.anchor):
        named.add(phrase.anchor)
    return frozenset(named)


def _own_words(phrase: "Phrase") -> Tuple[str, ...]:
    """A phrase's own words, folded, in order, its marks aside: "had them"."""
    return tuple(_fold(e.text) for e in phrase.form if isinstance(e, Piece) and not _is_mark(e.text))


def _kinds_named(phrase: "Phrase") -> FrozenSet[str]:
    """The kinds a phrase names a thing of its own as ("compiled them", a compiling)."""
    return frozenset(f.obj for f in phrase.facts if f.relation == "instance_of" and f.positive
                     and f.subject == phrase.anchor and not is_variable(f.obj))


def _held_within(held: Mapping[FrozenSet[Tuple[Tuple[str, bool], int]], Counter], wanted: Counter,
                 order: Sequence[Tuple[str, bool]]) -> List[Counter]:
    """THE SETS OF KINDS OF FACT HELD (`held`) THAT ARE PART OF WHAT IS WANTED, in the order counting through every part
    of it comes to them (each kind of `order` from none to all, the first slowest), by whichever is fewer: its parts or
    the sets held. Saying a meaning counted through every part of its kinds, held or not: a meaning of 30 facts of ten
    kinds has millions of parts, and counted twice, one inside the other, more than ever finished (UNDERSTANDS-PROSE-02
    on main, 2026-10-26: "In mountainous areas, heavy precipitation is possible where ..." read as asking, its "I do not
    know" said for over half an hour). Only a part some frame or phrase states is ever used, and those are gone
    through, the same ones in the same order."""
    parts = 1
    for k in order:
        parts *= wanted[k] + 1
        if parts > len(held):
            break
    if parts <= len(held):
        out = []
        for counts in itertools.product(*(range(wanted[k] + 1) for k in order)):
            part = Counter({k: n for k, n in zip(order, counts) if n})
            if frozenset(part.items()) in held:
                out.append(part)
        return out
    found = [(tuple(part.get(k, 0) for k in order), part) for part in held.values()
             if all(n <= wanted.get(k, 0) for k, n in part.items())]
    found.sort(key=lambda each: each[0])
    return [part for _, part in found]


def _fact_kinds(facts: Iterable[MeaningFact]) -> Counter:
    """How many facts of each kind, denied or not, a construction states."""
    return Counter((f.relation, f.positive) for f in facts)


def _template_values(template: Meaning, meaning: Meaning) -> List[Dict[str, str]]:
    """Every way of putting this meaning's concepts in a composed meaning's slots that gives exactly this meaning; a
    slot takes only a concept the meaning holds where the template holds the slot."""
    if len(template.facts) != len(meaning.facts):
        return []
    slots = sorted(template.slots())
    choices = []
    for slot in slots:
        held: Optional[Set[str]] = None
        for f in template.facts:
            for at, term in enumerate((f.subject, f.obj)):
                if term == slot:
                    here = {(g.subject, g.obj)[at] for g in meaning.facts
                            if g.relation == f.relation and g.positive == f.positive}
                    held = here if held is None else held & here
        held = {t for t in held or () if not is_variable(t)}
        if not held:
            return []
        choices.append(sorted(held))
    target = meaning.canonical()
    out = []
    for combo in itertools.product(*choices):
        values = dict(zip(slots, combo))
        filled = _fill(template, values)
        if filled is not None and filled.canonical() == target:
            out.append(values)
    return out


def _rendered(pattern: Pattern, fillers: Mapping[str, Union[Lexical, _Placed]],
              view: Optional[PatternInventory] = None) -> Tuple[Piece, ...]:
    """The frame's pieces with its fillers in place, a phrase's with its own (`_Placed`), written as the writing
    asks: a capital begins the sentence, a filler's capital that only ever began a sentence ("Milk") is not kept
    inside one, and a frame's word takes the shape the word after it asks ("an" before "ocelot"). Properties of the
    writing, as the reader sets them aside."""
    pieces: List[Piece] = []
    own: List[int] = []
    symbol_first = False
    for element, spaced, lexical in _spelled_out(pattern.form, fillers):
        if isinstance(element, Slot):
            filler = list(lexical.form)
            if not pieces:
                # Mathematics writes its symbols in their own case, first in a sentence or not: "x is 4.".
                value = str(lexical.value)
                symbol_first = _quantity(value) or (len(value) == 1 and value.isalpha() and value.islower())
            # A capital is kept where the word keeps one: a word held with one inside a sentence ("Monday"), a shape
            # of such a word ("Americans"), a concept's own name spelled with one ("Paris", "Bostonians"), or a day
            # written as English writes one ("October 6").
            if pieces and view is not None and filler[0].text[:1].isupper() \
                    and not view.is_proper(filler[0].text) \
                    and not any(view.is_proper(base) for base in view.names_of_shape(filler[0].text)) \
                    and not str(lexical.value)[:1].isupper() and not _temporal(str(lexical.value)):
                filler[0] = Piece(filler[0].text[:1].lower() + filler[0].text[1:], filler[0].space_after)
            pieces.extend(filler[:-1])
            pieces.append(Piece(filler[-1].text, spaced))
        else:
            own.append(len(pieces))
            pieces.append(element if spaced == element.space_after else Piece(element.text, spaced))
    # A frame's word is written in the shape the word after it asks: "An ocelot" through "A ?slot0 is a ?slot1.".
    for at in own if view is not None else ():
        if at + 1 < len(pieces) and pieces[at + 1].text[:1].isalpha() and view.variants_of(pieces[at].text):
            word = pieces[at].text
            shape = view.shape_before(word, pieces[at + 1].text[:1])
            if shape != _fold(word):
                pieces[at] = Piece(shape.capitalize() if word[:1].isupper() else shape, pieces[at].space_after)
    if pieces and pieces[0].text[:1].islower() and not symbol_first:
        pieces[0] = Piece(pieces[0].text[:1].upper() + pieces[0].text[1:], pieces[0].space_after)
    return tuple(pieces)


def _begins_with_structure(view: PatternInventory, lexical: Lexical) -> bool:
    words = _loose(lexical.words)
    return bool(words) and len(words) > 1 and view.names_nothing(words[0])


def _said_fillers(view: PatternInventory, pattern: Union[Pattern, Phrase], slot: str, value: str,
                  uses: Optional[Mapping[str, str]] = None,
                  named: Optional[Mapping[str, str]] = None,
                  apart: Optional[Collection[str]] = None, *,
                  first: Optional[bool] = None, after: Sequence[str] = ()) -> List[Tuple[Lexical, Optional[Link], str]]:
    """What may say one concept in one slot, as reading would take it there: a filler of that concept linked to the
    slot; with none linked, one of the slot's learned kind (the link proposed, never written); and when no filler
    names the concept at all, the concept's own name, as a word never seen is read as a new name.

    A NAME GIVEN APART (`apart`) is written as it is, as a name no filler holds: what is held under that name is
    another thing's (`say`).

    The writing is the slot's too. A filler begun by a word that names nothing ("A dog") does not go where the
    slot's own fillers never had one ("A ?slot0 eats ?slot1."), nor the other way round. Where a word is held both
    capitalized and not, the form written in the slot's place is preferred: a capital begins a sentence, and "Milk"
    is "milk" inside one. `first`: whether the slot begins the sentence, for a phrase's slot, which begins it only
    where the phrase does. `after`: the construction's own words right before where the slot stands (`_own_before`);
    a word linked to the slot and heard right after them is said there before any in the slot's shape: "chase", read
    in "did not chase the kelt" in a phrase holding "chased the blip", not "chased"."""
    if first is None:
        first = pattern.form.index(next(e for e in pattern.form if isinstance(e, Slot) and e.name == slot)) == 0
    shapes = view.filler_openings(pattern.key, slot)

    def stated(name: str) -> Optional[str]:
        # HOW A WORD IS USED, AS THE SOURCE SAYS ("furniture" uncounted), under the name itself, else by the word it
        # ends in: what the source read from real use outranks a guess from an ending, for a word no filler holds.
        words = str(name).split()
        if not words or not uses:
            return None
        # The word a name ends in, or the one before a word that builds frames inside it ("roll of tobacco", a roll).
        last = next((words[at - 1] for at in range(1, len(words)) if view.is_structure(words[at])), words[-1])
        return uses.get(_fold(" ".join(words))) or uses.get(_fold(last))

    def fits(lexical: Lexical) -> bool:
        return not shapes or _begins_with_structure(view, lexical) in shapes

    def written_here(candidates: List[Lexical]) -> List[Lexical]:
        placed = [lx for lx in candidates if lx.words and lx.words[0][:1].isupper() == first]
        return placed or candidates

    def as_named(candidates: List[Lexical]) -> List[Lexical]:
        # THE WORD THE CONCEPT WAS JUST CALLED BY (`named`), where it is among the words that may stand here: a
        # speaker says a thing with the word the other used for it. Asked about "the kennel", it is not answered
        # about "the dog house". With none, the word most used for it, however written ("dog", "Dog"): "dog", met
        # 350 times, not "domestic dog", met 5.
        word = (named or {}).get(value)
        same = [lx for lx in candidates if _loose(lx.words) == _loose(tuple(word.split()))] if word else []
        if same or not candidates:
            return same or candidates
        used_as: Dict[Tuple[str, ...], int] = {}
        for lx in candidates:
            used_as[_loose(lx.words)] = max(used_as.get(_loose(lx.words), 0), view.uses(lx))
        most = max(used_as.values())
        return [lx for lx in candidates if used_as[_loose(lx.words)] == most]

    def head(lexical: Lexical) -> str:
        # The word a name of several words is used as: its last, the one the rest describe ("domestic dog", a dog),
        # or the one before a word that builds frames inside it ("body of water", a body, not water).
        words = _loose(lexical.words)
        return next((words[at - 1] for at in range(1, len(words)) if view.is_structure(words[at])), words[-1])

    # THE SHAPE THE SLOT TAKES ("?slot0 are ?slot1." takes plurals): a concept goes there written in it -- a form
    # held for it ("Geese"), or its name changed as the learned shape changes names -- and a concept's own name
    # goes where the slot's fillers are names as they are.
    taken = view.shape_of_slot(pattern.key, slot, said=True)

    def one_word(lexical: Lexical) -> bool:
        return len(_loose(lexical.words)) == 1

    def in_shape(lexical: Lexical) -> bool:
        if not one_word(lexical):
            return True
        # A word used only as a plural ("tongs") is written in the plural shape as it is; not one that says more than
        # its concept, wherever it stood ("swam", a swimming before now: "Tom wants swam.").
        word = _loose(lexical.words)[0]
        plural = view.used_as(lexical.words[0]) == "plural" and not view.says_more(
            word, str(lexical.value), doing=view.stands_as_doing(lexical))
        other = word != _fold(lexical.value) or plural
        if not taken:
            # Written as its name, where the slot's own are written so (`written_against`): not "kick" where only
            # "drank" and "ate" stand, each saying a doing before now ("The fip kick trel.").
            return not other and not view.written_against(pattern.key, slot, lexical)
        # Written other than its name, a word is in the slot's shape when the change is one the slot takes ("dogs"),
        # or it is held as a plural ("Geese", "Children"); not when it is another shape of the name ("reasoned" for
        # `reasoning` is no plural of it), nor another word for the thing: "everyone", held for `person`, is not
        # its plural ("Men are everyone.").
        if stated(word) in ("plural", "invariant"):
            return True        # one form for many as for one ("Alewives are fish."), as the source states
        change = view.shape_between(word, lexical.value)
        # A change of the slot's with the word's own last letter written again ("swimming": `ing`, the "m" of "swim"
        # doubled) is the slot's, as it is held against no slot (`word_against`).
        doubled = change is not None and any(
            change[1] == names and change[0].endswith(written) and len(change[0]) - len(written) == 1
            and _fold(lexical.value).endswith(change[0][0]) for written, names in taken)
        return other and (plural or (change is not None and (change in set(taken) or doubled)))

    def as_taken(name: str) -> Optional[str]:
        name = str(name).replace("_", " ").strip()
        if not taken:
            return name
        if " " in name:
            return None
        for written, names in taken:
            if _fold(name).endswith(names) and len(name) > len(names):
                return name[:len(name) - len(names)] + written
        return None

    held = [] if apart and value in apart else [lx for lx in view.lexicals_with_value(value) if view.counts(lx)]
    if _quantity(value):
        # A NUMBER OR A FORMULA IS WRITTEN AS ITS WRITING WRITES IT: never in a shape a slot's words take ("56s"),
        # and never as a word it was only taught to rank or name ("tenth" for 10). A word taught for it in this
        # slot says it; so does one written as mathematics writes it ("56", "x^2 + 1"); else its own writing.
        linked = [lx for lx in held if view.link_between(pattern.key, slot, lx.key) is not None and fits(lx)]
        if linked:
            return [(lx, view.link_between(pattern.key, slot, lx.key), "linked") for lx in written_here(linked)]
        written = [lx for lx in held if len(lx.words) == 1 and _quantity(lx.words[0])
                   and _named_as(lx.form) == value]
        if written:
            return [(lx, link(pattern, slot, lx), "kind") for lx in written]
        pieces = form_of(_number_written(value))
        return [(Lexical(pieces, value), link(pattern, slot, Lexical(pieces, value)), "new")] if pieces else []
    if _temporal(value):
        # A DAY OR A TIME OF DAY IS WRITTEN AS ENGLISH WRITES IT ("October 6", "7 p.m."), never as it is held
        # ("--10-06"): a word taught for it in this slot, else its writing.
        linked = [lx for lx in held if view.link_between(pattern.key, slot, lx.key) is not None and fits(lx)]
        if linked:
            return [(lx, view.link_between(pattern.key, slot, lx.key), "linked") for lx in written_here(linked)]
        pieces = form_of(_temporal_written(value))
        if not pieces:
            return []
        written = Lexical(pieces, value)
        # In a slot that has held days, a day is one of its kind ("on October 5" says "on October 6"); elsewhere
        # it stands as a word never held would.
        kind = classify_literal(value).kind
        alike = any(isinstance(lx, Lexical) and _temporal(str(lx.value))
                    and classify_literal(str(lx.value)).kind == kind
                    for lx in view.fillers(pattern.key, slot))
        return [(written, link(pattern, slot, written), "kind" if alike else "new")]
    linked = [lx for lx in held if view.link_between(pattern.key, slot, lx.key) is not None and fits(lx)]
    if linked:
        placed = ([lx for lx in linked if view.heard_there(after, lx.words[0])]
                  or [lx for lx in linked if in_shape(lx)] or linked)
        return [(lx, view.link_between(pattern.key, slot, lx.key), "linked") for lx in written_here(as_named(placed))]
    if held:
        # WHAT THE READER TAKES IN A SLOT, THE SAYER WRITES THERE (`_alike`): of the slot's kind, or of the class that
        # stands where its fillers do. Kind alone, a verb the lessons taught ("walk") was written in no slot
        # english_41's verbs filled, and WordNet's "To stroll is to walk." was not said, though it read.
        alike = _alike(view, pattern, slot)
        kind = [lx for lx in held if fits(lx) and alike(lx.key)]
        if taken:
            # A WORD NOT COUNTED TAKES NO SHAPE, as a name no filler holds takes none (below): "furniture" is not
            # "furnitures". A word already written in a shape is no word to shape: "swimming", standing bare as an
            # uncounted word does ("Tom likes swimming."), is the slot's own shape of `swim`.
            kind = [lx for lx in kind if not one_word(lx) or _loose(lx.words)[0] != _fold(str(lx.value))
                    or (stated(_loose(lx.words)[0]) or view.used_as(lx.words[0])) != "mass"]
        if not taken:
            # A held word stands, through a link proposed, only where words used as it is used stand: "smoke", used
            # without "a", not after one. One none of whose uses was counted ("plate", held only in "Plates are
            # round." and "the plate") is used as a word never held would be (`use_of`): not where only uncounted
            # words stand ("Shell plating is plate.").
            admits = view.slot_admits(pattern.key, slot)

            def used(word: str) -> str:
                # A WORD ONE IN BOTH ("fish", "deer"), as the source states, stands where one thing does or where
                # many do: the lessons' "Fish are animals." holds it plural, and cannot show it is also one.
                if stated(word) == "invariant":
                    return "count" if "count" in admits or "plural" not in admits else "plural"
                # WHAT THE SOURCE STATES OF THE THING SAID COMES BEFORE HOW THE WORD IS HELD; then how the word is
                # held for this thing; then for anything it names. Held over everything written with it, "matter",
                # counted for an affair, said "A substance is a matter." of what things are made of.
                return stated(word) or view.used_as(word, value) or view.used_as(word) \
                    or view.use_of(word if view.is_proper(word) else _fold(word))
            # A name of several words is used as its head is (`head`): "domestic dog", a dog, stands bare no more
            # than "dog" does ("I do not know where domestic dog is."). Where its source states the use of the
            # whole name, that stands: "military action" is not counted because "action" is.
            def used_whole(lexical: Lexical) -> str:
                whole = (uses or {}).get(" ".join(_loose(lexical.words)))
                return whole if whole and whole != "invariant" else used(head(lexical))
            # A NAME ONLY EVER PLURAL ("spectacles") stands where a slot takes a shape, as a name no filler holds
            # does (below): not after "every" ("Every spectacles is an optical instrument."). A plural of a name
            # ("Lynxes", for `lynx`) is no such name: the name is said ("A lynx is an animal.").
            def only_many(lexical: Lexical) -> bool:
                return used_whole(lexical) == "plural" and (
                    stated(head(lexical)) == "plural"
                    or _loose(lexical.words) == _loose(tuple(str(value).replace("_", " ").split())))
            kind = [lx for lx in kind if not _loose(lx.words)
                    or ((not admits or used_whole(lx) in admits) and not only_many(lx))]
        placed = [lx for lx in kind if in_shape(lx)]
        # THE WORD THE THING WAS CALLED BY, in the slot's shape, before another word held for it: "person" said of
        # many is "persons", not "everyone", which the lessons hold where plurals stand ("Everyone can swim.") and
        # which says no more of it than "Men are everyone.".
        called = (named or {}).get(value)

        def of_called(lexical: Lexical) -> bool:
            # The called word itself, or that word in a shape it was taught in ("Zanths" for "zanth"): not another
            # word for the thing ("everyone" for "person").
            words = _loose(lexical.words)
            return len(words) == 1 and (words == _loose((called,))
                                        or PatternInventory.shape_between(words[0], called) is not None)
        if taken and called and len(called.split()) == 1 and as_taken(called) \
                and not any(of_called(lx) for lx in placed):
            placed = []
        # Shaped as the concept's own name is written ("American" is "Americans"), or as it was called.
        written = next((lx.surface for lx in written_here(kind)
                        if one_word(lx) and _loose(lx.words)[0] == _fold(value)),
                       called if called and len(called.split()) == 1 else value)
        if kind and not placed and as_taken(written):
            shaped = Lexical(form_of(as_taken(written)), value)
            # THE WORD WRITTEN IS THE ONE THE SLOT MUST ADMIT. A filler admitted in its own shape ("Mice", a plural,
            # standing bare as in "Mice are small.") does not admit the concept's name written in its place: "mouse"
            # is counted, and a counted word does not stand where only names, mass words and plurals do ("Mouse is
            # a rodent.").
            if not taken and admits and one_word(shaped) and used(shaped.words[0]) not in admits:
                return []
            # Nor a name written as it is where the slot's own are written otherwise ("kick" beside "drank").
            if not taken and view.written_against(pattern.key, slot, shaped):
                return []
            return [(shaped, link(pattern, slot, shaped), "kind")]
        # A SLOT THAT TAKES A SHAPE says a word of its kind only in that shape. Unwritable in it ("chase", where only
        # "kicked" stands, for a chasing before now), the concept is said in another frame, never in another shape
        # ("The kelt chases the blip.").
        return [(lx, link(pattern, slot, lx), "kind")
                for lx in written_here(as_named(placed or ([] if taken else kind)))]
    # A CONCEPT NO FILLER NAMES goes, under its own name, only where words used as it is used go (`use_of`): a
    # name ("Thiosulfil") where names are held, never after "a"; a word used without "a" ("paleoanthropology")
    # where such words are; a plural already ("fire tongs") as it is, where plurals go; a counted thing after "a",
    # or in the slot's shape.
    spelled = str(value).replace("_", " ").strip()
    use = stated(spelled) or view.use_of(spelled)
    invariant = use == "invariant"
    if invariant:
        use = "count"          # one form for both, said of one
    admits = view.slot_admits(pattern.key, slot)
    if "thing" not in view._taken_at(pattern.key, slot):
        # HOW A WORD IS COUNTED IS A THING'S. Where the slot takes doings or qualities, the word's use as a noun
        # elsewhere says nothing of it there: "strike", held only for a labour strike and an attack, counted, kept
        # the verb out of "To peck is to strike.", and a verb held under no word could stand in no slot a verb
        # does (2026-10-12).
        use = None
        name = (as_taken(value) if taken else spelled)
    elif taken:
        # Said of many, a word one in both is as it is ("fish", not "fishs").
        name = spelled if use == "plural" or invariant else as_taken(value) if use == "count" else None
    elif use == "plural" or (admits and use not in admits):
        name = None
    else:
        name = spelled
    pieces = form_of(name) if name else ()
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    if not pieces or not _may_be_new(pieces, view, MAX_TERM_WORDS, given=bool(apart) and value in apart):
        return []
    new = Lexical(pieces, value)
    # Written as the slot's fillers are: no bare "shrub" where they all begin with "a" ("Every ?slot0 is ?slot1."
    # holding "a bird").
    if not fits(new):
        return []
    return [(new, link(pattern, slot, new), "new")]


def _number_written(value: str) -> str:
    """A number as it is written to be read: in groups of three from five digits on (18,446,744,073,709,551,616)."""
    if value.isdigit() and len(value) >= 5:
        return f"{int(value):,}"
    if value.startswith("-") and value[1:].isdigit() and len(value) >= 6:
        return f"-{int(value[1:]):,}"
    return value


def say(meaning: Meaning, inventory: Optional[PatternInventory] = None, *,
        uses: Optional[Mapping[str, str]] = None, named: Optional[Mapping[str, str]] = None,
        framed: Optional[Collection[str]] = None, apart: Optional[Collection[str]] = None,
        heard: bool = False) -> Tuple[str, ...]:
    """Every sentence that means exactly this, best first; empty when nothing taught says it.

    Said the way it would be read: a holophrase of this meaning, or a frame of it with a filler for each concept --
    linked to the slot, else of the slot's kind, else the concept's own name. The sentences rank as readings do:
    what they had to suppose, then score. Saying writes nothing. `uses`: how words no filler holds are used, where a
    source says (`count`, `mass`, `plural`), by the word a name ends in.

    A SPEAKER SAYS A THING AS THE OTHER DID (Brennan and Clark 1996; Pickering and Garrod 2004). `named`: the word
    each concept was just called by, said again where it may stand; with none, the word most used for it
    (`_said_fillers`). `framed`: the constructions the other's sentences were read with; of sentences supposing the
    same, one in such a frame comes first ("The dog is in the kennel.", asked back after it was told so, before
    "The dog is inside the kennel.").

    A NAME IS NOT THE THING ANOTHER SENSE OF IT NAMES. `apart`: the names in this meaning that a source wrote for
    a thing of its own (a hairdo it calls "wave"), where the view may hold that name for something else ("wave to",
    the greeting). Such a name is written as it is, as a name no filler holds, in a place the use its source states
    admits: not with the fillers, the links or the use of what is held under it. Said as held, the hairdo was "A
    wave to is a hairdo.", and what things are made of was "A substance is a matter.", as an affair is counted.

    SAID AS HEARD (`_unheard`). A sentence putting a word where nothing like it was heard is said only where no
    sentence for the meaning puts none so. `heard`: not even then, for a speaker with more than one meaning for what
    it says: an event held at no time, asked of at one, is said "The kelt might chase the fip.", at none, before "The
    kelt did might chase the fip.", at the time asked."""
    if inventory is None:
        # SAID BY THE GRAMMAR IT IS READ BY (`GrammarView.say`), as memory holds it: every sentence the grammar makes
        # of the meaning's words that reads back to exactly it. The constructions taught say what it does not yet say,
        # until it says all they do.
        from core.agents import memory_agent as _memory
        grammar = getattr(_memory._memory_agent, "grammar_view", None)
        if grammar is not None:
            by_grammar = tuple(grammar().say(meaning, named=named))
            if by_grammar:
                return by_grammar
    view = inventory if inventory is not None else _live_inventory()
    said = _said_whole(meaning, view, uses=uses, named=named, framed=framed, apart=apart, heard=heard)
    if said or not meaning.unasserted:
        return said
    # WHAT SOMEONE SAID, WHERE NO SENTENCE SAYS IT WHOLE ("Tom said that the dog barked." does): the sentence around
    # a quotation and the sentence quoted.
    return _said_with_quotation(meaning, view, uses=uses, named=named, framed=framed, apart=apart, heard=heard)


def as_known(facts: Iterable[MeaningFact], kinds: Mapping[str, str]) -> Tuple[MeaningFact, ...]:
    """Facts naming particulars (`kelt_1`, `kinds`: each particular's kind), as a sentence says them: each one a known
    thing, `given instance_of(?k0, kelt)`, so it is said "the kelt" (docs/TEACHING.md §12d)."""
    facts = tuple(facts)
    named = sorted({t for f in facts for t in f.terms() if t in kinds})
    taken = {t for f in facts for t in f.terms() if is_variable(t)}
    names: Dict[str, str] = {}
    for particular in named:
        index = 0
        while f"?k{index}" in taken:
            index += 1
        names[particular] = f"?k{index}"
        taken.add(names[particular])
    out = [MeaningFact("instance_of", names[p], kinds[p], given=True) for p in named]
    out += [f.renamed(names) for f in facts
            if not (f.relation == "instance_of" and f.subject in names and f.obj == kinds.get(f.subject) and f.positive)]
    return tuple(dict.fromkeys(out))


def _said_whole(meaning: Meaning, view: PatternInventory, *, uses: Optional[Mapping[str, str]],
                named: Optional[Mapping[str, str]], framed: Optional[Collection[str]],
                apart: Optional[Collection[str]], heard: bool = False) -> Tuple[str, ...]:
    """`say`: the sentences that say the meaning whole, best first."""
    target = meaning.canonical()
    best: Dict[str, Reading] = {}
    misfits: Dict[str, int] = {}
    unheard: Dict[str, Tuple[int, int]] = {}
    for holophrase in view.with_meaning(target):
        if view.counts(holophrase):
            best.setdefault(holophrase.surface, view.reading((holophrase,), (), holophrase.meaning))
    for pattern in view.item_based():
        if not view.counts(pattern):
            continue
        anchors = sum(1 for e in pattern.form if isinstance(e, Piece) and not _is_mark(e.text))
        for values in _slot_values(pattern, meaning):
            options = []
            for slot in pattern.slots:
                fitting = _said_fillers(view, pattern, slot, values[slot], uses, named, apart,
                                        after=_own_before([pattern], {}, 0, slot))
                if not fitting:
                    break
                options.append(fitting)
            else:
                for combo in itertools.product(*options):
                    new = tuple(lx for lx, _, how in combo if how == "new")
                    if not _anchored(new, anchors + sum(1 for _, _, how in combo if how != "new")):
                        continue
                    fillers = {s: lx for s, (lx, _, _) in zip(pattern.slots, combo)}
                    reading = view.reading((pattern,) + tuple(fillers[s] for s in pattern.slots),
                                           tuple(held for _, held, how in combo if how == "linked"), meaning,
                                           proposed=tuple(held for _, held, how in combo if how != "linked"),
                                           new=new)
                    surface = surface_of(_rendered(pattern, fillers, view))
                    if surface not in best or _best_first(reading) < _best_first(best[surface]):
                        best[surface] = reading
                        misfits[surface] = _misfits(view, pattern, fillers)
                        unheard[surface] = _unheard(view, pattern, fillers)
    # A FRAME WITH A PHRASE IN ONE SLOT, as reading composes one (`_compositions`): "The dog sleeps in the house."
    # through "The ?slot0 ?slot1." and "?slot0 in the ?slot1"; the phrase's slots filled as a frame's are, and its
    # new names anchored by its own words, as reading anchors them (`_new_here`). The phrase stands where it was
    # linked, or where it may be read (`_alike`) and stood beside the slot's own (`stood_beside`), as reading asks of
    # a frame with no word of its own: a kind alone is wide. And the word it writes in the slot's place is written as
    # the slot's own are (`written_against`). Reading supposes more, to read what it was never taught; said, "Some
    # of the ?slot0" went where "lives" goes ("Tom Some of the lives in the city."), and "chased the ?slot0" where
    # "live" goes ("The kelt does chased the blip.").
    def worded(construction: Union[Pattern, Phrase]) -> int:
        return sum(1 for e in construction.form if isinstance(e, Piece) and not _is_mark(e.text))

    # A PHRASE INSIDE A PHRASE, as reading reads one, only where a frame with one phrase says nothing.
    for nested in (False, True):
        if nested and best:
            break
        for frame, layers, values in _compositions(view, meaning, nested=nested):
            constructions: List[Union[Pattern, Phrase]] = [frame] + [phrase for _, _, phrase in layers]
            holds = {at: slot for at, (_, slot, _) in enumerate(layers)}
            joins: List[Optional[Link]] = []
            for container, slot, phrase in layers:
                joined = view.link_between(container.key, slot, phrase.key)
                if joined is None and not (_alike(view, container, slot)(phrase.key)
                                           and view.stood_beside(container.key, slot, phrase.key)):
                    break
                # The word the phrase writes first: its own, as the kind of thing it stands for ("chased", a
                # chasing), or its first slot's filler.
                head = phrase.form[0]
                kinds = [f.obj for f in phrase.facts if f.relation == "instance_of" and f.subject == phrase.anchor
                         and f.positive and not is_variable(f.obj)]
                if joined is None and isinstance(head, Piece) and len(kinds) == 1 \
                        and view.word_against(container.key, slot, _fold(head.text), _fold(kinds[0]).split()[-1]):
                    break
                joins.append(joined)
            else:
                # The place the sentence begins with: the first slot down the phrases the frame's first slot holds.
                begins: Optional[Tuple[int, str]] = None
                at = 0
                while isinstance(constructions[at].form[0], Slot):
                    name = constructions[at].form[0].name
                    if holds.get(at) == name:
                        at += 1
                        continue
                    begins = (at, name)
                    break
                places = [(at, construction, name, values[at][name]) for at, construction in enumerate(constructions)
                          for name in construction.slots if holds.get(at) != name]
                options = []
                for at, construction, name, value in places:
                    fitting = _said_fillers(view, construction, name, value, uses, named, apart,
                                            first=None if at == 0 else (at, name) == begins,
                                            after=_own_before(constructions, holds, at, name))
                    if not fitting:
                        break
                    options.append(fitting)
                else:
                    for combo in itertools.product(*options):
                        chosen = [(at, name, said) for (at, _, name, _), said in zip(places, combo)]
                        if not all(_anchored(tuple(lx for a, _, (lx, _, how) in chosen if a == at and how == "new"),
                                             worded(construction) + (1 if at == 0 else 0)
                                             + sum(1 for a, _, (_, _, how) in chosen if a == at and how != "new"))
                                   for at, construction in enumerate(constructions)):
                            continue
                        placed: Dict[int, _Placed] = {}
                        for at in range(len(constructions) - 1, 0, -1):
                            own: Dict[str, Union[Lexical, _Placed]] = {
                                name: lx for a, name, (lx, _, _) in chosen if a == at}
                            if at in holds:
                                own[holds[at]] = placed[at + 1]
                            placed[at] = _Placed(constructions[at], own)
                        fillers: Dict[str, Union[Lexical, _Placed]] = {
                            name: lx for a, name, (lx, _, _) in chosen if a == 0}
                        fillers[holds[0]] = placed[1]
                        written = False
                        for at, ((container, slot, phrase), joined) in enumerate(zip(layers, joins)):
                            head = phrase.form[0]
                            first = placed[at + 1].fillers.get(head.name) if isinstance(head, Slot) else None
                            if joined is None and isinstance(first, Lexical) \
                                    and view.written_against(container.key, slot, first):
                                written = True
                        if written:
                            continue
                        order: List[Construction] = []

                        def walk(at: int) -> None:
                            order.append(constructions[at])
                            given = fillers if at == 0 else placed[at].fillers
                            for name in constructions[at].slots:
                                if holds.get(at) == name:
                                    walk(at + 1)
                                else:
                                    order.append(given[name])
                        walk(0)
                        held_links = (tuple(held for _, _, (_, held, how) in chosen if how == "linked")
                                      + tuple(joined for joined in joins if joined))
                        proposed = (tuple(held for _, _, (_, held, how) in chosen if how != "linked")
                                    + tuple(link(container, slot, phrase)
                                            for (container, slot, phrase), joined in zip(layers, joins) if not joined))
                        # A WORD IN A PHRASE THAT SAYS MORE THAN THE MEANING HOLDS (`_unsaid`, as reading judges it)
                        # says something not meant, and is not said: "Tom asked Rex to opened the door.", "opened" a
                        # door opened before now, where the opening asked for is at no time. "The kelt chased the
                        # blip." holds its "before now".
                        if _unsaid(view, tuple(order), held_links + proposed, meaning):
                            continue
                        reading = view.reading(tuple(order), held_links, meaning, proposed=proposed,
                                               new=tuple(lx for _, _, (lx, _, how) in chosen if how == "new"))
                        surface = surface_of(_rendered(frame, fillers, view))
                        if surface not in best or _best_first(reading) < _best_first(best[surface]):
                            best[surface] = reading
                            misfits[surface] = _misfits(view, frame, fillers)
                            unheard[surface] = _unheard(view, frame, fillers)
    # A filler begun with a letter no word after the one before it has begun with ("an bird": only "eagle",
    # "owl", "ant" ... follow "an") is said last: how a word's form goes with the next word's, as taught.
    # Of sentences that suppose the same, one in a frame the speaker used comes first (`framed`).
    def spoken(reading: Reading) -> int:
        return 0 if framed and reading.constructions and reading.constructions[0].key in framed else 1

    # SAID AS HEARD (`_unheard`). What was heard preempts what was not (statistical preemption: Goldberg 2006; Boyd
    # and Goldberg 2011), word by word: where a sentence says the meaning with every word where words like it were
    # heard, none putting a word where nothing like it was is said: "Tom may opens the box.", "Rex kicked the ball
    # not.", "The fip does did not chase the kelt.". Of the rest, after what each supposes, the one with fewer words
    # heard only by their likeness first: "Tom might open the box.", taught, before "Tom may open the box.". A word
    # heard only by its likeness is how a learner says what it was never told ("A lynx is an animal.", where only
    # "Lynxes are animals." was), and is not set aside: "Tom owns a two dollars." is said last, "a" having been heard
    # before "million" and "thousand", of the kind "two" is, and nothing taught saying "two" is not their kind there.
    kept = {surface: reading for surface, reading in best.items() if not unheard.get(surface, (0, 0))[0]}
    if kept or heard:
        best = kept
    return tuple(surface for surface, _ in sorted(
        best.items(), key=lambda kv: (misfits.get(kv[0], 0), kv[1].supposed, unheard.get(kv[0], (0, 0)),
                                      spoken(kv[1]), -kv[1].score, -kv[1].uses, kv[1].key)))


def _said_with_quotation(meaning: Meaning, view: PatternInventory, **how: Any) -> Tuple[str, ...]:
    """A meaning holding what someone said, said as it is read: the sentence around a quotation, the quoted sentence
    in it (`Tom said, "The dog barked."`), its end a comma where words follow it (`"The dog barked," Tom said.`)."""
    try:
        around = Meaning(meaning.act, tuple(f for f in meaning.facts if not f.unasserted), meaning.asked)
        quoted = Meaning("tell", tuple(MeaningFact(f.relation, f.subject, f.obj, f.positive, f.condition, f.alternative,
                                                   given=f.given)
                                       for f in meaning.unasserted))
    except ValueError:
        return ()
    arounds = [s for s in say(around, view, **how) if QUOTED in s]
    quotes = say(quoted, view, **how)
    if not arounds or not quotes:
        return ()
    out = []
    for sentence in arounds:
        before, _, after = sentence.partition(QUOTED)
        said = quotes[0][:-1] + "," if after.strip()[:1].isalpha() and quotes[0].endswith(".") else quotes[0]
        out.append(f'{before}"{said}"{after}')
    return tuple(out)


def _own_before(constructions: Sequence[Union[Pattern, Phrase]], holds: Mapping[int, str], at: int,
                name: str) -> Tuple[str, ...]:
    """The own words right before where a slot stands, the last two at most: those of its construction, or, for a
    slot a phrase begins with, those before the place the phrase stands in (`holds`: of each construction, the slot
    holding the next), "did not" before "?slot0 the ?slot1". None where a filler or nothing stands before it."""
    while True:
        form = constructions[at].form
        index = next(i for i, e in enumerate(form) if isinstance(e, Slot) and e.name == name)
        words: List[str] = []
        for element in reversed(form[:index]):
            if not isinstance(element, Piece) or _is_mark(element.text) or element.text == QUOTED:
                break
            words.insert(0, element.text)
            if len(words) == 2:
                break
        if words or index or at == 0:
            return tuple(words)
        at, name = at - 1, holds[at - 1]


def _words_said(construction: Union[Pattern, Phrase], fillers: Mapping[str, Union[Lexical, _Placed]]
                ) -> Iterator[Tuple[Optional[str], Any, Optional[Lexical]]]:
    """The words a sentence says, in order: each with what wrote it (a construction, for its own words; the filler,
    for a filler's) and the filler, None for a construction's own word. A mark is `(None, None, None)`: it ends a
    run of words."""
    for element in construction.form:
        if isinstance(element, Piece):
            yield (None, None, None) if _is_mark(element.text) or element.text == QUOTED else (element.text,
                                                                                             construction, None)
            continue
        filler = fillers[element.name]
        if isinstance(filler, _Placed):
            yield from _words_said(filler.phrase, filler.fillers)
            continue
        for piece in filler.form:
            yield (None, None, None) if _is_mark(piece.text) else (piece.text, filler, filler)


def _unheard(view: PatternInventory, pattern: Pattern, fillers: Mapping[str, Union[Lexical, _Placed]]
             ) -> Tuple[int, int]:
    """Where a sentence puts its words against what was heard (`heard_like`): how many it puts where none like them
    was heard, and how many only where words like them were. Counted: a filler's first word right after another word
    ("Tom may opens the box.", where "go" and "fly" were heard after "may"), held against the two words before it
    where both are one construction's own ("The fip did not chased the kelt.", "chased" heard after "has not", never
    after "did not"); and a construction's own word right after another construction's ("The fip does did not chase
    the kelt."). A construction's own word after a filler is how a frame takes a word it never held ("Horses are
    animals."), and is not counted."""
    never = like = 0
    earlier: Optional[Tuple[str, Any, Optional[Lexical]]] = None
    before: Optional[Tuple[str, Any, Optional[Lexical]]] = None
    for word, owner, filler in _words_said(pattern, fillers):
        if word is None:
            earlier = before = None
            continue
        if before is not None and before[1] is not owner:
            if filler is not None:
                own = earlier is not None and earlier[2] is None and before[2] is None and earlier[1] is before[1]
                heard = view.heard_like(before[0], word, str(filler.value), earlier[0] if own else None)
                never, like = never + (heard == 2), like + (heard == 1)
            elif before[2] is None:
                heard = view.heard_after(before[0])
                never += bool(heard) and _fold(word) not in heard
        earlier, before = before, (word, owner, filler)
    return never, like


def _misfits(view: PatternInventory, pattern: Pattern, fillers: Mapping[str, Union[Lexical, _Placed]]) -> int:
    """How many fillers begin with a letter that no word held right after the frame's word before them begins with,
    a phrase's words and fillers counted where they stand."""
    count = 0
    elements = list(_spelled_out(pattern.form, fillers))
    for (here, _, _), (there, _, filler) in zip(elements, elements[1:]):
        if isinstance(here, Piece) and isinstance(there, Slot) and not _is_mark(here.text):
            letter = _fold(filler.words[0][:1]) if filler.words else ""
            seen = view.letters_after(here.text)
            if letter.isalpha() and seen and letter not in seen:
                count += 1
    return count


# ── Learning: what each repair would create ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Repair:
    """What one repair would add so the pair it was given can be read: new constructions, new links, and held
    constructions the pair supports although they are no longer believed."""

    name: str
    constructions: Tuple[Construction, ...] = ()
    links: Tuple[Link, ...] = ()
    revived: Tuple[Construction, ...] = ()


#: The repairs, in the order the paper tries them, each with the paper's name.
REPAIR_NAMES = {
    "add_links": "add-categorial-links",
    "item_based_lexical": "item-based → lexical",
    "phrase_in_slot": "item-based → phrase",
    "substitution": "holophrase → item-based + lexical + lexical (substitution)",
    "addition": "holophrase → item-based + lexical (addition)",
    "deletion": "holophrase → item-based + lexical + holophrase (deletion)",
    "lexical_item_based": "lexical → item-based",
    "holophrase": "nothing → holophrase",
}


def _new(view: PatternInventory, items: Iterable[Item]) -> Tuple[Item, ...]:
    seen, out = set(), []
    for item in items:
        if item.key not in view and item.key not in seen:
            seen.add(item.key)
            out.append(item)
    return tuple(out)


def _keeps_a_word(construction: Construction) -> bool:
    """Whether an item-based construction has a word of its own, not marks alone."""
    return not isinstance(construction, Pattern) or not construction.slots \
        or any(isinstance(e, Piece) and not _is_mark(e.text) for e in construction.form)


def _repair(name: str, view: PatternInventory, constructions: Iterable[Construction],
            links: Iterable[Link]) -> Optional[Repair]:
    """A repair's proposal: the constructions not held yet, the ones held but no longer believed (this pair
    supports them again), and the links not held yet.

    A FRAME WITH NO WORD OF ITS OWN ("?slot0 ?slot1.") IS LEARNED ONLY BY SUBSTITUTION: from two that differ in
    nothing but what stands there ("Dogs ?slot0." held, "Cats run." said), each place seen filled two ways. Read
    off one sentence, a mark alone anchors nothing: "Dogs bark." is no evidence that any two words make a sentence,
    and frames so learned took the place of the ones the lessons teach ("Cats sleep." stopped reading)."""
    constructions = tuple(constructions)
    if name != "substitution" and any(c.key not in view and not _keeps_a_word(c) for c in constructions):
        return None
    revived = tuple(c for c in constructions if c.key in view and not view.counts(view.get(c.key)))
    return Repair(name, _new(view, constructions), _new(view, links), revived)  # type: ignore[arg-type]


def _gives(pattern: Pattern, values: Mapping[str, str], meaning: Meaning) -> bool:
    filled = _fill(pattern.meaning, values)
    return filled is not None and filled.canonical() == meaning.canonical()


def add_links(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
              names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(i) The constructions that read the pair are held, and only their links are missing."""
    words = tuple(p.text for p in form)
    shaped = _written_shapes(view, words)[0]
    best = None
    for pattern in view.item_based():
        if not view.counts(pattern):
            continue
        for spans in _chunkings(pattern.form, words, shaped=shaped):
            frame = _as_written(pattern, words, spans, form)
            if frame is not pattern:
                # The frame as written is another construction: held, its links may be all that is missing; not
                # held, it is not a matter of links.
                frame = view.get(frame.key)
                if frame is None or not view.counts(frame):
                    continue
            options = []
            for start, end in spans:
                held = [lx for lx in view.lexicals_with_words(words[start:end]) if view.counts(lx)]
                if not held:
                    break
                options.append(held)
            else:
                for combo in itertools.product(*options):
                    values = {s: lx.value for s, lx in zip(frame.slots, combo)}
                    if not _gives(frame, values, meaning):
                        continue
                    missing = tuple(link(frame, s, lx) for s, lx in zip(frame.slots, combo)
                                    if view.link_between(frame.key, s, lx.key) is None)
                    if not missing:
                        continue
                    rank = (len(missing), -view.reading((frame,) + combo, (), meaning).score, frame.key)
                    if best is None or rank < best[0]:
                        best = (rank, missing)
    return Repair("add_links", links=best[1]) if best else None


def item_based_lexical(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
                       names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(ii) An item-based construction reads the pair but for what fills a slot: that filler is created, as a name
    reading could take as new (`_may_be_new`): "An ocelot" holds "an", a word that builds sentences, so "ocelot" is
    the name, in "A ?slot0 is a ?slot1." written as the sentence writes it."""
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    words = tuple(p.text for p in form)
    shaped = _written_shapes(view, words)[0]
    best = None
    for pattern in view.item_based():
        if not view.counts(pattern):
            continue
        for spans in _chunkings(pattern.form, words, shaped=shaped):
            # Read through a frame whose word it writes in another shape, the sentence teaches that frame as written.
            frame = _as_written(pattern, words, spans, form)
            frame = view.get(frame.key) or frame
            new_frame = () if frame.key in view else (frame,)
            # A frame held and no longer believed is one this pair supports again: given to `_repair`, it is revived.
            revives = frame.key in view and not view.counts(frame)
            for values in _slot_values(pattern, meaning):
                fillers, created = [], []
                for slot, (start, end) in zip(pattern.slots, spans):
                    held = [lx for lx in view.lexicals_with_words(words[start:end])
                            if lx.value == values[slot] and view.counts(lx)]
                    if not held and (not _may_be_new(form[start:end], view, MAX_TERM_WORDS,
                                                     given=_given_whole(words[start:end], values[slot], names))
                                     or _names_within(view, words[start:end], values[slot], names)):
                        break
                    # A NEW WORD FOR WHAT ANOTHER PLACE OF THE SENTENCE NAMES points back to it, and names nothing:
                    # "himself" in "Tom helped himself." is Tom because Tom did the helping. Held as a name of Tom,
                    # and of Rex after "Rex helped himself.", "Tom helped himself." also read as Tom helping Rex.
                    if not held and any(values[other] == values[slot] for other in pattern.slots if other != slot):
                        break
                    filler = held[0] if held else Lexical(form[start:end], values[slot])
                    if not held:
                        created.append(filler)
                    fillers.append((slot, filler))
                else:
                    # With every filler held, the frame as written is what the pair teaches ("An adult male is a
                    # kind of adult.", read through "A ?slot0 is a kind of ?slot1."). `add_links` leaves a frame
                    # not held alone; left here too, the pair went on to a frame built of its own words ("An
                    # ?slot0 ?slot1 is a kind of adult.").
                    if not created and not new_frame and not revives:
                        continue
                    links = tuple(link(frame, s, lx) for s, lx in fillers
                                  if view.link_between(frame.key, s, lx.key) is None)
                    rank = (len(created) + len(new_frame), len(links), -view.score(pattern), frame.key)
                    if best is None or rank < best[0]:
                        best = (rank, tuple(created) + (frame,), links)
    if best is None:
        return None
    return _repair("item_based_lexical", view, best[1], best[2])


def _given_whole(words: Sequence[str], concept: str, names: Optional[Mapping[str, str]] = None) -> bool:
    """Whether the teacher wrote this run of words as this concept's word (`names`, concept -> word). The word is
    taken as a sentence writes it: "ship's company" is "ship", "'s", "company"."""
    written = (names or {}).get(concept)
    return bool(written) and _loose(tuple(p.text for p in form_of(str(written)))) == _loose(tuple(words))


def _names_within(view: PatternInventory, words: Sequence[str], concept: str,
                  names: Optional[Mapping[str, str]] = None) -> bool:
    """Whether a run of several words holds, as part of it, a word or run held as a name of this very concept ("All
    birds", where "birds" names `bird`): the rest is not part of the name, and belongs to the frame.

    NOT WHERE THE TEACHER WROTE THE RUN AS THE CONCEPT'S WORD (`names`, concept -> word). WordNet writes `computer`
    "electronic computer" as well as "computer"; taken apart, "electronic" went into the frame ("An electronic ?slot0
    is a kind of ?slot1.": an electronic dog, a kind of animal), "electronic device" could then be no name, and "A
    mouse is an electronic device." taught no word of the mouse. A new word beside a held name of the concept is
    the same to the learner in "All birds" and in "electronic computer"; only the teacher knows which is a name."""
    if _given_whole(words, concept, names):
        return False
    for start in range(len(words)):
        for end in range(start + 1, len(words) + 1):
            if end - start == len(words):
                continue
            part = tuple(words[start:end])
            if any(lx.value == concept for lx in view.lexicals_with_words(_loose(part), loose=True)):
                return True
            if len(part) == 1 and concept in view.names_of_shape(part[0]):
                return True
    return False


def _common_ends(a: Tuple[str, ...], b: Tuple[str, ...]) -> Tuple[int, int]:
    prefix = 0
    while prefix < min(len(a), len(b)) and a[prefix] == b[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(a), len(b)) - prefix
           and a[len(a) - 1 - suffix] == b[len(b) - 1 - suffix]):
        suffix += 1
    return prefix, suffix


def _shape(fact: MeaningFact) -> Tuple[str, bool, bool, bool, bool, bool, str, str]:
    return (fact.relation, fact.positive, fact.condition, fact.alternative, fact.unasserted, fact.given,
            "?" if is_variable(fact.subject) and not _named(fact.subject) else fact.subject,
            "?" if is_variable(fact.obj) and not _named(fact.obj) else fact.obj)


def _role(fact: MeaningFact) -> Tuple[str, bool, bool, bool, bool, bool]:
    """What a fact can only be compared with: the same link kind, the same polarity, on the same side of an `if`,
    an alternative only with an alternative, what is not told as so only with what is not, and what is taken as
    known only with what is."""
    return (fact.relation, fact.positive, fact.condition, fact.alternative, fact.unasserted, fact.given)


def _similar_first(view: PatternInventory, words: Tuple[str, ...], meaning: Meaning) -> List[Pattern]:
    """The held holophrases to generalize from, most alike first: the ones sharing the most form or meaning, and
    among equals the one with the higher score."""
    shapes = {_shape(f) for f in meaning.facts}

    def rank(holophrase: Pattern):
        prefix, suffix = _common_ends(holophrase.words, words)
        shared = prefix + suffix + len({_shape(f) for f in holophrase.meaning.facts} & shapes)
        return (-shared, -view.score(holophrase), holophrase.key)

    return sorted((h for h in view.holophrases() if view.counts(h)), key=rank)


# Meanings are compared with the substrate's Plotkin generalizer (rule_induction.anti_unify), over facts paired up
# one to one. A concept is handed to it as a plain token, so any concept's name can be compared.

def _encoded(fact: MeaningFact, tokens: Dict[str, str]):
    from core.learning.rule_induction import Fact

    def term(t: str) -> str:
        if is_variable(t):
            return t
        return tokens.setdefault(t, f"k{len(tokens)}")

    predicate = fact.relation if fact.positive else f"not_{fact.relation}"
    predicate = f"or_{predicate}" if fact.alternative else predicate
    predicate = f"if_{predicate}" if fact.condition else predicate
    predicate = f"given_{predicate}" if fact.given else predicate
    return Fact(f"unasserted_{predicate}" if fact.unasserted else predicate, (term(fact.subject), term(fact.obj)))


def _pairings(left: Tuple[MeaningFact, ...], right: Tuple[MeaningFact, ...]) -> Iterator[Tuple[int, ...]]:
    """Every one-to-one pairing of the left facts with right facts of the same relation, polarity, side of an `if`
    and standing as an alternative or not."""
    def walk(i: int, used: Tuple[int, ...]):
        if i == len(left):
            yield used
            return
        for j, fact in enumerate(right):
            if j not in used and _role(fact) == _role(left[i]):
                yield from walk(i + 1, used + (j,))
    yield from walk(0, ())


def _substitution(held: Meaning, observed: Meaning) -> Optional[Tuple[Meaning, str, str]]:
    """Two meanings that differ in exactly one concept: the meaning they share, with `?slot0` where the concept
    was, and the two concepts. Unknowns may be named differently; the situation's variables may not differ."""
    if held.act != observed.act or len(held.facts) != len(observed.facts) or len(held.asked) != len(observed.asked):
        return None
    from core.learning.rule_induction import anti_unify
    for pairing in _pairings(held.facts, observed.facts):
        tokens: Dict[str, str] = {}
        pairs = [(_encoded(held.facts[i], tokens), _encoded(observed.facts[j], tokens))
                 for i, j in enumerate(pairing)]
        result = anti_unify(pairs)
        if result is None:
            continue
        generalized, table = result
        concept = {v: k for k, v in tokens.items()}
        constants = [(a, b, v) for (a, b), v in table.items() if a in concept and b in concept]
        renamings = [(a, b, v) for (a, b), v in table.items() if is_variable(a) and is_variable(b)]
        if len(constants) != 1 or len(constants) + len(renamings) != len(table):
            continue
        if any(_named(a) or _named(b) for a, b, _ in renamings):
            continue
        if len({a for a, _, _ in renamings}) != len(renamings) or len({b for _, b, _ in renamings}) != len(renamings):
            continue
        renaming = {b: a for a, b, _ in renamings}
        if tuple(renaming.get(v, v) for v in observed.asked) != held.asked:
            continue
        a, b, variable = constants[0]
        names = {variable: slot_name(0), **{v: x for x, _, v in renamings}}
        facts = []
        for fact, original in zip(generalized, held.facts):
            subject, obj = (names.get(t, concept.get(t, t)) for t in fact.args)
            facts.append(MeaningFact(original.relation, subject, obj, original.positive, original.condition,
                                     original.alternative, original.unasserted, original.given))
        try:
            shared = Meaning(held.act, tuple(facts), held.asked)
        except ValueError:
            continue
        return shared, concept[a], concept[b]
    return None


def _embedding(small: Meaning, large: Meaning) -> Optional[Dict[str, str]]:
    """A renaming of the small meaning's unknowns under which every one of its facts is a fact of the large one,
    or None. The situation's variables and every concept stay as they are."""
    if small.act != large.act:
        return None

    def walk(i: int, names: Dict[str, str], used: Tuple[int, ...]) -> Optional[Dict[str, str]]:
        if i == len(small.facts):
            return names
        fact = small.facts[i]
        for j, other in enumerate(large.facts):
            if j in used or _role(other) != _role(fact):
                continue
            trial = dict(names)
            fits = True
            for mine, theirs in zip(fact.terms(), other.terms()):
                if not is_variable(mine) or _named(mine):
                    fits = mine == theirs
                elif mine in trial:
                    fits = trial[mine] == theirs
                else:
                    fits = (is_variable(theirs) and not _named(theirs)
                            and theirs not in trial.values())
                    trial[mine] = theirs
                if not fits:
                    break
            if fits:
                found = walk(i + 1, trial, used + (j,))
                if found is not None:
                    return found
        return None

    names = walk(0, {}, ())
    if names is None:
        return None
    if tuple(names.get(v, v) for v in small.asked) != large.asked:
        return None
    return names


def _extension(small: Meaning, large: Meaning) -> Optional[str]:
    """The one concept the large meaning adds to the small one, when it adds facts that bring exactly one concept
    the small meaning lacks; otherwise None."""
    names = _embedding(small, large)
    if names is None or len(large.facts) <= len(small.facts):
        return None
    image = {f.renamed(names) for f in small.facts}
    extra = [f for f in large.facts if f not in image]
    added = {t for f in extra for t in f.terms() if not is_variable(t)} - small.constants()
    if len(added) != 1:
        return None
    (value,) = added
    if value in {t for f in image for t in f.terms()}:
        return None
    return value


def _open_matches(partial: Tuple[MeaningFact, ...], slot: str, target: Tuple[MeaningFact, ...]
                  ) -> Iterator[Tuple[Dict[str, str], FrozenSet[int]]]:
    """Every way the facts of a construction still holding one open slot are facts of `target`, one to one and each
    only with its own kind of fact: the slot may stand for any term, an unknown only for an unknown of the target,
    and everything else only for itself. Yields the renaming and which target facts it used."""
    def walk(i: int, names: Dict[str, str], used: FrozenSet[int]):
        if i == len(partial):
            yield dict(names), used
            return
        fact = partial[i]
        for j, other in enumerate(target):
            if j in used or _role(other) != _role(fact):
                continue
            trial = dict(names)
            fits = True
            for mine, theirs in zip(fact.terms(), other.terms()):
                if mine == slot:
                    fits = trial.setdefault(slot, theirs) == theirs
                elif is_variable(mine) and not _named(mine):
                    if mine in trial:
                        fits = trial[mine] == theirs
                    else:
                        fits = (is_variable(theirs) and not _named(theirs)
                                and theirs not in {v for k, v in trial.items() if k != slot})
                        trial[mine] = theirs
                else:
                    fits = mine == theirs
                if not fits:
                    break
            if fits:
                yield from walk(i + 1, trial, used | {j})
    yield from walk(0, {}, frozenset())


def _tied(about: str, facts: Sequence[MeaningFact], outside: FrozenSet[str]) -> bool:
    """Whether every one of these facts is about `about`, or about an unknown of their own the others tie to it:
    "two hundred and six" is a number whose addends are 6 and a number, that one's factors 2 and 100. A fact not
    about `about` names nothing of `outside`, what the rest of the sentence names; and none names an unknown the rest
    of the sentence names, since a phrase's unknowns are its own: "helped herself" from "The girl helped herself.",
    holding the girl as an unknown, would point "herself" at nobody."""
    reached, left = {about}, list(facts)
    while True:
        tied = [f for f in left if reached & set(f.terms())]
        if not tied:
            return not left
        for fact in tied:
            if about not in fact.terms() and outside & set(fact.terms()):
                return False
            if any(is_variable(t) and not _named(t) and t != about and t in outside for t in fact.terms()):
                return False
            reached.update(t for t in fact.terms() if is_variable(t) and not _named(t) and t not in outside)
            left.remove(fact)


def _what_the_slot_adds(pattern: Pattern, values: Mapping[str, str], slot: str,
                        meaning: Meaning) -> Optional[Tuple[str, Tuple[MeaningFact, ...], bool]]:
    """What the pair's meaning says through one slot of a construction whose other slots hold `values`: the anchor
    the slot stands for and the facts about it that nothing else in the construction states -- a phrase's meaning.
    None when the construction does not otherwise give the pair's meaning, or what is left is not about the slot's
    thing.

    Where the construction uses the slot only as a thing's kind (`instance_of(?x, ?slot0)`), the phrase stands for
    the thing: it is a `?slot0` and whatever else is said of it. Elsewhere it stands for what fills the slot. Last,
    whether it says anything of a thing of its own besides (`_tied`): such a phrase is one held phrases compose, never
    one learned whole."""
    if pattern.meaning.act != meaning.act:
        return None
    partial = tuple(f.renamed(values) for f in pattern.meaning.facts)
    uses = [f for f in pattern.meaning.facts if slot in f.terms()]
    as_kind = bool(uses) and all(f.relation == "instance_of" and f.obj == slot and f.subject != slot and f.positive
                                 and not f.alternative for f in uses) and len({f.subject for f in uses}) == 1
    for names, used in _open_matches(partial, slot, meaning.facts):
        if tuple(names.get(v, v) for v in pattern.meaning.asked) != meaning.asked or slot not in names:
            continue
        extra = [f for j, f in enumerate(meaning.facts) if j not in used]
        if not extra or any(f.alternative for f in extra):
            continue
        if as_kind:
            thing, kind = names.get(uses[0].subject, uses[0].subject), names[slot]
            if is_variable(kind) or not is_variable(thing):
                continue
            about, anchor = thing, "?n"
            facts = (MeaningFact("instance_of", "?n", kind, given=uses[0].given),)
        else:
            about = names[slot]
            anchor = "?n" if is_variable(about) and not _named(about) else about
            facts = ()
        # A fact about the slot's thing belongs to it; one about an unknown only tied to it belongs to it when it
        # names nothing the rest of the construction names: "Only ?slot0" does not say what "can ?slot1" says, nor
        # "?slot0 tried to" what the event "?slot0 ?slot1 the ?slot2." is.
        outside = frozenset(pattern.meaning.constants() | set(values.values())
                            | {t for j, f in enumerate(meaning.facts) if j in used for t in f.terms()
                               if t != about})
        if not _tied(about, extra, outside) or any(f.condition != extra[0].condition for f in extra):
            continue
        facts += tuple(MeaningFact(f.relation, anchor if f.subject == about else f.subject,
                                   anchor if f.obj == about else f.obj, f.positive, f.condition, f.alternative,
                                   f.unasserted, f.given) for f in extra)
        return anchor, facts, any(about not in f.terms() for f in extra)
    return None


def _phrase_constants(anchor: str, facts: Iterable[MeaningFact]) -> FrozenSet[str]:
    """The concepts a phrase names: in its facts, and what it stands for when that is one."""
    return frozenset({t for f in facts for t in f.terms() if not is_variable(t)}
                     | (set() if is_variable(anchor) else {anchor}))


def _phrase_repair(form: Tuple[Piece, ...], anchor: str, facts: Tuple[MeaningFact, ...],
                   view: PatternInventory, *, composed: bool = False
                   ) -> Optional[Tuple[Phrase, Tuple[Construction, ...], Tuple[Link, ...]]]:
    """A phrase pair learned as a sentence pair is: read by a held phrase (nothing to create); or generalized over
    the held fillers it contains, a phrase with a slot for each (lexical → item-based, at the phrase's scale); or,
    when neither applies, held whole. Returns the phrase that stands for it, what to create, and its links.

    One that says something of a second thing (`composed`: "two hundred and six", a number with a number in it) is
    learned only as held phrases compose it, links and all; none, when they do not: "had barked", a barking and a time
    before now, is the sentence's to learn, not a phrase held whole."""
    target = _phrase_canonical(anchor, facts)
    for filling in _phrase_fillings(view, form, 0, len(form), _Chart(), extend=False, loose=False):
        if _phrase_canonical(filling.anchor, filling.facts) == target:
            return filling.constructions[0], (), ()                  # type: ignore[return-value]
    # Held phrases read it, and only their links are missing (`add_links`, at a phrase's scale): "two hundred and
    # six", where "?slot0 and ?slot1" has held "a hundred" in its first slot and "?slot0 ?slot1" reads "two hundred".
    linked = [filling for filling in _phrase_fillings(view, form, 0, len(form), _Chart(), extend=True, loose=False)
              if filling.proposed and not filling.new and all(c.key in view for c in filling.constructions)
              and _phrase_canonical(filling.anchor, filling.facts) == target]
    if linked:
        fewest = min(linked, key=lambda filling: (len(filling.proposed), filling.constructions[0].key))
        return fewest.constructions[0], (), tuple(fewest.proposed)   # type: ignore[return-value]
    if composed:
        return _joined(form, anchor, facts, target, view)
    # A held phrase reads it but for what one of its slots holds: words nothing holds as the concept the pair has
    # left, or holds as another (`item_based_lexical`, at a phrase's scale). "has flown", where "has ?slot0" reads
    # "has barked" and "flown" is the pair's `fly`; "will snow", where "snow" is held as the stuff and the pair's is
    # `snowing`.
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    wanted = _phrase_constants(anchor, facts)
    for filling in _phrase_fillings(view, form, 0, len(form), _Chart(), extend=True, loose=False):
        if len(filling.new) > 1 or filling.constructions[0].key not in view:
            continue
        have = _phrase_constants(filling.anchor, filling.facts)
        missing, other = wanted - have, have - wanted
        if len(missing) != 1 or len(other) != 1:
            continue
        (concept,), (was,) = missing, other
        words = [c for c in filling.constructions[1:] if isinstance(c, Lexical) and c.value == was]
        if len(words) != 1 or not _may_be_new(words[0].form, view, MAX_TERM_WORDS) \
                or not all(c.key in view for c in filling.constructions if c is not words[0]):
            continue
        named = {was: concept}
        if _phrase_canonical(named.get(filling.anchor, filling.anchor),
                             (f.renamed(named) for f in filling.facts)) != target:
            continue
        word, made = words[0], Lexical(words[0].form, concept)
        links = tuple(Link(l.pattern, l.slot, made.key, l.pattern_surface, made.surface)
                      for l in filling.links + filling.proposed if l.lexical == word.key)
        links += tuple(l for l in filling.proposed if l.lexical != word.key)
        return filling.constructions[0], (made,), links              # type: ignore[return-value]
    concepts = frozenset({t for f in facts for t in f.terms() if not is_variable(t)} | (
        set() if is_variable(anchor) else {anchor}))
    chosen, written = _covering_fillers(view, form, concepts)
    if chosen:
        elements: List[FormElement] = []
        at = 0
        for index, (start, end, _lexical) in enumerate(chosen):
            elements.extend(form[at:start])
            elements.append(Slot(slot_name(index), form[end - 1].space_after))
            at = end
        elements.extend(form[at:])
        names = {lx.value: slot_name(i) for i, (_, _, lx) in enumerate(chosen)}
        try:
            general = Phrase(tuple(elements), names.get(anchor, anchor), tuple(f.renamed(names) for f in facts))
        except ValueError:
            general = None
        if general is not None:
            gives = _composed(general.facts, general.anchor,
                              {slot_name(i): _Filling(lx.value, (), (lx,)) for i, (_, _, lx) in enumerate(chosen)})
            if gives is not None and _phrase_canonical(gives[0], gives[1]) == target:
                fillers = {slot_name(i): lx for i, (_, _, lx) in enumerate(chosen)}
                widened = _phrase_substitution(general, fillers, view)
                if widened is not None:
                    phrase, made, links = widened
                    return phrase, (phrase,) + tuple(written) + made, links
                return general, (general,) + tuple(written), tuple(link(general, slot, lx)
                                                                   for slot, lx in fillers.items())
    try:
        whole = Phrase(form, anchor, facts)
    except ValueError:
        return None
    return whole, (whole,), ()


def _node_of(part: _Filling, facts: Tuple[MeaningFact, ...], values: Mapping[str, str], anchor: str,
             taken: Set[str]) -> Optional[Tuple[str, FrozenSet[int]]]:
    """Where a held reading of some of a phrase's words stands in the pair's meaning: the term it stands for and
    the facts it says there. A number stands for the unknown the pair builds to its value ("two thousand" for the
    unknown whose factors are 2 and 1000), or for itself where the pair names it; anything else for the unknown its
    own facts, renamed, are facts of the pair about."""
    if not part.facts:
        for node, value in values.items():
            if value == part.anchor and node != anchor and node not in taken:
                return node, _built_from(node, facts)
        if part.anchor in {f.obj for f in facts} and part.anchor not in taken:
            return part.anchor, frozenset()
        return None
    if not is_variable(part.anchor):
        return None
    try:
        names = _embedding(Meaning("tell", part.facts), Meaning("tell", facts))
    except ValueError:
        return None
    if names is None or part.anchor not in names or names[part.anchor] in taken or names[part.anchor] == anchor:
        return None
    said = {f.renamed(names) for f in part.facts}
    return names[part.anchor], frozenset(j for j, f in enumerate(facts) if f in said)


def _built_from(node: str, facts: Tuple[MeaningFact, ...]) -> FrozenSet[int]:
    """The facts that build a number from numbers, down from one unknown: its addends or factors, and theirs."""
    out: Set[int] = set()
    pending = [node]
    while pending:
        here = pending.pop()
        for j, f in enumerate(facts):
            if f.subject == here and f.relation in _ARITHMETIC and j not in out:
                out.add(j)
                if is_variable(f.obj) and not _named(f.obj):
                    pending.append(f.obj)
    return frozenset(out)


def _joined(form: Tuple[Piece, ...], anchor: str, facts: Tuple[MeaningFact, ...], target: str,
            view: PatternInventory) -> Optional[Tuple[Phrase, Tuple[Construction, ...], Tuple[Link, ...]]]:
    """A phrase whose parts held constructions read, joined by nothing held: "two thousand five hundred", where
    "?slot0 ?slot1" reads "two thousand" and "five hundred" as products and nothing held adds them. What is learned
    joins them: a phrase with a slot for each part and the pair's own words between, saying of its slots what the
    pair says of the things the parts stand for -- here, that its anchor is their sum. It is learned only where it
    gives the pair's meaning back, composed with the parts' held readings; a part is read strictly, as held, and at
    least one is a phrase of held phrases, so single words are left to the covering fillers."""
    n = len(form)
    chart = _Chart()
    values, _ = _valued(facts)

    def readings(a: int, b: int) -> List[_Filling]:
        out = [f for f in _phrase_fillings(view, form, a, b, chart, extend=False, loose=False)
               if not f.proposed and not f.new]
        if b - a == 1:
            out += [_Filling(lx.value, (), (lx,)) for lx in view.lexicals_with_words((form[a].text,))
                    if view.counts(lx)]
        return out

    def covers(at: int, parts: Tuple[Tuple[int, int], ...], words: Tuple[int, ...]):
        if at == n:
            if len(parts) >= 2 and any(b - a > 1 for a, b in parts):
                yield parts, words
            return
        for end in range(n, at, -1):
            if (end - at < n) and readings(at, end):
                yield from covers(end, parts + ((at, end),), words)
        if not _is_mark(form[at].text):
            yield from covers(at + 1, parts, words + (at,))

    for parts, words in covers(0, (), ()):
        options = [readings(a, b) for a, b in parts]
        for combo in itertools.islice(itertools.product(*options), 64):
            taken: Set[str] = set()
            gone: Set[int] = set()
            renames: Dict[str, str] = {}
            for index, part in enumerate(combo):
                placed = _node_of(part, facts, values, anchor, taken)
                if placed is None:
                    break
                node, said = placed
                taken.add(node)
                gone |= said
                renames[node] = slot_name(index)
            else:
                own = tuple(f.renamed(renames) for j, f in enumerate(facts) if j not in gone)
                if not own:
                    continue
                elements: List[FormElement] = []
                at = 0
                for index, (a, b) in enumerate(parts):
                    elements.extend(form[at:a])
                    elements.append(Slot(slot_name(index), form[b - 1].space_after))
                    at = b
                elements.extend(form[at:])
                try:
                    joining = Phrase(tuple(elements), anchor, own)
                except ValueError:
                    continue
                gives = _composed(joining.facts, joining.anchor,
                                  {slot_name(i): part for i, part in enumerate(combo)})
                if gives is None or _phrase_canonical(gives[0], gives[1]) != target:
                    continue
                held = view.get(joining.key)
                joining = held if held is not None else joining
                links = tuple(link(joining, slot_name(i), part.constructions[0]) for i, part in enumerate(combo)
                              if view.link_between(joining.key, slot_name(i), part.constructions[0].key) is None)
                return joining, (() if held is not None else (joining,)), links
    return None


def _phrase_substitution(general: Phrase, fillers: Mapping[str, Lexical], view: PatternInventory
                         ) -> Optional[Tuple[Phrase, Tuple[Construction, ...], Tuple[Link, ...]]]:
    """Substitution at a phrase's scale: a held phrase differs from this one in one word of its own and one concept
    ("?slot0 slowly" and "?slot0 loudly", `slow` and `loud`): the phrase with a slot there too, a filler for each
    word, and the links for the pair's fillers and both words. None when no held phrase differs so."""
    def constants(phrase: Phrase) -> set:
        found = {term for f in phrase.facts for term in f.terms() if not is_variable(term)}
        return found | ({phrase.anchor} if not is_variable(phrase.anchor) else set())

    def same(a: FormElement, b: FormElement) -> bool:
        if isinstance(a, Slot) or isinstance(b, Slot):
            return isinstance(a, Slot) and isinstance(b, Slot) and a.name == b.name
        return _fold(a.text) == _fold(b.text)

    for held in view.phrases():
        # Whether a phrase is held at all is asked of memory, the costliest test, so last.
        if held.key == general.key or len(held.form) != len(general.form) or held.anchor != general.anchor \
                or not view.counts(held):
            continue
        differ = [i for i, (a, b) in enumerate(zip(held.form, general.form)) if not same(a, b)]
        if len(differ) != 1 or not all(isinstance(x.form[differ[0]], Piece) for x in (held, general)):
            continue
        at = differ[0]
        if _is_mark(held.form[at].text) or _is_mark(general.form[at].text):
            continue
        mine, theirs = constants(held) - constants(general), constants(general) - constants(held)
        if len(mine) != 1 or len(theirs) != 1:
            continue
        (was,), (now,) = mine, theirs
        if {f.renamed({was: _HERE}) for f in held.facts} != {f.renamed({now: _HERE}) for f in general.facts}:
            continue
        probe = general.form[:at] + (Slot(_HERE, general.form[at].space_after),) + general.form[at + 1:]
        names = {e.name: slot_name(k) for k, e in enumerate(e for e in probe if isinstance(e, Slot))}
        try:
            widened = Phrase(tuple(Slot(names[e.name], e.space_after) if isinstance(e, Slot) else e for e in probe),
                             names.get(general.anchor, general.anchor),
                             tuple(f.renamed({now: _HERE}).renamed(names) for f in general.facts))
            pair = tuple(
                next((lx for lx in view.lexicals_with_words((piece.text,)) if lx.value == concept and view.counts(lx)),
                     None) or Lexical((piece,), concept)
                for piece, concept in ((held.form[at], was), (general.form[at], now)))
        except ValueError:
            continue
        links = tuple(link(widened, names[slot], lx) for slot, lx in fillers.items()) \
            + tuple(link(widened, names[_HERE], lx) for lx in pair)
        return widened, pair, links
    return None


def _points_back(phrase: Phrase, pieces: Tuple[Piece, ...], named: Iterable[str]) -> bool:
    """Whether a phrase holds, as its own, a concept another place of its sentence names (`named`) while none of its
    own words names it: then its words point back to that place ("itself"), and say nothing of the concept."""
    own = {t for f in phrase.facts for t in f.terms() if not is_variable(t)}
    if not is_variable(phrase.anchor):
        own.add(phrase.anchor)
    written = " ".join(_loose(tuple(p.text for p in pieces)))
    return any(concept in own and _fold(str(concept).replace("_", " ")) not in written for concept in set(named))


def phrase_in_slot(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
                   names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(ii b) An item-based construction reads the pair but for one slot, whose words say more than one concept: what
    the pair's meaning adds there is a phrase pair, learned as one (`_phrase_repair`) and linked to the slot. A
    sentence pair can yield a phrase pair, and a phrase is read inside the slots of every construction that takes
    it, so what is learned once in a slot is used in every slot of its kind."""
    words = tuple(p.text for p in form)
    concepts = meaning.constants()
    shaped = _written_shapes(view, words)[0]
    for pattern in view.item_based():
        if not view.counts(pattern):
            continue
        for spans in _chunkings(pattern.form, words, shaped=shaped):
            frame = _as_written(pattern, words, spans)
            frame = view.get(frame.key) or frame
            for open_index, open_slot in enumerate(pattern.slots):
                others = [(slot, span) for slot, span in zip(pattern.slots, spans) if slot != open_slot]
                options = []
                for slot, (start, end) in others:
                    held = [lx for lx in view.lexicals_with_words(words[start:end])
                            if view.counts(lx) and lx.value in concepts]
                    if not held:
                        break
                    options.append(held)
                else:
                    for combo in itertools.product(*options):
                        values = {slot: lx.value for (slot, _), lx in zip(others, combo)}
                        adds = _what_the_slot_adds(pattern, values, open_slot, meaning)
                        if adds is None:
                            continue
                        start, end = spans[open_index]
                        learned = _phrase_repair(form[start:end], adds[0], adds[1], view, composed=adds[2])
                        if learned is None:
                            continue
                        phrase, created, links = learned
                        # A PHRASE THAT HOLDS WHAT ANOTHER PLACE OF THE SENTENCE NAMES, with no word of its own for
                        # it, points back to that place: "hurt itself", after "The cat", is a hurting done to the one
                        # who did it, not to cats. Held as it was read once, "The dog hurt itself." read as the dog
                        # hurting the cat.
                        if _points_back(phrase, form[start:end], values.values()):
                            continue
                        slot_links = tuple(link(frame, slot, lx) for (slot, _), lx in zip(others, combo)
                                           if view.link_between(frame.key, slot, lx.key) is None)
                        if view.link_between(frame.key, open_slot, phrase.key) is None:
                            slot_links += (link(frame, open_slot, phrase),)
                        # A frame held and no longer believed is one this pair supports again: given to `_repair`, it
                        # is revived.
                        if not created and not slot_links and not links and view.counts(frame):
                            continue
                        return _repair("phrase_in_slot", view, tuple(created) + (frame,), links + slot_links)
    return None


def substitution(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
                 names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(iii) A held holophrase differs from the pair in one place of its form and one concept of its meaning: an
    item-based construction with a slot there, a filler for each side, and their two links."""
    words = tuple(p.text for p in form)
    for held in _similar_first(view, words, meaning):
        prefix, suffix = _common_ends(held.words, words)
        mine = held.form[prefix:len(held.form) - suffix]
        theirs = form[prefix:len(form) - suffix]
        if not mine or not theirs:
            continue
        shared = _substitution(held.meaning, meaning)
        if shared is None:
            continue
        generalized, concept_held, concept_observed = shared
        # Neither filler is a held name of its concept with other words ("All birds", where "birds" names `bird`).
        if _names_within(view, tuple(p.text for p in mine), concept_held) \
                or _names_within(view, tuple(p.text for p in theirs), concept_observed, names):
            continue
        try:
            pattern = Pattern(held.form[:prefix] + (Slot(slot_name(0), mine[-1].space_after),)
                              + held.form[len(held.form) - suffix:], generalized)
            fillers = (Lexical(mine, concept_held), Lexical(theirs, concept_observed))
        except ValueError:
            continue
        if not (_gives(pattern, {slot_name(0): concept_held}, held.meaning)
                and _gives(pattern, {slot_name(0): concept_observed}, meaning)):
            continue
        return _repair("substitution", view, (pattern,) + fillers,
                       (link(pattern, slot_name(0), f) for f in fillers))
    return _frame_substitution(form, meaning, view, names=names)


#: The slot a frame substitution opens, before the frame's slots are named again by their place.
_HERE = slot_name(99)


def _frame_substitution(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
                        names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """Substitution from a held item-based construction: it differs from the pair in one word of its own, and its
    meaning, filled with the pair's other fillers, differs from the pair's in the one concept that word names ("The
    ?slot0 is bigger than the ?slot1." and "The bird is smaller than the dog."). The construction with a slot there
    too, a filler for each word, and the links that read the pair. The one held most alike first, as for a
    holophrase: most of its own words in the pair, then the higher score."""
    words = tuple(p.text for p in form)
    present = set(words)

    def own_words(pattern: Pattern) -> List[int]:
        return [i for i, e in enumerate(pattern.form) if isinstance(e, Piece) and not _is_mark(e.text)]

    frames = []
    for held in view.item_based():
        own = own_words(held)
        shared = sum(1 for i in own if held.form[i].text in present)
        if view.counts(held) and own and shared >= len(own) - 1:
            frames.append((-shared, -view.score(held), held.key, held))
    for _, _, _, held in sorted(frames):
        for i in own_words(held):
            if held.form[i].text in present and sum(1 for w in words if w == held.form[i].text) >= \
                    sum(1 for j in own_words(held) if held.form[j].text == held.form[i].text):
                continue                       # this word is in the pair: it is not the one that differs
            here = Slot(_HERE, held.form[i].space_after)
            probe = held.form[:i] + (here,) + held.form[i + 1:]
            order = [e.name for e in probe if isinstance(e, Slot)]
            for spans in _chunkings(probe, words):
                where = dict(zip(order, spans))
                values, fillers = {}, {}
                for slot in held.slots:
                    start, end = where[slot]
                    found = [lx for lx in view.lexicals_with_words(words[start:end]) if view.counts(lx)]
                    if not found:
                        break
                    values[slot], fillers[slot] = found[0].value, found[0]
                else:
                    bound = _fill(held.meaning, values)
                    shared = _substitution(bound, meaning) if bound is not None else None
                    if shared is None:
                        continue
                    _, concept_held, concept_observed = shared
                    if concept_held not in held.meaning.constants():
                        continue
                    slots = {name: slot_name(k) for k, name in enumerate(order)}
                    generalized = _renamed(_renamed(held.meaning, {concept_held: _HERE}) or held.meaning, slots) \
                        if concept_held in held.meaning.constants() else None
                    if generalized is None:
                        continue
                    start, end = where[_HERE]
                    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
                    if not view.lexicals_with_words(words[start:end]) \
                            and (not _may_be_new(form[start:end], view, MAX_TERM_WORDS,
                                                 given=_given_whole(words[start:end], concept_observed, names))
                                 or _names_within(view, words[start:end], concept_observed, names)):
                        continue               # a name reading could take as new, as `item_based_lexical` asks
                    try:
                        pattern = Pattern(tuple(Slot(slots[e.name], e.space_after) if isinstance(e, Slot) else e
                                                for e in probe), generalized)
                        # A filler held for the word and its concept is the one linked; one is made where none is.
                        pair = tuple(
                            next((lx for lx in view.lexicals_with_words(tuple(p.text for p in pieces))
                                  if lx.value == concept and view.counts(lx)), None) or Lexical(pieces, concept)
                            for pieces, concept in (((held.form[i],), concept_held),
                                                    (form[start:end], concept_observed)))
                    except ValueError:
                        continue
                    given = {slots[s]: v for s, v in values.items()}
                    if not (_gives(pattern, {**given, slots[_HERE]: concept_observed}, meaning)
                            and _gives(pattern, {**given, slots[_HERE]: concept_held}, bound)):
                        continue
                    links = [link(pattern, slots[_HERE], f) for f in pair]
                    links += [link(pattern, slots[s], f) for s, f in fillers.items()]
                    # The held construction is this one with its word in place, so what stood in its slots stands in
                    # the same slots here: "Dogs ?slot0." held "bark" and "swim", and "?slot0 ?slot1." holds them too.
                    links += [link(pattern, slots[s], f) for s in held.slots for f in view.fillers(held.key, s)
                              if f.key != fillers.get(s, f).key or s not in fillers]
                    return _repair("substitution", view, (pattern,) + pair, links)
    return None


def _insertion(short: Tuple[str, ...], long: Tuple[str, ...]) -> Optional[Tuple[int, int]]:
    """Where the long form has one run of words the short one lacks, and is otherwise the same: (start, end) in
    the long form."""
    if len(long) <= len(short):
        return None
    prefix, suffix = _common_ends(short, long)
    if prefix + suffix != len(short):
        return None
    return prefix, len(long) - suffix


def addition(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
             names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(iv) The pair adds to a held holophrase one run of words and facts bringing one concept: an item-based
    construction with a slot there, a filler, and its link."""
    words = tuple(p.text for p in form)
    for held in _similar_first(view, words, meaning):
        span = _insertion(held.words, words)
        if span is None:
            continue
        value = _extension(held.meaning, meaning)
        if value is None:
            continue
        start, end = span
        generalized = _renamed(meaning, {value: slot_name(0)})
        if generalized is None:
            continue
        try:
            pattern = Pattern(form[:start] + (Slot(slot_name(0), form[end - 1].space_after),) + form[end:],
                              generalized)
            filler = Lexical(form[start:end], value)
        except ValueError:
            continue
        if not _gives(pattern, {slot_name(0): value}, meaning):
            continue
        return _repair("addition", view, (pattern, filler), (link(pattern, slot_name(0), filler),))
    return None


def deletion(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
             names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(v) The pair lacks, of a held holophrase, one run of words and the facts bringing one concept: a holophrase
    for the pair, and from the held one an item-based construction with a slot there, a filler, and its link."""
    words = tuple(p.text for p in form)
    for held in _similar_first(view, words, meaning):
        span = _insertion(words, held.words)
        if span is None:
            continue
        value = _extension(meaning, held.meaning)
        if value is None:
            continue
        start, end = span
        generalized = _renamed(held.meaning, {value: slot_name(0)})
        if generalized is None:
            continue
        try:
            pattern = Pattern(held.form[:start] + (Slot(slot_name(0), held.form[end - 1].space_after),)
                              + held.form[end:], generalized)
            filler = Lexical(held.form[start:end], value)
            whole = Pattern(form, meaning)
        except ValueError:
            continue
        if not _gives(pattern, {slot_name(0): value}, held.meaning):
            continue
        return _repair("deletion", view, (whole, pattern, filler), (link(pattern, slot_name(0), filler),))
    return None


def _held_filler(view: PatternInventory, pieces: Tuple[Piece, ...], concepts: FrozenSet[str],
                 used: Iterable[str], *, loose: bool = False) -> Optional[Tuple[Lexical, bool]]:
    """The best held filler for these words naming one of `concepts` not used yet, and whether it must be created.
    With `loose`, a filler held only in another case ("Writing", begun a sentence), or a held word written in a
    productive shape ("Hats" for "hat"), is the same word written another way, so the word as written here is taken
    as a filler of that concept too."""
    words = tuple(p.text for p in pieces)
    used = set(used)

    def usable(candidates):
        return sorted((lx for lx in candidates if view.counts(lx) and lx.value in concepts and lx.value not in used),
                      key=lambda lx: (-view.score(lx), lx.key))

    if not loose:
        exact = usable(view.lexicals_with_words(words))
        return (exact[0], False) if exact else None
    if _parted(pieces):
        return None
    folded = usable(view.lexicals_with_words(_loose(words), loose=True))
    if folded:
        return Lexical(pieces, folded[0].value), True
    # A held word written in a shape learned from the fillers ("Hats", where "hat" is held): the same word, as
    # written here.
    if len(words) == 1:
        for name in view.names_of_shape(words[0]):
            shaped = usable(view.holding(name))
            if shaped:
                return Lexical(pieces, shaped[0].value), True
    return None


def _covering_fillers(view: PatternInventory, form: Tuple[Piece, ...],
                      concepts: FrozenSet[str]) -> Tuple[List[Tuple[int, int, Lexical]], List[Lexical]]:
    """Held fillers covering parts of these words, from the left, each the longest that names a concept of the
    meaning not named yet. Fillers held as written are found first, over the whole sentence; only then, for concepts
    still unnamed and in words still uncovered, a filler held in another case is taken as the same word written
    here. Returns the fillers with where they stand, and the ones to create."""
    words = tuple(p.text for p in form)
    chosen: List[Tuple[int, int, Lexical]] = []
    created: List[Lexical] = []
    used = set()
    for loose in (False, True):
        covered = {k for start, end, _ in chosen for k in range(start, end)}
        at = 0
        while at < len(words):
            if at in covered:
                at += 1
                continue
            found = None
            for end in range(len(words), at, -1):
                if any(k in covered for k in range(at, end)):
                    continue
                held = _held_filler(view, form[at:end], concepts, used, loose=loose)
                if held is not None:
                    found = (at, end, held[0], held[1])
                    break
            if found is None:
                at += 1
                continue
            begin, stop, filler, create = found
            chosen.append((begin, stop, filler))
            if create:
                created.append(filler)
            used.add(filler.value)
            covered.update(range(begin, stop))
            at = stop
    # A NUMBER OR A FORMULA WRITTEN HERE IS A FILLER, never a word of the construction: what its writing names is a
    # concept of the pair, and the construction has a slot where it stands ("?slot0 = ?slot1.", never
    # "1 + 5 = ?slot0.").
    covered = {k for start, end, _ in chosen for k in range(start, end)}
    for at, piece in enumerate(form):
        if at in covered or not _quantity(_named_as((piece,))):
            continue
        value = _named_as((piece,))
        if value in concepts and value not in used:
            filler = Lexical((piece,), value)
            chosen.append((at, at + 1, filler))
            created.append(filler)
            used.add(value)
    # SO IS A DAY OR A TIME OF DAY, in one word or several ("October 5", "7:30 p.m."): what its writing names is a
    # concept of the pair, and the construction has a slot where it stands ("?slot0 walked on ?slot1.", never
    # "?slot0 walked on October 5."). The longest run that writes one is taken.
    covered = {k for start, end, _ in chosen for k in range(start, end)}
    at = 0
    while at < len(form):
        found = None
        for end in range(min(len(form), at + 5), at, -1):
            if any(k in covered for k in range(at, end)):
                continue
            value = _named_as(form[at:end])
            if _temporal(value) and value in concepts and value not in used:
                found = (end, Lexical(form[at:end], value))
                break
        if found is None:
            at += 1
            continue
        end, filler = found
        chosen.append((at, end, filler))
        created.append(filler)
        used.add(filler.value)
        covered.update(range(at, end))
        at = end
    chosen.sort(key=lambda item: item[0])
    return chosen, created


def lexical_item_based(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
                       names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(vi) Held fillers cover parts of the pair: an item-based construction with a slot for each, several at once,
    and their links."""
    chosen, created = _covering_fillers(view, form, meaning.constants())
    if not chosen:
        return None
    elements: List[FormElement] = []
    at = 0
    for index, (start, end, _filler) in enumerate(chosen):
        elements.extend(form[at:start])
        elements.append(Slot(slot_name(index), form[end - 1].space_after))
        at = end
    elements.extend(form[at:])
    generalized = _renamed(meaning, {lx.value: slot_name(i) for i, (_, _, lx) in enumerate(chosen)})
    if generalized is None:
        return None
    try:
        pattern = Pattern(tuple(elements), generalized)
    except ValueError:
        return None
    if not _gives(pattern, {slot_name(i): lx.value for i, (_, _, lx) in enumerate(chosen)}, meaning):
        return None
    return _repair("lexical_item_based", view, (pattern,) + tuple(created),
                   (link(pattern, slot_name(i), lx) for i, (_, _, lx) in enumerate(chosen)))


def holophrase(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory, *,
               names: Optional[Mapping[str, str]] = None) -> Optional[Repair]:
    """(vii) Nothing else applies: the whole pair, as it was said. If it is held already but no longer believed,
    this pair supports it again."""
    whole = Pattern(form, meaning)
    held = view.get(whole.key)
    if held is not None:
        return Repair("holophrase", revived=(held,))  # type: ignore[arg-type]
    return Repair("holophrase", (whole,))


#: The order the paper tries them in: a link before a new construction, a lexical construction before an item-based
#: one, and a new holophrase last. A phrase in a slot is tried beside item-based → lexical: it is that repair where a
#: slot's words say more than one concept.
REPAIRS = (add_links, item_based_lexical, phrase_in_slot, substitution, addition, deletion, lexical_item_based,
           holophrase)


__all__ = ["ENGLISH_DOMAIN", "PATTERN_TAG", "ACTS", "SITUATION_VARIABLES", "VERDICTS", "MAX_FREE_VARIABLES",
           "INITIAL_SCORE", "MeaningFact", "Meaning", "Slot", "Pattern", "Lexical", "Link",
           "KIND_OF", "item_from", "link", "Phrase", "PatternInventory", "Reading", "Stretch", "Utterance", "Repair",
           "REPAIRS",
           "REPAIR_NAMES", "is_variable", "is_slot", "slot_name", "pattern_from", "live_view", "read", "read_text",
           "readings_of", "say", "stated", "heard_stated", "meant", "heard", "heard_which", "listening", "listening_facts", "sense_choices",
           "held_key", "PLACE_KINDS", "place_spoken_of"]
