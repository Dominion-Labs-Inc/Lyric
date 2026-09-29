# SHAPES-LEARN-03: the first English lesson, and what the reading engine reads with it

**Finding (2026-09-29, run `20260929T014113Z`, 10/10).** Step 3, parts 1 and 2 of the change map
(`docs/research/SHAPES_CHANGE_MAP.md` §11b) work end to end in the sandbox.

**The lesson.** The first lesson of basic English, `data/lessons/english_01.json`, is 228 sentences, each with its
meaning in the domain system's link kinds. It went through the one teaching path one pair at a time. None was refused,
and every taught sentence reads back to its meaning.

**The grammar it left:**

| Construction | Count |
|---|---|
| holophrases | 19 |
| item-based constructions (frames) | 84 |
| lexical fillers | 132 |
| links | 323 |

**The repairs that ran:**

| Repair | Runs |
|---|---|
| item-based → lexical | 65 |
| add-categorial-links | 59 |
| lexical → item-based | 58 |
| substitution | 26 |
| nothing → holophrase | 19 |

The lesson has no pair that adds or removes one run, so the addition and deletion repairs did not run.

**Examples state nothing.** Every sentence is an example of English (`TaughtRecord.example`), so the lesson taught how
English says things and nothing about the world. The 113 facts its examples state were looked for as relations,
beliefs and rules; none is held.

**Sentences never taught: 35/35 read to the meaning they have.** Each reading says what it had to suppose:
- **The hearing and conversation experiments' sentences**, all without capitals or marks and with names never seen:
  - "a vex123 is a mammal"
  - "is a vex123 an animal"
  - "a zq3k heron is a zq3k bird"
  - "if the vex123 is hot then the valve is hot"
  - "is the vex123 hot"
  - "what did I just tell you"
  - "are mammals animals"
- **Fillers of a learned kind in frames they never filled.** "Is the shoe red?", "Tie your shoe.", "Close the tank.",
  "Can geese fly?" (read as `goose`: "Geese" opened a taught sentence), "She tall.", "That shoe is fire."
- **A paragraph**, read as three utterances.
- **Four stay unread, as they should:** "Red, blue, and green are colors!", "I have a red shoe.", "He be working.",
  "Hello there."

The kind of utterance (tell, ask, request) came from the reading for all 33 read utterances.

**Measured, not checked:**

| Sentences | Engine with this lesson | Written reader (SHAPES-BASELINE-01, NLU-01) |
|---|---|---|
| SHAPES-BASELINE-01 statements read | 8/35 | 9/35 |
| SHAPES-BASELINE-01 kinds right | 11/45 | 13/45 |
| NLU-01's real prose | 2/300 | 83/300 |

One basic lesson does not read documentation. The prose it reads, it reads correctly: "The cause is not established."
and "Is the substrate halted?".

**What reading could not yet do** (the next step, phrases in slots): "The teacher's shoe is black." reads with
`teacher's shoe` as one new name, because in the published method a slot holds one filler naming one concept.

## Engine rules this run exercised (`core/semantics/derived_reader.py`)

- **A filler of the slot's kind.** It stands in a slot it was never linked to, and the link is proposed, never
  written.
- **A new word.** It stands in a known frame, under four limits:
  - a frame takes no more new words than it has words of its own;
  - a new name is no longer than the longest filler its slot's kind has held;
  - a name holds no structure word (a word used in frames and never as a filler on its own);
  - a word held in another case is the word it is, not a new one.
- **Loose reading.** Case is folded, a frame's marks may be missing, and a final mark is set aside. A mark inside what
  was said still separates.
- **A text** is read as the utterances that cover it, each ending where a held construction ends.
- **Conditionals** are meanings with condition facts, and a taught conditional that is not an example is held as a rule.
- **A frame keeps at least one word of its own.** A mark alone anchors nothing.

## What it checks

| Part | Check |
|---|---|
| A. Teach | the lesson through the one teaching path; every pair read or repaired, none refused |
| B. Examples | every sentence taken as an example; no relation, rule or belief states what an example says |
| C. Taught | every taught sentence reads to its meaning |
| D. Probes | 35 sentences never taught read to their meaning; the untaught stay unread |
| E. Kind | tell / ask / request from each reading |
| F. Baseline | SHAPES-BASELINE-01's sentences (measured) |
| G. Prose | NLU-01's 300 sentences (measured) |
| H. Nothing | reading wrote nothing |
| I. Main | the main model's store is untouched |

Run: `./venv_torin/bin/python3 experiments/SHAPES-LEARN-03/experiment.py` (sandbox; empties it first).
