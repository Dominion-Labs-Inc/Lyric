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
from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

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


def grouping(fine: Dict[str, int], coarse: Dict[str, int]) -> Callable[[Tuple[str, ...]], Sequence[Tuple[str, str]]]:
    """For `StructureView.grouping`: each word of a sentence, lowered, with its coarse and its fine group; a word in
    neither, ungrouped."""
    from core.semantics.structure import UNGROUPED

    def of(words: Tuple[str, ...]) -> Sequence[Tuple[str, str]]:
        return [(str(coarse.get(w.lower(), UNGROUPED)), str(fine.get(w.lower(), UNGROUPED))) for w in words]
    return of
