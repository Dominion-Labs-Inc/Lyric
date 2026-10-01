#!/usr/bin/env python3
"""Teach CREATE_DIRECTORY to the substrate from its OWN acts, reproducibly.

NOTHING IS ASSERTED AND NO DEMONSTRATION IS WRITTEN HERE. The substrate creates
real folders through its own tool path, which watches every act: the self
perceives what is at the path before and after, and files what happened, in its
own vocabulary (KIND, IDENTITY, or ABSENT).

What the teacher chooses is WHICH acts to show:
  * folders created where nothing is, in different places, so the path
    generalises to a variable;
  * a folder asked for where a folder already is, and where a file already is,
    which the tool refuses: the negatives that make a free place a precondition;
  * the world observed twice with nothing done.

Induction and validation are the learning authority's own (`reinduce_operator`).

Run:  POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/fs_mkdir_teach.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("LYRIC_SHADOW_MODE", "1")

from experiments.fs_move_teach import DOMAIN, reset, still_world  # noqa: E402

OPERATOR = "CREATE_DIRECTORY"


async def make(coord, target: Path, *, intent_id, label):
    """Ask the substrate to create one folder, through its own watched tool path.
    Whatever already occupies the place is READ first when it is a file, so the
    act is judged against a current reading of it."""
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    if target.is_file():
        await coord.tool_registry.execute_tool("read_file", {"file_path": str(target)})
    task = Task(id=f"teach_{label}", type=TaskType.EXECUTION,
                description=f"create folder {target.name} in {target.parent.name}",
                priority=Priority.MEDIUM, provenance={"intent_id": intent_id})
    return await coord._run_tool("create_directory", {"directory_path": str(target)}, task)


async def round_of_demonstrations(coord, root: Path, tag: str, intent_id) -> dict:
    """Two folders made where nothing is, then two refusals where something is,
    then the still world."""
    results = {}

    async def one(where, name, label, *, taken_by=None):
        reset(root)
        target = root / where / name
        if taken_by == "dir":
            target.mkdir()
        elif taken_by == "file":
            target.write_text("a file already in this place\n")
        result = await make(coord, target, intent_id=intent_id, label=f"{tag}_{label}")
        results[label] = bool(result and result.get("success"))
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    await one("inbox", "reports", "pos_inbox")
    await one("inbox", "drafts", "neg_dir_there", taken_by="dir")
    await one("archive", "2026", "pos_archive")
    await one("archive", "notes", "neg_file_there", taken_by="file")

    reset(root)
    (root / "inbox" / "doc_d.txt").write_text("still\n")
    results["still"] = await still_world(tag, root)
    return results


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.learning.demonstration_store import get_demonstration_store
    from core.learning.rule_store import get_rule_store
    from core.learning.unified_learning_system import get_learning_authority
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
    import uuid as _uuid

    coord = AutonomousCoordinator()
    if not await coord.initialize_execution_faculty():
        print("FAILED: execution faculty did not come up")
        return 1

    teaching = await get_intent_authority().form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"fs_mkdir_teach_{_uuid.uuid4().hex[:8]}"),
        shape={"proved": True, "operator": f"{OPERATOR}(?d)", "operators": [f"{OPERATOR}(?d)"],
               "goal_conditions": ["KIND(?d, Fdir)"], "rule_ids": [],
               "domain": DOMAIN, "steps": 1, "grounding_complete": True},
        content={"aim": "learn CREATE_DIRECTORY by creating real folders", "bindings": [{}]})
    print(f"teaching under intent {teaching.intent_id}")

    root = Path(tempfile.mkdtemp(prefix="fs-mkdir-teach-"))
    try:
        print("\nDemonstrations, by really creating folders:")
        for tag in ("md", "md_again"):
            shown = await round_of_demonstrations(coord, root, tag, teaching.intent_id)
            print(f"  {tag}: {shown}")

        arity = next((a for p, a in await get_demonstration_store().signatures(domain_id=DOMAIN)
                      if p == OPERATOR), None)
        if arity is None:
            print(f"FAILED: no {OPERATOR} demonstration was filed")
            return 1
        outcome = await get_learning_authority().reinduce_operator(
            domain_id=DOMAIN, predicate=OPERATOR, arity=arity)
        print(f"\n  induction: {outcome.get('status')} — "
              f"{outcome.get('positives')} positive of {outcome.get('demonstrations')} "
              f"demonstration(s), {outcome.get('contrastive')} contrastive, "
              f"rule {outcome.get('rule_id')}")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    executable = [r for r in await get_rule_store().executable_rules(domain_id=DOMAIN)
                  if r.rule.action is not None and r.rule.action.predicate == OPERATOR]
    for rule in executable:
        print(f"  executable: {rule.rule_id} {rule.rule}")
    ok = bool(executable)
    print("RESULT:", "TAUGHT and EXECUTABLE" if ok else "NOT executable")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
