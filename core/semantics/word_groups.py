"""Which words keep the same company, counted from raw text: each word's group, for the structure reader to weigh a
word it met rarely or never by the words that stand where it does (`StructureView.grouping`).

COUNTED, NOT LEARNED BY A MODEL. Every word is put in one of a number of groups so that the counts of which group
follows which say the text best: a class bigram model's likelihood (Brown et al. 1992), found by moving one word at a
time to the group where it rises most, again and again until few move (the exchange algorithm: Kneser & Ney 1993;
Martin, Liermann & Ney 1998). What comes out is a table, word to group, as readable as the text's own counts: "make,
take, get, see, give" stand together, and "more, less, rather, better, longer".

Counted over WikiText-103's 100 million words, the structure reader with each word's group beside it read EWT dev
78.3% to 79.2% UAS, PUD 75.5% to 76.4%; with UD's other English treebanks too, 80.5%, 78.8% and GUM's held-out test
79.9% (`experiments/GROUPS-01`, `experiments/STRUCTURE-03`). MiniLM's vectors, grouped the same way, read no better
(lab notebook 2026-10-18).
"""
from __future__ import annotations

import time
from array import array
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

#: Where a sentence begins and ends, in a group of its own that never moves.
BOUNDARY = "<s>"


def _f(x) -> "np.ndarray":
    """x log x, 0 at 0: what a count adds to a likelihood."""
    x = np.asarray(x, dtype=np.float64)
    return np.where(x > 0, x * np.log(np.maximum(x, 1e-300)), 0.0)


def counted_groups(sentences: Iterable[Sequence[str]], groups: int, words: int = 100_000, rounds: int = 12,
                   say: Optional[Callable[[str], None]] = None) -> Dict[str, int]:
    """Each of the `words` most frequent words of these sentences (lowered), and the group of `groups` it keeps the
    company of. Words met less often stand together as one word that never moves, so they count as company but are
    given no group. Moved `rounds` times over or until fewer than one word in 500 moves."""
    started = time.perf_counter()
    index = {BOUNDARY: 0}
    ids = array("q")
    for sentence in sentences:
        ids.append(0)
        ids.extend([index.get(w) if w in index else index.setdefault(w, len(index))
                    for w in (word.lower() for word in sentence)])
    ids.append(0)
    tokens = np.frombuffer(ids, dtype=np.int64)
    names = np.empty(len(index), dtype=object)
    for word, k in index.items():
        names[k] = word
    counts = np.bincount(tokens)
    order = np.argsort(-counts, kind="stable")
    order = order[order != 0][:words]
    grouped = np.full(len(index), -1, dtype=np.int64)
    grouped[0] = 0
    for rank, k in enumerate(order):
        grouped[k] = 1 + rank % (groups - 1)
    rest = len(index)
    tok = np.where(grouped[tokens] >= 0, tokens, rest)
    grouped = np.append(grouped, groups)
    size = groups + 1
    pairs = tok[:-1] * (rest + 1) + tok[1:]
    uniq, n = np.unique(pairs, return_counts=True)
    left, right = uniq // (rest + 1), uniq % (rest + 1)
    by_left = np.argsort(left, kind="stable")
    succ_w, succ_n = right[by_left], n[by_left]
    succ_at = np.searchsorted(left[by_left], np.arange(rest + 2))
    by_right = np.argsort(right, kind="stable")
    pred_w, pred_n = left[by_right], n[by_right]
    pred_at = np.searchsorted(right[by_right], np.arange(rest + 2))
    unigram = np.bincount(tok, minlength=rest + 1).astype(np.float64)
    met = np.nonzero(unigram)[0]
    M = np.zeros((size, size))
    np.add.at(M, (grouped[left], grouped[right]), n)
    sizes = np.bincount(grouped[met], weights=unigram[met], minlength=size)
    if say:
        say(f"{len(tokens):,} words of text, {len(index):,} words, {len(uniq):,} pairs met, "
            f"{time.perf_counter() - started:.0f}s")
    for round_ in range(rounds):
        moved = 0
        for w in order:
            a = grouped[w]
            sw, sn = succ_w[succ_at[w]:succ_at[w + 1]], succ_n[succ_at[w]:succ_at[w + 1]]
            pw, pn = pred_w[pred_at[w]:pred_at[w + 1]], pred_n[pred_at[w]:pred_at[w + 1]]
            itself = float(sn[sw == w].sum())
            r = np.bincount(grouped[sw[sw != w]], weights=sn[sw != w], minlength=size)
            l = np.bincount(grouped[pw[pw != w]], weights=pn[pw != w], minlength=size)
            nw = unigram[w]
            # Out of its group, then what each group gains by taking it: the pairs it is in, in that group's row and
            # column, the pairs with itself where they meet, and its own count in the group's.
            M[a, :] -= r
            M[:, a] -= l
            M[a, a] -= itself
            sizes[a] -= nw
            rj, li = np.nonzero(r)[0], np.nonzero(l)[0]
            gain = (_f(M[:, rj] + r[rj]) - _f(M[:, rj])).sum(axis=1)
            gain += (_f(M[li, :] + l[li, None]) - _f(M[li, :])).sum(axis=0)
            diagonal = np.diag(M)
            gain -= (_f(diagonal + r) - _f(diagonal)) + (_f(diagonal + l) - _f(diagonal))
            gain += _f(diagonal + r + l + itself) - _f(diagonal)
            gain -= 2 * (_f(sizes + nw) - _f(sizes))
            gain[0] = gain[groups] = -np.inf
            b = int(np.argmax(gain))
            if gain[b] <= gain[a] + 1e-9:
                b = a
            M[b, :] += r
            M[:, b] += l
            M[b, b] += itself
            sizes[b] += nw
            if b != a:
                grouped[w] = b
                moved += 1
        M = np.zeros((size, size))
        np.add.at(M, (grouped[left], grouped[right]), n)
        if say:
            say(f"round {round_ + 1}: {moved:,} moved, {time.perf_counter() - started:.0f}s")
        if moved < len(order) / 500:
            break
    return {str(names[k]): int(grouped[k]) for k in order}


def read_groups(path: str) -> Dict[str, int]:
    """A table of word to group as `counted_groups` gives it and GROUPS-01 writes it: a word and its group a line,
    split by a tab, the most frequent word first."""
    with open(path, encoding="utf-8") as handle:
        return {word: int(group) for word, group in (line.rstrip("\n").split("\t") for line in handle if line.strip())}


@dataclass(frozen=True)
class WordGroup:
    """One group of words that keep the same company, as counted from a text (`counted_groups`): the text, how many
    groups it was counted into, the group's number and its words, the most frequent first. Memory holds each group
    whole, one memory a group (`MemoryAgent.remember_word_groups`)."""

    counted_from: str
    of: int
    group: int
    words: Tuple[str, ...]

    def key(self) -> str:
        return f"{self.counted_from}:{self.of}:{self.group}"

    def claim(self) -> str:
        """The belief this group stands on: that these words keep the same company in the text."""
        return f"the words of group {self.group} of {self.of} keep the same company in {self.counted_from}"

    def said(self) -> str:
        """The group, said plainly over two lines, so memory keeps it as a record and never reads it as a claim
        (`_readable_claim`)."""
        return f"Words keeping the same company in {self.counted_from}, group {self.group} of {self.of}:\n" + \
            ", ".join(self.words)

    def to_dict(self) -> Dict[str, Any]:
        return {"counted_from": self.counted_from, "of": self.of, "group": self.group, "words": list(self.words)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WordGroup":
        return cls(str(data["counted_from"]), int(data["of"]), int(data["group"]), tuple(data["words"]))


def groups_of(table: Mapping[str, int], of: int, counted_from: str) -> List[WordGroup]:
    """A table of word to group (`counted_groups`, `read_groups`), counted into `of` groups, as its groups in the order
    of their numbers."""
    members: Dict[int, List[str]] = {}
    for word, group in table.items():
        members.setdefault(int(group), []).append(word)
    return [WordGroup(counted_from, of, group, tuple(members[group])) for group in sorted(members)]


class WordGroups:
    """The word groups memory holds, by the counting each is of: what the structure reader stands beside each word
    (`grouping`)."""

    def __init__(self) -> None:
        self._held: Dict[Tuple[str, int], Dict[int, WordGroup]] = {}

    def __len__(self) -> int:
        return sum(len(groups) for groups in self._held.values())

    def hold(self, group: WordGroup) -> None:
        self._held.setdefault((group.counted_from, group.of), {})[group.group] = group

    def grouping(self) -> Optional[Callable[[Tuple[str, ...]], Sequence[Tuple[str, str]]]]:
        """Each word's coarse and fine group, as `grouping` gives them, from the groups held of one text: its counting
        into the most groups the fine, into the fewest the coarse. None where none is held. Of several texts, the one
        with the most groups held."""
        if not self._held:
            return None
        text = max({t for t, _ in self._held}, key=lambda t: sum(len(g) for (u, _), g in self._held.items() if u == t))
        counts = sorted(of for t, of in self._held if t == text)

        def table(of: int) -> Dict[str, int]:
            return {word: group.group for group in self._held[(text, of)].values() for word in group.words}
        return grouping(table(counts[-1]), table(counts[0]))


def grouping(fine: Dict[str, int], coarse: Dict[str, int]) -> Callable[[Tuple[str, ...]], Sequence[Tuple[str, str]]]:
    """For `StructureView.grouping`: each word of a sentence, lowered, with its coarse and its fine group; a word in
    neither, ungrouped."""
    from core.semantics.structure import UNGROUPED

    def of(words: Tuple[str, ...]) -> Sequence[Tuple[str, str]]:
        return [(str(coarse.get(w.lower(), UNGROUPED)), str(fine.get(w.lower(), UNGROUPED))) for w in words]
    return of
