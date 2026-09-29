# EDU-15 — a programming lesson, graded by running the code

**What it tests.** A teacher model (Qwen) may explain and propose code, but may not vouch for it; running
the code decides. Four competences are measured separately:
- **pretest:** before any teaching;
- **assisted:** with the teacher reachable;
- **substrate:** with the teacher blocked, and any attempt to reach it counted;
- **transfer:** programs never shown.

The exam is sealed in `curriculum.py` before any lesson runs, and it is graded by behaviour on hidden
input/output pairs.

**Run:** `./venv_lyric/bin/python3 experiments/edu/EDU-15/session.py`

**Results.** No result is saved in this folder.

**Status.** It does not run: `session.py` uses the deleted `core.model_policy` and
`core.services.unified_llm`.
