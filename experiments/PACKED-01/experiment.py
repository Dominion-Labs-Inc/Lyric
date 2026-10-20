"""PACKED-01: the reader keeping each word's senses together and the listener choosing over the structure, against the
reader that builds every reading and the listener that weighs each.

The reader built every reading whole, every sense of every word crossed with every other and every bracketing of
every slot with every other, then kept the few it hands the listener: on main a long sentence never finished
(UNDERSTANDS-PROSE-01's primes sentence; lab notebook 2026-10-19 (23), handoff §0). Now a word held for several
things in a slot is one packed word (`derived_reader.Sense`), the readings it is in are kept packed, memory is asked
about the facts their senses make (`listening`), and the listener finds the best senses over the structure
(`meant`, `_choices`).

Every lesson sentence (`ListeningSource`) and every sentence and question of UNDERSTANDS-PROSE-01 (read in parts, as a
conversation reads them) is read once, and each utterance's choice made both ways, in one load:

- packed: the readings as read, and the listener over them (`listening`, `meant`), timed;
- one by one: the utterance read again as the reader read it before, every sense of every word apart (charts that
  do not pack), and the listener weighing each reading (`meant` on readings with no packed words), timed; and
  whether those readings are exactly the ones the packed readings stand for (`unpacked`): each meaning, and the
  reading of it kept, supposed, score, uses, constructions and links alike. What can never finish is
  this way: a sentence whose readings one by one do not finish within the run's own limit (`--limit`, seconds; the
  probe's, never the reader's) is compared on nothing, and its packed reading is still timed.

Then: how many choices are the same, how many lessons read as taught each way, the seconds each way, every sentence
whose choice changed (`_changed.json`), and that nothing was written to the store. No bar: it measures.

Run (from the Lyric folder; starts no substrate, reads only):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/PACKED-01/experiment.py \
        [--limit 600] [--prose-only] [--resume experiments/PACKED-01/work/<stamp>_sentences.jsonl]
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


class _Limit(BaseException):
    """The run's own limit on reading one sentence's readings one by one: a BaseException, so no handler of errors
    inside the reading can take it for one of them."""


def _alarm(*_):
    raise _Limit()


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(_results() / "run.log", mode="w")])
    from experiments._evidence import RunRecord
    limit = int(argument("--limit", "600"))
    prose_only = "--prose-only" in sys.argv
    EV = RunRecord("PACKED-01",
                   claim="the reader that keeps each word's senses together, with the listener choosing over the "
                         "structure, chooses as the reader that builds every reading and the listener that weighs "
                         "each, and finishes where that one does not",
                   hypothesis="every lesson and prose sentence that finishes one by one is taken the same way packed; "
                              "lessons read as taught do not drop (no bar: what changes is measured)")
    EV.note(f"the run's own limit on reading one sentence one by one: {limit}s")
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
        f"{sum(1 for k, _, _ in items if k == 'lesson'):,} lesson sentences")

    resumed = argument("--resume", None)
    path = Path(resumed) if resumed else _work() / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_sentences.jsonl"
    done = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if resumed else []
    say(f"  each sentence written to {path}" + (f"; {len(done)} already read" if done else ""))
    signal.signal(signal.SIGALRM, _alarm)
    with path.open("a") as out:
        for at, (kind, sentence, taught) in enumerate(items):
            if at < len(done):
                continue
            started = time.perf_counter()
            utterances = dr.read_text(sentence, view, parts=kind == "prose")
            packed_chosen = []
            for u in utterances:
                if u.readings:
                    chosen = dr.meant(u.readings, view, heard=await dr.listening((u.readings,)))
                    packed_chosen.append(chosen.meaning.canonical() if chosen is not None else None)
                else:
                    packed_chosen.append(None)
            packed_seconds = time.perf_counter() - started
            row = {"kind": kind, "sentence": sentence, "taught": taught,
                   "packed": {"chosen": packed_chosen, "seconds": round(packed_seconds, 2),
                              "readings": sum(len(u.readings) for u in utterances),
                              "packed": sum(1 for u in utterances for r in u.readings if r.senses)}}
            started = time.perf_counter()
            signal.alarm(limit)
            try:
                # ONE BY ONE: each utterance read again as the reader read it before, every sense of every word apart
                # (charts that do not pack); a composed reading is the same either way.
                # A quotation's readings are made one by one already (`_with_quotation`).
                old = [u.readings if any(r.composed for r in u.readings) or any(p.text == dr.QUOTED for p in u.pieces)
                       else (dr._read_pieces(u.pieces, view, {False: dr._Chart(), True: dr._Chart()})
                             if u.readings else ())
                       for u in utterances]
                made = [dr.unpacked(u.readings, view) for u in utterances]
                signal.alarm(0)
                one_chosen = []
                for readings in old:
                    if readings:
                        chosen = dr.meant(readings, view, heard=await dr.listening((readings,)))
                        one_chosen.append(chosen.meaning.canonical() if chosen is not None else None)
                    else:
                        one_chosen.append(None)

                def kept(readings):
                    return {r.meaning.canonical(): (r.supposed, round(r.score, 9), round(r.uses, 9), r.key, r.links,
                                                    r.proposed) for r in readings}
                row["one by one"] = {"chosen": one_chosen, "seconds": round(time.perf_counter() - started, 2),
                                     "readings": sum(len(r) for r in old),
                                     "same readings": all(kept(a) == kept(b) for a, b in zip(old, made))}
            except _Limit:
                row["one by one"] = {"not finished": True, "seconds": round(time.perf_counter() - started, 2)}
            finally:
                signal.alarm(0)
            out.write(json.dumps(row) + "\n")
            out.flush()
            done.append(row)
            if kind == "prose" or at % 100 == 0:
                one = row["one by one"]
                same = "NOT FINISHED one by one" if one.get("not finished") else (
                    ("same" if one["chosen"] == row["packed"]["chosen"] else "CHANGED")
                    + ("" if one["same readings"] else ", READINGS DIFFER"))
                say(f"  [{at + 1}/{len(items)}] packed {row['packed']['seconds']}s ({row['packed']['readings']} readings), "
                    f"one by one {one['seconds']}s ({one.get('readings', '-')}): {same}  {sentence[:60]}")
            await asyncio.sleep(0)

    say("")
    changed_all = {}
    unfinished = [row["sentence"] for row in done if row["one by one"].get("not finished")]
    EV.metric("sentences read", len(done), unit="count")
    EV.metric("sentences not finished one by one", len(unfinished), unit="count", note="; ".join(unfinished) or "none")
    for kind in ("prose", "lesson"):
        rows = [row for row in done if row["kind"] == kind]
        if not rows:
            continue
        compared = [row for row in rows if not row["one by one"].get("not finished")]
        same = sum(1 for row in compared if row["packed"]["chosen"] == row["one by one"]["chosen"])
        same_readings = sum(1 for row in compared if row["one by one"]["same readings"])
        EV.metric(f"{kind}: the listener handed the same readings packed as one by one", same_readings, unit="count",
                  note=f"of {len(compared):,}: each meaning, and the reading of it kept (supposed, score, uses, "
                       f"constructions, links)")
        packed_seconds = sum(row["packed"]["seconds"] for row in rows)
        one_seconds = sum(row["one by one"]["seconds"] for row in compared)
        EV.metric(f"{kind}: same choice packed as one by one", same, unit="count",
                  note=f"of {len(compared):,} that finished one by one")
        EV.metric(f"{kind}: seconds packed", round(packed_seconds, 1), unit="seconds", note=f"{len(rows):,} sentences")
        EV.metric(f"{kind}: seconds one by one", round(one_seconds, 1), unit="seconds",
                  note=f"{len(compared):,} sentences that finished")
        line = (f"  {kind:6}: same readings {same_readings:,}, same choice {same:,} of {len(compared):,}; "
                f"packed {packed_seconds:.0f}s for {len(rows):,}, "
                f"one by one {one_seconds:.0f}s for {len(compared):,}")
        if kind == "lesson":
            taught_packed = sum(1 for row in rows if row["packed"]["chosen"] == [row["taught"]])
            taught_one = sum(1 for row in compared if row["one by one"]["chosen"] == [row["taught"]])
            EV.metric("lessons read as taught, packed", taught_packed, unit="count", note=f"of {len(rows):,}")
            EV.metric("lessons read as taught, one by one", taught_one, unit="count", note=f"of {len(compared):,}")
            line += f"; read as taught packed {taught_packed:,}, one by one {taught_one:,}"
        say(line)
        changed_all[kind] = [{"sentence": row["sentence"], "taught": row["taught"],
                              "packed": row["packed"]["chosen"], "one by one": row["one by one"]["chosen"]}
                             for row in compared if row["packed"]["chosen"] != row["one by one"]["chosen"]]
        for c in changed_all[kind][:40]:
            say(f"    changed: {c['sentence']!r}: {c['one by one']} -> {c['packed']}")
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
