"""SPEECH-03: the sounds words are made of, taught from aligned speech and heard frame by frame.

What the offline studies share. No store and no substrate. Nothing is trained:
  - a frame is measured as the log energy in each of the ear's 26 speech bands, the channel removed (a running
    second's mean, as the ear measures words), with its change, and the same of the frames around it (`measured`);
  - the frames TAUGHT are those of each phone, cut by LibriSpeech's aligned phoneme times, a bounded number from
    each speaker so no voice outweighs the others (`Taught`);
  - a heard frame SOUNDS LIKE the phones its nearest taught frames are (k nearest neighbours; Fix and Hodges 1951);
  - a heard stretch FITS a word as well as its frames can be given, in order, to the word's phones, each lasting
    at least `SHORTEST` frames (Viterbi 1967).
"""
import io
import os
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
WORK = HERE / "work"
PER_SPEAKER = int(os.environ.get("PER_SPEAKER", 400))     # frames of a phone kept from one teaching speaker
PER_UTTERANCE = int(os.environ.get("PER_UTTERANCE", 20))  # and from one utterance
NEAREST = int(os.environ.get("NEAREST", 25))
REACH = int(os.environ.get("REACH", 6))                    # frames either side measured with each frame
CHANNEL = os.environ.get("CHANNEL", "mean")                # how the channel is removed: "mean" or "rasta"
TEACH = os.environ.get("TEACH", "dev_clean")                # the LibriSpeech splits the phones are taught from
#: A phone lasts at least this many frames: of 192,830 phones aligned in dev-clean, none is shorter. Fitted with no
#: such floor, a stretch hopped through a word's sounds a frame at a time on whatever fit.
SHORTEST = int(os.environ.get("SHORTEST", 3))


def chained(sequence, index):
    """A word's phones as the states a stretch passes through, each phone `SHORTEST` states long: `(phone of each
    state, whether a state may be stayed in)`. Only a phone's last state may be stayed in."""
    phone_of, stays = [], []
    for p in sequence:
        phone_of += [index[p]] * SHORTEST
        stays += [False] * (SHORTEST - 1) + [True]
    return phone_of, stays


def plain(phone: str) -> str:
    """A phone without its stress mark: "AH0" and "AH1" are one sound to tell apart from the others."""
    return phone.rstrip("012")


def energies(y) -> np.ndarray:
    """Log energy in each of the ear's 26 speech bands, every 10 ms."""
    from core.perception import speech as SP
    padded = np.pad(np.asarray(y, dtype=np.float64), (SP._NFFT // 2, SP._NFFT // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, SP._NFFT)[::SP._HOP]
    power = np.abs(np.fft.rfft(frames * np.hanning(SP._NFFT), axis=1)) ** 2
    return np.log(power @ SP._BANK.T + SP._EPS).astype(np.float32)


def measured(bands: np.ndarray, reach: int = REACH) -> np.ndarray:
    """Each frame as it is compared: its band energies less the channel, their change, and the same of four frames
    around it, out to `reach` frames either side (a sound is known by how it is come to and left)."""
    from core.perception import speech as SP
    if CHANNEL == "rasta":
        # RASTA (Hermansky and Morgan 1994): each band's log energy over time, band-pass filtered. What stays
        # still (a microphone's colour, a room) is removed with no speech around the word needed to find it.
        from scipy.signal import lfilter
        x = lfilter([0.2, 0.1, 0.0, -0.1, -0.2], [1.0, -0.94], bands, axis=0).astype(np.float32)
    else:
        x = bands - SP._running_mean(bands)
    x = np.concatenate([x, np.gradient(x, axis=0)], axis=1)
    pad = np.pad(x, ((reach, reach), (0, 0)), mode="edge")
    step = max(reach // 2, 1)
    return np.concatenate([pad[k:k + len(x)] for k in range(0, 2 * reach + 1, step)], axis=1).astype(np.float32)


def utterances(split: str, every: int = 1):
    """`(speaker, band energies, each frame's phone, the row's words)` for a LibriSpeech split, measured once and
    kept in `work/`. A frame's phone is "sil" where nothing is said and "" where the aligner knew no word."""
    import pyarrow.parquet as pq
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import speech as SP
    cache = WORK / f"utterances_{split}_{every}.npz"
    if cache.exists():
        held = np.load(cache, allow_pickle=True)
        return list(zip(held["speaker"], held["bands"], held["phones"], held["words"]))
    WORK.mkdir(exist_ok=True)
    table = pq.read_table(ALIGNED / f"{split}.parquet", columns=["id", "words", "phonemes", "audio"])
    out = []
    for k, row in enumerate(table.to_pylist()):
        if k % every:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        bands = energies(resample_poly(y, H.SR, rate) if rate != H.SR else y)
        phones = np.array(["sil"] * len(bands), dtype=object)
        for p in row["phonemes"]:
            lo, hi = int(np.ceil(p["start"] * H.SR / SP._HOP)), int(p["end"] * H.SR / SP._HOP)
            phones[lo:hi + 1] = "" if p["phoneme"] == "spn" else plain(p["phoneme"])
        words = [(w["word"], int(w["start"] * H.SR / SP._HOP), int(np.ceil(w["end"] * H.SR / SP._HOP)))
                 for w in row["words"]]
        out.append((row["id"].split("-")[0], bands, phones, words))
    np.savez(cache, speaker=np.array([o[0] for o in out], dtype=object),
             bands=np.array([o[1] for o in out], dtype=object), phones=np.array([o[2] for o in out], dtype=object),
             words=np.array([o[3] for o in out], dtype=object))
    return out


class Taught:
    """The frames taught, each with its phone, and what a heard frame sounds like beside them."""

    def __init__(self, splits: str = TEACH, seed: int = 20261003):
        rng = np.random.default_rng(seed)
        kept, names, seen = [], [], Counter()
        for speaker, bands, phones, _ in (u for split in splits.split(",") for u in utterances(split)):
            frames = measured(bands)
            for phone in sorted(set(phones) - {""}):      # in one order, so every run teaches the same frames
                at = np.flatnonzero(phones == phone)
                for i in rng.choice(at, size=min(len(at), PER_UTTERANCE), replace=False):
                    if seen[(speaker, phone)] < PER_SPEAKER:
                        seen[(speaker, phone)] += 1
                        kept.append(frames[i])
                        names.append(phone)
        self.frames = np.array(kept, dtype=np.float32)
        self.phones = sorted(set(names))
        self.index = {p: i for i, p in enumerate(self.phones)}
        self.phone_of = np.array([self.index[p] for p in names])
        self._squares = (self.frames ** 2).sum(axis=1)
        self.speakers = len({s for s, _ in seen})

    def sounds_like(self, frames: np.ndarray) -> np.ndarray:
        """For each heard frame, the log of the share of its nearest taught frames each phone holds, with half a
        frame for every phone so none is impossible."""
        out = np.zeros((len(frames), len(self.phones)), dtype=np.float32)
        for lo in range(0, len(frames), 256):
            q = frames[lo:lo + 256]
            d = (q ** 2).sum(axis=1)[:, None] + self._squares[None, :] - 2.0 * q @ self.frames.T
            near = self.phone_of[np.argpartition(d, NEAREST, axis=1)[:, :NEAREST]]
            np.add.at(out, (np.arange(lo, lo + len(q))[:, None], near), 1.0)
        return np.log((out + 0.5) / (NEAREST + 0.5 * len(self.phones)))

    def align(self, logp: np.ndarray, sequence):
        """Which of a word's phones each frame of a stretch is, by the best fit (`fit`), with quiet allowed before
        and after: a list as long as the stretch, "sil" for quiet. None when the stretch cannot hold the word."""
        if len(logp) < SHORTEST * len(sequence) or any(p not in self.index for p in sequence):
            return None
        inner, inner_stays = chained(sequence, self.index)
        states = np.array([self.index["sil"]] + inner + [self.index["sil"]])
        stays = np.array([True] + inner_stays + [True])
        n = len(states)
        best = np.full(n, -np.inf)
        best[0], best[1] = logp[0, states[0]], logp[0, states[1]]
        came = np.zeros((len(logp), n), dtype=np.int32)
        came[0] = np.arange(n)
        for t in range(1, len(logp)):
            stay = np.where(stays, best, -np.inf)
            move = np.concatenate([[-np.inf], best[:-1]])
            came[t] = np.where(move > stay, np.arange(n) - 1, np.arange(n))
            best = np.maximum(stay, move) + logp[t, states]
        state = n - 1 if best[-1] >= best[-2] else n - 2
        path = [state]
        for t in range(len(logp) - 1, 0, -1):
            state = came[t, state]
            path.append(state)
        return [self.phones[states[k]] for k in path[::-1]]

    def add(self, frames: np.ndarray, phones) -> None:
        """More taught frames, each with its phone."""
        self.frames = np.concatenate([self.frames, np.asarray(frames, dtype=np.float32)])
        self.phone_of = np.concatenate([self.phone_of, [self.index[p] for p in phones]])
        self._squares = (self.frames ** 2).sum(axis=1)

    def fit(self, logp: np.ndarray, sequence) -> float:
        """How well a stretch fits a word's phones in order: the best way of giving each phone some of the frames,
        quiet allowed before and after. The sum over the stretch's frames, so every word is weighed on the same
        frames."""
        if len(logp) < SHORTEST * len(sequence) or any(p not in self.index for p in sequence):
            return -np.inf
        inner, inner_stays = chained(sequence, self.index)
        states = np.array([self.index["sil"]] + inner + [self.index["sil"]])
        stays = np.array([True] + inner_stays + [True])
        best = np.full(len(states), -np.inf)
        best[0], best[1] = logp[0, states[0]], logp[0, states[1]]
        for t in range(1, len(logp)):
            best = np.maximum(np.where(stays, best, -np.inf), np.concatenate([[-np.inf], best[:-1]])) \
                + logp[t, states]
        return float(max(best[-1], best[-2]))
