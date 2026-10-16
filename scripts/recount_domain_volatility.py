#!/usr/bin/env python3
"""Set each domain's decay rate to what the belief system's rule gives now, where it was counted wrong.

A domain's rate is how fast its beliefs fade without new evidence: `0.01 + 0.1 x` the average change of its last
updates, plus a step for each reversal (`BayesianUncertaintySystem._update_domain_volatility`). It counted a
belief's first word (learning it, 0.5 to 0.94) and a witness taking its word back as changes in the domain, so a
domain taught once kept 0.054 and faded five times as fast as one never taught, and a teacher withdrawing what it no
longer taught counted each fact as a reversal (2026-10-12). Neither counts now. The changes behind a stored rate are
not kept, so a rate is set to what the rule gives with no change of mind recorded: the base, from which changes of
mind move it again.

Run with no substrate on the store. Without --apply it changes nothing and reports. Refuses lyric_db unless --main.

    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/recount_domain_volatility.py --main --apply
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

#: The rule's rate with no change recorded (`_update_domain_volatility`: `0.01 + 0.1 x 0 + 0`).
BASE = 0.01


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--main", action="store_true")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main:
        print("refused: name a store in POSTGRES_DATABASE, or pass --main for lyric_db")
        return 2
    from core.agents.memory_agent import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    agent = await get_memory_agent()
    await agent.initialize()
    us = get_uncertainty_system()
    await us._load_domain_volatility()
    print(f"{database}:")
    for domain, rate in sorted(us.domain_volatility.items()):
        print(f"  {domain:32} {rate:.4f} -> {BASE:.4f}" + ("" if abs(rate - BASE) > 1e-9 else "  (as it is)"))
    if args.apply:
        for domain in list(us.domain_volatility):
            us.domain_volatility[domain] = BASE
        print(f"saved {await us.save_domain_volatility()} domain rate(s)")
    await agent.stop_memory_loops()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
