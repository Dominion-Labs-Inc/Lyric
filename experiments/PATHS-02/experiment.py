#!/usr/bin/env python3
"""PATHS-02 — Lyric hands over; one door into the world; one conversation path.

The rule, in the user's words (2026-10-06): "It's supposed to be a learning
authority, which is the one learning path; then the coordinator, who is Lyric,
has that one conversation path." And: "the point is is it true or not." So Lyric
learns nothing itself: what it meets -- a telling, a percept, an act, a task's
outcome -- it hands to memory, whole; memory splits it by what it is about, holds
a person's part in their context, and takes a claim about the world to the one
door, the learning authority, which judges whether it is true
(docs/research/SEPARATION_MAP.md §11.2, §11.7).

Mostly STATIC, deliberately: a live probe can show that one path works, never
that a second does not exist. So the source is read with Python's own parser and
every call is classified by what it calls and on what.

  A. LYRIC PUTS NO CLAIM INTO KNOWLEDGE. In `autonomous_coordinator.py` -- Lyric
     and its Conversation -- no call reaches a door that puts a claim about the
     world or a person into knowledge: the learning authority's claim doors, the
     ingress, the person's context store, the belief store, the evidence
     producers, or memory's own writers of a person's context. Memory's intake
     (`take_in_*`) is how it hands over.
  B. THE CONVERSATION CALLS NO LEARNING. Inside `class Conversation`, nothing
     names the learning authority at all.
  C. ONE DOOR INTO THE WORLD. Outside the learning path itself (`core/learning`),
     the learning authority's claim doors are called only by memory, by the
     producers memory hands percepts to, and by Lyric's own reasoning conclusions
     (analogy discovery, entered as derived). The ingress's writes are called only
     by the learning authority, memory and the producers' ingestion.
  D. ONE CONVERSATION PATH. One Conversation class; a person's turn reaches
     `Conversation.understand` only through `_take_turn`; the one other caller is
     Lyric asking for its own work (the knowledge loop).
  E. MEMORY HANDS ON. Memory's intake reaches the world only through the
     learning authority's gate, and a person's context only through its own
     writers.
  F. LIVE, on the sandbox: one telling through the front door is handed to the
     pool, as the turn it was.

Run: ./venv_lyric/bin/python3 experiments/PATHS-02/experiment.py
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")

from experiments._evidence import RunRecord  # noqa: E402

CORE = ROOT / "core"
LYRIC = CORE / "agents" / "autonomous" / "autonomous_coordinator.py"
MEMORY = CORE / "agents" / "memory_agent.py"

EV = RunRecord(
    "PATHS-02",
    claim=("Lyric (the coordinator and its Conversation) puts no claim into knowledge: it hands what it meets to "
           "memory, memory splits it, and the learning authority is the one door into the world. The conversation "
           "calls no learning at all, and there is one conversation path."),
    hypothesis=("A call from Lyric to a claim door (the learning authority's, the ingress's, the person's context "
                "store's, the belief store's, an evidence producer, or memory's own person writers), any learning "
                "named inside Conversation, a claim door called from outside the learning path and memory, or a "
                "second way into Conversation.understand would each fail here."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# ── what the doors are, read from the code ───────────────────────────────────

#: The learning authority's methods that take a claim, a rule, a concept, a belief, an example or an experience
#: into knowledge. Its reads, its lifecycle, the triggers of its own induction work, and Lyric's bookkeeping of its
#: own decisions and gaps (`update_strategy_effectiveness`, `resolve_known_unknown`) put no claim about the world
#: or a person anywhere, and are not doors.
LEARNING_DOORS = {
    "admit_projection", "consider", "consider_envelope", "consider_many", "consider_rule", "contribute",
    "create_belief", "learn_concept", "learn_from_data", "learn_from_event", "learn_from_example",
    "learn_from_experience", "learn_from_feedback", "learn_patterns", "learn_pronunciations", "learn_said",
    "learn_usage", "learn_with_domain_context", "learn_word_classes", "observe_claim", "observe_method_outcome",
    "process_experience", "process_interaction", "record", "record_demonstration", "update_belief",
    "induce_category", "train_clause_classifier", "transfer_learning", "transfer_learning_across_domains",
}
#: Of those, the ones Lyric's own faculties use for its own state -- its competence in a domain, patterns over its
#: own memories, its own reasoning's record -- outside the learning path (section C).
SELF_STATE = {"create_belief", "update_belief", "learn_from_experience"}
#: The ingress's writes, the person's context store's, the belief store's.
INGRESS_WRITES = {"admit", "admit_relation", "admit_conditional", "remember_told"}
SCOPED_WRITES = {"observe", "observe_claim"}
BELIEF_WRITES = {"create_belief", "update_belief", "observe_claim", "flush_belief"}
#: Memory's own writers of a person's context and of the world's lessons: called by memory's intake, never by Lyric.
MEMORY_WRITERS = {"hold_for_person", "hold_rule_for_person", "hold_demonstration", "hold_scoped_relation",
                  "hold_scoped_belief", "hold_belief_about_speaker", "share_lesson", "hold_conditional"}


def producers() -> set:
    from core.domain import evidence_producers
    return {name for name, value in inspect.getmembers(evidence_producers, inspect.iscoroutinefunction)
            if name.startswith("submit_")}


def receiver_kind(func: ast.AST) -> str:
    """What a call is made on, by how the code names it: the learning authority, the ingress, the person's context
    store, the belief store, memory, or something else."""
    if not isinstance(func, ast.Attribute):
        return ""
    text = ast.unparse(func.value)
    if any(k in text for k in ("get_learning_authority()", "get_unified_learning_system()", "self.learning",
                               "learning_system", "authority")) and "intent" not in text:
        return "learning"
    if "ingress" in text:
        return "ingress"
    if "scoped" in text:
        return "scoped"
    if any(k in text for k in ("get_uncertainty_system()", "get_bayesian_uncertainty()", "uncertainty")):
        return "beliefs"
    if "memory" in text or text in ("agent", "self.memory"):
        return "memory"
    return ""


def door_of(call: ast.Call, submitters: set) -> str:
    """The door a call reaches, said, or "" when it reaches none."""
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    if name in submitters:
        return f"evidence producer {name}"
    kind = receiver_kind(func)
    if kind == "learning" and name in LEARNING_DOORS:
        return f"learning authority .{name}"
    if kind == "ingress" and name in INGRESS_WRITES:
        return f"ingress .{name}"
    if kind == "scoped" and name in SCOPED_WRITES:
        return f"person's context store .{name}"
    if kind == "beliefs" and name in BELIEF_WRITES:
        return f"belief store .{name}"
    if kind == "memory" and name in MEMORY_WRITERS:
        return f"memory's own writer .{name}"
    return ""


def doors_called(path: Path, submitters: set, within=None):
    """(line, door, the call) for every call in `path` (or within one node of it) that reaches a door."""
    tree = within if within is not None else ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            door = door_of(node, submitters)
            if door:
                found.append((node.lineno, door, ast.unparse(node.func)))
    return sorted(found)


def class_node(path: Path, name: str) -> ast.ClassDef:
    return next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == name)


def core_files():
    for path in CORE.rglob("*.py"):
        if "_disabled" not in path.parts:
            yield path


def callers(predicate, submitters: set):
    """{file: [(line, door)]} for every core file with a call the predicate keeps."""
    out = {}
    for path in core_files():
        try:
            calls = doors_called(path, submitters)
        except SyntaxError:
            continue
        kept = [(line, door) for line, door, _ in calls if predicate(door)]
        if kept:
            out[path.relative_to(ROOT).as_posix()] = kept
    return out


def writers_of(table: str) -> set:
    """Every core module whose SQL inserts, updates or deletes `unified.<table>`, comments aside."""
    import re
    pattern = re.compile(rf"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+unified\.{table}\b", re.I)
    return {path.relative_to(ROOT).as_posix() for path in core_files()
            if any(pattern.search(line) for line in path.read_text(errors="ignore").splitlines()
                   if not line.strip().startswith("#"))}


def functions_calling(path: Path, method: str):
    """The names of the functions in `path` that call `.method(`."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == method and inner is not node):
                    names.add(node.name)
    return names


async def main() -> int:
    submitters = producers()

    print("\n== A. Lyric puts no claim into knowledge ==")
    found = doors_called(LYRIC, submitters)
    check("no call in Lyric reaches a claim door", not found,
          "; ".join(f":{line} {door} ({call})" for line, door, call in found[:8]))
    handed = sorted({n.func.attr for n in ast.walk(ast.parse(LYRIC.read_text()))
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr.startswith("take_")})
    check("what Lyric meets it hands to memory's intake", len(handed) >= 8, ", ".join(handed))

    print("\n== B. The conversation calls no learning ==")
    conversation = class_node(LYRIC, "Conversation")
    named = sorted({(n.lineno, ast.unparse(n)) for n in ast.walk(conversation)
                    if (isinstance(n, ast.Attribute) and n.attr in ("learning", "_learning"))
                    or (isinstance(n, ast.Name) and n.id in ("get_learning_authority", "get_unified_learning_system",
                                                             "TeachingPass"))})
    check("nothing inside Conversation names the learning authority", not named,
          "; ".join(f":{line} {text}" for line, text in named[:6]))

    print("\n== C. One door into the world ==")
    # `core/quantum` is not read: the quantum subsystem is disabled and its learning bridge is never started
    # (`core/main.py`, "Quantum learning bridge not started").
    live = lambda f: not f.startswith("core/quantum/")
    claim_callers = callers(lambda door: door.startswith("learning authority")
                            and door.split(".")[-1] not in SELF_STATE, submitters)
    outside = {f: c for f, c in claim_callers.items() if live(f) and not f.startswith("core/learning/")
               and f not in {"core/agents/memory_agent.py", "core/domain/evidence_producers.py",
                             "core/reasoning/analogy_discovery.py", "core/integration/universal_domain_master.py"}}
    check("outside the learning path, a claim door is called only by memory, the producers memory hands percepts "
          "to, and Lyric's own reasoning conclusions over what it holds (analogy discovery's concepts, the domain "
          "master's cross-domain projections, both entered as derived candidates)",
          not outside, "; ".join(f"{f}:{c[0][0]} {c[0][1]}" for f, c in list(outside.items())[:6]))
    self_state = {f: sorted({d for _, d in c}) for f, c in callers(
        lambda door: door.startswith("learning authority") and door.split(".")[-1] in SELF_STATE,
        submitters).items() if live(f) and not f.startswith("core/learning/")}
    check("outside the learning path, a belief is created only for Lyric's own state: its competence in a domain "
          "(the domain master), patterns over its own memories (abstraction), and its own reasoning's record",
          set(self_state) <= {"core/integration/universal_domain_master.py",
                              "core/reasoning/hierarchical_abstraction.py",
                              "core/reasoning/abstract_reasoning_engine.py"}, f"{self_state}")
    ingress_callers = callers(lambda door: door.startswith("ingress"), submitters)
    check("the ingress's writes are called only by the learning path and memory",
          {f for f in ingress_callers if not f.startswith("core/learning/")} <= {"core/agents/memory_agent.py"},
          f"{sorted(ingress_callers)}")
    producer_callers = callers(lambda door: door.startswith("evidence producer"), submitters)
    check("the evidence producers are called only by memory and the learning path",
          {f for f in producer_callers if not f.startswith("core/learning/")}
          <= {"core/agents/memory_agent.py", "core/domain/evidence_producers.py"}, f"{sorted(producer_callers)}")
    scoped_callers = callers(lambda door: door.startswith("person's context store"), submitters)
    check("only memory writes to the person's context store",
          set(scoped_callers) <= {"core/agents/memory_agent.py"}, f"{sorted(scoped_callers)}")
    tables = {table: writers_of(table) for table in ("scoped_concept_relations", "scoped_beliefs", "user_beliefs",
                                                      "work_authorizations")}
    check("a person's and an organization's context tables, and who is authorized for which, have one writer, "
          "memory",
          all(w <= {"core/agents/memory_agent.py"} for w in tables.values()),
          f"{ {t: sorted(w) for t, w in tables.items()} }")

    print("\n== D. One conversation path ==")
    from core.agents.autonomous.autonomous_coordinator import Conversation
    import core.semantics.conversation as conversation_module
    check("there is one Conversation class", conversation_module.Conversation is Conversation)
    entries = functions_calling(LYRIC, "understand") - {"understand"}
    check("a person's turn reaches Conversation.understand only through _take_turn, and Lyric's own asking "
          "through the knowledge loop",
          entries <= {"_take_turn", "_answer_from_what_is_held", "_answer_via_knowledge_loop"}, f"{sorted(entries)}")
    held = functions_calling(LYRIC, "_answer_from_what_is_held")
    check("the answer from what is held is reached only from the turn", held == {"_take_turn"}, f"{sorted(held)}")

    print("\n== E. Memory hands on ==")
    intake = [n for n in ast.walk(class_node(MEMORY, "MemoryAgent"))
              if isinstance(n, ast.AsyncFunctionDef) and (n.name.startswith("take_in_")
                                                         or n.name == "take_outcome_to_learning")]
    reached = {}
    for method in intake:
        for node in ast.walk(method):
            if isinstance(node, ast.Call):
                door = door_of(node, submitters)
                if door:
                    reached.setdefault(method.name, set()).add(door)
    world = {m: sorted(d) for m, d in reached.items()}
    check("memory's intake reaches the world only through the learning authority's gate, a person's context only "
          "through its own writers, and percepts through their producers",
          all(door.startswith(("learning authority .consider", "learning authority .learn_with_domain_context",
                               "memory's own writer", "evidence producer", "ingress .remember_told"))
              for doors in reached.values() for door in doors), f"{world}")
    EV.metric("memory_intake_methods", len(intake), "count", ", ".join(sorted(m.name for m in intake)))

    print("\n== F. Live: a telling through the front door is handed to the pool ==")
    # A TURN IS PART OF ITS PURSUIT: told through the front door, it is a part of the request's pursuit memory, and
    # that memory waits in the pool once the pursuit concludes (`MemoryAgent.remember_experience`).
    from experiments._isolation import boot, db, shutdown
    system, coord = await boot()
    session = f"PATHS-02-{uuid.uuid4().hex[:6]}"
    name = f"Plorvex{uuid.uuid4().hex[:5]}"
    pursuit = None
    try:
        reply = await coord.handle_user_request(f"{name} is a gadget.", source="api",
                                                metadata={"session_id": session, "actor_identity": session})
        pursuit = reply.get("pursuit_memory_id")
        from core.memory import get_memory_agent
        await (await get_memory_agent()).drain_writes()
        held = await db().execute_query(
            "SELECT count(*) AS n FROM memory_hot.memory_hot WHERE memory_id = $1 AND memory_hot::text ILIKE $2",
            (pursuit, f"%{name}%"), fetch_one=True)
        check("the turn is a part of its pursuit's memory", pursuit and int(held["n"]) == 1,
              f"pursuit {pursuit}; reply {str(reply.get('answer') or reply)[:100]!r}")
        pooled = await db().execute_query(
            "SELECT count(*) AS n FROM unified.experience_pool WHERE memory_id = $1", (pursuit,), fetch_one=True)
        check("the pursuit, concluded, waits in the pool", int(pooled["n"]) == 1, f"{pooled['n']} pool rows")
    finally:
        await db().execute_query("DELETE FROM unified.experience_pool WHERE memory_id = $1", (pursuit,))
        for table, column in (("scoped_concept_relations", "scope_actor"), ("scoped_beliefs", "scope_actor")):
            await db().execute_query(f"DELETE FROM unified.{table} WHERE {column} = $1", (session,))
        await db().execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1 OR content ILIKE $2",
                                 (pursuit, f"%{name}%"))
        await shutdown(system)

    passed = sum(results)
    print(f"\n==== PATHS-02: {passed}/{len(results)} checks passed ====")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
