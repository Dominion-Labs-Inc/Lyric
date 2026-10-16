#!/usr/bin/env python3
"""SENSE-COVERAGE-01 — every sense of a word reaches the listener, wherever the word stands.

The reader reports every meaning a sentence can have and the listener (`derived_reader.meant`) takes one. A sense the
reader never reports cannot be taken, however much memory knows of it. This reads, for every word the store holds
with two or more senses, a sentence through each frame the word was taught in (any of its senses), the frame's other
places filled with words taught there, and checks which of the word's senses reach the listener:

  A  HOME     each sense is reported in the frames its own word was taught in
  B  SHARED   in the frames its other senses were taught in, each sense not reported is counted, by why: the
              reading of that sense read loosely or took new names (another reading of the words, set aside as such),
              another reading of the whole sentence was taken (a sentence taught with its meaning), or no reading of
              it at all (its concept cannot stand there); none may be left out for how well it fits there
  C  STORE    the store is the sandbox, read only

Runs on the SANDBOX (`lyric_dev`) as it stands: the database, the beliefs and the memory agent; the substrate is not
started; nothing is written.

Run: ./venv_lyric/bin/python3 experiments/SENSE-COVERAGE-01/experiment.py
"""
from __future__ import annotations

import asyncio
import collections
import os
import sys
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "SENSE-COVERAGE-01",
    claim=("Every sense of a word reaches the listener: the reader reports each sense where the word stands, and "
           "how well a sense fits there is the listener's evidence, never a reason to leave it out."),
    hypothesis=("A sense not reported in a frame its own word was taught in, or one left out of a frame where its "
                "word stands for any reason but reading the words otherwise, would each show here."))
TRANSCRIPT = []
PARTS = ("read loosely", "new names", "links proposed", "misfits", "apart")


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the store is the sandbox", where["d"] == "lyric_dev", f"connected to {where['d']}")
    if where["d"] != "lyric_dev":
        return 1
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    await get_uncertainty_system().load_from_db()
    from core.memory import get_memory_agent
    view = await (await get_memory_agent()).language_view()
    from core.semantics import derived_reader as dr

    # The word forms held with two or more senses, and each sense's own places.
    senses = collections.defaultdict(dict)
    for lexical in view.lexicals():
        words = dr._loose(lexical.words)
        if len(words) == 1 and words[0].isalpha() and view.counts(lexical):
            senses[words[0]].setdefault(lexical.value, lexical)
    many = {w: s for w, s in senses.items() if len(s) >= 2}
    say_line(f"== Words held with two or more senses: {len(many)} ==")

    def sentence_in(pattern, slot, lexical):
        fillers = {}
        for other in pattern.slots:
            if other == slot:
                fillers[other] = lexical
                continue
            # A word written out in full: a filler that is itself a frame with places ("?slot0 on the ?slot1")
            # says no sentence alone.
            taught = [f for f in view.fillers(pattern.key, other)
                      if view.counts(f) and all(isinstance(e, dr.Piece) for e in f.form)
                      and dr._loose(f.words) != dr._loose(lexical.words)]
            if not taught:
                return None
            fillers[other] = taught[0]
        return dr.surface_of(dr._rendered(pattern, fillers, view))

    frames = {p.key for p in view.item_based()}
    home_checked, home_missed, home_examples = 0, 0, []
    shared_checked, shared_missed = 0, collections.Counter()
    shared_examples = collections.defaultdict(list)
    for word, by_value in sorted(many.items()):
        places = {}
        for value, lexical in by_value.items():
            for pattern_key, slot in view._links_to.get(lexical.key, ()):
                pattern = view.get(pattern_key)
                if isinstance(pattern, dr.Pattern) and pattern_key in frames:
                    places.setdefault((pattern_key, slot), set()).add(value)
        for (pattern_key, slot), own in sorted(places.items()):
            pattern = view.get(pattern_key)
            # The word as English writes it inside a sentence: without a capital where it has a construction so
            # written ("The milk is black.", not "Black", which reads as a name).
            written = next((lx for lx in by_value.values() if lx.words[0][:1].islower()), next(iter(by_value.values())))
            sentence = sentence_in(pattern, slot, written)
            if not sentence:
                continue
            utterances = dr.read_text(sentence, view)
            # Reported: a reading takes the word as the thing through a word of it, or names the thing through a
            # frame's own words ("A ?slot0 is an amphibian."): a thing no other word of the reading names.
            offered = {c.value for u in utterances for r in u.readings for c in r.constructions
                       if isinstance(c, dr.Lexical) and dr._loose(c.words) == (word,)}
            for u in utterances:
                for r in u.readings:
                    named = {c.value for c in r.constructions if isinstance(c, dr.Lexical)}
                    offered |= {t for f in r.meaning.facts for t in f.terms() if t not in named} & set(by_value)
            for value in by_value:
                home = value in own
                if home:
                    home_checked += 1
                else:
                    shared_checked += 1
                if value in offered:
                    continue
                if home:
                    home_missed += 1
                    if len(home_examples) < 12:
                        home_examples.append((word, value, sentence))
                    continue
                pieces = tuple(dr.form_of(sentence))
                found = dr._analyses(tuple(p.text for p in pieces), view, pieces=pieces, extend=True) or \
                    dr._analyses(tuple(p.text for p in pieces), view, pieces=pieces, extend=True, loose=True)
                least = found[0].supposed if found else None
                worded = {dr._worded(r) for r in found if r.supposed == least}
                own_readings = [r for r in found
                                if any(isinstance(c, dr.Lexical) and c.value == value
                                       and dr._loose(c.words) == (word,) for c in r.constructions)]
                if not own_readings:
                    why = "no reading of it"
                elif all(any(f.subject == f.obj for f in r.meaning.facts) for r in own_readings):
                    # Two of the sentence's words would name the one thing ("A tour is a turn.", both `go`): the
                    # reading says a thing is itself, and is no other sense of the words.
                    why = "its words would name one thing twice"
                elif not any(dr._worded(r) in worded for r in own_readings):
                    why = "another reading of the sentence was taken"
                else:
                    best = min(r.supposed for r in own_readings)
                    why = ", ".join(PARTS[i] for i in range(len(PARTS)) if best[i] != least[i]) or "reported nowhere"
                shared_missed[why] += 1
                if len(shared_examples[why]) < 6:
                    shared_examples[why].append((word, value, sentence))

    say_line("\n== A. Each sense, in the frames its own word was taught in ==")
    for word, value, sentence in home_examples:
        say_line(f"    MISSED {word!r} as {value!r} in {sentence!r}")
    check("every sense is reported where its own word was taught", home_missed == 0,
          f"{home_checked - home_missed}/{home_checked}")
    EV.metric("senses reported in their own frames", f"{home_checked - home_missed}/{home_checked}")

    say_line("\n== B. Each sense, in the frames its other senses were taught in ==")
    for why, n in shared_missed.most_common():
        say_line(f"    not reported, {why}: {n}")
        for word, value, sentence in shared_examples[why]:
            say_line(f"      {word!r} as {value!r} in {sentence!r}")
    by_structure = sum(n for why, n in shared_missed.items()
                       if why not in ("no reading of it", "another reading of the sentence was taken",
                                      "its words would name one thing twice")
                       and not why.startswith(("read loosely", "new names")))
    check("no sense is left out for how well it fits where its word stands", by_structure == 0,
          f"{by_structure} left out so; {sum(shared_missed.values())} not reported of {shared_checked}")
    EV.metric("senses reported in their siblings' frames",
              f"{shared_checked - sum(shared_missed.values())}/{shared_checked}")
    for why, n in shared_missed.items():
        EV.metric(f"not reported in a sibling's frame: {why}", n)

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SENSE-COVERAGE-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
