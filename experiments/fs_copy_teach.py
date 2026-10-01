#!/usr/bin/env python3
"""Teach COPY_FILE to the substrate from its OWN acts, reproducibly.

WHY THIS EXISTS. MOVE_FILE and DELETE_FILE each have a teacher
(`fs_move_teach`, `fs_remove_teach`); COPY_FILE was only ever learned inside
TEACH-ACTION-01, which forgets its practice domain when it ends. Anything that
plans over a copy therefore depended on a run that deliberately leaves nothing
behind. This is the copy's own teaching path.

NOTHING IS ASSERTED AND NO DEMONSTRATION IS WRITTEN HERE. The substrate copies
real files through its own tool path, which watches every act: the self
perceives what is at each path the act names, before and after, and files what
happened, in its own vocabulary (KIND, SIZE, IDENTITY, or ABSENT).

What the teacher chooses is WHICH acts to show:
  * copies that work, of different files between different folders, so the
    paths generalise to variables instead of freezing as these ones;
  * copies of something that is not there, which fail and leave the world as it
    was: the negatives that make "the source is there" a precondition;
  * a copy onto a file that is already there, which the tool refuses: the
    negative that makes a free destination a precondition;
  * the world observed twice with nothing done.

A copy and a move take the same two arguments. What separates them is only
what the self sees afterwards: after a copy the source is still there, and the
thing at the destination is a NEW thing (a new identity), not the one that was
at the source.

Induction and validation are the learning authority's own (`reinduce_operator`).

Run:  POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/fs_copy_teach.py
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

OPERATOR = "COPY_FILE"


async def copy(coord, source: Path, destination: Path, *, intent_id, label):
    """Ask the substrate to copy one file, through its own watched tool path.

    A file already at the destination is READ first, as in the move teacher:
    Law 2 refuses an act that would displace a file with no current reading.
    """
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    if destination.exists():
        await coord.tool_registry.execute_tool("read_file", {"file_path": str(destination)})
    task = Task(id=f"teach_{label}", type=TaskType.EXECUTION,
                description=f"copy {source.name} to {destination.parent.name}",
                priority=Priority.MEDIUM, provenance={"intent_id": intent_id})
    return await coord._run_tool(
        "copy_file", {"source_path": str(source), "destination_path": str(destination)},
        task)


async def round_of_demonstrations(coord, root: Path, tag: str, intent_id) -> dict:
    """Five copies, each against a freshly minimal world, each real, then the
    still world:

      1. a file in `inbox`, copied to `archive`       -> works
      2. a file in `archive`, copied to `review`      -> works, so the folders
         generalise to variables
      3. a file named where it is NOT                 -> the tool fails, nothing
      4. the same, from the other side                  is copied
      5. a file copied onto one already there         -> the tool refuses

    The files differ in content, so the size is a value the copy carries, not a
    constant it requires.
    """
    results = {}

    async def one(name, content, where, named_in, dest, label, *, taken_by=None):
        reset(root)
        (root / where / name).write_text(content)
        if taken_by is not None:
            (root / dest / name).write_text(taken_by)
        result = await copy(coord, root / named_in / name, root / dest / name,
                            intent_id=intent_id, label=f"{tag}_{label}")
        results[label] = bool(result and result.get("success"))

    await one("doc_a.txt", "a report to keep a second copy of\n", "inbox", "inbox",
              "archive", "pos_in_to_ar")
    await one("doc_c.txt", "untouched\n", "inbox", "archive", "review",
              "neg_not_there_1")
    await one("doc_b.txt", "notes to review, longer than the first one\n", "archive",
              "archive", "review", "pos_ar_to_rv")
    await one("doc_e.txt", "untouched as well\n", "review", "inbox", "archive",
              "neg_not_there_2")
    await one("doc_f.txt", "a file whose place is taken\n", "inbox", "inbox",
              "archive", "neg_place_taken", taken_by="already in the archive\n")

    reset(root)
    (root / "inbox" / "doc_d.txt").write_text("still\n")
    results["still"] = await still_world(tag, root)
    return results


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.execution.tool_domain import derived_domain_id
    from core.learning.rule_store import get_rule_store
    from core.learning.unified_learning_system import get_learning_authority
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
    import uuid as _uuid

    if derived_domain_id(["path"]) != DOMAIN:
        print(f"FAILED: acts on paths belong to {derived_domain_id(['path'])!r}, "
              f"not {DOMAIN!r}")
        return 1

    coord = AutonomousCoordinator()
    if not await coord.initialize_execution_faculty():
        print("FAILED: execution faculty did not come up")
        return 1

    teaching = await get_intent_authority().form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"fs_copy_teach_{_uuid.uuid4().hex[:8]}"),
        shape={"proved": True, "operator": f"{OPERATOR}(?s, ?d)",
               "operators": [f"{OPERATOR}(?s, ?d)"],
               "goal_conditions": ["KIND(?d, Ffile)"], "rule_ids": [],
               "domain": DOMAIN, "steps": 1, "grounding_complete": True},
        content={"aim": "learn COPY_FILE by copying real files", "bindings": [{}]})
    print(f"teaching under intent {teaching.intent_id}")

    root = Path(tempfile.mkdtemp(prefix="fs-copy-teach-"))
    try:
        print("\nDemonstrations, by really copying files:")
        for tag in ("cp", "cp_again"):
            shown = await round_of_demonstrations(coord, root, tag, teaching.intent_id)
            print(f"  {tag}: {shown}")

        outcome = await get_learning_authority().reinduce_operator(
            domain_id=DOMAIN, predicate=OPERATOR, arity=2)
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


async def ensure_taught() -> bool:
    """Make sure the substrate HAS its COPY_FILE operator, teaching it if not."""
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
