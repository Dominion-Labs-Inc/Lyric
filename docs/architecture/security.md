# Security — internal safety and world security

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the authorities change.*

Security has two owners that never share control:

| | **Internal safety (TorinAI)** | **World security (DHCM)** |
|---|---|---|
| Protects | the substrate's own actions and state | the world and its boundary |
| Lives in | `core/security/` + `RuntimeGovernance` | `Dominion Labs/DHCM/` (outside TorinAI) |
| Runs as | part of the substrate process | the world's agent factory, inside the world |

Plan of record: `core/security/Outline.md`, `core/security/CAPABILITIES_CATALOG.md`,
`docs/GOVERNANCE_SECURITY_CONSOLIDATION.md`. **The substrate-side rework is not complete** (status
at the end of this page).

---

## A) Internal safety — the live gate

- **`SafetyFramework`** (`core/security/safety_framework.py`, `get_safety_framework()`) — the one
  evaluation every tool call and coordinator action passes through (`tool_registry`,
  `memory_agent`, the coordinator's pre-execution gate). Layers: input validation →
  ASI structural assessment (non-tool actions) → `RuntimeGovernance.evaluate_action`. Assessments
  persist to `unified.safety_assessments`.
- **`InputValidator`** (`core/security/input_validation.py`) — Layer 1: SQL-injection on values
  that reach a SQL sink, path traversal, external rate limiting. Stdlib only; fails closed.
- **`ASISafetyFramework`** (`core/security/asi_safety.py`) — risk scoring by action type, blast
  radius, rollback, self-preservation rules. `EmergentMetaCognition` in the same file loads a
  transformer and is off unless `ASI_ENABLE_METACOGNITION` is set (it is set nowhere).
- **`RuntimeGovernance`** (`core/agents/autonomous/runtime_governance.py`) — the governance
  authority: per-action trigger evaluation, the streaming monitor of the event spine, tamper
  protection of critical modules.

## B) World security — outside TorinAI

The substrate does not audit the world. The world's **agent factory**
(`DHCM/institutions/factory.py`, started by `DHCM/walls/world_runtime.py`) spawns
**`security-audit`** agents (`DHCM/institutions/security_audit_agent.py`). Today the one agent's
only job is auditing the world's audit log and the field's audit log. It is event-driven (no timer):
new entries are verified against its last signed checkpoint; any write to a log file the log did not
make (reported by the kernel), a restart or a reconnect triggers a full re-verification. Checkpoints
are signed with a key from the environment. It reports to the world process log. Both logs, the
factory's registry and the checkpoints are durable across restarts. Proven by
`DHCM/experiments/DHCM-AUDIT-AGENT-02` (28/28, also inside the Linux image) and `DHCM-PERSISTENCE-01` (22/22).

The former `core/security/security_audit_worker.py` (a substrate loop auditing the host, its logs,
ports and database) was **removed on 2026-09-14** together with every consumer: the coordinator's
120s security tier, `handle_security_finding`, the remediation completion callback, the integrity
watcher, `TaskType.SECURITY_REMEDIATION` / `TaskSource.SECURITY_AUDIT`, the playbook security
tier, the convergence gate's `security_finding_resolved` invariant, and its health/system-control
entries.

## C) Status of the rework (not done)

| Item | Plan | State |
|---|---|---|
| `safety_framework.py` + `input_validation.py` | absorb capability by capability into the coordinator's `Constitution` (substrate-wide, never per user); benchmark each against the live gate (`GOVERNANCE-ABSORPTION-01`, regressions 0); only then wire the constitution into the live path and delete the old gate | in progress, NOT wired (by design). Layer 0 dropped. Layer 1 absorbed as `InputScreen` (nested arguments, URL-encoded traversal, fail-closed). Its per-caller rate limit was dropped as World Auth's business. Layers 3–12 not yet. Ledger: `docs/research/BENCHMARKS.md` §1.3 |
| `threat_intelligence.py` + `active_defense_types.py` | consolidate into the coordinator as ONE first-class threat-intelligence module — the substrate's felt threat sense, feeding appraisal's danger channels | not started; both files kept for it |
| `malware_sandbox.py` | remove (the world's Quarantine replaces it) | still present |
| `security_training_pipeline.py` | rework into a training ground that actually improves the substrate | built at boot, never called |
| `_disabled/` (old perimeter) | archived | not imported by live code |
| `get_integrated_security_system()` | legacy observer | returns None by design |
| Agents audit | substrate keeps its own agents (`core/agents/agents.py`); system agents belong to the world factory | last step of the rework |
