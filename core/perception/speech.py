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
#: WHETHER THE EAR NAMES WORDS AT ALL (`LYRIC_SPEECH`, "on" or "off"; off unless said). Off, nothing heard is named
#: as a word, by the words taught whole or by the sounds words are made of, and a voice is still heard as one and
#: as whose. What was taught stays in memory, and teaching goes on: turned on, it is all used. Off since 2026-10-03:
#: words said by people the ear was not taught by are heard too seldom to read a sentence (SPEECH-02 to -04,
#: `docs/research/HEARING_BY_PHONES.md`).
WORDS_HEARD = __import__("os").environ.get("LYRIC_SPEECH", "off").strip().lower() in ("on", "1", "yes", "true")

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
    if WORDS_HEARD and len(words) >= 2:
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


def unpack_phones(data: bytes) -> Optional[Tuple[np.ndarray, List[str]]]:
    """The frames a lesson of sounds kept, with each frame's phone, or None when the archive keeps none."""
    with np.load(io.BytesIO(data)) as archive:
        if "example" not in archive.files or "example_phones" not in archive.files:
            return None
        return np.array(archive["example"]), [str(p) for p in archive["example_phones"]]


# --- hearing words by the sounds they are made of ------------------------------
#
# A whole word does not carry from one voice to another: taught a word from sixty speakers, the ear finds it the
# nearest about four times in ten when someone else says it (SPEECH-02). A word is made of a few dozen sounds, and
# every speaker says each thousands of times. So the SOUNDS are taught: a hearing told which phone is said when
# (`phones_example`), whose frames are kept. A heard frame sounds like the phones its nearest taught frames are (k
# nearest neighbours; Fix and Hodges 1951), and a stretch is heard as the words whose sounds, in the order a
# pronouncing dictionary gives them, fit it best (Viterbi 1967; the one-pass search `_decode` runs over whole-word
# examples). Nothing is trained. Measured offline on speakers never taught by (SPEECH-03): words cut from their
# sentences fit best 61.8% of the time of 100 lesson words, and are among the best five 85.0%.

#: Frames either side measured with each frame, every third: a sound is known by how it is come to and left. With
#: 60 ms either side 45.2% of frames are given their phone, with none 34.7% (SPEECH-03).
PHONE_REACH = 6
#: A phone lasts at least this many frames: none of 192,830 aligned in LibriSpeech dev-clean is shorter. With no
#: floor, a stretch hopped through a word's sounds a frame at a time on whatever fit.
SHORTEST_PHONE = 3
#: The taught frames that say what a heard frame sounds like.
PHONE_NEAREST = 25
#: At most this many frames of one phone are kept from one lesson, spread over where it is said. Every heard frame is
#: compared with every taught one: twenty a lesson made a million from dev-clean, ten seconds to hear a sentence of
#: seven. Each halving of the taught frames costs about two points of frames given their phone (SPEECH-03).
PHONE_FRAMES_KEPT = 10
#: Quiet, as a sound to tell apart from the others: where a lesson says no phone is said.
QUIET = "sil"


def plain_phone(phone: str) -> str:
    """A phone without its stress mark: "AH0" and "AH1" are one sound to tell apart from the others."""
    return str(phone).strip().upper().rstrip("012")


#: The band the sounds are heard over. Telling "s" from "sh" and "f" from "th" needs what is above the telephone band
#: words are matched in (`SPEECH_BAND`): frames given their phone 45.0% at 3800 Hz, 47.0% at 7600; the word that fits
#: best is the word said 47.8% and 51.9% of the time, a name at 0.5 right 88.8% and 93.5% (SPEECH-03).
PHONE_BAND = (100.0, 7600.0)


def _phone_bank() -> np.ndarray:
    to_mel = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    to_hz = lambda m: 700.0 * (10 ** (m / 2595.0) - 1.0)
    edges = to_hz(np.linspace(to_mel(PHONE_BAND[0]), to_mel(PHONE_BAND[1]), _BANDS + 2))
    freqs = np.fft.rfftfreq(_NFFT, 1.0 / SR)
    bank = np.zeros((_BANDS, len(freqs)))
    for b in range(_BANDS):
        lo, mid, hi = edges[b:b + 3]
        bank[b] = np.clip(np.minimum((freqs - lo) / (mid - lo), (hi - freqs) / (hi - mid)), 0, None)
    return bank


_PHONE_BANK = _phone_bank()


def band_energies(y: np.ndarray) -> np.ndarray:
    """The log energy in each band of `PHONE_BAND`, every 10 ms."""
    padded = np.pad(np.asarray(y, dtype=np.float64), (_NFFT // 2, _NFFT // 2))
    if len(padded) < _NFFT:
        padded = np.pad(padded, (0, _NFFT - len(padded)))
    frames = np.lib.stride_tricks.sliding_window_view(padded, _NFFT)[::_HOP]
    power = np.abs(np.fft.rfft(frames * np.hanning(_NFFT), axis=1)) ** 2
    return np.log(power @ _PHONE_BANK.T + _EPS).astype(np.float32)


def phone_frames(bands: np.ndarray) -> np.ndarray:
    """Each frame as it is compared with the taught sounds: its band energies less the channel (a running second's
    mean, as a word is measured), their change, and the same of the frames around it out to `PHONE_REACH` either
    side, every third."""
    x = bands - _running_mean(bands)
    x = np.concatenate([x, np.gradient(x, axis=0)], axis=1) if len(x) > 1 else np.concatenate([x, 0 * x], axis=1)
    pad = np.pad(x, ((PHONE_REACH, PHONE_REACH), (0, 0)), mode="edge")
    step = max(PHONE_REACH // 2, 1)
    return np.concatenate([pad[k:k + len(x)] for k in range(0, 2 * PHONE_REACH + 1, step)],
                          axis=1).astype(np.float32)


def phones_told(told: str) -> List[Tuple[str, float, float]]:
    """A lesson's phones as told: "M 0.21 0.29|IH1 0.29 0.33|..." is `[("M", 0.21, 0.29), ("IH", 0.29, 0.33), ...]`,
    each phone with when it starts and ends, in seconds."""
    out = []
    for part in str(told).split("|"):
        bits = part.split()
        if len(bits) == 3:
            out.append((plain_phone(bits[0]), float(bits[1]), float(bits[2])))
    return out


def phones_example(y: np.ndarray, told: str) -> Tuple[np.ndarray, List[str]]:
    """What a lesson of sounds keeps: frames of each phone said in it, as `phone_frames` measures them, at most
    `PHONE_FRAMES_KEPT` of a phone spread evenly over where it is said, and as many of the quiet where no phone is
    said; with each frame's phone. Raises when nothing in it can be kept."""
    said = phones_told(told)
    if not said:
        raise ValueError("a lesson of sounds says which phone is said when ('M 0.21 0.29|IH 0.29 0.33|...')")
    frames = phone_frames(band_energies(y))
    labels = np.array([QUIET] * len(frames), dtype=object)
    for phone, start, end in said:
        first, last = int(np.ceil(start * SR / _HOP)), int(end * SR / _HOP)
        labels[max(first, 0):min(last + 1, len(labels))] = phone
    kept, names = [], []
    for phone in sorted(set(labels)):
        at = np.flatnonzero(labels == phone)
        pick = at[np.unique(np.linspace(0, len(at) - 1, min(len(at), PHONE_FRAMES_KEPT)).round().astype(int))]
        kept.append(frames[pick])
        names += [phone] * len(pick)
    if not names:
        raise ValueError("nothing in the recording falls where the lesson says its phones are")
    return np.concatenate(kept).astype(np.float16), names


class PhoneLibrary:
    """The taught sounds as hearing compares heard frames with them: every frame kept, with its phone. Grows as
    lessons arrive, without copying what it holds each time."""

    def __init__(self):
        self.phones: List[str] = []
        self.index: Dict[str, int] = {}
        self._frames = np.zeros((0, 0), dtype=np.float32)
        self._ids = np.zeros(0, dtype=np.int32)
        self._squares = np.zeros(0, dtype=np.float32)
        self.size = 0

    def add(self, frames: np.ndarray, labels: Sequence[str]) -> None:
        if not len(labels):
            return
        for phone in labels:
            if phone not in self.index:
                self.index[phone] = len(self.phones)
                self.phones.append(phone)
        frames = np.asarray(frames, dtype=np.float32)
        if self._frames.shape[1] != frames.shape[1]:
            self._frames = np.zeros((0, frames.shape[1]), dtype=np.float32)
        need = self.size + len(frames)
        if need > len(self._frames):
            grown = max(need, 2 * len(self._frames), 1024)
            frames_now = np.zeros((grown, frames.shape[1]), dtype=np.float32)
            frames_now[:self.size] = self._frames[:self.size]
            ids_now = np.zeros(grown, dtype=np.int32)
            ids_now[:self.size] = self._ids[:self.size]
            squares_now = np.zeros(grown, dtype=np.float32)
            squares_now[:self.size] = self._squares[:self.size]
            self._frames, self._ids, self._squares = frames_now, ids_now, squares_now
        self._frames[self.size:need] = frames
        self._ids[self.size:need] = [self.index[p] for p in labels]
        self._squares[self.size:need] = (frames ** 2).sum(axis=1)
        self.size = need

    def sounds_like(self, frames: np.ndarray) -> np.ndarray:
        """For each heard frame, the log of the share of its `PHONE_NEAREST` nearest taught frames each phone holds,
        with half a frame for every phone so none is impossible."""
        X, ids, squares = self._frames[:self.size], self._ids[:self.size], self._squares[:self.size]
        k = min(PHONE_NEAREST, self.size - 1)
        out = np.zeros((len(frames), len(self.phones)), dtype=np.float32)
        # Sixty-four heard frames at a time: against a million taught, each block's distances are a quarter of a
        # gigabyte, and 256 at a time held the hearing process at nine.
        for lo in range(0, len(frames), 64):
            q = np.asarray(frames[lo:lo + 64], dtype=np.float32)
            d = (q ** 2).sum(axis=1)[:, None] + squares[None, :] - 2.0 * q @ X.T
            near = ids[np.argpartition(d, k, axis=1)[:, :k]]
            np.add.at(out, (np.arange(lo, lo + len(q))[:, None], near), 1.0)
        # The share itself, not the share over how common each phone is (Bourlard and Morgan 1994): divided so,
        # the best fit was the word said 34.2% of the time against 51.9% (SPEECH-03, `offline_margins.py`).
        return np.log((out + 0.5) / (k + 0.5 * len(self.phones)))


class SaidAs:
    """How each word is said, as the phones of each way of saying it, made into the states a stretch passes through
    when heard as words one after another: each phone `SHORTEST_PHONE` states long, only its last stayed in."""

    def __init__(self, said_as: Dict[str, Sequence[str]], used: Dict[str, int], library: PhoneLibrary):
        phone_of, word_of, stays, first, last = [], [], [], [], []
        self.ways: Dict[str, set] = {}
        for word in sorted(said_as):
            for way in sorted({tuple(plain_phone(p) for p in str(w).split()) for w in said_as[word]}):
                if not way or any(p not in library.index for p in way):
                    continue
                self.ways.setdefault(word, set()).add(way)
                first.append(len(phone_of))
                for p in way:
                    phone_of += [library.index[p]] * SHORTEST_PHONE
                    stays += [False] * (SHORTEST_PHONE - 1) + [True]
                    word_of += [word] * SHORTEST_PHONE
                last.append(len(phone_of) - 1)
        self.words = sorted(self.ways)
        self.quiet = len(phone_of)
        self.phone_of = np.array(phone_of + [library.index.get(QUIET, 0)], dtype=np.int32)
        self.word_of = word_of
        self.stays = np.array(stays + [True])
        self.is_first = np.zeros(self.quiet + 1, dtype=bool)
        self.is_first[first] = True
        self.is_last = np.zeros(self.quiet + 1, dtype=bool)
        self.is_last[last] = True
        total = sum(max(int(used.get(w, 0)), 0) + 1 for w in self.words) or 1
        share = {w: float(np.log((max(int(used.get(w, 0)), 0) + 1) / total)) for w in self.words}
        self.entry = np.array([share[w] for w in word_of] + [0.0], dtype=np.float64)
        self.word_index = {w: i for i, w in enumerate(self.words)}
        self.state_word = np.array([self.word_index[w] for w in word_of] + [-1])

    def alike(self, a: str, b: str) -> bool:
        """Whether two words are said the same way: then no sound tells them apart."""
        return bool(self.ways.get(a, set()) & self.ways.get(b, set()))


#: How much a word's share of real text weighs against its sounds, where a stretch is divided into words. With
#: none, the search broke words into short ones that fit a little better; with too much, it left words out. 2.0 is
#: where words put in and left out came nearest (SPEECH-03: 34.2% of the words in 60 sentences, against 27.6%).
PHONE_USAGE_WEIGHT = 2.0


def _phone_decode(logp: np.ndarray, said: SaidAs, pauses: np.ndarray) -> List[Tuple[int, int, str]]:
    """How a stretch divides into words, by their sounds: the spans `(first frame, last frame, word)` of the one
    sequence of words, quiet between them where hearing hears none, that fits the whole stretch best. A word is
    entered at the cost of its share of real text (`PHONE_USAGE_WEIGHT`)."""
    n = said.quiet + 1
    everything = np.arange(n)
    score = np.full(n, -np.inf)
    begun = np.zeros(n, dtype=int)
    ended = np.full(len(logp) + 1, -np.inf)
    ended[0] = 0.0
    how: List[Optional[Tuple[int, str]]] = [None] * (len(logp) + 1)
    for t in range(len(logp)):
        on = np.concatenate([[-np.inf], score[:-1]])
        on[said.is_first] = -np.inf
        on[said.quiet] = -np.inf
        enter = np.where(said.is_first, ended[t] + PHONE_USAGE_WEIGHT * said.entry, -np.inf)
        enter[said.quiet] = ended[t] if pauses[t] else -np.inf
        options = np.stack([np.where(said.stays, score, -np.inf), on, enter])
        choice = options.argmax(axis=0)
        began = np.stack([begun, np.concatenate([[0], begun[:-1]]), np.full(n, t)])
        begun = began[choice, everything]
        score = options[choice, everything] + logp[t, said.phone_of]
        ends = np.where(said.is_last, score, -np.inf)
        best = int(ends.argmax())
        if ends[best] >= score[said.quiet]:
            ended[t + 1], how[t + 1] = ends[best], (int(begun[best]), said.word_of[best])
        else:
            ended[t + 1] = score[said.quiet]
    spans: List[Tuple[int, int, str]] = []
    t = len(logp)
    while t > 0:
        if how[t] is None:
            t -= 1
        else:
            first, word = how[t]
            spans.append((first, t - 1, word))
            t = first
    return spans[::-1]


def _phone_fits(logp: np.ndarray, said: SaidAs) -> np.ndarray:
    """How well a stretch fits each word, said whole from its first frame to its last, by the best way of giving its
    phones the frames in order: one value a word (`said.words`), the best of its ways of being said."""
    n = said.quiet + 1
    score = np.where(said.is_first, logp[0, said.phone_of], -np.inf)
    score[said.quiet] = -np.inf
    for t in range(1, len(logp)):
        on = np.concatenate([[-np.inf], score[:-1]])
        on[said.is_first] = -np.inf
        score = np.maximum(np.where(said.stays, score, -np.inf), on) + logp[t, said.phone_of]
    ends = np.where(said.is_last, score, -np.inf)
    out = np.full(len(said.words), -np.inf)
    np.maximum.at(out, said.state_word[:n - 1][said.is_last[:n - 1]], ends[:n - 1][said.is_last[:n - 1]])
    return out


#: The words a span not clearly one word is handed on as, the best-fitting first, each said differently.
PHONE_CANDIDATES = 3

#: A span is named when its best word fits it better than any word said differently by at least this much, a frame
#: (the log of the share of nearest taught frames), and fully resolved at `PHONE_RESOLVED`. Measured on LibriSpeech
#: dev-other, whose speakers neither teach nor are heard elsewhere (`experiments/SPEECH-03/offline_margins.py`,
#: about 1,000 candidate words): at 0.5 a name is right 84.5% of the time (2.5% of words named); at 1.0, 5 of 5.
#: On test-clean, 88.8% and 5 of 6. NO MARGIN MAKES A NAME CERTAIN: a frame is given its phone about half the time,
#: and how far ahead the best word fits does not separate right from wrong well enough. Most words are handed to the
#: listener as the few they fit nearly as well (`close`), to choose among by which makes sense.
PHONE_CLEAR = 0.5
PHONE_RESOLVED = 1.5


def find_words_by_phones(y: np.ndarray, library: PhoneLibrary, said: SaidAs,
                         sounds: Optional[Any] = None) -> List[Dict[str, Any]]:
    """What was said in a stretch of speech, heard by its sounds, in order: every span the stretch divides into
    (`_phone_decode`), each with when it starts and ends and the word it clearly is, or `word` None with the words
    it fits nearly as well as `close`, for the listener to choose among by which makes sense. The same spans
    `find_words` gives for whole-word lessons.

    `sounds`: where how each 10 ms of the stretch sounds like each phone comes from, as a function of the stretch's
    samples (`library.index`'s phones, the log of each), when it is not the taught frames (`library.sounds_like`).
    Words, how they are said, and which is meant stay as they are."""
    y = np.asarray(y, dtype=np.float64)
    lo, hi, inside = _extent(y)
    if hi - lo < SHORTEST_PHONE or not (library.size or sounds) or not said.words:
        return []
    if sounds is not None:
        logp = np.asarray(sounds(y[lo * _HOP:hi * _HOP]), dtype=np.float32)[:hi - lo]
        if len(logp) < hi - lo:
            logp = np.concatenate([logp, np.repeat(logp[-1:], hi - lo - len(logp), axis=0)])
    else:
        # Measured over where speech is, as a word is: the channel taken off is the speech's, not the room's.
        logp = library.sounds_like(phone_frames(band_energies(y)[lo:hi]))
    spans: List[Dict[str, Any]] = []
    for first, last, _word in _phone_decode(logp, said, ~inside):
        fits = _phone_fits(logp[first:last + 1], said)
        frames = last - first + 1
        order = [said.words[i] for i in np.argsort(-fits) if np.isfinite(fits[i])]
        span: Dict[str, Any] = {"word": None, "starts_at": round((lo + first) * _HOP / SR, 3),
                                "ends_at": round((lo + last + 1) * _HOP / SR, 3)}
        if order:
            best = order[0]
            alike = [w for w in order if said.alike(w, best)]
            rival = next((w for w in order if not said.alike(w, best)), None)
            margin = ((fits[said.word_index[best]] - fits[said.word_index[rival]]) / frames
                      if rival is not None else np.inf)
            if margin >= PHONE_CLEAR and len(alike) == 1:
                span.update(word=best, margin=round(float(min(margin, 99.0)), 3),
                            standing=round(float(np.clip((margin - PHONE_CLEAR) / (PHONE_RESOLVED - PHONE_CLEAR),
                                                         0.0, 1.0)), 3))
            else:
                # NOT CLEARLY ONE WORD: the few that fit best, each said differently, with how far behind the best
                # each fits a frame, for the listener to choose among by which makes sense (`ranked_texts`).
                near, ways_seen = [], []
                for w in order:
                    if any(said.alike(w, other) for other in ways_seen):
                        continue
                    ways_seen.append(w)
                    near.append(w)
                    if len(near) == PHONE_CANDIDATES:
                        break
                span["close"] = near
                span["behind"] = [round(float((fits[said.word_index[best]] - fits[said.word_index[w]]) / frames), 3)
                                  for w in near]
        spans.append(span)
    return spans


def ranked_texts(spans: Sequence[Dict[str, Any]], most: int = _HEARD_WAYS) -> List[str]:
    """The ways a stretch heard by its sounds can be taken as text, the best-fitting first, at most `most`: each span
    its word where it was named, else each of the words it fits best (`close`), a way weighed by how far behind the
    best each of its words fits (`behind`, a frame) times the span's frames. Best first over the products, so a
    sentence of many uncertain words still hands the listener its likeliest ways instead of none."""
    import heapq
    options: List[List[Tuple[float, str]]] = []
    for span in spans:
        frames = max(1.0, (span["ends_at"] - span["starts_at"]) * SR / _HOP)
        if span.get("word"):
            options.append([(0.0, span["word"])])
        elif span.get("close"):
            options.append([(float(b) * frames, w) for w, b in zip(span["close"], span.get("behind") or
                                                                    [0.0] * len(span["close"]))])
        else:
            options.append([(0.0, "...")])
    if not options:
        return []
    start = tuple(0 for _ in options)
    heap = [(sum(o[0][0] for o in options), start)]
    seen, out = {start}, []
    while heap and len(out) < most:
        cost, pick = heapq.heappop(heap)
        out.append(said_text([{"word": options[k][i][1]} for k, i in enumerate(pick)]))
        for k in range(len(options)):
            if pick[k] + 1 < len(options[k]):
                nxt = pick[:k] + (pick[k] + 1,) + pick[k + 1:]
                if nxt not in seen:
                    seen.add(nxt)
                    heapq.heappush(heap, (cost - options[k][pick[k]][0] + options[k][pick[k] + 1][0], nxt))
    return list(dict.fromkeys(out))


def heard_by_phones(y: np.ndarray, library: PhoneLibrary, said: SaidAs,
                    sounds: Optional[Any] = None) -> Dict[str, Any]:
    """What was said in a recording, heard by its sounds, as `recognise` gives it: `said` (each word named, with its
    support and when), `heard_text`, and `heard_texts`, the likeliest ways of taking it, where words in it are not
    clearly one word (`ranked_texts`). `sounds` as `find_words_by_phones` takes it."""
    spans = find_words_by_phones(y, library, said, sounds)
    out: Dict[str, Any] = {}
    named = [{"word": s["word"], "support": s["standing"], "starts_at": s["starts_at"], "ends_at": s["ends_at"]}
             for s in spans if s.get("word")]
    if named:
        out["said"] = named
    if spans:
        out["heard_text"] = said_text(spans)
    if any(s.get("close") for s in spans):
        out["heard_texts"] = ranked_texts(spans)
    return out



# --- words found in a phone recogniser's marks ---------------------------------
#
# A trained recogniser (`phone_recogniser`) reports which sounds were said, a sharp mark for each with nothing new (its
# blank) between (connectionist temporal classification; Graves, Fernández, Gomez and Schmidhuber 2006). Read frame
# by frame as Lyric's own sounds are, its marks gave 70.4% of words in untaught speakers' sentences; read as it
# reports, 89.0% (SPEECH-05). The words, how each is said, and which was meant are Lyric's.

#: How much a word's share of real text weighs where a stretch is divided into words: with 0.5, 78.2% of words in
#: whole sentences right; with 2.0, 62.0%, words left out (SPEECH-05, `offline_sentences.py`).
MARK_USAGE_WEIGHT = 0.5
#: A span is named when its best word is at least this much likelier (log) than any word said differently, and fully
#: resolved at `MARK_RESOLVED`; a name is firm (support 0.5) halfway. Of words in untaught speakers' sentences, at 5
#: 2,223 of 2,254 named were right, at 10 all 779 (SPEECH-05, `offline_ctc.py`).
MARK_CLEAR = 5.0
MARK_RESOLVED = 15.0


class SaidInMarks:
    """How each word is said, as the recogniser's phones, and each word's share of real text."""

    def __init__(self, said_as: Dict[str, Sequence[str]], used: Dict[str, int]):
        from . import phone_recogniser as PR
        self.ways: Dict[str, set] = {}
        for word, ways in said_as.items():
            for way in ways:
                phones = [plain_phone(p) for p in str(way).split()]
                if phones and all(p in PR.INDEX for p in phones):
                    self.ways.setdefault(word, set()).add(tuple(PR.INDEX[p] for p in phones))
        self.words = sorted(self.ways)
        self.flat = [(w, seq) for w in self.words for seq in sorted(self.ways[w])]
        total = sum(max(int(used.get(w, 0)), 0) + 1 for w in self.words) or 1
        self.share = {w: float(np.log((max(int(used.get(w, 0)), 0) + 1) / total)) for w in self.words}
        self._states = None

    def alike(self, a: str, b: str) -> bool:
        return bool(self.ways.get(a, set()) & self.ways.get(b, set()))

    def states(self):
        """Every way of saying every word in the recogniser's form (blank, sound, blank, ..., blank), as one
        search's states, made once."""
        if self._states is None:
            from . import phone_recogniser as PR
            sym, word_of, first, last, skip = [], [], [], [], []
            for word, seq in self.flat:
                form = [PR.BLANK]
                for p in seq:
                    form += [p, PR.BLANK]
                start = len(sym)
                for k, s in enumerate(form):
                    sym.append(s)
                    word_of.append(word)
                    # A sound may follow the sound two states back directly, past the blank, when the two differ.
                    skip.append(k >= 2 and s != PR.BLANK and form[k - 2] != s)
                first += [start, start + 1]
                last += [start + len(form) - 1, start + len(form) - 2]
            n = len(sym)
            is_first = np.zeros(n, dtype=bool)
            is_first[first] = True
            starts = np.zeros(n, dtype=bool)
            starts[first[::2]] = True
            is_last = np.zeros(n, dtype=bool)
            is_last[last] = True
            self._states = (np.array(sym), word_of, is_first, starts, is_last, np.array(skip),
                            np.array([self.share[w] for w in word_of]))
        return self._states


def mark_scores(marks: np.ndarray, said: SaidInMarks) -> Dict[str, float]:
    """How likely a stretch of marks is to report each word, the best of its ways of being said (summed over every
    way of placing its sounds and blanks)."""
    import torch
    from . import phone_recogniser as PR
    if not said.flat or not len(marks):
        return {}
    seqs = [seq for _, seq in said.flat]
    lp = torch.tensor(marks, dtype=torch.float32).unsqueeze(1).expand(-1, len(seqs), -1)
    loss = torch.nn.functional.ctc_loss(
        lp, torch.tensor([p for seq in seqs for p in seq], dtype=torch.long),
        torch.full((len(seqs),), len(marks), dtype=torch.long), torch.tensor([len(s) for s in seqs], dtype=torch.long),
        blank=PR.BLANK, reduction="none")
    out: Dict[str, float] = {}
    for (word, _), value in zip(said.flat, (-loss).numpy()):
        out[word] = max(out.get(word, -np.inf), float(value))
    return out


def _mark_decode(marks: np.ndarray, said: SaidInMarks) -> List[Tuple[int, int, str, int, int]]:
    """How a stretch of marks divides into words: the spans `(first mark, last mark, word, first sounded, last
    sounded)` of the one sequence of words that fits it best, each entered at the cost of its share of real text
    (`MARK_USAGE_WEIGHT`). A word's sounds are the marks the search spent in its sounds, not its blanks."""
    from . import phone_recogniser as PR
    sym, word_of, is_first, starts, is_last, skip, entry = said.states()
    n = len(sym)
    every = np.arange(n)
    sounds = sym != PR.BLANK
    score = np.full(n, -np.inf)
    begun = np.zeros(n, dtype=int)
    onset = np.full(n, -1)
    offset = np.full(n, -1)
    ended = np.full(len(marks) + 1, -np.inf)
    ended[0] = 0.0
    how: List[Optional[Tuple[int, str, int, int]]] = [None] * (len(marks) + 1)
    back = lambda a, k, fill: np.concatenate([np.full(k, fill), a[:-k]])
    for t in range(len(marks)):
        one = back(score, 1, -np.inf)
        one[starts] = -np.inf
        two = back(score, 2, -np.inf)
        two[~skip] = -np.inf
        enter = np.where(is_first, ended[t] + MARK_USAGE_WEIGHT * entry, -np.inf)
        options = np.stack([score, one, two, enter])
        choice = options.argmax(axis=0)
        begun = np.stack([begun, back(begun, 1, 0), back(begun, 2, 0), np.full(n, t)])[choice, every]
        onset = np.stack([onset, back(onset, 1, -1), back(onset, 2, -1), np.full(n, -1)])[choice, every]
        onset = np.where(sounds & (onset < 0), t, onset)
        offset = np.stack([offset, back(offset, 1, -1), back(offset, 2, -1), np.full(n, -1)])[choice, every]
        offset = np.where(sounds, t, offset)
        score = options[choice, every] + marks[t, sym]
        ends = np.where(is_last, score, -np.inf)
        best = int(ends.argmax())
        ended[t + 1] = ends[best]
        how[t + 1] = (int(begun[best]), word_of[best], int(onset[best]), int(offset[best]))
    spans: List[Tuple[int, int, str, int, int]] = []
    t = len(marks)
    while t > 0 and how[t] is not None:
        first, word, on, off = how[t]
        spans.append((first, t - 1, word, on, off))
        t = first
    return spans[::-1]


def find_words_by_marks(y: np.ndarray, ear: Any, said: SaidInMarks) -> List[Dict[str, Any]]:
    """What was said in a stretch of speech, from a phone recogniser's marks (`ear`, `phone_recogniser`), in order:
    the same spans `find_words` gives, each with the word it clearly is (`MARK_CLEAR`), or the few it fits best as
    `close`, for the listener to choose among by which makes sense."""
    from . import phone_recogniser as PR
    y = np.asarray(y, dtype=np.float64)
    lo, hi, _inside = _extent(y)
    if hi - lo < SHORTEST_PHONE or not said.words:
        return []
    # THE WHOLE RECORDING IS HEARD: the recogniser marks where nothing is said itself, and cut to the stretch that is
    # loud enough, words said alone were heard right 43.0% of the time against 47.0% (`offline_alone.py`).
    marks = ear.marks(y, SR)
    spans: List[Dict[str, Any]] = []
    for first, last, _word, on, off in _mark_decode(marks, said):
        got = mark_scores(marks[first:last + 1], said)
        # A word is timed by its sounds, as the search placed them, not by the blanks before and after them.
        span: Dict[str, Any] = {"word": None, "starts_at": round(on * PR.STEP, 3), "ends_at": round((off + 1) * PR.STEP, 3)}
        if not got:
            spans.append(span)
            continue
        # NAMED BY HOW IT SOUNDS ALONE, as the margins were measured; where it is not clear, the words it may be are
        # weighed as the stretch was divided, by how they sound and how much each is used.
        near = _differently_said(sorted(got, key=got.get, reverse=True), said)
        margin = got[near[0]] - got[near[1]] if len(near) > 1 else float("inf")
        if margin >= MARK_CLEAR:
            span.update(word=near[0], margin=round(float(min(margin, 999.0)), 3),
                        standing=round(float(np.clip((margin - MARK_CLEAR) / (MARK_RESOLVED - MARK_CLEAR), 0.0, 1.0)), 3))
        else:
            weighed = {w: got[w] + MARK_USAGE_WEIGHT * said.share[w] for w in got}
            near = _differently_said(sorted(weighed, key=weighed.get, reverse=True), said)
            # How far behind, a frame of the ear's grid over the span's time, as `ranked_texts` weighs it.
            tens = max(1.0, (span["ends_at"] - span["starts_at"]) * SR / _HOP)
            span["close"] = near
            span["behind"] = [round(float((weighed[near[0]] - weighed[w]) / tens), 3) for w in near]
        spans.append(span)
    return spans


def _differently_said(order: Sequence[str], said: SaidInMarks) -> List[str]:
    """The first `PHONE_CANDIDATES` words of `order`, none said the same as one before it."""
    near: List[str] = []
    for w in order:
        if not any(said.alike(w, other) for other in near):
            near.append(w)
        if len(near) == PHONE_CANDIDATES:
            break
    return near


def heard_by_marks(y: np.ndarray, ear: Any, said: SaidInMarks) -> Dict[str, Any]:
    """What was said in a recording, from a phone recogniser's marks, as `recognise` gives it: `said`, `heard_text`,
    and `heard_texts`, the likeliest ways of taking it, where words in it are not clearly one word."""
    spans = find_words_by_marks(y, ear, said)
    out: Dict[str, Any] = {}
    named = [{"word": s["word"], "support": s["standing"], "starts_at": s["starts_at"], "ends_at": s["ends_at"]}
             for s in spans if s.get("word")]
    if named:
        out["said"] = named
    if spans:
        out["heard_text"] = said_text(spans)
    if any(s.get("close") for s in spans):
        out["heard_texts"] = ranked_texts(spans)
    return out
