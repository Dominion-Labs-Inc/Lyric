#!/usr/bin/env python3
"""PLANNING-01 — one planning authority, and every planning step verified honest.

The planning faculty is what gives the substrate the ability to make plans, and
`self.planning` is the only place a plan is formed or operated on. This checks
that claim and, for each planning path, that what it reports is TRUE — a plan it
calls proved really is proved, and a failure is reported as a failure rather than
quietly becoming a plausible-looking plan.

Against the real substrate: real coordinator, real rule store, real learned
operators, real Postgres. Nothing mocked.

  A  ONE AUTHORITY      the planner IS `self.planning`; goals made through it are
                        the goals it plans
  B  TRUE POSITIVE      a state goal with a real operator route plans, and the
                        steps are grounded in learned rules
  C  NO FALSE POSITIVE  a state goal with no route reports UNREACHABLE /
                        INDETERMINATE and produces NO plan
  D  THE GUARD          a state goal can never be decomposed into templates
  E  HONEST LABEL       a descriptive goal's plan is labelled `template`, never
                        presented as proved
  F  KNOWN FALSE POSITIVES — measured, not yet fixed: template confidence and
                        duration are invented rather than read from what the
                        substrate actually tracks (earned operating reliability,
                        measured tool latency).

F is EXPECTED TO FAIL until those two are fixed. It is here so the fix has a
before-and-after on the record rather than a claim.
"""
import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import RunRecord  # noqa: E402

os.environ.setdefault("LYRIC_SHADOW_MODE", "1")

PASS = FAIL = 0
EV = RunRecord(
    "PLANNING-01",
    claim="The substrate has exactly one planning authority, and every planning "
          "path reports honestly: a proved plan is really proved, an unreachable "
          "goal yields no plan, and a template plan is never presented as proved.",
    hypothesis="If planning is routed by goal type through one engine, then a "
               "state goal either proves a grounded operator route or reports "
               "why it could not, never falling through to a plausible template; "
               "and what a plan claims about itself is read from what the "
               "substrate measures rather than invented.")


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


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.shared_types import Priority, GoalType
    from core.execution.operator_binding import get_binding_registry
    from core.execution.tool_domain import sensed_fact, take_up_workspace, term
    from core.learning.rule_induction import Fact
    from core.learning.rule_store import get_rule_store
    from core.reasoning.temporal_reasoning import PlanningStatus

    # THE PRECONDITION IS DECLARED, NOT ASSUMED. This plans over a MOVE_FILE
    # operator the substrate LEARNED from its own acts. That was ambient state:
    # when the store was wiped, this failed with a signature that reads like
    # broken code rather than a missing prerequisite. `ensure_taught` teaches it
    # from real executions if it is not there, and costs a store read if it is.
    from experiments.fs_move_teach import DOMAIN, ensure_taught
    if not await ensure_taught():
        print("  [precondition] FAILED: no executable MOVE_FILE operator in "
              f"{DOMAIN}; nothing below can plan", flush=True)
        return 1
    root = Path(tempfile.mkdtemp(prefix="planning-01-"))
    (root / "inbox").mkdir()
    (root / "archive").mkdir()
    (root / "inbox" / "report.txt").write_text("the file the plan is about\n")

    print("\n== A. One planning authority ==")
    coord = AutonomousCoordinator()
    check("the planning faculty initialises", await coord.planning.initialize())
    # Stand in for main.py's bootstrap: the tool-metrics owner is constructed
    # there with the canonical DB (core/main.py:1148). Without it the learning
    # authority honestly reports "no database", and the measured path would never
    # be exercised here.
    from core.learning.adaptive_tool_owner import get_adaptive_tool_learning
    get_adaptive_tool_learning(coord.planning.unified_db)
    engine = await coord._get_planning_engine()
    check("the planner IS self.planning (one authority, not a second engine)",
          engine is coord.planning and not hasattr(coord, "_planning_engine"),
          f"same_object={engine is coord.planning}")
    probe = await coord.planning.create_goal("authority probe", Priority.MEDIUM)
    check("a goal made through self.planning is a goal the planner holds",
          bool(probe) and probe.id in engine.current_goals, probe.id[:8] if probe else None)

    print("\n== B. True positive: a state goal with a real operator route ==")
    # The workspace is handed over; the substrate looks at it with its own
    # perception, and what is there becomes the world it plans in.
    take_up_workspace(DOMAIN, str(root))
    rules = await get_rule_store().executable_rules(domain_id=DOMAIN)
    check("the domain offers a learned, executable operator", bool(rules),
          f"{len(rules)} executable rule(s) in {DOMAIN}")
    world = get_binding_registry().observe_world(DOMAIN) or frozenset()
    report = root / "inbox" / "report.txt"
    # "Archive the report", in perception's words: the report is a file in
    # archive, and is no longer one in the inbox.
    reachable = await engine.create_goal(
        "archive the report", Priority.MEDIUM,
        state_conditions=[
            sensed_fact("kind", "path", str(root / "archive" / "report.txt"),
                        "file").to_formula(),
            "¬" + sensed_fact("kind", "path", str(report), "file").to_formula()])
    check("a goal with state conditions is a STATE goal",
          reachable.goal_type is GoalType.STATE, str(reachable.goal_type))
    out = await engine.plan_for_goal(
        reachable.id, {"world_state": [f.to_formula() for f in world],
                       "domain_id": DOMAIN})
    check("it plans, by search, and says so",
          out.status is PlanningStatus.PLAN_FOUND and out.planning_mode == "state",
          f"{out.status.value} / {out.planning_mode} — {out.reason}")
    # A proved route may also carry PREPARATORY READINGS: Law 2 refuses an act on
    # a file the substrate has no current account of, and the answer the law gives
    # is "read it first", which is a planning step. Those steps declare themselves
    # (`read_path`) and are deliberately NOT grounded operators — they are not part
    # of what was proved, they are what the law requires before it may be run.
    plan_tasks = list(out.plan.tasks if out.plan else [])
    operator_steps = [t for t in plan_tasks
                      if not (t.provenance or {}).get("read_path")]
    reading_steps = [t for t in plan_tasks if (t.provenance or {}).get("read_path")]
    steps_grounded = bool(operator_steps) and all(
        (t.provenance or {}).get("grounded_operator") and
        (t.provenance or {}).get("learned_rule_id")
        for t in operator_steps)
    check("a preparatory reading is declared as one, never as a grounded operator",
          all(not (t.provenance or {}).get("grounded_operator") for t in reading_steps),
          f"{len(reading_steps)} reading step(s), {len(operator_steps)} operator step(s)")
    check("every step is grounded in a learned rule (not a description)",
          steps_grounded,
          str([(t.provenance or {}).get("grounded_operator")
               for t in (out.plan.tasks if out.plan else [])]))
    check("a proved plan states full confidence because it is proved, not estimated",
          bool(out.plan) and out.plan.confidence == 1.0,
          f"confidence={out.plan.confidence if out.plan else None}")

    print("\n== C. No false positive: a state goal with no route ==")
    # ENCRYPTED is in no learned operator's effects — nothing can reach it.
    unreachable = await engine.create_goal(
        "encrypt the report", Priority.MEDIUM,
        state_conditions=[Fact("ENCRYPTED", (term("path", str(report)),)).to_formula()])
    out_u = await engine.plan_for_goal(
        unreachable.id, {"world_state": [f.to_formula() for f in world],
                         "domain_id": DOMAIN})
    check("an unreachable state goal does NOT produce a plan",
          out_u.status is not PlanningStatus.PLAN_FOUND and out_u.plan is None,
          f"{out_u.status.value}, plan={out_u.plan}")
    check("it reports WHY, as a state verdict — never as a template plan",
          out_u.planning_mode == "state"
          and out_u.status in (PlanningStatus.UNREACHABLE, PlanningStatus.INDETERMINATE),
          f"{out_u.status.value} / {out_u.planning_mode} — {out_u.reason}")

    print("\n== D. The guard: a state goal can never be templated ==")
    # The property that matters is the SAFETY one: no template plan is ever
    # produced for a state goal. (The guard raises internally, but
    # generate_plan's blanket `except Exception` swallows it and returns None —
    # so a deliberate refusal is indistinguishable from a failure to the caller.
    # That is a reporting weakness, recorded below, not a false positive.)
    plans_before = set(engine.active_plans)
    refused = False
    refusal_detail = "generate_plan accepted a STATE goal"
    try:
        templated = await engine.generate_plan(reachable.id, {})
    except ValueError as e:
        refused, templated = True, None
        refusal_detail = str(e)[:90]
    leaked = [p for pid, p in engine.active_plans.items()
              if pid not in plans_before and p.goal_id == reachable.id]
    check("template decomposition produces NO plan for a state goal",
          templated is None and not leaked,
          f"returned={templated}, leaked_plans={len(leaked)}")
    check("that refusal is distinguishable from a generic failure",
          refused, refusal_detail)

    print("\n== E. A descriptive goal's plan is labelled, not claimed as proved ==")
    described = await engine.create_goal(
        "research the archive format", Priority.MEDIUM)
    check("a goal without state conditions is DESCRIPTIVE",
          described.goal_type is GoalType.DESCRIPTIVE, str(described.goal_type))
    out_d = await engine.plan_for_goal(described.id, {})
    check("it is planned by template, and says template",
          out_d.status is PlanningStatus.PLAN_FOUND and out_d.planning_mode == "template",
          f"{out_d.status.value} / {out_d.planning_mode}")
    templ_grounded = any(
        (t.provenance or {}).get("learned_rule_id")
        for t in (out_d.plan.tasks if out_d.plan else []))
    check("a template plan claims NO learned rule behind its steps",
          not templ_grounded, "no step claims a rule it does not have")

    print("\n== F. Known false positives (measured; fix comes after this run) ==")
    described2 = await engine.create_goal("analyze the archive format", Priority.MEDIUM)
    out_d2 = await engine.plan_for_goal(described2.id, {})
    c1 = out_d.plan.confidence if out_d.plan else None
    c2 = out_d2.plan.confidence if out_d2.plan else None
    dur1 = out_d.plan.estimated_duration if out_d.plan else None
    dur2 = out_d2.plan.estimated_duration if out_d2.plan else None
    print(f"     research plan: confidence={c1} duration={dur1}")
    print(f"     analyse  plan: confidence={c2} duration={dur2}")
    # Two earlier forms of these checks produced FALSE PASSES in the gate itself:
    # `c1 in (0.9,...)` missed 0.8999999999999999, and "duration != old constant"
    # passed on 0.0, which is the UNMEASURED sentinel rather than a measurement.
    # The property that actually matters is PROVENANCE: a plan must say where its
    # numbers came from, and must never dress an unmeasured value as evidence.
    meta1 = (out_d.plan.metadata or {}) if out_d.plan else {}
    meta2 = (out_d2.plan.metadata or {}) if out_d2.plan else {}
    csrc, dsrc = meta1.get("confidence_source"), meta1.get("duration_source")
    print(f"     provenance: confidence_source={csrc} duration_source={dsrc}")
    MEASURED_C = {"measured_tool_success_rate", "measured_overall_success_rate"}
    check("a template plan declares where its confidence came from",
          csrc in MEASURED_C | {"unmeasured"} and meta2.get("confidence_source") == csrc,
          f"confidence_source={csrc}")
    check("an UNMEASURED confidence is never presented as evidence",
          (csrc in MEASURED_C) or (csrc == "unmeasured" and c1 == 0.5),
          f"source={csrc}, confidence={c1} "
          f"(neutral 0.5 withheld both ways until earned, as operating_reliability does)")
    check("a measured confidence is a real reading, not the old 0.7+count heuristic",
          not (c1 is not None and abs(c1 - 0.9) < 1e-9),
          f"confidence={c1} from {csrc}")
    check("a template plan declares where its duration came from",
          dsrc in {"measured_tool_latency", "unmeasured"}, f"duration_source={dsrc}")
    check("an UNMEASURED duration is reported as unmeasured, not as constants",
          (dsrc == "measured_tool_latency" and dur1 > 0)
          or (dsrc == "unmeasured" and dur1 == 0.0),
          f"source={dsrc}, duration={dur1} "
          f"(was 75.0/65.0 summed from hardcoded per-task constants)")

    print("\n== G. Hierarchical planning, absorbed into the authority ==")
    # The abstraction pipeline is brought up by the reasoning authority, so bring
    # the real bridge up and re-plan — this exercises the AVAILABLE path, not just
    # the honest-absence one.
    from core.reasoning.neural_bridge import get_neural_bridge
    bridge_up = await get_neural_bridge().initialize()
    check("the reasoning authority is up (it owns the abstraction pipeline)",
          bridge_up)
    hier_goal = await engine.create_goal("research the archive format again",
                                         Priority.MEDIUM)
    out_h = await engine.plan_for_goal(hier_goal.id, {})
    h_inputs = ((out_h.plan.metadata or {}) if out_h.plan else {}).get("inputs") or {}
    h_gathered = h_inputs.get("gathered") or {}
    h_missing = {m["input"]: m["reason"] for m in (h_inputs.get("missing") or [])}
    print(f"     abstraction: {str(h_gathered.get('abstraction') or h_missing.get('abstraction'))[:150]}")
    print(f"     episodic:    {str(h_gathered.get('episodic_memory') or h_missing.get('episodic_memory'))[:150]}")
    check("a plan formed after the reasoning authority is up gathers abstraction",
          "abstraction" in h_gathered
          and h_gathered["abstraction"].get("source") == "reasoning authority",
          str(h_gathered.get("abstraction"))[:110] or h_missing.get("abstraction"))
    check("episodic memory is gathered within the abstraction's constraints",
          "episodic_memory" in h_gathered
          and isinstance(h_gathered["episodic_memory"].get("memories"), list),
          str(h_gathered.get("episodic_memory"))[:110] or h_missing.get("episodic_memory"))
    # The absorbed method must NOT bring the prose-step emitter with it.
    prose = [t.description for t in (out_h.plan.tasks if out_h.plan else [])
             if t.description.startswith(("Apply strategy:", "Based on past:"))]
    emitted_steps = any("plan_steps" in (v or {}) for v in h_gathered.values())
    check("no prose 'plan steps' are emitted (the dropped final step stays dropped)",
          not prose and not emitted_steps,
          f"prose_steps={prose}, has_plan_steps={emitted_steps}")
    EV.metric("abstraction_gathered", "abstraction" in h_gathered, "",
              h_missing.get("abstraction", ""))
    EV.metric("episodic_memory_gathered", "episodic_memory" in h_gathered, "",
              h_missing.get("episodic_memory", ""))

    print("\n== I. The proved route is recorded as the goal's intent ==")
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
    IA = get_intent_authority()
    recorded = ((out.plan.metadata or {}) if out.plan else {}).get("intent") or {}
    print(f"     plan's intent record: {recorded}")
    check("the plan records the intent it is the proved route of",
          recorded.get("recorded") is True and bool(recorded.get("intent_id")),
          str(recorded))
    held = await IA.get(SUBSTRATE_ACTOR, continuity_goal(reachable.id))
    check("the authority holds that intent, keyed to the goal",
          bool(held) and held.intent_id == recorded.get("intent_id"),
          f"id={held.intent_id[:8] if held else None} origin={held.origin_kind if held else None}")
    check("its shape carries the PROVED route — operator, rule, goal state",
          bool(held) and held.stated() and held.shape.get("rule_ids")
          and held.shape.get("domain") == DOMAIN,
          f"operator={held.operator if held else None} "
          f"rules={held.shape.get('rule_ids') if held else None} "
          f"proved={held.proved if held else None}")
    check("the goal's own words are actor-scoped content, not substrate-wide shape",
          bool(held) and held.aim == "archive the report"
          and "aim" not in held.shape,
          f"aim={held.aim if held else None!r}")
    step_refs = [(t.provenance or {}).get("intent_id")
                 for t in (out.plan.tasks if out.plan else [])]
    check("every step REFERENCES that one intent (one goal, one intent)",
          bool(step_refs) and all(r == recorded.get("intent_id") for r in step_refs),
          f"{len(step_refs)} step(s) -> {set(step_refs)}")
    # A preparatory reading has no step_index: it is not a step OF the route, so
    # numbering it as one would claim the proof covers it.
    route_steps = [t for t in (out.plan.tasks if out.plan else [])
                   if not (t.provenance or {}).get("read_path")]
    check("each step of the ROUTE still says which step of it it is",
          bool(route_steps) and all(
              isinstance((t.provenance or {}).get("step_index"), int)
              for t in route_steps),
          str([(t.provenance or {}).get("step_index") for t in route_steps]))
    # Re-planning the same goal must FIRM UP the one intent, not start a second.
    before_version = held.version if held else 0
    out2 = await engine.plan_for_goal(
        reachable.id, {"world_state": [f.to_formula() for f in world],
                       "domain_id": DOMAIN})
    again = await IA.get(SUBSTRATE_ACTOR, continuity_goal(reachable.id))
    check("re-planning the same goal firms up the SAME intent, not a second one",
          bool(again) and again.intent_id == recorded.get("intent_id")
          and again.version > before_version,
          f"id unchanged={again.intent_id == recorded.get('intent_id') if again else None}, "
          f"v{before_version} -> v{again.version if again else None}")
    EV.metric("plan_intent_id", recorded.get("intent_id"))
    EV.metric("plan_intent_operators", recorded.get("operators"), "count")

    print("\n== H. Each kind of plan declares its own inputs, from their owners ==")
    from core.agents.autonomous.planning_engine import PlanInput, PLAN_KIND_INPUTS
    state_needs = set(PLAN_KIND_INPUTS["state"])
    templ_needs = set(PLAN_KIND_INPUTS["template"])
    check("a state plan and a template plan declare DIFFERENT inputs",
          state_needs != templ_needs and state_needs and templ_needs,
          f"state={sorted(n.value for n in state_needs)} "
          f"template={sorted(n.value for n in templ_needs)}")
    check("only a state plan asks for the observed world and learned operators",
          PlanInput.OBSERVED_WORLD in state_needs
          and PlanInput.LEARNED_OPERATORS in state_needs
          and PlanInput.OBSERVED_WORLD not in templ_needs,
          "the coordinator perceives; the planner is given what it saw")

    s_inputs = ((out.plan.metadata or {}) if out.plan else {}).get("inputs") or {}
    t_inputs = ((out_d.plan.metadata or {}) if out_d.plan else {}).get("inputs") or {}
    print(f"     state    required={s_inputs.get('required')} "
          f"gathered={sorted((s_inputs.get('gathered') or {}).keys())} "
          f"missing={[m['input'] for m in (s_inputs.get('missing') or [])]}")
    print(f"     template required={t_inputs.get('required')} "
          f"gathered={sorted((t_inputs.get('gathered') or {}).keys())} "
          f"missing={[m['input'] for m in (t_inputs.get('missing') or [])]}")
    check("the state plan records the inputs it was formed on",
          s_inputs.get("kind") == "state" and bool(s_inputs.get("required")),
          f"required={s_inputs.get('required')}")
    check("the template plan records the inputs it was formed on",
          t_inputs.get("kind") == "template" and bool(t_inputs.get("required")),
          f"required={t_inputs.get('required')}")
    check("every declared input is either gathered or reported missing with a reason",
          all(
              set(d.get("required") or [])
              == set((d.get("gathered") or {}).keys())
              | {m["input"] for m in (d.get("missing") or [])}
              and all(m.get("reason") for m in (d.get("missing") or []))
              for d in (s_inputs, t_inputs)),
          f"state missing={[(m['input'], m['reason']) for m in (s_inputs.get('missing') or [])]}, "
          f"template missing={[(m['input'], m['reason']) for m in (t_inputs.get('missing') or [])]}")

    # Each gathered input must name the AUTHORITY it came from, not a store it
    # reached around. This is the check that would fail if the planner started
    # importing a global again.
    OWNERS = {
        "observed_world": "coordinator (perception)",
        "learned_operators": "rule store",
        "tool_history": "learning authority",
        "abstraction": "reasoning authority",
        "episodic_memory": "memory, within abstraction",
        "operating_reliability": "domain authority",
    }
    sourced = {name: got.get("source")
               for d in (s_inputs, t_inputs)
               for name, got in (d.get("gathered") or {}).items()}
    print(f"     sources: {sourced}")
    check("every gathered input names the authority that owns it",
          bool(sourced) and all(sourced[n] == OWNERS.get(n) for n in sourced),
          str(sourced))
    check("episodic memory is named as the memory authority names it",
          PlanInput.EPISODIC_MEMORY.value == "episodic_memory",
          "MemoryType.EPISODIC — not an invented term")
    EV.metric("state_plan_inputs", s_inputs.get("required"))
    EV.metric("template_plan_inputs", t_inputs.get("required"))
    EV.metric("input_sources", sourced)

    reliability = await (__import__(
        "core.integration.universal_domain_master", fromlist=["x"]
    ).get_universal_domain_master().operating_reliability(DOMAIN))
    EV.metric("earned_operating_reliability", reliability.get("earned"), "fraction",
              f"the honest signal a plan's confidence should read "
              f"(attempts={reliability.get('attempts')}, "
              f"enough_history={reliability.get('enough_history')})")
    EV.metric("template_plan_confidence", c1, "fraction", "currently invented")
    EV.metric("template_plan_duration", dur1, "minutes", "currently constants")
    EV.metric("state_plan_confidence", out.plan.confidence if out.plan else None,
              "fraction", "proved, not estimated")

    # Ask the SERVER which database this actually ran against, rather than
    # letting the record say the database was 'not recorded'.
    # Self-cleaning: this run recorded a real intent for its throwaway goal.
    # Remove both halves so repeated runs do not accumulate intents for goals
    # that no longer exist.
    if recorded.get("intent_id"):
        await IA.store._ready()
        await IA.store.db.execute_query(
            "DELETE FROM unified.scoped_intents WHERE intent_id = $1",
            (recorded["intent_id"],), commit=True)
        await IA.store.db.execute_query(
            "DELETE FROM unified.intents WHERE intent_id = $1",
            (recorded["intent_id"],), commit=True)

    await EV.verify_database()
    EV.write()
    shutil.rmtree(root, ignore_errors=True)
    print("\n" + "=" * 62)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
