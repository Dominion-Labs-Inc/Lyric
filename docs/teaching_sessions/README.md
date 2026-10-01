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

### 2026-09-29 — the English lessons, into the main model (`lyric_db`)

Taught through `scripts/teach.py --source lesson`, a live substrate each time, after each lesson passed in the sandbox.
A lesson teaches sentence–meaning examples: its constructions and links are memories, each with a belief, and it adds
no concepts or links between concepts.

| When (UTC) | Lesson | Patterns | Beliefs prior → after | Report |
|---|---|---|---|---|
| 13:07 | english_01 | 228 read or learned, none refused | 57,006 → 57,556 | [report](20260929T130724Z_lesson.md) |
| 13:08 | english_02 | 29, none refused | 57,556 → 57,639 | [report](20260929T130807Z_lesson.md) |
| 21:19 | english_01 again | all 228 already read | 57,640 → 58,638 (+998, the start-up's, below) | [report](20260929T211922Z_lesson.md) |
| 21:19 | english_02 again | all 29 already read | 58,638 → 58,638 | [report](20260929T211957Z_lesson.md) |
| 21:20 | english_03 | 21, none refused | 58,638 → 58,700 | [report](20260929T212032Z_lesson.md) |
| 21:21 | english_04 | 70, none refused | 58,700 → 58,875 | [report](20260929T212108Z_lesson.md) |
| 21:21 | english_05 | 52, none refused | 58,875 → 58,990 | [report](20260929T212144Z_lesson.md) |
| 21:22 | english_06 | 77, none refused | 58,990 → 59,161 | [report](20260929T212221Z_lesson.md) |
| 21:22 | english_07 | 101, none refused | 59,161 → 59,380 | [report](20260929T212258Z_lesson.md) |

- **Read again, not doubled.** english_01 and english_02 were taught again with the rest. A belief moves once per
  example, so reading them again moved none.
- **Not identical to the sandbox.** Those two lessons were learned in the morning by an earlier learner, so the main
  model keeps their constructions as learned then ("An eel" as a name). It differs from the sandbox by 31
  constructions of english_01 and 28 of english_02; english_03 to 07 differ by at most 5 each.
- **The +998 at 21:19 came from the first start-up in the renamed folder, not from teaching.** The substrate looked
  at its surroundings: the machine, and the Lyric folder's files by name, size and extension. That wrote 527
  concepts and 989 beliefs under `environment_dc1455ad4d39ee9c`, and it saw one image. Later start-ups added
  nothing.
- **Checked, read-only, against the main model's own view** (every table counted before and after; the checks wrote
  only 4 performance-log rows, the database's own logging):
  - all 578 taught sentences read to their meaning;
  - never-taught sentences read 15/15 with function words, and 9/9 with names, words without "a" and kinds of
    people;
  - on a WordNet sample, about 1,300 of 1,400 nouns are said. None has a name or uncounted word after "a", none has
    a counted word bare, and none has "a"/"an" against the letter;
  - SHAPES-LEARN-08's and SHAPES-LEARN-09's faults are all said rightly.
- **Two engine faults the check found, both fixed** (`SHAPES_CHANGE_MAP.md` §11f):
  - a view warmed from memory lost which words are names;
  - a word never held went bare into a slot whose fillers all begin with "a".

**Cleared and taught again (21:57–22:02 UTC, the owner's word).** To bring english_01 and 02 up to the current
learner, and 03 to 07 on top of them in order, the seven lessons' English was cleared from `lyric_db`:
- 1,412 construction and link memories and the 1,374 beliefs held of them were removed through the memory agent
  (`delete_memory`, `drop_belief`);
- each removal was recorded in the ledger (`learning.patterns.cleared`);
- everything removed was archived first to `data/snapshots/english_lessons_lyric_db_20260929T215742Z.json`;
- the belief that the substrate has learned `english` was kept, and nothing else was touched.

english_01 to 07 were then taught again, none refused (reports `20260929T215837Z` to `20260929T220218Z`), after two
more engine fixes: a kind statement names a kind in each place, and saying counts shapes over the concepts whose
plural is held.

Checked read-only against the main model's own view:
- its constructions and links are identical by key to the sandbox's, lesson for lesson (1,417);
- all 578 taught sentences read, and never-taught sentences 15/15 and 9/9;
- on the WordNet sample, 1,239 of 1,379 nouns are said, with no "a" wrong, no counted word bare and no "a"/"an"
  against the letter;
- the five faults are said rightly.

### 2026-09-30 — all twenty-six English lessons, into the main model (`lyric_db`)

english_08 to 26 are the grammar lessons (08–23) and the mathematics lessons (24–26: numbers to the trillions,
arithmetic said in words, written formulas). All twenty-six were first taught into a sandbox emptied for them, and
checked there; then the main model's lesson English was cleared and the twenty-six taught in order.

- **Sandbox** (`lyric_dev`, reset first; reports `20260930T052122Z` to `20260930T053652Z`): every lesson learned,
  none refused, each exactly as the in-memory run learned it.
- **Cleared from `lyric_db`** (05:43 UTC, the owner's word to run the teaching again): 1,417 construction and link
  memories and the 1,380 beliefs held of them, through the memory agent, each removal in the ledger
  (`learning.patterns.cleared`), everything archived first to
  `data/snapshots/english_lessons_lyric_db_20260930T054318Z.json`; the belief that the substrate has learned
  `english` was kept.
- **Taught** (05:43–06:01 UTC; reports `20260930T054407Z` to `20260930T060119Z`): all twenty-six, none refused. A
  lesson's sentences are examples: they teach constructions and links, and no fact is held from them.
- **Checked read-only against the main model's own view** (every table counted before and after; the check wrote
  only 4 performance-log rows): 6,077 constructions and links, the same as the sandbox's; all 2,485 taught sentences
  read to their meaning; every never-taught probe set of lessons 8–23 passes but one sentence of lesson 12's ("The
  cat walked carefully.", below); lessons 24–26's never-taught sentences 73/73; eleven questions worked through the
  symbolic mathematics faculty from the main model's reading, all right; the WordNet sample said with no "a" wrong
  and no counted word bare (the check flagged "A is a blood group." and "Provitamin A is a provitamin." as "a"/"an"
  against the letter: the "A" there is a name, and both are said rightly).
- **"The cat walked carefully."** read "carefully" as a quality of its own, where memory reads it as `careful`
  written in "-ly". The store's teaching had linked a few modal words ("could" for `possible`) to the adjective slot
  of "red ball", so that slot counted as written otherwise, and one "recently" among them made it a slot written in
  "-ly" whose other words broke the change. Fixed in the reader, not in what was taught: a slot is evidence of a
  change only when most of what stands there written otherwise is written by one. Learning is unchanged by it (the
  same 6,082 items in memory), so neither store was taught again.
- **Cleared and taught again (10:57–11:16 UTC).** SHAPES-LEARN-10's fourth run showed english_24 had taught "a" as the
  number 1, and three more faults behind it (its README; `SHAPES_CHANGE_MAP.md` §11f). With the lessons and the reader
  fixed, the twenty-six were taught into an emptied sandbox (none refused, checked clean), then the main model's lesson
  English was cleared again -- 6,077 memories and 6,002 beliefs, archived first to
  `data/snapshots/english_lessons_lyric_db_20260930T105755Z.json`, removed through the memory agent -- and the
  twenty-six taught again, none refused. The clear's ledger write failed after the removals: 6,077 rows at eleven
  values each is more than one statement carries, so `record_knowledge_updates` now writes in as many statements as
  it takes, and the 6,077 rows were then recorded from the archive (`learning.patterns.cleared`, batch
  `clear-english-20260930T105755Z`).
- **Checked read-only** from the main model's view: 6,087 constructions and links, the same as the sandbox's but for
  five of lessons 1 and 4; "a" and "an" build sentences only; 2,492/2,492 taught sentences read; every never-taught set
  passes, lessons 24–26's 77/77; eleven questions worked through the faculty, all right; WordNet's sample said with
  nothing wrong.

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
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
  ./venv_lyric/bin/python3 scripts/teach_session.py --limit 2000 --label <name>
```

Omit `--limit` to teach the full WordNet English taxonomy. Every run snapshots the
substrate before and after and writes a `<ts>_<label>.md` report here automatically.
