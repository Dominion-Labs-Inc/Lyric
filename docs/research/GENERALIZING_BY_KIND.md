# Generalizing from few examples, by what things are

Research note, 2026-10-01. It follows `WORD_SENSES.md`, which settled how the listener picks a word's sense. This
note asks how the substrate goes beyond the examples it was given: how a construction it learned from a few words
takes a word it never saw there, and how it knows how a word is used (counted, uncounted, a name) when nothing it
read shows it.

**Status (2026-10-02).** Step 1 is built and measured (COUNTABILITY-01, §4.1). Steps 2 to 4 are not built.

## 1. The problem, as measured

What is still wrong after the fixes of 2026-10-01 (LAB_NOTEBOOK entry 20) falls into two kinds.

**A construction does not reach words it never held.** After english_29, "Rex ate food.", "Tom ate bread." and
"Rex drank water." read, and so does "The dog drank water.". But "Rex ate rice." reads "ate rice" as a new name,
and "The cat ate fish." reads only as eating a fishing. The learner holds a verb with a bare object as a two-word
phrase. A noun stands in that phrase only where it has stood beside the phrase's own nouns somewhere
(`stood_beside`). The guard is there for a reason: without it, "walked carefully" was read as a count. Its kinds are
built only from distribution: two words are one kind once they shared a slot. This does two things wrong. Words
that are a thing and a doing ("run", "walk", "fish") join the noun kind to the verb kind, which is how a kind slot
came to say "reasoned". And a word seen in one place only ("cake", taught once) is a kind of its own.

**How a word is used is unknown where nothing read shows it.** These are wrong:
- "a baggage": Brown has four uses, and none of them tells.
- "Fish is a person.": WordNet's capitalized "Fish", one born under Pisces.
- "chairman", stated uncounted: its bare uses are roles ("served as chairman").

Measured against a hand-annotated lexicon (§2.2), the Brown model is right 89% of the time but finds only 153 of
815 uncounted words. It counts every plural as evidence of counting, and uncounted nouns pluralize too
("waters").

What the two share: a decision about a word is made from that word's own history alone, when what the word IS
(what memory holds it to be a kind of) would decide it.

## 2. What is known

### 2.1 How constructions extend to new words

- **Coverage** (Suttle and Goldberg 2011). Speakers accept a new word in a construction to the degree that the
  attested instances cover the semantic space that includes it: type frequency and the variety of attested
  instances combine, and similarity to an attested instance helps.
- **Semantic coherence** (Barðdal 2008). Productivity is a function of type frequency and semantic coherence, and
  the two trade off. A construction with many types needs little coherence. One with few types extends by
  analogy when its members are alike: "ate food, bread, a bone, a cake" is few and coherent.
- **Constructions as associations of syntax and meaning** (Alishahi and Stevenson 2008). They generalize over the
  semantic features of their arguments, and recover from overgeneralizing without negative evidence.
- **Overhypotheses** (Perfors, Tenenbaum and Wonnacott 2010). Learners acquire constraints on classes of verbs, not
  only on single verbs, and use them to generalize to a verb seen once.
- **The Tolerance Principle** (Yang 2016), already the substrate's test for productivity: a generalization over N
  cases holds if its exceptions number at most N / ln N.

### 2.2 How countability is known

- **From a corpus** (Baldwin and Bond 2003). Corpus features with memory-based classifiers reach 94.6% on open
  data, against 89.7% for calling everything counted.
- **From what a noun is** (Bond and Vatikiotis-Bateson 2002). A noun's place in an ontology predicts its countability
  78% of the time, five ways.
- **By hand, sense by sense**: the Bochum English Countability Lexicon (BECL 2.1; Kiss et al. 2016; CC BY 4.0).
  11,869 WordNet noun senses over 7,050 lemmas: 8,432 counted, 2,425 uncounted, 697 both, and 315 neither (the sun).
  It labels senses, not words: `baggage.n.01` (luggage, baggage) is uncounted, `fish.n.01` counted. It does not hold
  everything ("water", "chairman", "advice", "hair" are missing).

### 2.3 Measured here (offline, WordNet's taxonomy, 2026-10-01)

On BECL's 9,537 counted or uncounted senses:

| | Decides | Right | Uncounted found |
|---|---|---|---|
| All counted | all | 76.9% | none |
| The Brown model now in the source | words with cues | 89% | 153 of 815 |
| By kind: the class most of its kind's labelled senses carry, within the Tolerance Principle, the sense itself left out | 91% | 89.4% | 1,174 of 1,732 |

By kind is as accurate as the corpus model and finds uncounted senses far better, and it decides senses no corpus
shows.

## 3. What the substrate already has

| Mechanism | In Lyric |
|---|---|
| What things are | memory's taxonomy (WordNet's kinds, taught) |
| Generalization through kinds | `said_selection` (what words are said of, Resnik), `listening_evidence` (held of kinds) |
| A word's use from its ending, within the Tolerance Principle | `PatternInventory.use_of` ("Bostonian" counted beside "Canadian", "Italian") |
| Kinds of words from distribution | `same_kind` (union of fillers), `stood_beside` |
| How the source states a record's words are used | `TaughtRecord.uses`, from Brown (`WordNetSource._uses`) |

## 4. Proposed: one mechanism, generalizing through what things are

1. **A word's use, sense by sense.** A record is about a sense, so its use is the sense's:
   - BECL's label where it has one;
   - else what its kind's labelled senses carry, within the Tolerance Principle;
   - else Brown's cues for uncounted use only ("much", "a piece of", bare). A plural is no longer evidence of
     counting.

   "Fish", the person born under Pisces, is a kind of person, and people are counted: "A Fish is a person.".
   "baggage" is uncounted by BECL's label on its synset. A card game or a language goes bare as its kind does.

   **Built and measured (COUNTABILITY-01, 2026-10-02)** as `WordNetSource.use_of`, on BECL's senses held out five
   ways by word:
   - **Accuracy.** The chain is right 85.3% of the time over all 9,537, against 76.8% for calling every sense
     counted and 79.2% for real text alone.
   - **Uncounted senses.** It finds 1,316 of the 2,212 uncounted senses; real text alone finds 293.
   - **One change from the order above.** The word uncounted in real text comes before the kind, for the sense the
     word is mostly used in ("advice", "rice", "coffee"; 8,138 right against 8,119 for the kind first). An uncounted
     verdict from real text needs a majority past the Tolerance Principle; a counted one needs a single use.
   - **Open:**
     - Abstract nouns (acts, communication, states, attributes, cognition) hold most of the errors.
     - "fish" the food is counted: its kind is split, and the word's single counted use decides it.
     - A word WordNet writes capitalized is given no use, though 134 of the 137 such labelled senses are kinds, not
       names, so the Pisces "Fish" is not yet said with "a". That belongs with proper nouns
       (`COMPREHENSION_SCOPE.md`).
2. **The reader's use of a word it holds nothing of** (`use_of`): as the words of its kind are used, within the
   Tolerance Principle, before its ending decides. The same principle the reader already applies to endings.
3. **A slot takes kinds, not only words.** The kinds a slot's attested fillers are, in memory: the most specific kind
   covering all but N / ln N of them (Barðdal's coherence, Suttle and Goldberg's coverage, the Tolerance Principle).
   A held word with a sense under such a kind stands there through a link proposed, in that sense. "ate food,
   bread, a bone, a cake": the fillers are food, so "rice" stands there, and "fish" stands there as the food. This
   is a second way past `stood_beside`, by meaning, beside the one by distribution. The guard against "walked
   carefully" stays, because "carefully" is no kind of food.
4. **Kinds of words stop merging doings with things.** The kinds a slot generalizes by are memory's kinds of the
   things its fillers name, so a word that is both a noun and a verb no longer joins the two.

   **One consequence found and closed (2026-10-02, COMPREHENSION-01).** The merge itself is not fixed.
   - **What happened.** The wordless phrase "?slot0 ?slot1" holds both "red cup" and "usually runs". Its second slot
     had 9 words written as their names ("cup", "box", "run") and 11 in a changed form ("runs", "climbed").
   - **Why it mattered.** A slot "written otherwise than by name" is taken to take a shape, and a noun standing in
     it to be used as a plural, so "cup" was a plural.
   - **The same rule at scale.** In "A ?slot0 is a ?slot1." 3,730 of 4,842 words were not their concept's name:
     other words for the concept, and words of senses named apart. Every noun in it became a plural.
   - **The fix.** `PatternInventory._written_otherwise`: a slot is written otherwise only when the words written as
     names are few enough to be exceptions (the Tolerance Principle). A filler is judged against its word's own
     name ("wall" for `object wall`).

   **A second consequence found and closed (2026-10-04, QUESTION-FORMS-02).**
   - **What happened.** A filler of a slot that takes a shape was counted a plural wherever the slot stood, the slot
     of a doing included: "kicked" in "?slot0 the ?slot1" (`instance_of(?n, ?slot0)`, done to `?slot1`, before now)
     and "chases" were held as plurals.
   - **Why it mattered.** The sayer puts a word held as a plural in any slot that takes a shape, so "chases" stood in
     the slot that says a chasing before now: "The kelt chases the blip." was said of the past.
   - **The fix.** A slot naming a kind of happening (`_names_a_doing`: what is one of its kind is done by or to
     something, `EVENT_PARTICIPANTS`) gives its fillers no plural. Events and things are told apart by the meaning,
     as told happenings are held (`teaching.told_events`), not by the words.

Order: 1 and 2 first. They are data and the reader's use model, and can be measured offline against held-out BECL
senses before anything is taught. Then 3, measured by the in-memory replay's never-taught sentences, K, and
SENSE-COVERAGE-01.

## 5. Limits

- BECL holds 7,050 lemmas. Words outside it rest on their kind, which is right 89% of the time on BECL's own senses.
  It will be less right on words that differ from their kind.
- Generalizing by kind needs the kinds in memory: on main once WordNet is taught, and on the sandbox only for the
  words a run teaches.
- A slot's kinds come from few fillers when few were taught. The Tolerance Principle is generous for small N
  (2 of 4 fillers is enough), so a slot may take a kind broader than English does, until more is read.
- The figures in §2.1 and §2.2 are the papers' own. Those in §2.3 were measured here, on WordNet's taxonomy, not
  memory's.

## References (checked 2026-10-01)

- Suttle, L., Goldberg, A. E. (2011). The partial productivity of constructions as induction. *Linguistics* 49(6):
  https://www.degruyterbrill.com/document/doi/10.1515/ling.2011.035/html
- Barðdal, J. (2008). *Productivity: Evidence from case and argument structure in Icelandic*. John Benjamins:
  https://benjamins.com/catalog/cal.8
- Alishahi, A., Stevenson, S. (2008). A computational model of early argument structure acquisition. *Cognitive
  Science* 32(5): https://onlinelibrary.wiley.com/doi/full/10.1080/03640210801929287
- Perfors, A., Tenenbaum, J. B., Wonnacott, E. (2010). Variability, negative evidence, and the acquisition of verb
  argument constructions. *Journal of Child Language* 37: https://pubmed.ncbi.nlm.nih.gov/20367896/
- Baldwin, T., Bond, F. (2003). Learning the countability of English nouns from corpus data. ACL:
  https://aclanthology.org/P03-1059.pdf
- Baldwin, T., Bond, F. (2003). A plethora of methods for learning English countability. EMNLP:
  https://aclanthology.org/W03-1010.pdf
- Bond, F., Vatikiotis-Bateson, C. (2002). Using an ontology to determine English countability. COLING:
  https://aclanthology.org/C02-1052/
- Kiss, T., Pelletier, F. J., Husić, H., Simunic, R. N., Poppek, J. M. (2016). A sense-based lexicon of count and
  mass expressions: the Bochum English Countability Lexicon. LREC: https://aclanthology.org/L16-1447/ ; data:
  https://github.com/Linguistic-Data-Science-Lab/BECL
- Yang, C. (2016). *The Price of Linguistic Productivity*. MIT Press.
