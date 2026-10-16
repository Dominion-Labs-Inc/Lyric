# Word senses in a cognitive substrate: a general mechanism, not a fix per word

Research note, 2026-10-01. It follows `SENTENCE_AND_WORD_SHAPES.md` (how sentence shapes are learned without a
network) to the next problem: once a word names several things, how the substrate keeps every one of them in play and
takes the one meant, by one mechanism, so a wrong sense is not traced and recoded case by case. What of §4 is built,
and how it measured, is in §7.

## 1. The problem, as measured

The reader reports every meaning a sentence can have; the listener (`derived_reader.meant`) takes one, by what memory
holds (`held`), how it connects to the rest of what is said and to the conversation (`related`), then how often each
word names each thing (`used`). On 2026-10-01 the listener's bar (SENSE-01 K) went from 7/16 to 13/16. Almost every
step was one case traced and patched:

| What went wrong | Where | What it was |
|---|---|---|
| The sense never reached the listener | `_read_pieces` keeps only the readings that supposed least | the computer's mouse, its "mouse" linked in "A ?slot0 is an ?slot1.", read "A mouse is a device." only through a link proposed |
| Same | `apart` (`stood_beside`) | the bird's wing, taught in the "an" twin of a frame, never "stood" where the lessons' words stand |
| Same | `misfits` (`written_against`) | a synonym ("bank" for `depository financial institution`) judged like an irregular form |
| Every reading equally "held" | `listening_evidence` | "a thing is a Y" credited through very general kinds of both sides |
| A wrong word link learned | `_names_within` | "electronic computer" taken apart into a frame word and a filler |
| Concepts renamed at the door | `singularise` | "proboscis" stored as `probosci`; 4,213 WordNet names |

An audit of every word the sandbox holds with two or more senses (`"The <word> is big."`) found 24 of 70 words
offering every sense before these fixes and 46 after. That is 70 words; full WordNet has tens of thousands with
several senses. More cases will come, and each found by hand is a cost paid again and again.

**What the cases share:** a sense was judged by its own history (which frame its link was learned in, which words it
stood beside), where its word should have been judged, and evidence was combined by fixed rules (a strict order, a
hard cut) that one accident could tip.

## 2. What is known

### 2.1 How people do it

- **Every meaning is reached first, then one is taken.** Swinney (1979), with cross-modal priming: hearing "bug"
  primes both the insect and the spying device, even in a clear context; three syllables later only the meaning that
  fits is primed. Later work settled on frequency and context both shaping how strongly each meaning comes up
  (reordered access; Duffy, Morris and Rayner 1988), but no meaning is left out because of how the word arrived.
- **Related senses are not rivals in the way unrelated ones are.** Different senses of one polysemous word prime each
  other, while homonyms (bank of a river, bank for money) compete. One account holds that a polysemous word's standing
  meaning is underspecified, refined only as far as the context needs.

### 2.2 How cognitive architectures do it

- **ACT-R** retrieves from declarative memory by activation: A = B + Σ W·S. B, the base level, is learned from how
  often and how recently a chunk was used (the log odds it will be needed); the sum is activation spread from what is
  in the current goal; a chunk is retrieved only if its activation clears a threshold. Frequency, recency and context
  enter ONE number, on one scale, and "nothing clears the threshold" is an answer.
- **Hirst's Polaroid Words** (1987/1988): each ambiguous word is a small process holding its candidate senses. Senses
  go out by marker passing (spreading activation through the knowledge network), by selectional restrictions, and by
  negotiation with the other words of the sentence. Commitment is delayed, and ambiguity that nothing resolves is kept,
  not forced.

### 2.3 Without a model or hand-tagged text

- **Random walks over WordNet** (Personalized PageRank; Agirre and Soroa 2009; Agirre, López de Lacalle and Soroa
  2014). Senses are nodes, WordNet's relations edges; the walk starts from the other words of the context, and the
  candidate sense the walk visits most wins. No training data. All-words F1 (Table 3, 2014): 59.7 on SensEval-2 and
  57.9 on SensEval-3, against 60.1 and 62.3 for the most frequent sense, and 68.6 and 65.2 for the best supervised
  systems. On coarse-grained senses (SemEval-2007): 80.1. The walk combined with sense frequency does better than
  either; definitions linked to their senses ("disambiguated glosses") help most among the relations.
- **Selectional preferences** (Resnik 1997): how strongly a predicate selects a class of WordNet, learned from which
  things it is said of, with no annotation. Of all the classes a noun belongs to, the one the predicate selects most
  is the sense meant: "red" is said of physical things, so the table that is red is furniture.
- **One sense per discourse, one sense per collocation** (Yarowsky 1995): within a document a word keeps one sense
  (99.8% in his test), and nearby words are reliable clues; from a few seeds, unlabeled text is labeled by
  bootstrapping, past 96% on the words tested.

### 2.4 How fine a sense to choose

WordNet distinguishes more senses than people agree on. Clustering senses, or using WordNet's 26 noun and 15 verb
lexicographer classes (supersenses), raises both agreement and accuracy (the random walk above: 41.7 fine-grained,
80.1 coarse-grained, on SemEval-2007). A 2026 benchmark (Philippov et al., lexEN) puts frontier LLMs at 95.6% and
finds that at fine granularity experts themselves agree only moderately (Fleiss κ 0.537 on hard items); coarsening
raises agreement and model accuracy together. **An LLM's bar is a coarse-sense bar.**

## 3. What the substrate already has

| Mechanism | In Lyric |
|---|---|
| Every meaning reported | the reader (`read`, `read_text`) |
| A listener that chooses or leaves open | `meant`, `heard`, `listening` |
| Knowledge-based evidence | `MemoryAgent.listening_evidence`: kinds walked up the taxonomy (`held`), near kinds and facts between them (`related`) |
| Frequency | SemCor's counts taught as evidence on the word's construction (`learn_usage`); each construction's own uses |
| Context | the conversation's last 24 things talked of (`_talked_of`) |
| Beliefs on every construction and link | the belief system |

What it lacks: grammar pooled per word form; one activation in place of a strict order; a walk over the graph in
place of hand-set "held 2 / held 1 / near kinds"; selectional preferences; a coarse level; a self-check.

## 4. What it means for the substrate (proposed)

1. **Every sense reaches the listener (exhaustive access).** What structure says (which frames the word was linked in,
   what it stood beside, how it is written) is evidence about the WORD FORM, pooled over all its senses. Supposition
   is computed once per form; a sense is never set aside because of where its own link was learned. This removes the
   whole class of cut found on 2026-10-01 (§1, first three rows) instead of patching each one.
2. **One activation decides.** Each candidate sense gets one number, ACT-R's shape: base level (log of its uses:
   WordNet's tagged counts, its own observed uses, recency in the conversation) plus activation spread from the
   context through memory's graph (a short walk from the other words and the things talked of, as Personalized
   PageRank does, replacing the hand-set held/related scores) plus selectional fit (2.). The highest wins if it clears
   the next by a margin; otherwise the choice stays open and the listener asks. No strict order, so no single accident
   (one "held" point) outweighs everything else.
3. **Selectional preferences are learned from memory.** For each relation and predicate ("has_property … red",
   "done_to … eat"), the classes of the things it has been said of, generalized up the taxonomy (Resnik's
   association). Knowledge, not code: "The table is red." (red is said of physical things), "Tom ate the fish."
   (eating is done to food) are decided by what has been read and taught, and grow with it.
4. **One sense per discourse.** A sense taken earlier in a conversation or a document is part of the context for the
   word's next occurrence.
5. **Choose coarse first.** Take the coarse sense (homonym cluster or lexicographer class); go finer only when the
   evidence does. A fine-grained tie inside one coarse sense is understood, not left open.
6. **The substrate checks itself.** Each fact taught is said and read back (SENSE-01 E does this once); each word's
   senses are probed through frames fit for their kind; a sense that never reaches the listener, or a fact that does
   not come back as taught, is recorded as a learning failure with the step that caused it. A standing experiment
   first, then work the substrate does on its own time. A wrong choice found later (a sentence contradicting it)
   moves the belief behind it, as every outcome does.

## 5. Order proposed

1. Pool structure per word form (1.), with the coverage audit extended to every kind of word (noun, plural, verb,
   adjective) and kept as a standing experiment (6.).
2. One activation (2.) with selectional preferences learned from memory (3.), measured on K and the audit.
3. Definitions and examples taught with their meanings: the knowledge 3. needs most (eating is done to food; money is
   kept in a bank), and the relation the random-walk work found most useful.
4. The coarse level (5.) and one sense per discourse (4.).

## 6. Limits

- Knowledge-based methods reach about the most-frequent-sense level on fine-grained benchmarks; they do better coarse.
  K's remaining misses are knowledge (the table, the bank) and reading ("Tom ate the fish."), not choosing.
- A walk over a graph of WordNet's size per sentence has a cost; it is bounded to the senses in play and a few steps,
  and measured before it is relied on.
- The figures in §2 are the cited papers' own; none was re-run here.

## 7. Built (2026-10-01)

1. **Every sense reaches the listener** (§4.1). Not pooled per word form after all: a sense's own history stays
   evidence ("It will snow soon." is the snowing taught there), but no longer a cut. `_read_pieces` keeps every
   reading that says the same words as a best one of another thing; `meant` weighs how each fits (`Reading.supposed`).
   SENSE-COVERAGE-01 checks it for every word with two or more senses.
2. **Definitions linked to their senses** (§4.3's knowledge; Agirre et al.'s most useful relation). The Princeton
   WordNet Gloss Corpus, read from NLTK's data, taught as `defined_with` facts (`WordNetSource._definition_links`):
   the financial bank is defined with money, eating with food. The listener's `related` reads them as it reads any
   fact. A name shared by senses in different parts of speech is defined by the sense its word names most often.
3. **What words are said of** (§4.3, Resnik 1997). Uses, not facts: one memory for each word, relation and side
   (`MemoryAgent.remember_said`), from the Brown corpus's adjective–noun, verb–object and subject–verb pairs
   (`WordNetSource.said_of`: 59,956 pairs, 76,776 uses) and from every sentence learned with its meaning, by sense
   (`learn_patterns`). For the fact a word stands in, how much more likely the thing is given what the fact's other
   word is said of: `ln(P(k|w)/P(k))` over every kind the thing is, averaged, with one use spread as anything is
   (`said_selection`), measured over memory's own taxonomy.
4. **One activation** (§4.2, ACT-R in its rational form). The counted evidence is one number in nats: each
   construction's base level `ln(1 + uses)` plus that strength. No weights: both are log probabilities. Chosen by
   measurement, SENSE-SAID-01, on 12,654 adjective–noun and verb–object pairs of WordNet's hand-tagged definitions:

   | | verb–object | adjective–noun |
   |---|---|---|
   | Most frequent sense | 56.6% | 57.4% |
   | Said of first, frequency on a tie (the first build) | 44.6% | 42.5% |
   | One activation | **58.3%** | **58.8%** |

   Ranked first, what a word is said of lost 13 points against frequency, as Resnik (1997) found (44.3% against
   58.2%); added, it gains about 1.5. What memory knows, the conversation and where a word stands stay before it, in
   that order: memory holds no count that would put them on the same scale, and a weight would be made up.
5. **Coarse senses** (§4.5). Where the evidence ties, things that are one coarse sense in memory (one a near kind of
   the other, or both of one thing: `coarse_senses`) are understood, not left open.
6. **One sense per discourse** (§4.4). A thing talked of before counts in the context of the next word that names
   it.

Order of evidence now: held > related > fit > activation (base level + said of); on a tie, one coarse sense is
understood. Not built: a walk over memory's graph in place of `held`/`related` (§4.2), and the self-check as work the
substrate does on its own time (§4.6).

## References (checked 2026-10-01)

- Swinney, D. (1979). Lexical access during sentence comprehension. *Journal of Verbal Learning and Verbal Behavior*
  18. Summary: https://en.wikipedia.org/wiki/David_Swinney
- Duffy, S., Morris, R., Rayner, K. (1988), reordered access; see the review in *Lexical ambiguity and eye fixations in
  reading*: https://www.sciencedirect.com/science/article/abs/pii/0749596X9290023Q
- Polysemy against homonymy, underspecification: Falkum and Vicente (2015), *Polysemy: current perspectives and
  approaches*: https://philarchive.org/archive/FALPCP
- ACT-R activation, base-level learning, spreading activation, retrieval threshold: Taatgen, Lebiere and Anderson,
  *Modeling paradigms in ACT-R*: https://www.ai.rug.nl/~niels/publications/taatgenLebiereAnderson.pdf
- Hirst, G. (1988). Resolving lexical ambiguity computationally with spreading activation and Polaroid Words:
  https://www.cs.toronto.edu/pub/gh/Hirst-88.pdf
- Agirre, E., Soroa, A. (2009). Personalizing PageRank for word sense disambiguation: https://aclanthology.org/E09-1005.pdf
- Agirre, E., López de Lacalle, O., Soroa, A. (2014). Random walks for knowledge-based word sense disambiguation.
  *Computational Linguistics* 40(1): https://aclanthology.org/J14-1003.pdf ; UKB: http://ixa2.si.ehu.eus/ukb/
- Resnik, P. (1997). Selectional preference and sense disambiguation: https://aclanthology.org/W97-0209.pdf
- Yarowsky, D. (1995). Unsupervised word sense disambiguation rivaling supervised methods:
  https://en.wikipedia.org/wiki/Yarowsky_algorithm
- Princeton WordNet Gloss Corpus (WordNet 3.0 gloss tags, 2008): https://wordnetcode.princeton.edu/glosstag.shtml
- Navigli, R. (2006). Meaningful clustering of senses helps boost word sense disambiguation performance:
  https://aclanthology.org/P06-1014.pdf
- Philippov, V. et al. (2026). English word sense disambiguation in 2026: when the labels become the bottleneck:
  https://arxiv.org/abs/2609.17554
