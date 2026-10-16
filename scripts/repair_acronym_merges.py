#!/usr/bin/env python3
"""Undo what acronym identity merged from labels that were never a document's.

Identity by initials is a document's habit (`concept_ingestion._DOCUMENT_SOURCES`), and it was tried on every label:
WordNet's names, taught on 2026-10-10, were fused with whatever short word their initials spell. `common_unicorn_plant`
and a party went into `cup`, `acute_lymphocytic_leukemia` into `all`, and `age` into `adorned_gilt_edged`; 329 aliases
and 1,825 facts on the wrong things. The beliefs were named before identity was resolved and are right; the graph and
the aliases are not.

For each alias recorded by initials whose name no document gave:
  1. the observations that named it, and what they wrote on the concept it was merged into, are taken off that concept
     (`MemoryAgent.release_evidence`), and the alias is let go (`release_alias`);
  2. links that named it and were attached to that concept wait again (`free_links`);
  3. those observations are read again through the one write path (`ConceptIngestionService.ingest`), which no longer
     resolves a curated name by its initials, so each lands on its own concept; the freed links are attached to it.

Run with no substrate on the store. Without --apply it changes nothing and reports what it would do. Refuses lyric_db
unless --main is given.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/repair_acronym_merges.py
    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/repair_acronym_merges.py --main --apply
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)


def _entries(structured, label_is) -> list:
    """The relationships an observation gave the concept it named, as `hold_concept` merges them."""
    out = []
    for concept in (structured or {}).get("concepts", []):
        if label_is(concept.get("label", "")):
            for edge in concept.get("relationships") or []:
                edge = list(edge)
                out.append([str(edge[0]), str(edge[1]), str(edge[2]) if len(edge) > 2 else "positive"])
    return out


async def repair(*, apply: bool, only: tuple = (), report=print) -> dict:
    """The repair, over every alias recorded by initials (or `only` these aliases). Returns what it found and did."""
    from core.agents.memory_agent import memory_agent
    from core.domain.concept_ingestion import (_DOCUMENT_SOURCES, EvidenceEnvelope, EvidenceSourceType,
                                               get_concept_ingestion_service)
    service = get_concept_ingestion_service()
    db = service.db()
    documents = [t.value for t in _DOCUMENT_SOURCES]
    aliases = await db.execute_query(
        "SELECT a.alias, a.concept_id, c.name FROM unified.concept_aliases a "
        "JOIN unified.concepts c ON c.concept_id = a.concept_id WHERE a.alias_kind = 'acronym' "
        + ("AND a.alias = ANY($1::text[]) " if only else "") + "ORDER BY a.alias",
        (list(only),) if only else None, fetch_all=True) or []
    report(f"{len(aliases)} aliases recorded by initials")
    plan, envelopes = [], {}
    for row in aliases:
        alias, concept_id, merged_into = row["alias"], row["concept_id"], row["name"]

        def names_alias(label: str, alias=alias) -> bool:
            return service.resolver.canonical_label(label) == alias
        rows = await db.execute_query(
            "SELECT e.evidence_id, e.source_type, e.source_id, e.producer, e.content, e.structured_data, "
            "e.derived_from, e.observed_at FROM unified.concept_evidence ce "
            "JOIN unified.evidence_envelopes e ON e.evidence_id = ce.evidence_id WHERE ce.concept_id = $1",
            (concept_id,), fetch_all=True) or []
        mine = []
        for e in rows:
            structured = e["structured_data"]
            structured = json.loads(structured) if isinstance(structured, str) else structured
            if any(names_alias(c.get("label", "")) for c in (structured or {}).get("concepts", [])):
                mine.append((e, structured))
        if any(e["source_type"] in documents for e, _ in mine):
            # A document named it: its initials are its business, and this repair leaves it as it is.
            continue
        surfaces = [r["target_surface"] for r in await db.execute_query(
            "SELECT DISTINCT target_surface FROM unified.concept_relations WHERE target_concept_id = $1",
            (concept_id,), fetch_all=True) or [] if names_alias(r["target_surface"])]
        plan.append((alias, concept_id, merged_into, mine, surfaces))
        for e, structured in mine:
            envelopes[e["evidence_id"]] = (e, structured)
    found = {"aliases": len(plan), "observations": len(envelopes), "surfaces": sum(len(p[4]) for p in plan)}
    report(f"to repair: {found['aliases']} aliases, {found['observations']} observations to read again, "
           f"{found['surfaces']} surfaces whose links wait again")
    for alias, concept_id, merged_into, mine, surfaces in plan[:15]:
        report(f"  {alias} -> {merged_into}: {len(mine)} observation(s), {len(surfaces)} surface(s)")
    if not apply:
        return {"found": found}

    taken = {"links": 0, "evidence": 0, "domains": 0, "entries": 0, "aliases": 0, "freed": 0}
    for alias, concept_id, merged_into, mine, surfaces in plan:
        def names_alias(label: str, alias=alias) -> bool:
            return service.resolver.canonical_label(label) == alias
        released = await memory_agent().release_evidence(
            concept_id=concept_id, evidence_ids=[e["evidence_id"] for e, _ in mine],
            entries=[entry for _, structured in mine for entry in _entries(structured, names_alias)])
        for key, n in released.items():
            taken[key] += n
        taken["aliases"] += await memory_agent().release_alias(alias=alias, concept_id=concept_id)
        if surfaces:
            taken["freed"] += await memory_agent().free_links(target_concept_id=concept_id,
                                                              target_surfaces=surfaces)
    report(f"taken off: {taken}")

    read = {"created": 0, "reinforced": 0, "rejected": 0}
    for evidence_id, (e, structured) in envelopes.items():
        derived = e["derived_from"]
        derived = json.loads(derived) if isinstance(derived, str) else (derived or [])
        result = await service.ingest(EvidenceEnvelope(
            evidence_id=evidence_id, source_type=EvidenceSourceType(e["source_type"]), source_id=e["source_id"],
            content=e["content"], producer=e["producer"], structured_data=structured or {},
            observed_at=e["observed_at"], derived_from=tuple(derived)))
        read["created"] += len(result.created)
        read["reinforced"] += len(result.reinforced)
        read["rejected"] += len(result.rejected)
    for alias, concept_id, merged_into, mine, surfaces in plan:
        for surface in surfaces:
            target = await service._resolve_target(surface)
            if target and target != concept_id:
                await memory_agent().attach_waiting_links(target_concept_id=target, target_surface=surface)
    waiting = await db.execute_query(
        "SELECT count(*) n FROM unified.concept_relations WHERE target_concept_id IS NULL "
        "AND target_surface = ANY($1::text[])", ([s for p in plan for s in p[4]],), fetch_all=True)
    left = await db.execute_query(
        "SELECT count(*) n FROM unified.concept_aliases WHERE alias_kind = 'acronym' "
        + ("AND alias = ANY($1::text[])" if only else ""), (list(only),) if only else None, fetch_all=True)
    report(f"read again: {read}; freed links still waiting: {waiting[0]['n']}; aliases by initials left: {left[0]['n']}")
    return {"found": found, "taken": taken, "read": read, "waiting": int(waiting[0]["n"]), "left": int(left[0]["n"])}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="repair; without it, only report")
    parser.add_argument("--main", action="store_true", help="allow lyric_db")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main:
        print("refused: name a store in POSTGRES_DATABASE, or pass --main for lyric_db")
        return 2
    from core.agents.memory_agent import get_memory_agent
    agent = await get_memory_agent()
    await agent.initialize()
    print(f"{database}:", flush=True)
    await repair(apply=args.apply, report=lambda line: print(line, flush=True))
    await agent.stop_memory_loops()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
