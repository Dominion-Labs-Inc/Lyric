"""Melody from a full mix, against MDB-melody-synth's exact melody f0.

Scores (as mir_eval's melody metrics, on a 10 ms grid):
  RPA  raw pitch accuracy: of the frames with melody, pitch within 50 cents
  RCA  the same, octave errors forgiven
  VR   voicing recall: of the frames with melody, said to have one
  VFA  voicing false alarm: of the frames without, said to have one
  OA   overall accuracy: frames right in voicing and (when voiced) pitch
"""
import argparse
import csv
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "/Users/stefan/Dominion Labs/Lyric")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DATA = "/Users/stefan/Dominion Labs/Lyric/test_data/music/MDB-melody-synth"
GRID = 0.01


def songs(which):
    names = sorted(n[:-len("_MIX_melsynth.wav")] for n in os.listdir(os.path.join(DATA, "audio_mix")))
    dev, test = names[0::2], names[1::2]
    return {"DEV": dev, "TEST": test, "ALL": names}[which]


def truth(name):
    fn = next(f for f in os.listdir(os.path.join(DATA, "annotation_melody")) if f.startswith(name + "_"))
    rows = np.array([[float(a), float(b)] for a, b in csv.reader(open(os.path.join(DATA, "annotation_melody", fn)))])
    return rows[:, 0], rows[:, 1]


def on_grid(t, f, end):
    grid = np.arange(0, end, GRID)
    idx = np.clip(np.searchsorted(t, grid), 0, len(t) - 1)
    return grid, f[idx]


def score(ref, est):
    rv, ev = ref > 0, est > 0
    cents = np.zeros(len(ref))
    both = rv & ev
    cents[both] = 1200 * np.abs(np.log2(est[both] / ref[both]))
    chroma = np.abs(((cents + 600) % 1200) - 600)
    rpa = np.mean(cents[rv] <= 50) if False else np.sum(both & (cents <= 50)) / max(rv.sum(), 1)
    rca = np.sum(both & (chroma <= 50)) / max(rv.sum(), 1)
    vr = np.sum(both) / max(rv.sum(), 1)
    vfa = np.sum(ev & ~rv) / max((~rv).sum(), 1)
    oa = (np.sum(~rv & ~ev) + np.sum(both & (cents <= 50))) / len(ref)
    # Pitch alone, voicing aside: every frame with melody given the estimate's pitch.
    return {"RPA": rpa, "RCA": rca, "VR": vr, "VFA": vfa, "OA": oa}


def one(args):
    name, method, seconds = args
    from core.perception import hearing
    import melody_methods as M
    y = hearing.decode(os.path.join(DATA, "audio_mix", name + "_MIX_melsynth.wav"))
    if seconds:
        y = y[:int(seconds * hearing.SR)]
    t_est, f_est = getattr(M, method)(y)
    t_ref, f_ref = truth(name)
    end = min(t_ref[-1], len(y) / hearing.SR)
    _, ref = on_grid(t_ref, f_ref, end)
    _, est = on_grid(np.asarray(t_est), np.asarray(f_est), end)
    return name, score(ref, est)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="DEV")
    ap.add_argument("--method", default="yin_on_mix")
    ap.add_argument("--seconds", type=float, default=0.0, help="only the first N seconds of each song")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    names = songs(a.split)
    if a.limit:
        names = names[:a.limit]
    with Pool(min(12, len(names))) as pool:
        got = pool.map(one, [(n, a.method, a.seconds) for n in names])
    keys = ("RPA", "RCA", "VR", "VFA", "OA")
    for n, s in got:
        print(f"{n[:40]:40} " + " ".join(f"{k} {s[k]:.3f}" for k in keys))
    print(f"\n{a.split} {a.method} ({len(got)} songs" + (f", first {a.seconds:.0f} s" if a.seconds else "") + "): "
          + " ".join(f"{k} {np.mean([s[k] for _, s in got]):.3f}" for k in keys))
