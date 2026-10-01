#!/usr/bin/env python3
"""OUTSIDE-DB-01 — the database tools work on an outside database they are given, never the substrate's own.

`postgres_query` and `mysql_query` used to run SQL through the substrate's own database manager, on its own model,
memory and people's context: around every authority, which Law 5 forbids. They now work on the database they are
given, and refuse the substrate's own database server before connecting. The other database tools, which ran on the
substrate's own database, are archived. The outside world here is a throwaway PostgreSQL server and a throwaway
MySQL server that the run starts and removes. The substrate is not started.

  A  PostgreSQL: a query reads the outside database's rows, and a change writes to it;
  B  MySQL: the same, on a real MySQL server;
  C  refused: either tool pointed at the substrate's own database server, by any name of this machine, is
     refused before it connects (with a user that does not exist, so a connection would have failed otherwise);
  D  the tools are registered, the archived ones are not, and the login never appears in what a tool returns;
  E  the substrate's stores (main and sandbox) are untouched.

    ./venv_lyric/bin/python3 experiments/OUTSIDE-DB-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
             "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

PG_BIN = Path("/opt/homebrew/opt/postgresql@16/bin")
MYSQL_BIN = Path("/opt/homebrew/opt/mysql/bin")
NONCE = uuid.uuid4().hex[:6]
LOGIN = f"pw-{NONCE}-never-shown"
ADMIN = "outside_admin"
ARCHIVED = ("mysql_table_info", "mysql_backup", "mysql_restore", "connection_pool_manager", "transaction_wrapper",
            "migration_runner", "row_level_access_control", "safe_query_executor", "postgres_safe_query_executor",
            "check_mysql_health", "check_postgresql_health", "query_metrics", "create_alert")

EV = RunRecord(
    "OUTSIDE-DB-01",
    claim=("postgres_query and mysql_query work on the outside database they are given and never on the substrate's "
           "own database server, which they refuse before connecting; the database tools that ran on the "
           "substrate's own database are no longer registered."),
    hypothesis=("A tool reaching the substrate's own server, a tool that cannot read or write a real outside "
                "database, an archived tool still registered, the login in a tool's output, or a write to the "
                "substrate's stores would each show here."))


def say_line(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


async def lyric_rows(database: str) -> int:
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database=database)
    try:
        n = 0
        for t in await c.fetch("select table_schema s, table_name n from information_schema.tables "
                               "where table_schema in ('unified','memory_hot','memory_cold') "
                               "and table_type='BASE TABLE'"):
            n += await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
        return n
    finally:
        await c.close()


def start_postgres(world: Path) -> int:
    port = free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(world / "pg"), "-U", ADMIN, "-A", "trust"],
                   check=True, capture_output=True)
    subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(world / "pg"), "-l", str(world / "pg.log"), "-w",
                    "-o", f"-p {port} -c listen_addresses=localhost -c unix_socket_directories=''", "start"],
                   check=True, capture_output=True)
    return port


def start_mysql(world: Path):
    port = free_port()
    subprocess.run([str(MYSQL_BIN / "mysqld"), "--initialize-insecure", f"--datadir={world / 'my'}",
                    f"--basedir={MYSQL_BIN.parent}"], check=True, capture_output=True)
    server = subprocess.Popen(
        [str(MYSQL_BIN / "mysqld"), f"--datadir={world / 'my'}", f"--basedir={MYSQL_BIN.parent}",
         f"--port={port}", "--bind-address=127.0.0.1", "--mysqlx=OFF", f"--socket={world / 'my.sock'}",
         f"--pid-file={world / 'my.pid'}", f"--log-error={world / 'my.err'}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return port, server


async def mysql_ready(port: int, wait_s: float = 60.0):
    import aiomysql
    deadline = time.time() + wait_s
    while True:
        try:
            return await aiomysql.connect(host="127.0.0.1", port=port, user="root", password="", autocommit=True)
        except Exception:
            if time.time() > deadline:
                raise
            await asyncio.sleep(0.5)


async def main() -> int:
    import asyncpg

    before = {db: await lyric_rows(db) for db in ("lyric_db", "lyric_dev")}
    world = Path(tempfile.mkdtemp(prefix="outsidedb01_"))
    mysql_server = None
    shown = []
    try:
        pg_port = start_postgres(world)
        my_port, mysql_server = start_mysql(world)
        say_line(f"    the outside world: PostgreSQL on port {pg_port}, MySQL on port {my_port}")

        admin = await asyncpg.connect(host="localhost", port=pg_port, user=ADMIN, database="postgres")
        await admin.execute("CREATE DATABASE shop")
        await admin.close()
        shop = await asyncpg.connect(host="localhost", port=pg_port, user=ADMIN, database="shop")
        await shop.execute("CREATE TABLE orders (id serial PRIMARY KEY, item text, qty int)")
        await shop.execute("INSERT INTO orders (item, qty) VALUES ('valve', 3), ('pump', 1)")

        my = await mysql_ready(my_port)
        async with my.cursor() as cur:
            await cur.execute(f"CREATE USER 'clerk'@'%' IDENTIFIED BY '{LOGIN}'")
            await cur.execute("CREATE DATABASE store")
            await cur.execute("GRANT ALL ON store.* TO 'clerk'@'%'")
            await cur.execute("CREATE TABLE store.parts (id int AUTO_INCREMENT PRIMARY KEY, name text, qty int)")
            await cur.execute("INSERT INTO store.parts (name, qty) VALUES ('bolt', 40), ('nut', 55)")

        from core.tools.database_tools import MySQLQueryTool, PostgresQueryTool
        pg_tool, my_tool = PostgresQueryTool(), MySQLQueryTool()
        at_pg = {"host": "localhost", "port": pg_port, "database": "shop", "user": ADMIN, "password": LOGIN}
        at_my = {"host": "127.0.0.1", "port": my_port, "database": "store", "user": "clerk", "password": LOGIN}

        async def run(tool, query, where, params=None):
            result = await tool.execute(query=query, params=params, **where)
            shown.append(result)
            return result

        say_line("\n== A. PostgreSQL ==")
        read = await run(pg_tool, "SELECT item, qty FROM orders ORDER BY id", at_pg)
        check("a query reads the outside database's rows",
              read.success and [r["item"] for r in read.output["rows"]] == ["valve", "pump"],
              f"{read.output if read.success else read.error}")
        wrote = await run(pg_tool, "INSERT INTO orders (item, qty) VALUES ($1, $2)", at_pg, ["gasket", 12])
        held = await shop.fetchval("SELECT qty FROM orders WHERE item = 'gasket'")
        check("a change writes to it", wrote.success and wrote.output["affected_rows"] == 1 and held == 12,
              f"{wrote.output if wrote.success else wrote.error}; it holds {held}")

        say_line("\n== B. MySQL ==")
        read = await run(my_tool, "SELECT name, qty FROM parts ORDER BY id", at_my)
        check("a query reads the outside database's rows",
              read.success and [r["name"] for r in read.output["rows"]] == ["bolt", "nut"],
              f"{read.output if read.success else read.error}")
        wrote = await run(my_tool, "UPDATE parts SET qty = qty + %s WHERE name = %s", at_my, [5, "bolt"])
        async with my.cursor() as cur:
            await cur.execute("SELECT qty FROM store.parts WHERE name = 'bolt'")
            held = (await cur.fetchone())[0]
        check("a change writes to it", wrote.success and wrote.output["affected_rows"] == 1 and held == 45,
              f"{wrote.output if wrote.success else wrote.error}; it holds {held}")
        my.close()

        say_line("\n== C. The substrate's own server ==")
        nobody = f"nobody_{NONCE}"
        names = ["localhost", "127.0.0.1", socket.gethostname()]
        for tool, label in ((pg_tool, "postgres_query"), (my_tool, "mysql_query")):
            refused = []
            for host in names:
                r = await run(tool, "SELECT 1", {"host": host, "port": 5433, "database": "lyric_dev",
                                                 "user": nobody, "password": LOGIN})
                refused.append((host, not r.success and "substrate's own database server" in (r.error or "")))
            check(f"{label} pointed at the substrate's own server is refused before it connects",
                  all(ok for _, ok in refused), f"{refused}")

        say_line("\n== D. What is registered, and what is shown ==")
        from core.tools.tool_registry import get_tool_registry
        registry = get_tool_registry()
        check("postgres_query and mysql_query are registered",
              registry.get_tool("postgres_query") is not None and registry.get_tool("mysql_query") is not None)
        still = [name for name in ARCHIVED if registry.get_tool(name) is not None]
        check("the archived database tools are not", not still, f"{still}")
        check("the login never appears in what a tool returns",
              LOGIN not in " ".join(str(r.output) + str(r.error) for r in shown))
        await shop.close()
    finally:
        if mysql_server is not None:
            mysql_server.terminate()
            try:
                mysql_server.wait(timeout=60)
            except subprocess.TimeoutExpired:
                mysql_server.kill()
        subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(world / "pg"), "-m", "fast", "-w", "stop"],
                       capture_output=True)
        shutil.rmtree(world, ignore_errors=True)
        say_line("    the throwaway servers are stopped and removed")

    say_line("\n== E. The substrate's stores ==")
    after = {db: await lyric_rows(db) for db in ("lyric_db", "lyric_dev")}
    check("main and sandbox are untouched", before == after, f"before {before}, after {after}")
    EV.note(f"nonce {NONCE}; the outside world was a throwaway PostgreSQL and MySQL server, removed after the run")
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say_line(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
