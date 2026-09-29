#!/usr/bin/env python3
"""PURSUIT-01 — does work carry WHY it exists, and end with what actually ended it?

Queued tasks carry intent, so the substrate is never confused later about why work
exists, which also helps with drift; and the Constitution records a refusal as
replanned, refused or redirected, never as abandoned.

Measured before, on the live store and the live code:
  * 0 of 293 queued tasks named an intent — no producer recorded why its work existed;
  * every constitutional refusal was reconciled `abandoned`; `refused` was declared
    in the intent lifecycle and never written;
  * the declared-tool path returned an error string only, so whatever closed the
    pursuit could not tell a refusal from a failure;
  * nothing closed a pursuit that named no world state, so a task that carried one
    would have left it `forming` forever.

  A  WORK CARRIES ITS WHY         each producer forms the pursuit where it takes work on
  B  THE LAW'S WORD IS RECORDED   replanned / refused / halted, on real acts at the real gate
  C  THE WORK'S END CLOSES IT     fulfilled / abandoned / halted; the world's or the law's
                                  record is never overwritten; a plan step is not the owner
  D  THE GATE READS IT            sent back -> not repeated; halted -> resumes; a return reopens
  E  STANDING CHECK (static)      every Task the coordinator enqueues is intended first, and
                                  every ending of the task runner closes its pursuit

Run: ./venv_lyric/bin/python3 experiments/PURSUIT-01/experiment.py
"""
import ast
import asyncio
import contextlib
import io
import logging
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE.parent))
logging.disable(logging.CRITICAL)

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "PURSUIT-01",
    claim=("Every piece of work the substrate takes on carries the intent it serves, "
           "formed where the work was taken on, and that pursuit ends with what "
           "actually ended it — the constitution's verdict when the law stopped it, "
           "never `abandoned`."),
    hypothesis=("If each producer forms the pursuit through the intent authority, the "
                "acting paths carry the constitution's judgement to reconciliation, and "
                "the task's own ending closes what the world did not, then no work is "
                "left without a reason and no refusal is recorded as a loss."))

from experiments.fs_move_teach import DOMAIN, ensure_taught  # noqa: E402
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)


def static_checks():
    """E — read from the source, so a producer added later without an intent fails."""
    src = (REPO / "core/agents/autonomous/autonomous_coordinator.py").read_text()
    tree = ast.parse(src)
    sites, unintended, keyword_form = 0, [], []
    runner = None
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name == "_execute_and_validate_task":
            runner = fn
        intended = {}
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "intend" and node.args
                    and isinstance(node.args[0], ast.Name)):
                intended.setdefault(node.args[0].id, []).append(node.lineno)
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_task"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "task_queue"):
                continue
            if not node.args:
                keyword_form.append(f"{fn.name}:{node.lineno}")
                continue
            first = node.args[0]
            if not isinstance(first, ast.Name):
                continue
            sites += 1
            if not any(line < node.lineno for line in intended.get(first.id, [])):
                unintended.append(f"{fn.name}:{node.lineno} ({first.id})")
    marks = closes = 0
    if runner is not None:
        for node in ast.walk(runner):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("mark_completed", "mark_failed"):
                    marks += 1
                if node.func.attr == "conclude_pursuit":
                    closes += 1
    agents_src = (REPO / "core/agents/agents.py").read_text()
    body = agents_src[agents_src.index("async def _run_agent"):]
    body = body[:body.index("\n    def ", 10) if "\n    def " in body[10:] else len(body)]
    agent_ok = (0 <= body.find("intend(task") < body.find("execute_task(task")
                < body.find("conclude_pursuit("))
    return sites, unintended, keyword_form, marks, closes, agent_ok


async def main() -> int:
    quiet = io.StringIO()
    # THE PRECONDITION IS DECLARED, NOT ASSUMED: the route below is proved over
    # a MOVE_FILE the substrate learned from its own acts, taught if it is not
    # there.
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        taught = await ensure_taught()
    check("the MOVE_FILE operator is held, or taught", taught)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
        coord = AutonomousCoordinator()
        await coord.initialize(start_loop=False)   # no cognition loop: queued work is not run
    from core.agents.autonomous.shared_types import (
        Priority, SUBSTRATE_ACTOR, Task, TaskType)
    from core.database import get_database_manager
    from core.execution.operator_binding import get_binding_registry
    from core.execution.tool_domain import sensed_fact, take_up_workspace
    from core.learning.demonstration_store import get_demonstration_store
    from core.reasoning.intent_authority import continuity_goal, get_intent_authority

    db = get_database_manager()
    await db.initialize()
    authority = get_intent_authority()
    tag = uuid.uuid4().hex[:6]
    root = Path(tempfile.mkdtemp(prefix="pursuit-01-"))
    for d in ("inbox", "archive"):
        (root / d).mkdir()

    # ── what this run writes, recorded at the one place each is made ────────
    ids = lambda rows, k: {str(r[k]) for r in rows or []}
    intents_before = ids(await db.execute_query("SELECT intent_id FROM unified.intents", ()), "intent_id")
    queue_before = ids(await db.execute_query("SELECT task_id FROM unified.task_queue", ()), "task_id")
    demos = get_demonstration_store()
    pending_before = {tuple(r) for r in await demos.pending_signatures()}
    filed, created_goals = [], []
    _append, _create_goal = demos.append, coord.planning.create_goal

    async def recorded_append(example, *, domain_id):
        written = await _append(example, domain_id=domain_id)
        if written:
            filed.append(example.evidence_id)
        return written

    async def recorded_goal(*args, **kwargs):
        made = await _create_goal(*args, **kwargs)
        if made is not None:
            created_goals.append(made.id)
        return made
    demos.append, coord.planning.create_goal = recorded_append, recorded_goal

    async def status(intent_id, actor=None):
        held = await authority.get_by_id(str(intent_id), actor) if intent_id else None
        return held

    def declared(tid, tool, args, description):
        return Task(id=tid, type=TaskType.EXECUTION, description=description,
                    priority=Priority.LOW,
                    metadata={"parameters": {"tool_plan": [{"tool": tool, "args": args}]}})

    async def queued_intent(task_id):
        rows = await db.execute_query(
            "SELECT payload FROM unified.task_queue WHERE task_id = $1", (task_id,))
        if not rows:
            return None, None
        import json
        payload = rows[0]["payload"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        task = (payload or {}).get("task") or {}
        return (task.get("provenance") or {}).get("intent_id"), task.get("actor")

    try:
        print("\n== A. Work carries its WHY, formed where it was taken on ==")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            ack = await coord.handle_user_request(
                f"tidy the PURSUIT-01 scratch area {tag}", source="api",
                metadata={"conversation_id": f"pursuit01-{tag}"})
        iid, actor = await queued_intent((ack or {}).get("task_id"))
        held = await status(iid, actor)
        check("a USER REQUEST is queued naming its pursuit", bool(iid) and held is not None,
              f"task={(ack or {}).get('task_id')} intent={iid}")
        check("…scoped to the requester, their words the aim, the session recorded",
              held is not None and held.origin_kind == "goal"
              and held.actor == actor and actor != SUBSTRATE_ACTOR
              and tag in held.aim and held.content.get("session") == f"pursuit01-{tag}",
              f"origin={getattr(held, 'origin_kind', None)} actor={actor}")
        check("…and its anonymous shape says what kind of pursuit it is",
              held is not None and held.shape.get("pursuit") == "user_request"
              and held.shape.get("raised_by") == "user", f"{getattr(held, 'shape', None)}")

        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await coord._handle_error(RuntimeError(f"PURSUIT-01 probe {tag}"),
                                      f"pursuit_01_{tag}")
        rows = await db.execute_query(
            "SELECT task_id FROM unified.task_queue WHERE payload::text LIKE $1",
            (f"%pursuit_01_{tag}%",))
        fix_iid, _ = await queued_intent(rows[0]["task_id"]) if rows else (None, None)
        fix = await status(fix_iid)
        check("a REPAIR the substrate raised for its own error names its pursuit",
              fix is not None and fix.origin_kind == "self_goal"
              and fix.shape.get("pursuit") == "repair", f"intent={fix_iid}")

        note = root / "note.txt"
        note.write_text("a note for the agent to read\n")
        from core.agents.agents import AgentCoordinator
        factory = AgentCoordinator()
        factory.bind_coordinator(coord)
        agent_id = f"pursuit01-agent-{tag}"
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            ran = await factory._run_agent(
                agent_id, "read the PURSUIT-01 note", TaskType.RESEARCH, None,
                ["read_file"], {"tool_plan": [{"tool": "read_file",
                                               "args": {"file_path": str(note)}}]})
        agent = await authority.get(SUBSTRATE_ACTOR, continuity_goal(agent_id))
        check("AGENT work names its pursuit, and closes it with its real result",
              agent is not None and agent.shape.get("pursuit") == "agent_work"
              and ran.get("success") is True and agent.status == "fulfilled",
              f"success={ran.get('success')} status={getattr(agent, 'status', None)}")

        # A route proved WHILE working on a pursuit is its own intent, with that
        # pursuit as parent — the tree, not a merge.
        take_up_workspace(DOMAIN, str(root))
        (root / "inbox" / "route.txt").write_text("route\n")
        parent = declared(f"pursuit01_parent_{tag}", "read_file", {"file_path": str(note)},
                          "archive route.txt")
        parent_id = await coord.intend(parent, pursuit="probe_parent")
        # "route.txt is archived", in perception's words.
        goal_fact = [
            sensed_fact("kind", "path", str(root / "archive" / "route.txt"), "file").to_formula(),
            "¬" + sensed_fact("kind", "path", str(root / "inbox" / "route.txt"), "file").to_formula()]
        world = get_binding_registry().observe_world(DOMAIN) or set()
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            g = await coord.planning.create_goal("PURSUIT-01 route", Priority.MEDIUM,
                                                 state_conditions=goal_fact)
            proved = await coord.planning.plan_for_goal(
                g.id, {"world_state": [str(f) for f in world], "domain_id": DOMAIN,
                       "parent_intent_id": parent_id})
        route_iid = (((getattr(proved, "plan", None) and proved.plan.metadata) or {})
                     .get("intent") or {}).get("intent_id")
        route = await status(route_iid)
        check("a route proved while working on a pursuit is its CHILD, not merged into it",
              route is not None and route.parent_intent_id == parent_id
              and route.intent_id != parent_id and route.proved,
              f"route={route_iid} parent={getattr(route, 'parent_intent_id', None)}")

        print("\n== B. The law's word is recorded — never `abandoned` ==")
        existing = root / "existing.txt"
        existing.write_text("written by someone else\n")          # never read
        t_replan = declared(f"pursuit01_replan_{tag}", "write_file",
                            {"file_path": str(existing), "content": "overwritten\n"},
                            "overwrite the existing note")
        await coord.intend(t_replan, pursuit="probe_write")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            res_replan = await coord.execute_task(t_replan)
        rp = await status(t_replan.provenance["intent_id"])
        said = (rp.outcome or {}).get("judgment") or {} if rp else {}
        check("a REPLANNED act leaves its pursuit `replanned`, with the law and why",
              rp is not None and rp.status == "replanned" and said.get("verdict") == "replan"
              and said.get("law_number") == 2 and bool(said.get("judgment_id")),
              f"status={getattr(rp, 'status', None)} L{said.get('law_number')}: "
              f"{str(said.get('reason'))[:70]}")
        check("…and the file is untouched", existing.read_text() == "written by someone else\n")

        victim = root / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("keep\n")
        t_block = declared(f"pursuit01_block_{tag}", "run_shell_command",
                           {"command": f"rm -rf {victim}"}, "remove the victim directory")
        await coord.intend(t_block, pursuit="probe_remove")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await coord.execute_task(t_block)
        bk = await status(t_block.provenance["intent_id"])
        bsaid = (bk.outcome or {}).get("judgment") or {} if bk else {}
        check("a BLOCKED act concludes its pursuit `refused` — the one refusal that ends it",
              bk is not None and bk.status == "refused" and bsaid.get("verdict") == "block",
              f"status={getattr(bk, 'status', None)} L{bsaid.get('law_number')}")
        check("…and nothing was removed", (victim / "keep.txt").exists())

        # An act already past the task gate when a human halts the substrate.
        t_halt = declared(f"pursuit01_halt_{tag}", "write_file",
                          {"file_path": str(root / "halted.txt"), "content": "x\n"},
                          "write a note while halted")
        await coord.intend(t_halt, pursuit="probe_halt")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await coord.constitution.halt("PURSUIT-01 probe", by="constitution")
            try:
                await coord._execute_operation(t_halt)
            finally:
                await coord.constitution.resume(authorized_by="pursuit_01")
        ht = await status(t_halt.provenance["intent_id"])
        check("an act stopped by a HALT leaves its pursuit `halted` — not now, not never",
              ht is not None and ht.status == "halted"
              and ((ht.outcome or {}).get("judgment") or {}).get("law_number") == 5,
              f"status={getattr(ht, 'status', None)}")
        check("…and it did not write", not (root / "halted.txt").exists())

        # The verdict→status map, fed a constructed judgement — labelled as such:
        # a real REDIRECT is reachable only by a PROVED removal on a declared-
        # sensitive target, which OPERATOR-REMOVAL-01 judges and never executes.
        check("(map) a REDIRECT → `redirected`; a Law 5 BLOCK that is not the halt → "
              "`refused`; the halt's own BLOCK → `halted`, read from the judgement "
              "and not from whether a halt still stands; an ALLOW → nothing",
              coord._pursuit_stopped_as({"verdict": "redirect", "law_number": 3}) == "redirected"
              and coord._pursuit_stopped_as({"verdict": "block", "law_number": 5}) == "refused"
              and coord._pursuit_stopped_as({"verdict": "block", "law_number": 5,
                                             "halt": True}) == "halted"
              and not coord.constitution.halted
              and coord._pursuit_stopped_as({"verdict": "allow"}) is None)

        (root / "archive" / "held.txt").write_text("already there\n")
        held_fact = sensed_fact("kind", "path", str(root / "archive" / "held.txt"),
                                "file").to_formula()
        w_iid = await coord.intend(declared(f"pursuit01_world_{tag}", "read_file",
                                            {"file_path": str(note)}, "keep held.txt archived"),
                                   pursuit="probe_world")
        await coord._reconcile_intent(w_iid, DOMAIN, goal_conditions=[held_fact],
                                      judgment={"verdict": "replan", "law_number": 2})
        wd = await status(w_iid)
        check("THE WORLD DECIDES FIRST — an aim that holds is fulfilled, however its act ended",
              wd is not None and wd.status == "fulfilled"
              and ((wd.outcome or {}).get("judgment") or {}).get("verdict") == "replan",
              f"status={getattr(wd, 'status', None)}")

        print("\n== C. The work's end closes its pursuit ==")
        async def fresh(name):
            t = declared(f"pursuit01_{name}_{tag}", "read_file", {"file_path": str(note)}, name)
            await coord.intend(t, pursuit=f"probe_{name}")
            return t
        t_done, t_lost, t_paused, t_step = (await fresh("done"), await fresh("lost"),
                                            await fresh("paused"), await fresh("step"))
        await coord.conclude_pursuit(t_done, {"success": True}, completed=True)
        await coord.conclude_pursuit(t_lost, {"success": False, "error": "no tool could do it"},
                                     completed=False)
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            await coord.constitution.halt("PURSUIT-01 gate probe", by="constitution")
            try:
                at_gate = await coord._task_gate(t_paused)
            finally:
                await coord.constitution.resume(authorized_by="pursuit_01")
        await coord.conclude_pursuit(t_paused, at_gate, completed=False)
        t_step.provenance["plan_id"] = f"plan_probe_{tag}"
        await coord.conclude_pursuit(t_step, {"success": True}, completed=True)
        done, lost, paused, step = [await status(t.provenance["intent_id"])
                                    for t in (t_done, t_lost, t_paused, t_step)]
        check("completed work closes its pursuit `fulfilled`",
              done is not None and done.status == "fulfilled")
        check("work that ended with no verdict closes `abandoned`, saying why",
              lost is not None and lost.status == "abandoned"
              and (lost.outcome or {}).get("detail") == "no tool could do it")
        check("work the gate stopped for a halt closes `halted` — even closed after "
              "the halt was lifted, as the task runner's retries would",
              paused is not None and paused.status == "halted",
              f"status={getattr(paused, 'status', None)}")
        check("a step of a plan is not the owner — the plan closes its route",
              step is not None and step.status == "forming", f"status={getattr(step, 'status', None)}")
        again = await coord.conclude_pursuit(t_replan, res_replan, completed=False)
        check("the LAW's record is never overwritten by the work's ending",
              again == "replanned"
              and (await status(t_replan.provenance["intent_id"])).status == "replanned")

        print("\n== D. The gate reads it ==")
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            g_replan = await coord._task_gate(t_replan) or {}
            g_block = await coord._task_gate(t_block) or {}
            g_halt = await coord._task_gate(t_halt)
        check("the REPLANNED pursuit's work is not repeated at the gate, naming the law",
              g_replan.get("refused") and g_replan.get("intent_status") == "replanned"
              and "Law 2" in g_replan.get("error", ""), g_replan.get("error", "")[:100])
        check("the REFUSED pursuit's work does not start",
              g_block.get("refused") and g_block.get("intent_status") == "refused")
        check("the HALTED pursuit's work starts again once the halt is lifted",
              g_halt is None, f"{g_halt}")
        back = await authority.form(
            "self_goal", SUBSTRATE_ACTOR, continuity_goal(t_replan.id),
            shape={"pursuit": "probe_write", "replanned_with": "a reading first"},
            content={"aim": "overwrite the existing note"})
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            g_back = await coord._task_gate(t_replan)
        check("planning's RETURN reopens the replanned pursuit, and its work may start",
              back.status == "active" and g_back is None
              and (back.shape.get("earlier_attempts") or [{}])[-1].get("status") == "replanned",
              f"status={back.status}")

        print("\n== E. Standing check — read from the source ==")
        sites, unintended, keyword_form, marks, closes, agent_ok = static_checks()
        check("every Task the coordinator enqueues is intended first",
              sites >= 4 and not unintended, f"{sites} site(s); unintended={unintended}")
        check("every ending of the task runner closes its pursuit",
              marks == closes and marks >= 3, f"{marks} ending(s), {closes} close(s)")
        check("agent work is intended before it runs and closed after",
              agent_ok)
        if keyword_form:
            EV.note(f"add_task called WITHOUT a Task at {keyword_form} — add_task takes a "
                    f"Task, so this enqueues nothing (a TypeError swallowed as a warning); "
                    f"reported, not decided")
            print(f"  [NOTE] add_task called without a Task (cannot enqueue): {keyword_form}")
    finally:
        # ── remove everything this run wrote ─────────────────────────────────
        del demos.append                              # the store's own method again
        coord.planning.create_goal = _create_goal
        if filed:
            await db.execute_query(
                "DELETE FROM unified.operator_demonstrations WHERE evidence_id = ANY($1::text[])",
                (filed,), commit=True)
        for domain_id, predicate, arity in await demos.pending_signatures():
            if (domain_id, predicate, arity) not in pending_before:
                await demos.clear_pending(domain_id=domain_id, predicate=predicate, arity=arity)
        if created_goals:
            await db.execute_query("DELETE FROM unified.plans WHERE goal_id = ANY($1::text[])",
                                   (created_goals,), commit=True)
            await db.execute_query("DELETE FROM unified.goals WHERE id::text = ANY($1::text[])",
                                   (created_goals,), commit=True)
        new_tasks = sorted(ids(await db.execute_query("SELECT task_id FROM unified.task_queue", ()),
                               "task_id") - queue_before)
        if new_tasks:
            await db.execute_query("DELETE FROM unified.task_queue WHERE task_id = ANY($1::text[])",
                                   (new_tasks,), commit=True)
        new_intents = sorted(ids(await db.execute_query("SELECT intent_id FROM unified.intents", ()),
                                 "intent_id") - intents_before)
        if new_intents:
            await db.execute_query(
                "DELETE FROM unified.scoped_intents WHERE intent_id = ANY($1::text[])",
                (new_intents,), commit=True)
            await db.execute_query(
                "DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])",
                (new_intents,), commit=True)
        get_binding_registry().clear(DOMAIN)
        shutil.rmtree(root, ignore_errors=True)
        EV.metric("intents_written_and_removed", len(new_intents), "count")
        EV.metric("queued_tasks_written_and_removed", len(new_tasks), "count")
        EV.metric("demonstrations_written_and_removed", len(filed), "count")

    passed, total = sum(results), len(results)
    EV.note("A live, B on real acts at the real gate (REPLAN Law 2, BLOCK Law 3, halt "
            "Law 5); REDIRECT's status is checked on the map with a constructed "
            "judgement, labelled — a real one needs a proved removal of a declared-"
            "sensitive target, which OPERATOR-REMOVAL-01 judges and never executes.")
    await EV.verify_database()
    EV.write()
    print(f"\n==== PURSUIT-01: {passed}/{total} checks passed ====\n")
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
