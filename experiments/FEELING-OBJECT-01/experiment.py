#!/usr/bin/env python3
"""FEELING-OBJECT-01 — can the substrate say WHAT it feels about, and does a
doubt that fades leave its question behind?

Two gaps in alleviation, closed together because the second needs the first.

  THE FIRST GAP — a feeling with no object.
  Three ways a feeling could be relieved existed: its constituents moving
  (`doubt = (1−confidence) + epistemic_opportunity + risk` falls when confidence
  rises), time (the emotion fades on a half-life), and nothing else — there is
  deliberately no setter, so the substrate cannot relieve itself by deciding to.
  The fourth way, ADDRESSING WHAT THE FEELING IS ABOUT, was unreachable, because
  nothing named the object. `attribution` names WHY an outcome went as it did and
  is fed only by `outcome_class`, so outside a task it is None. `ThreatSense` has
  always carried a subject and a detail per event, and only the scalar magnitude
  ever left it — the same defect shape this codebase already names for bearing:
  "a famine ... and a file has a `.txt` extension arrived here as the same shape,
  differing only in magnitude."

  THE SECOND GAP — a doubt that fades is a question being dropped.
  Fading is alleviation by TIME, and for satisfaction that is harmless: it was
  about something finished. Doubt is not symmetric with it. Doubt is an open
  question wearing a feeling, and letting the feeling lapse with nothing recorded
  means the substrate stopped wondering about something it never settled —
  strictly worse than staying uncertain, because the uncertainty stops being
  visible to the machinery that exists to resolve it.

  A  THE THREAT NAMES WHAT, NOT ONLY HOW MUCH   dominant() tracks the live driver
  B  THE OBJECT REACHES APPRAISAL               state.about / about_domain
  C  THE FEELING CARRIES IT                     affect_state().about
  D  IT SURVIVES A RESTART                      persisted and rehydrated
  E  THE SUBSTRATE CAN SAY IT                   in its own words, about ≠ why
  F  A FADED DOUBT LEAVES ITS QUESTION          registered, and idempotent
  G  NO OBJECT ⇒ NO QUESTION                    counted as lost, never invented
  H  THE OBJECT IS NOT ERASED BY A PARTIAL UPDATE

Run: ./venv_lyric/bin/python3 experiments/FEELING-OBJECT-01/experiment.py
"""
import asyncio
import contextlib
import io
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
logging.disable(logging.CRITICAL)

sys.path.insert(0, str(HERE.parent))
from experiments._evidence import RunRecord  # noqa: E402

EV = RunRecord(
    "FEELING-OBJECT-01",
    claim=("An emotion can name WHAT it is about, and a doubt that fades leaves "
           "its question behind as a known-unknown."),
    hypothesis=("If the object of a feeling is named by whoever met it and "
                "carried onto the appraisal, then alleviation by addressing the "
                "cause becomes reachable — and a doubt that only fades stops "
                "being a question the substrate silently drops."))

results = []
SUBJECT = "feeling_object_01.probe_module"


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""),
          flush=True)


def open_questions(unc):
    return {(u.question, u.domain) for u in unc.known_unknowns.values()}


async def main() -> int:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.main import get_system
        system = get_system()
        await system.start()
        coord = system.autonomous_coordinator
        from core.database import get_database_manager
        db = get_database_manager()
    from core.agents.autonomous.appraisal import AppraisalState
    from core.reasoning.bayesian_uncertainty import get_bayesian_uncertainty

    threat = coord.threat
    ims = coord.intrinsic_motivation
    unc = get_bayesian_uncertainty()

    print("\n== A. The threat names WHAT it is about, not only how much ==")
    check("nothing met has no object either",
          threat.dominant() is None, f"dominant()={threat.dominant()}")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        # Real events through the real door. A refusal weighs 0.25, an integrity
        # finding 1.00, so the dominant one must flip to the integrity finding.
        await threat.note("refusal", "feeling_object_01.minor", "a law stopped an act")
        first = threat.dominant()
        await threat.note("integrity", SUBJECT, "the judging machinery was changed")
        second = threat.dominant()
    check("the only event met IS the dominant one",
          first is not None and first.subject == "feeling_object_01.minor",
          f"{getattr(first, 'kind', None)}:{getattr(first, 'subject', None)}")
    # Same arithmetic `level()` sums, so what it says it is worried about is by
    # construction what is actually driving the worry.
    check("the heavier event becomes what the worry is about",
          second is not None and second.kind == "integrity"
          and second.subject == SUBJECT,
          f"{getattr(second, 'kind', None)}:{getattr(second, 'subject', None)} "
          f"at felt={threat.level():.4f}")
    check("status() reports it", threat.status().get("about") == f"integrity:{SUBJECT}",
          str(threat.status().get("about")))

    print("\n== B. The object reaches appraisal ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await coord._refresh_motivation_signals()
    state = coord.appraisal.current_state
    check("appraisal's `about` is measured", state.about == f"integrity:{SUBJECT}",
          f"about={state.about!r}")
    check("and it is filed in the domain the memory went to",
          state.about_domain == "substrate_safety", f"{state.about_domain!r}")
    check("`about` is not `attribution` — the two answer different questions",
          "about" not in (state.attribution or ""),
          f"attribution={state.attribution!r} about={state.about!r}")

    print("\n== H. A partial update does not erase the object ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        coord.appraisal.update(epistemic={"information_gain": 0.4})
    check("the object survives an update that says nothing about it",
          coord.appraisal.current_state.about == f"integrity:{SUBJECT}",
          f"about={coord.appraisal.current_state.about!r}")

    print("\n== C. The feeling carries it ==")
    # Real signals through the real builder: high risk + open questions + no
    # confidence is what doubt IS. Nothing is injected into the emotion.
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        coord.appraisal.update(
            risk_level="critical",
            concerns=f"integrity:{SUBJECT}", concerns_domain="substrate_safety",
            epistemic={"information_gain": 0.8, "uncertainty_increase": 0.9})
        felt = await ims.update_affect()
    check("the substrate feels doubt", felt.emotion == "doubt",
          f"emotion={felt.emotion} intensity={felt.intensity}")
    check("and it knows what the doubt is about",
          felt.about == f"integrity:{SUBJECT}", f"about={felt.about!r}")

    print("\n== D. It survives a restart ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        row = await db.execute_query(
            "SELECT emotion, about, about_domain FROM unified.affect_state WHERE id=1",
            fetch_one=True)
    check("the object is durable, like the feeling it belongs to",
          row is not None and row["about"] == f"integrity:{SUBJECT}"
          and row["about_domain"] == "substrate_safety",
          f"stored about={(row['about'] if row else None)!r}")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        ims._affect_about = ims._affect_about_domain = None      # as a cold process
        await ims._load_affect()
    check("and it rehydrates", ims._affect_about == f"integrity:{SUBJECT}",
          f"rehydrated about={ims._affect_about!r}")

    print("\n== E. The substrate can SAY what it feels about ==")
    said = coord._describe_attitude(coord._attitude())
    check("it names the object, not the outcome class",
          said is not None and SUBJECT in said, said or "(said nothing)")
    print(f"      it says: {said}")

    print("\n== F. A doubt that fades leaves its question behind ==")
    before_q = open_questions(unc)
    question = f"what is unresolved about integrity:{SUBJECT}?"
    check("the question is not already open", (question, "substrate_safety") not in before_q)
    # Two hours pass with nothing supporting the feeling. The appraisal is set to
    # a genuinely UNMEASURED state — which is what the substrate is in outside a
    # task, and is exactly when the fade branch runs.
    saved_state = coord.appraisal.current_state
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        coord.appraisal.current_state = AppraisalState()
        ims._last_affect_at = ims._last_affect_at - timedelta(hours=2)
        faded = await ims.update_affect()
    check("the feeling is gone", faded.emotion is None and faded.about is None,
          f"emotion={faded.emotion} about={faded.about}")
    after_q = open_questions(unc)
    check("but the QUESTION is not", (question, "substrate_safety") in after_q,
          f"+{len(after_q - before_q)} open question(s)")
    check("it was counted honestly", ims._questions_kept == 1,
          f"kept={ims._questions_kept} lost={ims._questions_lost}")
    # One open question, not a pile: a doubt that recurs and fades repeatedly is
    # the same unsettled thing.
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        coord.appraisal.update(
            risk_level="critical",
            concerns=f"integrity:{SUBJECT}", concerns_domain="substrate_safety",
            epistemic={"information_gain": 0.8, "uncertainty_increase": 0.9})
        await ims.update_affect()
        coord.appraisal.current_state = AppraisalState()
        ims._last_affect_at = ims._last_affect_at - timedelta(hours=2)
        await ims.update_affect()
    check("fading again does not pile up duplicates",
          len(open_questions(unc) - before_q) == 1 and ims._questions_kept == 1,
          f"{len(open_questions(unc) - before_q)} question(s), kept={ims._questions_kept}")

    print("\n== G. No object ⇒ no question, never an invented one ==")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        coord.appraisal.current_state = AppraisalState()
        coord.appraisal.update(
            risk_level="high",
            epistemic={"information_gain": 0.8, "uncertainty_increase": 0.9})
        anon = await ims.update_affect()
        anon_emotion, anon_about = anon.emotion, anon.about
        coord.appraisal.current_state = AppraisalState()
        ims._last_affect_at = ims._last_affect_at - timedelta(hours=2)
        await ims.update_affect()
    check("a doubt with nothing naming it still fades",
          anon_emotion == "doubt" and anon_about is None,
          f"emotion={anon_emotion} about={anon_about}")
    check("and NO question is invented for it",
          len(open_questions(unc) - before_q) == 1 and ims._questions_lost == 1,
          f"lost={ims._questions_lost} (counted, not hidden)")

    # ── restore and clean up what this run created ────────────────────────
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        coord.appraisal.current_state = saved_state
        for uid in [u.unknown_id for u in list(unc.known_unknowns.values())
                    if SUBJECT in u.question]:
            unc.known_unknowns.pop(uid, None)
            with contextlib.suppress(Exception):
                await db.execute_query(
                    "DELETE FROM unified.known_unknowns WHERE unknown_id=$1",
                    (uid,), commit=True)
        with contextlib.suppress(Exception):
            await db.execute_query(
                "DELETE FROM unified.beliefs WHERE domain=$1 AND claim LIKE $2",
                ("substrate_safety", f"%{SUBJECT}%"), commit=True)

    passed, total = sum(results), len(results)
    print(f"\n==== FEELING-OBJECT-01: {passed}/{total} checks passed ====\n")
    EV.metric("questions_kept", ims._questions_kept, "known-unknowns")
    EV.metric("questions_lost", ims._questions_lost, "doubts with no object")
    EV.note(f"the substrate said: {said}")
    record = EV.write()
    print(f"  run record: {record.name} (+ .md)")
    sys.stdout.flush()
    os._exit(0 if passed == total else 1)


asyncio.run(main())
