# Are the tools for outside users? Audit of `core/tools`, 2026-09-30

**The rule.** A tool serves the people and systems outside the substrate. Versatile tools, which act on whatever
they are pointed at, are fine. A tool must never act on the substrate itself: its own database, memory, learning,
configuration, security, code or agents. The substrate reaches its own state through its authorities. A tool used
on itself goes around them, which Law 5 (Containment and Control) forbids: never circumvent the safety mechanisms,
never bypass the constitution's oversight.

**Decided and done (2026-09-30), checked by `experiments/TOOLS-EXTERNAL-01` (17/17):**
- **A.** Handled so far:
  - chaos tools archived;
  - memory tools (`query_memory`, `store_memory`) archived;
  - the six learning tools archived as obsolete: the learning system does all of it;
  - the configuration and environment tools rebuilt to work on a user's project and services, refusing the
    substrate's own settings and processes (TOOLS-EXTERNAL-01, 26/26).

  - `delegate_task` deleted, after AGENTS-01 (9/9) showed the substrate's own agent deployment is sound.

  - The firewall and Cloudflare tools are not rebuilt: Tet owns that, on the owner's word. The nine stay as they
    are; they cannot run, since they import `create_integrated_security_system`, which no longer exists. The owner wants those to
  work both ways, for users and for the substrate. The rule is that no tool is hardcoded to the substrate.
- **B.** The security tools are rebuilt to read the logs they are told to: outside, or the substrate's own when
  named. They are the one kind of tool that may look at the substrate itself, for its own defence.
  `detect_brute_force` is disabled, and its invented-attack fallback removed.
- **C.** The file and code tools take their folder from the caller, for the substrate's code and for users'.
- **D.** The AgentSO tools are left as they are, but guarded.
- **E.** Left.

**How it was checked.**
1. Every tool class in `core/tools` was read for three things:
   - imports of the substrate's own internals (database, memory, learning, reasoning, security, health, agents);
   - descriptions that name the substrate;
   - defaults that point at the substrate's own files.
2. Every tool flagged by that was then read by hand.

346 tools are registered.

## Already fixed

| Tools | What was wrong | Now |
|---|---|---|
| `postgres_query`, `mysql_query` | ran SQL on the substrate's own database | work on an outside database they are given, and refuse the substrate's own server (OUTSIDE-DB-01, 10/10) |
| 13 other database and monitoring tools | ran on the substrate's own database | archived: `archive/superseded_database_tools_2026-09-30/` |

## A. Act on the substrate itself

| Group | Tools | What they act on |
|---|---|---|
| Chaos | `create_chaos_experiment`, `run_chaos_experiment`, `create_chaos_experiment_from_scenario`, `list_chaos_scenarios`, `get_chaos_experiment_status`, `rollback_chaos_experiment` (chaos_tools.py); `chaos_testing` (testing_validation_tools.py) | The substrate's own systems (memory, learning, reasoning, security, tools, agents…), the only targets offered. Faults include `DATA_CORRUPTION`. |
| Its memory | `query_memory`, `store_memory` (ai_ml_tools.py) | The substrate's own memory, through a tool |
| Its learning | `profileperformance`, `analyzecausalfeedback`, `extractlessonslearned`, `benchmarkcapability`, `recommendtraining`, `generatehypothesis` (learning_tools.py) | Profile its own components, feed its own causal analyzer and meta-learner, benchmark itself, and write hypotheses into its own hypothesis store |
| Its configuration and environment | `reload_config`, `get_environment_variable`, `set_environment_variable`, `check_dependencies` (system_management_tools.py); `get_performance_profile` (monitoring_tools.py) | Its own config, **its own environment (passwords included)**, its own `.env` by default, its own project, its own processes |
| Its defenses | `block_ip_address`, `unblock_ip_address`, `get_active_blocks`, `create_waf_rule`, `apply_rate_limit`, `block_country`, `get_security_metrics`, `get_block_history`, `add_internal_threat` (security_tools.py) | Its own security system: the firewall of the machine it runs on, the Cloudflare account in its settings, its own threat records. `unblock_ip_address` can take down its own defenses. |
| Its agents | `delegate_task` (delegation_tools.py) | Its own agent coordinator |

## B. Meant for customers, but wired to the substrate's own database

| Tools | What they read |
|---|---|
| `detect_intrusion`, `analyze_anomaly`, `monitor_logs`, `detect_brute_force`, `analyze_traffic_pattern`, `hunt_threats`, `detect_zero_day` (security_tools.py) | `auth_logs`, `network_logs` and similar tables **in the substrate's own database**. A customer's logs are not there. |
| `check_rate_limit` (security_tools.py) | Keeps its counts in the substrate's own database |

These are cybersecurity work for customers. Like the database tools, they would need to read the customer's logs
from the source they are given.

## C. Versatile, but default to the substrate's own files

Given no path, these act on the folder the substrate runs in, which is its own code:

| Tool | File |
|---|---|
| `search_files` | filesystem_tools.py |
| `grep_search` | search_tools.py |
| `semantic_search` ("search codebase") | search_tools.py |
| `generate_changelog` | documentation_tools.py |
| `run_coverage` | testing_validation_tools.py |

The fix: the target must be given, and the substrate's own folder is refused, as the database tools refuse its
own server.

## D. Tie to another product

- **59 tools come from `connector_tools.py`.** It wraps the connectors of a separate program (AgentSO), loaded from
  `services/agentso` by path.
- **`agentso_capability_tools.py`** has the same tie.

That program is not part of the substrate or the startup.

## E. Fine: the substrate's faculties doing a job for the user

These compute on what the user gives them and neither read nor change the substrate's state:
- `prove_theorem`, `solve_constraints`, `generate_symbolic_math`, `refactor_code`, `extract_entities`;
- `generate_embedding`, `semantic_similarity`, `run_inference`, `get_model_info`;
- `synthesize_literature`, `check_ip_threat_intelligence`.

## Not yet settled

`detectpatterns` and `monitordatadrift` (learning_tools.py) take the data they are given, but run it through the
substrate's own causal analyzer. Whether that changes the analyzer's state needs a closer read.
`visualizelearningprogress` and `identifyskillgaps` compute only on what they are given.

## Everything else

About 230 tools act on whatever they are given: web, network, files, shell, code, documents, data, research,
messaging. None of them reference the substrate's internals or default to its files.
