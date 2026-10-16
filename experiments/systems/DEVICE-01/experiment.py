#!/usr/bin/env python3
"""DEVICE-01 — Lyric learns a device it operates through, as it learns where it runs.

A person's device answers for itself: what it is, what exists on it at all, and what the person set.
Lyric situates itself in it (`situate_device`) the way it situates itself in its host (`_situate`):

  1. A NEW KIND of device is a first-class ENVIRONMENT domain, announced once. Its kind (platform, major
     release, model, form) is its identity, not its owner: a second device of the same kind is not new.
  2. What exists there, as the device answered, becomes Lyric's OWN knowledge of that kind of place
     (the encounter's reaction, `_react_investigate_environment`): a capability it offers, and one it
     does not, as a fact with negative polarity.
  3. The device itself and what the person set on it are THEIRS: perceived with their origin, held in
     their scoped context, never in the shared graph.
  4. A location fix is the person's perception: the device is `located_at` a position held at about
     110 m, so a fix 30 m away meets the same position; a fix worse than 500 m is not evidence.
  5. The world inhabitant's `device` route reaches all of it, and refuses what is not a report or a
     location.

Every name written to shared knowledge carries this run's nonce (a made-up platform, model, form and
capabilities), and everything written is counted and removed by that nonce, the kind's domain id and the
test person's id. Never a reset.

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/systems/DEVICE-01/experiment.py
"""
from __future__ import annotations

import os

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_dev", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)

import asyncio
import contextlib
import io
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

from _evidence import RunRecord  # noqa: E402


def term(subject, relation, obj):
    """A fact in the learning door's own forms (`shape_proposition`), as the stores hold it: the checks
    ask the door how it names things rather than guessing its spelling."""
    from core.semantics.cognitive_ingress import shape_proposition
    s, r, o, refusal = shape_proposition(subject, relation, obj)
    return None if refusal else (s, r, o)

NONCE = f"d01{uuid.uuid4().hex[:8]}"
PERSON = f"device01-person-{NONCE}"
OTHER = f"device01-other-{NONCE}"


def report(device: str) -> dict:
    """A device's report, in the shape Lyric Beta sends: everything shared carries the nonce."""
    return {
        "device": device,
        "kind": {"platform": f"testos {NONCE}", "release": "26.0.1", "machine": f"model {NONCE}",
                 "form": f"phone {NONCE}", "manufacturer": f"maker {NONCE}"},
        "surface": {f"location {NONCE}": True, f"background location {NONCE}": True,
                    f"messages {NONCE}": False},
        "settings": {f"location {NONCE}": "granted", f"background location {NONCE}": "denied"},
    }


async def tagged_rows(db, tags):
    """Every row in every table of the store that names one of `tags` in a text column: what this run
    wrote. Counted per table, so 'nothing left' after cleanup is told apart from 'nothing written'."""
    columns = await db.execute_query(
        """SELECT table_schema, table_name, column_name FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND data_type IN ('text', 'character varying', 'jsonb', 'json')""", (), fetch_all=True) or []
    found = {}
    for col in columns:
        table = f'"{col["table_schema"]}"."{col["table_name"]}"'
        for tag in tags:
            try:
                row = await db.execute_query(
                    f'SELECT count(*) AS n FROM {table} WHERE "{col["column_name"]}"::text LIKE $1',
                    (f"%{tag}%",), fetch_one=True)
            except Exception:
                continue
            if row and row["n"]:
                found[(table, col["column_name"], tag)] = row["n"]
    return found


async def remove(db, tags, domain_id):
    """Remove this run's rows by its tags: the relations of its shared concepts first (they name the
    concepts by id), then every tagged row, retried until nothing more goes (references between tables)."""
    ids = [r["concept_id"] for r in (await db.execute_query(
        "SELECT concept_id FROM unified.concepts WHERE name LIKE $1 OR name = $2",
        (f"%{NONCE}%", domain_id), fetch_all=True) or [])]
    for concept in ids:
        await db.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id = $1 OR target_concept_id = $1",
            (concept,), fetch_all=False)
    for _ in range(4):
        left = await tagged_rows(db, tags)
        if not left:
            return
        for (table, column, tag) in left:
            try:
                await db.execute_query(f'DELETE FROM {table} WHERE "{column}"::text LIKE $1',
                                       (f"%{tag}%",), fetch_all=False)
            except Exception:
                continue


async def main() -> int:
    EV = RunRecord("DEVICE-01", results_dir=Path(__file__).resolve().parent / "results",
                   claim="Lyric learns a device it operates through as it learns where it runs: the kind is "
                         "its own knowledge of that place, the device and its settings are the person's.",
                   hypothesis="situate_device registers a new kind once, holds what exists there with "
                              "polarity, keeps the person's part scoped, and location fixes are the person's "
                              "perceptions at a ~110 m grain.")
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    from core.agents.autonomous.autonomous_coordinator import EnvironmentEncountered, SelfEventType
    from core.integration.world_inhabitant import WorldInhabitant
    EV.note(f"nonce {NONCE}; database {os.environ['POSTGRES_DATABASE']}")

    # The encounter's real reaction runs deferred, by the life loop this run does not start: catch the
    # event as it is emitted, then run the real reaction on it.
    met = []

    async def probe(event):
        met.append(event)
    coord.on(SelfEventType.ENVIRONMENT_ENCOUNTERED, probe, name="device01_probe", mode="sync", priority=10)

    device = f"Test phone {NONCE}"
    domain_id = None
    try:
        # 1. A new kind of device: a first-class environment, announced once.
        first = await coord.situate_device(report(device), actor_identity=PERSON)
        domain_id = first["environment"]
        row = await db.execute_query("SELECT domain_id, domain_name FROM unified.domains WHERE domain_id = $1",
                                     (domain_id,), fetch_one=True)
        EV.check("a new kind of device is a new environment domain", first["novel"] and row is not None,
                 f"{domain_id} {row and row['domain_name']}")
        encounters = [e for e in met if e.payload.domain == domain_id]
        EV.check("the encounter is announced once, with what the device answered",
                 len(encounters) == 1 and isinstance(encounters[0].payload, EnvironmentEncountered)
                 and f"messages {NONCE}" in encounters[0].payload.facts.get("surface", {}))
        EV.check("the answer says what it offers and what it lacks",
                 first["offers"] == sorted([f"background location {NONCE}", f"location {NONCE}"])
                 and first["lacks"] == [f"messages {NONCE}"], json.dumps(first)[:300])

        # 2. What exists there becomes Lyric's own knowledge of that kind of place.
        await coord._react_investigate_environment(encounters[0])
        held = await db.execute_query(
            """SELECT cr.relation, COALESCE(cr.target_surface, t.name) AS target, cr.polarity
                 FROM unified.concept_relations cr
                 JOIN unified.concepts s ON s.concept_id = cr.source_concept_id
            LEFT JOIN unified.concepts t ON t.concept_id = cr.target_concept_id
                WHERE s.name = $1""", (domain_id,), fetch_all=True) or []
        facts = {(h["relation"], str(h["target"]).lower(), str(h["polarity"] or "positive").lower()) for h in held}
        EV.note(f"held of the kind: {sorted(facts)}")
        offers = {t: p for (r, t, p) in facts if r == term(domain_id, "offers", "x")[1]}
        EV.check("it holds that this kind offers location",
                 offers.get(term(domain_id, "offers", f"location {NONCE}")[2], "").startswith("pos"))
        EV.check("it holds that this kind does NOT offer messages (negative polarity)",
                 offers.get(term(domain_id, "offers", f"messages {NONCE}")[2], "").startswith("neg"))
        EV.check("it holds what the kind is", any(r == "machine" and NONCE in t for (r, t, p) in facts)
                 and any(r == "platform" and NONCE in t for (r, t, p) in facts))
        EV.check("a device has no folder to count: no file counts held",
                 not any(r in ("entry_count", "file_count", "dir_count") for (r, t, p) in facts))

        # 3. Another person's device of the same kind is not a new place.
        second = await coord.situate_device(report(f"Other phone {NONCE}"), actor_identity=OTHER)
        EV.check("the same kind, someone else's device: not new, the same domain, no new encounter",
                 not second["novel"] and second["environment"] == domain_id
                 and len([e for e in met if e.payload.domain == domain_id]) == 1)

        # 4. The device and what the person set are theirs, never shared.
        mine = await db.execute_query(
            "SELECT subj, rel, obj, polarity FROM unified.scoped_concept_relations WHERE scope_actor = $1",
            (PERSON,), fetch_all=True) or []
        theirs = {(m["subj"], m["rel"], str(m["obj"]).lower(), str(m["polarity"] or "positive").lower()) for m in mine}
        EV.note(f"held for the person: {sorted(theirs)}")
        def has(rel, obj, positive=True, subject=device):
            want = term(subject, rel, obj)
            return any((s, r, o) == want and p.startswith("pos" if positive else "neg") for (s, r, o, p) in theirs)
        EV.check("the person's device is an instance of its model, in its kind's environment",
                 has("instance_of", f"model {NONCE}") and has("operates_in", domain_id))
        EV.check("what they allowed is held as allowed; what they refused, as refused",
                 has("allows", f"location {NONCE}") and has("allows", f"background location {NONCE}", positive=False))
        shared_device = await db.execute_query(
            "SELECT count(*) AS n FROM unified.concepts WHERE lower(name) = lower($1)", (device,), fetch_one=True)
        EV.check("nothing of the person's device is in the shared graph", shared_device["n"] == 0)

        # 5. Location: the person's perception, at a ~110 m grain.
        from core.memory import Origin
        origin = Origin.of(PERSON, "device")
        fix = {"device": device, "latitude": 25.76171, "longitude": -80.19181, "accuracy": 12,
               "at": "2026-10-02T14:05:00Z"}
        await coord.process_input(device, "location", fix, origin=origin)
        near = {**fix, "latitude": 25.76195, "longitude": -80.19160, "at": "2026-10-02T14:20:00Z"}
        await coord.process_input(device, "location", near, origin=origin)
        coarse = {**fix, "latitude": 25.9, "longitude": -80.3, "accuracy": 900, "at": "2026-10-02T14:30:00Z"}
        await coord.process_input(device, "location", coarse, origin=origin)
        here = term(device, "located_at", "25.762N 80.192W")
        located = await db.execute_query(
            """SELECT DISTINCT obj FROM unified.scoped_concept_relations
                WHERE scope_actor = $1 AND subj = $2 AND rel = $3""", (PERSON, here[0], here[1]), fetch_all=True) or []
        positions = sorted(str(r["obj"]) for r in located)
        EV.check("a fix is held as the person's: the device located at a position", here[2] in positions, f"{positions}")
        EV.check("a fix 30 m away is the same position; one 900 m out is not evidence", positions == [here[2]])
        lat = term("25.762N 80.192W", "latitude", "25.762")
        lon = term("25.762N 80.192W", "longitude", "-80.192")
        coordinates = await db.execute_query(
            """SELECT rel, obj FROM unified.scoped_concept_relations
                WHERE scope_actor = $1 AND subj = $2""", (PERSON, lat[0]), fetch_all=True) or []
        held_at = {(r["rel"], str(r["obj"])) for r in coordinates}
        EV.check("the position holds its latitude and its signed longitude", lat[1:] in held_at and lon[1:] in held_at,
                 f"{sorted(held_at)}")
        shared_position = await db.execute_query(
            "SELECT count(*) AS n FROM unified.concepts WHERE name = $1", (here[2],), fetch_one=True)
        EV.check("nothing of where the person was is in the shared graph", shared_position["n"] == 0)

        # 6. The world inhabitant's device route.
        inhabitant = WorldInhabitant(coord)
        answer = await inhabitant._device(PERSON, json.dumps({"report": report(device)}))
        EV.check("the device route situates a report and answers with what was learned",
                 answer.get("environment") == domain_id and answer.get("novel") is False, json.dumps(answer)[:200])
        taken = await inhabitant._device(PERSON, json.dumps({"location": fix}))
        EV.check("the device route takes a location", taken == {"received": True}, json.dumps(taken))
        EV.check("the device route refuses what is not JSON, and what is neither",
                 "refused" in await inhabitant._device(PERSON, "not json")
                 and "refused" in await inhabitant._device(PERSON, json.dumps({"weather": 1})))
        EV.check("a report that does not say what runs the device is refused",
                 "refused" in await inhabitant._device(PERSON, json.dumps({"report": {"kind": {}}})))
    finally:
        tags = [NONCE] + ([domain_id] if domain_id else [])
        before = await tagged_rows(db, tags)
        EV.metric("rows written by this run (before cleanup)", sum(before.values()))
        EV.note("tables written: " + ", ".join(sorted({t for (t, c, g) in before})))
        await remove(db, tags, domain_id or NONCE)
        after = await tagged_rows(db, tags)
        EV.metric("rows left after cleanup", sum(after.values()))
        EV.check("everything this run wrote is removed", sum(before.values()) > 0 and not after,
                 json.dumps({f"{t}.{c}": n for (t, c, g), n in after.items()})[:300])

    await EV.verify_database()
    path = EV.write()
    print(path.with_suffix(".md").read_text())
    return 0 if all(c.passed for c in EV.checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
