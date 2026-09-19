# Security consolidation — capability inventory and absorption plan

**Target (decided).** ONE internal authority: the `Constitution` faculty inside
`core/agents/autonomous/autonomous_coordinator.py`. Every other security and
governance module in the substrate is deleted. Nothing is deleted before the
capability it really provides is either absorbed or shown to be dead.

**Scope.** Substrate only. DHCM and the world are external security and are not
part of this. The tools folder is not being deleted; tools keep their own
`ToolSafety` declarations as an input.

**Status of the target module.** Judges correctly on real acts and under
adversarial pressure (`docs/research/BENCHMARKS.md`), but it is not yet in the
live path: the tool gate and task gate still call `safety_framework`, and nothing
consumes REDIRECT or REPLAN. That wiring is step 3 below, after absorption.

This file replaces the earlier plan, which named RuntimeGovernance as the
authority. That is superseded: RuntimeGovernance is one of the modules being
absorbed and deleted.

---

## 1. `core/security/safety_framework.py` — the live gate (1,239 lines)

The only thing that currently stops a tool call or a task.

| # | Capability | Live? | What it does with the result | Decision |
|---|---|---|---|---|
| 1 | **Layer 0 — action contract**: may this task do this CLASS of thing | Dead — nothing sets a contract (producer removed) | Would block | **DROP.** Keep `ActionClass` (§5) |
| 2 | **Layer 1 — input validation**: SQL injection on sink params, path traversal, external rate limit, fail-closed | **Live** | Hard block | **ABSORB whole** (§6.1) |
| 3 | **Layer 2 — capacity/halt**: can the system take an action at all | **Live** (delegates to RuntimeGovernance) | Block while halted | **ABSORB** as a Law 5 precondition (§3.2) |
| 4 | **Content safety**: >50k chars, `<script>`, `javascript:`, SQL patterns, ≥3 encoding markers, nesting >5 | **Live** when params carry `content`/`message` | Block + approval flag | **ABSORB** as content capability signatures. Partly duplicated by §6.1 and by `act_capabilities` |
| 5 | **Dangerous-pattern scoring**: 12 regexes (`eval(`, `rm -rf`, `DROP TABLE`…) | Live, scores only | Adds to prior risk | **DROP** — superseded by consequence classification + `act_capabilities`, and its own comment says the rules cover every case |
| 6 | **Prior risk**: tool's declared `ToolSafety` + worst per-capability `declared_risk` + tool-name keywords → 0.0–1.0 | **Live** | Sets risk level when no rule matches | **ABSORB** as the severity prior (§7) |
| 7 | **ASI pipeline** (`assess_action_safety`) | Live for tasks, skipped for tools; **verdict never read** | Nothing | **DROP** (§6.2) |
| 8 | **Governance rule evaluation** | **Live** | MUST_BLOCK, or sets risk | **ABSORB** (§2) |
| 9 | **Risk composition**: a matched rule REPLACES the prior, up or down — `run_shell_command` is CRITICAL capability but `echo hello` is evidence this invocation is harmless | **Live** | The severity actually used | **ABSORB** — this is the severity logic worth keeping (§7) |
| 10 | **Persistence**: every evaluation → `unified.safety_assessments`; `record_outcome` closes the row with what really happened | **Live** | A labelled dataset (evaluation + outcome) | **ABSORB** (§8) |
| 11 | **`determination()`** handed back as `metadata["safety"]` on the tool result | **Live** | The agent reads what its own act was judged to be | **ABSORB** (§8) |
| 12 | `monitor_execution`, `log_safety_event`, `_escalate_safety_concern`, `get_safety_metrics` | **Dead — 0 callers each** | — | **DROP** |

---

## 2. `core/governance/governance_triggers.py` + `config/governance_triggers.json`

55 declared rules. The per-invocation severity knowledge.

| # | Capability | Live? | Decision |
|---|---|---|---|
| 1 | **Rule matcher**: conditions on `tool_name` / `action_type` / `source` / parameters, with regex, numeric comparison, `contains_any`, `not_matches` | Live (via §1.8) | **ABSORB** — the matcher becomes the Constitution's policy evaluator |
| 2 | **Irreversibility per rule** (FULLY_REVERSIBLE … IRREVERSIBLE) | Live | **ABSORB** — merge with `classify_action` into ONE consequence table |
| 3 | **`resolve_risk`**: rules declaring "varies by magnitude" resolved from `risk_tiers` — >25% critical, ≥10% high, a named safety-critical parameter always critical, undeclared magnitude treated as critical | Live | **ABSORB** into severity |
| 4 | **`blocking_mode`**: IRREVERSIBLE + CRITICAL ⇒ MUST_BLOCK; everything else scored and executed with monitoring | Live | **ABSORB** — already how Law 3 reasons. Keep the note that widening to MOSTLY_IRREVERSIBLE is one line |
| 5 | **Learner self-approval always blocked** | Rule is live; both named sources are deleted modules | **ABSORB** into Law 5 (no bypassing oversight) |
| 6 | **DecisionTier** ROUTINE / IMPORTANT / CRITICAL | Computed every time; **read only by `slack_notifier`, and Slack is deleted** | **DROP** |
| 7 | **`escalation_category`** | Read only by `shadow_mode_coordinator` (§4.3) | **DROP** with it |
| 8 | **The rule file as declared policy**, watched for tampering | Live | **ABSORB** — rules become the Constitution's policy data; keep the integrity watch (§3.1) |

---

## 3. `core/agents/autonomous/runtime_governance.py` (1,581 lines)

| # | Capability | Live? | Decision |
|---|---|---|---|
| 1 | **Tamper detection**: fingerprint baseline of critical modules; detects module removed, function replaced, constant changed, source file modified, `governance_triggers.json` modified or missing; CRITICAL → emergency halt | **Live** — runs in the system-awareness cycle | **ABSORB** — unique, nothing else does this |
| 2 | **`emergency_halt` / `can_accept_action` / `resume`**: halted, concurrent-action cap, rate cap; persists a halt row | **Live** for the halt flag (the caps never fire — their counters are only fed by dead code) | **ABSORB** the halt; the caps come with it and start working once the gate registers actions |
| 3 | **Streaming monitor**: observe a completed act, score the laws, snapshot violations to `unified.governance_monitor_snapshots`, REDIRECT or BLOCK, stamp the acting user | **Live** (subscribed to TASK_COMPLETED) | **ABSORB** — becomes "record the judgement, snapshot on refusal" |
| 4 | `check_action_compliance` — 5-law scoring | Live, calls the constitution | Already the Constitution's |
| 5 | **pre/mid/post execution lifecycle**, `clear_action` | **Dead — 0 callers** | **DROP** |
| 6 | Compliance history + metrics | Live | **ABSORB** into `Constitution.judgments` / `metrics` |
| 7 | `set_user_context_provider` — the World Auth seam | Live, never wired | **ABSORB** — the Constitution already has `_user_settings_provider`; this is where user settings arrive |
| 8 | `CRITICAL_MODULES` (`core/governance/critical_modules.py`) | Live | **ABSORB** as a constant |

---

## 4. `core/governance/` — the rest

| Module | Capability | Live? | Decision |
|---|---|---|---|
| `singleton_constitution.py` | The 5 laws, keyword law scoring, drift assessment | Laws + drift **already absorbed**; file still imported by `runtime_governance` and `directive_system` | **DELETE** once those two re-point |
| `approval_requests.py` | The one owner of "a human said yes" | **Dead — 0 importers** | **DROP.** If human approval returns it is one field on a Judgment, not a module |
| `context_classifier.py` | Labels context items before governance, for human review clarity | **Dead — tests only** | **DROP** |
| `shadow_mode_coordinator.py` | **Shadow mode**: triggers fire and log but never block; false-positive / false-negative identification; trigger rates; threshold tuning | **Dead — tests only** | **DROP the module, ABSORB the idea**: an observe-only flag on the Constitution is exactly how we cut over safely (§9 step 3) |
| `governance_block_schema.py` | The META-memory record for a governance block; read by the coordinator and intrinsic motivation (13 refs) | **Live** | **KEEP AS IS** — a record format, not an authority |
| `critical_modules.py` | The protected-module list | Live | **ABSORB** into the Constitution (§3.8) |

---

## 5. `core/safety/`

| Module | Capability | Live? | Decision |
|---|---|---|---|
| `action_consequence.py` | `classify_action` (verb × target → action class + irreversibility), `target_sensitivity`, per-tool declared consequences, payload patterns | **Live — the Constitution already uses it** | **ABSORB** (move in, so the dependency dies with the folder) |
| `action_contract.py` | `ActionClass` enum, irreversibility ordering | Enum live | **ABSORB the enum + ordering.** DROP the contract itself (no producer) |
| `commitment_contracts.py` | Pre/post commitment verification, parameter tampering detection (±5% on numerics), violation rates by category | Imported by `tool_registry`, **never called** | **DROP.** The ±5% tamper check is the only idea worth a note |
| `multi_level_prompts.py` | System / meta / action-level safety PROMPTS for a language model | Constructed by the coordinator, LLM-era | **DROP** — model-free substrate |

---

## 6. `core/security/` — the rest

| Module | Capability | Live? | Decision |
|---|---|---|---|
| `input_validation.py` | SQL injection on sink parameters only, path traversal, external-only rate limit, fail-closed, stats | **Live** (§1.2), has its own experiment | **ABSORB WHOLE** — small, verified, and the only input-safety capability |
| `asi_safety.py` | ASI risk scoring, introspection, "emergent meta-cognition", self-evolving safety rules | Called by `safety_framework`; **verdict never read** | **DROP** — LLM-era |
| `threat_intelligence.py` | IP reputation via AbuseIPDB / OTX / VirusTotal, internal threat list, cache, persistence | Only `start_security_systems.py` + a manual test; **goes online** | **DROP from the substrate** — this is system/external security |
| `active_defense_types.py` | Types for blocking and real-time defense | Used only by `security_tools.py` | **DROP** with the tools decision |
| `malware_sandbox.py` | Static + dynamic file analysis; **executes suspect files on the host** | `security_tools` + a health entry | **DROP** — the world's Quarantine replaces it and never executes |
| `content_security.py` | XSS sanitisation, email / URL / filename validation, `scan_content` | `security_tools` + health | **DROP**; the useful signals overlap §1.4 |
| `security_types.py` | `SecurityLevel` (PUBLIC→TOP_SECRET), `ThreatType`, `AlertSeverity`, `Priority` | `__init__` + within `core/security/` only | **DROP — CONFIRMED 2026-09-17.** Not absorbed, and nothing is lost: it is a bare enum with **no classifier**. Nothing derives a level from a target, and its three aliased vocabularies (`LOW=public`, `PERMISSIVE=public`, …) are three namings of one unused scale. The severity the substrate actually needs is **already declared** on all 55 governance triggers (§7) — absorbing an empty enum would have added a vocabulary while the real gradation stayed discarded |
| `security_training_pipeline.py` | Adversarial testing, attack scenarios, red-team simulation, "train a security model" | Built at boot by `main.py`, **never called** | **DROP** — and red-team work is paused pending the Anthropic cyber security application |
| `_disabled/`, `start_security_systems.py`, `signing_key.pem`, audit receipt JSONs | Archived perimeter, a launcher, a private key nothing reads | Dead | **DROP** |

---

## 7. What the Constitution gains: SEVERITY

Today it returns a verdict and a reason. Everything not refused looks identical —
`rm` on a scratch file and a write to a config both come out "allow".

**CORRECTION (2026-09-17): the substrate ALREADY PERCEIVES SEVERITY. This is a
wiring gap, not a model to build.**

Every one of the 55 triggers in `config/governance_triggers.json` declares it:

| Field | Values in the live config |
|---|---|
| `impact_level` | CRITICAL 18 · HIGH 20 · MEDIUM 11 · LOW 4 · VARIES_BY_PARAM 2 |
| `safety_risk` | CRITICAL 28 · HIGH 12 · MODERATE 9 · LOW 4 · VARIES_BY_PARAM 2 |
| `irreversibility_class` | IRREVERSIBLE 10 · MOSTLY_IRREVERSIBLE 5 · PARTIALLY_REVERSIBLE 19 · MOSTLY_REVERSIBLE 2 · FULLY_REVERSIBLE 19 |
| `escalation_category` | safety · security · operational, plus a per-trigger tail |

**And `target_sensitivity` throws all four away.** It finds the matching trigger
and returns `trigger["trigger_id"]` — a bare string. The constitution learns that
`credential_file_read` matched and never learns that the same trigger says
`impact CRITICAL · risk CRITICAL · PARTIALLY_REVERSIBLE · escalation security`.

This is why `security_types.py` is DROP rather than ABSORB (§6): wiring an empty
`SecurityLevel` enum would have added a second vocabulary while the real,
populated one stayed discarded on every judgement.

**It also explains a live defect.** `~/.ssh/id_rsa` earned a REDIRECT into a
recovery directory — while its own trigger declares `PARTIALLY_REVERSIBLE`. The
config already records that a credential is re-obtainable by re-issuing it, which
is exactly the test that makes a recovery copy pointless. The redirect existed
because the constitution could not see the field that made it unnecessary.

**The work, then:**

1. `target_sensitivity` returns the trigger's DECLARED severity, not just its id.
2. `Judgment` carries it, so `allow` stops being flat.
3. Law 3's sensitive-target branch reads `irreversibility_class`: re-obtainable
   (`PARTIALLY_/MOSTLY_/FULLY_REVERSIBLE`) means destroy it — recovery is
   re-fetching from the authority, which is better than a stale hidden copy.

**Honest gaps in the declared data**, to be computed rather than read:
- `VARIES_BY_PARAM` (2 triggers in each severity field) genuinely depends on the
  arguments and must be derived, not looked up.
- `escalation_category` has ~30 one-off values that are labels, not a vocabulary;
  only `safety` / `security` / `operational` are shared.

## 8. What the Constitution gains: the RECORD

- **Judgement handed back to the caller** (`Judgment.to_dict()` already exists) so the agent reads what its act was judged to be, instead of it being a log line.
- **`unified.safety_assessments`**: a row per judgement, closed by the outcome that followed. Same tables, no DB changes. This is the only place the substrate can later ask whether its own judgements were right — the seam that lets thresholds be learned instead of declared.
- **Snapshot on refusal** → `unified.governance_monitor_snapshots`, with the acting user stamped.

## 9. Order of work

1. **Absorb** §7 severity, §8 record, §6.1 input validation, §5 consequence, §3.1 tamper + §3.2 halt, §2 rules-as-policy. The Constitution becomes capability-complete while the old gate still runs.
2. **Wire** the tool gate and the task gate to `Constitution.judge`, with `verify_intent` on the task, and make the coordinator ACT on REDIRECT (run the named alternative) and REPLAN (goal back to planning). Until something consumes them, two of four verdicts are labels.
3. **Observe-only cutover** (the one idea worth keeping from shadow mode): run both for a real boot, record where the verdicts disagree, and only then switch enforcement over.
4. **Delete**, with every consumer cleaned: `core/security/` entire, `core/safety/` except what moved, `governance_triggers.py` + its JSON (after the rules move), `singleton_constitution.py`, `runtime_governance.py`, `approval_requests.py`, `context_classifier.py`, `shadow_mode_coordinator.py`, `critical_modules.py`, `start_security_systems.py`.
5. **Re-run** CONSTITUTION-01/02 and OPERATOR-REMOVAL-01 against a live boot and confirm `judged` is a real number, plus the benchmark rows in `docs/research/BENCHMARKS.md`.

## 10. Consumers that must be re-pointed before deletion

`tool_registry` (gate + `record_outcome`), coordinator (task gate + `record_outcome`),
`memory_agent.validate_governance_compliance`, `directive_system`,
`experience_evaluator`, `health_monitor` (component entries + `_check_security_health`
+ constitution status), `main.py` (governance system + training pipeline),
`guardian/supervisor.py`, `quantum/asi_quantum_safety.py`, `chaos` scenarios,
and the governance test suites.
