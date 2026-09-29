# Change map: moving sentence and word shapes into memory

2026-09-27. Everything that has to change is mapped here before building, and each change is verified, so nothing
is left half implemented. Nothing in it has been changed yet.

**What is being built** (`SENTENCE_AND_WORD_SHAPES.md` §7a–7b): the Leuven method. The substrate stores whole
sentences with their meaning, turns the differences between them into slot patterns and word entries, and scores
each pattern by use. The owners:

| Part | Owner |
|---|---|
| Patterns and word entries | memory |
| Scores | beliefs |
| Meaning | the domain system |

Everything below is either English knowledge written into the code, which moves into those three owners, or a
caller of such code, which must switch.

**How it was mapped, and how to re-check it:** `scripts/language_map.py`. It scans 616 Python files by AST, not
text search, so imports inside functions count. It prints every importer of `core.semantics`, every outside call
into the reader with its enclosing function, and every English word list or pattern in `core/`. Today it reports
**150 English word lists and patterns in 42 files**. Each "no caller" claim below was also checked by name across
core, scripts, tests and experiments. Re-run the script after every step: a finished step leaves nothing of what
it replaced.

---

## 1. Reading: a sentence becomes meaning

### 1.1 The reader and its parts (all in `core/semantics/`)

| Piece | What it holds now | Live callers | Change |
|---|---|---|---|
| `sentence_reader.py` `SentenceReader` (1,488 lines) | 33 patterns (22 sentence shapes, 11 splitters), 7 word lists (`_PREPOSITIONS`, `_MODALS`, `_QUANTIFIERS`, `_COMPLEMENT_BREAKS`, `_EMPTY_SUBJECTS`, `_NARROWING_NEXT`, `_COPULAR_RELATIONS`), 42 English hits in all. 35 methods; 13 are called from outside | §1.2 | replaced by the pattern engine; deleted once §1.2 has switched |
| `sentence_machine.py` | **Step 1 (done):** the cursor machine (`SentenceMachine`, `INSTRUCTIONS`, `FLAGS`) is archived; `form_of` / `surface_of` split text into its pieces losing nothing (capitals, digits, apostrophes, marks). Still here: 13 fixed word lists, the yes/no verdict lists, the old `tokenize` | `tokenize`: `Conversation.resolve`, `_leads_on`, `subject_of`, `about_this_conversation`, `is_question`. `evaluative_verdict`: `Conversation.feedback_of`. The lists: `genericity:145, 248` | lists and verdicts deleted at step 3 (they become lessons); `tokenize` replaced by `form_of` when its callers switch |
| `derived_reader.py` (+ `reading_registry.py`) | **Step 1 (done): rewritten into the pattern reader.** Meaning (tell/ask/request; facts in link kinds; situation variables), Pattern (exact identity), the view's index, exact `read` / `say`. The 13 pairs and 22 demonstrations written here, the procedure synthesis and the `runtime/derived_reading.pkl` cache are archived; `reading_registry.py` is archived (memory's view replaced it) | `DerivedReadingFormalizer` (`neural_bridge.py`) reads through it; boot registration removed from `core/main.py` | step 2 adds slot patterns and word entries; step 3 makes it the one reader |
| `genericity.py` | word-kind lookups `_word_class` / `_word_classes`, `classes_implied_by`, attestation `depending` / `blame`, `_LOCATIVE_*` lists, imports the fixed lists | the reader; `Conversation._triple_sentence:22313`; **`Constitution._law_vocabulary:2790`**; `neural_bridge:38`; memory's word-kind view (`memory_agent:2721, 2850`); `Conversation.teach:21568`; `TeachingPass._read:603` | word kinds come from slot links (learned); the lookups ask that; the lists go |
| `claim_shape.py` | `NEGATORS`, `PAST_MARKERS`, `PRESENT_MARKERS`, `ASKING` (20 words) | `read_claim`: `MemoryAgent.claim_tags:3137`, `_readable_claim:402`, `LiveRecall.harvest` (`core/memory/live_recall.py:305`). `about_the_same_thing`: `MemoryAgent._could_be_the_same_claim:1753`, `MemoryAgent.retrieve:2540` | memory's claim reading and duplicate test read through patterns |
| `relation_types.py` | `_SPECS`: 165 English phrases mapped to link kinds ("part of" → `part_of`, "can" → `capable_of`); `classify`, `complement_class` | `Conversation._typed_relation:21679`, `TeachingPass._typed_relation:498`, `cognitive_ingress:408`, the reader `:967` | which words say which link is learned (a pattern's meaning). The link kinds (`SemanticRelation`, 39 since Step 0) **stay**: they are the domain system's own structure |
| `cognitive_ingress.py` | `NEVER_A_TERM` (53 function words refused as terms) | admission (`normalize_term` has 7 callers, all stay) | the refusal asks learned word kinds; the list goes |
| `lexical_normalization.py` | word shapes: 34 plural exceptions, 20 irregular singulars, 25 "-ics" words, suffix stripping, `deinflect_verb` | **concept identity** (`concept_ingestion:42`, `concept_identity:268` through `normalize_term`, `cognitive_ingress:196`), `memory_agent:1659, 1745`, `tool_discovery:78`, coordinator `match_key` `:2789, 2901, 5731, 19849`, `singularise` `:22323, 22338`, `stem()` (4 callers in `Conversation`) | word shapes are learned (§4). Identity then asks the learned shapes. **This is the most delicate switch: concept identity decides when two names are one thing** |
| `literals.py` | `_MONTHS` (month names for dates) | `classify_literal`: `concept_ingestion:764`, `evidence_producers:748`, `cognitive_ingress:133, 496`, `lexical_normalization:180, 316` | month names become word entries; the number and date structure stays |
| `class_induction.py` | spelling features for word kinds, switched off | **none in live code** (EDU-16 only) | **backed up** to `archive/superseded_language_2026-09-27/` (§8) |
| `conversation.py` | a lazy re-export of `Conversation` | `talk.py:16`, EDU-15/16, PATHS-01 | stays or goes with `talk.py`; no language content |
| `language_ops.py` | sentiment, name-finding, summaries, stop words | tools only (`ai_ml_tools`, `security_training_pipeline`) | **out of scope**: tools for outside systems (§9) |

### 1.2 Every live call into the reader

| Caller | File:line | Reads |
|---|---|---|
| `Conversation.read` (builds the formalizer chain) | `autonomous_coordinator.py:20851-20872` | a sentence, for anything that needs a structured reading |
| `Conversation.asked` | `:20886, 20900` | a question (`_parse_goal`) |
| `Conversation._reasoned_answers` | `:21267-21315` | a question (`_parse_goal`, `clause_parts`) |
| `Conversation._register_domain_gap` | `:21470-21477` | a question |
| `Conversation.teach` | `:21532-21570` | a telling (`read_all`, `_parse_statement`, `clause_parts`) |
| `Conversation._research_phrase` | `:21768, 21814` | text read from the web |
| `Conversation.classify` | `:22011-22012` | whether a sentence is a telling |
| `Conversation._yes_no_property` | `:22385` | a yes/no question |
| `AutonomousCoordinator._ingest_environment_entry` | `:10328, 10338` | text files found in the boot scan of the environment |
| `MemoryAgent._readable_claim`, called from `store_memory:982` | `memory_agent.py:403, 428` | **every memory stored**, to decide whether it is a claim |
| `TeachingPass._read` | `teaching.py:604, 613` | each taught sentence |
| `ConceptExtractor._read_statements` | `concept_ingestion.py:475` | **broken and unreachable** (§8) |
| `DeterministicExtractor.formalize` | `neural_bridge.py:558-660` | premises and questions for the solver (`_parse_goal`, `_parse_statement`, `_render_*`, `render_clause`, `_normalize`, `_singular`) |
| `DerivedReadingFormalizer._atoms` | `neural_bridge.py` | **Step 1 (done):** a taught ground statement or yes/no question, through `derived_reader.read`; atoms by `clause_atom` (same vocabulary as held graph facts) |
| `SegmentedReadingFormalizer._atoms` | `neural_bridge.py:924-925` | prose, claim by claim |
| `NeuralSymbolicBridge._answer_over_concept_graph` | `neural_bridge.py:2429-2433` | a question over the graph |
| `NeuralSymbolicBridge._answer_over_held_rules`, `_held_rule_chain` | `neural_bridge.py:2642-2734` | a question over held rules |
| `NeuralSymbolicBridge._answer_over_induced_rules` | `neural_bridge.py:2782-2783` | a question over induced rules |
| `NeuralSymbolicBridge._answer_over_sense_taxonomy` | `neural_bridge.py:2372` | its own English question pattern (`_SUBCLASS_Q`) |

Two traps the build must handle. First, memory reads every memory it stores (`store_memory` →
`_readable_claim`), and patterns are stored as memories, so pattern memories must be tagged so they are not read
as claims. Second, the formalizer chain (`FormalizerChain`, `neural_bridge.py:970`, built at `:2990` and
`autonomous_coordinator.py:20863`) exists to turn English into the solver's logic. After the switch the pattern
engine gives meaning as facts, and the chain becomes: formal input, else the pattern engine's facts.

### 1.3 The conversation's own English (module level in `autonomous_coordinator.py`)

| Constant or function | Line | Used by | Change |
|---|---|---|---|
| `FUNCTION_WORDS` (53) | 19760 | `_titles:20096`, `phrases:20124`, `_context_relations:20413`, `resolve:20692`, `_leads_on:20723`, `subject_of:20740`, `asked:20888-20980` (5 places), `_support_used:21091` | learned word kinds (the most frequent words, found by counting, as in Mintz 2003) |
| `LOCATIVE_RELATIONS`, `TEMPORAL_RELATIONS` | 19779, 19783 | `asked:20904` | learned patterns |
| `NUMBER_WORDS` (32) | 19789 | `asked:20948` | word entries |
| `SPEECH_ACTS` (25) | 19807 | `about_this_conversation:20769-20771` | learned (what the speaker wants, §3) |
| `QUESTION_OPENERS` (23) | 19822 | `is_question:21898` | learned (§3) |
| `_WH` | 21323 | `_reasoned_answers:21331` | learned question patterns |
| `_SINGULAR_IN_S` (21) | 20474 | `_plural_map:20494` | learned word shapes (§4) |
| `stem()` | 19879 | `:19902, 20709, 20938, 22109` | learned word shapes |
| `_ENDINGS` | 19876 | **nothing** | delete (§8) |
| `NEGATIVE_POLARITIES`, `SPEAKER_THEM/ME` | 19854, 19818 | internal data labels, not English reading | stay |

## 2. Speaking: meaning becomes a sentence

| Piece | Where | Change |
|---|---|---|
| `Conversation.say`, the one speech path | `autonomous_coordinator.py:22413-22726` | speaks through the same patterns run in reverse. Its fixed phrases go, including "so I'll run a more targeted search." (the give-up reply flagged earlier) |
| `_triple_sentence`, `_natural_claim`, `_article`, `_relation_english`, `_plural_of`, `_singular_verb`, `_render_atom`, `_yes_no_property`, `_from_the_record` | `:22245, 22344, 22185, 22224, 22241, 22336, 21004, 22379, 20774` | replaced by speaking through patterns |
| `_COPULA_RELATIONS`, `_RELATION_ENGLISH` (28), `_ARTICLED_OBJECTS`, `_PLURAL_VERB` (24), the `article` and `spoken_verb` tables | `:22191-22240, 22285, 22330` | deleted: they are English written into the code |
| The solver's English renderings (`_render_fact`/`_action`/`_relation`/`_conjunction`, `render_clause`) | `sentence_reader.py`, used at `neural_bridge.py:632-690` | go with the reader |
| Other fixed English the substrate says about itself (`_standing` and `why` in the coordinator; perception and appraisal wording) | several | **later phase**: after reading and conversation speaking work, in the set order |

## 3. What kind of utterance it is

| Piece | Where | Change |
|---|---|---|
| `Conversation.is_question` | `:21887` (`?` or a first word on `QUESTION_OPENERS`) | a pattern's meaning carries what the speaker wants (tell / ask / have something done) |
| `Conversation.classify` → question / telling / job | `:21988` ("job" is whatever did not read) | the same learned marker. The kinds stop being "everything unread" |
| `Conversation.feedback_of` → `evaluative_verdict` | `:21929` + `sentence_machine.py:163-178` | "no, that's wrong" learned as a verdict pattern |
| `Conversation.about_this_conversation` | `:20743` (`SPEECH_ACTS`, `tokenize`) | learned patterns about the exchange ("what did I ask you?") |
| `kinds_of_thinking_for` (114 cue phrases decide which kind of reasoning a question wants) | `reasoning_interfaces.py:105, 161`; callers `neural_bridge.py:1957, 3405, 3884` | the kind of question comes from its meaning |

## 4. Word shapes

The same method at word level: pairs like `shoe`/`shoes` and `paint`/`painted` become scored patterns. A pattern
is applied to new words only once its exceptions are few enough (Yang's tolerance threshold); exceptions (`feet`,
`mice`, `ate`) stay remembered.

It replaces:
- `lexical_normalization.py` (its lists and suffix stripping)
- `_SINGULAR_IN_S` and `stem()`
- `tokenize`, which today drops the 3 of `3pm`, turns `'` into `_` and splits `U.S.`

**Order matters:** concept identity (`normalize_term` → `canonical_term`) is used by the domain system to decide
that `men` and `man` are one concept. It switches only when the learned word shapes cover what identity needs.
Otherwise two names for one thing would split into two concepts.

## 5. Teaching

| Piece | Where | Change |
|---|---|---|
| `TaughtRecord` | `teaching.py` | **Step 1 (done):** carries `meaning` and `situation`; a meaning needs its sentence |
| The sentence-or-triple branch | `teaching.py` `_teach` | **Step 1 (done), the first plug:** a record with a meaning is not read; its bound facts are taught (by polarity) and the pair is taught as a pattern (`learn_patterns`). **Fixed on the way:** denials read from sentences were dropped ("a denial is not an edge this path can carry"); `learn_facts` now carries polarity and they are taught. Still to come (step 3): a reading that disagrees with a given meaning counts against the pattern that produced it |
| `TeachingPass._read`, `_typed_relation`, `_note_unread`, word-kind warm at `:314` | `teaching.py:590-644, 498, 514` | switch with the reader |
| `ClosedClassSource`, `CLOSED_CLASSES` (222 words), `PUNCTUATION_FACTS` | `teaching_sources.py:53, 102, 118` | become lessons: word entries and sentence–meaning pairs taught through the one path, not a table in code |
| `WordNetSource`, `ConceptNetSource`, `WikidataSource` | `teaching_sources.py:293, 174, 476` | each record carries its meaning as facts (they already have the triple) |
| `learn_word_classes` (writes "'x' is used as a noun." memories) | `unified_learning_system.py:3195` | word kinds come from slot links; a stated kind becomes one more observation |
| `scripts/teach.py` | `:234` | follows the pass |

## 6. The three owners

**Memory** (`core/agents/memory_agent.py`). Today:
- The word-kind view: `WORD_CLASS_TAG`, `TAUGHT_PROPOSITION_TAG`, `UNREAD_TELLING_TAG` (`:2630-2648`),
  `WORD_CLASS_WARM_LIMIT` = 400,000 (`:2660`), `word_class(es)` (`:2669, 2694`), `stated_word_classes` (`:2754`),
  `warm_word_classes` / `_rebuild_word_class_view` (`:2815-2826`), warmed at boot from `initialize` (`:269`).
- Claim reading at every store (`_readable_claim`, `:378`).
- English keyword heuristics in `_generate_worthiness_metadata` (`:1313, 1331`); the reasoner's complexity
  score carries the same phrase list (`neural_bridge.py:4260`). They misfire on the substrate's own words
  ("laws I cannot change" matches `i cannot`).

New:
- Pattern memories, and a pattern view warmed the same way.
- The word-kind view rebuilt from slot links.
- The keyword heuristics removed.

**Beliefs** (`core/reasoning/bayesian_uncertainty.py`). `observe_claim` (`:458`) gets new callers: one
observation per use of a pattern, against it for a failure or a competitor that lost. `is_grounded` (`:1189`) is
satisfied because the pattern is a memory. **This is the first path where outcomes move beliefs, a known defect, so
every use must name the pattern's memory.** Decay for the English domain must not wear down patterns
that are rare but right.

**Domain system** (`core/domain/`, `core/integration/universal_domain_master.py`):
- Meaning facts go through the one door (`ConceptIngestionService.ingest`, `concept_ingestion.py:1612`).
- English becomes a domain (`UDM.ensure_domain`).
- The link kinds (`relation_types.SemanticRelation`) stay: 39 since Step 0 added `done_by` / `done_to`. Checked
  before adding them: the algebra reads each kind's properties and lists none by hand (`relation_algebra.py:60-85`),
  and graph reasoning types a stored row by the kind's exact name (`concept_graph_reasoning.py:24, 43-55`), so a
  kind that does not chain, is not inherited and has no inverse stays isolated. No store constraint limits kinds.
- `ConceptResolver._NON_CONCEPTS` (`concept_ingestion.py:702`) holds 21 words, some of them English pointing words
  (`it`, `this`, `that`); those move to learned word kinds.

## 7. The Constitution and boot

- **`Constitution._law_vocabulary`** (`autonomous_coordinator.py:2754-2835`) takes the nouns in the laws'
  descriptions as the interests at stake, and asks memory which words are nouns. On the wiped store no word is a
  noun yet, so the vocabulary comes back empty: the Constitution has no bearing or stakes until word kinds exist.
  It logs a warning and recomputes. It switches to learned word kinds with the rest. BEARING-01 measures it.
- Boot: **Step 1 (done):** the derived-reader registration and its shutdown cancel are gone from `core/main.py`; patterns warm with the word kinds in `MemoryAgent.initialize` (`begin_word_class_warm`). The cache file
  `runtime/derived_reading.pkl` is archived.

## 8. Already broken or dead, independent of the build

A standing rule decides what happens to each: a capability is never removed on a "yes" to a plan. Broken
means fix it; no caller means wire it; removing one needs his explicit words, item by item. Only junk with no
capability behind it is deleted outright. Status as of Step 0 (2026-09-27):

| Item | Evidence | Done / proposed |
|---|---|---|
| `ConceptExtractor._read_statements` called `DeterministicExtractor()._parse_statement`, which does not exist, and wrote `is_a` / `is_not_a` / `implies` as link names (not kinds; a denial folded into the name) | ran it: `AttributeError`; `ingest` does not catch it (`concept_ingestion.py:1623`) | **fixed**: reads the claims the teaching path reads (`read_all`), types each link with `classify`, carries a denial as polarity, declines conditionals. `tests/test_concept_extractor_statements.py` 4/4. Switches to the pattern engine at step 3 with every other reader |
| `submit_research_result` (`evidence_producers.py`), the only producer of statements evidence | no caller anywhere (checked across core, scripts, tests, experiments) | **wire it in the research phase**, not delete: it is the path that gives research findings their own provenance |
| `synonym_of` did not resolve to itself: `classify("synonym_of")` gave `related_to` | measured | **fixed**: `classify` resolves a kind's own name first; a test checks every kind |
| 5 tests in `test_relation_types_and_algebra.py` called `derived_reader.read_typed`, removed 2026-09-04 | failing since then | **fixed**: the 3 algebra tests take typed edges directly; the 2 reading tests' seven constructions are step-3 acceptance cases. 21/21 |
| `tests/test_conversation.py` talks to the live store with web look-ups on | on 2026-09-27 it wrote 104 rows over 20 tables into the lesson-only store, including the wrong fact `load balancer isa replaced` | **removed by creation time**, snapshot `data/snapshots/test_conversation_rows_20260927.json`; not revertible: one lesson memory's `last_accessed`, the `reasoning_meta` strategy's trial counts. The test is rewritten at step 3 and must not run against `lyric_db` |
| 4 experiments import the deleted `core.semantics.lexicon` | ATTEST-01, POS-01, `edu/EDU-16/session.py`, `edu/EDU-16/scaled_session.py` | **marked retired** in `experiments/README.md`; the files stay as records |
| `_ENDINGS` (`autonomous_coordinator.py`) | used nowhere; junk | **deleted** |
| `core/semantics/genericity.py.bak` | an old 225-line copy of `genericity.py` inside the package; junk (git keeps its history) | **deleted** |
| `class_induction.py` | no live importer | **backed up, not deleted**: moved byte for byte to `archive/superseded_language_2026-09-27/` with a README and a restore command. Step 4's learned word shapes take its job |
| `scripts/migrate_copular_relations.py` | a one-off migration of old copular edges; the store was wiped, so it has nothing to migrate, and it imports reader internals that go at step 3 | **backed up, not deleted**: moved to the same archive folder |
| `derived_reader.ensure_registered` | no caller anywhere | decided with the derived reader at step 3 |
| The comment at `teaching_sources.py:44` says the fixed lists moved to memory | they are still in `sentence_machine.py` and still used: two authorities | resolved by the build |
| English error phrases in memory's worthiness scoring and the reasoner's complexity score (`memory_agent.py:1313`, `neural_bridge.py:4260`) | **corrected**: the map said nothing the substrate says could contain them. Wrong: it says "I am bound by … laws I cannot change" (`autonomous_coordinator.py:10649`), which matches `i cannot` | live English heuristics that misfire; replaced with memory's other English heuristics (§6), not deleted as dead |

## 9. Out of scope, and why

- **Tools for outside systems** (never removed as "not substrate"): `language_ops.py` (sentiment, names,
  summaries), the stop words in `academic_tools.py`.
- **Machine interfaces, not language:**
  - tool parameter names, SQL words, file extensions, homoglyphs
  - error categories (`tool_registry.py:42`)
  - component status strings (`health_monitor.py:1266, 2080`)
  - security cue lists (`security_training_pipeline.py:397`)
- **Formal syntax:** `and`/`or`/`not` as logic operators (`logical_integration.py:98`,
  `PassthroughFormalizer._FORMAL_WORDS`).
- **Later phases** (after language, in the set order: tasks, research, domains):
  - the planner's keyword switch and step splitting (`planning_engine.py:672, 854-872`)
  - request-to-tool matching (`tool_discovery.py:438, 511`, `capabilities.py:677`)
  - the knowledge-request test in task execution (`autonomous_coordinator.py:19380`)
  - research topic keywords (`research_tools.py:45`)
  - memory-injection triggers (`memory_injection_policy.py:74, 79`)
  - English cue lists in other reasoners (`abstract_reasoning_engine.py:219, 1289`,
    `formal_argumentation.py:816`, `analogy_discovery.py:692, 723`, `hierarchical_abstraction.py:2224`,
    `capability_benchmark.py:512`, `concept_graph_reasoning.py:124`)
  - the English reader inside the proof tool (`proof_faculty.py:46-49`, used by `code_generation_tools.py:2886`).
    That one is a second reader, so it must read through the pattern engine when the task phase comes

  Each stays listed by `scripts/language_map.py` until its phase.

## 10. Decisions needed before building

1. **Pointing words** (`I`, `you`, `it`, `they`, `this`, `here`): the conversation resolves them (it knows the
   speaker and listener and tracks the last thing talked about); for "this"/"here" the teacher names the thing
   until sight supplies it. *Proposed.*
2. **What the speaker wants** (tell / ask / have something done): a marker carried with each pattern's meaning.
   *Proposed.*
3. **Who did what to what**: **done in Step 0.** `done_by` and `done_to` added to the domain system's link
   kinds, with no English written for them, no chaining, no inheritance and no inverse. Tests cover all of
   that, plus an event participant staying a fact about its one event and the graph typing a stored
   participant row.
4. **Deletions**: each removal needs explicit sign-off, item by item (§8).

## 11. Build order, so nothing is left half done

Every verification run writes to the sandbox `lyric_dev` (same structure as the main store, emptied with `scripts/reset_dev_store.py`); the main store `lyric_db` receives a lesson only after it has been verified there.

The rule: a step is finished only when the new piece works end to end, every caller it replaces has switched,
the old piece is deleted, the tests and experiments listed for it are updated and re-run, and
`scripts/language_map.py` shows nothing left of what was replaced. There is no fallback to the old path and no
second reader, not even briefly in production.

| Step | Built | Switched, then deleted | Verified by |
|---|---|---|---|
| 0 | **done 2026-09-27**: `done_by` / `done_to`; kinds resolve by name; §8 fixes (statements reader, stale tests, junk deleted, stale experiments retired) | — | relation-algebra tests 21/21, statements-reader tests 4/4 |
| 1 | **done 2026-09-27**: meanings in `TaughtRecord`; pattern memories, belief scores, the English domain; storing a whole sentence with its meaning; reading and speaking an exact taught sentence; the derived reader rewritten into it and its consumers switched (formalizer, boot) | derived reader's procedure synthesis, `reading_registry`, the cursor machine (all archived) | `tests/test_derived_reading.py` 35/35; SHAPES-LEARN-01 27/27 in the sandbox |
| D | **done 2026-09-27** (before step 2, in the set order): the domain system keeps no knowledge of its own. Records hold no concepts, relations, knowledge or vocabulary; English is judged by its patterns; `knowledge_sparsity_map` has its caller; one domain per field (twin fix); a reload rebuilds | the six record (de)serializers (backed up in `archive/superseded_domain_copies_2026-09-27/`) | SHAPES-LEARN-01 33/33; SYSTEM-DOMAIN-01 14/14; DOM-KG-01 16/16; SELF-PARTITION-01 23/23; GATE-01 25/25; BORROWED-KNOWLEDGE-01 9/9; OPERABILITY-BAR-01 11/11 |
| 2 | **done 2026-09-27** (§11a): the three kinds of construction, links between slots and fillers, reading and speaking through them, and the learner running the paper's seven repairs in order; scores are beliefs | — | SHAPES-LEARN-02 32/32; SHAPES-LEARN-01 35/35 unchanged; `tests/test_derived_reading.py` 41/41 |
| 3 | **switched 2026-09-29** (record after §11b): the engine reads everything in §1.2 and §3: statements, questions, kinds of utterance, memory claims, formalizer facts (detail: §11b) | **all** reading callers in §1.2, §1.3, §3 in one step; then delete `sentence_reader`, the `sentence_machine` lists and verdicts, `claim_shape` rules, `relation_types._SPECS`, `NEVER_A_TERM`, and the conversation constants; word-kind users (memory view, `genericity`, the Constitution) switch too. (`derived_reader` is the engine since step 1 and stays; `reading_registry` was archived in step 1) | tests §12; every experiment in §12 re-baselined on a taught store |
| 4 | word shapes learned | `lexical_normalization` lists, `stem`, `_SINGULAR_IN_S`, tokenizer; identity switches last | identity tests; concept dedup on a taught store |
| 5 | speaking through patterns | `say` helpers and tables (§2); delete them | SYSTEM-CONVERSATION-01, lesson transcripts |
| 6 | the old lists become lessons | `ClosedClassSource` / `PUNCTUATION_FACTS` taught, not tabled | the first lessons (letters, words, the shoe lesson) |

**Step 1 record (2026-09-27).** Rewritten, not added:
- `derived_reader.py` (the pattern reader)
- `sentence_machine.py` (`form_of`)
- `memory_agent.py` (patterns in the language view; exact identity; not read as claims)
- `memory_filter.py` (taught language exempt from the novelty filter)
- `unified_learning_system.py` (`learn_patterns`; `learn_facts(positive=...)`)
- `teaching.py` (meanings, situations, polarity)
- `neural_bridge.py` (the formalizer reads patterns)
- `core/main.py` (no derivation at boot)

The one new file is the experiment. Archived: the old derived reader, `reading_registry.py`, the cursor machine,
the derivation cache and the verdict test (`archive/superseded_language_2026-09-27/`).

The regression over every test that touches these modules: 320 passed, 18 failed. None of the 18 come from Step 1;
they fail on their own and are for fixing separately:
- `test_edu12_stage2_boundaries` (5) imports the folded `SubstrateLearning`.
- `test_motivation_integration` (2) imports the missing `learning_adapter`.
- `test_domain_expansion_chain` (6) needs registered domains, which an empty store lacks.
- `test_abstraction_connectivity` (4) checks its own belief store, while the pipeline writes through the one
  authority.
- `test_tool_integration_production::test_store_memory` (1) is refused by the Constitution's accountability law.

**Domain rework record (2026-09-27).** Rewritten, not added:
- `domain_registry.py`: no copies in the record; `domain_for_field` and `_absorb_field_twin`; `initialize()`
  rebuilds instead of overlaying.
- `universal_domain_master.py`: English coverage counts patterns, their facts and their kinds.
- `autonomous_coordinator.py`: idle research topics come from `knowledge_sparsity_map`, the one UDM method that
  had no caller. The hard-coded list of LLM-era topics is gone. (My earlier count of "11 unused methods" was wrong:
  10 were called inside UDM.)

Pre-existing failures fixed on the way: every second `initialize()` raised (both backups fail the same way);
`ConceptType.QUANTITY` / `TEMPORAL` had no ontology mapping; the shadow-enum allow-list named 6 enums that were
already resolved. DOMAIN-DISCOVERY-01 is 8/11 in the sandbox; its 3 failing checks need store content an emptied
store lacks (learned rules, a stored decision, concepts in the `general` channel), so the experiment must build
its own preconditions.

**The separation comes first (2026-09-27).** There are three parts:
- world knowledge: the substrate's own knowledge, held in memory, not taken as fact without irrefutable evidence;
- the world model: the copy of the substrate the world uses;
- user context.

See `docs/research/SEPARATION_MAP.md`. Two things from this work sit inside it:
- The research wiring above would send the host's details out as research topics. It has never run: it needs 15
  minutes of uptime, and `unified.knowledge_refresh` is empty in both stores.
- Step 1 stores facts about the speaker ("This is my shoe.") as the substrate's own knowledge.

**The one-reader rule forces step 3 to switch all readers at once.** Until then, the pattern engine is built and
proven in experiments but not wired. Once switched, it reads only what it has been taught. On the empty store it
reads nothing until the lessons are given, which is the honest starting point.

## 11a. Step 2 in detail (mapped 2026-09-27, before building)

The method, exactly as published (Doumen, Beuls & Van Eecke, *Royal Society Open Science* 11:231998, 2024,
§4.1–4.2.8; re-read from the paper, not from memory). It is laid on what step 1 built, and nothing is stored
outside the three owners.

**Three kinds of construction** (the paper does not distinguish "words"; the kinds are only for counting):

| Kind | Form | Meaning | Here |
|---|---|---|---|
| Holophrase | the whole utterance, no open places | the whole meaning | step 1's `Pattern`, as it is |
| Item-based | pieces with open slots (`This is my ?X .`) | facts with a variable for each slot (`instance_of(?shown, ?X)`, `owned_by(?shown, ?speaker)`) | `Pattern` whose form holds `Slot`s beside `Piece`s; each slot has its own category |
| Lexical | the pieces that fill a slot (`shoe`) | what they supply for the slot's variable: a concept, or facts about it | a filler with one argument and its category |

**Links (the categorial network).** A link joins a slot's category to a filler's category. A filler fits a slot
only through a link. Word kinds are what emerges: the fillers linked to the same slots.

**Using it.**
- **Comprehension:** find the combinations of constructions that cover the sentence, holophrases on their own or
  an item-based construction with linked fillers in its slots. The meaning is the item-based meaning with each slot
  variable given its filler's meaning.
- **Production:** the reverse.
- **More than one combination:** the highest average score wins, and a tie is reported, not resolved.

**Learning, per sentence–meaning pair.** Comprehend first. If that gives the taught meaning, only the scores
move. Otherwise these repairs are tried in the paper's order (§4.2.7), and the first that can handle the pair is
used:

| # | Repair | When | What it creates |
|---|---|---|---|
| i | add-categorial-links | the needed constructions exist but are not linked | the missing links |
| ii | item-based → lexical | an item-based construction applies, and one slot's material is not covered | a lexical construction for it, and its link |
| iii | holophrase → item-based + lexical + lexical (substitution) | form and meaning differ from a held holophrase in one place | an item-based construction, two lexical ones, two links |
| iv | holophrase → item-based + lexical (addition) | the pair extends a held holophrase | an item-based construction, one lexical, one link |
| v | holophrase → item-based + lexical + holophrase (deletion) | the pair reduces a held holophrase | a holophrase for the pair, an item-based construction, one lexical, one link |
| vi | lexical → item-based | lexical constructions cover parts of the pair | an item-based construction with a slot for each, and their links (several slots at once) |
| vii | nothing → holophrase | nothing else applies | the whole pair, as step 1 does now |

When several held holophrases could be generalised from, the one sharing the most form or meaning wins, and
among equals the one with the higher score.

**Scores are beliefs** (the owners above). The paper's numbers are the reference: a new construction 0.5, +0.1
for a successful use, −0.3 for each competitor that could also have served, kept in [0, 1], and a construction
at 0 no longer counts. It states that the exact values do not matter as long as the signs hold. Here each
construction has a belief grounded in its memory. A successful use is an observation for it; a competitor's is an
observation against it (`observe_claim`); scores move after every pair, not only when a repair ran. Links carry
use counts.

**The comparison.** Two meanings are compared by anti-unification: the substrate's Plotkin generalizer
(`rule_induction.py`) computes the shared part and returns what differs. Two forms are compared piece by piece.
The difference in the pieces must be paired with the difference in the meaning.

**Where each part is built.** Rewrites only, no new modules:

| Part | Where |
|---|---|
| Slots, the three kinds, links, the view's indexes, comprehension and production | `core/semantics/derived_reader.py` |
| The learner: comprehend, align the scores, run the repairs in order | the learning authority, `learn_patterns` (`unified_learning_system.py`) |
| Constructions and links as memories, warmed into the view | `memory_agent.py` (as step 1's patterns are) |
| Teaching calls the learner for every pair | `teaching.py` (already does, since step 1) |

**Verified by SHAPES-LEARN-02** (sandbox), a kindergarten set grown from the shoe lesson. What it measures:
- communicative success over the pairs;
- grammar size and the count of each kind;
- which repairs ran;
- new sentences with known fillers in known slots;
- new combinations;
- production;
- refusal of shapes never seen;
- the word kinds that emerge, with none told;
- the comparison with SHAPES-BASELINE-01.

SHAPES-LEARN-01 is re-run unchanged. Step 3, switching every reader to this engine, stays separate.

**Decided while designing (2026-09-27, before building).**
- **A lexical construction supplies one concept for its slot** (its *value*). An item-based construction keeps the
  meaning's structure and a variable where the value goes. This is what comparing two of these flat meanings gives
  (`instance_of(?shown, shoe)` against `instance_of(?shown, hat)` differ in one term), and it is the paper's split:
  the item-based construction keeps the operation, the lexical one keeps the concept. So "red" is one construction,
  whichever frame it fills.
  - In addition and deletion, the added or removed facts must bring exactly one concept the other meaning lacks;
    that concept is the value.
  - A situation variable (`?speaker`, `?shown`, …) is never a value.
- **Slots are named by their place in the form** (`?slot0`, `?slot1`, …), in the form and in the meaning alike.
  That keeps a construction's identity exact.
- **Links are memories, and their use is a belief.** Each link has a belief grounded in the link's memory; every
  use is an observation for it, so its use count is its evidence.
- **Scores.**
  - A construction's score is its belief's posterior. One not yet observed stands at 0.5, the paper's start.
  - Below 0.5, the line the belief store already treats as a reversal, a construction no longer takes part in
    reading or speaking. It stays in memory and can come back if it is observed again.
  - An observation is identified by its source and its pair. The same lesson from the same source again moves
    nothing; each different pair is a new use.
  - Between successful analyses with equal scores, the one whose constructions have been used more wins. This is
    frequency, the paper's other half of entrenchment.
- **Reading never writes memory.** A sentence reads through linked slots only. The paper also adds a missing link
  while reading without a meaning (its test set). Here that happens only while learning, where the taught meaning
  confirms it. Whether reading may add links is a step 3 question.
- **Where the code goes.**
  - The repairs are pure functions in `derived_reader.py`: given a pair and the view, each says what it would
    create.
  - `learn_patterns` runs them in the paper's order and stores what the first one proposes (memory, beliefs, the
    ledger).
  - The Plotkin generalizer gains one public function, `anti_unify`: the existing pairwise generalization with its
    substitution table, used on facts already paired up.

**Step 2 record (2026-09-27).** Rewritten, not added:
- `derived_reader.py`: `Slot`; `Pattern` holds slots beside pieces; `Lexical`; `Link`; the view indexes all three
  and reads scores from the beliefs; reading and speaking through linked slots; the seven repairs.
- `unified_learning_system.py`: `learn_patterns` is the learner. It reads each pair, runs the first repair that
  applies, stores what it creates (memory, beliefs, the ledger, including revivals), and moves the scores after
  every pair.
- `memory_agent.py`: `taught_patterns` reads every kind back from memory; `language_view` warms the view before
  the learner reads with it.
- `universal_domain_master.py`: English is judged by its constructions and links.
- `neural_bridge.py`: the formalizer reads a reading's own meaning.
- `rule_induction.py`: `anti_unify`.

The one new file is the experiment, SHAPES-LEARN-02. The regression over the tests that touch these modules: 228
passed, 1 failed (`test_legacy_rule_ids_still_resolve`, which failed before this step too).

The lesson's thin frames show the method's dynamics honestly. A frame learned from two sentences can tie with its
holophrase, lose, fall below belief, and be revived by the next sentence (SHAPES-LEARN-02 README).

## 11b. Step 3 in detail (mapped 2026-09-28, before building)

Step 3 makes the construction engine the one reader. It is built in three parts, in this order. No caller switches
until parts 1 and 2 pass their checks. Then every caller switches in one change, and the old pieces are deleted as
each is signed off. The paper was re-read for this (open-access copy, PMC11268157). At test time it adds missing slot
links with no meaning given (its add-categorial-links repair), and only lexical constructions fill slots.

**Part 1: what the engine adds.** All of it is in `derived_reader.py`, and all of it is reading only: nothing is
written.

| # | Addition | Why | Rule |
|---|---|---|---|
| 1 | a filler of the same kind | the paper links a filler to a slot at test time. The step-2 engine refused "Is the ball red?" although `ball` fills the same slots as `shoe` | a held filler not linked to a slot may fill it when it belongs to the same learned kind (`word_kinds`) as a filler that is linked. "This is my red." stays refused. The link is proposed, not written |
| 2 | a word never seen | a name in a known frame ("A vex7 is a mammal.") read nothing. A child takes a new word into a frame it knows (fast mapping, Carey & Bartlett 1978) | the slot's words become a new concept named by those words, when: no held construction covers them; none of them is a word the view holds only as a piece of a form (a structure word, found from use: it stands in forms and never fills a slot); and there are at most `MAX_TERM_WORDS` of them, the store's own limit on a term |
| 3 | case, and a missing final mark | heard speech and chat arrive without capitals or a final mark | only when nothing reads exactly: pieces compare with letter case folded, and a form's last piece may be absent when it is a mark. These are properties of the writing system, not English |
| 4 | text, not one sentence | a paragraph arrived as one unread string | `read_text` covers the text with consecutive utterances, each ending where a held construction ends; each utterance has its readings, or none |
| 5 | conditionals | "If the valve is closed, the tank overflows." had no meaning form, so switching would have cut held rules | `Meaning.condition`: facts that must hold for the facts to hold. The repairs pair condition facts only with condition facts |

Readings rank: exact readings with linked fillers first, then fillers of the same kind, then new words, then the
loose form; fewer proposals first, then score, then use. The learner's own reading (`readings_of`) stays strict, so
a taught pair still creates the link the paper's repair creates.

**Part 2: the first lesson.** Basic English sentence–meaning pairs covering everything the written reader read:
- kinds and properties, with denials;
- has, can, made of, part of, where things are;
- yes/no and wh questions;
- requests, conditionals, pointing, and a verdict on what was just said.

It is taught in the sandbox through the one teaching path. It is measured on:
- SHAPES-BASELINE-01's 35 sentences;
- the sentences SENSES-TOGETHER-01 and SYSTEM-CONVERSATION-01 use;
- the 300-sentence prose sample.

**Part 3: the switch** (one change):

| Caller | Takes from the engine |
|---|---|
| front door `_request_kind`, `Conversation.classify`, `is_question` | the reading's act: ask = question, tell = telling, request = job. **Nothing read = not understood: the reply says so and no Task is made** (the hearing session asked for this, since heard fragments must not become work) |
| `Conversation.teach` | the reading's facts bound to the situation (`?speaker` the person, `?listener` the substrate, `?previous` the last subject), sorted as `TeachingPass._bucket_meaning` sorts them: a fact naming the situation is the speaker's; a fact still holding an unknown is not held, and the reply says so. A conditional with one fact a side is held as a rule (`learn_rule`), as now. An unread telling is remembered as unread, with no word-class blame |
| `Conversation.asked` | answers from the question's meaning: each asked variable is looked up on its fact's named concept, in that fact's link kind; a yes/no is the held fact or its denial. This replaces matching English stems |
| `_reasoned_answers`, and the bridge's `_answer_over_concept_graph`, `_answer_over_held_rules`, `_held_rule_chain`, `_answer_over_induced_rules`, `_answer_over_sense_taxonomy` | the question read once, carried on `ReasoningRequest.reading`; a request with no reading is read by the engine. Held premises reach the solver as atoms, not sentences to re-read |
| `_register_domain_gap`, `_yes_no_property` | the link kind and terms from the meaning |
| `about_this_conversation`, `feedback_of` | a meaning about an act (`ask`, `tell`, `request`) done by `?speaker` or `?listener` is about the exchange. A verdict is `has_property(?previous, true / false)`, the logic's own truth values. `SPEECH_ACTS`, `evaluative_verdict` and the verdict lists go |
| `_research_phrase`, `_ingest_environment_entry` (text only; the sound branch stays) | `read_text` |
| `MemoryAgent._readable_claim`, `LiveRecall.harvest` | a claim the substrate made carries its facts. Other text is read by the engine, and a telling is a claim, with polarity from its facts. The tense tag goes: meanings hold no tense, and nothing reads the tag |
| `TeachingPass._read`, `ConceptExtractor._read_statements` | the engine; a source's stated triple stands where its sentence does not read, as now |
| the formalizer chain | formal input, else the engine's facts (`DerivedReadingFormalizer`). `clause_atom` moves to the reasoning side, over link kinds only |
| `kinds_of_thinking_for` | the question's link kinds (a cause asks causal thinking, a precedence temporal), not cue phrases |
| word-kind users: memory's word-kind view, `genericity`, `Constitution._law_vocabulary`, `cognitive_ingress.NEVER_A_TERM` | kinds from the links (`word_kinds`); a term is refused when the view holds it only as a piece of a form; the laws' vocabulary is the concepts their meanings name, once the laws' sentences are taught |
| conversation constants `FUNCTION_WORDS`, `QUESTION_OPENERS`, `_WH`, `LOCATIVE_RELATIONS`, `TEMPORAL_RELATIONS`, `NUMBER_WORDS` | the meaning's act, asked variables and link kinds; structure words from the view |

Word shapes (`stem`, `_SINGULAR_IN_S`, `lexical_normalization`) stay until step 4, and speaking (`say` and its
tables) stays until step 5, as §11 orders.

**Deletions, each needing explicit sign-off:** `sentence_reader.py`; the `sentence_machine` word lists, `tokenize` and
`evaluative_verdict`; `claim_shape`'s word lists; `relation_types._SPECS` and surface typing
(`classify` of a kind's own name stays); `NEVER_A_TERM`; `genericity`'s reader half; `DeterministicExtractor` and
`SegmentedReadingFormalizer`; the conversation constants above; the memory word-kind view's stated classes; the tense
tag. `claim_tags` has no caller and is junk.

**Step 3 record (2026-09-29).** Every reading caller switched to the engine in one change:
- the conversation: what kind of utterance it is, teaching what was told, answering from the meaning (compared by
  link kind, whatever form a record holds the relation in), verdicts, and questions about the exchange;
- the front door: what nothing reads is answered by the conversation and makes no task;
- the reasoning bridge: the goal comes from the question's reading, and premises reach it as formal atoms;
- memory claims and recall, the teaching pass, concept ingestion, the boot scan of text files, and the phrase
  look-up. The last three share one function for what a text states outright (`derived_reader.stated`);
- the store's term check: a word "names nothing" when the view holds it only in the forms of more than one shape of
  sentence and no taught meaning uses it as a concept's name (`PatternInventory.names_nothing`).

Not switched yet, each for a reason:
- the Constitution's law vocabulary: its nouns come from word classes until the laws' own sentences are taught;
- speaking (`_triple_sentence` and the reply wording): step 5.

Added to the deletion list, each with no caller left: `phrases()` and `_about_speaker` (coordinator), both
`_typed_relation` functions and teaching's `_class_evidence`, `REASONING_TYPE_MARKERS`, and `NEVER_A_TERM`. The
tests of the old pieces go with them (`test_prose_reader_determiners.py`, the reader half of `test_genericity.py`,
the extractor cases of `test_lexical_normalization.py`, surface typing in `test_relation_types_and_algebra.py`).
The experiments that call the old reader directly (ATTEST-01, the NLU suite, DOC-01, ENGLISH-LESSON-01, and the
written-reader comparisons in SHAPES-BASELINE-01, SHAPES-LEARN-02 and SHAPES-LEARN-03) keep their recorded
results but cannot be re-run once it is archived; DOC-01's reading half can be pointed at `stated`.

Verified: `tests/test_derived_reading.py` 55/55, `tests/test_conversation.py` 15/15 (rewritten: every sentence it
speaks is taught to a view of its own first), `tests/test_concept_extractor_statements.py` 5/5; SENSES-TOGETHER-01
16/16 on the switched code; re-run once each in the sandbox: SHAPES-LEARN-01 36/36, SHAPES-LEARN-02 35/35,
SHAPES-LEARN-03 10/10, SHAPES-LEARN-04 14/14, SYSTEM-CONVERSATION-01 38/38.

**A person's conversation teaches the shared model nothing.** Under the separation plan (`SEPARATION_MAP.md` §10), what
a person says is their context; the shared model learns English only through its teaching path, and anything else
only through its own verified work. Reading a person's sentence proposes and writes nothing to the grammar.

**Next after step 3: phrases in slots.** In the published method a slot takes one filler naming one concept, so
"my red shoe" or "that my brother gave me" cannot stand in a slot. Real sentences need that. The same group's
broad-coverage method (Van Eecke & Beuls 2026, arXiv 2603.12754) gets there by running an outside neural
constituency parser, which the substrate cannot use. So phrases have to be learned from the pairs themselves, and
that is designed and measured as its own step.

## 11c. Step 3b: every sentence gets a reading (mapped 2026-09-29, before building)

**The bar.** The reader must be equivalent to an LLM, if not better. An LLM gives every sentence a
reading and never refuses one. After step 3 the engine reads 8 of SHAPES-BASELINE-01's 35 statements and 2 of 300
prose sentences, and it answers everything else with "I could not read that". Three things cause that:
1. **All or nothing.** A sentence that does not match one taught shape end to end is thrown away, together with
   everything in it that did read.
2. **No phrases in slots.** A slot takes one filler naming one concept, so every new sentence shape must be taught
   whole.
3. **Little teaching.** 228 pairs.

This step removes the first two. The third is teaching at scale, whose sources are still to be chosen.

**Part 1: partial readings.** Every stretch of an utterance that reads is kept: a stretch that reads as a sentence,
and a stretch a held filler covers. When nothing reads the whole utterance, its reading is the cover by kept
stretches that reads the most of it. The stretches between them are what did not read. So every utterance gets a
reading, and what did not read is named exactly.
- A partial reading is never taken as told. A telling read inside a longer sentence may be denied or made
  conditional by the part that did not read ("It is not true that the door is open."). So its facts are shown as
  what was understood. They are never taught, stored as claims, or reasoned from.
- The reply says what was understood, names the words not understood (a word the view holds nowhere), and asks
  about them. It replaces "I could not read that".
- Measured: the share of pieces read, beside the share of utterances read whole.

**Part 2: phrases in slots.** A phrase is what fills a slot. It names a thing, and it may say more about the thing.
- **Meaning.** A phrase's meaning is an anchor (a concept, or a variable standing for a thing) and facts about the
  anchor. A lexical construction is the simplest phrase: a concept and no facts. In english_01, "the door" means
  `door`, and "my hat" means `?x` with `instance_of(?x, hat)` and `owned_by(?x, ?speaker)`.
- **Filling a slot.** The slot's variable becomes the phrase's anchor, and the phrase's facts join the meaning. A
  construction may use a slot only as a thing's kind (`instance_of(?x, ?slot0)`). A phrase with a variable anchor
  in that slot describes that thing, so its facts are said of `?x` in place of `instance_of(?x, ?slot0)`. This is a
  rule of the meaning language (a kind and its instances), not of English. Example: "My ?slot0 is ?slot1." with "red
  hat" and "big" gives `instance_of(?x, hat) & has_property(?x, red) & owned_by(?x, ?speaker) & has_property(?x,
  big)`.
- **Nesting.** A phrase construction may have slots of its own ("red ?slot0", "?slot0 ?slot1"), filled the same
  way, so phrases nest to any depth. A link joins a slot to any construction that fills it: a lexical, a phrase, or
  a phrase with slots. Kinds come from the links, as now.
- **Learning.** A held construction may read a taught pair except that one slot's words have no filler. Then what
  the pair's meaning adds is that stretch's meaning: a phrase pair (words, anchor, facts about the anchor). It is
  learned by the same seven repairs, applied to phrase pairs:
  - a phrase holophrase first;
  - substitution and addition generalize phrase holophrases into phrases with slots;
  - held fillers covering parts of a phrase give a phrase with a slot for each.

  A sentence pair can yield a phrase pair, and a phrase pair can yield smaller ones.
- **Reading.** A chart: the phrases read over each stretch are found once and reused by every construction whose
  slot the stretch could fill.
- **Acceptance.**
  - english_01's sentences read to their taught meanings, as before.
  - Once english_03 teaches how a word joins a noun, "My red hat is big." and "This is my red shoe." read.
  - Reading writes nothing.

**Part 3: english_03**, a lesson of noun phrases. It covers articles, possessives, adjectives, numbers, plurals,
"of" and place phrases, and a noun followed by a phrase. It is taught in the sandbox and measured on
SHAPES-LEARN-03's sets, whole and partial.

**Part 1 record (2026-09-29).** Built:
- **Partial readings.** An utterance nothing reads whole keeps the parts that read (`Stretch`: as a sentence, or as
  held fillers), chosen to read the most pieces, then the most as sentences, then in the fewest parts; the words
  nothing held has (`Utterance.unknown`) and the runs between the parts (`Utterance.unread`). A part is shown as
  understood and never acted on. Every stretch is tried, so parts are read only when asked for
  (`read_text(..., parts=True)`: the conversation's replies); read for everything else, the boot scan's every line
  was held up behind them.
- **The reply** names what was understood and asks about the unknown words; with every word known, it says the words
  are known but not this arrangement.
- **Marks separate.** When every stretch between an utterance's inner marks reads as a sentence ("My dog is not a
  cat, he is a dog."), each is an utterance of its own, for every reader.
- **"Or".** Facts marked `alternative`: two or more, of which one holds. Stored as a sixth element only where there
  is one, so older meanings keep their identity. Alternatives are compared only with alternatives; none is stated
  outright, taught as a fact, or held from a telling; the reasoner receives them as one disjunction.
- **New names.** One word is never a new name when it names nothing (`names_nothing`: "a"), and several never when
  one of them is a structure word. A word held so far only inside forms may still name a thing ("cup").
- **english_02**, 29 pairs answering the substrate's own questions: "and" joining statements and names, "or"
  questions, "true" and "not true", and "my … is not a …" with "he" / "she". Taught in the sandbox, the four
  sentences it had asked about ("The door is open and the window is closed.", "My dog is not a cat, he is a dog.",
  "Is the stove hot or cold?", "It is not true that the door is open.") all read whole, none of them taught as
  such. The replies around those readings are still the old speech (step 5).

**Part 2 record (2026-09-29).** Built:
- **`Phrase`**, a fourth kind of construction: a form of pieces and slots of its own, and what it names, an anchor
  with facts about it. Stored and warmed like the others (`construction: "phrase"`); a link joins any slot to a
  lexical construction or a phrase; phrases take part in the learned kinds.
- **Reading.** A slot takes a phrase read over its words, found once per stretch and reused by every construction
  whose slot could take it (`_phrase_fillings`, `_slot_fillings`); phrases nest. Composition (`_composed`): the slot
  becomes the phrase's anchor and the phrase's facts join; a slot used only as a thing's kind is described by a
  phrase standing for a thing. Readings made only of words compose exactly as before.
- **Learning.** A repair between item-based → lexical and substitution, **item-based → phrase** (`phrase_in_slot`): a
  held construction reads the pair but for one slot, and what the meaning adds there, about that slot's thing, is a
  phrase pair (`_what_the_slot_adds`). It is learned as a pair is: read by a held phrase, generalized over the held
  fillers inside it (a slot for each), or held whole (`_phrase_repair`), and linked to the slot.
- **What a reading supposes** counts the words taken as new names, not the names: "blue ball" as one new name
  supposes more than "ball" beside the known "blue".
- **english_03**, 21 pairs: words before a thing (in five frames), several of them, where a thing is, whose it is,
  and questions about a thing said with a phrase; plus sentences placing the things of a room in the same frames.

Limits, each for a later step: "teacher's" is one piece, so a possessive is learned per owner until word shapes
(step 4) split "'s"; small lessons leave kinds apart ("That is your red book." does not read: "book" and the things
"That is your ?slot0." has taken share no slot yet); numbers, plurals as phrases and clauses inside phrases ("the cup
that is on the table") are later lessons.

Verified: `tests/test_derived_reading.py` 56/56 (a phrase learned in one slot reads in another frame, its link
there proposed and never written); SHAPES-LEARN-05 11/11 in the sandbox: english_03 learned 17 constructions and 44
links, the phrase repair ran 11 times and left 9 phrases; every sentence of the three lessons still reads; 9/9 noun
phrases never taught read to their meanings ("This is my big blue ball.", "Tie your small red sock.", "Where is the
big box?", "The cup on the table is hot."); shapes no lesson taught stay unread. NLU-01's prose: 3/300 utterances
whole, 15 + 271 of 4,081 words read (271 in parts, 261 before).

## 11d. Step 5: saying things through what was taught (mapped 2026-09-29, before building)

**Why now.** Reading is one engine; speaking is still two: the replies turn a held fact into English with templates
keyed on relation labels, word classes and articles (`Conversation._triple_sentence`, `_natural_claim`,
`_RELATION_ENGLISH`, `_PLURAL_VERB`, `_ARTICLED_OBJECTS`, `_article`), which is how the substrate said "Noted — a door
is an open." after reading "The door is open." Step 5 makes the engine the one speaker: a fact is said with the
constructions it is read with.

**Part 1: the engine says what it can read** (`derived_reader.say`). Today it says a meaning only through a
holophrase or a frame whose slots have fillers linked to them. It gets the reader's rules the other way round:
- a filler of the slot's learned kind may stand in it (the link is proposed, never written);
- a concept no filler names is said by its own name, as a word never seen is read as a new name, under the same
  limits (no longer than the slot's kind has held, no structure word);
- the sentences are ranked as readings are: what they had to suppose, then score.

**Part 2: a lesson for every link kind the store holds** (english_04). A kind no lesson taught cannot be read or said:
used for, causes, requires, enables, prevents, precedes, follows, produces, contains, member of, owns, eats, has
function, defined as, and the rest of `SemanticRelation`. Statements and questions for each.

**Part 3: the replies.** Every sentence in a reply that states a fact is said through the engine:
- what was noted from a telling;
- an answer: "Yes." or "No." (taught holophrases) followed by the fact said, or a wh-answer said as a statement;
  an "or" question is answered by the alternative that holds;
- what is held about a thing.

A remembered claim is quoted as it was said; a fact the engine cannot say yet is not said in another way: the reply
says it holds something it has not been taught to say. What the substrate says about itself ("I have remembered what
you said", "I don't hold ... yet") stays fixed wording until the later phase of §1's table. The reply also stops
listing the words of the sentence it could not place ("I hold open but nothing said about it yet"), and stops
reciting the sentence just said as a memory.

**Then deleted, with sign-off:** `_triple_sentence`, `_natural_claim`, `_RELATION_ENGLISH`, `_PLURAL_VERB`,
`_ARTICLED_OBJECTS`, `_article` and the word-class read in speaking, which is the last use of `genericity`'s word
classes outside the Constitution.

**Verified by:** `tests/test_derived_reading.py` (saying), `tests/test_conversation.py`, SYSTEM-CONVERSATION-01 and
SHAPES-LEARN-04's second telling, whose replies are recorded and now checked.

**Record (2026-09-29).** Built:
- **The engine says what it can read** (`derived_reader.say`, `_said_fillers`): a linked filler, else one of the
  slot's kind, else the concept's own name (no structure word in it; the length limit reading applies does not
  apply to a name already held). The writing is the slot's: a filler begun by a word that names nothing only
  where the slot's fillers were; a capital begins the sentence, and a capital that only ever began a sentence
  ("Milk") is not kept inside one, while one written mid-sentence ("Monday") is a name's (`is_proper`). A sentence
  it says reads back to exactly the meaning it was said for (tested).
- **The learner takes a word held in another case as the same word** (`_held_filler`, `_covering_fillers`): "Writing"
  learned at the start of a sentence fills the slot "writing" stands in, as a new filler of the same concept; held
  fillers as written are found over the whole sentence before any in another case. Without it, words met first at
  the start of a sentence stayed fixed inside frames ("A ?slot0 is used for writing.").
- **english_04**, 70 pairs: a statement frame and questions for every link kind no lesson had taught (used for,
  causes, caused by, requires, enables, prevents, precedes, follows, produces, produced by, creates, contains,
  member of, owns, eats, eaten by, synonym, antonym, adjacent to, derived from), each kind's words first met in a
  plain sentence so that both of its slots form.
- **The replies** (`Conversation.say`, `_said`): what a telling noted is said as taught; a telling's reply is what was
  noted, what was not and why, and the opposite on record, nothing else; an answer is "Yes." or "No." then the fact
  said, a wh-answer the fact said or else its name, an "or" question the alternative that holds; a remembered claim
  is quoted as said and the question itself is never recited; what is held is said only of what was asked about.
  Inside one text, "it", "he" and "they" point back to the previous sentence's subject, and to nothing when that
  subject has no name ("My dog is not a cat, he is a dog.").

In memory, with the four lessons: "A saw is used for cutting.", "A bike requires air.", "What causes pressure loss?",
"A goat eats grass." and "Does a cat eat grass?" read, none taught; "Rain causes floods." does not (a plural, step 4).

A reply recites a remembered memory only when it names what the question is about and reads, through what was taught,
as a claim: a record of hearing a word said, or of a file's size, is an episode, not knowledge about what was asked.

Verified: `tests/test_derived_reading.py` 57/57 (what it says reads back to what it meant), `tests/test_conversation.py`
15/15; in the sandbox SHAPES-LEARN-06 16/16 (8/8 facts of the new kinds said and read back, 7/7 of their sentences
never taught read, a conversation about a nonce name noted and answered with the fact said), SHAPES-LEARN-04 18/18
(its second telling's replies now checked: "Noted — The door is open. Noted — The window is closed."; "Part of that
is about something I have no name for yet, so I did not hold it."; "Noted — The door is not open."),
SYSTEM-CONVERSATION-01 38/38, SHAPES-LEARN-05 11/11.

Now without callers, for the deletion list: `_triple_sentence`, `_natural_claim`, `_relation_english`,
`_RELATION_ENGLISH`, `_PLURAL_VERB`, `_plural_of`, `_ARTICLED_OBJECTS`, `_COPULA_RELATIONS`, `_singular_verb`, and with
them speaking's read of `genericity` word classes. `_article` stays: the line saying a word's several senses uses it.

## 11e. Step 4: word shapes (mapped 2026-09-29, before building)

**Why.** Every word form a lesson did not teach is a new word to the reader today: "Tables" is not `table`, "floods"
is a name of its own, "teacher's" is one piece, so a possessive is learned per owner and "it's" per sentence. §4 says
what replaces the written shapes; this is how, in the engine.

**Part 1: an apostrophe joins two pieces** (`form_of`). Inside a word it begins a piece of its own, glued to the one
before: "teacher's" is `teacher` + `'s`, "it's" is `it` + `'s`, "don't" is `don` + `'t`. A property of the writing,
as marks are; what the pieces mean is learned, so "?slot0 's ?slot1" can form over every owner. Constructions held with
such a word as one piece (english_03's possessives, in the sandbox) are learned again.

**Part 2: word shapes are found from the fillers held, never told** (`PatternInventory.word_shapes`). A filler whose
written word differs from its concept's name ("Dogs" → `dog`, "wheels" → `wheel`, "flies" → `fly`) shows a change at
the word's end (`s` → nothing, `ies` → `y`). Each change is scored as Albright & Hayes score theirs: the held words
it reads rightly, against the held words it would misread (a base form it would cut: "bus", "grass"). It applies to a
word it has not seen only while its misreadings are within Yang's tolerance threshold, N / ln N. An irregular form
("geese" → `goose`) stays what it is: a filler held on its own.

**Part 3: reading.** A word no filler holds, whose productive shape leads to a held word, stands in a slot as that
word's concept, through a proposed link, when that word would stand there (linked, or of the slot's kind).

**Part 4: saying.** A slot whose fillers carry a shape (the plurals in "?slot0 are ?slot1.") takes the concept written
in that shape, by the productive change the other way round ("Tables are made of wood."); a concept's own name goes
where its slot's fillers are base forms.

**Part 5 (last): identity.** `normalize_term` / `canonical_term` switch to the learned shapes only when they cover
what concept identity needs; §4's order stands.

**Part 6: english_05**, plurals, possessives and contractions, taught in the sandbox and measured.

**Record (2026-09-29).** Parts 1 to 4 and 6 built; part 5 waits, as ordered.
- **Part 1** as mapped: "teacher's" is `teacher` + `'s`, "isn't" is `isn` + `'t`, "boys'" is `boys` + `'`, and
  what each piece means is learned over every word ("The boy's cup is red.", "Birds can't swim.", never taught).
- **Part 2, with contexts.** A change is found with each run of letters before it (`changes_between`: "boxes" from
  `box` is `es` → nothing, `xes` → `x`, `oxes` → `ox`), and every one is scored over the words it applies to, the most
  particular first. A word that a productive, more particular change reads rightly, where a general one would misread
  it, is that change's ("flies" is `ies` → `y`'s; "boxes" `xes` → `x`'s). Without contexts, `es` → nothing read 1 of
  5 of its words rightly ("horses" is not `hors` + `es`) and was never productive, so "Churches" stayed a new word.
  Irregular forms ("mice", "geese", "men", "teeth", "children") are words of their own.
- **Part 3**, and a concept's own name. A word no filler holds reads as the held word a productive shape makes of it
  (a held filler, or a held concept's name), and a concept's own name reads as that concept ("fox", where only
  "Foxes" is held): saying writes the name when no filler is in the slot's shape, so reading takes it back. The
  learner takes both as fillers of the concept (`_held_filler`), as it takes a word held in another case.
- **Part 4.** The shape a slot takes is the productive changes its kind's words are written in; a name takes the
  most particular that applies (the longest run of its letters), then the one more words show: `church` →
  "Churches", `penny` → "Pennies", `glass` → "Glasses", `bus` → "Buses", `horse` → "Horses".
- **Part 6.** `english_05`, 52 pairs: plurals of words already held first ("Hats are red."), so that the general
  "?slot0 are ?slot1." forms for properties before any new word arrives; then `-es`, `-ies` and `-ys` plurals, two
  or more for each context; irregular plurals; possessives; contractions; "What's a …?" and "What's an …?". Taught
  in the other order, the first plurals of new words were held inside frames of their own ("Dishes are round." whole),
  and never became words.
- **New words, anchored by the construction they stand in** (`_anchored`, `_new_here`). Counted per construction,
  a frame's or a phrase's own words anchor the new words in its slots, and so does each slot holding something
  held. A new word standing alone in a slot needs one anchor, so "Rain causes floods." reads with neither word ever
  met. A run of new words taken as one name is a guess at where a name begins and ends, so no more of those than
  anchors. A phrase of slots alone takes a new word only beside a held one ("glorpy dogs"). The limit it replaces
  (no more new names than the frame's own words, counted over the whole reading) is what kept "Rain causes floods."
  unread; SHAPES-LEARN-06 put that down to plurals, wrongly. A first, looser version read three NLU-01 prose sentences
  whole and wrongly ("Its queues are now built without persistence." as a kind of thing); measured again, this one
  reads the same three it read before.

Limits:
- A word whose held word is not held reads as written ("Classes"), and a new word keeps its writing in the meaning
  ("Rain", "floods"); the store's door still makes the identity (`canonical_term`), until part 5.
- "a" and "an" are two words: "What's an eagle?" read once "What's an owl?" was taught. That "an" is "a" before a
  vowel letter is found for saying (`letters_after`), not for reading.
- Among the sentences it can say, a bare "Church is big." can rank first: the frame taught with "Milk is white."
  takes any word of the kind, and which words go without "a" or "the" is not learned yet.

Verified: `tests/test_derived_reading.py` 62/62 (shapes in their contexts, reading and saying in a shape, new words
anchored per construction), `tests/test_conversation.py` 15/15; in the sandbox SHAPES-LEARN-07 16/16 (26 productive
changes, the irregular forms none; 19/19 plurals, possessives and contractions never taught read to their meanings;
8/8 facts said in the plural slot's shape, everything said reading back; untaught shapes unread; NLU-01 prose 3/300
whole, 461 of 4,112 words read in parts). SHAPES-LEARN-04's and -06's reading and saying checks were replayed in
memory under the new rules and all hold.

## 11f. The last step: every English word (mapped 2026-09-29, before building)

**Where it stands.** In memory with the five lessons: 246 lexical fillers, 40 of the 222 closed-class words, no word
of WordNet's 147,306 lemmas (77,898 of one word) beyond what the lessons use. On NLU-01's 300 prose sentences, 2,417
occurrences of words nothing held stop a reading: 1,786 are WordNet words, 472 closed-class words, 159 neither
(numbers, dates, identifiers, hyphenated compounds, "than", "how", "cannot"). The main model holds english_01 and 02;
the store was wiped on 2026-09-26, so the WordNet taxonomy taught before then is gone.

**Part 1: the engine at the scale of a vocabulary.** Measured with WordNet's nouns added as fillers of one frame:
a read costs 0.001 s once warm at 55,315 lexicals, but the first read after any addition rebuilds the kinds, the
word shapes and the letters after each word from everything held: 0.03 s at 5,238, 0.12 s at 20,202, 0.34 s at
55,315. Teaching reads between pairs, so the whole vocabulary would cost the square of its size. Saying also walks
every filler of a slot (0.14 s at 55,315). These views are kept up to date as each construction and link is added,
never rebuilt whole.

**Part 2: the closed-class words, taught by lessons.** The 182 missing function words are the frames every sentence
is built from. Each is taught in its constructions, as english_01 to 05 were. Some of their meanings are already in
the meaning language: "in" and "on" as `located_in`, "near" as `adjacent_to`, "before" and "after" as `precedes` and
`follows`, "because" as `causes`, "if" as a condition, and "can" as `capable_of`. Others have no form yet:
- places: above, below, under, behind, in front of, between;
- "with", both for an instrument and for company;
- tense: was, were, will, had;
- quantity: some, every, each, many, few, none, and numbers;
- comparison: "than", "more", "-er";
- modals beyond "can": must, should, may, might;
- contrast: but, although.

Each of those is a choice about the meaning language, and each choice has consequences for reasoning. They are taken
one at a time, from how existing semantic representations write them, before their lessons are written.

**Part 3: the open-class words, from WordNet.** `WordNetSource` is the curated source the teaching path already
reads. Its sentences come from a template in code (`_states`: "A X is a Y."). Instead, each record carries its
meaning: `isa(child, parent)` for nouns, antonyms for adjectives, and further relations as their frames are taught.
The sentence is what the substrate says for that meaning through the frames it was taught (`derived_reader.say`), so
no English is written in code, and each pair teaches the word, its kind and its fact. WordNet's exception lists
(`noun.exc`, `verb.exc`, `adj.exc`) give the irregular forms. The regular forms are shapes (§11e).

**Part 4: measured.** For every word taught:
- it reads in a sentence never taught;
- it is said;
- what is said reads back.

NLU-01's prose is measured again, whole and in parts. KNOWS-WORDNET-01's levels, negative control included, are
asked of the store.

**Part 5: identity** (§11e part 5), once the vocabulary is taught: `canonical_term` switches to the learned shapes.

**Part 1 record (2026-09-29).** `PatternInventory` keeps what it derives as each construction and link arrives:
- **Kinds** are a union-find joined link by link.
- **Word shapes** move only the counts of the endings a new word has (`_shape_word`). A change that becomes
  productive, or stops being so, moves only the words it reads (`_settle`).
- **Letters after each word** and **each slot's tallies** grow with each link.
- **The listings** (`holophrases`, `lexicals`, `links`) are indexes.

A slot's fillers are one kind, so a slot's kind and its longest filler are one lookup. One rule changed with it: a
filler written as its concept's name changed at the end ("Robins", "Children") is one word with the filler written
as that name, whether or not the change is productive. That standing says whether a change applies to words never
seen, and both of these are held. Tied to it, every new two-word ending forced the kinds to be rebuilt.

Measured with WordNet's 55,066 one-word nouns added, a third with a plural, and a read after each: 56 s in all,
linear. The rebuild-every-time version had not finished after ten minutes. At 55,315 lexicals, a read after an
addition costs 0.00 s (0.34 s before) and saying 0.00 s (0.14 s). The saying and reading of plurals held at that
size.

Verified:
- `tests/test_derived_reading.py` 63/63. The new test adds the same constructions and links in 12 random orders,
  some of which make `xes` → `x` productive and then not. It checks the shapes and their counts, the kinds, the
  letters after each word, and each slot's shape, openings and longest filler against a computation from
  everything held.
- `tests/test_conversation.py` 15/15.
- The view warmed from the sandbox's stored constructions (1,036) reads SHAPES-LEARN-07's 19 probes and says its 8
  facts as that run did.

**"a" and "an", one word in two shapes (2026-09-29).** Found when WordNet's words were said: new words came out as
"A ocelot is a wildcat.", and "An ocelot is a wildcat." was not offered at all. The lessons had taught "a" and "an"
as two unrelated words, and every frame in both versions except "An ?slot0 is a ?slot1.".
- **Found, never told** (`variants_of`). Two words of frames' own are one word in two shapes when three things hold:
  - frames otherwise the same, meaning the same, hold one or the other in the same place, in two pairs or more;
  - the letter after them decides which: letters written after both are within Yang's tolerance of each one's
    letters.

  "a" and "an" alternate in 8 pairs of the lessons' frames, and "an" is written before a, e, i, o. "is" and "'s"
  alternate too, but nearly every letter after "'s" also follows "is", so they are two ways of saying one thing.
- **Reading** takes a word where a frame has another of its shapes, when the word fits the next word
  (`written_for`, `_written_shapes`).
- **Saying** writes each frame word in the shape the next word asks (`shape_before`). Before a letter neither shape
  was written before, it uses the shape written before the most letters, by the elsewhere condition: "a jay".
- **The learner** learns a frame reached through its other shape as the sentence wrote it (`_as_written`), and never
  links the new word into the frame's other shape. Linking it there made the letters after "a" include "e", and
  that overlap hid the variant.

**Part 3, first cut (2026-09-29).**
- **The teaching record.** A record may carry a meaning, the words the source writes each concept with
  (`TaughtRecord.words`), and no sentence. The teaching pass has the substrate say it through the frames it was
  taught, keeping the best sentence that writes each word as the source does (`TeachingPass._said`), and teaches that
  pair. What nothing taught says teaches no English; its facts are still taught.
- **WordNet** gives each noun's `isa` edge as such a record, with the sense's first lemma as its word (`person` for
  `causal agent person`). A named thing ("Paris", "Hussein") is taught as a fact only: no frame taught yet says a
  name without an article. That covers 8,283 of its 83,102 edges. Its 78,122 definitions are unchanged, and their
  sentence still names the sense ("An entity abstraction is …"); they wait for part 2.
- **In memory, on a random 3,000 of the 74,819 noun edges:**
  - 2,898 were said, in 6 s;
  - every one was learned, none refused, 2,884 as a new word in the frame that said it;
  - 2,829 of the new words read in "What is a/an …?", never taught with them; the rest have another sense in the
    sample;
  - not said: names holding a word so far held only in frames ("body part", "oil well", "heat of dissociation").

`_states`, the template that wrote WordNet's sentences, is now without callers, for the deletion list.

**Verified in the sandbox: SHAPES-LEARN-08, 15/15**, on a uniform sample of 3,000 of WordNet's records after the five
lessons. It covered 1,319 noun facts, 175 named things' facts and 1,506 definitions:
- 1,275 noun facts said and learned, none refused;
- every one of the 1,275 nouns reads in "What is a/an …?", never taught with it, to the sense taught;
- 200 of 200 sampled facts held, and 0 of 200 pairs WordNet does not relate answered yes;
- 200 of 200 facts said back read back to themselves;
- the lessons still read.

**The cost, by stage.** The teaching path writes one word-class memory per word of WordNet's vocabulary (75,833
notes such as "'synovia' is used as a noun."), whatever the sample. That took 3,061 s, one memory at a time. The
3,000 records took about 292 s, 97 ms each. All of WordNet would take about 4.4 h plus the one-time 51 min.
Storing the word-class memories in batches is the obvious saving; it belongs to the memory agent's store path.

**Part 2, first lesson (2026-09-29): `english_06`**, 77 pairs, for function words whose meanings the meaning
language already holds:
- places: "at", "near", "inside";
- time: "before", "after";
- "his", "her", "its", "their" (`owned_by` the one spoken of before);
- "him", "her", "them", "me" in requests (`done_to`);
- "these", "those";
- "who", "which" in questions;
- "all", "every", "never" (what holds of a kind);
- "with" for a part a thing has;
- relative clauses: "The boy who owns the bike is tall.", "The cup that is on the table is hot."

"we", "our" and "us" wait: the meaning language has no speaker's group.

In memory, after the six lessons, every pair is learned, none refused, and every taught sentence reads to its
meaning. 15 of 15 sentences never taught read to their meanings, among them "The girl who owns the bike is
tall.", "The box with the handle is red.", "All fish can swim.", "Those are my socks." and "Noon is before
morning.".

**A learner rule it needed** (`_names_within`). A new name is never a held name of the same concept plus other words
("All birds", where "birds" already names `bird`); the other words belong to the frame. Without it, "All birds can
fly." taught "All birds" as a name of `bird` through "?slot0 can ?slot1.", so "all" never became a frame's word, and
"All fish can swim." read "All" as something fish are. With it, "All ?slot0 can ?slot1." and "Every ?slot0 is a
?slot1." form. The five earlier lessons still read in full, and the checks of SHAPES-LEARN-04, -06 and -07 still
hold in memory.

**Saying a word never held as it is used (2026-09-29).** SHAPES-LEARN-08 showed two faults in English said for new
words: "A paleoanthropology is a vertebrate paleontology." and "A fire tongs is a tongs." for words that take no
"a", and "A Thiosulfil is a sulfa drug." for a name. A word never held was said under its concept's name in any
slot, so it took the "a" of the only frame that said the fact.
- **How held words are used** (`PatternInventory._use_model`, `used_as`), from what they are linked to:
  - `name`: written with a capital inside a sentence;
  - `plural`: in a slot that takes a shape;
  - `count`: in a slot right after the word with shapes of its own, "a" (`counted_slot`, found as `variants_of`
    finds it, never listed);
  - `mass`: held alone, as named, where a sentence begins ("Water is cold.", "Biology is hard."), and never counted.
  A word only ever held after "the" or "my" has none of these.
- **How a word never held is used** (`use_of`):
  - a `name` when its source writes it with a capital;
  - as its last word is used, when that is held ("fire tongs" as "tongs");
  - else by its ending, the longest that decides, with two conditions:
    - by the elsewhere condition, "kindness" is "ness"'s and no evidence for "s";
    - an ending other than counted must be more reliable than counting is over every word held (Albright & Hayes:
      the more reliable rule wins). Without that, three "-ing" words made "g" decide, and "sulfa drug" lost its "a".
  - else `count`.

  A plural is never guessed from an ending: "bus" and "lens" end as plurals do.
- **Saying** (`_said_fillers`): a concept no filler names goes, under its own name, only where words of its use are
  held (`slot_admits`): a name never after "a", a plural as it is where plurals go, and a counted word after "a" or
  in the slot's shape. A held word used only as a plural is already in the plural shape ("tongs", never
  "tongses").
- **`english_07`**, 58 pairs:
  - names, met first in known sentences ("Tom is tall.") and then said to be kinds of things ("Tom is a boy.");
  - words without "a", met the same way;
  - "is a kind of", with counted and uncounted words;
  - "Ice is water.";
  - plural-only words ("Scissors are tools.").

  Met first in known sentences, the new words let the general frames form. Taught in the other order, each object
  became a frame of its own ("?slot0 is a science.").
- **The teaching pass** asks only the words a pair teaches, the concepts not held yet, to be written as the source
  writes them. A held concept is said as it is held ("Fire tongs are tools." for `tool`).

In memory with the seven lessons:
- all pairs are learned, none refused, and every sentence reads;
- "Thiosulfil is a sulfa drug.", "Cyanocitta is a bird genus.", "Mississippi is a river.";
- "Paleoanthropology is a kind of vertebrate paleontology.", "Brightness is a kind of quality.";
- "Fire tongs are tongs.", "Fire tongs are tools.";
- "A lens is an optical device.", "A bus is a vehicle.";
- the checks of SHAPES-LEARN-04, -06 and -07 and english_06's 15 probes still hold.

The test `test_a_word_never_held_is_said_as_the_words_used_like_it_are` is written. The sandbox run waits for the
rename's database cut-over.

**Order.** Part 1, then part 2's lessons for what the meaning language holds already, then part 3 in the sandbox on
a sample and then whole, then part 2's remaining meanings, then part 4 and part 5. The main model is taught only on
the owner's word.

## 12. Tests, experiments, scripts and docs that change

**Tests (8):** `tests/test_conversation.py`, `test_derived_reading.py`, `test_derived_reading_verdict.py`,
`test_genericity.py`, `test_graph_permutation_invariance.py`, `test_lexical_normalization.py`,
`test_prose_reader_determiners.py`, `test_relation_types_and_algebra.py`.

**Experiments that depend on reading, speaking or teaching (40 files):**
- ACTOR-IDENTITY-01, ATTEST-01*, BEARING-01, CHAT-CONCURRENCY-01, CONTENT-01, DOC-01, DOM-KG-01, ENCODER-04
- ENGLISH-LESSON-01, FRONTDOOR-IDENTITY-01, KNOWS-WORDNET-01, LEARNED-WORK-01, LOOKUP-SINGLEFLIGHT-01, PATHS-01
- PIPELINE-01, POS-01*, REMEMBER-01, RESEARCH-WRITE-01, RETRIEVAL-01, SELF-PARTITION-01, SHAPES-BASELINE-01
- SYSTEM-CONVERSATION-01, TAUGHT-IN-ENGLISH-01, TEACH-AND-DO-01, `cleanup/quarantine_rule_artifact.py`
- `edu/EDU-13`, `EDU-14`, `EDU-15`, `EDU-16`*
- the NLU suite (`nlu/`), `experiments/sentence_machine.py`, `systems/TOLD-SEEN-01`

(* already broken: they import the deleted lexicon.) Six more import `core.semantics` only for the provenance
record and are unaffected: DOMAIN-DISCOVERY-01, IDEMPOTENT-01, SEE-LOOP-01, SELFSTATE-01, SYSTEM-LEARNING-01,
SYSTEM-SEMANTICS-01.

**Scripts and CLI:** `scripts/teach.py`, `talk.py`. (`migrate_copular_relations.py` is backed up in `archive/superseded_language_2026-09-27/`.)

**Living docs to update:** `docs/design/MEMORY_SEMANTICS_CONVERSATION.md`, `docs/TEACHING.md`,
`docs/architecture/reasoning.md`, `memory.md`, `learning.md`, `coordinator.md`,
`docs/architecture/SUBSTRATE_SYSTEMS_MAP.md`, `docs/LYRIC_ARCHITECTURE_DOCUMENT.md`,
`docs/research/COMPREHENSION_SCOPE.md`. The lab notebook and teaching-session logs are records and are not edited.
