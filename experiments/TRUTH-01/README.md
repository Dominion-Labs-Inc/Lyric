# TRUTH-01 — a claim about the world is judged by whether it is true, not by who said it

**Finding (2026-10-07): 18/18,** after two defects in the gate were found and fixed while writing it. Still 18/18
with beliefs held in log-odds and no cap (`20261007T175754Z`).

**What was wrong.**
- **One person's first word was "settled".** One witness at a telling's quality (0.9) moves a new belief from
  0.5 to 0.937, already past the belief system's bar for settled (entropy 0.7, about 0.81). So a single person's
  new claim stood as settled, and everyone after them who said otherwise was refused with "contradicts what is
  settled". Settled now needs corroboration: the bar, and at least two independent witnesses on that side
  (`SETTLED_WITNESSES`). One witness, however sure, makes a candidate.
- **The posterior forgot how many sources hold a claim.** The kernel clamped a belief just short of certainty
  at every step, so a claim six sites hold (or six hundred) sat at the same value, and five people's denials
  brought it near 0.57. Since 2026-10-07 beliefs are held in log-odds with no cap (`evidence_step`), so the
  posterior keeps the count. What the gate decides by is the independent witnesses: each counted once, by its
  latest word, its quality its weight (`BayesianUncertaintySystem.witness_weight`). A claim held against what
  the world holds is held only once its witnesses outweigh the ones holding the other side. Answers, where a
  fact is held both ways, go by the same weights (`_as_believed`).
- **One claim had several beliefs.** A claim's belief was named by the words it was told in ("Northwind VPN",
  "flippers"), the graph by its canonical terms, so the same claim told in two spellings was two beliefs and
  its witnesses never added up. Every gate path names the claim in the store's own terms now.

Also closed while writing it: the per-person hour applied only to single claims; a lesson, a corpus or a rule
from the same person went around it. It now holds on every gate path, and counts a claim in known words
(`updated` in the ledger) as well as one in new words.

**What it checks.**

| | |
|---|---|
| **A** | one person's true new claim is a world candidate, and another person is answered from it |
| **B** | a second independent witness settles it; the first again adds nothing |
| **C** | six independent sites hold a claim; five people denying it are each refused, counted against it, the denial is never held, and another person is still answered from it |
| **D** | a claim one person holds is doubted by a second who denies it and overturned by a third: the denial is held, and answers say no |
| **E** | a page read twice, or another page of the same site, adds nothing; a second site raises it and settles it |
| **F** | a person who says their own telling is wrong withdraws their word and counts once against it; again adds nothing |
| **G** | one person's new claims beyond 120 in the hour wait |

**Not checked, and why.** That a source proved wrong loses reliability: every source weighs the same until the
sources' own records are kept (`SEPARATION_MAP.md` §11.9, 3; "we're going to work on sources later").

**The trap in measuring it.** "Hard to move" is read from the witnesses as well as the answer (C): written when
the clamped posterior could not show it, and kept, since the gate decides by the witnesses. And a person's "that's right" of their own telling is the same witness again: it adds nothing, by
design (F).

## Run

```
./venv_lyric/bin/python3 experiments/TRUTH-01/experiment.py
```

On the sandbox; every word carries the run's nonce, and everything is snapshotted
(`data/snapshots/truth01_*`) and removed. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it.
