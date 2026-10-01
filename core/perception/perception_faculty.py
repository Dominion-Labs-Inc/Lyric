#!/usr/bin/env python3
"""The substrate's senses: sight, hearing and reading, each its own.

They are the substrate's as a person's eyes and ears are theirs. None of them
owns what it takes in, and none does the work of another: sight takes in
pixels, hearing sound, reading written words, and whatever the substrate does
with what it met -- remembers it, knows it again, names it, judges how sure it
is, reads the words in it, believes what it says -- it does however it met it
(`AutonomousCoordinator.perceive_moment`).

THE SENSES WORK AT THE SAME TIME. A thing is taken in by every sense that can
take something from it, at once, each in its own process (`senses`): a clip is
seen and heard together. What is met at one moment -- a word said to it and the
room it was said in -- is one experience, not one per sense.

The substrate does not have many ad-hoc ways to read text -- it has one reader,
and every path that consumes language goes through it: what reading opens of a
file goes to that reader as a sentence typed or said does. `sense(path)` is how
a file becomes STRUCTURE: it perceives structure with the classical describers
(core.perception.vision for pixels, core.perception.hearing for sound,
core.perception.reading for written words) and matches known instances.
Sensing admits nothing: `admit_percept` takes in what was sensed, once, as
evidence and into what the substrate is aware of perceiving, so a percept is
admitted exactly once by one owner. Naming a novel structure is NOT done here --
that is the substrate's to learn downstream. What the senses produce is honest
structure; what it means is learned.

    from core.perception.perception_faculty import get_perception_faculty
    vf = get_perception_faculty()
    modality, content = await vf.sense("/path/to/photo.jpg")   # -> structure, not yet admitted
    modality, content = await vf.sense("/path/to/doorbell.wav")
    modality, content = await vf.sense("/path/to/report.pdf")
    await vf.learn_instance("front_door", "ref.jpg")           # register a known instance
    await vf.learn_instance("doorbell", "doorbell.wav")        # ... or a known sound
    await coord.learn_word("three", "three.wav", actor_identity=None)   # a word, taught by
    await coord.learn_voice("Ada", "ada.wav", actor_identity=None)       # hearing an example
    await coord.learn_song("Greensleeves", "greensleeves.mp3", actor_identity=None)
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import hearing, music, reading, senses, speech, vision
from .senses import SenseProcess

logger = logging.getLogger(__name__)

_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
#: What the ear can open: every container ffmpeg decodes to a sound track.
_AUDIO_EXT = {".wav", ".wave", ".aif", ".aiff", ".aifc", ".flac", ".mp3", ".m4a",
              ".aac", ".ogg", ".oga", ".opus", ".caf", ".au", ".wma", ".amr"}
#: What the visual reader can open. Declared so a file of NO known kind is
#: refused as what it is -- an unreadable kind -- instead of falling through to
#: the image reader and being reported as "not a readable image", which names
#: the wrong reason and sends anyone debugging it to the wrong place.
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff",
              ".webp", ".ppm", ".pgm"}


def _encode(data: bytes) -> str:
    """Bytes as text, to ride in a percept that is stored as JSON."""
    import base64
    return base64.b64encode(data).decode("ascii")


def decode_trace(text: str) -> bytes:
    """A trace carried in a percept, back to its bytes."""
    import base64
    return base64.b64decode(text.encode("ascii"))


def _term(text: str) -> str:
    """A single admissible term from a free string (filename, colour+shape)."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return cleaned or "scene"


def _percept_subject(label: str, sha: Optional[str]) -> str:
    """What to CALL the thing that was just seen.

    THE NAME HAS TO COME FROM WHAT WAS SEEN, and it used to come from who was
    looking. `see()` took its subject from the caller's `source`, and the
    substrate's own environment scan passes `source="environment"` for every
    image it walks past — so every picture in the world was the same individual.
    Demonstrated on the live graph: two different pictures, a red circle and a
    blue square, through one source, produced ONE concept holding `isa circle`
    AND `isa square`, `isa vivid_red` AND `isa vivid_blue`. The substrate came to
    believe in a thing that was both.

    The content digest is what makes two sightings be of the same thing, so it
    is what the name is built from. Seeing one picture twice lands on one
    individual and the evidence accumulates, which is right; seeing two pictures
    never merges them, which is the defect. The caller's label is kept in front
    of it so the name still says where the looking came from.

    THE DIGEST IS JOINED WITHOUT A WORD BREAK, and that is not cosmetic. The
    concept store admits a name of at most `MAX_TERM_WORDS` (4) underscore-
    separated words, on the stated ground that past this it is a clause someone
    stapled together rather than a thing. Joining with an underscore spent a word
    on the digest and pushed `recog_ab12cd_5_<digest>_blob1` to five, so EVERY
    blob name was refused at the door -- measured: the naming reflex fired
    correctly, `read_names` returned the category, and the write was rejected
    with "5 words is a clause, not a name" while the substrate went on holding
    only what it had measured. A percept's name is an identifier, not prose, and
    it has to fit in the budget the store gives a name rather than argue for a
    bigger one."""
    base = _term(label)
    return f"{base}x{_term(sha)[:10]}" if sha else base


#: THE KNOWN-INSTANCE LIBRARY LIVES IN THE STORE. It was a `.npz` file under the
#: repo's data/: a wipe of the store left it behind, an instance of the model run
#: from another checkout never saw it, and two instances each rewrote the whole
#: file with their own copy. One row per instance: its ORB descriptors, as bytes,
#: with the shape and type that read them back.
_VISION_INSTANCES_DDL = """
CREATE TABLE IF NOT EXISTS unified.vision_instances (
    name         TEXT PRIMARY KEY,
    descriptors  BYTEA NOT NULL,
    rows         INTEGER NOT NULL,
    cols         INTEGER NOT NULL,
    dtype        TEXT NOT NULL,
    learned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)"""
#: KNOWN SOUNDS, the same way: one row per sound, its landmark hashes as bytes
#: (rows of f1, f2, dt, t) with the shape and type that read them back.
_SOUND_INSTANCES_DDL = """
CREATE TABLE IF NOT EXISTS unified.sound_instances (
    name         TEXT PRIMARY KEY,
    landmarks    BYTEA NOT NULL,
    rows         INTEGER NOT NULL,
    cols         INTEGER NOT NULL,
    dtype        TEXT NOT NULL,
    learned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)"""
_vision_schema_ready = False


async def _instance_library():
    """The store, with the library's tables in it."""
    global _vision_schema_ready
    from core.database import get_database_manager
    db = get_database_manager()
    if not getattr(db, "initialized", False):
        await db.initialize()
    if not _vision_schema_ready:
        await db.execute_query(_VISION_INSTANCES_DDL, (), commit=True)
        await db.execute_query(_SOUND_INSTANCES_DDL, (), commit=True)
        _vision_schema_ready = True
    return db


#: A region owning more than this share of the picture's own edge is the GROUND:
#: it surrounds the scene rather than sitting in it. To be the surround, a region
#: has to be most of the surround.
_GROUND_BORDER = 0.5


def _object_regions(regions) -> List[Dict[str, Any]]:
    """The regions that are THINGS, in the order they get numbered as blobs.

    THE GROUND IS DECIDED BY WHAT A REGION IS, not by how big it is. This used to
    be `area_fraction > 0.9` -- a single magic number standing in for the whole
    idea of "background" -- and a number cannot say what a region is. Two
    measured failures, both from the same cause:

    - Under a 10% occlusion the white ground came in at area 0.895, missed the
      cut by five thousandths, and was admitted as an OBJECT. It then out-ranked
      the real object by area, so the thing being looked at silently moved from
      blob1 to blob2 and a harness reading "the first thing" measured the wall.
    - A crop shrinks the visible ground below 0.9 while leaving it exactly as
      much the background. FRAME-01 measured 50 spurious relations to `white`
      from precisely this.

    Background is what the edges of a picture are made of, which is a property a
    region either has or has not, and `border_share` measures it directly. A
    picture whose subject fills the frame edge to edge has no object regions at
    all, and that was true of the old rule too -- what changes is that it is now
    the answer to a question rather than the side effect of a threshold.

    ONE AUTHORITY, because the relations between blobs are indices into this
    list. Deciding "is this a thing" separately in each place is how
    `X larger_than Y` comes to mean a different pair than the names say."""
    out: List[Dict[str, Any]] = []
    for r in regions or []:
        if float(r.get("border_share") or 0.0) > _GROUND_BORDER:
            continue                      # this is the surround, not a thing
        if not (r.get("color") or r.get("shape")):
            continue
        out.append(r)
    return out


class PerceptionFaculty:
    """The substrate's senses -- sight, hearing and reading -- and what they
    have been taught to know again.

    THE SENSES ARE THE SUBSTRATE'S, NOT THIS CLASS'S. It holds the senses'
    processes and the library of things, sounds, words, voices and songs
    taught; the substrate perceives (`AutonomousCoordinator.perceive_moment`),
    and this is where its senses measure. No sense does another's work: a
    document is READ, by reading, in reading's own process -- it was once
    "sight's", which made the substrate's reading a kind of looking.

    `sense` TAKES A THING IN BY EVERY SENSE THAT CAN, AT ONCE (`senses_of`):
    pixels by sight, sound by hearing, written words by reading, a clip by sight
    and hearing together. Each returns the same `(modality, content)` contract,
    and `content["senses"]` says which senses took part, so the pipeline
    downstream treats what was read exactly as what was seen or heard. Adding a
    sense means adding its measuring here, never a second faculty.

    HEARING IS ONE OF THESE READERS, not a faculty beside this one. What it
    hears is stated on the SAME contract as what sight sees: each sound is a
    perceived individual under `blobs`, the key the pipeline reads as "the
    individuals perceived", carrying what it is (`isa`, with support) and
    what was measured of it in this recording (`properties`). How the sounds
    stand to one another goes under `blob_relations`, as regions' relations
    do. So admission, the naming reflex, describing a kind and the acceptance
    band all serve hearing without a line of their own.

    SPEECH IS HEARD AS FAR AS IT WAS TAUGHT (`core.perception.speech`). Words
    and voices are taught by HEARING an example of them, told what it is: the
    lesson is a hearing like any other, remembered as one; a recording is then
    heard for the words said (`said`, `heard_text`), each sound for whether it
    is a voice (`isa voice`), and the voices for whose they are (`spoken_by`),
    each with the support its matching earned.

    MUSIC IS HEARD IN EVERY RECORDING (`core.perception.music`): the key it is
    in (`in_key`) when it fits one closely, its tempo (`tempo`) when the beat is
    strong enough to name, and the notes of its melody (`melody`) when a single
    line holds its pitches at a singer's pace, each with the support its
    measurement earned. A SONG is taught as a word is, by hearing it, told what
    it is called; from then on it is known wherever it is played (`plays`).

    WHAT WAS SENSED IS ADMITTED HERE TOO (`admit_percept`), once: as evidence about the
    memory of perceiving it, and into what the substrate is aware of perceiving
    now (`recent_percepts`), so a memory forming while it perceives says what was in view.
    """

    #: How many percepts the substrate is aware of at once, newest last.
    AWARENESS = 1000

    def __init__(self) -> None:
        # Reference instances: name -> ORB descriptors. This is recognition of
        # KNOWN things by matching, not classification of novel ones -- no model.
        self._instances: Dict[str, Any] = {}
        #: Known sounds: name -> (landmark rows, lookup table). The same act for
        #: the ear: a sound heard before, recognised by matching, no model.
        self._sounds: Dict[str, Any] = {}
        #: Spoken words and voices TAUGHT by example: word -> the measured
        #: examples, person -> the measured examples of their voice. Read from
        #: memory, where teaching puts them; these are this process's copy.
        self._words: Dict[str, List[Any]] = {}
        self._voices: Dict[str, List[Any]] = {}
        #: Songs taught by hearing them: title -> the landmarks of each hearing.
        self._songs: Dict[str, List[Any]] = {}
        #: ... and title -> the tune of each hearing that taught it
        #: (`music.tune_line`), which the song is known by when hummed or sung:
        #: {"line", "mix"}, `mix` when it was read from a mix's melody.
        self._tunes: Dict[str, List[Any]] = {}
        #: How near the taught voices lie to one another (`speech.voice_reach`),
        #: kept with them so it is measured once per teaching, not per hearing.
        self._voice_reach: Optional[tuple] = None
        #: Moves whenever what was taught changes, so a listener holding a copy
        #: (the live ear) knows to take it again.
        self._taught_version = 0
        #: Whether this process has read the library from the store yet.
        self._instances_loaded = False
        #: EACH SENSE MEASURES IN ITS OWN PROCESS (`senses`), so sight,
        #: hearing, reading and the substrate's reasoning run at the same time.
        self._sight = SenseProcess("sight")
        self._hearing = SenseProcess("hearing")
        self._reading = SenseProcess("reading")
        #: WHAT IS BEING PERCEIVED NOW: the percepts met lately, newest last.
        self._aware: deque = deque(maxlen=self.AWARENESS)
        #: How many percepts were admitted as evidence in this process.
        self._admitted = 0

    # -- admitting what was sensed ------------------------------------------

    async def admit_percept(self, subject: str, modality: str, content: Dict[str, Any],
                    memory_id: Optional[str] = None, *, origin: "Origin") -> Any:
        """Take in what was sensed, once: into what the substrate is aware of
        perceiving now, and as evidence.

        `memory_id` is the memory of HAVING PERCEIVED it, formed by the caller
        that met it (`coord.see` remembers what it looked at). It is the
        percept's identity: every claim admitted from it is a belief ABOUT that
        memory, and anything formed while it is admitted links to it by
        reference (`set_acting_percept`). Without one the belief store refuses
        the claims -- correctly, since a belief names the memory it is about.

        `origin` is whose perception this is, and it has no default. A person's
        image is kept in their context, and what it shows goes where their words
        go, never into the substrate's own knowledge."""
        percept = self.note_percept(subject, modality, content, origin=origin)
        digest = (content or {}).get("sha256") or (content or {}).get("digest")
        if memory_id:
            # The memory of perceiving IS the percept's identity.
            percept.metadata["memory_id"] = str(memory_id)
        if digest:
            percept.metadata["digest"] = str(digest)
        # ADMITTED INSIDE THE SCOPE OF THE PERCEPT, so anything formed while the
        # evidence is being admitted links to what was perceived BY REFERENCE
        # rather than by having happened near it in time.
        token = set_acting_percept(memory_id, digest)
        try:
            await self._admit_as_evidence(subject, modality, content,
                                          memory_id=memory_id, origin=origin)
        finally:
            reset_acting_percept(token)
        return percept

    async def _admit_as_evidence(self, subject, modality, content, *,
                                 memory_id: Optional[str] = None,
                                 origin: "Origin") -> None:
        """Submit a percept as evidence. Never fails perceiving itself.

        Dispatched on modality: a sensor reading, an image, a video, a sound and
        a document read each carry structure a bare component/status envelope
        cannot (a typed value and unit, perceived individuals, recognised
        labels, temporal events, what the words said), so each has its own
        producer. Anything else -- a named
        component in a named state, a corpus arriving -- takes the general
        `submit_perception` path. The producer decides what is nameable; an
        unrecognised modality is not coerced into one that loses its structure.
        Whose it is travels with it."""
        try:
            from core.domain import evidence_producers as ep

            producer = {
                "sensor": ep.submit_sensor_reading,
                "image": ep.submit_image,
                "video": ep.submit_video,
                "audio": ep.submit_audio,
                "document": ep.submit_reading,
            }.get(str(modality or "").strip().lower())
            if producer is not None:
                await producer(subject, content or {}, memory_id=memory_id, origin=origin)
            else:
                await ep.submit_perception(subject, modality, content or {},
                                           memory_id=memory_id, origin=origin)
            self._admitted += 1
        except Exception as e:
            logger.error("perception from %s could not be recorded as evidence: %s: %s",
                         subject, type(e).__name__, e)

    def note_percept(self, subject: str, modality: str, content: Dict[str, Any], *,
             origin: "Origin", confidence: Optional[float] = None) -> Any:
        """Take a percept into what the substrate is aware of perceiving now,
        WITHOUT admitting it as evidence: for a percept whose evidence its own
        owner already admitted (a recognition rides `learn_fact`). `confidence`
        is what was measured of it, or None when nothing was."""
        from core.agents.autonomous.shared_types import PerceptionData
        percept = PerceptionData(source=subject, data_type=modality,
                                 content=dict(content or {}),
                                 confidence=None if confidence is None else float(confidence),
                                 origin=origin)
        self._aware.append(percept)
        return percept

    def recent_percepts(self, limit: int = 10) -> List[Any]:
        """The percepts met most lately, oldest first."""
        return list(self._aware)[-limit:] if limit > 0 else []

    def awareness(self) -> Dict[str, int]:
        """What the substrate is aware of perceiving, counted."""
        return {"aware": len(self._aware), "admitted": self._admitted}

    # -- durability ---------------------------------------------------------
    #
    # A REFERENCE INSTANCE IS LEARNED STATE. It lived in this dict and died with
    # the process, so the substrate could be shown its own front door, recognise
    # it all afternoon, and not know it the next morning -- and nothing said so,
    # because an empty library is indistinguishable from a library that matched
    # nothing. Written through on learning rather than flushed at shutdown:
    # learning an instance is a rare deliberate act, and a shutdown-only flush
    # loses everything on an unclean exit.

    async def load_instances(self) -> int:
        """Read the known-instance library -- things seen and sounds heard --
        from the store. Returns how many."""
        import numpy as np
        db = await _instance_library()
        rows = await db.execute_query(
            "SELECT name, descriptors, rows, cols, dtype FROM unified.vision_instances",
            (), fetch_all=True) or []
        self._instances = {
            str(r["name"]): np.frombuffer(bytes(r["descriptors"]), dtype=str(r["dtype"]))
            .reshape(int(r["rows"]), int(r["cols"]))
            for r in rows}
        sound_rows = await db.execute_query(
            "SELECT name, landmarks, rows, cols, dtype FROM unified.sound_instances",
            (), fetch_all=True) or []
        self._sounds = {}
        for r in sound_rows:
            marks = np.frombuffer(bytes(r["landmarks"]), dtype=str(r["dtype"])) \
                .reshape(int(r["rows"]), int(r["cols"]))
            self._sounds[str(r["name"])] = (marks, hearing.landmark_index(marks))
        await self._load_lessons()
        self._instances_loaded = True
        logger.info("👁️ restored %d known instance(s), %d known sound(s), %d taught "
                    "word(s), %d taught voice(s) and %d taught song(s)", len(self._instances),
                    len(self._sounds), len(self._words), len(self._voices), len(self._songs))
        return len(self._instances) + len(self._sounds)

    async def _load_lessons(self) -> None:
        """The words, voices and songs taught, as memory holds them: every
        hearing that was a lesson, with the example kept in its trace."""
        from core.memory import get_memory_agent
        agent = await get_memory_agent()
        words = await agent.lessons_taught(agent.SPOKEN_WORD_TAG, "word")
        voices = await agent.lessons_taught(agent.VOICE_TAG, "person")
        songs = await agent.lessons_taught(agent.SONG_TAG, "song")
        things = await agent.lessons_taught(agent.THING_TAG, "thing")
        kept = lambda archives: [e for e in (speech.unpack(b) for b in archives) if e is not None]
        self._words = {w: kept(archives) for w, archives in words.items() if kept(archives)}
        self._voices = {p: kept(archives) for p, archives in voices.items() if kept(archives)}
        self._songs = {t: [e.astype("int32") for e in kept(archives)]
                       for t, archives in songs.items() if kept(archives)}
        tuned = lambda archives: [{"line": line, "mix": hearing.trace_tune_from_mix(b)}
                                  for line, b in ((hearing.trace_tune(b), b) for b in archives)
                                  if line is not None]
        self._tunes = {t: tuned(archives) for t, archives in songs.items() if tuned(archives)}
        # THINGS SHOWN are known by their keypoints, beside the references
        # learned as instances: the latest showing of each name is the one held.
        for name, archives in things.items():
            for data in archives:
                features = vision.sight_trace(data)
                if features is not None and len(features["descriptors"]):
                    self._instances[_term(name)] = features["descriptors"]
        self._voice_reach = speech.voice_reach(self._voices)
        self._taught_version += 1

    @property
    def taught_version(self) -> int:
        """Moves whenever the words, voices or songs taught change."""
        return self._taught_version

    @property
    def taught_songs(self) -> Dict[str, int]:
        """Each song taught by hearing it, with how many hearings taught it."""
        return {t: len(examples) for t, examples in sorted(self._songs.items())}

    @property
    def taught_words(self) -> Dict[str, int]:
        """Each word taught by example, with how many examples, as last read."""
        return {w: len(examples) for w, examples in sorted(self._words.items())}

    @property
    def taught_voices(self) -> Dict[str, int]:
        """Each person whose voice was taught, with how many examples."""
        return {p: len(examples) for p, examples in sorted(self._voices.items())}

    @property
    def known_instances(self) -> List[str]:
        """The things this faculty can recognise by name -- seen or heard --
        as last read."""
        return sorted(set(self._instances) | set(self._sounds))

    async def forget_instance(self, name: str) -> bool:
        """Remove a reference instance, seen or heard. True if one was there."""
        from core.agents.memory_agent import memory_agent
        await _instance_library()
        seen = await memory_agent().drop_vision_instance(_term(name))
        heard = await memory_agent().drop_sound_instance(_term(name))
        self._instances.pop(_term(name), None)
        self._sounds.pop(_term(name), None)
        return seen is not None or heard is not None

    # -- the one entry point ------------------------------------------------

    @staticmethod
    def _document_content(read: Dict[str, Any], p: Path, label: str) -> Dict[str, Any]:
        """A document, as reading's process opened it (`senses.read`), in the
        structure a percept is admitted from.

        A DOCUMENT IS READ, NOT FETCHED. The substrate had tools that GENERATE a
        PDF and none that reads one, so every document it was given was a file
        it could write and not open. Reading is one of its senses, as sight and
        hearing are, and what it opens is taken in by the same act.

        WHAT IS RETURNED IS STRUCTURE, NOT A BLOB OF TEXT. The pages, and the
        text as the document laid it out, so the substrate's reader reads prose
        rather than a run-on of every page concatenated. Naming follows sight
        and hearing exactly: the subject comes from the CONTENT digest, so the
        same document met twice is one individual and two documents never
        merge. Its `trace` is the runs of words it is known again by, as a
        picture's is its keypoints and a sound's its landmarks.

        A FILE WITH NO WRITTEN WORDS READING CAN OPEN RAISES. It is not opened
        as bytes and reported as an empty document: "I cannot read this kind of
        file" and "this file says nothing" are different states, and only one
        of them is honest.
        """
        if read.get("named"):
            logger.warning(
                "document %s is named %s but its contents are %s — read as "
                "what it IS, not as what it is called", p.name, p.suffix, read["kind"])
        if read.get("lossy"):
            logger.warning("document %s is not valid UTF-8; decoded with replacement "
                           "— some characters are not what the file says", p.name)
        pages = read["pages"]
        # A READER THAT RETURNED NOTHING IS REPORTED AS SUCH. A scanned PDF is
        # pages of pixels with no text layer; saying "0 words" is the true
        # answer and reading words off pixels is a sense of its own, not a
        # silent empty.
        words = sum(len(page.split()) for page in pages)
        # WHAT IT IS, as its bytes say; a plain text says only by its name, and
        # not even that when its name claimed another kind.
        form = (read["kind"] if read["kind"] != "text" or read.get("named")
                else (p.suffix.lower().lstrip(".") or "text"))
        content: Dict[str, Any] = {
            "subject": _percept_subject(label, read["sha256"]),
            "sha256": read["sha256"],
            "pages": len(pages),
            "words": words,
            "text": pages,
            "properties": {"has_format": form, "has_pages": len(pages)},
            "caption": f"{len(pages)} page(s), {words} word(s), {form} document",
            "trace": _encode(read["trace"]) if read.get("trace") else None,
            "senses": ["reading"],
        }
        if not words:
            logger.warning(
                "document %s read as %d page(s) carrying NO text — a scanned "
                "document has no text layer, and this is that fact, not an "
                "empty document", p.name, len(pages))
        return content

    #: Which senses take something from each kind of thing, all at once.
    SENSES: Dict[str, tuple] = {"image": ("sight",), "video": ("sight", "hearing"),
                                "audio": ("hearing",), "document": ("reading",)}

    @staticmethod
    def modality_of(path: str) -> Optional[str]:
        """What kind of thing a file is -- "image", "video", "audio" or
        "document" -- judged the way `sense` dispatches, or None when no sense
        can take anything from it. Its name decides where it names a kind a
        sense opens; where it does not, its own bytes decide: a file of written
        words is read whatever it is called. Lets a door say what it takes in
        before opening a file."""
        suffix = Path(path).suffix.lower()
        if suffix in reading.DOCUMENT_READERS:
            return "document"
        if suffix in _VIDEO_EXT:
            return "video"
        if suffix in _AUDIO_EXT:
            return "audio"
        if suffix in _IMAGE_EXT:
            return "image"
        from core.memory.media_store import mime_of
        try:
            with open(path, "rb") as f:
                mime = mime_of(f.read(96))
        except OSError:
            return None
        said = mime.split("/", 1)[0] if mime else None
        if said in ("image", "audio", "video"):
            return said
        return "document" if reading.kind_of(path) is not None else None

    @classmethod
    def senses_of(cls, path: str) -> tuple:
        """Every sense that takes something from this file, all at once -- empty
        when none can."""
        return cls.SENSES.get(cls.modality_of(path) or "", ())

    async def _read_library(self) -> None:
        """Read the known-instance library once, before the first recognition."""
        if self._instances_loaded:
            return
        try:
            await self.load_instances()
        except Exception as error:
            # An unreadable library is reported, never silently treated as
            # empty: "I know nothing" and "I could not read what I know" are
            # different states and only one of them is honest here.
            logger.error("perception: could not read the known-instance library: "
                         "%s — this perception is BLIND to instances and sounds it "
                         "has been taught", error)

    async def sense(self, path: str, *, source: Optional[str] = None,
                    lesson: Optional[Dict[str, Any]] = None) -> Optional[tuple]:
        """Take in one real image, video, sound or document by every sense that
        can: the structure that is really in the file, as ``(modality,
        content)`` -- "image"/"video"/"audio"/"document" plus the perceived
        structure (regions, colours, shapes, codes, sounds, pages of text,
        instance matches), and `content["senses"]`, the senses that took part.

        A VIDEO IS SEEN AND HEARD AT ONCE. Its sound track goes through the same
        ear as a sound file, so what was heard in a clip is stated on the clip's
        percept beside what was seen in it. A document is read, in reading's
        own process, while the other senses take in whatever else they are
        given.

        `sense` ONLY senses; it admits nothing. `admit_percept` takes in what was
        sensed, so a percept is admitted exactly once, by one owner. Returns
        None only when there is nothing to sense.
        Raises when the file cannot be read as media -- an honest failure, distinct
        from a readable file with little structure.

        `lesson` says what a recording is an example OF -- `{"word": "three"}`,
        `{"person": "Ada"}`, `{"song": "Greensleeves"}` -- when it is heard to
        be taught. It is heard like any other recording; what is kept of it for
        matching rides in its trace (`hold_lesson` takes it in once
        remembered). A lesson that cannot be taught is refused here, before
        anything is remembered."""
        p = Path(path)
        label = source or p.stem
        modality = self.modality_of(str(p))
        taught = self.lesson_of(lesson)
        needs = "image" if taught is not None and taught[0] == "thing" else "audio"
        if taught is not None and modality != needs:
            raise ValueError(f"a lesson about {'what is seen is taught by a picture' if needs == 'image' else 'what is heard is taught by a recording'}; "
                             f"{p.name} is {modality or 'no kind of file the substrate reads'}")
        if modality == "document":
            return "document", self._document_content(
                await self._reading.run(senses.read, str(p)), p, label)
        if modality is None:
            raise ValueError(
                f"nothing in {p.name} can be seen, heard or read: the substrate has "
                f"no sense for this kind of file, and will not guess at its contents")
        # Known-instance recognition rides on the same observation.
        await self._read_library()
        if modality == "audio":
            heard = await self._hearing.run(senses.listen, str(p), self._hearing_library(), taught)
            # Named from the CONTENT, not from the caller -- see `_percept_subject`.
            content = self._audio_content(
                heard, _percept_subject(label, heard["desc"].get("sha256")), taught)
            content["senses"] = ["hearing"]
            return "audio", content
        if modality == "video":
            # A clip is seen and heard AT ONCE, each sense in its own process.
            seen, track = await asyncio.gather(
                self._sight.run(senses.watch, str(p)),
                self._hearing.run(senses.listen, str(p), self._hearing_library(), None, True),
                return_exceptions=True)
            if isinstance(seen, BaseException):
                raise seen
            subject = _percept_subject(label, seen.get("sha256"))
            content = self._video_content(seen, subject)
            self._add_soundtrack(track, str(p), content, subject)
            content["senses"] = ["sight", "hearing"]
            return "video", content

        looked = await self._sight.run(senses.look, str(p), dict(self._instances))
        subject = _percept_subject(label, looked["desc"].get("sha256"))
        content = self._image_content(looked["desc"], subject)
        # What memory keeps of the seeing to know it again: its sight trace.
        content["trace"] = _encode(looked["trace"])
        if taught is not None:
            # A THING SHOWN, told what it is: known again by its keypoints, so a
            # picture with too few can never be known again, and is refused.
            shown = vision.sight_trace(looked["trace"])
            if shown is None or len(shown["descriptors"]) < 2 * self.THING_MIN_KEYPOINTS:
                raise ValueError(f"{p.name} has {0 if shown is None else len(shown['descriptors'])} "
                                 f"keypoint(s); a thing is known again by at least "
                                 f"{2 * self.THING_MIN_KEYPOINTS}")
            content["lesson"] = {taught[0]: taught[1]}
            content["caption"] = f'{content.get("caption", "")}; taught: what "{taught[1]}" looks like'
        if looked["known"]:
            content.setdefault("detections", [])
            content["detections"].extend(
                {"label": _term(name), "confidence": round(score, 2)}
                for name, score in looked["known"])
        content["senses"] = ["sight"]
        return "image", content

    def _hearing_library(self) -> Dict[str, Any]:
        """What hearing matches against, as this faculty holds it, for the
        hearing process: words, voices and songs taught (and the songs' tunes),
        and known sounds."""
        return {"words": self._words, "voices": self._voices, "reach": self._voice_reach,
                "songs": self._songs, "tunes": self._tunes,
                "sounds": {name: marks for name, (marks, _table) in self._sounds.items()}}

    async def describe_picture(self, path: str) -> Dict[str, Any]:
        """Sight's measurement of one picture, in sight's own process, with
        nothing matched and nothing admitted."""
        return await self._sight.run(senses.describe_picture, str(path))

    async def agreements(self, sense: str, met: Any, kept: List[bytes]) -> List[Any]:
        """How traces kept in memory agree with what is met now, measured in
        that sense's own process, never in the substrate's loop: for "sound"
        (landmark rows) `senses.sound_agreements`, for "sight" (sight
        features) `senses.sight_agreements`, for "text" (runs of words)
        `senses.text_agreements`."""
        if sense == "sound":
            return await self._hearing.run(senses.sound_agreements, met, list(kept))
        if sense == "text":
            return await self._reading.run(senses.text_agreements, list(met), list(kept))
        return await self._sight.run(senses.sight_agreements, met, list(kept))

    async def sight_trace(self, path: str) -> bytes:
        """A picture's sight trace, measured in sight's process."""
        return await self._sight.run(senses.sight_trace_of, str(path))

    async def rebuild_sound(self, trace: bytes):
        """A remembered sound heard again in the mind, in hearing's process."""
        return await self._hearing.run(senses.rebuild_sound, trace)

    async def rebuild_picture(self, perceived: Dict[str, Any]):
        """A remembered picture seen again in the mind, in sight's process."""
        return await self._sight.run(senses.rebuild_picture, perceived)

    def close(self) -> None:
        """Stop the senses' processes."""
        self._sight.close()
        self._hearing.close()
        self._reading.close()

    # -- known-instance library (recognition by matching, no model) ---------

    async def learn_instance(self, name: str, image_path: str) -> int:
        """Register a reference image -- or a reference SOUND -- as a known
        instance, durably. Returns the number of keypoints (for an image) or
        landmark hashes (for a sound) stored; 0 means the reference was too
        featureless to match on, reported rather than silently accepted.

        Which it is, the FILE decides, the way `sense` decides how to read it.

        Persisted on the spot: what the substrate has been taught to recognise
        has to still be true after a restart, and a library held only in memory
        made every teaching good until the next process."""
        if self.modality_of(str(image_path)) == "audio":
            return await self._learn_sound(name, str(image_path))
        des = await self._sight.run(senses.picture_descriptors, str(image_path))
        if des is None or len(des) == 0:
            logger.warning("reference %s has no matchable features", name)
            return 0
        from core.agents.memory_agent import memory_agent
        await _instance_library()
        await memory_agent().hold_vision_instance(
            name=_term(name), descriptors=des.tobytes(), rows=int(des.shape[0]),
            cols=int(des.shape[1]), dtype=str(des.dtype))
        self._instances[_term(name)] = des
        return int(len(des))

    # -- speech taught by example (matching, no model) ----------------------

    #: What a lesson taught by hearing can be: which word was said, whose voice
    #: it was, or which song it is, with the memory tag that marks a hearing as
    #: that lesson and the memory agent's name for it.
    LESSONS = {"word": "SPOKEN_WORD_TAG", "person": "VOICE_TAG", "song": "SONG_TAG",
               "thing": "THING_TAG"}
    #: A thing shown is known again when this many of its keypoints agree on one
    #: geometry (`MemoryAgent.SIGHT_MIN_AGREE`); it must have twice as many.
    THING_MIN_KEYPOINTS = 20

    @classmethod
    def lesson_of(cls, lesson: Optional[Dict[str, Any]]) -> Optional[tuple]:
        """A lesson as (key, label): ("word", "three"), ("person", "Ada") or
        ("song", "Greensleeves"). None for no lesson; a ValueError for one that
        says nothing teachable."""
        if not lesson:
            return None
        keys = [k for k in cls.LESSONS if str(lesson.get(k) or "").strip()]
        if len(keys) != 1:
            raise ValueError("a lesson says which word was said (`word`), whose voice it was "
                             "(`person`), which song it is (`song`) or which thing is shown "
                             "(`thing`), one of them")
        key = keys[0]
        label = " ".join(str(lesson[key]).split())
        return key, (label.lower() if key == "word" else label)

    def hold_lesson(self, content: Dict[str, Any]) -> bool:
        """Take in a lesson the substrate has just REMEMBERED: the example kept
        in that hearing's memory joins the words or voices this faculty matches
        against. Called once the memory is kept, so this copy never holds a
        lesson memory does not. False when the content was no lesson."""
        lesson = self.lesson_of(content.get("lesson"))
        if lesson is None or not content.get("trace"):
            return False
        key, label = lesson
        if key == "thing":
            shown = vision.sight_trace(decode_trace(content["trace"]))
            if shown is None:
                return False
            self._instances[_term(label)] = shown["descriptors"]
            self._taught_version += 1
            return True
        example = speech.unpack(decode_trace(content["trace"]))
        if example is None:
            return False
        if key == "word":
            self._words.setdefault(label, []).append(example)
        elif key == "song":
            self._songs.setdefault(label, []).append(example.astype("int32"))
            kept = decode_trace(content["trace"])
            line = hearing.trace_tune(kept)
            if line is not None:
                self._tunes.setdefault(label, []).append(
                    {"line": line, "mix": hearing.trace_tune_from_mix(kept)})
        else:
            self._voices.setdefault(label, []).append(example)
            self._voice_reach = speech.voice_reach(self._voices)
        self._taught_version += 1
        return True

    async def _learn_sound(self, name: str, sound_path: str) -> int:
        """A reference sound's landmarks, kept so the sound is known when heard
        again. A reference with fewer than `hearing.KNOWN_MIN_LANDMARKS` can
        never reach the agreement a recognition needs, so it is refused as too
        featureless -- a short tick or a smooth hiss -- and 0 is returned."""
        marks = await self._hearing.run(senses.sound_landmarks, sound_path)
        distinct = hearing.distinct_landmarks(marks)
        if distinct < hearing.KNOWN_MIN_LANDMARKS:
            logger.warning(
                "reference sound %s has %d different landmark(s); at least %d are needed "
                "to recognise it heard again, so it is not kept", name, distinct,
                hearing.KNOWN_MIN_LANDMARKS)
            return 0
        from core.agents.memory_agent import memory_agent
        await _instance_library()
        await memory_agent().hold_sound_instance(
            name=_term(name), landmarks=marks.tobytes(), rows=int(marks.shape[0]),
            cols=int(marks.shape[1]), dtype=str(marks.dtype))
        self._sounds[_term(name)] = (marks, hearing.landmark_index(marks))
        return int(len(marks))

    @staticmethod
    def _sound_detections(known) -> List[Dict[str, Any]]:
        """Which known sounds were heard, and where, from the landmark agreement
        the hearing process counted (`senses.listen`).

        THE MATCH STATES ITS OWN STANDING. A count of agreeing hashes is how far
        past the cut the recognition sits, not how likely it is to be right, so
        it is mapped the way every other perceptual resolution is: exactly at
        the cut it is a coin flip between "that sound" and "not that sound", and
        fully resolved at twice the cut."""
        if not known:
            return []
        from core.domain.evidence_producers import quality_from_resolution
        out: List[Dict[str, Any]] = []
        for name, count, at in known:
            resolution = min(1.0, count / hearing.KNOWN_MIN_AGREE - 1.0)
            out.append({"label": _term(name), "at": at, "agreeing": count,
                        "confidence": round(quality_from_resolution(resolution), 3)})
        return sorted(out, key=lambda d: -d["agreeing"])

    # -- describe -> ingress content ---------------------------------------

    @staticmethod
    def _blob_token(region: Dict[str, Any], taken: Dict[str, int]) -> str:
        """What to call this blob WITHIN its percept, from what it looks like.

        IT USED TO BE `blob{n}`, WHERE n WAS THE AREA RANK, and an ordinal cannot
        carry identity. Measured across transforms of the same scenes: an area
        rank keeps pointing at the same object 100% of the time while the set of
        objects is unchanged, and **0%** of the time once a single new object
        enters the frame — a 10% occluder at area 0.097 out-ranks a circle at
        0.065, so `blob1` is the circle when clean and the OCCLUDER when
        occluded. Perfect until the set changes, then wrong, which is exactly why
        it survived this long. Appearance scores 95% and **90%**, and across
        every percept measured it never once gave two different objects the same
        key.

        THE HUE IS STRIPPED OF ITS MODIFIER on purpose: `vivid_red` and `red` are
        the same hue seen under different light, and the token should follow the
        object rather than the bulb. The full colour is still stated in `isa`,
        where it belongs as a claim -- this is a name, not a reading.

        RELATIONS ARE DELIBERATELY NOT IN IT, though they are the most stable
        thing this faculty produces. Measured: adding them takes cross-sighting
        identity from 90% to **0%** once an object enters the frame, because a
        new object changes every relational count. What is stable about a
        RELATION is not stable about a COUNT of relations.

        The name is still percept-local -- the subject in front of it carries the
        image's content digest -- so two pictures that both contain a red circle
        never become one individual. What changes is that within a scene the same
        object keeps its name when something else appears beside it."""
        colour = str(region.get("hue") or region.get("color") or "")
        base = _term(f"{colour}{region.get('shape') or ''}") or "blob"
        # Two things that look alike in one picture still have to be told apart,
        # and the index is the ONLY place an ordinal survives -- as a
        # disambiguator among identical-looking things, never as identity.
        taken[base] = taken.get(base, 0) + 1
        return base if taken[base] == 1 else f"{base}{taken[base]}"

    def _blobs(self, regions, subject: str) -> List[Dict[str, Any]]:
        """Each object-like region as an individual with its own features.

        The faculty measures a blob's colour and shape class off the pixels; this
        states them of the blob itself, so what reaches the substrate is a thing
        that IS round and IS red, which a rule can bind to and a name can be
        learned for. The whole-frame region is the background, not a thing, and
        is left out.

        THE SIZE BAND IS NOT ONE OF THESE FEATURES, and was. `isa` is category
        membership -- it is what a rule binds to and what recognition generalises
        over -- so putting `medium` in it says being medium-sized is part of what
        the thing IS. It is not; it is a fact about where the camera stood.
        Measured: the band survived 0% of zooms in either direction across 1512
        live sightings, and unlike colour it cannot be rescued by saying how sure
        we are, because a perfectly certain reading of the wrong KIND of property
        is still the wrong property (its discrimination came out at AUC 0.519,
        which is a coin flip).

        The exact measurement is not lost -- it was never in the band. It stays
        as `occupies`, a property of this blob in this view, which is what an
        area fraction honestly is. And what the band was reaching for, comparative
        size, is now stated where it is true: `larger_than` between blobs,
        measured to survive 48 of 48 geometric transforms."""
        out: List[Dict[str, Any]] = []
        taken: Dict[str, int] = {}
        for r in _object_regions(regions):
            # THE HUE, NOT THE HUE PLUS HOW IT LOOKED. `vivid_red` welds a
            # property of the object to a property of the light, which is the
            # same fusion that put a size band in `isa` and it failed the same
            # way: measured, 41% of every colour change under the nuisance
            # battery was the MODIFIER moving while the hue underneath held, and
            # on photographs the hue survives 71% where the full name survives
            # 64%. The modifier is still stated -- below, beside the other facts
            # about the view -- and the full name is still on the region.
            features = [_term(v) for v in (r.get("hue") or r.get("color"),
                                           r.get("shape")) if v]
            # WHICH of these features is inferred, and how well it is borne out.
            # Keyed BY FEATURE rather than by position: `isa` is a flat list and
            # a consumer that located the shape by index would silently qualify
            # the colour the moment a feature is missing or reordered.
            #
            # BOTH OF THESE CARRY ONE NOW. Only the shape used to, on the
            # reasoning that a colour is read off the pixels so it is a
            # "measurement plus a stated threshold — true by construction, not
            # probable". That reasoning was about the PHOTOGRAPH. What gets
            # stated here is about the OBJECT: `blob1 isa vivid_red` is a claim
            # about a thing, and a thing under a dimmer bulb is still the same
            # thing. Measured across 1512 live sightings — colour survived 0% of
            # a 0.55x illuminant while the substrate acted on it 100% of the
            # time, because every feature arrived at one fixed quality with
            # nothing anywhere saying how good the look had been.
            isa_support: Dict[str, float] = {}
            for key, support in (("shape", r.get("shape_support")),
                                 ("color", r.get("color_support"))):
                if r.get(key) and support is not None:
                    isa_support[_term(r[key])] = float(support)
            # NAMED FOR WHAT IT LOOKS LIKE, not for where it came in the area
            # ordering -- see `_blob_token` for the measurement that decided it.
            out.append({
                "name": _term(f"{subject}_{self._blob_token(r, taken)}"),
                "isa": features,
                "properties": {
                    "occupies": r.get("area_fraction"),
                    "sits": _term(r.get("position") or ""),
                    # HOW IT LOOKED, stated rather than fused into what it is.
                    # `looked` is the modifier that used to ride on the front of
                    # the colour name; `lit_as` is the name the raw pixels gave
                    # before the light was discounted, so the correction never
                    # destroys the measurement it was applied to.
                    **({"looked": _term(r["view_modifier"])}
                       if r.get("view_modifier") else {}),
                    **({"lit_as": _term(r["color_as_lit"])}
                       if r.get("color_as_lit")
                       and r.get("color_as_lit") != r.get("color") else {}),
                },
                # HOW WELL THE CONTOUR BEARS OUT ITS SHAPE, carried so the claim
                # arrives with its evidence rather than as a bare label.
                #
                # These features are not equally certain and were travelling as
                # though they were. `occupies` and the colour are read off the
                # pixels; the SHAPE comes from a lossy polygon approximation, and
                # `circularity` says how well it actually fits. None where the
                # shape was decided by a vertex count — no scalar support exists
                # there, which is different from weak support and must not be
                # rendered as a low number.
                "shape_support": r.get("shape_support"),
                #: Per-feature support for the `isa` claims, where one exists.
                #: Absent from a feature means measured-and-exact, never unknown.
                "isa_support": isa_support,
                #: The same, for the PROPERTIES. `sits` was the last reading the
                #: faculty made that went out with no standing attached, because
                #: it travels as a property rather than as an `isa` and so never
                #: passed through the per-feature channel.
                "property_support": (
                    {"sits": float(r["position_support"])}
                    if r.get("position_support") is not None else {}),
            })
        return out

    @staticmethod
    def correspond(before: Dict[str, Any], after: Dict[str, Any]
                   ) -> List[Dict[str, Any]]:
        """Which blob in `after` is the same thing as which blob in `before`.

        A NAME CANNOT DO THIS ON ITS OWN, and that is why this exists. Blob names
        are built from appearance, which carries identity across a sighting 95%
        of the time and, crucially, 90% of the time when a new object enters the
        frame where an area rank manages 0%. But appearance is exactly what a
        dimmer bulb moves: matching on the name alone would report the object
        GONE the moment its colour name shifted, which is the opposite of the
        truth and would hide the very instability worth measuring.

        So the signals are tried in order of how much they survive, each stated
        on the result so a reader can see what the match rests on:

          `name`    -- the same appearance token. Strongest, and it is the whole
                       token, so shape and hue both held. Measured 324/324.
          `shape`   -- shape survived rotation, perspective, blur and noise at
                       88-100%; it is the sturdiest single feature measured, and
                       it is what remains when the light changes. 20/20.
          `extent`  -- how much of the frame it takes up, used only to choose
                       between candidates the above left tied, never to match on.

        HUE ALONE WAS TRIED AS A THIRD SIGNAL AND REMOVED. It bought 13 further
        matches at 77% correct, and every error this function made came from it.
        A wrong correspondence is a false positive that quietly corrupts whatever
        is built on it, while an unmatched blob is an honest absence that says so
        -- so the trade is not worth making, and dropping it takes this from
        99% to 100% at the cost of matching 21 fewer blobs out of 352.

        Deliberately NOT relational, though relations are the most stable thing
        this faculty produces. Measured: adding relational counts drops
        cross-sighting identity from 90% to 0% once an object enters the frame,
        because a new object changes every count. What is stable about a RELATION
        is not stable about a COUNT of them.

        Returns one entry per matched pair, `{"before", "after", "on"}`, and says
        nothing about blobs it could not match -- an unmatched blob is an honest
        absence, not a failure to be papered over."""
        def parts(blob):
            # `isa` already carries the bare hue -- the viewing modifier is
            # stated separately as a fact about the light -- so there is nothing
            # left to strip here.
            isa = blob.get("isa") or []
            return {
                "name": blob["name"].rsplit("_", 1)[-1],
                "hue": str(isa[0]) if isa else "",
                "shape": str(isa[1]) if len(isa) > 1 else "",
                "extent": float(blob.get("properties", {}).get("occupies") or 0.0),
            }

        olds = [(b, parts(b)) for b in (before.get("blobs") or [])]
        news = [(b, parts(b)) for b in (after.get("blobs") or [])]
        out: List[Dict[str, Any]] = []
        spoken: set = set()
        for signal in ("name", "shape"):
            for ob, op in olds:
                if ob["name"] in {m["before"] for m in out}:
                    continue
                pool = [(nb, np_) for nb, np_ in news
                        if nb["name"] not in spoken and op[signal]
                        and np_[signal] == op[signal]]
                if not pool:
                    continue
                # Several things can look alike; the one whose share of the frame
                # is nearest settles it, which is a tiebreak and never a match on
                # its own -- extent is the property D3 removed from `isa` for
                # being about the framing.
                nb, _np = min(pool, key=lambda t: abs(t[1]["extent"] - op["extent"]))
                spoken.add(nb["name"])
                out.append({"before": ob["name"], "after": nb["name"],
                            "on": signal})
        return out

    def _blob_relations(self, regions, blobs) -> List[Dict[str, str]]:
        """How the things in this frame stand to ONE ANOTHER, by name.

        This is the half of sight that was being computed and thrown away.
        `vision.relations` has always produced left_of / above / larger_than, and
        `describe_image` has always reported them, and NOTHING has ever read
        them -- so the only frame-invariant structure the describer knows how to
        produce never reached the substrate, while the frame-relative size band
        did, stated as if it were a property of the object.

        Measured over geometric transforms of two-object scenes: `larger_than`
        survived 48/48 and invented nothing; `left_of` 94%; `above` 88%. Against
        73% for the size band and 52% for the position word it replaces.

        Relations are computed over the SAME object list the blobs were numbered
        from, so index i is always blob i+1 and the two cannot drift apart."""
        objects = _object_regions(regions)
        out: List[Dict[str, str]] = []
        for rel in vision.relations(objects, top=len(objects)):
            a, b = int(rel["a"]), int(rel["b"])
            if a >= len(blobs) or b >= len(blobs) or a == b:
                continue
            out.append({"subject": blobs[a]["name"],
                        "relation": str(rel["rel"]),
                        "object": blobs[b]["name"],
                        "support": rel.get("support")})
        return out

    def _image_content(self, desc: Dict[str, Any], subject: str) -> Dict[str, Any]:
        # Each real blob is admitted as its OWN individual carrying its own
        # measured features, not flattened into one "<colour>_<shape>" label
        # hung on the image. A flattened label cannot be reasoned about: a rule
        # about a circle that is red has nothing to bind to, because no circle
        # exists in what was admitted. A blob does.
        blobs = self._blobs(desc.get("regions", []), subject)
        # Decoded codes and matched instances are RECOGNITIONS, which is a
        # different thing from a perceived blob, and stay detections.
        detections: List[Dict[str, Any]] = []
        for code in desc.get("codes", []):
            detections.append({"label": _term(code)[:120]})

        props: Dict[str, Any] = {
            "has_format": desc["format"],
            "has_width": desc["width"],
            "has_height": desc["height"],
            "has_orientation": desc.get("orientation", "landscape"),
            "focus": "sharp" if desc.get("sharp") else "blurry",
            # HOW GOOD THE LOOK WAS, said out loud. The per-feature supports
            # carry this into the evidence quality of each claim; this states it
            # of the observation itself, so a reader can see why a percept's
            # claims are standing where they are, and a rule can be learned about
            # the conditions rather than only about the contents.
            "view_is": desc.get("view_category", "clear"),
            "brightness_is": desc.get("brightness_category", "normal"),
            "palette_is": desc.get("colorfulness_category", "muted"),
            "temperature_is": desc.get("palette_temperature", "neutral"),
        }
        if desc.get("dominant_colors"):
            props["dominant_color"] = desc["dominant_colors"][0]["name"]
        if desc.get("camera"):
            props["taken_with"] = desc["camera"]

        content: Dict[str, Any] = {
            "subject": subject,
            "blobs": blobs,
            #: How the blobs stand to one another. The frame-INVARIANT half of
            #: what was measured, and until now the discarded half.
            "blob_relations": self._blob_relations(desc.get("regions", []), blobs),
            "detections": detections,
            "properties": props,
            "sha256": desc.get("sha256"),
            "caption": (f"{desc['width']}x{desc['height']} {desc['format']} image, "
                        f"{desc.get('region_count', 0)} region(s)"),
            #: What is kept of the picture to see it again in the mind
            #: (`vision.rebuild`): the scene small, the things in it in detail.
            "gist": desc.get("gist"),
        }
        if desc.get("captured"):
            content["captured"] = desc["captured"]
        return content

    def _video_content(self, desc: Dict[str, Any], subject: str) -> Dict[str, Any]:
        events: List[Dict[str, Any]] = []
        if desc.get("has_motion"):
            events.append({"label": "motion"})
        if desc.get("scene_changes", 0) > 0:
            events.append({"label": "scene_change"})

        key_regions = (desc.get("keyframe", {}) or {}).get("regions", [])
        blobs = self._blobs(key_regions, subject)
        detections: List[Dict[str, Any]] = []

        props: Dict[str, Any] = {}
        for key, rel in (("codec", "has_codec"), ("width", "has_width"),
                         ("height", "has_height"), ("fps", "has_fps"),
                         ("frames", "has_frames")):
            if desc.get(key) is not None:
                props[rel] = desc[key]

        content: Dict[str, Any] = {
            "subject": subject,
            "blobs": blobs,
            "blob_relations": self._blob_relations(key_regions, blobs),
            "detections": detections,
            "events": events,
            "properties": props,
            "sha256": desc.get("sha256"),
            "caption": f"{desc.get('duration', '?')}s {desc.get('codec', '')} video",
        }
        if desc.get("duration") is not None:
            content["duration"] = desc["duration"]
        return content

    # -- hearing -> ingress content -----------------------------------------

    @staticmethod
    def _sound_token(sound: Dict[str, Any], taken: Dict[str, int]) -> str:
        """What to call this sound WITHIN its percept, from what it is like: its
        register and how it starts (`midabrupt`, `lowgradual`,
        `unpitchedabrupt`), as a blob is called by its hue and shape.

        NOT from when it came. An ordinal carries no identity: the first sound
        of a recording is a different sound the moment anything is heard before
        it. The index survives only to tell look-alikes apart. The token is one
        word, so a sound's name stays within the words the store gives a name."""
        register = str(sound.get("register") or "").replace("_pitched", "")
        base = _term(f"{register or 'unpitched'}{sound.get('onset') or ''}")
        taken[base] = taken.get(base, 0) + 1
        return base if taken[base] == 1 else f"{base}{taken[base]}"

    def _sound_individuals(self, sounds, subject: str,
                           voices: Optional[List[Optional[Dict[str, Any]]]] = None
                           ) -> List[Dict[str, Any]]:
        """Each sound as an individual with its own features, on the contract a
        blob uses.

        `isa` carries only what belongs to the SOUND and survived the nuisances
        it was measured under: whether it is pitched, its register, how it
        starts. How loud it came out and when it began are facts about THIS
        RECORDING -- turn it up, or pad it with silence, and they change while
        the sound does not -- so they are stated as properties, the way a blob's
        `occupies` and `sits` are, and never as what the sound is."""
        out: List[Dict[str, Any]] = []
        taken: Dict[str, int] = {}
        for k, s in enumerate(sounds or []):
            features = [f for f in (s.get("tonality"), s.get("register"), s.get("onset")) if f]
            support = dict(s.get("support") or {})
            # A SOUND HEARD AS A VOICE is one by matching the voices taught
            # (`speech.judge_voice`), with the support that judgement earned.
            judged = voices[k] if voices and k < len(voices) else None
            if judged is not None and judged["voice"]:
                features.append("voice")
                support["voice"] = judged["support"]
            props: Dict[str, Any] = {
                "starts_at": s.get("start"),
                "lasts": s.get("duration"),
                "level": s.get("level"),
            }
            if s.get("pitch"):
                props["pitch_hz"] = s["pitch"]
            out.append({
                "name": _term(f"{subject}_{self._sound_token(s, taken)}"),
                "isa": [_term(f) for f in features],
                "properties": props,
                "isa_support": {_term(f): float(support[f]) for f in features if f in support},
                "property_support": {},
            })
        return out

    @staticmethod
    def _sound_phrase(sound: Dict[str, Any]) -> str:
        """One sound in the words its measurement earned -- "a gradual
        mid-pitched sound" -- for the recallable account a memory is found by."""
        register = str(sound.get("register") or "").replace("_", "-") or "unpitched"
        words = " ".join(w for w in (sound.get("onset"), register, "sound") if w)
        return f"{'an' if words[0] in 'aeiou' else 'a'} {words}"

    @staticmethod
    def _sound_relations(desc_relations, individuals) -> List[Dict[str, Any]]:
        """How the sounds stand to one another, by name, over the same list the
        individuals were built from, so index i is always sound i."""
        out: List[Dict[str, Any]] = []
        for rel in desc_relations or []:
            a, b = int(rel["a"]), int(rel["b"])
            if a >= len(individuals) or b >= len(individuals) or a == b:
                continue
            out.append({"subject": individuals[a]["name"], "relation": str(rel["rel"]),
                        "object": individuals[b]["name"], "support": rel.get("support")})
        return out

    @staticmethod
    def _heard_properties(desc: Dict[str, Any]) -> Dict[str, Any]:
        """What is true of the recording as a whole: how good the hearing was
        and what it rests on between sounds, and -- when the listen was bounded
        -- how much of it was heard."""
        props: Dict[str, Any] = {
            "hearing_is": desc.get("hearing_category") or "no_soundtrack",
        }
        if desc.get("background"):
            props["background_is"] = desc["background"]
        heard, lasts = desc.get("heard_seconds"), desc.get("duration")
        if heard is not None and lasts is not None and heard + 0.05 < lasts:
            props["heard_for"] = heard
        return props

    @staticmethod
    def _speech_caption(heard: Dict[str, Any]) -> str:
        """What was said and by whom, for the recallable account a memory is
        found by: the words are what a person would remember of it."""
        parts = []
        if heard.get("heard_text"):
            parts.append(f'said "{heard["heard_text"]}"')
        if heard.get("spoken_by"):
            parts.append(f"in {heard['spoken_by']['person']}'s voice")
        elif heard.get("whose_judged"):
            parts.append("in a voice not clearly any taught")
        elif any(v and v["voice"] for v in heard.get("voices") or []):
            parts.append("in a voice")
        return ("; " + ", ".join(parts)) if parts else ""

    @staticmethod
    def _speech_content(heard: Dict[str, Any]) -> Dict[str, Any]:
        """The speech heard, under the percept's own keys."""
        return {k: heard[k] for k in ("said", "heard_text", "spoken_by") if heard.get(k)}

    @staticmethod
    def _music_content(heard: Dict[str, Any]) -> Dict[str, Any]:
        """The music heard, under the percept's own keys: what music claimed of
        the recording (`in_key`, `tempo`, `melody`), the songs taught that it
        plays (`plays`), and the song whose tune a single line of it carries
        (`has_tune_of`), each with the support its matching earned."""
        claims = (heard.get("music") or {}).get("claims") or {}
        out = {k: claims[k] for k in ("in_key", "tempo", "melody") if claims.get(k)}
        playing = [{"song": title, "agreeing": count, "at": at, "share": share,
                    "support": music.resolve_song(share)}
                   for title, count, at, share in heard.get("songs") or []]
        if playing:
            out["plays"] = playing
        tuned = [{"song": t["song"], "ratio": t["ratio"], "support": t["support"]}
                 for t in heard.get("tunes") or []]
        if tuned:
            out["has_tune_of"] = tuned
        return out

    @staticmethod
    def _music_caption(found: Dict[str, Any]) -> str:
        """The music in words, for the recallable account a memory is found by:
        the song, the key, the pace, and how the melody goes."""
        parts = []
        if found.get("plays"):
            parts.append(f'playing "{found["plays"][0]["song"]}"')
        elif found.get("has_tune_of"):
            parts.append(f'the tune of "{found["has_tune_of"][0]["song"]}"')
        if found.get("in_key"):
            parts.append(f"in {found['in_key']['key']}")
        if found.get("tempo"):
            parts.append(f"about {round(found['tempo']['bpm'])} beats a minute")
        if found.get("melody"):
            notes = found["melody"]["notes"]
            low = min(notes, key=lambda n: n["midi"])["name"]
            high = max(notes, key=lambda n: n["midi"])["name"]
            parts.append(f"a melody of {len(notes)} notes from {low} to {high}, going "
                         + " ".join(n["name"] for n in notes[:8]))
        return ("; " + ", ".join(parts)) if parts else ""

    def _audio_content(self, heard: Dict[str, Any], subject: str,
                       lesson: Optional[tuple] = None) -> Dict[str, Any]:
        """A recording, as the hearing process heard it (`senses.listen`), in
        the structure a percept is admitted from."""
        desc = heard["desc"]
        spoken = heard["speech"]
        individuals = self._sound_individuals(desc.get("sounds"), subject, spoken["voices"])
        props: Dict[str, Any] = {k: v for k, v in (
            ("has_format", desc.get("format")),
            ("has_codec", desc.get("codec")),
            ("lasts", desc.get("duration")),
            ("has_sample_rate", desc.get("sample_rate")),
            ("has_channels", desc.get("channels")),
        ) if v not in (None, "")}
        props.update(self._heard_properties(desc))
        detections = self._sound_detections(heard["known"])
        count = desc.get("sound_count") or 0
        caption = (f"{desc.get('duration', '?')}s {desc.get('format', '')} recording, "
                   f"{count} sound(s)")
        phrases = [self._sound_phrase(s) for s in (desc.get("sounds") or [])[:4]]
        if phrases:
            caption += ": " + ", ".join(phrases)
        if count > len(individuals):
            caption += f"; the {len(individuals)} most prominent kept"
        if "heard_for" in props:
            caption += f", first {props['heard_for']}s heard"
        caption += self._speech_caption(spoken)
        found = self._music_content(heard)
        caption += self._music_caption(found)
        if lesson is not None:
            key, label = lesson
            caption += {"word": f'; taught: how the word "{label}" sounds',
                        "person": f"; taught: how {label}'s voice sounds",
                        "song": f'; taught: the song "{label}"'}[key]
        return {
            **self._speech_content(spoken),
            **found,
            **({"lesson": {lesson[0]: lesson[1]}} if lesson is not None else {}),
            "subject": subject,
            "blobs": individuals,
            "blob_relations": self._sound_relations(desc.get("relations"), individuals),
            "detections": [{"label": d["label"], "confidence": d["confidence"]}
                           for d in detections],
            "properties": props,
            "sha256": desc.get("sha256"),
            "duration": desc.get("duration"),
            "caption": caption,
            #: What is kept of the hearing so it can be heard again in the mind
            #: (`hearing.rebuild`): each sound's shape over time, never the
            #: recording. Carried as text so the percept stays a JSON record.
            "trace": _encode(heard["trace"]) if heard.get("trace") else None,
        }

    def _add_soundtrack(self, track, path: str, content: Dict[str, Any], subject: str) -> None:
        """Add what was HEARD in a video (`track`, from the hearing process) to
        what was seen in it.

        The sounds join the keyframe's blobs as individuals of the same percept,
        their relations join the blobs' relations, and the clip states how good
        its hearing was. A clip with no sound track says so (`hearing_is
        no_soundtrack`), which is a fact about the clip. A sound track that
        cannot be heard is logged and stated (`hearing_is unreadable`) -- never
        silently dropped, which would make an unheard clip look silent."""
        props = content.setdefault("properties", {})
        if isinstance(track, BaseException):
            logger.error("video %s: its sound track could not be heard: %s", path, track)
            props["hearing_is"] = "unreadable"
            return
        desc = track["desc"]
        if not desc.get("has_audio"):
            props["hearing_is"] = "no_soundtrack"
            content["caption"] = f"{content.get('caption', '')}, no sound track"
            return
        spoken = track["speech"]
        individuals = self._sound_individuals(desc.get("sounds"), subject, spoken["voices"])
        content.update(self._speech_content(spoken))
        found = self._music_content(track)
        content.update(found)
        content.setdefault("blobs", []).extend(individuals)
        content.setdefault("blob_relations", []).extend(
            self._sound_relations(desc.get("relations"), individuals))
        props.update(self._heard_properties(desc))
        if desc.get("codec"):
            props["has_sound_codec"] = desc["codec"]
        if track["known"]:
            content.setdefault("detections", []).extend(
                {"label": d["label"], "confidence": d["confidence"]}
                for d in self._sound_detections(track["known"]))
        content["caption"] = (f"{content.get('caption', '')}, "
                              f"{desc.get('sound_count') or 0} sound(s) heard"
                              f"{self._speech_caption(spoken)}{self._music_caption(found)}")


# ══════════════════════════════════════════════════════════════════════════
# WHAT THE SUBSTRATE IS PERCEIVING RIGHT NOW — bound to the acting context
# ══════════════════════════════════════════════════════════════════════════
#
# The perceptual counterpart of `set_acting_intent`, and it exists for the same
# reason that one does: a memory forming while the substrate is perceiving has
# to be able to say WHICH percept it is of, by reference.
#
# WHAT THIS REPLACES. A memory already carried a `perceptual_state` snapshot,
# attached by RECENCY — a 120-second window over whatever had been perceived
# lately. That is a correlation: it says something was in view around then, and
# it degrades exactly where it matters most, when several things were seen close
# together. "I saw that employee send that email" then rests on the substrate's
# word plus a nearby timestamp, which is testimony, not a record.
#
# A reference is defensible where a recollection is not: the percept is the
# memory of perceiving, which holds what was sensed, and its digest identifies the
# very bytes.
#
# MODALITY-AGNOSTIC. `percept`, not `image` — hearing and voice arrive through
# the same door and bind here the same way.

import contextvars as _contextvars

_acting_percept: "_contextvars.ContextVar[Optional[Dict[str, Any]]]" = \
    _contextvars.ContextVar("lyric_acting_percept", default=None)


def set_acting_percept(percept_id: Optional[str],
                       digest: Optional[str] = None):
    """Bind the percept the current work is being done under. Returns the token.

    `digest` is the content identity of the thing perceived (an image's sha256),
    carried beside the id so the OBJECT stays identifiable even if the memory of
    perceiving it is later forgotten.
    """
    if not percept_id:
        return _acting_percept.set(None)
    return _acting_percept.set({"percept_id": str(percept_id),
                                "percept_digest": str(digest) if digest else None})


def get_acting_percept() -> Optional[Dict[str, Any]]:
    """The percept bound to the current async context, or None. None is honest:
    work that is not being done under a percept must not borrow one."""
    return _acting_percept.get()


def reset_acting_percept(token) -> None:
    try:
        _acting_percept.reset(token)
    except (ValueError, LookupError):
        # A token from another context is not this context's to reset; losing the
        # reset is harmless (the context ends), silently ignoring a real error is
        # not, so only these two are caught.
        pass


_faculty: Optional[PerceptionFaculty] = None


def get_perception_faculty() -> PerceptionFaculty:
    global _faculty
    if _faculty is None:
        _faculty = PerceptionFaculty()
    return _faculty
