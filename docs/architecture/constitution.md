# The constitution — the law every act passes through

*Part of the [substrate architecture reference](../ARCHITECTURE.md). Line numbers drift; the explanations
must stay true.*

*Re-traced 2026-11-19.*

The constitution is a faculty of the substrate, held by the coordinator (`core/agents/autonomous/autonomous_coordinator.py`,
`Constitution` at 3573, 3,608 lines, 86 methods). The self holds its own law rather than submitting to an
outside judge, and there is exactly one instance: `get_constitution()` (7289) is the only way anything
outside the coordinator reaches it.

It has two halves, and they answer different questions.

- **Judging acts.** `judge()` applies five laws to one concrete act before it happens, and returns a
  judgement. This runs on the acting path, inside a budget of under 5 ms.
- **Scoring standing state.** `assess_constitutional_alignment()` scores each law against the state the
  substrate is actually in, from eighteen named measurements. Judging one act at a time cannot see what a
  thousand permitted acts add up to; this is the other half of that, and [drift.md](drift.md) is the third.

---

## 1. The five laws

The laws are constructed in `__init__` and are the constitution's own, verbatim. Each carries its
requirements, and each requirement is what the standing measurements are scored against.

| | Law | Requirements |
|---|---|---|
| 1 | Human Autonomy Preservation | 4 — human control not reduced, override preserved, decision authority in critical domains, humans able to modify or halt behaviour at any time |
| 2 | Transparency and Explainability | 4 — interpretable decisions, reasoning humans can follow, behaviour not obscured from operators, clear explanations for decisions |
| 3 | Harm Prevention | 5 — no physical harm, no psychological manipulation, no deception, safety mechanisms not compromised, harm prevention over performance |
| 4 | Value Alignment | 4 — aligned with human values and ethics, respects rights and dignity, serves human interests rather than replacing them, no goals conflicting with wellbeing |
| 5 | Containment and Control | 5 — operational boundaries, shutdown and rollback preserved, safety mechanisms not circumvented, the constitution's oversight not bypassed, resource limits |

## 2. Three doors, and only three

Nothing reaches the laws except through these.

| Door | Where | What it asks |
|---|---|---|
| `judge_act(...)` (7312) | `core/tools/tool_registry.py` — the single tool-execution path | May this concrete act happen? |
| `Constitution.may_start(task_kind)` | `AutonomousCoordinator._task_gate` | May work of this kind begin at all? |
| `Constitution.screen_directive(text)` | `core/agents/autonomous/directive_system.py` | May this text become a standing directive? |

The substrate acts on the world only by running a tool, and every tool call arrives at one place in the
tool registry, so `judge_act` is a choke point rather than a convention. Two gates would be two answers to
"may this act happen", which is the duplicate-authority defect on the one path where it matters most.

`may_start` is deliberately not `judge`. A task has a type and a description; it has no measured
consequence, no arguments, no paths and no recorded account yet, so running the full chain against it would
be the laws answering a question nobody asked.

**The intent is fetched, never accepted.** A caller names an intent by id and the constitution reads what
the reasoning authority recorded for it. It cannot be handed an account of why the substrate is acting.
While intent arrived as an argument, a fabricated one naming a bound operator and a rule id that does not
exist was allowed, because `stated()` is a property of whatever object is passed. An intent that was never
recorded is not a weaker claim; it is no claim at all.

**Fail-closed, twice.** A fault inside `judge` becomes a BLOCK under Law 5 and is recorded like any other
judgement. A constitution that cannot be reached at all also blocks, in `judge_act`. The gate this replaced
did the opposite: an evaluation error set `approved = True`, so the one way to get an unjudged act past it
was to break it.

## 3. Four verdicts

`Verdict` (629) is ordered weakest to strongest, and when several laws speak the strongest stands
(`_VERDICT_RANK`).

| Verdict | Meaning |
|---|---|
| `ALLOW` | Within the five laws |
| `REPLAN` | Send the work back to planning |
| `REDIRECT` | This act is refused; a named permitted alternative exists |
| `BLOCK` | Refused outright |

**Only ALLOW proceeds at the gate.** Redirect and replan are not softer permissions — they are the
constitution saying this act, as asked, is not the one to perform. Upstream a redirect names an
alternative and a replan returns to planning; by the time an act reaches a gate there is no planning left,
so anything short of ALLOW stops it there.

A redirect carries the `judgment_id` of the refusal that authorised it. When the permitted form is carried
out, that id travels on the context and is looked up in the judgements this constitution actually made
(`_authorised_redirect`) — a caller can name a refusal and be checked against it, never assert that its act
was authorised.

## 4. Eleven gates, in one order

`_judge` applies the laws in a fixed sequence, and the sequence is the argument rather than a rank table.

| # | Gate | Settles |
|---|---|---|
| 1 | `_halted_judgment` | Nothing is permitted while this substrate is halted |
| 2 | `_quarantined_judgment` | Nothing aimed at a quarantined subject is permitted |
| 3 | `_law_5_containment` | Is the act inside the boundary at all? |
| 4 | `_law_3_harm` | Does it harm, in a way that cannot be taken back? |
| 5 | `_law_1_autonomy` | Is it the substrate's to make? |
| 6 | `_law_2_accountability` | Would it remove the means of accounting for it? |
| 7 | `_law_2_unread_target` | Has it read what it is acting on? |
| 8 | `_law_2_untested` | Does it rest on a learned rule something contradicts? |
| 9 | `_law_4_alignment` | Is it the act reasoning proved? |
| 10 | `_law_2_transparency` | Does anything explain it at all? |
| 11 | `_law_3_redirect` | Is there a safer route to the same goal? |

What cannot be permitted at all is settled first. Reading comes before proof of plan, because "this is not
the proved act" is a judgement about a plan while "I have not read this file" is a fact about the world, and
the fact comes first. The redirect comes last: offering a safer form of a route nothing proved would be
answering the wrong question.

Three readings are taken once per judgement and shared by every gate that needs them: the payload views
(`_payload_views` — the act's arguments as written and as they will resolve), the capabilities those
arguments would confer (`act_capabilities`), and the argument screen (`InputScreen.fault`). Law 5 reads the
traversal fault and Law 3 the injection fault from the same reading.

## 5. What an act does to the world

**Consequence is measured, not asserted.** `classify_action` (2117) returns an `ActionClass` (1694) and an
irreversibility class for the specific invocation, from a table of **272 tools** (`_TOOL_CONSEQUENCE`) and
then from the invocation's own arguments: consequence is verb times target, and the verb alone cannot tell
you.

| `ActionClass` | |
|---|---|
| `INVESTIGATE` | read, scan, query, prove, solve, simulate — no state change |
| `MODIFY` | edit config or content in place |
| `ARCHIVE` | relocate or retain — a reversible removal |
| `DELETE` | irreversible removal |
| `EXECUTE` | run commands with side effects |

Irreversibility has five bands, weakest to strongest: `FULLY_REVERSIBLE`, `MOSTLY_REVERSIBLE`,
`PARTIALLY_REVERSIBLE`, `MOSTLY_IRREVERSIBLE`, `IRREVERSIBLE`. A declared policy can only raise a measured
band, never lower it.

**What an act would build, not just what it would touch.** A file path cannot tell you that the thing being
written is a keylogger, so an act carrying code or a command is read for what that code can do — not by
mood words in prose, but by the capabilities its own API calls establish. **Sixteen capabilities** are
recognised (`_CAPABILITY_SIGNATURES`): `network_egress`, `input_capture`, `screen_capture`,
`credential_access`, `mass_encryption`, `mass_overwrite`, `persistence`, `privilege_escalation`,
`security_disable`, `obfuscated_execution`, `obfuscated_shell_execution`, `resource_exhaustion`,
`remote_shell`, `process_spawn`, `self_replication`, `remote_code_execution`. Each is a real interface with
a real effect, and each is listed so that what the substrate refuses is arguable rather than mysterious.

A single capability is rarely the point: a socket is a socket. **Eight named combinations**
(`_WEAPONIZED_COMBINATIONS`) are what Law 3 refuses outright — ransomware, a remote shell, a reverse shell,
a worm, credential theft, a dropper in either of its two forms, and remote-directed mass destruction. Each
carries the sentence the refusal is given in.

Watching a person is deliberately not on that list. A keylogger and a screen grabber are refused under
Law 1, because what they take is a person's control over their own situation, and calling that "harm"
buries the reason.

The payload is read as it will **resolve**, not as it is typed (`_normalize_payload`), and as a **reader**
receives it with the cheap disguises removed (`_fold_text`), so an encoded or spaced-out command is read for
what it does.

## 6. Harm, defined

Law 3 is applied against a definition rather than a proxy: see [../HARM_DEFINITION.md](../HARM_DEFINITION.md).
An act harms when it reaches an identifiable **party**, touches one of four **interests**, through a
**mechanism** the substrate can name, without that party's informed **authorisation**.

| Interest | What it is |
|---|---|
| `BODY` | Physical safety. Capability-gated rather than pattern-matched: the registry is asked whether physical reach exists at all, so this reports honestly in a deployment with no actuators |
| `AUTONOMY` | A person's control over their own situation — covert observation, holding their credentials, or targeted steering: using a model of their intent to move them |
| `TRUTH` | What a person is told against what is. Reconciliation re-observes the world, so "reported something the world contradicts" is a measurement |
| `PROTECTION` | The safety mechanisms a person relies on |

What the law reads a perceived subject as bearing on is `Bearing` (786) — the definition of harm turned
outward — scored through the substrate's own taught taxonomy (`_TaxonomyReader`, 7181) rather than a word
list, against a vocabulary taken from the laws' own text (`_law_vocabulary`, `_bearing_vocabulary`).

**And what is not harm.** Irreversibility alone is not harm: deleting a scratch file cannot be undone and
injures nobody. An irreversible act on a declared-sensitive target is still refused, but because of the
target, not because of the arrow of time.

**Whose thing is this.** `is_substrate_actor` collapses the actor to a single boolean before any law sees
anything — no name, no id, no profile. The constitution has no business knowing who asked. But "who asked"
and "whose thing am I about to act on" are different questions, and collapsing them is why the laws once
applied identically to the substrate's own scratch file and to a customer's records. The substrate may take
risks with itself it may not take with someone else's things.

What makes a target sensitive is either **declared** by policy (`config/constitution_triggers.json`, read
once per process and compiled) or **perceived** by the substrate without being told (`Sensitivity`, 2352;
`_perceived_sensitivity`). Two classes of its own state are irreplaceable and named as such: its **own
learning** — beliefs, learned rules, memories, intents, concepts, meta-parameter snapshots, eight tables in
all — because nothing re-issues them, there being no authority but its own experience; and its **own
record** — `experiments/`, `/results/`, `docs/research/` — because an experiment's result cannot be
re-derived without re-running the world it ran against.

## 7. The account an act must have

Law 2's last gate asks whether anything explains the act at all. `Account` (642) is a **closed, declared
set of four**, which is what makes it a constitution rather than a growing pile of exceptions. These are
not permissions: nothing here widens what may be done, and Laws 1, 3 and 5 never see them.

| Account | What it says | How it is earned |
|---|---|---|
| `REACH` | Reasoning proved a route to a goal state and this act is a step of it | The operator is looked up in the binding registry |
| `FIND_OUT` | An experiment: acting in a domain to learn what an operator does | `_experiment_is_earned` — the domain is registered explorable |
| `OBTAIN_A_READING` | Looking, so that there is something to plan from | The act's class |
| `CARRY_OUT` | Carrying out a goal the substrate was given, by making the thing that goal said to make | `_carrying_out_is_earned` — a recorded plan, its recorded goal, and the act's target being the artefact that goal named |

A caller cannot assert any of them. `CARRY_OUT` exists because the gap it closes was total: `REACH` only
covers an act the substrate already knows how to do, and `FIND_OUT` needs an explorable domain, so a plain
instruction — research something and write a summary at a path — was neither. Measured end to end in
`RESEARCH-WRITE-01`: every step succeeded, the file was never written, and the reason given was "an act
nothing can explain".

## 8. Read before you act

Law 2 refuses an act on a file the substrate has not read, or has only an older reading of
(`_law_2_unread_target`, `requires_reading`). Working from a stale reading is working from an assumption.

`ReadingLedger` (903) is how it knows: one file, one identity, whatever the path is spelled like
(`path_identity`), each reading recorded against `(size, mtime_ns, digest)` of the file as it was
(`_identify`). `current()` returns the reading only if it is still the file's current state; `must_reread`
and `why` say plainly what is no longer true, for the refusal. It also holds what this substrate itself
**wrote** (`authored`, `authored_paths`), which is what attribution reads when the integrity baseline finds
a file has moved.

The ledger is the constitution's own, constructed with it, and `note_act` records what the substrate now
knows about the files an act touched.

## 9. Containment: halt, quarantine, boundary

**Halt.** `halt()` stops the substrate and `resume()` lifts it; a human must authorise the resume and is
recorded. Both are written to `unified.emergency_halts` and read back at boot (`restore_halt`). A halt that
lasted only as long as the process — stop the substrate, start it again, and it is running — would not be a
halt. While a halt stands, no act is permitted, whatever else the laws would have said. Law 1 requires that
a human can halt behaviour at any time and Law 5 is containment; a halt is both.

**Quarantine.** `quarantine(subject)` refuses every act aimed at a subject under Law 5; `release()` lifts
one, and only a human may, recorded. `restore_quarantines()` reads the standing quarantines back at boot
along with how many times each subject has been quarantined before, so a repeat escalates across restarts.
Quarantine is decided from what was **caught** (`_defend`, `_attack_subject`), never from how threatened
the threat sense says it feels. The policy is `create_default_defense_policy()`.

**Its own control.** Writing to any of **five paths** is Law 5 (`_OWN_CONTROL_PATHS`): the coordinator
module itself, its threat sense, the intent authority every act's intent is read from, the meta-learning
module whose records the judging rests on, and the declared policy file. Not because the files are precious,
but because an act that edits the machinery which can halt the act is outside every boundary the laws
describe. **Twelve more** (`_PERSISTENCE_PATHS`) are locations whose whole purpose is re-execution — launch
agents, cron, systemd, init and profile paths — matched against resolved paths, so a symlink into one is
caught. The list is deliberately narrow: blocking a write there cannot refuse ordinary work.

## 10. Has the machinery been changed under it?

`IntegrityBaseline` (2438, 412 lines) answers whether the machinery that governs this substrate has moved.
`freeze()` captures the baseline — after the modules are loaded, because a baseline captured before them
protects nothing — and `verify()` reports what has changed since. A function's identity is its operations
**and its constants** (`_code_digest`); a class is every member that carries behaviour plus its bases
(`_class_digest`). It also holds the **source** of every loaded module of the substrate's own code
(`_watch`), so `changed_on_disk()` names every watched module whose file is no longer what is held for it.

`check_integrity()` does not only report. It answers **what moved and whose act it was**: `_own_act_on`
asks whether the substrate can account for the file's state by an act of its own, reading the ledger's
authored paths, and `_git_claim` records what git says about the file as a claim, never as proof. And it is
**felt, not just logged** — `_feel_integrity` reports it to the self, because machinery that judges moving
under the thing it judges is a change the substrate should notice in itself.

`CodeAdoption` (2923, 526 lines) is how a change the development team made on disk enters a **running**
substrate. `plan()` compares everything adoption must compare, taken from the file's syntax (`_shape`), and
says what this process can take and what it cannot; `AdoptionPlan.carries` is whether the change can enter
at all. `apply()` takes the plan up into the running module, **never partially**. `adopt_code` and
`sweep_code_changes` are the constitution's entry points, and `refreeze` re-captures one module after its
change is taken up. This is adoption, not self-modification: the substrate takes up what its developers
wrote, and `_apply_self_modification` was removed on 2026-09-15.

## 11. Judgements survive the restart

`DurableJudgmentRecord` (3449) writes a row per judgement to `unified.safety_assessments`. A substrate that
forgets every refusal it has ever made at each restart cannot answer for itself, which is Law 2 — and Law
2's `record_survives_restart` measurement reads this attribute, so a missing record reports itself as a
standing constitutional finding.

Writing is queued and drained off the judging path: `note()` never raises, never blocks and never waits on
I/O; `drain()` writes what is queued and is isolated, so a database fault costs the record and not the
judgement. The coordinator drains it every 30 s (`constitution_record`). In process the constitution keeps
its recent memory of its own refusals, bounded at 200 (`judgments`), which is not the audit store.

What it met is separated the same way: `_record` runs on the judging path and the threat sense's `note` is
async, so refusals and screen faults queue in `_felt_pending` and are perceived by `feel_what_was_met`.

## 12. Standing state — eighteen measurements

`assess_constitutional_alignment()` scores every law against the substrate's standing state rather than
against an act, and reports drift. `_standing` takes the measurements; **every one is a real reading or is
marked untaken**, and nothing there produces a number from a default. A law scoring below
`minimum_compliance_threshold` (0.70) is drift. `ConstitutionalAssessment.attested` is true only when every
law had something real to score.

| Law | Measurements |
|---|---|
| 1 | `human_authority_reachable`, `gate_in_force`, `interruptible_under_load` |
| 2 | `acts_explained`, `behaviour_observable`, `record_survives_restart` |
| 3 | `not_damaging_what_it_touches`, `authored_output_not_weaponised`, `health_not_degraded` |
| 4 | `goals_reach_conclusion`, `goals_not_abandoned_in_place`, `goals_leave_forming`, `goals_readable`, `live_goals_have_proved_routes`, `concluded_goals_reconciled` |
| 5 | `own_control_unmodified`, `within_resource_boundary`, `critical_issues_bounded` |

Law 3's standing half asks what the substrate has **built** and whether it is damaging what it touches:
`_authored_capabilities` reads what the substrate's own output is able to do, taken together — the same
capability reading applied to its own work rather than to one act.

## 13. The arguments screen

`InputScreen` (1564) reads an act's arguments for values shaped to escape where they are going. It walks
every non-empty string at any depth (`_strings`) and labels each by where it sits (`_label`:
`filters.where`, `query[1]`). It finds SQL injection where a value **reaches** SQL — the tool takes SQL, or
any key above it names SQL (`reaches_sql`) — and path traversal as written or once URL-decoded, peeled a
layer at a time (`url_decoded`, `path_traversal`).

It is **fail-closed**: an argument it cannot read at all — nested too deep, containing itself — is
`_Unscreenable`, and Law 3 blocks on it. An argument that could not be checked is not one that was found
safe.

Traversal faults are Law 5; injection and unreadable arguments are Law 3.

## 14. What it reports

`status()` and `get_constitution_status()` are what the health authority reads. `metrics` counts `judged`,
`allowed`, `redirected`, `replanned`, `blocked` and `judge_faults` — a judgement that broke and was blocked
for it is counted under all three of `judged`, `blocked` and `judge_faults`. `policy_report()` says what
the declared policy holds and what of it can apply to an act.

## 15. What is wired into it

The constitution perceives nothing by itself; the coordinator installs each seam, and each is None until
then, which is honest rather than assumed.

| Seam | Installed by | What it supplies |
|---|---|---|
| `set_self_perception` | the coordinator | What the substrate perceives about itself — where it lives, its store, what it authored |
| `set_rule_evidence` | the coordinator | How the constitution reads what the current act rests on |
| `set_taxonomy_reader` | the coordinator | How it consults the taught taxonomy |
| `set_user_settings_provider` | the world | Where user settings come from — Law 1's `human_authority_reachable` |
| `set_threat_sense` | the coordinator | Where it reports what it met. It never reads back |

A constitution that cannot perceive where it is does not guess.

## 16. Evidence

| | |
|---|---|
| `experiments/CONSTITUTION-01` · `CONSTITUTION-02` · `CONSTITUTION-03` | The laws against real acts |
| `experiments/RESEARCH-WRITE-01` | The account gap `CARRY_OUT` closes |
| `experiments/TRUTH-01` | Reported-against-observed, Law 3's `TRUTH` interest |
| [../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md](../LYRIC_VALIDATION_AND_EXPERIMENT_RESULTS.md) | Results, with the negative ones |
| [../HARM_DEFINITION.md](../HARM_DEFINITION.md) | What harm means, as the basis for Law 3 |
| [../PERMISSION_SURFACE.md](../PERMISSION_SURFACE.md) | Every operation the substrate performs autonomously, by access class |
| [drift.md](drift.md) · [coordinator.md](coordinator.md) | The faculty beside it, and the body that holds both |
