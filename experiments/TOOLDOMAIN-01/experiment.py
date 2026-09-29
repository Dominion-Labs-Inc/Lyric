#!/usr/bin/env python3
"""TOOLDOMAIN-01 — the substrate learns what an act DOES, from doing it.

THE GAP THIS MEASURES. `_execute_via_substrate` observes the world before an
act, acts, re-observes, and files the before/action/after triple induction needs
-- but only after finding a VALIDATED learned rule, in a declared domain, with a
registered binding. You need an operator to record the demonstration that would
teach you an operator. Everything else the substrate does went through
`_run_tool`, which appraised the act, believed it and metered it, and observed
nothing about the world at all.

So the substrate's DID/SAW evidence -- a real intervention and a fresh
post-intervention reading -- was spent entirely on judging whether a goal had
been reached, and never on learning what the action does. That is how 898,593
knowledge items came to sit beside 14 operators, 8 of them the same file move
relearned in 8 sandboxes.

WHAT IS DERIVED AND WHAT IS DECLARED. Nothing here names a directory, a domain,
a vocabulary or a tool list. The frame around an act comes from the act's own
arguments; which observations can be pointed at them comes from what tools
declare about themselves; and which of those observations belong in the frame is
read back from the demonstrations the substrate has already filed. Point it at a
SOC and the act names a host or an address instead -- the derivation cannot tell
the difference, which is the claim being tested.
"""
import asyncio
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_dev", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CHECKS = []
EV = None


def _record():
    """This run's record, made once the repository is importable."""
    global EV
    if EV is None:
        from experiments._evidence import RunRecord
        EV = RunRecord('TOOLDOMAIN-01',
                       claim="The substrate learns what an act does from doing it, with nothing written by hand: the act names its domain, practice in a sandbox it is given teaches the operator, and ordinary work files demonstrations read through the self's own perception.",
                       hypothesis='If domains, operators and observations are derived from the act and the tools, then a sandbox needs only to be named for an executable operator to be induced from practice, and ordinary acts file before/after demonstrations.')
    return EV


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    _record().check(name, bool(passed), str(detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main():
    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    from core.agents.autonomous.runtime_registry import get_autonomous_coordinator
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    from core.execution import tool_domain as TD
    from core.learning.demonstration_store import get_demonstration_store
    from core.reasoning.intent_authority import (
        SUBSTRATE_ACTOR, continuity_goal, get_intent_authority)

    check("the registry names the LIVE substrate",
          get_autonomous_coordinator() is coordinator)

    demos = get_demonstration_store()
    root = Path(tempfile.mkdtemp(prefix="tooldomain01_"))
    (root / "inbox").mkdir()
    (root / "archive").mkdir()

    # ── A. the derivation, from the registry alone ───────────────────────────
    print("\n== A. What the substrate can see and act on, derived from tools ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        index = TD.observer_index()
    check("an observation index is derived with no domain declared",
          len(index) > 1, f"{len(index)} kind(s), e.g. "
          f"{sorted(index)[:6]}")
    check("`path` is one kind among many — not a special case in the code",
          len(index.get("path", ())) > 1 and len(index) > 5,
          f"path has {len(index.get('path', ()))} observers; "
          f"other kinds: {sorted(set(index) - {'path'})[:8]}")

    probe = root / "inbox" / "probe.txt"
    probe.write_text("x\n")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        not_an_act = await TD.ActFrame.open("read_file", {"file_path": str(probe)})
        nothing_to_see = await TD.ActFrame.open("web_search", {"query": "anything"})
    check("an INVESTIGATION is not watched — it has no effect to learn",
          not_an_act is None)
    check("an act naming nothing observable is not watched, not guessed at",
          nothing_to_see is None)

    # ── B. meeting a domain is how it becomes one ────────────────────────────
    print("\n== B. It BINDS an operator by meeting one — nothing declared ==")
    from core.execution.operator_binding import get_binding_registry

    scratch = root / "inbox" / "encounter.txt"
    scratch.write_text("met you\n")
    before_binding = get_binding_registry().get("tools:path", "MOVE_FILE")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        met = TD.encounter("move_file", {"source_path": str(scratch),
                                         "destination_path": str(root / "archive" / "e.txt")})
    after_binding = get_binding_registry().get("tools:path", "MOVE_FILE")
    check("the act's own arguments name the domain — no workspace_root declared",
          met == "tools:path", f"domain={met!r}")
    check("and MOVE_FILE becomes a bound operator of it",
          after_binding is not None,
          f"{before_binding is not None} -> {after_binding is not None}; "
          f"tool={getattr(after_binding, 'tool_name', None)}")
    world = TD.world_of("tools:path")
    check("its world is the resources it has MET, not a directory someone named",
          bool(world.resources.get("path")),
          f"{len(world.resources.get('path', ()))} path(s) encountered")
    check("practising is NOT armed by meeting — asking and practising differ",
          __import__("core.learning.exploration", fromlist=["get_proposer"])
          .get_proposer("tools:path") is None)

    # ── C. given a domain it may practise in, it learns the operator ─────────
    print("\n== C. In a sandbox it is ALLOWED to practise in, it learns ==")
    from core.learning.exploration import SubstrateExplorer, get_proposer
    from core.learning.rule_store import get_rule_store

    SANDBOX = f"td01_sandbox_{uuid4().hex[:8]}"
    for i in range(3):
        (root / "inbox" / f"s{i}.txt").write_text(f"sandbox {i}\n")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        derived = TD.derive_domain(
            SANDBOX,
            observations=[("list_directory", {"directory_path": str(root / "inbox")}),
                          ("list_directory", {"directory_path": str(root / "archive")})],
            actions=["move_file"])
    check("the sandbox is actable and observable, derived from the tools",
          derived.get("actable") and derived.get("observable"),
          f"operators={derived.get('operators')} refused={len(derived.get('refused') or [])}")

    store = get_rule_store()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        acted = 0
        for _ in range(6):
            cycle = await SubstrateExplorer().explore(
                SANDBOX, get_proposer(SANDBOX), max_actions=6, reinduce=True)
            acted += cycle.get("acted", 0) or 0
            if await store.executable_rules(domain_id=SANDBOX):
                break
    executable = await store.executable_rules(domain_id=SANDBOX)
    check("it practised — real acts, in the real world",
          acted > 0, f"{acted} action(s)")
    check("and INDUCED an executable operator from what happened",
          bool(executable),
          f"{[(r.rule_id[:12], r.status.value) for r in await store.load(domain_id=SANDBOX)][:4]}")

    # ── D. ordinary work now files demonstrations ────────────────────────────
    print("\n== D. ORDINARY WORK now teaches it — this was the gap ==")
    before_rows = await demos.load(domain_id="tools:path",
                                   predicate="MOVE_FILE", arity=2)
    moved = []
    if executable:
        rule = executable[0]
        for i in range(3):
            src = root / "inbox" / f"work{i}.txt"
            src.write_text(f"real work {i}\n")
            dst = root / "archive" / f"work{i}.txt"
            op = f"MOVE_FILE({src}, {dst})"
            intent = await get_intent_authority().form(
                "goal", SUBSTRATE_ACTOR,
                continuity_goal(f"tooldomain01:{uuid4().hex}"),
                shape={"proved": True, "operator": op, "operators": [op],
                       "steps": 1, "domain": "tools:path",
                       "rule_ids": [rule.rule_id],
                       "goal_conditions": [f"AT({src}, {dst})"]})
            task = Task(
                id=f"td01_work{i}", type=TaskType.EXECUTION, description=op,
                priority=Priority.MEDIUM,
                metadata={"parameters": {"tool_plan": [
                    {"tool": "move_file",
                     "args": {"source_path": str(src),
                              "destination_path": str(dst)}}]}},
                provenance={"intent_id": getattr(intent, "intent_id", None),
                            "domain_id": "tools:path"})
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                result = await coordinator.execute_task(task)
            moved.append(dst.exists())
            print(f"    act {i}: success={None if result is None else result.get('success')} "
                  f"landed={dst.exists()}")
    check("the acts really happened in the real world",
          bool(moved) and all(moved), f"{sum(1 for m in moved if m)}/{len(moved)} moved")

    after_rows = await demos.load(domain_id="tools:path",
                                  predicate="MOVE_FILE", arity=2)
    gained = len(after_rows) - len(before_rows)
    check("ordinary work FILED DEMONSTRATIONS — the seam that was missing",
          gained > 0, f"{len(before_rows)} -> {len(after_rows)}")
    fresh = after_rows[len(before_rows):] if gained > 0 else []
    check("each carries a world read BEFORE and AFTER, and they DIFFER",
          bool(fresh) and all(e.before and e.after and set(e.before) != set(e.after)
                              for e in fresh),
          "; ".join(f"before={len(e.before)} after={len(e.after)} "
                    f"moved={len(set(e.before) ^ set(e.after))}" for e in fresh[:3]))

    # ── E. a refusal is not evidence ─────────────────────────────────────────
    print("\n== E. A refused act teaches nothing — it never ran ==")
    stray = root / "inbox" / "unaccounted.txt"
    stray.write_text("no account for this\n")
    unaccounted = Task(
        id="td01_refused", type=TaskType.EXECUTION, description="move it anyway",
        priority=Priority.MEDIUM,
        metadata={"parameters": {"tool_plan": [
            {"tool": "move_file", "args": {
                "source_path": str(stray),
                "destination_path": str(root / "archive" / "unaccounted.txt")}}]}},
        provenance={"domain_id": "tools:path"})   # no intent: nothing explains it
    pre = len(await demos.load(domain_id="tools:path", predicate="MOVE_FILE", arity=2))
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        refused = await coordinator.execute_task(unaccounted)
    post = len(await demos.load(domain_id="tools:path", predicate="MOVE_FILE", arity=2))
    check("the unaccounted act was refused",
          refused is not None and refused.get("success") is not True
          and not (root / "archive" / "unaccounted.txt").exists())
    check("and NOTHING was filed from it — a refusal is not a negative result",
          post == pre, f"{pre} -> {post}")

    # ── F. the frame narrows itself from its own evidence ────────────────────
    print("\n== F. The frame is learned, not chosen ==")
    TD._DISCRIMINATING.clear()
    discriminating = await TD.discriminating_predicates("tools:path", "MOVE_FILE", 2)
    check("it knows which observations this operator MOVES",
          bool(discriminating),
          f"{len(discriminating)}: {sorted(discriminating)[:6]}")
    wide = len(index.get("path", ())) * 2
    narrowing = root / "inbox" / "narrowed.txt"
    narrowing.write_text("narrow me\n")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        narrowed_frame = await TD.ActFrame.open(
            "move_file", {"source_path": str(narrowing),
                          "destination_path": str(root / "archive" / "narrowed.txt")})
    narrow = len(narrowed_frame._readings) if narrowed_frame else 0
    check("so it stops reading what this operator never moves",
          0 < narrow < wide, f"{wide} pointable readings -> {narrow} kept")

    # ── G. restart survival: the evidence IS the calibration ─────────────────
    print("\n== G. It survives a restart — the evidence is the calibration ==")
    TD._DISCRIMINATING.clear()
    TD._OBSERVER_PREDICATES.clear()
    TD._OBSERVER_WARM.clear()
    reread = await TD.discriminating_predicates("tools:path", "MOVE_FILE", 2)
    check("with every in-process cache dropped, it is re-derived from the store",
          reread == discriminating and bool(reread),
          f"{len(reread)} predicate(s) recovered from unified.operator_demonstrations")

    shutil.rmtree(root, ignore_errors=True)
    # This run's own sandbox domain, removed by its id: what it learned there
    # was for this run, and the next run makes a new one.
    from experiments._domains import forget_domain
    await forget_domain(SANDBOX)

    passed = sum(1 for c in CHECKS if c["passed"])
    print(f"\n{passed}/{len(CHECKS)} checks passed")
    await _record().verify_database()
    print(f"run record: {_record().write()}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
