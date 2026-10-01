"""Query by humming on HumTrans: teach one hum per tune, recognise the others.

Library: one hum of every tune in the split (the first singer's first take),
plus one hum each of 300 training tunes that are never queried. Queries: every
other hum of the split's tunes (other singers, and the same singer's second
take). A tune is ranked by how well the query's melody line follows its line
(subsequence DTW over semitones from the line's own median, a few key shifts).
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FEAT = "/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/pitch"
SPLIT = "/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/train_valid_test_keys.json"
RATE = 22050 / 256            # pitch_track hops per second


def line(f0, periodic, fps, min_periodic):
    """The melody line: semitones at `fps` points a second over the sung
    windows only (rests dropped), from the line's own median."""
    m = np.zeros(len(f0))
    ok = (f0 > 0) & (periodic >= min_periodic)
    m[ok] = 69.0 + 12.0 * np.log2(f0[ok] / 440.0)
    w = max(1, int(round(RATE / fps)))
    pts = []
    for a in range(0, len(m) - w + 1, w):
        seg = m[a:a + w]
        seg = seg[seg > 0]
        if len(seg) >= w / 2:
            pts.append(np.median(seg))
    pts = np.array(pts)
    if len(pts) < 8:
        return None
    return pts - np.median(pts)


def sdtw_shift(q, r, shifts, cap):
    """As `sdtw`, returning (cost, the shift it was reached at)."""
    best, at = np.inf, 0.0
    for s in shifts:
        c = sdtw(q, r, [s], cap)
        if c < best:
            best, at = c, s
    return best, at


FOLD = False


def sdtw(q, r, shifts, cap):
    """Subsequence DTW cost of query line q inside reference line r, per query
    point, at the best of `shifts` (semitones). Steps (1,0),(1,1),(1,2): the
    reference advances 0 to 2 points per query point (half to double speed)."""
    n, m = len(q), len(r)
    best = np.inf
    for s in shifts:
        prev = np.zeros(m + 2)                       # free start anywhere in r
        for i in range(n):
            d = q[i] - r - s
            c = np.minimum(np.abs(((d + 6.0) % 12.0) - 6.0) if FOLD else np.abs(d), cap)
            cur = np.full(m + 2, np.inf)
            # cur[j+2] for r index j: from prev[j+2] (stay), prev[j+1] (step), prev[j] (skip)
            cur[2:] = c + np.minimum(np.minimum(prev[2:], prev[1:-1]), prev[:-2])
            prev = cur
        best = min(best, prev[2:].min() / n)
    return best


_LOCAL = {}


def local(r, w):
    """The reference line from its own median over a window of `w` points
    around each point, so a query that is part of it meets it in its key."""
    w = max(8, int(round(w / 8.0)) * 8)
    key = (id(r), w)
    if key not in _LOCAL:
        from scipy.ndimage import median_filter
        _LOCAL[key] = r - median_filter(r, size=w, mode="nearest")
    return _LOCAL[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="VALID")
    ap.add_argument("--fps", type=float, default=16.0)
    ap.add_argument("--cap", type=float, default=3.0)
    ap.add_argument("--min-periodic", type=float, default=0.5)
    ap.add_argument("--shifts", default="-1,-0.5,0,0.5,1")
    ap.add_argument("--queries", type=int, default=0, help="limit, 0 = all")
    ap.add_argument("--crop", type=float, default=1.0, help="keep this middle share of each query")
    ap.add_argument("--fold", action="store_true", help="forgive octave errors in the matching")
    ap.add_argument("--untaught", action="store_true",
                    help="teach none of the split's tunes: every naming of its hums is wrong")
    ap.add_argument("--dump", default="", help="write each query's own and best wrong cost here")
    ap.add_argument("--refine", type=int, default=0,
                    help="re-score the best N candidates at quarter-semitone shifts around their best")
    ap.add_argument("--local", action="store_true",
                    help="measure the reference from its median over a window the query's length")
    args = ap.parse_args()
    shifts = [float(s) for s in args.shifts.split(",")]
    global FOLD
    FOLD = args.fold
    where = {k: s for s, ks in json.load(open(SPLIT)).items() for k in ks}
    lines = {}
    for fn in sorted(os.listdir(FEAT)):
        key = fn[:-4]
        d = np.load(os.path.join(FEAT, fn))
        ln = line(d["f0"], d["periodic"], args.fps, args.min_periodic)
        if ln is not None:
            lines[key] = ln
    tune = lambda k: "_".join(k.split("_")[1:3])
    in_split = defaultdict(list)
    distractors = []
    for k in lines:
        s = where.get(k)
        if s == args.split:
            in_split[tune(k)].append(k)
        elif s == "TRAIN":
            distractors.append(k)
    library, queries = {}, []
    for t, ks in in_split.items():
        ks = sorted(ks)
        if args.untaught:
            queries += [(k, t) for k in ks]
        else:
            library[t] = ks[0]
            queries += [(k, t) for k in ks[1:]]
    for k in distractors:
        library.setdefault(tune(k), k)
    if args.untaught:
        # The other held-out split is taught in their place, with the 300.
        other = "VALID" if args.split == "TEST" else "TEST"
        for k in sorted(lines):
            if where.get(k) == other:
                library.setdefault(tune(k), k)
    if args.queries:
        rng = np.random.default_rng(0)
        queries = [queries[i] for i in rng.choice(len(queries), args.queries, replace=False)]
    names = sorted(library)
    refs = [lines[library[t]] for t in names]
    ranks, margins, dumped = [], [], []
    for n, (k, t) in enumerate(queries, 1):
        q = lines[k]
        if args.crop < 1.0:
            keep = max(8, int(len(q) * args.crop))
            a = (len(q) - keep) // 2
            q = q[a:a + keep] - np.median(q[a:a + keep])
        scored = [sdtw_shift(q, local(r, len(q)) if args.local else r, shifts, args.cap)
                  for r in refs]
        costs = np.array([c for c, _ in scored])
        if args.refine:
            for i in np.argsort(costs)[:args.refine]:
                at = scored[i][1]
                fine = [at + d for d in (-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75)]
                costs[i] = sdtw(q, refs[i], fine, args.cap)
        order = np.argsort(costs)
        if args.untaught:
            ranks.append(0)
            margins.append((costs[order[0]] / max(costs[order[1]], 1e-9), False))
            dumped.append({"query": k, "tune": t, "best_wrong": float(costs[order[0]]),
                           "ratio": float(costs[order[0]] / max(costs[order[1]], 1e-9))})
            continue
        rank = int(np.flatnonzero(np.array(names)[order] == t)[0]) + 1
        own = float(costs[names.index(t)])
        wrong = float(min(c for c, nm in zip(costs, names) if nm != t))
        dumped.append({"query": k, "tune": t, "own": own, "best_wrong": wrong, "rank": rank,
                       "ratio": float(costs[order[0]] / max(costs[order[1]], 1e-9))})
        ranks.append(rank)
        margins.append((costs[order[0]] / max(costs[order[1]], 1e-9), rank == 1))
        if n % 50 == 0 and not args.untaught:
            r = np.array(ranks)
            print(f"{n}/{len(queries)} top1={np.mean(r == 1):.3f} top5={np.mean(r <= 5):.3f} "
                  f"MRR={np.mean(1 / r):.3f}", flush=True)
    if args.dump:
        json.dump(dumped, open(args.dump, "w"))
    if args.untaught:
        ratio = np.array([m for m, _ in margins])
        print(f"\n{args.split} UNTAUGHT: {len(queries)} hums of tunes never taught, against {len(library)} taught tunes")
        for cut in (0.6, 0.7, 0.75, 0.8, 0.85, 0.9):
            print(f"  named (wrongly) at best/second <= {cut}: {np.mean(ratio <= cut):.3f}")
        return
    r = np.array(ranks)
    print(f"\n{args.split}: {len(queries)} queries against {len(names)} taught tunes "
          f"(crop={args.crop} local={args.local} refine={args.refine} fps={args.fps} cap={args.cap} min_periodic={args.min_periodic} shifts={shifts})")
    print(f"top1={np.mean(r == 1):.3f} top5={np.mean(r <= 5):.3f} top10={np.mean(r <= 10):.3f} "
          f"MRR={np.mean(1 / r):.3f}")
    ratio = np.array([m for m, _ in margins]); right = np.array([ok for _, ok in margins])
    for cut in (0.6, 0.7, 0.75, 0.8, 0.85, 0.9):
        named = ratio <= cut
        prec = right[named].mean() if named.any() else float("nan")
        print(f"  name only when best/second <= {cut}: named {named.mean():.3f}, right when named {prec:.3f}")


if __name__ == "__main__":
    main()
