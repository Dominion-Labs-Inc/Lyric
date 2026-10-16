# PATHS-01 — one learning path, one conversation path, every write through its authority

**What it checks.** Partly static, deliberately: whether a second path exists can only be seen by reading all
of `core/`.

| | |
|---|---|
| **A** | one learning path: the concept graph's edges, the beliefs and the learned rules each have one writer, the concept table only ingestion and the domain authority, and the ingress is reached only through the learning authority; one call on the learning authority admits a fact to the graph, remembers it, moves a belief and reaches its domain |
| **B** | one conversation path: one Conversation class; an unbound conversation is a user scope, never the substrate; a speaker may not claim the substrate's identity; what a conversation is told of a name the world does not hold reaches the speaker's context and not the world |
| **C** | every path hits the authorities: relation typing decided in one place, the same sentence rendered to the same atom through either door, the kind hierarchy invariant held at admission |

**Changed 2026-10-07 (the gate, `docs/research/SEPARATION_MAP.md` §11).** The rule it quotes, "nothing in
conversation should be admitted as facts", is replaced by the user's of 2026-10-06: what is told is judged by
whether it is true, after memory splits off what is about the person. B now tells a name ("Plaxtold… is a
gadget.") rather than a kind, and A calls the gate (`consider`). PATHS-02 checks the split and that Lyric hands
everything to memory.

## Run

```
./venv_lyric/bin/python3 experiments/PATHS-01/experiment.py
```
