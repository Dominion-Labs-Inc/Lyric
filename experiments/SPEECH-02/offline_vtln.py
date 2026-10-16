"""SPEECH-02, offline: does undoing the length of a speaker's vocal tract carry a word from one speaker to another?

A shorter vocal tract moves every resonance up by about the same factor, which is much of why one speaker's word
measures apart from another's. Vocal tract length normalisation (Lee and Rose 1996) measures the heard word with
the frequency axis stretched by each of a few factors and keeps the one that fits best. Here: the ear's own
measurements (speech-band cepstra less their mean, their change, formants), with the cepstra's filter bank laid on
a stretched axis, for factors 0.88 to 1.12; a heard word's distance to a taught example is the least over the
factors. Nothing is learned. Scored as `offline_speakers.py` scores, on the same clips.

    ./venv_lyric/bin/python3 experiments/SPEECH-02/offline_vtln.py [--words 100] [--speakers 20]
"""
import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
FACTORS = (0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12)


def main() -> int:
    import numpy as np
    import scipy.fft
    from core.perception import hearing as H
    from core.perception import speech as SP
    from clips import clips, present
    from fetch_mswc import lesson_words
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=100)
    parser.add_argument("--speakers", type=int, default=20)
    args = parser.parse_args()

    def bank(factor):
        to_mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
        to_hz = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)
        edges = to_hz(np.linspace(to_mel(SP.SPEECH_BAND[0]), to_mel(SP.SPEECH_BAND[1]), SP._BANDS + 2)) * factor
        freqs = np.fft.rfftfreq(SP._NFFT, 1.0 / SP.SR)
        out = np.zeros((SP._BANDS, len(freqs)))
        for b in range(SP._BANDS):
            lo, mid, hi = edges[b:b + 3]
            out[b] = np.clip(np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)), 0, None)
        return out

    banks = {f: bank(f) for f in FACTORS}

    def measured(path, factor):
        y = np.asarray(H.decode(str(path)), dtype=np.float64)
        lo, hi, _ = SP._extent(y)
        padded = np.pad(y, (SP._NFFT // 2, SP._NFFT // 2))
        frames = np.lib.stride_tricks.sliding_window_view(padded, SP._NFFT)[::SP._HOP]
        power = np.abs(np.fft.rfft(frames * np.hanning(SP._NFFT), axis=1)) ** 2
        cep = scipy.fft.dct(np.log(power @ banks[factor].T + SP._EPS), type=2, norm="ortho", axis=1)[:, 1:SP._CEPSTRA + 1]
        return SP._measure(y, cep, lo, hi)

    used = lesson_words()
    available = clips(set(used), args.speakers, 3)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w))
             if w in available and len(available[w]["teach"]) >= args.speakers and len(available[w]["heard"]) == 3]
    words = words[:args.words]
    rng = np.random.default_rng(20261003)
    work = HERE / "work" / "offline"
    started = time.time()
    taught = {w: [measured(present(c["path"], work / "teach" / w / f"{k}.wav", rng), 1.0)
                  for k, c in enumerate(available[w]["teach"][:args.speakers])] for w in words}
    heard = [(w, {f: measured(present(c["path"], work / "heard" / w / f"{k}.wav", rng), f) for f in FACTORS})
             for w in words for k, c in enumerate(available[w]["heard"])]
    print(f"{len(words)} words, {args.speakers} teaching speakers, {len(heard)} heard, {len(FACTORS)} factors; "
          f"measured in {time.time() - started:.0f} s", flush=True)
    started = time.time()
    plain = []
    warped = []
    for _, by in heard:
        d = {w: [{f: SP.warp(by[f], e) for f in FACTORS} for e in ex] for w, ex in taught.items()}
        plain.append({w: [x[1.0] for x in xs] for w, xs in d.items()})
        warped.append({w: [min(x.values()) for x in xs] for w, xs in d.items()})
    print(f"distances in {time.time() - started:.0f} s", flush=True)
    for name, table in (("as the ear measures", plain), ("with the best of the factors", warped)):
        for k in (1, 3):
            near = top5 = 0
            for (said, _), d in zip(heard, table):
                per = {w: float(np.mean(sorted(ds)[:k])) for w, ds in d.items()}
                order = sorted(per, key=per.get)
                near += order[0] == said
                top5 += said in order[:5]
            print(f"  {name}, k={k}: nearest {100 * near / len(heard):.1f}%, in the nearest five "
                  f"{100 * top5 / len(heard):.1f}%", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
