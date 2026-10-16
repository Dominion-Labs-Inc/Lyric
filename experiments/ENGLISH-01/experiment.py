#!/usr/bin/env python3
"""ENGLISH-01 — Phase 1 of the English curriculum, built and measured on the sandbox: the writing system's marks,
english_32-39.

`docs/research/ENGLISH_CURRICULUM.md` Phase 1 teaches the writing system, each mark in its own lesson, the marks web
English uses most first (the survey of UD English EWT: `survey.py`): the comma (english_32), the apostrophe (33), the
colon and the semicolon (34), a title with a period (35), parentheses, dashes and "!" (36), money, measures and dates
(37), times of day, the ellipsis and the slash (38), and quotation marks (39), what someone said held as said. Each
meaning is one an earlier lesson teaches without the mark.

On the emptied sandbox: english_01-31, then each Phase 1 lesson in turn, then:

  A  each is learned, none refused, and every sentence of it reads as taught;
  B  sentences with its mark in the same uses, words the lessons have, never taught (`HELD_OUT`, written and frozen
     before the lesson's first run), read as written; measured before the lesson too;
  C  every sentence english_01-31 teach still reads as taught;
  D  the main model is untouched, checked where main was still (when it is taught alongside, its move is noted).

Measuring the comma on EWT's own held-out sentences waits for Phase 2: EWT's sentences are made of words no lesson
teaches yet.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/ENGLISH-01/experiment.py
"""
import asyncio
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("fresh_lesson_01", ROOT / "experiments" / "FRESH-LESSON-01" / "experiment.py")
fresh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fresh)

#: The expected meanings below were written before "the X" was written as a known thing (docs/TEACHING.md §12d,
#: 2026-10-06); they are read as the lessons now write them, through the rule the lessons were rewritten by.
_known_spec = importlib.util.spec_from_file_location("known_the", ROOT / "scripts" / "known_the.py")
known_the = importlib.util.module_from_spec(_known_spec)
_known_spec.loader.exec_module(known_the)

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, shutdown  # noqa: E402

tell, ask = fresh.tell, fresh.ask
FIRST = ROOT / "data" / "lessons" / "english_32.json"
BEFORE = [path for path in fresh.LESSONS if path.name < FIRST.name]


def past(v, kind, doer):
    return [("instance_of", v, kind, True), ("done_by", v, doer, True), ("precedes", v, "?now", True)]


def now(v, kind, doer):
    return [("instance_of", v, kind, True), ("done_by", v, doer, True)]


def denied(kind, doer, *when):
    return [("instance_of", "?v0", kind, True), ("done_by", "?v0", doer, True)] \
        + [(rel, "?v0", "?now", True) for rel in when] + [("has_property", "?v0", "false", True)]


#: Never taught: the comma in english_32's uses, with words the lessons have. Written before the first run.
HELD_OUT_32 = [
    ("Ducks, robins and owls are birds.", tell(*[("isa", t, "bird", True) for t in ("duck", "robin", "owl")])),
    ("Horses, cows, and dogs are mammals.", tell(*[("isa", t, "mammal", True) for t in ("horse", "cow", "dog")])),
    ("Milk, paper and snow are white.", tell(*[("has_property", t, "white", True) for t in ("milk", "paper", "snow")])),
    ("Rex has a cup, a book and a pen.", tell(*[("owns", "rex", t, True) for t in ("cup", "book", "pen")])),
    ("Anna has a dog, a bird, and a cat.", tell(*[("owns", "anna", t, True) for t in ("dog", "bird", "cat")])),
    ("The cat is small, black and fast.", tell(*[("has_property", "cat", p, True) for p in ("small", "black", "fast")])),
    ("Is the box red, green or blue?",
     ask([("has_property", "box", p, True, False, True) for p in ("red", "green", "blue")])),
    ("The door is closed, and the room is cold.",
     tell(("has_property", "door", "closed", True), ("has_property", "room", "cold", True))),
    ("The cat is small, but the dog is big.",
     tell(("has_property", "cat", "small", True), ("has_property", "dog", "big", True))),
    ("The cat ran, and the dog barked.", tell(*past("?v0", "run", "cat"), *past("?v1", "bark", "dog"))),
    ("The fish swam, the bird flew and the dog ran.",
     tell(*past("?v0", "swim", "fish"), *past("?v1", "fly", "bird"), *past("?v2", "run", "dog"))),
    ("At night, the dog barked.", tell(*past("?v0", "bark", "dog"), ("during", "?v0", "night", True))),
    ("In the morning, the bird flew.", tell(*past("?v0", "fly", "bird"), ("during", "?v0", "morning", True))),
    ("When the bird flies, the cat runs.",
     tell(*now("?v0", "run", "cat"), *now("?v1", "fly", "bird"), ("during", "?v0", "?v1", True))),
    ("Because the bird flies, the cat runs.",
     tell(*now("?v0", "run", "cat"), *now("?v1", "fly", "bird"), ("causes", "?v1", "?v0", True))),
    ("Anna, the teacher, is tall.", tell(("isa", "anna", "teacher", True), ("has_property", "anna", "tall", True))),
    ("Tom, the boy, is kind.", tell(("isa", "tom", "boy", True), ("has_property", "tom", "kind", True))),
    ("Rex, my cat, is small.",
     tell(("isa", "rex", "cat", True), ("owned_by", "rex", "?speaker", True), ("has_property", "rex", "small", True))),
]

#: Never taught: the apostrophe in english_33's uses, with words the lessons have. Written before english_33's first run.
HELD_OUT_33 = [
    ("Dogs aren't fish.", tell(("isa", "dog", "fish", False))),
    ("The box isn't hot.", tell(("has_property", "box", "hot", False))),
    ("Cats can't swim.", tell(("capable_of", "cat", "swim", False))),
    ("The bird doesn't bark.", tell(*denied("bark", "bird"))),
    ("Horses don't swim.", tell(*denied("swim", "horse"))),
    ("The fish didn't swim.", tell(*denied("swim", "fish", "precedes"))),
    ("The cat won't swim.", tell(*denied("swim", "cat", "follows"))),
    ("It's cold.", tell(("has_property", "?previous", "cold", True))),
    ("He's tall.", tell(("has_property", "?previous", "tall", True))),
    ("That's my cup.", tell(("instance_of", "?shown", "cup", True), ("owned_by", "?shown", "?speaker", True))),
    ("You're small.", tell(("has_property", "?listener", "small", True))),
    ("We're big.", tell(("has_member", "?v0", "?speaker", True), ("has_property", "?v0", "big", True))),
    ("I'll swim.", tell(("instance_of", "?v0", "swim", True), ("done_by", "?v0", "?speaker", True),
                        ("follows", "?v0", "?now", True))),
    ("You've run.", tell(("instance_of", "?v0", "run", True), ("done_by", "?v0", "?listener", True),
                         ("precedes", "?v0", "?now", True))),
    ("Anna's hat is blue.", tell(("instance_of", "?x", "hat", True), ("owned_by", "?x", "anna", True),
                                 ("has_property", "?x", "blue", True))),
    ("The cats' ball is red.", tell(("instance_of", "?x", "ball", True), ("owned_by", "?x", "cat", True),
                                    ("has_property", "?x", "red", True))),
]

def group(who, kind, *members):
    return [("owns", who, "?v0", True), ("instance_of", "?v0", kind, True), ("has_count", "?v0", str(len(members)), True)] \
        + [("has_member", "?v0", m, True) for m in members]


#: Never taught: the colon and the semicolon in english_34's uses, with words the lessons have. Written before
#: english_34's first run.
HELD_OUT_34 = [
    ("Rex has three animals: a dog, a bird and a cat.", tell(*group("rex", "animal", "dog", "bird", "cat"))),
    ("Anna has two toys: a hat and a ball.", tell(*group("anna", "toy", "hat", "ball"))),
    ("The cup is hot; the milk is cold.", tell(("has_property", "cup", "hot", True), ("has_property", "milk", "cold", True))),
    ("Rex is big; Anna is small.", tell(("has_property", "rex", "big", True), ("has_property", "anna", "small", True))),
    ("The fish swam; the bird flew.", tell(*past("?v0", "swim", "fish"), *past("?v1", "fly", "bird"))),
    ("Tom ran; Rex walked.", tell(*past("?v0", "run", "tom"), *past("?v1", "walk", "rex"))),
    ("Dogs can swim; birds can fly.", tell(("capable_of", "dog", "swim", True), ("capable_of", "bird", "fly", True))),
    ("A whale is a mammal; an owl is a bird.", tell(("isa", "whale", "mammal", True), ("isa", "owl", "bird", True))),
]

def titled(name, kind, said):
    return tell(("isa", name, kind, True), said)


#: Never taught: a title with a period before a name, in pairings english_35 does not make. Written before english_35's
#: first run.
HELD_OUT_35 = [
    ("Dr. Park is tall.", titled("park", "doctor", ("has_property", "park", "tall", True))),
    ("Mr. Kim is kind.", titled("kim", "man", ("has_property", "kim", "kind", True))),
    ("Mrs. Kim is here.", titled("kim", "woman", ("located_at", "kim", "?here", True))),
    ("Ms. Jones has a dog.", titled("jones", "woman", ("owns", "jones", "dog", True))),
    ("Dr. Smith has a cat.", titled("smith", "doctor", ("owns", "smith", "cat", True))),
    ("Mr. Park is here.", titled("park", "man", ("located_at", "park", "?here", True))),
    ("Mrs. Lee is tall.", titled("lee", "woman", ("has_property", "lee", "tall", True))),
    ("Ms. Smith is kind.", titled("smith", "woman", ("has_property", "smith", "kind", True))),
]

#: Never taught: parentheses and dashes around a second name, and "!" after a statement, in pairings english_36 does
#: not make. Written before english_36's first run.
HELD_OUT_36 = [
    ("Anna (the teacher) is small.", tell(("isa", "anna", "teacher", True), ("has_property", "anna", "small", True))),
    ("Rex (the cat) is kind.", tell(("isa", "rex", "cat", True), ("has_property", "rex", "kind", True))),
    ("Tom (my dog) is brown.",
     tell(("isa", "tom", "dog", True), ("owned_by", "tom", "?speaker", True), ("has_property", "tom", "brown", True))),
    ("Tom - the boy - is tall.", tell(("isa", "tom", "boy", True), ("has_property", "tom", "tall", True))),
    ("Anna - the teacher - is kind.", tell(("isa", "anna", "teacher", True), ("has_property", "anna", "kind", True))),
    ("The cat is small!", tell(("has_property", "cat", "small", True))),
    ("Rex is here!", tell(("located_at", "rex", "?here", True))),
    ("Tom has a dog!", tell(("owns", "tom", "dog", True))),
    ("The fish swam!", tell(*past("?v0", "swim", "fish"))),
]

def dollars(who, n):
    return tell(("owns", who, "?v0", True), ("instance_of", "?v0", "dollar", True), ("has_count", "?v0", n, True))


def meters(thing, how, n):
    return tell(("has_degree", thing, "?v0", True), ("instance_of", "?v0", how, True), ("has_measure", "?v0", "?v1", True),
                ("instance_of", "?v1", "meter", True), ("has_count", "?v1", n, True))


#: Never taught: money, measures written short, and dates, in pairings english_37 does not make. Written before
#: english_37's first run.
HELD_OUT_37 = [
    ("Anna has $7.", dollars("anna", "7")),
    ("Tom has $4.25.", dollars("tom", "4.25")),
    ("Rex has three dollars.", dollars("rex", "3")),
    ("The rope is 5 m long.", meters("rope", "long", "5")),
    ("The table is 1 m wide.", meters("table", "wide", "1")),
    ("Rex walked on May 1.", tell(*past("?v0", "walk", "rex"), ("during", "?v0", "--05-01", True))),
    ("The bird flew on October 5.", tell(*past("?v0", "fly", "bird"), ("during", "?v0", "--10-05", True))),
    ("Tom swam on June 10.", tell(*past("?v0", "swim", "tom"), ("during", "?v0", "--06-10", True))),
    # Added after the sixth run: the dates above are all dates english_37 teaches, so they showed the taught dates
    # read, not dates read by their writing. These are dates no lesson has.
    ("Tom walked on October 6.", tell(*past("?v0", "walk", "tom"), ("during", "?v0", "--10-06", True))),
    ("The dog barked on December 25.", tell(*past("?v0", "bark", "dog"), ("during", "?v0", "--12-25", True))),
    ("Rex ran on May 2.", tell(*past("?v0", "run", "rex"), ("during", "?v0", "--05-02", True))),
    ("Anna swam on March 3.", tell(*past("?v0", "swim", "anna"), ("during", "?v0", "--03-03", True))),
]

#: Never taught: times of day, the ellipsis and the slash, in pairings english_38 does not make. Written before
#: english_38's first run.
HELD_OUT_38 = [
    ("Anna swam at 8 p.m.", tell(*past("?v0", "swim", "anna"), ("during", "?v0", "8:00 p.m.", True))),
    ("The cat ran at 6:45 a.m.", tell(*past("?v0", "run", "cat"), ("during", "?v0", "6:45 a.m.", True))),
    ("Rex walked at 11:20.", tell(*past("?v0", "walk", "rex"), ("during", "?v0", "11:20", True))),
    ("The cat ran...", tell(*past("?v0", "run", "cat"))),
    ("Rex is small...", tell(("has_property", "rex", "small", True))),
    ("Is the box red/green?",
     ask([("has_property", "box", "red", True, False, True), ("has_property", "box", "green", True, False, True)])),
    ("Is the milk hot/cold?",
     ask([("has_property", "milk", "hot", True, False, True), ("has_property", "milk", "cold", True, False, True)])),
]

def quote(who, *content):
    return tell(("instance_of", "?v0", "say", True), ("done_by", "?v0", who, True), ("precedes", "?v0", "?now", True),
                *[f + (False, False, True) for f in content])


def did(kind, doer):
    return [("instance_of", "?v1", kind, True), ("done_by", "?v1", doer, True), ("precedes", "?v1", "?now", True)]


#: Never taught: quotations, in pairings english_39 does not make. Written before english_39's first run.
HELD_OUT_39 = [
    ('Anna said, "The dog barked."', quote("anna", *did("bark", "dog"))),
    ('Rex said, "The fish swam."', quote("rex", *did("swim", "fish"))),
    ('"The bird flew," Tom said.', quote("tom", *did("fly", "bird"))),
    ('"The cup is hot," Anna said.', quote("anna", ("has_property", "cup", "hot", True))),
    ('Rex said, "Anna is kind."', quote("rex", ("has_property", "anna", "kind", True))),
    ("Tom said, “The door is closed.”", quote("tom", ("has_property", "door", "closed", True))),
    ("“The dog is big,” Rex said.", quote("rex", ("has_property", "dog", "big", True))),
    ('Anna said, "The cat climbed."', quote("anna", *did("climb", "cat"))),
]

#: Phase 1's lessons, in the order they are taught, each with what it is measured on.
PHASE_1 = [(ROOT / "data" / "lessons" / "english_32.json", "the comma", HELD_OUT_32),
           (ROOT / "data" / "lessons" / "english_33.json", "the apostrophe", HELD_OUT_33),
           (ROOT / "data" / "lessons" / "english_34.json", "the colon and the semicolon", HELD_OUT_34),
           (ROOT / "data" / "lessons" / "english_35.json", "a title with a period", HELD_OUT_35),
           (ROOT / "data" / "lessons" / "english_36.json", "parentheses, dashes and '!'", HELD_OUT_36),
           (ROOT / "data" / "lessons" / "english_37.json", "money, measures and dates", HELD_OUT_37),
           (ROOT / "data" / "lessons" / "english_38.json", "times of day, the ellipsis and the slash", HELD_OUT_38),
           (ROOT / "data" / "lessons" / "english_39.json", "quotation marks", HELD_OUT_39)]

EV = RunRecord("ENGLISH-01",
               claim=("Taught Phase 1's lessons after english_01-31, Lyric reads the writing system's marks in the uses "
                      "web English makes of them most, in sentences it was taught and in ones it was not, and without "
                      "losing what the earlier lessons taught."),
               hypothesis=("A Phase 1 sentence refused or read otherwise than taught, a never-taught sentence read "
                           "otherwise than written here, an earlier lesson's sentence no longer read as taught, or a "
                           "write to the main store shows here."))


def say(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def taken(sentence):
    """What the listener takes the sentence to mean, said as one meaning: one utterance's, or, where the reader reads
    it as several ("Tom ran; Rex walked." is two sentences a semicolon joins), what they say together, each one's
    unknowns kept apart. None where it reads whole and the listener cannot tell; "unread" where it does not read."""
    from core.semantics import derived_reader as dr
    utterances = dr.read_text(sentence)
    if not utterances or not all(u.understood for u in utterances):
        return "unread"
    chosen = [dr.meant(u.readings) for u in utterances]
    if any(c is None for c in chosen):
        return None
    if len(chosen) == 1:
        return chosen[0].meaning.canonical()
    if len({c.meaning.act for c in chosen}) != 1:
        return " | ".join(c.meaning.canonical() for c in chosen)
    facts = []
    for at, c in enumerate(chosen):
        apart = {t: f"?u{at}_{t[1:]}" for f in c.meaning.facts for t in f.terms() if dr.is_variable(t)
                 and t not in dr.SITUATION_VARIABLES}
        facts.extend(f.renamed(apart) for f in c.meaning.facts)
    return dr.Meaning(chosen[0].meaning.act, tuple(facts)).canonical()


def read_all(items):
    """`(sentence, expected, read)` for each `(sentence, canonical meaning)`."""
    return [(sentence, expected, taken(sentence)) for sentence, expected in items]


def taught(paths):
    from core.semantics.derived_reader import Meaning
    return [(r["sentence"], Meaning.from_dict(r["meaning"]).canonical())
            for path in paths for r in json.loads(path.read_text())["records"]]


async def main() -> int:
    fresh.EV = EV
    started = time.time()
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")], capture_output=True,
                           text=True, cwd=str(ROOT))
    main_before = await fresh._sense.main_store_rows()
    system, coord = await boot()
    try:
        check("the run is in the sandbox, emptied first",
              await EV.verify_database() == "lyric_dev" and reset.returncode == 0,
              f"connected to {EV.verified_database}; reset exit {reset.returncode}")
        refused = {}
        for path in BEFORE:
            report, total = await fresh.teach(path, path.name, "english")
            if report.patterns.get("refused") or report.patterns.get("total") != total:
                refused[path.name] = report.patterns
        check(f"the {len(BEFORE)} earlier lessons are learned, none refused", not refused,
              f"{refused}" if refused else f"{BEFORE[-1].name} the last")
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        await agent.language_view()
        from core.semantics.derived_reader import Meaning
        for lesson_path, mark, held in PHASE_1:
            name = lesson_path.stem
            held_out = [(s, known_the.known(s, Meaning.from_dict(m)).canonical()) for s, m in held]
            before_lesson = read_all(held_out)
            EV.metric(f"never-taught sentences with {mark} read as written before {name}",
                      f"{sum(1 for _, e, g in before_lesson if g == e)}/{len(before_lesson)}")

            say(f"\n== A. {name}, {mark} ==")
            report, total = await fresh.teach(lesson_path, lesson_path.name, "english")
            check(f"{name} is learned, none refused",
                  report.patterns.get("refused") == 0 and report.patterns.get("total") == total, f"{report.patterns}")
            await agent.language_view()
            lesson = read_all(taught([lesson_path]))
            wrong = [(s, g) for s, e, g in lesson if g != e]
            for s, g in wrong:
                say(f"    {s!r} read {g!r}")
            check(f"every sentence of {name} reads as taught", not wrong,
                  f"{len(lesson) - len(wrong)} of {len(lesson)}")

            say(f"\n== B. Never taught, {mark} ==")
            after = read_all(held_out)
            wrong = [(s, e, g) for s, e, g in after if g != e]
            for s, e, g in wrong:
                say(f"    {s!r}\n        written {e}\n        read    {g}")
            EV.metric(f"never-taught readings, {mark}", [{"sentence": s, "written": e, "read": g} for s, e, g in after])
            check(f"never-taught sentences with {mark} read as written", not wrong,
                  f"{len(after) - len(wrong)} of {len(after)}")

        say("\n== C. The earlier lessons ==")
        earlier = read_all(taught(BEFORE))
        wrong = [(s, g) for s, e, g in earlier if g != e]
        for s, g in wrong[:20]:
            say(f"    {s!r} read {g!r}")
        EV.metric("earlier sentences read otherwise", [{"sentence": s, "read": g} for s, g in wrong])
        check("every sentence english_01-31 teach still reads as taught", not wrong,
              f"{len(earlier) - len(wrong)} of {len(earlier)}")
    finally:
        await shutdown(system)
    main_after = await fresh._sense.main_store_rows()
    if main_after == main_before:
        check("the main model's store is untouched", True, fresh._sense.main_store_change(main_before, main_after))
    else:
        # Not a check: the main model may be taught by its own process while this runs, so a change cannot be put
        # down to this run. Recorded, for whoever reads the record to tell whose write it was.
        EV.note("the main model's store moved during the run (it may have been taught alongside): "
                + fresh._sense.main_store_change(main_before, main_after))
        say("  main moved during the run; recorded as a note, not a check")
    passed = sum(1 for c in EV.checks if c.passed)
    say(f"\n==== ENGLISH-01: {passed}/{len(EV.checks)} checks passed ({time.time() - started:.0f} s) ====")
    say(f"  run record: {EV.write()}")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
