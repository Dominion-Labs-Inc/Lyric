#!/usr/bin/env python3
"""Where staging and production would send every statement the substrate's code runs.

Outside development the stores are kept in separate databases (runtime, the model, user context, and the
learning store). The database manager sends each statement to the database
its tables live in, and refuses what it cannot place. Against the model -- a frozen release there -- it answers
reads, checks table creation, and refuses every other write. This reads the code, finds every statement and raw
connection, and reports what staging and production would do with it:

  placed       the tables decide, or the store is named and agrees
  needs store  a per-owner table or a statement with no table, and no store is named
  refused      two stores in one statement, a table no store holds, or a tool's table
  unread       the statement is built at run time, so only running it can say

and, of the placed statements on the model, which a frozen release refuses (writes) and which it checks
(creation). A refused write is fine only where the code never runs it while serving.

A statement is read when it is written in the call, or in a name bound once to a string in the same
function or module. Tools (`core/tools/`) are reported apart: they serve the substrate, people and other
systems, and are not routed into the substrate's stores.

It also checks that the memory agent is the only writer of the substrate's memory. Every string in `core/`
that holds a statement writing a memory table is found, whatever runs it -- the manager, a raw connection --
and one outside the memory agent fails the run (exit 1). A write whose table is named only at run time fails
too, unless it was read and found not to be memory (`NOT_MEMORY`). Scripts that write memory directly are
listed, not failed: they are run by hand, not by the substrate. And every hand-off of a memory to the memory agent
must say where it came from (`origin=`) and never name its owner: the memory agent decides whose it is.

Run:  ./venv_lyric/bin/python3 scripts/separation_map.py [--all]
"""
from __future__ import annotations

import ast
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.database.postgres_config import (  # noqa: E402
    PER_OWNER_TABLES, STORE_TABLES, StoreRoutingError, statement_kind, store_for_statement)

CALLS = {"execute_query", "query", "execute_many"}
RAW = {"get_connection"}
SKIP_DIRS = {"__pycache__", ".cache", "data", "_disabled"}


def _text(node, bound):
    """The SQL a node holds, when it can be read without running anything."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # A filled-in part may be the table's name, so it is kept as a mark `scan` can see.
        return "".join(v.value if isinstance(v, ast.Constant) else " {} " for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left, bound), _text(node.right, bound)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.Name) and node.id in bound:
        return bound[node.id]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.attr in bound:
        return bound[node.attr]
    return None


def _bindings(scope, outer):
    """Names bound exactly once to readable SQL in this scope (module constants included)."""
    counts, texts = Counter(), {}
    for node in ast.walk(scope):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            name = target.id if isinstance(target, ast.Name) else (
                target.attr if isinstance(target, ast.Attribute) else None)
            if name:
                counts[name] += 1
                text = _text(node.value, outer)
                if text is not None:
                    texts[name] = text
    bound = dict(outer)
    bound.update({n: t for n, t in texts.items() if counts[n] == 1})
    return bound


def _flag(call, name):
    for kw in call.keywords:
        if kw.arg == name:
            return isinstance(kw.value, ast.Constant) and kw.value.value is True
    return False


def _store(call):
    for kw in call.keywords:
        if kw.arg == "store":
            return kw.value.value if isinstance(kw.value, ast.Constant) else "<named>"
    return None


def scan(path, rel):
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    except SyntaxError:
        return []
    module_bound = _bindings(tree, {})
    out = []
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    seen = set()
    for scope in scopes + [tree]:
        bound = _bindings(scope, module_bound) if scope is not tree else module_bound
        for call in ast.walk(scope):
            if not isinstance(call, ast.Call) or id(call) in seen:
                continue
            fn = call.func
            attr = fn.attr if isinstance(fn, ast.Attribute) else None
            if attr not in CALLS | RAW:
                continue
            seen.add(id(call))
            store = _store(call)
            if attr in RAW:
                out.append((rel, call.lineno, "raw", "placed" if store else "needs store", store or ""))
                continue
            if not call.args:
                continue
            sql = _text(call.args[0], bound)
            if sql is None:
                out.append((rel, call.lineno, attr, "unread", ""))
                continue
            schema = ("memory_cold" if _flag(call, "use_cold_tier")
                      else "memory_hot" if _flag(call, "use_hot_tier") else "unified")
            try:
                placed = store_for_statement(sql, search_schema=schema,
                                             store=None if store in (None, "<named>") else store)
                kind = statement_kind(sql)
                out.append((rel, call.lineno, attr, "placed", placed
                            + (" (frozen: refused)" if placed == "model" and kind == "write" else
                               " (frozen: checked)" if placed == "model" and kind == "schema" else "")))
            except StoreRoutingError as e:
                reason = str(e)
                if "touches no table" in reason and "{}" in sql:
                    out.append((rel, call.lineno, attr, "unread", "the table is filled in at run time"))
                elif store == "<named>" and ("name the store" in reason):
                    out.append((rel, call.lineno, attr, "placed", "<named>"))
                elif "name the store" in reason:
                    out.append((rel, call.lineno, attr, "needs store", reason[:90]))
                else:
                    out.append((rel, call.lineno, attr, "refused", reason[:110]))
    return out


#: The memory agent, the only writer of the substrate's memory, and the storage only it uses.
MEMORY_AGENT = ("core/agents/memory_agent.py", "core/memory/")

#: Writes outside the memory agent whose table is named only at run time, each read and found not to be memory.
NOT_MEMORY = {
    "core/learning/drift_monitoring/data_loaders.py": "drift samples: a table per source and data type",
}

#: Every table of the substrate's memory: the model's, each person's context, and the per-owner tables.
MEMORY_TABLES = (frozenset(STORE_TABLES["model"]) | frozenset(STORE_TABLES["user_context"])
                 | frozenset(t for t, store in PER_OWNER_TABLES.items() if store == "model"))

_IS_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\S+\s+(AS\s+\w+\s+)?SET|DELETE\s+FROM|TRUNCATE)\b", re.I)
_WRITE_TARGET = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|MERGE\s+INTO)\s+(?:ONLY\s+)?"
    r"(\{[^}]*\}|[A-Za-z_\"][\w.\"]*)", re.I)


def _memory_table(name):
    """`name` as a memory table, or None. An unqualified name resolves as the search path does."""
    name = name.replace('"', "").lower()
    candidates = [name] if "." in name else [f"{schema}.{name}"
                                             for schema in ("unified", "memory_hot", "memory_cold")]
    return next((c for c in candidates if c in MEMORY_TABLES), None)


def memory_writes(path, rel):
    """Every string in a module holding a statement that writes a memory table, whatever runs it, as
    (file, line, table). A table named only at run time is reported as its expression, in braces."""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    except SyntaxError:
        return []
    inside = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
              for part in ast.walk(node) if part is not node}
    out = set()
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant)
                           else "{" + ast.unparse(v.value) + "}" for v in node.values)
        else:
            continue
        if not _IS_WRITE.search(text):
            continue
        for match in _WRITE_TARGET.finditer(text):
            target = match.group(1)
            table = target if target.startswith("{") else _memory_table(target)
            if table:
                out.add((rel, node.lineno, table))
    return sorted(out)


#: The memory agent's doors for a memory: every call must say where the memory came from (`origin=`) and never
#: whose it is (`user_id=`); the memory agent decides that.
HAND_OFFS = {"store_memory", "enqueue_memory"}

#: The doors a perception comes in by, and what each must be told: whose image `see` is looking at, whose
#: recording `hear` is listening to and whose moment `perceive_moment` takes in (`actor_identity=`, None for the
#: substrate's own), and where a perception came from (`origin=`). `read` is the same door for a document; its
#: name is every file object's too, so it cannot be found by name here.
PERCEPTION_DOORS = {"see": "actor_identity", "hear": "actor_identity", "take_in": "actor_identity",
                    "perceive_moment": "actor_identity", "process_input": "origin",
                    "admit_percept": "origin", "note_percept": "origin", "remember_met": "origin"}


def hand_offs_without_origin(path, rel):
    """Calls of a memory hand-off that say no origin, or name an owner, and calls of a perception door that do not
    say whose the perception is, as (file, line, call, what is wrong)."""
    try:
        tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    except SyntaxError:
        return []
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        keywords = {k.arg for k in node.keywords}
        call = node.func.attr
        if call in HAND_OFFS:
            if "user_id" in keywords:
                out.append((rel, node.lineno, call, "names an owner (user_id)"))
            if "origin" not in keywords and None not in keywords:
                out.append((rel, node.lineno, call, "says no origin"))
        elif call in PERCEPTION_DOORS and PERCEPTION_DOORS[call] not in keywords and None not in keywords:
            out.append((rel, node.lineno, call, f"says not whose it is ({PERCEPTION_DOORS[call]})"))
    return out


def hand_offs_that_say_no_origin():
    """Every hand-off in `core/` that says no origin or names an owner."""
    found = []
    for dirpath, dirs, files in os.walk(os.path.join(ROOT, "core")):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(".py"):
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, ROOT)
                # The memory agent's own code calls its storage backend, whose
                # method has the same name; those are not hand-offs.
                if any(rel == m or (m.endswith("/") and rel.startswith(m)) for m in MEMORY_AGENT):
                    continue
                found += hand_offs_without_origin(path, rel)
    return found


def memory_written_outside_the_agent():
    """Writes of memory in `core/` outside the memory agent, and in `scripts/`: (outside, scripts)."""
    outside, scripts = [], []
    for top, into in (("core", outside), ("scripts", scripts)):
        for dirpath, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(dirpath, fn)
                rel = os.path.relpath(path, ROOT)
                if rel.startswith("core/tools/") or any(
                        rel == m or (m.endswith("/") and rel.startswith(m)) for m in MEMORY_AGENT):
                    continue
                for row in memory_writes(path, rel):
                    if row[2].startswith("{") and rel in NOT_MEMORY:
                        continue
                    into.append(row)
    return outside, scripts


def main() -> int:
    show_all = "--all" in sys.argv
    rows = []
    for dirpath, dirs, files in os.walk(os.path.join(ROOT, "core")):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(".py"):
                path = os.path.join(dirpath, fn)
                rows.extend(scan(path, os.path.relpath(path, ROOT)))
    substrate = [r for r in rows if not r[0].startswith("core/tools/")]
    tools = [r for r in rows if r[0].startswith("core/tools/")]
    for label, group in (("substrate", substrate), ("tools (not routed)", tools)):
        tally = Counter(r[3] for r in group)
        print(f"{label}: {len(group)} call sites -- " +
              ", ".join(f"{k} {tally[k]}" for k in ("placed", "needs store", "refused", "unread")))
    frozen = Counter(r[4].split("(frozen: ")[1].rstrip(")") for r in substrate
                     if r[3] == "placed" and "(frozen: " in r[4])
    print(f"of the placed, on the model: a frozen release refuses {frozen['refused']} (writes) and checks "
          f"{frozen['checked']} (creation)")
    print()
    for kind in ("refused", "needs store", "unread") + (("placed",) if show_all else ()):
        hits = [r for r in substrate if r[3] == kind]
        if not hits:
            continue
        print(f"== {kind} ({len(hits)})")
        by_file = defaultdict(list)
        for r in hits:
            by_file[r[0]].append(r)
        for f in sorted(by_file):
            for r in by_file[f]:
                print(f"   {f}:{r[1]} {r[2]} {r[4]}")

    outside, scripts = memory_written_outside_the_agent()
    print()
    print(f"memory written outside the memory agent: {len(outside)}")
    for f, line, table in outside:
        print(f"   {f}:{line} {table}")
    print(f"scripts that write memory directly (run by hand, not failed): {len(scripts)}")
    for f, line, table in scripts:
        print(f"   {f}:{line} {table}")
    unsaid = hand_offs_that_say_no_origin()
    print(f"memory handed over, or a perception taken in, without saying where it came from, or naming its "
          f"owner: {len(unsaid)}")
    for f, line, call, what in unsaid:
        print(f"   {f}:{line} {call} {what}")
    return 1 if outside or unsaid else 0


if __name__ == "__main__":
    sys.exit(main())
