#!/usr/bin/env python3
"""SPLIT-01 — what Lyric meets is split by what it is about.

The rule (docs/research/SEPARATION_MAP.md §11.3): a fact whose terms are all kinds, or particulars the world holds,
is about the world, and goes to the one door to be judged; a fact naming the person who told it, a particular of
theirs, or a name the world does not hold is about them, and is held in their context -- personal, or work and the
organization's -- where only they are answered from it. An experience holding both is split, part by part.

Each case below is given to memory's real intake (`MemoryAgent.take_in_*`), as Lyric hands it over, and where it
landed is read from the stores themselves. The destinations were written before the first run and are not changed
to fit a result. Run on the sandbox; every word the run makes up carries its nonce, and everything is removed after.

  world     an edge in the world's concept graph, and none in the person's context
  personal  an edge in the person's context, personal, and none in the world, which does not even name it
  work      an edge in the organization's Work Context (not the person's), none in the world, which does
            not even name it (docs/research/SEPARATION_MAP.md §11.13)
  speaker   what the person said of themselves, kept under them
  nothing   nowhere: not in the world, not in their context

Run: ./venv_lyric/bin/python3 experiments/SPLIT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")

from experiments import _separation as sep  # noqa: E402
from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

N = sep.nonce()
PERSON = f"split01-person-{N}"
ORG = f"split01-org-{N}"

#: THE CASES, AND WHERE EACH MUST LAND, frozen before the first run: (label, what is given, expected).
CASES = (
    ("a kind, told", f'"A wug{N} is a bird."', "world"),
    ("a particular the world holds, told", f'"Lumeria{N} is a port." (the world holds Lumeria{N} as a city)', "world"),
    ("a name the world does not hold", f'"Ava{N} is a dancer."', "personal"),
    ("the speaker, of themselves", '"I am a teacher."', "speaker"),
    ("a name, told at work", f'"Northwind{N} VPN is a network." through the work context', f"work:{ORG}"),
    ("their particular thing", f'"My printer is broken." (printer{N}_1, theirs)', "personal"),
    ("both in one telling", f'"A quill{N} is a bird and Ava{N} is happy."', "world + personal"),
    ("a rule of kinds", f'"If a wug{N} is hungry, a wug{N} is loud."', "world rule"),
    ("a rule of their particular", f'"If my printer is hot, my printer is loud."', "personal rule"),
    ("too weakly said", f'"A blorf{N} is a bird.", at quality 0.2', "nothing"),
    ("a page found by research", f'zorbite{N} is a mineral, on example.org', "world"),
    ("a thing in their picture, named", f'blob{N}_p in their photo named a printer', "personal"),
    ("a thing Lyric saw itself, named", f'blob{N}_l Lyric saw named a printer', "world"),
    ("Lyric's own observation of its host", f'host{N} is a machine', "world"),
    ("their device, as it reports itself", f'phone{N}, an iPhone, allows camera', "personal"),
    ("a sentence that did not read", f'"Glorp{N} frabbed the snoo."', "nothing (remembered as theirs)"),
)

EV = RunRecord(
    "SPLIT-01",
    claim=("Memory splits what Lyric meets by what it is about: kinds and what the world holds go to the one door; "
           "the speaker, their particulars and names the world does not hold go to their context, personal or "
           "work; a telling holding both is split; what is too weakly said, or did not read, is held nowhere."),
    hypothesis=("A case landing anywhere but where the table above says -- a person's thing in the world, a kind "
                "kept only for the person, work filed as personal, a weak telling held -- would fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.agents.memory_agent import memory_agent
    from core.learning.unified_learning_system import Evidence, Naming, get_learning_authority
    from core.memory import Origin
    from core.memory.utils.interfaces import Telling
    from core.semantics.derived_reader import MeaningFact

    system, coord = await boot()
    d = db()
    memory = memory_agent()
    learning = get_learning_authority()
    personal = Origin.of(PERSON, "conversation")
    at_work = Origin.of(PERSON, "conversation", context="work", organization=ORG)
    try:
        where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
        check("the run is in the sandbox", where["d"] == "lyric_dev", where["d"])
        print("\n== The cases, as frozen ==")
        for label, given, expected in CASES:
            print(f"    {label:40} {given:70} -> {expected}")
            EV.note(f"case: {label}: {given} -> {expected}")

        # What the world holds before any telling: Lumeria, a city (the world's own lesson).
        lesson = Evidence(source=f"lesson:split01-{N}", key=f"split01-{N}", source_type="IMPORTED_KNOWLEDGE",
                          quality=0.9)
        await learning.consider(f"lumeria{N}", "isa", "city", domain="split_01", evidence=lesson)

        async def tell(facts=(), rules=(), *, names=(), theirs=(), origin=personal, quality=0.9, said=""):
            return await memory.take_in_telling(Telling(
                sentence=said or f"split01 {N}", origin=origin, facts=tuple(facts), rules=tuple(rules),
                speaker=PERSON, theirs=frozenset(theirs), names=frozenset(names), quality=quality))

        async def world_only(subject, relation, obj):
            return (await sep.in_world(d, subject, relation, obj)
                    and await sep.in_context(d, PERSON, subject, relation, obj) is None)

        async def theirs_only(subject, relation, obj, context="personal", organization=None):
            owner = f"org:{organization}" if context == "work" else PERSON
            held = await sep.in_context(d, owner, subject, relation, obj)
            elsewhere = (await sep.in_context(d, PERSON, subject, relation, obj)) if owner != PERSON else None
            return (held == {"context": context, "organization": organization} and elsewhere is None
                    and not await sep.in_world(d, subject, relation, obj)
                    and not await sep.world_names(d, subject)), held

        async def nowhere(subject, relation, obj):
            return (not await sep.in_world(d, subject, relation, obj)
                    and await sep.in_context(d, PERSON, subject, relation, obj) is None)

        print("\n== Told ==")
        await tell([MeaningFact("isa", f"wug{N}", "bird")], said=f"A wug{N} is a bird.")
        check("a kind, told: the world's", await world_only(f"wug{N}", "isa", "bird"))

        await tell([MeaningFact("isa", f"Lumeria{N}", "port")], names=[f"Lumeria{N}"],
                   said=f"Lumeria{N} is a port.")
        check("a particular the world holds, told: the world's", await world_only(f"Lumeria{N}", "isa", "port"))

        await tell([MeaningFact("isa", f"Ava{N}", "dancer")], names=[f"Ava{N}"], said=f"Ava{N} is a dancer.")
        ok, held = await theirs_only(f"Ava{N}", "isa", "dancer")
        check("a name the world does not hold: theirs, personal, and the world does not even name it", ok, f"{held}")

        await tell([MeaningFact("isa", PERSON, "teacher")], said="I am a teacher.")
        spoken = await sep.about_speaker(d, PERSON, PERSON, "isa")
        check("the speaker, of themselves: kept under them, personal",
              spoken == {"object": "teacher", "context": "personal", "organization": None}
              and not await sep.in_world(d, PERSON, "isa", "teacher"), f"{spoken}")

        await tell([MeaningFact("isa", f"Northwind{N} VPN", "network")], names=[f"Northwind{N} VPN"],
                   origin=at_work, said=f"Northwind{N} VPN is a network.")
        ok, held = await theirs_only(f"Northwind{N} VPN", "isa", "network", "work", ORG)
        check("a name, told at work: the organization's Work Context, not the person's", ok, f"{held}")

        await tell([MeaningFact("has_property", f"printer{N}_1", "broken")], theirs=[f"printer{N}_1"],
                   said="My printer is broken.")
        ok, held = await theirs_only(f"printer{N}_1", "has_property", "broken")
        check("their particular thing: theirs", ok, f"{held}")

        await tell([MeaningFact("isa", f"quill{N}", "bird"), MeaningFact("has_property", f"Ava{N}", "happy")],
                   names=[f"Ava{N}"], said=f"A quill{N} is a bird and Ava{N} is happy.")
        ok, held = await theirs_only(f"Ava{N}", "has_property", "happy")
        check("both in one telling: split, the kind to the world and the name to them",
              await world_only(f"quill{N}", "isa", "bird") and ok, f"{held}")

        await tell(rules=[({"subject": f"wug{N}", "relation": "has_property", "obj": "hungry", "positive": True},
                           {"subject": f"wug{N}", "relation": "has_property", "obj": "loud", "positive": True})],
                   said=f"If a wug{N} is hungry, a wug{N} is loud.")
        check("a rule of kinds: a rule of the world's, and none in their context",
              await sep.rule_in_world(d, f"wug{N}") and await sep.rule_in_context(d, PERSON, f"wug{N}") is None)

        await tell(rules=[({"subject": f"printer{N}_1", "relation": "has_property", "obj": "hot", "positive": True},
                           {"subject": f"printer{N}_1", "relation": "has_property", "obj": "loud", "positive": True})],
                   theirs=[f"printer{N}_1"], said="If my printer is hot, my printer is loud.")
        held = await sep.rule_in_context(d, PERSON, f"printer{N}_1")
        check("a rule of their particular: theirs, and none in the world",
              held == {"context": "personal", "organization": None}
              and not await sep.rule_in_world(d, f"printer{N}_1"), f"{held}")

        taken = await tell([MeaningFact("isa", f"blorf{N}", "bird")], quality=0.2, said=f"A blorf{N} is a bird.")
        check("too weakly said: held nowhere, and why is said",
              await nowhere(f"blorf{N}", "isa", "bird") and all(not dec.admitted and dec.reasons
                                                                 for _, _, dec in taken),
              f"{[(dec.standing, dec.reasons) for _, _, dec in taken]}")

        print("\n== Found, seen, observed ==")
        await memory.take_in_research([(f"zorbite{N}", "isa", "mineral", f"https://example.org/zorbite{N}",
                                        f"Zorbite{N} is a mineral.")])
        check("a page found by research: the world's", await world_only(f"zorbite{N}", "isa", "mineral"))

        seen = Evidence(source="classifier:split01", key="classifier:split01", source_type="PERCEPTION",
                        quality=0.9, producer="clause_classifier:split01")
        await memory.take_in_recognised(Naming(f"blob{N}_p", "printer", seen), domain="perception", origin=personal)
        ok, held = await theirs_only(f"blob{N}_p", "isa", "printer")
        check("a thing in their picture, named: theirs", ok, f"{held}")
        await memory.take_in_recognised(Naming(f"blob{N}_l", "printer", seen), domain="perception",
                                         origin=Origin.own("split01"))
        check("a thing Lyric saw itself, named: the world's", await world_only(f"blob{N}_l", "isa", "printer"))

        sensed = Evidence(source="sense:environment", key=f"environment:split01-{N}", source_type="PERCEPTION",
                          quality=0.9, producer="perception")
        await memory.take_in_observed(f"host{N}", "isa", "machine", evidence=sensed, domain="environment")
        check("Lyric's own observation of its host: the world's", await world_only(f"host{N}", "isa", "machine"))

        await memory.take_in_percept(f"phone{N}", "device", {"device": f"phone{N}", "model": "iphone",
                                                             "settings": {"camera": "granted"}}, origin=personal)
        ok, held = await theirs_only(f"phone{N}", "allows", "camera")
        check("their device, as it reports itself: theirs", ok, f"{held}")

        await memory.take_in_unread(f"Glorp{N} frabbed the snoo.", origin=personal)
        await memory.drain_writes()
        kept = await d.execute_query("SELECT user_id FROM memory_hot.memory_hot WHERE content ILIKE $1",
                                     (f"%Glorp{N}%",), fetch_all=True) or []
        check("a sentence that did not read: no fact anywhere, remembered as theirs",
              kept and all(r["user_id"] == PERSON for r in kept) and not await sep.world_names(d, f"glorp{N}"),
              f"{[r['user_id'] for r in kept]}")
    finally:
        removed = await sep.clean(d, N, [PERSON, f"org:{ORG}"], "split01")
        await d.execute_query("DELETE FROM unified.work_authorizations WHERE person = $1", (PERSON,))
        EV.metric("rows_removed", sum(removed.values()), "count", f"{removed}")
        await shutdown(system)

    passed = sum(results)
    print(f"\n==== SPLIT-01: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
