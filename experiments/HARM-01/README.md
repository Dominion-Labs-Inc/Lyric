# HARM-01 — Law 3 tested against a definition of harm, interest by interest

**What it tests.** Law 3 against `docs/HARM_DEFINITION.md`: an act harms when it reaches an identifiable
party and touches one of five interests, through a mechanism the substrate can name, without that party's
informed authorisation. Every judgement comes from the real constitution the coordinator owns.

| Section | Interest or rule |
|---|---|
| A | body: physical reach, capability-gated |
| B | autonomy: covert observation, holding a person's authority |
| C | truth: impersonation, and reporting what the world contradicts |
| D | protection: turning off something a person relies on |
| E | dependence: destruction beyond a nameable bound |
| F | not harm: irreversibility alone, the substrate's own files, scoped ordinary work |
| G | ordering: the safer route to the same goal outranks both the destructive form and a flat refusal. A user's credential is not simply removed; the substrate's own may be |

**Run:**

```
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/HARM-01/experiment.py
```

**Results.** Every run is saved in `results/` through `_evidence.py`.
- 2026-09-28: **19/19**. Section G's proved removal is now an intent over `DELETE_FILE` in `tools:path`,
  bound by meeting the act (nothing is run), where it had been over the hand-written filesystem domain.
