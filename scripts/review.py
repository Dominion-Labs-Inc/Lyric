#!/usr/bin/env python3
"""Review what was learned in a domain, without teaching it again.

The substrate asks itself about a sample of what it holds as learned there, answers, and how it does moves its
competence in the domain (`UnifiedLearningSystem.review_learned`). Every teaching pass ends with one; this runs one
on its own, on the store `POSTGRES_DATABASE` names.

    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 scripts/review.py --domain english [--sample N]

Logs to `logs/review_<database>.log`, never into a teaching run's log.
"""
import argparse
import asyncio
import contextlib
import io
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
(ROOT / "logs").mkdir(exist_ok=True)
from core.utils.stack_dump import dump_stacks_on_signal  # noqa: E402
dump_stacks_on_signal("review", ROOT / "logs")
# Its own log, set before anything imports core.main (whose basicConfig then adds nothing).
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(
                        ROOT / "logs" / f"review_{os.environ.get('POSTGRES_DATABASE', 'default')}.log")])


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--domain", required=True)
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    quiet = io.StringIO()
    print("starting the substrate…", flush=True)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coordinator = system.autonomous_coordinator

    def progress(done, of):
        print(f"  {time.strftime('%H:%M:%S')}  reviewed {done:,}/{of:,}", flush=True)

    print(f"reviewing what was learned in {args.domain}…", flush=True)
    with contextlib.redirect_stderr(quiet):
        review = await coordinator.learning.review_learned(args.domain, sample=args.sample, seed=args.seed,
                                                           progress=progress)
    print(f"  held as learned: {review.get('held', 0):,}")
    print(f"  reviewed: {review.get('reviewed', 0)}  asked: {review.get('asked', 0)}  right: {review.get('right', 0)}")
    for why in ("cannot_ask", "unread", "misread", "denied", "not_derived", "skipped"):
        print(f"  {why.replace('_', ' ')}: {review.get(why, 0)}")
    for relation, per in sorted(review.get("by_relation", {}).items(), key=lambda kv: -kv[1]["reviewed"]):
        print(f"    {relation:14} looked at {per['reviewed']:4}, asked {per['asked']:4}, right {per['right']:4}")
    print(f"  competence in {args.domain}: {review.get('before')} -> {review.get('after')} (posterior, update_count)")
    for miss in review.get("missed", [])[:12]:
        print(f"    missed ({miss['why']}): {miss['fact']}  asked: {miss['asked'] or '(could not say it)'}")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await system.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
