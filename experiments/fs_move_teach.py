#!/usr/bin/env python3
"""Teach MOVE_FILE to the substrate from its OWN acts, reproducibly.

WHY THIS EXISTS. Several experiments (CONSTITUTION-01, CONSTITUTION-02,
PLANNING-01, INTENT-03, INTENT-04, GATE-01, RECONCILE-01, PURSUIT-01) plan over a
learned MOVE_FILE operator. That operator was once ambient state in the database
with no teaching path in the repository, so nothing could recreate it, and
anything that legitimately refuted it broke them all with no way back.

That is not hypothetical. An experiment made a destination unwritable to force a
failure; `move_file` copied the file but could not unlink the source; the
substrate observed its predicted delete-effect fail and CORRECTLY refuted the
rule. The substrate behaved properly — it was taught something false about an
operator that works.

NOTHING IS ASSERTED AND NO DEMONSTRATION IS WRITTEN HERE. The substrate moves
real files through its own tool path, which watches every act: the self perceives
what is at each path the act names, before and after, and files what happened.
The operator lives where the act puts it — the domain of acts on paths — and its
vocabulary is the self's own: what KIND of thing is at a path and its SIZE, or
that nothing is there (ABSENT).

What the teacher chooses is WHICH acts to show, as a teacher does:
  * moves that work, of different files between different folders, so the paths
    generalise to variables instead of freezing as these ones;
  * moves of something that is not there, which fail and leave the world as it
    was — the negatives that make "the source is there" a precondition rather
    than a coincidence;
  * a move onto a file that is already there, which the tool refuses — the
    negative that makes a free destination a precondition. The self sees that
    nothing is at a place (ABSENT), and every move that works had one, but a
    rule that ignores it explains those just as well; only this failure tells
    the two apart;
  * the world observed twice with nothing done, which separates what the act
    does from what happens anyway.

Induction and validation are the learning authority's own (`reinduce_operator`):
it induces from what was filed and validates against the most recent moves, which
it holds back.

Run:  ./venv_lyric/bin/python3 experiments/fs_move_teach.py
"""
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("LYRIC_SHADOW_MODE", "1")

#: The domain acts on paths belong to. Not chosen here: `derived_domain_id`
#: names it from the kind of thing the act touches, and `main` checks the two
#: agree.
DOMAIN = "tools:path"
OPERATOR = "MOVE_FILE"


def reset(root: Path) -> None:
    """Each demonstration starts from a MINIMAL world: induction generalizes over
    what the demonstrations share, so unrelated files bury the fact the operator
    actually depends on."""
    for d in ("inbox", "archive", "review"):
        (root / d).mkdir(exist_ok=True)
        for f in (root / d).iterdir():
            if f.is_file():
                f.unlink()


async def move(coord, source: Path, destination: Path, *, intent_id, label):
    """Ask the substrate to move one file, through its own watched tool path.

    A file already at the destination is READ first: Law 2 refuses an act that
    would displace a file with no current reading of it. The reading is not
    bound to the move's intent -- a reading is investigate-class, and claiming
    the intent for it would have Law 4 replan it for not being the proved act.
    """
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    if destination.exists():
        await coord.tool_registry.execute_tool("read_file", {"file_path": str(destination)})
    task = Task(id=f"teach_{label}", type=TaskType.EXECUTION,
                description=f"move {source.name} to {destination.parent.name}",
                priority=Priority.MEDIUM, provenance={"intent_id": intent_id})
    return await coord._run_tool(
        "move_file", {"source_path": str(source), "destination_path": str(destination)},
        task)


async def still_world(tag: str, root: Path) -> bool:
    """The world observed twice with nothing invoked: what separates "the state
    changed because of the ACTION" from "it was going to change anyway".

    The substrate LOOKS at the folder first, so the world it observes holds what
    is really there. A still world of nothing refutes nothing, and then the
    hypothesis that an effect happens without the act survives."""
    from core.execution.operator_binding import get_binding_registry
    from core.execution.tool_domain import world_of
    from core.learning.rule_induction import TrainingExample
    from core.learning.unified_learning_system import get_learning_authority
    world_of(DOMAIN).perceive(str(root))
    registry = get_binding_registry()
    before = await registry.observe_world_async(DOMAIN)
    after = await registry.observe_world_async(DOMAIN)
    if before is None or after != before:
        return False
    return await get_learning_authority().record_demonstration(
        TrainingExample(before=tuple(sorted(before)), action=None,
                        after=tuple(sorted(before)), positive=False,
                        evidence_id=f"{tag}_still"),
        domain_id=DOMAIN)


async def round_of_demonstrations(coord, root: Path, tag: str, intent_id) -> dict:
    """Five moves, each against a freshly minimal world, each real, then the
    still world:

      1. a file in `inbox`, moved to `archive`       → works
      2. a file in `archive`, moved to `review`       → works, so the folders
         generalize to variables instead of freezing as inbox/archive
      3. a file named where it is NOT                 → the tool fails, nothing
      4. the same, from the other side                  moves: the negatives
         that make the source's being there necessary
      5. a file moved onto one already there          → the tool refuses, nothing
         moves: the negative that makes a free destination necessary

    The files differ in content, so what is carried over — the size — is a value
    the operator moves, not a constant it requires.
    """
    results = {}

    async def one(name, content, where, named_in, dest, label, *, taken_by=None):
        reset(root)
        (root / where / name).write_text(content)
        if taken_by is not None:
            (root / dest / name).write_text(taken_by)
        result = await move(coord, root / named_in / name, root / dest / name,
                            intent_id=intent_id, label=f"{tag}_{label}")
        results[label] = bool(result and result.get("success"))

    await one("doc_a.txt", "a report for the archive\n", "inbox", "inbox",
              "archive", "pos_in_to_ar")
    await one("doc_c.txt", "untouched\n", "inbox", "archive", "review",
              "neg_not_there_1")
    await one("doc_b.txt", "notes to review, longer than the first\n", "archive",
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

    # The intent these demonstrations are done under, recorded through the real
    # authority. Without it Law 2 replans every move: an act nothing can explain
    # is not one the substrate may perform, and teaching is not an exception.
    teaching = await get_intent_authority().form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"fs_move_teach_{_uuid.uuid4().hex[:8]}"),
        shape={"proved": True, "operator": f"{OPERATOR}(?s, ?d)",
               "operators": [f"{OPERATOR}(?s, ?d)"],
               "goal_conditions": ["KIND(?d, Ffile)"], "rule_ids": [],
               "domain": DOMAIN, "steps": 1, "grounding_complete": True},
        content={"aim": "learn MOVE_FILE by moving real files", "bindings": [{}]})
    print(f"teaching under intent {teaching.intent_id}")

    root = Path(tempfile.mkdtemp(prefix="fs-move-teach-"))
    try:
        print("\nDemonstrations, by really moving files:")
        for tag in ("mv", "mv_again"):
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
    """Make sure the substrate HAS its MOVE_FILE operator, teaching it if not.

    THE DEPENDENCY IS DECLARED, NOT ASSUMED. Experiments that plan over this
    operator once read it out of the live store without saying where it came
    from. When the store was wiped they all failed at once — GATE-01 25/25 ->
    22/25, CONSTITUTION-01 39/39 -> 37/39 — with signatures that read like broken
    code (`proved=None operator=None`, `state space exhausted at 0 state(s)`)
    rather than a missing precondition. An experiment that cannot state what it
    needs cannot tell you which of the two it is.

    Idempotent and cheap when the rule is already there: it asks the store
    first and teaches only on a miss, so a suite run does the executions once.
    """
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
