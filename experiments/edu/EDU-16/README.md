# EDU-16 — teaching English from the bottom up

**What it tests.** The substrate starts with three closed word sets and no notion of word classes. A
teacher model proposes the classes in order: noun, adjective, verb, then subject + verb, then subject +
verb + object. A class counts only if sentences that depend on it read, and a wrong sentence fails to
read (see `world.py`). As in EDU-15, pretest, assisted, substrate (teacher blocked) and transfer are
measured separately. `scaled_session.py` is a sustained 30-minute reading run.

**Run:** `./venv_torin/bin/python3 experiments/edu/EDU-16/session.py` or `scaled_session.py`

**Results.**
- `result.json` (2026-08-21):
  - words: 0/18 before teaching, 18/18 with the teacher blocked;
  - sentences: 6/12 before, 12/12 after; transfer 6/6;
  - 0 model calls during the exam;
  - 27 of 28 proposals confirmed, 1 contradicted, and no false confidence.
- `scaled_result.json` (2026-08-21):
  - 30 minutes; 11,530 of 12,082 offered sentences were read;
  - vocabulary of 1,326 words: 777 nouns, 232 adjectives, 317 verbs;
  - 1,011 teacher calls.

**Status.** It does not run: it uses the deleted `core.model_policy` and `core.services.unified_llm`.
