#!/usr/bin/env python3
"""Each of the substrate's senses does its work in its own process.

Sight, hearing and reading are the substrate's own, as a person's eyes and ears
are theirs: what they take in is named, admitted, believed and remembered by
the substrate, in one act of perceiving, whichever senses took part. What runs
HERE is only the measuring -- the signal processing of hearing, the image
processing of sight, the opening of a text for reading -- which is pure
computation on a file and the library of what was taught.

WHY A PROCESS OF ITS OWN. Measured on the running substrate, sight took the
event loop for 1.4 s at a stretch to measure one video frame; for that time
nothing else the substrate does could run, so a question it answers in 0.3 s
waited 1.4 s behind a picture. A sense measuring in the substrate's own loop
makes it look OR think, never both. In a thread it would still hold the
interpreter for its Python-level work; in a process of its own, hearing,
sight, reading and the substrate's reasoning run at the same time, each on its
own -- so a clip is seen and heard at once, and a page is read while a picture
is looked at.

Each sense is ONE process, a program of its own, so a sense perceives one
thing at a time, in the order it was given, as a sense does. A process found
dead is reported and started again, and the perception given to the new one;
a perception that kills it twice fails, naming the sense.

Everything below `SenseProcess` runs inside a sense's process. It imports no
substrate module beyond the describers, and never touches the store.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pickle
import struct
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Where the substrate's code lives, so a sense's program imports the same code.
_ROOT = Path(__file__).resolve().parents[2]
_LENGTH = struct.Struct("!Q")


class SenseProcess:
    """One sense's own process: a program of its own (`python -m
    core.perception.senses`), where its measuring runs, apart from the
    substrate's loop and from every other sense. Started when the sense is
    first used; a sense perceives one thing at a time, in the order given.

    A PROGRAM, NOT A MULTIPROCESSING WORKER. A worker made by multiprocessing
    re-runs the script that started the substrate, and a script with no
    `__main__` guard -- every experiment here -- then started itself again
    inside the sense and killed it before it measured anything. Forking the
    substrate instead would copy its open connections, threads and event loop.
    A program of its own loads the describers and nothing else."""

    def __init__(self, sense: str) -> None:
        self.sense = sense
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None

    async def _started(self) -> asyncio.subprocess.Process:
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            # A process's pipes belong to the loop that opened them; a sense
            # used from another loop starts its own process on that loop.
            self._stop()
            self._loop, self._lock = loop, asyncio.Lock()
        if self._proc is None or self._proc.returncode is not None:
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(_ROOT)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p])
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "core.perception.senses", self.sense,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                cwd=str(_ROOT), env=env)
        return self._proc

    async def run(self, work: Callable[..., Any], *args: Any) -> Any:
        """Do `work(*args)` in this sense's process and hand back what it found.
        Whatever the work raises is raised here, as the perception's own failure.

        A PROCESS FOUND DEAD IS STARTED AGAIN, and the perception given to the
        new one, once. The substrate learns a child has died only some time
        after it happens, so a sense that died while idle looked alive, took
        the next perception, and failed it for nothing that perception did. A
        perception that kills the new process too fails, naming the sense: what
        kills a sense twice is in what it was given, and it is not given again."""
        request = pickle.dumps((work.__name__, args), protocol=pickle.HIGHEST_PROTOCOL)
        await self._started()
        async with self._lock:
            for attempt in (1, 2):
                proc = await self._started()
                try:
                    proc.stdin.write(_LENGTH.pack(len(request)) + request)
                    await proc.stdin.drain()
                    size = _LENGTH.unpack(await proc.stdout.readexactly(_LENGTH.size))[0]
                    ok, found = pickle.loads(await proc.stdout.readexactly(size))
                    break
                except (asyncio.IncompleteReadError, BrokenPipeError, ConnectionResetError) as error:
                    self._proc = None
                    if attempt == 2:
                        raise RuntimeError(
                            f"the {self.sense} process died twice on this perception "
                            f"({work.__name__}); what it was given is not given again") from error
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    logger.error("the %s process (pid %s) had died (exit %s); started again "
                                 "for this perception", self.sense, proc.pid, await proc.wait())
        if not ok:
            raise found
        return found

    def _stop(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        self._proc = None

    def close(self) -> None:
        self._stop()


def _serve() -> None:
    """A sense's program: take one request at a time from the substrate, do
    the work, send back what was found or what went wrong."""
    requests, replies = sys.stdin.buffer, sys.stdout.buffer
    # Replies are the only thing written to the reply channel; anything a
    # describer prints goes where the substrate's own logging goes.
    sys.stdout = sys.stderr
    work = {fn.__name__: fn for fn in _WORK}
    while True:
        head = requests.read(_LENGTH.size)
        if len(head) < _LENGTH.size:
            return
        name, args = pickle.loads(requests.read(_LENGTH.unpack(head)[0]))
        try:
            reply = (True, work[name](*args))
        except Exception as error:
            reply = (False, error)
        try:
            data = pickle.dumps(reply, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as error:
            data = pickle.dumps((False, RuntimeError(f"{name} found something that could "
                                                     f"not be sent back: {error}")))
        try:
            replies.write(_LENGTH.pack(len(data)) + data)
            replies.flush()
        except BrokenPipeError:
            return          # the substrate is gone; so is its sense


# ── hearing ─────────────────────────────────────────────────────────────────

#: Landmark lookup tables already built in this process, by the rows they were
#: built from: a taught song is looked up in every recording heard, and its
#: table is the same until it is taught again.
_TABLES: Dict[Tuple[int, Tuple[int, ...], int], Any] = {}


def _table(rows):
    import zlib
    from . import hearing
    key = (len(rows), tuple(rows.shape), zlib.crc32(rows.tobytes()))
    if key not in _TABLES:
        _TABLES[key] = hearing.landmark_index(rows)
    return _TABLES[key]


def listen(path: str, library: Dict[str, Any], lesson: Optional[Tuple[str, str]] = None,
           soundtrack: bool = False) -> Dict[str, Any]:
    """Everything hearing measures of one recording (or a video's sound track):
    its sounds (`hearing.describe`), the speech in it as far as speech was
    taught (`speech.recognise`), its music (`music.describe`: the beat, the
    key, the notes of a single line), the known sounds and the songs taught in
    it (landmark agreement, as raw counts: `(name, agreeing, at)`), and the
    trace a memory of it keeps -- with a lesson's example in it when the
    recording is a lesson.

    `library` is what was taught, as the faculty holds it: `words`, `voices`,
    `reach`, `sounds` (name -> landmark rows), `songs` (title -> the landmark
    rows of each hearing that taught it) and `tunes` (title -> the tune line
    of each hearing that taught it, when it was a single line); the songs
    whose tune a single line heard carries come back under `tunes`. A lesson
    that cannot be
    taught raises before anything is kept."""
    import numpy as np
    from . import hearing, music, speech
    desc = hearing.describe(path)
    if soundtrack and not desc.get("has_audio"):
        return {"desc": desc}
    y = hearing.decode(path)
    example = None
    if lesson is not None:
        example = (music.song_example(y, path) if lesson[0] == "song"
                   else speech.lesson_example(lesson[0], y, path))
    heard = speech.recognise(y, desc.get("sounds") or [], library.get("words") or {},
                        library.get("voices") or {}, library.get("reach"))
    known: List[Tuple[str, int, Any]] = []
    songs: List[Tuple[str, int, Any]] = []
    # Every hearing's landmarks: matched against what was taught here, and kept
    # in its trace so memory can know the same sound when it is met again.
    marks = hearing.landmarks(y)
    if library.get("sounds") or library.get("songs"):
        if len(marks):
            for name, rows in (library.get("sounds") or {}).items():
                count, at = hearing.agreement(_table(rows), marks)
                if count >= hearing.KNOWN_MIN_AGREE:
                    known.append((name, int(count), at))
            for title, examples in (library.get("songs") or {}).items():
                if not examples:
                    continue
                best = max((music.song_agreement(_table(rows), rows, marks)
                            for rows in (np.asarray(e, np.int32) for e in examples)),
                           key=lambda found: found[2])
                count, at, share = best
                if count >= hearing.KNOWN_MIN_AGREE and share >= music.SONG_MIN_SHARE:
                    songs.append((title, count, at, round(share, 4)))
    # A SINGLE LINE CARRIES A TUNE: followed against every song's taught tune,
    # so a song is known when someone else hums or sings it, in their own key
    # and at their own pace.
    described = music.describe(y)
    tune = described.pop("tune", None)
    # A SONG TAUGHT FROM A MIX keeps the tune of the mix's melody, so the song
    # is known when someone hums or sings it.
    from_mix = False
    if tune is None and lesson is not None and lesson[0] == "song":
        tune = music.tune_line(music.melody_of_mix(y))
        from_mix = tune is not None
    return {"desc": desc, "speech": heard, "music": described,
            "known": known, "songs": sorted(songs, key=lambda s: -s[3]),
            "tunes": ([] if from_mix else music.tunes_heard(tune, library.get("tunes") or {})),
            "tune": tune,
            "trace": (hearing.trace_bytes(desc["trace"], example, marks, tune, from_mix)
                      if desc.get("trace") else None)}


def sound_agreements(heard, kept: Sequence[bytes]) -> List[Tuple[int, Any, float]]:
    """How each kept hearing's landmarks line up in what was heard: for each
    trace, the agreeing count, where its start fell, and the share of what was
    heard while it would have been sounding (`music.song_agreement`). The
    counting runs here, in hearing's process, never in the substrate's loop."""
    import numpy as np
    from . import hearing, music
    heard = np.asarray(heard, np.int32)
    out: List[Tuple[int, Any, float]] = []
    for data in kept:
        rows = hearing.trace_landmarks(data)
        if rows is None or not len(rows) or not len(heard):
            out.append((0, None, 0.0))
            continue
        out.append(music.song_agreement(_table(rows), rows, heard))
    return out


def sound_landmarks(path: str):
    """A reference sound's landmark rows, for knowing it when heard again."""
    from . import hearing
    return hearing.landmarks(hearing.decode(path))


def rebuild_sound(trace: bytes):
    """A remembered sound heard again in the mind, from its trace."""
    from . import hearing
    return hearing.rebuild(hearing.trace_from_bytes(trace))


# ── sight ───────────────────────────────────────────────────────────────────

#: A local-descriptor match this strong recognises a specific known instance.
INSTANCE_MIN_GOOD = 12
INSTANCE_RATIO = 0.75


def _descriptors(path: str):
    """A picture's ORB descriptors, or None when it has none to match on.
    Raises when the file is not a readable picture: "I cannot read this" and
    "there is nothing in it to match" are different states."""
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cannot read {path} as a picture")
    _kp, des = cv2.ORB_create(1500).detectAndCompute(img, None)
    return des


def look(path: str, instances: Dict[str, Any]) -> Dict[str, Any]:
    """Everything sight measures of one picture (`vision.describe_image`),
    which known instances are in it, by descriptor match: `(name, score)`, and
    the sight trace a memory of it keeps (`vision.sight_features`): what the
    picture is known again by, never the picture."""
    from . import vision
    desc = vision.describe_image(str(path))
    features = vision.sight_features(str(path))
    known: List[Tuple[str, float]] = []
    if instances:
        import cv2
        des = features["descriptors"]
        if des is not None and len(des) >= 2:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
            for name, ref in instances.items():
                try:
                    pairs = matcher.knnMatch(des, ref, k=2)
                except cv2.error:
                    continue
                good = sum(1 for pr in pairs if len(pr) == 2
                           and pr[0].distance < INSTANCE_RATIO * pr[1].distance)
                if good >= INSTANCE_MIN_GOOD:
                    known.append((name, good / max(1, len(ref))))
    return {"desc": desc, "known": sorted(known, key=lambda t: -t[1]),
            "trace": vision.sight_trace_bytes(features)}


#: A keypoint matches when its nearest neighbour is clearly nearer than the
#: next (Lowe's ratio), as a known instance's do.
SIGHT_RATIO = INSTANCE_RATIO
#: How far, in shares of the picture, a matched keypoint may sit from where one
#: geometry puts it and still agree with it (RANSAC's reprojection threshold).
SIGHT_REPROJECTION = 0.01


def sight_agreements(seen: Dict[str, Any], kept: Sequence[bytes]) -> List[Dict[str, Any]]:
    """How each kept seeing agrees with what is seen: `matched` keypoints
    (ratio test), how many of them fit ONE geometry of one picture onto the
    other (`agreeing`, RANSAC homography), and how many of the two pictures'
    64 difference-hash bits differ (`hash_distance`). Measured here, in sight's
    process."""
    import cv2
    import numpy as np
    from . import vision
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    query = np.asarray(seen["descriptors"], np.uint8)
    points = np.asarray(seen["points"], np.float32)
    out: List[Dict[str, Any]] = []
    for data in kept:
        other = vision.sight_trace(data)
        found = {"matched": 0, "agreeing": 0, "hash_distance": 64}
        if other is None:
            out.append(found)
            continue
        found["hash_distance"] = bin(int(seen["dhash"]) ^ int(other["dhash"])).count("1")
        if len(query) >= 2 and len(other["descriptors"]) >= 2:
            pairs = matcher.knnMatch(query, other["descriptors"], k=2)
            good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < SIGHT_RATIO * p[1].distance]
            found["matched"] = len(good)
            if len(good) >= 4:
                src = points[[g.queryIdx for g in good]].reshape(-1, 1, 2)
                dst = other["points"][[g.trainIdx for g in good]].reshape(-1, 1, 2)
                _h, mask = cv2.findHomography(src, dst, cv2.RANSAC, SIGHT_REPROJECTION)
                found["agreeing"] = int(mask.sum()) if mask is not None else 0
        out.append(found)
    return out


def sight_trace_of(path: str) -> bytes:
    """A picture's sight trace alone, for a picture remembered outside a seeing."""
    from . import vision
    return vision.sight_trace_bytes(vision.sight_features(str(path)))


def watch(path: str) -> Dict[str, Any]:
    """What sight measures of a video (`vision.describe_video`)."""
    from . import vision
    return vision.describe_video(str(path))


def describe_picture(path: str) -> Dict[str, Any]:
    """Sight's measurement of a picture alone, with nothing matched."""
    from . import vision
    return vision.describe_image(str(path))


def picture_descriptors(path: str):
    """A reference picture's descriptors, for knowing it when seen again."""
    return _descriptors(path)


def rebuild_picture(perceived: Dict[str, Any], longest: int = 800):
    """A remembered picture seen again in the mind, from its gist."""
    from . import vision
    return vision.rebuild(perceived, longest=longest)


# ── reading ─────────────────────────────────────────────────────────────────


def read(path: str) -> Dict[str, Any]:
    """Everything reading measures of one file (`reading.read_document`): what
    it really is, its pages of text, and the trace a memory of it keeps -- the
    runs of words it is known again by (`reading.shingles`), never the words."""
    from . import reading
    found = reading.read_document(str(path))
    found["trace"] = reading.trace_bytes(reading.shingles(found["pages"]))
    return found


def text_agreements(met: Sequence[int], kept: Sequence[bytes]) -> List[Tuple[int, float, bool]]:
    """How much each kept reading shares with the text met now: the runs of
    words they share, the share of the shorter of the two, and whether it is the
    same text (`reading.agreement`). Measured here, in reading's process."""
    from . import reading
    out: List[Tuple[int, float, bool]] = []
    for data in kept:
        runs = reading.trace_keys(data)
        out.append((0, 0.0, False) if runs is None else reading.agreement(met, runs))
    return out


#: The work a sense's program does, by name.
_WORK = (listen, sound_landmarks, rebuild_sound, look, watch, describe_picture,
         picture_descriptors, rebuild_picture, read, sight_trace_of,
         sound_agreements, sight_agreements, text_agreements)


if __name__ == "__main__":
    _serve()
