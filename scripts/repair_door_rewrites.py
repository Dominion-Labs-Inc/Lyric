#!/usr/bin/env python3
"""Take back what WordNet taught under a name the door wrote wrong, so the sense can be taught again under its own.

The door's singular was one step of WordNet's plural rule, and a name it wrote was written again where it was taken
in: WordNet's `peoples` (the human beings of a particular nation) came in as `people` and was stored as `person`.
Twelve facts were the person's: a person a kind of group, defined with community and ethnic group, and what the Sioux,
the Iroquois and the Carib are defined with (`lexical_normalization.singularise`, "A SINGULAR IS WRITTEN THE SAME
AGAIN"). The door now leaves such a word as it is.

For each sense given whose name the door once wrote otherwise than it writes it now:
  1. every claim WordNet gave with the name as written then is withdrawn: WordNet's word on it is taken back
     (`BayesianUncertaintySystem.withdraw_observation`), and a claim nothing else vouches for is let go with its
     memory;
  2. every observation WordNet gave under that name is taken off each concept it was put on
     (`MemoryAgent.release_evidence`), and its record, written wrong, is let go (`release_envelope`): taught again
     it keeps its id, and the first record of an id is the one kept.
Then teach the senses again, through the one teaching path, written as the door writes them now:

    scripts/teach.py --source wordnet --sense peoples.n.01

Run with no substrate on the store. Without --apply it changes nothing and reports what it would do. Refuses lyric_db
unless --main is given.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/repair_door_rewrites.py --sense peoples.n.01
    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/repair_door_rewrites.py --sense peoples.n.01 --main --apply
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

#: WordNet's word on every fact it taught: the resource is the witness (`WordNetSource.provenance`).
WITNESS = "wordnet_3.0"


def written_once(name: str) -> str:
    """A name as the door wrote it before a singular had to be one the door leaves as it is: one step of the
    singular, the rest as `canonical_term` writes it."""
    from core.semantics import lexical_normalization as lexical
    whole = lexical.canonical_term(name)
    parts = whole.split("_")
    last = lexical.normalise(name).replace("-", "_").split("_")[-1]
    parts[-1] = lexical._singular_once(last)
    return "_".join(parts)


async def repair(*, senses, apply: bool, report=print) -> dict:
    """The repair, for `senses` (WordNet's names for them, `peoples.n.01`). Returns what it found and did."""
    from nltk.corpus import wordnet as wn
    from core.agents.memory_agent import memory_agent
    from core.database import get_database_manager
    from core.domain.concept_ingestion import get_concept_ingestion_service
    from core.learning.teaching_sources import WordNetSource
    from core.memory import knowledge_ledger as ledger
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics.cognitive_ingress import normalize_term

    names = WordNetSource()._sense_names()
    once = {}
    for sense in senses:
        name = names.get(wn.synset(sense), "")
        then, now = written_once(name), normalize_term(name)
        if not name or then == now:
            report(f"{sense}: named {name!r}, written {now!r} as it always was; nothing to repair")
            continue
        once[then] = now
        report(f"{sense}: named {name!r}, written {then!r} then and {now!r} now")
    if not once:
        return {"found": {}}

    us = get_uncertainty_system()
    claims = []
    for belief in list(us.beliefs.values()):
        words = str(belief.claim).split(" ")
        if words[0] not in once and words[-1] not in once:
            continue
        witnesses = {str(e.get("observation") or "") for e in list(belief.evidence_for) + list(belief.evidence_against)
                     if isinstance(e, dict)}
        if WITNESS in witnesses:
            claims.append((belief, witnesses - {WITNESS}))
    service = get_concept_ingestion_service()
    db = service.db()
    envelopes = []
    for then in once:
        rows = await db.execute_query(
            "SELECT evidence_id, structured_data FROM unified.evidence_envelopes WHERE source_id = $1 "
            "AND structured_data @> $2::jsonb ORDER BY evidence_id",
            (WITNESS, json.dumps({"concepts": [{"label": then}]})), fetch_all=True) or []
        envelopes.extend(rows)
    found = {"claims": len(claims), "let_go": sum(1 for _, others in claims if not others),
             "observations": len(envelopes)}
    report(f"to repair: {found['claims']} claims WordNet gave under the names written then "
           f"({found['let_go']} resting on nothing else), {found['observations']} observations to take off")
    for belief, others in claims:
        report(f"  {belief.claim}" + (f"  (also {sorted(others)})" if others else ""))
    if not apply:
        return {"found": found}

    agent = memory_agent()
    done = {"withdrawn": 0, "let_go": 0, "memories": 0, "links": 0, "evidence": 0, "entries": 0}
    updates = []
    batch = ledger.begin_batch(f"WordNet's {', '.join(sorted(once))} taught under a name the door wrote wrong; "
                               f"taught again as {', '.join(sorted(once.values()))}")
    try:
        for belief, others in claims:
            if us.withdraw_observation(belief.claim, WITNESS, source="taught") is not None:
                done["withdrawn"] += 1
        await us.drain_writes()
        for belief, others in claims:
            if others:
                updates.append(ledger.KnowledgeUpdate(
                    subject_kind="belief", subject_id=belief.belief_id, disposition=ledger.Disposition.UPDATED,
                    domain=belief.domain, detail=f"WordNet's word withdrawn: {belief.claim}"[:500]))
                continue
            memories = {str(e.get("memory_id")) for e in list(belief.evidence_for) + list(belief.evidence_against)
                        if isinstance(e, dict) and e.get("memory_id")}
            for memory_id in sorted(memories):
                if await agent.delete_memory(memory_id, reason=f"WordNet's word on {belief.claim!r} withdrawn"):
                    done["memories"] += 1
            if await us.let_go(belief.belief_id):
                done["let_go"] += 1
            updates.append(ledger.KnowledgeUpdate(
                subject_kind="belief", subject_id=belief.belief_id, disposition=ledger.Disposition.REMOVED,
                domain=belief.domain, detail=f"rested only on WordNet's word, withdrawn: {belief.claim}"[:500]))
        for row in envelopes:
            structured = row["structured_data"]
            structured = json.loads(structured) if isinstance(structured, str) else (structured or {})
            touched = await db.execute_query(
                "SELECT ce.concept_id, c.name FROM unified.concept_evidence ce JOIN unified.concepts c "
                "ON c.concept_id = ce.concept_id WHERE ce.evidence_id = $1", (row["evidence_id"],),
                fetch_all=True) or []
            for concept in touched:
                entries = [[str(e[0]), str(e[1]), str(e[2]) if len(e) > 2 else "positive"]
                           for c in structured.get("concepts", [])
                           if service.resolver.canonical_label(c.get("label", "")) == concept["name"]
                           for e in (c.get("relationships") or [])]
                released = await agent.release_evidence(concept_id=concept["concept_id"],
                                                        evidence_ids=[row["evidence_id"]], entries=entries)
                for key in ("links", "evidence", "entries"):
                    done[key] += released.get(key, 0)
            # THE RECORD GOES TOO: taught again, the observation has the same id (`admit_relation` keys it by what
            # the source said), and an envelope keeps the first record of its id, which would be this wrong one.
            if await agent.release_envelope(row["evidence_id"]):
                done["records"] = done.get("records", 0) + 1
        if updates:
            await ledger.record_many(get_database_manager(), updates)
    finally:
        ledger.end_batch(batch)
    left = await db.execute_query(
        "SELECT count(*) AS n FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
        ([r["evidence_id"] for r in envelopes],), fetch_all=True)
    report(f"done: {done}; records of them left: {left[0]['n']}")
    return {"found": found, "done": done, "left": int(left[0]["n"])}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sense", action="append", required=True, help="a WordNet sense (peoples.n.01)")
    parser.add_argument("--apply", action="store_true", help="repair; without it, only report")
    parser.add_argument("--main", action="store_true", help="allow lyric_db")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main:
        print("refused: name a store in POSTGRES_DATABASE, or pass --main for lyric_db")
        return 2
    from core.agents.memory_agent import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    agent = await get_memory_agent()
    await agent.initialize()
    await get_uncertainty_system().load_from_db()
    # THE WORDS BEFORE THE NAMES. `normalize_term` names a term from what Lyric holds (2026-11-13), and
    # `initialize` only STARTS the warm; waited for here, so a name this repair writes is the name the system
    # writes, not one the spelling rules reached for while the words were still being read.
    await agent.warm_word_classes()
    print(f"{database}:", flush=True)
    await repair(senses=args.sense, apply=args.apply, report=lambda line: print(line, flush=True))
    if args.apply:
        await get_uncertainty_system().flush_pending_writes()
    await agent.stop_memory_loops()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
