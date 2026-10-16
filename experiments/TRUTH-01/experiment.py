#!/usr/bin/env python3
"""TRUTH-01 — a claim about the world is judged by whether it is true, not by who said it.

The gate (docs/research/SEPARATION_MAP.md §11.4): every claim about the world, whoever or whatever says it, goes
through one door (`UnifiedLearningSystem.consider`), with its evidence -- a source, an independence key, a quality.
The same witness counts once however often it speaks; a witness that changes its word revises it; a claim held
against what the world holds is counted, and held only once its independent witnesses outweigh the ones holding
the other side; one witness makes a candidate, two settle it; one person's flood waits.

Each part is given to memory's real intake (`MemoryAgent.take_in_telling`, `take_in_research`), as Lyric hands it
over, and read back from the belief system, the concept graph, and the reasoner answering another person. Run on
the sandbox; every word the run makes up carries its nonce, and everything is removed after.

  A  A NEW CLAIM    one person's true new claim is a world candidate, and is used for another person
  B  CORROBORATED   one witness is a candidate; a second, independent, settles it; the first again adds nothing
  C  HARD TO MOVE   a claim six independent sites hold is not overturned by five people: each is refused, counted
                    against it, the denial is never held, and another person is still answered from it
  D  EVIDENCE       a claim one person holds is doubted by a second who denies it, and overturned by a third: the
                    denial is held, and answers now say no
  E  INDEPENDENCE   a page read twice, or another page of the same site, adds nothing; a second site raises it
  F  REVISION       a person who says "that's wrong" of their own telling withdraws their word and counts once
                    against it; saying it again adds nothing
  G  A FLOOD        one person's new claims beyond the hour's limit wait

Not checked here, and why: that a source proved wrong loses reliability. Every source weighs the same until the
sources' own records are kept (§11.9, 3: "we're going to work on sources later").

Run: ./venv_lyric/bin/python3 experiments/TRUTH-01/experiment.py
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
PEOPLE = [f"truth01-person{i}-{N}" for i in range(8)]

EV = RunRecord(
    "TRUTH-01",
    claim=("A claim about the world is judged by its evidence, not its teller: one witness makes a candidate used "
           "for everyone, a second settles it, the same witness counts once, a revised word is withdrawn, a claim "
           "many sources hold is not overturned by fewer, a single witness is overturned by more, and one "
           "person's flood waits."),
    hypothesis=("A one-person claim that is settled or unused for others, a repeat that moves a belief, five people "
                "overturning what six sites hold, two people unable to overturn one, a page or site counted twice, "
                "a revised word counted twice, or a flood all admitted would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.agents.memory_agent import memory_agent
    from core.learning.unified_learning_system import get_learning_authority
    from core.memory import Origin
    from core.memory.utils.interfaces import Telling
    from core.reasoning.bayesian_uncertainty import BayesianUncertaintySystem as Beliefs
    from core.reasoning.concept_graph_reasoning import answer_over_graph
    from core.reasoning.relation_algebra import FALSE, TRUE
    from core.semantics.derived_reader import MeaningFact
    from core.semantics.relation_types import SemanticRelation

    system, coord = await boot()
    d = db()
    memory = memory_agent()
    learning = get_learning_authority()

    async def tell(person, subject, obj, positive=True):
        taken = await memory.take_in_telling(Telling(
            sentence=f"{'A' if positive else 'No'} {subject} is a {obj}.", origin=Origin.of(person, "conversation"),
            facts=(MeaningFact("isa", subject, obj, positive),), speaker=person))
        return taken[0][2]

    def belief(subject, obj):
        return learning.belief_for_claim(" ".join(sep.shaped(subject, "isa", obj)))

    def witnesses(subject, obj, supports=True):
        held = belief(subject, obj)
        return 0 if held is None else Beliefs.witnesses(held, supports=supports)

    async def answered(subject, obj, actor):
        return (await answer_over_graph(d, subject, SemanticRelation.ISA, obj, actor=actor)).verdict

    try:
        where = await d.execute_query("SELECT current_database() AS d", (), fetch_one=True)
        check("the run is in the sandbox", where["d"] == "lyric_dev", where["d"])

        print("\n== A. One person's true new claim ==")
        first = await tell(PEOPLE[0], f"snib{N}", "bird")
        check("is a world candidate: held, used, not yet settled", first.standing == "candidate"
              and await sep.in_world(d, f"snib{N}", "isa", "bird"), f"{first.standing} {first.posterior}")
        check("and is used for another person", await answered(f"snib{N}", "bird", PEOPLE[1]) == TRUE)

        print("\n== B. Corroborated ==")
        second = await tell(PEOPLE[1], f"snib{N}", "bird")
        check("a second, independent witness settles it", second.standing == "settled"
              and witnesses(f"snib{N}", "bird") == 2, f"{second.standing}, {witnesses(f'snib{N}', 'bird')} witnesses")
        before = belief(f"snib{N}", "bird").posterior_probability
        await tell(PEOPLE[0], f"snib{N}", "bird")
        check("the first person again adds nothing",
              belief(f"snib{N}", "bird").posterior_probability == before and witnesses(f"snib{N}", "bird") == 2)

        print("\n== C. Hard to move ==")
        sites = [(f"krell{N}", "isa", "fish", f"https://site{i}-{N}.example.org/krell", f"A krell{N} is a fish.")
                 for i in range(6)]
        await memory.take_in_research(sites)
        check("six independent sites settle it", witnesses(f"krell{N}", "fish") == 6
              and learning._settled_on(belief(f"krell{N}", "fish"), positive=True))
        denied = [await tell(person, f"krell{N}", "fish", positive=False) for person in PEOPLE[:5]]
        check("five people denying it are each refused", all(dec.standing == "refused" for dec in denied),
              f"{[(dec.standing, dec.reasons[:1]) for dec in denied]}")
        check("each was counted against it", witnesses(f"krell{N}", "fish", supports=False) == 5)
        check("the denial is never held, and its witnesses still outweigh the denial's",
              not await sep.in_world(d, f"krell{N}", "isa", "fish", positive=False)
              and Beliefs.witness_weight(belief(f"krell{N}", "fish"), supports=True)
              > Beliefs.witness_weight(belief(f"krell{N}", "fish"), supports=False))
        check("another person is still answered from it", await answered(f"krell{N}", "fish", PEOPLE[6]) == TRUE)

        print("\n== D. The evidence decides ==")
        await tell(PEOPLE[0], f"glib{N}", "bird")
        doubting = await tell(PEOPLE[1], f"glib{N}", "bird", positive=False)
        check("one person's claim, denied by a second: doubted, counted, not held", doubting.standing == "doubted"
              and not await sep.in_world(d, f"glib{N}", "isa", "bird", positive=False),
              f"{doubting.standing} {doubting.reasons[:1]}")
        overturning = await tell(PEOPLE[2], f"glib{N}", "bird", positive=False)
        check("denied by a third: the denial outweighs it and is held", overturning.admitted
              and await sep.in_world(d, f"glib{N}", "isa", "bird", positive=False), overturning.standing)
        check("and another person is now answered no", await answered(f"glib{N}", "bird", PEOPLE[6]) == FALSE)

        print("\n== E. Independence ==")
        page = (f"zink{N}", "isa", "metal", f"https://one-{N}.example.org/zink", f"Zink{N} is a metal.")
        await memory.take_in_research([page])
        once = belief(f"zink{N}", "metal").posterior_probability
        await memory.take_in_research([page])
        await memory.take_in_research([(*page[:3], f"https://one-{N}.example.org/other-page", page[4])])
        check("the same page twice, and another page of the same site, add nothing",
              belief(f"zink{N}", "metal").posterior_probability == once and witnesses(f"zink{N}", "metal") == 1)
        await memory.take_in_research([(*page[:3], f"https://two-{N}.example.net/zink", page[4])])
        check("a second site raises it, and settles it",
              belief(f"zink{N}", "metal").posterior_probability > once and witnesses(f"zink{N}", "metal") == 2
              and learning._settled_on(belief(f"zink{N}", "metal"), positive=True))

        print("\n== F. Revision ==")
        await tell(PEOPLE[3], f"vorn{N}", "bird")
        await tell(PEOPLE[4], f"vorn{N}", "bird")
        await tell(PEOPLE[3], f"vorn{N}", "bird", positive=False)
        check("a person who says it is not so withdraws their word: one for, one against",
              witnesses(f"vorn{N}", "bird") == 1 and witnesses(f"vorn{N}", "bird", supports=False) == 1)
        moved = belief(f"vorn{N}", "bird").posterior_probability
        await tell(PEOPLE[3], f"vorn{N}", "bird", positive=False)
        check("saying it again adds nothing", belief(f"vorn{N}", "bird").posterior_probability == moved)

        print("\n== G. A flood ==")
        limit = learning.PERSON_CLAIMS_PER_HOUR
        flood = [await tell(PEOPLE[7], f"flood{N}x{i}", "bird") for i in range(limit + 3)]
        held = sum(dec.admitted for dec in flood)
        waits = [dec for dec in flood if dec.standing == "refused" and "in the hour" in " ".join(dec.reasons)]
        check(f"one person's new claims beyond {limit} in the hour wait", held == limit and len(waits) == 3,
              f"{held} held, {len(waits)} waiting")
    finally:
        removed = await sep.clean(d, N, PEOPLE, "truth01")
        EV.metric("rows_removed", sum(removed.values()), "count", f"{removed}")
        await shutdown(system)

    passed = sum(results)
    print(f"\n==== TRUTH-01: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
