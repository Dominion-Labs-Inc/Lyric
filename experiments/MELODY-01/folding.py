import numpy as np
from core.perception import music


def follow_folded(heard, taught, shifts):
    best, at = np.inf, 0.0
    heard = np.asarray(heard, float); taught = np.asarray(taught, float)
    for shift in shifts:
        prev = np.zeros(len(taught) + 2)
        for p in heard:
            d = p - taught - shift
            miss = np.minimum(np.abs(((d + 6.0) % 12.0) - 6.0), music._TUNE_MISS_CAP)
            cur = np.full(len(taught) + 2, np.inf)
            cur[2:] = miss + np.minimum(np.minimum(prev[2:], prev[1:-1]), prev[:-2])
            prev = cur
        c = float(prev[2:].min() / len(heard))
        if c < best: best, at = c, shift
    return best, at

