"""SPEECH-03, offline: frequency warping per utterance (Lee and Rose 1996) for frames given their phones.

Each heard utterance's band energies are measured with the ear's speech bands laid on a frequency axis stretched by
each factor, 0.88 to 1.12. The factor kept is the one under which the heard frames agree most clearly with the
taught ones: the mean share of a frame's nearest taught frames its most-voted phone holds. No label is used to
choose it. Taught frames are as measured (no warp). Scored on every seventh frame of 292 test-clean utterances.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_warp.py
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
FACTORS = (0.88, 0.92, 0.96, 1.0, 1.04, 1.08, 1.12)


def main() -> int:
    import io
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import speech as SP
    import phones as P

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
    started = time.time()
    taught = P.Taught()
    print(f"taught: {len(taught.frames)} frames ({time.time() - started:.0f} s)", flush=True)
    labelled = P.utterances("test_clean", 9)
    table = pq.read_table(P.ALIGNED / "test_clean.parquet", columns=["audio"])
    audio = [row["audio"]["bytes"] for k, row in enumerate(table.to_pylist()) if k % 9 == 0]
    plain_right = warped_right = total = 0
    chosen = []
    for (_, bands, phones, _), raw in zip(labelled, audio):
        y, rate = sf.read(io.BytesIO(raw))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        padded = np.pad(np.asarray(y, dtype=np.float64), (SP._NFFT // 2, SP._NFFT // 2))
        power = np.abs(np.fft.rfft(np.lib.stride_tricks.sliding_window_view(padded, SP._NFFT)[::SP._HOP]
                                   * np.hanning(SP._NFFT), axis=1)) ** 2
        known = np.flatnonzero(phones != "")[::7]
        truth = np.array([taught.index.get(p, -1) for p in phones[known]])
        best = None
        for factor in FACTORS:
            warped = np.log(power @ banks[factor].T + SP._EPS).astype(np.float32)
            logp = taught.sounds_like(P.measured(warped)[known])
            clear = float(np.exp(logp.max(axis=1)).mean())
            right = int((logp.argmax(axis=1) == truth).sum())
            if factor == 1.0:
                plain_right += right
            if best is None or clear > best[0]:
                best = (clear, factor, right)
        warped_right += best[2]
        chosen.append(best[1])
        total += len(known)
    print(f"  as measured: {100 * plain_right / total:.1f}%; each utterance at its clearest factor: "
          f"{100 * warped_right / total:.1f}% of {total} frames; factors chosen "
          f"{dict(zip(*np.unique(chosen, return_counts=True)))} ({time.time() - started:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
