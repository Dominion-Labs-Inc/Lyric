#!/usr/bin/env python3
"""Where PostgreSQL connection settings come from, and in what order.

One authority, with an explicit precedence:

    explicit argument  >  process environment  >  .env file  >  coded default

The defect this replaces: the database class called
``load_dotenv(".env.postgres", override=True)`` inside its own constructor,
*then* read ``os.getenv('POSTGRES_DATABASE')``. Because ``override=True``
rewrites the process environment, the file always won and the environment read
on the next line could never see an externally-supplied value. A subprocess
launched with ``POSTGRES_DATABASE=lyric_abl_blank`` connected to
``lyric_db`` and said nothing.

That was found by an ablation in which every condition -- including the ones
whose learned rules had been deleted -- loaded identical rules and passed
identically. The severance oracle worked: it showed the intended intervention
was not causally connected to the runtime's actual authority. The same defect
reaches CI, staging, container secrets, credential rotation and any maintenance
script that expects deployment configuration to override local defaults.

A database implementation consumes configuration; it does not mutate the
process it runs in. Resolution here reads ``.env`` files with ``dotenv_values``,
which returns a mapping and leaves ``os.environ`` untouched, so importing or
constructing a database never changes what any other component will observe.

Provenance is recorded per field so the answer to "which database am I actually
configured for, and who decided that" is available rather than inferred.

ENVIRONMENTS AND RELEASES. The model is taught in DEVELOPMENT and served, frozen, in STAGING and
PRODUCTION from a numbered RELEASE. Every database of a model's line is named
from its development database, `POSTGRES_DATABASE` (the root), so a sandbox line
(`lyric_dev`) never reaches the main line's releases or registry.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent

#: Consulted in order; the first file that exists supplies fallback values.
DEFAULT_ENV_FILES: Sequence[Path] = (
    _ROOT / ".env.postgres",
    _ROOT / ".env.production",
)

#: Lyric's OWN PostgreSQL instance. 5432 is the shared Homebrew instance that
#: also holds agentso's tenant databases, and Lyric connected there as a
#: superuser with BypassRLS -- no boundary at all between the substrate and that
#: data. The instances were separated for that reason: separate port, separate
#: data directory, separate process.
#:
#: THE CODED DEFAULT MUST BE 5433, NOT 5432. This is the value used when no
#: env file and no environment variable is found -- a container, a different
#: working directory, a copied deployment. Defaulting to 5432 means the
#: fallback path silently lands on agentso's instance, which is both the wrong
#: data and a boundary violation. A missing config should fail toward Lyric's
#: own database, never toward somebody else's.
#:
#: Imported by every other module that needs a port, so this is the one place
#: it is written down.
DEFAULT_PORT = 5433

#: Where the model is taught (development), and where a release of it is served, frozen (staging runs a
#: release candidate exactly as production would, before it is promoted).
ENVIRONMENTS = ("development", "staging", "production")
FROZEN_ENVIRONMENTS = ("staging", "production")

#: What an environment keeps apart:
#:   runtime       its running store: tasks, queue, its own records
#:   model         what the substrate knows: its memory, beliefs, and the facts linked in it. In staging and
#:                 production this is the release, read-only
#:   user_context  each person's context
#:   learning      staging and production only: what the substrate remembers of its own while serving, kept
#:                 for development, never read back while serving
#: Development keeps all of them in its one database.
STORES = ("runtime", "model", "user_context", "learning")

DEFAULTS: Dict[str, Any] = {
    "host": "localhost",
    "port": DEFAULT_PORT,
    "database": "lyric_db",
    "user": "postgres",
    "password": "",
    "pool_min_size": 5,
    "pool_max_size": 20,
    "environment": "development",
    "release": "",
}

ENV_KEYS: Dict[str, str] = {
    "host": "POSTGRES_HOST",
    "port": "POSTGRES_PORT",
    "database": "POSTGRES_DATABASE",
    "user": "POSTGRES_USER",
    "password": "POSTGRES_PASSWORD",
    "pool_min_size": "POSTGRES_POOL_MIN_SIZE",
    "pool_max_size": "POSTGRES_POOL_MAX_SIZE",
    "environment": "LYRIC_ENVIRONMENT",
    "release": "LYRIC_RELEASE",
}

#: Settings that no longer exist. Set anyway, they would be ignored without a word, so they are refused.
RETIRED_KEYS: Dict[str, str] = {
    "LYRIC_COPY": "LYRIC_COPY was replaced by LYRIC_ENVIRONMENT (development, staging, production) and "
                    "LYRIC_RELEASE",
}


def _qualified(schema: str, names: str) -> frozenset:
    return frozenset(f"{schema}.{name}" for name in names.split())


#: THE STORE OF EVERY TABLE THE SUBSTRATE USES. The one authority statements are placed by: a statement goes to
#: the database its tables live in. A table in none of these sets is refused outside development, never guessed.
STORE_TABLES: Dict[str, frozenset] = {
    "runtime": _qualified("unified", """
        affect_state backup_records causal_feedback_analyses chaos_adapter_state chaos_events
        chaos_experiments chaos_metrics component_health component_snapshots components cross_domain_queries
        directive_ab_tests directive_applications emergency_halts extraction_attempts
        failure_events frozen_capability_benchmarks goals intents internal_directives intrinsic_motivation
        knowledge_refresh long_term_baselines meta_decision_records meta_learning_strategies meta_learning_tasks
        meta_parameter_snapshots motivation_history motivation_profile novelty_detections operation_logs
        performance_logs performance_metrics plans queue_instances reasoning_bridge_stats reasoning_telemetry
        regression_events safety_assessments storage_health_probe system_control_commands system_control_status
        system_failures task_queue test_results test_sessions tool_error_events tool_execution_events
        tool_usage_history capability_benchmark_results capability_reports directive_evolution_log
        improvement_metrics meta_health_alerts metric_measurements prediction_results profiler_results
        task_execution_history release_memory_usage"""),
    "model": _qualified("unified", """
        analogies beliefs calibration_data clause_classifiers concept_aliases concept_domains concept_evidence
        concept_identity_relations concept_mappings concept_relations concepts domain_controllability
        domain_mappings domain_volatility domains evidence_envelopes held_conditionals
        knowledge_consumption knowledge_transfers knowledge_updates learned_rule_evidence learned_rules
        mapping_usage_events operator_demonstrations operator_induction_pending
        rule_authority_events rule_identity_aliases rule_projections
        rule_supersessions schemas sense_taxonomy vision_instances sound_instances
        security_training_examples"""),
    "user_context": _qualified("unified", """
        scoped_beliefs scoped_concept_relations user_beliefs"""),
}

#: Tables whose rows belong to whoever they are about, and the store the SUBSTRATE's own rows are kept in. A
#: person's rows are that person's context. The table exists in both databases, so the table cannot decide:
#: the caller names the store (shared_types.store_for_owner, and the manager's `write_store` for a write).
#:   memories, their images and archive log, the questions it could not answer, the experiences waiting in
#:   the pool, perceptions, and what reasoning wrote down (arguments, temporal knowledge, hypotheses with their
#:   experiments and evidence): the substrate's are the model (and, while serving frozen, the ones it makes go
#:   to the learning store);
#:   an intent's content (`scoped_intents`): the substrate's own intents are runtime, beside their shape rows
#:   in `intents` (intent_authority: "its content lives under this scope like any actor's");
#:   work that permanently failed (`failed_task_fingerprints`): the substrate's own is runtime, what it must not
#:   queue again; a person's request text is theirs.
PER_OWNER_TABLES: Dict[str, str] = {
    **{table: "model" for table in (
        _qualified("memory_hot", "memory_hot archive_log")
        | _qualified("memory_cold", "memory_cold")
        | _qualified("unified", "memory_media known_unknowns experience_pool perceptions "
                     "reasoning_arg_claims reasoning_arguments reasoning_arg_fallacies "
                     "reasoning_temporal_propositions reasoning_temporal_causal_links "
                     "hypotheses experiments evidence"))},
    "unified.scoped_intents": "runtime",
    "unified.failed_task_fingerprints": "runtime",
}

#: Tables the tools in `core/tools/` keep. Tools serve the substrate itself, people and other systems, so
#: their tables belong to no store of the substrate. Development keeps them in its one
#: database; in staging and production a statement on one is refused, because where a tool's own data lives
#: there has not been decided.
TOOL_TABLES = _qualified("unified", """
    access_logs auth_logs dns_logs file_integrity_logs memory_operations network_logs process_logs
    rate_limit_events row_access_policies schema_migrations security_events system_alerts""")

#: Names written like tables in SQL that are not tables: the enum types, and an index.
NOT_TABLES = (_qualified("unified", """
    ab_test_status chaos_severity chaos_status context_type directive_category directive_status
    evolution_type intent_type log_level test_status tracking_type knowledge_updates_unconsumed_idx""")
              | _qualified("memory_hot", "memory_status memory_type"))

_STORE_OF: Dict[str, str] = {table: store for store, tables in STORE_TABLES.items() for table in tables}
_KNOWN = frozenset(_STORE_OF) | frozenset(PER_OWNER_TABLES) | TOOL_TABLES


def tables_of(store: str) -> frozenset:
    """Every table a store's database keeps outside development: its own, and each per-owner table it can hold
    rows of. The learning store holds only the substrate's own rows of the model's per-owner tables."""
    if store == "learning":
        return frozenset(t for t, substrate in PER_OWNER_TABLES.items() if substrate == "model")
    own = set(STORE_TABLES[store])
    for table, substrate_store in PER_OWNER_TABLES.items():
        if store in (substrate_store, "user_context"):
            own.add(table)
    return frozenset(own)


class StoreRoutingError(RuntimeError):
    """A statement that cannot be placed in exactly one database of its environment.

    Raised instead of guessing. A statement sent to the wrong database there does not fail -- every table exists
    in the store it belongs to -- it reads or writes the wrong store, which is the separation broken silently.
    """


class ModelFrozenError(StoreRoutingError):
    """A write to the model where the model is a frozen release (staging, production).

    A release is never edited: it is replaced by a newer one, cut in development. Raised before the statement
    reaches the database; the release is read-only there as well."""


class ReleaseMismatchError(StoreRoutingError):
    """Code that creates a table, index or column its release does not have: the release and the code running
    it do not match. A frozen release cannot be given what it lacks."""


#: A schema-qualified name, not preceded by `::` (a cast to one of the enum types) or by another name.
_QUALIFIED = re.compile(r"(?<![\w.:])(unified|memory_hot|memory_cold)\.([a-z_][a-z0-9_]*)\b")
#: A name the search path resolves: the word after a keyword that introduces a table. Only a name that is a
#: known table counts, so a function (`unnest(`) or a column (`EXTRACT(EPOCH FROM created_at)`) never does; a
#: name followed by `.` is an alias or a schema, not a table.
_UNQUALIFIED = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE|EXISTS|REFERENCES|ON|TRUNCATE)\s+"
    r"(?!(?:unified|memory_hot|memory_cold|public|information_schema|pg_catalog)\.)"
    r"([a-z_][a-z0-9_]*)\b(?!\s*\.)", re.IGNORECASE)


def tables_in(statement: str, search_schema: str = "unified") -> frozenset:
    """The substrate's tables a statement touches, schema-qualified.

    A name written without its schema is resolved the way PostgreSQL resolves it, through the search path the
    database manager sets itself (`search_schema`, then `public`). A qualified name that is neither a known table
    nor one of the types is returned as it is, so the caller can refuse it."""
    found = set()
    for schema, name in _QUALIFIED.findall(statement or ""):
        qualified = f"{schema}.{name}"
        if qualified in NOT_TABLES:
            continue
        if schema != "unified" and qualified not in _KNOWN:
            # `memory_hot.access_count` in an upsert on the table `memory_hot`: the table's name and a column,
            # not a schema and a table. No table is named `unified`, so `unified.x` is always a table or a type.
            continue
        found.add(qualified)
    for name in _UNQUALIFIED.findall(statement or ""):
        qualified = f"{search_schema}.{name.lower()}"
        if qualified in _KNOWN:
            found.add(qualified)
    return frozenset(found)


def store_for_statement(statement: str, *, search_schema: str = "unified",
                        store: Optional[str] = None) -> str:
    """The one store a statement belongs to, outside development.

    The tables decide. The caller names the store only where the tables cannot: rows of a per-owner table, and a
    statement that touches no table. A statement touching two stores, a table no store holds, or a tool's table
    is refused."""
    if store is not None and store not in STORES:
        raise StoreRoutingError(f"{store!r} is not a store; the stores are {', '.join(STORES)}")
    tables = tables_in(statement, search_schema)
    unknown = sorted(t for t in tables if t not in _KNOWN)
    if unknown:
        raise StoreRoutingError(f"table(s) no store holds: {unknown}; classify them in "
                                f"postgres_config.STORE_TABLES")
    tools = sorted(tables & TOOL_TABLES)
    if tools:
        raise StoreRoutingError(f"{tools} belong to the tools, which only development keeps data for")
    decided = {_STORE_OF[t] for t in tables if t in _STORE_OF}
    if len(decided) > 1:
        raise StoreRoutingError(f"one statement touches {sorted(decided)} ({sorted(tables)}); "
                                f"they are kept in separate databases")
    per_owner = sorted(t for t in tables if t in PER_OWNER_TABLES)
    if per_owner:
        if store is None:
            raise StoreRoutingError(f"{per_owner} hold both the substrate's rows and people's; "
                                    f"name the store the rows belong to")
        for table in per_owner:
            substrate_store = PER_OWNER_TABLES[table]
            allowed = {substrate_store, "user_context"} | ({"learning"} if substrate_store == "model" else set())
            if store not in allowed:
                raise StoreRoutingError(f"{table} is kept in {substrate_store} (the substrate's rows), "
                                        f"user_context (people's)"
                                        + (" and learning (what it remembers while serving)"
                                           if substrate_store == "model" else "") + f", not {store}")
        if decided and decided != {store}:
            raise StoreRoutingError(f"{per_owner} named as {store}, but the statement also touches "
                                    f"{sorted(decided)}")
        return store
    if decided:
        (only,) = decided
        if store is not None and store != only:
            raise StoreRoutingError(f"named {store}, but its tables are in {only}: {sorted(tables)}")
        return only
    if store is None:
        raise StoreRoutingError("the statement touches no table, so nothing places it; name the store")
    return store


# ── What a statement does: read, change the schema, or write ─────────────────────────────────────────────────

#: Comments and literals, removed before a statement's keywords are read, so a word inside a string or a
#: comment ("update", "drop") is never taken for what the statement does.
_NOT_KEYWORDS = re.compile(r"--[^\n]*|/\*.*?\*/|'(?:[^']|'')*'|\$(\w*)\$.*?\$\1\$", re.S)
#: Anything that changes data (or needs to: a row lock, a sequence). A read-only transaction refuses each.
_WRITES = re.compile(
    r"\bINSERT\s+INTO\b|\bUPDATE\s+(?:ONLY\s+)?[\w.\"]+\s+(?:(?:AS\s+)?(?!SET\b)\w+\s+)?SET\b|\bDELETE\s+FROM\b"
    r"|\bMERGE\s+INTO\b|\bTRUNCATE\b|\bCOPY\s+[\w.\"]+(?:\s*\([^)]*\))?\s+FROM\b"
    r"|\bFOR\s+(?:NO\s+KEY\s+)?UPDATE\b|\bFOR\s+(?:KEY\s+)?SHARE\b|\bnextval\s*\(|\bsetval\s*\("
    r"|\bLOCK\s+TABLE\b|^\s*LOCK\b|\bREFRESH\s+MATERIALIZED\b|^\s*(?:VACUUM|ANALYZE|REINDEX|CLUSTER|GRANT|REVOKE"
    r"|CALL|DO)\b", re.I | re.M)
_SCHEMA_CHANGE = re.compile(r"^\s*(?:CREATE|ALTER|DROP|COMMENT)\b", re.I)


def statement_kind(statement: str) -> str:
    """"schema" (it creates, alters or drops), "write" (it changes rows, locks them or moves a sequence), or
    "read". A frozen release answers reads, has its schema checked, and refuses writes."""
    text = _NOT_KEYWORDS.sub(" ", statement or "")
    if _SCHEMA_CHANGE.match(text):
        return "schema"
    if _WRITES.search(text):
        return "write"
    return "read"


class SchemaRequirement(NamedTuple):
    """What a creation statement needs of a frozen release: `kind` (table, index, column or constraint) in
    `schema`, on `table`, named `name`, `present` or not (a `DROP ... IF EXISTS` needs it absent)."""
    kind: str
    schema: str
    table: str
    name: str
    present: bool


def _ident(text: str) -> str:
    """An identifier as PostgreSQL stores it: quoted ones as written, unquoted ones in lower case."""
    text = text.strip()
    return text[1:-1] if len(text) > 1 and text[0] == text[-1] == '"' else text.lower()


def _qualify(name: str, default_schema: str):
    parts = [_ident(p) for p in re.split(r'\.(?=(?:[^"]*"[^"]*")*[^"]*$)', name)]
    return (parts[0], parts[1]) if len(parts) == 2 else (default_schema, parts[0])


def _top_level_parts(text: str) -> List[str]:
    """`text` split at the commas outside parentheses: `ADD a NUMERIC(10,2), ADD b INT` is two actions."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


_IDENT = r'(?:"[^"]+"|[\w$]+)'
_NAME = rf'{_IDENT}(?:\.{_IDENT})?'
_CREATE_TABLE = re.compile(rf"^\s*CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<name>{_NAME})",
                           re.I)
_CREATE_INDEX = re.compile(rf"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
                           rf"(?P<name>{_IDENT})\s+ON\s+(?:ONLY\s+)?(?P<table>{_NAME})", re.I)
_DROP_INDEX = re.compile(rf"^\s*DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?IF\s+EXISTS\s+(?P<name>{_NAME})"
                         rf"\s*(?:CASCADE|RESTRICT)?\s*$", re.I)
_ALTER_TABLE = re.compile(rf"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<table>{_NAME})\s+"
                          rf"(?P<actions>.+)$", re.I | re.S)
_ADD_CONSTRAINT = re.compile(rf"^ADD\s+CONSTRAINT\s+(?P<name>{_IDENT})\b", re.I)
_ADD_COLUMN = re.compile(rf"^ADD\s+(?:COLUMN\s+)?IF\s+NOT\s+EXISTS\s+(?P<name>{_IDENT})\b", re.I)
_DROP_COLUMN = re.compile(rf"^DROP\s+(?:COLUMN\s+)?IF\s+EXISTS\s+(?P<name>{_IDENT})\s*(?:CASCADE|RESTRICT)?$",
                          re.I)


def schema_requirements(statement: str, search_schema: str = "unified") -> Optional[List[SchemaRequirement]]:
    """What a creation statement needs a frozen release to already have, or None when it is not a form that
    can be checked (it would then have to change the release, which cannot be done).

    The forms the substrate uses (measured 2026-09-27): CREATE TABLE / INDEX IF NOT EXISTS, ALTER TABLE ... ADD
    COLUMN IF NOT EXISTS or DROP COLUMN IF EXISTS, ADD CONSTRAINT, DROP INDEX IF EXISTS."""
    text = _NOT_KEYWORDS.sub(" ", statement or "").strip().rstrip(";").strip()
    match = _CREATE_TABLE.match(text)
    if match:
        schema, table = _qualify(match["name"], search_schema)
        return [SchemaRequirement("table", schema, table, table, True)]
    match = _CREATE_INDEX.match(text)
    if match:
        schema, table = _qualify(match["table"], search_schema)
        return [SchemaRequirement("index", schema, table, _ident(match["name"]), True)]
    match = _DROP_INDEX.match(text)
    if match:
        schema, index = _qualify(match["name"], search_schema)
        return [SchemaRequirement("index", schema, "", index, False)]
    match = _ALTER_TABLE.match(text)
    if match:
        schema, table = _qualify(match["table"], search_schema)
        needs = []
        for action in _top_level_parts(match["actions"]):
            for pattern, kind, present in ((_ADD_CONSTRAINT, "constraint", True), (_ADD_COLUMN, "column", True),
                                           (_DROP_COLUMN, "column", False)):
                found = pattern.match(action)
                if found:
                    needs.append(SchemaRequirement(kind, schema, table, _ident(found["name"]), present))
                    break
            else:
                return None
        return needs or None
    return None


_INTEGERS = {"port", "pool_min_size", "pool_max_size"}


class DatabaseIdentityError(RuntimeError):
    """Raised when the connected database is not the one that was intended.

    A process reporting that it operates against one database while writing to
    another is an authority contradiction, and for anything mutation-capable it
    has to stop rather than proceed on the assumption.
    """


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    #: the development database of this model's line: the one database of development, and the root every
    #: other database of the line is named from
    database: str
    user: str
    password: str
    pool_min_size: int
    pool_max_size: int
    #: development, staging or production (ENVIRONMENTS)
    environment: str
    #: the release a staging or production process serves; None in development
    release: Optional[int]
    #: field name -> "explicit" | "environment" | "dotenv:<file>" | "default"
    provenance: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        *,
        env: Optional[Mapping[str, str]] = None,
        env_files: Optional[Sequence[Path]] = None,
        **explicit: Any,
    ) -> "PostgresConfig":
        """Resolve settings without mutating the process environment."""
        environment = os.environ if env is None else env
        files = DEFAULT_ENV_FILES if env_files is None else env_files

        from_file: Dict[str, str] = {}
        file_label = ""
        for path in files:
            if path.exists():
                from_file = {k: v for k, v in dotenv_values(path).items() if v is not None}
                file_label = f"dotenv:{path.name}"
                break

        for key, why in RETIRED_KEYS.items():
            if environment.get(key) not in (None, "") or from_file.get(key) not in (None, ""):
                raise ValueError(why)

        values: Dict[str, Any] = {}
        provenance: Dict[str, str] = {}
        for name, default in DEFAULTS.items():
            key = ENV_KEYS[name]
            supplied = explicit.get(name)
            if supplied is not None:
                raw, source = supplied, "explicit"
            elif environment.get(key) not in (None, ""):
                raw, source = environment[key], "environment"
            elif from_file.get(key) not in (None, ""):
                raw, source = from_file[key], file_label
            else:
                raw, source = default, "default"

            values[name] = int(raw) if name in _INTEGERS else str(raw)
            provenance[name] = source

        if values["environment"] not in ENVIRONMENTS:
            raise ValueError(f"LYRIC_ENVIRONMENT={values['environment']!r} ({provenance['environment']}) is not "
                             f"an environment; the environments are {', '.join(ENVIRONMENTS)}")
        release = values["release"]
        if values["environment"] == "development":
            if release:
                raise ValueError(f"LYRIC_RELEASE={release!r} ({provenance['release']}) names a release, but "
                                 f"development serves none: it is where the model is taught")
            values["release"] = None
        else:
            if not re.fullmatch(r"[1-9][0-9]*", release):
                raise ValueError(f"{values['environment']} serves a release: set LYRIC_RELEASE to its number "
                                 f"(got {release!r}, {provenance['release']})")
            values["release"] = int(release)
        return cls(**values, provenance=provenance)

    @property
    def frozen(self) -> bool:
        """Whether this environment serves a frozen release rather than teaching the model."""
        return self.environment in FROZEN_ENVIRONMENTS

    def release_database(self, version: int) -> str:
        """The database a release of this line is kept in."""
        return f"{self.database}_model_v{int(version)}"

    @property
    def registry_database(self) -> str:
        """The database recording every release of this line."""
        return f"{self.database}_model_registry"

    def database_for(self, store: str) -> str:
        """The database a store is kept in. Development keeps every store in its one database; staging and
        production keep runtime, user context and learning in `<database>_<environment>_<store>`, and serve the
        model from their release."""
        if store not in STORES:
            raise StoreRoutingError(f"{store!r} is not a store; the stores are {', '.join(STORES)}")
        if not self.frozen:
            return self.database
        if store == "model":
            return self.release_database(self.release)
        return f"{self.database}_{self.environment}_{store}"

    def databases(self) -> Dict[str, str]:
        """store -> database, for every store."""
        return {store: self.database_for(store) for store in STORES}

    def describe(self) -> Dict[str, Any]:
        """Observable identity of the connection. Never includes the password."""
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "environment": self.environment,
            "release": self.release,
            "databases": self.databases(),
            "user": self.user,
            "configuration_source": dict(self.provenance),
        }

    def __repr__(self) -> str:
        return (f"PostgresConfig(host={self.host!r}, port={self.port}, "
                f"database={self.database!r}, environment={self.environment!r}, release={self.release!r}, "
                f"user={self.user!r}, password=<redacted>)")
