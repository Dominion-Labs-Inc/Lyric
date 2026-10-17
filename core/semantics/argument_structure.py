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
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from core.semantics.structure import StructureView

#: The relations that mark a phrase's part with a word of its own: a preposition ("to Rex"), a subordinator ("if it
#: rains").
MARKING = ("case", "mark")
#: The longest path kept whole; a longer one is its first steps and "…".
LONGEST_PATH = 4


def head_of(span: Tuple[int, int], heads: Sequence[int]) -> int:
    """The word a phrase hangs from (0-based): the first of its words that depends on a word outside it."""
    start, end = span
    outside = [i for i in range(start, end) if not start <= heads[i] - 1 < end]
    return outside[0] if outside else start


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


class ArgumentStructureView:
    """The arguments met, each in its situations and with what it was said in; read by the most specific situation
    met (`StructureView._decide`)."""

    def __init__(self) -> None:
        self._met: Dict[Tuple, Counter] = defaultdict(Counter)
        self.arguments = 0

    def __len__(self) -> int:
        return self.arguments

    def add(self, met: Sequence[Tuple], said: str) -> None:
        """Hold one argument: the situations it stood in (`situations`) and what it was said in."""
        for situation in met:
            self._met[situation][said] += 1
        self.arguments += 1

    def said(self, met: Sequence[Tuple]) -> Optional[str]:
        """What an argument standing in these situations is said in, as the arguments met in the most specific of
        them were; None when none was met."""
        decided = StructureView._decide((situation, self._met.get(situation)) for situation in met)
        return decided[0] if decided else None
