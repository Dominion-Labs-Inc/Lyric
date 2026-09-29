"""Releases of the model: taught in development, cut, and served frozen in staging and production.

  cut        copy development's model -- its tables, and only the substrate's own rows of the tables that hold
             people's rows too -- into `<database>_model_v<N>`; set it read-only; record its content and schema
             checksums and the code it was cut with; register it as a candidate
  stage      the candidate staging serves, exactly as production would
  promote    what production serves; the release it replaces is retired, and kept intact
  rollback   production back to the release it served before
  verify     a release against its registration
  take       into development, what production remembered of its own while serving, and how often it recalled
             each memory of its release

A process in staging or production checks, before it serves, that its release is registered for its
environment, read-only, intact (both checksums) and cut with the code now running (`verify_serving`). If any
check fails, it does not start.

The registry is `<database>_model_registry`. Every database of a line is named from its development database
(postgres_config), so a sandbox line never reaches the main line's releases.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from core.database.postgres_config import (
    FROZEN_ENVIRONMENTS, PER_OWNER_TABLES, PostgresConfig, tables_of)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS = ("unified", "memory_hot", "memory_cold")
STATUSES = ("candidate", "staging", "production", "retired")
#: What serves each frozen environment.
SERVES = {"staging": "staging", "production": "production"}
#: The directories under core/ that are not the substrate's code: caches, data, and code switched off.
_NOT_CODE = {"__pycache__", ".cache", "data", "_disabled"}
#: How a memory row names the substrate as its owner (memory rows store an empty owner for it).
SUBSTRATE_OWNERS = ("", "__substrate__")

REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS releases (
    version          INTEGER PRIMARY KEY,
    database         TEXT NOT NULL UNIQUE,
    cut_from         TEXT NOT NULL,
    cut_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    code_identity    TEXT NOT NULL,
    code_files       INTEGER NOT NULL,
    code_commit      TEXT,
    code_uncommitted INTEGER,
    content_checksum TEXT NOT NULL,
    schema_checksum  TEXT NOT NULL,
    row_counts       JSONB NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('candidate', 'staging', 'production', 'retired')),
    status_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes            TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_release_in_staging ON releases (status) WHERE status = 'staging';
CREATE UNIQUE INDEX IF NOT EXISTS one_release_in_production ON releases (status) WHERE status = 'production';
CREATE TABLE IF NOT EXISTS release_events (
    event_id    BIGSERIAL PRIMARY KEY,
    version     INTEGER NOT NULL REFERENCES releases(version),
    from_status TEXT,
    to_status   TEXT NOT NULL,
    at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detail      TEXT
);
"""

#: How often production recalled each memory of its release. Kept in runtime, never on the release's rows, and
#: taken into development's access counts by `take`.
USAGE_DDL = (
    """CREATE TABLE IF NOT EXISTS unified.release_memory_usage (
           usage_id      BIGSERIAL PRIMARY KEY,
           release       INTEGER NOT NULL,
           memory_id     TEXT NOT NULL,
           access_count  BIGINT NOT NULL DEFAULT 0,
           last_accessed TIMESTAMP NOT NULL,
           taken_at      TIMESTAMPTZ
       )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS release_memory_usage_untaken
           ON unified.release_memory_usage (release, memory_id) WHERE taken_at IS NULL""",
)


class ReleaseError(RuntimeError):
    """A release that cannot be cut, moved or served as asked."""


# ── Identity: the code, and what a release holds ─────────────────────────────────────────────────────────────

def code_identity(root: Path = ROOT) -> Dict[str, Any]:
    """What code this is: a hash over every `core/**/*.py` (path and content), with the git commit it sits on
    and how many files differ from it. The hash, not the commit, is compared: uncommitted changes are code too."""
    digest = hashlib.sha256()
    files = 0
    for directory, subdirectories, names in os.walk(root / "core"):
        subdirectories[:] = sorted(d for d in subdirectories if d not in _NOT_CODE)
        for name in sorted(names):
            if name.endswith(".py"):
                path = Path(directory) / name
                digest.update(str(path.relative_to(root)).encode())
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
                files += 1

    def git(*args: str) -> Optional[str]:
        try:
            done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--", "core")
    return {"sha256": digest.hexdigest(), "files": files, "commit": commit,
            "uncommitted": None if status is None else len(status.splitlines())}


#: Session settings fixed for a checksum, so the text form of a row cannot drift between the cut and a check.
_CANONICAL = ("SET TimeZone = 'UTC'", "SET DateStyle = 'ISO, YMD'", "SET IntervalStyle = 'postgres'",
              "SET extra_float_digits = 1", "SET bytea_output = 'hex'")


async def _root_tables(conn) -> List[str]:
    """Every table in the substrate's schemas, partitions counted with the table they partition."""
    rows = await conn.fetch(
        "SELECT n.nspname || '.' || c.relname AS name FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY($1::text[]) AND c.relkind IN ('r', 'p') AND NOT c.relispartition "
        "ORDER BY 1", list(SCHEMAS))
    return [r["name"] for r in rows]


def _quoted(table: str) -> str:
    schema, name = table.split(".", 1)
    return f'"{schema}"."{name}"'


async def content_checksum(conn) -> Tuple[str, Dict[str, int]]:
    """A checksum over every row of every table, independent of row order, and the rows per table."""
    for setting in _CANONICAL:
        await conn.execute(setting)
    digest = hashlib.sha256()
    counts: Dict[str, int] = {}
    for table in await _root_tables(conn):
        row = await conn.fetchrow(
            f"SELECT count(*) AS n, md5(coalesce(string_agg(h, '' ORDER BY h), '')) AS d "
            f"FROM (SELECT md5(t::text) AS h FROM {_quoted(table)} t) q")
        counts[table] = int(row["n"])
        digest.update(f"{table}\t{row['n']}\t{row['d']}\n".encode())
    return digest.hexdigest(), counts


async def schema_checksum(conn) -> str:
    """A checksum over the substrate's schemas: every column, index and constraint."""
    lines = [
        f"col {r['s']}.{r['t']}.{r['c']} {r['p']} {r['ty']} {r['nul']} {r['def']}"
        for r in await conn.fetch(
            "SELECT table_schema s, table_name t, column_name c, ordinal_position p, udt_name ty, "
            "is_nullable nul, coalesce(column_default, '') def FROM information_schema.columns "
            "WHERE table_schema = ANY($1::text[])", list(SCHEMAS))]
    lines += [f"idx {r['s']}.{r['i']} {r['d']}" for r in await conn.fetch(
        "SELECT schemaname s, indexname i, indexdef d FROM pg_indexes WHERE schemaname = ANY($1::text[])",
        list(SCHEMAS))]
    lines += [f"con {r['s']}.{r['t']}.{r['c']} {r['d']}" for r in await conn.fetch(
        "SELECT n.nspname s, c.relname t, k.conname c, pg_get_constraintdef(k.oid) d FROM pg_constraint k "
        "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = ANY($1::text[])", list(SCHEMAS))]
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()


# ── Databases ────────────────────────────────────────────────────────────────────────────────────────────────

async def connect(config: PostgresConfig, database: str):
    """A connection to one database, checked to have reached it."""
    conn = await asyncpg.connect(host=config.host, port=config.port, user=config.user,
                                 password=config.password or None, database=database)
    reached = await conn.fetchval("SELECT current_database()")
    if reached != database:
        await conn.close()
        raise ReleaseError(f"connected to {reached!r}, not {database!r}")
    return conn


async def database_exists(config: PostgresConfig, database: str) -> bool:
    admin = await connect(config, "postgres")
    try:
        return bool(await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database))
    finally:
        await admin.close()


def _pg_tool(name: str) -> str:
    found = shutil.which(name) or f"/opt/homebrew/opt/postgresql@16/bin/{name}"
    if not os.path.exists(found):
        raise ReleaseError(f"{name} not found on PATH or in /opt/homebrew/opt/postgresql@16/bin")
    return found


async def create_database(config: PostgresConfig, source: str, database: str) -> None:
    """A new database with `source`'s encoding, collation and structure (no rows)."""
    admin = await connect(config, "postgres")
    try:
        if await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", database):
            raise ReleaseError(f"{database} already exists")
        row = await admin.fetchrow(
            "SELECT pg_encoding_to_char(encoding) enc, datcollate, datctype FROM pg_database WHERE datname = $1",
            source)
        if row is None:
            raise ReleaseError(f"{source} does not exist")
        await admin.execute(
            f'CREATE DATABASE "{database}" TEMPLATE template0 ENCODING \'{row["enc"]}\' '
            f"LC_COLLATE '{row['datcollate']}' LC_CTYPE '{row['datctype']}'")
    finally:
        await admin.close()
    env = dict(os.environ, PGPASSWORD=config.password or "")
    with tempfile.NamedTemporaryFile("w+", suffix=".sql") as schema:
        subprocess.run([_pg_tool("pg_dump"), "-h", config.host, "-p", str(config.port), "-U", config.user,
                        "-d", source, "--schema-only", "--no-owner", "--no-privileges", "-f", schema.name],
                       check=True, env=env)
        subprocess.run([_pg_tool("psql"), "-h", config.host, "-p", str(config.port), "-U", config.user,
                        "-d", database, "-q", "-v", "ON_ERROR_STOP=1", "-f", schema.name],
                       check=True, env=env, stdout=subprocess.DEVNULL)


async def keep_only(config: PostgresConfig, database: str, keep: frozenset) -> Dict[str, int]:
    """Leave `database` holding only the tables in `keep` (a partition is kept with its table). It never removes
    data: a table outside `keep` is dropped only while it holds no rows; otherwise nothing is dropped and the
    tables holding rows are named."""
    conn = await connect(config, database)
    try:
        present = [f"{r['s']}.{r['t']}" for r in await conn.fetch(
            "SELECT table_schema s, table_name t FROM information_schema.tables "
            "WHERE table_schema = ANY($1::text[]) AND table_type = 'BASE TABLE'", list(SCHEMAS))]
        # A PARTITION BELONGS TO ITS TABLE: dropping the monthly partitions left their table nowhere to put a
        # row ("no partition of relation found"), measured 2026-09-27.
        parent_of = {f"{r['cs']}.{r['c']}": f"{r['ps']}.{r['p']}" for r in await conn.fetch(
            "SELECT cn.nspname cs, c.relname c, pn.nspname ps, p.relname p FROM pg_inherits i "
            "JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_namespace cn ON cn.oid = c.relnamespace "
            "JOIN pg_class p ON p.oid = i.inhparent JOIN pg_namespace pn ON pn.oid = p.relnamespace")}

        def kept(table: str) -> bool:
            while table not in keep and table in parent_of:
                table = parent_of[table]
            return table in keep

        outside = sorted(t for t in present if not kept(t))
        holding = [t for t in outside if await conn.fetchval(f"SELECT EXISTS (SELECT 1 FROM {_quoted(t)})")]
        if holding:
            raise ReleaseError(f"{database}: {len(holding)} table(s) outside what it keeps hold rows; nothing "
                               f"dropped: {holding[:10]}")
        for table in outside:
            await conn.execute(f"DROP TABLE IF EXISTS {_quoted(table)} CASCADE")
        left = {f"{r['s']}.{r['t']}" for r in await conn.fetch(
            "SELECT table_schema s, table_name t FROM information_schema.tables "
            "WHERE table_schema = ANY($1::text[]) AND table_type = 'BASE TABLE'", list(SCHEMAS))}
        strays = sorted(t for t in left if not kept(t))
        if strays:
            raise ReleaseError(f"{database}: still holds tables it does not keep: {strays}")
        return {"tables": len([t for t in left if t not in parent_of]),
                "partitions": len([t for t in left if t in parent_of]), "dropped": len(outside),
                "made_when_first_used": len(keep - left)}
    finally:
        await conn.close()


def environment_database(config: PostgresConfig, environment: str, store: str) -> str:
    return f"{config.database}_{environment}_{store}"


async def prepare_environment(config: PostgresConfig, environment: str) -> Dict[str, str]:
    """Make sure a frozen environment's own databases exist: runtime, user context and learning, each built
    from development's structure and holding only its store's tables. An existing one is left as it is: what
    an environment holds outlives the release it serves."""
    if environment not in FROZEN_ENVIRONMENTS:
        raise ReleaseError(f"{environment} is not an environment that serves a release")
    made = {}
    for store in ("runtime", "user_context", "learning"):
        database = environment_database(config, environment, store)
        if await database_exists(config, database):
            made[database] = "exists"
            continue
        await create_database(config, config.database, database)
        kept = await keep_only(config, database, tables_of(store))
        made[database] = f"created: {kept['tables']} tables, {kept['partitions']} partitions"
    return made


# ── The registry ─────────────────────────────────────────────────────────────────────────────────────────────

async def registry(config: PostgresConfig, *, create: bool = False):
    """A connection to this line's registry. `create` makes it on first use (by the first cut)."""
    database = config.registry_database
    if not await database_exists(config, database):
        if not create:
            raise ReleaseError(f"no release of {config.database} has been cut: {database} does not exist")
        admin = await connect(config, "postgres")
        try:
            await admin.execute(f'CREATE DATABASE "{database}"')
        finally:
            await admin.close()
    conn = await connect(config, database)
    if create:
        await conn.execute(REGISTRY_DDL)
    return conn


async def list_releases(config: PostgresConfig) -> List[Dict[str, Any]]:
    conn = await registry(config)
    try:
        return [dict(r) for r in await conn.fetch("SELECT * FROM releases ORDER BY version")]
    finally:
        await conn.close()


async def _record(conn, version: int, to_status: str, detail: str) -> None:
    before = await conn.fetchval("SELECT status FROM releases WHERE version = $1", version)
    await conn.execute("UPDATE releases SET status = $2, status_at = NOW() WHERE version = $1", version, to_status)
    await conn.execute("INSERT INTO release_events (version, from_status, to_status, detail) "
                       "VALUES ($1, $2, $3, $4)", version, before, to_status, detail)


# ── Cutting a release ────────────────────────────────────────────────────────────────────────────────────────

def _substrate_rows(table: str, conn_columns: List[str]) -> Optional[str]:
    """The WHERE clause that selects only the substrate's own rows of a per-owner table, or None for a table of
    the model itself (every row is its own). Refused for a per-owner table that cannot tell owners apart."""
    if table not in PER_OWNER_TABLES:
        return None
    owners = ", ".join(f"'{o}'" for o in SUBSTRATE_OWNERS)
    substrate_memory = (f"memory_id IN (SELECT memory_id FROM memory_hot.memory_hot WHERE user_id IS NULL "
                        f"OR user_id IN ({owners}) UNION SELECT memory_id FROM memory_cold.memory_cold "
                        f"WHERE user_id IS NULL OR user_id IN ({owners}))")
    if "user_id" in conn_columns:
        return f"user_id IS NULL OR user_id IN ({owners})"
    if "owner" in conn_columns:
        return f"owner IS NULL OR owner IN ({owners})"
    if table in ("memory_hot.archive_log", "unified.memory_media"):
        return substrate_memory          # they follow their memory
    raise ReleaseError(f"{table} holds people's rows and the substrate's, and has no owner column: a cut "
                       f"cannot tell them apart")


async def _columns(conn, table: str) -> List[str]:
    schema, name = table.split(".", 1)
    return [r["attname"] for r in await conn.fetch(
        "SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1 AND c.relname = $2 "
        "AND a.attnum > 0 AND NOT a.attisdropped AND a.attgenerated = '' ORDER BY a.attnum", schema, name)]


async def _dangling_references(conn) -> List[str]:
    """Every foreign key in a database with rows pointing at nothing: rows loaded without their triggers must
    still hold together."""
    problems = []
    for fk in await conn.fetch(
            "SELECT k.conname, k.conrelid::regclass::text child, k.confrelid::regclass::text parent, "
            "array(SELECT attname FROM pg_attribute WHERE attrelid = k.conrelid AND attnum = ANY(k.conkey) "
            "      ORDER BY array_position(k.conkey, attnum)) ccols, "
            "array(SELECT attname FROM pg_attribute WHERE attrelid = k.confrelid AND attnum = ANY(k.confkey) "
            "      ORDER BY array_position(k.confkey, attnum)) pcols "
            "FROM pg_constraint k WHERE k.contype = 'f'"):
        child_cols = ", ".join(f'c."{c}"' for c in fk["ccols"])
        parent_cols = ", ".join(f'p."{c}"' for c in fk["pcols"])
        not_null = " AND ".join(f'c."{c}" IS NOT NULL' for c in fk["ccols"])
        orphans = await conn.fetchval(
            f"SELECT count(*) FROM {fk['child']} c WHERE {not_null} AND NOT EXISTS "
            f"(SELECT 1 FROM {fk['parent']} p WHERE ({parent_cols}) = ({child_cols}))")
        if orphans:
            problems.append(f"{fk['child']} -> {fk['parent']} ({fk['conname']}): {orphans} row(s)")
    return problems


async def _beliefs_about_people(source, release) -> Tuple[int, int]:
    """Beliefs the release holds about a memory it does not: (about a person's memory, about none at all). A
    belief names the memory it is about; one about a person's memory is their context moving the model."""
    held = {r["memory_id"] for r in await release.fetch(
        "SELECT memory_id FROM memory_hot.memory_hot UNION SELECT memory_id FROM memory_cold.memory_cold")}
    named = [r["memory_id"] for r in await release.fetch(
        "SELECT DISTINCT memory_id FROM unified.beliefs WHERE memory_id IS NOT NULL")]
    missing = [m for m in named if m not in held]
    if not missing:
        return 0, 0
    people = await source.fetchval(
        "SELECT count(*) FROM (SELECT memory_id FROM memory_hot.memory_hot WHERE memory_id = ANY($1::text[]) "
        "UNION SELECT memory_id FROM memory_cold.memory_cold WHERE memory_id = ANY($1::text[])) q", missing)
    return int(people), len(missing) - int(people)


async def cut(config: PostgresConfig, *, notes: str = "") -> Dict[str, Any]:
    """Cut the next release from development's model. Returns its registration."""
    if config.frozen:
        raise ReleaseError(f"a release is cut in development; this process is {config.environment}")
    identity = code_identity()
    # EVERY CONCEPT FINDABLE BY MEANING. A release cannot encode what it lacks, so a concept cut without its
    # vectors would never be found by meaning where the release is served.
    source = await connect(config, config.database)
    try:
        unencoded = await source.fetchval("SELECT count(*) FROM unified.concepts WHERE embedding_model IS NULL")
    finally:
        await source.close()
    if unencoded:
        raise ReleaseError(f"{config.database} has {unencoded} concept(s) not yet encoded: let development's "
                           f"encoding finish, then cut")
    reg = await registry(config, create=True)
    try:
        version = int(await reg.fetchval("SELECT coalesce(max(version), 0) + 1 FROM releases"))
    finally:
        await reg.close()
    database = config.release_database(version)
    await create_database(config, config.database, database)
    keep = tables_of("model")
    await keep_only(config, database, keep)

    source = await connect(config, config.database)
    release = await connect(config, database)
    try:
        # Loaded without triggers (foreign keys included), then checked to hold together.
        await release.execute("SET session_replication_role = replica")
        copied = {}
        for table in sorted(t for t in await _root_tables(release) if t in keep):
            columns = await _columns(release, table)
            where = _substrate_rows(table, columns)
            select = (f"SELECT {', '.join(chr(34) + c + chr(34) for c in columns)} FROM {_quoted(table)}"
                      + (f" WHERE {where}" if where else ""))
            with tempfile.TemporaryFile() as rows:
                await source.copy_from_query(select, output=rows, format="binary")
                rows.seek(0)
                schema, name = table.split(".", 1)
                await release.copy_to_table(name, schema_name=schema, source=rows, columns=columns,
                                            format="binary")
            copied[table] = await release.fetchval(f"SELECT count(*) FROM {_quoted(table)}")
        for seq in await release.fetch(
                "SELECT sequence_schema s, sequence_name n FROM information_schema.sequences "
                "WHERE sequence_schema = ANY($1::text[])", list(SCHEMAS)):
            qualified = f'"{seq["s"]}"."{seq["n"]}"'
            state = await source.fetchrow(f"SELECT last_value, is_called FROM {qualified}")
            if state is not None:
                await release.execute("SELECT setval($1::regclass, $2, $3)", qualified,
                                      state["last_value"], state["is_called"])
        await release.execute("SET session_replication_role = origin")

        dangling = await _dangling_references(release)
        people_rows = await release.fetchval(
            "SELECT (SELECT count(*) FROM memory_hot.memory_hot WHERE NOT (user_id IS NULL OR user_id = ANY($1)))"
            " + (SELECT count(*) FROM memory_cold.memory_cold WHERE NOT (user_id IS NULL OR user_id = ANY($1)))",
            list(SUBSTRATE_OWNERS))
        about_people, about_nothing = await _beliefs_about_people(source, release)
        refusals = ([f"dangling references: {dangling}"] if dangling else []) + (
            [f"{people_rows} people's memories"] if people_rows else []) + (
            [f"{about_people} belief(s) about people's memories"] if about_people else [])
        if refusals:
            raise ReleaseError(f"release {version} not cut, it would carry people's context or broken links: "
                               f"{'; '.join(refusals)}. {database} is left for inspection, unregistered.")
        content, counts = await content_checksum(release)
        schema = await schema_checksum(release)
    finally:
        await source.close()
        await release.close()

    admin = await connect(config, "postgres")
    try:
        await admin.execute(f'ALTER DATABASE "{database}" SET default_transaction_read_only = on')
    finally:
        await admin.close()
    reg = await registry(config)
    try:
        async with reg.transaction():
            await reg.execute(
                "INSERT INTO releases (version, database, cut_from, code_identity, code_files, code_commit, "
                "code_uncommitted, content_checksum, schema_checksum, row_counts, status, notes) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,'candidate',$11)",
                version, database, config.database, identity["sha256"], identity["files"], identity["commit"],
                identity["uncommitted"], content, schema, json.dumps(counts), notes or None)
            await reg.execute("INSERT INTO release_events (version, from_status, to_status, detail) "
                              "VALUES ($1, NULL, 'candidate', $2)", version, f"cut from {config.database}")
    finally:
        await reg.close()
    return {"version": version, "database": database, "cut_from": config.database, "rows": sum(counts.values()),
            "row_counts": {t: n for t, n in counts.items() if n}, "content_checksum": content,
            "schema_checksum": schema, "code": identity,
            "beliefs_about_no_memory": about_nothing}


# ── Moving a release ─────────────────────────────────────────────────────────────────────────────────────────

async def stage(config: PostgresConfig, version: int) -> Dict[str, Any]:
    """Serve release `version` in staging. The release staged before it goes back to being a candidate."""
    report = await verify(config, version)
    if not report["intact"]:
        raise ReleaseError(f"release {version} is not intact: {report['problems']}")
    reg = await registry(config)
    try:
        async with reg.transaction():
            status = await reg.fetchval("SELECT status FROM releases WHERE version = $1", version)
            if status not in ("candidate", "staging"):
                raise ReleaseError(f"release {version} is {status}; only a candidate is staged")
            for row in await reg.fetch("SELECT version FROM releases WHERE status = 'staging' AND version <> $1",
                                       version):
                await _record(reg, row["version"], "candidate", f"release {version} staged in its place")
            if status != "staging":
                await _record(reg, version, "staging", "staged")
    finally:
        await reg.close()
    return {"version": version, "status": "staging", "databases": await prepare_environment(config, "staging")}


async def promote(config: PostgresConfig, version: int) -> Dict[str, Any]:
    """Serve release `version` in production. It must be the one in staging: nothing reaches production
    without having been staged. The release production served before is retired, and kept intact."""
    report = await verify(config, version)
    if not report["intact"]:
        raise ReleaseError(f"release {version} is not intact: {report['problems']}")
    reg = await registry(config)
    try:
        async with reg.transaction():
            status = await reg.fetchval("SELECT status FROM releases WHERE version = $1", version)
            if status != "staging":
                raise ReleaseError(f"release {version} is {status}; a release is promoted from staging")
            replaced = await reg.fetchval("SELECT version FROM releases WHERE status = 'production'")
            if replaced is not None:
                await _record(reg, replaced, "retired", f"replaced by release {version}")
            await _record(reg, version, "production", "promoted from staging"
                          + (f", replacing release {replaced}" if replaced else ""))
    finally:
        await reg.close()
    return {"version": version, "status": "production", "replaced": replaced,
            "databases": await prepare_environment(config, "production")}


async def rollback(config: PostgresConfig, to: Optional[int] = None) -> Dict[str, Any]:
    """Put production back on the release it served before (or on `to`, any release production has served).
    The release it was serving is retired, and kept intact."""
    reg = await registry(config)
    try:
        current = await reg.fetchval("SELECT version FROM releases WHERE status = 'production'")
        if current is None:
            raise ReleaseError("production serves no release")
        if to is None:
            to = await reg.fetchval(
                "SELECT version FROM release_events WHERE to_status = 'production' AND version <> $1 "
                "ORDER BY event_id DESC LIMIT 1", current)
            if to is None:
                raise ReleaseError(f"production has served no release before {current}")
        served = await reg.fetchval(
            "SELECT 1 FROM release_events WHERE version = $1 AND to_status = 'production'", to)
        if not served:
            raise ReleaseError(f"release {to} has never been in production; a release reaches it by promotion")
    finally:
        await reg.close()
    report = await verify(config, to)
    if not report["intact"]:
        raise ReleaseError(f"release {to} is not intact, so production cannot go back to it: {report['problems']}")
    reg = await registry(config)
    try:
        async with reg.transaction():
            await _record(reg, current, "retired", f"rolled back to release {to}")
            await _record(reg, to, "production", f"rollback from release {current}")
    finally:
        await reg.close()
    return {"from": current, "to": to, "status": "production"}


# ── Checking a release ───────────────────────────────────────────────────────────────────────────────────────

async def verify(config: PostgresConfig, version: int) -> Dict[str, Any]:
    """A release against its registration: it exists, is read-only, and both checksums match. Also says
    whether it was cut with the code now present (not a condition of `intact`: `verify_serving` requires it)."""
    reg = await registry(config)
    try:
        row = await reg.fetchrow("SELECT * FROM releases WHERE version = $1", version)
    finally:
        await reg.close()
    if row is None:
        raise ReleaseError(f"release {version} is not registered in {config.registry_database}")
    problems = []
    database = row["database"]
    if not await database_exists(config, database):
        return {"version": version, "status": row["status"], "intact": False,
                "problems": [f"{database} does not exist"], "same_code": None}
    conn = await connect(config, database)
    try:
        if await conn.fetchval("SHOW default_transaction_read_only") != "on":
            problems.append(f"{database} is not read-only")
        content, _counts = await content_checksum(conn)
        if content != row["content_checksum"]:
            problems.append("its content no longer matches the checksum it was cut with")
        if await schema_checksum(conn) != row["schema_checksum"]:
            problems.append("its schema no longer matches the checksum it was cut with")
    finally:
        await conn.close()
    same_code = code_identity()["sha256"] == row["code_identity"]
    return {"version": version, "status": row["status"], "database": database, "intact": not problems,
            "problems": problems, "same_code": same_code, "code_commit": row["code_commit"]}


async def verify_serving(config: PostgresConfig) -> Dict[str, Any]:
    """Before a staging or production process serves: its release is registered for its environment, read-only,
    intact, and was cut with the code now running; its own databases exist. Raises `ReleaseError` naming every
    check that failed."""
    if not config.frozen:
        raise ReleaseError("development serves no release")
    report = await verify(config, config.release)
    problems = list(report["problems"])
    wanted = SERVES[config.environment]
    if report["status"] != wanted:
        problems.append(f"release {config.release} is {report['status']}, not the release {config.environment} "
                        f"serves (it must be registered as {wanted})")
    if not report["same_code"]:
        problems.append(f"release {config.release} was cut with other code (commit {report['code_commit']}); "
                        f"the release and the code must match")
    for store in ("runtime", "user_context", "learning"):
        database = config.database_for(store)
        if not await database_exists(config, database):
            problems.append(f"{database} does not exist (release.py stage/promote prepares it)")
    if problems:
        raise ReleaseError(f"{config.environment} will not serve release {config.release}: " + "; ".join(problems))
    logger.info("%s serves release %s (%s): registered, read-only, intact, cut with this code",
                config.environment, config.release, report["database"])
    return report


# ── Taking what production kept into development ─────────────────────────────────────────────────────────────

async def take(config: PostgresConfig, environment: str, agent) -> Dict[str, Any]:
    """Into development, from `environment`: what the substrate remembered of its own while serving (its
    learning store), through the memory agent -- the normal path, where development learns from it -- the
    questions it met and could not answer, and how often it recalled each memory of its release (its runtime),
    added to those memories' access counts here.

    Taking twice takes once: a memory and a recall count are marked in the environment's own store when taken
    (a taken memory may merge into one development already holds, so development cannot be asked), and a
    question keeps its id."""
    if config.frozen:
        raise ReleaseError(f"development takes what {environment} kept; this process is {config.environment}")
    from core.memory.utils.interfaces import MemoryType
    learning = await connect(config, environment_database(config, environment, "learning"))
    runtime = await connect(config, environment_database(config, environment, "runtime"))
    counts = {"memories": 0, "already": 0, "images": 0, "usage": 0, "usage_unmatched": 0}
    try:
        rows = await learning.fetch(
            "SELECT 'memory_hot.memory_hot' AS tier, * FROM memory_hot.memory_hot "
            "UNION ALL SELECT 'memory_cold.memory_cold', * FROM memory_cold.memory_cold ORDER BY created_at")
        for row in rows:
            marked = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            if "taken_at" in marked:
                counts["already"] += 1
                continue
            metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            content = row["content"]
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                pass
            tags = row["tags"] if isinstance(row["tags"], list) else json.loads(row["tags"] or "[]")
            image = await learning.fetchrow(
                "SELECT bytes, perceived FROM unified.memory_media WHERE memory_id = $1 LIMIT 1", row["memory_id"])
            memory_type = row["memory_type"]
            from core.memory import Origin
            stored, _memory_id = await agent.store_memory(
                origin=Origin.own(f"{environment} learning store"),
                content=str(content),
                memory_type=MemoryType(memory_type) if memory_type in {m.value for m in MemoryType} else None,
                importance_score=float(row["importance_score"] or 0.5),
                confidence_score=float(row["confidence_score"] or 1.0),
                tags=list(tags),
                source_context={**metadata, "taken_from": f"{environment} learning store",
                                "taken_memory_id": row["memory_id"],
                                "taken_at": datetime.now(timezone.utc).isoformat()},
                media=bytes(image["bytes"]) if image else None,
                media_meta=(json.loads(image["perceived"]) if image and isinstance(image["perceived"], str)
                            else (image["perceived"] if image else None)),
            )
            if stored:
                counts["memories"] += 1
                counts["images"] += 1 if image else 0
                await agent.mark_taken(
                    learning, tier=row["tier"], memory_id=row["memory_id"],
                    taken_at=datetime.now(timezone.utc).isoformat(), taken_into=_memory_id)
        # ITS OWN QUESTIONS, the gaps it met while serving: joined to development's own open questions
        # (every instance reads that one store). A person's never reach the learning store.
        columns = [r["column_name"] for r in await learning.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'unified' "
            "AND table_name = 'known_unknowns' ORDER BY ordinal_position")]
        counts["questions"] = 0
        if columns:
            for row in await learning.fetch("SELECT * FROM unified.known_unknowns WHERE owner IS NULL"):
                counts["questions"] += await agent.hold_taken_question({c: row[c] for c in columns})
        for use in await runtime.fetch(
                "SELECT usage_id, memory_id, access_count, last_accessed FROM unified.release_memory_usage "
                "WHERE taken_at IS NULL") if await runtime.fetchval(
                "SELECT to_regclass('unified.release_memory_usage') IS NOT NULL") else []:
            matched = await agent.add_recorded_use(
                memory_id=use["memory_id"], access_count=int(use["access_count"]),
                last_accessed=use["last_accessed"])
            counts["usage" if matched else "usage_unmatched"] += int(use["access_count"])
            await runtime.execute("UPDATE unified.release_memory_usage SET taken_at = NOW() WHERE usage_id = $1",
                                  use["usage_id"])
    finally:
        await learning.close()
        await runtime.close()
    return counts
