# STRUCTURE-02: how many of the lessons' meaning roles fall on phrases

**Claim.** The meaning roles of the sentences the main model was taught fall on phrases of the structure it learned
from a treebank, so frames learned over phrases can read them as they were taught.

**Why.** The reader learned whole sentence frames with slots, and prose fails where nothing between words and frames
says which words form a phrase (`docs/research/READING_PROSE_AT_SCALE.md`). The owner chose (2026-10-16) that Lyric
learns phrase structure from a treebank; STRUCTURE-01 measured that structure. Before frames are learned over phrases,
this measures the ceiling they can reach: the research's first measurement (§5).

**What it measures** (read only, from the store's own views, warmed from memory). Each sentence of the English lessons
(`data/lessons/english_NN.json`) is read as the learner reads a taught pair (`readings_of`, strictly, to the meaning
it was taught with). Where it reads through a frame with slots, the words each slot holds are found as the reader
finds them (`_chunkings`, `_slot_fillings`, `_composed_meaning`), and the sentence is read for its structure
(`StructureView`). Each slot is tested twice:

| Test | A slot passes when |
|---|---|
| One phrase | exactly one of its words depends on a word outside them (a slot of one word always does) |
| Not against the meaning | going up from that word (through `conj`: a conjunct stands where the first one does), the first word that stands for anything in the meaning (a slot's words, or a frame's own word held to name a term: "kicked" the kicking) is where it hangs; it fails when the meaning ties the slot to something another word names, outside its own phrase, and not to where it hangs |

"Tom kicked the ball in the house." with "house" under "ball" fails the second test when the house is where the
kicking was; "The ball near the box is red." with "box" under "ball" passes it, and so does "four" under "ten" in
"What is ten minus four?", both tied to the difference, which no word names. A slot the meaning ties to nothing a
word names is not judged. Only the slots are tested: what a frame writes itself is not.

The share of sentences whose every slot passes both is the ceiling. **No bar:** it measures. It also reports each
test by the kind of thing a slot holds (`_role_of_slot`: kind, quality, doing, name, closed, thing), how each slot's
phrase depends on the rest (`_relations.json`), every sentence with a slot that fails (`_missed.json`), and checks
the store was not written to.

**Run** (from the Lyric folder; starts no substrate; about 5 minutes to load, then the lessons read once):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-02/experiment.py
```

**Results:** `results/<UTC timestamp>.json` and `.md`, `_missed.json` and `_relations.json` beside them, and
`results/run.log`.

**Runs on main:**

| Run | Second test | Read through a frame with slots | Every slot one phrase | And the second test |
|---|---|---|---|---|
| `20261016T222833Z` | first form: the first other slot above must be tied to it in one fact | 2,988 of 3,054 | 96.1% | 84.8% |
| `20261016T225042Z` | as above: none placed against the meaning | 2,988 of 3,054 | 96.1% | **93.9%** |

The first form of the second test counted as wrong what the meaning cannot place: a conjunct under the first
("three" under "two" in "two plus three"), two slots tied to one thing no word names ("ten minus four", "between the
cat and the bird", "To be quick is to be fast."), and clauses the meaning ties by no fact ("Although the dog barked,
the cat climbed."). It was replaced by the form above (lab notebook 2026-10-16 (9)).

**What fails in the second run** (182 sentences, each counted once, from `results/20261016T225441Z_missed.json`):

| Sentences | Why |
|---|---|
| 47 | a number written in words, parsed apart ("Thirty-five", "two hundred and six"; the treebank seldom spells numbers) |
| 24 | "Rex", in no sentence of the treebank, read as a verb: a word never met is classed by its ending alone |
| 16 | "Dr." written as two pieces, where the treebank keeps it one word |
| 11 | a verb read as a noun beside a noun ("Did the bird fly?", "The dog barks now.") |
| 6 | formulas ("Solve 2y + 1 = 9 for y.") |
| 42 | misreadings of attachment or clauses ("If the door is open then the room is cold.", "The cup that is on the table is hot.", "Tom opened the door with a key.") |
| 36 | a slot of the old frames that is no phrase ("It is true that the sky" in "?slot0 is ?slot1."), or a slot of several words parsed apart |
