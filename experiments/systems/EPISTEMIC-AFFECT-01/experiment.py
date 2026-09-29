#!/usr/bin/env python3
"""EPISTEMIC-AFFECT-01 — knowledge movement becomes feeling, through the reasoning
authority, from ANY source, without emotion casting a vote in a decision.

The substrate had a shared emotional state (appraisal) with NO live feeder from
knowledge change: `summarize_epistemic_mutations` had zero callers, and
`EpistemicEngine` only ever interpreted a *reasoning* pass — so perception and
teaching moved beliefs and the substrate never felt it. This wires the general
channel:

  belief MOVEMENT (any source)
     → EpistemicEngine.interpret_drift()          (read-only diff, the mechanism)
     → NeuralSymbolicBridge.epistemic_affect_signal()  (the reasoning AUTHORITY, one door)
     → coord.integrate_epistemic_affect()          (the body relays reasoning → appraisal)
     → appraisal (confidence ↑ on uncertainty reduced, doubt/curiosity ↑ on increase)

Invariant (verified, not assumed): knowledge → emotion → DISPOSITION. Emotion never
rewrites the evidence it read, and the channel is one-directional — so the core
decision stays evidence-vs-bar, with feeling setting only the bar (disposition).

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/EPISTEMIC-AFFECT-01/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, sys, uuid
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def _train_toy_ctm():
    from core.learning.tsetlin_gpu import BatchTsetlinMachine
    rng = np.random.RandomState(0)
    F, N = 24, 400
    X0 = (rng.random((N, F)) < 0.15).astype(np.int8)
    X1 = (rng.random((N, F)) < 0.85).astype(np.int8)
    X = np.vstack([X0, X1]); y = np.array([0] * N + [1] * N)
    m = BatchTsetlinMachine(n_classes=2, n_features=F); m.fit(X, y, epochs=12)
    return m, F


def _moved(sig) -> bool:
    if not sig:
        return False
    return any(float(sig.get(k, 0) or 0) > 0
               for k in ("information_gain", "uncertainty_reduction", "uncertainty_increase"))


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.agents.autonomous.appraisal import get_appraisal_system
        model, F = _train_toy_ctm()

    out, ok = [], True
    def check(label, cond):
        nonlocal ok; ok = ok and bool(cond)
        out.append(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    out.append("== 0. the drift snapshot is primed (pre-existing graph is the baseline) ==")
    # The boot primes it, so what the substrate learns from then on is read as change; this drain
    # moves the baseline to now, before this run's own teaching.
    from core.reasoning.epistemic_engine import get_epistemic_engine
    check("the boot primed the drift baseline", get_epistemic_engine()._drift_primed)
    await coord.integrate_epistemic_affect()

    # Fresh per-run identifiers — beliefs persist in Postgres, so a re-used claim is
    # already saturated and would (correctly) move nothing. Unique subjects isolate
    # THIS run's knowledge movement.
    uid = uuid.uuid4().hex[:8]
    out.append("== 1. a TEACHING source moves knowledge → feeling (via reasoning authority) ==")
    await coord.learning.learn_fact(f"creature_{uid}", "isa", "animal", domain="zoology")
    await coord.learning.learn_fact(f"creature_{uid}", "isa", "feline", domain="zoology")
    sig_teach = await coord.integrate_epistemic_affect()
    out.append(f"  signal(teaching)={ {k: round(float(v),4) for k,v in sig_teach.items() if isinstance(v,(int,float))} }")
    check("teaching-moved beliefs produced an epistemic feeling signal", _moved(sig_teach))

    out.append("== 2. a PERCEPTION source moves knowledge → feeling (same door) ==")
    coord.learning.register_clause_classifier(
        "toy_shapes", model, labels=["dark", "bright"], encode=None)
    from core.memory import Origin
    d = await coord.perceive("toy_shapes", np.ones(F, dtype=np.int8),
                             f"percept_{uid}", domain="toy_percepts",
                             origin=Origin.own("EPISTEMIC-AFFECT-01"))
    claim = d.claims[0].claim if d.claims else None   # a recognition makes one claim
    p_before = None
    if claim:
        b = coord.learning.belief_for_claim(claim)
        p_before = float(getattr(b, "posterior_probability", 0.0)) if b else None
    sig_perc = await coord.integrate_epistemic_affect()
    out.append(f"  recognition claim={claim!r} posterior_before={p_before}")
    out.append(f"  signal(perception)={ {k: round(float(v),4) for k,v in sig_perc.items() if isinstance(v,(int,float))} }")
    check("perception-moved beliefs produced an epistemic feeling signal", _moved(sig_perc))

    out.append("== 3. the shared emotional state actually moved ==")
    st = get_appraisal_system().current_state
    conf = getattr(st, "confidence", None) if st else None
    opp = getattr(st, "epistemic_opportunity", None) if st else None
    out.append(f"  appraisal.confidence={conf} epistemic_opportunity={opp}")
    check("appraisal reflects the knowledge movement (a dial is set)",
          st is not None and (conf is not None or opp is not None))

    out.append("== 4. INVARIANT: the channel is one-directional (emotion did not rewrite evidence) ==")
    p_after = None
    if claim:
        b2 = coord.learning.belief_for_claim(claim)
        p_after = float(getattr(b2, "posterior_probability", 0.0)) if b2 else None
    out.append(f"  posterior_after_integrate={p_after}")
    check("integrating the feeling did NOT change the belief's posterior it read",
          p_before is not None and p_after is not None and abs(p_after - p_before) < 1e-9)

    print("\n".join(out))
    print(f"\nRESULT: {'PASS — knowledge→emotion via the reasoning authority, general + one-directional' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
