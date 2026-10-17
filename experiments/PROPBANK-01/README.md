# PROPBANK-01: is every role PropBank gives the treebank said in Lyric's meaning language?

**Claim.** Every role PropBank gives the English Web Treebank is said in Lyric's meaning language: a fact in a link
kind it has, a rule its words settle, or nothing; what is not is a named gap, a kind or term to decide.

**Why.** Learning constructions over phrases needs sentences whose phrases are given their roles. PropBank gives them
for the whole treebank Lyric's structure was learned from, but a role the meaning language cannot say would lose part
of a sentence's meaning. The owner judged a mapping of most roles not enough: every label must be accounted for
before PropBank is taught.

**The data** (read from files; the store is not touched):

| Source | What | Licence |
|---|---|---|
| `propbank-release`, `data/google/ewt` | the annotations: each predicate's sense and the role of each phrase; each word written `[WORD]` | CC BY-SA 4.0 |
| `propbank-frames` (release 3.x) | each sense's roles: function tag, VerbNet role, description | CC BY-SA 4.0 |
| UD English EWT 2.18 | the words, by document, sentence and place (the same sentences the LDC's copy holds) | CC BY-SA 4.0 |

**The mapping** is `core/semantics/propbank_roles.py` (tests: `tests/test_propbank_roles.py`): each label, each
function tag and VerbNet role of a numbered argument, each predicate the lessons say in a link kind of their own
(`have.03` as `owns`, `need.01` as `requires`, `be.01` predicated), and every word that begins a modifier whose kind
the label leaves open (the modals, the discourse markers, the comparisons; time, place, direction, manner and the
other adverbials by their first word, with a default each).

**What it measures:** the share of the treebank's arguments said in the meaning language; what each named gap
holds; each label and numbered argument nothing maps; how each predicate is said (a happening, nothing, a quality);
and of the happenings, the share whose word WordNet holds a sense of in its part of speech (a noun predicate is
written with its verb's lemma: "agreement" as `agree`).

**Run** (from the Lyric folder; reads files only, about 10 seconds):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/PROPBANK-01/experiment.py
```

with `test_data/syntax/` holding `propbank-release`, `propbank-frames` (both cloned from github.com/propbank) and
`UD_English-EWT`; `--data DIR` reads them from elsewhere.

**Results:** `results/<UTC timestamp>.json` and `.md`, `_by_label.json` (each label: how its arguments are said)
and `_unmapped.json` beside them.

**Runs:**

| Run | Where | Arguments said | Needs a decision | Unmapped | Checks |
|---|---|---|---|---|---|
| `20261017T135256Z` | a cloud session, code 3502730 | 98.51% | 1.46% | 0.03% (33) | 4/4 |

The gaps (1,460 arguments, and 245 predicates of "have to"): **possible** 551 ("might", "maybe", "probably"),
**necessary** 455 ("must", "should"; and "have to"), **between sentences** 390 ("but", "however", "so", "then", "or"),
**felt** 64 ("wow", "ugh", "lol"). The 33 unmapped are words PropBank's own annotation gives a label they cannot have
(the modal "i", "most", "cold"). Of the happenings, WordNet names 99.8%; the rest are words it does not hold ("xray",
"preorder", "reprioritize"), which the reader takes as new.
