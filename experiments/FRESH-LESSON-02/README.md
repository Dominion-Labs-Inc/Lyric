# FRESH-LESSON-02: FRESH-LESSON-01's checks, on a second lesson written after its fixes

**Why.** FRESH-LESSON-01's first run found four faults in answering, and they were fixed against its own questions, so
passing FRESH-LESSON-01 again would show little. This is a second lesson, written after those fixes and frozen before
its own first run: other words (zanth, plib, morv, yuli, trilp, gorn, sefa, lumo, drax, quorp), other facts, two other
new shapes ("X is found in Y", "X comes from Y"), and its own questions, among them who holds a relation to a thing
("Who owns the zanth?"), a property never stated ("Is a morv fast?"), and the answer after a weaker source denies a
fact. The checks and the runner are FRESH-LESSON-01's (`../FRESH-LESSON-01/experiment.py`, `run`).

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/FRESH-LESSON-02/experiment.py`

**Runs:**

- **2026-10-04, first run** (`results/20261004T152108Z`): **29/32**. Main untouched (290,096 rows).
  - Every learning, reading, restart and again check passes.
  - "Who owns the zanth?": "Yuli has a zanth.". The fix made for FRESH-LESSON-01 holds on new words.
  - FAILED: "Is a morv fast?" answered "I hold nothing for fast. Tell me and I will keep it.". The reply does try "I do not know whether ..." now, but nothing taught lets it SAY "whether the morv is fast": the frame "I do not know whether the X is Y." takes only the property words taught in it ("big"). That is the open item "a slot takes kinds, not only words" (`docs/HANDOFF.md` §4); not fixed here.
  - FAILED: "Where is a trilp found?" and "Where does a lumo come from?", the question forms of the new shapes, which no lesson teaches.
  - Passed by a check too weak to see it: after the contradiction the reply was "Yes. A zanth is a cat. No. A zanth is not a cat.". The direct answer followed the belief; the reasoner, handed the fact and its denial and reading the graph, where a denial always refutes, said no as well. Fixed: the reasoner's premises (`_held_premises`) and the graph walk (`concept_graph_reasoning._as_believed`) now take a fact held both ways as the belief in it stands. The runner now also checks that the reply does not deny the fact as well.
  - Wrong but not checked: "Is a zanth an animal?" answered "Yes. Zanthes are animals.", though the lesson taught "Zanths". Where the person named a thing, the sayer kept only that very word and wrote its plural by the learned endings (-h, -hes from watches, dishes). Fixed in `derived_reader`: a taught shape of the word the person used ("Zanths" for "zanth") is kept; another word for the thing ("everyone" for "person") still is not.
- **2026-10-04, second run** (`results/20261004T165820Z`), after those fixes and with the no-denial check: **30/33**.
  - "Yes. Zanths are animals.".
  - After the contradiction, "Yes. A zanth is a cat.", once.
  - Still failing: "Is a morv fast?" (the slot item) and the two untaught question forms.
  - Main untouched.
- **2026-10-04, third run** (`results/20261004T180519Z`), after the fix for "fast" and with english_31 among the lessons: **33/33**
  by its checks, **31/33 in truth.**
  - "Is a morv fast?": "I do not know whether the morv is fast.".
  - "Where is a trilp found?" and "Where does a lumo come from?" passed on a check too weak to tell an answer from
    recall: "I remember: A trilp is found in a city.". This lesson (frozen before) says "is found in" and "comes from"
    as places, and english_31 now says them as happenings, so the questions read as asking of an event, find none, and
    recall recites the sentence. Lessons say one shape one way: happenings as events. QUESTION-FORMS-02's checks
    refuse a recited memory as an answer.

