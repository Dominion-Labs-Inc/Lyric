"""SPEECH-03, offline: which way of measuring a frame lets an untaught speaker's frames be given their phones.

No store and no substrate. Log speech-band energies of every 10 ms frame are measured once and kept (`work/`), for
dev-clean (40 speakers, to teach) and a ninth of test-clean (40 other speakers, to hear; every seventh frame scored). Each way below is then
made from them, a heard frame is given the phone most of its 25 nearest taught frames have, and how often that is
its phone is counted. Nothing is trained; `scaled` divides each measure by its spread over the taught frames.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_frames.py
"""
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
WORK = HERE / "work"
import os
PER_SPEAKER = int(os.environ.get("PER_SPEAKER", 120))     # frames of a phone kept from one teaching speaker
PER_UTTERANCE = int(os.environ.get("PER_UTTERANCE", 6))   # and from one utterance
NEAREST = int(os.environ.get("NEAREST", 25))
EVERY = 7                  # of the frames heard, the ones scored: about 31,000, enough to tell the ways apart


def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    import scipy.fft
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import speech as SP
    WORK.mkdir(exist_ok=True)
    rng = np.random.default_rng(20261003)
    plain = lambda phone: phone.rstrip("012")

    band_hi = float(os.environ.get("BAND_HI", SP.SPEECH_BAND[1]))
    bands_n = int(os.environ.get("BANDS", SP._BANDS))

    def bank():
        """The ear's mel bank, over 100 Hz to `BAND_HI`, in `BANDS` bands."""
        to_mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
        to_hz = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)
        edges = to_hz(np.linspace(to_mel(SP.SPEECH_BAND[0]), to_mel(band_hi), bands_n + 2))
        freqs = np.fft.rfftfreq(SP._NFFT, 1.0 / SP.SR)
        out = np.zeros((bands_n, len(freqs)))
        for b in range(bands_n):
            lo, mid, hi = edges[b:b + 3]
            out[b] = np.clip(np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)), 0, None)
        return out

    BANK = bank()

    def energies(y):
        """Log energy in each band, every 10 ms."""
        padded = np.pad(np.asarray(y, dtype=np.float64), (SP._NFFT // 2, SP._NFFT // 2))
        frames = np.lib.stride_tricks.sliding_window_view(padded, SP._NFFT)[::SP._HOP]
        power = np.abs(np.fft.rfft(frames * np.hanning(SP._NFFT), axis=1)) ** 2
        return np.log(power @ BANK.T + SP._EPS).astype(np.float32)

    def split(name, every):
        cache = WORK / f"energies_{name}_{int(band_hi)}_{bands_n}.npz"
        if cache.exists():
            held = np.load(cache, allow_pickle=True)
            return list(zip(held["speaker"], held["bands"], held["phones"]))
        table = pq.read_table(ALIGNED / f"{name}.parquet", columns=["id", "phonemes", "audio"])
        out = []
        for k, row in enumerate(table.to_pylist()):
            if k % every:
                continue
            y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
            bands = energies(resample_poly(y, H.SR, rate) if rate != H.SR else y)
            lab = np.array(["sil"] * len(bands), dtype=object)
            for p in row["phonemes"]:
                lo, hi = int(np.ceil(p["start"] * H.SR / SP._HOP)), int(p["end"] * H.SR / SP._HOP)
                lab[lo:hi + 1] = "" if p["phoneme"] == "spn" else plain(p["phoneme"])
            out.append((row["id"].split("-")[0], bands, lab))
        np.savez(cache, speaker=np.array([o[0] for o in out], dtype=object),
                 bands=np.array([o[1] for o in out], dtype=object), phones=np.array([o[2] for o in out], dtype=object))
        return out

    started = time.time()
    teach, hear = split("dev_clean", 1), split("test_clean", 9)
    print(f"measured: {len(teach)} utterances to teach, {len(hear)} to hear ({time.time() - started:.0f} s)", flush=True)

    def around(x, reach):
        if not reach:
            return x
        pad = np.pad(x, ((reach, reach), (0, 0)), mode="edge")
        return np.concatenate([pad[k:k + len(x)] for k in range(0, 2 * reach + 1, max(reach // 2, 1))], axis=1)

    def made(bands, how):
        """One utterance's frames, measured one way."""
        base, _, rest = how.partition("+")
        if base == "cep":            # the ear's: 12 cepstra, the channel (a running second's mean) removed
            x = scipy.fft.dct(bands, type=2, norm="ortho", axis=1)[:, 1:SP._CEPSTRA + 1]
        else:                        # the 26 band energies themselves
            x = bands
        x = x - SP._running_mean(x)
        parts = [x]
        if "d" in rest:
            parts.append(np.gradient(x, axis=0))
        if "dd" in rest:
            parts.append(np.gradient(np.gradient(x, axis=0), axis=0))
        out = np.concatenate(parts, axis=1)
        reach = next((int(r[1:]) for r in rest.split("+") if r.startswith("c")), 0)
        return around(out, reach).astype(np.float32)

    # The teaching frames: a few of each phone an utterance, no more than PER_SPEAKER of a phone from one speaker.
    picks, seen = [], Counter()
    for u, (speaker, bands, lab) in enumerate(teach):
        for phone in set(lab) - {""}:
            at = np.flatnonzero(lab == phone)
            for i in rng.choice(at, size=min(len(at), PER_UTTERANCE), replace=False):
                if seen[(speaker, phone)] < PER_SPEAKER:
                    seen[(speaker, phone)] += 1
                    picks.append((u, int(i), phone))
    phones = sorted({p for _, _, p in picks})
    index = {p: i for i, p in enumerate(phones)}
    taught_id = np.array([index[p] for _, _, p in picks])
    by_utterance = {}
    for row, (u, i, _) in enumerate(picks):
        by_utterance.setdefault(u, []).append((row, i))
    print(f"taught: {len(picks)} frames of {len(phones)} phones", flush=True)

    report = {}
    for how in sys.argv[1:] or ("cep+d", "cep+d+c2", "cep+d+c4", "bands+d", "bands+d+c2", "bands+d+c4",
                                "cep+d+dd", "cep+d+c2+scaled", "bands+d+c2+scaled"):
        begun = time.time()
        scaled = how.endswith("+scaled")
        way = how[:-len("+scaled")] if scaled else how
        X = None
        for u, rows in by_utterance.items():
            f = made(teach[u][1], way)
            if X is None:
                X = np.zeros((len(picks), f.shape[1]), dtype=np.float32)
            for row, i in rows:
                X[row] = f[i]
        spread = X.std(axis=0) + 1e-6 if scaled else 1.0
        X = X / spread
        x2 = (X ** 2).sum(axis=1)
        right = total = 0
        for speaker, bands, lab in hear:
            known = np.flatnonzero(lab != "")[::EVERY]
            q = made(bands, way)[known] / spread
            truth = np.array([index.get(p, -1) for p in lab[known]])
            for lo in range(0, len(q), 512):
                part = q[lo:lo + 512]
                d = (part ** 2).sum(axis=1)[:, None] + x2[None, :] - 2.0 * part @ X.T
                near = taught_id[np.argpartition(d, NEAREST, axis=1)[:, :NEAREST]]
                votes = np.zeros((len(part), len(phones)), dtype=np.int32)
                np.add.at(votes, (np.arange(len(part))[:, None], near), 1)
                right += int((votes.argmax(axis=1) == truth[lo:lo + 512]).sum())
            total += len(known)
        report[how] = round(100 * right / total, 1)
        print(f"  {how:22s} {X.shape[1]:3d} measures a frame: {100 * right / total:.1f}% of {total} frames given "
              f"their phone ({time.time() - begun:.0f} s)", flush=True)
    (WORK / "offline_frames.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
