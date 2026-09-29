# SYSTEM-CONVERSATION-01 — what a speaker tells is theirs

**Finding (2026-09-26): behaviour 37/37; one wiring finding (`beliefs_about_user`, called by nothing).**
A conversation session is a user actor, so what it is told lands in that speaker's scoped context, never the
shared mind. Two speakers, fresh nonce words each run, everything said through `understand`.

**What was wrong, all measured here first:**
- **The scoped path skipped the door.** A user's telling bypassed the ingress's shape test: a subject that
  names nothing, a clause for a relation, a quality under the floor were all held with `admitted=True`; and
  terms were stored raw (`isoprobe wren isa an isoprobe bird`), so the graph overlay — which walks canonical
  concept names — could never reach a two-word name, and a one-word name's chain stopped at `a mammal`. The
  door's test is now one function (`shape_proposition`) on every path, and scoped edges are canonical.
- **A told conditional asserted both sides.** "if the valve is closed then the tank overflows" put
  `valve isa closed` in the speaker's context as a held fact. Neither side is asserted now, as at the shared
  door; the implication is the speaker's one belief about it.
- **A refused promotion read "promoted".** A claim two speakers corroborate is lifted into the shared mind —
  but the flag was set whatever the shared door said, so a refused claim (e.g. a kind cycle) could never lift.
- **A question could not see the speaker's own context.** `resolve` read only the shared store, so a told
  two-word name was split on a shared word (`heron`) and a told name was answered "Yes" and then called
  "nothing held". It now reads the speaker's scoped layer, and premises from it are labelled `context`.
- **What was reasoned for a speaker became everyone's.** The reasoning record, the learning summary of it,
  and a speaker's unread sentence were stored with no owner, so another speaker's recall could return them.
  See SYSTEM-MEMORY-01 for the owner rule every memory search now applies.

The suspected "one telling promoted to the shared mind" was NOT a leak: the knowledge ledger showed each
promotion happened on a SECOND session's telling, as the rule allows.

**What it checks.**

| | |
|---|---|
| **A** | one held conversation per session; a session is a user actor |
| **B** | told → scoped edges in canonical terms; nothing in the shared graph or beliefs |
| **C** | asked back by the speaker: one-word, two-hop (onto the shared graph) and two-word questions affirmed, and the reply does not call what it answered unknown; the two-word name resolves whole |
| **D** | another speaker is not answered from it and resolves nothing of it |
| **E** | a told conditional is held; neither clause is an edge; the antecedent is not affirmed |
| **F** | the door refuses for a speaker what it refuses for the substrate |
| **G** | a claim two speakers corroborate but the shared door refuses is not flagged promoted |
| **H** | nothing held, nothing invented |
| **I** | it can say what it just heard |
| **J** | what was reasoned for the speaker is theirs: owned, recalled by them, not by the other speaker or the substrate |

**The trap in measuring it.** Earlier probes reused fixed words (`zorblatqx`, `isoprobe wren`) and left their
scoped rows behind, so a later telling was "corroborated" by an earlier run and promoted — making the run
order-dependent. Every run now uses fresh nonce words and removes, by id, every row its two speakers wrote, including their turns and reasonings in the memory agent's pool (added 2026-09-28: since the pool existed, those items had been left behind unseen).

## Run

```
./venv_lyric/bin/python3 experiments/SYSTEM-CONVERSATION-01/experiment.py
```

Residue is snapshotted to `data/snapshots/system_conversation_01_<nonce>_<ts>.json` before removal. Each run
writes `results/<UTC timestamp>.json` with a `.md` beside it, reporting **behaviour** (pass/fail), **wiring**
and **completeness** findings apart (`experiments/_isolation.py`).
