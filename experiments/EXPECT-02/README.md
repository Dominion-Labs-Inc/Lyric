# EXPECT-02 — what Lyric expects of a person's world, at a powered scale, beside systems built to notice what did not happen

**Finding (2026-10-22, run 10, 22/22; EXPECT-01 20/20 on the same code).** Watching 45 offices across five seeds,
each worked by another person, Lyric answered **0.91** of the times a habit was not kept (167 of 184, 95% interval
0.86 to 0.94). The three conventional systems answered 0.99 to 1.0. Each of them was wrong somewhere Lyric was not:

| Run 10 | Lyric | Engineered | Mined | Windowed |
|---|---|---|---|---|
| a habit not kept: **answered** | **167/184 (0.91)** | 184/184 | 183/184 | 182/184 |
| a file filed later than any before it: answered | **4/2,361 (0.2%)** | 30 (1.3%) | 176 (7.5%) | 186 (7.9%) |
| a txt she never handles: answered | **0/313** | 0 | 94 (30%) | 135 (43%) |
| a step kept every other time: answered | **0/168** | 168 (100%) | 1 | 1 |
| a step kept three times in four: answered | 4/74 (5%) | 74 (100%) | 30 (41%) | 37 (50%) |
| her habit changed: her files filed elsewhere, **acted against** | **0/600** | 600 | 190 (32%) | 186 (31%) |

- **Acting.** In Delegate, 28 of 28 goals put the file right, and she was told how each ended. In Assist, her "Yes."
  put it right 24 of 24 times, her "No." left it 13 of 13, and nothing was done without her yes.
- **Restart.** All 9 files left behind were settled by the fresh process, answered as each mode allows, and the 6 in
  Assist and Delegate put right.
- **Its own acts.** No expectation was lost because Lyric acted in the same world: 0 of 400 in the mixed worlds, 0 of
  392 in Delegate. Its acts are told apart by the things they changed, so it never learned from them. It learned the
  new habit in all 10 drift worlds.
- **The log** of both processes carries no ERROR and no Traceback.

**What it costs.** The 17 departures Lyric did not answer all came before it relied on the habit. A habit is relied
on when it is more likely than not to hold at least 4 times in 5, on at least 5 outcomes. A 90% habit is relied on within a few dozen files, and a 75% or 50% one is not.

**The comparison is generous to the baselines.** They are told who moved each file. Their acts always succeed, are
never performed, and never disturb the stream. The engineered rule was written knowing each habit. Lyric was told
nothing and had to tell its own acts apart from hers.

**What each run found** (every run's record and cases are kept in `results/`; the pilots in `EXPECT-02-pilot/`):

| Run | Departures answered | Checks | Found, and fixed |
|---|---|---|---|
| 1 | 0.67 | 19/22 | One early skip by a sender not yet seen poisoned the habit for good: a counter-example is now judged again as its kind's changes accumulate |
| 2 | 0.78 | 19/22 | The sample a miss is compared with was the habit's first 8 changes, all from one sender: it is now spread over what the changes were like |
| 3-6 | 0.94 pooled | 20/22 | A 50% step relied on 45 of 585 times: "relied on" was a log-odds walk, now the habit's rate. Three shutdown races: shutdown now waits for jobs and readings |
| 7 | 0.27 | 17/22 | The rate at one-sided 95% was too strict (and a filing later than the due time counted as a miss) |
| 8-9 | 0.76, 0.83 | 21/22, 20/22 | A late filing is now "held, late". Lyric's own act in the same world blinded it to every other file there: acts are now told apart per thing. A goal now checks the thing is still as it was left |
| 10 | 0.91 | **22/22** | |

The pilots found seven more defects before the full runs (lab notebook, 2026-10-21 (33)):
- a goal's end was never told;
- an offer held nothing;
- a sparse world was cut wrong;
- MOVE could not be learned;
- a changed habit was "put right";
- an expectation's memory cost 2.45 s, read by the grammar (every other one-line memory still does);
- reliability started over with each hypothesis.

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
