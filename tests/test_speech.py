"""Speech, on real recordings: words and voices taught by example, heard alone and
in running speech. Pure — no store is touched.

Recordings are the Free Spoken Digit Dataset in test_data/fsdd (six speakers
saying the digits, CC BY-SA 4.0), presented as a live buffer would present them:
with room quiet around them. The macOS system sounds stand for sounds that are
not a voice.
"""
from pathlib import Path

import numpy as np
import pytest

from core.memory.media_store import mime_of
from core.perception import hearing as H
from core.perception import speech as SP

REPO = Path(__file__).resolve().parents[1]
FSDD = REPO / "test_data" / "fsdd"
SYSTEM_SOUNDS = Path("/System/Library/Sounds")

pytestmark = pytest.mark.skipif(not (FSDD / "0_george_0.wav").exists(),
                                reason="the spoken digit recordings are not in this checkout")

TAUGHT = [str(d) for d in range(8)]          # 8 and 9 are never taught
_QUIET = 10 ** (-60 / 20)


def _said(speaker, digit, take):
    return H.decode(str(FSDD / f"{digit}_{speaker}_{take}.wav"))


def _in_a_room(*parts, gap=0.1, seed=0):
    """Recordings one after another, with room quiet before, between and after."""
    rng = np.random.default_rng(seed)
    quiet = lambda seconds: rng.normal(0, _QUIET, int(seconds * H.SR))
    out = [quiet(0.3)]
    for k, y in enumerate(parts):
        out += [y, quiet(gap if k < len(parts) - 1 else 0.3)]
    return np.concatenate(out)


@pytest.fixture(scope="module")
def georges_words():
    return {d: [SP.word_features(_in_a_room(_said("george", d, i), seed=i)) for i in range(5)]
            for d in TAUGHT}


@pytest.fixture(scope="module")
def three_voices():
    return {p: [SP.voice_frames(np.concatenate([_said(p, d, i) for d in range(10)]))
                for i in range(2)]
            for p in ("george", "jackson", "lucas")}


def test_a_word_is_measured_only_where_hearing_hears_it():
    y = _said("george", 3, 12)
    near = SP.word_features(_in_a_room(y, seed=1))
    far = SP.word_features(np.concatenate([np.random.default_rng(2).normal(0, _QUIET, H.SR),
                                           _in_a_room(y, seed=1)]))
    # More room around the word is not more word.
    assert len(near) >= 10 and abs(len(near) - len(far)) <= 1
    assert near.shape[1] == far.shape[1] == 2 * SP._CEPSTRA + 2


def test_a_taught_word_is_named_and_a_word_never_taught_is_not(georges_words):
    right = wrong = 0
    for d in TAUGHT:
        for take in (10, 11, 12):
            got = SP.name_word(SP.word_features(_in_a_room(_said("george", d, take), seed=take)),
                               georges_words)
            right += bool(got and got["word"] == d)
            wrong += bool(got and got["word"] != d)
    assert wrong == 0 and right >= 16          # of 24
    untaught = [SP.name_word(SP.word_features(_in_a_room(_said("george", d, take), seed=take)),
                             georges_words)
                for d in (8, 9) for take in (10, 11, 12)]
    # A name given to a word never taught is never a firm one.
    assert all(got is None or got["standing"] < 0.5 for got in untaught)


def test_one_word_taught_is_nothing_to_tell_apart():
    one = {"3": [SP.word_features(_in_a_room(_said("george", 3, 0)))]}
    assert SP.name_word(SP.word_features(_in_a_room(_said("george", 3, 10))), one) is None


def test_taught_words_are_found_in_running_speech_in_order(georges_words):
    phrase = _in_a_room(_said("george", 3, 20), _said("george", 1, 21), _said("george", 4, 22))
    spans = SP.find_words(phrase, georges_words)
    named = [s["word"] for s in spans if s["word"]]
    assert named == [w for w in ("3", "1", "4") if w in named] and len(named) >= 2
    assert all(a["ends_at"] <= b["starts_at"] + 1e-9 for a, b in zip(spans, spans[1:]))
    assert all(0.0 <= s["starts_at"] < s["ends_at"] <= len(phrase) / H.SR for s in spans)


def test_a_pause_is_never_inside_a_word(georges_words):
    phrase = _in_a_room(_said("george", 2, 30), _said("george", 5, 31), gap=0.6)
    lo, hi, inside = SP._extent(phrase)
    pause = np.flatnonzero(~inside)
    spans = SP._decode(SP.word_features(phrase), ~inside,
                       [e for w in georges_words for e in georges_words[w]])
    assert len(pause) >= 40                    # hearing heard the 0.6 s gap
    for first, last in spans:
        assert not np.any((pause >= first) & (pause <= last))


def test_room_quiet_alone_holds_nothing_to_teach():
    hiss = np.random.default_rng(3).normal(0, _QUIET, int(1.5 * H.SR))
    assert SP.rises_from_a_room(hiss) is False
    assert SP.rises_from_a_room(_in_a_room(_said("george", 7, 3))) is True


def test_what_was_said_reads_as_text_with_unknown_speech_marked():
    spans = [{"word": "call"}, {"word": None}, {"word": None}, {"word": "home"}, {"word": None}]
    assert SP.said_text(spans) == "call ... home ..."
    assert SP.said_text([]) == ""


@pytest.mark.skipif(not SYSTEM_SOUNDS.exists(), reason="needs the macOS system sounds")
def test_a_voice_is_told_from_sounds_that_are_not_one(three_voices):
    reach = SP.voice_reach(three_voices)
    assert reach is not None and reach[0] >= reach[1]
    stranger = np.concatenate([_said("nicolas", d, 20 + d) for d in range(5)])
    judged = SP.judge_voice(SP.voice_frames(stranger), three_voices, reach)
    assert judged["voice"] is True
    for name in ("Submarine", "Glass", "Hero", "Funk"):
        judged = SP.judge_voice(SP.voice_frames(H.decode(str(SYSTEM_SOUNDS / f"{name}.aiff"))),
                                three_voices, reach)
        assert judged is not None and judged["voice"] is False, name


def test_whose_voice_is_judged_only_on_enough_speech(three_voices):
    one_word = SP.voice_frames(_said("jackson", 4, 30))
    assert SP.whose_voice(one_word, three_voices) is None
    talking = SP.voice_frames(np.concatenate([_said("lucas", d, 30 + d) for d in (1, 5, 7, 2, 9)]))
    got = SP.whose_voice(talking, three_voices)
    assert got is not None and got["person"] == "lucas"


def test_one_voice_taught_is_nothing_to_tell_apart(three_voices):
    one = {"george": three_voices["george"]}
    assert SP.voice_reach(one) is None
    assert SP.judge_voice(SP.voice_frames(_said("george", 1, 40)), one) is None


def test_a_taught_example_is_kept_as_bytes_the_media_store_knows(georges_words):
    features = georges_words["3"][0]
    data = SP.pack(features)
    assert mime_of(data) == "application/x-npz"
    assert np.array_equal(SP.unpack(data), features)
