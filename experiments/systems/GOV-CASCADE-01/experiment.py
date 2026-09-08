#!/usr/bin/env python3
"""GOV-CASCADE-01 — Does one injected error contaminate authority OVER derivation
depth, on the real substrate?

Proposition 7(ii) made empirical. A chain of conclusions is derived from a single
unsupported (false) root: C0 is the injected error, and each C_i is derived from
C_{i-1}, so every conclusion in the chain traces to that one root — it shares its
causal lineage and carries no support independent of it.

We toggle only the independence discipline of the belief substrate — the same
collapse rule measured in the paper's correlated-evidence table — and count how
many chain conclusions reach AUTHORITATIVE confidence (posterior >= the 0.95
acceptance bar) as the chain deepens:

    SEG      confirmations that share a causal lineage collapse to their
             strongest before compounding — so a conclusion supported only by
             the (correlated) chain cannot climb past a single grounding.
    UNIFORM  every derivation is counted as an independent confirmation, so the
             chain compounds toward certainty.

Everything runs on the live substrate through the coordinator: the belief store
(`system.autonomous_coordinator.learning.create_belief/update_belief/get_belief`)
and the coordinator's own independence collapse (`_independent_groundings`, the
Evidence model). Model-free by construction. Add-only and self-cleaning
(a scratch belief domain, deleted afterward).

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/GOV-CASCADE-01/experiment.py
"""
from __future__ import annotations

import os

os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "torinai_db")
os.environ.setdefault("TORIN_NO_WATCHDOG", "1")

import asyncio
import contextlib
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DOMAIN = "gov_cascade"
HERE = Path(__file__).resolve().parent
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
ACCEPTANCE = 0.95          # a conclusion is AUTHORITATIVE only past this bar
DEPTH = 6                  # chain length C1..C6
GROUNDING_STRENGTH = 0.9   # quality of each (identical) chain confirmation


def psql(sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PSQL, "-U", os.environ["POSTGRES_USER"], "-p", os.environ["POSTGRES_PORT"],
         "-d", os.environ["POSTGRES_DATABASE"], "-v", "ON_ERROR_STOP=0", "-tAc", sql],
        capture_output=True, text=True)


def cleanup() -> None:
    # beliefs are the only store this experiment writes; remove the scratch ones.
    for col in ("domain", "claim"):
        psql(f"DELETE FROM unified.beliefs WHERE {col} LIKE 'gov_cascade%'")


async def main() -> int:
    cleanup()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        L = coord.learning
        from core.agents.autonomous.autonomous_coordinator import Evidence

        def belief_id(b):
            return getattr(b, "belief_id", None) or getattr(b, "id", None)

        def posterior(b):
            b2 = L.get_belief(belief_id(b))
            return float(getattr(b2, "posterior_probability", 0.0))

        def confirmations(claim, m, discipline):
            """Posterior of `claim` after m confirmations that all trace to the
            single false root (shared causal lineage 'root'). SEG collapses them
            through the coordinator's own _independent_groundings; UNIFORM counts
            each as independent."""
            b = L.create_belief(claim, DOMAIN, prior=0.15)
            evs = []
            for j in range(m):
                lineage = "root" if discipline == "SEG" else f"root:{j}"
                evs.append(Evidence(claim, True, GROUNDING_STRENGTH, f"chain:{j}",
                                    "reasoning", lineage, "saw", derived=False))
            grounds = coord._independent_groundings(evs) if discipline == "SEG" else evs
            for g in grounds:
                L.update_belief(belief_id(b),
                                {"quality": g.strength, "source": g.causal_lineage},
                                evidence_supports=g.polarity)
            return posterior(b), len(grounds)

        results = {}
        for discipline in ("SEG", "UNIFORM"):
            # C_i is derived from C_{i-1}: at depth i it has accumulated i
            # (mutually-correlated) confirmations from the chain rooted at C0.
            per_claim = []
            for i in range(1, DEPTH + 1):
                claim = f"gov_cascade:{discipline}:C{i}"
                post, groundings = confirmations(claim, i, discipline)
                per_claim.append({"depth": i, "confirmations": i,
                                  "independent_groundings": groundings,
                                  "posterior": round(post, 4),
                                  "authoritative": post >= ACCEPTANCE})
            # contamination(k) = # chain conclusions authoritative at depth <= k
            trajectory = []
            authoritative_ids = [c["depth"] for c in per_claim if c["authoritative"]]
            for k in range(1, DEPTH + 1):
                trajectory.append(sum(1 for d in authoritative_ids if d <= k))
            results[discipline] = {"per_claim": per_claim,
                                   "contamination_by_depth": trajectory,
                                   "authoritative_total": len(authoritative_ids)}

    manifest = {
        "experiment": "GOV-CASCADE-01",
        "question": "Does one injected error contaminate authority over derivation "
                    "depth (Proposition 7(ii)), and does the independence discipline "
                    "bound it?",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "coordinator_driven": [
            "system.autonomous_coordinator.learning.create_belief",
            "system.autonomous_coordinator.learning.update_belief",
            "system.autonomous_coordinator.learning.get_belief",
            "system.autonomous_coordinator._independent_groundings (Evidence collapse)",
        ],
        "acceptance_bar": ACCEPTANCE,
        "chain_depth": DEPTH,
        "grounding_strength": GROUNDING_STRENGTH,
        "model": {"policy": "model-free by construction",
                  "note": "no inference invoked; belief updates and the lineage "
                          "collapse are symbolic"},
        "SEG": results["SEG"],
        "UNIFORM": results["UNIFORM"],
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    cleanup()
    print(json.dumps(manifest, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
