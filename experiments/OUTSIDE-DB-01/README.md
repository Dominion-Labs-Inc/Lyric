# OUTSIDE-DB-01: the database tools work on an outside database, never the substrate's own

Fifteen database tools ran their SQL through the substrate's own database manager. The only databases they could
name were the substrate's own: `lyric_unified`, `lyric_thinking_hot`, `lyric_memory_cold`. The "MySQL" tools ran
against the substrate's own PostgreSQL. In development any task could read or change the substrate's memory,
beliefs and people's context through them, around every authority. Law 5 (Containment and Control) forbids that:
never circumvent the safety mechanisms, never bypass the constitution's oversight. The substrate needs no tool for
its own data; it has its authorities.

**What changed (2026-09-30):**
- **Two tools stay, rebuilt for outside databases:**
  - `postgres_query` (PostgreSQL, via asyncpg);
  - `mysql_query` (real MySQL, via aiomysql; before, it ran on the substrate's own PostgreSQL).
  Each takes the outside database's address and login with the query. Each refuses the substrate's own database
  server, by any name of this machine, before connecting (`_is_own_server`, `_outside_postgres`, `_outside_mysql`
  in `core/tools/database_tools.py`).
- **The other thirteen are archived:** the MySQL table info, backup and restore, connection pool, transactions,
  migrations, row-level access, the two safe query executors, the MySQL and PostgreSQL health checks, query metrics
  and create alert. See `archive/superseded_database_tools_2026-09-30/`.
- **Every tool registers the same way everywhere.** The registry's rule for leaving the own-database tools out of
  staging and production is gone, because none are left.
- **`postgres_query` had never been registered;** it is now.

**What it checks.** The outside world is a throwaway PostgreSQL server and a throwaway MySQL server that the run
starts in a temporary folder and removes. The substrate is not started. Another MySQL running on the machine is
not touched: the throwaway one has its own port and data folder, with its second protocol port switched off.

| | |
|---|---|
| A | PostgreSQL: a query reads the outside database's rows; a change writes to it. |
| B | MySQL: the same, on a real MySQL server. |
| C | Either tool pointed at the substrate's own server is refused before connecting, as `localhost`, `127.0.0.1` or the machine's name. The user given does not exist, so a connection would have failed another way. |
| D | Both tools are registered, the thirteen archived ones are not, and the login never appears in what a tool returns. |
| E | Main and sandbox are untouched. |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/OUTSIDE-DB-01/experiment.py
```

**Runs:**
- `20260930T195209Z`, 11/11. This was an earlier version, withdrawn: it looked the person's login up in another
  product's connector store, which has nothing to do with the substrate.
- `20260930T200313Z`, **10/10**, this version.

**Known limits:**
- The login is given with the query, so it passes through the task. Access controls come later.
