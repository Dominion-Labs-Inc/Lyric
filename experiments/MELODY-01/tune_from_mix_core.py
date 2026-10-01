"""End to end with the substrate's own code only: songs taught from their MIX
(`music.melody_of_mix` -> `music.tune_line`, kept as read from a mix), heard
as 20 s of their melody sung alone (the melody stem: `music.pitch_track` ->
`music.tune_line`), named by `music.tunes_heard`."""
import argparse
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "/Users/stefan/Dominion Labs/Lyric")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from melody_eval import DATA, songs          # noqa: E402
from tune_from_mix import stem_path, excerpt  # noqa: E402

CACHE = "/Users/stefan/Dominion Labs/Lyric/test_data/music/MDB-melody-synth/cache_core"


def get(name, what):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f"{name}.{what}.npy")
    if os.path.exists(fn):
        return np.load(fn)
    from core.perception import hearing, music
    if what == "mix":
        f0 = music.melody_of_mix(hearing.decode(os.path.join(DATA, "audio_mix", name + "_MIX_melsynth.wav")))["f0"]
    else:
        f0 = music.pitch_track(hearing.decode(stem_path(name)))["f0"]
    np.save(fn, np.asarray(f0, np.float32))
    return np.asarray(f0, np.float32)


def prepare(name):
    get(name, "mix"); get(name, "stem")
    return name


def line(f0):
    from core.perception import music
    return music.tune_line({"f0": f0, "periodic": (np.asarray(f0) > 0).astype(np.float32)})


def run(taught_names, heard_names, label):
    from core.perception import music
    taught = {n: [{"line": line(get(n, "mix")), "mix": True}] for n in taught_names}
    taught = {n: v for n, v in taught.items() if v[0]["line"] is not None}
    right = named = named_right = 0
    for n in heard_names:
        heard = line(excerpt(get(n, "stem")))
        costs = sorted((music._follow(heard, taught[m][0]["line"], music._TUNE_SHIFTS, True)[0], m)
                       for m in taught)
        right += costs[0][1] == n
        found = music.tunes_heard(heard, taught)
        named += bool(found)
        named_right += bool(found) and found[0]["song"] == n
    k = len(heard_names)
    print(f"{label}: {k} heard against {len(taught)} taught from mixes: right first {right / k:.3f}; "
          f"named {named / k:.3f}, right when named {named_right / max(named, 1):.3f} "
          f"({named - named_right} named wrongly)", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="DEV")
    a = ap.parse_args()
    names = songs(a.split)
    other = songs("TEST" if a.split == "DEV" else "DEV")
    with Pool(12) as pool:
        list(pool.imap_unordered(prepare, names + other))
    run(names, names, f"{a.split} taught")
    run(other, names, f"{a.split} NEVER taught (the other split taught)")
