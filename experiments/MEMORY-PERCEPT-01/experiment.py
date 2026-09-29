#!/usr/bin/env python3
"""MEMORY-PERCEPT-01 — a memory of something seen resolves to the seeing.

"I saw that employee send that email" was testimony: the substrate's word, plus
a `perceptual_state` snapshot attached by RECENCY — a 120-second window over
whatever had been perceived lately. That says something was in view around then.
It is a correlation, and it degrades exactly where it matters most, when several
things were seen close together.

A reference is defensible where a recollection is not. The percept holds what was
actually sensed — for an image the blobs and their `isa` features, the
dimensions, and the sha256 of the exact bytes — so the claim resolves to a record
of the seeing rather than to a memory of it.

  A  SCOPE        a percept is bound only for the work done under it, and
                 binding is owned by the caller that owns the scope.
  B  LINKED       a memory formed while seeing records WHICH percept, by id.
  C  NOT BORROWED a memory formed outside a seeing links to nothing.
  D  RESOLVES     the id resolves to the percept, and the digest matches the
                 bytes that were actually sensed.
  E  READS BACK   it survives RETRIEVAL, not just the write.
  F  RENDERED     and reaches the reader.
  G  MODALITY     the link is `percept_id`, not `image_id` — hearing arrives
                 through the same door and binds the same way.

Run: ./venv_torin/bin/python3 experiments/MEMORY-PERCEPT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "MEMORY-PERCEPT-01",
    claim=("A memory of something perceived carries a reference to the percept "
           "that recorded the perceiving, so recall of what was seen resolves to "
           "a record with the digest of the exact bytes rather than resting on "
           "the substrate's word."),
    hypothesis=("If the link were by recency, a memory would claim to be of "
                "whatever happened to be in view nearby — weakest precisely when "
                "several things were seen close together. If it were written but "
                "not read back, it would render to no reader. Both are checked."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.memory import Origin
    from core.database import get_unified_db
    from core.memory import get_memory_agent
    from core.memory.utils.interfaces import MemoryType
    from core.memory.utils.memory_injector import _percept_suffix
    from core.perception.perception_faculty import PerceptionFaculty
    from core.agents.autonomous.perception_manager import (
        PerceptionManager, get_acting_percept, set_acting_percept,
        reset_acting_percept)

    db = await get_unified_db()
    if not db.initialized:
        await db.initialize()
    agent = await get_memory_agent()
    TAG = "memory-percept-01-probe"

    # ── A. A SEEING IS A SCOPE ──────────────────────────────────────────────
    print("\n== A. The percept is bound by whoever owns the scope ==")
    pm = PerceptionManager()
    await pm.initialize()
    eyes = PerceptionFaculty()
    modality, content = await eyes.sense("test_data/vision_test.png",
                                         source="mp01_photo")
    from core.memory import Origin
    percept = await pm.process_input("mp01_photo", modality, content,
                                     origin=Origin.own("MEMORY-PERCEPT-01"))
    check("the image was really perceived", percept is not None, modality)
    check("perceiving leaves NOTHING bound — the hub does not own the scope",
          get_acting_percept() is None,
          "binding without owning the reset would leave a percept standing over "
          "unrelated later work — the recency defect by another route")
    meta = getattr(percept, "metadata", None) or {}
    check("but the percept's identity travels ON the percept, for a caller to bind",
          bool(meta.get("perception_id")), str(meta.get("perception_id")))
    EV.metric("percept_id_available", bool(meta.get("perception_id")), "bool")

    # ── B. LINKED WHILE SEEING ──────────────────────────────────────────────
    print("\n== B. A memory formed while seeing records WHICH percept ==")
    token = set_acting_percept(meta.get("perception_id"), meta.get("digest"))
    try:
        ok, seen_id = await agent.store_memory(
            content=f"observed the test card [{TAG}]",
            memory_type=MemoryType.EPISODIC, importance_score=0.8, origin=Origin.own("MEMORY-PERCEPT-01"))
    finally:
        reset_acting_percept(token)
    row = await db.execute_query(
        "SELECT percept_id, percept_digest FROM memory_hot.memory_hot "
        "WHERE memory_id = $1", (str(seen_id),), fetch_one=True)
    check("the memory records the percept it is of",
          bool(row) and row["percept_id"] == meta.get("perception_id"),
          str(row["percept_id"]) if row else None)
    check("and the digest of what was seen",
          bool(row) and bool(row["percept_digest"]),
          str(row["percept_digest"]) if row else None)

    # ── C. NOT BORROWED ─────────────────────────────────────────────────────
    print("\n== C. A memory formed outside a seeing links to nothing ==")
    ok2, unseen_id = await agent.store_memory(
        content=f"an unrelated thought [{TAG}]",
        memory_type=MemoryType.EPISODIC, importance_score=0.5, origin=Origin.own("MEMORY-PERCEPT-01"))
    row2 = await db.execute_query(
        "SELECT percept_id, percept_digest FROM memory_hot.memory_hot "
        "WHERE memory_id = $1", (str(unseen_id),), fetch_one=True)
    check("it carries no percept rather than the most recent one",
          bool(row2) and row2["percept_id"] is None
          and row2["percept_digest"] is None,
          "None — a memory that is not OF a seeing does not borrow one")
    EV.note("This is the check the old design could not pass. Attaching by a "
            "120-second recency window, a thought that merely FOLLOWED a "
            "perception was stamped with it, and nothing downstream could tell "
            "that apart from a memory genuinely of what was seen.")

    # ── D. IT RESOLVES, AND THE DIGEST MATCHES THE BYTES ────────────────────
    print("\n== D. The reference resolves to the record of the seeing ==")
    prow = await db.execute_query(
        "SELECT id, data_type, content FROM unified.perceptions WHERE id = $1",
        (row["percept_id"],), fetch_one=True)
    check("the percept id resolves to a stored percept", prow is not None,
          f"{prow['id']} ({prow['data_type']})" if prow else "DANGLING")
    sensed = {}
    if prow:
        sensed = (prow["content"] if isinstance(prow["content"], dict)
                  else json.loads(prow["content"]))
    check("the digest on the memory IS the digest of what was sensed",
          bool(sensed) and sensed.get("sha256") == row["percept_digest"],
          f"{sensed.get('sha256')} == {row['percept_digest']}")
    blobs = sensed.get("blobs") or []
    check("and the percept holds the STRUCTURE that was perceived, not a label",
          bool(blobs) and all(b.get("isa") for b in blobs),
          "; ".join(f"{b['name']} isa {'/'.join(b.get('isa') or [])}"
                    for b in blobs[:3]))
    EV.metric("percept_blobs", len(blobs), "count")
    EV.note("What makes this defensible rather than a recollection: the claim "
            "can be taken back to the object. The digest identifies the exact "
            "bytes, and the percept records what was actually sensed off them.")

    # ── E. IT SURVIVES RETRIEVAL ────────────────────────────────────────────
    print("\n== E. It reads back — a link that dies on the read is not wired ==")
    recalled = await agent.retrieve_memory(str(seen_id))
    check("the memory comes back from the store", recalled is not None,
          type(recalled).__name__ if recalled else "None")
    check("carrying the percept through RETRIEVAL, not only through the write",
          recalled is not None
          and getattr(recalled, "percept_id", None) == meta.get("perception_id")
          and bool(getattr(recalled, "percept_digest", None)),
          f"percept_id={getattr(recalled, 'percept_id', None)}")
    EV.note("`_row_to_memory_item` mapped neither this link nor the intent one "
            "when they were added, so both were written faithfully and returned "
            "as None on every read — and hot->cold migration reads through the "
            "same mapping, so the archive lost them too. Checked here through "
            "the path a reader actually uses, because a test that builds its "
            "own input cannot see that failure.")

    # ── F. AND REACHES THE READER ───────────────────────────────────────────
    print("\n== F. A recalled memory renders what it was of ==")
    rendered = _percept_suffix({
        "percept_id": getattr(recalled, "percept_id", None),
        "percept_digest": getattr(recalled, "percept_digest", None)})
    check("the recall names the seeing and the bytes",
          meta.get("perception_id") in rendered and "#" in rendered,
          rendered.strip())
    check("a memory that is of no percept renders nothing extra",
          _percept_suffix({"content": "x"}) == "")

    # ── G. MODALITY-AGNOSTIC ────────────────────────────────────────────────
    print("\n== G. The same link will carry hearing ==")
    from core.memory.utils.interfaces import MemoryItem
    import dataclasses
    fields = {f.name for f in dataclasses.fields(MemoryItem)}
    check("the field is named for PERCEPTION, not for one sense",
          "percept_id" in fields and "image_id" not in fields
          and "percept_digest" in fields,
          "percept_id / percept_digest — audio binds through the same door")
    heard = set_acting_percept("perc_mp01_audio", "aa11bb22cc33")
    try:
        ok3, audio_id = await agent.store_memory(
            content=f"heard the doorbell [{TAG}]",
            memory_type=MemoryType.EPISODIC, importance_score=0.5, origin=Origin.own("MEMORY-PERCEPT-01"))
    finally:
        reset_acting_percept(heard)
    row3 = await db.execute_query(
        "SELECT percept_id FROM memory_hot.memory_hot WHERE memory_id = $1",
        (str(audio_id),), fetch_one=True)
    check("a non-visual percept links through the same field, no new column",
          bool(row3) and row3["percept_id"] == "perc_mp01_audio",
          str(row3["percept_id"]) if row3 else None)

    # ── cleanup ─────────────────────────────────────────────────────────────
    try:
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE content::text LIKE $1",
            (f"%{TAG}%",), commit=True)
        await db.execute_query(
            "DELETE FROM unified.perceptions WHERE id = $1",
            (meta.get("perception_id"),), commit=True)
    except Exception as e:
        print(f"  (cleanup: {e})")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== MEMORY-PERCEPT-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
