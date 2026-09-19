# Intent — a first-class authority owned by reasoning

*Design of record. Status: PHASES 1–6 BUILT AND VERIFIED (2026-09-16). What
remains is not a phase but a widening: the learning authority consuming the
meant-vs-happened pairing as a credit signal, and integrity's two other links
coming off their proxies. This document was written before the code so the shape is agreed
and a later session cannot reconstruct a different one. When it is fully built,
the living account moves to `docs/architecture/` and this doc keeps the
rationale.*

*Phase 1 is `core/reasoning/intent_authority.py` (the `Intent` entity, the
`IntentStore` over `unified.intents` + `unified.scoped_intents`, and the
`IntentAuthority` lifecycle), proven by `experiments/INTENT-01` — 14/14 against
real Postgres, restart survival across a real process boundary (BENCHMARKS §5.1).*

*Phase 2 is the bridge hook (`NeuralSymbolicBridge._intent_engage` /
`_intent_settle`, called inside `reason()`): every reasoning pass opens or
refreshes the substrate's intent where reasoning starts and stamps its id onto
the result. Proven by `experiments/INTENT-02` — 15/15 against the real bridge,
including concurrency (six passes → one intent), latency (~36 ms/call) and
restart (BENCHMARKS §5.2). The old `Intent`/`from_task`/`verify_intent` are still
in place; removing them is phase 4.*

---

## 1. Why this exists

The substrate acts, answers and pursues goals, and every one of those comes from
reasoning. Reasoning has intent behind it. But the system has no owner for
intent, and three places in the code show the cost:

- **Nothing builds it.** `Intent` exists only as `Intent.from_task` — a value
  object *reconstructed* by parsing `task.provenance` at the moment something
  wants it. The substrate infers its own intentions from an artifact it wrote
  earlier. That is backwards for a self.
- **It has to distrust its own record.** `verify_intent` asks the rule store
  whether the reasoning a task claims was real, "because a task is a dict, and
  anything that can write a dict could assert that a destructive act was proved."
  The defensive re-check is a symptom: intent was externalized into a record, so
  it comes back untrusted.
- **A faculty already needs it and fakes it.** Appraisal's *integrity*
  dimension is coherence across `identity → intention → action → outcome`
  ([appraisal.py:373](../../core/agents/autonomous/appraisal.py#L373)). With no
  real intention to read, it substitutes proxies — `identity_intention = 1.0`
  if the pursuit was self-initiated, `intention_action = 1.0` if it acted at
  all. The substrate is already trying to reason about its own intentions in
  order to learn, and using stand-ins because the real thing was never built.

And it is too narrow. Intent today is built only from a planner's operator
step — `goal_conditions`, `grounded_operator`, `learned_rule_id`, `domain`,
`plan_id`. An answer to a general question, a research goal, a drive goal, idle
work — none of it carries intent. "Every action and every reasoning has intent
behind it" is true of the substrate we are building; it is not true of the code.

The consequence for learning is the whole point. Credit today can ask *"did the
tool succeed?"* It cannot ask *"did I do what I meant, and was what I meant the
right thing to mean?"* — because the meaning was never held. That second
question is the one that makes the substrate smarter over time, and it is
currently unanswerable.

## 2. The principle

**Intent is the substrate's own, persistent account of what it is trying to do
and why.** It is a distinct entity — not reasoning itself, but *made by*
reasoning — and the reasoning authority (the `NeuralSymbolicBridge`) owns it end
to end. Reasoning writes it; everyone else only reads it. That single ownership
fact dissolves the "untrusted dict" problem: once only reasoning can author
intent, no reader has to re-litigate whether it is real.

One concept, one owner. This replaces the old `Intent` entirely — the reconstruct
path is removed, not kept as a fallback, so there is never a second, weaker
account of why the substrate is acting.

## 3. What an intent is

An intent is created when reasoning first engages with something — a message it
reads, a goal it raises, a question it is asked — at the point it begins forming
context and a plan. Not when a plan is emitted; when reasoning *starts*.

Each intent holds:

- `intent_id` — unique, stable, assigned once.
- `parent_intent_id` — the intent this one was spawned from, or null. (Section 4.)
- `origin` — what brought it into being: a message on a thread, a self-raised
  goal, a question.
- `actor` — who it is on behalf of (a World Auth identity, or the substrate
  itself for its own pursuits).
- `aim` — what the substrate understands the goal/purpose to be, in its own
  terms. Refreshed as understanding sharpens.
- `context` — what it is reasoning from.
- `plan` — the route as it firms up: the proved operators, their goal
  conditions, the rules that license them. This is where the old `Intent`'s
  fields now live, but as they accrue, not reconstructed after the fact.
- `history` — the refreshes, timestamped, so the evolution survives.
- `outcome` — attached when the act completes: what actually happened, reconciled
  against the aim. Null until then.
- `status` — forming · active · fulfilled · abandoned · refused.

An act that did **not** come from reasoning carries no intent, and that absence
is reported as absence — there is nothing to fall back to. The constitution
answers a genuinely intent-less act with Law 2 ("an act nothing can explain is
not one the self can defend").

## 4. Identity and continuity — the resolution rule

The hard question is: when the substrate returns to something, is this the *same*
intent (refresh it) or a *new* one (create it)? A flat key of
`(actor, thread, topic)` breaks the moment a **goal is raised inside a thread** —
the goal is a distinct intent but shares the thread's actor and topic, so it
would collapse into the conversation's intent. That was the failure identified in
design.

Intents therefore form a **tree**, and the continuity key is **level-typed**:

| Engagement | Continuity key (find-or-create) | Parent |
|---|---|---|
| A message/turn on a conversation thread | `(actor, thread_id)` | none (root) |
| A general question/answer on that thread | `(actor, thread_id)` — refreshes the thread intent | — |
| A **goal raised while working** (inside a thread or not) | `(goal, goal_id)` — always its own intent | the active intent (the thread intent if inside one, else none) |
| Returning to that goal later, any turn or session | `(goal, goal_id)` — refreshes it | unchanged |
| A self-raised pursuit with no thread | `(goal, goal_id)`, actor = substrate | none or its raising intent |

So a goal never uses the thread key — it gets its own identity and a
`parent_intent_id` pointing at whatever it was spawned from. A conversation's
intent and the goals raised within it are distinct, linked nodes; refreshing one
never touches the other. Continuity survives turns and sessions because the key
is stable and the record is durable, and refresh updates the live node while
appending to its history rather than rebuilding it.

**Topic is not identity.** It is captured as part of `aim`/`context` and refreshed
as the understanding sharpens, but it is never a continuity key — topics drift,
and keying on them would fragment one intent into many or merge two. Identity is
thread-rooted or goal-rooted; topic is content.

## 5. Content vs shape — built in from the start

An intent about a user's message holds that user's context. That content is the
user's, and under the substrate-wide scope rule it must die when their profile
is deleted. But what the substrate *learns* from an intent — that this shape of
act, under this verdict, led to this outcome — must survive, identity-free, or
the substrate cannot get smarter. So every intent is split at the moment it is
recorded:

- **Content — actor-scoped.** The aim in the user's terms, the message context,
  any user text. Stored under the actor's partition (`scope_actor`), alongside
  the scoped beliefs and edges that already work this way
  ([scoped_context_store.py](../../core/learning/scoped_context_store.py)).
  Deleted with the profile. Shared goal creation never reads it.
- **Shape — substrate-wide.** The operator, the laws that bore on it, the
  verdict, the action class and capabilities, the outcome class — **no arguments,
  no commands, no task text, no actor id.** Stored in `unified.intents`. This is
  what learning, integrity and goal creation read.

The two are linked by `intent_id`. Deleting an actor removes the content rows;
the shape row remains, carrying no trace of who or what-text, only the anonymous
lesson. This is the split named in the deferred design note, made concrete here
because intent is exactly where the substrate first holds a user's purpose next
to its own reasoning.

## 6. Persistence

Durable, the way memory is — it outlives the turn, the session and a restart.
Memory is episodic ("what happened"); intent is its forward-looking twin ("what
I mean to do"), which the outcome later confirms or refutes. They are related and
distinct, and intent is not folded into memory: it has its own lifecycle
(form → refresh → reconcile) and its own owner.

- `unified.intents` (shape, substrate-wide): `intent_id` PK, `parent_intent_id`,
  `origin`, `continuity_key` (indexed, for find-or-create), `status`,
  `shape` (jsonb), `outcome` (jsonb, null until reconciled), `created_at`,
  `updated_at`, `version`.
- The actor-scoped content lives under the scoped store, keyed
  `(scope_actor, intent_id)`.

Restart survival is a first-class requirement, proven against a real restart, not
asserted (SESSION and self-partition experiments set the bar).

## 7. Lifecycle

1. **Form.** Reasoning engages; the bridge resolves the continuity key
   (Section 4), finds-or-creates the intent, records `aim`/`context` and the
   forming `plan`. Content scoped, shape substrate-wide.
2. **Refresh.** The substrate returns to it; the bridge updates the live node
   (new context, firmer plan) and appends to `history`. Same identity.
3. **Judge.** When the intent would become an act, the constitution reads the
   held intent (never reconstructs it) and judges. ALLOW proceeds; anything else
   does not.
4. **Reconcile.** The act completes; the outcome attaches to the intent, and the
   shape row records meant-vs-happened. Learning and integrity read that pairing.

## 8. What is removed

- The `Intent` dataclass's `from_task` reconstruction and intent-as-provenance —
  the task references an `intent_id`; it is no longer the *source* of intent.
- `verify_intent`'s defensive rule-store re-check at read time — correctness is
  guaranteed by the authority when it records a proved operator, not re-litigated
  by every reader.
- Any other place that infers "why" from an artifact after the fact.

The task keeps what an executor needs — the operator to run, its dependencies,
ordering — and gains an `intent_id` reference. It loses the job of *being* the
intent.

## 9. Who reads it (all read-only)

- **Constitution** — judges the act against the held intent. This is why intent
  comes first: wiring the constitution to `from_task` would bind the module meant
  to be the sole authority onto the mechanism we are removing.
- **Learning** — pairs intent with outcome for credit: did the act realize the
  intent, and was the intent well-formed.
- **Integrity / appraisal** — reads a real intention instead of the two proxies
  it fakes today.
- **Goal creation / self-reflection** — reads what the substrate was trying to
  do and why. This is the connective tissue those faculties need, which is why
  intent belongs before them.

## 10. Build plan

Phased, each phase real and tested before the next:

1. **The authority and its store. — DONE, verified (INTENT-01, 14/14).** The
   intent entity, `unified.intents` (shape) + `unified.scoped_intents` (content),
   and the authority's `form / refresh / get / reconcile / forget_actor`, with
   the level-typed continuity resolution and the shape/content split. Two-table
   writes are atomic; restart survival is proven by a separate process. Owner
   established as `get_intent_authority()`; nothing else rewired yet.
2. **Reasoning forms intent. — DONE, verified (INTENT-02, 15/15).** The bridge
   opens/refreshes intent inside `reason()`, keyed from the request's engagement
   (goal, thread, or the query itself when there is no other anchor), splitting
   shape from content and stamping the `intent_id` onto the result. It is
   annotation on reasoning — wrapped so it never changes the answer or takes the
   call down, but a failure is logged at error, because a self that silently
   stops recording its intentions is the defect this prevents.
3. **The planner records through the authority. — DONE, verified (PLANNING-01,
   38/38).** When `_plan_state_goal` proves a route, `_record_plan_intent` forms
   or refreshes the goal's intent (`goal:<goal.id>`) through the authority and
   records the proved route in its SHAPE — operators, the rule ids that license
   them, the goal state, domain, grounding completeness, `proved: True` — while
   the goal's own words and the concrete bindings go to actor-scoped CONTENT.
   Each task carries `intent_id` plus its `step_index`: **one goal is one
   intent**, and the steps are the route within it, not separate intentions.
   Re-planning the same goal firms up that one intent rather than starting a
   second account of the same pursuit. When recording fails, the plan says it has
   no intent and why, instead of appearing to have one.
4. **Remove the old `Intent`** and its `from_task` / `verify_intent` re-check.
   **— DONE, verified.** Doing this honestly required pulling phase 5's core with
   it: deleting `verify_intent` alone would have opened a real hole, because
   `judge()` **accepted an intent object**, and `stated()` is a property of
   whatever object you pass. Measured before the change: a fabricated intent
   naming a bound operator and a rule id that does not exist was **ALLOWED**.
   So `judge()` no longer takes an intent — it takes an `intent_id` and reads
   what the authority recorded, as the SHAPE view (no actor, no actor content,
   because the constitution governs the substrate as a whole). After: the same
   forgery is refused. An intent that was never recorded is not a weaker claim,
   it is no claim at all, so attestation is structural rather than a re-check
   every reader performs.
5. **Rewire the readers** — constitution, appraisal integrity, learning — onto
   the authority. **— CONSTITUTION DONE, verified.** It reads intent by id from
   the authority and never accepts one. Appraisal's integrity and learning are
   not yet rewired; they still use their proxies.
6. **Reconciliation. — DONE, verified (INTENT-04, 15/15).** The execution path
   reconciles automatically: `_reconcile_plan_intent` attaches what happened to
   the intent the plan was the route of, on every exit — reached, stopped, or
   step-failed. **The world decides, in one place:** whether the intent was
   realized is computed by re-observing and asking whether its conditions hold,
   never taken from a step's report. Both directions matter — a plan that ran
   cleanly while the world did not reach the goal is a MISS, and a step that
   reported failure while the world DID reach the goal is realized.

   Appraisal's integrity then reads its **action↔outcome** link from that
   reconciled intent instead of inferring it from `attribution == "success"`.
   This is the whole point of the authority made consequential: the substrate
   asks "did acting realize what I meant", and the answer moves its disposition.

   What this is, in one line: **intent-governed execution with automatic
   post-action reconciliation and downstream appraisal.**

   Still on proxies: integrity's `identity↔intention` and `intention↔action`
   links, and the learning authority does not yet consume the pairing as a
   credit signal.

Unwiring the old security systems (safety_framework, RuntimeGovernance) is
independent of all of this and can happen whenever; it does not block and is not
blocked by the intent work.

## 11. Experiments and benchmarks

- **INTENT-01 — DONE (14/14).** The authority and its store: intent formed on
  engagement, refreshed not rebuilt, a **goal raised inside a thread gets its own
  intent with a parent link** (the collision case from Section 4), content
  actor-scoped and dying with the profile while the shape survives, the outcome
  reconciled, and **surviving a real restart.**
- **INTENT-02 — DONE (15/15).** Reasoning forms intent on the real bridge:
  formation, refresh across turns, goal parenting, anchorless-question keying, the
  content/shape split under the live path, concurrency (one intent under a race),
  latency, and restart.
- **INTENT-03** (not built) — the learning tie: an intent whose outcome did not
  match its aim produces a credit signal that an intent whose outcome matched does
  not. This is the "gets smarter from its own intentions" claim, measured. Comes
  with phases 5–6.
- **Updated (not built):** CONSTITUTION-01/02 and GOVERNANCE-ABSORPTION-01 read
  intent from the authority instead of `from_task`; an appraisal/integrity
  experiment reads a real intention instead of the proxies.

All runs are captured through `experiments/_evidence.py` (a new JSON per run plus
its `.md` summary), and every capability number is appended to
`docs/research/BENCHMARKS.md` with the run it came from.
