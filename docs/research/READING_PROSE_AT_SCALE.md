# Reading prose at scale: what is wrong, and what the research says (2026-10-16)

For the owner. Written after phase 1 of the plan in `docs/HANDOFF.md` §4 moved the prose measure from 4 to 7 of 33
sentences, all three of the new ones misread. The plan fixes one piece of English per step. This note names the
shared cause and what the literature says closes it.

## 1. What is wrong, measured this week

The reader learns whole sentence frames with slots, from sentences paired with their meanings (the Leuven method,
chosen 2026-09-27: holophrase, then item-based constructions). 3,054 lesson sentences made 950 frames. A slot is
filled by a word or a name memory holds. Both failures below come from one missing layer: **nothing between the words
and the frames says which words form a phrase, or what grammatical role a word plays.**

**Composition.** A phrase built from parts has nowhere to go.
- "carbon dioxide and water", "a high-level, general-purpose programming language" and "the green pigment that
  absorbs the light" each need a frame variant never taught.
- Measured read only on main: hyphenated words were not the cause. "Python is a popular, general programming
  language." (a comma between modifiers) and "Python is typed and collected." ("and") fail the same way with no hyphen.
- Every unread prose sentence names a piece of this kind: a question word in front, a pronoun subject, "of", "and",
  a comma list, a relative clause. Phase 1 and phase 2 add these one per step, which is the accretion the goal rules
  out.

**Misreading.** With no grammatical role known, every WordNet sense of every word competes in every place. Read on
main: "a" as the ampere or the angstrom, "It" as information technology, "Berlin" as a limousine, "1889" as an inch,
"The account" as a record history, "hired" as a property of the engineers. Step 4 held three more sentences, and all
three were held as misread.

## 2. What the research says

**Learning from sentence and meaning pairs stays narrow.** The survey of 31 models (Doumen, Beuls & Van Eecke 2024)
finds they cover "specific linguistic phenomena only, such as basic argument structure" on "narrow artificial
datasets, such as Robocup ... GeoQuery ... CLEVR". Broad coverage remains an open challenge. This was already known
when the method was chosen (`SENTENCE_AND_WORD_SHAPES.md` §6: "Nobody has done this for all of English at scale").

**The same family of method scales once constructions match phrases** (Van Eecke & Beuls 2026, CoNLL). Each training
utterance comes with its constituent structure (noun phrase, verb phrase, and so on) and its PropBank frames.
- Three kinds of construction are learned:
  - **frame-evoking:** a lemma and its part of speech ("tell" as a verb);
  - **argument structure:** a pattern of constituents and the roles they fill (`arg0(np) v arg2(np) arg1(np)`),
    independent of the verb;
  - **roleset:** links the first two to a frame.
- Because a role is filled by a constituent, a noun phrase of any length or shape fills it, coordinated or not.
- Scale and results: 154,391 utterances from OntoNotes and the English Web Treebank gave 40,688 constructions.
  On 1,000 held-out open-domain utterances: frame F1 79.96, roleset F1 76.25.
- Structure comes from a trained parser (spaCy with the Berkeley Neural Parser), at learning time and at reading time.
- Released as part of Fluid Construction Grammar (PyFCG, `fcg-propbank`).

**Grammars learned from sentence and logical form pairs** (Kwiatkowski, Zettlemoyer, Goldwater & Steedman 2010).
This is Lyric's lesson format exactly. The method induces a combinatory categorial grammar: each word gets a category
and a meaning, and a few universal combining rules build the sentence's meaning. Coordination is one rule, not one
frame per shape. It was tested on database-question sets in four languages. The survey's caution: such grammars assume
meaning is fully compositional, so idioms need extra work.

**Wide-coverage meaning from structure** (Bos, Boxer). A categorial-grammar parser's derivation is turned into
discourse representation structures with neo-Davidsonian events, the same shape as Lyric's `done_by` / `done_to`.
Coverage was over 95% on newswire, and the method handles coordination and control well.

**Choosing a word's sense.** WordNet's first sense, its most frequent in the SemCor corpus, is the strongest simple
baseline. It scores 55% to 79% depending on the test set and how fine the senses are. Once a word's grammatical role
is known, a determiner or a pronoun never competes as a noun sense.

**Structure without a neural parser.** A grammar read off a treebank, with counts and readable rules, parses news
text at 72 F1. Klein & Manning's (2003) state splits raise that to 86.4 F1 with no lexical statistics.

## 3. What this means for Lyric

- **Keep:**
  - constructions held in memory, their scores in beliefs;
  - the meaning language: events with `done_by` / `done_to`, which is PropBank's `arg0` / `arg1` in other words;
  - the listener;
  - learning from pairs.
- **Add a phrase layer between words and constructions.** Frames are then learned against structure, not word
  strings. "and", commas, "of" phrases and relative clauses become phrase-internal, so they no longer need new
  sentence frames. Grammatical roles also cut most misreadings before the listener weighs senses.
- **Teaching data changes.** Examples need structure and meaning, not plain sentences. For the 50-million-example
  plan, plain sentences meet the same wall at any count.

## 4. Decisions for the owner

1. **Where phrase structure comes from.**
   - **(a) A trained parser, used as a tool that only reports structure,** as the phone recogniser only reports
     sounds. Fastest; it is what the 2026 paper uses. It reverses the 2026-08-31 choice ("word classes teacher-taught
     only, no statistical tagger"), which predates the 2026-10-16 clarification that model-free means no LLM.
   - **(b) Lyric learns phrase structure itself from a treebank,** as readable rules with counts. UD English EWT is
     licensed CC BY-SA 4.0. Expect 72 to 86 F1 on news text; slower to build.
   - **(c) Keep learning whole frames from lessons.** The research has no case of this reaching open text.
2. **Training data with meanings.**
   - OntoNotes and the PropBank English Web Treebank annotations are the corpora the 2026 result used.
   - OntoNotes is distributed by the LDC under its licence; check the terms for commercial use.
   - UD English EWT is CC BY-SA 4.0.
   - The PropBank release's licence is still to check.
3. **Phase 1 step 5 and the phase 2 lessons wait** until decision 1 is made.

## 5. Proposed first measurement (offline, nothing written)

1. Take the 33 prose sentences and the 2,882 lesson sentences, and get structure by the chosen route.
2. Count how many sentences have every meaning role filled by one phrase. That is the ceiling a phrase layer gives
   the reader.
3. Read the same sentences against main's current reader for comparison.

## References

- Doumen, Beuls & Van Eecke (2024). The computational learning of construction grammars: state of the art and
  prospective roadmap. https://arxiv.org/abs/2407.07606
- Van Eecke & Beuls (2026). A method for learning large-scale computational construction grammars from semantically
  annotated corpora. CoNLL 2026, 213–226. https://aclanthology.org/2026.conll-main.13/
- Doumen, Beuls & Van Eecke (2023). Modelling language acquisition through syntactico-semantic pattern finding.
  Findings of EACL. https://aclanthology.org/2023.findings-eacl.99/
- Kwiatkowski, Zettlemoyer, Goldwater & Steedman (2010). Inducing probabilistic CCG grammars from logical form with
  higher-order unification. EMNLP. https://aclanthology.org/D10-1119/
- Bos (2008, 2009). Wide-coverage semantic analysis with Boxer. https://www.let.rug.nl/bos/pubs/Bos2009GSCL.pdf
- Klein & Manning (2003). Accurate unlexicalized parsing. ACL. https://aclanthology.org/P03-1054/
- UD English EWT (CC BY-SA 4.0). https://universaldependencies.org/treebanks/en_ewt/
- Word sense baselines (most frequent sense from SemCor). https://arxiv.org/pdf/2101.02875
