# STRUCTURE-01: how the words of a sentence go together, learned from a treebank

**Claim.** The main model holds how the words of a sentence go together, learned from sentences analysed by hand,
and reads sentences it never held by it.

**Why.** The reader learned whole sentence frames with slots, and nothing between the words and the frames said which
words form a phrase or what role a word plays. Prose failed on both: "carbon dioxide and water" had no slot to stand
in, and "a" was read as the ampere (`docs/research/READING_PROSE_AT_SCALE.md`). The owner chose (2026-10-16) that
Lyric learns phrase structure itself from a treebank.

**What is taught** (`scripts/teach.py --source treebank`, through the learning authority, `learn_structure`): the
English Web Treebank's training part (UD English EWT 2.18, CC BY-SA 4.0, 12,544 sentences), each kept by memory
whole, as it was analysed (one memory per use of a sentence, tag `analysed_sentence`), its standing a belief on that
memory. Reading (`core/semantics/structure.py`) decides each word's class, then each step of the structure, by what
the sentences held did in the most specific situation like it they met: memory-based learning.

**What it measures** (read only, from the store's own view, warmed from memory):

| Measure | On | Bar (fixed before the run) |
|---|---|---|
| Classes right | the treebank's dev and test parts, held out from teaching | ≥ 91% |
| The word each depends on, right (UAS) | the same | ≥ 72% |
| That, with the relation right (LAS) | the same | ≥ 65% |

The bars are the method's own numbers, measured on the treebank's files before anything was taught (dev: classes
91.9%, UAS 73.1%, LAS 66.2%): read from memory, it must do as well, or memory holds less than was taught. It also reads
the 33 prose sentences of UNDERSTANDS-PROSE-01 and shows their phrases, and checks the store was not written to.

**Two ways, one run** (since 2026-10-16 (10)): as the treebank alone decides, and with a word no sentence held used
taking a class memory holds of it (`StructureView.held_classes`, from the reader's word-class view, through the
shapes it learned: "breathes" as `breathe`). The bars apply to both; the prose shows where the two read otherwise.
Since 2026-10-17 main's own structure view asks memory (`MemoryAgent._new_structure_view`): it measured better both
ways; "treebank only" stays measured beside it.

**Run** (from the Lyric folder, after the treebank is taught; starts no substrate):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-01/experiment.py
```

**Results:** `results/<UTC timestamp>.json` and `.md`, the prose read beside them, and `results/run.log`.

**Runs on main:**

| Run | Code | dev: classes / UAS / LAS | test: classes / UAS / LAS | Checks | Written |
|---|---|---|---|---|---|
| `20261016T205339Z` | c203650 | 91.8% / 73.2% / 66.3% | 92.0% / 73.7% / 67.0% | 9/9 | nothing |
| `20261016T212354Z` | 85e5d10: a tie is decided by the next situation | 92.0% / 73.6% / 66.9% | 92.3% / 73.8% / 67.5% | 9/9 | nothing |
| `20261016T231035Z` | 0c624fd, treebank only | 92.0% / 73.6% / 66.9% | 92.3% / 73.8% / 67.5% | 15/15 | nothing |
| `20261016T231035Z` | 0c624fd, with memory's word classes (a noun held as a noun only) | 91.8% / 73.6% / 66.9% | 92.1% / 74.0% / 67.7% | (same run) | nothing |
| `20261017T001822Z`, `20261017T013101Z` | 330c932, treebank only | 92.0% / 73.6% / 66.9% | 92.3% / 73.8% / 67.5% | 15/15 | nothing |
| `20261017T001822Z`, `20261017T013101Z` | 330c932, with memory's word classes (a noun held as a noun or a name) | **92.2% / 73.7% / 67.0%** | **92.5% / 74.2% / 67.9%** | (same runs) | nothing |

For each run, the same code reading the treebank's files gives the same to four places, and the same reading of
every prose sentence, treebank only (the other way needs main's word classes): memory holds what was taught. The file numbers above (91.9%, 73.1%, 66.2%) were measured with an
earlier state of `structure.py`; the bars stand as fixed. Lab notebook 2026-10-16 (7) and (8).
