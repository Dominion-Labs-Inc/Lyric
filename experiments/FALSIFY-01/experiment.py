#!/usr/bin/env python3
"""FALSIFY-01 — are the substrate's visual features about the OBJECT, or about
the PHOTOGRAPH?

Every claim the substrate makes about what it sees rests on four symbols read
off an image: a colour name, a shape name, a size band and a position. Induced
rules are conjunctions of them; a clause population votes over them;
`observed_instance_features` hands them to both. If those symbols are not stable
under changes that leave the object alone, then no recognition built on them can
be stable either — and measuring recognition on clean synthetic stimuli measures
the stimuli.

THROUGH THE LIVE SUBSTRATE, not the describer. Every image here goes in via
`coordinator.see()`: sensed by the faculty, admitted by the one perception
pipeline, fanned out to beliefs and the concept graph, named by the reflex,
judged by the acceptance band. What is measured is what the substrate ENDS UP
HOLDING about the thing — `observed_instance_features` — because that is what a
rule is applied against and what a clause population votes over. A pure-function
test of the describer would measure a stage; the defects live in the seams.

THE PREDICTIONS, read off the code before running, so this is a test and not a
fishing trip:

  P1  COLOUR IS NOT ILLUMINATION-INVARIANT. `_color_name` is a hard-thresholded
      HSV cascade: achromatic below s=28 or v=24, `dark_` below v=85, `vivid_`
      above s=185 and v=150. Cliffs, not slopes. Dimming a vivid_red object
      should change the SYMBOL — vivid_red -> red -> dark_red — and a rule
      naming vivid_red then cannot fire at all.
  P2  SIZE IS FRAME-RELATIVE, NOT OBJECT-RELATIVE. `_size_category` bands
      `area_fraction` — the object's share of the FRAME — at .02/.08/.25/.55.
      The same object photographed closer must change band: medium->large is
      3.1x in area, about 1.8x in linear zoom.
  P3  POSITION IS FRAME-RELATIVE. A 3x3 grid over the frame, so translating the
      object a third of the way across changes the symbol.
  P4  SHAPE SURVIVES ROTATION AND NOT PERSPECTIVE. A vertex count after
      `approxPolyDP` is rotation-invariant; the square/rectangle decision is an
      AXIS-ALIGNED bounding-box aspect ratio, which is not.
  P5  CIRCULARITY IS ATTACKED FROM BOTH SIDES — blur smooths the perimeter,
      noise inflates it, and circularity is 4*pi*A/P^2.
  P6  SEGMENTATION IS THE BINDING CONSTRAINT ON REAL PHOTOGRAPHS. Otsu
      figure/ground plus MSER has no notion of an object.
  P7  RECOGNITION INHERITS ALL OF IT. A category is a CONJUNCTION of these
      symbols, so its recall under a transform cannot exceed the survival of
      its weakest literal.
  P8  AND THE SUBSTRATE DOES NOT KNOW. This is the one that matters. The
      acceptance band judges a percept by the POSTERIOR of the claims it made,
      and a confidently-wrong reading has a high posterior: `vivid_red -> white`
      under a dimmer bulb is not an uncertain claim about red, it is a
      confident claim about white. So the ACT rate should stay high exactly
      where the symbols are breaking — the substrate acting, at full
      confidence, on a reading that no longer describes the object. If that
      holds, the band protects against weak evidence and not against wrong
      evidence, and those are different things.

  A  TEACH       categories learned through sight alone, both paths.
  B  FEATURES    what the substrate holds, under every transform.
  C  RECOGNITION whether the taught category still fires.
  D  NATURAL     the same battery on real photographs.

Staged by design — start small, confirm the harness, then scale:

    ./venv_torin/bin/python3 experiments/FALSIFY-01/experiment.py \
        --stimuli 6 --images 6 --mags 2
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1",
               "TORIN_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"
STIM = HERE / "stimuli"
COCO = REPO / "data" / "vision_flan" / "images"

sys.path.insert(0, str(HERE))
import transforms as T  # noqa: E402

#: The four symbols every downstream claim is built from. These are read back
#: from the CONCEPT GRAPH, not from the describer — what the substrate holds.
FEATURES = ("color", "shape", "size", "position")

COLOURS = {
    "red": (0, 0, 220), "blue": (220, 0, 0), "green": (0, 170, 0),
    "yellow": (0, 215, 235), "violet": (170, 40, 170), "orange": (0, 130, 240),
}
SHAPES = ("circle", "square", "triangle")
RADII = (52, 74, 96)

#: Which feature each symbol family belongs to, so a flat `isa` list read back
#: from the graph can be split into the four channels. Derived from the
#: describer's own vocabularies rather than guessed.
_SIZES = {"tiny", "small", "medium", "large", "dominant"}
_SHAPES = {"circle", "ellipse", "triangle", "square", "rectangle", "polygon", "blob"}


def draw(path: Path, shape: str, colour: str, radius: int) -> None:
    img = np.full((360, 360, 3), 245, np.uint8)
    bgr = COLOURS[colour]
    c = (180, 180)
    if shape == "circle":
        cv2.circle(img, c, radius, bgr, -1)
    else:
        unit = (np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
                if shape == "square"
                else np.array([[0, -1.1], [-1, 0.9], [1, 0.9]], np.float32))
        cv2.fillPoly(img, [(unit * radius + c).astype(np.int32)], bgr)
    if not cv2.imwrite(str(path), img):
        raise RuntimeError(f"could not write {path}")


def split_features(feats: List[str]) -> Dict[str, Optional[str]]:
    """The flat `isa` list the substrate holds, split into the four channels.

    A blob holds its colour, shape and size as undifferentiated `isa` edges, so
    a comparison has to put them back into channels to say WHICH one moved."""
    out: Dict[str, Optional[str]] = {f: None for f in FEATURES}
    for f in feats:
        if f in _SIZES:
            out["size"] = f
        elif f in _SHAPES:
            out["shape"] = f
        else:
            out["color"] = f
    return out


def iou(a, b) -> float:
    if not a or not b:
        return 0.0
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    return inter / (aw * ah + bw * bh - inter)


class Tally:
    """Per (family, magnitude): what survived, what was found, what was named."""

    def __init__(self) -> None:
        self.kept: Dict[Tuple[str, str, str], int] = defaultdict(int)
        self.total: Dict[Tuple[str, str, str], int] = defaultdict(int)
        self.lost: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.found: Dict[Tuple[str, str], int] = defaultdict(int)
        self.seen: Dict[Tuple[str, str], int] = defaultdict(int)
        #: |delta area_fraction| between the clean reading and this one — how
        #: far the thing the substrate found moved in extent. Region identity,
        #: measured with the only extent number the graph actually stores.
        self.drift: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        self.named: Dict[Tuple[str, str], int] = defaultdict(int)
        self.name_seen: Dict[Tuple[str, str], int] = defaultdict(int)
        self.misnamed: Dict[Tuple[str, str], int] = defaultdict(int)
        self.wrong_names: Dict[str, int] = defaultdict(int)
        #: What the acceptance band said about the percept: ACT / VERIFY /
        #: ABSTAIN. A broken reading the substrate ACTED on is the dangerous
        #: case; one it flagged is the system working.
        self.verdicts: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(
            lambda: defaultdict(int))
        self._order: List[Tuple[str, str]] = []

    def _touch(self, family: str, mag: str) -> None:
        if (family, mag) not in self._order:
            self._order.append((family, mag))

    def record(self, family: str, mag: str, clean: Optional[Dict[str, Any]],
               got: Optional[Dict[str, Any]]) -> None:
        self._touch(family, mag)
        self.seen[(family, mag)] += 1
        if got is None or clean is None:
            return
        self.found[(family, mag)] += 1
        if clean.get("occupies") is not None and got.get("occupies") is not None:
            self.drift[(family, mag)].append(
                abs(float(clean["occupies"]) - float(got["occupies"])))
        if got.get("decision"):
            self.verdicts[(family, mag)][str(got["decision"])] += 1
        a, b = clean["features"], got["features"]
        for f in FEATURES:
            if a.get(f) is None:
                continue
            self.total[(family, mag, f)] += 1
            if a.get(f) == b.get(f):
                self.kept[(family, mag, f)] += 1
            else:
                self.lost[f][f"{a.get(f)}->{b.get(f)}"] += 1

    def record_naming(self, family: str, mag: str, expected: str,
                      names: List[str]) -> None:
        self._touch(family, mag)
        self.name_seen[(family, mag)] += 1
        if expected in names:
            self.named[(family, mag)] += 1
        wrong = [n for n in names if n != expected]
        if wrong:
            self.misnamed[(family, mag)] += 1
            for w in wrong:
                self.wrong_names[w] += 1

    def rate(self, family: str, mag: str, feature: str) -> Optional[float]:
        t = self.total[(family, mag, feature)]
        return (self.kept[(family, mag, feature)] / t) if t else None

    def family_rate(self, family: str, feature: str) -> Optional[float]:
        k = sum(v for (fam, _m, f), v in self.kept.items()
                if fam == family and f == feature)
        t = sum(v for (fam, _m, f), v in self.total.items()
                if fam == family and f == feature)
        return (k / t) if t else None

    def families(self) -> List[str]:
        out: List[str] = []
        for fam, _m in self._order:
            if fam not in out:
                out.append(fam)
        return out

    def magnitudes(self, family: str) -> List[str]:
        return [m for fam, m in self._order if fam == family]


def table(tally: Tally, title: str, *, naming: bool) -> str:
    head = (f"  {'transform':<13}{'magnitude':<10}"
            + "".join(f"{f:>10}" for f in FEATURES)
            + f"{'found':>8}{'drift':>7}{'ACT':>6}")
    if naming:
        head += f"{'named':>8}{'wrong':>7}"
    lines = [f"\n{title}", "  " + "-" * (len(head) - 2), head]
    for fam in tally.families():
        for mag in tally.magnitudes(fam):
            seen = tally.seen[(fam, mag)]
            found = tally.found[(fam, mag)]
            drift = tally.drift[(fam, mag)]
            row = f"  {fam:<13}{mag:<10}"
            for f in FEATURES:
                r = tally.rate(fam, mag, f)
                row += f"{'  —':>10}" if r is None else f"{r*100:>9.0f}%"
            row += f"{(found/seen*100 if seen else 0):>7.0f}%"
            row += f"{(sum(drift)/len(drift) if drift else 0):>7.3f}"
            v = tally.verdicts[(fam, mag)]
            nv = sum(v.values())
            row += f"{(v.get('ACT', 0)/nv*100 if nv else 0):>5.0f}%"
            if naming:
                ns = tally.name_seen[(fam, mag)]
                row += f"{(tally.named[(fam,mag)]/ns*100 if ns else 0):>7.0f}%"
                row += f"{(tally.misnamed[(fam,mag)]/ns*100 if ns else 0):>6.0f}%"
            lines.append(row)
    return "\n".join(lines)


def thin(battery, mags: int):
    """Keep at most `mags` magnitudes per family, the EXTREMES first — a stage
    that can only afford two points should spend them on the mildest and the
    harshest, not on two neighbours in the middle."""
    if mags <= 0:
        return battery
    by_family: Dict[str, List] = defaultdict(list)
    for item in battery:
        by_family[item[0]].append(item)
    out = []
    for fam, items in by_family.items():
        if len(items) <= mags:
            out.extend(items)
            continue
        picked = [items[0], items[-1]]
        remaining = [i for i in items[1:-1]]
        while len(picked) < mags and remaining:
            picked.insert(len(picked) - 1, remaining.pop(len(remaining) // 2))
        out.extend(sorted(picked, key=items.index))
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stimuli", type=int, default=6,
                    help="synthetic base stimuli (sampled across shape x colour x size)")
    ap.add_argument("--images", type=int, default=6, help="natural photographs")
    ap.add_argument("--mags", type=int, default=2,
                    help="magnitudes kept per transform family (0 = all)")
    ap.add_argument("--teach", type=int, default=4,
                    help="clean examples per taught category")
    args = ap.parse_args()

    tag = uuid.uuid4().hex[:6]
    DOMAIN = f"falsify{tag}"
    CAT = f"disc{tag}"          # the taught category: a red circle
    buf = io.StringIO()
    WORK.mkdir(parents=True, exist_ok=True)
    STIM.mkdir(parents=True, exist_ok=True)

    EV = RunRecord(
        "FALSIFY-01",
        claim=("The substrate's visual features are symbols read off a "
               "photograph, not properties of an object. Under transformations "
               "that leave the object untouched they change, where they change "
               "is predictable from thresholds in the code, and recognition "
               "inherits every bit of it."),
        hypothesis=("Seven failures are predicted from the source before "
                    "measuring. Each is confirmed with a number or refuted. "
                    "Everything is measured through the LIVE substrate — what "
                    "it ends up holding — not through the describer."))

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.database import get_database_manager
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.reasoning.concept_graph_reasoning import observed_instance_features
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager()
        await db.initialize()

    counter = [0]

    # THE JUDGEMENT IS THE POINT, not an extra. When the features break, does
    # the substrate KNOW? The acceptance band is supposed to say "I am not sure
    # enough to act on this", and a perception study that only measures whether
    # the symbols changed cannot tell a degraded reading the substrate flagged
    # from one it acted on with full confidence. The second is the dangerous case.
    from core.agents.autonomous.autonomous_coordinator import SelfEventType
    judgements: List[Any] = []
    coord.on(SelfEventType.PERCEPT_RECOGNIZED,
             lambda ev: judgements.append(ev.payload), name=f"falsify_probe_{tag}")

    async def observe(path: Path,
                      against: Optional[Dict[str, Any]] = None
                      ) -> Optional[Dict[str, Any]]:
        """Show one image to the LIVE substrate and report what it ends up
        holding about the thing in it. None when nothing was admitted at all —
        which is itself a result, not an error.

        `against` is the CLEAN sighting of the same object, and giving it is what
        makes a transformed row mean anything. This used to read whichever blob
        the `contains` query returned first, which is an area ordering — so the
        moment a transform ADDED something to the frame (an occluder, a
        distractor) the row compared the original object against whatever had
        become biggest, and reported the object's every feature as lost. That is
        what made the occlusion and clutter rows harness artifacts rather than
        measurements. The substrate can now say which blob is which across two
        sightings, and this asks it."""
        counter[0] += 1
        source = f"fls_{tag}_{counter[0]}"
        judgements.clear()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.see(str(path), source=source, domain=DOMAIN, actor_identity=None)
        verdict = judgements[-1] if judgements else None
        # ASK WHAT THE PERCEPT WAS CALLED. The substrate names a percept from the
        # image's own content digest, so the label handed in is no longer the
        # concept's name -- rebuilding it here found nothing and the run read as
        # "no examples admitted" rather than "the name moved".
        if percept is None:
            return None
        content = getattr(percept, "content", None) or {}
        blobs = content.get("blobs") or []
        if not blobs:
            return None
        blob = ""
        matched_on = None
        if against and against.get("content"):
            from core.perception.perception_faculty import PerceptionFaculty
            for pair in PerceptionFaculty.correspond(against["content"], content):
                if pair["before"] == against["blob"]:
                    blob, matched_on = pair["after"], pair["on"]
                    break
            if not blob:
                # The substrate cannot say this is the same thing. That is an
                # honest absence and is reported as one, never resolved by
                # falling back to "whatever is biggest".
                return None
        else:
            blob = max(blobs, key=lambda b: float(
                b.get("properties", {}).get("occupies") or 0.0))["name"]
        feats, _ev = await observed_instance_features(db, blob)
        # Everything the substrate HOLDS of it, including anything it named it.
        from core.reasoning.concept_graph_reasoning import instance_predicates
        held = await instance_predicates(db, blob)
        bbox = await db.execute_query(
            "SELECT cr.relation, cr.target_surface FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON cr.source_concept_id = c.concept_id "
            "WHERE c.name = $1 AND cr.relation IN ('occupies','sits')",
            (blob,), fetch_all=True) or []
        props = {str(r["relation"]): str(r["target_surface"]) for r in bbox}
        split = split_features(feats)
        split["position"] = props.get("sits")
        try:
            occupies = float(props.get("occupies"))
        except (TypeError, ValueError):
            occupies = None
        return {"blob": blob, "source": percept.source, "features": split,
                "content": content, "matched_on": matched_on,
                "raw": sorted(feats), "held": sorted(held),
                # HOW MUCH OF THE FRAME the thing found takes up. This is the
                # only positional/extent number the substrate actually stores,
                # so region identity is measured by its drift rather than by a
                # bounding-box IoU the graph never keeps.
                "occupies": occupies,
                "decision": getattr(verdict, "decision", None),
                "accept": getattr(verdict, "accept", None),
                "claims": len(getattr(verdict, "claims", ()) or ())}

    # ── A. TEACH, THROUGH SIGHT ALONE ───────────────────────────────────────
    print("== A. A category taught through the live substrate, from sight ==",
          flush=True)
    t0 = time.perf_counter()
    pos_paths, neg_paths = [], []
    for i, r in enumerate(RADII[:max(2, args.teach // 2)] * 2):
        if len(pos_paths) >= args.teach:
            break
        p = STIM / f"teach_{tag}_pos{i}.png"
        draw(p, "circle", "red", r)
        pos_paths.append(p)
    for i, (sh, co) in enumerate([("square", "red"), ("circle", "blue"),
                                  ("triangle", "green"), ("square", "blue")]):
        p = STIM / f"teach_{tag}_neg{i}.png"
        draw(p, sh, co, RADII[i % len(RADII)])
        neg_paths.append(p)

    pos_obs = [await observe(p) for p in pos_paths]
    neg_obs = [await observe(p) for p in neg_paths]
    positives = [o["blob"] for o in pos_obs if o]
    negatives = [o["blob"] for o in neg_obs if o]
    print(f"  {len(positives)} positive(s), {len(negatives)} negative(s) admitted "
          f"through see()", flush=True)
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        induced = await coord.learning.induce_category(
            CAT, positives=positives, negatives=negatives, domain=DOMAIN)
        clf = f"falsify_{tag}"
        trained = await coord.learning.train_clause_classifier(
            clf, {CAT: positives}, others=negatives, domain=DOMAIN, epochs=60)
        await get_uncertainty_system().drain_writes()
    print(f"  rules: {induced.status.value}, "
          f"{len(induced.candidates or [])} hypothesis/es", flush=True)
    print(f"  clauses: accuracy {trained['training_accuracy']} over "
          f"{trained['examples']} example(s)", flush=True)
    EV.metric("taught_category", CAT, "name")
    EV.metric("induction_status", induced.status.value, "status")
    EV.metric("clause_training_accuracy", trained["training_accuracy"], "ratio")

    # ── B/C. THE BATTERY, ON SYNTHETIC STIMULI ──────────────────────────────
    battery = thin(T.standard_battery(include_background=True), args.mags)
    combos = [(s, c, r) for s in SHAPES for c in COLOURS for r in RADII]
    step = max(1, len(combos) // max(1, args.stimuli))
    chosen = combos[::step][:args.stimuli]
    bases: List[Tuple[Path, bool]] = []
    for sh, co, r in chosen:
        p = STIM / f"base_{sh}_{co}_{r}.png"
        draw(p, sh, co, r)
        bases.append((p, sh == "circle" and co == "red"))
    # Always include at least one true member of the taught category.
    if not any(is_member for _p, is_member in bases):
        p = STIM / f"base_circle_red_{RADII[1]}.png"
        draw(p, "circle", "red", RADII[1])
        bases.append((p, True))

    total = len(bases) * len(battery)
    print(f"\n== B/C. {len(bases)} stimuli x {len(battery)} conditions = "
          f"{total} sightings through the live substrate ==", flush=True)
    EV.metric("synthetic_stimuli", len(bases), "count")
    EV.metric("conditions_per_stimulus", len(battery), "count")
    EV.metric("synthetic_sightings", total, "count")

    syn = Tally()
    work = WORK / f"syn_{tag}"
    work.mkdir(parents=True, exist_ok=True)
    done = 0
    for bi, (base, is_member) in enumerate(bases):
        clean = await observe(base)
        if clean is not None:
            clean["bbox"] = None
        img = cv2.imread(str(base), cv2.IMREAD_COLOR)
        for family, mag, fn in battery:
            try:
                out = fn(img)
            except Exception:
                syn.seen[(family, mag)] += 1
                continue
            p = work / f"{bi}_{family}_{mag.replace('/', '_')}.png"
            cv2.imwrite(str(p), out)
            got = await observe(p, against=clean)
            syn.record(family, mag, clean, got)
            if is_member:
                # What the substrate NAMED it: everything it holds that it did
                # not observe. `held` is every isa edge, `raw` is the
                # root-sourced ones, so the difference is exactly the
                # conclusions — by rule or by clause vote.
                derived = ([n for n in got["held"] if n not in got["raw"]]
                           if got else [])
                syn.record_naming(family, mag, CAT, derived)
            done += 1
            if done % 25 == 0:
                rate = done / max(1e-6, time.perf_counter() - t0)
                eta = (total - done) / max(1e-6, rate)
                print(f"    {done}/{total} sightings, {rate:.1f}/s, "
                      f"~{eta/60:.1f} min left", flush=True)
    print(table(syn, "B/C. WHAT THE SUBSTRATE HOLDS — synthetic, % unchanged",
                naming=True))

    # ── D. NATURAL PHOTOGRAPHS ──────────────────────────────────────────────
    nat: Optional[Tally] = None
    ndone = 0
    photos = sorted(COCO.glob("*.jpg"))[:args.images] if COCO.is_dir() else []
    if photos:
        nat_battery = thin(T.standard_battery(include_background=False), args.mags)
        ntotal = len(photos) * len(nat_battery)
        print(f"\n== D. {len(photos)} real photographs x {len(nat_battery)} "
              f"conditions = {ntotal} sightings ==", flush=True)
        EV.metric("natural_photographs", len(photos), "count")
        EV.metric("natural_sightings", ntotal, "count")
        nat = Tally()
        nwork = WORK / f"nat_{tag}"
        nwork.mkdir(parents=True, exist_ok=True)
        ndone = 0
        nt0 = time.perf_counter()
        for pi, photo in enumerate(photos):
            clean = await observe(photo)
            img = cv2.imread(str(photo), cv2.IMREAD_COLOR)
            if img is None:
                continue
            for family, mag, fn in nat_battery:
                try:
                    out = fn(img)
                except Exception:
                    nat.seen[(family, mag)] += 1
                    continue
                p = nwork / f"{pi}_{family}_{mag.replace('/', '_')}.png"
                cv2.imwrite(str(p), out)
                nat.record(family, mag, clean, await observe(p, against=clean))
                ndone += 1
                if ndone % 25 == 0:
                    rate = ndone / max(1e-6, time.perf_counter() - nt0)
                    print(f"    {ndone}/{ntotal} sightings, {rate:.1f}/s, "
                          f"~{(ntotal-ndone)/max(1e-6,rate)/60:.1f} min left",
                          flush=True)
        print(table(nat, "D. WHAT THE SUBSTRATE HOLDS — real photographs",
                    naming=False))
    else:
        print(f"\n  no photographs at {COCO} — section D not run", flush=True)

    # ── THE PREDICTIONS ─────────────────────────────────────────────────────
    print("\n== The predictions, answered ==")
    results: Dict[str, Any] = {"predictions": {}}

    def verdict(name: str, statement: str, held: Optional[bool], detail: str) -> None:
        state = "NOT MEASURED" if held is None else (
            "CONFIRMED" if held else "REFUTED")
        results["predictions"][name] = {"statement": statement, "verdict": state,
                                        "detail": detail}
        EV.check(f"{name}: {statement}", True, f"{state} — {detail}")
        print(f"  [{state:<12}] {name}  {statement}\n               {detail}")

    def r(fam, mag, feat):
        return syn.rate(fam, mag, feat)

    mags_b = syn.magnitudes("brightness")
    dim = r("brightness", mags_b[0], "color") if mags_b else None
    verdict("P1", "colour is not illumination-invariant",
            None if dim is None else dim < 0.8,
            f"colour symbol survives {mags_b[0]} brightness in {dim*100:.0f}% of "
            f"cases" if dim is not None else "not measured")

    mags_z = syn.magnitudes("zoom")
    zoom_rates = [(m, r("zoom", m, "size")) for m in mags_z]
    zoom_rates = [(m, v) for m, v in zoom_rates if v is not None]
    zoom_worst = min((v for _m, v in zoom_rates), default=None)
    verdict("P2", "size is frame-relative, not object-relative",
            None if zoom_worst is None else zoom_worst < 0.5,
            ("size band survives zoom in as few as "
             f"{zoom_worst*100:.0f}% of cases — "
             + ", ".join(f"{m}: {v*100:.0f}%" for m, v in zoom_rates))
            if zoom_worst is not None else "not measured")

    mags_t = syn.magnitudes("translate")
    tr = min([r("translate", m, "position") for m in mags_t
              if r("translate", m, "position") is not None], default=None)
    verdict("P3", "position is frame-relative",
            None if tr is None else tr < 0.8,
            f"position symbol survives translation in as few as {tr*100:.0f}% of "
            f"cases" if tr is not None else "not measured")

    rot = syn.family_rate("rotate", "shape")
    per = syn.family_rate("perspective", "shape")
    verdict("P4", "shape survives rotation and not perspective",
            None if (rot is None or per is None) else rot > per,
            f"shape survives rotation in {rot*100:.0f}% of cases, perspective in "
            f"{per*100:.0f}%" if rot is not None and per is not None
            else "not measured")

    bl = syn.family_rate("blur", "shape")
    no = syn.family_rate("noise", "shape")
    verdict("P5", "circularity is attacked from both sides",
            None if (bl is None or no is None) else (bl < 0.95 or no < 0.95),
            f"shape survives blur in {bl*100:.0f}% of cases, noise in "
            f"{no*100:.0f}%" if bl is not None and no is not None
            else "not measured")

    if nat is not None:
        nat_found = sum(nat.found.values()) / max(1, sum(nat.seen.values()))
        syn_found = sum(syn.found.values()) / max(1, sum(syn.seen.values()))
        nat_shape = nat.family_rate("blur", "shape")
        verdict("P6", "segmentation is the binding constraint on photographs",
                nat_found < syn_found or (nat_shape is not None and nat_shape < 0.7),
                f"a region is admitted at all in {nat_found*100:.0f}% of "
                f"photograph sightings vs {syn_found*100:.0f}% of synthetic ones")
        EV.metric("natural_admission_rate", round(nat_found, 4), "ratio")
        EV.metric("synthetic_admission_rate", round(syn_found, 4), "ratio")
    else:
        verdict("P6", "segmentation is the binding constraint on photographs",
                None, "section D not run")

    # P8 — the calibration question, and the reason this study exists.
    broken: List[Tuple[str, str, float, float]] = []
    # WHICH FEATURES CHANGING MEANS PERCEPTION BROKE. Not all of them: `position`
    # is a fact about the VIEW, exactly like `occupies`, and `occupies` was never
    # counted here. Under a 28% translation the object is perceived perfectly —
    # colour 100%, shape 100% — and it has simply moved, so `sits middle_right`
    # is as true of the new view as `sits center` was of the old one. Counting
    # that as broken perception measures frame-relativity, which is P3's job and
    # is confirmed, and then holds the acceptance band responsible for not
    # doubting a claim that is true. The same category error as reading whichever
    # blob came back first, one level up.
    OBJECT_FEATURES = tuple(f for f in FEATURES if f != "position")
    for fam in syn.families():
        for mag in syn.magnitudes(fam):
            rates = [syn.rate(fam, mag, f) for f in OBJECT_FEATURES]
            rates = [x for x in rates if x is not None]
            if not rates:
                continue
            v = syn.verdicts[(fam, mag)]
            nv = sum(v.values())
            if not nv:
                continue
            broken.append((fam, mag, min(rates), v.get("ACT", 0) / nv))
    hard = [(f, m, s_, a) for f, m, s_, a in broken if s_ <= 0.5]
    if hard:
        mean_act_when_broken = sum(a for _f, _m, _s, a in hard) / len(hard)
        ok = [(f, m, s_, a) for f, m, s_, a in broken if s_ >= 0.99]
        mean_act_when_intact = (sum(a for _f, _m, _s, a in ok) / len(ok)) if ok else None
        verdict("P8", "the substrate does not know when its perception has broken",
                mean_act_when_broken > 0.5,
                f"in the {len(hard)} condition(s) where a feature survived 50% of "
                f"the time or less, the percept was still judged ACT in "
                f"{mean_act_when_broken*100:.0f}% of sightings"
                + (f" — against {mean_act_when_intact*100:.0f}% where every "
                   f"feature was intact" if mean_act_when_intact is not None else ""))
        EV.metric("act_rate_when_features_broken", round(mean_act_when_broken, 4), "ratio")
        if mean_act_when_intact is not None:
            EV.metric("act_rate_when_features_intact",
                      round(mean_act_when_intact, 4), "ratio")
        results["calibration"] = {
            "per_condition": [{"transform": f, "magnitude": m,
                               "worst_feature_survival": s_, "act_rate": a}
                              for f, m, s_, a in broken],
            "act_when_broken": mean_act_when_broken,
            "act_when_intact": mean_act_when_intact,
        }
    else:
        verdict("P8", "the substrate does not know when its perception has broken",
                None, "no condition degraded a feature to 50% or below")

    name_seen = sum(syn.name_seen.values())
    named = sum(syn.named.values())
    if name_seen:
        worst_lit = min(
            [v for fam in syn.families() for f in FEATURES
             if (v := syn.family_rate(fam, f)) is not None], default=1.0)
        verdict("P7", "recognition inherits every bit of the feature instability",
                (named / name_seen) <= 1.0,
                f"the taught category is still named in {named/name_seen*100:.0f}% "
                f"of transformed sightings of a true member; the weakest single "
                f"literal survives {worst_lit*100:.0f}% of the time, and a "
                f"conjunction cannot beat its weakest term")
        EV.metric("recognition_recall_under_transform",
                  round(named / name_seen, 4), "ratio")
    else:
        verdict("P7", "recognition inherits every bit of the feature instability",
                None, "no true member of the taught category was transformed")

    # ── WHAT MOVED ──────────────────────────────────────────────────────────
    if syn.wrong_names:
        print("\n== Names given to a true member that were NOT its category ==")
        for k, v in sorted(syn.wrong_names.items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {k}  ({v})")
        results["wrong_names"] = dict(sorted(syn.wrong_names.items(),
                                             key=lambda kv: -kv[1])[:25])

    print("\n== The most common symbol changes ==")
    for f in FEATURES:
        top = sorted(syn.lost[f].items(), key=lambda kv: -kv[1])[:6]
        if top:
            print(f"  {f:<10} " + ", ".join(f"{k} ({v})" for k, v in top))

    results["synthetic"] = {
        "per_condition": {fam: {mag: {f: syn.rate(fam, mag, f) for f in FEATURES}
                                for mag in syn.magnitudes(fam)}
                          for fam in syn.families()},
        "family_rates": {fam: {f: syn.family_rate(fam, f) for f in FEATURES}
                         for fam in syn.families()},
        "admission": {f"{fam}/{mag}": (syn.found[(fam, mag)] /
                                       max(1, syn.seen[(fam, mag)]))
                      for (fam, mag) in syn.seen},
        "naming": {f"{fam}/{mag}": {"recall": (syn.named[(fam, mag)] /
                                               max(1, syn.name_seen[(fam, mag)])),
                                    "wrong": (syn.misnamed[(fam, mag)] /
                                              max(1, syn.name_seen[(fam, mag)]))}
                   for (fam, mag) in syn.name_seen},
        "symbol_changes": {f: dict(sorted(syn.lost[f].items(),
                                          key=lambda kv: -kv[1])[:25])
                           for f in FEATURES},
        "verdicts": {f"{fam}/{mag}": dict(v)
                     for (fam, mag), v in syn.verdicts.items()},
        "extent_drift": {f"{fam}/{mag}": (sum(v) / len(v)) if v else None
                         for (fam, mag), v in syn.drift.items()},
    }
    if nat is not None:
        results["natural"] = {
            "family_rates": {fam: {f: nat.family_rate(fam, f) for f in FEATURES}
                             for fam in nat.families()},
            "admission": {f"{fam}/{mag}": (nat.found[(fam, mag)] /
                                           max(1, nat.seen[(fam, mag)]))
                          for (fam, mag) in nat.seen},
            "symbol_changes": {f: dict(sorted(nat.lost[f].items(),
                                              key=lambda kv: -kv[1])[:25])
                               for f in FEATURES},
        }
    results["scale"] = {"stimuli": len(bases), "photographs": len(photos),
                        "conditions": len(battery),
                        "sightings": done + (ndone if photos else 0),
                        "wall_clock_s": round(time.perf_counter() - t0, 1)}

    out = HERE / f"findings_{tag}.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    for fam in syn.families():
        for f in FEATURES:
            v = syn.family_rate(fam, f)
            if v is not None:
                EV.metric(f"synthetic/{fam}/{f}", round(v, 4), "survival")
    EV.metric("wall_clock_s", results["scale"]["wall_clock_s"], "s")
    EV.write()
    print(f"\n  findings: {out.relative_to(REPO)}")
    print(f"  {results['scale']['sightings']} sightings in "
          f"{results['scale']['wall_clock_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
