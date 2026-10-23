#!/usr/bin/env python3
"""PLANNING-01 — one owner for each kind of plan, and every planning step verified honest.

A goal stated over world state is planned by search: temporal reasoning's
`plan_state_goal`, asked by the drive through `_plan_route`, which records the
proved route on the pursuit's intent. A goal stated in words is decomposed into
the work it names by the execution plan adapter (`plan_described_goal`). There
is no planning engine beside them holding goals and plans of its own. This
checks that claim and, for each planning path, that what it reports is TRUE — a
plan it calls proved really is proved, and a failure is reported as a failure
rather than quietly becoming a plausible-looking plan.

Against the real substrate: real coordinator, real rule store, real learned
operators, real Postgres. Nothing mocked.

  A  ONE OWNER EACH     a state goal is planned by temporal reasoning, a goal in
                        words by the adapter, and no engine is held beside them
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

# THE SANDBOX, NEVER THE MODEL. Unset, the store is `lyric_db`, the main model,
# which holds only what it was taught; a run of this writes intents, rules and
# demonstrations. `lyric_dev` unless the run names a database itself.
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")

PASS = FAIL = 0
EV = RunRecord(
    "PLANNING-01",
    claim="Each kind of plan has exactly one owner, and every planning "
          "path reports honestly: a proved plan is really proved, an unreachable "
          "goal yields no plan, and a template plan is never presented as proved.",
    hypothesis="If planning is routed by goal type to the one owner of each kind, then a "
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
    from core.agents.autonomous.execution_plan_adapter import (
        PLAN_KIND_INPUTS, PlanInput, plan_described_goal)
    from core.agents.autonomous.shared_types import Goal, Priority, Task, TaskType
    from core.perception.perception_faculty import observe_world
    from core.learning.exploration import take_up_workspace
    from core.perception.perception_faculty import sensed_fact, term
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

    print("\n== A. One owner for each kind of plan ==")
    coord = AutonomousCoordinator()
    try:
        __import__("core.agents.autonomous.planning_engine")
        engine_gone = False
    except ModuleNotFoundError:
        engine_gone = True
    check("no planning engine is held beside the owners",
          engine_gone and not hasattr(coord, "planning"),
          f"module gone={engine_gone}, attribute={hasattr(coord, 'planning')}")

    def words(text):
        return Goal(id=uuid.uuid4().hex, description=text, priority=Priority.MEDIUM)

    print("\n== B. True positive: a state goal with a real operator route ==")
    # The workspace is handed over; the substrate looks at it with its own
    # perception, and what is there becomes the world it plans in.
    take_up_workspace(DOMAIN, str(root))
    rules = await get_rule_store().executable_rules(domain_id=DOMAIN)
    check("the domain offers a learned, executable operator", bool(rules),
          f"{len(rules)} executable rule(s) in {DOMAIN}")
    world = observe_world(DOMAIN) or frozenset()
    report = root / "inbox" / "report.txt"
    # "Archive the report", in perception's words: the report is a file in
    # archive, and is no longer one in the inbox.
    archived = [
        sensed_fact("kind", "path", str(root / "archive" / "report.txt"),
                    "file").to_formula(),
        "¬" + sensed_fact("kind", "path", str(report), "file").to_formula()]
    pursuit = Task(id=f"planning01_{uuid.uuid4().hex[:8]}", type=TaskType.EXECUTION,
                   description="archive the report", priority=Priority.MEDIUM)
    out, route = await coord._plan_route(
        pursuit, archived, [f.to_formula() for f in world], DOMAIN)
    check("it plans, by search, and says so",
          out.status is PlanningStatus.PLAN_FOUND and route is not None
          and route.metadata.get("planning_mode") == "state",
          f"{out.status.value} — {out.reason}")
    # A proved route may also carry PREPARATORY READINGS: Law 2 refuses an act on
    # a file the substrate has no current account of, and the answer the law gives
    # is "read it first", which is a planning step. Those steps declare themselves
    # (`read_path`) and are deliberately NOT grounded operators — they are not part
    # of what was proved, they are what the law requires before it may be run.
    plan_tasks = list(route.tasks if route else [])
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
          str([(t.provenance or {}).get("grounded_operator") for t in plan_tasks]))
    check("a proved plan states full confidence because it is proved, not estimated",
          bool(route) and route.confidence == 1.0,
          f"confidence={route.confidence if route else None}")

    print("\n== C. No false positive: a state goal with no route ==")
    # ENCRYPTED is in no learned operator's effects — nothing can reach it.
    out_u, route_u = await coord._plan_route(
        Task(id=f"planning01_{uuid.uuid4().hex[:8]}", type=TaskType.EXECUTION,
             description="encrypt the report"),
        [Fact("ENCRYPTED", (term("path", str(report)),)).to_formula()],
        [f.to_formula() for f in world], DOMAIN)
    check("an unreachable state goal does NOT produce a plan",
          out_u.status is not PlanningStatus.PLAN_FOUND and route_u is None,
          f"{out_u.status.value}, route={route_u}")
    check("it reports WHY, as a state verdict — never as a template plan",
          out_u.status in (PlanningStatus.UNREACHABLE, PlanningStatus.INDETERMINATE)
          and bool(out_u.reason),
          f"{out_u.status.value} — {out_u.reason}")

    print("\n== D. The guard: a state goal can never be templated ==")
    refused, templated = False, None
    refusal_detail = "the decomposition accepted a STATE goal"
    try:
        templated = await plan_described_goal(Goal(
            id=pursuit.id, description=pursuit.description, priority=Priority.MEDIUM,
            state_conditions=archived))
    except ValueError as e:
        refused = True
        refusal_detail = str(e)[:90]
    check("template decomposition produces NO plan for a state goal",
          templated is None, f"returned={templated}")
    check("that refusal is distinguishable from a generic failure",
          refused, refusal_detail)

    print("\n== E. A goal in words is decomposed, labelled, not claimed as proved ==")
    steps_d, claims_d = await plan_described_goal(words("research the archive format"))
    check("it is decomposed by template, and says template",
          bool(steps_d) and claims_d.get("planning_mode") == "template",
          f"{len(steps_d)} step(s) / {claims_d.get('planning_mode')}")
    templ_grounded = any((t.provenance or {}).get("learned_rule_id") for t in steps_d)
    check("a template plan claims NO learned rule behind its steps",
          not templ_grounded, "no step claims a rule it does not have")

    print("\n== F. What a template plan claims about itself is measured ==")
    steps_d2, claims_d2 = await plan_described_goal(words("analyze the archive format"))
    c1, c2 = claims_d.get("confidence"), claims_d2.get("confidence")
    dur1, dur2 = claims_d.get("estimated_duration"), claims_d2.get("estimated_duration")
    print(f"     research plan: confidence={c1} duration={dur1}")
    print(f"     analyse  plan: confidence={c2} duration={dur2}")
    # Two earlier forms of these checks produced FALSE PASSES in the gate itself:
    # `c1 in (0.9,...)` missed 0.8999999999999999, and "duration != old constant"
    # passed on 0.0, which is the UNMEASURED sentinel rather than a measurement.
    # The property that actually matters is PROVENANCE: a plan must say where its
    # numbers came from, and must never dress an unmeasured value as evidence.
    csrc, dsrc = claims_d.get("confidence_source"), claims_d.get("duration_source")
    print(f"     provenance: confidence_source={csrc} duration_source={dsrc}")
    MEASURED_C = {"measured_tool_success_rate", "measured_overall_success_rate"}
    check("a template plan declares where its confidence came from",
          csrc in MEASURED_C | {"unmeasured"} and claims_d2.get("confidence_source") == csrc,
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

    print("\n== G. Hierarchical planning, where a goal in words is decomposed ==")
    # The abstraction pipeline is brought up by the reasoning authority, so bring
    # the real bridge up and decompose again — this exercises the AVAILABLE path,
    # not just the honest-absence one.
    from core.reasoning.neural_bridge import get_neural_bridge
    bridge_up = await get_neural_bridge().initialize()
    check("the reasoning authority is up (it owns the abstraction pipeline)",
          bridge_up)
    steps_h, claims_h = await plan_described_goal(words("research the archive format again"))
    h_inputs = claims_h.get("inputs") or {}
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
    prose = [t.description for t in steps_h
             if t.description.startswith(("Apply strategy:", "Based on past:"))]
    emitted_steps = any("plan_steps" in (v or {}) for v in h_gathered.values())
    check("no prose 'plan steps' are emitted (the dropped final step stays dropped)",
          not prose and not emitted_steps,
          f"prose_steps={prose}, has_plan_steps={emitted_steps}")
    EV.metric("abstraction_gathered", "abstraction" in h_gathered, "",
              h_missing.get("abstraction", ""))
    EV.metric("episodic_memory_gathered", "episodic_memory" in h_gathered, "",
              h_missing.get("episodic_memory", ""))

    print("\n== I. The proved route is recorded as the pursuit's intent ==")
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
    IA = get_intent_authority()
    recorded = ((route.metadata or {}) if route else {}).get("intent") or {}
    print(f"     route's intent record: {recorded}")
    check("the route records the intent it is the proved route of",
          recorded.get("recorded") is True and bool(recorded.get("intent_id")),
          str(recorded))
    held = await IA.get(SUBSTRATE_ACTOR, continuity_goal(f"{pursuit.id}:route"))
    check("the authority holds that intent, keyed to the pursuit",
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
    step_refs = [(t.provenance or {}).get("intent_id") for t in plan_tasks]
    check("every step REFERENCES that one intent (one goal, one intent)",
          bool(step_refs) and all(r == recorded.get("intent_id") for r in step_refs),
          f"{len(step_refs)} step(s) -> {set(step_refs)}")
    # A preparatory reading has no step_index: it is not a step OF the route, so
    # numbering it as one would claim the proof covers it.
    check("each step of the ROUTE still says which step of it it is",
          bool(operator_steps) and all(
              isinstance((t.provenance or {}).get("step_index"), int)
              for t in operator_steps),
          str([(t.provenance or {}).get("step_index") for t in operator_steps]))
    # Planning the same pursuit again must FIRM UP the one intent, not start a second.
    before_version = held.version if held else 0
    await coord._plan_route(pursuit, archived, [f.to_formula() for f in world], DOMAIN)
    again = await IA.get(SUBSTRATE_ACTOR, continuity_goal(f"{pursuit.id}:route"))
    check("planning the same pursuit again firms up the SAME intent, not a second one",
          bool(again) and again.intent_id == recorded.get("intent_id")
          and again.version > before_version,
          f"id unchanged={again.intent_id == recorded.get('intent_id') if again else None}, "
          f"v{before_version} -> v{again.version if again else None}")
    EV.metric("plan_intent_id", recorded.get("intent_id"))
    EV.metric("plan_intent_operators", recorded.get("operators"), "count")

    print("\n== H. Each kind of plan declares its own inputs, from their owners ==")
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

    s_inputs = ((route.metadata or {}) if route else {}).get("inputs") or {}
    t_inputs = claims_d.get("inputs") or {}
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
    EV.metric("template_plan_confidence", c1, "fraction", claims_d.get("confidence_source"))
    EV.metric("template_plan_duration", dur1, "minutes", claims_d.get("duration_source"))
    EV.metric("state_plan_confidence", route.confidence if route else None,
              "fraction", "proved, not estimated")

    # Ask the SERVER which database this actually ran against, rather than
    # letting the record say the database was 'not recorded'.
    # Self-cleaning: this run recorded a real intent for its throwaway pursuit.
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
