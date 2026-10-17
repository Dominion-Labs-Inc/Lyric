"""How the words of a sentence go together: the class each word is used as, which word each depends on, and as what
(docs/research/READING_PROSE_AT_SCALE.md).

LEARNED FROM SENTENCES ANALYSED, KEPT AS THEY WERE MET. A treebank gives sentences with each word's class and the word
it depends on (`Analysed`). Memory keeps each one whole (`MemoryAgent.remember_analysed`), its standing a belief on
that memory; nothing is reduced to rules when it is learned. Reading decides each word's class, then each step of
the sentence's structure, by what the sentences held did in the most specific situation they met that is like this
one, and where none met it, by a less specific one: memory-based learning (Daelemans & van den Bosch 2005; the
tagger of Daelemans, Zavrel, Berck & Gillis 1996; the parser of Nivre, Hall & Nilsson 2004). One case is enough to go
by: requiring more measured worse at every level, as forgetting exceptions does in memory-based learning
(Daelemans, van den Bosch & Zavrel 1999).

A word with all that depends on it is a phrase (`Structure.phrase`): "carbon dioxide and water" is "dioxide" with
"carbon", "and" and "water" under it, whatever its length or shape.

Since 2026-10-17 (14) each decision weighs every situation met, the more specific counting for more as they were met
more often (`_chances`), and keeps several readings while it reads (a beam), where it went by the most specific
situation alone; a word's class is read beside the words around it as well as their classes (`_Classes`); the
structure is chosen whole, of the trees the steps' beam kept and every two words weighed by how often two words
standing so were joined (`_Pairs`, `_best_tree`); and the sentences held are also counted with the classes reading
gives them, where it gives others (`StructureView._as_read`), so the structure is learned over classes as they are
read. All counts, kept as met.

Measured on UD English EWT, learned from its 12,544 training sentences, on its held-out ones (from the files): first
(2026-10-16) dev classes 91.9% right, the word each depends on (UAS) 73.1%, and as what (LAS) 66.2%; since
2026-10-17 (15) dev 93.1% / 78.3% / 71.6%, test 93.7% / 79.5% / 73.1% (`experiments/STRUCTURE-01` measures the same
from what the main model holds). On UD's other English treebanks of open licence, never learned from, UAS rose as
much: news and Wikipedia (PUD) 71.5% to 75.5%, fiction (The Little Prince) 76.8% to 80.8%. Published for this treebank, the words given, roughly: 85% UAS for a parser with
learned weights and no word vectors (UDPipe 1), 91 to 93% for neural ones (UDPipe 2, Stanza).
"""
from __future__ import annotations

import dataclasses
import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

#: Where nothing in a sentence held says otherwise, a word is taken for the class most words are.
_OPEN_CLASS = "NOUN"
#: A word met this often or less is also counted among words met rarely: how a word never met is decided, by its
#: ending and how it is written.
_RARE = 5
#: The word everything else depends on through the root.
ROOT = "<root>"
#: How many partial structures are kept while a sentence is read (`StructureView.structure`): one is the likeliest
#: step each time; eight let a later step outweigh an earlier one. Measured on the treebank's held-out parts
#: (2026-10-17 (13)): UAS dev 73.6% to 74.5%, test 73.8% to 75.0%.
BEAM = 8
#: How many partial readings of a sentence's classes are kept as it is read (`StructureView.classes`).
CLASS_BEAM = 4
#: How far what was done in a situation is trusted over the less specific situations, as a word's class is read: met
#: n times with t different classes, n/(n + 4t) of the way (`_chances`). Measured on the treebank's dev
#: part (2026-10-17 (14)): with 1, 2, 4 and 8 in place of 4, 92.7%, 93.0%, 93.1% and 93.0% of classes right.
CLASS_DOUBT = 4
#: Into how many parts the sentences held are split to read each part's classes as the other parts read them, so
#: that the structure is learned over classes as reading gives them, its mistakes with them, beside the classes given.
FOLDS = 10
#: A situation two words stood in, in which no two words standing so were joined, is kept only if met this often: all
#: kept, eleven million situations; so, 1.2 million, and the same UAS on dev to a tenth (2026-10-17 (14)).
KEPT_UNJOINED = 10
#: What a dependency no tree the beam kept holds is still worth beside one every tree holds: a twentieth.
UNHELD = 0.05
#: The group of a word no grouping places.
UNGROUPED = "?"

#: Which group each word of a sentence stands in, coarse and fine, by the company it keeps
#: (`StructureView.grouping`): one (coarse, fine) a word.
Grouping = Callable[[Tuple[str, ...]], Sequence[Tuple[str, str]]]


@dataclass(frozen=True)
class Analysed:
    """One sentence as it was analysed: its words, the class each is used as, the word each depends on (1 for the
    first word, 0 for the root) and as what; and where it was met (`said_in`, a treebank's sentence id), so the same
    sentence met twice is two uses, as a corpus counts it, and the same use told again is one."""

    words: Tuple[str, ...]
    classes: Tuple[str, ...]
    heads: Tuple[int, ...]
    relations: Tuple[str, ...]
    said_in: str = ""

    def __post_init__(self):
        n = len(self.words)
        if not n or not (len(self.classes) == len(self.heads) == len(self.relations) == n):
            raise ValueError("an analysed sentence gives every word a class, a head and a relation")
        if any(not 0 <= h <= n or h == i + 1 for i, h in enumerate(self.heads)):
            raise ValueError("each word depends on another word of the sentence, or on the root")
        if sum(1 for h in self.heads if h == 0) != 1:
            raise ValueError("one word of a sentence depends on the root")

    @property
    def text(self) -> str:
        return " ".join(self.words)

    def key(self) -> str:
        """The analysis's identity: one use of the sentence, analysed so, however often it is told."""
        return hashlib.sha256("\x1e".join(
            [self.said_in, "\x1f".join(self.words), "\x1f".join(self.classes), "\x1f".join(map(str, self.heads)),
             "\x1f".join(self.relations)]).encode("utf-8")).hexdigest()[:32]

    def claim(self) -> str:
        """The belief this analysis stands on: that the sentence goes together so."""
        return f'the structure of "{self.text}" ({self.key()[:8]})'

    def said(self) -> str:
        """The analysis, said plainly: each word, its class, and what it depends on as what."""
        parts = []
        for i, word in enumerate(self.words):
            head = self.heads[i]
            on = "the root" if head == 0 else f'"{self.words[head - 1]}"'
            parts.append(f'"{word}" {self.classes[i].lower()}, {self.relations[i]} of {on}')
        return f'"{self.text}": ' + "; ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {"words": list(self.words), "classes": list(self.classes), "heads": list(self.heads),
                "relations": list(self.relations), "said_in": self.said_in}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Analysed":
        return cls(tuple(data["words"]), tuple(data["classes"]), tuple(int(h) for h in data["heads"]),
                   tuple(data["relations"]), str(data.get("said_in") or ""))

    def projective(self) -> bool:
        """Whether no two of its dependencies cross: what reading step by step can build."""
        arcs = [tuple(sorted((h, d + 1))) for d, h in enumerate(self.heads)]
        return not any(a1 < a2 < b1 < b2 for a1, b1 in arcs for a2, b2 in arcs)


@dataclass(frozen=True)
class Structure:
    """A sentence read: its words, their classes, the word each depends on (0 the root) and as what."""

    words: Tuple[str, ...]
    classes: Tuple[str, ...]
    heads: Tuple[int, ...]
    relations: Tuple[str, ...]

    def dependents(self, at: int) -> List[int]:
        """The words that depend on word `at` (1-based), in order."""
        return [d + 1 for d, h in enumerate(self.heads) if h == at]

    def phrase(self, at: int) -> Tuple[int, int]:
        """The words word `at` heads, itself with all that depends on it: (first, last), 1-based."""
        span = [at]
        for d in self.dependents(at):
            first, last = self.phrase(d)
            span += [first, last]
        return min(span), max(span)

    def phrases(self) -> List[Tuple[str, str, str]]:
        """Each word's phrase, as (relation, head word, the phrase's words)."""
        out = []
        for at in range(1, len(self.words) + 1):
            first, last = self.phrase(at)
            out.append((self.relations[at - 1], self.words[at - 1], " ".join(self.words[first - 1:last])))
        return out


def _distance(a: int, b: int) -> int:
    d = abs(a - b)
    return 1 if d == 1 else 2 if d == 2 else 3 if d <= 4 else 4 if d <= 8 else 5


def _written(word: str) -> str:
    """How a word is written, apart from what it is: a capital, a digit, a hyphen, no letters or digits at all."""
    return (("C" if word[:1].isupper() else "c") + ("d" if any(ch.isdigit() for ch in word) else "")
            + ("-" if "-" in word else "") + ("." if not any(ch.isalnum() for ch in word) else ""))


def _chances(met: Iterable[Tuple[Tuple, Optional[Counter]]], allowed: Callable[[str], bool],
             doubt: float = 1.0) -> Dict[str, float]:
    """How likely each allowed choice is here, from every situation met: the least specific first, each more specific
    one counting as Witten-Bell weighs it (met n times with t different choices, n/(n + doubt·t) of the way, the rest
    left to the less specific). Counts only."""
    chances: Dict[str, float] = {}
    for _, did in reversed(list(met)):
        if not did:
            continue
        options = {choice: n for choice, n in did.items() if allowed(choice)}
        if not options:
            continue
        n = sum(options.values())
        weight = n / (n + doubt * len(options))
        chances = {choice: weight * options.get(choice, 0) / n + (1 - weight) * chances.get(choice, 0.0)
                   for choice in set(chances) | set(options)}
    return chances


class _Classes:
    """What sentences analysed say of the class each word is used as: the situations each word was met in, from the
    most specific to the least (the word, the words beside it, the classes before it, the classes the words after it
    were used as), and the classes it was used as there; for a word met rarely, the same by its ending and how it is
    written, which is how a word never met is read. Where words are grouped (`StructureView.grouping`), a word's
    group stands beside the word: under it for a word met, above its ending for a word never met."""

    def __init__(self, sentences: Iterable["Analysed"], groups: Optional[Callable[[Sequence[str]], Sequence]] = None
                 ) -> None:
        self._groups = groups
        held = list(sentences)
        classes_of: Dict[str, set] = defaultdict(set)
        met: Counter = Counter()
        for analysed in held:
            for word, cls in zip(analysed.words, analysed.classes):
                classes_of[word].add(cls)
                met[word] += 1
        self._classes_of = {word: frozenset(cs) for word, cs in classes_of.items()}
        known: Dict[Tuple, Counter] = defaultdict(Counter)
        unknown: Dict[Tuple, Counter] = defaultdict(Counter)
        for analysed in held:
            words, classes = analysed.words, analysed.classes
            for i, cls in enumerate(classes):
                for situation in self.situations(words, classes, i, met=True):
                    known[situation][cls] += 1
                if met[words[i]] <= _RARE:
                    for situation in self.situations(words, classes, i, met=False):
                        unknown[situation][cls] += 1
        self._known, self._unknown = dict(known), dict(unknown)

    def met(self, word: str) -> bool:
        return word in self._classes_of or word.lower() in self._classes_of

    def _ambiguity(self, word: Optional[str]) -> str:
        if word is None:
            return "</s>"
        classes = self._classes_of.get(word) or self._classes_of.get(word.lower())
        return "|".join(sorted(classes)) if classes else "?"

    def situations(self, words: Sequence[str], classes: Sequence[str], i: int, *, met: bool) -> List[Tuple]:
        """The situations word `i` stands in, the most specific first, the words before it read as `classes`. A word
        met only as written otherwise ("Snow" first in a sentence, met as "snow") stands as it was met."""
        word = words[i] if not met or words[i] in self._classes_of else words[i].lower()
        before = classes[i - 1] if i >= 1 else "<s>"
        after = self._ambiguity(words[i + 1] if i + 1 < len(words) else None)
        coarse, fine = self._groups(words)[i] if self._groups is not None else (None, None)
        if met:
            before_two = classes[i - 2] if i >= 2 else "<s>"
            last = words[i - 1].lower() if i >= 1 else "<s>"
            next_word = words[i + 1].lower() if i + 1 < len(words) else "</s>"
            after_two = self._ambiguity(words[i + 2] if i + 2 < len(words) else None)
            return [("beside", word, last, before, next_word), ("before, next", word, before_two, before, after,
                                                                 next_word),
                    ("last", word, last, before, after), ("next", word, before, next_word),
                    ("before, after", word, before_two, before, after, after_two), ("around", word, before, after),
                    ("last only", word, last, before), ("next only", word, next_word), ("before only", word, before),
                    ("after only", word, after), ("word", word)] + (
                [("group", fine, before, after), ("coarse group", coarse, before, after)] if fine is not None else [])
        lower, written = word.lower(), _written(word)
        first = "first" if i == 0 else "later"
        grouped = ([("group", fine, written, first, before, after), ("coarse group", coarse, written, before, after)]
                   if fine is not None else [])
        return grouped + [
                ("ends 5", lower[-5:], written, first, before, after), ("ends 4", lower[-4:], written, first, before,
                                                                         after),
                ("ends 3", lower[-3:], written, first, before, after), ("ends 3 before", lower[-3:], written, before),
                ("ends 2 before", lower[-2:], written, before), ("ends 1 before", lower[-1:], written, before),
                ("written", written, first, before, after), ("written before", written, before),
                ("written only", written)]

    def read(self, words: Sequence[str],
             held_classes: Optional[Callable[[str], Mapping[str, int]]] = None) -> Tuple[str, ...]:
        """The class each word is used as here, read left to right, the likeliest `CLASS_BEAM` partial readings kept,
        each by how likely its classes were (`_chances`). A word no sentence held used takes a class memory holds of
        it, where it holds one (`held_classes`)."""
        beam: List[Tuple[float, Tuple[str, ...]]] = [(0.0, ())]
        for i, word in enumerate(words):
            met = self.met(word)
            held = held_classes(word) if not met and held_classes is not None else {}
            allowed = (lambda c: c in held) if held else (lambda _: True)
            grown = []
            for score, chosen in beam:
                chances = _chances(((s, self._known.get(s)) for s in self.situations(words, chosen, i, met=True)),
                                   allowed, CLASS_DOUBT) if met else {}
                if not chances:
                    chances = _chances(((s, self._unknown.get(s))
                                        for s in self.situations(words, chosen, i, met=False)), allowed, CLASS_DOUBT)
                if not chances:
                    chances = {max((n, c) for c, n in held.items())[1] if held else _OPEN_CLASS: 1.0}
                for cls, chance in sorted(chances.items(), key=lambda kv: (-kv[1], kv[0]))[:CLASS_BEAM]:
                    if chance > 0:
                        grown.append((score + math.log(chance), chosen + (cls,)))
            beam = sorted(grown, key=lambda kept: -kept[0])[:CLASS_BEAM]
        return beam[0][1] if beam else ()


def _apart(a: int, b: int) -> int:
    d = abs(a - b)
    return d if d <= 3 else 4 if d <= 5 else 6 if d <= 10 else 11


#: The classes counted as a verb standing between two words.
_VERBS = frozenset({"VERB", "AUXILIARY"})


class _Pairs:
    """How often two words standing so were joined, the first the head of the second: for every two words of the
    sentences held, the situations they stood in, from the most specific to the least (both words and classes; one
    word; the classes, which way and how far apart, how many verbs and marks stand between, the classes beside each),
    how often two words standing so were met, and how often joined. And as what each pair joined was joined.

    Each situation is held by its hash: eleven million are met in the English Web Treebank's training part, read both
    ways; counted as words they took 1.2 gigabytes, as hashes 0.4, and the chance that any two of them share a hash
    is about one in three million."""

    #: The situations two words stand in, the most specific first: both words; the head's word; the dependent's;
    #: then by their classes alone, with the classes around each, around one, the verbs and marks between, how far
    #: apart, which way. Where words are grouped, by their groups after their words (`GROUPED_LEVELS`).
    LEVELS = ("words", "head word", "dependent word", "around both", "around dependent", "around head", "between",
              "far", "side")
    GROUPED_LEVELS = LEVELS[:3] + ("groups", "head group", "dependent group", "coarse groups") + LEVELS[3:]

    def __init__(self, sentences: Iterable["Analysed"], groups: Optional[Callable[[Sequence[str]], Sequence]] = None
                 ) -> None:
        self._groups = groups
        self.levels = self.GROUPED_LEVELS if groups is not None else self.LEVELS
        held = [(self.laid(a.words, a.classes, groups(a.words) if groups is not None else None), a.heads,
                 a.relations) for a in sentences]
        self._met: List[Dict[int, int]] = []
        self._joined: List[Dict[int, int]] = []
        for level in self.levels:
            met: Dict[int, int] = defaultdict(int)
            joined: Dict[int, int] = defaultdict(int)
            for laid, heads, _ in held:
                for d in range(1, len(heads) + 1):
                    head = heads[d - 1]
                    for h in range(len(heads) + 1):
                        if h != d:
                            situation = hash(self._situation(laid, h, d, level))
                            met[situation] += 1
                            if h == head:
                                joined[situation] += 1
            self._met.append({s: n for s, n in met.items() if n >= KEPT_UNJOINED or s in joined})
            self._joined.append(dict(joined))
        said: List[Dict[Tuple, Counter]] = [defaultdict(Counter) for _ in self._relation_situations(held[0][0], 0, 1)
                                            ] if held else []
        for laid, heads, relations in held:
            for d, head in enumerate(heads, 1):
                for level, situation in zip(said, self._relation_situations(laid, head, d)):
                    level[situation][relations[d - 1]] += 1
        self._said = [dict(level) for level in said]

    @staticmethod
    def laid(words: Sequence[str], classes: Sequence[str], groups: Optional[Sequence[Tuple[str, str]]] = None
             ) -> Tuple:
        """A sentence laid out for its pairs: its words (lowered) and classes from the root (0) to a mark past its
        end, how many verbs and how many marks stand before each word, and each word's groups, fine and coarse, where
        words are grouped."""
        w = (ROOT,) + tuple(word.lower() for word in words) + ("</s>",)
        c = ("ROOT",) + tuple(classes) + ("</s>",)
        verbs, marks = [0], [0]
        for cls in c:
            verbs.append(verbs[-1] + (cls in _VERBS))
            marks.append(marks[-1] + (cls == "PUNCTUATION"))
        if groups is None:
            return w, c, verbs, marks, None, None
        fine = (ROOT,) + tuple(g for _, g in groups) + ("</s>",)
        coarse = (ROOT,) + tuple(g for g, _ in groups) + ("</s>",)
        return w, c, verbs, marks, fine, coarse

    @staticmethod
    def _situation(laid: Tuple, h: int, d: int, level: str) -> Tuple:
        """The situation of word `h` as the head of word `d`, at `level` (`LEVELS`)."""
        w, c, verbs, marks, g, coarse = laid
        side = "<" if h < d else ">"
        if level == "side":
            return c[h], c[d], side
        far = _apart(h, d)
        if level == "far":
            return c[h], c[d], side, far
        if level == "words":
            return w[h], c[h], w[d], c[d], side, far
        lo, hi = (h, d) if h < d else (d, h)
        between = min(verbs[hi] - verbs[lo + 1], 2), min(marks[hi] - marks[lo + 1], 2)
        if level == "head word":
            return w[h], c[h], c[d], side, far, between
        if level == "dependent word":
            return c[h], w[d], c[d], side, far, between
        if level == "groups":
            return level, g[h], c[h], g[d], c[d], side, far, between
        if level == "head group":
            return level, g[h], c[h], c[d], side, far, between
        if level == "dependent group":
            return level, c[h], g[d], c[d], side, far, between
        if level == "coarse groups":
            return level, coarse[h], c[h], coarse[d], c[d], side, far, between
        if level == "between":
            return c[h], c[d], side, far, between
        around_d = c[d - 1], c[d + 1]
        if level == "around dependent":
            return c[h], c[d], side, far, between, around_d
        around_h = c[h - 1] if h > 0 else "<s>", c[h + 1]
        if level == "around head":
            return c[h], c[d], side, far, between, around_h
        return c[h], c[d], side, far, between, around_h, around_d

    def chance(self, laid: Tuple, h: int, d: int) -> float:
        """How likely word `h` is the head of word `d`: of the pairs met standing so, the share joined, each
        situation from the least specific up counting as Witten-Bell weighs it (`_chances`)."""
        chance = 0.0
        for at in range(len(self.levels) - 1, -1, -1):
            situation = hash(self._situation(laid, h, d, self.levels[at]))
            n = self._met[at].get(situation, 0)
            if not n:
                continue
            joined = self._joined[at].get(situation, 0)
            weight = n / (n + (joined > 0) + (joined < n))
            chance = weight * joined / n + (1 - weight) * chance
        return chance

    @staticmethod
    def _relation_situations(laid: Tuple, h: int, d: int) -> List[Tuple]:
        w, c, _, _, g, _ = laid
        side, far = ("<" if h < d else ">"), _apart(h, d)
        return [(w[h], c[h], w[d], c[d], side)] + ([("groups", g[h], c[h], g[d], c[d], side)] if g else []) + [
            (c[h], w[d], c[d], side, far), (w[h], c[h], c[d], side), (c[h], c[d], side, far, c[d + 1]),
            (c[h], c[d], side), (c[d],)]

    def relation(self, laid: Tuple, h: int, d: int) -> str:
        """As what word `d` depends on word `h`, as the pairs joined in the most specific situation like it were."""
        decided = StructureView._decide(((s, level.get(s)) for level, s in
                                         zip(self._said, self._relation_situations(laid, h, d))),
                                        lambda relation: relation != "root")
        return decided[0] if decided else "dep"


def _best_tree(scores: "np.ndarray") -> List[int]:
    """The tree over words 1..n, one word under the root (0), whose dependencies' scores (`scores[h, d]`, word `h`
    the head of word `d`) sum highest, of the trees no two of whose dependencies cross: Eisner's algorithm (1996),
    built from the shortest spans up. The head of each word, 1-based."""
    n = scores.shape[0] - 1
    inner = scores[1:, 1:]
    least = -1e18
    # Spans s..t: open (`o`) with a dependency between s and t still to be completed, or complete (`c`); headed at
    # the left end (`r`, its dependents to the right) or the right end (`l`).
    o_l, o_r, c_l, c_r = (np.full((n, n), least) for _ in range(4))
    at_o_l, at_o_r, at_c_l, at_c_r = (np.zeros((n, n), dtype=int) for _ in range(4))
    for s in range(n):
        c_l[s, s] = c_r[s, s] = 0.0
    for k in range(1, n):
        for s in range(0, n - k):
            t = s + k
            joined = c_r[s, s:t] + c_l[s + 1:t + 1, t]
            r = int(np.argmax(joined))
            o_l[s, t], at_o_l[s, t] = joined[r] + inner[t, s], s + r
            o_r[s, t], at_o_r[s, t] = joined[r] + inner[s, t], s + r
            left = c_l[s, s:t] + o_l[s:t, t]
            r = int(np.argmax(left))
            c_l[s, t], at_c_l[s, t] = left[r], s + r
            right = o_r[s, s + 1:t + 1] + c_r[s + 1:t + 1, t]
            r = int(np.argmax(right))
            c_r[s, t], at_c_r[s, t] = right[r], s + 1 + r
    root = int(np.argmax([scores[0, r + 1] + c_l[0, r] + c_r[r, n - 1] for r in range(n)]))
    heads = [0] * n
    spans = [("c", 0, root, False), ("c", root, n - 1, True)]
    while spans:
        kind, s, t, rightward = spans.pop()
        if s == t:
            continue
        if kind == "c":
            if rightward:
                q = int(at_c_r[s, t])
                spans += [("o", s, q, True), ("c", q, t, True)]
            else:
                q = int(at_c_l[s, t])
                spans += [("c", s, q, False), ("o", q, t, False)]
            continue
        if rightward:
            heads[t] = s + 1
            q = int(at_o_r[s, t])
        else:
            heads[s] = t + 1
            q = int(at_o_l[s, t])
        spans += [("c", s, q, True), ("c", q + 1, t, False)]
    return heads


class StructureView:
    """The analysed sentences memory holds, read as memory-based learning reads them: for each decision, the
    situations the sentences met it in, from the most specific to the least, and what they did there.

    Sentences are added one at a time as memory holds them (`add`); the situations are worked out from all of them
    when next read, since how often a word was met decides where it counts."""

    def __init__(self) -> None:
        self._held: Dict[str, Analysed] = {}
        self._ready = False
        self._classes = _Classes(())
        self._steps: List[Dict[Tuple, Counter]] = []
        self._pairs: Optional[_Pairs] = None
        #: What memory holds of a word's class, from all it was taught (`held_classes`), asked only of a word no
        #: sentence held used: its class is then one of those, as the situations decide. None asks nothing, and a
        #: word never met is decided by its ending and how it is written alone.
        self.held_classes: Optional[Callable[[str], Mapping[str, int]]] = None
        #: Which group each word of a sentence stands in by the company it keeps, coarse and fine (`Grouping`);
        #: weighed beside the word wherever a word is, and in its place where the word was met rarely or never. None
        #: groups nothing, and the situations are as they were (`experiments/GROUPS-01`).
        self.grouping: Optional[Grouping] = None
        self._grouped: Dict[Tuple[str, ...], Tuple[Tuple[str, str], ...]] = {}

    def __len__(self) -> int:
        return len(self._held)

    def __contains__(self, key: str) -> bool:
        return key in self._held

    def _groups(self, words: Sequence[str]) -> Optional[Tuple[Tuple[str, str], ...]]:
        """Each word's groups, coarse and fine, as `grouping` places the sentence's words; None where nothing groups
        them. Asked once a sentence."""
        if self.grouping is None:
            return None
        key = tuple(words)
        if key not in self._grouped:
            self._grouped[key] = tuple((str(coarse), str(fine)) for coarse, fine in self.grouping(key))
        return self._grouped[key]

    def add(self, analysed: Analysed) -> bool:
        """Hold one analysed sentence. False if it was held."""
        key = analysed.key()
        if key in self._held:
            return False
        self._held[key] = analysed
        self._ready = False
        return True

    # ── what each step of the structure is ────────────────────────────────────

    _LEVELS = 9

    @staticmethod
    def _step_situations(words: Sequence[str], classes: Sequence[str], stack: Sequence[int], waiting: Sequence[int],
                         under: Mapping[int, List[int]], relation: Mapping[int, str],
                         groups: Optional[Sequence[str]] = None) -> List[Tuple]:
        def w(i):
            return words[i] if i is not None else "-"

        def g(i):
            return groups[i] if i is not None else "-"

        def c(i):
            return classes[i] if i is not None else "-"

        def first_under(i):
            if i is None:
                return "-"
            left = [k for k in under.get(i, ()) if k < i]
            return relation.get(min(left)) if left else "-"

        def last_under(i):
            if i is None:
                return "-"
            right = [k for k in under.get(i, ()) if k > i]
            return relation.get(max(right)) if right else "-"
        s0 = stack[-1] if stack else None
        s1 = stack[-2] if len(stack) >= 2 else None
        s2 = stack[-3] if len(stack) >= 3 else None
        b0 = waiting[0] if waiting else None
        b1 = waiting[1] if len(waiting) >= 2 else None
        far = _distance(s0, s1) if s0 is not None and s1 is not None else 0
        grouped = [("groups", g(s1), g(s0), g(b0), c(s1), c(s0), c(b0), last_under(s1), first_under(s0)),
                   ("group", g(s0), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0))
                   ] if groups is not None else []
        return [
            (w(s1), w(s0), w(b0), c(s1), c(s0), c(b0), last_under(s1), first_under(s0)),
            (w(s1), w(s0), c(s1), c(s0), c(b0), last_under(s1), first_under(s0)),
            (w(s0), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0)),
            (w(s1), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0)),
        ] + grouped + [
            (c(s2), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0), far),
            (c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), far),
            (c(s1), c(s0), c(b0), first_under(s0), far),
            (c(s1), c(s0), c(b0)),
            (c(s1), c(s0)),
        ]

    def _work_out(self) -> None:
        """The situations of every held sentence, and what it did in each: of each word's class, of each step of
        its structure and of each two of its words, over the classes given and the classes reading gives
        (`_as_read`)."""
        if self._ready:
            return
        held = list(self._held.values())
        groups = self._groups if self.grouping is not None else None
        self._classes = _Classes(held, groups)
        both = self._as_read(held, groups)
        steps: List[Dict[Tuple, Counter]] = [defaultdict(Counter)
                                             for _ in range(self._LEVELS + (2 if groups is not None else 0))]
        for analysed in both:
            if not analysed.projective():
                continue
            for situations, step in self._steps_of(analysed):
                for level, situation in zip(steps, situations):
                    level[situation][step] += 1
        self._steps = [dict(level) for level in steps]
        self._pairs = _Pairs(both, groups)
        self._ready = True

    @staticmethod
    def _as_read(held: Sequence[Analysed], groups: Optional[Callable[[Sequence[str]], Sequence]] = None
                 ) -> List[Analysed]:
        """Each sentence held as it was analysed, and, where reading gives its words other classes, as read: split
        into `FOLDS` parts by its key, each part's classes read by what the other parts say, as the treebank alone
        decides, its structure as given. Learned over both, a step or a pair is known in the situations reading meets
        it in, a class read wrong among them (2026-10-17 (14)): UAS on dev 77.4% to 78.0%."""
        parts = min(FOLDS, len(held))
        if parts < 2:
            return list(held)
        both = {analysed.key(): analysed for analysed in held}
        for part in range(parts):
            others = _Classes((a for a in held if int(a.key()[:8], 16) % parts != part), groups)
            for analysed in held:
                if int(analysed.key()[:8], 16) % parts == part:
                    read = dataclasses.replace(analysed, classes=others.read(analysed.words))
                    both.setdefault(read.key(), read)
        return list(both.values())

    def _steps_of(self, analysed: Analysed) -> Iterable[Tuple[List[Tuple], str]]:
        """The steps that build this sentence's structure, each with the situations it was taken in: SHIFT the next
        word on, or attach the word below the top to the top (`L:relation`) or the top to the word below it
        (`R:relation`)."""
        words = (ROOT,) + tuple(word.lower() for word in analysed.words)
        classes = ("ROOT",) + analysed.classes
        grouped = self._groups(analysed.words)
        groups = (ROOT,) + tuple(fine for _, fine in grouped) if grouped is not None else None
        heads = (None,) + analysed.heads
        relations = (None,) + analysed.relations
        owed = Counter(analysed.heads)
        stack, waiting = [0], list(range(1, len(words)))
        under: Dict[int, List[int]] = defaultdict(list)
        relation: Dict[int, str] = {}
        while waiting or len(stack) > 1:
            if len(stack) >= 2 and stack[-2] != 0 and heads[stack[-2]] == stack[-1]:
                step = "L:" + relations[stack[-2]]
            elif len(stack) >= 2 and heads[stack[-1]] == stack[-2] and owed[stack[-1]] == 0 \
                    and (stack[-2] != 0 or not waiting):
                step = "R:" + relations[stack[-1]]
            else:
                step = "S"
            yield self._step_situations(words, classes, stack, waiting, under, relation, groups), step
            self._take(step, stack, waiting, under, relation)
            if step != "S":
                owed[stack[-1]] -= 1

    @staticmethod
    def _take(step: str, stack: List[int], waiting: List[int], under: Dict[int, List[int]],
              relation: Dict[int, str]) -> Optional[Tuple[int, int]]:
        """Take one step; the (dependent, head) it attached, if it attached one."""
        if step == "S":
            stack.append(waiting.pop(0))
            return None
        dependent = stack.pop(-2) if step.startswith("L") else stack.pop()
        under[stack[-1]].append(dependent)
        relation[dependent] = step[2:]
        return dependent, stack[-1]

    # ── reading ───────────────────────────────────────────────────────────────

    @staticmethod
    def _decide(met: Iterable[Tuple[Tuple, Optional[Counter]]],
                allowed: Callable[[str], bool] = lambda _: True) -> Optional[Tuple[str, Tuple]]:
        """What the sentences held did most in the most specific of these situations they met (each given with what
        was done in it), of what is allowed here, and the situation it went by. Where they did two or more things
        equally often, the next, less specific situation decides between those, never the order of their names
        ("whale" after "a", a word never met: its ending split once a noun, once an adjective, once a verb). If no
        situation tells them apart, the first tie stands."""
        first, tied = None, None
        for situation, did in met:
            if not did:
                continue
            options = [(times, choice) for choice, times in did.items()
                       if allowed(choice) and (tied is None or choice in tied)]
            if not options:
                continue
            most = max(times for times, _ in options)
            top = {choice for times, choice in options if times == most}
            if len(top) == 1:
                return top.pop(), situation
            if first is None:
                first = max(options)[1], situation
            tied = top
        return first

    def classes(self, words: Sequence[str]) -> Tuple[str, ...]:
        """The class each word is used as here (`_Classes.read`). A word no sentence held used takes a class memory
        holds of it, where it holds one (`held_classes`): "whale" after "A" is a noun, not the verb its ending gave
        it."""
        self._work_out()
        return self._classes.read(words, self.held_classes)

    def structure(self, words: Sequence[str], classes: Sequence[str]) -> Structure:
        """Which word each depends on, and as what, decided by two readings of the sentence held together. The steps
        that build it are searched with a beam (`BEAM`), each partial structure kept by how likely its steps were
        (`_chances`), so a later step can outweigh an earlier one. And every two words are weighed whole, by how often
        two words standing so were joined (`_Pairs`). The tree taken is the one whose dependencies are likeliest by
        both (`_best_tree`): each by its pair's chance, times the share of the beam's trees that hold it (a dependency
        none holds still worth `UNHELD`). Measured (2026-10-17 (14)): UAS on dev 74.5% by the beam alone, 78.0% so.
        Each dependency is as the beam's likeliest tree says where that tree holds it, else as the pairs joined in
        the most specific situation like it were."""
        return self.readings_apart(words, classes)[0]

    def readings_apart(self, words: Sequence[str], classes: Sequence[str]
                       ) -> Tuple[Structure, Tuple[int, ...], Tuple[int, ...]]:
        """The structure read (`structure`), with the head of each word as each reading alone has it: the tree the
        steps' beam likes best, and the tree the pairs alone like best (`_best_tree` over the pairs' chances, nothing
        of the beam's). Learned apart from the same sentences, the two err apart: where they agree, the reading is
        confirmed, and a sentence never taught can be kept as analysed so (`experiments/SELF-TEACH-01`)."""
        self._work_out()
        beam = self._beam(words, classes)
        n = len(words)
        best = beam[0][0]
        shares = [math.exp(score - best) for score, *_ in beam]
        held = np.zeros((n + 1, n + 1))
        for (_, _, _, heads, _, _), share in zip(beam, shares):
            for d in range(1, n + 1):
                held[heads[d], d] += share / sum(shares)
        laid, chances = self._pair_chances(words, classes)
        heads = _best_tree(chances + np.log(held + UNHELD))
        _, _, _, beam_heads, _, beam_relation = beam[0]
        relations = tuple("root" if heads[d - 1] == 0 else beam_relation.get(d, "dep")
                          if heads[d - 1] == beam_heads[d] else self._pairs.relation(laid, heads[d - 1], d)
                          for d in range(1, n + 1))
        return (Structure(tuple(words), tuple(classes), tuple(heads), relations), tuple(beam_heads[1:]),
                tuple(_best_tree(chances)))

    def _pair_chances(self, words: Sequence[str], classes: Sequence[str]) -> Tuple[Tuple, "np.ndarray"]:
        """The sentence laid out for its pairs, and the log chance that word h is the head of word d, `[h, d]`."""
        n = len(words)
        laid = _Pairs.laid(words, classes, self._groups(words))
        chances = np.full((n + 1, n + 1), -1e9)
        for d in range(1, n + 1):
            for h in range(n + 1):
                if h != d:
                    chances[h, d] = math.log(max(self._pairs.chance(laid, h, d), 1e-12))
        return laid, chances

    def _beam(self, words: Sequence[str], classes: Sequence[str]) -> List[Tuple]:
        """The structures the steps' beam keeps at the end (`BEAM`), likeliest first: each (score, stack, waiting,
        heads by word from 1, dependents, relations)."""
        lowered = (ROOT,) + tuple(word.lower() for word in words)
        with_root = ("ROOT",) + tuple(classes)
        grouped = self._groups(words)
        groups = (ROOT,) + tuple(fine for _, fine in grouped) if grouped is not None else None

        def allowed(stack: Sequence[int], waiting: Sequence[int]) -> Callable[[str], bool]:
            def ok(step: str) -> bool:
                if step == "S":
                    return bool(waiting)
                if len(stack) < 2:
                    return False
                if step.startswith("L"):
                    return stack[-2] != 0
                return stack[-2] != 0 or not waiting
            return ok
        beam = [(0.0, [0], list(range(1, len(lowered))), [0] * len(lowered), defaultdict(list), {})]
        while any(waiting or len(stack) > 1 for _, stack, waiting, _, _, _ in beam):
            grown = []
            for score, stack, waiting, heads, under, relation in beam:
                if not waiting and len(stack) <= 1:
                    grown.append((score, stack, waiting, heads, under, relation))
                    continue
                situations = self._step_situations(lowered, with_root, stack, waiting, under, relation, groups)
                chances = _chances(((s, level.get(s)) for level, s in zip(self._steps, situations)),
                                   allowed(stack, waiting))
                if not chances:
                    chances = {("S" if waiting else "R:dep"): 1.0}
                for step, chance in sorted(chances.items(), key=lambda kv: (-kv[1], kv[0]))[:BEAM]:
                    if chance <= 0:
                        continue
                    stack2, waiting2, heads2 = list(stack), list(waiting), list(heads)
                    under2 = defaultdict(list, {k: list(v) for k, v in under.items()})
                    relation2 = dict(relation)
                    attached = self._take(step, stack2, waiting2, under2, relation2)
                    if attached is not None:
                        dependent, head = attached
                        heads2[dependent] = head
                        if head == 0:
                            relation2[dependent] = "root"
                    grown.append((score + math.log(chance), stack2, waiting2, heads2, under2, relation2))
            beam = sorted(grown, key=lambda kept: -kept[0])[:BEAM]
        return beam

    def read(self, words: Sequence[str]) -> Structure:
        """How these words go together: their classes, then their structure."""
        return self.structure(words, self.classes(words))


#: The word-class view's classes by the treebank's names. A NOUN is the treebank's noun or its name: the view holds no
#: name apart from a noun (WordNet files "Boston" as a noun), and the situations tell the two apart, as they did
#: before memory was asked. Held as a noun only, the proper names of the treebank's held-out text (40% of its words
#: never met) were all read as nouns (2026-10-16 (10)).
_HELD_AS = {"MODAL": ("AUXILIARY",), "COPULA": ("AUXILIARY",), "QUANTIFIER": ("DETERMINER",),
            "NOUN": ("NOUN", "NAME")}


def held_classes(inventory: Any) -> Callable[[str], Dict[str, int]]:
    """What memory holds of a word's classes, by the treebank's names, for `StructureView.held_classes`: the classes
    the reader's view observed the word in with net evidence for them (`PatternInventory.word_classes`); for a word
    it holds none of, those of the held words it is written as a shape of (`names_of_shape`: "breathes" is `breathe`,
    by a change learned from the lessons). Empty for a word memory knows nothing of."""
    def of(word: str) -> Dict[str, int]:
        folded = word.casefold()
        for name in [folded] + [n for n in inventory.names_of_shape(folded) if n != folded]:
            counts: Dict[str, int] = {}
            for cls, n in inventory.word_classes.get(name, {}).items():
                if n > 0:
                    for named in _HELD_AS.get(cls, (cls,)):
                        counts[named] = counts.get(named, 0) + n
            if counts:
                return counts
        return {}
    return of


def words_of(pieces: Iterable[Any]) -> Tuple[str, ...]:
    """A sentence's pieces (`sentence_machine.form_of`) as the words a treebank writes: "doesn't" is "does" and
    "n't" there, where the pieces are "doesn" and "'t"."""
    words: List[str] = []
    for piece in pieces:
        text = getattr(piece, "text", piece)
        if text in ("'t", "’t") and words and words[-1][-1:].lower() == "n":
            words[-1] = words[-1][:-1]
            text = "n't"
        words.append(text)
    return tuple(words)
