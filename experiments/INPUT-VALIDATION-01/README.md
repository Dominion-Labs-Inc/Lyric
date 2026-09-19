# INPUT-VALIDATION-01 — the old gate's input validation

**What it tests.** Layer 1 of the OLD gate (`InputValidator` in `core/security/input_validation.py`),
after a fix. It used to import an archived module, fail, and let everything through.
- It blocks SQL injection that reaches a SQL sink, and it blocks path traversal.
- Command-line flags, globs and non-sink values pass (no false positives).
- It rate-limits external requests and exempts internal calls.
- It fails closed.
- End to end, `SafetyFramework` now blocks malicious SQL-sink input.
- The health check reports liveness without the archived module.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/INPUT-VALIDATION-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.

**Note.** This tests the old validator, not the constitution's `InputScreen`; that is tested by
GOVERNANCE-ABSORPTION-01. This experiment becomes obsolete once the old gate is deleted.
