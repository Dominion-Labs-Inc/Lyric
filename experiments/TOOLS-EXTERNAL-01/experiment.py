#!/usr/bin/env python3
"""TOOLS-EXTERNAL-01 — no tool is hardcoded to the substrate; the security tools may look at it, when named.

The tools serve people and systems outside the substrate. After the audit of `core/tools`
(docs/research/TOOLS_AUDIT_2026-09-30.md), on the owner's word:

  A  the chaos tools, whose only targets were the substrate's own systems, and the six learning tools that
     drove its own learning machinery, are archived and not registered; the
     testing and validation tools are all still registered; `detect_brute_force` is disabled (kept, not
     registered);
  B  the security tools read the security logs they are told to: an outside log database, or the substrate's own
     (`logs_of="lyric"`, the one kind of tool that may look at the substrate itself, for its own defence). With no
     source named they refuse; an "outside" source that is the substrate's own server is refused. On an outside
     log database they find what is there; the rate limiter counts there; zero-day detection says which checks it
     could not make instead of reporting them clean;
  C  the file and code tools take the folder they work on from the caller, and work on the substrate's own code
     and on a user's alike;
  D  the AgentSO connector tools stay, guarded: AgentSO's folder is last on the import path, and a connector that
     points at the substrate's own database server is refused (the connector here is the one stand-in);
  F  the memory tools are archived; the configuration and environment tools work on a user's project and
     services: they read and write the .env file they are given (never the substrate's own, which holds its
     passwords, and never the substrate's live environment), check a project's requirements against its own
     interpreter, profile and reload the process they are given, and refuse the substrate's own process;
  E  the substrate's stores (main and sandbox) are untouched.

The outside world is a throwaway PostgreSQL server the run starts and removes. The substrate is not started.

    ./venv_lyric/bin/python3 experiments/TOOLS-EXTERNAL-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
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
NONCE = uuid.uuid4().hex[:6]
ADMIN = "outside_admin"
CHAOS = ("create_chaos_experiment", "run_chaos_experiment", "create_chaos_experiment_from_scenario",
         "list_chaos_scenarios", "get_chaos_experiment_status", "rollback_chaos_experiment", "chaos_testing")
TESTING = ("run_pytest", "run_unittest", "check_syntax", "validate_json", "validate_yaml", "validate_xml",
           "validate_schema", "lint_python", "type_check", "benchmark_code", "generate_mock", "test_data_generator",
           "integration_test_runner", "load_test", "run_coverage", "fuzz_testing", "mutation_testing",
           "static_security_analysis", "golden_test_harness")
SECURITY = ("detect_intrusion", "analyze_anomaly", "monitor_logs", "analyze_traffic_pattern", "hunt_threats",
            "detect_zero_day", "check_rate_limit")
PATHED = {"search_files": "directory", "grep_search": "path", "semantic_search": "workspace_path",
          "generate_changelog": "repo_path", "run_coverage": "source_path"}

EV = RunRecord(
    "TOOLS-EXTERNAL-01",
    claim=("No tool is hardcoded to the substrate: the chaos and memory tools are archived, the security tools read the logs "
           "they are told to (an outside log database, or the substrate's own when named), the file and code "
           "tools work on the folder they are given, and the AgentSO connector tools are guarded against the "
           "substrate."),
    hypothesis=("A chaos tool still registered, a testing tool lost, a security tool reading the substrate's logs "
                "unasked or an outside source that is its own server, a made-up or silently skipped finding, a "
                "file tool falling back to the substrate's folder, an unguarded connector, or a write to the "
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


async def main() -> int:
    import asyncpg
    import logging
    logging.disable(logging.WARNING)

    before = {db: await lyric_rows(db) for db in ("lyric_db", "lyric_dev")}
    from core.tools.tool_registry import get_tool_registry
    registry = get_tool_registry()

    say_line("== A. Chaos archived, testing kept, brute force disabled ==")
    still = [n for n in CHAOS if registry.get_tool(n) is not None]
    check("no chaos tool is registered", not still, f"{still}")
    lost = [n for n in TESTING if registry.get_tool(n) is None]
    check("every testing and validation tool is still registered", not lost,
          f"{len(TESTING) - len(lost)}/{len(TESTING)} registered; missing {lost}")
    obsolete = ("profileperformance", "analyzecausalfeedback", "extractlessonslearned", "benchmarkcapability",
                "recommendtraining", "generatehypothesis")
    kept = ("monitordatadrift", "detectpatterns", "visualizelearningprogress", "identifyskillgaps")
    check("the six obsolete learning tools are not registered; the four that work on given data are",
          not [n for n in obsolete if registry.get_tool(n)] and all(registry.get_tool(n) for n in kept),
          f"left: {[n for n in obsolete if registry.get_tool(n)]}; missing: {[n for n in kept if not registry.get_tool(n)]}")
    from core.tools import security_tools
    check("detect_brute_force is disabled: kept in the code, not registered",
          registry.get_tool("detect_brute_force") is None and hasattr(security_tools, "DetectBruteForceTool"))

    world = Path(tempfile.mkdtemp(prefix="toolsexternal01_"))
    port = free_port()
    subprocess.run([str(PG_BIN / "initdb"), "-D", str(world / "pg"), "-U", ADMIN, "-A", "trust"],
                   check=True, capture_output=True)
    subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(world / "pg"), "-l", str(world / "pg.log"), "-w",
                    "-o", f"-p {port} -c listen_addresses=localhost -c unix_socket_directories=''", "start"],
                   check=True, capture_output=True)
    try:
        admin = await asyncpg.connect(host="localhost", port=port, user=ADMIN, database="postgres")
        await admin.execute("CREATE DATABASE siem")
        await admin.close()
        siem = await asyncpg.connect(host="localhost", port=port, user=ADMIN, database="siem")
        # A customer's log database, shaped as the tools read it.
        await siem.execute("""
            CREATE TABLE auth_logs (source_ip text, username text, result text, endpoint text,
                                    timestamp timestamp DEFAULT now());
            CREATE TABLE access_logs (source_ip text, entity_id text, endpoint text, status_code int,
                                      timestamp timestamp DEFAULT now());
            CREATE TABLE network_logs (source_ip text, dest_ip text, dest_port int, protocol text,
                                       bytes_sent bigint DEFAULT 0, bytes_received bigint DEFAULT 0,
                                       timestamp timestamp DEFAULT now());""")
        await siem.executemany("INSERT INTO auth_logs (source_ip, username, result, endpoint) VALUES ($1, $2, $3, $4)",
                               [("203.0.113.9", f"admin{i}", "failed", "/login") for i in range(12)])
        outside = {"logs_of": "outside", "host": "localhost", "port": port, "database": "siem", "user": ADMIN}
        tools = {name: registry.get_tool(name) for name in SECURITY}

        say_line("\n== B. Security tools read the logs they are told to ==")
        missing = [n for n, t in tools.items() if t is None]
        check("the six security tools and the rate limiter are registered", not missing, f"missing {missing}")
        unnamed = {}
        for name, tool in tools.items():
            args = {"identifier": "x"} if name == "check_rate_limit" else \
                   {"entity_id": "x"} if name == "analyze_anomaly" else \
                   {"log_source": "auth"} if name == "monitor_logs" else \
                   {"hunt_type": "ioc", "iocs": ["203.0.113.9"]} if name == "hunt_threats" else {}
            r = await tool.execute(**args)
            unnamed[name] = not r.success and "logs_of is required" in (r.error or "")
        check("with no source named, each refuses", all(unnamed.values()),
              f"{[n for n, ok in unnamed.items() if not ok]}")
        own = await tools["detect_intrusion"].execute(logs_of="outside", host="127.0.0.1", port=5433,
                                                      database="lyric_dev", user="nobody")
        check("an 'outside' source that is the substrate's own server is refused",
              not own.success and "logs_of='lyric'" in (own.error or ""), own.error)
        found = await tools["detect_intrusion"].execute(detection_sensitivity="medium", **outside)
        hits = [d for d in (found.output or {}).get("detections", []) if "203.0.113.9" in str(d)]
        check("on an outside log database, what is there is found",
              found.success and hits, f"{found.error or len(hits)} detection(s) of 203.0.113.9")
        counts = []
        for _ in range(4):
            r = await tools["check_rate_limit"].execute(identifier=f"client-{NONCE}", max_requests=3,
                                                        window_seconds=60, **outside)
            counts.append(r.output["is_allowed"] if r.success else r.error)
        kept = await siem.fetchval("SELECT count(*) FROM rate_limit_events WHERE identifier = $1", f"client-{NONCE}")
        check("the rate limiter counts in the protected system's database",
              counts == [True, True, True, False] and kept == 3, f"{counts}; {kept} counted there")
        zero = await tools["detect_zero_day"].execute(analysis_scope="comprehensive", **outside)
        unchecked = [n["scope"] for n in (zero.output or {}).get("not_checked", [])]
        check("zero-day detection says which checks it could not make, never reports them clean",
              not zero.success and "memory_patterns" in unchecked, f"not checked: {unchecked}")
        mine = await tools["analyze_traffic_pattern"].execute(analysis_type="all", logs_of="lyric")
        check("named, the substrate's own security logs are read", mine.success,
              mine.error or f"{(mine.output or {}).get('total_findings', 'read')}")
        await siem.close()
    finally:
        subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(world / "pg"), "-m", "fast", "-w", "stop"],
                       capture_output=True)
        shutil.rmtree(world, ignore_errors=True)
        say_line("    the throwaway server is stopped and removed")

    say_line("\n== C. File and code tools work where they are told ==")
    optional = [f"{t}.{p}" for t, p in PATHED.items()
                if not next(x for x in registry.get_tool(t).parameters if x.name == p).required]
    check("each takes its folder from the caller, with none assumed", not optional, f"{optional}")
    theirs = Path(tempfile.mkdtemp(prefix="toolsexternal01_user_"))
    (theirs / "notes.txt").write_text(f"marker-{NONCE}\n")
    grep = registry.get_tool("grep_search")
    user_hit = await grep.execute(pattern=f"marker-{NONCE}", path=str(theirs))
    own_hit = await grep.execute(pattern="class MemoryAgent", path=str(ROOT / "core" / "agents"))
    check("it works on a user's folder", user_hit.success and f"marker-{NONCE}" in str(user_hit.output),
          user_hit.error or "found")
    check("and on the substrate's own code, here", own_hit.success and "memory_agent.py" in str(own_hit.output),
          own_hit.error or "found")
    shutil.rmtree(theirs, ignore_errors=True)

    say_line("\n== D. AgentSO connector tools, guarded ==")
    from core.tools import connector_tools
    agentso = str(connector_tools.AGENTSO_PATH)
    first_own = next(i for i, p in enumerate(sys.path) if Path(p or ".").resolve() == ROOT)
    check("AgentSO's folder is after the substrate's own on the import path",
          agentso in sys.path and sys.path.index(agentso) > first_own,
          f"substrate at {first_own}, AgentSO at {sys.path.index(agentso) if agentso in sys.path else None}")
    names = [n for n in list(registry.tool_factories) + list(registry.tools) if n.startswith("virustotal_")]
    check("its connector tools are still registered", names, f"{len(names)} VirusTotal tools")

    class StandIn:
        """The one stand-in: a connector configured with the substrate's own database server."""
        host, port, config = "localhost", 5433, {}

        async def fetch_alerts(self, **_):
            raise AssertionError("ran against the substrate")

    real = connector_tools.get_active_connector
    connector_tools.get_active_connector = lambda: StandIn()
    try:
        guarded = await connector_tools.ConnectorTool("standin", "fetch_alerts", "stand-in", []).execute()
    finally:
        connector_tools.get_active_connector = real
    check("a connector pointing at the substrate's own database server is refused before it runs",
          not guarded.success and "substrate's own database server" in (guarded.error or ""), guarded.error)

    say_line("\n== F. Memory tools gone; configuration and environment tools work for users ==")
    gone = [n for n in ("query_memory", "store_memory") if registry.get_tool(n) is not None]
    check("the memory tools are not registered", not gone, f"{gone}")
    project = Path(tempfile.mkdtemp(prefix="toolsexternal01_project_"))
    env = project / ".env"
    env.write_text("APP_MODE=staging\n")
    get_env, set_env = registry.get_tool("get_environment_variable"), registry.get_tool("set_environment_variable")
    read = await get_env.execute(key="APP_MODE", env_file=str(env))
    check("a variable is read from the project's .env file", read.success and read.output["value"] == "staging",
          read.error or f"{read.output}")
    marker = f"LYRIC_TEST_{NONCE.upper()}"
    wrote = await set_env.execute(key=marker, value="1", env_file=str(env))
    check("and written there, never into the substrate's live environment",
          wrote.success and f"{marker}=1" in env.read_text() and marker not in os.environ, wrote.error or "written")
    own_env = str(ROOT / ".env.postgres")
    refused = [await get_env.execute(key="POSTGRES_PASSWORD", env_file=own_env),
               await set_env.execute(key=marker, value="1", env_file=own_env)]
    check("the substrate's own settings file is refused, for reading and for writing",
          all(not r.success and "substrate's own settings file" in (r.error or "") for r in refused)
          and marker not in (ROOT / ".env.postgres").read_text(), f"{[r.error for r in refused]}")
    required = [f"{t}.{p}" for t, p in (("get_environment_variable", "env_file"), ("set_environment_variable", "env_file"),
                                          ("check_dependencies", "requirements_file"), ("check_dependencies", "python"),
                                          ("reload_config", "pid"))
                if not next(x for x in registry.get_tool(t).parameters if x.name == p).required]
    check("each takes its file, interpreter or process from the caller", not required, f"optional: {required}")
    reqs = project / "requirements.txt"
    reqs.write_text(f"asyncpg\nnot-a-package-{NONCE}\n")
    deps = await registry.get_tool("check_dependencies").execute(requirements_file=str(reqs), python=sys.executable)
    check("a project's requirements are checked against its own interpreter",
          deps.success and deps.output["installed"] == 1 and deps.output["missing"] == 1,
          deps.error or f"{deps.output['installed']} installed, {deps.output['missing']} missing")
    heard = project / "heard"
    service = project / "service.py"
    service.write_text(
        "import signal, time, pathlib, sys\n"
        f"signal.signal(signal.SIGHUP, lambda *a: pathlib.Path({str(heard)!r}).write_text('reloaded'))\n"
        "deadline = time.time() + 30\n"
        "while time.time() < deadline and not pathlib.Path(sys.argv[1]).exists(): time.sleep(0.1)\n")
    # Started detached, as a user's service is: not a child of this run.
    pid = int(subprocess.run(["/bin/sh", "-c", f"'{sys.executable}' '{service}' '{heard}' >/dev/null 2>&1 & echo $!"],
                             capture_output=True, text=True).stdout.strip())
    await asyncio.sleep(1.0)
    prof = await registry.get_tool("get_performance_profile").execute(pid=pid)
    check("the process asked about is the one profiled",
          prof.success and [p["pid"] for p in prof.output["processes"]] == [pid], prof.error or f"{prof.output}")
    reload = await registry.get_tool("reload_config").execute(pid=pid)
    for _ in range(50):
        if heard.exists():
            break
        await asyncio.sleep(0.1)
    check("a user's service is told to reread its configuration",
          reload.success and heard.exists() and heard.read_text() == "reloaded", reload.error or "reloaded")
    mine = await registry.get_tool("reload_config").execute(pid=os.getpid())
    check("the substrate's own process is refused", not mine.success and "substrate's own process" in (mine.error or ""),
          mine.error)
    shutil.rmtree(project, ignore_errors=True)

    say_line("\n== E. The substrate's stores ==")
    after = {db: await lyric_rows(db) for db in ("lyric_db", "lyric_dev")}
    check("main and sandbox are untouched", before == after, f"before {before}, after {after}")
    EV.note(f"nonce {NONCE}; the outside world was a throwaway PostgreSQL server, removed after the run")
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say_line(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
