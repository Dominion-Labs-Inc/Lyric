# Memory — `MemoryAgent`

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

*File:* `core/agents/memory_agent.py` — about 9,970 lines, almost all of them one class: `MemoryAgent`,
with **228 public and 107 private methods**. Utilities live in `core/memory/`; the class lives in `core/agents/`.

`get_memory_agent()` is the one entry — async, returning a **ready** singleton under a lock, and
raising if the backends will not connect. Callers await it and never construct `MemoryAgent()` directly.
`initialize_memory_agent()` is a legacy alias, as are the names `MemoryManager`,
`CentralizedMemoryManager` and `UnifiedMemorySystem`.

---

## 1. Memory is everything the substrate holds

The memory agent is **the only writer of the substrate's memory** — not only the memories, but the concepts
and the links between them, its beliefs, the rules it induced and the demonstrations it induced them from,
its domains, what its reasoning produced, what it has learned to see and hear, the record of what it
learned, and each person's context.

The parts that work out *what* to hold — the learning authority, the belief system, induction, the domain
master, the reasoning engines, perception — hand it here, and the memory agent writes it. **Nothing else
writes a memory table**, and `scripts/separation_map.py` fails if anything does.

Those writes need only the database, so they work whether or not recall, the loops and the embedding model
have started. Every one goes through `_memory_db()`, which hands back the process's own manager behind a
guard (`_KeylessWrites`) that keeps keys out of every concept, belief, rule and record written through it.

**The agent decides, the caller does not.** Callers pass raw content; the agent decides worthiness and type
itself. Passing a pre-computed importance is refused.

## 2. Tiers and search

| | |
|---|---|
| Hot | PostgreSQL `memory_hot`, 0–60 days |
| Cold | PostgreSQL `memory_cold`, 60+ days, archival |
| Search | pgvector over `all-MiniLM-L6-v2`, 384 dimensions |

`migrate_to_cold_tier` and `retrieve_from_archive` move between them. Tiering is a storage-cost decision,
not an epistemic one.

A missing embedding service **degrades search and never fails a store**.

## 3. The five kinds of memory

`MemoryType`: `EPISODIC` (a specific experience), `SEMANTIC` (general knowledge), `PROCEDURAL` (skills and
procedures), `WORKING` (temporary), `META` (learning about learning).

## 4. Storing a memory

`enqueue_memory` is the **non-blocking** store: it decides the memory's importance, queues the write,
records it in `_pending_memories` so recall can already see it, and returns a provisional `pending_<hex>`
id immediately. `_write_queue_worker` drains the queue through `store_memory` and survives per-item errors.
`drain_writes` awaits every queued write and retires the worker, returning how many landed.

**`store_memory` is the primary write authority.** In order it:

1. Decides importance itself (`importance_of`). A producer that passes one is refused.
2. Generates the worthiness metadata itself.
3. Runs the worthiness filter, with an **event-class exemption** for records that matter because they
   happened.
4. On rejection, returns without an id.
5. On acceptance, writes an admission record and stamps a **belief-state** snapshot (the relevant beliefs
   for the domain) and an **appraisal** snapshot from the live appraisal system.
6. Mints `mem_<hex>`, infers the type if none was given, stamps the readable claim and its shape tags,
   embeds, persists to hot, retains any media, and counts the episodic store.

**A memory is never folded into another, however alike they read.** The merge by likeness was removed on
2026-09-28: the substrate doing the same thing on two days is two memories, and merging wiped one. What
repeats within one pursuit is summarised inside that pursuit's memory, and what overlaps between memories
is recall's to bring together. The merge had compared only a reading's subject.

`importance_of` is the memory agent's alone, decided from what the memory *is* — by the first of its tags
naming its kind, a conclusion at its confidence, a goal from its reward potential, a percept, else a
default. Each producer used to choose its own.

`_readable_claim` extracts the substrate-readable claim a memory asserts, strips reasoning-status prefixes,
and keeps it only if the sentence reader parses it, returning the claim with its polarity and tense.

`store_batch` and `bulk_import` write built items with batch embeddings, bypassing per-item worthiness.

## 5. What a memory keeps of what was met

A memory that carries media is marked `has_image`, `has_video` or `has_sound` **by what its bytes are**, and
stamped `met` — the sha256 of those bytes, which is the identity of the thing met.

A picture's bytes and its gist are kept. A sound's **trace** is kept, never the recording. The coordinator's
`recollect` rebuilds either from what was kept, and `get_memory_media` returns the bytes, mime, dimensions
and perceived structure.

**Media is kept per memory.** A media row's id is the memory's and the content's together. Keyed by content
alone, the same recording heard twice *moved* its row to the second memory and the first could no longer be
heard again (`MEMORY-SOUND-01`).

**A lesson taught by hearing is a hearing memory like any other.** A word, a voice or a song is taught by
hearing an example; the hearing is remembered as every hearing is — episodic, trace kept, never the
recording — tagged with what it taught, and its trace archive keeps the example measured for matching.
`take_in_lesson` decides whether a just-remembered perceiving is a lesson; `lessons_taught` is the view the
perception faculty reads lessons back through; `share_lesson` makes a lesson someone gave the world's.
There is no store beside memory.

`add_perception_to_pursuit` makes a seeing or hearing within a pursuit a **part** of that pursuit's memory:
added to its experience with repeats counted, its trace or picture kept as that memory's media.

## 6. Recall

| | |
|---|---|
| `retrieve_memory` | By id, from hot or cold |
| `retrieve` / `search_memories` | The general recall paths |
| `recall_for` | What memory hands a request — the memories of a sound heard and a picture seen first |
| `get_recent_memories` | Recent, from hot |
| `query_by_tags` / `get_memory_by_content` | By tag, and by keyword or exact match |
| `claims_of` | The facts each memory claims, by memory id |
| `task_occurrences` / `tool_runs` | Every time the substrate did a task of its own; the tool runs a task did, by tool |

## 7. Changing and forgetting

`update_memory`, `update_importance` (which says **why** on the memory), `update_tags` (replace, add or
remove), `update_metadata`, `add_related_memory`, `increment_access_count`.

`supersede` replaces what a memory says **while keeping what it used to say**. `find_open` returns episodes
still waiting on something that this might be about, and `close_open` settles one.

`delete_memory` forgets a memory: its row and what it kept of what was met both go.

## 8. Episodes of pursuit

A pursuit is remembered as one episode that grows.

| | |
|---|---|
| `begin_pursuit` | Form the memory of a pursuit as it is taken on, and return its id |
| `add_to_pursuit` | Add one finished task: its record among the rest |
| `add_parts_to_pursuit` | Add parts of an experience, repeats counted |
| `add_perception_to_pursuit` | A seeing or hearing as a part of it |
| `close_pursuit` | Close it with how the pursuit ended, and queue it for consolidation |
| `pursuit_memory_id` / `acting_pursuit_memory` | The memory of a named pursuit, hot or cold; the one the current act is done under |

## 9. The rest of memory

Each family below is a set of write methods the owning authority hands to. The authority decides; memory
writes.

| Family | Holds |
|---|---|
| **Concepts and links** | `hold_concept`, `hold_concept_evidence`, `link_concepts`, `hold_alias`, `hold_surface_form`, `hold_evidence_envelope`, `hold_domain_membership`, `hold_identity_relation`, `hold_concept_vectors`, `file_concepts`, `refile_concepts`, `replace_sense_taxonomy`, `attach_waiting_links` — a link that named a surface before it was learned points at it once it is |
| **Undoing a wrong identity** | `release_evidence`, `release_alias`, `free_links`, `release_envelope` — what identity resolution put on the wrong concept, taken off; links wait again for theirs |
| **Beliefs** | `hold_belief` (replaced only while still at its expected update count), `belief_evidence`, `every_belief_evidence`, `settle_belief_evidence`, `drop_belief` so a reload cannot bring it back |
| **Expectations of the world** | `hold_expectation`, `settle_expectation` (confirmed, unmet or not judgeable, once), `departed_expectations`, `confirm_late`, `pending_expectations`, `expectations_of`, `expectation_outcomes`, `forget_expectations` |
| **Calibration** | `hold_calibration`, `calibration_records`, `hold_prediction_result`, `forget_calibration` |
| **Known unknowns** | `hold_known_unknown` — a question held open, in its owner's store — and `add_unknown_attempts` |
| **Rules and demonstrations** | `hold_rule`, `hold_rule_evidence`, `recount_rule_evidence`, `set_rule_status`, `refute_rule`, `hold_rule_projection`, `hold_supersession`, `forget_rules`, `record_rule_authority_change`, `hold_conditional`, `hold_demonstration`, `mark_induction_pending`, `clear_induction_pending` |
| **Domains** | `hold_domain`, `hold_default_domain`, `hold_domain_mapping`, `hold_domain_correspondence`, `hold_knowledge_transfer`, `resolve_knowledge_transfer`, `record_mapping_use`, `record_controllability`, `record_operating_outcome`, `hold_domain_volatility` |
| **What reasoning produced** | `hold_argument`, `hold_argument_claim`, `hold_fallacy`, `hold_temporal_proposition`, `hold_causal_link`, `hold_hypothesis`, `hold_experiment`, `hold_hypothesis_evidence`, `hold_schema`, `drop_schema`, `hold_analogy`, `hold_concept_mapping` |
| **Perception** | `hold_vision_instance`, `drop_vision_instance`, `hold_sound_instance`, `drop_sound_instance` — a reference image's features and a reference sound's landmarks, so the instance is recognised by name |
| **Trained recognisers** | `hold_clause_classifier`, `hold_security_training_example` |
| **The record of what was learned** | `record_knowledge_update`, `record_knowledge_updates`, `mark_knowledge_consumed`, `mark_behaviour_change` |

## 10. A person's context

What a person tells the substrate is held **in that person's context**, not in the world.

| | |
|---|---|
| `hold_for_person` | A fact about a person's own things: the link, and their belief in it |
| `hold_scoped_relation` / `hold_scoped_belief` / `hold_scoped_rule` | A link, a belief and a rule a person told, personal or work |
| `hold_belief_for_person` / `hold_rule_for_person` | A person's belief moved by one observation; a rule about their own things, asserting neither side |
| `hold_belief_about_speaker` / `said_of_themselves` | What a person said about themselves, in the context it came through; a restatement replaces it |
| `held_where` | Where something a person gave is held — owner, context, organization |
| `shared_world_context` | The owners composed into what Lyric may reason over for an actor: Lyric's own world knowledge, plus theirs. **Composed, never stored** |
| `ensure_work_authorizations` / `authorize_work` / `unlink_work` / `work_contexts` | Which organizations' Work Context a person is authorized for, as the identity that authenticated them says |

**Working memory** holds what a conversation was told but not to remember, for as long as the process
lives, each person's apart: `working_relations`, `working_beliefs`, `working_rules`. They are read together
with what the store holds wherever a context is read.

## 11. Taking in what it was told, split by what it is about

`take_in_telling` takes in what someone told and returns, for each fact and each rule, what became of it.
The rest of the family splits by **what the thing is about**, which is what decides where it is held:

`take_in_unread` (a sentence that did not read, kept verbatim and marked unread, recallable by meaning),
`take_in_tool` and `take_in_tool_use` (which tool, and the **names** of what it was given — never their
values, which are the caller's), `take_in_percept`, `take_in_demonstration`, `take_in_transition`,
`take_in_recognised`, `take_in_verdict`, `take_in_observed`, `take_in_research`, `take_in_reasoning`, and
`take_outcome_to_learning`.

`memory_type_of` decides what kind of memory a conclusion is kept as, and **unverified is never a fact**: a
deduction the reasoning authority did not verify is not stored as one.

## 12. Language lives in memory

There is no lexicon file. Everything the substrate knows about English is memories, read back through
**views** that are rebuilt from those memories and never written to disk.

The word-class store was removed because it cost more than it bought: measured on the live store it held
199 words, every one a NOUN, 197 of them asserted by a fan-out nobody taught — and a word recorded NOUN
*destroyed* readings that worked without it. "A filter separates particles." reads when `separates` is
unknown and stops reading once it is filed as a noun.

What replaces it is a view: empty until warmed from memory, extended as something is taught, and losing
nothing when dropped. Entries are **net** evidence — a reading that leaned on a class and succeeded counts
for it, one that failed counts against — which is the same evidence discipline beliefs use.

| View | Reads back |
|---|---|
| `word_class` / `word_classes` | The class a word has been observed to have, with net evidence. Synchronous |
| `warm_word_classes` / `begin_word_class_warm` | Rebuild it, joining one already in flight |
| `note_taught_proposition` / `note_refusal` | Fold one just-stored proposition, or a reading's blamed classes, into the view |
| `language_view` / `taught_patterns` / `pattern_inventory` / `note_pattern` | The constructions and links memory holds |
| `grammar_taught` / `grammar_view` | **English's grammar as the reader takes it**, built from what memory holds |
| `keep_grammar_learning` | What the grammar learned from each sentence, kept with the sentence under the rules it was learned by |
| `structure_view` / `argument_view` / `composition_view` / `lay_out` | Sentences as analysed, with their happenings' arguments, and as the composer reads them |
| `word_groups` / `word_forms` | Which words keep the same company; the forms words are written in |
| `stated_word_classes` / `stated_pronunciations` / `stated_patterns` | What has already been told |
| `listening_memory` / `listening_evidence` / `said_selection` / `coarse_senses` | What the listener counted, and what bears on which thing a word was meant to name |
| `tool_doings` / `remember_tool_doing` | What Lyric has read its own tools to do |

The `remember_*` family writes those memories: `remember_said`, `remember_analysed`, `remember_derived`,
`remember_grammar_rules`, `remember_grammar_pairs`, `remember_records`, `remember_word_records`,
`remember_argued`, `remember_taught_sentences`, `remember_word_forms`, `remember_word_groups`,
`remember_heard`. Each holds one memory per item, and one already held is not held again.

**What a word may mean** is read from the words recorded whole: `word_meanings`, `word_kinds`,
`word_senses_alike`, `word_senses_written_so`, `word_senses_any_class`, `word_senses_written_alike`,
`word_sense_is_a_kind_of`, `word_held_as_both`, `says_a_kind`, `words_for`, `used_for`, `recorded_name`,
`name_of`, `known_name`.

`taught_language` marks a memory as **taught language** — how to read or how to say — and never a claim
about the world.

## 13. Experiences and methods

`remember_experience` takes in one experience, which waits in the pool as a candidate.
`task_experience` records a finished task, succeeded or failed, as an experience. `methods_held` is every
method memory an owner holds, `standing_history` how a standing in a method has moved, and `person_reward`
the mean reward a person's counted outcomes of a method carried.

`capture_statistics` reports how fully the memories formed in a recent window carry what they should.

## 14. Loops

`start_memory_loops` and `stop_memory_loops` run the maintenance loops. Only maintenance is a **timer**;
abstraction and reflection are triggered by new work.

| | |
|---|---|
| `_maintenance_loop` | The one timed loop |
| `note_episodic_stored` | Counts newly-stored episodic memories and, past the threshold, makes abstraction due |
| `consolidate_memories` | Short-term to long-term |
| `form_abstractions_if_due` | Runs abstraction only when there is genuinely new work |
| `form_abstractions` | A back-compat shim — **abstraction is the reasoning authority's** |
| `reflect_on_beliefs` | Belief-graph hygiene, which is reasoning: the memory agent asks, it does not decide |
| `get_metrics` / `cleanup_cache` | Metrics; cache eviction |

Abstraction and beliefs are not owned here. They are reasoning, delegated to the neural bridge
([reasoning.md](reasoning.md)) and the belief authority ([beliefs.md](beliefs.md)).

Under `LYRIC_SHADOW_MODE`, `initialize` suppresses the loops and the queue worker while storage stays live.

## 15. Who reaches it

**Callers:** the cognitive ingress; the learning authority; the coordinator and intrinsic motivation; the
reasoning faculties (`neural_bridge`, `hypothesis_testing`) and the cross-domain reasoner; the recall
surfaces; perception; health, tools and chaos.

**Delegates to:** the belief authority (to stamp a belief state), appraisal (for the snapshot), the
reasoning authority (abstraction and reflection), the worthiness filter, storage, embeddings, the media
store and the write queue, and semantics (`claim_shape`, the sentence reader).

## 16. Evidence

| | |
|---|---|
| `experiments/MEMORY-SOUND-01` | A recording heard twice is two memories, each still hearable |
| [../research/MEMORY_AGENT_MAP.md](../research/MEMORY_AGENT_MAP.md) | What is held where |
| [../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | Results, with the negative ones |
| [beliefs.md](beliefs.md) · [reasoning.md](reasoning.md) · [learning.md](learning.md) | The authorities that decide what memory writes |
