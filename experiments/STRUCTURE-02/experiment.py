"""STRUCTURE-02: how many of the lessons' meaning roles each fall on one phrase of the structure read.

Each sentence of the English lessons is read as the learner reads a taught pair (`readings_of`, strictly, to the
meaning it was taught with). Its frame's slots are where it says its meaning's things: the words each slot holds are
found as the reader finds them (`_chunkings`, `_slot_fillings`, `_composed_meaning`), and the same words are read for
how they go together (`StructureView`, the treebank taught to the store). Two tests, each slot:

- ONE PHRASE: exactly one of its words depends on a word outside them; they stand together. A slot of one word
  always does.
- ATTACHED AS THE MEANING SAYS: going up from that word through what each word depends on, the first other slot met,
  if any, is one the meaning says something of together with it, in one fact. "Tom kicked the ball in the house."
  with "house" under "ball" is not, when the house is where the kicking was; "The ball near the box" is.

The share of sentences whose every slot passes both is the ceiling a phrase layer gives the reader
(`docs/research/READING_PROSE_AT_SCALE.md` §5): frames learned over phrases can read those sentences as they were
taught. Only the slots are tested: what a frame writes itself is not. No bar: it measures. Then it checks nothing
was written.

Run (from the Lyric folder; starts no substrate, reads only):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-02/experiment.py
"""
import asyncio
import contextlib
import io
import itertools
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def say(*a):
    print(*a, flush=True)


def outside(span, heads):
    """The words of `span` (start, end) that depend on a word outside it, or on the root; `heads` 1-based."""
    start, end = span
    return [i for i in range(start, end) if not start <= heads[i] - 1 < end]


def slot_spans(words, meaning, frame, view):
    """Where each of `frame`'s slots stands in `words` when the frame reads them to `meaning` strictly, as
    `_analyses` reads them; None when no way of covering them does."""
    from core.semantics import derived_reader as dr
    from core.semantics.sentence_machine import Piece
    pieces = tuple(Piece(word, True) for word in words)
    target = meaning.canonical()
    shaped, _ = dr._written_shapes(view, words)
    chart = dr._Chart()
    for spans in dr._chunkings(frame.form, words, str.__eq__, lambda piece: False, shaped):
        options = []
        for slot, (start, end) in zip(frame.slots, spans):
            fitting = dr._slot_fillings(view, frame, slot, pieces, start, end, chart, extend=False, loose=False)
            if not fitting:
                break
            options.append(fitting)
        else:
            for combo in itertools.product(*options):
                composed = dr._composed_meaning(frame.meaning, dict(zip(frame.slots, combo)))
                if composed is not None and composed.canonical() == target:
                    return spans
    return None


def tied(frame, one, other):
    """Whether the frame's meaning says something of what slot `one` stands for and what slot `other` stands for
    together, in one fact: the thing a slot names the kind of (`instance_of(?t, ?slot1)`), or the slot itself."""
    facts = frame.meaning.facts

    def stands_for(slot):
        return {slot} | {f.subject for f in facts if f.relation == "instance_of" and f.obj == slot}
    ones, others = stands_for(one), stands_for(other)
    return any((f.subject in ones and f.obj in others) or (f.subject in others and f.obj in ones) for f in facts)


def attached_to(at, spans, heads):
    """The slot whose words are the first met going up from word `at` (0-based) through what each word depends on;
    None when only the frame's own words, then the root, are met."""
    head = heads[at]
    while head != 0:
        for slot, (start, end) in spans.items():
            if start <= head - 1 < end:
                return slot
        head = heads[head - 1]
    return None


def roles_on_phrases(pairs, view, structure):
    """For each (sentence, meaning): read strictly as taught, its frame's slots found, and each slot's words checked
    against the structure read. A slot's words are ONE PHRASE when exactly one of them depends on a word outside
    them (a slot of one word always is); the phrase is ATTACHED AS THE MEANING SAYS when the first other slot met
    going up from it, if any, is one the meaning ties it to (`tied`): "in May" under "engineers" is not, when May is
    when the hiring was. Returns the counts and every sentence with a slot that is either not."""
    from core.semantics import derived_reader as dr
    from core.semantics.sentence_machine import form_of
    from core.semantics.structure import words_of
    counts = Counter()
    by_role, by_relation = Counter(), Counter()
    missed = []
    for sentence, meaning in pairs:
        counts["sentences"] += 1
        pieces = form_of(sentence)
        words = tuple(p.text for p in pieces)
        readings = dr.readings_of(words, meaning, view)
        if not readings:
            counts["not read as taught"] += 1
            continue
        frame = readings[0].constructions[0]
        if not isinstance(frame, dr.Pattern) or not frame.slots:
            counts["read whole (no slots)"] += 1
            continue
        spans = slot_spans(words, meaning, frame, view)
        if spans is None:
            counts["slots not found"] += 1
            continue
        counts["read through a frame with slots"] += 1
        read = structure.read(words_of(pieces))
        placed = dict(zip(frame.slots, spans))
        every_one = every_attached = True
        slots = []
        for slot, span in placed.items():
            role = dr._role_of_slot(frame, slot)
            heads_out = outside(span, read.heads)
            one = len(heads_out) == 1
            under = attached_to(heads_out[0], {s: p for s, p in placed.items() if s != slot}, read.heads) \
                if one else None
            attached = one and (under is None or tied(frame, slot, under))
            counts["slots"] += 1
            counts["slots on one phrase"] += one
            counts["slots on one phrase, attached as the meaning says"] += attached
            by_role[(role, "one phrase", one)] += 1
            by_role[(role, "attached", attached)] += 1
            if one:
                by_relation[(role, read.relations[heads_out[0]])] += 1
            every_one, every_attached = every_one and one, every_attached and attached
            slots.append({"slot": slot, "role": role, "words": " ".join(words[span[0]:span[1]]), "one": one,
                          "under": under, "attached": attached,
                          "depend outside": [f"{words[i]} {read.relations[i]}" for i in heads_out]})
        counts["every slot on one phrase"] += every_one
        counts["every slot on one phrase, attached as the meaning says"] += every_attached
        if not every_attached:
            missed.append({"sentence": sentence, "frame": frame.surface, "facts": [f.render() for f in
                                                                                   frame.meaning.facts],
                           "slots": slots, "words": list(read.words), "classes": list(read.classes),
                           "heads": list(read.heads), "relations": list(read.relations)})
    return counts, by_role, by_relation, missed


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(_results() / "run.log", mode="w")])
    from experiments._evidence import RunRecord
    EV = RunRecord("STRUCTURE-02",
                   claim="the meaning roles of the sentences the main model was taught fall on phrases of the "
                         "structure it learned from a treebank",
                   hypothesis="read strictly as taught, each slot of a lesson sentence's frame holds words that "
                              "stand together as one phrase of the structure read (no bar: the share is measured)")
    quiet = io.StringIO()
    say("loading memory and its views (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.learning.teaching_sources import ListeningSource
        from core.semantics.derived_reader import live_view
        agent = await get_memory_agent()
        await agent.initialize()
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

    view, structure = live_view(), agent.structure_view()
    EV.check("memory holds what was taught of English", len(view) > 0, f"{len(view):,} constructions and links")
    EV.check("memory holds the treebank's sentences as analysed", len(structure) > 0,
             f"{len(structure):,} sentences held")
    source = ListeningSource()
    pairs = list(source.listening_pairs())
    EV.check("the lessons are on disk", len(pairs) > 0, f"{len(source.paths)} lessons, {len(pairs):,} sentences")
    say(f"  {len(pairs):,} lesson sentences; {len(structure):,} analysed sentences held")

    started = time.perf_counter()
    counts, by_role, by_relation, missed = roles_on_phrases(pairs, view, structure)
    say(f"  read in {time.perf_counter() - started:.0f}s")
    framed = counts["read through a frame with slots"]
    for name in ("sentences", "not read as taught", "read whole (no slots)", "slots not found",
                 "read through a frame with slots", "slots", "slots on one phrase",
                 "slots on one phrase, attached as the meaning says", "every slot on one phrase",
                 "every slot on one phrase, attached as the meaning says"):
        EV.metric(name, counts[name], unit="count")
        say(f"    {name:55} {counts[name]:,}")
    if framed:
        for test in ("on one phrase", "on one phrase, attached as the meaning says"):
            share = counts[f"every slot {test}"] / framed
            EV.metric(f"sentences with every slot {test}", round(share, 4), unit="fraction",
                      note=f"of the {framed:,} sentences read through a frame with slots")
            EV.metric(f"slots {test} (share)", round(counts[f"slots {test}"] / counts["slots"], 4), unit="fraction")
            say(f"    sentences with every slot {test}: {share:.1%}")
    for role in sorted({role for role, _, _ in by_role}):
        for test in ("one phrase", "attached"):
            on, off = by_role[(role, test, True)], by_role[(role, test, False)]
            EV.metric(f"{role} slots: {test}", round(on / (on + off), 4), unit="fraction", note=f"of {on + off:,}")
            say(f"    {role:10} {test:11} {on / (on + off):.1%} of {on + off:,}")

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (_results() / f"{stamp}_missed.json").write_text(json.dumps(missed, indent=1))
    (_results() / f"{stamp}_relations.json").write_text(json.dumps(
        [{"role": role, "relation": relation, "slots": n} for (role, relation), n in by_relation.most_common()],
        indent=1))

    await asyncio.sleep(1)
    after = await written()
    moved = {name: after[name] - before.get(name, 0) for name in after if after[name] != before.get(name, 0)}
    EV.check("reading wrote nothing to the store", not moved,
             "; ".join(f"{name} +{n}" for name, n in sorted(moved.items())) or "no table written to")
    path = EV.write()
    say(f"\n  run record: {path}")
    return 0 if EV.failed == 0 else 1


def _results() -> Path:
    (HERE / "results").mkdir(exist_ok=True)
    return HERE / "results"


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
