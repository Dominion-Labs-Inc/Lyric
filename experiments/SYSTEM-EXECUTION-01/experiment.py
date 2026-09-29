#!/usr/bin/env python3
"""SYSTEM-EXECUTION-01 — the acting faculties, alone, on the live substrate.

The rule store (`RuleStore`), the operator bindings (`BindingRegistry`) and the
tool registry — what the substrate acts through. A rule is found by id and by
status, an unknown id is None; a binding is registered, found and cleared; a
tool call passes the one gate, carries its judgement, and really does what it
says; a tool that does not exist is refused, not invented.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-EXECUTION-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import authority_audit, boot, outcome, shutdown  # noqa: E402

DOMAIN = "isolation_probe_execution"
EV = RunRecord(
    "SYSTEM-EXECUTION-01",
    claim=("Acting has one store of rules, one registry of bindings and one tool gate: rules "
           "are found by id and status, bindings register and clear, a tool call is judged "
           "and carries its judgement, and a tool that does not exist is refused."),
    hypothesis=("A second rule store or binding registry, a tool call that ran unjudged, a "
                "fabricated result for an unknown tool, or a dead public method would each "
                "fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    try:
        from core.execution.operator_binding import BindingRegistry, OperatorBinding, get_binding_registry
        from core.learning.rule_store import EpistemicStatus, get_rule_store
        from core.tools.tool_registry import get_tool_registry
        RS, BR, TR = get_rule_store(), get_binding_registry(), get_tool_registry()

        print("\n== A. One authority each, and each is called ==")
        authority_audit(EV, check, system="rules", cls="RuleStore",
                        path="core/learning/rule_store.py", held=coord.learning.store, reached=RS)
        authority_audit(EV, check, system="bindings", cls="BindingRegistry",
                        path="core/execution/operator_binding.py", held=get_binding_registry(), reached=BR)
        check("the coordinator holds the one tool registry",
              getattr(coord, "tool_registry", None) is None or coord.tool_registry is TR)
        check("the probe registry type is the live one", isinstance(BR, BindingRegistry))

        print("\n== B. Rules: found by id and status, honest about unknowns ==")
        validated = await RS.load(EpistemicStatus.VALIDATED)
        check("validated rules load", isinstance(validated, list), f"{len(validated)} validated")
        EV.metric("validated_rules", len(validated), "count")
        if validated:
            one = validated[0]
            got = await RS.get(one.rule_id)
            check("a rule is found by its id", got is not None and got.rule_id == one.rule_id, one.rule_id)
            roots = await RS.evidence_roots(one.rule_id)
            check("its evidence roots are named", isinstance(roots, set), f"{len(roots)} root(s)")
        else:
            check("a rule is found by its id", False, "no validated rule in the store to look up")
            check("its evidence roots are named", False, "no validated rule in the store")
        check("an unknown rule id is None", await RS.get("rule_does_not_exist_qzx") is None)
        exe = await RS.executable_rules(DOMAIN)
        check("a domain with no rules has no executable rules", exe == [], f"{len(exe)}")

        print("\n== C. Bindings: registered, found, cleared ==")
        BR.register(DOMAIN, OperatorBinding(predicate="ISOPROBE", tool_name="read_file",
                                            parameters=lambda args: {"file_path": args[0]},
                                            observe=lambda: frozenset()))
        check("a binding is found by domain and predicate",
              BR.get(DOMAIN, "ISOPROBE") is not None and BR.get(DOMAIN, "ISOPROBE").tool_name == "read_file")
        check("an unknown predicate is None", BR.get(DOMAIN, "NOPE") is None)
        BR.clear(DOMAIN)
        check("clearing the domain removes it", BR.get(DOMAIN, "ISOPROBE") is None and BR.bindings_for(DOMAIN) == [])

        print("\n== D. Tools: judged, then done ==")
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("isoprobe file content qzx")
            path = f.name
        try:
            res = await TR.execute_tool("read_file", {"file_path": path})
            j = (res.metadata or {}).get("judgment") or {}
            check("a read passes the gate and carries its judgement",
                  res.success is True and j.get("verdict") == "allow", f"verdict={j.get('verdict')} law={j.get('law_number')}")
            check("and really read the file", "qzx" in str(res.output), str(res.output)[:60])
            bad = await TR.execute_tool("tool_that_does_not_exist_qzx", {})
            check("a tool that does not exist is refused, not invented",
                  bad.success is False and bad.output in (None, "", {}, []), f"error={str(bad.error)[:80]}")
            esc = await TR.execute_tool("read_file", {"file_path": "../../../../etc/passwd"})
            je = (esc.metadata or {}).get("judgment") or {}
            check("a path escape is refused at the gate", esc.success is False and je.get("verdict") == "block",
                  f"verdict={je.get('verdict')} law={je.get('law_number')}")
        finally:
            Path(path).unlink(missing_ok=True)
    finally:
        try:
            get_binding_registry().clear(DOMAIN)
        except Exception:
            pass
        await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-EXECUTION-01")
    EV.write()
    return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
