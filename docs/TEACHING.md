# Teaching the substrate

*Living document. Part of the [substrate architecture reference](ARCHITECTURE.md);
the authority itself is documented in [architecture/learning.md](architecture/learning.md).
Every number here was measured against the live store on 2026-09-20 — nothing is
estimated, and where something is a hypothesis it says so.*

---

## 1 · Why this document exists

Everyone knows how to train a language model. You collect text, you run gradient
descent, and the knowledge ends up distributed across weight deltas; if you want
to do it cheaply you train a LoRA adapter instead of the full network. The
procedure is standard, the vocabulary is standard, and none of it applies here.

This is not a language model. In several respects it is the opposite of one, and
the differences are not cosmetic — they change what a teaching pass *is*, what it
costs, what can go wrong, and how you check that it worked.

| | LLM (pre-train / fine-tune / LoRA) | this substrate |
|---|---|---|
| what a teach changes | weight deltas | rows in stores |
| granularity | one fact is smeared across all parameters | one fact is one row |
| how you undo one fact | retrain, or drop the whole adapter | delete the row |
| provenance of a fact | gone at the gradient step | carried on the fact, queryable |
| when it takes effect | after the training run | on commit |
| can it hold a fact *and know it's doubted* | no | yes — the posterior moves |
| what "more knowledge" costs | compute | disk |
| **does repeating the same data help** | **yes — that's an epoch** | **no — that's double counting** |

The last row is the one that has already caused real damage here, and §6.2
measures it. Epoch intuition is correct for a network and catastrophic for an
evidence store: showing a Bayesian belief the same evidence twice does not
reinforce it, it *fabricates a second witness*. There are beliefs in this store
that the substrate is now 0.999999 certain of because the same single assertion
was counted 674 times.

So: there is no LoRA here, there is no fine-tune, there is no "training run".
There is **teaching** — admitting a claim through one door, with its provenance
and its evidence quality attached, into every system that ought to change
because of it.

---

## 2 · The rule

> **One teaching path, through the authority, touching all systems. There is no
> solo teaching.**

A teach that reaches the concept graph but not beliefs has not taught the
substrate a fact — it has inserted a row. The substrate can then *walk* the edge
while not *believing* anything, having no word-class for the terms, no memory of
being told, and no domain that grew. That is four systems out of five holding
still while one moves, and the result is a system that can recite and cannot
think.

This mirrors how an LLM is trained, and that is the point of comparison worth
keeping: you do not fine-tune one attention head. The whole network moves or the
training step is broken. Here, the whole substrate moves or the teach is broken.

---

## 3 · The one path

Everything enters through the learning authority (`coord.learning`,
`UnifiedLearningSystem`). There are five public ways to teach, and they are
different *shapes of knowledge*, not different pipelines:

| method | file:line | shape of knowledge |
|---|---|---|
| `learn_fact` | [unified_learning_system.py:2875](../core/learning/unified_learning_system.py#L2875) | one declarative triple |
| `learn_facts` | [:3014](../core/learning/unified_learning_system.py#L3014) | many facts, fan-out amortised once; each may carry **the sentence it was said in** |
| `learn_concept` | [:3114](../core/learning/unified_learning_system.py#L3114) | a node and its edges |
| `learn_rule` | [:3147](../core/learning/unified_learning_system.py#L3147) | a told conditional → held-conditional store |
| `learn_word_classes` | [:2941](../core/learning/unified_learning_system.py#L2941) | what CLASS a word has → **memory** |

`learn_words` is gone with the lexicon it wrote to. It was replaced by
`learn_word_classes`, and the difference is where a word class lives: a lexicon
file was a second authority beside memory — unwipeable, ungrowable by teaching,
and unarguable-with. A stated class is now an ordinary semantic memory.

All of them converge on two things:

```
learn_*  →  cognitive_ingress.admit_relation()   ← THE DOOR   (one instance, one door)
         →  _fan_out_learning()                  ← THE SYSTEMS
```

### 3.1 The door — what it refuses, and why refusal is absence

[`admit_relation`](../core/semantics/cognitive_ingress.py#L267) is the only way
into the concept graph. It checks, in order:

- **Provenance is required.** There is no anonymous entry. A `Provenance`
  carries producer, source id, and source type; an unknown source type is a
  refusal, not a default.
- **The support floor** — `MIN_ADMIT_QUALITY = 0.5`
  ([:49](../core/semantics/cognitive_ingress.py#L49)). Below it the door does
  not open. This is the substrate's answer to "I don't know": **absence, not a
  low-posterior belief.** A weak belief has already contaminated the graph and
  will be reasoned over like any other; an absent one has not.
- **Shape.** A term may be at most `MAX_TERM_WORDS = 4`
  ([:111](../core/semantics/cognitive_ingress.py#L111)) — "past this it is a
  clause, not a name". Relations likewise, and a relation carrying a determiner
  is a phrase cut mid-term. The door checks, *not the caller* — every caller had
  its own idea of what was worth writing down, and the one that guessed hardest
  wrote the most.
- **Normalisation** ([:173](../core/semantics/cognitive_ingress.py#L173)) — one
  surface form, one canonical concept, delegated to `lexical_normalization` so
  `bird` and `birds` cannot enter as two concepts.

If you are writing a teaching pass, **read the `Admission` object, including
`refusals`**. It is the only place the door explains itself, and a pass that
counts `admitted` without reading `refusals` will report success while writing
nothing. That has happened here before.

### 3.2 The systems — what a taught fact must touch

[`_fan_out_learning`](../core/learning/unified_learning_system.py#L3287) is the
shared fan-out, so a fact and a rule touch the same systems. Each arm is
isolated: one failing never rolls back what already landed.

| system | store | what changes |
|---|---|---|
| **concept graph** | `unified.concepts`, `concept_relations`, `concept_aliases`, `concept_domains`, `concept_evidence`, `evidence_envelopes` | the node, the edge, the identity, the evidence |
| **beliefs** | `unified.beliefs` | one posterior moved per admitted clause, at the stated quality |
| **word classes** | semantic memory, tagged `word_class` | *(not an arm of the fan-out)* a class is TOLD through `learn_word_classes`, or DERIVED by `warm_word_classes` from the surface of a taught proposition. There is no lexicon: `data/lexicon.json` and `core/semantics/lexicon.py` are deleted, and so is the `save_lexicon` flag |
| **memory** | semantic memory (`MemoryType.SEMANTIC`) | the claim, recallable later *by meaning* |
| **domain** | `ensure_domain`, then an `EVIDENCE_ADMITTED` announcement | the domain is REGISTERED, and the substrate is told — which is what wakes crystallisation, expansion and discovery. `ensure_domain` alone does NOT crystallise; see §12 |
| **metrics** | in-process counters | the learning is counted |
| **held conditionals** | `unified.held_conditionals` | (rules only) what the reasoner chains over |

`quality` is a **required** argument to the fan-out and used to be `= 0.9`. That
default became the prior of 204,865 of 205,861 beliefs before anyone chose it —
"a default cannot be told apart from a judgement once it is in the store, which
is exactly why there is no longer one."

---

## 4 · What counts as solo teaching

Four things, all present in the repo today:

1. **`fan_out=False`** — writes the graph, skips beliefs, domain, metrics.
2. ~~**`remember=False`**~~ — deleted 2026-09-20; admission always remembers (§7.3).
3. ~~**`save_lexicon=False`**~~ — deleted 2026-09-22 with the lexicon itself. There
   is no file to flush, so there is no window in which a batch has taught the
   graph and not the vocabulary.
4. **Bypassing the authority** — calling `observe_claim`, or writing a store
   directly, instead of teaching.

Measured at the call sites:

**The memory column no longer has a choice in it** — `remember` was deleted on
2026-09-20 (§7.3). This is what the call sites looked like before that.

| script | line | fan-out | memory |
|---|---|---|---|
| `teach_session.py` | [157](../scripts/teach_session.py#L157) | ✅ on | ✅ configurable |
| `teach_conceptnet.py` | [121](../scripts/teach_conceptnet.py#L121) | ✅ on | ❌ `remember=False` |
| `teach_general_wikidata.py` | [242](../scripts/teach_general_wikidata.py#L242) | ✅ on | ❌ `remember=False` |
| `teach_graduate_wikidata.py` | [115](../scripts/teach_graduate_wikidata.py#L115) | ❌ **off** | ❌ `remember=False` |
| `teach_wordnet_taxonomy.py` | [118](../scripts/teach_wordnet_taxonomy.py#L118) | ❌ **off** | ❌ `remember=False` |
| `teach_conceptnet_beliefs.py` | [93](../scripts/teach_conceptnet_beliefs.py#L93) | — **bypasses the authority entirely** | — |

That last row is the tell. `teach_conceptnet_beliefs.py` exists *to repair the
solo teach that preceded it* — it re-reads the same dump and calls
`observe_claim` directly to backfill the beliefs the first pass skipped. Its own
comment names the alternative it declined: "`coord.learning.learn_facts` over the
triples — heavier, re-admits." A second pass over the same file, outside the one
authority, to add the systems the first pass left out, **is** the duplicate
pipeline.

---

## 5 · Why solo teaching was invented here (the real root cause)

`teach_wordnet_taxonomy.py` turns the fan-out off deliberately, and its docstring
says exactly why:

> `fan_out=False` (the class of every term is taught directly in step 1,
> **correctly**, instead of being guessed from an article that a bare
> `child isa parent` surface does not have)

That author was right about the symptom. Here is the mechanism.

**FIXED 2026-09-22 — a fact may now carry the sentence it was said in.** What
follows is what the defect was, and it is kept because the shape of it recurs.

`learn_facts` synthesised a surface from the triple, and that was the only
surface there was:

```python
surface = " ".join(str(p) for p in (subject, relation, obj) if p)   # "beagle isa dog"
```

A word class is derived from the surface of a taught proposition, and that
string is not English. It has no article, and `isa` is a typed relation nobody
ever says — so the relation was never recorded as a VERB, and the object of a
kind-relation is always a NOUN. **The store could therefore only ever learn
nouns, whatever the source knew.** Measured after a full pass: 199 words, every
one a noun — and `_reads_as_verb` then REFUSED every sentence whose verb had
been catalogued that way.

`TaughtRecord.sentence` now carries the fact as said ("A pump is a device."),
`learn_facts` takes it as the surface, and the pass READS it — a definition
states the kind AND what the kind does, which is the only place a verb appears
in a taxonomy source. The old text follows.

The fan-out handed that surface to `observe_proposition`, which decided the
object's word class by looking for an article:

```python
_record(obj, NOUN if _has_article(sentence, obj) else ADJECTIVE)
```

The heuristic is sound for a sentence a person actually said — "the beagle is a
dog" → NOUN, "the tank is hot" → ADJECTIVE. It is **systematically wrong for a
synthesised triple, where the article cannot be present by construction.**
Verified live:

```
surface='beagle isa dog'         has_article=False  -> dog       proposed as ADJECTIVE
surface='kettle isa container'   has_article=False  -> container proposed as ADJECTIVE
surface='alcohol isa drug'       has_article=False  -> drug      proposed as ADJECTIVE
surface='the beagle is a dog'    has_article=True   -> dog       proposed as NOUN
```

Every one of the 314,856 `isa` edges taught in bulk proposed its parent as an
adjective. The damage is visible in the lexicon today:

```
dog      NOUN confirmed   contradictions=163   all "conflicting proposal ADJECTIVE from taught"
run      VERB proposed    contradictions= 65
water    NOUN confirmed   contradictions= 61
alcohol  NOUN proposed    contradictions= 42
```

This is the same defect shape as the perception defects fixed earlier this
month: **a measurement taken where the information cannot be**, with absence of
evidence read as evidence of the negative. It is a false negative in the sense
the project forbids.

**So solo teaching here is not laziness — it is a workaround for a broken arm of
the one path.** The fix is not to keep the arm switched off. It is to feed that
arm the word class from the source's own tag, in the same pass, and stop
guessing. Which brings us to the tag that is currently thrown away.

---

## 6 · The four defects a real teaching pass has to fix

### 6.1 The part of speech is discarded at the parse

Both ConceptNet scripts carry verbatim copies of `_term()`:

```python
def _term(uri):
    """/c/en/hot_dog/n -> 'hot dog'; non-English -> None."""
    p = uri.split("/")
    return p[3].replace("_", " ").strip().lower()      # p[4] is the part of speech
```

It **names the part of speech in its own docstring and discards it**, in both
copies, on every pass ever run. The grammar the substrate needs for articles,
number, and agreement has been going past this line and onto the floor — while
the fan-out, downstream, guesses that same grammar from a surface that has none
(§5). One line of one file carries both the answer and the wrong guess.

The weight is on the same line too: ConceptNet puts the assertion, its weight,
and the POS tag in one row. **Grammar and content are properties of one harvest,
not two passes.** Any design that reads that row twice has two pipelines again.

### 6.2 Re-teaching is not idempotent, because the guard is in-memory

The door deduplicates on a hash of `subject|relation|object|source_id`
([:311](../core/semantics/cognitive_ingress.py#L311)) against `self._seen`
([:223](../core/semantics/cognitive_ingress.py#L223)) — **a plain set on the
singleton.** It does not survive a restart. In a fresh process every previously
taught fact is new again, the fan-out runs again, and `observe_claim` appends
another evidence entry to the same belief.

Measured:

```
beliefs re-observed  >10 times     3,395    (3,220 of them in the `tools` domain)
beliefs re-observed >100 times     2,588
worst single belief                  674 observations, posterior 0.999999
   "misp_get_event provides get_system_info"
```

Those are tool capabilities re-registered at every boot. The substrate is now
essentially certain of them **because it rebooted 674 times**. That is one
witness counted 674 times, which is precisely the epoch intuition from §1
applied to a store where it is invalid.

Requirement: **teaching the same fact from the same source twice must not move
the posterior.** Restart survival is the default here, never an open item — the
idempotence guard has to live where the facts live.

### 6.3 One stated quality becomes the prior of everything

```
beliefs                              573,278
  at posterior 0.99                  498,193   (87%)
  update_count == 1                  537,699   (94%)
```

A corpus taught at a single stated quality gives almost every belief the same
posterior and no revision history. That is not a defect of the mechanism — the
mechanism did what it was told — but it means the belief store currently carries
almost no *discrimination*. ConceptNet ships a per-assertion weight and it is
being ignored: over 230,137 English `IsA` edges, 120,107 sit at weight 1.0,
76,951 at 2.0, and 31,746 at 0.5 — and `oxygen isa book` is one of the 0.5s.
The weight is the per-fact quality the fan-out already demands.

### 6.4 "The first N" is the alphabetical head

ConceptNet's CSV is sorted by assertion URI. A pass that takes the first N edges
gets `00t shirts`, `10 downing street`, `1976 audi` — not a sample of English.
The 4,000 facts taught in one session this month were all of that shape. **A
real pass streams the whole file or samples across it**, and says which it did.

---

## 7 · How to teach properly

### 7.1 The shape

One owner of source → taught facts. Not a shared helper that seven scripts
import — *a shared `_term()` that all seven call is not one pipeline, it is seven
pipelines agreeing about one function.* The owner has to hold the **policy**:

```
TeachingPass                        ← the one owner
  ├─ Source          which dump, streamed WHOLE (not its head)
  ├─ Harvest         one row → (subject, relation, object, quality, word classes)
  │                    the weight and the POS tag come off the SAME row
  ├─ Map             source relation → substrate relation
  ├─ Gate            per-fact quality; below the floor it is not taught
  └─ Teach           learning.learn_facts(..., fan_out=True, quality=<per fact>)
                     learning.learn_word_classes(...)   ← same pass, same row
```

A record that can say itself in English is READ rather than assumed: the triple
is what the source's FORMAT states, the sentence is what the source's own WORDS
say, and a definition says more than its taxonomy edge does. A sentence-only
record (a gloss, with no triple behind it) is read or it is dropped — there is
no fallback that could file a mis-parsed gloss as a taxonomy edge.

The existing scripts become thin invocations naming a source, or they are
deleted.

### 7.2 The rules

1. **Go through the authority.** Never `observe_claim`, never a direct store write.
2. **`fan_out=True`, always.** If an arm of the fan-out is wrong, fix the arm.
   Switching it off is how the substrate ended up able to recite without
   believing.
3. **State the quality per fact**, from the source. Never inherit a default.
4. **Teach the word classes from the source's tag**, in the same pass, never by
   guessing from a synthesised surface.
5. **Be idempotent.** Re-running a pass must not make anything truer.
6. **Stream the whole source**, and say so if you sampled.
7. **Read `refusals`.** An `Admission` that refused is information, not an error
   to swallow.

### 7.3 `remember` is gone — RESOLVED 2026-09-20

Four of five corpus passes disabled the episode. The stated reason was that a
reference taxonomy is knowledge, not a conversation to recall. But
[`_remember`](../core/semantics/cognitive_ingress.py#L444) does not store an
event — it stores a **semantic** memory, and its own comment says why: what was
learned has to be findable later **by meaning**, and that "is the whole point of
storing it, and the substrate's alternative to baking knowledge into weights."

So turning it off for the entire reference corpus left that corpus reachable
only by exact-name graph lookup, never by meaning.

**Resolved by deleting the parameter, not by choosing a value for it.** The
question was never which value to pass; it was that a flag existed at all. A
fact is a fact however it arrived, and identical knowledge having different
standing depending on which door it came through is the second pipeline showing
up in the output. Measured before removal: ask about a conversation-taught fact
and the substrate answered *"I remember: a kettle boils water."*; ask about one
of the 314,856 taught from ConceptNet and it answered correctly while having no
recollection of ever learning it.

The performance defence was measured rather than argued: **12.5 facts/s with the
episode against 18.4 without (+47%)** — the full taxonomy costs about 7.0h
instead of 4.7h. Real, and not a reason to hold two grades of knowledge.

[`REMEMBER-01`](../experiments/REMEMBER-01/experiment.py) (5/5) pins it: the
parameter is absent from both `learn_facts` and `admit_relation`, a bulk
admission carries a real `memory_id`, and a fact taught in bulk now answers
**"I remember: ..."** — the behaviour only conversationally taught facts had.

---

## 8 · How to verify a teach

A teaching pass that reports only "N facts admitted" cannot be audited. Every
run writes a before/after report to `docs/teaching_sessions/<ts>.md`, and the
report must cover **every system**, because the whole point is that all of them
moved:

```sql
-- concept graph
SELECT COUNT(*) FROM unified.concepts;
SELECT COUNT(*) FROM unified.concept_relations WHERE relation IN ('isa','is a');

-- beliefs, WITH the distribution (a single spike means one stated quality)
SELECT ROUND(posterior_probability::numeric,2) p, COUNT(*)
  FROM unified.beliefs GROUP BY p ORDER BY 2 DESC LIMIT 8;

-- provenance is in evidence_for, NOT evidence  (the `evidence` column is null)
SELECT e->>'source' src, COUNT(*), ROUND(AVG((e->>'quality')::numeric),3)
  FROM unified.beliefs, LATERAL jsonb_array_elements(evidence_for) e
  GROUP BY src ORDER BY 2 DESC;

-- idempotence: this must NOT climb across runs
SELECT COUNT(*) FROM unified.beliefs WHERE update_count > 10;

-- domains
SELECT domain, COUNT(*) FROM unified.beliefs GROUP BY domain ORDER BY 2 DESC;
```

and the word classes, which are MEMORIES — not a file, and not a table of their
own:

```sql
-- every class the substrate holds, and how many words it holds under each
SELECT metadata->>'word_class' AS class,
       COUNT(DISTINCT metadata->>'word') AS words
FROM memory_hot.memory_hot
WHERE tags @> '["word_class"]'::jsonb
GROUP BY 1 ORDER BY 2 DESC;

-- idempotence: every pair must appear EXACTLY once. More than one row for a
-- (word, class) is a pass that taught what it had already said.
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT (metadata->>'word') || '|' || (metadata->>'word_class')) AS pairs
FROM memory_hot.memory_hot WHERE tags @> '["word_class"]'::jsonb;
```

**Watch `rows` against `pairs`.** They must be equal. When they diverged —
98,198 rows carrying 57,671 pairs — the cause was orphaned
`multiprocessing.spawn_main` children re-running the whole pass, which is why
`scripts/teach.py` now has an `if __name__ == "__main__"` guard.

### Where the store stood on 2026-09-20

| | |
|---|---|
| concepts | 308,475 |
| concept relations (isa) | 575,329 (314,856) |
| concept evidence | 1,145,105 |
| beliefs | 573,278 |
| lexicon entries | 92,470 — NOUN 68,441 · ADJ 18,152 · VERB 5,877 *(the lexicon is deleted; kept as the historical figure)* |
| lexicon sources | wordnet 72,457 · taught 19,947 · observed 39 *(historical)* |
| largest domains | vision 356,011 · general 195,292 · tools 3,681 |

Measured throughput with the whole system firing: **8.9 facts/s, 11,747
bytes/fact** — so 10 GB buys roughly 851k facts and about 27 hours. Disk is the
budget, not compute. That is the LLM contrast made concrete: knowledge here is
something you store, not something you spend GPU-hours compressing.

---

## 9 · Source hygiene — the hard rules

*Absorbed from `docs/design/TEACHING_ARCHITECTURE.md`, which was a second
teaching doc. These were learned expensively and are now enforced in code by
`TeachingPass._guard_reasoning_edges` rather than remembered by whoever writes
the next script.*

The reasoner walks the concept graph's `isa` edges as a **transitive closure**,
so one bad edge is not one bad fact — it is every conclusion reachable through
it.

- **Never admit crowd-sourced free text as reasoning `isa` edges.** Raw
  ConceptNet `/r/IsA` carries `apple isa car`, `dog isa cuter_than_kid`,
  `robin isa band` (the singer) alongside real hypernymy. Admitted wholesale it
  gave 450k `isa` edges, a term's ancestor set exploded 45→681 over one to four
  hops, and the reasoner confabulated `dog isa plant` via
  organism→system→plan_of_action→plant. **The quality gate does not save you
  here** — `apple isa car` is well attested by people who found it funny. The
  reasoning taxonomy must be curated hypernymy (WordNet, Wikidata P279).
- **Record provenance per edge.** That cleanup was expensive precisely because
  `concept_relations` recorded no source — WordNet and ConceptNet both tagged
  `extractor='structured'` — so junk could not be retracted selectively and had
  to be separated by content against a reference set.
- **Bound the closure.** Cap the `isa` walk (currently 4 hops): real
  common-sense subclass chains are short, and a long walk over a name-keyed
  graph invites homonym drift. Abstain past the bound.
- **Beliefs back-stop the bounded graph.** Where the graph cannot derive an
  `isa` within the bound, the belief store answers — a fact taught and held
  ≥0.99 (`copper isa metal`). An untaught claim has no such belief, so recall is
  restored without reintroducing confabulation.

The audit behind these is `experiments/systems/KNOW-50`: 37/40 true correct,
100% of answered correct, 0 confabulations, 0 model calls.

---

## 10 · Running a pass, and what used to go wrong

- **Detach a long run** — `nohup env … python3 scripts/teach.py … > logs/x.log
  2>&1 </dev/null & disown`, then confirm `ps -o ppid -p <PID>` shows `1`.
  Closing a terminal has killed a multi-hour pass before.
- **Verify after the flush, not from progress lines.** Belief writes are
  fire-and-forget until flushed; a flat count mid-run is not a failure.
- **Watch the rate.** If throughput decays as the store grows, something is
  O(n²) — stop and fix. `observe_claim` was once a linear scan at ~180/s and
  falling; with the claim index it is ~68,000/s and flat.

**Two entries in the old failure table were themselves defects, and both are now
fixed rather than worked around:**

| old advice | what it actually was |
|---|---|
| *"Re-run teaches but 0 new beliefs → backfill via direct `observe_claim`"* | This is what produced `teach_conceptnet_beliefs.py`, the authority bypass. Re-teaching now correctly changes nothing, and 0 new beliefs is the right answer, not a problem to route around. |
| *"Reinforcement on re-teach: 0.9926 → 0.9995"* — listed as a verified reference number | That was the double-counting. Re-presenting one witness is not corroboration; see §6.2. Repaired across 34,774 beliefs on 2026-09-20. |

---

## 11 · Teaching a LIVE substrate

**Every teaching script before 2026-09-20 called `TorinAISystem.initialize()`
and never `start()`.** That constructs every first-class module — appraisal,
motivation, the domain authority, perception, the coordinator — and starts none
of them. They are woken by events, and the reactive drain worker that runs
deferred reactions is started only by `start_coordination()`, which only
`start()` calls.

So teaching poured knowledge into an organ of a substrate that was switched
off. The modules were not bypassed; they were present and inert.

`scripts/teach.py` is the one teaching entry point and it starts the substrate:

```
PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/teach.py --source wordnet --domain lexical
```

- `start()`, not `initialize()` — and it **refuses to teach** if the reactive
  drain worker is not running, rather than teaching into a substrate that cannot
  react.
- The substrate **perceives** being taught: a corpus arriving is external input,
  and `process_input` is the one door external input comes through. Teaching
  went around it for as long as teaching has existed.
- Nothing in the script orchestrates subsystems. The authority announces an
  admission; the substrate reacts on its own drain worker, coalesced. **That is
  why teaching is not a loop over subsystems** — a domain sweep is a full graph
  scan and must be allowed to take as long as it takes.
- It does not exit until the substrate has finished reacting. A pass that
  returns while the drain queue is full has measured its own inserts and
  nothing else.

Verified: one `EVIDENCE_ADMITTED` per batch (not per fact), waking
`crystallize_taught`, `domain_expansion_on_evidence` and `pursue_frontier`.

---

## 12 · Announcing is not a caller's option

`_fan_out_learning` branched on whether the CALLER passed an emitter, and only
the conversational path ever did. A fact told in conversation woke the domain
authority; the same fact taught from a corpus woke nothing. The `elif` branch
claimed to "crystallize it immediately" via `ensure_domain` — but that method
**returns an already-registered domain unchanged**, so for every domain a corpus
teaches into it was a call that did nothing.

Measured before the fix: `lexical` holds over 300,000 taught facts, and the
substrate's belief that it has learned that domain sat at its **0.5000 prior
with zero updates**. 234 competence beliefs across 163 domains, every one at
0.5000, none ever moved. The substrate could not tell you it had learned
anything, because nothing had ever told it.

Now `UnifiedLearningSystem._announce` runs on **every** admission. A caller
holding its own transport (the conversation) supplies it; everything else
reaches the live coordinator through the runtime registry. There is no silent
no-op: an admission the substrate was not told about — no live substrate, or a
failed announcement — is counted on `admissions_unannounced` and reported by
every teaching pass.

**Still open:** competence does not move on learning. `record_competence_evidence`
has four call sites, all on *acting* outcomes. Raising competence on taught
volume alone would be a lie — the substrate would believe it is competent
because it was fed. The exam is what earns it, and it is the next piece.

---

## 13 · Open

- The one pipeline **is built**: `TeachingPass` owns the policy and
  `scripts/teach.py` is the entry point. Sources name a format and decide
  nothing.
- ~~§5 (lexicon arm)~~ — RESOLVED 2026-09-22. The lexicon is deleted. A word
  class is a memory: told through `learn_word_classes`, or derived by
  `warm_word_classes` from the surface of a taught proposition. The surface is
  now the sentence the fact was SAID in, which is what makes a verb learnable.
- ~~§6.2 (idempotence)~~ — RESOLVED 2026-09-22, and the cause was not the store.
  `scripts/teach.py` ran `asyncio.run(main())` at module level with no
  `if __name__ == "__main__"` guard; macOS spawns multiprocessing children by
  re-importing `__main__`, so every child re-ran the whole pass and OUTLIVED the
  parent it was killed with. A pass now teaches each thing once.
- The quality gate (§6.3) should land before scale is spent, so the scale is not
  spent on noise — the store held `dog isa cat`, `oxygen isa book`,
  `clock isa book`.
- ~~`remember=False`~~ — RESOLVED 2026-09-20; the parameter is deleted (§7.3).
- **A domain is still whatever the caller passed.** `ensure_domain` registers a
  name; it originates nothing. Everything a corpus teaches lands in one bucket,
  so the subsystem that exists to carry knowledge BETWEEN subjects has one
  subject to work with.

Related: [architecture/learning.md](architecture/learning.md) ·
[architecture/semantics-ingress.md](architecture/semantics-ingress.md) ·
[research/COMPREHENSION_SCOPE.md](research/COMPREHENSION_SCOPE.md)
