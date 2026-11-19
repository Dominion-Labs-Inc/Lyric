#!/usr/bin/env python3
"""Lift a standing Constitution halt, or say what one is.

A halt is DURABLE: the Constitution writes it to `unified.emergency_halts` and reads it back at every start
(`AutonomousCoordinator.restore_halt`), so a halted substrate comes up halted and permits no act. Law 1 puts
lifting it in human hands, and `AutonomousCoordinator.resume` refuses any caller that is the substrate.

THERE WAS NO DOOR FOR THE HUMAN. `resume(authorized_by=...)` is a coordinator method, so lifting a halt meant
starting a substrate -- five minutes of warm, and a substrate is exactly what the halt says must not run. A
containment only a human may lift, with no way for a human to lift it, stops being a containment and becomes an
outage. This is that door.

It writes the same event `_write_halt_event("resume", ...)` writes, which is all `restore_halt` reads, and it
applies the same rule: the name given must be a person's, never the substrate's. It starts nothing, warms
nothing and touches no other table.

  ./venv_lyric/bin/python3 scripts/resume.py                 # say whether a halt stands, and what it says
  ./venv_lyric/bin/python3 scripts/resume.py --by <name>     # lift it, recorded as lifted by that person

Exit 0 where it said or lifted; 1 where a halt stands and was not lifted, or the name was refused.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: The newest halt or resume THE CONSTITUTION wrote decides, exactly as `restore_halt` reads it: other writers
#: of this table may not mask a standing halt.
_STANDING = (
    "SELECT reason, timestamp, metadata FROM unified.emergency_halts "
    "WHERE metadata->>'source' = 'constitution' "
    "AND COALESCE(metadata->>'event', 'halt') IN ('halt', 'resume') "
    "ORDER BY timestamp DESC LIMIT 1"
)


def _meta(row) -> dict:
    meta = row.get("metadata") if isinstance(row, dict) else row["metadata"]
    if isinstance(meta, str):
        try:
            return json.loads(meta or "{}")
        except ValueError:
            return {}
    return dict(meta or {})


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--by", default=None,
                        help="the person lifting it, recorded in the containment log")
    args = parser.parse_args()

    from core.agents.autonomous.shared_types import is_substrate_actor
    from core.database import get_database_manager

    db = get_database_manager()
    await db.initialize()

    rows = await db.execute_query(_STANDING, ()) or []
    if not rows:
        print("no halt and no resume has ever been recorded: nothing is standing.")
        return 0
    row, meta = rows[0], _meta(rows[0])
    event = str(meta.get("event", "halt"))
    if event != "halt":
        print(f"no halt stands. The last containment event was a {event} "
              f"by {meta.get('by') or 'someone unrecorded'} at {row['timestamp']}.")
        return 0

    print("A HALT STANDS. Nothing this substrate is asked to do will be permitted.")
    print(f"   since : {row['timestamp']}")
    print(f"   by    : {meta.get('by') or 'unrecorded'}")
    print(f"   reason: {row['reason']}")

    if not args.by:
        print("\nTo lift it, say who is lifting it:  "
              "./venv_lyric/bin/python3 scripts/resume.py --by <name>")
        return 1

    who = str(args.by).strip()
    # THE SAME RULE THE METHOD APPLIES. A defence the defended party can lift is not one, so the substrate's own
    # name is refused here as it is there (`AutonomousCoordinator.resume`).
    if not who or is_substrate_actor(who):
        print(f"\nREFUSED: a halt is lifted by a human, and {args.by!r} is not one.")
        return 1

    await db.execute_query(
        "INSERT INTO unified.emergency_halts (reason, active_actions, timestamp, metadata) "
        "VALUES ($1,$2,$3,$4)",
        (str(row["reason"]), "", datetime.now(),
         json.dumps({"event": "resume", "by": who, "source": "constitution",
                     "lifted": str(row["reason"]), "halted_at": str(row["timestamp"])},
                    default=str)),
        commit=True)

    again = await db.execute_query(_STANDING, ()) or []
    lifted = bool(again) and str(_meta(again[0]).get("event", "halt")) == "resume"
    print(f"\n{'LIFTED' if lifted else 'NOT LIFTED'} — recorded as lifted by {who}.")
    if lifted:
        print("The next start will come up running. The halt itself is kept in the log, not deleted.")
    return 0 if lifted else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
