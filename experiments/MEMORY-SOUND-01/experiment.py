#!/usr/bin/env python3
"""MEMORY-SOUND-01 — memory recalls a sound by the sound itself.

Every hearing keeps its landmarks in its trace, and the memory agent is asked,
by the sound, whether it was heard before (`MemoryAgent.retrieve`, strategy
`sound`). This boots the real substrate and hears real recordings through
`coordinator.hear()`, asserting what happened at every stage and every seam.

  A  KEPT        the same recording heard twice is two memories, each keeping
                 its own trace, its landmarks in it.
  B  RECALLED    the second hearing recalls the first, by the sound: it says so
                 in words, in the graph (`same_sound_as`), and as a belief.
  C  A ROOM      six seconds of it played into a real room, through a codec,
                 recall both hearings.
  D  ANOTHER     a different recording recalls neither.
  E  RETRIEVE    memory's own recall finds a hearing by the sound, with how
                 much agreed, and recall by words is as it was.
  F  NAMED LATER a song heard untaught, then taught, names the earlier hearing:
                 the earlier recording is said to play it.
  G  INJECTED    the same sound's memories are injected into what is being
                 thought, saying they are this sound heard before.
  H  WHOSE       a person's hearing is recalled for that person, never for
                 another, nor for the substrate's own.
  I  A PURSUIT   what is heard and seen within a pursuit is part of its one
                 memory: no memory of its own, its trace and picture kept in
                 the pursuit's, said in its account, its beliefs naming it,
                 and the sound recalled later as that pursuit.

Recordings: GTZAN clips, a real room recorded from this Mac's microphone
(LIVE-01). Excerpts are built into `stimuli/` on first run.

Run (sandbox store): ./venv_torin/bin/python3 experiments/MEMORY-SOUND-01/experiment.py
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
ROOM = REPO / "experiments" / "LIVE-01" / "stimuli" / "room.wav"
HEARD = GTZAN / "blues" / "blues.00010.wav"          # heard twice, then in the room
OTHER = GTZAN / "classical" / "classical.00005.wav"  # another recording
SONG = GTZAN / "rock" / "rock.00020.wav"             # heard untaught, then taught
THEIRS = GTZAN / "jazz" / "jazz.00010.wav"           # a person's hearing
WITHIN = GTZAN / "hiphop" / "hiphop.00010.wav"       # heard within a pursuit
PICTURE = REPO / "test_data" / "vision_test.png"     # seen within it

EV = RunRecord(
    "MEMORY-SOUND-01",
    claim=("The memory agent recalls a sound by the sound itself: a recording heard again, "
           "through a room and a codec, is known as heard before -- in words, in the graph and "
           "as a belief -- each memory keeping its own sound; a song taught later names the "
           "hearings that came before; recall by sound is injected into what is thought; and "
           "a person's hearing is recalled only for that person."),
    hypothesis=("H1 the second hearing of a recording recalls the first by landmark agreement. "
                "H2 six seconds of it, in a real room through a 64 kbit/s codec, recall it. "
                "H3 a different recording recalls nothing. H4 a song taught names its earlier "
                "hearing. H5 recall by sound respects whose memories may be seen."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def excerpt(src: Path, name: str) -> Path:
    STIM.mkdir(parents=True, exist_ok=True)
    out = STIM / name
    if not out.exists():
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "12", "-t", "6", "-i", str(src), "-i", str(ROOM),
             "-filter_complex",
             "[0:a]volume=0.5[a];[1:a]volume=1.0[b];[a][b]amix=inputs=2:duration=first:normalize=0",
             "-ac", "1", "-b:a", "64k", str(out)], check=True)
    return out


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
    from core.perception import hearing as H
    from core.memory.media_store import get_media_store
    from core.memory import get_memory_agent
    from core.memory.utils.memory_injector import get_memory_injector, InjectionConfig
    from core.domain.evidence_producers import _term_like
    room_heard = excerpt(HEARD, "heard_in_the_room.mp3")
    room_theirs = excerpt(THEIRS, "theirs_in_the_room.mp3")

    tag = uuid.uuid4().hex[:6]
    DOMAIN = "hearing"
    memory_ids = []
    intents = []
    agent = await get_memory_agent()
    as_json = lambda v: json.loads(v) if isinstance(v, str) else (v or {})
    person_a, person_b = f"alex_{tag}", f"blair_{tag}"

    async def hear(path, label, who=None):
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.hear(str(path), source=f"m{tag}{label}", domain=DOMAIN,
                                       actor_identity=who)
            await get_uncertainty_system().drain_writes()
        meta = (percept.metadata or {}) if percept is not None else {}
        if meta.get("memory_id"):
            memory_ids.append(meta["memory_id"])
        return percept, meta.get("memory_id")

    async def edges_of(name):
        rows = await db.execute_query(
            "SELECT cr.relation AS rel, COALESCE(c2.name, cr.target_surface) AS obj "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE c1.name = $1", (name,), fetch_all=True) or []
        return {(str(r["rel"]), str(r["obj"])) for r in rows}

    def recalled(percept):
        return [e["memory"] for e in (percept.content.get("heard_before") or [])] if percept else []

    try:
        # ── A. KEPT ─────────────────────────────────────────────────────────
        print("\n== A. The same recording heard twice is two memories, each with its sound ==")
        first, first_id = await hear(HEARD, "x1")
        second, second_id = await hear(HEARD, "x2")
        kept = {m: await get_media_store().media_for_memory(str(m)) for m in (first_id, second_id)}
        check("two memories, each keeping its own trace",
              first_id and second_id and first_id != second_id
              and all(len(v) == 1 and v[0]["mime"] == "application/x-npz" for v in kept.values())
              and kept[first_id][0]["media_id"] != kept[second_id][0]["media_id"],
              f"{first_id}, {second_id}")
        marks = [H.trace_landmarks(v[0]["bytes"]) if v else None for v in kept.values()]
        check("and each trace keeps the sound's landmarks",
              all(m is not None and len(m) >= H.KNOWN_MIN_LANDMARKS for m in marks),
              str([0 if m is None else len(m) for m in marks]))

        # ── B. RECALLED ─────────────────────────────────────────────────────
        print("\n== B. The second hearing recalls the first, by the sound ==")
        before = second.content.get("heard_before") or [] if second else []
        check("the first hearing is recalled, fully resolved",
              [e["memory"] for e in before] == [first_id] and before[0]["support"] == 1.0,
              str([(e["memory"], e["share"], e["support"]) for e in before]))
        check("and first had nothing to recall", not recalled(first), str(recalled(first)))
        caption = second.content.get("caption", "") if second else ""
        import re
        check("the hearing says so in words, and when",
              re.search(r"heard before, 1 time\(s\), last on \d{4}-\d{2}-\d{2} \d{2}:\d{2}", caption)
              is not None, caption[-90:])
        row = await db.execute_query("SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
                                     (str(second_id),), fetch_one=True)
        check("and its memory says so", bool(row) and "heard before" in str(row["content"]),
              str(row["content"])[-90:] if row else None)
        link = ("same_sound_as", _term_like(first.source))
        check("the graph holds it: the second recording is the same sound as the first",
              link in await edges_of(second.source), f"{second.source} {link}")
        belief = await db.execute_query(
            "SELECT belief_text FROM unified.beliefs WHERE belief_text = $1",
            (f"{second.source} same_sound_as {_term_like(first.source)}",), fetch_one=True)
        check("and believes it", belief is not None, str(belief["belief_text"]) if belief else None)

        # ── C. A ROOM ───────────────────────────────────────────────────────
        print("\n== C. Six seconds of it, in a real room through a codec, recall it ==")
        roomed, _ = await hear(room_heard, "room")
        check("both hearings are recalled", set(recalled(roomed)) == {first_id, second_id},
              str([(e["memory"], e["share"]) for e in (roomed.content.get("heard_before") or [])]))

        # ── D. ANOTHER ──────────────────────────────────────────────────────
        print("\n== D. A different recording recalls neither ==")
        other, _ = await hear(OTHER, "other")
        check("nothing is recalled", other is not None and not recalled(other), str(recalled(other)))

        # ── E. RETRIEVE ─────────────────────────────────────────────────────
        print("\n== E. Memory's own recall finds a hearing by the sound ==")
        probe = H.landmarks(H.decode(str(room_heard)))
        found = await agent.retrieve(strategies=["sound"], heard=probe, actor=None, limit=5)
        scores = {m.memory_id: getattr(m, "similarity_score", None) for m in found}
        check("by the sound, with how much agreed",
              {first_id, second_id} <= set(scores) and all((s or 0) >= 0.1 for s in scores.values()),
              str(scores))
        words = await agent.retrieve(query="heard before", strategies=["keyword"], actor=None,
                                     limit=20)
        check("and recall by words is as it was", second_id in {m.memory_id for m in words},
              f"{len(words)} found by words")

        # ── F. NAMED LATER ──────────────────────────────────────────────────
        print("\n== F. A song taught later names the hearing that came before ==")
        untaught, untaught_id = await hear(SONG, "song")
        title = f"rock twenty {tag}"
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            lesson_id = await coord.learn_song(title, str(SONG), actor_identity=None,
                                               source=f"m{tag}lesson", domain=DOMAIN)
            await get_uncertainty_system().drain_writes()
        memory_ids.append(lesson_id)
        media = await get_media_store().media_for_memory(str(lesson_id))
        taught_before = [e["memory"] for e in (media[0]["perceived"].get("heard_before") or [])] \
            if media else []
        check("the lesson recalled the earlier hearing", untaught_id in taught_before,
              str(taught_before))
        named = ("plays", _term_like(title))
        check("and the earlier recording is now said to play the song",
              named in await edges_of(untaught.source), f"{untaught.source} plays {_term_like(title)}")

        # ── G. INJECTED ─────────────────────────────────────────────────────
        print("\n== G. The same sound's memories are injected into what is thought ==")
        injected = await get_memory_injector().inject_memories(
            query="", config=InjectionConfig(max_memories=5, min_importance_score=0.0),
            actor=None, heard=probe)
        text = injected.formatted_text or ""
        check("they are injected, saying they are this sound heard before",
              {first_id, second_id} <= set(injected.memory_ids)
              and "(heard before: the same sound" in text, text[:200])

        # ── H. WHOSE ────────────────────────────────────────────────────────
        print("\n== H. A person's hearing is recalled only for that person ==")
        theirs, theirs_id = await hear(THEIRS, "theirs", who=person_a)
        for_b, _ = await hear(room_theirs, "forb", who=person_b)
        for_self, _ = await hear(room_theirs, "forself", who=None)
        for_a, _ = await hear(room_theirs, "fora", who=person_a)
        check("not for another person", theirs_id not in recalled(for_b), str(recalled(for_b)))
        check("nor for the substrate's own", theirs_id not in recalled(for_self),
              str(recalled(for_self)))
        check("but for them", theirs_id in recalled(for_a), str(recalled(for_a)))

        # ── I. A PURSUIT ────────────────────────────────────────────────────
        print("\n== I. What is heard and seen within a pursuit is part of its one memory ==")
        from core.agents.autonomous.shared_types import Priority, Task, TaskType
        from core.reasoning.intent_authority import reset_acting_intent, set_acting_intent
        task = Task(id=f"memsound_{tag}", type=TaskType.EXECUTION, priority=Priority.LOW,
                    description=f"listen and look for memsound {tag}")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            intent_id = await coord.intend(task, pursuit="memsound_probe")
        intents.append(intent_id)
        pursuit_id = (getattr(task, "provenance", None) or {}).get("pursuit_memory_id")
        memory_ids.append(pursuit_id)
        token = set_acting_intent(intent_id)
        try:
            heard_in, heard_in_id = await hear(WITHIN, "within")
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                seen_in = await coord.see(str(PICTURE), source=f"m{tag}seen", domain="vision",
                                          actor_identity=None)
                await get_uncertainty_system().drain_writes()
        finally:
            reset_acting_intent(token)
        seen_in_id = (seen_in.metadata or {}).get("memory_id") if seen_in else None
        check("the hearing and the seeing are the pursuit's memory, not memories of their own",
              pursuit_id and heard_in_id == pursuit_id and seen_in_id == pursuit_id,
              f"pursuit {pursuit_id}, heard {heard_in_id}, seen {seen_in_id}")
        media = await get_media_store().media_for_memory(str(pursuit_id)) if pursuit_id else []
        check("its memory keeps the sound's trace and the picture",
              sorted(m["mime"].split("/")[0] for m in media) == ["application", "image"],
              str([m["mime"] for m in media]))
        row = await db.execute_query("SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
                                     (str(pursuit_id),), fetch_one=True)
        said = str(row["content"]) if row else ""
        check("and says what was heard and seen in it", " I heard " in said and " I saw " in said,
              said[:200])
        named = await db.execute_query(
            "SELECT count(*) AS n, count(*) FILTER (WHERE memory_id = $2) AS m "
            "FROM unified.beliefs WHERE belief_text LIKE $1",
            (f"{heard_in.source} %", str(pursuit_id)), fetch_one=True) if heard_in else None
        check("what was heard is believed, of the pursuit's memory",
              named is not None and named["n"] > 0 and named["m"] == named["n"],
              f"{named['m'] if named else 0} of {named['n'] if named else 0} beliefs")
        later, _ = await hear(WITHIN, "later")
        check("heard again later, it is recalled as that pursuit", pursuit_id in recalled(later),
              str(recalled(later)))
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
                "SELECT memory_id FROM memory_hot.memory_hot WHERE content::text LIKE $1 "
                "OR user_id LIKE $1", (like,), fetch_all=True) or []
            for mid in set(map(str, filter(None, memory_ids))) | {str(r["memory_id"]) for r in tagged}:
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (mid,), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (mid,), commit=True)
            for intent_id in filter(None, intents):
                await db.execute_query("DELETE FROM unified.scoped_intents WHERE intent_id = $1",
                                       (intent_id,), commit=True)
                await db.execute_query("DELETE FROM unified.intents WHERE intent_id = $1",
                                       (intent_id,), commit=True)
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
    print(f"\n==== MEMORY-SOUND-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
