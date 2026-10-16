#!/usr/bin/env python3
"""SPEECH-05 — the substrate hears words said by anyone, its ear a trained sense of which sounds were said.

Offline (`offline_ctc.py`, `offline_sentences.py`), a phone recogniser that reports only which of 39 English sounds
were said, with Lyric's pronunciations and its one-pass word search, put 78.2% of the words of untaught speakers'
whole sentences right, and every word it named at a log margin of 10 was right. This builds it into the substrate
(`phone_recogniser`, `speech.find_words_by_marks`, the hearing process) and measures it there, on the sandbox:

  A  SAID AS TAUGHT    how the lesson words and the words of the sentences heard are said, from the CMU Pronouncing
                       Dictionary through the one teaching pass (`PronunciationSource`): kept as memories, as told.
  B  RESTART           a fresh faculty reads every pronunciation back.
  C  WORDS ALONE       MSWC's 100 most used lesson words, each said alone by three speakers never taught by, through
                       their own microphones, heard by the faculty's own `sense` (nothing kept).
  D  SENTENCES         LibriSpeech test-clean sentences, one untaught speaker each, no word boundary given, heard by
                       `sense`: words right in the likeliest way of hearing each (Levenshtein), a word named firmly
                       (support at least 0.5) the word said there or one said the same, and the listener choosing
                       among the ways as the live loop does (`derived_reader.heard_which`).
  E  CLEAN             everything the run wrote is removed from the sandbox; the main model's store is untouched.

Stated before the run: no word named firmly is wrong; at least 70% of the words of whole sentences are right in the
likeliest way (model-free hearing: 14 of 789 in the substrate, SPEECH-04); at least 40% of words said alone are
heard right in the likeliest way (model-free: 0 of 198).

Recordings (never pushed): LibriSpeech test-clean with the Montreal Forced Aligner's times
(`gilkeyio/librispeech-alignments`, CC BY 4.0); MSWC clips as SPEECH-02 fetched them.

Run (sandbox store; speech and the recogniser on):
    ./venv_lyric/bin/python3 experiments/SPEECH-05/experiment.py [--sentences 146] [--words 100]
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
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
# Speech is off in the substrate unless said (`speech.WORDS_HEARD`); this experiment measures it, so it is on here,
# with the ear's recogniser (`phone_recogniser.wanted`).
os.environ.setdefault("LYRIC_SPEECH", "on")
os.environ.setdefault("LYRIC_EAR", "recogniser")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
SPEECH_02 = REPO / "experiments" / "SPEECH-02"
SPEECH_03 = REPO / "experiments" / "SPEECH-03"

EV = RunRecord(
    "SPEECH-05",
    claim=("With an ear that senses only which sounds were said, and its own pronunciations, word search and "
           "listener, the substrate hears words said by people it was never taught by well enough to follow a "
           "sentence; a word it names firmly is the word said."),
    hypothesis=("A pronunciation is not kept or read back as told; or a word named firmly is not the word said; or "
                "fewer than 70% of the words of whole sentences, or 40% of words said alone, are heard right in "
                "the likeliest way."))
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


def sentences(every: int, most: int):
    """`(id, audio at the hearing's rate, words with their times)` of every `every`-th LibriSpeech test-clean
    sentence, as `offline_sentences.py` takes them."""
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    table = pq.read_table(ALIGNED / "test_clean.parquet", columns=["id", "words", "audio"])
    out = []
    for k, row in enumerate(table.to_pylist()):
        if k % every:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        out.append((row["id"], np.asarray(y, dtype=np.float32), [w for w in row["words"] if w["word"] != "<unk>"]))
        if len(out) == most:
            break
    return out


def written(path: Path, y) -> Path:
    import soundfile as sf
    from core.perception import hearing as H
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), y, H.SR)
    return path


def likeliest(content) -> str:
    """The likeliest way what was heard can be taken: the first the ear hands on, or what it named."""
    ways = (content or {}).get("heard_texts") or []
    return ways[0] if ways else (content or {}).get("heard_text") or ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=int, default=146, help="test-clean sentences heard whole")
    parser.add_argument("--words", type=int, default=100, help="MSWC lesson words heard alone, three speakers each")
    args = parser.parse_args()
    import numpy as np
    sys.path.insert(0, str(SPEECH_02))
    sys.path.insert(0, str(SPEECH_03))
    from clips import clips, present
    from fetch_mswc import lesson_words
    from offline_connected import aligned

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
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
    from core.perception import phone_recogniser as PR
    from core.perception import speech as SP
    from core.perception.perception_faculty import PerceptionFaculty
    from core.semantics.derived_reader import heard_which
    began = await db.execute_query("SELECT now() AS tz, localtimestamp AS local", fetch_one=True)
    faculty = coord.vision
    EV.metric("the ear", PR.MODEL if PR.wanted() else "no recogniser")

    try:
        # ── A. SAID AS TAUGHT ───────────────────────────────────────────────────────────────────────────────────
        print("\n== A. How the lesson words and the sentences' words are said, taught ==", flush=True)
        heard_sentences = sentences(18, args.sentences)
        vocabulary = set(lesson_words()) | {w["word"] for _, _, words in heard_sentences for w in words}
        report = await TeachingPass(PronunciationSource(vocabulary), domain="english",
                                    sample=False).run(get_learning_authority())
        stated = await (await get_memory_agent()).stated_pronunciations()
        EV.metric("pronunciations taught", report.pronunciations)
        expected = list(PronunciationSource(vocabulary).pronunciations())
        check("every pronunciation the source states is kept, as told",
              {(w, p) for w, p, _ in stated} >= {(w, p) for w, p, _ in expected},
              f"{report.pronunciations}; {len(stated)} held for {len(expected)} stated")

        # ── B. RESTART ──────────────────────────────────────────────────────────────────────────────────────────
        print("\n== B. A fresh faculty reads the pronunciations back ==", flush=True)
        fresh = PerceptionFaculty()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await fresh.load_instances()
        check("every pronunciation", sum(len(v) for v in fresh._said_as.values()) == len(stated),
              f"{sum(len(v) for v in fresh._said_as.values())} ways of {len(fresh._said_as)} words")
        ways_of = {w: {tuple(SP.plain_phone(x) for x in way.split()) for way in ways}
                   for w, ways in fresh._said_as.items()}
        alike = lambda a, b: a == b or bool(ways_of.get(a, set()) & ways_of.get(b, set()))

        # ── C. WORDS ALONE ──────────────────────────────────────────────────────────────────────────────────────
        print("\n== C. Words said alone by speakers never taught by ==", flush=True)
        used = lesson_words()
        available = clips(set(used), 1, 3)
        words = [w for w in sorted(used, key=lambda w: (-used[w], w)) if w in available
                 and len(available[w]["heard"]) == 3 and w in fresh._said_as][:args.words]
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
                firm_wrong += [(w, s["word"], s["support"]) for s in said
                               if s["support"] >= 0.5 and not alike(s["word"], w)]
                tally["heard right in the likeliest way"] += any(alike(x, w) for x in likeliest(content).split())
                tally["named firmly and right"] += any(alike(s["word"], w) and s["support"] >= 0.5 for s in said)
                tally["heard"] += 1
        alone_right = tally["heard right in the likeliest way"]
        EV.metric("MSWC words alone", dict(tally))
        EV.metric("seconds to hear a word (the first loads the ear)", round(float(np.mean(timings)), 2))
        print(f"    words alone: {dict(tally)}; {np.mean(timings):.2f} s each", flush=True)

        # ── D. SENTENCES ────────────────────────────────────────────────────────────────────────────────────────
        print("\n== D. Whole sentences, each said by one speaker never taught by ==", flush=True)
        count = Counter()
        chose = Counter()
        examples, timings = [], []
        for uid, y, said_words in heard_sentences:
            path = written(WORK / "sentences" / f"{uid}.wav", y)
            begun_at = time.time()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                _m, content = await faculty.sense(str(path))
            timings.append(time.time() - begun_at)
            for s in (content or {}).get("said") or []:
                count["named"] += 1
                if s["support"] >= 0.5:
                    count["named firmly"] += 1
                    if not any(alike(s["word"], w["word"]) for w in said_words
                               if w["start"] - 0.3 <= s["starts_at"] <= w["end"] + 0.3):
                        firm_wrong.append((uid, s["word"], s["support"]))
            truth = [w["word"] for w in said_words]
            heard = likeliest(content).split()
            r, s_, d, i = aligned(truth, heard)
            count["right"] += r
            count["for another"] += s_
            count["left out"] += d
            count["put in"] += i
            ways = [way for way in (content or {}).get("heard_texts") or [] if "..." not in way.split()]
            if ways:
                which = await heard_which(ways)
                chose["the listener chose" if which else "the listener could not choose"] += 1
                if which:
                    chose["words right in what it chose"] += aligned(truth, which.split())[0]
                    chose["words right in the likeliest, where it chose"] += r
            else:
                chose["named every word clearly" if (content or {}).get("said") else "nothing heard"] += 1
            if len(examples) < 4:
                examples.append((" ".join(truth[:14]), " ".join(heard[:14])))
        n = count["right"] + count["for another"] + count["left out"]
        EV.metric("sentences: words in the likeliest way", dict(count))
        EV.metric("sentences: words right in the likeliest way", f"{count['right']}/{n}",
                  note=f"{100 * count['right'] / max(n, 1):.1f}%")
        EV.metric("sentences: the listener", dict(chose))
        EV.metric("seconds to hear a sentence", round(float(np.mean(timings)), 2))
        EV.metric("sentences, said and heard", examples)
        print(f"    {dict(count)}; right {100 * count['right'] / max(n, 1):.1f}% of {n}; {dict(chose)}; "
              f"{np.mean(timings):.2f} s each", flush=True)
        for truth, heard in examples[:3]:
            print(f"      said:  {truth}\n      heard: {heard}", flush=True)

        check("a word named firmly is the word said, or one said the same", not firm_wrong,
              f"{len(firm_wrong)} firm and wrong: {firm_wrong[:4]}")
        check("at least 70% of the words of whole sentences are right in the likeliest way",
              count["right"] * 10 >= n * 7, f"{count['right']} of {n}")
        check("at least 40% of words said alone are heard right in the likeliest way",
              alone_right * 10 >= tally["heard"] * 4, f"{alone_right} of {tally['heard']}")
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
    print(f"\n==== SPEECH-05: {passed}/{len(results)} checks passed ====", flush=True)
    await EV.verify_database()
    print(f"  run record: {EV.write()}", flush=True)
    return 0 if passed == len(results) else 1


#: What a hearing and a teaching pass write, and when each row says it was written (as SPEECH-04 cleans).
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
