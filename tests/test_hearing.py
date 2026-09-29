"""The ear, on real recordings: what hearing measures, what it claims, and what it
refuses to claim. Pure — no store is touched.

Recordings are the ones in the repo: the JFK inaugural sample (real speech, with
room hiss between phrases), a plucked string saved in several formats, and a
real silent video clip.
"""
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from core.memory.media_store import media_kind, mime_of
from core.perception import hearing as H
from core.perception.perception_faculty import PerceptionFaculty

REPO = Path(__file__).resolve().parents[1]
JFK = REPO / "third_party" / "whisper.cpp" / "samples" / "jfk.wav"
PLUCK = REPO / "Python-3.11.4" / "Lib" / "test" / "audiodata"
SILENT_CLIP = REPO / "test_data" / "jellyfish_real_10s.mp4"

pytestmark = pytest.mark.skipif(not JFK.exists(), reason="the JFK sample is not in this checkout")


def _written(tmp_path, name, samples):
    path = tmp_path / name
    sf.write(str(path), np.clip(samples, -1, 1).astype(np.float32), H.SR)
    return str(path)


def test_speech_is_heard_as_sounds_on_a_ground():
    d = H.describe(str(JFK))
    assert d["has_audio"] and d["sound_count"] >= 4
    assert d["ground"] is not None and -50 < d["ground"] < -35     # the room hiss
    assert d["hearing_category"] == "clear"
    for s in d["sounds"]:
        # every name a sound earns carries its own support
        named = {s["tonality"], s["onset"]} | ({s["register"]} if s["register"] else set())
        assert set(s["support"]) == named
        assert all(0.0 <= v <= 1.0 for v in s["support"].values())


def test_relations_are_between_neighbours_only():
    d = H.describe(str(JFK))
    assert all(r["b"] - r["a"] in (1, -1) for r in d["relations"])
    assert len(d["relations"]) <= 3 * (len(d["sounds"]) - 1)


def test_padding_with_silence_changes_nothing_that_was_heard(tmp_path):
    y = H.decode(str(JFK))
    padded = _written(tmp_path, "padded.wav",
                      np.concatenate([np.zeros(H.SR // 2), y, np.zeros(H.SR // 2)]))
    a, b = H.describe(str(JFK)), H.describe(padded)
    assert a["sound_count"] == b["sound_count"]
    assert [s["register"] for s in a["sounds"]] == [s["register"] for s in b["sounds"]]


def test_the_level_is_the_recordings_and_the_register_is_the_sounds(tmp_path):
    y = H.decode(str(JFK))
    quieter = H.describe(_written(tmp_path, "quiet.wav", y * 10 ** (-12 / 20)))
    base = H.describe(str(JFK))
    assert [s["register"] for s in base["sounds"]] == [s["register"] for s in quieter["sounds"]]
    for s, t in zip(base["sounds"], quieter["sounds"]):
        assert abs((s["level"] - t["level"]) - 12.0) < 0.5


def test_a_steady_sound_with_no_ground_is_one_sound(tmp_path):
    t = np.arange(int(0.5 * H.SR)) / H.SR
    tone = _written(tmp_path, "tone.wav", 0.5 * np.sin(2 * np.pi * 440 * t))
    d = H.describe(tone)
    assert d["ground"] is None and d["hearing_category"] == "no_ground"
    assert d["sound_count"] == 1 and d["sounds"][0]["register"] == "mid_pitched"
    assert abs(d["sounds"][0]["pitch"] - 440) < 5


def test_nothing_audible_is_no_sound(tmp_path):
    d = H.describe(_written(tmp_path, "silence.wav", np.zeros(H.SR)))
    assert d["sound_count"] == 0 and d["sounds"] == []


def test_the_same_sound_in_any_format_is_heard_alike():
    pitches = {H.describe(str(PLUCK / f"pluck-{fmt}"))["sounds"][0]["pitch"]
               for fmt in ("pcm16.wav", "pcm24.aiff", "pcm32.au")}
    assert max(pitches) - min(pitches) < 2.0


def test_a_video_with_no_sound_track_says_so():
    if not SILENT_CLIP.exists():
        pytest.skip("the silent clip is not in this checkout")
    d = H.describe(str(SILENT_CLIP))
    assert d["has_audio"] is False and d["sounds"] == []


def test_an_unreadable_file_is_a_failure_not_silence(tmp_path):
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"not a recording at all")
    with pytest.raises(ValueError):
        H.describe(str(junk))


def test_a_known_sound_agrees_with_itself_and_not_with_speech():
    pluck = H.decode(str(PLUCK / "pluck-pcm16.wav"))
    speech = H.decode(str(JFK))
    table = H.landmark_index(H.landmarks(speech[: 4 * H.SR]))
    agreeing, at = H.agreement(table, H.landmarks(speech))
    assert agreeing >= H.KNOWN_MIN_AGREE and at is not None and abs(at) < 0.05
    unrelated, _ = H.agreement(table, H.landmarks(pluck))
    assert unrelated < H.KNOWN_MIN_AGREE


def test_what_the_bytes_are_the_bytes_say():
    assert mime_of(JFK.read_bytes()[:16]) == "audio/wav"
    assert mime_of((PLUCK / "pluck-pcm16.aiff").read_bytes()[:16]) == "audio/aiff"
    assert media_kind(str(REPO / "test_data" / "vision_test.png")) == "image"


def test_the_faculty_opens_each_kind_of_file_with_its_reader():
    assert PerceptionFaculty.modality_of("a.wav") == "audio"
    assert PerceptionFaculty.modality_of("a.MP3") == "audio"
    assert PerceptionFaculty.modality_of("a.mp4") == "video"
    assert PerceptionFaculty.modality_of("a.png") == "image"
    assert PerceptionFaculty.modality_of("a.pdf") == "document"
    assert PerceptionFaculty.modality_of("a.xyz") is None


def test_a_sound_is_named_by_what_it_is_like_and_told_apart_from_look_alikes():
    taken = {}
    s = {"register": "mid_pitched", "onset": "abrupt"}
    assert PerceptionFaculty._sound_token(s, taken) == "midabrupt"
    assert PerceptionFaculty._sound_token(s, taken) == "midabrupt2"
    assert PerceptionFaculty._sound_token({"register": None, "onset": "gradual"}, {}) \
        == "unpitchedgradual"
    assert PerceptionFaculty._sound_phrase(s) == "an abrupt mid-pitched sound"
    assert PerceptionFaculty._sound_phrase({"register": "low_pitched", "onset": "gradual"}) \
        == "a gradual low-pitched sound"
