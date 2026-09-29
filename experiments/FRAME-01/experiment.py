#!/usr/bin/env python3
"""FRAME-01 — what a thing IS, against where the camera stood.

A blob used to be admitted as `isa <colour>`, `isa <shape>` AND `isa <size>`.
The first two are about the object. The third is not: `_size_category` bands an
area FRACTION, which is the object's share of the frame, so the same cup at half
the camera distance is a different category. Measured in FALSIFY-01 across 1512
live sightings, the size band survived 0% of zooms in either direction — and
unlike the colour name it cannot be rescued by stating how sure we are, because
a perfectly certain reading of the wrong KIND of property is still the wrong
property. Its discrimination came out at AUC 0.519, a coin flip.

The describer has always known the object-invariant version and thrown it away.
`vision.relations` computes left_of, above and larger_than between regions,
`describe_image` has always reported them, and nothing has ever read them. So
the one frame-INVARIANT structure sight produces never reached the substrate,
while the frame-relative band did, dressed as a property of the object.

  A  THE ARRANGEMENT SURVIVES   what the absolutes do not: the same two-object
                                scene under zoom, translation, rotation and
                                perspective.
  B  AND IT IS NOT INVENTED     a relation that was not true before a transform
                                does not become true after it.
  C  ADMITTED, NOT DISCARDED    the live substrate holds the relations as
                                beliefs between the blobs it saw.
  D  THE BAND IS GONE           no blob is a member of a size category, and the
                                exact measurement is still there as `occupies`.
  E  HONEST ABOUT ROTATION      left_of and above are NOT rotation-invariant,
                                and the run says so rather than averaging it away.

Run: ./venv_torin/bin/python3 experiments/FRAME-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import itertools
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1",
               "TORIN_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "FALSIFY-01"))

from experiments._evidence import RunRecord  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import transforms  # noqa: E402  (the FALSIFY-01 nuisance battery)

HERE = Path(__file__).resolve().parent
WORK = HERE / "work"

BGR = {"red": (40, 40, 220), "blue": (220, 60, 40),
       "green": (60, 190, 60), "violet": (200, 50, 160)}

#: Transforms that move the CAMERA and leave the scene alone. These are exactly
#: the ones an absolute size band and position word cannot survive.
GEOMETRIC = {"zoom", "translate", "rotate", "perspective"}
#: Rotation reorients the image plane, so left_of and above genuinely change
#: under it. Kept in the run and reported separately rather than dropped.
REORIENTING = {"rotate"}

EV = RunRecord(
    "FRAME-01",
    claim=("A size band and a position word are properties of the framing, and "
           "were being admitted as properties of the object. The relations "
           "between blobs — larger_than, left_of, above — are properties of the "
           "arrangement, survive the transforms that destroy the absolutes, and "
           "were computed and discarded. The substrate now holds the invariant "
           "half and no longer claims category membership from the framing."),
    hypothesis=("If the size band really were about the object, moving the "
                "camera would not change it. If the relations really are about "
                "the arrangement, moving the camera would not change them "
                "either — except rotation, which reorients the plane that "
                "left_of and above are defined in, and so should visibly break "
                "those two while leaving larger_than untouched."))

results: List[bool] = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def draw(path: Path, a_col, a_xy, a_r, b_col, b_xy, b_r) -> np.ndarray:
    """One circle and one square, of known relative size and position."""
    img = np.full((400, 600, 3), 245, np.uint8)
    cv2.circle(img, a_xy, a_r, BGR[a_col], -1)
    cv2.rectangle(img, (b_xy[0] - b_r, b_xy[1] - b_r),
                  (b_xy[0] + b_r, b_xy[1] + b_r), BGR[b_col], -1)
    if not cv2.imwrite(str(path), img):
        raise RuntimeError(f"could not write the stimulus to {path}")
    return img


def hue(name: str) -> str:
    """The colour name without its viewing-condition modifier, so an object can
    be followed across a transform that dims or washes it."""
    for m in ("dark_", "pale_", "vivid_"):
        if name.startswith(m):
            return name[len(m):]
    return name


def arrangement(content: Dict[str, Any]) -> Tuple[Set[Tuple[str, str, str]],
                                                  Set[str]]:
    """The relations the FACULTY produced, re-keyed from blob names onto the
    COLOUR of each blob, so the same fact is comparable across a transform that
    renumbered the blobs. Also returns WHICH objects were perceived at all.

    That second half is not bookkeeping, it decides what the first half means.
    A relation between two things cannot survive one of them leaving the
    picture, and two of these transforms make that happen for reasons that have
    nothing to do with relations: `zoom x0.5` shrinks the smaller object below
    `_regions`' own 0.01 minimum area, and `translate 28%` pushes it past the
    frame edge. Scoring those as broken relations measures the detection floor
    and calls it geometry."""
    by_name = {b["name"]: hue((b.get("isa") or ["?"])[0]) for b in content["blobs"]}
    out: Set[Tuple[str, str, str]] = set()
    for r in content.get("blob_relations") or []:
        a, b = by_name.get(r["subject"]), by_name.get(r["object"])
        if a and b and a != b:
            out.add((a, str(r["relation"]), b))
    return out, set(by_name.values())


async def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    tag = uuid.uuid4().hex[:6]
    DOMAIN = f"frame{tag}"

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.database import get_database_manager
        from core.perception.perception_faculty import get_perception_faculty
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager()
        await db.initialize()
        eyes = get_perception_faculty()

    cases = [
        ("red", (150, 200), 70, "blue", (450, 200), 35),
        ("red", (450, 200), 35, "blue", (150, 200), 70),
        ("green", (150, 120), 40, "violet", (430, 300), 75),
        ("green", (430, 130), 80, "violet", (160, 290), 38),
    ]
    battery = [t for t in transforms.standard_battery(include_background=False)
               if t[0] in GEOMETRIC]

    # ── A/B/E. WHAT SURVIVES A MOVE OF THE CAMERA ───────────────────────────
    print("\n== A. The arrangement survives what the absolutes do not ==")
    kept = defaultdict(lambda: [0, 0])      # kind -> [survived, total]
    invented = defaultdict(int)
    band_kept = [0, 0]
    sightings = 0
    lost_object = 0
    ground_relations = defaultdict(int)

    for n, (ac, axy, ar, bc, bxy, br) in enumerate(cases):
        p = WORK / f"case{n}.png"
        img = draw(p, ac, axy, ar, bc, bxy, br)
        _m, clean = await eyes.sense(str(p))
        base, base_objs = arrangement(clean)
        base_occ = {hue((b.get("isa") or ["?"])[0]):
                    b["properties"]["occupies"] for b in clean["blobs"]}
        if len(base) < 2:
            continue
        for family, mag, fn in battery:
            q = WORK / f"case{n}_{family}_{mag}.png"
            cv2.imwrite(str(q), fn(img))
            _m, got = await eyes.sense(str(q))
            sightings += 1
            seen, seen_objs = arrangement(got)
            rotating = family in REORIENTING
            if not base_objs <= seen_objs:
                # One of the things is no longer in the picture. Whether a
                # relation "survived" is not a question that has an answer here.
                lost_object += 1
                continue
            for fact in base:
                kind = fact[1]
                # Rotation is allowed to break the DIRECTIONAL relations; it is
                # not allowed to break larger_than, and the two are counted apart
                # so that one cannot be averaged into the other.
                bucket = (f"{kind} (rotated)" if rotating and kind != "larger_than"
                          else kind)
                kept[bucket][1] += 1
                kept[bucket][0] += (fact in seen)
            for fact in seen - base:
                # A relation that involves something that was NOT one of the
                # objects is not a claim about the arrangement going wrong -- it
                # is a new region being admitted as a thing. Measured, every one
                # of these involves the white GROUND, which a zoom crops until it
                # no longer fills the 0.9 of the frame that would have marked it
                # as the frame. That is the frame/object boundary being a magic
                # number (D4), arriving here through relations rather than being
                # caused by them, and it is counted apart so it can be seen.
                if fact[0] not in base_objs or fact[2] not in base_objs:
                    ground_relations[fact[1]] += 1
                    continue
                invented[f"{fact[1]} (rotated)" if rotating
                         and fact[1] != "larger_than" else fact[1]] += 1
            # the same scene's AREA FRACTION, for contrast: the exact number the
            # band was derived from moves freely under the very same transforms.
            for b in got["blobs"]:
                k = hue((b.get("isa") or ["?"])[0])
                if k in base_occ and base_occ[k]:
                    band_kept[1] += 1
                    band_kept[0] += (abs(b["properties"]["occupies"]
                                         - base_occ[k]) / base_occ[k] < 0.25)

    EV.metric("sightings", sightings, "count")
    EV.metric("sightings_with_an_object_missing", lost_object, "count")
    print(f"     {'(an object left the picture)':24} {lost_object}/{sightings} "
          f"sightings, not scored — see below")
    for kind in sorted(kept):
        s, t = kept[kind]
        print(f"     {kind:24} {s}/{t} survived, {invented[kind]} invented")
        EV.metric(f"survival_{kind.replace(' ', '_')}", round(s / t, 4), "ratio")

    lt_s, lt_t = kept["larger_than"]
    check("larger_than survives every camera move, including rotation",
          lt_t > 0 and lt_s == lt_t, f"{lt_s}/{lt_t}")
    check("and the area fraction it replaces does not",
          band_kept[1] > 0 and band_kept[0] / band_kept[1] < 0.9,
          f"area fraction held within 25% in only "
          f"{band_kept[0]}/{band_kept[1]} sightings")

    steady = [k for k in kept if "(rotated)" not in k and k != "larger_than"]
    for kind in sorted(steady):
        s, t = kept[kind]
        check(f"{kind} survives a camera move that does not rotate",
              t > 0 and s / t >= 0.9, f"{s}/{t}")

    print("\n== B. And nothing is invented ==")
    bogus = sum(v for k, v in invented.items() if "(rotated)" not in k)
    check("no relation between two THINGS becomes true merely by moving the "
          "camera",
          bogus == 0,
          f"{bogus} invented across {sightings} sightings")
    ground_total = sum(ground_relations.values())
    EV.metric("relations_involving_the_ground", ground_total, "count")
    # THIS CHECK USED TO ASSERT THE OPPOSITE, and the change is the finding.
    # When this run was first written the ground was decided by `area_fraction >
    # 0.9`, so a crop that shrank the background under that line promoted it to
    # an object and relations formed with it — 50 of them, which this recorded as
    # the frame/object boundary being a magic number. The boundary is now decided
    # by what a region IS (how much of the picture's own edge it is made of), and
    # the same run produces none.
    check("a camera move no longer promotes the GROUND into a thing that "
          "relations attach to",
          ground_total == 0,
          f"{ground_total} relation(s) to a region that was background before "
          f"the crop" + (": " + ", ".join(f"{k} x{v}" for k, v
                                          in sorted(ground_relations.items()))
                         if ground_total else " (was 50 under the old rule)"))

    # The excluded sightings are a real finding, just not a finding about
    # relations: they are the detector's own floor and the frame's own edge.
    check("an object that leaves the picture is reported as that, and not as a "
          "broken relation",
          lost_object > 0,
          f"{lost_object}/{sightings} sightings lost an object — `zoom x0.5` "
          f"shrinks the smaller one under the 0.01 minimum area and "
          f"`translate 28%` pushes it off the edge")

    print("\n== E. Honest about rotation ==")
    rot = {k: v for k, v in kept.items() if "(rotated)" in k}
    if rot:
        worst = min(v[0] / v[1] for v in rot.values() if v[1])
        check("turning the picture DOES break left_of and above, and the run "
              "says so rather than averaging it away",
              worst < 1.0,
              "; ".join(f"{k}: {v[0]}/{v[1]}" for k, v in sorted(rot.items())))
        check("while larger_than is untouched by the same rotation",
              lt_s == lt_t, f"{lt_s}/{lt_t}")

    # ── C. THE LIVE SUBSTRATE HOLDS THEM ────────────────────────────────────
    print("\n== C. The substrate holds the arrangement, not just the parts ==")
    subject = f"frame_{tag}"
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        percept = await coord.see(str(WORK / "case0.png"), source=subject,
                                  domain=DOMAIN, actor_identity=None)
        await get_uncertainty_system().drain_writes()
    # The substrate names a percept from the image's own content digest, so the
    # label handed in is not the concept's name. Ask for it.
    subject = percept.source if percept else subject

    rows = await db.execute_query(
        "SELECT c1.name AS subj, cr.relation AS rel, "
        "COALESCE(c2.name, cr.target_surface) AS obj "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
        "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
        "WHERE c1.name LIKE $1 AND cr.relation = ANY($2::text[])",
        (f"{subject}\\_%", ["larger_than", "left_of", "above"]),
        fetch_all=True) or []
    held = {(r["subj"], r["rel"], r["obj"]) for r in rows}
    check("the relations between blobs are admitted to the concept graph",
          bool(held), "; ".join(f"{s} {r} {o}" for s, r, o in sorted(held)) or "none")
    EV.metric("relations_admitted", len(held), "count")

    beliefs = await db.execute_query(
        "SELECT belief_text, prior_probability p FROM unified.beliefs "
        "WHERE belief_text LIKE $1 AND (belief_text LIKE '%larger_than%' "
        "OR belief_text LIKE '%left_of%' OR belief_text LIKE '%above%')",
        (f"{subject}\\_%",), fetch_all=True) or []
    check("and they move posteriors, like every other observation",
          bool(beliefs),
          "; ".join(f"{b['belief_text']} @{b['p']}" for b in beliefs[:3]) or "none")

    # ── D. THE BAND IS GONE ─────────────────────────────────────────────────
    print("\n== D. No blob is a member of a size category ==")
    _m, one = await eyes.sense(str(WORK / "case0.png"))
    bands = {"tiny", "small", "medium", "large", "dominant"}
    claimed = {f for b in one["blobs"] for f in (b.get("isa") or [])}
    check("the size band is not among a blob's categories",
          not (claimed & bands),
          f"isa: {sorted(claimed)}")
    check("while the exact measurement it came from is still stated",
          all(b["properties"].get("occupies") is not None for b in one["blobs"]),
          "; ".join(f"{b['name']} occupies {b['properties']['occupies']}"
                    for b in one["blobs"]))

    isa_rows = await db.execute_query(
        "SELECT COALESCE(c2.name, cr.target_surface) AS obj "
        "FROM unified.concept_relations cr "
        "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
        "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
        "WHERE c1.name LIKE $1 AND cr.relation = 'isa'",
        (f"{subject}\\_%",), fetch_all=True) or []
    check("and the live substrate holds no size membership either",
          not ({str(r["obj"]) for r in isa_rows} & bands),
          f"isa in the graph: {sorted({str(r['obj']) for r in isa_rows})}")

    passed = sum(results)
    print(f"\n==== FRAME-01: {passed}/{len(results)} checks passed ====")
    EV.metric("checks_passed", passed, "count")
    EV.metric("checks_total", len(results), "count")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
