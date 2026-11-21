"""A running Lyric's own door: how a handover reaches it (`scripts/handover.py`), and how a new instance passes it a
person's turn while it still holds their conversation (`WorldInhabitant.pass_to`).

Local only (127.0.0.1, on a port the system picks) and keyed: each instance makes a key when it starts and writes it,
with its address, to runtime/instances/<instance>.json, which only its owner can read. Every request carries the key.

    GET  /health   what it is: its instance, process, environment and release, the code it started with, whether it
                   has started, whether it is a worker, whether it takes turns from the world, and whose
                   conversations it holds
    POST /check    questions it answers from what it holds, each asked in a conversation that remembers nothing
    POST /turn     ONE PERSON'S TURN, from any environment that calls: their identity, what they said, and which
                   environment is calling. Lyric held no way in of its own -- a turn reached it only by Lyric
                   reaching OUT to a world and polling its mailbox (`WorldInhabitant`), so a world was privileged
                   and nothing else could speak to a running Lyric at all. Through this, LyricOS is one caller
                   among any, and the environment names the conversation rather than being assumed to be "world".
    POST /attach   take turns from the world, and open the senses
    POST /detach   let go of the world, and close the senses
    POST /pass     pass the turns of the people another instance still holds to that instance, or stop passing
    POST /take     one thing the world held, passed on by the instance that took it from the world
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
#: Where each running instance says where its door is (LYRIC_INSTANCES_DIR, for a line run apart, as an experiment's).
INSTANCES = Path(os.environ.get("LYRIC_INSTANCES_DIR") or ROOT / "runtime" / "instances")
#: How long a person may go unheard before their conversation counts as quiet.
QUIET = 600.0
#: What /check asks by default: questions of the kinds of things any line holds. A new instance is checked against
#: the running one (`scripts/handover.py`): each it answers, the new one must answer the same.
CHECKS = ("Is a dog an animal?", "Is a cat an animal?", "Is a rose a plant?", "Is iron a metal?",
          "Is water a liquid?", "Is a car a vehicle?", "Is Paris a city?", "Is a hammer a tool?")


async def take_turn(coordinator, identity: str, text: str, environment: str = "world") -> Dict[str, Any]:
    """ONE PERSON'S TURN, TAKEN FROM WHATEVER ENVIRONMENT CALLS: the real front door
    (`handle_user_request`), in a conversation of their own named for the environment they are speaking from.

    THE ONE IMPLEMENTATION, called by the door's `/turn` and by `WorldInhabitant._message`, so a turn from
    LyricOS and a turn from anything else are taken the same way. It lived in the inhabitant, which made a
    world the only thing that could hand Lyric a turn; the environment is now a caller's word, and
    `environment="world"` is what the inhabitant passes, not what Lyric assumes.

    A CONVERSATION OF THEIR OWN. With no conversation named, every person's turn was taken in one shared
    conversation ("api:unsessioned"), so one person's "it" could be what another had said.
    """
    if coordinator is None:
        return {"refused": "Lyric is not taking turns in this process"}
    reply = await coordinator.handle_user_request(
        text, source="api", metadata={"actor_identity": identity,
                                      "conversation_id": f"{environment}:{identity}"})
    # WORK THEIR ALLOWANCE DID NOT LET LYRIC TAKE ON is answered with why.
    why = coordinator.task_queue.refusal_of(reply["task_id"]) if reply.get("task_id") else None
    if why and not reply.get("success"):
        reply = {**reply, "answer": f"{why[0].upper()}{why[1:]}."}
    return {key: reply.get(key) for key in ("success", "answer", "task_id") if key in reply}


class InstanceDoor:
    """The door of the Lyric running in this process."""

    def __init__(self, system) -> None:
        self._system = system
        self.instance = os.environ.get("LYRIC_INSTANCE_ID") or (
            f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}")
        self._key = secrets.token_urlsafe(32)
        self._runner = None
        self.address: Optional[str] = None
        self.record = INSTANCES / f"{self.instance}.json"
        self.started_at = datetime.now(timezone.utc).isoformat()
        #: whether the Lyric behind it has started: set by the system once it has
        self.ready = False
        self._code: Dict[str, Any] = {}

    async def open(self) -> str:
        """Open the door and say where it is. The code is identified now, as it was when this process started."""
        from aiohttp import web
        from core.database.releases import code_identity
        self._code = code_identity()
        @web.middleware
        async def keyed(request, handler):
            return await self._keyed(request, handler)

        app = web.Application(middlewares=[keyed])
        app.add_routes([web.get("/health", self._health), web.post("/check", self._check),
                        web.post("/turn", self._turn),
                        web.post("/attach", self._attach), web.post("/detach", self._detach),
                        web.post("/pass", self._pass), web.post("/take", self._take)])
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", int(os.environ.get("LYRIC_DOOR_PORT") or 0))
        await site.start()
        port = self._runner.addresses[0][1]
        self.address = f"http://127.0.0.1:{port}"
        INSTANCES.mkdir(parents=True, exist_ok=True)
        written = self.record.with_suffix(".tmp")
        written.touch(mode=0o600)
        written.write_text(json.dumps({"instance": self.instance, "pid": os.getpid(), "door": self.address,
                                       "key": self._key, "started_at": self.started_at,
                                       **self._environment()}, indent=1))
        os.chmod(written, 0o600)
        written.replace(self.record)
        logger.info("instance %s: its door is at %s (%s)", self.instance, self.address, self.record)
        return self.address

    async def close(self) -> None:
        """Close the door; the instance no longer says it is running."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        try:
            self.record.unlink()
        except FileNotFoundError:
            logger.debug("this instance's record was already gone at close")

    def _environment(self) -> Dict[str, Any]:
        db = getattr(self._system, "db_manager", None)
        return {"environment": getattr(db, "environment", None) or os.environ.get("LYRIC_ENVIRONMENT", "development"),
                "release": getattr(db, "release", None),
                "database": getattr(getattr(db, "config", None), "database", None) or os.environ.get("POSTGRES_DATABASE"),
                "world": os.environ.get("TET_WORLD_ADDRESS"), "code": self._code}

    def _inhabitant(self):
        return getattr(self._system, "world_inhabitant", None)

    # ── requests ────────────────────────────────────────────────────────────────────────────────────────────

    async def _keyed(self, request, handler):
        from aiohttp import web
        given = request.headers.get("Authorization", "")
        if not secrets.compare_digest(given, f"Bearer {self._key}"):
            return web.json_response({"refused": "this door opens only with the instance's key"}, status=401)
        return await handler(request)

    async def _health(self, request):
        from aiohttp import web
        from core.agents.autonomous.autonomous_coordinator import is_worker
        inhabitant = self._inhabitant()
        quiet = float(request.query.get("quiet", QUIET))
        return web.json_response({
            "instance": self.instance, "pid": os.getpid(), "door": self.address, "started_at": self.started_at,
            **self._environment(), "ready": self.ready, "role": "worker" if is_worker() else "lyric",
            "in_world": bool(inhabitant is not None and inhabitant.taking),
            "holds": inhabitant.holds(quiet) if inhabitant is not None else {},
            "passing_to": (inhabitant._passing or {}).get("to") if inhabitant is not None else None})

    async def _check(self, request):
        """Each question asked in a conversation of its own that remembers nothing, and forgotten after: what it
        replied, and its verdict (None where it gave none)."""
        from aiohttp import web
        from core.agents.autonomous.autonomous_coordinator import end_conversation, get_conversation
        said = await request.json() if request.can_read_body else {}
        answers = []
        for question in said.get("questions") or CHECKS:
            session = f"door-check:{self.instance}:{time.time_ns()}"
            try:
                understanding = await get_conversation(session, remembers=False).understand(question, look_up=False)
            finally:
                end_conversation(session)
            # EVERY PART'S VERDICT, AND A VERDICT FOR THE WHOLE ONLY WHERE EVERY PART HAS ONE. This gathered the
            # verdicts that were not None and reported the one survivor, so a text whose parts were partly
            # unsettled came back as though it had been answered: asked "Do whales breathe air? Is a whale a
            # mammal?" it replied "Yes. A whale's a mammal." with `verdict True` -- and the store holds no
            # happening that fills the first question at all, so the "Yes." is the second's and the first went
            # unanswered with nothing saying so. Unsettled is not agreement.
            said = [a.verdict for a in (understanding.answers or [])]
            verdicts = {v for v in said if v is not None} if said and None not in said else set()
            # WHY NOTHING ANSWERED IT, CARRIED OUT WITH THE REPLY. `_understand` gathers this for exactly this
            # reason -- "so a person asking, and anything reading the reply, is told which path stopped where
            # instead of only that there is no answer" -- and this door threw it away, which is the whole of what
            # it was for. Asked 'Do whales breathe air?' the reply was "Air is a gas. A whale's a cetacean
            # mammal." with a None verdict, and nothing said that the question had gone unanswered: the store
            # holds no happening that fills it and `unified.learned_rules` holds none to derive one, which the
            # paths say in order (held relations, then the happenings told, then what was reasoned). An answered
            # question carries an empty list, since `_understand` empties it where there are answers.
            answers.append({"asked": question, "reply": understanding.reply,
                            "verdict": verdicts.pop() if len(verdicts) == 1 else None,
                            "verdicts": said,
                            "why_not": [{name: value if isinstance(value, (str, int, float, bool, type(None)))
                                         else str(value) for name, value in reason.items()}
                                        for reason in (understanding.why_not or ())]})
        return web.json_response({"answers": answers})

    async def _turn(self, request):
        """One person's turn from whatever environment is calling, taken through the real front door."""
        from aiohttp import web
        from core.agents.autonomous.autonomous_coordinator import is_worker
        if is_worker():
            return web.json_response({"refused": "this Lyric is a worker: it takes queued work, never turns"},
                                     status=409)
        said = await request.json() if request.can_read_body else {}
        identity = str(said.get("identity") or "").strip()
        text = str(said.get("text") or "").strip()
        if not identity or not text:
            return web.json_response({"refused": "a turn needs an identity and what was said"}, status=400)
        answered = await take_turn(getattr(self._system, "autonomous_coordinator", None), identity, text,
                                   environment=str(said.get("environment") or "world").strip() or "world")
        return web.json_response(answered)

    async def _attach(self, request):
        from aiohttp import web
        from core.agents.autonomous.autonomous_coordinator import is_worker
        if is_worker():
            return web.json_response({"refused": "this Lyric is a worker: it takes queued work, never turns"},
                                     status=409)
        inhabitant = self._inhabitant()
        if inhabitant is None:
            return web.json_response({"refused": "this Lyric is not in a world (TET_WORLD_ADDRESS)"}, status=409)
        if not inhabitant.taking:
            inhabitant.attach()
            await self._system.open_senses()
        return web.json_response({"in_world": inhabitant.taking})

    async def _detach(self, request):
        from aiohttp import web
        inhabitant = self._inhabitant()
        if inhabitant is not None:
            await inhabitant.detach()
        await self._system.close_senses()                # two Lyrics never listen at once
        return web.json_response({"in_world": bool(inhabitant is not None and inhabitant.taking)})

    async def _pass(self, request):
        from aiohttp import web
        inhabitant = self._inhabitant()
        if inhabitant is None:
            return web.json_response({"refused": "this Lyric is not in a world (TET_WORLD_ADDRESS)"}, status=409)
        said = await request.json()
        inhabitant.pass_to(said.get("to"), said.get("key"), said.get("people") or ())
        return web.json_response({"passing_to": said.get("to"), "people": sorted(said.get("people") or ())})

    async def _take(self, request):
        from aiohttp import web
        inhabitant = self._inhabitant()
        if inhabitant is None:
            return web.json_response({"refused": "this Lyric is not in a world (TET_WORLD_ADDRESS)"}, status=409)
        said = await request.json()
        taken = await inhabitant.take(str(said.get("intent") or ""), str(said.get("identity") or ""),
                                      str(said.get("payload") or ""))
        return web.json_response({"taken": taken})


def running_instances() -> Dict[str, Dict[str, Any]]:
    """Every instance that says it is running, by instance."""
    found = {}
    for record in sorted(INSTANCES.glob("*.json")):
        try:
            found[record.stem] = json.loads(record.read_text())
        except (OSError, ValueError) as error:
            logger.warning("instance record %s could not be read (%s: %s): that "
                           "instance is left out of the list of what is running",
                           record.name, type(error).__name__, error)
            continue
    return found
