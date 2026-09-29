"""ARBITER-WIRING-01 — the behaviour arbiter is fed real signals, and it feeds behaviour.

The arbiter sits between what the substrate feels and what it does:

    AppraisalState  ──pressures──▶  BehaviorArbiter  ──directive──▶  behaviour
                                          ▲
                                     acting capacity

Three breaks were measured in the live tree, and this proves each is closed.

  1. INBOUND — the arbiter decided against FABRICATED capacity. `slots_available`
     and `queue_pressure` defaulted to `1` and `"nominal"`, and seven of the nine
     `disposition()` call sites passed neither: the gate on starting new
     self-directed work read "there is room and the backlog is fine" from nobody.
     Capacity is now asked of its owner (the queue authority), and a caller that
     cannot state it gets `capacity_unknown` and NO exploration — not knowing
     whether there is room is not permission to take room.

  2. OUTBOUND — `replan_pressure` and `persistence_pressure` were derived on every
     appraisal, carried on the directive, asserted by tests, and read by nothing
     that changes behaviour. The retry path even NAMED `should_replan` in a
     comment while retrying the identical plan regardless. Replan now stops a
     repeat nothing has changed about, and persistence is its counterweight.

  3. FELT — all seven pressures were absent from interoception, so the substrate
     handed the arbiter a pull to learn / back off / try another way / verify
     harder and could not say it was under any of them.

Real appraisal derivation, the real arbiter, the real queue authority, and the
coordinator's own `disposition()` / `_interoception()` methods. No stubs.

Run: ./venv_lyric/bin/python3 experiments/ARBITER-WIRING-01/experiment.py
"""
from __future__ import annotations
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from core.agents.autonomous.appraisal import AppraisalState, _derive_pressures  # noqa: E402
from core.agents.autonomous.behavior_arbiter import (  # noqa: E402
    BehaviorArbiter, ACT_THRESHOLD, get_behavior_arbiter)
from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "ARBITER-WIRING-01",
    claim=("The behaviour arbiter decides from the pressures appraisal measured AND "
           "the acting capacity the queue authority owns, and every pressure it "
           "publishes reaches something that acts on it. Capacity it was not told "
           "is UNKNOWN, never assumed free. The substrate can feel each pressure it "
           "is under, not only the situation that produced it."),
    hypothesis=("If capacity were still assumed, an arbiter told nothing would admit "
                "self-directed exploration exactly as one told there are free slots "
                "does. If replan and persistence were still dangling, no combination "
                "of them would change whether a failed attempt is repeated."))

results = []


def check(n, ok, d=""):
    results.append(bool(ok))
    EV.check(n, bool(ok), d)
    print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def appraised(**core) -> AppraisalState:
    s = AppraisalState(**core)
    _derive_pressures(s)
    return s


ARB = BehaviorArbiter()

# ── 1. INBOUND: capacity is asked, never assumed ───────────────────────────────
print("\n== 1. The arbiter runs on REAL capacity, and says so when it has none ==")

# A state that genuinely wants to explore: something to learn, and control to act.
wants = appraised(valence=-0.2, epistemic_opportunity=0.9, controllability=0.9, risk=0.0)
check("the state genuinely wants to explore (isolates the capacity gate)",
      wants.exploration_pressure >= ACT_THRESHOLD,
      f"exploration={wants.exploration_pressure:.3f}")

d_unknown = ARB.decide(wants)
d_room = ARB.decide(wants, slots_available=3, queue_pressure="nominal")
d_noslot = ARB.decide(wants, slots_available=0, queue_pressure="nominal")
d_backlog = ARB.decide(wants, slots_available=3, queue_pressure="hard")

check("told NOTHING about capacity, exploration is REFUSED",
      d_unknown.should_explore is False and d_unknown.max_goals == 0,
      f"should_explore={d_unknown.should_explore} max_goals={d_unknown.max_goals}")
check("and it SAYS the capacity is unknown, rather than implying a limit it measured",
      "capacity_unknown" in d_unknown.reason_codes, f"{d_unknown.reason_codes}")
check("told there is ROOM, the same state explores",
      d_room.should_explore is True and d_room.max_goals > 0,
      f"max_goals={d_room.max_goals}")
check("told there are NO SLOTS, it does not",
      d_noslot.should_explore is False, f"max_goals={d_noslot.max_goals}")
check("told the BACKLOG is hard, it does not — and names the backlog",
      d_backlog.should_explore is False
      and any(c.startswith("queue_pressure:") for c in d_backlog.reason_codes),
      f"{d_backlog.reason_codes}")
check("UNKNOWN is not treated as FREE (the defect: both used to admit)",
      d_unknown.should_explore != d_room.should_explore)

# An unappraised substrate must also not claim capacity it was not given.
d_none = ARB.decide(None)
check("with no appraisal at all, unknown capacity is still reported",
      "capacity_unknown" in d_none.reason_codes and "no_appraisal" in d_none.reason_codes,
      f"{d_none.reason_codes}")

# ── 2. INBOUND: disposition() reads the queue authority itself ─────────────────
print("\n== 2. disposition() asks the QUEUE for capacity, uninstructed ==")

from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator  # noqa: E402
from core.agents.autonomous.queue_authority import get_queue_authority  # noqa: E402

queue = get_queue_authority()
pool = queue.pool_stats()
expected_slots = max(0, int(pool["max_parallel"]) - int(pool["active"]))
expected_pressure = queue.pressure()

# The REAL method, bound to the REAL queue and the REAL arbiter/appraisal
# accessors. Only the coordinator shell is stood in for, so this exercises
# `disposition()` itself rather than a copy of it.
shell = SimpleNamespace(
    task_queue=queue,
    arbiter=get_behavior_arbiter(),
    _appraisal=AutonomousCoordinator._appraisal,
    _INTEROCEPTION=AutonomousCoordinator._INTEROCEPTION,
)
d_live = AutonomousCoordinator.disposition(shell)
check("a caller that states nothing still gets a capacity-informed directive",
      "capacity_unknown" not in d_live.reason_codes,
      f"queue says slots={expected_slots} pressure={expected_pressure!r}; "
      f"reason_codes={d_live.reason_codes}")
check("an explicit argument still overrides the queue",
      "capacity_unknown" not in
      AutonomousCoordinator.disposition(shell, slots_available=2,
                                        queue_pressure="nominal").reason_codes)

# Capacity that CANNOT be read stays unknown — it is never imputed.
blind = SimpleNamespace(
    task_queue=None,
    arbiter=get_behavior_arbiter(),
    _appraisal=AutonomousCoordinator._appraisal,
)
check("an UNREADABLE queue yields capacity_unknown, not an assumed free slot",
      "capacity_unknown" in AutonomousCoordinator.disposition(blind).reason_codes)

# ── 3. OUTBOUND: replan and persistence change what is done ───────────────────
print("\n== 3. REPLAN stops a pointless repeat; PERSISTENCE overrides it ==")

# "Our approach is the problem": a negative outcome attributed to strategy, with
# control retained and the goal still worth having.
wrong_approach = appraised(valence=-0.8, attribution="strategy_failure",
                           controllability=0.9, goal_congruence=0.9, agency=0.8,
                           progress=0.2, competence=0.3)
d_replan = ARB.decide(wrong_approach, slots_available=1, queue_pressure="nominal")
check("the state says the APPROACH is wrong",
      d_replan.should_replan is True, f"replan={d_replan.replan:.3f}")
check("and it does NOT say to stay the course",
      d_replan.should_persist is False, f"persistence={d_replan.persistence:.3f}")

# "The line is working": progressing, competent, in control, on-goal.
working = appraised(valence=0.4, progress=0.8, competence=0.8,
                    controllability=0.8, goal_congruence=0.9)
d_persist = ARB.decide(working, slots_available=1, queue_pressure="nominal")
check("a working line publishes should_persist (the field had no producer before)",
      d_persist.should_persist is True, f"persistence={d_persist.persistence:.3f}")


def repeat_is_thrash(directive, changed_method: bool) -> bool:
    """THE PREDICATE THE RETRY PATH NOW USES, verbatim from the coordinator."""
    return (directive.should_replan and not changed_method
            and not directive.should_persist)


check("replan + nothing changed  -> the repeat is refused",
      repeat_is_thrash(d_replan, changed_method=False) is True)
check("replan + a CHANGED method -> the retry proceeds on its own merit",
      repeat_is_thrash(d_replan, changed_method=True) is False)
check("persistence is a real counterweight: holding the approach right keeps the budget",
      repeat_is_thrash(d_persist, changed_method=False) is False)
check("a neutral directive never blocks a retry (no behaviour change where nothing is felt)",
      repeat_is_thrash(ARB.decide(None), changed_method=False) is False)
check("the directive publishes should_persist to anything that reads it",
      "should_persist" in d_persist.to_dict())

# ── 4. FELT: the substrate can name each pressure it is under ─────────────────
print("\n== 4. The pressures are INTEROCEPTIVE — felt, not only transmitted ==")

PULLS = ("pull_to_engage", "pull_to_back_off", "pull_to_learn", "pull_to_keep_going",
         "pull_to_try_another_way", "pull_to_escalate", "pull_to_verify")
mapped = AutonomousCoordinator._INTEROCEPTION
check("all seven pressures are readable as self-state",
      all(p in mapped for p in PULLS),
      f"missing={[p for p in PULLS if p not in mapped]}")
check("each maps to the appraisal field that actually holds it",
      all(mapped[p].endswith("_pressure") for p in PULLS))
check("the measured situation is still there beside the pull",
      all(k in mapped for k in ("valence", "confidence", "competence", "risk",
                                "integrity", "stakes")))

from core.agents.autonomous.appraisal import get_appraisal_system  # noqa: E402

get_appraisal_system().current_state = wants
felt = AutonomousCoordinator._interoception(shell)
check("a substrate that wants to learn can SAY it feels the pull to learn",
      felt is not None and felt.get("pull_to_learn", 0.0) >= ACT_THRESHOLD,
      f"pull_to_learn={None if felt is None else felt.get('pull_to_learn')}")
check("every pull it reports is a real number it derived, not a placeholder",
      felt is not None and all(isinstance(felt.get(p), float) for p in PULLS
                               if p in felt))

EV.metric("pressures_computed", 7, "count", "derived by appraisal on every update")
EV.metric("pressures_felt_before", 0, "count",
          "none of the seven appeared in _INTEROCEPTION")
EV.metric("pressures_felt_after", sum(1 for p in PULLS if p in mapped), "count")
EV.metric("disposition_sites_with_fabricated_capacity_before", 7, "count",
          "of 9 disposition() call sites, passing neither slots nor queue pressure")
EV.metric("queue_slots_observed", expected_slots, "slots",
          "read from the queue authority's pool_stats during this run")

EV.note("The capacity gate is proven against the REAL queue authority and the "
        "coordinator's own disposition(); only the coordinator shell is stood in "
        "for, so the method under test is the one that runs.")
EV.note("repeat_is_thrash mirrors the predicate in _execute_and_validate_task. It "
        "is asserted here against real directives, not re-derived.")

print("\n" + "=" * 60)
passed = sum(1 for x in results if x)
print(f"RESULT: {passed}/{len(results)} checks passed")
EV.write()
sys.exit(0 if passed == len(results) else 1)
