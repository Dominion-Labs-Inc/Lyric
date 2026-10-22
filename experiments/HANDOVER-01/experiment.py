"""HANDOVER-01: a running Lyric hands over to a new instance of itself without going down, and without cutting
anyone's conversation off.

Two whole Lyrics (core/main.py) on the sandbox line (lyric_dev), in a world of their own: a real Tet field and
world, in this process, on sockets in work/, with an inhabitant key made for the run and two people in it. The
microphone and camera stay off. Nothing reaches the live world: the instances are told this world's address, and no
environment file names another.

  A. Instance A starts in the world and serves person A: "Is a cat an animal?", then "Is it a mammal?".
  B. scripts/handover.py hands over to instance B, recorded step by step.
  C. While A still holds person A's conversation, person A's next turn ("Is it a mammal?" again) is answered by A,
     passed to it by B; person B, new, is answered by B. (The sandbox line holds cats, not dogs.)
  D. Once person A has been quiet for the quiet period, A is stopped: its door and record are gone, and B is the
     one in the world.
  E. Person A's next turn is answered by B.
  F. Every turn was answered.

Run (from the Lyric folder; it starts two Lyrics on lyric_dev and stops both):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/HANDOVER-01/experiment.py
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
WORK = HERE / "work"
#: How long a person goes unheard before their conversation counts as over, for this run: longer than the new
#: instance takes to start, so person A is still in conversation with A when the handover switches (at 45 s, B's
#: start outlasted it, A held no one, and was stopped at once).
QUIET = 300
LOOK_EVERY = 2.0


def say(*a):
    print(*a, flush=True)


def world():
    """A Tet field and world in this process, with two people in it and an inhabitant key of this run's."""
    from Tet.authority import (Authority, Entitlements, PolicyStore, PrincipalRegistry, generate_ed25519,
                               load_ed25519_public)
    from Tet.gateway import Gateway
    from Tet.space import TetSpace
    from Tet.walls import Field, WorldRuntime, serve
    people = {"person_a": os.urandom(32), "person_b": os.urandom(32)}
    allowed = Entitlements(capabilities=frozenset({"world.message"}), actions=frozenset(),
                           executables=frozenset(), exec_argv={}, resource_limits={}, trust="trusted",
                           max_classification=5)
    gate = Gateway(TetSpace(), Authority(PrincipalRegistry(dict(people)),
                                         PolicyStore({p: allowed for p in people})), door_depth=1)
    link = os.urandom(32)
    field_sock, world_sock = str(WORK / "field.sock"), str(WORK / "world.sock")
    threading.Thread(target=serve, args=(field_sock,), kwargs={"field": Field(gate, link)}, daemon=True).start()
    private, public = generate_ed25519()
    runtime = WorldRuntime(field_sock, world_sock, link_secret=link, checkpoint_key=os.urandom(32),
                           inhabitant_key=load_ed25519_public(public))
    threading.Thread(target=runtime._pull_loop, daemon=True).start()
    threading.Thread(target=runtime._serve_lyric, daemon=True).start()
    return field_sock, world_sock, private, people


def environment(world_sock: str, private: str) -> dict:
    return dict(os.environ, POSTGRES_DATABASE="lyric_dev", TET_WORLD_ADDRESS=world_sock,
                TET_OPERATOR_PRIVATE_KEY=private, LYRIC_INSTANCES_DIR=str(WORK / "instances"),
                LYRIC_HANDOVER_RECORD=str(WORK / "handovers.jsonl"), LYRIC_MICROPHONE="off", LYRIC_CAMERA="off",
                LYRIC_BACKUP_DIR=str(WORK / "backups"), PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")


def instances() -> dict:
    found = {}
    for record in (WORK / "instances").glob("*.json"):
        try:
            found[record.stem] = json.loads(record.read_text())
        except ValueError:
            continue
    return found


def health(record: dict) -> dict:
    request = urllib.request.Request(record["door"] + f"/health?quiet={QUIET}",
                                     headers={"Authorization": f"Bearer {record['key']}"})
    with urllib.request.urlopen(request) as answer:
        return json.loads(answer.read())


def stop_all(processes) -> None:
    """Every Lyric this run started is stopped, however the run ends: the ones it started itself, and any an
    instance record names."""
    mine = {p.pid for p in processes}
    others = {r["pid"] for r in instances().values()} - mine
    for pid in {p.pid for p in processes if p.poll() is None} | others:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for process in processes:
        process.wait()                              # its own: reaped, never polled (a dead child polls as alive)
    for pid in others:
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(LOOK_EVERY)


def main() -> int:
    started = []
    try:
        return run(started)
    finally:
        stop_all(started)


def run(started) -> int:
    from experiments._evidence import RunRecord
    EV = RunRecord("HANDOVER-01",
                   claim="a running Lyric hands over to a new instance of itself without going down, without "
                         "losing a turn and without cutting a conversation off",
                   hypothesis="each check below holds")
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "instances").mkdir(parents=True)
    field_sock, world_sock, private, people = world()
    env = environment(world_sock, private)
    from Tet.walls import ExternalClient
    answers = []

    def turn(person: str, text: str) -> str:
        reply = ExternalClient(field_sock, person, people[person]).message(text).get("result")
        answer = (reply or {}).get("answer") if isinstance(reply, dict) else reply
        answers.append((person, text, answer))
        say(f"  {person}: {text!r} -> {answer!r}" + ("" if answer else f"  (the whole reply: {reply!r})"))
        return answer or ""

    say("== A. instance A starts in the world ==")
    a_log = (WORK / "instance_a.log").open("w")
    a = subprocess.Popen([sys.executable, "-u", str(ROOT / "core" / "main.py")], cwd=ROOT,
                         env=dict(env, LYRIC_INSTANCE_ID="handover01-a"), stdout=a_log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    started.append(a)
    record_a = None
    while record_a is None or not health(record_a).get("in_world"):
        if a.poll() is not None:
            EV.check("instance A started", False, f"it stopped (exit {a.returncode}); see work/instance_a.log")
            EV.write()
            return 1
        record_a = instances().get("handover01-a")
        time.sleep(LOOK_EVERY)
    EV.check("instance A started in the world", True, f"door {record_a['door']}")
    turn("person_a", "Is a cat an animal?")
    held = turn("person_a", "Is it a mammal?")
    EV.check("on one instance, person A's 'it' is the cat", held.startswith("Yes"), repr(held))

    say("== B. the handover ==")
    handover = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "handover.py"), "--quiet", str(QUIET)],
                                cwd=ROOT, env=env, stdout=(WORK / "handover.log").open("w"),
                                stderr=subprocess.STDOUT)
    started.append(handover)
    steps = lambda: [json.loads(l)["step"] for l in (WORK / "handovers.jsonl").read_text().splitlines()] \
        if (WORK / "handovers.jsonl").exists() else []
    while "switched" not in steps():
        if handover.poll() is not None:
            EV.check("the handover switched", False, f"it ended first: {steps()}; see work/handover.log")
            break
        time.sleep(LOOK_EVERY)
    record_b = next((r for i, r in instances().items() if i != "handover01-a"), None)

    say("== C. during the drain ==")
    switched_at = time.time()
    again = turn("person_a", "Is it a mammal?")
    new_person = turn("person_b", "Is iron a metal?")
    held_by_a = (health(record_a).get("holds") or {}) if record_b else {}
    held_by_b = (health(record_b).get("holds") or {}) if record_b else {}
    EV.check("person A's conversation went on where it was held: 'it' is still the cat", again.startswith("Yes"),
             repr(again))
    EV.check("person A was answered by A, passed on by B",
             held_by_a.get("person_a", 0) >= switched_at and "person_a" not in held_by_b,
             f"A holds {sorted(held_by_a)}, B holds {sorted(held_by_b)}")
    EV.check("person B, new, was answered by B", "person_b" in held_by_b and "person_b" not in held_by_a,
             f"B holds {sorted(held_by_b)}")

    say("== D. drained and stopped ==")
    handover.wait()
    went = steps() == ["begun", "started", "ready", "checked", "switched", "drained", "stopped", "done"]
    EV.check("the handover went through each step in order", went, f"steps: {steps()}; see work/handover.log")
    if not went:
        EV.write()
        return 1
    a.wait()
    EV.check("instance A stopped, and no longer says it is running",
             a.returncode is not None and "handover01-a" not in instances(), f"exit {a.returncode}")
    EV.check("instance B is the one in the world", bool(record_b) and health(record_b).get("in_world"),
             f"{record_b and record_b['instance']}")

    say("== E. after ==")
    after = turn("person_a", "Is a cat an animal?")
    EV.check("person A was answered by B", after.startswith("Yes")
             and "person_a" in (health(record_b).get("holds") or {}), repr(after))
    EV.check("every turn was answered", all(answer for _, _, answer in answers),
             f"unanswered: {[(p, t) for p, t, answer in answers if not answer]}")

    EV.note("logs: work/instance_a.log, work/instance_<B>.log in logs/, work/handover.log, work/handovers.jsonl")
    path = EV.write()
    say(f"\n  run record: {path}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
