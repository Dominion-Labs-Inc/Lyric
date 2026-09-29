#!/usr/bin/env python3
"""SHAPES-LEARN-03 — the first English lesson, and what the reading engine reads with it.

Step 3, part 2 of `docs/research/SHAPES_CHANGE_MAP.md` (§11b). The first lesson of basic English
(`data/lessons/english_01.json`) is taught through the ONE teaching path, one sentence with its meaning at a time,
in the sandbox. Every sentence in it is an example of English, so nothing it states is held. Then the engine reads
with nothing but what the lesson left in memory:

  A  TEACH      the lesson through the one teaching path; every pair read or repaired, none refused
  B  EXAMPLES   nothing the lesson states is held: no fact, rule or relation from it, only how English says things
  C  TAUGHT     every taught sentence reads to its meaning
  D  PROBES     sentences never taught read to the meaning they have: fillers of a known kind, new words in known
                frames, sentences heard without capitals or marks, a paragraph; what the lesson never taught stays
                unread
  E  KIND       the kind of utterance (tell / ask / request) comes from the reading
  F  BASELINE   SHAPES-BASELINE-01's sentences, beside the written reader's 9/35 read and 13/45 kinds right
  G  PROSE      the 300 sentences of real prose NLU-01 measured, beside the written reader's 83
  H  NOTHING    reading wrote nothing
  I  MAIN       the main model's store is untouched

Runs in the SANDBOX (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`. The substrate is started
before anything is taught, so the domain reactions run as they would.

Run: ./venv_lyric/bin/python3 experiments/SHAPES-LEARN-03/experiment.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
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

LESSON_PATH = ROOT / "data" / "lessons" / "english_01.json"
LESSON_DOMAIN = "shapes_learn_03"


def _m(act, *facts, asked=()):
    """A meaning from facts written `relation subject object`, `!` before a denied relation, `if ` before a
    condition; `_` stands for a space inside a name."""
    out = []
    for fact in facts:
        condition = fact.startswith("if ")
        relation, subject, obj = (fact[3:] if condition else fact).split()
        out.append(F(relation.lstrip("!"), subject.replace("_", " "), obj.replace("_", " "),
                     not relation.startswith("!"), condition))
    return Meaning(act, tuple(out), tuple(asked))


#: Never taught. (text, the meaning of each utterance in it, or None where it should stay unread)
PROBES = [
    # the sentences the hearing and conversation experiments say, with names never seen
    ("a vex123 is a mammal", [_m("tell", "isa vex123 mammal")]),
    ("is a vex123 an animal", [_m("ask", "isa vex123 animal")]),
    ("is a vex123 a mammal", [_m("ask", "isa vex123 mammal")]),
    ("a zq3k heron is a zq3k bird", [_m("tell", "isa zq3k_heron zq3k_bird")]),
    ("is a zq3k heron a zq3k bird", [_m("ask", "isa zq3k_heron zq3k_bird")]),
    ("is a zq3k heron a zq3k fish", [_m("ask", "isa zq3k_heron zq3k_fish")]),
    ("is a n9florp a n9blip", [_m("ask", "isa n9florp n9blip")]),
    ("if the vex123 is hot then the valve is hot", [_m("tell", "if has_property vex123 hot",
                                                       "has_property valve hot")]),
    ("is the vex123 hot", [_m("ask", "has_property vex123 hot")]),
    ("what did I just tell you", [_m("ask", "instance_of ?e tell", "done_by ?e ?speaker", "done_to ?e ?listener",
                                     asked=("?e",))]),
    ("are mammals animals", [_m("ask", "isa mammal animal")]),
    ("a mammal is an animal", [_m("tell", "isa mammal animal")]),
    # SHAPES-BASELINE-01's shapes, with fillers the lesson never put in them
    ("The shoe is black.", [_m("tell", "has_property shoe black")]),
    ("My shoe is black.", [_m("tell", "instance_of ?x shoe", "owned_by ?x ?speaker", "has_property ?x black")]),
    ("It is black.", [_m("tell", "has_property ?previous black")]),
    ("Is the shoe red?", [_m("ask", "has_property shoe red")]),
    ("What color is the shoe?", [_m("ask", "has_property shoe ?c", "instance_of ?c color", asked=("?c",))]),
    ("Tie your shoe.", [_m("request", "instance_of ?e tying", "done_by ?e ?listener", "done_to ?e ?x",
                           "instance_of ?x shoe", "owned_by ?x ?listener")]),
    ("She tall.", [_m("tell", "has_property ?previous tall")]),
    ("That shoe is fire.", [_m("tell", "instance_of ?shown shoe", "has_property ?shown excellent")]),
    # new combinations of what was taught
    ("Birds can swim.", [_m("tell", "capable_of bird swim")]),
    ("Can geese fly?", [_m("ask", "capable_of goose fly")]),
    ("Does a bike have wheels?", [_m("ask", "has_part bike wheel")]),
    ("Where is the cup?", [_m("ask", "located_in cup ?x", asked=("?x",))]),
    ("The cup is in the bag.", [_m("tell", "located_in cup bag")]),
    ("Close the tank.", [_m("request", "instance_of ?e closing", "done_by ?e ?listener", "done_to ?e tank")]),
    ("If the window is open, the room is cold.", [_m("tell", "if has_property window open",
                                                     "has_property room cold")]),
    ("A whale is not a bird.", [_m("tell", "!isa whale bird")]),
    ("What is a dog?", [_m("ask", "isa dog ?x", asked=("?x",))]),
    ("no, that is wrong", [_m("tell", "has_property ?previous false")]),
    # a paragraph
    ("This is my hat. It is black. The shoe is red.", [
        _m("tell", "instance_of ?shown hat", "owned_by ?shown ?speaker"),
        _m("tell", "has_property ?previous black"), _m("tell", "has_property shoe red")]),
    # never taught: stays unread
    ("Red, blue, and green are colors!", [None]),
    ("I have a red shoe.", [None]),
    ("He be working.", [None]),
    ("Hello there.", [None]),
]

EV = RunRecord(
    "SHAPES-LEARN-03",
    claim=("Taught one lesson of basic English, sentence by sentence with each sentence's meaning, the substrate "
           "reads sentences it was never taught: fillers of a kind it learned, names it has never seen in frames "
           "it knows, sentences heard without capitals or marks, and paragraphs. It says what kind of utterance "
           "each is, and holds nothing the lesson's examples state."),
    hypothesis=("A lesson pair refused or left unread; a fact, rule or relation held from an example; a taught "
                "sentence that does not read; a probe read to the wrong meaning, or an untaught shape read at all; "
                "a reading that writes; or any write to the main store would each show here. The prose sample is "
                "measured, not checked: one basic lesson is not expected to read documentation."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


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
        return await _run(db, main_before)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


def _described(utterances) -> list:
    out = []
    for u in utterances:
        if not u.readings:
            out.append("unread")
            continue
        r = u.readings[0]
        how = [w for w, on in (("new " + ",".join(x.value for x in r.new), bool(r.new)),
                               ("kind", bool(r.proposed) and not r.new), ("loose", r.loose)) if on]
        out.append(r.meaning.canonical() + (f" [{'; '.join(how)}]" if how else ""))
    return out


def _baseline_sentences():
    spec = importlib.util.spec_from_file_location("baseline", ROOT / "experiments" / "SHAPES-BASELINE-01" /
                                                  "experiment.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SENTENCES


async def _run(db, main_before: int) -> int:
    from core.learning import get_learning_authority
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import LessonSource
    from core.memory import get_memory_agent
    from core.semantics import derived_reader as dr
    agent = await get_memory_agent()
    await agent.warm_word_classes()
    learning = get_learning_authority()
    source = LessonSource(str(LESSON_PATH))
    lesson = list(source.records())

    say_line(f"== A. The lesson ({source.name}, {len(lesson)} sentences), through the one teaching path ==")
    report = await TeachingPass(source, domain=LESSON_DOMAIN, sample=False).run(learning)
    for line in report.lines():
        say_line(f"    {line}")
    check("every pair is read or repaired, none refused",
          report.patterns.get("refused") == 0 and report.patterns.get("total") == len(lesson), f"{report.patterns}")
    ran = {k[len("repair_"):]: v for k, v in report.patterns.items() if k.startswith("repair_")}
    say_line(f"    repairs: {ran}")
    for name, runs in sorted(ran.items()):
        EV.metric(f"repair: {name}", runs)
    view = agent.pattern_inventory()
    counted = {"holophrase": len(view.holophrases()), "item_based": len(view.item_based()),
               "lexical": len(view.lexicals()), "link": len(view.links())}
    say_line(f"    the view holds {counted}")

    say_line("\n== B. Examples state nothing ==")
    check("every sentence was taken as an example", report.meanings.get("example") == len(lesson)
          and sum(v for k, v in report.meanings.items() if k != "example") == 0, f"{report.meanings}")
    # The running substrate writes relations of its own while it boots (its tools, the files it can see), so
    # what is looked for is the lesson's own facts, each by its terms and link kind.
    stated = {(f.subject, f.relation, f.obj) for r in lesson for f in r.meaning.facts
              if not dr.is_variable(f.subject) and not dr.is_variable(f.obj)}
    relations = 0
    for subject, relation, obj in sorted(stated):
        row = await db.execute_query(
            "SELECT count(*) AS n FROM unified.concept_relations WHERE relation = $1 "
            "AND (source_concept_id = $2 OR source_concept_id LIKE '%:' || $2) "
            "AND (target_concept_id = $3 OR target_concept_id LIKE '%:' || $3)",
            (relation, subject.replace(" ", "_"), obj.replace(" ", "_")), fetch_one=True)
        relations += int(row["n"])
    beliefs = await db.execute_query(
        "SELECT count(*) AS n FROM unified.beliefs WHERE claim = ANY($1::text[])",
        ([f"{s} {r} {o}" for s, r, o in stated],), fetch_one=True)
    rules_table = await db.execute_query("SELECT to_regclass('unified.held_conditionals') AS t", (), fetch_one=True)
    rules = 0 if rules_table["t"] is None else int((await db.execute_query(
        "SELECT count(*) AS n FROM unified.held_conditionals", (), fetch_one=True))["n"])
    check("no relation, rule or belief states what the lesson's examples say",
          relations == 0 and rules == 0 and int(beliefs["n"]) == 0,
          f"{len(stated)} facts looked for: relations {relations}, beliefs {beliefs['n']}, rules {rules}")

    say_line("\n== C. Every taught sentence reads to its meaning ==")
    unread = [r.sentence for r in lesson
              if not [x for x in dr.read(r.sentence) if x.meaning.canonical() == r.meaning.canonical()][:1]]
    check("every taught sentence reads to its meaning", not unread, f"{unread[:5]}")

    size = len(view)
    say_line("\n== D. Sentences never taught ==")
    right, kinds_right, kinds_total = 0, 0, 0
    for text, wanted in PROBES:
        utterances = dr.read_text(text)
        got = [u.readings[0].meaning if u.readings else None for u in utterances]
        ok = [g.canonical() if g else None for g in got] == [w.canonical() if w else None for w in wanted]
        right += ok
        say_line(f"    {'ok ' if ok else 'BAD'} {text!r}\n          -> {_described(utterances)}")
        for g, w in zip(got, wanted):
            if w is not None:
                kinds_total += 1
                kinds_right += bool(g is not None and g.act == w.act)
    check("every probe reads to the meaning it has, and the untaught stay unread", right == len(PROBES),
          f"{right}/{len(PROBES)}")
    EV.metric("probes read as they mean", f"{right}/{len(PROBES)}")

    say_line("\n== E. The kind of utterance, from the reading ==")
    check("tell, ask and request come from each reading", kinds_right == kinds_total,
          f"{kinds_right}/{kinds_total}")

    say_line("\n== F. SHAPES-BASELINE-01's sentences ==")
    act_of = {"telling": "tell", "question": "ask", "job": "request"}
    statements = read_statements = kind_total = kind_right = 0
    for group, pairs in _baseline_sentences().items():
        for sentence, kind in pairs:
            utterances = dr.read_text(sentence)
            readings = [u.readings[0] for u in utterances if u.readings]
            understood = bool(utterances) and all(u.understood for u in utterances)
            if kind == "telling":
                statements += 1
                read_statements += understood
            kind_total += 1
            kind_right += bool(readings) and readings[0].meaning.act == act_of.get(kind)
            say_line(f"    {'read  ' if understood else 'unread'} [{group}] {sentence!r} -> {_described(utterances)}")
    say_line(f"    statements read: {read_statements}/{statements} (the written reader: 9/35); "
             f"kind right: {kind_right}/{kind_total} (the written reader: 13/45)")
    EV.metric("baseline statements read", f"{read_statements}/{statements}")
    EV.metric("baseline kind right", f"{kind_right}/{kind_total}")

    say_line("\n== G. Real prose (NLU-01's 300 sentences) ==")
    sys.path.insert(0, str(ROOT / "experiments" / "nlu"))
    from _nlu_lib import real_prose
    prose = real_prose(limit=300)
    whole = partly = 0
    for sentence in prose:
        utterances = dr.read_text(sentence)
        whole += bool(utterances) and all(u.understood for u in utterances)
        partly += any(u.understood for u in utterances)
    say_line(f"    read whole: {whole}/{len(prose)}; read in part: {partly}/{len(prose)} "
             f"(the written reader gave some reading of 83/300)")
    EV.metric("prose read whole", f"{whole}/{len(prose)}")
    EV.metric("prose read in part", f"{partly}/{len(prose)}")

    say_line("\n== H. Reading wrote nothing ==")
    check("the view is as teaching left it", len(view) == size, f"{size} -> {len(view)}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")
    for name, value in counted.items():
        EV.metric(f"constructions: {name}", value)
    EV.metric("communicative success, first hearing", f"{report.patterns.get('understood')}/{len(lesson)}")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-03 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
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
