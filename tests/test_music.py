#!/usr/bin/env python3
"""Hearing music (`core.perception.music`), on real recordings with people's
annotations: a sung melody's notes, a song's key and tempo, speech heard as no
music at all, a taught song known again through a real room and a codec, and
the music reaching the percept and the claims it makes.

No store and no substrate boot: the describers, the hearing process's own
`listen`, and the faculty's and coordinator's pure pieces.
"""
import subprocess
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import linear_sum_assignment

from core.perception import hearing, music, senses

REPO = Path(__file__).resolve().parents[1]
MUSIC = REPO / "test_data" / "music"
VOCADITO = MUSIC / "vocadito"
GTZAN = MUSIC / "genres"
JFK = REPO / "third_party" / "whisper.cpp" / "samples" / "jfk.wav"
ROOM = REPO / "experiments" / "LIVE-01" / "stimuli" / "room.wav"

needs = pytest.mark.skipif(not (VOCADITO.exists() and GTZAN.exists() and ROOM.exists()),
                           reason="the music recordings are not in test_data")


def _notes_matched(est, ref):
    """Notes matched one to one with onset within 50 ms and pitch within 50
    cents (the standard note-transcription criterion), as an F-measure."""
    if not est or not ref:
        return 0.0
    ok = np.array([[abs(e[0] - r[0]) <= 0.05 and abs(1200 * np.log2(e[1] / r[1])) <= 50
                    for e in est] for r in ref])
    rows, cols = linear_sum_assignment(~ok)
    hit = int(ok[rows, cols].sum())
    p, r = hit / len(est), hit / len(ref)
    return 0.0 if hit == 0 else 2 * p * r / (p + r)


def test_note_names():
    assert [music.note_name(m) for m in (69, 60, 59, 57, 72)] == ["A4", "C4", "B3", "A3", "C5"]
    assert music.key_name("F#", "minor") == "F-sharp minor"


@needs
def test_a_sung_melody_is_heard_as_its_notes():
    y = hearing.decode(str(VOCADITO / "Audio" / "vocadito_5.wav"))
    claims = music.describe(y)["claims"]
    # Measured support 0.80: held pitches at a singer's pace.
    assert "melody" in claims and claims["melody"]["support"] > 0.5
    heard = [(n["start"], n["pitch"]) for n in claims["melody"]["notes"]]
    rows = (VOCADITO / "Annotations" / "Notes" / "vocadito_5_notesA1.csv").read_text().split()
    annotated = [(float(a), float(b)) for a, b, _c in (r.split(",") for r in rows)]
    # Measured 0.73 against this annotator; the two annotators agree at 0.60.
    assert _notes_matched(heard, annotated) >= 0.65


@needs
def test_speech_is_heard_as_no_music():
    assert music.describe(hearing.decode(str(JFK)))["claims"] == {}


@needs
def test_a_songs_key_and_tempo():
    y = hearing.decode(str(GTZAN / "country" / "country.00013.wav"))
    claims = music.describe(y)["claims"]
    # Annotated A major (Kraft/Lerch) at 127.05 bpm (GTZAN-Rhythm).
    assert claims["in_key"]["key"] == "A major" and claims["in_key"]["support"] >= 0.9
    assert abs(claims["tempo"]["bpm"] - 127.05) <= 0.04 * 127.05


@needs
def test_a_taught_song_is_known_through_a_room_and_a_codec(tmp_path):
    song = GTZAN / "pop" / "pop.00005.wav"
    taught = music.song_example(hearing.decode(str(song)), song.name)
    library = {"songs": {"Pop five": [taught]}}
    heard = tmp_path / "pop5_in_the_room.mp3"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", "12", "-t", "6", "-i", str(song), "-i", str(ROOM),
         "-filter_complex", "[0:a]volume=0.5[a];[1:a]volume=1.0[b];"
                            "[a][b]amix=inputs=2:duration=first:normalize=0",
         "-ac", "1", "-b:a", "64k", str(heard)], check=True)
    found = senses.listen(str(heard), library)["songs"]
    assert found and found[0][0] == "Pop five"
    title, agreeing, at, share = found[0]
    assert music.resolve_song(share) == 1.0 and abs(at + 12.0) < 0.1
    assert senses.listen(str(GTZAN / "pop" / "pop.00006.wav"), library)["songs"] == []


def test_a_recording_too_plain_to_know_again_is_refused(tmp_path):
    import soundfile as sf
    tone = 0.3 * np.sin(2 * np.pi * 440 * np.arange(hearing.SR) / hearing.SR)
    with pytest.raises(ValueError, match="landmark"):
        music.song_example(tone, "tone")
    # Read from a file it ends abruptly, and gave 107 landmarks, over the
    # floor of 100; only 66 of them were different.
    path = tmp_path / "tone.wav"
    sf.write(str(path), tone.astype(np.float32), hearing.SR)
    heard = hearing.decode(str(path))
    assert len(hearing.landmarks(heard)) >= hearing.KNOWN_MIN_LANDMARKS
    with pytest.raises(ValueError, match="different landmark"):
        music.song_example(heard, "tone.wav")


def test_a_song_lesson_is_held_once_remembered():
    from core.perception.perception_faculty import PerceptionFaculty, _encode
    faculty = PerceptionFaculty()
    assert PerceptionFaculty.lesson_of({"song": "  Take  Five "}) == ("song", "Take Five")
    marks = np.array([[10, 20, 3, 0], [11, 25, 4, 7]], dtype=np.int32)
    trace = hearing.trace_bytes({"samples": 1, "segments": [], "ground": None}, marks)
    before = faculty.taught_version
    assert faculty.hold_lesson({"lesson": {"song": "Take Five"}, "trace": _encode(trace)})
    assert faculty.taught_songs == {"Take Five": 1} and faculty.taught_version == before + 1
    assert np.array_equal(faculty._songs["Take Five"][0], marks)


HUMTRANS = MUSIC / "humtrans" / "wav"
hums = pytest.mark.skipif(not HUMTRANS.exists(), reason="HumTrans is not in test_data")
#: HumTrans VALID tunes, one segment of each of sixteen songs, each hummed by
#: F01 and by F02 (first takes). Two segments of one song share its melody, so
#: they are not taught as two songs.
_TAUGHT = ("0003_0001", "0027_0001", "0034_0001", "0089_0001", "0161_0001", "0162_0001",
           "0191_0001", "0210_0001", "0232_0001", "0249_0002", "0256_0001", "0262_0002")
_NEVER_TAUGHT = ("0269_0001", "0275_0001", "0291_0001", "0305_0001")


def _tune_of(person: str, tune: str):
    path = next(HUMTRANS.glob(f"{person}_{tune}_1*.wav"))
    return music.describe(hearing.decode(str(path))).get("tune")


@hums
def test_a_tune_is_known_hummed_by_someone_else():
    """Taught from one person's hum, a tune is known from another person's, in
    their own key and at their own pace; a tune never taught is not named."""
    taught = {t: [_tune_of("F01", t)] for t in _TAUGHT}
    assert all(lines[0] is not None and len(lines[0]) >= music.TUNE_MIN_POINTS
               for lines in taught.values())
    named = {t: music.tunes_heard(_tune_of("F02", t), taught) for t in _TAUGHT}
    right = [t for t, found in named.items() if found and found[0]["song"] == t]
    wrong = [t for t, found in named.items() if found and found[0]["song"] != t]
    # Measured: all twelve named, each at a ratio of 0.61 or less. On the VALID
    # split, among 350 taught tunes: 79% of whole hums named, 99.5% of them right.
    assert len(right) >= 10 and not wrong, named
    assert not any(music.tunes_heard(_tune_of("F02", t), taught) for t in _NEVER_TAUGHT)
    # A ratio needs a rival: one song taught names nothing.
    one = {_TAUGHT[0]: taught[_TAUGHT[0]]}
    assert music.tunes_heard(_tune_of("F02", _TAUGHT[0]), one) == []


MDB = MUSIC / "MDB-melody-synth"
mixes = pytest.mark.skipif(not MDB.exists(), reason="MDB-melody-synth is not in test_data")


def _melody_scores(name: str, start: float, f0_of) -> tuple:
    """(pitch right, overall) of `f0_of(y)` against the annotated melody of a
    minute of `name`'s mix, from `start`, on a 10 ms grid."""
    import csv
    y = hearing.decode(str(MDB / "audio_mix" / f"{name}_MIX_melsynth.wav"))
    y = y[int(start * hearing.SR):int((start + 60) * hearing.SR)]
    ann = next((MDB / "annotation_melody").glob(f"{name}_STEM_*.csv"))
    rows = np.array([[float(a), float(b)] for a, b in csv.reader(open(ann))])
    grid = np.arange(0, 60, 0.01)
    ref = rows[np.clip(np.searchsorted(rows[:, 0], grid + start), 0, len(rows) - 1), 1]
    f0 = f0_of(y)
    est = f0[np.clip((grid * hearing.SR / hearing.HOP).astype(int), 0, len(f0) - 1)]
    rv, ev = ref > 0, est > 0
    near = np.zeros(len(ref), bool)
    near[rv & ev] = 1200 * np.abs(np.log2(est[rv & ev] / ref[rv & ev])) <= 50
    return near.sum() / rv.sum(), (np.sum(~rv & ~ev) + near.sum()) / len(ref)


@mixes
def test_the_melody_of_a_mix_is_read_as_annotated():
    """Which line of a full mix is the melody (MDB-melody-synth's exact f0): the
    salience path follows it where the pitch tracker for a single line cannot.
    Measured: 0.54/0.67, 0.52/0.56, 0.62/0.69 (pitch right / overall); YIN on
    the same mixes 0.02 pitch right."""
    for name in ("AClassicEducation_NightOwl", "LizNelson_Coldwar", "HopAlong_SisterCities"):
        pitch, overall = _melody_scores(name, 35.0, lambda y: music.melody_of_mix(y)["f0"])
        assert pitch >= 0.45 and overall >= 0.5, (name, pitch, overall)
        yin, _ = _melody_scores(name, 35.0, lambda y: music.pitch_track(y)["f0"])
        assert yin < 0.1, (name, yin)


def test_a_hearing_keeps_its_tune_and_a_song_lesson_holds_it():
    from core.perception.perception_faculty import PerceptionFaculty, _encode
    line = np.array([0.0, 2.0, 4.0, 5.0, 7.0, 5.0, 4.0, 2.0, 0.0], np.float32)
    marks = np.array([[10, 20, 3, 0], [11, 25, 4, 7]], dtype=np.int32)
    trace = hearing.trace_bytes({"samples": 1, "segments": [], "ground": None}, marks,
                                marks, line)
    assert np.allclose(hearing.trace_tune(trace), line)
    faculty = PerceptionFaculty()
    assert faculty.hold_lesson({"lesson": {"song": "Ode"}, "trace": _encode(trace)})
    assert np.allclose(faculty._tunes["Ode"][0]["line"], line)
    assert faculty._tunes["Ode"][0]["mix"] is False
    assert "Ode" in faculty._hearing_library()["tunes"]
    # A song taught from a mix says its tune was read from the mix's melody.
    mixed = hearing.trace_bytes({"samples": 1, "segments": [], "ground": None}, marks,
                                marks, line, tune_from_mix=True)
    assert hearing.trace_tune_from_mix(mixed) and not hearing.trace_tune_from_mix(trace)
    assert faculty.hold_lesson({"lesson": {"song": "Ode"}, "trace": _encode(mixed)})
    assert faculty._tunes["Ode"][1]["mix"] is True
    # A hearing that was not a single line keeps no tune.
    assert hearing.trace_tune(hearing.trace_bytes(
        {"samples": 1, "segments": [], "ground": None}, None, marks)) is None


def test_a_tune_heard_reaches_the_percept_and_its_claims():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.perception.perception_faculty import PerceptionFaculty
    found = PerceptionFaculty._music_content(
        {"music": {"claims": {}}, "tunes": [{"song": "Ode to Joy", "cost": 0.4,
                                              "ratio": 0.5, "support": 1.0}]})
    assert found["has_tune_of"] == [{"song": "Ode to Joy", "ratio": 0.5, "support": 1.0}]
    assert PerceptionFaculty._music_caption(found) == '; the tune of "Ode to Joy"'
    assert "hum has_tune_of ode_to_joy" in AutonomousCoordinator._sensed_claims("hum", found)


def test_music_reaches_the_percept_and_its_claims():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.perception.perception_faculty import PerceptionFaculty
    heard = {"music": {"claims": {
                 "in_key": {"key": "F-sharp minor", "support": 0.8},
                 "tempo": {"bpm": 120.0, "rival_bpm": 60.0, "support": 0.6},
                 "melody": {"notes": [{"name": "A4", "midi": 69.0}, {"name": "C5", "midi": 72.0},
                                      {"name": "B4", "midi": 71.0}], "support": 0.9}}},
             "songs": [("Take Five", 900, 0.0, 0.5)]}
    found = PerceptionFaculty._music_content(heard)
    assert found["plays"][0]["song"] == "Take Five" and found["plays"][0]["support"] == 1.0
    caption = PerceptionFaculty._music_caption(found)
    assert caption == ('; playing "Take Five", in F-sharp minor, about 120 beats a minute, '
                       "a melody of 3 notes from A4 to C5, going A4 C5 B4")
    claims = AutonomousCoordinator._sensed_claims("rec", found)
    assert {"rec in_key f_sharp_minor", "rec has_tempo 120.0", "rec plays take_five"} <= set(claims)
