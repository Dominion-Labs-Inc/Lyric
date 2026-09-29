#!/usr/bin/env python3
"""CANARY-01 — what a person gives the substrate stays in that person's context.

Part 1 of M2 (`docs/research/MEMORY_AGENT_MAP.md` §8.2, M2a). Unique markers are planted in what one person gives
the substrate through its real doors, and in a note of the substrate's own. After the work, every table of the
substrate's memory is searched for them. Nothing in this harness says whose work anything is: each door is given
only what a caller would give it.

  A  LESSON     the substrate's own, taught through the learning authority: a robin is a bird, a bird is an animal
  B  TELL       the person tells it through the front door (`handle_user_request`) that a <marker> is a robin
  C  ASK        the person asks through the front door whether a <marker> is an animal: answered by reasoning over
                their fact and the lesson, the way the conversation reasons (through the neural bridge). They also
                ask what a <marker> is that nothing held can place, so it is looked up. Reasoning is done for their
                work through `reason_about`, over a cause, a rule and an observation of theirs, so the causal and
                the abductive reasoning write something down
  D  TASK       the person gives a job through the front door: read their note, which holds a marker. The job runs
                to its end on the task loop, so every memory a finished task makes is made
  E  IMAGE      the person's image, carrying a marker in a QR code, is seen through `see`, given their identity;
                while it is in view they give a second job, so a memory of theirs forms in the window it is stamped in
  F  OWN        a note of the substrate's own, written with no one's work under way
  G  MEMORIES   every memory row holding the person's markers is theirs (a stored image belongs to its memory);
                the memory `see` made of their image is theirs; the substrate's note is its own; every memory is
                stamped only with what its own owner was perceiving, and theirs, formed while their image was in
                view, carries it. Which paths kept anything is reported, so a path that kept nothing is not
                mistaken for one that kept it safely
  H  THE REST   every other table of memory: where an owner can be recorded, a person's marker is under them;
                tables with no owner that hold one are reported. Nothing of each kind of the person's work is in a
                table of the substrate's own; their argument, the cause and the explanation reasoned for them are
                kept as theirs; what their image showed is held in their context
  I  MAIN       the main model's store is untouched
  J  POOL       each experience waits in the pool as a candidate, in its owner's store. The person's job, their
                telling and question, the reasoning over their fact, the look-up of their word and the seeing of
                their image are each theirs and hold their marker, with each part saying where it came from. A job
                and a question of the substrate's own, put on the task queue as its own loops do, are its own. The
                substrate's recall finds nothing of the person's work

Runs in the SANDBOX (`torinai_dev`), emptied first by `scripts/reset_dev_store.py`.

Run: ./venv_torin/bin/python3 experiments/CANARY-01/experiment.py
"""
from __future__ import annotations

import asyncio
import inspect
import os
import random
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("POSTGRES_DATABASE", "torinai_dev")
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from experiments._evidence import RunRecord  # noqa: E402


def _token(prefix: str) -> str:
    return prefix + "".join(random.choice(string.ascii_lowercase) for _ in range(9))


MQ, MT, MS, MO = _token("zq"), _token("zt"), _token("zs"), _token("zo")
MR, MI, MK = _token("zr"), _token("zi"), _token("zk")
MC, MH = _token("zc"), _token("zh")
PERSON_ID = _token("canary-person-")
SESSION = _token("canary-session-")

EV = RunRecord(
    "CANARY-01",
    claim=("What a person gives the substrate through its doors -- a question, a job, an image -- is held in that "
           "person's context and in no memory of anyone else's, while what the substrate does on its own is its "
           "own."),
    hypothesis=("A marker from the person found in a memory row of the substrate's, or under another owner in a "
                "table that records owners, would show a leak here."))
TRANSCRIPT = []


def say_line(line=""):
    TRANSCRIPT.append(line)
    print(line)


def check(name, ok, detail=""):
    EV.check(name, bool(ok), detail)
    say_line(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main_store_rows() -> int:
    """Rows in the main model's store, counted over its own connection."""
    import asyncpg
    c = await asyncpg.connect(host="localhost", port=5433, user="stefan", database="torinai_db")
    try:
        n = 0
        for t in await c.fetch(
                "select table_schema s, table_name n from information_schema.tables "
                "where table_schema in ('unified','memory_hot','memory_cold') and table_type='BASE TABLE'"):
            n += await c.fetchval(f'select count(*) from "{t["s"]}"."{t["n"]}"')
        return n
    finally:
        await c.close()


def _memory_tables():
    sys.path.insert(0, str(ROOT / "scripts"))
    from separation_map import MEMORY_TABLES
    return sorted(MEMORY_TABLES)


#: Columns that say whose a row is, in the tables that have one.
OWNER_COLUMNS = ("user_id", "owner", "scope_actor", "speaker")

#: Tables whose rows are parts of a memory (the image a memory kept), and so whoever's the memory is. Only
#: these: a row that merely points at a memory (a belief about it) sits where it sits, and reading its owner
#: through the memory would hide it.
MEMORY_PARTS = ("unified.memory_media",)
MEMORY_OWNER = ("(SELECT m.user_id FROM memory_hot.memory_hot m WHERE m.memory_id = t.memory_id"
                " UNION ALL SELECT c.user_id FROM memory_cold.memory_cold c WHERE c.memory_id = t.memory_id"
                " LIMIT 1)")


async def where_marker(db, marker: str):
    """Every memory table holding `marker` anywhere in a row, with the owners recorded on those rows (or None
    when the table records no owner)."""
    found = {}
    for table in _memory_tables():
        schema, name = table.split(".")
        exists = await db.execute_query(
            "SELECT 1 AS x FROM information_schema.tables WHERE table_schema = $1 AND table_name = $2",
            (schema, name), fetch_one=True)
        if not exists:
            continue
        columns = {r["column_name"] for r in await db.execute_query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2",
            (schema, name), fetch_all=True) or []}
        owner = next((c for c in OWNER_COLUMNS if c in columns), None)
        if owner:
            select = f"t.{owner} AS owner"
        elif table in MEMORY_PARTS:
            owner, select = "its memory's owner", f"{MEMORY_OWNER} AS owner"
        else:
            select = "NULL AS owner"
        rows = await db.execute_query(
            f'SELECT {select} FROM "{schema}"."{name}" AS t WHERE t::text LIKE $1',
            (f"%{marker}%",), fetch_all=True) or []
        if rows:
            found[table] = {"owner_column": owner, "owners": sorted({str(r["owner"]) for r in rows}),
                            "rows": len(rows)}
    return found


async def settle(agent):
    """Let the writes already under way land: background tasks started by the work, then the memory agent's
    queue. The queue's worker keeps running (`drain_writes` would retire it)."""
    for _ in range(2):
        await asyncio.sleep(4)
        await asyncio.wait_for(agent._write_queue.join(), timeout=60)


async def pool_item(db, task_id, wait_s=90):
    """The pool's item for a finished task, once the memory agent's worker has decided it."""
    deadline = time.time() + wait_s
    row = None
    while time.time() < deadline:
        row = await db.execute_query(
            "SELECT item_id, owner, status, decision, parts::text AS parts FROM unified.experience_pool"
            " WHERE about = $1 ORDER BY created_at DESC LIMIT 1", (task_id,), fetch_one=True)
        if row and row["status"] == "decided":
            return row
        await asyncio.sleep(2)
    return row


async def pool_items(db, kind, marker, wait_s=90):
    """Every item of one kind in the pool holding `marker`, once the memory agent's worker has decided them."""
    deadline = time.time() + wait_s
    rows = []
    while time.time() < deadline:
        rows = await db.execute_query(
            "SELECT item_id, owner, kind, status, decision, parts::text AS parts FROM unified.experience_pool"
            " WHERE kind = $1 AND parts::text LIKE $2 ORDER BY created_at", (kind, f"%{marker}%"),
            fetch_all=True) or []
        if rows and all(r["status"] == "decided" for r in rows):
            return rows
        await asyncio.sleep(2)
    return rows


async def job(coord, message, *, metadata, wait_s=240):
    """Through the front door, as the person, and wait for the task loop to finish it."""
    meta = {"actor_identity": PERSON_ID, "session_id": SESSION, **metadata}
    ack = await coord.handle_user_request(message, source="api", metadata=meta)
    if not ack.get("task_id"):
        return ack
    from core.agents.autonomous.shared_types import TaskSource, actor_for
    person = actor_for(TaskSource.MANUAL, PERSON_ID)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        result = await coord.get_task_result(ack["task_id"], actor=person)
        if result.get("status") in ("completed", "failed", "not_found"):
            return {**result, "task_id": ack["task_id"]}
        await asyncio.sleep(2)
    return {"status": "still_running", "task_id": ack["task_id"]}


async def main() -> int:
    main_before = await main_store_rows()
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    where = await db.execute_query("SELECT current_database() AS d", (), fetch_one=True)
    check("the run is in the sandbox", where["d"] == "torinai_dev", f"connected to {where['d']}")
    if where["d"] != "torinai_dev":
        return 1
    import contextlib
    import io
    boot_log = io.StringIO()
    with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
        from core.main import get_system
        system = get_system()
        await system.start()
    check("the substrate is running", system.autonomous_coordinator is not None and system.running)
    try:
        return await _run(db, system.autonomous_coordinator, main_before)
    finally:
        with contextlib.redirect_stdout(boot_log), contextlib.redirect_stderr(boot_log):
            await system.shutdown()


async def _run(db, coord, main_before: int) -> int:
    from core.agents.autonomous.shared_types import TaskSource, actor_for
    from core.learning import get_learning_authority
    from core.memory import get_memory_agent
    agent = await get_memory_agent()
    person = actor_for(TaskSource.MANUAL, PERSON_ID)
    front = {"actor_identity": PERSON_ID, "session_id": SESSION}
    say_line(f"    the person: {person}; markers: their fact and question {MQ}, their job {MT}, own {MS}")
    work = Path(tempfile.mkdtemp(prefix="canary01_"))

    say_line("\n== A. The substrate's own lesson ==")
    learning = get_learning_authority()
    for subject, obj in (("robin", "bird"), ("bird", "animal")):
        adm = await learning.learn_fact(subject, "isa", obj, domain="canary_01", quality=0.95)
        say_line(f"    a {subject} is a {obj}: admitted={getattr(adm, 'admitted', adm)}")

    say_line("\n== B. The person tells it something, through the front door ==")
    told = await coord.handle_user_request(f"A {MQ} is a robin.", source="api", metadata=front)
    say_line(f"    reply: {str(told.get('reply') or told.get('answer') or told)[:300]}")

    say_line("\n== C. The person asks, through the front door ==")
    asked = await coord.handle_user_request(f"Is a {MQ} an animal?", source="api", metadata=front)
    reply = str(asked.get("reply") or asked.get("answer") or asked)
    say_line(f"    reply: {reply[:300]}")
    check("the question was answered by reasoning over their fact and the lesson", reply.lower().startswith("yes"),
          reply[:120])
    looked_up = await coord.handle_user_request(f"What is a {MR}?", source="api", metadata=front)
    say_line(f"    a word nothing held places: {str(looked_up.get('answer') or looked_up)[:300]}")
    # Reasoning done for their work, through the door a job reasons through (`reason_about`, told whose it
    # is): a cause among their premises, and a rule with an observation to explain. What the kinds of thinking
    # write down -- the cause traced, the explanation proposed -- is theirs.
    from core.memory import Origin
    reasoned = await coord.reason_about(
        f"what would cause the {MC} pump leak",
        context={"premises": [f"{MC} seal wear causes {MC} pump leak", f"{MC}_pump_leak"],
                 "rules": [f"{MH}_valve_stuck -> {MC}_pump_leak"]},
        origin=Origin.of(person, "task"))
    say_line(f"    reasoned for their work: {str(getattr(reasoned, 'answer', reasoned))[:200]}; "
             f"route {((getattr(reasoned, 'metadata', None) or {}).get('route'))}")

    say_line("\n== D. A job, through the front door, run to its end ==")
    note = work / f"{MT}_note.txt"
    note.write_text(f"My note: the {MT} pump in bay 4 is broken and leaks oil.\n")
    done = await job(coord, f"Read my note about the {MT} pump.",
                     metadata={"parameters": {"tool_plan": [{"tool": "read_file",
                                                             "args": {"file_path": str(note)}}]}})
    say_line(f"    job: {done.get('status')}; {str(done.get('result') or done.get('error'))[:300]}")
    check("the job ran to its end and succeeded", done.get("status") == "completed", f"{done.get('status')}")

    say_line("\n== E. An image, through `see` ==")
    import numpy as np
    import cv2
    image = work / "photo.png"
    code = cv2.QRCodeEncoder.create().encode(MI)
    code = cv2.resize(code, (code.shape[1] * 6, code.shape[0] * 6), interpolation=cv2.INTER_NEAREST)
    code = cv2.copyMakeBorder(code, 24, 24, 24, 24, cv2.BORDER_CONSTANT, value=255)
    side = code.shape[0]
    frame = np.full((side, side + 160, 3), 255, np.uint8)
    frame[:, :side] = cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)
    frame[40:side - 40, side + 30:side + 130] = (0, 0, 255)
    cv2.imwrite(str(image), frame)
    takes_identity = "actor_identity" in inspect.signature(coord.see).parameters
    check("`see` takes whose image it is, as the front door takes whose message it is", takes_identity,
          "it takes a source (where the image came from) and no identity" if not takes_identity else "")
    if not takes_identity:
        say_line("    `see` cannot be told whose image this is; the image step is not run")
        seen = None
    else:
        seen = await coord.see(str(image), source="upload", actor_identity=PERSON_ID)
    say_line(f"    seen: {bool(seen)}")
    # While their image is still in view, the person gives a second job. A finished job's record is never merged
    # into an earlier one, so a new memory of theirs forms inside the window a memory is stamped in.
    second_note = work / "second_note.txt"
    second_note.write_text("My second note: the valve in bay 5 is fine.\n")
    in_view = await job(coord, "Read my second note about the valve.",
                        metadata={"parameters": {"tool_plan": [{"tool": "read_file",
                                                                "args": {"file_path": str(second_note)}}]}})
    say_line(f"    a job while it was in view: {in_view.get('status')}")

    say_line("\n== F. A note of the substrate's own ==")
    from core.memory import Origin
    ok, own_id = await agent.store_memory(content=f"The substrate's own note: {MS} came up in its own work.",
                                          tags=["canary_01"], importance_score=0.9,
                                          origin=Origin.own("CANARY-01"))
    say_line(f"    stored: {ok} {own_id}")

    await settle(agent)

    say_line("\n== G. Memory rows ==")
    tiers = ("memory_hot.memory_hot", "memory_cold.memory_cold", "unified.memory_media")
    found = {}
    for label, marker in (("fact and question", MQ), ("look-up", MR), ("job", MT), ("image", MI),
                          ("cause", MC), ("hypothesis", MH),
                          ("own", MS)):
        found[label] = await where_marker(db, marker)
        say_line(f"    {label} ({marker}):")
        for table, info in sorted(found[label].items()):
            say_line(f"      {table}: {info['rows']} row(s), owners {info['owners']} "
                     f"(by {info['owner_column'] or 'no owner column'})")

    def memory_owners(label):
        owners = set()
        for table in tiers:
            owners |= set(found[label].get(table, {}).get("owners", []))
        return owners

    for label in ("fact and question", "look-up", "job", "image"):
        owners = memory_owners(label)
        check(f"the person's {label} reached memory, and every memory row holding it is theirs",
              owners == {person}, f"owners {sorted(owners) or 'none'}")
    # THE memory `see` made of their image, by the id the percept carries back: other seeings (the substrate's
    # own, of its environment) form vision memories at the same time and are not this one.
    seen_memory = (getattr(seen, "metadata", None) or {}).get("memory_id") if seen else None
    seen_rows = (await db.execute_query(
        "SELECT memory_id, user_id FROM memory_hot.memory_hot WHERE memory_id = $1",
        (seen_memory,), fetch_all=True) or []) if seen_memory else []
    seen_owners = sorted({str(r["user_id"]) for r in seen_rows})
    check("the memory `see` made of the person's image is theirs", seen_rows and seen_owners == [person],
          f"{len(seen_rows)} memory(ies), owners {seen_owners or 'none'}")
    import json as _stamp_json
    stamped = await db.execute_query(
        "SELECT user_id, (thinking_state::jsonb)->'perceptual_state'->'perceptions' AS seen"
        " FROM memory_hot.memory_hot WHERE thinking_state::jsonb ? 'perceptual_state'", (), fetch_all=True) or []
    crossed, theirs_stamped = [], 0
    for row in stamped:
        owner = row["user_id"] or None
        seen_then = row["seen"]
        seen_then = _stamp_json.loads(seen_then) if isinstance(seen_then, str) else (seen_then or [])
        crossed += [(owner, p.get("owner"), p.get("source")) for p in seen_then
                    if (p.get("owner") or None) != owner]
        theirs_stamped += owner == person
    check("every memory is stamped only with what its own owner was perceiving", stamped and not crossed,
          f"{len(stamped)} stamped memories; crossed {crossed[:3]}")
    check("a memory of the person's formed while their image was in view carries it", theirs_stamped > 0,
          f"{theirs_stamped} of theirs stamped")
    own = memory_owners("own")
    check("the substrate's own note is its own", own and own <= {"None", "", "__substrate__"},
          f"owners {sorted(own)}")

    bridge = await db.execute_query(
        "SELECT user_id FROM memory_hot.memory_hot WHERE tags::jsonb ? 'reasoning' AND content LIKE $1",
        (f"%{MQ}%",), fetch_all=True) or []
    task_end = await db.execute_query(
        "SELECT user_id FROM memory_hot.memory_hot WHERE (tags::jsonb ? 'task_knowledge' "
        "OR tags::jsonb ? 'task_execution') AND content LIKE $1", (f"%{MT}%",), fetch_all=True) or []
    say_line(f"    the reasoning bridge kept a memory of the question: {len(bridge)} "
             f"(owners {sorted({str(r['user_id']) for r in bridge})})")
    say_line(f"    the task-end record of what the job found and the tools it used: {len(task_end)} "
             f"(owners {sorted({str(r['user_id']) for r in task_end})})")
    EV.metric("reasoning memories of the person's question", len(bridge))
    EV.metric("task-end records of the person's job", len(task_end))

    say_line("\n== H. The rest of memory ==")
    open_tables = {}
    for label in ("fact and question", "look-up", "job", "image", "cause", "hypothesis"):
        for table, info in found[label].items():
            if table in tiers:
                continue
            if info["owner_column"]:
                check(f"{table} holds the person's {label} only under them", info["owners"] == [person],
                      f"owners {info['owners']}")
            else:
                open_tables.setdefault(table, []).append(label)
    say_line("    tables with no owner column holding a person's marker (M2b gives them owners):")
    for table, labels in sorted(open_tables.items()):
        say_line(f"      {table}: {', '.join(labels)}")
    EV.metric("owner-less tables holding a person's marker", len(open_tables),
              note="; ".join(f"{t}: {','.join(l)}" for t, l in sorted(open_tables.items())))
    for label in ("fact and question", "look-up", "job", "image", "cause", "hypothesis"):
        leaked = sorted(t for t, labels in open_tables.items() if label in labels)
        check(f"nothing of the person's {label} is in a table of the substrate's own", not leaked,
              f"{leaked or 'none'}")
    # Kept as theirs, not merely absent from the substrate's: each was written, under them.
    for label, table, what in (("fact and question", "unified.reasoning_arg_claims", "the argument over their answer"),
                               ("cause", "unified.reasoning_temporal_propositions", "the cause in their premises, as reasoned"),
                               ("hypothesis", "unified.hypotheses", "the explanation proposed for their observation")):
        held = found[label].get(table, {})
        check(f"{what} is kept as theirs", held.get("owners") == [person], f"{held or 'not written'}")
    in_context = found["image"].get("unified.scoped_concept_relations", {})
    check("what their image showed is held in their context", in_context.get("owners") == [person],
          f"{in_context or 'not held'}")

    say_line("\n== J. The pool ==")
    import json as _json
    from core.agents.autonomous.shared_types import Priority, SUBSTRATE_ACTOR, Task, TaskSource, TaskType
    theirs = await pool_item(db, done.get("task_id")) if done.get("task_id") else None
    decision = (theirs["decision"] if theirs and isinstance(theirs["decision"], dict)
                else _json.loads(theirs["decision"]) if theirs and theirs["decision"] else {})
    say_line(f"    the person's job: {dict(theirs) if theirs else None}"[:400])
    check("the person's job is an experience in the pool, theirs, holding their marker",
          theirs is not None and theirs["owner"] == person and MT in (theirs["parts"] or ""),
          f"owner {theirs['owner'] if theirs else None}")
    check("the memory agent decided it: a candidate, waiting for the lift and the gate",
          decision.get("standing") == "candidate", f"{decision}")
    shared = [p for p in _json.loads(theirs["parts"]) if p["source"] in ("substrate", "world")] if theirs else []
    check("it holds what the substrate did, apart from what was theirs",
          any(p["role"] == "step" for p in shared) and any(p["role"] == "tool_run" for p in shared),
          f"{[(p['role'], p['source']) for p in shared]}")

    own_note = work / f"{MO}_own.txt"
    own_note.write_text(f"The substrate's own note: {MO}.\n")
    own_task = Task(id=f"canary_own_{MO}", type=TaskType.ANALYSIS, description=f"Read the {MO} note.",
                    priority=Priority.HIGH, source=TaskSource.AUTONOMOUS,
                    metadata={"parameters": {"tool_plan": [{"tool": "read_file",
                                                            "args": {"file_path": str(own_note)}}]}})
    await coord.task_queue.add_task(own_task, priority=Priority.HIGH)
    ours = await pool_item(db, own_task.id, wait_s=240)
    check("a job of the substrate's own is its own experience in the pool",
          ours is not None and ours["owner"] is None and MO in (ours["parts"] or ""),
          f"{dict(ours) if ours else None}"[:200])

    def parts_of(row):
        return _json.loads(row["parts"])

    def holds(part, marker):
        return marker in _json.dumps(part["content"], default=str)

    def shown(rows):
        return [[(p["role"], p["source"]) for p in parts_of(r)] for r in rows][:2]

    talk = await pool_items(db, "conversation", MQ)
    check("the person's telling and question are experiences in the pool, theirs, holding their words",
          len(talk) >= 2 and all(r["owner"] == person for r in talk)
          and all(any(p["source"] == "person" and holds(p, MQ) for p in parts_of(r)) for r in talk),
          f"{len(talk)} item(s), owners {sorted({str(r['owner']) for r in talk})}")
    check("how the substrate took each of them is its own part",
          talk and all(any(p["role"] == "route" and p["source"] == "substrate" for p in parts_of(r))
                       for r in talk), f"{shown(talk)}")

    thought = await pool_items(db, "reasoning", MQ)
    premises = [p for r in thought for p in parts_of(r) if p["role"] == "premise"]
    check("the reasoning over their fact is an experience in the pool, theirs",
          thought and all(r["owner"] == person for r in thought),
          f"{len(thought)} item(s), owners {sorted({str(r['owner']) for r in thought})}")
    check("their fact is their premise; the lesson it reasoned from is the substrate's, holding nothing of theirs",
          any(p["source"] == "person" and holds(p, MQ) for p in premises)
          and any(p["source"] == "substrate" and holds(p, "bird") for p in premises)
          and not any(p["source"] == "substrate" and holds(p, MQ) for p in premises),
          f"{[(p['source'], p['content'].get('kind'), p['content'].get('statement')) for p in premises][:6]}")

    looked = await pool_items(db, "research", MR)
    parts = [p for r in looked for p in parts_of(r)]
    check("the look-up of their word is an experience in the pool, theirs",
          looked and all(r["owner"] == person for r in looked),
          f"{len(looked)} item(s), owners {sorted({str(r['owner']) for r in looked})}")
    check("the word is their part, the query it sent out is its own, and what came back is the world's",
          any(p["role"] == "asked" and p["source"] == "person" and holds(p, MR) for p in parts)
          and any(p["role"] == "query" and p["source"] == "substrate" for p in parts)
          and all(p["source"] == "world" for p in parts if p["role"] in ("source", "finding", "error")),
          f"{shown(looked)}")

    seeing = await pool_items(db, "perception", MI)
    check("the seeing of their image is an experience in the pool, theirs, holding what was seen in it",
          seeing and all(r["owner"] == person for r in seeing)
          and all(any(p["role"] == "perceived" and p["source"] == "person" and holds(p, MI)
                      for p in parts_of(r)) for r in seeing),
          f"{len(seeing)} item(s), owners {sorted({str(r['owner']) for r in seeing})}; {shown(seeing)}")

    decided = talk + thought + looked + seeing
    standings = [(r["decision"] if isinstance(r["decision"], dict)
                  else _json.loads(r["decision"] or "{}")).get("standing") for r in decided]
    check("the memory agent decided each of them, and said why",
          decided and all(r["status"] == "decided" for r in decided) and all(standings),
          f"{sorted(set(map(str, standings)))}")
    for kind, rows in (("conversation", talk), ("reasoning", thought), ("research", looked),
                       ("perception", seeing)):
        EV.metric(f"the person's {kind} experiences in the pool", len(rows))

    own_question = Task(id=f"canary_know_{MK}", type=TaskType.ANALYSIS, description=f"What is a {MK}?",
                        priority=Priority.HIGH, source=TaskSource.AUTONOMOUS)
    await coord.task_queue.add_task(own_question, priority=Priority.HIGH)
    own_research = await pool_items(db, "research", MK, wait_s=240)
    own_talk = await pool_items(db, "conversation", MK)
    check("a question of the substrate's own, looked up on its own, is its own experience in the pool",
          own_research and own_talk and all(r["owner"] is None for r in own_research + own_talk),
          f"research {[str(r['owner']) for r in own_research]}, conversation "
          f"{[str(r['owner']) for r in own_talk]}")

    recalled = {label: len(await agent.postgres_storage.search_by_content(marker, actor=SUBSTRATE_ACTOR,
                                                                          limit=20) or [])
                for label, marker in (("job", MT), ("fact and question", MQ), ("look-up", MR),
                                      ("image", MI))}
    check("the substrate's own recall finds nothing of the person's work", not any(recalled.values()),
          f"{recalled}")

    say_line("\n== I. The main store ==")
    main_after = await main_store_rows()
    check("the main model's store is untouched", main_after == main_before,
          f"{main_before} rows before, {main_after} after")

    record = EV.write()
    transcript = record.with_name(record.stem + "_transcript.md")
    transcript.write_text("# CANARY-01 transcript\n\n```\n" + "\n".join(TRANSCRIPT) + "\n```\n")
    say_line(f"\n{EV.passed}/{EV.passed + EV.failed} passed")
    say_line(f"  run record: {record.relative_to(ROOT)}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    reset = subprocess.run([sys.executable, str(ROOT / "scripts" / "reset_dev_store.py")],
                           capture_output=True, text=True)
    print(reset.stdout.strip() or reset.stderr.strip())
    if reset.returncode != 0:
        sys.exit("the sandbox could not be emptied; not running")
    sys.exit(asyncio.run(main()))
