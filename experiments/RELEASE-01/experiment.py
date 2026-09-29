#!/usr/bin/env python3
"""RELEASE-01 — the model is released, served frozen, and replaced only by a newer release.

On the sandbox line (`torinai_dev`). This process is development; each staging or production process is started
on its own (`serve.py`), because a process is one environment for its whole life.

  A  CUT       release 1 is cut from development's model: a candidate, read-only in the database, its content,
               schema and code recorded, no person's memory
  B  STAGED    nothing reaches production unstaged; staging will not serve a candidate; it serves a staged release
  C  TAMPER    a changed release is found out, and staging will not serve it; put back, it serves again
  D  CODE      a release registered as cut with other code is not served
  E  SERVED    promoted, production serves it: boot, a person, the substrate's own memory, recall, maintenance and
               idle, with nothing refused; the person's context in user context; its own memory in the learning
               store; recalls counted in runtime; its own learning and belief changes refused, beliefs unmoved
  F  FROZEN    after serving, the release is exactly what was cut
  G  TAKE      development takes what production kept: its memory, and its recalls as access counts; taking again
               takes nothing
  H  NEXT      release 2 carries what was taken; staged and promoted, it retires release 1, which stays intact
  I  ROLLBACK  production goes back to release 1 and serves it; release 2 is retired and intact
  J  MAIN      the main line is untouched

Run: ./venv_torin/bin/python3 experiments/RELEASE-01/experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.pop("TORINAI_RELEASE", None)
os.environ["TORINAI_ENVIRONMENT"] = "development"
os.environ["POSTGRES_DATABASE"] = "torinai_dev"
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402

BASE = "torinai_dev"
MARK = "quillmoss"          # a word in every memory this run writes
IDLE = 60.0

EV = RunRecord(
    "RELEASE-01",
    claim=("A release of the model is cut from development, checked before it is served, served by production "
           "without ever changing, and replaced only by a newer release or by rolling back; what production "
           "keeps while serving reaches development, and through it the next release."),
    hypothesis=("A release served unstaged, tampered or cut with other code; any refusal while production "
                "serves; a person's context outside user context; the substrate's own memory in the release; a "
                "recall written on the release; own learning or a belief change let through; a release changed "
                "by serving; a take that loses or duplicates what production kept; a next release without it; "
                "a rollback that does not serve; or any write to the main line would each show here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def connect(database: str):
    import asyncpg
    return await asyncpg.connect(host="localhost", port=5433, user="stefan", database=database)


async def fetch(database: str, sql: str, *args):
    c = await connect(database)
    try:
        return await c.fetch(sql, *args)
    finally:
        await c.close()


def run(script: str, *args: str, environment: str = "development", release: int = 0) -> dict:
    """One process of the given environment; the JSON object that ends its output."""
    env = {k: v for k, v in os.environ.items() if k not in ("TORINAI_ENVIRONMENT", "TORINAI_RELEASE")}
    env["TORINAI_ENVIRONMENT"] = environment
    if release:
        env["TORINAI_RELEASE"] = str(release)
    done = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, env=env)
    lines = done.stdout.strip().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("{")]
    for start in reversed(starts):
        try:
            return json.loads("\n".join(lines[start:]))
        except ValueError:
            continue
    return {"failed": done.returncode, "stderr": done.stderr[-2000:], "stdout": done.stdout[-1000:]}


def serve(environment: str, release: int, *args: str) -> dict:
    return run(str(HERE / "serve.py"), *args, environment=environment, release=release)


async def main_line() -> tuple:
    c = await connect("torinai_db")
    try:
        rows = 0
        for t in await c.fetch("select table_schema s, table_name n from information_schema.tables "
                               "where table_schema in ('unified','memory_hot','memory_cold') "
                               "and table_type = 'BASE TABLE'"):
            rows += await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
    finally:
        await c.close()
    c = await connect("postgres")
    try:
        lines = sorted(r["datname"] for r in await c.fetch(
            "select datname from pg_database where datname ~ '^torinai_db_model_'"))
    finally:
        await c.close()
    return rows, lines


async def main() -> int:
    from core.database import releases
    from core.database.postgres_config import PostgresConfig
    development = PostgresConfig.resolve()
    assert development.environment == "development" and development.database == BASE
    main_before = await main_line()
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    say_line(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        say_line("the sandbox could not be emptied; not running")
        return 1
    taught = run(str(ROOT / "experiments" / "_develop.py"), "--mark", MARK)
    if "failed" in taught:
        say_line(f"development phase failed: {taught}")
        return 1
    say_line(f"    taught in development: patterns {taught['patterns']}, facts {taught['facts']}")

    say_line("\n== A. Cut ==")
    cut = await releases.cut(development, notes="RELEASE-01")
    registered = (await releases.list_releases(development))[0]
    say_line(f"    release {cut['version']}: {cut['rows']} rows, content {cut['content_checksum'][:12]}, "
             f"code {cut['code']['sha256'][:12]} ({cut['code']['files']} files, commit "
             f"{str(cut['code']['commit'])[:10]}, {cut['code']['uncommitted']} uncommitted)")
    check("release 1 is registered as a candidate", cut["version"] == 1 and registered["status"] == "candidate")
    c = await connect(cut["database"])
    try:
        read_only = await c.fetchval("SHOW default_transaction_read_only")
        try:
            await c.execute("DELETE FROM unified.domains WHERE false")
            direct = "accepted"
        except Exception as error:
            direct = type(error).__name__
        people = await c.fetchval("select count(*) from memory_hot.memory_hot "
                                  "where not (user_id is null or user_id in ('', '__substrate__'))")
    finally:
        await c.close()
    check("it is read-only in the database itself", read_only == "on" and direct == "ReadOnlySQLTransactionError",
          f"default_transaction_read_only={read_only}; a direct write: {direct}")
    check("its content, schema and code are recorded", all(registered[k] for k in (
        "content_checksum", "schema_checksum", "code_identity", "row_counts")), f"{registered['code_files']} files")
    check("it holds no person's memory", people == 0, f"{people}")

    say_line("\n== B. Staged ==")
    try:
        await releases.promote(development, 1)
        unstaged = "promoted"
    except releases.ReleaseError as error:
        unstaged = str(error)
    check("a candidate cannot be promoted", "promoted from staging" in unstaged, unstaged[:120])
    refused = serve("staging", 1, "--start-only")
    check("staging will not serve a candidate", refused.get("started") is False
          and "candidate" in refused.get("refused", ""), refused.get("refused", str(refused))[:160])
    await releases.stage(development, 1)
    started = serve("staging", 1, "--start-only")
    check("staging serves the staged release", started.get("started") is True, f"{started}")

    say_line("\n== C. Tamper ==")
    c = await connect(cut["database"])
    try:
        columns = [r["column_name"] for r in await c.fetch(
            "select column_name from information_schema.columns where table_schema = 'unified' "
            "and table_name = 'domain_volatility' order by ordinal_position")]
        async with c.transaction():
            await c.execute("SET TRANSACTION READ WRITE")
            await c.execute(f"INSERT INTO unified.domain_volatility ({', '.join(columns)}) "
                            f"SELECT 'tamper_probe', {', '.join(columns[1:])} FROM unified.domain_volatility LIMIT 1")
    finally:
        await c.close()
    tampered = await releases.verify(development, 1)
    check("a changed release is found out", not tampered["intact"], f"{tampered['problems']}")
    refused = serve("staging", 1, "--start-only")
    check("staging will not serve it", refused.get("started") is False
          and "checksum" in refused.get("refused", ""), refused.get("refused", str(refused))[:160])
    c = await connect(cut["database"])
    try:
        async with c.transaction():
            await c.execute("SET TRANSACTION READ WRITE")
            await c.execute("DELETE FROM unified.domain_volatility WHERE domain = 'tamper_probe'")
    finally:
        await c.close()
    restored = await releases.verify(development, 1)
    started = serve("staging", 1, "--start-only")
    check("put back, it is intact and served again", restored["intact"] and started.get("started") is True,
          f"{restored['problems']}")

    say_line("\n== D. Code ==")
    reg = await releases.registry(development)
    try:
        await reg.execute("UPDATE releases SET code_identity = 'other code' WHERE version = 1")
    finally:
        await reg.close()
    refused = serve("staging", 1, "--start-only")
    reg = await releases.registry(development)
    try:
        await reg.execute("UPDATE releases SET code_identity = $1 WHERE version = 1", cut["code"]["sha256"])
    finally:
        await reg.close()
    check("a release cut with other code is not served", refused.get("started") is False
          and "other code" in refused.get("refused", ""), refused.get("refused", str(refused))[:160])

    say_line("\n== E. Served ==")
    await releases.promote(development, 1)
    served = serve("production", 1, "--mark", MARK, "--idle", str(IDLE))
    if "failed" in served:
        say_line(f"production failed to serve: {served}")
    say_line(f"    production served release 1 ({IDLE:.0f}s idle): {json.dumps(served, default=str)[:600]}")
    prod = {s: f"{BASE}_production_{s}" for s in ("runtime", "user_context", "learning")}
    check("production served, with nothing refused: no statement, and no change to the release",
          served.get("routing_refusals") == [] and served.get("frozen_refusals") == [],
          f"routing {served.get('routing_refusals')}; frozen {served.get('frozen_refusals')}")
    check("creation statements were checked against the release, not run", (served.get("schema_checks") or 0) > 0,
          f"{served.get('schema_checks')} checked")
    scoped = await fetch(prod["user_context"], "select count(*) n from unified.scoped_concept_relations "
                                               "where scope_actor = $1", "user:alice:release01")
    alice_memory = await fetch(prod["user_context"], "select count(*) n from memory_hot.memory_hot "
                                                     "where memory_id = $1", served.get("alice_memory") or "")
    check("the person's fact and memory are in user context, and her context answers her",
          scoped[0]["n"] == 1 and alice_memory[0]["n"] == 1 and str(served.get("alice_answer")).lower() == "true",
          f"{scoped[0]['n']} fact, {alice_memory[0]['n']} memory, answer {served.get('alice_answer')}")
    own_in_learning = await fetch(prod["learning"], "select count(*) n from memory_hot.memory_hot "
                                                    "where memory_id = $1", served.get("own_memory") or "")
    own_in_release = await fetch(cut["database"], "select count(*) n from memory_hot.memory_hot "
                                                  "where content like $1", f"%while serving: {MARK}%")
    check("its own memory is in the learning store, not the release",
          own_in_learning[0]["n"] == 1 and own_in_release[0]["n"] == 0)
    usage = await fetch(prod["runtime"], "select memory_id, access_count from unified.release_memory_usage "
                                         "where release = 1 and taken_at is null")
    counted = {r["memory_id"]: r["access_count"] for r in usage}
    recalled = served.get("recalled") or []
    check("recalling the release's memory is counted in runtime", recalled and all(
        counted.get(m, 0) >= 1 for m in recalled), f"{counted}")
    frozen_after = served.get("frozen_refusals_after") or []
    check("its own learning is refused, with the reason",
          served.get("own_learning_admitted") is False
          and any("frozen" in r for r in served.get("own_learning_refusals") or []),
          f"{(served.get('own_learning_refusals') or [''])[0][:120]}")
    check("a belief it would form or move is refused, and no belief moved",
          served.get("belief_refused") and served.get("belief_move_refused") and served.get("beliefs_unchanged"),
          f"{served.get('beliefs_held')} beliefs held; refusals counted {len(frozen_after)}")
    check("maintenance ran on people's memory only", served.get("decay_ran") is True, f"cleaned {served.get('cleaned')}")

    say_line("\n== F. Frozen ==")
    after = await releases.verify(development, 1)
    check("after serving, release 1 is exactly what was cut", after["intact"], f"{after['problems']}")

    say_line("\n== G. Take ==")
    kept = (await fetch(prod["learning"], "select (select count(*) from memory_hot.memory_hot) + "
                                          "(select count(*) from memory_cold.memory_cold) n"))[0]["n"]
    access_before = {r["memory_id"]: r["access_count"] for r in await fetch(
        BASE, "select memory_id, access_count from memory_hot.memory_hot where memory_id = any($1::text[])",
        recalled)}
    taken = run(str(ROOT / "scripts" / "release.py"), "take", "production")
    say_line(f"    production kept {kept} memor{'y' if kept == 1 else 'ies'}; taken: {taken}")
    # The memory agent may merge a taken memory into one development already holds: what is looked for is
    # what production remembered, wherever development keeps it.
    serving_note = f"%while serving: {MARK} was asked about today%"
    held = await fetch(BASE, "select memory_id from memory_hot.memory_hot where content like $1", serving_note)
    access_after = {r["memory_id"]: r["access_count"] for r in await fetch(
        BASE, "select memory_id, access_count from memory_hot.memory_hot where memory_id = any($1::text[])",
        recalled)}
    check("development takes every memory production kept, through the memory agent",
          kept >= 1 and taken.get("memories") == kept and len(held) == 1, f"{taken}")
    check("and its recalls, as access counts", recalled and taken.get("usage", 0) >= len(recalled) and all(
        access_after.get(m, 0) > access_before.get(m, 0) for m in recalled),
          f"{access_before} -> {access_after}")
    again = run(str(ROOT / "scripts" / "release.py"), "take", "production")
    check("taking again takes nothing", again.get("memories") == 0 and again.get("already") == kept
          and again.get("usage") == 0, f"{again}")

    say_line("\n== H. Next ==")
    second = await releases.cut(development, notes="RELEASE-01, with what production kept")
    carried = await fetch(second["database"], "select count(*) n from memory_hot.memory_hot "
                                              "where content like $1", serving_note)
    check("release 2 carries what production kept", second["version"] == 2 and carried[0]["n"] == 1,
          f"{carried[0]['n']}")
    await releases.stage(development, 2)
    promoted = await releases.promote(development, 2)
    statuses = {r["version"]: r["status"] for r in await releases.list_releases(development)}
    check("promoted, release 2 retires release 1", promoted["replaced"] == 1
          and statuses == {1: "retired", 2: "production"}, f"{statuses}")
    on_two = serve("production", 2, "--start-only")
    on_one = serve("production", 1, "--start-only")
    check("production serves release 2, and no longer release 1", on_two.get("started") is True
          and on_one.get("started") is False, f"{on_one.get('refused', '')[:120]}")

    say_line("\n== I. Rollback ==")
    back = await releases.rollback(development)
    statuses = {r["version"]: r["status"] for r in await releases.list_releases(development)}
    on_one = serve("production", 1, "--start-only")
    check("production goes back to release 1 and serves it", back == {"from": 2, "to": 1, "status": "production"}
          and statuses == {1: "production", 2: "retired"} and on_one.get("started") is True,
          f"{statuses}; {back}; serving release 1: "
          f"{on_one.get('refused') or on_one.get('stderr', '')[-160:] or on_one.get('started')}")
    one, two = await releases.verify(development, 1), await releases.verify(development, 2)
    check("both releases are intact", one["intact"] and two["intact"], f"{one['problems']} {two['problems']}")

    say_line("\n== J. Main ==")
    main_after = await main_line()
    check("the main line is untouched", main_after == main_before,
          f"{main_before} before, {main_after} after (rows, releases)")

    path = EV.write()
    Path(path).with_suffix(".txt").write_text("\n".join(TRANSCRIPT) + "\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {path.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
