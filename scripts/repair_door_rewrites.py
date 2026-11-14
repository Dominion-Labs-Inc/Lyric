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
    """A name as the door wrote it before the changes that have moved one, which is the name the store holds it
    under.

    Five changes have moved a name since the store was taught:

      * a singular had to be one the door LEAVES AS IT IS -- WordNet's `peoples` came in as `people` and was
        stored as `person` (`lexical_normalization.singularise`, 2026-11-13);
      * a determiner had to come off BEFORE a hyphen was read as a break between words, so "a-bomb" was stored
        as `bomb` and "a-team" as `team` -- the thing fused with another the store cannot part again;
      * a count's plural had to be KEPT, so "15 minutes" was stored as `15_minute`;
      * short groups joined by a mark had to NAME a thing rather than operate, so "b-52" was stored as `b - 52`;
      * a mark between two digits had to be kept as the BREAK it is, so "9/11" was stored as `911`;
      * and the words had to be READ, because a plural's singular is what Lyric holds and not what spelling
        says: a door with nothing recorded to ask took the final "s" off by rule, so "acne vulgaris" was stored
        `acne_vulgari`, "acanthosis nigricans" `acanthosis_nigrican` and "abo antibodies" `abo_antibody`. 969 of
        WordNet's senses are held under such a name, and the door writes them rightly now that all 144,612 words
        are recorded (2026-11-14). This is the one way a name has moved that cannot be replayed by asking the
        system: the system is what changed, so the singular is taken by spelling alone (`asking=False`).

    Written out here rather than taken from the store, so a sense never taught is told apart from one taught
    under a name the door has since stopped writing."""
    import re as _re
    from core.semantics import lexical_normalization as lexical
    from core.semantics.literals import _OPERATES, classify_literal
    from core.reasoning.arithmetic_reading import read_expression, render
    literal = classify_literal(name)
    if literal is not None:
        return literal.canonical
    # The gate as it was: a slash name stayed unread, and a hyphen was read as a subtraction whatever stood
    # about it (`literals._JOINED_NAME` asks it of both marks now).
    if _OPERATES.search(name) and not _re.match(r"^\d{1,2}/\d{1,2}$", name):
        expression = read_expression(name)
        if expression is not None:
            return render(expression)
    s = lexical._WS.sub(" ", str(name).strip().lower())
    s = lexical._NORMALISE_STRIP.sub("", s)
    s = _re.sub(r"_+", "_", s.strip().replace(" ", "_").replace("-", "_")).strip("_")
    for prefix in lexical.DETERMINER_PREFIXES:
        if s.startswith(prefix) and len(s) > len(prefix):
            s = s[len(prefix):]
            break
    parts = [p for p in s.split("_") if p]
    if parts:
        parts[-1] = lexical._singular_once(parts[-1], asking=False)
    return "_".join(parts).strip("_")


async def repair(*, senses, apply: bool, take_back: bool = False, report=print) -> dict:
    """The repair, for `senses` (WordNet's names for them, `peoples.n.01`). Returns what it found and did.

    `take_back`: the names have NOT moved, and what was taught under them is taken back anyway so it can be
    taught again. A name is only the first thing that can go wrong on the way in. The door named "a-horizon"
    `a_horizon` and the concept resolver named that again and filed the facts on `horizon` -- so a pass could
    put the propositions and the beliefs in rightly and the concepts wrongly, and no comparison of names can
    find it, because the name the door writes now is the name it wrote then (lyric_db, 2026-11-13)."""
    from nltk.corpus import wordnet as wn
    from core.agents.memory_agent import memory_agent
    from core.database import get_database_manager
    from core.domain.concept_ingestion import get_concept_ingestion_service
    from core.learning.teaching_sources import WordNetSource
    from core.memory import knowledge_ledger as ledger
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics.cognitive_ingress import normalize_term

    names = WordNetSource()._sense_names()
    named = normalize_term if take_back else written_once
    once = {}
    for sense in senses:
        name = names.get(wn.synset(sense), "")
        then, now = named(name), normalize_term(name)
        if not name:
            continue
        if then == now and not take_back:
            report(f"{sense}: named {name!r}, written {now!r} as it always was; nothing to repair")
            continue
        report(f"{sense}: named {name!r}, taught under {then!r}"
               + (", taken back to be taught again" if take_back else f" and written {now!r} now"))
        once[then] = now
    if not once:
        return {"found": {}}

    # WHICH CLAIMS ARE THE SENSE'S OWN, ASKED OF THE SOURCE AND NOT OF THE NAME. A claim's text holds the names
    # the DOOR wrote, and the door wrote "a-list" and the list itself both as `list` -- so the text cannot tell
    # them apart. Taken by name, repairing eleven senses came to 390 claims answered by `list`, `team`, `horizon`
    # and `911`, among them "faq isa list", "blacklist defined with list", "volleyball net defined with team" and
    # "horizon part of perspective": all but about thirty of them the OTHER thing's, and withdrawing them would
    # have taken out what the store rightly holds to recover what it wrongly holds (lyric_db, 2026-11-13).
    #
    # So the claims are every fact WORDNET STATES with one of these senses on either side (`WordNetSource.senses`
    # filters its records to exactly that), each written as the door wrote it then. A sense's own facts and no
    # others.
    source = WordNetSource(senses=tuple(senses))
    wanted, ever = set(), set()
    for taught in source.records():
        relation = str(taught.relation).replace("_", " ")
        for how, into in ((named, wanted), (written_once, ever), (normalize_term, ever)):
            subject = how(str(taught.subject))
            obj = how(str(taught.obj)) if taught.obj else ""
            into.add(" ".join(part for part in (subject, relation, obj) if part))
    report(f"WordNet states {len(wanted)} fact(s) of these senses, as the door wrote them then")

    us = get_uncertainty_system()
    claims = []
    for belief in list(us.beliefs.values()):
        if str(belief.claim) not in wanted:
            continue
        witnesses = {str(e.get("observation") or "") for e in list(belief.evidence_for) + list(belief.evidence_against)
                     if isinstance(e, dict)}
        if WITNESS in witnesses:
            claims.append((belief, witnesses - {WITNESS}))
    service = get_concept_ingestion_service()
    db = service.db()
    # AND THE OBSERVATIONS OF THOSE SAME FACTS. An envelope holds the door's names too ("met in use: 'listed
    # defined with list'"), so it is narrowed the same way: of the envelopes put on a name written then, only
    # those whose own account is one of the facts above.
    envelopes = []
    held = set()
    for then in once:
        rows = await db.execute_query(
            "SELECT evidence_id, structured_data FROM unified.evidence_envelopes WHERE source_id = $1 "
            "AND structured_data @> $2::jsonb ORDER BY evidence_id",
            (WITNESS, json.dumps({"concepts": [{"label": then}]})), fetch_all=True) or []
        for row in rows:
            said = json.dumps(row["structured_data"]) if not isinstance(row["structured_data"], str) \
                else row["structured_data"]
            if any(f"'{claim}'" in said for claim in wanted) and str(row["evidence_id"]) not in held:
                held.add(str(row["evidence_id"]))
                envelopes.append(row)
    # AND THE EDGES THE CLAIMS NAME, WHEREVER THEY SIT. The door decides a fact is held already by looking for
    # its EDGE in the graph and not for its record, so an edge left behind makes the fact UNTEACHABLE: a pass
    # skips it as held already and it never comes back. The envelopes above are found by the label written then,
    # and an edge whose concept has since been named otherwise is not among them -- so seven facts of eleven
    # senses, every one of them an `isa`, stayed out of the store through two repairs and showed as "already"
    # both times (`english:list isa list`, `reading:team isa team`, `english:r - 2 isa flunitrazepan`;
    # lyric_db, 2026-11-14). An edge goes when the claim it spells was taken back and no belief vouches for it.
    backed = {str(belief.claim) for belief, others in claims if others}
    # UNDER EVERY NAME THE DOOR HAS WRITTEN FOR IT (`ever`), not only the one asked for here: an edge left behind
    # by an earlier pass spells the name of its own day, and the seven that survived two repairs spelled the
    # names from before the fixes (`english:list isa list`) while this run was asking after `a_list isa list`.
    targets = sorted({claim.rsplit(" ", 1)[-1] for claim in ever if " " in claim})
    edges = []
    if targets:
        rows = await db.execute_query(
            "SELECT r.source_concept_id, r.relation, r.target_surface, c.name FROM unified.concept_relations r "
            "JOIN unified.concepts c ON c.concept_id = r.source_concept_id "
            "WHERE r.target_surface = ANY($1::text[])", (targets,), fetch_all=True) or []
        for row in rows:
            spells = f"{row['name']} {row['relation']} {row['target_surface']}"
            if spells in ever and spells not in backed:
                edges.append(row)
    found = {"claims": len(claims), "let_go": sum(1 for _, others in claims if not others),
             "observations": len(envelopes), "edges": len(edges)}
    report(f"to repair: {found['claims']} claims WordNet gave under the names written then "
           f"({found['let_go']} resting on nothing else), {found['observations']} observations to take off, "
           f"{found['edges']} edge(s) in the graph no belief vouches for")
    for row in edges:
        report(f"  edge {row['source_concept_id']} {row['relation']} {row['target_surface']}")
    for belief, others in claims:
        report(f"  {belief.claim}" + (f"  (also {sorted(others)})" if others else ""))
    if not apply:
        return {"found": found}

    agent = memory_agent()
    done = {"withdrawn": 0, "let_go": 0, "memories": 0, "links": 0, "evidence": 0, "entries": 0, "edges": 0}
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
        for row in edges:
            await db.execute_query(
                "DELETE FROM unified.concept_relations WHERE source_concept_id = $1 AND relation = $2 "
                "AND target_surface = $3",
                (row["source_concept_id"], row["relation"], row["target_surface"]), commit=True)
            done["edges"] += 1
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
    parser.add_argument("--take-back", action="store_true", dest="take_back",
                        help="the names have not moved: take back what was taught under them anyway, so a pass "
                             "that went in under a defect further along can be taught again")
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
    await repair(senses=args.sense, apply=args.apply, take_back=args.take_back,
                 report=lambda line: print(line, flush=True))
    if args.apply:
        await get_uncertainty_system().flush_pending_writes()
    await agent.stop_memory_loops()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
