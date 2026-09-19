#!/usr/bin/env python3
"""INTENT-01 — the intent authority, on the real substrate.

Intent is the substrate's own account of what it is trying to do and why, owned
by the reasoning authority (see docs/design/INTENT_AUTHORITY.md). This proves the
foundation, against real Postgres, nothing mocked:

  1. forming an intent when reasoning engages creates it (shape + scoped content);
  2. returning to it REFRESHES the same intent — same id, version up, history
     grown — rather than rebuilding it;
  3. a GOAL raised inside a thread is its OWN intent, parented to the thread and
     resolved by its own key, so it cannot collapse into the conversation intent
     (the flat-key trap);
  4. the content/shape split holds: the substrate-wide view carries no actor and
     no content;
  5. the outcome reconciles onto the intent (meant-vs-happened, for learning);
  6. it SURVIVES A RESTART — a separate interpreter reads it all back;
  7. forgetting the actor removes content and continuity while the anonymous
     shape (the lesson) survives.

The restart check spawns a fresh `./venv_torin/bin/python3`, so persistence is
proven across a real process boundary, not asserted.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import RunRecord  # noqa: E402
from core.reasoning.intent_authority import (  # noqa: E402
    get_intent_authority, continuity_thread, continuity_goal)

os.environ.setdefault("TORIN_SHADOW_MODE", "1")

PASS = FAIL = 0
EV = RunRecord(
    "INTENT-01",
    claim="Intent is a first-class, durable, reasoning-owned entity: formed on "
          "engagement, refreshed not rebuilt, tree-structured so a goal never "
          "collapses into its thread, split into substrate-wide shape and "
          "actor-scoped content, and surviving a restart.",
    hypothesis="If the reasoning authority owns intent and persists it split by "
               "shape/content, then a return refreshes the same node, a goal "
               "raised in a thread is a distinct parented intent, the outcome "
               "reconciles onto it, it survives a fresh process, and forgetting "
               "the actor leaves the anonymous shape behind.")


def check(label, ok, detail=""):
    global PASS, FAIL
    EV.check(label, ok, detail)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


async def readback(actor, thread_id, goal_id, thread_intent_id, goal_intent_id):
    """Run in a FRESH interpreter (see __main__): read the intents back and print
    a JSON verdict. Success here is durability across a real process boundary."""
    A = get_intent_authority()
    t = await A.get(actor, continuity_thread(thread_id))
    g = await A.get_by_id(goal_intent_id, actor=actor)
    result = {
        "thread_reloaded": bool(t and t.intent_id == thread_intent_id),
        "thread_version": t.version if t else None,
        "thread_aim": t.aim if t else None,
        "goal_reloaded": bool(g and g.intent_id == goal_intent_id),
        "goal_outcome_class": (g.outcome or {}).get("outcome_class") if g else None,
        "goal_operator": g.operator if g else None,
        "goal_parent": g.parent_intent_id if g else None,
    }
    print("READBACK " + json.dumps(result))
    return result


async def main():
    A = get_intent_authority()
    run = uuid.uuid4().hex[:8]
    actor = f"intent01_{run}"
    thread_id = f"thread_{run}"
    goal_id = f"goal_{run}"

    print("\n== A. Form on engagement ==")
    t1 = await A.form("thread", actor, continuity_thread(thread_id),
                      shape={"reasoning_mode": "read_message"},
                      content={"aim": "help archive a report", "topic": "archiving",
                               "message": "please file report.txt"})
    check("forming a thread intent creates it",
          bool(t1.intent_id) and t1.version == 1 and t1.status == "forming",
          f"id={t1.intent_id[:8]} v{t1.version} {t1.status}")

    print("\n== B. Return refreshes, does not rebuild ==")
    t2 = await A.form("thread", actor, continuity_thread(thread_id),
                      content={"aim": "archive report.txt into /archive",
                               "topic": "archiving"})
    check("a return keeps the same intent id", t2.intent_id == t1.intent_id,
          f"{t2.intent_id[:8]} == {t1.intent_id[:8]}")
    check("refresh bumps version and appends history, not a new intent",
          t2.version == 2 and len(t2.history) == 1,
          f"v{t2.version}, history={len(t2.history)}")
    check("refreshed content is the newer understanding",
          t2.aim == "archive report.txt into /archive", t2.aim)

    print("\n== C. A goal raised inside the thread is its own intent ==")
    g = await A.form("goal", actor, continuity_goal(goal_id),
                     parent_intent_id=t1.intent_id,
                     shape={"operator": "MOVE_FILE",
                            "goal_conditions": ["FILE_IN(report, archive)"],
                            "proved": True, "rule_id": "rule_x", "domain": "fs"},
                     content={"aim": "move report.txt", "bound": {"f": "report.txt"}})
    check("the goal is a distinct intent, not the thread's",
          g.intent_id != t1.intent_id, f"goal={g.intent_id[:8]} thread={t1.intent_id[:8]}")
    check("the goal is parented to the thread it was raised in",
          g.parent_intent_id == t1.intent_id, g.parent_intent_id[:8] if g.parent_intent_id else None)
    by_goal = await A.get(actor, continuity_goal(goal_id))
    by_thread = await A.get(actor, continuity_thread(thread_id))
    check("goal key and thread key resolve to different intents (no collision)",
          by_goal.intent_id == g.intent_id and by_thread.intent_id == t1.intent_id
          and by_goal.intent_id != by_thread.intent_id,
          f"goalkey->{by_goal.intent_id[:8]} threadkey->{by_thread.intent_id[:8]}")
    check("the proved goal reads as stated (operator + goal + proof)", g.stated(),
          f"operator={g.operator} proved={g.proved}")

    print("\n== D. Content vs shape split ==")
    sv = g.shape_view()
    check("the substrate-wide view carries no actor and no content",
          sv.actor == "" and sv.content == {} and sv.operator == "MOVE_FILE",
          f"actor={sv.actor!r} content={sv.content} operator={sv.operator}")

    print("\n== E. Reconcile the outcome ==")
    await A.reconcile(g.intent_id, {"outcome_class": "success", "matched_aim": True},
                      status="fulfilled")
    shape_only = await A.get_by_id(g.intent_id)          # no actor -> shape view
    check("the outcome attaches to the intent, substrate-wide",
          shape_only.outcome and shape_only.outcome["outcome_class"] == "success"
          and shape_only.status == "fulfilled" and shape_only.content == {},
          f"outcome={shape_only.outcome} status={shape_only.status}")

    print("\n== F. Survives a restart (a fresh interpreter reads it back) ==")
    payload = {"actor": actor, "thread_id": thread_id, "goal_id": goal_id,
               "thread_intent_id": t1.intent_id, "goal_intent_id": g.intent_id}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        payload_path = fh.name
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--readback", payload_path],
        capture_output=True, text=True)
    rb = None
    for line in proc.stdout.splitlines():
        if line.startswith("READBACK "):
            rb = json.loads(line[len("READBACK "):])
    os.unlink(payload_path)
    check("a fresh process reloads the thread intent at its latest version",
          bool(rb) and rb["thread_reloaded"] and rb["thread_version"] == 2
          and rb["thread_aim"] == "archive report.txt into /archive",
          json.dumps(rb) if rb else f"no readback (rc={proc.returncode}): {proc.stderr[-300:]}")
    check("a fresh process reloads the goal intent with its outcome and parent",
          bool(rb) and rb["goal_reloaded"] and rb["goal_outcome_class"] == "success"
          and rb["goal_operator"] == "MOVE_FILE" and rb["goal_parent"] == t1.intent_id,
          json.dumps(rb) if rb else "no readback")

    print("\n== G. Forget the actor: content goes, the anonymous shape stays ==")
    removed = await A.forget_actor(actor)
    gone = await A.get_by_id(g.intent_id, actor=actor)      # content view
    survives = await A.get_by_id(g.intent_id)               # shape view
    check("forgetting the actor removes their content + continuity",
          removed >= 2 and gone is None, f"removed {removed} rows, full_view={gone}")
    check("the anonymous shape (the lesson) survives the actor's deletion",
          survives is not None and survives.operator == "MOVE_FILE"
          and survives.outcome and survives.outcome["outcome_class"] == "success",
          f"operator={survives.operator if survives else None}")

    EV.metric("intents_formed", 2, "count", "one thread, one goal")
    EV.metric("refresh_version_reached", t2.version, "version")
    EV.metric("actor_content_rows_removed", removed, "count")
    EV.metric("restart_readback_ok",
              bool(rb and rb["thread_reloaded"] and rb["goal_reloaded"]))

    # Self-cleaning: the scoped rows are already gone (forget_actor); remove this
    # run's shape rows too so the table is left as it was found.
    await A.store._ready()
    await A.store.db.execute_query(
        "DELETE FROM unified.intents WHERE intent_id = ANY($1::text[])",
        ([t1.intent_id, g.intent_id],), commit=True)

    # Ask the SERVER which database this actually ran against, rather than
    # letting the record say the database was 'not recorded'.
    await EV.verify_database()
    EV.write()
    print("\n" + "=" * 60)
    print(f"RESULT: {PASS}/{PASS + FAIL} checks passed")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--readback"]:
        data = json.load(open(sys.argv[2]))
        asyncio.run(readback(data["actor"], data["thread_id"], data["goal_id"],
                             data["thread_intent_id"], data["goal_intent_id"]))
    else:
        sys.exit(asyncio.run(main()) or 0)
