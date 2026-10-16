#!/usr/bin/env python3
"""SPEECH-04 — the substrate hears a word by the sounds it is made of, said by anyone.

SPEECH-03 measured offline that taught the sounds words are made of, and nothing of the words, a word said in a
sentence by a speaker never heard fits best six times in ten among 100 lesson words. This builds it into the
substrate and measures it there, on the sandbox:

  A  SOUNDS TAUGHT     LibriSpeech dev-clean sentences, each HEARD through `coord.learn_phones`, told which phone is
                       said when: each a hearing in the shared mind tagged as spoken sounds, its trace keeping the
                       frames `speech.phones_example` measures, exactly; none refused.
  B  SAID AS TAUGHT    how the lesson words are said, from the CMU Pronouncing Dictionary through the one teaching
                       pass (`PronunciationSource`): kept as memories, read back as told.
  C  RESTART           a fresh faculty reads every lesson of sounds back, every frame, exactly, and every
                       pronunciation.
  D  HEARD             MSWC's lesson words said alone by speakers never taught by, and LibriSpeech test-clean
                       sentences, heard by the faculty's own `sense` (nothing kept): a word named firmly (support at
                       least 0.5) is the word said, or one said the same; how many are named and how many words of
                       each sentence are heard right is measured.
  E  CLEAN             everything the run wrote is removed from the sandbox; the main model's store is untouched.

Recordings (never pushed): LibriSpeech dev-clean and test-clean with the Montreal Forced Aligner's times
(`gilkeyio/librispeech-alignments`, CC BY 4.0); MSWC clips as SPEECH-02 fetched them.

Run (sandbox store):
    ./venv_lyric/bin/python3 experiments/SPEECH-04/experiment.py [--every 2] [--sentences 40]
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
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
SPEECH_02 = REPO / "experiments" / "SPEECH-02"

EV = RunRecord(
    "SPEECH-04",
    claim=("Taught the sounds words are made of by hearing sentences told which sound is said when, and how the "
           "lesson words are said, the substrate hears a word said by a speaker it never heard by its sounds; a "
           "word it names firmly is the word said."),
    hypothesis=("A lesson of sounds is refused, misplaced or not read back exactly; or a word named firmly is not "
                "the word said; or no more words are named than whole words were (SPEECH-02: 4 of 200)."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def utterances(split: str, every: int):
    """`(id, speaker, audio at the hearing's rate, told phones, words with their frames)` of a LibriSpeech split."""
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    table = pq.read_table(ALIGNED / f"{split}.parquet", columns=["id", "words", "phonemes", "audio"])
    for k, row in enumerate(table.to_pylist()):
        if k % every:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        told = "|".join(f"{p['phoneme']} {p['start']:.3f} {p['end']:.3f}"
                        for p in row["phonemes"] if p["phoneme"] != "spn")
        yield row["id"], row["id"].split("-")[0], np.asarray(y, dtype=np.float32), told, row["words"]


def written(path: Path, y) -> Path:
    import soundfile as sf
    from core.perception import hearing as H
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), y, H.SR)
    return path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--every", type=int, default=2, help="teach every n-th dev-clean sentence")
    parser.add_argument("--sentences", type=int, default=40, help="test-clean sentences heard whole")
    args = parser.parse_args()
    import numpy as np
    sys.path.insert(0, str(SPEECH_02))
    from clips import clips, present
    from fetch_mswc import lesson_words

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
    sense = _module(REPO / "experiments" / "SENSE-01" / "experiment.py", "sense_01")
    main_before = await sense.main_store_rows()
    before = await dev_rows(db)
    from core.learning import get_learning_authority
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import PronunciationSource
    from core.memory import get_memory_agent
    from core.memory.media_store import get_media_store
    from core.perception import speech as SP
    from core.perception import hearing as H
    from core.perception.perception_faculty import PerceptionFaculty
    began = await db.execute_query("SELECT now() AS tz, localtimestamp AS local", fetch_one=True)
    faculty = coord.vision
    lessons, refused = [], []

    try:
        # ── A. SOUNDS TAUGHT ────────────────────────────────────────────────────────────────────────────────────
        print("\n== A. The sounds words are made of, taught by hearing sentences said ==", flush=True)
        started = time.time()
        for uid, speaker, y, told, _ in utterances("dev_clean", args.every):
            path = written(WORK / "teach" / f"{uid}.wav", y)
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    mid = await coord.learn_phones(told, str(path), actor_identity=None, source=f"s04{uid}",
                                                   domain="hearing")
                lessons.append((str(mid), path, told))
            except (ValueError, RuntimeError) as error:
                refused.append((uid, str(error)[:160]))
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await get_uncertainty_system().drain_writes()
        EV.metric("lessons of sounds", len(lessons))
        EV.metric("seconds per lesson", round((time.time() - started) / max(len(lessons) + len(refused), 1), 2))
        EV.metric("refused", refused[:20])
        check("no sentence said is refused as a lesson of sounds", not refused,
              f"{len(refused)} of {len(lessons) + len(refused)}: {refused[:3]}")
        as_json = lambda v: json.loads(v) if isinstance(v, str) else (v or {})
        wrong_memory, wrong_trace = [], []
        for mid, path, told in lessons:
            row = await db.execute_query("SELECT tags, metadata FROM memory_hot.memory_hot WHERE memory_id = $1",
                                         (mid,), fetch_one=True)
            meta = as_json(row["metadata"]) if row else {}
            origin = meta.get("origin") or {}
            tags = set(as_json(row["tags"])) if row else set()
            if not (row and {"sound", "hearing", "spoken_sounds"} <= tags and origin.get("through") == "hear"
                    and origin.get("person") is None):
                wrong_memory.append((mid, sorted(tags), origin))
            media = await get_media_store().media_for_memory(mid)
            kept = SP.unpack_phones(media[0]["bytes"]) if len(media) == 1 else None
            frames, labels = SP.phones_example(H.decode(str(path)), told)
            if kept is None or kept[1] != labels or not np.array_equal(kept[0], frames):
                wrong_trace.append((mid, len(media)))
        check("each lesson of sounds is a hearing in the shared mind, tagged as spoken sounds",
              not wrong_memory, f"{len(wrong_memory)} wrong: {wrong_memory[:2]}")
        check("its trace keeps exactly the frames measured of each phone said, with their phones", not wrong_trace,
              f"{len(wrong_trace)} wrong of {len(lessons)}: {wrong_trace[:2]}")
        print(f"    {faculty.taught_sounds} frames of sounds held", flush=True)

        # ── B. SAID AS TAUGHT ───────────────────────────────────────────────────────────────────────────────────
        print("\n== B. How the lesson words are said, taught ==", flush=True)
        heard_sentences = list(utterances("test_clean", 9))[:args.sentences]
        vocabulary = set(lesson_words()) | {w["word"] for *_, words in heard_sentences for w in words}
        report = await TeachingPass(PronunciationSource(vocabulary), domain="english",
                                    sample=False).run(get_learning_authority())
        stated = await (await get_memory_agent()).stated_pronunciations()
        EV.metric("pronunciations taught", report.pronunciations)
        expected = list(PronunciationSource(vocabulary).pronunciations())
        check("every pronunciation the source states is kept, as told",
              {(w, p) for w, p, _ in stated} >= {(w, p) for w, p, _ in expected},
              f"{report.pronunciations}; {len(stated)} held for {len(expected)} stated")

        # ── C. RESTART ──────────────────────────────────────────────────────────────────────────────────────────
        print("\n== C. A fresh faculty reads the sounds and pronunciations back ==", flush=True)
        fresh = PerceptionFaculty()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await fresh.load_instances()
        check("every frame of every lesson of sounds", fresh.taught_sounds == faculty.taught_sounds,
              f"{fresh.taught_sounds} against {faculty.taught_sounds}")
        check("every pronunciation", sum(len(v) for v in fresh._said_as.values()) == len(stated),
              f"{sum(len(v) for v in fresh._said_as.values())} ways of {len(fresh._said_as)} words")

        # ── D. HEARD ────────────────────────────────────────────────────────────────────────────────────────────
        print("\n== D. Said by speakers never taught by ==", flush=True)
        alike = lambda a, b: a == b or bool({tuple(SP.plain_phone(x) for x in w.split()) for w in fresh._said_as.get(a, [])}
                                            & {tuple(SP.plain_phone(x) for x in w.split()) for w in fresh._said_as.get(b, [])})
        used = lesson_words()
        available = clips(set(used), 1, 2)
        words = [w for w in sorted(used, key=lambda w: (-used[w], w)) if w in available
                 and available[w]["heard"] and w in fresh._said_as][:100]
        rng = np.random.default_rng(20261003)
        tally, firm_wrong, timings = Counter(), [], []
        for w in words:
            for k, c in enumerate(available[w]["heard"]):
                path = present(c["path"], WORK / "heard" / w / f"{k}.wav", rng)
                begun_at = time.time()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    _m, content = await faculty.sense(str(path))
                timings.append(time.time() - begun_at)
                said = (content or {}).get("said") or []
                ways = (content or {}).get("heard_texts") or []
                if any(alike(s["word"], w) for s in said):
                    tally["right, firmly" if any(alike(s["word"], w) and s["support"] >= 0.5 for s in said)
                          else "right, weakly"] += 1
                elif any(w in way.split() for way in ways):
                    tally["among words that sound alike"] += 1
                elif said:
                    tally["named wrongly"] += 1
                    firm_wrong += [(w, s["word"], s["support"]) for s in said if s["support"] >= 0.5]
                else:
                    tally["not named"] += 1
        n = sum(tally.values())
        right = tally["right, firmly"] + tally["right, weakly"]
        EV.metric("MSWC words alone", dict(tally))
        EV.metric("seconds to hear a word", round(float(np.mean(timings)), 2) if timings else None)
        print(f"    MSWC words alone: {dict(tally)}; {np.mean(timings):.2f} s each", flush=True)
        right_words = said_words = 0
        examples = []
        for uid, _, y, _, words_said in heard_sentences:
            path = written(WORK / "sentences" / f"{uid}.wav", y)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                _m, content = await faculty.sense(str(path))
            for s in (content or {}).get("said") or []:
                if s["support"] >= 0.5 and not any(alike(s["word"], w["word"]) for w in words_said
                                                    if w["start"] - 0.3 <= s["starts_at"] <= w["end"] + 0.3):
                    firm_wrong.append((uid, s["word"], s["support"]))
            truth = [w["word"] for w in words_said if w["word"] != "<unk>"]
            heard = ((content or {}).get("heard_text") or "").split()
            right_words += sum(1 for w in set(heard) if w in truth)
            said_words += len(truth)
            if len(examples) < 3:
                examples.append((" ".join(truth[:12]), " ".join(heard[:12])))
        EV.metric("sentences: words heard that were said", f"{right_words}/{said_words}")
        EV.metric("sentences, said and heard", examples)
        print(f"    sentences: {right_words} of {said_words} words said were heard; e.g. {examples[:2]}", flush=True)
        check("a word named firmly is the word said, or one said the same", not firm_wrong,
              f"{len(firm_wrong)} firm and wrong: {firm_wrong[:4]}")
        check("more words said alone by untaught speakers are named right than whole words were (4 of 200)",
              right * 50 > n, f"{right} of {n}")
    finally:
        # ── E. CLEAN ────────────────────────────────────────────────────────────────────────────────────────────
        for table, column, zoned in WRITTEN:
            try:
                await db.execute_query(f"DELETE FROM {table} WHERE {column} >= $1",
                                       (began["tz"] if zoned else began["local"],), commit=True)
            except Exception as error:
                EV.note(f"Cleanup of {table} failed: {error}")
    after = await dev_rows(db)
    left = {t: after.get(t, 0) - before.get(t, 0) for t in after if after.get(t, 0) != before.get(t, 0)}
    EV.metric("rows left after cleanup, by table", left)
    check("everything the run wrote to the sandbox is removed", not left, str(left))
    main_after = await sense.main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          sense.main_store_change(main_before, main_after))
    passed = sum(results)
    print(f"\n==== SPEECH-04: {passed}/{len(results)} checks passed ====", flush=True)
    await EV.verify_database()
    print(f"  run record: {EV.write()}", flush=True)
    return 0 if passed == len(results) else 1


#: What a hearing and a teaching pass write, and when each row says it was written (as SPEECH-02 cleans).
WRITTEN = (("unified.concept_relations", "created_at", True), ("unified.concept_evidence", "created_at", True),
           ("unified.concept_aliases", "first_seen", True), ("unified.concept_domains", "created_at", True),
           ("unified.concept_identity_relations", "created_at", True), ("unified.beliefs", "created_at", False),
           ("unified.concepts", "created_at", False), ("unified.memory_media", "created_at", True),
           ("memory_hot.memory_hot", "created_at", False), ("unified.experience_pool", "created_at", True),
           ("unified.evidence_envelopes", "ingested_at", True), ("unified.domains", "created_at", False),
           ("unified.knowledge_updates", "occurred_at", True), ("unified.performance_logs", "timestamp", False))


async def dev_rows(db) -> dict:
    """Rows in each table of the sandbox's store, to say what cleanup left."""
    rows = {}
    for t in await db.execute_query(
            "SELECT table_schema s, table_name n FROM information_schema.tables "
            "WHERE table_schema IN ('unified','memory_hot','memory_cold') AND table_type='BASE TABLE'",
            fetch_all=True) or []:
        found = await db.execute_query(f'SELECT count(*) AS n FROM "{t["s"]}"."{t["n"]}"', fetch_one=True)
        rows[f'{t["s"]}.{t["n"]}'] = int(found["n"])
    return rows


sys.exit(asyncio.run(main()))
