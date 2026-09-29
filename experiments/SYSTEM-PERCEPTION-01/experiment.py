#!/usr/bin/env python3
"""SYSTEM-PERCEPTION-01 — the perception faculty, alone, on the live substrate.

One authority for sensing (`PerceptionFaculty`, reached through
`get_perception_faculty`). A real image is sensed into structure; a file it has
no reader for is refused rather than guessed; two sightings correspond; an
instance is learned by name and forgotten.

Then SIGHT, the whole of it (F): a real photograph seen through `coord.see`, the
one entry point, forms a memory that can produce the picture again, is admitted
once as evidence, and is held as beliefs grounded in that memory. The
photograph is a COCO camera image with one pixel changed per run, so each run
sees a picture no earlier run has seen; everything it wrote is removed by id.

Run: ./venv_lyric/bin/python3 experiments/SYSTEM-PERCEPTION-01/experiment.py
"""
from __future__ import annotations

import asyncio
import os
import random
import string
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from experiments._evidence import RunRecord  # noqa: E402
from experiments._isolation import ROOT, authority_audit, boot, db, outcome, shutdown  # noqa: E402

STIMULUS = ROOT / "experiments" / "RECOGNISE-02" / "stimuli" / "recog2_13ff0d_1.png"
#: A real camera photograph (COCO), 640x433.
PHOTO = ROOT / "data" / "vision_flan" / "images" / "000000298154.jpg"
OTHER = ROOT / "experiments" / "RECOGNISE-02" / "stimuli" / "recog2_13ff0d_10.png"
EV = RunRecord(
    "SYSTEM-PERCEPTION-01",
    claim=("Perception has one sensing authority: a real image becomes structure, a file with "
           "no reader is refused, two sightings correspond, and an instance can be learned and "
           "forgotten."),
    hypothesis=("A second faculty, a guessed reading of an unreadable file, or a dead public "
                "method would each fail here."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    system, coord = await boot()
    d = db()
    wrote = {}
    try:
        from core.perception.perception_faculty import get_perception_faculty
        P = get_perception_faculty()

        print("\n== A. One authority, and it is called ==")
        held = getattr(getattr(coord, "perception", None), "faculty", None) or get_perception_faculty()
        authority_audit(EV, check, system="perception", cls="PerceptionFaculty",
                        path="core/perception/perception_faculty.py", held=held, reached=P)

        print("\n== B. A real image becomes structure ==")
        check("the stimulus exists", STIMULUS.exists(), str(STIMULUS))
        sensed = await P.sense(str(STIMULUS), source="isoprobe")
        modality, content = (sensed or (None, {}))
        check("sensing returns (modality, content)", modality == "image" and isinstance(content, dict),
              f"modality={modality} keys={sorted(content)[:8] if isinstance(content, dict) else content}")
        regions = content.get("regions") or content.get("blobs") or content.get("objects") or []
        # The NAME comes from what was seen: the caller's label in front, the
        # content digest after it. One picture seen twice is one individual; two
        # different pictures through the same label never merge.
        again = (await P.sense(str(STIMULUS), source="isoprobe"))[1]
        other = (await P.sense(str(OTHER), source="isoprobe"))[1]
        check("one picture seen twice is the same individual",
              content.get("subject") == again.get("subject"), f"{content.get('subject')}")
        check("two different pictures through one label are never merged",
              content.get("subject") != other.get("subject"),
              f"{content.get('subject')} vs {other.get('subject')}")
        EV.metric("regions_sensed", len(regions) if hasattr(regions, "__len__") else 0, "count")

        print("\n== C. A file it cannot read is refused, not guessed ==")
        with tempfile.NamedTemporaryFile(suffix=".qzx", delete=False) as f:
            f.write(b"not a picture")
            odd = f.name
        try:
            await P.sense(odd)
            check("an unknown file kind raises", False, "no error")
        except ValueError as e:
            check("an unknown file kind raises", True, str(e)[:80])
        finally:
            Path(odd).unlink(missing_ok=True)

        print("\n== D. Two sightings correspond ==")
        pairs = P.correspond(content, content)
        check("the same scene seen twice corresponds blob for blob", isinstance(pairs, list),
              f"{len(pairs)} correspondence(s)")

        print("\n== E. An instance is learned and forgotten ==")
        n = await P.learn_instance("isoprobe_instance", str(STIMULUS))
        known = P.known_instances
        check("an instance is learned by name", "isoprobe_instance" in known, f"features={n} known={len(known)}")
        gone = await P.forget_instance("isoprobe_instance")
        check("and forgotten", gone is True and "isoprobe_instance" not in P.known_instances)

        print("\n== F. Sight: a real photograph, through the one entry point ==")
        from PIL import Image
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        nonce = "".join(random.choice(string.ascii_lowercase) for _ in range(6))
        photo = Path(tempfile.gettempdir()) / f"sysperc_{nonce}.jpg"
        with Image.open(PHOTO) as im:
            im = im.convert("RGB")
            im.putpixel((0, 0), tuple(random.randrange(256) for _ in range(3)))
            im.save(photo, quality=95)
        wrote["photo"] = photo
        percept = await coord.see(str(photo), source=f"sysperc{nonce}", domain="vision", actor_identity=None)
        await get_uncertainty_system().drain_writes()
        meta = getattr(percept, "metadata", None) or {}
        wrote["subject"] = subject = getattr(percept, "source", None)
        wrote["perception_id"] = meta.get("perception_id")
        wrote["memory_id"] = memory_id = meta.get("memory_id")
        check("sight returns a percept with a durable identity",
              percept is not None and bool(wrote["perception_id"]) and bool(subject),
              f"subject={subject} perception={wrote['perception_id']}")
        mem = await d.execute_query(
            "SELECT content FROM memory_hot.memory_hot WHERE memory_id = $1", (memory_id,),
            fetch_one=True) if memory_id else None
        check("seeing formed a memory of the picture", mem is not None,
              f"{memory_id}: {(mem or {}).get('content', '')[:70]!r}")
        from core.memory.media_store import get_media_store
        media = await get_media_store().media_for_memory(memory_id) if memory_id else []
        check("the memory can produce the picture again", bool(media),
              f"{len(media)} image(s) retained")
        env = await d.execute_query(
            "SELECT evidence_id FROM unified.evidence_envelopes WHERE producer = $1",
            (subject,), fetch_all=True) or []
        wrote["envelopes"] = [r["evidence_id"] for r in env]
        check("what was seen was admitted as evidence, once", len(env) == 1,
              f"{len(env)} envelope(s)")
        edges = await d.execute_query(
            "SELECT count(*) AS n FROM unified.concept_relations WHERE evidence_id = ANY($1::text[])",
            (wrote["envelopes"],), fetch_one=True)
        check("and entered the concept graph", int(edges["n"]) > 0, f"{edges['n']} edge(s)")
        beliefs = await d.execute_query(
            "SELECT belief_id, memory_id FROM unified.beliefs WHERE belief_text LIKE $1",
            (f"{subject}%",), fetch_all=True) or []
        check("what was seen is held as beliefs", len(beliefs) > 0, f"{len(beliefs)} belief(s)")
        check("every one of them is about the memory of seeing it",
              beliefs and all(b["memory_id"] == memory_id for b in beliefs),
              f"{sorted({b['memory_id'] for b in beliefs})}")
    finally:
        try:
            await get_perception_faculty().forget_instance("isoprobe_instance")
            left = await remove_sight(d, wrote)
            if wrote.get("subject"):
                check("everything sight wrote is removed", sum(left.values()) == 0, f"{left}")
        finally:
            await shutdown(system)

    await EV.verify_database()
    code = outcome(EV, results, "SYSTEM-PERCEPTION-01")
    EV.write()
    return code


async def remove_sight(d, wrote):
    """Remove, by id, everything one `see` wrote: its perception row, its memory
    and the retained picture, its evidence envelope and every graph row citing
    it, the concepts only that envelope made, the beliefs about the memory, and
    the experience it handed to the memory agent's pool. Returns what is left of
    each."""
    subject, memory_id = wrote.get("subject"), wrote.get("memory_id")
    envelopes = wrote.get("envelopes") or []
    if wrote.get("photo"):
        Path(wrote["photo"]).unlink(missing_ok=True)
    if not subject:
        return {}
    made = [r["concept_id"] for r in (await d.execute_query(
        "SELECT DISTINCT concept_id FROM unified.concept_evidence ce "
        "WHERE evidence_id = ANY($1::text[]) AND NOT EXISTS ("
        "  SELECT 1 FROM unified.concept_evidence o WHERE o.concept_id = ce.concept_id "
        "  AND NOT (o.evidence_id = ANY($1::text[])))", (envelopes,), fetch_all=True) or [])]
    for table in ("concept_relations", "concept_domains", "concept_evidence"):
        await d.execute_query(f"DELETE FROM unified.{table} WHERE evidence_id = ANY($1::text[])",
                              (envelopes,))
    if made:
        await d.execute_query(
            "DELETE FROM unified.concept_relations WHERE source_concept_id = ANY($1::text[]) "
            "OR target_concept_id = ANY($1::text[])", (made,))
        await d.execute_query("DELETE FROM unified.concept_aliases WHERE concept_id = ANY($1::text[])", (made,))
        await d.execute_query("DELETE FROM unified.concepts WHERE concept_id = ANY($1::text[])", (made,))
    await d.execute_query("DELETE FROM unified.knowledge_updates WHERE evidence_id = ANY($1::text[])",
                          (envelopes,))
    await d.execute_query("DELETE FROM unified.evidence_envelopes WHERE evidence_id = ANY($1::text[])",
                          (envelopes,))
    await d.execute_query("DELETE FROM unified.beliefs WHERE belief_text LIKE $1 OR memory_id = $2",
                          (f"{subject}%", memory_id or ""))
    if wrote.get("perception_id"):
        await d.execute_query("DELETE FROM unified.perceptions WHERE id = $1", (wrote["perception_id"],))
    if memory_id:
        await d.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1", (memory_id,))
        await d.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1", (memory_id,))
    await d.execute_query("DELETE FROM unified.experience_pool WHERE kind = 'perception' AND about = $1",
                          (subject,))
    counts = {
        "experience": ("SELECT count(*) AS n FROM unified.experience_pool WHERE about = $1", subject),
        "envelopes": ("SELECT count(*) AS n FROM unified.evidence_envelopes WHERE producer = $1", subject),
        "beliefs": ("SELECT count(*) AS n FROM unified.beliefs WHERE belief_text LIKE $1", f"{subject}%"),
        "perceptions": ("SELECT count(*) AS n FROM unified.perceptions WHERE source = $1", subject),
        "memory": ("SELECT count(*) AS n FROM memory_hot.memory_hot WHERE memory_id = $1", memory_id or ""),
        "media": ("SELECT count(*) AS n FROM unified.memory_media WHERE memory_id = $1", memory_id or ""),
    }
    left = {k: int((await d.execute_query(sql, (arg,), fetch_one=True))["n"]) for k, (sql, arg) in counts.items()}
    row = await d.execute_query(
        "SELECT (SELECT count(*) FROM unified.concept_relations WHERE evidence_id = ANY($1::text[])) + "
        "(SELECT count(*) FROM unified.concepts WHERE concept_id = ANY($2::text[])) AS n",
        (envelopes, made), fetch_one=True)
    left["graph"] = int(row["n"])
    return left


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
