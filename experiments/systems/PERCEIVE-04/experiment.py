#!/usr/bin/env python3
"""PERCEIVE-04 — the substrate remembers a picture, not just a sentence about it.

`coord.remember_image` perceives a real image, stores a memory whose text
describes what is in it (so it is recallable by content), and retains the image
BYTES with the memory. This verifies, on the real system, that:
  1. the memory is stored and returns an id,
  2. the exact image bytes round-trip (sha-256 of what comes back == the file),
  3. the perceived structure (dimensions, palette, regions) rides with it,
  4. the image is LINKED to its memory (recall_media finds it by memory id),
  5. the memory's recallable text describes the picture.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan TORIN_NO_WATCHDOG=1 \
    ./venv_torin/bin/python3 experiments/systems/PERCEIVE-04/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1"}.items():
    os.environ.setdefault(k, v)
import asyncio, contextlib, hashlib, io, json, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
HERE = Path(__file__).resolve().parent
IMAGE = str(REPO / "test_data" / "vision_test.png")


async def main() -> int:
    from core.memory import Origin
    file_sha = hashlib.sha256(Path(IMAGE).read_bytes()).hexdigest()

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system(); await system.initialize()
        coord = system.autonomous_coordinator

        memory_id = await coord.remember_image(IMAGE, note="a test card I was shown", origin=Origin.own("PERCEIVE-04"))
        images = await coord.recall_media(memory_id) if memory_id else []

    print(f"=== remembered {IMAGE} ===", flush=True)
    print(f"  memory_id: {memory_id}", flush=True)
    img = images[0] if images else None
    if img:
        got_sha = hashlib.sha256(img["bytes"]).hexdigest()
        print(f"  retained {img['byte_size']} bytes, mime {img['mime']}, "
              f"{img['width']}x{img['height']}", flush=True)
        print(f"  bytes round-trip exact: {got_sha == file_sha}", flush=True)
        per = img["perceived"]
        print(f"  perceived: {per.get('caption')}", flush=True)
        print(f"    dominant: {[c['name'] for c in (per.get('dominant_colors') or [])][:4]}",
              flush=True)
        print(f"    regions:  {[(r['color'], r['shape']) for r in (per.get('regions') or []) if r.get('area_fraction',1)<=0.9]}",
              flush=True)

    checks = {
        "memory_stored": memory_id is not None,
        "image_linked_to_memory": bool(img) and img["memory_id"] == memory_id,
        "bytes_round_trip_exact": bool(img) and
            hashlib.sha256(img["bytes"]).hexdigest() == file_sha,
        "dimensions_retained": bool(img) and img["width"] == 800 and img["height"] == 400,
        "perceived_structure_attached": bool(img) and
            bool(img["perceived"].get("dominant_colors")) and
            bool(img["perceived"].get("regions")),
        "memory_text_describes_picture": bool(img) and
            "image" in str(img["perceived"].get("caption", "")).lower(),
    }
    summary = {"checks": checks, "all_pass": all(checks.values())}
    manifest = {
        "experiment": "PERCEIVE-04",
        "purpose": "memory stores image data: bytes retained, perceived, linked, recallable",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "image": IMAGE, "file_sha256": file_sha, "memory_id": memory_id,
        "retained": None if not img else {k: img[k] for k in
                    ("media_id", "memory_id", "mime", "byte_size", "width", "height")},
        "checks": checks,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("\n=== summary ===", flush=True)
    print(json.dumps(checks, indent=2), flush=True)
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
