#!/usr/bin/env python3
"""PERCEIVE-02 — give the real substrate sight over REAL files.

Unlike PERCEIVE-01, nothing here is hand-authored. The vision faculty opens
actual pixels, perceives their structure with classical algorithms, and admits
what it saw through the perception ingress. We then verify the substrate holds
exactly what the code read from the bytes -- the same widths, colours, shapes and
codec the describer measured -- and that model-free instance recognition both
fires on a learned reference and refuses to hallucinate it elsewhere.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-02/experiment.py
"""
from __future__ import annotations
import os, re
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, io, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = Path(__file__).resolve().parents[3]              # TorinAI repo root
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent

IMAGE = str(REPO / "test_data" / "vision_test.png")     # a real file in the repo
VIDEO = "/Users/stefan/Desktop/Founder Video.mp4"        # a real video
REF_PHOTO = "/Users/stefan/Desktop/d9f2d50d-fb93-4619-a754-edfcd75a9ef9.jpg"


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager(); await db.initialize()
        from core.perception import vision          # for ground-truth comparison

    async def edges_for(subject):
        rows = await db.execute_query(
            """SELECT cr.relation, cr.target_surface
                 FROM unified.concept_relations cr
                 JOIN unified.concepts c ON cr.source_concept_id = c.concept_id
                WHERE c.name = $1 ORDER BY cr.relation, cr.target_surface""",
            (subject,), fetch_all=True) or []
        return [(str(r["relation"]).replace("_", " ").strip(),
                 str(r["target_surface"]).strip()) for r in rows]

    async def beliefs_for(subject):
        rows = await db.execute_query(
            "SELECT claim, posterior_probability FROM unified.beliefs "
            "WHERE claim ILIKE $1 ORDER BY posterior_probability DESC",
            (f"%{subject}%",), fetch_all=True) or []
        return [(r["claim"], round(float(r["posterior_probability"] or 0), 4))
                for r in rows]

    checks = {}

    # === 1. a real IMAGE, perceived and admitted ==========================
    truth_img = vision.describe_image(IMAGE)
    await coord.see(IMAGE, source="test_card")
    img_edges = dict((rel, tgt) for rel, tgt in await edges_for("test_card"))
    perceived = {tgt for rel, tgt in await edges_for("test_card") if rel == "observed"}
    # Each object-like region is admitted as its own individual, so what the
    # substrate holds about a blob is read off the BLOB, not off the image.
    blobs = sorted(tgt for rel, tgt in await edges_for("test_card") if rel == "contains")
    blob_features = {b: {tgt for rel, tgt in await edges_for(b) if rel == "isa"}
                     for b in blobs}

    checks["image_width_matches_bytes"] = img_edges.get("has width") == str(truth_img["width"])
    checks["image_height_matches_bytes"] = img_edges.get("has height") == str(truth_img["height"])
    checks["image_dominant_color_matches"] = (
        img_edges.get("dominant color") == truth_img["dominant_colors"][0]["name"])
    # Honest self-consistency: the substrate must hold every structure the
    # describer measured (labels derived from the real output, not hardcoded).
    def _term(s):
        return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")
    truth_regions = [r for r in truth_img["regions"] if r["area_fraction"] <= 0.9]
    checks["image_holds_one_individual_per_region"] = len(blobs) == len(truth_regions)
    # every measured structure is held OF a blob, as separate features a rule
    # can bind to, not as one flattened label
    expected = [{_term(r["color"]), _term(r["shape"]), _term(r["size"])}
                for r in truth_regions]
    held = list(blob_features.values())
    checks["image_holds_all_perceived_structures"] = all(
        any(want <= got for got in held) for want in expected)
    # and perception genuinely found the real shapes in the card
    checks["image_saw_a_red_circle"] = any(
        "red" in r["color"] and r["shape"] == "circle" for r in truth_regions)
    checks["image_saw_a_green_rectangle"] = any(
        r["color"] == "green" and r["shape"] == "rectangle" for r in truth_regions)

    print("=== REAL IMAGE:", IMAGE, "===", flush=True)
    print(f"  describer measured: {truth_img['width']}x{truth_img['height']} "
          f"{truth_img['format']}, dominant {truth_img['dominant_colors'][0]['name']}, "
          f"regions={truth_img['region_count']}", flush=True)
    print(f"  substrate observed: {sorted(perceived)}", flush=True)
    for b in blobs:
        print(f"      blob {b}: {sorted(blob_features[b])}", flush=True)
    for rel, tgt in sorted(await edges_for("test_card")):
        print(f"      {rel} -> {tgt}", flush=True)
    print(flush=True)

    # === 2. a real VIDEO, perceived and admitted ==========================
    truth_vid = vision.describe_video(VIDEO)
    await coord.see(VIDEO, source="founder_clip")
    vid_edges = dict((rel, tgt) for rel, tgt in await edges_for("founder_clip"))
    vid_observed = {tgt for rel, tgt in await edges_for("founder_clip") if rel == "observed"}

    checks["video_codec_matches_bytes"] = vid_edges.get("has codec") == str(truth_vid.get("codec"))
    checks["video_frames_match_bytes"] = vid_edges.get("has frames") == str(truth_vid.get("frames"))
    checks["video_holds_duration"] = "lasts" in vid_edges
    checks["video_saw_motion"] = ("motion" in vid_observed) == bool(truth_vid.get("has_motion"))

    print("=== REAL VIDEO:", VIDEO.split("/")[-1], "===", flush=True)
    print(f"  describer measured: {truth_vid.get('codec')} "
          f"{truth_vid.get('width')}x{truth_vid.get('height')}, "
          f"{truth_vid.get('duration')}s, {truth_vid.get('frames')} frames, "
          f"motion={truth_vid.get('mean_motion')}", flush=True)
    for rel, tgt in sorted(await edges_for("founder_clip")):
        print(f"      {rel} -> {tgt}", flush=True)
    print(flush=True)

    # === 3. model-free INSTANCE recognition ===============================
    # Learn a reference photo as a known instance, then confirm the faculty
    # recognises it in that same photo and does NOT hallucinate it in the card.
    kp = coord.vision.learn_instance("known_face", REF_PHOTO)
    await coord.see(REF_PHOTO, source="photo_a")
    await coord.see(IMAGE, source="card_b")
    recognised_in_photo = "known_face" in {
        tgt for rel, tgt in await edges_for("photo_a") if rel == "observed"}
    recognised_in_card = "known_face" in {
        tgt for rel, tgt in await edges_for("card_b") if rel == "observed"}
    checks["instance_recognised_where_present"] = bool(recognised_in_photo)
    checks["instance_not_hallucinated_elsewhere"] = not recognised_in_card

    print("=== INSTANCE RECOGNITION (no model) ===", flush=True)
    print(f"  reference 'known_face' stored with {kp} keypoints", flush=True)
    print(f"  recognised in its own photo: {recognised_in_photo}", flush=True)
    print(f"  hallucinated in the test card: {recognised_in_card}", flush=True)
    print(flush=True)

    print("=== what the substrate believes it saw (sample) ===", flush=True)
    for subject in ("test_card", "founder_clip", "photo_a"):
        for claim, post in (await beliefs_for(subject))[:4]:
            print(f"    «{claim}» -> {post}", flush=True)
    print(flush=True)

    summary = {"checks": checks, "all_pass": all(checks.values())}
    manifest = {
        "experiment": "PERCEIVE-02",
        "purpose": "sight over real files: substrate holds exactly what code read from the bytes",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "image": {"path": IMAGE, "measured": {k: truth_img[k] for k in
                  ("width", "height", "format", "region_count", "dominant_colors")}},
        "video": {"path": VIDEO, "measured": {k: truth_vid.get(k) for k in
                  ("codec", "width", "height", "duration", "frames", "mean_motion")}},
        "checks": checks,
        "summary": summary,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("=== summary ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
