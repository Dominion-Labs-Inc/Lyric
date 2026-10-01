"""Pitch-track every downloaded hum once (music.pitch_track) and cache it."""
import os
import sys
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, "/Users/stefan/Dominion Labs/Lyric")
WAV = "/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/wav"
OUT = "/Users/stefan/Dominion Labs/Lyric/test_data/music/humtrans/pitch"


def one(name):
    out = os.path.join(OUT, name[:-4] + ".npz")
    if os.path.exists(out):
        return name, True
    try:
        from core.perception import hearing, music
        y = hearing.decode(os.path.join(WAV, name))
        track = music.pitch_track(y)
        np.savez_compressed(out, f0=track["f0"].astype(np.float32),
                            periodic=track["periodic"].astype(np.float32),
                            seconds=np.float32(len(y) / hearing.SR))
        return name, True
    except Exception as error:
        return name, f"{type(error).__name__}: {error}"


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    names = sorted(n for n in os.listdir(WAV) if n.endswith(".wav"))
    bad = 0
    with Pool(8) as pool:
        for n, (name, ok) in enumerate(pool.imap_unordered(one, names, chunksize=4), 1):
            if ok is not True:
                bad += 1
                print("FAILED", name, ok, flush=True)
            if n % 200 == 0:
                print(n, "of", len(names), flush=True)
    print("DONE", len(names), "failed", bad, flush=True)
