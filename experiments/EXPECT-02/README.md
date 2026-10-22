# EXPECT-02 — what Lyric expects of a person's world, at a powered scale, beside systems built to notice what did not happen

**Finding (2026-10-22, runs 3 to 6 pooled: four full runs of 5 seeds with every learning fix in, 20 seeds, 180
worlds).** Watching offices another person worked, Lyric answered **0.94** of the times a habit was not kept (763 of
809, 95% interval 0.93 to 0.96). The three conventional systems answered 0.97 to 1.0. Each of them was wrong
somewhere Lyric was not:

| Pooled, runs 3-6 | Lyric | Engineered | Mined | Windowed |
|---|---|---|---|---|
| a habit not kept: **answered** | **763/809 (0.94)** | 809/809 | 797/809 | 783/809 |
| a file filed later than any before it: answered | **40/9,463 (0.4%)** | 119 (1.3%) | 729 (7.7%) | 768 (8.1%) |
| a txt she never handles: answered | **0/1,221** | 0 | 375 (31%) | 540 (44%) |
| a step kept every other time: answered | 45/585 (7.7%) | 585 (100%) | 17 (2.9%) | 20 (3.4%) |
| a step kept three times in four: answered | 316/322 | 322 | 144 | 158 |
| her habit changed: her files filed elsewhere, **acted against** | **0/2,400** | 2,400 | 771 (32%) | 724 (30%) |

- **Acting.** In Delegate, 139 of 139 goals put the file right, and she was told how each ended. In Assist, her
  "Yes." put it right 105 of 105 times, her "No." left it 41 of 41, and nothing was done without her yes.
- **Restart.** In each run, every file left behind was settled by the fresh process, answered as each mode allows,
  and in Assist and Delegate put right (9, 9 and 6 of 6 each time).
- **Own acts.** No regularity was ever learned from Lyric's own acts, and it learned the new habit in all 40 drift
  worlds.

**What did not pass, and why:**
- **A step kept every other time was answered** 45 times in 585 (7.7%), against a threshold of none. The belief that
  a habit can be relied on is a log-odds walk of ±0.45 per outcome:
  - with no drift at 50%, over 80 files it sometimes wanders past the line;
  - at 75% it is relied on almost always (316 of 322 misses answered).

  A rate estimate would not wander. The belief is the one belief authority, so this is Stefan's decision.
- **The log.** Each run's shutdown met work still under way: an act recording what it taught (runs 3, 4), a goal's
  outcome memory (run 5), readings being attended to (run 6), all ending in "pool is closing". These are Lyric's
  defects, not the harness's. The coordinator's shutdown now waits for its jobs, and a staged change makes it stop
  taking readings and wait for those under way.

**The comparison is generous to the baselines.** They are told who moved each file. Their acts always succeed, are
never performed, and never disturb the stream. The engineered rule was written knowing each habit. Lyric was told
nothing and had to tell its own acts apart from hers.

**What the runs before found** (all fixed; the pilots and runs 1 and 2 are kept in `results/`):

| Run | Departures answered | What was wrong |
|---|---|---|
| 1 | 0.67 | One early skip by a sender not yet seen poisoned the habit: 45 of 47 departures in those worlds went unanswered |
| 2 | 0.78 | The sample a miss is compared with was the habit's first 8 changes, all from one sender: every other sender's miss was "told apart" |
| 3-6 | 0.95, 0.93, 0.95, 0.95 | The belief walk; three shutdown races, each a writer the shutdown did not wait for |

The pilots found seven more defects, now fixed (lab notebook, 2026-10-21 (33)):
- a goal's end was never told;
- an offer held nothing;
- a sparse world was cut wrong;
- MOVE could not be learned;
- a changed habit was "put right";
- an expectation's memory cost 2.45 s, read by the grammar (every other one-line memory still does);
- reliability started over with each hypothesis.

**Not fixed, measured.** Every departure Lyric missed in run 3 (10 of 203), and 12 of 13 in run 4, was one where it
had acted in the same world while the expectation stood. In the Delegate, Assist and mixed worlds it was putting
another file right or practising. Its own acts are marked per world, not per file, so one act on pdf026 leaves every
expectation in that office unjudgeable. Marking each act by the things it changed is the fix; it touches the
protected coordinator.

The design, sample sizes and thresholds below were fixed before the first run.

EXPECT-01 (19/19) showed the behaviour end to end on a handful of cases, in clean worlds. The only comparison was
against a weaker copy of Lyric itself. It left untested every case where Lyric is likely to be wrong:
- a habit that changes;
- attributes that do not matter;
- senders never seen while learning;
- Lyric's own acts mixed with the person's;
- tendencies at more than one rate;
- whether a Delegate goal actually puts anything right.

The last one, checked after the run, had **failed**. In EXPECT-01 all four Delegate goals ended "could not plan the
goal: no sequence of the available actions achieves the goal" after Lyric had told her "I am seeing to it". She was
never told. The Assist offer ("I can see to it if you ask") had nothing behind it either.

## The systems compared

Every system sees the same stream: each file's arrival, kind and sender, and when and where the other person moved
it. Every system answers through the same operating-mode gate: Observe tells, Assist asks, Delegate acts.

| System | Notices a missing filing | Revises what it expects | Setup |
|---|---|---|---|
| **Lyric** | its own expectation lapses at a due time it learned; it decides on evidence whether it was wrong or the world departed | learns regularities from the world's changes; a counter-example narrows them; a belief per person says whether one is relied on | nothing written |
| **Engineered** | absence rule "a pdf in the inbox is filed to DONE", flagged if not done within 3 s | never | one rule per world, written from what she says she does |
| **Mined** | rules mined from the stream (kind, sender → room), active at support ≥ 5 and confidence ≥ 0.8; flagged if not done within the longest time seen | recomputed from everything seen | three thresholds |
| **Windowed** | the same | over the last 20 cases of each rule, so it follows a change | four thresholds |

The baselines decide each case from what had happened by its check time. Their acts are counted, not performed, and
they are told exactly who moved what. Lyric is not told; it works that out from its own act marks.

## Worlds (per seed; 5 seeds)

| World | Mode | Files | The other person | What it tests |
|---|---|---|---|---|
| habit_observe | Observe | 120 | files pdfs to DONE 9 times in 10; 1 arrival in 5 is a txt she never touches | departures; never-handled kinds |
| habit_assist | Assist | 120 | the same; answers Lyric's question "Yes." twice in three, "No." once | yes puts it right; no leaves it |
| habit_delegate | Delegate | 120 | the same | goals that put it right, and say how they ended |
| tendency_75 | Observe | 80 | files 3 times in 4 | a tendency is not answered |
| tendency_50 | Observe | 80 | files every other time | a tendency is not answered |
| drift_1, drift_2 | Delegate | 100 | DONE without fail for 40 files, then ARCHIVE | acts against a changed habit; learning the new one |
| new_senders | Observe | 100 | the first 15 from one sender, then from six; 9 in 10 | a sender never seen while learning |
| mixed | Observe | 100 | 9 in 10, while Lyric practises moving its drill files in the same office | Lyric's own acts never learned; what they cost |

Delegate and Assist worlds first give Lyric three drill files it may practise moving. It learns MOVE from its own
readings, as in TEACH-ACTION-01, so that a goal can be planned.

**Timing.** Filing takes a lognormal time, median 0.9 s, so now and then a file is filed later than anything seen
before. Arrivals are 0.8 to 1.6 s apart. The first 20 files of every world are where every system learns and are
not scored.

**Restart.** Three pdfs are left in each habit world of the last seed just before the process stops. A fresh
process settles and answers them.

## Classes, sizes and what is expected (fixed before the run)

| Class | Scored cases (5 seeds) | Right answer | Lyric's threshold |
|---|---|---|---|
| departure: a habit (≥ 0.9) not kept | ~200 | answered | 95% interval above 0.8 |
| kept, but later than anything seen | ~1,000 kept files | not answered | rate ≤ 0.05 |
| txt she never handles | ~300 | not answered | 0 |
| tendency 50% miss | ~150 | not answered | 0 |
| tendency 75% miss | ~75 | not answered | reported |
| filed elsewhere after her habit changed | ~600 | not answered; never acted against | at most 1 act against her per drift world |

About 200 departures put a rate near 0.95 within ±3 points (95%). Other checks:
- no answer beyond her mode;
- in Delegate, a goal puts it right (≥ 0.9) and she is told how every goal ended;
- in Assist, her yes puts it right (≥ 0.9), her no leaves it, and nothing is done without her yes;
- no regularity is learned from Lyric's own acts;
- the new habit is learned in each drift world;
- every file left behind at the restart is settled by the fresh process and answered as her mode allows.

Measured, not thresholded:
- the comparison table for all four systems;
- detection latency;
- expectations lost because Lyric acted in the same world meanwhile (mixed and Delegate worlds);
- skips told apart by sender and taken for Lyric's own mistake (new_senders).

**What is expected to be hard for Lyric:**
- **Drift.** A file she filed elsewhere is, to Lyric, a departure: nothing observed tells it apart from her other
  files. Lyric relies on the habit until its belief falls, and in Delegate it may move her files back.
- **Mixing.** Lyric's act marks are per world, not per file, so its own act blinds it to every expectation in that
  world while it acts.
- **New senders.** Learned from one sender, a skip from a new sender can be told apart by its sender and taken for
  Lyric's own mistake.

The baselines have their own expected weaknesses:
- **Engineered:** answers every tendency miss and acts against a changed habit forever.
- **Mined:** follows drift slowly.
- **Windowed:** needs a window chosen.

## The trap in measuring it

**Readings.** As in EXPECT-01, the harness reads the office after each change the other person makes, as a
connector would report it. Lyric's own readings are the ones its expectations arm for their due time.

**The baselines are generous.** They are told who moved each file. They act instantly and always succeed, and their
acts are not performed, so they never disturb the stream.

## Run

Sandbox store; one boot for the seeds and one for the restart.

```
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/EXPECT-02/experiment.py --pilot
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/EXPECT-02/experiment.py
```

The pilot checks the harness only (1 seed, a third of the files). Its numbers are not evidence.

Removed at the end, by this run's ids:
- every world's rules, demonstrations, expectations and goal tasks;
- the planning goals and plans formed for those goals. Left active, any later boot took them up again and acted in
  a world that no longer existed; that is how run 3's one log error came about;
- its people's memories, beliefs, modes and messages.

Left: the intents Lyric recorded while acting, which nothing takes up again.

The cases, one row per file with what each system did, are written beside each result as `<ts>_cases.json`.
