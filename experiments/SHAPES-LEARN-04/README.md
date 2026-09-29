# SHAPES-LEARN-04: it asks about what it cannot read, is answered by example, and reads what it asked about

**Finding (2026-09-29, run `20260929T123255Z`, 14/14).** Part 1 of step 3b in `docs/research/SHAPES_CHANGE_MAP.md`
(§11c) works end to end in the sandbox. No sentence is thrown away, and the substrate learns what it asks about.

**The start.** The first lesson (`data/lessons/english_01.json`, 228 examples) is taught through the one teaching
path, as SHAPES-LEARN-03 teaches it.

**Told what it cannot read whole.** None of these reads whole. Each reply says what was understood and asks about
the rest, and each sentence is remembered as said:

| Told | Reply |
|---|---|
| The door is open and the window is closed. | I understood 'The door is open' and 'the window is closed', but I don't know 'and' yet. What does that word mean? |
| My dog is not a cat, he is a dog. | I understood 'dog', 'cat' and 'a dog', but not how 'My', 'is not a' and 'he is' fit with it. |
| Is the stove hot or cold? | I understood 'Is the stove hot or' and 'cold', but not how they go together. |
| It is not true that the door is open. | I understood 'the door is open', but I don't know 'true' yet. What does that word mean? |
| the the the | I know these words, but not this way of putting them together. |

Each reply also says "I have remembered what you said."

**The answers, by example.** The second lesson (`data/lessons/english_02.json`, 29 examples) answers those questions
the way English is taught here: sentence-meaning pairs through the one teaching path. It covers:
- "and" joining statements and names;
- "or" questions;
- "true" and "not true";
- "my ... is not a ..." with "he" and "she".

None of the four sentences is in either lesson. Taught in 4.8 s:
- 21 new constructions and 63 new links;
- repairs run: lexical → item-based 12, item-based → lexical 9, add-categorial-links 8;
- nothing the examples state is held as a fact.

**What it asked about, read again: 4/4, to the meaning each has.**

| Sentence | Meaning |
|---|---|
| The door is open and the window is closed. | `has_property(door, open) & has_property(window, closed)` |
| My dog is not a cat, he is a dog. | two sentences, split at the comma: `instance_of(?x, dog) & owned_by(?x, ?speaker) & not instance_of(?x, cat)`, then `instance_of(?previous, dog)` |
| Is the stove hot or cold? | asks which of `has_property(stove, hot)` or `has_property(stove, cold)` holds |
| It is not true that the door is open. | `not has_property(door, open)` |

Neither lesson taught these, and none reads whole:
- "the the the";
- "The door is open or the window is closed." ("or" between statements);
- "I think the tank is full.".

**Told again.** The replies around those readings are still the old speech ("Noted — a door is an open."). Step 5
(speaking through constructions) replaces it. The transcript records them, and nothing checks them here.

**Measured, not checked: NLU-01's 300 real prose sentences.**

| Measure | Value |
|---|---|
| Utterances read whole | 3/300 |
| Words read, in whole sentences | 15 of 4,081 |
| Words read, in parts | 261 of 4,081 |

Two short lessons do not read documentation; this is the distance to cover. Phrases in slots (part 2) and teaching at
scale are what cover it.

**Also held:**
- reading wrote nothing: the view held 642 items before and after;
- the main model's store is untouched: 188,529 rows before and after.

**What it leaves.** The sandbox keeps both lessons and the conversation, remembered. Nothing is cleaned up, because
that is the point.

Run: `./venv_lyric/bin/python3 experiments/SHAPES-LEARN-04/experiment.py` (empties the sandbox first).
