"""Oracles for the health evaluator's evidence rules.

Every test here corresponds to a verdict the evaluator actually returned in
production. They are written against the failure, not around it: each one
passes on the old code only if the fabrication is still present.
"""
import ast
import inspect
import textwrap

import pytest

from core.health.health_monitor import HealthMonitor, HealthStatus


@pytest.fixture
def hm():
    # __new__ skips __init__, which is what we want (no monitoring loop, no DB),
    # but the declared-metric channel the checks write through must still exist.
    monitor = HealthMonitor.__new__(HealthMonitor)
    monitor._declared_metrics = {}
    return monitor


def test_no_signals_produces_no_score(hm):
    """A score is a summary of measurements. With none, there is nothing to
    summarise -- `sum(...) if signals else 1.0` invented a perfect one."""
    r = hm.evaluate("tools", {"total_tools": 384}, [])
    assert r["score"] is None
    assert r["status"] is HealthStatus.UNKNOWN
    assert r["coverage"] == 0.0


def test_issues_without_signals_are_not_a_passing_grade(hm):
    """The production reading: tools, one issue, zero measurable signals,
    graded HEALTHY 0.9 -- 1.0 fabricated, then decremented by one issue."""
    r = hm.evaluate("tools", {"total_tools": 384},
                    ["Tool outcomes are recorded asymmetrically"])
    assert r["status"] is not HealthStatus.HEALTHY
    assert r["status"] is HealthStatus.DEGRADED
    assert r["score"] is None, "unmeasured severity must not be quantified"


def test_severity_is_not_a_function_of_issue_count(hm):
    """Eleven issues and no signals graded UNHEALTHY 0.0; one graded HEALTHY
    0.9. Both numbers came from the same invented baseline, so the count alone
    decided severity -- the rule the weighted evaluator was meant to replace."""
    few = hm.evaluate("tools", {"n": 1}, ["a"])
    many = hm.evaluate("tools", {"n": 1}, [f"issue-{i}" for i in range(11)])
    assert few["status"] is many["status"], (
        "with no measurements, eleven issues are not gradably worse than one"
    )
    assert few["score"] is None and many["score"] is None


def test_high_score_on_partial_evidence_is_not_healthy(hm):
    """reasoning read HEALTHY 1.0 at coverage 0.25: one signal true, three
    metrics returned None. evaluate_declared already blocked this."""
    # Liveness-named, as the checks emit them: a bare None field is
    # informational and not evidence at all, so it could not show the defect.
    r = hm.evaluate("reasoning",
                    {"neural_bridge_initialized": True,
                     "bayesian_engine_initialized": None,
                     "causal_engine_initialized": None,
                     "symbolic_engine_initialized": None},
                    [])
    assert r["coverage"] == 0.25
    assert r["status"] is HealthStatus.DEGRADED
    assert r["score"] == 1.0, "the score is real; the confidence in it is not"


def test_full_evidence_still_reaches_healthy(hm):
    """The coverage rule must not make HEALTHY unreachable."""
    r = hm.evaluate("reasoning",
                    {"neural_bridge_initialized": True, "engine_loaded": True},
                    [])
    assert r["coverage"] == 1.0
    assert r["status"] is HealthStatus.HEALTHY
    assert r["score"] == 1.0


def test_critical_gate_still_dominates(hm):
    """Gates outrank both rules above."""
    r = hm.evaluate("database", {"accessible": False, "query_rate": 1.0}, [])
    assert r["status"] is HealthStatus.CRITICAL
    assert r["gate_failures"] == ["accessible"]


def test_both_paths_apply_the_same_coverage_rule(hm):
    """The declared and inferred paths disagreed: one demoted a confident score
    computed without its required evidence, the other did not."""
    from core.health.health_monitor import HealthMetric
    declared = hm.evaluate_declared(
        "x",
        [HealthMetric(name="a", raw_value=True, normalized=1.0, required=True),
         HealthMetric(name="b", raw_value=None, normalized=None, required=True)],
        [],
    )
    inferred = hm.evaluate("x", {"a_initialized": True, "b_initialized": None}, [])
    assert declared["status"] is inferred["status"] is HealthStatus.DEGRADED


def test_persistence_never_substitutes_a_bucket_for_a_missing_score():
    """_persist_assessment fell back to _STATUS_SCORE[status] -- writing a
    fabricated 75.0 for a component whose score was None precisely because
    nothing could be measured. Asserted on the source: the behaviour needs a
    live database, but the substitution is a syntactic property."""
    src = textwrap.dedent(inspect.getsource(HealthMonitor._persist_assessment))
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "_STATUS_SCORE" not in names
    assert not hasattr(HealthMonitor, "_STATUS_SCORE"), (
        "the bucket table is the fabrication source; it should not be reachable"
    )


def test_unmeasurable_component_still_writes_a_row():
    """Returning early left the component's PREVIOUS row in place, so the store
    kept serving a stale `healthy` for something no longer measurable."""
    src = inspect.getsource(HealthMonitor._persist_assessment)
    body = src.split("score =", 1)[1]
    assert "return False" not in body.split("INSERT")[0], (
        "no early return may precede the write; unmeasured is a row with NULL"
    )


def test_declared_not_applicable_is_neither_signal_nor_gap(hm):
    """The distinction has to hold generally, not just for the llm check."""
    base = hm.evaluate("x", {"a_initialized": True, "b_rate": None}, [])
    na = hm.evaluate("x", {"a_initialized": True, "b_rate": None,
                           "_not_applicable": ["b_rate"]}, [])
    assert base["coverage"] < 1.0 and na["coverage"] == 1.0
    assert na["signals_measured"] == base["signals_measured"], (
        "not-applicable must not be counted as a passing measurement either"
    )


@pytest.mark.asyncio
async def test_storage_failure_does_not_erase_a_computed_verdict(monkeypatch):
    """Persistence sat inside the outer handler, so a failed write replaced an
    already-computed verdict with UNKNOWN -- and would have erased a CRITICAL
    one the same way, hiding the failure instead of the outage."""
    from core.health.health_monitor import get_health_monitor
    monitor = get_health_monitor()

    async def boom(_record):
        raise RuntimeError("Database not initialized")

    monkeypatch.setattr(monitor, "_persist_assessment", boom)
    health = await monitor.check_component_health("storage")

    assert health.status is not HealthStatus.UNKNOWN, (
        "an unwritable store is a storage fact, not an unmeasurable component"
    )
    assert health.metrics.get("_persisted") is False
    assert any("not recorded" in i for i in health.issues)


@pytest.mark.asyncio
async def test_busy_dependency_is_not_an_unreachable_one(monkeypatch):
    """llama-server serves one request at a time, so /v1/models queues behind an
    in-flight generation and blows the 5s budget whenever the brain is thinking.
    This is a CRITICAL gate: ordinary inference load flipped `network` to
    UNHEALTHY and made system_awareness report critical services down, while
    inference was completing successfully."""
    import asyncio, os
    from core.health.health_monitor import get_health_monitor

    async def stalled(reader, writer):
        await reader.read(1024)      # accept, read the request, never answer
        await asyncio.sleep(60)

    srv = await asyncio.start_server(stalled, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    monkeypatch.setenv("LLM_SERVER_URL", f"http://127.0.0.1:{port}")
    try:
        metrics, issues = await get_health_monitor()._check_network_health()
    finally:
        srv.close()
        await srv.wait_closed()

    assert metrics["path_llm_server_reachable"] is True
    assert metrics["path_llm_server_slow"] is True
    assert not [i for i in issues if "llm_server" in i]


@pytest.mark.asyncio
async def test_dead_dependency_is_still_reported_unreachable(monkeypatch):
    """The discrimination must not swallow a genuine outage."""
    import socket
    from core.health.health_monitor import get_health_monitor

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                        # nothing is listening on this port

    monkeypatch.setenv("LLM_SERVER_URL", f"http://127.0.0.1:{port}")
    metrics, issues = await get_health_monitor()._check_network_health()

    assert metrics["path_llm_server_reachable"] is False
    assert any("required_dependency_unreachable:llm_server" in i for i in issues)


def test_record_rate_separates_undefined_from_unread(hm):
    """One None was doing two jobs: a rate over zero observations (arithmetic,
    subsystem fine) and a value that could not be read (missing evidence)."""
    m = {}
    hm._record_rate(m, "idle_rate", 0.0, 0)            # nothing counted yet
    hm._record_rate(m, "broken_rate", "not-a-number", 5)   # reading failed
    hm._record_rate(m, "real_rate", 0.75, 4)

    assert m["idle_rate"] is None and "idle_rate" in m["_not_applicable"]
    assert m["broken_rate"] is None and "broken_rate" not in m["_not_applicable"]
    assert m["real_rate"] == 0.75


@pytest.mark.asyncio
async def test_an_idle_parts_rates_are_declared_undefined_and_kept_beside_the_checks_own(monkeypatch):
    """`reasoning` graded degraded while idle, at coverage 0.4: the probe blanked an idle part's rates without
    declaring them not applicable, so they counted as missing evidence; and the probe's metrics replaced the list
    the check had declared itself. Nothing is stored or sent: the verdict's write and notice are stubbed."""
    import sys
    import types
    from core.health.health_monitor import get_health_monitor
    monitor = get_health_monitor()

    class IdlePart:
        initialized = True

        def get_stats(self):
            return {"total_proofs": 0, "success_rate": 0.0}

    async def own_check():
        return {"engine_initialized": True, "own_rate": None, "_not_applicable": ["own_rate"]}, []

    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setitem(sys.modules, "idle_part_for_health_test", types.SimpleNamespace(part=IdlePart))
    monkeypatch.setattr(type(monitor), "_PROBED_SUBCOMPONENTS",
                        {"reasoning": {"prover": ("idle_part_for_health_test", "part", "get_stats")}})
    monkeypatch.setattr(monitor, "_check_reasoning_health", own_check)
    monkeypatch.setattr(monitor, "_persist_assessment", nothing)
    monkeypatch.setattr(monitor, "_notify_status", nothing)

    health = await monitor.check_component_health("reasoning")

    assert health.metrics["prover_success_rate"] is None
    assert {"own_rate", "prover_success_rate"} <= set(health.metrics["_not_applicable"])
    assert health.metrics["_evidence_coverage"] == 1.0
    assert health.status is HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_memory_is_graded_on_the_failures_since_the_last_check(hm, monkeypatch):
    """Two writes lost once kept memory degraded until the process ended: the check graded storage's lifetime count
    of failed operations. A stand-in agent; nothing is read from a store."""
    failed = {"n": 2}

    class Storage:
        async def get_statistics(self):
            return {"total_memories": 10, "metrics": {"failed_operations": failed["n"]}}

    class Agent:
        initialized = True
        postgres_storage = Storage()

        def get_metrics(self):
            return {"postgres_available": True, "cache_size": 0, "cache_hits": 0, "embedding_available": True}

    hm._memory_failures_seen = 0
    monkeypatch.setattr(hm, "_live_singleton", lambda *_args: Agent())

    metrics, issues = await hm._check_memory_health()
    assert metrics["storage_failed_operations"] == 2 and any("2 failed memory operations" in i for i in issues)
    metrics, issues = await hm._check_memory_health()
    assert metrics["storage_failed_operations"] == 0 and not issues, "no failure since the last check"
    assert metrics["storage_failed_operations_total"] == 2
    failed["n"] = 3
    metrics, issues = await hm._check_memory_health()
    assert metrics["storage_failed_operations"] == 1 and any("1 failed memory operations" in i for i in issues)
    failed["n"] = 1
    metrics, _ = await hm._check_memory_health()
    assert metrics["storage_failed_operations"] == 1, "a count that fell is a storage begun again: all of it is new"


def test_topology_matches_services_by_port_not_name():
    """The scanner reports one `postgresql`; the topology models the two logical
    databases sharing that instance as postgresql-lyric/-agentso. Neither name
    could ever match, so a running Postgres was recorded as a CRITICAL service
    down -- while every database health check was passing against it."""
    from core.system.infrastructure_topology import InfrastructureTopology, ServiceTier
    from core.system.environment_state import ServiceInfo, ServiceStatus

    # Lyric's Postgres listens on 5433 (`PostgresConfig`), the port the
    # topology models `postgresql-lyric` on.
    class _Env:
        running_services = {
            "postgresql": ServiceInfo(name="postgresql", port=5433,
                                      status=ServiceStatus.RUNNING),
        }

    topo = InfrastructureTopology()
    topo.update_from_environment(_Env())

    assert topo.services["postgresql-lyric"].is_running is True
    assert topo.services["postgresql-lyric"].health_score > 0.0
    crit_down = [k for k, n in topo.services.items()
                 if n.tier is ServiceTier.CRITICAL and not n.is_running]
    assert "postgresql-lyric" not in crit_down


def test_genuinely_absent_service_still_reads_down():
    """Port matching must not turn every node into a running one."""
    from core.system.infrastructure_topology import InfrastructureTopology

    class _Env:
        running_services = {}

    topo = InfrastructureTopology()
    topo.update_from_environment(_Env())
    assert topo.services["postgresql-lyric"].is_running is False
    assert topo.get_health_summary()["critical_services_down"] > 0


@pytest.mark.asyncio
async def test_system_awareness_probes_before_it_reports(hm):
    """Both EnvironmentState and InfrastructureTopology were constructed and read
    immediately, so every number came from their constructors -- topology starts
    every node at is_running=False ('assume down until proven up') and the
    proving never happened. It reported '4 critical service(s) down' on every
    run regardless of what was actually running."""
    import inspect
    src = inspect.getsource(hm._check_system_awareness_health)
    assert "await env_state.refresh()" in src, "the environment must be scanned"
    assert "update_from_environment" in src, "topology must receive the readings"
    assert "InfrastructureTopology().get_health_summary()" not in src, (
        "reading a freshly constructed topology reports its defaults, not the system"
    )
