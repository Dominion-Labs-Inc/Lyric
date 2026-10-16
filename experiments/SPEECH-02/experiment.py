#!/usr/bin/env python3
"""SPEECH-02 — the lessons' own words, taught by hearing them said, and heard said by others.

SPEECH-01 taught eight digits from one speaker. This teaches the words the 30 English lessons are written in, each
from several speakers, and hears them said by speakers it was never taught by. No model anywhere: a lesson is a
hearing, told which word was said (`coord.learn_word`), and heard speech is matched against what those hearings
kept (`core/perception/speech.py`).

  A  TAUGHT    every example is heard through the one door and remembered as a hearing of its own, in the shared
               mind, saying which word it taught, its trace keeping exactly what was measured; no real word said is
               refused; the word taught is one the reader holds; and what teaching wrote anywhere else is listed.
  B  RESTART   a fresh faculty reads every taught word back from memory, every example, exactly.
  C  HEARD     the same words said by speakers never taught by, heard by the faculty's own sense (nothing kept):
               a FIRM reading (support >= 0.5) is right, and how many are named, named wrongly or left unnamed is
               measured.
  D  CLEAN     everything the run wrote is removed from the sandbox, and the main model's store is untouched.

Recordings (fetched once, never pushed):
  - the Multilingual Spoken Words Corpus (MLCommons, CC BY 4.0), one-second clips of single words cut from Common
    Voice, split by speaker: dev to teach from, test to hear (`fetch_mswc.py`);
  - LibriSpeech (CC BY 4.0) for the lesson words MSWC does not keep ("is", "a", "of", contractions), cut from read
    sentences by their aligned times: dev-clean to teach from, test-clean to hear (`cut_librispeech.py`).
Each is presented as a live buffer presents speech, with room quiet around it, as SPEECH-01 does.

Run (sandbox store):
    ./venv_lyric/bin/python3 experiments/SPEECH-02/experiment.py [--words N] [--examples E] [--heard H]
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
# Speech is off in the substrate unless said (`speech.WORDS_HEARD`); this experiment measures it, so it is on here.
os.environ.setdefault("LYRIC_SPEECH", "on")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
DOMAIN = "hearing"

EV = RunRecord(
    "SPEECH-02",
    claim=("The words the English lessons are written in can be taught to the substrate by hearing them said, "
           "each lesson kept as a hearing in the shared mind and read back exactly; and said by people it was "
           "never taught by, a word it names firmly is the word said."),
    hypothesis=("H1 every example of a real word said is taught, none refused, each a hearing of its own saying "
                "which word it taught. H2 a fresh faculty reads every example back exactly. H3 a firm reading of "
                "a word said by an untaught speaker is right; how many are named at all is measured."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _sense_01():
    spec = importlib.util.spec_from_file_location("sense_01", REPO / "experiments" / "SENSE-01" / "experiment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: What a hearing writes, and when each row says it was written: (table, column, whether the column keeps a time
#: zone). The store keeps some times in local time (`timestamp without time zone`). Children before the rows they
#: point at, so each delete is allowed.
WRITTEN = (("unified.concept_relations", "created_at", True), ("unified.concept_evidence", "created_at", True),
           ("unified.concept_aliases", "first_seen", True), ("unified.concept_domains", "created_at", True),
           ("unified.concept_identity_relations", "created_at", True), ("unified.beliefs", "created_at", False),
           ("unified.concepts", "created_at", False), ("unified.memory_media", "created_at", True),
           ("memory_hot.memory_hot", "created_at", False), ("unified.experience_pool", "created_at", True),
           ("unified.evidence_envelopes", "ingested_at", True), ("unified.domains", "created_at", False),
           ("unified.performance_logs", "timestamp", False))


async def dev_rows(db) -> dict:
    """Rows in each table of the sandbox's store, to say what teaching wrote and what cleanup left."""
    rows = {}
    for t in await db.execute_query(
            "SELECT table_schema s, table_name n FROM information_schema.tables "
            "WHERE table_schema IN ('unified','memory_hot','memory_cold') AND table_type='BASE TABLE'",
            fetch_all=True) or []:
        found = await db.execute_query(f'SELECT count(*) AS n FROM "{t["s"]}"."{t["n"]}"', fetch_one=True)
        rows[f'{t["s"]}.{t["n"]}'] = int(found["n"])
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=100, help="the lessons' most-used words to teach")
    parser.add_argument("--examples", type=int, default=3, help="speakers each word is taught from")
    parser.add_argument("--heard", type=int, default=2, help="untaught speakers each word is heard from")
    args = parser.parse_args()

    import numpy as np
    sys.path.insert(0, str(HERE))
    from clips import clips, present
    from fetch_mswc import lesson_words
    used = lesson_words()
    available = clips(set(used), args.examples, args.heard)
    ranked = [w for w in sorted(used, key=lambda w: (-used[w], w))
              if w in available and len(available[w]["teach"]) == args.examples and available[w]["heard"]]
    words = ranked[:args.words]
    missing = sorted((w for w in used if w not in available), key=lambda w: -used[w])
    EV.metric("lesson words", len(used))
    EV.metric("lesson words with no clip to teach or hear", missing)
    EV.metric("words taught", len(words))
    print(f"== {len(words)} of the lessons' {len(used)} words, {args.examples} speakers each to teach, "
          f"{args.heard} untaught to hear; with no clip: {missing[:20]} ==", flush=True)

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
    check("the run is in the sandbox", os.environ["POSTGRES_DATABASE"] == "lyric_dev",
          os.environ["POSTGRES_DATABASE"])
    sense = _sense_01()
    main_before = await sense.main_store_rows()
    before = await dev_rows(db)
    from core.memory import get_memory_agent
    from core.memory.media_store import get_media_store
    from core.perception import hearing as H
    from core.perception import speech as SP
    from core.perception.perception_faculty import PerceptionFaculty

    rng = np.random.default_rng(20261003)
    tag = uuid.uuid4().hex[:6]
    began = await db.execute_query("SELECT now() AS tz, localtimestamp AS local", fetch_one=True)
    faculty = coord.vision
    memory_ids, taught, refused = [], {}, []
    started_at = datetime.now(timezone.utc)

    try:
        # ── A. TAUGHT ───────────────────────────────────────────────────────────────────────────────────────────
        print("\n== A. The lessons' words, taught by hearing them said ==", flush=True)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await faculty._read_library()
        held_before = dict(faculty.taught_words)
        EV.note(f"Spoken words held before this run: {len(held_before)}.")
        started = time.time()
        for word in words:
            for k, clip in enumerate(available[word]["teach"]):
                stim = present(clip["path"], WORK / "teach" / word / f"{k}.wav", rng)
                try:
                    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                        mid = await coord.learn_word(word, str(stim), actor_identity=None,
                                                     source=f"s02{tag}{word}{k}", domain=DOMAIN)
                    memory_ids.append(str(mid))
                    taught.setdefault(word, []).append((str(mid), stim))
                except ValueError as error:
                    refused.append((word, available[word]["source"], clip["speaker"][:8], str(error)[:160]))
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await get_uncertainty_system().drain_writes()
        lessons = sum(len(v) for v in taught.values())
        EV.metric("seconds to teach", round(time.time() - started, 1))
        EV.metric("seconds per lesson", round((time.time() - started) / max(lessons + len(refused), 1), 2))
        EV.metric("refused", refused)
        check("no real word said is refused", not refused,
              f"{len(refused)} of {lessons + len(refused)}: {refused[:4]}")
        check("every example taught is a hearing remembered on its own",
              len(set(memory_ids)) == lessons, f"{len(set(memory_ids))} memories for {lessons} lessons")

        as_json = lambda v: json.loads(v) if isinstance(v, str) else (v or {})
        wrong_memory, wrong_trace = [], []
        for word, kept in taught.items():
            for mid, stim in kept:
                row = await db.execute_query(
                    "SELECT memory_type, tags, metadata FROM memory_hot.memory_hot WHERE memory_id = $1",
                    (mid,), fetch_one=True)
                meta = as_json(row["metadata"]) if row else {}
                origin = meta.get("origin") or {}
                tags = set(as_json(row["tags"])) if row else set()
                if not (row and {"sound", "hearing", "spoken_word"} <= tags and meta.get("word") == word
                        and origin.get("through") == "hear" and origin.get("person") is None):
                    wrong_memory.append((word, mid, sorted(tags), meta.get("word"), origin))
                media = await get_media_store().media_for_memory(mid)
                measured = SP.word_features(H.decode(str(stim)))
                if not (len(media) == 1 and media[0]["mime"] == "application/x-npz"
                        and (media[0]["perceived"] or {}).get("lesson") == {"word": word}
                        and np.array_equal(SP.unpack(media[0]["bytes"]), measured)):
                    wrong_trace.append((word, mid, len(media)))
        check("each lesson is a hearing in the shared mind, tagged a spoken word, saying which word it taught",
              not wrong_memory, f"{len(wrong_memory)} wrong: {wrong_memory[:3]}")
        check("its trace keeps exactly what was measured of the example, never the recording",
              not wrong_trace, f"{len(wrong_trace)} wrong: {wrong_trace[:3]}")

        view = await (await get_memory_agent()).language_view()
        unread = [w for w in taught if not view.lexicals_with_words((w,), loose=True)
                  and not view.is_structure(w) and w not in view._frame_words]
        check("every word taught by hearing is a word the reader holds, written the same", not unread,
              f"{len(unread)} not: {unread[:10]}")

        after_teaching = await dev_rows(db)
        wrote = {t: after_teaching.get(t, 0) - before.get(t, 0) for t in after_teaching
                 if after_teaching.get(t, 0) != before.get(t, 0)}
        EV.metric("rows teaching wrote, by table", wrote)
        print(f"    rows teaching wrote: {wrote}", flush=True)
        relations = await db.execute_query(
            "SELECT cr.relation AS rel, COALESCE(c1.name, '?') AS s, COALESCE(c2.name, cr.target_surface) AS o "
            "FROM unified.concept_relations cr "
            "LEFT JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE cr.created_at >= $1 ORDER BY cr.created_at LIMIT 40", (started_at,), fetch_all=True) or []
        EV.metric("relations teaching wrote, first 40", [(r["s"], r["rel"], r["o"]) for r in relations])

        # ── B. RESTART ──────────────────────────────────────────────────────────────────────────────────────────
        print("\n== B. A fresh faculty reads every taught word back ==", flush=True)
        fresh = PerceptionFaculty()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await fresh.load_instances()
        counts = {w: n for w, n in fresh.taught_words.items() if w in taught}
        expected = {w: len(v) + held_before.get(w, 0) for w, v in taught.items()}
        check("every taught word, with every example", counts == expected,
              f"{sum(counts.values())} examples of {len(counts)} words, against {sum(expected.values())}")
        exact = sum(any(np.array_equal(b, SP.word_features(H.decode(str(stim)))) for b in fresh._words.get(w, []))
                    for w, kept in taught.items() for _, stim in kept)
        check("exactly as they were taught", exact == lessons, f"{exact} of {lessons}")

        # ── C. HEARD ────────────────────────────────────────────────────────────────────────────────────────────
        print("\n== C. The same words said by speakers never taught by ==", flush=True)
        tally, confused, firm_wrong, timings = Counter(), Counter(), [], []
        for word in taught:
            for k, clip in enumerate(available[word]["heard"]):
                stim = present(clip["path"], WORK / "heard" / word / f"{k}.wav", rng)
                begun = time.time()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    _modality, content = await faculty.sense(str(stim))
                timings.append(time.time() - begun)
                said = [s for s in (content or {}).get("said") or []]
                ways = (content or {}).get("heard_texts") or []
                named = [s["word"] for s in said]
                if word in named:
                    firm = any(s["word"] == word and s["support"] >= 0.5 for s in said)
                    tally["right, firmly" if firm else "right, weakly"] += 1
                elif any(word in way.split() for way in ways):
                    tally["among words that sound alike"] += 1
                elif named:
                    tally["named wrongly"] += 1
                    confused[(word, named[0])] += 1
                    if any(s["support"] >= 0.5 for s in said):
                        firm_wrong.append((word, [(s["word"], s["support"]) for s in said]))
                else:
                    tally["not named"] += 1
                tally["heard"] += 1
        n = tally["heard"]
        right = tally["right, firmly"] + tally["right, weakly"]
        EV.metric("heard", dict(tally))
        EV.metric("named right", f"{right}/{n}")
        EV.metric("named wrongly, most often", [f"{a} as {b} ({c})" for (a, b), c in confused.most_common(15)])
        EV.metric("seconds to hear a word", round(float(np.mean(timings)), 2) if timings else None)
        print(f"    {dict(tally)}; most confused: {confused.most_common(8)}; "
              f"{np.mean(timings) if timings else 0:.2f} s a word", flush=True)
        check("a word named firmly is the word said", not firm_wrong,
              f"{len(firm_wrong)} firm and wrong: {firm_wrong[:4]}")
        check("most words said by an untaught speaker are named", right * 2 > n, f"{right} of {n}")
    finally:
        # ── D. CLEAN ────────────────────────────────────────────────────────────────────────────────────────────
        # EVERYTHING THE RUN WROTE, BY WHEN IT WAS WRITTEN. A hearing writes far more than its memory: what it
        # measured (each pitch and level a quantity of its own), their aliases, the evidence for them, and identity
        # links. Most carry no mark of the run, so removing what did left 564 concepts behind in the first run. No
        # other writer runs in the sandbox during a run; the counts of every table are compared after.
        for table, column, zoned in WRITTEN:
            try:
                await db.execute_query(f"DELETE FROM {table} WHERE {column} >= $1",
                                       (began["tz"] if zoned else began["local"],), commit=True)
            except Exception as error:
                EV.note(f"Cleanup of {table} failed: {error}")
                print(f"  (cleanup of {table}: {error})", flush=True)
    after = await dev_rows(db)
    left = {t: after.get(t, 0) - before.get(t, 0) for t in after if after.get(t, 0) != before.get(t, 0)}
    EV.metric("rows left after cleanup, by table", left)
    check("everything the run wrote to the sandbox is removed", not left, str(left))
    main_after = await sense.main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          sense.main_store_change(main_before, main_after))

    passed = sum(results)
    print(f"\n==== SPEECH-02: {passed}/{len(results)} checks passed ====", flush=True)
    await EV.verify_database()
    record = EV.write()
    print(f"  run record: {record}", flush=True)
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
