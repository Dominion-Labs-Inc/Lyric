# ORG-01 — a person's Shared World Context is composed; work belongs to the organization

**Finding (2026-10-07): 20/20,** on the second run. The first run found that a work context claimed by an
unverified session was accepted and the anonymous session authorized for the organization: the front door's
"identity" falls back to the session when none was verified, so the guard has to read the verified identity the
authenticating layer put in the request.

The rule (`docs/research/SEPARATION_MAP.md` §11.13, from the teammate 2026-10-07): Shared World Context is not a
store. It is the composition, at the moment Lyric works for a person, of World Knowledge (Lyric's own), their
Personal Context, and the Work Context of each organization they are authorized for, each kept where its owner keeps
it. Ownership follows identity, authorization and organizational context, never the device. Coworkers share their
organization's Work Context and never each other's Personal Context. A person who leaves takes the Work Context out
of their composition; it stays the organization's.

**What it checks.**

| | |
|---|---|
| **A** | a verified request through a person's work context authorizes the organization's Work Context; another instance of theirs (another session, no context) resolves to the same composition; an outsider composes none, Lyric's own work only its own |
| **B** | what they tell at work is held under the organization (`org:<organization>`), what they tell personally under them |
| **C** | they are answered from both; a coworker from the Work Context and never from their Personal Context; an outsider from neither |
| **D** | a memory made at work is the organization's, found by them and the coworker and not the outsider; a personal memory by them alone |
| **E** | unlinked through the front door (`unlink_work`): the Work Context leaves their composition, they are no longer answered from it nor find its memories, keep their Personal Context, and the organization keeps everything (the coworker is still answered) |
| **F** | a work context, or an unlink, without a verified identity is refused |

**The trap in measuring it.** "Answered" is read from the reasoner (`answer_over_graph` for the person) and "found"
from memory's own search, so the composition is measured where every answer and recall reads it, apart from the
reader. The front door's requests are jobs on the queue too, so the run removes them with everything else it wrote.

## Run

```
./venv_lyric/bin/python3 experiments/ORG-01/experiment.py
```

On the sandbox. Each run writes `results/<UTC timestamp>.json` with a `.md` beside it.
