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
import heapq
import itertools
import math
import re
from dataclasses import dataclass
from typing import (Any, Callable, Dict, FrozenSet, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple,
                    Union)

from core.semantics.relation_types import SemanticRelation
from core.semantics.sentence_machine import Piece, form_of, surface_of

#: English is a domain like any subject: its constructions are what the substrate knows of it, and its competence
#: is measured the way any domain's is.
ENGLISH_DOMAIN = "english"

#: The tag on a memory that holds a construction or a link.
PATTERN_TAG = "language_pattern"

#: What a speaker can want done with what they say.
ACTS = ("tell", "ask", "request")

#: Bound by the situation a sentence is said in, never by the sentence.
SITUATION_VARIABLES = ("?speaker", "?listener", "?shown", "?previous")

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
        `?slot0` is the first open place in the form.
        """
        free = sorted({t for f in self.facts for t in f.terms()
                       if is_variable(t) and not _named(t)})
        best: Optional[str] = None
        for order in itertools.permutations(free):
            names = {variable: f"?v{i}" for i, variable in enumerate(order)}
            facts = " & ".join(sorted(f.renamed(names).render() for f in self.facts))
            asked = ", ".join(names.get(v, v) for v in self.asked)
            text = f"{self.act}: {facts}" + (f" ? {asked}" if asked else "")
            if best is None or text < best:
                best = text
        return best  # type: ignore[return-value]

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


def _is_mark(text: str) -> bool:
    """A piece with no letter or digit in it: a mark of the writing, not a word."""
    return not any(ch.isalnum() for ch in str(text))


def _loose(words: Iterable[str]) -> Tuple[str, ...]:
    """A filler's words as a loose reading looks them up: case folded, marks set aside."""
    return tuple(_fold(w) for w in words if not _is_mark(w))


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
    meaning, every renaming of the unknowns to `?v0, ?v1, ...` tried and the smallest kept."""
    facts = tuple(facts)
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
    """A construction's score and use count, from its belief in this process: its posterior, and how many
    observations support it. One nothing has observed stands at the initial score."""
    from core.reasoning import bayesian_uncertainty as beliefs
    system = beliefs._uncertainty_system
    belief = system.belief_for_claim(item.claim()) if system is not None else None
    if belief is None:
        return INITIAL_SCORE, 0
    return float(belief.posterior_probability), len(belief.evidence_for)


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
        # Words that alternate in one place of frames otherwise the same and meaning the same (`variants_of`): each
        # frame with one of its words left out, and the words held there; and how often two words alternate.
        self._alternation: Dict[Tuple[Tuple[Any, ...], str], set] = {}
        self._alternates: Dict[str, Dict[str, int]] = {}
        # How the held words are used, for placing a word never held (`use_of`, `slot_admits`): found again after
        # anything is added, since a word's use turns on everything it is linked to.
        self._uses: Optional[Tuple[Dict[Tuple[str, str], FrozenSet[str]], Dict[str, str],
                                   Dict[str, Dict[str, int]]]] = None
        self._score = score or _held_score
        for item in items:
            self.add(item)

    def add(self, item: Item) -> bool:
        """Index one construction or link, and move what it changes. False when it is already here."""
        key = item.key
        if key in self._by_key:
            return False
        self._by_key[key] = item
        self._uses = None
        if isinstance(item, (Pattern, Lexical, Phrase)):
            self._words.update(_loose(p.text for p in item.form if isinstance(p, Piece)))
            if isinstance(item, Pattern):
                concepts = item.meaning.constants()
            elif isinstance(item, Lexical):
                concepts = (item.value,)
            else:
                concepts = tuple(t for t in {t for f in item.facts for t in f.terms()} | {item.anchor}
                                 if not is_variable(t))
            self._named.update(_fold(w) for concept in concepts for w in str(concept).replace("_", " ").split())
        if isinstance(item, Pattern):
            self._pattern_keys.append(key)
            self._proper.update(_fold(e.text) for e in item.form[1:] if isinstance(e, Piece) and e.text[:1].isupper())
            if item.slots:
                self._item_based.append(key)
                pieces = [e.text for e in item.form if isinstance(e, Piece)]
                self._needs[key] = (frozenset(pieces), frozenset(_loose(pieces)))
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
                self._note_alternation(item, item.meaning.canonical())
            if isinstance(item.form[-1], Piece):
                self._ends.add(_fold(item.form[-1].text))
            self._letters_of(item)
        elif isinstance(item, Phrase):
            self._phrases.append(key)
            if item.slots:
                pieces = [e.text for e in item.form if isinstance(e, Piece)]
                self._needs[key] = (frozenset(pieces), frozenset(_loose(pieces)))
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
            if key in self._parent:
                self._register(key, item)
        else:
            self._link_keys.append(key)
            self._links[(item.pattern, item.slot, item.lexical)] = key
            self._linked.setdefault((item.pattern, item.slot), []).append(item.lexical)
            self._links_to.setdefault(item.lexical, []).append((item.pattern, item.slot))
            self._join(item.pattern, item.slot, item.lexical)
            frame, filler = self._by_key.get(item.pattern), self._by_key.get(item.lexical)
            if isinstance(filler, Lexical):
                self._filled(item.pattern, item.slot, filler)
            if isinstance(frame, (Pattern, Phrase)) and isinstance(filler, Lexical) and filler.words \
                    and filler.words[0][:1].isupper() and frame.form and not (
                        isinstance(frame.form[0], Slot) and frame.form[0].name == item.slot):
                self._proper.add(_fold(filler.words[0]))
        return True

    def _letters_of(self, item: Union["Pattern", "Phrase"]) -> None:
        """What a form shows of the letters after its words: a word written after a word, and the first letters of
        the fillers of a slot written after a word."""
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

    def _note_alternation(self, item: Union["Pattern", "Phrase"], meaning: str) -> None:
        """Each word of a frame's own, as one that frames otherwise the same and meaning the same hold in its place."""
        shape = tuple(("slot", e.name) if isinstance(e, Slot) else e.text for e in item.form)
        for index, element in enumerate(item.form):
            if not isinstance(element, Piece) or _is_mark(element.text):
                continue
            words = self._alternation.setdefault((shape[:index] + (None,) + shape[index + 1:], meaning), set())
            word = _fold(element.text)
            for other in words - {word}:
                for one, two in ((word, other), (other, word)):
                    counts = self._alternates.setdefault(one, {})
                    counts[two] = counts.get(two, 0) + 1
            words.add(word)

    def variants_of(self, word: str) -> FrozenSet[str]:
        """The words that are this word written in another shape, as the word after it asks: "an" for "a". Two words
        are one in two shapes when frames otherwise the same and meaning the same hold one or the other in the same
        place, in two pairs of frames or more, and the letter after them decides which: the letters written after
        both are, for each, within Yang's tolerance of the letters written after it ("an" before a, e, i, o, "a"
        before consonants, "u" after both). Found from what was taught, never told. Words that alternate after
        the same letters ("is" and "'s") are two ways of saying one thing, not shapes of one word."""
        word = _fold(word)
        mine = self._after.get(word)
        if not mine:
            return frozenset()

        def decided(letters: set, shared: int) -> bool:
            return shared == 0 or (len(letters) >= 2 and shared <= len(letters) / math.log(len(letters)))

        out = set()
        for other, count in self._alternates.get(word, {}).items():
            theirs = self._after.get(other)
            if count >= 2 and theirs:
                shared = len(mine & theirs)
                if decided(mine, shared) and decided(theirs, shared):
                    out.add(other)
        return frozenset(out)

    def written_for(self, word: str, following: str) -> FrozenSet[str]:
        """The frame words this word stands for, written in the shape the word after it asks: "an" before "ocelot"
        stands for "a", since "an" is written before an "o" and "a" is not."""
        if not following or not following[:1].isalpha():
            return frozenset()
        variants = self.variants_of(word)
        if not variants or self.shape_before(word, following[:1]) != _fold(word):
            return frozenset()
        return variants

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
        self._after.setdefault(word, set()).add(letter)
        counts = self._after_count.setdefault(word, {})
        counts[letter] = counts.get(letter, 0) + 1

    def _filled(self, pattern: str, slot: str, filler: Lexical) -> None:
        """A held filler linked to a slot: the letter it begins with after the slot's word before it, and how the
        slot's fillers are written (`shape_of_slot`, `filler_openings`)."""
        self._letter_after(pattern, slot, filler)
        words = _loose(filler.words)
        tally = self._slot_tally.setdefault((pattern, slot), [0, 0, 0])
        if len(words) == 1:
            tally[0 if words[0] == _fold(filler.value) else 1] += 1
        if len(words) <= 1:
            tally[2] += 1
        else:
            runs = self._slot_runs.setdefault((pattern, slot), {})
            runs[words[0]] = runs.get(words[0], 0) + 1

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
        shape is one sighting of a word, not evidence that it builds sentences."""
        word = _fold(word)
        return self.is_structure(word) and word not in self._named and self._shapes.get(word, 0) > 1

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

    def _join(self, pattern: str, slot: str, lexical: str) -> None:
        """A link puts its filler in the kind of its slot's first filler."""
        first = self._linked[(pattern, slot)][0]
        for key in (first, lexical):
            if key not in self._parent:
                self._parent[key] = key
                self._kind_size[key] = 1
                item = self._by_key.get(key)
                if isinstance(item, Lexical):
                    self._register(key, item)
        self._union(first, lexical)

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
        """Whether this filler is of the same learned kind as a filler linked to this slot."""
        kind = self._kind_of_slot(pattern, slot)
        return kind is not None and lexical in self._parent and self._find(lexical) == kind

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
                loose: bool = False) -> "Reading":
        scores = [self._score(c) for c in constructions]
        return Reading(constructions, links, meaning,
                       sum(s for s, _ in scores) / len(scores), sum(u for _, u in scores) / len(scores),
                       proposed=proposed, new=new, loose=loose)

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

    def shape_of_slot(self, pattern: str, slot: str) -> Tuple[Tuple[str, str], ...]:
        """The shapes a slot takes: when most of its one-word fillers are written otherwise than their concept's
        name ("Dogs", "Cats", "Geese" in "?slot0 can ?slot1."), the productive changes, in any context, of the
        changes the words of its kind are written in, the most particular first (the longest run of a name's letters it asks for, then the change more
        words show); none when most are written as the name is. An irregular form ("Geese") counts as written
        otherwise, and a word the same both ways ("Fish") as written as the name."""
        tally = self._slot_tally.get((pattern, slot))
        if not tally or tally[1] * 2 <= tally[0] + tally[1]:
            return ()
        kind = self._kind_of_slot(pattern, slot)
        written = self._kind_changes.get(kind, ()) if kind is not None else ()
        family = [change for change in self._productive_shapes if self._least(change) in written]
        return tuple(sorted(family, key=lambda c: (-len(c[1]), -self._shape_counts[c][0], -len(c[0]), c)))

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

    def _use_model(self) -> Tuple[Dict[Tuple[str, str], FrozenSet[str]], Dict[str, str],
                                  Dict[str, Dict[str, int]]]:
        """How each linked one-word filler is used, per slot, per word, and how the words ending alike are used:
        - `name`: written with a capital inside a sentence (`is_proper`);
        - `plural`: in a slot that takes a shape ("Dogs" in "?slot0 can ?slot1.");
        - `count`: its concept held in a counted slot ("robin" in "A ?slot0 is a bird.");
        - `mass`: a word of the same kind as counted things, held alone and as it is named where a sentence begins,
          and never counted ("Water is cold.", "Biology is hard."). A counted thing never begins a sentence so.
        A word only ever held after "the" or "my", or of another kind ("red"), has none of these."""
        if self._uses is None:
            counted, bare, plural, taken = set(), set(), set(), {}
            for pattern, slot, key in self._links:
                filler = self._by_key.get(key)
                if not isinstance(filler, Lexical) or len(_loose(filler.words)) != 1:
                    continue
                if self.counted_slot(pattern, slot):
                    counted.add(filler.value)
                if (pattern, slot) not in taken:
                    taken[(pattern, slot)] = bool(self.shape_of_slot(pattern, slot))
                if taken[(pattern, slot)]:
                    plural.add(key)
                    continue
                frame = self._by_key.get(pattern)
                if isinstance(frame, (Pattern, Phrase)) and frame.form and isinstance(frame.form[0], Slot) \
                        and frame.form[0].name == slot and _loose(filler.words)[0] == _fold(filler.value):
                    bare.add(filler.value)
            nouns = {self._find(k) for k in self._parent
                     if isinstance(self._by_key.get(k), Lexical) and self._by_key[k].value in counted}
            use: Dict[str, str] = {}
            for key in self._parent:
                filler = self._by_key.get(key)
                if not isinstance(filler, Lexical) or len(_loose(filler.words)) != 1:
                    continue
                word = _loose(filler.words)[0]
                if self.is_proper(word):
                    use[key] = "name"
                elif key in plural:
                    use[key] = "plural"
                elif filler.value in counted:
                    use[key] = "count"
                elif filler.value in bare and self._find(key) in nouns:
                    use[key] = "mass"
            slots: Dict[Tuple[str, str], FrozenSet[str]] = {}
            for where, keys in self._linked.items():
                slots[where] = frozenset(use[k] for k in keys if k in use)
            words: Dict[str, Dict[str, int]] = {}
            for key, how in use.items():
                counts = words.setdefault(_loose(self._by_key[key].words)[0], {})
                counts[how] = counts.get(how, 0) + 1
            # WHICH ENDINGS DECIDE A WORD'S USE, the longest first, as the elsewhere condition orders them: a word
            # that a longer ending decides ("kindness", by "ness") is that ending's, and no evidence for a shorter
            # one ("s"), which "lens" and "abacus" end in too. An ending decides a use within Yang's tolerance, and
            # one other than counted only where it is more reliable than counting is over every word held, the rule
            # it overrides (Albright & Hayes: the more reliable rule wins). A capital shows a name, and a plural is
            # a word's shape, so neither decides an ending.
            by_ending: Dict[str, List[Tuple[str, str]]] = {}
            kept = {"count": 0, "mass": 0}
            for word, counts in words.items():
                how = max(counts.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))[0]
                if how in ("name", "plural"):
                    continue
                kept[how] += 1
                for size in range(1, min(4, len(word) - 1) + 1):
                    by_ending.setdefault(word[len(word) - size:], []).append((word, how))
            counted = kept["count"] / max(1, kept["count"] + kept["mass"])
            endings: Dict[str, str] = {}
            for ending in sorted(by_ending, key=lambda e: (-len(e), e)):
                tally: Dict[str, int] = {}
                for word, how in by_ending[ending]:
                    if any(word[len(word) - size:] in endings for size in range(len(ending) + 1, len(word))):
                        continue
                    tally[how] = tally.get(how, 0) + 1
                total = sum(tally.values())
                if total < 2:
                    continue
                how, most = max(tally.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))
                if most * 2 > total and total - most <= total / math.log(total) \
                        and (how == "count" or most / total > counted):
                    endings[ending] = how
            self._uses = (slots, endings, words)
        return self._uses

    def used_as(self, word: str) -> Optional[str]:
        """How a held one-word filler is used, the most of its uses (`_use_model`), or None when none is held."""
        counts = self._use_model()[2].get(_fold(word))
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: (kv[1], kv[0] == "count", kv[0]))[0]

    def use_of(self, name: str) -> str:
        """How a word no filler holds is used, as its writing and the words held show: a `name` when it is written
        with a capital ("Thiosulfil"); else as its last word is used, when that is held ("fire tongs" as "tongs",
        a plural); else as the held words ending as its last word does are used, the longest ending that decides
        it within Yang's tolerance ("paleoanthropology" is `mass` beside "biology" and "geology"); else `count`, a
        thing counted with "a". A plural is never guessed from an ending: "bus" and "lens" end as plurals do."""
        name = str(name).replace("_", " ").strip()
        if name[:1].isupper():
            return "name"
        last = _fold(name.split()[-1]) if name.split() else ""
        held = self.used_as(last)
        if held is not None and held != "name":
            return held
        endings = self._use_model()[1]
        for size in range(min(4, len(last) - 1), 0, -1):
            if last[len(last) - size:] in endings:
                return endings[last[len(last) - size:]]
        return "count"

    def slot_admits(self, pattern: str, slot: str) -> FrozenSet[str]:
        """The uses of the words a slot holds (`_use_model`), and `count` where it is counted: what a word never
        held may be to stand there."""
        slots = self._use_model()[0]
        admits = set(slots.get((pattern, slot), ()))
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

    @property
    def pattern(self) -> Pattern:
        return self.constructions[0]  # type: ignore[return-value]

    @property
    def key(self) -> str:
        return "+".join(c.key for c in self.constructions)

    @property
    def supposed(self) -> Tuple[bool, int, int]:
        """How much the reading had to suppose: read loosely, how many words it took as new names, how many links it
        proposed. Words, not names: "blue ball" taken as one new name supposes more than "ball" alone beside the
        known word "blue"."""
        return (self.loose, sum(len(_loose(lexical.words)) for lexical in self.new), len(self.proposed))


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
    if not pieces or len(pieces) > min(MAX_TERM_WORDS, max(longest, 1)) or any(_is_mark(p.text) for p in pieces):
        return False
    if len(pieces) == 1:
        # One word is a name unless it is a word that names nothing ("a"); a word held so far only inside forms
        # ("cup" in "That is my cup.") may still name a thing, and a taught meaning names it.
        return not view.names_nothing(pieces[0].text)
    return not any(view.is_structure(p.text) for p in pieces)


def _fillers(view: PatternInventory, pattern: Pattern, slot: str, pieces: Tuple[Piece, ...], *,
             extend: bool, loose: bool) -> List[Tuple[Lexical, Optional[Link], str]]:
    """What may stand in one slot for these words: (filler, the link it stands through, how). A held link is
    `linked`; with `extend`, a filler of the slot's kind stands through a `kind` link proposed, and words nothing
    held covers stand as a `new` filler through a link proposed."""
    words = tuple(p.text for p in pieces)
    if loose and any(_is_mark(w) for w in words):
        return []          # a mark inside what was said separates; no filler spans it
    held = view.lexicals_with_words(_loose(words) if loose else words, loose=loose)
    out: List[Tuple[Lexical, Optional[Link], str]] = []
    for lexical in held:
        if not view.counts(lexical):
            continue
        linked = view.link_between(pattern.key, slot, lexical.key)
        if linked is not None:
            out.append((lexical, linked, "linked"))
        elif extend and view.same_kind(pattern.key, slot, lexical.key):
            out.append((lexical, link(pattern, slot, lexical), "kind"))
    # A word held in another case is not a new word: it is read as the word it is, loosely.
    if extend and not held and not view.lexicals_with_words(_loose(words), loose=True):
        # Nor is a held word written in a shape learned from the fillers ("tables", where "table" is held), or a
        # held concept's own name: it stands where that word would, as that word's concept.
        if len(pieces) == 1:
            for name in view.names_of_shape(words[0]):
                for base in view.holding(name):
                    if view.counts(base) and (view.link_between(pattern.key, slot, base.key) is not None
                                              or view.same_kind(pattern.key, slot, base.key)):
                        shaped = Lexical(pieces, base.value)
                        out.append((shaped, link(pattern, slot, shaped), "kind"))
                        break
        if _may_be_new(pieces, view, view.longest_filler(pattern.key, slot)):
            new = Lexical(pieces, surface_of(pieces))
            out.append((new, link(pattern, slot, new), "new"))
    return out


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


def _composed(facts: Iterable[MeaningFact], anchor: Optional[str],
              fillings: Mapping[str, _Filling]) -> Optional[Tuple[Optional[str], Tuple[MeaningFact, ...]]]:
    """A construction's facts, and its anchor when it is a phrase, with every slot filled; None when that makes no
    meaning (a fact of its own stated twice).

    A slot's variable becomes its filling's anchor, and the filling's facts join. Where the construction uses a slot
    only as a thing's kind (`instance_of(?x, ?slot0)`) and the filling stands for a thing, the filling describes that
    thing: its facts are said of `?x`, in place of `instance_of(?x, ?slot0)`. That is a rule of the meaning language,
    a kind and its instances, not of English. A filling's own unknowns are renamed apart from everything else's, and
    what it says of a thing named only in a condition is said in the condition too."""
    out = list(facts)
    added: List[MeaningFact] = []
    names: Dict[str, str] = {}
    fresh = itertools.count()
    for slot, filling in fillings.items():
        free = {t for f in filling.facts for t in f.terms()} | {filling.anchor}
        apart = {v: f"?u{next(fresh)}" for v in sorted(free) if is_variable(v) and not _named(v)}
        thing_of = apart.get(filling.anchor, filling.anchor)
        said = [f.renamed(apart) for f in filling.facts]
        uses = [f for f in out if slot in f.terms()]
        described = (slot != anchor and uses and is_variable(thing_of) and not _named(thing_of)
                     and all(f.relation == "instance_of" and f.obj == slot and f.subject != slot and f.positive
                             and not f.alternative for f in uses)
                     and len({(f.subject, f.condition) for f in uses}) == 1)
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
    for lexical, held, how in _fillers(view, frame, slot, pieces[start:end], extend=extend, loose=loose):
        if how == "linked":
            out.append(_Filling(lexical.value, (), (lexical,), links=(held,)))
        else:
            out.append(_Filling(lexical.value, (), (lexical,), proposed=(held,),
                                new=(lexical,) if how == "new" else ()))
    for filling in _phrase_fillings(view, pieces, start, end, chart, extend=extend, loose=loose):
        top = filling.constructions[0]
        held = view.link_between(frame.key, slot, top.key)
        if held is not None:
            out.append(_Filling(filling.anchor, filling.facts, filling.constructions,
                                filling.links + (held,), filling.proposed, filling.new))
        elif extend and view.same_kind(frame.key, slot, top.key):
            out.append(_Filling(filling.anchor, filling.facts, filling.constructions,
                                filling.links, filling.proposed + (link(frame, slot, top),), filling.new))
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
    if not words or (loose and any(_is_mark(w) for w in words)):
        return []
    same = (lambda word, text: word == _fold(text)) if loose else str.__eq__
    missing = (lambda piece: _is_mark(piece.text)) if loose else (lambda piece: False)
    shaped, stood = _written_shapes(view, words, pieces[end].text if end < len(pieces) else "", loose=loose)
    have = frozenset(words) | stood
    out: List[_Filling] = []
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
                                        tuple(x for c in combo for x in c.new)))
    chart[key] = out
    return out


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
    shaped, stood = _written_shapes(view, words, loose=loose)
    have = frozenset(words) | stood
    chart: Dict[Tuple[int, int], List[_Filling]] = {}
    for pattern in view.item_based():
        if not view.may_read(pattern.key, have, loose) or not view.counts(pattern):
            continue
        form = pattern.form
        anchors = sum(1 for e in form if isinstance(e, Piece) and not _is_mark(e.text))
        for spans in _chunkings(form, words, same, missing, shaped):
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
                            proposed=tuple(x for c in combo for x in c.proposed), new=new, loose=loose))
    return sorted(out, key=_best_first)


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
    never resolved here: which one is meant is decided by the situation and the scores, by whoever is listening.
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
            if any(_is_mark(w) for w in words):
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


def stated(text: str, inventory: Optional[PatternInventory] = None) -> Tuple[MeaningFact, ...]:
    """What a text states outright between named things: the asserted facts of each utterance that reads, to one
    meaning, as a telling. A question or a request states nothing; a conditional states none of its facts; of
    alternatives, none is stated, only that one holds; a fact still naming an unknown or the situation has nothing
    here to name it by; and an utterance read to more than one meaning states nothing, because which one was meant
    is not the reader's to pick."""
    out: List[MeaningFact] = []
    for utterance in read_text(text, inventory):
        readings = utterance.readings
        if not readings or len({r.meaning.canonical() for r in readings}) > 1:
            continue
        meaning = readings[0].meaning
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
    for element in pattern.form:
        if isinstance(element, Slot):
            filler = list(fillers[element.name].form)
            # A capital is kept where the word keeps one: a name held with one inside a sentence ("Monday"), or a
            # concept's own name, spelled so ("Paris").
            if pieces and view is not None and filler[0].text[:1].isupper() \
                    and not view.is_proper(filler[0].text) \
                    and surface_of(tuple(filler)) != str(fillers[element.name].value).replace("_", " "):
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
    if pieces and pieces[0].text[:1].islower():
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
    linked = [lx for lx in held if view.link_between(pattern.key, slot, lx.key) is not None and fits(lx)]
    if linked:
        placed = [lx for lx in linked if in_shape(lx)] or linked
        return [(lx, view.link_between(pattern.key, slot, lx.key), "linked") for lx in written_here(placed)]
    if held:
        kind = [lx for lx in held if fits(lx) and view.same_kind(pattern.key, slot, lx.key)]
        placed = [lx for lx in kind if in_shape(lx)]
        if kind and not placed and as_taken(value):
            shaped = Lexical(form_of(as_taken(value)), value)
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
    return [(new, link(pattern, slot, new), "new")]


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
    """(ii) An item-based construction reads the pair but for what fills a slot: that filler is created."""
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
                    if not held and _names_within(view, words[start:end], values[slot]):
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


def _what_the_slot_adds(pattern: Pattern, values: Mapping[str, str], slot: str,
                        meaning: Meaning) -> Optional[Tuple[str, Tuple[MeaningFact, ...]]]:
    """What the pair's meaning says through one slot of a construction whose other slots hold `values`: the anchor
    the slot stands for and the facts about it that nothing else in the construction states -- a phrase's meaning.
    None when the construction does not otherwise give the pair's meaning, or what is left is not about the slot's
    thing.

    Where the construction uses the slot only as a thing's kind (`instance_of(?x, ?slot0)`), the phrase stands for
    the thing: it is a `?slot0` and whatever else is said of it. Elsewhere it stands for what fills the slot."""
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
        if any(about not in f.terms() for f in extra) or any(f.condition != extra[0].condition for f in extra):
            continue
        facts += tuple(MeaningFact(f.relation, anchor if f.subject == about else f.subject,
                                   anchor if f.obj == about else f.obj, f.positive) for f in extra)
        return anchor, facts
    return None


def _phrase_repair(form: Tuple[Piece, ...], anchor: str, facts: Tuple[MeaningFact, ...],
                   view: PatternInventory) -> Optional[Tuple[Phrase, Tuple[Construction, ...], Tuple[Link, ...]]]:
    """A phrase pair learned as a sentence pair is: read by a held phrase (nothing to create); or generalized over
    the held fillers it contains, a phrase with a slot for each (lexical → item-based, at the phrase's scale); or,
    when neither applies, held whole. Returns the phrase that stands for it, what to create, and its links."""
    target = _phrase_canonical(anchor, facts)
    for filling in _phrase_fillings(view, form, 0, len(form), {}, extend=False, loose=False):
        if _phrase_canonical(filling.anchor, filling.facts) == target:
            return filling.constructions[0], (), ()                  # type: ignore[return-value]
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
                return general, (general,) + tuple(written), tuple(link(general, slot_name(i), lx)
                                                                   for i, (_, _, lx) in enumerate(chosen))
    try:
        whole = Phrase(form, anchor, facts)
    except ValueError:
        return None
    return whole, (whole,), ()


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
                        learned = _phrase_repair(form[start:end], adds[0], adds[1], view)
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
    if any(_is_mark(w) for w in words):
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
           "readings_of", "say", "stated"]
