# FRONTDOOR-IDENTITY-01 — the front door binds the verified identity

**What it tests.** `handle_user_request` is the one door a user request comes in by. The adapter puts
the verified World Auth identity in `metadata["actor_identity"]`. This checks that the door passes that
identity into the conversation it opens, so what the person teaches is scoped to them. With no verified
identity, the door falls back to the session.

ACTOR-IDENTITY-01 tests what happens after the binding.

**Run** (from the TorinAI folder):

```
./venv_torin/bin/python3 experiments/FRONTDOOR-IDENTITY-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.
