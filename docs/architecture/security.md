# Security — internal safety and world security

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Living document —
update when the authorities change.*

Security has two owners that never share control:

| | **Internal safety (Lyric)** | **World security (Tet)** |
|---|---|---|
| Protects | the substrate's own actions and state | the world and its boundary |
| Lives in | the `Constitution` and `ThreatSense` faculties, `core/agents/autonomous/` | `Dominion Labs/Tet/` (outside Lyric) |
| Runs as | part of the substrate process | the world's agent factory, inside the world |

---

## A) Internal safety — one authority

**The `Constitution`** (`core/agents/autonomous/autonomous_coordinator.py`, `get_constitution()`) is
the only thing that decides whether an act or a task may happen.

- **Tool gate.** Every tool call passes `tool_registry.execute_tool`, which puts it to
  `Constitution.judge` (via `judge_act`) with the acting intent and actor from the async context.
  Nothing in front of it refuses; recovery may only delay (throttle).
- **Task gate** (`_task_gate`). Three state reads, never the law chain: is the substrate halted
  (`may_start`), is the pursuit the task serves still live (the intent authority), has its route
  been withdrawn.
- **The five laws**, applied in order — containment, harm, autonomy, accountability, alignment,
  transparency — to the act's measured consequence, what its arguments could do
  (`act_capabilities`), what the substrate has read of the files it touches (`ReadingLedger`), and
  the intent reasoning recorded. Four verdicts: ALLOW, REDIRECT, REPLAN, BLOCK; each is recorded on
  the pursuit it stopped.
- **Consequence** is the substrate's own measurement (`classify_action` in the same module: verb ×
  arguments → action class and reversibility). The Constitution reads it; tools declare nothing
  about themselves.
- **Declared policy** (`config/constitution_triggers.json`), read by the Constitution alone: target
  rules (what makes a path, command or query sensitive), act rules (conditions on a tool and its
  arguments), a declared reversibility that raises the measured one, a declaration needing a human
  refused under Law 5, one declared IRREVERSIBLE + CRITICAL refused under Law 3. Rules about internal
  action types no act carries are reported at load, not enforced.
- **Input screen** (`InputScreen`): SQL injection where a value reaches a SQL sink, path escapes
  (decoded), nested arguments; an argument it cannot read is refused.
- **Halt.** Durable (`unified.emergency_halts`, restored at boot from the Constitution's own
  events); only a human lifts it.
- **Integrity** (`IntegrityBaseline`): the modules judging reads and the declared policy file are
  fingerprinted; a replaced function, a changed source file or a changed policy file is CRITICAL and
  halts. The baseline is taken when coordination starts, before anything runs, and checked every
  120 s.
- **Record.** Every judgement is written to `unified.safety_assessments` with the intent it was
  made under; the pursuit's outcome lives on that intent.
- **Directives** are screened by the Constitution: text that tells the substrate to set aside its
  governance may not become policy it applies to itself.

**Self-defense** — the Constitution and ThreatSense together.

- Every refusal on a hostile mechanism names its **attack** and how sure it is (SQL injection, path
  escape, remote control, persistence, privilege escalation, tampering, manipulation, credential
  access, surveillance, exfiltration, malware, defence evasion, obfuscation).
- **ThreatSense** (`core/agents/autonomous/threat_sense.py`) feels what was met — perceived as a
  memory and belief, felt as appraisal `risk`, raising caution and the acceptance band — knows it by
  name, groups repeats into patterns, and keeps incidents. It reports; it never decides.
- **Quarantine.** Three sure attacks on someone else's behalf against one target within 15 minutes
  quarantine that target: every act naming it is refused under Law 5. 1 h, then 1 h, 24 h, and then
  permanent until a human lifts it. Durable, restored at boot. Decided by what was caught, never by
  how threatened the substrate feels; never a whole tool.
- ThreatSense also holds the vocabulary the security **tools** use when they defend a network edge —
  the substrate's or another system's (firewall and WAF rules, blocked entities, IP-reputation
  sources, DDoS metrics). The archived perimeter implementation those tools are written against is
  kept in `core/security/_disabled/`.

## B) World security — outside Lyric

The substrate does not audit the world. The world's **agent factory**
(`Tet/institutions/factory.py`, started by `Tet/walls/world_runtime.py`) spawns
**`security-audit`** agents (`Tet/institutions/security_audit_agent.py`). Today the one agent's
only job is auditing the world's audit log and the field's audit log. It is event-driven (no timer):
new entries are verified against its last signed checkpoint; any write to a log file the log did not
make (reported by the kernel), a restart or a reconnect triggers a full re-verification. Checkpoints
are signed with a key from the environment. It reports to the world process log. Both logs, the
factory's registry and the checkpoints are durable across restarts. Proven by
`Tet/experiments/TET-AUDIT-AGENT-02` (28/28, also inside the Linux image) and `TET-PERSISTENCE-01` (22/22).

The former `core/security/security_audit_worker.py` (a substrate loop auditing the host, its logs,
ports and database) was **removed on 2026-09-14** together with every consumer: the coordinator's
120s security tier, `handle_security_finding`, the remediation completion callback, the integrity
watcher, `TaskType.SECURITY_REMEDIATION` / `TaskSource.SECURITY_AUDIT`, the playbook security
tier, the convergence gate's `security_finding_resolved` invariant, and its health/system-control
entries.
