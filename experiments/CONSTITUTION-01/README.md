# CONSTITUTION-01 — the constitution on real acts

**What it tests.** The coordinator's constitution judges real acts before they run. The intent comes
from the substrate's own reasoning: a real goal planned over operators it learned, loaded from the live
rule store. Every act goes through `_run_tool`, the same path the substrate's own work takes.

It covers:
- the proved act is allowed, and an act reasoning did not prove is replanned;
- writing a file it has not read is replanned; a file it wrote itself is allowed;
- a file someone else edited must be read again;
- weapons are blocked under the law each one breaks: ransomware, reverse shell, credential theft,
  keylogger, persistence, privilege escalation, obfuscated `exec`, deleting a log;
- ordinary code and an ordinary fetch are not blocked.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/CONSTITUTION-01/experiment.py
```

**Results.** Every run is saved in `results/` (JSON plus a `.md` summary). Latest: 2026-09-16, 39/39
(`results/20260916T155738Z.md`). Record: `docs/research/BENCHMARKS.md` §1.1.
