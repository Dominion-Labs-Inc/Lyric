# Teaching Architecture — how the substrate is taught, end to end

*Canonical reference for TorinAI's teaching path. Model-free (no LLM). Written
against the running code with `file:line` anchors so future teaching runs stop
repeating the mistakes that cost us ~13 hours of failed sessions. If you change
the pipeline, update this document.*

---

## 0. TL;DR — the rules that matter

1. **There is ONE teaching path:** `coord.learning` (`UnifiedLearningSystem`).
   Everything — a single fact, a whole taxonomy, a taught word, a conversational
   `teach()` — funnels through `learn_fact` / `learn_facts` / `learn_word(s)` and
   the shared `_fan_out_learning`. Do not write a second path.
2. **A taught fact fans out to four stores:** the **concept graph**, **beliefs**,
   the **lexicon**, and the **domain** — plus **metrics**. Each arm is isolated;
   one failing never rolls back the others.
3. **Beliefs are per-fact and Bayesian.** Each taught fact is one `observe_claim`
   — find-or-create by claim, reinforce on repeat, never duplicate.
4. **Source data comes from OFFLINE bulk dumps** (WordNet via nltk; ConceptNet
   assertions file), never HTTP-per-query against a live endpoint.
5. **Teach at scale in BATCHES with a flush per batch** so beliefs commit
   incrementally and memory stays flat. Never one giant single call.
6. **Long runs are detached** (`nohup … & disown`, verify `PPID 1`) and logged to
   a file, so closing a terminal or the session never kills them.
7. **Verify by watching the DB belief count climb**, not by assuming success —
   belief writes are fire-and-forget and only durable after a flush.

---

## 1. The one teaching path

```
teach()/learn_fact/learn_facts/learn_words   (entry — coordinator faculty: coord.learning)
        │
        ▼
cognitive_ingress.admit_relation             (STAGE 1 — admit into the concept graph)
        │  (only NEWLY-admitted clauses continue)
        ▼
_fan_out_learning(clauses, domain, …)         (STAGE 2 — fan out, once, over admitted clauses)
        ├── LEXICON   observe_proposition(...)         → parts of speech (data/lexicon.json)
        ├── BELIEFS   observe_claim(...) PER CLAUSE     → unified.beliefs (Bayesian, per-fact)
        ├── METRICS   system_metrics / counts
        └── DOMAIN    emit(payload)  OR  ensure_domain  → unified.domains (crystallize)
```

**Entry points** (`core/learning/unified_learning_system.py`):
- `learn_fact(subject, relation, obj, …)` — one fact `:2111`
- `learn_facts(facts, *, provenance, domain, fan_out=True, remember=True, progress)` — bulk `:2141`
- `learn_word` `:2254` / `learn_words(words, source, authoritative)` `:2265` — lexicon POS
- `_fan_out_learning(*, surface, claim, clauses, positive, domain, emit, emit_payload, save_lexicon)` `:2407`

The conversational door is `coord.teach()` / `Conversation` (autonomous_coordinator),
which admits per sentence and emits `EvidenceAdmitted`, reacting into domain
crystallization. Bulk teaching (a taxonomy) calls `coord.learning.learn_facts`
directly.

---

## 2. Stage 1 — admission (the concept graph)

`cognitive_ingress.admit_relation(subject, relation, obj, surface, provenance,
positive, domain, remember)` (`core/semantics/cognitive_ingress.py:257`,
singleton `get_cognitive_ingress():647`) admits a `child isa parent` relation as
concepts + a typed edge — the taxonomy the reasoner walks. It returns an
`Admission` with `admitted` / `already_present` / (refused).

**Admit-gating — the trap that silently teaches zero beliefs.** `learn_facts`
fans out **only over clauses that were newly `admitted`** (`:2183`). Facts that
come back `already_present` are counted and **skipped** — they do NOT reach the
belief/lexicon/domain arms. Consequence:

> Re-running `learn_facts` over a taxonomy whose concepts are already in the store
> admits nothing new → fans out nothing → creates **zero** beliefs.

To establish beliefs over facts whose concepts already exist (a *backfill*), do
not go through admission — call the belief arm directly (see §7,
`scripts/teach_conceptnet_beliefs.py`).

Counts returned: `{admitted, already, refused, total}`.

---

## 3. Stage 2 — the fan-out (`_fan_out_learning`)

Runs once, over the list of admitted clauses. Each arm is wrapped in try/except.

### 3.1 Lexicon
`observe_proposition(surface, subj, rel, obj, source="taught", save=False)`
(`core/semantics/lexicon.py:196`; `get_lexicon():159`) records parts of speech so
the reader's vocabulary grows. In bulk it accumulates in memory and the file is
saved once (the 24 MB `data/lexicon.json` must not be rewritten per clause).

> **Cost warning:** `observe_proposition` is the *slowest* arm at scale (POS work
> per clause). At hundreds of thousands of clauses it dominates wall-clock. For a
> taxonomy-scale drain, run the lexicon enrichment as a separate, batched pass (or
> skip it) rather than inline in one giant fan-out.

### 3.2 Beliefs — per fact, Bayesian
`get_uncertainty_system().observe_claim(proposition, domain, supports, source="taught")`
(`core/reasoning/bayesian_uncertainty.py:282`). `_fan_out_learning` builds one
proposition per clause and calls `observe_claim` **once per fact** (`:2453` area) —
so a bulk teach forms one belief PER admitted fact, not a single "N taught facts"
summary. Singular `learn_fact` forms its one belief. Same substrate both ways.

`observe_claim` is **find-or-create by normalized claim key** (`_claim_key`):
- first telling → `create_belief` (prior reflects the telling),
- each later telling → `update_belief` on the SAME belief (reinforce/contradict).

Properties that follow:
- **Idempotent & de-duplicated.** Teaching the same fact twice does not spawn a
  second belief; it moves the posterior. Observed: `0.9926` (one obs) → `0.9995`
  (two obs) → `1.0000` (saturated).
- **Global by claim, not per-domain.** The claim index is global, so a fact taught
  into `general` that already exists as a `lexical` belief **reinforces the
  existing belief** rather than creating a `general` duplicate. (This is why a
  221k-proposition drain produced ~191k *new* `general` beliefs, not 221k — the
  remainder overlapped prior domains and were reinforced in place.)
- **Persistence is fire-and-forget.** Writes queue; they are durable only after
  `flush_pending_writes()` (`:1251`). The in-DB count therefore *lags* an
  in-progress run — verify by querying after a flush, not mid-batch.

> **THE performance rule (root cause of the wasted hours).** `observe_claim`'s
> find-by-claim MUST be O(1). It originally scanned every in-memory belief on each
> call — O(n) per call, **O(n²)** across a run — so the rate decayed (≈750→180
> obs/s and falling at 30k beliefs) and multi-hour runs stalled having committed
> nothing. Fixed with a `claim → belief_id` index (`self._claim_index`) maintained
> at every add/load/delete; `observe_claim` is now a dict lookup (~68,000 obs/s
> flat at 36k beliefs). **Never reintroduce a linear scan over `self.beliefs`.**

### 3.3 Metrics
`system_metrics["total_learning_sessions"]` is incremented per fan-out; the bulk
entry returns `{admitted, already, refused, total}`. Tool/execution metrics live
elsewhere (`_run_tool` → `tool_usage_history`); teaching metrics are these counts
plus the belief/concept/domain deltas a session report records.

### 3.4 Domain crystallization
`_fan_out_learning` crystallizes the taught domain two ways (one owner,
`UniversalDomainMaster`):
- **Conversational path:** an `emit(payload)` is wired → the crystallization runs
  **deferred**, off the reply path (Phase-3 reaction).
- **Standalone/bulk path (no event bus):** it calls
  `UniversalDomainMaster.ensure_domain(domain)` **immediately**
  (`core/integration/universal_domain_master.py:565`; `get_universal_domain_master():2398`),
  so bulk teaching registers a *new* subject domain on the spot instead of waiting
  for the idle domain-discovery tier. `ensure_domain` is idempotent.

---

## 4. Where the data comes from (sourcing)

- **WordNet** (offline, via `nltk`) — the English noun `isa` taxonomy (~147k
  hypernym edges) + POS. Zero network. `scripts/teach_session.py`.
- **ConceptNet 5.7.0 assertions** — one bulk file downloaded once to
  `data/bulk/conceptnet-assertions-5.7.0.csv.gz` (git-ignored); stream and keep
  English `/r/IsA` edges (221,203 unique). `scripts/teach_conceptnet.py`
  (admit + fan-out) and `scripts/teach_conceptnet_beliefs.py` (belief backfill).

> **Do NOT teach from live SPARQL-per-query.** The Wikidata Query Service enforces
> a ~60 s per-query limit and 504s / truncates on deep `P279*` closures; and
> chunking a mega-root by direct children explodes (e.g. `chemical compound` has
> 1,050,504 subclasses — a million queries). Named-entity roots (organization,
> event, taxon) are the wrong scope anyway. Use a bulk dump. `teach_general_wikidata.py`
> is retained only for small, bounded, chunk-guarded fetches.

---

## 5. How to run a teaching session correctly (checklist)

1. **Source from a local dump.** Parse offline into `(child, "isa", parent)`.
2. **Admit once** (concepts): `learn_facts(fan_out=…)` OR a prior admit run. If the
   concepts already exist, admission is a fast no-op (`already`).
3. **Beliefs at scale = a batched, flushed backfill.** Iterate the facts in chunks
   (~5,000), `observe_claim` each, `await flush_pending_writes()` after each chunk.
   Beliefs commit incrementally; memory stays flat; the DB count climbs live.
4. **Crystallize the domain** once via `ensure_domain(domain)` (idempotent).
5. **Lexicon** (optional at scale): a separate batched pass, not inline.
6. **Detach** the run: `nohup env … python3 script.py > logs/x.log 2>&1 </dev/null & disown`,
   then confirm `ps -o ppid -p <PID>` shows **1** (reparented to launchd).
7. **Verify while it runs:** `SELECT count(*) FROM unified.beliefs WHERE domain=…;`
   must climb. If the rate decays with size, something is O(n²) — stop and fix.
8. **Document the session** (§6).

---

## 6. Documentation & verification

Every run writes a prior→after report to `docs/teaching_sessions/<ts>_<label>.md`
(beliefs by domain, concepts, domains, elapsed). `docs/teaching_sessions/README.md`
is the index. A session is only "done" when the report's *after* counts are read
back from the DB **after the final flush** — not from mid-run progress lines.

**Verified reference numbers (this hardware, current code):**

| Operation | Rate / result |
|---|---|
| `observe_claim` (O(1), 36k beliefs in memory) | ~68,000 / s, flat |
| `observe_claim` (OLD O(n²), ~30k beliefs) | ~180 / s and falling — DO NOT SHIP |
| WordNet 2,000 facts, full fan-out | +1,899 per-fact beliefs, 42 s |
| Reinforcement on re-teach | 0.9926 → 0.9995 (one → two observations) |
| ConceptNet drain | 221,203 props → 256,049 concepts; +162k beliefs |

---

## 7. Failure modes we hit (so we don't again)

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Run pegs one CPU for hours, commits nothing | `observe_claim` O(n²) linear scan | claim index → O(1) (§3.2) |
| 2 | Single giant `learn_facts` never returns | fan-out over 200k+ clauses in one call (lexicon arm + O(n²) beliefs) | batch + flush per batch (§5) |
| 3 | Re-run "teaches" but 0 new beliefs | admit-gating: already-present facts skip fan-out | backfill via direct `observe_claim` (§2) |
| 4 | Live fetch 504s / hangs; chunking explodes | SPARQL-per-query + million-child mega-roots | bulk offline dump (§4) |
| 5 | DB count flat mid-run, looks broken | fire-and-forget writes lag until flush; re-covering an already-committed prefix reinforces (no new rows) | verify after flush; expect a flat prefix on resume |
| 6 | Run dies when terminal/session closes | attached to the shell | `nohup … & disown`, verify `PPID 1` (§5) |

---

## 7a. Source hygiene for the reasoning taxonomy (hard rules)

The reasoner walks the concept graph's `isa` edges as a transitive closure. That
graph is only as good as what is admitted into it, and one bad class of source
poisons all downstream reasoning.

- **Never admit crowd-sourced free text as reasoning `isa` edges.** Raw ConceptNet
  `/r/IsA` includes assertions like `apple isa car`, `dog isa cuter_than_kid`,
  `robin isa band` (Robin the singer). Admitted wholesale, these gave 450k `isa`
  edges where a term's ancestor set exploded 45&#8594;681 over 1&#8211;4 hops, and
  transitive `isa` became meaningless &#8212; the reasoner confabulated
  (`dog isa plant` via `organism&#8594;system&#8594;plan_of_action&#8594;plant`).
  The reasoning taxonomy must be a **curated** hypernymy (WordNet), not a crowd
  graph. ConceptNet-style data, if kept at all, belongs in *beliefs*, never as
  concept-graph edges the reasoner walks.
- **Record provenance per edge.** The cleanup was expensive because
  `concept_relations` recorded no source (WordNet vs ConceptNet both tag
  `extractor='structured'`), so junk could not be selectively retracted &#8212;
  it had to be separated by content against a WordNet reference set. Tag every
  admitted edge with its source so a noisy source can be dropped in one query.
- **Bound the common-sense closure.** Even on a clean graph, cap the `isa` walk
  (currently 4 hops): real common-sense subclass chains are short, and a long walk
  over any large name-keyed graph risks homonym drift. Abstain past the bound.
- **Beliefs back-stop the bounded graph.** When the graph cannot derive an `isa`
  within the bound, consult the belief store: a fact *taught* and held &#8805;0.99
  answers it (e.g. `copper isa metal`). An untaught claim has no such belief, so
  this restores recall WITHOUT reintroducing confabulation. (See
  `neural_bridge._answer_over_concept_graph`.)

These rules were learned the hard way; the audit that surfaced them is `KNOW-50`
(`experiments/systems/KNOW-50`), which asks the live substrate taught-knowledge
questions with answers withheld and displays what it reasons *and* what it
believes. Result after the fix: 37/40 true correct, 100% of answered correct,
0 confabulations, 0 model calls.

## 8. Critical files

- `core/learning/unified_learning_system.py` — the one path (`learn_fact:2111`,
  `learn_facts:2141`, `learn_words:2265`, `_fan_out_learning:2407`).
- `core/reasoning/bayesian_uncertainty.py` — beliefs (`observe_claim:282`,
  `create_belief:238`, `flush_pending_writes:1251`, `_claim_index`,
  `get_uncertainty_system:1771`).
- `core/semantics/cognitive_ingress.py` — admission (`admit_relation:257`).
- `core/semantics/lexicon.py` — lexicon (`observe_proposition:196`).
- `core/integration/universal_domain_master.py` — domains (`ensure_domain:565`).
- `scripts/teach_session.py` — WordNet teach (documented).
- `scripts/teach_conceptnet.py` — ConceptNet admit + fan-out (offline).
- `scripts/teach_conceptnet_beliefs.py` — batched, flushed belief backfill.
- `docs/teaching_sessions/` — per-session reports + the log index.
