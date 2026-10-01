#!/usr/bin/env python3
"""MEMORY-SIGHT-01 — memory knows what it has seen before, by the picture itself.

Every seeing keeps its sight trace (keypoints and a difference hash) and its
gist -- never the photograph -- and the memory agent is asked, by the picture,
whether the same thing was seen before (`MemoryAgent.retrieve`, strategy
`sight`). Boots the real substrate and sees real photographs (UKBench: four
views of each object) through `coordinator.see()`.

  A  KEPT         a seeing keeps its gist and sight trace, never the
                  photograph, and is seen again from memory.
  B  THE PICTURE  the same picture resized and re-encoded is known as seen
                  before: in words, in the graph (`same_thing_as`), believed.
  C  ANOTHER VIEW the same object from another view is known as seen before.
  D  ANOTHER      a different object is not.
  E  RETRIEVE     memory's own recall finds a seeing by the picture.
  F  NAMED LATER  shown the thing later, told what it is: the earlier seeing
                  is said to show it, and a new view of it is known by name.
  G  INJECTED     the same thing's memories are injected, saying so.
  H  WHOSE        a person's seeing is recalled only for that person.

Run (sandbox store): ./venv_lyric/bin/python3 experiments/MEMORY-SIGHT-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import re
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")

from experiments._evidence import RunRecord  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
U = REPO / "test_data" / "vision" / "ukbench" / "full"
VIEW = lambda i: U / f"ukbench{i:05d}.jpg"
FIRST, OTHER_VIEW, THIRD_VIEW = VIEW(0), VIEW(1), VIEW(2)   # object 0
ANOTHER = VIEW(40)                                          # object 10
SHOWN = VIEW(3)                                             # object 0, shown and named
THEIRS, THEIRS_AGAIN = VIEW(100), VIEW(101)                 # object 25

EV = RunRecord(
    "MEMORY-SIGHT-01",
    claim=("The memory agent knows what the substrate has seen before, by the picture itself: "
           "a seeing keeps its gist and sight trace and never the photograph; the same picture "
           "resized and re-encoded, and the same object from another view, are known as seen "
           "before -- in words, in the graph and as a belief; a different object is not; a thing "
           "shown later and named names the earlier seeing and is then known by name; recall by "
           "sight is injected; a person's seeing is recalled only for that person."),
    hypothesis=("H1 the same picture re-encoded is known by its difference hash. H2 another view "
                "of the same object agrees on one geometry (at least 20 keypoints). H3 a different "
                "object does not. H4 naming reaches back. H5 recall by sight respects whose "
                "memories may be seen."))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def build_stimuli() -> Path:
    import cv2
    STIM.mkdir(parents=True, exist_ok=True)
    out = STIM / "first_resized_reencoded.jpg"
    if not out.exists():
        img = cv2.imread(str(FIRST))
        cv2.imwrite(str(out), cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2)),
                    [cv2.IMWRITE_JPEG_QUALITY, 60])
    return out


async def main() -> int:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    await db.assert_database_identity(os.environ["POSTGRES_DATABASE"])
    from core.perception import vision as V
    from core.memory.media_store import get_media_store
    from core.memory import get_memory_agent
    from core.memory.utils.memory_injector import get_memory_injector, InjectionConfig
    from core.domain.evidence_producers import _term_like
    reencoded = build_stimuli()

    tag = uuid.uuid4().hex[:6]
    memory_ids = []
    agent = await get_memory_agent()
    person_a, person_b = f"alex_{tag}", f"blair_{tag}"

    async def see(path, label, who=None):
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.see(str(path), source=f"v{tag}{label}", domain="vision",
                                      actor_identity=who)
            await get_uncertainty_system().drain_writes()
        meta = (percept.metadata or {}) if percept is not None else {}
        if meta.get("memory_id"):
            memory_ids.append(meta["memory_id"])
        return percept, meta.get("memory_id")

    async def edges_of(name):
        rows = await db.execute_query(
            "SELECT cr.relation AS rel, COALESCE(c2.name, cr.target_surface) AS obj "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "LEFT JOIN unified.concepts c2 ON cr.target_concept_id = c2.concept_id "
            "WHERE c1.name = $1", (name,), fetch_all=True) or []
        return {(str(r["rel"]), str(r["obj"])) for r in rows}

    def recalled(percept):
        return [e["memory"] for e in (percept.content.get("seen_before") or [])] if percept else []

    try:
        # ── A. KEPT ─────────────────────────────────────────────────────────
        print("\n== A. A seeing keeps its gist and sight trace, never the photograph ==")
        first, first_id = await see(FIRST, "first")
        kept = await get_media_store().media_for_memory(str(first_id)) if first_id else []
        check("its memory keeps the sight trace and the gist, and no photograph",
              len(kept) == 1 and kept[0]["perceived"].get("kind") == "sight_trace"
              and bool(kept[0]["perceived"].get("gist"))
              and not str(kept[0]["mime"]).startswith("image/")
              and kept[0]["byte_size"] < FIRST.stat().st_size,
              f"{kept[0]['mime']}, {kept[0]['byte_size']} bytes of a {FIRST.stat().st_size}-byte "
              f"photograph" if kept else "nothing kept")
        again = [r for r in await coord.recollect(str(first_id)) if r["kind"] == "image"] \
            if first_id else []
        check("and it is seen again from memory, at its proportions",
              bool(again) and abs(again[0]["pixels"].shape[1] / again[0]["pixels"].shape[0]
                                  - 640 / 480) < 0.02,
              str(again[0]["pixels"].shape) if again else "not seen again")
        check("the first seeing had nothing to recall", not recalled(first), str(recalled(first)))

        # ── B. THE SAME PICTURE ─────────────────────────────────────────────
        print("\n== B. The same picture, resized and re-encoded, is known ==")
        same, _ = await see(reencoded, "reencoded")
        before = (same.content.get("seen_before") or []) if same else []
        check("it is known as the same picture seen before",
              [e["memory"] for e in before] == [first_id] and before[0]["same_picture"]
              and before[0]["support"] == 1.0,
              str([(e["memory"], e["same_picture"], e["support"]) for e in before]))
        caption = same.content.get("caption", "") if same else ""
        check("and says so in words, and when",
              re.search(r"seen before, 1 time\(s\), last on \d{4}-\d{2}-\d{2} \d{2}:\d{2}", caption)
              is not None, caption[-90:])
        link = ("same_thing_as", _term_like(first.source))
        check("the graph holds it: the same thing as the first",
              link in await edges_of(same.source), f"{same.source} {link}")
        belief = await db.execute_query(
            "SELECT belief_text FROM unified.beliefs WHERE belief_text = $1",
            (f"{same.source} same_thing_as {_term_like(first.source)}",), fetch_one=True)
        check("and believes it", belief is not None, str(belief["belief_text"]) if belief else None)

        # ── C. ANOTHER VIEW ─────────────────────────────────────────────────
        print("\n== C. The same object from another view is known ==")
        other_view, _ = await see(OTHER_VIEW, "view")
        found = [(e["memory"], e["agreeing"], e["same_picture"])
                 for e in (other_view.content.get("seen_before") or [])] if other_view else []
        check("both earlier seenings of it are recalled, by their keypoints",
              {m for m, _a, _s in found} == {first_id, memory_ids[1]}, str(found))

        # ── D. ANOTHER ──────────────────────────────────────────────────────
        print("\n== D. A different object is not ==")
        another, _ = await see(ANOTHER, "another")
        check("nothing is recalled", another is not None and not recalled(another),
              str(recalled(another)))

        # ── E. RETRIEVE ─────────────────────────────────────────────────────
        print("\n== E. Memory's own recall finds a seeing by the picture ==")
        probe = V.sight_features(str(THIRD_VIEW))
        by_sight = await agent.retrieve(strategies=["sight"], seen=probe, actor=None, limit=5)
        scores = {m.memory_id: getattr(m, "similarity_score", None) for m in by_sight}
        check("by the picture, with how firmly it agreed",
              first_id in scores and all((s or 0) > 0 for s in scores.values()), str(scores))

        # ── F. NAMED LATER ──────────────────────────────────────────────────
        print("\n== F. Shown later and named, the thing names its earlier seeing ==")
        name = f"green mug {tag}"
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            lesson_id = await coord.learn_thing(name, str(SHOWN), actor_identity=None,
                                                source=f"v{tag}lesson")
            await get_uncertainty_system().drain_writes()
        memory_ids.append(lesson_id)
        media = await get_media_store().media_for_memory(str(lesson_id))
        taught_before = {e["memory"] for e in (media[0]["perceived"].get("seen_before") or [])} \
            if media else set()
        check("the lesson recalled the earlier seenings", first_id in taught_before,
              str(sorted(taught_before)))
        check("and the first picture is now said to show the thing",
              ("observed", _term_like(name)) in await edges_of(first.source),
              f"{first.source} observed {_term_like(name)}")
        third, _ = await see(THIRD_VIEW, "third")
        labels = [d.get("label") for d in (third.content.get("detections") or [])] if third else []
        check("a new view of it is known by name", _term_like(name) in labels, str(labels))

        # ── G. INJECTED ─────────────────────────────────────────────────────
        print("\n== G. The same thing's memories are injected, saying so ==")
        injected = await get_memory_injector().inject_memories(
            query="", config=InjectionConfig(max_memories=5, min_importance_score=0.0),
            actor=None, seen=probe)
        text = injected.formatted_text or ""
        check("they are injected as the same thing seen before",
              first_id in injected.memory_ids and "(seen before: the same" in text, text[:200])

        # ── H. WHOSE ────────────────────────────────────────────────────────
        print("\n== H. A person's seeing is recalled only for that person ==")
        _theirs, theirs_id = await see(THEIRS, "theirs", who=person_a)
        for_b, _ = await see(THEIRS_AGAIN, "forb", who=person_b)
        for_self, _ = await see(THEIRS_AGAIN, "forself", who=None)
        for_a, _ = await see(THEIRS_AGAIN, "fora", who=person_a)
        check("not for another person", theirs_id not in recalled(for_b), str(recalled(for_b)))
        check("nor for the substrate's own", theirs_id not in recalled(for_self),
              str(recalled(for_self)))
        check("but for them", theirs_id in recalled(for_a), str(recalled(for_a)))
    finally:
        _tagged = ("SELECT (SELECT count(*) FROM unified.concepts WHERE name LIKE $1) + "
                   "(SELECT count(*) FROM unified.beliefs WHERE belief_text LIKE $1) + "
                   "(SELECT count(*) FROM memory_hot.memory_hot WHERE content::text LIKE $1) AS n")
        like = f"%{tag}%"
        try:
            written = await db.execute_query(_tagged, (like,), fetch_one=True)
        except Exception as error:
            written = None
            EV.note(f"Could not count this run's rows before cleanup: {error}")
        try:
            await db.execute_query(
                "DELETE FROM unified.concept_relations WHERE source_concept_id IN "
                "(SELECT concept_id FROM unified.concepts WHERE name LIKE $1) "
                "OR target_concept_id IN (SELECT concept_id FROM unified.concepts "
                "WHERE name LIKE $1) OR target_surface LIKE $1", (like,), commit=True)
            await db.execute_query("DELETE FROM unified.concepts WHERE name LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.beliefs WHERE belief_text LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.experience_pool WHERE about LIKE $1",
                                   (like,), commit=True)
            await db.execute_query("DELETE FROM unified.evidence_envelopes "
                                   "WHERE producer LIKE $1 OR source_id LIKE $1",
                                   (like,), commit=True)
            tagged = await db.execute_query(
                "SELECT memory_id FROM memory_hot.memory_hot WHERE content::text LIKE $1 "
                "OR user_id LIKE $1", (like,), fetch_all=True) or []
            for mid in set(map(str, filter(None, memory_ids))) | {str(r["memory_id"]) for r in tagged}:
                await db.execute_query("DELETE FROM unified.memory_media WHERE memory_id = $1",
                                       (mid,), commit=True)
                await db.execute_query("DELETE FROM memory_hot.memory_hot WHERE memory_id = $1",
                                       (mid,), commit=True)
            coord.vision._instances.pop(_term_like(f"green mug {tag}"), None)
            left = await db.execute_query(_tagged, (like,), fetch_one=True)
            EV.note(f"Cleanup by nonce {tag} and exact memory id: "
                    f"{written['n'] if written else 'an uncounted number of'} tagged row(s) "
                    f"written, {left['n']} left.")
        except Exception as error:
            print(f"  (cleanup: {error})")
            EV.note(f"Cleanup failed: {error}")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            coord.vision.close()

    passed = sum(1 for ok in results if ok)
    print(f"\n==== MEMORY-SIGHT-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
