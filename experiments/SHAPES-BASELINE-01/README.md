# SHAPES-BASELINE-01 — what the hand-written sentence and word shapes do on their own

**Finding (2026-09-26, run `20260927T034210Z`):** with nothing learned behind them, the shapes written into the
code read **9 of 35 statements**. They read none of the 7 African American English sentences, none of the 4 slang
sentences, none of the 3 commands, and not "This is my shoe.", "It is black." or "It's black.". The request-kind
test was right on 13 of 45, and the 3 commands it got right are not credit: anything the reader cannot read is
called a job, so all 7 African American English statements and all 4 slang statements are jobs too. The tokenizer
split none of 7 written forms into the words they stand for, and it drops the number from `3pm`.

This is the baseline for moving sentence shapes and word shapes out of code and into memory
(`docs/research/SENTENCE_AND_WORD_SHAPES.md`): what the code does when nothing has been learned.

## Results

| Group | Gave a reading | Kind right |
|---|---|---|
| preschool statements | 2/10 | 2/10 |
| questions | (question reader) 4/6 parsed | 5/5 |
| commands | 0/3 | 3/3 (only because unread = job) |
| a paragraph | 1/1 (one of its three sentences) | 0/1 |
| joined clauses | 1/3 | 0/3 |
| African American English | 0/7 | 0/7 |
| slang | 0/4 | 0/4 |
| abbreviations | 2/6 | 1/6 |
| punctuation | 3/6 | 2/6 |

| Word shapes | Right |
|---|---|
| written forms split into their words (`It's`, `I'll`, `ain't`, `U.S.`, `3pm`, `teacher's`, `Dr.`) | 0/7 |
| plurals reduced to their singular | 9/12 (`boxes`→`boxe`, `buses`→`buse`, `news`→`new`) |
| verb forms whose base is among the candidates | 7/10 (no irregular: `ate`, `made`, `knew`) |

Readings worth reading in the transcript:
- "Red, blue, and green are colors!" → `Red is colors`, `green is colors`. `blue` is lost.
- "What color is the shoe?" → asks for something related by `color` to `is the shoe`.
- "When it rains, I wear boots." → a question, because `when` is on the question-opener list.
- "Dr. Smith is a doctor." → `Smith is a doctor`; the title is dropped.
- The paragraph "I have a dog. His name is Max. He is brown and he likes to run." gives one reading,
  `His name is Max`.

## The trap in measuring it

It runs with the memory authority down, so every word-class lookup answers "never observed", which is what an
empty store answers. That is on purpose: it measures the code alone, the part that is to be replaced. On a taught
store the same sentences read differently, and not always better (the NLU suite once found the reader reading
less as vocabulary grew). "Kind right" for commands is the fallback, not recognition. There is no answer key for
the meaning of each reading; the readings are recorded as said, and the wrong ones above were judged by reading
them.

## Run

```
./venv_torin/bin/python3 experiments/SHAPES-BASELINE-01/experiment.py
```
Opens no database and writes nothing but its own run record and transcript.
