#!/usr/bin/env python3
"""
Lyric Unified PostgreSQL Database
====================================
Production PostgreSQL database implementation with schema-based tier architecture.

Environments and stores:
- DEVELOPMENT keeps everything in one database (`POSTGRES_DATABASE`: lyric_db
  for the main line, lyric_dev for its sandbox). The model is taught there.
- STAGING and PRODUCTION serve a numbered RELEASE of the model, frozen
  (`<database>_model_v<N>`, read-only), and keep their runtime, each person's
  context and what the substrate remembers of its own while serving (learning)
  in `<database>_<environment>_<store>`. `LYRIC_ENVIRONMENT` and
  `LYRIC_RELEASE` say which a process is.

Every component holds this one manager. Outside development it sends each
statement to the database its tables live in (postgres_config.STORE_TABLES);
a caller names the store only where the tables cannot decide (a person's rows
in a per-owner table, a statement with no table, a raw connection). Against a
frozen release it answers reads, checks table creation against what the release
has, and refuses every other write. In development there is one database and
nothing to route.

Architecture within a database:
- Hot Tier: memory_hot schema for last 60 days
- Unified: unified schema with directives, governance, metrics
- Cold Tier: memory_cold schema for 60+ day old memories

Connection Pooling:
- Uses asyncpg for async PostgreSQL operations
- One connection pool per database, with schema routing via search_path
- pgvector integration for 100x faster semantic search
- Configuration resolved by postgres_config (explicit > environment > .env > default)
"""

import logging

from .postgres_config import DEFAULT_PORT
import os
import json
import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple, Union
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

try:
    import asyncpg
    from pgvector.asyncpg import register_vector
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    logging.warning("asyncpg or pgvector not available - database operations will fail")

from dotenv import load_dotenv

from core.database.postgres_config import (
    PER_OWNER_TABLES, STORES, DatabaseIdentityError, ModelFrozenError, PostgresConfig,
    ReleaseMismatchError, StoreRoutingError, schema_requirements, statement_kind,
    store_for_statement, tables_in)

logger = logging.getLogger(__name__)


def _tier_schema(use_hot_tier: bool, use_cold_tier: bool) -> str:
    """The schema a connection's search path starts with (priority: cold > hot > unified)."""
    if use_cold_tier:
        return 'memory_cold'
    if use_hot_tier:
        return 'memory_hot'
    return 'unified'


class _DatabasePool:
    """One database's connection pool, and the event loop it belongs to.

    Development has one; staging and production have one per store.
    """

    def __init__(self, database: str, index: int):
        self.database = database
        #: Position among this process's pools, part of every pool tag.
        self.index = index
        self.pool = None
        #: The event loop self.pool was created on. asyncpg pools are not
        #: portable across loops; see matches_running_loop.
        self.loop = None
        #: Identifies each pool generation server-side, so backends stranded by
        #: a dead loop can be found and closed. See _reap_stale_pools.
        self.generation = 0
        self.tag: Optional[str] = None
        self.stale_tags: set = set()
        #: `ensure_schema` keys already run against this database by this process.
        self.schemas_ready: set = set()

    def matches_running_loop(self) -> bool:
        """True when self.pool can actually be used from the current loop.

        asyncpg binds a pool and every connection in it to the loop that
        created them. Using one from another loop does not raise a clear error
        — it fails inside the protocol with "another operation is in progress",
        naming a query that is entirely valid, which reads as a database fault
        rather than a lifecycle one.
        """
        if self.pool is None:
            return False
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return False
        if self.loop is None:
            return True          # created before this tracking existed
        return self.loop is running and not self.loop.is_closed()


class LyricUnifiedDatabasePostgres:
    """
    Unified PostgreSQL Database for Lyric (Singleton)

    All instantiations return the same shared instance with shared connection
    pools, preventing connection exhaustion from multiple components each
    creating their own pools.

    Provides async connection pooling and database operations for:
    - Directive system (internal_directives, etc.)
    - Unified metrics and alerts
    - Component tracking
    - Hot tier memory storage (0-60 days) with pgvector semantic search
    - Cold tier memory archival (60+ days) with pgvector semantic search
    - Learning and adaptation data

    Usage:
        db = LyricUnifiedDatabasePostgres()
        await db.initialize()

        # Execute query with automatic schema routing
        results = await db.execute_query(
            "SELECT * FROM internal_directives WHERE status = $1",
            ('ACTIVE',),
            fetch_all=True
        )

        await db.close()

    Memory (hot and cold tiers) is read and written only through the memory
    agent, its one authority; nothing else queries those tables.
    """

    # Singleton: all instantiations share the same object and connection pools
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        pool_min_size: Optional[int] = None,
        pool_max_size: Optional[int] = None
    ):
        """
        Initialize database connection manager

        Args:
            host: PostgreSQL host (from env if None)
            port: PostgreSQL port (from env if None)
            user: PostgreSQL user (from env if None)
            password: PostgreSQL password (from env if None)
            database: The development database (from env if None); every
                other database of its line is named from it
            pool_min_size: Min pool size (from env if None, default 0)
            pool_max_size: Max pool size (from env if None, default 100)
        """
        # Skip re-initialization if singleton already configured
        if hasattr(self, '_singleton_configured'):
            return
        self._singleton_configured = True

        # Set ALL instance attributes to safe defaults BEFORE any code that can raise.
        # This ensures the singleton is always in a usable (non-crashing) state even
        # if initialization fails partway through.
        self.initialized = False
        #: Whether initialize() has ever succeeded. After close() the next use builds the pools
        #: again; before the first initialize() it is a caller error.
        self._ever_initialized = False
        #: database name -> its pool. One in development, one per store in staging and production.
        self._pools: Dict[str, _DatabasePool] = {}
        self.host = 'localhost'
        # 5433 is Lyric's own instance; 5432 is the shared one holding
        # agentso's tenant databases. See postgres_config.DEFAULT_PORT.
        self.port = DEFAULT_PORT
        self.user = 'postgres'
        self.password = ''
        self.database = 'lyric_db'
        self.environment = 'development'
        self.release: Optional[int] = None
        #: Whether this process serves a frozen release (staging, production).
        self.frozen = False
        #: The release this process serves, as its start-up check found it (releases.verify_serving).
        self.release_verified: Optional[Dict[str, Any]] = None
        #: Every write refused because the model is a frozen release: "caller-visible statement head".
        self.frozen_refusals: List[str] = []
        self.pool_min_size = 0
        self.pool_max_size = 100
        #: Seconds a pooled connection may sit idle before it is closed.
        self.pool_idle_seconds = 60
        self._boot_time = time.time()
        self._error_counts: Dict[str, int] = {}
        self._error_grace_seconds = 60
        self._error_retry_threshold = 3
        self.metrics = {
            'total_queries': 0,
            'failed_queries': 0,
            'total_connections': 0,
            'pool_errors': 0,
            'hot_tier_queries': 0,
            'cold_tier_queries': 0,
            'unified_queries': 0,
            'frozen_refusals': 0,
            'release_schema_checks': 0,
        }

        if not ASYNCPG_AVAILABLE:
            raise ImportError(
                "asyncpg and pgvector are required for PostgreSQL database operations. "
                "Install with: pip install asyncpg pgvector"
            )

        # Configuration is resolved, not imposed. This previously called
        # load_dotenv(override=True) and then read os.getenv on the next line,
        # so the file overwrote the process environment and an externally
        # supplied POSTGRES_DATABASE could never take effect -- a subprocess
        # asked for one database and silently connected to another.
        self.config = PostgresConfig.resolve(
            host=host, port=port, user=user, password=password, database=database,
            pool_min_size=pool_min_size, pool_max_size=pool_max_size,
        )
        self.host = self.config.host
        self.port = self.config.port
        self.user = self.config.user
        self.password = self.config.password
        self.database = self.config.database
        self.environment = self.config.environment
        self.release = self.config.release
        self.frozen = self.config.frozen
        self.pool_min_size = self.config.pool_min_size
        self.pool_max_size = self.config.pool_max_size
        self.pool_idle_seconds = self.config.pool_idle_seconds
        self._error_grace_seconds = int(os.getenv("DB_ERROR_GRACE_SECONDS", "60"))
        self._error_retry_threshold = int(os.getenv("DB_ERROR_MAX_INITIAL_RETRIES", "3"))
        for index, name in enumerate(dict.fromkeys(self.config.databases().values())):
            self._pools[name] = _DatabasePool(name, index)

        logger.info(
            f"LyricUnifiedDatabasePostgres singleton configured "
            f"(host: {self.host}:{self.port}, {self.environment}"
            f"{f' serving release {self.release}' if self.release else ''}, "
            f"databases: {', '.join(self._pools)}, "
            f"pool: {self.pool_min_size}-{self.pool_max_size}, "
            f"database_source: {self.config.provenance.get('database')}, "
            f"environment_source: {self.config.provenance.get('environment')})"
        )

    # ── Which database ────────────────────────────────────────────────────

    def _pool_for(self, store: Optional[str]) -> _DatabasePool:
        """The pool a store's statements run in. Development has one pool, so an
        unnamed store is that one; staging and production refuse to guess."""
        if store is None:
            if len(self._pools) == 1:
                return next(iter(self._pools.values()))
            raise StoreRoutingError(
                f"{self.environment} keeps its stores in separate databases; name the store "
                f"({', '.join(STORES)})")
        return self._pools[self.config.database_for(store)]

    def _route(self, statement: str, use_hot_tier: bool, use_cold_tier: bool,
               store: Optional[str]) -> Optional[str]:
        """The store a statement runs in.

        Staging and production decide it from the statement's tables
        (postgres_config.store_for_statement), and against their frozen release
        refuse every write (`ModelFrozenError`); table creation there is checked,
        not run (`_run_or_check`). Development has one database, so nothing is
        routed and a named store is only checked to be one."""
        if not self.frozen:
            if store is not None and store not in STORES:
                raise StoreRoutingError(f"{store!r} is not a store; the stores are {', '.join(STORES)}")
            return store
        store = store_for_statement(statement, search_schema=_tier_schema(use_hot_tier, use_cold_tier),
                                    store=store)
        if store == "model" and statement_kind(statement) == "write":
            raise self.frozen_refusal(" ".join(str(statement).split())[:160])
        return store

    def frozen_refusal(self, what: str) -> ModelFrozenError:
        """Count one change to the frozen model refused -- here, or by a component
        that holds part of the model in the process (the belief store, the
        learning authority) -- and return the error to raise. Every refusal is
        counted in one place, so a run can say how many there were."""
        self.frozen_refusals.append(what)
        self.metrics['frozen_refusals'] += 1
        return ModelFrozenError(
            f"the model is release {self.release}, frozen: {self.environment} never changes it "
            f"(development teaches the model and cuts the next release). Refused: {what}")

    def refuse_if_frozen(self, statement: str, *, store: Optional[str],
                         use_hot_tier: bool = False, use_cold_tier: bool = False) -> None:
        """Raise `ModelFrozenError` (counted) when `statement` would write the frozen
        release. For a caller about to make a change of several statements, so the
        refusal comes before the first of them rather than halfway through."""
        self._route(statement, use_hot_tier, use_cold_tier, store)

    def _checks_against_release(self, statement: str, store: Optional[str]) -> bool:
        """Whether this statement creates something in the frozen release, and so
        is checked against what the release already has rather than run."""
        return self.frozen and store == "model" and statement_kind(statement) == "schema"

    async def _check_against_release(self, statement: str, schema: str) -> str:
        """Check a creation statement against the release: what it would create
        must already be there (and what it would drop, gone). A release is cut
        complete, so a mismatch means the release and the code do not match, and
        the statement is refused (`ReleaseMismatchError`). Only reads the release's
        catalogue."""
        needs = schema_requirements(statement, schema)
        head = " ".join(str(statement).split())[:160]
        if needs is None:
            raise ReleaseMismatchError(
                f"release {self.release} is frozen, and this is not a creation that can be checked "
                f"against it: {head}")
        pool = self._pool_for("model")
        async with self._acquire(pool, 'unified') as conn:
            for need in needs:
                if need.kind == "table":
                    found = await conn.fetchval(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = $1 AND table_name = $2", need.schema, need.table)
                elif need.kind == "index":
                    found = await conn.fetchval(
                        "SELECT 1 FROM pg_indexes WHERE schemaname = $1 AND indexname = $2",
                        need.schema, need.name)
                elif need.kind == "column":
                    found = await conn.fetchval(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = $1 AND table_name = $2 AND column_name = $3",
                        need.schema, need.table, need.name)
                else:
                    found = await conn.fetchval(
                        "SELECT 1 FROM information_schema.table_constraints "
                        "WHERE table_schema = $1 AND table_name = $2 AND constraint_name = $3",
                        need.schema, need.table, need.name)
                if bool(found) != need.present:
                    raise ReleaseMismatchError(
                        f"release {self.release} {'lacks' if need.present else 'still has'} the {need.kind} "
                        f"{need.schema}.{need.table + '.' if need.kind in ('column', 'constraint') else ''}"
                        f"{need.name} that this code {'creates' if need.present else 'removes'}: the "
                        f"release and the code running it do not match. Statement: {head}")
        self.metrics['release_schema_checks'] += 1
        return "CHECKED"

    def _unique_stores(self, stores) -> List[str]:
        """`stores`, once per database, in order."""
        seen, out = set(), []
        for store in stores:
            database = self.config.database_for(store)
            if database not in seen:
                seen.add(database)
                out.append(store)
        return out

    def owner_stores(self, substrate_store: str = "model") -> List[str]:
        """The stores a per-owner table (postgres_config.PER_OWNER_TABLES) is READ
        from, once per database: where the substrate's own rows are
        (`substrate_store`, the table's entry there) and user context. Development
        keeps them in its one database, so one; staging and production keep them
        apart, so two. What the substrate remembers while serving (the learning
        store) is never read back while serving."""
        return self._unique_stores((substrate_store, "user_context"))

    def write_store(self, owner: Optional[str], substrate_store: str = "model") -> str:
        """The store a new row of a per-owner table is WRITTEN to: a person's to
        user context; the substrate's to `substrate_store` in development, and,
        where the model is a frozen release, to the learning store beside it."""
        from core.agents.autonomous.shared_types import store_for_owner
        store = store_for_owner(owner, substrate_store)
        if store == "model" and self.frozen:
            return "learning"
        return store

    def schema_stores(self, substrate_store: str = "model") -> List[str]:
        """Every store a per-owner table must exist in: where its rows are read
        from and written to."""
        stores = [substrate_store] + (["learning"] if self.frozen and substrate_store == "model" else [])
        return self._unique_stores(stores + ["user_context"])

    def maintained_stores(self, substrate_store: str = "model") -> List[str]:
        """The stores whose rows of a per-owner table maintenance may change
        (decay, clean-up, moving to the cold tier, refreshing what is derived).
        A frozen release is not maintained, and neither is what waits in the
        learning store for development: only people's context is."""
        if self.frozen:
            return ["user_context"]
        return self._unique_stores((substrate_store, "user_context"))

    def is_frozen_store(self, store: Optional[str]) -> bool:
        """Whether rows in this store may not be changed here: the release, and
        (for maintenance) the learning store's lessons waiting for development."""
        return self.frozen and store in ("model", "learning")

    @property
    def pool(self):
        """The connection pool of development, which has one. Staging and
        production have one per store: `pool_for(store)`."""
        return self._pool_for(None).pool

    def pool_for(self, store: str):
        """The connection pool a store's statements run in."""
        return self._pool_for(store).pool

    async def assert_database_identity(self, expected: str) -> str:
        """Verify against the live connections which databases these actually are.

        Asks the server rather than trusting configuration, so a mismatch is
        caught whether it came from resolution, a pooled connection or a
        singleton constructed earlier by something else. Required before any
        mutation-capable experiment: a process that believes it is operating on
        a clone while writing to production is not merely misconfigured.

        `expected` is the development database this process is configured from;
        in staging and production every store's database, named from it, is
        checked.
        """
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if expected != self.database:
            raise DatabaseIdentityError(
                f"operating from {self.database!r} "
                f"(configured from {self.config.provenance.get('database')}), not {expected!r}")
        for store in STORES:
            wanted = self.config.database_for(store)
            actual = await self.execute_query("SELECT current_database()", store=store)
            if isinstance(actual, list) and actual:
                actual = actual[0]
            if hasattr(actual, "values"):
                actual = list(actual.values())[0]
            actual = str(actual)

            if actual != wanted:
                raise DatabaseIdentityError(
                    f"{store} connected to {actual!r} while operating as {wanted!r} "
                    f"(configured from {self.config.provenance.get('database')}, "
                    f"{self.environment} from {self.config.provenance.get('environment')})"
                )
        return expected

    def _should_notify_error(self, operation: str) -> bool:
        """Decide whether to send a database error notification.

        Applies a startup grace window and per-operation retry threshold so
        transient errors during boot don't flood the notifications.
        """
        # Track how many times we've seen this operation fail
        current_count = self._error_counts.get(operation, 0) + 1
        self._error_counts[operation] = current_count

        # Within the grace window, suppress the first N failures per operation
        if self._error_grace_seconds > 0:
            since_boot = time.time() - self._boot_time
            if since_boot < self._error_grace_seconds and current_count <= self._error_retry_threshold:
                logger.warning(
                    "Suppressing %s database error (attempt %d within grace window %ds)",
                    operation,
                    current_count,
                    self._error_grace_seconds,
                )
                return False

        # Outside grace window or beyond retry threshold: notify
        return True

    # ── Pools and the event loop ──────────────────────────────────────────

    async def _ensure_pool_for_running_loop(self, pool: _DatabasePool) -> None:
        """Guarantee a usable pool before any query.

        Replaces a bare `if not self.initialized: raise`. That guard checked a
        boolean, not whether the pool could actually serve the CURRENT loop, so
        a manager initialized on one loop passed it and then failed inside
        asyncpg with a message about the query rather than the lifecycle.

        Re-initializing here is safe: initialize() is idempotent when every pool
        already matches the running loop.
        """
        if self.initialized and pool.matches_running_loop():
            return
        if not self._ever_initialized:
            # Never initialized at all — that is a caller error, not a loop one.
            raise RuntimeError(
                "Database not initialized. Call await db.initialize() at startup before using."
            )
        await self.initialize()

    async def _register_connection_codecs(self, conn) -> None:
        """Give one pooled connection the pgvector codec.

        Best-effort per connection: a database without the vector extension is
        still perfectly usable for everything that is not an embedding query, so
        a missing extension must not stop the pool from being created at all.
        Raising here would take out the whole pool -- and did, for any database
        created without pgvector.
        """
        try:
            await register_vector(conn)
        except Exception as e:
            logger.debug("pgvector codec unavailable on this connection: %s", e)

    async def _discard_pool(self, pool: _DatabasePool) -> None:
        """Drop a pool that belongs to a dead or foreign loop, releasing its
        sockets rather than abandoning them.

        `await pool.close()` is a graceful shutdown that has to run on the loop
        that owns the pool, so it is unavailable here by definition — this is
        called precisely when that loop is gone. Dropping the reference and
        waiting for the collector was the previous behaviour, and it leaks:
        every loop switch strands up to `pool_max_size` server connections
        until GC happens to run. A process that switches loops often — a worker
        thread with its own loop, repeated asyncio.run(), a test session where
        each test gets a fresh loop — walks that leak straight into
        `max_connections` and then fails to build ANY pool, which surfaces as a
        database outage in whatever unrelated component asked next.

        `terminate()` is asyncpg's synchronous, non-graceful release: it aborts
        the transports directly instead of negotiating shutdown, so it does not
        need the owning loop to still be alive. In-flight queries on that pool
        are already lost — the loop running them is dead — so there is nothing
        graceful left to preserve.
        """
        # Asked BEFORE the fields are cleared. matches_running_loop reads
        # pool.pool, so consulting it afterwards always answered False and the
        # graceful branch below could never be reached — every discard, even one
        # on the pool's own live loop, fell through to abandonment.
        owns_loop = pool.matches_running_loop()
        stale_tag = pool.tag

        old = pool.pool
        pool.pool = None
        pool.loop = None
        self.initialized = False
        if old is None:
            return

        if owns_loop:
            try:
                await old.close()
                return
            except Exception as e:
                logger.debug("Graceful close of old pool failed: %s", e)

        try:
            old.terminate()
            return
        except Exception as e:
            # Expected when the owning loop is gone: terminate() aborts the
            # transports, and aborting needs the loop. Nothing in this process
            # can release those sockets now, so the backends are handed to the
            # server-side reaper instead of being abandoned.
            logger.debug("Cannot terminate a pool from a dead loop (%s)", e)

        if stale_tag:
            pool.stale_tags.add(stale_tag)

    async def _reap_stale_pools(self, pool: _DatabasePool) -> int:
        """Close the server-side backends left by pools this process abandoned.

        Terminates by `application_name`, which is stamped per pool generation,
        so this can only ever reach connections THIS process opened and never
        the current pool. Anything else sharing the server -- another service,
        another instance -- is untouched by construction.

        Without this, each event-loop switch strands up to `pool_max_size`
        backends until the collector happens to run, and a process that
        switches loops faster than that walks into `max_connections`. The
        failure then surfaces as "cannot create pool" in whichever component
        asked next, which is never the one that caused it.
        """
        if not pool.stale_tags or pool.pool is None:
            return 0

        tags = sorted(pool.stale_tags - {pool.tag})
        if not tags:
            return 0

        try:
            rows = await pool.pool.fetch(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                " WHERE application_name = ANY($1::text[])"
                "   AND pid <> pg_backend_pid()",
                tags,
            )
        except Exception as e:
            # Reaping is hygiene, not correctness for THIS query. A failure
            # here must not stop the pool that was just built from being used.
            logger.warning("Could not reap abandoned database backends: %s", e)
            return 0

        pool.stale_tags -= set(tags)
        if rows:
            logger.info(
                "Reaped %d abandoned database backend(s) from %d dead pool(s)",
                len(rows), len(tags),
            )
        return len(rows)

    async def _create_pool(self, pool: _DatabasePool) -> None:
        """Build one database's connection pool on the running loop."""
        # Every pool generation is tagged so its server-side backends can be
        # identified later BY NAME. A pool abandoned with its dead loop
        # cannot be closed from Python -- asyncpg needs the owning loop to
        # abort the transports -- but the backends it left behind can be
        # reaped through ordinary SQL from the new one.
        pool.generation += 1
        pool.tag = f"lyric_{os.getpid()}_{pool.index}_{pool.generation}"

        pool.pool = await asyncpg.create_pool(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=pool.database,
            min_size=self.pool_min_size,
            max_size=self.pool_max_size,
            # An idle connection is closed, and opened again when it is needed.
            max_inactive_connection_lifetime=self.pool_idle_seconds,
            command_timeout=60,
            server_settings={'application_name': pool.tag},
            # EVERY pooled connection gets the pgvector codec, via asyncpg's
            # init hook. This function existed and was never passed anywhere;
            # registration was done once on a single acquired connection
            # instead, so exactly one connection in the pool could adapt a
            # Python list to `vector`. A lone query happened to get that
            # connection and worked, which is why this looked fine -- but
            # concurrent embedding queries fan out across the pool and the
            # rest failed with "expected str, got list".
            init=self._register_connection_codecs,
        )
        pool.loop = asyncio.get_running_loop()

        # The new pool is the first thing able to reach the server since
        # the old one died, so this is the earliest point the backends it
        # stranded can be closed.
        await self._reap_stale_pools(pool)

        logger.info(
            f"PostgreSQL database pool created "
            f"(database: {pool.database}, pool: {self.pool_min_size}-{self.pool_max_size})"
        )

        # Verify schemas exist
        try:
            async with pool.pool.acquire() as conn:
                schemas = await conn.fetch(
                    "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('unified', 'memory_hot', 'memory_cold')"
                )
                schema_names = [row['schema_name'] for row in schemas]

                if 'unified' in schema_names:
                    logger.info("✓ unified schema available (%s)", pool.database)
                if 'memory_hot' in schema_names:
                    logger.info("✓ memory_hot schema available (%s)", pool.database)
                if 'memory_cold' in schema_names:
                    logger.info("✓ memory_cold schema available (%s)", pool.database)

                if len(schema_names) == 0:
                    logger.warning(
                        "No schemas found in %s! Run postgres_schemas.sql to create database structure.",
                        pool.database,
                    )
        except Exception as e:
            logger.warning(f"Schema verification warning ({pool.database}): {e}")

    async def initialize(self) -> bool:
        """
        Initialize the connection pools

        One pool per database of this environment (one in development, one per
        store in staging and production), each serving every schema:
        - unified (main tables - directives, governance, logs)
        - memory_hot (hot tier with pgvector)
        - memory_cold (cold tier with pgvector)

        Staging and production then check, once per process, that they serve an
        intact release of the code they are running (releases.verify_serving). A
        failed check raises `ReleaseError` and the process does not start.

        Returns:
            True if successful
        """
        if self.initialized and all(p.matches_running_loop() for p in self._pools.values()):
            logger.debug("Database already initialized")
            return True

        if self.frozen and self.release_verified is None:
            from core.database.releases import verify_serving
            # Before any pool is used: a process that cannot show it serves an
            # intact release, cut with the code it runs, must not start.
            self.release_verified = await verify_serving(self.config)

        try:
            for pool in self._pools.values():
                if pool.matches_running_loop():
                    continue
                if pool.pool is not None:
                    # The pool belongs to a different event loop. asyncpg binds a pool
                    # and its connections to the loop that created them, so reusing it
                    # here fails deep inside the protocol with
                    #   InterfaceError: cannot perform operation: another operation is
                    #   in progress
                    # naming a query that is perfectly valid. This manager is a process
                    # singleton, so any caller that runs asyncio.run() twice, starts a
                    # worker thread with its own loop, or restarts the loop after a
                    # crash inherits a pool from a dead one. Rebuild instead.
                    logger.warning(
                        "Connection pool for %s belongs to a different event loop; "
                        "rebuilding for the running loop", pool.database
                    )
                    await self._discard_pool(pool)
                await self._create_pool(pool)

            self.initialized = True
            self._ever_initialized = True
            logger.info("PostgreSQL database initialization complete (%s%s: %s)", self.environment,
                        f" serving release {self.release}" if self.release else "", ", ".join(self._pools))
            return True

        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            self.metrics['pool_errors'] += 1

            # Send notification for database initialization failure (respect grace window)
            if self._should_notify_error("initialization"):
                try:
                    from core.utils.notification_helpers import notify_database_error
                    asyncio.create_task(notify_database_error(
                        operation="initialization",
                        error=e,
                        database="PostgreSQL Unified Database",
                        context={"host": self.host, "databases": list(self._pools)}
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send database error notification: {notify_error}")

            return False

    # ── Connections and statements ────────────────────────────────────────

    @asynccontextmanager
    async def _acquire(self, pool: _DatabasePool, schema: str):
        """A connection from one pool, its search path starting at `schema`."""
        await self._ensure_pool_for_running_loop(pool)

        if not pool.pool:
            raise RuntimeError("Database pool not available")

        # Acquire connection from pool
        async with pool.pool.acquire() as conn:
            self.metrics['total_connections'] += 1

            # Set search_path to route queries to appropriate schema
            # Include 'public' as fallback for extension types (vector, etc.)
            await conn.execute(f"SET search_path TO {schema}, public")

            try:
                yield conn
            finally:
                # Reset search_path to default after use
                await conn.execute("SET search_path TO public")

    @asynccontextmanager
    async def advisory_lock(self, key: str, *, store: Optional[str] = None):
        """Hold a named lock, across every instance of the model, while the block runs.

        The lock lives on a server session, so its connection is held for the
        whole block. That connection is its own, opened for the lock and closed
        with it, never one of the pool's: the block's statements need the pool,
        and a lock held on a pooled connection sits on one of them. With as many
        blocks at once as the pool has connections, every connection was held
        by a block waiting for another, and nothing moved until each timed out.
        If the process dies holding it, the server ends the session and the
        lock with it."""
        pool = self._pool_for(store)
        conn = await asyncpg.connect(
            host=self.host, port=self.port, user=self.user, password=self.password,
            database=pool.database, server_settings={'application_name': f"lyric_{os.getpid()}_lock"})
        try:
            await conn.execute("SELECT pg_advisory_lock(hashtext($1))", key)
            try:
                yield
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtext($1))", key)
        finally:
            await conn.close()

    @asynccontextmanager
    async def get_connection(self, use_hot_tier: bool = False, use_cold_tier: bool = False,
                             *, store: Optional[str] = None):
        """
        Get database connection from pool with schema routing (context manager)

        Args:
            use_hot_tier: Set search_path to memory_hot schema
            use_cold_tier: Set search_path to memory_cold schema
            store: which store the connection's statements belong to. Staging
                and production require it: the statements on a raw connection
                are not known in advance, so nothing else can place them. A raw
                connection to a frozen release is read-only in the database.

        Usage:
            # Unified schema (default)
            async with db.get_connection(store="runtime") as conn:
                result = await conn.fetch("SELECT * FROM internal_directives")

        Yields:
            asyncpg.Connection with search_path set to appropriate schema
        """
        async with self._acquire(self._pool_for(store), _tier_schema(use_hot_tier, use_cold_tier)) as conn:
            yield conn

    async def execute_query(
        self,
        query: str,
        params: Optional[Union[Tuple, List]] = None,
        use_hot_tier: bool = False,
        use_cold_tier: bool = False,
        fetch_one: bool = False,
        fetch_all: bool = False,
        commit: bool = False,
        *,
        store: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Execute SQL query with optional fetch/commit

        Args:
            query: SQL query to execute (use $1, $2, $3 placeholders)
            params: Query parameters (tuple or list)
            use_hot_tier: Use memory_hot schema
            use_cold_tier: Use memory_cold schema
            fetch_one: Fetch single row
            fetch_all: Fetch all rows
            commit: Commit transaction (asyncpg auto-commits by default)
            store: the store the statement belongs to, where its tables cannot
                say: rows of a per-owner table, or a statement touching no table.
                Staging and production route everything else by its tables.

        Returns:
            Query results if fetch_one/fetch_all, None otherwise. A creation
            statement checked against a frozen release returns "CHECKED".

        Note:
            PostgreSQL uses $1, $2, $3 placeholders instead of MySQL's %s.
            asyncpg returns asyncpg.Record objects which behave like dicts.
        """
        store = self._route(query, use_hot_tier, use_cold_tier, store)
        pool = self._pool_for(store)
        await self._ensure_pool_for_running_loop(pool)
        if self._checks_against_release(query, store):
            return await self._check_against_release(query, _tier_schema(use_hot_tier, use_cold_tier))

        # Safety/ergonomics: if a caller issues a SELECT-like query without
        # fetch_one/fetch_all, automatically fetch_all to avoid returning None.
        # This prevents a common class of "NoneType is not iterable" bugs.
        try:
            autofetch = os.getenv("LYRIC_DB_AUTOFETCH_SELECT", "true").strip().lower() not in {"0", "false", "no", "off"}
            if autofetch and not fetch_one and not fetch_all:
                q = (query or "").lstrip().lower()
                if q.startswith("select") or q.startswith("with") or q.startswith("show") or q.startswith("explain"):
                    fetch_all = True
        except Exception:
            pass

        try:
            async with self._acquire(pool, _tier_schema(use_hot_tier, use_cold_tier)) as conn:
                # Execute query with asyncpg
                # asyncpg uses positional parameters: $1, $2, $3
                if params:
                    # Convert params to list if tuple
                    params_list = list(params) if isinstance(params, tuple) else params
                else:
                    params_list = []

                self.metrics['total_queries'] += 1
                if use_cold_tier:
                    self.metrics['cold_tier_queries'] += 1
                elif use_hot_tier:
                    self.metrics['hot_tier_queries'] += 1
                else:
                    self.metrics['unified_queries'] += 1

                # Fetch results based on mode
                result = None
                if fetch_one:
                    # fetchrow returns single Record or None
                    result = await conn.fetchrow(query, *params_list)
                    # Convert Record to dict for compatibility with MySQL version
                    if result:
                        result = dict(result)
                elif fetch_all:
                    # fetch returns list of Records
                    result = await conn.fetch(query, *params_list)
                    # Convert Records to dicts for compatibility
                    result = [dict(row) for row in result]
                else:
                    # asyncpg's execute() returns a status string such as
                    # "UPDATE 3" / "INSERT 0 1". It was being DISCARDED, so every
                    # write in the substrate returned None and no caller could
                    # tell a write that changed 3 rows from one that changed
                    # none. Capturing it is what lets update_memory() report an
                    # honest False when a row does not exist in the tier.
                    result = await conn.execute(query, *params_list)

                # Note: asyncpg auto-commits by default for non-transactional queries
                # commit parameter kept for API compatibility but is a no-op

                return result

        except Exception as e:
            logger.error(f"Query execution failed: {type(e).__name__}: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Params: {params}")
            self.metrics['failed_queries'] += 1

            # Send notification for query failure (respect grace window)
            if self._should_notify_error("query"):
                try:
                    from core.utils.notification_helpers import notify_database_error
                    asyncio.create_task(notify_database_error(
                        operation="query",
                        error=e,
                        database="PostgreSQL",
                        context={
                            "query": query[:200] if len(query) > 200 else query,
                            "tier": "cold" if use_cold_tier else ("hot" if use_hot_tier else "unified"),
                            "database": pool.database,
                        }
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send query error notification: {notify_error}")

            raise

    async def query(
        self,
        query: str,
        params: Optional[Tuple] = None,
        use_hot_tier: bool = False,
        *,
        store: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return all results as list of dicts

        This is a convenience method that wraps execute_query with fetch_all=True.
        Used by security tools and other components that need simple query access.

        Args:
            query: SQL query to execute (use $1, $2, $3 placeholders)
            params: Query parameters (tuple)
            use_hot_tier: Use memory_hot schema
            store: as for execute_query

        Returns:
            List of result rows as dictionaries
        """
        result = await self.execute_query(query, params, use_hot_tier=use_hot_tier, fetch_all=True,
                                          store=store)
        return result if result is not None else []

    async def ensure_schema(self, key: str, statements: List[str], *,
                            store: Optional[str] = None) -> None:
        """Create what a store needs, once per process, safely when many do it at once.

        `CREATE TABLE IF NOT EXISTS` is not safe CONCURRENTLY: two sessions that
        both find the table missing both create it, and the second fails on
        Postgres's catalog (`duplicate key ... pg_type_typname_nsp_index`).
        Measured: two processes counting one client's first requests at once. So
        the statements run in one transaction holding an advisory lock named for
        `key`, which makes every other creator of the same schema wait and then
        find it there.

        Outside development each statement runs in the database its tables live
        in. A per-owner table lives in every store its rows are read from or
        written to (`schema_stores`), so unless `store` names one, its statements
        run in each. Against a frozen release a statement is checked, not run
        (`_check_against_release`).
        """
        by_pool: Dict[str, List[str]] = {}
        checks: List[str] = []
        for statement in statements:
            if not self.frozen:
                stores = [store]
            elif store is None and any(t in PER_OWNER_TABLES for t in tables_in(statement)):
                # The table must exist wherever its rows can be read or written.
                stores = []
                for table in sorted(t for t in tables_in(statement) if t in PER_OWNER_TABLES):
                    stores += [s for s in self.schema_stores(PER_OWNER_TABLES[table]) if s not in stores]
                for each in stores:
                    store_for_statement(statement, store=each)
            else:
                stores = [store_for_statement(statement, store=store)]
            for each in stores:
                if self._checks_against_release(statement, each):
                    checks.append(statement)
                else:
                    by_pool.setdefault(self._pool_for(each).database, []).append(statement)

        release_key = ("release", key)
        if checks and release_key not in self._pool_for("model").schemas_ready:
            for statement in checks:
                await self._check_against_release(statement, 'unified')
            self._pool_for("model").schemas_ready.add(release_key)
        for database, group in by_pool.items():
            pool = self._pools[database]
            if key in pool.schemas_ready:
                continue
            async with self._acquire(pool, 'unified') as conn:
                async with conn.transaction():
                    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))",
                                       f"schema:{key}")
                    for statement in group:
                        await conn.execute(statement)
            pool.schemas_ready.add(key)

    async def execute_many(
        self,
        query: str,
        params_list: List[Tuple],
        use_hot_tier: bool = False,
        use_cold_tier: bool = False,
        commit: bool = True,
        *,
        store: Optional[str] = None,
    ) -> int:
        """
        Execute query with multiple parameter sets

        Args:
            query: SQL query to execute (use $1, $2, $3 placeholders)
            params_list: List of parameter tuples
            use_hot_tier: Use memory_hot schema
            use_cold_tier: Use memory_cold schema
            commit: Commit transaction (kept for API compatibility)
            store: as for execute_query

        Returns:
            Number of rows affected
        """
        store = self._route(query, use_hot_tier, use_cold_tier, store)
        pool = self._pool_for(store)
        await self._ensure_pool_for_running_loop(pool)
        if self._checks_against_release(query, store):
            await self._check_against_release(query, _tier_schema(use_hot_tier, use_cold_tier))
            return 0

        try:
            async with self._acquire(pool, _tier_schema(use_hot_tier, use_cold_tier)) as conn:
                # asyncpg executemany
                result = await conn.executemany(query, params_list)

                self.metrics['total_queries'] += len(params_list)
                if use_cold_tier:
                    self.metrics['cold_tier_queries'] += len(params_list)
                elif use_hot_tier:
                    self.metrics['hot_tier_queries'] += len(params_list)
                else:
                    self.metrics['unified_queries'] += len(params_list)

                # Return number of affected rows (executemany returns status string)
                return len(params_list)

        except Exception as e:
            logger.error(f"Execute many failed: {e}")
            logger.error(f"Query: {query}")
            self.metrics['failed_queries'] += 1

            # Send notification for execute many failure (respect grace window)
            if self._should_notify_error("execute_many"):
                try:
                    from core.utils.notification_helpers import notify_database_error
                    asyncio.create_task(notify_database_error(
                        operation="execute_many",
                        error=e,
                        database="PostgreSQL",
                        context={
                            "query": query[:200] if len(query) > 200 else query,
                            "batch_size": len(params_list),
                            "tier": "cold" if use_cold_tier else ("hot" if use_hot_tier else "unified"),
                            "database": pool.database,
                        }
                    ))
                except Exception as notify_error:
                    logger.warning(f"Failed to send execute many error notification: {notify_error}")

            raise

    async def table_exists(self, table_name: str, use_hot_tier: bool = False, use_cold_tier: bool = False,
                           *, store: Optional[str] = None) -> bool:
        """
        Check if table exists in schema

        Args:
            table_name: Table name to check
            use_hot_tier: Check in memory_hot schema
            use_cold_tier: Check in memory_cold schema
            store: for a per-owner table, whose database to look in

        Returns:
            True if table exists
        """
        schema = _tier_schema(use_hot_tier, use_cold_tier)
        # The table asked about decides the database, as it would for a statement on it.
        store = self._route(f"SELECT FROM {schema}.{table_name}", use_hot_tier, use_cold_tier, store)

        result = await self.execute_query(
            """
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = $2
            """,
            params=(schema, table_name),
            fetch_one=True,
            store=store,
        )

        return result['count'] > 0 if result else False

    async def create_database_if_not_exists(
        self,
        database_name: str
    ) -> bool:
        """
        Create database if it doesn't exist

        Args:
            database_name: Database name to create

        Returns:
            True if successful
        """
        try:
            # Connect to postgres default database to create new database
            temp_pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database='postgres',  # Connect to default database
                min_size=1,
                max_size=1
            )

            async with temp_pool.acquire() as conn:
                # Check if database exists
                exists = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1",
                    database_name
                )

                if not exists:
                    # CREATE DATABASE cannot run in transaction, use execute directly
                    await conn.execute(f'CREATE DATABASE {database_name}')
                    logger.info(f"Database {database_name} created")
                else:
                    logger.info(f"Database {database_name} already exists")

            await temp_pool.close()
            return True

        except Exception as e:
            logger.error(f"Failed to create database {database_name}: {e}")
            return False

    async def execute_schema_file(
        self,
        schema_file: Path,
        use_hot_tier: bool = False,
        *,
        store: Optional[str] = None,
    ) -> bool:
        """
        Execute SQL schema file

        Args:
            schema_file: Path to SQL schema file
            use_hot_tier: Execute on memory_hot schema (kept for API compatibility)
            store: which store's database the file builds; required outside development

        Returns:
            True if successful
        """
        if not schema_file.exists():
            logger.error(f"Schema file not found: {schema_file}")
            return False

        pool = self._pool_for(store)
        try:
            # Read schema file
            with open(schema_file, 'r', encoding='utf-8') as f:
                schema_sql = f.read()

            # Execute entire schema (PostgreSQL handles multi-statement execution)
            await self._ensure_pool_for_running_loop(pool)
            async with pool.pool.acquire() as conn:
                await conn.execute(schema_sql)

            logger.info(f"Schema file executed: {schema_file.name} ({pool.database})")
            return True

        except Exception as e:
            logger.error(f"Failed to execute schema file {schema_file}: {e}")
            return False

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get database metrics

        Returns:
            Dict with database metrics, the pool figures per database
        """
        pool_metrics = {}

        for pool in self._pools.values():
            if pool.pool:
                pool_metrics[pool.database] = {
                    'size': pool.pool.get_size(),
                    'min_size': pool.pool.get_min_size(),
                    'max_size': pool.pool.get_max_size()
                }

        return {
            'initialized': self.initialized,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'environment': self.environment,
            'release': self.release,
            'databases': self.config.databases(),
            'pool_metrics': pool_metrics,
            'query_metrics': self.metrics.copy()
        }

    async def health_check(self) -> Dict[str, Any]:
        """
        Check database health, in every database of this environment

        Returns:
            Dict with health status; `databases` holds each database's own
        """
        health = {
            'initialized': self.initialized,
            'pool_available': all(p.pool is not None for p in self._pools.values()),
            'unified_connection_ok': True,
            'hot_connection_ok': True,
            'cold_connection_ok': True,
            'pgvector_available': True,
            'databases': {},
            'errors': []
        }

        # One check per database: in development every store is the same one.
        checked = {}
        for store in STORES:
            database = self.config.database_for(store)
            if database in checked:
                continue
            pool = self._pools[database]
            own = {
                'stores': [s for s in STORES if self.config.database_for(s) == database],
                'unified_connection_ok': False,
                'hot_connection_ok': False,
                'cold_connection_ok': False,
                'pgvector_available': False,
            }
            checked[database] = own
            if pool.pool is None:
                health['errors'].append(f"{database}: no connection pool")
            else:
                for key, hot, cold in (('unified_connection_ok', False, False),
                                       ('hot_connection_ok', True, False),
                                       ('cold_connection_ok', False, True)):
                    try:
                        result = await self.execute_query(
                            "SELECT 1 as test", use_hot_tier=hot, use_cold_tier=cold,
                            fetch_one=True, store=store)
                        own[key] = result is not None
                    except Exception as e:
                        health['errors'].append(f"{database}: {key.replace('_ok', '')} test failed: {e}")
                try:
                    async with self._acquire(pool, 'unified') as conn:
                        result = await conn.fetchval(
                            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                        )
                        own['pgvector_available'] = result is not None
                except Exception as e:
                    health['errors'].append(f"{database}: pgvector test failed: {e}")
            for key in ('unified_connection_ok', 'hot_connection_ok', 'cold_connection_ok',
                        'pgvector_available'):
                health[key] = health[key] and own[key]
        health['databases'] = checked

        health['healthy'] = (
            health['unified_connection_ok'] and
            health['hot_connection_ok'] and
            health['cold_connection_ok'] and
            health['pgvector_available'] and
            len(health['errors']) == 0
        )

        return health

    async def close(self) -> None:
        """
        Close the connection pools

        Closes every pool of this environment and releases all connections.
        """
        for pool in self._pools.values():
            if pool.pool:
                await pool.pool.close()
                logger.info("PostgreSQL database pool closed (%s)", pool.database)
            pool.pool = None
            pool.loop = None

        self.initialized = False
        logger.info("Database connections closed")

    async def __aenter__(self):
        """Async context manager entry"""
        for pool in self._pools.values():
            await self._ensure_pool_for_running_loop(pool)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


# Convenience alias
LyricUnifiedDatabase = LyricUnifiedDatabasePostgres

async def get_unified_database() -> LyricUnifiedDatabasePostgres:
    """
    Get singleton instance of unified database.

    NOTE: This does NOT auto-initialize. The database must be initialized
    separately at startup via main.py or service initialization.

    The class itself is a singleton via __new__.

    Returns:
        LyricUnifiedDatabasePostgres singleton instance (may not be initialized)
    """
    return LyricUnifiedDatabasePostgres()


# Alias for shorter name
get_unified_db = get_unified_database
