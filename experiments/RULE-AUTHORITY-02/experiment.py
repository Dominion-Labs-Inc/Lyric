#!/usr/bin/env python3
"""RULE-AUTHORITY-02: authority to act, benchmarked independently of Lyric.

RULE-AUTHORITY-01 measured the right property in a way a reviewer could not trust: its worlds were built from
Lyric's own `Fact`, its hidden rules were exactly the rules Lyric's language can say, its oracle was amended to
that language and mirrored the learner's hold-out, and its scoring called Lyric's own `applies`, `derives` and
`judged_by`. Every world was one template (one act, one effect, the same six conditions).

Here three parts keep apart:

  generator.py   standard library only. Writes every world before Lyric runs, in two files: what is shown
                 (worlds_public.jsonl) and the answers (worlds_truth.jsonl), with SHA-256 of both in manifest.json.
                 Hidden rules come from three families, two of them outside a conjunction-only language.
  this runner    the only part that loads Lyric. Opens worlds_public.jsonl ONLY, feeds each observation through
                 the learner's real authority step (`_judge_signature`, after every arrival), and writes the rules
                 left with authority as plain text (answers.jsonl).
  evaluator.py   standard library only, run as its own isolated process. Checks the hashes, decides what the
                 evidence settles by its own account, and scores the plain-text rules against the world's truth
                 with its own matcher.

The checks are the evaluator's (see its docstring); the learner's own bookkeeping (rules refuted after validation)
is recorded beside them as reported by Lyric, never as a check.

Run on the benchmark's own instance, `lyric_bench` (lyric_dev's schema, no data; nothing else uses it):
  POSTGRES_DATABASE=lyric_bench ./venv_lyric/bin/python3 experiments/RULE-AUTHORITY-02/experiment.py --worlds 10000 --seed 20261026

NOT lyric_dev. Every session working on Lyric shares lyric_dev, and what one runs there (a reset, a sweep, a drain
of the whole store's pending learning) acts on another's data mid-run.
"""
import argparse
import asyncio
import gc
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_bench")
os.environ.setdefault("LYRIC_NO_WATCHDOG", "1")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE.parent))

from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "RULE-AUTHORITY-02",
    claim=("A learned operator gains the authority to act only when independent evidence has seen it work and "
           "nothing it applies to contradicts it, judged by a generator and an evaluator that share no code or "
           "representation with Lyric."),
    hypothesis=("Over worlds whose hidden rules include forms Lyric cannot express, no rule left with authority "
                "is contradicted by what was shown or follows from fewer than three successes; where the "
                "evidence settles the rule, no rule authorizes an act the world refuses or predicts a wrong "
                "effect, and where it settles a conjunctive rule Lyric ends with that rule or none, most often "
                "that rule; where it does not, no rule holds authority."))


async def run_world(w, run_tag, la, store, demos):
    from core.learning.rule_induction import Fact, TrainingExample
    dom = f"ra02_{run_tag}_{w['world']}"
    statuses = []
    for k, o in enumerate(w["observations"]):
        action = Fact.parse(o["action"]) if o["action"] else None
        ex = TrainingExample(before=tuple(Fact.parse(f) for f in o["before"]), action=action,
                             after=tuple(Fact.parse(f) for f in o["after"]),
                             positive=action is not None and set(o["after"]) != set(o["before"]),
                             evidence_id=f"{dom}:o{k}")
        await demos.append(ex, domain_id=dom)
        if action is not None:
            summary, _, _ = await la._judge_signature(domain_id=dom, predicate=w["act"], arity=w["arity"])
            statuses.append(summary.get("status"))
    executable = [r for r in await store.executable_rules(domain_id=dom)
                  if r.rule.action is not None and r.rule.action.predicate == w["act"]]
    rules = [{"body": sorted(str(f) for f in r.rule.body), "add": sorted(str(f) for f in r.rule.effects.add),
              "delete": sorted(str(f) for f in r.rule.effects.delete)} for r in executable]
    all_rules = await store.load(domain_id=dom)
    refuted_late = sum(1 for r in all_rules
                       if r.status.value == "refuted" and "after it was validated" in (r.detail or ""))
    return {"world": w["world"], "rules": rules, "statuses": statuses, "rules_total": len(all_rules),
            "refuted_after_validation": refuted_late, "shown": len(w["observations"])}


def isolated(script, *args):
    """Run a benchmark script as its own process: -I keeps the repository and user packages off its path."""
    return subprocess.run([sys.executable, "-I", str(HERE / script), *map(str, args)], cwd="/",
                          check=True, capture_output=True, text=True).stdout


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=10000)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    run_dir = EV.results_dir / f"{EV.started_at.strftime('%Y%m%dT%H%M%SZ')}_run"
    manifest = json.loads(isolated("generator.py", "--worlds", args.worlds, "--seed", args.seed,
                                   "--outdir", run_dir))
    print(f"  worlds frozen before Lyric ran: {manifest}", flush=True)

    from core.database import get_database_manager
    from core.learning.demonstration_store import get_demonstration_store
    from core.learning.rule_store import get_rule_store
    from core.learning.unified_learning_system import get_learning_authority
    from experiments._domains import forget_domain

    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    await db.assert_database_identity("lyric_bench")
    await EV.verify_database()
    store, demos, la = get_rule_store(), get_demonstration_store(), get_learning_authority()
    await store.ensure_schema()

    # Workers read the worlds one at a time. Holding all of them, and a task per world, made the cyclic garbage
    # collector walk that heap over and over: measured 2026-10-27, a 10,000-world run spent more of its time in
    # gc_collect_main than in running the learner, at about 3 s a world. Freezing moves what setup built out of
    # the collector's reach.
    gc.freeze()
    total = manifest["worlds"]
    run_tag = uuid.uuid4().hex[:6]
    answers, t0 = [], time.perf_counter()

    async def worker(lines):
        for line in lines:
            w = json.loads(line)
            try:
                answers.append(await run_world(w, run_tag, la, store, demos))
            finally:
                await forget_domain(f"ra02_{run_tag}_{w['world']}")
            if len(answers) % 500 == 0:
                print(f"  {len(answers)}/{total} worlds  ({time.perf_counter() - t0:.0f}s)", flush=True)

    with open(run_dir / "worlds_public.jsonl") as f:
        lines = iter(f)
        await asyncio.gather(*(worker(lines) for _ in range(args.concurrency)))
    elapsed = time.perf_counter() - t0
    answers.sort(key=lambda a: a["world"])
    with open(run_dir / "answers.jsonl", "w") as f:
        for a in answers:
            f.write(json.dumps(a) + "\n")

    print(isolated("evaluator.py", "--inputs", run_dir, "--answers", run_dir / "answers.jsonl",
                   "--out", run_dir / "evaluation.json"), end="")
    evaluation = json.loads((run_dir / "evaluation.json").read_text())

    for c in evaluation["checks"]:
        EV.check(c["label"], c["passed"], c["detail"])
    for name, value in evaluation["metrics"].items():
        EV.metric(name, value)
    EV.metric("observations_shown", sum(a["shown"] for a in answers))
    EV.metric("authority_judgements", sum(len(a["statuses"]) for a in answers), note="one after every act shown")
    EV.metric("rules_refuted_after_validation", sum(a["refuted_after_validation"] for a in answers),
              note="reported by Lyric, not judged by the evaluator")
    EV.metric("elapsed_s", round(elapsed, 1))
    EV.note(f"run tag {run_tag}; seed {args.seed}; every world's domain forgotten after it ran; "
            f"inputs, answers and per-world evaluation in {run_dir.name}/")

    left = await db.execute_query(
        "SELECT (SELECT count(*) FROM unified.learned_rules WHERE domain_id LIKE $1) r, "
        "(SELECT count(*) FROM unified.operator_demonstrations WHERE domain_id LIKE $1) d",
        (f"ra02_{run_tag}_%",), fetch_all=True)
    print(f"  residue after cleanup: {dict(left[0])}")
    path = EV.write()
    passed = sum(1 for c in evaluation["checks"] if c["passed"])
    print(f"\n==== RULE-AUTHORITY-02: {passed}/{len(evaluation['checks'])} checks passed over {len(answers)} "
          f"worlds in {elapsed:.0f}s: {path} ====")
    return 0 if passed == len(evaluation["checks"]) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
