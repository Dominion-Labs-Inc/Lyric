# Semantics (write) — `CognitiveIngress`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

## `CognitiveIngress` — the semantics-write authority (the one door)

*`core/semantics/cognitive_ingress.py` · `get_cognitive_ingress()`.*

### 1. Purpose
**The one door knowledge comes through.** A sentence that has been *read* is not yet knowledge — something must admit it. Division of labour: **the reader interprets, the ingress admits, reasoning consumes.** It admits each proposition ONCE, with provenance, and fans it to every store with a stake: concepts (via `ConceptIngestionService`, the declared sole writer of `unified.concepts`), aliases (surface word → concept), evidence (the sentence as root of belief), memory (the recallable episode). It does NOT decide truth — epistemic status follows from accumulated independent evidence, not from who said it.

### 2. The `Admission` object & the quality floor
`@dataclass Admission` — the record of what admitting one proposition did; every field a count/flag: `proposition`, `surface`, `admitted`, `already_present`, `concepts_created`, `concepts_reinforced`, `aliases_bound`, `memories`, `memory_id` (the semantic memory this admission made, so a later feedback turn flags *that* record), `evidence_id`, `polarity`, `contradicts` (surfaced, never silently resolved), `refusals`; plus a `summary` property.
`MIN_ADMIT_QUALITY = 0.5` — **the support floor**: below this evidence quality the gate *refuses* (true absence — no concept, no belief) rather than minting a weakly-held belief. Conservative default; a stricter deployment raises it.
Support: `@dataclass Provenance` (required — no anonymous entry); `NEVER_A_TERM` stopwords, `MAX_RELATION_WORDS=4`; `MAX_TERM_WORDS=4` is the reader's rule for coining a name from a run of words and is no longer asked at the door (2026-11-15).

### 3. Methods by area

#### Admissibility checks (module-level)
- **`admissible(term) -> (bool, str)`** — whether a term may name a concept: admits well-formed numerals/dates (`classify_literal`), refuses empties, over-length clauses, pure-stopword strings, bare numbers. **The door checks, not the caller.**
- **`admissible_relation(relation) -> (bool, str)`** — different tests than a term (copulas `is`/`in`/`of` are exactly what relations look like); disqualifies only clauses — over-length or determiner-carrying.
- **`normalize_term(term) -> str`** — canonical form (via `lexical_normalization.canonical_term`: strip determiners, singularize; NOT `canonical_label` doc heuristics) — enforces one-surface-one-interpretation at the single door.
- **`_parse(proposition)`** — decodes the reader's atom (`cup_in_cabinet`→`(cup,in,cabinet,positive)`; leading `~`=negative).

#### `CognitiveIngress` class
- **`__init__(db_manager=None)`** — optional DB manager, lazy `ConceptIngestionService`, `_seen` idempotency set.
- **`async _ingestion()`** — lazily caches the `ConceptIngestionService` (sole writer of `unified.concepts`).

**Admit entry points**
- **`async admit(proposition, surface, provenance, word_class_of=None) -> Admission`** — admit a read proposition (atom form); idempotent per `(proposition, source_id)` via SHA in `_seen`; validate source type; parse; → `_admit_parts`.
- **`async admit_relation(subject, relation, obj, surface, provenance, positive=True, description="", domain="language", word_class_of=None, remember=True, quality=1.0) -> Admission`** — admit a proposition already split into parts (lossless where the atom form isn't); enforces `MIN_ADMIT_QUALITY`, idempotency, and `remember=False` (concept graph without a recallable episode, for bulk taxonomies).
- **`async _admit_parts(...)`** — **the one admission every caller funnels to.** Normalize terms, run `admissible`/`admissible_relation`, type each term, build the `EvidenceEnvelope` (concepts + relation with polarity), call the ingestion service, then fan out to `_remember`, `_bind_aliases`, `_contradiction_check`, set `admitted`.

**Held conditionals**
- **`_CONDITIONALS_DDL`** · **`async _ensure_conditionals_schema`** · **`@staticmethod _clause_key(prop)`** · **`async admit_conditional(antecedent, consequent, *, surface, provenance, domain="language") -> Admission`** (admit a taught conditional as a first-class held rule; both clauses pass the same gates a fact passes; the implication is stored while neither side is asserted) · **`async held_conditionals(domain=None) -> List[Dict]`** (returns the told conditionals for the reasoner to consume as held rules — never re-parsed from surface).

**Fan-out helpers**
- **`async _remember(proposition, surface, provenance, result) -> int`** — stores the claim as a SEMANTIC memory (importance 0.75); records `result.memory_id`; a declined filter is surfaced as a refusal, not a write.
- **`async _bind_aliases(terms, provenance) -> int`** — binds each surface word to its concept in `unified.concept_aliases` (**what makes a word mean something**); `RETURNING` distinguishes a real write from an `ON CONFLICT DO NOTHING` skip.
- **`async _contradiction_check(subject, relation, obj) -> Optional[Dict]`** — queries `unified.concept_relations` for a positive/negative polarity clash; returns the conflicting evidence ids (surfaced, never auto-resolved).

**Singleton**
- **`get_cognitive_ingress()`** — the global one-door instance.

### 4. Feeds / feeds-into
**Consumes:** `ConceptIngestionService` (`EvidenceEnvelope`, `EvidenceSourceType`, sole writer of `unified.concepts`); `literals.classify_literal`; `lexical_normalization.canonical_term`; `memory.get_memory_agent` (the recallable episode); tables `unified.concept_aliases`, `unified.concept_relations`, `unified.held_conditionals`.
**Called by:** the learning authority alone. `UnifiedLearningSystem._admit_to_world` and `consider_many` call `admit_relation`, and `consider_rule` calls `admit_conditional` — so everything taught reaches the door through `consider` ([learning.md](learning.md) §2), and the door has one upstream rather than many. The reasoning authority consumes `held_conditionals()` in `_answer_over_held_rules`. Downstream, the returned `Admission` — its `memory_id`, `contradicts` and `refusals` — lets a later turn flag or reconcile the exact record an interaction produced.
