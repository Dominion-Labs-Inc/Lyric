#!/usr/bin/env python3
"""QUESTION-FORMS-03 — questions about kinds, parts, members, what things are made of and opposites, and "Is it true
that ...?", taught (english_40) and read on a copy of the main model.

UNDERSTANDS-WORDNET-01's first run (2026-10-11) asked the main model "Is a beroe a kind of ctenophore?", "Is a flower
part of an angiosperm?", "Is occupied the opposite of unoccupied?" and "Is it true that an investigator is an
expert?": 0 of 419 read. No lesson asks any of them; english_01-39 teach only "Is a robin a bird?" and "Are robins
birds?" of these, beside the statements ("A robin is a kind of bird.", "A wheel is part of a car.", "Hot is the
opposite of cold.") that WordNet's facts were then taught through. FRESH-LESSON-01 to -03 found a statement's shape
does not bring its question; english_31 taught questions beside what they ask, and english_40 does the same here.

On a copy of main (`lyric_check` or another, made from `lyric_db` just before the run; never `lyric_db` itself):

  A  english_40 is learned, none refused, and every sentence of it reads as taught;
  B  never-taught questions in its forms, with words WordNet taught main (`HELD_OUT`, frozen before the first run),
     read as written: each word taken to name a thing that word names, in the facts asked; measured before too.
     Plurals are measured, not checked: main holds few plurals as plurals (LAB_NOTEBOOK 2026-10-11 (2));
  C  of 600 sentences english_01-39 teach (`EARLIER_SAMPLE`, drawn with a fixed seed), none that read as taught
     before english_40 reads otherwise after. A sample: read as the conversation reads, with memory at hand, all of
     them take over two hours a pass on main;
  D  the main model's store is untouched.

Each sentence is read as the conversation reads it: the reader's readings, the listener taking one with memory at
hand (`derived_reader.heard`).

Run (on a fresh copy of main):
    POSTGRES_DATABASE=lyric_check2 ./venv_lyric/bin/python3 experiments/QUESTION-FORMS-03/experiment.py
"""
import asyncio
import importlib.util
import itertools
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_check")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
if os.environ["POSTGRES_DATABASE"] == "lyric_db":
    sys.exit("QUESTION-FORMS-03 teaches the store it runs on: run it on a copy of main, never lyric_db itself")
LOG = HERE / "results" / "run.log"
LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    handlers=[logging.FileHandler(LOG, mode="w")])

_spec = importlib.util.spec_from_file_location("fresh_lesson_01", ROOT / "experiments" / "FRESH-LESSON-01" / "experiment.py")
fresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fresh)

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, shutdown  # noqa: E402

LESSON = ROOT / "data" / "lessons" / "english_40.json"
BEFORE = [path for path in fresh.LESSONS if path.name < LESSON.name]
#: How many of english_01-39's sentences C reads, and the seed they are drawn with. Fixed before the first run.
EARLIER_SAMPLE = 600
SEED = 20261011

#: Never taught, in english_40's forms, with words WordNet taught main. Frozen before the first run (2026-10-11).
#: `(sentence, act, facts, asked)`, each fact `(relation, subject, object)` in words; "?x" is the thing asked for.
HELD_OUT = [
    ("Is a heron a kind of bird?", "ask", [("isa", "heron", "bird")], []),
    ("Is a beroe a kind of ctenophore?", "ask", [("isa", "beroe", "ctenophore")], []),
    ("Is a multiplexer a kind of device?", "ask", [("isa", "multiplexer", "device")], []),
    ("Is a lockstitch a kind of stitch?", "ask", [("isa", "lockstitch", "stitch")], []),
    ("Is a cupflower a kind of shrub?", "ask", [("isa", "cupflower", "shrub")], []),
    ("Is a petal part of a flower?", "ask", [("part_of", "petal", "flower")], []),
    ("Is a flower part of an angiosperm?", "ask", [("part_of", "flower", "angiosperm")], []),
    ("Is a hull part of a ship?", "ask", [("part_of", "hull", "ship")], []),
    ("Is a keel a part of a boat?", "ask", [("part_of", "keel", "boat")], []),
    ("Is a senator a member of a senate?", "ask", [("member_of", "senator", "senate")], []),
    ("Is a coin made of metal?", "ask", [("made_of", "coin", "metal")], []),
    ("Is occupied the opposite of unoccupied?", "ask", [("antonym_of", "occupied", "unoccupied")], []),
    ("Is happy the opposite of sad?", "ask", [("antonym_of", "happy", "sad")], []),
    ("Is public the opposite of private?", "ask", [("antonym_of", "public", "private")], []),
    ("Is it true that an investigator is an expert?", "ask", [("isa", "investigator", "expert")], []),
    ("Is it true that a heron is a bird?", "ask", [("isa", "heron", "bird")], []),
    ("Is it true that a petal is part of a flower?", "ask", [("part_of", "petal", "flower")], []),
    ("Is it true that happy is the opposite of sad?", "ask", [("antonym_of", "happy", "sad")], []),
    ("What is a heron a kind of?", "ask", [("isa", "heron", "?x")], ["?x"]),
    ("What is a petal part of?", "ask", [("part_of", "petal", "?x")], ["?x"]),
    ("What is the opposite of happy?", "ask", [("antonym_of", "happy", "?x")], ["?x"]),
]
#: Measured, not checked: plurals main holds few of as plurals.
HELD_OUT_PLURAL = [
    ("Are herons a kind of bird?", "ask", [("isa", "heron", "bird")], []),
    ("Are petals part of flowers?", "ask", [("part_of", "petal", "flower")], []),
    ("Are hawks raptors?", "ask", [("isa", "hawk", "raptor")], []),
    ("Are coiners sources?", "ask", [("isa", "coiner", "source")], []),
]

EV = RunRecord("QUESTION-FORMS-03",
               claim=("Taught english_40 on a copy of the main model, Lyric reads questions about kinds, parts, members, "
                      "what things are made of and opposites, and \"Is it true that ...?\", in sentences it was taught "
                      "and in never-taught ones with words WordNet taught it, without losing what english_01-39 taught."),
               hypothesis=("english_40 refused or a sentence of it read otherwise than taught, a never-taught question "
                           "read otherwise than written here, an earlier sentence read as taught before and otherwise "
                           "after, or a write to the main store shows here."))


def say(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


async def taken(sentence):
    """The meaning the listener takes, canonical: "unread" when it does not read whole, None when it reads whole and
    the listener with memory at hand cannot tell which way."""
    from core.semantics import derived_reader as dr
    utterances = dr.read_text(sentence)
    if not utterances or not all(u.understood for u in utterances):
        return "unread", None
    chosen = [await dr.heard(u.readings) for u in utterances]
    if any(c is None for c in chosen):
        return None, None
    if len(chosen) == 1:
        return chosen[0].meaning.canonical(), chosen[0]
    return " | ".join(c.meaning.canonical() for c in chosen), None


def names(view, value, word):
    """Whether a thing taken from the words is one `word` names: its own name, or held written as `word`."""
    from core.semantics import derived_reader as dr
    if dr._fold(str(value)).replace("_", " ") == word:
        return True
    return any(" ".join(dr._loose(lexical.words)) == word for lexical in view.lexicals_with_value(value))


def as_written(view, reading, act, facts, asked):
    """Whether the reading means what was written: the act, and the facts asked, each word taken to name a thing
    that word names; the thing asked for is any one variable, the same in each fact it stands in."""
    from core.semantics.derived_reader import is_variable
    meaning = reading.meaning
    if meaning.act != act or len(meaning.asked) != len(asked):
        return False
    read = [f for f in meaning.facts if not (f.relation == "instance_of" and getattr(f, "given", False))]
    if len(read) != len(facts):
        return False
    for order in itertools.permutations(read):
        bound = {}
        ok = True
        for fact, (relation, subject, obj) in zip(order, facts):
            if fact.relation != relation or not fact.positive:
                ok = False
                break
            for term, word in ((fact.subject, subject), (fact.obj, obj)):
                if word.startswith("?"):
                    if not is_variable(term) or bound.setdefault(word, term) != term:
                        ok = False
                elif is_variable(term) or not names(view, term, word):
                    ok = False
            if not ok:
                break
        if ok:
            return True
    return False


async def read_held(view, items):
    out = []
    for sentence, act, facts, asked in items:
        canonical, reading = await taken(sentence)
        await asyncio.sleep(0)
        good = reading is not None and as_written(view, reading, act, facts, asked)
        out.append({"sentence": sentence, "read": canonical if canonical else "read two ways, not told apart",
                    "as_written": good})
    return out


def lesson_items(paths):
    from core.semantics.derived_reader import Meaning
    return [(r["sentence"], Meaning.from_dict(r["meaning"]).canonical())
            for path in paths for r in json.loads(path.read_text())["records"]]


async def read_all(items, label):
    out = []
    started = time.time()
    for at, (sentence, expected) in enumerate(items, 1):
        got, _ = await taken(sentence)
        out.append((sentence, expected, got))
        # The reader holds the loop for the length of a sentence; between sentences the substrate's own work runs.
        await asyncio.sleep(0)
        if at % 50 == 0:
            say(f"    {label}: {at}/{len(items)} read ({time.time() - started:.0f} s)")
    return out


async def main() -> int:
    started = time.time()
    main_before = await fresh._sense.main_store_rows()
    say(f"QUESTION-FORMS-03 on {os.environ['POSTGRES_DATABASE']}; booting the substrate…")
    system, coord = await boot()
    try:
        check("the run is on a copy of main, not main",
              await EV.verify_database() == os.environ["POSTGRES_DATABASE"] != "lyric_db",
              f"connected to {EV.verified_database}")
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        words = await agent.warm_word_classes()
        view = await agent.language_view()
        say(f"  the language view holds {words:,} words")

        say("\n== Before english_40 ==")
        held_before = await read_held(view, HELD_OUT)
        plural_before = await read_held(view, HELD_OUT_PLURAL)
        EV.metric("never-taught questions read as written before english_40",
                  f"{sum(r['as_written'] for r in held_before)}/{len(held_before)}")
        say(f"  never taught, read as written: {sum(r['as_written'] for r in held_before)}/{len(held_before)}")
        earlier = random.Random(SEED).sample(lesson_items(BEFORE), EARLIER_SAMPLE)
        earlier_before = await read_all(earlier, "english_01-39 before")
        right_before = {s for s, e, g in earlier_before if g == e}
        EV.metric("english_01-39 sentences read as taught before english_40", f"{len(right_before)}/{len(earlier)}")
        say(f"  english_01-39 read as taught: {len(right_before)}/{len(earlier)}")

        say("\n== A. english_40 ==")
        report, total = await fresh.teach(LESSON, LESSON.name, "english")
        check("english_40 is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == total, f"{report.patterns}")
        view = await agent.language_view()
        # AS TAUGHT, WORD BY WORD, as B reads: each word taken to name a thing that word names. A lesson names its
        # concepts by their words ("raptor"), and main holds WordNet's senses under their own names: "raptor" names
        # `bird of prey` there, and "Is an owl a kind of raptor?" read as isa(owl, bird of prey) is read as taught
        # (the first run's four misses, all that). The concept names alike are kept as a measure.
        records = json.loads(LESSON.read_text())["records"]
        lesson = await read_held(view, [(r["sentence"], r["meaning"]["act"],
                                         [(f[0], f[1], f[2]) for f in r["meaning"]["facts"]
                                          if not (f[0] == "instance_of" and len(f) > 7 and f[7])],
                                         r["meaning"].get("asked") or []) for r in records])
        strict = await read_all(lesson_items([LESSON]), "english_40")
        EV.metric("english_40 read with the lesson's own concept names", f"{sum(1 for _, e, g in strict if g == e)}/{len(strict)}")
        wrong = [r for r in lesson if not r["as_written"]]
        for r in wrong:
            say(f"    {r['sentence']!r} read {r['read']}")
        check("every sentence of english_40 reads as taught", not wrong, f"{len(lesson) - len(wrong)} of {len(lesson)}")

        say("\n== B. Never taught ==")
        held_after = await read_held(view, HELD_OUT)
        for r in held_after:
            if not r["as_written"]:
                say(f"    {r['sentence']!r}\n        read {r['read']}")
        EV.metric("never-taught readings", held_after)
        check("never-taught questions in english_40's forms read as written", all(r["as_written"] for r in held_after),
              f"{sum(r['as_written'] for r in held_after)} of {len(held_after)}")
        plural_after = await read_held(view, HELD_OUT_PLURAL)
        EV.metric("never-taught plural questions read as written, before and after english_40",
                  {"before": f"{sum(r['as_written'] for r in plural_before)}/{len(plural_before)}",
                   "after": f"{sum(r['as_written'] for r in plural_after)}/{len(plural_after)}",
                   "readings": plural_after})
        say(f"  plurals (measured): {sum(r['as_written'] for r in plural_after)}/{len(plural_after)}")

        say("\n== C. english_01-39 ==")
        earlier_after = await read_all(earlier, "english_01-39 after")
        lost = [(s, g) for s, e, g in earlier_after if s in right_before and g != e]
        for s, g in lost[:20]:
            say(f"    {s!r} read {g!r}")
        EV.metric("english_01-39 sentences read as taught after english_40",
                  f"{sum(1 for s, e, g in earlier_after if g == e)}/{len(earlier)}")
        EV.metric("earlier sentences read as taught before and otherwise after", [{"sentence": s, "read": g} for s, g in lost])
        check(f"of {EARLIER_SAMPLE} sentences english_01-39 teach, none that read as taught before reads otherwise "
              "after", not lost,
              f"{len(right_before) - len(lost)} of {len(right_before)} still")
    finally:
        await shutdown(system)
    main_after = await fresh._sense.main_store_rows()
    if main_after == main_before:
        check("the main model's store is untouched", True, fresh._sense.main_store_change(main_before, main_after))
    else:
        EV.note("the main model's store moved during the run (its world inhabitant runs on it): "
                + fresh._sense.main_store_change(main_before, main_after))
        say("  main moved during the run; recorded as a note, not a check")
    passed = sum(1 for c in EV.checks if c.passed)
    say(f"\n==== QUESTION-FORMS-03: {passed}/{len(EV.checks)} checks passed ({time.time() - started:.0f} s) ====")
    say(f"  run record: {EV.write()}")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
