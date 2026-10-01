#!/usr/bin/env python3
"""Deterministic hearing: read the structure that is really in a sound, with no
learned model anywhere in the loop.

The ear's counterpart of `vision`. Every value returned here is MEASURED from the
waveform by a classical algorithm -- the recording's quiet ground, the sounds that
rise above it, each sound's pitch (YIN), how much of it is pitched, how abruptly
it starts, its level and length, how the sounds stand to one another in time,
pitch and loudness, and the spectral-peak landmarks a known sound is recognised
by. Nothing here names a novel sound; what a sound IS is the substrate's to
learn, downstream, exactly as it learns what a shape is.

Decoding goes through ffmpeg, so every format it reads -- wav, aiff, flac, mp3,
aac/m4a, ogg/opus, and the soundtrack of a video -- is heard by the same code.

Pure functions over a file path. No substrate imports, so it can be tested and
reasoned about on its own.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

#: The rate every sound is analysed at. Content up to 11 kHz covers pitch,
#: speech and the landmarks a known sound is recognised by; the file's own rate
#: is still reported, as a fact about the recording.
SR = 22050
FRAME = 1024                 # 46 ms spectral frame
HOP = 256                    # 11.6 ms between frames
PITCH_FRAME = 1024           # two periods of a 50 Hz note
_EPS = 1e-10

#: Bounded listening. A long recording is heard for this long and the percept
#: says so (`heard_seconds` beside `lasts`), the way a video is seek-sampled:
#: the cost is the same for a ten-minute and a ten-hour file, and nothing claims
#: to have heard what it did not.
MAX_SECONDS = 600.0

# --- the ground and the sounds on it ------------------------------------------

#: Below this a frame carries no signal at all. 16-bit audio cannot represent
#: anything quieter than -96 dBFS, so a frame this quiet is digital silence --
#: the absence of a recording, not the room it was made in.
_SIGNAL_DB = -90.0
#: A recording whose loudest moment is quieter than this holds nothing audible.
_AUDIBLE_DB = -60.0
#: A sound is what rises this far above the ground, and it lasts while it stays
#: this far above it (hysteresis, so one sound is not chopped by its own flutter).
_RISE_DB = 12.0
_HOLD_DB = 6.0
#: Two stretches closer than this are one sound: shorter gaps are the dips
#: inside a word or a note, not silence between two things.
_MERGE_GAP = 0.08
_MIN_SOUND = 0.03
#: A sound is heard CLEARLY when it stands this far above its ground; the
#: support of every claim about it scales with how far it does.
_CLEAR_DB = 30.0

# --- naming measured structure --------------------------------------------------

#: A frame is periodic (it has a pitch) when YIN's aperiodicity is below this.
_PERIODIC_AP = 0.3
#: A sound is PITCHED when most of its energy is periodic. Its share moved by
#: at most 0.04 in 95% of sounds under gain, padding and codec, so it is fully
#: resolved a tenth from the cut, or at twice its standard error over the frames
#: it was read over, whichever is wider (a sound seven frames long is not
#: resolved anywhere near the cut).
_PITCHED_SHARE = 0.5
_PITCHED_RESOLUTION = 0.1
#: The registers, cut at middle C (C4) and two octaves above it (C6). Given, the
#: way hue names are given: the bass clef ends at middle C, and a whistle, a
#: beep or a bird sits above C6.
_REGISTERS: Tuple[Tuple[float, str], ...] = (
    (261.63, "low_pitched"), (1046.5, "mid_pitched"), (math.inf, "high_pitched"))
#: How far from a register's edge, in octaves, a pitch must sit to be fully
#: resolved. Pitch moved by at most 0.03 octave under gain, padding, codec,
#: reverb and telephone band; an OCTAVE error is a different failure, which a
#: margin cannot see because it lands in the middle of the wrong register.
_PITCH_RESOLUTION = 0.1
#: A sound that reaches its level within this long starts abruptly (a strike, a
#: click, a plucked string); slower is a gradual onset (a swell, a blown note).
_ABRUPT_SECONDS = 0.05
#: How far from the cut, in octaves of time, an attack is fully resolved: the
#: most an attack moved under gain, padding and codec was 1.31 octaves (a
#: speech onset whose neighbour's boundary moved), so 1.35.
_ONSET_RESOLUTION = 1.35

# --- relations ------------------------------------------------------------------

#: One sound is `louder_than` another by at least this, fully resolved at twice it.
_LOUDER_DB = 6.0
#: One pitched sound is `higher_than` another by at least this many semitones.
_HIGHER_SEMITONES = 2.0


def _margin(value: float, cut: float, resolution: float) -> float:
    return round(min(1.0, abs(value - cut) / resolution), 3)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


# --- reading the file ---------------------------------------------------------

def probe(path: str) -> Dict[str, Any]:
    """Container facts from ffprobe: format, codec, rate, channels, duration, and
    whether the file has a sound track at all.

    EMPTY WHEN FFPROBE CANNOT READ THE FILE, which is not the same answer as "a
    file with no sound track". A readable video with no audio stream says
    `has_audio: False`; a file ffprobe cannot open says nothing, and `describe`
    raises on it rather than reporting it as silent."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=60)
        meta = json.loads(out.stdout or "{}")
    except Exception:
        return {}
    if out.returncode != 0 or not (meta.get("streams") or meta.get("format")):
        return {}
    audio = next((s for s in meta.get("streams", [])
                  if s.get("codec_type") == "audio"), None)
    fmt = str((meta.get("format") or {}).get("format_name") or "").split(",")[0]
    info: Dict[str, Any] = {"has_audio": audio is not None}
    if fmt:
        info["format"] = fmt.lower()
    duration = (audio or {}).get("duration") or (meta.get("format") or {}).get("duration")
    if duration:
        info["duration"] = round(float(duration), 3)
    if audio:
        if audio.get("codec_name"):
            info["codec"] = str(audio["codec_name"]).lower()
        if audio.get("sample_rate"):
            info["sample_rate"] = int(audio["sample_rate"])
        if audio.get("channels"):
            info["channels"] = int(audio["channels"])
    return info


def decode(path: str, *, seconds: Optional[float] = MAX_SECONDS) -> np.ndarray:
    """The sound track as mono samples at `SR`. Raises when ffmpeg cannot read
    it: a file that cannot be decoded is a real failure, distinct from a quiet one."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-f", "f32le", "-ac", "1", "-ar", str(SR), "-"]
    out = subprocess.run(cmd, capture_output=True)
    if out.returncode != 0:
        raise ValueError(f"{path} is not a readable sound: "
                         f"{out.stderr.decode(errors='replace').strip()[:200]}")
    return np.frombuffer(out.stdout, np.float32).astype(np.float64)


def _frames(y: np.ndarray, n: int) -> np.ndarray:
    """Frames of length `n` CENTRED on every hop, as a view (no copy), so the
    spectral and pitch frames of one hop describe the same instant."""
    padded = np.pad(y, (n // 2, n // 2))
    if len(padded) < n:
        padded = np.pad(padded, (0, n - len(padded)))
    return np.lib.stride_tricks.sliding_window_view(padded, n)[::HOP]


def _levels(y: np.ndarray) -> np.ndarray:
    """Each frame's level in dBFS."""
    fr = _frames(y, FRAME)
    out = np.empty(len(fr))
    for i in range(0, len(fr), 4096):
        chunk = fr[i:i + 4096]
        out[i:i + len(chunk)] = 20 * np.log10(np.sqrt((chunk ** 2).mean(axis=1)) + _EPS)
    return out


def _spectrum(y: np.ndarray, lo: int = 0, hi: Optional[int] = None) -> np.ndarray:
    """Magnitude spectra of frames [lo, hi), Hann-windowed."""
    fr = _frames(y, FRAME)[lo:hi]
    return np.abs(np.fft.rfft(fr * np.hanning(FRAME), axis=1))


#: Choosing a pitch PATH through the frames, in costs that are negative log
#: probabilities.
#:
#: WHICH DIP A FRAME'S PITCH IS: a signal periodic at T is exactly as periodic
#: at 2T, so the deepest dip drifts an octave down; and a shallow dip at the
#: wrong lag can come before the deep right one. Neither "deepest" nor "first"
#: is right, and a fixed penalty for going lower fixed one sound and broke
#: another. The threshold a dip has to beat is not known, so it is treated as
#: spread over a fixed distribution (Beta(2, 18), mean 0.1, as pYIN does), and a
#: dip's probability is the share of that distribution under which it is the
#: FIRST dip below the threshold: an early dip wins when it is reasonably deep,
#: a later one only when everything before it is shallow.
_THRESHOLDS = np.arange(0.01, 1.0, 0.01)
_THRESHOLD_PRIOR = (_THRESHOLDS ** (2 - 1)) * ((1 - _THRESHOLDS) ** (18 - 1))
_THRESHOLD_PRIOR = _THRESHOLD_PRIOR / _THRESHOLD_PRIOR.sum()
#: Moving the pitch costs this per octave between consecutive frames: a
#: semitone about a third, an octave as much as a 55-fold drop in probability.
_JUMP_COST = 4.0
_CANDIDATES = 6


def _dips(row: np.ndarray, tmin: int, tmax: int, W: int) -> List[Tuple[float, float]]:
    """Every dip of one frame's cumulative-mean-normalised difference below 0.5,
    as (f0, depth), deepest first, each refined by a clamped parabola."""
    seg = row[tmin:tmax]
    if len(seg) < 3:
        return []
    inner = np.flatnonzero((seg[1:-1] < seg[:-2]) & (seg[1:-1] <= seg[2:]) & (seg[1:-1] < 0.5)) + 1
    if not len(inner):
        j = int(np.argmin(seg))
        inner = np.array([j]) if seg[j] < 0.5 else np.array([], dtype=int)
    out: List[Tuple[float, float]] = []
    for j in inner[np.argsort(seg[inner])][:_CANDIDATES]:
        tau = int(j) + tmin
        a, b, c = row[tau - 1], row[tau], row[min(tau + 1, W)]
        den = a - 2 * b + c
        # The refinement moves the dip by less than a lag or not at all: a flat
        # dip makes the parabola's vertex run off to a period no lag supports
        # (a note at 80 Hz once read as 33 kHz).
        shift = 0.5 * (a - c) / den if abs(den) > _EPS else 0.0
        out.append((SR / (tau + (shift if abs(shift) <= 1.0 else 0.0)), float(b)))
    return out


def yin(frames: np.ndarray, fmin: float = 50.0, fmax: float = 3000.0
        ) -> Tuple[np.ndarray, np.ndarray]:
    """The fundamental frequency and aperiodicity of each frame, for a run of
    CONSECUTIVE frames, chosen as one path through them.

    The measure is YIN's (de Cheveigne and Kawahara, 2002): the cumulative-mean-
    normalised difference function, whose dips mark candidate periods and whose
    depth is the aperiodicity. Aperiodicity is near 0 for a clean periodic frame
    and near 1 for noise; f0 is 0 where a frame has no pitch.

    WHICH DIP IS THE PITCH IS DECIDED OVER THE FRAMES, NOT FRAME BY FRAME. Taking
    each frame's first dip under a threshold read a low note with strong
    overtones as 80 Hz in some frames and 100 Hz in others, because a shallow
    dip at the wrong lag came before the deep one at the right lag, and which
    frames happened to fall inside the sound then decided its pitch. Every dip
    is kept as a candidate and the path that is both deep and continuous is
    chosen (the approach of pYIN, Mauch and Dixon 2014, without its learned
    priors): a real leap in pitch is paid for once and kept, a slip onto a
    harmonic for a frame or two costs more than it saves."""
    frames = np.asarray(frames, dtype=np.float64)
    n = len(frames)
    W = frames.shape[1] // 2
    tmin, tmax = max(2, int(SR / fmax)), min(int(SR / fmin), W - 1)
    x = frames - frames.mean(axis=1, keepdims=True)
    L = 1 << int(np.ceil(np.log2(2 * frames.shape[1])))
    r = np.fft.irfft(np.conj(np.fft.rfft(x[:, :W], L)) * np.fft.rfft(x, L), L)[:, :W + 1]
    sq = np.concatenate([np.zeros((n, 1)), np.cumsum(x ** 2, axis=1)], axis=1)
    taus = np.arange(W + 1)
    d = sq[:, [W]] + (sq[:, W + taus] - sq[:, taus]) - 2 * r
    d[:, 0] = 0.0
    cm = np.ones_like(d)
    cm[:, 1:] = d[:, 1:] * np.arange(1, W + 1) / np.maximum(np.cumsum(d[:, 1:], axis=1), _EPS)

    options: List[List[Tuple[float, float]]] = [
        [] if sq[i, W] < 1e-7 else _dips(cm[i], tmin, tmax, W) for i in range(n)]
    f0 = np.zeros(n)
    # HOW PERIODIC A FRAME IS belongs to the frame, not to the path: its deepest
    # dip, whichever lag is chosen as its pitch. Letting "no pitch" compete with
    # the dips inside one probability silenced two thirds of the voiced frames
    # of speech.
    ap = np.array([min((c[1] for c in o), default=1.0) for o in options])

    def chances(o: List[Tuple[float, float]]) -> np.ndarray:
        """Each dip's probability of being the pitch: the prior mass of the
        thresholds under which it is the first dip below the threshold, taking
        dips in order of lag, earliest (highest pitch) first."""
        freq = np.array([c[0] for c in o])
        depth = np.array([c[1] for c in o])
        out = np.zeros(len(o))
        shallowest_before = 1.0
        for j in np.argsort(-freq):
            window = (_THRESHOLDS > depth[j]) & (_THRESHOLDS <= shallowest_before)
            out[j] = _THRESHOLD_PRIOR[window].sum()
            shallowest_before = min(shallowest_before, depth[j])
        return out

    # One path per run of frames that have candidates; a frame with none (a
    # silent frame) ends the run.
    i = 0
    while i < n:
        if not options[i]:
            i += 1
            continue
        j = i
        while j < n and options[j]:
            j += 1
        run = range(i, j)
        freqs = [np.array([c[0] for c in options[k]]) for k in run]
        costs = [-np.log(chances(options[i]) + 1e-4)]
        backs: List[np.ndarray] = [np.zeros(len(freqs[0]), dtype=int)]
        for m in range(1, len(freqs)):
            move = _JUMP_COST * np.abs(np.log2(freqs[m][None, :] / freqs[m - 1][:, None]))
            total = costs[-1][:, None] + move
            pick = np.argmin(total, axis=0)
            costs.append(total[pick, np.arange(len(freqs[m]))]
                         - np.log(chances(options[i + m]) + 1e-4))
            backs.append(pick)
        state = int(np.argmin(costs[-1]))
        for m in range(len(freqs) - 1, -1, -1):
            f0[i + m] = freqs[m][state]
            state = int(backs[m][state])
        i = j
    # A frame whose best dip is not periodic enough has no pitch to report.
    f0 = np.where(ap < _PERIODIC_AP, f0, 0.0)
    return f0, ap


#: How long, and how steadily, the recording must stay at a level for that level
#: to be where it RESTS rather than somewhere it passed through. Room hiss
#: wobbles by a few dB from frame to frame; a decay sweeps through thirty. The
#: pauses between spoken phrases run 0.1 to 0.15 s, so a longer rest would find
#: none in ordinary speech.
_DWELL_SECONDS = 0.1
_DWELL_SPREAD_DB = 6.0


def ground(levels: np.ndarray) -> Optional[float]:
    """The level the recording rests at when nothing is sounding: its GROUND.

    WHERE IT RESTS, NOT WHERE IT PASSES. The ground is the lowest level the
    recording holds steadily for `_DWELL_SECONDS`. A percentile of frames cannot
    tell resting from passing through. A struck glass decaying into silence
    passes through every level on the way down, and a percentile puts the
    ground inside the glass's own tail, cutting the sound to a fifth of its
    length.

    DIGITAL SILENCE IS NOT A LEVEL THE ROOM RESTS AT. A frame below `_SIGNAL_DB`
    carries no signal: it is the absence of a recording, not the room it was
    made in. So zeros padded around a hissing recording leave its ground at the
    hiss. Taking the ground from the padding put it at -200 dB under JFK's room
    hiss, which made the hiss between two words part of both words: eight
    phrases were heard as six.

    A recording that never rests at any signal level, but does fall to digital
    silence, rests on silence, and its ground is `_SIGNAL_DB`. A recording that
    does neither never rests at all. Its ground is None, and `segment` then
    hears the whole of it as one sound."""
    width = max(3, int(round(_DWELL_SECONDS * SR / HOP)))
    carrying = levels > _SIGNAL_DB
    if not carrying.any():
        return None
    if len(levels) >= width:
        windows = np.lib.stride_tricks.sliding_window_view(levels, width)
        steady = (np.all(np.lib.stride_tricks.sliding_window_view(carrying, width), axis=1)
                  & (np.percentile(windows, 90, axis=1) - np.percentile(windows, 10, axis=1)
                     <= _DWELL_SPREAD_DB))
        if steady.any():
            return float(np.min(np.median(windows[steady], axis=1)))
    return _SIGNAL_DB if not carrying.all() else None


def segment(levels: np.ndarray) -> Tuple[List[Tuple[int, int]], Optional[float]]:
    """The sounds in a recording, as (first frame, last frame), and its ground.

    A sound is a stretch that rises `_RISE_DB` above the ground and lasts while
    it stays `_HOLD_DB` above it. AUDIBILITY IS HOW LOUD THE RECORDING GETS, not
    how much of it is loud: a 0.1 s tink in 1.6 s of silence is 5% of the frames
    and is still plainly heard.

    A RECORDING WITH NO GROUND is one sound. When it never falls quiet -- a
    steady tone, a hum filling the clip -- there is nothing for a sound to rise
    above, and the whole of it is what is sounding. That case returns a ground
    of None, because none was measured."""
    if not len(levels) or float(levels.max()) < _AUDIBLE_DB:
        return [], ground(levels)
    floor = ground(levels)
    if floor is None or float(levels.max()) - floor < _RISE_DB:
        audible = np.flatnonzero(levels > _SIGNAL_DB)
        return [(int(audible[0]), int(audible[-1]))], None
    rise, hold = levels > floor + _RISE_DB, levels > floor + _HOLD_DB
    spans: List[List[int]] = []
    i = 0
    while i < len(levels):
        if not rise[i]:
            i += 1
            continue
        s = i
        while s > 0 and hold[s - 1]:
            s -= 1
        e = i
        while e + 1 < len(levels) and hold[e + 1]:
            e += 1
        if spans and (s - spans[-1][1]) * HOP / SR < _MERGE_GAP:
            spans[-1][1] = e
        else:
            spans.append([s, e])
        i = e + 1
    return ([(s, e) for s, e in spans if (e - s + 1) * HOP / SR >= _MIN_SOUND], floor)


# --- what each sound is like ----------------------------------------------------

def _register(f0: float) -> Tuple[str, float]:
    """The register a pitch sits in, and how far (in octaves) from the nearest
    edge it sits, as a support."""
    lower = 0.0
    for edge, name in _REGISTERS:
        if f0 < edge:
            edges = [e for e in (lower, edge) if 0 < e < math.inf]
            dist = min(abs(math.log2(f0 / e)) for e in edges)
            return name, round(min(1.0, dist / _PITCH_RESOLUTION), 3)
        lower = edge
    return _REGISTERS[-1][1], 1.0


def _onset(attack: float) -> Tuple[str, float]:
    a = max(attack, HOP / SR)
    name = "abrupt" if a <= _ABRUPT_SECONDS else "gradual"
    return name, round(min(1.0, abs(math.log2(a / _ABRUPT_SECONDS)) / _ONSET_RESOLUTION), 3)


#: The attack is read on a fine envelope -- RMS over 5 ms, every millisecond --
#: so where the analysis grid happens to fall cannot move it. Frames 46 ms wide
#: every 11.6 ms read a padded copy of a recording as starting 58 ms sooner.
_ENVELOPE_WINDOW = int(0.005 * SR)
_ENVELOPE_STEP = int(0.001 * SR)
_ATTACK_WINDOW = 0.15


def _rise(y: np.ndarray, s: int, floor: Optional[float]) -> Tuple[Optional[int], Optional[np.ndarray]]:
    """The sample at which a sound rises above its ground, and the fine envelope
    from there on; (None, None) when the rise was not heard -- when the
    recording's very first milliseconds are already above the ground."""
    rise_at = _SIGNAL_DB if floor is None else floor + _HOLD_DB
    begin = max(0, s * HOP - FRAME // 2)
    stop = min(len(y), s * HOP + FRAME // 2 + int(_ATTACK_WINDOW * SR) + _ENVELOPE_WINDOW)
    chunk = y[begin:stop]
    if len(chunk) < _ENVELOPE_WINDOW:
        return None, None
    windows = np.lib.stride_tricks.sliding_window_view(chunk, _ENVELOPE_WINDOW)[::_ENVELOPE_STEP]
    env = 20 * np.log10(np.sqrt((windows ** 2).mean(axis=1)) + _EPS)
    above = np.flatnonzero(env > rise_at)
    if not len(above) or (begin == 0 and int(above[0]) == 0):
        return None, None
    first = int(above[0])
    return begin + first * _ENVELOPE_STEP, env[first:]


def _attack(y: np.ndarray, s: int, floor: Optional[float]) -> Optional[float]:
    """How long the sound takes to come within 3 dB of the loudest it gets in
    its first 150 ms, counted from the moment it rises above its ground: None
    when that moment was not heard.

    Over longer than the attack this would measure a swell AFTER the attack (a
    note that kept growing for a quarter second read as slow to start when it
    began within a hop), and over the whole sound it would measure where the
    stressed syllable of a phrase falls.

    A SOUND ALREADY SOUNDING WHEN THE RECORDING BEGAN WAS NOT HEARD TO START. If
    the recording's very first milliseconds are already above the ground, the
    rise, if there was one, happened before the recording or in its first
    instant, and cannot be told from a recording that cut into the sound. How it
    started is unknown and is not claimed: the edge of a recording is not the
    edge of the sound, as the edge of a picture is not the edge of the thing."""
    _at, env = _rise(y, s, floor)
    if env is None:
        return None
    reach = env[:int(_ATTACK_WINDOW * SR / _ENVELOPE_STEP)]
    peak_at = int(np.flatnonzero(reach >= reach.max() - 3.0)[0])
    return peak_at * _ENVELOPE_STEP / SR


def _describe_sound(y: np.ndarray, levels: np.ndarray, span: Tuple[int, int],
                    floor: Optional[float]) -> Dict[str, Any]:
    """Everything measured of one sound, and the names that measurement earns.

    WHAT IS CLAIMED OF THE SOUND is what belongs to the sound: whether it is
    pitched, its register, how it starts. What belongs to the RECORDING -- how
    loud it came out, when in the recording it began, how long it stayed above
    this recording's ground -- is kept as a measurement and never as `isa`,
    because a microphone moved closer makes the same sound louder exactly as a
    camera moved closer makes the same thing larger."""
    s, e = span
    seg = levels[s:e + 1]
    power = 10 ** (seg / 10)
    level = float(10 * np.log10(power.mean() + _EPS))
    f0, ap = yin(_frames(y, PITCH_FRAME)[s:e + 1])
    periodic = ap < _PERIODIC_AP
    pitched_share = float((power * periodic).sum() / max(power.sum(), _EPS))
    # HOW FIRMLY THE SHARE IS KNOWN depends on how many frames it really rests
    # on. One half-silent frame more or less at the start of a short sound (the
    # analysis grid landing differently when the recording is padded) moved a
    # pop's share by 0.23. The share is weighted by energy, so a percussive sound
    # whose energy sits in its first few frames rests on those few, however many
    # frames it lasts: the frames that count are the EFFECTIVE number, (sum w)^2 /
    # sum w^2 (Kish). The share's resolution is the larger of what moved it on
    # long sounds and twice its standard error over those frames.
    effective = float(power.sum() ** 2 / max((power ** 2).sum(), _EPS))
    share_resolution = max(_PITCHED_RESOLUTION,
                           2.0 * math.sqrt(max(pitched_share * (1 - pitched_share), 0.0625)
                                           / max(effective, 1.0)))
    # The median of the STEADIED track -- slips onto a harmonic folded back, and
    # leaps between two notes smoothed out -- because a plain median of frames
    # is pulled by the slips: a note at 80 Hz with strong overtones reported
    # itself at 100.7 Hz. The trace keeps the same track, so what is described
    # and what is remembered agree.
    steady = _steady_pitch(f0, 1.0 - ap)
    held = steady[periodic & (steady > 0)]
    pitch = float(np.median(held)) if len(held) >= 3 else None
    # HOW WELL ONE PITCH FITS THE SOUND: the share of its periodic frames within
    # a semitone of that pitch. A chord has no one pitch -- a sound whose frames
    # read 80 Hz or 100 Hz (a major third) gave either as "its" pitch depending
    # on which frames fell inside it -- and a claim built on its pitch must say
    # so rather than pass one note off as the sound.
    steadiness = (float(np.mean(np.abs(12 * np.log2(held / pitch)) <= 1.0))
                  if pitch else None)
    attack = _attack(y, s, floor)
    mag = _spectrum(y, s, e + 1)
    freqs = np.fft.rfftfreq(FRAME, 1 / SR)
    centroid = float((mag * freqs).sum() / max(mag.sum(), _EPS))

    # HOW WELL IT WAS HEARD, the counterpart of how good the look was: a sound
    # just over its ground is barely heard, one far above it is heard clearly.
    # Multiplies into every support, because each reading was taken off the
    # same waveform. None when the recording has no ground to stand on.
    heard = (None if floor is None else
             round(max(0.0, min(1.0, (level - floor - _HOLD_DB) / (_CLEAR_DB - _HOLD_DB))), 3))

    def supported(support: float) -> float:
        return round(support if heard is None else support * heard, 3)

    tonal = "pitched" if pitched_share >= _PITCHED_SHARE else "unpitched"
    names: Dict[str, float] = {
        tonal: supported(_margin(pitched_share, _PITCHED_SHARE, share_resolution))}
    register = None
    if tonal == "pitched" and pitch:
        register, reg_support = _register(pitch)
        # The margin of the median from the register's edges, times the share of
        # the sound actually heard in that register: a sound straddling middle C
        # is not firmly in either, and a chord both of whose notes are low is
        # firmly low whichever of them the median landed on.
        in_register = float(np.mean([_register(f)[0] == register for f in held]))
        # And never surer than that the sound is pitched at all: a register is
        # a fact about a pitch, and a sound barely heard as pitched has a barely
        # known register however far its median sits from middle C.
        names[register] = min(supported(reg_support * in_register), names[tonal])
    onset = None
    if attack is not None:
        onset, onset_support = _onset(attack)
        names[onset] = supported(onset_support)
    return {
        "start": round(s * HOP / SR, 3),
        "end": round((e + 1) * HOP / SR, 3),
        "duration": round((e - s + 1) * HOP / SR, 3),
        "level": round(level, 1),
        "above_ground": None if floor is None else round(level - floor, 1),
        "heard": heard,
        "pitched_share": round(pitched_share, 3),
        "pitch": round(pitch, 1) if pitch else None,
        "pitch_steadiness": None if steadiness is None else round(steadiness, 3),
        "attack": None if attack is None else round(attack, 3),
        "centroid": round(centroid),
        "tonality": tonal,
        "register": register,
        "onset": onset,
        #: The names this sound earns and how well each is borne out.
        "support": names,
    }


def relations(sounds: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """How each sound stands to the one that came NEXT, as
    `{"a": i, "rel": ..., "b": j, "support": ...}` over the list given, which
    is in time order.

    These are the INVARIANT half of hearing, as `left_of` and `larger_than` are
    of sight. Turn the recording up and every level changes while the louder of
    two sounds is still the louder; pad it with silence and every start time
    moves while what came first still came first.

      `before`      -- a ends before b starts, the gap measured against the
                       merge gap (two sounds closer than that are one sound).
      `louder_than` -- by at least `_LOUDER_DB`, fully resolved at twice it.
      `higher_than` -- both pitched, by at least `_HIGHER_SEMITONES`, fully
                       resolved at twice it.

    BETWEEN NEIGHBOURS ONLY. Order is transitive, so `before` between every pair
    restates the neighbours' chain n(n-1)/2 times. Comparing each sound with the
    one that followed it is also the comparison a listener makes. So a
    recording of n sounds states at most 3(n-1) relations."""
    out: List[Dict[str, Any]] = []
    for i in range(len(sounds) - 1):
        a, b = sounds[i], sounds[i + 1]
        gap = b["start"] - a["end"]
        if gap >= 0:
            out.append({"a": i, "rel": "before", "b": i + 1,
                        "support": round(min(1.0, gap / _MERGE_GAP), 3)})
        for x, y, first, second in ((a, b, i, i + 1), (b, a, i + 1, i)):
            louder = x["level"] - y["level"]
            if louder >= _LOUDER_DB:
                out.append({"a": first, "rel": "louder_than", "b": second,
                            "support": round(min(1.0, louder / _LOUDER_DB - 1.0), 3)})
            if x.get("register") and y.get("register") and x.get("pitch") and y.get("pitch"):
                semis = 12 * math.log2(x["pitch"] / y["pitch"])
                if semis >= _HIGHER_SEMITONES:
                    # Only as sure as the two pitches are single pitches.
                    fit = min(x.get("pitch_steadiness") or 0.0, y.get("pitch_steadiness") or 0.0)
                    out.append({"a": first, "rel": "higher_than", "b": second,
                                "support": round(min(1.0, semis / _HIGHER_SEMITONES - 1.0) * fit, 3)})
    return out


def _hearing_category(sounds: Sequence[Dict[str, Any]], floor: Optional[float]) -> str:
    """How good the hearing was, said of the whole recording: `clear` when its
    sounds stand well above the ground, `fair`, `poor`, or `no_ground` when the
    recording never fell quiet and so offered nothing to measure against."""
    if floor is None:
        return "no_ground"
    heard = [s["heard"] for s in sounds if s.get("heard") is not None]
    if not heard:
        return "poor"
    m = float(np.median(heard))
    return "clear" if m >= 0.75 else ("fair" if m >= 0.35 else "poor")


def _background_category(floor: Optional[float]) -> str:
    """What the recording rests on between sounds."""
    if floor is None:
        return "none"
    if floor < -70:
        return "silent"
    return "quiet" if floor < -45 else "noisy"


#: The most sounds one recording states as individuals, as sight states at most
#: ten regions. The most PROMINENT are kept (loudest above the ground), in the
#: order they were heard, and `sound_count` still says how many there were.
MAX_SOUNDS = 12


def describe(path: str, *, max_sounds: int = MAX_SOUNDS) -> Dict[str, Any]:
    """Everything classically knowable about the sound in one file -- an audio
    file, or the sound track of a video.

    Raises on a path that names nothing ffmpeg can decode. A file with NO sound
    track (a silent video) returns `has_audio: False` and no sounds: nothing was
    heard because there was nothing to hear, which is a fact, not a failure."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"no sound at {path}")
    raw = p.read_bytes()
    info = probe(str(p))
    result: Dict[str, Any] = {"kind": "audio", "path": str(p), "sha256": _sha256(raw)}
    result.update(info)
    if not info.get("has_audio", False):
        if not info:
            raise ValueError(f"{path} is not a readable sound")
        result.update({"sounds": [], "relations": [], "heard_seconds": 0.0})
        return result
    y = decode(str(p))
    levels = _levels(y)
    spans, floor = segment(levels)
    found = [_describe_sound(y, levels, span, floor) for span in spans]
    prominent = sorted(range(len(found)), key=lambda k: -found[k]["level"])[:max_sounds]
    sounds = [found[k] for k in sorted(prominent)]
    result.update({
        "heard_seconds": round(len(y) / SR, 3),
        "ground": None if floor is None else round(floor, 1),
        "peak": round(float(levels.max()), 1) if len(levels) else None,
        "sounds": sounds,
        "sound_count": len(found),
        "relations": relations(sounds),
        "hearing_category": _hearing_category(sounds, floor),
        "background": _background_category(floor),
        #: What is kept of the hearing so it can be heard again in the mind:
        #: the sounds' shape over time, never the recording itself.
        "trace": trace(y, levels, spans, floor),
    })
    return result


# --- the trace: what is remembered of a sound, and hearing it again -----------
#
# A MEMORY OF A SOUND IS NOT THE RECORDING. A person who remembers a bell does
# not replay a file; they rebuild the bell from what stayed with them -- its
# pitch, how it rang, how long, how loud, what the room was like. So what is
# kept is the SHAPE of each sound over time: its spectral envelope in a couple
# of dozen bands, its pitch and how periodic it was, a few times a second, plus
# the ground the recording rested on. The quiet stretches between sounds are not
# kept at all. Rebuilding pushes a source (harmonics at the remembered pitch,
# blended with noise by how periodic it was) through the remembered envelope.
# The rebuilt sound is a GIST: its pitch, timing, loudness and rough colour are
# the original's, its fine detail is not, which is also true of the one a
# person hears in their head.
#
# THE TEST OF A TRACE IS WHETHER THE REBUILT SOUND IS HEARD AS THE SAME: the
# same sounds, at the same pitches, starting the same way.

#: The trace's frames, bands and range. Two analysis hops per trace frame
#: (~43 a second, so a 70 ms tink is three frames and not one) and 24 bands
#: between 50 Hz and 10 kHz.
TRACE_HOP = 2 * HOP
TRACE_BANDS = 24
_TRACE_FMIN, _TRACE_FMAX = 50.0, 10000.0


def _mel_bank(bands: int = TRACE_BANDS, n_fft: int = FRAME) -> np.ndarray:
    """Triangular bands evenly spaced on the mel scale, over an `n_fft` spectrum."""
    def to_mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def to_hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)
    edges = to_hz(np.linspace(to_mel(_TRACE_FMIN), to_mel(_TRACE_FMAX), bands + 2))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / SR)
    bank = np.zeros((bands, len(freqs)))
    for b in range(bands):
        lo, mid, hi = edges[b], edges[b + 1], edges[b + 2]
        bank[b] = np.clip(np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)), 0, None)
    return bank


_BANK = _mel_bank()
_WINDOW = np.hanning(FRAME)
_WINDOW_POWER = float((_WINDOW ** 2).sum())


def _band_db(frames: np.ndarray) -> np.ndarray:
    """Each frame's power in each band, in dB, normalised by the window so the
    same sound measures the same whatever the frame."""
    spectrum = np.abs(np.fft.rfft(frames * _WINDOW, axis=1)) ** 2 / _WINDOW_POWER
    return 10.0 * np.log10(spectrum @ _BANK.T + _EPS)


def _steady_pitch(f0: np.ndarray, periodic: np.ndarray) -> np.ndarray:
    """One sound's pitch track with harmonic slips folded back.

    A single frame's pitch can land on a harmonic or a subharmonic of the true
    one -- a low note with strong overtones read 79, 158, 318, 80, 400 Hz over
    five frames. The sound's median pitch is robust to that, so each frame is
    moved to whichever multiple or fraction of itself (1/5 .. 5) lies nearest
    the median, IF that multiple lies within a third of an octave of it. A frame
    further than that from every multiple is a real movement of the pitch
    (speech glides by half an octave) and is left where it was.

    The centre is taken over the frames that were clearly periodic, but EVERY
    frame keeps a pitch: a frame just over the periodicity threshold in the
    middle of a steady note is still that note, and storing it as "no pitch"
    rebuilt the note with a burst of noise in it. How periodic each frame was
    is kept beside the pitch and decides the blend on rebuilding. A frame whose
    pitch is still more than an octave from the centre after folding has no
    pitch of this sound in it -- an attack transient read as 3.4 kHz -- and is
    kept as none."""
    out = f0.astype(np.float64).copy()
    voiced = out > 0
    steady = voiced & (periodic > 1.0 - _PERIODIC_AP)
    if steady.sum() < 3:
        return np.where(steady, out, 0.0)
    centre = float(np.median(out[steady]))
    ratios = np.array([1 / 5, 1 / 4, 1 / 3, 1 / 2, 1, 2, 3, 4, 5], dtype=np.float64)
    for i in np.flatnonzero(voiced):
        options = out[i] * ratios
        distance = np.abs(np.log2(options / centre))
        best = int(np.argmin(distance))
        if distance[best] <= 1 / 3 and abs(np.log2(out[i] / centre)) > 1 / 3:
            out[i] = options[best]
        if abs(np.log2(out[i] / centre)) > 1.0:
            out[i] = 0.0
    # A voice glides; it does not leap a third and back between two frames 23 ms
    # apart. Such a leap is the reading slipping between two notes of a chord,
    # and a 5-frame median over the voiced frames (in octaves) takes it out
    # while keeping every glide that lasts longer than two frames.
    voiced = out > 0
    if voiced.sum() >= 5:
        logs = np.log2(np.where(voiced, out, 1.0))
        runs = np.flatnonzero(voiced)
        smoothed = logs.copy()
        for j, i in enumerate(runs):
            window = runs[max(0, j - 2):j + 3]
            smoothed[i] = np.median(logs[window])
        out = np.where(voiced, 2 ** smoothed, 0.0)
    return out


def trace(y: np.ndarray, levels: np.ndarray, spans: Sequence[Tuple[int, int]],
          floor: Optional[float]) -> Dict[str, Any]:
    """What is kept of a hearing: for each sound, its band envelope, pitch and
    periodicity at every trace frame; and the ground's own spectrum and level.
    Nothing between the sounds is kept."""
    step = TRACE_HOP // HOP
    spectral = _frames(y, FRAME)
    pitch_frames = _frames(y, PITCH_FRAME)
    segments: List[Dict[str, Any]] = []
    for s, e in spans:
        idx = np.arange(s - s % step, e + 1, step)
        idx = idx[idx < min(len(spectral), len(pitch_frames))]
        if not len(idx):
            continue
        f0, ap = yin(pitch_frames[idx])
        periodic = np.clip(1.0 - ap, 0.0, 1.0)
        rose, _env = _rise(y, s, floor)
        segments.append({
            "at": int(idx[0]),
            #: The sample at which the sound rose above its ground (-1 when that
            #: was not heard), so it is heard again starting where it started
            #: and not a window's width sooner.
            "rose": -1 if rose is None else int(rose),
            #: Loudness at every hop, so an attack is remembered as sharp as it
            #: was: the bands say what the sound was like, this says how it rose
            #: and fell, at a few hundred bytes a second.
            "level": levels[idx[0]:min(len(levels), idx[-1] + step)].astype(np.float16),
            "bands": _band_db(spectral[idx]).astype(np.float16),
            "pitch": _steady_pitch(f0, periodic).astype(np.float16),
            "periodic": periodic.astype(np.float16),
        })
    ground_bands = None
    if floor is not None and floor > _SIGNAL_DB:
        resting = np.flatnonzero(np.abs(levels - floor) <= 3.0)
        if len(resting):
            ground_bands = np.median(_band_db(spectral[resting[:: max(1, len(resting) // 200)]]),
                                     axis=0).astype(np.float16)
    return {"samples": int(len(y)), "segments": segments, "ground": ground_bands}


def trace_bytes(t: Dict[str, Any], example: Optional[np.ndarray] = None,
                landmarks: Optional[np.ndarray] = None,
                tune: Optional[np.ndarray] = None, tune_from_mix: bool = False) -> bytes:
    """A trace as bytes, for keeping in a memory. A hearing that was a LESSON
    -- an example of a word, a voice or a song -- keeps what was measured of it
    for matching (`example`, see `core.perception.speech`) in the same archive,
    so one memory holds all that was kept of that hearing.

    EVERY HEARING KEEPS ITS LANDMARKS (`landmarks`), lesson or not: they are
    what the same sound is known by when it is met again, so memory can be
    asked "have I heard this?" by the sound itself (`MemoryAgent.retrieve`,
    strategy `sound`).

    A SINGLE LINE KEEPS ITS TUNE (`tune`, `music.tune_line`): how its melody
    goes, which a song is known by when someone else hums or sings it. A song
    taught from a mix keeps the tune of the mix's melody (`tune_from_mix`)."""
    import io
    arrays: Dict[str, np.ndarray] = {"samples": np.array([t["samples"]], np.int64)}
    if example is not None:
        arrays["example"] = np.asarray(example, np.float32)
    if landmarks is not None and len(landmarks):
        arrays["landmarks"] = np.asarray(landmarks, np.int32)
    if tune is not None and len(tune):
        arrays["tune"] = np.asarray(tune, np.float16)
        if tune_from_mix:
            arrays["tune_from_mix"] = np.array([1], np.int8)
    if t.get("ground") is not None:
        arrays["ground"] = np.asarray(t["ground"], np.float16)
    for k, seg in enumerate(t["segments"]):
        arrays[f"s{k}_at"] = np.array([seg["at"], seg.get("rose", -1)], np.int64)
        for key in ("level", "bands", "pitch", "periodic"):
            arrays[f"s{k}_{key}"] = np.asarray(seg[key], np.float16)
    buf = io.BytesIO()
    np.savez_compressed(buf, **arrays)
    return buf.getvalue()


def trace_landmarks(data: bytes) -> Optional[np.ndarray]:
    """The landmarks a hearing's trace kept, or None when it kept none (a
    trace kept before hearings kept them)."""
    import io
    with np.load(io.BytesIO(data)) as z:
        return np.array(z["landmarks"], np.int32) if "landmarks" in z.files else None


def trace_tune(data: bytes) -> Optional[np.ndarray]:
    """The tune a hearing's trace kept (`music.tune_line`), or None when what
    was heard was not a single line."""
    import io
    with np.load(io.BytesIO(data)) as z:
        return np.array(z["tune"], np.float32) if "tune" in z.files else None


def trace_tune_from_mix(data: bytes) -> bool:
    """Whether the tune a trace kept was read from a mix's melody."""
    import io
    with np.load(io.BytesIO(data)) as z:
        return "tune_from_mix" in z.files


def landmark_hashes(rows: np.ndarray) -> np.ndarray:
    """A sound's distinct landmark hashes, each (f1, f2, dt) packed into one
    integer (f1 and f2 are under 1024, dt under 64), for looking sounds up by
    what they share."""
    if rows is None or not len(rows):
        return np.zeros(0, np.int32)
    r = np.asarray(rows, np.int64)
    return np.unique((r[:, 0] << 16) | (r[:, 1] << 6) | r[:, 2]).astype(np.int32)


def trace_from_bytes(data: bytes) -> Dict[str, Any]:
    import io
    with np.load(io.BytesIO(data)) as z:
        count = len({k.split("_", 1)[0] for k in z.files if k.startswith("s") and "_" in k})
        return {"samples": int(z["samples"][0]),
                "ground": np.array(z["ground"]) if "ground" in z.files else None,
                "segments": [{"at": int(z[f"s{k}_at"][0]),
                              "rose": int(z[f"s{k}_at"][1]) if len(z[f"s{k}_at"]) > 1 else -1,
                              "level": np.array(z[f"s{k}_level"], np.float32),
                              "bands": np.array(z[f"s{k}_bands"], np.float32),
                              "pitch": np.array(z[f"s{k}_pitch"], np.float32),
                              "periodic": np.array(z[f"s{k}_periodic"], np.float32)}
                             for k in range(count)]}


def rebuild(t: Dict[str, Any], *, seed: int = 0) -> np.ndarray:
    """Hear a remembered sound again: samples at `SR`, rebuilt from its trace.

    Source and filter, computed rather than chased. The remembered bands are
    turned into a smooth spectral density for every hop. The PERIODIC part is
    added up harmonic by harmonic at the remembered pitch, each harmonic at the
    amplitude that density calls for at its own frequency, so its phase runs on
    unbroken and it is heard as the same note. The rest is noise shaped by the
    same density. How periodic each frame was divides the density between the
    two, so a breathy frame comes back breathy and a clean one clean, and the
    energy in every band is the remembered energy by construction.

    Chasing the target instead -- measuring the source's own band energies each
    frame and correcting toward the remembered ones -- made the gains flutter
    with the noise and with harmonics crossing band edges, and a note came back
    heard as unpitched. The ground is noise in the ground's own spectrum, under
    everything."""
    rng = np.random.default_rng(seed)
    n = int(t["samples"])
    step = TRACE_HOP // HOP
    hops = 1 + n // HOP
    target = np.full((hops, TRACE_BANDS), -np.inf)
    pitch = np.zeros(hops)
    periodic = np.zeros(hops)
    if t.get("ground") is not None:
        target[:] = np.asarray(t["ground"], np.float64)
    for seg in t["segments"]:
        bands = np.asarray(seg["bands"], np.float64)
        at = int(seg["at"])
        # Trace frames every `step` hops, spread to every hop by moving in dB
        # between them, which is how loudness moves.
        idx = at + np.arange(len(bands)) * step
        span = np.arange(at, min(hops, at + len(bands) * step))
        if not len(span):
            continue
        for b in range(TRACE_BANDS):
            target[span, b] = np.interp(span, idx, bands[:, b])
        # The shape comes from the bands; how loud each hop was comes from the
        # level remembered at every hop, so the rise and fall are the heard ones.
        fine = np.asarray(seg.get("level", []), np.float64)
        if len(fine):
            here = span[span - at < len(fine)]
            coarse = 10 * np.log10(np.sum(10 ** (target[here] / 10), axis=1) + _EPS)
            remembered = 10 * np.log10(np.sum(10 ** (bands / 10), axis=1) + _EPS)
            # The fine track and the bands measure loudness differently (a
            # frame's mean square, and power summed over the bands), so the
            # fine track moves the rebuilt level, measured against itself at the
            # trace frames, and never sets it outright.
            anchor = np.interp(here, idx, fine[np.clip(idx - at, 0, len(fine) - 1)])
            target[here] += (fine[here - at] - anchor)[:, None]
            del coarse, remembered
        raw = np.asarray(seg["pitch"], np.float64)
        voiced = raw > 0
        if voiced.any():
            # Interpolated over the voiced frames only: a pitch half way
            # between a note and "no pitch" is a pitch nobody heard.
            pitch[span] = np.interp(span, idx[voiced], raw[voiced])
            pitch[span] *= np.interp(span, idx, voiced.astype(float)) >= 0.5
        periodic[span] = np.interp(span, idx, np.asarray(seg["periodic"], np.float64))

    # The spectral density each hop calls for, per analysis bin, in the units
    # `_band_db` measures in (white noise of unit variance measures 1 per bin).
    area = _BANK.sum(axis=1)
    spread = _BANK.T / np.maximum(_BANK.sum(axis=0), _EPS)[:, None]
    power = np.where(np.isfinite(target), 10 ** (np.where(np.isfinite(target), target, 0.0) / 10), 0.0)
    density = (power / area) @ spread.T                        # (hops, bins)
    share = np.where(pitch > 0, np.clip(periodic, 0.0, 1.0), 0.0)

    # The periodic part: harmonic k at amplitude 2*sqrt(S(k f0) * f0 / SR), which
    # makes a series of harmonics f0 apart average to the density S.
    out = np.zeros(n)
    centres = np.arange(hops) * HOP
    voiced_hops = np.flatnonzero(pitch > 0)
    if len(voiced_hops):
        f0 = np.interp(np.arange(n), centres, pitch)
        f0 = np.where(np.interp(np.arange(n), centres, (pitch > 0).astype(float)) >= 0.5, f0, 0.0)
        phase = 2 * np.pi * np.cumsum(f0) / SR
        bin_width = SR / FRAME
        most = int(np.floor((SR / 2) / max(float(pitch[voiced_hops].min()), 20.0)))
        for k in range(1, most + 1):
            freq = k * pitch
            ok = (pitch > 0) & (freq < SR / 2)
            if not ok.any():
                break
            b = np.clip(np.round(freq / bin_width).astype(int), 0, density.shape[1] - 1)
            amp = np.where(ok, 2.0 * np.sqrt(share * density[np.arange(hops), b]
                                             * pitch / SR), 0.0)
            out += np.interp(np.arange(n), centres, amp) * np.cos(k * phase)

    # The rest: noise shaped by what the periodic part did not take.
    noise = np.pad(rng.standard_normal(n), (FRAME // 2, FRAME // 2))
    shaped = np.zeros(len(noise))
    norm = np.zeros(len(noise))
    rest = np.sqrt(density * (1.0 - share)[:, None])
    for i in range(min(hops, 1 + (len(noise) - FRAME) // HOP)):
        if not rest[i].any():
            continue
        spec = np.fft.rfft(noise[i * HOP:i * HOP + FRAME] * _WINDOW)
        shaped[i * HOP:i * HOP + FRAME] += np.fft.irfft(spec * rest[i], FRAME) * _WINDOW
        norm[i * HOP:i * HOP + FRAME] += _WINDOW ** 2
    shaped = shaped[FRAME // 2:FRAME // 2 + n] / np.maximum(norm[FRAME // 2:FRAME // 2 + n], 1e-3)
    heard = out + shaped
    # WHERE A SOUND ROSE, IT RISES AGAIN. The synthesis window is 46 ms wide, so
    # a sound would otherwise begin up to half a window before it did -- at the
    # very first sample of a recording where the original had a few quiet
    # milliseconds, which then reads as a sound already under way. Before its
    # remembered rise a sound is silent in its own frames, reaching full level
    # over a millisecond.
    ramp = max(1, _ENVELOPE_STEP)
    for seg in t["segments"]:
        rose = int(seg.get("rose", -1))
        if rose < 0:
            continue
        lead = max(0, int(seg["at"]) * HOP - FRAME // 2)
        if rose > lead:
            heard[lead:rose] = 0.0
            heard[rose:rose + ramp] *= np.linspace(0.0, 1.0, min(ramp, n - rose))
    return heard.astype(np.float32)


# --- landmarks: recognising a sound heard before ------------------------------
#
# A known sound is recognised the way a known instance is seen: by distinctive
# local features that must AGREE with one another, not by resemblance. Here the
# features are peaks of the spectrogram, paired into (frequency, frequency, time
# gap) hashes, and agreement is a single time offset at which many hashes of the
# reference line up in what is heard (Wang, 2003). One agreeing hash means
# nothing; many agreeing on one offset do not happen by chance.
#
# What this recognises is THE SAME SOUND HEARD AGAIN -- a doorbell, an alert, a
# recorded voice replayed -- through gain, noise, a telephone line, a codec, a
# room. It does NOT recognise a different utterance of a word: a word is a kind
# of sound, and a kind is named by the substrate's own induction.

#: Strongest peaks kept per second. Ranked per second rather than over the whole
#: recording, or a quiet sound loses every peak to a louder one elsewhere.
_PEAKS_PER_SECOND = 25
_PEAK_BINS, _PEAK_FRAMES = 21, 11
_PEAK_OVER_LOCAL_DB = 6.0
_PEAK_MIN_DB = -85.0
#: A peak is paired with EVERY peak in its target zone, not with the next few:
#: pairing with the next few lets one inserted peak displace every pair after it.
_ZONE_FRAMES, _ZONE_BINS = 48, 150
#: Hashes that must agree on one offset to recognise a known sound. The worst
#: unrelated recording reached 6 across 252 comparisons of the system sounds
#: against each other and against real speech.
KNOWN_MIN_AGREE = 10
#: A reference with fewer DISTINCT landmarks can never be recognised: about a
#: tenth of a reference's hashes survive a replay mixed with other sound, so
#: fewer than this cannot reach the cut. Distinct, because a plain sound says
#: the same thing over and over: a one-second 440 Hz tone gave 107 landmarks
#: and only 66 different ones, and any other 440 Hz tone would agree with them.
KNOWN_MIN_LANDMARKS = 100


def distinct_landmarks(rows: np.ndarray) -> int:
    """How many different hashes (f1, f2, dt) a sound's landmarks hold."""
    if not len(rows):
        return 0
    return int(len(np.unique(np.asarray(rows)[:, :3], axis=0)))


def _peaks(y: np.ndarray) -> np.ndarray:
    from scipy.ndimage import maximum_filter, uniform_filter
    S = np.empty((FRAME // 2 + 1, len(_frames(y, FRAME))), dtype=np.float32)
    for i in range(0, S.shape[1], 4096):
        S[:, i:i + 4096] = (20 * np.log10(_spectrum(y, i, i + 4096) + _EPS)).T
    local = maximum_filter(S, size=(_PEAK_BINS, _PEAK_FRAMES), mode="nearest")
    mean = uniform_filter(S, size=(_PEAK_BINS * 3, _PEAK_FRAMES * 3), mode="nearest")
    cand = np.argwhere((S == local) & (S > mean + _PEAK_OVER_LOCAL_DB) & (S > _PEAK_MIN_DB))
    if not len(cand):
        return np.zeros((0, 2), dtype=np.int64)
    strength = S[cand[:, 0], cand[:, 1]]
    per_second = int(SR / HOP)
    keep: List[int] = []
    for w0 in range(0, S.shape[1], per_second):
        idx = np.flatnonzero((cand[:, 1] >= w0) & (cand[:, 1] < w0 + per_second))
        keep.extend(idx[np.argsort(-strength[idx])][:_PEAKS_PER_SECOND].tolist())
    chosen = cand[np.array(keep, dtype=np.int64)]
    return chosen[np.argsort(chosen[:, 1], kind="stable")]


def landmarks(y: np.ndarray) -> np.ndarray:
    """The hashes of a sound, as rows (f1, f2, dt, t) of int32: two peaks'
    frequency bins, the frames between them, and when the first one fell."""
    pk = _peaks(y)
    rows: List[Tuple[int, int, int, int]] = []
    for i in range(len(pk)):
        f1, t1 = int(pk[i, 0]), int(pk[i, 1])
        for j in range(i + 1, len(pk)):
            f2, t2 = int(pk[j, 0]), int(pk[j, 1])
            dt = t2 - t1
            if dt <= 0:
                continue
            if dt > _ZONE_FRAMES:
                break
            if abs(f2 - f1) <= _ZONE_BINS:
                rows.append((f1, f2, dt, t1))
    return np.array(rows, dtype=np.int32).reshape(-1, 4)


def landmark_index(rows: np.ndarray) -> Dict[Tuple[int, int, int], List[Tuple[int, int]]]:
    """A reference's hashes, keyed for lookup: hash -> [(row, time)]."""
    table: Dict[Tuple[int, int, int], List[Tuple[int, int]]] = defaultdict(list)
    for k, (f1, f2, dt, t) in enumerate(rows.tolist()):
        table[(f1, f2, dt)].append((k, t))
    return table


#: A peak can move by a bin or a frame when a sound lands a fraction of a frame
#: off the grid, so a hash is looked up with that much give on each part.
_GIVE = [(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]


def agreement(table: Dict[Tuple[int, int, int], List[Tuple[int, int]]],
              heard: np.ndarray) -> Tuple[int, Optional[float]]:
    """How many of a reference's hashes line up at ONE offset in what was heard,
    and where (seconds into the heard recording). Offsets within a frame or two
    are one alignment."""
    votes: Dict[int, set] = defaultdict(set)
    for f1, f2, dt, t in heard.tolist():
        for a, b, c in _GIVE:
            for k, tr in table.get((f1 + a, f2 + b, dt + c), ()):
                votes[(t - tr) // 2].add(k)
    if not votes:
        return 0, None
    best = max(votes, key=lambda o: len(votes[o] | votes.get(o + 1, set())))
    count = len(votes[best] | votes.get(best + 1, set()))
    return count, round(best * 2 * HOP / SR, 3)
