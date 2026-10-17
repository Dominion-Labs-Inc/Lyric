"""Argument-structure constructions: how a phrase stands to its predicate says what fact it is said in.

"Tom gave Rex the ball." is a giving `done_by` Tom, `received_by` Rex, `done_to` the ball. Which phrase plays which
part is said by how each stands to the verb: the subject of an active verb is who did it, its second object who got
it, "to" a person who got it, "in" a place where it was. Learned over phrases (`structure.StructureView` gives each
sentence's structure), not over word strings, a construction holds for every phrase that stands so, of any length
or shape: "carbon dioxide and water" stands where "water" does.

LEARNED FROM SENTENCES WHOSE PHRASES WERE GIVEN THEIR PARTS, KEPT AS MET. Each argument is met as the situations it
stands in, from the most specific to the least: the predicate's word, the path between them in the structure (`↑`
up from the predicate, `↓` down to the argument: "↓nsubj", "↑xcomp↓nsubj"), the word that marks it ("to", "in",
"if"), the predicate's voice and class, the class of the argument's head and its first word. An argument is said as
the arguments met in the most specific situation like it were (`StructureView._decide`, backing off on a tie):
memory-based learning, as the structure itself is decided.

What each argument was said in comes from the meaning language (`propbank_roles`): a fact in a link kind
(`done_by`, `located_in`), a rule its words settle (`predicated`), nothing, or a named gap.

WHICH PHRASES ARE ARGUMENTS. Not every word near a predicate heads one of its arguments. The words that may
(`candidates`) are its dependents and, going up the structure from it, each word above it and that word's
dependents: "Tom" in "Tom wanted to leave" is an argument of "leave" two steps up (the pruning of dependency role
labelling, Zhao, Chen, Kit & Zhou 2009). Learned with every candidate that heads none said as `NONE`, the same view
finds the arguments and says each (`ArgumentStructureView.arguments`), each as a phrase: the word with all that
depends on it (`phrase`).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from core.semantics.structure import StructureView

#: The relations that mark a phrase's part with a word of its own: a preposition ("to Rex"), a subordinator ("if it
#: rains").
MARKING = ("case", "mark")
#: The longest path kept whole; a longer one is its first steps and "…".
LONGEST_PATH = 4
#: What a candidate that heads no argument is said in.
NONE = "none"


def head_of(span: Tuple[int, int], heads: Sequence[int]) -> int:
    """The word a phrase hangs from (0-based): the first of its words that depends on a word outside it."""
    start, end = span
    outside = [i for i in range(start, end) if not start <= heads[i] - 1 < end]
    return outside[0] if outside else start


def candidates(heads: Sequence[int], predicate: int) -> List[int]:
    """The words that may head an argument of the predicate (0-based; `heads` 1-based, 0 the root): its dependents,
    then, going up, each word above it and that word's dependents."""
    under: Dict[int, List[int]] = defaultdict(list)
    for i, head in enumerate(heads):
        under[head - 1].append(i)
    found: List[int] = []
    at = predicate
    while True:
        found += [i for i in under[at] if i != predicate and i not in found]
        up = heads[at] - 1
        if up < 0:
            return found
        if up not in found:
            found.append(up)
        at = up


def phrase(at: int, heads: Sequence[int]) -> Tuple[int, int]:
    """The words word `at` heads, itself with all that depends on it: (start, end), 0-based, end past the last."""
    under: Dict[int, List[int]] = defaultdict(list)
    for i, head in enumerate(heads):
        under[head - 1].append(i)
    span, waiting = [at], [at]
    while waiting:
        for i in under[waiting.pop()]:
            if i not in span:
                span.append(i)
                waiting.append(i)
    return min(span), max(span) + 1


def path(predicate: int, argument: int, heads: Sequence[int], relations: Sequence[str]) -> str:
    """How an argument's head stands to its predicate (both 0-based; `heads` 1-based, 0 the root): the relations up
    from the predicate to the nearest word above both, then down to the argument. "self" when they are one word."""
    def up(i: int) -> List[int]:
        chain = [i]
        while heads[chain[-1]] != 0 and len(chain) <= len(heads):
            chain.append(heads[chain[-1]] - 1)
        return chain
    from_predicate, from_argument = up(predicate), up(argument)
    meeting = next((i for i in from_predicate if i in from_argument), None)
    if meeting is None:
        return "far"
    steps = ["↑" + relations[i].split(":")[0] for i in from_predicate[:from_predicate.index(meeting)]]
    steps += ["↓" + relations[i] for i in reversed(from_argument[:from_argument.index(meeting)])]
    if not steps:
        return "self"
    return "".join(steps[:LONGEST_PATH]) + ("…" if len(steps) > LONGEST_PATH else "")


def situations(words: Sequence[str], classes: Sequence[str], heads: Sequence[int], relations: Sequence[str],
               predicate: int, span: Tuple[int, int]) -> List[Tuple]:
    """The situations an argument stands in, the most specific first."""
    head = head_of(span, heads)
    between = path(predicate, head, heads, relations)
    marks = [words[i].lower() for i in range(len(words))
             if heads[i] - 1 == head and relations[i].split(":")[0] in MARKING]
    mark = marks[0] if marks else "-"
    first = words[span[0]].lower()
    under = {relations[i] for i in range(len(words)) if heads[i] - 1 == predicate}
    voice = "passive" if under & {"aux:pass", "nsubj:pass", "csubj:pass"} else "active"
    said_by, its_class, head_class = words[predicate].lower(), classes[predicate], classes[head]
    return [("word", said_by, between, mark, first), ("word", said_by, between, mark),
            ("voice", voice, its_class, between, mark, head_class, first),
            ("voice", voice, its_class, between, mark, head_class), ("voice", voice, its_class, between, mark),
            ("path", between, mark), ("path", between), ("class", head_class, mark), ("class", head_class)]


def taught_arguments(words: Sequence[Any], predicates: Sequence[Any],
                     roles: Mapping[Tuple[str, str], Tuple[str, Tuple[str, ...]]]
                     ) -> Tuple[Dict[int, Dict[int, str]], Dict[int, Set[int]]]:
    """What PropBank's annotation of a sentence says of each happening's arguments, in the meaning language
    (`propbank_roles.said`): {happening: {head word: what it is said in}}, both 0-based, and {happening: head words
    left out}, a relative pronoun or a continuation (which takes its argument's part) and an argument the mapping does
    not say. `words` are `PropBankWord`s, `predicates` `PropBankPredicate`s (`read_propbank_ewt`), `roles` the frame
    files' function tags and VerbNet roles (`propbank_roles_of_frames`). Auxiliaries, `be.02` and light verbs are no
    happening (`propbank_roles.predicate`)."""
    from core.semantics import propbank_roles as pr
    heads = [w.head for w in words]
    found: Dict[int, Dict[int, str]] = defaultdict(dict)
    left: Dict[int, Set[int]] = defaultdict(set)
    for predicate in predicates:
        if pr.predicate(predicate.roleset, predicate.tag) is not None:
            continue
        found[predicate.at]
        for label, spans in predicate.arguments:
            base, stands = pr.label_of(label)
            tag, verbnet = roles.get((predicate.roleset, base), ("", ()))
            for span in spans:
                head = head_of(span, heads)
                said = None if stands else pr.said(
                    label, roleset=predicate.roleset, function_tag=tag, verbnet=verbnet,
                    words=tuple(w.form for w in words[span[0]:span[0] + 2]), first_class=words[span[0]].word_class)
                if said is not None and said.how == "rule" and said.rule == "pivot":
                    said = pr.fact("done_by")   # a pivot not said by its predicate is its doer (`RULES`)
                if said is None or head == predicate.at:
                    left[predicate.at].add(head)
                    continue
                found[predicate.at][head] = ":".join(
                    x for x in (said.how, said.kind or said.rule or said.needs, "" if said.positive else "not") if x)
    return found, left


def learned_from_propbank(sentences: Sequence[Tuple[Any, ...]],
                          roles: Mapping[Tuple[str, str], Tuple[str, Tuple[str, ...]]]) -> "ArgumentStructureView":
    """The view learned from PropBank's training part over UD's structure (`read_propbank_ewt`'s sentences), every
    candidate of every happening said as its argument is, or `NONE`."""
    view = ArgumentStructureView()
    for part, _, _, words, predicates in sentences:
        if part != "train":
            continue
        forms, classes = [w.form for w in words], [w.word_class for w in words]
        heads, relations = [w.head for w in words], [w.relation for w in words]
        found, left = taught_arguments(words, predicates, roles)
        for at, said in found.items():
            for candidate in candidates(heads, at):
                if candidate not in left[at]:
                    view.add(situations(forms, classes, heads, relations, at, phrase(candidate, heads)),
                             said.get(candidate, NONE))
    return view


class ArgumentStructureView:
    """The arguments met, each in its situations and with what it was said in; read by the most specific situation
    met (`StructureView._decide`)."""

    def __init__(self) -> None:
        self._met: Dict[Tuple, Counter] = defaultdict(Counter)
        self._held = 0

    def __len__(self) -> int:
        return self._held

    def add(self, met: Sequence[Tuple], said: str) -> None:
        """Hold one argument: the situations it stood in (`situations`) and what it was said in."""
        for situation in met:
            self._met[situation][said] += 1
        self._held += 1

    def said(self, met: Sequence[Tuple]) -> Optional[str]:
        """What an argument standing in these situations is said in, as the arguments met in the most specific of
        them were; None when none was met."""
        decided = StructureView._decide((situation, self._met.get(situation)) for situation in met)
        return decided[0] if decided else None

    def arguments(self, words: Sequence[str], classes: Sequence[str], heads: Sequence[int],
                  relations: Sequence[str], predicate: int) -> Dict[int, str]:
        """The predicate's arguments: each candidate (`candidates`) said in something other than `NONE`, as {its
        head word (0-based): what it is said in}. Learned with `NONE` for the candidates that head none."""
        found: Dict[int, str] = {}
        for at in candidates(heads, predicate):
            said = self.said(situations(words, classes, heads, relations, predicate, phrase(at, heads)))
            if said and said != NONE:
                found[at] = said
        return found
