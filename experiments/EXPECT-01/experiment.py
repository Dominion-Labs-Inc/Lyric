#!/usr/bin/env python3
"""EXPECT-01 — Lyric expects things of a person's world, and the world not doing them is its own event.

The predictive intelligence system learns regularities from changes a world makes on its own, expects them, and
judges every reading against what it expects (core/intelligence/predictive_intelligence_system.py, WORLD
EXPECTATIONS). Here, on the running substrate in the SANDBOX, a person's office -- rooms are directories, a file's
kind is its extension -- is worked by another person, the harness, while Lyric only watches. Each change the other
person makes is read at once, as a perception would deliver it; Lyric's own readings come only when an expectation
falls due.

  A  LEARNED      pdfs arriving in the inbox are moved to DONE by the other person. With nothing done by Lyric,
                  the moves are learned as a regularity, and its delay from how long the moves took.
  B  RELIED ON    each later move it expected is a confirmation, until the regularity is relied on in her world.
  C  DEPARTED     a pdf the other person leaves behind lapses at its due time, by Lyric's own reading. Nothing
                  observed tells it apart from the pdfs that moved: the world departed. The regularity is not
                  refuted, and what Lyric does follows her operating mode -- Observe tells her, Assist offers,
                  Delegate forms a goal for her.
  D  WRONG        a txt in the inbox is never moved. If Lyric expected it to be, the miss is told apart by its kind:
                  Lyric was wrong, the regularity narrows, and nothing is done for her. No txt is expected after.
  E  A TENDENCY   in another of her worlds, docs are archived every other time. The regularity is never relied
                  on, and nothing is ever done for her.
  F  A RESTART    a pdf left behind with its expectation still waiting; a fresh process, past its due time, settles
                  it as a departure by its own reading.
  G  ABLATION     in a third world, every unmet expectation is charged to the regularity, as an act's outcome is:
                  the first departure refutes it, and the ones after go unnoticed.

Every expected value is written here before the run. Runs in the SANDBOX (`lyric_dev`) and does not empty it.
Removed at the end, by this run's ids: the worlds' rules, demonstrations and expectations, the memories they left,
her beliefs, mode, messages, memories and goal tasks.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 experiments/EXPECT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
             "TQDM_DISABLE": "1"}.items():
    os.environ.setdefault(k, v)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import boot, db, shutdown  # noqa: E402

EV = RunRecord(
    "EXPECT-01",
    claim=("Lyric learns what a person's world does on its own, expects it by a time it learned, and when the world "
           "does not do it, decides on evidence whether it was wrong (it learns) or the world departed (its own "
           "event, acted on as her operating mode allows). A tendency is never acted on, a waiting expectation "
           "survives a restart, and charging every miss to the regularity loses the departures."),
    hypothesis=("A departure missed, a confirmation taken for a departure, a refuted regularity after a departure, "
                "an action taken on a tendency or on Lyric's own mistake, a mode not honoured, an expectation lost "
                "at a restart, or an ablation that detects as much would each show here."))

#: How long the other person takes to move a file, in seconds.
DELAY = (0.6, 1.4)
#: Confirmations allowed for the regularity to become relied on before the run says it never did.
RELY_LIMIT = 60
SKIPS_PER_MODE = 2
MODES = ("observe", "assist", "delegate")
TXT_FILES = 4
TENDENCY_FILES = 16
WAIT_S = 90


def say(line=""):
    print(line, flush=True)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return bool(ok)


class Office:
    """A person's office: rooms are directories, a file's kind is its extension. Read from the disk alone."""

    ROOMS = ("INBOX", "DONE", "ARCHIVE")

    def __init__(self, root: Path):
        self.root = Path(root)
        for room in self.ROOMS:
            (self.root / room).mkdir(parents=True, exist_ok=True)

    def put(self, name: str, kind: str, room: str = "INBOX") -> None:
        (self.root / room / f"{name}.{kind}").write_text(name)

    def move(self, name: str, src: str, dst: str) -> None:
        for path in (self.root / src).glob(f"{name}.*"):
            path.rename(self.root / dst / path.name)

    def observe(self):
        from core.learning.rule_induction import Fact
        if not self.root.exists():
            return None
        facts = set()
        for room in self.ROOMS:
            directory = self.root / room
            if not directory.is_dir():
                continue
            facts.add(Fact("OPEN", (room,)))
            for entry in directory.iterdir():
                if entry.is_file() and "." in entry.name:
                    stem, kind = entry.name.split(".", 1)
                    facts.add(Fact("AT", (stem, room)))
                    facts.add(Fact("KIND", (stem, kind)))
        return frozenset(facts)

    def register(self, domain_id: str, owner: str) -> "Office":
        from core.perception.perception_faculty import set_owner
        from core.tools.tool_registry import OperatorBinding, get_binding_registry
        get_binding_registry().register(domain_id, OperatorBinding(
            predicate="MOVE", tool_name="move_file",
            parameters=lambda args: {"source_path": str(self.root / args[1] / args[0]),
                                     "destination_path": str(self.root / args[2] / args[0]),
                                     "create_dirs": False},
            observe=self.observe, description="an office: rooms are directories"))
        set_owner(domain_id, owner)
        return self


class Run:
    def __init__(self, state, coord):
        self.state = state
        self.coord = coord
        self.n = 0

    @property
    def intel(self):
        return self.coord.intelligence

    async def read(self, domain: str) -> None:
        """A reading of the world, as a perception delivers it when the world changes."""
        from core.perception.perception_faculty import observe_world_async
        await observe_world_async(domain)
        await self.intel.readings_settled()

    def name(self, kind: str) -> str:
        self.n += 1
        return f"{kind}{self.n:03d}"

    async def other_person_moves(self, office: Office, domain: str, name: str, src: str, dst: str) -> None:
        await asyncio.sleep(random.uniform(*DELAY))
        office.move(name, src, dst)
        await self.read(domain)

    async def expectations(self, domain: str):
        from core.agents.memory_agent import memory_agent
        return await memory_agent().expectations_of(domain_id=domain)

    async def settled(self, domain: str, wait_s: float = WAIT_S) -> list:
        """Wait until nothing is pending in this world (each due expectation read by Lyric's own clock)."""
        deadline = time.time() + wait_s
        while time.time() < deadline:
            rows = await self.expectations(domain)
            if all(r["status"] != "pending" for r in rows):
                return rows
            await asyncio.sleep(0.25)
        return await self.expectations(domain)

    async def regularities(self, domain: str):
        from core.learning.rule_store import get_rule_store
        return await get_rule_store().expectation_rules(domain_id=domain)

    async def learn(self, domain: str) -> None:
        await self.coord.learning.drain_pending_induction(limit=50)

    async def relied_on(self, domain: str, owner: str) -> bool:
        rules = await self.regularities(domain)
        return any([await self.coord.learning.regularity_relied_on(r, domain_id=domain) for r in rules])

    async def moved_pdf(self, office: Office, domain: str, kind: str = "pdf", src: str = "INBOX",
                        dst: str = "DONE", moved: bool = True) -> str:
        name = self.name(kind)
        office.put(name, kind, src)
        await self.read(domain)
        if moved:
            await self.other_person_moves(office, domain, name, src, dst)
        return name

    async def reacted(self, owner: str, expectation_id: str, wait_s: float = 60) -> bool:
        """Wait until the substrate has answered a departure (deferred, on its reactive worker): she was told
        about it, or a goal of its own formed for her."""
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if f"expect_{expectation_id}" in self.coord.task_queue.tasks_by_id:
                return True
            said = await db().execute_query(
                "SELECT 1 AS said FROM unified.outbox WHERE actor = $1 AND about = $2 LIMIT 1",
                (owner, expectation_id), fetch_one=True)
            if said:
                return True
            await asyncio.sleep(0.25)
        return False

    async def messages(self, owner: str):
        return await db().execute_query(
            "SELECT text, why, about FROM unified.outbox WHERE actor = $1 ORDER BY due_at", (owner,),
            fetch_all=True) or []


async def learn_regularity(run: Run, office: Office, domain: str, owner: str, kind: str = "pdf",
                           src: str = "INBOX", dst: str = "DONE") -> int:
    """Changes until a regularity is validated; returns how many it took."""
    for i in range(1, 30):
        await run.moved_pdf(office, domain, kind, src, dst)
        if i >= 3:
            await run.learn(domain)
            if await run.regularities(domain):
                return i
    return -1


async def rely(run: Run, office: Office, domain: str, owner: str) -> int:
    """Confirmations until the regularity is relied on in her world; -1 if it never was."""
    for i in range(RELY_LIMIT):
        if await run.relied_on(domain, owner):
            return i
        await run.moved_pdf(office, domain)
    return -1


async def phase_one(state) -> None:
    random.seed(state["seed"])
    system, coord = await boot()
    run = Run(state, coord)
    where = await db().execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox", where["d"] == "lyric_dev", where["d"])
    owner = state["owner"]
    work = Path(state["work"])
    try:
        main = state["domains"]["main"]
        office = Office(work / "office").register(main, owner)

        say("\n== A. Learned ==")
        took = await learn_regularity(run, office, main, owner)
        rules = await run.regularities(main)
        EV.metric("moves_to_validate", took, "count")
        check("the other person's moves are learned as a regularity, with Lyric doing nothing",
              took > 0 and bool(rules), f"{took} moves; {[str(r.rule) for r in rules]}")
        check("a regularity of the world, never an operator: nothing of it can be executed",
              all(not r.is_executable and r.rule.action is None for r in rules), [r.rule_kind for r in rules])
        from core.learning.demonstration_store import get_demonstration_store
        from core.learning.demonstration_store import regularity_signature
        sig = regularity_signature(rules[0].rule.effects) if rules else ("", 0)
        lags = await get_demonstration_store().lags(domain_id=main, predicate=sig[0], arity=sig[1])
        check("how long the change takes is learned from the moves", lags and 0 < max(lags.values()) < 10,
              f"{len(lags)} timed, longest {max(lags.values()) if lags else None:.2f}s")

        say("\n== B. Relied on ==")
        confirmations = await rely(run, office, main, owner)
        EV.metric("confirmations_to_rely", confirmations, "count")
        rows = await run.settled(main)
        confirmed = [r for r in rows if r["status"] == "confirmed"]
        check("each expected move is confirmed, until the regularity is relied on in her world",
              confirmations >= 0 and confirmed and all(r["status"] == "confirmed" for r in rows),
              f"{confirmations} confirmations; {len(confirmed)} confirmed of {len(rows)}")

        say("\n== D. Lyric was wrong ==")
        departures_before = coord.intelligence.expectation_stats["departures"]
        txt = []
        for _ in range(TXT_FILES):
            txt.append(await run.moved_pdf(office, main, kind="txt", moved=False))
        await run.settled(main)
        await run.learn(main)
        # The txt files' own expectations: a pdf filed late in B is not one of them.
        txt_ids = {r["expectation_id"] for r in await db().execute_query(
            "SELECT expectation_id FROM unified.held_expectations WHERE domain_id = $1 AND add_facts::text LIKE ANY($2)",
            (main, [f'%"AT({name}, %' for name in txt]), fetch_all=True) or []}
        txt_rows = [r for r in await run.expectations(main) if r["expectation_id"] in txt_ids]
        wrong = [r for r in txt_rows if r["attribution"] == "rule_evidence"]
        EV.metric("txt_expected", len(txt_rows), "count", "tentative expectations of a txt moving")
        check("no txt miss is taken for the world departing: each is Lyric's own mistake, or never expected",
              coord.intelligence.expectation_stats["departures"] == departures_before
              and all(r["attribution"] == "rule_evidence" for r in txt_rows),
              f"{len(txt_rows)} txt expectation(s), {len(wrong)} told apart")
        await run.moved_pdf(office, main, kind="txt", moved=False)
        rows = await run.expectations(main)
        check("after it, a txt in the inbox is not expected to move",
              not [r for r in rows if r["status"] == "pending"], [r["status"] for r in rows][-3:])
        await run.settled(main)
        msgs = await run.messages(owner)
        check("and nothing was said or done for her about a txt", not msgs, [m["text"][:60] for m in msgs])

        say("\n== C. Departed ==")
        from core.learning.rule_store import EpistemicStatus, get_rule_store
        detected = []
        for mode in MODES:
            await coord.capabilities.set_operating_mode(owner, mode)
            for _ in range(SKIPS_PER_MODE):
                await rely(run, office, main, owner)
                before = {r["expectation_id"] for r in await run.expectations(main)}
                left = await run.moved_pdf(office, main, moved=False)
                rows = await run.settled(main)
                new = [r for r in rows if r["expectation_id"] not in before]
                # Answered under the mode that holds when the substrate acts, so her mode is not changed until it has.
                answered = [await run.reacted(owner, r["expectation_id"]) for r in new if r["status"] == "unmet"]
                detected.append((mode, left, [(r["status"], r["attribution"]) for r in new], answered))
        ok = [d for d in detected if d[2] == [("unmet", "external_failure")] and d[3] == [True]]
        EV.metric("departures_detected", len(ok), "count", f"of {len(detected)} left behind")
        check("every pdf left behind lapses at its due time, by Lyric's own reading, as the world departing, and is answered",
              len(ok) == len(detected), detected)
        rules_after = await get_rule_store().load(domain_id=main)
        check("and the regularity is not refuted by it",
              any(r.status is EpistemicStatus.VALIDATED for r in rules_after),
              [(r.rule_id, r.status.value) for r in rules_after])
        from core.agents.autonomous.shared_types import TaskStatus
        msgs = await run.messages(owner)
        expected = [m for m in msgs if m["why"] == "expected"]
        told = [m for m in expected if "putting it right" not in m["text"]]
        offered = [m for m in msgs if m["why"] == "confirm" and m["text"].endswith("Shall I put it right?")]
        seeing = [m for m in expected if "I am putting it right" in m["text"]]
        ours = [q for tid, q in coord.task_queue.tasks_by_id.items() if tid.startswith("expect_")
                and getattr(q.task, "actor", None) == owner]
        held = [q.task for q in ours if q.status is TaskStatus.BLOCKED]
        goals = [q.task for q in ours if q.status is not TaskStatus.BLOCKED]
        EV.metric("told", len(told), "count")
        EV.metric("offered", len(offered), "count")
        EV.metric("goals", len(goals), "count")
        check("Observe: she is told what was expected and that it has not happened",
              len(told) == SKIPS_PER_MODE, [m["text"][:90] for m in told])
        check("Assist: she is asked whether it should be put right, and the goal waits for her yes",
              len(offered) == SKIPS_PER_MODE and len(held) == SKIPS_PER_MODE
              and {m["about"] for m in offered} == {t.id for t in held}, [m["text"][-40:] for m in offered])
        check("Delegate: a goal of Lyric's own forms for her, that the expected change holds",
              len(goals) == SKIPS_PER_MODE and len(seeing) == SKIPS_PER_MODE
              and all((g.provenance or {}).get("goal_conditions") for g in goals),
              [(g.id, (g.provenance or {}).get("goal_conditions")) for g in goals])
        # NO OPERATOR HERE: Lyric has not learned to move her files in this office, so each goal ends unreached,
        # and she is told so, as work she was told was taken on for her.
        ended = []
        deadline = time.time() + WAIT_S
        while time.time() < deadline:
            ended = [m for m in await run.messages(owner) if m["why"] == "work ended"
                     and m["about"] in {g.id for g in goals}]
            if len(ended) == len(goals):
                break
            await asyncio.sleep(0.5)
        check("and she is told how each goal ended", goals and len(ended) == len(goals),
              [m["text"][:120] for m in ended])

        say("\n== E. A tendency ==")
        tend = state["domains"]["tendency"]
        office_t = Office(work / "office_t").register(tend, owner)
        await coord.capabilities.set_operating_mode(owner, "delegate")
        took_t = await learn_regularity(run, office_t, tend, owner, kind="doc", src="DONE", dst="ARCHIVE")
        msgs_before = len(await run.messages(owner))
        for i in range(TENDENCY_FILES):
            await run.moved_pdf(office_t, tend, kind="doc", src="DONE", dst="ARCHIVE", moved=(i % 2 == 0))
        rows = await run.settled(tend)
        relied = await run.relied_on(tend, owner)
        msgs_after = len(await run.messages(owner))
        unmet = [r for r in rows if r["status"] == "unmet"]
        EV.metric("tendency_unmet", len(unmet), "count")
        check("a step taken every other time is never relied on, and nothing is done for her about it",
              took_t > 0 and not relied and msgs_after == msgs_before,
              f"learned after {took_t}; {len(unmet)} unmet; relied on: {relied}; messages {msgs_before}->{msgs_after}")

        say("\n== G. Ablation ==")
        abl = state["domains"]["ablation"]
        office_a = Office(work / "office_a").register(abl, owner)
        await learn_regularity(run, office_a, abl, owner)
        await rely(run, office_a, abl, owner)
        import core.intelligence.effect_verification as verification
        honest = verification.attribute_expectation

        def charged_to_the_rule(evidence, *, acted, separable):
            from core.intelligence.effect_verification import Attribution, ExpectationOutcome
            if evidence.outcome is ExpectationOutcome.CONTRADICTION and not acted:
                return Attribution.RULE_EVIDENCE, "ablation: every miss charged to the regularity"
            return honest(evidence, acted=acted, separable=separable)

        verification.attribute_expectation = charged_to_the_rule
        try:
            departed_before = coord.intelligence.expectation_stats["departures"]
            noticed = 0
            for _ in range(len(MODES) * SKIPS_PER_MODE):
                before = {r["expectation_id"] for r in await run.expectations(abl)}
                await run.moved_pdf(office_a, abl, moved=False)
                rows = await run.settled(abl)
                noticed += sum(1 for r in rows if r["expectation_id"] not in before and r["status"] == "unmet")
            departed = coord.intelligence.expectation_stats["departures"] - departed_before
        finally:
            verification.attribute_expectation = honest
        EV.metric("ablation_noticed", noticed, "count", f"of {len(MODES) * SKIPS_PER_MODE} left behind")
        survived = [r for r in await get_rule_store().load(domain_id=abl)
                    if r.status is EpistemicStatus.VALIDATED]
        check("charged to the regularity, a miss refutes it and no departure is ever raised, where her honest "
              "world kept its regularity through the same misses",
              departed == 0 and not survived and len(ok) == len(detected),
              f"departures {departed} (honest: {len(ok)}); validated after: {len(survived)}; noticed {noticed}")

        say("\n== F. A restart (left behind now, read after it) ==")
        await coord.capabilities.set_operating_mode(owner, "observe")
        await rely(run, office, main, owner)
        state["restart_file"] = await run.moved_pdf(office, main, moved=False)
        pending = [r for r in await run.expectations(main) if r["status"] == "pending"]
        state["restart_expectation"] = pending[0]["expectation_id"] if pending else None
        check("its expectation is waiting when the process stops", bool(pending), len(pending))
    finally:
        await shutdown(system)


async def phase_restart(state) -> None:
    owner = state["owner"]
    main = state["domains"]["main"]
    Office(Path(state["work"]) / "office").register(main, owner)
    system, coord = await boot()
    try:
        from core.agents.memory_agent import memory_agent
        deadline = time.time() + WAIT_S
        row = None
        while time.time() < deadline:
            rows = await memory_agent().expectations_of(domain_id=main)
            row = next((r for r in rows if r["expectation_id"] == state["restart_expectation"]), None)
            if row is not None and row["status"] != "pending":
                break
            await asyncio.sleep(0.5)
        check("after a restart it is settled, by the fresh process's own reading, as the world departing",
              row is not None and (row["status"], row["attribution"]) == ("unmet", "external_failure"),
              row and (row["status"], row["attribution"]))
        await Run(state, coord).reacted(owner, state["restart_expectation"])
        said = await db().execute_query(
            "SELECT text FROM unified.outbox WHERE actor = $1 AND why = 'expected' AND about = $2",
            (owner, state["restart_expectation"]), fetch_all=True) or []
        check("and she is told, as her mode (Observe) allows", len(said) == 1, [s["text"][:80] for s in said])
    finally:
        await shutdown(system)


async def cleanup(state) -> None:
    from core.agents.memory_agent import memory_agent
    from core.learning.rule_store import get_rule_store
    await db().initialize()
    agent = memory_agent()
    owner = state["owner"]
    domains = list(state["domains"].values())
    mdb = agent._memory_db()
    memories, demos, tasks = [], [], []
    for store in mdb.maintained_stores():
        for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
            memories += [r["memory_id"] for r in await mdb.execute_query(
                f"SELECT memory_id FROM {table} WHERE user_id = $1", (owner,), fetch_all=True, store=store) or []]
    for domain in domains:
        rows = await agent.expectations_of(domain_id=domain)
        memories += [r["memory_id"] for r in rows if r["memory_id"]]
        tasks += [f"expect_{r['expectation_id']}" for r in rows]
        demos += [r["evidence_id"] for r in await db().execute_query(
            "SELECT evidence_id FROM unified.operator_demonstrations WHERE domain_id = $1", (domain,),
            fetch_all=True) or []]
        await agent.forget_expectations(domain_id=domain)
        await get_rule_store().forget_domain(domain)
    await db().execute_query("DELETE FROM unified.operator_demonstrations WHERE evidence_id = ANY($1::text[])",
                             (demos,), commit=True)
    await db().execute_query("DELETE FROM unified.operator_induction_pending WHERE domain_id = ANY($1::text[])",
                             (domains,), commit=True)
    for store in mdb.maintained_stores():
        for table in ("memory_hot.memory_hot", "memory_cold.memory_cold"):
            await mdb.execute_query(f"DELETE FROM {table} WHERE memory_id = ANY($1::text[])", (memories,),
                                    commit=True, store=store)
        await mdb.execute_query("DELETE FROM unified.experience_pool WHERE memory_id = ANY($1::text[])",
                                (memories,), commit=True, store=store)
        await mdb.execute_query("DELETE FROM unified.scoped_beliefs WHERE scope_actor = $1", (owner,),
                                commit=True, store=store)
    # THE PLANNING ENGINE'S GOALS FOR THEM, and their plans: left active, a later boot of anyone's would take them
    # up again and act in a world that no longer exists.
    patterns = [f"[substrate goal] Put right what was expected in {d}:%" for d in domains]
    goals = [r["id"] for r in await db().execute_query(
        "SELECT id FROM unified.goals WHERE description LIKE ANY($1::text[])", (patterns,), fetch_all=True) or []]
    await db().execute_query("DELETE FROM unified.plans WHERE goal_id = ANY($1::text[])", (goals,), commit=True)
    await db().execute_query("DELETE FROM unified.goals WHERE id = ANY($1::text[])", (goals,), commit=True)
    await db().execute_query("DELETE FROM unified.outbox WHERE actor = $1", (owner,), commit=True)
    await db().execute_query("DELETE FROM unified.operating_modes WHERE person = $1", (owner,), commit=True,
                             store="runtime")
    await db().execute_query("DELETE FROM unified.task_queue WHERE task_id = ANY($1::text[])", (tasks,), commit=True)
    say(f"\n    removed by id: {len(domains)} worlds' rules and expectations, {len(demos)} demonstrations, "
        f"{len(memories)} memories, her goal tasks, beliefs, mode and messages")


def _printed(name, ok, detail=""):
    print("CHECK\t" + json.dumps({"name": name, "ok": bool(ok), "detail": str(detail)}), flush=True)
    return bool(ok)


def restart_main(state_path: str) -> int:
    global check
    check = _printed
    state = json.loads(Path(state_path).read_text())
    try:
        asyncio.run(phase_restart(state))
    finally:
        asyncio.run(cleanup(state))
    return 0


async def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="expect01_"))
    nonce = uuid.uuid4().hex[:6]
    state = {"nonce": nonce, "seed": int(nonce, 16), "work": str(work), "owner": f"expect_{nonce}",
             "domains": {k: f"expect01_{k}_{nonce}" for k in ("main", "tendency", "ablation")}}
    started = time.time()
    try:
        await phase_one(state)
    finally:
        (work / "state.json").write_text(json.dumps(state))
    if state.get("restart_expectation"):
        out = subprocess.run([sys.executable, __file__, "--restart", str(work / "state.json")],
                             capture_output=True, text=True, env={**os.environ}, timeout=1800)
        recorded = 0
        for line in out.stdout.splitlines():
            if line.startswith("CHECK\t"):
                c = json.loads(line.split("\t", 1)[1])
                check(c["name"], c["ok"], c["detail"])
                recorded += 1
            elif line.startswith("    "):
                say(line)
        check("the restarted process ran to its end", out.returncode == 0 and recorded == 2,
              f"exit {out.returncode}; {recorded} checks" + ("" if out.returncode == 0 else f"; {out.stderr[-600:]}"))
    else:
        await cleanup(state)
    shutil.rmtree(work, ignore_errors=True)
    EV.metric("seconds", round(time.time() - started, 1), "s")
    EV.note(f"nonce {nonce}")
    await EV.verify_database()
    EV.write()
    passed = sum(1 for c in EV.checks if c.passed)
    say(f"\n{passed}/{len(EV.checks)} passed")
    return 0 if passed == len(EV.checks) else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--restart":
        raise SystemExit(restart_main(sys.argv[2]))
    raise SystemExit(asyncio.run(main()))
