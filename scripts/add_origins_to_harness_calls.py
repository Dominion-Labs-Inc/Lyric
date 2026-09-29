"""Give every harness call of a changed memory door the argument it now requires, stating where its content came
from: the harness's own material is the substrate's own (named after the experiment or test); a call that named a
person as the owner now gives that person as the origin."""
import ast, os, sys
ROOT = "/Users/stefan/Dominion Labs/TorinAI"
NEEDS = {"store_memory": "origin", "enqueue_memory": "origin", "see": "actor_identity",
         "remember_image": "origin", "reason_about": "origin", "make_enhanced_prediction": "origin",
         "perform_cross_domain_reasoning": "origin", "remember_told": "origin"}
SKIP = {"experiments/CANARY-01/experiment.py"}

def name_of(rel):
    parts = rel.split("/")
    if parts[0] == "experiments" and len(parts) > 2:
        return parts[-2] if parts[-1] in ("experiment.py", "serve.py", "probe.py", "probe2.py", "attempt.py") else parts[-1][:-3]
    return os.path.splitext(parts[-1])[0]

def offset(lines_start, lineno, col):
    return lines_start[lineno - 1] + col

changed = {}
for top in ("tests", "experiments", "scripts"):
    for dp, dirs, files in os.walk(os.path.join(ROOT, top)):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", "results"}]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, ROOT)
            if rel in SKIP:
                continue
            src = open(p, encoding="utf-8").read()
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            starts, pos = [], 0
            for line in src.splitlines(keepends=True):
                starts.append(pos); pos += len(line)
            edits = []            # (start, end, replacement)
            import_into = {}      # function node -> True
            label = name_of(rel)
            funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in NEEDS):
                    continue
                recv = ast.unparse(n.func.value)
                if n.func.attr == "store_memory" and ("postgres_storage" in recv or recv.endswith("storage")):
                    continue
                kws = {k.arg: k for k in n.keywords}
                need = NEEDS[n.func.attr]
                if need in kws or None in kws:
                    continue
                if need == "actor_identity":
                    add = "actor_identity=None"
                elif "user_id" in kws:
                    k = kws["user_id"]
                    value = ast.get_source_segment(src, k.value)
                    s0 = offset(starts, k.lineno, k.col_offset)
                    s1 = offset(starts, k.value.end_lineno, k.value.end_col_offset)
                    edits.append((s0, s1, f'origin=Origin.of({value}, "{label}")'))
                    add = None
                else:
                    add = f'origin=Origin.own("{label}")'
                if need == "origin":
                    owner = min((f for f in funcs if f.lineno <= n.lineno <= f.end_lineno),
                                key=lambda f: f.end_lineno - f.lineno, default=None)
                    import_into[owner] = True
                if add:
                    close = offset(starts, n.end_lineno, n.end_col_offset) - 1
                    assert src[close] == ")", (rel, n.lineno)
                    k = close - 1
                    while src[k] in " \t\n":
                        k -= 1
                    if src[k] in ",(":
                        sep = "" if src[k] == "(" else " "
                        edits.append((k + 1, k + 1, f"{sep}{add}"))
                    else:
                        edits.append((k + 1, k + 1, f", {add}"))
            for f in import_into:
                if f is None:
                    first = tree.body[0]
                    # after the leading docstring and imports: before the first def/class
                    anchor = next((b for b in tree.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))), None)
                    at = offset(starts, anchor.lineno, 0)
                    edits.append((at, at, "from core.memory import Origin  # noqa: E402\n\n\n"))
                    continue
                body0 = f.body[0]
                if (isinstance(body0, ast.Expr) and isinstance(getattr(body0, "value", None), ast.Constant)
                        and isinstance(body0.value.value, str)):
                    nxt = f.body[1] if len(f.body) > 1 else None
                    target = nxt or body0
                    col = target.col_offset if nxt else body0.col_offset
                    at = offset(starts, target.lineno, 0) if nxt else offset(starts, body0.end_lineno, 0) + len(src.splitlines(keepends=True)[body0.end_lineno - 1])
                else:
                    col = body0.col_offset
                    at = offset(starts, body0.lineno, 0)
                edits.append((at, at, " " * col + "from core.memory import Origin\n"))
            if not edits:
                continue
            for s0, s1, rep in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
                src = src[:s0] + rep + src[s1:]
            ast.parse(src)
            open(p, "w", encoding="utf-8").write(src)
            changed[rel] = len(edits)
for rel, n in sorted(changed.items()):
    print(f"{n:3} {rel}")
print(len(changed), "files")
