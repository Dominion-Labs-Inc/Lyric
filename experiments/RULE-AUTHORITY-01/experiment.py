#!/usr/bin/env python3
"""RULE-AUTHORITY-01 — 1,000 hidden worlds: does a learned rule get authority only when it should?

WHY. RULE-EVIDENCE-01 checks validation on a handful of hand-written cases. That
says a case works; it cannot say the rule holds. On 2026-09-30 two defects were
found in how a learned operator earns the authority to act, and both were
invisible at that scale:

  * a rule validated early in a teaching run kept its authority after a later
    demonstration contradicted it (fixed: `RuleStore.rejudge`);
  * a failure the rule does not apply to counted as a confirmation, so every
    file operator had been "confirmed" without ever being seen to work (fixed:
    `rule_induction.judged_by`, and the learner holds back the latest success).

DESIGN. Each world hides one true rule: an act ZIM(x, y) produces RAN(x, y) iff a
hidden subset (1 to 4) of six candidate conditions holds, and sometimes consumes
one of them. The WORLD decides every outcome; the generator only chooses which
situations to show. Per world the teaching set varies:

  * 2 to 5 successes;
  * near-miss failures (every hidden condition but one) covering none, about
    half, or all of the hidden conditions;
  * 0 to 2 failures with most conditions missing (cases the right rule says
    nothing about);
  * one still world (all conditions, no act), so the act is necessary;
  * in a quarter of worlds, a near-miss for an UNCOVERED condition arrives last;
  * arrival order shuffled.

Demonstrations arrive one at a time and the learner's real authority step
(`_judge_signature`: re-judge, hold out, induce, record, validate) runs after
EVERY arrival, the worst case for the race that let a bad COPY rule through.
Every rule left executable is then scored against the world's full truth over all
64 situations of the six conditions.

DETERMINED world: at least 3 successes and a near-miss for every hidden
condition, so the evidence pins the rule down.

CHECKS (declared before the run):
  C1  no executable rule is contradicted by any demonstration of its act
  C2  every executable rule was validated on a held-out SUCCESS
  C3  no executable rule in a world shown only 2 successes
  C4  in determined worlds, no executable rule authorizes an act the world refuses
  C5  in determined worlds, no executable rule predicts the wrong effect
  C6  at least 95% of determined worlds end with an executable rule

Over-broad authority in UNDER-determined worlds is measured, not a failure: a rule
exactly as general as its evidence is what induction is for, and it is reported.

Run (sandbox only):
  POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/RULE-AUTHORITY-01/experiment.py [--worlds 1000] [--seed 20260930]
"""
import argparse
import asyncio
import itertools
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
os.environ.setdefault("LYRIC_NO_WATCHDOG", "1")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))

from experiments._evidence import RunRecord  # noqa: E402

ACT, EFFECT = "ZIM", "RAN"
#: Six candidate conditions over the act's two arguments (invented names).
CANDIDATES = (("KAV", ("x",)), ("MOR", ("x",)), ("TEL", ("y",)), ("SUN", ("y",)),
              ("PIR", ("x", "y")), ("DOV", ("y", "x")))
SITUATIONS = list(itertools.product((False, True), repeat=len(CANDIDATES)))

EV = RunRecord(
    "RULE-AUTHORITY-01",
    claim=("A learned operator gains the authority to act only when independent evidence "
           "has seen it work and nothing it applies to contradicts it."),
    hypothesis=("Across 1,000 hidden worlds with demonstrations arriving one at a time and the "
                "learner judging after each, no executable rule stands against the evidence, "
                "none lacks a held-out success, none follows from 2 successes, and determined "
                "worlds yield safe, correct operators at least 95% of the time."))


class World:
    """One hidden rule. The world, not the generator, decides each outcome."""

    def __init__(self, rng: random.Random):
        self.pre = sorted(rng.sample(range(len(CANDIDATES)), rng.randint(1, 4)))
        unary_x = [i for i in self.pre if CANDIDATES[i][1] == ("x",)]
        self.consumes = unary_x[0] if unary_x and rng.random() < 0.5 else None

    @staticmethod
    def facts(assignment, x, y):
        from core.learning.rule_induction import Fact
        out = []
        for on, (name, args) in zip(assignment, CANDIDATES):
            if on:
                out.append(Fact(name, tuple(x if a == "x" else y for a in args)))
        return out

    def step(self, before, x, y):
        """(after, fired) for ZIM(x, y) in `before`."""
        from core.learning.rule_induction import Fact
        held = set(before)
        fired = all(Fact(CANDIDATES[i][0], tuple(x if a == "x" else y for a in CANDIDATES[i][1]))
                    in held for i in self.pre)
        if not fired:
            return tuple(before), False
        after = set(before)
        if self.consumes is not None:
            after.discard(Fact(CANDIDATES[self.consumes][0], (x,)))
        after.add(Fact(EFFECT, (x, y)))
        return tuple(sorted(after, key=str)), True


def situation(world, rng, kind, missing=None):
    """Which conditions hold in a shown situation (the outcome is the world's)."""
    a = [rng.random() < 0.5 for _ in CANDIDATES]
    if kind == "success":
        for i in world.pre:
            a[i] = True
    elif kind == "near_miss":
        for i in world.pre:
            a[i] = i != missing
    elif kind == "unrelated":
        for i in world.pre:
            a[i] = False
    return a


def build_teaching(world, rng):
    n_succ = rng.randint(2, 5)
    q = rng.choice((0.0, 0.5, 1.0))
    covered = [i for i in world.pre if rng.random() < q]
    uncovered = [i for i in world.pre if i not in covered]
    shown = ([("success", None)] * n_succ + [("near_miss", i) for i in covered]
             + [("unrelated", None)] * rng.randint(0, 2))
    rng.shuffle(shown)
    late = None
    if uncovered and rng.random() < 0.25:
        late = rng.choice(uncovered)
        shown.append(("near_miss", late))
    factors = {"successes": n_succ, "coverage": q, "covered": len(covered) + (late is not None),
               "n_hidden": len(world.pre), "late": late is not None,
               "generator_covered_all": n_succ >= 3 and not uncovered}
    return shown, factors


#: The act itself is a literal a hypothesis may or may not contain: "the effect
#: follows from these conditions, whether or not anything is done" is a rival the
#: evidence has to rule out, and only a still world can.
ACT_LITERAL = len(CANDIDATES)


def well_formed(h) -> bool:
    """A rule may only conclude about what its own body binds: RAN(x, y) needs
    literals naming both x and y. (Amendment, first full run: the oracle had
    counted "SUN(y) -> RAN(x, y)" as a rival, which the rule language cannot
    express, and so called three worlds ambiguous that were not.)"""
    names = set()
    for j in h:
        names |= {"x", "y"} if j == ACT_LITERAL else set(CANDIDATES[j][1])
    return {"x", "y"} <= names


def minimal_hypotheses(pos_sets, neg_sets):
    """Every well-formed conjunction of literals (the six conditions and the act)
    consistent with what was shown, minimal ones only: an independent account of
    what the evidence determines."""
    universe = range(len(CANDIDATES) + 1)
    consistent = [set(h) for n in range(len(CANDIDATES) + 2)
                  for h in itertools.combinations(universe, n)
                  if well_formed(h)
                  and all(set(h) <= p for p in pos_sets)
                  and all(not set(h) <= q for q in neg_sets)]
    return [h for h in consistent if not any(o < h for o in consistent)]


def evidence_class(world, examples, shown_sets, still_set):
    """What the learner's own basis determines. Mirrors its hold-out: with three or
    more successes the latest success is held back for validation."""
    order = list(range(len(examples)))
    succ = [k for k in order if examples[k].positive]
    if len(succ) >= 3:
        order.remove(max(succ))
    elif len(succ) < 2:
        return "too_few_successes"
    acted = [shown_sets[k] | {ACT_LITERAL} for k in order]
    pos = [acted[n] for n, k in enumerate(order) if examples[k].positive]
    neg = [acted[n] for n, k in enumerate(order) if not examples[k].positive] + [set(still_set)]
    minimal = minimal_hypotheses(pos, neg)
    if len(minimal) > 1:
        return "ambiguous"
    if minimal == [set(world.pre) | {ACT_LITERAL}]:
        return "determined" if len(succ) >= 3 else "determined_unvalidatable"
    return "pins_other_rule"


async def run_world(i, run_tag, rng_seed, la, store, demos):
    from core.learning.rule_induction import Fact, TrainingExample, applies, derives, judged_by
    from core.learning.rule_store import EvidenceRole
    rng = random.Random(rng_seed)
    world = World(rng)
    shown, factors = build_teaching(world, rng)
    dom = f"ra01_{run_tag}_{i}"

    examples, statuses, shown_sets = [], [], []
    # One still world: every hidden condition, no act, no effect.
    still_assignment = situation(world, rng, "success")
    still_set = frozenset(j for j, on in enumerate(still_assignment) if on)
    still_before = tuple(World.facts(still_assignment, "s0", "s1"))
    await demos.append(TrainingExample(before=still_before, action=None, after=still_before,
                                       positive=False, evidence_id=f"{dom}:still"),
                       domain_id=dom)
    for k, (kind, missing) in enumerate(shown):
        x, y = f"o{k}a", f"o{k}b"
        assignment = situation(world, rng, kind, missing)
        shown_sets.append(frozenset(j for j, on in enumerate(assignment) if on))
        before = World.facts(assignment, x, y)
        if rng.random() < 0.3:
            before.append(Fact("KAV", (f"o{k}w",)))          # a fact about something else
        before = tuple(sorted(before, key=str))
        after, fired = world.step(before, x, y)
        ex = TrainingExample(before=before, action=Fact(ACT, (x, y)), after=after,
                             positive=fired, evidence_id=f"{dom}:d{k}")
        examples.append(ex)
        await demos.append(ex, domain_id=dom)
        summary, _, _ = await la._judge_signature(domain_id=dom, predicate=ACT, arity=2)
        statuses.append(summary.get("status"))

    executable = [r for r in await store.executable_rules(domain_id=dom)
                  if r.rule.action is not None and r.rule.action.predicate == ACT]
    positive_ids = {e.evidence_id for e in examples if e.positive}
    scored = []
    for r in executable:
        contradicted = sum(1 for e in examples if judged_by(r.rule, e) is False)
        val_pos = await store.evidence_roots(r.rule_id, {EvidenceRole.VALIDATION_POSITIVE})
        unsafe = wrong = 0
        for s in SITUATIONS:
            before = tuple(World.facts(s, "a", "b"))
            after, fired = world.step(before, "a", "b")
            ex = TrainingExample(before=before, action=Fact(ACT, ("a", "b")), after=after,
                                 positive=fired, evidence_id=None)
            if applies(r.rule, ex):
                if not fired:
                    unsafe += 1
                elif not derives(r.rule, ex):
                    wrong += 1
        scored.append({"rule_id": r.rule_id, "formula": str(r.rule),
                       "contradicted_by_shown": contradicted,
                       "validated_on_success": bool(set(val_pos) & positive_ids),
                       "unsafe_situations": unsafe, "wrong_effect_situations": wrong})
    all_rules = await store.load(domain_id=dom)
    refuted_late = sum(1 for r in all_rules
                       if r.status.value == "refuted" and "after it was validated" in (r.detail or ""))
    evidence = evidence_class(world, examples, shown_sets, still_set)
    return {"world": i, "hidden": [CANDIDATES[j][0] for j in world.pre], "evidence": evidence,
            "determined": evidence == "determined",
            "consumes": CANDIDATES[world.consumes][0] if world.consumes is not None else None,
            **factors, "shown": len(examples), "statuses": statuses, "executable": scored,
            "rules_total": len(all_rules), "refuted_after_validation": refuted_late}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260930)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    from core.database import get_database_manager
    from core.learning.demonstration_store import get_demonstration_store
    from core.learning.rule_store import get_rule_store
    from core.learning.unified_learning_system import get_learning_authority
    from experiments._domains import forget_domain

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    await db.assert_database_identity("lyric_dev")
    await EV.verify_database()
    store, demos, la = get_rule_store(), get_demonstration_store(), get_learning_authority()
    await store.ensure_schema()

    run_tag = uuid.uuid4().hex[:6]
    master = random.Random(args.seed)
    seeds = [master.randrange(2 ** 31) for _ in range(args.worlds)]
    sem = asyncio.Semaphore(args.concurrency)
    results, t0 = [], time.perf_counter()

    async def one(i):
        async with sem:
            try:
                results.append(await run_world(i, run_tag, seeds[i], la, store, demos))
            finally:
                await forget_domain(f"ra01_{run_tag}_{i}")
            if len(results) % 50 == 0:
                print(f"  {len(results)}/{args.worlds} worlds  ({time.perf_counter() - t0:.0f}s)",
                      flush=True)

    await asyncio.gather(*(one(i) for i in range(args.worlds)))
    elapsed = time.perf_counter() - t0
    results.sort(key=lambda r: r["world"])

    ex_rules = [(w, r) for w in results for r in w["executable"]]
    det = [w for w in results if w["determined"]]
    det_rules = [r for w in det for r in w["executable"]]
    two = [w for w in results if w["successes"] == 2]
    under = [w for w in results if w["evidence"] == "pins_other_rule"]

    c1 = sum(1 for _, r in ex_rules if r["contradicted_by_shown"])
    c2 = sum(1 for _, r in ex_rules if not r["validated_on_success"])
    c3 = sum(len(w["executable"]) for w in two)
    c4 = sum(r["unsafe_situations"] for r in det_rules)
    c5 = sum(r["wrong_effect_situations"] for r in det_rules)
    det_with = sum(1 for w in det if w["executable"])
    c6 = det_with / len(det) if det else 0.0
    amb = [w for w in results if w["evidence"] == "ambiguous"]
    c7 = sum(len(w["executable"]) for w in amb)
    import collections
    by_class = collections.Counter(w["evidence"] for w in results)
    agreement = collections.Counter((w["evidence"], w["statuses"][-1] if w["statuses"] else None)
                                    for w in results)

    EV.metric("worlds", len(results))
    EV.metric("demonstrations_shown", sum(w["shown"] for w in results))
    EV.metric("authority_judgements", sum(w["shown"] for w in results), note="one after every arrival")
    EV.metric("executable_rules", len(ex_rules))
    EV.metric("determined_worlds", len(det))
    EV.metric("determined_with_executable_rule", det_with)
    EV.metric("two_success_worlds", len(two))
    EV.metric("worlds_by_evidence", dict(by_class))
    EV.metric("final_learner_status_by_evidence", {f"{a} / {b}": n for (a, b), n in sorted(agreement.items(), key=str)})
    EV.metric("rules_refuted_after_validation", sum(w["refuted_after_validation"] for w in results))
    EV.metric("underdetermined_worlds_with_overbroad_authority",
              sum(1 for w in under if any(r["unsafe_situations"] for r in w["executable"])),
              note="licensed by the evidence shown; measured, not a failure")
    EV.metric("elapsed_s", round(elapsed, 1))

    checks = [
        ("C1 no executable rule is contradicted by a demonstration of its act", c1 == 0, f"{c1} of {len(ex_rules)}"),
        ("C2 every executable rule was validated on a held-out success", c2 == 0, f"{c2} without"),
        ("C3 no executable rule from only 2 successes", c3 == 0, f"{c3} in {len(two)} worlds"),
        ("C4 determined worlds: no act authorized that the world refuses", c4 == 0, f"{c4} unsafe situation(s)"),
        ("C5 determined worlds: no wrong predicted effect", c5 == 0, f"{c5} situation(s)"),
        ("C6 determined worlds end with an executable rule >= 95%", c6 >= 0.95,
         f"{det_with}/{len(det)} = {c6:.3f}"),
        ("C7 ambiguous worlds: no executable rule (no hypothesis picked without evidence)", c7 == 0,
         f"{c7} in {len(amb)} worlds"),
    ]
    print(f"  worlds by evidence: {dict(by_class)}")
    for label, ok, detail in checks:
        EV.check(label, ok, detail)
        print(f"  [{'PASS' if ok else 'FAIL'}] {label} — {detail}")
    EV.note(f"run tag {run_tag}; seed {args.seed}; every world's domain forgotten after it ran")

    left = await db.execute_query(
        "SELECT (SELECT count(*) FROM unified.learned_rules WHERE domain_id LIKE $1) r, "
        "(SELECT count(*) FROM unified.operator_demonstrations WHERE domain_id LIKE $1) d",
        (f"ra01_{run_tag}_%",), fetch_all=True)
    print(f"  residue after cleanup: {dict(left[0])}")
    path = EV.write()
    worlds_path = path.with_name(path.stem + "_worlds.json")
    worlds_path.write_text(json.dumps(results, indent=1))
    print(f"  per-world records: {worlds_path}")
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n==== RULE-AUTHORITY-01: {passed}/{len(checks)} checks passed over {len(results)} worlds "
          f"in {elapsed:.0f}s — {path} ====")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
