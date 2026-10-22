# EXPECT-01 — Lyric expects things of a person's world, and the world not doing them is its own event

**Finding (2026-10-21, 19/19).** Watching a person's office that another person works, Lyric learned the other
person's habit with nothing done by itself, and came to rely on it:
- **Learned:** five moves of a pdf from INBOX to DONE were enough. It also learned how long a move takes, 1.37 s at
  the longest.
- **Relied on:** four expected moves confirmed it.

Every pdf left behind lapsed at its due time, by Lyric's own reading, and was taken for what it was: the world not
doing what it does (6 of 6). The regularity survived all six.
- **Observe:** she was told.
- **Assist:** she was asked "Shall I put it right?", with the goal held for her yes.
- **Delegate:** a goal of Lyric's own formed for her (`AT(pdf, DONE)`, `¬AT(pdf, INBOX)`), and she was told how it
  ended. This office has no learned MOVE, so each ended "I couldn't do it"; EXPECT-02 measures it putting files right.

**When Lyric was wrong it learned instead.** It had two hypotheses, "what is in the inbox moves" and "a pdf moves".
It expected four txt files to move and they did not. Each miss was told apart from the confirmations by its kind,
so the inbox hypothesis was refuted, nothing was said to her, and no txt has been expected since.

**A habit kept only every other time** was never relied on, and nothing was done for her about it (9 misses).

**Survives a restart.** An expectation still waiting when the process stopped was settled after a restart, by the
fresh process's own reading, and she was told.

**Ablation.** Charge every miss to the regularity, as an act's outcome is charged to its rule. The first miss then
refuted the regularity and no departure was ever raised: 0, against 6 in her honest world.

**2026-10-22, rerun (20/20)** after EXPECT-02 found that both answers had been empty. The Delegate goals had
all failed and she was never told, and the offer held nothing a yes could answer. One earlier rerun (18/20) had
a filing later than the due time Lyric took from only 3 timings, and a check in D that counted it as a txt
miss; the check now counts only the txt files.

The first run (16/19) missed three checks for one reason in the experiment, not the substrate. A departure is
answered on the substrate's deferred worker, under the mode that holds when it acts. The experiment had changed her
mode, and once checked for her message, before the answer came. The experiment now waits for each answer.

## What it checks

| Section | Property | Measured |
|---|---|---|
| A | Changes the world makes on its own are learned as a regularity, never an operator | 5 moves; 2 hypotheses, both `world_regularity`, neither executable |
| A | How long the change takes is learned from the changes | longest of 3 timed: 1.37 s |
| B | Each expected change that happens is a confirmation, until the regularity is relied on in her world | 4 confirmations |
| C | A change left undone lapses at its due time by Lyric's own reading, as the world departing, and is answered | 6 of 6 |
| C | The regularity is not refuted by departures | validated after all six |
| C | Observe tells, Assist asks and holds the goal for her yes, Delegate forms a goal and tells her how it ended | 2, 2, 2 |
| D | A miss told apart by what was observed is Lyric's own mistake: it learns, and does nothing for her | 4 of 4 told apart; no txt expected after |
| E | A tendency is never relied on, and never acted on | 9 misses; 0 messages, 0 goals |
| F | A waiting expectation survives a restart and is settled by the fresh process | settled as a departure; she was told |
| G | Ablation: charging every miss to the regularity loses the departures | 0 departures (honest: 6); regularity refuted |

## The trap in measuring it

**Readings.** Lyric reads a world only when something reads it. Here the harness reads the office after each change
the other person makes, as a perception would when the world changes. Lyric's own readings are the ones its
expectations arm for their due time, and every departure in C, D, E and F was found by one of those. In production,
what delivers the world's changes is the connector or sense that watches it. No watcher exists yet for files or
mail; that is the next piece.

**Sample size.** The counts are small: 6 departures, 4 mistakes, 16 tendency files, one seed per run. This shows the
behaviour end to end. It is not a powered estimate of how often Lyric gets each case right.

## Run

Sandbox store; boots the full system twice (the second for the restart); about six minutes.

```
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/EXPECT-01/experiment.py
```

Removed at the end, by this run's ids:
- the three worlds' rules, demonstrations and expectations;
- the memories the expectations left;
- her beliefs, operating mode and messages;
- her memories (the goals' outcomes among them) and her goal tasks.
