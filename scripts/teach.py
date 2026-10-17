#!/usr/bin/env python3
"""Teach the substrate. THE teaching entry point, and it teaches a LIVE substrate.

Every teaching script before this one called `LyricSystem.initialize()` and
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

  --source   conceptnet | wordnet | wordnet-examples | wordnet-usage | listening | treebank | propbank | composition
             | wikidata | closed-classes | lesson
             wordnet-examples: WordNet's examples of English and none of its facts, for a store WordNet was taught
             to before they were said: its nouns' plurals ("Hawks are raptors."), its verbs' forms ("Tom strolled.")
             and kinds ("To stroll is to walk."), its adjectives' likenesses ("To be lovely is to be beautiful.")
             wordnet-usage: how often WordNet's words were met naming each sense (SemCor), and nothing else, for a
             store that holds the words
             listening: what the listener's evidence is worth, counted on the English lessons (data/lessons), whose
             meanings say which reading was meant; nothing else is taught
             treebank: how the words of a sentence go together, from sentences analysed by hand (the English Web
             Treebank's training part, test_data/syntax/UD_English-EWT): each kept whole, its standing a belief;
             --limit N takes the first N sentences
             propbank: which phrases are a happening's arguments and what each is, from PropBank's annotations of the
             same treebank's training part (test_data/syntax/propbank-release and propbank-frames): each annotated
             sentence kept whole, its standing a belief; --limit N takes the first N
             composition: the lessons' sentences each with its taught meaning (data/lessons), kept whole for the
             composer to learn what a sentence means from how its words go together; --limit N takes the first N
  --relations grammar | practical | taxonomy      (conceptnet only)
  --limit N  teach a uniform sample of N across the WHOLE source
  --small N  a uniform sample of N, and of what the source states about its whole vocabulary (word classes, usage,
             what words are said of) only what concerns their words: every phase, small, end to end in minutes
  --head     take the source's first N instead of a sample
  --definitions  (wordnet) also offer each definition as a sentence with no meaning given
  --sense S  (wordnet) only the facts the sense S is in (peoples.n.01), and what WordNet states about its vocabulary
             only for their words; given several times, several senses
  --part P   (wordnet, wordnet-examples) only the senses of part of speech P (n, v, a): their facts and the
             sentences they are said in, or their examples only; given several times, several parts
  --lesson F (lesson) a lesson file; given several times, the lessons are taught in that order in one running
             substrate, each under its own name, then reviewed once

Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan \
     LYRIC_NO_WATCHDOG=1 ./venv_lyric/bin/python3 scripts/teach.py --source wordnet
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
               "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1",
               "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(ROOT))
from core.utils.stack_dump import dump_stacks_on_signal  # noqa: E402
dump_stacks_on_signal("teach", ROOT / "logs")

SESSIONS = ROOT / "docs" / "teaching_sessions"
DUMP = ROOT / "data" / "bulk" / "conceptnet-assertions-5.7.0.csv.gz"


def build_source(args):
    from core.learning.teaching_sources import (ClosedClassSource,
                                                CompositionSource, ConceptNetSource, ListeningSource,
                                                PropBankSource, TreebankSource, WikidataSource,
                                                WordNetExamplesSource,
                                                WordNetSource, WordNetUsageSource)
    if args.source == "conceptnet":
        relations = ConceptNetSource.RELATION_SETS.get(args.relations)
        if relations is None:
            raise SystemExit(f"--relations must be one of "
                             f"{sorted(ConceptNetSource.RELATION_SETS)}")
        return ConceptNetSource(path=args.dump or str(DUMP),
                                relations=dict(relations))
    if args.source == "wordnet":
        return WordNetSource(definitions=args.definitions, senses=tuple(args.sense or ()), parts=tuple(args.part or ()))
    if args.source == "wordnet-examples":
        return WordNetExamplesSource(parts=tuple(args.part or ()))
    if args.source == "wordnet-usage":
        return WordNetUsageSource(parts=tuple(args.part or ()))
    if args.source == "listening":
        return ListeningSource()
    if args.source == "treebank":
        return TreebankSource()
    if args.source == "propbank":
        return PropBankSource()
    if args.source == "composition":
        return CompositionSource()
    if args.source == "closed-classes":
        # The finite classes of English. No facts, only what class each word
        # has -- which is the half of language a taxonomy source cannot state.
        return ClosedClassSource()
    if args.source == "wikidata":
        if not args.cache:
            raise SystemExit("--source wikidata needs --cache <edges.json>")
        return WikidataSource(cache_path=args.cache, section=args.section)
    raise SystemExit(f"unknown source {args.source!r}")


def build_sources(args):
    """What to teach from: one source, or for `lesson` each lesson given, in the order given. Sentences with their
    meanings, written by a teacher (data/lessons/); each lesson is its own source, under its own name, as when it is
    taught alone."""
    if args.source != "lesson":
        return [build_source(args)]
    if not args.lesson:
        raise SystemExit("--source lesson needs --lesson <lesson.json>")
    from core.learning.teaching_sources import LessonSource
    return [LessonSource(path=path) for path in args.lesson]


class _Passes:
    """Several lessons' reports, said as one session's (`write_session` reads `lines`)."""

    def __init__(self, reports):
        self.reports = reports

    def lines(self):
        if len(self.reports) == 1:
            return self.reports[0][1].lines()
        return [f"{name}: {line}" for name, report in self.reports for line in report.lines()]


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
    """The substrate's own belief that it is competent in this domain: read under its claim, or under the wording
    it held before it was renamed (`UniversalDomainMaster.COMPETENCE_CLAIM`), which the store keeps until the
    belief is next written."""
    from core.integration.universal_domain_master import UniversalDomainMaster as UDM
    row = await db.execute_query(
        "SELECT posterior_probability p, update_count u FROM unified.beliefs "
        "WHERE claim = ANY($1::text[]) ORDER BY update_count DESC LIMIT 1",
        ([f"{UDM.COMPETENCE_CLAIM}{domain}", f"{UDM._OLD_COMPETENCE_CLAIM}{domain}"],),
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
                        choices=("conceptnet", "wordnet", "wordnet-examples", "wordnet-usage", "listening",
                                 "treebank", "propbank", "composition", "wikidata", "closed-classes", "lesson"))
    parser.add_argument("--domain", default="general")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--small", type=int, default=None)
    parser.add_argument("--head", action="store_true")
    parser.add_argument("--cache", default=None)
    parser.add_argument("--section", default=None)
    parser.add_argument("--dump", default=None)
    parser.add_argument("--relations", default="grammar")
    parser.add_argument("--lesson", action="append", default=None,
                        help="a lesson file; give it several times to teach several, in order, in one run")
    parser.add_argument("--definitions", action="store_true",
                        help="wordnet: also offer each definition as a sentence with no meaning, read or dropped")
    parser.add_argument("--sense", action="append", default=None,
                        help="wordnet: teach only the facts this sense is in (peoples.n.01); give it several times")
    parser.add_argument("--part", action="append", default=None, choices=("n", "v", "a", "r"),
                        help="wordnet, wordnet-examples: teach only the senses of this part of speech; give it several "
                             "times")
    args = parser.parse_args()
    if args.small is not None:
        if args.limit is not None:
            parser.error("--small is a limit of its own; give one or the other")
        args.limit = args.small
    if args.sense and args.source != "wordnet":
        parser.error("--sense is WordNet's")
    if args.part and args.source not in ("wordnet", "wordnet-examples", "wordnet-usage"):
        parser.error("--part is WordNet's and its examples'")

    from core.learning.teaching import TeachingPass

    sources = build_sources(args)
    quiet = io.StringIO()

    print("starting the substrate…", flush=True)
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
        at = time.strftime("%H:%M:%S")
        if counts.get("phase"):
            print(f"  {at}  {counts['phase']}: {done:,}/{total:,}", flush=True)
            return
        print(f"  {at}  facts: {done:,}/{total:,}  admitted={counts.get('admitted', 0):,} "
              f"refused={counts.get('refused', 0):,}", flush=True)

    reports = []
    for source in sources:
        # A lesson is taught in the order it is written: each pair is learned from
        # what the pairs before it left, so it is never sampled. Lessons are taught
        # in the order given, each from what the ones before it left.
        pass_ = TeachingPass(source, domain=args.domain, limit=args.limit,
                             sample=not args.head and args.source != "lesson",
                             # Cut to some senses, what WordNet states about its whole vocabulary is taught only
                             # for the words their facts use, as for a small pass's.
                             small=args.small is not None or bool(args.sense) or bool(args.part),
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
            reports.append((source.name, await pass_.run(coordinator.learning)))
    report = _Passes(reports)

    print("waiting for the substrate to finish reacting…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        settled = await settle(coordinator)
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        # NOTHING HERE IS SUPPRESSED. A belief write that fails is knowledge the
        # run reported and did not keep; a view that will not warm is a store
        # the reader cannot read. Either ends the run with its error.
        await get_uncertainty_system().flush_pending_writes()
        # Nothing to flush: word classes are derived from memories, which
        # are already durable. Warm the view so a reader in this process sees
        # what this session just taught.
        await coordinator.memory.warm_word_classes()
    # WHAT WAS LEARNED, REVIEWED BY THE SUBSTRATE ITSELF: it asks itself about what it holds in the domain and
    # answers, and how it does moves its competence there (`review_learned`). Its count is the pass's own outcome.
    print("reviewing what was learned…", flush=True)
    with contextlib.redirect_stderr(quiet):
        review = await coordinator.learning.review_learned(
            args.domain, progress=lambda done, of: progress(done, of, {"phase": "reviewing what was learned"}))
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
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
        (f"reviewed {review.get('reviewed', 0)} of {review.get('held', 0):,} things held as learned in "
         f"`{args.domain}`: asked {review.get('asked', 0)}, answered {review.get('right', 0)} right; missed: "
         + ", ".join(f"{k.replace('_', ' ')} {review.get(k, 0)}" for k in
                     ("unread", "misread", "denied", "not_derived"))
         + f"; no question taught for {review.get('cannot_ask', 0)}"),
        f"competence in `{args.domain}`: {competence_before} -> {competence_after} "
        f"(posterior, update_count)",
        f"admissions the substrate was NOT told about: {unannounced}",
    ]
    print("\n  what it did about it:")
    for line in extra:
        print(f"    {line}")
    print(f"\n  session: {write_session(args, report, before, after, extra)}")

    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
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
