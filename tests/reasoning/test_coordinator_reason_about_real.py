#!/usr/bin/env python3
"""The autonomous coordinator's reasoning entry, `reason_about()`, against the
real system — proving the coordinator reasons THROUGH the authority.

reason_about() is the method every autonomous path uses to reason. It must:
  - go through the authority (`neural_bridge.reason`), never around it;
  - return the authority's own verdict (verified / derived-by-kind);
  - record provenance route [reason_about, neural_bridge, ...].

This drives the REAL `AutonomousCoordinator.reason_about` code, bound to a
minimal object carrying a real, initialised neural bridge and the REAL memory
agent, so the conclusion it reaches is also shown to be remembered. Runs against
the real DB; the whole thing is model-free.
"""

import asyncio
import sys
import types


async def run() -> int:
    # Always substrate-first, and model-free BY CONSTRUCTION: `core.model_policy`
    # was REMOVED with the last model in core/, so there is no policy to set.

    from core.reasoning.neural_bridge import get_neural_bridge
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    from core.reasoning.reasoning_interfaces import ReasoningType

    bridge = get_neural_bridge()
    if hasattr(bridge, "initialize"):
        await bridge.initialize()

    # Minimal stand-in: the real reason_about method, a real bridge, and the
    # REAL memory agent. This used to hang a `store_memory` stub off the object
    # itself; reason_about writes through `self.memory.store_memory(...)`, so
    # the stub was never reached and the test had been failing on a missing
    # attribute. Memory is the one and only store, so the honest fixture is the
    # store -- and it also proves the conclusion is actually remembered.
    from core.agents.memory_agent import get_memory_agent

    class _Stub:
        pass
    obj = _Stub()
    obj.neural_bridge = bridge
    obj.memory = await get_memory_agent()

    reason_about = AutonomousCoordinator.reason_about.__get__(obj, _Stub)

    cases = [
        ("deductive", "is socrates mortal?",
         {"premises": ["human(socrates)"], "rules": ["human(?x) -> mortal(?x)"]},
         "mortal"),
        ("causal", "what does smoking cause?",
         {"premises": ["smoking causes lung damage"]}, "lung damage"),
        ("temporal", "does the alarm ring before breakfast?",
         {"premises": ["the alarm rings before the coffee brews",
                       "the coffee brews before breakfast"]}, "before"),
    ]

    results = []
    remembered = 0
    at_default = 0
    for kind_value, question, ctx, expect in cases:
        rt = next(t for t in ReasoningType if t.value == kind_value)
        result = await reason_about(question, ctx, rt)
        md = getattr(result, "metadata", {}) or {}
        answer = str(getattr(result, "answer", "") or "")
        route = md.get("route") or []
        ok = (md.get("verified") is True
              and md.get("kind") == kind_value
              and "reason_about" in route and "neural_bridge" in route
              and expect.lower() in answer.lower())
        results.append((kind_value, ok,
                        f"verified={md.get('verified')} kind={md.get('kind')} "
                        f"route={route} answer={answer[:50]!r}"))
        # DID THE CONCLUSION LAND IN THE STORE? That is reason_about's memory
        # obligation, so it is read from the store itself.
        #
        # search_memories returns (ok, items) -- NOT a bare list. Iterating the
        # tuple compares against the repr of the item list, which contains the
        # question text, so a naive loop reports a hit for a search that found
        # nothing. Unpack it.
        async def _found(threshold):
            ok_search, items = await obj.memory.search_memories(
                f"I was asked: {question}", min_similarity=threshold, limit=5)
            return bool(ok_search and any(
                question.lower() in str(getattr(m, "content", "")).lower()
                for m in (items or [])))

        if await _found(0.5):
            remembered += 1
        # Separately measured, NOT asserted: the same memory at the 0.7 default.
        # The write always lands; the default floor is what hides it. Reported
        # as a number so a change either way is visible.
        if await _found(0.7):
            at_default += 1

    print("\n===== coordinator.reason_about() THROUGH THE AUTHORITY =====")
    passed = 0
    for kind_value, ok, detail in results:
        if ok:
            passed += 1
        print(f"  {'PASS' if ok else 'FAIL'}  {kind_value:12} {detail}")
    print(f"  conclusions written to the real store: {remembered}/{len(cases)}")
    print(f"  ...of those, surfaced by search at the 0.7 default: "
          f"{at_default}/{len(cases)}  (retrieval floor, not a write failure)")
    print(f"\n  {passed}/{len(cases)} coordinator reasoning calls verified via the authority\n")
    return 0 if (passed == len(cases) and remembered == len(cases)) else 1


def main() -> int:
    try:
        return asyncio.run(run())
    except Exception as error:
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
