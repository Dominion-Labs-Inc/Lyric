# EDU-14 — taught to read by a language model

**What it tests.** Whether a language model can hand over what sentences mean once, and then be removed.
1. **Teach:** the model proposes what five sentences assert. Its calls are counted.
2. **Derive:** the reading is derived from those proposals with the model blocked.
3. **Read:** unseen sentences are graded against a key the model never supplied.
4. **Refuse:** a wrong teacher must not produce a confident substrate.

**Run:** `./venv_torin/bin/python3 experiments/edu/EDU-14/taught_to_read.py`

**Results.** `taught_to_read.json` (recorded 2026-08-20): passed. 5 sentences were taught, and 7
sentences never taught were read.

**Status.** It does not run: it uses `core.model_policy` and `core.services.unified_llm`, both deleted
when the LLM teacher was retired (2026-09-13).
