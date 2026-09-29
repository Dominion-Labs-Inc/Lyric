#!/usr/bin/env python3
"""SHAPES-LEARN-02 — constructions found between taught sentences: slots, fillers and the links between them.

Step 2 of `docs/research/SHAPES_CHANGE_MAP.md` (§11a): the Leuven method (Doumen, Beuls & Van Eecke, Royal Society
Open Science 11:231998, 2024). A kindergarten lesson grown from the shoe lesson is taught through the ONE teaching
path, one sentence with its meaning at a time. Each pair is read first; what cannot be read is repaired in the
paper's order, and what the repair creates is held in memory, scored by beliefs, and read and said through.

  A  TEACH      the lesson through the one teaching path; every one of the seven repairs runs where it applies
  B  MEMORY     one memory per construction and per link, each identified exactly; counts by kind agree
  C  BELIEFS    one belief per construction and per link, grounded in its memory, in the English domain
  D  READ       every taught sentence reads to its meaning; sentences never taught, made of held parts, read and
                are said; a filler of another kind, or a shape never seen, is refused; a filler of the slot's kind,
                and a sentence without its final mark, read by supposing it, and the reading writes nothing
  E  KINDS      the kinds of word that emerge from the slots fillers share, none told
  F  WARM       a fresh warm, from memory alone, reads and says the same
  G  AGAIN      the same lesson again from the same source: understood, nothing learned, and no construction
                counts the same pair twice; only a generalization reading a pair it never read before moves
  H  WITNESS    the lesson from another source: communicative success rises, and nothing is lost; the
                constructions that read it are observed for, a holophrase that competed with a generalization is
                observed against and loses ground, and a construction that fell below belief is revived by the pair
                that needs it
  I  LEDGER     every construction and link recorded as new, with the repair that made it
  J  DOMAIN     English is judged by what memory holds of it
  K  BASELINE   what the written reader of SHAPES-BASELINE-01 makes of the same sentences
  L  MAIN       the main model's store is untouched

Runs in the SANDBOX (`torinai_dev`), emptied first by `scripts/reset_dev_store.py`. The substrate is started
before anything is taught, so the domain reactions run as they would.

Run: ./venv_torin/bin/python3 experiments/SHAPES-LEARN-02/experiment.py
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from core.semantics.derived_reader import Meaning, MeaningFact as F  # noqa: E402

LESSON_DOMAIN = "shapes_learn_02"


def _tell(*facts):
    return Meaning("tell", tuple(F(*f) for f in facts))


def _mine(thing):
    return _tell(("instance_of", "?shown", thing), ("owned_by", "?shown", "?speaker"))


def _it(colour):
    return _tell(("has_property", "?previous", colour))


def _the(thing, colour):
    return _tell(("instance_of", "?shown", thing), ("has_property", "?shown", colour))


def _is_the(thing, colour):
    return Meaning("ask", (F("instance_of", "?shown", thing), F("has_property", "?shown", colour)))


_WAVE = (F("instance_of", "?e", "waving"), F("done_by", "?e", "?listener"))
_SING = (F("instance_of", "?e", "singing"), F("done_by", "?e", "?listener"), F("done_to", "?e", "?s"),
         F("instance_of", "?s", "song"))

#: (sentence, meaning, the repair the paper would use for it here)
LESSON = [
    ("This is my shoe.", _mine("shoe"), "holophrase"),
    ("This is my hat.", _mine("hat"), "substitution"),
    ("This is my cup.", _mine("cup"), "item_based_lexical"),
    ("This is my ball.", _mine("ball"), "item_based_lexical"),
    ("It is red.", _it("red"), "holophrase"),
    ("It is blue.", _it("blue"), "substitution"),
    ("It is green.", _it("green"), "item_based_lexical"),
    ("It is black.", _it("black"), "item_based_lexical"),
    ("The shoe is red.", _the("shoe", "red"), "lexical_item_based"),
    ("The hat is blue.", _the("hat", "blue"), "add_links"),
    ("The cup is green.", _the("cup", "green"), "add_links"),
    ("The ball is black.", _the("ball", "black"), "add_links"),
    ("Is the shoe red?", _is_the("shoe", "red"), "lexical_item_based"),
    ("Is the hat blue?", _is_the("hat", "blue"), "add_links"),
    ("Is the cup black?", _is_the("cup", "black"), "add_links"),
    ("Wave bye bye.", Meaning("request", _WAVE), "holophrase"),
    ("Wave bye bye to grandma.", Meaning("request", _WAVE + (F("done_to", "?e", "grandma"),)), "addition"),
    ("Wave bye bye to grandpa.", Meaning("request", _WAVE + (F("done_to", "?e", "grandpa"),)),
     "item_based_lexical"),
    ("Sing the happy song.", Meaning("request", _SING + (F("has_property", "?s", "happy"),)), "holophrase"),
    ("Sing the song.", Meaning("request", _SING), "deletion"),
    ("Sing the sad song.", Meaning("request", _SING + (F("has_property", "?s", "sad"),)), "item_based_lexical"),
    ("A robin is a bird.", _tell(("isa", "robin", "bird")), "holophrase"),
    ("A sparrow is a bird.", _tell(("isa", "sparrow", "bird")), "substitution"),
    ("A cat is a mammal.", _tell(("isa", "cat", "mammal")), "holophrase"),
    ("A dog is a mammal.", _tell(("isa", "dog", "mammal")), "substitution"),
]

#: Never taught, made only of held parts: each filler has been seen in its slot.
NEW = [("The shoe is blue.", _the("shoe", "blue")), ("The ball is red.", _the("ball", "red")),
       ("The cup is black.", _the("cup", "black")), ("Is the hat red?", _is_the("hat", "red")),
       ("Is the shoe blue?", _is_the("shoe", "blue"))]

#: Refused: a filler never seen in that slot, or a shape never seen at all.
UNSEEN = ["This is my red.", "Blue is the shoe.", "My shoe is red.", "Sing the happy song to grandma."]

#: Read by supposing what no taught pair showed: `ball` fills the slot's kind though no pair linked it there, and a
#: sentence heard without its final mark is read loosely. (sentence, meaning, what was supposed)
SUPPOSED = [("Is the ball red?", _is_the("ball", "red"), "kind"), ("The shoe is blue", _the("shoe", "blue"), "loose")]

EV = RunRecord(
    "SHAPES-LEARN-02",
    claim=("Taught one sentence with its meaning at a time, the substrate finds constructions between them by the "
           "Leuven method -- slots, fillers and the links between them -- holds them in memory scored by "
           "beliefs, and reads and says sentences it was never taught, made of parts it has seen, while "
           "refusing what it has not."),
    hypothesis=("A repair that does not run where it applies, or runs out of order; a construction or link not "
                "held in memory, or not scored by a grounded belief; a taught sentence that does not read; a new "
                "combination not read or said; a pairing or shape never seen that reads; word kinds mixing things "
                "and colours; a re-teach that learns or moves anything; a second source not moving the chosen "
                "constructions, or not moving a competing holophrase down; a warm that reads differently; or any "
                "write to the main store would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class Lesson:
    """The kindergarten lesson as a teaching source: each sentence with what it means."""

    name = "SHAPES-LEARN-02 lesson"
    curated = True
    quality = 0.9

    def __init__(self, source_id: str):
        self.source_id = source_id

    def provenance(self):
        from core.learning.teaching_sources import _provenance
        return _provenance("teaching", self.source_id)

    def records(self):
        from core.learning.teaching import TaughtRecord
        for sentence, meaning, _repair in LESSON:
            yield TaughtRecord(subject="", relation="", obj="", quality=self.quality,
                               sentence=sentence, meaning=meaning)


async def main_store_rows() -> int:
    """Rows in the main model's store, counted over its own connection."""
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="torinai_db")
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
    check("the run is in the sandbox", where["d"] == "torinai_dev", f"connected to {where['d']}")
    if where["d"] != "torinai_dev":
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


def _counted(view):
    return {"holophrase": len(view.holophrases()), "item_based": len(view.item_based()),
            "lexical": len(view.lexicals()), "link": len(view.links())}


async def _run(db, main_before: int) -> int:
    from core.learning import get_learning_authority
    from core.learning.teaching import TeachingPass
    from core.memory import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr
    agent = await get_memory_agent()
    await agent.warm_word_classes()
    learning = get_learning_authority()
    us = get_uncertainty_system()

    say_line("== A. The lesson, through the one teaching path ==")
    report = await TeachingPass(Lesson("shapes-learn-02"), domain=LESSON_DOMAIN, sample=False).run(learning)
    for line in report.lines():
        say_line(f"    {line}")
    ran = {k[len("repair_"):]: v for k, v in report.patterns.items() if k.startswith("repair_")}
    wanted = dict(Counter(r for _, _, r in LESSON))
    check("every pair is read or repaired, none refused", report.patterns.get("refused") == 0
          and report.patterns.get("total") == len(LESSON), f"{report.patterns}")
    check("each of the seven repairs runs, as often as the paper's order says it applies",
          ran == wanted, f"ran {ran}; expected {wanted}")
    check("communicative success on first hearing: the pairs understood by adding links only",
          report.patterns.get("understood") == wanted["add_links"],
          f"{report.patterns.get('understood')}/{len(LESSON)}")

    say_line("\n== B. Memory ==")
    rows = await db.execute_query(
        "SELECT memory_id, content, metadata FROM memory_hot.memory_hot WHERE tags::jsonb ? $1",
        (dr.PATTERN_TAG,), fetch_all=True) or []
    metas = [r["metadata"] if isinstance(r["metadata"], dict) else _json.loads(r["metadata"] or "{}") for r in rows]
    by_kind = Counter(m.get("construction") for m in metas)
    keys = [m.get("pattern_key") for m in metas]
    view = agent.pattern_inventory()
    counted = _counted(view)
    say_line(f"    memory holds {dict(by_kind)}; the view holds {counted}")
    check("one memory per construction and per link, none merged, each keyed exactly",
          len(rows) == len(set(keys)) == len(view) and all(keys), f"{len(rows)} memories, {len(set(keys))} keys")
    check("memory and the view agree, kind by kind",
          by_kind.get("holophrase", 0) == counted["holophrase"] and by_kind.get("item_based", 0) ==
          counted["item_based"] and by_kind.get("lexical", 0) == counted["lexical"]
          and by_kind.get("link", 0) == counted["link"], f"{dict(by_kind)} / {counted}")
    check("what was learned is what the report says",
          report.patterns.get("learned") == counted["holophrase"] + counted["item_based"] + counted["lexical"]
          and report.patterns.get("linked") == counted["link"],
          f"learned {report.patterns.get('learned')}, linked {report.patterns.get('linked')}")
    for p in view.item_based():
        say_line(f"      item-based  {p.surface!r:28} {p.meaning.canonical()}")
    for p in view.holophrases():
        say_line(f"      holophrase  {p.surface!r}")
    say_line(f"      lexical     {sorted(x.surface for x in view.lexicals())}")

    say_line("\n== C. Beliefs ==")
    memory_of = {m.get("pattern_key"): r["memory_id"] for m, r in zip(metas, rows)}
    beliefs = [(item, us.belief_for_claim(item.claim())) for item in view.items()]
    check("one belief per construction and per link", all(b is not None for _, b in beliefs),
          f"{sum(1 for _, b in beliefs if b is not None)}/{len(beliefs)}")
    check("each belief is grounded in its own memory", all(
        b is not None and b.memory_id == memory_of.get(item.key) for item, b in beliefs))
    check("each is in the English domain", all(b is not None and b.domain == dr.ENGLISH_DOMAIN for _, b in beliefs))

    say_line("\n== D. Reading and saying ==")
    taught_read = [(s, [r.meaning.canonical() for r in dr.read(s)]) for s, _, _ in LESSON]
    check("every taught sentence reads to its meaning",
          all(got and got[0] == m.canonical() for (s, got), (_, m, _) in zip(taught_read, LESSON)),
          f"{[s for (s, got), (_, m, _) in zip(taught_read, LESSON) if not got or got[0] != m.canonical()]}")
    for sentence, meaning in NEW:
        got = dr.read(sentence)
        said = dr.say(meaning)
        say_line(f"    new  {sentence!r} -> {[r.meaning.canonical() for r in got]}; said {said}")
    check("sentences never taught, made of held parts, read to their meaning",
          all([r.meaning.canonical() for r in dr.read(s)][:1] == [m.canonical()] for s, m in NEW))
    check("and their meanings are said as those sentences", all(dr.say(m)[:1] == (s,) for s, m in NEW))
    unseen = {s: len(dr.read(s)) for s in UNSEEN}
    say_line(f"    unseen {unseen}")
    check("a filler of another kind, and a shape never seen, read to nothing", not any(unseen.values()))
    size = len(view)
    supposed = {s: dr.read(s) for s, _, _ in SUPPOSED}
    for s, m, how in SUPPOSED:
        got = supposed[s]
        say_line(f"    supposed {s!r} -> {[r.meaning.canonical() for r in got]} "
                 f"(links proposed {[len(r.proposed) for r in got]}, loose {[r.loose for r in got]})")
    check("a filler of the slot's kind, and a sentence without its final mark, read to their meaning",
          all([r.meaning.canonical() for r in supposed[s]][:1] == [m.canonical()] for s, m, _ in SUPPOSED))
    check("each says what it supposed",
          all(supposed[s] and (bool(supposed[s][0].proposed) if how == "kind" else supposed[s][0].loose)
              for s, _, how in SUPPOSED))
    check("and reading wrote nothing", len(view) == size, f"{size} -> {len(view)}")

    say_line("\n== E. Kinds of word, none told ==")
    kinds = [sorted(x.surface for x in kind) for kind in view.word_kinds()]
    for kind in kinds:
        say_line(f"    {kind}")
    things, colours = {"shoe", "hat", "cup", "ball"}, {"red", "blue", "green", "black"}
    check("the things are one kind and the colours another",
          sorted(things) in kinds and sorted(colours) in kinds, f"{len(kinds)} kinds")
    check("no kind mixes them", not any(set(k) & things and set(k) & colours for k in kinds))

    say_line("\n== F. A fresh warm, from memory alone ==")
    agent._pattern_inventory = None
    agent._word_classes_warm = False
    rewarmed = await agent.language_view()
    check("the view rebuilt from memory holds the same", _counted(rewarmed) == counted, f"{_counted(rewarmed)}")
    check("and reads and says the same", all(
        [r.meaning.canonical() for r in dr.read(s)][:1] == [m.canonical()] and dr.say(m)[:1] == (s,)
        for s, m in NEW))

    say_line("\n== G. The same lesson again, from the same source ==")
    before = {item.key: (b.posterior_probability, len(b.evidence_for), len(b.evidence_against))
              for item, b in ((i, us.belief_for_claim(i.claim())) for i in rewarmed.items()) if b is not None}
    again = await TeachingPass(Lesson("shapes-learn-02"), domain=LESSON_DOMAIN, sample=False).run(learning)
    items = agent.pattern_inventory().items()
    after = {item.key: (b.posterior_probability, len(b.evidence_for), len(b.evidence_against))
             for item, b in ((i, us.belief_for_claim(i.claim())) for i in items) if b is not None}
    check("every pair understood, nothing learned", again.patterns.get("understood") == len(LESSON)
          and again.patterns.get("learned") == 0 and again.patterns.get("linked") == 0, f"{again.patterns}")
    witnesses = [[str(e.get("observation")) for e in (*b.evidence_for, *b.evidence_against) if isinstance(e, dict)]
                 for b in (us.belief_for_claim(i.claim()) for i in items) if b is not None]
    check("no construction or link counts the same pair from the same source twice",
          all(len(w) == len(set(w)) for w in witnesses))
    moved = [i for i in items if i.key in before and after.get(i.key) != before[i.key]]
    say_line(f"    moved: {sorted(getattr(i, 'surface', '') or i.claim()[:40] for i in moved)}")
    check("what moved is a generalization reading a pair a holophrase read first; no holophrase moved",
          not any(isinstance(i, dr.Pattern) and not i.slots for i in moved), f"{len(moved)} moved")

    say_line("\n== H. The lesson from another source ==")
    shoe = next(p for p in agent.pattern_inventory().holophrases() if p.surface == "This is my shoe.")
    shoe_before = us.belief_for_claim(shoe.claim())
    shoe_before = (shoe_before.posterior_probability, len(shoe_before.evidence_against))
    other = await TeachingPass(Lesson("another-teacher"), domain=LESSON_DOMAIN, sample=False).run(learning)
    check("communicative success rises with a second source, and nothing new is needed",
          other.patterns.get("understood") > report.patterns.get("understood")
          and other.patterns.get("learned") == 0 and other.patterns.get("linked") == 0,
          f"{other.patterns.get('understood')}/{len(LESSON)} understood as they came "
          f"(first hearing {report.patterns.get('understood')}/{len(LESSON)}); {other.patterns}")
    revived = await db.execute_query(
        "SELECT detail FROM unified.knowledge_updates WHERE detail LIKE 'revived:%' ORDER BY occurred_at",
        (), fetch_all=True) or []
    for r in revived:
        say_line(f"    {r['detail']}")
    check("every pair not understood as it came was a construction below belief, revived by that pair",
          len(LESSON) - other.patterns.get("understood") == sum(
              v for k, v in other.patterns.items() if k.startswith("repair_"))
          and (other.patterns.get("understood") == len(LESSON) or len(revived) > 0),
          f"{len(revived)} revived")
    check("after it, every taught sentence still reads to its meaning",
          all([r.meaning.canonical() for r in dr.read(s)][:1] == [m.canonical()] for s, m, _ in LESSON))
    moved = {item.key for item in agent.pattern_inventory().items()
             if (b := us.belief_for_claim(item.claim())) is not None and item.key in after
             and len(b.evidence_for) > after[item.key][1]}
    check("the constructions that read it are observed once more", len(moved) > 0, f"{len(moved)} moved up")
    shoe_after = us.belief_for_claim(shoe.claim())
    check("the holophrase that competed with a generalization is observed against and loses ground",
          len(shoe_after.evidence_against) > shoe_before[1] and shoe_after.posterior_probability < shoe_before[0],
          f"{shoe_before[0]:.4f} -> {shoe_after.posterior_probability:.4f}, "
          f"{len(shoe_after.evidence_against)} against")
    first = dr.read("This is my shoe.")[0]
    check("the generalization now reads the sentence first", first.pattern.slots != (),
          f"{first.pattern.surface!r} + {[c.surface for c in first.constructions[1:]]}")

    say_line("\n== I. Ledger ==")
    ledger = await db.execute_query(
        "SELECT subject_kind, disposition, count(*) AS n FROM unified.knowledge_updates "
        "WHERE subject_kind IN ('language_pattern', 'language_link') GROUP BY 1, 2", (), fetch_all=True) or []
    by = {(r["subject_kind"], r["disposition"]): int(r["n"]) for r in ledger}
    say_line(f"    {by}")
    check("every construction and link is recorded as new",
          by.get(("language_pattern", "new")) == report.patterns.get("learned")
          and by.get(("language_link", "new")) == report.patterns.get("linked"))
    named = await db.execute_query(
        "SELECT detail FROM unified.knowledge_updates WHERE disposition = 'new' "
        "AND subject_kind IN ('language_pattern', 'language_link')", (), fetch_all=True) or []
    check("each with the repair that made it", all(
        any(str(r["detail"]).startswith(name) for name in dr.REPAIR_NAMES.values()) for r in named))

    say_line("\n== J. The English domain ==")
    from core.domain.domain_types import coverage_from_counts
    udm_items = await agent.taught_patterns()
    patterns = [i for i in udm_items if isinstance(i, dr.Pattern)]
    expected_maturity = coverage_from_counts(
        sum(1 for i in udm_items if not isinstance(i, dr.Link)),
        sum(len(p.meaning.facts) for p in patterns) + sum(1 for i in udm_items if isinstance(i, dr.Link)),
        len({f.relation for p in patterns for f in p.meaning.facts}))
    maturity = None
    for _ in range(120):
        row = await db.execute_query("SELECT (metadata->>'maturity_score')::float AS m FROM unified.domains "
                                     "WHERE domain_id = $1", (dr.ENGLISH_DOMAIN,), fetch_one=True)
        maturity = row["m"] if row else None
        if maturity is not None and abs(maturity - expected_maturity) < 1e-4:
            break
        await asyncio.sleep(1.0)
    check("English is judged by its constructions and links", maturity is not None
          and abs(maturity - expected_maturity) < 1e-4, f"maturity {maturity} (expected {expected_maturity:.4f})")

    say_line("\n== K. The written reader of SHAPES-BASELINE-01, on the same sentences ==")
    from core.semantics.sentence_reader import SentenceReader
    reader = SentenceReader()

    def written(sentence: str) -> bool:
        if sentence.rstrip().endswith("?"):
            return reader._parse_goal(sentence) is not None
        return bool(reader.read_all(sentence))

    sets = {"taught": [s for s, _, _ in LESSON], "never taught": [s for s, _ in NEW]}
    for label, sentences in sets.items():
        learned = sum(1 for s in sentences if dr.read(s))
        by_code = sum(1 for s in sentences if written(s))
        say_line(f"    {label}: learned constructions read {learned}/{len(sentences)} to their taught meaning; "
                 f"the written reader gives some reading of {by_code}/{len(sentences)}")
        EV.metric(f"{label}: learned constructions read", f"{learned}/{len(sentences)}")
        EV.metric(f"{label}: written reader gives a reading", f"{by_code}/{len(sentences)}")

    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")
    for name, value in counted.items():
        EV.metric(f"constructions: {name}", value)
    EV.metric("communicative success, first hearing", f"{report.patterns.get('understood')}/{len(LESSON)}")
    EV.metric("communicative success, second source", f"{other.patterns.get('understood')}/{len(LESSON)}")
    EV.metric("constructions revived", len(revived))

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-LEARN-02 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
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
