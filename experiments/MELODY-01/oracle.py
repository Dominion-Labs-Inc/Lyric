import sys, os, numpy as np
sys.path.insert(0, "/Users/stefan/Dominion Labs/Lyric"); sys.path.insert(0, ".")
from multiprocessing import Pool
from melody_eval import songs, truth, DATA

def one(name):
    from core.perception import hearing
    import melody_methods as M
    y = hearing.decode(os.path.join(DATA, "audio_mix", name + "_MIX_melsynth.wav"))[:60 * hearing.SR]
    s = M.salience(M._highpassed(y), harmonics=20, beta=0.5)
    t = np.arange(len(s)) * M.HOP / M.SR
    tr, fr = truth(name)
    ref = fr[np.clip(np.searchsorted(tr, t), 0, len(tr) - 1)]
    v = ref > 0
    fp = M._frame_peaks(s)
    hits = {1: 0, 3: 0, 5: 0, 10: 0}; fold = {1: 0, 3: 0, 5: 0, 10: 0}
    for i in np.flatnonzero(v):
        b, val = fp[i]
        if not len(b): continue
        order = b[np.argsort(-val)]
        want = 1200 * np.log2(ref[i] / M.F_LO) / M.BIN_CENTS
        d = np.abs(order - want)
        df = np.abs(((order - want + 60) % 120) - 60)
        for k in hits:
            hits[k] += bool((d[:k] <= 5).any()); fold[k] += bool((df[:k] <= 5).any())
    n = max(v.sum(), 1)
    return {k: hits[k] / n for k in hits}, {k: fold[k] / n for k in fold}

if __name__ == "__main__":
    with Pool(12) as p:
        got = p.map(one, songs("DEV"))
    for k in (1, 3, 5, 10):
        print(f"true pitch among the top {k:2} salience peaks: {np.mean([g[0][k] for g in got]):.3f}  (any octave: {np.mean([g[1][k] for g in got]):.3f})")
