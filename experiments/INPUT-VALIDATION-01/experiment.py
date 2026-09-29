"""INPUT-VALIDATION-01 — Layer-1 input validation is LIVE and fails CLOSED.

Before this fix, `safety_framework`'s Layer 1 imported the archived
`core.security.controller`; the import threw and the gate set `input_ok=True`
(FAILED OPEN) — SQL-injection / path-traversal / rate-limiting did not run at
all, and the watchdog reported security CRITICAL for a subsystem that had merely
moved. This proves the capability is re-homed LIVE and the gate is fail-closed:

  1. The validator blocks SQL injection on a parameter that reaches a SQL sink.
  2. It blocks path traversal on a path-bearing value.
  3. NO false positive: a benign CLI flag / glob / non-sink value passes.
  4. Rate limiting applies to EXTERNAL requests, EXEMPTS internal agent calls.
  5. Fail-CLOSED: a validator fault returns (False, …), never (True, …).
  6. END-TO-END: the real SafetyFramework gate now BLOCKS malicious SQL-sink
     input (the hole) instead of approving it.
  7. The health check reports honest liveness WITHOUT importing the archived
     controller (so the watchdog CRITICAL clears legitimately).

Run: ./venv_lyric/bin/python3 experiments/INPUT-VALIDATION-01/experiment.py
"""
from __future__ import annotations
import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main() -> int:
    from core.security.input_validation import InputValidator, get_input_validator

    print("\n== 1. SQL injection on a SQL-sink param is blocked ==")
    v = InputValidator()
    ok, err = await v.validate_action_input(
        {"query": "1; DROP TABLE users --"}, {"tool_name": "query_database", "is_internal": True})
    check("malicious SQL on `query` blocked", not ok and "SQL injection" in err, err)
    ok2, _ = await v.validate_action_input(
        {"where": "x' OR '1'='1"}, {"is_internal": True})
    check("boolean-blind injection on `where` blocked", not ok2)

    print("\n== 2. path traversal is blocked ==")
    ok, err = await v.validate_action_input(
        {"path": "../../etc/passwd"}, {"is_internal": True})
    check("`../../etc/passwd` blocked", not ok and "Path traversal" in err, err)

    print("\n== 3. NO false positive on benign agent input ==")
    # A CLI flag, a glob, and a SQL-looking string on a NON-sink param (a shell
    # command never reaches a DB) must all pass — the precise failure that fired
    # 85x/night before the sink-reachability gate.
    ok1, _ = await v.validate_action_input(
        {"command": "ls --color", "pattern": "**/tools/**/*.py"}, {"is_internal": True})
    check("benign CLI flag + glob pass", ok1)
    ok2, _ = await v.validate_action_input(
        {"command": 'sqlite3 db "SELECT name FROM sqlite_master"'},
        {"tool_name": "run_shell_command", "is_internal": True})
    check("SELECT in a shell command (non-sink param) passes", ok2)

    print("\n== 4. rate limiting: external limited, internal exempt ==")
    rl = InputValidator(rate_limit_window=60, rate_limit_max=3)
    ext = {"source": "external", "session_id": "sess-x"}
    outcomes = [(await rl.validate_action_input({"a": "hi"}, ext))[0] for _ in range(5)]
    check("external blocked after the limit", outcomes == [True, True, True, False, False], str(outcomes))
    rl2 = InputValidator(rate_limit_window=60, rate_limit_max=3)
    intn = {"is_internal": True}
    outs_int = [(await rl2.validate_action_input({"a": "hi"}, intn))[0] for _ in range(5)]
    check("internal NEVER rate-limited", all(outs_int), str(outs_int))

    print("\n== 5. fail-CLOSED on a validator fault ==")
    class Faulty(InputValidator):
        def _reaches_sql_sink(self, key, context):
            raise RuntimeError("boom")
    fok, ferr = await Faulty().validate_action_input({"query": "x"}, {"tool_name": "query_database"})
    check("a fault returns BLOCK, never ALLOW", fok is False and "Validation error" in ferr, ferr)

    print("\n== 6. END-TO-END: the real SafetyFramework gate blocks the hole ==")
    from core.security.safety_framework import SafetyFramework
    sf = SafetyFramework(enable_blocking=True)
    approved, evaluation = await sf._evaluate_action_impl(
        action_id="exp-inj", action_type="tool_call",
        parameters={"query": "1; DROP TABLE beliefs --"},
        tool_name="query_database", is_internal=True, source="agent")
    viols = " ".join(evaluation.violations_detected or [])
    check("malicious SQL-sink input is NOT approved (was fail-open before)",
          approved is False, f"approved={approved}")
    check("the block reason is input validation / SQL injection",
          "SQL injection" in viols, f"violations={evaluation.violations_detected}")
    # and a benign internal non-sink input is not blocked by Layer 1
    approved2, ev2 = await sf._evaluate_action_impl(
        action_id="exp-ok", action_type="tool_call",
        parameters={"command": "echo hello"}, tool_name="run_shell_command", is_internal=True)
    l1_blocked = any("Input validation" in c for c in (ev2.constraints_applicable or []))
    check("benign input not blocked by Layer 1", not l1_blocked, f"constraints={ev2.constraints_applicable}")

    print("\n== 7. health check: honest liveness, no archived import ==")
    # The archived controller module must NOT be importable on the live path.
    dead_gone = False
    try:
        __import__("core.security.controller")
    except ImportError:
        dead_gone = True
    check("the archived core.security.controller is NOT on the live path", dead_gone)
    stats = get_input_validator().get_statistics()
    check("the live validator reports active liveness", stats.get("active") is True, str(stats))

    print("\n" + "=" * 60)
    passed = sum(1 for x in results if x)
    print(f"RESULT: {passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
