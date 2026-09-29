# SHAPES-LEARN-08: WordNet's nouns, said by the substrate and learned from what it said

**Finding (2026-09-29, run `20260929T154631Z`, 15/15).** Part 3 of the last step in
`docs/research/SHAPES_CHANGE_MAP.md` (§11f) works in the sandbox, on a uniform sample of 3,000 of WordNet's 161,225
records. A noun record carries what is so (`isa(child, parent)`) and the word WordNet writes each sense with. The
substrate says the fact through the frames it was taught, and learns the word, its kind and the fact from the pair.
No sentence is written from a template.

**Taught:**
- the five lessons through the one teaching path, none refused;
- then the sample: 1,319 nouns' facts, 175 named things' facts (taught as facts only; no frame taught yet says a
  name), and 1,506 definitions.

**Said and learned:**
- 1,275 of the 1,319 noun facts were said through the frames taught.
- The 44 not said name a sense with a word held so far only inside frames ("body part", "oil well").
- Every pair said was learned, none refused: 1,274 as a new word in the frame that said it, 1 as a missing link.

**Checked:**

| Check | Result |
|---|---|
| Every noun taught reads in "What is a/an <word>?", never taught with it, to the sense taught | 1,275/1,275 |
| The reasoning authority answers yes to facts taught (sampled) | 200/200 |
| Pairs WordNet does not relate answered yes | 0/200 |
| Facts taught, said, read back to themselves | 200/200 |
| Every sentence of the five lessons still reads | yes |

**Said, for example:** "A peludo is an armadillo.", "A collaborator is a traitor.", "A state is an administrative
district.", "A mythical monster is a monster."

**The cost, split by stage.** The run took 3,362 s, but the stages differ:
- **Word-class notes, 3,061 s.** The teaching path writes one note per word in WordNet's vocabulary ("'synovia' is
  used as a noun."), 75,833 of them, whatever the sample size. This is a one-time cost of the vocabulary, one
  memory at a time, at about 40 ms each.
- **Everything else, about 292 s:** the sample's facts, sentences and definitions, about 97 ms a record.
- **All 161,225 of WordNet's records** would take about 4.4 h, plus the one-time 51 min: about 5 h in all. The run
  record's own figure, 50 h, divides the one-time stage by the sample and is wrong.

**Limits:**
- **Nouns that take no "a"** are said with one anyway: "A paleoanthropology is a vertebrate paleontology.", "A fire
  tongs is a tongs."
- **Names.** "Thiosulfil" is written with a capital, as WordNet writes it, and with "a". Named things proper
  (WordNet's instances) are not said at all until a lesson teaches names.
- **Definitions** are read as before, and most do not read yet. They wait for the function-word lessons.
- **The code at run time.** The run loaded its code before the learner rule `_names_within` was added (§11f). That
  rule only stops a new name holding a held name of the same concept.

Run: `./venv_lyric/bin/python3 experiments/SHAPES-LEARN-08/experiment.py` (empties the sandbox first; about an
hour, most of it the word-class notes).
