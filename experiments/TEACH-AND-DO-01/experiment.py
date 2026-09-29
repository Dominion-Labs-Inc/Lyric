#!/usr/bin/env python3
"""TEACH-AND-DO-01 — a very small teaching pass, then real work on what was taught.

Before the store is wiped and the main model is taught on corrected data, this checks the
system operates as one: a small lesson goes in through THE teaching path, and then the
substrate is asked to use it — answering from it, looking up what it lacks on the web,
reading a document, running code, and writing down what it knows — while every store the
learning should touch is measured before and after.

  A  TEACH       six facts and one conditional, through `TeachingPass` (the one path)
  B  ASK BACK    a question that chains through what was taught
  C  WEB         a question about something NOT taught: look it up, learn it, answer
  D  DOCUMENTS   a real note on disk — asked in plain words, and with `read_file` declared;
                 then a planned goal: write down what it knows, at a path
  E  CODE        a computation — asked in plain words, and with `run_python` declared
  F  LEARNING    which stores moved: memory, concept graph, beliefs, the knowledge ledger,
                 held rules, tool metrics, demonstrations, a user's scoped context

Plain-words requests are OBSERVED, not scored: how the model-free substrate handles free
text is what this finds out. The taught lesson is KEPT (the store is to be wiped and
re-taught); scratch files are removed.

Run: ./venv_torin/bin/python3 experiments/TEACH-AND-DO-01/experiment.py
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
USER = f"teach-and-do-{N}"
DOMAIN = "maintenance"
EV = RunRecord(
    "TEACH-AND-DO-01",
    claim=("A small lesson taught through the one teaching path is held in the substrate's "
           "memory and used: asked back, extended from the web, applied to a document, and "
           "written down — and every learning path the work should touch moves."),
    hypothesis=("A taught fact that cannot be asked back, a gap never looked up, a declared "
                "tool that does not run, a planned artefact never written, or a learning store "
                "that never moves would each show here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def observe(name, detail):
    EV.note(f"OBSERVED — {name}: {detail}")
    print(f"  [OBSERVED] {name} — {detail}")


# ── the lesson ───────────────────────────────────────────────────────────────

LESSON = [
    ("centrifugal pump", "isa", "pump", "A centrifugal pump is a pump."),
    ("pump", "isa", "machine", "A pump is a machine."),
    ("impeller", "part_of", "centrifugal pump", "An impeller is part of a centrifugal pump."),
    ("pump", "used_for", "moving water", "A pump is used for moving water."),
    ("cavitation", "causes", "impeller damage", "Cavitation causes impeller damage."),
    ("water", "isa", "liquid", "Water is a liquid."),
]


class Lesson:
    """A hand-written source: it states its sentences and the classes of its words."""
    name = "TEACH-AND-DO-01 lesson"
    curated = True

    def provenance(self):
        from core.learning.teaching_sources import _provenance
        return _provenance("teaching", "TEACH-AND-DO-01")

    def records(self):
        from core.learning.teaching import TaughtRecord
        for subject, relation, obj, sentence in LESSON:
            yield TaughtRecord(subject=subject, relation=relation, obj=obj, quality=0.95,
                               word_classes=((subject, "NOUN"), (obj, "NOUN")),
                               sentence=sentence)


# ── measuring the stores ─────────────────────────────────────────────────────

STORES = {
    "memories": "SELECT count(*) AS n FROM memory_hot.memory_hot",
    "concepts": "SELECT count(*) AS n FROM unified.concepts",
    "graph_edges": "SELECT count(*) AS n FROM unified.concept_relations",
    "beliefs": "SELECT count(*) AS n FROM unified.beliefs",
    "knowledge_updates": "SELECT count(*) AS n FROM unified.knowledge_updates",
    "held_rules": "SELECT count(*) AS n FROM unified.held_conditionals",
    "tool_runs": "SELECT count(*) AS n FROM tool_usage_history",
    "demonstrations": "SELECT count(*) AS n FROM unified.operator_demonstrations",
}


async def measure(d):
    out = {}
    for name, sql in STORES.items():
        row = await d.execute_query(sql, (), fetch_one=True)
        out[name] = int(row["n"])
    return out


LOOKED_UP = "peristaltic_pump"


async def forget_look_up(d, name):
    """Remove what a look-up of `name` put in the shared mind, so each run meets the gap
    fresh and leaves nothing behind. Only what rests on RESEARCH evidence goes: the edges
    that finding asserted, their envelopes, the memories it wrote and the beliefs about
    them, and a concept only when every piece of evidence it rests on is that finding."""
    from core.semantics.cognitive_ingress import normalize_term
    rows = await d.execute_query(
        "SELECT cr.evidence_id, cr.source_concept_id, cr.target_concept_id "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
        "JOIN unified.evidence_envelopes e ON e.evidence_id = cr.evidence_id "
        "WHERE c.name = $1 AND e.source_type = 'research_finding'", (name,), fetch_all=True) or []
    ev = sorted({r["evidence_id"] for r in rows})
    touched = sorted({r["source_concept_id"] for r in rows} | {r["target_concept_id"] for r in rows})
    only = await d.execute_query(
        "SELECT concept_id FROM unified.concept_evidence WHERE concept_id = ANY($1::text[]) "
        "GROUP BY concept_id HAVING bool_and(evidence_id = ANY($2::text[]))",
        (touched, ev), fetch_all=True) or [] if ev else []
    gone = [r["concept_id"] for r in only]
    memories = [r["memory_id"] for r in (await d.execute_query(
        "SELECT memory_id, metadata->>'reading' AS reading FROM memory_hot.memory_hot "
        "WHERE metadata->>'source_type' = 'RESEARCH_FINDING'", (), fetch_all=True) or [])
        if normalize_term(str(r["reading"] or "").split("|")[0]) == name]
    for sql, args in (
            ("DELETE FROM unified.beliefs WHERE memory_id = ANY($1::text[])", (memories,)),
            ("DELETE FROM memory_hot.memory_hot WHERE memory_id = ANY($1::text[])", (memories,)),
            ("DELETE FROM unified.concept_relations WHERE evidence_id = ANY($1::text[]) "
             "OR source_concept_id = ANY($2::text[]) OR target_concept_id = ANY($2::text[])", (ev, gone)),
            ("DELETE FROM unified.concept_evidence WHERE evidence_id = ANY($1::text[]) "
             "OR concept_id = ANY($2::text[])", (ev, gone)),
            ("DELETE FROM unified.concept_domains WHERE evidence_id = ANY($1::text[]) "
             "OR concept_id = ANY($2::text[])", (ev, gone)),
            ("DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1::text[])", (gone,)),
            ("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])", (gone,)),
            ("DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])", (ev,))):
        await d.execute_query(sql, args, commit=True)
    return {"evidence": ev, "concepts": gone, "memories": memories}


async def job(coord, message, *, metadata=None, wait_s=240):
    """Submit through the ONE front door, as a user, and wait for the outcome."""
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


def said(outcome) -> str:
    """What came back, as text, whichever shape it has."""
    if not isinstance(outcome, dict):
        return str(outcome)
    for key in ("answer", "result", "error", "status"):
        if outcome.get(key):
            value = outcome[key]
            return value if isinstance(value, str) else repr(value)[:400]
    return repr(outcome)[:400]


async def main() -> int:
    system, coord = await boot()
    d = db()
    work = Path(tempfile.mkdtemp(prefix=f"teach_and_do_{N}_"))
    EV.metric("user", USER)
    started = time.time()
    try:
        from core.learning import get_learning_authority
        L = get_learning_authority()
        before = await measure(d)
        unannounced_before = L.system_metrics.get("admissions_unannounced", 0)

        print("\n== A. Teach: six facts and one conditional, through the one teaching path ==")
        from core.learning.teaching import TeachingPass
        report = await TeachingPass(Lesson(), domain=DOMAIN, sample=False).run(L)
        for line in report.lines():
            print(f"    {line}")
        taught = dict(report.taught)
        check("the lesson is read and taught", report.read == len(LESSON)
              and taught.get("admitted", 0) + taught.get("already", 0) == len(LESSON),
              f"read={report.read} taught={taught}")
        rule = await L.learn_rule(
            {"subject": "valve", "relation": "is", "obj": "closed"},
            {"subject": "pump", "relation": "is", "obj": "overheating"},
            surface="if the valve is closed then the pump is overheating", domain=DOMAIN)
        check("the conditional is held", bool(getattr(rule, "admitted", False)),
              f"{getattr(rule, 'refusals', None)}")
        after_teach = await measure(d)
        # THE LESSON IS KEPT BETWEEN RUNS, so a run either teaches it for the first
        # time or re-teaches what is held -- and each has its own correct result.
        # A first teach must write the substrate's memory; a re-teach must write
        # NOTHING new (one source saying the same thing twice is one fact, not a
        # second witness) and say so in the ledger.
        if taught.get("already", 0) == len(LESSON):
            for store in ("graph_edges", "beliefs"):
                check(f"re-teaching the held lesson moved nothing: {store}",
                      after_teach[store] == before[store], f"{before[store]} -> {after_teach[store]}")
            unchanged = await d.execute_query(
                "SELECT count(*) AS n FROM unified.knowledge_updates WHERE occurred_at >= to_timestamp($1) "
                "AND cause = 'learning.bulk_teach.teaching' AND disposition = 'unchanged'",
                (started,), fetch_one=True)
            check("and the ledger records it as unchanged, not new", int(unchanged["n"]) == len(LESSON),
                  f"{unchanged['n']} unchanged")
            check("the conditional was already held, and is not held twice",
                  getattr(rule, "already_present", False)
                  and after_teach["held_rules"] == before["held_rules"],
                  f"{before['held_rules']} -> {after_teach['held_rules']}")
        else:
            for store in ("memories", "graph_edges", "beliefs", "knowledge_updates"):
                check(f"teaching wrote the substrate's memory: {store}",
                      after_teach[store] > before[store], f"{before[store]} -> {after_teach[store]}")
            check("teaching held the conditional as a rule",
                  after_teach["held_rules"] > before["held_rules"] or getattr(rule, "already_present", False),
                  f"{before['held_rules']} -> {after_teach['held_rules']}")
        check("every admission was announced to the substrate",
              L.system_metrics.get("admissions_unannounced", 0) == unannounced_before,
              f"unannounced {unannounced_before} -> {L.system_metrics.get('admissions_unannounced', 0)}")

        print("\n== B. Ask back: a question that chains through what was taught ==")
        asked = await job(coord, "Is a centrifugal pump a machine?")
        print(f"    reply: {said(asked)[:200]!r}")
        check("a chain through taught facts is affirmed (centrifugal pump -> pump -> machine)",
              said(asked).lower().startswith("yes"), said(asked)[:160])

        print("\n== C. Web: a question about something not taught ==")
        stale = await forget_look_up(d, LOOKED_UP)
        if stale["evidence"] or stale["memories"]:
            observe("an earlier run's look-up removed first", f"{stale}")
        runs_before_web = (await measure(d))["tool_runs"]
        web = await job(coord, "What is a peristaltic pump?")
        print(f"    reply: {said(web)[:300]!r}")
        runs_after_web = (await measure(d))["tool_runs"]
        searched = await d.execute_query(
            "SELECT tool_names_used, success FROM tool_usage_history "
            "WHERE started_at >= to_timestamp($1) ORDER BY started_at", (started,), fetch_all=True) or []
        web_tools = [r for r in searched if "web" in str(r["tool_names_used"])]
        check("the gap was looked up on the web", bool(web_tools),
              f"tool runs since start: {[(r['tool_names_used'], r['success']) for r in searched][-6:]}")
        check("and answered", bool(said(web).strip()) and "hold nothing" not in said(web).lower(),
              said(web)[:160])
        # WORLD KNOWLEDGE, NOT THE ASKER'S CONTEXT: the page is the source, so the finding
        # is the substrate's, in the shared graph with the page as its evidence.
        world = await d.execute_query(
            "SELECT c.name AS subj, cr.relation AS rel, t.name AS obj, e.source_id "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON c.concept_id = cr.source_concept_id "
            "JOIN unified.concepts t ON t.concept_id = cr.target_concept_id "
            "JOIN unified.evidence_envelopes e ON e.evidence_id = cr.evidence_id "
            "WHERE c.name = $1 AND e.source_type = 'research_finding'",
            (LOOKED_UP,), fetch_all=True) or []
        check("what was read is world knowledge, sourced to the page it came from",
              any(str(r["source_id"]).startswith("http") for r in world),
              f"{[(r['subj'], r['rel'], r['obj'], r['source_id']) for r in world][:3]}")
        mine = await d.execute_query(
            "SELECT subj, rel, obj FROM unified.scoped_concept_relations "
            "WHERE scope_actor = $1 AND (subj = $2 OR obj = $2)",
            (USER, LOOKED_UP), fetch_all=True) or []
        check("and none of it is filed as the asker's own context", not mine,
              f"{[(r['subj'], r['rel'], r['obj']) for r in mine]} "
              f"(tool runs {runs_before_web} -> {runs_after_web})")

        print("\n== D. Documents ==")
        note = work / "maintenance_note.txt"
        note.write_text("Maintenance note, pump P-7.\n"
                        "P-7 is a centrifugal pump. Its impeller shows pitting consistent with "
                        "cavitation. Recommend inspecting suction pressure.\n")
        plain_doc = await job(coord, f"Read the maintenance note at {note} and tell me what is "
                                     f"wrong with pump P-7.")
        observe("plain words: read a note and say what is wrong", said(plain_doc)[:300])
        declared_doc = await job(
            coord, "Read the maintenance note.",
            metadata={"parameters": {"tool_plan": [{"tool": "read_file",
                                                    "args": {"file_path": str(note)}}]}})
        print(f"    declared read_file: {said(declared_doc)[:200]!r}")
        check("with read_file declared, the note is read", "P-7" in said(declared_doc),
              said(declared_doc)[:160])

        from core.agents.autonomous.shared_types import Priority, SystemState, TaskStatus
        summary = work / "centrifugal_pumps.md"
        planning = coord.planning
        goal = await planning.create_goal(
            f"Create a written summary of what you know about centrifugal pumps at {summary}",
            Priority.HIGH)
        plan = await planning.generate_plan(getattr(goal, "goal_id", None) or getattr(goal, "id", None))
        steps = list(getattr(plan, "tasks", None) or []) if plan else []
        ours = {t.id for t in steps}
        observe("the planned goal's steps", f"{[(t.type.name, t.description[:40]) for t in steps]}")
        done = []
        for _ in range(12):
            ready = [t for t in await planning.get_next_tasks(SystemState()) if t.id in ours]
            if not ready:
                break
            for task in ready:
                outcome = await coord.execute_task(task)
                ok = bool(outcome and outcome.get("success"))
                task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
                done.append((task.type.name, ok, (outcome or {}).get("method")))
        observe("the plan's steps as run", f"{done}")
        text = summary.read_text() if summary.exists() else ""
        check("the planned goal wrote a summary at the path it named", bool(text.strip()),
              f"{len(text)} bytes")
        check("and the summary is what it was taught", "impeller" in text.lower() or
              "pump" in text.lower(), text[:200].replace("\n", " / "))

        print("\n== E. Code ==")
        plain_code = await job(coord, "Use Python to compute the average of 3, 5 and 10.")
        observe("plain words: compute with Python", said(plain_code)[:300])
        declared_code = await job(
            coord, "Run the average calculation.",
            metadata={"parameters": {"tool_plan": [{"tool": "run_python",
                                                    "args": {"code": "print(sum([3, 5, 10]) / 3)"}}]}})
        print(f"    declared run_python: {said(declared_code)[:200]!r}")
        check("with run_python declared, the code runs and returns 6.0", "6.0" in said(declared_code),
              said(declared_code)[:160])

        print("\n== F. Which learning paths moved ==")
        consolidated = await L.consolidate_learning()
        after = await measure(d)
        moved = {k: after[k] - before[k] for k in after}
        EV.metric("store_deltas", moved)
        print(f"    deltas: {moved}")
        by_cause = await d.execute_query(
            "SELECT cause, disposition, count(*) AS n FROM unified.knowledge_updates "
            "WHERE occurred_at >= to_timestamp($1) GROUP BY 1, 2 ORDER BY 3 DESC",
            (started,), fetch_all=True) or []
        observe("knowledge ledger since start, by cause",
                f"{[(r['cause'], r['disposition'], r['n']) for r in by_cause]}")
        tools = await d.execute_query(
            "SELECT tool_names_used, count(*) AS n, sum(CASE WHEN success THEN 1 ELSE 0 END) AS ok "
            "FROM tool_usage_history WHERE started_at >= to_timestamp($1) GROUP BY 1",
            (started,), fetch_all=True) or []
        observe("tool runs since start", f"{[(r['tool_names_used'], r['n'], r['ok']) for r in tools]}")
        check("tool runs were metered to learning", moved["tool_runs"] > 0, f"+{moved['tool_runs']}")
        scoped = await d.execute_query(
            "SELECT count(*) AS n FROM unified.scoped_beliefs WHERE scope_actor = $1",
            (USER,), fetch_one=True)
        observe("this user's scoped context (beliefs)", f"{scoped['n']}")
        from core.integration.universal_domain_master import get_universal_domain_master
        udm = get_universal_domain_master()
        check("the taught domain is a domain the substrate holds", await udm.has_domain(DOMAIN))
        competence = udm.competence_belief(DOMAIN)
        observe("competence in the taught domain",
                f"{getattr(competence, 'posterior_probability', None)}")
        observe("consolidation", f"{consolidated}")
    finally:
        try:
            shutil.rmtree(work, ignore_errors=True)
            # WHAT THIS RUN'S USER LEARNED GOES WITH THEM. The lesson is kept; the
            # user is a fixture. Left behind, the next run's user looking up the
            # same page counted as an INDEPENDENT holder, and the web finding was
            # promoted into the shared mind on the strength of two test users.
            for sql in ("DELETE FROM unified.scoped_concept_relations WHERE scope_actor = $1",
                        "DELETE FROM unified.scoped_beliefs WHERE scope_actor = $1",
                        "DELETE FROM memory_hot.memory_hot WHERE user_id = $1"):
                await d.execute_query(sql, (USER,))
            # The web finding is world knowledge now, so it is the RUN's residue, not the
            # user's: removed by its research evidence, and the next run looks it up again.
            await forget_look_up(d, LOOKED_UP)
        finally:
            await shutdown(system)

    await EV.verify_database()
    passed = sum(1 for r in results if r)
    print(f"\n==== TEACH-AND-DO-01: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
