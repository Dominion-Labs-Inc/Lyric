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
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
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

    def verb_forms(self, word: str) -> Mapping[str, float]:
        """How often the word is used as each form of its verb: `base`, `present`, `third`, `past`, `participle`,
        `ing`."""
        return {}

    def frames(self, name: str) -> Mapping[str, float]:
        """How often the verb is used in each frame (`intransitive`, `transitive`, `ditransitive`, `to`, `that`)."""
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
        features subjects share with verbs: `("NOUN", "Number=Sing")`, `("PRONOUN", "Number=Sing|Person=1")`; of no
        word, every finite form's together. Nothing where memory holds none."""
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
        if not self.words.known_verb([name, tokens[i + 1].lower()]):
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
            for e in closed:
                cat = self._category(e["cat"])
                if _alike(way, cat) or _alike(way, _raised_thing(cat)):
                    return e["use"], ""
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
            for t in self.templates.get(cls, ()):
                if _alike(way, self._category(t["cat"])):
                    return t.get("use", cls), ""
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
        # Words joined by a hyphen are one word ("bullet-proof").
        if i + 2 < n and tokens[i + 1] == "-" and tokens[i].isalpha() and tokens[i + 2].isalpha() \
                and tokens[i + 2][:1].islower() and not (self._is_number(tokens[i]) and self._is_number(tokens[i + 2])):
            # No name: a name joined by a hyphen is capitalised throughout ("Coca-Cola", a name of several words), and
            # "Python-based" is used as words joined by a hyphen are.
            joined = f"{tokens[i]}-{tokens[i + 2]}".lower()
            for cls, p in self._evidence([joined], 0, (_beside(tokens, i - 1), _beside(tokens, i + 3))).items():
                name = self.words.name(joined, cls) if cls != "NAME" else joined.lower()
                for t in self.templates.get(cls, ()) if cls != "VERB" else ():
                    out.append((i + 3, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls, name, p,
                                             t.get("label", ""))))
        # A verb and the word after it that memory knows together as one verb ("passed away", "let up"), as often as
        # the second is said with a verb so.
        if i + 1 < n and tokens[i].isalpha() and tokens[i + 1].isalpha() and tokens[i + 1][:1].islower():
            verb = self._evidence(tokens, i).get("VERB")
            name = self.words.name(tokens[i], "VERB") if verb is not None else ""
            together = self.words.known_verb([name, tokens[i + 1].lower()]) if verb is not None else None
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
                    name = f"{tokens[i].lower()} {self.words.name(tokens[i + 1], 'NOUN')}"
                    for t in self.templates.get("NOUN", ()):
                        out.append((i + 2, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "NOUN", name,
                                                 score, "compound")))
        # Words memory knows as one thing: "credit card", "bus stop", "prime number"; as sure as its words are,
        # each used as it is used most.
        for length in (3, 2):
            if i + length <= n and all(t.isalpha() and t[:1].islower() for t in tokens[i:i + length]):
                known = self.words.known_name([t.lower() for t in tokens[i:i + length]])
                if known:
                    score = sum(max(self._evidence(tokens, k).values(), default=-20.0) for k in range(i, i + length))
                    for t in self.templates.get("NOUN", ()):
                        out.append((i + length, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), "NOUN",
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
    #: as it reads its words (`Grammar.read`).
    sure: float = 0.0


#: The categories a whole sentence may be read as, and what the speaker wants by each.
WHOLE = {"S[dcl]": "tell", "S[q]": "ask", "S[wq]": "ask", "S[imp]": "tell", "S": "tell", "NP": "tell"}
#: Punctuation that closes a sentence, and what it says the speaker wants.
CLOSING = {".": "tell", "!": "tell", "?": "ask"}

#: The links that tell of a happening: what holds them is said with a verb.
_HAPPENING_LINKS = frozenset({"done_by", "done_to", "received_by", "precedes", "follows", "during"})
#: What the situation names ("I", "you", "it", "now"): said with the grammar's own words, never a word for a thing.
_SITUATION = frozenset({"?speaker", "?listener", "?previous", "?now", "?here", "?there"})


def _things_said(meaning: Meaning) -> List[Tuple[str, str]]:
    """WHAT A MEANING NAMES, each with the class of word that says it, once (`Grammar.say`): the kind a thing is
    (`instance_of`), a doing where the thing is a happening; both kinds a kind is said of (`isa`); a quality a thing
    has, an adverb's of a happening; a number; any other thing named, by its name."""
    events = {f.subject for f in meaning.facts if f.relation in _HAPPENING_LINKS}
    out: List[Tuple[str, str]] = []
    for f in meaning.facts:
        if f.relation == "instance_of" and not is_variable(f.obj):
            out.append((f.obj, "VERB" if f.subject in events else "NOUN"))
            continue
        if f.relation == "isa":
            out += [(t, "NOUN") for t in (f.subject, f.obj) if not is_variable(t)]
            continue
        if f.relation == "has_property" and not is_variable(f.obj):
            out.append((f.obj, "ADVERB" if f.subject in events else "ADJECTIVE"))
            terms = (f.subject,)
        else:
            terms = (f.subject, f.obj)
        for t in terms:
            if not is_variable(t) and t not in _SITUATION:
                out.append((t, "NUMERAL" if _number(str(t)) is not None else "NAME"))
    return list(dict.fromkeys(out))


def _piece_says(piece: Tuple, meaning: Meaning) -> Optional[int]:
    """WHAT A PIECE OF A GRAMMAR WORD'S ENTRY SAYS IN A MEANING, as `spell_out` makes it: how many of the meaning's
    facts it may say (a thing known, `given`; a time before now, `past`; what one thing is of another, `be`: `isa`,
    `equals`, or a named thing of a kind; a denial, `deny`; a link a word names, `fact`), none for any other piece;
    None for a piece saying nothing a meaning holds (`indefinite`, `finite`)."""
    kind, facts = piece[0], meaning.facts
    if kind in ("indefinite", "finite"):
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
    if kind == "fact":
        return sum(1 for f in facts if f.relation == piece[1])
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

    def _lexical(self, tokens: Sequence[str], i: int, end: int, entry: Entry) -> Sign:
        names: Dict[str, Term] = {}

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
        # Of a noun of several words, the last is the one it is ("credit card": a card).
        head = end - 1 if entry.cls == "NOUN" else i
        return Sign(cat, tuple(pieces), entry.score, i, end, "lex", (), head, entry.label or entry.cls,
                    entry.crossing)

    def _combine(self, left: Sign, right: Sign) -> List[Sign]:
        out: List[Sign] = []
        lc, rc = left.cat, right.cat

        def made(cat: Cat, s: Dict[int, Term], rule: str, head: int, weighed: float = 0.0) -> None:
            out.append(Sign(_apply(cat, s), (), left.score + right.score + weighed, left.start, right.end, rule,
                            (left, right), head, binding=s))
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
            if _unify(lc.arg, rc, s):
                made(lc.res, s, ">", right.head if _same_shape(lc.res, lc.arg) else left.head)
        if isinstance(rc, Fn) and rc.slash == "\\":
            s = {}
            if _unify(rc.arg, lc, s):
                made(rc.res, s, "<", left.head if _same_shape(rc.res, rc.arg) else right.head,
                     self._agreement(left, right) if _verb_phrase(rc) and isinstance(lc, Atom) else 0.0)
        # Composition: X/Y Y/Z => X/Z; Y\Z X\Y => X\Z.
        if isinstance(lc, Fn) and lc.slash == "/" and isinstance(rc, Fn) and rc.slash == "/":
            s = {}
            if _unify(lc.arg, rc.res, s):
                made(Fn(lc.res, "/", rc.arg), s, ">B", left.head)
            elif isinstance(rc.res, Fn) and rc.res.slash == "/":
                # X/Y (Y/Z)/W => (X/Z)/W: "Did you give him" before what was given.
                s = {}
                if _unify(lc.arg, rc.res.res, s):
                    made(Fn(Fn(lc.res, "/", rc.res.arg), "/", rc.arg), s, ">B2", left.head)
        if isinstance(lc, Fn) and lc.slash == "\\" and isinstance(rc, Fn) and rc.slash == "\\":
            s = {}
            if _unify(rc.arg, lc.res, s):
                made(Fn(rc.res, "\\", lc.arg), s, "<B", right.head)
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
        subject's class with its features (what form it is, as the forms memory holds say; any features where it holds
        none), against that share of every finite verb's subjects, with one subject more spread as that share is.
        Nothing where memory holds no subject of the verb, or the subject is no one word of a class: a noun, a name, a
        pronoun.

        Nothing compared a subject with its verb: "a wall am" was read as "a wall is", and the first sentence the
        grammar said of a wall being a partition was "Wall'm the the a partition." (lyric_dev2, 2026-10-27)."""
        words, tokens = self.lexicon.words, self._tokens
        hook = _hook(doing.cat)
        finite = [p[-1] for p in doing.pieces if p[0] == "finite" and p[1] == hook]
        if not finite or not 0 <= min(finite) < len(tokens):
            return 0.0
        took = words.subjects(str(tokens[min(finite)]))
        if not took:
            return 0.0
        ref = subject.cat.ref
        said = [p for p in subject.pieces if p[0] == "word"]
        at = {p[-1] for p in subject.pieces if p[0] == "kind" and p[1] == ref}
        found = [(p[2], p[4] - 1) for p in said if p[3] in at and p[2] == "NOUN"] or \
            [(p[2], p[3]) for p in said if p[2] == "NAME" and p[1] == ref] or \
            ([("PRONOUN", subject.start)] if subject.rule == "lex" and subject.entry == "pron" else [])
        if len(found) != 1 or not 0 <= found[0][1] < len(tokens):
            return 0.0
        cls, k = found[0]
        every = words.subjects()
        shared = {f.split("=")[0] for _, features in every for f in features.split("|") if f}
        forms = {"|".join(f for f in features.split("|") if f and f.split("=")[0] in shared)
                 for features in words.form_features(str(tokens[k]), cls)}

        def matched(held: Mapping[Tuple[str, str], float]) -> float:
            return sum(n for (c, features), n in held.items() if c == cls and (not forms or features in forms))
        share = matched(every) / sum(every.values()) if every else 0.0
        if share <= 0:
            return 0.0
        return min(0.0, math.log((matched(took) + share) / (sum(took.values()) + 1.0) / share))

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
        self._weighed, self._marking, self._asking = None, frozenset(), frozenset()
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
        for i, t in enumerate(tokens):
            if not any(ch.isalnum() for ch in t) and t not in ("'s", "'") and not isinstance(t, Joining):
                # A hyphen joining two words is no mark between them: read only with the words it joins ("high-level",
                # never "high" and "level": "a high-level, general-purpose programming language" was two things).
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
        if weighed is None or not (0 <= at < len(tokens) and 0 <= of < len(tokens)) or at == of \
                or not any(ch.isalnum() for ch in str(tokens[of])) or of in self._marking:
            # A word that only marks another is joined as the grammar joins it: "did" takes its doer first in "Where
            # did Gandhi study?", the treebanks join it to "study", and the join the structure view made unlikely
            # (-6.2) decided the question was what Gandhi studied (GRAMMAR-01 dev, 2026-10-26).
            return
        sign.score += float(weighed[at + 1, of + 1])

    # ── reading a sentence ──
    def read(self, tokens: Sequence[str]) -> Reading:
        tokens = tuple(tokens)
        if not tokens:
            return Reading(tokens, None, None, "no words")
        cells = self.chart(tokens)
        whole = [s for s in cells.get((0, len(tokens)), {}).values() if _whole(s.cat) is not None]
        if not whole:
            covered = sorted(((e - s, s, e) for (s, e), cell in cells.items() if cell
                              and any(not (isinstance(x.cat, Atom) and x.cat.base == "punct") for x in cell.values())),
                             reverse=True)
            return Reading(tokens, None, None, "the grammar reads no whole", tuple((s, e) for _, s, e in covered[:3]))
        # A sentence is read as one wherever the grammar reads it so; as a phrase alone ("What a feast!") only
        # where it does not; as an order as often as what is said is one (`_said_so`).
        best = max(whole, key=lambda s: (_rank(s.cat) == 2, s.score + self._said_so(s.cat), _rank(s.cat)))
        reading = Reading(tokens, best, None)
        # HOW SURE: the reading's share of every reading of the whole, by how surely each reads its words.
        top = max(s.score for s in whole)
        reading.sure = math.exp(best.score - top) / sum(math.exp(s.score - top) for s in whole)
        try:
            reading.meaning = self._spell_out(best, tokens, reading)
        except ValueError as error:
            reading.why = str(error)
        return reading

    # ── saying a meaning ──
    def say(self, meaning: Meaning, named: Optional[Mapping[str, str]] = None) -> List[str]:
        """EVERY SENTENCE THIS GRAMMAR SAYS A MEANING WITH, the surest read first: the grammar a sentence is read by,
        used the other way (one grammar for reading and saying, Shieber 1988; chart generation, Kay 1996). The words
        for its things (`Words.words_for`: memory's words for each, every form held), and the grammar's own words whose
        pieces say what it holds (`_says_of`), as often as it holds it, a word saying nothing as often as what it takes
        is made ("a", making a thing of a kind); combined by the rules reading combines by (`_combine`, `_unary`), in
        any order, each word for a thing once; each sentence made READ BACK (`read`), and said only where it reads to
        exactly this meaning. The speaker's own word for a thing (`named`) before another. Empty where nothing the
        grammar holds says it: then it is not said another way here."""
        if meaning.act not in WHOLE.values() or not meaning.facts:
            return []
        wanted = _things_said(meaning)
        if not wanted:
            return []
        words = self.lexicon.words
        named = {str(k).lower(): str(v).lower() for k, v in (named or {}).items()}
        # THE WORDS FOR ITS THINGS, each a place the sentence must fill once, with each word and entry that may fill it.
        tokens: List[str] = []
        places: List[List[Tuple[int, Entry]]] = []
        for concept, cls in wanted:
            written = words.words_for(concept, cls) or []
            if cls == "NAME":
                written = [" ".join(w[:1].upper() + w[1:] for w in str(concept).split())]
            options: List[Tuple[int, Entry]] = []
            for form in written:
                for _, entry in self.lexicon.entries((form,), 0):
                    if entry.cls == cls:
                        options.append((len(tokens), entry))
                        tokens.append(form)
            if not options:
                return []
            places.append(options)
        # THE GRAMMAR'S OWN WORDS, each spending what it says, as often as the meaning holds it, with every other word
        # saying the same (`_says_of`); a link a preposition names, once for each fact of it.
        budget: Dict[Tuple[str, ...], int] = {}
        chosen: List[Tuple[str, Entry, Dict[Tuple[str, ...], int]]] = []
        empty: List[Tuple[str, Entry]] = []
        for word in sorted(self.lexicon.closed):
            for _, entry in self.lexicon.entries((word,), 0):
                if entry.cls != "GRAMMAR":
                    continue
                # A word making a question ("is" put first, a tag "isn't it") only asks: nothing told holds one.
                cat = parse_category(entry.cat)
                if meaning.act != "ask" and _whole((_comes_to(cat) or [cat])[-1]) == "ask":
                    continue
                says = _says_of(entry, meaning)
                if says:
                    budget.update(says)
                    chosen.append((word, entry, {k: 1 for k in says}))
                elif says is not None and isinstance(cat, Fn) and not _leaves_as_is(cat):
                    # A WORD SAYING NOTHING ENTERS WHERE SOMETHING NEEDS IT (Carroll, Copestake, Flickinger and
                    # Poznański 1999; Carroll and Oepen 2005): one that leaves what it takes as it was ("the" before a
                    # name, NP.x/NP.x; "then", S[F].a/S[F].a) is needed by nothing, whatever it is said with meaning
                    # the same without it. Offered as often as there are things, "the" said "Wall is the the a
                    # partition." (lyric_dev2, 2026-10-27). Reading still reads it.
                    empty.append((word, entry))
        for link in sorted({f.relation for f in meaning.facts}):
            for word in self.lexicon.saying(link):
                for _, entry in self.lexicon.entries((word,), 0):
                    if entry.cls == "PREPOSITION":
                        budget[("fact", link)] = sum(1 for f in meaning.facts if f.relation == link)
                        chosen.append((word, entry, {("fact", link): 1}))
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
        budget[("joins",)] = max(clauses - 1, 0)
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
        extra: List[Tuple[int, Entry, Tuple[int, ...]]] = []
        for word, entry, spends in chosen:
            extra.append((len(tokens), entry, tuple(spends.get(k, 0) for k in spending)))
            tokens.append(word)
        most = tuple(budget[k] for k in spending)
        self._tokens, self._weighed, self._marking, self._asking = tuple(tokens), None, frozenset(), frozenset()
        full = (1 << len(places)) - 1
        # THE CHART, over which words are used, not where they stand: (places filled, what the grammar words spent,
        # what it means and its category (`_meant`)) -> the surest such sign, with its words in order and where each
        # is among the words. ONE OF WHAT MEANS THE SAME: "a wall is" and "a wall 's" go on to the same sentences,
        # only as surely as each is read (kept by its words in order, every way of putting each was read back, 19,296
        # for "A wall is a partition.", lyric_dev2, 2026-10-27).
        Item = Tuple[int, Tuple[int, ...], Sign, Tuple[str, ...], Tuple[int, ...], Tuple]
        held: Dict[Tuple, Item] = {}
        agenda: List[Item] = []
        none = tuple(0 for _ in spending)
        # A WORD WEIGHED BY THE WORD SAID AFTER IT ("a", "an": `Lexicon._sound_after`) is weighed alone until a word is
        # put after it, then by that word; what ends in one, and what begins with each first sound, is kept apart
        # until then. Packed by meaning alone, "a" was surer alone than "an" and "an" was never said: "A owl is a
        # bird." was said first (2026-10-27).
        lexicon = self.lexicon
        alike = {w for w in set(tokens) if len(lexicon.words.said_before(w)) > 1}
        # What such a word takes after it ("a" a noun): only that is kept apart by the sound it begins with.
        taken = [cat.arg for w in alike for _, e in lexicon.entries((w,), 0)
                 for cat in [parse_category(e.cat)] if isinstance(cat, Fn) and cat.slash == "/"]

        def first_sound(word: str) -> Tuple[str, ...]:
            return tuple(sorted({way.split()[0].rstrip("012") for way in lexicon.words.sounds(word) if way.split()}))

        def hold(filled: int, used: Tuple[int, ...], sign: Sign, said: Tuple[str, ...], order: Tuple[int, ...]) -> None:
            key = (filled, used, _meant(sign, order, tokens)) + (
                (said[-1] if said[-1] in alike else "",
                 first_sound(said[0]) if any(_same_shape(sign.cat, c) for c in taken) else ()) if alike else ())
            if key in held and held[key][2].score >= sign.score:
                return
            held[key] = item = (filled, used, sign, said, order, key)
            agenda.append(item)
            for u in self._unary(sign):
                hold(filled, used, u, said, order)
        for k, options in enumerate(places):
            for at, entry in options:
                with contextlib.suppress(ValueError, IndexError):
                    hold(1 << k, none, self._lexical(tokens, at, at + 1, entry), (tokens[at],), (at,))
        for at, entry, spends in extra:
            with contextlib.suppress(ValueError, IndexError):
                hold(0, spends, self._lexical(tokens, at, at + 1, entry), (tokens[at],), (at,))
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
        while agenda:
            item = agenda.pop()
            filled, used, sign, said, order, key = item
            if held[key] is not item:
                continue
            n = len(done)
            done.append(item)
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
                for left, right, words_said, words_order, last, first in (
                        (sign, other, said + other_said, order + other_order, said[-1], other_said[0]),
                        (other, sign, other_said + said, other_order + order, other_said[-1], said[0])):
                    beside = lexicon._sound_after((last, first), 0) - lexicon._sound_after((last,), 0) \
                        if last in alike else 0.0
                    for combined in self._combine(left, right):
                        if combined.binding is not None:
                            # As the chart makes a combination's meaning (`chart`, `keep`): its parts' pieces, bound.
                            combined.pieces = _substitute(left.pieces + right.pieces, combined.binding)
                            combined.binding = None
                        combined.score += beside
                        hold(filled | other_filled, together, combined, words_said, words_order)
        closing = {"tell": ".", "ask": "?"}[meaning.act] if meaning.act in ("tell", "ask") else "."
        wanted_act = meaning.act
        target = meaning.canonical()
        sentences: Dict[Tuple[str, ...], Tuple[int, float]] = {}
        for filled, _, sign, said, _, _ in list(held.values()):
            if filled != full or _whole(sign.cat) is None:
                continue
            if said in sentences:
                continue
            # Read as it is written, its first word with a capital: "wall" first was read surely (-4.6), "Wall" not
            # (-32.3), a name it might be (lyric_dev2, 2026-10-27).
            reading = self.read((said[0][:1].upper() + said[0][1:],) + said[1:] + (closing,))
            if reading.meaning is None or reading.meaning.act != wanted_act or reading.meaning.canonical() != target:
                continue
            own = sum(1 for w in said if w.lower() in named.values())
            sentences[said] = (own, reading.sign.score if reading.sign is not None else 0.0)
        ranked = sorted(sentences, key=lambda said: (-sentences[said][0], -sentences[said][1]))
        return [_written(said, closing) for said in ranked]

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
    loose = {p[1] for p in pieces if p[0] in ("indefinite", "bare")}
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
                                                          "finite", "closing")
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
    for x, p in kinds.items():
        if x in events:
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
    def numeric(t: Term) -> bool:
        """Whether a term is a number, or one of a kind of number."""
        kind = kinds[t][2] if t in kinds else t if isinstance(t, str) and t in kind_of.values() else None
        return _number(str(t)) is not None or (kind is not None and "number" in [kind] + words.kinds(kind, "NOUN"))
    bes: List[Piece] = [p for p in pieces if p[0] == "be"]
    holders: Dict[Term, Term] = {p[3]: p[1] for p in pieces if p[0] == "quality"}
    holders.update({p[3]: p[1] for p in bes})
    merged: Dict[Term, Term] = {}
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
                decided.append(("quality", name, how, add(got or "has_property", x, name, positive=q not in denied,
                                                          at=at)))
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
        if y in generic_be and y not in given:
            # "Whales are mammals.": a kind said to be of a kind (`isa(whale, mammal)`).
            how_said, how = "merge", "rule"
        decided.append(("be", ":".join(key), how, None))
        if how_said == "merge" and y_kind is not None and isinstance(y, int) and y not in asked:
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
        "kind" if any(q[0] in ("indefinite", "bare", "every") and q[1] == x for q in pieces) else "thing"))
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
            if any(p[0] == "pron" for p in e.get("sem", ())):
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
        knowledge = getattr(words, "knowledge", None)
        out: List[Dict[str, Any]] = []
        for sense in word.senses:
            for example in sense.examples:
                text = example.strip().strip("`'\"")
                if not text:
                    continue
                if text[-1:] not in ".?!":
                    text += "."
                tokens = tokens_of(text, words)
                unknown = sorted({t.lower() for t in tokens if str(t).isalpha() and not words.closed.get(t.lower())
                                  and not getattr(words, "form_uses", {}).get(t.lower())
                                  and not (knowledge.classes(t) if knowledge is not None else {})})
                reading = self.grammar.read(tokens)
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
        # HOW EACH FORM IS USED, as an analysed sentence counts it (`form_uses`): which of the grammar's entries a form
        # is read with, how often ("for" a preposition 1,885 times, a `sub` 231).
        uses = getattr(words, "form_uses", None)
        if uses is not None:
            for form, use, n in getattr(word, "used_as", ()):
                uses[form][use] += times * n
                if uses[form][use] <= 0:
                    del uses[form][use]
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
        # written most often as the other is), and the subjects each finite form took: what the grammar weighs a form
        # by beside the word after it, and a subject with its verb (`Lexicon._sound_after`, `Grammar._agreement`).
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
                for cls, features, n in f.subjects:
                    counted(words.subjects_of, form, (cls, features), n)
                    words.every_subject[(cls, features)] += times * n
                    if words.every_subject[(cls, features)] <= 0:
                        del words.every_subject[(cls, features)]
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

    def say(self, meaning: Meaning, named: Optional[Mapping[str, str]] = None) -> List[str]:
        """A meaning said by the grammar it is read by (`Grammar.say`), after learning from what is waiting: every
        sentence that reads back to exactly it, the surest first."""
        self.learn_waiting()
        return self.grammar.say(meaning, named)

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
