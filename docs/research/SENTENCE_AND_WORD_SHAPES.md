# Sentence and word shapes: what the substrate has, and how shapes can be learned

Research note, 2026-09-26, on sentence and word shapes. It starts from the position that rules are not needed,
memory is the one store, and the job is to plug the system correctly. Nothing here has been built; the baseline measurement is `experiments/SHAPES-BASELINE-01`.

## 1. What a shape is

- A **sentence shape** is a pattern of words with open places, paired with what it means. "This is my ___" says
  the thing being pointed at belongs to the speaker and is a ___.
- A **word shape** is how a word's written form changes with what it means: `shoe`/`shoes` (more than one),
  `paint`/`painted` (already happened), `it is`/`it's` (shortened), `U.S.` (abbreviated), a capital letter at the
  start of a sentence or a name.

Today both kinds are written into the code as English. The question is whether they can be learned and held in
memory instead, and what that takes.

## 2. What the substrate has today

| Part | Where | Written or learned |
|---|---|---|
| 33 patterns: 22 sentence shapes (copular fact, negated fact, subject-verb-object, comparative, modal, quantified, passive, apposition, relative clause, coordination, ditransitive, universal, conditional, yes/no questions, …) and 11 that split or clean a sentence first. Each has English words inside it: `is/are/am`, `a/an/the`, `not`, `all/every/no`, `if/then`, `do/does/did`, `by`, `than`, prepositions, modals | `core/semantics/sentence_reader.py:60-285` and below | written |
| 13 fixed word lists (copulas, determiners, negators, 66 prepositions, 52 pronouns, relatives, quantifiers, modals, auxiliaries, conjunctions, subordinators, question openers). `teaching_sources.py:44` says they moved to memory; they are still here and still used | `core/semantics/sentence_machine.py:68-141` | written, twice |
| The derived reader: learns how to read from 13 sentence–meaning pairs, plus 22 demonstrations of its 8 instructions, by procedure synthesis over instructions it induces. 6 procedures, live (the cached derivation matches today's code). EDU-13/14 measured its limits: it generalizes to new words, not new shapes; one word per slot; search cost grows about 6× per added rule | `core/semantics/derived_reader.py:55, 99` | learned, but its evidence is written in the code |
| What kind of request: a question is `?` or a first word on a 23-word list; a telling is anything the reader reads; a job is everything else | `autonomous_coordinator.py:21988`, list at `:19822` | written |
| What link words mean ("part of", "can", "is a"): 170 phrases | `core/semantics/relation_types.py:184` | written |
| Words: the tokenizer keeps letters only, turns apostrophes into `_`, splits `U.S.` into `u`, `s`, drops the `3` of `3pm` | `sentence_machine.py:150-153` | written |
| Plurals: 34 exceptions, 20 irregulars, 25 "-ics" words, then suffix stripping. Verb forms: strip `-ing`/`-ed`, no irregulars | `core/semantics/lexical_normalization.py:39-123, 268` | written |
| Word kinds from spelling: induced, but not allowed to decide, after it called `valves` and `pumps` verbs (`-s` marks plural nouns and verbs alike) | `core/semantics/class_induction.py:33, 185` | learned, switched off |

Machinery that is **not** English, and is what learning needs:
- **Generalization from examples**: Plotkin's least general generalization, pruned by negatives, with rule states
  CANDIDATE / SUPPORTED / VALIDATED / REFUTED (`core/learning/rule_induction.py:731`). Learned rules are kept in
  `unified.learned_rules` (`core/learning/rule_store.py:314`).
- **Procedure synthesis**: builds a procedure that is right on every example (used by the derived reader).
- **Word kinds in memory**: one memory per (word, kind), with three kinds of evidence: stated, implied by a
  reading, refuted when a reading failed because of it (`MemoryAgent.warm_word_classes`).

**The teaching path already carries the pairs a shape learner needs, and throws them away**
(`core/learning/teaching.py:345-412`). A taught record can carry a sentence and what it means (subject, relation,
object). If the sentence reads, the reading is taught; if not, the stated meaning is. Nothing compares the two, so
no shape is ever learned from the pair, and a reading that disagrees with what the teacher said is never noticed.

## 3. Baseline: the written shapes alone (SHAPES-BASELINE-01, run `20260927T034210Z`)

No memory behind the reader, which is what an empty store gives.

- **Statements read: 9 of 35.** African American English 0/7, slang 0/4, commands 0/3, preschool 2/10 ("This is
  my shoe.", "It is black." and "It's black." do not read).
- **Request kind right: 13 of 45.** Every unread sentence is called a job, so the 3 commands are right by
  default and all 11 African American English and slang statements are wrong. "When it rains, I wear boots." is
  called a question because it opens with `when`.
- **Questions parsed: 4 of 6**, and "What color is the shoe?" is parsed as asking what relates by `color` to
  `is the shoe`.
- **Word shapes:** written forms split into their words 0/7; plurals 9/12 (`boxes`→`boxe`, `buses`→`buse`,
  `news`→`new`); verb bases 7/10 (no `ate`, `made`, `knew`).
- "Red, blue, and green are colors!" reads as `Red is colors` and `green is colors`: `blue` is lost.

## 4. What is known about learning shapes

### 4.1 How children do it

- **Whole phrases and word-specific frames first, general patterns later.** Children's early grammar is built
  around particular words and phrases and becomes abstract by generalizing over them (Tomasello 2003). Young
  children use `a` and `the` with largely different nouns, which points to word-specific frames rather than a
  general determiner category (Pine & Lieven 1997).
- **Word kinds come from where words appear.** Words that stand in the same places belong together (Harris 1954).
  In child-directed speech this works well, better for content words than for function words (Redington, Chater &
  Finch 1998). Mintz (2003): words that appear between the same two frequent words, a frame like `you ___ it`,
  fall into one kind with high accuracy; analysing about 6% of the tokens categorized words that make up about half
  of all tokens. The frame words are the most frequent words, the function words, so a learner can find them by
  counting. They do not have to be told.
- **Repetition shapes what is learned and kept** (Bybee 2006).
- **Where words start and end in speech** is learned from how predictable the next sound is (Saffran, Aslin &
  Newport 1996). In print, spaces mark words; that is taught in kindergarten (Common Core RF.K.1.c).
- **What a word means, when a scene has many candidates,** is learned from what stays paired across situations
  (Yu & Smith 2007). This is the sight half of the sight-and-hearing plan.

### 4.2 Programs that learn sentence shapes without a neural network

**From sentences paired with their meaning:**
- **Doumen, Beuls & Van Eecke (2023)** is the closest match to the substrate. The inventory starts empty. The
  first sentence is stored whole with its meaning. When a later pair differs in one place, in the words and in the
  meaning, the program makes a pattern with a slot ("How many rubber ?X are there?"), plus one entry per
  difference (`cubes`↔cube, `spheres`↔sphere), plus links saying which entries fit which slot. When known entries
  cover part of a sentence, the rest becomes a new entry. Each pattern has a score: 0.5 when made, +0.1 when it
  works, −0.3 for competitors that would also have applied, kept between 0 and 1. On questions about pictures of
  blocks (the CLEVR set) it handled over 90% of new sentences after 500 examples and 99.6% after 2,000. On the
  held-out test set it scored 100% both ways, understanding and producing. The inventory peaked around 230 entries
  and settled at about 101. It was given no segmentation, word list or word kinds; it was given every sentence's
  meaning, and the sentences are a narrow, artificial set.
- **Chang (2008)** learned patterns from annotated child speech (15–24 months) by merging, joining and splitting
  them and keeping the shortest grammar. The scale was small (40, then 200 examples), and it only understands.
- **Zelle & Mooney (1996)** used inductive logic programming, the same family as the substrate's rule inducer, to
  learn a parser from sentences paired with database queries. The learned parser beat the hand-built one on the
  same geography questions.

**From text alone, with no meanings:** ADIOS (Solan et al. 2005), Alignment-Based Learning (van Zaanen 2000:
the parts that differ between two otherwise equal sentences are units that can stand in for each other), U-DOP
(Bod 2009: rules and remembered examples are two ends of one range), and the Chunk-Based Learner (McCauley &
Christiansen 2019: words are grouped into chunks by how strongly neighbouring words predict each other, learned
from child-directed speech one word at a time, and used both to understand and to produce). These find structure but not what it means.

**Memory-based language processing** (Daelemans & van den Bosch 2005) keeps every example and decides a new case
by the most similar stored ones.

**Where the field stands** (the survey by Doumen, Schmalz, Beuls & Van Eecke, 31 models):
- Its target is this note's position: "no grammar rules, system of categories, or other linguistic structures are
  predefined. The model can only rely on general strategies to construct form-meaning mappings, combine them, and
  generalise over them."
- No model yet learns without at least one of these: input already cut into words, letters or sounds; given
  meanings; a given word list; or given word kinds. All of them start from segmented input.
- Learning like this at large scale "remains very much an open challenge."
- Given meanings are "a scaffold" and "cannot be the end point": meaning should in the end come from the
  situation the learner is in.

### 4.3 Word shapes

- **Goldsmith (2001):** a stem together with the set of endings it takes (`paint`: –, -s, -ed, -ing) forms a
  signature, found by keeping the description short. The set of endings separates verbs from nouns where one
  ending cannot. That is the mistake `class_induction` made with `-s`.
- **Albright & Hayes (2003):** patterns are learned by comparing word pairs (`walk`/`walked`). Each is scored as
  hits divided by the words it applies to, and lowered when it rests on few words: at a 75% confidence limit, 5 of
  5 becomes 0.825, while 1,000 of 1,000 stays 0.999. People's judgments of made-up verbs matched these learned, scored patterns. A
  purely look-alike model failed: it "favored implausible responses based on single, highly similar exemplars."
- **Yang (2016), the Tolerance Principle:** a pattern over N words is applied to new words only while its
  exceptions number at most N/ln N (9 words tolerate 4). Below that, words are remembered one by one.
- **Han & Baldwin (2011):** shortened and slang spellings are mapped to words by the company they keep and how
  they are spelled.

### 4.4 Dialect

African American English is a rule-governed system, not a set of errors (Green 2002). Leaving out the copula,
as in "She nice", follows regular conditions (Labov 1969). Standard language tools work worse on African American
English text than on text by white speakers (Blodgett, Green & O'Connor 2016). A reader with shapes written for
one variety cannot read another; a learner that is shown examples can.

## 5. What this means for the substrate

**Rules.** Hand-written English rules are not needed, and the field's own target is none. Learned patterns are
needed. Look-alike memory alone gave wrong answers for new words; patterns learned from memory and scored by how
often they worked did better. So memory holds both the examples and what the substrate learned from them, each
with the confidence it earned. That is how the substrate is meant to learn everything else, applied to language.

**What stays built in, because it is not English:** cutting input into units (every published model starts
there), comparing two examples to find what they share and where they differ (the substrate already has this),
counting and scoring, storing and recalling.

**Meaning has to come from somewhere.** At first the teacher gives it, in the substrate's own terms, which is the
scaffold every working model uses. Later it comes from what the substrate sees and hears. That is the field's end
point and the reason for the sight and hearing plan.

**How it would sit on what exists (a proposal, not built):**
1. A shape is a memory: its words and open places, what it means, its score, and where it came from.
2. The teaching path learns from every sentence–meaning pair. This is the missing step in `teaching.py`.
3. Two pairs are compared with the generalization the substrate already has (`rule_induction.py`).
4. A word's kind comes from the places it fills, which replaces told word kinds and the fixed lists.
5. Word shapes work the same way. Word pairs give scored patterns, a pattern is applied to new words only past
   the tolerance threshold, and exceptions (`feet`, `mice`, `ate`) stay remembered.
6. Reading means finding the shapes that cover a sentence. Speaking means running the same shapes the other way,
   which replaces the fixed phrases the speaking side uses now.
7. A reading that disagrees with what the teacher said counts against the shape that produced it.

**What to teach, in order.** The kindergarten standards give the spine. RF.K.1 covers print: upper- and lowercase
letters, words separated by spaces, reading left to right. L.K.1 covers plurals with /s/ and /es/, the question
words, the common prepositions, and complete sentences. Later grades follow grade by grade. Child-speech corpora
(CHILDES) are licensed CC BY-NC-SA 3.0, and TalkBank says this "precludes the incorporation of the data in
commercial products". They can be used to measure, not to teach the product substrate.

## 6. Limits

- Nobody has done this for all of English at scale. This is research, not assembly.
- The substrate's form for meaning, subject–relation–object, is too thin for the first lesson. "This is my shoe."
  points at a thing and says the speaker owns it. Questions ask, commands ask for something done, and tense places
  events in time. Before a shape can be learned for those sentences, what it means needs a form the store can
  hold. This is the largest open design question.
- The derived reader's search grew about 6× per rule. Comparing pairs one at a time is cheaper, but an inventory
  can grow before it settles (230 down to 101 on CLEVR).

## 7. Decisions

1. **Where learned shapes live:** decided 2026-09-27: patterns in memory, their scores in beliefs, their meanings in
   the domain system (§7b).
2. **What the teacher gives as meaning at first:** decided: facts in the domain system's terms. Still open: how
   it holds pointing, what the speaker wants, and events with their participants (§7b).
3. **Child-speech corpora:** for measurement only.

## 7a. The Leuven method, part by part, against the code (checked 2026-09-27)

The method chosen (Doumen, Beuls & Van Eecke 2023; extended in *Royal Society Open Science* 11:231998,
2024). How it works in the extended paper:
- **Form** is the utterance itself, with open places between pieces of text ("What is the ?X block made of?").
  The learner has no notion of "word".
- **Meaning** is a set of predicates that share variables.
- A slot in the form is coupled to a variable in the meaning. A filler fits a slot when the network of slot–filler
  links connects them. When several combinations apply, the one with the highest average score wins.
- The authors' own limits: the intended meaning is given, the data is synthetic, and learning from failure happens
  only when understanding, not when speaking.

| The method needs | What the substrate has | State |
|---|---|---|
| A store for patterns that starts empty and is wiped with everything else | Memory holds structured, tagged memories, and a view is warmed from them at the events that change them. The word-kind view is a working example: `learn_word_classes` writes (`unified_learning_system.py:3195`), `warm_word_classes` reads (`memory_agent.py:2815`) | have |
| A score per pattern that moves with use | A memory's `confidence_score` can be updated (`memory_agent.py:3225`, a protected field); beliefs move with evidence; learned rules carry states | have the pieces; the scoring rule itself (+ for use, − for competitors) is small and missing |
| Meaning as predicates that share variables | `Fact(predicate, args)` with `?X` variables (`rule_induction.py:118`) | have |
| Each sentence arrives with its meaning | The teaching path carries a sentence and ONE subject–relation–object | partly: the meaning has to become a set of facts |
| Matching a pattern's meaning to a meaning (speaking) and its form to a sentence (reading) | `unify`, `match_body`, `apply_substitution` (`core/reasoning/unification.py`) | have the matching step. The engine that combines patterns (fill slots, follow the slot–filler links, pick the best-scored combination) is missing, and it is the largest part to build |
| Finding what two examples share and where they differ | Plotkin's generalizer, whose shared table records each difference (`rule_induction.py:603-716`). It is built for rules (before → action → after), not for a form paired with a meaning | partly: the core step exists. A version for form–meaning pairs that also returns the differences, and pairs the difference in the words with the difference in the meaning, is missing |
| The four learning steps: store whole; generalize into a slot pattern plus fillers; learn the uncovered rest of a partly understood sentence; add a missing slot–filler link | none | missing |
| Slot–filler links (the word kinds that emerge) | The concept graph can hold them as edges | have the store; the links come from the learning steps |
| Teaching calls the learner on every pair | `teaching.py:345-412` teaches the reading or the stated meaning, never compares | missing (the first plug) |
| Reading and speaking go through the learned patterns | The conversation uses the written patterns and fixed lists; speaking uses fixed phrases | missing (the second plug). The written patterns, fixed lists and phrases then go |
| The text as written, nothing lost | The tokenizer drops the 3 of `3pm`, turns `'` into `_` and splits `U.S.` (`sentence_machine.py:150`) | small fix, or work on the text itself as the paper does |

**Verdict.** The foundation is there: the store, the fact language, matching, the generalizer's core step, the
graph and scores. The method itself is not: the engine that reads and speaks by combining patterns, and the four
learning steps, have to be built on that foundation, and the teaching input needs meanings written as facts.

**The reference implementation** is open source: Babel/FCG in Common Lisp, Apache 2.0
(https://gitlab.ai.vub.ac.be/ehai/babel). It can be read for the exact steps. PyFCG (Van Eecke & Beuls 2025) is a
Python wrapper that launches that Lisp program as a background process and talks to it over HTTP. Plugging it in
would put a second language system beside the substrate, so the method is built in the substrate on its own
memory, matching and generalizer.

## 7b. Which system owns each part (decided 2026-09-27)

A place to store patterns that starts empty is memory; a score for each pattern that changes with use is beliefs;
meaning written as linked facts is the domain system. Checked against the code, all three hold. The concept layer describes itself (`core/domain/concept_ingestion.py:6-10`) as "what things, kinds of
things, properties and relationships" the substrate can represent, distinct from memory ("what happened") and
beliefs ("what is currently thought true"). Nothing new is stored anywhere else.

| Part | Owner | How it fits | What to watch |
|---|---|---|---|
| Patterns and word entries | **Memory** | tagged, structured memories with a view warmed from them, as word kinds already are | — |
| A pattern's score | **Beliefs** | one belief per pattern, naming the pattern's memory. `observe_claim` (`bayesian_uncertainty.py:458`) records each use as an observation for it, or against it for a failure or a competitor that lost. The same observation is never counted twice, and the update is the substrate's own odds kernel with decay | This is the first place outcomes must move beliefs (a known defect), so every use has to name the pattern's memory. The decay must not wear down patterns that are rare but right |
| What a sentence means | **Domain system** | facts over its concepts and its relation kinds (37 then; 39 since `done_by` / `done_to` were added) (`relation_types.SemanticRelation`). Most of the first lesson fits: "This is my shoe." → `instance_of(?x, shoe)`, `owned_by(?x, speaker)`; "It is black." → `has_property(?x, black)`; "My shoe … has laces" → `has_part(?x, ?l)`, `instance_of(?l, lace)` | English itself (its patterns and word entries) becomes a domain, measured like any subject |

**What the domain system cannot hold yet, and the first lesson needs:**
1. **Who and what the words point to**: `I`/`you` (the speaker and the listener, whom the conversation already
   knows), `this`/`here` (the thing shown), and `it`/`they` (the thing just talked about, which the conversation
   already tracks).
2. **What the speaker wants**: to tell, to ask, or to have something done. The same facts said as a statement, a
   question or a command mean different things.
3. **Who did what to what**: "Tie your shoe." and "I paint my shoe." are events with a doer and a thing done to.
   None of the 37 relation kinds links an event to its participants.

**Every place that changes** is mapped, with evidence and a build order, in `docs/research/SHAPES_CHANGE_MAP.md`; re-check it with `scripts/language_map.py`.

## 8. Next experiment (proposed, not built)

**SHAPES-LEARN-01**, on an empty store, with no English written in:
1. Teach kindergarten-level sentence–meaning pairs ("This is my shoe." / "This is my hat." / "That is your
   sock." …).
2. Measure new sentences that use known shapes with new words (vocabulary).
3. Measure new combinations of known shapes (syntax).
4. Measure meaning → sentence (speaking).
5. Measure refusals of shapes never seen.
6. Measure which word kinds appear from the places words fill, with none told.
7. Compare against SHAPES-BASELINE-01.

## References (checked 2026-09-26)

- Albright, A. & Hayes, B. (2003). Rules vs. analogy in English past tenses: a computational/experimental study.
  *Cognition* 90, 119–161. https://brucehayes.org/papers/AlbrightHayes2003RulesVsAnalogy.pdf
- Blodgett, S. L., Green, L. & O'Connor, B. (2016). Demographic dialectal variation in social media: a case study
  of African-American English. *EMNLP 2016*, 1119–1130. https://aclanthology.org/D16-1120/
- Bod, R. (2009). From exemplar to grammar: a probabilistic analogy-based model of language learning.
  *Cognitive Science* 33(5), 752–793. https://onlinelibrary.wiley.com/doi/10.1111/j.1551-6709.2009.01031.x
- Bybee, J. (2006). From usage to grammar: the mind's response to repetition. *Language* 82(4), 711–733.
  https://www.unm.edu/~jbybee/downloads/Bybee2006FromUsage.pdf
- Chang, N. (2008). *Constructing grammar: a computational model of the emergence of early constructions.* PhD
  thesis, UC Berkeley. As described in Doumen et al. (survey), §3.2.
- Common Core State Standards, English Language Arts, Kindergarten: RF.K.1, L.K.1.
  https://www.thecorestandards.org/ELA-Literacy/RF/K/ · https://learninglab.si.edu/standards/CCSS.ELA-Literacy.L.K.1/1537
- Daelemans, W. & van den Bosch, A. (2005). *Memory-Based Language Processing.* Cambridge University Press.
  https://aclanthology.org/J06-4007.pdf
- Doumen, J., Beuls, K. & Van Eecke, P. (2023). Modelling language acquisition through syntactico-semantic
  pattern finding. *Findings of EACL 2023*, 1347–1357. https://aclanthology.org/2023.findings-eacl.99/
- Doumen, J., Beuls, K. & Van Eecke, P. (2024). Modelling constructivist language acquisition through
  syntactico-semantic pattern finding. *Royal Society Open Science* 11, 231998. https://doi.org/10.1098/rsos.231998
- Van Eecke, P. & Beuls, K. (2025). PyFCG: Fluid Construction Grammar in Python. https://arxiv.org/abs/2505.12920
- Babel toolkit (FCG reference implementation, Common Lisp, Apache 2.0). https://gitlab.ai.vub.ac.be/ehai/babel
- Doumen, J., Schmalz, V. J., Beuls, K. & Van Eecke, P. The computational learning of construction grammars:
  state of the art and prospective roadmap. *Constructions and Frames* (accepted 2024). https://arxiv.org/abs/2407.07606
- Goldsmith, J. (2001). Unsupervised learning of the morphology of a natural language. *Computational
  Linguistics* 27(2), 153–198. https://aclanthology.org/J01-2001/
- Green, L. J. (2002). *African American English: A Linguistic Introduction.* Cambridge University Press.
- Han, B. & Baldwin, T. (2011). Lexical normalisation of short text messages: makn sens a #twitter. *ACL 2011*,
  368–378. https://aclanthology.org/P11-1038/
- Harris, Z. S. (1954). Distributional structure. *Word* 10(2–3), 146–162.
- Labov, W. (1969). Contraction, deletion, and inherent variability of the English copula. *Language* 45,
  715–762. https://languagelog.ldc.upenn.edu/myl/Labov1969.pdf
- McCauley, S. M. & Christiansen, M. H. (2019). Language learning as language use: a cross-linguistic model of
  child language development. *Psychological Review* 126(1). https://pubmed.ncbi.nlm.nih.gov/30604987/
- MacWhinney, B. (2000). *The CHILDES Project.* Licence terms: https://talkbank.org/0share/rules.html
- Mintz, T. H. (2003). Frequent frames as a cue for grammatical categories in child directed speech.
  *Cognition* 90(1), 91–117. https://pubmed.ncbi.nlm.nih.gov/14597271/
- Pine, J. M. & Lieven, E. V. M. (1997). Slot and frame patterns and the development of the determiner category.
  *Applied Psycholinguistics* 18, 123–138.
- Plotkin, G. D. (1970). A note on inductive generalization. *Machine Intelligence* 5, 153–163.
- Redington, M., Chater, N. & Finch, S. (1998). Distributional information: a powerful cue for acquiring
  syntactic categories. *Cognitive Science* 22, 435–469.
- Saffran, J. R., Aslin, R. N. & Newport, E. L. (1996). Statistical learning by 8-month-old infants. *Science*
  274, 1926–1928. https://www.science.org/doi/10.1126/science.274.5294.1926
- Solan, Z., Horn, D., Ruppin, E. & Edelman, S. (2005). Unsupervised learning of natural languages. *PNAS*
  102(33), 11629–11634. https://www.pnas.org/doi/10.1073/pnas.0409746102
- Tomasello, M. (2003). *Constructing a Language: A Usage-Based Theory of Language Acquisition.* Harvard
  University Press.
- van Zaanen, M. (2000). ABL: Alignment-Based Learning. *COLING 2000.* https://aclanthology.org/C00-2139/
- Yang, C. (2016). *The Price of Linguistic Productivity.* MIT Press.
- Yu, C. & Smith, L. B. (2007). Rapid word learning under uncertainty via cross-situational statistics.
  *Psychological Science* 18(5), 414–420.
- Zelle, J. M. & Mooney, R. J. (1996). Learning to parse database queries using inductive logic programming.
  *AAAI-96*, 1050–1055. https://cdn.aaai.org/AAAI/1996/AAAI96-156.pdf
