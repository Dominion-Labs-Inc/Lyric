#!/usr/bin/env python3
"""LIVE-01 — always listening and looking, keeping only what is said to it.

The live senses (`core.perception.live`) listen to a microphone and look at a
camera for as long as the substrate runs. The ear cuts what it hears into
utterances and keeps one only when the substrate's NAME was said in it, or
when it follows one that was; everything else is dropped inside the ear's own
process. Each kept utterance is heard through the one door (`coord.hear`) and
the scene looked at (`coord.see`); a complete hearing goes to the one front
door a typed message goes to (`coord.handle_user_request`).

This runs the real ear and eye programs against a stream played in real time,
exactly as a device feeds them: a real room (recorded from this Mac's
microphone) with a speaker in it (the classic, rule-based macOS voice "Fred"),
and real video footage for the camera.

  A  UNNAMED     before its name is taught, what is said -- even its name -- is
                 let pass, and it says why.
  B  TAUGHT LIVE a name taught while it listens is listened for from then on.
  C  ADDRESSED   what is said to it is kept; what follows within attention is
                 kept without the name; everything else is let pass.
  D  DROPPED     nothing let pass reaches the substrate: no percept, no memory.
  E  REMEMBERED  each kept utterance is a hearing, remembered in words, as a
                 trace; the recording is never kept, on disk or in memory.
  F  LOOKED      the scene is looked at when it is spoken to.
  G  ANSWERED    a complete hearing (every word a taught word) goes to the
                 front door, without its name, into the same conversation memory
                 typed words go to; an incomplete one is remembered and not
                 acted on. Three questions are said to it; how many come
                 through complete is recorded.
  H  STOPPED     the ear and the eye stop with the live senses.

Run (sandbox store): ./venv_torin/bin/python3 experiments/LIVE-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import random
import string
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
JELLYFISH = REPO / "test_data" / "jellyfish_real_10s.mp4"
N = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
NAME = "torin"
WORDS = ("are", "mammals", "animals", "do", "birds", "fly", "cats")
RATES = (140, 165, 190, 215, 240)
VOICE = "Fred"

EV = RunRecord(
    "LIVE-01",
    claim=("The running substrate listens and looks all the time and keeps only what is "
           "said to it: an utterance with its taught name in it, and what follows within "
           "attention, is heard, remembered in words, looked at and answered through the "
           "front door; everything else is dropped inside the ear and never reaches it."),
    hypothesis=("An utterance is kept exactly when the taught name is found in it or it "
                "follows a kept one within ATTENTION_SECONDS; a name taught while listening "
                "is listened for within the ear's re-teach interval; nothing dropped leaves a "
                "percept or a memory; the recording is never kept."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def say(path: Path, text: str, rate: int) -> Path:
    if not path.exists():
        subprocess.run(["say", "-v", VOICE, "-r", str(rate), "-o", str(path), text], check=True)
    return path


def build_stimuli() -> dict:
    """Lessons (each word said alone at five rates, with the room around it) and
    one stream: the room, with things said in it, in real time order."""
    import numpy as np
    import soundfile as sf
    from core.perception import hearing as H
    room = H.decode(str(STIM / "room.wav"))
    room = room[int(0.5 * H.SR):]                     # past the microphone's start

    def quiet(seconds, offset=[0]):
        n = int(seconds * H.SR)
        out = np.resize(np.roll(room, -offset[0]), n)
        offset[0] = (offset[0] + n) % len(room)
        return out

    def in_room(y):
        return np.concatenate([quiet(0.4), y, quiet(0.4)])

    lessons = {}
    for word in (NAME,) + WORDS:
        lessons[word] = []
        for rate in RATES:
            path = STIM / f"lesson_{word}_{rate}.wav"
            if not path.exists():
                spoken = H.decode(str(say(STIM / f"_{word}_{rate}.aiff", word, rate)))
                sf.write(str(path), in_room(spoken).astype(np.float32), H.SR)
            lessons[word].append(path)
    lines = {
        "early": ("Torin [[slnc 300]] are [[slnc 300]] mammals [[slnc 300]] animals?", 180),
        "other": ("are cats animals?", 185),
        "addressed": ("Torin [[slnc 300]] are [[slnc 300]] mammals [[slnc 300]] animals?", 180),
        "follow": ("yesterday [[slnc 300]] birds [[slnc 300]] fly", 180),
        "addressed2": ("Torin [[slnc 300]] do [[slnc 300]] birds [[slnc 300]] fly?", 180),
        "addressed3": ("Torin [[slnc 300]] are [[slnc 300]] cats [[slnc 300]] animals?", 180),
        "late": ("are mammals animals?", 175),
    }
    said = {k: H.decode(str(say(STIM / f"_{k}.aiff", t, r))) for k, (t, r) in lines.items()}
    stream = STIM / "stream.wav"
    if not stream.exists():
        parts = [quiet(2.5), said["early"], quiet(30.0), said["other"], quiet(2.0),
                 said["addressed"], quiet(2.5), said["follow"], quiet(12.0),
                 said["addressed2"], quiet(3.0), said["addressed3"], quiet(12.0),
                 said["late"], quiet(2.5)]
        sf.write(str(stream), np.concatenate(parts).astype(np.float32), H.SR)
    return {"lessons": lessons, "stream": stream}


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()          # its services, not its cognition cycle
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
    await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    from core.perception.live import ATTENTION_SECONDS, LiveSenses
    from core.agents.autonomous.shared_types import TaskSource, actor_for
    stim = build_stimuli()
    session = f"LIVE-01-{N}"
    actor = actor_for(TaskSource.MANUAL, session)
    memory_ids, task_ids = [], []
    vocab = (NAME,) + WORDS
    before = {r["concept_id"] for r in await db.execute_query(
        "SELECT concept_id FROM unified.concepts WHERE name = ANY($1::text[])",
        (list(vocab),), fetch_all=True) or []}
    live = None
    try:
        # ── the words it knows, but not yet its name ────────────────────────
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            for word in WORDS:
                for k, path in enumerate(stim["lessons"][word]):
                    memory_ids.append(await coord.learn_word(
                        word, str(path), actor_identity=None, source=f"t{N}{word}{k}",
                        domain="hearing"))
        # WHAT IT IS ASKED, IT IS TAUGHT FIRST. A lesson's examples are how
        # English says things, never facts about the world, so nothing holds
        # "a mammal is an animal" unless it is taught as a fact.
        held = await db.execute_query(
            "SELECT 1 FROM unified.concept_relations cr JOIN unified.concepts c "
            "ON cr.source_concept_id = c.concept_id WHERE c.name = 'mammal' "
            "AND cr.relation = 'isa' AND cr.target_surface = 'animal' LIMIT 1", (), fetch_one=True)
        if not held:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                await coord.learning.learn_fact("mammal", "isa", "animal", domain="general")
            EV.note("taught 'a mammal is an animal' (left in place, as SENSES-TOGETHER-01 does)")
        live = LiveSenses(coord, microphone=f"file:{stim['stream']}", camera=f"file:{JELLYFISH}",
                          name=NAME, session=session, label=f"l{N}")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await live.start()
        started = time.monotonic()

        # ── A. UNNAMED ──────────────────────────────────────────────────────
        print("\n== A. Before its name is taught ==")
        while live.account["passed"] < 1 and time.monotonic() - started < 20:
            await asyncio.sleep(0.2)
        check("what is said before its name is taught is let pass, even its name",
              live.account["passed"] >= 1 and not live.account["kept"],
              f"{live.account['passed']} let pass, {len(live.account['kept'])} kept")
        check("and it says why",
              any("never taught" in s for s in live.account["status"]),
              next((s for s in live.account["status"] if "never taught" in s), None))

        # ── B. TAUGHT LIVE ──────────────────────────────────────────────────
        print("\n== B. Its name, taught while it listens ==")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            for k, path in enumerate(stim["lessons"][NAME]):
                memory_ids.append(await coord.learn_word(
                    NAME, str(path), actor_identity=None, source=f"t{N}{NAME}{k}",
                    domain="hearing"))
        while live._taught_version != coord.vision.taught_version and \
                time.monotonic() - started < 40:
            await asyncio.sleep(0.2)
        taught_at = time.monotonic() - started
        check("a name taught while it listens is listened for from then on",
              live._taught_version == coord.vision.taught_version and taught_at < 32,
              f"the ear re-taught {taught_at:.1f}s into a stream that speaks again at 34s")

        # ── the rest of the stream ──────────────────────────────────────────
        while not any("ended" in s for s in live.account["status"]) and \
                time.monotonic() - started < 120:
            await asyncio.sleep(0.5)
        await asyncio.sleep(3.0)           # the last utterance's hearing, if any
        kept = [r for r in live.account["kept"] if "error" not in r]
        for r in kept:
            memory_ids += [m for m in (r.get("heard_memory"), r.get("seen_memory")) if m]
            reply = r.get("reply") or {}
            if reply.get("task_id"):
                task_ids.append(reply["task_id"])

        # ── C. ADDRESSED ────────────────────────────────────────────────────
        print("\n== C. What is said to it, and nothing else, is kept ==")
        check("what was said to it by name is kept",
              bool(kept) and kept[0]["named"] and NAME in kept[0]["heard_text"].split(),
              f"heard \"{kept[0]['heard_text']}\"" if kept else "nothing kept")
        check(f"what followed within {ATTENTION_SECONDS:.0f}s is kept without the name",
              len(kept) >= 2 and not kept[1]["named"],
              f"heard \"{kept[1]['heard_text']}\"" if len(kept) > 1 else "nothing followed")
        check("and nothing else: only the three questions said to it and the talk that followed",
              len(kept) == 4 and [r["named"] for r in kept] == [True, False, True, True],
              f"{len(kept)} kept; {live.account['passed']} let pass "
              f"({live.account['passed_seconds']}s), questions and the room's own sounds")
        EV.metric("let_pass", live.account["passed"], "utterances")
        EV.metric("let_pass_seconds", live.account["passed_seconds"], "s")

        # ── D. DROPPED ──────────────────────────────────────────────────────
        print("\n== D. Nothing let pass reaches the substrate ==")
        percepts = await db.execute_query(
            "SELECT data_type, count(*) AS n FROM unified.perceptions WHERE source LIKE $1 "
            "GROUP BY data_type", (f"l{N}%",), fetch_all=True) or []
        by = {str(r["data_type"]): int(r["n"]) for r in percepts}
        check("the only percepts are of what was kept: one hearing and one seeing each",
              by.get("audio", 0) == len(kept) and by.get("image", 0) == len(kept),
              f"{by}")

        # ── E. REMEMBERED ───────────────────────────────────────────────────
        print("\n== E. Kept, it is a hearing remembered in words ==")
        rows = {}
        for r in kept:
            row = await db.execute_query(
                "SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
                (str(r.get("heard_memory")),), fetch_one=True)
            rows[r["heard_memory"]] = str(row["content"]) if row else ""
        check("each kept utterance is a hearing memory that says what was heard",
              kept and all(r["heard_memory"] and all(w in rows[r["heard_memory"]]
                                                       for w in r["heard_text"].split() if w != "...")
                           for r in kept),
              "; ".join(rows.get(r["heard_memory"], "")[-70:] for r in kept))
        from core.memory.media_store import get_media_store
        media = [m for r in kept for m in await get_media_store().media_for_memory(str(r["heard_memory"]))]
        check("remembered as a trace, never the recording",
              media and all(m["mime"] == "application/x-npz"
                            and (m["perceived"] or {}).get("kind") == "sound_trace" for m in media),
              ", ".join(f"{m['mime']} {m['byte_size']}B" for m in media))
        check("and no recording is left on disk",
              not any(live._dir.glob("*")), f"{len(list(live._dir.glob('*')))} file(s) in {live._dir}")

        # ── F. LOOKED ───────────────────────────────────────────────────────
        print("\n== F. The scene is looked at when it is spoken to ==")
        seen = []
        for r in kept:
            got = await get_media_store().media_for_memory(str(r.get("seen_memory")))
            seen.append(bool(got) and str(got[0]["mime"]).startswith("image/")
                        and bool((got[0]["perceived"] or {}).get("gist")))
        check("each time it was spoken to, what it saw is remembered with its gist",
              kept and all(seen), f"{sum(seen)} of {len(kept)}")

        # ── G. ANSWERED ─────────────────────────────────────────────────────
        print("\n== G. What was said to it is answered, in the one conversation ==")
        complete = [r for r in kept if r.get("complete")]
        partial = [r for r in kept if not r.get("complete")]
        EV.metric("heard_complete", f"{len(complete)}/{len(kept)}", "utterances",
                  "; ".join(repr(r["heard_text"]) for r in kept))
        check("at least one hearing came through complete, so the front door is reached",
              bool(complete), "; ".join(repr(r["heard_text"]) for r in kept))
        check("every complete hearing went to the front door, without the name it was called by",
              complete and all(r.get("asked") and NAME not in r["asked"].split()
                               and r["asked"] == " ".join(w for w in r["heard_text"].split() if w != NAME)
                               for r in complete),
              "; ".join(repr(r.get("asked")) for r in complete))
        check("and the front door took each one in",
              complete and all((r.get("reply") or {}).get("success") for r in complete),
              "; ".join(repr((r.get("reply") or {}).get("answer")
                             or (r.get("reply") or {}).get("task_id")) for r in complete))
        answered = [r for r in complete if (r.get("reply") or {}).get("answer")]
        exchanges = await db.execute_query(
            "SELECT content FROM memory_hot.memory_hot WHERE user_id = $1 AND tags::text LIKE $2",
            (actor, "%user_exchange%"), fetch_all=True) or []
        check("what it answered is in the same conversation memory typed words go to",
              all(any(r["asked"] in str(e["content"]) for e in exchanges) for r in answered),
              f"{len(answered)} answered; " + "; ".join(str(e["content"])[:70] for e in exchanges))
        mammals = next((r for r in complete if r.get("asked") == "are mammals animals"), None)
        said_back = str(((mammals or {}).get("reply") or {}).get("answer") or "")
        check("asked aloud whether mammals are animals, it answers yes, from what it was taught",
              said_back.startswith("Yes"), said_back[:120] or "not asked complete")
        check("an incomplete hearing is remembered and not acted on",
              all("asked" not in r and r.get("heard_memory") for r in partial),
              "; ".join(repr(r["heard_text"]) for r in partial) or "none was incomplete")
    finally:
        # ── H. STOPPED ──────────────────────────────────────────────────────
        if live is not None:
            programs = [p for p in (live._ear, live._eye) if p is not None]
            await live.stop()
            print("\n== H. The ear and the eye stop ==")
            check("the ear and the eye stop with the live senses",
                  programs and all(p.returncode is not None for p in programs)
                  and not live._dir.exists(),
                  f"{len(programs)} program(s) stopped")
        # ── cleanup: by nonce, by exact id, by the run's own speaker ────────
        like = f"%{N}%"
        try:
            concepts = [r["concept_id"] for r in await db.execute_query(
                "SELECT concept_id FROM unified.concepts WHERE name ILIKE $1", (like,),
                fetch_all=True) or []]
            # A word concept this run brought into being (none was there before).
            concepts += [r["concept_id"] for r in await db.execute_query(
                "SELECT concept_id FROM unified.concepts WHERE name = ANY($1::text[])",
                (list(vocab),), fetch_all=True) or [] if r["concept_id"] not in before]
            envelopes = [r["evidence_id"] for r in await db.execute_query(
                "SELECT evidence_id FROM unified.evidence_envelopes WHERE content ILIKE $1 "
                "OR source_id ILIKE $1 OR producer ILIKE $1", (like,), fetch_all=True) or []]
            if concepts or envelopes:
                await db.execute_query(
                    "DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
                    "OR target_concept_id = ANY($1::text[]) OR evidence_id = ANY($2::text[]) "
                    "OR target_surface ILIKE $3", (concepts, envelopes, like), commit=True)
                for t in ("concept_domains", "concept_evidence"):
                    await db.execute_query(f"DELETE FROM unified.{t} WHERE concept_id = ANY($1::text[]) "
                                           f"OR evidence_id = ANY($2::text[])", (concepts, envelopes),
                                           commit=True)
                await db.execute_query("DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1::text[])",
                                       (concepts,), commit=True)
                await db.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])",
                                       (concepts,), commit=True)
                await db.execute_query("DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                                       (envelopes,), commit=True)
            for table, col in (("unified.beliefs", "belief_text"), ("unified.perceptions", "source"),
                               ("unified.experience_pool", "about")):
                await db.execute_query(f"DELETE FROM {table} WHERE {col} ILIKE $1", (like,), commit=True)
            spoken = [r["memory_id"] for r in await db.execute_query(
                "SELECT memory_id FROM memory_hot.memory_hot WHERE user_id = $1", (actor,),
                fetch_all=True) or []]
            for mid in set(map(str, memory_ids)) | set(map(str, spoken)):
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (mid,), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (mid,), commit=True)
            for t in ("scoped_beliefs", "scoped_concept_relations"):
                await db.execute_query(f"DELETE FROM unified.{t} WHERE scope_actor = $1", (actor,),
                                       commit=True)
            if task_ids:
                await db.execute_query("DELETE FROM unified.task_queue WHERE task_id = ANY($1::text[])",
                                       (task_ids,), commit=True)
            left = await db.execute_query(
                "SELECT (SELECT count(*) FROM unified.concepts WHERE name ILIKE $1) + "
                "(SELECT count(*) FROM unified.perceptions WHERE source ILIKE $1) + "
                "(SELECT count(*) FROM memory_hot.memory_hot WHERE user_id = $2) AS n",
                (like, actor), fetch_one=True)
            EV.note(f"Cleanup by nonce {N}, exact ids and the run's speaker {actor}: "
                    f"{len(concepts)} concepts, {len(set(memory_ids) | set(spoken))} memories, "
                    f"{len(task_ids)} task(s); {left['n']} left.")
        except Exception as error:
            EV.note(f"Cleanup failed: {error}")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== LIVE-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
