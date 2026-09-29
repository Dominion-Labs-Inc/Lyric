# KNOWS-WORDNET-01 — does the substrate KNOW what it was taught?

**Why this exists.** A teaching run reports how many facts it **admitted**. That is a
claim about the writer, not about the substrate: it says an edge was accepted, not that
the substrate can be asked and will answer. Before a large teaching run, the question
worth asking is the second one, and nothing was measuring it.

**Source of truth.** `WordNetSource` itself — the same records the teaching pass offers.
The question is always *"you were offered this; do you hold it?"*, never a question about
some other corpus. **Nothing is taught by this experiment. It only asks.**

## Four levels, reported separately

They are different claims and collapsing them would hide which one fails.

| level | what it reads |
|---|---|
| **ADMITTED** | the edge is in `unified.concept_relations` (a store read) |
| **DERIVABLE** | `answer_over_graph` returns TRUE when asked — so a fact reachable only by transitivity still counts as known |
| **CLASSED** | the part of speech the source STATED is among those with net-positive evidence in the memory agent's warm view (polysemy is not a contradiction) |
| **SAYABLE** | the conversation path puts the fact back into words |

## The negative control is not optional

Without it the four figures above are unfalsifiable: a substrate that answers YES to
everything scores 100% on recall. **INVENTED** asks about pairs built from real WordNet
terms that WordNet does **not** relate — any pair the source actually asserts is dropped
first, so a YES there is a fact the substrate invented rather than one it was taught.

A run is only meaningful with both halves read together. **INVENTED must be ~0.**

## Run

```
./venv_lyric/bin/python3 experiments/KNOWS-WORDNET-01/experiment.py [N]
```

`N` is the sample size per level (default 500). The sample is seeded (`SEED = 20260924`),
so two runs against different stores ask the same questions and are comparable.

Each run writes a structured record to `results/<timestamp>.json`.
