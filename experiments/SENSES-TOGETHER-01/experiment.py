#!/usr/bin/env python3
"""SENSES-TOGETHER-01 — the substrate hears, sees and reasons at the same time.

Hearing and sight stay first-class parts of the substrate -- one faculty, one
perception pipeline, one memory -- but each sense measures in a process of its
own (`core.perception.senses`), so neither holds the substrate's loop while it
measures. This boots the whole running system and asks it to hear a real
recording, see a real video frame and answer a question that needs reasoning,
alone and in every combination at once.

  A  ALONE       each on its own: heard, seen, answered.
  B  TOGETHER    hear + reason, see + reason, hear + see, all three: every result
                 right, each memory holding its own sound or picture, the
                 substrate's loop never held long, and reasoning not queued
                 behind what is being perceived.
  C  PROCESSES   sight and hearing are each a process of their own.
  D  RECOVERY    a sense whose process dies -- while perceiving or while idle --
                 is reported and started again, and the perception completes.
  E  SHUTDOWN    the senses' processes stop with the substrate.

Measured before the change (2026-09-28, same stimuli): sight held the loop for
1.4 s at a stretch, and a question answered in 0.3 s waited 1.4 s behind a
picture. The thresholds below were fixed before this experiment first ran.

Run (sandbox store): ./venv_torin/bin/python3 experiments/SENSES-TOGETHER-01/experiment.py
"""
from __future__ import annotations

import asyncio
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
from experiments._isolation import boot, db, shutdown  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
JFK = REPO / "third_party" / "whisper.cpp" / "samples" / "jfk.wav"
JELLYFISH = REPO / "test_data" / "jellyfish_real_10s.mp4"
N = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
V = f"vex{N}"
#: Fixed before the first run.
LOOP_HELD_MS = 100          # was 1,400
REASON_SLOWER = 3.0         # reasoning beside perception, against reasoning alone

EV = RunRecord(
    "SENSES-TOGETHER-01",
    claim=("The running substrate hears, sees and reasons at the same time: each sense "
           "measures in its own process, so hearing, sight and reasoning run together "
           "in every combination, each result right and each memory its own."),
    hypothesis=(f"With each sense in its own process the substrate's loop is never held more "
                f"than {LOOP_HELD_MS} ms (it was 1,400 ms), and a question asked while it "
                f"hears and sees is answered within {REASON_SLOWER}x its time alone and before "
                f"the perceptions beside it finish."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def build_stimuli() -> dict:
    """Real footage and a real recording; each run of each combination gets its
    own copy, so no two hearings or seeings are the same file met twice."""
    import numpy as np
    import soundfile as sf
    from core.perception import hearing as H
    STIM.mkdir(parents=True, exist_ok=True)
    y = H.decode(str(JFK))
    out = {"sounds": [], "frames": []}
    for k in range(6):
        path = STIM / f"jfk_{k}.wav"
        if not path.exists():
            sf.write(str(path), np.concatenate([np.zeros(441 * (k + 1)), y]).astype(np.float32), H.SR)
        out["sounds"].append(path)
        frame = STIM / f"jellyfish_{k}.jpg"
        if not frame.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(1 + 1.3 * k), "-i",
                            str(JELLYFISH), "-frames:v", "1", "-q:v", "2", str(frame)], check=True)
        out["frames"].append(frame)
    return out


class Heartbeat:
    """Ticks every 5 ms; the longest gap is how long nothing else could run."""

    def __init__(self):
        self.gaps, self.running = [], True

    async def run(self):
        last = time.perf_counter()
        while self.running:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            self.gaps.append(now - last)
            last = now


async def main() -> int:
    stim = build_stimuli()
    system, coord = await boot()
    d = db()
    await d.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    from core.memory.media_store import get_media_store
    memory_ids, actors, killed = [], [], []
    faculty = coord.vision
    try:
        A = coord.conversation(f"SENSES-TOGETHER-01-{N}")
        actors.append(A._actor)
        held = await d.execute_query(
            "SELECT 1 FROM unified.concept_relations cr JOIN unified.concepts c "
            "ON cr.source_concept_id = c.concept_id WHERE c.name = 'mammal' "
            "AND cr.relation = 'isa' AND cr.target_surface = 'animal' LIMIT 1", (), fetch_one=True)
        if not held:
            await coord.learning.learn_fact("mammal", "isa", "animal", domain="general")
            EV.note("taught 'a mammal is an animal' (left in place, as SYSTEM-CONVERSATION-01 does)")
        await A.understand(f"a {V} is a mammal", look_up=False)
        sounds, frames = iter(stim["sounds"]), iter(stim["frames"])

        def hear(label):
            return coord.hear(str(next(sounds)), actor_identity=None, source=f"t{N}{label}",
                              domain="hearing")

        def see(label):
            return coord.see(str(next(frames)), actor_identity=None, source=f"t{N}{label}",
                             domain="vision")

        async def reason():
            return type(A).say(await A.understand(f"is a {V} an animal", look_up=False))

        async def run(label, jobs):
            beat = Heartbeat()
            hb = asyncio.create_task(beat.run())
            spans = {}

            async def timed(name, coro):
                t = time.perf_counter()
                result = await coro
                spans[name] = (t, time.perf_counter())
                return result
            t0 = time.perf_counter()
            got = dict(zip(jobs, await asyncio.gather(*(timed(n, j) for n, j in jobs.items()))))
            wall = time.perf_counter() - t0
            beat.running = False
            await hb
            held = max(beat.gaps) * 1000
            for p in got.values():
                meta = getattr(p, "metadata", None) or {}
                if meta.get("memory_id"):
                    memory_ids.append(meta["memory_id"])
            took = {n: round(b - a, 2) for n, (a, b) in spans.items()}
            print(f"   {label}: wall {wall:.2f}s, took {took}, loop held at most {held:.0f} ms")
            return got, took, held, spans

        async def own(label, percept, kind):
            """Is this percept's memory its own: its own caption, its own kind of thing kept?"""
            mid = ((percept.metadata or {}) if percept else {}).get("memory_id")
            row = await d.execute_query("SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1",
                                        (str(mid),), fetch_one=True) if mid else None
            media = await get_media_store().media_for_memory(str(mid)) if mid else []
            kept = [str((m["perceived"] or {}).get("kind") or m["mime"]) for m in media]
            return (bool(row) and str(percept.content.get("caption"))[:30] in str(row["content"])
                    and any(kind in k for k in kept))

        def answered(text):
            return isinstance(text, str) and text.startswith("Yes") and V in text

        # ── A. ALONE ────────────────────────────────────────────────────────
        print("\n== A. Each on its own ==")
        alone = {}
        for name, job in (("hear", lambda: hear("ah")), ("see", lambda: see("as")),
                          ("reason", reason)):
            got, took, held, _ = await run(name, {name: job()})
            alone[name] = (got[name], took[name])
        check("a recording is heard", alone["hear"][0] is not None
              and len(alone["hear"][0].content.get("blobs") or []) >= 4,
              alone["hear"][0].content.get("caption", "")[:70] if alone["hear"][0] else None)
        check("a video frame is seen", alone["see"][0] is not None
              and bool(alone["see"][0].content.get("blobs")),
              alone["see"][0].content.get("caption", "")[:70] if alone["see"][0] else None)
        check("a question is answered by reasoning", answered(alone["reason"][0]),
              repr(alone["reason"][0]))
        for name in alone:
            EV.metric(f"{name}_alone_s", alone[name][1], "s")

        # ── B. TOGETHER ─────────────────────────────────────────────────────
        print("\n== B. Together, in every combination ==")
        combos = (("hear + reason", {"hear": hear("bh"), "reason": reason()}),
                  ("see + reason", {"see": see("bs"), "reason": reason()}),
                  ("hear + see", {"hear": hear("ch"), "see": see("cs")}),
                  ("hear + see + reason", {"hear": hear("dh"), "see": see("ds"), "reason": reason()}))
        worst_held = 0.0
        for label, jobs in combos:
            got, took, held, spans = await run(label, jobs)
            worst_held = max(worst_held, held)
            right = []
            if "hear" in got:
                right.append(await own("hearing", got["hear"], "sound_trace"))
            if "see" in got:
                right.append(await own("seeing", got["see"], "image"))
            if "reason" in got:
                right.append(answered(got["reason"]))
            check(f"{label}: every result is right, each memory its own", all(right),
                  f"{sum(right)} of {len(right)}")
            if "reason" in got:
                slower = took["reason"] / max(alone["reason"][1], 0.01)
                last_perception = max(b for n, (a, b) in spans.items() if n != "reason")
                check(f"{label}: reasoning is not queued behind the perceiving",
                      slower <= REASON_SLOWER and spans["reason"][1] < last_perception,
                      f"{took['reason']}s beside it, {alone['reason'][1]}s alone ({slower:.1f}x)")
                EV.metric(f"reason_beside_{label.replace(' + ', '_')}_s", took["reason"], "s")
            EV.metric(f"loop_held_ms_{label.replace(' + ', '_')}", round(held), "ms")
        check(f"the substrate's loop was never held more than {LOOP_HELD_MS} ms (was 1,400)",
              worst_held <= LOOP_HELD_MS, f"at most {worst_held:.0f} ms")

        # ── C. PROCESSES ────────────────────────────────────────────────────
        print("\n== C. Each sense is a process of its own ==")
        sight_pid = faculty._sight._proc.pid if faculty._sight._proc else None
        hearing_pid = faculty._hearing._proc.pid if faculty._hearing._proc else None
        check("sight and hearing each measure in a process of their own",
              sight_pid and hearing_pid and len({sight_pid, hearing_pid, os.getpid()}) == 3,
              f"substrate {os.getpid()}, sight {sight_pid}, hearing {hearing_pid}")

        # ── D. RECOVERY ─────────────────────────────────────────────────────
        print("\n== D. A sense found dead is started again, and the perception kept ==")
        import logging
        told = io.StringIO()
        handler = logging.StreamHandler(told)
        logging.getLogger("core.perception.senses").addHandler(handler)
        clip = str(JELLYFISH)
        await faculty.sense(clip)                         # sight is warm
        before = faculty._sight._proc.pid
        perceiving = asyncio.create_task(faculty.sense(clip))
        await asyncio.sleep(0.3)                          # seeing the clip takes ~1.8 s
        faculty._sight._proc.kill()
        _modality, seen = await perceiving
        check("killed while perceiving, the sense is started again and the perception completes",
              bool(seen.get("caption")) and faculty._sight._proc.pid != before,
              f"sight {before} -> {faculty._sight._proc.pid}: {seen.get('caption', '')[:40]}")
        check("and its death is reported, not passed over",
              f"sight process (pid {before}) had died" in told.getvalue(),
              told.getvalue().strip()[:100])
        killed.append(before)
        idle = faculty._hearing._proc.pid
        killed.append(idle)
        faculty._hearing._proc.kill()                     # dies while idle
        _modality, heard = await faculty.sense(str(stim["sounds"][0]))
        check("a sense that died while idle does not cost the next perception",
              bool(heard.get("blobs")) and faculty._hearing._proc.pid != idle,
              f"hearing {idle} -> {faculty._hearing._proc.pid}")
        logging.getLogger("core.perception.senses").removeHandler(handler)
    finally:
        # ── cleanup: by nonce and exact memory id ───────────────────────────
        like = f"%{N}%"
        try:
            concepts = [r["concept_id"] for r in await d.execute_query(
                "SELECT concept_id FROM unified.concepts WHERE name ILIKE $1", (like,), fetch_all=True) or []]
            envelopes = [r["evidence_id"] for r in await d.execute_query(
                "SELECT evidence_id FROM unified.evidence_envelopes WHERE content ILIKE $1 "
                "OR source_id ILIKE $1 OR producer ILIKE $1", (like,), fetch_all=True) or []]
            if concepts or envelopes:
                await d.execute_query(
                    "DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
                    "OR target_concept_id = ANY($1::text[]) OR evidence_id = ANY($2::text[]) "
                    "OR target_surface ILIKE $3", (concepts, envelopes, like))
                for t in ("concept_domains", "concept_evidence"):
                    await d.execute_query(f"DELETE FROM unified.{t} WHERE concept_id = ANY($1::text[]) "
                                          f"OR evidence_id = ANY($2::text[])", (concepts, envelopes))
                await d.execute_query("DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1::text[])",
                                      (concepts,))
                await d.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])",
                                      (concepts,))
                await d.execute_query("DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                                      (envelopes,))
            updates = [r["update_id"] for r in await d.execute_query(
                "SELECT update_id FROM unified.knowledge_updates WHERE subject_id ILIKE $1",
                (like,), fetch_all=True) or []]
            if updates:
                await d.execute_query("DELETE FROM unified.knowledge_consumption WHERE update_id = ANY($1::text[])",
                                      (updates,))
                await d.execute_query("DELETE FROM unified.knowledge_updates WHERE update_id = ANY($1::text[])",
                                      (updates,))
            for table, col in (("unified.beliefs", "belief_text"), ("unified.beliefs", "claim"),
                               ("unified.perceptions", "source"), ("unified.experience_pool", "about"),
                               ("unified.experience_pool", "parts::text"),
                               ("unified.held_conditionals", "surface")):
                await d.execute_query(f"DELETE FROM {table} WHERE {col} ILIKE $1", (like,))
            tagged = [r["memory_id"] for r in await d.execute_query(
                "SELECT memory_id FROM memory_hot.memory_hot WHERE content ILIKE $1", (like,),
                fetch_all=True) or []]
            for mid in set(map(str, memory_ids)) | set(map(str, tagged)):
                await d.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1", (mid,))
                await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (mid,))
            for t in ("scoped_beliefs", "scoped_concept_relations"):
                await d.execute_query(f"DELETE FROM unified.{t} WHERE scope_actor = ANY($1::text[])",
                                      (actors,))
            # The deaths this run caused are recorded as failures, named by the
            # process that died, and removed by that name.
            for pid in killed:
                await d.execute_query(
                    "DELETE FROM unified.failure_events WHERE component = 'perception.senses' "
                    "AND description LIKE $1", (f"%process (pid {pid}) had died%",))
            left = await d.execute_query(
                "SELECT (SELECT count(*) FROM unified.concepts WHERE name ILIKE $1) + "
                "(SELECT count(*) FROM unified.beliefs WHERE belief_text ILIKE $1) + "
                "(SELECT count(*) FROM unified.perceptions WHERE source ILIKE $1) + "
                "(SELECT count(*) FROM memory_hot.memory_hot WHERE content ILIKE $1) AS n",
                (like,), fetch_one=True)
            EV.note(f"Cleanup by nonce {N} and exact memory id: {len(concepts)} concepts, "
                    f"{len(envelopes)} envelopes, {len(set(memory_ids) | set(tagged))} memories; "
                    f"{left['n']} left.")
        except Exception as error:
            EV.note(f"Cleanup failed: {error}")
        # ── E. SHUTDOWN ─────────────────────────────────────────────────────
        procs = [p for p in (faculty._sight._proc, faculty._hearing._proc) if p is not None]
        await shutdown(system)
        await asyncio.sleep(0.2)
        stopped = [p.returncode is not None for p in procs]
        print("\n== E. The senses stop with the substrate ==")
        check("the senses' processes stop with the substrate", procs and all(stopped),
              f"{sum(stopped)} of {len(procs)} stopped")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== SENSES-TOGETHER-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
