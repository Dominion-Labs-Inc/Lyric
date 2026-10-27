#!/usr/bin/env python3
"""RULE-AUTHORITY-02 world generator. Standard library only: nothing here comes from Lyric.

Each world hides one rule saying when an act produces its effect. The rules are drawn from three families, and
two of them are outside what a learner limited to plain conjunctions can express:

  conjunction   the act works when every one of 1 to 4 conditions holds
  negated       1 to 3 conditions hold AND one further condition does not
  either_or     either of two groups of 1 or 2 conditions holds

Every world draws its own vocabulary (invented names), 4 to 7 conditions, an act of 1 to 3 arguments, conditions
over those arguments in any order, one or two effects, sometimes a condition the act consumes, and distractor facts
about other things. A world is a set of GROUPS OF THINGS, all present from the start, each with the conditions that
hold of it:

  the still group     every condition holds; never offered to act on, so the world left alone shows that the act,
                      and no combination of the conditions alone, produces the effect
  practice            2 to 6 successes (8 to 16 in the noisy arm), near misses covering none, about half or all of
                      the rule, failures the rule says nothing about, and in a quarter of worlds a revealing near
                      miss that comes last: the acts the world offers Lyric to practise, in this order
  goals               6 groups, half where the rule lets the act work and half where it does not: the world asks
                      Lyric to bring the act's effect about on each
  more                another practice drawn the same way, offered whenever Lyric explores again

Two files are written, and the learner's side opens only the first:

  worlds_public.jsonl   what the world offers: its act, the acts it lets Lyric practise, the goals it asks for
  worlds_truth.jsonl    the answers: conditions, hidden rule, effects, the groups, factors

plus manifest.json with the SHA-256 of both files and of this script, written before any learner runs.

`serve` IS THE WORLDS: a separate process that holds the truth and works out, when Lyric acts, what the act does
from what holds then (and, in the noisy arm, whether the noise turns or hides it), logging every act it receives.

Run:  python3 -I generator.py --worlds 10000 --seed 20261026 --outdir <folder> [--noise]
      python3 -I generator.py serve --inputs <folder> --log <folder>/world_log.jsonl
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


#: The noisy arm's world, as `warehouse_stochastic.NOISY_PARTIAL` (EDU-10): where the rule holds the act works
#: 90% of the time, where it does not it works 2% of the time, and 10% of outcomes cannot be read at all.
NOISE = {"success_rate": 0.90, "leak_rate": 0.02, "unknown_rate": 0.10}

#: Goals each world asks of Lyric once it has practised: half where the world's rule lets the act work, half where
#: it does not.
GOALS = 6


def make_world(i, seed, noise=None):
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
    n_succ = rng.randint(8, 16) if noise else rng.randint(2, 6)   # noise needs more evidence (EDU-10: 25 -> 36)
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

    # EVERY SITUATION IS A GROUP OF THINGS PRESENT IN ONE WORLD, from the start: its objects (the act's arguments),
    # the conditions that hold of them, and distractor things beside them. What an act does is not drawn here: the
    # world works it out when Lyric acts (`serve`), from what holds then.
    groups = []

    def group(a, kind):
        k = len(groups)
        names = [f"o{k}{c}" for c in "abc"[:arity]]
        binding = dict(zip(args, names))
        facts = [fact(c["name"], c["args"], binding) for c, on in zip(conditions, a) if on]
        things = list(names)
        for d in range(rng.randint(0, 3)):
            other = f"o{k}w{d}"
            things.append(other)
            if rng.random() < 0.5:
                c = rng.choice(conditions)
                b = {v: other for v in args}
                if len(c["args"]) == 2:
                    b[c["args"][0]] = binding[c["args"][0]]
                facts.append(fact(c["name"], c["args"], b))
            else:
                facts.append(f"{rng.choice(unrelated_preds)}({other})")
        groups.append({"kind": kind, "objects": names, "things": things, "assignment": [int(v) for v in a],
                       "facts": sorted(set(facts))})
        return k

    # THE STILL GROUP HOLDS EVERY CONDITION and is never acted on: the world unchanged where nothing is done shows
    # that the act, and no combination of the conditions alone, produces the effect.
    success(rng, terms, n)
    group([1] * n, "still")
    practice = []
    for kind, lit in plan:
        a = success(rng, terms, n) if kind == "success" else \
            near_miss(rng, terms, n, lit) if kind == "near_miss" else failure(rng, terms, n)
        if a is not None:
            practice.append(group(a, kind))
    tests = []
    for g in range(GOALS):
        if g % 2 == 0:
            a, kind = success(rng, terms, n), "goal_works"
        else:
            a, kind = (near_miss(rng, terms, n, rng.choice(literals)) if rng.random() < 0.5 else None), "goal_refused"
            a = a or failure(rng, terms, n)
        if a is not None:
            tests.append(group(a, kind))

    # MORE TO PRACTISE ON, drawn as the practice was: what the world offers once the first practice is used up,
    # when Lyric explores again (to close a gap a goal showed it, or of its own accord). A world does not run out of
    # things to try.
    more_plan = [("success", None)] * n_succ + [("near_miss", lit) for lit in literals] + \
                [("failure", None)] * rng.randint(0, 3)
    rng.shuffle(more_plan)
    more = []
    for kind, lit in more_plan:
        a = success(rng, terms, n) if kind == "success" else \
            near_miss(rng, terms, n, lit) if kind == "near_miss" else failure(rng, terms, n)
        if a is not None:
            more.append(group(a, kind))

    def acts_on(k):
        return f"{act}({', '.join(groups[k]['objects'])})"

    def effects_on(k):
        binding = dict(zip(args, groups[k]["objects"]))
        return sorted(fact(e["name"], e["args"], binding) for e in adds)

    public = {"world": i, "act": act, "arity": arity, "args": args,
              "practice": [acts_on(k) for k in practice], "more": [acts_on(k) for k in more],
              "goals": [effects_on(k) for k in tests]}
    truth = {"world": i, "seed": seed, "family": family, "act": act, "args": args, "conditions": conditions,
             "rule": terms, "effects": {"add": adds, "consumes": consumes}, "noise": noise, "groups": groups,
             "practice": practice, "tests": tests, "more": more,
             "factors": {"conditions": n, "arity": arity, "planned_successes": n_succ, "coverage": q,
                         "late_near_miss": late is not None, "consumes": consumes is not None,
                         "effects": len(adds)}}
    return public, truth


# ── the world, live ─────────────────────────────────────────────────────────────────────────────────────────────

def terms_of(text):
    return set(text[text.index("(") + 1:-1].split(", "))


def serve(inputs, log_path):
    """Every world, as a service Lyric reaches over HTTP and nothing else.

      POST /w/<world>/act   {"x": ..., "y": ...}   the act, on the things named. The world works out from what holds
                                                    now whether its rule lets the act work (and, in the noisy arm,
                                                    whether the noise turns it), changes accordingly, and answers
                                                    that the act was performed: what it did is read by looking.
      GET  /w/<world>/look                          every fact that holds now; 503 when the outcome of the last act
                                                    cannot be read (the noisy arm), once.

    Every act is written to `log_path` as it happens, with the world's own account of it, for the evaluator.
    """
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    worlds = {}
    with open(Path(inputs) / "worlds_truth.jsonl") as f:
        for line in f:
            t = json.loads(line)
            worlds[t["world"]] = t
    states, lock = {}, threading.Lock()
    log = open(log_path, "a")

    def state_of(w):
        if w not in states:
            t = worlds[w]
            states[w] = {"facts": {f for g in t["groups"] for f in g["facts"]},
                         "rng": random.Random(t["seed"] + 1), "unreadable": False, "acts": 0}
        return states[w]

    def act(w, given):
        t, s = worlds[w], state_of(w)
        names = [str(given.get(v)) for v in t["args"]]
        binding = dict(zip(t["args"], names))
        a = [int(fact(c["name"], c["args"], binding) in s["facts"]) for c in t["conditions"]]
        fired = fires(t["rule"], a)
        happened, unknown = fired, False
        if t["noise"]:
            happened = s["rng"].random() < (t["noise"]["success_rate"] if fired else t["noise"]["leak_rate"])
            unknown = s["rng"].random() < t["noise"]["unknown_rate"]
        k = next((k for k, g in enumerate(t["groups"]) if g["objects"] == names), None)
        frame = set(t["groups"][k]["things"]) if k is not None else set(names)
        before = sorted(f for f in s["facts"] if terms_of(f) & frame)
        added = []
        if happened:
            if t["effects"]["consumes"] is not None:
                c = t["conditions"][t["effects"]["consumes"]]
                s["facts"].discard(fact(c["name"], c["args"], binding))
            effects = {fact(e["name"], e["args"], binding) for e in t["effects"]["add"]}
            added = sorted(effects - s["facts"])
            s["facts"] |= effects
        s["unreadable"] = unknown
        s["acts"] += 1
        after = sorted(f for f in s["facts"] if terms_of(f) & frame)
        log.write(json.dumps({"world": w, "n": s["acts"], "at": time.time(), "objects": names, "group": k,
                              "kind": t["groups"][k]["kind"] if k is not None else None, "assignment": a,
                              "fired": fired, "happened": happened, "unknown": unknown,
                              "before": before, "after": after, "added": added}) + "\n")
        log.flush()

    class World(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _world(self, verb):
            parts = self.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "w" and parts[2] == verb and parts[1].isdigit() \
                    and int(parts[1]) in worlds:
                return int(parts[1])
            return None

        def _answer(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            w = self._world("look")
            if w is None:
                return self._answer(404, {"error": "no such world"})
            with lock:
                s = state_of(w)
                if s["unreadable"]:
                    s["unreadable"] = False
                    return self._answer(503, {"error": "the world cannot be read just now"})
                facts = sorted(s["facts"])
            self._answer(200, {"facts": facts})

        def do_POST(self):
            w = self._world("act")
            if w is None:
                return self._answer(404, {"error": "no such world"})
            given = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with lock:
                act(w, given if isinstance(given, dict) else {})
            self._answer(200, {"performed": True})

    server = ThreadingHTTPServer(("127.0.0.1", 0), World)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"port": server.server_address[1]}), flush=True)
    sys.stdin.read()            # the world stands until whoever started it lets go
    server.shutdown()
    log.close()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    if sys.argv[1:2] == ["serve"]:
        ap = argparse.ArgumentParser()
        ap.add_argument("serve")
        ap.add_argument("--inputs", required=True)
        ap.add_argument("--log", required=True)
        a = ap.parse_args()
        return serve(a.inputs, a.log)
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=10000)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--noise", action="store_true", help="the noisy arm: outcomes as NOISE says")
    args = ap.parse_args()
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=False)
    master = random.Random(args.seed)
    seeds = [master.randrange(2 ** 31) for _ in range(args.worlds)]
    with open(out / "worlds_public.jsonl", "w") as pub, open(out / "worlds_truth.jsonl", "w") as tru:
        for i, s in enumerate(seeds):
            p, t = make_world(i, s, NOISE if args.noise else None)
            pub.write(json.dumps(p) + "\n")
            tru.write(json.dumps(t) + "\n")
    manifest = {"worlds": args.worlds, "seed": args.seed, "noise": NOISE if args.noise else None,
                "worlds_public_sha256": sha256(out / "worlds_public.jsonl"),
                "worlds_truth_sha256": sha256(out / "worlds_truth.jsonl"),
                "generator_sha256": sha256(Path(__file__))}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
