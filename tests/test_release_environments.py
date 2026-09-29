"""Environments, releases and the frozen model: the rules, without a database.

The model is taught in development and served, strictly frozen, from a numbered release in staging and
production. What is pinned here:

  * which settings name an environment and its release, and which are refused;
  * which database each store of each environment is, named from the development database, so a sandbox line
    never reaches the main line;
  * what a statement does (read, write, create), which decides what a frozen release does with it;
  * what a creation statement needs a release to have already;
  * where a per-owner row may be written, the learning store included.
"""
import pytest

from core.database.postgres_config import (
    PostgresConfig, StoreRoutingError, schema_requirements, statement_kind, store_for_statement, tables_of)


def resolve(**env):
    return PostgresConfig.resolve(env={"POSTGRES_DATABASE": "torinai_dev", **env}, env_files=[])


def test_development_is_the_default_and_serves_no_release():
    config = resolve()
    assert config.environment == "development" and config.release is None and not config.frozen
    assert set(config.databases().values()) == {"torinai_dev"}


def test_production_names_every_database_from_the_development_database():
    config = resolve(TORINAI_ENVIRONMENT="production", TORINAI_RELEASE="3")
    assert config.frozen and config.release == 3
    assert config.databases() == {
        "runtime": "torinai_dev_production_runtime",
        "model": "torinai_dev_model_v3",
        "user_context": "torinai_dev_production_user_context",
        "learning": "torinai_dev_production_learning",
    }
    assert config.registry_database == "torinai_dev_model_registry"


def test_staging_serves_the_same_release_databases_as_production_names_them():
    staging = resolve(TORINAI_ENVIRONMENT="staging", TORINAI_RELEASE="3")
    assert staging.database_for("model") == "torinai_dev_model_v3"
    assert staging.database_for("runtime") == "torinai_dev_staging_runtime"


@pytest.mark.parametrize("env, says", [
    ({"TORINAI_ENVIRONMENT": "staging"}, "serves a release"),
    ({"TORINAI_ENVIRONMENT": "production", "TORINAI_RELEASE": "0"}, "serves a release"),
    ({"TORINAI_ENVIRONMENT": "production", "TORINAI_RELEASE": "latest"}, "serves a release"),
    ({"TORINAI_RELEASE": "2"}, "development serves none"),
    ({"TORINAI_ENVIRONMENT": "world"}, "not an environment"),
    ({"TORINAI_COPY": "world"}, "was replaced by TORINAI_ENVIRONMENT"),
])
def test_settings_that_cannot_be_served_are_refused(env, says):
    with pytest.raises(ValueError, match=says):
        resolve(**env)


@pytest.mark.parametrize("statement, kind", [
    ("SELECT * FROM memory_hot WHERE memory_id = $1", "read"),
    ("SELECT pg_advisory_xact_lock(hashtext($1))", "read"),
    ("SELECT claim FROM unified.beliefs WHERE claim = 'drop table x; update t set y'", "read"),
    ("SELECT EXTRACT(EPOCH FROM (NOW() - last_updated)) FROM unified.beliefs", "read"),
    ("UPDATE memory_hot SET access_count = access_count + 1 WHERE memory_id = $1", "write"),
    ("UPDATE unified.beliefs b SET x = 1 FROM y WHERE b.id = y.id", "write"),
    ("INSERT INTO unified.beliefs AS b (a) VALUES ($1) ON CONFLICT (belief_id) DO UPDATE SET a = 1", "write"),
    ("WITH cleared AS (UPDATE unified.concepts SET name_embedding = NULL RETURNING 1) "
     "SELECT count(*) FROM cleared", "write"),
    ("DELETE FROM memory_hot WHERE created_at < $1 RETURNING memory_id", "write"),
    ("select * from unified.task_queue for update skip locked", "write"),
    ("SELECT nextval('unified.x_seq')", "write"),
    ("TRUNCATE unified.sense_taxonomy", "write"),
    ("CREATE TABLE IF NOT EXISTS unified.learned_rules (rule_id VARCHAR PRIMARY KEY)", "schema"),
    ("  -- a comment\n ALTER TABLE unified.x ADD COLUMN IF NOT EXISTS y INT", "schema"),
])
def test_what_a_statement_does(statement, kind):
    assert statement_kind(statement) == kind


def test_creation_is_checked_by_what_it_needs_the_release_to_have():
    needs = schema_requirements(
        "ALTER TABLE unified.concepts ADD COLUMN IF NOT EXISTS a NUMERIC(10,2), "
        "ADD COLUMN IF NOT EXISTS b vector(384)")
    assert [(n.kind, n.table, n.name, n.present) for n in needs] == [
        ("column", "concepts", "a", True), ("column", "concepts", "b", True)]
    (index,) = schema_requirements("CREATE UNIQUE INDEX IF NOT EXISTS r_idx ON unified.learned_rules (a, b)")
    assert (index.kind, index.schema, index.table, index.name) == ("index", "unified", "learned_rules", "r_idx")
    (gone,) = schema_requirements("DROP INDEX IF EXISTS unified.knowledge_updates_unconsumed_idx")
    assert gone.kind == "index" and not gone.present
    (table,) = schema_requirements("CREATE TABLE IF NOT EXISTS memory_hot (id int)", "memory_hot")
    assert (table.schema, table.table) == ("memory_hot", "memory_hot")


@pytest.mark.parametrize("statement", [
    "ALTER TABLE unified.x RENAME COLUMN a TO b",
    "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ select 1 $$ LANGUAGE sql",
    "DROP TABLE unified.concepts",
])
def test_a_creation_that_cannot_be_checked_is_not_guessed(statement):
    assert schema_requirements(statement) is None


def test_the_substrates_own_rows_may_be_written_to_the_learning_store_and_no_other_table_may():
    assert store_for_statement("INSERT INTO memory_hot (memory_id) VALUES ($1)", search_schema="memory_hot",
                               store="learning") == "learning"
    assert store_for_statement("INSERT INTO unified.known_unknowns (unknown_id) VALUES ($1)",
                               store="learning") == "learning"
    with pytest.raises(StoreRoutingError):
        # an intent's content: the substrate's own is runtime, never the learning store
        store_for_statement("INSERT INTO unified.scoped_intents (intent_id) VALUES ($1)", store="learning")
    with pytest.raises(StoreRoutingError):
        store_for_statement("INSERT INTO unified.beliefs (belief_id) VALUES ($1)", store="learning")


def test_each_environment_database_holds_only_its_stores_tables():
    assert tables_of("learning") == {"memory_hot.memory_hot", "memory_hot.archive_log", "memory_cold.memory_cold",
                                     "unified.memory_media", "unified.known_unknowns",
                                     "unified.experience_pool", "unified.perceptions",
                                     "unified.reasoning_arg_claims", "unified.reasoning_arguments",
                                     "unified.reasoning_arg_fallacies", "unified.reasoning_temporal_propositions",
                                     "unified.reasoning_temporal_causal_links", "unified.hypotheses",
                                     "unified.experiments", "unified.evidence"}
    assert "unified.beliefs" in tables_of("model") and "unified.beliefs" not in tables_of("runtime")
    assert "unified.release_memory_usage" in tables_of("runtime")
    assert "unified.scoped_intents" in tables_of("runtime") and "unified.scoped_intents" in tables_of("user_context")
