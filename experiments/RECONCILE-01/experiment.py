#!/usr/bin/env python3
"""RECONCILE-01 — whoever owns a pursuit closes it, once, from the world.

DRIFT_CONSOLIDATION §0 made reconciliation a pipeline stage with one rule: the
execution path that OWNS a pursuit closes its intent, exactly once. Every earlier
experiment drove `coord._run_tool` directly, which owns nothing — so the owner
paths were code-complete and unevidenced, and a first version that closed a
multi-step route on its FIRST step passed every suite.

This drives every case through the real dispatcher, `execute_task`, never
`_run_tool`, and reads the verdict off the intent authority:

  A  PLAN owner (`_drive_substrate_goal`): a two-step route closes ONCE, after
     BOTH steps — not on step one — and as fulfilled.
  B  a plan STEP (`plan_id` present) runs and does NOT close the plan's intent.
  C  STANDALONE operator owner: closes its intent, fulfilled.
  D  the WORLD decides, not the step: an operator that ran and CONFIRMED its rule,
     but left the file somewhere the intent did not mean, closes as missed —
     and the rule is not blamed.
  E  a REFUSED standalone operator (Law 2: never read) still closes its pursuit
     as missed; the world and the rule are untouched.
  F  OPERATION owner (`_execute_operation`, declared tools): closes, fulfilled.
  G  an operation that is a plan step does NOT close.

`_reconcile_intent` is wrapped only to COUNT calls; it runs unchanged.
Self-cleaning: every intent this run formed is deleted, and the temp tree removed.
"""
import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import RunRecord  # noqa: E402

os.environ.setdefault("LYRIC_SHADOW_MODE", "1")

from experiments.fs_move_teach import DOMAIN, ensure_taught  # noqa: E402
# NO FIXED RULE ID. This named `rule_399de8f89089`, which no longer exists: rule
# identity became a fingerprint over canonical meaning, and the domain's MOVE_FILE
# operator has been re-induced since. What the cases rely on is whichever validated
# rule each proved route RESTS ON, read from the route itself.

PASS = FAIL = 0
EV = RunRecord(
    "RECONCILE-01",
    claim="Every execution path that owns a pursuit reconciles its intent exactly "
          "once, from the re-observed world; a step that does not own the pursuit "
          "leaves it open for its owner.",
    hypothesis="If ownership is the rule, then a planned route closes once after "
               "its last step, a standalone operator and a declared-tool operation "
               "each close their own intent (including when refused), a plan step "
               "closes nothing, and the verdict follows the world rather than the "
               "step's own success.")


def check(label, ok, detail=""):
    global PASS, FAIL
    EV.check(label, ok, detail)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


def make_task(description, provenance=None, metadata=None):
    from core.agents.autonomous.shared_types import (
        Task, TaskType, TaskStatus, Priority, TaskSource)
    return Task(id=str(uuid4()), type=TaskType.EXECUTION, description=description,
                priority=Priority.MEDIUM, status=TaskStatus.PENDING,
                created_at=datetime.now(), source=TaskSource.AUTONOMOUS,
                provenance=dict(provenance or {}), metadata=dict(metadata or {}))


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.shared_types import Priority
    from core.execution.effect_verification import RuntimeOutcome
    from core.execution.operator_binding import get_binding_registry
    from core.execution.tool_domain import sensed_fact, take_up_workspace, term
    from core.learning.rule_induction import Fact
    from core.learning.rule_store import EpistemicStatus, get_rule_store
    from core.reasoning.intent_authority import get_intent_authority
    from core.reasoning.temporal_reasoning import PlanningStatus

    IA = get_intent_authority()
    store = get_rule_store()
    formed = set()

    root = Path(tempfile.mkdtemp(prefix="reconcile-01-"))
    for d in ("inbox", "archive", "elsewhere"):
        (root / d).mkdir()
    names = ("a", "b", "step", "solo", "stray", "moved", "tool", "toolstep")
    for n in names:
        (root / "inbox" / f"{n}.txt").write_text(f"{n}\n")

    def in_dir(name, d):
        return (root / d / f"{name}.txt").exists()

    def goal(name, d="archive"):
        # "It is in `d`", in perception's words: a file there, and no longer one
        # in the inbox it started in.
        return [sensed_fact("kind", "path", str(root / d / f"{name}.txt"), "file").to_formula(),
                "¬" + sensed_fact("kind", "path", str(root / "inbox" / f"{name}.txt"),
                                  "file").to_formula()]

    coord = AutonomousCoordinator()
    # What initialize() attaches in production. Case D files a demonstration
    # with a new signature, which wakes the induction drain, and the drain
    # records competence through the domain master.
    from core.integration.universal_domain_master import get_universal_domain_master
    coord.universal_domain_master = get_universal_domain_master()
    # THE PRECONDITION IS DECLARED, NOT ASSUMED: every case rests on a MOVE_FILE
    # the substrate learned from its own acts, taught here if it is not there.
    check("the MOVE_FILE operator is held, or taught", await ensure_taught())
    check("execution faculty up", await coord.initialize_execution_faculty())
    await coord.planning.initialize()
    take_up_workspace(DOMAIN, str(root))
    binding = get_binding_registry().get(DOMAIN, "MOVE_FILE")

    validated = [r for r in await store.load(domain_id=DOMAIN)
                 if r.status is EpistemicStatus.VALIDATED
                 and r.rule.action.predicate == "MOVE_FILE"]
    check("the domain holds a validated MOVE_FILE operator for every case to rest on",
          bool(validated), f"{[r.rule_id for r in validated]}")
    rested_on = set()     # the rule ids the proved routes actually stood on

    # AND EVERY DEMONSTRATION THIS RUN FILES. Each act here records one into
    # this shared fixture domain and enqueues its signature for induction. Left
    # behind, they are induced by the NEXT process that wakes the drain — measured:
    # run right after this one, CREDIT-01 watched a new rule appear mid-run
    # (`MOVE_FILE(?X0, Finbox, ?X1)`, induced 0.4 s after its own first act, over
    # a batch holding six of this run's demonstrations) and failed its "this miss
    # taught nothing" check. Recorded by id at the store's one write, removed at
    # the end with the pending entries this run created (not ones already queued).
    from core.learning.demonstration_store import get_demonstration_store
    demos = get_demonstration_store()
    filed = []
    pending_before = {tuple(row) for row in await demos.pending_signatures()}
    _append = demos.append

    async def recorded_append(example, *, domain_id):
        written = await _append(example, domain_id=domain_id)
        if written:          # every domain: its reading steps file into `tools:path` too
            filed.append(example.evidence_id)
        return written
    demos.append = recorded_append

    # EVERY GOAL THIS RUN CREATES IS REMOVED WITH IT. The cleanup used to delete
    # the intents it formed and leave the goals and plans that name them — so
    # each run left `active` goals ("[substrate goal] archive a and b") pointing
    # at intents that no longer exist. Recorded here, at the one place goals are
    # made, including the goal case A's drive creates internally.
    created_goals = []
    _create_goal = coord.planning.create_goal

    async def recorded_goal(*args, **kwargs):
        made = await _create_goal(*args, **kwargs)
        if made is not None:
            created_goals.append(made.id)
        return made
    coord.planning.create_goal = recorded_goal

    # ── instrumentation: count closes, run them unchanged ──────────────────
    closes = []
    original = coord._reconcile_intent

    async def counted(intent_id, domain_id, **kw):
        out = await original(intent_id, domain_id, **kw)
        closes.append({"intent_id": str(intent_id), "result": out,
                       "files_archived": sorted(
                           n for n in names if in_dir(n, "archive"))})
        return out
    coord._reconcile_intent = counted

    def closes_for(intent_id):
        return [c for c in closes if c["intent_id"] == str(intent_id)]

    async def prove(conditions, label):
        world = get_binding_registry().observe_world(DOMAIN) or set()
        g = await coord.planning.create_goal(label, Priority.MEDIUM,
                                             state_conditions=conditions)
        out = await coord.planning.plan_for_goal(
            g.id, {"world_state": [str(f) for f in world], "domain_id": DOMAIN})
        if out.status is not PlanningStatus.PLAN_FOUND:
            return out, None
        iid = ((out.plan.metadata or {}).get("intent") or {}).get("intent_id")
        if iid:
            formed.add(iid)
        rested_on.update(t.provenance.get("learned_rule_id")
                         for t in out.plan.tasks
                         if (t.provenance or {}).get("learned_rule_id"))
        return out, iid

    def operator_step(plan):
        return next(t for t in plan.tasks
                    if (t.provenance or {}).get("grounded_operator"))

    async def read(name):
        path = str(root / "inbox" / f"{name}.txt")
        await coord._run_tool("read_file", {"file_path": path}, make_task(f"read {name}"))
        coord.reading.record(path)

    async def status_of(intent_id):
        held = await IA.get_by_id(str(intent_id))
        return held.status if held else None, (held.outcome or {}) if held else {}

    # ── A. the PLAN owner closes a two-step route once, at the end ─────────
    print("\n== A. Plan owner: a two-step route closes once, after both steps ==")
    task_a = make_task("archive a and b", provenance={
        "goal_conditions": goal("a") + goal("b"), "domain_id": DOMAIN})
    res_a = await coord.execute_task(task_a)
    iid_a = ((res_a or {}).get("intent_outcome") or {}).get("intent_id")
    if iid_a:
        formed.add(iid_a)
    check("the route ran through the plan owner and reached the goal",
          bool(res_a) and res_a.get("execution_path") == "substrate_plan"
          and res_a.get("goal_reached") is True,
          f"path={(res_a or {}).get('execution_path')} steps={(res_a or {}).get('steps_executed')}")
    ran_ops = [s for s in (res_a or {}).get("steps", [])
               if (s or {}).get("execution_path") == "substrate"]
    check("it really was two operator steps", len(ran_ops) == 2, f"{len(ran_ops)} operator step(s)")
    a_closes = closes_for(iid_a)
    check("the intent was closed EXACTLY ONCE", len(a_closes) == 1, f"{len(a_closes)} close(s)")
    check("…and only after BOTH files had moved (not on step one)",
          bool(a_closes) and {"a", "b"} <= set(a_closes[0]["files_archived"]),
          f"archived at close: {a_closes[0]['files_archived'] if a_closes else None}")
    st, oc = await status_of(iid_a)
    check("it closed as fulfilled, matching what it meant",
          st == "fulfilled" and oc.get("matched_aim") is True, f"status={st}")
    check("both files really moved on disk",
          in_dir("a", "archive") and in_dir("b", "archive")
          and not in_dir("a", "inbox") and not in_dir("b", "inbox"))

    # ── B. a plan STEP is not the owner ────────────────────────────────────
    print("\n== B. A plan step runs but leaves the plan's intent to its owner ==")
    out_b, iid_b = await prove(goal("step"), "archive step")
    check("a route is proved", iid_b is not None, out_b.reason)
    step_b = operator_step(out_b.plan)
    await read("step")
    res_b = await coord.execute_task(step_b)
    check("the step ran through the operator path and confirmed",
          bool(res_b) and res_b.get("execution_path") == "substrate"
          and res_b.get("success") is True, str((res_b or {}).get("runtime_outcome")))
    check("the step did NOT close the plan's intent", closes_for(iid_b) == [],
          f"{len(closes_for(iid_b))} close(s)")
    st, _ = await status_of(iid_b)
    check("the intent is still open for its owner", st in ("forming", "active"), f"status={st}")

    # ── C. STANDALONE operator owns its pursuit ────────────────────────────
    print("\n== C. A standalone operator closes its own intent ==")
    out_c, iid_c = await prove(goal("solo"), "archive solo")
    prov_c = dict(operator_step(out_c.plan).provenance)
    prov_c.pop("plan_id", None)          # the same proved act, owned by no plan
    await read("solo")
    res_c = await coord.execute_task(make_task(prov_c["grounded_operator"], prov_c))
    check("the operator ran and confirmed",
          bool(res_c) and res_c.get("success") is True, str((res_c or {}).get("runtime_outcome")))
    check("it closed its intent exactly once", len(closes_for(iid_c)) == 1,
          f"{len(closes_for(iid_c))} close(s)")
    st, oc = await status_of(iid_c)
    check("as fulfilled, and the verdict travels with the result",
          st == "fulfilled" and (res_c.get("intent_outcome") or {}).get("matched_aim") is True,
          f"status={st}")

    # ── D. the world decides: a confirmed step can still miss the intent ───
    print("\n== D. A step that confirmed its rule, but missed the intent ==")
    out_d, iid_d = await prove(goal("stray"), "archive stray")
    prov_d = dict(operator_step(out_d.plan).provenance)
    prov_d.pop("plan_id", None)
    elsewhere = Fact("MOVE_FILE", (term("path", str(root / "inbox" / "stray.txt")),
                                   term("path", str(root / "elsewhere" / "stray.txt")))).to_formula()
    prov_d["grounded_operator"] = elsewhere   # same operator, a destination not meant
    await read("stray")
    res_d = await coord.execute_task(make_task(elsewhere, prov_d))
    check("the act ran and its rule was CONFIRMED (the operator works)",
          bool(res_d) and res_d.get("runtime_outcome") == RuntimeOutcome.CONFIRMATION.value,
          f"{(res_d or {}).get('runtime_outcome')} / refused={(res_d or {}).get('refused')}")
    check("the file is where the act put it, not where the intent meant",
          in_dir("stray", "elsewhere") and not in_dir("stray", "archive"))
    st, oc = await status_of(iid_d)
    check("the intent closed once, as MISSED — the world decided, not the step",
          len(closes_for(iid_d)) == 1 and st == "abandoned" and oc.get("matched_aim") is False,
          f"closes={len(closes_for(iid_d))} status={st}")

    # ── E. a REFUSED standalone operator still concludes its pursuit ──────
    print("\n== E. A refused standalone operator closes its intent as missed ==")
    # THE REFUSAL IS ONE THE CURRENT LAWS MAKE. This case used to leave the file
    # unread and expect Law 2 to refuse the move. Since 2026-09-20 Law 2 judges
    # the path an act writes, not the one it relocates FROM (`_paths_acted_on`:
    # "a source is none of those") — so the unread move RAN, filed demonstrations
    # into this domain, and the case failed on a law that no longer says that.
    # The refusal used now is the other one every route must survive: the world
    # moved under it. The route is proved, then the file is relocated before the
    # act, and the executor refuses because its precondition no longer holds in
    # the observed world. A refused standalone operator, owning its pursuit.
    out_e, iid_e = await prove(goal("moved"), "archive moved")
    prov_e = dict(operator_step(out_e.plan).provenance)
    prov_e.pop("plan_id", None)
    (root / "inbox" / "moved.txt").rename(root / "elsewhere" / "moved.txt")
    res_e = await coord.execute_task(make_task(prov_e["grounded_operator"], prov_e))
    check("the act was refused", bool(res_e) and bool(res_e.get("refused")),
          str((res_e or {}).get("refused"))[:100])
    check("the refused act changed nothing on disk",
          in_dir("moved", "elsewhere") and not in_dir("moved", "archive")
          and not in_dir("moved", "inbox"))
    st, oc = await status_of(iid_e)
    check("the pursuit was concluded, once, as missed — not left in forming",
          len(closes_for(iid_e)) == 1 and st == "abandoned" and oc.get("matched_aim") is False,
          f"closes={len(closes_for(iid_e))} status={st}")
    check("the refusal is recorded as why", "refused" in str(oc.get("detail", "")),
          str(oc.get("detail", ""))[:100])

    # ── F. OPERATION owner (declared tools) ────────────────────────────────
    print("\n== F. A declared-tool operation closes its own intent ==")
    out_f, iid_f = await prove(goal("tool"), "archive tool")
    args_f = binding.parameters(Fact.parse(operator_step(out_f.plan).description).args)
    await read("tool")
    task_f = make_task("move tool.txt with a declared tool",
                       provenance={"intent_id": iid_f, "domain_id": DOMAIN},
                       metadata={"parameters": {"tool_plan": [
                           {"tool": binding.tool_name, "args": args_f}]}})
    res_f = await coord.execute_task(task_f)
    check("the declared tool ran", bool(res_f) and res_f.get("success") is True,
          str((res_f or {}).get("error"))[:90])
    st, oc = await status_of(iid_f)
    check("the operation closed its intent once, fulfilled",
          len(closes_for(iid_f)) == 1 and st == "fulfilled" and oc.get("matched_aim") is True,
          f"closes={len(closes_for(iid_f))} status={st}")

    # ── G. an operation that is a plan step does not close ─────────────────
    print("\n== G. A declared-tool plan step leaves the intent to its owner ==")
    out_g, iid_g = await prove(goal("toolstep"), "archive toolstep")
    step_g = operator_step(out_g.plan)
    args_g = binding.parameters(Fact.parse(step_g.description).args)
    await read("toolstep")
    task_g = make_task("move toolstep.txt as a plan step",
                       provenance={"intent_id": iid_g, "domain_id": DOMAIN,
                                   "plan_id": step_g.provenance.get("plan_id")},
                       metadata={"parameters": {"tool_plan": [
                           {"tool": binding.tool_name, "args": args_g}]}})
    res_g = await coord.execute_task(task_g)
    check("the declared tool ran", bool(res_g) and res_g.get("success") is True)
    st, _ = await status_of(iid_g)
    check("the plan step did NOT close the intent",
          closes_for(iid_g) == [] and st in ("forming", "active"),
          f"closes={len(closes_for(iid_g))} status={st}")

    # ── the rule was never blamed for any of it ────────────────────────────
    after = {rid: await store.get(rid) for rid in rested_on if rid}
    check("every rule the routes rested on is still validated after every case",
          bool(after) and all(r is not None and r.status is EpistemicStatus.VALIDATED
                              for r in after.values()),
          f"{ {rid: (r.status.value if r else None) for rid, r in after.items()} }")

    EV.metric("closes_recorded", len(closes), "count")
    EV.metric("intents_formed", len(formed), "count")

    # Self-cleaning
    coord._reconcile_intent = original
    await IA.store._ready()
    coord.planning.create_goal = _create_goal
    del demos.append                     # the store's own method again
    if filed:
        await IA.store.db.execute_query(
            "DELETE FROM unified.operator_demonstrations WHERE evidence_id = ANY($1::text[])",
            (filed,), commit=True)
    for domain_id, predicate, arity in await demos.pending_signatures():
        if (domain_id, predicate, arity) not in pending_before:
            await demos.clear_pending(domain_id=domain_id, predicate=predicate,
                                      arity=arity)
    EV.metric("demonstrations_filed_and_removed", len(filed), "count")
    for intent_id in formed:
        await IA.store.db.execute_query(
            "DELETE FROM unified.scoped_intents WHERE intent_id = $1", (intent_id,), commit=True)
        await IA.store.db.execute_query(
            "DELETE FROM unified.intents WHERE intent_id = $1", (intent_id,), commit=True)
    if created_goals:
        await IA.store.db.execute_query(
            "DELETE FROM unified.plans WHERE goal_id = ANY($1::text[])",
            (created_goals,), commit=True)
        await IA.store.db.execute_query(
            "DELETE FROM unified.goals WHERE id::text = ANY($1::text[])",
            (created_goals,), commit=True)
    for gid in created_goals:
        coord.planning.current_goals.pop(gid, None)
    for pid in [p.id for p in coord.planning.active_plans.values()
                if p.goal_id in set(created_goals)]:
        coord.planning.active_plans.pop(pid, None)

    await EV.verify_database()
    EV.write()
    shutil.rmtree(root, ignore_errors=True)
    print("\n" + "=" * 62)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
