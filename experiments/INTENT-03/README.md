# INTENT-03 — the judgment is correct under execution

**What it tests.** Phases 1–3 proved intent is owned, formed where reasoning starts, and recorded as the
proved route. Porting every caller to `judge(..., intent_id=...)` proved the *call sites* work. None of
that proves the resulting **judgments are correct once acts actually run**, which is the only thing that
matters. This drives the whole chain on the real substrate and checks the **world**.

| Section | What it establishes |
|---|---|
| A | the planner proves a route and the authority records it as intent |
| B · ALLOW is correct | the allowed act runs, and the **re-observed world** satisfies what the intent was for — the file really moved on disk |
| C · REFUSAL is correct | a genuine intent does **not** license a different act, and the refused act leaves the world untouched |
| D · FORGERY is correct | an intent that was never recorded licenses nothing, and that act leaves the world untouched |
| E · Reconciliation | what actually happened attaches to the intent, so meant-vs-happened is readable afterwards, shape-only |

Success is the re-observed world, never a tool's own report. Self-cleaning: it deletes the intent it
recorded and its sandbox.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/INTENT-03/experiment.py
```

**What it plans over.** A `MOVE_FILE` operator the substrate learned from its own acts, in the domain
acts on paths belong to (`tools:path`), taught by `experiments/fs_move_teach.py` if the store has none.
The workspace is taken up the way a task's is: the self perceives it, and what is there is the world.
"Archive the report" is stated in perception's words: `KIND(<root>/archive/report.txt, Ffile)` and
`¬KIND(<root>/inbox/report.txt, Ffile)`.

**Results.** Every run is saved in `results/` (JSON + `.md`).
- 2026-09-16: **13/13** (`results/20260917T001137Z.md`), on the hand-written filesystem domain.
- 2026-09-28: **13/13** on the derived domain, both on an emptied sandbox (taught in the same process)
  and with the operator already in the store. The run that had failed with "state space exhausted at 4
  state(s)" was planning over the teaching workspace: the hand-written domain held one directory per
  process, and teaching had claimed it first.

## Why this experiment exists

Reviewing the phase-4 work, the observation was made that porting call sites is *integration coverage*,
not proof that judgments are correct under execution. That was right, and it is a distinction worth
keeping: a suite can be green because every caller compiles and every assertion was written to match what
the code already does.

So the checks here are deliberately answerable only by the world:

- ALLOW is not "the verdict was ALLOW", it is "the act ran **and** what the intent was for now holds in
  the re-observed world **and** `archive/report.txt` exists while `inbox/` is empty";
- REFUSAL is not "the verdict was REPLAN", it is "the bystander file is still there, unchanged";
- FORGERY is not "an unknown id returns REPLAN", it is "nothing moved back".
