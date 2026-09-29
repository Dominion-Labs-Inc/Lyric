#!/usr/bin/env python3
"""Run the NLU suite against ONE live substrate.

  PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/nlu/run_all.py

Boots the substrate once and runs every experiment against it, in order. The
experiments that WRITE to the store run last, so nothing they teach can flatter
a measurement taken before them.
"""
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _nlu_lib import (conversation_of, live_substrate, save_suite,  # noqa: E402
                      stamp_now)
from nlu_experiments import ALL                              # noqa: E402


async def main() -> int:
    done = []
    stamp = stamp_now()
    here = Path(__file__).resolve().parent
    warm = None
    async with live_substrate() as coordinator:
        # The faculty, reached through the substrate that owns it.
        coord = conversation_of(coordinator)
        warm = getattr(coordinator, "_nlu_warm", None)
        # Read-only first, writers last -- order is part of the method.
        for fn in sorted(ALL, key=lambda f: f.__name__):
            started = time.time()
            try:
                x = await fn(coord)
            except Exception as error:
                import traceback
                print(f"\n{fn.__name__} RAISED: {type(error).__name__}: {error}")
                traceback.print_exc()
                continue
            x.seconds = time.time() - started
            done.append(x)
            print(x.render(), flush=True)
            # THE ARTIFACT IS MADE WHETHER IT PASSED OR FAILED. A run that only
            # recorded its successes leaves the failures nowhere but a terminal,
            # and a failure is the more useful half of a measurement.
            artifact = x.save(here, stamp)
            print(f"         -> {artifact.relative_to(ROOT)}", flush=True)
            # AND THE SUBSTRATE HOLDS WHAT WAS FOUND OUT ABOUT IT. The probe is
            # never taught; the finding is, with the faculty as its subject and
            # this run as the one witness.
            try:
                held = await x.learned(coordinator, run=stamp,
                                       artifact=str(artifact.relative_to(ROOT)))
                if held:
                    print(f"         -> the substrate now holds {held} finding(s) "
                          f"about its own {x.faculty}", flush=True)
            except Exception as error:
                print(f"         -> findings NOT held: "
                      f"{type(error).__name__}: {error}", flush=True)

    suite_path = save_suite(done, here, stamp, warm)
    total = sum(len(x.checks) for x in done)
    passed = sum(x.passed for x in done)
    print("\n" + "=" * 72)
    print(f"NLU SUITE — {len(done)}/{len(ALL)} experiments ran, "
          f"{passed}/{total} checks passed")
    for x in done:
        flag = "" if x.passed == len(x.checks) else "   <-- has failures"
        print(f"  {x.code}  {x.passed:>3}/{len(x.checks):<3} {x.question[:52]}{flag}")
    print(f"\nresults written: {suite_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
