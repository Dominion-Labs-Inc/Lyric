"""Lyric as the inhabitant of its world.

Lyric runs by itself and attaches to the world (Tet, which runs in its own containers) as its
inhabitant: it proves it holds the inhabitant's key, and from then on takes what the world holds FOR
it. Everything the world hands over has passed the gate and carries the gate-verified identity of the
person who sent it, which is the actor everything of theirs is kept under.

    message           one conversational turn -> the front door (`handle_user_request`)
    shared_learning   whether each kind of a person's or an organization's work goes into shared learning -> the
                      learning authority
    hearing           what a person's device hears while Listening is on, and their wake phrase to set it up ->
                      Lyric's ears on people's devices (`core.perception.live.DeviceEars`)

ITS PEOPLE'S ALLOWANCES. Attached with a running Lyric, the queue takes on work for a person only while the
allowance the world keeps for their seat lets it (`Allowance`: their month's action minutes, the tasks it runs for
them a day and at once), answers work refused with why, and keeps in their usage each task it took on, how long each
job was in flight, the CPU its programs used, and how much their workspace holds (where their files are kept while
Lyric works for them).

The world's address and the inhabitant's key come from the environment (TET_WORLD_ADDRESS,
TET_OPERATOR_PRIVATE_KEY). Neither has a default: without them Lyric is not attached to a world, and
`attach` says so.

A HANDOVER. A new release of Lyric takes over from the running one without either going down
(`scripts/handover.py`): the new one attaches, the running one lets go (`detach`), and a turn arriving in
between waits in the world. Each person talks in a conversation of their own (`world:<identity>`), held by
the instance they talk to; while the old instance still holds a person's conversation, the new one passes
their turns to it (`pass_to`) until it has gone quiet, so no one's conversation is cut off mid-way.

Run alone, this attaches the appraisal authority only (no turns are taken):
    ./venv_lyric/bin/python3 -m core.integration.world_inhabitant
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

#: The principal the world's gate knows its inhabitant as.
INHABITANT_PRINCIPAL = "operator_7"

#: The tenancy of a person who belongs to no organization, in the identities the world hands over
#: (`<organization>:<person>` or `individual:<person>`, Tet's `access.INDIVIDUAL`).
INDIVIDUAL = "individual"

#: Where the Tet package is when it is not installed: the folder Lyric's own folder sits in.
_BESIDE = Path(__file__).resolve().parents[3]


#: What is held for a person in one instance and so follows them during a handover: their conversation, and
#: what their device is in the middle of hearing.
_HELD_FOR_A_PERSON = ("message", "hearing")


def _tet():
    """The world's own client for its inhabitant, its hold on the world, and the inhabitant's key."""
    try:
        from Tet.walls._config import operator_private_key
        from Tet.walls.lyric_main import Attachment, serve_messages
    except ImportError:
        sys.path.insert(0, str(_BESIDE))
        from Tet.walls._config import operator_private_key
        from Tet.walls.lyric_main import Attachment, serve_messages
    return serve_messages, Attachment, operator_private_key


class Allowance:
    """Each person's allowance, as the world keeps it (Tet's `platform.usage`), for the queue authority
    (`QueueAuthority.allowance`): whether work for the person a task is for may be taken on now (`may_take`), and
    what Lyric used for them (`taken`: a task taken on; `acted`: the seconds a job was in flight). Asked over its own
    link to the world, not the one turns are pulled on (that one waits); called off Lyric's loop, so one link is
    held under a lock and opened again when it drops."""

    def __init__(self, address: str, key) -> None:
        self._address, self._key = address, key
        self._link = None
        self._lock = threading.Lock()

    def _ask(self, ask: Callable[[Any], Any]) -> Any:
        from Tet.walls import LyricClient
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._link is None:
                        self._link = LyricClient(self._address, INHABITANT_PRINCIPAL, self._key)
                    return ask(self._link)
                except (ConnectionError, OSError):
                    self.close_link()
                    if attempt == 2:
                        raise

    def may_take(self, task, running: int) -> Optional[str]:
        """Why work for the person `task` is for may not be taken on now, `running` of theirs already owed; None
        when it may."""
        return self._ask(lambda link: link.may_start(task.actor, running))

    def taken(self, task) -> None:
        """A task taken on for its person: kept in their usage."""
        self._ask(lambda link: link.used(task.actor, "task", 1, {"task": str(task.id)}))

    def acted(self, actor: str, seconds: float, task_id: str) -> None:
        """The seconds a job for its person was in flight: kept in their usage."""
        self._ask(lambda link: link.used(actor, "action", seconds, {"task": task_id}))

    def computed(self, actor: str, seconds: float, task_id: str) -> None:
        """The CPU seconds the programs a job for its person ran used: kept in their usage."""
        self._ask(lambda link: link.used(actor, "compute", seconds, {"task": task_id}))

    def holds(self, actor: str, size: int) -> None:
        """How much the person's workspace holds now, in bytes: kept in their usage as their compute storage."""
        self._ask(lambda link: link.used(actor, "core", size))

    def close_link(self) -> None:
        if self._link is not None:
            try:
                self._link.close()
            except OSError:
                pass
        self._link = None


class WorldInhabitant:
    """Lyric's attachment to its world."""

    def __init__(self, coordinator=None) -> None:
        #: The running Lyric, whose front door takes a person's turn. None when only the appraisal
        #: authority is attached: a message is then refused, by name, never answered by something else.
        self._coordinator = coordinator
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        #: Its hold on the world (`Tet.walls.lyric_main.Attachment`), while it has one.
        self._attachment = None
        #: Lyric's ears on people's devices (`DeviceEars`), made when the first device is heard.
        self._ears = None
        #: When each person last spoke to this instance, or was heard by it: whose conversation it holds.
        self.last_heard: Dict[str, float] = {}
        #: During a handover, the instance that still holds some people's conversations: where their turns
        #: are passed, with the door's key ({"to", "key", "people"}). None otherwise.
        self._passing: Optional[Dict[str, Any]] = None
        self._takes = {"message": self._message, "shared_learning": self._shared_learning, "hearing": self._hearing,
                       "device": self._device}
        #: Each person's allowance (`Allowance`), held by the running Lyric's queue while attached with one.
        self._allowance: Optional[Allowance] = None

    def attach(self, world_address: Optional[str] = None, key=None) -> None:
        """Start taking what the world holds for Lyric. Called from Lyric's running loop: each thing
        pulled is handled on that loop, where everything of Lyric's runs."""
        address = world_address or os.environ.get("TET_WORLD_ADDRESS")
        if not address:
            raise RuntimeError("TET_WORLD_ADDRESS is not set: Lyric is not attached to a world")
        if self.taking:
            raise RuntimeError("this Lyric is already attached to its world")
        serve_messages, Attachment, operator_private_key = _tet()
        self._loop = asyncio.get_running_loop()
        self._attachment = Attachment()
        self._thread = threading.Thread(
            target=serve_messages, name="world-inhabitant", daemon=True,
            args=(address, INHABITANT_PRINCIPAL, key if key is not None else operator_private_key(),
                  {intent: self._on_loop(intent) for intent in self._takes}),
            kwargs={"attachment": self._attachment})
        self._thread.start()
        if self._coordinator is not None:
            # ITS PEOPLE'S ALLOWANCES. Work for a person is taken on only while their seat allows it, and what it
            # used is kept in their usage: each task taken on, and how long each job was in flight once it ends.
            self._allowance = Allowance(address, key if key is not None else operator_private_key())
            self._coordinator.task_queue.allowance = self._allowance
            if not getattr(self._coordinator.task_queue, "_usage_kept", False):
                self._coordinator.task_queue.on_work_ended(self._work_ended)
                self._coordinator.task_queue._usage_kept = True
        logger.info("Lyric attached to its world at %s as its inhabitant", address)

    @property
    def taking(self) -> bool:
        """Whether it takes what the world holds for it: attached, and not letting go."""
        return (self._thread is not None and self._thread.is_alive() and self._attachment is not None
                and not self._attachment.letting_go)

    async def detach(self) -> None:
        """Let go of the world: the turn being answered is answered, and whatever comes after waits in the
        world for the next inhabitant. Returns once it has let go."""
        if self._attachment is None:
            return
        connected = self._attachment.attached
        self._attachment.detach()
        thread = self._thread
        # Only a connected inhabitant can hold a turn, so only one is waited for: one still reaching for a world
        # that has gone holds none, and lets go if it ever connects (`serve_messages`).
        if thread is not None and connected:
            await asyncio.get_running_loop().run_in_executor(None, thread.join)
        if self._allowance is not None:
            if self._coordinator is not None and self._coordinator.task_queue.allowance is self._allowance:
                self._coordinator.task_queue.allowance = None
            self._allowance.close_link()
            self._allowance = None
        logger.info("Lyric let go of its world")

    def holds(self, quiet_for: float) -> Dict[str, float]:
        """The people whose conversation it holds: each who spoke to it, or was heard by it, within the last
        `quiet_for` seconds, with when."""
        since = time.time() - quiet_for
        return {person: at for person, at in self.last_heard.items() if at >= since}

    def pass_to(self, door: Optional[str], key: Optional[str] = None, people: Iterable[str] = ()) -> None:
        """During a handover: the turns of `people`, whose conversations the instance at `door` still holds,
        are passed to it. `door` None passes nothing on."""
        self._passing = {"to": door.rstrip("/"), "key": key, "people": frozenset(people)} if door else None

    def _on_loop(self, intent: str) -> Callable[[str, str], Any]:
        """What the world holds of `intent`, taken on Lyric's loop from the thread that pulls from the world."""
        def take(identity: str, payload: str):
            return asyncio.run_coroutine_threadsafe(self.take(intent, identity, payload), self._loop).result()
        return take

    async def take(self, intent: str, identity: str, payload: str) -> Any:
        """One thing the world held for Lyric: taken here, or passed to the instance that holds the person's
        conversation (`pass_to`)."""
        passing = self._passing
        if passing is not None and intent in _HELD_FOR_A_PERSON and identity in passing["people"]:
            import aiohttp
            try:
                return await self._pass_on(passing, intent, identity, payload)
            except aiohttp.ClientConnectorError as gone:
                # NO ONE HOLDS IT ANY MORE: the instance that held their conversation has gone, so it is taken here.
                logger.warning("the instance holding %s's conversation is gone (%s); taking their turn here",
                               identity, gone)
                self._passing = {**passing, "people": passing["people"] - {identity}}
        taken = self._takes.get(intent)
        if taken is None:
            return {"refused": f"the inhabitant does not take {intent!r}"}
        if intent in _HELD_FOR_A_PERSON:
            self.last_heard[identity] = time.time()
        return await taken(identity, payload)

    @staticmethod
    async def _pass_on(passing: Dict[str, Any], intent: str, identity: str, payload: str) -> Any:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{passing['to']}/take",
                                    json={"intent": intent, "identity": identity, "payload": payload},
                                    headers={"Authorization": f"Bearer {passing['key']}"}) as answer:
                if answer.status != 200:
                    raise RuntimeError(f"the instance holding {identity}'s conversation refused their turn: "
                                       f"{answer.status} {await answer.text()}")
                return (await answer.json())["taken"]

    async def _message(self, identity: str, text: str) -> Dict[str, Any]:
        if self._coordinator is None:
            return {"refused": "Lyric is not taking turns in this process"}
        # A CONVERSATION OF THEIR OWN. With no conversation named, every person's turn from the world was taken
        # in one shared conversation ("api:unsessioned"), so one person's "it" could be what another had said.
        reply = await self._coordinator.handle_user_request(
            text, source="api", metadata={"actor_identity": identity, "conversation_id": f"world:{identity}"})
        # WORK THEIR ALLOWANCE DID NOT LET LYRIC TAKE ON is answered with why.
        why = self._coordinator.task_queue.refusal_of(reply["task_id"]) if reply.get("task_id") else None
        if why and not reply.get("success"):
            reply = {**reply, "answer": f"{why[0].upper()}{why[1:]}."}
        return {key: reply.get(key) for key in ("success", "answer", "task_id") if key in reply}

    async def _work_ended(self, job: Dict[str, Any], task) -> None:
        """A job for a person ended: what it used is kept in their usage. The seconds it was in flight, the CPU seconds
        its programs used, and how much their workspace holds now."""
        allowance, actor = self._allowance, getattr(task, "actor", None)
        if allowance is None or not actor:
            return
        from core.agents.autonomous.queue_authority import workspace_bytes
        from core.agents.autonomous.shared_types import is_substrate_actor
        if is_substrate_actor(actor):
            return
        acted, computed = float(job.get("acting_seconds") or 0), float(job.get("compute_seconds") or 0)
        loop = asyncio.get_running_loop()
        try:
            if acted > 0:
                await loop.run_in_executor(None, allowance.acted, actor, acted, str(task.id))
            if computed > 0:
                await loop.run_in_executor(None, allowance.computed, actor, computed, str(task.id))
            await loop.run_in_executor(None, allowance.holds, actor, workspace_bytes(actor))
        except Exception as error:
            logger.error("what %s used could not be kept in their usage: %s", actor, error)

    async def _shared_learning(self, identity: str, payload: str) -> Dict[str, Any]:
        """Whether what Lyric learns from this person's work goes into shared learning (Context and privacy), for
        the learning authority, one switch for each kind of work: nothing in the payload asks where they are, "on" or
        "off" sets every one, and "<kind>:on" or "<kind>:off" one of them. A person on their own has their own
        switches; a person in an organization sees its Work Context's, and which of its people may set them is the
        world's to decide before it hands one over. A refusal is the authority's own, said back."""
        from core.agents.autonomous.shared_types import work_owner
        from core.learning.unified_learning_system import get_learning_authority
        tenancy, sep, person = str(identity or "").partition(":")
        if not (sep and tenancy and person):
            return {"refused": "a shared learning switch belongs to a signed-in person or their organization"}
        owner = identity if tenancy == INDIVIDUAL else work_owner(tenancy)
        authority = get_learning_authority()
        asked = str(payload or "").strip().lower()
        if not asked:
            return {"shared_learning": await authority.shared_learning(owner)}
        category, _, setting = asked.rpartition(":")
        try:
            if setting not in ("on", "off"):
                raise ValueError("shared learning is on or off")
            return {"shared_learning": await authority.set_shared_learning(
                owner, setting == "on", by=identity, category=category or None)}
        except ValueError as refused:
            return {"shared_learning": await authority.shared_learning(owner), "refused": str(refused)}

    async def _hearing(self, identity: str, payload: str) -> Dict[str, Any]:
        """What a person's device hears, for Lyric's ears on people's devices (`DeviceEars`): a JSON object with
          `stream` and `pcm`   the next half second its microphone heard while Listening or voice mode is on
                               (16-bit mono at `rate`, as base64), answered with what was said to Lyric on that stream
                               since last asked; with `attend`, voice mode is on there and what the person says is
                               taken as said to Lyric without the wake phrase (`DeviceEars.hear`);
          `stream` and `end`   it stopped listening;
          `lesson` and `pcm`   one time the person said the wake phrase (or its rival) to set Listening up, taught in
                               their voice, answered with how far setup has come;
          `ask`                how far setup has come.
        A refusal is the ears' own, said back."""
        if self._coordinator is None:
            return {"refused": "Lyric is not listening in this process"}
        try:
            said = json.loads(payload or "")
        except ValueError:
            return {"refused": "what a device hears comes as a JSON object"}
        if not isinstance(said, dict):
            return {"refused": "what a device hears comes as a JSON object"}
        if self._ears is None:
            from core.perception.live import DeviceEars
            self._ears = DeviceEars(self._coordinator)
        try:
            if said.get("ask"):
                return {"setup": await self._ears.setup(identity)}
            sound = base64.b64decode(str(said.get("pcm") or ""), validate=True)
            rate = int(said.get("rate") or 0)
            if said.get("lesson"):
                return {"setup": await self._ears.teach(identity, str(said["lesson"]).strip().lower(), sound, rate)}
            stream = str(said.get("stream") or "").strip()
            if not stream:
                raise ValueError("what a device hears names the stream it is from")
            if said.get("end"):
                return await self._ears.end(identity, stream)
            return await self._ears.hear(person=identity, stream=stream, pcm=sound, rate=rate,
                                         attend=bool(said.get("attend")))
        except (ValueError, RuntimeError) as refused:
            return {"refused": str(refused)}

    async def _device(self, identity: str, payload: str) -> Dict[str, Any]:
        """What a person's device says, from Lyric's own code running on it. A `report`: what the device
        is, what exists on it and what the person set, which situates Lyric in it (`situate_device`) and
        answers with what was learned. A `location`: a position fix, perceived as the person's."""
        if self._coordinator is None:
            return {"refused": "Lyric is not taking in devices in this process"}
        try:
            said = json.loads(payload or "{}")
        except ValueError:
            return {"refused": "a device's report is JSON"}
        if not isinstance(said, dict):
            return {"refused": "a device's report is a JSON object"}
        try:
            if "report" in said:
                return await self._coordinator.situate_device(said["report"], actor_identity=identity)
            if "location" in said:
                from core.memory import Origin
                fix = dict(said["location"])
                await self._coordinator.process_input(
                    str(fix.get("device") or "device"), "location", fix,
                    origin=Origin.of(identity, "device"))
                return {"received": True}
        except ValueError as refused:
            return {"refused": str(refused)}
        return {"refused": "a device sends a report or a location"}


async def _alone() -> None:
    """Attach the appraisal authority to the world, with no running Lyric behind it."""
    from core.agents.autonomous.appraisal import get_appraisal_system
    from core.database import get_database_manager
    db = get_database_manager()
    await db.initialize()
    await get_appraisal_system().join_world(db)
    WorldInhabitant().attach()
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_alone())
