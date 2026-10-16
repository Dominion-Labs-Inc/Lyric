# FIFTY-01 — what Lyric overcomes for one person, it does again at once, for them and for anyone

**Finding (2026-10-07): 16/16** (`results/20261007T175344Z`).
- The first task of a shape that worked was lifted at once into the world's method, `WRITE_FILE(?V0, Ftrue, ?V1)`.
  Nothing of Ana's is in it.
- Once she overcame a failure, the method kept the fix.
- Her next job and Ben's were each given the fix before any act. Each was recognised as the world's method and
  waited for its person's go-ahead, and neither met the failure.
- Her own earlier work was recalled for her. Nothing of hers was recalled for him.

The rule is `docs/research/SEPARATION_MAP.md` §11.4: "from the first checked success the method is a candidate
everyone's work can use, so the second of 50 users does not relearn it."

**What was wrong.** Memory lifted a method only when a second task of the same shape arrived, from a different
pursuit (`MemoryAgent._lift`: the first waited, then the two were generalized). So what Lyric overcame for one
person was nothing anyone's work could use until it happened again. The second person met the failure again, and
only then did the method form, from both.

**What was built.**
- **The lift from the first task that worked.** A task whose outcome the credit gate counts, and that worked, is
  lifted at once into the world's method (`lift.lift_one`). It keeps as constants only what is no one's particular
  (`MemoryAgent._no_ones`):
  - its tools' own words: a truth value, or a value the tool declares the argument takes (`lift.vocabulary`, read from
    the tool registry);
  - what the world holds a thing under.

  Every other value (her file, her text) is a variable, so nothing of the person is in it.
- **Tasks of the shape before then.** Those that did not work, or whose outcome did not count, wait. When the method
  forms, each that is an instance of it is a witness of it.
- **Later tasks.** A task that worked widens the method; a failure that is not an instance says nothing of it.
- **A person's own method** forms beside the world's when two of their tasks share something only they supplied
  (the residue test, kept).
- **The fix.** What a task changed to overcome a failure (`causal_rules`) is kept on the method as `fixes`, where
  the value is no one's.
- **Using it before acting.** `Capabilities.known_fix` gives a plan the fix before its first attempt
  (`_execute_declared_tools`), when the fix makes the plan an instance of the method. A retry stays the retry's own.
- **Recall serves the task's person.** `_recall_similar_task_experience` searched with no actor, so every person's
  task recalled only Lyric's own experience. It now recalls their own, their organizations' and Lyric's, never
  another person's.

**The checks, written before the run.**

| | |
|---|---|
| **A** | Ana's first note into a new folder worked. The first task of its shape that worked is lifted at once into a world method, held by no person, with her file and text as variables. |
| **B** | Her second, into another new folder with create_dirs false, failed, was retried with create_dirs true, and worked. It is an instance of the method, the method keeps the fix, nothing of hers is in it, and both of hers are counted outcomes. |
| **C** | Her third, asked through the front door the same way. Before any act its plan is given the fix, it is recognised as the world's method, and its act waits for her go-ahead with nothing run. Her own earlier work is recalled for her. |
| **D** | Ben's, the same way. Before any act his plan is given the fix from the world's method, and its act waits for his go-ahead: he never met the failure. Nothing of hers is recalled for him. |
| **E** | A plan of another shape, and a plan that already has the fix, are given nothing. |

**What is recorded and what is real.**
- **Recorded (A and B).** Ana's two tasks go through the coordinator's own recorder (`_store_task_outcome_meta_memory`),
  with the outcomes written by the run, as a task's conclusion records them. The lift, the fix and the beliefs are
  the substrate's own.
- **Why they are recorded.** A person's declared write has no account under the constitution's Law 2 today: no proved
  route, no experiment, no plan step. The first run sent her writes through the front door and Law 2 refused each
  one: "write_file would modify with no account of why".
- **Real (C and D).** These are front-door jobs run by the real queue up to the first act, which waits for the person
  (supervised until the capability is unlocked for them). The run then stops them. Whether the act runs once they say
  yes is the constitution's question, not this check's.
- **What would make the person's side real.** The constitution judging the substrate's intention in a request it
  took on, instead of only a planner's route. In the owner's order that comes after learning from experience and
  reasoning to a belief.

## Run

```
./venv_lyric/bin/python3 experiments/FIFTY-01/experiment.py
```

On the sandbox. Every name carries the run's nonce, and everything the run made is snapshotted
(`data/snapshots/fifty01_*`) and removed:
- the people's memories, pool items, beliefs, messages and jobs;
- the method and its belief.

Each run writes `results/<UTC timestamp>.json` with a `.md` beside it.
