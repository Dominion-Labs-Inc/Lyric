# ACTOR-IDENTITY-01 — conversations are scoped to the verified identity

**What it tests.** A fact a person tells the substrate is kept under their World Auth identity, not
under the session string.
- `Conversation._actor` returns the bound identity (through `actor_for`). It falls back to the
  session only when no identity is bound.
- Binding the substrate's own actor ID raises, so a user cannot pose as the substrate.
- End to end: teaching through a bound conversation puts the fact in that identity's scoped context,
  not under the session.

Uses the real learning authority and the real scoped store.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/ACTOR-IDENTITY-01/experiment.py
```

**Results.** Printed to the terminal only; no run is saved.

Related: FRONTDOOR-IDENTITY-01 (where the binding happens) and SELF-PARTITION-01.
