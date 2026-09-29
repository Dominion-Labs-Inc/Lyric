"""The FULL frozen capability suite — every case, no sampling — captured as an artifact.

This is the MEASUREMENT. `experiment.py` beside it is a different thing: it runs
`sample_size=6` and checks that the harness grades, counts and tracks honestly —
harness validity, not capability. A capability number must come from here, and it
writes the run to `results/` so the number in a report can be traced to a file.

`benchmark_capability()` returns a DICT (not the report object); reading it as an
object is what produced a run record full of nulls a moment ago.
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments._evidence import write_new  # noqa: E402


def full_suite_summary(record, json_name):
    """The short page for one full-suite run, rendered from its record only."""
    r = record["report"] if isinstance(record["report"], dict) else {}
    lines = [
        f"# CAPABILITY-BENCHMARK-01 full suite — run {record['started_at']}",
        "",
        "Every frozen capability case, no sampling, graded by "
        "`learning_authority.benchmark_capability()`.",
        "",
        f"Took {record['duration_seconds']} s. Command: `{record['command']}`",
        "",
    ]
    if r:
        lines += ["| Measure | Value |", "|---|---|"]
        lines += [f"| {k} | {r[k]} |" for k in r]
    else:
        lines += ["The report was not a dict:", "", f"    {record['report']}"]
    lines += ["", f"Generated from `{json_name}`, the data for this run.", ""]
    return "\n".join(lines)


async def main():
    from core.learning import get_learning_authority
    authority = get_learning_authority()
    await authority.start()
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    report = await authority.benchmark_capability()      # no sample_size = every frozen case
    took = time.perf_counter() - t0

    record = {
        "run": "capability_benchmark_full_frozen_suite",
        "started_at": started.isoformat(),
        "duration_seconds": round(took, 2),
        "command": ("./venv_lyric/bin/python3 "
                    "experiments/CAPABILITY-BENCHMARK-01/full_suite.py"),
        "report": report if isinstance(report, dict) else str(report),
    }
    path = write_new(Path(__file__).resolve().parent / "results",
                     f"{started.strftime('%Y%m%dT%H%M%SZ')}_full_suite",
                     json.dumps(record, indent=2, default=str),
                     summary=lambda name: full_suite_summary(record, name))
    print("ARTIFACT", path)
    print("REPORT", json.dumps(record["report"], indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
