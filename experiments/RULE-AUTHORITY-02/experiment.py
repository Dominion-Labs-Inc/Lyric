#!/usr/bin/env python3
"""RULE-AUTHORITY-02: authority to act, benchmarked independently of Lyric, on the whole running system.

RULE-AUTHORITY-01 measured the right property in a way a reviewer could not trust: its worlds were built from
Lyric's own `Fact`, its hidden rules were exactly the rules Lyric's language can say, its oracle was amended to
that language and mirrored the learner's hold-out, and its scoring called Lyric's own `applies`, `derives` and
`judged_by`. Every world was one template (one act, one effect, the same six conditions).

Here three parts keep apart:

  generator.py   standard library only. Writes every world before Lyric runs, in two files: what the world offers
                 (worlds_public.jsonl: its act, the acts it lets Lyric practise, the goals it asks for) and the
                 answers (worlds_truth.jsonl), with SHA-256 of both in manifest.json. Hidden rules come from three
                 families, two of them outside a conjunction-only language. Its `serve` mode IS the worlds: a
                 separate process that holds the hidden rules and works out what each act Lyric sends does.
  this runner    the only part that loads Lyric, and it starts the whole system (`_isolation.boot`). Each world is
                 an outside service Lyric reaches with its own `http_request` tool: the act is bound to that tool,
                 the world is read by looking at the service. Lyric practises the acts the world offers through its
                 own explorer, under its constitution; its own learner drains what that recorded; then the world's
                 goals are handed to its coordinator, which plans with whatever it has learned, acts or does not,
                 observes, and learns from what happened. The runner reads nothing of the truth and decides
                 nothing: it writes the rules left with authority and what Lyric reported of each goal
                 (answers.jsonl).
  evaluator.py   standard library only, run as its own isolated process. Checks the hashes, reads every act the
                 world received from the world's own log, decides what that evidence settles by its own account,
                 and scores the plain-text rules and the goal reports against the world's truth.

The checks are the evaluator's (see its docstring); the learner's own bookkeeping (rules refuted after validation)
is recorded beside them as reported by Lyric, never as a check.

Run on the benchmark's own instance, `lyric_bench` (nothing else uses it), which the runner makes again before every
run as a copy of Lyric's home, `lyric_bench_home` (`fresh_instance`): lyric_dev's schema, and what Lyric held after
booting on it once and meeting the place it runs in. The home is made the first time it is needed, or again with
--home. Run from the Lyric folder, the place Lyric's home is:
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
import urllib.error
import urllib.request
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
    hypothesis=("Over worlds whose hidden rules include forms Lyric cannot express, which the whole running system "
                "practises in and then pursues goals in through its own tools, planner and constitution: no rule "
                "left with authority is contradicted by an outcome it saw (that the noise did not turn) or follows "
                "from fewer than three successes; where what it saw settles a conjunctive rule, Lyric ends with "
                "that rule or none, most often that rule, and no rule authorizes an act the world refuses or "
                "predicts a wrong effect; where it leaves several, no rule holds authority; where it settles a rule "
                "no conjunction can say, no rule acts where the world refuses or predicts a wrong effect; and "
                "Lyric never reports a goal reached that the world did not reach."))

#: Acts tried in one exploration cycle, as the explorer's own default.
MAX_ACTIONS = 8


class World:
    """One world, as Lyric meets it: an outside service it acts on with its `http_request` tool and reads by
    looking. Nothing here knows the world's rule; the service works out what each act does."""

    def __init__(self, public, port, domain_id):
        from core.learning.rule_induction import Fact
        self.public, self.domain_id = public, domain_id
        self.base = f"http://127.0.0.1:{port}/w/{public['world']}"
        self.practice = [Fact.parse(a) for a in public["practice"]]
        self.offerable = self.practice + [Fact.parse(a) for a in public["more"]]
        self.offered = 0
        #: How far into what it offers the world goes: the first practice, then everything.
        self.limit = len(self.practice)

    def look(self):
        """What holds in the world now, or None when it cannot be read."""
        from core.learning.rule_induction import Fact
        try:
            with urllib.request.urlopen(f"{self.base}/look") as answer:
                return frozenset(Fact.parse(f) for f in json.load(answer)["facts"])
        except urllib.error.HTTPError:
            return None

    def parameters(self, args):
        return {"url": f"{self.base}/act", "method": "POST",
                "data": dict(zip(self.public["args"], (str(a) for a in args)))}

    def propose(self):
        """The acts the world lets Lyric practise, those not yet offered first: its first practice, then more of the
        same kind whenever Lyric explores again, whose things the world brings as it offers them."""
        batch = self.offerable[self.offered:self.limit][:MAX_ACTIONS]
        arriving = self.offered + len(batch) - max(self.offered, len(self.practice))
        if arriving > 0:
            request = urllib.request.Request(f"{self.base}/offer", data=json.dumps({"count": arriving}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(request) as answer:
                answer.read()
        self.offered += len(batch)
        return batch

    def register(self):
        from core.learning.exploration import register_explorable_domain
        from core.tools.tool_registry import OperatorBinding, get_binding_registry
        get_binding_registry().register(self.domain_id, OperatorBinding(
            predicate=self.public["act"], tool_name="http_request", parameters=self.parameters,
            observe=self.look, description="a world served over HTTP: the act is a request to it, and what holds "
                                           "is read from it"))
        register_explorable_domain(self.domain_id, self.propose)
        return self


async def learned(db, domain_id):
    """Until Lyric's own learner has drained what this world's acts recorded."""
    while (await db.execute_query(
            "SELECT count(*) AS c FROM unified.operator_induction_pending WHERE domain_id = $1",
            (domain_id,), fetch_one=True))["c"]:
        await asyncio.sleep(0.05)


async def ended(coordinator, task_id):
    """Until Lyric's queue holds the task as ended, and the ended record of it."""
    from core.agents.autonomous.shared_types import TaskStatus
    done = (TaskStatus.VERIFIED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
            TaskStatus.PARTIALLY_COMPLETE, TaskStatus.BLOCKED)
    while True:
        queued = coordinator.task_queue.tasks_by_id.get(task_id)
        if queued is not None and queued.status in done:
            return queued
        await asyncio.sleep(0.05)


async def run_world(public, run_tag, port, coordinator, db, store):
    from core.agents.autonomous.shared_types import Priority, Task, TaskType
    from core.learning.exploration import SubstrateExplorer

    dom = f"ra02_{run_tag}_{public['world']}"
    world = World(public, port, dom).register()
    practice = []
    while world.offered < len(world.practice):
        cycle = await SubstrateExplorer().explore(dom, world.propose, max_actions=MAX_ACTIONS)
        practice.append({k: cycle.get(k, 0) for k in ("acted", "positive", "negative", "contrastive", "refused",
                                                       "interfered")})
    world.limit = len(world.offerable)
    await learned(db, dom)

    goals = []
    for k, conditions in enumerate(public["goals"]):
        task = Task(id=f"ra02_{run_tag}_{public['world']}_g{k}", type=TaskType.EXECUTION,
                    description=f"bring about {', '.join(conditions)}", priority=Priority.MEDIUM,
                    provenance={"domain_id": dom, "goal_conditions": conditions})
        # HANDED TO LYRIC AS WORK IS: queued, drawn by its own worker, validated, and, when it cannot be reached,
        # diagnosed and learned toward and tried again, all as the coordinator's task lifecycle does it.
        began = time.perf_counter()
        await coordinator.task_queue.add_task(task, priority=Priority.MEDIUM)
        queued = await ended(coordinator, task.id)
        result = (queued.task.result if queued is not None else None) or {}
        goals.append({"goal": k, "conditions": conditions, "success": result.get("success") is True,
                      "task_status": queued.status.value if queued is not None else None,
                      "task_error": str(queued.error_message or "")[:200] if queued is not None else None,
                      "retries": queued.task.retry_count if queued is not None else None,
                      "status": str(result.get("planning_status") or result.get("status") or ""),
                      "error": str(result.get("error") or "")[:200],
                      "seconds": round(time.perf_counter() - began, 2)})
        await learned(db, dom)

    # THE ANSWER IS WHAT LYRIC HOLDS NOW, and the world is retired with it: its act is unbound, so nothing Lyric
    # still has in hand for it (a deferred reaction to a goal it could not reach) acts there after this. The
    # evaluator judges these rules on what Lyric had seen by this moment.
    from core.learning.exploration import unregister_explorable_domain
    from core.tools.tool_registry import get_binding_registry
    get_binding_registry().clear(dom)
    unregister_explorable_domain(dom)
    answered_at = time.time()
    executable = [r for r in await store.executable_rules(domain_id=dom)
                  if r.rule.action is not None and r.rule.action.predicate == public["act"]]
    # AND WHERE ITS CONSTITUTION LETS IT ACT ON THE RULE: each success of the act, as the conditions of the things it
    # names that held in it. Law 2 sends an act back to planning where something holds that held in no success, or
    # where two conditions of which every success held one both do not (`untested_conditions`). The evaluator reads
    # the rule alone for C1 to C7, and the rule with these for what Lyric would actually do (C8).
    from core.learning.demonstration_store import get_demonstration_store
    from core.learning.unified_learning_system import success_conditions
    shown = await get_demonstration_store().load(domain_id=dom, predicate=public["act"], arity=len(public["args"]))
    rules = [{"body": sorted(str(f) for f in r.rule.body), "add": sorted(str(f) for f in r.rule.effects.add),
              "delete": sorted(str(f) for f in r.rule.effects.delete),
              "absent": sorted(str(f) for f in r.rule.absent),
              "successes": [sorted(str(f) for f in held) for held in success_conditions(r.rule, shown)]}
             for r in executable]
    all_rules = await store.load(domain_id=dom)
    refuted_late = sum(1 for r in all_rules
                       if r.status.value == "refuted" and "after it was validated" in (r.detail or ""))
    return {"world": public["world"], "answered_at": answered_at, "rules": rules, "goals": goals,
            "practice": practice,
            "rules_total": len(all_rules), "refuted_after_validation": refuted_late}


HOME = "lyric_bench_home"


def _postgres():
    pg = Path(os.environ.get("LYRIC_PG_BIN", "/opt/homebrew/opt/postgresql@16/bin"))
    where = ["-h", os.environ.get("POSTGRES_HOST", "localhost"), "-p", os.environ.get("POSTGRES_PORT", "5433")]
    return pg, where


def fresh_instance():
    """`lyric_bench` as the benchmark defines it, made again before every run: a copy of Lyric's home. What a run
    leaves (concepts Lyric would transfer from, the outcomes and evidence of every world it ran) is not where the next
    one starts; where Lyric lives is. Made with no rows at all, every run's Lyric met the place it runs in as a new
    one and read up to 400 of its files, each read holding every world for as long as it took (minutes, 2026-10-27).
    Only `lyric_bench` is ever dropped."""
    assert os.environ["POSTGRES_DATABASE"] == "lyric_bench", "RULE-AUTHORITY-02 runs on lyric_bench only"
    pg, where = _postgres()
    held = subprocess.run([pg / "psql", *where, "-Atc", f"SELECT 1 FROM pg_database WHERE datname = '{HOME}'",
                           "postgres"], check=True, capture_output=True, text=True).stdout.strip()
    if not held:
        subprocess.run([sys.executable, __file__, "--home"], check=True,
                       env={**os.environ, "POSTGRES_DATABASE": HOME})
    subprocess.run([pg / "dropdb", *where, "--if-exists", "--force", "lyric_bench"], check=True)
    subprocess.run([pg / "createdb", *where, "-T", HOME, "lyric_bench"], check=True)


async def make_home() -> int:
    """Lyric's home: lyric_dev's schema, then Lyric booted on it once, until it has met the place it runs in, and
    stopped. Meeting it is registering it as an environment domain (`_situate`), which is what every later boot finds
    and so does not meet it as new. What the encounter goes on to do, reading up to 400 of the place's files on the
    event loop (`_react_investigate_environment`), is not waited for: no boot had been seen to finish it (no
    "Investigated environment" in Lyric's log since 2026-10-26), and the read in progress ends with the boot."""
    assert os.environ["POSTGRES_DATABASE"] == HOME, f"Lyric's home is made on {HOME} only"
    pg, where = _postgres()
    subprocess.run([pg / "dropdb", *where, "--if-exists", "--force", HOME], check=True)
    subprocess.run([pg / "createdb", *where, HOME], check=True)
    schema = subprocess.run([pg / "pg_dump", *where, "--schema-only", "--no-owner", "lyric_dev"],
                            check=True, capture_output=True).stdout
    subprocess.run([pg / "psql", *where, "-q", "-v", "ON_ERROR_STOP=1", HOME], input=schema, check=True,
                   capture_output=True)
    from experiments._isolation import boot, shutdown
    system, coordinator = await boot()
    environment = coordinator._environment
    assert environment is not None and environment["novel"], "Lyric did not meet its home as a new place"
    await shutdown(system)
    print(f"  Lyric met its home: {environment['identity']}, domain {environment['domain_id']}", flush=True)
    return 0


def isolated(script, *args):
    """Run a benchmark script as its own process: -I keeps the repository and user packages off its path."""
    return subprocess.run([sys.executable, "-I", str(HERE / script), *map(str, args)], cwd="/",
                          check=True, capture_output=True, text=True).stdout


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=10000)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--noise", action="store_true", help="the noisy arm (generator.NOISE)")
    ap.add_argument("--home", action="store_true", help=f"make Lyric's home ({HOME}) again, and nothing else")
    args = ap.parse_args()
    if args.home:
        return await make_home()
    if args.seed is None:
        ap.error("--seed is required for a run")

    fresh_instance()
    run_dir = EV.results_dir / f"{EV.started_at.strftime('%Y%m%dT%H%M%SZ')}_run"
    manifest = json.loads(isolated("generator.py", "--worlds", args.worlds, "--seed", args.seed,
                                   "--outdir", run_dir, *(["--noise"] if args.noise else [])))
    print(f"  worlds frozen before Lyric ran: {manifest}", flush=True)
    # THE WORLDS STAND IN THEIR OWN PROCESS, started from the generator's own file and never imported here.
    service = subprocess.Popen([sys.executable, "-I", str(HERE / "generator.py"), "serve", "--inputs", run_dir,
                                "--log", run_dir / "world_log.jsonl"],
                               cwd="/", stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    port = json.loads(service.stdout.readline())["port"]

    from experiments._isolation import boot, shutdown
    from core.learning.rule_store import get_rule_store
    from experiments._domains import forget_domain

    system, coordinator = await boot()
    from core.database import get_database_manager
    db = get_database_manager()
    await db.assert_database_identity("lyric_bench")
    await EV.verify_database()
    store = get_rule_store()
    await store.ensure_schema()

    gc.freeze()
    total = manifest["worlds"]
    run_tag = uuid.uuid4().hex[:6]
    answers, t0 = [], time.perf_counter()

    async def worker(lines):
        for line in lines:
            public = json.loads(line)
            answers.append(await run_world(public, run_tag, port, coordinator, db, store))
            if len(answers) % 100 == 0:
                print(f"  {len(answers)}/{total} worlds  ({time.perf_counter() - t0:.0f}s)", flush=True)

    try:
        with open(run_dir / "worlds_public.jsonl") as f:
            lines = iter(f)
            await asyncio.gather(*(worker(lines) for _ in range(args.concurrency)))
        elapsed = time.perf_counter() - t0
        # WHAT THE WORLDS LEFT IN LYRIC IS REMOVED ONCE IT HAS STOPPED: forgetting a domain while a deferred reaction
        # still validates a rule there raced it (a rule's evidence written between the two deletes).
        await shutdown(system)
    finally:
        service.stdin.close()
        service.wait()
    if not getattr(db, "initialized", False):
        await db.initialize()
    for a in answers:
        await forget_domain(f"ra02_{run_tag}_{a['world']}")
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
    for name in ("acted", "positive", "negative", "contrastive", "refused", "interfered"):
        EV.metric(f"practice_{name}", sum(c[name] for a in answers for c in a["practice"]),
                  note="as Lyric's explorer reported it")
    EV.metric("goals_reported_reached", sum(g["success"] for a in answers for g in a["goals"]),
              note=f"of {sum(len(a['goals']) for a in answers)} goals, as Lyric reported them")
    EV.metric("rules_refuted_after_validation", sum(a["refuted_after_validation"] for a in answers),
              note="reported by Lyric, not judged by the evaluator")
    EV.metric("elapsed_s", round(elapsed, 1))
    EV.note(f"run tag {run_tag}; seed {args.seed}; noise {manifest.get('noise')}; the whole system booted on "
            f"lyric_bench; every world's domain forgotten after it ran; inputs, the world's log, answers and "
            f"per-world evaluation in {run_dir.name}/")

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
