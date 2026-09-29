#!/usr/bin/env python3
"""Where English lives in the code, and who depends on the language modules.

The re-check for `docs/research/SHAPES_CHANGE_MAP.md`. Moving sentence and word shapes into
memory is finished only when the language knowledge written into the code is gone and nothing
calls what was removed; this prints both, so every build step can be checked against the map
rather than against memory of it.

  1. IMPORTERS  every file that imports from `core.semantics`, per module and symbol, including
                imports made inside functions (AST, not text search)
  2. READER     every method of `SentenceReader` called from outside the reader, with the
                enclosing function of each call
  3. ENGLISH    every word list (a set/list/tuple/dict literal holding at least 4 English-shaped
                strings, one of them a core English word) and every regex holding an alternation
                of core English words, across `core/`

Run:  ./venv_lyric/bin/python3 scripts/language_map.py [--section importers|reader|english]
"""
from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
CODE_ROOTS = ("core", "scripts", "tests", "experiments", "demos")

#: Core English words: a hit on one of these is what marks a list or a pattern as English
#: rather than as identifiers that happen to be lowercase.
CORE_ENGLISH = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "am", "been", "being", "i", "you",
    "he", "she", "it", "we", "they", "my", "your", "his", "her", "its", "our", "their", "this",
    "that", "these", "those", "what", "who", "whom", "whose", "where", "when", "why", "how",
    "which", "and", "or", "but", "not", "no", "nor", "if", "then", "because", "so", "of", "in",
    "on", "at", "to", "from", "with", "by", "for", "has", "have", "had", "do", "does", "did",
    "can", "could", "will", "would", "should", "may", "might", "must", "all", "every", "some",
    "any", "many", "most", "few", "yes", "please", "tell", "explain", "define"})
_ENGLISH_SHAPED = re.compile(r"^[a-z][a-z']{0,20}( [a-z][a-z']{0,20}){0,3}$")
_ALTERNATION = re.compile(r"(?<![\\\w])([a-z]{2,})\|([a-z]{2,})")


def _python_files(roots=CODE_ROOTS) -> List[Path]:
    files = [p for r in roots for p in (ROOT / r).rglob("*.py") if "__pycache__" not in p.parts]
    return files + sorted(ROOT.glob("*.py"))


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return None


def _enclosing(tree, line: int) -> str:
    best, best_start = "<module>", -1

    def walk(node, prefix):
        nonlocal best, best_start
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                if child.lineno <= line <= (child.end_lineno or child.lineno) \
                        and child.lineno >= best_start:
                    best, best_start = name, child.lineno
                walk(child, name)
            else:
                walk(child, prefix)

    walk(tree, "")
    return best


def importers() -> Dict[str, Dict[str, List[str]]]:
    """module -> symbol -> ["file:line", ...] for everything imported from core.semantics."""
    out: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for path in _python_files():
        tree = _parse(path)
        if tree is None:
            continue
        aliases: Dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                if node.level:
                    package = ".".join(Path(_rel(path)).with_suffix("").parts[:-node.level])
                    module = f"{package}.{module}"
                if module.startswith("core.semantics"):
                    for name in node.names:
                        out[module][name.name].append(f"{_rel(path)}:{node.lineno}")
                        if module == "core.semantics":
                            aliases[name.asname or name.name] = f"core.semantics.{name.name}"
            elif isinstance(node, ast.Import):
                for name in node.names:
                    if name.name.startswith("core.semantics"):
                        aliases[name.asname or name.name] = name.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id in aliases:
                out[aliases[node.value.id]][node.attr].append(f"{_rel(path)}:{node.lineno}")
    return out


def reader_calls() -> Dict[str, List[Tuple[str, str]]]:
    """SentenceReader method -> [(file:line, enclosing function)] for calls from outside it."""
    reader = ROOT / "core/semantics/sentence_reader.py"
    tree = ast.parse(reader.read_text())
    methods = {n.name for c in tree.body if isinstance(c, ast.ClassDef) and c.name == "SentenceReader"
               for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for path in _python_files():
        if path == reader:
            continue
        text = path.read_text(errors="replace")
        # Only files that can reach the reader: it is imported, or a formalizer that holds it
        # is. Name matching alone would count every class that happens to have a `_normalize`.
        if "SentenceReader" not in text and "DeterministicExtractor" not in text:
            continue
        ftree = _parse(path)
        if ftree is None:
            continue
        for node in ast.walk(ftree):
            if isinstance(node, ast.Attribute) and node.attr in methods:
                out[node.attr].append((f"{_rel(path)}:{node.lineno}", _enclosing(ftree, node.lineno)))
    return out


def english_in_core() -> Dict[str, List[Tuple[str, int, str, int, List[str]]]]:
    """file -> [(kind, line, name, size, core English words in it)]."""
    out: Dict[str, List[Tuple[str, int, str, int, List[str]]]] = defaultdict(list)
    for path in sorted((ROOT / "core").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                name = getattr(target, "id", getattr(target, "attr", "?"))
                words = {c.value for c in ast.walk(node.value)
                         if isinstance(c, ast.Constant) and isinstance(c.value, str)
                         and _ENGLISH_SHAPED.match(c.value)}
                core = sorted(w for w in words if w in CORE_ENGLISH
                              or any(t in CORE_ENGLISH for t in w.split()))
                if len(words) >= 4 and core:
                    out[_rel(path)].append(("list", node.lineno, name, len(words), core[:6]))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" \
                    and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    pattern = first.value
                elif isinstance(first, ast.JoinedStr):
                    pattern = "".join(v.value for v in first.values if isinstance(v, ast.Constant))
                else:
                    continue
                alternatives = set(sum(_ALTERNATION.findall(pattern.lower()), ()))
                core = sorted(alternatives & CORE_ENGLISH)
                if core:
                    out[_rel(path)].append(("regex", node.lineno, node.func.attr,
                                            len(alternatives), core[:6]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--section", choices=("importers", "reader", "english"))
    args = parser.parse_args()

    if args.section in (None, "importers"):
        print("== 1. IMPORTERS of core.semantics")
        for module, symbols in sorted(importers().items()):
            print(f"\n{module}")
            for symbol, where in sorted(symbols.items()):
                live = [w for w in where if not w.startswith(("tests/", "experiments/"))]
                print(f"  {symbol}: {len(live)} live, {len(where) - len(live)} test/experiment"
                      + (f"  {live}" if live else ""))
    if args.section in (None, "reader"):
        print("\n== 2. READER methods called from outside the reader")
        for method, calls in sorted(reader_calls().items()):
            print(f"\n{method}: {len(calls)}")
            for where, function in calls:
                print(f"  {where}  [{function}]")
    if args.section in (None, "english"):
        print("\n== 3. ENGLISH word lists and patterns in core/")
        found = english_in_core()
        for path, items in sorted(found.items(), key=lambda kv: -len(kv[1])):
            print(f"\n{path}: {len(items)}")
            for kind, line, name, size, core in items:
                print(f"  {kind:<5} {line:>6} {name:<28} n={size:<4} {core}")
        print(f"\nTOTAL {sum(len(v) for v in found.values())} in {len(found)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
