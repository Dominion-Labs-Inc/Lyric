#!/usr/bin/env python3
"""Take back what WordNet taught under names its senses no longer have, so they can be taught again under their own.

WordNet's senses are taught under the names `WordNetSource._sense_names` gives them, and the name a word keeps across
parts of speech follows how the English lessons use it (`_lesson_parts`). Counting a degree's kind as a thing's
("The car is faster than the bike.": `instance_of(?d, fast)`) gave "fast", "old" and "deep" to the nouns (fasting,
past times, the deep), and the adjectives were taught as `accelerated fast`, `aged old` and `heavy deep`: "Cars are
fast." read as cars being abstinences. Counted an adjective's, the names went back, and a store taught before holds
both senses under the names they had.

`--was` names a file `{"taught_under": {sense: the name it was taught under}}`. For every sense whose name now differs,
and every sense that shared an old name with it:
  1. WordNet's word on each fact it gave under an old name is withdrawn
     (`BayesianUncertaintySystem.withdraw_observation`); a fact nothing else vouches for is let go with its memory;
  2. its observations under an old name are taken off each concept (`MemoryAgent.release_evidence`) and their records
     let go (`release_envelope`): taught again, an observation keeps its id;
  3. the word pairs WordNet taught with a word naming an old name are withdrawn (`withdraw_pairs`), and its counts of
     how often a word names that thing (`wordnet_3.0:usage`) are withdrawn from those claims only.
Then teach the senses again, through the one teaching path, under the names they have now; the script prints the
command.

Run with no substrate on the store. Without --apply it changes nothing and reports what it would do. Refuses lyric_db
unless --main is given.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/repair_renamed_senses.py --was logs/renamed_senses_20261012.json
    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/repair_renamed_senses.py --was logs/renamed_senses_20261012.json --main --apply
"""
import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

#: WordNet's provenance: its word on a fact is this observation; on a word pair `wordnet_3.0:<pair>`; on how often a
#: word names a thing `wordnet_3.0:usage`.
WITNESS = "wordnet_3.0"
USAGE = f"{WITNESS}:usage"
PAIR = re.compile(rf"^{re.escape(WITNESS)}:[0-9a-f]{{16}}$")
NAMES = re.compile(r'^"[^"]+" names (.+)$')


def affected(was: dict):
    """(the old names, written as the door writes them -> the name now; the senses to teach again)."""
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import WordNetSource
    from core.semantics.cognitive_ingress import normalize_term
    names = WordNetSource()._sense_names()
    old = {sense: name for sense, name in was.items() if names.get(wn.synset(sense), "") != name}
    # The renamed senses, and every sense named now as one of them was: those that kept an old name alongside it
    # ("fast" the adverb, beside fasting) and those that took one ("fast" the adjective).
    teach = sorted(set(old) | {s.name() for s, n in names.items() if n and n in set(old.values())})
    return {normalize_term(n): n for n in old.values()}, old, teach


async def repair(*, was: dict, apply: bool, report=print) -> dict:
    from core.agents.memory_agent import memory_agent
    from core.database import get_database_manager
    from core.domain.concept_ingestion import get_concept_ingestion_service
    from core.learning.unified_learning_system import get_learning_authority
    from core.memory import knowledge_ledger as ledger
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system

    door, old, teach = affected(was)
    if not old:
        report("every sense has the name it was taught under; nothing to repair")
        return {"found": {}}
    for sense, name in sorted(old.items()):
        report(f"{sense}: taught as {name!r}")
    report(f"to teach again: {' '.join(teach)}")
    us = get_uncertainty_system()
    written = set(door.values())
    facts, words, usage = [], set(), []
    for belief in list(us.beliefs.values()):
        claim = str(belief.claim)
        entries = [e for e in list(belief.evidence_for) + list(belief.evidence_against) if isinstance(e, dict)]
        given = {str(e.get("observation") or "") for e in entries}
        tokens = claim.split(" ")
        if WITNESS in given and (tokens[0] in door or tokens[-1] in door):
            facts.append((belief, given - {WITNESS}))
        named = NAMES.match(claim)
        if named and named.group(1) in written:
            words.update(o for o in given if PAIR.match(o) and us._witness_word(belief, o) is not None)
            if USAGE in given and us._witness_word(belief, USAGE) is not None:
                usage.append(belief)
    service = get_concept_ingestion_service()
    db = service.db()
    envelopes = []
    for label in door:
        envelopes.extend(await db.execute_query(
            "SELECT evidence_id, structured_data FROM unified.evidence_envelopes WHERE source_id = $1 "
            "AND structured_data @> $2::jsonb ORDER BY evidence_id",
            (WITNESS, json.dumps({"concepts": [{"label": label}]})), fetch_all=True) or [])
    found = {"facts": len(facts), "let_go": sum(1 for _, others in facts if not others),
             "observations": len(envelopes), "word_pairs": len(words), "usage": len(usage)}
    report(f"to repair: {found['facts']} facts WordNet gave under the old names ({found['let_go']} resting on "
           f"nothing else), {found['observations']} observations to take off, {found['word_pairs']} word pairs "
           f"and {found['usage']} counts of use to withdraw")
    if not apply:
        return {"found": found, "teach": teach}

    agent = memory_agent()
    done = {"withdrawn": 0, "let_go": 0, "memories": 0, "links": 0, "evidence": 0, "entries": 0, "records": 0,
            "usage": 0}
    updates = []
    cause = (f"WordNet's senses taught under names they no longer have ({', '.join(sorted(written))}); taught "
             f"again under their own")
    batch = ledger.begin_batch(cause)
    try:
        for belief, _ in facts:
            if us.withdraw_observation(belief.claim, WITNESS, source="taught") is not None:
                done["withdrawn"] += 1
        for belief in usage:
            if us.withdraw_observation(belief.claim, USAGE, source="taught") is not None:
                done["usage"] += 1
        await us.drain_writes()
        for belief, others in facts:
            if others:
                updates.append(ledger.KnowledgeUpdate(
                    subject_kind="belief", subject_id=belief.belief_id, disposition=ledger.Disposition.UPDATED,
                    domain=belief.domain, detail=f"WordNet's word withdrawn: {belief.claim}"[:500]))
                continue
            for memory_id in sorted({str(e.get("memory_id")) for e in list(belief.evidence_for)
                                     + list(belief.evidence_against) if isinstance(e, dict) and e.get("memory_id")}):
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
            if await agent.release_envelope(row["evidence_id"]):
                done["records"] += 1
        if updates:
            await ledger.record_many(get_database_manager(), updates)
    finally:
        ledger.end_batch(batch)
    done["word_pairs"] = await get_learning_authority().withdraw_pairs(words, cause=cause, apply=True)
    report(f"done: {done}")
    return {"found": found, "done": done, "teach": teach}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--was", required=True, help="the names the senses were taught under (json)")
    parser.add_argument("--apply", action="store_true", help="repair; without it, only report")
    parser.add_argument("--main", action="store_true", help="allow lyric_db")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main:
        print("refused: name a store in POSTGRES_DATABASE, or pass --main for lyric_db")
        return 2
    was = json.loads(Path(args.was).read_text())["taught_under"]
    from core.agents.memory_agent import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    agent = await get_memory_agent()
    await agent.initialize()
    await get_uncertainty_system().load_from_db()
    await agent.warm_word_classes()
    print(f"{database}:", flush=True)
    result = await repair(was=was, apply=args.apply, report=lambda line: print(line, flush=True))
    if args.apply:
        await get_uncertainty_system().flush_pending_writes()
    if result.get("teach"):
        print("then: scripts/teach.py --source wordnet --domain english "
              + " ".join(f"--sense {s}" for s in result["teach"]), flush=True)
    await agent.stop_memory_loops()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
