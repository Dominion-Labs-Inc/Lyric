"""Replay a teaching pass's data-dependent work over ALL of a source's records, offline, before the pass is run.

A teaching pass runs for many hours, and a record nothing had met before could end it at its last step (2026-10-08:
"a meaning states the same fact twice", at 134,000 of 134,409, twelve hours in). This does, for every record, what the
pass does with the words and the facts, against the language the store holds now, and writes nothing:

  * saying each record with a meaning (`TeachingPass._said`) and splitting its facts (`_bucket_meaning`);
  * shaping each fact (`shape_proposition`) and typing its terms (`classify_literal`);
  * reading each memory a fact would be kept as, as storing it reads it (`MemoryAgent._readable_claim`), and the
    word classes it implies (`note_taught_proposition`);
  * what each word is said of and what was heard after each word, written as their memories are and read the same
    way (`remember_said`, `remember_heard`), and the source's own counts of use (`usage`, `said_of`).

Every failure is kept, with the record it came from, and the replay goes on: what it reports is every error the pass
would meet in this work, not the first. Workers in parallel, each with the language read once.

  POSTGRES_DATABASE=lyric_dev PYTHONPATH="$PWD" ./venv_lyric/bin/python3 scripts/teaching_preflight.py \
      --source wordnet --domain english [--workers 6] [--limit N]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

_STATE: Dict[str, Any] = {}


def _failure(stage: str, item: Any, error: BaseException) -> Dict[str, Any]:
    frames = traceback.extract_tb(error.__traceback__)[-3:]
    return {"stage": stage, "item": str(item)[:300], "error": f"{type(error).__name__}: {error}"[:400],
            "where": [f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in frames]}


def _start_worker() -> None:
    """Each worker reads the language the store holds, once."""
    import logging
    logging.disable(logging.WARNING)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def ready():
        # THE PROCESS'S OWN MEMORY AGENT, as the pass's: the sayer and the reader read the live view
        # (`derived_reader.live_view`), which is that agent's. A second agent warmed its own view and the live one
        # stayed empty, so nothing was said.
        from core.agents.memory_agent import get_memory_agent
        from core.semantics.derived_reader import live_view
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.language_view()
        view = live_view()
        # A REPLAY WITH NO LANGUAGE PASSES EVERYTHING: nothing is said, nothing reads, nothing can fail. It is refused
        # here rather than reported as clean (a first run of this did exactly that, every meaning "not said").
        words = len(getattr(agent, "_word_class_index", {}) or {})
        if not agent._word_classes_warm or len(view) == 0 or words == 0:
            raise RuntimeError(f"the worker read no language: {len(view)} construction(s), {words} word(s)")
        return agent
    _STATE["loop"] = loop
    _STATE["agent"] = loop.run_until_complete(ready())


def _read(agent, text: str, stage: str, failures: List[Dict[str, Any]]) -> None:
    try:
        _STATE["loop"].run_until_complete(agent._readable_claim(text, {"conclusion": text}))
    except Exception as error:      # every failure is kept, and the replay goes on
        failures.append(_failure(stage, text, error))


def _replay_records(records) -> Dict[str, Any]:
    """Say, split, shape and read every record in this chunk, as the pass does."""
    from core.learning.teaching import TeachingPass
    from core.semantics import derived_reader as dr
    from core.semantics.cognitive_ingress import shape_proposition
    from core.semantics.literals import classify_literal
    from core.semantics.sentence_machine import form_of
    agent = _STATE["agent"]
    failures: List[Dict[str, Any]] = []
    counts = Counter()
    said_uses: List[Tuple[str, str, str, str]] = []
    heard: List[Tuple[str, ...]] = []
    facts: List[Tuple[Any, ...]] = []
    for record in records:
        quality = round(float(record.quality), 3)
        if record.meaning is not None:
            sentence = record.sentence
            try:
                if not sentence:
                    sentence = TeachingPass._said(record)
                    counts["said" if sentence else "not_said"] += 1
            except Exception as error:
                failures.append(_failure("saying", record, error))
                continue
            if sentence:
                try:
                    heard.append(tuple(p.text for p in form_of(sentence)))
                    for fact in dr.listening_facts(record.meaning):
                        if fact.relation not in ("isa", "instance_of"):
                            said_uses.append((fact.relation, str(fact.obj), "object", str(fact.subject)))
                            said_uses.append((fact.relation, str(fact.subject), "subject", str(fact.obj)))
                except Exception as error:
                    failures.append(_failure("said and heard", record, error))
            if record.example:
                continue
            buckets: Dict[Any, List[Tuple[str, ...]]] = {}
            meanings = Counter()
            rules: List[Any] = []
            try:
                TeachingPass._bucket_meaning(record, sentence or "", quality, buckets, meanings, rules)
            except Exception as error:
                failures.append(_failure("splitting the meaning", record, error))
                continue
            for (_q, positive, speaker), told in buckets.items():
                facts.extend((subject, relation, obj, said, positive, speaker)
                             for subject, relation, obj, said in told)
            counts["rules"] += len(rules)
        else:
            facts.append((record.subject, record.relation, record.obj, record.sentence, True, None))
    for subject, relation, obj, said, positive, speaker in facts:
        counts["facts"] += 1
        try:
            subject_term, relation_term, obj_term, refusal = shape_proposition(subject, relation, obj)
            for term in (subject_term, obj_term):
                if term:
                    classify_literal(term)
        except Exception as error:
            failures.append(_failure("shaping the fact", (subject, relation, obj), error))
            continue
        if refusal:
            counts["refused_by_shape"] += 1
            continue
        claim = " ".join(str(p) for p in (subject_term, relation_term, obj_term) if p)
        surface = said or claim
        _read(agent, surface, "reading the fact's memory", failures)
        try:
            agent.note_taught_proposition(surface, f"{subject}|{relation}|{obj}")
        except Exception as error:
            failures.append(_failure("noting the fact's word classes", surface, error))
    return {"failures": failures, "counts": dict(counts), "said": said_uses, "heard": heard}


def _read_texts(chunk) -> Dict[str, Any]:
    stage, texts = chunk
    failures: List[Dict[str, Any]] = []
    for text in texts:
        _read(_STATE["agent"], text, stage, failures)
    return {"failures": failures, "counts": {stage: len(texts)}}


def _said_contents(uses) -> List[str]:
    """What each word is said of, written as `remember_said` writes its memories."""
    grouped: Dict[Tuple[str, str, str], Counter] = defaultdict(Counter)
    for relation, word, side, other in uses:
        grouped[(str(relation), str(word).strip().lower(), str(side))][str(other).strip().lower()] += 1
    out = []
    for (relation, word, side), others in grouped.items():
        most = sorted(others.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
        out.append(f'"{word}" ({relation}, {side}) is said of ' + ", ".join(f"{o} ({n})" for o, n in most))
    return out


def _heard_contents(sentences) -> List[str]:
    """What was heard after each word, written as `remember_heard` writes its memories."""
    after: Dict[str, set] = defaultdict(set)
    for words in sentences:
        for earlier, later in zip(words, words[1:]):
            after[earlier.lower()].add(later.lower())
    return [f"Heard after {word}: " + ", ".join(sorted(nxt)[:24]) + (", ..." if len(nxt) > 24 else "")
            for word, nxt in after.items()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--domain", default="english")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--chunk", type=int, default=2000)
    parser.add_argument("--out", default="logs/teaching_preflight.json")
    parser.add_argument("--records", default=None,
                        help="records: the JSON Lines file of records to replay (`SentenceRecord`, `WordRecord`)")
    parser.add_argument("--treebank", default=None, choices=("ewt", "gum", "lines", "partut", "atis", "eslspok"))
    parser.add_argument("--pmb", default="gold", choices=("gold", "silver"))
    args = parser.parse_args()
    if "lyric_dev" not in os.environ.get("POSTGRES_DATABASE", ""):
        raise SystemExit("the preflight reads the sandbox's language: POSTGRES_DATABASE=lyric_dev")

    import importlib.util
    spec = importlib.util.spec_from_file_location("teach", "scripts/teach.py")
    teach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(teach)
    from core.learning.teaching import TeachingPass, Report
    # EVERY FIELD `build_source` READS, or the source it builds raises before a single record is checked. Four were
    # missing (`records`, `treebank`, `pmb`, `small`, `sense`, `part`), so the sources that need one -- `records`
    # above all, which is the format a vocabulary is taught from -- could not be preflighted at all.
    source = teach.build_source(argparse.Namespace(
        source=args.source, domain=args.domain, limit=None, head=False, cache=None, section=None, dump=None,
        relations="grammar", lesson=None, definitions=False, records=args.records, treebank=args.treebank,
        pmb=args.pmb, small=None, sense=(), part=()))
    started = time.time()
    records = TeachingPass(source, domain=args.domain, limit=None, sample=True)._harvest(
        Report(source=source.name, domain=args.domain))
    if args.limit:
        records = records[:args.limit]
    print(f"{len(records):,} records harvested in {time.time() - started:.0f}s", flush=True)
    usage = list(source.usage()) if hasattr(source, "usage") else []
    said_of = list(source.said_of()) if hasattr(source, "said_of") else []

    failures: List[Dict[str, Any]] = []
    counts: Counter = Counter()
    said_uses: List[Tuple[str, str, str, str]] = []
    heard: List[Tuple[str, ...]] = []
    chunks = [records[i:i + args.chunk] for i in range(0, len(records), args.chunk)]
    context = multiprocessing.get_context("spawn")
    with context.Pool(args.workers, initializer=_start_worker) as pool:
        done = 0
        for result in pool.imap_unordered(_replay_records, chunks):
            failures.extend(result["failures"])
            counts.update(result["counts"])
            said_uses.extend(result["said"])
            heard.extend(result["heard"])
            done += 1
            if done % 25 == 0 or done == len(chunks):
                print(f"  {time.strftime('%H:%M:%S')}  records {min(done * args.chunk, len(records)):,}/"
                      f"{len(records):,}  failures {len(failures)}", flush=True)
        # What the source counted of its words in use, as `learn_said` keeps it.
        said_uses.extend((relation, word, side, other) for relation, word, side, other, *_ in said_of)
        texts = ([("reading what words are said of", t) for t in _said_contents(said_uses)]
                 + [("reading what was heard after", t) for t in _heard_contents(heard)])
        groups: Dict[str, List[str]] = defaultdict(list)
        for stage, text in texts:
            groups[stage].append(text)
        jobs = [(stage, items[i:i + args.chunk]) for stage, items in groups.items()
                for i in range(0, len(items), args.chunk)]
        for result in pool.imap_unordered(_read_texts, jobs):
            failures.extend(result["failures"])
            counts.update(result["counts"])
        print(f"  {time.strftime('%H:%M:%S')}  said-of and heard memories read", flush=True)

    # The source's counts of use, looked up as `learn_usage` looks them up.
    from core.semantics.sentence_machine import form_of
    for word, concept, times, forms in usage:
        counts["usage"] += 1
        try:
            tuple(p.text for p in form_of(str(word)))
            int(times)
        except Exception as error:
            failures.append(_failure("usage", (word, concept, times, forms), error))

    meanings = sum(1 for r in records if r.meaning is not None and not r.sentence)
    if meanings and counts.get("said", 0) < 0.5 * meanings:
        failures.append({"stage": "the replay itself", "item": f"{counts.get('said', 0)} of {meanings} said",
                         "error": "RuntimeError: most meanings were not said; the language the workers read is wrong",
                         "where": []})
    by_kind = Counter((f["stage"], f["error"].split(":")[0], f["where"][-1] if f["where"] else "") for f in failures)
    report = {"records": len(records), "seconds": round(time.time() - started), "counts": dict(counts),
              "failures": len(failures), "kinds": [{"stage": s, "error": e, "where": w, "n": n}
                                                   for (s, e, w), n in by_kind.most_common()],
              "examples": failures[:200]}
    Path(args.out).write_text(json.dumps(report, indent=1))
    print(f"\n{len(failures)} failure(s) in {report['seconds']}s; {dict(counts)}")
    for kind in report["kinds"][:20]:
        print(f"  {kind['n']:>6}  {kind['stage']}: {kind['error']}  at {kind['where']}")
    print(f"report: {args.out}")
    return 1 if failures else 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
