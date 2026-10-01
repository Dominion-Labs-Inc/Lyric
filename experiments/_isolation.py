"""Shared harness for the SYSTEM-* experiments: one system at a time, on the live
substrate, through its own authority.

Every SYSTEM-* experiment asks three things of one faculty:

  ONE AUTHORITY   the instance the coordinator holds IS the one the accessor
                  returns, and the class is constructed in one place.
  IT WORKS        the public contract, exercised on the live substrate with real
                  writes and real reads; a wrong or unknown input is refused,
                  never answered with a fabricated success; everything written
                  is removed by id.
  IT IS CALLED    every public method is reached by something in `core/`, and
                  none is a stub body. Reported by name so the decision can be
                  made — nothing is removed here.

THREE KINDS OF RESULT, KEPT APART. A run used to fold all of these into one
"N/M checks passed", which read an unwired method as the system failing:

  BEHAVIOUR     a check of what the system DOES through its real path. These
                alone decide whether the run passed.
  WIRING        a public method nothing in `core/` calls -- split into ones only
                experiments or tests exercise (a capability that exists but is
                not wired into the substrate) and ones nothing calls at all.
                The SYSTEM-* audits are not counted as callers.
  COMPLETENESS  a public method whose body is not an implementation: it raises
                NotImplementedError, returns a literal (which would pass as a
                result if anything called it), or is empty.

Wiring and completeness are FINDINGS: recorded by name, counted, printed apart
from behaviour, and never scored as a failed check.

Each system is tested in isolation -- learning, domain, memory, reasoning, all the
others -- to make sure each performs exactly as it should and has proper callers.
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import sys
from pathlib import Path

# EXPERIMENTS RUN IN THE SANDBOX. `lyric_db` is the main model; testing and
# development use `lyric_dev`, unless the run names a database itself
# (`POSTGRES_DATABASE=... python3 experiments/...`). The same rule as
# tests/conftest.py, and `boot` checks it against the server.
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── the live substrate ───────────────────────────────────────────────────────

async def boot():
    """Start the whole system, quietly, and return (system, coordinator)."""
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
    await db().assert_database_identity(os.environ["POSTGRES_DATABASE"])
    return system, system.autonomous_coordinator


async def shutdown(system) -> None:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await system.shutdown()


def db():
    from core.database import get_database_manager
    return get_database_manager()


# ── static reading of one authority ──────────────────────────────────────────

_CORE = ROOT / "core"


def _core_sources() -> Dict[Path, str]:
    out: Dict[Path, str] = {}
    for p in _CORE.rglob("*.py"):
        s = str(p)
        if "_disabled" in s or "__pycache__" in s:
            continue
        try:
            out[p] = p.read_text(errors="ignore")
        except OSError:
            continue
    return out


def _class_node(path: Path, cls: str) -> Optional[ast.ClassDef]:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return node
    return None


def public_methods(path: Path, cls: str) -> List[ast.AST]:
    node = _class_node(path, cls)
    if node is None:
        return []
    return [m for m in node.body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not m.name.startswith("_")]


def body_kind(fn: ast.AST) -> Optional[str]:
    """What a public method's body IS when it is not an implementation --
    'not_implemented' (raises NotImplementedError), 'constant' (returns a
    literal other than None), 'empty' (`pass`, `...`, bare `return` or
    `return None`) -- or None for a real body. Read after the docstring."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) != 1:
        return None if body else "empty"
    stmt = body[0]
    if isinstance(stmt, ast.Raise) and "NotImplemented" in ast.dump(stmt):
        return "not_implemented"
    if isinstance(stmt, ast.Pass):
        return "empty"
    if isinstance(stmt, ast.Expr) and isinstance(getattr(stmt, "value", None), ast.Constant) \
            and stmt.value.value is Ellipsis:
        return "empty"
    if isinstance(stmt, ast.Return):
        if stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None):
            return "empty"
        if isinstance(stmt.value, ast.Constant):
            return "constant"
    return None


def construction_sites(cls: str, sources: Dict[Path, str]) -> List[str]:
    """Every place in core/ that CALLS the class — real constructions only, read
    from the AST so a usage docstring does not count."""
    sites: List[str] = []
    for path, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name == cls:
                    sites.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return sorted(sites)


def _uses(name: str, text: str, *, skip_def: bool) -> int:
    """How many times `name` is USED in `text`: called, referenced as an
    attribute, or named in a string (a tier registered by name) -- never its own
    `def` line."""
    pat = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")
    n = 0
    for line in text.splitlines():
        if not pat.search(line):
            continue
        stripped = line.strip()
        if skip_def and re.match(r"(async\s+)?def\s+" + re.escape(name) + r"\b", stripped):
            continue
        n += len(pat.findall(line))
    return n


def reach(methods: Iterable[str], own_path: Path, sources: Dict[Path, str]) -> Dict[str, List[str]]:
    """Split public methods by who uses them:
        dead      -- nothing in core/ names them, not even their own file;
        internal  -- only their own file uses them (public in name only)."""
    own = own_path.resolve()
    own_text = sources.get(own_path) or next((t for p, t in sources.items() if p.resolve() == own), "")
    dead, internal = [], []
    for name in methods:
        outside = sum(_uses(name, t, skip_def=False) for p, t in sources.items() if p.resolve() != own)
        if outside:
            continue
        inside = _uses(name, own_text, skip_def=True)
        (internal if inside else dead).append(name)
    return {"dead": dead, "internal": internal}


def unreached(methods: Iterable[str], own_path: Path, sources: Dict[Path, str]) -> List[str]:
    """Public methods nothing in core/ uses at all -- dead (see `reach`)."""
    return reach(methods, own_path, sources)["dead"]


def _outside_core_sources() -> Dict[Path, str]:
    """experiments/ and tests/, WITHOUT the SYSTEM-* audits and this harness --
    an audit naming a method in order to test it is not a caller of it."""
    out: Dict[Path, str] = {}
    for folder in (ROOT / "experiments", ROOT / "tests"):
        for p in folder.rglob("*.py"):
            rel = str(p.relative_to(ROOT))
            if rel.startswith("experiments/SYSTEM-") or p.name == "_isolation.py" \
                    or "__pycache__" in rel:
                continue
            try:
                out[p] = p.read_text(errors="ignore")
            except OSError:
                continue
    return out


def split_uncalled(names: Iterable[str]) -> Dict[str, Any]:
    """Uncalled-in-core methods, split: those only experiments/tests exercise
    ({name: [where]}) and those nothing calls at all."""
    outside = _outside_core_sources()
    exercised: Dict[str, List[str]] = {}
    nothing: List[str] = []
    for name in names:
        where = sorted(str(p.relative_to(ROOT)) for p, t in outside.items()
                       if _uses(name, t, skip_def=True))
        if where:
            exercised[name] = where
        else:
            nothing.append(name)
    return {"experiments_only": exercised, "nothing": nothing}


#: This run's wiring and completeness findings, by category -> [(system, name)].
FINDINGS: Dict[str, List[tuple]] = {
    "experiments_only": [], "uncalled": [],
    "not_implemented": [], "constant": [], "empty": []}

_FINDING_LABEL = {
    "experiments_only": "wiring: exercised only by experiments/tests",
    "uncalled": "wiring: called by nothing",
    "not_implemented": "completeness: raises NotImplementedError",
    "constant": "completeness: returns a literal",
    "empty": "completeness: empty body",
}


def callable_surface(EV, *, system: str, cls: str, path: str) -> Dict[str, Any]:
    """The IT IS CALLED leg for one class, recorded as FINDINGS (not checks):
    which public methods nothing in core/ calls (split by whether experiments
    or tests exercise them), and which bodies are not implementations."""
    p = ROOT / path
    methods = public_methods(p, cls)
    names = [m.name for m in methods]
    split = reach(names, p, _core_sources())
    dead, internal = split["dead"], split["internal"]
    uncalled = split_uncalled(dead)
    kinds = {m.name: body_kind(m) for m in methods}
    EV.metric(f"{system}_public_methods", len(names), "count")
    EV.metric(f"{system}_internal_only_public_methods", len(internal), "count",
              "used only inside their own file: " + ", ".join(internal))
    found = {
        "experiments_only": sorted(uncalled["experiments_only"]),
        "uncalled": uncalled["nothing"],
        "not_implemented": sorted(n for n, k in kinds.items() if k == "not_implemented"),
        "constant": sorted(n for n, k in kinds.items() if k == "constant"),
        "empty": sorted(n for n, k in kinds.items() if k == "empty"),
    }
    for category, found_names in found.items():
        FINDINGS[category].extend((system, n) for n in found_names)
        detail = ", ".join(
            f"{n} ({'; '.join(uncalled['experiments_only'][n][:2])})"
            if category == "experiments_only" else n for n in found_names)
        EV.metric(f"{system}_{category}", len(found_names), "count", detail)
        if found_names:
            print(f"  [FINDING] {system} — {_FINDING_LABEL[category]}: {detail}")
    return {"methods": names, "internal": internal, **found}


def authority_audit(EV, check, *, system: str, cls: str, path: str,
                    held: Any, reached: Any, allowed_sites: Iterable[str] = ()) -> Dict[str, Any]:
    """The ONE AUTHORITY and IT IS CALLED legs, for one class.

    `held` is what the coordinator holds; `reached` is what the accessor
    returns. `allowed_sites` are construction sites that are the one place by
    design (the accessor's own module is always allowed)."""
    p = ROOT / path
    sources = _core_sources()

    check(f"{system}: the coordinator holds the instance the accessor returns",
          held is not None and held is reached,
          f"held={type(held).__name__ if held is not None else None} "
          f"same={held is reached}")

    sites = construction_sites(cls, sources)
    own = {s for s in sites if s.startswith(path + ":")}
    allowed = set(allowed_sites)
    extra = [s for s in sites if s not in own and not any(s.startswith(a) for a in allowed)]
    EV.metric(f"{system}_construction_sites", len(sites), "count", "; ".join(sites))
    check(f"{system}: {cls} is constructed in one place",
          len(own) <= 1 and not extra,
          f"in its module: {sorted(own)}; elsewhere: {extra}")

    surface = callable_surface(EV, system=system, cls=cls, path=path)
    return {**surface, "sites": sites}


def outcome(EV, checks: List[bool], name: str) -> int:
    """Report behaviour, wiring and completeness APART. Only behaviour decides
    the exit status: a finding is information about the callable surface, not
    a failure of what the system does."""
    passed = sum(1 for c in checks if c)
    wiring = len(FINDINGS["experiments_only"]) + len(FINDINGS["uncalled"])
    incomplete = (len(FINDINGS["not_implemented"]) + len(FINDINGS["constant"])
                  + len(FINDINGS["empty"]))
    EV.metric("behaviour_checks_passed", passed, "count", f"of {len(checks)}")
    EV.metric("wiring_findings", wiring, "count",
              f"{len(FINDINGS['experiments_only'])} exercised only by experiments/tests, "
              f"{len(FINDINGS['uncalled'])} called by nothing")
    EV.metric("completeness_findings", incomplete, "count",
              f"{len(FINDINGS['not_implemented'])} NotImplementedError, "
              f"{len(FINDINGS['constant'])} return a literal, {len(FINDINGS['empty'])} empty")
    print(f"\n==== {name}: behaviour {passed}/{len(checks)} checks passed"
          f" · wiring findings {wiring} ({len(FINDINGS['experiments_only'])} experiments-only,"
          f" {len(FINDINGS['uncalled'])} uncalled)"
          f" · completeness findings {incomplete} ====")
    return 0 if passed == len(checks) else 1
