# SPLIT-01 — what Lyric meets is split by what it is about

**Finding (2026-10-07): 17/17.** Every case landed where the table below said it would, the table written
before the first run. A kind, a particular the world holds, a page found, Lyric's own observation and what it saw
itself go to the world, through the one door. A name the world does not hold, the speaker, a particular of
theirs, what was in their picture and their device go to their context: personal, or work and the
organization's. A telling holding both is split. What is too weakly said is held nowhere, and why is said.

The rule is `docs/research/SEPARATION_MAP.md` §11.3: a fact whose terms are all kinds or particulars the world
holds is about the world; a fact with any particular of a person or an organization is about them.

**What was built to pass it.** A person's context did not record which of their contexts a thing came through.
`Origin` carried personal or work, and memories kept it, but the facts and beliefs held for the person dropped
it. The context tables and the table of what people say of themselves now keep `context` and `organization`, and
since 2026-10-07 (§11.13) work is held under the organization itself (`org:<organization>`), not the person:
the first run of this check, which expected work under the person, was written to the wrong rule.

**The cases, frozen before the run.**

| Case | Given | Lands |
|---|---|---|
| a kind, told | "A wug is a bird." | world |
| a particular the world holds | "Lumeria is a port." (the world holds Lumeria) | world |
| a name the world does not hold | "Ava is a dancer." | personal |
| the speaker, of themselves | "I am a teacher." | speaker (kept under them) |
| a name, told at work | "Northwind VPN is a network." | work: the organization's Work Context, not the person's |
| their particular thing | "My printer is broken." | personal |
| both in one telling | "A quill is a bird and Ava is happy." | world + personal |
| a rule of kinds | "If a wug is hungry, a wug is loud." | world rule |
| a rule of their particular | "If my printer is hot, my printer is loud." | personal rule |
| too weakly said | at quality 0.2 | nothing |
| a page found by research | zorbite is a mineral, on example.org | world |
| a thing in their picture, named | their photo's blob named a printer | personal |
| a thing Lyric saw itself, named | Lyric's blob named a printer | world |
| Lyric's own observation | its host is a machine | world |
| their device, as it reports itself | phone, an iPhone, allows camera | personal |
| a sentence that did not read | "Glorp frabbed the snoo." | nothing (remembered as theirs) |

"World" means an edge in the world's concept graph and none in their context. "Personal" and "work" mean an edge
in their context with that context, none in the world, and the world does not even name the thing.

**The trap in measuring it.** The cases go through memory's real intake (`take_in_telling`, `take_in_research`,
`take_in_recognised`, `take_in_observed`, `take_in_percept`, `take_in_unread`) with the meaning already read, so
the split is measured apart from the reader. That the reader reads such sentences is measured by CANARY-01 and
SYSTEM-CONVERSATION-01 through the front door. Every word the run makes up carries its nonce, and everything it
wrote is snapshotted (`data/snapshots/split01_*`) and removed.

## Run

```
./venv_lyric/bin/python3 experiments/SPLIT-01/experiment.py
```

On the sandbox. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it.
