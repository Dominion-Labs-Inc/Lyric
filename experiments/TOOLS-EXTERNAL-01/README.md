# TOOLS-EXTERNAL-01: no tool is hardcoded to the substrate

The tools serve people and systems outside the substrate. The audit of `core/tools`
(`docs/research/TOOLS_AUDIT_2026-09-30.md`) found tools that could only act on the substrate itself, tools meant
for customers but wired to the substrate's own database, and tools that fell back to the substrate's own folder.
On the owner's word:

- **Chaos tools archived.** Seven tools whose only targets were the substrate's own systems
  (`archive/superseded_chaos_tools_2026-09-30/`). The testing and validation tools stay.
- **Security tools rebuilt.** The six log readers and the rate limiter read the logs of the system they are told
  to:
  - `logs_of="outside"`: a PostgreSQL log database given by address and login;
  - `logs_of="lyric"`: the substrate's own logs. These are the one kind of tool that may look at the substrate
    itself, for its own defence.

  Details:
  - Nothing is assumed: with no source named they refuse. An "outside" source that is the substrate's own server
    is refused, and the refusal says to name it instead.
  - The rate limiter counts in the protected system's database.
  - `detect_zero_day` now says which checks it could not make. Before, a failed check was skipped and the result
    read as clean.
  - `detect_brute_force` is **disabled** (kept, not registered). When its query failed, it invented an attack: two
    made-up sources and their attempts, reported as found. That is removed; a failure is now a failure.
- **File and code tools take their folder from the caller:** `search_files`, `grep_search`, `semantic_search`,
  `generate_changelog`, `run_coverage`. They work on the substrate's own code and on a user's alike, but never
  assume either.
- **Six learning tools archived.** They drove the substrate's own learning machinery; the learning system does
  all of that itself (`archive/superseded_learning_tools_2026-09-30/`). The four that work on given data stay.
- **Memory tools archived.** `query_memory` and `store_memory` read and wrote the substrate's own memory through a
  tool (`archive/superseded_memory_tools_2026-09-30/`). The memory agent is the only way to that memory.
- **Configuration and environment tools work for users:**
  - `get_environment_variable` and `set_environment_variable` read and write the project's .env file they are
    given. They used to read the substrate's own live environment, handing out its passwords, and write the
    substrate's own `.env` by default. The substrate's own folder is refused.
  - `check_dependencies` checks a project's requirements against that project's interpreter, not whichever `pip3`
    came first.
  - `get_performance_profile` profiles the process it is asked about. It used to ignore that and always profile the
    substrate's own process.
  - `reload_config` has a running service reread its configuration (SIGHUP). It used to reload the substrate's own
    config module. The substrate's own processes are refused.
- **AgentSO connector tools guarded, not changed.**
  - AgentSO's folder goes at the end of the import path, so none of its modules can stand in for the substrate's.
  - Its tools are not registered when AgentSO is absent.
  - A connector that points at the substrate's own database server is refused before it runs.

**What it checks.** The outside world is a throwaway PostgreSQL server holding a customer's log database, which the
run starts and removes. The substrate is not started.

| | |
|---|---|
| A | No chaos tool is registered. All 19 testing and validation tools are. The six obsolete learning tools are not registered; the four that work on given data are. `detect_brute_force` is kept in the code and not registered. |
| B | Each security tool refuses with no source named. An "outside" source that is the substrate's own server is refused. On the customer's log database, twelve failed logins from one address are found. The rate limiter allows three and blocks the fourth, counting there. Zero-day detection names the check it could not make. Named, the substrate's own security logs are read. |
| C | Each file and code tool requires its folder. `grep_search` finds text in a user's folder and in the substrate's own code. |
| D | AgentSO's folder is after the substrate's own on the import path. Its connector tools are registered. A connector pointing at the substrate's own database server is refused before it runs. The connector there is the one stand-in. |
| F | The memory tools are not registered. A variable is read from a project's .env file, and written there, never into the substrate's live environment. The substrate's own settings file is refused for both. Each tool takes its file, interpreter or process from the caller. A project's requirements are checked against its own interpreter. A user's service, started detached, is profiled and told to reread its configuration. The substrate's own process is refused. |
| E | Main and sandbox are untouched. |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/TOOLS-EXTERNAL-01/experiment.py
```

**Runs:**
- `20260930T222025Z`, **17/17** (A to E).
- `20260930T223926Z`, **26/26**, with F.
- `20260930T225951Z`, **27/27**, with the learning tools archived.

**Known limits:**
- **The substrate records no security logs of its own yet.** Its `auth_logs`, `access_logs`, `network_logs` and
  `security_events` tables are empty in both stores; the only writers are a disabled security controller and the
  website gateway, which keeps its own database. So `logs_of="lyric"` reads, and finds nothing, until the
  substrate's front door records its own logins and requests.
- **The substrate's `auth_logs` does not match the tools.** It names the address `ip_address`; the tools read
  `source_ip` and `endpoint`. The login checks on `logs_of="lyric"` report an error until the two agree.
- **Outside log databases are PostgreSQL only.** The tools' SQL is PostgreSQL's.
- **Logins pass through the task.** Access controls come later.
