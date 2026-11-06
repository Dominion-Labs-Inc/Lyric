# One language, end to end: the plan to make reading, understanding, reasoning and saying speak the same facts

*Written 2026-11-03. Nothing in this plan has been applied. Every claim below was read off the code and the last
run, not off the notebook; the verification record is section 7 and the re-certification is section 8.*

---

## 1. What the teaching standard solved, and what it never touched

The teaching standardization (TRAIN-FORMAT-01 and -02, `SentenceRecord` and `WordRecord` in
`core/learning/teaching_sources.py`) was built to end one problem: Lyric learned from about ten differently
structured sources (UD CoNLL-U, PMB CCG Prolog, PMB SBN, lessons JSON, PropBank, WordNet, Brown, CMUdict, word
groups, ConceptNet) bridged by hand-written conventions, so what it knew of a word depended on which corpus
happened to carry it.

**That problem is solved for words and sentences.** There is one record per word and one per sentence, every layer
by word position, and `lyric_db` now holds 12,228 word records and 6,137 sentence records.

**It is not solved for constructions, and that was not known when this plan was written.** The standard defines
`SentenceRecord`, `WordRecord`, `RecordWord`, `RecordFact` and `RecordSource`, and no record for a construction.
Nothing teaches one as a record; constructions exist only as a side effect of `learn_patterns` consuming raw
`(sentence, meaning)` pairs. Measured 2026-11-06: **no store holds a single construction** (§2.7).

**It was the wrong half.** The standard governs what goes IN. It says nothing about the language Lyric's own
components speak to each other. So the ten corpora became one format, and inside the system reading, understanding,
reasoning and saying went on speaking dialects — and no measurement in the teaching standard would ever show it,
because every TRAIN-FORMAT check reads the record back through the same component that wrote it.

Two different problems. One was solved and the other was never stated:

| | the source problem | the construction problem | the interchange problem |
|---|---|---|---|
| question | how must data be structured to teach Lyric? | what teaches Lyric a construction? | what language do Lyric's parts speak to each other? |
| answer | `SentenceRecord` / `WordRecord` | **no record exists** | **never decided** |
| status | solved for words and sentences | **§2.7, found 2026-11-06** | **this plan** |

This is the standing architecture rule applied where it was never applied — *one observation, one canonical
interpretation, many consumers* — and the pathology is the one already written down: *capability exists → local
integration is convenient → another subsystem builds its own copy → both appear functional → they drift → false
certification exposes divergence.* Every violation in section 2 is an instance of it.

---

## 2. The violations, each verified against the code

### 2.1 Two atom vocabularies, both documented as the only one, disagreeing on half their inputs

`clause_atom` — the function that turns a fact into the symbol a solver reasons over — exists twice:

- `core/reasoning/neural_bridge.py:164` — *"the one vocabulary held rules, held facts and read meanings are
  formalized into."*
- `core/semantics/sentence_reader.py:1451` — *"This is the one vocabulary the reasoner formalizes held rules AND
  held facts into."*

Both are the sole authority. Run on the same inputs, read-only, no store
(`scratchpad/atom_compare.py`):

| subject / relation / object | `neural_bridge` | `SentenceReader` | |
|---|---|---|---|
| valve / is / closed | `valve_is_closed` | `valve_closed` | **DIFFER** |
| a wall / isa / partition | `a_wall_partition` | `wall_partition` | **DIFFER** |
| socrates / is_a / man | `socrates_is_a_man` | `socrates_man` | **DIFFER** |
| men / is / mortal | `man_is_mortal` | `men_mortal` | **DIFFER** |
| the dog / are / animals | `the_dog_are_animal` | `dog_animal` | **DIFFER** |
| tom / was / happy | `tom_was_happy` | `tom_happy` | **DIFFER** |
| x / be / y | `x_be_y` | `x_y` | **DIFFER** |
| valve / isa / closed | `valve_closed` | `valve_closed` | OK |
| robin / instance_of / bird | `robin_bird` | `robin_bird` | OK |
| south asia / has_property / southern | `south_asia_southern` | `south_asia_southern` | OK |
| africa / straddles / equator | `africa_straddle_equator` | `africa_straddle_equator` | OK |
| reproduction / has_count / two | `reproduction_has_count_two` | `reproduction_has_count_two` | OK |
| rain / composed_of / water | `rain_composed_of_water` | `rain_composed_of_water` | OK |
| spider / has_part / leg | `spider_has_part_leg` | `spider_has_part_leg` | OK |

**7 of 14 disagree.** Three mechanical causes, all in the source:

1. **Different copular sets.** `_ATOM_DROPS_RELATION` is `{isa, instance_of, has_property}`;
   `_COPULAR_RELATIONS` is `{is, are, was, were, be, been, isa, is_a, instance_of, has_property}`. A fact whose
   relation is the plain copula is dropped by one and kept by the other, so a held rule's antecedent and a graph
   fact about the same thing become unrelated propositions and the rule cannot fire.
2. **Articles.** `SentenceReader._normalize` strips a leading article before normalising; `neural_bridge` does not.
3. **Singularisation on the copular branch.** `SentenceReader._atom` singularises the complement but not the
   subject; `neural_bridge` singularises the subject in its three-part branch. The `SentenceReader` docstring
   records that its own `_normalize` was fixed precisely so *"the substrate's logic believed `men != man` while its
   concept store believed `men == man`, and the canonical syllogism could not be proved."* **The second copy
   reintroduced that bug on the branch the first one fixed.** `men / is / mortal` is `man_is_mortal` in one and
   `men_mortal` in the other — which is the canonical syllogism, unprovable again, by the exact mechanism that was
   already found and fixed once.

**Reachability, checked separately — and this is the part a first pass got wrong.** Every live caller of a
`clause_atom` uses the **module-level** one: `DerivedReadingFormalizer` (857), held rules (2745, 2764, 2767, 2836),
concept-graph edges (2804), `_formal_query` (3105), `abstract_reasoning_engine._atom` (466, importing it), and
`autonomous_coordinator._clause_atom` (20955, importing it). **`SentenceReader.clause_atom` has no live caller at
all:** its only call site is `neural_bridge.py:967`, inside `SegmentedReadingFormalizer`, which is in no chain
(2.6).

So the divergence is **real as code and latent in production, not actively corrupting answers today.** It is still
a defect and still step 2, for three reasons: the only thing standing between the two vocabularies is that one is
unreachable, the unreachable one is what the tests exercise (2.6), and the moment anyone wires the long-prose
reader — which is work this plan recommends — the two meet. Stating it as a live corruption would have been wrong,
and section 2.8 shows what is live.

### 2.2 A second reader exists and is tested, but production does not call it — *corrected on the third pass*

`core/semantics/derived_reader.py` is declared *"the one reader"* at 14 sites across 10 files — the memory agent,
the coordinator, teaching, the document reader, the tools layer, and `neural_bridge.py` itself.

`core/semantics/sentence_reader.py:38` — `SentenceReader`, *"Turns a bounded slice of English into structure"* — is
a **regex** reader: `_COPULA = r"(?:is|are|am)"`, `_FACT = re.compile(rf"^{_DETERMINER}{_SUBJ}\s+{_COPULA}\s+...")`.

**An earlier draft of this plan said the reasoning authority reads queries with that regex reader. That was wrong,
and it was wrong because the draft trusted `docs/architecture/reasoning.md` instead of the code.** The architecture
document states that `_answer_over_concept_graph` *"reads the query to a typed (s,r,o) triple (`SentenceReader`)"*.
The code at `neural_bridge.py:2503` says the opposite, in its own comment: *"**ONE reader, no fallback**: the
question's meaning (`question_of`), read through the same constructions the teaching path learned."* It calls
`goal_fact(question_of(request))` — `derived_reader`. The regex reader is not in that path.

Checked exhaustively: in all of `core/`, `SentenceReader` appears at exactly three lines — the import at
`neural_bridge.py:41` and the two class attributes at 570 and 961, both inside formalizers that no chain contains
(2.6). **It has no live production caller.** Its live existence is in tests and experiments.

So the live reasoning path does use the one reader throughout. The violation here is not an active bypass; it is
**a second reader kept alive by its tests**, and a documented architecture that describes a bypass which no longer
exists. Both still have to go, because the next engineer reads the document — this draft did, and got it wrong.

### 2.3 The reasoning authority refuses the one reader's output language

`DerivedReadingFormalizer` is the door from read English into the solver. It declines, by explicit guard:

- `neural_bridge.py:847` — `if meaning.act == "request" or meaning.asked: return None`. **Every wh-question**,
  however well read.
- `neural_bridge.py:855` — `if is_variable(fact.subject) or is_variable(fact.obj): return None`. **Every fact
  holding an unknown.** The grammar mints unknowns for everything a sentence describes rather than names, so this
  refuses nearly every reading it is handed.
- `neural_bridge.py:928` — *"A GOAL IS ONE CLAIM"*. **Every conjunctive question.** This guard is itself
  duplicated: `DerivedReadingFormalizer` refuses at 928 and `DeterministicExtractor` refuses again at 1002, each
  with its own copy of the rule and its own error string. Widening the contract means finding every copy, which is
  the same defect class as 2.1 and 2.5 — so step 4 cannot be a one-line change and must not be attempted as one.
- `neural_bridge.py:902` — an unreadable premise **declines the whole request**, so one unread sentence in a passage
  kills every question about it. Also duplicated: the second formalizer declines the same way at 981.

The reasoning authority's own documentation states the scope honestly: *"a taught ground statement or yes/no
question."* That contract was written 2026-09-27. The reading program that produces non-ground readings of
arbitrary prose arrived from 2026-10-20 onward. **The reader's output language grew and the one door into reasoning
was never widened**, so everything built since reads into a room with no entrance.

### 2.4 The capability the reasoning authority lacks already exists, in the coordinator

`AutonomousCoordinator._held_ways` (`autonomous_coordinator.py:22497`) does exactly what the bridge refuses:
*"EVERY WAY WHAT IS HELD MAKES ALL OF A QUESTION'S FACTS HOLD, each `{unknown: held thing}`"*. It takes conjunctive
patterns, binds unknowns against what is held, orders the search so nothing is looked for that a fact does not lead
to, and it uses `derived_reader.is_variable` — it speaks the reader's language natively.

So the pattern solver exists, is good, and lives in the wrong component. The declared reasoning authority has none,
and a question can only be answered by whichever of the two routes it happens to enter.

### 2.5 The lexical layer is duplicated three ways with about nine ad-hoc folders beside it

`core/semantics/lexical_normalization.py` is the shared layer: `normalise` (121), `singularise` (156),
`canonical_term` (211), `canonical_label` (364). Beside it:

- `core/learning/rule_induction.py:90` — its own `canonical_term`.
- `core/domain/concept_ingestion.py:741,747` — its own `normalise` and `canonical_label`.
- at least nine private `endswith("s")` plural folders, including `neural_bridge.py:382`, `proof_faculty.py:61`,
  `teaching_sources.py:830`, `genericity.py:149`, `grammar_words.py:552`, `grammar.py:1504`,
  `autonomous_coordinator.py:22015`.

Every atom, every concept name and every alias is built on top of these. Two components that fold plurals
differently cannot agree on a fact's name no matter how well either of them reads.

### 2.6 Two formalizers are in no chain, one of them a capability that was built, measured and never wired

Both live formalizer chains are two long and identical:

- `neural_bridge.py:3093` — `FormalizerChain([PassthroughFormalizer(), DerivedReadingFormalizer()])`
- `autonomous_coordinator.py:22372` — `FormalizerChain([PassthroughFormalizer(), DerivedReadingFormalizer()])`

Four formalizer classes exist: `PassthroughFormalizer` (454), `DeterministicExtractor` (537),
`DerivedReadingFormalizer` (804), `SegmentedReadingFormalizer` (938). **Two of the four are in neither chain.**

**`SegmentedReadingFormalizer` is referenced by nothing** — no chain, no test, no experiment. Its docstring says
*"LAST IN THE CHAIN, DELIBERATELY"* and records the measurement that justified it: *"Measured before this existed:
0 of 86 sentences of nineteen words or more produced any reading at all."* It breaks a long sentence into the
claims it carries and reads each. **That is the long-prose capability, built and measured, sitting unwired** —
while section 2.8 shows 28 of 50 passage sentences going unread. Nobody should delete this; somebody should find
out why it is not in the chain.

**`DeterministicExtractor` has no production caller either**, but it is exercised by four test files
(`test_lexical_normalization.py`, `test_prose_reader_determiners.py`, `test_genericity.py`,
`test_graph_permutation_invariance.py`) and one experiment. So **the tests certify a path the system does not
run.** `test_lexical_normalization.py` in particular tests the naming layer through a formalizer production never
calls — which is how two `clause_atom`s could disagree for weeks with the suite green.

**And the architecture document is stale in four ways**, each of which misled this plan's first draft:

| `docs/architecture/reasoning.md` says | the code says |
|---|---|
| chain is `[Passthrough, DeterministicExtractor, DerivedReading]` | `[Passthrough, DerivedReading]` |
| classes at 323 / 371 / 638 / 751 | 454 / 537 / 804 / 1012 |
| `_answer_over_concept_graph` reads with `SentenceReader` | reads with `derived_reader` via `question_of` |
| `_answer_over_held_rules` renders with `SentenceReader.clause_atom` | renders with the module-level `clause_atom` |

The document carries the instruction *"Living document — update when the authority changes. Line numbers drift; the
explanations must stay true."* The explanations did not stay true. Correcting these documents is part of the work,
not a tidy-up after it: a wrong authority document reproduces the defect in the next engineer, which is exactly
what it did here.

### 2.7 The construction layer has no record in the standard, and no store holds one

`derived_reader` reads an utterance through the constructions the substrate was taught — holophrases, item-based
constructions, lexicals, phrases and links — each held as one semantic memory tagged `PATTERN_TAG`
(`"language_pattern"`). That is the layer `PatternInventory` serves and `meant` weighs over.

Measured 2026-11-06, read-only, every one of the 14 databases on `localhost:5433` (`lyric_db`, `lyric_dev`,
`lyric_dev2`, `lyric_bench`, `lyric_bench_home` and the nine per-store production and staging databases):

| | |
|---|---:|
| rows tagged `language_pattern`, all 14 databases | **0** |
| `MemoryAgent.taught_patterns()` on `lyric_dev` | **0** |
| `pattern_inventory()` after a full warm | `patterns=0 holophrases=0 item_based=0 lexicals=0 phrases=0` |

The query is sound: the same form returns 94,528 `word_class` rows on `lyric_dev`, and a breakdown of `lyric_db` by
full tag combination shows `word_record` (12,240), `sentence_record` (6,137), `word_class` (266), `read_english`
(28) and no construction under any tag.

**What follows from it.** Every utterance falls to `_read_by_composing`, which asks the grammar for
`COMPOSED_READINGS` readings — one — so `meant` returns *"the only meaning the words have"* before weighing
anything. Twelve sentences tried, including `A whale is a mammal.` and `The empire was in the west.`, all came back
`composed=True`, `senses=[]`, one reading. The listener's ACT-R activation, `said_selection`, spreading activation,
`listening_worths` and all four memory channels of `Heard` are unreachable, not unused.

**WIDENING IS NOT THE FIX, AND IT IS ALREADY MEASURED.** `nbest.py` puts the reader's own choice at 52.7% flat
from width 6 to 50 against 61.8% for an exhaustive chart, and it is tempting to read 6 points as waiting to be
claimed. They are not: that is what an oracle would take, not what the listener does.
`GRAMMAR-01/diagnostics/listener_on_store.json` (2026-11-03, 400 sentences, memory up) ran it —

| width | right reading available | right reading taken | readings handed up | seconds |
|---:|---:|---:|---:|---:|
| 1 | 172 | **172** | 390 | 23.4 |
| 6 | 179 | **168** | 592 | 107.9 |

— so making the right reading available more often got it taken **less**, with 11 cases of the listener overruling
a right reader, at 4.6x the time. In that run too, every sentence reports *"memory asked, knew nothing of any
reading"*: the listener ranks by structure alone, because a composed reading carries no packed senses and memory
holds nothing about what a composed reading says. **That is the argument for constructions, and against widening
without them** — the choosing cannot pay until there is evidence to choose on, and constructions are what carry
it.

**Why it belongs in this plan and not beside it.** It is the same pathology in section 1, one layer earlier: the
standard governs what goes in, so a layer it has no record for is a layer nothing can teach, and no TRAIN-FORMAT
check would ever show it because every check reads back a record that exists. The question layer in step 5 and this
one are the same omission twice — the standard certifies that a sentence was read, never that what reading needs in
order to work was taught.

**A measurement hazard this exposes, and it affects work already done.** The two stores are near-opposites:
`lyric_db` holds 6,137 taught sentences and 266 word classes; `lyric_dev` holds **1** taught sentence and 94,528
word classes. A grammar on `lyric_dev` has learned from one sentence, so any reading judged wrong there is judged
against a near-untaught grammar. Reading-quality conclusions drawn on `lyric_dev` need re-measuring on `lyric_db`
before they mean anything.

- **Certified by:** a count of `language_pattern` rows per store, which is one indexed query and belongs in
  `ONE-LANGUAGE-01` alongside the conformance checks: a store holding none cannot be read through constructions,
  and a run on it is measuring composition alone.
- **Needs your decision:** whether the standard gains a construction record, and whether the lessons and the PMB
  pairs are taught through `learn_patterns` into a store before any further reading measurement is believed.

---

### 2.8 What this costs, measured

The last end-to-end run, `UNDERSTANDS-PROSE-02` `20261102T150052Z` (after the `same_as` fix of notebook entry 103):

| | |
|---|---:|
| passage sentences taken in | 50 |
| passage sentences read | 22 (44%) |
| questions scored | 45 |
| **right** | **1** |
| wrong | 1 |
| not answered | 43 |
| reached the reasoner | 34 |
| of those, `substrate → kinds_of_thinking → unsettled` | 34 |
| of those, **steps taken** | **0, every one** |
| `run.log`: `Selected 0 reasoning strategies` | **35 of 35** |
| `run.log`: `Selected [1-9]` | **0** |

Entry (103) predicted the `same_as` fix would show *"the reasoner taking steps where it took none."* It ran the next
day and still takes none. **That prediction is refuted and the notebook does not yet say so.**

The one right answer, *"Does Africa straddle the equator?"*, has `reasoned: []` — it was answered by the
coordinator's held-fact route, not by the reasoning authority.

This is why reading accuracy moving 41.4% → 43.6% over ten days changed nothing a person would feel: **no amount of
reading accuracy survives a door that refuses the form reading produces.**

---

## 3. The fix: one language, four authorities, nothing beside them

The rule being restored: *one concept, one authoritative state, many views.* Per-consumer **views** are correct;
per-consumer **copies of the truth** are the defect. Each step below removes a copy and leaves a view.

### Step 1 — One lexical layer *(no behaviour change intended; it is the floor everything else stands on)*

`lexical_normalization` is the sole owner of normalising, singularising and canonical naming. `rule_induction`'s
`canonical_term`, `concept_ingestion`'s `normalise` and `canonical_label`, and every private `endswith("s")` folder
become calls into it.

- **Certified by:** a conformance check that every surviving caller gets the same string from the shared layer that
  its private copy produced, over the vocabulary of all 12,228 word records. Any disagreement is a real naming
  change and is listed, reviewed and decided before it lands — not folded in silently.
- **Risk:** a changed fold renames concepts in a live store. **Nothing is applied to `lyric_db` in this step.**

### Step 2 — One atom vocabulary

One `clause_atom`, in the semantics layer beside the meaning language that owns facts. The `neural_bridge` copy is
deleted and its callers import the one. The merged behaviour must be decided, not inherited, because the two copies
are each wrong in a different place:

| decision | `neural_bridge` today | `SentenceReader` today | to decide |
|---|---|---|---|
| plain copula (`is`, `are`, `was`, `be`) dropped? | no | yes | **drop it** — a copula is not a relation; it is how English says one |
| leading article stripped? | no | yes | **strip** — `a wall` and `wall` are one concept in the store |
| subject singularised on the copular branch? | n/a | no | **yes** — this is the `men`/`man` bug, already found and fixed once |

- **Certified by:** `ONE-LANGUAGE-01` (new, section 5) — the same fact rendered by every path must produce one
  atom, and the canonical syllogism must prove.
- **Needs your decision:** the three rows above change how facts are named. That is a behaviour change.

### Step 3 — Resolve the dead paths, which is a decision and not a deletion

Production already uses the one reader throughout (2.2). What remains is two unwired formalizers, and they must be
resolved in opposite directions:

**`SegmentedReadingFormalizer` — wire it or say why not.** It is the long-prose capability: it splits a long
sentence into the claims it carries so each can be read, and its docstring carries the measurement that *0 of 86
sentences of nineteen words or more produced any reading at all* without it. Section 2.8 shows **28 of 50 passage
sentences unread**. This is the most likely single cause of that and it is already written.

- **First find out why it is not in the chain.** It may have been left out deliberately — git history on
  `neural_bridge.py` for that class will say. **Do not wire it before reading that history**; if it was pulled for
  a reason, the reason matters more than the capability.
- If it is wired, it must first be moved onto the one atom vocabulary (step 2) and the one reader, or it reintroduces
  the divergence of 2.1 live, on exactly the prose path where it would matter most.
- **Certified by:** passage sentences read, on the same 50 as section 2.8. Today 22.

**`DeterministicExtractor` — retire it, and repoint its tests.** It has no production caller and four test files
plus one experiment keep it alive. Deleting the class without repointing those tests deletes coverage; repointing
them at `DerivedReadingFormalizer` is the actual work, and `test_lexical_normalization.py` is the one that matters,
because the naming layer it tests is step 1's.

- **Certified by:** the four test files pass against the live path, not the dead one. A test that cannot be
  repointed is testing something production does not do, and that is a finding to report, not to delete.

**And correct the architecture documents** (`docs/architecture/reasoning.md`, `semantics-ingress.md`) in the same
change as the code they describe. The four stale claims in 2.6 are not cosmetic: they are what made the first draft
of this plan wrong about where the defect was. A wrong authority document reproduces the defect in whoever reads it
next.

- **Risk:** low for the retirement, real for the wiring. Ordered after step 2 so the atoms agree before any new
  path starts producing them.

### Step 4 — The one door into reasoning takes the one reader's language

This is the step that moves the end-to-end number, and the previous three exist to make it safe.

`DerivedReadingFormalizer` stops refusing what the reader produces:

- a goal may be a **conjunctive pattern**, not one claim;
- a fact may hold an **unknown**;
- a **wh-question** is a goal with the asked unknown as what is to be found;
- an unreadable premise **narrows** the premise set and says so, instead of declining the request — with the
  refusal named and counted, so a question answered on partial premises is never silently treated as answered on
  all of them.

The solver behind it is **not** new work: `_held_ways` already does this. The correct shape is for the pattern
solver to live where the reasoning authority can call it and for the coordinator to call the same one, so there is
one solver with two callers rather than two solvers.

- **Needs your decision, and it is the big one.** `autonomous_coordinator.py` is a `CRITICAL_MODULE`: editing it
  while a substrate runs is a constitution HALT written durably into that store. Either the solver moves out of the
  coordinator (a protected-file edit, staged in `backups/` and applied with nothing running) or the bridge calls
  into the coordinator's (no protected edit, but the reasoning authority then depends on the coordinator, which is
  its own authority inversion). **I recommend moving it out**, staged, because the dependency direction matters
  more than the once-off cost — but it is your call and it is not reversible cheaply.
- **Certified by:** `UNDERSTANDS-PROSE-02` on `lyric_db`, read-only. The number to beat is **1 right of 45, 0 steps
  taken on 34**. The first honest target is steps taken > 0; the answer count follows or the diagnosis was wrong.

### Step 5 — The standard gains its missing layer

`SentenceRecord` standardises what a sentence's words, senses, roles and meaning are. It does not standardise **the
facts a question about that sentence must match**. That is why a passage read correctly still answers nothing: the
record certifies that reading reproduced the gold meaning, never that the facts it deposited are reachable by a
question.

Add to the standard, as a layer of the record: the questions the sentence answers and the facts each one must
match. Then a record is only taught successfully if the sentence can be read AND a question over it resolves
against what the reading deposited. That is the layer that would have caught every defect in section 2 on the day
it was introduced.

- **Certified by:** `TRAIN-FORMAT-01` extended with the new layer, on `lyric_dev2`, which is what that instance is
  for.
- **Needs your decision:** this changes the record format. One sample record first, per the standing rule, then the
  set.

---

## 4. Order, and why this order

1. **Lexical layer** — floor. Nothing above it can be certified while names disagree.
2. **Atom vocabulary** — requires 1; without it a conformance check cannot tell a real disagreement from a folding
   difference.
3. **One reader** — requires 2, so retiring the regex reader does not also change how facts are named. Two changes
   at once cannot be bisected.
4. **The door into reasoning** — requires 1, 2 and 3 to be certified, or a gain cannot be attributed and a loss
   cannot be found.
5. **The standard's missing layer** — last, because it encodes the invariant the first four establish. Written
   first, it would encode today's dialects.

Steps 1 to 3 are expected to move the end-to-end number by **nothing**. They are the conditions under which step 4
is attributable. Reporting them as progress would be the same false certification this plan exists to end.

---

## 5. `ONE-LANGUAGE-01` — the standing certification

A new experiment whose whole job is to fail when a second dialect appears. It is the guarantee that this does not
happen again, and it is worth more than any single fix in this plan.

**What it asserts:**

1. **One atom.** For a corpus of facts drawn from the word and sentence records, every path that renders a fact to
   an atom produces the same string: the read meaning, the held conditional's stored parts, the concept-graph edge,
   the induced rule's clause.
2. **One name.** Every component that names a concept from a surface word produces the same name, over the
   vocabulary of all 12,228 word records.
3. **One reader.** Every component that turns English into structure produces the same structure for the same
   sentence, or declines; no component reads English with a pattern of its own.
4. **The round trip.** A sentence taught from a record, read back, and asked a question over, resolves against the
   facts the reading deposited. This is the invariant of section 3 step 5.
5. **The canonical syllogism proves.** The regression test for 2.1, which has now broken twice.

**Why an experiment and not unit tests:** unit tests check a component against its own idea of correctness, which
is exactly how two `clause_atom`s each passed their own tests for weeks. This asserts agreement BETWEEN components,
which no component's own tests can.

---

## 6. What this plan does not claim

- **It does not claim to reach the 95% bar.** Notebook (102) measured that 95% exact whole-meaning match needs facts
  F1 of about 0.99, that the best published parsing of this corpus is 89.3, and that Boxer — the hand-built system
  that made the gold — scores 74.3. The bar as currently defined is not reachable by anything that exists. This
  plan is about the system speaking one language; where the bar should sit is a separate decision and is still open
  from (102).
- **It does not fix reading accuracy.** The held-out gap is 25.5 points of right-words-joined-wrong with no
  recurring mechanism found (three hypotheses measured and refuted) and 18.2 points of wrong-words whose largest
  family is worth 2.25 points. That is a ranked tail and it is separate work. This plan makes that work pay out;
  today it cannot.
- **It does not promise a number for step 4.** The measured facts are that 34 of 34 questions take zero steps and
  that the door refuses the form the reader produces. That the door is shut is certain; what comes through when it
  opens is not, and claiming otherwise is what the last two weeks were made of.

---

## 7. Verification of this plan

Every factual claim above was checked against the code or the run, not against the notebook. What was checked, and
how:

| claim | how verified | result |
|---|---|---|
| two `clause_atom` definitions | `grep -rn "def clause_atom"` | `neural_bridge.py:164`, `sentence_reader.py:1451` |
| they disagree | both imported and run on 14 shared inputs, no store, no boot | **7 of 14 differ** |
| different copular sets | read both frozensets | `{isa, instance_of, has_property}` vs 10 entries |
| the `men`/`man` regression | run, and `SentenceReader._normalize` docstring read | `man_is_mortal` vs `men_mortal` |
| `derived_reader` is the declared one reader | `grep -rc "the one reader"` | **14 sites, 10 files** |
| `SentenceReader` is a regex reader | class body read | `_COPULA`, `_FACT = re.compile(...)` |
| the bridge refuses variables / wh / conjunctions | source read at each guard | lines 847, 855, 928 |
| the one-claim guard is duplicated | `grep -n "a goal must be one"` | **928 and 1002** |
| an unreadable premise declines the whole request | source read | 902, and again at 981 |
| which atom function each caller reaches | every call site read | module-level live; `SentenceReader`'s has **no live caller** |
| `SentenceReader` has no production caller | `grep -rn "SentenceReader"` over all of `core/` | 3 lines, all in dead classes |
| `_answer_over_concept_graph` reads with the one reader | source read at 2503 | `goal_fact(question_of(request))` |
| the chain composition | both constructions read | `[Passthrough, DerivedReading]`, twice |
| two formalizers unwired | `grep -rn` for each class name | Segmented: **no reference at all**; Deterministic: tests + 1 experiment |
| `_held_ways` solves what the bridge refuses | source read | `autonomous_coordinator.py:22497` |
| the coordinator is protected | `CRITICAL_MODULES` read | **line 2396, coordinator listed** |
| lexical layer duplicated | `grep -rn "def normalise\|def canonical_term\|def canonical_label"` | 3 owners + ~9 folders |
| 34 of 34 zero steps, 1 right of 45 | transcript parsed, then **re-derived with `grep`** | both methods agree |
| 35 of 35 `Selected 0 reasoning strategies` | `run.log` counted | confirmed, `Selected [1-9]` = 0 |
| 50 sentences in, 22 read | transcript parsed, then re-derived with `grep` | 22 true + 28 false = 50 |
| `lyric_db` record counts | **read from the store directly**, read-only `psql` | 12,228 word, 6,137 sentence — notebook confirmed |

**Not verified, and flagged as such:** that step 4 moves the end-to-end number (unmeasurable until the door opens);
why `SegmentedReadingFormalizer` is not in the chain (step 3 reads the git history before acting); that the step 2
folding decisions are right for the live store (step 1's conformance check lists every rename for review).

---

## 8. Re-certification

A second pass over section 7, run after the plan was written, re-reading each site rather than trusting the first
read. Line numbers drift, so each was re-grepped by content.

| re-checked | outcome |
|---|---|
| the 14-case atom comparison | re-run from the same script, identical output, 7 of 14 |
| `_ATOM_DROPS_RELATION` / `_COPULAR_RELATIONS` | re-read, unchanged |
| the four refusal guards | re-grepped by content: 847, 855, 928, 902 |
| `_held_ways` signature and docstring | re-read at 22497 |
| the Nov 2 transcript counts | re-parsed, 1 right / 1 wrong / 43 not answered / 34 zero-step |
| `run.log` counts | re-counted, 35 and 0 |
| the one-reader sites | re-counted per file — **14, not 12; the first count was truncated output** |
| the lexical owners | re-grepped, 3 + 9 |
| `CRITICAL_MODULES` | **found at 2396; the first grep missed it on the type annotation** |

**Four corrections found on re-certification and carried into the text above:**

1. The one-reader sites are **14 across 10 files**, not 12. The first count was truncated terminal output read as a
   total — the exact kind of error this plan exists to stop, found in the plan itself.
2. **The one-claim guard is duplicated** (928 and 1002), as is the unreadable-premise refusal (902 and 981). Step 4
   is therefore not a one-line widening, and section 2.3 now says so.
3. **`neural_bridge.py` appeared to contradict itself** on which reader it uses. The third pass showed it does
   not — see below. This correction was itself corrected.
4. **`CRITICAL_MODULES` verified at line 2396** with the coordinator listed, after a first grep missed it on the
   type annotation. The protected-file constraint in step 4 stands on the code, not on memory.

**And one that changes how step 4 must be approached:** the reasoning architecture document
`docs/architecture/reasoning.md` states `DerivedReadingFormalizer`'s scope as *"a taught ground statement or yes/no
question"* — so this limit is **documented, not accidental**. The defect is not that someone wrote a careless guard;
it is that the reader's output language grew from 2026-10-20 onward and **the documented contract was never
revisited**. Section 2.3 is written that way. This matters for step 4: the contract must be changed deliberately,
in the architecture document as well as the code, or the next engineer will read the doc and restore the guard.

---

## 8a. Third pass — independent, and it overturned a section

The second pass re-ran the same script and re-grepped the same lines. That proves repeatability, not correctness.
The third pass derived each load-bearing claim a **different way**, and asked the one question the first two never
asked: *is the defect reachable in the running system?*

| claim | how it was checked differently | outcome |
|---|---|---|
| transcript counts | re-derived with `grep -o \| wc -l` instead of the Python parser | identical: 1 / 1 / 43 / 34, and 22 + 28 = 50 |
| `lyric_db` record counts | queried the store read-only instead of citing notebook (109) | **12,228 and 6,137 — notebook confirmed at the source** |
| the atom divergence | traced every call site instead of only the definitions | **`SentenceReader.clause_atom` has no live caller** |
| which reader the bridge uses | read `_answer_over_concept_graph` instead of the architecture doc | **the one reader, not the regex** |
| the formalizer chain | read both constructions instead of the architecture doc | **two long, not three** |

**Two corrections, one of them structural:**

1. **Section 2.2 was wrong and is rewritten.** The draft claimed the reasoning authority reads queries with the
   regex reader. It does not — it uses `derived_reader` via `question_of`, and says so in its own comment. The
   draft got this from `docs/architecture/reasoning.md`, which is stale. **A plan about components trusting the
   wrong source trusted the wrong source.** The correction is in 2.2 and the stale document is now step 3 work.
2. **Section 2.1 was overstated and is qualified.** The two `clause_atom`s do disagree on 7 of 14 — that stands,
   re-run twice. But the divergent one is unreachable in production, so it is a latent trap and the tests'
   certification of a dead path, not a live corruption. 2.1 now says which callers reach which.

**One new finding, which may matter more than anything else in this plan:** `SegmentedReadingFormalizer` —
the long-prose capability, built, measured (*0 of 86 long sentences read without it*), documented as belonging in
the chain — **is referenced by nothing at all.** Section 2.8 shows 28 of 50 passage sentences unread. These are
very likely the same fact. It is section 2.6 and step 3.

**What this pass says about the plan as a whole:** the live blocker narrows to one thing — step 4, the guards that
refuse the reader's own output, confirmed by 34 of 34 questions taking zero steps. Everything else in section 2 is
real but latent: duplicated code that the tests keep alive, capabilities built and unwired, and authority documents
that describe a system that no longer exists. That is a better diagnosis than the draft had, and it was only
reachable by not trusting the first two passes.

---

## 9. What needs your yes before anything is touched

1. **The three folding decisions in step 2** (drop the plain copula, strip the article, singularise the copular
   subject). These change how facts are named.
2. **Where the pattern solver lives** (step 4): moved out of the protected coordinator, staged and applied with
   nothing running — my recommendation — or called into from the bridge.
3. **`SegmentedReadingFormalizer`** (step 3): whether to wire the long-prose reader back into the chain. I would
   read the git history for why it left before recommending either way, and that reading needs no approval; wiring
   it does.
4. **The record format gaining a questions layer** (step 5), one sample first.
4a. **The record format gaining a construction layer** (§2.7), and whether to teach the lessons and the PMB pairs
   through `learn_patterns` into a store. No store holds a construction today, so every reading measured so far is
   composition alone. One sample record first, per the standing rule.
5. **Any run.** Nothing in this plan has been run beyond the read-only pure-function comparison in 2.1 and the
   parsing of a transcript already on disk. `UNDERSTANDS-PROSE-02` on `lyric_db` is read-only but is still yours to
   start.
