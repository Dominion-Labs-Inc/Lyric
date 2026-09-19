#!/usr/bin/env python3
"""Agent factory — the one authority for agents.

An **agent** is a lightweight copy of the substrate. It does NOT carry
its own reasoning/learning/memory engines: it SHARES the substrate's deputies
(the one executor, the learning authority, the memory authority, the reasoning
substrate) exactly as the substrate self reaches them. What makes it a separate
agent is only its own bounded task and the SUBSTRATE-DEFINED subset of tools it
is allowed to use — the substrate decides, per deployment, what a copy of itself
may reach.

This replaces the old factory that minted bespoke `memory` / `research` /
`logical` agent classes. Those were authorities/tools wearing an agent costume:
memory is the `MemoryAgent` authority, research is the `conduct_research` tool,
logical/formal reasoning is reasoning substrate (`core.reasoning.logical_integration`).
None of them are agents; every agent shares them. The `MemoryAgent` is an
authority, never a thing this factory instantiates. This factory holds the
SUBSTRATE's own agents; system agents (security) belong to the world's factory.

Deployment model:
- **No flat cap.** Each ReasoningType carries an ALLOWANCE — how many
  agents may run concurrently for that kind of thinking. Harder,
  search-heavier reasoning (abductive, causal, counterfactual) gets a larger
  allowance so the substrate can pursue several hypotheses at once; simple
  reasoning gets a small one. The substrate deploys up to the allowance and need
  not use all of it.
- **Await-queue.** A deployment runs as its own task. The substrate can `await`
  a specific deployment's findings, or keep talking and later `collect_ready()`
  the ones that have come back — so a slow acquisition never blocks the
  conversation.
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# The per-reasoning-type agent ALLOWANCE is NOT the factory's to decide, and it
# is not the reasoning faculty's either — how many parallel copies of the self a
# kind of thinking justifies is a DEPLOYMENT decision owned by the coordinator
# (the self that reasons and deploys). The factory ASKS the coordinator
# (`AutonomousCoordinator.agent_allowance`) and only ENFORCES the number at the
# single deploy choke point. The one bookkeeping fact the factory keeps for
# itself is the key it counts active deployments under:
def _reasoning_key(reasoning_type: Any) -> str:
    """A ReasoningType enum, its value, or a bare string, as a lowercase key."""
    value = getattr(reasoning_type, "value", reasoning_type)
    return str(value or "").strip().lower()


# ── agent names ───────────────────────────────────────────────────────────
#
# A deployed agent gets a short, memorable NAME as its handle — an
# "adjective-noun" slug like `wandering-otter`, the way a plan or branch gets a
# readable name — instead of an opaque `aos_3f9a…` id. The name IS the handle:
# it's what the substrate awaits/collects under and what shows up in logs, so a
# running fleet reads as names, not hashes. Kept unique among the agents
# CURRENTLY active (that's all the await/collect bookkeeping keys on).
_NAME_ADJECTIVES = (
    "amber", "brave", "brisk", "clever", "cobalt", "crimson", "dapper", "eager",
    "feral", "gilded", "hazy", "ivory", "jolly", "keen", "lucid", "mellow",
    "nimble", "opal", "plucky", "quiet", "rustic", "sly", "spry", "stoic",
    "sunny", "swift", "teal", "umber", "vivid", "wandering", "wily", "witty",
    "zephyr", "bold", "canny", "dusky", "frosty", "lunar", "misty", "noble",
)
_NAME_NOUNS = (
    "otter", "comet", "lantern", "falcon", "cinder", "willow", "harbor",
    "marble", "thistle", "ember", "quartz", "badger", "meadow", "beacon",
    "pebble", "sparrow", "cairn", "birch", "heron", "lynx", "maple", "nimbus",
    "orchard", "raven", "sable", "tundra", "vireo", "walnut", "yarrow", "fox",
    "wren", "sage", "flint", "grove", "kestrel", "moth", "reef", "silo", "cove",
    "fern",
)


def _agent_name(taken: set) -> str:
    """A memorable `adjective-noun` handle, unique among the given active names.
    Adds a tiny suffix only if the space is somehow exhausted — never loops
    forever, never returns a duplicate."""
    for _ in range(64):
        name = f"{random.choice(_NAME_ADJECTIVES)}-{random.choice(_NAME_NOUNS)}"
        if name not in taken:
            return name
    return f"{random.choice(_NAME_ADJECTIVES)}-{random.choice(_NAME_NOUNS)}-{uuid.uuid4().hex[:4]}"


# ── a deployment ────────────────────────────────────────────────────────────

@dataclass
class Deployment:
    """The factory's lightweight record of one running agent.

    The RUNNING task itself is NOT held here — it runs as a background await-job
    on the queue authority, which owns the concurrency budget. This record is only
    what the factory needs to account for the deployment (its reasoning type, for
    the allowance) and to describe it when its findings come back."""
    deployment_id: str
    reasoning_type: str
    description: str
    #: The tools the substrate granted this copy, or None for unrestricted
    #: (full toolset — a plain sub-task of the substrate's own work).
    allowed_tools: Optional[List[str]]
    created_at: datetime


class AgentCoordinator:
    """Deploys and tracks agents. The one authority for agents.

    Holds a reference to the substrate's coordinator — the self, which IS the
    execution faculty (there is no separate executor object) AND owns the agent
    allowance. An agent runs its task through the coordinator's `execute_task`,
    scoped to the tools it was granted; it builds no engines of its own. The
    factory itself is thin: it accounts for running deployments and owns the
    await-queue, nothing more.
    """

    def __init__(self, enable_monitoring: bool = True, enable_safety: bool = True):
        self.enable_monitoring = enable_monitoring
        self.enable_safety = enable_safety
        self.initialized = False
        self.coordinator_id = f"agent_factory_{uuid.uuid4().hex[:8]}"

        #: The substrate's coordinator (the self). It IS the execution faculty —
        #: an agent's task runs through `coordinator.execute_task` — and it OWNS
        #: the agent allowance (`coordinator.agent_allowance`). Bound by the
        #: substrate at wire time (`bind_coordinator`); until then no agent can
        #: run and `deploy` refuses honestly rather than building a second
        #: execution path.
        self._coordinator: Any = None

        #: The queue authority — the ONE owner of concurrency. Every agent runs
        #: as a background await-job on it (never the factory's own
        #: ensure_future), so agent work is bounded by the authority's background
        #: budget and can never steal an acting slot. Fetched lazily.
        self._authority: Any = None

        #: deployment_id -> Deployment. ONLY the currently-running agents: the
        #: authority pushes each result to `_on_agent_done` when it finishes,
        #: which removes the record here (so this is the live allowance count) and
        #: stashes the finding below.
        self._active: Dict[str, Deployment] = {}
        #: Findings delivered by the authority but not yet taken by the substrate.
        #: The factory keeps its OWN ready list rather than sharing the
        #: authority's global pull-collect, so an agent's finding is never
        #: scooped by the coordinator's own `collect_finished_jobs` (and vice
        #: versa). Drained by `collect_ready`.
        self._ready: List[Dict[str, Any]] = []
        #: deployment_id -> Future, for a caller awaiting ONE specific agent
        #: (`await_findings`). Resolved by `_on_agent_done` when that agent lands.
        self._futures: Dict[str, "asyncio.Future"] = {}

        self.metrics = {"deployed": 0, "completed": 0, "failed": 0, "refused": 0}

    async def initialize(self) -> bool:
        """Nothing to build eagerly — agents are spawned on demand and
        share the substrate's deputies. Present so existing callers
        (`get_agent_coordinator`) keep working."""
        self.initialized = True
        logger.info("agent factory ready (%s)", self.coordinator_id)
        return True

    def bind_coordinator(self, coordinator: Any) -> None:
        """Bind the substrate's coordinator (the self) to the factory. Every
        deployed agent runs its task through `coordinator.execute_task`, and the
        allowance number comes from `coordinator.agent_allowance` — never a
        private executor or a private allowance table."""
        self._coordinator = coordinator
        logger.info("agent factory bound to the coordinator (execution + allowance)")

    # ── allowance accounting ────────────────────────────────────────────────

    def _allowance(self, reasoning_type: Any) -> int:
        """Ask the COORDINATOR (the self) how many copies this reasoning type
        warrants. The factory does not decide this and does not keep its own
        numbers; the self — the one that reasons and deploys — owns the allowance.
        Falls back to the moderate default before the coordinator is bound."""
        if self._coordinator is None:
            return 3
        return self._coordinator.agent_allowance(reasoning_type)

    def _authority_handle(self):
        """The queue authority — the one owner of concurrency. Lazy so the
        factory singleton can exist before the authority is constructed."""
        if self._authority is None:
            from core.agents.autonomous.queue_authority import get_queue_authority
            self._authority = get_queue_authority()
        return self._authority

    def active_for(self, reasoning_type: Any) -> int:
        """agents currently RUNNING for this reasoning type. `_active` holds only
        the still-running ones (a finished agent is removed by
        `_on_agent_done`), so this count is exactly the live concurrency."""
        key = _reasoning_key(reasoning_type)
        return sum(1 for d in self._active.values() if d.reasoning_type == key)

    def can_deploy(self, reasoning_type: Any) -> bool:
        return self.active_for(reasoning_type) < self._allowance(reasoning_type)

    # ── deploy / await ──────────────────────────────────────────────────────

    def deploy(
        self,
        description: str,
        *,
        reasoning_type: Any,
        allowed_tools: Optional[List[str]],
        task_type: Any = None,
        actor: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Deploy an agent for `description`, scoped to `allowed_tools`
        (a list the substrate grants; None = unrestricted, the full toolset).

        Returns the agent's NAME (its handle — a memorable slug like
        `wandering-otter`) to await/collect later, or None when the reasoning
        type's allowance is already full (an honest refusal — the substrate
        decides what to do, it is never silently queued or dropped) or the
        coordinator is not bound yet.
        """
        if self._coordinator is None:
            logger.warning("deploy refused: no coordinator bound (no execution faculty)")
            self.metrics["refused"] += 1
            return None
        if not self.can_deploy(reasoning_type):
            logger.info("deploy refused: %s allowance full (%d/%d)",
                        _reasoning_key(reasoning_type),
                        self.active_for(reasoning_type), self._allowance(reasoning_type))
            self.metrics["refused"] += 1
            return None

        deployment_id = _agent_name(set(self._active))  # the agent's memorable handle
        key = _reasoning_key(reasoning_type)
        self._active[deployment_id] = Deployment(
            deployment_id=deployment_id, reasoning_type=key,
            description=description,
            allowed_tools=list(allowed_tools) if allowed_tools is not None else None,
            created_at=datetime.now())
        # Run through the queue authority on its BACKGROUND budget, with PUSH
        # delivery: when the agent finishes the authority hands its outcome to
        # `_on_agent_done`. The factory never spawns its own task and never
        # shares the authority's global pull-collect.
        self._authority_handle().submit(
            lambda: self._run_agent(deployment_id, description, task_type, actor,
                                    allowed_tools, parameters or {}),
            name=f"agent:{key}", job_id=deployment_id,
            on_complete=self._on_agent_done)
        self.metrics["deployed"] += 1
        logger.info("deployed agent %s (%s, tools=%s)", deployment_id, key,
                    "all" if allowed_tools is None else f"{len(allowed_tools)} scoped")
        return deployment_id

    def _on_agent_done(self, outcome: Dict[str, Any]) -> None:
        """Push handler the authority calls when an agent finishes. `outcome` is
        {job_id, name, result, error} — error set means the agent failed, and it
        is carried through honestly, never reported as findings. Moves the
        deployment out of the live set and either resolves a waiter
        (`await_findings`) or stashes it for `collect_ready`."""
        deployment_id = outcome.get("job_id")
        dep = self._active.pop(deployment_id, None)
        error = outcome.get("error")
        if error:
            self.metrics["failed"] += 1
            logger.error("agent %s failed: %s", deployment_id, error)
        else:
            self.metrics["completed"] += 1
        finding = {
            "deployment_id": deployment_id,
            "description": dep.description if dep else None,
            "findings": outcome.get("result") if not error else None,
            "error": error,
        }
        fut = self._futures.pop(deployment_id, None)
        if fut is not None and not fut.done():
            fut.set_result(finding)
        else:
            self._ready.append(finding)

    async def _run_agent(self, deployment_id, description, task_type, actor,
                         allowed_tools, parameters) -> Dict[str, Any]:
        """An agent runs its task through the COORDINATOR's execution faculty
        (`execute_task` — the self IS the executor; there is no separate executor
        object), scoped to the tools it was granted. It carries no engines of its
        own; the coordinator, and every authority beneath it, is the substrate's."""
        from core.agents.autonomous.shared_types import (
            Task, TaskType, TaskSource, SUBSTRATE_ACTOR)

        tt = task_type if isinstance(task_type, TaskType) else TaskType.RESEARCH
        task = Task(
            id=deployment_id,
            type=tt,
            description=description,
            source=TaskSource.AUTONOMOUS,
            actor=actor or SUBSTRATE_ACTOR,
            created_by=f"agent:{deployment_id}",
            allowed_tools=(list(allowed_tools) if allowed_tools is not None else None),
            metadata={"agent": True, "parameters": parameters},
        )
        result = await self._coordinator.execute_task(task)
        return result if isinstance(result, dict) else {"result": result}

    async def await_findings(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """Block until this agent returns, then hand back its findings (or an
        honest error). None if the id is unknown. Works whether the agent is
        still running (waits on a future the push handler resolves) or has
        already landed in the ready list (takes it from there)."""
        # Already delivered? Take it from the ready list.
        for i, finding in enumerate(self._ready):
            if finding["deployment_id"] == deployment_id:
                return self._ready.pop(i)
        if deployment_id not in self._active:
            return None
        # Still running — wait on a future the push handler will resolve.
        fut = self._futures.get(deployment_id)
        if fut is None:
            fut = asyncio.get_event_loop().create_future()
            self._futures[deployment_id] = fut
        return await fut

    def collect_ready(self) -> List[Dict[str, Any]]:
        """Take every agent that has come back since the last collect, WITHOUT
        blocking — so the substrate can keep a conversation going and reconcile
        findings whenever it checks. Still-running agents stay in `_active`. This
        drains the factory's OWN ready list (filled by the authority's push
        delivery), never the authority's global pull-collect."""
        ready, self._ready = self._ready, []
        return ready

    def pending(self) -> List[str]:
        """Deployment ids still running."""
        return list(self._active)

    async def delegate_task(
        self,
        task: str,
        task_type: str,
        parameters: Optional[Dict[str, Any]] = None,
        allowed_tools: Optional[List[str]] = None,
        reasoning_type: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Deploy an agent for one task and WAIT for it — the synchronous
        convenience the `delegate_task` tool uses. `allowed_tools` defaults to
        None → the executor's full set (a plain sub-task of the substrate's own
        work); the substrate passes a scoped set when it wants a restricted copy.
        Returns the findings, or None on refusal/failure (honest)."""
        from core.agents.autonomous.shared_types import TaskType

        tt = None
        try:
            tt = TaskType(str(task_type).lower())
        except Exception:
            tt = TaskType.RESEARCH
        deployment_id = self.deploy(
            task, reasoning_type=reasoning_type or "deductive",
            allowed_tools=allowed_tools,  # None = unrestricted (full toolset)
            task_type=tt, parameters=parameters)
        if deployment_id is None:
            return None
        outcome = await self.await_findings(deployment_id)
        return outcome.get("findings") if outcome else None

    async def get_statistics(self) -> Dict[str, Any]:
        return {
            "coordinator_id": self.coordinator_id,
            "initialized": self.initialized,
            "coordinator_bound": self._coordinator is not None,
            "running": len(self._active),
            "ready_uncollected": len(self._ready),
            **self.metrics,
        }

    async def shutdown(self):
        """Cancel any in-flight agents through the authority (which owns the
        running tasks), then clear the factory's records."""
        authority = self._authority_handle()
        for deployment_id in list(self._active):
            authority.cancel(deployment_id)
        self._active.clear()
        self._futures.clear()
        self._ready.clear()
        logger.info("agent factory shut down")


# ── singleton ───────────────────────────────────────────────────────────────
#
# Exactly ONE factory in the process (main.py and the delegate_task tool both
# reach it). Two would split the deployment registry the way two meta-learners
# split the posteriors — authoritative state disagreeing with itself.

_agent_coordinator: Optional[AgentCoordinator] = None


async def get_agent_coordinator(
    enable_monitoring: bool = False,
    enable_safety: bool = True,
) -> AgentCoordinator:
    """Get the shared agent factory, initializing it on first use."""
    global _agent_coordinator
    if _agent_coordinator is None:
        _agent_coordinator = AgentCoordinator(enable_monitoring, enable_safety)
        if not await _agent_coordinator.initialize():
            raise RuntimeError("AgentCoordinator failed to initialize")
    return _agent_coordinator
