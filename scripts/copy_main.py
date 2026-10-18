"""A copy of main (`lyric_db`) in a local Postgres, read through the API gateway, so a cloud session can read, trace
and measure with main's own knowledge without a round trip through the owner's Mac. Read only: the gateway answers
reads, and nothing here writes to main.

    python3 scripts/copy_main.py fetch DIR [--streams N]   # main's tables, their columns and rows, into DIR
    python3 scripts/copy_main.py load DIR                  # DIR into the local Postgres, as main's own tables

What is copied: every memory (`memory_hot.memory_hot`, without its embedding and per-moment state: about 1.4 million,
the most of the time), and every table of `unified` (beliefs and their evidence, the concept graph and the small
tables) but the logs, histories and evidence text nothing reads to read or answer (`SKIPPED`). Each table is paged in
the order of a column (`ORDER`): paged in no order, pages overlap and rows are missed (a first copy held 926,567 of
1,444,559 memories). Each is checked whole afterwards: its rows, distinct, as many as the gateway counts (`COUNT`,
"total distinct"). A page fetched is kept, so a stopped fetch resumes. Main's memories took 85 minutes on 2026-10-18,
the gateway sending 8.6 MB a page whatever is kept of it.

`load` makes each table with main's columns (a vector column, or one of main's own types, held as text), loads the
rows and indexes what the warm reads by. It needs a Postgres where Lyric looks by default (localhost:5433, user
postgres, no password): in a cloud container,
    su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/lyric_mirror -A trust"
    su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/lyric_mirror -o '-p 5433 -k /tmp' \
        -l /var/lib/postgresql/lyric_mirror.log start"
Then Lyric reads the copy as it reads main: `POSTGRES_DATABASE=lyric_db`. A run on the copy may write to it; it is a
copy, and `load` again puts back what main held.

Needs `GATEWAY_BASE` and `LYRIC_STORE_TOKEN` in the environment (`fetch` only); the token is never printed.
"""
import argparse
import asyncio
import glob
import gzip
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

#: Not copied: logs, histories and evidence text nothing reads to read or answer.
SKIPPED = ("log", "knowledge_updates", "evidence_envelopes", "concept_evidence", "knowledge_consumption")
#: What is kept of each memory: what the warm and the reader read.
MEMORY_KEPT = ("memory_id", "memory_type", "content", "metadata", "tags", "user_id", "created_at", "status")
#: The column each table is paged in the order of; another table, by its first column.
ORDER = {"memory_hot": "memory_id", "beliefs": "belief_id", "belief_evidence": "seq", "concepts": "concept_id",
         "concept_relations": "source_concept_id", "concept_aliases": "alias", "concept_domains": "concept_id",
         "concept_identity_relations": "subject_concept_id"}
#: Each table's identity, to check it whole; another table, by the whole row.
IDENTITY = {"memory_hot": "memory_id", "beliefs": "belief_id", "belief_evidence": "seq"}
#: What the warm and the reader look rows up by.
INDEXES = [
    "CREATE INDEX ON memory_hot.memory_hot (memory_id)", "CREATE INDEX ON memory_hot.memory_hot USING gin (tags)",
    "CREATE INDEX ON memory_hot.memory_hot (user_id)", "CREATE INDEX ON memory_hot.memory_hot (created_at)",
    "CREATE INDEX ON unified.beliefs (belief_id)", "CREATE INDEX ON unified.beliefs (claim)",
    "CREATE INDEX ON unified.belief_evidence (belief_id, seq)",
    "CREATE INDEX ON unified.concepts (name)", "CREATE INDEX ON unified.concepts (concept_id)",
    "CREATE INDEX ON unified.concept_relations (source_concept_id)",
    "CREATE INDEX ON unified.concept_relations (target_concept_id)",
    "CREATE INDEX ON unified.concept_aliases (alias)", "CREATE INDEX ON unified.concept_aliases (concept_id)",
    "CREATE INDEX ON unified.concept_domains (concept_id)",
    "CREATE INDEX ON unified.concept_identity_relations (subject_concept_id)",
]


def say(*a):
    print(*a, flush=True)


def gateway(path, **params):
    """One read of the gateway's store routes, retried while it does not answer JSON."""
    base = os.environ["GATEWAY_BASE"] + "/api/admin/lyric-store/lyric_db/"
    args = ["curl", "-sS", "-m", "180", "-G", base + path, "-H", "X-Lyric-Store-Token: " + os.environ["LYRIC_STORE_TOKEN"]]
    for key, value in params.items():
        args += ["--data-urlencode", f"{key}={value}"]
    for attempt in range(6):
        out = subprocess.run(args, capture_output=True, text=True)
        try:
            return json.loads(out.stdout)
        except ValueError:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{path}: {out.stdout[:200]} {out.stderr[:200]}")


def partition(name: str) -> bool:
    """A monthly partition (`..._YYYY_MM`): its parent is copied."""
    return len(name) > 8 and name[-8] == "_" and name[-7:-3].isdigit() and name[-3] == "_"


def copied(tables):
    """The tables copied, as (schema, table) pairs."""
    return [(t["schema"], t["name"]) for t in tables
            if (t["schema"], t["name"]) == ("memory_hot", "memory_hot")
            or (t["schema"] == "unified" and not any(s in t["name"] for s in SKIPPED) and not partition(t["name"]))]


def fetch(out: str, streams: int) -> int:
    os.makedirs(out, exist_ok=True)
    tables = gateway("tables")["tables"]
    columns = {f"{s}.{t}": gateway(f"tables/{t}", schema=s) for s, t in copied(tables)}
    with open(f"{out}/columns.json", "w") as handle:
        json.dump(columns, handle)
    started = time.perf_counter()
    totals, pages = {}, []
    for name, info in columns.items():
        schema, table = name.split(".", 1)
        totals[name] = gateway(f"tables/{table}/count", schema=schema)["count"]
        os.makedirs(f"{out}/{name}", exist_ok=True)
        pages += [(name, offset) for offset in range(0, totals[name], 1000)]
    say(f"{len(columns)} tables, {sum(totals.values()):,} rows in {len(pages):,} pages")

    def page(item):
        name, offset = item
        path = f"{out}/{name}/{offset:09d}.jsonl.gz"
        if os.path.exists(path):
            return
        schema, table = name.split(".", 1)
        kept = MEMORY_KEPT if table == "memory_hot" else [
            c["name"] for c in columns[name]["columns"] if not c["type"].startswith(("vector", "halfvec"))]
        rows = gateway(f"tables/{table}/rows", schema=schema, limit=1000, offset=offset,
                       order_by=ORDER.get(table, columns[name]["columns"][0]["name"]))["rows"]
        with gzip.open(path + ".part", "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps({k: row.get(k) for k in kept}) + "\n")
        os.replace(path + ".part", path)
    done = 0
    with ThreadPoolExecutor(streams) as pool:
        for _ in pool.map(page, pages):
            done += 1
            if done % 200 == 0:
                say(f"  {done:,}/{len(pages):,} pages, {time.perf_counter() - started:.0f}s")
    whole = True
    for name, total in totals.items():
        table = name.split(".", 1)[1]
        seen = set()
        for path in glob.glob(f"{out}/{name}/*.jsonl.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                seen.update(json.loads(line)[IDENTITY[table]] if table in IDENTITY else line for line in handle)
        with open(f"{out}/{name}/COUNT", "w") as handle:
            handle.write(f"{total} {len(seen)}")
        if len(seen) != total:
            whole = False
            say(f"  {name}: {len(seen):,} distinct of {total:,}: not whole; fetch again after removing its pages")
    say(f"{'whole' if whole else 'NOT whole'}, {time.perf_counter() - started:.0f}s")
    return 0 if whole else 1


def column_type(kind: str) -> str:
    """Main's column type as the copy holds it: a vector, or one of main's own types (schema-qualified), as text."""
    if kind.startswith(("vector", "halfvec")) or ("." in kind and not kind[0].isdigit()):
        return "text"
    return kind


async def load(out: str) -> int:
    import asyncpg
    from core.database.postgres_config import PostgresConfig
    settings = PostgresConfig.resolve()
    connect = dict(host=settings.host, port=settings.port, user=settings.user, password=settings.password or None)
    columns = json.load(open(f"{out}/columns.json"))
    admin = await asyncpg.connect(database="postgres", **connect)
    if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = 'lyric_db'"):
        await admin.execute("CREATE DATABASE lyric_db")
    await admin.close()
    db = await asyncpg.connect(database="lyric_db", **connect)
    started = time.perf_counter()
    for name, info in columns.items():
        schema, table = name.split(".", 1)
        await db.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        made = ", ".join(f'"{c["name"]}" {column_type(c["type"])}' for c in info["columns"])
        await db.execute(f'CREATE TABLE IF NOT EXISTS {schema}."{table}" ({made})')
        await db.execute(f'TRUNCATE {schema}."{table}"')
        loaded = 0
        for path in sorted(glob.glob(f"{out}/{name}/*.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            if rows:
                names = ", ".join(f'"{k}"' for k in rows[0])
                await db.execute(f'INSERT INTO {schema}."{table}" ({names}) SELECT {names} '
                                 f'FROM json_populate_recordset(NULL::{schema}."{table}", $1::json)', json.dumps(rows))
                loaded += len(rows)
        if loaded:
            say(f"{name}: {loaded:,} rows, {time.perf_counter() - started:.0f}s")
    for statement in INDEXES:
        await db.execute(statement)
    await db.execute("ANALYZE")
    say(f"indexed, {time.perf_counter() - started:.0f}s")
    await db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("fetch", "load"))
    parser.add_argument("dir")
    parser.add_argument("--streams", type=int, default=8)
    args = parser.parse_args()
    if args.action == "fetch":
        return fetch(args.dir, args.streams)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return asyncio.run(load(args.dir))


if __name__ == "__main__":
    sys.exit(main())
