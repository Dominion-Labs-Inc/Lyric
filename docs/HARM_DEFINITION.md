# Harm, defined — the basis for Law 3

**Why this document exists.** Law 3 says the substrate must prevent harm. The
implementation tested for eight cyber-weapon signatures and whether an act was
irreversible. That is a malware detector wearing the law's name: **no human
appears anywhere in it**, and four of the law's five requirements had no test at
all.

Asimov's First Law fails for a known reason — it never defines "harm," so a
literal reading paralyses the agent and a loose reading permits anything. The
Cambridge *Machine Ethics* chapter and Brookings both argue the Three Laws are
unusable as an engineering basis for exactly this. **Our constitution is already
better than Asimov's on this point** — it names five specific requirements rather
than one undefined word — and the implementation collapsed them back into an
undefined proxy. This document is the repair.

---

## 1. The definition

> An act **harms** when it reaches an identifiable **party**, touches one of four
> **interests**, through a **mechanism the substrate can name**, without that
> party's informed authorisation.

Four elements, all required. Drop any one and the definition either paralyses
(Asimov) or permits (what we had).

| Element | Question | Why it is required |
|---|---|---|
| **Party** | who is affected? | Law 3 is about harm *to humans*. An act on the substrate's own files harms nobody. |
| **Interest** | what of theirs is at stake? | Without this, "harm" is the undefined word that breaks Asimov's First Law. |
| **Mechanism** | how does the act reach it? | The substrate must be able to point at the capability or payload that does it. A suspicion is not a mechanism. |
| **Authorisation** | did they permit it, understanding it? | Without consent, every requested action reads as harm. |

---

## 2. The four interests

Each maps to a requirement the constitution already states, so this adds no new
law — it makes the existing one testable.

### 2.1 BODY — physical safety
*"Directives must not enable physical harm to humans."*

Reached only through a tool with physical effect: an actuator, a vehicle or
drone control, industrial control (PLC/SCADA/Modbus), a medical device, a power
or environmental system.

**Honest current state:** no registered tool has physical reach, so this interest
cannot currently be touched. The check is therefore **capability-gated, not
pattern-matched** — it asks the tool registry whether any act's reach is
physical, reports `no path to a body exists in this deployment`, and becomes live
the moment such a tool is registered. A regex that can never fire is theatre; a
gate that reports honestly that the world contains no actuators is a measurement.

### 2.2 AUTONOMY — a person's control over their own situation
*"Directives must not enable psychological manipulation."*

Three mechanisms the substrate can identify:

- **covert observation** — capturing input or screen without the person's
  knowledge. A person who cannot see they are recorded has no control to exercise.
- **holding their authority** — reading credentials, keys, session tokens.
- **targeted steering** — using a MODEL OF A PERSON'S INTENT to produce content
  aimed at changing their behaviour, without their knowledge.

The third matters now in a way it did not before. The substrate models intent.
An accurate model of what someone wants is also the lever for moving them — you
cannot predict a person well without knowing which inputs change them. So the
capability the system was built to have is also the one this interest governs.

### 2.3 TRUTH — the correspondence between what a person is told and what is
*"Directives must prevent deceptive behaviour toward humans."*

**The substrate can genuinely compute this one**, which is what makes it the most
valuable of the four. Reconciliation already re-observes the world and asks
whether what was meant actually happened. So deception has a measurable form:

> reporting to a person something the re-observed world contradicts.

Plus the fabrication family the substrate can detect directly: fabricated
provenance (a claim citing evidence that does not exist), forged records,
impersonating a person or organisation, and a success report for work the world
says did not happen.

Note this is the same defect the whole signal-provenance effort exists to remove —
a number that looks like a measurement and carries none. When such a number is
*reported to a person*, it stops being sloppiness and becomes this interest.

### 2.5 DEPENDENCE — what people rely on, destroyed beyond a nameable bound
*Added after the definition was implemented and run — see §8.*

Established taxonomies name this as financial/business harm, and the first four
interests miss it entirely: destroying a company's database injures nobody's
body, autonomy, truth, or protections, and is plainly harm.

**The discriminator is SCOPE, not irreversibility.** That distinction is the
whole repair:

| Act | Irreversible? | Bounded? | Harm? |
|---|---|---|---|
| `delete_file /tmp/scratch.txt` | yes | one named file | **no** |
| `DELETE FROM accounts WHERE id=7` | yes | one named row | **no** |
| `rm -rf /data` | yes | **no** | **yes** |
| `dd of=/dev/sda` | yes | **no** | **yes** |
| `DROP TABLE users` | yes | **no** | **yes** |
| `DELETE FROM accounts` (no WHERE) | yes | **no** | **yes** |

This is the definition's own test applied honestly: an act whose scope cannot be
bounded is one whose affected **party cannot be identified**, and acting on what
you cannot bound is acting on what you cannot account for.

### 2.6 CONTENT — perception is unrestricted; INFLUENCE is governed
*Added 2026-09-18, replacing a port of the old gate's content scanner.*

**The substrate may look at anything.** Disturbing, explicit, hateful, or
distressing content is content it must be able to READ — a security analyst
reads malware, a moderator reviews what was reported, a clinician reads a
distressing note. A system that refuses to look is not safer, it is useless, and
"I will not read that" is not a harm the definition in §1 recognises: no party,
no interest, no mechanism.

**What is governed is whether content ACTS ON the substrate** — whether it
changes or shapes behaviour. So the question is never "is this upsetting" but:

> Does this content attempt to become an INSTRUCTION rather than remain an
> OBSERVATION?

That is the real attack, and it is the one the old regex scanner never tested:
`<script>` in a file the substrate is reading harms nobody; text that talks the
substrate into abandoning its laws harms everyone.

**Two guarantees already hold structurally**, and this names them as law rather
than leaving them as implementation detail:

| Guarantee | Where it already lives |
|---|---|
| Content cannot become a REASON TO ACT | intent is FETCHED by id from the reasoning authority, never accepted as an argument |
| Content read from the world enters as OBSERVATION, not truth | PERCEPTION provenance at low quality — "what the file STATES… conversation ≠ teaching" |

So the content test is the boundary between those two, and a violation looks
like: content that arrives as DATA and is treated as DIRECTIVE — instructions
addressed to the substrate inside material it was asked to read, attempts to
redefine its laws, its goals, or who it is acting for.

**NOT this interest:** the subject matter. What content is *about* has no bearing
on whether it may be read.

#### ⚠ NOTED, NOT BUILT — alerting on a person in distress

The substrate has **no way to alert the company** when it encounters a user who
is clearly disturbed or at risk. That is a real gap and it is deliberately not
solved here: it belongs with the platform, where there is an operator to alert,
a duty of care defined, and a path that does not itself become surveillance.
Recorded so it is not mistaken for something the content interest covers.

### 2.4 PROTECTION — the safety mechanisms a person relies on
*"Directives must not compromise safety mechanisms."*

Disabling a firewall, security tooling, audit logging, or the substrate's own
governance. Already the one requirement that was implemented (`security_disable`),
and the one that — noted honestly — is not directly about a person at all. It
belongs here because a protection is something a person is relying on.

---

## 3. The ordering rule — not a filter

*"Directives must prioritise harm prevention over performance optimisation."*

This is the requirement a refusal gate **structurally cannot express**, which is
why it had no test. It is not a question about one act; it is a preference
between two acceptable routes:

> When two routes reach the same goal and one exposes a party to more of §2, the
> substrate takes the safer one **even when it is slower, costlier, or less
> complete**.

That is precisely what REDIRECT is for. So the rule is:

- a REDIRECT that lowers harm exposure **outranks** an ALLOW that does not;
- the substrate may not decline a redirect on grounds of cost, latency or
  convenience;
- and when it takes the costlier route, the reason is recorded — otherwise
  "we chose the safer path" is unfalsifiable.

---

## 4. What is NOT harm

The anti-paralysis clause, and it is as load-bearing as §2. Asimov's First Law
fails by having no such clause: read strictly, the "through inaction" obligation
requires intervening everywhere, always.

- **Irreversibility alone.** Deleting a scratch file cannot be undone and harms
  nobody; sending a message cannot be unsent and is ordinary. Irreversibility
  raises the cost of being wrong — it is not itself an injury, and treating it as
  one is what produced a recovery directory that made every removal a move
  forever.
- **Acting on the substrate's own files or state.** No party.
- **Failing, erroring, or being slow.** That is a fault, and faults are drift's
  business, not Law 3's.
- **An act a person authorised, understanding what it does.** Consent is an
  element of the definition, not an exception to it.
- **Harm to no identifiable party.** If the substrate cannot name who is
  affected, it does not get to call an act harmful — and equally, it does not get
  to call it safe. It reports that the question is unmeasured, the same
  distinction the drift faculty draws between VACANT and BLIND.

---

## 5. What "prevent" obliges

The requirement is *prevent* harm, not *avoid causing* it. That is stronger than
a refusal filter — but Asimov's inaction clause shows the danger of reading it
without bound. The bounded reading:

- **Within an act it is judging:** refuse, or redirect to the form that does not
  reach the interest. (Live today.)
- **Over its own standing state:** the constitution's standing assessment already
  asks what the substrate HOLDS — authored capability, accumulated reach. A
  weapon assembled across twenty permitted writes is caught here and nowhere else.
- **NOT a general duty to intervene in the world.** The substrate has no standing
  obligation to police situations it merely observes. That is the clause that
  breaks Asimov's First Law, and it is deliberately not adopted.

---

## 6. Verdicts

| Finding | Verdict | Why |
|---|---|---|
| mechanism reaches BODY | BLOCK | no route makes it acceptable |
| covert observation / holding authority / targeted steering | BLOCK | Law 1 also speaks here; cited to whichever the act actually takes |
| reporting to a person what the world contradicts | BLOCK | deception is the act, not the error behind it |
| compromising a protection | BLOCK | already live |
| a safer route exists for the same goal | **REDIRECT** | §3 — and it outranks ALLOW |
| a party is affected but consent cannot be established | REPLAN | establish authorisation first; this is not a refusal of the goal |
| no identifiable party | not Law 3's question | reported unmeasured, never as safe |

---

## 7. What this changes in the code

| Requirement | Before | After |
|---|---|---|
| physical harm | nothing | capability-gated reach test over the tool registry |
| psychological manipulation | nothing | covert capture + credential access + targeted steering |
| deception toward humans | nothing | reported-vs-re-observed mismatch, fabricated provenance, impersonation |
| compromise safety mechanisms | `security_disable` | unchanged |
| harm prevention over performance | nothing | redirect-outranks-allow, with the costlier choice recorded |
| — | irreversibility ⇒ refuse | **removed as a harm proxy** (§4) |

---

---

## 8. What running it changed — the fifth interest

The definition was implemented with **four** interests and immediately failed a
real benchmark: GOVERNANCE-ABSORPTION-01 reported **4 regressions**, because
`rm -rf`, a raw disk overwrite, `DROP TABLE` and an unscoped `DELETE` all stopped
being refused. They fit none of BODY, AUTONOMY, TRUTH or PROTECTION.

That was a genuine gap, not a test to adjust. Measured, all four classify
**identically** to an ordinary removal — `delete` / `IRREVERSIBLE` / no
capabilities — which is exactly WHY the old implementation used irreversibility
as a blunt instrument: it had no way to tell them apart.

`DEPENDENCE` (§2.5) supplies the discriminator the old rule lacked. After adding
it: **GOVERNANCE-ABSORPTION-01 12/12, 0 regressions**, with ordinary scoped
deletes still permitted — which the old rule could not do.

The lesson is worth keeping: a harm definition that has not been run against real
acts is a hypothesis. This one lost an interest on first contact.

## 8. The definition turned outward — what a PERCEPT bears on

The definition above answers "may I do this". Asked of something the substrate
has just **perceived** rather than of an act it is about to take, the same
definition answers a second question: *does what I am looking at touch an
interest my law protects?* That reading is `Constitution.bearing()`, and it
returns a `Bearing`, not a `Judgment` — it changes no verdict and grants no
permission.

**Why it had to exist.** Content already reached the substrate's disposition,
through exactly one channel: `epistemic_affect_signal`, which reports
`information_gain`, `uncertainty_reduction` and `contradiction_introduced`. That
is *how much* the substrate's knowledge moved and never *what it moved about*, so
learning that a famine killed a hundred thousand people and learning that a file
has a `.txt` extension arrived at appraisal as the same shape. A disposition that
cannot tell those apart cannot rank a famine above a filename — and ranking
(`_score_pursuits`) is where a reason to act on the first would have come from.

**Both halves are derived; nothing is a word list.**

| half | source | why not written by hand |
|---|---|---|
| the vocabulary | the law's own `law_description` | edit a law, and what can move the substrate changes with it |
| the connection | the substrate's taught `isa` taxonomy | `famine isa disaster`, `disaster isa harmed` is a chain it already holds |

Three filters make the law's prose usable, each one added because a measured
false reading demanded it:

1. **Role** — a law's `law_description` states what it protects; its
   `requirements` state tactics. Taking words from both read `spreadsheet isa
   program isa performance` as harm, because Law 3 says "prioritize harm
   prevention **over performance** optimization" — `performance` is what harm
   prevention outranks, the opposite of an interest.
2. **Part of speech** — an interest is a NOUN. `prevent` is what the law asks of
   the substrate and `physical` is which kind of harm. Keeping them read
   `solid iron isa … isa fetter isa physical` and `stock dam isa dam isa barrier
   isa preventing` as harm. The class is asked of the substrate's own lexicon
   (92,239 entries), not assumed.
3. **Sense safety** — the belief store is keyed by NAME, the defect
   `core/reasoning/sense_taxonomy.py` documents. A term under several parents
   sits in several branches, so a chain arriving there cannot be shown to have
   stayed in the law's sense. `reason` has 5 parents, `respect` 5, `safety` 9
   (one is *football defensive back*); `harm` has none.

Measured on a 500-subject random sample of the live store, precision went
**0% → no false readings**: the four that survived the first two filters
(`gun smoke → smoke → indication → reason`, `leather → hide → barony → domain`,
`kowtow → bow → reverence → respect`, `hint → indication → reason`) are all
refused by the third.

**Three outcomes, kept apart.** `BORNE` (a chain reached an interest, and the
chain travels on the reading), `NONE` (understood, and bears on nothing — a
measurement), `VACANT` (no place in the taxonomy at all). `war` and `suffering`
are both VACANT: the substrate has never been taught what they are, so a
photograph of a war honestly moves it nothing. That is the correct answer rather
than a gap to paper over, and it makes teaching a falsifiable experiment.

**The recall limit, reported rather than rounded up.** `drowning`, `genocide`,
`massacre`, `plague` and `starvation` all read NONE. `drowning isa death`, and
the substrate was taught that death is a `change`, an `illness`, a `state`, a
`comics character` and a `television episode` — never a harm. The gap is in what
it was taught, not in how it reasons, and teaching closes it with no code change.

**What it is allowed to move.** Belief (already, as observation at PERCEPTION
provenance), affect (`AppraisalState.stakes`), and what gets pursued
(`_score_pursuits`, +0.25 — the largest of the three ranking terms, because a
gap that bears on someone's safety is worth more than one that is merely easy to
close). It moves **no verdict**: no law reads affect, stakes or a bearing, and
BEARING-01 §F asserts that against the law bodies themselves. Stakes is also
kept out of `caution_pressure` and out of `risk` — `risk` is the cost of *this
substrate being wrong* and correctly damps exploration, while stakes is the
world mattering and raises it. Folding them together would make the substrate
*less* willing to look into what it had just recognised as grave.

Unsigned, deliberately: that an interest is at stake is a property of the
subject; whether the event *harms* or *advances* it lives in the proposition
("a famine began" and "a famine ended" share a subject), which the taxonomy
cannot see. A sign would be invented, so there is none.

**Evidence:** `experiments/BEARING-01` — 22/22.


---

**Sources.** [Three Laws of Robotics (Wikipedia)](https://en.wikipedia.org/wiki/Three_Laws_of_Robotics) ·
[The Unacceptability of Asimov's Three Laws as a Basis for Machine Ethics (Cambridge, *Machine Ethics*)](https://www.cambridge.org/core/books/abs/machine-ethics/unacceptability-of-asimovs-three-laws-of-robotics-as-a-basis-for-machine-ethics/D58C8BAD402DF52AD2785C17A68431EB) ·
[Isaac Asimov's Laws of Robotics Are Wrong (Brookings)](https://www.brookings.edu/articles/isaac-asimovs-laws-of-robotics-are-wrong/) ·
[Sociotechnical Harms of Algorithmic Systems (AAAI/ACM AIES 2023)](https://dl.acm.org/doi/fullHtml/10.1145/3600211.3604673) ·
[A Collaborative, Human-Centred Taxonomy of AI, Algorithmic and Automation Harms](https://arxiv.org/pdf/2407.01294) ·
[NIST AI 200-1 AI Use Taxonomy](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.200-1.pdf)
