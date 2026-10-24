#!/usr/bin/env python3
"""Hand Lyric over to a new release of it, or to new code, without going down.

    ./venv_lyric/bin/python3 scripts/handover.py                    new code, the same line and environment
    ./venv_lyric/bin/python3 scripts/handover.py --release 4        release 4, in production (it must be promoted)
    ./venv_lyric/bin/python3 scripts/handover.py --release 4 --environment staging

1. START the new instance beside the running one, with LYRIC_ATTACH=later: it starts and warms, and takes no
   turn yet. A release is checked as every release is before it serves (`releases.verify_serving`).
2. CHECK it: once it has started, it is asked what the running one is asked (its door's /check), and must answer
   each question the running one answers, the same way.
3. SWITCH: the new instance is told whose conversations the running one holds (a person heard within --quiet
   seconds), to pass their turns to it; the running one lets go of the world, and the new one attaches. A turn
   arriving in between waits in the world.
4. DRAIN: the running one answers the people it holds, through the new one, until each has been quiet for
   --quiet seconds.
5. STOP the running one, once no one's conversation is left in it.
6. WORKERS (`./lyric worker`): each running other code than the new instance's is started again on its code, the
   new worker first and then the old one stopped, so queued work never waits for a worker.

Nothing is lost in between: a turn the world handed to an instance that let go of it is handed to the next
(Tet's WorldRuntime, WORLD-HANDOVER-01). Each step is written to runtime/handovers.jsonl as it happens. Going back
is a handover too: to the release served before, while the code that release was cut with is the code here.

Run on the owner's word, as a restart is.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.integration.instance_door import INSTANCES, QUIET, running_instances  # noqa: E402

#: Each step of every handover, as it happens (LYRIC_HANDOVER_RECORD, for a line run apart, as an experiment's).
RECORD = Path(os.environ.get("LYRIC_HANDOVER_RECORD") or ROOT / "runtime" / "handovers.jsonl")
#: How often the instances are looked at while waiting on them.
LOOK_EVERY = 2.0


class HandoverError(RuntimeError):
    """A handover that cannot go on: what was done stays recorded, and the running instance keeps serving."""


def say(step: str, **detail) -> None:
    line = {"at": datetime.now(timezone.utc).isoformat(), "step": step, **detail}
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    with RECORD.open("a") as f:
        f.write(json.dumps(line) + "\n")
    print(f"[handover] {step}: " + ", ".join(f"{k}={v}" for k, v in detail.items()), flush=True)


def ask(instance: dict, path: str, body: dict = None, method: str = None) -> dict:
    """A request to an instance's door, with its key."""
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(instance["door"] + path, data=data, method=method or ("POST" if data else "GET"),
                                     headers={"Authorization": f"Bearer {instance['key']}",
                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request) as answer:
        return json.loads(answer.read())


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def serving() -> dict:
    """The instance taking turns from the world now."""
    in_world = []
    for record in running_instances().values():
        if not alive(record["pid"]):
            continue
        try:
            health = ask(record, "/health")
        except (urllib.error.URLError, OSError):
            continue
        if health.get("in_world"):
            in_world.append({**record, **health})
    if len(in_world) > 1:
        raise HandoverError(f"more than one instance takes turns from the world: "
                            f"{[i['instance'] for i in in_world]}")
    return in_world[0] if in_world else None


def start(args, old: dict) -> tuple:
    """The new instance, started beside the running one and not yet in the world."""
    instance = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-handover"
    env = dict(os.environ, LYRIC_ATTACH="later", LYRIC_INSTANCE_ID=instance, PYTHONUNBUFFERED="1")
    if old is not None:
        env.setdefault("TET_WORLD_ADDRESS", old.get("world") or "")
        if old.get("database"):
            env["POSTGRES_DATABASE"] = old["database"]
    if args.release:
        env.update(LYRIC_ENVIRONMENT=args.environment, LYRIC_RELEASE=str(args.release))
    if not env.get("TET_WORLD_ADDRESS"):
        raise HandoverError("no world is named (TET_WORLD_ADDRESS), so there is nothing to take turns from")
    process, log = launch(instance, env)
    say("started", instance=instance, pid=process.pid, release=args.release or "none", log=str(log))
    return instance, process, log


def launch(instance: str, env: dict) -> tuple:
    """A Lyric process, its output in logs/instance_<instance>.log."""
    log = ROOT / "logs" / f"instance_{instance}.log"
    log.parent.mkdir(exist_ok=True)
    process = subprocess.Popen([sys.executable, "-u", str(ROOT / "core" / "main.py")], cwd=ROOT, env=env,
                               stdout=log.open("w"), stderr=subprocess.STDOUT, start_new_session=True)
    return process, log


def workers() -> list:
    """The workers running now (`LYRIC_ROLE=worker`), as their doors say."""
    found = []
    for record in running_instances().values():
        if not alive(record["pid"]):
            continue
        try:
            health = ask(record, "/health")
        except (urllib.error.URLError, OSError):
            continue
        if health.get("role") == "worker":
            found.append({**record, **health})
    return found


def renew_workers(args, new: dict) -> None:
    """Each worker running other code than the new instance's, started again on its code: the new worker first,
    then the old one stopped (it lets go of the work it holds, which another instance takes)."""
    code = (new.get("code") or {}).get("sha256")
    for n, old in enumerate(workers(), 1):
        if (old.get("code") or {}).get("sha256") == code:
            continue
        instance = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-worker-{n}"
        env = dict(os.environ, LYRIC_ROLE="worker", LYRIC_INSTANCE_ID=instance, PYTHONUNBUFFERED="1")
        env.pop("LYRIC_ATTACH", None)
        if new.get("database"):
            env["POSTGRES_DATABASE"] = new["database"]
        if args.release:
            env.update(LYRIC_ENVIRONMENT=args.environment, LYRIC_RELEASE=str(args.release))
        process, log = launch(instance, env)
        until_ready(instance, process, log)
        say("worker renewed", instance=instance, pid=process.pid, replaces=old["instance"])
        stop(old, f"renewed on the code of {new['instance']}")


def until_ready(instance: str, process, log: Path) -> dict:
    """Wait for the new instance to have started; if it stops instead, say why from its log."""
    while True:
        if process.poll() is not None:
            tail = log.read_text(errors="replace").splitlines()[-15:]
            raise HandoverError(f"the new instance stopped while starting (exit {process.returncode}): "
                                + " | ".join(tail))
        record = running_instances().get(instance)
        if record is not None:
            try:
                health = ask(record, "/health")
                if health.get("ready"):
                    return {**record, **health}
            except (urllib.error.URLError, OSError):
                pass
        time.sleep(LOOK_EVERY)


def stop(record: dict, why: str) -> None:
    """Stop an instance as a restart would (SIGTERM: it lets go of the world, then shuts down) and wait for it."""
    os.kill(record["pid"], signal.SIGTERM)
    while alive(record["pid"]):
        time.sleep(LOOK_EVERY)
    say("stopped", instance=record["instance"], why=why)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release", type=int, help="the release the new instance serves")
    parser.add_argument("--environment", default="production", choices=("staging", "production"))
    parser.add_argument("--quiet", type=float, default=QUIET,
                        help="seconds a person goes unheard before their conversation counts as over")
    args = parser.parse_args()

    old = serving()
    say("begun", running=old["instance"] if old else "none",
        running_release=(old or {}).get("release"), running_code=((old or {}).get("code") or {}).get("sha256"))
    instance, process, log = start(args, old)
    new = None
    try:
        new = until_ready(instance, process, log)
        say("ready", instance=instance, release=new.get("release"), code=(new.get("code") or {}).get("sha256"),
            commit=(new.get("code") or {}).get("commit"))
        theirs = {a["asked"]: a for a in ask(new, "/check", {})["answers"]}
        ours = {a["asked"]: a for a in ask(old, "/check", {})["answers"]} if old else {}
        differ = [q for q, a in ours.items() if a["verdict"] is not None and theirs.get(q, {}).get("verdict") != a["verdict"]]
        if differ:
            raise HandoverError("the new instance does not answer as the running one does: " + "; ".join(
                f"{q!r}: running {ours[q]['reply']!r}, new {theirs.get(q, {}).get('reply')!r}" for q in differ))
        say("checked", compared=sum(a["verdict"] is not None for a in ours.values()),
            answered_by_new=sum(a["verdict"] is not None for a in theirs.values()), asked=len(theirs))

        held = sorted((ask(old, f"/health?quiet={args.quiet}").get("holds") or {}) if old else ())
        if old is not None:
            ask(new, "/pass", {"to": old["door"], "key": old["key"], "people": held})
            ask(old, "/detach", {})
        ask(new, "/attach", {})
        say("switched", to=instance, running_held=len(held))
    except BaseException as error:
        if new is not None and old is not None:
            # NOTHING CHANGES HANDS: the running instance goes back into the world if it had let go.
            try:
                if not ask(old, "/health").get("in_world"):
                    ask(old, "/attach", {})
            except (urllib.error.URLError, OSError):
                pass
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            process.wait()
        say("abandoned", instance=instance, why=f"{type(error).__name__}: {error}")
        return 1

    if old is not None:
        while alive(old["pid"]):
            try:
                holds = ask(old, f"/health?quiet={args.quiet}").get("holds") or {}
            except (urllib.error.URLError, OSError):
                break                                    # gone: the new instance takes their turns itself
            if not holds:
                break
            time.sleep(LOOK_EVERY)
        ask(new, "/pass", {"to": None})
        say("drained", instance=old["instance"])
        if alive(old["pid"]):
            stop(old, f"handed over to {instance}")
    if "LYRIC_INSTANCES_DIR" not in os.environ:
        (ROOT / "runtime" / "lyric_main.pid").write_text(str(new["pid"]))
    renew_workers(args, new)
    say("done", serving=instance, release=new.get("release"), code=(new.get("code") or {}).get("sha256"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HandoverError as error:
        say("refused", why=str(error))
        sys.exit(1)
