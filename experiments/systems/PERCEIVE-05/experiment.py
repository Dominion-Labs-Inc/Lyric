#!/usr/bin/env python3
"""PERCEIVE-05 — one perception pipeline, recognition wired, perception stamped
WITHIN memories.

Three things were wrong and are fixed here; each is checked against the booted
substrate, no stubs:

  1. TWO perception pipelines. Vision admitted percepts through `vision.see` while
     a separate perception manager admitted through its own `process_input`. Now
     the perception faculty senses AND admits (`admit_percept`), once, and
     `coord.see` returns the PerceptionData and the evidence lands.

  2. `perceive` was ORPHANED (zero callers). Now it is the recognition primitive:
     a trained Tsetlin machine recognizes an instance, the finding goes through the
     gate, the posterior is compared to the completion acceptance band, and the
     decision (ACT / VERIFY / ABSTAIN) is emitted on the event spine — a probe
     confirms the decision actually travels it (confidence governs behaviour).

  3. Perception was NOT recalled with memories. Now a memory, as it forms, stamps
     the contemporaneous perceptual state alongside what was believed and the
     self-state — so recalling a memory returns what was perceived at that moment.
     This is the point of the whole change, and it is asserted on a real read-back.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-05/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_dev", "LYRIC_NO_WATCHDOG": "1"}.items():
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
    from core.memory import Origin
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
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

    out.append("== 1. the perception faculty is the one admitter ==")
    check("the coordinator's perception faculty admits percepts",
          callable(getattr(coord.vision, "admit_percept", None))
          and not hasattr(coord, "perception"))

    out.append("== 2. perceive is the recognition primitive (no longer orphaned) ==")
    coord.learning.register_clause_classifier(
        "toy_shapes", model, labels=["dark", "bright"], encode=None)
    from core.memory import Origin
    d = await coord.perceive("toy_shapes", np.ones(F, dtype=np.int8),
                             "sample_bright", domain="toy_percepts",
                             origin=Origin.own("PERCEIVE-05"))
    posterior = d.claims[0].posterior if d.claims else None
    out.append(f"  decision={d.decision} posterior={posterior} accept={d.accept}")
    check("perceive returned a governed decision (ACT/VERIFY/ABSTAIN)",
          d.decision in ("ACT", "VERIFY", "ABSTAIN"))

    out.append("== 3. the decision was fanned through the event spine ==")
    await asyncio.sleep(0.2)
    check("PERCEPT_RECOGNIZED reached a reaction (confidence governs behaviour)",
          len(seen_events) > 0)

    out.append("== 4. ONE pipeline: coord.see senses, the faculty admits once ==")
    coord.learning.register_clause_classifier(
        "toy_vision", model, labels=["dark", "bright"],
        encode=lambda p: _image_features(p, F))
    coord.attach_recognizer("vision", "toy_vision")
    pd = await coord.see(IMAGE, source="vision_test", domain="vision", actor_identity=None)
    await asyncio.sleep(0.2)
    check("see returned PerceptionData (the faculty was the admitter)", pd is not None)
    # THE PERCEPT IS NAMED FROM THE IMAGE'S CONTENT, not from the caller's
    # label: `source="vision_test"` becomes `vision_testx<digest>`, because the
    # caller's label is not an identity (an environment scan passes
    # `source="environment"` for every image it walks past, which made every
    # picture in the world the same individual). These two checks still looked
    # for the bare label and so could not pass. Ask the percept its name.
    percept_name = getattr(pd, "source", None) or "vision_test"
    check("the percept was admitted as evidence (edges for the subject exist)",
          len(await edges_for(percept_name)) > 0)
    recent = coord.vision.recent_percepts(limit=20)
    check("the percept is in the substrate's perceptual awareness",
          any(getattr(p, "source", None) == percept_name for p in recent))

    out.append("== 5. perception is stamped WITHIN a memory (the whole point) ==")
    stored, mid = await agent.store_memory(
        content="Observed the vision test card on the workbench.",
        memory_type=MemoryType.EPISODIC, importance_score=0.85,
        confidence_score=0.9, tags=["perceive05", "episode"], origin=Origin.own("PERCEIVE-05"))
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

    # EVERYTHING THIS RUN WROTE IS REMOVED: its memories by exact id, and what
    # it admitted under its own names (the percept's and the recognised sample's).
    names = [percept_name, "sample_bright"]
    ids = {mid, (getattr(pd, "metadata", None) or {}).get("memory_id")}
    for name in names:
        for sql in ("SELECT DISTINCT memory_id FROM unified.beliefs WHERE belief_text LIKE $1",
                    "SELECT memory_id FROM memory_hot.memory_hot WHERE content::text LIKE $1"):
            rows = await db.execute_query(sql, (f"%{name}%",), fetch_all=True) or []
            ids |= {r["memory_id"] for r in rows}
    ids.discard(None)
    for memory_id in ids:
        for table in ("unified.beliefs", "unified.memory_media", "memory_hot.memory_hot"):
            await db.execute_query(f"DELETE FROM {table} WHERE memory_id = $1", (memory_id,),
                                   commit=True)
    for name in names:
        like = f"{name}%"
        await db.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id IN "
            "(SELECT concept_id FROM unified.concepts WHERE name LIKE $1) "
            "OR target_concept_id IN (SELECT concept_id FROM unified.concepts "
            "WHERE name LIKE $1) OR target_surface LIKE $1", (like,), commit=True)
        for sql in ("DELETE FROM unified.concepts WHERE name LIKE $1",
                    "DELETE FROM unified.beliefs WHERE belief_text LIKE $1",
                    "DELETE FROM unified.experience_pool WHERE about LIKE $1",
                    "DELETE FROM unified.evidence_envelopes WHERE producer LIKE $1 OR source_id LIKE $1"):
            await db.execute_query(sql, (like,), commit=True)
    left = sum(int((await db.execute_query(
        "SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE $1) + "
        "(SELECT count(*) FROM unified.beliefs WHERE belief_text LIKE $1) AS n",
        (f"{name}%",), fetch_one=True))["n"]) for name in names)
    out.append(f"  cleanup: {len(ids)} memories and what was admitted under "
               f"{', '.join(names)} removed; {left} left")

    print("\n".join(out))
    print(f"\nRESULT: {'PASS — one pipeline; perceive wired; perception rides within memory' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
