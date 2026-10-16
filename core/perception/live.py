#!/usr/bin/env python3
"""The live senses: always listening and looking while the substrate runs,
keeping only what is said TO it.

The ear and the eye are each a program of their own, as the senses' measuring
is (`core.perception.senses`), so listening never holds the substrate's loop.

THE EAR listens to a microphone without stopping. It hears where speech rises
above the room, by hearing's own rules (the ground a recording rests at, a
sound rising `_RISE_DB` above it and lasting while it stays `_HOLD_DB` above),
and cuts the stream into utterances where the room falls quiet. For each
utterance it asks one thing: was the substrate's NAME said in it? The name is a
taught spoken word like any other (`coord.learn_word`); nothing is built in.
An utterance with the name in it is kept, and so is one said within
`ATTENTION_SECONDS` after a kept one in which taught words were firmly heard,
since a person goes on talking without repeating the name, or while they have
voice mode on on the device it hears (`Ear.attending`) -- while the room's
own clicks and hum, in which no word is heard, hold nothing open. EVERYTHING ELSE IS DROPPED INSIDE THE EAR'S PROCESS: its
sound and its words never reach the substrate, and only its length is
reported, so the substrate can say how much it let pass.

THE EYE looks at a camera without stopping and keeps only the latest frame;
every other frame is overwritten. It hands the frame over only when asked.

THE SUBSTRATE (`LiveSenses`) takes each kept utterance and the scene of that
moment in together, as ONE moment (`coord.perceive_moment`): heard and seen at
the same time, admitted, judged and remembered as one experience -- in words,
as traces, never the recording or the picture. When the hearing was complete --
every word in it a taught word, nothing unknown -- what was said goes to the
one front door a person's message comes through (`coord.handle_user_request`),
where typed words go, so spoken and written talk are one conversation in one
memory. The reply is text; a voice of its own is later work.

Run the ear or the eye alone (they are started by `LiveSenses`):
    python -m core.perception.live ear mic:default
    python -m core.perception.live eye cam:0
A recording or a video file played in real time stands in for the device:
    python -m core.perception.live ear file:/path/to/talk.wav
"""
from __future__ import annotations

import asyncio
import logging
import os
import pickle
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from . import hearing
from .senses import _LENGTH, _ROOT

logger = logging.getLogger(__name__)

#: An utterance ends when the room has been quiet this long. Words said one at
#: a time, with the pauses of slow speech (0.35-0.4 s), stay one utterance.
PAUSE_SECONDS = 0.8
#: Room quiet kept on each side of an utterance: hearing finds where speech is
#: from the room around it, and measured, it needed 0.3 s of it.
EDGE_SECONDS = 0.3
#: The longest utterance kept whole; a longer stretch is cut here.
MAX_UTTERANCE_SECONDS = 15.0
#: After something said to it, what is said within this long is also kept: a
#: person goes on talking without saying the name every time.
ATTENTION_SECONDS = 8.0
#: How much of the room's recent history its resting level is read from.
ROOM_SECONDS = 30.0
_CHUNK = 1024                      # samples read from the device at a time

#: What a person says to call Lyric through their own device: a taught spoken word like any other, taught whole, in
#: their own voice, when they turn Listening on (`DeviceEars.teach`).
WAKE_PHRASE = "hello lyric"
#: Taught with it, in the same voice, so the ear has something to weigh it against: a word is named only when it
#: clearly beats every other taught word (`speech.RATIO`), and "hello" said to someone else must not call Lyric.
WAKE_RIVAL = "hello"
#: How many times each is said when Listening is set up.
WAKE_LESSONS = {WAKE_PHRASE: 3, WAKE_RIVAL: 1}
#: The rates a device may send its sound at; the ears hear it at hearing's own (`hearing.SR`).
DEVICE_RATES = (8000, 48000)


def asked_in(heard_as: str, name: str) -> List[str]:
    """THE NAME SAID TO CALL IT IS HOW IT WAS ADDRESSED, not what was asked. What was asked is what follows the name,
    or, when the name is said last, what came before it. What came before a name that the request follows -- a sound
    in the room, a word to someone else -- was not asked of it. A name of several words (a wake phrase) is those words
    in order."""
    words, called = heard_as.split(), name.split()

    def without(part: List[str]) -> List[str]:
        out, i = [], 0
        while i < len(part):
            if part[i:i + len(called)] == called:
                i += len(called)
            else:
                out.append(part[i])
                i += 1
        return out

    at = next((i for i in range(len(words) - len(called) + 1) if words[i:i + len(called)] == called), None)
    if at is None:
        return words
    after = without(words[at + len(called):])
    return after if after else without(words[:at])


# ── framing, shared with the substrate side ────────────────────────────────

def _send(stream, message: Any) -> None:
    data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(_LENGTH.pack(len(data)) + data)
    stream.flush()


def _receive(stream) -> Optional[Any]:
    head = stream.read(_LENGTH.size)
    if len(head) < _LENGTH.size:
        return None
    return pickle.loads(stream.read(_LENGTH.unpack(head)[0]))


# ── the ear ─────────────────────────────────────────────────────────────────

def _capture(source: str, *, audio: bool, size: Tuple[int, int] = (640, 360)) -> List[str]:
    """The ffmpeg command that turns a device, or a file played in real time,
    into a stream: mono samples at hearing's rate, or frames of `size`."""
    kind, _, where = source.partition(":")
    if kind in ("mic", "cam"):
        spec = ["-f", "avfoundation"] + (
            ["-i", f":{where}"] if audio else
            ["-framerate", "30", "-video_size", "1280x720", "-i", f"{where}:none"])
    elif kind == "file":
        spec = ["-re"] + ([] if audio else ["-stream_loop", "-1"]) + ["-i", where]
    else:
        raise ValueError(f"no such source {source!r}: mic:<device>, cam:<device> or file:<path>")
    out = (["-vn", "-ac", "1", "-ar", str(hearing.SR), "-f", "s16le", "-"] if audio else
           ["-an", "-vf", f"fps=2,scale={size[0]}:{size[1]}", "-f", "rawvideo",
            "-pix_fmt", "bgr24", "-"])
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"] + spec + out


class Ear:
    """Cuts a stream of samples into utterances and decides, for each, whether
    it was said to the substrate. `feed` takes samples as they arrive; `heard`
    is called with each utterance kept and `passed` with the length of each
    one dropped."""

    def __init__(self, heard, passed, status) -> None:
        self.heard, self.passed, self.status = heard, passed, status
        self.library: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._buf = np.zeros(0, dtype=np.float32)   # samples not yet let go
        self._at = 0                                # stream index of _buf[0]
        self._total = 0                             # samples received
        self._levels: deque = deque(maxlen=int(ROOM_SECONDS * hearing.SR / hearing.HOP))
        self._next_hop = 0                          # next hop whose level is due
        self._ground: Optional[float] = None
        self._ground_at = -1
        self._start: Optional[int] = None           # first hop of the utterance
        self._last_held = 0                         # last hop of its last sound
        self._run: Optional[int] = None             # a held run going on, from here
        self._rose = False                          # ... and whether it has risen
        self._attending_until = -1                 # stream index attention lasts to
        self._told_unnamed = False
        self.person: Optional[str] = None           # whose device it hears, when it hears one (`_ears`)
        #: The person has voice mode on on the device this ear hears: attention is held open as long as it is, as it
        #: is after the name is said (`_ears`, the device's `attend`).
        self.attending = False

    def teach(self, library: Dict[str, Any]) -> None:
        with self._lock:
            self.library = library
            self._told_unnamed = False

    def feed(self, samples: np.ndarray) -> None:
        self._buf = np.concatenate([self._buf, samples])
        self._total += len(samples)
        half = hearing.FRAME // 2
        while self._next_hop * hearing.HOP + half <= self._total:
            h = self._next_hop
            lo = h * hearing.HOP - half - self._at
            frame = self._buf[max(lo, 0):lo + hearing.FRAME]
            level = 20 * np.log10(np.sqrt(np.mean(frame.astype(np.float64) ** 2)) + hearing._EPS) \
                if len(frame) else hearing._SIGNAL_DB
            self._levels.append((h, level))
            self._next_hop += 1
            self._step(h, level)
        self._let_go()

    def _room(self, h: int) -> Optional[float]:
        """The level the room rests at, from its recent history, read afresh
        every half second: hearing's own `ground`."""
        if h - self._ground_at >= int(0.5 * hearing.SR / hearing.HOP):
            self._ground = hearing.ground(np.array([lv for _h, lv in self._levels]))
            self._ground_at = h
        return self._ground

    def _step(self, h: int, level: float) -> None:
        """One more level heard. SOUNDS are found exactly as `hearing.segment`
        finds them -- a run of frames held `_HOLD_DB` above the room, counted
        only if it rises `_RISE_DB` above it and lasts `_MIN_SOUND` -- and an
        UTTERANCE is sounds that follow one another within `PAUSE_SECONDS`.
        The room's own flicker just above the hold level is not a sound, and
        keeps nothing going."""
        ground = self._room(h)
        if ground is None:
            return                                  # nothing to rise above yet
        if level > ground + hearing._HOLD_DB:
            if self._run is None:
                self._run, self._rose = h, False
            self._rose = self._rose or level > ground + hearing._RISE_DB
        elif self._run is not None:
            first, last = self._run, h - 1
            self._run = None
            if self._rose and (last - first + 1) * hearing.HOP / hearing.SR >= hearing._MIN_SOUND:
                self._sound(first, last)
        pause = int(PAUSE_SECONDS * hearing.SR / hearing.HOP)
        if self._start is not None:
            waiting = self._run is not None and self._run - self._last_held <= pause
            if (h - self._last_held >= pause and not waiting) or \
                    (h - self._start) * hearing.HOP / hearing.SR >= MAX_UTTERANCE_SECONDS:
                self._cut(self._start, self._last_held)
                self._start = None

    def _sound(self, first: int, last: int) -> None:
        """A sound heard: it begins an utterance, or joins the one going on."""
        pause = int(PAUSE_SECONDS * hearing.SR / hearing.HOP)
        if self._start is not None and first - self._last_held > pause:
            self._cut(self._start, self._last_held)
            self._start = None
        if self._start is None:
            self._start = first
        self._last_held = last

    def _cut(self, first: int, last: int) -> None:
        edge = int(EDGE_SECONDS * hearing.SR)
        a = max(first * hearing.HOP - edge, self._at)
        b = min(last * hearing.HOP + edge, self._total)
        samples = self._buf[a - self._at:b - self._at].copy()
        self.decide(samples, a, b)

    def decide(self, samples: np.ndarray, begins: int, ends: int) -> None:
        """Keep an utterance said to the substrate; drop anything else here.
        `begins` and `ends` are where it lies in the stream, whose own clock
        attention is kept on: how long ago something was said to it is how
        much was heard since, not how long the thinking took."""
        from . import speech
        with self._lock:
            library = self.library
        words, name = library.get("words") or {}, library.get("name")
        spans = speech.find_words(samples, words) if name in words and len(words) >= 2 else []
        named = any(s.get("word") == name for s in spans)
        # ATTENTION IS KEPT BY WORDS. Within it, an utterance is kept -- and
        # holds attention open -- only when a taught word was FIRMLY heard in
        # it (support 0.5 or more: every firm reading measured was right, and
        # nothing never taught was ever named firmly). A room clicking and
        # humming every few seconds otherwise held attention open for good,
        # and neither voicing nor `judge_voice` could tell an 87 Hz hum from a
        # voice.
        talking = any(s.get("word") and (s.get("standing") or 0.0) >= 0.5 for s in spans)
        if name not in words and not self._told_unnamed:
            self.status(f"its name {name!r} was never taught as a spoken word, so nothing "
                        f"heard is taken as said to it")
            self._told_unnamed = True
        if named or (talking and (self.attending or begins <= self._attending_until)):
            self._attending_until = ends + int(ATTENTION_SECONDS * hearing.SR)
            self.heard({"samples": (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes(),
                        "rate": hearing.SR, "named": named, "at": time.time(),
                        "said": [{"word": s.get("word"), "support": s.get("standing")}
                                 for s in spans]})
        else:
            self.passed(round(len(samples) / hearing.SR, 2))

    def _let_go(self) -> None:
        """Samples no utterance can still need are let go of: before the
        current utterance's start, or, between utterances, all but the room
        quiet an utterance would keep before it.

        A SOUND STILL GOING ON is kept from where it began. A sound is known
        only when it ends, and an utterance starts with its first sound, so
        letting go by the utterance's start alone dropped the opening of any
        first sound longer than the room kept before it: a name said as one
        unbroken sound ("Lyric", half a second) lost its first fifth and was
        no longer heard as the name."""
        begins = self._start if self._start is not None else self._run
        keep_from = (begins * hearing.HOP if begins is not None
                     else self._total) - int(EDGE_SECONDS * hearing.SR) - hearing.FRAME
        drop = keep_from - self._at
        if drop > 0:
            self._buf = self._buf[drop:]
            self._at += drop


def _ear(source: str) -> None:
    """The ear's program: listen to `source` until told to stop; tell the
    substrate what was said to it, and how much was let pass."""
    events, commands = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr
    out_lock = threading.Lock()

    def emit(message):
        with out_lock:
            try:
                _send(events, message)
            except BrokenPipeError:
                os._exit(0)                 # the substrate is gone; so is its ear

    ear = Ear(heard=lambda u: emit(("heard", u)), passed=lambda s: emit(("passed", s)),
              status=lambda t: emit(("status", t)))
    capture = subprocess.Popen(_capture(source, audio=True), stdout=subprocess.PIPE)
    chunks: "queue.Queue[Optional[bytes]]" = queue.Queue()

    def drain():                            # never let the device wait on thinking
        while True:
            data = capture.stdout.read(_CHUNK * 2)
            chunks.put(data or None)
            if not data:
                return

    def listen_to_substrate():
        while True:
            message = _receive(commands)
            if message is None or message[0] == "stop":
                capture.terminate()
                return
            if message[0] == "library":
                ear.teach(message[1])

    threading.Thread(target=drain, daemon=True).start()
    threading.Thread(target=listen_to_substrate, daemon=True).start()
    emit(("status", f"listening to {source}"))
    while True:
        data = chunks.get()
        if data is None:
            emit(("ended", source))
            capture.wait()
            return
        ear.feed(np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0)


def _ears() -> None:
    """The ears' program for what people's devices hear: an ear for each device's stream, all in one program, fed the
    sound the substrate passes on (16-bit mono at hearing's rate) and taught what each person's ears listen for.
    Tells the substrate, stream by stream, what was said to it and how much was let pass."""
    events, commands = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr
    out_lock = threading.Lock()

    def emit(message):
        with out_lock:
            try:
                _send(events, message)
            except BrokenPipeError:
                os._exit(0)                 # the substrate is gone; so are its ears

    ears: Dict[str, Ear] = {}
    libraries: Dict[str, Dict[str, Any]] = {}
    work: "queue.Queue[Optional[Any]]" = queue.Queue()

    def listen_to_substrate():              # never let the substrate wait on hearing
        while True:
            message = _receive(commands)
            work.put(message)
            if message is None or message[0] == "stop":
                return

    threading.Thread(target=listen_to_substrate, daemon=True).start()
    emit(("status", None, "listening to devices"))
    while True:
        message = work.get()
        if message is None or message[0] == "stop":
            return
        if message[0] == "library":         # ("library", person, library)
            _kind, person, library = message
            libraries[person] = library
            for each in ears.values():
                if each.person == person:
                    each.teach(library)
        elif message[0] == "samples":       # ("samples", stream, person, 16-bit samples, voice mode on)
            _kind, stream, person, data, attending = message
            ear = ears.get(stream)
            if ear is None:
                ear = ears[stream] = Ear(heard=lambda u, s=stream: emit(("heard", s, u)),
                                         passed=lambda t, s=stream: emit(("passed", s, t)),
                                         status=lambda t, s=stream: emit(("status", s, t)))
                ear.person = person
                ear.teach(libraries.get(person) or {})
            ear.attending = attending
            ear.feed(np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0)
        elif message[0] == "end":           # ("end", stream): the device stopped listening
            ears.pop(message[1], None)


# ── the eye ─────────────────────────────────────────────────────────────────

def _eye(source: str) -> None:
    """The eye's program: look at `source` until told to stop, keeping only
    the latest frame, and hand it over (as a JPEG) when asked."""
    import cv2
    replies, commands = sys.stdout.buffer, sys.stdin.buffer
    sys.stdout = sys.stderr
    width, height = 640, 360
    if source.startswith("file:"):
        from .vision import _ffprobe
        facts = _ffprobe(source[5:])
        if facts.get("width") and facts.get("height"):
            height = int(round(width * facts["height"] / facts["width"] / 2)) * 2
    capture = subprocess.Popen(_capture(source, audio=False, size=(width, height)),
                               stdout=subprocess.PIPE)
    latest: Dict[str, Any] = {"frame": None, "at": None}

    def look():
        size = width * height * 3
        while True:
            data = capture.stdout.read(size)
            if len(data) < size:
                return
            latest["frame"] = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
            latest["at"] = time.time()

    looking = threading.Thread(target=look, daemon=True)
    looking.start()
    while True:
        message = _receive(commands)
        if message is None or message[0] == "stop":
            # Stopped while it is still looking: let it finish what it was
            # writing before its reader goes, or it reports a broken pipe.
            capture.terminate()
            looking.join(timeout=3.0)
            capture.wait(timeout=3.0)
            return
        frame = latest["frame"]
        reply = None
        if frame is not None:
            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            reply = {"jpeg": jpeg.tobytes(), "at": latest["at"]} if ok else None
        try:
            _send(replies, reply)
        except BrokenPipeError:
            return


# ── the substrate's side ────────────────────────────────────────────────────

async def take_in_utterance(coord, utterance: Dict[str, Any], *, name: str, label: str, session: str,
                            workdir: Path, actor_identity: Optional[str],
                            picture: Optional[Path] = None) -> Dict[str, Any]:
    """One utterance said to the substrate: heard, and the scene looked at (`picture`, when an eye looked), as one
    moment, and -- when every word of it was heard as a taught word -- what was said given to the front door. Returns
    the record of what came of it.

    WHOSE IT IS. `actor_identity` is the person whose device heard it, None for the substrate's own microphone: what
    a person says to it through their device is theirs, sensed and remembered as theirs, and goes to the front door
    as their request, as their typed words do.

    WHAT IT BECOMES DECIDES WHICH MEMORY IT IS PART OF. The hearing and the
    look are sensed first and remembered after: a request they start forms
    its pursuit, and they are parts of that pursuit's memory; what starts
    no pursuit is remembered as its own."""
    import soundfile as sf
    stamp = int(utterance["at"] * 1000)
    path = workdir / f"heard_{stamp}_{os.getpid()}_{id(utterance)}.wav"
    samples = np.frombuffer(utterance["samples"], dtype=np.int16)
    sf.write(str(path), samples, utterance["rate"], subtype="PCM_16")
    jobs = [coord.sense_first(str(path), door="hear", actor_identity=actor_identity, source=label)]
    if picture is not None:
        jobs.append(coord.sense_first(str(picture), door="see", actor_identity=actor_identity, source=label))
    sensed = await asyncio.gather(*jobs, return_exceptions=True)
    heard_sensed = sensed[0]
    if isinstance(heard_sensed, BaseException):
        path.unlink(missing_ok=True)
        raise heard_sensed
    seen_sensed = sensed[1] if len(sensed) > 1 else None
    content = heard_sensed[1] if heard_sensed is not None else {}
    said = [s["word"] for s in content.get("said") or []]
    supports = [s["support"] for s in content.get("said") or []]
    text = content.get("heard_text") or ""

    words = asked_in(text, name)
    # WORDS THAT SOUND ALIKE ARE HEARD AS A PERSON HEARS THEM. The ear hands
    # on every way what was said can be heard ("I have to go" and "I have
    # two go"); the listener takes the one that makes sense
    # (`derived_reader.heard_which`), and only when it can tell.
    ways = [" ".join(asked_in(way, name)) for way in content.get("heard_texts") or []]
    ways = [way for way in dict.fromkeys(ways) if way and "..." not in way.split()]
    if ways:
        from core.semantics.derived_reader import heard_which
        which = await heard_which(ways)
        if which is not None:
            words = which.split()
    # COMPLETE when every word of what was asked was heard as a taught word,
    # or as one of the words it sounds alike to, which the listener chose.
    complete = bool(said or ways) and bool(words) and "..." not in words
    record: Dict[str, Any] = {
        "at": utterance["at"], "named": utterance["named"], "heard_text": text,
        "complete": complete,
        "spoken_by": (content.get("spoken_by") or {}).get("person"),
    }
    within = None
    if complete and words:
        asked = " ".join(words)
        metadata = {"conversation_id": session, "heard": True,
                    "heard_support": round(min(supports), 3) if supports else None}
        if actor_identity is not None:
            metadata["actor_identity"] = actor_identity
        reply = await coord.handle_user_request(
            asked, source="api" if actor_identity is not None else "manual", metadata=metadata, heard=content)
        within = reply.get("pursuit_memory_id")
        record.update({"asked": asked, "reply": reply, "pursuit_memory": within})
        logger.info("🗣 said to it: %r -> %s", asked,
                    reply.get("answer") or reply.get("task_id") or reply)
        # WHAT WAS SAID TO IT went to the front door, where what a person
        # tells it is read; it is not read a second time as the room's words.
        if heard_sensed is not None:
            heard_sensed[1]["said_to_it"] = True
    else:
        logger.info("🗣 said to it, not all understood: %r (remembered, not acted on)", text)
    from core.agents.autonomous.autonomous_coordinator import Met
    moment = [Met(path=str(path), door="hear", domain="hearing", sensed=heard_sensed)]
    if picture is not None and seen_sensed is not None \
            and not isinstance(seen_sensed, BaseException):
        moment.append(Met(path=str(picture), door="see", domain="vision",
                          sensed=seen_sensed))
    try:
        perceived = await coord.perceive_moment(
            moment, actor_identity=actor_identity, source=label, within=within)
    finally:
        for kept in (path, picture):
            if kept is not None:
                kept.unlink(missing_ok=True)        # memory keeps what it keeps
    heard = perceived[0]
    seen = perceived[1] if len(perceived) > 1 else None
    record["heard_memory"] = (heard.metadata or {}).get("memory_id") if heard else None
    record["seen_memory"] = (seen.metadata or {}).get("memory_id") if seen else None
    return record


class LiveSenses:
    """The substrate listening and looking while it runs.

    `microphone` and `camera` are sources for the ear and the eye
    (`mic:<device>`, `cam:<device>`, or `file:<path>` played in real time), or
    None for a sense that is off. Every kept utterance, what came of it and how
    much was let pass are kept in `account` for whoever asks."""

    def __init__(self, coord, *, microphone: Optional[str], camera: Optional[str],
                 name: Optional[str] = None, session: Optional[str] = None,
                 label: str = "live") -> None:
        from core.agents.autonomous.autonomous_coordinator import NAME
        self.coord = coord
        self.microphone, self.camera = microphone, camera
        self.name = " ".join(str(name or NAME).lower().split())
        self.session = session or f"voice:{microphone}"
        #: What the hearings and seeings are called when admitted (their source).
        self.label = label
        self.account: Dict[str, Any] = {"kept": [], "passed_seconds": 0.0, "passed": 0,
                                        "status": [], "told": []}
        self._stop_listening = None
        self._ear = self._eye = None
        self._tasks: List[asyncio.Task] = []
        self._eye_lock = asyncio.Lock()
        self._dir = Path(tempfile.mkdtemp(prefix="lyric_live_"))
        self._taught_version = None

    async def _program(self, which: str, source: str):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(_ROOT)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
        return await asyncio.create_subprocess_exec(
            sys.executable, "-m", "core.perception.live", which, source,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            cwd=str(_ROOT), env=env)

    async def start(self) -> None:
        await self.coord.vision._read_library()
        if self.microphone:
            self._ear = await self._program("ear", self.microphone)
            await self._teach_ear()
            self._tasks.append(asyncio.create_task(self._listen()))
            self._tasks.append(asyncio.create_task(self._keep_ear_taught()))
        if self.camera:
            self._eye = await self._program("eye", self.camera)
        # WHAT THE SUBSTRATE SAYS UNASKED to whoever talks to it here reaches them
        # here: work they asked for that ended, a reminder due. Said in words
        # until the substrate has a voice of its own.
        self._stop_listening = self.coord.on_message(self.session, self._told)
        logger.info("👂👁 live senses on: listening to %s, looking at %s; kept only when "
                    "%r is said", self.microphone or "nothing", self.camera or "nothing",
                    self.name)

    async def _teach_ear(self) -> None:
        """What the ear listens for: every word taught, among them its name."""
        faculty = self.coord.vision
        self._taught_version = faculty.taught_version
        data = pickle.dumps(("library", {"words": dict(faculty._words), "name": self.name}),
                            protocol=pickle.HIGHEST_PROTOCOL)
        self._ear.stdin.write(_LENGTH.pack(len(data)) + data)
        await self._ear.stdin.drain()

    async def _keep_ear_taught(self) -> None:
        """A word taught while listening is listened for from then on."""
        while True:
            await asyncio.sleep(2.0)
            if self.coord.vision.taught_version != self._taught_version:
                await self._teach_ear()

    async def _listen(self) -> None:
        reader = self._ear.stdout
        while True:
            try:
                head = await reader.readexactly(_LENGTH.size)
                kind, what = pickle.loads(await reader.readexactly(_LENGTH.unpack(head)[0]))
            except asyncio.IncompleteReadError:
                logger.error("the ear's program ended (exit %s) with its source still "
                             "sounding; nothing more is heard", await self._ear.wait())
                self.account["status"].append("the ear stopped")
                return
            if kind == "ended":
                # A recording played to it ends; a device that stops giving sound
                # has failed, and nothing is heard until the substrate restarts.
                self.account["status"].append(f"{what} ended")
                if what.startswith("file:"):
                    logger.info("👂 %s ended", what)
                else:
                    logger.error("👂 %s stopped giving sound; the ear is not listening", what)
                return
            if kind == "passed":
                self.account["passed"] += 1
                self.account["passed_seconds"] = round(self.account["passed_seconds"] + what, 2)
            elif kind == "status":
                logger.info("👂 %s", what)
                self.account["status"].append(what)
            elif kind == "heard":
                try:
                    await self._take_in(what)
                except Exception as error:
                    # A kept utterance that could not be taken in is reported
                    # with why; the ear goes on listening.
                    logger.error("an utterance said to it could not be taken in: %s",
                                 error, exc_info=True)
                    self.account["kept"].append({"error": str(error)})

    async def _look(self) -> Optional[Path]:
        """The scene at this moment, from the eye, as a picture file."""
        if self._eye is None:
            return None
        async with self._eye_lock:
            request = pickle.dumps(("frame",), protocol=pickle.HIGHEST_PROTOCOL)
            self._eye.stdin.write(_LENGTH.pack(len(request)) + request)
            await self._eye.stdin.drain()
            head = await self._eye.stdout.readexactly(_LENGTH.size)
            reply = pickle.loads(await self._eye.stdout.readexactly(_LENGTH.unpack(head)[0]))
        if not reply:
            return None
        path = self._dir / f"seen_{int(reply['at'] * 1000)}.jpg"
        path.write_bytes(reply["jpeg"])
        return path

    async def _take_in(self, utterance: Dict[str, Any]) -> None:
        """One utterance said to the substrate, with the scene looked at as it was said (`take_in_utterance`)."""
        self.account["kept"].append(await take_in_utterance(
            self.coord, utterance, name=self.name, label=self.label, session=self.session,
            workdir=self._dir, actor_identity=None, picture=await self._look()))

    def _told(self, message: Dict[str, Any]) -> None:
        """What the substrate said to the person here, unasked."""
        logger.info("🗣 said to you (%s): %s", message.get("why"), message.get("text"))
        self.account["told"].append({k: message.get(k) for k in ("text", "why", "about", "due_at")})

    async def stop(self) -> None:
        if self._stop_listening is not None:
            self._stop_listening()
        for task in self._tasks:
            task.cancel()
        for program in (self._ear, self._eye):
            if program is not None and program.returncode is None:
                try:
                    data = pickle.dumps(("stop",))
                    program.stdin.write(_LENGTH.pack(len(data)) + data)
                    await program.stdin.drain()
                    await asyncio.wait_for(program.wait(), 3.0)
                except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
                    program.kill()
        shutil.rmtree(self._dir, ignore_errors=True)
        logger.info("👂👁 live senses off")


def _at_hearing_rate(pcm: bytes, rate: int) -> bytes:
    """A device's 16-bit mono sound at `rate`, as the ears hear it: at hearing's own rate."""
    from math import gcd

    from scipy.signal import resample_poly
    if not DEVICE_RATES[0] <= rate <= DEVICE_RATES[1]:
        raise ValueError(f"a device sends its sound at {DEVICE_RATES[0]} to {DEVICE_RATES[1]} samples a second, "
                         f"not {rate}")
    samples = np.frombuffer(pcm[:len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    if rate != hearing.SR:
        step = gcd(hearing.SR, rate)
        samples = resample_poly(samples, hearing.SR // step, rate // step)
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


class DeviceEars:
    """Lyric listening through people's own devices, while they have Listening on (Context and privacy).

    Each device's stream of sound comes through the world (its `hearing` crossing) and is heard by an ear of its own,
    all of them in one program (`_ears`), so listening never holds the substrate's loop. Each ear wakes on the wake
    phrase (`WAKE_PHRASE`) taught in its person's own voice when they set Listening up (`teach`), and listens for
    every word taught to Lyric and to them. What it keeps is taken in as that person's, at the front door their typed
    words go to (`take_in_utterance`); everything else is dropped inside the ear, and only its length is reported.
    What was said to Lyric on a stream, and how much was let pass, wait for that device's next crossing."""

    def __init__(self, coord) -> None:
        self.coord = coord
        self._program = None
        self._tasks: set = set()
        self._dir = Path(tempfile.mkdtemp(prefix="lyric_devices_"))
        #: Each stream: whose it is, what was said to Lyric on it since the device last asked, and how much was kept
        #: and let pass.
        self._streams: Dict[str, Dict[str, Any]] = {}
        #: The version of what Lyric has been taught that each person's ears were last taught from.
        self._taught: Dict[str, int] = {}
        #: Utterances are taken in one after another on each stream, in the order they were said.
        self._order: Dict[str, asyncio.Lock] = {}

    async def _ready(self) -> None:
        if self._program is not None and self._program.returncode is None:
            return
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(_ROOT)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
        self._program = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "core.perception.live", "ears",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, cwd=str(_ROOT), env=env)
        self._taught.clear()
        self._spawn(self._listen())

    def _spawn(self, work) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _send(self, message: Any) -> None:
        data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
        self._program.stdin.write(_LENGTH.pack(len(data)) + data)
        await self._program.stdin.drain()

    @staticmethod
    async def _lessons(person: Optional[str]) -> Dict[str, List[bytes]]:
        """Every spoken word taught: Lyric's own (None), or Lyric's own and the ones taught in `person`'s voice."""
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        return await agent.lessons_taught(agent.SPOKEN_WORD_TAG, "word", actor=person)

    async def _teach_ears(self, person: str) -> None:
        """What a person's ears listen for: every word taught, Lyric's own and the ones taught in their voice."""
        from . import speech
        version = self.coord.vision.taught_version
        words = {}
        for word, archives in (await self._lessons(person)).items():
            examples = [e for e in (speech.unpack(b) for b in archives) if e is not None]
            if examples:
                words[word] = examples
        await self._send(("library", person, {"words": words, "name": WAKE_PHRASE}))
        self._taught[person] = version

    async def hear(self, person: str, stream: str, pcm: bytes, rate: int, attend: bool = False) -> Dict[str, Any]:
        """The next stretch of what a person's device hears. Returns what was said to Lyric on it since last asked.

        `attend`: the person has voice mode on on that device (they opened it there, or said the name). Their ear then
        keeps what they say to it as it does just after the name is said -- only where taught words are firmly heard
        -- for as long as voice mode stays on, not only `ATTENTION_SECONDS`."""
        sound = _at_hearing_rate(pcm, rate)
        await self._ready()
        if self._taught.get(person) != self.coord.vision.taught_version:
            await self._teach_ears(person)
        key = f"{person}\n{stream}"
        self._streams.setdefault(key, {"person": person, "stream": stream, "said": [],
                                       "kept_seconds": 0.0, "passed_seconds": 0.0})
        await self._send(("samples", key, person, sound, bool(attend)))
        return self._account(key)

    async def end(self, person: str, stream: str) -> Dict[str, Any]:
        """A device stopped listening: its ear goes, and what was said on it is answered one last time."""
        key = f"{person}\n{stream}"
        if self._program is not None and self._program.returncode is None:
            await self._send(("end", key))
        account = self._account(key)
        self._streams.pop(key, None)
        return account

    def _account(self, key: str) -> Dict[str, Any]:
        held = self._streams.get(key)
        if held is None:
            return {"said": [], "kept_seconds": 0.0, "passed_seconds": 0.0}
        said, held["said"] = held["said"], []
        return {"said": said, "kept_seconds": round(held["kept_seconds"], 2),
                "passed_seconds": round(held["passed_seconds"], 2)}

    async def teach(self, person: str, word: str, pcm: bytes, rate: int) -> Dict[str, Any]:
        """One time the person said the wake phrase, or its rival, to set Listening up: a lesson heard in their
        voice and kept in their context (`learn_word`). Returns how far their setup has come. Raises when nothing in
        the recording could be taught."""
        import soundfile as sf
        if word not in WAKE_LESSONS:
            raise ValueError(f"setting up Listening teaches {' and '.join(repr(w) for w in WAKE_LESSONS)}, "
                             f"not {word!r}")
        path = self._dir / f"lesson_{int(time.time() * 1000)}_{id(pcm)}.wav"
        sf.write(str(path), np.frombuffer(_at_hearing_rate(pcm, rate), dtype=np.int16), hearing.SR,
                 subtype="PCM_16")
        try:
            # `learn_word`'s own act, the lesson given as THEIRS: their voice calling Lyric is for their ears alone,
            # never taken as the world's (`MemoryAgent.take_in_lesson`).
            await self.coord._hear_lesson(str(path), {"word": word, "theirs": True}, actor_identity=person,
                                          source="listening setup", domain="hearing")
        finally:
            path.unlink(missing_ok=True)
        if self._program is not None and self._program.returncode is None:
            await self._teach_ears(person)
        return await self.setup(person)

    async def setup(self, person: str) -> Dict[str, Any]:
        """How far a person's setup has come: how many times each of its words has been taught in their own voice,
        and how many it takes."""
        theirs, own = await self._lessons(person), await self._lessons(None)
        return {"taught": {w: len(theirs.get(w, [])) - len(own.get(w, [])) for w in WAKE_LESSONS},
                "needed": dict(WAKE_LESSONS), "wake_phrase": WAKE_PHRASE}

    async def _listen(self) -> None:
        reader = self._program.stdout
        while True:
            try:
                head = await reader.readexactly(_LENGTH.size)
                kind, key, what = pickle.loads(await reader.readexactly(_LENGTH.unpack(head)[0]))
            except asyncio.IncompleteReadError:
                logger.error("the ears' program ended (exit %s); devices are not heard until they send again",
                             await self._program.wait())
                return
            held = self._streams.get(key) if key is not None else None
            if kind == "status":
                logger.info("👂 %s%s", f"{key.replace(chr(10), ' ')}: " if key else "", what)
            elif held is None:
                continue                        # a stream that has ended since
            elif kind == "passed":
                held["passed_seconds"] += what
            elif kind == "heard":
                held["kept_seconds"] += len(what["samples"]) / 2 / what["rate"]
                self._spawn(self._take_in(key, what))

    async def _take_in(self, key: str, utterance: Dict[str, Any]) -> None:
        held = self._streams.get(key)
        if held is None:
            return
        async with self._order.setdefault(key, asyncio.Lock()):
            try:
                record = await take_in_utterance(
                    self.coord, utterance, name=WAKE_PHRASE, label="device",
                    session=f"voice:{held['stream']}", workdir=self._dir, actor_identity=held["person"])
            except Exception as error:
                # An utterance that could not be taken in is reported with why; the ear goes on listening.
                logger.error("what was said to it through a device could not be taken in: %s", error, exc_info=True)
                held["said"].append({"at": utterance["at"], "error": str(error)})
                return
        reply = record.get("reply") or {}
        held["said"].append({"at": record["at"], "heard": record["heard_text"], "understood": record["complete"],
                             "asked": record.get("asked"), "answer": reply.get("answer")})

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._program is not None and self._program.returncode is None:
            try:
                await self._send(("stop",))
                await asyncio.wait_for(self._program.wait(), 3.0)
            except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
                self._program.kill()
        shutil.rmtree(self._dir, ignore_errors=True)


def sources_from_environment() -> Tuple[Optional[str], Optional[str]]:
    """Which microphone and camera the running substrate uses:
    `LYRIC_MICROPHONE` / `LYRIC_CAMERA` (a device name or index, or "off"),
    the system's default microphone and the first camera when unset."""
    mic = os.environ.get("LYRIC_MICROPHONE", "default").strip()
    cam = os.environ.get("LYRIC_CAMERA", "0").strip()
    return (None if mic.lower() == "off" else f"mic:{mic}",
            None if cam.lower() == "off" else f"cam:{cam}")


if __name__ == "__main__":
    which, source = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    code = 0
    try:
        if which == "ears":
            _ears()
        else:
            {"ear": _ear, "eye": _eye}[which](source)
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    # LEAVE WITHOUT THE INTERPRETER'S SHUTDOWN. A thread still waiting on the
    # substrate holds standard input's lock; Python's own shutdown then tried
    # to close it, hit the held lock, and aborted -- every time the ear
    # stopped, macOS reported "Python quit unexpectedly". Everything the
    # program had to say has been written; it exits here.
    try:
        sys.__stdout__.flush()
    except Exception:
        pass
    os._exit(code)
