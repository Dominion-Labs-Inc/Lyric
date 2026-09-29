"""What an experiment's own learned domain holds, removed by the domain's id.

An experiment that practises in a domain of its own (a sandbox id it made, or
one no other experiment uses) removes everything that domain holds when it is
done: the operators bound there, its explorable registration, its rules with
everything that references them, the demonstrations it filed and what waits to
be induced. Removal is by that exact id, so nothing another run or another
session holds is touched.
"""
from __future__ import annotations


async def forget_domain(domain_id: str) -> None:
    from core.execution.operator_binding import get_binding_registry
    from core.learning.exploration import unregister_explorable_domain
    from core.learning.rule_store import get_rule_store

    get_binding_registry().clear(domain_id)
    unregister_explorable_domain(domain_id)
    store = get_rule_store()
    # The rules, through the store's own removal: it knows what references a
    # rule, removes it through the memory agent, and raises if any survive.
    await store.forget_domain(domain_id)
    # The demonstration store has no removal of its own.
    db = store.db()
    for table in ("operator_demonstrations", "operator_induction_pending"):
        await db.execute_query(f"DELETE FROM unified.{table} WHERE domain_id = $1", (domain_id,))
