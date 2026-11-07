#!/usr/bin/env python3
"""Empty the sandbox line, so a build or test run starts from nothing.

The sandbox line is everything named from `lyric_dev`:
  lyric_dev                                      its development database
  lyric_dev_{staging,production}_{runtime,user_context,learning}
                                                   the databases of its frozen environments
  lyric_dev_model_v<N>, lyric_dev_model_registry
                                                   the releases its runs cut, and their registry

Each database is emptied: every table truncated and its sequences restarted. The releases and the registry are
dropped, so the next run's first cut is release 1 again; they are only what earlier sandbox runs cut. This is
how "what does the substrate learn from an empty store?" can be asked again as often as it is needed, which the
main store can answer only once.

The names are fixed here rather than read from the environment or a `.env` file, and for each database the
server is asked which database the connection reached before anything is removed; any other answer refuses that
database.

THE MAIN LINE IS EMPTIED ONLY WHEN IT IS NAMED AND THE WIPE IS TYPED OUT (`--line main --yes-empty-main`), and
the sandbox stays what this runs on when nothing is said. This file used to say the main line was never touched,
and the reason it gave was that "what does the substrate learn from an empty store?" can be asked of the sandbox
as often as needed and of the main store only once. That reason was sound and it is no longer the only
consideration: the main line is retaught whenever the standard a store is taught under changes, and it has
changed nine times since the store was last built. A reteach begins by emptying it. So the guard is kept as a
guard -- named line, typed confirmation, and the server asked which database it reached -- rather than removed.

Run:  ./venv_lyric/bin/python3 scripts/reset_dev_store.py
      ./venv_lyric/bin/python3 scripts/reset_dev_store.py --line main --yes-empty-main
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys

import asyncpg

SANDBOX = "lyric_dev"
MAIN = "lyric_db"


def environment_databases(line: str) -> tuple:
    """The databases of a line's frozen environments. The main line has production only; the sandbox has staging
    beside it, which is where a release is tried before it is cut."""
    environments = ("staging", "production") if line == SANDBOX else ("production",)
    return tuple(f"{line}_{environment}_{store}"
                 for environment in environments
                 for store in ("runtime", "user_context", "learning"))


ENVIRONMENT_DATABASES = environment_databases(SANDBOX)


def releases(line: str) -> "re.Pattern":
    """What a line's runs cut: dropped, never emptied (a release is read-only)."""
    return re.compile(rf"^{line}_model_(v[1-9][0-9]*|registry)$")


#: What sandbox runs cut: dropped, never emptied (a release is read-only).
RELEASES = releases(SANDBOX)
SCHEMAS = ("unified", "memory_hot", "memory_cold", "public")


async def connect(database: str):
    return await asyncpg.connect(host="localhost", port=5433, user="stefan", database=database)


async def empty(database: str) -> bool:
    connection = await connect(database)
    try:
        reached = await connection.fetchval("SELECT current_database()")
        if reached != database:
            print(f"refused: connected to {reached!r}, not {database!r}; nothing removed")
            return False
        tables = await connection.fetch(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema = ANY($1::text[]) AND table_type = 'BASE TABLE'",
            list(SCHEMAS))
        names = [f'"{t["table_schema"]}"."{t["table_name"]}"' for t in tables]
        before = 0
        for name in names:
            before += await connection.fetchval(f"SELECT count(*) FROM {name}")
        if names:
            await connection.execute(
                f"TRUNCATE TABLE {', '.join(names)} RESTART IDENTITY CASCADE")
        after = 0
        for name in names:
            after += await connection.fetchval(f"SELECT count(*) FROM {name}")
        print(f"{database}: {len(names)} tables, {before} rows before, {after} after")
        return after == 0
    finally:
        await connection.close()


async def main(line: str = SANDBOX) -> int:
    admin = await connect("postgres")
    try:
        present = {r["datname"] for r in await admin.fetch("SELECT datname FROM pg_database")}
        cut = sorted(d for d in present if releases(line).match(d))
        for database in cut:
            await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
            print(f"{database}: dropped (cut by an earlier run of this line)")
    finally:
        await admin.close()
    emptied = [await empty(database) for database in (line,) + environment_databases(line)
               if database in present]
    return 0 if all(emptied) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--line", default=SANDBOX, choices=(SANDBOX, "main"),
                        help=f"which line to empty: the sandbox ({SANDBOX}, the default) or main ({MAIN})")
    parser.add_argument("--yes-empty-main", action="store_true",
                        help=f"required with --line main: empties {MAIN} and its frozen environments")
    asked = parser.parse_args()
    if asked.line == "main" and not asked.yes_empty_main:
        raise SystemExit(f"--line main empties {MAIN} and everything named from it, which nothing restores; "
                         f"say --yes-empty-main as well")
    sys.exit(asyncio.run(main(MAIN if asked.line == "main" else SANDBOX)))
