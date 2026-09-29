# SHAPES-LEARN-02: constructions found between taught sentences

**Finding (2026-09-27, run `20260927T202516Z`, 32/32): step 2 of the change map works end to end.** A kindergarten
lesson of 25 sentences went through the one teaching path, each sentence with its meaning, one at a time. The
substrate found constructions between them by the Leuven method (Doumen, Beuls & Van Eecke, *Royal Society Open
Science* 11:231998, 2024), holding them in memory and scoring them with beliefs.

- **Learned:**
  - 7 holophrases;
  - 8 item-based constructions, such as `This is my ?slot0.`, `The ?slot0 is ?slot1.` and `Is the ?slot0 ?slot1?`;
  - 16 lexical constructions;
  - 30 links between slots and fillers.

  There is one memory and one grounded belief for each, 61 in all.
- **Every repair ran where it applies, in the paper's order:**

  | Repair | Runs |
  |---|---|
  | nothing → holophrase | 6 |
  | substitution | 4 |
  | item-based → lexical | 6 |
  | lexical → item-based | 2 |
  | add-categorial-links | 5 |
  | addition | 1 |
  | deletion | 1 |
- **Reading:**
  - every taught sentence reads back to its meaning;
  - five sentences never taught, made of parts it had seen, read to their meaning and are said back ("The shoe is
    blue.", "Is the hat red?", …);
  - six are refused: a filler never seen in a slot ("Is the ball red?", "This is my red.") and shapes never seen.
- **Six word kinds emerged**, none told and none mixed:
  - shoe / hat / cup / ball
  - red / blue / green / black
  - robin / sparrow
  - cat / dog
  - happy / sad
  - to grandma / to grandpa
- **Communicative success** (the paper's measure: understood as it came, or by adding links only) was 5/25 on first
  hearing and 25/25 from a second source.
- **Scores moved the right way.** The same lesson again from the same source counted no pair twice. The second
  source raised the constructions that read it. "This is my shoe." lost ground (0.9926 → 0.9000) to "This is my
  ?slot0." + "shoe", which now reads it first.
- **The English domain** is judged by what memory holds of it (maturity 0.7024). The main store was untouched.

**Step 3 (2026-09-29, run `20260929T013931Z`, 35/35).** Reading may now suppose what no taught pair showed
(`docs/research/SHAPES_CHANGE_MAP.md` §11b). Two sentences this experiment used to refuse now read by design, and
each reading says what it supposed:
- "Is the ball red?" reads because `ball` is of the kind that fills the slot. The link is proposed and not written.
- "The shoe is blue" (no final mark) reads loosely.

The four other unseen sentences are still refused, and reading still writes nothing.

SHAPES-LEARN-01 re-ran unchanged under the new learner: 35/35 (`20260927T202821Z`).

## What it checks

| Part | Check |
|---|---|
| A. Teach | the lesson through the one teaching path. Every pair is read or repaired, each repair runs as often as it applies, and first-hearing success is the pairs understood by adding links only |
| B. Memory | one memory per construction and link, keyed exactly. Memory and the view agree kind by kind, and with the report |
| C. Beliefs | one per construction and link, grounded in its memory, in the English domain |
| D. Read | taught sentences read; new combinations read and are said; unseen pairings and shapes do not read |
| E. Kinds | things and colours are separate kinds, and none mixes them |
| F. Warm | a view rebuilt from memory holds, reads and says the same |
| G. Again | the same source again: nothing learned. No construction counts a pair twice, and no holophrase moves |
| H. Witness | a second source: success rises, nothing is new, nothing is lost. The competing holophrase loses ground, and the generalization reads first |
| I. Ledger | every construction and link recorded as new, with the repair that made it |
| J. Domain | English maturity equals what its constructions and links give |
| K. Baseline | the written reader of SHAPES-BASELINE-01 on the same sentences |
| L. Main | the main store untouched |

## The written reader, on the same sentences

| Sentences | Learned constructions read them to their taught meaning | The written reader gives some reading |
|---|---|---|
| the 25 taught | 25/25 | 11/25 |
| the 5 never taught | 5/5 | 5/5 |

The written reader's readings are not checked for meaning, as in SHAPES-BASELINE-01. It reads statements with its
written shapes, and its question reader parses the "Is the …?" forms.

## Worth knowing

- **Why a frame learns a slot.** A lexical construction supplies one concept for its slot. That is what comparing
  two flat meanings gives: `instance_of(?shown, shoe)` against `instance_of(?shown, hat)` differ in one term. So
  "red" is one construction, whichever frame it fills.
- **Thin frames can lose, and then come back.**
  - A frame learned from two sentences ("A ?slot0 is a bird." from robin and sparrow) has been used no more than
    the holophrase it came from. Re-hearing "A robin is a bird." then ties the two.
  - Scores are beliefs, and the belief store decays them with time, so run timing breaks such ties.
  - In an earlier run (`20260927T202111Z`) the holophrase won. The frame was punished as a competitor below
    belief, the next sentence's substitution revived it, and the second source scored 23/25.
  - The paper's frames win by being used more often. In a 25-sentence lesson some frames are too thin to, which is
    why the experiment checks that success rises and nothing is lost, not a fixed number.
- **Reading adds no links.** "Is the ball red?" is refused because "ball" was never seen in that question's slot.
  The paper would add the link while reading. Here reading never writes memory; whether it may is a step 3 question.

## Run

```
./venv_torin/bin/python3 experiments/SHAPES-LEARN-02/experiment.py
```

It empties the sandbox first (`scripts/reset_dev_store.py`) and starts the substrate before teaching.
