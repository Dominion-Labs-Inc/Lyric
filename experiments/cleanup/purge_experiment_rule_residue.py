#!/usr/bin/env python3
"""Remove the classification rules that are experiment residue, not knowledge.

Every classification rule in the store belongs to an experiment run, and says so
in its own name: the domain it is filed under (`seec290e1`, `probe2_0b96e7`,
`rfx620efe`, `vis4d2413`) or the category it concludes (`catc290e1cire`,
`stopsignb6f5e2`, `gtfd64ff`) carries the run's `uuid4().hex[:6]`. That is how
each perception experiment mints collision-free names, so the name is the
evidence of what the rule is: a fixture, generalised correctly from stimuli drawn
for one run and meaningless outside it.

Measured 2026-09-19: 46 of 46. **The substrate has not yet been taught a single
visual category outside an experiment** — which is worth recording plainly rather
than leaving implied by an empty KEPT list.

This mattered the moment naming became a reflex (`Coordinator.recognise_sensed`).
Until then the rules sat inert, because recognition only happened when something
asked about one category by name. Now every rule is weighed against every blob
seen, and RECOGNISE-01 measured one green triangle collecting eleven names, all
of them residue. The substrate was behaving correctly over a store that was 98%
debris.

They accumulated because of a defect, now fixed: six experiments deleted their
rules with `rule_identity_aliases WHERE rule_id`, a column that table does not
have (it keys on `canonical_rule_id`). The query raised, a `suppress(Exception)`
swallowed it, and the rule survived AFTER its evidence had already been deleted.
`RuleStore.forget` owns this now and raises rather than half-succeeding.

DELETED, not marked REFUTED. Refuted means evidence showed a hypothesis false.
These were never false -- they are correct generalisations of stimuli that no
longer exist, and filing them as negative findings would put fabricated results
in the learning record.

A census runs first, and every rule is printed with its id, domain and formula
before anything is removed. Nothing in the repository references these ids (a
sweep of every .json and .md found zero), so no recorded result depends on them.

    ./venv_torin/bin/python3 experiments/cleanup/purge_experiment_rule_residue.py
    ./venv_torin/bin/python3 experiments/cleanup/purge_experiment_rule_residue.py --yes
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(_k, _v)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from core.database import get_database_manager          # noqa: E402
from core.learning.rule_store import get_rule_store     # noqa: E402

#: A run id as the experiments mint it: `uuid4().hex[:6]`. It appears wherever
#: the experiment needed a collision-free name, which is the DOMAIN it files
#: under (`seec290e1`, `probe2_0b96e7`, `rfx620efe`) and often the CATEGORY too
#: (`catc290e1cire` -- note the id sits in the MIDDLE there, so this is a search,
#: not a match). Either one marks the rule as belonging to a run.
#:
#: This is a signature, not a proof, and it is not left to decide on its own:
#: the script prints the complete partition and refuses to delete anything
#: without `--yes`, so what goes and what stays is read before it happens.
RUN_ID = re.compile(r"[0-9a-f]{6,}")

REFERENCE_COLUMNS = [
    ("unified.learned_rule_evidence", "rule_id"),
    ("unified.rule_authority_events", "rule_id"),
    ("unified.rule_projections", "rule_id"),
    ("unified.rule_supersessions", "superseded_rule_id"),
    ("unified.rule_supersessions", "replacement_rule_id"),
    ("unified.learned_rules", "supersedes_rule_id"),
    ("unified.rule_identity_aliases", "canonical_rule_id"),
]


async def main() -> int:
    dry = "--dry-run" in sys.argv
    db = get_database_manager()
    await db.initialize()
    store = get_rule_store()

    stored = await store.load()
    classification = [s for s in stored if s.rule_kind == "classification"]
    residue, kept = [], []
    for s in classification:
        heads = sorted({f.predicate for f in s.rule.effects.add})
        marked = bool(RUN_ID.search(s.domain_id or "")) or (
            bool(heads) and all(RUN_ID.search(h) for h in heads))
        (residue if marked else kept).append(s)

    print(f"\n{len(stored)} rule(s) in the store, {len(classification)} of them "
          f"classification rules.\n")
    print(f"RESIDUE — {len(residue)} rule(s) to delete:")
    for s in sorted(residue, key=lambda r: (r.domain_id or "", r.rule_id)):
        print(f"  {s.rule_id}  [{s.domain_id}]  {s.status.value:<10} {s.rule}")
    if kept:
        print(f"\nKEPT — {len(kept)} classification rule(s) whose category carries "
              f"no run id:")
        for s in kept:
            print(f"  {s.rule_id}  [{s.domain_id}]  {s.status.value:<10} {s.rule}")
    else:
        print("\nKEPT — none. No visual category has been taught outside an "
              "experiment yet; that is the honest state of the store.")

    ids = [s.rule_id for s in residue]
    census = {}
    for table, column in REFERENCE_COLUMNS:
        got = await db.execute_query(
            f"SELECT count(*) n FROM {table} WHERE {column} = ANY($1::text[])",
            (ids,), fetch_all=True) or []
        if got and got[0]["n"]:
            census[f"{table}.{column}"] = int(got[0]["n"])
    print(f"\nCENSUS — rows referencing them: "
          f"{census or 'none outside learned_rules itself'}")

    record = {
        "operation": "purge_experiment_rule_residue",
        "at": datetime.now(timezone.utc).isoformat(),
        "reason": ("classification rules whose concluded category carries an "
                   "experiment run id; fixtures, not knowledge. Inert until "
                   "naming became a reflex, at which point every one of them "
                   "fired on every blob seen."),
        "rules_in_store_before": len(stored),
        "classification_before": len(classification),
        "census": census,
        "kept": [{"rule_id": s.rule_id, "domain_id": s.domain_id,
                  "status": s.status.value, "formula": str(s.rule)} for s in kept],
        "deleted": [{"rule_id": s.rule_id, "domain_id": s.domain_id,
                     "status": s.status.value, "formula": str(s.rule),
                     "positive_roots": s.positive_root_count,
                     "negative_roots": s.negative_root_count,
                     "fingerprint": s.semantic_fingerprint} for s in residue],
    }

    if dry or "--yes" not in sys.argv:
        print("\nNothing deleted. Read the partition above, then re-run with "
              "--yes to delete the residue.")
        return 0
    if not ids:
        print("\nNothing to delete.")
        return 0

    removed = await store.forget(ids)
    after = await store.load()
    left = [s for s in after if s.rule_kind == "classification"
            and s.rule_id in set(ids)]
    record["deleted_count"] = removed
    record["rules_in_store_after"] = len(after)
    record["verified_gone"] = not left
    if left:
        raise RuntimeError(f"{len(left)} rule(s) survived deletion")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = HERE / f"EXPERIMENT_RULE_RESIDUE_{stamp}.json"
    path.write_text(json.dumps(record, indent=2, default=str))
    print(f"\nDeleted {removed} rule(s). {len(after)} rule(s) remain in the store.")
    print(f"Record: {path.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
