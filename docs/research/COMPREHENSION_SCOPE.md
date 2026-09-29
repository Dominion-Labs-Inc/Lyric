# Comprehension — what is actually wrong, and what closing it takes

Written 2026-09-19, after the speech paths were collapsed into one and the
rendering was fixed far enough to expose what sits underneath it. Every number
here was measured against the live substrate during that session; nothing is
estimated.

---

## Amendment, 2026-09-22 — half of this is now closed

**Part of speech now exists.** It is taught into memory as ordinary semantic
knowledge (`learn_word_classes`, one memory per `(word, CLASS)`), and the
substrate holds **19 classes**: the four open ones, fourteen closed ones, and
punctuation. WordNet states 75,834 of them, including 3,630 adverbs that this
document was written while the code was dropping at the door. There is no
lexicon file; a wipe takes the vocabulary with it, which is the point.

**What this document says about the REST is still true.** There is still no
number, no countability, no agreement and no proper-noun marking anywhere in the
store, so every example in the table below still fails for the reason stated. A
part of speech was the first missing piece, not the only one — do not read the
amendment as closing the finding.

---

## The finding

**The substrate composes English with no grammatical knowledge whatsoever.**

Verified directly against the store: the relations it holds are `isa` (314,856)
and the perception relations built today (`contains`, `occupies`, `sits`,
`larger_than`, `above`, `left_of`, `has_width`, …). There is **no part of
speech, no number, no countability, and no proper-noun marking anywhere in it.**

So every article and every verb form in a reply is a string heuristic —
`_article()` picks "a" or "an" by looking at the first letter, and that is the
whole of the grammar. This is why fixing one class of error kept revealing the
next:

| what was said | what it should say | what was missing |
|---|---|---|
| "An alcohol is found in a fraternity house." | "Alcohol is found in a fraternity house." | countability |
| "that was about kettle" | "that was about a kettle" | countability |
| "an andaman islands **is** found in…" | "The Andaman Islands **are** found in…" | number, agreement |
| "a bay of bengal is found in a south asia" | "The Bay of Bengal is found in South Asia." | proper nouns |
| "A bird is found in **an air**" | "A bird is found in the air." | countability (object side) |

Three of those are now fixed — by taking the determiner from the person's own
sentence (the only countability evidence available) and by deriving number from
the store (a word ending in `-s` whose singular is also held is plural: measured
9/9 on plurals, 11/13 on singulars). **Proper nouns and object-side countability
are not fixed and cannot be by more of the same**, because the knowledge is not
there to consult.

---

## The knowledge that is missing, and where it is

| needed | in the store? | available? | where |
|---|---|---|---|
| word class (noun/verb/adj/adv) | no | **yes** | the POS tag on every ConceptNet URI — `/c/en/dog/n` |
| number (singular/plural) | no | **yes** | 378,859 `/r/FormOf` edges; 60,000 English sampled, 72% nouns |
| countability (mass/count) | no | **derivable** | a noun with no plural `FormOf` is mass — `alcohol`, `water` |
| proper noun | no | **partial** | `/r/InstanceOf`; ConceptNet lowercases, so capitalisation is lost |

**The POS tag is currently thrown away.** The harvest reads `uri.split("/")[3]`
and ignores `[4]`, which is exactly the part of speech. It has been discarded on
every teaching pass so far.

---

## First: there must be ONE teaching pipeline

There are seven teaching scripts — `teach_conceptnet.py`,
`teach_conceptnet_beliefs.py`, `teach_wordnet_taxonomy.py`,
`teach_general_wikidata.py`, `teach_graduate_wikidata.py`, `teach_session.py`,
`teach_theorems.py` — and the two ConceptNet ones parse the **same dump** with
their own verbatim copies of `_term()` and `build_isa()`.

`learning.learn_facts()` is the one authority underneath and that part is right.
What is duplicated is the **policy**: which source, what to harvest, which
relations to keep, how a term is normalised, what quality floor applies, whether
the part of speech survives. Every script decides all of that for itself, which
is the same shape as the two speech renderers — one owner underneath, several
callers each re-deriving what the owner should have settled.

The cost is not hypothetical. `_term()` reads:

```python
def _term(uri):
    """/c/en/hot_dog/n -> 'hot dog'; non-English -> None."""
    p = uri.split("/")
    return p[3].replace("_", " ").strip().lower()      # p[4] is the part of speech
```

It **names the POS tag in its own docstring and then discards it**, in both
copies, on every pass that has ever run. The grammar the substrate needs has been
going past this line and onto the floor for months.

So the work below is not four passes over a dump. It is **one pipeline** that
owns source → taught facts, holding in one place:

- the harvest (streaming the whole file, not its alphabetical head)
- term normalisation, **keeping the part of speech**
- the relation mapping (ConceptNet/WordNet/Wikidata relation → substrate relation)
- the quality gate (the weight floor below)
- one call to the one learning authority

and the existing scripts become thin invocations naming a source, or are deleted.
Grammar and content come out of the SAME file in the SAME pass — splitting them
into separate passes would be inventing the second pipeline again.

---

## What that one pass has to carry

### 1 · The grammar, which is currently on the floor

Word class from the URI tag; number from `FormOf`; countability from the absence
of a plural. These are lexical facts and go in through the one learning path like
every other fact, so they arrive with provenance and can be revised.

*Buys:* correct articles and agreement for every noun, not only the ones the
person just said. Closes the two failures above that nothing else can.

*Verified by:* the two probes already written — the plural test (currently 9/9
and 11/13, should go to 13/13 once number is held rather than inferred) and the
mass/count separation (currently impossible, should separate cleanly).

### 2 · A quality gate, in the same pass

The store holds `dog isa cat`, `clock isa book`, `oxygen isa book`, `chair isa
commortable to sit`. These are crowd-sourced noise, and the speech layer now
renders them in fluent English, which is worse than rendering them badly.

**ConceptNet carries a weight on every assertion and it is being ignored.**
Measured over 230,137 English `IsA` edges: 120,107 at weight 1.0, 76,951 at 2.0,
31,746 at 0.5. `oxygen isa book` sits at **0.50**, from a dbpedia scrape. A floor
at 1.0 drops ~14% of the edges and takes that class of noise with it.

Not a complete filter — `1 isa abstaction` (a typo) carries weight 2.0 — but it
is a real signal presently unused.

*Buys:* answers that are wrong less often; and it is a precondition for step 3,
because the sense detection below is only as good as the parents it reads.

Both of these are properties of ONE harvest, not two passes: the weight, the POS
tag and the assertion itself arrive on the same line of the same file, and any
design that reads that line twice has two pipelines again.

---

## Then, and only then: what depends on the pipeline

### 3 · Question comprehension

Four measured failures, none of them about rendering:

- **Greetings are looked up as concepts.** "hello" → *"A hello is an airline. It
  is a greeting."* A greeting is a social act, not a query.
- **A yes/no question with no answer recites facts instead of declining.** "is a
  grandfather clock a beer?" returns clock facts, then beer facts.
- **Locative questions lose to ambiguity.** "where is a dog?" answers with senses
  instead of places.
- **Sense detection over-fires.** Asked for ambiguity, it now asks "Which dog do
  you mean?" because `dog` has unchained parents in the store — most of which are
  noise. It cannot tell a second SENSE from a second PARENT without knowing which
  kinds exclude each other, and it does not. Depends on step 2.

### 4 · Recall

It recites raw records as memories: *"I remember: Observed the vision test card
on the workbench."* (a log line), *"September 2, 2025 -A card is often described
assomething small and handy…"* (an unspaced web scrape). Relevance is also poor —
asked about `bass`, it recalled a fact about an embassy.

---

## Not in scope

- Rewriting the renderer again. It is one path now (`say()`), a fact becomes
  words in one place (`_triple_sentence`), and it is artifact-clean at 16/16.
  What remains wrong with the output is knowledge, not rendering.
- A parser or POS tagger. The substrate has one reader by design; word class is
  taught as fact, not inferred by a second machine.
- Bulk-teaching for scale. Measured at 8.9 facts/s and 11,747 bytes/fact with the
  whole system firing — 10 GB buys ~851k facts and ~27 hours. That is a separate
  decision from this, and the quality gate should land first so the scale is not
  spent on noise.
- Seven scripts kept alive behind a shared helper. A shared `_term()` that all
  seven import is not one pipeline; it is seven pipelines agreeing about one
  function. The owner has to hold the policy, not just the parsing.

---

## The one thing to decide first

Steps 1 and 2 are both teaching passes over the same dump, and the harvest has a
defect that affects both: **ConceptNet's CSV is sorted by assertion URI**, so
taking the first N edges returns the alphabetical head. The 4,000 facts taught
during this session were *all* `at_location`, about `00t shirts`, `10 downing
street` and `1976 audi`. Any real pass has to stream the whole file or sample
across it.
