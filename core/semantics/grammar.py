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

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from core.semantics.derived_reader import Meaning, MeaningFact, is_variable
from core.semantics.relation_types import worded

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

    def kinds(self, name: str, cls: str) -> List[str]:
        """What memory holds the word's thing to be a kind of, nearest first."""
        return []

    def is_person(self, name: str) -> bool:
        return False

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

    def said_together(self, verb: str, word: str) -> Tuple[float, float]:
        """How often the verb is said with the word after it as one verb ("take in"), and how often with that word
        after it otherwise ("sleep in the car")."""
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

    def bare_relatives(self) -> Tuple[float, float]:
        """How often a clause telling of a thing before it is said without "that", "who" or "which", and with."""
        return 0.0, 0.0

    def plural(self, word: str) -> bool:
        return False


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
                for form, r in self._forms(word, name).items():
                    for frame, q in self._frame_evidence(name).items():
                        for t in self.verb_templates.get(form, {}).get(frame, ()):
                            out.append((i + 1, Entry(t["cat"], tuple(tuple(x) for x in t.get("sem", ())), cls, name,
                                                     p + r + q, f"{form}:{frame}")))
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
        return out

    def _evidence(self, tokens: Sequence[str], i: int) -> Dict[str, float]:
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

    def _frame_evidence(self, name: str) -> Dict[str, float]:
        frames = list(self.verb_templates.get("frames", {}).keys())
        return estimate(self.words.frames(name), self.words.like(name, "frames"), frames)

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
            for cls, p in self._evidence([joined], 0).items():
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
                # As often as the two are said together so; where they never were, as often as the second word is
                # said with a verb so.
                second = self.words.uses(tokens[i + 1])
                alone = estimate(second, {}, set(second) | {"PARTICLE"})["PARTICLE"]
                one, apart = self.words.said_together(name, tokens[i + 1])
                particle = estimate({"one": one, "apart": apart},
                                    {"one": math.exp(alone), "apart": 1.0 - math.exp(alone)}, ("one", "apart"))["one"]
                for form, r in self._forms(tokens[i], name).items():
                    for frame, q in self._frame_evidence(together).items():
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

    # ── what was learned ──
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


def _weighed(held: Counter, default: Optional[Any]) -> Optional[Any]:
    """What sentences said, the grammar's own link counted once beside them; the rule where they tie with it."""
    counts = Counter(held)
    if default is not None:
        counts[default] += 1
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
    text = word.replace(",", "")
    try:
        value = float(text)
    except ValueError:
        return None
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


#: The categories a whole sentence may be read as, and what the speaker wants by each.
WHOLE = {"S[dcl]": "tell", "S[q]": "ask", "S[wq]": "ask", "S[imp]": "tell", "S": "tell", "NP": "tell"}
#: Punctuation that closes a sentence, and what it says the speaker wants.
CLOSING = {".": "tell", "!": "tell", "?": "ask"}


class Grammar:
    """Reads sentences by the grammar (`read`), and learns from sentences taught with their meanings (`learn`)."""

    def __init__(self, lexicon: Lexicon):
        self.lexicon = lexicon
        self._fresh = FIRST_VARIABLE
        self._tokens: Tuple[str, ...] = ()

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

        def made(cat: Cat, s: Dict[int, Term], rule: str, head: int) -> None:
            out.append(Sign(_apply(cat, s), _substitute(left.pieces + right.pieces, s), left.score + right.score,
                            left.start, right.end, rule, (left, right), head))
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
                made(rc.res, s, "<", left.head if _same_shape(rc.res, rc.arg) else right.head)
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
                made(Fn(rc.res.res, "/", rc.arg), s, ">T>B", right.head)
        return out

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
            out.append(Sign(Atom("NP", None, c.ref), sign.pieces + (("bare", c.ref, sign.head),),
                            sign.score + cost, sign.start, sign.end, "N=>NP", (sign,), sign.head))
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
        cells: Dict[Tuple[int, int], Dict[str, Sign]] = defaultdict(dict)

        def keep(sign: Sign) -> bool:
            k = _key(sign.cat)
            cell = cells[(sign.start, sign.end)]
            held = cell.get(k)
            if held is None or sign.score > held.score + 1e-9:
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
        # where it does not.
        best = max(whole, key=lambda s: (_rank(s.cat) == 2, s.score, _rank(s.cat)))
        reading = Reading(tokens, best, None)
        try:
            reading.meaning = self._spell_out(best, tokens, reading)
        except ValueError as error:
            reading.why = str(error)
        return reading

    # ── the meaning ──
    def _spell_out(self, sign: Sign, tokens: Sequence[str], reading: Reading) -> Optional[Meaning]:
        return spell_out(self.lexicon, sign, tokens, reading)

    # ── learning from sentences taught with their meanings ──
    def learn(self, tokens: Sequence[str], meaning: Meaning, words: Mapping[str, Sequence[int]],
              counted: Optional[List[Tuple[str, Tuple, str]]] = None) -> bool:
        """Learn from a sentence taught with its meaning, its terms aligned to its words (`words`: term -> the
        words saying it): read it by the grammar, and for each place a verb, a preposition, a possessive, an adverb
        or "is" holds, the link the meaning says between the two words' terms. Returns whether it was read; each
        count made is added to `counted` (table, key, link), so it can be taken back (`unlearn`)."""
        tokens = tuple(tokens)
        cells = self.chart(tokens)
        whole = [s for s in cells.get((0, len(tokens)), {}).values() if _whole(s.cat) is not None]
        if not whole:
            return False
        best = max(whole, key=lambda s: (_rank(s.cat) == 2, s.score, _rank(s.cat)))
        term_of: Dict[int, str] = {}
        for t, ws in words.items():
            for w in ws:
                term_of.setdefault(w, t)
        between: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for f in meaning.facts:
            between[(f.subject, f.obj)].append(f.relation)
        pieces = best.pieces
        word_of = _words_of_terms(pieces)
        holders: Dict[Term, Term] = {p[3]: p[1] for p in pieces if p[0] == "quality"}
        holders.update({p[3]: p[1] for p in pieces if p[0] == "be"})
        timed = {p[1] for p in pieces if p[0] == "past"}
        graded = {p[1] for p in pieces if p[0] in ("degree", "degree_asked")}
        kinds_of = {p[1]: p for p in pieces if p[0] in ("kind", "event")}
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
                time = (self.lexicon.words.is_time(b) if isinstance(b, str) else None) or (
                    self.lexicon.words.is_time(kinds_of[b][2]) if b in kinds_of else None) or "-"
                count("prep", (word, kind, time), got[0] if got else "")
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


def _rank(cat: Cat) -> int:
    """Of two readings as sure, a sentence before a thing said alone."""
    if isinstance(cat, Atom) and cat.base == "S":
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
        add("instance_of", e, p[2], at=at)
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
        add("instance_of", x, p[2], given_=x in given and isinstance(x, int), at=p[-1])
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
            time = (words.is_time(b) if isinstance(b, str) else None) or (
                words.is_time(kinds[b][2]) if b in kinds else None) or "-"
            head = events.get(a) or kinds.get(a)
            got, how = (None, "rule")
            if head is not None:
                got, how = lexicon.link("prep_of", (head[2], word, time), None)
            if how != "own":
                got, how = lexicon.link("prep", (word, kind, time), worded(word) if word.replace(" ", "").isalpha() else None)
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


class GrammarView:
    """The grammar memory reads with (`MemoryAgent.grammar_view`): its words (`Words`, what memory holds of them),
    and what it learned from the sentences memory holds with their taught meanings (`hold`: the lessons', the
    PMB's), each learned from when next read; a sentence taught again corrected is taken back (`drop`) and learned
    from as corrected."""

    def __init__(self, words: Words, grammar: Optional[Mapping[str, Any]] = None):
        self.grammar = Grammar(Lexicon(words, grammar))
        self._waiting: List[Any] = []
        self._waiting_keys: Set[str] = set()
        self._counted: Dict[str, List[Tuple[str, Tuple, str]]] = {}
        self.learned_from = 0
        self.read_whole = 0

    def __len__(self) -> int:
        return len(self._counted) + len(self._waiting)

    @property
    def words(self) -> Words:
        return self.grammar.lexicon.words

    def hold(self, taught: Any) -> None:
        """Hold one sentence taught with its meaning (`composition.TaughtSentence`), learned from when next read; one
        held already is not held again."""
        key = taught.key()
        if key not in self._counted and key not in self._waiting_keys:
            self._waiting.append(taught)
            self._waiting_keys.add(key)

    def drop(self, taught: Any) -> None:
        """Take back what one sentence taught (corrected since)."""
        key = taught.key()
        self._waiting = [t for t in self._waiting if t.key() != key]
        self._waiting_keys.discard(key)
        counted = self._counted.pop(key, None)
        if counted:
            self.grammar.unlearn(counted)

    def learn_waiting(self) -> int:
        """Learn from every sentence held since last read. Returns how many."""
        waiting, self._waiting, self._waiting_keys = self._waiting, [], set()
        for taught in waiting:
            tokens = tokens_of(taught.sentence, self.words)
            if not tokens:
                continue
            aligned = (align_by_anchors(tokens, taught.sentence, taught.anchors) if taught.anchors else
                       align_by_names(tokens, taught.meaning, self.grammar.lexicon))
            counted: List[Tuple[str, Tuple, str]] = []
            self.read_whole += self.grammar.learn(tokens, taught.meaning, aligned, counted)
            self._counted[taught.key()] = counted
            self.learned_from += 1
        return len(waiting)

    def read(self, sentence: str) -> Reading:
        """A sentence read by the grammar (`Reading`), after learning from what is waiting. A word written lowercase
        read as a name ("the function sorted") is heard as one from then on."""
        self.learn_waiting()
        reading = self.grammar.read(tokens_of(sentence, self.words))
        if reading.meaning is not None and reading.sign is not None:
            for p in reading.sign.pieces:
                if p[0] == "named":
                    self.grammar.lexicon.heard[p[1]] += 1
        return reading

    def compose_sentence(self, sentence: str) -> Optional[Meaning]:
        """What a sentence means, read by the grammar; None where the grammar reads no whole or the meaning language
        cannot say it (`Reading.why`)."""
        return self.read(sentence).meaning
