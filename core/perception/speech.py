#!/usr/bin/env python3
"""Speech: what hearing measures of spoken words and voices, and matching it
against what was taught.

No model anywhere. Words and voices are TAUGHT: an example of a word being said,
an example of a person speaking. Each is kept as a memory (teaching is memory),
and heard speech is matched against those examples. The measurements are
classical: the speech band's cepstrum (MFCCs over 100-3800 Hz, the band speech
is understood in, so a telephone line and a studio read alike), and the vowel
resonances (formants, measured by Praat's Burg method) scaled to the speaker's
own vowel space. Where speech is, hearing decides (`_extent`), for a word
taught and a word heard alike.

A NAME IS GIVEN ONLY WHEN IT CLEARLY WINS. The best match must be at most
`RATIO` of the distance to the best match of anything else, as a known image is
recognised only when its best descriptor match clearly beats the second. What
is not clearly one taught word is reported as unknown, never guessed.

Measured on real recordings of six speakers (FSDD digits, 0-7 taught, 8 and 9
never), each presented as a live buffer would present it -- with room quiet
around it, at the recording's own floor or 15 dB below it:

    taught examples    alone: named / wrong / untaught named
    5 per word         71-73% / 0.3-0.8% / 0-3.1%
    10 per word        75-77% / 0-0.5%   / 0-2.1%
                       in phrases of three words (720 words):
    5 per word         67-70% / 0.3-0.8% / 2.5-7.4%
    10 per word        68-75% / 0.3-0.5% / 0.8-2.5%

An untaught word that sounds like a taught one is heard as it: "nine", never
taught, was named "five", its nearest, at ratios just inside the cut. No test
on distance alone separates it -- it lies as near "five" as the "five"s taught
lie to one another. Teaching the word is what separates it: a taught "nine" is
a rival the ratio test weighs.

Pure functions. No substrate imports beyond the hearing describer.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import scipy.fft

from . import hearing

SR = hearing.SR
#: The band speech is understood in. A telephone line carries 300-3400 Hz and
#: every word on it is understood; measuring only this band means a word taught
#: over one channel is recognised over another.
SPEECH_BAND = (100.0, 3800.0)
_NFFT, _HOP, _BANDS, _CEPSTRA = 512, 220, 26, 12      # 23 ms windows every 10 ms
#: A name must beat the best OTHER name by this ratio of distances.
RATIO = 0.85
#: Fully resolved at this ratio: below it no untaught word was accepted.
_RATIO_RESOLVED = 0.70
#: At most this many taught words may sound alike enough to be handed on together: English's sets of words that
#: sound the same are two or three ("to", "two", "too").
_CLOSE_MOST = 3
_EPS = 1e-10


def _speech_bank() -> np.ndarray:
    to_mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    to_hz = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)
    edges = to_hz(np.linspace(to_mel(SPEECH_BAND[0]), to_mel(SPEECH_BAND[1]), _BANDS + 2))
    freqs = np.fft.rfftfreq(_NFFT, 1.0 / SR)
    bank = np.zeros((_BANDS, len(freqs)))
    for b in range(_BANDS):
        lo, mid, hi = edges[b:b + 3]
        bank[b] = np.clip(np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)), 0, None)
    return bank


_BANK = _speech_bank()


def _cepstrum(y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Speech-band cepstra (c1..c12) and each frame's level in dB, every 10 ms."""
    padded = np.pad(y, (_NFFT // 2, _NFFT // 2))
    if len(padded) < _NFFT:
        padded = np.pad(padded, (0, _NFFT - len(padded)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, _NFFT)[::_HOP]
    power = np.abs(np.fft.rfft(frames * np.hanning(_NFFT), axis=1)) ** 2
    cep = scipy.fft.dct(np.log(power @ _BANK.T + _EPS), type=2, norm="ortho", axis=1)[:, 1:_CEPSTRA + 1]
    return cep, 10.0 * np.log10(power.sum(axis=1) + _EPS)


def _formants(y: np.ndarray, count: int) -> np.ndarray:
    """F1 and F2 (Praat, Burg) on the same 10 ms grid, in the speaker's own
    vowel space: log-frequency, standardised over the utterance (Lobanov), so a
    child's and a man's "ee" land in the same place."""
    import parselmouth
    sound = parselmouth.Sound(y.astype(np.float64), sampling_frequency=SR)
    formant = sound.to_formant_burg(time_step=_HOP / SR, max_number_of_formants=5,
                                    maximum_formant=5500.0)
    times = formant.xs()
    values = np.array([[formant.get_value_at_time(k, t) for k in (1, 2)] for t in times])
    if not len(values) or not np.isfinite(values).any():
        return np.zeros((count, 2))
    values = np.where(np.isfinite(values), values, np.nanmedian(values, axis=0))
    logs = np.log(np.maximum(values, 50.0))
    pick = np.linspace(0, len(logs) - 1, count).round().astype(int)
    return _running_standardise(logs[pick])


#: Normalisation runs over a second of speech around each frame. A word said
#: alone and the same word said in a phrase then measure alike; normalised over
#: the whole stretch, a word's frames moved with whatever else was said beside
#: it, and in running speech four taught words in five went unrecognised.
_RUNNING = 100


def _running_mean(x: np.ndarray, width: int = _RUNNING) -> np.ndarray:
    """Each frame's mean over the `width` frames centred on it (fewer at the
    edges and in a stretch shorter than `width`, where it is the stretch's own)."""
    csum = np.concatenate([np.zeros((1, x.shape[1])), np.cumsum(x, axis=0)])
    idx = np.arange(len(x))
    lo = np.clip(idx - width // 2, 0, len(x))
    hi = np.clip(idx + width // 2 + 1, 0, len(x))
    return (csum[hi] - csum[lo]) / (hi - lo)[:, None]


def _running_standardise(x: np.ndarray) -> np.ndarray:
    mean = _running_mean(x)
    spread = np.sqrt(np.maximum(_running_mean((x - mean) ** 2), 0.0))
    return (x - mean) / (spread + 1e-6)


def _extent(y: np.ndarray) -> Tuple[int, int, np.ndarray]:
    """Where speech is in a stretch, as hearing hears it: the frames (on the
    10 ms grid) from the start of the first sound hearing segments the stretch
    into to the end of the last, and which of them are inside a sound. The rest
    are pauses. A word taught and a word heard are both cut by this one rule, so
    the quiet tail of a word hearing does not hear (the "s" of "six" in a noisy
    room) is missing from both or from neither."""
    spans, _ground = hearing.segment(hearing._levels(y))
    at = np.arange(len(y) // _HOP + 1) * _HOP / hearing.HOP
    inside = np.zeros(len(at), dtype=bool)
    for first, last in spans:
        inside |= (at >= first) & (at <= last)
    heard = np.flatnonzero(inside)
    if not len(heard):
        return 0, 0, inside[:0]
    return int(heard[0]), int(heard[-1]) + 1, inside[heard[0]:heard[-1] + 1]


def _measure(y: np.ndarray, cep: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Frames `lo`..`hi` of a stretch measured on their own, as if nothing were
    said around them: the channel is removed and the vowel space is found over
    these frames alone."""
    cep = cep[lo:hi]
    if len(cep) < 3:
        return np.zeros((0, 2 * _CEPSTRA + 2), dtype=np.float32)
    cep = cep - _running_mean(cep)
    delta = np.gradient(cep, axis=0)
    return np.concatenate([cep, delta, _formants(y[lo * _HOP:hi * _HOP], len(cep))],
                          axis=1).astype(np.float32)


def rises_from_a_room(y: np.ndarray) -> bool:
    """Whether anything in a recording rises above a room it can be heard
    resting in (`hearing.segment` found a ground). A recording that never rests
    -- a hiss filling it, a hum -- holds nothing a word or a voice could be told
    apart from. Taught as a word, room hiss lay near the middle of every other
    word's measurements and was then heard in speech and in a submarine's ping."""
    _spans, ground = hearing.segment(hearing._levels(np.asarray(y, dtype=np.float64)))
    return ground is not None


def word_features(y: np.ndarray) -> np.ndarray:
    """What a stretch of speech is like, frame by frame, for matching words: the
    speech-band cepstrum with the channel removed (a running mean over a second
    around each frame), its rate of change, and the vowel resonances in the
    speaker's own local vowel space. Only the frames `_extent` finds speech in:
    the quiet around it is not part of any word."""
    y = np.asarray(y, dtype=np.float64)
    lo, hi, _inside = _extent(y)
    return _measure(y, _cepstrum(y)[0], lo, hi)


def voice_frames(y: np.ndarray) -> np.ndarray:
    """What a voice is like: the speech-band cepstrum of its VOICED frames, with
    nothing removed -- the colour of the voice is exactly what the channel mean
    would take away. Voicing is hearing's own pitch tracker's."""
    y = np.asarray(y, dtype=np.float64)
    cep, _level = _cepstrum(y)
    _f0, ap = hearing.yin(hearing._frames(y, hearing.PITCH_FRAME))
    at_cep = np.arange(len(cep)) * _HOP / SR
    at_pitch = np.arange(len(ap)) * hearing.HOP / SR
    voiced = np.interp(at_cep, at_pitch, (ap < hearing._PERIODIC_AP).astype(float)) >= 0.5
    return cep[voiced].astype(np.float32)


# --- matching ------------------------------------------------------------------

def warp(a: np.ndarray, b: np.ndarray) -> float:
    """How far apart two stretches are, allowing either to be said faster: the
    symmetric dynamic time warping distance (Sakoe and Chiba), diagonal steps
    weighing a cell twice, so every path weighs len(a) + len(b) and the cost is
    normalised by it. Each row is one vector step: within a row a chain of
    horizontal steps is a running minimum over prefix sums."""
    n, m = len(a), len(b)
    cost = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    prev = None
    for i in range(n):
        entry = np.full(m, np.inf)
        if i == 0:
            entry[0] = 2 * cost[0, 0]
        else:
            entry[1:] = prev[:-1] + 2 * cost[i, 1:]
            entry = np.minimum(entry, prev + cost[i])
        run = np.cumsum(cost[i])
        prev = run + np.minimum.accumulate(entry - run)
    return float(prev[-1] / (n + m))


#: A word said in running speech lasts between half and twice as long as the
#: example it was taught from.
_TEMPO = (0.5, 2.0)


def _decode(heard: np.ndarray, pauses: np.ndarray, examples: Sequence[np.ndarray]
            ) -> List[Tuple[int, int]]:
    """How a stretch of speech divides into words: the spans (first frame, last
    frame) of the one sequence of taught examples, said one after another with
    pauses between them, that together lie nearest the whole stretch.

    One pass over the stretch (Vintsyuk; Bridle; Ney's one-stage algorithm).
    Every frame of every example is a state. At each heard frame a state is
    reached from itself, the frame before, or the frame two before (so an
    example may be said up to twice as fast, and slower), and the first frame of
    every example is reached from the best way of ending the stretch so far,
    whether with a word or with a pause. Each heard frame is paid for exactly
    once, by the example frame it is matched to, so every division of the
    stretch is weighed on the same frames. A pause costs nothing and may only
    be where hearing hears no sound."""
    lengths = np.array([len(e) for e in examples])
    frames = np.vstack(examples).astype(np.float64)
    pos = np.concatenate([np.arange(n) for n in lengths])
    of = np.repeat(np.arange(len(examples)), lengths)
    own = lengths[of]
    last = pos == own - 1
    everything = np.arange(len(frames))
    cost = np.full(len(frames), np.inf)
    start = np.zeros(len(frames), dtype=int)
    ended = np.full(len(heard) + 1, np.inf)    # best way of ending before frame t
    ended[0] = 0.0
    how: List[Optional[Tuple[int, int]]] = [None] * (len(heard) + 1)
    for t in range(len(heard)):
        near = np.sqrt(((frames - heard[t]) ** 2).sum(axis=1))
        one = np.full(len(frames), np.inf)
        one[1:] = cost[:-1]
        one[pos < 1] = np.inf
        two = np.full(len(frames), np.inf)
        two[2:] = cost[:-2]
        two[pos < 2] = np.inf
        enter = np.where(pos == 0, ended[t], np.inf)
        choice = np.stack([cost, one, two, enter]).argmin(axis=0)
        came = np.stack([cost, one, two, enter])[choice, everything]
        begun = np.stack([start, np.concatenate([[0], start[:-1]]),
                          np.concatenate([[0, 0], start[:-2]]), np.full(len(frames), t)])
        start = begun[choice, everything]
        cost = came + near
        said = t - start + 1
        ends = np.where(last & (said >= _TEMPO[0] * own) & (said <= _TEMPO[1] * own), cost, np.inf)
        best = int(ends.argmin())
        pause = ended[t] if pauses[t] else np.inf
        if ends[best] < pause:
            ended[t + 1], how[t + 1] = ends[best], (int(start[best]), t)
        else:
            ended[t + 1] = pause
    if not np.isfinite(ended[-1]):
        return []
    spans: List[Tuple[int, int]] = []
    t = len(heard)
    while t > 0:
        if how[t] is None:
            t -= 1
        else:
            first, last_frame = how[t]
            spans.append((first, last_frame))
            t = first
    return spans[::-1]


def _standing(ratio: float) -> float:
    """How clearly a name won, 0 at the cut and 1 when fully resolved."""
    return float(np.clip((RATIO - ratio) / (RATIO - _RATIO_RESOLVED), 0.0, 1.0))


def _distances(heard: np.ndarray, taught: Dict[str, Sequence[np.ndarray]]) -> Dict[str, float]:
    """How far a stretch of speech lies from each taught word: its nearest taught example's distance."""
    return {w: min(warp(heard, e) for e in examples) for w, examples in taught.items() if examples}


def _named(distance: Dict[str, float]) -> Optional[Dict[str, Any]]:
    """The taught word the distances clearly name, or None (the ratio test)."""
    order = sorted(distance, key=distance.get)
    ratio = distance[order[0]] / max(distance[order[1]], _EPS)
    if ratio > RATIO:
        return None
    return {"word": order[0], "distance": round(distance[order[0]], 3),
            "ratio": round(ratio, 3), "standing": round(_standing(ratio), 3)}


def _alike(distance: Dict[str, float]) -> List[str]:
    """The taught words a stretch the ratio test could not name sounds like, nearest first: every word as near as
    the ratio test cannot separate from the nearest. Words that sound alike ("to", "two", "too") lie as near one
    another as their own examples do, and no distance tells them apart; a person tells them apart by which one
    makes sense of what is said, so they are handed on for the listener to choose among
    (`derived_reader.heard_which`). More than `_CLOSE_MOST` is not a word sounding like another but a sound like
    many, and is handed on as nothing."""
    order = sorted(distance, key=distance.get)
    close = [w for w in order if distance[w] <= distance[order[0]] / RATIO]
    return close if 2 <= len(close) <= _CLOSE_MOST else []


def name_word(heard: np.ndarray, taught: Dict[str, Sequence[np.ndarray]]
              ) -> Optional[Dict[str, Any]]:
    """Which taught word a stretch of speech is, or None when none clearly is.
    Each word's distance is its nearest taught example's."""
    if len(taught) < 2:
        # A ratio needs a rival. With one word taught there is nothing to beat,
        # and a distance alone accepted a fifth of the words never taught.
        return None
    return _named(_distances(heard, taught))


def find_words(y: np.ndarray, taught: Dict[str, Sequence[np.ndarray]]) -> List[Dict[str, Any]]:
    """What was said in a stretch of speech, in order: every span the stretch
    divides into, each with when it starts and ends (seconds into the stretch)
    and the taught word it clearly is, or `word` None when it is speech but not
    clearly any taught word. A span that sounds like a few taught words alike
    and clearly none of them carries them as `close` (`_alike`).

    The stretch is divided into words by `_decode`, with pauses wherever hearing
    hears no sound. Each span is then measured on its own (`_measure`), exactly
    as a word said alone is, and named by `name_word`: the same test a word said
    alone passes. Measured together with its neighbours, a word's frames moved
    with whatever was said beside it."""
    examples = [e for w in taught for e in taught[w] if len(e) >= 3]
    y = np.asarray(y, dtype=np.float64)
    lo, hi, inside = _extent(y)
    cep = _cepstrum(y)[0]
    heard = _measure(y, cep, lo, hi)
    if len(taught) < 2 or len(heard) < 3 or not examples:
        return []
    spans: List[Dict[str, Any]] = []
    for first, last in _decode(heard, ~inside, examples):
        alone = _measure(y, cep, lo + first, lo + last + 1)
        distance = _distances(alone, taught) if len(alone) >= 3 else {}
        named = _named(distance) if distance else None
        span = {"word": None, **(named or {}),
                "starts_at": round((lo + first) * _HOP / SR, 3),
                "ends_at": round((lo + last + 1) * _HOP / SR, 3)}
        close = _alike(distance) if distance and not named else []
        if close:
            span["close"] = close
        spans.append(span)
    return spans


#: At most this many ways a stretch of speech can be heard, when words in it sound alike: past it the listener is
#: not asked to choose, and what was said is not all understood.
_HEARD_WAYS = 27


def heard_texts(spans: Sequence[Dict[str, Any]]) -> List[str]:
    """Every way what was said can be heard as text, when words in it sound like other taught words: each span
    named as the word it clearly is, or as each of the words it sounds alike to (`close`), with "..." where it is
    speech but no taught word. One way when nothing sounded alike; none past `_HEARD_WAYS`."""
    import itertools
    options = [[span["word"]] if span.get("word") else list(span.get("close") or ["..."]) for span in spans]
    ways = 1
    for option in options:
        ways *= len(option)
    if ways > _HEARD_WAYS:
        return []
    return list(dict.fromkeys(said_text([{"word": w} for w in combo]) for combo in itertools.product(*options)))


def said_text(spans: Sequence[Dict[str, Any]]) -> str:
    """What was said, as text: the words named, in order, with "..." where
    something was said that is not a taught word."""
    out: List[str] = []
    for span in spans:
        word = span.get("word") or "..."
        if not (word == "..." and out and out[-1] == "..."):
            out.append(word)
    return " ".join(out)


def _nearness(heard: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """For each heard frame, how far the nearest of `frames` is."""
    return np.sqrt(((heard[:, None, :] - frames[None, :, :]) ** 2).sum(-1)).min(axis=1)


#: A sound is judged a voice or not on at least this many voiced frames (0.1 s).
_VOICED_ENOUGH = 10
#: WHOSE voice is judged on at least 0.4 s of voiced speech. Measured over all
#: twenty trios of three people taught, by how much was heard voiced: under
#: 0.4 s, 14% of strangers' stretches were named as a taught person and 10
#: taught people's as someone else; from 0.4 s on, about 1% of strangers' and
#: none wrongly, in every band up to several seconds.
_WHOSE_ENOUGH = 40


def voice_reach(voices: Dict[str, Sequence[np.ndarray]]) -> Optional[Tuple[float, float]]:
    """How near the voices taught lie to one another: for every taught example,
    how far its voiced frames lie from the voices of everyone ELSE, as the
    farthest and nearest of those distances. None when fewer than two people's
    voices were taught, since a voice then has no other voice to lie near."""
    people = [p for p, examples in voices.items() if any(len(e) for e in examples)]
    if len(people) < 2:
        return None
    lying = []
    for person in people:
        others = np.vstack([e for q in people if q != person for e in voices[q] if len(e)])
        lying.extend(float(_nearness(e, others).mean())
                     for e in voices[person] if len(e) >= _VOICED_ENOUGH)
    if not lying:
        return None
    return max(lying), min(lying)


def judge_voice(heard: np.ndarray, voices: Dict[str, Sequence[np.ndarray]],
                reach: Optional[Tuple[float, float]] = None) -> Optional[Dict[str, Any]]:
    """Whether a sound is a voice: its voiced frames lie as near the voices
    taught as those lie to one another (`voice_reach`). No threshold is chosen;
    the voices taught set it. `support` is fully resolved when the sound lies as
    near as the nearest taught voice does (or, for "not a voice", as far beyond
    the reach as that).

    Measured with three people taught: stretches of three people never taught
    lay at 3.75-4.83 against a reach of 5.76, and every one of the thirteen
    system sounds with voiced frames at 6.76 or more; of 113 single spoken words
    judged, 111 were voices. Machine voices (macOS speech) mostly fall inside,
    a whispered one far out. None when fewer than two voices are taught or too
    little of the sound was voiced to judge."""
    reach = reach if reach is not None else voice_reach(voices)
    if reach is None or len(heard) < _VOICED_ENOUGH:
        return None
    farthest, nearest = reach
    pooled = np.vstack([e for examples in voices.values() for e in examples if len(e)])
    lies = float(_nearness(heard, pooled).mean())
    return {"voice": lies <= farthest, "lies": round(lies, 3),
            "support": round(float(np.clip(abs(farthest - lies) / max(farthest - nearest, _EPS),
                                           0.0, 1.0)), 3)}


#: A PERSON is named only when their voice beats the next by this ratio --
#: stricter than a word, as naming a known individual is stricter than naming a
#: kind (sight's instance recognition likewise). Measured over all twenty trios
#: of three people taught from six, on stretches of three to six words: at 0.80,
#: 79% of taught people's speech was named, none wrongly, and 0.9% of strangers'
#: speech was named as a taught person; at the 0.85 words use, 5.9% was.
WHOSE_RATIO = 0.80
#: Fully resolved at this ratio: below it no stranger was named.
_WHOSE_RESOLVED = 0.70


def whose_voice(heard: np.ndarray, voices: Dict[str, Sequence[np.ndarray]]
                ) -> Optional[Dict[str, Any]]:
    """Whose voice a stretch of speech is, among the voices taught.

    Each voiced frame is matched to its nearest frame of each taught voice; the
    voice whose frames lie nearest on average is named only if it clearly beats
    the next (`WHOSE_RATIO`). Returns None when it cannot be judged -- fewer
    than two voices taught, or less than `_WHOSE_ENOUGH` voiced frames heard;
    otherwise `person`, which is None when no taught voice clearly won. The more
    voices taught, the fewer strangers pass as one of them: with two people
    taught, 9 stranger stretches in 36 were named at the words' ratio."""
    people = {p: np.vstack([e for e in examples if len(e)])
              for p, examples in voices.items() if any(len(e) for e in examples)}
    if len(people) < 2 or len(heard) < _WHOSE_ENOUGH:
        return None
    score = {p: float(_nearness(heard, frames).mean()) for p, frames in people.items()}
    order = sorted(score, key=score.get)
    ratio = score[order[0]] / max(score[order[1]], _EPS)
    if ratio > WHOSE_RATIO:
        return {"person": None, "ratio": round(ratio, 3)}
    return {"person": order[0], "distance": round(score[order[0]], 3), "ratio": round(ratio, 3),
            "standing": round(float(np.clip((WHOSE_RATIO - ratio) / (WHOSE_RATIO - _WHOSE_RESOLVED),
                                            0.0, 1.0)), 3)}


# --- a recording heard, as far as speech was taught -----------------------------

def recognise(y: np.ndarray, sounds: Sequence[Dict[str, Any]],
         words: Dict[str, Sequence[np.ndarray]], voices: Dict[str, Sequence[np.ndarray]],
         reach: Optional[Tuple[float, float]]) -> Dict[str, Any]:
    """What was said in a recording, which of its sounds are voices, and whose
    voice they were, as far as the words and voices taught let it be heard.
    Nothing is heard as speech that was not taught.

    `said`: the taught words named, each with its support and when it was said,
    and `heard_text`, what was said as text ("..." where something was said
    that is not a taught word). `voices`: per sound (the same list as `sounds`,
    each with its `start` and `duration`), whether it is a voice
    (`judge_voice`), or None where too little was voiced to judge. `spoken_by`:
    whose voice, judged over every sound that is one, since a single word is
    too little to know a person by (`whose_voice`); `whose_judged` says it was
    judged, so "no taught voice clearly won" is told apart from "too little to
    say"."""
    out: Dict[str, Any] = {"voices": [None] * len(sounds)}
    if len(words) >= 2:
        spans = find_words(y, words)
        said = [{"word": w["word"], "support": w["standing"],
                 "starts_at": w["starts_at"], "ends_at": w["ends_at"]}
                for w in spans if w.get("word")]
        if said:
            out["said"] = said
            out["heard_text"] = said_text(spans)
        if any(w.get("close") for w in spans):
            # Words that sound alike are heard every way they can be; which was said is the listener's to choose.
            out["heard_texts"] = heard_texts(spans)
    if reach is not None:
        voiced = []
        for k, sound in enumerate(sounds):
            first = int(round(float(sound.get("start") or 0.0) * SR))
            last = first + int(round(float(sound.get("duration") or 0.0) * SR))
            frames = voice_frames(y[first:last])
            judged = judge_voice(frames, voices, reach)
            out["voices"][k] = judged
            if judged is not None and judged["voice"]:
                voiced.append(frames)
        if voiced:
            whose = whose_voice(np.vstack(voiced), voices)
            if whose is not None:
                out["whose_judged"] = True
                if whose["person"]:
                    out["spoken_by"] = {"person": whose["person"], "support": whose["standing"]}
    return out


def lesson_example(key: str, y: np.ndarray, path: str) -> np.ndarray:
    """What a lesson's recording holds to be matched against later: a word's
    measurements (`word_features`, `key` "word") or a voice's voiced frames
    (`key` "person"). Raises when nothing in it rises above the room it was
    recorded in, or too little of it was voiced to know a voice by."""
    if not rises_from_a_room(y):
        raise ValueError(f"nothing in {path} rose above the room it was recorded in, "
                         f"so no {'word' if key == 'word' else 'voice'} can be told "
                         f"apart in it")
    if key == "word":
        example = word_features(y)
        if len(example) < 3:
            raise ValueError(f"nothing in {path} was heard said")
        return example
    example = voice_frames(y)
    if len(example) < _VOICED_ENOUGH:
        raise ValueError(f"too little in {path} was voiced to know a voice by "
                         f"({len(example)} voiced frame(s))")
    return example


def pack(features: np.ndarray) -> bytes:
    """A measured example as bytes: a numpy archive, which the media store
    knows by its first bytes. A hearing's trace keeps its example under the
    same name (`hearing.trace_bytes`), so either reads back with `unpack`."""
    buf = io.BytesIO()
    np.savez_compressed(buf, example=np.asarray(features, dtype=np.float32))
    return buf.getvalue()


def unpack(data: bytes) -> Optional[np.ndarray]:
    """The measured example kept in an archive, or None when it keeps none."""
    with np.load(io.BytesIO(data)) as archive:
        return np.array(archive["example"]) if "example" in archive.files else None
