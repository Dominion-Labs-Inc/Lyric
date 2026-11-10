"""Composing what a sentence means from how its words go together (`structure.Structure`): the meaning language's
facts, built over the structure from what each word stands for and what the words near one another say together.

"The dog chased a cat." is a chasing (`instance_of(?e, chase)`) done by the known dog (`done_by(?e, ?d)`, `given
instance_of(?d, dog)`), done to a cat, before now. What each word and each two words did is learned from sentences
taught with their meanings, each read by the structure reader and its meaning aligned to its words: the lessons
(`docs/TEACHING.md`, aligned by the names their facts hold) and the Parallel Meaning Bank (`pmb_meanings`, aligned by
the words each line of its meanings says, `TaughtSentence.anchors`). Each decision is memory-based learning, the most
specific situation the sentences met deciding (`StructureView._decide`):

- what each word stands for (`STANDS`): nothing; a thing, a known thing ("the dog"), a thing of no kind said ("it",
  "someone", the "and" joining two things); a name; the speaker, the listener, the one spoken of before, here,
  there, now; what a question asks, with a kind ("Which car") or without ("Where"); or what another word of the
  sentence stands for ("who" in "the boy who ran", "his" in "Tom wiped away his tears.");
- for TWO WORDS THE STRUCTURE JOINS WITHIN TWO STEPS (`NEAR`), the facts their terms hold: the upper word's piece
  first (its name, the relations and markers down to the other: "breathe" with its object), then the lower word's
  ("when", "who" under the word they ask of), then a word between ("has", "is"), then their classes and standings;
- which word a word standing for another's thing stands for: the nearest the situations say it is;
- what a word's term holds of a term no word says (`precedes ?now`; `done_by ?listener` of an order);
- whether a thing's own kind is denied ("The dog barks unless it rains.": no raining);
- the flags a clause puts on its facts (`condition` under "if"), and what the speaker wants.

ONE MEANING, BUILT OVER THE STRUCTURE. The composer before this one decided each word and every pair of words of the
sentence apart, from the situations met nearby: measured on the PMB's held-out English (2026-10-20, lab notebook
(26)), eight times the data raised its whole meanings right 0.2 points, and "When was the Eiffel Tower built?" asked a
place. Of the PMB's facts joining two words, 98% join words at most two steps apart in Lyric's structure (62% one
step), so no other pair is weighed; a fact that would contradict the facts held (a second count, a second time) is
not held. Lab notebook 2026-10-20 (27); `experiments/PMB-01` measures it.

WHAT DENIES IS LEARNED, never listed: a word under a word whose facts are not so, most often where no word found so
already stands beside it ("doesn't": "n't", not "does") (`CompositionView.negators`).

WHERE NOTHING PARTICULAR IS KNOWN, two things stand behind the sentences: a preposition's link that only the most
general situation decides is held as its word (`relation_types.worded`: "the capital of France" `word_of`); and
where the sentences decide nothing at all of a happening's argument, what PropBank's arguments say
(`argument_structure.ArgumentStructureView`).

A run of words joined as compound or flat is one name ("Eiffel Tower", "carbon dioxide", "Guido van Rossum"), and
so is an adjective with its noun where memory knows the two as one name ("blue whale").
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from core.semantics.argument_structure import ArgumentStructureView, candidates, phrase
from core.semantics.argument_structure import situations as argument_situations
from core.semantics.derived_reader import Meaning, MeaningFact, is_variable
from core.semantics.relation_types import worded
from core.semantics.structure import StructureView

#: What a word may stand for, and the term each gives it: a variable of its own for a thing ("thing", "known", "bare",
#: "asked", "asked thing") and for a word standing for another's thing ("same", until it is found).
STANDS = {"none": None, "name": None, "thing": None, "known": None, "bare": None, "asked": None, "asked thing": None,
          "same": None, "speaker": "?speaker", "listener": "?listener", "previous": "?previous", "here": "?here",
          "there": "?there", "now": "?now"}
#: The standings that make a variable.
VARIABLES = ("thing", "known", "bare", "asked", "asked thing", "same")
#: The situation's terms, and the standing of a word saying each.
SITUATION = {term: standing for standing, term in STANDS.items() if term}
#: The words the lessons' meanings say the situation's terms and what is asked by, for aligning a lesson to its words
#: by its names (`words_by_names`); a sentence taught with its words' lines (`TaughtSentence.anchors`) needs none.
SPEAKER = frozenset({"i", "me", "my", "mine", "myself", "we", "us", "our"})
LISTENER = frozenset({"you", "your", "yours", "yourself"})
PREVIOUS = frozenset({"it", "its", "they", "them", "their", "this", "that", "these", "those", "he", "him", "his",
                      "she", "her"})
SITUATION_WORDS = {"here": "?here", "there": "?there", "now": "?now"}
ASKING = frozenset({"who", "whom", "whose", "what", "which", "where", "when", "why", "how"})
#: The relations a clause hangs from the one above it by.
CLAUSES = ("advcl", "ccomp", "csubj", "acl", "xcomp", "conj", "parataxis")
#: The relations that join words into one name.
JOINED = ("compound", "flat", "flat:name")
#: The words of a word's own grammar that mark how it joins: "in", "of", "that".
MARKS = ("case", "mark")
#: How far apart two words the structure joins may be for their terms to hold a fact together: of the PMB's facts
#: between two words, 62% join words one step apart in Lyric's structure, 98% at most two (2026-10-20).
NEAR = 2
#: The relations of the structure a word marked by a preposition hangs by ("the capital of France", "killed on
#: Tuesday"): where only the most general situation decides the link, it is held as the preposition's word.
MARKED = ("nmod", "obl")
#: A name a word's fact holds that no word of its sentence says (`hypothetical`, `unexpected`) is kept only where met
#: in this many sentences: fewer, it is a word the alignment missed ("comes_from america" from one sentence).
GRAMMAR_MET = 3
#: How sure a word must be to deny what its clause says: of the words beside it where no denying word is, this share
#: deny, met at least `GRAMMAR_MET` times.
DENIES = 0.6


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
    #: WHAT THE ARGUMENTS ANNOTATED SAY EACH WORD IS, for the happening it belongs to: {word: what it is said in}
    #: (`argument_structure.ArgumentStructureView.arguments`, learned from PropBank's annotated sentences). Empty
    #: for every word the arguments held say nothing of, which is what a store holding none gives -- and then every
    #: situation below is exactly the situation it was before (`_word_situations`).
    arguments: Mapping[int, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.words)

    def children(self, i: int, relations: Sequence[str]) -> str:
        """The words under word i joined by these relations (by family), lowercased, or "-"."""
        return "+".join(self.words[k].lower() for k in self.under.get(i, ())
                        if self.relations[k].split(":")[0] in relations) or "-"

    def below(self, i: int, relations: Sequence[str]) -> List[int]:
        """The words under word i joined by these relations (by family)."""
        return [k for k in self.under.get(i, ()) if self.relations[k].split(":")[0] in relations]


def lay(words: Sequence[str], classes: Sequence[str], heads: Sequence[int], relations: Sequence[str],
        name_of: Callable[[str, str], str], known_name: Callable[[Sequence[str]], bool] = lambda _: False,
        arguments: Optional[Mapping[int, str]] = None) -> Laid:
    """The sentence laid out (`Laid`), each word named by `name_of(word, class)`; a run joined as compound or flat
    named as one, and an adjective with its noun where `known_name` knows the two.

    `arguments` is what the arguments annotated say each word is for its happening, where any are held
    (`MemoryAgent.lay_out`); none, and the composer decides exactly as it did before."""
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
                {k: tuple(v) for k, v in under.items()}, dict(arguments or {}))


def offsets(laid: Laid, text: str) -> List[Optional[Tuple[int, int]]]:
    """Where each word of the sentence laid out is in its text (characters, end excluded); None for one not found
    as written ("n't" is written "'t" after "doesn")."""
    out: List[Optional[Tuple[int, int]]] = []
    at = 0
    for w in laid.words:
        k = text.find(w, at)
        if k < 0 and w == "n't":
            k = text.find("'t", at)
            k = k - 1 if k > 0 else k
        if k < 0:
            out.append(None)
            continue
        out.append((k, k + len(w)))
        at = k + len(w)
    return out


# ── where two words stand in the structure ────────────────────────────────────────────────────────────────────────

def _up(laid: Laid, k: int) -> List[int]:
    chain = [k]
    while laid.heads[chain[-1]] and len(chain) <= len(laid):
        chain.append(laid.heads[chain[-1]] - 1)
    return chain


def _paths(laid: Laid, i: int, j: int) -> Optional[Tuple[List[int], List[int]]]:
    """The path from word i up to where it meets word j's, and from j up to it, each ending at the meeting word."""
    a, b = _up(laid, i), _up(laid, j)
    meet = next((k for k in a if k in b), None)
    if meet is None:
        return None
    return a[:a.index(meet) + 1], b[:b.index(meet) + 1]


def steps(laid: Laid, i: int, j: int) -> int:
    """How many steps of the structure lie between word i and word j."""
    paths = _paths(laid, i, j)
    return len(laid) + 1 if paths is None else len(paths[0]) + len(paths[1]) - 2


def placed(laid: Laid, i: int, j: int) -> Tuple[int, int, int, str]:
    """Two words as their link is decided: (the upper, the lower, the word between or -1, the shape). The upper is
    the one nearer where the two meet (the head of a word hanging from it); of two hanging from one word, the one
    whose relation sorts first. The shape is the relations from the upper down to the lower."""
    a, b = _paths(laid, i, j)
    relation = laid.relations
    if len(a) == 1 or len(b) == 1:
        upper, lower, path = (i, j, b) if len(a) == 1 else (j, i, a)
        downs = list(reversed(path[:-1]))
        return upper, lower, downs[0] if len(downs) > 1 else -1, "v" + "v".join(relation[k] for k in downs)
    upper, lower = (i, j) if (relation[i], i) <= (relation[j], j) else (j, i)
    up, down = (a[:-1], b[:-1]) if upper == i else (b[:-1], a[:-1])
    return (upper, lower, a[-1],
            "^" + "^".join(relation[k] for k in up) + "|" + "v".join(relation[k] for k in reversed(down)))


def _is_clause(laid: Laid, i: int) -> bool:
    return laid.relations[i].split(":")[0] in CLAUSES or laid.relations[i] == "root"


def _clause_of(laid: Laid, i: int) -> int:
    while not _is_clause(laid, i) and laid.heads[i]:
        i = laid.heads[i] - 1
    return i


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


def _sentence_situations(laid: Laid) -> List[Tuple]:
    root = laid.heads.index(0)
    subject = "subject" if any(laid.relations[k].startswith(("nsubj", "csubj", "expl"))
                               for k in laid.under.get(root, ())) else "-"
    return [("s", laid.words[-1], laid.words[0].lower(), laid.classes[0], subject),
            ("s", laid.words[-1], laid.classes[0], subject), ("s", laid.words[-1])]


# ── a sentence's meaning aligned to its words ─────────────────────────────────────────────────────────────────────

#: Where a line of a taught meaning says a term: its words' characters, "head" where its own words say it and
#: "marked" where the words it marks as of its grammar do ("How many"), and those marked words.
Anchor = Tuple[int, int, str, Tuple[str, ...]]


@dataclass
class Aligned:
    """A sentence taught with its meaning, aligned to its words: what each word stands for (`stands`); the facts
    the terms of two near words hold (`links`, by (upper, lower) as `placed` orders them: `kind:ul` where the
    upper's term is the fact's subject, `kind:lu` where the lower's, `not ` before a denied one; "-" for none); the
    facts of one word's term and a term no word says (`ones`: `precedes:>?now`); the flags of each clause's facts
    (`flags`, by the clause's head); the words whose facts are not so (`denied`) and whose own kind is not
    (`kinds_denied`); for each word standing for another's thing, that word (`same`); and how many facts no two near
    words hold (`loose`)."""

    laid: Laid
    act: str
    stands: Dict[int, str]
    links: Dict[Tuple[int, int], str]
    ones: Dict[int, str]
    flags: Dict[int, str]
    denied: Set[int] = field(default_factory=set)
    kinds_denied: Set[int] = field(default_factory=set)
    same: Dict[int, int] = field(default_factory=dict)
    loose: int = 0
    #: Whether the sentence was aligned by its names (a lesson's), not by its words' lines.
    by_names: bool = False
    #: The key of the taught sentence it was aligned from (`TaughtSentence.key`), where it was held whole.
    key: str = ""


def taught_name(term: str, names: Sequence[str]) -> str:
    """A taught name as the sentence's word: itself, or the last word of a sense's name ("dipterous insect fly")."""
    if term.startswith("?") or term in names:
        return term
    last = term.split()[-1]
    return last if last in names else term


def words_by_names(laid: Laid, meaning: Meaning) -> Tuple[Meaning, Dict[str, List[int]]]:
    """A lesson's meaning aligned to its words by the names its facts hold: each variable to the word named as its
    kind, a situation's term and what is asked to the words saying them, a name to the word named so. The meaning is
    returned with each taught name as the sentence's word (`taught_name`)."""
    names = laid.names
    facts = [MeaningFact(f.relation, taught_name(f.subject, names), taught_name(f.obj, names), f.positive,
                         f.condition, f.alternative, f.unasserted, f.given) for f in meaning.facts]
    term: Dict[int, str] = {}
    for f in facts:
        if f.relation == "instance_of" and is_variable(f.subject) and f.subject not in SITUATION:
            for i, name in enumerate(names):
                if name == f.obj and i not in term and f.subject not in term.values():
                    term[i] = f.subject
                    break
    held = {t for f in facts for t in f.terms()}
    for i, name in enumerate(names):
        if i in term or not name:
            continue
        w = laid.words[i].lower()
        situation = ("?speaker" if w in SPEAKER else "?listener" if w in LISTENER else "?previous" if w in PREVIOUS
                     else SITUATION_WORDS.get(w))
        if situation and situation in held and situation not in term.values():
            term[i] = situation
        elif w in ASKING and any(v not in term.values() for v in meaning.asked):
            term[i] = next(v for v in meaning.asked if v not in term.values())
        elif name in held:
            term[i] = name
    words: Dict[str, List[int]] = defaultdict(list)
    for i, t in sorted(term.items()):
        words[t].append(i)
    return Meaning(meaning.act, tuple(dict.fromkeys(facts)), meaning.asked), dict(words)


def words_by_anchors(laid: Laid, text: str, anchors: Iterable[Tuple[str, Sequence[Anchor]]]) -> Dict[str, List[int]]:
    """A meaning's terms aligned to the words of its sentence by where its lines say each (`Anchor`): a line's own
    words are the word of them the others hang from, one with a name; its marked words, the first of them."""
    at = offsets(laid, text)
    words: Dict[str, List[int]] = defaultdict(list)
    for t, said in anchors:
        for start, end, how, marked in said:
            inside = [i for i, o in enumerate(at) if o and o[0] >= start and o[1] <= end]
            marks = {m.lower() for m in marked}
            if how == "marked":
                found = [i for i in inside if laid.words[i].lower() in marks]
                w = found[0] if found else None
            else:
                own = [i for i in inside if laid.words[i].lower() not in marks] or inside
                roots = [i for i in own if laid.heads[i] - 1 not in own]
                named = [i for i in roots if laid.names[i]]
                w = (named or roots or own or [None])[0]
            if w is not None and w not in words[t]:
                words[t].append(w)
    return dict(words)


def align(laid: Laid, meaning: Meaning, words: Mapping[str, Sequence[int]]) -> Aligned:
    """A sentence's meaning aligned to its words (`Aligned`), given the words saying each term (`words_by_names`,
    `words_by_anchors`)."""
    facts = list(meaning.facts)
    at: Dict[str, List[int]] = {t: sorted(set(ws)) for t, ws in words.items() if ws}
    # A VARIABLE'S KIND IS ITS WORD'S OWN where a word saying the variable says the kind ("a dog"); a kind another
    # word says is a fact the two words' terms hold ("Is it a llama?": `instance_of(?it, llama)`).
    kinds: Dict[str, Tuple[str, bool, bool]] = {}
    for f in facts:
        if f.relation == "instance_of" and is_variable(f.subject):
            if not at.get(f.obj) or set(at[f.obj]) & set(at.get(f.subject, ())):
                kinds.setdefault(f.subject, (f.obj, f.given, f.positive))
    # A name no line says is said by the word named so.
    for f in facts:
        for t in f.terms():
            if t not in at and not is_variable(t):
                found = [i for i, name in enumerate(laid.names) if name == t]
                if found:
                    at[t] = found
    # EACH WORD'S OWN TERM: a thing whose kind the word says (or a thing of no kind), a situation's term, the name
    # that is the word's own ("town" in "Bergen is a Norwegian town.", where the town is Bergen), another word's
    # thing (the word stands for what that word does), another name; the kind of its own thing is none.
    of_word: Dict[int, List[str]] = defaultdict(list)
    for t, ws in at.items():
        for w in ws:
            of_word[w].append(t)
    own: Dict[int, str] = {}
    for w, ts in of_word.items():
        variables = [t for t in ts if is_variable(t) and t not in SITUATION]
        kinds_said = [v for v in variables if v not in kinds or w in at.get(kinds[v][0], ())]
        own_kinds = {kinds[v][0] for v in kinds_said if v in kinds}
        constants = [t for t in ts if not is_variable(t) and t not in own_kinds]
        named = [t for t in constants if laid.names[w] == t]
        chosen = (kinds_said or [t for t in ts if t in SITUATION] or named or variables or constants or [None])[0]
        if chosen is not None:
            own[w] = chosen
    saying: Dict[str, List[int]] = defaultdict(list)
    for w, t in sorted(own.items()):
        saying[t].append(w)
    stands: Dict[int, str] = {}
    first: Dict[str, int] = {}
    kinds_denied: Set[int] = set()
    for t, ws in saying.items():
        if t in SITUATION:
            for w in ws:
                stands[w] = SITUATION[t]
            first[t] = ws[0]
            continue
        if is_variable(t):
            kind = kinds.get(t)
            # THE WORD THAT IS THE THING: the one its kind's line says, else the one named as its kind, else the
            # first of a class that names things ("It ... the dog": the dog).
            said = set(at.get(kind[0], ())) if kind else set()
            one = next((w for w in ws if w in said), None)
            if one is None and kind:
                one = next((w for w in ws if laid.names[w] == kind[0]), None)
            if one is None:
                one = next((w for w in ws if laid.classes[w] in ("NOUN", "NAME", "VERB", "ADJECTIVE")), ws[0])
            standing = (("asked thing" if kind else "asked") if t in meaning.asked
                        else ("known" if kind[1] else "thing") if kind else "bare")
            if kind and not kind[2]:
                kinds_denied.add(one)
        else:
            one = next((w for w in ws if laid.names[w] == t), ws[0])
            standing = "name"
        first[t] = one
        for w in ws:
            if w != one and laid.heads[w] - 1 == one and not (not is_variable(t) and laid.names[w] == t):
                # A WORD OF THE LINE OF THE WORD IT HANGS FROM stands for nothing of its own: "It is raining." says the
                # raining with "It" in its line, and held as standing for what its verb does, "it" was learned to be
                # its own verb ("It supports multiple programming paradigms.": a supporting that is what it does).
                saying[t].remove(w)
                continue
            stands[w] = standing if w == one or (not is_variable(t) and laid.names[w] == t) else "same"
    links: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    ones: Dict[int, List[str]] = defaultdict(list)
    denied: Set[int] = set()
    loose = 0
    by_clause: Dict[int, List[Set[str]]] = defaultdict(list)
    for f in facts:
        owner = next(iter(saying.get(f.subject, []) or saying.get(f.obj, [])), None)
        if owner is not None:
            by_clause[_clause_of(laid, owner)].append(
                {name for name, on in (("condition", f.condition), ("alternative", f.alternative),
                                       ("unasserted", f.unasserted)) if on})
    for f in facts:
        if f.relation == "instance_of" and f.subject in saying and kinds.get(f.subject, ("",))[0] == f.obj:
            continue
        subjects, objects = saying.get(f.subject, []), saying.get(f.obj, [])
        mark = "" if f.positive else "not "
        if subjects and objects:
            # The nearest two words saying the two terms; of two as near, the two holding fewer facts so far ("Tom
            # hated himself.": the hating done by Tom, done to "himself").
            best = min(((steps(laid, i, j), len(links.get(placed(laid, i, j)[:2], ())), i, j)
                        for i in subjects for j in objects if i != j), default=None)
            if best is None or best[0] > NEAR:
                loose += 1
                continue
            _, _, i, j = best
            upper, lower, _, _ = placed(laid, i, j)
            links[(upper, lower)].append(f"{mark}{f.relation}:{'ul' if i == upper else 'lu'}")
            if not f.positive:
                denied.update((i, j))
        elif subjects and (not is_variable(f.obj) or f.obj in SITUATION):
            ones[first[f.subject]].append(f"{mark}{f.relation}:>{f.obj}")
            if not f.positive or (f.relation, f.obj) == ("has_property", "false"):
                # A happening said not to have happened is denied as a denied fact is ("The dog did not bark.").
                denied.add(first[f.subject])
        elif objects and (not is_variable(f.subject) or f.subject in SITUATION):
            ones[first[f.obj]].append(f"{mark}{f.relation}:<{f.subject}")
        else:
            loose += 1
    # Every other two near words with terms hold no fact together.
    standing = sorted(stands)
    for x, i in enumerate(standing):
        for j in standing[x + 1:]:
            if steps(laid, i, j) <= NEAR:
                links.setdefault(placed(laid, i, j)[:2], [])
    return Aligned(laid, meaning.act, stands, {k: "|".join(sorted(v)) or "-" for k, v in links.items()},
                   {k: "|".join(sorted(v)) for k, v in ones.items()},
                   {k: "+".join(sorted(set.intersection(*v))) or "-" for k, v in by_clause.items()},
                   denied, kinds_denied,
                   {w: first[t] for t, ws in saying.items() for w in ws if stands.get(w) == "same"}, loose)


# ── a sentence taught with its meaning ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaughtSentence:
    """A sentence taught with the meaning it was taught to have. Memory keeps one for each sentence of the lessons
    and of the Parallel Meaning Bank (`MemoryAgent.remember_taught_sentences`), and the composer learns from them,
    each read with the structure and names memory has when it is learned from (`CompositionView.hold`). `anchors`
    says where in the sentence each term of the meaning is said (`Anchor`), where the source says so (the PMB's
    lines); a lesson's terms are aligned by their names."""

    sentence: str
    meaning: Meaning
    said_in: str = ""
    anchors: Tuple[Tuple[str, Tuple[Anchor, ...]], ...] = ()

    def key(self) -> str:
        return hashlib.sha256("\x1e".join([self.said_in, self.sentence, self.meaning.canonical()])
                              .encode("utf-8")).hexdigest()[:32]

    def identity(self) -> Optional[Tuple[str, str]]:
        """What it is taught about: the sentence where it was said ("pmb/p70/d3477", "english_12"). Taught again from
        there with another meaning, it corrects the one memory holds (`MemoryAgent._correct_whole`); None where it was
        said nowhere named."""
        return (self.said_in, self.sentence) if self.said_in else None

    def claim(self) -> str:
        """What it was taught as, as the knowledge ledger records it: the sentence meaning what it was taught to."""
        return f'"{self.sentence}" means {self.meaning.canonical()} ({self.key()[:8]})'

    def said(self) -> str:
        """The sentence and its meaning, on two lines: memory keeps it as a record, never reads it as a claim."""
        return f'"{self.sentence}"\nmeans {self.meaning.canonical()}'

    def to_dict(self) -> Dict[str, Any]:
        data = {"sentence": self.sentence, "meaning": self.meaning.to_dict(), "said_in": self.said_in}
        if self.anchors:
            data["anchors"] = [[t, [list(a[:3]) + [list(a[3])] for a in said]] for t, said in self.anchors]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaughtSentence":
        anchors = tuple((str(t), tuple((int(a[0]), int(a[1]), str(a[2]), tuple(a[3])) for a in said))
                        for t, said in data.get("anchors") or ())
        return cls(str(data["sentence"]), Meaning.from_dict(data["meaning"]), str(data.get("said_in") or ""),
                   anchors)


# ── the view ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _decide(table: Mapping[Tuple, Counter], met: Iterable[Tuple],
            allowed: Callable[[str], bool] = lambda _: True) -> Optional[Tuple[str, Tuple]]:
    return StructureView._decide(((s, table.get(s)) for s in met), allowed)


class CompositionView:
    """The sentences taught with their meanings, aligned to their words and read as memory-based learning reads
    them; PropBank's arguments (`arguments`) behind them where they decide nothing of a happening's argument."""

    def __init__(self, arguments: Optional[ArgumentStructureView] = None,
                 lay_out: Optional[Callable[[str], Optional[Laid]]] = None) -> None:
        self.arguments = arguments
        #: How a sentence is read and laid out (`lay`), for the sentences held whole (`hold`) and composed
        #: (`compose_sentence`): memory's structure view and names, on main.
        self.lay_out = lay_out
        self._held: List[Aligned] = []
        self._waiting: List[TaughtSentence] = []
        self._ready = False
        #: The words that deny what their clause says, learned (`_work_out`).
        self.negators: Set[str] = set()
        self._grammar: Set[str] = set()
        self._stands: Dict[Tuple, Counter] = {}
        #: The term of the situation each word stands for where the lessons say it as one ("it", the one spoken of
        #: before; "we", the speaker): how many times each.
        self._taught_terms: Dict[str, Counter] = {}
        #: The words for happenings whose subject was learned to stand for nothing ("It rains.", "It took me two
        #: hours."): an empty subject is the verb's.
        self._empty_subjects: Set[str] = set()
        self._links: Dict[Tuple, Counter] = {}
        self._same: Dict[Tuple, Counter] = {}
        self._ones: Dict[Tuple, Counter] = {}
        self._kinds_denied: Dict[Tuple, Counter] = {}
        self._flags: Dict[Tuple, Counter] = {}
        self._acts: Dict[Tuple, Counter] = {}

    def __len__(self) -> int:
        return len(self._held) + len(self._waiting)

    def learn(self, laid: Laid, meaning: Meaning, words: Optional[Mapping[str, Sequence[int]]] = None) -> None:
        """Hold one sentence laid out, with its meaning and the words saying each of its terms; a lesson's are found
        by its names (`words_by_names`)."""
        by_names = words is None
        if by_names:
            meaning, words = words_by_names(laid, meaning)
        aligned = align(laid, meaning, words)
        aligned.by_names = by_names
        self._held.append(aligned)
        self._ready = False

    def hold(self, taught: TaughtSentence) -> None:
        """Hold one taught sentence whole, to be read and laid out (`lay_out`) when the view is next worked out."""
        self._waiting.append(taught)
        self._ready = False

    def drop(self, taught: TaughtSentence) -> None:
        """Hold a taught sentence no longer: what it was taught to mean was corrected (`MemoryAgent._correct_whole`)."""
        key = taught.key()
        self._waiting = [t for t in self._waiting if t.key() != key]
        self._held = [a for a in self._held if a.key != key]
        self._ready = False

    # ── learning ──────────────────────────────────────────────────────────────────────────────────────────────────
    def _work_out(self) -> None:
        if self._ready:
            return
        if self._waiting and self.lay_out is not None:
            for taught in self._waiting:
                laid = self.lay_out(taught.sentence)
                if laid is None:
                    continue
                if taught.anchors:
                    self.learn(laid, taught.meaning, words_by_anchors(laid, taught.sentence, taught.anchors))
                else:
                    self.learn(laid, taught.meaning)
                self._held[-1].key = taught.key()
            self._waiting = []
        self.negators = self._denying_words()
        met: Dict[str, Set[int]] = defaultdict(set)
        for n, aligned in enumerate(self._held):
            for labels in aligned.ones.values():
                for part in labels.split("|"):
                    met[part.split(":", 1)[1][1:]].add(n)
        self._grammar = {name for name, where in met.items() if len(where) >= GRAMMAR_MET or name.startswith("?")}
        stands, links, same, ones, kinds_denied, flags, acts = (defaultdict(Counter) for _ in range(7))
        taught_terms: Dict[str, Counter] = defaultdict(Counter)
        subjects: Dict[str, Counter] = defaultdict(Counter)
        for aligned in self._held:
            laid, standing = aligned.laid, aligned.stands
            for i in range(len(laid)):
                if not laid.names[i]:
                    continue
                for s in self._word_situations(laid, i):
                    stands[s][standing.get(i, "none")] += 1
                if aligned.by_names and STANDS.get(standing.get(i, "none")):
                    taught_terms[laid.words[i].lower()][standing[i]] += 1
                head = laid.heads[i] - 1
                if laid.relations[i] in ("nsubj", "nsubj:pass") and head >= 0 and laid.classes[head] == "VERB":
                    subjects[laid.names[head]]["none" if i not in standing else "some"] += 1
                if i in standing:
                    kept = "|".join(part for part in aligned.ones.get(i, "").split("|")
                                    if part and part.split(":", 1)[1][1:] in self._grammar)
                    for s in self._one_situations(laid, i):
                        ones[s][kept or "-"] += 1
                if standing.get(i) in ("thing", "known", "asked thing"):
                    for s in self._kind_situations(laid, i):
                        kinds_denied[s]["not" if i in aligned.kinds_denied else "-"] += 1
            for (upper, lower), label in aligned.links.items():
                for s in self._link_situations(laid, standing, upper, lower):
                    links[s][label] += 1
            for w, other in aligned.same.items():
                for c in standing:
                    if c != w:
                        for s in self._same_situations(laid, standing, w, c):
                            same[s]["=" if c == other else "-"] += 1
            for i, common in aligned.flags.items():
                for s in _clause_situations(laid, i):
                    flags[s][common] += 1
            for s in _sentence_situations(laid):
                acts[s][aligned.act] += 1
        self._stands, self._links, self._same, self._ones = dict(stands), dict(links), dict(same), dict(ones)
        self._taught_terms = dict(taught_terms)
        self._empty_subjects = {verb for verb, met in subjects.items()
                                if met["none"] >= 2 and met["none"] * 3 >= sum(met.values())}
        self._kinds_denied, self._flags, self._acts = dict(kinds_denied), dict(flags), dict(acts)
        self._ready = True

    def _denying_words(self) -> Set[str]:
        """THE WORDS THAT DENY WHAT THEIR CLAUSE SAYS: a word under a word whose facts are not so, where no word found
        so already stands beside it, at least `DENIES` of the times it was met there, the surest first ("doesn't":
        "n't" found first, then "does" is no denying word)."""
        beside: List[Tuple[Set[str], bool]] = []
        for aligned in self._held:
            laid = aligned.laid
            for i in range(len(laid)):
                children = {laid.words[k].lower() for k in laid.under.get(i, ())}
                if children:
                    beside.append((children, i in aligned.denied))
        found: Set[str] = set()
        while True:
            met, denying = Counter(), Counter()
            for children, denied in beside:
                if children & found:
                    continue
                for w in children:
                    met[w] += 1
                    denying[w] += denied
            best = max(((denying[w] / n, n, w) for w, n in met.items() if n >= GRAMMAR_MET and w not in found),
                       default=None)
            if best is None or best[0] < DENIES:
                return found
            found.add(best[2])

    # ── the situations ────────────────────────────────────────────────────────────────────────────────────────────
    def _denied(self, laid: Laid, *words: int) -> str:
        return "not" if any(laid.words[k].lower() in self.negators
                            for i in words if i >= 0 for k in laid.under.get(i, ())) else "-"

    @staticmethod
    def _word_situations(laid: Laid, i: int) -> List[Tuple]:
        """What word i stands for: the word, its class and relation, its determiner, auxiliaries and adverbs, what it
        hangs from, whether it opens the sentence and whether the sentence asks."""
        w, c, rel = laid.words[i].lower(), laid.classes[i], laid.relations[i]
        head = laid.heads[i] - 1
        head_class = laid.classes[head] if head >= 0 else "ROOT"
        head_rel = laid.relations[head] if head >= 0 else "-"
        det = laid.children(i, ("det",))
        if any(laid.relations[k] == "nmod:poss" for k in laid.under.get(i, ())):
            det = "poss" if det == "-" else det + "+poss"
        aux = laid.children(i, ("aux", "cop"))
        counted = "count" if any(laid.relations[k] == "nummod" for k in laid.under.get(i, ())) else "-"
        first = "first" if i == 0 else "-"
        asks = "?" if laid.words[-1] == "?" else "."
        adverbs = laid.children(i, ("advmod",))
        # WHAT THE ARGUMENTS ANNOTATED SAY THIS WORD IS, where any are held of it: PropBank's 10,495 annotated
        # sentences were learned into a view nothing read, so what they say of a happening's arguments reached no
        # reading (2026-11-10). Said here as a situation of its own, ahead of the rest, so where the composer has
        # learned what a word standing as that argument stands for, that decides; and where it has not, or the
        # arguments say nothing of this word, the situations below are exactly the situations they were.
        role = laid.arguments.get(i) or ""
        said_as: List[Tuple] = [("a", w, c, rel, role, det, aux, head_class, head_rel, asks),
                                ("a", c, rel, role, det, head_class, head_rel, asks),
                                ("a", c, rel, role)] if role else []
        return said_as + [("w", w, c, rel, det, aux, head_class, head_rel, first, asks, adverbs),
                ("w", w, c, rel, det, aux, head_class, head_rel, first, asks),
                ("w", w, c, rel, det, head_class, head_rel, asks), ("w", w, c, rel, det, head_rel),
                ("w", w, c, rel, det), ("w", w, c, rel), ("w", w, c),
                ("c", c, rel, det, aux, counted, head_class, head_rel, first, asks, adverbs),
                ("c", c, rel, det, aux, counted, head_class, head_rel, first, asks),
                ("c", c, rel, det, counted, head_class), ("c", c, rel, det), ("c", c, rel), ("c", c)]

    def _link_situations(self, laid: Laid, stands: Mapping[int, str], upper: int, lower: int) -> List[Tuple]:
        """What two near words' terms hold together: the upper word's piece (its name, the shape and markers down to
        the lower), then the lower's, then the word between's, then their classes; each with what the two stand for,
        whether the upper has a copula, whether a denying word stands beside them, whether the lower joins others to
        it ("Tom and Mary": the two together are the one who does it)."""
        _, _, middle, shape = placed(laid, upper, lower)
        if any(laid.relations[k] == "conj" for k in laid.under.get(lower, ())):
            shape += "&"
        su, sl = stands.get(upper, "none"), stands.get(lower, "none")
        mu, ml = laid.children(upper, MARKS), laid.children(lower, MARKS)
        nu = laid.names[upper] or laid.words[upper].lower()
        nl = laid.names[lower] or laid.words[lower].lower()
        cu, cl = laid.classes[upper], laid.classes[lower]
        nm = (laid.names[middle] or laid.words[middle].lower()) if middle >= 0 else "-"
        cm = laid.classes[middle] if middle >= 0 else "-"
        sm = stands.get(middle, "none") if middle >= 0 else "-"
        cop = "cop" if laid.below(upper, ("cop",)) else "-"
        neg = self._denied(laid, upper, lower, middle)
        return [("1", shape, mu, ml, nu, nl, nm, su, sl, cop, neg), ("2", shape, mu, ml, nu, cl, nm, su, sl, cop, neg),
                ("3", shape, mu, ml, cu, nl, nm, su, sl, cop, neg),
                ("4", shape, mu, ml, cu, cl, nm, sm, su, sl, cop, neg),
                ("5", shape, mu, ml, cu, cl, cm, sm, su, sl, cop, neg), ("6", shape, ml, cu, cl, su, sl, cop, neg),
                ("7", shape, su, sl, cop, neg)]

    @staticmethod
    def _same_situations(laid: Laid, stands: Mapping[int, str], w: int, c: int) -> List[Tuple]:
        """Whether word w stands for what word c does ("his" for Tom in "Tom wiped away his tears.")."""
        form, rel_w, cls_w = laid.words[w].lower(), laid.relations[w], laid.classes[w]
        rel_c, cls_c, st_c = laid.relations[c], laid.classes[c], stands.get(c, "none")
        side = "before" if c < w else "after"
        near = min(steps(laid, w, c), 6)
        together = "same clause" if _clause_of(laid, w) == _clause_of(laid, c) else "-"
        # WHETHER THE OTHER WORD IS WRITTEN IN A SHAPE OF ITS NAME ("experiments", `experiment`): "it" stands for no
        # thing written so, "they" does ("In experiments on three datasets, it detects more attacks ...": the
        # detecting was done by the experiments, 2026-10-20).
        shape = "shaped" if laid.names[c] and laid.words[c].lower() != laid.names[c] else "-"
        return [("s1", form, rel_w, rel_c, cls_c, st_c, side, near, together, shape),
                ("s2", form, rel_w, cls_c, st_c, side, together, shape), ("s3", form, cls_c, st_c, side, shape),
                ("s4", cls_w, rel_w, rel_c, cls_c, st_c, side, near, together, shape),
                ("s5", cls_w, cls_c, st_c, side, together, shape), ("s6", cls_c, st_c, side, shape)]

    def _one_situations(self, laid: Laid, i: int) -> List[Tuple]:
        """What word i's term holds of a term no word says: the word, how it is written beside its name, its
        auxiliaries and those of the word it hangs from, whether it has a subject, whether a denying word stands
        beside it, whether it opens the sentence and how the sentence ends ("Call him.": done by the listener)."""
        form, cls, name = laid.words[i].lower(), laid.classes[i], laid.names[i]
        aux = laid.children(i, ("aux", "cop"))
        subject = "subject" if any(laid.relations[k].startswith(("nsubj", "csubj", "expl"))
                                   for k in laid.under.get(i, ())) else "-"
        k = 0
        while k < min(len(form), len(name)) and form[k] == name[k]:
            k += 1
        inflection = form[k:] if k >= len(name) - 1 else "other:" + form[k:]
        denied = self._denied(laid, i)
        rel = laid.relations[i]
        first = "first" if all(not laid.names[j] for j in range(i)) else "-"
        end = laid.words[-1] if laid.words[-1] in ("?", "!", ".") else "-"
        head = laid.heads[i] - 1
        up = laid.children(head, ("aux", "cop")) if head >= 0 else "-"
        return [("w", form, cls, aux, subject, rel, denied, first, end, up), ("w", form, cls, aux, subject, rel, denied),
                ("e", inflection, cls, aux, subject, rel, denied, first, end, up),
                ("e", inflection, cls, aux, subject, rel, denied), ("c", cls, aux, subject, rel, denied, first, end),
                ("c", cls, aux, subject, rel, denied), ("c", cls, aux, subject, denied), ("c", cls, denied)]

    def _kind_situations(self, laid: Laid, i: int) -> List[Tuple]:
        """Whether word i's own kind is denied: whether a denying word stands beside it or beside the word above."""
        head = laid.heads[i] - 1
        neg, up = self._denied(laid, i), self._denied(laid, head) if head >= 0 else "-"
        return [("k", laid.names[i], laid.classes[i], laid.relations[i], neg, up),
                ("k", laid.classes[i], laid.relations[i], neg, up), ("k", laid.classes[i], neg, up), ("k", neg, up)]

    # ── composing ─────────────────────────────────────────────────────────────────────────────────────────────────
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

    def _argument(self, laid: Laid, stands: Mapping[int, str], v: int, c: int) -> Optional[str]:
        """What PropBank's arguments say word c is to the happening word v, as a link's label, or None."""
        if self.arguments is None or laid.classes[v] != "VERB" or stands.get(v) not in ("thing", "known") \
                or c not in candidates(laid.heads, v):
            return None
        said = self.arguments.said(argument_situations(laid.words, laid.classes, laid.heads, laid.relations, v,
                                                        phrase(c, laid.heads)))
        if not said or not said.startswith("fact:"):
            return None
        parts = said.split(":")
        return ("" if len(parts) < 3 else "not ") + parts[1] + ":ul"

    def _link(self, laid: Laid, stands: Mapping[int, str], upper: int, lower: int) -> Optional[str]:
        """The facts the terms of two near words hold, as `Aligned.links` writes them, or None."""
        got = _decide(self._links, self._link_situations(laid, stands, upper, lower))
        if not got:
            said = self._argument(laid, stands, upper, lower)
            if said:
                return said
        if (not got or got[1][0] == "7") and laid.heads[lower] - 1 == upper \
                and laid.relations[lower].split(":")[0] in MARKED:
            # A LINK SAID WITH A WORD THAT NOTHING PARTICULAR NAMES IS HELD AS THAT WORD, never guessed: "the
            # capital of France" is `word_of(capital, France)` where only the most general situation decides.
            marker = " ".join(laid.words[k].lower() for k in laid.below(lower, ("case",)))
            if marker and all(part.isalpha() for part in marker.split()):
                return worded(marker) + ":ul"
        return got[0] if got and got[0] != "-" else None

    def compose(self, laid: Laid) -> Meaning:
        """What the sentence laid out means, composed. Raises ValueError where nothing is composed to a meaning."""
        self._work_out()
        stands: Dict[int, str] = {}
        for i in range(len(laid)):
            if laid.names[i]:
                got = _decide(self._stands, self._word_situations(laid, i))
                if got and got[0] != "none":
                    stands[i] = got[0]
        # A SUBJECT STANDS FOR NOTHING ONLY UNDER THE VERBS IT WAS LEARNED TO: "It rains.", "It took me two hours.".
        # Counted by sentences, those few verbs said "it" stands for nothing under any verb, and "In experiments on
        # three datasets, it detects more attacks than earlier methods." held a detecting no one did
        # (UNDERSTANDS-PROSE-01 on main, 2026-10-20): of the verbs "it" was learned under, most had it stand for
        # something (20 to 4). Under any other verb, a subject is what it may stand for besides nothing.
        for i in range(len(laid)):
            head = laid.heads[i] - 1
            if i in stands or not laid.names[i] or laid.relations[i] not in ("nsubj", "nsubj:pass") or head < 0 \
                    or laid.classes[head] != "VERB" or stands.get(head) not in ("thing", "known") \
                    or laid.names[head] in self._empty_subjects:
                continue
            got = _decide(self._stands, self._word_situations(laid, i), allowed=lambda standing: standing != "none")
            if got:
                stands[i] = got[0]
        # A WORD STANDING FOR WHAT ANOTHER STANDS FOR takes its term: the nearest word the situations say it is. One
        # that finds none in its sentence stands for a thing of no kind said here ("It does not change the original
        # list.": nothing in the sentence is what "it" is).
        same: Dict[int, int] = {}
        for w in (w for w, s in stands.items() if s == "same"):
            for c in sorted((c for c in stands if c != w and stands[c] != "same"),
                            key=lambda c: (steps(laid, w, c), c > w, abs(c - w))):
                got = _decide(self._same, self._same_situations(laid, stands, w, c))
                if got and got[0] == "=":
                    same[w] = c
                    break
            else:
                stands[w] = "bare"
        term = {i: f"?x{i}" if standing in VARIABLES else laid.names[i] if standing == "name" else STANDS[standing]
                for i, standing in stands.items()}
        # A WORD LEFT A THING OF NO KIND THAT THE LESSONS SAY AS A TERM OF THE SITUATION TAKES THAT TERM: the PMB
        # leaves "they" or "it" unnamed where its document does not say what it is, the lessons say the one spoken of
        # before ("They are blue."), and the conversation holds nothing of a thing it cannot name: "They live in the
        # ocean." was not taken in (UNDERSTANDS-PROSE-01 on main, 2026-10-20 (28)). Only the term changes; what the
        # words hold together is decided as the PMB taught it, the lessons' own pronouns being taught as one ("They
        # chased them." aligns both to the one spoken of before). The term is the one the lessons say the word as
        # wherever they say it as one ("it": the one spoken of before 21 times; its 101 others are "It rains." and
        # "It is true that ..."). The one spoken of before is one: a second word so ("He fixed it.") stays unnamed,
        # never held as the first. A word the lessons never met so ("someone") stays unnamed.
        before = False
        for i in sorted(i for i, standing in stands.items() if standing == "bare"):
            taught = self._taught_terms.get(laid.words[i].lower())
            said = STANDS.get(taught.most_common(1)[0][0]) if taught else None
            if said and not (said == "?previous" and before):
                term[i] = said
                before = before or said == "?previous"
        links: Dict[Tuple[int, int], str] = {}
        standing = sorted(stands)
        for x, i in enumerate(standing):
            for j in standing[x + 1:]:
                if steps(laid, i, j) <= NEAR:
                    upper, lower, _, _ = placed(laid, i, j)
                    said = self._link(laid, stands, upper, lower)
                    if said:
                        links[(upper, lower)] = said
        term = {i: term[same.get(i, i)] for i in term}
        flags = {i: self._flags_of(laid, i) for i in range(len(laid))}
        facts: List[MeaningFact] = []

        def add(relation: str, subject: str, obj: str, holds: bool, on: Set[str], given: bool = False) -> None:
            if subject == obj:
                # No fact is of a thing and itself: two words taken as one term ("we" the speaker, of which the
                # speaker is one) say nothing of it.
                return
            try:
                fact = MeaningFact(relation, subject, obj, holds, "condition" in on, "alternative" in on,
                                   "unasserted" in on, given)
                if fact in facts:
                    return
                # ONE MEANING: a fact the facts held would contradict (a second count, a second time) is not held.
                Meaning("tell", tuple(facts) + (fact,))
            except ValueError as error:
                if "condition alone" not in str(error):
                    return
            facts.append(fact)
        asked: List[str] = []
        for i, standing in stands.items():
            if standing in ("thing", "known", "asked thing"):
                got = _decide(self._kinds_denied, self._kind_situations(laid, i))
                add("instance_of", term[i], laid.names[i], not (got and got[0] == "not"),
                    flags[i] - {"alternative"}, standing == "known")
            if standing in ("asked", "asked thing") and term[i] not in asked:
                asked.append(term[i])
        for (upper, lower), label in links.items():
            for part in label.split("|"):
                holds = not part.startswith("not ")
                kind, way = part.replace("not ", "").split(":")
                subject, obj, owner = ((term[upper], term[lower], upper) if way == "ul"
                                       else (term[lower], term[upper], lower))
                add(kind, subject, obj, holds, flags[owner])
        for i in stands:
            got = _decide(self._ones, self._one_situations(laid, i))
            for part in (got[0].split("|") if got and got[0] != "-" else ()):
                holds = not part.startswith("not ")
                kind, rest = part.replace("not ", "").split(":", 1)
                way, other = rest[0], rest[1:]
                add(kind, *((term[i], other) if way == ">" else (other, term[i])), holds, flags[i])
        got = _decide(self._acts, _sentence_situations(laid))
        act = got[0] if got else "tell"
        return Meaning(act, tuple(facts),
                       tuple(t for t in asked if any(t in f.terms() for f in facts)) if act == "ask" else ())

    def _flags_of(self, laid: Laid, i: int) -> Set[str]:
        """The flags word i's clause and every clause above it put on their facts."""
        flags: Set[str] = set()
        at, seen = i, set()
        while at >= 0 and at not in seen:
            seen.add(at)
            if _is_clause(laid, at):
                got = _decide(self._flags, _clause_situations(laid, at))
                if got and got[0] != "-":
                    flags |= set(got[0].split("+"))
            at = laid.heads[at] - 1
        return flags
