#!/usr/bin/env python3
"""SHAPES-BASELINE-01 — what the hand-written sentence and word shapes do on their own.

Before sentence shapes and word shapes can move out of code and into memory, this measures what
the shapes written into the code do today, with nothing learned behind them. It runs the
substrate's own reader, its own question test and its own word-shape functions over sentences
of every kind listed: preschool statements, questions, commands, a paragraph, joined
clauses, African American English, slang, abbreviations and punctuation.

  A  SENTENCES  whether the reader reads each sentence, and what it makes of it
  B  KINDS      question / telling / job, as `Conversation.classify` decides them
  C  QUESTIONS  what the question reader makes of each question
  D  WORDS      how the tokenizer splits words, and how plurals and past tenses are reduced

Nothing is written anywhere and no database is opened. The memory authority is not up, so every
word-class lookup answers "never observed", which is exactly what an empty store answers
(`genericity._word_class` and `_word_classes` return None / empty when there is no memory agent).
So this measures the code's shapes alone.

Run: ./venv_lyric/bin/python3 experiments/SHAPES-BASELINE-01/experiment.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

#: (sentence, the kind it is). The kind is what a reader of English would say: a statement tells,
#: a question asks, a command asks for something to be done. `response` is an acknowledgement that
#: is none of the three; the classifier has no kind for it, so it cannot be right about it.
SENTENCES = {
    "preschool": [
        ("This is my shoe.", "telling"), ("It is black.", "telling"),
        ("My shoe is black.", "telling"), ("The shoe is black.", "telling"),
        ("Here are the laces.", "telling"), ("They are red.", "telling"),
        ("I have a red shoe.", "telling"), ("A is a letter.", "telling"),
        ("The cat sat on the mat.", "telling"), ("I like my shoes.", "telling")],
    "questions": [
        ("What color is the shoe?", "question"), ("Is the shoe red?", "question"),
        ("Where are my shoes?", "question"), ("Can you tie your shoe?", "question"),
        ("Who has a red shoe?", "question")],
    "commands": [
        ("Tie your shoe.", "job"), ("Look at the sole.", "job"),
        ("Please put on your shoes.", "job")],
    "paragraph": [
        ("I have a dog. His name is Max. He is brown and he likes to run.", "telling")],
    "joined clauses": [
        ("I wear my shoes because it is cold.", "telling"),
        ("My shoe is black but the laces are red.", "telling"),
        ("When it rains, I wear boots.", "telling")],
    "African American English": [
        ("She nice.", "telling"), ("He be working.", "telling"),
        ("They ain't got no shoes.", "telling"), ("I been knew that.", "telling"),
        ("She finna go to the store.", "telling"), ("He done ate.", "telling"),
        ("It's a lot of people outside.", "telling")],
    "slang": [
        ("That shoe is fire.", "telling"), ("Those kicks are dope.", "telling"),
        ("No cap, it's lit.", "telling"), ("Bruh, that's crazy.", "telling")],
    "abbreviations": [
        ("Dr. Smith is a doctor.", "telling"), ("The U.S. is a country.", "telling"),
        ("I'll be there ASAP.", "telling"), ("idk what that is", "telling"),
        ("lol ok", "response"), ("My appt is at 3pm.", "telling")],
    "punctuation": [
        ("It's black.", "telling"), ("The teacher's shoe is black.", "telling"),
        ("Wait — is it red?", "question"), ("My shoes (the black ones) are new.", "telling"),
        ('"Hi," she said.', "telling"), ("Red, blue, and green are colors!", "telling")],
}

#: A plural and the singular it names.
PLURALS = [("shoes", "shoe"), ("laces", "lace"), ("glasses", "glass"), ("children", "child"),
           ("feet", "foot"), ("boxes", "box"), ("kicks", "kick"), ("dresses", "dress"),
           ("buses", "bus"), ("mice", "mouse"), ("fish", "fish"), ("news", "news")]
#: A verb form and its base.
VERB_FORMS = [("painted", "paint"), ("going", "go"), ("ate", "eat"), ("tied", "tie"),
              ("running", "run"), ("made", "make"), ("knew", "know"), ("stopped", "stop"),
              ("choose", "choose"), ("put", "put")]
#: A written form and the words it stands for.
WRITTEN = [("It's", ["it", "is"]), ("I'll", ["i", "will"]), ("ain't", ["ain't"]),
           ("U.S.", ["u.s."]), ("3pm", ["3", "pm"]), ("teacher's", ["teacher's"]),
           ("Dr.", ["dr."])]

EV = RunRecord(
    "SHAPES-BASELINE-01",
    claim=("With nothing learned, the sentence and word shapes written into the code read every kind "
           "of sentence a speaker of American English uses, tell a question from a statement from a "
           "request, and reduce every word form to the word it is a form of."),
    hypothesis=("The hand-written shapes cover a narrow slice: copular and simple subject-verb-object "
                "sentences whose subject is a noun phrase. Pronoun subjects, African American English, "
                "slang, commands and most contractions will not read; plural and past-tense reduction "
                "will fail on irregular forms and on words that end in -es or -s but are not plurals."))
TRANSCRIPT = []


def say(line=""):
    TRANSCRIPT.append(line)
    print(line)


def main() -> int:
    from core.agents.autonomous.autonomous_coordinator import QUESTION_OPENERS
    from core.semantics.lexical_normalization import deinflect_verb, singularise
    from core.semantics.sentence_machine import tokenize
    from core.semantics.sentence_reader import SentenceReader

    reader = SentenceReader()

    def kind_of(sentence: str) -> str:
        # `Conversation.classify`, exactly: `is_question`, then the reader's statement test.
        words = tokenize(sentence)
        if sentence.strip().endswith("?") or (bool(words) and words[0] in QUESTION_OPENERS):
            return "question"
        return "telling" if reader._parse_statement(sentence) is not None else "job"

    say("== A/B. Each sentence: its kind, and what the reader makes of it ==")
    kind_right = total = 0
    for group, rows in SENTENCES.items():
        group_read = group_kind = 0
        say(f"\n  -- {group} --")
        for sentence, expected in rows:
            parts = [(p.get("subject"), p.get("relation"), p.get("obj"), p.get("positive", True))
                     for p in reader.read_all(sentence)]
            kind = kind_of(sentence)
            group_read += bool(parts)
            group_kind += kind == expected
            say(f"  {sentence}\n      kind: {kind} (it is: {expected})"
                f"\n      reading: {parts if parts else 'NOT READ'}")
        EV.metric(f"{group}: gave a reading", f"{group_read}/{len(rows)}")
        EV.metric(f"{group}: kind right", f"{group_kind}/{len(rows)}")
        kind_right += group_kind
        total += len(rows)
    statement_rows = [(s, k) for rows in SENTENCES.values() for s, k in rows if k == "telling"]
    statements_read = sum(1 for s, _ in statement_rows if reader.read_all(s))
    EV.metric("statements that gave a reading", f"{statements_read}/{len(statement_rows)}")
    EV.metric("sentences whose kind was right", f"{kind_right}/{total}")

    say("\n== C. What the question reader makes of each question ==")
    questions = [s for rows in SENTENCES.values() for s, k in rows if k == "question"]
    parsed = 0
    for q in questions:
        goal = reader._parse_goal(q)
        parsed += goal is not None
        say(f"  {q}\n      -> {goal if goal is not None else 'NOT READ'}")
    EV.metric("questions the question reader parsed", f"{parsed}/{len(questions)}")

    say("\n== D. Word shapes ==")
    split_right = 0
    for written, words in WRITTEN:
        got = tokenize(written)
        split_right += got == words
        say(f"  tokenize({written!r}) = {got}   (the words: {words})")
    plural_right = 0
    for plural, singular in PLURALS:
        got = singularise(plural)
        plural_right += got == singular
        say(f"  singularise({plural!r}) = {got!r}   (the word: {singular!r})")
    verb_right = 0
    for form, base in VERB_FORMS:
        got = sorted(deinflect_verb(form))
        verb_right += base in got
        say(f"  deinflect_verb({form!r}) = {got}   (the base: {base!r})")
    EV.metric("written forms split into the words they stand for", f"{split_right}/{len(WRITTEN)}")
    EV.metric("plurals reduced to their singular", f"{plural_right}/{len(PLURALS)}")
    EV.metric("verb forms whose base is among the candidates", f"{verb_right}/{len(VERB_FORMS)}")

    EV.check("every statement gave a reading", statements_read == len(statement_rows),
             f"{statements_read}/{len(statement_rows)}")
    EV.check("every sentence's kind was right", kind_right == total, f"{kind_right}/{total}")
    EV.check("every question was parsed", parsed == len(questions), f"{parsed}/{len(questions)}")
    EV.check("every written form split into its words", split_right == len(WRITTEN),
             f"{split_right}/{len(WRITTEN)}")
    EV.check("every plural reduced to its singular", plural_right == len(PLURALS),
             f"{plural_right}/{len(PLURALS)}")
    EV.check("every verb form's base was found", verb_right == len(VERB_FORMS),
             f"{verb_right}/{len(VERB_FORMS)}")
    EV.note("No database was opened and nothing was written. The memory authority was not up, so every "
            "word-class lookup answered 'never observed', which is what an empty store answers.")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# SHAPES-BASELINE-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    print(f"  transcript: {transcript}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
