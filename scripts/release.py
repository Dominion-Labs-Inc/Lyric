#!/usr/bin/env python3
"""Cut, stage, promote, roll back, verify and list releases of the model; take into development what a frozen
environment kept (core/database/releases.py).

Run from development (`LYRIC_ENVIRONMENT` unset or `development`). The line is `POSTGRES_DATABASE`:
lyric_db for the main line, lyric_dev for the sandbox.

  ./venv_lyric/bin/python3 scripts/release.py list
  ./venv_lyric/bin/python3 scripts/release.py cut [--notes TEXT]
  ./venv_lyric/bin/python3 scripts/release.py verify N
  ./venv_lyric/bin/python3 scripts/release.py stage N
  ./venv_lyric/bin/python3 scripts/release.py promote N
  ./venv_lyric/bin/python3 scripts/release.py rollback [--to N]
  ./venv_lyric/bin/python3 scripts/release.py take {staging,production}

A process serving a release is started with LYRIC_ENVIRONMENT=staging|production and LYRIC_RELEASE=N; it
checks its release before it serves. Promoting or rolling back changes the registry: the serving process is
then restarted on the release now registered for it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.database import releases  # noqa: E402
from core.database.postgres_config import PostgresConfig  # noqa: E402


def show(value) -> None:
    print(json.dumps(value, indent=2, default=str))


async def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    cut = commands.add_parser("cut")
    cut.add_argument("--notes", default="")
    for name in ("verify", "stage", "promote"):
        commands.add_parser(name).add_argument("version", type=int)
    commands.add_parser("rollback").add_argument("--to", type=int, default=None)
    commands.add_parser("take").add_argument("environment", choices=("staging", "production"))
    args = parser.parse_args(argv)

    config = PostgresConfig.resolve()
    if config.frozen:
        print(f"refused: releases are handled from development; this process is {config.environment}")
        return 2
    try:
        if args.command == "list":
            for row in await releases.list_releases(config):
                print(f"v{row['version']:<3} {row['status']:<10} {row['database']:<28} cut {row['cut_at']:%Y-%m-%d %H:%M} "
                      f"from {row['cut_from']}, commit {str(row['code_commit'])[:10]}"
                      f"{' +' + str(row['code_uncommitted']) + ' uncommitted' if row['code_uncommitted'] else ''}")
        elif args.command == "cut":
            show(await releases.cut(config, notes=args.notes))
        elif args.command == "verify":
            report = await releases.verify(config, args.version)
            show(report)
            return 0 if report["intact"] else 1
        elif args.command == "stage":
            show(await releases.stage(config, args.version))
        elif args.command == "promote":
            show(await releases.promote(config, args.version))
        elif args.command == "rollback":
            show(await releases.rollback(config, args.to))
        elif args.command == "take":
            from core.memory import get_memory_agent
            from core.database import get_database_manager
            await get_database_manager().initialize()
            agent = await get_memory_agent()
            show(await releases.take(config, args.environment, agent))
    except releases.ReleaseError as error:
        print(f"refused: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
