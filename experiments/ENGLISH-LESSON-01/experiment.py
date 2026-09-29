#!/usr/bin/env python3
"""ENGLISH-LESSON-01 — the substrate's first lesson in American English, on an empty store.

The lesson is a university-published preschool lesson plan: Illinois Early Learning Project
(University of Illinois at Urbana-Champaign), "Language Arts Lesson Addressing Benchmark
1.C.ECa — Describe familiar people, places, things, and events"
(https://illinoisearlylearning.org/ields/ields-plans/adapting-1ceca/). In it the teacher
describes her shoe to the class; afterwards she asks the children questions.

The substrate is taught the teacher's own sentences, word for word, through the ONE teaching
path (`TeachingPass`), which reads each sentence with the substrate's own reader. Nothing is
pre-cut into facts for it. Then it is asked about what it was taught, and asked the lesson's
own questions, and every reply is recorded as it was said.

  A  READ     what the substrate's reader makes of each sentence of the lesson
  B  TEACH    the lesson through the one teaching path
  C  HELD     everything the lesson left in the store
  D  ASKED    questions about the lesson, and the lesson's own questions

Run WITHOUT booting the whole system, on purpose: a full boot writes its own startup knowledge
(tool descriptions, a scan of the folder it runs in) into the store, and this is the store's
first lesson. So nothing but the lesson goes in. The domain authority is not running, so no
domain forms from it. Look-ups are OFF when it is asked, so an answer can only come from the
lesson. Nothing is removed afterwards: this is what the substrate now knows.

Run: ./venv_lyric/bin/python3 experiments/ENGLISH-LESSON-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import sys
from pathlib import Path

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

N = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
EXAMINER = f"english-lesson-examiner-{N}"
DOMAIN = "english_lesson_01"
SOURCE_URL = "https://illinoisearlylearning.org/ields/ields-plans/adapting-1ceca/"

#: What the teacher says in the lesson, word for word (Step 1).
LESSON = [
    "I get my shoes from my closet each morning.",
    "My shoe is black and has laces.",
    "I have to tie my shoe to put it on.",
    "I put my shoes on all by myself in the morning.",
    "I'm going to choose the black, brown, and red paints to create my shoe.",
    "This is my shoe.",
    "It is black.",
    "Look, I painted the sole of my shoe here; it is brown.",
    "Here are the laces.",
    "They are red.",
    "You will have a chance to paint pictures of your shoes at small group time this week.",
]

#: Asked afterwards. First about what the teacher said, from the listener's side; then the
#: lesson's own questions (Step 4), as the teacher asks them.
ABOUT_THE_LESSON = [
    "What color is the shoe?",
    "Does the shoe have laces?",
    "What color are the laces?",
    "What color is the sole?",
    "Where do the shoes come from?",
    "Is the shoe red?",
    "What is a shoe?",
]
LESSON_QUESTIONS = [
    "What color are your shoes?",
    "Where do you keep your shoes at your house?",
    "Did someone help you put on your shoes this morning?",
    "Where did you get those shoes?",
]

EV = RunRecord(
    "ENGLISH-LESSON-01",
    claim=("Taught a preschool lesson's sentences on an empty store, the substrate reads them, "
           "holds what they say, and answers questions about it in English."),
    hypothesis=("A sentence it cannot read, a reading that is not what the sentence says, a question "
                "about the lesson it cannot answer, or an answer that is not what was taught would "
                "each show here."))
TRANSCRIPT = []
results = []


def say(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def observe(name, detail):
    EV.note(f"OBSERVED — {name}: {detail}")
    say(f"  [OBSERVED] {name} — {detail}")


class LessonSource:
    """The lesson plan as a teaching source: the teacher's sentences, and nothing cut from them."""
    name = "Illinois Early Learning Project, lesson 1.C.ECa"
    curated = True

    def provenance(self):
        from core.learning.teaching_sources import _provenance
        return _provenance("teaching", SOURCE_URL)

    def records(self):
        from core.learning.teaching import TaughtRecord
        for sentence in LESSON:
            yield TaughtRecord(subject="", relation="", obj="", quality=0.9, sentence=sentence)


STORES = {
    "memories": "SELECT count(*) AS n FROM memory_hot.memory_hot",
    "concepts": "SELECT count(*) AS n FROM unified.concepts",
    "graph_edges": "SELECT count(*) AS n FROM unified.concept_relations",
    "beliefs": "SELECT count(*) AS n FROM unified.beliefs",
    "knowledge_updates": "SELECT count(*) AS n FROM unified.knowledge_updates",
}


async def measure(d):
    return {name: int((await d.execute_query(sql, (), fetch_one=True))["n"])
            for name, sql in STORES.items()}


async def main() -> int:
    from core.database import get_database_manager
    d = get_database_manager()
    await d.initialize()
    from core.memory import get_memory_agent
    agent = await get_memory_agent()
    await agent.warm_word_classes()
    from core.learning import get_learning_authority
    L = get_learning_authority()

    before = await measure(d)
    observe("the store before the lesson", f"{before}")

    say("\n== A. What the substrate's reader makes of each sentence ==")
    from core.semantics.sentence_reader import SentenceReader
    reader = SentenceReader()
    read_ok = 0
    for sentence in LESSON:
        parts = [(p.get("subject"), p.get("relation"), p.get("obj"), p.get("positive", True))
                 for p in reader.read_all(sentence)]
        read_ok += 1 if parts else 0
        say(f"  {sentence}\n      -> {parts if parts else 'NOT READ'}")

    say("\n== B. The lesson, through the one teaching path ==")
    from core.learning.teaching import TeachingPass
    report = await TeachingPass(LessonSource(), domain=DOMAIN, sample=False).run(L)
    for line in report.lines():
        say(f"    {line}")
    observe("records given / facts taught", f"given={report.read} taught={dict(report.taught)}")

    say("\n== C. What the lesson left in the store ==")
    after = await measure(d)
    observe("the store after the lesson", f"{after}")
    edges = await d.execute_query(
        "SELECT c.name AS s, cr.relation AS r, t.name AS o, cr.polarity AS p "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
        "JOIN unified.concepts t ON t.concept_id = cr.target_concept_id ORDER BY cr.created_at",
        (), fetch_all=True) or []
    say("  what it now holds, as links:")
    for e in edges:
        say(f"      {e['s']} —{e['r']}→ {e['o']}" + ("" if e["p"] == "positive" else f"  ({e['p']})"))
    memories = await d.execute_query(
        "SELECT content, tags FROM memory_hot.memory_hot ORDER BY created_at", (), fetch_all=True) or []
    say("  what it now remembers:")
    for m in memories:
        say(f"      {str(m['content'])[:160]}  {m['tags']}")
    words = sorted({w.strip(".,;'!?").lower() for s in LESSON for w in s.split()} - {""})
    classes = {w: sorted(agent.word_classes(w)) for w in words}
    observe("the lesson's words it has a class for", f"{ {w: c for w, c in classes.items() if c} }")
    observe("the lesson's words it has no class for", f"{[w for w, c in classes.items() if not c]}")

    say("\n== D. Asked about the lesson (look-ups off: answers can only come from the lesson) ==")
    from core.agents.autonomous.autonomous_coordinator import Conversation
    from core.agents.autonomous.shared_types import TaskSource
    talk = Conversation(session=f"lesson-check-{N}", actor_identity=EXAMINER, source=TaskSource.MANUAL)
    for heading, questions in (("About what the teacher said", ABOUT_THE_LESSON),
                               ("The lesson's own questions", LESSON_QUESTIONS)):
        say(f"\n  -- {heading} --")
        for question in questions:
            understanding = await talk.understand(question, look_up=False)
            say(f"  > {question}")
            for line in str(understanding.reply or "(no reply)").split("\n"):
                say(f"      {line}")

    check("every sentence of the lesson was read", read_ok == len(LESSON),
          f"{read_ok}/{len(LESSON)} sentences gave a reading")

    await EV.verify_database()
    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# ENGLISH-LESSON-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    print(f"  transcript: {transcript}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
