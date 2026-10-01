"""End to end: a song taught from its full mix, known from its melody sung alone.

Taught: each song's tune line (`music.tune_line`) from the melody extracted
from the whole MIX. Heard: a 20 s stretch of the song's melody stem alone (a
single line, as a person singing it would be), from the middle of where it
sings. Also, as the ceiling: tunes taught from the clean stem itself.
"""
import argparse
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "/Users/stefan/Dominion Labs/Lyric")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from melody_eval import DATA, songs   # noqa: E402

CACHE = "/Users/stefan/Dominion Labs/Lyric/test_data/music/MDB-melody-synth/cache"


def stem_path(name):
    d = os.path.join(DATA, "audio_melody")
    return os.path.join(d, next(f for f in os.listdir(d) if f.startswith(name + "_")))


def cached(name, what, method):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f"{name}.{what}.{method}.npy")
    if os.path.exists(fn):
        return np.load(fn)
    from core.perception import hearing, music
    import melody_methods as M
    if what == "mix":
        y = hearing.decode(os.path.join(DATA, "audio_mix", name + "_MIX_melsynth.wav"))
        f0 = getattr(M, method)(y)[1]
    else:
        f0 = music.pitch_track(hearing.decode(stem_path(name)))["f0"]
    np.save(fn, np.asarray(f0, np.float32))
    return np.asarray(f0, np.float32)


def prepare(args):
    name, method = args
    cached(name, "mix", method)
    cached(name, "stem", "yin")
    return name


def line_of(f0):
    from core.perception import music
    return music.tune_line({"f0": f0, "periodic": (np.asarray(f0) > 0).astype(np.float32)})


def excerpt(f0, seconds=20.0):
    """A stretch of `seconds` from the middle of where the stem has melody."""
    from core.perception.hearing import HOP, SR
    voiced = np.flatnonzero(np.asarray(f0) > 0)
    if not len(voiced):
        return f0
    mid = int(np.median(voiced))
    half = int(seconds * SR / HOP / 2)
    return f0[max(0, mid - half):mid + half]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="DEV")
    ap.add_argument("--method", default="mel_nu_m06")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--fold", action="store_true")
    a = ap.parse_args()
    names = songs(a.split)
    with Pool(min(12, len(names))) as pool:
        list(pool.imap_unordered(prepare, [(n, a.method) for n in names]))
    from core.perception import music
    if a.fold:
        from folding import follow_folded
        music._follow = follow_folded
    for taught_from in (("mix",) if a.fold else ("mix", "stem")):
        taught = {n: [line_of(cached(n, taught_from, a.method if taught_from == "mix" else "yin"))]
                  for n in names}
        right = named = named_right = 0
        for n in names:
            heard = line_of(excerpt(cached(n, "stem", "yin"), a.seconds))
            # rank all, and what tunes_heard names
            costs = sorted((music._follow(heard, taught[m][0], music._TUNE_SHIFTS)[0], m)
                           for m in names if taught[m][0] is not None)
            right += costs[0][1] == n
            found = music.tunes_heard(heard, taught)
            named += bool(found)
            named_right += bool(found) and found[0]["song"] == n
        print(f"{a.split} taught from the {taught_from} ({a.method if taught_from == 'mix' else 'clean stem'}), "
              f"heard {a.seconds:.0f} s of the melody alone, {len(names)} songs: right first "
              f"{right / len(names):.3f}; named {named / len(names):.3f}, right when named "
              f"{named_right / max(named, 1):.3f}", flush=True)
