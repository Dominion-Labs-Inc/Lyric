#!/usr/bin/env python3
"""Hearing music: the beat and its tempo, the key, and the notes of a melody,
measured from the waveform by classical methods, with no learned model.

The ear's reading of music, beside `hearing` (the sounds in a recording) and
`speech` (the words said in it). Everything here is MEASURED:

  the beat     -- where the music's onsets recur, by the autocorrelation of
                  how much new sound starts at each moment, and the beats
                  themselves by dynamic programming over those onsets (Ellis,
                  "Beat tracking by dynamic programming", 2007);
  the key      -- how the music's energy falls on the twelve pitch classes
                  (a harmonic pitch-class profile, Gomez 2006), correlated
                  with the probe-tone profiles of the 24 keys (Krumhansl and
                  Kessler 1982; the key-finding algorithm of Krumhansl and
                  Schmuckler);
  the notes    -- where a single line of melody holds a pitch, from hearing's
                  own pitch path.

The NAMES are given, the way hue names and registers are given: note names on
equal temperament from A4 = 440 Hz, tempo in beats per minute, the 24 major and
minor keys. What a piece of music IS -- a song, which song -- is not named
here: a known song is recognised by hearing it again (`hearing.landmarks`).

Pure functions over samples at `hearing.SR`. No substrate imports.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import hearing
from .hearing import FRAME, HOP, SR, _EPS

#: Frames of the onset envelope per second (hearing's hop).
_RATE = SR / HOP

# --- how much new sound starts at each moment ----------------------------------

_ONSET_BANDS = 40
_ONSET_BANK = hearing._mel_bank(_ONSET_BANDS, FRAME)
_ONSET_RANGE_DB = 80.0
#: The envelope is smoothed over about 20 ms, as Ellis does: onsets within a
#: frame or two of each other are one onset.
_ONSET_SMOOTH_SECONDS = 0.02


def onset_strength(y: np.ndarray) -> np.ndarray:
    """How much NEW sound starts at each hop: the rise of the log mel spectrum
    from one hop to the next, half-wave rectified and averaged over the bands
    (a note starting raises many bands at once; a note sustaining raises none),
    with its slow drift removed and smoothed over 20 ms. Normalised to unit
    standard deviation, so how loud the recording is does not matter."""
    frames = hearing._frames(y, FRAME)
    window = np.hanning(FRAME)
    bands = np.empty((len(frames), _ONSET_BANDS))
    for i in range(0, len(frames), 4096):
        chunk = frames[i:i + 4096]
        power = np.abs(np.fft.rfft(chunk * window, axis=1)) ** 2
        bands[i:i + len(chunk)] = 10.0 * np.log10(power @ _ONSET_BANK.T + _EPS)
    if not len(bands):
        return np.zeros(0)
    bands = np.maximum(bands, bands.max() - _ONSET_RANGE_DB)
    rise = np.maximum(0.0, np.diff(bands, axis=0)).mean(axis=1)
    rise = np.concatenate([[0.0], rise])
    # The slow drift of the envelope is removed with a one-pole high-pass
    # (Ellis's filter, [1 -1] / [1 -0.99]): what matters is where onsets stand
    # out from the level around them, not the level.
    from scipy.signal import lfilter
    rise = lfilter([1.0, -1.0], [1.0, -0.99], rise)
    width = max(1, int(round(_ONSET_SMOOTH_SECONDS * _RATE)))
    taps = np.exp(-0.5 * (np.arange(-2 * width, 2 * width + 1) / width) ** 2)
    rise = np.convolve(rise, taps / taps.sum(), mode="same")
    spread = float(rise.std())
    return rise / spread if spread > _EPS else rise * 0.0


# --- the tempo ------------------------------------------------------------------

#: Which beat periods a listener hears as THE beat, when the onsets recur at
#: several: a Gaussian on a log-time axis centred on 0.5 s (120 beats a
#: minute), 1.4 octaves wide (Ellis 2007, from listeners' tempo judgements).
_TEMPO_CENTRE_SECONDS = 0.5
_TEMPO_SPREAD_OCTAVES = 1.4
_LONGEST_PERIOD_SECONDS = 4.0
_SHORTEST_PERIOD_SECONDS = 60.0 / 320.0


def _periodicity(env: np.ndarray) -> np.ndarray:
    """The onset envelope's autocorrelation at every lag up to the longest beat
    period, unbiased (each lag divided by how many products it sums)."""
    n = len(env)
    most = min(n - 1, int(_LONGEST_PERIOD_SECONDS * _RATE) * 3 + 2)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    spectrum = np.fft.rfft(env - env.mean(), size)
    ac = np.fft.irfft(np.abs(spectrum) ** 2, size)[:most + 1]
    return ac / np.maximum(n - np.arange(most + 1), 1)


def _peak(values: np.ndarray, at: int) -> float:
    """Where a peak at index `at` really lies, by a parabola through it and its
    neighbours (the lag grid is 2.3% of a 120 bpm beat; the tempo is judged
    within 4%)."""
    if 0 < at < len(values) - 1:
        a, b, c = values[at - 1], values[at], values[at + 1]
        den = a - 2 * b + c
        if abs(den) > _EPS:
            shift = 0.5 * (a - c) / den
            if abs(shift) <= 1.0:
                return at + shift
    return float(at)


def tempo(env: np.ndarray) -> Dict[str, Any]:
    """The tempo the onsets recur at, in beats per minute, as a listener would
    tap it (Ellis 2007): the peak of the onsets' periodicity, weighted by the
    perceptual preference for beats near 0.5 s.

    WHICH LEVEL OF THE BEAT. Music recurs at the beat and at its multiples, and
    listeners tap one of them. Ellis also reads each lag together with its
    double and triple, which finds the beat's family more often and its level
    less often: measured on GTZAN's 998 annotated clips, the plain peak named
    the tapped tempo within 4% on 63.5% of the clips it was chosen on and
    64.0% of the half kept apart to confirm it, the combined reading on 59%.

    Returns `bpm`, `period` (seconds), `strength` (how much of the onsets'
    variation recurs at that period, 0..1), and `rival_bpm` with
    `rival_share`: the tempo at the strongest other peak and how strong it is
    beside the chosen one. The tempo tapped was the rival instead in a fifth
    of those clips; which of the two levels is THE beat is a fact about the
    music and its listeners, reported rather than decided."""
    if len(env) < int(4 * _TEMPO_CENTRE_SECONDS * _RATE):
        return {"bpm": None}
    ac = _periodicity(env)
    lags = np.arange(len(ac))
    weight = np.zeros(len(ac))
    positive = lags > 0
    weight[positive] = np.exp(-0.5 * (np.log2(lags[positive] / (_TEMPO_CENTRE_SECONDS * _RATE))
                                      / _TEMPO_SPREAD_OCTAVES) ** 2)
    tps = weight * np.maximum(ac, 0.0)
    lo = int(_SHORTEST_PERIOD_SECONDS * _RATE)
    hi = min(int(_LONGEST_PERIOD_SECONDS * _RATE), len(tps) - 1)
    if hi <= lo + 2:
        return {"bpm": None}
    curve = tps[lo:hi]
    best = int(np.argmax(curve))
    if curve[best] <= 0:
        return {"bpm": None}
    period = (lo + _peak(curve, best)) / _RATE
    # The rival: the strongest other peak, at least a fifth of an octave away
    # (a peak's own shoulder is not a rival).
    peaks = [j for j in range(1, len(curve) - 1)
             if curve[j] >= curve[j - 1] and curve[j] >= curve[j + 1]
             and abs(math.log2((lo + j) / (lo + best))) > 0.2]
    rival = max(peaks, key=lambda j: curve[j]) if peaks else None
    energy = float(ac[0]) if ac[0] > _EPS else 1.0
    return {
        "bpm": round(float(60.0 / period), 1),
        "period": round(float(period), 4),
        "strength": round(float(max(0.0, ac[int(round(period * _RATE))]) / energy), 3),
        "rival_bpm": None if rival is None else round(float(60.0 * _RATE / (lo + _peak(curve, rival))), 1),
        "rival_share": None if rival is None else round(float(curve[rival] / curve[best]), 3),
    }


#: How strongly the beats keep to the tempo against following the onsets
#: (Ellis 2007, alpha).
_TIGHTNESS = 680.0


def beats(env: np.ndarray, period: float) -> np.ndarray:
    """The beat times, in seconds, at a given beat period: the sequence of
    moments that both falls on strong onsets and keeps an even pace, found as
    the best such sequence by dynamic programming (Ellis 2007). Each beat's
    score is its onset strength plus the best score of a previous beat, less
    the cost of the gap between them straying from the period, which is
    -(log(gap / period))^2 weighted by the tightness."""
    n = len(env)
    p = period * _RATE
    if n < 2 or p < 2:
        return np.zeros(0)
    score = env.astype(np.float64).copy()
    back = -np.ones(n, dtype=int)
    reach = np.arange(-int(round(2 * p)), -int(round(p / 2)) + 1)
    penalty = -_TIGHTNESS * np.log(-reach / p) ** 2
    for t in range(n):
        prev = t + reach
        ok = prev >= 0
        if not ok.any():
            continue
        cand = score[prev[ok]] + penalty[ok]
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[t] = env[t] + cand[j]
            back[t] = int(prev[ok][j])
    # The last beat is the best-scoring moment within the final period.
    tail = np.arange(max(0, n - int(round(p))), n)
    t = int(tail[np.argmax(score[tail])])
    out = [t]
    while back[t] >= 0:
        t = int(back[t])
        out.append(t)
    return np.array(out[::-1], dtype=np.float64) / _RATE


# --- the key --------------------------------------------------------------------

#: The pitch classes, from A, as note names are given.
PITCH_CLASSES = ("A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#")

#: A frame long enough to tell semitones apart at the bottom of the range
#: (a semitone at 55 Hz is 3.3 Hz; this frame's bins are 2.7 Hz).
_CHROMA_FRAME = 8192
_CHROMA_HOP = 4096
_CHROMA_FMIN, _CHROMA_FMAX = 50.0, 5000.0
_PEAK_RANGE_DB = 60.0
#: Harmonic weighting (Gomez 2006): a spectral peak is also counted as the
#: h-th harmonic of the note an octave-and-more below it, h = 1..8, with
#: weight 0.6^(h-1), so the notes a chord's overtones belong to gather its
#: energy. A peak's energy spreads over pitch classes within 2/3 of a
#: semitone of it, by a squared cosine.
_HARMONICS = 8
_HARMONIC_DECAY = 0.6
_SPREAD_SEMITONES = 2.0 / 3.0


def _spectral_peaks(y: np.ndarray):
    """Each frame's spectral peaks within the chroma range, as (frame,
    frequency, energy) arrays, each peak's frequency refined by a parabola
    through the log magnitudes around it."""
    n = len(y)
    if n < _CHROMA_FRAME:
        y = np.pad(y, (0, _CHROMA_FRAME - n))
    view = np.lib.stride_tricks.sliding_window_view(y, _CHROMA_FRAME)[::_CHROMA_HOP]
    window = np.hanning(_CHROMA_FRAME)
    freqs = np.fft.rfftfreq(_CHROMA_FRAME, 1.0 / SR)
    lo, hi = np.searchsorted(freqs, _CHROMA_FMIN), np.searchsorted(freqs, _CHROMA_FMAX)
    frames, where, energy = [], [], []
    for i in range(0, len(view), 256):
        mag = np.abs(np.fft.rfft(view[i:i + 256] * window, axis=1))
        db = 20.0 * np.log10(mag + _EPS)
        top = db.max(axis=1, keepdims=True)
        mid = db[:, lo:hi]
        is_peak = ((mid > db[:, lo - 1:hi - 1]) & (mid >= db[:, lo + 1:hi + 1])
                   & (mid > top - _PEAK_RANGE_DB))
        f_idx, b_idx = np.nonzero(is_peak)
        b = b_idx + lo
        a, c, m = db[f_idx, b - 1], db[f_idx, b + 1], db[f_idx, b]
        den = a - 2 * m + c
        shift = np.where(np.abs(den) > _EPS, 0.5 * (a - c) / np.where(np.abs(den) > _EPS, den, 1.0), 0.0)
        shift = np.clip(shift, -0.5, 0.5)
        frames.append(f_idx + i)
        where.append((b + shift) * SR / _CHROMA_FRAME)
        energy.append(mag[f_idx, b] ** 2)
    if not frames:
        return np.zeros(0, int), np.zeros(0), np.zeros(0)
    return np.concatenate(frames), np.concatenate(where), np.concatenate(energy)


def tuning(freqs: np.ndarray, energy: np.ndarray) -> float:
    """How far, in semitones (-0.5..0.5), the recording's pitches sit from
    equal temperament at A4 = 440 Hz: the energy-weighted circular mean of
    every spectral peak's offset from its nearest semitone. A band tuned to
    A = 446 Hz reads +0.23."""
    if not len(freqs):
        return 0.0
    offset = 12.0 * np.log2(freqs / 440.0)
    angle = 2 * np.pi * (offset - np.round(offset))
    w = np.sqrt(energy)
    return float(np.angle(np.sum(w * np.exp(1j * angle))) / (2 * np.pi))


def chroma(y: np.ndarray) -> Tuple[np.ndarray, float]:
    """The recording's harmonic pitch-class profile: how its tonal energy falls
    on the twelve pitch classes (A, A#, ... G#), summed over the whole
    recording with each frame normalised to its own strongest class, so a loud
    chorus does not outweigh the verse. And the tuning it was read against."""
    fr, freqs, energy = _spectral_peaks(y)
    if not len(fr):
        return np.zeros(12), 0.0
    tune = tuning(freqs, energy)
    frames = int(fr.max()) + 1
    profile = np.zeros((frames, 12))
    for h in range(1, _HARMONICS + 1):
        f0 = freqs / h
        keep = f0 >= _CHROMA_FMIN / 2
        if not keep.any():
            continue
        semis = 12.0 * np.log2(f0[keep] / 440.0) - tune
        w = energy[keep] * _HARMONIC_DECAY ** (h - 1)
        for step in (-1, 0, 1):
            cls = np.round(semis) + step
            d = np.abs(semis - cls)
            near = d < _SPREAD_SEMITONES
            contribution = w[near] * np.cos(0.5 * np.pi * d[near] / _SPREAD_SEMITONES) ** 2
            np.add.at(profile, (fr[keep][near], (cls[near].astype(int)) % 12), contribution)
    top = profile.max(axis=1, keepdims=True)
    heard = top[:, 0] > 0
    profile = profile[heard] / top[heard]
    return (profile.sum(axis=0) if len(profile) else np.zeros(12)), tune


#: The probe-tone profiles of Krumhansl and Kessler (1982): how well each of
#: the twelve pitch classes, from the tonic up, was heard to fit a major or a
#: minor key.
KK_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def key(profile: np.ndarray, major: np.ndarray = KK_MAJOR,
        minor: np.ndarray = KK_MINOR) -> Dict[str, Any]:
    """The key a pitch-class profile is in: the one of the 24 keys whose
    profile, turned to that tonic, it correlates with best (Krumhansl-
    Schmuckler). Returns `tonic` (a pitch class name), `mode` ("major" or
    "minor"), `r` (that correlation), and `runner_up` with `margin`: the next
    best key and how far behind it is."""
    if not np.any(profile > 0):
        return {"tonic": None}
    scores: List[Tuple[float, str, str]] = []
    for mode, shape in (("major", major), ("minor", minor)):
        for tonic in range(12):
            r = float(np.corrcoef(profile, np.roll(shape, tonic))[0, 1])
            scores.append((r, PITCH_CLASSES[tonic], mode))
    scores.sort(reverse=True)
    (r, tonic, mode), (r2, tonic2, mode2) = scores[0], scores[1]
    return {"tonic": tonic, "mode": mode, "r": round(r, 3),
            "runner_up": f"{tonic2} {mode2}", "margin": round(r - r2, 3)}


# --- the notes of a melody ------------------------------------------------------

#: How far a held note's pitch wanders about its note, in semitones: vibrato,
#: a scoop into it, drift.
_NOTE_SPREAD = 0.7
#: The most one frame's misfit counts against a note, so a frame whose pitch
#: slipped an octave (onto a harmonic) cannot on its own make a note.
_NOTE_MISFIT_CAP = 4.5
#: The cost of changing note, in frames of a one-semitone misfit: a change of
#: a semitone must be heard for about five frames (58 ms) to be a new note.
_NOTE_CHANGE = 5.0
#: A note is at least this long; a shorter run of one note joins its neighbour.
_SHORTEST_NOTE = 0.05
#: Unvoiced gaps this short, inside a sung stretch, are the pitch reading
#: dropping out for a frame, not the singer stopping.
_DROPOUT_FRAMES = 2


def midi(f0: np.ndarray) -> np.ndarray:
    """Frequency in Hz as a MIDI note number (A4 = 440 Hz = 69); 0 stays 0."""
    out = np.zeros(len(f0))
    ok = f0 > 0
    out[ok] = 69.0 + 12.0 * np.log2(f0[ok] / 440.0)
    return out


def note_name(m: float) -> str:
    """The name of the nearest equal-tempered note, with its octave (C4 is
    middle C): 69 -> "A4"."""
    k = int(round(m))
    return f"{PITCH_CLASSES[(k - 69) % 12]}{k // 12 - 1}"


def pitch_track(y: np.ndarray) -> Dict[str, Any]:
    """Hearing's pitch at every hop, over the sounds in the recording: `f0`
    (Hz, 0 where no pitch), `periodic` (1 - aperiodicity), and the sounds'
    spans. The path is hearing's own (`hearing.yin`), chosen over each sound."""
    levels = hearing._levels(y)
    spans, _ground = hearing.segment(levels)
    frames = hearing._frames(y, hearing.PITCH_FRAME)
    f0 = np.zeros(len(levels))
    periodic = np.zeros(len(levels))
    for s, e in spans:
        e = min(e, len(frames) - 1)
        if e < s:
            continue
        f, ap = hearing.yin(frames[s:e + 1])
        f0[s:e + 1] = f
        periodic[s:e + 1] = np.clip(1.0 - ap, 0.0, 1.0)
    return {"f0": f0, "periodic": periodic, "spans": spans}


def _decode_notes(m: np.ndarray, known: np.ndarray, tune: float) -> np.ndarray:
    """The held note (as a MIDI number on the recording's own tuning) at every
    frame of one sung stretch: the sequence of notes that best explains the
    pitch heard, where every frame's distance from its note costs and every
    change of note costs `_NOTE_CHANGE` (Viterbi). Frames with no pitch
    (`known` False) cost nothing whatever note they are given."""
    lo = int(np.floor(m[known].min() - tune)) - 1
    hi = int(np.ceil(m[known].max() - tune)) + 1
    states = np.arange(lo, hi + 1) + tune
    misfit = np.minimum(((m[:, None] - states[None, :]) ** 2) / (2 * _NOTE_SPREAD ** 2),
                        _NOTE_MISFIT_CAP)
    misfit[~known] = 0.0
    n, k = misfit.shape
    cost = misfit[0].copy()
    back = np.zeros((n, k), dtype=int)
    for t in range(1, n):
        stay = cost
        best = int(np.argmin(cost))
        move = cost[best] + _NOTE_CHANGE
        choose_move = move < stay
        back[t] = np.where(choose_move, best, np.arange(k))
        cost = np.where(choose_move, move, stay) + misfit[t]
    path = np.empty(n, dtype=int)
    path[-1] = int(np.argmin(cost))
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return states[path]


def notes(y: np.ndarray, track: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The notes of a single line of melody -- a voice, a whistle, one
    instrument -- where the recording holds a pitch.

    Returns `tuning` (semitones from A4 = 440 Hz, read from the pitches sung)
    and `notes`, each with `start` and `end` (seconds), `pitch` (Hz, the median
    of what was heard), `midi` (fractional), `name` (the nearest note, on
    equal temperament from A4 = 440 Hz) and `cents` (how far from that note)."""
    track = track or pitch_track(y)
    f0, periodic = track["f0"], track["periodic"]
    m = midi(f0)
    voiced = m > 0
    if voiced.sum() < 3:
        return {"tuning": 0.0, "notes": []}
    offset = m[voiced] - np.round(m[voiced])
    tune = float(np.angle(np.sum(periodic[voiced] * np.exp(2j * np.pi * offset))) / (2 * np.pi))
    # Sung stretches: voiced frames, joined across dropouts of a frame or two.
    idx = np.flatnonzero(voiced)
    runs: List[List[int]] = [[int(idx[0]), int(idx[0])]]
    for i in idx[1:]:
        if i - runs[-1][1] - 1 <= _DROPOUT_FRAMES:
            runs[-1][1] = int(i)
        else:
            runs.append([int(i), int(i)])
    shortest = max(1, int(round(_SHORTEST_NOTE * _RATE)))
    out: List[Dict[str, Any]] = []
    for s, e in runs:
        seg = m[s:e + 1]
        held = _decode_notes(seg, seg > 0, tune)
        # Runs of one held note are notes; one too short to be heard as a
        # note joins the neighbour nearer in pitch.
        bounds = [0] + [t for t in range(1, len(held)) if held[t] != held[t - 1]] + [len(held)]
        pieces = [[bounds[j], bounds[j + 1], held[bounds[j]]] for j in range(len(bounds) - 1)]
        merged = True
        while merged and len(pieces) > 1:
            merged = False
            for j, (a, b, note) in enumerate(pieces):
                if b - a >= shortest:
                    continue
                left = pieces[j - 1] if j > 0 else None
                right = pieces[j + 1] if j + 1 < len(pieces) else None
                into = min((p for p in (left, right) if p is not None),
                           key=lambda p: abs(p[2] - note))
                into[0], into[1] = min(into[0], a), max(into[1], b)
                del pieces[j]
                merged = True
                break
        for a, b, _note in pieces:
            if b - a < shortest:
                continue
            heard = seg[a:b][seg[a:b] > 0]
            if not len(heard):
                continue
            mid = float(np.median(heard))
            out.append({"start": round((s + a) * HOP / SR, 3),
                        "end": round((s + b) * HOP / SR, 3),
                        "pitch": round(440.0 * 2 ** ((mid - 69.0) / 12.0), 2),
                        "midi": round(mid, 2), "name": note_name(mid),
                        "cents": int(round(100 * (mid - round(mid))))})
    return {"tuning": round(tune, 3), "notes": out}


# --- a song heard before ---------------------------------------------------------

def song_example(y: np.ndarray, path: str) -> np.ndarray:
    """What a lesson about a song keeps, to know the song when it is heard
    again: its landmarks (`hearing.landmarks`), which recognise the same
    recording through gain, noise, a room and a codec. Raises when the
    recording has too few for a replay ever to reach the agreement a
    recognition needs."""
    marks = hearing.landmarks(y)
    distinct = hearing.distinct_landmarks(marks)
    if distinct < hearing.KNOWN_MIN_LANDMARKS:
        raise ValueError(f"{path} has {distinct} different landmark(s); a song is known "
                         f"again by at least {hearing.KNOWN_MIN_LANDMARKS}")
    return marks


#: A SONG IS KNOWN when this share of the landmarks heard, while the song
#: would have been playing, agree with it at one offset. A count alone cannot
#: be the cut: a song carries thousands of landmarks (GTZAN clips: 9,166 in 30
#: s at the median), so chance agreement grows with the song and with the
#: recording. Measured, 100 GTZAN clips taught and heard back as 6 s excerpts
#: played into a real room and through a 64 kbit/s codec: 0.30 at the least of
#: what was heard agreed with its own song, and no excerpt of 300 others ever
#: reached 0.029 with any taught song. The cut sits between; fully resolved at
#: twice it, as a known sound is.
SONG_MIN_SHARE = 0.1


def song_agreement(table, reference: np.ndarray, heard: np.ndarray) -> Tuple[int, Optional[float], float]:
    """How a taught song's landmarks (`reference`, looked up through `table`)
    line up in what was heard: the agreeing count, where the song's start fell
    in the recording (seconds; negative when it began before the recording),
    and the SHARE of the landmarks heard during the stretch the song overlaps
    that agree with it."""
    count, at = hearing.agreement(table, heard)
    if at is None or not len(heard):
        return 0, None, 0.0
    start = at * SR / HOP
    stop = start + float(reference[:, 3].max() if len(reference) else 0)
    inside = int(np.sum((heard[:, 3] >= start - 2) & (heard[:, 3] <= stop + 2)))
    return int(count), at, (count / inside if inside else 0.0)


def resolve_song(share: float) -> float:
    """How far past the cut a song's recognition sits: a coin flip exactly at
    `SONG_MIN_SHARE`, fully resolved at twice it."""
    return round(max(0.0, min(1.0, share / SONG_MIN_SHARE - 1.0)), 3)


# --- what is claimed of the music, and how firmly --------------------------------
#
# EACH CLAIM CARRIES THE SUPPORT ITS MEASUREMENT EARNED, set so that the belief
# it becomes (0.5 at no support, 0.9 at full, `quality_from_resolution`) is how
# often such a reading was right. Measured against people's annotations:
#
#   the key, by its fit (r) to the key profile -- exact key named, GTZAN 837
#   clips / GiantSteps 225 single-key tracks kept apart to confirm it:
#       r < 0.82       45% / 49%   -- a coin flip: no key is claimed
#       0.82 - 0.88    55% / 83%
#       0.88 - 0.93    76% / 77%
#       0.93 and over  88% / 80%
#   Speech fits some key at 0.7 (spoken digits, JFK), as any peaked profile
#   does, so a key is claimed only of music that fits one closely.
#
#   the tempo, by the strength of the beat -- tapped tempo named within 4%,
#   GTZAN 998 clips:
#       strength < 0.39     44%   -- no tempo is claimed below 0.35
#       0.39 - 0.54         64%
#       0.54 - 0.64         72%
#       0.64 and over       74%   -- the level of the beat is never surer
#   Speech has no beat to speak of (0 to 0.37).
_KEY_FROM, _KEY_FULL, _KEY_MOST = 0.82, 0.93, 0.95
_BEAT_FROM, _BEAT_FULL, _BEAT_MOST = 0.35, 0.60, 0.60

#: A MELODY IS HEARD where a single line holds its pitches at a singer's pace.
#:
#: A single line: most of what sounds is periodic. Half the sounding frames of
#: every one of 40 solo voices (vocadito) were 0.92 periodic or more; of full
#: mixes, 0.64 at the median (GTZAN, 199 clips). Of a mix, notes would be
#: whichever part is loudest, so none are read.
#:
#: Held pitches at a singer's pace: songs are slower than speech and hold their
#: pitch more steadily (Ozaki et al., Science Advances 2024, song and speech in
#: 75 languages). Measured, the pitch moving within a note, and notes a second:
#:                      cents a second      notes a second
#:   solo singing       775 median, 1105 p90    4.1 median, 5.4 p90
#:   read speech        1533 median, 1206 p10   7.5 median, 6.0 p10
#: (LibriSpeech dev-clean, the 71 of 600 utterances a single line). Cut half way
#: between, 37 of 40 sung recordings are heard as melody and 2 of 600 spoken
#: ones. Each margin is fully resolved at the singers' median, and the
#: melody is as sure as its weakest: sung recordings came out at 0.90 at the
#: median and a quarter below 0.37 (fast, gliding singing, as quick and as
#: moving as speech), the two spoken ones at 0.20 and 0.21.
_ONE_LINE, _ONE_LINE_FULL = 0.9, 0.97
_HELD_CENTS, _HELD_CENTS_FULL = 1150.0, 775.0
_SUNG_RATE, _SUNG_RATE_FULL = 5.7, 4.1
#: The pitch's movement within a note, not a leap between two.
_WITHIN_NOTE = 1.0


def _ramp(value: float, lo: float, hi: float, most: float) -> float:
    return round(most * max(0.0, min(1.0, (value - lo) / (hi - lo))), 3)


def key_name(tonic: str, mode: str) -> str:
    """A key as it is said: "F# minor" -> "F-sharp minor"."""
    return f"{tonic.replace('#', '-sharp')} {mode}"


def describe(y: np.ndarray) -> Dict[str, Any]:
    """Everything this module measures of one recording, and what it claims.

    `tempo`, `beats` (seconds), `key` and `tuning` are the measurements, kept
    whole. `claims` holds what is stated, each with its support: `in_key`
    (the key, as said) when the music fits one closely, `tempo` (bpm) when the
    beat is strong enough to name its level, `melody` (its notes) when a single
    line is heard. What is not claimed is still measured, and stays here."""
    env = onset_strength(y)
    beat = tempo(env)
    profile, tune = chroma(y)
    found = key(profile)
    track = pitch_track(y)
    levels = hearing._levels(y)
    sounding = np.zeros(len(levels), bool)
    for s, e in track["spans"]:
        sounding[s:e + 1] = True
    periodic = float(np.median(track["periodic"][sounding])) if sounding.any() else 0.0
    out: Dict[str, Any] = {
        "tempo": beat, "key": found, "tuning": round(tune, 3),
        "beats": ([] if not beat.get("period") else
                  [round(float(b), 3) for b in beats(env, beat["period"])]),
        "one_line": round(periodic, 3),
    }
    claims: Dict[str, Any] = {}
    if found.get("tonic"):
        support = _ramp(found["r"], _KEY_FROM, _KEY_FULL, _KEY_MOST)
        if support > 0:
            claims["in_key"] = {"key": key_name(found["tonic"], found["mode"]),
                                "support": support}
    if beat.get("bpm"):
        support = _ramp(beat["strength"], _BEAT_FROM, _BEAT_FULL, _BEAT_MOST)
        if support > 0:
            claims["tempo"] = {"bpm": beat["bpm"], "rival_bpm": beat.get("rival_bpm"),
                               "support": support}
    if periodic >= _ONE_LINE:
        melody = notes(y, track)
        m = midi(track["f0"])
        voiced = m > 0
        both = voiced[1:] & voiced[:-1]
        steps = np.abs(np.diff(m))[both]
        steps = steps[steps < _WITHIN_NOTE]
        cents = float(np.median(steps) * 100 * _RATE) if len(steps) else math.inf
        rate = len(melody["notes"]) / max(voiced.sum() / _RATE, 1e-6)
        out["line"] = {"periodic": round(periodic, 3), "cents_a_second": round(float(cents), 1),
                       "notes_a_second": round(float(rate), 2)}
        if melody["notes"] and cents < _HELD_CENTS and rate < _SUNG_RATE:
            support = min(
                (periodic - _ONE_LINE) / (_ONE_LINE_FULL - _ONE_LINE),
                (_HELD_CENTS - cents) / (_HELD_CENTS - _HELD_CENTS_FULL),
                (_SUNG_RATE - rate) / (_SUNG_RATE - _SUNG_RATE_FULL))
            claims["melody"] = {"notes": melody["notes"], "tuning": melody["tuning"],
                                "support": round(float(max(0.0, min(1.0, support))), 3)}
    out["claims"] = claims
    return out
