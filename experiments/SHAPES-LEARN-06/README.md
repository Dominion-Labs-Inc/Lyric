# SHAPES-LEARN-06: it says what it holds with the sentences it was taught

**Finding (2026-09-29, run `20260929T135032Z`, 16/16).** Step 5 of `docs/research/SHAPES_CHANGE_MAP.md` (§11d) works
end to end in the sandbox. The engine that reads is the one that speaks. A held fact is said through a construction
it was taught, never through a template over a relation's label, and what it says reads back to what it meant.

**Taught:** four lessons through the one teaching path, none refused. The fourth, `english_04` (70 examples), gives
a statement and questions for every link kind no lesson had taught:
- used for, causes, caused by, requires;
- enables, prevents, precedes, follows;
- produces, produced by, creates, contains;
- member of, owns, eats, eaten by;
- synonym, antonym, next to, made from.

Each kind's words are met first in a plain sentence, so that both of its slots form. Every sentence of the four
lessons still reads to its meaning.

**Saying: 8/8.** Facts of the new kinds, none of them a lesson's own sentence, are said, and each sentence reads back
to exactly the meaning it was said for:

| Fact | Said |
|---|---|
| `used_for(saw, cutting)` | A saw is used for cutting. |
| `requires(bike, air)` | A bike requires air. |
| `causes(heat, smoke)` | Heat causes smoke. |
| `eats(goat, grass)` | A goat eats grass. |
| `contains(bag, pen)` | The bag contains a pen. |
| `produces(bee, milk)` | A bee produces milk. |
| `member_of(singer, team)` | A singer is a member of a team. |
| `owns(boy, car)` | The boy owns a car. |

**Reading: 7/7 never taught.** Each reads to its meaning:
- "A saw is used for cutting."
- "A bike requires air."
- "A goat eats grass."
- "The bag contains a pen."
- "Does a cat eat grass?"
- "What is a pen used for?"
- "What causes pressure loss?"

**Talking, about a name it had never met:**

| Said to it | Reply |
|---|---|
| A vexayjcdq is used for cutting. | Noted — A vexayjcdq is used for cutting. |
| What is a vexayjcdq used for? | A vexayjcdq is used for cutting. |
| Is a vexayjcdq used for cutting? | Yes. A vexayjcdq is used for cutting. |
| Is a vexayjcdq used for writing? | not a yes, and no store words |

That last reply also recited an unrelated memory ("I remember: README.md has extension md."). Since this run, a
reply recites only a memory that names what was asked about; recall handing the memory up is the recall work's to
look at.

**Also held:**
- reading and saying wrote nothing;
- the main model's store is untouched;
- the conversation's fact is about a nonce name and was removed by it.

**Limits:**
- A plural a lesson never used ("Rain causes floods.") needs word shapes (step 4).
- What the substrate says about itself ("I hold nothing for writing.") is still fixed wording, as the plan orders.

Run: `./venv_torin/bin/python3 experiments/SHAPES-LEARN-06/experiment.py` (empties the sandbox first, and leaves the
four lessons taught).
