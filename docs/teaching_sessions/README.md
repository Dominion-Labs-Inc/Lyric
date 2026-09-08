# Teaching sessions — the learning log

Every fact below is taught through the ONE learning pipeline in
the coordinator (`coord.learning` → `UnifiedLearningSystem.learn_facts`), with fan-out
**on**, so a taught `child isa parent` fact reaches the substrate's three durable
stores: **beliefs**, the **domain**, and the **lexicon**. Each session is snapshotted
before and after and written to its own timestamped report in this folder; this file is
the index that ties them together.*

> **How teaching works end-to-end** — the one path, admission, fan-out (beliefs /
> lexicon / domain / metrics), the O(1) belief index, sourcing, and the scaling
> rules — is documented in [`../TEACHING_ARCHITECTURE.md`](../TEACHING_ARCHITECTURE.md).
> Read it before running a large teaching session.

## What "teach a fact" does

Teaching is not a table insert. A single `child isa parent` fact fans out:

1. **Concept store** — the subject and object are admitted as concepts and the `isa`
   relation is linked (this is the taxonomy the reasoner walks).
2. **Beliefs** — the fact is observed as a *claim* in the Bayesian layer
   (`observe_claim`, source `taught`). This is graded, not binary: the posterior rises
   with evidence and is updated **in place** by proposition key, so re-teaching a known
   fact reinforces its belief rather than duplicating it.
3. **Lexicon** — the words carry their parts of speech (`learn_words`, WordNet POS),
   so the reader's vocabulary grows.
4. **Domain** — facts accumulate under their subject domain (`lexical` for the WordNet
   English taxonomy). Bulk teaching now crystallizes the taught domain **immediately**
   through the single domain authority (`UniversalDomainMaster.ensure_domain`, idempotent):
   teaching under a domain the substrate has never held registers it as a first-class
   Domain on the spot, rather than waiting for the idle domain-discovery tier. Verified:
   teaching 5 facts under a fresh domain took the domain store 22 → 23, the new domain
   present immediately. The conversational path keeps its deferred emit (off the reply
   path); both routes go through the one owner, never a second registrar.

**Each taught fact affects beliefs individually.** Bulk teaching used to write a single
summary belief per batch (`"N taught facts"`); the belief fan-out now iterates the
admitted clauses and observes **one belief per fact** (the real proposition). Verified:
2,000 facts → +1,899 distinct per-fact beliefs (a handful of identical propositions
collapse, correctly), never one summary row.

## Sessions

| When (UTC) | Label | Facts taught | Beliefs prior → after | Effect | Report |
|---|---|--:|---|---|---|
| 2026-09-08 01:45 | `wordnet-validate` | 1,200 | validating batch | first fan-out check | [report](20260908T014505Z_wordnet-validate.md) |
| 2026-09-08 01:50 | `wordnet-validate2` | 1,200 | validating batch | per-fact belief confirm | [report](20260908T015016Z_wordnet-validate2.md) |
| 2026-09-08 02:09 | `wordnet-round1` | 2,000 (`isa`) | **2,815 → 4,714 (+1,899)** | per-fact beliefs backfilled | [report](20260908T020931Z_wordnet-round1.md) |
| 2026-09-08 02:11 | `wordnet-round2-reteach` | same 2,000 (`isa`) | **4,714 → 4,714 (+0)** | reinforcement, no duplicates | [report](20260908T021129Z_wordnet-round2-reteach.md) |
| 2026-09-08 (drain) | `conceptnet-english` | 221,203 (`isa`) | concepts 175k → **256,049** | full English taxonomy admitted (offline bulk dump) | — |
| 2026-09-08 16:48 | `conceptnet-english-beliefs` | 221,203 (`isa`) | **33,114 → 195,718** (`general` 28,588 → 191,192) | per-fact beliefs, batched + flushed, O(1) index | [report](20260908T164829Z_conceptnet-english-beliefs.md) |

### ConceptNet English drain — the full taxonomy, and the O(1) belief fix

Teaching the entire ConceptNet English `IsA` taxonomy (221,203 unique edges, from a
downloaded bulk dump — no live queries) admitted the concepts (**175k → 256,049**) and
then established one Bayesian belief per fact. This is where we found and fixed the
defect behind ~13 hours of failed runs: `observe_claim` was finding beliefs by a
**linear scan over every belief in memory** — O(n²) across a run, so the rate decayed
(≈750 → 180 obs/s and falling) and multi-hour runs stalled having committed nothing.

A `claim → belief_id` **index** made `observe_claim` O(1): **~68,000 obs/s flat** at
36k beliefs (was ~180 and falling). The belief backfill then ran as a **batched,
flushed** pass (commit per batch, memory flat, count watchable) and completed:
`general` beliefs **28,588 → 191,192**, total **33,114 → 195,718**. The gap between
221k propositions and ~162k *new* beliefs is correct idempotency — facts already held
in another domain (e.g. WordNet `lexical`) were reinforced in place via the global
claim index, not duplicated into `general`.

### Round 1 — teaching creates per-fact beliefs

Teaching the first 2,000 nouns of the WordNet taxonomy added **1,899 distinct beliefs**,
all in the `lexical` domain (183 → 2,082). The concept count did **not** move
(175,166 → 175,166): the substrate already knew these as concepts — this session
*backfilled the beliefs it had never held*, because the pre-fix fan-out only wrote one
summary belief per batch. Each new belief is a real proposition
(`abrader isa tool → 0.9926`, `ascender isa mover → 0.9926`), the single-observation
value.

### Round 2 — teaching again reinforces, it does not duplicate

Re-teaching the **same** 2,000 facts admitted all 1,997 again at the fact layer but added
**zero** new beliefs — `observe_claim` updates the existing belief in place. What moved is
the **posterior**: a second supporting observation raised the re-taught facts from the
one-observation value to the two-observation value.

| Belief (domain `lexical`) | After round 1 (1 obs) | After round 2 (2 obs) |
|---|--:|--:|
| `abrader isa tool` | 0.9926 | **0.9995** |
| `abortion isa termination` | 0.9926 | **0.9995** |
| `ascender isa mover` | 0.9926 | **0.9995** |
| `asceticism isa doctrine` | 0.9926 | **0.9995** |

Distribution of the `lexical` posteriors after both rounds — the reinforcement is visible
as a population shift, not a single anecdote:

| Posterior | Count | Meaning |
|--:|--:|---|
| 0.9926 | 86 | taught once |
| 0.9995 | 1,899 | taught twice (round 1 + round 2) |
| 1.0000 | 97 | saturated |

This is the whole point of representing knowledge as *graded beliefs* rather than flat
rows: repeated, independent teaching of the same fact **raises confidence** (Bayesian
update, model-free), while the belief store stays free of duplicates.

## Substrate state after these sessions

- **Beliefs:** 4,714 total (2,082 in `lexical`).
- **Domains:** 21 (the `lexical` domain reinforced). Bulk teaching now crystallizes a
  taught domain immediately through the one domain authority, so a *new* subject domain
  appears the moment it is taught (verified: a fresh domain took the store 22 → 23 on the
  spot) — the idle domain-discovery tier remains the backstop.
- **Lexicon:** 73,010 words with parts of speech.
- **Concepts:** 175,166 (unchanged by these sessions — the taxonomy was already present;
  these sessions established the *beliefs* over it).

## How to run a session

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
  ./venv_torin/bin/python3 scripts/teach_session.py --limit 2000 --label <name>
```

Omit `--limit` to teach the full WordNet English taxonomy. Every run snapshots the
substrate before and after and writes a `<ts>_<label>.md` report here automatically.
