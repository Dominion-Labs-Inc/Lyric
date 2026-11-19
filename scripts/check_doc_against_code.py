#!/usr/bin/env python3
"""Check an architecture document against the code it describes.

What it can check mechanically, and does:
  - every `module.py` named exists, and every `(N lines)` claim matches
  - every `name (LINE)` claim lands on that definition in the module the section names
  - every method or class named in backticks is defined somewhere in core/ (a file that
    lives in tests/, scripts/, experiments/ or archive/ is reported as found, not missing)
  - every cross-file `file.py:LINE` reference, whether that line is within the file

What it CANNOT check, and nobody should read a clean run as covering:
  - whether the prose is TRUE. "The gate refuses below the floor" names real code at the
    right place whether or not the refusal works. That needs a run, not a scan.

    ./venv_lyric/bin/python3 scripts/check_doc_against_code.py docs/architecture/*.md
"""
import ast, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
# The substrate itself: what a document about the architecture is checked against.
PY = {os.path.basename(p): p for p in glob.glob("core/**/*.py", recursive=True)}
PY.setdefault("main.py", "core/main.py")

# Everywhere else a document may legitimately name a file -- tests, scripts, experiments,
# the archive. A path that resolves HERE is not a defect; it is simply not substrate code,
# and reporting it as missing sent four documents to be "corrected" against files that exist.
ELSEWHERE = {}
for _root in ("tests", "scripts", "experiments", "archive", "tools", "."):
    for _p in glob.glob(f"{_root}/**/*.py", recursive=True) if _root != "." else glob.glob("*.py"):
        if _p.startswith(("venv", ".git", "core/")):
            continue
        ELSEWHERE.setdefault(os.path.basename(_p), _p)

# Words that look like a call in prose and are not a substrate symbol: Python's own
# builtins, and the logic atoms a reasoning document necessarily writes out ("human(x)",
# "mortal(x)"). Checking these produced nothing but noise.
import builtins as _b
NOT_A_SYMBOL = set(dir(_b)) | {
    "isa", "instance_of", "has_property", "located_in", "precedes", "capable_of",
    "human", "mortal", "rained", "wet", "circle", "square", "triangle",
}

_defs_cache = {}
def defs_of(path):
    if path not in _defs_cache:
        try:
            tree = ast.parse(open(path, encoding="utf-8", errors="replace").read())
        except Exception:
            _defs_cache[path] = ({}, set())
            return _defs_cache[path]
        d = {n.name: n.lineno for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        src = open(path, encoding="utf-8", errors="replace").read()
        attrs = set(re.findall(r"self\.([a-z_][a-z_0-9]*)\s*[:=]", src))
        _defs_cache[path] = (d, attrs)
    return _defs_cache[path]

ALL_DEFS = None
def defined_anywhere(name):
    global ALL_DEFS
    if ALL_DEFS is None:
        ALL_DEFS = set()
        for p in PY.values():
            d, a = defs_of(p)
            ALL_DEFS |= set(d) | a
    return name in ALL_DEFS

def check(doc):
    t = open(doc, encoding="utf-8").read()
    out = []

    # the module this document is principally about: the first `core/...py` it names
    # the module this document is about: the one named in the first 40 lines, which is where
    # these documents put it. A path cited later belongs to something the document mentions.
    primary = None
    head = "\n".join(t.split("\n")[:40])
    m = re.search(r"`(core/[a-z_0-9/]+\.py)`", head)
    if m and os.path.exists(m.group(1)):
        primary = m.group(1)

    # 1. line-count claims
    for name, num in re.findall(r"`([a-z_0-9/]+\.py)`\s*\(([\d,]+)(?:\s*lines)?\)", t):
        p = name if os.path.exists(name) else PY.get(os.path.basename(name))
        if not p:
            out.append(("path", f"{name} does not exist")); continue
        real = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        if real != int(num.replace(",", "")):
            out.append(("lines", f"{name}: says {num}, is {real:,}"))

    # 2. files named at all
    for f in set(re.findall(r"`([a-z_0-9]+\.py)`", t)):
        if f not in PY and not os.path.exists(f):
            if f in ELSEWHERE:
                continue                      # a real file, outside the substrate
            out.append(("path", f"{f} not found in core/"))

    # 3. `name (LINE)` against the primary module
    if primary:
        d, attrs = defs_of(primary)
        for name, ln in re.findall(r"`(?:async )?([A-Za-z_][A-Za-z_0-9]*)(?:\([^`]*\))?`(?:\*\*)?[^`\n(]{0,60}\((\d{3,5})\)", t):
            if name in d and abs(d[name] - int(ln)) > 2:
                out.append(("line", f"{name}: says {ln}, is {d[name]}"))

    # 4. every method or class named must exist somewhere
    for name in sorted(set(re.findall(r"`(?:async )?([a-z_][a-z_0-9]*)\(", t))):
        if not defined_anywhere(name):
            if name in NOT_A_SYMBOL or name.endswith("_"):
                continue
            out.append(("symbol", f"{name}() is defined nowhere in core/"))

    # 5. cross-file `file.py:LINE`
    for f, ln in re.findall(r"`?([a-z_0-9]+\.py):(\d+)", t):
        p = PY.get(f)
        if not p: out.append(("xref", f"{f}:{ln} — file not found")); continue
        n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        if int(ln) > n:
            out.append(("xref", f"{f}:{ln} is past the end of a {n}-line file"))
    return primary, out

if __name__ == "__main__":
    targets = sys.argv[1:] or sorted(glob.glob("docs/architecture/*.md"))
    total = 0
    for doc in targets:
        primary, out = check(doc)
        print(f"\n=== {doc}" + (f"   (about {primary})" if primary else ""))
        if not out:
            print("    nothing mechanical to report")
        for kind, msg in out:
            print(f"    {kind:<8} {msg}")
        total += len(out)
    print(f"\n{len(targets)} document(s), {total} mechanical finding(s).")
    print("A clean run means the names and numbers resolve. It does NOT mean the prose is true.")
