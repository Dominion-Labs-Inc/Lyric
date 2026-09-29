# DOMAIN-DISCOVERY-01 — does the substrate create domains, or only file names?

**Claim.** The substrate DECIDES which domains exist, from what it has learned and
been taught, rather than filing whatever string a caller passed into `domain=`.

**Run.** `./venv_torin/bin/python3 experiments/DOMAIN-DISCOVERY-01/experiment.py`

**2026-09-27, run `20260927T061500Z` in the sandbox (`torinai_dev`): 8/11. The harness fails, not the code.** Three
checks read the store for what only exists after learning:
- a provisional domain comes from learned rules (`kite17` on 09-25);
- a stored decision (`warehouse`);
- concepts in the `general` channel (82,676 on 09-25).

An emptied store has none of these, so the checks fail whatever the code does. The last run on the store before
the wipe (`20260925T192419Z`) was 11/11. To be fixed: the experiment builds its own preconditions (teaches a
rule, makes a decision, fills a channel) instead of relying on what the store happens to hold.

## Why

Four days of work kept landing back on the same hand-written domains — `kite17`,
`warehouse`, `fs_g2_real1` — across two flushes of the store. The reason was not
that discovery was slow or unlucky. **Both halves of it were unreachable by
construction**, and every row in `unified.domains` is a name someone typed.

### The operational half was empty by construction

`provisional_domains()` returned *rule-domains minus registered domains* — i.e.
"not yet **registered**". But the learning fan-out calls `ensure_domain(domain)`
on the **first fact taught**, long before any operator is induced there. So the
candidate set was empty on every wake, forever.

Measured on the live store:

| | |
|---|---|
| `provisional_domains()` | `[]` |
| rule-holding domains registered *before* their first rule | 6 of 8 |
| times `crystallize()` had run on a real domain | 0 |

`crystallize()` is the function that decides new-vs-merge **and records
cross-domain analogies**. It had never executed in the substrate's life.

### The declarative half read an empty channel

`_idle_domain_discovery_work` asked for `discover_concept_domains(from_field="conversation")`.

| channel | concepts |
|---|---|
| `conversation` | **0** |
| `general` | **82,676** |

The splitter written for exactly that blob — `crystallize_taxonomic_domains`,
whose own docstring records the measurement — had **zero callers anywhere in the
tree**. The 226 domains created at 2026-09-21 16:19 were a hand run of it.

### And the splitter placed concepts by alphabet

The home-subject choice was `max(Counter(roots), key=lambda r: (tally[r], r))`,
described in a comment as "the subject the most of this concept's hypernym chains
arrive at". **The counts were all 1** — the walk shares one `seen` set, so each
root is recorded once however many chains reach it. That collapses the choice to
`max` over the *name*: the alphabetically last root won every time.

| placement rule | subjects | largest bucket |
|---|---|---|
| alphabetically last root | 5 | `x_linked_recessive` — **65,056 of 82,676** |
| …after deleting that one edge | 5 | `written` — **65,048** (`w` sorts next) |
| nearest subject (this fix) | **74** | `artificial` — 1,106 |

Two different mega-buckets from one arbitrary tie-break. Deleting edges was
whack-a-mole; distance is real evidence and was already in hand from the walk.

## Checks

| | check | what it defends |
|---|---|---|
| A | a registered-but-undecided domain is still a candidate | registration is not the decision |
| B | a domain never merges into itself | exposed the moment A made the path live |
| C | a decided domain is not decided again, durably | or every sweep re-decides forever |
| D | the declarative sweep names more than one channel | not one hardcoded name |
| E | the taxonomic splitter has a caller | it had none |
| F | a concept lands under its **nearest** subject | the mega-bucket defect |
| G | a root reached through ONE child is rejected as a funnel | one bad edge must not take the bucket |
| H | a root with several kinds under it is **still** a subject | the negative control for G |

**H is the control.** A guard that rejects funnels by rejecting everything would
"fix" the mega-bucket by making discovery produce nothing at all.

**B is worth its own line.** Making dead code live exposed a defect the dead code
had hidden: a candidate is registered, so it appeared in its own comparison set,
matched itself under the identity correspondence, and was recorded as "the same
subject re-learned" — merged into itself. Impossible while `provisional` meant
"unregistered", because then a candidate could not be in that list at all.

## What this does NOT claim

The **subject map's quality is capped by the taught taxonomy, not by this code.**
With placement corrected the split finds 74 subjects, but many are adjectives and
past participles taught as genera — `cooked`, `assessed`, `emitted`, `written`,
`artificial`, `added`. That is an upstream reading defect (a premodifier taken as
the hypernym, the same family as a postmodified subject read as the head).

The substrate's own word classes cannot separate them today — asked directly,
`cooked` returns NOUN 4 / ADJECTIVE 1 and `written` NOUN 6 / ADJECTIVE 1 — so a
noun-head filter would pass exactly the roots it should reject. Filtering in the
splitter would patch the symptom.

Therefore `UniversalDomainMaster.DECLARATIVE_APPLY` is **off**: the split is
surveyed and logged on every sweep but does not rewrite 10,277 concepts' `domain`
irreversibly on the strength of a known-defective taxonomy. The operational half
and the component splitter are unaffected and do apply.

## Result of the fix, on the live store

`discover_domains()` — the first real run in the substrate's life:

```
examined=4  crystallized=3  merged=0
  fs_g2_real1    crystallized   operators=1
  fs_removal_01  crystallized   operators=1
  kite17         incoherent     operators=2   (correctly left provisional)
  warehouse      crystallized   operators=1   analogies=['kite17']
```

`warehouse → kite17` was persisted as a verified analogical transfer bridge —
"a thing moves along a link", shared between warehouse logistics and movement.
**That bridge had never been produced before**, because the function that
produces it had never run.
