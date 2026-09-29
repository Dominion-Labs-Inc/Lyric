#!/usr/bin/env python3
"""ONE-TIME REPAIR — recompute beliefs whose evidence was counted more than once.

WHAT WENT WRONG. Evidence carried only `{quality, source}`: nothing said WHICH
observation it was. A standing fact re-read at every boot therefore appended an
entry and moved the posterior every time, so the substrate grew certain of
things by restarting. `misp_get_event provides get_system_info` holds 690
evidence entries of which THREE are distinct, at posterior 0.999999.

The code defect is fixed (`observe_claim(..., observation=...)`, IDEMPOTENT-01,
proven across real restarts). Fixing it does not undo the history, which is what
this is for.

WHAT THIS DOES. For every belief whose SUPPORTING evidence holds byte-identical
duplicates FROM THE `taught` PRODUCER: drop the duplicates, and recompute the
posterior by replaying the substrate's OWN kernel -- `posterior_from_evidence`, "the ONE place this math
lives" -- once per surviving entry. The odds update is commutative
(new_odds = prior_odds * prod(lr_i)), so the replay is closed form and does not
depend on an ordering the store never kept.

THE ONE THING IT CANNOT DO, STATED PLAINLY. `update_belief` applies temporal
decay before each update, and evidence entries carry no per-entry timestamp, so
the decay history cannot be replayed. Measured on 400 UNDAMAGED beliefs (where
the replay must reproduce what is stored): 93.0% exact to 1e-9, 98.2% within
1e-6, 100% within 1e-3, worst 1.9e-05. So the omission is real and negligible,
and it biases very slightly HIGH -- the repaired posteriors are, if anything, a
touch more confident than a faithful replay, never less.

Dry run by default. `--apply` writes.

Run: PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan \
     TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 \
     scripts/repair_double_counted_beliefs.py [--apply]
"""
import asyncio
import json
import os
import sys
from pathlib import Path

for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1",
               "TORIN_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.reasoning.bayesian_uncertainty import (  # noqa: E402
    belief_entropy, clamp_posterior, posterior_from_evidence)

SNAPSHOT = "unified.beliefs_snapshot_20260920_predup"
BATCH = 500


def _entries(value):
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    return parsed if isinstance(parsed, list) else []


#: The ONLY source this repair collapses, and the reason is not squeamishness.
#: `_fan_out_learning` hardcoded `source="taught"`, and admission already
#: deduplicates within a process — so a duplicate `taught` entry can ONLY have
#: come from re-admission in a later process, which is precisely the defect.
#: Every other producer is left alone because byte-identity does NOT prove same
#: observation: an evidence dict is `{quality, source}` with no timestamp, so
#: seventy genuine repeated checks serialise identically to one check recorded
#: seventy times, and nothing in the row can tell them apart.
REPAIRABLE_SOURCE = "taught"


def _dedup(entries, *, only_source=REPAIRABLE_SOURCE):
    """Collapse byte-identical entries FROM THE AFFECTED PRODUCER ONLY.

    THE BLANKET VERSION OF THIS WOULD HAVE FLIPPED A SECURITY BELIEF. Dry-run
    over every source proposed collapsing 71 identical counter-evidence entries
    on "security findings are present in the system" — taking it from 0.000013
    to 0.997635, false to true. Those 71 are far more likely to be 71 separate
    scans that each found nothing than one scan recorded 71 times, and the
    stored row cannot distinguish them. Measured scope of what is left alone:
    11 beliefs hold duplicated counter-evidence, and the duplicated supporting
    evidence outside `taught` is 398 entries across 13 beliefs.
    """
    seen, kept = set(), []
    for entry in entries:
        source = entry.get("source") if isinstance(entry, dict) else None
        if source != only_source:
            kept.append(entry)          # not ours to judge
            continue
        key = json.dumps(entry, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            kept.append(entry)
    return kept


def _replay(prior, for_entries, against_entries, default_quality=0.9):
    posterior = float(prior)
    for entry in for_entries:
        quality = entry.get("quality", default_quality) if isinstance(entry, dict) else default_quality
        posterior, _ = posterior_from_evidence(posterior, float(quality), True)
    for entry in against_entries:
        quality = entry.get("quality", default_quality) if isinstance(entry, dict) else default_quality
        posterior, _ = posterior_from_evidence(posterior, float(quality), False)
    return clamp_posterior(posterior)


async def main(apply: bool) -> int:
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()

    guard = await db.execute_query(
        "SELECT COUNT(*) n FROM information_schema.tables "
        "WHERE table_schema = $1 AND table_name = $2",
        tuple(SNAPSHOT.split(".")), fetch_one=True)
    if not int(guard["n"]):
        print(f"REFUSING: snapshot {SNAPSHOT} does not exist. "
              f"A repair with no way back is not a repair.")
        return 2
    print(f"snapshot present: {SNAPSHOT}")

    rows = await db.execute_query(
        """SELECT belief_id, claim, domain, prior_probability pr,
                  posterior_probability po, evidence_for, evidence_against,
                  update_count u
           FROM unified.beliefs
           WHERE (evidence_for IS NOT NULL AND jsonb_array_length(evidence_for) >
                  (SELECT COUNT(DISTINCT e) FROM jsonb_array_elements(evidence_for) e))
              OR (evidence_against IS NOT NULL AND jsonb_array_length(evidence_against) >
                  (SELECT COUNT(DISTINCT e) FROM jsonb_array_elements(evidence_against) e))
        """, (), fetch_all=True) or []
    print(f"beliefs carrying duplicate evidence: {len(rows):,}\n")

    planned, dropped_total, deltas = [], 0, []
    for row in rows:
        ef, ea = _entries(row["evidence_for"]), _entries(row["evidence_against"])
        # COUNTER-EVIDENCE IS NOT TOUCHED AT ALL. The defect was a standing fact
        # re-READ; a claim refuted repeatedly is the ordinary shape of a
        # recurring check, and there are only 11 such beliefs.
        kf, ka = _dedup(ef), ea
        dropped = (len(ef) - len(kf)) + (len(ea) - len(ka))
        if not dropped:
            continue
        posterior = _replay(row["pr"], kf, ka)
        deltas.append(float(row["po"]) - posterior)
        dropped_total += dropped
        planned.append((row["belief_id"], posterior, belief_entropy(posterior),
                        json.dumps(kf), json.dumps(ka), len(kf) + len(ka)))

    print(f"beliefs to repair          : {len(planned):,}")
    print(f"redundant entries to drop  : {dropped_total:,}")
    if deltas:
        deltas.sort()
        n = len(deltas)
        print(f"posterior falls by         : median {deltas[n // 2]:.6f}   "
              f"max {deltas[-1]:.6f}   min {deltas[0]:.6f}")
    print("\nsample:")
    for belief_id, posterior, _, kf, ka, count in planned[:8]:
        before = next(r for r in rows if r["belief_id"] == belief_id)
        print(f"  {str(before['claim'])[:40]:42} {float(before['po']):.9f} -> "
              f"{posterior:.9f}   evidence {int(before['u'])} -> {count}")

    if not apply:
        print(f"\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    written = 0
    for start in range(0, len(planned), BATCH):
        for belief_id, posterior, entropy, kf, ka, count in planned[start:start + BATCH]:
            await db.execute_query(
                """UPDATE unified.beliefs
                   SET posterior_probability = $2, confidence = $2, entropy = $3,
                       evidence_for = $4::jsonb, evidence_against = $5::jsonb,
                       update_count = $6
                   WHERE belief_id = $1""",
                (belief_id, posterior, entropy, kf, ka, count), commit=True)
            written += 1
        print(f"  ...{written:,}/{len(planned):,}")

    left = await db.execute_query(
        """SELECT COUNT(*) n FROM unified.beliefs
           WHERE evidence_for IS NOT NULL AND jsonb_array_length(evidence_for) >
                 (SELECT COUNT(DISTINCT e) FROM jsonb_array_elements(evidence_for) e)""",
        (), fetch_one=True)
    print(f"\nrepaired {written:,}; beliefs still holding duplicates: "
          f"{int(left['n']):,}")
    return 0


sys.exit(asyncio.run(main("--apply" in sys.argv)))
