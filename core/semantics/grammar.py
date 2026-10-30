"""Reading a sentence by its grammar: what each word is, and general rules that put words together, the meaning of
the whole built from the meanings of its parts.

A COMPILER READS A PROGRAM IT HAS NEVER SEEN, the first time, because it has a grammar and the meaning of each
piece, never because it saw a program like it. The composers before this one (`composition`, and the readers before
it) learned English as sentences remembered and read a new sentence by the remembered ones it looked like; real
sentences rarely look enough like any, and the decisions taken where none did were wrong one time in three
(2026-10-20: the most specific situations met decided 71% of what a word stands for, 2% wrong; the rest were decided
by coarser ones, 9% to 75% wrong). Here a sentence is read the way the Parallel Meaning Bank's own meanings were
first made: a categorial grammar (CCG, Steedman 2000) and its meaning built with it (Bos 2008).

THREE PARTS:

- THE WORDS (`Lexicon`). Each word's category says what it combines with and what it makes: "the" makes a thing
  from a kind (`NP/N`), "detects" a sentence from a thing after it and a thing before it (`(S[dcl]\\NP)/NP`). Its
  meaning says what its part of the sentence holds: "detects" a detecting, done by what stands before it, done to
  what stands after. The words of English's grammar ("the", "is", "who", "not") are taught as data
  (`data/grammar/english.json`); every other word's categories come from what kind of word it is (a noun, a verb)
  and how it is used (a verb with an object), as held for it, and which link each of a verb's places makes, what a
  preposition means and how a thing is someone's, from the sentences taught with their meanings (`Lexicon.learn`).
- THE RULES (`_combine`): a function applied to what it takes, to its right (`X/Y Y => X`) or left (`Y X\\Y => X`);
  two functions composed (`X/Y Y/Z => X/Z`), which lets "What did you see?" ask what was seen; words joined by "and".
  They are not English: they are how any categorial grammar combines.
- THE MEANING (`_spell_out`): the facts the words' meanings hold once every place is filled, said in the meaning
  language as `docs/TEACHING.md` says it.

EVERY READING THE GRAMMAR ALLOWS IS BUILT ONCE, never multiplied out (a chart, Cocke-Younger-Kasami), and of the
readings of the whole the one whose words are used most as they are used is taken: a word's evidence for each of its
categories (how often it is that kind of word, how often a verb takes an object) is held for it, and the sum over
the words is exact over the chart (dynamic programming). A sentence the grammar cannot read whole is not read
(`Reading.missing` says which words it could not join), never guessed.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import heapq
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from core.semantics.derived_reader import Meaning, MeaningFact, is_variable
from core.semantics.relation_types import is_worded, worded
from core.semantics.sentence_machine import _ADDRESS

#: The grammar of English as taught: its grammar words, the categories of each kind of word, the default links.
ENGLISH = Path(__file__).resolve().parents[2] / "data" / "grammar" / "english.json"

Term = Union[int, str]


# ── categories ────────────────────────────────────────────────────────────────────────────────────────────────────

class Atom:
    """A category of its own: `S[dcl]`, `NP`, `N`, `PP[by]`; its feature (a value, a variable, or None for any) and
    the term it stands for (a variable, a constant, or None)."""
    __slots__ = ("base", "feat", "ref")

    def __init__(self, base: str, feat: Optional[Term], ref: Optional[Term]):
        self.base, self.feat, self.ref = base, feat, ref

    def __repr__(self) -> str:
        return show(self)


class Fn:
    """A category taking another: `res/arg` takes `arg` to its right, `res\\arg` to its left."""
    __slots__ = ("res", "slash", "arg")

    def __init__(self, res: "Cat", slash: str, arg: "Cat"):
        self.res, self.slash, self.arg = res, slash, arg

    def __repr__(self) -> str:
        return show(self)


Cat = Union[Atom, Fn]
_TOKEN = re.compile(r"\s*(\(|\)|/|\\|[A-Za-z]+(?:\[[^\]]*\])?(?:\.[^/\\()\s]+)?)")


def parse_category(text: str) -> Cat:
    """A category as written in the grammar's data: `(S[dcl].e\\NP.x)/NP.y`. A lowercase letter or word after a dot
    is a variable of the word's meaning, `@` the word's own name, `?speaker` a term of the situation; an uppercase
    feature (`S[F]`) is a variable that agrees."""
    tokens = [t for t in _TOKEN.findall(text) if t.strip()]
    if "".join(tokens) != re.sub(r"\s+", "", text):
        raise ValueError(f"not a category: {text!r}")
    at = 0

    def primary() -> Cat:
        nonlocal at
        token = tokens[at]
        at += 1
        if token == "(":
            inner = category()
            if tokens[at] != ")":
                raise ValueError(f"unbalanced category: {text!r}")
            at += 1
            return inner
        m = re.fullmatch(r"([A-Za-z]+)(?:\[([^\]]*)\])?(?:\.(.+))?", token)
        if not m:
            raise ValueError(f"not a category: {text!r}")
        return Atom(m.group(1), m.group(2), m.group(3))

    def category() -> Cat:
        nonlocal at
        left = primary()
        while at < len(tokens) and tokens[at] in ("/", "\\"):
            slash = tokens[at]
            at += 1
            left = Fn(left, slash, primary())
        return left

    out = category()
    if at != len(tokens):
        raise ValueError(f"not a category: {text!r}")
    return out


def show(cat: Cat, refs: bool = True) -> str:
    if isinstance(cat, Atom):
        text = cat.base + (f"[{cat.feat}]" if cat.feat is not None else "")
        return text + (f".{cat.ref}" if refs and cat.ref is not None else "")
    res = show(cat.res, refs)
    arg = show(cat.arg, refs)
    return f"({res}{cat.slash}{arg})" if isinstance(cat.res, Fn) or True else f"{res}{cat.slash}{arg}"


def _walk(t: Optional[Term], s: Mapping[int, Term]) -> Optional[Term]:
    while isinstance(t, int) and t in s:
        t = s[t]
    return t


def _bind(a: Optional[Term], b: Optional[Term], s: Dict[int, Term]) -> bool:
    a, b = _walk(a, s), _walk(b, s)
    if a is None or b is None or a == b:
        return True
    if isinstance(a, int):
        s[a] = b
        return True
    if isinstance(b, int):
        s[b] = a
        return True
    return False


def _unify(c1: Cat, c2: Cat, s: Dict[int, Term]) -> bool:
    """Whether two categories are one, binding their variables in `s`. A feature left open matches any."""
    if isinstance(c1, Atom):
        if not isinstance(c2, Atom) or c1.base != c2.base:
            return False
        return _bind(c1.feat, c2.feat, s) and _bind(c1.ref, c2.ref, s)
    if not isinstance(c2, Fn) or c1.slash != c2.slash:
        return False
    return _unify(c1.res, c2.res, s) and _unify(c1.arg, c2.arg, s)


def _apply(cat: Cat, s: Mapping[int, Term]) -> Cat:
    if not s:
        return cat
    if isinstance(cat, Atom):
        return Atom(cat.base, _walk(cat.feat, s), _walk(cat.ref, s))
    return Fn(_apply(cat.res, s), cat.slash, _apply(cat.arg, s))


def _key(cat: Cat) -> str:
    """A category written with its variables numbered as they come, so two of one shape are one key."""
    seen: Dict[int, int] = {}

    def term(t: Optional[Term]) -> str:
        if t is None:
            return ""
        if isinstance(t, int):
            return "#" + str(seen.setdefault(t, len(seen)))
        return t

    def walk(c: Cat) -> str:
        if isinstance(c, Atom):
            return f"{c.base}[{term(c.feat)}]{term(c.ref)}"
        return f"({walk(c.res)}{c.slash}{walk(c.arg)})"
    return walk(cat)


def _same_shape(c1: Cat, c2: Cat) -> bool:
    """Whether two categories are of one shape, their terms aside: `X/X` modifies what it takes."""
    if isinstance(c1, Atom):
        return isinstance(c2, Atom) and c1.base == c2.base
    return isinstance(c2, Fn) and c1.slash == c2.slash and _same_shape(c1.res, c2.res) and _same_shape(c1.arg, c2.arg)


def _takes_its_head(fn: Cat) -> bool:
    """Whether a function is headed by what it takes, as CCGbank heads them (Hockenmaier and Steedman 2007): a
    modifier (`X/X`: "very", "red"), or a thing raised over what takes it (`S/(S\\NP)`, `(S\\NP)\\((S\\NP)/NP)`:
    "nothing" as the doer or what is done to): the doing is the head, the thing joined to it. Headed by the raised
    thing, "They suspected nothing." joined "They" to "nothing", which the structure view rightly made unlikely, and
    read "nothing" a thing; a raised "nothing" was headed so only where the tagger called it a pronoun (`_asking`),
    as main's did and lyric_dev2's did not (2026-10-29)."""
    return isinstance(fn, Fn) and (_same_shape(fn.res, fn.arg) or (isinstance(fn.arg, Fn)
                                                                   and _same_shape(fn.res, fn.arg.res)))


def _shape(cat: Cat) -> str:
    """A category's shape, its terms and features aside: what two categories must share to be one (`_unify`)."""
    if isinstance(cat, Atom):
        return cat.base
    return f"({_shape(cat.res)}{cat.slash}{_shape(cat.arg)})"


def _offers(cat: Cat) -> Set[str]:
    """The shapes a stretch of this category stands as to what combines with it: itself, and each result along its
    spine, as composition takes one (X/Y with Y/Z, Y\\Z with X\\Y, X/Y with (Y/Z)/W)."""
    out = {_shape(cat)}
    while isinstance(cat, Fn):
        cat = cat.res
        out.add(_shape(cat))
    return out


def _wants(cat: Cat) -> Tuple[Optional[str], Set[str]]:
    """The shapes a stretch of this category takes: after it (X/Y: Y), and before it (X\\Y: Y; and a phrase still
    taking what follows that takes what comes before it, (X\\Y)/Z: Y, as a thing raised to a verb taking what follows
    it and a preposition left without its thing combine with what is before them)."""
    if not isinstance(cat, Fn):
        return None, set()
    before = {_shape(cat.arg)} if cat.slash == "\\" else set()
    if isinstance(cat.res, Fn) and cat.res.slash == "\\":
        before.add(_shape(cat.res.arg))
    return (_shape(cat.arg) if cat.slash == "/" else None), before


def _takes_noun(cat: Cat, ref: Term) -> bool:
    """Whether a category still takes a noun of this thing (`NP.x/N.x`, "is a" `(S\\NP)/N.x`): what a determiner
    says which of is yet to come."""
    while isinstance(cat, Fn):
        if isinstance(cat.arg, Atom) and cat.arg.base == "N" and cat.arg.ref == ref:
            return True
        cat = cat.res
    return False


def _leaves_as_is(cat: Cat) -> bool:
    """Whether a category takes what it makes, the same in every term: `NP.x/NP.x`, `S[F].a/S[F].a`; not
    `S[em].c/S[dcl].c` ("that" making a clause one that is taken)."""
    return isinstance(cat, Fn) and show(cat.res) == show(cat.arg)


# ── signs: a stretch of words read, its category and its meaning ──────────────────────────────────────────────────

#: A piece of meaning: (what it says, its terms ..., the word that said it). What each says is spelled out in the
#: meaning language by `_spell_out`.
Piece = Tuple[Any, ...]
#: In the grammar's data, a variable of a word's meaning is a lowercase letter, with a digit or not ("x", "e2");
#: any other word is itself ("subject", "has_member", "necessary").
_MEANING_VARIABLE = re.compile(r"[a-z][0-9]?")


@dataclass
class Sign:
    """A stretch of the sentence read: its category, the pieces of its meaning, how sure the reading of its words is
    (summed logarithms of each word's evidence for the category it is read in), the words it covers, how it was
    put together, and its word that heads it."""
    cat: Cat
    pieces: Tuple[Piece, ...]
    score: float
    start: int
    end: int
    rule: str
    kids: Tuple["Sign", ...] = ()
    head: int = -1
    entry: str = ""
    #: Whether the word's entry lets it compose across what it takes (`Entry.crossing`).
    crossing: bool = False
    #: Of a combination not yet kept, what its two parts' variables are bound to: its pieces are its parts' pieces
    #: so bound, made only once the chart keeps it (`Grammar.chart`).
    binding: Optional[Dict[int, Term]] = None
    #: The word the stretch is about, as the treebanks join words: its head, but what a word of the kinds that only
    #: mark another takes ("the dog": dog; "in the park": park). Set as the chart weighs how its parts were joined
    #: (`Grammar._joined`).
    word: int = -1


#: Variables are numbered from here, so no variable is ever a word's place in its sentence.
FIRST_VARIABLE = 1_000_000


def _substitute(pieces: Iterable[Piece], s: Mapping[int, Term]) -> Tuple[Piece, ...]:
    if not s:
        return tuple(pieces)
    return tuple(tuple(_walk(p, s) if type(p) is int and p >= FIRST_VARIABLE else p for p in piece)
                 for piece in pieces)


# ── the words ─────────────────────────────────────────────────────────────────────────────────────────────────────

class Words:
    """What is held of each word, as the grammar asks it; on main memory's (`memory_agent`), in an experiment from
    files. Every method has a plain answer for a word nothing is held of."""

    def uses(self, word: str) -> Mapping[str, float]:
        """How often the word (as written: a capitalised word may be a name) is used each way: as each kind of word (`NOUN`, `VERB`, `ADJECTIVE`,
        `ADVERB`, `NAME`, `NUMERAL`, `PREPOSITION`), and in each of the ways the grammar's own words are read
        (`det`, `pron`, `be:ng`, `wh:subject`: each grammar entry's `use`)."""
        return {}

    def name(self, word: str, cls: str) -> str:
        """The name of the word as a word of that kind: "took" as a verb is `take`."""
        return word.lower()

    def spelled(self, word: str) -> Optional[str]:
        """How memory holds words joined by hyphens as one word ("bullet-proof"): as written, with its parts together
        (`bulletproof`) or apart (`ice cream`); None where it holds it in none of these."""
        return word.lower()

    def lexeme(self, word: str, cls: str) -> str:
        """The word this one is a form of, as a word of that kind ("paints" `paint`); the word itself where none."""
        return word.lower()

    def verb_forms(self, word: str) -> Mapping[str, float]:
        """How often the word is used as each form of its verb: `base`, `present`, `third`, `past`, `participle`,
        `ing`."""
        return {}

    def frames(self, name: str) -> Mapping[str, float]:
        """How often the verb is used in each frame (`intransitive`, `transitive`, `ditransitive`, `to`, `that`)."""
        return {}

    def known_words(self, words: Sequence[str]) -> Mapping[str, str]:
        """Each kind of word memory knows these words as one word of, with the name it knows them under: "credit
        card" a thing, "fed up" a quality, "kind of" an adverb. Nothing where it knows them as none."""
        return {}

    def known_name(self, words: Sequence[str]) -> Optional[str]:
        """The name memory knows these words as together ("credit card", "phone number"), or None."""
        return None

    def known_verb(self, words: Sequence[str]) -> Optional[str]:
        """The name memory knows a verb and the word after it as together ("pass away"), or None."""
        return None

    def words_for(self, name: str, cls: str) -> List[str]:
        """What is written for a thing as a word of the class, every form, the word most used for it first: `name` the
        other way (`Grammar.say`). Nothing where memory holds no word for it."""
        return []

    def kinds(self, name: str, cls: str) -> List[str]:
        """What memory holds the word's thing to be a kind of, nearest first."""
        return []

    def defined(self, name: str) -> List[str]:
        """What a thing held as a kind of nothing (an adjective's sense) is defined with: "Norwegian" Norway."""
        return []

    def is_person(self, name: str, particular: bool = False) -> Optional[bool]:
        """Whether the thing is a person: True, False where memory holds what it is and a person is not among it, None
        where it holds nothing of it (`grammar_words.Knowledge.is_person`)."""
        return None

    def is_time(self, term: str) -> Optional[str]:
        """Whether the term is a time, and which: a point in time (`point`: a year, a day, an hour of the clock) or
        a stretch of it (`stretch`: an hour, a week); None for no time."""
        return None

    def like(self, word: str, what: str) -> Mapping[str, float]:
        """How words spelled like this one (ending as it does; for `frames`, all verbs) are used: `uses`, `forms`,
        `shapes`, `frames`, as `uses`, `verb_forms`, `verb_shapes`, `frames` count them."""
        return {}

    def capitalized(self, word: str) -> Mapping[str, float]:
        """What memory holds the word, written capitalised, to be: a name (`NAME`: "Lincoln") or a kind of thing
        (`NOUN`: "Estonian", a language), each as many times as it holds a sense so."""
        return {}

    def degree(self, word: str) -> Optional[str]:
        """Whether an adjective's form compares ("bigger": `more`) or is the most ("biggest": `most`); None where it
        is its plain form."""
        return None

    def verb_shapes(self, word: str) -> Mapping[str, float]:
        """How often the word, an -ing or -ed form of a verb, says a doing that stands as a thing (`thing`), after
        a thing it tells of (`after`), or as a doing (`doing`)."""
        return {}

    def noun_alone(self, word: str) -> Mapping[str, float]:
        """How often the noun is said with nothing before it saying which ("water", "farmers": `bare`) and with a
        word that does ("the", "my": `determined`)."""
        return {}

    def bare_modifier(self, word: str) -> Mapping[str, float]:
        """How often the word, heading a thing said of a doing with no preposition before it, tells of the doing ("One
        morning the dog ran.", "We met last week.": `modifier`), and how often it is used as a noun otherwise."""
        return {}

    def hear_read(self, uses: Iterable[Tuple[str, str]], verbs: Iterable[Tuple[str, str, str, str]],
                  weight: float) -> None:
        """How a sentence read used its words (`Lexicon.uses_in`), counted as much as `weight`
        (`GrammarView._learn_from_reading`). Words that count nothing learn nothing from it."""

    def hear_kind(self, subject: str, relation: str, kind: str) -> None:
        """What memory has just taken in a thing to be (`isa`, `instance_of`: "Harvard is a university."), as
        `kinds` answers from then on (`MemoryAgent.link_concepts`). Words that hold no kinds learn nothing from it."""

    def said_together(self, verb: str, word: str, ends: Optional[bool] = None) -> Tuple[float, float]:
        """How often the verb is said with the word after it as one verb ("take in"), and how often with that word
        after it otherwise ("sleep in the car"); `ends`, of those where the clause ends after the two (True) or goes
        on (False), where that is held."""
        return 0.0, 0.0

    def adjectives_after(self, followed: bool = False) -> Tuple[float, float]:
        """How often an adjective telling of a thing is said after it, and before; `followed`, an adjective with words
        after it in its phrase ("a number greater than 1")."""
        return 0.0, 0.0

    def asking(self, use: str) -> Tuple[float, float]:
        """How often a word is used this way in a sentence that asks, and in one that tells, every word together."""
        return 0.0, 0.0

    def doing_after(self, use: str) -> Tuple[float, float]:
        """How often a word used this way has a doing's -ing form after it, and how often not, every word together."""
        return 0.0, 0.0

    def to_purposes(self) -> Tuple[float, float]:
        """How often a "to" clause says what a doing is for ("Rex ran to catch the ball."), and how often what a
        verb takes ("wants to swim")."""
        return 0.0, 0.0

    def orders(self) -> Tuple[float, float]:
        """How often a sentence that tells is an order, a doing asked of the listener with its doer unsaid ("Read the
        links."), and how often it says its doing's doer ("The dog barked."), every sentence together."""
        return 0.0, 0.0

    def bare_relatives(self) -> Tuple[float, float]:
        """How often a clause telling of a thing before it is said without "that", "who" or "which", and with."""
        return 0.0, 0.0

    def plural(self, word: str) -> bool:
        return False

    def sounds(self, word: str) -> List[str]:
        """How the word is said, each way its phones, as a word recorded whole holds them (the CMU Pronouncing
        Dictionary's: "wall" `W AO1 L`). Nothing where memory holds none."""
        return []

    def said_before(self, word: str) -> Mapping[str, Mapping[str, float]]:
        """Of the forms of the word the analysts mark nothing apart ("a" and "an"), each, the word itself among them,
        with how often it was said before a word beginning with each first sound (`AW`: "an hour"). Nothing where the
        word has no such forms."""
        return {}

    def subjects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
        """Of a finite form of a verb ("is", "paints"), how often its subjects were of each class with each of the
        features subjects share with verbs or are marked subjects by: `("NOUN", "Number=Sing")`, `("PRONOUN",
        "Case=Nom|Number=Sing|Person=1")`; of no word, every finite form's together. Nothing where memory holds none."""
        return {}

    def took_subjects(self) -> Tuple[str, ...]:
        """Every finite form memory holds a subject of ("is", "paints"), so that what the verbs written as a form is
        took may be gathered where that form took nothing of its own (`Grammar._subjects_like`). Nothing where
        memory holds none."""
        return ()

    def objects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
        """Of a verb ("misled", "paints"), how often what stood as its object was of each class with each of those
        features: `("PRONOUN", "Case=Acc|Number=Sing|Person=1")`; of no word, every verb's together. This is what
        says a thing standing after a verb is written as "me" and not as "I". Nothing where memory holds none."""
        return {}

    def nouns(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
        """Of a determiner ("a", "the"), how often the nouns it was said with were of each class with each of those
        features: `("NOUN", "Number=Sing")`; of no word, every determiner's together. Nothing where memory holds none."""
        return {}

    def predicated(self, said: Optional[Tuple[str, str]] = None) -> Mapping[Tuple[str, str], float]:
        """Of what a copula said a thing to be, by its class and those features (`("NOUN", "Number=Sing")`: "a
        partition"), how often the things it was said of were of each class with each; of nothing, every such thing
        together. Nothing where memory holds none."""
        return {}

    def form_features(self, word: str, cls: str) -> Mapping[str, float]:
        """What form the word is as a word of the class, as the forms memory holds say, how often each: "walls" as a
        noun `Number=Plur`. Nothing where memory holds none."""
        return {}


@dataclass(frozen=True)
class Entry:
    """One way a word is read: its category and its meaning's pieces (written as in the grammar's data), the kind
    of word it is read as, its name, and its evidence (a logarithm)."""
    cat: str
    sem: Tuple[Tuple[str, ...], ...]
    cls: str
    name: str
    score: float
    label: str = ""
    crossing: bool = False


# ── sentences derived by hand ─────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Derived:
    """One sentence as it was derived by hand in a categorial grammar (a CCG derivation checked by hand: the Parallel
    Meaning Bank's gold): each word with the category it has in this sentence, written as the bank writes it
    ("(s:dcl\\np)/np"), its part of speech (Penn's), its lemma, its WordNet sense ("" for none), its VerbNet roles, the
    bank's semantic tag, and where it is in `text`; how the words were combined (`tree`: a word is its place, a
    combination `(rule, category, ...what it combines)`, a category a rule names written as a string); and where it
    was met (`said_in`, the document; `part`, which of its sentences). A word of several is one word, its parts
    joined by "~" ("Burt~Lancaster"). What a word takes beside the words around it is learned from these
    (`Lexicon.hear_derived`)."""

    text: str
    words: Tuple[str, ...]
    categories: Tuple[str, ...]
    tags: Tuple[str, ...]
    lemmas: Tuple[str, ...]
    senses: Tuple[str, ...]
    roles: Tuple[Tuple[str, ...], ...]
    semantics: Tuple[str, ...]
    spans: Tuple[Tuple[int, int], ...]
    tree: Any = ()
    said_in: str = ""
    part: int = 1

    def __post_init__(self):
        n = len(self.words)
        if not n or any(len(x) != n for x in (self.categories, self.tags, self.lemmas, self.senses, self.roles,
                                              self.semantics, self.spans)):
            raise ValueError("a derived sentence gives every word a category, a part of speech, a lemma, a sense, "
                             "its roles, a semantic tag and its place")

    def key(self) -> str:
        """The derivation's identity: this sentence of its document, derived so."""
        return hashlib.sha256("\x1e".join(
            [self.said_in, str(self.part), "\x1f".join(self.words), "\x1f".join(self.categories)]).encode("utf-8")
        ).hexdigest()[:32]

    def identity(self) -> Optional[Tuple[str, int]]:
        """What the derivation is of: a sentence of a document. One derived again otherwise corrects the memory of
        the first (`MemoryAgent._remember_whole`)."""
        return (self.said_in, self.part) if self.said_in else None

    def claim(self) -> str:
        """What it was taught as, as the knowledge ledger records it: the sentence derived so."""
        return f'the derivation of "{self.text}" ({self.key()[:8]})'

    def said(self) -> str:
        """The derivation, said plainly: each word and its category."""
        return f'"{self.text}": ' + "; ".join(f'"{w}" {c}' for w, c in zip(self.words, self.categories))

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "words": list(self.words), "categories": list(self.categories),
                "tags": list(self.tags), "lemmas": list(self.lemmas), "senses": list(self.senses),
                "roles": [list(r) for r in self.roles], "semantics": list(self.semantics),
                "spans": [list(s) for s in self.spans], "tree": self.tree, "said_in": self.said_in,
                "part": self.part}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Derived":
        return cls(str(data["text"]), tuple(data["words"]), tuple(data["categories"]), tuple(data["tags"]),
                   tuple(data["lemmas"]), tuple(data["senses"]), tuple(tuple(r) for r in data["roles"]),
                   tuple(data["semantics"]), tuple((int(a), int(b)) for a, b in data["spans"]),
                   _tupled(data.get("tree") or ()), str(data.get("said_in") or ""), int(data.get("part") or 1))


#: Where a sentence opens and closes, as the word beside its first and last words.
SENTENCE_START, SENTENCE_END = "<s>", "</s>"
#: The kind of word each of Penn's parts of speech names, as a derivation's words are tagged.
_TAGGED = {"NN": "NOUN", "NNS": "NOUN", "NNP": "NAME", "NNPS": "NAME", "JJ": "ADJECTIVE", "JJR": "ADJECTIVE",
           "JJS": "ADJECTIVE", "RB": "ADVERB", "RBR": "ADVERB", "RBS": "ADVERB", "CD": "NUMERAL",
           "IN": "PREPOSITION", "TO": "PREPOSITION", "VB": "VERB", "VBD": "VERB", "VBG": "VERB", "VBN": "VERB",
           "VBP": "VERB", "VBZ": "VERB"}
#: A derivation's atoms as the grammar writes them: `s:dcl` is `S[dcl]`; a word's particle (`pr`) is `PR`.
_BANK = re.compile(r"\(|\)|/|\\|[a-z]+(?::[a-z]+)?")


def bank_category(text: str) -> Cat:
    """A category as the Parallel Meaning Bank writes it (`(s:dcl\\np)/np`, `n/pp`), as the grammar's: atoms as
    `parse_category` makes them, a feature where the bank writes one."""
    tokens = _BANK.findall(text)
    if "".join(tokens) != re.sub(r"\s+", "", text):
        raise ValueError(f"not a category: {text!r}")
    at = 0

    def primary() -> Cat:
        nonlocal at
        token = tokens[at]
        at += 1
        if token == "(":
            inner = category()
            at += 1
            return inner
        base, _, feat = token.partition(":")
        return Atom(base if base == "conj" else base.upper(), feat or None, None)

    def category() -> Cat:
        nonlocal at
        left = primary()
        while at < len(tokens) and tokens[at] in ("/", "\\"):
            slash = tokens[at]
            at += 1
            left = Fn(left, slash, primary())
        return left
    return category()


def _alike(said: Cat, cat: Optional[Cat]) -> bool:
    """Whether a category a derivation gives (`said`) is one the grammar writes (`cat`): of one shape, each atom the
    same, a feature the derivation leaves unsaid ("s") or the grammar leaves open (`S[F]`) matching any."""
    if cat is None:
        return False
    if isinstance(said, Atom):
        if not isinstance(cat, Atom) or said.base != cat.base:
            return False
        feat = cat.feat
        return said.feat is None or not (isinstance(feat, str) and feat[:1].islower()) or said.feat == feat
    return isinstance(cat, Fn) and said.slash == cat.slash and _alike(said.res, cat.res) and _alike(said.arg, cat.arg)


def _atoms(cat: Cat) -> List[Atom]:
    return [cat] if isinstance(cat, Atom) else _atoms(cat.res) + _atoms(cat.arg)


def _exactness(said: Cat, cat: Cat) -> int:
    """Of a category a derivation gives and one the grammar writes that are alike (`_alike`), how many of the
    derivation's features the grammar's writes as they are (`S[adj]`), not leaves open (`S[F]`): of the entries a
    category is alike to, the one it is most exactly is its use. Taken in the order they are written, "very"'s
    `(s:adj\\np)/(s:adj\\np)` was an adverb of a doing (`S[F]`), never the degree written for it (`S[adj]`): the 81
    derivations of "very" on lyric_dev2 were each counted against its 610 uses as a degree, and "The sea was very
    smooth." lost the "very" (2026-10-29)."""
    return sum(1 for a, b in zip(_atoms(said), _atoms(cat)) if a.feat is not None and a.feat == b.feat)


def _without_taken(cat: Cat) -> Cat:
    """A category a derivation gives a word taking a phrase of a preposition (`PP`) or a particle (`PR`), as the
    grammar says it: taking neither, the preposition read as telling of what it joins and the particle read with the
    verb. "(s\\np)/pp" is `S\\NP` ("relies on"), "n/pp" `N` ("my uncle"), "np/(n/pp)" `NP/N` ("my")."""
    if isinstance(cat, Atom):
        return cat
    if cat.slash == "/" and isinstance(cat.arg, Atom) and cat.arg.base in ("PP", "PR") and cat.arg.feat is None:
        return _without_taken(cat.res)
    return Fn(_without_taken(cat.res), cat.slash, _without_taken(cat.arg))


def _said_of_a_thing(cat: Cat) -> Cat:
    """A preposition's phrase a form of "be" takes, as the grammar says it: what is said of a thing (`S[pp]\\NP`)."""
    if isinstance(cat, Atom):
        return Fn(Atom("S", "pp", None), "\\", Atom("NP", None, None)) if cat.base == "PP" and cat.feat is None \
            else cat
    return Fn(_said_of_a_thing(cat.res), cat.slash, _said_of_a_thing(cat.arg))


def _clause_taken(cat: Cat) -> Optional[Cat]:
    """A clause a word takes said with no "that" before it ("I think Tom is drunk": `(s:dcl\\np)/s:dcl`), as the
    grammar writes a clause a verb takes (`S[em]`); None where the word takes no such clause."""
    if isinstance(cat, Fn) and cat.slash == "/" and isinstance(cat.arg, Atom) and (cat.arg.base, cat.arg.feat) == (
            "S", "dcl"):
        return Fn(cat.res, "/", Atom("S", "em", None))
    return None


def _share(scores: Mapping[str, float]) -> Dict[str, float]:
    """Logarithms of weights, as the logarithm of each one's share of them all."""
    if not scores:
        return {}
    top = max(scores.values())
    whole = top + math.log(sum(math.exp(v - top) for v in scores.values()))
    return {k: v - whole for k, v in scores.items()}


def _there(cat: Cat) -> Cat:
    """The bank's "there" of "there is" (`np:thr`), as the grammar writes it (`THERE`)."""
    if isinstance(cat, Atom):
        return Atom("THERE", None, None) if (cat.base, cat.feat) == ("NP", "thr") else cat
    return Fn(_there(cat.res), cat.slash, _there(cat.arg))


def _raised_thing(cat: Cat) -> Optional[Cat]:
    """A thing as the grammar writes a word standing for one where it waits on its doing ("nobody":
    `S/(S\\NP)`, `(S\\NP)\\((S\\NP)/NP)`): the thing (`NP`) it is; None for any other."""
    if isinstance(cat, Fn) and isinstance(cat.arg, Fn) and cat.slash != cat.arg.slash \
            and _same_shape(cat.res, cat.arg.res) and isinstance(cat.arg.arg, Atom) and cat.arg.arg.base == "NP":
        return Atom("NP", None, None)
    return None


def _marked(cat: Cat, preposition: str) -> Cat:
    """A category taking a preposition's phrase, the phrase named by its preposition (`NP/PP` as `NP/PP[of]`)."""
    if isinstance(cat, Atom):
        return Atom("PP", preposition, None) if cat.base == "PP" and cat.feat is None else cat
    return Fn(_marked(cat.res, preposition), cat.slash, _marked(cat.arg, preposition))


def _beside(tokens: Sequence[str], k: int) -> str:
    """The word at k as a word beside another is counted (`Lexicon.hear_derived`): written in lowercase, or where
    the sentence opens or closes."""
    if k < 0:
        return SENTENCE_START
    return str(tokens[k]).lower() if k < len(tokens) else SENTENCE_END


def _taken_in(derived: Derived) -> Tuple[Dict[int, List[int]], Set[int]]:
    """WHAT EACH WORD OF A DERIVATION TOOK, in the order it took it: for each word heading a function applied to what
    it takes (`fa`, `ba`), the word heading each thing taken ("chased" took "cat", then "dog"; "in" took "park", then
    the doing it tells of). A phrase is headed by its function's word, or, where the function only tells of what it
    takes (a determiner, an adjective, an adverb, "is" before a doing: `X/X`, `NP/N`, as the grammar says them:
    `_without_taken`), by what it takes; things joined by "and" by no word. And the words whose phrases were composed (`fc`, `bxc`, ...), whose places a count of what they took does not give."""
    took: Dict[int, List[int]] = defaultdict(list)
    composed: Set[int] = set()

    def category(node: Any) -> str:
        return derived.categories[node] if isinstance(node, int) else node[1]

    def walk(node: Any) -> Optional[int]:
        if isinstance(node, int):
            return node
        if not node:
            return None
        kids = [k for k in node[2:] if not isinstance(k, str)]
        heads = [walk(k) for k in kids]
        rule = node[0]
        if len(kids) == 1:
            return heads[0]
        if rule == "rp":
            return heads[0]
        if rule == "lp":
            return heads[1]
        if rule == "conj" or any(isinstance(k, tuple) and k and k[0] == "conj" for k in kids):
            # Things joined by "and" are no one word's: a place one fills is not counted.
            return None
        f, a = (0, 1) if rule in ("fa", "fc", "fxc", "gfc") else (1, 0)
        try:
            functor = _without_taken(bank_category(category(kids[f])))
        except (ValueError, IndexError):
            return heads[f]
        if rule in ("fa", "ba"):
            if heads[f] is not None and heads[a] is not None:
                took[heads[f]].append(heads[a])
        else:
            composed.update(h for h in heads if h is not None)
        if isinstance(functor, Fn) and (_same_shape(functor.res, functor.arg) or (
                isinstance(functor.res, Atom) and functor.res.base == "NP" and isinstance(functor.arg, Atom)
                and functor.arg.base == "N")):
            return heads[a]
        return heads[f]
    walk(derived.tree)
    return took, composed


def _offsets(text: str, tokens: Sequence[str]) -> List[Optional[Tuple[int, int]]]:
    """Where each of a sentence's words is in its text, in order; None for one not found."""
    out: List[Optional[Tuple[int, int]]] = []
    at = 0
    for t in tokens:
        w = str(t)
        k = text.find(w, at)
        if k < 0:
            k = text.lower().find(w.lower(), at)
        if k < 0:
            out.append(None)
            continue
        out.append((k, k + len(w)))
        at = k + len(w)
    return out


def _taking_a_pp(derived: Derived) -> Dict[int, Tuple[str, Optional[int]]]:
    """For each word of a derivation heading a preposition's phrase (`pp/np`), what takes the phrase: its category,
    and its word where one word takes it (None where words combined take it)."""
    out: Dict[int, Tuple[str, Optional[int]]] = {}

    def category(node: Any) -> str:
        return derived.categories[node] if isinstance(node, int) else node[1]

    def head(node: Any) -> Optional[int]:
        while not isinstance(node, int):
            kids = [k for k in node[2:] if not isinstance(k, str)]
            if not kids:
                return None
            node = next((k for k in kids if category(k).startswith("pp/") or category(k) == "pp"), kids[0])
        return node if derived.categories[node].startswith("pp/") else None

    def walk(node: Any) -> None:
        if isinstance(node, int) or not node:
            return
        kids = [k for k in node[2:] if not isinstance(k, str)]
        if len(kids) == 2:
            for one, other in ((kids[0], kids[1]), (kids[1], kids[0])):
                # A mark said beside the phrase (`rp`, `lp`) takes nothing.
                if category(one) == "pp" and any(ch.isalpha() for ch in category(other)):
                    word = head(one)
                    if word is not None:
                        out[word] = (category(other), other if isinstance(other, int) else None)
        for kid in kids:
            walk(kid)
    walk(derived.tree)
    return out


class Lexicon:
    """The words: English's grammar words and the categories of each kind of word (`data/grammar/english.json`),
    each word's kinds and uses as held for it (`Words`), and what is learned from sentences taught with their
    meanings: the link each of a verb's places makes, what each preposition means, how a thing is someone's, what
    each adverb says, what "is a" says (`learn`)."""

    def __init__(self, words: Words, grammar: Optional[Mapping[str, Any]] = None):
        self.words = words
        self.grammar = dict(grammar) if grammar is not None else json.loads(ENGLISH.read_text(encoding="utf-8"))
        self.closed: Dict[str, List[Mapping[str, Any]]] = {w.lower(): list(v) for w, v in
                                                           self.grammar["words"].items()}
        self.templates: Dict[str, List[Mapping[str, Any]]] = self.grammar["classes"]
        self.verb_templates: Dict[str, Dict[str, List[Mapping[str, Any]]]] = self.grammar["verbs"]
        self.linking: Dict[str, str] = self.grammar["linking"]
        self.name_particles = set(self.grammar.get("name_particles", ()))
        self.numbers: Dict[str, int] = dict(self.grammar.get("numbers", {}))
        self.number_scales: Dict[str, int] = dict(self.grammar.get("number_scales", {}))
        self.phrases: Dict[str, str] = dict(self.grammar.get("phrases", {}))
        self.together: Dict[str, Mapping[str, Any]] = self.grammar.get("together", {})
        self._runs_of: Tuple[Tuple[str, ...], List[Tuple[int, int]]] = ((), [])
        self._numbers_of: Tuple[Tuple[str, ...], List[Tuple[int, int]]] = ((), [])
        self._hyphened_of: Tuple[Tuple[str, ...], List[Tuple[int, int, Optional[str]]]] = ((), [])
        #: The words heard as names though written lowercase ("the function sorted"), and how often: a name heard is
        #: one when said again ("Does sorted return a new list?").
        self.heard: Counter = Counter()
        #: Learned from sentences taught with their meanings: (key) -> the links said there, counted.
        self.learned: Dict[str, Dict[Tuple, Counter]] = defaultdict(lambda: defaultdict(Counter))
        #: Learned from sentences derived by hand (`hear_derived`), each word's way as the grammar names its ways:
        #: `uses` (the word -> its ways; "" every word's), `after` (the word before it -> the ways of the word after),
        #: `before` (the word after it -> the ways of the word before), `frames` (a verb -> its frames; "" every
        #: verb's), `frames before` (the word after a verb -> the verb's frames).
        self.derived: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        self._categories: Dict[str, Cat] = {}
        #: WHICH SENSE OF A VERB A SENTENCE MEANS (`sense_of`): each verb's senses by the name its word is read under
        #: (verb name -> sense -> how often used), and what each was seen used with (verb name -> sense -> (slot, the
        #: thing) -> how often), from words and sentences recorded whole (`GrammarView.hold_word`, `hold_use`).
        self.sense_used: Dict[str, Counter] = defaultdict(Counter)
        self.sense_seen: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        #: What may fill each place of each sense (verb name -> sense -> (slot, the thing) -> how many say it): what
        #: VerbNet restricts it to, "restricted" ("+animate", a living thing), and what PropBank says fills it,
        #: "described" ("art").
        self.sense_wants: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        #: WHAT EACH PLACE OF A VERB SAYS, BY THE PLACES SAID WITH IT (`framed`): verb name -> sense ("" the word's) ->
        #: a frame's places ((slot, link), ...) -> how many frames say just those (`WordRecord.frames_said`).
        self.frames_said: Dict[str, Dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
        #: Of what `learned["role"]` holds of a verb's place, what its word's PropBank places said ((verb name, slot)
        #: -> link -> how many): the rest sentences taught with their meanings said (`taught_role`).
        self.place_links: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        #: WHICH SENSE OF A NOUN A SENTENCE MEANS (`thing_sense_of`): each noun's senses by the name its word is read
        #: under (noun name -> sense -> how often used), and how much of what is said each sense and each of its kinds
        #: cover (noun name -> sense -> the sense or kind -> SemCor's uses under it), from words recorded whole.
        self.thing_used: Dict[str, Counter] = defaultdict(Counter)
        self.thing_covers: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(dict)
        self._taking_pps: Optional[List[Cat]] = None

    def saying(self, link: str) -> List[str]:
        """THE WORDS THAT SAY A LINK joining a doing or a thing to a thing, as what was taught says each did
        (`prep`, `prep_to`, `prep_of`), the most said first; a word whose own link it is (`worded`: "of" `word_of`).
        What `Grammar.say` says a link with."""
        counted: Counter = Counter()
        for table, at in (("prep", 0), ("prep_to", 0), ("prep_of", 1)):
            for key, links in self.learned[table].items():
                if links.get(link, 0) > 0:
                    counted[key[at]] += links[link]
        if is_worded(link):
            counted[link.split("_", 1)[1].replace("_", " ")] += 1
        return [w for w, _ in counted.most_common()]

    def said_with(self, link: str) -> Tuple[Counter, float]:
        """HOW OFTEN A LINK WAS SAID WITH EACH WORD, AND WITH NONE, as what was taught says it: by a preposition of a
        doing or a thing (`prep`), after the very word it follows (`prep_of`), after a quality (`holder`); and by no
        word of its own, as a verb's place (`role`: the object `done_to`), a quality, an adverb or a possessive says
        it. Each saying counted once (`prep_to` counts one again for each kind its thing is)."""
        words: Counter = Counter()
        for table, at in (("prep", 0), ("prep_of", 1), ("holder", 0)):
            for key, links in self.learned[table].items():
                if links.get(link, 0) > 0 and len(key) > at:
                    words[key[at]] += links[link]
        bare = float(sum(links.get(link, 0) for table in ("role", "quality", "adv", "poss")
                         for links in self.learned[table].values()))
        return words, bare

    def sense_of(self, name: str, fillers: Mapping[str, str]) -> str:
        """THE SENSE OF A VERB A SENTENCE MEANS, by what fills its places (`fillers`: slot -> the thing's name): each
        sense weighed by how often it is used, and, for each place filled, by how many of the things it was seen used
        with there are of the most specific kind the filler shares with any of them ("the wall", a structure, as the
        porch `coat paint` was seen done to; class-based, as Resnik 1993 weighs a verb's selection). The name the
        word is read under where it has no senses apart, or nothing it was seen with is of any kind the filler is."""
        used = self.sense_used.get(name)
        if not used or len(used) < 2:
            return name
        senses = list(used)
        total = sum(used.values())
        score = {c: math.log((used[c] + 0.5) / (total + 0.5 * len(senses))) for c in senses}
        for slot, filler in fillers.items():
            if not filler:
                continue
            levels = [filler] + list(self.words.kinds(filler, "NOUN"))
            # WHAT MAY FILL THE PLACE: a filler of a kind PropBank's description of the place names is evidence for
            # the sense; one of no kind VerbNet restricts the place to, where its kinds are known, against it.
            for c in senses:
                wants = self.sense_wants.get(name, {}).get(c, {})
                described = {f for (sl, how, f), n in wants.items() if sl == slot and how == "described" and n > 0}
                restricted = {f for (sl, how, f), n in wants.items() if sl == slot and how == "restricted" and n > 0}
                if described & set(levels):
                    score[c] += math.log(2.0)
                if restricted and len(levels) > 1 and not restricted & set(levels):
                    score[c] -= math.log(2.0)
            seen = {c: [(f, n) for (sl, f), n in self.sense_seen.get(name, {}).get(c, {}).items() if sl == slot]
                    for c in senses}
            kinds_of = {f: {f} | set(self.words.kinds(f, "NOUN")) for c in senses for f, _ in seen[c]}
            for level in levels:
                counts = {c: sum(n for f, n in seen[c] if level in kinds_of[f]) for c in senses}
                if any(counts.values()):
                    every = sum(counts.values())
                    for c in senses:
                        score[c] += math.log((counts[c] + 0.5) / (every + 0.5 * len(senses)))
                    break
        return max(senses, key=lambda c: (score[c], used[c]))

    def framed(self, name: str, sense: str, slots: Sequence[str], slot: str, default: Optional[str] = None) \
            -> Optional[str]:
        """WHAT A VERB'S PLACE SAYS BY THE PLACES SAID WITH IT, as its frames say (`frames_said`; Boxer gives a verb's
        roles by the frame its category is, Bos 2008): of the frames of the sense the sentence means (and, for a
        place after a preposition, else of the word's), those giving the most of the places said (`slots`, a `pp:*`
        any preposition's), the fewest besides; the link most of them give `slot`, `default` where it ties with
        another. None where no frame gives it: "The chicken is pecking at Tom." is a pecking done to Tom
        (`chew-39.2-1`: "NP V PP-Conative", the one pecked after "at"). THE WORD'S FRAMES SAY NOTHING OF ITS SUBJECT
        AND OBJECTS: its senses' frames disagree there ("call" a Topic, a Theme, a Recipient), and taken where the
        sense's said nothing, 86.0% of the PMB's train objects were linked as the PMB links them, against 86.5% by
        the sense's alone; after a preposition, 45.1% against 40.8% (`GRAMMAR-01/diagnostics/verb_places.py`,
        2026-10-29)."""
        held = self.frames_said.get(name)
        if not held:
            return None
        used = self.sense_used.get(name) or {}
        if sense not in used and len(used) == 1:
            sense = next(iter(used))        # a verb of one sense is read under its word's name (`sense_of`)
        for key in ([sense] if sense else []) + ([""] if slot.startswith("pp:") else []):
            frames = held.get(key)
            if not frames:
                continue
            fits = {}
            for frame in frames:
                said = dict(frame)
                fits[frame] = (sum(s in said or (s.startswith("pp:") and "pp:*" in said) for s in slots),
                               -abs(len(said) - len(slots)))
            best = max(fits.values())
            votes: Counter = Counter()
            for frame, n in frames.items():
                said = dict(frame)
                link = said.get(slot) or (said.get("pp:*") if slot.startswith("pp:") else None)
                if fits[frame] == best and link:
                    votes[link] += n
            if votes:
                top = max(votes.values())
                tied = sorted(link for link, n in votes.items() if n == top)
                return default if default in tied else tied[0]
        return None

    def taught_role(self, name: str, slot: str) -> bool:
        """Whether sentences taught with their meanings said what a verb's place is, beyond what its word's PropBank
        places said (`place_links`): what was said of the very verb is not overruled by its frames (`framed`).
        "You tortured a prisoner." taught the torturer who does it; VerbNet's only class of "torture" is one of
        feelings (`amuse-31.1`: "NP:Stimulus V NP:Experiencer"), and "Who did Maurice Papon torture?" was read as
        Papon tortured (lyric_dev2, 2026-10-29)."""
        held = self.learned["role"].get((name, slot)) or {}
        recorded = self.place_links.get((name, slot)) or {}
        return any(n > recorded.get(link, 0) for link, n in held.items())

    def thing_sense_of(self, name: str, around: Sequence[str]) -> str:
        """THE SENSE OF A NOUN A SENTENCE MEANS, by the other things it names (`around`, each by its name): each sense
        weighed by how often it is used, and, for each thing around it, by the information of the most specific kind
        the sense shares with it (the sense itself, or a kind of it, that the thing is or is a kind of): how little of
        what is said that kind covers, against the most any sense's kinds cover (Resnik 1995; lexical cohesion, Morris
        and Hirst 1991). "a second coat of paint": paint is a coating, as the coat that is a layer is, and a coating
        covers far less than the coverings a coat that is worn shares with it. The name the word is read under where
        it has no senses apart, or nothing around it is of any kind its senses are."""
        used = self.thing_used.get(name)
        if not used or len(used) < 2:
            return name
        senses = list(used)
        covers = {c: self.thing_covers.get(name, {}).get(c, {}) for c in senses}
        everything = max((n for held in covers.values() for n in held.values()), default=0)
        total = sum(used.values())
        score = {c: math.log(used[c] / total) for c in senses}
        for other in around:
            if not other or other == name:
                continue
            levels = [other] + list(self.words.kinds(other, "NOUN"))
            shared = {c: next((covers[c][level] for level in levels if level in covers[c]), everything)
                      for c in senses}
            if everything and any(n < everything for n in shared.values()):
                for c in senses:
                    score[c] += math.log(everything / shared[c])
        return max(senses, key=lambda c: (score[c], used[c]))

    # ── what each word may be ──
    def entries(self, tokens: Sequence[str], i: int) -> List[Tuple[int, Entry]]:
        """Each way the words from i may be read: (the word after the last one read, the entry)."""
        out: List[Tuple[int, Entry]] = []
        word = tokens[i]
        low = word.lower()
        # Several words read as one: a name ("Charles de Gaulle"), a name in quotes, words joined by a hyphen,
        # words memory knows as one ("credit card"), the grammar's words of several ("no one", "how many").
        for end, entry in self._together(tokens, i):
            out.append((end, entry))
        closed = self.closed.get(low, [])
        if not any(ch.isalnum() for ch in word):
            return out
        if _formula(word):
            # A formula written in the sentence ("100 / 4", "sqrt(144)", "15%") is one thing it speaks of, read
            # as written (`sentence_machine.form_of` keeps it one piece).
            for t in self.templates.get("NUMERAL", ()):
                if t.get("use") == "NUMERAL:alone":
                    out.append((i + 1, Entry(t["cat"], (), "NUMERAL", word.replace(" ", ""), 0.0, "formula")))
            return out
        if _ADDRESS.fullmatch(word):
            # WHERE A FILE OR A PAGE IS ("/notes/story.txt", "https://example.com/a") is one thing, named as written
            # (`sentence_machine.form_of` keeps it one piece). Read as a word, it was a kind, written in lower case,
            # and "Read /notes/story.txt." told of a doing it named, done by someone called Read.
            for t in self.templates.get("NAME", ()):
                out.append((i + 1, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "NAME", word, 0.0,
                                         t.get("label", ""))))
            return out
        marking = [e for e in closed if e["use"] == "case:part"]
        if marking and i > 0 and self._is_number(tokens[i - 1]) and not any(
                start <= i - 1 < end and end - start > 1
                for start, end in self._name_runs(tokens) + self._number_runs(tokens)):
            # A NUMERAL'S "OF" MARKS WHAT IT IS A NUMBER OF: "Two of them" is two of them. After a numeral standing
            # alone the treebank's "of" is that 113 times in 123, the rest a numeral inside a date, a name or an
            # amount ("October 3 of", "Ivan IV of", "$ 3 M of"); read word by word, "of" is a noun's 24 times as
            # often, and "Two of them work in Berlin." told of the number 2 working (UNDERSTANDS-PROSE-01, 2026-10-21).
            return out + [(i + 1, Entry(e["cat"], (), "GRAMMAR", low, 0.0, e.get("label", e["use"])))
                          for e in marking]
        evidence = self._evidence(tokens, i)
        for e in closed:
            out.append((i + 1, Entry(e["cat"], tuple(tuple(p) for p in e.get("sem", ())), "GRAMMAR", low,
                                     evidence.get(e["use"], -20.0), e.get("label", e["use"]),
                                     bool(e.get("crossing")))))
        inside = any(start <= i < end for start, end in self._name_runs(tokens))
        in_number = any(start <= i < end for start, end in self._number_runs(tokens))
        for cls, p in evidence.items():
            if cls not in self.templates and cls != "VERB":
                continue
            if cls == "NAME" and inside:
                # A word of a name of several words is read as that name, never as a name of its own.
                continue
            if cls == "NUMERAL" and in_number:
                # A word of a number said in several words is read as that number ("thirty-two": 32, never 30
                # and 2).
                continue
            name = self.words.name(word, cls) if cls != "NAME" else word.lower()
            if cls == "VERB":
                alone = self._alone_cost(tokens, i)
                for form, r in self._forms(word, name).items():
                    for frame, q in self._frame_evidence(name, _beside(tokens, i + 1)).items():
                        for t in self.verb_templates.get(form, {}).get(frame, ()):
                            out.append((i + 1, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls, name,
                                                     p + r + q + alone, f"{form}:{frame}")))
                continue
            if cls == "NUMERAL":
                name = _number(word) or self._number_name(word) or self.words.name(word, "NUMERAL")
            compares = self.words.degree(word) if cls == "ADJECTIVE" else None
            for t in self.templates.get(cls, ()):
                if t.get("use", cls) != cls:
                    continue
                sem = tuple(tuple(x) for x in t.get("sem", ()))
                if compares:
                    # "bigger", "biggest": the plain quality compared (`more`, `most`).
                    sem += (("compared", "q", compares),)
                out.append((i + 1, Entry(t["cat"], sem, cls, name, p, t.get("label", ""))))
        # A kind of word's other ways, each as often as the word is used that way.
        for use, p in evidence.items():
            cls = use.split(":")[0]
            if use == cls or cls not in self.templates:
                continue
            if (cls == "NAME" and inside) or (cls == "NUMERAL" and in_number):
                continue
            name = self.words.name(word, cls) if cls != "NUMERAL" else (
                _number(word) or self._number_name(word) or self.words.name(word, cls))
            for t in self.templates[cls]:
                if t.get("use") == use:
                    out.append((i + 1, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls, name, p,
                                             t.get("label", ""))))
        after = self._sound_after(tokens, i)
        if after:
            out = [(end, Entry(e.cat, e.sem, e.cls, e.name, e.score + after, e.label, e.crossing)) for end, e in out]
        return out

    def _sound_after(self, tokens: Sequence[str], i: int) -> float:
        """HOW LIKELY THE WORD AT `i` IS BEFORE THE WORD AFTER IT, of the forms of its word the analysts mark nothing
        apart ("a" and "an"), as a logarithm: as often as it was said before a word beginning with that word's first
        sound, of all of them so said, with one saying more spread as each is said at all (`Words.said_before`); where
        memory holds no sound of the word after it, as often as it is said at all. Nothing for a word with no such
        forms. Every way the word is read is weighed alike: which form is said, not which reading, is weighed.

        Taught no sounds, "a" and "an" were one word to the grammar, and nothing but a first letter written by hand
        ever chose between them, which says "a hour" and "an unicorn" (lyric_dev2, 2026-10-27)."""
        alike = self.words.said_before(tokens[i])
        own = alike.get(tokens[i].lower())
        if own is None or len(alike) < 2:
            return 0.0
        said = {form: sum(sounds.values()) for form, sounds in alike.items()}
        prior = (said[tokens[i].lower()] + 1.0) / (sum(said.values()) + len(said))
        firsts = set()
        if i + 1 < len(tokens):
            firsts = {way.split()[0].rstrip("012") for way in self.words.sounds(tokens[i + 1]) if way.split()}
        if not firsts:
            return math.log(prior)
        return max(math.log((own.get(s, 0.0) + prior) / (sum(f.get(s, 0.0) for f in alike.values()) + 1.0))
                   for s in firsts)

    def _said_as_one(self, tokens: Sequence[str], i: int, name: str) -> Tuple[float, float]:
        """How likely the verb at `i` (named `name`) and the word after it are one verb, and how likely apart, as
        logarithms: as often as the two are said together so; where they never were, as often as the second word is
        said with a verb so. WHERE WHETHER THEY ARE ONE IS HELD BY WHERE THE CLAUSE ENDS (a verb of several words
        recorded whole), by the clause here ending after them or going on."""
        second = self.words.uses(tokens[i + 1])
        alone = estimate(second, {}, set(second) | {"PARTICLE"})["PARTICLE"]
        one, apart = self.words.said_together(
            name, tokens[i + 1], ends=i + 2 >= len(tokens) or not any(ch.isalnum() for ch in tokens[i + 2]))
        shares = estimate({"one": one, "apart": apart},
                          {"one": math.exp(alone), "apart": 1.0 - math.exp(alone)}, ("one", "apart"))
        return shares["one"], shares["apart"]

    def _alone_cost(self, tokens: Sequence[str], i: int) -> float:
        """WHAT THE VERB AT `i` READ ALONE COSTS where it and the word after it are a verb of several words whose being
        one is held by where the clause ends: as likely as they are said apart there. Told nothing of "it" as a
        particle, "We made it!" was `make` with "it" made, which SemCor's annotators said 3 times in 8 where the
        clause ends there, `make it` 5 (lyric_dev2, 2026-10-27). Nothing elsewhere: the second word's own uses weigh
        a verb read alone, as "away" read as an adverb weighs "passed" (`_together`)."""
        if i + 1 >= len(tokens) or not tokens[i + 1].isalpha():
            return 0.0
        name = self.words.name(tokens[i], "VERB")
        if not (self.words.known_verb([tokens[i].lower(), tokens[i + 1].lower()])
                or self.words.known_verb([name, tokens[i + 1].lower()])):
            return 0.0
        if self.words.said_together(name, tokens[i + 1]) == self.words.said_together(
                name, tokens[i + 1], ends=i + 2 >= len(tokens) or not any(ch.isalnum() for ch in tokens[i + 2])):
            return 0.0
        return self._said_as_one(tokens, i, name)[1]

    def _evidence(self, tokens: Sequence[str], i: int, beside: Optional[Tuple[str, str]] = None) -> Dict[str, float]:
        """Each way the word may be read, as a grammar word's use or a kind of word, with the logarithm of how often
        it is used so beside the words around it (`_held_evidence`, `_in_context`). `beside`: the words before and
        after it, where they are not its neighbours in `tokens`."""
        return self._in_context(self._held_evidence(tokens, i), tokens, i, beside)

    def _in_context(self, ways: Mapping[str, float], tokens: Sequence[str], i: int,
                    beside: Optional[Tuple[str, str]] = None) -> Dict[str, float]:
        """A WORD'S WAYS BESIDE THE WORDS AROUND IT, as the sentences derived by hand say (`hear_derived`). Weighed by
        how the treebank uses a word out of context, the grammar chose a word's category wrongly one time in five
        (2026-10-26 (51)): "fight" is used as a noun more than as a verb, and after "are" it is a verb.

        How often the derivations use this very word each way, with one use more spread as `ways` weighs it (how the
        treebank uses the word, `_held_evidence`): a word the derivations never hold is weighed as before. Then, for
        each word beside it, how much more often a word beside that one is used each way than words are at all, with
        one use more spread as words are used at all: after "the" a noun, before "to" a verb, before "." a doing that
        takes nothing; a word beside it the derivations never hold says nothing. The ways are those `ways` holds and
        those the derivations use the word in where the grammar reads a word so (`_takes_way`).

        On the PMB's held-out dev sentences derived by hand, the way so chosen for each word is the derivation's
        92.7% of the time, out of context 78.3%. Each way's share of the word's ways is what is given (`_share`): a
        neighbour's weight is how much more often, not how often, and summed as they were over a reading's words, the
        surer a word's neighbours the more the reading was worth beside one reading a name of several words as one."""
        every = self.derived["uses"].get("")
        if not every:
            return dict(ways)
        word = tokens[i]
        own = self.derived["uses"].get(word.lower(), {})
        names = list(ways) + [u for u in own if u not in ways and self._takes_way(word, u)]
        n = sum(own.get(u, 0) for u in names)
        out = {u: math.log((own.get(u, 0) + (math.exp(ways[u]) if u in ways else 0.0)) / (n + 1.0)) for u in names}
        if beside is None:
            beside = (_beside(tokens, i - 1), _beside(tokens, i + 1))
        prior = estimate(every, {}, names)
        for table, near in (("after", beside[0]), ("before", beside[1])):
            held = self.derived[table].get(near)
            if not held:
                continue
            m = sum(held.get(u, 0) for u in names)
            for u in names:
                out[u] += math.log((held.get(u, 0) + math.exp(prior[u])) / (m + 1.0)) - prior[u]
        return _share(out)

    def _takes_way(self, word: str, way: str) -> bool:
        """Whether the grammar reads the word in this way: one of its own entries' uses; else, where it is not read
        only as its own, a kind of word's way, a name only written capitalised or heard as one."""
        low = word.lower()
        closed = self.closed.get(low, [])
        if any(e["use"] == way for e in closed):
            return True
        if any(e.get("only") for e in closed):
            return False
        cls = way.split(":")[0]
        if cls == "NAME" and not word[:1].isupper() and low not in self.heard:
            return False
        return way == "VERB" or (cls in self.templates and way in self._uses_of_class(cls))

    def _held_evidence(self, tokens: Sequence[str], i: int) -> Dict[str, float]:
        """Each way the word may be read, as a grammar word's use or a kind of word, with the logarithm of how often
        it is used so (`estimate`). A word the grammar reads only as its own ("not", "where") is no other kind of
        word; a word with no ways of its own is read only as kinds of word ("every" is not read until the grammar
        is taught it)."""
        word = tokens[i]
        low = word.lower()
        held = dict(self.words.uses(word))
        closed = self.closed.get(low, [])
        counts: Dict[str, float] = {}
        if closed:
            counts = {u: held.get(u, 0.0) for u in {e["use"] for e in closed}}
        if not any(e.get("only") for e in closed):
            # Each kind of word it may be, with each use of that kind's ways ("very" as a degree); a use no way of
            # the kind's has ("ADJECTIVE:before", read by a rule) counts as the kind.
            for c in {u.split(":")[0] for u in held}:
                if c in self.templates or c == "VERB":
                    ways = self._uses_of_class(c)
                    for u in ways:
                        counts[u] = held.get(u, 0.0)
                    counts[c] = counts.get(c, 0.0) + sum(n for u, n in held.items()
                                                         if u.split(":")[0] == c and u not in ways)
        if self._is_number(word):
            # A number is a numeral, each of a numeral's ways ("two books", "in 1970"); a number word is no name,
            # written capitalised or not ("Seven is a prime number.").
            counts.pop("NAME", None)
            for u in self._uses_of_class("NUMERAL"):
                counts.setdefault(u, held.get(u, 0.0))
            counts["NUMERAL"] = max(counts.get("NUMERAL", 0.0), 1.0)
            for u in self._uses_of_class("NUMERAL"):
                counts.setdefault(u, held.get(u, 0.0))
        if not word[:1].isupper():
            # A name is written capitalised: "apple" is no Apple, "us" no US; a word written lowercase is a name only
            # where it was heard as one ("the function sorted": `heard`).
            counts.pop("NAME", None)
            if low in self.heard and not closed:
                counts["NAME"] = float(self.heard[low])
        if word[:1].isupper() and closed and i > 0 and not self._is_number(word) and not tokens[i - 1] in ('"', ":", "``") and low != "i":
            # A grammar word written capitalised inside a sentence may be a name ("in May", "Will Smith").
            written = self.words.capitalized(word)
            counts["NAME"] = written.get("NAME", 0.0)
            counts.update({c: n for c, n in written.items() if c != "NAME" and c in self.templates})
        if word[:1].isupper() and not closed and not self._is_number(word):
            if i > 0 and not tokens[i - 1] in ('"', ":", "``"):
                # A capitalised word not opening the sentence is a name, or a kind memory holds by a capitalised
                # name ("Estonian", a language).
                written = self.words.capitalized(word)
                counts = {"NAME": written.get("NAME", 0.0) + 1.0}
                counts.update({c: n for c, n in written.items() if c != "NAME" and c in self.templates})
                return estimate(counts, {}, counts)
            # Opening it, a name only as often as the word is not used otherwise.
            counts.setdefault("NAME", 0.0)
        if not counts:
            counts = {"NOUN": 0.0, "VERB": 0.0, "ADJECTIVE": 0.0}
        ways = estimate(counts, self.words.like(word, "uses"), counts)
        return self._as_said(ways, tokens, i) if closed else ways

    def _as_said(self, ways: Mapping[str, float], tokens: Sequence[str], i: int) -> Dict[str, float]:
        """Each way a grammar word may be read, weighed as well by how often a word used that way is used in a
        sentence that asks, where this one asks, or in one that tells (`Words.asking`, every word's uses together,
        one use more spread over the two). A word's own uses are counted in every sentence, and a way used in
        questions is seldom among them: "were" after "How many failed attempts" was "were there" as a place, not that
        there were five, its use as a question's "there were" met once in the treebank (UNDERSTANDS-PROSE-01 on main,
        2026-10-21). A grammar word's ways are what a question is built with; of any other word, how often its kind
        is met in questions says how questions are written, not which kind it is, and weighed so, "dynamically" in
        "Is Python dynamically typed?" was read as a thing.

        AND BY WHETHER A DOING'S -ING FORM IS SAID NEXT (`Words.doing_after`), as a grammar word's ways are told
        apart by what follows: "for" before "detecting" marks what a thing is for, as the treebank's "for" before a
        doing does every time, where word by word it is a preposition some seventy times as often, and "a new method for
        detecting anomalies" proposed a detecting (UNDERSTANDS-PROSE-01 on main, 2026-10-21)."""
        asks = bool(tokens) and tokens[-1] == "?"
        doing = i + 1 < len(tokens) and self._doing_form(tokens[i + 1])
        out: Dict[str, float] = {}
        for use, p in ways.items():
            asking, telling = self.words.asking(use)
            before, other = self.words.doing_after(use)
            out[use] = p + math.log(((asking if asks else telling) + 1.0) / (asking + telling + 2.0)) \
                + math.log(((before if doing else other) + 1.0) / (before + other + 2.0))
        return out

    def _doing_form(self, word: str) -> bool:
        """Whether a word may be a doing's -ing form: written so, and used as a verb or not yet met."""
        uses = self.words.uses(word)
        return word.lower().endswith("ing") and (not uses or "VERB" in uses)

    def _is_number(self, word: str) -> bool:
        return _number(word) is not None or self._number_name(word) is not None

    def _uses_of_class(self, cls: str) -> Set[str]:
        return {t.get("use", cls) for t in self.templates.get(cls, ())} | {cls}

    def _forms(self, word: str, name: str) -> Dict[str, float]:
        """The forms of its verb the word may be, each with the logarithm of how often it is used so: the forms its
        spelling allows, and any it is held to be used as ("put" as past and participle too)."""
        low = word.lower()
        held = dict(self.words.verb_forms(low))
        if low == name:
            spelled = {"base", "present"}
        elif low.endswith("ing"):
            spelled = {"ing"}
        elif low.endswith("s") and not low.endswith("ss") and low[:-1].rstrip("e") == name.rstrip("e")[:len(
                low[:-1].rstrip("e"))]:
            spelled = {"third"}
        else:
            spelled = {"past", "participle"}
        return estimate(held, self.words.like(word, "forms"), spelled | set(held))

    def _frame_evidence(self, name: str, after: Optional[str] = None) -> Dict[str, float]:
        """Each frame of the verb, with the logarithm of how often it is used so: as the treebank uses it, and, as
        `_in_context` weighs a word's ways, as the sentences derived by hand use it and a verb before the word after
        it (`after`): before "the" a verb takes a thing, before "." nothing. On the PMB's held-out dev sentences, the
        frame so chosen for each verb is the derivation's 90.5% of the time, by the treebank alone 65.4%."""
        frames = list(self.verb_templates.get("frames", {}).keys())
        held = estimate(self.words.frames(name), self.words.like(name, "frames"), frames)
        every = self.derived["frames"].get("")
        if not every:
            return held
        own = self.derived["frames"].get(name, {})
        n = sum(own.get(f, 0) for f in frames)
        out = {f: math.log((own.get(f, 0) + math.exp(held[f])) / (n + 1.0)) for f in frames}
        near = self.derived["frames before"].get(after) if after is not None else None
        if near:
            prior = estimate(every, {}, frames)
            m = sum(near.get(f, 0) for f in frames)
            for f in frames:
                out[f] += math.log((near.get(f, 0) + math.exp(prior[f])) / (m + 1.0)) - prior[f]
        return _share(out)

    # ── what sentences derived by hand say ──
    def hear_derived(self, derived: Derived, times: int = 1) -> None:
        """WHAT A SENTENCE DERIVED BY HAND SAYS EACH WORD TAKES, BESIDE THE WORDS AROUND IT, counted (`_in_context`,
        `_frame_evidence`): each word's way as the grammar names it (`uses_derived`), with the word before it and the
        word after it; each verb's frame, with the word after it. A word of several and a category the grammar has
        no meaning for are not counted. `times` -1 takes a sentence's counts back (derived otherwise since)."""
        def count(table: str, key: str, what: str) -> None:
            held = self.derived[table][key]
            held[what] += times
            if held[what] <= 0:
                del held[what]
        words = [w.lower() for w in derived.words]
        for k, got in enumerate(self.uses_derived(derived)):
            if got is None:
                continue
            use, frame = got
            way = self._way(use)
            before = words[k - 1].rsplit("~", 1)[-1] if k else SENTENCE_START
            after = words[k + 1].split("~", 1)[0] if k + 1 < len(words) else SENTENCE_END
            count("uses", words[k], way)
            count("uses", "", way)
            count("after", before, way)
            count("before", after, way)
            if use == "VERB" and frame:
                lemma = derived.lemmas[k].lower()
                count("frames", lemma, frame)
                count("frames", "", frame)
                count("frames before", after, frame)
    def _way(self, use: str) -> str:
        """A use as `_held_evidence` weighs it: a kind of word's use no way of the kind's has ("ADJECTIVE:before", read
        by a rule) as the kind."""
        cls = use.split(":")[0]
        return cls if cls in self.templates and use not in self._uses_of_class(cls) else use

    def uses_derived(self, derived: Derived) -> List[Optional[Tuple[str, str]]]:
        """Each word of a derivation, named as the grammar names its ways (`_held_evidence`, `HeldWords.use_of` for a
        treebank's): the use of the grammar's entry whose category the derivation gives the word, and for a verb its
        frame (`(use, frame)`, "" for none); None for a mark, a word of several, and a category the grammar has no
        meaning for. The derivation says some things otherwise than the grammar does, and they are put as the grammar
        says them (`_without_taken`, `_said_of_a_thing`, `_there`, `_raised_thing`): a phrase of a preposition a word
        takes is read as telling of what takes it; a particle as the verb's; "nobody" a thing."""
        takers = _taking_a_pp(derived)
        return [self._use_derived(derived, k, takers.get(k)) for k in range(len(derived.words))]

    def _category(self, text: str) -> Cat:
        if text not in self._categories:
            self._categories[text] = parse_category(text)
        return self._categories[text]

    def _use_derived(self, derived: Derived, k: int, taker: Optional[Tuple[str, Optional[int]]]
                     ) -> Optional[Tuple[str, str]]:
        word, text = derived.words[k], derived.categories[k]
        if "~" in word or not any(ch.isalnum() for ch in word) or not any(ch.isalpha() for ch in text):
            return None
        try:
            said = _there(bank_category(text))
        except (ValueError, IndexError):
            return None
        if isinstance(said, Atom) and said.base == "PR":
            # A verb's particle ("picked it up"), as the treebank's `compound:prt` is counted.
            return "PARTICLE", ""
        low = word.lower()
        closed = self.closed.get(low, [])
        if isinstance(said, Fn) and said.slash == "/" and isinstance(said.res, Atom) and said.res.base == "PP" \
                and said.res.feat is None and isinstance(said.arg, Atom) and said.arg.base == "NP":
            return self._preposition_derived(derived, low, closed, taker)
        ways = [said]
        if any(a.base in ("PP", "PR") for a in _atoms(said)):
            ways += [_said_of_a_thing(said), _without_taken(said)]
        ways += [c for c in (_clause_taken(w) for w in ways) if c is not None]
        for way in ways:
            alike = [(e, cat) for e, cat in ((e, self._category(e["cat"])) for e in closed)
                     if _alike(way, cat) or _alike(way, _raised_thing(cat))]
            if alike:
                return max(alike, key=lambda ec: _exactness(way, ec[1]))[0]["use"], ""
        kind = _TAGGED.get(derived.tags[k])
        got = self._use_of_kind(kind, ways) if kind else None
        if got is None and kind != "PREPOSITION":
            # Where the part of speech says one kind of word and the category another ("broken" an adjective,
            # "lives" a verb), the category decides.
            for other in ("NOUN", "ADJECTIVE", "VERB", "ADVERB"):
                if other != kind:
                    got = self._use_of_kind(other, ways)
                    if got is not None:
                        break
        return got

    def _use_of_kind(self, cls: str, ways: Sequence[Cat]) -> Optional[Tuple[str, str]]:
        """The use of a kind of word's entry, or a reading the grammar's rules make of one (`Grammar._unary`; a noun
        before a noun, `_together`), whose category is one of `ways`."""
        for way in ways:
            if cls == "VERB":
                for form, frames in self.verb_templates.items():
                    if form == "frames":
                        continue
                    for frame, templates in frames.items():
                        if any(_alike(way, self._category(t["cat"])) for t in templates):
                            return "VERB", frame
                continue
            alike = [t for t in self.templates.get(cls, ()) if _alike(way, self._category(t["cat"]))]
            if alike:
                return max(alike, key=lambda t: _exactness(way, self._category(t["cat"]))).get("use", cls), ""
            made = {"ADJECTIVE": (("N/N", "ADJECTIVE:before"), ("N\\N", "ADJECTIVE")),
                    "NOUN": (("N", "NOUN"), ("N/N", "NOUN:compound")), "NAME": (("N", "NAME"),),
                    "NUMERAL": (("N", "NUMERAL:alone"),)}.get(cls, ())
            for cat, use in made:
                if _alike(way, self._category(cat)):
                    return use, ""
        return None

    def _preposition_derived(self, derived: Derived, low: str, closed: Sequence[Mapping[str, Any]],
                             taker: Optional[Tuple[str, Optional[int]]]) -> Tuple[str, str]:
        """A preposition heading a phrase a word takes (`pp/np`), named by what takes it: where the grammar has a
        word take the phrase by this very preposition ("Two of them": `PP[of]`; "killed by a hornet": `PP[by]`), the
        preposition's entry making it; else the preposition read as telling of what takes the phrase, a thing
        ("my uncle in Paris"), a quality ("proud of"), what is said of a thing ("is in the garden"), or a doing."""
        if taker is None:
            return "PREPOSITION", ""
        took = bank_category(taker[0])
        own = [e for e in closed if isinstance(self._category(e["cat"]), Fn)
               and isinstance(self._category(e["cat"]).res, Atom) and self._category(e["cat"]).res.base == "PP"
               and self._category(e["cat"]).res.feat == low]
        if own:
            mine = _marked(took, low)
            if any(_alike(mine, cat) for cat in self._taking_pp()):
                return own[0]["use"], ""
        rest = _without_taken(took)
        if isinstance(rest, Atom) and rest.base in ("N", "NP"):
            return "PREPOSITION:thing", ""
        if isinstance(rest, Fn) and isinstance(rest.res, Atom) and (rest.res.base, rest.res.feat) == ("S", "adj"):
            return "PREPOSITION:quality", ""
        if taker[1] is not None and any(_alike(_said_of_a_thing(took), self._category(e["cat"]))
                                        for e in self.closed.get(derived.words[taker[1]].lower(), [])):
            return "PREPOSITION:said", ""
        return "PREPOSITION", ""

    def _taking_pp(self) -> List[Cat]:
        """Every category the grammar gives a word that takes a preposition's phrase by its preposition
        (`NP/PP[of]`, `(S[pss]\\NP)/PP[by]`)."""
        if self._taking_pps is None:
            written = [e["cat"] for es in self.closed.values() for e in es]
            written += [t["cat"] for ts in self.templates.values() for t in ts]
            written += [t["cat"] for form, frames in self.verb_templates.items() if form != "frames"
                        for ts in frames.values() for t in ts]
            self._taking_pps = [c for c in (self._category(w) for w in written) if isinstance(c, Fn)
                                and isinstance(c.arg, Atom) and c.arg.base == "PP" and c.arg.feat]
        return self._taking_pps

    def _together(self, tokens: Sequence[str], i: int) -> List[Tuple[int, Entry]]:
        out: List[Tuple[int, Entry]] = []
        n = len(tokens)
        # The grammar's words of several words ("no one", "how many", "kind of").
        for words, e in self.together.items():
            parts = words.split()
            if [t.lower() for t in tokens[i:i + len(parts)]] == parts:
                for one in e:
                    out.append((i + len(parts), Entry(one["cat"], tuple(tuple(p) for p in one.get("sem", ())),
                                                      one.get("class", "GRAMMAR"), words,
                                                      math.log(one.get("weight", 1.0)), one.get("label", ""))))
        # A number said in several words ("five hundred", "forty-five", "six thousand seven hundred and eighty-nine"):
        # one number, its value as the words make it.
        number = self._number_words(tokens, i)
        if number is not None:
            end, value = number
            score = sum(self._evidence(tokens, k).get("NUMERAL", -2.0) for k in range(i, end)
                        if tokens[k].lower() in self.numbers or tokens[k].lower() in self.number_scales)
            for t in self.templates.get("NUMERAL", ()):
                out.append((end, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "NUMERAL", str(value),
                                       score, t.get("label", ""))))
        # A TIME OF THE CLOCK ("6:30", "7:15 a.m.", "5 p.m.", "six o'clock") is one time, written as times are
        # (`literals.classify_literal`): its half of the day where its words say it, never where they do not. Read
        # word by word, "six o'clock" was six and a thing called o'clock, and "8:00" the number 8.
        clock = self._clock_time(tokens, i)
        if clock is not None:
            end, written = clock
            for t in self.templates.get("NUMERAL", ()):
                if t.get("use") == "NUMERAL:alone":
                    out.append((end, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "NUMERAL", written,
                                           0.0, "time")))
        # A preposition of several words ("in front of", "to the left of"), read as one.
        for words, cls in self.phrases.items():
            parts = words.split()
            if [t.lower() for t in tokens[i:i + len(parts)]] == parts:
                for t in self.templates.get(cls, ()):
                    out.append((i + len(parts), Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls,
                                                      words, 0.0, t.get("label", ""))))
        # A name in quotes: "Sunflowers", the "Concierto de Aranjuez".
        if tokens[i] in ('"', "``", "“") and i + 2 < n:
            for j in range(i + 2, n):
                if tokens[j] in ('"', "''", "”"):
                    inside = [t for t in tokens[i + 1:j] if any(ch.isalnum() for ch in t)]
                    if inside and j - i <= 8:
                        out.append((j + 1, self._name_entry(inside)))
                    break
        # A name of several words: capitalised words in a row, with the words a name may hold between them ("Charles
        # de Gaulle", "Coca-Cola"), as sure as each of its words is a name.
        for start, end in self._name_runs(tokens):
            if start == i:
                score = sum(self._evidence(tokens, k).get("NAME", -20.0) for k in range(start, end)
                            if tokens[k][:1].isupper())
                out.append((end, self._name_entry([t for t in tokens[start:end] if t != "-"], score)))
        # Words joined by hyphens are one word where memory holds them as one ("bullet-proof", `bulletproof`;
        # "state-of-the-art"), as written (`hyphened`).
        for start, end, joined in self.hyphened(tokens):
            if start != i or joined is None:
                continue
            # No name: a name joined by a hyphen is capitalised throughout ("Coca-Cola", a name of several words).
            for cls, p in self._evidence([joined], 0, (_beside(tokens, i - 1), _beside(tokens, end))).items():
                name = self.words.name(joined, cls) if cls != "NAME" else joined.lower()
                for t in self.templates.get(cls, ()) if cls != "VERB" else ():
                    out.append((end, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls, name, p,
                                           t.get("label", ""))))
        # A verb and the word after it that memory knows together as one verb ("passed away", "let up"), as often as
        # the second is said with a verb so.
        if i + 1 < n and tokens[i].isalpha() and tokens[i + 1].isalpha() and tokens[i + 1][:1].islower():
            verb = self._evidence(tokens, i).get("VERB")
            name = self.words.name(tokens[i], "VERB") if verb is not None else ""
            # ASKED UNDER THE WORDS AS WRITTEN, which is how a verb of several words is held ("grow up", "grew up",
            # "stand for"), as well as under the verb's name, which is the thing's and not the word's ("grow"
            # `cultivate grow`, "show" `to show`): asked under the name alone, "Where did Golda Meir grow up?" read
            # no whole (lyric_dev2, 2026-10-29).
            together = (self.words.known_verb([tokens[i].lower(), tokens[i + 1].lower()])
                        or self.words.known_verb([name, tokens[i + 1].lower()])) if verb is not None else None
            if together:
                particle = self._said_as_one(tokens, i, name)[0]
                # IN THE FRAMES IT IS HELD TO BE USED IN, where any are: "make it" is never said of a thing, and
                # "Roy made it clear." read "clear" as what Roy made it (lyric_dev2, 2026-10-27).
                held_frames = {f for f, k in self.words.frames(together).items() if k > 0}
                for form, r in self._forms(tokens[i], name).items():
                    for frame, q in self._frame_evidence(together, _beside(tokens, i + 2)).items():
                        if held_frames and frame not in held_frames:
                            continue
                        for t in self.verb_templates.get(form, {}).get(frame, ()):
                            out.append((i + 2, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "VERB",
                                                     together, verb + r + q + particle, f"{form}:{frame}:particle")))
        # A noun before a noun names one thing with it ("cell phone"), as often as the first is said before another.
        if i + 1 < n and tokens[i].isalpha() and tokens[i + 1].isalpha() and tokens[i][:1].islower() \
                and tokens[i + 1][:1].islower():
            first = dict(self.words.uses(tokens[i]))
            if "NOUN" in first or "NOUN:compound" in first:
                second = self._evidence(tokens, i + 1).get("NOUN")
                if second is not None and tokens[i].lower() not in self.closed:
                    score = estimate(first, self.words.like(tokens[i], "uses"),
                                     set(first) | {"NOUN:compound"})["NOUN:compound"] + second
                    # NAMED BY ITS OWN WORDS, the second as the word it is a form of ("dairy products" `dairy
                    # product`): named by the second word's name instead, "cell phone" was `cell telephone`, which
                    # is no thing's name and no words of the sentence (2026-10-29).
                    name = f"{tokens[i].lower()} {self.words.lexeme(tokens[i + 1], 'NOUN')}"
                    for t in self.templates.get("NOUN", ()):
                        out.append((i + 2, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "NOUN", name,
                                                 score, "compound")))
        # WORDS MEMORY KNOWS AS ONE WORD, of each kind it holds them as: a thing ("credit card", "bus stop"), a
        # quality ("fed up", "in love"), an adverb ("kind of", "in vain"); as sure as its words are, each used as it
        # is used most. A verb of several words is read by the verb and its particle above, which says the form and
        # the frame too. Asked as written and with the last word as the word it is a form of, which is the spelling
        # a word of several words is held under ("gold medals" `gold medal`, "sleeping pills" `sleeping pill`).
        for length in (3, 2):
            # THE FIRST WORD MAY BE CAPITALISED ("Easter egg", "At last, we arrived"): a run whose later words are
            # written lowercase is no name of several words, which the capitalised run reads (`_name_runs`).
            if i + length > n or not all(t.isalpha() for t in tokens[i:i + length]) \
                    or not all(t[:1].islower() for t in tokens[i + 1:i + length]):
                continue
            said = [t.lower() for t in tokens[i:i + length]]
            held = dict(self.words.known_words(said))
            base = self.words.lexeme(said[-1], "NOUN")
            if base and base != said[-1]:
                for cls, name in self.words.known_words(said[:-1] + [base]).items():
                    held.setdefault(cls, name)
            if not held:
                continue
            score = sum(max(self._evidence(tokens, k).values(), default=-20.0) for k in range(i, i + length))
            for cls, known in held.items():
                for t in self.templates.get(cls, ()):
                    out.append((i + length, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls,
                                                  known, score, "known together")))
            break
        return out

    def _number_runs(self, tokens: Sequence[str]) -> List[Tuple[int, int]]:
        key = tuple(tokens)
        if self._numbers_of[0] != key:
            runs, i = [], 0
            while i < len(tokens):
                found = self._number_words(tokens, i)
                if found is not None:
                    runs.append((i, found[0]))
                    i = found[0]
                else:
                    i += 1
            self._numbers_of = (key, runs)
        return self._numbers_of[1]

    def _clock_time(self, tokens: Sequence[str], i: int) -> Optional[Tuple[int, str]]:
        """The time of the clock said from word i ("6:30", "7:15 a.m.", "5 p.m.", "six o'clock"), as times are written
        (`literals.classify_literal`), and the word after it; None where none is said."""
        from core.semantics.literals import classify_literal
        word = tokens[i]
        hour: Optional[str] = None
        end = i + 1
        if re.fullmatch(r"\d{1,2}:\d{2}", word):
            hour = word
        else:
            number = self._number_words(tokens, i)
            value = number[1] if number is not None else _number(word) if _number(word) is not None \
                else self.numbers.get(word.lower())
            if value is not None and float(value) == int(float(value)) and 1 <= int(float(value)) <= 12:
                hour, end = str(int(float(value))), number[0] if number is not None else i + 1
        if hour is None:
            return None
        after = tokens[end].lower().rstrip(".") if end < len(tokens) else ""
        if after in ("a.m", "p.m", "am", "pm"):
            literal = classify_literal(f"{hour} {after[0]}.m.")
            end += 1
        elif after in ("o'clock", "o’clock", "oclock"):
            literal = classify_literal(f"{hour}:00" if ":" not in hour else hour)
            end += 1
        elif ":" in hour:
            literal = classify_literal(hour)
        else:
            return None
        return (end, literal.canonical) if literal is not None and literal.kind == "time" else None

    def hyphened(self, tokens: Sequence[str]) -> List[Tuple[int, int, Optional[str]]]:
        """WORDS JOINED BY HYPHENS ("state-of-the-art", "novel-based", "33-year-old"): where each run starts and ends,
        and how memory holds it as one word (`Words.spelled`), None where it holds no such word. Held, it is that one
        word; held in none of its spellings, it is its words, the hyphens no mark between them, as the PMB's gold
        reads them: of the 80 such words of its training sentences (numbers and names aside), 57 of the 58 WordNet
        holds in some spelling are one word, and 16 of the 22 it holds in none are their words ("a novel-based film",
        "a 33-year-old"). A number's words ("forty-eight") and a name's ("Coca-Cola") are read as a number's and a
        name's are."""
        key = tuple(tokens)
        if self._hyphened_of[0] != key:
            runs: List[Tuple[int, int, Optional[str]]] = []
            n, i = len(tokens), 0
            while i < n:
                end = i + 1
                while end + 1 < n and tokens[end] == "-" and tokens[end - 1].isalnum() and tokens[end + 1].isalnum() \
                        and not tokens[end + 1][:1].isupper() \
                        and not (self._is_number(tokens[end - 1]) and self._is_number(tokens[end + 1])):
                    end += 2
                if end > i + 1:
                    runs.append((i, end, self.words.spelled("-".join(tokens[i:end:2]))))
                i = end
            self._hyphened_of = (key, runs)
        return self._hyphened_of[1]

    def _number_name(self, word: str) -> Optional[str]:
        """A number word's value, as the grammar's numbers give it ("seven": 7)."""
        w = word.lower()
        value = self.numbers.get(w, self.number_scales.get(w))
        return str(value) if value is not None else None

    def _number_words(self, tokens: Sequence[str], i: int) -> Optional[Tuple[int, int]]:
        """A number said in several words from i: (the word after it, its value); None where fewer than two words say
        one. Its words are the grammar's numbers (`numbers`, `number_scales`), with "and" and "-" between them."""
        total = current = 0
        end = i
        k = i
        said = 0
        n = len(tokens)
        while k < n:
            w = tokens[k].lower()
            if w in self.numbers:
                current += self.numbers[w]
            elif w in self.number_scales:
                scale = self.number_scales[w]
                if scale == 100:
                    current = (current or 1) * scale
                else:
                    total += (current or 1) * scale
                    current = 0
            elif w == "-" and said and k + 1 < n and tokens[k + 1].lower() in self.numbers:
                k += 1
                continue
            elif w == "and" and said and k > 0 and tokens[k - 1].lower() in self.number_scales and k + 1 < n \
                    and tokens[k + 1].lower() in self.numbers:
                # "seven hundred and eighty-nine": "and" inside a number only after a hundred or more ("ten and five"
                # are two numbers).
                k += 1
                continue
            else:
                break
            said += 1
            k += 1
            end = k
        if said < 2:
            return None
        return end, total + current

    def _name_runs(self, tokens: Sequence[str]) -> List[Tuple[int, int]]:
        """The names of several words in the sentence: capitalised words side by side are one name. A word opening
        the sentence starts one only where it is used as a name more than as anything else."""
        key = tuple(tokens)
        if self._runs_of[0] == key:
            return self._runs_of[1]
        runs: List[Tuple[int, int]] = []
        n, i = len(tokens), 0
        while i < n:
            word = tokens[i]
            if not (word[:1].isupper() and any(ch.isalpha() for ch in word)):
                i += 1
                continue
            if (i == 0 or tokens[i - 1] in ('"', ":", "``")) and not self._mostly_name(word):
                i += 1
                continue
            j, last = i + 1, i
            while j < n:
                t = tokens[j]
                if t[:1].isupper() and any(ch.isalpha() for ch in t) and t.lower() not in ("i",):
                    last = j
                elif not ((t.lower() in self.name_particles or t == "-") and j + 1 < n
                          and tokens[j + 1][:1].isupper()):
                    break
                j += 1
            if last > i:
                runs.append((i, last + 1))
            i = last + 1
        self._runs_of = (key, runs)
        return runs

    def _mostly_name(self, word: str) -> bool:
        if word.lower() in self.closed:
            return False
        held = self.words.uses(word)
        return not held or held.get("NAME", 0.0) >= sum(n for c, n in held.items() if c != "NAME")

    def _name_entry(self, words: Sequence[str], score: float = 0.0) -> Entry:
        name = " ".join(w.lower() for w in words)
        return Entry("NP.@", (), "NAME", name, score, "name")

    # ── what was read ──
    def uses_in(self, sign: Sign, tokens: Sequence[str]) -> Tuple[List[Tuple[str, str]],
                                                                  List[Tuple[str, str, str, str]]]:
        """How a reading used each of its words, named as the treebank's uses are counted (`HeldWords.use_of`): a word
        of a kind as its kind ("NOUN") or one of the kind's ways ("ADJECTIVE:degree"), a grammar word as its way
        ("be:np"); and each verb, its form and its frame (`(word, verb, form, frame)`). A name of several words is no
        word's use."""
        uses: List[Tuple[str, str]] = []
        verbs: List[Tuple[str, str, str, str]] = []
        stack = [sign]
        while stack:
            s = stack.pop()
            if s.rule != "lex":
                stack.extend(s.kids)
                continue
            if s.end - s.start != 1:
                continue
            said = next((p for p in s.pieces if p[0] == "word"), None)
            if said is None:
                continue
            low, cls = str(tokens[s.start]).lower(), said[2]
            if cls == "VERB" and ":" in s.entry:
                form, frame = s.entry.split(":", 1)
                uses.append((low, "VERB"))
                verbs.append((low, str(said[1]), form, frame))
            elif cls == "GRAMMAR":
                use = next((e["use"] for e in self.closed.get(low, []) if e.get("label", e["use"]) == s.entry), None)
                if use:
                    uses.append((low, use))
            else:
                uses.append((low, next((t.get("use", cls) for t in self.templates.get(cls, ())
                                        if (t.get("label", "") or cls) == s.entry), cls)))
        return uses, verbs

    # ── what was learned ──
    def time_of(self, term: Any) -> Optional[str]:
        """Whether a term is a time, and which: as memory holds it (`Words.is_time`: a point or a stretch), else a point
        where sentences taught with their meanings said a happening was during one of it (`Grammar.learn`, the `time`
        table): "The dog barked in the morning." taught that a morning is when things happen, where memory holds
        nothing of what a morning is, and "One morning the dog ran to the park." could not be read without it."""
        if not isinstance(term, str):
            return None
        held = self.words.is_time(term)
        if held:
            return held
        return "point" if self.learned["time"].get((term.lower(),)) else None

    def link(self, table: str, key: Tuple, default: Optional[str]) -> Tuple[Optional[str], str]:
        """The link `table` holds for `key`, most often said, and where it came from: "own" (said of this word),
        "kind" (said of what memory holds it a kind of), or "rule" (the grammar's link, nothing being said of either).
        THE GRAMMAR'S LINK COUNTS AS ONE SAYING OF ITS OWN (`_weighed`): one sentence saying otherwise ties with it,
        and the rule stands ("This material absorbs CO2." taught the material as what the absorbing is for, and
        every subject of "absorb" after it was read so); two say more than the rule."""
        held = self.learned[table].get(key)
        if held:
            return _weighed(held, default), "own"
        return default, "rule"

    def inherited(self, table: str, name: str, cls: str, rest: Tuple, default: Optional[str]) \
            -> Tuple[Optional[str], str]:
        """As `link`, for a word whose own uses say nothing: what is said of the nearest kind memory holds it to be."""
        held = self.learned[table].get((name,) + rest)
        if held:
            return _weighed(held, default), "own"
        for kind in self.words.kinds(name, cls):
            held = self.learned[table].get((kind,) + rest)
            if held:
                return _weighed(held, default), "kind"
        return default, "rule"

    def selected(self, table: str, key: Tuple, what: Sequence[str], default: Optional[str]) \
            -> Tuple[Optional[str], str]:
        """WHAT A LINK SAYS, BY WHAT THE THING IT JOINS IS: "with" a person is with whom it was done ("Vance worked
        with Hooper."), "with" a tool what it was done with; "in" a country where. The link `table` holds for `key`
        and the nearest of `what` (`_what_is`) two taught sentences said something of, weighed against `default`
        (what is said of the word whatever its thing is); `default` where nothing is said of any."""
        for kind in what:
            held = self.learned[table].get(tuple(key) + (kind,))
            if held and sum(held.values()) >= 2:
                return _weighed(held, default), "kind"
        return default, "rule"


def _weighed(held: Counter, default: Optional[Any]) -> Optional[Any]:
    """What sentences said, the grammar's own link counted once beside them; the rule where they tie with it.

    A LINK HELD AS ITS WORD IS NO RULE (`relation_types.worded`: "with" as `word_with`, where nothing known says which
    link it makes) and counts as no saying: it commits to no kind, and where memory knows the kind, the kind is said.
    Counted as one, one sentence teaching "with a pin" a `done_with` tied with it and lost, and "Roy painted the
    medal with paint." was `word_with` (TRAIN-FORMAT-02, lyric_dev2, 2026-10-26)."""
    counts = Counter(held)
    if default is not None and not is_worded(default):
        counts[default] += 1
    if not counts:
        return default
    best = max(counts.values())
    if default is not None and counts[default] == best:
        return default
    return counts.most_common(1)[0][0] or None


def estimate(own: Mapping[str, float], like: Mapping[str, float], ways: Iterable[str]) -> Dict[str, float]:
    """How often a word is used each way, as a logarithm: its own uses counted, with one use more spread over the
    ways as words spelled like it are used (`Words.like`: "-ing" words are mostly doings), half of it, and evenly,
    the other half. A word used often is read as it is used; a word seldom or never seen, as words like it are."""
    ways = list(dict.fromkeys(ways))
    if not ways:
        return {}
    k = len(ways)
    mass = sum(like.get(w, 0.0) for w in ways)
    prior = {w: 0.5 * (like.get(w, 0.0) / mass if mass > 0 else 1.0 / k) + 0.5 / k for w in ways}
    total = sum(own.get(w, 0.0) for w in ways) + 1.0
    return {w: math.log((own.get(w, 0.0) + prior[w]) / total) for w in ways}


def _formula(word: str) -> bool:
    """Whether a piece is a formula written in a sentence: mathematics' own writing, not a word or a number."""
    if _number(word) is not None or word.replace("-", "").replace("'", "").isalpha():
        return False
    # MATHEMATICS IS WRITTEN WITH ITS MARKS: letters and digits alone are a word, however a formula reader could take
    # them ("1980s", the decade, not 1980 times s, and "the late 1980s" went unread; "3rd"), and a hyphen between
    # letters joins a word ("COVID-19").
    marks = "+*/^%!√()×÷·=<>" + ("" if any(ch.isalpha() for ch in word) else "-")
    if not any(ch in marks for ch in word):
        return False
    from core.reasoning.arithmetic_reading import read_expression
    try:
        return read_expression(word) is not None
    except Exception:
        return False


def _number(word: str) -> Optional[str]:
    """The number a numeral written in digits says ("3,000": 3000; "2.5"), or None. Python's `float` also reads the
    words "nan", "inf" and "infinity" as numbers, and "1_000": English writes no number so, and "My nan baked a cake."
    stopped the grammar (READ-LEARN-01, 2026-10-25). A numeral too large to hold ("1e999") is said as written."""
    text = word.replace(",", "")
    if "_" in text or not any(ch.isdigit() for ch in text):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return text
    return str(int(value)) if value == int(value) else str(value)


class Joining(str):
    """A hyphen written between two words with no space on either side: it joins them into one word ("high-level",
    "thirty-two", "Coca-Cola"), and is no mark between them (`tokens_of`)."""


def tokens_of(text: str, words: Words) -> Tuple[str, ...]:
    """A sentence's words as the grammar reads them: Lyric's pieces (`sentence_machine.form_of`, as a treebank writes
    them: "does", "n't"), with a piece the pieces join as a formula split back into its words where each is a word
    held ("log a failed login" is no logarithm), and kept one where any is not ("2x + 3"). A hyphen joining two words
    is a `Joining` hyphen."""
    from core.semantics.sentence_machine import form_of
    from core.semantics.structure import words_of
    pieces = form_of(text)
    written = words_of(pieces)
    out: List[str] = []
    for k, piece in enumerate(written):
        parts = piece.split()
        if len(parts) > 1 and all(p.isalpha() and words.uses(p) for p in parts):
            out.extend(parts)
        elif piece == "-" and 0 < k < len(written) - 1 and not pieces[k - 1].space_after \
                and not pieces[k].space_after and written[k - 1][-1:].isalnum() and written[k + 1][:1].isalnum():
            out.append(Joining(piece))
        else:
            out.append(piece)
    return tuple(out)


def words_not_held(tokens: Sequence[str], lexicon: "Lexicon") -> Tuple[str, ...]:
    """THE WORDS OF A SENTENCE MEMORY DOES NOT HOLD, each once, in the order first met. A word is held where it is one
    of the grammar's own words (`Lexicon.closed`, the finite classes stated and not discovered), where memory holds
    any use of that form (`Words.uses`, which counts both a class and a grammar entry's use), or where the words'
    knowledge holds a class for it; anything not spelled in letters is no word to hold.

    Asked of the lexicon and not of the words alone, because the two halves live apart: the grammar's own words are
    the lexicon's and every other word is memory's, and `Words` promises a plain answer for a word nothing is held
    of while defining no `closed` at all -- which the question's first writing reached for, so it would have raised
    on any words but the one it was called with.

    Reading is permissive on purpose -- a word nobody taught is read by reading the SENTENCE instead, which is a
    capability and not a fault -- but it was also SILENT. "This sparkles." read whole at 0.915 sure with `sparkles` a
    concept minted from its own letters, and "The whistle juggled Tom." at 0.898 with `tom` resolved from nothing, no
    store holding any of the three (lyric_db, 2026-10-30). `Reading.sure` is the reading's share of every whole
    reading, which is sureness about STRUCTURE among the readings built; nothing anywhere said how much of the
    sentence memory actually holds, so a sentence of words never seen was indistinguishable from one of words taught.
    This is the one place that asks, for reading and for reviewing a word taught alike (`GrammarView.review_word`,
    where the question was first written and answered for the teaching report only)."""
    words = lexicon.words
    knowledge = getattr(words, "knowledge", None)
    out: List[str] = []
    for token in tokens:
        word = str(token).lower()
        if not str(token).isalpha() or word in out:
            continue
        if lexicon.closed.get(word) or words.uses(word) \
                or (knowledge.classes(word) if knowledge is not None else {}):
            continue
        out.append(word)
    return tuple(out)


# ── reading ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Reading:
    """A sentence read: its best reading of the whole (None where the grammar reads no whole), its meaning (None
    where nothing is said in the meaning language, with why), the words, and where the reading broke: the
    stretches the grammar read, the longest first, when no whole was read."""
    words: Tuple[str, ...]
    sign: Optional[Sign]
    meaning: Optional[Meaning]
    why: str = ""
    missing: Tuple[Tuple[int, int], ...] = ()
    names: Dict[int, str] = field(default_factory=dict)
    #: The links decided spelling the meaning out: (what decided: "role", "prep", "poss", ...; of what; by what:
    #: "own" (the word's own uses), "kind" (what memory holds it a kind of), "rule" (the grammar's link); the fact
    #: it made, or None).
    decided: List[Tuple[str, str, str, Optional[MeaningFact]]] = field(default_factory=list)
    #: How sure the reading of the whole is: its share of every reading of the whole the grammar made, each as surely
    #: as it reads its words (`Grammar.read`). SURENESS ABOUT STRUCTURE, never about the words: a sentence holding a
    #: word memory has never seen reads at whatever share its structure wins, which is why `unheld` is kept beside it.
    sure: float = 0.0
    #: The words of the sentence MEMORY DOES NOT HOLD, each once, in the order first met (`words_not_held`): read
    #: anyway, by reading the sentence around them, and now said instead of passed over in silence.
    unheld: Tuple[str, ...] = ()


#: The categories a whole sentence may be read as, and what the speaker wants by each.
WHOLE = {"S[dcl]": "tell", "S[q]": "ask", "S[wq]": "ask", "S[imp]": "tell", "S": "tell", "NP": "tell"}
#: How many sentences saying a meaning are read back to it and said (`Grammar.say`), the best its making ranks first:
#: a reply says the first; the rest are there to compare against.
SAID_AT_MOST = 8
#: Punctuation that closes a sentence, and what it says the speaker wants.
CLOSING = {".": "tell", "!": "tell", "?": "ask"}

#: The links that tell of a happening: what holds them is said with a verb.
_HAPPENING_LINKS = frozenset({"done_by", "done_to", "received_by", "precedes", "follows", "during"})
#: What the situation names ("I", "you", "it", "now"): said with the grammar's own words, never a word for a thing.
_SITUATION = frozenset({"?speaker", "?listener", "?previous", "?now", "?here", "?there"})


def _places_filled(meaning: Meaning) -> Dict[Term, int]:
    """HOW MANY PLACES OF ONE HAPPENING EACH THING FILLS, which is one for all but a thing that is its own
    happening's other place (`done_by` and `done_to` of the same doing: "Tom misled Tom.", and in English a
    reflexive the second time). What `_things_said` says such a thing twice by, and what a word saying it spends
    twice of (`_piece_says`: "we" says a group the speaker is one of, and a sentence naming that group twice says
    it twice)."""
    filled: Counter = Counter((f.subject, f.obj) for f in meaning.facts if f.relation in _HAPPENING_LINKS
                              and f.obj not in _SITUATION and f.subject != f.obj)
    stands: Dict[Term, int] = {}
    for (_, t), n in filled.items():
        stands[t] = max(stands.get(t, 1), n)
    return stands


def _things_said(meaning: Meaning) -> List[Tuple[str, str]]:
    """WHAT A MEANING NAMES, each with the class of word that says it (`Grammar.say`): the kind a thing is
    (`instance_of`), a doing where the thing is a happening; both kinds a kind is said of (`isa`); a quality a thing
    has, an adverb's of a happening; a number; any other thing named, by its name.

    ONCE FOR EACH PLACE OF ONE HAPPENING THE THING FILLS, which is once for all but a thing that is its own
    happening's other place: a sentence says such a thing twice ("Tom misled Tom.", and in English a reflexive the
    second time). Named once however many places it filled, there was one word for it and no sentence putting it in
    both could be made, so every meaning holding one was said back as nothing at all: `Tom misled Tom.` and
    `Tom misled himself.` alike (lyric_db, 2026-10-30)."""
    events = {f.subject for f in meaning.facts if f.relation in _HAPPENING_LINKS}
    stands = _places_filled(meaning)
    out: List[Tuple[Tuple[str, str], Optional[Term]]] = []
    for f in meaning.facts:
        if f.relation == "instance_of" and not is_variable(f.obj):
            out.append(((f.obj, "VERB" if f.subject in events else "NOUN"), f.subject))
            continue
        if f.relation == "isa":
            out += [((t, "NOUN"), None) for t in (f.subject, f.obj) if not is_variable(t)]
            continue
        if f.relation == "has_property" and not is_variable(f.obj):
            out.append(((f.obj, "ADVERB" if f.subject in events else "ADJECTIVE"), None))
            terms = (f.subject,)
        else:
            terms = (f.subject, f.obj)
        for t in terms:
            if not is_variable(t) and t not in _SITUATION:
                out.append(((t, "NUMERAL" if _number(str(t)) is not None else "NAME"), t))
    # A doing is said once however many places it fills of another: a word for it says the whole of it.
    said: Dict[Tuple[str, str], int] = {}
    for key, term in out:
        said[key] = max(said.get(key, 1), 1 if term is None or term in events else stands.get(term, 1))
    return [key for key in dict.fromkeys(key for key, _ in out) for _ in range(said[key])]


def _said_by_other(meaning: Meaning) -> Set[MeaningFact]:
    """THE FACTS "ANOTHER" SAYS IN A MEANING, as `spell_out` makes them of its `other`: of each thing held not to be
    another thing, where that other is a thing given of the same kind and nothing more is said of it, the denial and
    what the other is."""
    out: Set[MeaningFact] = set()
    for f in meaning.facts:
        if f.relation != "equals" or f.positive or not (is_variable(f.subject) and is_variable(f.obj)):
            continue
        for one, other in ((f.subject, f.obj), (f.obj, f.subject)):
            of_other = [g for g in meaning.facts if other in (g.subject, g.obj)]
            kinds = {g.obj for g in meaning.facts if g.relation == "instance_of" and g.subject == one and g.positive}
            if len(of_other) == 2 and any(g.relation == "instance_of" and g.subject == other and g.given
                                          and g.positive and g.obj in kinds for g in of_other):
                out.update(of_other)
    return out


def _piece_says(piece: Tuple, meaning: Meaning) -> Optional[int]:
    """WHAT A PIECE OF A GRAMMAR WORD'S ENTRY SAYS IN A MEANING, as `spell_out` makes it: how many of the meaning's
    facts it may say (a thing known, `given`; a time before now, `past`; what one thing is of another, `be`: `isa`,
    `equals`, or a named thing of a kind; a denial, `deny`; a link a word names, `fact`; the one spoken of before,
    `pron`), none for any other piece;
    None for a piece saying nothing a meaning holds (`indefinite`, `finite`, `some`); a thing that is not another of
    its kind, `other`: a denied `equals`."""
    kind, facts = piece[0], meaning.facts
    if kind in ("indefinite", "finite", "some"):
        return None
    if kind == "given":
        return sum(1 for f in facts if f.given)
    if kind == "past":
        return sum(1 for f in facts if f.relation == "precedes" and f.obj == "?now")
    if kind == "be":
        return sum(1 for f in facts if f.relation in ("isa", "equals")
                   or (f.relation == "instance_of" and not is_variable(f.subject)))
    if kind == "deny":
        return sum(1 for f in facts if not f.positive)
    if kind == "other":
        return sum(1 for f in facts if f.relation == "equals" and not f.positive)
    if kind == "pron":
        # THE ONE SPOKEN OF BEFORE IS SAID AS OFTEN AS IT STANDS IN A PLACE, as the speaker and the listener are
        # (`Grammar.say`'s `situation`, which counts them): counted once however many places it filled, two words
        # could never say it and a sentence saying it twice could not be made at all -- "They misled themselves."
        # was said back as nothing (lyric_db, 2026-10-30). A pronoun of its own sentence ("himself") says it as any
        # other does; which places take it is not settled here but by reading, which binds it to what stands before
        # it (`spell_out`) and reads no sentence where nothing does, so a sentence saying it wrongly is never kept.
        # Refused here instead, every reflexive was unsayable and lifting the refusal alone changed nothing, the
        # count being what stopped it.
        #
        # A PRONOUN OF ITS OWN SENTENCE WHOSE THING IS NOT THE ONE SPOKEN OF BEFORE SAYS NOTHING OF ITS OWN, and is
        # said by what else its entry says ("ourselves", a group the speaker is one of) or by what its category
        # stands for ("myself", "yourself"). It cannot be counted against `?previous` as "himself" is, a meaning of
        # the speaker holding none, and counted so it spent nothing and was refused with its whole entry.
        previous = sum(1 for f in facts for t in (f.subject, f.obj) if t == "?previous")
        if len(piece) > 3 and piece[3] == "own":
            return previous or None
        return previous
    if kind == "fact":
        # AS OFTEN AS THE MEANING HOLDS IT, AND ONCE MORE FOR EACH FURTHER PLACE ITS THING FILLS: a word saying the
        # fact is the word naming the thing ("we", "us": a group the speaker is one of), so a sentence naming that
        # group in two places of one doing says it twice. Counted by the facts alone, one word could be said and
        # "We misled ourselves." was said back as nothing (lyric_db, 2026-10-30).
        stands = _places_filled(meaning)
        return sum(stands.get(f.subject, 1) for f in facts if f.relation == piece[1])
    return 0


def _says_of(entry: Entry, meaning: Meaning) -> Optional[Dict[Tuple[str, ...], int]]:
    """WHAT A GRAMMAR WORD'S ENTRY SAYS OF A MEANING (`Grammar.say`), as what it spends: each piece saying something
    the meaning holds (`_piece_says`), with how often the meaning holds it; ONE FOR EVERY WORD SAYING IT ("is", "was"
    and "'s" all say one `be`, so a meaning of one kind said of another has one of them). None where a piece says
    what the meaning does not hold; empty for an entry saying nothing."""
    out: Dict[Tuple[str, ...], int] = {}
    for piece in entry.sem:
        n = _piece_says(piece, meaning)
        if n is None:
            continue
        if n == 0:
            return None
        out[("fact", piece[1]) if piece[0] == "fact" else (piece[0],)] = n
    return out


def _comes_to(cat: Cat) -> List[Cat]:
    """What a category comes to as it takes what it takes: each result, the first taken first ("is" before a noun
    phrase: `S[dcl]\\NP`, then `S[dcl]`)."""
    out: List[Cat] = []
    while isinstance(cat, Fn):
        cat = cat.res
        out.append(cat)
    return out


def _heads_a_clause(cat: Cat) -> bool:
    """Whether a word of this category heads a sentence of its own: it makes a sentence and takes none ("paint",
    "is" before a noun phrase; never "did" or "to", which take the doing they make finite or make an aim of)."""
    if not _clausal(cat):
        return False
    while isinstance(cat, Fn):
        if _clausal(cat.arg):
            return False
        cat = cat.res
    return True


def _meant(sign: "Sign", order: Sequence[int], tokens: Sequence[str]) -> Tuple:
    """WHAT A SIGN MADE IN SAYING MEANS, as reading spells it out (`spell_out`): its category and its pieces, their
    variables numbered as they come, each word by where it stands among the sign's words (`order`), a word for a thing
    by how it is written ("wall", "walls"), a grammar word not by which it is ("is", "'s" and "was" each say `be`, and
    `spell_out` reads no grammar word by its name). Two signs meaning the same in one category go on to the same
    sentences."""
    rank = {at: k for k, at in enumerate(order)}
    seen: Dict[int, int] = {}

    def term(t: Any) -> Any:
        if isinstance(t, int) and not isinstance(t, bool):
            return ("at", rank.get(t, -1)) if t < FIRST_VARIABLE else ("x", seen.setdefault(t, len(seen)))
        return t

    def walk(c: Cat) -> Tuple:
        if isinstance(c, Atom):
            return (c.base, term(c.feat), term(c.ref))
        return (walk(c.res), c.slash, walk(c.arg))
    shape = walk(sign.cat)
    pieces = []
    for p in sign.pieces:
        if p[0] == "word":
            if p[2] != "GRAMMAR":
                pieces.append(("word", p[1], p[2], tokens[p[3]], rank.get(p[3], -1)))
            continue
        pieces.append(tuple(term(t) for t in p))
    return shape, tuple(pieces)


def _joins(cat: Cat) -> bool:
    """Whether a word of this category, saying nothing, joins a sentence onto another thing: it takes a sentence and
    makes of it what modifies something ("that", "who": `(N\\N)/(S[dcl]\\NP)`; "if")."""
    return isinstance(cat, Fn) and _clausal(cat.arg) and isinstance(cat.res, Fn) and _same_shape(cat.res.res,
                                                                                                    cat.res.arg)


def _written(said: Sequence[str], closing: str) -> str:
    """Words said, written as a sentence: one space between words, none before a word's ending written apart ("'s",
    "n't"), the first letter a capital, its closing mark."""
    text = re.sub(r" (?=['\u2019]|n't\b)", "", " ".join(said))
    return text[:1].upper() + text[1:] + closing


def _clausal(cat: Cat) -> bool:
    """Whether a category is of a doing or a sentence: what it makes, taken all it takes, is a sentence (`S`)."""
    while isinstance(cat, Fn):
        cat = cat.res
    return cat.base == "S"


#: The kinds of word the treebanks join to the word they mark, not what they mark to them (`Grammar._joined`): "in"
#: to "park" in "in the park", "the" to "dog", "is" to "teacher" in "is a teacher", "that" to the doing it opens.
MARKING = frozenset({"PREPOSITION", "SUBORDINATOR", "DETERMINER", "AUXILIARY", "CONJUNCTION", "PARTICLE"})


class Grammar:
    """Reads sentences by the grammar (`read`), and learns from sentences taught with their meanings (`learn`)."""

    def __init__(self, lexicon: Lexicon):
        self.lexicon = lexicon
        self._fresh = FIRST_VARIABLE
        self._tokens: Tuple[str, ...] = ()
        #: What agreement is weighed by, worked out once for the words being read or said (`_features`,
        #: `_agreement`): the features subjects agree by, every verb's subjects, each verb's, each word's forms.
        self._agreeing: Dict[Any, Any] = {}
        #: The sentences memory holds analysed, as the structure reader reads them (`structure.StructureView`): which
        #: of two readings read as surely the chart keeps (`_joined`). None where none is held.
        self.structure: Optional[Any] = None
        self._weighed: Optional[Any] = None
        self._marking: FrozenSet[int] = frozenset()
        self._asking: FrozenSet[int] = frozenset()

    # ── the chart ──
    def _new(self) -> int:
        self._fresh += 1
        return self._fresh

    def _lexical(self, tokens: Sequence[str], i: int, end: int, entry: Entry,
                 bound: Optional[Mapping[str, Term]] = None) -> Sign:
        """A word read as one of its entries; `bound`, each of the entry's variables a meaning's term it is said of
        (`Grammar.say`, Kay binding), the rest fresh."""
        names: Dict[str, Term] = dict(bound or {})

        def term(t: Optional[str]) -> Optional[Term]:
            if t is None:
                return None
            if t == "@":
                return entry.name
            if t.startswith("?") or t[:1].isdigit() or t in ("false", "true"):
                return t
            if t not in names:
                names[t] = self._new()
            return names[t]

        def instantiate(c: Cat) -> Cat:
            if isinstance(c, Atom):
                feat = c.feat
                if feat is not None and feat[:1].isupper():
                    feat = term("F:" + feat)
                elif feat == "@":
                    feat = entry.name
                return Atom(c.base, feat, term(c.ref))
            return Fn(instantiate(c.res), c.slash, instantiate(c.arg))
        cat = instantiate(parse_category(entry.cat))
        pieces = []
        for p in entry.sem:
            what, *args = p
            out = [what]
            for a in args:
                if a == "@":
                    out.append(entry.name)
                elif isinstance(a, str) and _MEANING_VARIABLE.fullmatch(a):
                    out.append(term(a))
                elif isinstance(a, str) and re.fullmatch(r"[A-Z]", a):
                    out.append(term("F:" + a))
                else:
                    out.append(a)
            out.append(i)
            pieces.append(tuple(out))
        pieces.append(("word", entry.name, entry.cls, i, end))
        # WHICH THING A DETERMINER SAYS WHICH OF, kept so its noun is weighed with it wherever the two first stand
        # together (`_met`), whichever rule joins them: "is an" composed before "artifacts" was not weighed.
        if entry.cls == "GRAMMAR" and entry.label == "det" and isinstance(cat, Fn) and isinstance(cat.arg, Atom) \
                and cat.arg.base == "N":
            pieces.append(("det", cat.arg.ref, i))
        # Of a noun of several words, the last is the one it is ("credit card": a card).
        head = end - 1 if entry.cls == "NOUN" else i
        return Sign(cat, tuple(pieces), entry.score, i, end, "lex", (), head, entry.label or entry.cls,
                    entry.crossing)

    def _combine(self, left: Sign, right: Sign) -> List[Sign]:
        out: List[Sign] = []
        lc, rc = left.cat, right.cat

        def made(cat: Cat, s: Dict[int, Term], rule: str, head: int, weighed: float = 0.0) -> None:
            out.append(Sign(_apply(cat, s), (), left.score + right.score + weighed + self._met(left, right, s, rule),
                            left.start, right.end, rule, (left, right), head, binding=s))
        # A stretch joined by "and" waits for what it is joined to, and nothing else takes it.
        joining = isinstance(rc, Fn) and rc.slash == "&"
        if isinstance(lc, Fn) and lc.slash == "&":
            return out
        # Punctuation joins nothing: a comma, a quote or a dash is read with what it stands beside; a stop or a
        # question mark only with what it closes.
        if isinstance(rc, Atom) and rc.base == "punct":
            if rc.feat in (",", ";", ":", '"', "-", "''", "``", ")", "--") or (rc.feat in CLOSING):
                out.append(Sign(lc, left.pieces + (("closing", rc.feat, right.start),) if rc.feat in CLOSING else
                                left.pieces, left.score + right.score, left.start, right.end, "punct", (left, right),
                                left.head))
            return out
        if isinstance(lc, Atom) and lc.base == "punct":
            if joining:
                return out
            if lc.feat in (",", '"', "``", "(", "--", "-") and not (isinstance(rc, Atom) and rc.base in ("punct",
                                                                                                         "conj")):
                out.append(Sign(rc, right.pieces, left.score + right.score, left.start, right.end, "punct",
                                (left, right), right.head))
            if lc.feat == "," and not (isinstance(rc, Atom) and rc.base in ("punct", "conj")):
                # A comma joining two in a list ("Ken, Bill and Yumi").
                out.append(Sign(Fn(rc, "&", rc), right.pieces + (("and", ",", right.start),), left.score
                                + right.score, left.start, right.end, "conj", (left, right), right.head))
            return out
        # Sentences one after another are each told ("It's not blood. It's beet."): a sentence closed by its stop
        # with the next.
        if isinstance(lc, Atom) and lc.base == "S" and isinstance(rc, Atom) and rc.base == "S" \
                and any(p[0] == "closing" and p[2] == right.start - 1 for p in left.pieces):
            out.append(Sign(rc, left.pieces + right.pieces + (("main", _hook(lc), left.start),),
                            left.score + right.score, left.start, right.end, "then", (left, right), right.head))
            return out
        # Words joined by "and", "or", "but": the second with its joining word first.
        if isinstance(lc, Atom) and lc.base == "conj":
            if not (isinstance(rc, Atom) and rc.base in ("punct", "conj")) and not joining:
                out.append(Sign(Fn(rc, "&", rc), right.pieces + (("and", lc.feat, left.start),),
                                left.score + right.score, left.start, right.end, "conj", (left, right), right.head))
            return out
        if joining:
            joined = self._coordinate(left, right)
            if joined is not None:
                out.append(joined)
            return out
        # Application.
        if isinstance(lc, Fn) and lc.slash == "/":
            s: Dict[int, Term] = {}
            if _unify(lc.arg, rc, s) and (not _after_its_subject(lc)
                                          or self._stands_as_written(left, right, lc.res, s)):
                # A SUBJECT ALREADY RAISED AGREES WITH ITS VERB AS ANY OTHER SUBJECT DOES. The words that deny are
                # stated raised (`nothing`, `nobody`, `none`: `S/(S\NP)`), so they take their verb's phrase by this
                # rule and were weighed by neither of the two that ask for a subject, both of which ask the subject
                # to be one category and not a function. Saying was free of a sixth way to score no evidence as
                # perfect agreement: of nobody being intelligent, "Nothing am intelligent." was said, "am" never
                # once asked how well it agreed with "nothing" (lyric_db, 2026-10-30).
                made(lc.res, s, ">", right.head if _takes_its_head(lc) else left.head,
                     self._agreement(left, right) if _raised_subject(lc) and _verb_phrase(rc) else
                     self._object_agreement(left, right) if _takes_object(lc) and isinstance(rc, Atom) else 0.0)
        if isinstance(rc, Fn) and rc.slash == "\\":
            s = {}
            if _unify(rc.arg, lc, s):
                made(rc.res, s, "<", left.head if _takes_its_head(rc) else right.head,
                     self._agreement(left, right) if _verb_phrase(rc) and isinstance(lc, Atom) else 0.0)
        # Composition: X/Y Y/Z => X/Z; Y\Z X\Y => X\Z.
        if isinstance(lc, Fn) and lc.slash == "/" and isinstance(rc, Fn) and rc.slash == "/":
            s = {}
            if _unify(lc.arg, rc.res, s):
                # A RAISED SUBJECT AGREES WITH ITS VERB WHERE IT IS COMPOSED WITH IT TOO, before the verb has taken
                # what else it takes, as a subject raised by the rule above does (`>T>B`). Weighed where the subject
                # TAKES its verb and not where it is composed with it, the copula's only unweighed form was the one
                # said: of nobody being intelligent, "Nothing am intelligent." was composed for -0.084 while taking
                # the same verb's whole phrase cost -5.839, and no other form of the copula was ever offered to
                # "nothing" at all (lyric_db, 2026-10-30).
                made(Fn(lc.res, "/", rc.arg), s, ">B", right.head if _takes_its_head(lc) else left.head,
                     self._agreement(left, right) if _raised_subject(lc) and _verb_phrase(rc.res) else 0.0)
            elif isinstance(rc.res, Fn) and rc.res.slash == "/":
                # X/Y (Y/Z)/W => (X/Z)/W: "Did you give him" before what was given.
                s = {}
                if _unify(lc.arg, rc.res.res, s):
                    made(Fn(Fn(lc.res, "/", rc.res.arg), "/", rc.arg), s, ">B2",
                         right.head if _takes_its_head(lc) else left.head)
        if isinstance(lc, Fn) and lc.slash == "\\" and isinstance(rc, Fn) and rc.slash == "\\":
            s = {}
            if _unify(rc.arg, lc.res, s):
                made(Fn(rc.res, "\\", lc.arg), s, "<B", left.head if _takes_its_head(rc) else right.head)
        # Y/Z X\Y => X/Z, only for what modifies a verb's phrase from after it: "was not a student" ("not" taking
        # "was" before its complement), as categorial grammars of English allow it and nothing else.
        if isinstance(lc, Fn) and lc.slash == "/" and isinstance(rc, Fn) and rc.slash == "\\" and right.crossing \
                and _same_shape(rc.res, rc.arg) and _verb_phrase(rc.arg):
            s = {}
            if _unify(rc.arg, lc.res, s):
                made(Fn(rc.res, "/", lc.arg), s, "<Bx", left.head)
        # AN ORDER SAID TO SOMEONE BY NAME is theirs to do: "Close the box, Tom.", "Tom, close the box.".
        tokens = self._tokens
        if _verb_phrase(lc) and lc.res.feat == "b" and isinstance(rc, Atom) and rc.base == "NP" \
                and 0 <= right.start < len(tokens) and tokens[right.start] == ",":
            s = {}
            if _unify(lc.arg, rc, s):
                made(Atom("S", "imp", lc.res.ref), s, "said to", left.head)
        if isinstance(lc, Atom) and lc.base == "NP" and _verb_phrase(rc) and rc.res.feat == "b" \
                and 0 < left.end <= len(tokens) and tokens[left.end - 1] == ",":
            s = {}
            if _unify(rc.arg, lc, s):
                made(Atom("S", "imp", rc.res.ref), s, "said to", right.head)
        # A KIND AND THE NAME OF THE ONE OF IT: "the river Thames", "the function sorted": the thing is the named one.
        # A word written lowercase is a name here as seldom as the word is one (`estimate`, no uses of its own).
        if isinstance(lc, Atom) and lc.base == "N" and right.rule == "lex" and right.end - right.start == 1:
            word = tokens[right.start]
            if isinstance(rc, Atom) and rc.base == "NP" and right.entry in ("NAME", "name") and isinstance(rc.ref, str):
                name, cost = rc.ref, 0.0
            elif word.isalpha() and word[:1].islower() and word.lower() not in self.lexicon.closed \
                    and right.entry != "N" and not isinstance(rc, Atom):
                uses = self.lexicon.words.uses(word)
                name = word.lower()
                cost = estimate(uses, self.lexicon.words.like(word, "uses"), set(uses) | {"NAME"})["NAME"] - right.score
            else:
                name = None
            if name is not None:
                s = {}
                if _bind(lc.ref, name, s):
                    out.append(Sign(Atom("N", lc.feat, name), _substitute(left.pieces, s) + (
                        ("word", name, "NAME", right.start, right.end), ("named", name, right.start)),
                        left.score + right.score + cost, left.start, right.end, "named", (left, right), left.head))
        # A THING AND WHAT IT IS, SAID BETWEEN COMMAS: "Tom, the teacher, is tall.".
        if isinstance(lc, Atom) and lc.base == "NP" and isinstance(rc, Atom) and rc.base == "NP" \
                and 0 <= right.start < right.end <= len(tokens) and tokens[right.start] == "," \
                and tokens[right.end - 1] == "," and right.end - right.start > 2:
            out.append(Sign(lc, left.pieces + right.pieces + (("be", lc.ref, rc.ref, self._new(), right.start),),
                            left.score + right.score, left.start, right.end, "apposition", (left, right), left.head))
        # A measure before a quality is its degree's ("Tom is ten years old.": an oldness measured ten years).
        if isinstance(lc, Atom) and lc.base == "NP" and _verb_phrase(rc) and rc.res.feat == "adj" \
                and any(p[0] == "count" and p[1] == lc.ref for p in left.pieces):
            out.append(Sign(rc, left.pieces + right.pieces + (("measure", rc.res.ref, lc.ref, left.start),),
                            left.score + right.score, left.start, right.end, "measure", (left, right), right.head))
        # A PREPOSITION LEFT WITHOUT ITS THING, its phrase still taking it: "Who did you get these flowers from?"
        # ("get these flowers from" still takes who), "What is a table made of?". (X\Y)/Z after Y => X/Z: the
        # preposition's phrase applied to what it modifies, its own place left open.
        if right.rule == "lex" and right.entry.startswith("prep:") and isinstance(rc, Fn) and rc.slash == "/" \
                and isinstance(rc.res, Fn) and rc.res.slash == "\\" and _same_shape(rc.res.res, rc.res.arg) \
                and not (isinstance(lc, Fn) and lc.slash == "&"):
            s = {}
            if _unify(rc.res.arg, lc, s):
                made(Fn(rc.res.res, "/", rc.arg), s, "<stranded", left.head)
        # A thing raised to what is said of it and composed with a verb still taking what follows: "the money she
        # owed" (she => S/(S\NP), with "owed" => S/NP).
        if isinstance(lc, Atom) and lc.base == "NP" and isinstance(rc, Fn) and rc.slash == "/" \
                and isinstance(rc.res, Fn) and rc.res.slash == "\\" and isinstance(rc.res.arg, Atom) \
                and rc.res.arg.base == "NP" and isinstance(rc.res.res, Atom) and rc.res.res.base == "S":
            s = {}
            if _unify(rc.res.arg, lc, s):
                # Its subject agrees with its verb as when the verb's phrase is whole: "Owl'm birds." was read so,
                # "Owl'm" composed before "birds", and agreement weighed only the other way of reading it.
                made(Fn(rc.res.res, "/", rc.arg), s, ">T>B", right.head, self._agreement(left, right))
        return out

    def _agreement(self, subject: Sign, doing: Sign) -> float:
        """HOW WELL A SUBJECT AGREES WITH ITS VERB, as a logarithm, never more than nothing: of the subjects the
        doing's finite verb took (`Words.subjects`, as the treebanks' subjects took that form), the share of this
        subject's class with its features (`_agreed`); of a verb memory holds no subject of, as every finite verb's
        subjects are (a form no subject was written as, "me", is none). Nothing where memory holds no subject of any
        verb, or the subject is no one word of a class: a noun, a name, a pronoun (`_said_by`).

        Nothing compared a subject with its verb: "a wall am" was read as "a wall is", and the first sentence the
        grammar said of a wall being a partition was "Wall'm the the a partition." (lyric_dev2, 2026-10-27)."""
        words, tokens = self.lexicon.words, self._tokens
        # WHAT THE PLACE ITSELF ASKS OF THE WORD STANDING IN IT, weighed whatever the verb agrees in and so asked
        # first: a verb in the past agrees in nothing, and before this every subject of one scored the same nothing.
        standing = self._standing(subject, "subject")
        hook = _hook(doing.cat)
        finite = [p[-1] for p in doing.pieces if p[0] == "finite" and p[1] == hook]
        if not finite or not 0 <= min(finite) < len(tokens):
            return standing
        if "every" not in self._agreeing:
            self._agreeing["every"] = words.subjects()
        every = self._agreeing["every"]
        ref = _subject_ref(subject.cat)
        found = self._said_by(subject.pieces, ref) if every and ref is not None else None
        if not found:
            return standing
        verb = ("took", str(tokens[min(finite)]))
        if verb not in self._agreeing:
            self._agreeing[verb] = words.subjects(verb[1]) or self._subjects_like(verb[1])
        return standing + self._agreed(self._agreeing[verb], every, *found)

    def _stands_as_written(self, doing: Sign, thing: Sign, taking: Cat, s: Mapping[int, Term]) -> bool:
        """WHETHER A THING STANDING AFTER A VERB IS WRITTEN AS THE PLACE ASKS: a thing said by a pronoun of its own
        sentence ("himself", "ourselves", "myself") says the thing the doing is done BY, so it may stand after the
        verb only where the two are the one thing; a thing said by any other pronoun only where they are not.
        English holds a form for each and nothing told them apart: of the one spoken of before misleading a group
        the speaker is one of, "They misled ourselves." was said, and of the speaker misleading the speaker,
        "I misled i." (lyric_db, 2026-10-30).

        Both things must be known for this to say anything. They are where a meaning is being SAID, a verb's places
        being bound to the meaning's own terms before a word is put in (`Grammar.say`'s `roles_bound`), and they
        never are where a sentence is being READ, the subject not yet taken and each place still a variable -- so
        reading is left as permissive as it was, binding a pronoun of its own sentence to what stands before it
        (`spell_out`) rather than being told here which places it may stand in."""
        if not isinstance(thing.cat, Atom) or thing.cat.base != "NP":
            return True
        ref = _subject_ref(thing.cat)
        stands = _walk(ref, s) if ref is not None else None
        # THE THING THE DOING IS DONE BY, AS THE DOING'S OWN PLACES HOLD IT: a verb carries a piece for each place
        # it has and what fills it (`Grammar.say`'s `roles_bound` binds them to the meaning's terms), and those
        # outlive the category, which loses the subject the moment a raised subject is composed with the verb.
        hook = _hook(doing.cat)
        subject = next((_walk(p[2], s) for p in doing.pieces
                        if p[0] == "role" and p[1] == hook and len(p) > 3 and p[3] == "subject"), None)
        if subject is None:
            rest = _apply(taking, s)
            subject = rest.arg.ref if _verb_phrase(rest) and isinstance(rest.arg, Atom) else None
        if not isinstance(subject, str) or not isinstance(stands, str):
            return True
        if any(p[0] == "pron" and len(p) > 3 and p[3] == "own" and p[1] == ref for p in thing.pieces):
            return subject == stands
        if subject != stands:
            return True
        # A thing said by a word of its own and not by a pronoun has no form saying it is the subject again, so it
        # stands here as it is: "Tom misled Tom." is all there is to say of Tom misleading Tom.
        found = self._said_by(thing.pieces, ref)
        return found is None or found[0] != "PRONOUN"

    def _object_agreement(self, doing: Sign, thing: Sign) -> float:
        """HOW WELL A THING STANDING AFTER A VERB IS WRITTEN FOR THE PLACE IT STANDS IN, as a logarithm, never more
        than nothing: of the things that verb took as its object (`Words.objects`, as the treebanks' objects stood
        after that form), the share of this thing's class with its features, weighed exactly as a subject is
        weighed against its verb (`_agreed`); of a verb memory holds no object of, as every verb's objects are.
        Nothing where memory holds no object of any verb, or the thing is no one word of a class (`_said_by`).

        Nothing weighed a thing standing after a verb at all: memory counted the subjects verbs took, the nouns
        determiners were said with and the things a copula said something to be, and nothing counted what stood as
        an object, so "They misled me." was said back as "They misled i." and "I misled them." as "I misled this."
        (lyric_db, 2026-10-30)."""
        words, tokens = self.lexicon.words, self._tokens
        if "every object" not in self._agreeing:
            self._agreeing["every object"] = words.objects()
        every = self._agreeing["every object"]
        if not every or not 0 <= doing.head < len(tokens):
            return 0.0
        ref = _subject_ref(thing.cat)
        found = self._said_by(thing.pieces, ref) if ref is not None else None
        if not found:
            return 0.0
        verb = ("object of", str(tokens[doing.head]))
        if verb not in self._agreeing:
            # WHAT STOOD AFTER THIS VERB, COUNTED TOGETHER WITH WHAT STOOD AFTER EVERY VERB, never the verb's own
            # alone: `_agreed` gives a form no evidence names a flat penalty, so weighing by a verb's own handful
            # would throw away the only thing that tells a case apart -- "them" and "they" both scored -3.71 after
            # "misled", which memory holds 40 objects of and none of them plural. The case a place takes belongs to
            # the place and not to the verb standing before it, and a verb's own objects can then only tell its own
            # preferences more sharply.
            held: Counter = Counter(every)
            held.update(words.objects(verb[1]))
            self._agreeing[verb] = held
        return self._agreed(self._agreeing[verb], every, *found)

    def _shared_features(self) -> Set[str]:
        """THE FEATURES A SUBJECT AND A VERB SHARE and a subject is marked by (number, person, case), as what memory
        holds of the subjects verbs took says them (`Words.subjects`): nothing else a form is written with is weighed
        for agreement, a tense or a mood saying nothing of what may stand before it."""
        if "shared" not in self._agreeing:
            self._agreeing["shared"] = {f.split("=")[0] for _, features in self.lexicon.words.subjects()
                                        for f in features.split("|") if f}
        return self._agreeing["shared"]

    def _marking_features(self) -> Set[str]:
        """THE FEATURES THAT MARK WHERE A THING MAY STAND rather than what its verb agrees in (its case), as what
        memory holds says them: of the features a subject is written with (`_shared_features`), those no form of a
        finite verb memory holds a subject of is ever written with. A verb is written with a number and a person and
        agrees in them; it is never written with a case, so what is left of a subject's features marks the place.

        They have to be weighed apart because an English verb in the past agrees in NOTHING -- "misled" is
        `Tense=Past|VerbForm=Fin` and says no number and no person -- so `_agreement` has nothing to weigh and
        returned the same nothing for every subject, and the subject's CASE went unweighed with it:
        "We misled them." was said back as "Ourselves misled this." (lyric_db, 2026-10-30). Nothing where memory
        holds no form of any such verb, there being nothing to tell the two apart by."""
        if "marking" not in self._agreeing:
            words, on_verbs = self.lexicon.words, set()
            for word in words.took_subjects():
                for cls in ("VERB", "AUXILIARY"):
                    for features in words.form_features(word, cls):
                        on_verbs |= {f.split("=")[0] for f in features.split("|") if f}
            self._agreeing["marking"] = (self._shared_features() - on_verbs) if on_verbs else set()
        return self._agreeing["marking"]

    def _placed(self, held: Mapping[Tuple[str, str], float]) -> Counter:
        """What stood somewhere, counted by the features that mark the place alone (`_marking_features`): the
        subjects memory holds as `("PRONOUN", "Case=Nom")` and `("NOUN", "")`, a noun being written with no case."""
        marking, out = self._marking_features(), Counter()
        for (cls, features), n in held.items():
            out[(cls, "|".join(f for f in features.split("|") if f and f.split("=")[0] in marking))] += n
        return out

    def _places(self) -> Mapping[Tuple[str, str], float]:
        """EVERYTHING THAT STOOD IN ANY PLACE A THING MAY STAND, by the features that mark the place: the subjects
        verbs took and the things they took as objects, together. This is what one place's share is weighed against,
        and it has to be every place rather than the place itself: a share weighed against itself tells nothing
        apart, and `ourselves`, accusative and 3 of main's 11,295 subjects, came out at -0.15 against `we` when it
        was (lyric_db, 2026-10-30)."""
        if "places" not in self._agreeing:
            words = self.lexicon.words
            held = self._placed(words.subjects())
            held.update(self._placed(words.objects()))
            self._agreeing["places"] = held
        return self._agreeing["places"]

    def _standing(self, thing: Sign, place: str) -> float:
        """HOW WELL A THING IS WRITTEN FOR THE PLACE IT STANDS IN, as a logarithm, never more than nothing: of what
        stood in this place, the share of this thing's class with its case, against that share of everything that
        stood in any place (`_places`, `_agreed`). Nothing where memory holds nothing of the other place, a place's
        share then being weighed against itself, or where the thing is no one word of a class (`_said_by`)."""
        marking = self._marking_features()
        ref = _subject_ref(thing.cat)
        found = self._said_by(thing.pieces, ref) if marking and ref is not None else None
        if not found:
            return 0.0
        key = ("standing", place)
        if key not in self._agreeing:
            words = self.lexicon.words
            self._agreeing[key] = self._placed(words.subjects() if place == "subject" else words.objects())
        return self._agreed(self._agreeing[key], self._places(), *found, names=marking)

    def _agrees_as(self, word: str) -> str:
        """WHAT A FINITE VERB'S FORM SAYS OF ITS SUBJECT: the number and person memory holds this word written with
        most, by the features subjects share with verbs ("am" `Number=Sing|Person=1|VerbForm=Fin`, "is" the same of
        a third person); nothing where memory holds no form of it as a verb.

        Asked in three places and so held in one: a finite verb still taking its subject is kept apart by it until
        the subject is taken (`Grammar.say`), a form this decides is not chosen by how often it is written, and a
        verb memory holds no subject of is weighed by what the verbs written as it is took (`_subjects_like`). Of a
        word memory holds no form of at all, what the verbs ending as it does say (`_written_like`)."""
        words = self.lexicon.words
        held = self._agreeing.setdefault("agrees as", {})
        if word not in held:
            shared = self._shared_features()
            written: Counter = Counter()
            for cls in ("VERB", "AUXILIARY"):
                for features, n in words.form_features(word, cls).items():
                    written["|".join(f for f in features.split("|") if f and f.split("=")[0] in shared)] += n
            # A form saying nothing of these features is no evidence of having none, as of a thing's case
            # (`Grammar._features`): a verb held once with its person and once without would otherwise be kept
            # apart by whichever the tie fell to.
            if any(f for f in written):
                written.pop("", None)
            held[word] = max(sorted(written), key=lambda f: written[f]) if written else self._written_like(word)
        return held[word]

    def _written_like(self, word: str) -> str:
        """WHAT A VERB MEMORY HOLDS NO FORM OF SAYS OF ITS SUBJECT, by what the verbs ending as it does say: of the
        forms memory holds as verbs, those whose last letters are this word's, the form they are written as most.
        Nothing where memory holds no verb ending so, and nothing for a word too short to end like anything.

        A word nobody taught is still read as a verb by the ending it is written with, and then nothing could be
        weighed against it: `sparkles` is held as no form at all, so it said what number its subject was not, and of
        a thing sparkling "They sparkles." was said above "He sparkles." (lyric_db, 2026-10-30). The endings are the
        word's own last letters rather than a list of English endings here, as every other thing the grammar knows
        about a word's shape is counted and not stated."""
        words = self.lexicon.words
        like = self._agreeing.setdefault("written like", {})
        if not like:
            for other in words.took_subjects():
                says = self._agrees_as(other)
                if not says:
                    continue
                for cut in (1, 2, 3):
                    if len(other) > cut:
                        like.setdefault(other[-cut:], Counter())[says] += 1
        # The longest ending memory holds any verb with, so "-les" is preferred to "-es" and "-es" to "-s".
        for cut in (3, 2, 1):
            held = like.get(word[-cut:]) if len(word) > cut else None
            if held:
                return max(sorted(held), key=lambda f: held[f])
        return ""

    def _subjects_like(self, word: str) -> Mapping[Tuple[str, str], float]:
        """THE SUBJECTS EVERY FINITE FORM WRITTEN AS THIS ONE IS TOOK, gathered together (`_agrees_as`: "stinks" by
        every other third person singular), to weigh a subject against a verb memory holds no subject of. Nothing
        where memory holds no form of the word as a verb, or no verb written as it is ever took a subject.

        A VERB NO SUBJECT WAS EVER HELD OF TOOK EVERY SUBJECT AS WELL AS ANY OTHER COULD: with nothing of its own to
        weigh, a subject's share of this verb's subjects came out as its share of all subjects, whatever it was, and
        so agreed perfectly -- the same nothing again for no evidence as for agreeing (`_agreed`). Of a person
        reeking, "The people stinks." was said above "The person stinks.", memory holding a subject of 19 finite
        forms and "stinks" not among them (lyric_db, 2026-10-30). What a form says of its subject is held of the
        form and not of the word, so the verbs written as it is are what is left to weigh it by."""
        of = self._agrees_as(word)
        if "like" not in self._agreeing:
            words, like = self.lexicon.words, defaultdict(Counter)
            for other in words.took_subjects():
                like[self._agrees_as(other)].update(words.subjects(other))
            self._agreeing["like"] = like
        return self._agreeing["like"].get(of, {}) if of else {}

    def _said_by(self, pieces: Sequence[Piece], ref: Term) -> Optional[Tuple[str, int]]:
        """The one word saying a thing among these pieces, its class and where it stands: a noun (its last word), a
        name, a pronoun (a grammar word standing for the speaker or the hearer, "I", "me", "you", among them, or the
        one grammar word a thing is said by and nothing else); None where none or more than one. Without those,
        nothing weighed "me" as a subject, and "Me loves the moon." was said of the speaker loving it (lyric_dev2,
        2026-10-28).

        A pronoun standing for a group the speaker is one of ("we", "us", "ourselves") says no term of the situation
        but a thing of its own that the speaker is a member of, so none of the three was ever found and none was ever
        weighed against a verb or kept apart from the others by its case: of the speaker and another being
        intelligent, "Ourselves is intelligent." was all that was said (lyric_db, 2026-10-30)."""
        said = [p for p in pieces if p[0] == "word"]
        at = {p[-1] for p in pieces if p[0] == "kind" and p[1] == ref}
        found = [(p[2], p[4] - 1) for p in said if p[3] in at and p[2] == "NOUN"] or \
            [(p[2], p[3]) for p in said if p[2] == "NAME" and p[1] == ref] or \
            [("PRONOUN", p[-1]) for p in pieces if p[0] == "pron" and p[1] == ref] or \
            [("PRONOUN", p[3]) for p in said if p[2] == "GRAMMAR" and p[4] - p[3] == 1
             and (ref in ("?speaker", "?listener") or len(said) == 1)]
        if len(found) != 1 or not 0 <= found[0][1] < len(self._tokens):
            return None
        return found[0]

    def _features(self, cls: str, k: int, names: Optional[Set[str]] = None) -> Counter:
        """What form the word at `k` is as a word of the class, as the forms memory holds say, by the features
        subjects share with verbs and mark a subject by (number, person, case): "walls" `Number=Plur`, "me"
        `Case=Acc|Number=Sing|Person=1`; each with how often the word is that form. None where memory holds none.
        `names`: the features to keep, where only some of them are being weighed -- the case alone, where what is
        weighed is the place a thing stands in and not what its verb agrees in (`_standing`)."""
        shared = self._shared_features() if names is None else names
        if (cls, k, tuple(sorted(shared))) in self._agreeing:
            return self._agreeing[(cls, k, tuple(sorted(shared)))]
        out: Counter = Counter()
        for features, n in self.lexicon.words.form_features(str(self._tokens[k]), cls).items():
            out["|".join(f for f in features.split("|") if f and f.split("=")[0] in shared)] += n
        # A FORM SAYING NOTHING OF THESE FEATURES IS NO EVIDENCE OF HAVING NONE. Where any form of the word as this
        # class says what number, person or case it is, the forms that say nothing are dropped rather than weighed
        # beside them. "I" is held twice -- stated `Case=Nom|Number=Sing|Person=1`, and again under the base a
        # sentence recorded whole gives it (the PMB lemmatises "I" as `speaker`) with no features at all -- once
        # each, and `standing_as` takes the case the word is written with most, which that tie settled on no case at
        # all. Every pronoun was then packed with every other and the surest form alone said: "I is intelligent.",
        # "Him is intelligent.", "Ourselves is intelligent.", while "You are intelligent." -- the one pronoun with
        # no case to get wrong -- came out right (lyric_db, 2026-10-30).
        if any(f for f in out):
            out.pop("", None)
        self._agreeing[(cls, k, tuple(sorted(shared)))] = out
        return out

    def _agreed(self, took: Mapping[Tuple[str, str], float], every: Mapping[Tuple[str, str], float],
                cls: str, k: int, names: Optional[Set[str]] = None) -> float:
        """HOW WELL A WORD AGREES WITH WHAT IT IS SAID WITH, as a logarithm, never more than nothing: of the words
        that other took (`took`: a finite verb's subjects, a determiner's nouns), the share of this word's class with
        each of its forms' features (`_features`), against that share of what every such word took (`every`), with
        one more spread as that share is; the forms weighed by how often the word is each. Nothing where memory holds
        no subject of any such word at all, there being nothing to weigh against.

        Its forms weighed alike, "me", written `Case=Nom` 6 times in 942 ("Me and him went"), agreed with "love" as
        "I" does, and "Me love the moon." was said of the speaker loving the moon (lyric_dev2, 2026-10-28)."""
        forms = self._features(cls, k, names)
        total, seen = sum(every.values()), sum(took.values())
        if not total:
            return 0.0

        def matched(held: Mapping[Tuple[str, str], float], features: Optional[str]) -> float:
            return sum(n for (c, f), n in held.items() if c == cls and (features is None or f == features))
        weights: Dict[Optional[str], float] = {f: (n if sum(forms.values()) > 0 else 1.0) for f, n in forms.items()} \
            if forms else {None: 1.0}
        agrees = 0.0
        for features, w in weights.items():
            # A FORM NO SUBJECT WAS EVER WRITTEN WITH IS EVIDENCE AGAINST, NOT NO EVIDENCE: the share is smoothed as
            # the rest of saying smooths a share (`share_of`, `said_for`), so that a case no subject ever had is
            # still a share to be weighed against rather than being passed over. Passed over, "him", "them" and
            # "us" -- every accusative pronoun, which not one of the 11,295 subjects memory holds ever was -- agreed
            # with every verb as well as it is possible to agree, a word no form of which was ever a subject coming
            # back the same nothing as a word with no verb to weigh it against. "Him is intelligent." was said of a
            # man being intelligent, above "He is intelligent." (lyric_db, 2026-10-30).
            share = (matched(every, features) + 0.5) / (total + 0.5 * (len(every) + 1))
            agrees += w * (matched(took, features) + share) / (seen + 1.0) / share
        return min(0.0, math.log(agrees / sum(weights.values())))

    def _met(self, left: Sign, right: Sign, s: Dict[int, Term], rule: str) -> float:
        """AGREEMENT WEIGHED WHERE ITS TWO WORDS FIRST STAND TOGETHER, by whichever rule joins them, as a subject with
        its verb (`_agreement`), from what the treebanks' words agreeing so took: a determiner with its noun ("a"
        before a noun, `Words.nouns`), and a thing with what it is said to be (`be`: "Walls are a partition.",
        `Words.predicated`, of what the copula said a thing to be by its class and features).

        Neither was weighed: "a" before "representations" was read as surely as before "representation", and
        "Pictures are a representations." was said of a picture being a representation (lyric_dev2, 2026-10-28)."""
        words, tokens = self.lexicon.words, self._tokens
        weight = 0.0
        # A determiner whose noun is still to come (its category still takes the noun) meets it here or later; one
        # whose noun it already holds was weighed when they met.
        dets = [(side, p) for side in (left, right) for p in side.pieces
                if p[0] == "det" and _takes_noun(side.cat, p[1]) and 0 <= p[2] < len(tokens)]
        dets = [(side, p, took) for side, p in dets for took in [words.nouns(str(tokens[p[2]]))] if took]
        bes = [(side, p) for side in (left, right) for p in side.pieces if p[0] == "be"]
        every_predicated = words.predicated() if bes else {}
        if not dets and not every_predicated:
            return weight
        sides = {id(left): (_substitute(left.pieces, s), _substitute(right.pieces, s)),
                 id(right): (_substitute(right.pieces, s), _substitute(left.pieces, s))}
        if dets:
            every_noun = words.nouns()
            for side, p, took in dets:
                noun = self._said_by(sides[id(side)][1], _walk(p[1], s))
                if noun is not None:
                    weight += self._agreed(took, every_noun, *noun)
        for side, p in (bes if every_predicated else ()):
            one, other = sides[id(side)]
            x, y = _walk(p[1], s), _walk(p[2], s)
            for a, b in ((one, other), (other, one)):
                thing, what = self._said_by(a, x), self._said_by(b, y)
                if thing is None or what is None or self._said_by(b, x) or self._said_by(a, y):
                    continue
                took: Counter = Counter()
                for features in self._features(what[0], what[1]):
                    took.update(words.predicated((what[0], features)))
                if took:
                    weight += self._agreed(took, every_predicated, *thing)
        return weight

    def _coordinate(self, left: Sign, right: Sign) -> Optional[Sign]:
        """Two read alike joined: two things are a group of both ("Ken and Yumi"), two of anything else are both
        said ("sang and danced"), their places one ("Tom sang and danced": Tom did both)."""
        lc, joined = left.cat, right.cat.arg
        if not _same_shape(lc, joined):
            return None
        word = next((p[1] for p in right.pieces if p[0] == "and"), "and")
        pieces = tuple(p for p in right.pieces if p[0] != "and")
        if isinstance(lc, Atom) and lc.base in ("NP", "N"):
            s: Dict[int, Term] = {}
            if not _bind(lc.feat, joined.feat, s):
                return None
            group = self._new()
            members = (("member", group, lc.ref, left.start), ("member", group, joined.ref, right.start),
                       ("group", group, word, right.start))
            return Sign(Atom(lc.base, _walk(lc.feat, s), group), _substitute(left.pieces + pieces, s) + members,
                        left.score + right.score, left.start, right.end, "&", (left, right), left.head)
        # Of anything else the places are one, what each makes its own.
        s = {}

        def places(a: Cat, b: Cat) -> bool:
            if isinstance(a, Atom):
                return _bind(a.feat, b.feat, s)
            return places(a.res, b.res) and _unify(a.arg, b.arg, s)
        if not places(lc, joined):
            return None
        extra = (("either", _hook(lc), _hook(joined), left.start),
                 ("alternatives", left.start, left.end, right.start, right.end, left.start)) if word == "or" else ()
        extra += (("both", _hook(lc), _hook(joined), left.start),)
        return Sign(_apply(lc, s), _substitute(left.pieces + pieces, s) + _substitute(extra, s),
                    left.score + right.score, left.start, right.end, "&", (left, right), left.head)

    def _said_of_a_doing(self, sign: Sign) -> List[Sign]:
        """A THING SAID OF A DOING WITH NO PREPOSITION BEFORE IT tells of the doing as a preposition's thing does ("One
        morning the dog ran to the park.", "We met last week."), after it or opening the sentence, as often as the
        word naming the thing is said so: its kind's word ("that morning": morning), else the word heading it ("Monday").
        Only a word ever said so, or held a time. What it says of the doing is learned as a preposition's link is,
        under no word (`spell_out`). With no way to read it, "One morning the dog ran to the park." was read as a
        morning the dog ran to, and the park done by it."""
        c = sign.cat
        at = next((p[-1] for p in sign.pieces if p[0] == "kind" and p[1] == c.ref), sign.head)
        if not 0 <= at < len(self._tokens):
            return []
        word = self._tokens[at]
        said = self.lexicon.words.bare_modifier(word)
        if not said.get("modifier") and not self.lexicon.time_of(word):
            return []
        cost = estimate(said, self.lexicon.words.like(word, "bare"), ("modifier", "otherwise"))["modifier"]
        e, z, f = self._new(), self._new(), self._new()
        s = Atom("S", f, e)
        vp = Fn(s, "\\", Atom("NP", None, z))
        told = sign.pieces + (("prep", e, c.ref, "", "-", sign.start),)
        return [Sign(Fn(vp, "\\", vp), told, sign.score + cost, sign.start, sign.end, "NP=>adjunct", (sign,),
                     sign.head),
                Sign(Fn(s, "/", s), told, sign.score + cost, sign.start, sign.end, "NP=>opening", (sign,),
                     sign.head)]

    def _unary(self, sign: Sign) -> List[Sign]:
        """What a stretch read one way may also be read as, as often as it is said so: a kind said bare is a thing
        ("Farmers rebelled"); a doing is a thing ("Forming a cabinet is difficult"), as often as its word says a
        doing standing as a thing; a doing after a thing tells of it ("a book written by Tom"), as often as its
        word is said so; a clause still taking a thing tells of the thing before it ("the money she owed him"), as
        often as such a clause is said without "that"."""
        out: List[Sign] = []
        c = sign.cat
        if isinstance(c, Atom) and c.base == "N" and 0 <= sign.head < len(self._tokens):
            # A kind said with nothing saying which is a thing ("Farmers rebelled", "I like water"), as often as the
            # noun is said so: a singular count noun seldom is ("The phone is ringing" is no phone that is a
            # ringing).
            word = self._tokens[sign.head]
            cost = estimate(self.lexicon.words.noun_alone(word), self.lexicon.words.like(word, "alone"),
                            ("bare", "determined"))["bare"]
            bare = Sign(Atom("NP", None, c.ref), sign.pieces + (("bare", c.ref, sign.head),),
                        sign.score + cost, sign.start, sign.end, "N=>NP", (sign,), sign.head)
            out.append(bare)
            # A thing said bare may tell of a doing too ("Last year the company hired three engineers.").
            out.extend(self._said_of_a_doing(bare))
        if isinstance(c, Atom) and c.base == "NP":
            out.extend(self._said_of_a_doing(sign))
        if _verb_phrase(c) and c.res.feat == "adj" and sign.end - sign.start > 1:
            # A quality said with what it is compared to or of, after a thing, is the thing's ("a natural number
            # greater than 1", "a man proud of his son"), as often as an adjective's phrase is said after a thing:
            # one with words after the adjective ("greater than 2") as often as such a phrase is, which is seldom
            # before a thing; counted with every adjective, it was rarer than "greater" as a name, and "Every prime
            # number greater than 2 is odd." told of a thing called "greater".
            after, before = self.lexicon.words.adjectives_after(followed=sign.head < sign.end - 1)
            cost = estimate({"after": after, "before": before}, {}, ("after", "before"))["after"]
            x = c.arg.ref
            out.append(Sign(Fn(Atom("N", None, x), "\\", Atom("N", None, x)), sign.pieces, sign.score + cost,
                            sign.start, sign.end, "adj=>N\\N", (sign,), sign.head))
        if _verb_phrase(c) and c.res.feat == "adj" and 0 <= sign.head < len(self._tokens):
            # A quality said before a thing is the thing's ("a very generous offer"), as often as the adjective is
            # said before a thing.
            word = self._tokens[sign.head]
            uses = self.lexicon.words.uses(word)
            cost = estimate(uses, self.lexicon.words.like(word, "uses"), ("ADJECTIVE:before", "ADJECTIVE"))[
                "ADJECTIVE:before"]
            x = c.arg.ref
            out.append(Sign(Fn(Atom("N", None, x), "/", Atom("N", None, x)), sign.pieces, sign.score + cost,
                            sign.start, sign.end, "adj=>N/N", (sign,), sign.head))
        if isinstance(c, Fn) and c.slash == "\\" and isinstance(c.res, Atom) and c.res.base == "S" \
                and isinstance(c.arg, Atom) and c.arg.base == "NP" and 0 <= sign.head < len(self._tokens):
            word = self._tokens[sign.head]
            shapes = estimate(self.lexicon.words.verb_shapes(word), self.lexicon.words.like(word, "shapes"),
                              ("thing", "after", "before", "doing"))
            if c.res.feat in ("pss", "ng", "pt") and sign.end - sign.start == 1:
                # A doing said before a thing tells of it ("a failed login": a login that failed; "a broken
                # window"; "a running man").
                x = c.arg.ref
                out.append(Sign(Fn(Atom("N", None, x), "/", Atom("N", None, x)), sign.pieces,
                                sign.score + shapes["before"], sign.start, sign.end, "VP=>N/N", (sign,), sign.head))
            if c.res.feat == "ng":
                cost = shapes["thing"]
                out.append(Sign(Atom("NP", None, c.res.ref), sign.pieces, sign.score + cost, sign.start, sign.end,
                                "ng=>NP", (sign,), sign.head))
            if c.res.feat in ("ng", "pss"):
                cost = shapes["after"]
                x = c.arg.ref
                out.append(Sign(Fn(Atom("N", None, x), "\\", Atom("N", None, x)), sign.pieces, sign.score + cost,
                                sign.start, sign.end, "VP=>N\\N", (sign,), sign.head))
        if _verb_phrase(c) and c.res.feat == "to":
            # "Rex ran to catch the ball.": what the running was for, as often as a "to" clause says so; what it
            # says is not told as done.
            purpose, taken = self.lexicon.words.to_purposes()
            cost = estimate({"for": purpose, "taken": taken}, {}, ("for", "taken"))["for"]
            e, x = self._new(), c.arg.ref
            vp = Fn(Atom("S", self._new(), e), "\\", Atom("NP", None, x))
            out.append(Sign(Fn(vp, "\\", vp), sign.pieces + (("purpose", e, c.res.ref, sign.start),
                                                            ("untold", sign.start, sign.end, sign.start)),
                            sign.score + cost, sign.start, sign.end, "to=>purpose", (sign,), sign.head))
        if isinstance(c, Fn) and c.slash == "/" and isinstance(c.res, Atom) and c.res.base == "S" \
                and c.res.feat == "dcl" and isinstance(c.arg, Atom) and c.arg.base == "NP":
            bare, marked = self.lexicon.words.bare_relatives()
            cost = estimate({"bare": bare, "marked": marked}, {}, ("bare", "marked"))["bare"]
            x = c.arg.ref
            out.append(Sign(Fn(Atom("N", None, x), "\\", Atom("N", None, x)), sign.pieces, sign.score + cost,
                            sign.start, sign.end, "S/NP=>N\\N", (sign,), sign.head))
        return out

    def chart(self, tokens: Sequence[str]) -> Dict[Tuple[int, int], Dict[str, Sign]]:
        """Every reading of every stretch the grammar allows, one of each category, the surest."""
        n = len(tokens)
        self._tokens = tuple(tokens)
        self._weighed, self._marking, self._asking, self._agreeing = None, frozenset(), frozenset(), {}
        if self.structure is not None and len(self.structure) and n:
            classes, self._weighed = self.structure.joins(tuple(str(t) for t in tokens))
            self._marking = frozenset(i for i, c in enumerate(classes) if c in MARKING)
            self._asking = frozenset(i for i, c in enumerate(classes) if c in ("PRONOUN", "ADVERB"))
        cells: Dict[Tuple[int, int], Dict[str, Sign]] = defaultdict(dict)

        def keep(sign: Sign) -> bool:
            if sign.word < 0:
                self._joined(sign)
            k = _key(sign.cat)
            cell = cells[(sign.start, sign.end)]
            held = cell.get(k)
            if held is None or sign.score > held.score + 1e-9:
                if sign.binding is not None:
                    # WHAT A COMBINATION MEANS IS MADE ONLY FOR ONE KEPT: its parts' pieces, all of them, with the
                    # variables bound. Made for every combination, most of them never kept, it was the half of a
                    # paragraph's grammar it took (34 million pieces bound reading Wikipedia's Photosynthesis lead,
                    # lyric_dev, 2026-10-23).
                    left, right = sign.kids
                    sign.pieces = _substitute(left.pieces + right.pieces, sign.binding)
                    sign.binding = None
                cell[k] = sign
                return True
            return False
        apart = {k for start, end, joined in self.lexicon.hyphened(tokens) if joined is None
                 for k in range(start + 1, end, 2)}
        for i, t in enumerate(tokens):
            if not any(ch.isalnum() for ch in t) and t not in ("'s", "'") and (not isinstance(t, Joining) or i in apart):
                # A hyphen joining two words is no mark between them: read only with the words it joins where memory
                # holds them as one word ("high-level", never "high" and "level": "a high-level, general-purpose
                # programming language" was two things); where it holds none, they are read as written apart
                # ("a novel-based film", `Lexicon.hyphened`).
                keep(Sign(Atom("punct", t, None), (), 0.0, i, i + 1, "lex", (), i, "punct"))
            for end, entry in self.lexicon.entries(tokens, i):
                try:
                    sign = self._lexical(tokens, i, end, entry)
                except (ValueError, IndexError):
                    continue
                if keep(sign):
                    for u in self._unary(sign):
                        keep(u)
        for length in range(2, n + 1):
            for start in range(0, n - length + 1):
                end = start + length
                made: List[Sign] = []
                for mid in range(start + 1, end):
                    lefts, rights = cells.get((start, mid)), cells.get((mid, end))
                    if not lefts or not rights:
                        continue
                    for left in list(lefts.values()):
                        for right in list(rights.values()):
                            made.extend(self._combine(left, right))
                for sign in made:
                    if keep(sign):
                        for u in self._unary(sign):
                            keep(u)
        return cells

    def _joined(self, sign: Sign) -> None:
        """The word a stretch is about (`Sign.word`), and of two stretches combined, how likely the structure view
        makes the one joined to the other (`_weighed`, as `StructureView.joins` weighs it for its own tree), added to
        how surely it is read. Each stretch is weighed by the word it is about, as the treebanks the view learned from
        join words: the phrase's head, but where that word only marks what it takes (a preposition, a determiner, an
        auxiliary or "is", "that", "and": `_marking`), what it takes ("in the park": park, the park joined to what it
        tells of, "in" to the park); a pronoun or an adverb taking a doing, the doing ("Who stabbed Tom?": stabbed);
        and a modifier composed before what it tells of is joined with it ("can reproduce": reproduce).

        WHICH WORD TAKES WHICH WAS DECIDED BY THE ORDER THE CHART BUILT. Counted by its words' readings alone, two
        readings joining the same words otherwise scored the same, and the chart kept the first it built: of the joins
        in the readings chosen of 20 sentences of published prose, 146 of 221 were so chosen over another joining them
        otherwise ("pay the penalty within 30 days": the paying within 30 days, or the penalty). The readings chosen
        joined 49.2% of the content words of 200 sentences of UD English PUD (news and Wikipedia, held out of all Lyric
        learned) as the analysis by hand does, where the structure view, learned from EWT's training part, joins
        72.5%. With its likelihoods added: 60.6% (52.2% where they only chose between readings read as surely, 58.9%
        and 60.8% at half and twice the weight; lyric_dev, 2026-10-26). The PMB's checked derivations' own joins,
        counted (8,679 short sentences), chose worse than the order built: 47.8%, and 40.8% added."""
        kids = sign.kids
        if not kids:
            sign.word = sign.head
            return
        if len(kids) == 1:
            sign.word = kids[0].word if kids[0].word >= 0 else kids[0].head
            return
        left, right = kids[0], kids[-1]
        head, joined = (right, left) if right.head == sign.head and left.head != sign.head else (left, right)
        if head.head in self._marking or (sign.rule in (">B", "<B", ">B2", "<Bx") and isinstance(head.cat, Fn)
                                          and _same_shape(head.cat.res, head.cat.arg)) or (
                head.head in self._asking and isinstance(head.cat, Fn) and _clausal(head.cat.arg)):
            # A pronoun or an adverb taking a doing is joined to it, as the treebanks join them: "who" to "stabbed"
            # in "Who stabbed Tom?", "nothing" to "saw". Joined the other way, the structure view rightly made the
            # joins unlikely, and "who" was read a thing and not what is asked (GRAMMAR-01 dev, 2026-10-26).
            head, joined = joined, head
        at = head.word if head.word >= 0 else head.head
        sign.word = at
        of = joined.word if joined.word >= 0 else joined.head
        weighed, tokens = self._weighed, self._tokens
        several = not joined.kids and joined.end - joined.start > 1 and any(
            p[0] == "word" and p[2] == "GRAMMAR" for p in joined.pieces)
        if weighed is None or not (0 <= at < len(tokens) and 0 <= of < len(tokens)) or at == of \
                or not any(ch.isalnum() for ch in str(tokens[of])) or of in self._marking or several:
            # A word that only marks another is joined as the grammar joins it: "did" takes its doer first in "Where
            # did Gandhi study?", the treebanks join it to "study", and the join the structure view made unlikely
            # (-6.2) decided the question was what Gandhi studied (GRAMMAR-01 dev, 2026-10-26). So is a grammar word
            # of several words ("kind of", "no one"), which no treebank reads as one: "kind", to them the head of
            # "kind of flowers", weighed as joined to "flowers", and "What kind of flowers" asked a kind and a flower
            # (2026-10-29).
            return
        sign.score += float(weighed[at + 1, of + 1])

    # ── reading a sentence ──
    def read(self, tokens: Sequence[str]) -> Reading:
        tokens = tuple(tokens)
        if not tokens:
            return Reading(tokens, None, None, "no words")
        # WHAT OF THIS SENTENCE MEMORY DOES NOT HOLD, worked out whether it reads or not: a sentence may fail to read
        # BECAUSE of a word nobody taught, and that was the one thing a reading never said either way.
        unheld = words_not_held(tokens, self.lexicon)
        cells = self.chart(tokens)
        whole = [s for s in cells.get((0, len(tokens)), {}).values() if _whole(s.cat) is not None]
        if not whole:
            covered = sorted(((e - s, s, e) for (s, e), cell in cells.items() if cell
                              and any(not (isinstance(x.cat, Atom) and x.cat.base == "punct") for x in cell.values())),
                             reverse=True)
            return Reading(tokens, None, None,
                           "the grammar reads no whole" + (f"; no word held for {', '.join(unheld)}" if unheld else ""),
                           tuple((s, e) for _, s, e in covered[:3]), unheld=unheld)
        # A sentence is read as one wherever the grammar reads it so; as a phrase alone ("What a feast!") only
        # where it does not; as an order as often as what is said is one (`_said_so`).
        best = max(whole, key=lambda s: (_rank(s.cat) == 2, s.score + self._said_so(s.cat), _rank(s.cat)))
        reading = Reading(tokens, best, None, unheld=unheld)
        # HOW SURE: the reading's share of every reading of the whole, by how surely each reads its words.
        top = max(s.score for s in whole)
        reading.sure = math.exp(best.score - top) / sum(math.exp(s.score - top) for s in whole)
        try:
            reading.meaning = self._spell_out(best, tokens, reading)
        except ValueError as error:
            reading.why = str(error)
        return reading

    # ── saying a meaning ──
    def say(self, meaning: Meaning, named: Optional[Mapping[str, str]] = None,
            why: Optional[Dict[str, Any]] = None,
            how_surely: Optional[Dict[str, float]] = None) -> List[str]:
        """EVERY SENTENCE THIS GRAMMAR SAYS A MEANING WITH, the surest read first: the grammar a sentence is read by,
        used the other way (one grammar for reading and saying, Shieber 1988; chart generation, Kay 1996). The words
        for its things (`Words.words_for`: memory's words for each, every form held), and the grammar's own words whose
        pieces say what it holds (`_says_of`), as often as it holds it, a word saying nothing as often as what it takes
        is made ("a", making a thing of a kind); combined by the rules reading combines by (`_combine`, `_unary`), in
        any order, each word for a thing once; each sentence made READ BACK (`read`), and said only where it reads to
        exactly this meaning. The speaker's own word for a thing (`named`) before another. Empty where nothing the
        grammar holds says it: then it is not said another way here.

        `why`, a dict, is filled with WHY NOTHING WAS SAID. Reading says why it read nothing (`Reading.why`,
        `Reading.missing`); saying returned the same empty list for seven different reasons, and half of what the
        grammar reads right it says nothing for (lab notebook (86)), so which reason it is was unknowable from
        outside. Measured, not reported: a meaning it cannot say exhausts the whole agenda, 267 s to say nothing of
        "Your arm's broken." (lyric_dev2, 2026-10-29).

        `how_surely`, a dict, is filled with HOW SURE IT IS OF EACH SENTENCE IT SAYS: the share of every whole reading
        of that sentence which is the meaning asked for (`Reading.sure`), the sentence said first at its head. A
        sentence is kept only where it reads back to exactly the meaning, which asks whether and never how surely, so
        one the grammar barely preferred and one it could not misread left looking the same: "Yourself'm vain." was
        kept with the standing of a sentence said well, every alternative reading of it unasked. Reading keeps how
        sure it is of what it reads and teaches from what it read as much as it was sure (`_learn_from_reading`);
        saying computed the same number at the very place it decided and threw it away (2026-10-30)."""
        def give_up(reason: str, **of: Any) -> List[str]:
            """Nothing said, and why. The reason is the first thing that stopped it, never a guess after the fact."""
            if why is not None:
                why.clear()
                why.update(of)
                why["why"] = reason
            # Nothing said is not something said unsurely: what was asked how surely is emptied, never left standing.
            if how_surely is not None:
                how_surely.clear()
            return []
        if meaning.act not in WHOLE.values() or not meaning.facts:
            return give_up("no act a sentence says, or no fact to say", act=meaning.act, facts=len(meaning.facts))
        # A NAME IS WRITTEN AS READING WRITES IT, its words apart (`award decoration`), as `Words.words_for` finds the
        # words for it: memory's store writes the same name joined (`award_decoration`), and each sentence said is
        # read back and kept only where its meaning is this one. Told "Roy fastened the medal with a pin.", "What did
        # Roy fasten?" was answered with the kind the store held (`award_decoration`): "Roy fastened the medal." was
        # made and read back `award decoration`, so nothing was said, and the answer was the bare word, "Medal."
        # (TRAIN-FORMAT-01, lyric_dev2, 2026-10-28).
        written = {t: t.replace("_", " ") for f in meaning.facts for t in f.terms()
                   if not is_variable(t) and "_" in t}
        if written:
            meaning = Meaning(meaning.act, tuple(replace(f, subject=written.get(f.subject, f.subject),
                                                         obj=written.get(f.obj, f.obj)) for f in meaning.facts),
                              tuple(written.get(a, a) for a in meaning.asked))
        # WHAT "ANOTHER" SAYS IS ITS OWN (Kay 1996: the facts a word's meaning covers are spent by it): a thing given of
        # a kind and held not to be the one of that kind said (`spell_out`'s `other`) is said by "another" before the
        # one, and by no word of its own, so the words are sought for the rest and each sentence read back to the
        # whole. Sought for the whole, nothing joined the cat chased to the cat known and "Tom chased another cat." was
        # never said, every word saying a denial and a being tried instead (2026-10-28).
        whole = meaning
        covered = _said_by_other(meaning)
        if covered:
            meaning = Meaning(meaning.act, tuple(f for f in meaning.facts if f not in covered), meaning.asked)
        wanted = _things_said(meaning)
        if not wanted:
            return give_up("the meaning names no thing a word could say")
        words = self.lexicon.words
        named = {str(k).lower(): str(v).lower() for k, v in (named or {}).items()}
        # KAY BINDING (Kay 1996, "Chart Generation"): each word put in is bound to the meaning's own terms where its
        # pieces say which (the word for a thing to the thing, "the" to a thing the meaning gives known, "a" to one it
        # does not, a word saying the past to the doing before now, a preposition to the two its fact joins), so
        # nothing combines it with what it is not said of: "in" said of the chasing and the park joins no cat. Unbound,
        # every way of saying each fact was combined with every other, and "Tom chased a cat in the park." was never
        # said: 131,665 items after 90 s, "if Tom which was in a park 'm" among them (2026-10-28).
        def variable(t: Any) -> bool:
            return is_variable(t) and t not in _SITUATION
        events = {f.subject for f in meaning.facts if f.relation in _HAPPENING_LINKS}
        of_kind: Dict[Tuple[str, str], Set[Term]] = defaultdict(set)
        for f in meaning.facts:
            if f.relation == "instance_of" and variable(f.subject) and not is_variable(f.obj):
                of_kind[(f.obj, "VERB" if f.subject in events else "NOUN")].add(f.subject)
            elif f.relation == "has_property" and not is_variable(f.obj):
                of_kind[(f.obj, "ADVERB" if f.subject in events else "ADJECTIVE")].add(f.subject)
        known = sorted({f.subject for f in meaning.facts if f.given and variable(f.subject)})
        unknown = sorted({f.subject for f in meaning.facts if f.relation == "instance_of" and variable(f.subject)
                          and f.subject not in events} - set(known))
        before_now = sorted({f.subject for f in meaning.facts if f.relation == "precedes" and f.obj == "?now"
                             and variable(f.subject)})

        def own_letter(entry: Entry) -> Optional[str]:
            # The variable of the piece naming the word itself (`kind x @`, `event e @`, `quality x @ q`).
            return next((p[1] for p in entry.sem if len(p) > 2 and "@" in p[2:] and isinstance(p[1], str)
                         and _MEANING_VARIABLE.fullmatch(p[1])), None)
        def roles_bound(entry: Entry, e: str, event: Term) -> List[Dict[str, Term]]:
            # A VERB'S PLACES, each bound to what the meaning's fact of its link holds, the link as reading decides it
            # (`spell_out`: `Lexicon.inherited` from the role's slot, "by" as the subject's, "~" turned round), one
            # way for each; a place whose link the meaning holds no fact of left open (reading skips some roles: an
            # ability's). A clause it takes must be a doing the meaning holds, not the cat: a frame taking one where
            # none is, is not offered ("chase" taking a "that" clause, a "to" clause, an -ing clause).
            ways: List[Dict[str, Term]] = [{e: event}]
            lexicon = self.lexicon
            for p in entry.sem:
                if p[0] != "role" or p[1] != e or len(p) < 4 or not isinstance(p[2], str):
                    continue
                slot = p[3]
                default = lexicon.linking.get(slot)
                if slot.startswith("pp:"):
                    default = worded(slot[3:]) if slot[3:].isalpha() else None
                got, _ = lexicon.inherited("role", entry.name, "VERB", (slot,), default)
                if slot == "by":
                    got, _ = lexicon.inherited("role", entry.name, "VERB", ("subject",), lexicon.linking.get("subject"))
                if not got or got == "same":
                    continue
                relation, turned = (got[1:], True) if got.startswith("~") else (got, False)
                ends = [f.subject if turned else f.obj for f in meaning.facts
                        if f.relation == relation and (f.obj if turned else f.subject) == event]
                if ends:
                    ways = [dict(w, **{p[2]: t}) for w in ways for t in dict.fromkeys(ends) if w.get(p[2], t) == t]
            for p in entry.sem:
                if p[0] == "clause" and p[1] == e and len(p) > 2:
                    ways = [w for w in ways if p[2] not in w or (w[p[2]] in events and w[p[2]] != event)]
            return ways
        bound_at: Dict[int, Dict[str, Term]] = {}
        # THE WORDS FOR ITS THINGS, each a place the sentence must fill once, with each word and entry that may fill it.
        tokens: List[str] = []
        places: List[List[Tuple[int, Entry]]] = []
        for concept, cls in wanted:
            written = words.words_for(concept, cls) or []
            if cls == "NAME":
                written = [" ".join(w[:1].upper() + w[1:] for w in str(concept).split())]
            options: List[Tuple[int, Entry]] = []
            # Bound only where the meaning holds one thing of the kind: of two cats, either word may be either.
            of_it = of_kind.get((concept, cls), set())
            for form in written:
                for _, entry in self.lexicon.entries((form,), 0):
                    if entry.cls == cls:
                        letter = own_letter(entry)
                        ways: List[Dict[str, Term]] = [{}]
                        if letter is not None and len(of_it) == 1:
                            ways = [{letter: next(iter(of_it))}]
                            if cls == "VERB":
                                ways = roles_bound(entry, letter, next(iter(of_it)))
                        for way in ways:
                            if way:
                                bound_at[len(tokens)] = way
                            options.append((len(tokens), entry))
                            tokens.append(form)
            if not options:
                # NO WORD FOR THIS THING, or none the grammar has an entry for as that kind of word. The thing's own
                # name is already what memory falls back to (`MemoryAgent.words_for`), so reaching here means memory
                # holds no word naming it at all, or holds one the grammar reads as another kind of word.
                return give_up("no word for a thing it must say", thing=f"{concept} ({cls})",
                               written=list(written)[:6])
            places.append(options)
        # THE GRAMMAR'S OWN WORDS, each spending what it says, as often as the meaning holds it, with every other word
        # saying the same (`_says_of`); a link a preposition names, once for each fact of it.
        budget: Dict[Tuple[str, ...], int] = {}
        chosen: List[Tuple[str, Entry, Dict[Tuple[str, ...], int]]] = []
        empty: List[Tuple[str, Entry]] = []
        # THE SPEAKER, THE LISTENER AND THE ONE SPOKEN OF BEFORE are said by the words whose category or meaning is
        # them ("I", "me", "you"; "he", "she", "it", "they": `_piece_says`), as often as the meaning holds them.
        # Neither was ever offered (the pronouns' piece said nothing saying knew, "I" and "you" carry none), so an
        # answer of what was told of "he" could not be said, and saying tried every way of saying the rest before it
        # found none: "He fixed the bicycle with a hacksaw." was still being said after 45 minutes (lyric_dev2,
        # 2026-10-28).
        situation = Counter(t for f in meaning.facts for t in (f.subject, f.obj)
                            if t in ("?speaker", "?listener", "?previous"))
        # EACH GRAMMAR WORD AS SURELY AS IT IS SAID FOR WHAT IT SAYS (lexical choice by how often a word is used so,
        # Belz 2008): a word saying a piece against the surest word saying the same ("some" 612 of the determiners'
        # uses against "a" 8,848); a word saying nothing, its share of the uses of words used as it is, said or not;
        # a preposition, of every way the link it is offered for was said, a verb's place saying it bare among them
        # (`Lexicon.said_with`: "for" 92 times `done_to`, an object 3,813). Who a pronoun, "I" or "you" stands for
        # decides it, and agreement with what it is said with: how often each is used does not. Offered as though
        # each were sure, every word that might say a piece was built with every other ("under", "towards", "if",
        # "although", "anybody" put into 70,000 makings of "She wears a blue hat."), none of them said, for over ten
        # minutes; and "some" was said before "a" (lyric_dev2, 2026-10-28).
        use_of = {(word, e["cat"]): e["use"] for word, held in self.lexicon.closed.items() for e in held
                  if isinstance(e, Mapping) and "use" in e and "cat" in e}
        of_use: Dict[str, Tuple[float, int]] = {}

        def share_of(word: str, entry: Entry) -> Optional[float]:
            use = use_of.get((word, entry.cat))
            if use is None:
                return None
            if use not in of_use:
                held = [words.uses(w).get(use, 0.0) for w in {w for (w, _), e in use_of.items() if e == use}]
                of_use[use] = (sum(held), len(held))
            total, n = of_use[use]
            return math.log((words.uses(word).get(use, 0.0) + 0.5) / (total + 0.5 * max(n, 1)))
        links_said: Dict[str, Tuple[Counter, float]] = {}

        def said_for(word: str, link: str, entry: Entry) -> Entry:
            if link not in links_said:
                links_said[link] = self.lexicon.said_with(link)
            held, bare = links_said[link]
            share = (held.get(word, 0) + 0.5) / (sum(held.values()) + bare + 0.5 * (len(held) + 1))
            return replace(entry, score=entry.score + math.log(share))
        for word in sorted(self.lexicon.closed):
            for _, entry in self.lexicon.entries((word,), 0):
                if entry.cls != "GRAMMAR":
                    continue
                # A word making a question ("is" put first, a tag "isn't it") only asks: nothing told holds one.
                cat = parse_category(entry.cat)
                if meaning.act != "ask" and _whole((_comes_to(cat) or [cat])[-1]) == "ask":
                    continue
                says = _says_of(entry, whole if any(p[0] == "other" for p in entry.sem) else meaning)
                if says:
                    budget.update(says)
                    chosen.append((word, entry, {k: 1 for k in says}))
                # Nothing of the meaning spent (`says` empty, never None) is what makes it such a word, which a
                # piece that only marks it does not change: "myself" marked a pronoun of its own sentence was no
                # longer offered for the speaker at all while this asked for no pieces whatever.
                elif says is not None and isinstance(cat, Atom) and cat.ref in situation and not says:
                    budget[("situation", cat.ref)] = situation[cat.ref]
                    chosen.append((word, entry, {("situation", cat.ref): 1}))
                elif says is not None and isinstance(cat, Fn) and not _leaves_as_is(cat):
                    # A WORD SAYING NOTHING ENTERS WHERE SOMETHING NEEDS IT (Carroll, Copestake, Flickinger and
                    # Poznański 1999; Carroll and Oepen 2005): one that leaves what it takes as it was ("the" before a
                    # name, NP.x/NP.x; "then", S[F].a/S[F].a) is needed by nothing, whatever it is said with meaning
                    # the same without it. Offered as often as there are things, "the" said "Wall is the the a
                    # partition." (lyric_dev2, 2026-10-27). Reading still reads it.
                    empty.append((word, entry))
        surest: Dict[Tuple[Tuple[str, ...], str], float] = {}
        shares = {(word, entry.cat): share_of(word, entry) for word, entry, _ in chosen}
        by_whom = {"situation", "pron"}

        def among(word: str, k: Tuple[str, ...]) -> Tuple[Tuple[str, ...], str]:
            """WHAT A WORD IS WEIGHED AGAINST BY HOW OFTEN IT IS WRITTEN: the words saying the same piece, and of
            those only the ones whose form says the same of a subject (`_agrees_as`).

            A FORM AGREEMENT DECIDES IS NOT CHOSEN BY HOW OFTEN IT IS WRITTEN, as who a pronoun stands for and not
            how often it is written decides it (`by_whom`, above). The copula's forms share one use, so "am",
            written 327 times against "are" 1,975, was offered 2.5 nats worse than "are" for saying a thing of the
            speaker; agreement is never better than nothing, so it could not make that up however well "I" and "am"
            agree. "Me are intelligent." was said of the speaker being intelligent, and "I am intelligent." was
            never built at all -- the two pack together once the subject is taken, and the surer was kept (lyric_db,
            2026-10-30)."""
            return k, self._agrees_as(word)
        for word, entry, spends in chosen:
            share = shares[(word, entry.cat)]
            if share is not None and not any(k[0] in by_whom for k in spends):
                for k in spends:
                    surest[among(word, k)] = max(surest.get(among(word, k), share), share)
        chosen = [(word, entry if shares[(word, entry.cat)] is None or any(k[0] in by_whom for k in spends) else
                   replace(entry, score=entry.score + shares[(word, entry.cat)]
                           - max(surest[among(word, k)] for k in spends)), spends)
                  for word, entry, spends in chosen]
        surest_of_use: Dict[Tuple[Tuple[str, ...], str], float] = {}
        for word, entry in empty:
            share, use = share_of(word, entry), use_of.get((word, entry.cat))
            if share is not None:
                surest_of_use[among(word, (use,))] = max(surest_of_use.get(among(word, (use,)), share), share)
        empty = [(word, entry if share_of(word, entry) is None else replace(
            entry, score=entry.score + share_of(word, entry)
            - surest_of_use[among(word, (use_of[(word, entry.cat)],))])) for word, entry in empty]
        # A PREPOSITION SAYS A LINK HERE ONLY WHERE READING IT HERE GIVES THAT LINK (Kay 1996: only what may say part
        # of the meaning is put in): what the word was taught to say of a doing or a thing, by what the thing it takes
        # is, and what it said of the very word it follows, as `spell_out` decides it. Offered wherever it ever said
        # the link, "of" ("a kind of fish": `isa`) was tried for every kind said to be a kind, and "A wall is a
        # structure." took 198 s, 4,460 sentences with "of" read back and none of them meaning it (lyric_dev2,
        # 2026-10-28).
        kind_of_term = {f.subject: f.obj for f in meaning.facts
                        if f.relation == "instance_of" and variable(f.subject) and not is_variable(f.obj)}

        def read_as(word: str, a: Term, b: Term) -> Optional[str]:
            kind = "event" if a in events else "thing"
            time = self.lexicon.time_of(b) or (self.lexicon.time_of(kind_of_term[b]) if b in kind_of_term else None) or "-"
            if b in kind_of_term:
                what = [kind_of_term[b]] + words.kinds(kind_of_term[b], "NOUN")
            elif b in ("?speaker", "?listener"):
                what = ["person"]
            elif not isinstance(b, str) or b.startswith("?") or _number(b) is not None:
                what = []
            else:
                what = words.kinds(b, "NOUN") + [NAMED]
            said, _ = self.lexicon.link("prep", (word, kind, time), worded(word) if word.replace(" ", "").isalpha()
                                   else None)
            got, _ = self.lexicon.selected("prep_to", (word, kind), what, said)
            head = kind_of_term.get(a) if variable(a) else a
            if head is not None:
                own, how_own = self.lexicon.link("prep_of", (head, word, time), None)
                if how_own == "own":
                    got = own
            return got

        def says_here(word: str, link: str) -> bool:
            return any(read_as(word, f.subject, f.obj) == link or read_as(word, f.obj, f.subject) == "~" + link
                       for f in meaning.facts if f.relation == link)
        for link in sorted({f.relation for f in meaning.facts}):
            for word in self.lexicon.saying(link):
                if not says_here(word, link):
                    continue
                for _, entry in self.lexicon.entries((word,), 0):
                    if entry.cls == "PREPOSITION":
                        budget[("fact", link)] = sum(1 for f in meaning.facts if f.relation == link)
                        chosen.append((word, said_for(word, link, entry), {("fact", link): 1}))
        # WHAT THE SENTENCE MAKES, so a word saying nothing is said only as often as what it takes is: each phrase the
        # words for its things and the grammar words saying something come to ("paint" a doing, "is" a doing of a
        # thing), each once a place or as often as what it says; and how many sentences of their own they head.
        made: Counter = Counter()
        clauses = 0
        for options in places:
            cats = [parse_category(e.cat) for _, e in options]
            made.update({_key(c) for cat in cats for c in [cat] + _comes_to(cat)})
            clauses += any(_heads_a_clause(cat) for cat in cats)
        spent_by: Dict[Tuple[str, ...], List[Cat]] = defaultdict(list)
        for _, entry, spends in chosen:
            for k in spends:
                spent_by[k].append(parse_category(entry.cat))
        for k, cats in spent_by.items():
            made.update({c: budget[k] for c in {_key(c) for cat in cats for c in _comes_to(cat)}})
            clauses += budget[k] if any(_heads_a_clause(cat) for cat in cats) else 0
        # A WORD SAYING NOTHING spends what it takes, with every word taking the same: "a", "an" and "some" together
        # one for each kind said; one joining a sentence onto a thing ("that", "who"), once less than the sentences
        # the meaning's words head, the sentence said keeping one. What one makes ("the medal" of "medal") is what
        # another takes ("by"), counted over again as often as there are words making a thing, a chain of them no
        # longer (one modifying what it takes makes nothing more).
        def takes(cat: Fn) -> Tuple[str, ...]:
            return ("joins",) if _joins(cat) else ("takes", _key(cat.arg))
        making: Dict[Tuple[str, ...], Set[str]] = defaultdict(set)
        for _, entry in empty:
            cat = parse_category(entry.cat)
            if not _joins(cat) and not _same_shape(cat.res, cat.arg):
                making[takes(cat)] |= {_key(c) for c in _comes_to(cat)}
        # The sentences a meaning can need are no more than its doings and what it says of a thing that is no doing
        # (a cat being red, a thing being in a place): "in the park" said of the chasing is no sentence of its own,
        # though "in" may head one ("was in the park"), and counted so, "if" and "which" were offered twice for "Tom
        # chased a cat in the park." (2026-10-28).
        said_of_things = sum(1 for f in meaning.facts if f.subject not in events and f.relation not in _HAPPENING_LINKS
                             and not (f.relation == "instance_of" and variable(f.subject)))
        budget[("joins",)] = max(min(clauses, len(events) + said_of_things) - 1, 0)
        grown = Counter(made)
        for _ in range(len(making) + 1):
            for _, entry in empty:
                cat = parse_category(entry.cat)
                if not _joins(cat):
                    budget[takes(cat)] = grown[_key(cat.arg)]
            more = Counter(made)
            for k, keys in making.items():
                more.update({c: budget[k] for c in keys})
            if more == grown:
                break
            grown = more
        for word, entry in empty:
            k = takes(parse_category(entry.cat))
            if budget.get(k):
                chosen.append((word, entry, {k: 1}))
        spending = sorted({k for _, _, spends in chosen for k in spends})
        if (("?speaker" in situation and ("situation", "?speaker") not in spending)
                or ("?listener" in situation and ("situation", "?listener") not in spending)
                or ("?previous" in situation and ("pron",) not in spending)):
            return give_up("no word for the speaker, the listener or the one spoken of",
                           situation=sorted(situation))
        qualities = any(f.relation == "has_property" for f in meaning.facts)

        def bindings_of(entry: Entry, spends: Mapping[Tuple[str, ...], int]) -> List[Dict[str, Term]]:
            # A grammar word, one way for each term its pieces may be said of: "the" each thing given, "a" each
            # thing not, a word saying the past each doing before now; a preposition the two its fact joins, either
            # way round (a link learned the other way, "~", turns them), and where the meaning holds a quality, its
            # thing alone (after a quality, "allergic to pollen", it tells of the quality's holder).
            links = {k[1] for k in spends if k[0] == "fact"}
            prep = next((p for p in entry.sem if p[0] == "prep"), None)
            if links and prep is not None:
                a, b = prep[1], prep[2]
                ways = []
                for f in meaning.facts:
                    if f.relation in links:
                        ways += [{a: f.subject, b: f.obj}, {a: f.obj, b: f.subject}]
                        ways += [{b: f.obj}, {b: f.subject}] if qualities else []
                return [dict(w) for w in dict.fromkeys(tuple(sorted(w.items())) for w in ways)] or [{}]
            out: List[Dict[str, Term]] = [{}]
            for p in entry.sem:
                of = {"given": known, "past": before_now, "indefinite": unknown, "pron": ("?previous",)}.get(p[0])
                if p[0] == "pron" and len(p) > 3 and p[3] == "own":
                    # A PRONOUN OF ITS OWN SENTENCE STANDS FOR A THING THE SENTENCE SAYS, not for the one spoken of
                    # before, so it is bound to nothing here and what takes it decides which thing it is. Bound to
                    # `?previous` as a pronoun of another sentence is, "ourselves" was made to stand for a thing
                    # outside the sentence and "We misled ourselves." was said back as nothing at all.
                    continue
                if of and len(p) > 1 and isinstance(p[1], str) and _MEANING_VARIABLE.fullmatch(p[1]):
                    out = [dict(o, **{p[1]: t}) for o in out for t in of if o.get(p[1], t) == t]
            return out or [{}]
        extra: List[Tuple[int, Entry, Tuple[int, ...]]] = []
        for word, entry, spends in chosen:
            for way in bindings_of(entry, spends):
                if way:
                    bound_at[len(tokens)] = way
                extra.append((len(tokens), entry, tuple(spends.get(k, 0) for k in spending)))
                tokens.append(word)
        most = tuple(budget[k] for k in spending)
        self._tokens, self._weighed, self._marking, self._asking = tuple(tokens), None, frozenset(), frozenset()
        self._agreeing = {}
        # A WORD TAKING WHAT NO WORD HERE CAN MAKE IS NEVER SAID: every word of a sentence has all it takes. What the
        # words can make is found from the words up (each word, what it makes once what it takes can be made, what
        # composing two makes, a thing raised to what is said of it, what `_unary` reads a stretch as), and a word is
        # offered only where all it takes is among it. "be", "been", "being" before a quality and "anybody" waited for
        # a quality no word of "Tom chased a cat in the park." says (2026-10-28).
        made_here = self._makes([self._lexical(tokens, at, at + 1, entry, bound_at.get(at))
                                 for at, entry in [o for options in places for o in options]
                                 + [(at, entry) for at, entry, _ in extra]])
        places = [[(at, entry) for at, entry in options if self._takes_from(entry, made_here)] for options in places]
        if not all(places):
            return give_up("a thing's every word takes something no word here can make",
                           thing=next(f"{c} ({cls})" for (c, cls), options in zip(wanted, places) if not options))
        extra = [(at, entry, spends) for at, entry, spends in extra if self._takes_from(entry, made_here)]
        full = (1 << len(places)) - 1
        # THE CHART, over which words are used, not where they stand: (places filled, what the grammar words spent,
        # what it means and its category (`_meant`)) -> the surest such sign, with its words in order and where each
        # is among the words. ONE OF WHAT MEANS THE SAME: "a wall is" and "a wall 's" go on to the same sentences,
        # only as surely as each is read (kept by its words in order, every way of putting each was read back, 19,296
        # for "A wall is a partition.", lyric_dev2, 2026-10-27).
        Item = Tuple[int, Tuple[int, ...], Sign, Tuple[str, ...], Tuple[int, ...], Tuple]
        held: Dict[Tuple, Item] = {}
        agenda: List[Tuple[float, int, int, Item]] = []
        pushed = itertools.count()
        none = tuple(0 for _ in spending)
        # THE MOST EACH PLACE STILL TO BE SAID CAN ADD: the surest of its words alone. Nothing made adds to how surely
        # a word is read (a join, agreement, a word put beside it each weigh it down), so what is made is never surer
        # than it and these together, and what is made first is made best first (A*: Klein and Manning 2003).
        best_at: List[float] = []
        for options in places:
            scores = []
            for at, entry in options:
                with contextlib.suppress(ValueError, IndexError):
                    scores.append(self._lexical(tokens, at, at + 1, entry, bound_at.get(at)).score)
            best_at.append(max(scores, default=-1e9))

        def to_come(filled: int) -> float:
            return sum(s for k, s in enumerate(best_at) if not filled >> k & 1)
        # A WORD WEIGHED BY THE WORD SAID AFTER IT ("a", "an": `Lexicon._sound_after`) is weighed alone until a word is
        # put after it, then by that word; what ends in one, and what begins with each first sound, is kept apart
        # until then. Packed by meaning alone, "a" was surer alone than "an" and "an" was never said: "A owl is a
        # bird." was said first (2026-10-27).
        lexicon = self.lexicon
        alike = {w for w in set(tokens) if len(lexicon.words.said_before(w)) > 1}
        # What such a word takes after it ("a" a noun): only that is kept apart by the sound it begins with.
        taken = [cat.arg for w in alike for _, e in lexicon.entries((w,), 0)
                 for cat in [parse_category(e.cat)] if isinstance(cat, Fn) and cat.slash == "/"]

        beside_of: Dict[Tuple[str, str], float] = {}

        def first_sound(word: str) -> Tuple[str, ...]:
            return tuple(sorted({way.split()[0].rstrip("012") for way in lexicon.words.sounds(word) if way.split()}))

        # WHAT CAN NEVER BE COMPLETED IS DROPPED (Kay 1996): a thing of the meaning said inside a stretch but no longer
        # reachable from its category ("a cat" taken by "chased": the cat) is joined to nothing more, so each fact
        # joining it to another thing must already be said there, or be sayable by a piece of it still open.
        joined: Dict[Term, Set[Term]] = defaultdict(set)
        for f in meaning.facts:
            if f.relation not in ("instance_of", "has_property") and variable(f.subject) \
                    and f.obj not in _SITUATION and f.subject != f.obj:
                joined[f.subject].add(f.obj)
                if variable(f.obj):
                    joined[f.obj].add(f.subject)

        def reachable(cat: Cat) -> Set[Term]:
            if isinstance(cat, Atom):
                return {cat.ref} if cat.ref is not None else set()
            return reachable(cat.res) | reachable(cat.arg)

        def completable(sign: Sign) -> bool:
            if not joined:
                return True
            reach = reachable(sign.cat)
            within = {t for p in sign.pieces for t in p if isinstance(t, str) and t in joined} - reach
            # Still open is what its category reaches: a variable inside it no longer reached is bound by nothing.
            still = {y for y in reach if type(y) is int and y >= FIRST_VARIABLE}
            for t in within:
                for u in joined[t]:
                    if not any(t in p and (u in p or any(y in still for y in p if type(y) is int)) for p in sign.pieces):
                        return False
            return True

        # A DOING MADE FINITE IS TOLD AT THE TIME THE WORD MAKING IT FINITE TELLS (`spell_out`: `past` a doing before
        # now, `now` one now, `future` one after): nothing said after that makes it another, so one of the meaning's
        # doings made finite at another time than the meaning holds can never be completed ("Tom do chase", for a
        # chasing before now: "do" makes it finite and tells no time).
        time_of: Dict[Term, str] = {}
        for f in meaning.facts:
            when = {"precedes": "past", "follows": "future", "during": "now"}.get(f.relation)
            if when and f.obj == "?now" and variable(f.subject):
                time_of[f.subject] = when

        def timed(sign: Sign) -> bool:
            told: Dict[Term, str] = {}
            for p in sign.pieces:
                if p[0] in ("past", "future", "now") and len(p) > 1:
                    told.setdefault(p[1], p[0])
            return all(told.get(p[1]) == time_of.get(p[1]) for p in sign.pieces
                       if p[0] == "finite" and len(p) > 1 and variable(p[1]))

        # A FINITE VERB STILL TAKING ITS SUBJECT is kept apart by its form until the subject is taken: the subject is
        # weighed with the form (`_agreement`), and what a later rule weighs may not be packed away (Oepen and Carroll
        # 2000). Packed by meaning alone ("was" and "were" each say `be` before now), the form surer alone was kept and
        # the other never said: of the medal painted, "The medal were painted." was all there was (lyric_dev2,
        # 2026-10-28).
        def taking_subject(sign: Sign) -> str:
            # Kept apart by what a subject is weighed with: the number and person the form is written with most
            # (`_agrees_as`: "was", "were"), not the form ("is" and "'s" go on alike).
            if "NP" not in _wants(sign.cat)[1]:
                return ""
            hook = _hook(sign.cat)
            at = [p[-1] for p in sign.pieces if p[0] == "finite" and p[1] == hook]
            if not at or not 0 <= min(at) < len(tokens):
                return ""
            return self._agrees_as(str(tokens[min(at)]))
        case_of: Dict[Tuple[str, int], str] = {}

        def standing_as(sign: Sign) -> str:
            # A THING IS KEPT APART BY ITS CASE, the one form where it stands decides ("I" and "me", "he" and "him"):
            # the case its word is written with most. Packed by meaning alone, the speaker was said as whichever of
            # "I" and "me" was surer before any verb took it, and "Me love the moon." was said of the speaker loving
            # it; kept apart by number and person too, every thing's every form was built with every other's, and "He
            # fixed the bicycle with a hacksaw." went from 1.9 s to over ten minutes (lyric_dev2, 2026-10-28).
            if not isinstance(sign.cat, Atom) or sign.cat.base != "NP" or not words.subjects():
                return ""
            found = self._said_by(sign.pieces, sign.cat.ref)
            if found is None:
                return ""
            if found not in case_of:
                forms = self._features(*found)
                most = max(sorted(forms), key=lambda f: forms[f]) if forms else ""
                case_of[found] = next((f for f in most.split("|") if f.startswith("Case=")), "")
            # AND BY WHETHER IT IS SAID BY A PRONOUN OF ITS OWN SENTENCE, which the place it stands in asks for or
            # refuses (`_stands_as_written`) and which no case tells apart, "me" and "myself" both being accusative:
            # packed together by case alone, the surer of the two was kept and the other never reached the place
            # that asked for it.
            own = any(p[0] == "pron" and len(p) > 3 and p[3] == "own" and p[1] == sign.cat.ref
                      for p in sign.pieces)
            return case_of[found] + (" own" if own else "")

        def hold(filled: int, used: Tuple[int, ...], sign: Sign, said: Tuple[str, ...], order: Tuple[int, ...]) -> None:
            if not completable(sign) or not timed(sign):
                return
            key = (filled, used, _meant(sign, order, tokens), taking_subject(sign), standing_as(sign)) + (
                (said[-1] if said[-1] in alike else "",
                 first_sound(said[0]) if any(_same_shape(sign.cat, c) for c in taken) else ()) if alike else ())
            if key in held and held[key][2].score >= sign.score:
                return
            held[key] = item = (filled, used, sign, said, order, key)
            heapq.heappush(agenda, (-(sign.score + to_come(filled)), -bin(filled).count("1"), next(pushed), item))
            for u in self._unary(sign):
                hold(filled, used, u, said, order)
        for k, options in enumerate(places):
            for at, entry in options:
                with contextlib.suppress(ValueError, IndexError):
                    hold(1 << k, none, self._lexical(tokens, at, at + 1, entry, bound_at.get(at)), (tokens[at],),
                         (at,))
        for at, entry, spends in extra:
            with contextlib.suppress(ValueError, IndexError):
                hold(0, spends, self._lexical(tokens, at, at + 1, entry, bound_at.get(at)), (tokens[at],), (at,))
        closing = {"tell": ".", "ask": "?"}[meaning.act] if meaning.act in ("tell", "ask") else "."
        wanted_act = meaning.act
        target = whole.canonical()
        sentences: Dict[Tuple[str, ...], Tuple[int, float]] = {}
        refused: Set[Tuple[str, ...]] = set()
        # THE SPEAKER'S OWN VERB IS THE VERB, NOT THE FORM IT TOOK (Brennan and Clark 1996: a speaker keeps the other's
        # term): a verb's form is what its subject and its time make it (contextual inflection, Booij 1996), and the
        # time is the meaning's, so each of its forms counts as it. A noun's form says how many (inherent inflection),
        # which the meaning does not hold, so a noun is the speaker's as they wrote it: "Roy made the pictures." of one
        # picture. Counted as written, the verb a question put in its base form was said so whatever its subject and
        # time: "Does Roy paint?" answered "Roy paint.", "Did Roy coat the wall?" "Roy coat the wall." (lyric_dev2,
        # 2026-10-28).
        own_verbs = {words.lexeme(w, "VERB") for w in named.values()}

        def own(said: Tuple[str, ...], sign: Optional[Sign]) -> int:
            verbs = {k for p in (sign.pieces if sign is not None else ()) if p[0] == "word" and p[2] == "VERB"
                     for k in range(p[3], p[4])}
            return sum(1 for k, w in enumerate(said) if w.lower() in named.values()
                       or (k in verbs and words.lexeme(w, "VERB") in own_verbs))
        # MADE BEST FIRST, READ BACK AS SOON AS WHOLE, AND MADE NO FURTHER ONCE ENOUGH ARE SAID (anytime realization,
        # White 2004; Carroll and Oepen 2005: a realizer builds the most complete, surest first and stops at the first
        # good ones, never every way of saying it): the agenda takes first what is surest with the most the rest of
        # the meaning can add (`to_come`); each sentence made whole is read back at once, and making stops once
        # `SAID_AT_MOST` read back to the meaning. Every sentence was made and then every one read back: told "Roy
        # painted the box for Tom.", "Who did Roy paint the box for?" took over ten minutes once 238 words were taught,
        # each preposition taught to say what it joins combined with every other (lyric_dev2, 2026-10-28). Taken by
        # what says most of the meaning first, the first made were one way of saying it in all its forms: of a dog
        # being a mammal, "A dog is mammals." and "A dogs is a mammal." were said, never "Dogs are mammals.".
        state = (self._tokens, self._weighed, self._marking, self._asking, self._agreeing)

        def read_back(said: Tuple[str, ...]) -> None:
            # Read as it is written, its first word with a capital: "wall" first was read surely (-4.6), "Wall" not
            # (-32.3), a name it might be (lyric_dev2, 2026-10-27). Reading takes the grammar's state for the
            # sentence read; the making's is put back.
            reading = self.read((said[0][:1].upper() + said[0][1:],) + said[1:] + (closing,))
            self._tokens, self._weighed, self._marking, self._asking, self._agreeing = state
            if reading.meaning is None or reading.meaning.act != wanted_act or reading.meaning.canonical() != target:
                refused.add(said)
                return
            # HOW SURELY IT READS BACK, kept beside whether it does: a sentence with one reading says the meaning and
            # nothing else, where one of several says it only as surely as that reading is taken (`Reading.sure`).
            sentences[said] = (own(said, reading.sign), reading.sign.score if reading.sign is not None else 0.0,
                               reading.sure)
        # TWO STRETCHES SAYING NOTHING ARE NOT COMBINED (Eisner 1996, normal-form CCG): what both say nothing of the
        # meaning (no word for a thing, nothing spent the meaning holds) combine only with what says something, every
        # sentence built so being built otherwise too, each word taking what says something first: "to" with "be in
        # the park", never "to be" waiting for it. Combined, "to be", "to have been" and "if if" were built for every
        # way of saying each fact ("Tom chased a cat in the park.", 2026-10-28).
        content = tuple(k[0] not in ("takes", "joins") for k in spending)

        def says_nothing(filled: int, used: Tuple[int, ...]) -> bool:
            return not filled and not any(n and c for n, c in zip(used, content))
        # KAY'S INDEX (Kay 1996, chart generation): each item kept is filed under the shapes it stands as (`_offers`) and
        # the shapes it takes after it and before it (`_wants`), so a new one is tried only with those it may combine
        # with, in the order they were kept, each way round. Tried with every item kept, 88% of 1.34 million tries made
        # nothing, and the trying was two thirds of the time ("Tom chased a cat.", 15.2 s); a doing of five facts was
        # never said ("Did Roy coat the wall?", lyric_dev2, 2026-10-28). What combines by no shape (a joining word, a
        # list's second part, a mark) is tried with all; a kind with any one word, as a name may follow it ("named").
        done: List[Item] = []
        standing: Dict[str, List[int]] = defaultdict(list)
        taking_after: Dict[str, List[int]] = defaultdict(list)
        taking_before: Dict[str, List[int]] = defaultdict(list)
        kinds: List[int] = []
        lexical: List[int] = []
        unshaped: List[int] = []

        def by_no_shape(cat: Cat) -> bool:
            return (isinstance(cat, Atom) and cat.base in ("conj", "punct")) or (isinstance(cat, Fn) and cat.slash == "&")
        while agenda and len(sentences) < SAID_AT_MOST:
            item = heapq.heappop(agenda)[-1]
            filled, used, sign, said, order, key = item
            if held[key] is not item:
                continue
            n = len(done)
            done.append(item)
            if filled == full and _whole(sign.cat) is not None and said not in sentences and said not in refused:
                read_back(said)
            offers, (after, before) = _offers(sign.cat), _wants(sign.cat)
            for s in offers:
                standing[s].append(n)
            if after is not None:
                taking_after[after].append(n)
            for s in before:
                taking_before[s].append(n)
            noun = isinstance(sign.cat, Atom) and sign.cat.base == "N"
            if noun:
                kinds.append(n)
            if sign.rule == "lex":
                lexical.append(n)
            if by_no_shape(sign.cat):
                unshaped.append(n)
            if by_no_shape(sign.cat):
                partners: Iterable[int] = range(n + 1)
            else:
                found = set(unshaped)
                for s in offers:
                    found.update(taking_before[s])
                    found.update(taking_after[s])
                if after is not None:
                    found.update(standing[after])
                for s in before:
                    found.update(standing[s])
                if noun:
                    found.update(lexical)
                if sign.rule == "lex":
                    found.update(kinds)
                partners = sorted(found)
            for j in partners:
                other_item = done[j]
                other_filled, other_used, other, other_said, other_order, other_key = other_item
                if filled & other_filled or held[other_key] is not other_item:
                    continue
                together = tuple(a + b for a, b in zip(used, other_used))
                if any(n > m for n, m in zip(together, most)):
                    continue
                if says_nothing(filled, used) and says_nothing(other_filled, other_used):
                    continue
                for left, right, words_said, words_order, last, first in (
                        (sign, other, said + other_said, order + other_order, said[-1], other_said[0]),
                        (other, sign, other_said + said, other_order + order, other_said[-1], said[0])):
                    combinations = self._combine(left, right)
                    if not combinations:
                        continue
                    if last not in alike:
                        beside = 0.0
                    elif (last, first) not in beside_of:
                        beside = beside_of[(last, first)] = \
                            lexicon._sound_after((last, first), 0) - lexicon._sound_after((last,), 0)
                    else:
                        beside = beside_of[(last, first)]
                    for combined in combinations:
                        if combined.binding is not None:
                            # As the chart makes a combination's meaning (`chart`, `keep`): its parts' pieces, bound.
                            combined.pieces = _substitute(left.pieces + right.pieces, combined.binding)
                            combined.binding = None
                        combined.score += beside
                        hold(filled | other_filled, together, combined, words_said, words_order)
        ranked = sorted(sentences, key=lambda said: (-sentences[said][0], -sentences[said][1]))
        if how_surely is not None:
            how_surely.clear()
            how_surely.update({_written(said, closing): sentences[said][2] for said in ranked})
        if not sentences and why is not None:
            # SEARCHED AND FOUND NOTHING, which is two different things: no whole sentence was ever made, or some were
            # and reading took every one of them to mean something else. The second is the grammar disagreeing with
            # itself and is the more serious. Which things nothing ever said is the chart's own `filled`, read off the
            # items it kept rather than counted in the loop that keeps them.
            said_any = 0
            for key in held:
                said_any |= key[0]
            why.clear()
            why.update({
                "why": ("made whole and reading took them to mean something else" if refused
                        else "no whole sentence was ever made"),
                "unsaid": [f"{c} ({cls})" for k, (c, cls) in enumerate(wanted) if not said_any >> k & 1],
                "items": len(held), "refused": len(refused),
                "read_back_otherwise": [_written(said, closing) for said in sorted(refused)[:3]]})
        return [_written(said, closing) for said in ranked]

    @staticmethod
    def _bare(cat: Cat) -> Cat:
        """A category without what it is of: its shape and features, nothing it refers to; a feature the grammar's
        data writes as a variable (`S[F]`) open."""
        if isinstance(cat, Atom):
            open_ = isinstance(cat.feat, str) and cat.feat[:1].isupper()
            return Atom(cat.base, None if open_ else cat.feat, None)
        return Fn(Grammar._bare(cat.res), cat.slash, Grammar._bare(cat.arg))

    def _makes(self, signs: Sequence[Sign]) -> List[Cat]:
        """EVERY CATEGORY THESE WORDS CAN MAKE, from the words up (`Grammar.say`): each word's category; what a word
        makes once what it takes can be made, along its spine; what composing two makes (X/Y with Y/Z: X/Z; Y\\Z
        with X\\Y: X\\Z); a thing raised to what is said of it (NP with (S\\NP)/Z: S/Z); and what `_unary` reads a
        stretch of each as, of one word and of more. Of every category its shape and features, not what it is of."""
        held: Dict[str, Cat] = {}

        def fits(cat: Cat) -> bool:
            return any(_unify(self._bare(cat), c, {}) for c in held.values())

        def fitting(cat: Cat) -> List[Dict[int, Term]]:
            # Each way what a word takes is one of what can be made: what its features are bound to so, which what
            # it makes then carries ("in the park" makes of an S[dcl] doing an S[dcl] one, never any S).
            out = []
            for c in list(held.values()):
                s: Dict[int, Term] = {}
                if _unify(cat, c, s):
                    out.append(s)
            return out

        def add(cat: Cat) -> bool:
            k = _key(self._bare(cat))
            if k in held:
                return False
            held[k] = self._bare(cat)
            for length in (1, 2):
                for u in self._unary(Sign(cat, (), 0.0, 0, length, "lex", (), 0, "")):
                    add(u.cat)
            return True
        for sign in signs:
            add(sign.cat)
        grew = True
        while grew:
            grew = False
            for sign in signs:
                waiting = [self._bare(sign.cat)]
                while waiting:
                    cat = waiting.pop()
                    if isinstance(cat, Fn) and cat.slash in "/\\":
                        for s in fitting(cat.arg):
                            made = _apply(cat.res, s)
                            if add(made):
                                grew = True
                                waiting.append(made)
            for f in list(held.values()):
                if not isinstance(f, Fn) or f.slash not in "/\\":
                    continue
                for g in list(held.values()):
                    if not isinstance(g, Fn) or g.slash != f.slash:
                        continue
                    first, second = (f, g) if f.slash == "/" else (g, f)
                    s: Dict[int, Term] = {}
                    if f.slash == "/" and _unify(first.arg, second.res, s):
                        grew |= add(_apply(Fn(first.res, "/", second.arg), s))
                    s = {}
                    if f.slash == "\\" and _unify(second.arg, first.res, s):
                        grew |= add(_apply(Fn(second.res, "\\", first.arg), s))
                if isinstance(f.res, Fn) and f.res.slash == "\\" and f.slash == "/" and fits(f.res.arg) \
                        and isinstance(f.res.res, Atom):
                    grew |= add(Fn(f.res.res, "/", f.arg))
        return list(held.values())

    def _takes_from(self, entry: Entry, made: Sequence[Cat]) -> bool:
        """Whether all a word's entry takes, along its spine, is among what the words can make (`_makes`); a word
        joining a list or a mark takes by no shape, and is kept."""
        cat = parse_category(entry.cat)
        while isinstance(cat, Fn):
            if cat.slash in "/\\" and not any(_unify(self._bare(cat.arg), c, {}) for c in made):
                return False
            cat = cat.res
        return True

    def _said_so(self, cat: Cat) -> float:
        """How often what is said is said as a reading of this category says it, as a logarithm: an order
        (`_ordered`), or a sentence saying its doer, as often as the sentences memory holds analysed are each
        (`Words.orders`), with one more spread over the two.

        AN ORDER IS SAID SELDOM. Read by its words alone, "Water boils." was an order to water the boils, and "Smoke
        rises." one to smoke the rises: words used as nouns and as verbs read either way about as surely. Of the
        English Web Treebank's first 200 sentences held, 7 are orders and 150 tell or ask of a doer (lyric_dev,
        2026-10-24). Before orders were ranked as sentences (`_rank`), every telling came before every order."""
        ordered, told = self.lexicon.words.orders()
        return math.log(((ordered if _ordered(cat) else told) + 1.0) / (ordered + told + 2.0))

    # ── the meaning ──
    def _spell_out(self, sign: Sign, tokens: Sequence[str], reading: Reading) -> Optional[Meaning]:
        return spell_out(self.lexicon, sign, tokens, reading)

    # ── learning from sentences taught with their meanings ──
    def learn(self, tokens: Sequence[str], meaning: Meaning, words: Mapping[str, Sequence[int]],
              counted: Optional[List[Tuple[str, Tuple, str]]] = None, derived: Sequence[Derived] = (),
              text: str = "") -> bool:
        """Learn from a sentence taught with its meaning, its terms aligned to its words (`words`: term -> the
        words saying it): read it by the grammar, and for each place a verb, a preposition, a possessive, an adverb
        or "is" holds, the link the meaning says between the two words' terms. Returns whether it was read; each
        count made is added to `counted` (table, key, link), so it can be taken back (`unlearn`).

        WHERE THE SENTENCE'S DERIVATION BY HAND IS HELD (`derived`, its `text`), a verb's places and a preposition's
        links are learned from it, read or not (`_learn_places_derived`): which word fills which place, what each
        preposition tells of and what it takes, as the derivation says, the link as the meaning says. Learned from
        the reading the grammar's word counts preferred, they were labelled whatever that reading joined: "studying
        English" read with English what the studying was done to, where the meaning says what it is about."""
        tokens = tuple(tokens)
        # WHAT A HAPPENING WAS DURING IS A TIME (`Lexicon.time_of`), from the meaning alone, read or not: "The dog
        # barked yesterday.", "The cat ran at night.", "Tom walked in the morning." (a morning, by its kind). Not a
        # happening another was during ("The dog barked when the cat ran."): a running is no kind of time, and counted
        # as one, `run` and `bark` were times.
        kinds_said = {f.subject: f.obj for f in meaning.facts if f.relation == "instance_of"}
        happenings = {f.subject for f in meaning.facts
                      if f.relation in ("done_by", "done_to", "during", "precedes", "follows")}
        for f in meaning.facts:
            if f.relation == "during" and f.positive and f.obj not in happenings:
                name = f.obj if not is_variable(f.obj) else kinds_said.get(f.obj)
                if name and not is_variable(name):
                    self.lexicon.learned["time"][(str(name).lower(),)]["during"] += 1
                    if counted is not None:
                        counted.append(("time", (str(name).lower(),), "during"))
        placed = self._learn_places_derived(tokens, meaning, words, derived, text, counted) if derived else set()
        cells = self.chart(tokens)
        whole = [s for s in cells.get((0, len(tokens)), {}).values() if _whole(s.cat) is not None]
        if not whole:
            return False
        # Read as its meaning says it was said: a request as an order where the grammar reads it as one, anything
        # else as no order ("Water boils." is taught a telling, and is not learned from as an order to water boils).
        ordered = meaning.act == "request"
        fitting = [s for s in whole if _ordered(s.cat) == ordered]
        best = max(fitting or whole, key=lambda s: (_rank(s.cat) == 2, s.score, _rank(s.cat)))
        term_of: Dict[int, str] = {}
        for t, ws in words.items():
            for w in ws:
                term_of.setdefault(w, t)
        between: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for f in meaning.facts:
            between[(f.subject, f.obj)].append(f.relation)
        pieces = best.pieces
        word_of = _words_of_terms(pieces)
        #: Where each word read ends: a preposition of several words ("away from") is placed where any of its words is.
        ends = {p[3]: p[4] for p in pieces if p[0] == "word"}
        holders: Dict[Term, Term] = {p[3]: p[1] for p in pieces if p[0] == "quality"}
        holders.update({p[3]: p[1] for p in pieces if p[0] == "be"})
        timed = {p[1] for p in pieces if p[0] == "past"}
        graded = {p[1] for p in pieces if p[0] in ("degree", "degree_asked")}
        kinds_of = {p[1]: p for p in pieces if p[0] in ("kind", "event")}
        things = {p[1]: p for p in pieces if p[0] == "kind"}
        learned = self.lexicon.learned

        def count(table: str, key: Tuple, link: str) -> None:
            learned[table][key][link] += 1
            if counted is not None:
                counted.append((table, key, link))

        held_terms = {t for f in meaning.facts for t in f.terms()}

        def said(a: Term, b: Term) -> Optional[List[str]]:
            # A term is the meaning's term its word is aligned to; a name or a number the meaning holds as written
            # is itself ("in 1970": the year said by no line of its own).
            wa, wb = word_of.get(a), word_of.get(b)
            ta = (term_of.get(wa) if wa is not None else None) or (a if isinstance(a, str) and a in held_terms
                                                                   else None)
            tb = (term_of.get(wb) if wb is not None else None) or (b if isinstance(b, str) and b in held_terms
                                                                   else None)
            if ta is None or tb is None:
                return None
            if ta == tb:
                # The two words say one thing ("It's a trap.": the trap is it).
                return ["same"]
            return between.get((ta, tb), []) + ["~" + r for r in between.get((tb, ta), [])]
        # WHETHER WHAT A VERB'S CLAUSE SAYS IS TOLD AS SO: "Tom knows that the dog barked." tells the barking; "Tom
        # said that the dog barked." does not (`unasserted`).
        for p in pieces:
            if p[0] != "clause":
                continue
            verb = kinds_of.get(p[1])
            inner = term_of.get(word_of.get(p[2])) if word_of.get(p[2]) is not None else None
            if verb is None or inner is None:
                continue
            of_it = [f for f in meaning.facts if f.subject == inner]
            if of_it:
                count("clause", (verb[2],), "unasserted" if any(f.unasserted for f in of_it) else "asserted")
        # A VERB SAID AS A LINK: where the meaning gives a verb's word no happening ("Tom owns four books.":
        # `owns(tom, ...)`, no owning), the link it holds between two of its places is the verb's ("own": the subject
        # owns the object); where it gives it one, the verb says a happening.
        for p in pieces:
            if p[0] != "event":
                continue
            e, lemma, at = p[1], p[2], p[-1]
            if at in term_of:
                count("verb", (lemma,), "")
                continue
            places = [(q[3], q[2]) for q in pieces if q[0] == "role" and q[1] == e]
            places += [("pp:" + q[3], q[2]) for q in pieces if q[0] == "prep" and q[1] == e]
            for one, a in places:
                for other, b in places:
                    if one != other:
                        got = said(a, b)
                        for r in got or ():
                            if not r.startswith("~") and r != "same":
                                count("verb", (lemma,), (one, other, r))
        for p in pieces:
            if (p[0] == "role" and p[1] in kinds_of and kinds_of[p[1]][-1] in placed) or (
                    p[0] == "prep" and p[1] not in holders
                    and placed.intersection(range(p[-1], ends.get(p[-1], p[-1] + 1)))):
                # This verb's places, this preposition's link: learned from the derivation (`_learn_places_derived`).
                continue
            if p[0] == "role":
                _, e, x, slot, *_ = p
                got = said(e, x)
                verb = kinds_of.get(e)
                if got is None or verb is None:
                    continue
                count("role", (verb[2], slot), got[0] if got else "")
            elif p[0] == "prep" and p[1] in holders:
                got = said(holders[p[1]], p[2])
                if got is not None:
                    count("holder", (p[3],), got[0] if got else "")
            elif p[0] == "prep":
                _, a, b, word, *_ = p
                got = said(a, b)
                if got is None:
                    continue
                kind = "event" if a in kinds_of and kinds_of[a][0] == "event" else "thing"
                time = self.lexicon.time_of(b) or (
                    self.lexicon.time_of(kinds_of[b][2]) if b in kinds_of else None) or "-"
                count("prep", (word, kind, time), got[0] if got else "")
                for what in _what_is(b, things, pieces, self.lexicon.words):
                    count("prep_to", (word, kind, what), got[0] if got else "")
                head = kinds_of.get(a)
                if head is not None:
                    count("prep_of", (head[2], word, time), got[0] if got else "")
            elif p[0] == "holder":
                _, x, b, word, *_ = p
                got = said(x, b)
                if got is not None:
                    count("holder", (word,), got[0] if got else "")
            elif p[0] == "poss":
                _, x, owner, *_ = p
                got = said(x, owner)
                thing = kinds_of.get(x)
                if got is not None and thing is not None:
                    count("poss", (thing[2],), got[0] if got else "")
            elif p[0] == "be":
                got = said(p[1], p[2])
                if got is None:
                    continue
                given = {q[1] for q in pieces if q[0] == "given"}
                asked = [q[1] for q in pieces if q[0] == "asked"]
                way = ("equals" if any(r in ("equals", "~equals") for r in got) else
                       "merge" if any(r in ("isa", "instance_of", "same") for r in got) else "")
                count("be", _be_key(pieces, p, given, asked), way)
            elif p[0] == "quality" and p[3] not in timed and p[3] not in graded:
                # What a quality said of a thing says: that it has it ("a red ball"), or another link ("a British
                # novelist": one from Britain), learned for the adjective and for what memory holds it to be of.
                got = said(p[1], p[3])
                if got is None:
                    continue
                link = got[0] if got else ""
                count("quality", (p[2],), link)
                for kind in self.lexicon.words.kinds(p[2], "ADJECTIVE")[:3]:
                    count("quality", (kind,), link)
            elif p[0] == "adv":
                _, e, name, *_ = p
                w = p[-1]
                t = term_of.get(w)
                te = term_of.get(word_of.get(e)) if word_of.get(e) is not None else None
                if te is None:
                    continue
                got = [r for r in between.get((te, t), [])] if t else []
                count("adv", (name,), got[0] if got else "")
        return True


    def _learn_places_derived(self, tokens: Sequence[str], meaning: Meaning, words: Mapping[str, Sequence[int]],
                              derived: Sequence[Derived], text: str,
                              counted: Optional[List[Tuple[str, Tuple, str]]]) -> Set[int]:
        """A VERB'S PLACES AND A PREPOSITION'S LINKS, FROM THE SENTENCE AS IT WAS DERIVED BY HAND, each link as its
        taught meaning says it: for each verb (named so, `Lexicon.uses_derived`), the word it took for each of its
        places (`_taken_in`), the place as the grammar's entry for the verb's category names it (subject, object,
        second, passive), counted as `learn` counts a reading's (`role`); for each preposition telling of a doing or a
        thing, what it tells of and what it takes (`prep`, `prep_to`, `prep_of`). A verb whose phrase the derivation
        composed, or one taking things joined by "and", is not counted. Returns the words, by their place among
        `tokens`, whose places and links were counted: the reading learns the rest."""
        lexicon, held_words = self.lexicon, self.lexicon.words
        spans = _offsets(text, tokens)
        term_of: Dict[int, str] = {}
        for t, ws in words.items():
            for w in ws:
                term_of.setdefault(w, t)
        held_terms = {t for f in meaning.facts for t in f.terms()}
        kinds_said = {f.subject: f.obj for f in meaning.facts if f.relation == "instance_of"}
        between: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for f in meaning.facts:
            between[(f.subject, f.obj)].append(f.relation)

        def count(table: str, key: Tuple, link: str) -> None:
            lexicon.learned[table][key][link] += 1
            if counted is not None:
                counted.append((table, key, link))
        placed: Set[int] = set()
        for d in derived:
            start = text.find(d.text)
            if start < 0:
                continue
            named = lexicon.uses_derived(d)

            def token(k: int) -> Optional[int]:
                a, b = d.spans[k]
                return next((i for i, sp in enumerate(spans) if sp and start + a <= sp[0] and sp[1] <= start + b),
                            None)
            took, composed = _taken_in(d)
            taker = {w: h for h, ws in took.items() for w in ws}

            def term(k: int) -> Optional[str]:
                """The meaning's term the derivation's word says: by where it is, or a name the meaning holds as
                written."""
                a, b = d.spans[k]
                for i, sp in enumerate(spans):
                    if sp and start + a <= sp[0] and sp[1] <= start + b and i in term_of:
                        return term_of[i]
                name = d.words[k].replace("~", " ").lower()
                return name if name in held_terms else None

            def said(a: Optional[str], b: Optional[str]) -> Optional[str]:
                if a is None or b is None:
                    return None
                if a == b:
                    return "same"
                got = between.get((a, b), []) + ["~" + r for r in between.get((b, a), [])]
                return got[0] if got else ""

            def name_of(k: int) -> str:
                use = named[k][0] if named[k] else ""
                cls = "VERB" if use == "VERB" else "NOUN" if use.startswith("NOUN") else ""
                return held_words.name(d.words[k], cls) if cls else d.words[k].replace("~", " ").lower()

            def what_is(k: int, t: Optional[str]) -> List[str]:
                """As `_what_is` says it of a reading's term."""
                use = named[k][0] if named[k] else ""
                if use.startswith("NOUN"):
                    name = name_of(k)
                    return [name] + held_words.kinds(name, "NOUN")
                if t in ("?speaker", "?listener"):
                    return ["person"]
                if use == "pron":
                    return ["person"] if _pronoun_kind(d.words[k]) == "person" else []
                if t is None or is_variable(t) or _number(t) is not None:
                    return []
                return held_words.kinds(t, "NOUN") + [NAMED]
            for k, got in enumerate(named):
                if not got:
                    continue
                use, frame = got
                if use == "VERB" and k not in composed and token(k) is not None:
                    if self._places_derived(d, k, frame, took.get(k, []), term, said, name_of, count):
                        placed.add(token(k))
                elif use in ("PREPOSITION", "PREPOSITION:thing"):
                    what = took.get(k, [])
                    if not what:
                        continue
                    # What it takes, then what it tells of; a phrase a word takes ("gave it to Mary", "my uncle in
                    # Paris") tells of the word that took it.
                    thing = what[0]
                    head = what[1] if len(what) > 1 else taker.get(k)
                    if head is None or not named[head]:
                        continue
                    link = said(term(head), term(thing))
                    if link is None:
                        continue
                    kind = "event" if named[head][0] == "VERB" else "thing"
                    t = term(thing)
                    time = lexicon.time_of(t) or lexicon.time_of(
                        kinds_said.get(t) if t is not None and is_variable(t) else name_of(thing)) or "-"
                    word = d.words[k].lower()
                    count("prep", (word, kind, time), link)
                    for kind_of in what_is(thing, t):
                        count("prep_to", (word, kind, kind_of), link)
                    if named[head][0] == "VERB" or named[head][0].startswith("NOUN"):
                        count("prep_of", (name_of(head), word, time), link)
                    if token(k) is not None:
                        placed.add(token(k))
        return placed

    def _places_derived(self, d: Derived, k: int, frame: str, took: Sequence[int], term, said, name_of, count) -> bool:
        """A verb's places as the derivation fills them (`_learn_places_derived`): what it took, in order, beside
        what its category takes, a preposition's phrase and a particle aside, each the place the grammar's entry for
        its category names. Returns whether they were counted."""
        lexicon = self.lexicon
        try:
            category = bank_category(d.categories[k])
        except (ValueError, IndexError):
            return False
        taken: List[Cat] = []
        c = category
        while isinstance(c, Fn):
            taken.append(c.arg)
            c = c.res
        if len(taken) != len(took):
            return False
        fillers = [w for a, w in zip(taken, took) if not (isinstance(a, Atom) and a.base in ("PP", "PR"))]
        said_so = _without_taken(_there(category))
        template = None
        for way in [said_so] + [w for w in [_clause_taken(said_so)] if w is not None]:
            template = next((t for form, frames in lexicon.verb_templates.items() if form != "frames"
                             for fr, ts in frames.items() if fr == frame for t in ts
                             if _alike(way, lexicon._category(t["cat"]))), None)
            if template is not None:
                break
        if template is None:
            return False
        slots = {p[2]: p[3] for p in template.get("sem", ()) if p[0] == "role"}
        refs: List[Optional[str]] = []
        c = lexicon._category(template["cat"])
        while isinstance(c, Fn):
            arg = c.arg
            while isinstance(arg, Fn):
                arg = arg.res
            refs.append(arg.ref)
            c = c.res
        if len(refs) != len(fillers):
            return False
        verb = name_of(k)
        particle = next((w for a, w in zip(taken, took) if isinstance(a, Atom) and a.base == "PR"), None)
        if particle is not None:
            # A verb and its particle are one verb, named as memory knows them together ("stepped out": step out).
            verb = lexicon.words.known_verb([verb, d.words[particle].lower()]) or verb
        e = term(k)
        for ref, filler in zip(refs, fillers):
            slot = slots.get(ref)
            link = said(e, term(filler))
            if slot and link is not None:
                count("role", (verb, slot), link)
        return True

    def unlearn(self, counted: Iterable[Tuple[str, Tuple, str]]) -> None:
        """Take back counts `learn` made (a sentence taught again corrected)."""
        learned = self.lexicon.learned
        for table, key, link in counted:
            held = learned[table].get(key)
            if held is not None and held[link] > 0:
                held[link] -= 1
                if held[link] <= 0:
                    del held[link]
                if not held:
                    del learned[table][key]


def _verb_phrase(cat: Cat) -> bool:
    return isinstance(cat, Fn) and cat.slash == "\\" and isinstance(cat.res, Atom) and cat.res.base == "S" \
        and isinstance(cat.arg, Atom) and cat.arg.base == "NP"


def _takes_object(cat: Cat) -> bool:
    """WHETHER THE CATEGORY TAKES A NOUN PHRASE AFTER IT AS SOMETHING OTHER THAN ITS SUBJECT: it takes one to the
    right AND still has its subject to come, as `(S[dcl]\\NP)/NP` does ("misled" before what was misled) and
    `((S[dcl]\\NP)/NP)/NP` twice over.

    Taking a noun phrase to the right is not enough to make it an object: a question asked with the copula takes its
    SUBJECT that way (`(S[q].p/NP.y)/NP.x`, "Is Tom a student?"), and a determiner of a name takes one too
    (`NP.x/NP.x`). What tells them apart is whether a subject is still outstanding, so the first noun phrase a
    question takes is not weighed as an object and the second is not weighed at all."""
    return isinstance(cat, Fn) and cat.slash == "/" and isinstance(cat.arg, Atom) and cat.arg.base == "NP" \
        and (_verb_phrase(cat.res) or _takes_object(cat.res))


def _after_its_subject(cat: Cat) -> bool:
    """WHETHER THE CATEGORY TAKES A THING TO THE RIGHT IN A PLACE THAT IS NOT ITS SUBJECT: it takes one and either
    still has its subject to come (`_takes_object`), or has taken it already, what is left being a sentence -- a
    subject raised and composed with its verb leaves `S/NP`, where the thing taken next is the object and the
    subject is nowhere in the category any more. Asked of `_takes_object` alone, the rule asked of a thing standing
    after a verb never reached a sentence built that way, as the weighing of such a subject never did before it."""
    return _takes_object(cat) or (isinstance(cat, Fn) and cat.slash == "/" and isinstance(cat.arg, Atom)
                                  and cat.arg.base == "NP" and isinstance(cat.res, Atom) and cat.res.base == "S")


def _raised_subject(cat: Cat) -> bool:
    """WHETHER THE CATEGORY IS A SUBJECT ALREADY RAISED to what is said of it, `S/(S\\NP)`: how the grammar states the
    words that deny ("nothing", "nobody", "none"), which take their verb's phrase rather than being taken by it.
    The sentence is the same sentence either way, but the rule that joins it is forward application, not backward,
    so every weighing that asks for a subject and a verb must ask this as well as `_verb_phrase`."""
    return isinstance(cat, Fn) and cat.slash == "/" and isinstance(cat.res, Atom) and cat.res.base == "S" \
        and _verb_phrase(cat.arg)


def _subject_ref(cat: Cat) -> Optional[Term]:
    """THE TERM OF THE THING STANDING AS A SUBJECT: its own, or, where the subject is already raised, the term of the
    place it leaves open for itself, which is not the term of the sentence it makes (`_raised_subject`). None where
    the category is neither."""
    if _raised_subject(cat):
        return cat.arg.arg.ref
    return cat.ref if isinstance(cat, Atom) else None


def _hook(cat: Cat) -> Optional[Term]:
    while isinstance(cat, Fn):
        cat = cat.res
    return cat.ref


def _whole(cat: Cat) -> Optional[str]:
    if isinstance(cat, Atom):
        if cat.base == "S" and not isinstance(cat.feat, str):
            return WHOLE["S"]
        return WHOLE.get(cat.base + (f"[{cat.feat}]" if isinstance(cat.feat, str) and cat.base == "S" else ""))
    if isinstance(cat, Fn) and cat.slash == "\\" and isinstance(cat.res, Atom) and cat.res.base == "S" \
            and cat.res.feat == "b" and isinstance(cat.arg, Atom) and cat.arg.base == "NP":
        return "order"
    return None


def _ordered(cat: Cat) -> bool:
    """Whether a reading of the whole is an order: a doing asked of the listener ("Close the door.", `S[b]\\NP`), or
    said to someone named ("Come here, Rex.", `S[imp]`)."""
    return _whole(cat) == "order" or (isinstance(cat, Atom) and cat.base == "S" and cat.feat == "imp")


def _rank(cat: Cat) -> int:
    """Of two readings as sure, a sentence before a thing said alone.

    AN ORDER IS A SENTENCE: a doing asked of the listener, its doer unsaid ("Look up photosynthesis.", `S[b]\\NP`,
    `_whole`). Ranked with what is said alone, any reading as a telling came first however its words are used:
    "up" taken as a verb, "Look up photosynthesis." told of someone named Look upping photosynthesis, and "Contact
    Dana." was the phrase "Contact Dana", a contact (lyric_dev, 2026-10-24). Between a telling and an order, how
    the words are used decides."""
    if (isinstance(cat, Atom) and cat.base == "S") or _whole(cat) == "order":
        return 2
    return 1 if isinstance(cat, Fn) else 0


def _words_of_terms(pieces: Iterable[Piece]) -> Dict[Term, int]:
    """The word saying each term: the word whose meaning names its kind, or the name it is."""
    out: Dict[Term, int] = {}
    for p in pieces:
        if p[0] in ("kind", "event", "quality"):
            out.setdefault(p[1] if p[0] != "quality" else p[3], p[-1])
    for p in pieces:
        if p[0] == "word" and p[2] in ("NAME", "NUMERAL"):
            out.setdefault(p[1], p[3])
        if p[0] in ("pron", "speaker", "asked"):
            out.setdefault(p[1], p[-1])
    return out


# ── spelling a reading out in the meaning language ────────────────────────────────────────────────────────────────

def spell_out(lexicon: Lexicon, sign: Sign, tokens: Sequence[str], reading: Reading) -> Optional[Meaning]:
    """The meaning of a reading of the whole, in the meaning language (`docs/TEACHING.md`): each piece of each word's
    meaning said with the terms its places were filled by. Raises ValueError where the meaning language cannot say
    it (a word whose meaning it has no words for yet)."""
    pieces = list(sign.pieces)
    words = lexicon.words
    cat = sign.cat
    # A bare verb said alone is an order to the listener ("Add three spoonfuls of white wine.").
    if isinstance(cat, Fn):
        s: Dict[int, Term] = {}
        _bind(cat.arg.ref, "?listener", s)
        pieces = list(_substitute(pieces, s))
    gaps = [p for p in pieces if p[0] == "gap"]
    if gaps:
        raise ValueError("the meaning language has no words yet for " + ", ".join(sorted({str(p[1]) for p in gaps})))
    closing = next((p[1] for p in pieces if p[0] == "closing"), ".")
    act = "ask" if (_whole(cat) == "ask" or closing == "?") else "tell"

    events: Dict[Term, Piece] = {}
    kinds: Dict[Term, Piece] = {}
    given: Set[Term] = set()
    asked: List[Term] = []
    denied: Set[Term] = set()
    times: Dict[Term, str] = {}
    degrees: Dict[Term, List[Piece]] = defaultdict(list)
    groups: Dict[Term, str] = {}
    for p in pieces:
        what = p[0]
        if what == "event":
            events.setdefault(p[1], p)
        elif what == "kind":
            kinds.setdefault(p[1], p)
        elif what == "given":
            given.add(p[1])
        elif what == "asked" and p[1] not in asked:
            asked.append(p[1])
        elif what == "deny":
            denied.add(p[1])
        elif what in ("past", "future", "now"):
            times.setdefault(p[1], what)
        elif what == "degree":
            degrees[p[1]].append(p)
        elif what == "group":
            groups[p[1]] = p[2]
    # "No one", "no money": the doing or having the thing is in is what is denied.
    for p in pieces:
        if p[0] == "deny_arg":
            for q in pieces:
                if q[0] == "role" and q[2] == p[1]:
                    denied.add(q[1])
                elif q[0] in ("fact", "be") and p[1] in q[1:4]:
                    denied.add(q[-2] if q[0] == "fact" else q[3])
    # WHAT A THING IS SAID NOT TO BE, ITS QUALITIES WITH IT: "Edison was not a bright student." is no student and not
    # bright, as the PMB's gold says it; said of Edison once the student was Edison, he was said to be bright.
    for p in pieces:
        if p[0] == "be" and p[3] in denied:
            denied.update(q[3] for q in pieces if q[0] == "quality" and q[1] == p[2])

    # WHOM A PRONOUN STANDS FOR. "his", "her", "its", "their" before a thing are the nearest one before them that
    # they may be ("Tom unbuttoned his shirt": Tom's; "The man robbed her of her bag": hers); a pronoun nothing
    # before it may be is the one spoken of before, and that is one: a second ("He fixed it.") is a thing not named.
    order: List[Tuple[int, Term, str]] = []
    for p in pieces:
        if p[0] == "kind":
            order.append((p[-1], p[1], "person" if words.is_person(p[2]) else "thing"))
        elif p[0] == "word" and p[2] == "NAME":
            order.append((p[3], p[1], "person"))
        elif p[0] == "pron":
            order.append((p[-1], p[1], _pronoun_kind(p[2])))
        elif p[0] == "fact" and p[1] == "has_member" and len(p) > 3 and p[3] in ("?speaker", "?listener"):
            # A GROUP THE SPEAKER OR THE LISTENER IS ONE OF IS A THING THE SENTENCE HAS NAMED ("we", "us", "you"),
            # so a pronoun of its own sentence may stand for it. Named by no kind word, no name and no pronoun, it
            # was in nothing this search could find, "ourselves" was bound to nothing, and "We misled ourselves."
            # read as no sentence at all once the mark was stated for it (lyric_db, 2026-10-30).
            order.append((p[-1], p[2], "person"))
    order.sort(key=lambda o: o[0])
    names: Dict[Term, Term] = {}
    previous_taken = False
    for p in sorted((p for p in pieces if p[0] == "pron"), key=lambda p: p[-1]):
        x, word, own, at = p[1], p[2], p[3] == "own", p[-1]
        want = _pronoun_kind(word)
        found = None
        if own:
            for w, t, k in reversed(order):
                if w < at and t != x and (want == "any" or k == want):
                    found = t
                    break
        if found is not None:
            names[x] = names.get(found, found)
        elif own and type(x) is int:
            # A PRONOUN OF ITS OWN SENTENCE SAYS A THING STANDING BEFORE IT IN THAT SENTENCE, so where nothing does
            # there is no sentence to read: "Themselves are intelligent." took the one spoken of before, as a
            # pronoun of another sentence does, and read as surely as "They are intelligent." -- and saying, which
            # keeps what reads back to the meaning, was then free to say it (lyric_db, 2026-10-30). A thing its
            # category fixes ("myself", the speaker) is bound to nothing and needs nothing standing before it: the
            # mark says which form stands where, and the thing is already the one the sentence says.
            return None
        elif not previous_taken:
            names[x] = "?previous"
            previous_taken = True
    if names:
        s: Dict[int, Term] = {}
        for x, t in names.items():
            _bind(x, t, s)
        pieces = list(_substitute(pieces, s))
        events = {_walk(k, s): _substitute([v], s)[0] for k, v in events.items()}
        kinds = {_walk(k, s): _substitute([v], s)[0] for k, v in kinds.items()}
        given = {_walk(k, s) for k in given}
        asked = [_walk(k, s) for k in asked]
        denied = {_walk(k, s) for k in denied}
        times = {_walk(k, s): v for k, v in times.items()}
        degrees = {_walk(k, s): _substitute(v, s) for k, v in degrees.items()}
        groups = {_walk(k, s): v for k, v in groups.items()}

    # WHAT IS SAID OF A KIND. A thing said with "every" or "all", and one said bare in the plural ("Whales") or with
    # "a" ("A robin") as what a sentence's own statement in the present tells of (its finite verb's subject: "Whales
    # are mammals.", "A robin is a bird.", "Birds can fly."; never "five failed attempts"), is the kind itself (`docs/TEACHING.md`: `isa(robin, bird)`, `capable_of(bird, fly)`); in
    # the past ("Farmers rebelled.") or going on now ("A typhoon is approaching.") it is some of the kind.
    # The sentence's own statements: what its whole says, what is joined to it, and each sentence told after
    # another; never a clause telling of a thing ("a function that is applied ...").
    mains = {_walk(_hook(cat), {})} | {p[1] for p in pieces if p[0] == "main"}
    for p in pieces:
        if p[0] == "both" and p[1] in mains:
            mains.add(p[2])
    every = {p[1] for p in pieces if p[0] == "every"}
    # "SOME" IS SOME OF THE KIND, NEVER THE KIND (the Parallel Meaning Bank writes "some" as "a": a thing of the kind,
    # "I want some potatoes.", "Tom put some rice in a bowl."; never a kind told of, as "a" may say one: "A dog barks."
    # is dogs, "Some dogs bark." some of them). With nothing of its own, "some" read and was said as nothing.
    loose = {p[1] for p in pieces if p[0] in ("indefinite", "bare")} - {p[1] for p in pieces if p[0] == "some"}
    finite = {p[1] for p in pieces if p[0] == "finite"}
    subjects: Dict[Term, List[Term]] = defaultdict(list)
    for p in pieces:
        if p[0] == "role" and p[3] == "subject":
            subjects[p[2]].append(p[1])
        elif p[0] in ("be", "quality"):
            subjects[p[1]].append(p[3])
        elif p[0] == "can":
            subjects[p[2]].append(p[1])
        elif p[0] == "prep" and len(p) > 5 and p[4] != "-":
            # "A wheel is part of a car.": what a place said of a thing tells of it.
            subjects[p[1]].append(p[4])
    kind_of: Dict[Term, Term] = {}
    for x, said_of in subjects.items():
        if x in kinds and isinstance(x, int) and x not in given and any(
                said in finite and said in mains and (x in every or (x in loose and times.get(said) is None))
                for said in said_of):
            kind_of[x] = kinds[x][2]
    # A KIND SAID WITH WHAT PICKS SOME OF IT OUT ("Every prime number greater than 2 is odd.", "Big dogs bark.") is
    # not the kind: what is said holds of each one that is of the kind and is so, said as what must hold (as an
    # "if" says it). Said of the kind, every prime number was told odd, 2 among them.
    finite_at = {p[1]: p[-1] for p in pieces if p[0] == "finite"}
    picked: List[Tuple[int, int]] = []
    for x in list(kind_of):
        at_verb = min((finite_at[said] for said in subjects[x] if said in finite_at and said in mains), default=None)
        if at_verb is None:
            continue
        before = [p[-1] for p in pieces if p[0] not in ("kind", "every", "indefinite", "bare", "word", "given",
                                                          "finite", "closing", "det")
                  and x in p[1:-1] and isinstance(p[-1], int) and p[-1] < min(at_verb, FIRST_VARIABLE)]
        if before:
            picked.append((min(before + [kinds[x][-1]]), at_verb))
            del kind_of[x]
    generic_be: Set[Term] = set()
    if kind_of:
        for p in pieces:
            if p[0] == "be" and p[1] in kind_of:
                generic_be.add(p[2])
        s = {}
        for x, k in kind_of.items():
            _bind(x, k, s)
        pieces = [p for p in _substitute(pieces, s) if not (p[0] == "kind" and isinstance(p[1], str)
                                                            and p[1] in kind_of.values())]
        kinds = {k: v for k, v in kinds.items() if k not in kind_of}
        subjects = defaultdict(list, {_walk(k, s): v for k, v in subjects.items()})
    # A VERB SAID AS A LINK between two of its places, as the sentences taught say it ("Tom owns four books.":
    # `owns(tom, ...)`; "The cat needs milk.": `requires`): its happening is not said.
    as_link: Dict[Term, Tuple[str, str, str]] = {}
    for e, p in events.items():
        held = lexicon.learned["verb"].get((p[2],))
        if held:
            said_as = held.most_common(1)[0][0]
            if said_as:
                as_link[e] = said_as
    # "Birds can fly.": what a thing can do is said of it (`capable_of(bird, fly)`); "You can open the box." a doing
    # allowed.
    able: Dict[Term, Term] = {p[1]: p[2] for p in pieces if p[0] == "can"}
    may: Dict[Term, Term] = {p[1]: p[2] for p in pieces if p[0] == "may"}
    # WHAT IS ASKED OF THE LISTENER IS A REQUEST: an order ("Close the door."), "please", and a question asking
    # whether the listener could, would or can do it ("Could you open the box?"), whose "could" says no possibility.
    polite = {p[1] for p in pieces if p[0] == "polite" and p[2] == "?listener"}
    if _whole(cat) == "order" or (isinstance(cat, Atom) and cat.feat == "imp") or (
            polite and (act == "ask" or any(p[0] == "polite" and p[1] == _hook(cat) for p in pieces))):
        act = "request"
        for e in polite:
            able.pop(e, None)
            may.pop(e, None)
        pieces = [p for p in pieces if not (p[0] == "fact" and p[1] == "has_property" and p[2] in polite
                                            and p[3] in ("possible", "hypothetical"))]
    alone_able = {e for e in able if not any(q[0] == "role" and q[1] == e and q[3] != "subject" for q in pieces)
                  and not any(q[0] in ("prep", "adv") and q[1] == e for q in pieces)}
    # WHAT AN "IF" SAYS MUST HOLD: every fact of the clause it takes is the condition ("If the valve is closed, the
    # tank is full.": the valve and its being closed).
    conditions = _argument_spans(sign, ("if",)) + picked
    # "ANY" IS SOME ONE OF A KIND ONLY WHERE A DENIAL, A QUESTION OR AN "IF" TAKES IT (Ladusaw 1979; the Parallel
    # Meaning Bank writes "Tom didn't break any laws." a law not broken, "Are you allergic to any plants?" a plant
    # asked of): there it is read as a thing of the kind, as "a" is. Told with nothing of these ("Roy fastened the
    # medal with any pin."), it says every one of the kind will do, which the meaning language has no words for yet.
    # Read as "a" there, it was said for "a" (lyric_dev2, 2026-10-28).
    for p in pieces:
        if p[0] == "npi" and act != "ask" and not denied and not any(q[0] in ("deny", "deny_arg") for q in pieces) \
                and not any(start <= p[-1] < end for start, end in conditions):
            raise ValueError("the meaning language has no words yet for any said where nothing denies, asks or "
                             "supposes")
    # WHAT A CLAUSE A VERB TAKES SAYS is told as so or not, as the verb was learned to tell it ("knows that": so;
    # "said that": not); WHAT "OR" JOINS are alternatives.
    unasserted: List[Tuple[int, int]] = []
    for at_verb, span in _clause_spans(sign):
        verb = next((p for p in pieces if p[0] == "event" and p[-1] == at_verb), None)
        if verb is not None:
            told, _ = lexicon.link("clause", (verb[2],), "asserted")
            if told == "unasserted":
                unasserted.append(span)
    alternatives = [(p[1], p[2]) for p in pieces if p[0] == "alternatives"] + \
        [(p[3], p[4]) for p in pieces if p[0] == "alternatives"]
    unasserted += [(p[1], p[2]) for p in pieces if p[0] == "untold"]
    as_link_unfilled: Set[Term] = set()

    facts: List[MeaningFact] = []
    decided = reading.decided
    counter = [0]

    def fresh() -> int:
        counter[0] += 1
        return -counter[0]

    def term(t: Term) -> str:
        if isinstance(t, int):
            return f"?x{t}" if t >= 0 else f"?y{-t}"
        return t

    def add(relation: Optional[str], a: Term, b: Term, positive: bool = True, given_: bool = False,
            at: int = -1) -> Optional[MeaningFact]:
        if relation == "same":
            return None
        if relation and relation.startswith("~"):
            relation, a, b = relation[1:], b, a
        if not relation or a == b:
            return None
        condition = any(start <= at < end for start, end in conditions)
        either = any(start <= at < end for start, end in alternatives)
        untold = any(start <= at < end for start, end in unasserted)
        try:
            fact = MeaningFact(relation, term(a), term(b), positive, condition=condition, alternative=either,
                               unasserted=untold, given=given_)
        except ValueError:
            return None
        if fact not in facts:
            facts.append(fact)
        return fact
    # Groups made by joining, inside one another ("Ken, Bill and Yumi"), are one group.
    member_of: Dict[Term, Term] = {}
    for p in pieces:
        if p[0] == "member" and p[2] in groups and p[1] in groups:
            member_of[p[2]] = p[1]

    def group_of(g: Term) -> Term:
        while g in member_of:
            g = member_of[g]
        return g
    # What a happening and a thing are.
    for e, (one, other, relation) in as_link.items():
        filled = {q[3]: q[2] for q in pieces if q[0] == "role" and q[1] == e}
        filled.update({"pp:" + q[3]: q[2] for q in pieces if q[0] == "prep" and q[1] == e})
        if one in filled and other in filled:
            decided.append(("verb", events[e][2], "own", add(relation, filled[one], filled[other],
                                                              positive=e not in denied, at=events[e][-1])))
        else:
            as_link_unfilled.add(e)
    for e in as_link_unfilled:
        as_link.pop(e, None)
    meant_of: Dict[Term, str] = {}
    for e, p in events.items():
        at = p[-1]
        if e in as_link:
            continue
        if e in alone_able:
            add("capable_of", able[e], p[2], positive=e not in denied, at=at)
            continue
        filled = {q[3]: (kinds[q[2]][2] if q[2] in kinds else q[2] if isinstance(q[2], str) else "")
                  for q in pieces if q[0] == "role" and q[1] == e and q[3] in ("subject", "object", "passive")}
        if "passive" in filled:
            filled["object"] = filled.pop("passive")
        meant = lexicon.sense_of(p[2], filled)
        meant_of[e] = meant
        if meant != p[2]:
            decided.append(("sense", p[2], "seen", None))
        add("instance_of", e, meant, at=at)
        if e in able:
            add("has_property", e, "allowed", at=at)
        if e in may:
            add("has_property", e, "allowed" if may[e] == "?listener" else "possible", at=at)
        when = times.get(e)
        if when == "past":
            add("precedes", e, "?now", at=at)
        elif when == "future":
            add("follows", e, "?now", at=at)
        elif when == "now":
            add("during", e, "?now", at=at)
        if e in denied:
            add("has_property", e, "false", at=at)
    # A KIND OF A KIND: "this kind of apple", "What kind of flowers": the thing is a kind of apple, the apple the kind
    # said, no apple of its own and no "kind" (the PMB's `InstanceOf`: "kind of", "kinds of", "sort of", "sorts of", 47
    # times). Read as a noun and "of", a kind and an apple were two things, the one a kind of the other.
    subkinds = {p[1] for p in pieces if p[0] == "subkind"}
    for x, p in kinds.items():
        if x in events:
            continue
        if x in subkinds and not isinstance(x, str):
            add("isa", x, p[2], at=p[-1])
            continue
        if isinstance(x, str):
            if not x.startswith("?") and x not in kind_of.values() and _number(x) is None:
                # "the function sorted": what the named one is (`isa(sorted, function)`).
                add("isa", x, p[2], at=p[-1])
            continue
        around = [q[2] for y, q in kinds.items() if y != x and y not in events and isinstance(q[2], str)]
        meant = lexicon.thing_sense_of(p[2], around)
        if meant != p[2]:
            decided.append(("sense", p[2], "around", None))
        add("instance_of", x, meant, given_=x in given and isinstance(x, int), at=p[-1])
        # ANOTHER OF A KIND is one of it that is not one given (Heim 1982, Kamp and Reyle 1993; the Parallel Meaning
        # Bank writes "another woman" a woman not the same as a woman, `NEQ`): "Tom chased another cat." is a cat
        # chased, a cat known, the two not one. Saying nothing, "another" was read as "a", and "A wall is another
        # artifact." said of a wall being an artifact (lyric_dev2, 2026-10-28).
        for q in pieces:
            if q[0] == "other" and q[1] == x:
                known = fresh()
                add("instance_of", known, meant, given_=True, at=q[-1])
                add("equals", x, known, positive=False, at=q[-1])
    def numeric(t: Term) -> bool:
        """Whether a term is a number, or one of a kind of number."""
        kind = kinds[t][2] if t in kinds else t if isinstance(t, str) and t in kind_of.values() else None
        return _number(str(t)) is not None or (kind is not None and "number" in [kind] + words.kinds(kind, "NOUN"))
    bes: List[Piece] = [p for p in pieces if p[0] == "be"]
    holders: Dict[Term, Term] = {p[3]: p[1] for p in pieces if p[0] == "quality"}
    holders.update({p[3]: p[1] for p in bes})
    merged: Dict[Term, Term] = {}

    def timed(b: Term) -> bool:
        return bool(lexicon.time_of(b) or (lexicon.time_of(kinds[b][2]) if b in kinds else None))

    def places_of(e: Term) -> List[str]:
        """The places a happening's verb is said with, as its frames name them (`Lexicon.framed`): its subject,
        objects, and each preposition after it that says no time."""
        return [q[3] for q in pieces if q[0] == "role" and q[1] == e and (q[3] in ("subject", "object", "second")
                                                                          or q[3].startswith("pp:"))] + \
            ["pp:" + q[3] for q in pieces if q[0] == "prep" and q[1] == e and q[3] and not timed(q[2])]
    for p in pieces:
        what = p[0]
        at = p[-1] if isinstance(p[-1], int) and p[-1] < FIRST_VARIABLE else -1
        if what == "role":
            _, e, x, slot = p[:4]
            verb = events.get(e)
            if verb is None or e in alone_able or e in as_link:
                continue
            if isinstance(x, int) and x in kinds and kinds[x][0] == "quality":
                continue
            default = lexicon.linking.get(slot)
            if slot.startswith("pp:"):
                default = worded(slot[3:]) if slot[3:].isalpha() else None
            got, how = lexicon.inherited("role", verb[2], "VERB", (slot,), default)
            if slot == "by":
                got, how = lexicon.inherited("role", verb[2], "VERB", ("subject",), lexicon.linking.get("subject"))
            elif (slot in ("subject", "object", "second") or slot.startswith("pp:")) \
                    and not lexicon.taught_role(verb[2], slot):
                # WHAT THE PLACE IS BY THE PLACES SAID WITH IT, as the verb's frames say (`Lexicon.framed`), where
                # no sentence taught said what it is: "Our colleague's mother passed away." is a passing away done
                # to her (`die-42.4-1`: "NP:Patient V").
                framed = lexicon.framed(verb[2], meant_of.get(e, ""), places_of(e), slot, got)
                if framed is not None:
                    got, how = framed, "frame"
            decided.append(("role", f"{verb[2]}:{slot}", how, add(got, e, x, at=at)))
        elif what == "prep" and p[1] in holders:
            # A preposition after a quality ("allergic to pollen") tells of who has it.
            _, a, b, word = p[:4]
            got, how = lexicon.link("holder", (word,), worded(word) if word.replace(" ", "").isalpha() else None)
            decided.append(("holder", word, how, add(got, holders[a], b, at=at)))
        elif what == "prep" and p[1] in as_link:
            continue
        elif what == "prep":
            _, a, b, word = p[:4]
            owner = p[4] if len(p) > 5 else None
            kind = "event" if a in events else "thing"
            time = lexicon.time_of(b) or (lexicon.time_of(kinds[b][2]) if b in kinds else None) or "-"
            head = events.get(a) or kinds.get(a)
            # A TIME SAID OF A DOING WITH NO PREPOSITION (`NP=>adjunct`, no word) says when it was, as the PMB's
            # meanings say a happening's time (`during`), where memory holds it a time; else only what taught
            # sentences said such a thing is to its doing ("a lot", "that way").
            default = (worded(word) if word.replace(" ", "").isalpha()
                       else "during" if not word and time != "-" else None)
            said, how_said = lexicon.link("prep", (word, kind, time), default)
            got, how = lexicon.selected("prep_to", (word, kind), _what_is(b, kinds, pieces, words), said)
            if how != "kind":
                how = how_said
            if head is not None:
                # What sentences said of this very doing or thing with the word ("arrived in": where to) decides
                # before what is said of the word with what its thing is: weighed against that, one sentence tied
                # and lost, and "landed on my windowsill" was where the robin landed, not where to.
                own, how_own = lexicon.link("prep_of", (head[2], word, time), None)
                if how_own == "own":
                    got, how = own, "own"
                elif a in events and time == "-" and word:
                    # What the verb's frames say of the preposition, by the places said with it ("collided with a
                    # truck": `Lexicon.framed`), before what is said of the word whatever its verb.
                    framed = lexicon.framed(head[2], meant_of.get(a, ""), places_of(a), "pp:" + word, got)
                    if framed is not None:
                        got, how = framed, "frame"
            decided.append(("prep", f"{word}:{kind}:{time}", how,
                            add(got, a, b, positive=not (owner is not None and owner in denied), at=at)))
        elif what == "holder":
            _, x, b, word = p[:4]
            got, how = lexicon.link("holder", (word,), worded(word) if word.replace(" ", "").isalpha() else None)
            decided.append(("holder", word, how, add(got, x, b, at=at)))
        elif what == "poss":
            _, x, owner = p[:3]
            thing = kinds.get(x)
            if thing is None:
                add(lexicon.linking.get("possessive"), x, owner, at=at)
                continue
            got, how = lexicon.inherited("poss", thing[2], "NOUN", (), lexicon.linking.get("possessive"))
            decided.append(("poss", thing[2], how, add(got, x, owner, at=at)))
        elif what == "adv":
            _, e, name = p[:3]
            got, how = lexicon.link("adv", (name,), lexicon.linking.get("adverb"))
            # "She runs very fast": a degree of the doing's quality, as "very smooth" is a quality's; each degree
            # word grades the nearest of the doing's adverbs after it.
            after = [d[-1] for d in pieces if d[0] == "adv" and d[1] == e]
            grading = [d[2] for d in degrees.get(e, ())
                       if min((a for a in after if a > d[-1]), default=None) == at]
            if got == "has_property" and grading:
                held = fresh()
                decided.append(("adv", name, how, add("has_degree", e, held, at=at)))
                add("instance_of", held, name, at=at)
                for d in grading:
                    add("has_property", held, d, at=at)
            else:
                decided.append(("adv", name, how, add(got, e, name, at=at) if got else None))
        elif what == "prop":
            _, x, name = p[:3]
            add("has_property", x, name, at=at)
        elif what == "quality":
            _, x, name, q = p[:4]
            asked_degree = next((d[2] for d in pieces if d[0] == "degree_asked" and d[1] == q), None)
            measured = [d[2] for d in pieces if d[0] == "measure" and d[1] == q]
            compared = next((d[2] for d in pieces if d[0] == "compared" and d[1] == q), None)
            than = [d[2] for d in pieces if d[0] == "than" and d[1] == q]
            if compared in ("more", "less") and than:
                # "Rex is more careful than Tom.": a degree of carefulness, Rex's, above Tom's (`exceeds`); a number
                # is above another itself ("Is two less than ten?": `exceeds(10, 2)`), and so is one of a kind of
                # number ("a natural number greater than 1": `exceeds(?x, 1)`).
                for y in than:
                    if numeric(x) and numeric(y):
                        a_, b_ = (x, y) if compared == "more" else (y, x)
                        add("exceeds", a_, b_, positive=q not in denied, at=at)
                        continue
                    mine, theirs = fresh(), fresh()
                    add("has_degree", x, mine, at=at)
                    add("instance_of", mine, name, at=at)
                    add("has_degree", y, theirs, at=at)
                    add("instance_of", theirs, name, at=at)
                    a_, b_ = (mine, theirs) if compared == "more" else (theirs, mine)
                    add("exceeds", a_, b_, positive=q not in denied, at=at)
            elif compared == "most" and x in kinds:
                # "the most careful boy", "the biggest city": its degree the greatest of its kind's.
                held = fresh()
                add("has_degree", x, held, at=at)
                add("instance_of", held, name, at=at)
                add("greatest_of", held, kinds[x][2], at=at)
            elif asked_degree is not None:
                # "How big is the dog?": a degree of bigness, the dog's, asked.
                add("has_degree", x, asked_degree, at=at)
                add("instance_of", asked_degree, name, at=at)
            elif measured:
                # "Tom is ten years old.": a degree of oldness, Tom's, measured ten years.
                held = fresh()
                add("has_degree", x, held, positive=q not in denied, at=at)
                add("instance_of", held, name, positive=q not in denied, at=at)
                for m in measured:
                    add("has_measure", held, m, positive=q not in denied, at=at)
            elif q in degrees:
                for d in degrees[q]:
                    held = fresh()
                    add("has_degree", x, held, positive=q not in denied, at=at)
                    add("instance_of", held, name, positive=q not in denied, at=at)
                    add("has_property", held, d[2], positive=q not in denied, at=at)
            elif times.get(q) == "past":
                state = fresh()
                add("instance_of", state, name, at=at)
                add("precedes", state, "?now", at=at)
                add("state_of", state, x, positive=q not in denied, at=at)
            else:
                got, how = lexicon.inherited("quality", name, "ADJECTIVE", (), "has_property")
                # A quality saying a link to what it is of says it to that thing ("the Dutch people": from the
                # Netherlands); said to the adjective, "The Dutch people approve ..." was `comes_from(?v0, dutch)`.
                of = lexicon.words.defined(name) if got and got != "has_property" else []
                decided.append(("quality", name, how, add(got or "has_property", x, of[0] if of else name,
                                                          positive=q not in denied, at=at)))
        elif what == "count":
            _, x, n = p[:3]
            add("has_count", x, n, at=at)
        elif what == "counted":
            # "more attacks than earlier methods": the attacks' count above the other's (`exceeds`).
            _, x, way = p[:3]
            for y in (q[2] for q in pieces if q[0] == "than" and q[1] == x):
                mine, theirs = fresh(), fresh()
                add("has_count", x, mine, at=at)
                add("has_count", y, theirs, at=at)
                add("exceeds", *((mine, theirs) if way == "more" else (theirs, mine)), at=at)
        elif what == "purpose":
            _, e, c = p[:3]
            add("has_purpose", e, c, at=at)
        elif what == "member":
            _, g, x = p[:3]
            if x in groups:
                continue
            add("has_member", group_of(g), x, at=at)
        elif what == "fact":
            _, relation, a, b, owner = p[:5]
            add(relation, a, b, positive=not (owner is not None and owner in denied), at=at)
        elif what == "during":
            _, e, t = p[:3]
            add("during", e, t, at=at)
    for p in bes:
        _, x, y, owner = p[:4]
        at = p[-1]
        positive = owner not in denied
        y_kind = kinds.get(y)
        key = _be_key(pieces, p, given, asked)
        how_said, how = lexicon.link("be", key, "equals")
        if y in generic_be and y in asked:
            # "What is water?": what a kind is a kind of, asked (`isa(water, ?x)`).
            add("isa", x, y, positive=positive, at=at)
            continue
        # WHAT A THING IS SAID TO BE IS A KIND ONLY SAID SO: with "a", bare, known, "another", whose, or "no" (Partee
        # 1987: of noun phrases, these shift to what is said of a thing; "some", "any", "every" quantify and do not).
        # "A wall is any artifact." was read as a wall being an artifact, and said so (lyric_dev2, 2026-10-28).
        quantified = any(q[0] == "det" and q[1] == y for q in pieces) and (any(
            q[0] == "some" and q[1] == y for q in pieces) or not any(
            q[0] in ("indefinite", "bare", "given", "other", "poss", "deny_arg") and q[1] == y for q in pieces))
        if y in generic_be and y not in given and not quantified:
            # "Whales are mammals.": a kind said to be of a kind (`isa(whale, mammal)`).
            how_said, how = "merge", "rule"
        decided.append(("be", ":".join(key), how, None))
        # A KIND OF A KIND SAID OF A THING is no merging: "This is a kind of watermelon." is one, a kind of watermelon,
        # never a watermelon (`equals`, as the PMB says it).
        if how_said == "merge" and y_kind is not None and isinstance(y, int) and y not in asked and not quantified \
                and y not in subkinds:
            # "Tom is a gentleman": the gentleman is Tom, what is said of one said of the other.
            facts[:] = [f for f in facts if not (f.relation == "instance_of" and f.subject == term(y))]
            if isinstance(x, str) and not x.startswith("?"):
                add("isa", x, y_kind[2], positive=positive, at=at)
            else:
                add("instance_of", x, y_kind[2], positive=positive, at=at)
            merged[y] = x
            continue
        if x in asked and y not in asked:
            add("equals", y, x, positive=positive, at=at)
        else:
            add("equals", x, y, positive=positive, at=at)
    if merged:
        rename = {term(k): term(v) for k, v in merged.items()}
        facts = [f.renamed(rename) if any(t in rename for t in f.terms()) else f for f in facts]
        facts = list(dict.fromkeys(f for f in facts if f.subject != f.obj))
    if not facts:
        raise ValueError("nothing said")
    held = {t for f in facts for t in f.terms()}
    asked_terms = tuple(dict.fromkeys(term(a) for a in asked if term(a) in held and is_variable(term(a))))
    # The meaning, its unknowns named in order.
    numbering: Dict[str, str] = {}
    for f in facts:
        for t in f.terms():
            if is_variable(t) and t not in ("?speaker", "?listener", "?previous", "?now", "?here", "?there") \
                    and t not in numbering:
                numbering[t] = f"?v{len(numbering)}"
    facts = [f.renamed(numbering) if any(t in numbering for t in f.terms()) else f for f in facts]
    decided[:] = [(kind, key, how, f.renamed(numbering) if f is not None else None) for kind, key, how, f in decided]
    # `renamed` drops `given` of a renamed variable only where it is named; keep it.
    out = []
    for f in facts:
        out.append(f)
    return Meaning(act, tuple(dict.fromkeys(out)),
                   tuple(numbering.get(a, a) for a in asked_terms) if act == "ask" else ())


def _argument_spans(sign: Sign, labels: Sequence[str]) -> List[Tuple[int, int]]:
    """Where in the sentence the words a word of these entries took stand: "if" and the clause it takes."""
    out: List[Tuple[int, int]] = []
    stack = [sign]
    while stack:
        s = stack.pop()
        if s.rule in (">", "<") and len(s.kids) == 2:
            fn, arg = (s.kids[0], s.kids[1]) if s.rule == ">" else (s.kids[1], s.kids[0])
            if fn.rule == "lex" and fn.entry in labels:
                out.append((arg.start, arg.end))
        stack.extend(s.kids)
    return out


def _clause_spans(sign: Sign) -> List[Tuple[int, Tuple[int, int]]]:
    """Where the clause each verb taking one ("knows that ...", "wants to ...", "told Rex to ...") took stands: (the
    verb's word, the clause's words)."""
    out: List[Tuple[int, Tuple[int, int]]] = []
    stack = [sign]
    while stack:
        s = stack.pop()
        if s.rule == ">" and len(s.kids) == 2:
            fn, arg = s.kids
            clause = (isinstance(arg.cat, Atom) and arg.cat.base == "S" and arg.cat.feat == "em") or (
                _verb_phrase(arg.cat) and arg.cat.res.feat in ("to", "ng"))
            head = fn
            while head.rule != "lex" and head.kids:
                head = head.kids[0]
            if clause and head.rule == "lex" and head.entry.split(":")[-1] in ("that", "to", "ing", "told to"):
                out.append((head.start, (arg.start, arg.end)))
        stack.extend(s.kids)
    return out


def _be_key(pieces: Sequence[Piece], be: Piece, given: Set[Term], asked: Sequence[Term]) -> Tuple[str, str]:
    """What "is" joins, as what it says is learned: what stands before it (a name, the speaker, a pronoun by its
    word, a thing) and after (a thing known, a name, what is asked, a kind)."""
    x, y = be[1], be[2]
    pronoun = next((q[2] for q in pieces if q[0] == "pron" and q[1] == x), None)
    subject = ("name" if isinstance(x, str) and not x.startswith("?") else pronoun or (
        x[1:] if isinstance(x, str) else "asked" if x in asked else
        # A thing said with "a" or "every", or bare ("A robin is a bird.", "Whales are mammals."): a kind said, what
        # it is said to be learned apart from what a particular thing is said to be ("My father was an engineer.").
        "kind" if any(q[0] in ("indefinite", "bare", "every") and q[1] == x for q in pieces)
        and not any(q[0] == "some" and q[1] == x for q in pieces) else "thing"))
    complement = "given" if y in given else "name" if isinstance(y, str) else "asked" if y in asked else "kind"
    return subject, complement


#: What a name memory holds nothing of is, as what a link is learned for: one thing called by its name ("Vance worked
#: with Hooper.").
NAMED = "(a name)"


def _what_is(t: Term, kinds: Mapping[Term, Piece], pieces: Sequence[Piece], words: Words) -> List[str]:
    """WHAT A THING SAID IS, nearest first, as what a link is learned and decided for (`Lexicon.selected`): the kind
    it is said to be and what memory holds that a kind of ("the election": an election, a vote, a group action, an
    event); a name's kinds as memory holds them, then that it is a name; the speaker, the listener and a pronoun of a
    person ("him") a person."""
    if t in kinds:
        kind = str(kinds[t][2])
        return [kind] + words.kinds(kind, "NOUN")
    pronoun = next((q[2] for q in pieces if q[0] == "pron" and q[1] == t), None)
    if pronoun is not None:
        return ["person"] if _pronoun_kind(pronoun) == "person" else []
    if not isinstance(t, str):
        return []
    if t in ("?speaker", "?listener"):
        return ["person"]
    if t.startswith("?") or _number(t) is not None:
        return []
    return words.kinds(t, "NOUN") + [NAMED]


def _pronoun_kind(word: str) -> str:
    word = word.lower()
    if word in ("he", "him", "his", "himself", "she", "her", "hers", "herself"):
        return "person"
    if word in ("it", "its", "itself"):
        return "thing"
    return "any"


def pronoun_number(word: str) -> Optional[bool]:
    """Whether a pronoun points back to many things (True), to one (False), or is no pronoun that says (None)."""
    word = word.lower()
    if word in ("they", "them", "their", "theirs", "themselves", "these", "those"):
        return True
    if word in ("it", "its", "itself", "he", "him", "his", "himself", "she", "her", "hers", "herself"):
        return False
    return None


def pronoun_person(word: str) -> Optional[bool]:
    """Whether a pronoun points back to a person (True: "he", "she"), to what is no person (False: "it"), or does not
    say (None: "they", or no pronoun)."""
    word = word.lower()
    if word in ("he", "him", "his", "himself", "she", "her", "hers", "herself"):
        return True
    if word in ("it", "its", "itself"):
        return False
    return None


# ── the sentences taught with their meanings, aligned to their words; the view memory keeps ────────────────────────

def closed_uses(grammar: Optional[Mapping[str, Any]] = None) -> Dict[str, Set[str]]:
    """Each grammar word's uses, as its entries name them ("is": `be:ng`, `be:np`, ...): how a treebank's uses of it
    are signed (`grammar_words.HeldWords`)."""
    data = dict(grammar) if grammar is not None else json.loads(ENGLISH.read_text(encoding="utf-8"))
    return {w.lower(): {e["use"] for e in entries if "use" in e} for w, entries in data["words"].items()}


def align_by_anchors(tokens: Sequence[str], text: str, anchors: Iterable[Tuple[str, Sequence[Any]]]
                     ) -> Dict[str, List[int]]:
    """A taught meaning's terms aligned to its words by where its source says each is said (the PMB's lines:
    `composition.TaughtSentence.anchors`, characters each): a line's own words, those it marks as of its grammar
    ("the", "in") aside; a term said by its marked words ("How many"), those."""
    at: List[Optional[Tuple[int, int]]] = []
    k = 0
    for w in tokens:
        found = text.find(w, k)
        if found < 0 and w == "n't":
            found = text.find("'t", k)
            found = found - 1 if found > 0 else found
        if found < 0:
            at.append(None)
            continue
        at.append((found, found + len(w)))
        k = found + len(w)
    words: Dict[str, List[int]] = defaultdict(list)
    for t, said in anchors:
        for start, end, how, marked in said:
            inside = [i for i, o in enumerate(at) if o and o[0] >= start and o[1] <= end]
            marks = {m.lower() for m in marked}
            own = ([i for i in inside if tokens[i].lower() in marks] if how == "marked" else
                   [i for i in inside if tokens[i].lower() not in marks] or inside)
            for i in own:
                if i not in words[t]:
                    words[t].append(i)
    return dict(words)


def align_by_names(tokens: Sequence[str], meaning: Meaning, lexicon: "Lexicon") -> Dict[str, List[int]]:
    """A taught meaning's terms aligned to its words by the names it holds (a lesson's: it says no more): a variable
    to the word named as its kind, a name or a kind said of a kind to the word named so, a term of the situation to
    a word the grammar reads as standing for it ("I": `?speaker`; "it": the one spoken of before), what is asked to a
    word the grammar reads as asking."""
    words = lexicon.words
    named = [{words.name(t, c) for c in ("NOUN", "VERB", "ADJECTIVE", "ADVERB")} | {t.lower()} for t in tokens]
    stands: Dict[str, Set[str]] = defaultdict(set)
    asking: Set[str] = set()
    for w, entries in lexicon.closed.items():
        for e in entries:
            for ref in re.findall(r"\.(\?[a-z]+)", e["cat"]):
                stands[ref].add(w)
            # A pronoun of its own sentence whose category fixes its thing ("myself", "yourself") stands for the
            # speaker or the listener and never for the one spoken of before, whatever its mark.
            if any(p[0] == "pron" for p in e.get("sem", ())) and not re.findall(r"\.(\?[a-z]+)", e["cat"]):
                stands["?previous"].add(w)
            if any(p[0] == "asked" for p in e.get("sem", ())):
                asking.add(w)
    out: Dict[str, List[int]] = defaultdict(list)
    used: Set[int] = set()

    def place(term: str, name: str) -> None:
        for i, held in enumerate(named):
            if i not in used and (name in held or name.split()[-1] in held):
                out[term].append(i)
                used.add(i)
                return
    for f in meaning.facts:
        if f.relation == "instance_of" and is_variable(f.subject) and f.subject not in out:
            place(f.subject, f.obj)
    terms = {t for f in meaning.facts for t in f.terms()}
    for t in sorted(terms):
        if not is_variable(t) and t not in out:
            place(t, t)
    for t, said in stands.items():
        if t in terms:
            i = next((i for i, w in enumerate(tokens) if w.lower() in said and i not in used), None)
            if i is not None:
                out[t].append(i)
                used.add(i)
    for a in meaning.asked:
        if a not in out:
            i = next((i for i, w in enumerate(tokens) if w.lower() in asking and i not in used), None)
            if i is not None:
                out[a].append(i)
                used.add(i)
    return dict(out)


def _rules_written() -> str:
    """The grammar's rules as written: this module, how it counts how words are used (`grammar_words`), and the
    grammar's own words (`data/grammar/english.json`). What a sentence taught it is kept under them, and learned again
    once they change."""
    import hashlib
    digest = hashlib.sha256()
    for path in (Path(__file__), Path(__file__).with_name("grammar_words.py"), ENGLISH):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


#: The rules what each sentence taught was learned under (`GrammarView.hold`, `MemoryAgent.keep_grammar_learning`).
RULES = _rules_written()


def _tupled(value: Any) -> Any:
    """A key or a link as the grammar counts it, from how it was kept (lists for its tuples)."""
    return tuple(_tupled(v) for v in value) if isinstance(value, (list, tuple)) else value


#: WHETHER WHAT IS READ NOW TEACHES LYRIC'S ENGLISH (`reading_teaches`): set where Lyric knows whose text it reads and
#: that it may learn from it (a page it looked up, a document a person who shares their learning gave it). Unset,
#: reading teaches nothing: a claim read as it is kept, a tool's description.
_TEACHES: "contextvars.ContextVar[bool]" = contextvars.ContextVar("reading_teaches", default=False)


@contextlib.contextmanager
def reading_teaches(teaches: bool = True):
    """What is read inside this teaches Lyric's English (`GrammarView.read`), as a book teaches a reader."""
    token = _TEACHES.set(bool(teaches))
    try:
        yield
    finally:
        _TEACHES.reset(token)


class GrammarView:
    """The grammar memory reads with (`MemoryAgent.grammar_view`): its words (`Words`, what memory holds of them),
    and what it learned from the sentences memory holds with their taught meanings (`hold`: the lessons', the
    PMB's), each learned from when next read; a sentence taught again corrected is taken back (`drop`) and learned
    from as corrected."""

    def __init__(self, words: Words, grammar: Optional[Mapping[str, Any]] = None, structure: Optional[Any] = None):
        self.grammar = Grammar(Lexicon(words, grammar))
        self.grammar.structure = structure
        self._waiting: List[Any] = []
        self._waiting_keys: Set[str] = set()
        self._counted: Dict[str, List[Tuple[str, Tuple, str]]] = {}
        #: What was learned from each sentence read since memory last kept it (`unkept`).
        self._unkept: Dict[str, List[Tuple[str, Tuple, str]]] = {}
        #: Each sentence read that taught how its words are used (`read`, `hold_read`), by its digest: a sentence read
        #: again teaches nothing more.
        self._read: Set[str] = set()
        #: What sentences read taught since memory last kept it (`unkept_read`).
        self._unkept_read: List[Dict[str, Any]] = []
        #: The sentences derived by hand held (`hold_derived`), by their keys, and the rules learning is kept under
        #: with them (`rules`).
        self._derived: Set[str] = set()
        #: The words recorded whole held (`hold_word`), by their records' keys.
        self._words: Set[str] = set()
        #: Each document's sentences derived by hand, its taught sentence's places learned from them (`Grammar.learn`).
        self._derived_by_document: Dict[str, List[Derived]] = defaultdict(list)
        self._rules: Optional[str] = None
        self.learned_from = 0
        self.read_whole = 0

    def __len__(self) -> int:
        return len(self._counted) + len(self._waiting)

    @property
    def words(self) -> Words:
        return self.grammar.lexicon.words

    @property
    def rules(self) -> str:
        """What a sentence taught is learned under: the grammar's rules as written (`RULES`) and the sentences derived
        by hand it holds, which decide which reading of a taught sentence is learned from (`hold_derived`). Learning
        kept under other rules is learned again (`hold`, `MemoryAgent.keep_grammar_learning`)."""
        if self._rules is None:
            self._rules = RULES if not (self._derived or self._words) else hashlib.sha256(
                (RULES + "".join(sorted(self._derived)) + "".join(sorted(self._words))).encode("utf-8")).hexdigest()[:16]
        return self._rules

    def hold_word(self, word: Any) -> None:
        """A WORD RECORDED WHOLE (`teaching_sources.WordRecord`), what English's grammar takes of it: what each of its
        senses is a kind of (the words' knowledge, `GraphKnowledge.add`), how each form is used (`form_uses`), what
        it says joining a doing to a thing (`prep`), how often its verb is used in each frame (the words'
        `verb_frames`, as an analysed sentence counts them), and what each of its verb's places says (`role`,
        `prep_of`, as a taught meaning teaches them). Its forms, classes and names memory holds
        (`MemoryAgent._learn_word_record`). Held again, nothing is counted twice; held otherwise, `drop_word` first."""
        key = word.key()
        if key in self._words:
            return
        self._words.add(key)
        self._count_word(word, 1)
        self._rules = None

    def review_word(self, word: Any) -> List[Dict[str, Any]]:
        """A WORD TAUGHT, READ BACK IN ITS OWN EXAMPLES (WordNet's, each of a sense): whether each example is read
        whole, whether the word is read in the example's sense (its thing, or its doing, named so), and the words
        of the example nothing taught yet holds, the words to teach next. Asks nothing of memory; reads nothing it
        learns from."""
        words = self.grammar.lexicon.words
        out: List[Dict[str, Any]] = []
        for sense in word.senses:
            for example in sense.examples:
                text = example.strip().strip("`'\"")
                if not text:
                    continue
                if text[-1:] not in ".?!":
                    text += "."
                tokens = tokens_of(text, words)
                reading = self.grammar.read(tokens)
                # The words nothing taught yet holds, as the reading itself worked them out (`words_not_held`): the
                # question was written here first and asked for this report alone, which left reading unable to say
                # it of a sentence anyone else gave it.
                unknown = sorted(reading.unheld)
                meaning = reading.meaning
                in_sense = meaning is not None and any(
                    f.relation == "instance_of" and f.obj == sense.concept for f in meaning.facts)
                out.append({"sense": sense.id, "example": text, "read": meaning is not None,
                            "in_sense": in_sense, "unknown": unknown})
        return out

    def hold_use(self, word: str, sense: str, slot: str, filler: str, times: int = 1) -> None:
        """A SENSE OF A VERB SEEN USED, in a sentence recorded whole: the verb's word, the sense its meaning names, the
        place (subject, object) and the thing in it ("fastened" `fasten`, the object `award decoration`)."""
        lexicon = self.grammar.lexicon
        name = lexicon.words.name(word, "VERB")
        lexicon.sense_seen[name][sense][(slot, filler)] += times
        if lexicon.sense_seen[name][sense][(slot, filler)] <= 0:
            del lexicon.sense_seen[name][sense][(slot, filler)]

    def drop_word(self, word: Any) -> None:
        """A word recorded whole, taken back."""
        key = word.key()
        if key not in self._words:
            return
        self._words.discard(key)
        self._count_word(word, -1)
        self._rules = None

    def _count_word(self, word: Any, times: int) -> None:
        words, lexicon = self.grammar.lexicon.words, self.grammar.lexicon
        for cache in ("_uses", "_names"):
            if isinstance(getattr(words, cache, None), dict):
                getattr(words, cache).clear()
        # WHAT EACH OF ITS SENSES IS A KIND OF, as the grammar asks what a thing is deciding a link by it
        # (`Lexicon.inherited`, `selected`): "coating paint" a coating, the verb `paint` an act of creating. Asked of
        # memory's concepts alone, a word taught only as a word was a kind of nothing.
        knowledge = getattr(words, "knowledge", None)
        if knowledge is not None and hasattr(knowledge, "discard"):
            for sense in word.senses:
                for _, kind in sense.kind_of:
                    if kind:
                        (knowledge.add if times > 0 else knowledge.discard)(sense.concept, "isa", kind)
                # An adjective is weighed by what it is of, as one memory holds defined with a thing ("British", the
                # United Kingdom; `GraphKnowledge.kinds`): "Norwegian" by Norway and what Norway is a kind of.
                for _, of, kinds in getattr(sense, "pertains_to", ()):
                    (knowledge.add if times > 0 else knowledge.discard)(sense.concept, "defined_with", of)
                    for kind in kinds:
                        (knowledge.add if times > 0 else knowledge.discard)(of, "isa", kind)
        # HOW EACH FORM IS USED, as an analysed sentence counts it (`form_uses`): which of the grammar's entries a form
        # is read with, how often ("for" a preposition 1,885 times, a `sub` 231).
        uses = getattr(words, "form_uses", None)
        if uses is not None:
            for form, use, n in getattr(word, "used_as", ()):
                uses[form][use] += times * n
                if uses[form][use] <= 0:
                    del uses[form][use]
        # HOW OFTEN EACH NOUN FORM IS SAID WITH NOTHING BEFORE IT SAYING WHICH, AND WITH A WORD THAT DOES, as an analysed
        # sentence counts it (`noun_alone`): a kind said bare costs as seldom as it is so said.
        alone = getattr(words, "alone", None)
        if alone is not None:
            for form, bare, determined in getattr(word, "said_alone", ()):
                for how, n in (("bare", bare), ("determined", determined)):
                    alone[form][how] += times * n
                    if alone[form][how] <= 0:
                        del alone[form][how]
        # AND THE REST AN ANALYSED SENTENCE TEACHES OF A WORD (`HeldWords._count`), as its record carries it: each form
        # written with a capital inside a sentence (`capitalized`), each -ing or participle form's shape (`verb_shapes`),
        # each noun said of a doing with no preposition (`bare_modifier`), each word said after the verb, as one with it
        # or apart (`said_together`).
        name = words.name(word.word, "VERB") if any(s.word_class == "VERB" for s in word.senses) else word.word
        for table, layer, key_of in (
                ("written", "capitalized", lambda x: (x[0], ((x[1], x[2]),))),
                ("shapes", "shapes", lambda x: (x[0], ((x[1], x[2]),))),
                ("bare", "said_of_doing", lambda x: (x[0], (("modifier", x[1]), ("otherwise", x[2])))),
                ("particles", "said_after", lambda x: ((name, x[0]), ((True, x[1]), (False, x[2]))))):
            held = getattr(words, table, None)
            if held is None:
                continue
            for item in getattr(word, layer, ()):
                key, counts = key_of(item)
                for what, n in counts:
                    held[key][what] += times * n
                    if held[key][what] <= 0:
                        del held[key][what]
        # WHAT IT SAYS IN WHAT IS MEANT, as sentences taught with their meanings taught it (`WordRecord.means`): each
        # learned under this grammar's own name for the word as a word of its class ("paint" the noun is `coating
        # paint` here), as `learn` learns it of a sentence.
        for table, cls, rest, said, n in getattr(word, "means", ()):
            held = lexicon.learned[table][(words.name(word.word, cls),) + tuple(rest)]
            held[said] += times * n
            if held[said] <= 0:
                del held[said]
        # AND HOW OFTEN EACH USE HAD A DOING'S -ING FORM NEXT, AND WAS IN A SENTENCE THAT ASKS, as an analysed sentence
        # counts them (`doing_after`, `asking`). Taught only how often "is" is each use, "Roy is painting the medal."
        # was Roy being a painting, `be:np` used 1,671 times to `be:ng`'s 306 (lyric_dev2, 2026-10-27).
        for table, layer in ((getattr(words, "before_doing", None), "used_before_doing"),
                             (getattr(words, "asked", None), "used_asking")):
            if table is None:
                continue
            so = {(form, use): n for form, use, n in getattr(word, layer, ())}
            for form, use, n in getattr(word, "used_as", ()):
                for flag, k in ((True, so.get((form, use), 0)), (False, n - so.get((form, use), 0))):
                    table[use][flag] += times * k
                    if table[use][flag] <= 0:
                        del table[use][flag]
        # HOW EACH FORM IS SAID, which forms are said alike and the first sounds said after each ("a" and "an", each
        # written most often as the other is), the subjects each finite form took, what each verb took as
        # its object, the nouns each determiner was said with, and the things said to be what a copula said they
        # were: what the grammar weighs a form by beside the
        # word after it, a subject with its verb and with what it is said to be, and a determiner with its noun
        # (`Lexicon._sound_after`, `Grammar._agreement`, `Grammar._determined`).
        if hasattr(words, "said"):
            def counted(table: Dict[Any, Counter], key: Any, what: Any, n: int) -> None:
                table[key][what] += times * n
                if table[key][what] <= 0:
                    del table[key][what]
            most: Dict[Tuple[str, str], Any] = {}
            for f in word.forms:
                form = f.form.lower()
                for way in f.sounds:
                    counted(words.said, form, way, 1)
                for table, every, key, layer in (
                        (words.subjects_of, words.every_subject, None, f.subjects),
                        (words.nouns_of, words.every_noun, None, f.nouns),
                        (words.objects_of, words.every_object, None, getattr(f, "objects", ())),
                        (words.predicated_of, words.every_predicated, "said", f.predicated)):
                    for agreed in layer:
                        at, what, n = (tuple(agreed[:2]), tuple(agreed[2:4]), agreed[4]) if key else \
                            (form, tuple(agreed[:2]), agreed[2])
                        counted(table, at, what, n)
                        every[what] += times * n
                        if every[what] <= 0:
                            del every[what]
                if (form, f.word_class) not in most or f.count > most[(form, f.word_class)].count:
                    most[(form, f.word_class)] = f
            alike: Dict[Tuple[str, str], List[str]] = defaultdict(list)
            for (form, cls), f in most.items():
                if f.before:
                    alike[(cls, f.features)].append(form)
                    for sound, n in f.before:
                        counted(words.sounds_after, form, sound, n)
            for forms in alike.values():
                for form in forms:
                    for other in forms:
                        counted(words.said_alike, form, other, 1)
        # WHAT IT SAYS JOINING A DOING TO A THING, as a taught meaning teaches a preposition (`prep`): "for"
        # `done_for`, `has_purpose`, weighed against each other by how often PropBank's arguments it opens are each.
        for link, n in getattr(word, "joins", ()):
            held = lexicon.learned["prep"][(word.word, "event", "-")]
            held[link] += times * n
            if held[link] <= 0:
                del held[link]
        # WHAT IT SAYS JOINING A THING TO A THING, as a taught meaning teaches a preposition (`prep`), and by what the
        # thing it takes is (`prep_to`): "of" `made_of` cheese, a food, `part_of` a road.
        from core.semantics.grammar_words import POINTS, STRETCHES, _concept
        for link, names, n in getattr(word, "joins_things", ()):
            time = ("point" if {_concept(x) for x in names} & POINTS else
                    "stretch" if {_concept(x) for x in names} & STRETCHES else "-")
            for table, key in [("prep", (word.word, "thing", time))] + [("prep_to", (word.word, "thing", kind))
                                                                        for kind in names]:
                held = lexicon.learned[table][key]
                held[link] += times * n
                if held[link] <= 0:
                    del held[link]
        # EACH NOUN SENSE, how often it is used and how much of what is said it and each of its kinds cover.
        if any(s.word_class == "NOUN" for s in word.senses):
            thing = words.name(word.word, "NOUN")
            for sense in word.senses:
                if sense.word_class != "NOUN":
                    continue
                lexicon.thing_used[thing][sense.concept] += times * (sense.used + 1)
                if lexicon.thing_used[thing][sense.concept] <= 0:
                    del lexicon.thing_used[thing][sense.concept]
                    lexicon.thing_covers[thing].pop(sense.concept, None)
                elif sense.covers:
                    lexicon.thing_covers[thing][sense.concept] = dict(
                        zip([sense.concept] + [kind for _, kind in sense.kind_of], sense.covers))
        if not any(s.word_class == "VERB" for s in word.senses):
            return
        name = words.name(word.word, "VERB")
        # A VERB OF SEVERAL WORDS ("make it"): how often its first word and the next were said as it, and apart, as the
        # treebank's verbs said with a particle are counted (`HeldWords.particles`, `said_together`).
        if getattr(word, "together", ()) and hasattr(words, "particles"):
            first, after = word.word.split(" ")[:2]
            key = (words.name(first, "VERB"), after)
            for table, counts in ((words.particles, word.together[:2]), (words.particles_ending, word.together[2:])):
                for as_one, n in zip((True, False), counts):
                    table[key][as_one] += times * n
                    if table[key][as_one] <= 0:
                        del table[key][as_one]
        # EACH VERB SENSE, how often it is used and what it was seen used with (SemCor), each thing's kinds known.
        for sense in word.senses:
            if sense.word_class != "VERB":
                continue
            lexicon.sense_used[name][sense.concept] += times * (sense.used + 1)
            for place in sense.places:
                for slot, _ in place.slots:
                    if slot in ("subject", "object"):
                        for how, thing in [("described", place.fills)] + [("restricted", c) for _, c in
                                                                          place.restricted]:
                            if thing:
                                lexicon.sense_wants[name][sense.concept][(slot, how, thing)] += times
            for slot, _, kinds, n in getattr(sense, "seen_with", ()):
                lexicon.sense_seen[name][sense.concept][(slot, kinds[0])] += times * n
                if knowledge is not None and hasattr(knowledge, "discard"):
                    for kind in kinds[1:]:
                        (knowledge.add if times > 0 else knowledge.discard)(kinds[0], "isa", kind)
        for sense, said in (word.frames_said().items() if hasattr(word, "frames_said") else ()):
            for frame, n in said.items():
                held = lexicon.frames_said[name][sense]
                held[frame] += times * n
                if held[frame] <= 0:
                    del held[frame]
        frames = getattr(words, "verb_frames", None)
        if frames is not None:
            for frame, n in word.frames().items():
                frames[name][frame] += times * n
                if frames[name][frame] <= 0:
                    del frames[name][frame]
        for (slot, link), n in word.links().items():
            if slot == "by":
                continue        # the grammar reads a doer after "by" by the subject's link (`spell_out`)
            held = lexicon.learned["role"][(name, slot)]
            held[link] += times * n
            if held[link] <= 0:
                del held[link]
            recorded = lexicon.place_links[(name, slot)]
            recorded[link] += times * n
            if recorded[link] <= 0:
                del recorded[link]
        # WHAT A PREPOSITION AFTER THE VERB SAYS, as its places say it ("paint for someone": `done_for`), as a taught
        # sentence teaches it of the very doing (`prep_of`).
        for (preposition, link), n in word.prepositions().items():
            held = lexicon.learned["prep_of"][(name, preposition, "-")]
            held[link] += times * n
            if held[link] <= 0:
                del held[link]

    def hold_derived(self, derived: Derived) -> None:
        """Hold one sentence derived by hand (`Derived`): what it says each word takes beside the words around it is
        counted at once (`Lexicon.hear_derived`); one held already is not counted again. Held before the sentences
        taught with their meanings are learned from, since it decides which of a taught sentence's readings is."""
        key = derived.key()
        if key in self._derived:
            return
        self._derived.add(key)
        self._derived_by_document[derived.said_in].append(derived)
        self._rules = None
        self.grammar.lexicon.hear_derived(derived)

    def drop_derived(self, derived: Derived) -> None:
        """Take back what one sentence derived by hand said (derived otherwise since)."""
        key = derived.key()
        if key not in self._derived:
            return
        self._derived.discard(key)
        self._derived_by_document[derived.said_in] = [d for d in self._derived_by_document[derived.said_in]
                                                      if d.key() != key]
        self._rules = None
        self.grammar.lexicon.hear_derived(derived, times=-1)

    def hold(self, taught: Any, learned: Optional[Sequence[Any]] = None) -> None:
        """Hold one sentence taught with its meaning (`composition.TaughtSentence`), learned from when next read; one
        held already is not held again. `learned`: what it taught these rules before (`RULES`), as memory kept it with
        the sentence (`unkept`): taken as learned, and the sentence is not read again."""
        key = taught.key()
        if key in self._counted or key in self._waiting_keys:
            return
        if learned is not None:
            counted = [(str(table), _tupled(was), _tupled(link)) for table, was, link in learned]
            for table, was, link in counted:
                self.grammar.lexicon.learned[table][was][link] += 1
            self._counted[key] = counted
            self.learned_from += 1
            return
        self._waiting.append(taught)
        self._waiting_keys.add(key)

    def unkept(self) -> Dict[str, List[Tuple[str, Tuple, str]]]:
        """What was learned from each sentence read since this was last asked, by the sentence's key, for memory to
        keep with the sentence; each is given once."""
        unkept, self._unkept = self._unkept, {}
        return unkept

    def drop(self, taught: Any) -> None:
        """Take back what one sentence taught (corrected since)."""
        key = taught.key()
        self._waiting = [t for t in self._waiting if t.key() != key]
        self._waiting_keys.discard(key)
        self._unkept.pop(key, None)
        counted = self._counted.pop(key, None)
        if counted:
            self.grammar.unlearn(counted)

    def learn_waiting(self) -> int:
        """Learn from every sentence held since last read. Returns how many."""
        waiting, self._waiting, self._waiting_keys = self._waiting, [], set()
        for taught in waiting:
            self._learn_one(taught)
        return len(waiting)

    async def learn_waiting_in_turn(self) -> int:
        """`learn_waiting`, giving way after each sentence (`GiveWay`), so a process that learns its grammar while it
        starts stays live: every sentence memory holds with its meaning, minutes of work. One read meanwhile learns
        what is still waiting at once (`learn_waiting`), and nothing is learned twice. Returns how many."""
        from core.utils.give_way import GiveWay
        give_way, learned = GiveWay(), 0
        while self._waiting:
            taught = self._waiting.pop(0)
            self._waiting_keys.discard(taught.key())
            self._learn_one(taught)
            learned += 1
            await give_way()
        return learned

    def _learn_one(self, taught: Any) -> None:
        tokens = tokens_of(taught.sentence, self.words)
        if not tokens:
            return
        aligned = (align_by_anchors(tokens, taught.sentence, taught.anchors) if taught.anchors else
                   align_by_names(tokens, taught.meaning, self.grammar.lexicon))
        counted: List[Tuple[str, Tuple, str]] = []
        derived = sorted(self._derived_by_document.get(taught.said_in, ()), key=lambda d: d.part) \
            if taught.said_in else ()
        self.read_whole += self.grammar.learn(tokens, taught.meaning, aligned, counted, derived, taught.sentence)
        self._counted[taught.key()] = counted
        self._unkept[taught.key()] = counted
        self.learned_from += 1

    def read(self, sentence: str) -> Reading:
        """A sentence read by the grammar (`Reading`), after learning from what is waiting. A word written lowercase
        read as a name ("the function sorted") is heard as one from then on."""
        self.learn_waiting()
        tokens = tokens_of(sentence, self.words)
        reading = self.grammar.read(tokens)
        if reading.meaning is not None and reading.sign is not None:
            named = [str(p[1]) for p in reading.sign.pieces if p[0] == "named"]
            for name in named:
                self.grammar.lexicon.heard[name] += 1
            if _TEACHES.get():
                self._learn_from_reading(sentence, tokens, reading, named)
        return reading

    def say(self, meaning: Meaning, named: Optional[Mapping[str, str]] = None,
            why: Optional[Dict[str, Any]] = None,
            how_surely: Optional[Dict[str, float]] = None) -> List[str]:
        """A meaning said by the grammar it is read by (`Grammar.say`), after learning from what is waiting: every
        sentence that reads back to exactly it, the surest first. `why` is filled with why nothing was said, and
        `how_surely` with how sure it is of each sentence it says."""
        self.learn_waiting()
        return self.grammar.say(meaning, named, why, how_surely)

    def _learn_from_reading(self, sentence: str, tokens: Sequence[str], reading: Reading, named: List[str]) -> None:
        """READING TEACHES, as a book teaches its reader (`reading_teaches`): how the sentence's reading used each of its
        words (`Lexicon.uses_in`) is counted beside the treebank's, as much as the reading was sure (`Reading.sure`),
        so a word met is known from then on and how words are used is learned from what is read. A sentence read again
        teaches nothing more. Kept for memory to keep (`unkept_read`)."""
        key = hashlib.sha256(sentence.strip().encode("utf-8")).hexdigest()[:24]
        if key in self._read:
            return
        uses, verbs = self.grammar.lexicon.uses_in(reading.sign, tokens)
        record = {"key": key, "uses": [list(u) for u in uses], "verbs": [list(v) for v in verbs],
                  "named": named, "sure": round(reading.sure, 4)}
        self.hold_read(record)
        self._unkept_read.append(record)

    def hold_read(self, record: Mapping[str, Any]) -> None:
        """What one sentence read taught (`_learn_from_reading`), counted: as it is read, or as memory kept it."""
        if record["key"] in self._read:
            return
        self._read.add(record["key"])
        self.words.hear_read([tuple(u) for u in record.get("uses", ())], [tuple(v) for v in record.get("verbs", ())],
                             float(record.get("sure", 0.0)))
        for name in record.get("named", ()):
            self.grammar.lexicon.heard[name] += 1

    def unkept_read(self) -> List[Dict[str, Any]]:
        """What sentences read taught since this was last asked, for memory to keep; each is given once."""
        unkept, self._unkept_read = self._unkept_read, []
        return unkept

    def compose_sentence(self, sentence: str) -> Optional[Meaning]:
        """What a sentence means, read by the grammar; None where the grammar reads no whole or the meaning language
        cannot say it (`Reading.why`)."""
        return self.read(sentence).meaning
