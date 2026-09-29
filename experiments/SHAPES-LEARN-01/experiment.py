#!/usr/bin/env python3
"""SHAPES-LEARN-01 — sentences taught with their meaning become patterns the substrate reads and says.

Step 1 of `docs/research/SHAPES_CHANGE_MAP.md`. A small lesson is taught through
the ONE teaching path (`TeachingPass` -> the learning authority), every record a
sentence WITH what it means. Then each named owner is checked for what it
now holds, and the patterns are used:

  A  TEACH      the lesson, through the one teaching path
  B  MEMORY     one pattern memory per sentence, exactly identified, not merged,
                not read as a claim
  C  BELIEFS    one belief per pattern, grounded in its memory, in the English domain
  D  DOMAINS    every admission reaches the running substrate; English and the
                lesson's domain are judged by what memory holds for them (English by
                its patterns); no domain record stores a copy of what it holds; the
                thinnest knowledge is what proactive research would go after
  E  FACTS      what the meanings state, bound to the situation: general facts held in
                the model's graph, denials as denials; facts about the situation (the
                speaker's shoe) held in the speaker's context, never the model;
                nothing from questions or requests
  F  LEDGER     every pattern recorded as new
  G  READ/SAY   a taught sentence reads to its meaning; its meaning says it back;
                an untaught sentence reads to nothing; a taught one heard without
                its capital reads loosely, and says so
  H  WARM       a fresh warm, from memory alone, reads the same
  I  AGAIN      the same lesson again from the same source moves nothing
  J  WITNESS    the same lesson from another source is a second observation
  K  REASON     the reasoner formalizes a taught premise and a taught question
  L  MAIN       the main model's store is untouched

Runs in the SANDBOX (`lyric_dev`), emptied first by `scripts/reset_dev_store.py`,
so it starts from nothing every time. The main store is counted before and after.
The substrate is STARTED before anything is taught: learning announces what it
admitted to the running substrate, whose reactions judge the domains, and a lesson
taught into a substrate that is not running is never heard (2026-09-27: that is how
every domain record was found empty).

Run: ./venv_lyric/bin/python3 experiments/SHAPES-LEARN-01/experiment.py
"""
from __future__ import annotations

import asyncio
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

LESSON_DOMAIN = "shapes_learn_01"
TEACHER = (("?speaker", "teacher"), ("?shown", "teachers_shoe"))

SHOE = Meaning("tell", (F("instance_of", "?shown", "shoe"),
                        F("owned_by", "?shown", "?speaker")))
BLACK = Meaning("tell", (F("has_property", "?shown", "black"),))
IT_BLACK = Meaning("tell", (F("has_property", "?previous", "black"),))
RED_Q = Meaning("ask", (F("has_property", "?shown", "red"),))
COLOR_Q = Meaning("ask", (F("has_property", "?shown", "?c"),
                          F("instance_of", "?c", "color")), asked=("?c",))
TIE = Meaning("request", (F("instance_of", "?e", "tying"),
                          F("done_by", "?e", "?listener"),
                          F("done_to", "?e", "?shown")))
ROBIN = Meaning("tell", (F("isa", "robin", "bird"),))
ROBIN_Q = Meaning("ask", (F("isa", "robin", "bird"),))
NOT_MAMMAL = Meaning("tell", (F("isa", "robin", "mammal", positive=False),))

#: (sentence, meaning, situation)
LESSON = [
    ("This is my shoe.", SHOE, TEACHER),
    ("My shoe is black.", BLACK, TEACHER),
    ("It is black.", IT_BLACK, (("?previous", "teachers_shoe"),)),
    ("Is the shoe red?", RED_Q, TEACHER),
    ("What color is the shoe?", COLOR_Q, TEACHER),
    ("Tie your shoe.", TIE, (("?shown", "teachers_shoe"),)),
    ("A robin is a bird.", ROBIN, ()),
    ("Is a robin a bird?", ROBIN_Q, ()),
    ("A robin is not a mammal.", NOT_MAMMAL, ()),
]

EV = RunRecord(
    "SHAPES-LEARN-01",
    claim=("Sentences taught with their meaning through the one teaching path become patterns: "
           "held in memory, scored by beliefs, in the English domain, their facts held in the graph; "
           "a taught sentence then reads to its meaning and its meaning is said back as the sentence."),
    hypothesis=("A pattern not stored, merged, or read as a claim; a belief missing or not grounded "
                "in its pattern's memory; no English domain; a fact missing, or held from a question "
                "or a request; a denial held as an assertion; a sentence that does not read back, or an "
                "untaught one that does; a re-teach that counts twice; or any write to the main store "
                "would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class Lesson:
    """The lesson as a teaching source: each sentence with what it means."""

    name = "SHAPES-LEARN-01 lesson"
    curated = True
    quality = 0.9

    def __init__(self, source_id: str):
        self.source_id = source_id

    def provenance(self):
        from core.learning.teaching_sources import _provenance
        return _provenance("teaching", self.source_id)

    def records(self):
        from core.learning.teaching import TaughtRecord
        for sentence, meaning, situation in LESSON:
            yield TaughtRecord(subject="", relation="", obj="", quality=self.quality,
                               sentence=sentence, meaning=meaning, situation=situation)


async def main_store_rows() -> int:
    """Rows in the main model's store, counted over its own connection."""
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan",
                              database="lyric_db")
    try:
        n = 0
        for t in await c.fetch(
                "select table_schema s, table_name n from information_schema.tables "
                "where table_schema in ('unified','memory_hot','memory_cold') "
                "and table_type='BASE TABLE'"):
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
    coordinator = system.autonomous_coordinator
    check("the substrate is running", coordinator is not None and system.running)
    try:
        return await _run(db, coordinator, main_before)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


async def _run(db, coordinator, main_before: int) -> int:
    from core.memory import get_memory_agent
    agent = await get_memory_agent()
    await agent.warm_word_classes()
    from core.learning import get_learning_authority
    learning = get_learning_authority()
    unannounced_before = learning.system_metrics.get("admissions_unannounced", 0)
    import json as _json
    from core.learning.teaching import TeachingPass
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr
    from core.semantics.derived_reader import pattern_from

    say_line("== A. The lesson, through the one teaching path ==")
    report = await TeachingPass(Lesson("shapes-learn-01"), domain=LESSON_DOMAIN,
                                sample=False).run(learning)
    for line in report.lines():
        say_line(f"    {line}")
    check("every sentence became a pattern", report.patterns.get("learned") == len(LESSON)
          and report.patterns.get("refused") == 0, f"{report.patterns}")
    # Six facts are told (2 + 1 + 1 + 1 + 1) and seven are asked or requested
    # (1 + 2 + 3 + 1). WHOSE EACH TOLD FACT IS, ITS MEANING SAYS: the two
    # about robins name nothing of the situation and are the model's; the three
    # about the teacher's shoe name the shown thing or the speaker, so they are
    # the teacher's context; "It is black." names what was mentioned before, in
    # a situation that names no speaker, so it has nobody to belong to.
    check("meaning facts: the model's, the speaker's, and none from questions or requests",
          report.meanings == {"bound": 2, "speaker_context": 3, "no_speaker": 1, "open": 0,
                              "not_told": 7, "rule": 0, "rule_not_held": 0, "alternative": 0, "example": 0},
          f"{report.meanings}")
    check("each told fact is admitted once, where it belongs",
          report.taught.get("admitted") == 5 and report.taught.get("already") == 0
          and report.taught.get("refused") == 0, f"{report.taught}")

    patterns = [pattern_from(s, m) for s, m, _ in LESSON]

    say_line("\n== B. Memory ==")
    rows = await db.execute_query(
        "SELECT memory_id, content, tags, metadata FROM memory_hot.memory_hot "
        "WHERE tags::jsonb ? $1", (dr.PATTERN_TAG,), fetch_all=True) or []
    metas = [r["metadata"] if isinstance(r["metadata"], dict) else _json.loads(r["metadata"] or "{}")
             for r in rows]
    keys = {m.get("pattern_key") for m in metas}
    check("one pattern memory per sentence, none merged", len(rows) == len(LESSON)
          and keys == {p.key for p in patterns}, f"{len(rows)} memories, {len(keys)} keys")
    check("no pattern memory was read as a claim about the world",
          not any(m.get("conclusion") for m in metas))
    memory_of = {m.get("pattern_key"): r["memory_id"] for m, r in zip(metas, rows)}

    say_line("\n== C. Beliefs ==")
    us = get_uncertainty_system()
    beliefs = [us.belief_for_claim(p.claim()) for p in patterns]
    check("one belief per pattern", all(b is not None for b in beliefs),
          f"{sum(b is not None for b in beliefs)}/{len(patterns)}")
    check("each belief is grounded in its pattern's memory",
          all(b is not None and b.memory_id == memory_of.get(p.key)
              for b, p in zip(beliefs, patterns)))
    check("each belief is in the English domain",
          all(b is not None and b.domain == dr.ENGLISH_DOMAIN for b in beliefs))
    persisted = await db.execute_query(
        "SELECT count(*) AS n FROM unified.beliefs WHERE domain = $1",
        (dr.ENGLISH_DOMAIN,), fetch_one=True)
    check("the pattern beliefs are persisted", int(persisted["n"]) >= len(LESSON),
          f"{persisted['n']} belief row(s) in the English domain")

    say_line("\n== D. Domains, judged by what memory holds ==")
    from core.integration.universal_domain_master import get_universal_domain_master
    udm = get_universal_domain_master()
    check("every admission reached the running substrate",
          learning.system_metrics.get("admissions_unannounced", 0) == unannounced_before,
          f"{learning.system_metrics.get('admissions_unannounced', 0) - unannounced_before} unannounced")
    check("English is a domain", await udm.has_domain(dr.ENGLISH_DOMAIN))

    async def maturity(domain_id):
        row = await db.execute_query(
            "SELECT (metadata->>'maturity_score')::float AS m FROM unified.domains "
            "WHERE domain_id = $1", (domain_id,), fetch_one=True)
        return None if row is None else row["m"]

    # The reaction to each admission re-measures the domain it went into; it runs
    # on the substrate's own worker, so this waits for it rather than calling it.
    waited = 0.0
    while waited < 120 and not ((await maturity(dr.ENGLISH_DOMAIN) or 0) > 0.1
                                and (await maturity(LESSON_DOMAIN) or 0) > 0.1):
        await asyncio.sleep(1.0)
        waited += 1.0
    english, lesson = await maturity(dr.ENGLISH_DOMAIN), await maturity(LESSON_DOMAIN)
    # 9 patterns, 13 facts in their meanings, 6 link kinds -> coverage_from_counts
    from core.domain.domain_types import coverage_from_counts
    expected = coverage_from_counts(9, 13, 6)
    check("English is judged by its patterns", english is not None
          and abs(english - expected) < 1e-4, f"maturity {english} (expected {expected}, "
          f"after {waited:.0f}s)")
    check("the lesson's domain is judged by what it now holds", lesson is not None
          and lesson > 0.1, f"maturity {lesson} (registered at 0.1)")
    records = await db.execute_query(
        "SELECT domain_id, metadata FROM unified.domains WHERE domain_id = ANY($1::text[])",
        ([dr.ENGLISH_DOMAIN, LESSON_DOMAIN],), fetch_all=True) or []
    copies = {r["domain_id"]: sorted(set(_json.loads(r["metadata"]) if isinstance(r["metadata"], str)
                                         else r["metadata"]) & {"concepts", "relations",
                                                                "knowledge", "vocabulary"})
              for r in records}
    check("no domain record stores a copy of what it holds",
          len(records) == 2 and not any(copies.values()), f"{copies}")
    sparsity = await udm.knowledge_sparsity_map(LESSON_DOMAIN)
    say_line(f"  sparsity map of {LESSON_DOMAIN}: {sparsity.get('concepts')} concept(s), "
             f"sparsest {[r['concept'] for r in sparsity.get('sparsest', [])]}")
    lesson_concepts = {"robin", "bird", "mammal"}      # the model's; the shoe is the teacher's
    # Starting the substrate also runs its one boot scan of the folder it runs
    # in, which makes learned domains of its own; the lesson's thin concepts are
    # looked for among all the topics, not assumed to rank first.
    topics = await coordinator._thinnest_knowledge_topics(limit=64)
    say_line(f"  proactive research topics: {topics}")
    check("the thinnest knowledge is what proactive research would go after",
          any(str(r["concept"]) in lesson_concepts for r in sparsity.get("sparsest", []))
          and any(t.split(" (")[0].replace(" ", "_") in lesson_concepts for t in topics),
          f"{len(topics)} topic(s)")

    say_line("\n== E. Facts ==")
    edges = await db.execute_query(
        "SELECT c.name AS s, cr.relation AS r, cr.target_surface AS o, cr.polarity AS p "
        "FROM unified.concept_relations cr JOIN unified.concepts c "
        "ON c.concept_id = cr.source_concept_id ORDER BY cr.created_at", (), fetch_all=True) or []
    held = {(e["s"], e["r"].replace(" ", "_"), e["o"], e["p"]) for e in edges}
    for e in edges:
        say_line(f"      {e['s']} —{e['r']}→ {e['o']} ({e['p']})")
    wanted = {("robin", "isa", "bird", "positive"),
              ("robin", "isa", "mammal", "negative")}
    speakers = {("teachers_shoe", "instance_of", "shoe", "positive"),
                ("teachers_shoe", "owned_by", "teacher", "positive"),
                ("teachers_shoe", "has_property", "black", "positive")}
    check("the general facts are held in the model's graph", wanted <= held,
          f"missing {sorted(wanted - held)}" if not wanted <= held else f"{len(edges)} edge(s)")
    check("no fact about the situation is in the model", not any(s == "teachers_shoe" for s, *_ in held),
          f"{sorted(e for e in held if e[0] == 'teachers_shoe')}")
    scoped = await db.execute_query(
        "SELECT scope_actor, subj, rel, obj, polarity FROM unified.scoped_concept_relations", (),
        fetch_all=True, store="user_context") or []
    teachers = {(r["subj"], r["rel"].replace(" ", "_"), r["obj"], r["polarity"])
                for r in scoped if r["scope_actor"] == "teacher"}
    for r in scoped:
        say_line(f"      [{r['scope_actor']}] {r['subj']} —{r['rel']}→ {r['obj']} ({r['polarity']})")
    check("the facts about the teacher's shoe are the teacher's context", speakers <= teachers
          and {r["scope_actor"] for r in scoped} == {"teacher"},
          f"teacher holds {sorted(teachers)}")
    check("a denial is held as a denial",
          ("robin", "isa", "mammal", "negative") in held
          and ("robin", "isa", "mammal", "positive") not in held)
    check("nothing is held from a question or a request",
          not any(o in ("red", "color", "tying") for _s, _r, o, _p in held))

    say_line("\n== F. Ledger ==")
    ledger = await db.execute_query(
        "SELECT disposition, count(*) AS n FROM unified.knowledge_updates "
        "WHERE subject_kind = 'language_pattern' GROUP BY disposition", (), fetch_all=True) or []
    by = {r["disposition"]: int(r["n"]) for r in ledger}
    check("every pattern is recorded as new", by.get("new") == len(LESSON), f"{by}")

    say_line("\n== G. Read and say, through memory's view ==")
    for p in patterns:
        readings = dr.read(p.surface)
        said = dr.say(p.meaning)
        say_line(f"  {p.surface!r} -> {[r.meaning.canonical() for r in readings]} -> says {said}")
    check("every taught sentence reads to its meaning",
          all([r.meaning for r in dr.read(p.surface)] == [p.meaning] for p in patterns))
    check("every taught meaning is said back as its sentence",
          all(dr.say(p.meaning) == (p.surface,) for p in patterns))
    untaught = ["This is my hat.", "A robin is a fish.", "My shoe is red."]
    check("an untaught sentence reads to nothing", all(dr.read(s) == () for s in untaught),
          f"{[(s, len(dr.read(s))) for s in untaught]}")
    heard = dr.read("this is my shoe.")
    check("a taught sentence heard without its capital reads loosely, and says so",
          [r.meaning for r in heard] == [dr.read("This is my shoe.")[0].meaning] and heard[0].loose,
          f"{[(r.meaning.canonical(), r.loose) for r in heard]}")

    say_line("\n== H. A fresh warm, from memory alone ==")
    agent._pattern_inventory = None
    await agent.warm_word_classes()
    check("the view rebuilt from memory reads every taught sentence",
          len(agent.pattern_inventory()) == len(LESSON)
          and all(dr.read(p.surface) for p in patterns),
          f"{len(agent.pattern_inventory())} pattern(s) after the warm")

    say_line("\n== I. The same lesson again, from the same source ==")
    evidence_before = [len(us.belief_for_claim(p.claim()).evidence_for) for p in patterns]
    again = await TeachingPass(Lesson("shapes-learn-01"), domain=LESSON_DOMAIN,
                               sample=False).run(learning)
    evidence_after = [len(us.belief_for_claim(p.claim()).evidence_for) for p in patterns]
    check("nothing is learned twice", again.patterns.get("already") == len(LESSON)
          and again.patterns.get("learned") == 0, f"{again.patterns}")
    check("no belief moved", evidence_after == evidence_before,
          f"{evidence_before} -> {evidence_after}")
    rows_again = await db.execute_query(
        "SELECT count(*) AS n FROM memory_hot.memory_hot WHERE tags::jsonb ? $1",
        (dr.PATTERN_TAG,), fetch_one=True)
    check("still one memory per pattern", int(rows_again["n"]) == len(LESSON), f"{rows_again['n']}")

    say_line("\n== J. The same lesson from another source ==")
    other = await TeachingPass(Lesson("another-teacher"), domain=LESSON_DOMAIN,
                               sample=False).run(learning)
    evidence_other = [len(us.belief_for_claim(p.claim()).evidence_for) for p in patterns]
    check("a second source is a second observation of each pattern",
          evidence_other == [n + 1 for n in evidence_after], f"{evidence_after} -> {evidence_other}")
    updated = await db.execute_query(
        "SELECT count(*) AS n FROM unified.knowledge_updates "
        "WHERE subject_kind = 'language_pattern' AND disposition = 'updated'", (), fetch_one=True)
    check("the ledger records the second source as an update", int(updated["n"]) == len(LESSON),
          f"{updated['n']}; report {other.patterns}")

    say_line("\n== K. The reasoner reads what was taught ==")
    from core.reasoning.neural_bridge import DerivedReadingFormalizer
    result = await DerivedReadingFormalizer().formalize("Is a robin a bird?", ["A robin is a bird."])
    say_line(f"  goal={result.statement!r} premises={result.premises} source={result.source}")
    check("a taught question and a taught premise formalize without a model",
          result.succeeded and not result.requires_model and result.statement == "robin_bird"
          and result.premises == ["robin_bird"])
    declined = await DerivedReadingFormalizer().formalize("Is a sparrow a bird?", [])
    check("an untaught question is declined", not declined.succeeded, declined.error or "")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    await EV.verify_database()
    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    print(f"  transcript: {transcript}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    print(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        sys.exit("the sandbox could not be emptied; not running")
    sys.exit(asyncio.run(main()))
