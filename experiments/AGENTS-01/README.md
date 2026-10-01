# AGENTS-01: the substrate deploys agents of itself, and they are sound

An agent of self is a copy of the substrate scoped to one task and a granted set of tools. It runs through the
coordinator's own execution and every authority beneath it: `AutonomousCoordinator.deploy_agent`, `await_agent`,
`collect_agent_findings` and `pending_agents`, over the agent factory (`core/agents/agents.py`), on the queue
authority's background budget. This checks that path before the `delegate_task` tool, a second way into the same
factory, was deleted.

**The substrate never has to wait for an agent (2026-09-30).** The moment an agent lands, the factory hands its
findings to the coordinator as a `JOB_COMPLETED` self-event. That is the event already meant for "an agent's
findings", but the factory had only kept them in its own list, so the substrate learned of them only by waiting or
by asking. The self now reconciles them on arrival (`_react_job_completed`: a domain outcome is learned from, a
failure recorded). Awaiting one agent, or collecting, stay for a caller that wants them. The held list keeps only
the latest 100. Also fixed: the reaction read a failed job's error as `payload["error"]` from a dataclass, so every
failed job's event faulted.

**What it checks**, on the running substrate in the sandbox:

| | |
|---|---|
| A | The coordinator holds the agent factory, and the factory is bound back to it (at boot, by `core/main.py`). |
| B | A deployed agent returns its name. Awaited, it returns its findings: what the note it read says. |
| C | An agent never uses a tool it was not granted. The log shows the refusal: "read_file not granted to task … (allowed=['list_directory']); refused". |
| D | Past the allowance for a kind of reasoning, deployment is refused while the others run. |
| E | Findings are collected when they are back, without waiting on any one agent, and nothing is left pending. |
| F | An agent whose work fails reports the failure, never findings. |
| H | An agent's findings reach the substrate on their own, as a `JOB_COMPLETED` self-event, with nothing awaited or collected. A failed job's event is received without fault. |
| G | The main model's store is untouched. |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/AGENTS-01/experiment.py
```

It leaves in the sandbox, named by the run's nonce, the agents' pursuit memories and task records.

**Runs:**
- `20260930T230418Z`, **9/9**.
- `20260930T235350Z`, **11/11**, with H: findings handed to the substrate, never waited for.

**Known limit:** nothing in the substrate decides to deploy an agent yet. `deploy_agent` has no caller; the
`delegate_task` tool was the only way agents were ever used. The ability is sound, and the substrate's own
decision to use it (a knowledge gap, a long watch) is not built.
