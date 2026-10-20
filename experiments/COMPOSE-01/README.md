# COMPOSE-01: what a sentence means, composed from how its words go together

**Claim.** What a sentence means, in Lyric's meaning language, is composed from how its words go together (the
structure reader's reading), learned from the lessons: which word stands for what, and which fact two words' places
say.

**Why.** The reader learned whole sentence frames with slots over word strings; prose holds sentences no frame
matches (`docs/research/READING_PROSE_AT_SCALE.md`). The plan's step 3 (handoff): compose a sentence's meaning from
its phrases, so a sentence never taught is read as the sentences that stand as it does were.

**How** (`core/semantics/composition.py`; as built 2026-10-17, rebuilt 2026-10-20 to compose over the structure,
`experiments/PMB-01`): each lesson sentence, read and laid out with its words named
(`composition.lay`; a run joined as compound or flat is one name), is aligned to its taught meaning
(`composition.align`), and five things are counted in the situations they stood in: what each word stands for,
which facts two words' terms hold, which facts a word holds with a term of the situation's or the grammar's own, the
flags each clause puts on its facts, and the act. A sentence is composed by the most specific situation met for
each. Where the lessons say nothing particular, a general situation is gone by only where met often and saying one
thing (`TRUST`), then PropBank's arguments (`argument_structure.learned_from_propbank`), then one readable sense for
each relation of the structure (`RELATION_SENSES`). Lab notebook 2026-10-17 (16), (17).

**What it measures** (files only, no store): the lessons ten ways, learned from nine tenths of the sentences, each of
the tenth held out composed and compared whole with its taught meaning, written canonically; and with names aside,
where only the names differ (the lessons name some things by sense, which memory gives and a lemma from the files
cannot). The 298 sentences of arithmetic are left to the arithmetic reader. Then the 33 sentences of
UNDERSTANDS-PROSE-01, composed with all the lessons learned, kept in `results/<stamp>_prose.json`. No bar: measured.

Names come from files: a word's plain form by WordNet, else by the treebank's lemmas; a name of several words as
WordNet holds it; a word the treebank never used limited to the classes WordNet gives it (standing in for memory's
word classes). On main the names are memory's.

**Run** (from the Lyric folder; about ten minutes):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/COMPOSE-01/experiment.py
```

with `test_data/syntax/` holding `propbank-release`, `propbank-frames` and `UD_English-EWT` (`--data DIR`), the
lessons in `data/lessons/` (`--lessons DIR`), and WordNet for `nltk`.

**Results:** `results/<UTC timestamp>.json` and `.md`, the prose composed (`_prose.json`) and 300 of the lessons
held out not composed as taught (`_missed.json`).

**Runs:**

| Run | Where | Lessons held out: as taught | names aside | no meaning | Prose: a meaning composed |
|---|---|---|---|---|---|
| `20261017T181328Z` | a cloud session (the lessons read through the gateway), code 71e6151 | 50.1% | 52.4% | 8.7% | 29 of 33 |
| `20261020T164055Z` | the Mac, files only; the composer rebuilt to compose over the structure (lab notebook 2026-10-20 (27)), learned from the lessons with PropBank's arguments behind them | 50.6% | 52.6% | 8.9% | 31 of 33 |
| `20261020T185728Z` | the Mac, files only; pronouns named as the lessons name them (lab notebook 2026-10-20 (28)) | 52.5% | 54.4% | 9.1% | 31 of 33 |
| `20261020T210127Z` | the Mac, files only; a subject stands for nothing only under the verbs it was learned to (lab notebook 2026-10-20 (30)) | 52.1% | 54.0% | 9.1% | 31 of 33 |

Of the prose, about six are composed as a reader means them ("Whales are mammals.", "They live in the ocean.", "A
whale breathes air through a blowhole.", "The valve is closed.", "Seven is a prime number.", "The company hired
three engineers in May." but for "in May") and about six more nearly; the rest are wrong, most of them where the
structure is (lab notebook 2026-10-17 (17)).
