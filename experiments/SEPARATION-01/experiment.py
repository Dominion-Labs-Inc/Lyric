#!/usr/bin/env python3
"""SEPARATION-01 — staging serves a frozen release, and keeps its runtime, the model and each person's context apart.

The model is taught in development (the sandbox, `lyric_dev`), cut into release 1 and staged. This process is
staging serving release 1. Where every row landed is read over separate connections to each database, never
through the database manager under test.

  A  RELEASE   the sandbox's model is cut into release 1 and staged: registered, read-only, intact, holding no
               person's memory
  B  STAGING   this process is staging serving release 1: one pool per store, each reaching its own database;
               the release was checked before serving; the tools that reach its own databases are not carried
  C  BOOT      the substrate starts; no statement refused, none reaching a database without its table
  D  MODEL     the lesson is in the release: patterns, the model's facts, beliefs, ledger; nothing of it in user
               context or the learning store
  E  PEOPLE    two people tell it something and leave a memory: in user context, in neither the release nor the
               learning store; the substrate's own new memory goes to the learning store, not the release
  F  RECALL    each person finds their memory and the release's, never the other person's; the substrate's own
               search finds the release's and neither person's, nor what it remembered while serving
  G  REASON    an answer for a person chains their context; for the other person and for the substrate, no answer
  H  RESEARCH  research topics come from the release and carry no person's context
  I  RUNTIME   runtime holds the running records and no memory
  J  UNTOUCHED nothing refused in the whole run, nothing the frozen release refused; the release is still what was
               cut; development received nothing from staging; the main line is untouched

Run: ./venv_lyric/bin/python3 experiments/SEPARATION-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

os.environ["LYRIC_ENVIRONMENT"] = "staging"
os.environ["LYRIC_RELEASE"] = "1"
os.environ["POSTGRES_DATABASE"] = "lyric_dev"
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

BASE = "lyric_dev"
STAGING = {"runtime": f"{BASE}_staging_runtime", "model": f"{BASE}_model_v1",
           "user_context": f"{BASE}_staging_user_context", "learning": f"{BASE}_staging_learning"}
ALICE, BOB = "user:alice:separation01", "user:bob:separation01"
MARK = "zephyrine"          # a word in every memory this run writes, so recall can be asked about it
PATTERN = '["language_pattern"]'

EV = RunRecord(
    "SEPARATION-01",
    claim=("Staging serves a frozen release of the model taught in development, and keeps its runtime, the model "
           "and each person's context in separate databases: what was taught is in the release, what a person "
           "tells it lands in that person's context, what the substrate remembers while serving waits in the "
           "learning store, and no search, answer or research done for one owner reaches another's."),
    hypothesis=("A statement refused or sent to a database without its table; a write the frozen release refused; "
                "a lesson row in user context or the learning store; a person's fact or memory in the release or "
                "the learning store; the substrate's new memory in the release or read back while serving; a "
                "search or answer for one person reaching the other's context; a research topic carrying a "
                "person's context; memory in runtime; a changed release; or any row written to development by "
                "staging or to the main line would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class RoutingWatch(logging.Handler):
    """Every warning or error that says a statement could not be placed, or reached a database without its table."""

    SIGNS = ("no store holds", "name the store", "touches no table", "one statement touches",
             "belong to the tools", "StoreRoutingError", "does not exist", "UndefinedTable",
             "ModelFrozenError", "ReleaseMismatchError", "read-only transaction")

    def __init__(self):
        super().__init__(logging.WARNING)
        self.hits = []

    def emit(self, record):
        text = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            text += f" {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
        if any(sign in text for sign in self.SIGNS):
            self.hits.append(f"{record.name}: {text[:220]}")


async def connect(database: str):
    import asyncpg
    return await asyncpg.connect(host="localhost", port=5433, user="stefan", database=database)


async def rows_in(database: str) -> dict:
    """Rows per table in one database, over its own connection."""
    c = await connect(database)
    try:
        out = {}
        for t in await c.fetch(
                "select table_schema s, table_name n from information_schema.tables "
                "where table_schema in ('unified','memory_hot','memory_cold') and table_type='BASE TABLE'"):
            n = await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
            if n:
                out[f"{t['s']}.{t['n']}"] = n
        return out
    finally:
        await c.close()


async def fetch(database: str, sql: str, *args):
    c = await connect(database)
    try:
        return await c.fetch(sql, *args)
    finally:
        await c.close()


async def main_line() -> tuple:
    rows = sum((await rows_in("lyric_db")).values())
    c = await connect("postgres")
    try:
        releases = sorted(r["datname"] for r in await c.fetch(
            "select datname from pg_database where datname ~ '^lyric_db_model_'"))
    finally:
        await c.close()
    return rows, releases


async def main() -> int:
    main_before = await main_line()
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    say_line(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        say_line("the sandbox could not be emptied; not running")
        return 1

    say_line("== A. The release ==")
    develop = subprocess.run([sys.executable, str(ROOT / "experiments" / "_develop.py"), "--mark", MARK],
                             capture_output=True, text=True,
                             env={k: v for k, v in os.environ.items()
                                  if k not in ("LYRIC_ENVIRONMENT", "LYRIC_RELEASE")})
    if develop.returncode != 0:
        say_line(f"development phase failed:\n{develop.stderr[-3000:]}")
        return 1
    taught = json.loads(develop.stdout.strip().splitlines()[-1])
    say_line(f"    taught in development: patterns {taught['patterns']}, facts {taught['facts']}")
    from core.database import releases
    from core.database.postgres_config import PostgresConfig
    development = PostgresConfig.resolve(env={"POSTGRES_DATABASE": BASE, "POSTGRES_PORT": "5433",
                                              "POSTGRES_USER": "stefan"}, env_files=[])
    cut = await releases.cut(development, notes="SEPARATION-01")
    staged = await releases.stage(development, cut["version"])
    report = await releases.verify(development, 1)
    say_line(f"    cut release {cut['version']}: {cut['rows']} rows; staged: {staged['databases']}")
    check("release 1 is cut from development and staged", cut["version"] == 1 and report["status"] == "staging",
          f"{report['status']}")
    check("it is read-only and intact", report["intact"], f"{report['problems']}")
    people_in_release = await fetch(STAGING["model"], "select count(*) n from memory_hot.memory_hot "
                                                      "where not (user_id is null or user_id in ('', '__substrate__'))")
    context_tables = await fetch(STAGING["model"], "select count(*) n from information_schema.tables "
                                                   "where table_name in ('scoped_concept_relations', "
                                                   "'scoped_beliefs', 'user_beliefs')")
    check("it holds no person's memory and no person's context table",
          people_in_release[0]["n"] == 0 and context_tables[0]["n"] == 0,
          f"{people_in_release[0]['n']} people's memories, {context_tables[0]['n']} context tables")
    development_after_cut = await rows_in(BASE)

    say_line("\n== B. Staging ==")
    watch = RoutingWatch()
    logging.getLogger().addHandler(watch)
    from core.database import get_database_manager
    from core.database.postgres_config import StoreRoutingError
    db = get_database_manager()
    # Every refusal, counted where it is raised: a component that catches one and logs it quietly (or not at
    # all) would never reach the log watch.
    refusals = watch.refusals = []
    for name in ("_route", "_pool_for"):
        original = getattr(db, name)

        def counted(*args, _original=original, _name=name, **kwargs):
            try:
                return _original(*args, **kwargs)
            except StoreRoutingError as error:
                refusals.append(f"{_name}: {error}")
                raise
        setattr(db, name, counted)
    await db.initialize()
    check("this process is staging serving release 1", db.environment == "staging" and db.release == 1,
          f"{db.environment}, release {db.release}")
    check("it checked its release before serving", bool(db.release_verified) and db.release_verified["intact"],
          f"{db.release_verified and db.release_verified['database']}")
    check("it holds one pool per store, each for its own database",
          sorted(db._pools) == sorted(STAGING.values()), f"{sorted(db._pools)}")
    check("each pool reaches the database it is for", await db.assert_database_identity(BASE) == BASE)
    from core.tools.tool_registry import get_tool_registry
    registry = get_tool_registry()
    carried = set(registry.tools) | set(registry.tool_factories)
    reaching = {"mysql_query", "mysql_table_info", "mysql_backup", "mysql_restore", "connection_pool_manager",
                "transaction_wrapper", "migration_runner", "row_level_access_control", "safe_query_executor",
                "check_mysql_health", "query_metrics", "create_alert"}
    check("the tools that reach its own databases are not carried", not (reaching & carried),
          f"{len(carried)} tools; reaching its databases: {sorted(reaching & carried)}")

    say_line("\n== C. Boot ==")
    boot_log = io.StringIO()
    with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
        from core.main import get_system
        system = get_system()
        await system.start()
    coordinator = system.autonomous_coordinator
    check("the substrate is running", coordinator is not None and system.running)
    await asyncio.sleep(20)
    check("no statement was refused, reached a database without its table, or tried to change the release "
          "during boot", not watch.hits and not watch.refusals and not db.frozen_refusals,
          f"logged {len(watch.hits)}: {watch.hits[:3]}; raised {len(watch.refusals)}: {watch.refusals[:3]}; "
          f"frozen {db.frozen_refusals[:5]}")
    try:
        return await _serve(db, coordinator, watch, main_before, development, development_after_cut)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()
        logging.getLogger().removeHandler(watch)


async def _serve(db, coordinator, watch, main_before, development, development_after_cut) -> int:
    from core.memory import Origin
    from core.database import releases
    from core.learning import get_learning_authority
    from core.memory import get_memory_agent
    from core.reasoning.concept_graph_reasoning import answer_over_graph
    from core.reasoning.relation_algebra import TRUE
    from core.semantics.relation_types import SemanticRelation
    learning = get_learning_authority()
    agent = await get_memory_agent()

    say_line("\n== D. The model is the release ==")
    patterns = await fetch(STAGING["model"],
                           f"select count(*) n from memory_hot.memory_hot where tags @> '{PATTERN}'")
    model_facts = await fetch(STAGING["model"], "select c.name from unified.concept_relations cr join "
                              "unified.concepts c on c.concept_id = cr.source_concept_id where c.name = 'robin'")
    beliefs = await fetch(STAGING["model"], "select count(*) n from unified.beliefs where domain = 'english'")
    ledgered = await fetch(STAGING["model"], "select count(*) n from unified.knowledge_updates "
                                             "where subject_kind = 'language_pattern'")
    check("the lesson's patterns are memories in the release", patterns[0]["n"] == 9, f"{patterns[0]['n']}")
    check("its facts about the world are in the release", len(model_facts) == 2, f"{len(model_facts)} robin facts")
    check("its beliefs and ledger entries are in the release", beliefs[0]["n"] >= 9 and ledgered[0]["n"] == 9,
          f"{beliefs[0]['n']} english beliefs, {ledgered[0]['n']} pattern updates")
    elsewhere = {store: await rows_in(STAGING[store]) for store in ("user_context", "learning")}
    check("nothing of the lesson is in user context or the learning store", not any(elsewhere.values()),
          f"{elsewhere}")

    say_line("\n== E. Two people, and the substrate itself ==")
    for person, subject in ((ALICE, "quibnar"), (BOB, "vorplex")):
        adm = await learning.learn_fact(subject, "isa", "gadget", domain="separation_01", quality=0.9,
                                        actor=person)
        say_line(f"    {person} told it: a {subject} is a gadget -> admitted={getattr(adm, 'admitted', adm)}")
    stored = {}
    for owner, text in ((ALICE, f"Alice's note: the {MARK} pump in bay 4 is broken."),
                        (BOB, f"Bob's note: the {MARK} valve in bay 9 leaks."),
                        (None, f"The substrate's note while serving: {MARK} came up again today.")):
        ok, memory_id = await agent.store_memory(content=text, origin=Origin.of(owner, "SEPARATION-01"),
                                                 tags=["separation_01"], importance_score=0.9)
        stored[owner] = memory_id
        say_line(f"    stored for {owner or 'the substrate'}: {ok} {memory_id}")
    scoped = await fetch(STAGING["user_context"],
                         "select scope_actor, count(*) n from unified.scoped_concept_relations group by 1")
    by_actor = {r["scope_actor"]: r["n"] for r in scoped}
    check("each person's fact is in user context", by_actor.get(ALICE) and by_actor.get(BOB), f"{by_actor}")
    in_release = await fetch(STAGING["model"], "select name from unified.concepts where name = any($1)",
                             ["quibnar", "vorplex"])
    check("neither person's fact is in the release", not in_release, f"{[r['name'] for r in in_release]}")
    placed = {}
    for store in ("model", "user_context", "learning"):
        for r in await fetch(STAGING[store], "select memory_id, user_id from memory_hot.memory_hot "
                                             "where content like $1", f"%{MARK}%"):
            placed.setdefault(r["memory_id"], []).append(store)
    check("each person's memory is in user context, and only there",
          placed.get(stored[ALICE]) == ["user_context"] and placed.get(stored[BOB]) == ["user_context"],
          f"{ {k: v for k, v in placed.items() if k in (stored[ALICE], stored[BOB])} }")
    check("the substrate's new memory is in the learning store, not the release",
          placed.get(stored[None]) == ["learning"], f"{placed.get(stored[None])}")

    say_line("\n== F. Recall, for each owner ==")
    storage = agent.postgres_storage
    released = {r["memory_id"] for r in await fetch(
        STAGING["model"], "select memory_id from memory_hot.memory_hot where content like $1", f"%{MARK}%")}
    seen = {}
    for label, actor in (("Alice", ALICE), ("Bob", BOB), ("the substrate", None)):
        found = await storage.search_by_content(MARK, actor=actor, limit=20)
        seen[label] = {m.memory_id for m in found}
        say_line(f"    {label}: {len(found)} memories")
    check("the release holds the memory development made", len(released) == 1, f"{released}")
    check("Alice finds her memory and the release's, not Bob's",
          stored[ALICE] in seen["Alice"] and released <= seen["Alice"] and stored[BOB] not in seen["Alice"])
    check("Bob finds his memory and the release's, not Alice's",
          stored[BOB] in seen["Bob"] and released <= seen["Bob"] and stored[ALICE] not in seen["Bob"])
    check("the substrate's own search finds the release's memory, and neither a person's nor what it "
          "remembered while serving", seen["the substrate"] == released, f"{seen['the substrate']}")

    say_line("\n== G. An answer, for each owner ==")
    verdicts = {}
    for label, actor in (("Alice", ALICE), ("Bob", BOB), ("the substrate", None)):
        answer = await answer_over_graph(db, "quibnar", SemanticRelation.ISA, "gadget", actor=actor)
        verdicts[label] = answer.verdict
    say_line(f"    is a quibnar a gadget? {verdicts}")
    check("for Alice, her context answers it", verdicts["Alice"] == TRUE)
    check("for Bob and for the substrate, it does not",
          verdicts["Bob"] != TRUE and verdicts["the substrate"] != TRUE)

    say_line("\n== H. Research ==")
    topics = await coordinator._thinnest_knowledge_topics()
    say_line(f"    topics: {topics}")
    check("research topics come from the release and carry no person's context",
          not any(w in " ".join(topics) for w in ("quibnar", "vorplex", "bay 4", "bay 9", MARK)),
          f"{len(topics)} topics")

    say_line("\n== I. Runtime ==")
    rt = await rows_in(STAGING["runtime"])
    say_line(f"    rows: {rt}")
    memory_tables = await fetch(STAGING["runtime"],
                                "select count(*) n from information_schema.tables "
                                "where table_schema in ('memory_hot','memory_cold') and table_type='BASE TABLE'")
    check("runtime holds the substrate's running records", sum(rt.values()) > 0, f"{len(rt)} tables")
    check("and no memory at all", memory_tables[0]["n"] == 0 and not any(t.startswith("memory_") for t in rt))

    say_line("\n== J. Untouched ==")
    check("no statement was refused or reached a database without its table during the whole run",
          not watch.hits and not watch.refusals,
          f"logged {len(watch.hits)}: {watch.hits[:5]}; raised {len(watch.refusals)}: {watch.refusals[:5]}")
    check("nothing tried to change the frozen release", not db.frozen_refusals, f"{db.frozen_refusals[:8]}")
    recorded = await fetch(STAGING["runtime"],
                           "select component, description as message from unified.failure_events order by occurred_at")
    for r in recorded:
        say_line(f"    recorded error: {r['component']}: {r['message'][:160]}")
    structural = [r for r in recorded if any(sign in r["message"] for sign in RoutingWatch.SIGNS + (
        "no partition",))]
    check("none of the errors the substrate recorded is a missing table, a refusal or a frozen write",
          not structural, f"{len(recorded)} recorded; structural: {[r['message'][:100] for r in structural]}")
    after = await releases.verify(development, 1)
    check("the release is still exactly what was cut", after["intact"], f"{after['problems']}")
    check("development received nothing from staging", await rows_in(BASE) == development_after_cut)
    main_after = await main_line()
    check("the main line is untouched", main_after == main_before,
          f"{main_before} before, {main_after} after (rows, releases)")
    for store, database in STAGING.items():
        EV.metric(f"rows_{store}", sum((await rows_in(database)).values()), unit="rows")

    path = EV.write()
    transcript = Path(path).with_suffix(".txt")
    transcript.write_text("\n".join(TRANSCRIPT) + "\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {path.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
