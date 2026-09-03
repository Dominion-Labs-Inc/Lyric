#!/usr/bin/env python3
"""Retype legacy COPULAR edges so classification questions stop reading UNKNOWN.

Early data stored "X is (a) Y" under the bare, UNTYPED copula `is` (and the
variants `is_a` / `is a` / `is a type of`). `concept_graph_reasoning` only walks
TYPED edges, so `kestrel is bird` was invisible and "is a kestrel a bird?" came
back UNKNOWN even though the fact was held.

This re-derives the type the CURRENT reader would assign to the same copular
sentence — `has_property` when the object is a known adjective, `isa` otherwise —
so the migrated edge matches how a query is read (the query side uses the same
rule, so they meet). Polarity is preserved untouched: a denial stays a denial.

Idempotent: after it runs, no copular-family relation remains, so a second run is
a no-op. Verb relations (provides/adds/…) and the inverse-direction `can be` are
deliberately NOT touched — they are not classification facts, and guessing a type
for them would be fabricating semantics.

Run:  PYTHONPATH="$PWD" ./venv_torin/bin/python3 scripts/migrate_copular_relations.py
"""
import asyncio
import io
import contextlib
import logging
import os

os.environ.setdefault("TQDM_DISABLE", "1")

#: The relations that mean "X is (a) Y" and belong in the typed taxonomy.
_COPULAR = ("is", "is_a", "is a", "is a type of")


async def main() -> None:
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        from core.database import get_database_manager
        from core.semantics.sentence_reader import _word_class

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()

    rows = await db.execute_query(
        """SELECT cr.source_concept_id AS sid, cr.relation AS rel,
                  cr.target_surface AS tsurf, cr.evidence_id AS eid,
                  cr.polarity AS pol, c2.name AS obj
           FROM unified.concept_relations cr
           LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id
           WHERE cr.relation = ANY($1)""",
        (list(_COPULAR),), fetch_all=True) or []

    to_isa = to_prop = deleted_dup = 0
    for r in rows:
        obj = r["obj"] or r["tsurf"] or ""
        # The reader's own rule: a KNOWN adjective is a property; everything else
        # (kinds, and adjectives it has not been taught) classifies as isa. The
        # query side reads the same way, so the two meet on the same atom.
        new_rel = "has_property" if _word_class(str(obj)) == "ADJECTIVE" else "isa"

        # A typed twin may already exist (same fact taught again, typed). The PK
        # is (source, relation, target_surface, evidence_id, polarity), so a
        # straight UPDATE would violate it; when the twin is there, the legacy row
        # is a duplicate and is removed rather than merged.
        clash = await db.execute_query(
            """SELECT 1 FROM unified.concept_relations
               WHERE source_concept_id=$1 AND relation=$2 AND target_surface=$3
                 AND evidence_id=$4 AND polarity=$5""",
            (r["sid"], new_rel, r["tsurf"], r["eid"], r["pol"]), fetch_all=True)
        if clash:
            await db.execute_query(
                """DELETE FROM unified.concept_relations
                   WHERE source_concept_id=$1 AND relation=$2 AND target_surface=$3
                     AND evidence_id=$4 AND polarity=$5""",
                (r["sid"], r["rel"], r["tsurf"], r["eid"], r["pol"]), commit=True)
            deleted_dup += 1
            continue

        await db.execute_query(
            """UPDATE unified.concept_relations SET relation=$2
               WHERE source_concept_id=$1 AND relation=$6 AND target_surface=$3
                 AND evidence_id=$4 AND polarity=$5""",
            (r["sid"], new_rel, r["tsurf"], r["eid"], r["pol"], r["rel"]),
            commit=True)
        if new_rel == "isa":
            to_isa += 1
        else:
            to_prop += 1

    print(f"copular edges seen : {len(rows)}")
    print(f"  -> isa           : {to_isa}")
    print(f"  -> has_property  : {to_prop}")
    print(f"  removed as dup   : {deleted_dup}")


if __name__ == "__main__":
    asyncio.run(main())
