# What Lyric's meaning language can say, and what it cannot yet (2026-10-17)

Asked: are PropBank's roles all said in the meaning language, are other labels, links or kinds missing, does Lyric
read and understand numbers, equations and poems, and does it know words that sound alike or are spelled alike. Each
answer below is measured or read from the code, the store or the data, and says which.

## 1. PropBank's roles: all mapped, four gaps named

`core/semantics/propbank_roles.py` maps every label PropBank's annotations of the English Web Treebank use, every
function tag and VerbNet role of a numbered argument, and every word that begins a modifier whose kind the label
leaves open. `experiments/PROPBANK-01` measures it on all 16,579 annotated sentences (100,297 arguments), with the
words from UD English EWT (`results/20261017T135037Z.md`):

| | Arguments |
|---|---|
| said in a link kind the meaning language has (53 kinds), by a rule its words settle, or as nothing | **98.51%** |
| a named gap, to decide | 1.46% |
| unmapped: words PropBank's own annotation labels wrongly (the modal "i", "most", "cold") | 0.03% (33) |

The four gaps, each with what it would take:

| Gap | Arguments | What it holds | Smallest change |
|---|---|---|---|
| possible | 551 | "might", "may", "maybe", "probably", "perhaps" | a grammar term, as `allowed` and `hypothetical` are (`has_property` of the happening) |
| necessary | 455 + 245 "have to" | "must", "should", "ought", "have to" | a grammar term, likewise |
| between sentences | 390 | "but", "however", "so", "therefore", "then", "or" | a link between what two sentences tell: contrast, result, sequence, alternative. A meaning is one sentence's, so this is a layer above it |
| felt | 64 | "wow", "ugh", "lol", "oops" | what the speaker feels as they speak; the acts are tell, ask and request |

The lessons' own conventions decided the rest: "can" `capable_of`, "would" `hypothetical`, "may I" `allowed`, "on"
`located_at`, "in" `located_in`, "with a key" `done_with`, "has a bike" `owns`, "needs" `requires`; "please" a
request; "hello", "thanks", "sorry" a greeting, a thanking, an apology of the speaker's to the listener; a name
addressed ("Richard, ...") the listener `named`; "with Kim" (a co-agent) `done_by` Kim too; a price `has_measure`.
WordNet names 99.8% of the happenings PropBank's predicates name.

## 2. Beyond PropBank: AMR's list as a check

AMR's guidelines (`amrisi/amr-guidelines`, `amr.md`) were written to cover the meaning of English sentences, so its
relations are a checklist for the meaning language. Against Lyric's link kinds:

| AMR relation | Lyric | |
|---|---|---|
| time, duration, location, source, destination, direction, path | `during`, `lasts_for`, `located_*`, `moves_*` | held |
| cause, purpose, condition, concession | `caused_by`, `has_purpose`, the condition mark, `unexpected` | held |
| instrument, medium ("by phone"), manner, beneficiary, accompanier | `done_with`, `has_property`, `done_for`, `done_by` | held |
| topic, part, consist-of, subset, subevent | `about`, `part_of`/`has_part`, `made_of`, `member_of`, `part_of` | held |
| quant, ord, degree, extent, value, unit, age | `has_count`, `has_rank`, `has_degree`, `has_measure`, `equals` | held |
| polarity, mode (imperative, interrogative), polite, name | not so, the acts request and ask, "please", `named` | held |
| comparison, superlative | `has_degree` + `exceeds`, `greatest_of` | held |
| dates and times | read as literals (`literals`) | held |
| **poss of a relation between people**: "his mother", "the company's president" | none: only `owns`/`owned_by`, which says a person owns their mother | **gap** |
| **rate**: "$5 per hour", "three times a week" | `has_measure` holds one value, not one per another | **gap** |
| **frequency** beyond the lessons' `often` and `usually`: "always", "sometimes", "rarely" | the same kind (`has_property` of the happening), with terms not yet taught | terms to add |
| mode expressive ("Wow!") | none | the gap `felt` above |

## 3. Numbers and mathematics: read, and computed

Read from the code and the store:
- **Numbers**: numerals and number words (the lessons teach "Thirty-five is a number.", "two hundred and six",
  "Five and a quarter"), counts, ranks and fractions, each in the meaning language's number kinds (`has_count`,
  `has_rank`, `has_addend`, `has_factor`, `has_dividend`, ...); what kind a number is is decided by arithmetic.
- **Arithmetic in words**: "What is ten minus four?" (main holds 105 taught patterns with "minus").
- **Written mathematics** (`core/reasoning/arithmetic_reading.py`): any formula as mathematics writes it, numbers of
  any size, letters for unknowns, + - × ÷ ^, brackets, |x|, √, n!, n%, sin, log, ln, sqrt, d/dx, ∫ ... dx, lim, and
  = ≠ < > ≤ ≥, read by notation's rules into a tree, never evaluated as code.
- **Computing**: `core/tools/symbolic_math_faculty.py` (SymPy) works out what was read; linear equations are solved
  by Z3 (`core/reasoning/constraint_solver.py`); "Solve 2y + 1 = 9 for y." is taught (243 patterns on main).
- **Measured weakness** (STRUCTURE-02): the structure reader parses numbers written in words apart (47 lesson
  sentences: "Thirty-five" as three words, "Thirty" a name) and does not take a formula as one thing (6).

## 4. Poems: not read as poems

Nothing in the code reads what makes a poem one: no rhyme, metre, stress or line, and no figurative meaning (a
metaphor is read as said; an idiom only where it was taught whole, as a holophrase). A poem's sentences are read as
any sentences are. Understanding a poem needs the sounds (§5), its lines, and meaning beyond the said.

## 5. Sounds and spellings: on hearing only, and main holds no pronunciations

- **How words are said**: `PronunciationSource` reads the CMU Pronouncing Dictionary (123,455 words, every way of
  saying each, stress marked) and `learn_pronunciations` teaches it as memory. **Main holds none**: 0 memories tagged
  `pronunciation` (counted through the gateway, 2026-10-17). It was never taught to main.
- **Words that sound alike, while hearing**: the ear (`core/perception/speech.py`) hands words that sound alike on
  together ("to", "two", "too"), for the listener to choose by meaning. That is perception, not knowledge: nothing
  holds that two words sound alike, so it cannot be asked ("Do 'their' and 'there' sound the same?") or reasoned
  over.
- **Spelled alike, said otherwise** ("lead" the metal and "lead" the verb): the dictionary holds both ways of saying
  "lead", but nothing ties a way of saying to a sense.
- **No link kinds** for sounding like, rhyming, being spelled like, or a word's syllables and stress.
- Lyric learns how words change shape (`PatternInventory.names_of_shape`: "tables" from `table`), which is spelling
  within one word, not a relation between words.

## 6. Decisions for the owner

1. The grammar terms `possible` and `necessary`, as `allowed` and `hypothetical` are.
2. A link between what two sentences tell (contrast, result, sequence, alternative): a layer above one sentence's
   meaning.
3. What the speaker feels (`felt`).
4. Relations between people: kin ("his mother") and roles ("the company's president").
5. Rates ("per hour", "a week"), and the frequency terms past `often` and `usually`.
6. Sounds and spellings: teach the pronouncing dictionary to main, and say what sounds alike, rhymes, or is spelled
   alike as knowledge (kinds of their own, or worked out from the pronunciations when asked).
