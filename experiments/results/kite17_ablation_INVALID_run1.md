# kite17_ablation — run 2026-08-17T20:14:05.502163+00:00

**INVALID — CONFIGURATION ISOLATION FAILURE.** This run is not evidence about the substrate.

- **Cause:** core/database/unified_database_postgres.py called load_dotenv('.env.postgres', override=True) inside the constructor and then read os.getenv('POSTGRES_DATABASE') on the following line. override=True rewrote the process environment, so the externally supplied per-condition database was discarded and every condition connected to the same authority.
- **What was seen:** All 7 conditions loaded identical rules (executable=2) and passed 14/14, including NO_LEARNED_RULES and BLANK, whose learned state had been deleted from their clones.
- **What it shows:** The severance oracle behaved correctly: it showed the intended intervention was not causally connected to the runtime's actual configuration authority. The null result is evidence about the harness, not about the substrate.
- **Repair:** load_dotenv removed from the database class; PostgresConfig introduced as the single resolution authority (explicit > environment > .env file > coded default) reading via dotenv_values so os.environ is never mutated. assert_database_identity() added, which asks the server SELECT current_database() rather than trusting configuration.

**Hypothesis.** The novel capability is causally carried by unified.learned_rules. Removing that learned state removes the capability; restoring the same state restores it, with source code, runtime, evaluation inputs and model availability unchanged.

Each condition runs the same frozen case suite against its own copy of the database (source: `torinai_db`), with the model off and learning frozen.

| Condition | Database connected | Rules executable | Cases passed |
|---|---|---|---|
| FULL | torinai_db | 2 | 14/14 |
| SHAM | torinai_db | 2 | 14/14 |
| NO_LEARNED_RULES | torinai_db | 2 | 14/14 |
| RULE_PRESENT_BUT_NOT_VALIDATED | torinai_db | 2 | 14/14 |
| NO_CONCEPTS | torinai_db | 2 | 14/14 |
| BLANK | torinai_db | 2 | 14/14 |
| RESTORED | torinai_db | 2 | 14/14 |

Commit: not_a_git_repo. Frozen rules: rule_d3244fd036c3, rule_dcd916b30f7f.

Generated from `kite17_ablation_INVALID_run1.json`, the data for this run.
