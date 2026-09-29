# THREAT-SENSE-01 — does the substrate FEEL a threat, and does feeling it change what it does?

**What this replaced.** `core/security/threat_intelligence.py` asked AbuseIPDB, OTX and
VirusTotal whether an IP address was bad. That is threat intelligence as a DATABASE QUERY:
it reached outside (which the air-gapped world forbids), it was about addresses rather
than about this substrate, and nothing it returned changed any behaviour. It has been
deleted.

A person does not look up whether they are in danger. They notice, and they act
differently afterwards — they check more before committing. This proves the replacement
does that, in the substrate's own terms:

```
a security event -> PERCEIVED  (a memory, and a belief resting on it)
                 -> FELT       (appraisal `risk`)
                 -> ACTED ON   (caution -> verification intensity ->
                                the acceptance band a percept is judged by)
```

## The seven properties

| | |
|---|---|
| **A** | untested is not safe — nothing met reads `None`, never `0.0` |
| **B** | a refusal is MET — real judgements, through the real path |
| **C** | it is PERCEIVED — each one becomes a memory it can be asked about |
| **D** | it is FELT — appraisal `risk`, a channel no caller had ever fed |
| **E** | it CHANGES BEHAVIOUR — the acceptance band actually moves |
| **F** | tampering outweighs everything — the judging machinery changing is the worst case |
| **G** | it NEVER decides — feeling informs behaviour; a law is not moved by it |

**G is checked against the code, not a promise.** Every law method's body is parsed and
unparsed — dropping comments and docstrings — and scanned for any reading of affect,
stakes or a bearing. A first version scanned raw source and reported a COMMENT as a law
reading `stakes`: a false failure on the one invariant that must never be ignored.

**A is not pedantry.** `ThreatSense.level()` returns `None` when nothing has been met,
because a substrate that has met nothing is UNTESTED, not safe, and `0.0` would feed
appraisal a measured calm it never measured.

## What counts as a threat

Three producers, all of them the substrate meeting something real, weighted by what they
mean rather than by how loud they are:

| kind | weight | what it means |
|---|---|---|
| `integrity` | 1.00 | the machinery that judges was changed under it |
| `screen` | 0.55 | an argument shaped to escape where it was going |
| `refusal` | 0.25 | its own law stopped an act — the system WORKING |

Events decay on a 15-minute half-life and the level SATURATES rather than averaging: ten
screen faults are worse than one, and nothing is worse than certain. A substrate that
forgets instantly cannot notice a pattern; one that never forgets stays afraid of
something that stopped.

## Run

```
./venv_torin/bin/python3 experiments/THREAT-SENSE-01/experiment.py
```

Runs a LIVE substrate, halts it on purpose in section F and resumes it, and deletes the
`substrate_safety` beliefs it created. Each run writes a structured record to
`results/<timestamp>.json`.
