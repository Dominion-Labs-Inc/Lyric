#!/usr/bin/env python3
"""Teach the substrate. THE teaching entry point, and it teaches a LIVE substrate.

Every teaching script before this one called `TorinAISystem.initialize()` and
never `start()`. That constructs every first-class module -- appraisal,
motivation, the domain authority, perception, the coordinator -- and starts none
of them. The modules were present and inert: they are woken by events, and the
reactive drain worker that runs deferred reactions is started only by
`start_coordination()`, which only `start()` calls. So teaching poured knowledge
into an organ of a substrate that was switched off.

Measured before this: the domain `lexical` holds over 300,000 taught facts, and
the substrate's belief that it has learned that domain sits at its 0.5000 prior,
never once updated. 234 competence beliefs across 163 domains, every one at
0.5000 with zero updates. The substrate could not tell you it had learned
anything, because nothing ever told it.

So this starts the substrate and teaches it while it is running:

  * `start()`, not `initialize()` -- the coordination cycle and the reactive
    drain worker are alive, so what the learning authority announces is heard.
  * The substrate PERCEIVES being taught. A corpus arriving is external input,
    and `process_input` is the one door external input comes through; teaching
    went around it for as long as teaching has existed.
  * Nothing here orchestrates the subsystems. The authority announces an
    admission and the substrate reacts -- domain crystallization, expansion,
    discovery -- on its own drain worker, coalesced, taking as long as it takes.
    That is why this is not a loop over subsystems.
  * It does not exit until the substrate has finished reacting. A pass that
    returns while the drain queue is full has measured its own inserts and
    nothing else.

  --source   conceptnet | wordnet | wikidata
  --relations grammar | practical | taxonomy      (conceptnet only)
  --limit N  teach a uniform sample of N across the WHOLE source
  --head     take the source's first N instead of a sample

Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan \
     TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 scripts/teach.py --source wordnet
"""
import argparse
import asyncio
import contextlib
import io
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1",
               "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(ROOT))

SESSIONS = ROOT / "docs" / "teaching_sessions"
DUMP = ROOT / "data" / "bulk" / "conceptnet-assertions-5.7.0.csv.gz"


def build_source(args):
    from core.learning.teaching_sources import (ClosedClassSource,
                                                ConceptNetSource, LessonSource,
                                                WikidataSource, WordNetSource)
    if args.source == "conceptnet":
        relations = ConceptNetSource.RELATION_SETS.get(args.relations)
        if relations is None:
            raise SystemExit(f"--relations must be one of "
                             f"{sorted(ConceptNetSource.RELATION_SETS)}")
        return ConceptNetSource(path=args.dump or str(DUMP),
                                relations=dict(relations))
    if args.source == "wordnet":
        return WordNetSource()
    if args.source == "closed-classes":
        # The finite classes of English. No facts, only what class each word
        # has -- which is the half of language a taxonomy source cannot state.
        return ClosedClassSource()
    if args.source == "wikidata":
        if not args.cache:
            raise SystemExit("--source wikidata needs --cache <edges.json>")
        return WikidataSource(cache_path=args.cache, section=args.section)
    if args.source == "lesson":
        # Sentences with their meanings, written by a teacher (data/lessons/).
        if not args.lesson:
            raise SystemExit("--source lesson needs --lesson <lesson.json>")
        return LessonSource(path=args.lesson)
    raise SystemExit(f"unknown source {args.source!r}")


async def _count(db, sql, params=()):
    row = await db.execute_query(sql, params, fetch_one=True)
    return int(row["n"]) if row else 0


async def snapshot(db):
    """What the substrate holds. Read from the DATABASE, never from counters."""
    return {
        "concepts": await _count(db, "SELECT COUNT(*) n FROM unified.concepts"),
        "relations": await _count(db, "SELECT COUNT(*) n FROM unified.concept_relations"),
        "beliefs": await _count(db, "SELECT COUNT(*) n FROM unified.beliefs"),
        "domains": await _count(db, "SELECT COUNT(*) n FROM unified.domains"),
        "memberships": await _count(db, "SELECT COUNT(*) n FROM unified.concept_domains"),
        "words": await _count(
            db, "SELECT COUNT(*) n FROM memory_hot.memory_hot "
                "WHERE tags @> '[\"admitted_proposition\"]'::jsonb"),
    }


async def competence(db, domain: str):
    """The substrate's own belief that it has learned this domain."""
    row = await db.execute_query(
        "SELECT posterior_probability p, update_count u FROM unified.beliefs "
        "WHERE claim = $1",
        (f"the substrate has learned the operators of domain {domain}",),
        fetch_one=True)
    return (float(row["p"]), int(row["u"])) if row else (None, None)


async def settle(coordinator, *, quiet_for: float = 8.0, limit: float = 900.0):
    """Wait until the substrate has finished reacting.

    Deferred reactions run on the drain worker, woken by emit. A domain sweep is
    a full graph scan and an admission can wake one, so "done" is not a count of
    what was inserted -- it is the queue being empty and STAYING empty. Returns
    how long the substrate went on working after the last fact was taught.
    """
    started = time.time()
    quiet_since = None
    while time.time() - started < limit:
        # TWO PLACES, NOT ONE. `_wake_domain_discovery` spawns the sweep as its
        # OWN task rather than queueing it, so watching `_reactive_queue` alone
        # returns while the domain authority is still working -- which is how a
        # run reported "reacted for 8s" having waited for nothing. Measured: the
        # sweep takes 1.2s and creates a domain, 42 memberships and a competence
        # belief, none of which had happened yet when the queue first emptied.
        sweep = getattr(coordinator, "_domain_discovery_drain_task", None)
        busy = (len(getattr(coordinator, "_reactive_queue", ()))
                or (sweep is not None and not sweep.done())
                or bool(getattr(coordinator, "_domain_discovery_dirty", False)))
        if busy:
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.time()
        elif time.time() - quiet_since >= quiet_for:
            return time.time() - started
        await asyncio.sleep(1.0)
    return time.time() - started


def write_session(args, report, before, after, extra) -> Path:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = SESSIONS / f"{stamp}_{args.source}.md"
    rows = "\n".join(
        f"| {k} | {before[k]:,} | {after[k]:,} | {after[k] - before[k]:+,} |"
        for k in before)
    path.write_text(
        f"# Teaching session — {args.source}\n\n"
        f"Taught a LIVE substrate (`start()`, coordination cycle and reactive "
        f"drain worker running), so what the learning authority announced was "
        f"heard and reacted to.\n\n"
        "## The pass\n\n"
        + "\n".join(f"- {line}" for line in report.lines())
        + "\n\n## The substrate, before and after\n\n"
        "| | before | after | change |\n|---|---:|---:|---:|\n" + rows
        + "\n\n## What the substrate did about it\n\n"
        + "\n".join(f"- {line}" for line in extra) + "\n")
    return path


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True,
                        choices=("conceptnet", "wordnet", "wikidata",
                                 "closed-classes", "lesson"))
    parser.add_argument("--domain", default="general")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--head", action="store_true")
    parser.add_argument("--cache", default=None)
    parser.add_argument("--section", default=None)
    parser.add_argument("--dump", default=None)
    parser.add_argument("--relations", default="grammar")
    parser.add_argument("--lesson", default=None)
    args = parser.parse_args()

    from core.learning.teaching import TeachingPass

    source = build_source(args)
    quiet = io.StringIO()

    print(f"starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.database import get_database_manager
        from core.main import get_system
        system = get_system()
        # THE WHOLE SUBSTRATE, RUNNING. Not `initialize()`.
        await system.start()
        coordinator = system.autonomous_coordinator
        db = get_database_manager()
        before = await snapshot(db)
        competence_before = await competence(db, args.domain)

    alive = bool(getattr(coordinator, "_reactive_worker", None))
    print(f"  substrate running: coordination={bool(getattr(coordinator, 'coordination_task', None))} "
          f"reactive_drain={alive}", flush=True)
    if not alive:
        raise SystemExit(
            "the reactive drain worker is not running; deferred reactions would "
            "queue forever. Refusing to teach a substrate that cannot react.")

    def progress(done, total, counts):
        print(f"  {done:,}/{total:,}  admitted={counts.get('admitted', 0):,} "
              f"refused={counts.get('refused', 0):,}", flush=True)

    # A lesson is taught in the order it is written: each pair is learned from
    # what the pairs before it left, so it is never sampled.
    pass_ = TeachingPass(source, domain=args.domain, limit=args.limit,
                         sample=not args.head and args.source != "lesson",
                         progress=progress)

    print(f"teaching from {source.name} into {args.domain}…", flush=True)
    with contextlib.redirect_stderr(quiet):
        # THE SUBSTRATE PERCEIVES BEING TAUGHT. External input comes through one
        # door; teaching has never used it.
        with contextlib.redirect_stdout(quiet):
            from core.memory import Origin
            await coordinator.process_input(
                source.name, "knowledge",
                {"domain": args.domain, "source": source.name,
                 "limit": args.limit, "curated": bool(getattr(source, "curated", False))},
                origin=Origin.own("teaching"))
        report = await pass_.run(coordinator.learning)

    print("waiting for the substrate to finish reacting…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        settled = await settle(coordinator)
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        with contextlib.suppress(Exception):
            await get_uncertainty_system().flush_pending_writes()
        # Nothing to flush: word classes are derived from memories, which
        # are already durable. Warm the view so a reader in this process sees
        # what this session just taught.
        with contextlib.suppress(Exception):
            await coordinator.memory.warm_word_classes()
        after = await snapshot(db)
        competence_after = await competence(db, args.domain)
        unannounced = coordinator.learning.system_metrics.get(
            "admissions_unannounced", 0)

    for line in report.lines():
        print(f"  {line}")
    print("\n  the substrate:")
    for k in before:
        print(f"    {k:14} {before[k]:>10,} -> {after[k]:>10,} "
              f"({after[k] - before[k]:+,})")

    extra = [
        f"reacted for {settled:.0f}s after the last fact was taught",
        f"competence in `{args.domain}`: {competence_before} -> {competence_after} "
        f"(posterior, update_count)",
        f"admissions the substrate was NOT told about: {unannounced}",
    ]
    print("\n  what it did about it:")
    for line in extra:
        print(f"    {line}")
    print(f"\n  session: {write_session(args, report, before, after, extra)}")

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        with contextlib.suppress(Exception):
            await system.shutdown()
    return 0


# THE GUARD IS LOAD-BEARING, NOT CEREMONY.
#
# This read `sys.exit(asyncio.run(main()))` at module level. macOS spawns
# multiprocessing children by RE-IMPORTING __main__, and the substrate loads a
# sentence-transformer that does exactly that -- so every child re-entered
# main() and taught the whole corpus again. One launch ran three teaching
# passes over the same source.
#
# Measured: 98,198 word-class rows carrying 57,671 distinct (word, class)
# pairs. Teaching is not an epoch -- the same pair arriving twice is one thing
# the source says, not two witnesses to it -- so this was the double-count
# defect, produced by the launcher rather than by the store.
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(asyncio.run(main()))
