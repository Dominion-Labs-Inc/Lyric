# TOOLDOMAIN-01 — the substrate learns what an act does, from doing it

**What it tests.** That a domain the substrate can act in and learn from needs nothing written by hand:
- an act's own arguments name its domain (acts on paths belong to `tools:path`) and make its operator a
  bound one, with no workspace declared;
- meeting an act does not license practising it: acting when asked and practising unasked differ;
- in a sandbox it is given to practise in (`derive_domain`), it practises and induces an executable
  `MOVE_FILE` from what happened;
- ordinary work then files before/after demonstrations, the world read through the self's own
  perception of each path;
- it learns which observations an operator moves, and recovers that from the store after its caches are
  dropped.

**Run** (sandbox store, boots the full system):

```
POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/TOOLDOMAIN-01/experiment.py
```

**Results.**
- No run was recorded before 2026-09-28.
- 2026-09-28: **20/20**, the first full pass. Two changes made the practice sections work:
  - a declared sandbox is now perceived: the self looks at what is in it;
  - practice tries each thing on a free place and back again, plus a move of something that is not
    there.
