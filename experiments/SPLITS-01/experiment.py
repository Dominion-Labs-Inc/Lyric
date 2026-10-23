"""SPLITS-01: the reader asking the chart where the words split between a form's slots, against the reader that made
every split and threw away each at its first slot nothing stands in.

Reading a page looked up stayed at full CPU (lab notebook 2026-10-22 (36), error 7: RESEARCH-WRITE-01 and
TEACH-AND-DO-01 at their research step, in `_slot_fillings` and `_phrase_fillings`, and `grammar.chart`'s
`_combine`). Measured on lyric_dev (2026-10-23), the second paragraph of Wikipedia's Photosynthesis lead made
1,560,913 coverings of its runs of words by the forms that could read them and 786 had something standing in every
slot; half its 24 s went to making them. Changed, each keeping what is read:
- a slot's span is asked of the chart as the covering reaches it, where the rest of the form can still cover the
  rest of the words (`derived_reader._coverings`);
- the chart keeps each run of words by a number found once for each place (`_Chart.span`), where a run's pieces were
  looked up afresh at each place a covering reached;
- a construction's key is made once (`Pattern.key`, `Lexical.key`, `Link.key`, `Phrase.key`);
- the grammar makes a combination's pieces only once its chart keeps it (`grammar.Sign.binding`).

Every lesson sentence (`ListeningSource`), every sentence and question of UNDERSTANDS-PROSE-01 and of the half of
UNDERSTANDS-PROSE-02 fixed against (read in parts, as a conversation reads them; the half kept unseen is not read),
and every paragraph of the Photosynthesis lead (read as a page looked up is, `photosynthesis_lead.txt`) is read both
ways in one load, in turns (the first way alternates, so neither has the other's warmed view):

- now: `read_text` as it is;
- before: the same as it was: the coverings made as they were (`coverings_before`, the old walk, each slot asked in
  turn), each run looked up by its pieces (`_span`), each key made when asked, and every combination's pieces made
  by the grammar as it is made (`as_before`);

and compared whole: every utterance and every reading, equal and written alike. Each lesson is also read strictly, as
the learner reads a taught pair (`readings_of`), both ways. Then the listener's choice for each utterance read, the
seconds each way, and that nothing was written to the store. No bar: it measures.

Run (from the Lyric folder; starts no substrate, reads only):
    POSTGRES_DATABASE=lyric_dev POSTGRES_PORT=5433 POSTGRES_USER=stefan PYTHONPATH="$PWD" \
        ./venv_lyric/bin/python3 experiments/SPLITS-01/experiment.py [--prose-only]
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def say(*a):
    print(*a, flush=True)


def coverings_before(form, words, same=str.__eq__, missing=lambda piece: False, shaped=None, fill=None):
    """The coverings as they were made before 2026-10-23: every split of the words between the form's slots, then
    each slot asked in turn and the split thrown away at the first slot nothing stands in."""
    from core.semantics.derived_reader import Piece, Slot
    at_least = [0] * (len(form) + 1)
    for i in range(len(form) - 1, -1, -1):
        element = form[i]
        at_least[i] = at_least[i + 1] + (0 if isinstance(element, Piece) and missing(element) else 1)

    def walk(i, at, spans):
        if i == len(form):
            if at == len(words):
                yield spans
            return
        element = form[i]
        if isinstance(element, Slot):
            for end in range(at + 1, len(words) - at_least[i + 1] + 1):
                yield from walk(i + 1, end, spans + ((at, end),))
            return
        if at < len(words) and (same(words[at], element.text) or (shaped is not None and shaped(at, element.text))):
            yield from walk(i + 1, at + 1, spans)
        if missing(element):
            yield from walk(i + 1, at, spans)

    for spans in walk(0, 0, ()):
        if fill is None:
            yield spans, tuple(() for _ in spans)
            continue
        options = []
        for k, (a, b) in enumerate(spans):
            standing = fill(k, a, b)
            if not standing:
                break
            options.append(standing)
        else:
            yield spans, tuple(options)


@contextlib.contextmanager
def as_before():
    """The reader and the grammar as they were before 2026-10-23, inside the block: the coverings (`coverings_before`),
    each run of words kept by its pieces, each construction's key made each time it is asked, and each combination's
    pieces made as it is made."""
    from core.semantics import derived_reader as dr
    from core.semantics import grammar as gm
    coverings, span, combine = dr._coverings, dr._Chart.span, gm.Grammar._combine
    keys = {cls: cls.__dict__["key"] for cls in (dr.Pattern, dr.Lexical, dr.Link, dr.Phrase)}

    def eager(self, left, right):
        out = combine(self, left, right)
        for sign in out:
            if sign.binding is not None:
                sign.pieces = gm._substitute(left.pieces + right.pieces, sign.binding)
                sign.binding = None
        return out
    dr._coverings = coverings_before
    dr._Chart.span = lambda self, pieces, start, end: dr._span(pieces, start, end)
    gm.Grammar._combine = eager
    for cls, cached in keys.items():
        setattr(cls, "key", property(cached.func))
    try:
        yield
    finally:
        dr._coverings, dr._Chart.span, gm.Grammar._combine = coverings, span, combine
        for cls, cached in keys.items():
            setattr(cls, "key", cached)


def blocks_of(path):
    """A page's text as a looked-up page is read: a block a line, parentheticals and spaces before marks taken out
    (`Conversation._research_phrase`)."""
    out = []
    for block in path.read_text().split("\n"):
        clean = re.sub(r"\([^()]*\)", " ", block)
        clean = re.sub(r"[ \t]+([,.;:!?])", r"\1", clean).strip()
        if clean:
            out.append(clean)
    return out


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(_results() / "run.log", mode="w")])
    from experiments._evidence import RunRecord
    prose_only = "--prose-only" in sys.argv
    EV = RunRecord("SPLITS-01",
                   claim="the reader asking the chart where the words split between a form's slots, and the grammar "
                         "making only the combinations it keeps, read every sentence exactly as before, in less time",
                   hypothesis="every utterance of every lesson, prose sentence and question and looked-up paragraph "
                              "reads to the same readings both ways, and lessons read strictly to the same readings")
    quiet = io.StringIO()
    say("loading memory, the beliefs and the language view (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.learning.teaching_sources import ListeningSource
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.semantics import derived_reader as dr
        from core.semantics.sentence_machine import form_of
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
    before_writes = await written()

    view = dr.live_view()
    EV.check("memory holds what was taught of English", len(view) > 0, f"{len(view):,} constructions and links")
    prose01 = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text())
    prose02 = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-02" / "texts.json").read_text())
    fit = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-02" / "split.json").read_text())["fit"]
    items = [("page", block, None) for block in blocks_of(HERE / "photosynthesis_lead.txt")]
    items += [("prose", sentence, None) for text in prose01
              for sentence in list(text["text"]) + [q["q"] for q in text["questions"]]]
    items += [("prose", sentence, None) for n in fit
              for sentence in list(prose02[n - 1]["text"]) + [q["q"] for q in prose02[n - 1]["questions"]]]
    if not prose_only:
        items += [("lesson", sentence, meaning) for sentence, meaning in ListeningSource().listening_pairs()]
    counts = {kind: sum(1 for k, _, _ in items if k == kind) for kind in ("page", "prose", "lesson")}
    say(f"  {counts['page']} paragraphs of a page, {counts['prose']} prose sentences and questions, "
        f"{counts['lesson']:,} lesson sentences")
    EV.note(f"read: {counts['page']} paragraphs of Wikipedia's Photosynthesis lead, {counts['prose']} sentences and "
            f"questions of UNDERSTANDS-PROSE-01 and of UNDERSTANDS-PROSE-02's half fixed against, "
            f"{counts['lesson']:,} lesson sentences")

    # A WORD THE GRAMMAR READ AS A NAME IS HEARD AS ONE FROM THEN ON (`GrammarView.read`), so a sentence read twice
    # can read otherwise the second time: "When needing to use this stored energy, ..." did, the reader aside
    # (2026-10-23). Each way starts from what the grammar had heard before the sentence.
    heard = agent.grammar_view().grammar.lexicon.heard
    path = _work() / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_sentences.jsonl"
    say(f"  each sentence written to {path}")
    done = []

    def read(sentence, kind, way):
        with way():
            started = time.perf_counter()
            utterances = dr.read_text(sentence, view, parts=kind == "prose")
            return utterances, time.perf_counter() - started

    def strictly(sentence, meaning, way):
        with way():
            started = time.perf_counter()
            readings = dr.readings_of(tuple(p.text for p in form_of(sentence)), meaning, view)
            return readings, time.perf_counter() - started

    # THE FIRST READ IN A LOAD WARMS WHAT THE VIEW WORKS OUT WHEN FIRST ASKED, the structure reader's training among
    # it: on main the first paragraph read now took 127.1 s against 28.1 s before, read second (`20261023T134633Z`).
    # One read of it beforehand, not timed.
    heard_before = dict(heard)
    dr.read_text(items[0][1], view, parts=items[0][0] == "prose")
    heard.clear()
    heard.update(heard_before)
    with path.open("a") as out:
        for at, (kind, sentence, meaning) in enumerate(items):
            ways = [("now", contextlib.nullcontext), ("before", as_before)]
            if at % 2:
                ways.reverse()
            heard_before = dict(heard)
            got = {}
            for name, way in ways:
                heard.clear()
                heard.update(heard_before)
                got[name] = read(sentence, kind, way)
            (now, now_seconds), (old, old_seconds) = got["now"], got["before"]
            row = {"kind": kind, "sentence": sentence,
                   "now": {"seconds": round(now_seconds, 3), "utterances": len(now),
                           "read": sum(1 for u in now if u.readings),
                           "readings": sum(len(u.readings) for u in now)},
                   "before": {"seconds": round(old_seconds, 3), "utterances": len(old),
                              "read": sum(1 for u in old if u.readings),
                              "readings": sum(len(u.readings) for u in old)},
                   "same": now == old, "written alike": repr(now) == repr(old)}
            chosen = []
            for u in now:
                if u.readings:
                    choice = dr.meant(u.readings, view, heard=await dr.listening((u.readings,)))
                    chosen.append(choice.meaning.canonical() if choice is not None else None)
                else:
                    chosen.append(None)
            row["chosen"] = chosen
            if not row["same"]:
                old_chosen = []
                for u in old:
                    if u.readings:
                        choice = dr.meant(u.readings, view, heard=await dr.listening((u.readings,)))
                        old_chosen.append(choice.meaning.canonical() if choice is not None else None)
                    else:
                        old_chosen.append(None)
                row["chosen before"] = old_chosen
            if kind == "lesson":
                row["taught"] = meaning.canonical()
                learned = {name: strictly(sentence, meaning, way) for name, way in ways}
                row["strictly"] = {"same": learned["now"][0] == learned["before"][0],
                                   "written alike": repr(learned["now"][0]) == repr(learned["before"][0]),
                                   "readings": len(learned["now"][0]),
                                   "seconds now": round(learned["now"][1], 3),
                                   "seconds before": round(learned["before"][1], 3)}
            out.write(json.dumps(row) + "\n")
            out.flush()
            done.append(row)
            if kind != "lesson" or at % 200 == 0 or not row["same"]:
                same = "same" if row["same"] and row["written alike"] else "DIFFER"
                say(f"  [{at + 1}/{len(items)}] {kind}: now {now_seconds:.1f}s, before {old_seconds:.1f}s, "
                    f"{row['now']['read']}/{row['now']['utterances']} read: {same}  {sentence[:60]}")
            await asyncio.sleep(0)

    say("")
    for kind in ("page", "prose", "lesson"):
        rows = [row for row in done if row["kind"] == kind]
        if not rows:
            continue
        same = sum(1 for row in rows if row["same"] and row["written alike"])
        differ = [row["sentence"] for row in rows if not (row["same"] and row["written alike"])]
        now_seconds = sum(row["now"]["seconds"] for row in rows)
        old_seconds = sum(row["before"]["seconds"] for row in rows)
        EV.metric(f"{kind}: read to the same utterances and readings both ways", same, unit="count",
                  note=f"of {len(rows):,}" + (f"; differ: {'; '.join(differ[:10])}" if differ else ""))
        EV.metric(f"{kind}: seconds now", round(now_seconds, 1), unit="seconds", note=f"{len(rows):,} read")
        EV.metric(f"{kind}: seconds before", round(old_seconds, 1), unit="seconds", note=f"{len(rows):,} read")
        slowest = max(rows, key=lambda row: row["before"]["seconds"])
        EV.metric(f"{kind}: slowest before, and now", f"{slowest['before']['seconds']}s, {slowest['now']['seconds']}s",
                  note=slowest["sentence"][:120])
        line = (f"  {kind:6}: same {same:,} of {len(rows):,}; now {now_seconds:.0f}s, before {old_seconds:.0f}s; "
                f"slowest before {slowest['before']['seconds']}s, now {slowest['now']['seconds']}s")
        if kind == "lesson":
            strict = sum(1 for row in rows if row["strictly"]["same"] and row["strictly"]["written alike"])
            EV.metric("lessons read strictly, as the learner reads a taught pair, to the same readings both ways",
                      strict, unit="count", note=f"of {len(rows):,}")
            taught = sum(1 for row in rows if row["chosen"] == [row["taught"]])
            EV.metric("lessons read as taught", taught, unit="count", note=f"of {len(rows):,}")
            line += f"; strictly the same {strict:,}; read as taught {taught:,}"
        say(line)
        EV.check(f"{kind}: every one read to the same readings both ways", same == len(rows),
                 f"{same:,} of {len(rows):,}")

    await asyncio.sleep(1)
    after_writes = await written()
    moved = {name: after_writes[name] - before_writes.get(name, 0) for name in after_writes
             if after_writes[name] != before_writes.get(name, 0)}
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
