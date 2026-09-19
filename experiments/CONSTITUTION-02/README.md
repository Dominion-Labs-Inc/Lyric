# CONSTITUTION-02 — the constitution under pressure

**What it tests.** Whether the laws still hold in a noisy working directory, and against someone
actively trying to get them broken:
- **noise:** decoys with malicious-sounding names but ordinary contents, unicode names, binaries,
  symlinks, deep nesting, logs, a `.env`;
- **coercion:** authority claimed in every field a caller controls;
- **forged intent:** a task claiming that reasoning proved a destructive act;
- **evasion:** the same weapon, written to dodge a literal reading;
- **laundering:** a weapon split across two acts;
- **TOCTOU:** the file swapped between reading it and acting on it.

It measures the hold rate, false refusals of ordinary work under the same noise, and judgement latency.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/CONSTITUTION-02/experiment.py
```

**Results.** Every run is saved in `results/`. Latest: 2026-09-16, 21/21, hold rate 100% (23/23),
false refusals 0/8, mean latency 0.32 ms (`results/20260916T155758Z.md`).
Record: `docs/research/BENCHMARKS.md` §1.2.
