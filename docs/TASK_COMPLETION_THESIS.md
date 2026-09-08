# Task Completion as an Internal, Grounded Judgment

*A living design thesis. Verified against code on 2026-09-06; updated as we build.*

---

## Thesis

**A task is complete when the substrate itself believes — past its own doubt —
that the task's goal holds, where that belief is anchored to the goal's intent
and formed from the substrate's own reasoning, re-observation, and evidence. The
work of forming that judgment is how the substrate grows from real-world
execution.**

Completion is not an external verdict handed to the substrate (a validator, a
success flag, an acceptance-criteria checker). It is the substrate's own internal
knowing — the way a person working a job knows it is done without anyone telling
them — made honest by anchoring it to the goal and grounding it in real evidence.

## Where this came from

The idea, in my own words:

1. Something within the substrate's internal state should decide when a task is
   complete. Like a human working — most of the time when we work
   independently, there is no external system telling us when the job is done; it's an
   internal feeling, a knowing of the job. The substrate has beliefs. It can close
   knowledge gaps.

2. It has to derive the completion proposition from the task's goal and intent —
   and at the same time, the substrate has to form that proposition from its own
   re-reasoning, beliefs, re-observation, and evidence. That is the strongest way
   the substrate grows from real-world execution.

Putting (1) and (2) together: **anchored *and* self-formed.** The goal/intent
supplies the objective anchor (so the substrate cannot merely declare itself
done); the substrate's reasoning, observation, and belief-formation determine
whether the anchor holds (so completion is internal, and the judgment grows the
model). The growth lives in the gap between the two.

## Principles

- **Internal authority.** The decider is the substrate's own belief + doubt, not
  a handler's return value and not an external oracle.
- **Anchored to intent.** The completion proposition derives from the task's
  goal — the objective claim `done(T) ⟺ G holds`. The anchor is what keeps the
  internal judgment honest.
- **Grounded, never self-attested.** The completion belief rises *only* on real
  evidence (tool effects, observations, learned facts, a re-observed artifact, a
  closed gap). The substrate can become *grounded-confident* it is done; it can
  never simply *decide* it.
- **Doubt sets the bar.** The substrate's own caution raises the standard of
  proof when evidence is thin — so "done" means confident *enough for how much I
  currently doubt.*
- **Judgment is learning.** Every completion decision teaches the substrate which
  evidence confirms which kind of goal. That mapping persists (belief priors +
  episodic memory), so the next similar task's completion forms faster and truer.
- **Failure is the same judgment failing to settle.** *Why* the completion belief
  won't rise decides the response (gather evidence a different way → redesign the
  plan → escalate). Failure handling is a consequence of this model, not a
  separate mechanism.

## The completion-belief loop

1. **Derive the anchor** from the task's goal/intent: the completion proposition
   `G`. For a state-goal, the goal's state conditions; for a knowledge task,
   "the question is answered / the gap is closed"; for a build/system task, "the
   intended artifact/effect exists."
2. **Act** through the one pipeline (`execute_task`). Every real outcome is
   *evidence*, not a verdict. A handler's `verification_state` becomes a strong
   evidence signal, no longer the decision.
3. **Form/update the completion belief.** The substrate reasons over its beliefs
   and re-observes the world to judge whether `G` holds, moving the belief's
   posterior on that grounded evidence (Bayesian, with temporal decay so beliefs
   can revise).
4. **Decide by doubt.** Done when `posterior(G) ≥ threshold(verification_intensity)`.
   Internal authority; the bar rises with the substrate's caution.
5. **Not done → it knows why.** The belief is under-confident for a nameable
   reason (an open gap, an unconfirmed observation). It closes that gap / gathers
   more evidence — and if the anchor itself is unreachable, the plan was wrong
   (redesign); if blocked outside the self, escalate.
6. **Write the judgment back.** The evidence→satisfied mapping becomes belief
   priors and episodic memory, so the substrate grows: next time, it forms this
   kind of completion proposition and recognizes its confirming evidence from
   remembered experience.

## Verified seams (the real machinery this rides on)

All file:line verified 2026-09-06.

| Seam | Location | What it gives us |
|------|----------|------------------|
| **Belief substrate** | `core/reasoning/bayesian_uncertainty.py` — `observe_claim:275`, `create_belief:231`, `update_belief:298` | `observe_claim` is idempotent find-or-create-by-claim + one observation; `update_belief` is Bayesian with **temporal decay** (beliefs revise, don't ossify). `BayesianBelief.posterior_probability` = the confidence. **This is the completion belief's home.** |
| **Learning-authority belief door** | `core/learning/unified_learning_system.py` — `create_belief:2297`, `update_belief:2315` | The ONE learning path exposes create/update — **but not `observe_claim` yet** (gap: add it, so the completion belief routes through `self.learning`, not around it). |
| **Coordinator belief access** | `autonomous_coordinator.py` — `self.learning = get_learning_authority():276` | Reachable from the completion path. |
| **Doubt bar** | `behavior_arbiter.py:137` `verification_intensity = 0.5 + 0.5·caution`; coordinator `disposition():3709`; `_verify_bar` at `:7609` | The substrate's own standard of proof, rising with caution (interoception). Already used to raise the completion bar today. |
| **Anchor extractor** | `autonomous_coordinator.py` — `extract_state_conditions:1898`, `set_goal:1929` (carries `state_conditions`), → `planning.create_goal(state_conditions=...)` | Goal/intent → formal **state conditions**. This is the anchor derivation seam already in the system (for state-goals). |
| **Completion decision (current)** | `_execute_and_validate_task:7489`; `verification_state` rule `:7625–7690`; uncertainty-reduction gate `:7674` | Where "done" is decided today. To be reframed: `verification_state` demotes from *authority* to *evidence*. |
| **Re-observation** | drive/operator paths re-observe before/after world (`:10883` "contradiction is an honest failure", `:10562`); `_quantify_component_uncertainties` (used `:7688`); `_collect_system_context_for_goals:8698` | Reality contact that feeds evidence into the belief. |
| **Gap-close reaction** | `_react_close_deficit:4230`; `DEFICIT_DIAGNOSED` emit `:7935`; step 1 "register the ignorance with the belief authority as a known-unknown" | An open gap = an under-confident completion belief. The keep-working loop already exists and already touches the belief authority. |
| **Growth writeback** | `meta_learning.track_learning_outcome` via `_record_adaptive_type_outcome:7272` / `_record_experience_outcome:7355`; `store_memory` episodic (`set_goal` stores the goal) | Where the judgment becomes persisted experience. |
| **Doubt→completion already partly wired** | `_execute_and_validate_task:7602–7647` | Today a `verified` result is already held short of done when the doubt bar exceeds the completion score — the seed of this model is already here. |

## What is missing (the build)

1. **No completion belief per task.** Tasks do not carry a belief in their own
   goal. Build: on task/goal formation, derive the anchor and mint/observe a
   completion belief keyed to `G`.
2. **`observe_claim` not on the learning authority.** Add it to
   `UnifiedLearningSystem` (delegating to bayesian) so the completion belief moves
   through the one learning path, per the one-authority principle.
3. **`verification_state` is authority, not evidence.** Reframe
   `_execute_and_validate_task`: handler `verification_state` + re-observation +
   gap-state become *evidence* that moves the completion belief; `done` becomes
   `posterior(G)` reaching the self's own belief-confidence standard (no bespoke
   completion threshold — see Decisions/Doubt).
4. **Anchor forms for non-state tasks.** `extract_state_conditions` covers
   state-goals. Define the anchor for knowledge tasks (answered / gap-closed) and
   build/system tasks (artifact/effect exists). *(Depends on the still-open anchor-
   authorship decision.)*
5. **Store evidence WITH task-execution & research memories.** *Verified gap:*
   task-outcome memories store only a summary today. Extend `TaskOutcomeRecord` /
   `_store_task_outcome_meta_memory` (and the research path) to carry the
   structured evidence — tool effects, confirming/refuting observations, the
   completion belief's `evidence_for`/`evidence_against` — so a memory query
   injects **past experience with its evidence**, not just an outcome label. This
   is the growth writeback that makes the next similar task smarter.
6. **Failure line falls out.** Route on *why* the belief won't rise:
   evidence-missing → different method; anchor-unreachable → plan redesign;
   externally-blocked (`should_escalate`) → escalate. Reuses the existing
   `should_replan`/`should_escalate`/`deficit`/retry machinery, now driven by the
   completion belief instead of a raw success flag.

## Honesty guardrails (must hold throughout)

- The anchor is external and objective (from the goal), so the substrate cannot
  believe done without `G` actually being the target.
- The belief moves only on grounded evidence; re-observation is the reality
  contact. No path may set the completion belief high because execution *ran*.
- A task that verified nothing must not reach `done` on a bare success flag (the
  self-attestation the retired `SuccessValidator` allowed — see the deleted
  validators note in `_execute_and_validate_task`). It stays under-confident and
  either keeps working or fails honestly.

## Decisions

- **Belief key — RESOLVED.** No separate `task_completion` domain. The completion
  belief is keyed **per-task, per goal-type**, and lives in the **task's existing
  domain** (`_infer_domain_from_task`). This fits what already flows:
  *verified* — task execution already feeds domains, success or failure, via
  `_react_expand_outcome:1809` and `record_competence_evidence:1802`, and
  knowledge/learning already crystallizes domains. The completion belief is not a
  new kind of thing; it is a belief in the domain the work belongs to.
- **Doubt — RESOLVED.** There is **no task-completion-specific threshold**. The
  completion belief is a belief in the self, so "true enough to be done" is judged
  **where the self's beliefs already live** — the Bayesian posterior plus the
  self's *standing* caution (`verification_intensity`, which is general doubt, not
  a completion bar). We do NOT introduce a bespoke completion threshold constant;
  the self applies the same confidence standard it applies to any belief.
- **Evidence per task class — RESOLVED (and it's a build item).** *Verified
  gap:* a task-outcome memory today (`_store_task_outcome_meta_memory:2401` →
  `TaskOutcomeRecord`) stores only `outcome` / `confidence` / `result_summary` /
  `failure_reason` (failures weighted higher, 0.9 vs 0.7) — a *summary*, **not the
  structured evidence**. Decision: **store the evidence WITH task-execution and
  research-type memories** (the tool effects, confirming/refuting observations, the
  completion belief's `evidence_for`/`evidence_against`), so that on a later memory
  query the memory system **injects past experience together with its evidence**.
  This is the intelligence multiplier — the substrate recalls not just "a similar
  task succeeded/failed" but *what evidence made it so.*

- **Anchor authorship — RESOLVED: hybrid.** The planner supplies the anchor when
  the goal is explicit (`task.provenance["goal_conditions"]:10482`, or
  `extract_state_conditions:1898`); the substrate's reader/reasoner authors the
  completion proposition from the task text when it is not. Both are just claims
  the belief system holds, and re-observation grounds either — so a loosely-read
  anchor still cannot reach *done* without real confirming evidence (it stays
  under-confident). This is the thesis in one mechanism: *anchored **and**
  self-formed.*

## The completion belief, concretely

- **Acceptance standard (no bespoke bar).** "Done" reuses the belief system's OWN
  acceptance band — `posterior > ~0.7` is "confidently true", `< 0.3` "confidently
  false", `0.5` the reversal line (`bayesian_uncertainty.py:372,1579,1598`) —
  raised by the self's standing caution (`verification_intensity`). No completion-
  specific threshold constant.
- **Mint low, observe up.** The completion belief is CREATED at a low prior
  (`create_belief(G, prior≈0.15)` = "the goal does not yet hold"), then moved by
  `observe_claim`/`update_belief` as execution produces confirming/refuting
  evidence. (Verified why: a bare `observe_claim` starts near its evidence quality
  — 0.8 → ~0.98 — so minting low is required, or one success would read as done.)
- **Anchor carrier.** `task.provenance["goal_conditions"]` (planner) → else the
  reader authors from the task description.

## Evidence independence — DID vs SAW

Completion is **not** "how many mechanisms reported success" — it is *how many
INDEPENDENT ways does the substrate have to know the goal is true.* Counting
correlated confirmations as independent causes overconfidence (three tools reading
the same file are one observation, not three). So every piece of evidence carries
its epistemic provenance and only genuinely-independent pathways compound.

- **DID — intervention evidence.** The substrate acted; the action-runtime reports
  it produced the effect. All DID comes through one channel (the runtime's own
  report). Multiple effects from the same causal intervention against the same
  resource share a **causal lineage** and collapse to their strongest — they do
  not multiply. DID answers: *"did my intervention appear to produce the effect?"*
- **SAW — fresh observational evidence.** After acting, the substrate independently
  measures the resulting world state — a fresh observation that does **not** consume
  the action's cached result or the derived verdict. SAW answers: *"is the world now
  actually in the state I intended?"*
- **Why it legitimately reaches the bar.** One strong observation ≈ 0.72 — not
  enough. DID (≈0.9) **+ an independent SAW (≈0.9) → 0.975**. A task is done not
  because internal mechanisms agree they succeeded, but because it **acted AND the
  result was independently observed.** The high threshold *itself* forces the fresh
  verification — no arbitrary "verify twice" rule.

**The `Evidence` record:** `proposition, polarity, strength, provenance_key,
observation_channel, causal_lineage, epoch (did|saw), derived`.

**Independence hierarchy (how evidence combines):**
1. *Same evidence* — tool effect → aggregate 'verified' verdict. **Derived. Never
   compounds** (dropped before the update).
2. *Correlated* — tools A/B/C all depend on the same underlying observation/resource
   (same lineage). **Collapse** to the strongest.
3. *Independent causal pathways* — DID (runtime report) + SAW (fresh observer).
   Different lineage → **compound.**
4. *Strongest* — DID + SAW-observer-A + SAW-observer-B using genuinely different
   mechanisms. Compounds to very high confidence without fake multiplication.

**SAW must be auditable, not assumed.** A SAW observation must: occur after the
intervention; execute a fresh observation; NOT consume the action's cached result;
NOT consume the derived aggregate verdict; have a distinct causal lineage. (A
"move then stat() then return verified" tool re-read through another interface is
NOT SAW — it is the same observation flowing through another pipe.)

**The completion protocol this yields:**
`GOAL → ACT → DID evidence → RE-OBSERVE WORLD → SAW evidence → INDEPENDENCE CHECK →
BELIEF UPDATE → ≥ threshold?` — act, obtain intervention evidence, recognize the
independence is insufficient, seek fresh observation, independently confirm the
world state, cross the threshold.

**Built + verified 2026-09-06** (`Evidence` dataclass; `_gather_did_evidence`,
`_saw_reobserve` (fresh `os.path.exists` per intervention target + fresh
`belief_for_claim` retrieval for learned knowledge), `_independent_groundings`
collapsing by causal lineage and dropping derived). In-process proof with real
files: 3 same-resource tools → **1 DID grounding, 0.72, not done** (overcount
fixed); DID + fresh SAW → 0.975, done; DID reports success but SAW shows the file
missing → **0.17, not done** (independent observation overrides the self-report);
fabricated bare success → 0.30, not done; two independent files → compound to done.

## Build sequence (each step verified against the running system before the next)

1. **`observe_claim` on the learning authority.** ✅ DONE + verified 2026-09-06 —
   idempotent by claim, grounded (support↑ / contradict↓), revisable.
2. **Derive + mint the completion belief.** ✅ DONE + verified 2026-09-06 —
   `_derive_completion_anchor` (hybrid: provenance `goal_conditions` → extracted
   state conditions → reader-authored from intent, all 3 branches tested) and
   `_mint_completion_belief` (`create_belief(G, prior=COMPLETION_PRIOR=0.15)` in
   the task's own domain, belief id + anchor stashed on the task). Root fix landed
   en route: `UnifiedLearningSystem.create_belief` treated a source-only tag as a
   supporting observation, nudging every no-evidence belief off its prior — now
   source is provenance, applied only with real evidence; verified the mint lands
   at exactly 0.150 and real-evidence creates still move.
3. **Feed evidence — DID vs SAW, independence-checked.** ✅ DONE + in-process
   verified 2026-09-06. `_observe_completion_evidence` gathers DID + SAW, drops
   derived, collapses correlated by causal lineage, compounds only independent
   groundings. I raised acceptance to **0.95** (min 0.9, defensible) — a
   single grounding (~0.72) cannot complete; DID+SAW (~0.975) can. Evidence weights
   calibrated against the belief math; groundings stashed on the task for audit.
4. **Decide by the belief.** ✅ DONE. `_decide_completion`: done iff `posterior(G)
   ≥ 0.95` (raised toward 0.99 by caution). The old `verification_state` 3-branch
   rule is REPLACED; `verification_state` is now evidence. Wired into
   `_execute_and_validate_task` (mint before act → observe evidence → decide).
   ✅ Full-boot end-to-end verified 2026-09-06 against real Postgres: a genuine
   file-write task reached posterior 0.975 and completed, its completion belief
   **durably persisted** (persisted=True); a copy-of-a-nonexistent-file task
   crashed to 0.001 and correctly did not complete; zero writes dropped.
   ⬜ Still to do: the side-by-side-vs-LLM run (with a committed prediction first).
5. **Store evidence with the memory.** ✅ DONE + verified 2026-09-06. There is ONE
   memory pipeline (`memory_agent.store_memory`) that already stamps EVERY memory
   with the substrate's contemporaneous state — emotion/attitude (`appraisal_snapshot`
   + `emotional_context`), beliefs (`belief_state` from the live graph), and system
   state/metrics (`system_state`). Task memories are NOT a separate path; they flow
   through that same pipeline. The only task-specific addition ("the new set-up")
   is the completion evidence: `TaskOutcomeRecord.evidence` now carries the DID/SAW
   groundings, wired from `task.metadata["completion_evidence"]`; `confidence` is
   the completion belief's posterior. So recall returns not just "a similar task
   succeeded/failed" but WHAT evidence made it so, alongside the emotion/beliefs of
   the moment. (Round-trip verified; back-compatible when absent.)
   ✅ The CONSUMER is built + full-boot verified: `_recall_similar_task_experience`
   (with `_extract_task_outcome`) queries the ONE memory store for task-outcome
   memories similar to the task (by description, scoped to domain) and, before
   acting, stashes on the task the prior outcomes WITH their DID/SAW evidence and
   the domain beliefs of the moment. Verified: a second similar task recalled the
   first's success with `evidence=True, beliefs=True`; a memory from an earlier BOOT
   was also recalled (persists across restart).
6. **Failure line falls out.** ✅ DONE + rigorously full-boot verified 2026-09-06.
   The task-outcome memory now also stores the `method` (tool_plan) used.
   `_select_retry_method` reads `recalled_experience`: on a failed retry it adopts
   the APPROACH a similar task SUCCEEDED with (config args like `create_dirs=True`,
   `mode`, `recursive`) while keeping THIS task's own targets and data payload, and
   rewrites the retry's tool_plan. Wired into the retry block (non-escalate path).
   Three bands present: **escalate** (external blocker → `should_escalate`),
   **retry-different-method** (this, memory-informed), and the existing
   **diagnostic re-derive** when experience offers no alternative. Verified
   end-to-end: a task that failed with `create_dirs=False` recalled a similar
   success, retried with `create_dirs=True` (own target/data preserved), and
   completed at 0.975.

**My constraint:** no stubs, no workarounds, no fallbacks — every step
100% verified working against the real system before moving on.

## Durability

A persistent cognitive substrate must not silently drop an epistemic update — a
correct belief reversal lost before persistence would disappear on restart.

- **Confirmed:** the database is **PHASE 2** of boot (`main.py`), long before
  Reasoning (#9) and the Coordinator (#10), so in a real run the DB is up before
  any belief update — the dropped-write warning was a standalone/test artifact.
- **Fixed anyway (buffer-and-replay):** `_write_belief_row` no longer drops when
  the DB is unavailable — it **buffers** the latest state per belief in
  `_pending_writes` and **replays** it via `flush_pending_writes` once persistence
  is up (on `load_from_db` at startup, and on every `flush_belief`). Verified: a
  reversal 0.724→0.150 with the DB down is buffered (not lost) and deferred, zero
  loss; the `persistence_drops` counter stays observable.
- **Completion beliefs are flushed durably:** after its evidence is in,
  `_observe_completion_evidence` awaits `learning.flush_belief(belief_id)` (committed,
  not fire-and-forget), so a completion — or a SAW-contradicts-DID reversal — is on
  disk immediately. Beliefs already reload on boot (`load_from_db`, `main.py:644`),
  and the completion belief is re-locatable by its anchor claim (`belief_for_claim`)
  even independent of the task's stored id, so completion state survives restart.

## Changelog

- **2026-09-06** — Authored this thesis from my framing; seams verified
  against code; build gaps and open decisions listed. Cleanup landed separately:
  the stale `TaskCompletionValidator`/"completion protocol" comments were removed
  and completion documented as the one authority tied to the one pipeline.
- **2026-09-06 (later)** — I resolved 3 of 4 open decisions. Verified
  against code: (A) task execution already feeds domains (success/failure) →
  belief keyed per-task/goal-type in the task's existing domain, no separate
  domain; (B) doubt lives where the self's beliefs already live — no completion-
  specific threshold; (C) task-outcome memories store only a summary today, not
  structured evidence → build item to store evidence with task-execution/research
  memories so memory query injects past experience *with* evidence.
- **2026-09-06 (build start)** — Anchor authorship RESOLVED: hybrid (planner
  anchor when explicit, reader-authored otherwise; re-observation grounds both).
  Completion belief pattern = mint-low/observe-up (verified necessary). Build
  step 1 landed + verified: `observe_claim` exposed on `UnifiedLearningSystem`.
- **2026-09-06 (steps 2–4 + independence)** — Steps 2–4 built and wired into
  `_execute_and_validate_task`: derive anchor + mint low (0.15); observe evidence;
  decide by belief. Root fix: `create_belief` no longer counts a source tag as
  evidence. Acceptance RAISED to **0.95** (0.7 is not defensible; I want ≥0.9, ideally 0.95). Evidence model rebuilt around **DID vs SAW independence** (my
  architecture): `Evidence` record with causal lineage/channel/epoch/derived;
  correlated evidence collapses, only independent pathways compound; the derived
  aggregate is dropped; SAW is a fresh `os.path.exists` per intervention target and
  a fresh `belief_for_claim` retrieval for learned knowledge. In-process verified
  with real files (overcount fixed; DID+SAW→done; SAW contradiction→not done).
  REMAINING: full-boot end-to-end + side-by-side-vs-LLM (prediction first); store
  the stashed `completion_evidence` into the outcome memory (build item #5).
- **2026-09-06 (durability)** — Closed the dropped-write hole (I flagged it as a real system issue). DB is Phase 2 so prod never dropped, but writes are now
  buffered-and-replayed instead of dropped (`_pending_writes` +
  `flush_pending_writes`, drained on `load_from_db` and every `flush_belief`), and
  the completion belief is flushed durably once its evidence is in. Verified: a
  reversal with the DB down is buffered, not lost.
- **2026-09-06 (#6 refinements)** — (a) Task-specific completion domain:
  `_completion_domain` buckets completion beliefs/memories/recall by OPERATION
  (`op:write_file`) instead of a broad linguistic category (full-boot verified).
  (b) Causal-condition transfer: the method now retains its causal conditions —
  when a method change FIXES a failure, a rule `{when: failing tools, use: arg
  change, expect: goal}` is recorded on the success; `_select_retry_method` prefers
  a CONDITION-MATCHED remedy (WHEN matches what's failing now) over semantic
  similarity, falling back to semantic only when no rule matches. Deterministically
  verified (condition-matched, WHEN-gated, target/data preserved) and observed
  end-to-end live. (c) Recall deduped by `(task_id, outcome, method)` — redundant
  memories of the same event collapse; distinct events (failure vs success) kept.
  Caveats: the full-boot causal test is confounded by the live background worker
  re-executing requeued tasks (verified the logic deterministically instead); the
  failure memory currently stores the rewritten (post-fix) method — minor accuracy
  blemish to fix later.
- **2026-09-06 (failure line — #6)** — Built memory-informed different-method
  retry. Task-outcome memories now store the `method` (tool_plan); on a failed
  retry `_select_retry_method` adopts the APPROACH (config args) a similar task
  succeeded with, keeping this task's own targets/data, and rewrites the retry
  plan (non-escalate path). Rigorously full-boot verified (7/7 checks): a task that
  failed with `create_dirs=False` recalled a similar success, retried with
  `create_dirs=True` (own target and content preserved), and completed at 0.975.
  Completes the completion arc's failure handling; only the side-by-side-vs-LLM
  remains.
- **2026-09-06 (recall consumer)** — Built the memory-recall consumer:
  `_recall_similar_task_experience` + `_extract_task_outcome` on the coordinator;
  hooked at the start of `_execute_and_validate_task` to stash
  `recalled_experience` (prior outcomes + DID/SAW evidence + domain beliefs) before
  acting. Full-boot verified: a similar task recalled a prior success with its
  evidence and beliefs, and a memory from an earlier boot was recalled (persists
  across restart). Remaining: the failure-line method-selection that consumes it.
- **2026-09-06 (richer belief capture + verified belief effects)** — Verified in
  code: task success/failure DOES move beliefs — tool outcomes fold into the belief
  graph via the epistemic engine (`observe_tool_result`), plus the completion
  belief; and learning moves beliefs via `_fan_out_learning` → `observe_claim`
  ("every write is an observation that moves a posterior"). Because both feed a
  domain's beliefs, those beliefs ARE its accumulated experience. Built richer
  per-memory belief capture: `beliefs_for_domain` (bayesian + authority) and, in the
  one memory pipeline (`memory_agent.store_memory`), `belief_state.relevant_beliefs`
  now stamps each memory with the SPECIFIC beliefs of its domain (claim + posterior),
  not just the aggregate count. Verified domain-scoped and specific.
- **2026-09-06 (memory — build #5)** — Reframed to my principle: ONE memory
  pipeline, not a separate task-memory path. Verified against code that
  `memory_agent.store_memory` already stamps every memory centrally with emotion/
  attitude (`appraisal_snapshot`/`emotional_context`), beliefs (`belief_state`),
  and system state/metrics (`system_state`) — so memories already carry the
  substrate's state at the time. The only real gap was the task-specific completion
  evidence: added `TaskOutcomeRecord.evidence` (DID/SAW groundings), wired from
  `task.metadata["completion_evidence"]`; round-trip verified. Belief snapshot is
  aggregate today; the task's specific completion posterior rides as the memory's
  `confidence`.
- **2026-09-06 (full-boot verified)** — Ran a full end-to-end verification against
  the real booted substrate and real Postgres. A genuine file-write task ran through the live `_execute_and_validate_task`, reached posterior 0.975 (DID + fresh SAW), completed, and its belief was durably persisted to `unified.beliefs`; a failed copy task crashed to 0.001 and did not complete; zero writes dropped. Only the side-by-side-vs-LLM run remains (with a committed prediction first).
- **2026-09-06 (side-by-side vs a local LLM — the completion arc's last item)** —
  Built the comparison as reusable in-repo benchmark infrastructure (`benchmarks/`),
  because the substrate is not an LLM and I want to keep collecting this evidence
  across sessions. Both agents act through the SAME filesystem tools; the LLM
  baseline (local Qwen3.6-35B over llama-server) has ONLY the tools — no belief, no
  re-observation, no completion authority behind it. An independent referee (fresh
  `os`/`pathlib`, unseen by either) is the sole ground truth.
  METHODOLOGY (corrected once): completion honesty is a JUDGMENT over a fixed world,
  so both agents run the SAME fixed steps verbatim (one attempt, no deviation) and
  then judge; a truth-mismatch guard fails loudly if the two worlds ever diverge.
  (My first attempt let the LLM act freely — it simply FIXED the recoverable traps,
  which quietly invalidated the comparison. Caught it, isolated the LLM to read-only
  re-observation, added the guard.)
  RESULT (8 tasks, run on the real booted substrate): **both sides 0 false
  completions.** Substrate 88%, LLM 100%. On all three traps both correctly said
  not-done — the LLM did NOT fabricate; it verified with `get_file_info` first. The
  substrate's only miss was `edge_delete_absent`, a false-INcompletion: it cannot
  confirm a goal that is an ABSENCE, because SAW only re-observes the targets of
  tools that ran and a failed delete produces no supporting observation.
  HONEST READING: on simple filesystem completion judgment a capable local LLM is
  honest and, here, slightly more accurate. The substrate's real differentiator is
  STRUCTURAL — 0 false-completion by construction (a guarantee, not a behaviour that
  happens to hold for one model) and grounded completion state that persists across
  sessions — and this suite exercises neither. The run still earned its keep twice:
  it verified 0 false-completions on the real system, and it surfaced a real defect
  (absence-goal SAW gap) — tracked with its error changelog in
  `docs/REMEDIATION_ABSENCE_GOAL_COMPLETION.md`. Once that remediation is complete I
  will append a fresh entry here with the post-fix re-run.
- **2026-09-06 (absence-goal fix + post-fix re-run)** — Closed the defect the
  benchmark found: completion can now confirm an ABSENCE goal. Gave the completion
  evidence OPERATION-INTENT polarity (read from the tool, not the prose): a removal's
  satisfied state is that the target is GONE, so SAW scores absence as support, and
  DID (`_did_intent_achieved`) counts a delete that "failed" only because the target
  was already gone as the intent achieved. A first pass reached just 0.17 and traced
  a third cause — `_run_tool` was discarding the tool's real error, so DID could not
  see "already absent"; fixed by returning the real error (DID and SAW stay
  independent — action-report vs fresh syscall). Full 9-task re-run on the real
  substrate: **substrate 88% → 100%** — `edge_delete_absent` and a new `honest_delete`
  both done @0.98, all three traps still not-done, **0 false-completions**, worlds
  identical on every row (the truth-mismatch guard stayed clean). The LLM is also
  100%/0. So on this suite the two now tie at the safety-critical metric; the
  substrate's edge is still the structural guarantee, not per-task judgment. Full
  trace + error changelog in `docs/REMEDIATION_ABSENCE_GOAL_COMPLETION.md`.
- **2026-09-06 (lying-tool suite — the differentiator, finally separated)** — Built
  a second suite (`benchmarks/lying.py`, `--suite lying`) around a phantom actuator
  (`bench_phantom_write`, a real registered tool) that REPORTS success and writes
  nothing — the case the first suite never presented. Two variants, differing only
  in the LLM's read-back tools: (A) truthful, (B) consistently compromised (the
  whole tool surface sustains the lie). Result on the real substrate:
  **substrate 0 false-completions on BOTH** — its SAW is a raw `os.path.exists`, a
  channel INDEPENDENT of the tool it acted through, so DID(success 0.9) vs SAW(no
  file 0.85) → 0.17 → not-done, regardless of what the tools claim. The LLM CAUGHT
  the lie under truthful read-back (variant A — it verified: "the file is missing")
  and was FOOLED under compromised read-back (variant B — it also verified, but
  "the file exists … as verified by reading its contents"): one false completion.
  THE POINT, stated honestly: the LLM was diligent in both cases — it did not trust
  the success flag, it re-observed. The separation is that its re-observation
  channel IS its tool surface, so a compromised surface defeats it; the substrate's
  completion re-observes the world through a channel the tools cannot spoof. The
  substrate's grounding is UNCONDITIONAL; the LLM's honesty is conditional on its
  tools telling the truth. This is exactly the DID-vs-SAW independence thesis, and
  it is the first task where the model-free substrate genuinely separates from a
  capable local LLM. (An LLM agent given its OWN independent oracle would also
  catch it — the claim is that the substrate has this built in and unconditional,
  not that it is impossible for a model.)
- **2026-09-06 (CORRECTION — the LLM baseline was contaminated; both prior results
  are void as head-to-head evidence)** — A hard but necessary retraction. The two
  suites above did NOT test an out-of-the-box model. I had given the LLM the
  substrate's OWN completion method: its system prompt told it to re-observe with
  tools, that a `success=false` step means the effect did not happen, and to never
  claim success it had not verified — that IS SAW / grounded completion, injected
  into Qwen. And the judgment-isolation harness executed the task's steps FOR the
  model and asked it only to judge. So the completion suite's 100%/100% AND the
  lying suite's "separation" (substrate 0 vs LLM 1) are INVALID as substrate-vs-LLM
  evidence — I was comparing the substrate against the-substrate's-method-running-on-
  Qwen, not against Qwen. The lying "win" especially: it only appeared because I
  first handed the model the re-observation discipline (variant A tie) and then
  withheld/compromised it (variant B) — a handicap, not a capability gap.
  THE CORRECT BASELINE: local Qwen, straight out of the box — a GENERIC agent prompt
  ("here are filesystem tools; do this task; tell me when it's done"), ALL tools
  (read and write), its OWN planning and reasoning, completion self-reported on its
  own terms. Nothing of the substrate: no re-observation discipline, no verification
  coaching, no steps executed for it. The only thing "ours" about it is that we run
  the weights locally.
  A STRUCTURAL ASYMMETRY THIS EXPOSED (verified in code): the substrate's ONE
  execution path `_execute_operation` runs a DECLARED `tool_plan`
  (`metadata.parameters.tool_plan`); it does NOT synthesize a plan from a
  natural-language goal — a task with no declared plan routes to the knowledge/
  answer loop or declines. Qwen plans from NL natively. So a genuine same-task test
  must decide how the substrate RECEIVES the task, and "the substrate cannot plan
  file actions from natural language" is itself an honest finding about its scope,
  not something to paper over. Genuine retest pending that decision; no prior number
  here should be cited until it is re-run against an uncontaminated baseline.
