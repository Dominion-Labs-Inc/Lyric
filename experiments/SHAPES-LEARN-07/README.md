# SHAPES-LEARN-07: word shapes

**Finding (2026-09-29, run `20260929T145115Z`, 16/16).** Step 4 of `docs/research/SHAPES_CHANGE_MAP.md` (§11e) works
end to end in the sandbox:
- A word written in a learned shape is read as the word it is.
- Possessives and contractions are read over words never taught with them.
- A concept is said in the shape its slot takes.

Nothing tells the substrate what a plural is. The shapes are found from the fillers it holds.

**Taught:** five lessons through the one teaching path, none refused. The fifth, `english_05` (52 examples), holds:
- plurals, the ones of words already held first;
- `-es`, `-ies` and `-ys` plurals, two or more for each ending;
- irregular plurals;
- possessives and contractions;
- "What's a …?" and "What's an …?".

Every sentence of the five lessons still reads to its meaning.

**Shapes found: 26 productive changes, each in its context.** A change is scored over the words it applies to, the
most particular first. A word that a more particular change reads rightly is not held against a general one.

| Change | Reads rightly |
|---|---|
| `s` → nothing | 29 of 32 |
| `es` → nothing | 9 of 11 |
| `ies` → `y` | 5 of 5 |
| `ses` → `s` | 3 of 5 |
| `ys` → `y` | 3 of 3 |
| `xes` → `x`, `ches` → `ch`, `shes` → `sh`, `sses` → `ss`, `oys` → `oy` | 2 of 2 each |

The irregular forms ("mice", "children", "men", "teeth", "geese") are words of their own, not shapes.

**Reading: 19/19 never taught.** Each reads whole, to its meaning:
- plurals of words held only as they are named: "Cups are red.", "Churches are big.", "Pennies are small.",
  "Horses are tall.", "Can horses swim?";
- plurals of endings met in other words: "Foxes are red.", "Glasses are big.", "Dishes are small.";
- a concept's own name, where only its plural is held: "The fox is red.";
- possessives: "The boy's cup is red.", "The teacher's ball is blue.";
- contractions: "It's green.", "The window isn't open.", "A robin isn't a fish.", "Birds can't swim.", "I'm nice.",
  "They're green.", "Where's the cup?", "What's an eagle?".

**Words never met.** "Rain causes floods." reads with both words new, one to a slot of "?slot0 causes ?slot1.".
SHAPES-LEARN-06 put its failure down to plurals. The cause was the old limit of no more new words than the frame's
own words.

**Saying: 8/8.** Each fact is about a concept held only as it is named. Every one is said in the plural slot's shape,
and every sentence said reads back to exactly the meaning it was said for:

| Fact | Said in the plural slot |
|---|---|
| `has_property(church, big)` | Churches are big. |
| `has_property(penny, small)` | Pennies are small. |
| `has_property(fox, red)` | Foxes are red. |
| `has_property(bus, red)` | Buses are red. |
| `has_property(glass, big)` | Glasses are big. |
| `has_property(horse, big)` | Horses are big. |
| `has_property(cup, red)` | Cups are red. |
| `capable_of(horse, swim)` | Horses can swim. |

**What no lesson taught stays unread whole:**
- "the the the";
- "The cup that is on the table is hot.";
- "Red, blue, and green are colors!";
- "Its queues are now built without persistence." (a run of new words standing in one slot).

**Measured, not checked: NLU-01's 300 real prose sentences.**

| Measure | Value |
|---|---|
| Utterances read whole | 3/300, the same three as SHAPES-LEARN-05 |
| Words read, in whole sentences | 14 of 4,112 |
| Words read, in parts | 461 of 4,112 (271 of 4,081 in SHAPES-LEARN-05) |

The word count grew because "it's" and "don't" are now two pieces each.

**Also held:**
- reading and saying wrote nothing: the view held 1,036 items before and after;
- the main model's store is untouched: 192,294 rows before and after.

**Limits:**
- **Unheld words keep their writing.** A plural whose word is not held reads as written ("Classes"). A new word keeps
  its writing in the meaning ("Rain", "floods"). The store's door still makes a term's identity (`canonical_term`)
  until part 5 of step 4.
- **"a" and "an" are two words to the reader.** "What's an eagle?" reads because "What's an owl?" was taught.
- **Bare nouns in first place.** Among the sentences it can say, a bare "Church is big." can rank first. The frame
  learned from "Milk is white." takes any word of the kind, and which words go without "a" or "the" is not learned
  yet.

Run: `./venv_lyric/bin/python3 experiments/SHAPES-LEARN-07/experiment.py` (empties the sandbox first, and leaves the
five lessons taught).
