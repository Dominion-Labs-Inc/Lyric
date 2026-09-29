# SYSTEM-PERCEPTION-01 — the perception faculty and sight, alone

**Finding (2026-09-26): behaviour 18/18; two wiring findings.** One sensing authority
(`PerceptionFaculty`). A real image becomes structure, a file with no reader is refused rather than guessed,
two sightings correspond, an instance is learned and forgotten. Section F sees a REAL photograph through
`coord.see`: one COCO camera image (640x433, one pixel changed per run so each run sees a picture no earlier
run saw) formed a memory that can produce the picture again, was admitted once as evidence, entered the
concept graph (147 edges), and is held as beliefs every one of which is about that memory — then everything
it wrote was removed by id, to zero. Wiring: `known_instances`, `forget_instance` are exercised only by
experiments.

**What it checks.**

| | |
|---|---|
| **A** | one authority, one construction site |
| **B** | a real image becomes structure; one picture seen twice is one individual |
| **C** | a file it cannot read is refused, not guessed |
| **D** | two sightings correspond |
| **E** | an instance is learned and forgotten |
| **F** | sight end to end on a real photograph: memory, retained picture, one envelope, graph edges, grounded beliefs, removal |

**The trap in measuring it.** `known_instances` is a property, not a method. A percept is named from the image's content digest, so the
same file seen by two runs is the same individual — which is why section F changes one pixel per run: a
residue from one run would otherwise make the next "already present".

## Run

```
./venv_lyric/bin/python3 experiments/SYSTEM-PERCEPTION-01/experiment.py
```

Section F removes its perception row, memory, retained picture, envelope, every graph row citing it, the concepts only it made, its beliefs, and the experience the seeing handed to the memory agent's pool (added 2026-09-28: since the pool existed, the seeing's pool item had been left behind unseen). Each run writes `results/<UTC timestamp>.json` with a `.md` beside it. The run reports three things apart (`experiments/_isolation.py`): **behaviour** checks, which alone decide pass/fail; **wiring** findings (a public method nothing in `core/` calls — split into ones only experiments/tests exercise and ones nothing calls); and **completeness** findings (a body that raises `NotImplementedError`, returns a literal, or is empty).
