#!/usr/bin/env python3
"""Teach WRITE_FILE, as making a new file, to the substrate from its OWN acts.

NOTHING IS ASSERTED AND NO DEMONSTRATION IS WRITTEN HERE. The substrate writes
real files through its own tool path, which watches every act: the self
perceives what is at the path before and after (KIND, SIZE, IDENTITY, or ABSENT)
and files what happened.

What the teacher chooses is WHICH acts to show:
  * new files written where nothing is, in different folders and of different
    lengths, so the path is a variable and the size is what the act produces;
  * a file asked for where a folder is, which fails: the negative that makes a
    free place a precondition;
  * the world observed twice with nothing done.

Writing OVER a file is not shown here. What it changes is what the file holds,
and the self does not yet perceive a file's content, so such a demonstration
would show no change at all.

Run:  POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/fs_write_teach.py
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

OPERATOR = "WRITE_FILE"


async def write(coord, target: Path, content: str, *, intent_id, label):
    """Ask the substrate to write one file, through its own watched tool path."""
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    task = Task(id=f"teach_{label}", type=TaskType.EXECUTION,
                description=f"write {target.name} in {target.parent.name}",
                priority=Priority.MEDIUM, provenance={"intent_id": intent_id})
    return await coord._run_tool(
        "write_file", {"file_path": str(target), "content": content}, task)


async def round_of_demonstrations(coord, root: Path, tag: str, intent_id) -> dict:
    """Two new files written where nothing is, one refusal where a folder is,
    then the still world."""
    results = {}

    async def one(where, name, content, label, *, folder_there=False):
        reset(root)
        target = root / where / name
        if folder_there:
            target.mkdir()
        result = await write(coord, target, content, intent_id=intent_id,
                             label=f"{tag}_{label}")
        results[label] = bool(result and result.get("success"))
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    await one("inbox", "summary.txt", "a short summary\n", "pos_inbox")
    await one("archive", "minutes.txt",
              "the minutes of the meeting, longer than the summary was\n", "pos_archive")
    await one("review", "plan.txt", "a plan\n", "neg_folder_there", folder_there=True)

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
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"fs_write_teach_{_uuid.uuid4().hex[:8]}"),
        shape={"proved": True, "operator": f"{OPERATOR}(?p)", "operators": [f"{OPERATOR}(?p)"],
               "goal_conditions": ["KIND(?p, Ffile)"], "rule_ids": [],
               "domain": DOMAIN, "steps": 1, "grounding_complete": True},
        content={"aim": "learn WRITE_FILE by writing real files", "bindings": [{}]})
    print(f"teaching under intent {teaching.intent_id}")

    root = Path(tempfile.mkdtemp(prefix="fs-write-teach-"))
    try:
        print("\nDemonstrations, by really writing files:")
        for tag in ("wr", "wr_again"):
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
