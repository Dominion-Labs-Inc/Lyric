#!/usr/bin/env python3
"""The vision faculty: the one entry point for all sight.

The substrate does not have many ad-hoc ways to read text -- it has one reader,
and every path that consumes language goes through it. Sight is built the same
way. `VisionFaculty.sense(path)` is the sole route by which pixels become
STRUCTURE: it perceives structure with the classical describer (core.perception.
vision) and matches known instances. It does NOT admit evidence -- it is a sensor.
The one perception pipeline (PerceptionManager.process_input) admits what was
sensed, so a percept is admitted exactly once by one owner. Naming a novel
structure is NOT done here -- that is the substrate's to learn downstream. What
the faculty produces is honest structure; what it means is learned.

    from core.perception.vision_faculty import get_vision_faculty
    vf = get_vision_faculty()
    modality, content = await vf.sense("/path/to/photo.jpg")   # -> structure, not yet admitted
    vf.learn_instance("front_door", "ref.jpg")                 # register a known instance
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2

from . import vision

logger = logging.getLogger(__name__)

_VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
#: A local-descriptor match this strong recognises a specific known instance.
_INSTANCE_MIN_GOOD = 12
_INSTANCE_RATIO = 0.75


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


def _instance_library_path() -> Path:
    """Durable home for the known-instance library. Under the repo's data/ so it
    survives a restart like every other durable store."""
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "vision_instances.npz"


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

    ONE AUTHORITY, because two things depend on this list agreeing with itself: a
    blob's name is its position in it, and the relations between blobs are
    indices into it. Deciding "is this a thing" separately in each place is how
    `blob2 larger_than blob3` comes to mean a different pair than the names say."""
    out: List[Dict[str, Any]] = []
    for r in regions or []:
        if float(r.get("border_share") or 0.0) > _GROUND_BORDER:
            continue                      # this is the surround, not a thing
        if not (r.get("color") or r.get("shape")):
            continue
        out.append(r)
    return out


class VisionFaculty:
    """One faculty, the single entry point for all sight."""

    def __init__(self) -> None:
        # Reference instances: name -> ORB descriptors. This is recognition of
        # KNOWN things by matching, not classification of novel ones -- no model.
        self._instances: Dict[str, Any] = {}
        self._load_instances()

    # -- durability ---------------------------------------------------------
    #
    # A REFERENCE INSTANCE IS LEARNED STATE. It lived in this dict and died with
    # the process, so the substrate could be shown its own front door, recognise
    # it all afternoon, and not know it the next morning -- and nothing said so,
    # because an empty library is indistinguishable from a library that matched
    # nothing. Written through on learning rather than flushed at shutdown:
    # learning an instance is a rare deliberate act, the file is small, and a
    # shutdown-only flush loses everything on an unclean exit.

    def _load_instances(self) -> None:
        path = _instance_library_path()
        if not path.exists():
            return
        try:
            import numpy as np
            with np.load(str(path)) as data:
                self._instances = {str(k): data[k] for k in data.files}
            logger.info("👁️ restored %d known instance(s) from %s",
                        len(self._instances), path.name)
        except Exception as error:
            # An unreadable library is reported, never silently treated as empty:
            # "I know nothing" and "I could not read what I know" are different
            # states and only one of them is honest here.
            logger.error("vision: could not read the known-instance library at "
                         "%s: %s — the substrate is starting BLIND to instances "
                         "it has been taught", path, error)

    def _save_instances(self) -> None:
        path = _instance_library_path()
        try:
            import numpy as np
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(str(path), **self._instances)
        except Exception as error:
            raise RuntimeError(
                f"vision: learned the instance but could not persist the library "
                f"to {path}: {error}") from error

    @property
    def known_instances(self) -> List[str]:
        """The instances this faculty can recognise by name."""
        return sorted(self._instances)

    def forget_instance(self, name: str) -> bool:
        """Remove a reference instance. True if one was there."""
        gone = self._instances.pop(_term(name), None) is not None
        if gone:
            self._save_instances()
        return gone

    # -- the one entry point ------------------------------------------------

    async def sense(self, path: str, *, source: Optional[str] = None
                    ) -> Optional[tuple]:
        """Sense one real image or video: read the structure that is really in the
        file and return it as ``(modality, content)`` — "image"/"video" plus the
        perceived structure (regions, colours, shapes, codes, instance matches).

        This faculty ONLY senses. It does NOT admit evidence. The one perception
        pipeline (PerceptionManager.process_input) admits what is sensed, so a percept
        is admitted exactly once by one owner, instead of vision submitting through a
        second parallel path. Returns None only when there is nothing to sense.
        Raises when the file cannot be read as media -- an honest failure, distinct
        from a readable file with little structure."""
        p = Path(path)
        label = source or p.stem
        if p.suffix.lower() in _VIDEO_EXT:
            desc = vision.describe_video(str(p))
            return "video", self._video_content(
                desc, _percept_subject(label, desc.get("sha256")))

        desc = vision.describe_image(str(p))
        # Named from the CONTENT, not from the caller -- see `_percept_subject`.
        subject = _percept_subject(label, desc.get("sha256"))
        content = self._image_content(desc, subject)
        # Known-instance recognition rides on the same observation.
        matched = self._match_instances(str(p))
        if matched:
            content.setdefault("detections", [])
            content["detections"].extend(
                {"label": _term(name), "confidence": round(score, 2)}
                for name, score in matched)
        return "image", content

    # -- known-instance library (recognition by matching, no model) ---------

    def learn_instance(self, name: str, image_path: str) -> int:
        """Register a reference image as a known instance, durably. Returns the
        number of keypoints stored (0 means the reference was too featureless to
        match on, reported rather than silently accepted).

        Persisted on the spot: what the substrate has been taught to recognise
        has to still be true after a restart, and a library held only in memory
        made every teaching good until the next process."""
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"cannot read reference image {image_path}")
        orb = cv2.ORB_create(1500)
        _kp, des = orb.detectAndCompute(img, None)
        if des is None or len(des) == 0:
            logger.warning("reference %s has no matchable features", name)
            return 0
        self._instances[_term(name)] = des
        self._save_instances()
        return int(len(des))

    def _match_instances(self, path: str) -> List[tuple]:
        """Which registered instances this image contains, by descriptor match."""
        if not self._instances:
            return []
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return []
        orb = cv2.ORB_create(1500)
        _kp, des = orb.detectAndCompute(img, None)
        if des is None or len(des) < 2:
            return []
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        out: List[tuple] = []
        for name, ref in self._instances.items():
            try:
                pairs = matcher.knnMatch(des, ref, k=2)
            except cv2.error:
                continue
            good = sum(1 for pr in pairs if len(pr) == 2
                       and pr[0].distance < _INSTANCE_RATIO * pr[1].distance)
            if good >= _INSTANCE_MIN_GOOD:
                out.append((name, good / max(1, len(ref))))
        return sorted(out, key=lambda t: -t[1])

    # -- describe -> ingress content ---------------------------------------

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
        for r in _object_regions(regions):
            features = [_term(v) for v in (r.get("color"), r.get("shape")) if v]
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
            # Numbered over the things, not over the raw region list, so the
            # first thing in an image is always blob1 whether or not the frame
            # itself came back as a region.
            out.append({
                "name": _term(f"{subject}_blob{len(out) + 1}"),
                "isa": features,
                "properties": {
                    "occupies": r.get("area_fraction"),
                    "sits": _term(r.get("position") or ""),
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
            })
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


_faculty: Optional[VisionFaculty] = None


def get_vision_faculty() -> VisionFaculty:
    global _faculty
    if _faculty is None:
        _faculty = VisionFaculty()
    return _faculty
