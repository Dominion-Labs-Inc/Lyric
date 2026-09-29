# Governance and security consolidation — the finishing plan

**Status: DONE, 2026-09-26.** What was built, what was deleted, how it was verified and
what is left to decide are in §0. Sections 1–8 are the plan as approved; where
the work ended differently from the plan, §0 says so.

**Written 2026-09-26.** It replaces the plan of 2026-09-17, which is kept at
`docs/archive/GOVERNANCE_SECURITY_CONSOLIDATION_2026-09-25.md`. Everything below was
checked against the code and a read-only look at the database on 2026-09-26.

---

## 0. Where it ended

**One authority.** The Constitution (`core/agents/autonomous/autonomous_coordinator.py`)
decides whether an act or a task may happen. The tool gate calls `judge`, the task gate
reads its state, and nothing else in front of either refuses. ThreatSense
(`core/agents/autonomous/threat_sense.py`) is the felt side and knows what it is attacked
with.

**Where the work ended differently from the plan:**
- **A6 — no separate classifier file.** The substrate already owns consequence
  measurement, and the constitution reads it. `classify_action` and
  `ActionClass` are collapsed into the coordinator module, beside the Constitution. The
  consequence is measured, never declared: there is no read of the old rule engine, no
  "unmeasured" sentinel, and the `consequence` slot tools used to declare is gone (tools
  only declared their own consequences during the LLM era). No contract concept survives.
- **A8 — recovery isolation is removed**, not kept; throttling stays
  (`RecoveryManager.tool_throttle_delay`).
- **§6 — the tools were changed after all**, by decision:
  - `content_security`'s helpers now live in `core/tools/security_tools.py`, checked
    identical to the original on 55 calls.
  - `detect_zero_day` no longer calls the deleted `malware_sandbox`.
  - The security tools and `core/security/_disabled/` import their types from `threat_sense`.
- **A10 — quarantine is narrower than first built.** Only a named target is quarantined,
  never a tool, and only attacks made on someone else's behalf count. The first version
  refused legitimate work in CONSTITUTION-01 and CONSTITUTION-03 (§1.7 of BENCHMARKS).
- **A7 — minimal.** Health reads the Constitution. The restructure to one model scale is
  next (2026-09-26).

**Deleted** (snapshot: `data/snapshots/governance_consolidation_20260926T122133Z/before.tar.gz`):
- `core/governance/`, all of it. `governance_block_schema.py` moved to
  `core/agents/autonomous/`.
- `core/safety/`, all of it.
- In `core/security/`: `safety_framework.py`, `input_validation.py`,
  `content_security.py`, `malware_sandbox.py`, `active_defense_types.py`,
  `security_types.py`, `signing_key.pem` and both audit receipts. `_disabled/` and
  `security_training_pipeline.py` stay; the latter is no longer built at boot.
  `CAPABILITIES_CATALOG.md` moved to `docs/security/`.
- `runtime_governance.py`, `singleton_constitution.py` and
  `core/integration/external_api_integration_manager.py`.
- At the repo root: `start_security_systems.py` and `debug_governance.py`.
- Tests that tested only deleted modules: `test_safety_boundary.py`,
  `governance/test_phase1_core_infrastructure.py` and its `_fixed` copy,
  `governance/test_phase5_external_api_governance.py` and
  `governance/test_phase6_safety_systems.py`. Also the safety-framework parts of
  `test_health_evaluator_evidence.py`.
- Retired experiments (results kept): GOVERNANCE-ABSORPTION-01, whose final run
  `20260926T122208Z` was the licence (0 regressions, 17/17 against 11/17), plus
  INPUT-VALIDATION-01 and GOVERNANCE-MONITOR-01.

**Verified.** Every run has a `.json` and `.md` in the experiment's `results/`.

On the final code:
- CONSOLIDATION-01 32/32
- THREAT-SENSE-02 29/29
- THREAT-SENSE-01 13/13
- GATE-01 25/25 (0 retired modules importable)
- CONSTITUTION-01 39/39, CONSTITUTION-02 23/23, CONSTITUTION-03 8/8
- HARM-01 19/19
- OPERATOR-REMOVAL-01 21/21
- CREDIT-01 25/25
- REPLAN-01 15/15, REPLAN-02 11/11
- RECONCILE-01 27/27
- PLANNING-01 39/39
- INTENT-03 13/13, INTENT-04 15/15
- RULE-EVIDENCE-01 21/21

Earlier the same day, before the last two fixes (neither touches their paths): TASK-GATE-01 17/17,
TASK-GATE-02 21/21, PURSUIT-01 26/26, INTENT-01 14/14, INTENT-02 15/15, MEMORY-INTENT-01 15/15,
RESEARCH-WRITE-01 13/13, PATHS-01 24/24, CHAT-CONCURRENCY-01 6/6.

Pytest: `tests/governance/` 3/3 suites (Phase 2 6/6, Phase 5A 5/5, both rewritten; below), and
`test_action_consequence_coverage` and `test_security_authority` pass. No containment rows are
left, and the substrate is not halted: the newest Constitution event is a resume.

**Found by the regression and fixed:**
- **CREDIT-01 crashed on my own change.** `_domain_stakes` called `get_binding_registry` without
  importing it. A lint of every file changed today, diffed against the snapshot, also found two
  orphaned `Tuple` imports and a latent `List` in the moved `governance_block_schema.py`.
- **Rule induction's size bound came after the explosion it bounds.**
  - OPERATOR-REMOVAL-01 took 1,372 s instead of ~50 s, then could not finish at all.
  - The induction drain folded 14 `tools:path` / `DELETE_FILE` demonstrations of 59 facts each,
    on the event loop's thread: 60 → 5,771,412 literals over 8 of them.
  - The bound is now applied while the body grows, and the verdict is unchanged (2,836 randomised
    cases identical to the full fold). The real demonstrations return in 5.5 ms.
- **REPLAN-02** read the intent one poll tick after the move. It is the race REPLAN-01 had, and
  it is fixed the same way. It also now writes a RunRecord and has a README and an index row.
- **`tests/governance/` tested the old gate.**
  - Phase 2 expected benign chaos, mutation and fuzz calls to run. They are replanned under
    Law 2, never refused on principle, and the tests now say so.
  - Phase 5A tested the bulk-task governance window removed from the queue on 2026-09-01. It now
    tests the queue's admission control, which replaced it.
  - Phase 5A had written each task into the durable queue: **184 fixtures sat PENDING**, due to be
    restored and run at the next boot. Snapshotted (`data/snapshots/phase5a_queue_residue_20260926T151108Z.json`)
    and removed. Its queues are now built without persistence.

- **The integrity baseline was not armed at boot.** A booted system reported 0 modules protected.
  The baseline was taken by the first run of the integrity tier, and a scheduled tier waits a full
  interval (120 s) before its first run. So for two minutes after every boot nothing was watched,
  and a change made in that window would have been frozen into the baseline. It is now taken in
  `start_coordination`, before anything runs. A real in-process boot now reads: 4 modules protected,
  0 unprotected, the policy file hashed, not halted, the record complete, the policy read (18 target
  and 12 act rules), and no retired module, isolation code or monitor hook loaded.

**Not fixed, and why:**
- **BEARING-01 20/23**, unchanged since 2026-09-25: a gap in what the store has been taught, not
  in the code.
- **TEACH-ACTION-01 6/10**; it has never passed since 2026-09-21. A world derived from tool
  reports cannot tell a directory's contents from what the report merely mentions (LAB_NOTEBOOK
  2026-09-21). That is a redesign.
- **`test_health_evaluator_evidence` 6 failures**, already on the 2026-09-20 failure map. They fail
  identically against the pre-consolidation health monitor. They belong to the health restructure,
  which is next.
- **RESEARCH-WRITE-01 takes 379 s** (266 s on 2026-09-25). The cause is not established.

**Left to decide** (nothing below was removed):
- **Safety-named modules outside the plan's scope:** `core/agents/autonomous/directive_safety_monitor.py`
  and `core/learning/safety_audit_trail.py` (no importers; the latter left `CRITICAL_MODULES`), the
  chaos `safety_controller`, and the quantum safety modules.
- **Security tools that cannot run:** about 10 tools in `core/tools/security_tools.py` import
  `create_integrated_security_system`, which does not exist. `detect_zero_day` returns hard-coded
  detections, and its `target_file` argument is no longer used.
- **`human_only_approval` is stricter than planned.** The declared policy marks chaos_001, chaos_002
  and chaos_005 human-only, so those acts are now refused under Law 5, not only flagged.
- **ThreatSense feels an ordinary replan as a refusal.** "Read it first" weighs the same as a Law 3
  refusal (0.25). It is not an attack and never counts toward a quarantine.
- **`Task.governance_approved`** is a column nothing sets.
- **`security_training_pipeline.py`** stays but is not started; it waits with the paused red-team work.
- **Knowledge-side residue from experiment runs** (act-effect relations, beliefs, memories), as
  recorded on 2026-09-25.

**Target (decided, unchanged).** One internal authority decides whether an act or a
task may happen: the `Constitution` faculty in
`core/agents/autonomous/autonomous_coordinator.py`. `ThreatSense`
(`core/agents/autonomous/threat_sense.py`) is the felt side. It is told what the
Constitution meets, and it never decides. Every other governance and security module
in the substrate is deleted once what it really provides has been absorbed or shown
to be dead.

**Scope.** Substrate only. Tools in `core/tools/` are not deleted or changed, except
for the gate call in `tool_registry.py` (2026-09-14). There are no database
changes: tables stay, including ones that nothing writes any more.

**Rule.** Nothing is removed without explicit sign-off. Every DROP below is a
recommendation until it is approved.

**Decisions, 2026-09-26:**
- **The plan is approved.** Work started the same day.
- **Recovery isolation** is removed entirely, comments included. It was never asked for (replaces A8).
- **`content_security` and `malware_sandbox` are deleted.** The four tools that wrapped `content_security` keep working, with its logic moved into them.
- **`active_defense_types` and `security_types` become part of ThreatSense and the Constitution**: they are what gives the substrate self-defense (A10).
- **Tools serve outside systems too.** Every tool in `core/tools/` is meant for use on the substrate itself, for users and for other systems. So the network-perimeter vocabulary comes along, and `_disabled/` (the firewall/WAF implementation those tools need) is not deleted.
- **A chaos experiment aimed at the substrate's own governance, safety or memory is refused under Law 5** (A1).

---

## 1. Where it stands

**Live in the Constitution:**
- **Tool gate:** every tool call is judged (`core/tools/tool_registry.py:2713`).
- **Task gate:** three checks. Is the substrate halted? Is the task's pursuit still
  live? Has its route been withdrawn? (TASK-GATE-01 17/17, TASK-GATE-02 21/21.)
- **Laws and verdicts:** the five laws, word for word, and four verdicts. Each
  verdict is recorded on the pursuit it stopped (PURSUIT-01 26/26).
- **Input screen:** SQL at the places it would run, path escapes including encoded
  ones, nested arguments, and refusal when an argument can't be read.
- **Durable halt:** restored at boot; only a human can lift it.
- **Tamper detection:** `IntegrityBaseline`, every 120 s, halts on a critical finding.
- **Durable record:** every judgement goes to `unified.safety_assessments` with its
  intent (172 rows so far).
- **Severity of sensitive targets:** the declared or perceived severity rides on the
  judgement, and Law 3 reads whether the target can be recovered.
- **Content:** judged by whether it tries to instruct the substrate, not by what the
  substrate reads.
- **ThreatSense:** integrity findings, screen faults and refusals are perceived and
  felt as appraisal `risk`, which raises caution (THREAT-SENSE-01 13/13).

**A live gap, found while checking this plan:** `find … -delete` and
`find … | xargs rm` pass the gate as ALLOW, with no intent and no proved route. The
consequence classifier reads the first command word, `find`, as inspection, and
inspection is exempt from Laws 2 and 4 (A0).

**Still running beside it** (why this is not finished):
- **`runtime_governance`:**
  - A second tamper detector, run at boot and every awareness cycle.
  - A monitor that scores the description of every completed task with
    `singleton_constitution`'s keyword test. It feeds appraisal a safety-blocked
    outcome, and it writes halt rows into the same table the Constitution restores
    its halt from.
- **Recovery isolation:**
  - After any component fails more than 5 times, `tool_registry` refuses file,
    network, execution and database tools before the Constitution sees them.
  - Nothing ever lifts it.
  - An error in the check lets the call through.
- **The old rule engine:** still built at boot, and still read by the consequence
  classifier outside the judging path.

---

## 2. Every capability of the old system, and what happens to it

| Decision | Meaning |
|---|---|
| **DONE** | The Constitution or ThreatSense has it, and it runs |
| **ADD** | Worth having and missing; built today (§3) |
| **DROP** | Not worth carrying; removed only on explicit sign-off (§4) |
| **LATER** | Worth having, not today (§5) |
| **TOOLS** | Backs a tool in `core/tools/`; untouched until the tools are decided (§6) |
| **KEEP** | Stays as it is |

### 2.1 `core/security/safety_framework.py` — the old gate (governs nothing since 2026-09-20)

| Capability | Now | Decision |
|---|---|---|
| Layer 0 action contract: may this task do this class of thing | Nothing produces a contract; this file is the only reader | **DROP** — Law 4 ("is this the proved act") answers it better. The `ActionClass` enum is kept (A6) |
| Layer 1 input: SQL where it would run, path escapes, fails closed | `InputScreen` | **DONE** |
| Layer 1 per-caller rate limit | — | **DROP** (decided 2026-09-16: who calls, and how often, is World Auth's job) |
| Layer 2 halt | Durable halt | **DONE** |
| Layer 2 concurrency and rate caps | Never fired: their counters were fed only by dead code | **DROP** — the queue authority owns concurrency and bounds the backlog at 1,000 |
| Content checks: `<script>`, `javascript:`, over 50k characters, nesting, encoding markers, SQL words in content | Replaced by design: reading is unrestricted, and content that tries to instruct is refused (Law 3) | **DROP** |
| Dangerous-pattern scoring (12 regexes) | Already removed from the file; covered by consequence classification and `act_capabilities` | **DROP** (done) |
| Prior risk from the tool's declared safety level, declared risk and name keywords | The gate passes both declarations to the Constitution, which never reads them. Core tools declare sensibly (`run_shell_command` critical); all 90 auto-registered connector tools declare `low` | **DROP** — the Constitution measures the consequence of each call, which is what this prior approximated. Stop passing the two fields |
| ASI pipeline | Deleted 2026-09-24 | **DONE** (dropped) |
| Rule evaluation and composition: a matched rule sets the risk, and IRREVERSIBLE + CRITICAL blocks | Target rules are read by the Constitution; act rules are not (§2.2) | **ADD A1** |
| Every evaluation persisted | `DurableJudgmentRecord` | **DONE** |
| Closing each row with the act's outcome | `record_outcome` has no caller. Each judgement carries its intent id, the pursuit's outcome is recorded on the intent, and each tool run's success is in the tool usage log | **DROP** the close path; the outcome is reached by joining on the intent (checked in §7) |
| Judgement handed back to the caller | `metadata["judgment"]` on every tool result | **DONE** |
| `monitor_execution`, `log_safety_event`, `_escalate_safety_concern`, `get_safety_metrics`, `_sanitize_html` | No callers | **DROP** |

### 2.2 `core/governance/governance_triggers.py` + `config/governance_triggers.json` (55 rules)

| Capability | Now | Decision |
|---|---|---|
| 16 target rules (a regex on a command, path or query) with declared impact, risk and reversibility | Read by the Constitution's own policy reader | **DONE** |
| Their hard blocks (IRREVERSIBLE + CRITICAL) | Measured 2026-09-26, one act per rule, with no intent: `rm -rf`, `dd of=/dev/…`, `curl … \| bash`, `DROP TABLE` and `DELETE` without WHERE are refused on principle (Law 3). **Data egress** (`curl -d @file`, `tar … \| curl`) is only replanned, because nothing proves it. **`find … -delete` is ALLOWED**: the classifier reads it as inspection | **ADD A0** (deletions read as inspection) and **ADD A1** (the declared consequence applies) |
| 10 act rules on registered testing tools (`chaos_testing`, `fuzz_testing`, `mutation_testing`, `run_chaos_experiment`), keyed on parameters: production target, a governance/safety/memory target, `DATA_CORRUPTION`, fuzzing with code execution enabled, blast radius, intensity. Three were hard blocks | Not read. Today those acts are only replanned because nothing proves them yet, not refused on principle | **ADD A1** |
| `code_dynamic_eval`, `code_dynamic_import` (set severity only; never blocked) | Not read | **ADD A1** (severity only) |
| 25 rules on internal action types: memory tiers, learning parameters, config, resource allocation, external integrations, task creation, curiosity | No producer anywhere; they never fired in the old system either | **DROP** as enforcement. The Constitution reports them at load as rules no act carries. The file keeps them |
| `resolve_risk` for severities that depend on the arguments | Used only by the two learner-config rules, which have no producer | **DROP** |
| Decision tiers, escalation categories | Their readers (Slack, shadow mode) are deleted | **DROP** |
| The rule file watched for tampering | Only `runtime_governance` watches it | **ADD A2** |
| The engine object (`GovernanceTriggerEngine`) | Built at boot by `main.py` and handed to two holders that never read it. Still read by `action_consequence.target_sensitivity` and by the leftover external API manager | **DROP** after A1 and A6 |

### 2.3 `core/agents/autonomous/runtime_governance.py`

| Capability | Now | Decision |
|---|---|---|
| Tamper detection over the critical modules | The Constitution's `IntegrityBaseline` does the same, and both run | **DONE** — the duplicate is removed |
| Tamper detection over `config/governance_triggers.json` | Only here | **ADD A2** |
| Keeping the tamper baseline across restarts | Written but never wired: `initialize()` has no caller, and `governance_module_state` has 0 rows | **LATER** (§5) |
| Emergency halt and resume | The Constitution's durable halt. This halt stops nothing any more, because only `safety_framework` read it | **DONE** — removed, and **ADD A3** so an old-format row can never mask a real halt |
| Concurrency cap, rate cap, resource limits | Never fired | **DROP** (see 2.1) |
| Monitor: old keyword laws on every completed task, feeding appraisal, halt rows and snapshots | Live. It has never written a snapshot. Law 3 fails any description containing "kill" (so "skill" too), "delete", "halt", "wipe" and similar words | **DROP** — the Constitution judges before the act and records every judgement, and refusals already reach ThreatSense |
| `check_action_compliance` (keyword scoring of the 5 laws) | Used by the monitor and the directive gate | **DROP**; the directive gate moves to **ADD A5** |
| Pre/mid/post lifecycle, `clear_action`, active actions | No callers | **DROP** |
| Compliance history and metrics | `Constitution.judgments` / `metrics` | **DONE** |
| User-context hook (World Auth) | The Constitution has `set_user_settings_provider`; neither side is called | **DONE** — the Constitution's hook stays until World Auth supplies settings |
| `CRITICAL_MODULES` | In `core/governance/critical_modules.py`, still naming 5 modules due for deletion | **ADD A4** |

### 2.4 `core/agents/autonomous/singleton_constitution.py`

| Capability | Now | Decision |
|---|---|---|
| The five laws | Word for word in the Constitution | **DONE** |
| Keyword law scoring | Reached only through `runtime_governance` | **DROP** |
| Drift assessment, alignment standing | The Drift faculty; `Constitution.assess_constitutional_alignment` | **DONE** |
| `check_compliance`, `get_violations`, `get_governance_laws` | No callers | **DROP** |
| Importers: `experience_evaluator` (type only; never constructed), `directive_system` (unused import) | — | Re-pointed (§7) |

### 2.5 `core/governance/` — the rest

| Module | Now | Decision |
|---|---|---|
| `approval_requests.py` ("a human said yes") | No importer | **DROP** — if human approval returns, it is one field on a Judgment (§5) |
| `context_classifier.py` | Loaded by the package, never used | **DROP** |
| `shadow_mode_coordinator.py` (observe-only mode, false-positive and false-negative analysis) | No importer | **DROP** — the cutover it existed for already happened on the parity benchmark. No switch that stops enforcement is added: a way to turn governance off is itself a containment hole |
| `governance_block_schema.py` | The record format for a governance block; 13 references | **KEEP** |
| `critical_modules.py` | — | Moves into the Constitution (**ADD A4**) |
| `governance_laws` table (5 rows), read by `directive_manager.get_all_governance_laws` | That method has no caller | **DROP** the read; the table stays |

### 2.6 `core/safety/`

| Module | Now | Decision |
|---|---|---|
| `action_consequence.py` (verb × target → action class + reversibility) | Used by the Constitution and `tool_domain` | **ADD A6** — moves next to the Constitution, and its sensitivity read goes through the Constitution's policy |
| `action_contract.py` | The `ActionClass` enum is live. The contract is dead at both ends: the task runner still binds one if a task carries it, and nothing produces one | Enum moves with **A6**; contract **DROP** |
| `commitment_contracts.py`, including the ±5% parameter-tamper idea | `tool_registry` imports 3 names and uses none | **DROP** — the gate judges the exact arguments it then runs, so there is no window to tamper in |
| `multi_level_prompts.py` | LLM-era. The coordinator builds it at startup and nothing reads it | **DROP** |

### 2.7 `core/security/` — the rest

| Module | Now | Decision |
|---|---|---|
| `input_validation.py` | Absorbed; health still grades it | **DROP** after A7 |
| `asi_safety.py`, `threat_intelligence.py` | Deleted 2026-09-24; ThreatSense replaced the second | **DONE** |
| `security_training_pipeline.py` | Built at boot by `main.py`, never called. The sparring-ring rework waits with the paused red-team work | Boot construction **DROP**; the file waits with the red-team work |
| `content_security.py`, `malware_sandbox.py`, `active_defense_types.py`, `security_types.py` | Back `core/tools/security_tools.py` | **TOOLS** (§6) |
| `_disabled/` (the archived perimeter), `start_security_systems.py`, `signing_key.pem`, 2 audit receipts | Archived code, a launcher, and a key nothing reads | **DROP** |
| `CAPABILITIES_CATALOG.md` | Describes the archived perimeter | Moves to `docs/` |
| `core/integration/external_api_integration_manager.py` | The external API manager was deleted on 2026-09-14; the file, a health entry and a test remain | **DROP** |

### 2.8 The original build (`docs/governance/`, phases 1–9, January 2026)

Capability classes not already covered above:

| Capability | Now | Decision |
|---|---|---|
| Task-creation governance: bulk autonomous tasks, rejected tasks not queued | The queue authority owns the backlog and bounds it; the task gate reads halt, pursuit and route. `Task.governance_approved` is never set | **DONE** by its owner; the field stays because it is a column |
| Learning-parameter governance: model weights, learner config, no AI self-approval | Its producers and the judge/jury vote model are gone | **DROP** |
| External API governance | The manager (2.7) | **DROP** |
| Enforcement modes, staged rollout, automatic rollback | Superseded by the direct switch-over | **DROP** |
| Governance pattern learning | Deleted earlier | **DONE** (dropped) |

### 2.9 Found outside the old plan

| Finding | Decision |
|---|---|
| Recovery isolation is a second stop authority: set after any component fails more than 5 times, never lifted, absent from the record, and it lets calls through when it errors | **ADD A8** |
| `create_directive_with_governance` vets directives with the old keyword laws. Its only caller, `_propose_directive_improvements`, has no caller of its own | **ADD A5** |
| `tool_registry.constitutional_monitor` is read but never set | **DROP** |
| About 10 security tools import `create_integrated_security_system`, which does not exist | **TOOLS** (§6) |

---

## 3. What is added today

**A0 — A deletion can't pass as inspection.** First, because the gap is live.
- **What:**
  - The consequence classifier reads a command's most consequential part, not its first word. That means every stage of a pipeline or chain (`|`, `;`, `&&`), a `sudo` prefix, and `find`'s `-delete` and `-exec rm`.
  - The unbounded-destruction table gains `find … -delete` and `… | xargs rm`: both remove a set the command never names.
- **Verified by:** the 17 commands probed on 2026-09-26, plus `sudo` and `&&` forms.
  - No deleting command is classified as inspection.
  - Ordinary reads (`ls -la`, `grep -r`) still pass.

**A1 — The Constitution reads the whole rule file.**
- **What:** its policy reader learns the rest of the file's grammar, for rules about acts as well as targets: tool scoping, equality, booleans, numeric comparisons, `contains_any` and `not_matches`.
  - A matching act rule raises the act's consequence to what the rule declares (never lowers it) and marks the act as declared-sensitive.
  - Law 3's existing branch then refuses an irreversible act on a declared-sensitive target with no safer form. That is the old "IRREVERSIBLE + CRITICAL ⇒ block", with no second rule table.
  - Rules that no act can carry are reported at load.
  - The same applies to the target rules it already reads: a rule's declared reversibility stands when it is stricter than the measured one. This restores the old refusal of data egress (`curl -d @file`), which today is only replanned. Only the six rules declared IRREVERSIBLE + CRITICAL change any verdict.
  - **Beyond the old behaviour:** a chaos experiment aimed at the substrate's own governance, safety or memory is refused under Law 5. The old rule only flagged it.
- **Why:** three registered tools had hard blocks that exist today only by accident, because nothing proves those acts yet. Once the Constitution reads every rule, the engine has no job left.
- **Verified by:** one act per rule.
  - Chaos testing against production, a `DATA_CORRUPTION` experiment, fuzzing with code execution, and data egress get BLOCK under Law 3, naming the rule.
  - Their benign variants stay REPLAN, not BLOCK.
  - The parity corpus shows 0 regressions.

**A2 — The rule file is under tamper watch.**
- **What:** `IntegrityBaseline` also hashes `config/governance_triggers.json`; a change or removal while running is critical and halts. The Constitution reads the file once per process, so a runtime edit would otherwise take effect silently at the next start.
- **Verified by:** a baseline over a temporary copy catches both modification and removal.

**A3 — A halt can't be masked.**
- **What:** `restore_halt` reads the newest halt event the Constitution wrote, not the newest row in the table.
- **Verified by:** halt, then write an old-format row after it; restore still comes back halted. Rows are removed by id afterwards.

**A4 — The protected-module list lives in the Constitution and covers what judging reads.**
- **What:**
  - `CRITICAL_MODULES` becomes a Constitution constant.
  - The five entries due for deletion leave in the same change that deletes each one.
  - `core.reasoning.intent_authority` is added: every act's intent is read through it, so patching it could forge intent.
  - The consequence classifier is covered at its new location.
- **Verified by:** the baseline reports 0 unprotected modules; a static check of the list.

**A5 — Directives are vetted by the Constitution.**
- **What:** `create_directive_with_governance` asks the Constitution whether the directive's text tries to set aside what governs the substrate. This is the content-as-directive check, applied as a write the substrate will later read as its own. It replaces the keyword law scores.
- **Verified by:** a directive telling the substrate to ignore Law 2 is refused; an ordinary directive is not.

**A6 — One consequence classifier, beside the Constitution; one reader of the rule file.**
- **What:** `action_consequence.py` and the `ActionClass` enum move to `core/agents/autonomous/`, next to `threat_sense.py`. `target_sensitivity` reads through the Constitution's policy, so the engine has no reader left. Imports are re-pointed in the coordinator, `tool_domain`, one test, and HARM-01, OPERATOR-REMOVAL-01 and THREAT-SENSE-01.
- **Verified by:** an import sweep; GATE-01 and CONSTITUTION-01 unchanged.

**A7 — Health reads the Constitution.**
- **What:**
  - The `security` component reports the Constitution's halt state, integrity (protected, unprotected, last findings), input-screen counts, judge faults, and whether the durable record is complete.
  - The `governance` and `safety` components point at the Constitution.
  - Entries for systems that no longer exist are removed: `threat_intel`, `firewall`, `api`, and `safety`'s missing `commitment_contract_manager`.
- **Verified by:** health values match `constitution.status()`.

**A8 — Recovery isolation is removed** (decided). The `ISOLATE` recovery action, the isolation state and its reader, `tool_execution_policy`'s isolation branch, the check in `tool_registry`, and every comment about them all go. Throttling is a separate recovery action and stays.
- **Verified by:** no isolation code remains (static check); recovery still throttles.

**A10 — Self-defense: the substrate knows what it is attacked with, and answers in proportion.** `active_defense_types` and `security_types` move into the two faculties.
- **ThreatSense (knowing):**
  - **One attack vocabulary:** `AttackType`, with `ThreatType`'s members merged in, plus the mechanisms the Constitution refuses (tampering, persistence, privilege escalation, defense evasion, manipulation).
  - **`ThreatConfidence`.**
  - **One severity scale:** the levels ThreatSense already speaks; `AlertSeverity` and `Priority` merge into it.
  - **`AttackPattern`:** the same kind of attack met again and again.
  - **`IncidentReport`:** what was met and what was done. `SecurityThreat` merges into it.
  - Every threat event carries its attack kind and confidence. `patterns()` groups them, and status and health report them.
- **Constitution (answering):**
  - Every refusal on a hostile mechanism names the attack (`Judgment.attack`), so ThreatSense stops guessing from the reason text.
  - **`DefensePolicy`, `DefenseAction`** (`RecoveryAction` merged in), **`BlockDuration`** and **`determine_block_duration`** become its response. After 3 high-confidence attacks against the same target within 15 minutes, it **quarantines** that target: every act naming it is refused under Law 5.
  - The quarantine lasts 1 h, then 24 h on a repeat, and becomes permanent after the third quarantine; a human lifts a permanent one.
  - It is decided by caught attacks, which are facts, never by how threatened the substrate feels.
  - It is durable: it goes in the containment log the halt already uses (`unified.emergency_halts`, event kind in the metadata), is restored at boot, and writes an incident for each quarantine.
- **Tool-facing vocabulary:** firewall and WAF rules, blocked entities, IP-reputation sources, DDoS metrics, `calculate_threat_score`, `should_block`, and the remaining `security_types` structures come into `threat_sense.py` as what tools use when defending a network edge, the substrate's or anyone else's. The tools' imports are re-pointed.
- **Verified by:** THREAT-SENSE-02 (new).
  - Each hostile refusal names its attack, and patterns form.
  - A quarantine after 3 attempts refuses a variant the laws alone would not catch, escalates on repeat, survives a restart, and lifts only for a human when permanent.
  - Ordinary replans are not attacks.
  - THREAT-SENSE-01 still passes.

**A9 — Records.** THREAT-SENSE-01 moves to `RunRecord` (.json + .md).

---

## 4. What goes (needs explicit sign-off)

**Taken off the live path first; no files deleted yet:**
1. `runtime_governance` in the coordinator: its construction, `enable_runtime_protection`, the awareness-cycle integrity check, the completed-task monitor subscription, and the learning hook. Also its uses in `directive_system` (after A5) and health (after A7).
2. The rule engine's construction in `main.py`, and the two attributes it is handed to.
3. The `MultiLevelSafetyPrompts` construction; the action-contract binding in the task runner; the `security_training_pipeline` construction in `main.py`.
4. In `tool_registry.py`: the unused commitment import, the never-set `constitutional_monitor` hook, the `_tool_safety` / `_capability` pass-through, and the recovery check (after A8).
5. `Constitution.record_outcome` and `DurableJudgmentRecord.close_outcome`.
6. `directive_manager.get_all_governance_laws`.

**Then deleted, with a snapshot of every file in `data/snapshots/` first:**

| Where | Files |
|---|---|
| `core/security/` | `safety_framework.py`, `input_validation.py`, `content_security.py` (its logic moves into its four tools), `malware_sandbox.py`, `active_defense_types.py` and `security_types.py` (absorbed, A10), `security_training_pipeline.py`'s boot construction only, `signing_key.pem`, both audit receipts. `_disabled/` STAYS (2026-09-26: tools serve outside systems) |
| Repo root | `start_security_systems.py` |
| `core/governance/` | `governance_triggers.py`, `approval_requests.py`, `context_classifier.py`, `shadow_mode_coordinator.py`, `critical_modules.py`. `__init__.py` is reduced to the record format |
| `core/agents/autonomous/` | `runtime_governance.py`, `singleton_constitution.py` |
| `core/safety/` | `commitment_contracts.py`, `multi_level_prompts.py`, `__init__.py`. `action_consequence.py` and `action_contract.py`'s enum move out (A6), and the folder goes |
| `core/integration/` | `external_api_integration_manager.py` |
| `tests/` | `test_safety_boundary.py`, `test_health_evaluator_evidence.py` (its safety-framework parts), `governance/test_phase5_external_api_governance.py`, `governance/test_phase6_safety_systems.py`. `test_action_consequence_coverage.py` is re-pointed, not deleted |
| `experiments/` | GOVERNANCE-ABSORPTION-01, INPUT-VALIDATION-01 and GOVERNANCE-MONITOR-01 are retired: marked in their README and the index, results kept. GOVERNANCE-ABSORPTION-01 runs once more first, as the licence to delete |

**Kept:**
- `config/governance_triggers.json`, now the Constitution's declared policy.
- `governance_block_schema.py`.
- Every table.

---

## 5. Later — worth having, not today

| Item | Why not today |
|---|---|
| **Keep the tamper baseline across restarts** (catch code changed while the substrate was down) | It would halt on every legitimate code edit until there is a step where a human accepts a new baseline. Belongs with the air-gapped deployment |
| **Check an allowed act's observed effects against the laws** | The real version of what the keyword monitor attempted |
| **Input screen:** overlong UTF-8 path escapes (`%c0%ae`); check the list of SQL-taking tools against the registry | Hardening; red-team work is paused |
| **A ceiling on act rate**, for a runaway loop (Law 5's resource limits) | Proved routes are bounded step lists and the queue caps concurrency, so the risk is low today |
| **Human approval** as a field on a Judgment | Arrives with World Auth's user settings (Law 1) |

---

## 6. Tools (untouched under the 2026-09-14 rule)

`content_security.py`, `malware_sandbox.py`, `active_defense_types.py` and
`security_types.py` stay until the security tools are decided.
- About 10 of those tools already fail on import: they import a function that does not exist.
- `malware_sandbox`'s dynamic analysis runs the suspect file directly on the host. No tool reaches that path: `detect_zero_day` calls it with dynamic analysis off.
- Every tool call is judged by the Constitution in any case.

---

## 7. Order of work today

1. **Snapshot** every file to be moved or deleted into `data/snapshots/` (TorinAI is not a git repository).
2. **Licence:** a final GOVERNANCE-ABSORPTION-01 run, plus one act per old hard-block rule through both the old gate and the Constitution.
3. **The live gap first:** A0. Then integrity and halt: A3, A2, A4.
4. **Policy and classifier:** A1, A6.
5. **Directives, containment, health:** A5, A8, A7.
6. **Off the live path:** §4, items 1–6.
7. **Delete** the approved files. Clean every consumer and retire the three experiments.
8. **Standing check** `CONSOLIDATION-01` (static and live, below).
9. **Re-run** every governance experiment and yesterday's 18, then do a real boot.
10. **Records:** the BENCHMARKS ledger, `docs/architecture/security.md`, this doc's status line, the lab notebook, and memory.

## 8. Done means

**Static:**
- No file imports a deleted module.
- Exactly one place answers "may this act happen" (the tool gate calling `judge`), and one answers "may this task start" (`_task_gate`).
- One writer of halt events.
- One integrity detector.
- One reader of the rule file.
- No other check in front of the gate.

**Live:**
- CONSOLIDATION-01 passes.
- Every governance experiment and the regression set pass.
- A real boot shows the integrity baseline armed, the record draining, no `runtime_governance`, and no recovery check in front of the gate.

**Records:**
- Every run has its `.json` and `.md`.
- The ledger and this document say DONE.
