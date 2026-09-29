# SHAPES-LEARN-05: phrases in slots

**Finding (2026-09-29, run `20260929T132341Z`, 11/11).** Part 2 of step 3b in `docs/research/SHAPES_CHANGE_MAP.md`
(§11c) works end to end in the sandbox. A slot holds a phrase as well as a word. A phrase learned in one slot is read
in every slot of its kind, and phrases nest inside one another.

**Taught:** three lessons through the one teaching path, none refused.
- `english_01` (228 examples).
- `english_02` (29 examples).
- `english_03` (21 examples), the noun-phrase lesson. It teaches:
  - words before a thing, in five frames;
  - several words before a thing;
  - where a thing is, said after it;
  - whose a thing is;
  - questions about a thing said with a phrase.

`english_03` made 17 constructions and 44 links. The new repair **item-based → phrase** ran 11 times and left 9
phrases:

| Construction | Count |
|---|---|
| holophrases | 19 |
| item-based constructions (frames) | 97 |
| phrases | 9 |
| lexical fillers | 148 |
| links | 430 |

**Every sentence of the three lessons still reads to its taught meaning.**

**Noun phrases never taught: 9/9 read whole, to the meaning each has.**

| Sentence | Meaning |
|---|---|
| This is my big blue ball. | the shown thing is a ball, the speaker's, big and blue |
| The small box is closed. | a box, small and closed |
| The cup on the table is hot. | a cup, at the table, hot |
| The teacher's sock is blue. | a sock, the teacher's, blue |
| Tie your small red sock. | a request to tie a sock of the listener's that is small and red |
| Is the small cup hot? | asks whether a small cup is hot |
| Where is the big box? | asks where a big box is |
| My big red hat is cold. | a hat, the speaker's, big, red and cold |
| The pen on the chair is big. | a pen, at the chair, big |

None of those combinations was taught. Each is read by joining things the lessons taught separately:
- phrases in frames they never appeared in (a request, a question);
- a learned phrase with different words in it;
- phrases inside phrases ("big blue ball").

**What no lesson taught stays unread whole:**
- "the the the";
- "The cup that is on the table is hot." (a clause inside a phrase);
- "Red, blue, and green are colors!".

**Measured, not checked: NLU-01's 300 real prose sentences.**

| Measure | Value |
|---|---|
| Utterances read whole | 3/300 |
| Words read, in whole sentences | 15 of 4,081 |
| Words read, in parts | 271 of 4,081 (261 before part 2) |

Real prose needs far more English than three short lessons.

**Also held:**
- reading wrote nothing: the view held 703 items before and after;
- the main model's store is untouched: 192,294 rows before and after.

**Limits, for later steps:**
- **Possessives.** "teacher's" is one piece, so each owner word is learned on its own until word shapes (step 4)
  split off "'s".
- **Small lessons leave kinds apart.** "That is your red book." does not read yet.

Run: `./venv_lyric/bin/python3 experiments/SHAPES-LEARN-05/experiment.py` (empties the sandbox first, and leaves the
three lessons taught).
