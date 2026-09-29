#!/usr/bin/env python3
"""IDEMPOTENT-01 — re-teaching a fact must not make it truer.

Showing a network the same data again is training. Showing a Bayesian belief the
same evidence again FABRICATES A SECOND WITNESS, and the substrate had been
doing exactly that on every boot.

Evidence carried only `{quality, source}` — nothing said WHICH observation it
was — so a standing fact re-read at startup appended an entry and moved the
posterior every time. Measured on the live store before the fix:

    beliefs observed  >10 times     3,395   (3,220 of them in the `tools` domain)
    beliefs observed >100 times     2,588
    worst single belief               674 observations, posterior 0.999999
        "misp_get_event provides get_system_info"

The substrate was near-certain of a tool's declared signature because it had
rebooted 674 times. One witness, counted 674 times.

The identity already existed and was dropped at the seam: `submit_tool_capability`
stamps `evidence_id=_stable_id("toolcap", name)` — identical on every boot — and
the comment beside it says "the envelope id already collapses them in the store".
It did, for the concept layer. It never reached the belief layer, because
`_fan_out_learning` passed `source="taught"` and nothing else.

THIS MUST BE PROVEN ACROSS A REAL RESTART, and that is the whole point: the
ingress already deduplicated on `subject|relation|object|source_id`, but against
`self._seen` — a plain set on a singleton. It worked perfectly within one process
and vanished with it. So each phase below runs in its OWN interpreter.

  A  A FACT IS TAUGHT        first telling creates the belief.
  B  RE-TAUGHT, FRESH        same fact, same source, NEW PROCESS: posterior,
     PROCESS, NO CHANGE      update_count and evidence count all unmoved.
  C  A DIFFERENT WITNESS     same fact, DIFFERENT source: the posterior DOES
     STILL COUNTS            move — this fixes double counting, it does not
                             freeze beliefs.

Run: PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/IDEMPOTENT-01/experiment.py
"""
import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(ROOT))


async def _teach_and_report(subject: str, source_id: str) -> dict:
    """Teach ONE fact through the one path, then read the belief back FROM THE
    DATABASE -- not from memory, which is the thing under test."""
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.database import get_database_manager
        from core.main import get_system
        from core.semantics.cognitive_ingress import Provenance

        system = get_system()
        await system.initialize()
        learning = system.autonomous_coordinator.learning
        db = get_database_manager()

        claim = f"{subject} isa idempotentkind"
        await learning.learn_facts(
            [(subject, "isa", "idempotentkind")],
            domain="idempotent01", quality=0.9,
            provenance=Provenance(producer="idempotent01", source_id=source_id,
                                  source_type="USER_SUPPLIED"))
        # Beliefs are written through; read the committed row.
        us = __import__("core.reasoning.bayesian_uncertainty",
                        fromlist=["get_uncertainty_system"]).get_uncertainty_system()
        with contextlib.suppress(Exception):
            await us.flush_pending_writes()
        for belief in list(us.beliefs.values()):
            if us._claim_key(belief.claim) == us._claim_key(claim):
                with contextlib.suppress(Exception):
                    await us.flush_belief(belief.belief_id)

        row = await db.execute_query(
            "SELECT posterior_probability p, update_count u, "
            "       COALESCE(jsonb_array_length(evidence_for), 0) e "
            "FROM unified.beliefs WHERE lower(claim) = lower($1) LIMIT 1",
            (claim,), fetch_one=True)
    return {"posterior": float(row["p"]) if row else None,
            "updates": int(row["u"]) if row else None,
            "evidence": int(row["e"]) if row else None} if row else {}


def _phase(subject: str, source_id: str) -> dict:
    """Run one teaching in a SEPARATE interpreter — a real restart."""
    out = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--teach", subject, source_id],
        cwd=str(ROOT), capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)})
    for line in reversed(out.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"phase produced no result:\n{out.stdout[-2000:]}\n"
                       f"{out.stderr[-2000:]}")


if len(sys.argv) > 1 and sys.argv[1] == "--teach":
    print(json.dumps(asyncio.run(_teach_and_report(sys.argv[2], sys.argv[3]))))
    sys.exit(0)

PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    good = got == want
    PASS, FAIL = PASS + good, FAIL + (not good)
    print(f"  {'PASS' if good else 'FAIL'}  {label}")
    if not good:
        print(f"          got={got!r}  want={want!r}")


print(__doc__.split("Run:")[0].rstrip())
SUBJECT = f"idem{time.strftime('%H%M%S')}"

print("\n" + "=" * 72)
print("A  A FACT IS TAUGHT   (process 1)")
print("=" * 72)
first = _phase(SUBJECT, "witness-one")
print(f"  posterior={first['posterior']:.9f}  updates={first['updates']}  "
      f"evidence={first['evidence']}")
check("the belief exists", first.get("posterior") is not None, True)

print("\n" + "=" * 72)
print("B  RE-TAUGHT IN A FRESH PROCESS, SAME WITNESS   (process 2)")
print("=" * 72)
again = _phase(SUBJECT, "witness-one")
print(f"  posterior={again['posterior']:.9f}  updates={again['updates']}  "
      f"evidence={again['evidence']}")
check("the posterior did not move", again["posterior"], first["posterior"])
check("update_count did not rise", again["updates"], first["updates"])
check("no evidence entry was appended", again["evidence"], first["evidence"])

print("\n" + "=" * 72)
print("C  A DIFFERENT WITNESS STILL COUNTS   (process 3)")
print("=" * 72)
other = _phase(SUBJECT, "witness-two")
print(f"  posterior={other['posterior']:.9f}  updates={other['updates']}  "
      f"evidence={other['evidence']}")
check("a genuinely new witness appends evidence",
      other["evidence"] > first["evidence"], True)
check("and moves the posterior", other["posterior"] != first["posterior"], True)

print("\n" + "=" * 72)
print(f"{PASS}/{PASS + FAIL}")
print("=" * 72)
sys.exit(0 if not FAIL else 1)
