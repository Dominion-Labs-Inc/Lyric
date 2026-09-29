#!/usr/bin/env python3
"""SONGS-01 — music heard by the substrate: songs taught by hearing them and
known again, the key and tempo of a song, the notes of a sung melody.

No model anywhere. Music is MEASURED (`core.perception.music`): the key by the
fit of the music's pitch-class profile to the key profiles of Krumhansl and
Kessler, the tempo by the periodicity of its onsets (Ellis), the notes of a
single line by hearing's own pitch path. A SONG is taught as a word is: by
hearing it, told what it is called; the lesson is a hearing like any other,
remembered as one, and its trace keeps the song's landmarks. This boots the
real substrate, teaches it, and hears real recordings through
`coordinator.hear()`, asserting what happened at every stage and every seam.

  A  TAUGHT      each song is HEARD through the one door, told its title, and
                 remembered as a hearing like any other, saying what it taught,
                 its trace keeping the song's landmarks; a recording too plain
                 to know again is refused, nothing kept.
  B  RESTART     a fresh faculty reads the taught songs back from memory,
                 exactly as they were taught.
  C  KNOWN       a taught song, played into a real room and through a codec,
                 is known (`plays`); a song never taught is not.
  D  KEY, TEMPO  a song is heard in the key and at the tempo people annotated.
  E  ADMITTED    what it plays, its key and its tempo are in the concept graph
                 and held as beliefs.
  F  MELODY      a sung melody is heard as its notes, as people transcribed
                 them, and remembered in words.
  G  RECALLED    the melody heard again in the mind is the same notes.
  H  SPEECH      speech is heard as no key, no tempo, no melody, no song.
  I  VIDEO       a clip whose sound track is a taught song plays that song.

Recordings: GTZAN (1000 clips, 30 s; key annotations by Kraft and Lerch, tempo
by GTZAN-Rhythm), vocadito (solo singing, notes transcribed by two annotators,
CC BY 4.0), JFK's inaugural sample, a real room recorded from this Mac's
microphone, and the repo's jellyfish footage. Stimuli are built from those
into `stimuli/` on first run.

Run (sandbox store): ./venv_torin/bin/python3 experiments/SONGS-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
GTZAN = REPO / "test_data" / "music" / "genres"
VOCADITO = REPO / "test_data" / "music" / "vocadito"
JFK = REPO / "third_party" / "whisper.cpp" / "samples" / "jfk.wav"
ROOM = REPO / "experiments" / "LIVE-01" / "stimuli" / "room.wav"
JELLYFISH = REPO / "test_data" / "jellyfish_real_10s.mp4"

#: The songs taught, by clip, and one never taught. country.00013 is
#: annotated A major at 127.05 bpm.
TAUGHT = {"country": "country/country.00013.wav", "disco": "disco/disco.00033.wav",
          "pop": "pop/pop.00005.wav"}
UNTAUGHT = "pop/pop.00006.wav"
SUNG = "vocadito_5"
#: Fixed before the first run.
NOTES_MATCHED = 0.65        # a sung melody's notes against the annotator's (measured 0.73)
RECALLED_SAME = 0.8         # the melody heard again from its trace (0.85-0.88 offline)

EV = RunRecord(
    "SONGS-01",
    claim=("The substrate hears music with no model: a song is taught by hearing it and "
           "known again through a room and a codec; a song's key and tempo, and a sung "
           "melody's notes, are heard as people annotated them, admitted, believed and "
           "remembered in words; speech is heard as no music."),
    hypothesis=(f"H1 a taught song is known from 6 s of it played into a real room and a "
                f"64 kbit/s codec, and a song never taught is not. H2 a song's key and "
                f"tempo are heard as annotated, with firm support. H3 a sung melody's "
                f"notes match the annotator's at {NOTES_MATCHED} or more. H4 the melody "
                f"rebuilt from its trace is heard as the same notes, {RECALLED_SAME} or "
                f"more. H5 speech gets no key, tempo, melody or song."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def build_stimuli() -> dict:
    """Excerpts of the taught songs played into the real room and through a
    codec, the song never taught, a tone too plain to know again, and a clip
    whose sound track is a taught song."""
    import numpy as np
    import soundfile as sf
    STIM.mkdir(parents=True, exist_ok=True)
    stim = {"room": {}}
    for name, rel in TAUGHT.items():
        out = STIM / f"{name}_in_the_room.mp3"
        if not out.exists():
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", "12", "-t", "6", "-i", str(GTZAN / rel),
                 "-i", str(ROOM), "-filter_complex",
                 "[0:a]volume=0.5[a];[1:a]volume=1.0[b];[a][b]amix=inputs=2:duration=first:normalize=0",
                 "-ac", "1", "-b:a", "64k", str(out)], check=True)
        stim["room"][name] = out
    stim["untaught"] = STIM / "untaught_in_the_room.mp3"
    if not stim["untaught"].exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "12", "-t", "6", "-i", str(GTZAN / UNTAUGHT),
             "-i", str(ROOM), "-filter_complex",
             "[0:a]volume=0.5[a];[1:a]volume=1.0[b];[a][b]amix=inputs=2:duration=first:normalize=0",
             "-ac", "1", "-b:a", "64k", str(stim["untaught"])], check=True)
    stim["tone"] = STIM / "tone.wav"
    if not stim["tone"].exists():
        sr = 22050
        sf.write(str(stim["tone"]), (0.3 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr))
                 .astype(np.float32), sr)
    stim["clip"] = STIM / "jellyfish_with_disco.mp4"
    if not stim["clip"].exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(JELLYFISH), "-ss", "5", "-t", "10",
                        "-i", str(GTZAN / TAUGHT["disco"]), "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                        str(stim["clip"])], check=True)
    return stim


def notes_matched(est, ref) -> float:
    """Notes matched one to one, onset within 50 ms and pitch within 50 cents,
    as an F-measure."""
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    if not est or not ref:
        return 0.0
    ok = np.array([[abs(e[0] - r[0]) <= 0.05 and abs(1200 * np.log2(e[1] / r[1])) <= 50
                    for e in est] for r in ref])
    rows, cols = linear_sum_assignment(~ok)
    hit = int(ok[rows, cols].sum())
    return 2 * hit / (len(est) + len(ref))


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    import numpy as np
    from core.perception import hearing as H
    from core.perception import music as MU
    from core.perception.perception_faculty import PerceptionFaculty
    from core.memory.media_store import get_media_store
    from core.domain.evidence_producers import _term_like
    stim = build_stimuli()

    tag = uuid.uuid4().hex[:6]
    DOMAIN = "hearing"
    title_of = {name: f"{name} song {tag}" for name in TAUGHT}
    memory_ids = []
    faculty = coord.vision
    as_json = lambda v: json.loads(v) if isinstance(v, str) else (v or {})

    async def perceive(door, path, label):
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await getattr(coord, door)(str(path), source=f"s{tag}{label}",
                                                 domain=DOMAIN, actor_identity=None)
            await get_uncertainty_system().drain_writes()
        meta = (percept.metadata or {}) if percept is not None else {}
        if meta.get("memory_id"):
            memory_ids.append(meta["memory_id"])
        return percept

    async def edges_of(name):
        rows = await db.execute_query(
            "SELECT cr.relation AS rel, COALESCE(c2.name, cr.target_surface) AS obj "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE c1.name = $1", (name,), fetch_all=True) or []
        return [(str(r["rel"]), str(r["obj"])) for r in rows]

    def text_of(content):
        try:
            return str(json.loads(content))
        except (TypeError, ValueError):
            return str(content)

    try:
        # ── A. TAUGHT ───────────────────────────────────────────────────────
        print("\n== A. Songs are taught by hearing them, as memories ==")
        await faculty._read_library()
        taught_ids = {}
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            for name, rel in TAUGHT.items():
                taught_ids[name] = await coord.learn_song(
                    title_of[name], str(GTZAN / rel), actor_identity=None,
                    source=f"s{tag}t{name}", domain=DOMAIN)
            await get_uncertainty_system().drain_writes()
        memory_ids.extend(taught_ids.values())
        check("every song taught was heard, and remembered as a hearing of its own",
              len(set(taught_ids.values())) == len(TAUGHT), str(list(taught_ids.values())))
        row = await db.execute_query(
            "SELECT tags, metadata, content FROM memory_hot.memory_hot WHERE memory_id = $1",
            (str(taught_ids["country"]),), fetch_one=True)
        ctx = as_json(row["metadata"]) if row else {}
        tags = as_json(row["tags"]) if row else []
        says = bool(row) and f'taught: the song "{title_of["country"]}"' in text_of(row["content"])
        check("a song's lesson is the same memory as any hearing, and says what it taught",
              bool(row) and {"sound", "hearing", "song"} <= set(tags)
              and ctx.get("song") == title_of["country"]
              and (ctx.get("origin") or {}).get("through") == "hear" and says,
              f"tags {tags}, song {ctx.get('song')}, says so: {says}")
        kept = await get_media_store().media_for_memory(str(taught_ids["country"]))
        landmarks = MU.song_example(H.decode(str(GTZAN / TAUGHT["country"])), "country")
        from core.perception import speech as SP
        check("its trace keeps the song's landmarks, never the recording",
              len(kept) == 1 and kept[0]["mime"] == "application/x-npz"
              and kept[0]["perceived"].get("lesson") == {"song": title_of["country"]}
              and np.array_equal(SP.unpack(kept[0]["bytes"]).astype(np.int32), landmarks),
              f"{kept[0]['byte_size']} bytes, {len(landmarks)} landmarks" if kept else "nothing")
        before = await db.execute_query(
            "SELECT count(*) AS n FROM memory_hot.memory_hot WHERE content LIKE $1",
            (f"%{tag}%",), fetch_one=True)
        refused = None
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                await coord.learn_song(f"tone {tag}", str(stim["tone"]), actor_identity=None,
                                       source=f"s{tag}tone", domain=DOMAIN)
        except ValueError as error:
            refused = str(error)
        after = await db.execute_query(
            "SELECT count(*) AS n FROM memory_hot.memory_hot WHERE content LIKE $1",
            (f"%{tag}%",), fetch_one=True)
        check("a recording too plain to know again is refused, and nothing is kept",
              refused is not None and after["n"] == before["n"], refused)

        # ── B. RESTART ──────────────────────────────────────────────────────
        print("\n== B. A fresh faculty reads the taught songs back from memory ==")
        fresh = PerceptionFaculty()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await fresh.load_instances()
        songs = {t: n for t, n in fresh.taught_songs.items() if tag in t}
        check("every taught song", songs == {title_of[n]: 1 for n in TAUGHT}, str(songs))
        back = (fresh._songs.get(title_of["country"]) or [None])[0]
        check("exactly as it was taught", back is not None and np.array_equal(back, landmarks),
              f"{0 if back is None else len(back)} landmarks")
        fresh.close()

        # ── C. KNOWN ────────────────────────────────────────────────────────
        print("\n== C. A taught song is known again through a room and a codec ==")
        known = {}
        for name in TAUGHT:
            percept = await perceive("hear", stim["room"][name], f"room{name}")
            known[name] = percept
        plays = {name: [(p["song"], p["support"]) for p in (known[name].content.get("plays") or [])]
                 if known[name] else None for name in TAUGHT}
        check("each taught song is known from 6 s of it played into the room",
              all(v and v[0] == (title_of[n], 1.0) for n, v in plays.items()), str(plays))
        caption = known["country"].content.get("caption", "") if known["country"] else ""
        check("and the hearing says so in words", f'playing "{title_of["country"]}"' in caption,
              caption[-120:])
        other = await perceive("hear", stim["untaught"], "untaught")
        check("a song never taught is not known as any taught one",
              other is not None and not other.content.get("plays"),
              str(other.content.get("plays") if other else None))

        # ── D. KEY, TEMPO ───────────────────────────────────────────────────
        print("\n== D. A song is heard in the key and at the tempo people annotated ==")
        whole = await perceive("hear", GTZAN / TAUGHT["country"], "whole")
        content = whole.content if whole else {}
        key = content.get("in_key") or {}
        tempo = content.get("tempo") or {}
        check("in A major, firmly (annotated A major)",
              key.get("key") == "A major" and key.get("support", 0) >= 0.9, str(key))
        check("at the annotated tempo, within 4% (127.05 bpm)",
              bool(tempo) and abs(tempo["bpm"] - 127.05) <= 0.04 * 127.05, str(tempo))

        # ── E. ADMITTED ─────────────────────────────────────────────────────
        print("\n== E. What it plays, its key and its tempo are admitted and believed ==")
        excerpt = known["country"].source if known["country"] else None
        subject = whole.source if whole else None
        plays_edges = set(await edges_of(excerpt)) if excerpt else set()
        edges = set(await edges_of(subject)) if subject else set()
        check("the recording heard in the room PLAYS the song, in the graph",
              ("plays", _term_like(title_of["country"])) in plays_edges,
              ", ".join(f"{r} {o}" for r, o in sorted(plays_edges) if r == "plays"))
        want = {("in_key", _term_like(key.get("key") or "")),
                ("has_tempo", str(tempo.get("bpm")))}
        check("the song is IN its key and HAS its tempo, in the graph",
              bool(key) and bool(tempo) and want <= edges,
              ", ".join(f"{r} {o}" for r, o in sorted(edges) if r in ("plays", "in_key", "has_tempo")))
        rows = await db.execute_query(
            "SELECT belief_text FROM unified.beliefs WHERE (belief_text LIKE $1 OR belief_text LIKE $2) "
            "AND (belief_text LIKE '% plays %' OR belief_text LIKE '% in_key %' "
            "OR belief_text LIKE '% has_tempo %')", (f"%{excerpt}%", f"%{subject}%"),
            fetch_all=True) or []
        check("and they are held as beliefs", len(rows) >= 3,
              "; ".join(str(r["belief_text"]) for r in rows)[:240])

        # ── F. MELODY ───────────────────────────────────────────────────────
        print("\n== F. A sung melody is heard as its notes ==")
        sung = await perceive("hear", VOCADITO / "Audio" / f"{SUNG}.wav", "sung")
        melody = (sung.content.get("melody") if sung else None) or {}
        rows = (VOCADITO / "Annotations" / "Notes" / f"{SUNG}_notesA1.csv").read_text().split()
        annotated = [(float(a), float(b)) for a, b, _c in (r.split(",") for r in rows)]
        matched = notes_matched([(n["start"], n["pitch"]) for n in melody.get("notes", [])], annotated)
        EV.metric("sung_notes_matched", round(matched, 3), "F", "onset 50 ms, pitch 50 cents")
        check(f"its notes match the annotator's at {NOTES_MATCHED} or more",
              matched >= NOTES_MATCHED, f"{matched:.3f} over {len(melody.get('notes', []))} notes")
        sung_id = (sung.metadata or {}).get("memory_id") if sung else None
        mrow = await db.execute_query(
            "SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1", (str(sung_id),),
            fetch_one=True) if sung_id else None
        words = text_of(mrow["content"]) if mrow else ""
        check("and it is remembered in words: a melody, its notes, how it goes",
              "a melody of" in words and " going " in words, words[-160:])
        media = await get_media_store().media_for_memory(str(sung_id)) if sung_id else []
        check("its memory keeps the melody, not the recording",
              len(media) == 1 and len((media[0]["perceived"].get("melody") or {}).get("notes", []))
              == len(melody.get("notes", [])) and media[0]["mime"] == "application/x-npz",
              f"{len(media)} media")

        # ── G. RECALLED ─────────────────────────────────────────────────────
        print("\n== G. The melody heard again in the mind is the same notes ==")
        rebuilt = await coord.recollect(str(sung_id)) if sung_id else []
        again = MU.describe(np.asarray(rebuilt[0]["samples"], np.float64))["claims"] \
            .get("melody") if rebuilt else None
        same = notes_matched([(n["start"], n["pitch"]) for n in (again or {}).get("notes", [])],
                             [(n["start"], n["pitch"]) for n in melody.get("notes", [])])
        EV.metric("recalled_notes_same", round(same, 3), "F", "rebuilt melody against heard melody")
        check(f"rebuilt from its trace, it is heard as the same notes, {RECALLED_SAME} or more",
              same >= RECALLED_SAME, f"{same:.3f}")

        # ── H. SPEECH ───────────────────────────────────────────────────────
        print("\n== H. Speech is heard as no music ==")
        spoken = await perceive("hear", JFK, "speech")
        claimed = [k for k in ("in_key", "tempo", "melody", "plays")
                   if spoken and spoken.content.get(k)]
        check("no key, no tempo, no melody, no song", spoken is not None and not claimed,
              str(claimed))

        # ── I. VIDEO ────────────────────────────────────────────────────────
        print("\n== I. A clip whose sound track is a taught song plays it ==")
        clip = await perceive("see", stim["clip"], "clip")
        played = [p["song"] for p in (clip.content.get("plays") or [])] if clip else []
        check("the clip is seen, and heard playing the song",
              played[:1] == [title_of["disco"]] and bool((clip.content.get("blobs") or [])),
              str(played))
    finally:
        # ── cleanup: everything this run wrote, by exact id and by its nonce ─
        _tagged = ("SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE $1) + "
                   "(SELECT count(*) FROM unified.beliefs WHERE belief_text LIKE $1) + "
                   "(SELECT count(*) FROM unified.perceptions WHERE source LIKE $1) + "
                   "(SELECT count(*) FROM memory_hot.memory_hot WHERE content::text LIKE $1) AS n")
        like = f"%{tag}%"
        try:
            written = await db.execute_query(_tagged, (like,), fetch_one=True)
        except Exception as error:
            written = None
            EV.note(f"Could not count this run's rows before cleanup: {error}")
        try:
            await db.execute_query(
                "DELETE FROM unified.concept_relations WHERE source_concept_id IN "
                "(SELECT concept_id FROM unified.concepts WHERE name LIKE $1) "
                "OR target_concept_id IN (SELECT concept_id FROM unified.concepts "
                "WHERE name LIKE $1) OR target_surface LIKE $1", (like,), commit=True)
            await db.execute_query("DELETE FROM unified.concepts WHERE name LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.beliefs WHERE belief_text LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.experience_pool WHERE about LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.evidence_envelopes "
                                   "WHERE producer LIKE $1 OR source_id LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.perceptions WHERE source LIKE $1",
                                   (like,), commit=True)
            tagged = await db.execute_query(
                "SELECT memory_id FROM memory_hot.memory_hot WHERE content::text LIKE $1",
                (like,), fetch_all=True) or []
            for mid in set(map(str, memory_ids)) | {str(r["memory_id"]) for r in tagged}:
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (mid,), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (mid,), commit=True)
            left = await db.execute_query(_tagged, (like,), fetch_one=True)
            EV.note(f"Cleanup by nonce {tag} and exact memory id: "
                    f"{written['n'] if written else 'an uncounted number of'} tagged row(s) "
                    f"written, {left['n']} left.")
        except Exception as error:
            print(f"  (cleanup: {error})")
            EV.note(f"Cleanup failed: {error}")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            coord.vision.close()

    passed = sum(1 for ok in results if ok)
    print(f"\n==== SONGS-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
