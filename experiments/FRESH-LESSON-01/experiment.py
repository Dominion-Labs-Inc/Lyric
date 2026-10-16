#!/usr/bin/env python3
"""FRESH-LESSON-01 — what Lyric learns from a lesson no earlier experiment taught or tested.

SENSE-01, COMPREHENSION-01 and SYSTEM-LEARNING-01 have been run and fixed against since the start; passing them now
says little. This teaches one new lesson (`lesson.json`, written and frozen before the first run), on a sandbox
emptied first and given English by the 30 lessons (which teach how English says things, and no facts), and asks:

  A  LEARNING      the lesson is taught through the one path, none refused; every fact it states is in the concept
                   graph and moved a belief; each new word is a memory found by meaning, held in the lesson's
                   domain, and has the class its use shows (a noun).
  B  READING       sentences never taught, in shapes the 30 lessons teach, with the lesson's new words, are read
                   with the meaning written here; and two shapes the 30 lessons never use ("X lives in Y",
                   "X belongs to Y"), not read before the lesson, are read in sentences the lesson never had.
  C  MEANING       questions through the conversation, answered from what was taught: kinds, what a kind can do
                   passed down to its members, places, what a thing is made of, who owns what, and no answer made
                   up where nothing was taught. Two ask in shapes nobody taught ("Where does a snorf live?").
  D  RESTART       a process started afterwards, holding nothing of this run, reads the new shapes the same way.
  E  AGAIN         the lesson taught a second time adds nothing and moves no belief.
  F  TOLD OTHERWISE  a weaker source saying the opposite of one fact moves its belief down.
  G  the main model is untouched.

Every expected meaning and answer is written here before the run.

Run (empties the sandbox first):
    ./venv_lyric/bin/python3 experiments/FRESH-LESSON-01/experiment.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

_spec = importlib.util.spec_from_file_location("sense_01", ROOT / "experiments" / "SENSE-01" / "experiment.py")
_sense = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sense)

LESSONS = sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json"))
#: The lessons FRESH-LESSON-01 to -03 were written against and frozen with, english_01-30. english_31, written after,
#: says "is kept in" and "sleeps in" as happenings (events), where these lessons say them as where a thing is: taught
#: both, the reader holds two meanings for one shape and rightly reads neither (FRESH-LESSON-03, second run).
FROZEN_WITH = [path for path in LESSONS if path.name <= "english_30.json"]


def tell(*facts):
    return {"act": "tell", "facts": [list(f) for f in facts], "asked": []}


def ask(facts, asked=()):
    return {"act": "ask", "facts": [list(f) for f in facts], "asked": list(asked)}


#: Never taught, in shapes the 30 lessons teach, with the lesson's words.
IN_TAUGHT_SHAPES = [
    ("A glim is not a fish.", tell(("isa", "glim", "fish", False))),
    ("Is a dax a bird?", ask([("isa", "dax", "bird", True)])),
    ("What is a blicket?", ask([("isa", "blicket", "?x", True)], ["?x"])),
    ("Where is the blicket?", ask([("located_in", "blicket", "?x", True)], ["?x"])),
    ("Nella has a blicket.", tell(("owns", "nella", "blicket", True))),
    ("Daxes are small.", tell(("has_property", "dax", "small", True))),
    ("The wug is in the box.", tell(("located_in", "wug", "box", True))),
    ("A fep is not a tool.", tell(("isa", "fep", "tool", False))),
]

#: The two shapes the 30 lessons never use, in sentences the lesson never had.
IN_NEW_SHAPES = {
    "lives in": [
        ("A glim lives in a tree.", tell(("located_in", "glim", "tree", True))),
        ("A vora lives in a house.", tell(("located_in", "vora", "house", True))),
        ("A wug lives in a box.", tell(("located_in", "wug", "box", True))),
    ],
    "belongs to": [
        ("The ball belongs to Nella.", tell(("owned_by", "ball", "nella", True))),
        ("The wug belongs to Tom.", tell(("owned_by", "wug", "tom", True))),
        ("The fep belongs to Rex.", tell(("owned_by", "fep", "rex", True))),
    ],
}

#: Asked through the conversation after the lesson: (question, what an answer from the lesson does, test on it).
QUESTIONS = [
    ("What is a wug?", "says a wug is a bird", lambda r: "bird" in r),
    ("Is a wug a bird?", "yes", lambda r: r.startswith("yes")),
    ("Is a wug a fish?", "no", lambda r: r.startswith("no")),
    ("Is a wug an animal?", "yes: a wug is a bird, a bird an animal", lambda r: r.startswith("yes")),
    ("Can a wug fly?", "yes: birds can fly", lambda r: r.startswith("yes")),
    ("Can a dax swim?", "yes: fish can swim", lambda r: r.startswith("yes")),
    ("Where is the blicket?", "in the box", lambda r: "box" in r),
    ("What is a blicket made of?", "wood", lambda r: "wood" in r),
    ("Is Nella a person?", "yes: Nella is a girl, a girl a person", lambda r: r.startswith("yes")),
    ("Who owns the wug?", "Nella", lambda r: "nella" in r),
    ("Is a blicket big?", "not yes: nothing taught says so", lambda r: not r.startswith("yes")),
    ("Where does a snorf live?", "in a house (a question shape never taught)", lambda r: "house" in r),
    ("Who does the blicket belong to?", "Nella (a question shape never taught)", lambda r: "nella" in r),
]

def say(line=""):
    print(line, flush=True)


#: The run record of the run under way (`run`).
EV = None


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def canonical(meaning) -> str:
    from core.semantics.derived_reader import Meaning
    return Meaning.from_dict(meaning).canonical()


def lesson_facts(lesson):
    """`(subject, relation, object, true)` for every fact the lesson states between named things."""
    out = []
    for record in json.loads(lesson.read_text())["records"]:
        for relation, subject, obj, positive in record["meaning"]["facts"]:
            if not str(subject).startswith("?") and not str(obj).startswith("?"):
                out.append((subject, relation, obj, positive))
    return out


async def teach(path, label, domain):
    from core.learning import get_learning_authority
    from core.learning.teaching import TeachingPass
    from core.learning.teaching_sources import LessonSource
    source = LessonSource(str(path))
    total = len(list(source.records()))
    report = await TeachingPass(source, domain=domain, sample=False).run(get_learning_authority())
    say(f"    {label}: {report.patterns} meanings {report.meanings} in {report.seconds:.0f} s")
    return report, total


def posterior(claim):
    from core.learning import get_learning_authority
    belief = get_learning_authority().belief_for_claim(claim)
    return None if belief is None else float(getattr(belief, "posterior_probability", 0.0))


def answered(test, reply: str) -> bool:
    """The reply passes the question's test as an answer: a memory recited ("I remember: A quib is kept in a
    room.") is recall, not the question understood. Added after FRESH-LESSON-03's second run passed two questions so,
    as QUESTION-FORMS-02 already refused them."""
    reply = reply.strip().lower()
    return not reply.startswith("i remember") and test(reply)


async def asking(conversation, question):
    """The reply to a question through the conversation, or what went wrong saying it: a fault in the reply is a
    finding of the run, recorded as a failed answer, not the end of it."""
    try:
        understanding = await conversation.understand(question, look_up=False)
        return type(conversation).say(understanding) or ""
    except Exception as error:
        return f"CRASH: {type(error).__name__}: {error}"


async def run(material) -> int:
    """One fresh lesson, taught and tested: `material` names the lesson, its contradiction, the words it brings, the
    sentences to read and the questions to ask, each with what is expected, all written before the run."""
    global EV
    EV = RunRecord(material["name"], claim=material["claim"], hypothesis=material["hypothesis"])
    LESSON, CONTRADICTION, DOMAIN = material["lesson"], material["contradiction"], material["domain"]
    NEW_WORDS, CLAIM = material["new_words"], material["contested"]
    IN_TAUGHT_SHAPES, IN_NEW_SHAPES = material["in_taught_shapes"], material["in_new_shapes"]
    QUESTIONS = material["questions"]
    started = time.time()
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")], capture_output=True,
                           text=True, cwd=str(ROOT))
    say(reset.stdout.strip())
    main_before = await _sense.main_store_rows()
    system, coord = await boot()
    d = db()
    where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox, emptied first", where["d"] == "lyric_dev" and reset.returncode == 0,
          f"connected to {where['d']}; reset exit {reset.returncode}")
    try:
        from core.memory import get_memory_agent
        agent = await get_memory_agent()

        say(f"\n== English first: the {len(FROZEN_WITH)} lessons (how English says things; no facts) ==")
        refused = {}
        for path in FROZEN_WITH:
            report, total = await teach(path, path.name, DOMAIN)
            if report.patterns.get("refused") or report.patterns.get("total") != total:
                refused[path.name] = report.patterns
        check(f"the {len(FROZEN_WITH)} lessons are learned, none refused", not refused,
              f"{refused}" if refused else f"{FROZEN_WITH[-1].name} the last")
        await agent.language_view()
        before = {s: _sense._taken(s) for shape in IN_NEW_SHAPES.values() for s, _ in shape}
        already = [s for shape in IN_NEW_SHAPES.values() for s, m in shape if before[s] == canonical(m)]
        check("the two new shapes are not read before the lesson", not already,
              f"read already: {already}" if already else f"{list(before.values())}")

        say("\n== A. Learning: the lesson, through the one teaching path ==")
        report, total = await teach(LESSON, "the lesson", DOMAIN)
        check("every sentence of the lesson is learned, none refused",
              report.patterns.get("refused") == 0 and report.patterns.get("total") == total, f"{report.patterns}")
        facts = lesson_facts(LESSON)
        missing, unmoved = [], []
        for subject, relation, obj, positive in facts:
            row = await d.execute_query(
                "SELECT count(*) AS n FROM unified.concept_relations cr "
                "JOIN unified.concepts s ON cr.source_concept_id = s.concept_id "
                "JOIN unified.concepts o ON cr.target_concept_id = o.concept_id "
                "WHERE lower(s.name) = $1 AND lower(o.name) = $2 AND replace(cr.relation, ' ', '_') = $3",
                (subject, obj, relation), fetch_one=True)
            if not row or not int(row["n"]):
                missing.append(f"{subject} {relation} {obj}")
            if positive:
                p = posterior(f"{subject} {relation} {obj}")
                if p is None or p <= 0.5:
                    unmoved.append((f"{subject} {relation} {obj}", p))
        check("every fact the lesson states is in the concept graph", not missing,
              f"{len(facts) - len(missing)} of {len(facts)}; missing: {missing}")
        check("every fact it states as true moved a belief above even", not unmoved,
              f"{len(unmoved)} not: {unmoved}" if unmoved else f"{sum(1 for f in facts if f[3])} beliefs")
        negatives = {f"{s} {r} {o}": posterior(f"{s} {r} {o}") for s, r, o, positive in facts if not positive}
        EV.metric("beliefs in what the lesson denies", negatives)
        unfound, outside, unclassed = [], [], {}
        for word in NEW_WORDS:
            found = await agent.search_memories(query_text=word, limit=10) or []
            if not any(word in json.dumps(getattr(m, "content", {})).lower() for m in found):
                unfound.append(word)
            row = await d.execute_query(
                "SELECT count(*) AS n FROM unified.concept_domains cd JOIN unified.concepts c "
                "ON cd.concept_id = c.concept_id WHERE lower(c.name) = $1 AND cd.domain = $2",
                (word, DOMAIN), fetch_one=True)
            if not row or not int(row["n"]):
                outside.append(word)
            if agent.word_class(word) != "NOUN":
                unclassed[word] = agent.word_classes(word)
        check("each new word is a memory found by meaning", not unfound, f"not found: {unfound}" if unfound else "")
        check("each new word is held in the lesson's domain", not outside, f"not held: {outside}" if outside else "")
        check("each new word has the class its use shows: a noun", not unclassed,
              f"{unclassed}" if unclassed else "")

        say("\n== B. Reading: sentences never taught ==")
        view_size = len(await agent.language_view())
        say(f"    {view_size} constructions and links in the view")
        wrong = []
        for sentence, meaning in IN_TAUGHT_SHAPES:
            got = await _sense._listened(sentence)
            if got != canonical(meaning):
                wrong.append((sentence, got))
            say(f"    {sentence!r:30s} {'right' if got == canonical(meaning) else 'WRONG: ' + str(got)}")
        check("never-taught sentences in shapes the lessons teach are read as written here", not wrong,
              f"{len(IN_TAUGHT_SHAPES) - len(wrong)} of {len(IN_TAUGHT_SHAPES)}")
        after = {}
        for shape, items in IN_NEW_SHAPES.items():
            wrong = []
            for sentence, meaning in items:
                got = await _sense._listened(sentence)
                after[sentence] = got
                if got != canonical(meaning):
                    wrong.append((sentence, got))
                say(f"    {sentence!r:30s} {'right' if got == canonical(meaning) else 'WRONG: ' + str(got)}")
            check(f"the new shape '{shape}', learned from three sentences, reads three it never had", not wrong,
                  f"{len(items) - len(wrong)} of {len(items)}")

        say("\n== C. Meaning: questions through the conversation ==")
        conversation = coord.conversation(material["name"])
        answers = []
        for question, expected, test in QUESTIONS:
            reply = await asking(conversation, question)
            answers.append({"asked": question, "reply": reply})
            say(f"    > {question}\n    < {reply}")
            check(f"{question!r}: {expected}", answered(test, reply), reply[:160])
        EV.metric("answers", answers)

        say("\n== D. Restart: a new process reads from memory alone ==")
        read = [s for shape in IN_NEW_SHAPES.values() for s, _ in shape] + [s for s, _ in IN_TAUGHT_SHAPES]
        fresh = subprocess.run([sys.executable, str(HERE / "restart_read.py")], input=json.dumps(read),
                               capture_output=True, text=True, cwd=str(ROOT))
        restarted = json.loads(fresh.stdout.strip().splitlines()[-1]) if fresh.returncode == 0 else {}
        expected = {s: canonical(m) for shape in IN_NEW_SHAPES.values() for s, m in shape}
        expected.update({s: canonical(m) for s, m in IN_TAUGHT_SHAPES})
        lost = [s for s in read if restarted.get(s) != expected[s] and after.get(s, expected[s]) == expected[s]]
        check("a new process reads every sentence it read right before, the same way", fresh.returncode == 0 and not lost,
              f"exit {fresh.returncode}; lost: {lost}" + (f"; {fresh.stderr[-300:]}" if fresh.returncode else ""))

        say("\n== E. Again: the same lesson a second time ==")
        claim = CLAIM
        p_before = posterior(claim)
        report, total = await teach(LESSON, "the lesson again", DOMAIN)
        p_again = posterior(claim)
        check("taught again, no sentence is learned anew", report.patterns.get("learned", 0) == 0
              and report.patterns.get("refused", 0) == 0, f"{report.patterns}")
        check("taught again, the belief does not move", p_before is not None and p_again is not None
              and abs(p_again - p_before) < 1e-9, f"{claim}: {p_before} then {p_again}")

        say("\n== F. Told otherwise: a weaker source denies one fact ==")
        report, total = await teach(CONTRADICTION, "the contradiction", DOMAIN)
        p_after = posterior(claim)
        check("a weaker source saying the opposite moves the belief down", p_after is not None and p_again is not None
              and p_after < p_again, f"{claim}: {p_again} then {p_after}")
        question, expected, test = material["after_contradiction"]
        reply = await asking(conversation, question)
        say(f"    > {question}\n    < {reply}")
        check(f"asked again after it, {question!r}: {expected}", answered(test, reply), reply[:160])
        # Added after FRESH-LESSON-02's first run, whose reply opened "Yes." and went on "No. A zanth is not a cat.".
        check("and the reply does not deny it as well",
              not any(line.strip().lower().startswith("no") for line in reply.splitlines()), reply[:160])
    finally:
        await shutdown(system)
    main_after = await _sense.main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          _sense.main_store_change(main_before, main_after))
    passed = sum(1 for c in EV.checks if c.passed)
    say(f"\n==== {material['name']}: {passed}/{len(EV.checks)} checks passed ({time.time() - started:.0f} s) ====")
    await EV.verify_database()
    say(f"  run record: {EV.write()}")
    return 0 if passed == len(EV.checks) else 1


MATERIAL_CLAIM = dict(
    claim=("Taught one lesson no experiment has taught or tested, Lyric holds every fact it states as a fact, a belief "
           "and a memory; reads sentences it was never taught, in shapes it already had and in two it learned from "
           "three sentences each; answers questions from what it was taught, passing what a kind can do down to its "
           "members and making nothing up; keeps it across a restart; does not grow surer from being told again; and "
           "moves a belief when told otherwise."),
    hypothesis=("Any fact refused, missing from the graph or moving no belief; any sentence read otherwise than written "
                "here; a new shape read before it was taught or not read after; a wrong or made-up answer; a reading "
                "lost on restart; a belief moved by the same lesson again or not moved by its contradiction; or a "
                "write to the main store, each shows here."))

#: FRESH-LESSON-01's material, written before its first run. Run 2 (2026-10-04) added the check of the answer asked
#: again after the contradiction, which run 1 only recorded.
MATERIAL = dict(
    name="FRESH-LESSON-01", lesson=HERE / "lesson.json", contradiction=HERE / "contradiction.json",
    domain="fresh_lesson_01", contested="wug isa bird",
    new_words=["wug", "dax", "blicket", "fep", "snorf", "toma", "pell", "glim", "vora"],
    in_taught_shapes=IN_TAUGHT_SHAPES, in_new_shapes=IN_NEW_SHAPES, questions=QUESTIONS,
    after_contradiction=("Is a wug a bird?", "still yes: the belief stands at 0.97",
                         lambda r: r.startswith("yes")),
    **MATERIAL_CLAIM)


if __name__ == "__main__":
    sys.exit(asyncio.run(run(MATERIAL)))
