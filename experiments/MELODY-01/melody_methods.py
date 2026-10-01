"""Melody from a mix: the methods measured. Each returns (times, f0 Hz, 0 = none)."""
import numpy as np

from core.perception import hearing, music

SR, HOP = hearing.SR, hearing.HOP
FRAME, NFFT = 1024, 4096               # 46 ms, zero-padded four times
F_LO, F_HI = 55.0, 1760.0
BIN_CENTS = 10.0
N_BINS = int(round(1200 * np.log2(F_HI / F_LO) / BIN_CENTS))
PEAK_MAX_HZ = 5000.0
GAMMA_DB = 40.0
HARMONICS, ALPHA = 8, 0.8
SPREAD_BINS = 10                        # a peak reaches +-100 cents


def yin_on_mix(y):
    track = music.pitch_track(y)
    t = np.arange(len(track["f0"])) * HOP / SR
    return t, track["f0"]


def peaks(y):
    """Each frame's spectral peaks: (frame, Hz, linear magnitude)."""
    pad = FRAME // 2
    y = np.pad(y.astype(np.float64), (pad, pad))
    view = np.lib.stride_tricks.sliding_window_view(y, FRAME)[::HOP]
    win = np.hanning(FRAME)
    freqs_per_bin = SR / NFFT
    hi = int(PEAK_MAX_HZ / freqs_per_bin)
    fr, hz, mag = [], [], []
    for i in range(0, len(view), 512):
        m = np.abs(np.fft.rfft(view[i:i + 512] * win, n=NFFT, axis=1))[:, :hi + 2]
        db = 20 * np.log10(m + 1e-10)
        top = db.max(axis=1, keepdims=True)
        mid = db[:, 1:-1]
        is_peak = (mid > db[:, :-2]) & (mid >= db[:, 2:]) & (mid > top - GAMMA_DB)
        f_i, b_i = np.nonzero(is_peak)
        b = b_i + 1
        a, c, p = db[f_i, b - 1], db[f_i, b + 1], db[f_i, b]
        den = a - 2 * p + c
        shift = np.where(np.abs(den) > 1e-9, 0.5 * (a - c) / np.where(np.abs(den) > 1e-9, den, 1), 0.0)
        shift = np.clip(shift, -0.5, 0.5)
        fr.append(f_i + i)
        hz.append((b + shift) * freqs_per_bin)
        mag.append(10 ** ((p - 0.25 * (a - c) * shift) / 20))
    return len(view), np.concatenate(fr), np.concatenate(hz), np.concatenate(mag)


def salience(y, harmonics=HARMONICS, alpha=ALPHA, beta=1.0):
    """The salience of every 10-cent pitch bin at every frame: each peak counted
    as the h-th harmonic of the pitch h times below it, weighted alpha^(h-1)
    and by a squared cosine of its distance from the bin."""
    n, fr, hz, mag = peaks(y)
    sal = np.zeros(n * N_BINS)
    for h in range(1, harmonics + 1):
        f0 = hz / h
        ok = (f0 >= F_LO * 2 ** (-SPREAD_BINS * BIN_CENTS / 1200)) & (f0 <= F_HI)
        b = 1200 * np.log2(f0[ok] / F_LO) / BIN_CENTS
        base = np.round(b).astype(int)
        w0 = mag[ok] ** beta * alpha ** (h - 1)
        frames = fr[ok]
        for d in range(-SPREAD_BINS, SPREAD_BINS + 1):
            bins = base + d
            dist = np.abs(b - bins) / SPREAD_BINS
            keep = (dist < 1) & (bins >= 0) & (bins < N_BINS)
            np.add.at(sal, frames[keep] * N_BINS + bins[keep], w0[keep] * np.cos(0.5 * np.pi * dist[keep]) ** 2) if False else None
            sal += np.bincount(frames[keep] * N_BINS + bins[keep],
                               weights=w0[keep] * np.cos(0.5 * np.pi * dist[keep]) ** 2,
                               minlength=n * N_BINS)
    return sal.reshape(n, N_BINS)


def bin_hz(b):
    return F_LO * 2 ** (np.asarray(b) * BIN_CENTS / 1200)


def salience_argmax(y):
    """Pitch alone: the most salient bin at every frame, every frame voiced."""
    s = salience(y)
    f0 = bin_hz(np.argmax(s, axis=1))
    f0[s.max(axis=1) <= 0] = 0
    t = np.arange(len(f0)) * HOP / SR
    return t, f0


def _argmax_of(s):
    f0 = bin_hz(np.argmax(s, axis=1))
    f0[s.max(axis=1) <= 0] = 0
    return np.arange(len(f0)) * HOP / SR, f0


def argmax_h20(y):
    return _argmax_of(salience(y, harmonics=20))


def argmax_h12_a09(y):
    return _argmax_of(salience(y, harmonics=12, alpha=0.9))


def argmax_sqrtmag(y):
    """Peak magnitudes compressed (square root) before summing."""
    global peaks
    orig = peaks
    def compressed(y):
        n, fr, hz, mag = orig(y)
        return n, fr, hz, np.sqrt(mag)
    peaks = compressed
    try:
        return _argmax_of(salience(y, harmonics=20))
    finally:
        peaks = orig


def _variant(h, a, b):
    return lambda y: _argmax_of(salience(y, harmonics=h, alpha=a, beta=b))


for _h in (12, 20):
    for _b in (0.25, 0.33, 0.5):
        globals()[f"arg_h{_h}_b{str(_b).replace('.', '')}"] = _variant(_h, 0.8, _b)


# --- contours and melody selection (Salamon & Gomez 2012, simplified) -------------
TAU_PLUS = 0.9          # a frame's peaks within this share of its strongest are candidates
TAU_SIGMA = 0.9         # ... and not below the song's mean - 0.9 std of candidates
STEP_BINS = 8           # a contour moves at most 80 cents a frame
GAP_FRAMES = int(round(0.1 * SR / HOP))   # 100 ms of weaker peaks bridge a gap
MIN_FRAMES = int(round(0.1 * SR / HOP))   # a contour lasts at least 100 ms
NU = 0.2                # voicing: contours below mean - NU std of contour saliences dropped
SMOOTH_S = 5.0          # the melody's pitch path, smoothed over 5 s


def _frame_peaks(s):
    """Per frame: arrays of (bin, salience) of its local maxima across bins."""
    left = np.zeros_like(s); left[:, 1:] = s[:, :-1]
    right = np.zeros_like(s); right[:, :-1] = s[:, 1:]
    is_peak = (s > left) & (s >= right) & (s > 0)
    out = []
    for t in range(len(s)):
        b = np.flatnonzero(is_peak[t])
        out.append((b, s[t, b]))
    return out


def contours(s):
    fp = _frame_peaks(s)
    n = len(s)
    plus, minus = [], []
    for t, (b, v) in enumerate(fp):
        top = v.max() if len(v) else 0.0
        keep = v >= TAU_PLUS * top
        plus.append(dict(zip(b[keep].tolist(), v[keep].tolist())))
        minus.append(dict(zip(b[~keep].tolist(), v[~keep].tolist())))
    allv = np.array([x for d in plus for x in d.values()])
    if not len(allv):
        return []
    floor = allv.mean() - TAU_SIGMA * allv.std()
    for t in range(n):
        for b in [b for b, v in plus[t].items() if v < floor]:
            minus[t][b] = plus[t].pop(b)
    order = sorted(((v, t, b) for t in range(n) for b, v in plus[t].items()), reverse=True)
    used = [set() for _ in range(n)]
    found = []
    for v0, t0, b0 in order:
        if b0 in used[t0] or b0 not in plus[t0]:
            continue
        pts = {t0: (b0, v0)}
        used[t0].add(b0)
        for direction in (1, -1):
            t, b, gap = t0, b0, 0
            while 0 <= t + direction < n:
                t += direction
                cand = [(bb, vv, True) for bb, vv in plus[t].items() if abs(bb - b) <= STEP_BINS and bb not in used[t]]
                if not cand:
                    cand = [(bb, vv, False) for bb, vv in minus[t].items() if abs(bb - b) <= STEP_BINS and bb not in used[t]]
                    gap += 1
                    if not cand or gap > GAP_FRAMES:
                        break
                else:
                    gap = 0
                bb, vv, strong = min(cand, key=lambda c: abs(c[0] - b))
                used[t].add(bb)
                if strong:
                    plus[t].pop(bb, None)
                pts[t] = (bb, vv)
                b = bb
        if len(pts) >= MIN_FRAMES:
            ts = np.array(sorted(pts))
            bins = np.array([pts[t][0] for t in ts], float)
            sal = np.array([pts[t][1] for t in ts])
            found.append({"t": ts, "bin": bins, "sal": sal, "mean_bin": float(np.mean(bins)),
                          "mean_sal": float(sal.mean()), "total": float(sal.sum())})
    return found


def _pitch_path(cs, n):
    """The melody's pitch path: per frame the salience-weighted mean bin of the
    contours present, smoothed over SMOOTH_S and carried across gaps."""
    num, den = np.zeros(n), np.zeros(n)
    for c in cs:
        num[c["t"]] += c["bin"] * c["sal"]
        den[c["t"]] += c["sal"]
    have = den > 0
    if not have.any():
        return np.full(n, N_BINS / 2)
    path = np.interp(np.arange(n), np.flatnonzero(have), num[have] / den[have])
    w = max(1, int(SMOOTH_S * SR / HOP))
    k = np.hanning(w); k /= k.sum()
    return np.convolve(np.pad(path, (w // 2, w - w // 2 - 1), mode="edge"), k, mode="valid")


def select(cs, n):
    if not cs:
        return np.zeros(n)
    ms = np.array([c["mean_sal"] for c in cs])
    cs = [c for c in cs if c["mean_sal"] >= ms.mean() - NU * ms.std()]
    for _ in range(3):
        path = _pitch_path(cs, n)
        # octave duplicates: overlapping contours an octave apart, the one farther from the path goes
        drop = set()
        for i, a in enumerate(cs):
            for j in range(i + 1, len(cs)):
                b = cs[j]
                lo, hi = max(a["t"][0], b["t"][0]), min(a["t"][-1], b["t"][-1])
                if hi <= lo:
                    continue
                if abs(abs(a["mean_bin"] - b["mean_bin"]) - 120) > 5:
                    continue
                da = np.abs(a["bin"][(a["t"] >= lo) & (a["t"] <= hi)] - path[lo:hi + 1][:np.sum((a["t"] >= lo) & (a["t"] <= hi))]).mean()
                db = np.abs(b["bin"][(b["t"] >= lo) & (b["t"] <= hi)] - path[lo:hi + 1][:np.sum((b["t"] >= lo) & (b["t"] <= hi))]).mean()
                drop.add(i if da > db else j)
        cs = [c for k, c in enumerate(cs) if k not in drop]
        path = _pitch_path(cs, n)
        # pitch outliers: more than an octave from the path
        cs = [c for c in cs if np.abs(c["bin"] - path[c["t"]]).mean() <= 120]
    f0 = np.zeros(n)
    best = np.full(n, -1.0)
    for c in cs:
        better = c["total"] > best[c["t"]]
        f0[c["t"][better]] = bin_hz(c["bin"][better])
        best[c["t"][better]] = c["total"]
    return f0


def melody(y, harmonics=20, beta=0.5):
    s = salience(y, harmonics=harmonics, beta=beta)
    cs = contours(s)
    f0 = select(cs, len(s))
    return np.arange(len(f0)) * HOP / SR, f0


def melody_b033(y):
    return melody(y, beta=0.33)


def _with(**kw):
    def run(y):
        g = globals()
        old = {k: g[k] for k in kw}
        g.update(kw)
        try:
            return melody(y)
        finally:
            g.update(old)
    return run


mel_nu0 = _with(NU=0.0)
mel_nu_m03 = _with(NU=-0.3)
mel_nu_m06 = _with(NU=-0.6)
mel_tau08 = _with(TAU_PLUS=0.8)
mel_tau08_nu_m03 = _with(TAU_PLUS=0.8, NU=-0.3)


def _highpassed(y, hz=150.0):
    from scipy.signal import butter, sosfiltfilt
    sos = butter(2, hz, btype="highpass", fs=SR, output="sos")
    return sosfiltfilt(sos, np.asarray(y, np.float64))


def mel_hp(y):
    g = globals(); old = g["NU"]; g["NU"] = -0.6
    try:
        return melody(_highpassed(y))
    finally:
        g["NU"] = old


def mel_hp_nu_m1(y):
    g = globals(); old = g["NU"]; g["NU"] = -1.0
    try:
        return melody(_highpassed(y))
    finally:
        g["NU"] = old


def _range(lo):
    def run(y):
        g = globals(); old = (g["F_LO"], g["N_BINS"], g["NU"])
        g["F_LO"] = lo; g["N_BINS"] = int(round(1200 * np.log2(F_HI / lo) / BIN_CENTS)); g["NU"] = -0.6
        try:
            return melody(_highpassed(y))
        finally:
            g["F_LO"], g["N_BINS"], g["NU"] = old
    return run


mel_hp_lo80 = _range(80.0)
mel_hp_lo100 = _range(100.0)


def _harmonic(y):
    import librosa
    return librosa.effects.harmonic(np.asarray(y, np.float32), margin=1.0)


def mel_hpss_hp(y):
    g = globals(); old = g["NU"]; g["NU"] = -0.6
    try:
        return melody(_highpassed(_harmonic(y)))
    finally:
        g["NU"] = old


# --- a Viterbi path through the salience ------------------------------------------
def viterbi_path(s, lam):
    """The pitch path (a bin per frame) minimising, over the song, each frame's
    -log(salience / the frame's strongest) plus `lam` per bin moved between
    frames. Each step is exact in O(bins): a cost linear in the distance is a
    running minimum from each side."""
    T, N = s.shape
    top = s.max(axis=1, keepdims=True)
    e = -np.log(np.where(top > 0, s / np.where(top > 0, top, 1.0), 1.0) + 1e-3).astype(np.float32)
    idx = (np.arange(N) * lam).astype(np.float32)
    C = np.empty((T, N), np.float32)
    C[0] = e[0]
    for t in range(1, T):
        p = C[t - 1]
        fwd = np.minimum.accumulate(p - idx) + idx
        bwd = np.minimum.accumulate((p + idx)[::-1])[::-1] - idx
        C[t] = e[t] + np.minimum(fwd, bwd)
    path = np.empty(T, int)
    path[-1] = int(np.argmin(C[-1]))
    ar = np.arange(N)
    for t in range(T - 1, 0, -1):
        path[t - 1] = int(np.argmin(C[t - 1] + lam * np.abs(ar - path[t])))
    return path


def vit(lam, harmonics=20, beta=0.5):
    def run(y):
        s = salience(_highpassed(y), harmonics=harmonics, beta=beta)
        path = viterbi_path(s, lam)
        f0 = bin_hz(path)
        f0[s.max(axis=1) <= 0] = 0
        return np.arange(len(f0)) * HOP / SR, f0
    return run


vit002, vit005, vit01, vit02 = vit(0.02), vit(0.05), vit(0.1), vit(0.2)
vit001, vit0005, vit0002 = vit(0.01), vit(0.005), vit(0.002)


def vit_voiced(v, lam=0.01):
    """Viterbi pitch; a frame voiced when the path's salience is at least v times
    the song's median path salience."""
    def run(y):
        s = salience(_highpassed(y), harmonics=20, beta=0.5)
        path = viterbi_path(s, lam)
        on = s[np.arange(len(s)), path]
        ref = np.median(on[on > 0]) if (on > 0).any() else 1.0
        f0 = bin_hz(path)
        f0[on < v * ref] = 0
        return np.arange(len(f0)) * HOP / SR, f0
    return run


def vit_contour_voiced(y, lam=0.01):
    """Viterbi pitch, voiced where the contour stage (NU -0.6) found melody."""
    hp = _highpassed(y)
    s = salience(hp, harmonics=20, beta=0.5)
    path = viterbi_path(s, lam)
    g = globals(); old = g["NU"]; g["NU"] = -0.6
    try:
        cf0 = select(contours(s), len(s))
    finally:
        g["NU"] = old
    f0 = bin_hz(path)
    f0[cf0 <= 0] = 0
    return np.arange(len(f0)) * HOP / SR, f0


vv05, vv075, vv1, vv125 = vit_voiced(0.5), vit_voiced(0.75), vit_voiced(1.0), vit_voiced(1.25)


def core_mix(y):
    """The substrate's own `music.melody_of_mix`."""
    got = music.melody_of_mix(y)
    return np.arange(len(got["f0"])) * HOP / SR, got["f0"]
