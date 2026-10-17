# ROLES-01: argument-structure constructions, learned over phrases, say each argument's part

**Claim.** Constructions learned over phrases say which part each phrase plays: who did it (`done_by`), what it was
done to (`done_to`), who got it (`received_by`), where it was (`located_in`), and so on, in Lyric's meaning language.

**Why.** The reader learned whole sentence frames over word strings, and prose failed where its phrases differ from
any frame taught (`docs/research/READING_PROSE_AT_SCALE.md`). The plan (handoff, "The plan now", step 1): learn how a
phrase's place in the structure says its part, from PropBank's roles on the treebank Lyric's structure was learned
from, each role said in the meaning language (`core/semantics/propbank_roles.py`, PROPBANK-01).

**How** (`core/semantics/argument_structure.py`): each argument stands to its predicate in situations, most specific
first: the predicate's word, the path between them in the structure, the word marking it, the predicate's voice and
class, the class of the argument's head, its first word. It is said as the arguments met in the most specific
situation like it were (memory-based, backing off on a tie, as `StructureView` decides).

**What it measures** (files only, no store): learned from the treebank's training part; on dev and test, the
arguments given, the share said in the fact PropBank's role maps to, over UD's structure, over Lyric's own
(`StructureView` from the same training part), and by the path alone. No bar: measured.

**Run** (from the Lyric folder; a few minutes):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/ROLES-01/experiment.py
```

with `test_data/syntax/` holding `propbank-release`, `propbank-frames` and `UD_English-EWT` (`--data DIR` reads them
from elsewhere).

**Results:** `results/<UTC timestamp>.json` and `.md`.

**Runs:**

| Run | Where | dev: UD's structure / Lyric's / path alone | test: the same |
|---|---|---|---|
| `20261017T140216Z` | a cloud session, code 2b30ade | 80.2% / 65.5% / 56.5% | 80.5% / 65.8% / 55.7% |
