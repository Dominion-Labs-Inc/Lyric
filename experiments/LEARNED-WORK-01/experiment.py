#!/usr/bin/env python3
"""LEARNED-WORK-01 — teach something new, then watch how the substrate behaves on it.

The substrate is built on confidence earned from what it has met: taught, seen or done.
So it should be able to say what it knows and what it does not, what it can do and what
it cannot, and it should be different after it has tried. This teaches a lesson it does
not already hold (pipeline corrosion and cathodic protection), then watches:

  A  TEACH       eight facts and one rule, through `TeachingPass` (the one teaching path);
                 what it now believes, and how strongly
  B  KNOWS       questions answered from the lesson, one that chains through it, one the
                 lesson contradicts, and one it was never taught
  C  CAN DO      asked, before trying, whether it can do two tasks
  D  DOES        a research-and-report goal in plain words through the front door, the same
                 goal through the planning engine, and an inspection report to judge
  E  AFTER       its confidence after the work, the same "can you" asked again, and the
                 same goal a second time

This OBSERVES. Almost nothing is scored: the point is to see what the substrate does,
step by step, and a transcript of every request, reply, step, tool run and belief is
written beside the run record. Nothing is fixed during it.

The lesson and what the substrate learns are KEPT (the store is to be wiped and
re-taught); scratch files are removed after their contents are copied into the
transcript. The fixture user's context is kept too, under `USER`, so it can be inspected.

Run: ./venv_torin/bin/python3 experiments/LEARNED-WORK-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import random
import shutil
import string
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

N = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
USER = f"learned-work-{N}"
DOMAIN = "corrosion_protection"
EV = RunRecord(
    "LEARNED-WORK-01",
    claim=("After a lesson it did not already hold, the substrate knows what it was taught and "
           "says so, says what it was not taught, can say what it can and cannot do, does "
           "multi-step work built on the lesson, and is different after it has tried."),
    hypothesis=("Confidence that does not follow what was taught, a gap answered as if known, a "
                "task it cannot do claimed as doable (or the reverse), work that ignores the "
                "lesson, or confidence that does not move after doing would each show here."))
results = []
TRANSCRIPT = []


def say(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def observe(name, detail):
    EV.note(f"OBSERVED — {name}: {detail}")
    say(f"  [OBSERVED] {name} — {detail}")


# ── the lesson ───────────────────────────────────────────────────────────────

LESSON = [
    ("cathodic protection", "isa", "corrosion control method",
     "Cathodic protection is a corrosion control method."),
    ("cathodic protection", "prevents", "corrosion", "Cathodic protection prevents corrosion."),
    ("sacrificial anode", "isa", "anode", "A sacrificial anode is an anode."),
    ("sacrificial anode", "part_of", "cathodic protection system",
     "A sacrificial anode is part of a cathodic protection system."),
    ("sacrificial anode", "made_of", "zinc", "A sacrificial anode is made of zinc."),
    ("moisture", "causes", "corrosion", "Moisture causes corrosion."),
    ("corrosion", "causes", "pipeline failure", "Corrosion causes pipeline failure."),
    ("coating", "prevents", "corrosion", "A coating prevents corrosion."),
]
RULE = ({"subject": "sacrificial anode", "relation": "is", "obj": "depleted"},
        {"subject": "pipeline", "relation": "is", "obj": "unprotected"},
        "if the sacrificial anode is depleted then the pipeline is unprotected")


class Lesson:
    """A hand-written source: it states its sentences and the classes of its words."""
    name = "LEARNED-WORK-01 lesson"
    curated = True

    def provenance(self):
        from core.learning.teaching_sources import _provenance
        return _provenance("teaching", "LEARNED-WORK-01")

    def records(self):
        from core.learning.teaching import TaughtRecord
        for subject, relation, obj, sentence in LESSON:
            yield TaughtRecord(subject=subject, relation=relation, obj=obj, quality=0.95,
                               word_classes=((subject, "NOUN"), (obj, "NOUN")),
                               sentence=sentence)


# ── reading the substrate ────────────────────────────────────────────────────

STORES = {
    "memories": "SELECT count(*) AS n FROM memory_hot.memory_hot",
    "concepts": "SELECT count(*) AS n FROM unified.concepts",
    "graph_edges": "SELECT count(*) AS n FROM unified.concept_relations",
    "beliefs": "SELECT count(*) AS n FROM unified.beliefs",
    "knowledge_updates": "SELECT count(*) AS n FROM unified.knowledge_updates",
    "held_rules": "SELECT count(*) AS n FROM unified.held_conditionals",
    "tool_runs": "SELECT count(*) AS n FROM tool_usage_history",
    "demonstrations": "SELECT count(*) AS n FROM unified.operator_demonstrations",
    "learned_rules": "SELECT count(*) AS n FROM unified.learned_rules",
    "known_unknowns": "SELECT count(*) AS n FROM unified.known_unknowns",
}


async def measure(d):
    out = {}
    for name, sql in STORES.items():
        row = await d.execute_query(sql, (), fetch_one=True)
        out[name] = int(row["n"])
    return out


def claim_beliefs():
    """How strongly each taught fact is believed now: (posterior, updates) or None."""
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    unc = get_uncertainty_system()
    out = {}
    for subject, relation, obj, _ in LESSON:
        claim = f"{subject} {relation} {obj}"
        belief = unc.belief_for_claim(claim)
        out[claim] = (None if belief is None else
                      (round(float(belief.posterior_probability), 3), int(belief.update_count)))
    return out


async def confidence(udm):
    """The substrate's own reading of itself in the taught domain."""
    competence = udm.competence_belief(DOMAIN)
    reliability = await udm.operating_reliability(DOMAIN)
    return {"competence": (None if competence is None else
                           round(float(competence.posterior_probability), 3)),
            "operating": {k: reliability.get(k) for k in ("attempts", "wins", "earned")}}


async def tools_since(d, t0):
    rows = await d.execute_query(
        "SELECT tool_names_used, success FROM tool_usage_history "
        "WHERE started_at >= to_timestamp($1) ORDER BY started_at", (t0,), fetch_all=True) or []
    grouped = {}
    for r in rows:
        name = str(r["tool_names_used"])
        runs, ok = grouped.get(name, (0, 0))
        grouped[name] = (runs + 1, ok + (1 if r["success"] else 0))
    return grouped


async def learned_since(d, t0):
    """Graph edges written since t0, with where each came from (tool observations aside)."""
    rows = await d.execute_query(
        "SELECT c.name AS s, cr.relation AS r, t.name AS o, e.source_type AS st, e.source_id AS sid "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
        "JOIN unified.concepts t ON t.concept_id = cr.target_concept_id "
        "LEFT JOIN unified.evidence_envelopes e ON e.evidence_id = cr.evidence_id "
        "WHERE cr.created_at >= to_timestamp($1) ORDER BY cr.created_at", (t0,), fetch_all=True) or []
    return [(r["s"], r["r"], r["o"], r["st"], str(r["sid"] or "")[:70]) for r in rows
            if r["st"] not in ("tool_observation", "imported_knowledge")]


def said(outcome) -> str:
    """What came back, as text, whichever shape it has."""
    if not isinstance(outcome, dict):
        return str(outcome)
    for key in ("answer", "result", "error", "status"):
        if outcome.get(key):
            value = outcome[key]
            return value if isinstance(value, str) else repr(value)[:600]
    return repr(outcome)[:600]


async def job(coord, message, *, metadata=None, wait_s=300):
    """Submit through the ONE front door, as a person, and wait for the outcome."""
    meta = {"actor_identity": USER, "session_id": USER, **(metadata or {})}
    ack = await coord.handle_user_request(message, source="api", metadata=meta)
    if not ack.get("task_id") or ack.get("kind") in ("question", "telling"):
        return ack
    deadline = time.time() + wait_s
    while time.time() < deadline:
        result = await coord.get_task_result(ack["task_id"], actor=USER)
        if result.get("status") in ("completed", "failed", "not_found"):
            return {**result, "task_id": ack["task_id"]}
        await asyncio.sleep(2)
    return {"status": "still_running", "task_id": ack["task_id"]}


async def ask(coord, message, **kw):
    """One request and its reply, written into the transcript."""
    say(f"\n  > {message}")
    outcome = await job(coord, message, **kw)
    route = outcome.get("kind") or ("job" if outcome.get("task_id") else "?")
    say(f"    [{route}{', ' + str(outcome.get('status')) if outcome.get('status') else ''}] "
        f"{said(outcome)[:700]}")
    return outcome


async def planned(coord, description):
    """A goal given to the planning engine, worked to the end the way the live loop does."""
    from core.agents.autonomous.shared_types import Priority, SystemState, TaskStatus
    planning = coord.planning
    goal = await planning.create_goal(description, Priority.HIGH)
    plan = await planning.generate_plan(getattr(goal, "goal_id", None) or getattr(goal, "id", None))
    steps = list(getattr(plan, "tasks", None) or []) if plan else []
    ours = {t.id for t in steps}
    say(f"    plan: {[(t.type.name, t.description[:60]) for t in steps]}")
    done = []
    for _ in range(14):
        ready = [t for t in await planning.get_next_tasks(SystemState()) if t.id in ours]
        if not ready:
            break
        for task in ready:
            outcome = await coord.execute_task(task)
            ok = bool(outcome and outcome.get("success"))
            task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
            done.append((task.type.name, ok))
            say(f"    step {task.type.name:<10} success={ok} method={(outcome or {}).get('method')} "
                f"— {said(outcome)[:400]}")
    return steps, done


# ── the run ──────────────────────────────────────────────────────────────────

async def main() -> int:
    system, coord = await boot()
    d = db()
    work = Path(tempfile.mkdtemp(prefix=f"learned_work_{N}_"))
    EV.metric("user", USER)
    started = time.time()
    try:
        from core.integration.universal_domain_master import get_universal_domain_master
        from core.learning import get_learning_authority
        L = get_learning_authority()
        udm = get_universal_domain_master()
        before = await measure(d)
        observe("before the lesson — the taught facts", f"{claim_beliefs()}")
        observe("before the lesson — confidence in the domain", f"{await confidence(udm)}")

        say("\n== A. Teach: eight facts and one rule, through the one teaching path ==")
        from core.learning.teaching import TeachingPass
        report = await TeachingPass(Lesson(), domain=DOMAIN, sample=False).run(L)
        for line in report.lines():
            say(f"    {line}")
        taught = dict(report.taught)
        check("the lesson is read and held", report.read == len(LESSON)
              and taught.get("admitted", 0) + taught.get("already", 0) == len(LESSON),
              f"read={report.read} taught={taught}")
        rule = await L.learn_rule(RULE[0], RULE[1], surface=RULE[2], domain=DOMAIN)
        check("the rule is held", bool(getattr(rule, "admitted", False)
                                       or getattr(rule, "already_present", False)),
              f"{getattr(rule, 'refusals', None)}")
        after_teach = await measure(d)
        observe("stores moved by the lesson",
                f"{ {k: after_teach[k] - before[k] for k in before if after_teach[k] != before[k]} }")
        observe("after the lesson — the taught facts (posterior, updates)", f"{claim_beliefs()}")
        observe("after the lesson — confidence in the domain", f"{await confidence(udm)}")

        say("\n== B. What it knows, and what it does not ==")
        await ask(coord, "Is a sacrificial anode part of a cathodic protection system?")
        await ask(coord, "What is a sacrificial anode made of?")
        await ask(coord, "Does moisture cause pipeline failure?")
        await ask(coord, "Does a coating cause corrosion?")
        await ask(coord, "What prevents corrosion?")
        await ask(coord, "What is an impressed current system?")

        say("\n== C. What it can do — asked before it tries ==")
        await ask(coord, "Can you write a report about cathodic protection?")
        await ask(coord, "Can you inspect a pipeline?")
        before_work = await confidence(udm)
        observe("before the work — confidence in the domain", f"{before_work}")

        say("\n== D. The work ==")
        say("\n-- D1. A research-and-report goal, in plain words, through the front door --")
        plain_path = work / "report_plain.md"
        t_d1 = time.time()
        await ask(coord, f"Research how cathodic protection protects pipelines from corrosion, and "
                         f"write a report at {plain_path} that connects what you find to what you "
                         f"already know.")
        observe("D1 tool runs", f"{await tools_since(d, t_d1)}")
        observe("D1 learned", f"{await learned_since(d, t_d1)}")
        observe("D1 file", plain_path.read_text()[:1500] if plain_path.exists() else "not written")

        say("\n-- D2. The same goal, given to the planning engine --")
        plan_path = work / "report_planned.md"
        t_d2 = time.time()
        steps, done = await planned(
            coord, f"Research how cathodic protection protects pipelines from corrosion, and write a "
                   f"report at {plan_path} that connects what you find to what you already know.")
        observe("D2 steps as run", f"{done}")
        observe("D2 tool runs", f"{await tools_since(d, t_d2)}")
        observe("D2 learned", f"{await learned_since(d, t_d2)}")
        body = plan_path.read_text() if plan_path.exists() else ""
        observe("D2 file", body[:2000] if body else "not written")
        used = [s for s, _r, o, _ in LESSON if s in body.lower() or o in body.lower()]
        observe("D2 file — lesson terms it uses", f"{sorted(set(used))}")

        say("\n-- D3. An inspection report to judge --")
        inspection = work / "inspection_segment_14.txt"
        inspection.write_text("Pipeline segment 14 inspection report.\n"
                              "The sacrificial anode is depleted.\n"
                              "The coating is damaged near valve V-3.\n"
                              "The soil around the pipe is wet.\n")
        await ask(coord, f"Read the inspection report at {inspection} and tell me what risks it shows.")
        await ask(coord, "Read the inspection report.",
                  metadata={"parameters": {"tool_plan": [{"tool": "read_file",
                                                          "args": {"file_path": str(inspection)}}]}})
        await ask(coord, "The sacrificial anode is depleted.")
        await ask(coord, "Is the pipeline unprotected?")
        await ask(coord, "Is the pipeline at risk of failure?")

        say("\n== E. After the work ==")
        after_work = await confidence(udm)
        observe("confidence in the domain: before the work -> after", f"{before_work} -> {after_work}")
        observe("the taught facts after the work (posterior, updates)", f"{claim_beliefs()}")
        await ask(coord, "Can you write a report about cathodic protection?")
        say("\n-- E2. The same planned goal a second time --")
        again_path = work / "report_again.md"
        t_e2 = time.time()
        steps2, done2 = await planned(
            coord, f"Research how cathodic protection protects pipelines from corrosion, and write a "
                   f"report at {again_path} that connects what you find to what you already know.")
        observe("second attempt: steps as run", f"{done2} (first: {done})")
        observe("second attempt: tool runs", f"{await tools_since(d, t_e2)}")
        body2 = again_path.read_text() if again_path.exists() else ""
        observe("second attempt: file", body2[:2000] if body2 else "not written")
        observe("confidence in the domain after the second attempt", f"{await confidence(udm)}")

        say("\n== F. What moved, over the whole run ==")
        after = await measure(d)
        observe("stores moved", f"{ {k: after[k] - before[k] for k in before if after[k] != before[k]} }")
        ledger = await d.execute_query(
            "SELECT cause, disposition, count(*) AS n FROM unified.knowledge_updates "
            "WHERE occurred_at >= to_timestamp($1) GROUP BY 1, 2 ORDER BY 3 DESC", (started,),
            fetch_all=True) or []
        observe("knowledge ledger by cause", f"{[(r['cause'], r['disposition'], r['n']) for r in ledger]}")
        observe("tool runs (runs, successes)", f"{await tools_since(d, started)}")
        unknowns = await d.execute_query(
            "SELECT question FROM unified.known_unknowns WHERE discovered_at >= to_timestamp($1)",
            (started,), fetch_all=True) or []
        observe("open questions it registered", f"{[r['question'] for r in unknowns]}")
        scoped = await d.execute_query(
            "SELECT subj, rel, obj FROM unified.scoped_concept_relations WHERE scope_actor = $1",
            (USER,), fetch_all=True) or []
        observe("this person's own context", f"{[(r['subj'], r['rel'], r['obj']) for r in scoped]}")
    finally:
        try:
            for path in sorted(work.glob("*")):
                TRANSCRIPT.append(f"\n--- scratch file {path.name} ---\n{path.read_text()[:4000]}")
            shutil.rmtree(work, ignore_errors=True)
        finally:
            await shutdown(system)

    await EV.verify_database()
    passed = sum(1 for r in results if r)
    say(f"\n==== LEARNED-WORK-01: {passed}/{len(results)} checks passed "
        f"(the run is observations; see the transcript) ====")
    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# LEARNED-WORK-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    print(f"  transcript: {transcript}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
