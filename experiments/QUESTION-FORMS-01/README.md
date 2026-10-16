# QUESTION-FORMS-01: questions with "does", "do" and a word at the end, taught and asked of new words

**Why.** FRESH-LESSON-01 to -03 found that a statement shape learned from a lesson does not bring its question, and
that none of the 2,636 sentences of english_01-30 asks "Where does ...?", "Who does ... belong to?" or "Where is ...
kept?". `data/lessons/english_31.json` teaches 14 such questions, each beside the sentence that tells what it asks.

**What it checks.** On the emptied sandbox, the 31 lessons, then facts with new words (`lesson.json`, frozen before
the first run), then questions through the conversation:
- **Shapes english_31 asks about** (lives in, belongs to, is kept in, comes from, sleep in), of new words: checked.
- **Shapes no lesson asks about** (hides in, grows in, rests in): measured, whether a question form taught with some
  verbs carries to another.
- **The main model:** untouched.

**Run** (empties the sandbox first): `./venv_lyric/bin/python3 experiments/QUESTION-FORMS-01/experiment.py`

**Runs:**

- **2026-10-04, first run** (`results/20261004T175021Z`): **9/9**. Main untouched.
  - All 31 lessons were learned and the facts too, none refused.
  - Every question in a shape english_31 asks about, of new words, was read and answered:
    - "A fip lives in a kitchen.";
    - "The plonk belongs to Nella.";
    - "The trel is kept in a bag.";
    - "A snell comes from a city.";
    - "Brabs sleep in boxes.".
  - **Shapes no lesson asks about, 0 of 3:** "Where does a kelt hide?" gave "I understood 'does a kelt hide', but not how 'Where' fits with it.", and the same for grow and rest.
    - The meanings english_31 and the lessons give these verbs leave the verb out: "Tom lives in the city." means only located_in(tom, city). So the question's verb stands for nothing in its meaning, and the reader cannot make it a slot: each verb's question is learned on its own.
    - The 30 lessons write an activity as an event whose kind is the verb ("Where did the dog run?": instance_of(?v0, run), done_by(?v0, dog), moves_to(?v0, ?v1)). There, the verb is a slot.
- **After this run:** with the teammate's decision to hold told happenings as events, english_31 was rewritten to say
  its happenings as events of their verbs' kinds, and this experiment became the runner QUESTION-FORMS-02 uses. The
  run above was with the first english_31, whose happenings dropped the verb.

