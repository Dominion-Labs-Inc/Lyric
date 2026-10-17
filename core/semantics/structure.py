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

Measured on UD English EWT, learned from its 12,544 training sentences, on its 2,001 held-out ones (2026-10-16, from
the files): classes 91.9% right; the word each depends on 73.1% right, and as what 66.2% (`experiments/STRUCTURE-01`
measures the same from what the main model holds).
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


class StructureView:
    """The analysed sentences memory holds, read as memory-based learning reads them: for each decision, the
    situations the sentences met it in, from the most specific to the least, and what they did there.

    Sentences are added one at a time as memory holds them (`add`); the situations are worked out from all of them
    when next read, since how often a word was met decides where it counts."""

    def __init__(self) -> None:
        self._held: Dict[str, Analysed] = {}
        self._ready = False
        self._known: Dict[Tuple, Counter] = {}
        self._unknown: Dict[Tuple, Counter] = {}
        self._steps: List[Dict[Tuple, Counter]] = []
        self._classes_of: Dict[str, frozenset] = {}
        #: What memory holds of a word's class, from all it was taught (`held_classes`), asked only of a word no
        #: sentence held used: its class is then one of those, as the situations decide. None asks nothing, and a
        #: word never met is decided by its ending and how it is written alone.
        self.held_classes: Optional[Callable[[str], Mapping[str, int]]] = None

    def __len__(self) -> int:
        return len(self._held)

    def __contains__(self, key: str) -> bool:
        return key in self._held

    def add(self, analysed: Analysed) -> bool:
        """Hold one analysed sentence. False if it was held."""
        key = analysed.key()
        if key in self._held:
            return False
        self._held[key] = analysed
        self._ready = False
        return True

    # ── what each word is used as ─────────────────────────────────────────────

    def _ambiguity(self, word: Optional[str]) -> str:
        if word is None:
            return "</s>"
        classes = self._classes_of.get(word) or self._classes_of.get(word.lower())
        return "|".join(sorted(classes)) if classes else "?"

    def _class_situations(self, words: Sequence[str], classes: Sequence[str], i: int, *, met: bool) -> List[Tuple]:
        word = words[i]
        before = classes[i - 1] if i >= 1 else "<s>"
        before_two = classes[i - 2] if i >= 2 else "<s>"
        after = self._ambiguity(words[i + 1] if i + 1 < len(words) else None)
        after_two = self._ambiguity(words[i + 2] if i + 2 < len(words) else None)
        next_word = words[i + 1].lower() if i + 1 < len(words) else "</s>"
        if met:
            return [("met", word, before_two, before, after, next_word), ("met", word, before_two, before, after,
                                                                          after_two),
                    ("met", word, before, after), ("met", word, before), ("met", word, after), ("met", word)]
        lower, written = word.lower(), _written(word)
        return [("new", lower[-4:], written, before, after), ("new", lower[-3:], written, before, after),
                ("new", lower[-3:], written, before), ("new", lower[-2:], written, before),
                ("new", lower[-1:], written, before), ("new", written, before, after), ("new", written, before),
                ("new", written)]

    # ── what each step of the structure is ────────────────────────────────────

    _LEVELS = 9

    @staticmethod
    def _step_situations(words: Sequence[str], classes: Sequence[str], stack: Sequence[int], waiting: Sequence[int],
                         under: Mapping[int, List[int]], relation: Mapping[int, str]) -> List[Tuple]:
        def w(i):
            return words[i] if i is not None else "-"

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
        return [
            (w(s1), w(s0), w(b0), c(s1), c(s0), c(b0), last_under(s1), first_under(s0)),
            (w(s1), w(s0), c(s1), c(s0), c(b0), last_under(s1), first_under(s0)),
            (w(s0), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0)),
            (w(s1), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0)),
            (c(s2), c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), last_under(s0), far),
            (c(s1), c(s0), c(b0), c(b1), last_under(s1), first_under(s0), far),
            (c(s1), c(s0), c(b0), first_under(s0), far),
            (c(s1), c(s0), c(b0)),
            (c(s1), c(s0)),
        ]

    def _work_out(self) -> None:
        """The situations of every held sentence, and what it did in each."""
        if self._ready:
            return
        classes_of: Dict[str, set] = defaultdict(set)
        met: Counter = Counter()
        for analysed in self._held.values():
            for word, cls in zip(analysed.words, analysed.classes):
                classes_of[word].add(cls)
                met[word] += 1
        self._classes_of = {word: frozenset(cs) for word, cs in classes_of.items()}
        known: Dict[Tuple, Counter] = defaultdict(Counter)
        unknown: Dict[Tuple, Counter] = defaultdict(Counter)
        steps: List[Dict[Tuple, Counter]] = [defaultdict(Counter) for _ in range(self._LEVELS)]
        for analysed in self._held.values():
            words, classes = analysed.words, analysed.classes
            for i, cls in enumerate(classes):
                for situation in self._class_situations(words, classes, i, met=True):
                    known[situation][cls] += 1
                if met[words[i]] <= _RARE:
                    for situation in self._class_situations(words, classes, i, met=False):
                        unknown[situation][cls] += 1
            if not analysed.projective():
                continue
            for situations, step in self._steps_of(analysed):
                for level, situation in zip(steps, situations):
                    level[situation][step] += 1
        self._known, self._unknown, self._steps = dict(known), dict(unknown), [dict(level) for level in steps]
        self._ready = True

    def _steps_of(self, analysed: Analysed) -> Iterable[Tuple[List[Tuple], str]]:
        """The steps that build this sentence's structure, each with the situations it was taken in: SHIFT the next
        word on, or attach the word below the top to the top (`L:relation`) or the top to the word below it
        (`R:relation`)."""
        words = (ROOT,) + tuple(word.lower() for word in analysed.words)
        classes = ("ROOT",) + analysed.classes
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
            yield self._step_situations(words, classes, stack, waiting, under, relation), step
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
        """The class each word is used as here, decided left to right. A word no sentence held used takes a class
        memory holds of it, where it holds one (`held_classes`): "whale" after "A" is a noun, not the verb its ending
        gave it."""
        self._work_out()
        chosen: List[str] = []
        for i, word in enumerate(words):
            met = word in self._classes_of or word.lower() in self._classes_of
            held = self.held_classes(word) if not met and self.held_classes is not None else {}
            table = self._known if met else self._unknown
            decided = self._decide(((s, table.get(s)) for s in self._class_situations(words, chosen, i, met=met)),
                                   (lambda c: c in held) if held else (lambda _: True))
            if decided is None and met:
                decided = self._decide((s, self._unknown.get(s))
                                       for s in self._class_situations(words, chosen, i, met=False))
            if decided is None and held:
                decided = max((n, c) for c, n in held.items())[1], ()
            chosen.append(decided[0] if decided else _OPEN_CLASS)
        return tuple(chosen)

    @staticmethod
    def _chances(met: Iterable[Tuple[Tuple, Optional[Counter]]], allowed: Callable[[str], bool]) -> Dict[str, float]:
        """How likely each allowed step is here, from every situation met: the least specific first, each more
        specific one counting as Witten-Bell weighs it (met n times with t different steps, n/(n+t) of the way, the
        rest left to the less specific). Counts only."""
        chances: Dict[str, float] = {}
        for _, did in reversed(list(met)):
            if not did:
                continue
            options = {step: n for step, n in did.items() if allowed(step)}
            if not options:
                continue
            n = sum(options.values())
            weight = n / (n + len(options))
            chances = {step: weight * options.get(step, 0) / n + (1 - weight) * chances.get(step, 0.0)
                       for step in set(chances) | set(options)}
        return chances

    def structure(self, words: Sequence[str], classes: Sequence[str]) -> Structure:
        """Which word each depends on, and as what: the steps that build it searched with a beam (`BEAM`), each
        partial structure kept by how likely its steps were (`_chances`), so a later step can outweigh an earlier
        one where taking the likeliest step each time could not."""
        self._work_out()
        lowered = (ROOT,) + tuple(word.lower() for word in words)
        with_root = ("ROOT",) + tuple(classes)

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
                situations = self._step_situations(lowered, with_root, stack, waiting, under, relation)
                chances = self._chances(((s, level.get(s)) for level, s in zip(self._steps, situations)),
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
        _, _, _, heads, _, relation = beam[0]
        return Structure(tuple(words), tuple(classes), tuple(heads[1:]),
                         tuple(relation.get(d, "dep") for d in range(1, len(lowered))))

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
