#!/usr/bin/env python3
"""CREDIT-01 — meant-vs-happened becomes the substrate's operating credit.

The substrate already collects evidence: every executed step is verified against
the re-observed world, filed as a demonstration, and allowed to revise the rule it
came from. So the credit signal worth building is NOT a new number — it is the one
credit that already governs behaviour, answered by what the substrate now owns.

`operating_reliability` is that signal. Its own code says it asks "did the
operation achieve its intent?", and it is consumed twice: by the KNOW→DO
operability bar (`_domain_operability`), which decides whether the substrate may
act in a domain at all, and by `PlanInput.OPERATING_RELIABILITY`, which every
state plan declares as an input. Until now it was answered by a completion
POSTERIOR — a belief about doneness standing in for an observation of correctness.

Two things were MEASURED before this experiment was written (probe, live substrate):

  * a goal the substrate could not PLAN — nothing executed, no tool invoked, no
    world change — recorded `operating_attempts += 1, wins += 0`. A knowledge
    deficit was being recorded as an operating failure. Because a falling `earned`
    RAISES the bar, not knowing how to act in a domain made the substrate less
    free to act there: the remedy for the deficit closed the door on itself.
  * a goal that WAS reached (file verified on disk) recorded a win from a
    posterior that sat at ≥0.5 while the same task's completion decision said
    "not accepted" — two proxies disagreeing, with the world-decided answer
    sitting unused on the reconciled intent.

What this checks, end to end on the real substrate:

  A  the credit invariant holds at the AUTHORITY, not at call sites: an outcome
     that establishes nothing about operating correctly cannot move the posterior,
     and an unclassified one is denied.
  B  the drive path's credit is read FROM the reconciled intent — including the
     case per-step evidence structurally cannot see: every step CONFIRMS and the
     aim is still not realized.
  C  the corrected signal reaches its consumers: earned reliability, the KNOW→DO
     bar, and the inputs the planner declares.

Non-polluting: the domain's operating counters are snapshotted and restored, the
synthetic domain of section A is deleted, and every intent this run creates is
removed. Nothing here makes a real operator fail — see INTENT-04 for why that
matters.

Run:  ./venv_lyric/bin/python3 experiments/CREDIT-01/experiment.py
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

from experiments.fs_move_teach import DOMAIN, ensure_taught  # noqa: E402
SYN = f"credit01_syn_{uuid.uuid4().hex[:8]}"
REACHED_RUNS = 5

PASS = FAIL = 0
EV = RunRecord(
    "CREDIT-01",
    claim="The substrate's operating credit is read from what it MEANT against "
          "what the world DID — and where nothing was operated, nothing is "
          "credited.",
    hypothesis="If meant-vs-happened supplies operating correctness, then a "
               "reached aim credits a win from the reconciled intent, an "
               "unrealized aim credits a loss even when every step confirmed, "
               "and a goal that never planned moves the posterior not at all.")


def check(label, ok, detail=""):
    global PASS, FAIL
    EV.check(label, ok, detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


async def counters(db, domain):
    rows = await db.execute_query(
        "SELECT operating_attempts, operating_wins FROM unified.domain_controllability "
        "WHERE domain_id=$1", (domain,), fetch_all=True)
    if not rows:
        return 0, 0
    return rows[0]["operating_attempts"] or 0, rows[0]["operating_wins"] or 0


async def rule_statuses(domain):
    """What the store holds for this domain, so the experiment can prove it did
    not teach the substrate anything about its operators."""
    from core.learning.rule_store import get_rule_store
    return {r.rule_id: r.status.value
            for r in await get_rule_store().load(domain_id=domain)}


async def main():
    from core.database import get_database_manager
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.agents.autonomous.shared_types import Task, TaskType, TaskSource
    from core.execution.tool_domain import sensed_fact, take_up_workspace, term
    from core.integration.universal_domain_master import get_universal_domain_master
    from core.learning.meta_learning import OutcomeClass

    db = get_database_manager()
    await db.initialize()
    udm = get_universal_domain_master()
    await udm.initialize()

    root = Path(tempfile.mkdtemp(prefix="credit01-"))
    for d in ("inbox", "archive", "review"):
        (root / d).mkdir()

    print("=" * 62)
    print("CREDIT-01 — meant-vs-happened becomes operating credit")
    print("=" * 62)

    # ── A · the credit invariant lives at the authority ──────────────────────
    print("\n[A] the invariant holds where the posterior MOVES, not at call sites")
    denied = []
    for klass in (OutcomeClass.INSUFFICIENT_EVIDENCE, OutcomeClass.INDETERMINATE,
                  OutcomeClass.INFRASTRUCTURE_FAILURE, OutcomeClass.EXTERNAL_FAILURE,
                  OutcomeClass.INVALID_TASK):
        credited = await udm.record_operating_outcome(
            SYN, success=False, outcome_class=klass)
        denied.append((klass.value, credited))
    att, win = await counters(db, SYN)
    check("outcomes that establish nothing about operating are DENIED credit",
          all(c is False for _, c in denied),
          ", ".join(f"{k}={c}" for k, c in denied))
    check("a denied outcome does not even enter the DENOMINATOR",
          (att, win) == (0, 0),
          f"attempts={att} wins={win} after {len(denied)} denied outcome(s) — "
          f"counting them as attempts would dilute earned reliability")

    unclassified = await udm.record_operating_outcome(SYN, success=True)
    att, win = await counters(db, SYN)
    check("an UNCLASSIFIED outcome is denied (a caller that forgets loses the "
          "data point loudly rather than teaching a false one)",
          unclassified is False and (att, win) == (0, 0),
          f"returned {unclassified}, attempts={att}")

    ok_win = await udm.record_operating_outcome(
        SYN, success=True, outcome_class=OutcomeClass.SUCCESS)
    ok_loss = await udm.record_operating_outcome(
        SYN, success=False, outcome_class=OutcomeClass.EXECUTION_FAILURE)
    att, win = await counters(db, SYN)
    check("eligible outcomes DO move the posterior (the invariant is not a wall)",
          ok_win is True and ok_loss is True and (att, win) == (2, 1),
          f"attempts={att} wins={win}")

    # ── the live substrate ───────────────────────────────────────────────────
    # THE PRECONDITION IS DECLARED, NOT ASSUMED: the drives below plan over a
    # MOVE_FILE the substrate learned from its own acts, taught if it is not
    # there.
    check("the MOVE_FILE operator is held, or taught", await ensure_taught())
    coord = AutonomousCoordinator()
    await coord.initialize(start_loop=False)
    take_up_workspace(DOMAIN, str(root))

    completed = []

    async def _mc(tid, res, *a, **k):
        completed.append(tid)
        return True
    async def _mf(tid, err, *a, **k):
        return True
    coord.task_queue.mark_completed = _mc
    coord.task_queue.mark_failed = _mf

    # `_execute_and_validate_task` returns None — it DECIDES completion and files
    # outcomes rather than handing the result back. The drive's own result is what
    # the credit is read from, so it is captured here, at the substrate's own
    # executor, without altering what runs.
    drive_results = {}
    _execute_task = coord.execute_task

    async def capture(task):
        result = await _execute_task(task)
        drive_results[task.id] = result
        return result
    coord.execute_task = capture

    # A task whose completion belief does not reach the acceptance band is
    # fingerprinted as permanently failed and PERSISTED for the session. This run
    # must not leave that behind.
    failed_fps_before = set(coord._permanently_failed_fps)

    # THE STORE AT REST BEFORE THE BASELINE. It is shared with every run before
    # this one, and the induction drain processes EVERY pending signature, whoever
    # filed it — so a backlog left by an earlier run is induced on this run's
    # first act and reads as "this miss taught the substrate something". Measured:
    # run right after RECONCILE-01, a new rule appeared 0.4 s into this run, over a
    # batch holding six of that run's demonstrations. Drained here, through the
    # coordinator's own drain, so the baseline is the store at rest and the check
    # measures only what this run does.
    coord._induction_dirty = True
    await coord._coalesced_induction_drain()

    # WHAT THIS RUN WRITES IS REMOVED WITH IT. The cleanup below used to delete
    # only the intents the run formed, leaving the goals and plans that name them
    # — `active` goals whose steps point at intents that no longer exist (this
    # experiment's `MOVE_FILE(report.txt, inbox, archive)` was 166 of the 673 such
    # steps on the live store) — and the demonstrations its acts filed, which the
    # next process to wake the induction drain would learn from. Recorded at the
    # one place each is made, and removed by id.
    from core.learning.demonstration_store import get_demonstration_store
    demos = get_demonstration_store()
    filed, created_goals = [], []
    pending_before = {tuple(row) for row in await demos.pending_signatures()}
    _append, _create_goal = demos.append, coord.planning.create_goal

    async def recorded_append(example, *, domain_id):
        written = await _append(example, domain_id=domain_id)
        if written:          # every domain: its reading steps file into `tools:path` too
            filed.append(example.evidence_id)
        return written

    async def recorded_goal(*args, **kwargs):
        made = await _create_goal(*args, **kwargs)
        if made is not None:
            created_goals.append(made.id)
        return made
    demos.append, coord.planning.create_goal = recorded_append, recorded_goal

    att0, win0 = await counters(db, DOMAIN)
    rules_before = await rule_statuses(DOMAIN)
    intents_before = {r["intent_id"] for r in (await db.execute_query(
        "SELECT intent_id FROM unified.intents", (), fetch_all=True) or [])}
    print(f"\nBASELINE {DOMAIN}: attempts={att0} wins={win0} "
          f"rules={len(rules_before)}")

    # "Put report.txt in archive", in perception's words.
    GOAL = [sensed_fact("kind", "path", str(root / "archive" / "report.txt"), "file").to_formula(),
            "¬" + sensed_fact("kind", "path", str(root / "inbox" / "report.txt"), "file").to_formula()]

    def goal_task(conditions, desc):
        return Task(
            id=f"credit01_{uuid.uuid4().hex[:8]}",
            type=TaskType.EXECUTION,
            description=desc,
            source=TaskSource.AUTONOMOUS,
            provenance={"goal_conditions": conditions, "domain_id": DOMAIN},
        )

    async def drive(conditions, desc):
        """One task through the REAL path, returning what the substrate's own
        executor produced for it."""
        task = goal_task(conditions, desc)
        await coord._execute_and_validate_task(task)
        return task, drive_results.get(task.id)

    def stage():
        """Put the world back where a move to `archive` is the route."""
        for d in ("inbox", "archive", "review"):
            for f in (root / d).iterdir():
                if f.is_file():
                    f.unlink()
        (root / "inbox" / "report.txt").write_text("real content\n")

    try:
        # ── B1 · a goal that never planned ──────────────────────────────────
        print("\n[B1] a goal the substrate cannot PLAN operates nothing")
        unplannable = []
        for _ in range(2):
            stage()
            _, result = await drive([f"PAINTED({term('path', str(root / 'inbox' / 'report.txt'))}, RED)"],
                                    "paint the report red")
            unplannable.append(result)
        att1, win1 = await counters(db, DOMAIN)
        planning_declined = [r for r in unplannable
                             if isinstance(r, dict) and r.get("planning_status")]
        check("the planner declined honestly and the deficit was diagnosed",
              len(planning_declined) == 2
              and all(r.get("deficit") for r in planning_declined),
              ", ".join(f"{r.get('planning_status')}/"
                        f"{(r.get('deficit') or {}).get('deficit_type')}"
                        for r in planning_declined))
        check("NO operating outcome recorded for work that was never operated",
              (att1, win1) == (att0, win0),
              f"attempts {att0}→{att1}, wins {win0}→{win1} — a knowledge deficit "
              f"is not an operating failure")
        verdict = coord._operating_verdict(planning_declined[0], 0.1, False)
        check("the verdict names WHY it is not evidence about operating",
              verdict["read_from"] == "no operation was performed"
              and verdict["outcome_class"] is OutcomeClass.INSUFFICIENT_EVIDENCE,
              f"read_from={verdict['read_from']} class={verdict['outcome_class'].value}")

        # ── B2 · the aim is realized ────────────────────────────────────────
        print(f"\n[B2] {REACHED_RUNS} real drives where the aim IS realized")
        reached_results, reached_tasks = [], []
        for _ in range(REACHED_RUNS):
            stage()
            task, result = await drive(GOAL, "put report.txt in archive")
            reached_tasks.append(task)
            reached_results.append(result)
        on_disk = (root / "archive" / "report.txt").exists()
        att2, win2 = await counters(db, DOMAIN)
        realized = [r for r in reached_results
                    if (r.get("intent_outcome") or {}).get("matched_aim") is True]
        check("every drive really moved the file (the filesystem is the oracle)",
              on_disk and len(realized) == REACHED_RUNS,
              f"file_in_archive={on_disk} realized={len(realized)}/{REACHED_RUNS}")
        check("each realized aim credited exactly one operating WIN",
              (att2 - att1, win2 - win1) == (REACHED_RUNS, REACHED_RUNS),
              f"attempts Δ{att2-att1}, wins Δ{win2-win1}")
        v_reached = coord._operating_verdict(reached_results[0], 0.99, True)
        check("the win is read from the BELIEF, grounded in the reconciled intent",
              v_reached["read_from"] == "completion belief, grounded in the "
                                        "reconciled intent"
              and v_reached["success"] is True,
              f"read_from={v_reached['read_from']}")

        # THE BELIEF ITSELF. Before the plan path had a SAW grounding, a driven
        # plan was stuck on DID alone (~0.72) against a 0.95 acceptance band, so
        # the substrate marked every verifiably-successful drive NOT done.
        accepted = sum(1 for t in reached_tasks if t.id in completed)
        check("the substrate BELIEVES it did what it meant — the completion "
              "belief reaches done for a multi-step plan (measured 0/5 before "
              "the plan path had a world grounding)",
              accepted == REACHED_RUNS, f"{accepted}/{REACHED_RUNS} accepted")
        grounds = (reached_tasks[0].metadata or {}).get("completion_evidence") or []
        world_grounds = [g for g in grounds if g.get("channel") == "world_reobserve"]
        check("the belief was moved by a FRESH re-observation of what the plan "
              "MEANT (its goal conditions), independent of the act's own report",
              bool(world_grounds) and all(g.get("supports") for g in world_grounds)
              and any(g.get("epoch") == "saw" for g in world_grounds),
              ", ".join(f"{g.get('provenance')}→{g.get('supports')}"
                        for g in world_grounds) or "no world grounding")
        EV.metric("reached_runs_accepted_as_complete", accepted, "count",
                  note="the substrate's own belief that the goal holds; 0/5 "
                       "before the driven-plan path had a world grounding")

        # ── B3 · every step confirms and the aim is still missed ────────────
        print("\n[B3] the case per-step evidence CANNOT see: all steps confirm, "
              "aim unrealized")
        stage()
        original = coord._execute_grounded_operator

        async def step_then_world_changes(step_task):
            """An EXTERNAL actor moves the file back AFTER the step was verified.

            Nothing false is taught: the move really happened and the step's own
            evidence is a genuine CONFIRMATION. What the substrate must notice is
            that its AIM was still not realized — a fact no per-step verification
            can hold, because each step only ever checks its own predicted
            effects against the world.
            """
            result = await original(step_task)
            moved = root / "archive" / "report.txt"
            if result is not None and moved.exists():
                shutil.move(str(moved), str(root / "inbox" / "report.txt"))
            return result

        coord._execute_grounded_operator = step_then_world_changes
        try:
            missed_task, missed_result = await drive(
                GOAL, "put report.txt in archive")
        finally:
            coord._execute_grounded_operator = original
        att3, win3 = await counters(db, DOMAIN)

        # Only the OPERATOR steps carry runtime evidence. A preparatory reading —
        # which Law 2 requires before the route may act on a file it has not read
        # — is not part of the proved route and verifies no rule's effects.
        steps = [s for s in (missed_result.get("steps") or [])
                 if isinstance(s, dict) and s.get("execution_path") == "substrate"]
        from core.execution.effect_verification import RuntimeOutcome
        all_confirmed = bool(steps) and all(
            s.get("runtime_outcome") == RuntimeOutcome.CONFIRMATION.value
            for s in steps)
        check("every step's own runtime evidence CONFIRMED",
              all_confirmed,
              ", ".join(str(s.get("runtime_outcome")) for s in steps))
        intent_outcome = missed_result.get("intent_outcome") or {}
        check("the AIM was still not realized, and only meant-vs-happened says so",
              intent_outcome.get("matched_aim") is False
              and intent_outcome.get("goal_conditions_met") == [],
              f"matched_aim={intent_outcome.get('matched_aim')} "
              f"met={intent_outcome.get('goal_conditions_met')}")
        check("the miss credited an operating LOSS (attempt counted, no win)",
              (att3 - att2, win3 - win2) == (1, 0),
              f"attempts Δ{att3-att2}, wins Δ{win3-win2}")
        v_missed = coord._operating_verdict(missed_result, 0.2, False)
        check("the loss is read from the BELIEF, grounded in the reconciled intent",
              v_missed["read_from"] == "completion belief, grounded in the "
                                       "reconciled intent"
              and v_missed["success"] is False
              and v_missed["outcome_class"] is OutcomeClass.EXECUTION_FAILURE,
              f"read_from={v_missed['read_from']} success={v_missed['success']}")
        missed_grounds = [g for g in ((missed_task.metadata or {})
                                      .get("completion_evidence") or [])
                          if g.get("channel") == "world_reobserve"]
        check("the substrate does NOT believe it did what it meant — the fresh "
              "world grounding is evidence AGAINST the goal",
              bool(missed_grounds)
              and all(g.get("supports") is False for g in missed_grounds),
              ", ".join(f"{g.get('provenance')}→{g.get('supports')}"
                        for g in missed_grounds) or "no world grounding")
        rules_after = await rule_statuses(DOMAIN)
        check("no operator was taught anything by this miss (statuses unchanged)",
              rules_after == rules_before,
              f"{len(rules_before)} rule(s) before, {len(rules_after)} after — "
              f"{'identical' if rules_after == rules_before else 'CHANGED'}")

        # ── D · belief and world must agree, or neither is overruled ────────
        print("\n[D] an unresolved epistemic conflict is not a credit")
        believed_true = coord._operating_verdict(missed_result, 0.99, True)
        check("a HIGH completion posterior does NOT turn an unrealized aim into "
              "a win — the conflict is denied, not resolved in favour of either",
              believed_true["success"] is False
              and believed_true["outcome_class"] is OutcomeClass.INDETERMINATE
              and "disagree" in believed_true["read_from"],
              f"read_from={believed_true['read_from']} "
              f"class={believed_true['outcome_class'].value}")
        disbelieved = coord._operating_verdict(reached_results[0], 0.1, False)
        check("and the mirror: a LOW posterior does not turn a realized aim into "
              "a loss",
              disbelieved["success"] is False
              and disbelieved["outcome_class"] is OutcomeClass.INDETERMINATE,
              f"read_from={disbelieved['read_from']}")
        check("the guard is not swallowing the real runs — belief and world "
              "AGREED on every drive this experiment made",
              all((r.get("intent_outcome") or {}).get("matched_aim") is True
                  for r in reached_results)
              and (missed_result.get("intent_outcome") or {})
                  .get("matched_aim") is False
              and accepted == REACHED_RUNS
              and missed_task.id not in completed,
              f"{accepted}/{REACHED_RUNS} realized aims believed done, "
              f"miss believed done: {missed_task.id in completed}")

        # ── C · the corrected signal reaches its consumers ───────────────────
        print("\n[C] the signal reaches what consumes it")
        rel = await udm.operating_reliability(DOMAIN)
        credited_attempts = att3 - att0
        check("earned reliability is computed from the credited outcomes only",
              rel["attempts"] == att3 and rel["wins"] == win3
              and rel["enough_history"] is True,
              f"attempts={rel['attempts']} wins={rel['wins']} "
              f"earned={rel['earned']} win_rate={rel['win_rate']}")

        # What the same record WOULD have said if the two unplannable goals had
        # been credited as losses, as they were before this change.
        from core.agents.autonomous.idle_work_playbook import StrategyAdaptationGate
        polluted_lo, _ = StrategyAdaptationGate._wilson_ci(win3, att3 + 2)
        check("crediting the never-operated goals would have LOWERED earned "
              "reliability on work the substrate never did",
              round(polluted_lo, 4) < rel["earned"],
              f"earned={rel['earned']} vs {round(polluted_lo, 4)} had the two "
              f"unplannable goals counted as operating failures")

        operability = await coord._domain_operability(DOMAIN)
        band = coord._OPERABILITY_BAND
        expected_bar = round(max(coord._OPERABILITY_FLOOR,
                                 min(coord._OPERABILITY_CEIL,
                                     operability["stakes"] - band * (rel["earned"] - 0.5))), 4)
        check("the KNOW→DO bar moved with it, by the bar's own rule",
              operability["bar"] == expected_bar and operability["earned"] == rel["earned"],
              f"bar={operability['bar']} stakes={operability['stakes']} "
              f"earned={operability['earned']}")

        engine = await coord._get_planning_engine()
        from core.agents.autonomous.shared_types import Priority
        goal_obj = await engine.create_goal(
            "[substrate goal] put report.txt in archive", Priority.MEDIUM,
            state_conditions=GOAL)
        inputs = await engine.assemble_inputs(
            "state", goal_obj, {"domain_id": DOMAIN,
                                "world_state": sorted(str(f) for f in
                                                      (coord._observe_world(DOMAIN) or []))})
        declared = (inputs.get("gathered") or {}).get("operating_reliability") or {}
        check("the planner's DECLARED input carries the corrected number, from "
              "the domain authority",
              declared.get("source") == "domain authority"
              and declared.get("earned") == rel["earned"],
              f"source={declared.get('source')} earned={declared.get('earned')}")

        EV.metric("operating_attempts_credited", credited_attempts, "count")
        EV.metric("operating_wins_credited", win3 - win0, "count")
        EV.metric("earned_reliability", rel["earned"], "fraction")
        EV.metric("earned_if_never_operated_counted", round(polluted_lo, 4), "fraction",
                  note="the same record with the two unplannable goals credited "
                       "as losses, which is what happened before this change")
        EV.metric("know_do_bar", operability["bar"], "fraction")
        EV.metric("denied_outcome_classes", [k for k, _ in denied])
    finally:
        # ── restore everything this run touched ─────────────────────────────
        await db.execute_query(
            "UPDATE unified.domain_controllability SET operating_attempts=$2, "
            "operating_wins=$3 WHERE domain_id=$1", (DOMAIN, att0, win0), commit=True)
        for table in ("unified.domain_controllability", "unified.domains"):
            await db.execute_query(f"DELETE FROM {table} WHERE domain_id=$1",
                                   (SYN,), commit=True)
        # The failed-work store is insert-only; this run's rows are removed by
        # fingerprint, the ones recorded before it are left as they were.
        added_fps = sorted(set(coord._permanently_failed_fps) - failed_fps_before)
        coord._permanently_failed_fps = failed_fps_before
        if added_fps:
            await db.execute_query(
                "DELETE FROM unified.failed_task_fingerprints "
                "WHERE fingerprint = ANY($1::text[])", (added_fps,), commit=True,
                store="runtime")
        del demos.append                     # the store's own method again
        coord.planning.create_goal = _create_goal
        if filed:
            await db.execute_query(
                "DELETE FROM unified.operator_demonstrations "
                "WHERE evidence_id = ANY($1::text[])", (filed,), commit=True)
        for domain_id, predicate, arity in await demos.pending_signatures():
            if (domain_id, predicate, arity) not in pending_before:
                await demos.clear_pending(domain_id=domain_id, predicate=predicate,
                                          arity=arity)
        if created_goals:
            await db.execute_query(
                "DELETE FROM unified.plans WHERE goal_id = ANY($1::text[])",
                (created_goals,), commit=True)
            await db.execute_query(
                "DELETE FROM unified.goals WHERE id::text = ANY($1::text[])",
                (created_goals,), commit=True)
        rows = await db.execute_query(
            "SELECT intent_id FROM unified.intents", (), fetch_all=True) or []
        for row in rows:
            if row["intent_id"] in intents_before:
                continue
            for table in ("unified.scoped_intents", "unified.intents"):
                await db.execute_query(
                    f"DELETE FROM {table} WHERE intent_id = $1",
                    (row["intent_id"],), commit=True)
        shutil.rmtree(root, ignore_errors=True)

    restored = await counters(db, DOMAIN)
    print(f"\nrestored {DOMAIN} counters → attempts={restored[0]} wins={restored[1]}")

    await EV.verify_database()
    EV.write()
    print("\n" + "=" * 62)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
