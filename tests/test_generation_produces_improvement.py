"""Phase 3 generation must actually produce a validated improvement when handed a
code-addressable target — the thing that never once happened, because it invoked a
fictional parameter contract no tool accepts and then asked the symbolic reasoner a
question it cannot formalise.

Guards, against the REAL system:
  1. The real tool contract: optimize_code accepts {"code": ...}; the old blob is
     rejected by the tool's schema.
  2. End-to-end: an EFFICIENCY target yields exactly one improvement, verified
     structurally (no reasoner crash).
  3. A non-codegen family (META) is skipped, never invoked with a contract it
     would reject.
"""
import asyncio
import io
import contextlib
import logging

SNIPPET = ("def collect(items):\n    result = []\n    for x in items:\n"
           "        result.append(x * 2)\n    return result\n")


def test_generation_produces_a_verified_improvement():
    async def _impl():
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from core.main import get_system
            s = get_system(); await s.initialize()
            from core.learning.enhanced_asi_self_improvement import (
                get_asi_self_improvement, ImprovementTarget, RemedyFamily)
            from core.learning import ImprovementScope
            eng = get_asi_self_improvement()

            # 1) contract: old blob rejected, real contract accepted
            old = await eng.tool_registry.execute_tool("optimize_code", {
                "description": "x", "function_name": "y", "component": "z",
                "requirements": "r", "existing_code": SNIPPET, "scope": "minor",
                "context": {}, "parameters": {}})
            new = await eng.tool_registry.execute_tool("optimize_code", {"code": SNIPPET})

            # feed the snippet as the component's source
            async def _fake_source(component):
                return SNIPPET
            eng._get_existing_code = _fake_source

            # 2) EFFICIENCY target -> one verified improvement
            eff = ImprovementTarget(
                target_id="t1", component="demo.collect", metric="health_score",
                current_value=60.0, target_value=90.0, improvement_potential=20.0,
                difficulty="easy", risk_level="low",
                context={"issues": ["hot loop rebuilds a list; latency elevated"]})
            eff.remedy_family = RemedyFamily.EFFICIENCY
            eff.function = "collect"  # generation is function-granular
            eff_out = await eng._generate_improvements([eff], ImprovementScope.MINOR, {})

            # 3) META target -> skipped, not crashed
            meta = ImprovementTarget(
                target_id="t2", component="learning", metric="health_score",
                current_value=25.0, target_value=90.0, improvement_potential=10.0,
                difficulty="hard", risk_level="low",
                context={"issues": ["Low ASI improvement success rate: 0% over 15 cycles"]})
            meta.remedy_family = RemedyFamily.META
            meta_out = await eng._generate_improvements([meta], ImprovementScope.MINOR, {})

        assert old.success is False and "parameter" in (old.error or "").lower()
        assert new.success is True and (new.output or {}).get("code", "").strip()
        assert len(eff_out) == 1
        assert meta_out == []

    asyncio.run(_impl())
