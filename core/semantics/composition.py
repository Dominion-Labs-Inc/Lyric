"""Composing what a sentence means from how its words go together (`structure.Structure`): the meaning language's
facts, read off the structure, as the lessons taught the meanings of their sentences.

"The dog chased a cat." is a chasing (`instance_of(?e, chase)`) done by the known dog (`done_by(?e, ?d)`, `given
instance_of(?d, dog)`), done to a cat, before now. Which word stands for what, and which fact two words' places say,
is learned from the lessons (`docs/TEACHING.md`): each lesson sentence read by the structure reader, its taught
meaning's facts aligned to its words, and what each word and each two words did counted in the situations they stood
in, from the most specific to the least, as the structure itself is learned (memory-based learning,
`StructureView._decide`). Five decisions:

- what a word stands for (`STANDS`): nothing, a name ("robin" in "A robin is a bird."), a thing ("a cat" chased), a
  known thing ("the dog"), the speaker, the listener, the thing spoken of before ("it"), here, there, now, or what a
  question asks;
- what fact two words' places say: the path between them in the structure, the words on it ("has" between "Tom" and
  "water" is `owns`), the function words on each ("in", "is"), a denial ("not");
- what fact a word brings with a term of the situation's or of the grammar's own (`precedes ?now` by its tense,
  `has_property ... hypothetical` by "would", `unexpected` by "although");
- which flags a clause puts on its facts (`condition` under "if", `unasserted` under "think" or "say", `alternative`
  with "or" in a question), each fact being of its subject's clause;
- what the speaker wants (`tell`, `ask`, `request`).

WHERE THE LESSONS SAY NOTHING PARTICULAR. The lessons are few (3,054 sentences) and taught for frames; prose holds
verbs and phrases they never use. Three things stand behind them, in order: a general situation of the lessons is
gone by only where it was met often and said one thing (`TRUST`); for a happening and a word that may head one of
its arguments, what PropBank's arguments say (`argument_structure.ArgumentStructureView`, learned from PropBank's
annotations of the treebank); and last, one readable sense for each relation of the structure (`RELATION_SENSES`:
an adjective on a noun is a quality of it, a number its count, a possessor its owner).

A run of words joined as compound or flat is one name ("Eiffel Tower", "carbon dioxide", "Guido van Rossum"), and
so is an adjective with its noun where memory knows the two as one name ("blue whale").

Lab notebook 2026-10-17 (16) and (17); `experiments/COMPOSE-01` measures it on the lessons held out and reads the
prose of UNDERSTANDS-PROSE-01 with it.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from core.semantics.argument_structure import ArgumentStructureView, candidates, phrase
from core.semantics.argument_structure import situations as argument_situations
from core.semantics.derived_reader import Meaning, MeaningFact
from core.semantics.relation_types import worded
from core.semantics.structure import StructureView

#: What a word may stand for, and the term each gives it ("thing", "known" and "asked" a variable of its own).
STANDS = {"none": None, "name": None, "thing": None, "known": None, "asked": None, "speaker": "?speaker",
          "listener": "?listener", "previous": "?previous", "here": "?here", "there": "?there", "now": "?now"}
SPEAKER = frozenset({"i", "me", "my", "mine", "myself", "we", "us", "our"})
LISTENER = frozenset({"you", "your", "yours", "yourself"})
PREVIOUS = frozenset({"it", "its", "they", "them", "their", "this", "that", "these", "those", "he", "him", "his",
                      "she", "her"})
SITUATION_WORDS = {"here": "?here", "there": "?there", "now": "?now"}
ASKING = frozenset({"who", "whom", "whose", "what", "which", "where", "when", "why", "how"})
NEGATIONS = frozenset({"not", "n't", "never", "no"})
#: The relations a clause hangs from the one above it by.
CLAUSES = ("advcl", "ccomp", "csubj", "acl", "xcomp", "conj", "parataxis")
#: The relations that join words into one name.
JOINED = ("compound", "flat", "flat:name")
#: Relations whose kind says more than their family, kept whole in a path.
KEPT_WHOLE = ("nmod:poss", "acl:relcl", "nsubj:pass", "obl:tmod", "obl:npmod")
#: The situations of two words that name a word: the lessons' decision there is particular and stands.
PARTICULAR = ("n", "v", "ni", "nj")
#: A general situation of the lessons is gone by only where met this often, the fact it says this share of the times:
#: where it said less, it carried the lessons' few cases into prose (`antonym_of` between "new" and "anomaly").
#: Measured (2026-10-17 (17)): the lessons held out 49.8% to 48.9%, the prose read far cleaner.
TRUST = (5, 0.8)
#: The relations of the structure a word marked by a preposition hangs by ("the capital of France", "killed on
#: Tuesday"): where nothing known says which link the preposition makes there, the link is held as its word
#: (`relation_types.worded`).
MARKED = ("nmod", "obl")
#: One readable sense of a relation of the structure, gone by last: the fact a word joined so says of its head
#: ("<": the head is the fact's first term).
RELATION_SENSES = {"↑amod": "has_property:<", "↓amod": "has_property:>", "↑nummod": "has_count:<",
                   "↓nummod": "has_count:>", "↑nmod:poss": "owned_by:<", "↓nmod:poss": "owned_by:>"}
#: A name a word's fact holds that no word of its sentence says (`hypothetical`, `unexpected`) is kept only where met
#: in this many sentences: fewer, it is a word the alignment missed.
GRAMMAR_MET = 3


@dataclass(frozen=True)
class Laid:
    """A sentence laid out for composing: its words, their classes, the word each depends on (1-based, 0 the root)
    and as what, each word's name (empty for a word that is part of another's name), and each word's dependents."""

    words: Tuple[str, ...]
    classes: Tuple[str, ...]
    heads: Tuple[int, ...]
    relations: Tuple[str, ...]
    names: Tuple[str, ...]
    under: Mapping[int, Tuple[int, ...]]

    def __len__(self) -> int:
        return len(self.words)

    def children(self, i: int, relations: Sequence[str]) -> str:
        """The words under word i joined by these relations (by family), lowercased, or "-"."""
        return "+".join(self.words[k].lower() for k in self.under.get(i, ())
                        if self.relations[k].split(":")[0] in relations) or "-"


def lay(words: Sequence[str], classes: Sequence[str], heads: Sequence[int], relations: Sequence[str],
        name_of: Callable[[str, str], str], known_name: Callable[[Sequence[str]], bool] = lambda _: False) -> Laid:
    """The sentence laid out (`Laid`), each word named by `name_of(word, class)`; a run joined as compound or flat
    named as one, the head's, and an adjective with its noun where `known_name` knows the two."""
    names = [name_of(w, c) for w, c in zip(words, classes)]
    under: Dict[int, List[int]] = defaultdict(list)
    for i, head in enumerate(heads):
        under[head - 1].append(i)
    for h in range(len(words)):
        if classes[h] not in ("NOUN", "NAME"):
            continue
        joined = [k for k in under[h] if relations[k] in JOINED and classes[k] in ("NOUN", "NAME", "ADJECTIVE",
                                                                                    "NUMERAL")]
        if not joined:
            described = [k for k in under[h] if relations[k] == "amod" and k == h - 1]
            if described and known_name([words[described[0]], names[h]]):
                joined = described
        span = sorted(joined + [h])
        if not joined or span != list(range(span[0], span[-1] + 1)):
            continue
        names[h] = " ".join(words[k].lower() if k != h else names[h] for k in span)
        for k in joined:
            names[k] = ""
    return Laid(tuple(words), tuple(classes), tuple(heads), tuple(relations), tuple(names),
                {k: tuple(v) for k, v in under.items()})


# ── the situations ────────────────────────────────────────────────────────────────────────────────────────────────

def _word_situations(laid: Laid, i: int) -> List[Tuple]:
    w, c, rel = laid.words[i].lower(), laid.classes[i], laid.relations[i]
    head = laid.heads[i] - 1
    head_class = laid.classes[head] if head >= 0 else "ROOT"
    head_name = laid.names[head] if head >= 0 else "-"
    det = laid.children(i, ("det",))
    if any(laid.relations[k] == "nmod:poss" for k in laid.under.get(i, ())):
        det = "poss" if det == "-" else det + "+poss"
    aux = laid.children(i, ("aux", "cop"))
    counted = "count" if any(laid.relations[k] == "nummod" for k in laid.under.get(i, ())) else "-"
    plural = "s" if w.endswith("s") and c == "NOUN" else "-"
    first = "first" if i == 0 else "-"
    return [("w", w, c, rel, det, aux, counted, head_class), ("w", w, c, rel, det, aux, counted),
            ("c", c, rel, det, aux, counted, plural, head_class, first), ("c", c, rel, det, aux, counted, plural),
            ("h", c, rel, det, counted, head_name), ("wd", w, c, det), ("c", c, rel, det, counted), ("w", w, c),
            ("c", c, rel), ("c", c)]


def _first_conjunct(laid: Laid, i: int) -> int:
    while laid.relations[i] == "conj" and laid.heads[i]:
        i = laid.heads[i] - 1
    return i


def route(laid: Laid, i: int, j: int) -> Tuple[str, Tuple[str, ...]]:
    """The path from word i to word j (relations up from i, then down to j) and the names of the words between."""
    def up(k: int) -> List[int]:
        chain = [k]
        while laid.heads[chain[-1]] and len(chain) <= len(laid):
            chain.append(laid.heads[chain[-1]] - 1)
        return chain
    a, b = up(i), up(j)
    meet = next((k for k in a if k in b), None)
    if meet is None:
        return "far", ()
    ups, downs = a[:a.index(meet)], b[:b.index(meet)]
    steps = (["↑" + (laid.relations[k] if laid.relations[k] in KEPT_WHOLE else laid.relations[k].split(":")[0])
              for k in ups] + ["↓" + laid.relations[k] for k in reversed(downs)])
    between = [k for k in ups[1:] + [meet] + list(reversed(downs))[:-1] if k not in (i, j)]
    return "".join(steps[:5]) or "self", tuple(laid.names[k] for k in between)


def _denied(laid: Laid, words: Iterable[int]) -> str:
    return "not" if any(laid.words[c].lower() in NEGATIONS and laid.relations[c] in ("advmod", "det")
                        for k in words for c in laid.under.get(k, ())) else "-"


def _pair_situations(laid: Laid, i: int, j: int) -> List[Tuple]:
    """Word i and word j (i < j): the path from i to j, a conjunct taken where its first conjunct stands; the words
    between; the function words on each; a denial; their classes and names."""
    si, sj = _first_conjunct(laid, i), _first_conjunct(laid, j)
    if si == sj:
        si, sj = i, j
    between, via = route(laid, si, sj)
    marks = ("case", "mark", "cop", "aux")
    fi, fj = laid.children(si, marks), laid.children(sj, marks)
    denied = _denied(laid, (si, sj))
    via_names = "+".join(via) or "-"
    ci, cj = laid.classes[i], laid.classes[j]
    return [("n", laid.names[i], laid.names[j], between, via_names, fi, fj, denied),
            ("v", via_names, between, fi, fj, ci, cj, denied),
            ("ni", laid.names[i], between, via_names, fi, fj, cj, denied),
            ("nj", laid.names[j], between, via_names, fi, fj, ci, denied),
            ("p", between, fi, fj, ci, cj, denied), ("p", between, fj, ci, cj, denied),
            ("p", between, fi, ci, cj, denied), ("p", between, ci, cj, denied), ("p", between, denied)]


def _one_situations(laid: Laid, i: int) -> List[Tuple]:
    form, cls, name = laid.words[i].lower(), laid.classes[i], laid.names[i]
    aux = laid.children(i, ("aux", "cop"))
    subject = "subject" if any(laid.relations[k].startswith(("nsubj", "csubj", "expl"))
                               for k in laid.under.get(i, ())) else "-"
    k = 0
    while k < min(len(form), len(name)) and form[k] == name[k]:
        k += 1
    inflection = form[k:] if k >= len(name) - 1 else "other:" + form[k:]
    denied = _denied(laid, (i,))
    title = laid.children(i, ("compound", "flat"))
    adverbs = "+".join(sorted([laid.words[c].lower() for c in laid.under.get(i, ())
                               if laid.relations[c] in ("advmod", "discourse")]
                              + [laid.words[m].lower() for c in laid.under.get(i, ())
                                 if laid.relations[c].startswith("advcl")
                                 for m in laid.under.get(c, ()) if laid.relations[m] == "mark"] or ["-"]))
    rel = laid.relations[i]
    return [("w", form, cls, aux, subject, rel, denied, title, adverbs), ("w", form, cls, aux, subject, rel, denied,
                                                                          title),
            ("e", inflection, cls, aux, subject, rel, denied), ("a", cls, aux, adverbs, denied),
            ("c", cls, aux, subject, rel, denied), ("c", cls, aux, subject, denied), ("t", cls, title),
            ("c", cls, denied)]


def _clause_situations(laid: Laid, i: int) -> List[Tuple]:
    """How word i's clause hangs from the one above it: the relation, the word marking it, the word above, whether
    the sentence asks, whether "or" joins another to it."""
    mark = laid.children(i, ("mark", "cc"))
    up = laid.heads[i] - 1
    above = laid.names[up] if up >= 0 else "-"
    asks = "?" if laid.words[-1] == "?" else "."
    either = "or" if any(laid.relations[k] == "conj" and "or" in laid.children(k, ("cc",)).split("+")
                         for k in laid.under.get(i, ())) else "-"
    return [("w", laid.relations[i], mark, above, asks, either), ("r", laid.relations[i], mark, asks, either),
            ("r", laid.relations[i], asks)]


def _is_clause(laid: Laid, i: int) -> bool:
    return laid.relations[i].split(":")[0] in CLAUSES or laid.relations[i] == "root"


def _clause_of(laid: Laid, i: int) -> int:
    while not _is_clause(laid, i) and laid.heads[i]:
        i = laid.heads[i] - 1
    return i


def _sentence_situations(laid: Laid) -> List[Tuple]:
    root = laid.heads.index(0)
    subject = "subject" if any(laid.relations[k].startswith(("nsubj", "csubj", "expl"))
                               for k in laid.under.get(root, ())) else "-"
    return [("s", laid.words[-1], laid.words[0].lower(), laid.classes[0], subject),
            ("s", laid.words[-1], laid.classes[0], subject), ("s", laid.words[-1])]


# ── a lesson's meaning aligned to its words ───────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Aligned:
    """A lesson sentence's taught meaning, aligned to its words: what each word stands for (`stands`), the facts
    two words' terms hold (`pairs`, by the two words in order, each fact written `kind:>` when the first word's term
    is its subject, `kind:<` when the second's, `not ` before a denied one), the facts of one word's term and a term no
    word says (`ones`: `precedes:>?now`), the flags of each clause's facts (`flags`, by the clause's head), and the
    words in a fact no word of the sentence aligns with (`loose`), whose pairs teach nothing."""

    laid: Laid
    act: str
    stands: Mapping[int, str]
    pairs: Mapping[Tuple[int, int], Tuple[str, ...]]
    ones: Mapping[int, Tuple[str, ...]]
    flags: Mapping[int, FrozenSet[str]]
    loose: FrozenSet[int]


def taught_name(term: str, names: Sequence[str]) -> str:
    """A taught name as the sentence's word: itself, or the last word of a sense's name ("dipterous insect fly")."""
    if term.startswith("?") or term in names:
        return term
    last = term.split()[-1]
    return last if last in names else term


def align(laid: Laid, meaning: Meaning) -> Aligned:
    """A lesson's taught meaning aligned to the words of its sentence (`Aligned`)."""
    names = laid.names
    facts = [MeaningFact(f.relation, taught_name(f.subject, names), taught_name(f.obj, names), f.positive,
                         f.condition, f.alternative, f.unasserted, f.given) for f in meaning.facts]
    term: Dict[int, str] = {}
    stands: Dict[int, str] = {}
    introduced: Set[int] = set()
    for k, f in enumerate(facts):
        if f.relation == "instance_of" and f.subject.startswith("?") and f.subject not in ("?speaker", "?listener",
                                                                                             "?now"):
            for i, name in enumerate(names):
                if name == f.obj and i not in term and f.subject not in term.values():
                    term[i], stands[i] = f.subject, "known" if f.given else "thing"
                    introduced.add(k)
                    break
    mentioned = {t for k, f in enumerate(facts) if k not in introduced for t in f.terms()}
    for i, name in enumerate(names):
        if i in term or not name:
            continue
        w = laid.words[i].lower()
        situation = ("?speaker" if w in SPEAKER else "?listener" if w in LISTENER else "?previous" if w in PREVIOUS
                     else SITUATION_WORDS.get(w))
        if situation and situation in {t for f in facts for t in f.terms()} and situation not in term.values():
            term[i] = situation
            stands[i] = next(k for k, v in STANDS.items() if v == situation)
        elif w in ASKING and any(v not in term.values() for v in meaning.asked):
            term[i] = next(v for v in meaning.asked if v not in term.values())
            stands[i] = "asked"
        elif name in mentioned:
            term[i], stands[i] = name, "name"
    for i in term:
        if term[i] in meaning.asked:
            stands[i] = "asked"
    at: Dict[str, int] = {}
    for i, t in sorted(term.items()):
        at.setdefault(t, i)
    pairs: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    ones: Dict[int, List[str]] = defaultdict(list)
    loose: Set[int] = set()
    by_clause: Dict[int, List[Set[str]]] = defaultdict(list)
    for k, f in enumerate(facts):
        i, j = at.get(f.subject), at.get(f.obj)
        owner = i if i is not None else j
        if owner is not None:
            by_clause[_clause_of(laid, owner)].append(
                {name for name, on in (("condition", f.condition), ("alternative", f.alternative),
                                       ("unasserted", f.unasserted)) if on})
        if k in introduced:
            continue
        denied = "" if f.positive else "not "
        if i is not None and j is not None and i != j:
            pairs[(min(i, j), max(i, j))].append(f"{denied}{f.relation}:{'>' if i < j else '<'}")
        elif i is not None and j is None:
            ones[i].append(f"{denied}{f.relation}:>{f.obj}")
        elif j is not None and i is None:
            ones[j].append(f"{denied}{f.relation}:<{f.subject}")
        if (i is None or j is None) and not (i is not None and not f.obj.startswith("?")) \
                and not (j is not None and not f.subject.startswith("?")):
            loose |= {x for x in (i, j) if x is not None}
    return Aligned(laid, meaning.act, stands, {k: tuple(sorted(v)) for k, v in pairs.items()},
                   {k: tuple(v) for k, v in ones.items()},
                   {k: frozenset(set.intersection(*v)) for k, v in by_clause.items()}, frozenset(loose))


# ── a sentence taught with its meaning ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaughtSentence:
    """A sentence as a lesson taught it, with the meaning it was taught to have. Memory keeps one for each sentence
    of the lessons (`MemoryAgent.remember_taught_sentences`), and the composer learns from them, each read with the
    structure and names memory has when it is learned from (`CompositionView.hold`)."""

    sentence: str
    meaning: Meaning
    said_in: str = ""

    def key(self) -> str:
        return hashlib.sha256("\x1e".join([self.said_in, self.sentence, self.meaning.canonical()])
                              .encode("utf-8")).hexdigest()[:32]

    def claim(self) -> str:
        """The belief it stands on: that the sentence means what it was taught to."""
        return f'"{self.sentence}" means {self.meaning.canonical()} ({self.key()[:8]})'

    def said(self) -> str:
        """The sentence and its meaning, on two lines: memory keeps it as a record, never reads it as a claim."""
        return f'"{self.sentence}"\nmeans {self.meaning.canonical()}'

    def to_dict(self) -> Dict[str, Any]:
        return {"sentence": self.sentence, "meaning": self.meaning.to_dict(), "said_in": self.said_in}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaughtSentence":
        return cls(str(data["sentence"]), Meaning.from_dict(data["meaning"]), str(data.get("said_in") or ""))


# ── the view ──────────────────────────────────────────────────────────────────────────────────────────────────────

class CompositionView:
    """The lessons' sentences aligned to their meanings, read as memory-based learning reads them; and what stands
    behind them where they say nothing particular: PropBank's arguments (`arguments`) and the relations' senses."""

    def __init__(self, arguments: Optional[ArgumentStructureView] = None,
                 lay_out: Optional[Callable[[str], Optional[Laid]]] = None) -> None:
        self.arguments = arguments
        #: How a sentence is read and laid out (`lay`), for the sentences held whole (`hold`) and composed
        #: (`compose_sentence`): memory's structure view and names, on main.
        self.lay_out = lay_out
        self._held: List[Aligned] = []
        self._waiting: List[TaughtSentence] = []
        self._ready = False
        self._stands: Dict[Tuple, Counter] = {}
        self._pairs: Dict[Tuple, Counter] = {}
        self._ones: Dict[Tuple, Counter] = {}
        self._flags: Dict[Tuple, Counter] = {}
        self._acts: Dict[Tuple, Counter] = {}

    def __len__(self) -> int:
        return len(self._held) + len(self._waiting)

    def learn(self, laid: Laid, meaning: Meaning) -> None:
        """Hold one lesson sentence, laid out, with its taught meaning."""
        self._held.append(align(laid, meaning))
        self._ready = False

    def hold(self, taught: TaughtSentence) -> None:
        """Hold one taught sentence whole, to be read and laid out (`lay_out`) when the view is next worked out."""
        self._waiting.append(taught)
        self._ready = False

    def _work_out(self) -> None:
        if self._ready:
            return
        if self._waiting and self.lay_out is not None:
            for taught in self._waiting:
                laid = self.lay_out(taught.sentence)
                if laid is not None:
                    self._held.append(align(laid, taught.meaning))
            self._waiting = []
        grammar_met: Dict[str, Set[int]] = defaultdict(set)
        for n, aligned in enumerate(self._held):
            for labels in aligned.ones.values():
                for label in labels:
                    other = label.split(":", 1)[1][1:]
                    if other not in aligned.laid.names:
                        grammar_met[other].add(n)
        grammar = {name for name, met in grammar_met.items() if len(met) >= GRAMMAR_MET or name.startswith("?")}
        stands, pairs, ones, flags, acts = (defaultdict(Counter) for _ in range(5))
        for aligned in self._held:
            laid = aligned.laid
            for i in range(len(laid)):
                if not laid.names[i]:
                    continue
                for s in _word_situations(laid, i):
                    stands[s][aligned.stands.get(i, "none")] += 1
                if i in aligned.stands:
                    kept = "|".join(sorted(x for x in aligned.ones.get(i, ()) if x.split(":", 1)[1][1:] in grammar))
                    for s in _one_situations(laid, i):
                        ones[s][kept or "-"] += 1
            standing = sorted(aligned.stands)
            for x, i in enumerate(standing):
                for j in standing[x + 1:]:
                    said = "|".join(aligned.pairs.get((i, j), ())) or "-"
                    if said == "-" and (i in aligned.loose or j in aligned.loose):
                        continue
                    for s in _pair_situations(laid, i, j):
                        pairs[s][said] += 1
            for i, common in aligned.flags.items():
                for s in _clause_situations(laid, i):
                    flags[s]["+".join(sorted(common)) or "-"] += 1
            for s in _sentence_situations(laid):
                acts[s][aligned.act] += 1
        self._stands, self._pairs, self._ones, self._flags, self._acts = (
            dict(stands), dict(pairs), dict(ones), dict(flags), dict(acts))
        self._ready = True

    @staticmethod
    def _decide(table: Mapping[Tuple, Counter], met: Iterable[Tuple]) -> Optional[Tuple[str, Tuple]]:
        return StructureView._decide((s, table.get(s)) for s in met)

    def _flags_of(self, laid: Laid, i: int) -> Set[str]:
        """The flags word i's clause and every clause above it put on their facts."""
        flags: Set[str] = set()
        at, seen = i, set()
        while at >= 0 and at not in seen:
            seen.add(at)
            if _is_clause(laid, at):
                got = self._decide(self._flags, _clause_situations(laid, at))
                if got and got[0] != "-":
                    flags |= set(got[0].split("+"))
            at = laid.heads[at] - 1
        return flags

    def _argument(self, laid: Laid, stands: Mapping[int, str], v: int, c: int) -> Optional[Tuple[str, bool]]:
        """What PropBank's arguments say word c is to the happening word v: a fact's kind and whether it holds."""
        if self.arguments is None or laid.classes[v] != "VERB" or stands.get(v) not in ("thing", "known") \
                or c not in candidates(laid.heads, v):
            return None
        said = self.arguments.said(argument_situations(laid.words, laid.classes, laid.heads, laid.relations, v,
                                                        phrase(c, laid.heads)))
        if not said or not said.startswith("fact:"):
            return None
        parts = said.split(":")
        return parts[1], len(parts) < 3

    def _pair(self, laid: Laid, stands: Mapping[int, str], i: int, j: int) -> Optional[str]:
        """The facts word i's and word j's terms hold (i < j), as `Aligned.pairs` writes them, or None."""
        got = self._decide(self._pairs, _pair_situations(laid, i, j))
        particular = bool(got and got[1]) and got[1][0] in PARTICULAR
        if got and got[1] and not particular:
            did = self._pairs.get(got[1]) or Counter()
            if sum(did.values()) < TRUST[0] or did[got[0]] < TRUST[1] * sum(did.values()):
                got = None
        if not particular:
            for v, c in ((i, j), (j, i)):
                said = self._argument(laid, stands, v, c)
                if said:
                    kind, holds = said
                    return ("" if holds else "not ") + kind + (":>" if v == i else ":<")
            between = route(laid, _first_conjunct(laid, i), _first_conjunct(laid, j))[0]
            if between in RELATION_SENSES and (not got or got[0] == "-" or not got[1] or got[1][0] == "p"):
                return RELATION_SENSES[between]
        return got[0] if got and got[0] != "-" else None

    def compose_sentence(self, sentence: str) -> Optional[Meaning]:
        """What a sentence means, composed after it is read and laid out (`lay_out`); None where nothing is composed
        to a meaning."""
        laid = self.lay_out(sentence) if self.lay_out is not None else None
        if laid is None or not len(laid):
            return None
        try:
            return self.compose(laid)
        except ValueError:
            return None

    def compose(self, laid: Laid) -> Meaning:
        """What the sentence laid out means, composed. Raises ValueError where what is composed is no meaning (no
        fact, or facts no meaning may hold together)."""
        self._work_out()
        term: Dict[int, str] = {}
        stands: Dict[int, str] = {}
        for i in range(len(laid)):
            if not laid.names[i]:
                continue
            got = self._decide(self._stands, _word_situations(laid, i))
            if not got or got[0] == "none":
                continue
            stands[i] = got[0]
            term[i] = STANDS.get(got[0]) or (laid.names[i] if got[0] == "name" else f"?x{i}")
        flags = {i: self._flags_of(laid, i) for i in range(len(laid))}
        facts: List[MeaningFact] = []

        def add(relation: str, subject: str, obj: str, holds: bool, on: Set[str], given: bool = False) -> None:
            try:
                fact = MeaningFact(relation, subject, obj, holds, "condition" in on, "alternative" in on,
                                   "unasserted" in on, given)
            except ValueError:
                return
            if fact not in facts:
                facts.append(fact)
        for i, stood in stands.items():
            if stood in ("thing", "known"):
                add("instance_of", term[i], laid.names[i], True, flags[i] - {"alternative"}, stood == "known")
        standing = sorted(stands)
        for x, i in enumerate(standing):
            for j in standing[x + 1:]:
                said = self._pair(laid, stands, i, j)
                for label in (said.split("|") if said else ()):
                    holds = not label.startswith("not ")
                    kind, way = label.replace("not ", "").split(":")
                    subject, obj, owner = (term[i], term[j], i) if way == ">" else (term[j], term[i], j)
                    add(kind, subject, obj, holds, flags[owner])
        # A LINK SAID WITH A WORD THAT NOTHING KNOWN NAMES IS HELD AS THAT WORD, never dropped: "the capital of
        # France" is `word_of(capital, France)` where neither the lessons nor PropBank's arguments say which link "of"
        # makes there. Measured on UD English EWT's held-out sentences with main's composer (2026-10-20): of about
        # 600 nouns with a preposition after them, about one in five had a link; PropBank's verbs, asked of nouns,
        # said one of every one, mostly wrong ("judge of the Court" done to it). Where the lessons say particularly
        # that no fact holds, none is held.
        linked = {frozenset((f.subject, f.obj)) for f in facts}
        for d in sorted(stands):
            h = laid.heads[d] - 1
            if h not in stands or laid.relations[d].split(":")[0] not in MARKED \
                    or frozenset((term[h], term[d])) in linked:
                continue
            marker = " ".join(laid.words[k].lower() for k in laid.under.get(d, ())
                              if laid.relations[k].split(":")[0] == "case")
            if not marker or not all(part.isalpha() for part in marker.split()):
                continue
            i, j = min(d, h), max(d, h)
            got = self._decide(self._pairs, _pair_situations(laid, i, j))
            if got and got[1] and got[1][0] in PARTICULAR and got[0] == "-":
                continue
            add(worded(marker), term[h], term[d], True, flags[h])
        for i in stands:
            got = self._decide(self._ones, _one_situations(laid, i))
            for label in (got[0].split("|") if got and got[0] != "-" else ()):
                holds = not label.startswith("not ")
                kind, rest = label.replace("not ", "").split(":", 1)
                way, other = rest[0], rest[1:]
                subject, obj = (term[i], other) if way == ">" else (other, term[i])
                add(kind, subject, obj, holds, flags[i])
        got = self._decide(self._acts, _sentence_situations(laid))
        act = got[0] if got else "tell"
        asked = tuple(term[i] for i, stood in stands.items()
                      if stood == "asked" and any(term[i] in f.terms() for f in facts)) if act == "ask" else ()
        return Meaning(act, tuple(facts), asked)
