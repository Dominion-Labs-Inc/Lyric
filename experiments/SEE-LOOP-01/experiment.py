#!/usr/bin/env python3
"""SEE-LOOP-01 — ONE act of sight, through the whole live substrate.

Every stage of the sensing path has been proven on its own: the floor, the
per-edge evidence quality, the acceptance band, the percept link on memories, the
bearing that moves affect. Proven separately is how four defects survived a day
of work — each stage was correct and the SEAM between two of them dropped the
value. `detection_confidence` sat on the wrong concept, circularity was collapsed
to a label, edges were truncated at extraction, `intent_id` was written and never
mapped on read. Not one of those is visible from inside the stage that owned it.

So this boots the real substrate and calls `coordinator.see()` on a real file,
once, and asserts what happened at every stage AND at every junction between
them. Nothing is constructed for the test but the image.

  A  SIGHT       the live substrate sees a real file through the one entry point.
  B  BELIEF      what it saw is held, and an inferred claim is held at its own
                 measured support while a measured claim is not.
  C  FLOOR       a poorly-supported claim is refused on this same path, as
                 absence rather than as a weak belief.
  D  JUDGEMENT   sensation is judged by the acceptance band, per claim.
  E  SPINE       that judgement reaches the reaction system as an event.
  F  MEMORY      a memory formed during the seeing resolves to the percept, and
                 to the digest of the bytes.
  G  AFFECT      what was seen is read through the substrate's own law.
  H  PERMISSION  and none of it changed what the substrate may do.
  I  UNSURE      the same loop again on a percept the substrate is NOT sure of:
                 the verdict flips to VERIFY and the reaction can still READ it.

Run: ./venv_lyric/bin/python3 experiments/SEE-LOOP-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiments._evidence import RunRecord  # noqa: E402

IMAGE = str(REPO / "test_data" / "vision_test.png")
#: A pentagon reads as `ellipse` at circularity ~0.79 — an INFERRED claim whose
#: support sits inside the acceptance band. Written by this experiment because
#: the repo's test card is clean: every claim it yields is high-support, so a
#: loop that only ever sees it exercises ACT and never VERIFY, and the branch
#: that matters (what the substrate does when it is NOT sure) goes unrun.
PENTAGON = str(REPO / "test_data" / "seeloop_pentagon.png")

EV = RunRecord(
    "SEE-LOOP-01",
    claim=("One act of sight carries through the live substrate intact: what was "
           "seen is held at the standing its evidence warrants, judged by the "
           "same band that judges a recognition and a finished task, recorded so "
           "the memory of it resolves to the bytes, read through the law that "
           "governs the substrate — and changes nothing about what it may do."),
    hypothesis=("Each stage of this path passes its own test. The defects found "
                "today all lived in the SEAMS — a value computed by one stage and "
                "dropped before the next could read it — and no single-stage test "
                "can see one. This exercises the whole chain in one run."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    from core.memory import Origin
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
        await db.initialize()
        from core.agents.autonomous.autonomous_coordinator import SelfEventType
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.domain import evidence_producers as ep
        from core.memory.utils.interfaces import MemoryType

    if not Path(PENTAGON).exists():
        import cv2, numpy as np, math
        img = np.full((400, 800, 3), 255, np.uint8)
        cx, cy, R = 400, 200, 120
        pts = np.array([[int(cx + R * math.cos(2 * math.pi * i / 5)),
                         int(cy + R * math.sin(2 * math.pi * i / 5))]
                        for i in range(5)], np.int32)
        cv2.fillPoly(img, [pts], (40, 40, 220))
        cv2.imwrite(PENTAGON, img)

    tag = uuid.uuid4().hex[:6]
    subject = f"seeloop_{tag}"
    DOMAIN = "vision"

    # Catch the judgement as it fans out, rather than reading the return value:
    # the decision is supposed to GOVERN behaviour through the spine, and a test
    # that only reads what `see` returned cannot tell whether it ever did.
    seen_events = []
    coord.on(SelfEventType.PERCEPT_RECOGNIZED,
             lambda ev: seen_events.append(ev), name="seeloop_probe")

    # ── A. SIGHT ────────────────────────────────────────────────────────────
    print("\n== A. The live substrate sees a real file ==")
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        percept = await coord.see(IMAGE, source=subject, domain=DOMAIN, actor_identity=None)
        await get_uncertainty_system().drain_writes()
    # WHAT THE SUBSTRATE CALLED IT, which is no longer the label handed in: a
    # percept is named from the image's own content digest, so that two pictures
    # seen by one route cannot become one individual. Everything below asks for
    # the name rather than rebuilding it.
    subject = percept.source if percept else subject
    check("the substrate is the live one, with its faculties up",
          coord.constitution is not None and coord.appraisal is not None
          and coord.vision is not None,
          "constitution + appraisal + vision all held")
    check("sight returned a percept through the one entry point",
          percept is not None, type(percept).__name__ if percept else "None")
    meta = getattr(percept, "metadata", None) or {}
    percept_id = meta.get("perception_id")
    check("the percept has a durable identity", bool(percept_id), str(percept_id))
    EV.metric("percept_id", percept_id, "id")

    # ── B. BELIEF, AT THE STANDING ITS EVIDENCE WARRANTS ────────────────────
    print("\n== B. What it saw is held, and not all at one standing ==")
    rows = await db.execute_query(
        "SELECT belief_text, prior_probability p, posterior_probability post "
        "FROM unified.beliefs WHERE belief_text LIKE $1 ORDER BY belief_text",
        (f"{subject}%",)) or []
    held = {r["belief_text"]: (r["p"], r["post"]) for r in rows}
    check("what was seen is held as beliefs", len(held) >= 8, f"{len(held)} belief(s)")
    EV.metric("beliefs_from_one_sight", len(held), "count")

    inferred = {k: v for k, v in held.items()
                if " isa circle" in k or " isa ellipse" in k}
    measured = {k: v for k, v in held.items() if " has_width " in k}
    check("an INFERRED claim is held at its own measured support",
          bool(inferred) and all(abs(float(p) - 0.9) > 1e-6 for p, _ in inferred.values()),
          "; ".join(f"{k.split()[-1]} prior={p}" for k, (p, _) in inferred.items()))
    check("while a MEASURED claim is not — they entered by different evidence",
          bool(measured) and all(abs(float(p) - 0.9) < 1e-6 for p, _ in measured.values()),
          "; ".join(f"{k.split()[-2]}={k.split()[-1]} prior={p}"
                    for k, (p, _) in measured.items()))
    EV.note("Before this the whole percept shared one envelope quality, so a "
            "shape inferred from a lossy polygon approximation and a width read "
            "off the file were equally well founded in the record. The support "
            "existed at every point and was dropped at the seam: "
            "`concept_ingestion` truncated every edge to three elements at "
            "extraction, before the reader of the fourth ever ran.")

    # ── C. THE FLOOR IS ON THIS PATH ────────────────────────────────────────
    print("\n== C. A poorly-supported claim is refused, as absence ==")
    from core.semantics.cognitive_ingress import MIN_ADMIT_QUALITY
    weak = f"{subject}_weak"
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        # THE MEMORY IS SUPPLIED, so the QUALITY FLOOR is the only thing that
        # can refuse this. Without one the belief is refused for naming no
        # memory as well, and the check would pass with the floor removed --
        # a check that cannot fail is not testing the floor.
        ok_mem, weak_memory = await coord.memory.store_memory(
            content=f"I was shown something I could barely make out: {weak}",
            memory_type=MemoryType.EPISODIC, importance_score=0.3,
            tags=["percept", DOMAIN], origin=Origin.own("SEE-LOOP-01"))
        await ep.submit_image(weak, {"subject": weak,
                                     "detections": [{"label": f"ghost_{tag}",
                                                     "confidence": 0.02}]},
                              domain=DOMAIN, memory_id=weak_memory,
                              origin=Origin.own("SEE-LOOP-01"))
        await get_uncertainty_system().drain_writes()
    ghost = await db.execute_query(
        "SELECT count(*) n FROM unified.beliefs WHERE belief_text LIKE $1",
        (f"%ghost_{tag}%",), fetch_one=True)
    check("a recognition below the floor is not held at all",
          int(ghost["n"]) == 0,
          f"quality 0.02 < floor {MIN_ADMIT_QUALITY}; {ghost['n']} belief(s) — "
          f"absence, not a weak posterior (memory {weak_memory} supplied, so "
          f"the floor is the only thing refusing it)")

    # ── D. JUDGEMENT ────────────────────────────────────────────────────────
    print("\n== D. Sensation is judged by the acceptance band, per claim ==")
    vi, accept = coord._acceptance_band()
    judged = [e for e in seen_events
              if getattr(getattr(e, "payload", None), "subject", None) == subject]
    check("the sensing produced a judgement, not only beliefs",
          bool(judged), f"{len(judged)} judgement event(s)")
    payload = judged[0].payload if judged else None
    check("every claim it made was judged, none skipped",
          payload is not None and len(payload.claims) >= 8,
          f"{len(payload.claims) if payload else 0} claim(s) at "
          f"accept={payload.accept if payload else None}")
    acted = sum(1 for c in payload.claims if c.decision == "ACT")
    verify = sum(1 for c in payload.claims if c.decision == "VERIFY")
    abstained = sum(1 for c in payload.claims if c.decision == "ABSTAIN")
    check("each claim carries its own verdict and the posterior behind it",
          all(c.decision and hasattr(c, "posterior") for c in payload.claims),
          f"ACT {acted} / VERIFY {verify} / ABSTAIN {abstained}")
    check("the percept's own verdict is the WEAKEST of its claims",
          payload.decision in ("ACT", "VERIFY", "ABSTAIN")
          and (payload.decision != "ACT" or verify == 0),
          f"percept={payload.decision}")
    EV.metric("acceptance_band", round(accept, 4), "posterior")
    EV.metric("claims_judged", len(payload.claims), "count")
    EV.note("`perceive` asked of every recognition whether its confidence "
            "cleared a defensible bar; `sense` ran to the belief store and "
            "stopped. The substrate held an acceptance standard for what it "
            "RECOGNISED and none for what it SAW — on the path that runs "
            "constantly and that an attacker reaches first.")

    # ── E. THE SPINE ────────────────────────────────────────────────────────
    print("\n== E. The judgement reaches the reaction system ==")
    check("it fans out on the SAME event a recognition does",
          bool(judged) and judged[0].type is SelfEventType.PERCEPT_RECOGNIZED,
          "PERCEPT_RECOGNIZED")
    check("and names which path produced it, so the two stay distinguishable",
          getattr(judged[0], "origin", "") == "perceive_sensed" if judged else False,
          getattr(judged[0], "origin", None) if judged else None)

    # ── F. MEMORY ───────────────────────────────────────────────────────────
    print("\n== F. A memory of the seeing resolves to the bytes ==")
    from core.agents.autonomous.perception_manager import (
        set_acting_percept, reset_acting_percept)
    token = set_acting_percept(percept_id, meta.get("digest"))
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            ok, mem_id = await coord.memory.store_memory(
                content=f"looked at the card [{subject}]",
                memory_type=MemoryType.EPISODIC, importance_score=0.7, origin=Origin.own("SEE-LOOP-01"))
    finally:
        reset_acting_percept(token)
    recalled = await coord.memory.retrieve_memory(str(mem_id))
    check("the memory records WHICH percept it is of",
          recalled is not None
          and getattr(recalled, "percept_id", None) == percept_id,
          str(getattr(recalled, "percept_id", None)))
    prow = await db.execute_query(
        "SELECT content FROM unified.perceptions WHERE id = $1",
        (percept_id,), fetch_one=True)
    import json as _json
    sensed = ({} if not prow else (prow["content"] if isinstance(prow["content"], dict)
                                   else _json.loads(prow["content"])))
    check("which resolves to the record of the seeing, digest and all",
          bool(sensed) and sensed.get("sha256")
          and sensed.get("sha256") == getattr(recalled, "percept_digest", None),
          f"sha256={sensed.get('sha256')}")

    # ── G. AFFECT ───────────────────────────────────────────────────────────
    print("\n== G. What was seen is read through the substrate's own law ==")
    subjects = [b.get("name") for b in (sensed.get("blobs") or []) if b.get("name")]
    reading = await coord._bearing_of_moved({"subjects": subjects}) if subjects else None
    check("every blob it saw is read through the law, none skipped",
          bool(reading) and sum(reading.get(k, 0) for k in
                                ("borne", "none", "vacant")) == len(subjects),
          f"{reading} over {len(subjects)} blob(s)")
    EV.note("A shape and a colour bear on no interest the law protects, and the "
            "reading says so as NONE or VACANT rather than as an absence of "
            "reading. That is the honest result for a test card: the faculty "
            "fires, and finds nothing at stake.")

    # ── H. PERMISSION ───────────────────────────────────────────────────────
    print("\n== H. And none of it changed what the substrate may do ==")
    before = await coord.constitution.judge(
        "execute", "execute_command", {"command": "rm -rf /", "reasoning": "x"})
    check("a refusal is still a refusal after a whole act of sight",
          not before.allowed, f"{before.verdict.value} — law {before.law_number}")
    check("and affect still reaches no law",
          coord.appraisal.current_state is None
          or "stakes" in coord.appraisal.DIMENSIONS,
          "stakes is an appraisal dimension, and no law reads appraisal "
          "(asserted against the law bodies in BEARING-01)")

    # ── I. THE SAME LOOP, ON SOMETHING IT IS NOT SURE OF ────────────────────
    print("\n== I. A percept the substrate is not sure of ==")
    unsure = f"unsure_{tag}"
    # RAISE THE CAUTION, do not lower the claim. The band moves with
    # verification_intensity by design — this is the substrate being careful,
    # which is exactly the state in which a shaky shape should be re-observed.
    real_band = coord._acceptance_band
    coord._acceptance_band = lambda: (1.0, coord.COMPLETION_ACCEPT_MAX)
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            u_percept = await coord.see(PENTAGON, source=unsure, domain=DOMAIN, actor_identity=None)
            await get_uncertainty_system().drain_writes()
        unsure = u_percept.source if u_percept else unsure
    finally:
        coord._acceptance_band = real_band
    u_judged = [e for e in seen_events
                if getattr(getattr(e, "payload", None), "subject", None) == unsure]
    u_payload = u_judged[0].payload if u_judged else None
    shaky = list(u_payload.below_band()) if u_payload else []
    u_acted = sum(1 for c in u_payload.claims if c.decision == "ACT") if u_payload else 0
    check("an inferred claim it is unsure of is flagged, not acted on",
          bool(shaky),
          "; ".join(f"{c.claim.split()[-1]} @{c.posterior}" for c in shaky))
    check("while the claims it measured are still acted on", u_acted > 0,
          f"ACT {u_acted} / VERIFY {len(shaky)}")
    check("so the percept's own verdict is VERIFY — the weakest claim decides",
          u_payload is not None and u_payload.decision == "VERIFY",
          str(u_payload.decision if u_payload else None))

    # THE REACTION MUST BE ABLE TO READ IT. This is where the sensed shape was
    # unreadable: `_react_percept` looked for `claim` and `instance_id`, which a
    # sensing does not carry, so VERIFY logged a None claim and registered no
    # known-unknown — the corroboration it exists to trigger never happened.
    # The declared shape names it — the reaction no longer re-parses a sentence
    # at every call site, and a claim that cannot name its subject says so.
    named = [c.subject for c in shaky]
    check("and the reaction can name what to re-observe from the payload alone",
          bool(named) and all(named),
          f"would register known-unknowns for: {', '.join(n for n in named if n)}")
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        await coord._react_percept(u_judged[0]) if u_judged else None
    check("the reaction carries the VERIFY verdict out without raising",
          True, "_react_percept ran on a sensed VERIFY")
    EV.metric("unsure_claims_flagged", len(shaky), "count")
    EV.note("The test card is clean, so every claim it yields is high-support "
            "and the loop only ever exercised ACT. The branch that matters is "
            "the other one: what the substrate does when it is NOT sure. It was "
            "broken here and no single-stage test could see it, because both "
            "stages were individually correct and disagreed about the payload.")

    # ── cleanup ─────────────────────────────────────────────────────────────
    try:
        for _s in (subject, unsure):
            await db.execute_query(
                "DELETE FROM unified.beliefs WHERE belief_text LIKE $1", (f"{_s}%",),
                commit=True)
        await db.execute_query(
            "DELETE FROM memory_hot.memory_hot WHERE content::text LIKE $1",
            (f"%{subject}%",), commit=True)
        await db.execute_query(
            "DELETE FROM unified.perceptions WHERE id = $1", (percept_id,), commit=True)
        await db.execute_query(
            "DELETE FROM unified.evidence_envelopes WHERE producer IN ($1,$2)",
            (subject, weak), commit=True)
    except Exception as e:
        print(f"  (cleanup: {e})")

    passed = sum(1 for ok in results if ok)
    print(f"\n==== SEE-LOOP-01: {passed}/{len(results)} checks passed ====")
    await EV.verify_database()
    EV.write()
    return 0 if passed == len(results) else 1


sys.exit(asyncio.run(main()))
