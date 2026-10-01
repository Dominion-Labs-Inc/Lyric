#!/usr/bin/env python3
"""SHAPES-LEARN-09 — function words, names and words without "a", taught; and new words said as words like them are.

Part 2's first lesson and the fix to saying new words, in `docs/research/SHAPES_CHANGE_MAP.md` (§11f). `english_06`
teaches function words the meaning language already holds; `english_07` teaches names, words used without "a", "is a
kind of", plural-only words, and kinds of people written with a capital ("An American is a person.") beside names
that end as they do ("Japan"). A word never held is said only where words used as it is used stand: a name never
after "a", a word without "a" bare, a plural-only word as a plural, a counted word never bare
(`PatternInventory.use_of`, `slot_admits`).

  A  TEACH      the seven lessons (english_01 to english_07) through the one teaching path, none refused
  B  TAUGHT     every taught sentence of the seven still reads to its meaning
  C  FUNCTION   sentences with english_06's words, never taught, read to the meaning they have
  D  NAMES      sentences with names, words without "a" and kinds of people, never taught, read to the meaning
                they have
  E  SAID       WordNet's nouns, said through the teaching pass's own saying: no name after "a", no word the view
                takes to go without "a" after one, no counted word bare, "a" and "an" as the letter after them
                asks, plural-only words as plurals (measured and checked)
  F  FAULTS     the sentences SHAPES-LEARN-08, and this experiment's first run, said wrongly are said rightly
  G  NOTHING    reading and saying wrote nothing
  H  MAIN       the main model's store is untouched

WordNet is said here, not taught: its word-class stage (75,833 memories) is not what is measured. Runs in the SANDBOX
(`lyric_dev`), emptied first by `scripts/reset_dev_store.py`; the seven lessons are kept.

Run: ./venv_lyric/bin/python3 experiments/SHAPES-LEARN-09/experiment.py
"""
from __future__ import annotations

import asyncio
import collections
import os
import random
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from core.semantics.derived_reader import Meaning, MeaningFact as F  # noqa: E402

LESSONS = [ROOT / "data" / "lessons" / f"english_0{n}.json" for n in range(1, 8)]
DOMAIN = "shapes_learn_09"
SAMPLE = 3000
SEED = 20260929


def _tell(*facts):
    return Meaning("tell", tuple(F(*f) for f in facts))


def _ask(facts, asked=()):
    return Meaning("ask", tuple(F(*f) for f in facts), tuple(asked))


#: Sentences with english_06's words, never taught, and what each means.
FUNCTION = [
    ("The ball is near the table.", _tell(("near", "ball", "table"))),
    ("Is the book inside the bag?", _ask([("located_in", "book", "bag")])),
    ("The dog is at the table.", _tell(("located_at", "dog", "table"))),
    ("Noon is before morning.", _tell(("precedes", "noon", "morning"))),
    ("This is his ball.", _tell(("instance_of", "?shown", "ball"), ("owned_by", "?shown", "?previous"))),
    ("Her dog is big.", _tell(("instance_of", "?x", "dog"), ("owned_by", "?x", "?previous"), ("has_property", "?x", "big"))),
    ("Those are my socks.", _tell(("instance_of", "?shown", "sock"), ("owned_by", "?shown", "?speaker"))),
    ("Who owns the dog?", _ask([("owns", "?x", "dog")], ["?x"])),
    ("Which ball is red?", _ask([("instance_of", "?x", "ball"), ("has_property", "?x", "red")], ["?x"])),
    ("All fish can swim.", _tell(("capable_of", "fish", "swim"))),
    ("Every cat is an animal.", _tell(("isa", "cat", "animal"))),
    ("Birds never swim.", _tell(("capable_of", "bird", "swim", False))),
    ("The box with the handle is red.", _tell(("instance_of", "?x", "box"), ("has_part", "?x", "handle"), ("has_property", "?x", "red"))),
    ("The girl who owns the bike is tall.", _tell(("instance_of", "?x", "girl"), ("owns", "?x", "bike"), ("has_property", "?x", "tall"))),
    ("The pen that is on the table is red.", _tell(("instance_of", "?x", "pen"), ("located_at", "?x", "table"), ("has_property", "?x", "red"))),
]
#: Sentences with names and words without "a", never taught, and what each means (a word never held keeps its
#: writing when read, so these compare case aside).
NAMES = [
    ("Is Rex a cat?", _ask([("isa", "rex", "cat")])),
    ("Tom can fly.", _tell(("capable_of", "tom", "fly"))),
    ("Rex owns a bike.", _tell(("owns", "rex", "bike"))),
    ("Water is a kind of liquid.", _tell(("isa", "water", "liquid"))),
    ("Is milk a food?", _ask([("isa", "milk", "food")])),
    ("Mississippi is a river.", _tell(("isa", "mississippi", "river"))),
    ("Hydrology is a kind of geology.", _tell(("isa", "hydrology", "geology"))),
    ("Is Rex a German?", _ask([("isa", "rex", "german")])),
    ("A Bostonian is a person.", _tell(("isa", "bostonian", "person"))),
]
#: What SHAPES-LEARN-08, and this experiment's first run, said wrongly, and the English ways of saying it: a kind
#: said of every one of its kind is said of "a" or of "every" one.
FAULTS = [
    (("thiosulfil", "sulfa drug", (("thiosulfil", "Thiosulfil"),)), ("Thiosulfil is a sulfa drug.",)),
    (("paleoanthropology", "vertebrate paleontology", ()),
     ("Paleoanthropology is a kind of vertebrate paleontology.",)),
    (("fire tongs", "tongs", ()), ("Fire tongs are tongs.",)),
    (("asian", "inhabitant", (("asian", "Asian"),)), ("An Asian is an inhabitant.", "Every Asian is an inhabitant.")),
    (("slovenian", "person", (("slovenian", "Slovenian"),)), ("A Slovenian is a person.", "Every Slovenian is a person.")),
]

EV = RunRecord(
    "SHAPES-LEARN-09",
    claim=("Taught function words, names, words used without 'a' and kinds of people written with a capital by "
           "example through its one teaching path, the substrate reads sentences with them it was never taught, and "
           "says a word it never held only where words used as it is used stand: WordNet's names without 'a', its "
           "words used without 'a' bare, its counted words, capital or not, after 'a' or 'an' as the next letter "
           "asks, its plural-only words as plurals."),
    hypothesis=("A lesson pair refused; a taught sentence that no longer reads; a never-taught probe unread or misread; "
                "a name said after 'a', a word the view takes to go without 'a' said after one, a counted word said "
                "bare, or 'a' and 'an' against the letter after them; a fault said again; a reading or saying that "
                "writes; or a write to the main store would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main_store_rows() -> int:
    """Rows in the main model's store, counted over its own connection."""
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="lyric_db")
    try:
        n = 0
        for t in await c.fetch(
                "select table_schema s, table_name n from information_schema.tables "
                "where table_schema in ('unified','memory_hot','memory_cold') and table_type='BASE TABLE'"):
            n += await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
        return n
    finally:
        await c.close()


async def main() -> int:
    main_before = await main_store_rows()
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox", where["d"] == "lyric_dev", f"connected to {where['d']}")
    if where["d"] != "lyric_dev":
        return 1
    import contextlib
    import io
    boot_log = io.StringIO()
    with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
        from core.main import get_system
        system = get_system()
        await system.start()
    check("the substrate is running", system.autonomous_coordinator is not None and system.running)
    try:
        return await _run(main_before)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


def _meanings(sentence):
    from core.semantics import derived_reader as dr
    return [u.readings[0].meaning.canonical() if u.readings else None for u in dr.read_text(sentence)]


def _after_a(sentence: str, word: str) -> bool:
    """Whether this word is written right after "a" or "an" in the sentence."""
    from core.semantics.sentence_machine import form_of
    pieces = [p.text.lower() for p in form_of(sentence)]
    written = [p.text.lower() for p in form_of(word)]
    return any(pieces[i] in ("a", "an") and pieces[i + 1:i + 1 + len(written)] == written
               for i in range(len(pieces) - len(written)))


def _bare(sentence: str, word: str, *, at_start: bool = True) -> bool:
    """Whether the sentence has this word right after "is", nothing before it, or, `at_start`, begins with it."""
    from core.semantics.sentence_machine import form_of
    written = [p.text.lower() for p in form_of(word)]
    pieces = [p.text.lower() for p in form_of(sentence)]
    return (at_start and pieces[:len(written)] == written) or any(
        pieces[i] == "is" and pieces[i + 1:i + 1 + len(written)] == written for i in range(len(pieces)))


def _against_the_letter(sentence: str) -> list:
    """Where "a" or "an" is written against the letter after it, as the checker reads English spelling: "an" before
    a consonant, "a" before a, e, i or o. A word beginning with "h" or "u" goes either way ("an hour", "a unit") and
    is not judged."""
    from core.semantics.sentence_machine import form_of
    pieces = [p.text for p in form_of(sentence)]
    return [f"{one} {two}" for one, two in zip(pieces, pieces[1:]) if two[:1].isalpha() and two[:1].lower() not in "hu"
            and ((one.lower() == "an" and two[:1].lower() not in "aeio")
                 or (one.lower() == "a" and two[:1].lower() in "aeio"))]


async def _run(main_before: int) -> int:
    from core.learning import get_learning_authority
    from core.learning.teaching import Report, TaughtRecord, TeachingPass
    from core.learning.teaching_sources import LessonSource, WordNetSource
    from core.memory import get_memory_agent
    from core.semantics import derived_reader as dr
    agent = await get_memory_agent()
    learning = get_learning_authority()

    say_line("== A. The seven lessons, through the one teaching path ==")
    taught = []
    for path in LESSONS:
        source = LessonSource(str(path))
        lesson = list(source.records())
        report = await TeachingPass(source, domain=DOMAIN, sample=False).run(learning)
        taught.extend(lesson)
        check(f"{path.name} is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson),
              f"{report.patterns}")
    view = agent.pattern_inventory()
    size = len(view)

    say_line("\n== B. Every taught sentence still reads to its meaning ==")
    unread = [r.sentence for r in taught
              if not [x for x in dr.read(r.sentence) if x.meaning.canonical() == r.meaning.canonical()][:1]]
    check("every taught sentence of the seven lessons reads to its meaning", not unread, f"{unread[:5]}")

    for title, probes, name in (("C. english_06's words, never taught", FUNCTION, "function words"),
                                ("D. Names and words without \"a\", never taught", NAMES, "names and bare words")):
        say_line(f"\n== {title} ==")
        right = 0
        for sentence, wanted in probes:
            got = _meanings(sentence)
            ok = [g.lower() if g else g for g in got] == [wanted.canonical().lower()]
            right += ok
            say_line(f"    {'ok ' if ok else 'BAD'} {sentence!r} -> {got}")
        check(f"sentences with {name} never taught read to the meaning they have", right == len(probes),
              f"{right}/{len(probes)}")
        EV.metric(f"never-taught {name} read", f"{right}/{len(probes)}")

    say_line("\n== E. WordNet's nouns, said through the teaching pass's own saying ==")
    wordnet = TeachingPass(WordNetSource(), domain=DOMAIN, limit=SAMPLE, sample=True, seed=SEED)
    nouns = [r for r in wordnet._harvest(Report(source="wordnet", domain=DOMAIN)) if r.meaning is not None]
    uses = collections.Counter()
    examples = collections.defaultdict(list)
    wrong, bare, lettered = [], [], []
    said = 0
    for record in nouns:
        sentence = TeachingPass._said(record)
        word = dict(record.words).get(record.subject, record.subject)
        # A word held already is said as it was taught; the use found from its writing governs a word never held.
        use = "held" if view.lexicals_with_value(record.subject) or view.lexicals_with_value(word) \
            or view.lexicals_with_words((word.lower(),), loose=True) else view.use_of(word)
        uses[use] += 1
        if not sentence:
            continue
        said += 1
        if len(examples[use]) < 6:
            examples[use].append(sentence)
        if use in ("name", "mass") and _after_a(sentence, word):
            wrong.append(sentence)
        parent = dict(record.words).get(record.obj, record.obj)
        if (use == "count" and _bare(sentence, word)) \
                or (view.use_of(parent) == "count" and _bare(sentence, parent, at_start=False)):
            bare.append(sentence)
        if _against_the_letter(sentence):
            lettered.append(sentence)
    for use in ("count", "name", "mass", "plural", "held"):
        say_line(f"    {use:7} {uses[use]:5} words, e.g. {examples[use][:6]}")
    say_line(f"    said {said} of {len(nouns)}")
    check("no name, and no word taken to go without 'a', is said after 'a'", not wrong, f"{wrong[:5]}")
    check("no word taken to be counted is said bare", not bare, f"{bare[:5]}")
    check("'a' and 'an' are written as the letter after them asks", not lettered, f"{lettered[:5]}")
    EV.metric("WordNet nouns said", f"{said}/{len(nouns)}")
    EV.metric("uses found for WordNet's nouns", dict(uses))

    say_line("\n== F. What SHAPES-LEARN-08, and this experiment's first run, said wrongly ==")
    fixed = 0
    for (child, parent, words), wanted in FAULTS:
        record = TaughtRecord(child, "isa", parent, 0.9, meaning=Meaning("tell", (F("isa", child, parent),)),
                              words=words)
        got = TeachingPass._said(record)
        fixed += got in wanted
        say_line(f"    {'ok ' if got in wanted else 'BAD'} isa({child}, {parent}) -> {got!r}")
    check("each is said as English says it", fixed == len(FAULTS), f"{fixed}/{len(FAULTS)}")

    say_line("\n== G. Reading and saying wrote nothing ==")
    check("the view is as teaching left it", len(agent.pattern_inventory()) == size,
          f"{size} -> {len(agent.pattern_inventory())}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-09 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    print(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        sys.exit("the sandbox could not be emptied; not running")
    sys.exit(asyncio.run(main()))
