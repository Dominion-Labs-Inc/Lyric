"""SENSES-01: a bound on the sense combinations of each grouping of the words, against the reader with none.

The reader builds every reading whole, every sense of every word crossed with every other, and on main a long
sentence never finished: "A prime number is a natural number greater than 1 that has no divisors other than 1 and
itself." built no whole reading in ten minutes (lab notebook 2026-10-19 (23)). `derived_reader.SENSES_KEPT`
(`LYRIC_SENSES=N`) keeps, for each grouping of the words, the N sense combinations that suppose least and were met
most often (`_senses_kept`). This measures what that bound changes, before any run depends on it.

Every lesson sentence (`ListeningSource`, as the listener's counts are made) and every sentence and question of
UNDERSTANDS-PROSE-01 is read with no bound and with each N asked for, in one load. Of each, as read: the readings
each utterance hands the listener (and, for the prose, read in parts as a conversation reads it, the readings of
each part), the one the listener takes (`heard`, memory at hand, no conversation before it), and the seconds it
took. Then for each N: how many sentences read to the same readings and the same choice as with no bound, how many
lessons read as taught, and every sentence that changed, with what it changed from and to.

A sentence that does not finish with no bound within the run's own limit per sentence (`--limit`, seconds; the
probe's, never the reader's) is recorded as not finishing and compared on nothing; with each N it is still read
and timed. No bar: it measures. Then it checks nothing was written.

Each sentence's result is written as it is read (`work/<stamp>_sentences.jsonl`, kept out of git as every run's
working files are); `--resume FILE` reads that file and goes on after the last sentence in it.

Run (from the Lyric folder; starts no substrate, reads only):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/SENSES-01/experiment.py \
        [--senses 4,8,16] [--limit 900] [--prose-only] [--resume experiments/SENSES-01/work/<stamp>_sentences.jsonl]
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def say(*a):
    print(*a, flush=True)


def argument(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


#: Written for a bound's readings where they are those read with no bound, so a run's file holds what changed.
SAME = "as with no bound"


def readings(row, bound):
    """A sentence's readings with one bound, as read."""
    way = row["ways"][bound]["readings"]
    return row["ways"]["0"]["readings"] if way == SAME else way


class _Limit(BaseException):
    """The run's own limit on one sentence read with no bound: a BaseException, so no handler of errors inside the
    reading can take it for one of them."""


def _alarm(*_):
    raise _Limit()


async def read_one(dr, view, sentence, parts, limit):
    """What one sentence reads to: each utterance's readings (canonical, sorted) and its parts' where read in parts,
    the listener's choice for each utterance, and how many readings reached the listener. `limit`: the run's own
    limit on the reading, in seconds (0, none); never on the listener, which waits on memory."""
    signal.alarm(limit)
    try:
        utterances = dr.read_text(sentence, view, parts=parts)
    finally:
        signal.alarm(0)
    readings, chosen, handed = [], [], 0
    for u in utterances:
        mine = sorted({("composed: " if r.composed else "") + r.meaning.canonical() for r in u.readings})
        stretches = [[s.start, s.end, sorted({r.meaning.canonical() for r in s.readings})]
                     for s in u.partial if s.readings]
        readings.append({"readings": mine, "parts": stretches})
        handed += len(u.readings) + sum(len(s.readings) for s in u.partial)
        if u.readings:
            heard = await dr.heard(u.readings)
            chosen.append(heard.meaning.canonical() if heard is not None else None)
        else:
            chosen.append(None)
    return {"readings": readings, "chosen": chosen, "handed": handed,
            "understood": bool(utterances) and all(u.understood for u in utterances)}


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(_results() / "run.log", mode="w")])
    from experiments._evidence import RunRecord
    bounds = [int(n) for n in argument("--senses", "4,8,16").split(",") if n.strip()]
    limit = int(argument("--limit", "900"))
    prose_only = "--prose-only" in sys.argv
    EV = RunRecord("SENSES-01",
                   claim="a bound on the sense combinations of each grouping of the words lets every sentence "
                         "finish reading and changes no reading the listener chooses",
                   hypothesis="with N sense combinations kept per grouping (those supposing least, then met most "
                              "often), every lesson and prose sentence that finishes with no bound reads to the same "
                              "readings and the same choice (no bar: what changes is measured)")
    EV.note(f"bounds measured: {bounds}; the run's own limit on one sentence read with no bound: {limit}s")
    quiet = io.StringIO()
    say("loading memory, the beliefs and the language view (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.learning.teaching_sources import ListeningSource
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr
        agent = await get_memory_agent()
        await agent.initialize()
        await get_uncertainty_system().load_from_db()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
        db = await get_unified_db()
        if not getattr(db, "initialized", False):
            await db.initialize()
    EV.check("the run is on the store it says", await EV.verify_database() is not None,
             f"connected to {EV.verified_database}")

    async def written():
        rows = await db.execute_query(
            "SELECT schemaname || '.' || relname AS name, n_tup_ins + n_tup_upd + n_tup_del AS n "
            "FROM pg_stat_user_tables")
        return {row["name"]: int(row["n"]) for row in rows or ()}
    before = await written()

    view = dr.live_view()
    EV.check("memory holds what was taught of English", len(view) > 0, f"{len(view):,} constructions and links")
    texts = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text())
    items = [("prose", sentence, None) for text in texts
             for sentence in list(text["text"]) + [q["q"] for q in text["questions"]]]
    if not prose_only:
        items += [("lesson", sentence, meaning.canonical()) for sentence, meaning in ListeningSource().listening_pairs()]
    say(f"  {sum(1 for k, _, _ in items if k == 'prose')} prose sentences and questions, "
        f"{sum(1 for k, _, _ in items if k == 'lesson'):,} lesson sentences; bounds {bounds}")

    resumed = argument("--resume", None)
    path = Path(resumed) if resumed else _work() / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_sentences.jsonl"
    done = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if resumed else []
    say(f"  each sentence written to {path}" + (f"; {len(done)} already read" if done else ""))
    signal.signal(signal.SIGALRM, _alarm)
    kept = dr.SENSES_KEPT
    with path.open("a") as out:
        for at, (kind, sentence, taught) in enumerate(items):
            if at < len(done):
                continue
            row = {"kind": kind, "sentence": sentence, "taught": taught, "ways": {}}
            for bound in [0] + bounds:
                dr.SENSES_KEPT = bound
                started = time.perf_counter()
                try:
                    read = await read_one(dr, view, sentence, kind == "prose", 0 if bound else limit)
                except _Limit:
                    read = {"not finished": True}
                read["seconds"] = round(time.perf_counter() - started, 2)
                row["ways"][str(bound)] = read
            dr.SENSES_KEPT = kept
            for bound in bounds:
                way = row["ways"][str(bound)]
                if "readings" in way and way["readings"] == row["ways"]["0"].get("readings"):
                    way["readings"] = SAME
            out.write(json.dumps(row) + "\n")
            out.flush()
            done.append(row)
            if kind == "prose" or at % 100 == 0:
                ways = "  ".join(f"{b}: {row['ways'][b]['seconds']}s" + (" NOT FINISHED" if row['ways'][b].get("not finished") else "")
                                 for b in row["ways"])
                say(f"  [{at + 1}/{len(items)}] {ways}  {sentence[:70]}")
            await asyncio.sleep(0)

    # WHAT EACH BOUND CHANGED, against no bound, of the sentences that finished with none.
    say("")
    finished = [row for row in done if not row["ways"]["0"].get("not finished")]
    unfinished = [row["sentence"] for row in done if row["ways"]["0"].get("not finished")]
    EV.metric("sentences read", len(done), unit="count")
    EV.metric("sentences not finished with no bound", len(unfinished), unit="count",
              note="; ".join(unfinished) or "none")
    say(f"  {len(done)} read; not finished with no bound within {limit}s: {len(unfinished)} {unfinished}")
    changed_all = {}
    for bound in ["0"] + [str(b) for b in bounds]:
        for kind in ("prose", "lesson"):
            rows = [row for row in done if row["kind"] == kind]
            if not rows:
                continue
            seconds = sum(row["ways"][bound]["seconds"] for row in rows)
            handed = sum(row["ways"][bound].get("handed", 0) for row in rows)
            EV.metric(f"{kind}: seconds reading, bound {bound}", round(seconds, 1), unit="seconds")
            EV.metric(f"{kind}: readings handed to the listener, bound {bound}", handed, unit="count")
            line = f"  bound {bound:>3} {kind:6}: {seconds:8.0f}s, {handed:,} readings to the listener"
            if kind == "lesson":
                taught = sum(1 for row in rows if row["ways"][bound].get("chosen") == [row["taught"]])
                EV.metric(f"lessons read as taught, bound {bound}", taught, unit="count", note=f"of {len(rows):,}")
                line += f", {taught:,} of {len(rows):,} lessons read as taught"
            if bound != "0":
                compared = [row for row in finished if row["kind"] == kind]
                same_readings = sum(1 for row in compared if readings(row, bound) == readings(row, "0"))
                same_choice = sum(1 for row in compared
                                  if row["ways"][bound]["chosen"] == row["ways"]["0"]["chosen"])
                EV.metric(f"{kind}: same readings as with no bound, bound {bound}", same_readings, unit="count",
                          note=f"of {len(compared):,} that finished with no bound")
                EV.metric(f"{kind}: same choice as with no bound, bound {bound}", same_choice, unit="count",
                          note=f"of {len(compared):,} that finished with no bound")
                line += (f"; of {len(compared):,} finished with no bound, same readings {same_readings:,}, "
                         f"same choice {same_choice:,}")
                changed_all[f"{kind} {bound}"] = [
                    {"sentence": row["sentence"], "taught": row["taught"],
                     "chosen with no bound": row["ways"]["0"]["chosen"], "chosen": row["ways"][bound]["chosen"],
                     "readings with no bound": sum(len(u["readings"]) for u in readings(row, "0")),
                     "readings": sum(len(u["readings"]) for u in readings(row, bound)),
                     "lost": sorted({r for u in readings(row, "0") for r in u["readings"]}
                                    - {r for u in readings(row, bound) for r in u["readings"]})[:20]}
                    for row in compared if row["ways"][bound]["chosen"] != row["ways"]["0"]["chosen"]]
            say(line)
    for name, changed in changed_all.items():
        if changed:
            say(f"\n  choice changed, {name}: {len(changed)}")
            for c in changed[:40]:
                say(f"    {c['sentence']!r}: {c['chosen with no bound']} -> {c['chosen']}")
    (_results() / path.name.replace("_sentences.jsonl", "_changed.json")).write_text(json.dumps(changed_all, indent=1))

    await asyncio.sleep(1)
    after = await written()
    moved = {name: after[name] - before.get(name, 0) for name in after if after[name] != before.get(name, 0)}
    EV.check("reading wrote nothing to the store", not moved,
             "; ".join(f"{name} +{n}" for name, n in sorted(moved.items())) or "no table written to")
    record = EV.write()
    say(f"\n  run record: {record}")
    return 0 if EV.failed == 0 else 1


def _results() -> Path:
    (HERE / "results").mkdir(exist_ok=True)
    return HERE / "results"


def _work() -> Path:
    """Where each sentence is written as it is read: the run's own working file, regenerable, not kept in git."""
    (HERE / "work").mkdir(exist_ok=True)
    return HERE / "work"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
