#!/usr/bin/env python3
"""Teach DELETE_FILE to the substrate from its OWN acts, reproducibly.

WHY THIS EXISTS. CONSTITUTION-03 and HARM-01 judge a learned removal operator,
and OPERATOR-REMOVAL-01 is where it was first learned. An experiment that needs
the operator must be able to recreate it, or it fails on an empty store with a
signature that reads like broken code ("Grounding produced NO operators from 0
rule(s)") rather than a missing precondition.

NOTHING IS ASSERTED AND NO DEMONSTRATION IS WRITTEN HERE. The substrate deletes
real files through its own tool path, which watches every act: the self perceives
what is at the path before and after, and files what happened. The operator lives
where the act puts it — the domain of acts on paths — in the self's own
vocabulary: what KIND of thing is at a path and its SIZE, or that nothing is
there (ABSENT).

What the teacher chooses is WHICH removals to show:
  * removals that work, of different files in different folders;
  * removals aimed where the file is NOT, which fail and leave the world as it
    was;
  * the world observed twice with nothing done.

Induction and validation are the learning authority's own (`reinduce_operator`).

Run:  ./venv_lyric/bin/python3 experiments/fs_remove_teach.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("LYRIC_SHADOW_MODE", "1")

from experiments.fs_move_teach import DOMAIN, still_world  # noqa: E402

OPERATOR = "DELETE_FILE"


def reset(root: Path) -> None:
    """A minimal world for each demonstration: only the folders, empty."""
    for d in ("inbox", "archive"):
        (root / d).mkdir(exist_ok=True)
        for f in (root / d).iterdir():
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f, ignore_errors=True)


async def remove(coord, target: Path, *, intent_id, label):
    """Ask the substrate to delete one file, through its own watched tool path.

    The file is READ first when it is there: Law 2 refuses an act on a file with
    no current reading. The reading is not bound to the removal's intent — a
    reading is investigate-class, and claiming the intent for it would have Law
    4 replan it for not being the proved act.
    """
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    if target.exists():
        await coord.tool_registry.execute_tool("read_file", {"file_path": str(target)})
    task = Task(id=f"teach_{label}", type=TaskType.EXECUTION,
                description=f"remove {target.name} from {target.parent.name}",
                priority=Priority.MEDIUM, provenance={"intent_id": intent_id})
    return await coord._run_tool(
        "delete_file", {"path": str(target), "confirm": True}, task)


async def round_of_demonstrations(coord, root: Path, tag: str, intent_id) -> dict:
    """Four removals against freshly minimal worlds, then the still world:

      1. a file in `inbox`, removed from `inbox`       → works
      2. a file in `inbox`, removal aimed at `archive` → the tool fails, nothing
                                                          moves
      3. a file in `archive`, removed from `archive`   → works, so the folder
                                                          generalizes
      4. a file in `archive`, removal aimed at `inbox` → fails
    """
    results = {}

    async def one(name, content, where, aimed_at, label):
        reset(root)
        (root / where / name).write_text(content)
        result = await remove(coord, root / aimed_at / name, intent_id=intent_id,
                              label=f"{tag}_{label}")
        results[label] = bool(result and result.get("success"))

    await one("doc_a.txt", "an obsolete draft\n", "inbox", "inbox", "pos_inbox")
    await one("doc_c.txt", "untouched\n", "inbox", "archive", "neg_not_there_1")
    await one("doc_b.txt", "an old archived copy, longer\n", "archive", "archive",
              "pos_archive")
    await one("doc_e.txt", "untouched as well\n", "archive", "inbox", "neg_not_there_2")

    reset(root)
    (root / "inbox" / "doc_d.txt").write_text("still\n")
    results["still"] = await still_world(tag, root)
    return results


async def teaching_intent():
    """The intent removals are done under, recorded through the real authority.
    Without it Law 2 replans every removal: an act nothing can explain is not
    one the substrate may perform, and teaching is not an exception."""
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
    import uuid as _uuid
    return await get_intent_authority().form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"rm_teach_{_uuid.uuid4().hex[:8]}"),
        shape={"proved": True, "operator": f"{OPERATOR}(?p)",
               "operators": [f"{OPERATOR}(?p)"],
               "goal_conditions": ["¬KIND(?p, Ffile)"], "rule_ids": [],
               "domain": DOMAIN, "steps": 1, "grounding_complete": True},
        content={"aim": "learn DELETE_FILE by removing real files", "bindings": [{}]})


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.learning.rule_store import get_rule_store
    from core.learning.unified_learning_system import get_learning_authority

    coord = AutonomousCoordinator()
    if not await coord.initialize_execution_faculty():
        print("FAILED: execution faculty did not come up")
        return 1
    teaching = await teaching_intent()
    print(f"teaching under intent {teaching.intent_id}")

    root = Path(tempfile.mkdtemp(prefix="fs-remove-teach-"))
    try:
        print("\nDemonstrations, by really removing files:")
        for tag in ("rm", "rm_again"):
            shown = await round_of_demonstrations(coord, root, tag, teaching.intent_id)
            print(f"  {tag}: {shown}")
        outcome = await get_learning_authority().reinduce_operator(
            domain_id=DOMAIN, predicate=OPERATOR, arity=1)
        print(f"\n  induction: {outcome.get('status')} — "
              f"{outcome.get('positives')} positive of {outcome.get('demonstrations')} "
              f"demonstration(s), rule {outcome.get('rule_id')}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    executable = [r for r in await get_rule_store().executable_rules(domain_id=DOMAIN)
                  if r.rule.action is not None and r.rule.action.predicate == OPERATOR]
    for rule in executable:
        print(f"  executable: {rule.rule_id} {rule.rule}")
    ok = bool(executable)
    print("RESULT:", "TAUGHT and EXECUTABLE" if ok else "NOT executable")
    return 0 if ok else 1


async def ensure_taught() -> bool:
    """Make sure the substrate HAS its DELETE_FILE operator, teaching it if not.
    Cheap when it is there: the store is asked first."""
    from core.learning.rule_store import get_rule_store

    async def held() -> bool:
        return any(r.rule.action is not None and r.rule.action.predicate == OPERATOR
                   for r in await get_rule_store().executable_rules(domain_id=DOMAIN))

    if await held():
        return True
    print(f"  [precondition] {DOMAIN} has no executable {OPERATOR} — teaching it "
          f"from the substrate's own acts", flush=True)
    await main()
    return await held()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
