#!/usr/bin/env python3
"""RULE-AUTHORITY-02 world generator. Standard library only: nothing here comes from Lyric.

Each world hides one rule saying when an act produces its effect. The rules are drawn from three families, and
two of them are outside what a learner limited to plain conjunctions can express:

  conjunction   the act works when every one of 1 to 4 conditions holds
  negated       1 to 3 conditions hold AND one further condition does not
  either_or     either of two groups of 1 or 2 conditions holds

Every world draws its own vocabulary (invented names), 4 to 7 conditions, an act of 1 to 3 arguments, conditions
over those arguments in any order, one or two effects, sometimes a condition the act consumes, distractor facts
about other objects, 2 to 6 successes, near misses covering none, about half or all of the rule, failures the rule
says nothing about, and in a quarter of worlds a revealing near miss that arrives last.

Two files are written, and the learner's side opens only the first:

  worlds_public.jsonl   what is shown: per world, the act and its observations (facts before, act, facts after)
  worlds_truth.jsonl    the answers: conditions, hidden rule, effects, factors

plus manifest.json with the SHA-256 of both files and of this script, written before any learner runs.

Run:  python3 -I generator.py --worlds 10000 --seed 20261026 --outdir <folder>
"""
import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

assert not any(m == "core" or m.startswith("core.") for m in sys.modules), "generator must not load Lyric"

FAMILIES = (("conjunction", 0.50), ("negated", 0.25), ("either_or", 0.25))
SYLLABLES = ("BA", "DO", "FE", "GA", "HI", "JO", "KE", "LU", "MA", "NO", "PI", "RA", "SU", "TO", "VE", "WI",
             "ZA", "BRO", "DRA", "FIL", "GOR", "KAL", "MIR", "NEX", "POL", "QUA", "RIN", "SOL", "TAV", "VOR")
ARG_NAMES = ("x", "y", "z")


def invented(rng, used):
    while True:
        w = "".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3)))
        if w not in used:
            used.add(w)
            return w


def patterns(arity):
    args = ARG_NAMES[:arity]
    unary = [(a,) for a in args]
    binary = [(a, b) for a in args for b in args if a != b]
    return unary + binary


def holds(term, a):
    return all(a[i] for i in term["pos"]) and not any(a[i] for i in term["neg"])


def fires(terms, a):
    return any(holds(t, a) for t in terms)


def hidden_rule(rng, family, n):
    idx = list(range(n))
    if family == "conjunction":
        return [{"pos": sorted(rng.sample(idx, rng.randint(1, min(4, n)))), "neg": []}]
    if family == "negated":
        pos = sorted(rng.sample(idx, rng.randint(1, min(3, n - 1))))
        neg = [rng.choice([i for i in idx if i not in pos])]
        return [{"pos": pos, "neg": neg}]
    while True:
        a = set(rng.sample(idx, rng.randint(1, 2)))
        b = set(rng.sample(idx, rng.randint(1, 2)))
        if not a <= b and not b <= a:
            return [{"pos": sorted(a), "neg": []}, {"pos": sorted(b), "neg": []}]


def success(rng, terms, n):
    a = [rng.random() < 0.5 for _ in range(n)]
    t = rng.choice(terms)
    for i in t["pos"]:
        a[i] = True
    for i in t["neg"]:
        a[i] = False
    return a


def near_miss(rng, terms, n, literal):
    """A firing situation with one literal of the rule broken, and the rule not firing."""
    owner = [t for t in terms if literal[0] in t[literal[1]]]
    for _ in range(200):
        a = [rng.random() < 0.5 for _ in range(n)]
        t = rng.choice(owner)
        for i in t["pos"]:
            a[i] = True
        for i in t["neg"]:
            a[i] = False
        i, kind = literal
        a[i] = kind == "neg"
        for other in terms:
            if holds(other, a) and other["pos"]:
                a[rng.choice(other["pos"])] = False
        if not fires(terms, a) and a[i] == (kind == "neg"):
            return a
    return None


def failure(rng, terms, n):
    for _ in range(200):
        a = [rng.random() < 0.5 for _ in range(n)]
        if not fires(terms, a):
            return a
    return None


def fact(name, args, binding):
    return f"{name}({', '.join(binding[v] for v in args)})"


def make_world(i, seed):
    rng = random.Random(seed)
    used = set()
    family = rng.choices([f for f, _ in FAMILIES], weights=[w for _, w in FAMILIES])[0]
    n = rng.randint(4, 7)
    arity = rng.choice((1, 2, 2, 3))
    args = list(ARG_NAMES[:arity])
    act = invented(rng, used)
    pool = patterns(arity)
    conditions = [{"name": invented(rng, used), "args": list(rng.choice(pool))} for _ in range(n)]
    terms = hidden_rule(rng, family, n)
    effect_args = [rng.choice(pool) for _ in range(1 if rng.random() < 0.8 else 2)]
    adds = [{"name": invented(rng, used), "args": list(p)} for p in effect_args]
    consumes = None
    if family != "either_or" and rng.random() < 0.4:
        consumes = rng.choice(terms[0]["pos"])
    unrelated_preds = [invented(rng, used) for _ in range(2)]

    literals = sorted({(i, "pos") for t in terms for i in t["pos"]} | {(i, "neg") for t in terms for i in t["neg"]})
    n_succ = rng.randint(2, 6)
    q = rng.choice((0.0, 0.5, 1.0))
    covered = [lit for lit in literals if rng.random() < q]
    uncovered = [lit for lit in literals if lit not in covered]
    plan = [("success", None)] * n_succ + [("near_miss", lit) for lit in covered] + \
           [("failure", None)] * rng.randint(0, 3)
    rng.shuffle(plan)
    late = None
    if uncovered and rng.random() < 0.25:
        late = rng.choice(uncovered)
        plan.append(("near_miss", late))

    def observe(k, a, acted):
        names = [f"o{k}{c}" for c in "abc"[:arity]]
        binding = dict(zip(args, names))
        before = [fact(c["name"], c["args"], binding) for c, on in zip(conditions, a) if on]
        for d in range(rng.randint(0, 3)):
            other = f"o{k}w{d}"
            if rng.random() < 0.5:
                c = rng.choice(conditions)
                b = {v: other for v in args}
                if len(c["args"]) == 2:
                    b[c["args"][0]] = binding[c["args"][0]]
                before.append(fact(c["name"], c["args"], b))
            else:
                before.append(f"{rng.choice(unrelated_preds)}({other})")
        before = sorted(set(before))
        fired = acted and fires(terms, a)
        after = set(before)
        if fired:
            if consumes is not None:
                after.discard(fact(conditions[consumes]["name"], conditions[consumes]["args"], binding))
            after |= {fact(e["name"], e["args"], binding) for e in adds}
        action = f"{act}({', '.join(names)})" if acted else None
        return {"before": before, "action": action, "after": sorted(after)}, \
               {"kind": None, "assignment": [int(v) for v in a], "fired": fired}

    public_obs, truth_obs = [], []
    o, t = observe(0, success(rng, terms, n), acted=False)
    t["kind"] = "still"
    public_obs.append(o)
    truth_obs.append(t)
    shown_succ = 0
    for k, (kind, lit) in enumerate(plan, start=1):
        a = success(rng, terms, n) if kind == "success" else \
            near_miss(rng, terms, n, lit) if kind == "near_miss" else failure(rng, terms, n)
        if a is None:
            continue
        o, t = observe(k, a, acted=True)
        t["kind"] = kind
        shown_succ += t["fired"]
        public_obs.append(o)
        truth_obs.append(t)

    public = {"world": i, "act": act, "arity": arity, "observations": public_obs}
    truth = {"world": i, "seed": seed, "family": family, "act": act, "args": args, "conditions": conditions,
             "rule": terms, "effects": {"add": adds, "consumes": consumes}, "observations": truth_obs,
             "factors": {"conditions": n, "arity": arity, "successes": shown_succ, "coverage": q,
                         "late_near_miss": late is not None, "consumes": consumes is not None,
                         "effects": len(adds)}}
    return public, truth


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=10000)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=False)
    master = random.Random(args.seed)
    seeds = [master.randrange(2 ** 31) for _ in range(args.worlds)]
    with open(out / "worlds_public.jsonl", "w") as pub, open(out / "worlds_truth.jsonl", "w") as tru:
        for i, s in enumerate(seeds):
            p, t = make_world(i, s)
            pub.write(json.dumps(p) + "\n")
            tru.write(json.dumps(t) + "\n")
    manifest = {"worlds": args.worlds, "seed": args.seed,
                "worlds_public_sha256": sha256(out / "worlds_public.jsonl"),
                "worlds_truth_sha256": sha256(out / "worlds_truth.jsonl"),
                "generator_sha256": sha256(Path(__file__))}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
