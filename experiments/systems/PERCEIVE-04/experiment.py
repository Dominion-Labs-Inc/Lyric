#!/usr/bin/env python3
"""PERCEIVE-04 — the substrate remembers a picture, not just a sentence about it.

`coord.remember_met` takes a real image in by every sense that can and stores a
memory whose text describes what is in it (so it is recallable by content). What it keeps of the
picture is its SUMMARY -- the gist it is seen again from -- and its sight trace
-- what it is known again by -- never the photograph. This verifies, on the
real system:
  1. the memory is stored and returns an id,
  2. no photograph is kept: what is kept is the sight trace,
  3. the perceived structure (its properties and the things seen in it) and the gist ride with it,
  4. the seeing is LINKED to its memory (recall_media finds it by memory id),
  5. the picture is seen again from memory (recollect), at its proportions,
  6. the memory's recallable text describes the picture.

    PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
    ./venv_lyric/bin/python3 experiments/systems/PERCEIVE-04/experiment.py
"""
from __future__ import annotations
import os
for k, v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
             "POSTGRES_DATABASE": "lyric_dev", "LYRIC_NO_WATCHDOG": "1"}.items():
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
        from core.database import get_database_manager
        await get_database_manager().assert_database_identity(os.environ["POSTGRES_DATABASE"])

        memory_id = await coord.remember_met([(IMAGE, None, None)], note="a test card I was shown",
                                             origin=Origin.own("PERCEIVE-04"))
        images = await coord.recall_media(memory_id) if memory_id else []
        seen_again = [r for r in (await coord.recollect(memory_id) if memory_id else [])
                      if r["kind"] == "image"]

    print(f"=== remembered {IMAGE} ===", flush=True)
    print(f"  memory_id: {memory_id}", flush=True)
    img = images[0] if images else None
    if img:
        print(f"  kept {img['byte_size']} bytes, mime {img['mime']}, "
              f"kind {img['perceived'].get('kind')}", flush=True)
        print(f"  the photograph kept: {hashlib.sha256(img['bytes']).hexdigest() == file_sha}",
              flush=True)
        per = img["perceived"]
        print(f"  perceived: {per.get('caption')}", flush=True)
        print(f"    properties: {per.get('properties')}", flush=True)
        print(f"    seen in it: {[b.get('isa') for b in (per.get('blobs') or [])]}", flush=True)

    gist = (img["perceived"].get("gist") or {}) if img else {}
    pixels = seen_again[0]["pixels"] if seen_again else None
    checks = {
        "memory_stored": memory_id is not None,
        "seeing_linked_to_memory": bool(img) and img["memory_id"] == memory_id,
        "no_photograph_kept": bool(images) and all(
            hashlib.sha256(m["bytes"]).hexdigest() != file_sha
            and not str(m["mime"]).startswith("image/") for m in images),
        "sight_trace_kept": bool(img) and img["perceived"].get("kind") == "sight_trace",
        "dimensions_retained_in_gist": gist.get("width") == 800 and gist.get("height") == 400,
        "perceived_structure_attached": bool(img) and
            bool((img["perceived"].get("properties") or {}).get("dominant_color")) and
            bool(img["perceived"].get("blobs")),
        "seen_again_from_memory": pixels is not None and
            abs(pixels.shape[1] / pixels.shape[0] - 2.0) < 0.02,
        "memory_text_describes_picture": bool(img) and
            "image" in str(img["perceived"].get("caption", "")).lower(),
    }
    # The memory it formed is forgotten again, with what it kept.
    if memory_id:
        forgotten = await coord.memory.delete_memory(memory_id, reason="PERCEIVE-04")
        print(f"  cleanup: memory {memory_id} forgotten: {forgotten}", flush=True)
    summary = {"checks": checks, "all_pass": all(checks.values())}
    manifest = {
        "experiment": "PERCEIVE-04",
        "purpose": "memory keeps a picture's summary and sight trace, never the photograph; seen again from memory",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "image": IMAGE, "file_sha256": file_sha, "memory_id": memory_id,
        "kept": None if not img else {k: img[k] for k in
                    ("media_id", "memory_id", "mime", "byte_size")},
        "checks": checks,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("\n=== summary ===", flush=True)
    print(json.dumps(checks, indent=2), flush=True)
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
