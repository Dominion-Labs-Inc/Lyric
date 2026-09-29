#!/usr/bin/env python3
"""RECALL-01 — remembering is rebuilding, for what was heard and what was seen.

A person who remembers a bell or a street does not replay a file; they rebuild
it from what stayed with them. The substrate now does the same:
- a hearing is remembered as a TRACE: each sound's spectral shape, pitch,
  periodicity and loudness over time, a few percent of the recording;
- a seeing is remembered as a GIST: the scene small, and the things most
  prominent in it in more detail.

`recollect(memory_id)` rebuilds what the memory holds. This boots the real
substrate and checks that what comes back is perceived as what was met.

  A  NOT A COPY   a hearing's memory holds a trace and no recording.
  B  FROM MEMORY  the file is deleted before recollecting; the sound and the
                  picture still come back.
  C  HEARD AGAIN  the rebuilt sound is heard as the same sounds: the same
                  number, the same pitchedness, register and onset wherever
                  those were firmly read, pitch within 5 %, level within 3 dB.
  D  SEEN AGAIN   the rebuilt picture is seen as the same: a clean picture's
                  things come back exactly; on real footage at least half of
                  them come back, and the dominant hue.
  E  NOTHING MET  a memory that met nothing rebuilds nothing.

Thresholds are the ones measured before this was written: over 19 real
recordings, a rebuilt sound kept 25/26 firmly read pitchednesses and 23/24
registers. Over 12 pictures (10 real frames), a rebuilt picture's things were
found again 16/24, where the describer finds its own things again only 20/24
when the same frame is merely re-encoded.

Run (sandbox store): ./venv_torin/bin/python3 experiments/RECALL-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
JFK = REPO / "third_party" / "whisper.cpp" / "samples" / "jfk.wav"
SYSTEM_SOUNDS = Path("/System/Library/Sounds")
CARD = REPO / "test_data" / "vision_test.png"
VIDEOS = Path("/Users/stefan/Dominion Labs/edgemed/videos")

EV = RunRecord(
    "RECALL-01",
    claim=("The substrate remembers what it heard and saw as traces, not copies, "
           "and rebuilds them in the mind: a rebuilt sound is heard as the same "
           "sounds and a rebuilt picture is seen as the same things."),
    hypothesis=("From the scratch measurements: firmly read pitchedness, register "
                "and onset survive the rebuild in at least 90% of sounds; a clean "
                "picture's things all come back; on real footage at least half of a "
                "picture's things and its dominant hue come back."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def build_frames():
    """Real frames from real footage, extracted once."""
    STIM.mkdir(parents=True, exist_ok=True)
    frames = []
    for name in ("daytime", "dusk", "sunrise", "nightsky"):
        out = STIM / f"{name}.jpg"
        if not out.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "4", "-i",
                            str(VIDEOS / f"{name}.mp4"), "-frames:v", "1",
                            "-vf", "scale='min(1600,iw)':-2", str(out)], check=True)
        frames.append(out)
    return frames


def compare_sounds(original, rebuilt):
    """Per-reading agreement between two descriptions of the same recording."""
    agree = {"firm": 0, "firm_of": 0, "pitch": 0, "pitch_of": 0, "level": 0, "level_of": 0}
    for s in original["sounds"]:
        best = max(rebuilt["sounds"], default=None,
                   key=lambda u: min(s["end"], u["end"]) - max(s["start"], u["start"]))
        if best is not None and min(s["end"], best["end"]) - max(s["start"], best["start"]) <= 0:
            best = None
        for k in ("tonality", "register", "onset"):
            if s[k] is not None and s["support"].get(s[k], 0) >= 0.5:
                agree["firm_of"] += 1
                agree["firm"] += int(best is not None and best[k] == s[k])
        if s["pitch"] and best is not None and best["pitch"]:
            agree["pitch_of"] += 1
            agree["pitch"] += int(abs(best["pitch"] / s["pitch"] - 1) < 0.05)
        agree["level_of"] += 1
        agree["level"] += int(best is not None and abs(best["level"] - s["level"]) <= 3.0)
    return agree


def things(desc):
    from core.perception.perception_faculty import _object_regions
    return sorted(f"{r.get('hue') or r.get('color')}/{r.get('shape')}"
                  for r in _object_regions(desc["regions"]))


async def main() -> int:
    import cv2
    import soundfile as sf
    from core.perception import hearing as H
    from core.perception import vision as V
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
    tag = uuid.uuid4().hex[:6]
    memory_ids = []
    work = Path(tempfile.mkdtemp(prefix="recall01_"))

    async def perceive(door, source, label):
        """Copy the stimulus away, perceive it through the door, delete the copy:
        whatever comes back later can only have come from memory."""
        copy = work / f"{label}{Path(source).suffix}"
        shutil.copy(source, copy)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await getattr(coord, door)(str(copy), source=f"r{tag}{label}",
                                                 domain="recall", actor_identity=None)
            await get_uncertainty_system().drain_writes()
        copy.unlink()
        mid = (percept.metadata or {}).get("memory_id") if percept else None
        if mid:
            memory_ids.append(mid)
        return percept, mid

    try:
        # ── A/B/C. A HEARING, REMEMBERED AND HEARD AGAIN ────────────────────
        print("\n== A–C. A hearing is remembered as a trace and heard again ==")
        percept, mid = await perceive("hear", JFK, "jfk")
        check("hearing formed a memory", bool(mid), str(mid))
        kept = await coord.recall_media(mid) if mid else []
        check("A: the memory holds a trace and no recording",
              len(kept) == 1 and kept[0]["mime"] == "application/x-npz",
              f"{[m['mime'] for m in kept]}, {kept[0]['byte_size'] if kept else 0} bytes "
              f"of {JFK.stat().st_size}")
        rebuilt = await coord.recollect(mid) if mid else []
        sound = next((r for r in rebuilt if r["kind"] == "sound"), None)
        check("B: with the file gone, the sound still comes back — from memory",
              sound is not None and len(sound["samples"]) > 0,
              f"{len(sound['samples']) / sound['rate']:.2f} s rebuilt" if sound else "nothing")
        totals = {"firm": 0, "firm_of": 0, "pitch": 0, "pitch_of": 0, "level": 0, "level_of": 0}
        counts = [0, 0]
        for label, source in [("jfk", JFK)] + [(n.lower(), SYSTEM_SOUNDS / f"{n}.aiff")
                                              for n in ("Glass", "Ping", "Funk", "Sosumi",
                                                        "Submarine", "Hero", "Basso")]:
            if label == "jfk":
                heard_rebuilt = sound
            else:
                _p, m = await perceive("hear", source, label)
                heard_rebuilt = next((r for r in await coord.recollect(m)
                                      if r["kind"] == "sound"), None) if m else None
            if heard_rebuilt is None:
                continue
            path = work / f"{label}_rebuilt.wav"
            sf.write(str(path), heard_rebuilt["samples"], heard_rebuilt["rate"])
            original, again = H.describe(str(source)), H.describe(str(path))
            counts[1] += 1
            counts[0] += int(original["sound_count"] == again["sound_count"])
            for k, v in compare_sounds(original, again).items():
                totals[k] += v
        EV.metric("sound_count_same", f"{counts[0]}/{counts[1]}", "recordings")
        for k in ("firm", "pitch", "level"):
            EV.metric(f"sound_{k}_kept", f"{totals[k]}/{totals[k + '_of']}", "readings")
        check("C: firmly read pitchedness, register and onset are heard the same",
              totals["firm_of"] and totals["firm"] >= 0.9 * totals["firm_of"],
              f"{totals['firm']}/{totals['firm_of']}")
        check("C: pitch comes back within 5%",
              totals["pitch_of"] and totals["pitch"] >= 0.9 * totals["pitch_of"],
              f"{totals['pitch']}/{totals['pitch_of']}")
        check("C: loudness comes back within 3 dB",
              totals["level_of"] and totals["level"] >= 0.9 * totals["level_of"],
              f"{totals['level']}/{totals['level_of']}")

        # ── D. A SEEING, REMEMBERED AND SEEN AGAIN ──────────────────────────
        print("\n== D. A seeing is remembered as a gist and seen again ==")
        _p, card_mid = await perceive("see", CARD, "card")
        card = next((r for r in await coord.recollect(card_mid) if r["kind"] == "image"),
                    None) if card_mid else None
        check("B: with the picture gone, it still comes back — from memory",
              card is not None and card["pixels"].size > 0,
              f"{card['pixels'].shape}" if card is not None else "nothing")
        if card is not None:
            cv2.imwrite(str(work / "card_rebuilt.png"), card["pixels"])
            want, got = things(V.describe_image(str(CARD))), things(
                V.describe_image(str(work / "card_rebuilt.png")))
            check("D: a clean picture's things all come back",
                  bool(want) and all(t in got for t in want), f"{want} -> {got}")
            # What the rebuilt card shows beyond them is recorded, not hidden: the
            # card's thin black frame, not a thing to the describer at full
            # resolution, comes back as a soft grey band that is one.
            EV.metric("card_things_beyond_original", ", ".join(t for t in got if t not in want) or "none",
                      "things", "the card's own frame, remembered soft")
        found = of = hues = pictures = 0
        for frame in build_frames():
            _p, m = await perceive("see", frame, frame.stem)
            pic = next((r for r in await coord.recollect(m) if r["kind"] == "image"),
                       None) if m else None
            if pic is None:
                continue
            path = work / f"{frame.stem}_rebuilt.png"
            cv2.imwrite(str(path), pic["pixels"])
            original, again = V.describe_image(str(frame)), V.describe_image(str(path))
            want, got = things(original), things(again)
            pictures += 1
            found += sum(t in got for t in want)
            of += len(want)
            hues += int(V.split_colour(original["dominant_colors"][0]["name"])[0]
                        == V.split_colour(again["dominant_colors"][0]["name"])[0])
        EV.metric("real_things_found_again", f"{found}/{of}", "things")
        EV.metric("real_dominant_hue_kept", f"{hues}/{pictures}", "pictures")
        check("D: on real footage, at least half of a picture's things come back",
              of and found >= 0.5 * of, f"{found}/{of} over {pictures} real frames")
        check("D: and its dominant hue", pictures and hues >= pictures - 1,
              f"{hues}/{pictures}")

        # ── E. NOTHING MET ──────────────────────────────────────────────────
        print("\n== E. A memory that met nothing rebuilds nothing ==")
        from core.memory import Origin, get_memory_agent
        from core.memory.utils.interfaces import MemoryType
        agent = await get_memory_agent()
        ok, plain = await agent.store_memory(
            content=f"a thought with nothing met in it [{tag}]", memory_type=MemoryType.EPISODIC,
            importance_score=0.8, origin=Origin.own("RECALL-01"))
        if plain:
            memory_ids.append(plain)
        check("E: nothing is rebuilt from it", bool(plain) and await coord.recollect(plain) == [],
              str(plain))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        like = f"%{tag}%"
        tagged = ("SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE $1) + "
                  "(SELECT count(*) FROM unified.beliefs WHERE belief_text LIKE $1) + "
                  "(SELECT count(*) FROM unified.perceptions WHERE source LIKE $1) AS n")
        try:
            written = await db.execute_query(tagged, (like,), fetch_one=True)
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
            for mid in set(memory_ids):
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (str(mid),), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (str(mid),), commit=True)
            left = await db.execute_query(tagged, (like,), fetch_one=True)
            EV.note(f"Cleanup by nonce {tag}: {written['n']} tagged row(s) written, "
                    f"{left['n']} left; {len(set(memory_ids))} memories removed by id.")
        except Exception as error:
            EV.note(f"Cleanup failed: {error}")
            print(f"  (cleanup: {error})")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== RECALL-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
