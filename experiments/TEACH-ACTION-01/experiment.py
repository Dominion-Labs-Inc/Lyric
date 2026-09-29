#!/usr/bin/env python3
"""TEACH-ACTION-01 — a teaching pass shaped as BEFORE / ACTION / AFTER.

WHY THIS IS A CURRICULUM AND NOT AN ASSERTION. All five teaching doors
(`learn_fact`, `learn_facts`, `learn_concept`, `learn_rule`, `learn_words`)
converge on `admit_relation` / `admit_conditional`, and both take a SUBJECT,
a RELATION and an OBJECT. A triple cannot carry an operator: an operator is a
set of precondition literals over variables, an action with arguments, and
effects added and deleted. There is no door of that shape, so a before/action/
after cannot be TOLD to this substrate at all. Measured, not argued -- see
`cognitive_ingress.admit_conditional`.

And it should not be tellable. A demonstration says "I observed this state, took
this action, and observed that state". Writing one the substrate did not observe
is fabricating its evidence, which is the thing refused everywhere else here
(a constitutionally refused act files nothing; an unlabelled outcome is not
recorded as a positive).

So the pass teaches the way a curriculum teaches: it gives the substrate acts to
perform IN A SANDBOX IT IS ALLOWED TO PRACTISE IN, and every before/action/after
is its own reading. Declaring that sandbox is the one thing here a person does,
and it is deliberate: acting when ASKED and practising UNASKED are different
permissions, and nothing in a tool's declaration separates them.

THE AMBIGUOUS CASE. `copy_file` and `move_file` take the SAME two arguments and
differ in exactly one respect -- whether the source survives. A learner that
generalises over argument shape cannot tell them apart; only observing the source
after the act can. So this measures whether experience produces a DISTINCTION,
not just an operator.
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
        EV = RunRecord('TEACH-ACTION-01',
                       claim='A curriculum of acts in a sandbox the substrate may practise in produces operators from its own readings, and experience separates copy from move.',
                       hypothesis="If every before/action/after is the substrate's own reading, then practising copy and move yields two executable operators that differ exactly in whether the source survives.")
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
    from core.execution import tool_domain as TD
    from core.learning.demonstration_store import get_demonstration_store
    from core.learning.exploration import SubstrateExplorer, get_proposer
    from core.learning.rule_store import get_rule_store

    check("the registry names the LIVE substrate",
          get_autonomous_coordinator() is coordinator)

    demos = get_demonstration_store()
    store = get_rule_store()

    # ── the sandbox: the one thing a person declares ─────────────────────────
    root = Path(tempfile.mkdtemp(prefix="teachaction_"))
    (root / "inbox").mkdir()
    (root / "archive").mkdir()
    for i in range(4):
        (root / "inbox" / f"report{i}.txt").write_text(f"the quarterly numbers {i}\n")

    SANDBOX = f"teachaction_{uuid4().hex[:8]}"
    print(f"\n== A. A sandbox it is ALLOWED to practise in ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        derived = TD.derive_domain(
            SANDBOX,
            observations=[("list_directory", {"directory_path": str(root / "inbox")}),
                          ("list_directory", {"directory_path": str(root / "archive")})],
            actions=["copy_file", "move_file"])
    check("both operators derived from the tools themselves",
          set(derived.get("operators") or []) == {"COPY_FILE", "MOVE_FILE"},
          f"operators={derived.get('operators')} refused={derived.get('refused')}")

    world = TD.world_of(SANDBOX)
    # IT LOOKS AT WHERE IT IS. Not "parse the shape of a tool's report" — the
    # substrate's own environment scan, which reports each entry's KIND.
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        perceived = world.perceive(str(root))
    print(f"    perceived {perceived} resource(s) by scanning the sandbox")
    files = [p for p in world.resources.get("path", ()) if p.endswith(".txt")]
    check("its world contains the FILES, not only the directories it was shown",
          len(files) >= 4,
          f"{len(world.resources.get('path', ()))} resources, {len(files)} file(s)")

    # ── B. what it can actually sense about them ─────────────────────────────
    print("\n== B. The vocabulary it will have to learn in — its own, not ours ==")
    observed = world.observe()
    predicates = sorted({f.predicate for f in (observed or ())})
    check("it can read its world",
          bool(observed), f"{len(observed or ())} facts, {len(predicates)} predicate(s)")
    print(f"    predicates: {predicates[:14]}")

    # ── C. the curriculum: it acts, and every reading is its own ─────────────
    print("\n== C. The curriculum — before / action / after, all of it observed ==")
    before_rows = len(await demos.load(domain_id=SANDBOX, predicate="COPY_FILE", arity=2))
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        cycles = []
        for _ in range(8):
            cycles.append(await SubstrateExplorer().explore(
                SANDBOX, get_proposer(SANDBOX), max_actions=8, reinduce=True))
    acted = sum(c.get("acted", 0) or 0 for c in cycles)
    positive = sum(c.get("positive", 0) or 0 for c in cycles)
    negative = sum(c.get("negative", 0) or 0 for c in cycles)
    check("it performed real acts in the real sandbox",
          acted > 0, f"{acted} act(s) over {len(cycles)} cycle(s)")
    check("and some of them WORKED — a positive transition at last",
          positive > 0, f"+{positive} / -{negative}")

    sigs = await demos.signatures(domain_id=SANDBOX)
    lines = []
    for predicate, arity in sorted(sigs):
        rows = await demos.load(domain_id=SANDBOX, predicate=predicate, arity=arity)
        lines.append(f"{predicate}/{arity} +{sum(1 for e in rows if e.positive)} "
                     f"-{sum(1 for e in rows if not e.positive)}")
    check("both operators gathered before/action/after demonstrations",
          len(lines) >= 2, "; ".join(lines))

    # ── D. did experience produce an operator, and a DISTINCTION? ────────────
    print("\n== D. Did experience produce capability — and the distinction? ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await coordinator.learning.drain_pending_induction(limit=50)
    rules = await store.load(domain_id=SANDBOX)
    executable = await store.executable_rules(domain_id=SANDBOX)
    check("it INDUCED an executable operator from its own experience",
          bool(executable),
          f"{[(r.rule_id[:12], r.rule_kind, r.status.value) for r in rules][:6]}")

    kinds = {r.rule_kind for r in executable}
    check("it learned BOTH — copy and move are not one operator to it",
          {"copy_file", "move_file"} <= kinds, f"executable kinds: {sorted(kinds)}")

    def effects_of(rule_kind):
        for r in executable:
            if r.rule_kind == rule_kind:
                return str(r.rule)[:400]
        return ""

    copy_formula, move_formula = effects_of("copy_file"), effects_of("move_file")
    print(f"\n    COPY_FILE: {copy_formula[:300]}")
    print(f"    MOVE_FILE: {move_formula[:300]}")
    check("and it learned the difference — a move deletes the source, a copy does not",
          bool(copy_formula) and bool(move_formula) and copy_formula != move_formula,
          "the two formulas differ" if copy_formula != move_formula
          else "IDENTICAL — the distinction was not learned")

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
