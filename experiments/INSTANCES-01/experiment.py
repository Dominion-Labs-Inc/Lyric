#!/usr/bin/env python3
"""INSTANCES-01 — many instances of the model, one store: no instance undoes another.

Once the main model is taught, it runs as multiple instances. Every instance holds its OWN in-memory copies of beliefs, strategy arms, known
unknowns and queued work, and they all write the ONE store. Measured before this run's
fixes, four writes were last-writer-wins, so instances silently undid each other:

  beliefs          a plain upsert of the posterior -> one instance's evidence lost
  strategy arms    absolute trial/success counts upserted -> outcomes lost
  known unknowns   the full row upserted -> a stale instance reopens a resolved one
  durable queue    every boot re-queued ALL owed rows and reset running ones -> a job runs twice

Each is exercised here with two instances' worth of separate objects against the live store
(the store is where the conflict lives; the process boundary adds nothing to it):

  A  beliefs:        both instances update one belief -> both pieces of evidence are in it
  B  strategy arms:  3 outcomes from one, 2 from the other -> the stored arm has 5
  C  known unknowns: one resolves, the stale other writes -> still resolved; attempts from
                     both count; the stale instance's refresh drops it
  D  queue:          a living instance's job is not claimed; a stopped one's is; two
                     instances racing for one ownerless job -> exactly one gets it

Everything written is removed by id.

Run: ./venv_torin/bin/python3 experiments/INSTANCES-01/experiment.py
"""
from __future__ import annotations

import asyncio
import copy
import os
import random
import string
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402

N = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
EV = RunRecord(
    "INSTANCES-01",
    claim=("Several instances of the model share one store without undoing each other: every "
           "instance's evidence, outcomes and attempts count, a resolution is final, and a "
           "queued job is run by exactly one instance."),
    hypothesis=("A lost belief update, a lost strategy outcome, a reopened unknown, a claimed "
                "living instance's job, or a job claimed twice would each show here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.database import get_database_manager
    from core.reasoning.bayesian_uncertainty import (BayesianUncertaintySystem, ResolutionGrounds,
                                                     KnowledgeState, posterior_from_evidence)
    d = get_database_manager()
    await d.initialize()
    written = {"beliefs": [], "strategies": [], "unknowns": [], "tasks": [], "instances": []}
    try:
        print("\n== A. Beliefs: two instances update one belief ==")
        mem = await d.execute_query("SELECT memory_id FROM memory_hot.memory_hot LIMIT 1", (),
                                    fetch_one=True)
        A, B = BayesianUncertaintySystem(), BayesianUncertaintySystem()
        for inst in (A, B):
            await inst.unified_db.initialize()
        belief = A.create_belief(f"instances probe {N}: the pump runs", f"instances_{N}", 0.5, None)
        belief.memory_id = mem["memory_id"]
        written["beliefs"].append(belief.belief_id)
        await A.flush_belief(belief.belief_id)
        B.beliefs[belief.belief_id] = copy.deepcopy(belief)            # B loaded it too
        A.update_belief(belief.belief_id, {"source": "instance A", "quality": 0.9}, True)
        after_a = A.beliefs[belief.belief_id].posterior_probability
        await A.flush_belief(belief.belief_id)
        B.update_belief(belief.belief_id, {"source": "instance B", "quality": 0.8}, True)
        b_weight = B.beliefs[belief.belief_id].unsaved_evidence[-1][2]  # as B applied it
        await B.flush_belief(belief.belief_id)                          # B's copy is stale
        row = await d.execute_query(
            "SELECT posterior_probability, update_count, evidence_for FROM unified.beliefs "
            "WHERE belief_id = $1", (belief.belief_id,), fetch_one=True)
        sources = [e.get("source") for e in (row["evidence_for"] if isinstance(row["evidence_for"], list)
                                             else __import__("json").loads(row["evidence_for"]))]
        check("both instances' evidence is in the stored belief",
              "instance A" in sources and "instance B" in sources and row["update_count"] == 2,
              f"evidence={sources} update_count={row['update_count']}")
        expected, _ = posterior_from_evidence(after_a, b_weight, True)
        check("the stored posterior is A's update with B's evidence applied on top",
              abs(float(row["posterior_probability"]) - expected) < 1e-6,
              f"stored={float(row['posterior_probability']):.6f} expected={expected:.6f}")

        print("\n== B. Strategy arms: outcomes from two instances add up ==")
        from core.learning.meta_learning import MetaLearner, OutcomeClass, TaskFamily
        ml_a, ml_b = MetaLearner(), MetaLearner()
        for ml in (ml_a, ml_b):
            await ml.initialize()
        arm = f"instances_probe_{N}"
        for _ in range(3):
            await ml_a.track_learning_outcome(TaskFamily.CONTROL, arm, True, 1.0, 5.0,
                                              outcome_class=OutcomeClass.SUCCESS)
        for _ in range(2):
            await ml_b.track_learning_outcome(TaskFamily.CONTROL, arm, True, 1.0, 5.0,
                                              outcome_class=OutcomeClass.SUCCESS)
        stored = await d.execute_query(
            "SELECT strategy_id, trials, successes FROM meta_learning_strategies "
            "WHERE strategy_type = $1", (arm,), fetch_all=True) or []
        written["strategies"] += [r["strategy_id"] for r in stored]
        check("the stored arm holds all five outcomes", len(stored) == 1 and stored[0]["trials"] == 5
              and stored[0]["successes"] == 5, f"{[dict(r) for r in stored]}")
        b_arm = next((s for s in ml_b.strategies.values() if str(s.strategy_type) == arm), None)
        check("and the second instance's copy took the store's totals back",
              b_arm is not None and b_arm.trials == 5, f"B sees {getattr(b_arm, 'trials', None)}")

        print("\n== C. Known unknowns: a resolution is final; attempts from both count ==")
        ku = A.register_known_unknown(f"what is unresolved about instances probe {N}?",
                                      f"instances_{N}", [], [],
                                      target={"kind": "settled", "about": f"instances probe {N}"})
        written["unknowns"].append(ku.unknown_id)
        await A.drain_writes()
        B.known_unknowns[ku.unknown_id] = copy.deepcopy(ku)             # B loaded it open
        grounds = ResolutionGrounds(ku.unknown_id, (True, "probe"), (True, "probe"), (True, "probe"),
                                    answer="settled by the probe", belief_id=belief.belief_id)
        A.resolve_known_unknown(ku.unknown_id, grounds)
        await A.drain_writes()
        B.note_resolution_attempt(ku.unknown_id)                       # stale B keeps working
        B._save_known_unknown(B.known_unknowns[ku.unknown_id])
        await B.drain_writes()
        row = await d.execute_query(
            "SELECT knowledge_state, resolved_at, resolution_attempts FROM unified.known_unknowns "
            "WHERE unknown_id = $1", (ku.unknown_id,), fetch_one=True)
        check("a stale instance cannot reopen a resolved unknown",
              row["knowledge_state"] == KnowledgeState.KNOWN_KNOWN.value and row["resolved_at"] is not None,
              f"{dict(row)}")
        refreshed = await B.refresh_known_unknowns()
        check("and its refresh drops it from its open set", ku.unknown_id not in B.known_unknowns,
              f"{refreshed}")
        ku2 = A.register_known_unknown(f"what is unresolved about instances probe two {N}?",
                                       f"instances_{N}", [], [],
                                       target={"kind": "settled", "about": f"instances probe two {N}"})
        written["unknowns"].append(ku2.unknown_id)
        await A.drain_writes()
        B.known_unknowns[ku2.unknown_id] = copy.deepcopy(ku2)
        A.note_resolution_attempt(ku2.unknown_id)
        B.note_resolution_attempt(ku2.unknown_id)
        await A.drain_writes()
        await B.drain_writes()
        row = await d.execute_query(
            "SELECT resolution_attempts FROM unified.known_unknowns WHERE unknown_id = $1",
            (ku2.unknown_id,), fetch_one=True)
        check("attempts from both instances count", row["resolution_attempts"] == 2,
              f"stored attempts={row['resolution_attempts']}")

        print("\n== D. The queue: one job, one instance ==")
        from core.agents.autonomous.queue_persistence import QueuePersistence
        from core.agents.autonomous.shared_types import Task, TaskType
        qa = QueuePersistence(instance_id=f"instances_a_{N}")
        qb = QueuePersistence(instance_id=f"instances_b_{N}")
        qc = QueuePersistence(instance_id=f"instances_c_{N}")
        written["instances"] += [qa.instance_id, qb.instance_id, qc.instance_id]
        job = Task(id=f"instances_job_{N}", type=TaskType.ANALYSIS, description="instances probe job")
        written["tasks"].append(job.id)
        await qa.heartbeat()
        await qa.upsert(task=job, status="in_progress", priority=2)
        await qb.heartbeat()
        claimed = await qb.claim_restorable(120.0)
        check("a living instance's running job is not claimed by another",
              job.id not in [c["task"].id for c in claimed], f"B claimed {[c['task'].id for c in claimed]}")
        await qa.release()                                              # A stops
        claimed = await qb.claim_restorable(120.0)
        check("once its instance has stopped, the job is claimed",
              [c["task"].id for c in claimed] == [job.id], f"B claimed {[c['task'].id for c in claimed]}")
        loose = Task(id=f"instances_loose_{N}", type=TaskType.ANALYSIS, description="ownerless probe job")
        written["tasks"].append(loose.id)
        await qa.upsert(task=loose, status="pending", priority=2)       # owner A, which is stopped
        await qc.heartbeat()
        got_b, got_c = await asyncio.gather(qb.claim_restorable(120.0), qc.claim_restorable(120.0))
        takers = [n for n, got in (("B", got_b), ("C", got_c)) if loose.id in [c["task"].id for c in got]]
        check("two instances racing for one job: exactly one gets it", len(takers) == 1,
              f"taken by {takers}")
    finally:
        for bid in written["beliefs"]:
            await d.execute_query("DELETE FROM unified.beliefs WHERE belief_id = $1", (bid,))
        for sid in written["strategies"]:
            await d.execute_query("DELETE FROM meta_learning_strategies WHERE strategy_id = $1", (sid,))
        for uid in written["unknowns"]:
            await d.execute_query("DELETE FROM unified.known_unknowns WHERE unknown_id = $1", (uid,))
        for tid in written["tasks"]:
            await d.execute_query("DELETE FROM unified.task_queue WHERE task_id = $1", (tid,))
        for iid in written["instances"]:
            await d.execute_query("DELETE FROM unified.queue_instances WHERE instance_id = $1", (iid,))
        left = await d.execute_query(
            "SELECT (SELECT count(*) FROM unified.beliefs WHERE belief_id = ANY($1::text[])) + "
            "(SELECT count(*) FROM unified.known_unknowns WHERE unknown_id = ANY($2::text[])) + "
            "(SELECT count(*) FROM unified.task_queue WHERE task_id = ANY($3::text[])) + "
            "(SELECT count(*) FROM unified.queue_instances WHERE instance_id = ANY($4::text[])) AS n",
            (written["beliefs"], written["unknowns"], written["tasks"], written["instances"]),
            fetch_one=True)
        check("everything this run wrote is removed", int(left["n"]) == 0, f"left={left['n']}")

    await EV.verify_database()
    passed = sum(1 for r in results if r)
    print(f"\n==== INSTANCES-01: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
