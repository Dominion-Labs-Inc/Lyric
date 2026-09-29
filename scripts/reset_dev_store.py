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

It can only touch the sandbox. The names are fixed here rather than read from the environment or a `.env`
file, and for each database the server is asked which database the connection reached before anything is
removed; any other answer refuses that database. The main line (`lyric_db`, and everything named from it) is
never touched.

Run:  ./venv_lyric/bin/python3 scripts/reset_dev_store.py
"""
from __future__ import annotations

import asyncio
import re
import sys

import asyncpg

SANDBOX = "lyric_dev"
ENVIRONMENT_DATABASES = tuple(f"{SANDBOX}_{environment}_{store}"
                              for environment in ("staging", "production")
                              for store in ("runtime", "user_context", "learning"))
#: What sandbox runs cut: dropped, never emptied (a release is read-only).
RELEASES = re.compile(rf"^{SANDBOX}_model_(v[1-9][0-9]*|registry)$")
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


async def main() -> int:
    admin = await connect("postgres")
    try:
        present = {r["datname"] for r in await admin.fetch("SELECT datname FROM pg_database")}
        cut = sorted(d for d in present if RELEASES.match(d))
        for database in cut:
            await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
            print(f"{database}: dropped (cut by an earlier sandbox run)")
    finally:
        await admin.close()
    emptied = [await empty(database) for database in (SANDBOX,) + ENVIRONMENT_DATABASES
               if database in present]
    return 0 if all(emptied) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
