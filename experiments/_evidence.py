#!/usr/bin/env python3
"""Run records for experiments — so evidence cites captured data, not a memory of stdout.

An experiment that only prints its result leaves nothing behind. The number in a
report then rests on someone having read a terminal correctly, which is exactly
the thing a reviewer cannot check. This writes every run to
`experiments/<NAME>/results/<UTC timestamp>.json` (with a short `.md` summary
beside it, rendered from the same data): the environment it ran in,
every check with its outcome, and every measured value.

Deliberately small and dependency-free. It records; it never decides. An
experiment's pass/fail logic stays in the experiment.

Usage:

    from experiments._evidence import RunRecord

    EV = RunRecord("CONSTITUTION-01", claim="...", hypothesis="...")
    ...
    EV.check("the proved act is allowed", ok, detail)     # returns ok
    EV.metric("hold_rate", 1.0, unit="fraction")
    path = EV.write()                                     # -> results/<ts>.json
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]


def write_new(directory: Path, stem: str, text: str,
              summary: Optional[Callable[[str], str]] = None) -> Path:
    """Write `text` to `<directory>/<stem>.json`, a file that did not exist before.

    A run never replaces another run's record. The file is opened for exclusive
    creation, so two runs that start in the same second get `<stem>.json` and
    `<stem>_2.json` rather than the second silently erasing the first.

    `summary`, when given, is called with the JSON file's final name and its
    text is written beside it as `<same name>.md`, also exclusively — the short
    human-readable page for that one run.
    """
    directory.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        path = directory / (f"{stem}.json" if n == 1 else f"{stem}_{n}.json")
        try:
            with path.open("x", encoding="utf-8") as fh:
                fh.write(text)
            break
        except FileExistsError:
            n += 1
    if summary is not None:
        with path.with_suffix(".md").open("x", encoding="utf-8") as fh:
            fh.write(summary(path.name))
    return path


def _cell(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text.replace("|", "\\|").replace("\n", " ")


def run_summary(record: Dict[str, Any], json_name: str) -> str:
    """The short page for one run, rendered from its record and nothing else —
    so the page cannot say anything the data does not."""
    s = record.get("summary", {})
    env = record.get("environment", {})
    lines = [
        f"# {record.get('experiment', '?')} — run {record.get('started_at', '?')}",
        "",
        f"**Outcome: {s.get('outcome', '?')}** — {s.get('passed', '?')}/"
        f"{s.get('checks', '?')} checks passed, {record.get('duration_seconds', '?')} s.",
        "",
    ]
    if record.get("claim"):
        lines += [f"**Claim.** {record['claim']}", ""]
    if record.get("hypothesis"):
        lines += [f"**Hypothesis.** {record['hypothesis']}", ""]
    if record.get("checks"):
        lines += ["## Checks", ""]
        for c in record["checks"]:
            mark = "PASS" if c.get("passed") else "**FAIL**"
            detail = f" — {c['detail']}" if c.get("detail") else ""
            lines.append(f"- {mark} {c.get('label', '')}{detail}")
        lines.append("")
    if record.get("metrics"):
        lines += ["## Metrics", "", "| Metric | Value | Unit | Note |", "|---|---|---|---|"]
        for m in record["metrics"]:
            lines.append(f"| {_cell(m.get('name', ''))} | {_cell(m.get('value'))} | "
                         f"{_cell(m.get('unit', ''))} | {_cell(m.get('note', ''))} |")
        lines.append("")
    if record.get("notes"):
        lines += ["## Notes", ""] + [f"- {n}" for n in record["notes"]] + [""]
    pg = env.get("postgres") or {}
    verified = env.get("database_verified")
    if verified:
        database = f"**{verified}** (asked the server)"
        if pg.get("database") and pg["database"] != verified:
            database += (f" — configuration resolved {pg['database']!r}, "
                         f"which DISAGREES with the server")
    elif pg.get("database"):
        database = (f"{pg['database']} on {pg.get('host')}:{pg.get('port')} "
                    f"(resolved configuration, {env.get('database_verified_reason')})")
    else:
        database = "not resolved"
    dirty = env.get("git_uncommitted_changes")
    commit = env.get("git_commit") or "none"
    if dirty:
        commit += f" plus {dirty} uncommitted changes (the code that ran is not that commit)"
    elif dirty is None and env.get("git_commit"):
        commit += " (uncommitted changes not recorded)"
    lines += [
        "## Environment",
        "",
        f"Python {env.get('python')} · shadow mode {env.get('shadow_mode')} · "
        f"git commit {commit} · database {database}",
        "",
        f"Generated from `{json_name}`, the data for this run.",
        "",
    ]
    return "\n".join(lines)


@dataclass
class CheckRecord:
    label: str
    passed: bool
    detail: str = ""
    at: str = ""


@dataclass
class MetricRecord:
    name: str
    value: Any
    unit: str = ""
    note: str = ""


class RunRecord:
    """One execution of one experiment, captured."""

    def __init__(self, experiment: str, *, claim: str = "", hypothesis: str = "",
                 results_dir: Optional[Path] = None) -> None:
        self.experiment = experiment
        self.claim = claim
        self.hypothesis = hypothesis
        self.started_at = datetime.now(timezone.utc)
        self._t0 = time.perf_counter()
        self.checks: List[CheckRecord] = []
        self.metrics: List[MetricRecord] = []
        self.notes: List[str] = []
        #: What the SERVER said this run's database is, once verified. Left None
        #: until `verify_database()` is awaited, with the reason recorded.
        self.verified_database: Optional[str] = None
        self.verified_database_reason: str = "not verified"
        self.results_dir = results_dir or (ROOT / "experiments" / experiment / "results")

    async def verify_database(self) -> Optional[str]:
        """Ask the SERVER which database this run actually used.

        Configuration can lie. A run that believed it was operating on a clone
        while writing to the real database is exactly what invalidated
        `kite17_ablation_INVALID_run1`, and the repair was to ask
        `SELECT current_database()` rather than trust resolution. This records
        what the server answered.

        It never OPENS a connection — a run that touched no database records that
        it touched none, rather than acquiring one just to look.
        """
        try:
            from core.database import get_unified_db
            db = await get_unified_db()
            if not getattr(db, "initialized", False):
                self.verified_database_reason = (
                    "no initialized connection in this process")
                return None
            row = await db.execute_query("SELECT current_database() AS db",
                                         fetch_one=True)
            name = row["db"] if row else None
            self.verified_database = str(name) if name else None
            self.verified_database_reason = (
                "asked the server" if name else "the server named no database")
            return self.verified_database
        except Exception as e:
            self.verified_database_reason = f"could not be asked: {e}"
            return None

    # ── recording ────────────────────────────────────────────────────────────

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(CheckRecord(label=label, passed=bool(ok), detail=str(detail),
                                       at=datetime.now(timezone.utc).isoformat()))
        return bool(ok)

    def metric(self, name: str, value: Any, unit: str = "", note: str = "") -> Any:
        self.metrics.append(MetricRecord(name=name, value=value, unit=unit, note=note))
        return value

    def note(self, text: str) -> None:
        self.notes.append(str(text))

    # ── the environment the numbers came from ────────────────────────────────

    @staticmethod
    def _environment() -> Dict[str, Any]:
        def _cmd(args):
            try:
                return subprocess.run(args, capture_output=True, text=True,
                                      timeout=5).stdout.strip() or None
            except Exception:
                return None
        env = {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
            "cwd": os.getcwd(),
            "shadow_mode": os.environ.get("LYRIC_SHADOW_MODE"),
            "git_commit": _cmd(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
            "postgres": None,
        }
        # THE DATABASE IS ASKED OF ITS AUTHORITY, not guessed from the process
        # environment. Reading POSTGRES_* here recorded `null` on every run that
        # resolved its database any other way — which is every run — so the
        # evidence said "not recorded" about a run that used a real database.
        try:
            from core.database.postgres_config import PostgresConfig
            env["postgres"] = PostgresConfig.resolve().describe()
        except Exception as e:
            env["postgres"] = {"resolved": False, "reason": str(e)}
        # The commit alone does not say what ran: uncommitted changes mean the code
        # differs from it. None when git could not be asked.
        status = _cmd(["git", "-C", str(ROOT), "status", "--porcelain"])
        env["git_uncommitted_changes"] = (
            None if env["git_commit"] is None
            else len(status.splitlines()) if status else 0)
        host = os.environ.get("POSTGRES_HOST")
        db = os.environ.get("POSTGRES_DB")
        if host or db:
            # Identity of the database only — never a credential.
            env["postgres"] = {"host": host, "database": db,
                               "port": os.environ.get("POSTGRES_PORT")}
        return env

    # ── the artifact ─────────────────────────────────────────────────────────

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "experiment": self.experiment,
            "claim": self.claim,
            "hypothesis": self.hypothesis,
            "started_at": self.started_at.isoformat(),
            "duration_seconds": round(time.perf_counter() - self._t0, 3),
            "environment": {
                **self._environment(),
                # What the SERVER said, kept distinct from what configuration
                # resolved — the two disagreeing is the failure this records.
                "database_verified": self.verified_database,
                "database_verified_reason": self.verified_database_reason,
            },
            "summary": {"checks": len(self.checks), "passed": self.passed,
                        "failed": self.failed,
                        "outcome": "PASS" if self.failed == 0 else "FAIL"},
            "metrics": [asdict(m) for m in self.metrics],
            "checks": [asdict(c) for c in self.checks],
            "notes": list(self.notes),
        }

    def write(self) -> Path:
        """Write the run to a NEW results/<UTC timestamp>.json, with its short
        summary beside it as .md, and return the JSON path."""
        stamp = self.started_at.strftime("%Y%m%dT%H%M%SZ")
        record = self.as_dict()
        path = write_new(self.results_dir, stamp,
                         json.dumps(record, indent=2, default=str),
                         summary=lambda name: run_summary(record, name))
        shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"\n  run record: {shown}")
        return path
