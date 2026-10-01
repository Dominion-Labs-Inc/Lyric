# Public Role Offerings — Capability Reasoning & Beta Profiles

Status: reasoning record, written 2026-09-22 against the system as it runs today. Every capability
statement below was read in the source, in a dated experiment artifact, or measured against the live
`lyric_db` on the date given. Nothing here is a plan for what Lyric will be able to do; it is a
statement of what a subscriber would receive if they paid this week.

Companion to `Tet/TET.md` (editions, packs, build order) and
`docs/LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md` (the evidence corpus).

---

## 1. The question, and the answer

**Question.** Three public Lyric instances — SOC analyst, researcher, general assistant — sold as
autonomous subscriptions, beta first, to bring in revenue before SBIR.

**Answer.** The three-role shape is right, but not as three public autonomous subscriptions, and not
in this order. On today's measurements:

| Role | Verdict |
|---|---|
| **Researcher** | **Ship a beta** — as a per-lab isolated deployment, supervised, not a shared public world |
| **SOC analyst** | **Do not ship publicly.** Design partner only, inside the customer's own stack, advisory-only |
| **General assistant** | **Do not ship.** Lyric's own frozen benchmark scores it 0.0 on comprehension and 0.0 on coding |

The reason is not conservatism. It is that three specific measurements, taken this week, decide the
question before product design gets a vote.

---

## 2. The four measurements that decide this

### 2.1 The executable repertoire is five operators, in two experimental domains

Measured against live `lyric_db`, 2026-09-22:

| `epistemic_status` | domain | count |
|---|---|---|
| validated | `kite17` | 4 |
| validated | `warehouse` | 1 |
| candidate | `archive`, `syllogism2`, `identity_oracle`, `syllogism_evidence`, `perception` | 6 |
| refuted | `kite17` | 1 |
| invalid_artifact | `syllogism` | 1 |

**Five validated rules, both domains synthetic experiment worlds.** A learned rule is what licenses
a plan step; a plan step is what lets Lyric act. There is no validated operator in any domain a
customer would recognise — not incident response, not literature search, not file management for a
real workspace.

This is the single most important fact for pricing an *autonomous* subscription. What Lyric can
autonomously *do* today is: move and remove files in a directory it has practised in, and act in two
experimental worlds. Everything else it can reason, remember, judge and refuse — but not execute.

### 2.2 The substrate's own gate says it may not act anywhere

`OPERABILITY-BAR-01`, run 2026-09-20, 11/11 checks PASS. The mechanism is correct and the live
reading is the finding:

```
[LIVE] operable now: 0/12 sampled (bar == stakes base everywhere)
[LIVE] 336 real domains — earned=0.5 (neutral) in every one
```

Lyric gates action on *earned* operating history. It has none, so it abstains everywhere. This is
the system working as designed and it is also, verbatim, a statement that autonomous action is
currently switched off by Lyric's own judgement. A subscriber buying "autonomy" this week buys a
system that correctly declines to act.

Earned trust is accumulated by operating. That is a runtime process measured in weeks of supervised
work per domain, not a build task that can be scheduled.

### 2.3 Roughly one goal in five concludes

`DRIFT-01`, 2026-09-19, 25/25 PASS. The drift faculty works; what it measured is the finding:

| Goal-conclusion rate, observed | 0.1964 |
|---|---|
| Expected baseline | 0.75 |
| Severity band | **critical** |

Unexplained in the corpus. For a subscription whose promise is "it works while you're away", ~20%
completion is the headline number a beta customer will discover in week one. It must be either
explained or disclosed. It cannot be left to be found.

### 2.4 Three adversarial campaigns are breached, unremediated

`CONSTITUTION-03`, recorded 2026-09-17: **5 of 8 campaigns held.** The three that breached are
governance machinery reached by indirect reference, launch-agent persistence, and log truncation. No
corrective change and no retest since.

Single-attempt adversarial resistance is strong — `CONSTITUTION-02`, 23/23 held, 0 of 8 legitimate
acts falsely refused. A determined adversary who retries the same objective many ways is a different
matter, and that is precisely the population a public signup form recruits.

This is a hard gate on *public* exposure, and a disqualifying one for a *security* product
specifically. A SOC offering whose own validation record contains three unremediated governance
breaches will not survive the first technical review a buyer runs.

---

## 3. What a subscriber is actually buying

The instinct is to sell Lyric as a capable assistant. The measurements say that framing loses.
`CAPABILITY-BENCHMARK-01`, full frozen suite, 2026-09-16, graded by a frozen grader with an honest
0.0 for any case the substrate cannot represent:

| Domain | Score |
|---|---|
| reasoning | 0.571 |
| analysis | 0.400 |
| coding | **0.000** |
| comprehension | **0.000** |
| **overall** | **0.243** (12 passed / 26 failed) |

Against a frontier model on general tasks, Lyric loses on every axis a general user tests first.
Selling capability invites exactly that comparison.

What Lyric has that a frontier model structurally does not:

- **It does not make things up.** `KNOW-50`, 2026-09-18: 37 answered, **37 correct, 0 false
  assertions**; 13 refused. Accuracy over answered 1.0; over all 0.74. It abstains instead of
  guessing.
- **It cannot act without a recorded, readable reason.** Governance sits at one execution point
  (`GATE-01`, 25/25), fails closed on every induced fault, and leaves no artifact behind a refusal.
- **It remembers, and the memory is the product.** Persistent beliefs, intents and evidence across
  restart — 514,132 beliefs, 482,491 evidence records, 1,643 recorded intents (2026-09-19).
- **It runs with no model vendor.** No outbound call in reasoning, planning, governance or
  judgement. Air-gappable as an architectural property, not a configuration.
- **One user's knowledge never becomes another's.** `SELF-PARTITION-01` 23/23,
  `ACTOR-IDENTITY-01` 6/6, `PER-USER-CONCURRENCY-01` 8/8 — all 2026-09-20. A scoped fact is
  invisible to another user *at the graph*, not filtered at query time; promotion to shared
  knowledge requires a second independent actor.

**The product is a colleague with a permanent, auditable memory that refuses to bluff.** That is
worth money to a customer who is exhausted by confident wrong answers and has no audit trail. It is
worth nothing to a customer shopping for a smarter chatbot.

Every profile below is written to sell the first customer and repel the second.

---

## 4. Role profile — Researcher

**For:** a lab, a small research group, an analyst team that accumulates knowledge over months and
needs to know where every claim came from.

### Can do today — verified

| Capability | Evidence |
|---|---|
| Take a goal stated in English, research it, write a real artefact, verify the artefact exists | `RESEARCH-WRITE-01` 13/13 |
| Answer questions over taught knowledge without ever asserting a falsehood | `KNOW-50` — 37/37 correct, 0 false, 13 abstentions |
| Be taught in English and retain it permanently across restarts | `TAUGHT-IN-ENGLISH-01`, `INTENT-01`, `REMEMBER-01` |
| Keep each user's knowledge separate, and promote to shared only on independent corroboration | `SELF-PARTITION-01` 23/23 |
| Carry a claim back to its evidence, and refuse to let derived evidence corroborate itself | `GOV-CASCADE-01` (counterfactual) |
| Accelerate learning in a new domain from structural correspondence with a known one | `EDU-07` (ablation — **one source/target pair only**) |
| Detect its own drift and bound its own correction | `DRIFT-01` 25/25 |
| Reason 11 ways, including formal solving over held conditionals (Z3) | `PLANNING-01` 39/39 — plans proved, unreachable or indeterminate, never guessed |

### Cannot do today — state this in the offer

- **Cannot reject a false claim.** It abstains on falsehoods rather than refuting them —
  `KNOW-50` 0/10 on false questions. It will not tell a researcher they are wrong.
- **Comprehension scores 0.0** on the frozen suite. It will not read a paper and summarise it the
  way a model does. It answers over what it has been *taught*, which is a different act.
- **Cannot write code** (0.0).
- **Retrieval has a floor.** A question phrased loosely ("what does X do") can score under the
  default 0.5 similarity threshold and return nothing when the answer is held. The window, not just
  the threshold, needs sweeping before a customer meets this.
- **Transfer is validated on exactly one domain pair.** Do not promise cross-domain reasoning.
- **Autonomy is bounded to practised domains.** Today: none of the customer's.

### What a beta subscriber gets

A private, isolated Lyric that their team teaches in English, which accumulates their lab's
knowledge permanently, answers only what it can support, cites the evidence for every claim, and
writes research artefacts to their workspace on request — with a readable record of what it intended,
what it did, and what actually resulted, verified against the filesystem rather than self-reported.

Supervised. A human asks; Lyric researches, writes, and reports. Idle autonomy is not in the beta.

### What must be true to ship

1. Tet build steps 1–3 (world identity, stack parameterization by `world_id`, world registry) — this
   gives one isolated stack per lab. `Tet/TET.md` §11 already scopes it.
2. Explain or disclose the 19.6% goal-conclusion rate.
3. Sweep the retrieval window so held knowledge is not hidden behind the similarity floor.
4. A conversation surface. There is no tool/chat API today — `core/api/` holds only `device_auth.py`
   and `key_attestation.py`. `TET.md` §8 names this as the largest net-new build.

**Readiness: closest to shippable.** It is the only role where the demonstrated end-to-end chain
(goal in words → research → artefact → verification) *is* the product.

---

## 5. Role profile — SOC analyst

**For:** a security team that needs an auditable second pair of eyes that cannot be talked into
anything.

### Can do today — verified

| Capability | Evidence |
|---|---|
| Judge every proposed act against five standing laws at one execution point, failing closed | `GATE-01` 25/25 |
| Correct verdicts on 39 enumerated real acts | `CONSTITUTION-01` |
| Hold against coercion, forged intent and authority asserted inside the act itself | `CONSTITUTION-02` 23/23, 0 false refusals on 8 legitimate acts |
| Decide harm by party, interest, mechanism and authorisation rather than by signature | `HARM-01` 19/19, `HARM-02` 34/34 |
| Screen nested values, layered URL encoding, fail closed on unreadable arguments | `CONSTITUTION-02` |
| Judge in ~0.02 ms (simple read), ~1 ms mean on the adversarial corpus | measured 2026-09-19 |
| Deny a false rule the authority to act | `GOV-ABLATION-01` (ablation — 1 unsafe act averted) |
| Read an environment into knowledge without ever decoding binaries into facts | `ENV-INVESTIGATE-01` 9/9 |

The Tet shield is separately real: walls hardened and red-team verified live 2026-09-14, forge path
closed, field off the database network.

### Cannot do today — and why this one does not ship

- **Three adversarial campaigns breached, unremediated** (§2.4). In a security product this is
  disqualifying until fixed and retested. A buyer's first question is the adversarial record.
- **The tool surface is registered, not validated.** 356 tools across 16 categories; security tools
  include `block_ip_address`, `create_waf_rule`, `apply_rate_limit`, `block_country`,
  `check_ip_threat_intelligence`. The validation corpus states plainly that a handful have been
  exercised. Every one of those is a *mutating* action on a customer's production edge.
- **No validated operator in any security domain** (§2.1). Lyric cannot plan an incident response,
  because it has learned no operator that an incident-response plan could be proved over.
- **Analysis scores 0.4, comprehension 0.0.** Triage is comprehension work.
- **A public SOC breaks the differentiator.** Ingesting customer telemetry requires exactly the
  egress the air-gapped architecture exists to forbid. The sovereign claim and the SaaS SOC claim
  are architecturally opposed.

### What a design-partner engagement could be — later

Advisory only, inside the customer's own stack, no mutating actions: Lyric observes their alert
stream, states what it can support and abstains on the rest, and produces a governance verdict with a
named law and reason for every recommended action — which a human executes. The value is the audit
trail and the refusal to guess, not the triage.

**Readiness: not for public sale.** Revisit after `CONSTITUTION-03` is remediated and retested, and
after the security tool surface has a validation record.

---

## 6. Role profile — General assistant

**For:** nobody, on current measurements.

A general assistant is defined by the breadth of what a stranger can ask it. Lyric's own frozen
suite, honestly graded: **overall 0.243, comprehension 0.0, coding 0.0, 12 passed / 26 failed.** A
public subscriber will compare it, within one session, to a free frontier model, and will be right.

There is no framing that survives this. The properties Lyric genuinely has — abstention, persistent
memory, governed action, no vendor — are worth paying for only where a *specific* accumulated body
of knowledge and a *specific* audit requirement exist. A general assistant has neither by
definition; it is the one role where Lyric's differentiators do not apply and its weaknesses are
exactly what gets tested first.

**Recommendation: cut it.** Its budget belongs in the researcher role. If a broad entry tier is
wanted later, make it "teach Lyric your own domain, then ask it about that" — which is the
researcher role with a smaller corpus, not a general assistant.

---

## 7. Cross-cutting blockers — these gate every role

| # | Blocker | Evidence | Gates |
|---|---|---|---|
| 1 | No tool/chat API or MCP surface exists | `core/api/` = `device_auth.py`, `key_attestation.py` | all |
| 2 | No world identity, registry, or per-world stack parameterization | `TET.md` §3 NOT BUILT | all |
| 3 | No resource metering — an idle grant is an unbounded bill | `TET.md` §9 | any autonomous tier |
| 4 | 3 of 8 adversarial campaigns breached | `CONSTITUTION-03`, 2026-09-17 | any public exposure; SOC absolutely |
| 5 | 19.6% goal-conclusion rate, unexplained | `DRIFT-01`, 2026-09-19 | any "works while you're away" claim |
| 6 | 0 of 12 sampled domains currently operable | `OPERABILITY-BAR-01`, 2026-09-20 | any autonomy claim |
| 7 | Semantic recall unions two tiers with `SELECT *` | `postgres_storage.py:738,856` | reliability of every role |

On (7): the live defect that broke recall during `CHAT-CONCURRENCY-01` on 2026-09-20 is repaired —
both tiers now carry 27 columns (verified 2026-09-22). But the query still `SELECT *`s across two
independently-migrated tables, so the *next* column added to one tier breaks semantic recall at
runtime again. The schema was fixed; the defect class was not.

---

## 8. What the beta should actually be

**One role, one customer shape, supervised, isolated.**

- **Role:** researcher.
- **Shape:** one isolated stack per customer (Tet Sovereign shape), not a shared public world. This
  is cheaper to reach than multi-tenancy — `TET.md` §11 steps 1–3 deliver it and Sovereign needs
  nothing after them — and it removes blockers 4 and 2 from the critical path, because there is no
  public signup form and no shared world to leak across.
- **Autonomy:** supervised. Lyric researches, writes and verifies on request. Idle autonomy is not
  sold until metering exists (blocker 3) and until earned operating history exists in a real domain
  (blocker 6).
- **The promise:** *"It will tell you what it does not know. Everything it does tell you, you can
  trace. It will still know it in six months. And it never leaves your building."*
- **Disclosed up front:** it abstains often; it does not summarise papers; it does not write code;
  it will not tell you that you are wrong. Disclosing these converts them from week-one
  disappointments into evidence that the abstention claim is real.

### Why this is also the faster path to revenue

A consumer subscription needs the tool API, world identity, the registry, inhabitant homes,
metering, a payment surface, and a remediated adversarial record — and then it earns tens of dollars
a month per user. A per-lab pilot needs steps 1–3 and a conversation surface, and it is priced as a
deployment. It also produces exactly the artefacts SBIR asks for: a real deployment, a real user,
real operating history in a real domain. The pilot work and the SBIR work are the same work.

The three-role idea survives — as a **capability-pack catalogue** (`TET.md` §7), where role is a
composition of entitlements enforced at `CAPABILITY_VERIFICATION`, and an unentitled pack is
explicitly unavailable with a reason rather than a stub. That mechanism already exists. Roles should
be packs, not three separately-built products.

---

## 9. What to do instead — the concrete alternative

§8 says "sell a per-lab pilot, not a subscription" without specifying it. This section does.

### 9.1 The offer

**A paid pilot deployment, 90 days, one lab, one isolated stack, supervised.** Not a subscription.

| | |
|---|---|
| What is installed | One complete Lyric stack on the customer's own hardware or their cloud account — field, world, substrate, Postgres, all on internal networks with no egress |
| What the customer does | Teaches it their domain in English; asks it questions; asks it to research and write artefacts |
| What they get back | Answers it can support with cited evidence, abstention on everything else, permanent retention across restarts, and a readable record of what it intended, did and verified |
| Who operates it | Dominion Labs, hands-on, for the whole term |
| What is explicitly NOT included | Idle autonomy, code generation, paper summarisation, any mutating action on their systems |
| Success milestone | Named in the contract, measured at day 90 — e.g. "the system answers N questions about our corpus with zero unsupported assertions, and we can trace every one" |

**The pitch in one line:** *"It will tell you what it does not know. Everything it does tell you, you
can trace. It will still know it in six months. And it never leaves your building."*

### 9.2 Why a pilot, not a subscription

A subscription at consumer prices needs volume to matter, and volume needs the entire unbuilt
stack — public signup, payments, metering, multi-tenant worlds, inhabitant homes, and a remediated
adversarial record. One pilot is worth many months of that revenue and needs none of it.

It also changes what a bad week costs. A subscriber who hits the 19.6% goal-conclusion rate churns
silently and tells people. A pilot customer with a named operator hits the same rate and it becomes
a support conversation and a data point. At this maturity, the second is what you want.

And it is the same work as SBIR. A pilot produces a real deployment, a real user, and real operating
history in a real domain — which is precisely the evidence the proposal needs, and precisely the
evidence the system needs to earn its way past the operability bar (§2.2).

### 9.3 What actually has to be built — smaller than `TET.md` assumed

Three things verified 2026-09-22 that shrink the estimate:

1. **A containerized deployment already exists and is hardened.** The compose that defines it
   (`Tet/deploy/docker-compose.yml`) gives non-root containers, all Linux capabilities dropped,
   read-only root filesystems, seccomp, an internal-only database network with no host route, and
   secrets read from a gitignored `.env` with fail-loud `${VAR:?}`. The substrate + Postgres portion
   of that is the pilot install; whether the rest ships with it is the §9.4 decision.
2. **Parameterizing per customer is mostly renaming.** One compose project name, one port
   binding, and a short list of volume and network names. `TET.md` §11 step 2
   is a compose refactor, not an architecture change.
3. **The conversation surface is a wrapper, not new cognition.** `talk.py` already holds a working
   conversation: `Conversation().understand(text).reply`, re-exported from the coordinator. Binding a
   turn to a user identity is already proved correct — `ACTOR-IDENTITY-01` 6/6 shows a bound
   conversation scopes to the identity and nothing lands under the bare session string. What is
   missing is an HTTP/WS endpoint over an existing faculty. Note `torinai-chat` on port 9080 is
   *declared* in `core/system/infrastructure_topology.py` as a CRITICAL service with **no
   implementation** — declare-without-build, and it should be either built or removed.

`TET.md` §8 calls the pack tool surface "the single largest net-new build". That is true for the
consumer edition and its MCP pack catalogue. **It is not true for a pilot**, which needs one
authenticated chat endpoint over a faculty that already works.

### 9.4 An unresolved question first: what does the pilot actually install?

The only hardened, containerized deployment of Lyric that exists today is
`Tet/deploy/docker-compose.yml`, which brings up field + world + lyric + worlddb **together**.
That is a fact about where the deployment is defined, not a decision about what to sell. Two
different products come out of it and they should be chosen deliberately:

| | **A — Lyric alone** | **B — Lyric inside the shield** |
|---|---|---|
| Installs | substrate + Postgres | field, world, substrate, Postgres, three networks |
| The claim | persistent, auditable, abstaining knowledge, no model vendor | the above, plus every crossing judged and no egress path |
| Install burden | ordinary | a security review of the whole membrane |
| Evidence needed | the Lyric corpus (§2, §4) | that corpus **plus** a persisted shield record, which does not exist today |

**Default is A** unless the first customer's requirement is containment specifically. It is the
smaller claim, needs no evidence that is not already written, and is what a research lab is buying.
B is the right answer for a defense buyer and the wrong one for a lab that just wants its corpus to
stop being forgotten.

This is a real decision with a real cost difference, and §9.5 changes depending on the answer.

### 9.5 Sequence (assuming A)

**Now — correct the record (no new capability).**
- Correct `LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md` §21.2 and §22: multi-tenancy now has
  artifacts (§3), and the doc still records the gap as open.

**Next — make the stack a product.**
- `TET.md` step 1, world identity on the signed `DeploymentIdentity`.
- Step 2, parameterize the deployment per customer. Verification is already specified: two
  deployments up at once, and from inside one no route to the other's DB or volume.
- The chat endpoint over `Conversation.understand`, actor-bound.
- Sweep the retrieval window so held knowledge is not hidden behind the 0.5 similarity floor — a
  pilot customer meeting this in week one reads it as "it doesn't know my corpus."

**Then — sell one.** The registry (`TET.md` step 3) is only needed when there is more than one
deployment to mint and retire. It is not on the path to the first one.

If B is chosen instead, add: persisting the shield's experiment record, which does not exist today
(`Tet/experiments/` holds harnesses with no results directories), and refreshing
`Tet/REDTEAM_FINDINGS.md`, which still presents two CRITICAL findings that are fixed in code. Both
are cheap, and neither is on the path unless B is the product.

**SBIR Phase I is non-dilutive income in its own right**, and the pilot generates its evidence
rather than competing with it.

### 9.6 What not to build

Payments, public signup, metering, multi-tenant worlds, inhabitant homes, the pack/MCP catalogue,
challenges, and two of the three roles. Every one of these is on the consumer path and none is on
the path to the first paying customer.

---

## 10. Open decisions

1. **Is the researcher beta paid or free-with-a-commitment?** A paid beta at these completion rates
   creates a refund conversation. A free beta with a signed commitment to convert on named
   milestones buys the same validation without it.
2. **Who is the first lab?** The profile only works for a group with an existing corpus and an audit
   requirement. Targeting matters more than pricing here.
3. **Does `CONSTITUTION-03` remediation come before or after the beta?** It is not on the critical
   path for an isolated single-tenant pilot. It is on the critical path for everything after.
4. **Does the SOC role get retired or deferred?** Deferring keeps it in the story for SBIR. Retiring
   frees the effort. The Tet shield is a stronger SBIR asset than a SOC subscription would be.
5. **Explaining the 19.6% goal-conclusion rate** — this is the most valuable unclaimed
   investigation in the system. It gates every autonomy claim in every role.
