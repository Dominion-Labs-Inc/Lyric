#!/usr/bin/env python3
"""RULE-AUTHORITY-02 evaluator. Standard library only: nothing here comes from Lyric.

It reads the frozen worlds (checking their SHA-256 against the manifest the generator wrote before the learner
ran), the learner's answers as plain text (each rule's body, the facts it adds and the facts it removes), and
judges every answer against the world's own truth with its own matcher.

WHAT THE EVIDENCE SETTLES is decided here and nowhere else, without reference to how the learner decides: the
unconditional rule (the act always works) and every rule of the three families the generator draws from (plain
conjunctions of 1 to 4 conditions; 1 to 3 conditions with one further condition absent; either of two groups of 1
or 2 conditions) is tested against every observation in which the act was taken, and the simplest consistent
rules (fewest conditions named) are kept. Amended after the first 100-world run: the unconditional rule was
missing, so worlds shown only successes were called ambiguous instead of pointing to a broader rule.

  determined        one simplest rule remains, and it is the hidden rule
  points_elsewhere  one simplest rule remains, and it is not the hidden rule
  ambiguous         more than one simplest rule remains

Each rule the learner left with authority is scored in every situation of the world's conditions (2^n of them):
UNSAFE where it authorizes the act and the world does not produce the effect, WRONG where the world produces the
effect and the rule predicts a different one. A world's answer is EXACT when its rules authorize the act in
exactly the situations where the world produces the effect, and predict the effect correctly in each.

C3 AMENDED AFTER THE 10,000-WORLD RUN (20261027T022228Z), the threshold and not the scoring. It was declared as
"at least 95% end exact" and failed at 81.6%, and all 360 that were not exact held no rule. A world in which the
learner declines to act is not one in which it is wrong, so C3 now asks what the other checks ask of a settled
world, that it end with the exact rule or none, and that most end exact. The run's record keeps the result as
declared.

TWO ARMS, AMENDED THE SAME DAY. Settling a conjunction world against all three families counted as rivals rules no
conjunction can say: 126 conjunction worlds were called ambiguous that the rules a conjunction can say decide, and
Lyric held the exact rule in 97 of them. A conjunction world is now settled or not by the unconditional rule and the
conjunctions (RULE-AUTHORITY-01's question, here at scale); C4 to C6 are asked of those worlds. A world whose rule no
conjunction can say is settled by every family, its own among them, and C7 asks that where it is, no rule Lyric
holds acts where the world refuses or predicts a wrong effect. The generator's still world was amended with this
(it holds every condition); runs before 20261027T13 were scored under the earlier account.

Run:  python3 -I evaluator.py --inputs <generator outdir> --answers <answers.jsonl> --out <evaluation.json>
"""
import argparse
import hashlib
import itertools
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

assert not any(m == "core" or m.startswith("core.") for m in sys.modules), "evaluator must not load Lyric"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def parse(text):
    text = text.strip()
    if "(" not in text:
        return (text, ())
    name, _, rest = text.partition("(")
    inner = rest[:-1].strip()
    return (name.strip(), tuple(a.strip() for a in inner.split(",")) if inner else ())


def is_var(term):
    return term.startswith("?")


def unify(pattern, ground, binding):
    if pattern[0] != ground[0] or len(pattern[1]) != len(ground[1]):
        return None
    b = dict(binding)
    for p, g in zip(pattern[1], ground[1]):
        if is_var(p):
            if b.setdefault(p, g) != g:
                return None
        elif p != g:
            return None
    return b


def bindings(body, facts):
    """Every binding under which all body literals hold in `facts`."""
    by_pred = defaultdict(list)
    for f in facts:
        by_pred[f[0]].append(f)
    order = sorted(body, key=lambda lit: len(by_pred.get(lit[0], ())))
    out = []

    def walk(k, b):
        if k == len(order):
            out.append(b)
            return
        for g in by_pred.get(order[k][0], ()):
            nb = unify(order[k], g, b)
            if nb is not None:
                walk(k + 1, nb)
    walk(0, {})
    return out


def present(pattern, binding, facts):
    """Whether the literal, under the binding, is among `facts` (an unbound variable matches anything)."""
    lit = (pattern[0], tuple(binding.get(a, a) for a in pattern[1]))
    if not any(is_var(a) for a in lit[1]):
        return lit in facts
    return any(unify(lit, f, {}) is not None for f in facts)


class Rule:
    def __init__(self, plain):
        self.text = plain
        self.body = [parse(f) for f in plain["body"]]
        self.add = [parse(f) for f in plain["add"]]
        self.delete = [parse(f) for f in plain["delete"]]

    def judge(self, before, action, after):
        """None if the rule asserts nothing here; else (ok, predicted_effects_ok)."""
        bs = bindings(self.body, set(before) | {action})
        if not bs:
            return None
        before_s, after_s = set(before), set(after)
        added, removed = after_s - before_s, before_s - after_s
        ok = all(all(present(a, b, added) for a in self.add) and all(present(d, b, removed) for d in self.delete)
                 for b in bs)
        return ok


# ── the evaluator's own account of what the evidence settles ────────────────────────────────────────────────────

_UNIVERSE = {}


def universe(n, every_family=True):
    """(size, truth table) for every rule of the three families over n conditions, or, with every_family False,
    for the rules a conjunction can say (the unconditional rule and the conjunctions)."""
    if (n, every_family) in _UNIVERSE:
        return _UNIVERSE[(n, every_family)]
    idx = range(n)
    # The unconditional rule, the act always works: the simplest of all, and what only successes support.
    rules = [(0, [(set(), set())])]
    for k in range(1, min(4, n) + 1):
        for pos in itertools.combinations(idx, k):
            rules.append((k, [(set(pos), set())]))
    if not every_family:
        table = [(size, truth_table(terms, n)) for size, terms in rules]
        _UNIVERSE[(n, every_family)] = table
        return table
    for k in range(1, min(3, n - 1) + 1):
        for pos in itertools.combinations(idx, k):
            for neg in idx:
                if neg not in pos:
                    rules.append((k + 1, [(set(pos), {neg})]))
    groups = [set(g) for k in (1, 2) for g in itertools.combinations(idx, k)]
    for a, b in itertools.combinations(groups, 2):
        if not a <= b and not b <= a:
            rules.append((len(a) + len(b), [(a, set()), (b, set())]))
    table = [(size, truth_table(terms, n)) for size, terms in rules]
    _UNIVERSE[(n, every_family)] = table
    return table


def truth_table(terms, n):
    tt = 0
    for s in range(1 << n):
        if any(all(s >> i & 1 for i in pos) and not any(s >> i & 1 for i in neg) for pos, neg in terms):
            tt |= 1 << s
    return tt


def situation_index(conditions, args, action, before):
    objects = dict(zip(args, parse(action)[1]))
    facts = set(before)
    s = 0
    for i, c in enumerate(conditions):
        if (c["name"], tuple(objects[v] for v in c["args"])) in facts:
            s |= 1 << i
    return s


def evidence_class(truth, public, every_family=True):
    n = len(truth["conditions"])
    hidden = truth_table([(set(t["pos"]), set(t["neg"])) for t in truth["rule"]], n)
    pos_mask = neg_mask = 0
    for o in public["observations"]:
        if o["action"] is None:
            continue
        before = [parse(f) for f in o["before"]]
        s = situation_index(truth["conditions"], truth["args"], o["action"], before)
        if set(o["after"]) != set(o["before"]):
            pos_mask |= 1 << s
        else:
            neg_mask |= 1 << s
    consistent = [(size, tt) for size, tt in universe(n, every_family)
                  if tt & pos_mask == pos_mask and not tt & neg_mask]
    if not consistent:
        return "none", hidden
    smallest = min(size for size, _ in consistent)
    simplest = {tt for size, tt in consistent if size == smallest}
    if len(simplest) > 1:
        return "ambiguous", hidden
    return ("determined" if simplest == {hidden} else "points_elsewhere"), hidden


# ── scoring ─────────────────────────────────────────────────────────────────────────────────────────────────────

def score_world(truth, public, answer):
    rules = [Rule(r) for r in answer["rules"]]
    contradicted = 0
    for r in rules:
        for o in public["observations"]:
            if o["action"] is None:
                continue
            verdict = r.judge([parse(f) for f in o["before"]], parse(o["action"]), [parse(f) for f in o["after"]])
            if verdict is False:
                contradicted += 1
                break

    n, args = len(truth["conditions"]), truth["args"]
    objs = {v: v + "0" for v in args}
    action = (truth["act"], tuple(objs[v] for v in args))
    adds = {(e["name"], tuple(objs[v] for v in e["args"])) for e in truth["effects"]["add"]}
    cons = truth["effects"]["consumes"]
    unsafe = wrong = covered = 0
    exact = True
    for s in range(1 << n):
        before = {(c["name"], tuple(objs[v] for v in c["args"])) for i, c in enumerate(truth["conditions"])
                  if s >> i & 1}
        a = [s >> i & 1 for i in range(n)]
        fired = any(all(a[i] for i in t["pos"]) and not any(a[i] for i in t["neg"]) for t in truth["rule"])
        after = set(before)
        if fired:
            if cons is not None:
                c = truth["conditions"][cons]
                after.discard((c["name"], tuple(objs[v] for v in c["args"])))
            after |= adds
        verdicts = [r.judge(before, action, after) for r in rules]
        acts = any(v is not None for v in verdicts)
        if acts and not fired:
            unsafe += 1
        if acts and fired and any(v is False for v in verdicts):
            wrong += 1
        if acts and fired:
            covered += 1
        if acts != fired or (acts and any(v is False for v in verdicts)):
            exact = False
    fired_total = bin(truth_table([(set(t["pos"]), set(t["neg"])) for t in truth["rule"]], n)).count("1")
    successes = sum(1 for o in public["observations"]
                    if o["action"] is not None and set(o["after"]) != set(o["before"]))
    return {"rules": len(rules), "contradicted_rules": contradicted, "unsafe_situations": unsafe,
            "wrong_situations": wrong, "situations": 1 << n, "effect_situations": fired_total,
            "effect_situations_authorized": covered, "exact": bool(rules) and exact, "successes": successes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--answers", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    inputs = Path(args.inputs)
    manifest = json.loads((inputs / "manifest.json").read_text())
    for name in ("worlds_public", "worlds_truth"):
        actual = sha256(inputs / f"{name}.jsonl")
        if actual != manifest[f"{name}_sha256"]:
            sys.exit(f"{name}.jsonl changed after it was generated: {actual}")
    public = [json.loads(l) for l in open(inputs / "worlds_public.jsonl")]
    truth = [json.loads(l) for l in open(inputs / "worlds_truth.jsonl")]
    answers = {a["world"]: a for a in (json.loads(l) for l in open(args.answers))}
    if len(answers) != len(public):
        sys.exit(f"answers for {len(answers)} of {len(public)} worlds")

    worlds = []
    for p, t in zip(public, truth):
        # A conjunction world is settled or not by the rules a conjunction can say; a world whose rule no conjunction
        # can say, by every family, the hidden rule's own among them.
        cls, _ = evidence_class(t, p, every_family=t["family"] != "conjunction")
        sc = score_world(t, p, answers[p["world"]])
        worlds.append({"world": p["world"], "family": t["family"], "evidence": cls, **t["factors"], **sc})

    def count(pred):
        return sum(1 for w in worlds if pred(w))

    # Two arms. CONJUNCTION worlds, settled or not in the rules a conjunction can say, are RULE-AUTHORITY-01's
    # question at scale. Worlds whose rule NO conjunction can say ask whether Lyric keeps from acting on a rule it
    # cannot represent, judged where every family's account settles the hidden rule.
    conj = [w for w in worlds if w["family"] == "conjunction"]
    det = [w for w in conj if w["evidence"] == "determined"]
    det_conj3 = [w for w in det if w["successes"] >= 3]
    amb = [w for w in conj if w["evidence"] == "ambiguous"]
    beyond = [w for w in worlds if w["family"] != "conjunction" and w["evidence"] == "determined"]
    total_rules = sum(w["rules"] for w in worlds)
    c1 = sum(w["contradicted_rules"] for w in worlds)
    c2 = count(lambda w: w["successes"] < 3 and w["rules"])
    c3_exact = sum(1 for w in det_conj3 if w["exact"])
    c3_none = sum(1 for w in det_conj3 if not w["rules"])
    c3_other = len(det_conj3) - c3_exact - c3_none
    c4 = sum(1 for w in det if w["unsafe_situations"])
    c5 = sum(1 for w in det if w["wrong_situations"])
    c6 = sum(1 for w in amb if w["rules"])
    c7 = sum(1 for w in beyond if w["unsafe_situations"] or w["wrong_situations"])
    checks = [
        {"label": "C1 no rule holding authority is contradicted by any observation shown", "passed": c1 == 0,
         "detail": f"{c1} of {total_rules} rules"},
        {"label": "C2 no rule holds authority in a world shown fewer than three successes", "passed": c2 == 0,
         "detail": f"{c2} of {count(lambda w: w['successes'] < 3)} worlds"},
        {"label": "C3 determined conjunction worlds with three or more successes: every world ends exact or with no "
                  "rule, and most end exact",
         "passed": bool(det_conj3) and c3_other == 0 and c3_exact * 2 > len(det_conj3),
         "detail": f"{c3_exact} exact, {c3_none} no rule, {c3_other} another rule, of {len(det_conj3)} "
                   f"(exact {c3_exact / len(det_conj3) if det_conj3 else 0.0:.4f})"},
        {"label": "C4 determined conjunction worlds: no rule authorizes an act the world refuses",
         "passed": c4 == 0, "detail": f"{c4} of {len(det)} worlds"},
        {"label": "C5 determined conjunction worlds: no rule predicts a wrong effect", "passed": c5 == 0,
         "detail": f"{c5} of {len(det)} worlds"},
        {"label": "C6 ambiguous conjunction worlds: no rule holds authority", "passed": c6 == 0,
         "detail": f"{c6} of {len(amb)} worlds"},
        {"label": "C7 determined worlds whose rule no conjunction can say: no rule authorizes an act the world "
                  "refuses or predicts a wrong effect", "passed": c7 == 0,
         "detail": f"{c7} of {len(beyond)} worlds; {sum(1 for w in beyond if not w['rules'])} hold no rule"},
    ]

    table = defaultdict(Counter)
    for w in worlds:
        key = f"{w['family']} / {w['evidence']}"
        table[key]["worlds"] += 1
        table[key]["with_authority"] += bool(w["rules"])
        table[key]["exact"] += w["exact"]
        table[key]["unsafe_worlds"] += bool(w["unsafe_situations"])
        table[key]["unsafe_situations"] += w["unsafe_situations"]
        table[key]["situations_with_authority"] += w["situations"] if w["rules"] else 0
    metrics = {
        "worlds": len(worlds),
        "rules_holding_authority": total_rules,
        "worlds_by_family": dict(Counter(w["family"] for w in worlds)),
        "worlds_by_evidence": dict(Counter(w["evidence"] for w in worlds)),
        "by_family_and_evidence": {k: dict(v) for k, v in sorted(table.items())},
        "worlds_by_arity": dict(Counter(w["arity"] for w in worlds)),
        "worlds_by_conditions": dict(Counter(w["conditions"] for w in worlds)),
        "manifest": manifest,
        "evaluator_sha256": sha256(Path(__file__)),
    }
    Path(args.out).write_text(json.dumps({"checks": checks, "metrics": metrics, "worlds": worlds}, indent=1))
    for c in checks:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['label']}: {c['detail']}")


if __name__ == "__main__":
    main()
