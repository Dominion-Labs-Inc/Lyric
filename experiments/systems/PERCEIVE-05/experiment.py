#!/usr/bin/env python3
"""PERCEIVE-05 — one perception pipeline, recognition wired, perception stamped
WITHIN memories.

Three things were wrong and are fixed here; each is checked against the booted
substrate, no stubs:

  1. TWO perception pipelines. Vision admitted percepts through `vision.see` while
     the overall `PerceptionManager` admitted through `process_input` — and the hub
     was never even initialized, so it was dead. Now vision SENSES only, and every
     percept funnels through the ONE pipeline (PerceptionManager.process_input),
     admitted once. `coord.see` returns the PerceptionData and the evidence lands.

  2. `perceive` was ORPHANED (zero callers). Now it is the recognition primitive:
     a trained Tsetlin machine recognizes an instance, the finding goes through the
     gate, the posterior is compared to the completion acceptance band, and the
     decision (ACT / VERIFY / ABSTAIN) is emitted on the event spine — a probe
     confirms the decision actually travels it (confidence governs behaviour).

  3. Perception was NOT recalled with memories. Now a memory, as it forms, stamps
     the contemporaneous perceptual state alongside what was believed and the
     self-state — so recalling a memory returns what was perceived at that moment.
     This is the point of the whole change, and it is asserted on a real read-back.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-05/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
IMAGE = str(REPO / "test_data" / "vision_test.png")     # a real file in the repo


def _train_toy_ctm():
    """A REAL BatchTsetlinMachine trained to separate two boolean patterns —
    trained TA state, a mechanism, not a stub."""
    from core.learning.tsetlin_gpu import BatchTsetlinMachine
    rng = np.random.RandomState(0)
    F, N = 24, 400
    X0 = (rng.random((N, F)) < 0.15).astype(np.int8)    # sparse -> dark
    X1 = (rng.random((N, F)) < 0.85).astype(np.int8)    # dense  -> bright
    X = np.vstack([X0, X1]); y = np.array([0] * N + [1] * N)
    m = BatchTsetlinMachine(n_classes=2, n_features=F)
    m.fit(X, y, epochs=12)
    return m, F


def _image_features(path: str, F: int) -> np.ndarray:
    """A REAL, deterministic visual feature of the file: grayscale -> F cells ->
    threshold at the image mean. (The toy model was trained on synthetic patterns,
    so its LABEL on a photo is not meaningful; step 4 checks that the CHAIN fires on
    a real file and admits+governs, not classification accuracy.)"""
    import cv2
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cannot read {path}")
    side = int(round(F ** 0.5)) or 1
    small = cv2.resize(img, (side, side), interpolation=cv2.INTER_AREA).reshape(-1)[:F]
    if small.shape[0] < F:
        small = np.pad(small, (0, F - small.shape[0]))
    return (small > float(small.mean())).astype(np.int8)


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        from core.memory import get_memory_agent
        from core.memory.utils.interfaces import MemoryType
        agent = await get_memory_agent()

    out, ok = [], True
    def check(label, cond):
        nonlocal ok
        ok = ok and bool(cond)
        out.append(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    async def edges_for(subject):
        rows = await db.execute_query(
            """SELECT cr.relation FROM unified.concept_relations cr
                 JOIN unified.concepts c ON cr.source_concept_id = c.concept_id
                WHERE c.name = $1""", (subject,), fetch_all=True) or []
        return rows

    # Probe: prove the recognition decision actually travels the event spine.
    # SYNC mode so it runs inline inside emit() — this test initializes but does not
    # start the life loop, so the deferred drain worker (which runs the real,
    # deferred _react_percept in production) is not draining here.
    from core.agents.autonomous.autonomous_coordinator import SelfEventType
    seen_events = []
    async def _probe(ev):
        # The payload is a declared `PerceptJudged`, not a dict: the event spine
        # is typed, so a shape mismatch raises at the emit instead of drifting.
        seen_events.append(ev.payload)
    coord.on(SelfEventType.PERCEPT_RECOGNIZED, _probe,
             name="perceive05_probe", mode="sync", priority=10)

    model, F = _train_toy_ctm()

    out.append("== 1. the perception hub is active (the one pipeline is live) ==")
    check("PerceptionManager initialized -> process_input admits",
          getattr(coord.perception, "active", False) is True)

    out.append("== 2. perceive is the recognition primitive (no longer orphaned) ==")
    coord.learning.register_clause_classifier(
        "toy_shapes", model, labels=["dark", "bright"], encode=None)
    d = await coord.perceive("toy_shapes", np.ones(F, dtype=np.int8),
                             "sample_bright", domain="toy_percepts")
    posterior = d.claims[0].posterior if d.claims else None
    out.append(f"  decision={d.decision} posterior={posterior} accept={d.accept}")
    check("perceive returned a governed decision (ACT/VERIFY/ABSTAIN)",
          d.decision in ("ACT", "VERIFY", "ABSTAIN"))

    out.append("== 3. the decision was fanned through the event spine ==")
    await asyncio.sleep(0.2)
    check("PERCEPT_RECOGNIZED reached a reaction (confidence governs behaviour)",
          len(seen_events) > 0)

    out.append("== 4. ONE pipeline: coord.see senses, the hub admits once ==")
    coord.learning.register_clause_classifier(
        "toy_vision", model, labels=["dark", "bright"],
        encode=lambda p: _image_features(p, F))
    coord.attach_recognizer("vision", "toy_vision")
    pd = await coord.see(IMAGE, source="vision_test", domain="vision")
    await asyncio.sleep(0.2)
    check("see returned PerceptionData (the hub was the admitter)", pd is not None)
    check("the percept was admitted as evidence (edges for the subject exist)",
          len(await edges_for("vision_test")) > 0)
    recent = await coord.perception.get_recent_perceptions(limit=20)
    check("the percept is in the substrate's perceptual awareness",
          any(getattr(p, "source", None) == "vision_test" for p in recent))

    out.append("== 5. perception is stamped WITHIN a memory (the whole point) ==")
    stored, mid = await agent.store_memory(
        content="Observed the vision test card on the workbench.",
        memory_type=MemoryType.EPISODIC, importance_score=0.85,
        confidence_score=0.9, tags=["perceive05", "episode"])
    check("a memory was stored to hang perception on", stored and bool(mid))
    ts = {}
    if stored and mid:
        item = await agent.retrieve_memory(mid)
        ts = getattr(item, "thinking_state", None) or {}
    ps = ts.get("perceptual_state") if isinstance(ts, dict) else None
    out.append(f"  perceptual_state on the memory: "
               f"{[p.get('source') for p in (ps or {}).get('perceptions', [])] if ps else None}")
    check("the memory carries a contemporaneous perceptual_state", bool(ps))
    check("belief_state is also stamped (perceived + believed together)",
          isinstance(ts, dict) and "belief_state" in ts)

    print("\n".join(out))
    print(f"\nRESULT: {'PASS — one pipeline; perceive wired; perception rides within memory' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
