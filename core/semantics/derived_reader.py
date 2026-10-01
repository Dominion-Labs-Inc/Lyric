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

import hashlib
import functools
import heapq
import itertools
import math
import re
from dataclasses import dataclass
from typing import (Any, Callable, Dict, FrozenSet, Iterable, Iterator, List, Mapping, Optional, Sequence, Set,
                    Tuple, Union)

from core.semantics.relation_types import SemanticRelation
from core.semantics.literals import classify_literal
from core.semantics.sentence_machine import Piece, form_of, surface_of

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

#: The kinds whose object is a place, where a thing is or where an event goes: the place "there" can point back to
#: (`place_spoken_of`).
PLACE_KINDS = frozenset({"located_at", "located_in", "adjacent_to", "near", "above", "below", "left_of", "right_of",
                         "in_front_of", "behind", "moves_to", "moves_into", "moves_onto", "moves_from",
                         "moves_out_of", "moves_through", "moves_across", "moves_over", "moves_around",
                         "moves_toward", "moves_up", "moves_down"})

#: A verdict on what was just said is `has_property(?previous, true)` or `(?previous, false)`: the logic's own truth
#: values, whatever words said them.
VERDICTS = {"true": True, "false": False}

#: A meaning with more unknowns than this is refused. `canonical` compares meanings under every renaming of their
#: unknowns, which grows as a factorial; six is 720 renamings. A limit stated, not a silent truncation.
MAX_FREE_VARIABLES = 6

#: The score of a construction nothing has observed yet: where the paper starts a new one.
INITIAL_SCORE = 0.5

#: A construction scoring below this is no longer believed, and takes no part in reading or speaking. It is the
#: line the belief store itself treats as a reversal. The construction stays in memory and can come back.
COUNTS_FROM = 0.5

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
    evaluated = _evaluated(meaning.facts)
    free = sorted({t for f in evaluated for t in f.terms() if is_variable(t) and not _named(t)})
    best: Optional[str] = None
    for order in itertools.permutations(free):
        names = {variable: f"?v{i}" for i, variable in enumerate(order)}
        facts = " & ".join(sorted(f.renamed(names).render() for f in evaluated))
        asked = ", ".join(names.get(v, v) for v in meaning.asked)
        text = f"{meaning.act}: {facts}" + (f" ? {asked}" if asked else "")
        if best is None or text < best:
            best = text
    return best  # type: ignore[return-value]


def slot_name(index: int) -> str:
    return f"?slot{int(index)}"


def _named(term: str) -> bool:
    """A variable whose name is part of what it means: the situation's, and a slot's."""
    return term in SITUATION_VARIABLES or is_slot(term)


@dataclass(frozen=True)
class MeaningFact:
    """One fact a sentence states, in one of the domain system's link kinds; or, marked `condition`, one that must
    hold for the sentence's other facts to hold; or, marked `alternative`, one of the alternatives on its side of
    an `if`, of which one holds: "Is the stove hot or cold?"."""

    relation: str
    subject: str
    obj: str
    positive: bool = True
    condition: bool = False
    alternative: bool = False

    def __post_init__(self):
        relation = str(self.relation).strip()
        if relation not in _KINDS:
            raise ValueError(f"{relation!r} is not a link kind the domain system "
                             f"reasons with")
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

    def terms(self) -> Tuple[str, str]:
        return (self.subject, self.obj)

    def renamed(self, names: Mapping[str, str]) -> "MeaningFact":
        return MeaningFact(self.relation, names.get(self.subject, self.subject),
                           names.get(self.obj, self.obj), self.positive, self.condition, self.alternative)

    def render(self) -> str:
        text = f"{self.relation}({self.subject}, {self.obj})"
        text = text if self.positive else f"not {text}"
        text = f"either {text}" if self.alternative else text
        return f"if {text}" if self.condition else text

    def to_list(self) -> List[Any]:
        """As memory holds it. A condition or an alternative is marked only where there is one, so a meaning
        written before either existed is stored, and identified, exactly as it was."""
        out = [self.relation, self.subject, self.obj, self.positive]
        if self.alternative:
            return out + [self.condition, True]
        return out + [True] if self.condition else out

    @classmethod
    def from_list(cls, data: Iterable[Any]) -> "MeaningFact":
        relation, subject, obj, positive, *rest = list(data)
        return cls(relation, subject, obj, bool(positive), bool(rest[0]) if rest else False,
                   bool(rest[1]) if len(rest) > 1 else False)


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
        counted: Dict[Tuple[str, bool, bool], str] = {}
        for f in facts:
            if f.relation == "has_count" and f.positive and not f.alternative:
                if counted.setdefault((f.subject, f.condition, f.alternative), f.obj) != f.obj:
                    raise ValueError("a group has one count: how many there are is one number")
        timed: Dict[Tuple[str, str, bool], str] = {}
        for f in facts:
            if f.relation in ("precedes", "during", "follows") and f.positive and not f.alternative:
                if timed.setdefault((f.subject, f.obj, f.condition), f.relation) != f.relation:
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
        free = {t for t in mentioned if not _named(t)}
        if len(free) > MAX_FREE_VARIABLES:
            raise ValueError(f"{len(free)} unknowns in one meaning; at most "
                             f"{MAX_FREE_VARIABLES} can be compared")
        object.__setattr__(self, "act", act)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "asked", asked)

    def canonical(self) -> str:
        """This meaning written one way, whatever its unknowns were called.

        Every renaming of the unknowns to `?v0, ?v1, ...` is tried and the smallest rendering kept, so two meanings
        that differ only in what their unknowns were named render identically -- and two that differ in anything
        else do not. The situation's variables and the slots keep their names: `?speaker` is not `?listener`, and
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
        """The facts that hold, or that hold once the condition does."""
        return tuple(f for f in self.facts if not f.condition)

    def bound(self, situation: Mapping[str, str]) -> Tuple[MeaningFact, ...]:
        """The facts with the situation's variables replaced by what they stand
        for here. A fact may still hold a variable afterwards: an unknown the
        sentence introduced, which no situation names."""
        names = {}
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
        if slots and not any(isinstance(e, Piece) and not _is_mark(e.text) for e in form):
            raise ValueError("an item-based construction keeps at least one word of its own; a mark alone "
                             "anchors nothing")
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

    @property
    def key(self) -> str:
        """The construction's identity: exactly these pieces and slots with exactly this meaning.

        Memory is asked for it by this key before a construction is stored, and it is what makes teaching the same
        pair twice one construction, not two -- the identity is structural, never a resemblance a vector index
        judged."""
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

    @property
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

    @property
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
    meaning, every renaming of the unknowns to `?v0, ?v1, ...` tried and the smallest kept, and a number built from
    numbers written as its value. A phrase never changes, so it is written once."""
    return _phrase_written(anchor, tuple(facts))


@functools.lru_cache(maxsize=1 << 16)
def _phrase_written(anchor: str, facts: Tuple[MeaningFact, ...]) -> str:
    values, facts = _valued(facts)
    anchor = values.get(anchor, anchor)
    free = sorted({t for f in facts for t in f.terms()} | {anchor})
    free = [t for t in free if is_variable(t) and not _named(t)]
    best: Optional[str] = None
    for order in itertools.permutations(free):
        names = {variable: f"?v{i}" for i, variable in enumerate(order)}
        text = names.get(anchor, anchor) + " : " + " & ".join(sorted(f.renamed(names).render() for f in facts))
        if best is None or text < best:
            best = text
    return best  # type: ignore[return-value]


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

    @property
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


# ── The view ─────────────────────────────────────────────────────────────────────────────────────────────────────

Scorer = Callable[[Item], Tuple[float, int]]


def _held_score(item: Item) -> Tuple[float, int]:
    """A construction's score and use count, from its belief in this process: its posterior, and how many uses
    the observations supporting it witnessed (one each, or as many as a corpus counted). One nothing has observed
    stands at the initial score."""
    from core.reasoning import bayesian_uncertainty as beliefs
    system = beliefs._uncertainty_system
    belief = system.belief_for_claim(item.claim()) if system is not None else None
    if belief is None:
        return INITIAL_SCORE, 0
    return float(belief.posterior_probability), sum(
        int(e.get("uses", 1)) if isinstance(e, dict) else 1 for e in belief.evidence_for)


class PatternInventory:
    """The constructions and links memory holds, indexed for reading, speaking and learning.

    NOT A STORE. Memory is the store; this is memory's view of its own construction memories, rebuilt from them at
    every warm and extended by `add` as one is taught, so it always says what a rebuild would say. Scores are read
    from the beliefs as they stand, never copied here.
    """

    def __init__(self, items: Iterable[Item] = (), score: Optional[Scorer] = None):
        self._by_key: Dict[str, Item] = {}
        self._holophrase_words: Dict[Tuple[str, ...], List[str]] = {}
        self._holophrase_first: Dict[str, List[str]] = {}
        self._holophrase_meaning: Dict[str, List[str]] = {}
        self._item_based: List[str] = []
        self._phrases: List[str] = []
        self._lexical_words: Dict[Tuple[str, ...], List[str]] = {}
        self._lexical_loose: Dict[Tuple[str, ...], List[str]] = {}
        self._lexical_value: Dict[str, List[str]] = {}
        self._links: Dict[Tuple[str, str, str], str] = {}
        self._linked: Dict[Tuple[str, str], List[str]] = {}
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
        self._pattern_keys: List[str] = []
        self._holophrase_keys: List[str] = []
        self._lexical_keys: List[str] = []
        self._link_keys: List[str] = []
        self._links_to: Dict[str, List[Tuple[str, str]]] = {}
        # What reading derives from everything held is kept as each construction and link arrives, never rebuilt
        # from all of it: a vocabulary is taught one pair at a time, and a reading between two pairs must not cost
        # what everything held costs.
        # The kinds: a union-find over the fillers linked to slots, with each kind's longest filler and the changes
        # its words are written in (`_join`, `_register`).
        self._parent: Dict[str, str] = {}
        self._kind_size: Dict[str, int] = {}
        self._kind_longest: Dict[str, int] = {}
        self._kind_changes: Dict[str, set] = {}
        self._same_word: Dict[Tuple[Tuple[str, ...], str], str] = {}
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
        # The letters after each word (`letters_after`), how often each, and the words written right before each slot.
        self._after: Dict[str, set] = {}
        self._after_count: Dict[str, Dict[str, int]] = {}
        self._before_slot: Dict[Tuple[str, str], Tuple[str, ...]] = {}
        # Each slot's fillers: [written as named, written otherwise, of one word or none], and the first words of
        # the longer ones.
        self._slot_tally: Dict[Tuple[str, str], List[int]] = {}
        self._slot_runs: Dict[Tuple[str, str], Dict[str, int]] = {}
        # The changes each slot's own one-word fillers are written in, without their context ("barked": `ed`):
        # "The dog ?slot1." holding "barks" and "The dog ?slot1." holding "barked" are told apart by them.
        self._slot_changes: Dict[Tuple[str, str], Dict[Tuple[str, str], int]] = {}
        # Each slot's concepts, with the changes their words there are written in: none for a word written as its
        # name ("cut", where "barked" stands), None for an irregular form ("flew"). What saying counts a change over.
        self._slot_stems: Dict[Tuple[str, str], Dict[str, set]] = {}
        # One-word phrases that are a word of their concept written in a shape and say more of it than its kind
        # ("barked": a barking, before now), grouped by what they say more (`_shape_says`): what a shape adds.
        self._shape_groups: Dict[FrozenSet[Tuple[Any, ...]], Dict[str, Tuple[str, str]]] = {}
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
        self._use_bare: Dict[str, int] = {}
        self._use_plural: Dict[str, int] = {}
        self._use_noun: Dict[str, int] = {}
        self._use_bare_keys: Dict[str, set] = {}
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
        # found again after anything is added.
        self._said: Optional[Tuple[Dict[Tuple[str, str], Tuple[int, int]], FrozenSet[Tuple[str, str]]]] = None
        self._said_by_least: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        self._score = score or _held_score
        for item in items:
            self.add(item)

    def add(self, item: Item) -> bool:
        """Index one construction or link, and move what it changes. False when it is already here."""
        key = item.key
        if key in self._by_key:
            return False
        self._by_key[key] = item
        self._added += 1
        self._said = None
        if isinstance(item, (Pattern, Lexical, Phrase)):
            self._words.update(_folded(p.text for p in item.form if isinstance(p, Piece)))
            if isinstance(item, Pattern):
                concepts = item.meaning.constants()
            elif isinstance(item, Lexical):
                concepts = (item.value,)
            else:
                concepts = tuple(t for t in {t for f in item.facts for t in f.terms()} | {item.anchor}
                                 if not is_variable(t))
            # A number or a formula names itself, whole: "a + b" does not make "a" a word that names something.
            self._named.update(_fold(w) for concept in concepts if not _quantity(str(concept))
                               for w in str(concept).replace("_", " ").split())
        if isinstance(item, (Pattern, Phrase)):
            self._use_touched.update((key, slot) for slot in item.slots)
        if isinstance(item, Pattern):
            self._pattern_keys.append(key)
            for e in item.form[1:]:
                if isinstance(e, Piece) and e.text[:1].isupper():
                    self._name_noted(_fold(e.text))
            if item.slots:
                self._item_based.append(key)
                pieces = [e.text for e in item.form if isinstance(e, Piece)]
                self._needs[key] = (frozenset(pieces), frozenset(_folded(pieces)))
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
            self._join_twins(key)
            if isinstance(item.form[-1], Piece):
                self._ends.add(_fold(item.form[-1].text))
            self._letters_of(item)
        elif isinstance(item, Phrase):
            self._phrases.append(key)
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
            if key in self._parent:
                self._use_enter(key)
                self._register(key, item)
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
            self._count_writing(pattern, slot, words[0], _fold(filler.value))
            return
        tally = self._slot_tally.setdefault((pattern, slot), [0, 0, 0])
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
        tally = self._slot_tally.setdefault((pattern, slot), [0, 0, 0])
        tally[0 if word == name else 1] += 1
        tally[2] += 1
        self._use_touched.add((pattern, slot))
        if tally[1] * 2 > tally[0] + tally[1]:
            self._use_shaped.add((pattern, slot))
        else:
            self._use_shaped.discard((pattern, slot))
        change = self.shape_between(word, name)
        if change is not None:
            changes = self._slot_changes.setdefault((pattern, slot), {})
            least = self._least(change)
            changes[least] = changes.get(least, 0) + 1
        made = self._slot_stems.setdefault((pattern, slot), {}).setdefault(name, set())
        made.update(self.changes_between(word, name))
        if word != name and change is None:
            made.add(None)      # an irregular form ("geese", "flew"): written otherwise, by no change

    def __len__(self) -> int:
        return len(self._by_key)

    def letters_after(self, word: str) -> FrozenSet[str]:
        """The letters the words written right after this one have begun with, in everything held: after "an",
        the "e" of "eagle", the "o" of "owl"; after "a", the "b" of "bird". How a word's form goes with the next
        word's, found from what was taught."""
        return frozenset(self._after.get(_fold(word), ()))

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

    def links(self) -> Tuple[Link, ...]:
        return tuple(self._by_key[k] for k in self._link_keys)

    def with_words(self, words: Tuple[str, ...], loose: bool = False) -> Tuple[Pattern, ...]:
        """The holophrases with exactly these words; or, `loose`, the ones that begin with the same word, for a loose
        reading to compare in full."""
        if loose:
            return tuple(self._by_key[k] for k in self._holophrase_first.get(_first_word(words), ()))
        return tuple(self._by_key[k] for k in self._holophrase_words.get(tuple(words), ()))

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

    def ends(self) -> FrozenSet[str]:
        """The pieces held constructions end on: where an utterance can end, as far as anything taught says."""
        return frozenset(self._ends)

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
        shape is one sighting of a word, not evidence that it builds sentences. Nor is a word written in a change
        two held words show, from the name of a concept a taught meaning holds: "jumped", held only inside "The
        ?slot0 jumped onto the ?slot1." and "The ?slot0 jumped over the ?slot1.", names `jump`."""
        word = _fold(word)
        if not (self.is_structure(word) and word not in self._named and self._shapes.get(word, 0) > 1):
            return False
        for size in range(1, len(word)):
            for written, names in self._by_written.get(word[len(word) - size:], ()):
                if self._shape_counts[(written, names)][0] >= 2 \
                        and word[:len(word) - len(written)] + names in self._named:
                    return False
        return True

    def may_read(self, pattern: str, words: FrozenSet[str], loose: bool) -> bool:
        """Whether every word of this item-based construction's own is among these words (case folded and marks
        aside, `loose`): a construction can read words only where its own words are."""
        exact, folded = self._needs[pattern]
        return (folded if loose else exact) <= words

    # ── kinds: fillers linked to a common slot are one kind, and a kind is everything reachable that way ─────────

    def _find(self, key: str) -> str:
        parent = self._parent
        root = key
        while parent[root] != root:
            root = parent[root]
        while parent[key] != root:
            parent[key], key = root, parent[key]
        return root

    def _union(self, one: str, other: str) -> None:
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

    def _join(self, pattern: str, slot: str, lexical: str) -> None:
        """A link puts its filler in the kind of its slot's first filler -- and of the same slot of every frame that
        is this one with a word of its own written in another shape (`twins_of`): "Every ?slot0 is a ?slot1." and
        "Every ?slot0 is an ?slot1." are one construction, so what fills one fills the other's kind."""
        first = self._linked[(pattern, slot)][0]
        for key in (first, lexical):
            if key not in self._parent:
                self._parent[key] = key
                self._kind_size[key] = 1
                item = self._by_key.get(key)
                if isinstance(item, Lexical):
                    self._use_enter(key)
                    self._register(key, item)
        self._union(first, lexical)
        self._join_twins(pattern)

    def _join_twins(self, pattern: str) -> None:
        """A frame's slots, one kind with the same slots of its twins, where both hold fillers."""
        item = self._by_key.get(pattern)
        if not isinstance(item, (Pattern, Phrase)):
            return
        for twin in self.twins_of(pattern):
            for slot in item.slots:
                mine, theirs = self._linked.get((pattern, slot)), self._linked.get((twin, slot))
                if mine and theirs and mine[0] in self._parent and theirs[0] in self._parent:
                    self._union(mine[0], theirs[0])

    def _register(self, key: str, lexical: Lexical) -> None:
        """A held filler of some kind: its length and the change it is written in count for its kind, and it is one
        word with every filler that names the same concept written with the same letters, in any case ("Birds"
        opening a sentence, "birds" ending one), or written as that concept's name changed at its end ("Robins" and
        "robin", "Children" and "child"). Whether the change is productive does not matter here: that says whether
        it applies to words never seen, and both of these are held."""
        root = self._find(key)
        words = _loose(lexical.words)
        self._kind_longest[root] = max(self._kind_longest.get(root, 0), len(words))
        if len(words) == 1:
            change = self.shape_between(words[0], lexical.value)
            if change is not None:
                self._kind_changes.setdefault(root, set()).add(change)
                words = (_fold(lexical.value),)
        self._union(self._same_word.setdefault((words, lexical.value), key), key)

    def _kind_of_slot(self, pattern: str, slot: str) -> Optional[str]:
        linked = self._linked.get((pattern, slot))
        return self._find(linked[0]) if linked else None

    def longest_filler(self, pattern: str, slot: str) -> int:
        """How many words the longest filler of this slot's kind has: the longest a name in that slot has been."""
        kind = self._kind_of_slot(pattern, slot)
        return self._kind_longest.get(kind, 0) if kind is not None else 0

    def same_kind(self, pattern: str, slot: str, lexical: str) -> bool:
        """Whether this filler is of the same learned kind as a filler linked to this slot -- or, written as a number
        or a formula, stands where numbers or formulas stand: what a number is, its writing says (`_quantity`), and
        12 is the kind of thing 7 is wherever 7 stood, whether or not the two ever filled one slot."""
        kind = self._kind_of_slot(pattern, slot)
        if kind is not None and lexical in self._parent and self._find(lexical) == kind:
            return True
        item = self._by_key.get(lexical)
        return (isinstance(item, Lexical) and _quantity(item.value)
                and any(isinstance(self._by_key.get(key), Lexical) and _quantity(self._by_key[key].value)
                        for key in self._linked.get((pattern, slot), ())))

    def lexicals_with_value(self, value: str) -> Tuple[Lexical, ...]:
        return tuple(self._by_key[k] for k in self._lexical_value.get(value, ()))

    def link_between(self, pattern: str, slot: str, lexical: str) -> Optional[Link]:
        key = self._links.get((pattern, slot, lexical))
        return self._by_key.get(key) if key else None  # type: ignore[return-value]

    def fillers(self, pattern: str, slot: str) -> Tuple[Lexical, ...]:
        """The lexical constructions linked to one slot."""
        return tuple(self._by_key[k] for k in self._linked.get((pattern, slot), ()) if k in self._by_key)

    def score(self, item: Item) -> float:
        return self._score(item)[0]

    def uses(self, item: Item) -> int:
        return self._score(item)[1]

    def counts(self, item: Item) -> bool:
        """Whether a construction takes part in reading and speaking: it is still believed."""
        return self.score(item) >= COUNTS_FROM

    def reading(self, constructions: Tuple[Construction, ...], links: Tuple[Link, ...],
                meaning: Meaning, *, proposed: Tuple[Link, ...] = (), new: Tuple[Lexical, ...] = (),
                loose: bool = False, said_for: int = 0, sized: int = 0) -> "Reading":
        scores = [self._score(c) for c in constructions]
        # A filler a taught pair linked stands where it was taught; one a link is only proposed for is judged by
        # how the slot's own fillers are written.
        fillers = {c.key: c for c in constructions if isinstance(c, (Lexical, Phrase))}
        misfits = sum(1 for held in proposed if held.lexical in fillers
                      and self.written_against(held.pattern, held.slot, fillers[held.lexical]))
        apart = sized + sum(1 for held in proposed if held.lexical in self._by_key
                            and not self.stood_beside(held.pattern, held.slot, held.lexical))
        return Reading(constructions, links, meaning,
                       sum(s for s, _ in scores) / len(scores), sum(u for _, u in scores) / len(scores),
                       proposed=proposed, new=new, loose=loose, misfits=misfits, said_for=said_for, apart=apart)

    def stood_beside(self, pattern: str, slot: str, filler: str) -> bool:
        """Whether a held filler has stood, in some other slot, beside one of this slot's own fillers, as the concept
        they stand for (`_standing`). A kind is everything any slot ever joined, so it grows wide; what has filled a
        place the slot's own fillers fill is like them where a kind alone cannot say: "snow" for `snowing` stood with "rain" in "It will ?slot0.", and
        "snow" the stuff never stood where "rain", "bark" and "go" stand."""
        own = self._standing((pattern, slot))
        if not own:
            return False
        return any(place != (pattern, slot) and not own.isdisjoint(self._standing(place))
                   for place in self._links_to.get(filler, ()))

    def admits_there(self, pattern: str, slot: str, value: str) -> bool:
        """Whether a concept may stand in a slot for what the slot has held. A slot that has held two fillers or more,
        all of them mathematics -- numbers, formulas, letters for unknowns, phrases that build a number -- takes only
        mathematics: "What is ?slot0?", taught with "2 + 3" and "x", asks what a quantity comes to, and "water" is no
        quantity. One that has held two or more, none of them mathematics, takes none: "What is ?slot0?", taught
        with "water" and "milk", asks what kind of thing it is, and "7 × 8" comes to a number."""
        kinds = [kind for key in self._linked.get((pattern, slot), ())
                 for kind in (_filler_mathematical(self._by_key.get(key)),) if kind is not None]
        if len(kinds) < 2 or len(set(kinds)) != 1:
            return True
        return _mathematical(value) == kinds[0]

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
        written ("barked" and "bark" both stand for `bark`), a phrase as itself. Kept until anything more is held."""
        kept = self._standing_at.get(place)
        if kept is not None and kept[0] == self._added:
            return kept[1]
        standing = frozenset(("concept", item.value) if isinstance(item, Lexical) else ("phrase", key)
                             for key in self._linked.get(place, ()) for item in (self._by_key.get(key),)
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
    def _counted(change: Tuple[str, str], rights: Iterable[Tuple[str, str]],
                 productive: set) -> Tuple[int, int]:
        """What one word the change applies to adds to its count, (read rightly, applies), given the changes that
        read the word rightly: nothing, where a productive change with a longer written side reads it rightly and
        this one would not."""
        if change in rights:
            return 1, 1
        if any(len(other[0]) > len(change[0]) and other in productive for other in rights):
            return 0, 0
        return 0, 1

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
                right, applies = self._counted(change, self._rights.get(other, ()), self._productive_shapes)
                counts[0] += right
                counts[1] += applies
            self._shape_counts[change] = counts
        touched = set(fresh)
        for size in range(len(word)):
            for change in self._by_written.get(word[len(word) - size:], ()):
                if change in fresh:
                    continue
                old = self._counted(change, before, self._productive_shapes) if seen else (0, 0)
                new = self._counted(change, after, self._productive_shapes)
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
                for size in range(len(change[0])):
                    for shorter in self._by_written.get(word[len(word) - size:], ()):
                        if shorter in rights:
                            continue
                        other = any(len(o[0]) > size and o != change and o in self._productive_shapes for o in rights)
                        if (other or now) != (other or was):
                            self._shape_counts[shorter][1] += -1 if now else 1
                            heapq.heappush(heap, (-size, shorter))

    def written_in_shape(self, word: str, name: str) -> bool:
        """Whether a productive change makes this word from this name: "Robins" is `robin` written in a shape."""
        return any(self.productive(change) for change in self.changes_between(word, name))

    def names_of_shape(self, word: str) -> List[str]:
        """The held words a word no filler holds is written as: the word itself when it is a held concept's own name
        ("fox", where only "Foxes" is held), then the word written in a productive shape of a held word or name
        ("tables" is "table" when `s` is a shape), the most particular change first."""
        word = _fold(word)
        fillers = self._fillers_by_word

        def held(name: str) -> bool:
            return name in fillers or bool(self._lexical_value.get(name))

        out: List[str] = [word] if word not in fillers and self._lexical_value.get(word) else []
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
            # The concepts in the slots written in each change (its context aside), with the changes their words
            # there are written in.
            cells: Dict[Tuple[str, str], Dict[str, set]] = {}
            for where, changes in self._slot_changes.items():
                # A slot whose fillers are mostly written as named ("red", "big", and "recently" among them) is not
                # written in a change, whatever one filler there shows.
                if self.changed_writing(*where) is None:
                    continue
                stems = self._slot_stems.get(where, {})
                for least in changes:
                    cell = cells.setdefault(least, {})
                    for stem, made in stems.items():
                        cell.setdefault(stem, set()).update(made)
            named = {stem for where, stems in self._slot_stems.items() if self.changed_writing(*where) is None
                     for stem in stems}
            counts: Dict[Tuple[str, str], Tuple[int, int]] = {}
            productive: set = set()
            every = {change for cell in cells.values() for made in cell.values() for change in made
                     if change is not None}
            for change in sorted(every, key=lambda c: (-len(c[1]), -len(c[0]), c)):
                cell = cells.get(self._least(change), {})
                right = covered = 0
                for stem, made in cell.items():
                    if not (stem.endswith(change[1]) and len(stem) > len(change[1])):
                        continue
                    if change in made:
                        right += 1
                        covered += 1
                    elif not made and stem not in named:
                        continue
                    elif not any(o is not None and len(o[1]) > len(change[1]) and o in productive for o in made):
                        covered += 1
                counts[change] = (right, covered)
                if _tolerated(right, covered):
                    productive.add(change)
            self._said = (counts, frozenset(productive))
            self._said_by_least = {}
            for change in productive:
                self._said_by_least.setdefault(self._least(change), []).append(change)
        return self._said

    def shape_of_slot(self, pattern: str, slot: str) -> Tuple[Tuple[str, str], ...]:
        """The shapes a slot takes: when most of its one-word fillers are written otherwise than their concept's
        name ("Dogs", "Cats", "Geese" in "?slot0 can ?slot1."), the changes productive in saying (`said_shapes`), in
        any context, of the changes the words of its kind are written in, the most particular first (the longest
        run of a name's letters it asks for, then the change more concepts show); none when most are written as the
        name is. An irregular form ("Geese") counts as written otherwise, and a word the same both ways ("Fish") as
        written as the name."""
        tally = self._slot_tally.get((pattern, slot))
        if not tally or tally[1] * 2 <= tally[0] + tally[1]:
            return ()
        kind = self._kind_of_slot(pattern, slot)
        written = self._kind_changes.get(kind, ()) if kind is not None else ()
        counts, _ = self.said_shapes()
        family = [change for least in written for change in self._said_by_least.get(least, ())]
        return tuple(sorted(family, key=lambda c: (-len(c[1]), -counts[c][0], -len(c[0]), c)))

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
        if self.shape_between(word, name) is not None:
            self._shape_groups.setdefault(says, {})[phrase.key] = (word, name)

    def says_more(self, word: str, name: str) -> bool:
        """Whether a word, written from this name, is one that says more than its concept: held as a phrase that
        does ("ran": a running, before now), or written in a change that the phrases saying more are written in
        ("closed": `d`, as "chased" and "tied" are). Such a word stands for its bare concept only where it was
        taught to."""
        word, name = _fold(word), _fold(name)
        if word == name:
            return False
        if word in self._saying_words:
            return True
        change = self.shape_between(word, name)
        if change is None:
            return False
        least = self._least(change)
        return any(len(members) >= 2 and any(self._least(self.shape_between(w, n) or ("", "")) == least
                                             for w, n in members.values())
                   for members in self._shape_groups.values())

    def said_by(self, word: str, name: str) -> List[FrozenSet[Tuple[Any, ...]]]:
        """What a word written from this name says more than its concept, each way it does (`@` for the thing
        named): as the held phrases of its shape show, or as its change would make of it ("walked": before now)."""
        word, name = _fold(word), _fold(name)
        held = [says for says, members in self._shape_groups.items() if (word, name) in members.values()]
        return held or [says for made, says, _ in self.shaped_phrases(word) if made == name]

    def shaped_phrases(self, word: str) -> List[Tuple[str, FrozenSet[Tuple[Any, ...]], Tuple[str, ...]]]:
        """For a word none holds, what each shape that says more than a kind would make of it: the name it is written
        from, what the shape says (with `@` for the thing named), and the held phrases that show it ("jumped":
        `jump`, before now, as "barked" and "walked" show). The change is the one Albright & Hayes's confidence
        ranks first over the words of that shape ending as this one does: taking "ed" off is right for "barked",
        "walked" and "helped", "d" only for "closed" and "tied", so "jumped" is `jump`."""
        word = _fold(word)
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
        return out

    def slot_writing(self, pattern: str, slot: str) -> Optional[FrozenSet[Tuple[str, str]]]:
        """How a slot's own one-word fillers are written: None when most are written as their concept's name
        ("dog", "table"), or when it holds none; else the changes they are written in, without context ("barked":
        `ed`; "Dogs": `s`), empty when none shows one (only irregular forms, "Geese"). A slot's own, not its kind's:
        "barks", "barked" and "barking" are one kind, and "The dog ?slot1." is two frames, one holding each."""
        tally = self._slot_tally.get((pattern, slot))
        if not tally or tally[1] * 2 <= tally[0] + tally[1]:
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
        if writing is None or sum(self._slot_changes.get((pattern, slot), {}).values()) * 2 <= tally[1]:
            return None
        return writing

    def written_against(self, pattern: str, slot: str, filler: Any) -> bool:
        """Whether a filler is written otherwise than a slot's own fillers are: as named where they are written in
        a shape, in a shape where they are written as named (unless one of them is written in it too), or in a
        change none of them shows ("barked" where "barks" stands). An irregular form ("flew") shows no change and is not held against a slot that takes a
        shape; a filler of several words, or a slot holding no one-word filler, is not judged. A phrase of one word
        is judged as its word ("barking", where "barked" stands)."""
        written = self._written_as(filler)
        tally = self._slot_tally.get((pattern, slot))
        if written is None or not tally or not tally[0] + tally[1]:
            return False
        word, name = written
        otherwise = word != name
        writing = self.slot_writing(pattern, slot)
        if writing is None:
            # Where most are written as named, one written in a change one of them is written in is written as they
            # are: "snow" for `snowing` where "rain" stands for `raining`.
            change = self.shape_between(word, name) if otherwise else None
            return otherwise and (change is None
                                  or self._least(change) not in self._slot_changes.get((pattern, slot), {}))
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

    def unshaped_in(self, pattern: str, slot: str, word: str) -> Optional[str]:
        """The name a word never held has in a slot whose fillers are written in a shape: the word with the most
        particular change of theirs that it ends in undone, of those productive in saying (`said_shapes`: the slot's
        fillers are concepts said in a shape) ("jumps", where "barks" and "climbs" stand, is `jump`); None when the
        slot takes no shape, or the word ends in none of its changes."""
        writing = self.changed_writing(pattern, slot)
        if not writing:
            return None
        word = _fold(word)
        for written, names in sorted(self.said_shapes()[1], key=lambda c: (-len(c[1]), -len(c[0]), c)):
            if self._least((written, names)) in writing and word.endswith(written) \
                    and len(word) - len(written) + len(names) >= 2:
                return word[:len(word) - len(written)] + names
        return None

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
        """A filler held in a kind, and held as an item: its concept, counted or held bare, counts for its kind."""
        if not self._uses_built or key in self._use_entered:
            return
        item = self._by_key.get(key)
        if key not in self._parent or not isinstance(item, Lexical):
            return
        self._use_entered.add(key)
        root = self._find(key)
        if self._use_counted.get(item.value):
            self._use_noun_more(root)
        if len(_loose(item.words)) == 1 and self._use_bare.get(item.value):
            self._use_bare_keys.setdefault(root, set()).add(key)
        self._use_dirty.add(key)

    def _use_noun_more(self, root: str) -> None:
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
            self._use_counted[value] = self._use_counted.get(value, 0) + 1
            if self._use_counted[value] == 1:
                for other in self._lexical_value.get(value, ()):
                    if other in self._use_entered:
                        self._use_noun_more(self._find(other))
                    self._use_dirty.add(other)
        if taken:
            self._use_plural[key] = self._use_plural.get(key, 0) + 1
            self._use_dirty.add(key)
        elif first and _loose(filler.words)[0] == _fold(value):
            self._use_bare[value] = self._use_bare.get(value, 0) + 1
            if self._use_bare[value] == 1:
                for other in self._lexical_value.get(value, ()):
                    item = self._by_key.get(other)
                    if other in self._use_entered and isinstance(item, Lexical) and len(_loose(item.words)) == 1:
                        self._use_bare_keys.setdefault(self._find(other), set()).add(other)
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
        if self.is_proper(words[0]) and not self._use_counted.get(filler.value):
            return "name"
        if self._use_plural.get(key):
            return "plural"
        if self._use_counted.get(filler.value):
            return "count"
        if self._use_bare.get(filler.value) and self._use_noun.get(self._find(key)):
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
        for table in (self._use_slot_state, self._use_counted, self._use_bare, self._use_plural, self._use_noun,
                      self._use_bare_keys, self._use_key, self._use_slots, self._use_words, self._end_word,
                      self._end_term, self._end_children, self._end_passed, self._end_decided):
            table.clear()
        self._end_kept = {False: {}, True: {}}
        self._end_trusted = {False: 0.0, True: 0.0}
        self._end_contested = {False: set(), True: set()}
        shapes: Dict[str, bool] = {}
        self._use_slot_state.update({where: self._slot_state(where, shapes) for where in self._linked})
        for key in self._parent:
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

    def used_as(self, word: str) -> Optional[str]:
        """How a held one-word filler is used, the most of its uses (`_use_model`), or None when none is held."""
        self._uses_now()
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
        and `count` where it is counted: what a word never held may be to stand there."""
        self._uses_now()
        admits = {how for how, n in self._use_slots.get((pattern, slot), {}).items() if n}
        for twin in self.twins_of(pattern):
            admits |= {how for how, n in self._use_slots.get((twin, slot), {}).items() if n}
        if self.counted_slot(pattern, slot):
            admits.add("count")
        return frozenset(admits)

    def filler_openings(self, pattern: str, slot: str) -> FrozenSet[bool]:
        """How this slot's fillers begin: True for a filler begun by a word that names nothing ("A dog"), False for
        any other."""
        tally = self._slot_tally.get((pattern, slot))
        openings = {self.names_nothing(word) for word in self._slot_runs.get((pattern, slot), {})}
        if tally and tally[2]:
            openings.add(False)
        return frozenset(openings)

    def word_kinds(self) -> List[FrozenSet[Lexical]]:
        """The lexical constructions grouped by the slots they fill. Two that fill a common slot are one kind, and
        a kind is everything reachable that way. Nothing tells the substrate what the kinds are."""
        groups: Dict[str, set] = {}
        for key in list(self._parent):
            if key in self._by_key:
                groups.setdefault(self._find(key), set()).add(self._by_key[key])
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
        return (self.loose, sum(len(_loose(lexical.words)) for lexical in self.new),
                len(self.proposed) + self.said_for, self.misfits, self.apart)


def _best_first(reading: Reading):
    return reading.supposed + (-reading.score, -reading.uses, reading.key)


def _chunkings(form: Tuple[FormElement, ...], words: Tuple[str, ...],
               same: Callable[[str, str], bool] = str.__eq__,
               missing: Callable[[Piece], bool] = lambda piece: False,
               shaped: Optional[Callable[[int, str], bool]] = None) -> Iterator[Tuple[Tuple[int, int], ...]]:
    """Every way a construction's form covers `words` exactly: each piece matches its word (as `same` compares
    them, or as `shaped` finds the word there written for it in another shape) or, where `missing` allows it, is
    absent; each slot takes one or more words. Yields each slot's span (start, end) in `words`, in slot order."""
    at_least = [0] * (len(form) + 1)
    for i in range(len(form) - 1, -1, -1):
        element = form[i]
        at_least[i] = at_least[i + 1] + (0 if isinstance(element, Piece) and missing(element) else 1)

    def walk(i: int, at: int, spans: Tuple[Tuple[int, int], ...]):
        if i == len(form):
            if at == len(words):
                yield spans
            return
        element = form[i]
        if isinstance(element, Slot):
            # Leave a word for each later piece that cannot be missing, and for each later slot.
            for end in range(at + 1, len(words) - at_least[i + 1] + 1):
                yield from walk(i + 1, end, spans + ((at, end),))
            return
        if at < len(words) and (same(words[at], element.text) or (shaped is not None and shaped(at, element.text))):
            yield from walk(i + 1, at + 1, spans)
        if missing(element):
            yield from walk(i + 1, at, spans)

    yield from walk(0, 0, ())


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


def _as_written(pattern: Pattern, words: Sequence[str], spans: Sequence[Tuple[int, int]]) -> Pattern:
    """The frame as these words write it, where they cover it with these slot spans: a word of its own matched in
    another of its shapes ("An" for the "A" of "A ?slot0 is a ?slot1.") is written as the words have it. The frame
    itself when every word of its own is written as it is. What the learner links, and what it creates, is the frame
    as the sentence wrote it: the words held after a frame's word are the words written after it."""
    form: List[FormElement] = []
    slots = iter(spans)
    at, changed = 0, False
    for element in pattern.form:
        if isinstance(element, Slot):
            at = next(slots)[1]
            form.append(element)
        else:
            changed = changed or words[at] != element.text
            form.append(Piece(words[at], element.space_after) if words[at] != element.text else element)
            at += 1
    return Pattern(tuple(form), pattern.meaning) if changed else pattern


def _fill(meaning: Meaning, values: Mapping[str, str]) -> Optional[Meaning]:
    return _renamed(meaning, values)


def _may_be_new(pieces: Tuple[Piece, ...], view: PatternInventory, longest: int) -> bool:
    """Whether these words can be taken as a new concept's name in a slot whose kind's longest filler has `longest`
    words: no more words than that, nor than the store takes in a term; none of them a mark; one word alone not a
    word that names nothing (`names_nothing`); and several, none of them a structure word -- a run of words that
    holds one is structure the substrate has not learned to read, not a name."""
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    words = _written_words(pieces)
    if not pieces or len(words) > min(MAX_TERM_WORDS, max(longest, 1)) or _parted(pieces):
        return False
    if len(pieces) == 1:
        # One word is a name unless it is a word that names nothing ("a"); a word held so far only inside forms
        # ("cup" in "That is my cup.") may still name a thing, and a taught meaning names it.
        return not view.names_nothing(pieces[0].text)
    # The words a hyphen joins are one word, whatever they are: "give-and-take" is a name.
    return not any(len(word) == 1 and view.is_structure(word[0].text) for word in words)


def _fillers(view: PatternInventory, pattern: Pattern, slot: str, pieces: Tuple[Piece, ...], *,
             extend: bool, loose: bool) -> List[Tuple[Lexical, Optional[Link], str]]:
    """What may stand in one slot for these words: (filler, the link it stands through, how). A held link is
    `linked`; with `extend`, a filler of the slot's kind stands through a `kind` link proposed, and words nothing
    held covers stand as a `new` filler through a link proposed."""
    words = tuple(p.text for p in pieces)
    if loose and _parted(pieces):
        return []          # a mark inside what was said separates; no filler spans it
    held = view.lexicals_with_words(_loose(words) if loose else words, loose=loose)
    out: List[Tuple[Lexical, Optional[Link], str]] = []
    alike = _alike(view, pattern, slot)
    for lexical in held:
        if not view.counts(lexical):
            continue
        linked = view.link_between(pattern.key, slot, lexical.key)
        if linked is not None:
            out.append((lexical, linked, "linked"))
        elif extend and alike(lexical.key) and view.admits_there(pattern.key, slot, lexical.value) \
                and not (len(lexical.words) == 1 and view.says_more(lexical.words[0], lexical.value)
                         and not _frame_says(pattern, slot, view.said_by(lexical.words[0], lexical.value))):
            # A word that says more than its concept ("walked": a walking before now) stands as its concept only
            # where the frame says the rest itself: "Only ?slot0 ?slot1." says its events were before now.
            out.append((lexical, link(pattern, slot, lexical), "kind"))
    # A word held in another case is not a new word: it is read as the word it is, loosely.
    if extend and not held and not view.lexicals_with_words(_loose(words), loose=True):
        # Nor is a held word written in a shape learned from the fillers ("tables", where "table" is held), or a
        # held concept's own name: it stands where that word would, as that word's concept.
        if len(pieces) == 1:
            for name in view.names_of_shape(words[0]):
                if view.says_more(words[0], name):
                    continue               # "jumped" is a jumping before now (`shaped_phrases`), not `jump` alone
                for base in view.holding(name):
                    if view.counts(base) and (view.link_between(pattern.key, slot, base.key) is not None
                                              or alike(base.key)):
                        shaped = Lexical(pieces, base.value)
                        out.append((shaped, link(pattern, slot, shaped), "kind"))
                        break
        if _may_be_new(pieces, view, view.longest_filler(pattern.key, slot)) \
                and view.admits_there(pattern.key, slot, _named_as(pieces)):
            new = Lexical(pieces, _named_as(pieces))
            out.append((new, link(pattern, slot, new), "new"))
            # A word never held, where the slot's fillers are written in a shape, is also the word that shape makes
            # it from: "jumped", where "barked" and "walked" stand, is `jump`.
            name = view.unshaped_in(pattern.key, slot, words[0]) if len(pieces) == 1 else None
            if name:
                shaped = Lexical(pieces, name)
                out.append((shaped, link(pattern, slot, shaped), "new"))
    return out


def _named_as(pieces: Tuple[Piece, ...]) -> str:
    """What a word never met names where it stands: itself, as written -- or, written as a number or a formula,
    the number or formula it writes, one thing however it is written: `1,000,000` is 1000000, `2+3` is `2 + 3`."""
    surface = surface_of(pieces)
    if len(pieces) == 1:
        literal = classify_literal(surface)
        if literal is not None and literal.kind in ("cardinal", "decimal", "expression"):
            return literal.canonical
    return surface


def _alike(view: PatternInventory, frame: Union[Pattern, Phrase], slot: str) -> Callable[[str], bool]:
    """Whether a held filler may stand in a slot it was never linked to: one of the slot's kind. In a construction
    with no word of its own ("?slot0 ?slot1"), nothing but its fillers anchors it, so the filler must also have stood
    beside the slot's own fillers somewhere (`stood_beside`): a kind alone reads any two words there ("walked
    carefully" as a count)."""
    wordless = not any(isinstance(e, Piece) and not _is_mark(e.text) for e in frame.form)
    return lambda key: view.same_kind(frame.key, slot, key) and (not wordless or view.stood_beside(frame.key, slot, key))


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
    condition is said in the condition too."""
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
                     and len({(f.subject, f.condition) for f in uses}) == 1)
        if not described and is_variable(thing_of) and not _named(thing_of) and slot != anchor \
                and any(f.relation == "instance_of" and f.obj == slot for f in uses):
            return None        # a thing is never a kind: one standing for a thing describes one thing, or none
        if described:
            thing, condition = uses[0].subject, uses[0].condition
            out = [f for f in out if f not in uses]
            added.extend(MeaningFact(f.relation, thing if f.subject == thing_of else f.subject,
                                     thing if f.obj == thing_of else f.obj, f.positive, condition) for f in said)
        else:
            names[slot] = thing_of
            condition = bool(uses) and all(f.condition for f in uses)
            added.extend(MeaningFact(f.relation, f.subject, f.obj, f.positive, condition) for f in said)
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


def _slot_fillings(view: PatternInventory, frame: Union[Pattern, Phrase], slot: str, pieces: Tuple[Piece, ...],
                   start: int, end: int, chart: Dict[Tuple[int, int], List[_Filling]], *,
                   extend: bool, loose: bool) -> List[_Filling]:
    """Everything that may stand in one slot for `pieces[start:end]`: the lexical fillers `_fillers` finds, and the
    phrases read over those pieces (`_phrase_fillings`) that fill this slot through a held link or, with `extend`, a
    proposed link to a phrase of the slot's kind."""
    out: List[_Filling] = []
    alike = _alike(view, frame, slot)

    def sized(value: str) -> int:
        return 1 if view.sized_apart(frame.key, slot, value) else 0
    for lexical, held, how in _fillers(view, frame, slot, pieces[start:end], extend=extend, loose=loose):
        if how == "linked":
            out.append(_Filling(lexical.value, (), (lexical,), links=(held,), apart=sized(lexical.value)))
        else:
            out.append(_Filling(lexical.value, (), (lexical,), proposed=(held,),
                                new=(lexical,) if how == "new" else (), apart=sized(lexical.value)))
    for filling in _phrase_fillings(view, pieces, start, end, chart, extend=extend, loose=loose):
        top = filling.constructions[0]
        held = view.link_between(frame.key, slot, top.key)
        apart = filling.apart + sized(_valued(filling.facts)[0].get(filling.anchor, filling.anchor)
                                      if filling.facts else filling.anchor)
        if held is not None:
            out.append(_Filling(filling.anchor, filling.facts, filling.constructions,
                                filling.links + (held,), filling.proposed, filling.new, apart=apart))
        elif extend and (alike(top.key)
                         or any(view.link_between(frame.key, slot, held) is not None
                                or alike(held) for held in filling.like)):
            out.append(_Filling(filling.anchor, filling.facts, filling.constructions,
                                filling.links, filling.proposed + (link(frame, slot, top),), filling.new,
                                apart=apart))
    return out


def _phrase_fillings(view: PatternInventory, pieces: Tuple[Piece, ...], start: int, end: int,
                     chart: Dict[Tuple[int, int], List[_Filling]], *, extend: bool, loose: bool) -> List[_Filling]:
    """Every phrase that reads `pieces[start:end]`, read once and kept in `chart` for every slot that could take it:
    a phrase with no slots whose form is those words, or one whose slots hold fillers of their own, phrases
    included, so phrases nest."""
    key = (start, end)
    if key in chart:
        return chart[key]
    chart[key] = []                      # read once; a phrase reading itself finds nothing
    span = pieces[start:end]
    words = tuple(_fold(p.text) for p in span) if loose else tuple(p.text for p in span)
    if not words or (loose and _parted(span)):
        return []
    same = (lambda word, text: word == _fold(text)) if loose else str.__eq__
    missing = (lambda piece: _is_mark(piece.text)) if loose else (lambda piece: False)
    shaped, stood = _written_shapes(view, words, pieces[end].text if end < len(pieces) else "", loose=loose)
    have = frozenset(words) | stood
    out: List[_Filling] = []
    # A word written in a shape that says more than its kind ("jumped", where "barked" and "walked" say a barking and
    # a walking before now), held by no filler that says only its concept: the phrase that shape would make of it.
    held = view.lexicals_with_words((_fold(span[0].text),), loose=True) if len(span) == 1 else ()
    if extend and len(span) == 1 and all(view.says_more(lx.words[0], lx.value) for lx in held) \
            and _may_be_new(span, view, 1):
        for name, says, held in view.shaped_phrases(span[0].text):
            anchor = "?x"
            facts = (MeaningFact("instance_of", anchor, name),) + tuple(
                MeaningFact(relation, anchor if subject == "@" else subject, anchor if obj == "@" else obj, positive)
                for relation, subject, obj, positive in sorted(says))
            try:
                made = Phrase(span, anchor, facts)
            except ValueError:
                continue
            out.append(_Filling(anchor, facts, (made,), new=(Lexical(span, name),), like=held))
    for phrase in view.phrases():
        if not view.counts(phrase) or (phrase.slots and not view.may_read(phrase.key, have, loose)):
            continue
        anchors = sum(1 for e in phrase.form if isinstance(e, Piece) and not _is_mark(e.text))
        for spans in _chunkings(phrase.form, words, same, missing, shaped):
            if not phrase.slots:
                out.append(_Filling(phrase.anchor, phrase.facts, (phrase,)))
                break
            options = []
            for slot, (a, b) in zip(phrase.slots, spans):
                fitting = _slot_fillings(view, phrase, slot, pieces, start + a, start + b, chart,
                                         extend=extend, loose=loose)
                if not fitting:
                    break
                options.append(fitting)
            else:
                for combo in itertools.product(*options):
                    here, held = _new_here(combo)
                    if not _anchored(here, anchors + held):
                        continue
                    composed = _composed(phrase.facts, phrase.anchor, dict(zip(phrase.slots, combo)))
                    if composed is None:
                        continue
                    anchor, facts = composed
                    out.append(_Filling(anchor, facts, (phrase,) + tuple(x for c in combo for x in c.constructions),
                                        tuple(x for c in combo for x in c.links),
                                        tuple(x for c in combo for x in c.proposed),
                                        tuple(x for c in combo for x in c.new),
                                        apart=sum(c.apart for c in combo)))
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
    kept: Dict[Tuple[str, str], _Filling] = {}
    for filling in out:
        top = filling.constructions[0].key
        if _supposes(filling, view) != least[top]:
            continue
        said = (top, _phrase_canonical(filling.anchor, filling.facts))
        if said not in kept or len(filling.constructions) < len(kept[said].constructions):
            kept[said] = filling
    out = list(kept.values())
    chart[key] = out
    return out


def _supposes(filling: _Filling, view: PatternInventory) -> Tuple[int, bool, int, int]:
    """How much a reading of a phrase supposes, least first: new words, constructions not held, links proposed, and
    numbers standing where numbers of their size never stood (`sized_apart`)."""
    return (sum(len(_loose(lexical.words)) for lexical in filling.new),
            any(c.key not in view for c in filling.constructions), len(filling.proposed), filling.apart)


def _analyses(words: Tuple[str, ...], view: PatternInventory, *, pieces: Optional[Tuple[Piece, ...]] = None,
              extend: bool = False, loose: bool = False) -> List[Reading]:
    """Every reading of these words through constructions still believed, best first.

    Strict, as the learner reads: every slot holds a filler linked to it, a word or a phrase. `extend` lets a slot
    also hold a filler of its kind or new words (`_slot_fillings`); a reading takes new words only through a frame
    with words of its own, since those words are what anchor it (`_anchored`). A frame's word may be written in
    another of its shapes, as the word after it asks (`_written_shapes`). `loose` compares with case folded, lets a
    form's marks be missing and sets aside a final mark on what was said; a mark inside what was said is never set
    aside."""
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
    shaped, stood = _written_shapes(view, words, loose=loose)
    have = frozenset(words) | stood
    chart: Dict[Tuple[int, int], List[_Filling]] = {}
    for pattern in view.item_based():
        if not view.may_read(pattern.key, have, loose) or not view.counts(pattern):
            continue
        form = pattern.form
        anchors = sum(1 for e in form if isinstance(e, Piece) and not _is_mark(e.text))
        for spans in _chunkings(form, words, same, missing, shaped):
            said_for = _said_for(view, form, words, spans, same)
            options = []
            for slot, (start, end) in zip(pattern.slots, spans):
                fitting = _slot_fillings(view, pattern, slot, pieces, start, end, chart, extend=extend, loose=loose)
                if not fitting:
                    break
                options.append(fitting)
            else:
                for combo in itertools.product(*options):
                    here, held = _new_here(combo)
                    if not _anchored(here, anchors + held):
                        continue
                    new = tuple(x for c in combo for x in c.new)
                    meaning = _composed_meaning(pattern.meaning, dict(zip(pattern.slots, combo)))
                    if meaning is not None:
                        out.append(view.reading(
                            (pattern,) + tuple(x for c in combo for x in c.constructions),
                            tuple(x for c in combo for x in c.links), meaning,
                            proposed=tuple(x for c in combo for x in c.proposed), new=new, loose=loose,
                            said_for=said_for, sized=sum(c.apart for c in combo)))
    return sorted(out, key=_best_first)


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
    phrase of slots alone takes a new name only beside something held ("glorpy dogs")."""
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


def _read_pieces(pieces: Tuple[Piece, ...], view: PatternInventory) -> Tuple[Reading, ...]:
    """The meanings these pieces read to, best reading of each first, from the readings that had to suppose the
    least: none that had to suppose more is reported beside one that supposed less."""
    words = tuple(p.text for p in pieces)
    found = (_analyses(words, view, pieces=pieces, extend=True)
             or _analyses(words, view, pieces=pieces, extend=True, loose=True))
    if not found:
        return ()
    least = found[0].supposed
    best: Dict[str, Reading] = {}
    for reading in found:
        if reading.supposed == least:
            best.setdefault(reading.meaning.canonical(), reading)
    return tuple(sorted(best.values(), key=_best_first))


def read(sentence: str, inventory: Optional[PatternInventory] = None) -> Tuple[Reading, ...]:
    """Every meaning this sentence can be read to, best reading of each first; empty when nothing reads it.

    More than one when the same words were taught, or can be combined, to mean different things. That is reported,
    never resolved here: which one is meant is decided by the situation and the scores, by whoever is listening
    (`meant`).
    """
    view = inventory if inventory is not None else _live_inventory()
    pieces = form_of(sentence)
    if not pieces:
        return ()
    return _read_pieces(pieces, view)


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


def _partial(pieces: Tuple[Piece, ...], view: PatternInventory) -> Tuple[Tuple[Stretch, ...], Tuple[str, ...]]:
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
            readings = _read_pieces(part, view)
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


#: How many stretches between held ends one utterance may span. An end a construction ends on can also stand inside
#: an utterance ("Dr. Smith is here."), so a reading may run past it; this bounds how far.
_ENDS_SPANNED = 3


def read_text(text: str, inventory: Optional[PatternInventory] = None, *,
              parts: bool = False) -> Tuple[Utterance, ...]:
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
    ends = view.ends()
    cuts = [0] + [i + 1 for i, p in enumerate(pieces[:-1]) if _fold(p.text) in ends] + [len(pieces)]
    read_at: Dict[Tuple[int, int], Tuple[Reading, ...]] = {}

    def readings(a: int, b: int) -> Tuple[Reading, ...]:
        if (a, b) not in read_at:
            read_at[(a, b)] = _read_pieces(pieces[a:b], view)
        return read_at[(a, b)]

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
        separated = _separated(said, view)
        if separated:
            out.extend(separated)
            continue
        partial, unknown = _partial(said, view) if parts else ((), ())
        out.append(Utterance(said, (), partial, unknown))
    return tuple(out)


def _separated(said: Tuple[Piece, ...], view: PatternInventory) -> Tuple[Utterance, ...]:
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
        found = _read_pieces(stretch, view) if any(not _is_mark(p.text) for p in stretch) else ()
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


def held_key(fact: MeaningFact) -> Tuple[str, str, str, bool]:
    """A fact between named things as the listener asks memory about it: whether memory holds it."""
    return (fact.relation, fact.subject, fact.obj, fact.positive)


def listening_facts(meaning: Meaning) -> Tuple[MeaningFact, ...]:
    """What a meaning says between named things, as a listener weighs it against what it knows. An event stands
    for its kind: "I ate fish." is an eating done to fish, weighed as `done_to(eat, fish)`; "Tom has a red ball."
    a ball that is red, `has_property(ball, red)`. What still names an unknown or the situation is not weighed."""
    kinds = {f.subject: f.obj for f in meaning.facts
             if f.relation == "instance_of" and f.positive and is_variable(f.subject) and not is_variable(f.obj)}
    out: List[MeaningFact] = []
    for fact in meaning.facts:
        if fact.relation == "instance_of" and fact.subject in kinds:
            continue
        subject, obj = kinds.get(fact.subject, fact.subject), kinds.get(fact.obj, fact.obj)
        if is_variable(subject) or is_variable(obj) or subject == obj:
            continue
        out.append(MeaningFact(fact.relation, subject, obj, fact.positive))
    return tuple(dict.fromkeys(out))


def _worded(reading: Reading) -> str:
    """A reading's meaning with each concept a word named put back as that word: what was said, whichever thing
    each word was taken to name. Two readings that differ only in which thing a word names ("fish", the animal or
    the food) are the same here."""
    names = {c.value: " ".join(_loose(c.words)) for c in reading.constructions if isinstance(c, Lexical)}
    meaning = reading.meaning
    return Meaning(meaning.act, tuple(f.renamed(names) for f in meaning.facts), meaning.asked).canonical()


def sense_choices(readings: Sequence[Reading]) -> Tuple[Reading, ...]:
    """The readings a listener chooses among by which thing a word names: the best reading of each meaning, when
    the utterance read to more than one and they all say the same words of the same things but for that. Empty
    when it read to one meaning, or when its meanings differ otherwise (what is said of what), which is the
    listener's to ask about."""
    best: Dict[str, Reading] = {}
    for reading in readings:
        best.setdefault(reading.meaning.canonical(), reading)
    if len(best) < 2 or len({_worded(r) for r in best.values()}) != 1:
        return ()
    return tuple(best.values())


def _senses(choices: Sequence[Reading]) -> Tuple[Dict[str, FrozenSet[str]], FrozenSet[str]]:
    """For readings that differ only in which thing a word names: the things each takes the words to name that the
    others do not (its senses), and the things they all name (the rest of what was said)."""
    named = {r.meaning.canonical(): frozenset(t for f in listening_facts(r.meaning) for t in f.terms())
             for r in choices}
    shared = frozenset.intersection(*named.values()) if named else frozenset()
    return {key: terms - shared for key, terms in named.items()}, shared


def meant(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None, *,
          held: Mapping[Tuple[str, str, str, bool], int] = {},
          related: Mapping[str, int] = {}) -> Optional[Reading]:
    """Which reading of an utterance was meant, as a listener takes it; None when the listener cannot tell.

    The reader reports every meaning the words can have (`read`); this is the listener's half. One meaning is
    the one meant. Meanings that differ only in which thing a word names are told apart by evidence, as a listener
    does it, in this order:
      1. what the listener knows of what is said: the reading whose facts (`listening_facts`) memory holds more
         firmly (`held`: 2 for a fact held of the things themselves, 1 for one held of what they are kinds of).
         "A salmon is a fish." is about the fish memory knows a salmon to be; "I ate fish." about the fish that is
         a food, when memory holds that food is eaten;
      2. how what each takes the words to name bears on the rest of what is said and on what was said before
         (`related`: for each thing, how many of those it is connected to in memory). After "We went to the
         river.", "the bank" is the bank a river has;
      3. how the words are used: the reading whose words have been met naming those things more often, from the
         uses each word's construction has been observed in. "Fish" names the animal far more often than the food.
    Evidence that does not tell them apart leaves the choice open, and so do meanings that differ in what is said
    of what: those are the listener's to ask about, never to pick. With no memory at hand (`held` and `related`
    empty) only the words' uses can tell them apart; `heard` asks memory first."""
    best: Dict[str, Reading] = {}
    for reading in readings:
        best.setdefault(reading.meaning.canonical(), reading)
    if len(best) == 1:
        return next(iter(best.values()))
    choices = sense_choices(readings)
    if not choices:
        return None
    view = inventory if inventory is not None else _live_inventory()
    senses, _ = _senses(choices)

    def evidence(reading: Reading) -> Tuple[int, int, float]:
        knows = sum(held.get(held_key(f), 0) for f in listening_facts(reading.meaning))
        near = sum(related.get(term, 0) for term in senses[reading.meaning.canonical()])
        used = sum(math.log1p(view.uses(c)) for c in reading.constructions if isinstance(c, (Lexical, Phrase)))
        return knows, near, used

    ranked = sorted(choices, key=evidence, reverse=True)
    return ranked[0] if evidence(ranked[0]) != evidence(ranked[1]) else None


async def listening(utterances: Iterable[Sequence[Reading]], context: Iterable[str] = ()
                    ) -> Tuple[Dict[Tuple[str, str, str, bool], int], Dict[str, int]]:
    """What memory knows that bears on which thing each word was meant to name, for every utterance whose meanings
    differ only in that: how firmly it holds each fact each meaning says (`held`), and how each thing a meaning
    takes a word to name is connected to the rest of what was said and to `context`, the things talked of before
    (`related`). Asked of the memory agent, the one reader of memory. Empty where nothing is to be chosen."""
    facts, senses, around = set(), set(), set(context)
    for readings in utterances:
        choices = sense_choices(readings)
        if not choices:
            continue
        own, shared = _senses(choices)
        for reading in choices:
            facts.update(held_key(f) for f in listening_facts(reading.meaning))
        for terms in own.values():
            senses.update(terms)
        around.update(shared)
    if not facts and not senses:
        return {}, {}
    from core.agents.memory_agent import memory_agent
    return await memory_agent().listening_evidence(facts, senses, around - senses)


async def heard(readings: Sequence[Reading], inventory: Optional[PatternInventory] = None, *,
                context: Iterable[str] = ()) -> Optional[Reading]:
    """Which reading was meant, as a listener with memory at hand takes it: memory asked first (`listening`), then
    `meant`. Every place that reads where it can wait for memory listens this way."""
    held, related = await listening((readings,), context)
    return meant(readings, inventory, held=held, related=related)


async def heard_which(texts: Sequence[str], inventory: Optional[PatternInventory] = None, *,
                      context: Iterable[str] = ()) -> Optional[str]:
    """Which of several ways of hearing what was said was said, as a listener takes it: when words in it sound
    alike ("to", "two", "too"), the ear hands on every way it can be heard, and a person takes the one that makes
    sense. In this order: the ways whose every utterance reads; of those, the one whose meaning memory holds more
    firmly and connects more to the rest of what was said and to `context` (what was talked of before); then the
    one whose words have been met meaning that more often. None when no way reads, or the evidence does not tell
    two apart: then what was said is not all understood, and is asked about, never guessed."""
    read: List[Tuple[str, Tuple[Reading, ...]]] = []
    for text in dict.fromkeys(texts):
        utterances = read_text(text, inventory)
        if utterances and all(u.understood for u in utterances):
            read.append((text, tuple(u.readings for u in utterances)))
    if len(read) < 2:
        return read[0][0] if read else None
    held, related = await listening([r for _, ways in read for r in ways], context)
    view = inventory if inventory is not None else _live_inventory()
    facts: Set[Tuple[str, str, str, bool]] = set()
    terms: Set[str] = set()
    taken: List[Tuple[str, Tuple[Reading, ...]]] = []
    for text, ways in read:
        chosen = tuple(meant(r, inventory, held=held, related=related) for r in ways)
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
    known, near = await memory_agent().listening_evidence(facts, terms, list(context))

    def evidence(item) -> Tuple[int, int, float]:
        _, chosen = item
        meant_facts = [f for c in chosen for f in listening_facts(c.meaning)]
        return (sum(known.get(held_key(f), 0) for f in meant_facts),
                sum(near.get(t, 0) for f in meant_facts for t in f.terms()),
                sum(math.log1p(view.uses(k)) for c in chosen for k in c.constructions
                    if isinstance(k, (Lexical, Phrase))))

    ranked = sorted(taken, key=evidence, reverse=True)
    return ranked[0][0] if evidence(ranked[0]) != evidence(ranked[1]) else None


def stated(text: str, inventory: Optional[PatternInventory] = None) -> Tuple[MeaningFact, ...]:
    """What a text states outright between named things: the asserted facts of each utterance that reads, to one
    meaning, as a telling. A question or a request states nothing; a conditional states none of its facts; of
    alternatives, none is stated, only that one holds; a fact still naming an unknown or the situation has nothing
    here to name it by; and an utterance whose meaning the listener cannot tell (`meant`) states nothing.

    Read with no memory at hand: where a word names several things, only how often each has been met tells them
    apart. Where the reading can wait for memory, `heard_stated` asks it first."""
    return _stated_in(read_text(text, inventory), inventory, {}, {})


async def heard_stated(text: str, inventory: Optional[PatternInventory] = None, *,
                       context: Iterable[str] = ()) -> Tuple[MeaningFact, ...]:
    """What a text states outright, as `stated`, taken as a listener with memory at hand takes it: where a word
    names several things, memory is asked which each was meant to name (`listening`), against the rest of the text
    and `context`."""
    utterances = read_text(text, inventory)
    held, related = await listening([u.readings for u in utterances], context)
    return _stated_in(utterances, inventory, held, related)


def _stated_in(utterances, inventory, held, related) -> Tuple[MeaningFact, ...]:
    out: List[MeaningFact] = []
    for utterance in utterances:
        chosen = meant(utterance.readings, inventory, held=held, related=related)
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


def _rendered(pattern: Pattern, fillers: Mapping[str, Lexical],
              view: Optional[PatternInventory] = None) -> Tuple[Piece, ...]:
    """The frame's pieces with its fillers in place, written as the writing asks: a capital begins the sentence, a
    filler's capital that only ever began a sentence ("Milk") is not kept inside one, and a frame's word takes the
    shape the word after it asks ("an" before "ocelot"). Properties of the writing, as the reader sets them aside."""
    pieces: List[Piece] = []
    own: List[int] = []
    symbol_first = False
    for element in pattern.form:
        if isinstance(element, Slot):
            filler = list(fillers[element.name].form)
            if not pieces:
                # Mathematics writes its symbols in their own case, first in a sentence or not: "x is 4.".
                value = str(fillers[element.name].value)
                symbol_first = _quantity(value) or (len(value) == 1 and value.isalpha() and value.islower())
            # A capital is kept where the word keeps one: a word held with one inside a sentence ("Monday"), a shape
            # of such a word ("Americans"), or a concept's own name spelled with one ("Paris", "Bostonians").
            if pieces and view is not None and filler[0].text[:1].isupper() \
                    and not view.is_proper(filler[0].text) \
                    and not any(view.is_proper(base) for base in view.names_of_shape(filler[0].text)) \
                    and not str(fillers[element.name].value)[:1].isupper():
                filler[0] = Piece(filler[0].text[:1].lower() + filler[0].text[1:], filler[0].space_after)
            pieces.extend(filler[:-1])
            pieces.append(Piece(filler[-1].text, element.space_after))
        else:
            own.append(len(pieces))
            pieces.append(element)
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


def _said_fillers(view: PatternInventory, pattern: Pattern, slot: str,
                  value: str) -> List[Tuple[Lexical, Optional[Link], str]]:
    """What may say one concept in one slot, as reading would take it there: a filler of that concept linked to the
    slot; with none linked, one of the slot's learned kind (the link proposed, never written); and when no filler
    names the concept at all, the concept's own name, as a word never seen is read as a new name.

    The writing is the slot's too. A filler begun by a word that names nothing ("A dog") does not go where the
    slot's own fillers never had one ("A ?slot0 eats ?slot1."), nor the other way round. Where a word is held both
    capitalized and not, the form written in the slot's place is preferred: a capital begins a sentence, and "Milk"
    is "milk" inside one."""
    first = pattern.form.index(next(e for e in pattern.form if isinstance(e, Slot) and e.name == slot)) == 0
    shapes = view.filler_openings(pattern.key, slot)

    def fits(lexical: Lexical) -> bool:
        return not shapes or _begins_with_structure(view, lexical) in shapes

    def written_here(candidates: List[Lexical]) -> List[Lexical]:
        placed = [lx for lx in candidates if lx.words and lx.words[0][:1].isupper() == first]
        return placed or candidates

    # THE SHAPE THE SLOT TAKES ("?slot0 are ?slot1." takes plurals): a concept goes there written in it -- a form
    # held for it ("Geese"), or its name changed as the learned shape changes names -- and a concept's own name
    # goes where the slot's fillers are names as they are.
    taken = view.shape_of_slot(pattern.key, slot)

    def one_word(lexical: Lexical) -> bool:
        return len(_loose(lexical.words)) == 1

    def in_shape(lexical: Lexical) -> bool:
        if not one_word(lexical):
            return True
        # A word used only as a plural ("tongs") is written in the plural shape as it is.
        other = _loose(lexical.words)[0] != _fold(lexical.value) or view.used_as(lexical.words[0]) == "plural"
        return other if taken else not other

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

    held = [lx for lx in view.lexicals_with_value(value) if view.counts(lx)]
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
    linked = [lx for lx in held if view.link_between(pattern.key, slot, lx.key) is not None and fits(lx)]
    if linked:
        placed = [lx for lx in linked if in_shape(lx)] or linked
        return [(lx, view.link_between(pattern.key, slot, lx.key), "linked") for lx in written_here(placed)]
    if held:
        kind = [lx for lx in held if fits(lx) and view.same_kind(pattern.key, slot, lx.key)]
        if not taken:
            # A held word stands, through a link proposed, only where words used as it is used stand: "smoke", used
            # without "a", not after one. One none of whose uses was counted ("plate", held only in "Plates are
            # round." and "the plate") is used as a word never held would be (`use_of`): not where only uncounted
            # words stand ("Shell plating is plate.").
            admits = view.slot_admits(pattern.key, slot)

            def used(word: str) -> str:
                held_as = view.used_as(word)
                return held_as if held_as is not None else view.use_of(word if view.is_proper(word) else _fold(word))
            kind = [lx for lx in kind if not admits or not one_word(lx) or used(lx.words[0]) in admits]
        placed = [lx for lx in kind if in_shape(lx)]
        # Shaped as the concept's own name is written: "American" is "Americans".
        written = next((lx.surface for lx in written_here(kind)
                        if one_word(lx) and _loose(lx.words)[0] == _fold(value)), value)
        if kind and not placed and as_taken(written):
            shaped = Lexical(form_of(as_taken(written)), value)
            return [(shaped, link(pattern, slot, shaped), "kind")]
        return [(lx, link(pattern, slot, lx), "kind") for lx in written_here(placed or kind)]
    # A CONCEPT NO FILLER NAMES goes, under its own name, only where words used as it is used go (`use_of`): a
    # name ("Thiosulfil") where names are held, never after "a"; a word used without "a" ("paleoanthropology")
    # where such words are; a plural already ("fire tongs") as it is, where plurals go; a counted thing after "a",
    # or in the slot's shape.
    spelled = str(value).replace("_", " ").strip()
    use = view.use_of(spelled)
    admits = view.slot_admits(pattern.key, slot)
    if taken:
        name = spelled if use == "plural" else as_taken(value) if use == "count" else None
    elif use == "plural" or (admits and use not in admits):
        name = None
    else:
        name = spelled
    pieces = form_of(name) if name else ()
    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
    if not pieces or not _may_be_new(pieces, view, MAX_TERM_WORDS):
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


def say(meaning: Meaning, inventory: Optional[PatternInventory] = None) -> Tuple[str, ...]:
    """Every sentence that means exactly this, best first; empty when nothing taught says it.

    Said the way it would be read: a holophrase of this meaning, or a frame of it with a filler for each concept --
    linked to the slot, else of the slot's kind, else the concept's own name. The sentences rank as readings do:
    what they had to suppose, then score. Saying writes nothing."""
    view = inventory if inventory is not None else _live_inventory()
    target = meaning.canonical()
    best: Dict[str, Reading] = {}
    misfits: Dict[str, int] = {}
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
                fitting = _said_fillers(view, pattern, slot, values[slot])
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
    # A filler begun with a letter no word after the one before it has begun with ("an bird": only "eagle",
    # "owl", "ant" ... follow "an") is said last: how a word's form goes with the next word's, as taught.
    return tuple(surface for surface, _ in sorted(best.items(),
                                                  key=lambda kv: (misfits.get(kv[0], 0), _best_first(kv[1]))))


def _misfits(view: PatternInventory, pattern: Pattern, fillers: Mapping[str, Lexical]) -> int:
    """How many fillers begin with a letter that no word held right after the frame's word before them begins with."""
    count = 0
    for here, there in zip(pattern.form, pattern.form[1:]):
        if isinstance(here, Piece) and isinstance(there, Slot) and not _is_mark(here.text):
            filler = fillers[there.name]
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


def _repair(name: str, view: PatternInventory, constructions: Iterable[Construction],
            links: Iterable[Link]) -> Repair:
    """A repair's proposal: the constructions not held yet, the ones held but no longer believed (this pair
    supports them again), and the links not held yet."""
    constructions = tuple(constructions)
    revived = tuple(c for c in constructions if c.key in view and not view.counts(view.get(c.key)))
    return Repair(name, _new(view, constructions), _new(view, links), revived)  # type: ignore[arg-type]


def _gives(pattern: Pattern, values: Mapping[str, str], meaning: Meaning) -> bool:
    filled = _fill(pattern.meaning, values)
    return filled is not None and filled.canonical() == meaning.canonical()


def add_links(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
    """(i) The constructions that read the pair are held, and only their links are missing."""
    words = tuple(p.text for p in form)
    shaped = _written_shapes(view, words)[0]
    best = None
    for pattern in view.item_based():
        if not view.counts(pattern):
            continue
        for spans in _chunkings(pattern.form, words, shaped=shaped):
            frame = _as_written(pattern, words, spans)
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


def item_based_lexical(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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
            frame = _as_written(pattern, words, spans)
            frame = view.get(frame.key) or frame
            new_frame = () if frame.key in view else (frame,)
            for values in _slot_values(pattern, meaning):
                fillers, created = [], []
                for slot, (start, end) in zip(pattern.slots, spans):
                    held = [lx for lx in view.lexicals_with_words(words[start:end])
                            if lx.value == values[slot] and view.counts(lx)]
                    if not held and (not _may_be_new(form[start:end], view, MAX_TERM_WORDS)
                                     or _names_within(view, words[start:end], values[slot])):
                        break
                    filler = held[0] if held else Lexical(form[start:end], values[slot])
                    if not held:
                        created.append(filler)
                    fillers.append((slot, filler))
                else:
                    if not created:
                        continue
                    links = tuple(link(frame, s, lx) for s, lx in fillers
                                  if view.link_between(frame.key, s, lx.key) is None)
                    rank = (len(created) + len(new_frame), len(links), -view.score(pattern), frame.key)
                    if best is None or rank < best[0]:
                        best = (rank, tuple(created) + new_frame, links)
    if best is None:
        return None
    return _repair("item_based_lexical", view, best[1], best[2])


def _names_within(view: PatternInventory, words: Sequence[str], concept: str) -> bool:
    """Whether a run of several words holds, as part of it, a word or run held as a name of this very concept ("All
    birds", where "birds" names `bird`): the rest is not part of the name, and belongs to the frame."""
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


def _shape(fact: MeaningFact) -> Tuple[str, bool, bool, bool, str, str]:
    return (fact.relation, fact.positive, fact.condition, fact.alternative,
            "?" if is_variable(fact.subject) and not _named(fact.subject) else fact.subject,
            "?" if is_variable(fact.obj) and not _named(fact.obj) else fact.obj)


def _role(fact: MeaningFact) -> Tuple[str, bool, bool, bool]:
    """What a fact can only be compared with: the same link kind, the same polarity, on the same side of an `if`,
    and an alternative only with an alternative."""
    return (fact.relation, fact.positive, fact.condition, fact.alternative)


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
    return Fact(f"if_{predicate}" if fact.condition else predicate, (term(fact.subject), term(fact.obj)))


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
                                     original.alternative))
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
    about `about` names nothing of `outside`, what the rest of the sentence names."""
    reached, left = {about}, list(facts)
    while True:
        tied = [f for f in left if reached & set(f.terms())]
        if not tied:
            return not left
        for fact in tied:
            if about not in fact.terms() and outside & set(fact.terms()):
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
            facts = (MeaningFact("instance_of", "?n", kind),)
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
                                   anchor if f.obj == about else f.obj, f.positive) for f in extra)
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
    for filling in _phrase_fillings(view, form, 0, len(form), {}, extend=False, loose=False):
        if _phrase_canonical(filling.anchor, filling.facts) == target:
            return filling.constructions[0], (), ()                  # type: ignore[return-value]
    # Held phrases read it, and only their links are missing (`add_links`, at a phrase's scale): "two hundred and
    # six", where "?slot0 and ?slot1" has held "a hundred" in its first slot and "?slot0 ?slot1" reads "two hundred".
    linked = [filling for filling in _phrase_fillings(view, form, 0, len(form), {}, extend=True, loose=False)
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
    for filling in _phrase_fillings(view, form, 0, len(form), {}, extend=True, loose=False):
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
    chart: Dict[Tuple[int, int], List[_Filling]] = {}
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
        if not view.counts(held) or held.key == general.key or len(held.form) != len(general.form) \
                or held.anchor != general.anchor:
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


def phrase_in_slot(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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
                        slot_links = tuple(link(frame, slot, lx) for (slot, _), lx in zip(others, combo)
                                           if view.link_between(frame.key, slot, lx.key) is None)
                        if view.link_between(frame.key, open_slot, phrase.key) is None:
                            slot_links += (link(frame, open_slot, phrase),)
                        if not created and not slot_links and not links:
                            continue
                        new_frame = () if frame.key in view else (frame,)
                        return _repair("phrase_in_slot", view, tuple(created) + new_frame, links + slot_links)
    return None


def substitution(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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
                or _names_within(view, tuple(p.text for p in theirs), concept_observed):
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
    return _frame_substitution(form, meaning, view)


#: The slot a frame substitution opens, before the frame's slots are named again by their place.
_HERE = slot_name(99)


def _frame_substitution(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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
        if view.counts(held) and len(own) >= 2 and shared >= len(own) - 1:
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
                    names = {name: slot_name(k) for k, name in enumerate(order)}
                    generalized = _renamed(_renamed(held.meaning, {concept_held: _HERE}) or held.meaning, names) \
                        if concept_held in held.meaning.constants() else None
                    if generalized is None:
                        continue
                    start, end = where[_HERE]
                    from core.semantics.cognitive_ingress import MAX_TERM_WORDS
                    if not view.lexicals_with_words(words[start:end]) \
                            and (not _may_be_new(form[start:end], view, MAX_TERM_WORDS)
                                 or _names_within(view, words[start:end], concept_observed)):
                        continue               # a name reading could take as new, as `item_based_lexical` asks
                    try:
                        pattern = Pattern(tuple(Slot(names[e.name], e.space_after) if isinstance(e, Slot) else e
                                                for e in probe), generalized)
                        # A filler held for the word and its concept is the one linked; one is made where none is.
                        pair = tuple(
                            next((lx for lx in view.lexicals_with_words(tuple(p.text for p in pieces))
                                  if lx.value == concept and view.counts(lx)), None) or Lexical(pieces, concept)
                            for pieces, concept in (((held.form[i],), concept_held),
                                                    (form[start:end], concept_observed)))
                    except ValueError:
                        continue
                    given = {names[s]: v for s, v in values.items()}
                    if not (_gives(pattern, {**given, names[_HERE]: concept_observed}, meaning)
                            and _gives(pattern, {**given, names[_HERE]: concept_held}, bound)):
                        continue
                    links = [link(pattern, names[_HERE], f) for f in pair]
                    links += [link(pattern, names[s], f) for s, f in fillers.items()]
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


def addition(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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


def deletion(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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
    chosen.sort(key=lambda item: item[0])
    return chosen, created


def lexical_item_based(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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


def holophrase(form: Tuple[Piece, ...], meaning: Meaning, view: PatternInventory) -> Optional[Repair]:
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
           "INITIAL_SCORE", "COUNTS_FROM", "MeaningFact", "Meaning", "Slot", "Pattern", "Lexical", "Link",
           "KIND_OF", "item_from", "link", "Phrase", "PatternInventory", "Reading", "Stretch", "Utterance", "Repair",
           "REPAIRS",
           "REPAIR_NAMES", "is_variable", "is_slot", "slot_name", "pattern_from", "live_view", "read", "read_text",
           "readings_of", "say", "stated", "heard_stated", "meant", "heard", "heard_which", "listening", "listening_facts", "sense_choices",
           "held_key", "PLACE_KINDS", "place_spoken_of"]
