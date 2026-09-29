"""LOOKUP-SINGLEFLIGHT-01 — a crowd asking the same unknown at once researches it ONCE.

The real `Conversation.look_up` single-flight, with the web research (`_research_phrase`)
replaced by an instrumented stand-in that counts real calls and is slow enough to overlap.
Proves: N concurrent callers for the same phrase → exactly ONE research call, all get the
same result; distinct phrases are NOT deduped; after it drains, a later call researches
again (not a cross-time cache). Also proves case/whitespace normalisation collapses to one.

Run: ./venv_lyric/bin/python3 scratchpad/bench_lookup_singleflight.py
"""
import asyncio, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

results = []
def check(n, ok, d=""):
    results.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


async def main():
    from core.agents.autonomous.autonomous_coordinator import Conversation, _LOOKUPS_INFLIGHT

    calls = {"n": 0}
    class _Probe:
        # only what look_up touches: the real single-flight body calls self._research_phrase
        look_up = Conversation.look_up
        async def _research_phrase(self, phrase):
            calls["n"] += 1
            await asyncio.sleep(0.05)          # long enough that the crowd overlaps
            return f"acquired::{phrase}"
    me = _Probe()

    print("\n== 100 concurrent callers, same phrase → ONE research ==")
    calls["n"] = 0
    res = await asyncio.gather(*[me.look_up("memristor") for _ in range(100)])
    check("exactly ONE real research call for 100 identical concurrent asks", calls["n"] == 1,
          f"research calls = {calls['n']}")
    check("all 100 callers got the same result", all(r == "acquired::memristor" for r in res),
          f"distinct results = {len(set(res))}")
    check("in-flight registry drained after completion", len(_LOOKUPS_INFLIGHT) == 0,
          f"held = {len(_LOOKUPS_INFLIGHT)}")

    print("\n== case / whitespace variants of the same phrase collapse to one ==")
    calls["n"] = 0
    await asyncio.gather(me.look_up("Memristor"), me.look_up("  memristor "),
                         me.look_up("MEMRISTOR"), me.look_up("memristor"))
    check("normalised variants dedup to ONE research", calls["n"] == 1, f"calls = {calls['n']}")

    print("\n== distinct phrases are NOT deduped ==")
    calls["n"] = 0
    await asyncio.gather(me.look_up("alpha particle"), me.look_up("beta decay"),
                         me.look_up("gamma ray"))
    check("three distinct phrases → three researches", calls["n"] == 3, f"calls = {calls['n']}")

    print("\n== not a cross-time cache: a later ask re-verifies ==")
    calls["n"] = 0
    await me.look_up("memristor")          # in-flight entry already drained
    await me.look_up("memristor")
    check("two sequential (non-overlapping) asks → two researches (world may have changed)",
          calls["n"] == 2, f"calls = {calls['n']}")

    print("\n== an error does not wedge the registry (next ask can proceed) ==")
    class _Boom(_Probe):
        async def _research_phrase(self, phrase):
            raise RuntimeError("research blew up")
    boom = _Boom()
    raised = 0
    async def _try():
        nonlocal raised
        try:
            await boom.look_up("thing")
        except RuntimeError:
            raised += 1
    await asyncio.gather(_try(), _try(), _try())
    check("concurrent callers all see the error (propagated, not swallowed)", raised == 3, f"raised={raised}")
    check("registry drained after the error (no wedged key)", len(_LOOKUPS_INFLIGHT) == 0,
          f"held = {len(_LOOKUPS_INFLIGHT)}")

    passed = sum(results); total = len(results)
    print(f"\n==== LOOKUP-SINGLEFLIGHT-01: {passed}/{total} checks passed ====")
    return 0 if passed == total else 1

sys.exit(asyncio.run(main()))
