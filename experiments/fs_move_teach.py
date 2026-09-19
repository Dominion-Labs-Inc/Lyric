#!/usr/bin/env python3
"""Teach MOVE_FILE in `fs_g2_real1` from REAL executions, reproducibly.

WHY THIS EXISTS. Four experiments (CONSTITUTION-01, CONSTITUTION-02, PLANNING-01,
INTENT-03) plan over a learned MOVE_FILE operator in `fs_g2_real1`. That operator
was ambient state in the database with no teaching path in the repository — so
nothing could recreate it, and anything that legitimately refuted it broke all
four with no way back.

That is not hypothetical. An experiment made a destination unwritable to force a
failure; `move_file` copied the file but could not unlink the source; the
substrate observed its predicted delete-effect fail and CORRECTLY refuted the
rule. The substrate behaved properly — it was taught something false about an
operator that works.

So the dependency is made reproducible here, the same way `REMOVE_FILE` is taught
in OPERATOR-REMOVAL-01: nothing is asserted, every demonstration is produced by
executing the real `move_file` tool against a real directory and reading the
filesystem before and after. Induction is the substrate's own, the rule goes to
the real store, and it is VALIDATED against held-out observations it was not
induced from.

Run:  ./venv_torin/bin/python3 experiments/fs_move_teach.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("TORIN_SHADOW_MODE", "1")

DOMAIN = "fs_g2_real1"


def _enc(name):
    from core.execution.filesystem_domain import _encode
    return _encode(name)


def reset(root: Path) -> None:
    """Each demonstration starts from a MINIMAL world: induction generalizes over
    what the demonstrations share, so unrelated files bury the fact the operator
    actually depends on."""
    for d in ("inbox", "archive", "review"):
        (root / d).mkdir(exist_ok=True)
        for f in (root / d).iterdir():
            if f.is_file():
                f.unlink()


async def demonstrate(coord, world, binding, action, evidence_id, intent_id=None):
    """Execute one candidate move FOR REAL and record what the world did.

    THE TEACHER IS THE SUBSTRATE, so it obeys the substrate's own law. Since the
    constitution became the live gate on `execute_tool`, two of the five laws
    apply to these demonstrations exactly as they apply to any other act:

      * Law 2 refuses an act on a file with no current reading — so each file is
        READ first, through the real tool, which is what records the account.
        The read changes nothing about what is demonstrated: the before/after the
        learner induces from are FILE_IN facts, and reading moves no file.
      * Law 2 also refuses an act nothing can explain — so the moves run under a
        recorded INTENT naming MOVE_FILE in this domain. The reads do not: a
        reading is investigate-class and claiming the move's intent for it would
        make Law 4 replan it for not being the proved act.
    """
    from core.learning.rule_store import training_example_from_runtime
    from core.reasoning.intent_authority import set_acting_intent, reset_acting_intent

    before = world.observe()
    params = binding.parameters(action.args)
    source = params.get("source_path")
    if source:
        await coord.tool_registry.execute_tool("read_file", {"file_path": source})
    token = set_acting_intent(intent_id)
    try:
        await coord.tool_registry.execute_tool(binding.tool_name, params)
    finally:
        reset_acting_intent(token)
    after = world.observe()
    moved = before != after
    return training_example_from_runtime(
        before=before, action=action, after=after,
        evidence_id=evidence_id, positive=moved), moved


async def no_action(world, evidence_id):
    """The world observed twice with nothing invoked — what separates 'the state
    changed because of the ACTION' from 'it was going to change anyway'."""
    from core.learning.rule_store import training_example_from_runtime
    before = world.observe()
    after = world.observe()
    return training_example_from_runtime(
        before=before, action=None, after=after,
        evidence_id=evidence_id, positive=False)


async def round_of_demonstrations(coord, root, world, binding, tag, intent_id=None):
    """Four demonstrations, each against a freshly minimal world, each real:

      1. a file in `inbox`  moved to `archive`   → succeeds
      2. a file in `archive` moved to `inbox`    → succeeds, so the directories
         generalize to variables instead of freezing as inbox/archive
      3. a file that is NOT where the move says  → the tool fails and the world
         does not move: the negative isolating FILE_IN(file, source)
      4. a file in place and NOTHING invoked     → separates action from drift
    """
    from core.learning.rule_induction import Fact
    examples = []

    async def one(name, where, src, dst, evidence):
        reset(root)
        (root / where / name).write_text("real content\n")
        action = Fact("MOVE_FILE", (_enc(name), _enc(src), _enc(dst)))
        example, _ = await demonstrate(coord, world, binding, action, evidence,
                                       intent_id=intent_id)
        examples.append(example)

    await one("doc_a.txt", "inbox", "inbox", "archive", f"{tag}_pos_in_to_ar")
    await one("doc_b.txt", "archive", "archive", "review", f"{tag}_pos_ar_to_rv")

    # THE NEGATIVES MUST CONTRADICT THE UNGUARDED RULE, and that takes a THIRD
    # directory. Bodies here are "pruned by negatives and then minimized", so a
    # literal survives only if a negative needs it.
    #
    # A negative that moves a file INTO the directory it is already in cannot do
    # that: the unguarded rule predicts add FILE_IN(file, dest) — already true —
    # and delete FILE_IN(file, source) — never true. Both hold vacuously, nothing
    # is contradicted, and the guard `FILE_IN(?X0, ?X2)` is minimized away. That
    # is exactly what happened: the re-taught operator let a planner bind the
    # SOURCE to `bystander.txt`, and the move failed with "Source not found".
    #
    # With three directories the predicted destination is somewhere the file
    # demonstrably does NOT end up, so the rule is contradicted unless it carries
    # the guard.
    await one("doc_c.txt", "inbox", "archive", "review", f"{tag}_neg_src_wrong_1")
    await one("doc_e.txt", "review", "inbox", "archive", f"{tag}_neg_src_wrong_2")

    reset(root)
    (root / "inbox" / "doc_d.txt").write_text("untouched\n")
    examples.append(await no_action(world, f"{tag}_noaction"))
    return examples


async def main():
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.domain.concept_ingestion import EvidenceSourceType
    from core.domain.evidence_producers import submit_demonstration
    from core.execution.filesystem_domain import install_filesystem_domain
    from core.execution.operator_binding import get_binding_registry
    from core.learning.rule_induction import get_rule_inducer
    from core.learning.rule_store import get_rule_store

    root = Path(tempfile.mkdtemp(prefix="fs-move-teach-"))
    for d in ("inbox", "archive", "review"):
        (root / d).mkdir()

    coord = AutonomousCoordinator()
    if not await coord.initialize_execution_faculty():
        print("FAILED: execution faculty did not come up")
        return 1
    world = install_filesystem_domain(DOMAIN, root)
    binding = get_binding_registry().get(DOMAIN, "MOVE_FILE")
    if binding is None or binding.tool_name != "move_file":
        print(f"FAILED: MOVE_FILE is not bound to move_file ({binding})")
        return 1
    print(f"MOVE_FILE is bound to {binding.tool_name} in {DOMAIN}")

    # The intent these demonstrations are done under, recorded through the real
    # authority. Without it Law 2 replans every move: an act nothing can explain
    # is not one the substrate may perform, and teaching is not an exception.
    from core.reasoning.intent_authority import (
        get_intent_authority, continuity_goal, SUBSTRATE_ACTOR)
    import uuid as _uuid
    teaching = await get_intent_authority().form(
        "goal", SUBSTRATE_ACTOR, continuity_goal(f"fs_move_teach_{_uuid.uuid4().hex[:8]}"),
        shape={"proved": True, "operator": "MOVE_FILE(?f, ?src, ?dst)",
               "operators": ["MOVE_FILE(?f, ?src, ?dst)"],
               "goal_conditions": ["FILE_IN(?f, ?dst)"], "rule_ids": [],
               "domain": DOMAIN, "steps": 1, "grounding_complete": True},
        content={"aim": "learn MOVE_FILE by moving real files", "bindings": [{}]})
    print(f"teaching under intent {teaching.intent_id}")

    print("\nDemonstrations, by really moving files:")
    examples = await round_of_demonstrations(coord, root, world, binding, "mv",
                                             intent_id=teaching.intent_id)
    for example in examples:
        outcome = await submit_demonstration(
            example, domain_id=DOMAIN,
            source_type=EvidenceSourceType.TASK_ARTIFACT,
            producer="filesystem_move_execution")
        if not outcome.read_successfully:
            print(f"FAILED: demonstration {example.evidence_id} unreadable: "
                  f"{outcome.extraction_failures}")
            return 1
    print(f"  {len(examples)} demonstration(s) submitted")

    induction = get_rule_inducer().induce(examples)
    print(f"  induction: {induction.status.value}")
    if induction.rule is None:
        print(f"FAILED: no rule induced — {induction.detail}")
        for candidate in induction.candidates:
            print("    candidate:", candidate)
        return 1
    print(f"  rule     : {induction.rule}")

    store = get_rule_store()
    stored = (await store.record_induction(
        induction, examples, domain_id=DOMAIN, rule_kind="move_file"))[0]
    print(f"  persisted: {stored.rule_id} ({stored.status.value})")

    print("\nValidation against moves it was NOT induced from:")
    held_out = await round_of_demonstrations(coord, root, world, binding, "mv_holdout",
                                             intent_id=teaching.intent_id)
    for example in held_out:
        await submit_demonstration(
            example, domain_id=DOMAIN,
            source_type=EvidenceSourceType.TASK_ARTIFACT,
            producer="filesystem_move_execution")
    outcome = await store.validate(stored, held_out)
    print(f"  validation: {outcome.status.value} — {outcome.detail}")

    executable = await store.executable_rules(domain_id=DOMAIN)
    ids = [r.rule_id for r in executable]
    print(f"\n{DOMAIN}: {len(executable)} executable rule(s) {ids}")
    ok = outcome.status.value == "validated" and stored.rule_id in ids
    print("RESULT:", "TAUGHT and EXECUTABLE" if ok else "NOT executable")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
