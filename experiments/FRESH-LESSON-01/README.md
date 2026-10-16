# FRESH-LESSON-01: what Lyric learns from a lesson no experiment has tested

**Why.** SENSE-01, COMPREHENSION-01 and SYSTEM-LEARNING-01 have been run and fixed against since the start, so
passing them says little about whether learning, the sentence machine and understanding work as intended. This
teaches one new lesson, written and frozen before the first run (`lesson.json`), and checks what Lyric does with it.

**The lesson.** 27 sentences stated as facts:
- the background facts the questions need (birds are animals and can fly, fish can swim, a girl is a person);
- ten words neither WordNet nor the 30 lessons have: wug, dax, blicket, fep, nella, snorf, toma, pell, glim, vora;
- two shapes of sentence the 30 lessons never use, three sentences each: "X lives in Y", "X belongs to Y".

The 30 lessons are taught first, on an emptied sandbox; they teach how English says things and state no facts.
`contradiction.json` is one weaker source saying "A wug is not a bird.".

**What it checks** (every expected meaning and answer is written in `experiment.py` before the run):

| | |
|---|---|
| A. Learning | none refused; every fact in the concept graph; every true fact a belief above even; each new word a memory found by meaning, held in the lesson's domain, classed a noun |
| B. Reading | 8 never-taught sentences in shapes the lessons teach, read as written; the two new shapes not read before the lesson, and read in 3 sentences each the lesson never had |
| C. Meaning | 13 questions through the conversation: kinds, abilities passed down from a kind, places, materials, owners, nothing made up, and two question shapes nobody taught |
| D. Restart | a process started afterwards reads every sentence the same way, from memory alone |
| E. Again | the lesson taught twice learns nothing new and moves no belief |
| F. Told otherwise | the contradiction moves the belief in "wug isa bird" down |
| G | the main model is untouched |

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/FRESH-LESSON-01/experiment.py`

**Runs:**

- **2026-10-04, first run** (`work/run.log`). It stopped at the last step, so it wrote no run record and made no main check of its own. Main was counted afterwards: 290,096 rows, as before.
  - **Before the lesson:** the 30 lessons were learned with none refused, and the two new shapes did not read right.
  - **A. Learning.**
    - The lesson was learned, none refused.
    - All 25 facts it states as true moved a belief above even.
    - Each new word is a memory found by meaning, held in the lesson's domain, and classed a noun.
    - "In the concept graph" FAILED, 15 of 26, but on this experiment's query, not on Lyric: the graph writes those 11 relations with spaces ("capable of", "located in"), and the query asked for "capable_of". All 11 are there.
    - The graph holds some relations under both spellings (`has_property` and `has property`); still to look at.
  - **B. Reading.**
    - 8 of 8 never-taught sentences were read as written.
    - Both new shapes ("lives in", "belongs to"), learned from three sentences each, read 3 of 3 sentences the lesson never had.
  - **C. Meaning: 10 of 13.**
    - Right:
      - a wug is a bird, not a fish, and an animal;
      - a wug can fly, and a dax can swim, both from their kinds;
      - the blicket is in the box and made of wood;
      - Nella is a person.
    - "Is a blicket big?" made nothing up, but answered "I hold nothing for big. Tell me and I will keep it." instead of "I do not know whether the blicket is big."
    - "Who owns the wug?" FAILED: it was read right, but the answer engine found nothing, though "nella owns wug" is in the graph; it said "I remember: A wug is a bird."
    - "Where does a snorf live?" and "Who does the blicket belong to?" FAILED: a question form of a shape learned only as a statement is not read ("I understood 'does a snorf live', but not how 'Where' fits with it.").
  - **D. Restart:** a new process read all 14 sentences the same way.
  - **E. Again:** nothing learned anew, and the belief held at 0.99696.
  - **F. Told otherwise:** the belief in "wug isa bird" moved from 0.997 to 0.970.
    - Asking "Is a wug a bird?" again then CRASHED the reply (`'str' object has no attribute 'get'`). `Conversation.say` used `named` both for the names it speaks with and for the names one answer lists, so a question with two answers broke. Fixed (`listed`).
    - Asked again after the fix, it answers "No. A wug is not a bird." while the belief stands at 0.97 for yes: the reply follows the first answer, not the belief.
- **2026-10-04, second run** (`results/20261004T153806Z`), after the fixes below: **29/31**. Every check passes but the two question forms of the new shapes, which no lesson teaches. Main untouched (290,096 rows).
  - The graph check now passes 26 of 26. The query now compares relations as the graph writes them.
  - "Who owns the wug?": "Nella has a wug.".
  - "Is a blicket big?": "I do not know whether the blicket is big.".
  - Asked again after the contradiction, the reply still read "Yes. A wug is a bird. No. A wug is not a bird." (the check then only asked that it start with yes). Fixed after this run; see FRESH-LESSON-02.

**The fixes the first run led to** (in `core/agents/autonomous/autonomous_coordinator.py` unless said):
- `Conversation.say`: the names one answer lists have their own variable (`listed`), so a question with two answers no longer breaks the reply.
- `Conversation.asked`: a question asking WHO or WHAT holds a relation to a named thing ("who owns the wug?", `owns(?x, wug)`) is answered from the facts that name it as their object (`incoming`). Before, a question whose unknown was the subject was skipped, and the reasoner, handed "nella owns wug" as a premise, answered "By analogy with '~wug_bird' ..." and marked it verified; the grounding check refused that, so nothing was answered.
- `Conversation.asked`: where a fact and its denial are both held, the belief in the fact decides which answers.
- The not-known reply: a question about a thing memory holds is answered "I do not know whether ..." even where a word in it names no held concept ("big").

**Found here, fixed the same day** (`docs/research/LAB_NOTEBOOK.md`, 2026-10-04 (1)):
- The reasoner's analogical route marked an empty analogy `verified`. Now only a kind of reasoning that yields facts
  verifies (`neural_bridge._FACT_YIELDING_KINDS`), and induction and analogy work over the premises' structure.
- The graph held some relations under two spellings (`has_property`, `has property`). `memory_agent.link_concepts`
  writes every relation one way.
- "Who owns the car?", with nothing held of cars, said "I'll run a more targeted search". Both replies now state the
  gap and promise nothing.

**The runner, after FRESH-LESSON-03's second run:**
- It teaches the 30 lessons this lesson and the next two were frozen with (`FROZEN_WITH`, english_01-30). It had
  taught every lesson file, english_31 among them, which says "is kept in" and "sleeps in" as happenings where
  FRESH-LESSON-03 says them as where a thing is.
- A memory recited ("I remember: ...") is no answer (`answered`).

