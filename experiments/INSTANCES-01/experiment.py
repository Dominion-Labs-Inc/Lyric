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
  E  one queue:      an instance with room takes a job a living instance queued and has
                     not started; the one that queued it does not run it, and its stale
                     copy does not overwrite the row; a capped person's job is not taken;
                     two instances racing for one waiting job -> exactly one gets it; two
                     queue authorities: the one with nothing of its own draws it, and its
                     result is read where it was queued (added 2026-10-23)
  F  workers:        a worker's word reaches the Lyric it works for through the store (`SELF_CHANNEL`), and a
                     message a worker owes a person is said by the Lyric their front end listens to (2026-10-23)

Everything written is removed by id.

Run: ./venv_lyric/bin/python3 experiments/INSTANCES-01/experiment.py
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
                                                     KnowledgeState, evidence_step, probability_of)
    d = get_database_manager()
    await d.initialize()
    written = {"beliefs": [], "strategies": [], "unknowns": [], "tasks": [], "instances": [], "messages": []}
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
        after_a = A.beliefs[belief.belief_id].log_odds
        await A.flush_belief(belief.belief_id)
        B.update_belief(belief.belief_id, {"source": "instance B", "quality": 0.8}, True)
        b_weight = B.beliefs[belief.belief_id].unsaved_evidence[-1][2]  # as B applied it
        await B.flush_belief(belief.belief_id)                          # B's copy is stale
        row = await d.execute_query(
            "SELECT posterior_probability, update_count FROM unified.beliefs "
            "WHERE belief_id = $1", (belief.belief_id,), fetch_one=True)
        from core.agents.memory_agent import memory_agent
        stored_for, _ = await memory_agent().belief_evidence(belief.belief_id)
        sources = [e.get("source") for e in stored_for]
        check("both instances' evidence is in the stored belief",
              "instance A" in sources and "instance B" in sources and row["update_count"] == 2,
              f"evidence={sources} update_count={row['update_count']}")
        expected = probability_of(after_a + evidence_step(b_weight, True))
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
        await qa.upsert(task=job, status="in_progress", priority=2, lease_s=120.0)
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
        await qa.upsert(task=loose, status="pending", priority=2, lease_s=120.0)  # owner A, which is stopped
        await qc.heartbeat()
        got_b, got_c = await asyncio.gather(qb.claim_restorable(120.0), qc.claim_restorable(120.0))
        takers = [n for n, got in (("B", got_b), ("C", got_c)) if loose.id in [c["task"].id for c in got]]
        check("two instances racing for one job: exactly one gets it", len(takers) == 1,
              f"taken by {takers}")

        print("\n== E. One queue: an instance with room takes what another queued ==")
        # `claim_waiting` takes the highest-priority waiting job in the whole table, so E runs only
        # when the live table holds no waiting work of its own.
        others = await d.execute_query(
            "SELECT count(*) AS n FROM unified.task_queue WHERE status = ANY($1::text[])"
            " AND NOT task_id = ANY($2::text[])",
            (list(QueuePersistence.WAITING_STATUSES), written["tasks"]), fetch_one=True)
        if int(others["n"]):
            check("the live table holds no waiting work for E to take", False, f"{others['n']} waiting")
        else:
            qd, qe, qf = (QueuePersistence(instance_id=f"instances_{x}_{N}") for x in "def")
            written["instances"] += [qd.instance_id, qe.instance_id, qf.instance_id]
            for q in (qd, qe, qf):
                await q.heartbeat()
            waiting = Task(id=f"instances_waiting_{N}", type=TaskType.ANALYSIS, description="waiting probe job")
            written["tasks"].append(waiting.id)
            await qd.claim_new(task=waiting, status="pending", priority=1000, lease_s=120.0)
            taken = await qe.claim_waiting()
            check("an instance with room takes a job a living instance queued and has not started",
                  taken is not None and taken["task"].id == waiting.id,
                  f"E took {taken['task'].id if taken else None}")
            started = await qd.claim_start(task=waiting, priority=1000, lease_s=120.0)
            check("the instance that queued it does not start it", not started, f"started={started}")
            stale = await qd.upsert(task=waiting, status="pending", priority=1000, lease_s=120.0)
            row = await d.execute_query("SELECT status, owner FROM unified.task_queue WHERE task_id = $1",
                                        (waiting.id,), fetch_one=True)
            check("its stale copy does not overwrite the running job's row",
                  not stale and row["owner"] == qe.instance_id and row["status"] == "in_progress",
                  f"written={stale} row={dict(row)}")
            own = Task(id=f"instances_own_{N}", type=TaskType.ANALYSIS, description="own probe job")
            written["tasks"].append(own.id)
            await qd.claim_new(task=own, status="pending", priority=1000, lease_s=120.0)
            check("an instance starts its own waiting job",
                  await qd.claim_start(task=own, priority=1000, lease_s=120.0))
            theirs = Task(id=f"instances_theirs_{N}", type=TaskType.ANALYSIS, description="a person's probe job",
                          actor=f"instances_person_{N}")
            written["tasks"].append(theirs.id)
            await qd.claim_new(task=theirs, status="pending", priority=1000, lease_s=120.0)
            skipped = await qe.claim_waiting(skip_actors=(theirs.actor,))
            check("a job of a person at their cap is not taken",
                  skipped is None or skipped["task"].id != theirs.id,
                  f"took {skipped['task'].id if skipped else None}")
            got_e, got_f = await asyncio.gather(qe.claim_waiting(), qf.claim_waiting())
            takers = [n for n, got in (("E", got_e), ("F", got_f)) if got and got["task"].id == theirs.id]
            check("two instances racing for one waiting job: exactly one gets it", len(takers) == 1,
                  f"taken by {takers}")

            from core.agents.autonomous.queue_authority import QueueAuthority
            from core.agents.autonomous.shared_types import Priority
            first, second = QueueAuthority(), QueueAuthority()
            first._persistence = QueuePersistence(instance_id=f"instances_g_{N}")
            second._persistence = QueuePersistence(instance_id=f"instances_h_{N}")
            written["instances"] += [first._persistence.instance_id, second._persistence.instance_id]
            for authority in (first, second):
                await authority.heartbeat()
            work = Task(id=f"instances_work_{N}", type=TaskType.ANALYSIS, description="work probe job")
            written["tasks"].append(work.id)
            await first.add_task(work, Priority.HIGH)
            drawn = await second.get_next_task(timeout=0)
            check("a queue authority with nothing of its own draws the job another queued",
                  drawn is not None and drawn.task.id == work.id,
                  f"drew {drawn.task.id if drawn else None}")
            again = await first.get_next_task(timeout=0)
            check("the authority that queued it lets it go and draws nothing",
                  again is None and work.id not in first.tasks_by_id,
                  f"drew {again.task.id if again else None}; still held: {work.id in first.tasks_by_id}")
            await second.mark_completed(work.id, {"done": True})
            read = await first.result_for(work.id, actor=work.actor)
            check("its result is read from the store where it was queued",
                  read.get("status") == "completed" and read.get("result") == {"done": True}, f"{read}")

        print("\n== F. Workers: the self hears what a worker tells it ==")
        from collections import deque
        from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator, SELF_CHANNEL
        from core.agents.autonomous.outbox import get_outbox

        def bare(worker):
            c = AutonomousCoordinator.__new__(AutonomousCoordinator)
            c._reactions, c._reactive_queue, c._work_ready = {}, deque(), asyncio.Event()
            c._emit_depth, c._max_emit_depth, c.active, c._stopping = 0, 8, True, False
            c.worker, c._listeners, c._last_session_of, c.outbox = worker, {}, {}, get_outbox()
            return c
        worker, lyric = bare(True), bare(False)
        heard = []

        async def until(condition):
            for _ in range(50):
                if condition():
                    return True
                await asyncio.sleep(0.1)
            return condition()
        async with d.listen(SELF_CHANNEL, heard.append, store="runtime"):
            await worker._tell_the_self(f"event:competence_changed")
            got = await until(lambda: heard)
        check("a worker's word reaches the Lyric it works for through the store",
              got and heard == ["event:competence_changed"], f"heard {heard}")

        person = f"instances_person_{N}"
        said_to = []
        lyric.on_message(person, said_to.append)
        # A front end that starts listening is handed what already waits for its person (`on_message`): let that
        # finish first, so what is checked is the worker's message reaching it through the self.
        await asyncio.sleep(0.5)

        class Conversation:
            async def note_said(self, text, **kept):
                said_to.append(("noted", text))
        lyric.conversation = lambda session, actor_identity=None: Conversation()
        owed = await worker.speak_to(person, f"The probe job {N} is done.", why="work ended", about="probe")
        written["messages"].append(owed["message_id"])
        undelivered = (await get_outbox().get(owed["message_id"])).get("delivered_at") is None
        lyric._heard_from_a_worker(f"said:{owed['message_id']}")
        got = await until(lambda: any(isinstance(m, dict) for m in said_to))
        delivered = await get_outbox().get(owed["message_id"])
        check("a message a worker owes is said by the Lyric the person's front end listens to",
              undelivered and got and delivered.get("delivered_by") == "push"
              and ("noted", f"The probe job {N} is done.") in said_to,
              f"undelivered before={undelivered} said={said_to} delivered_by={delivered.get('delivered_by')}")
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
        for mid in written["messages"]:
            await d.execute_query("DELETE FROM unified.outbox WHERE message_id = $1", (mid,))
        left = await d.execute_query(
            "SELECT (SELECT count(*) FROM unified.beliefs WHERE belief_id = ANY($1::text[])) + "
            "(SELECT count(*) FROM unified.known_unknowns WHERE unknown_id = ANY($2::text[])) + "
            "(SELECT count(*) FROM unified.task_queue WHERE task_id = ANY($3::text[])) + "
            "(SELECT count(*) FROM unified.queue_instances WHERE instance_id = ANY($4::text[])) + "
            "(SELECT count(*) FROM unified.outbox WHERE message_id = ANY($5::text[])) AS n",
            (written["beliefs"], written["unknowns"], written["tasks"], written["instances"], written["messages"]),
            fetch_one=True)
        check("everything this run wrote is removed", int(left["n"]) == 0, f"left={left['n']}")

    await EV.verify_database()
    passed = sum(1 for r in results if r)
    print(f"\n==== INSTANCES-01: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
