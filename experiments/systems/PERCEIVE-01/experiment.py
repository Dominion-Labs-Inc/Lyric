#!/usr/bin/env python3
"""PERCEIVE-01 — feed the real substrate a sensor reading, an image, and a video
through its genuine perception path, then read back what it actually HOLDS.

The claim under test is narrow and honest: the substrate is model-free, so it
does not perceive pixels or waveforms. What it CAN do — and what this verifies —
is take the STRUCTURE an upstream detector/sensor/annotator supplies (a value
with a unit, a list of recognised labels, a duration, a capture date) and turn it
into first-class, provenance-carried, revisable knowledge through the one ingress
authority, exactly as a taught fact is.

Nothing is asserted by fiat. For each modality we drive
`PerceptionManager.process_input` (the real path: manager -> _observe_semantically
-> the modality producer -> ConceptIngestionService.ingest -> belief fan-out) and
then inspect the store directly:

  1. the perception was RETAINED (unified.perceptions),
  2. the observation reached the concept graph as edges (unified.concept_relations),
  3. a numeric value is held as a TYPED QUANTITY, not a word (unified.concepts),
  4. the substrate now BELIEVES the observations, with posteriors (unified.beliefs),
  5. every observation carries PERCEPTION provenance (unified.evidence_envelopes).

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-01/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent

# The three inputs. Each is STRUCTURE an upstream produced — a sensor bus, an
# object detector, a video analytic — never raw media. A fixed capture date so a
# re-run reinforces the same observation rather than minting a new one.
DAY = "2026-09-08"
INPUTS = [
    ("boiler_room", "sensor", {
        "sensor": "boiler_temp_sensor", "quantity": "temperature",
        "value": 94.5, "unit": "celsius", "at": DAY,
        "location": "primary boiler loop"}),
    ("front_door_camera", "image", {
        "detections": [{"label": "person", "confidence": 0.94},
                       {"label": "package"}],
        "dimensions": "1920x1080", "captured": DAY,
        "caption": "a person leaving a package at the door"}),
    ("lobby_camera", "video", {
        "detections": ["person"],
        "events": [{"label": "door_opening", "confidence": 0.81}],
        "duration": 12, "captured": DAY}),
]

# What each input should leave in the graph: (subject_concept, [(relation, target)]).
EXPECTED_EDGES = {
    "boiler_temp_sensor": [("reads", "94.5"), ("measures", "temperature"),
                           ("reads in", "celsius"), ("observed at", DAY)],
    "front_door_camera": [("observed", "person"), ("observed", "package"),
                          ("observed at", DAY)],
    "lobby_camera": [("observed", "person"), ("observed", "door_opening"),
                     ("lasts", "12"), ("observed at", DAY)],
}
SUBJECTS = list(EXPECTED_EDGES)


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()

        pm = getattr(coord, "perception", None)
        if pm is not None and not getattr(pm, "active", False):
            await pm.initialize()

    if pm is None:
        print("FAIL: coordinator has no perception manager to drive", flush=True)
        return 1

    print("=== feeding 3 perceptions through the real PerceptionManager path ===\n",
          flush=True)
    feed = []
    for source, data_type, content in INPUTS:
        from core.memory import Origin
        processed = await pm.process_input(source, data_type, content,
                                           origin=Origin.own("PERCEIVE-01"))
        retained = bool(processed and processed.metadata.get("retained"))
        feed.append({"source": source, "data_type": data_type,
                     "processed": processed is not None, "retained": retained})
        state = "retained" if retained else ("processed, NOT retained"
                                             if processed else "NOT processed")
        print(f"  [{data_type:6}] {source:18} -> {state}", flush=True)

    async def edges_for(subject):
        rows = await db.execute_query(
            """SELECT cr.relation, cr.target_surface,
                      cr.target_concept_id IS NOT NULL AS resolved
                 FROM unified.concept_relations cr
                 JOIN unified.concepts c ON cr.source_concept_id = c.concept_id
                WHERE c.name = $1
                ORDER BY cr.relation, cr.target_surface""",
            (subject,), fetch_all=True) or []
        # relation is stored canonicalised (underscores -> spaces at the door)
        return [(str(r["relation"]).replace("_", " ").strip(),
                 str(r["target_surface"]).strip(), bool(r["resolved"])) for r in rows]

    async def concept(name):
        rows = await db.execute_query(
            "SELECT name, concept_kind, attributes, provenance FROM unified.concepts "
            "WHERE name = $1 LIMIT 1", (name,), fetch_all=True) or []
        return dict(rows[0]) if rows else None

    async def beliefs_for(subject):
        rows = await db.execute_query(
            "SELECT claim, posterior_probability, domain FROM unified.beliefs "
            "WHERE claim ILIKE $1 ORDER BY posterior_probability DESC",
            (f"%{subject}%",), fetch_all=True) or []
        return [{"claim": r["claim"],
                 "posterior": round(float(r["posterior_probability"] or 0), 4),
                 "domain": r["domain"]} for r in rows]

    async def perception_provenance():
        rows = await db.execute_query(
            "SELECT producer, count(*) n FROM unified.evidence_envelopes "
            "WHERE lower(source_type) = 'perception' AND producer = ANY($1::text[]) "
            "GROUP BY producer ORDER BY producer", (SUBJECTS_SRC,), fetch_all=True) or []
        return {r["producer"]: int(r["n"]) for r in rows}

    SUBJECTS_SRC = [s for s, _, _ in INPUTS]

    print("\n=== what the substrate now HOLDS ===\n", flush=True)
    per_subject = {}
    for subject in SUBJECTS:
        held_edges = await edges_for(subject)
        held_pairs = {(rel, tgt) for rel, tgt, _ in held_edges}
        want = EXPECTED_EDGES[subject]
        missing = [f"{rel}->{tgt}" for rel, tgt in want if (rel, tgt) not in held_pairs]
        beliefs = await beliefs_for(subject)
        per_subject[subject] = {
            "edges": [{"relation": rel, "target": tgt, "resolved": res}
                      for rel, tgt, res in held_edges],
            "expected_edges": [f"{rel}->{tgt}" for rel, tgt in want],
            "missing_edges": missing,
            "beliefs": beliefs,
        }
        print(f"• {subject}", flush=True)
        for rel, tgt, res in held_edges:
            print(f"    edge:   {rel} -> {tgt}"
                  f"{'' if res else '   (target not yet a concept)'}", flush=True)
        for b in beliefs[:6]:
            print(f"    believes «{b['claim']}» -> {b['posterior']} [{b['domain']}]",
                  flush=True)
        if missing:
            print(f"    MISSING expected edges: {missing}", flush=True)
        print(flush=True)

    value = await concept("94.5")
    value_typed = bool(value and str(value.get("concept_kind")).lower() == "quantity")
    print(f"• typed value: 94.5 -> "
          f"{value.get('concept_kind') if value else 'ABSENT'} "
          f"{(value or {}).get('attributes') or ''}", flush=True)

    provenance = await perception_provenance()
    print(f"• PERCEPTION provenance envelopes by producer: {provenance}\n", flush=True)

    all_edges_present = all(not per_subject[s]["missing_edges"] for s in SUBJECTS)
    all_retained = all(f["retained"] for f in feed)
    any_beliefs = all(per_subject[s]["beliefs"] for s in SUBJECTS)
    provenance_ok = all(provenance.get(s, 0) > 0 for s in SUBJECTS_SRC)

    summary = {
        "all_retained": all_retained,
        "all_expected_edges_present": all_edges_present,
        "value_held_as_quantity": value_typed,
        "beliefs_held_for_every_subject": any_beliefs,
        "perception_provenance_present": provenance_ok,
        "verdict_pass": bool(all_retained and all_edges_present and value_typed
                             and any_beliefs and provenance_ok),
    }
    manifest = {
        "experiment": "PERCEIVE-01",
        "purpose": ("feed sensor/image/video through the real perception path and "
                    "verify each becomes provenance-carried, typed, believed knowledge"),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "inputs": [{"source": s, "data_type": d, "content": c} for s, d, c in INPUTS],
        "feed": feed,
        "held": per_subject,
        "typed_value": value,
        "provenance": provenance,
        "summary": summary,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("=== summary ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["verdict_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
