# Security capabilities catalog — captured before the shield rebuild

Snapshot of EVERY capability in `core/security/` so nothing is lost when we delete the
system files and build the clean shield. Each file is tagged with how it should be handled.

Legend: **[DELETE→SHIELD]** old perimeter-system, rebuilt as the shield · **[KEEP]** load-bearing,
not a perimeter file · **[TOOL-BACKING]** implements agent tools in `core/tools/security_tools.py`
(deleting breaks those tools) · **[RELOCATE/REWORK]** capability moves to a new home per the layered plan.

---

## system_security.py  **[DELETE→SHIELD]**  (the primitives fold into the shield)
- SQL-injection validation, path-traversal validation (regex).
- In-memory rate limiting; in-memory IP blocklist (`block_ip`/`is_ip_blocked`); in-memory audit log.
- Password hash/verify (sha256+secrets), token generation, filename sanitization.

## controller.py — SecurityController  **[DELETE→SHIELD]**  (shield authority reborn)
- Request validation (rate-limit external; SQL-injection on SQL-sink params; path traversal).
- Request sanitization; authN (api_key/token DB lookup); authZ (RBAC DB join).
- Security-event + audit logging (+ Postgres persistence, degrades to in-memory).
- Finding system + **offline finding queue** (`data/security_finding_queue.json`) with retry drain.
- Auto-remediation (block IP, elevate level, tighten validation); threat-pattern analysis.
- Security levels/policies; coordinator finding delivery (`handle_security_finding`).

## firewall_manager.py — RealTimeFirewallManager  **[DELETE→SHIELD]**  (becomes OS enforcement)
- OS firewall rules: iptables/pf/nftables detection + dynamic rules via subprocess.
- block/unblock IP, block port, allow IP, flush all; drift-detection sync loop.
- Blocklist persistence (Postgres, optional); **test_mode dry-run**.

## threat_blocking.py — ThreatBlockingEngine  **[DELETE→SHIELD]**  (block/quarantine decisioning)
- Coordinated decision: whitelist/blacklist → (intel lookup) → threat score → firewall + WAF block.
- unblock, block country, rate-limit, expired-block cleanup, metrics.

## cloudflare_waf.py — CloudflareWAFManager  **[DELETE — ONLINE]**  (edge WAF; not the substrate's own boundary)
- Cloudflare API: block IP/country, rate-limit rules, custom WAF rules, zone lockdown, events.

## threat_intelligence.py — ThreatIntelligenceEngine  **[RELOCATE/REWORK → substrate faculty]**
- IP reputation aggregation: AbuseIPDB / VirusTotal / OTX / WHOIS  **(ONLINE — drop)**.
- Internal threat DB (local), cache, Postgres persistence, scoring/aggregation, notifications.
- → rebuilt offline as the substrate's felt threat-sense in the coordinator.

## malware_sandbox.py — MalwareSandbox  **[RELOCATE/REWORK → quarantine]**
- Static analysis: md5/sha256, `file` type, entropy, suspicious strings, embedded-URL extraction, signatures.
- **Dynamic analysis: executes the file on-host (temp-dir) — REMOVE (never run untrusted code).**
- Behavioral analysis, threat-level assessment, IOC extraction, recommendations, DB/memory persistence.

## security_audit_worker.py — SecurityAuditWorker  **[REMOVED from TorinAI 2026-09-14 → DHCM world factory security-audit agent]**
- 12 sub-audits: access control, data integrity, authentication, configuration, anomalies, file
  integrity (manifest hashing + authorized-drift), attack surface (listener enumeration by bind
  addr), tool permissions, log integrity, dependency security (`pip-audit`), active-defense
  coverage, database auth (`pg_hba` reach).
- Finding model + ActionContract; reconcile (open/re-open/auto-retire); compliance score.
- Critical escalation (failure_record/Slack/governance); remediation task creation; threat-intel
  enrichment + auto-block; finding query API; **coalesced** run; self-owned 120s loop.

## security_training_pipeline.py — SecurityTrainingPipeline  **[RELOCATE/REWORK → sparring training ground]**
- Attack scenarios, training examples, adversarial testing, red-team simulation, defense testing,
  train security model, statistics, export. → becomes where the substrate spars and actually improves.

## active_defense_types.py  **[KEEP — response vocabulary + TOOL-BACKING]**
- AttackType (15), DefenseAction (BLOCK_IP, **QUARANTINE**, RATE_LIMIT, CHALLENGE, ESCALATE, …),
  BlockDuration, BlockedEntity, ThreatConfidence, FirewallRule/WAFRule, DefensePolicy, DefenseMetrics;
  helpers `calculate_threat_score`/`should_block`/`determine_block_duration`.

## content_security.py  **[TOOL-BACKING]**  (used by security_tools.py)
- XSS sanitization, email/URL/filename validation, malicious-pattern detection, ContentSecurityScanner.

## digital_footprint.py  **[TOOL-BACKING — outward, online; NOT the shield]**
- External footprint scrubbing across 50+ platforms: crypto signing, pattern detection, search
  de-indexing, data-broker removal, archive scrubbing, DNS/WHOIS scrubbing, social nuking, CDN purge,
  credential rotation. (A separate outward capability, exposed as agent tools.)

## safety_framework.py  **[KEEP — load-bearing tool-safety gate; already model-free]**
- `evaluate_action` (contracts + content safety + risk + ASI structural + governance), action
  contracts, `record_outcome`, governance block. **Depended on by the coordinator's tool gate,
  memory_agent, service_locator, health — deleting it breaks tool execution + memory writes.**

## asi_safety.py — ASISafetyFramework  **[KEEP — safety family]**
- ASI safety levels/action types; **self-preservation rules** (relevant to the outline's
  "self-preservation within the laws"); action-safety assessment; improvement-area identification.
- EmergentMetaCognition (distilbert) — **OFF by default, non-load-bearing** (keep off for model-free).

## security_types.py  **[KEEP — shared vocabulary imported across the codebase]**
- Enums/dataclasses: SecurityLevel, ThreatType, ContentType, ValidationResult, AlertSeverity,
  RecoveryAction, Priority, AgentType, ContentCategory, SecurityContext, SecurityThreat, DigitalTrace,
  SwarmAgent, SecurityPolicy, SecurityMetrics.

## __init__.py  **[DELETE→SHIELD]**  (recompose as the shield's assembly)
- `create_integrated_security_system` (the dict "seam"), `get_integrated_security_system`, exports.

---

## Import blast radius (what must be rewired when the DELETE→SHIELD files go)
- `core/__init__.py` — exports `create_integrated_security_system`, `SecurityLevel`, `ASISafetyFramework`.
- `core/agents/autonomous/autonomous_coordinator.py` — `get_security_controller`, `get_audit_worker`,
  `SecurityController`, `SecurityAuditWorker` (+ `get_safety_framework` — KEEP).
- `core/agents/memory_agent.py` — `get_safety_framework` (KEEP).
- `core/execution/convergence_gate.py` — `get_audit_worker().get_active_findings`.
- `core/health/health_monitor.py` — audit_worker, safety_framework, integrated_security, controller, malware_sandbox.
- `core/health/recovery_manager.py` — `get_security_controller` / `reset_security_controller`.
- `core/main.py` — `create_integrated_security_system`, `get_audit_worker`, `get_training_pipeline`, safety_framework.
- `core/tools/security_tools.py` — content_security, active_defense_types, digital_footprint, malware_sandbox, integrated_security (TOOL-BACKING).
- `core/system/service_locator.py` — `get_safety_framework` (KEEP).
- `core/quantum/asi_quantum_safety.py` — `ASISafetyFramework`; also imports `core.security.security_master` (**no such file — already a dead import; flag**).
- `core/guardian/supervisor.py` — DELETE anyway.
