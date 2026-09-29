#!/usr/bin/env python3
"""RECOGNISE-01 — the substrate names what it sees, without being asked.

It could already recognise and did not. Measured on the live system before this
was built: it induced `circle(?X) ∧ vivid_red(?X) → <cat>(?X)` from sight alone,
then saw a fresh red circle, held `circle, large, vivid_red`, and named nothing.
Asked "is that blob a <cat>?" it answered "Yes" and cited the rule. The knowledge
was there the whole time; nothing asked. Recognition existed as a
question-answering capability and not as a consequence of seeing — the same shape
of gap as having to switch your eyes on before you can look.

  A  TAUGHT      a category is learned from what sight admitted, nothing handed over.
  B  REFLEX      a FRESH instance is named by the act of seeing it, unasked.
  C  DERIVATION  the name carries the rule that licensed it, and the substrate
                 answers the question the same way it recognised.
  D  LINEAGE     a name is DERIVED: it declares the observations it rests on and
                 adds support to nothing, so recognising cannot corroborate the
                 rule that recognised.
  E  GROUNDED    a name is never a premise. What the substrate concluded is not
                 read back as a feature, by naming or by induction.
  F  JUDGED      the name is judged by the same acceptance band as everything
                 else the percept claims, and the percept's verdict is the weakest.
  G  SILENCE     a thing that matches nothing is named nothing — and that is
                 distinguishable from having no rules to try.
  H  UNDECIDED   a category whose hypotheses disagree names nothing and becomes a
                 question instead.
  I  DURABLE     a reference instance taught to the faculty survives the process.

Run: ./venv_lyric/bin/python3 experiments/RECOGNISE-01/experiment.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import uuid
from pathlib import Path

for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan",
               "POSTGRES_DATABASE": "lyric_db", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiments._evidence import RunRecord  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 170, 0)}

EV = RunRecord(
    "RECOGNISE-01",
    claim=("The substrate names what it sees at the moment it sees it, from rules "
           "it induced itself, through the same authority that answers a question "
           "about a name — and the name arrives with the derivation that licensed "
           "it, resting on the observations it was read from and on nothing else."),
    hypothesis=("Recognition was a capability the substrate had and never used, "
                "because nothing asked. Making it a reflex closes that, and the "
                "risk it introduces is circularity: a name becoming a feature, a "
                "conclusion becoming its own evidence. Both are closed here by "
                "construction rather than by care."))

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    EV.check(name, bool(ok), detail)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def draw(path: Path, shape: str, colour: str, radius: int) -> None:
    img = np.full((300, 300, 3), 255, np.uint8)
    bgr = COLOURS[colour]
    if shape == "circle":
        cv2.circle(img, (150, 150), radius, bgr, -1)
    else:
        unit = (np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
                if shape == "square"
                else np.array([[0, -1], [-1, 1], [1, 1]], np.float32))
        cv2.fillPoly(img, [(unit * radius + [150, 150]).astype(np.int32)], bgr)
    if not cv2.imwrite(str(path), img):
        raise RuntimeError(f"could not write the stimulus to {path}")


async def main() -> int:
    from core.memory import Origin
    STIM.mkdir(exist_ok=True)
    buf = io.StringIO()
    tag = uuid.uuid4().hex[:6]
    DOMAIN = f"recog{tag}"
    CAT = f"recogcat{tag}"

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.database import get_database_manager
        from core.learning.rule_naming import read_names
        from core.learning.rule_store import get_rule_store
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.reasoning.concept_graph_reasoning import (
            instance_predicates, observed_instance_features)
        from core.agents.autonomous.autonomous_coordinator import SelfEventType
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager()
        await db.initialize()

    seen_events = []
    coord.on(SelfEventType.PERCEPT_RECOGNIZED,
             lambda ev: seen_events.append(ev), name=f"recog_probe_{tag}")

    n = [0]

    async def blob_of(image_name: str) -> str:
        rows = await db.execute_query(
            "SELECT cr.target_surface FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON cr.source_concept_id = c.concept_id "
            "WHERE c.name = $1 AND cr.relation = 'contains'",
            (image_name,), fetch_all=True) or []
        return str(rows[0]["target_surface"]) if rows else ""

    async def see(shape: str, colour: str, radius: int) -> str:
        """Draw it, show it to the live substrate, return the blob it admitted."""
        n[0] += 1
        name = f"recog_{tag}_{n[0]}"
        path = STIM / f"{name}.png"
        draw(path, shape, colour, radius)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.see(str(path), source=name, domain=DOMAIN, actor_identity=None)
            await get_uncertainty_system().drain_writes()
        # ASK THE SUBSTRATE WHAT IT CALLED THE PERCEPT rather than rebuilding
        # the name from the label handed in. The two used to be the same string
        # and are not any more: a percept is named from the image's own content
        # digest, because a caller's label is not an identity.
        return await blob_of(percept.source if percept else name)

    try:
        # ── A. TAUGHT FROM SIGHT ────────────────────────────────────────────
        print("\n== A. A category learned from what sight admitted ==")
        # Seen FIRST, before any rule for CAT exists, so it carries no name and
        # the only way to answer a question about it is to APPLY the rule. This
        # is the reasoner's own door onto the shared naming authority; without
        # it, section C would be answered from the belief the reflex wrote.
        untouched = await see("circle", "red", 88)
        wrong_kind = await see("square", "blue", 58)
        positives = [await see("circle", "red", r) for r in (46, 72)]
        negatives = [await see("square", "red", 58), await see("circle", "blue", 58)]
        check("every example entered through sight, not by hand",
              all(positives) and all(negatives),
              f"{len(positives)} positive(s), {len(negatives)} negative(s)")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            induced = await coord.learning.induce_category(
                CAT, positives=positives, negatives=negatives, domain=DOMAIN)
        check("a naming rule was induced from them",
              induced.rule is not None, str(induced.rule))
        EV.metric("induced_rule", str(induced.rule), "formula")

        # ── B. THE REFLEX ───────────────────────────────────────────────────
        print("\n== B. A fresh instance is named by the act of seeing it ==")
        before = len(seen_events)
        fresh = await see("circle", "red", 88)
        check("sight admitted the fresh thing", bool(fresh), fresh)
        held = await instance_predicates(db, fresh)
        named = [f for f in held if f == CAT]
        check("and NAMED it, with nobody asking", bool(named),
              f"{fresh} isa {CAT}" if named else f"held only {sorted(held)}")
        observed, _ = await observed_instance_features(db, fresh)
        EV.metric("observed_features", len(observed), "count")
        EV.metric("held_features", len(held), "count")

        # ── C. THE DERIVATION TRAVELS WITH IT ───────────────────────────────
        print("\n== C. The name carries what licensed it ==")
        stored = await get_rule_store().load()
        reading = read_names(fresh, observed, stored)
        mine = [x for x in reading.names if x.category == CAT]
        check("the naming authority states the rule that fired",
              bool(mine) and bool(mine[0].body),
              f"{mine[0].body} -> {CAT} ({mine[0].status})" if mine else "none")
        check("and how many hypotheses agreed, not just that one did",
              bool(mine) and mine[0].hypotheses >= 1,
              f"{mine[0].hypotheses} hypothesis/es" if mine else "n/a")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            asked = await coord.reason_about(f"is {fresh} a {CAT}?", origin=Origin.own("RECOGNISE-01"))
        answer = (getattr(asked, "answer", "") or "").strip()
        check("asking gives the SAME answer — one authority, two doors",
              answer.lower().startswith("yes"), answer[:80] or "(no answer)")

        # The reasoner's own door, on a blob the reflex never named.
        untouched_held = await instance_predicates(db, untouched)
        check("a blob seen BEFORE the rule existed carries no name",
              CAT not in untouched_held, untouched)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            applied = await coord.reason_about(f"is {untouched} a {CAT}?", origin=Origin.own("RECOGNISE-01"))
        ans2 = (getattr(applied, "answer", "") or "").strip()
        steps = list(getattr(applied, "reasoning_steps", []) or [])
        check("so the reasoner must APPLY the rule to answer — and does",
              ans2.lower().startswith("yes"), ans2[:70] or "(no answer)")
        check("citing the induced rule as the derivation",
              any("induced rule" in s for s in steps),
              steps[0] if steps else "no steps")
        check("over the OBSERVED features, not what it had concluded",
              any(s.startswith(f"{untouched} is ") and CAT not in s for s in steps),
              next((s for s in steps if s.startswith(f"{untouched} is ")), "n/a"))
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            wrong = await coord.reason_about(f"is {wrong_kind} a {CAT}?", origin=Origin.own("RECOGNISE-01"))
        check("and the wrong kind of thing is not named",
              not (getattr(wrong, "answer", "") or "").lower().startswith("yes"),
              (getattr(wrong, "answer", "") or "(abstained)")[:60])
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            action = await coord.reason_about(f"is {untouched} a TEXT?", origin=Origin.own("RECOGNISE-01"))
        check("an ACTION rule is not reachable as a naming rule",
              not (getattr(action, "answer", "") or "").lower().startswith("yes"),
              "` -> TEXT(?X0) <?X0 := READ()>` is precondition-free and would "
              "name everything")

        # ── D. A NAME IS DERIVED, AND SAYS SO ───────────────────────────────
        print("\n== D. The name rests on the seeing, and corroborates nothing ==")
        rows = await db.execute_query(
            "SELECT ee.source_type, ee.derived_from FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "JOIN unified.evidence_envelopes ee ON ee.evidence_id = cr.evidence_id "
            "WHERE c1.name = $1 AND cr.target_surface = $2",
            (fresh, CAT), fetch_all=True) or []
        src = str(rows[0]["source_type"]) if rows else ""
        check("it entered as a DERIVATION, not as an observation",
              src == "induced_rule", src or "no evidence envelope found")
        import json as _json
        lineage = rows[0]["derived_from"] if rows else "[]"
        lineage = _json.loads(lineage) if isinstance(lineage, str) else (lineage or [])
        check("declaring the observations it was read from",
              len(lineage) > 0, f"{len(lineage)} root(s)")
        # The rule's OWN support must be untouched by having been used.
        roots_now = await get_rule_store().evidence_roots(
            mine[0].rule_id if mine else "")
        check("and the rule it applied gained no support from being applied",
              not (set(lineage) & set(roots_now)),
              f"rule roots {len(roots_now)}, name roots {len(lineage)}, "
              f"overlap {len(set(lineage) & set(roots_now))}")

        # ── E. A NAME IS NEVER A PREMISE ────────────────────────────────────
        print("\n== E. What it concluded is not read back as what it saw ==")
        check("the name is held as a fact about the thing",
              CAT in held, f"{len(held)} held feature(s)")
        check("and is NOT among what was observed of it",
              CAT not in observed, f"observed: {sorted(observed)}")
        check("so a second naming cannot rest on the first",
              set(observed).isdisjoint({x.category for x in reading.names}),
              "no derived name appears in the premises")
        # Induction sees the same restriction.
        second = await see("circle", "red", 46)
        obs2, _ = await observed_instance_features(db, second)
        check("induction generalises over the observed features only",
              CAT not in obs2 and len(obs2) > 0, f"{sorted(obs2)}")

        # ── F. JUDGED WITH THE REST OF THE PERCEPT ──────────────────────────
        print("\n== F. The name is judged by the same band as the seeing ==")
        judged = [e.payload for e in seen_events[before:]
                  if getattr(e.payload, "subject", None)]
        percept = next((p for p in judged
                        if any(c.claim.endswith(CAT) for c in p.claims)), None)
        check("the name reached the judgement as a claim of that percept",
              percept is not None,
              f"{len(percept.claims)} claim(s) at accept={percept.accept}"
              if percept else "no percept judgement carried it")
        if percept is not None:
            verdicts = [c for c in percept.claims if c.claim.endswith(CAT)]
            check("carrying its own posterior and verdict",
                  bool(verdicts) and verdicts[0].posterior is not None,
                  f"{verdicts[0].decision} @ {verdicts[0].posterior}"
                  if verdicts else "none")
            order = {"ABSTAIN": 0, "VERIFY": 1, "ACT": 2}
            weakest = min((c.decision for c in percept.claims),
                          key=lambda d: order[d])
            check("and the percept's verdict is still the WEAKEST of them all",
                  percept.decision == weakest,
                  f"percept={percept.decision}, weakest={weakest}")

        # ── G. SILENCE IS AN ANSWER ─────────────────────────────────────────
        print("\n== G. A thing that matches nothing is named nothing ==")
        odd = await see("triangle", "green", 58)
        obs_odd, _ = await observed_instance_features(db, odd)
        reading_odd = read_names(odd, obs_odd, stored)
        check("nothing it learned here names this one",
              CAT not in {x.category for x in reading_odd.names},
              f"named: {sorted(x.category for x in reading_odd.names) or 'nothing'}")
        check("and 'nothing fired' is distinguishable from 'nothing to try'",
              reading_odd.considered > 0,
              f"{reading_odd.considered} naming rule(s) weighed")
        empty = read_names(odd, obs_odd, [])
        check("because with no rules at all it says so",
              empty.considered == 0 and not empty.names, "considered=0")

        # ── H. DISAGREEMENT BECOMES A QUESTION ──────────────────────────────
        print("\n== H. A category whose hypotheses disagree names nothing ==")
        # Positives that are green AND triangular, against a negative that is
        # neither, leave a version space: `green -> X` survives beside
        # `triangle -> X` and `triangle & green -> X`, and nothing seen so far
        # tells them apart.
        AMB = f"recogamb{tag}"
        amb_pos = [await see("triangle", "green", 46),
                   await see("triangle", "green", 46)]
        amb_neg = [await see("square", "blue", 88)]
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            amb = await coord.learning.induce_category(
                AMB, positives=amb_pos, negatives=amb_neg, domain=DOMAIN)
        stored2 = await get_rule_store().load()
        # A GREEN SQUARE separates them: `green -> X` fires on it and the two
        # hypotheses mentioning `triangle` do not.
        #
        # This used to be a green triangle that was LARGE, separating `small ->
        # X` from `triangle & green -> X`. That fixture was built out of the size
        # band, which is no longer a feature of a blob -- it is a fact about
        # where the camera stood, it survived 0% of zooms, and D3 removed it. The
        # ambiguity being tested is real and unchanged; only the accidental
        # feature carrying it had to become one that is about the object.
        splitter = await see("square", "green", 46)
        obs_split, _ = await observed_instance_features(db, splitter)
        split_reading = read_names(splitter, obs_split, stored2)
        undecided = [u for u in split_reading.undetermined if u.category == AMB]
        hypotheses = len([s for s in stored2 if s.domain_id == DOMAIN
                          and any(f.predicate == AMB for f in s.rule.effects.add)])
        EV.metric("hypotheses_for_ambiguous_category", hypotheses, "count")
        if hypotheses > 1:
            check("the disagreement is reported, not resolved by picking one",
                  bool(undecided),
                  f"{undecided[0].firing}/{undecided[0].hypotheses} fire"
                  if undecided else "no disagreement seen")
            check("it is NOT named while its hypotheses disagree",
                  AMB not in {x.category for x in split_reading.names},
                  "withheld")
            check("and what would decide it is stated",
                  bool(undecided) and bool(undecided[0].silent),
                  "; ".join(undecided[0].silent) if undecided else "n/a")
        else:
            check("induction collapsed to one hypothesis, so there is no "
                  "version space to disagree — reported, not asserted",
                  hypotheses == 1, f"{hypotheses} hypothesis, status={amb.status.value}")

        # ── I. A TAUGHT INSTANCE SURVIVES THE PROCESS ───────────────────────
        print("\n== I. A reference instance outlives the process that learned it ==")
        from core.perception.perception_faculty import PerceptionFaculty, get_perception_faculty
        ref_name = f"recog_ref_{tag}"
        ref_path = STIM / f"recog_{tag}_1.png"
        kp = await get_perception_faculty().learn_instance(ref_name, str(ref_path))
        check("the faculty learned a reference instance", kp > 0, f"{kp} keypoints")
        fresh_faculty = PerceptionFaculty()
        await fresh_faculty.load_instances()
        check("a faculty that never saw it knows it — the library is durable",
              ref_name in fresh_faculty.known_instances,
              f"knows {len(fresh_faculty.known_instances)} instance(s)")
        _modality, seen_again = await fresh_faculty.sense(str(ref_path))
        matched = [(d["label"], d["confidence"]) for d in seen_again.get("detections") or []]
        check("and can actually recognise it again from the pixels",
              any(m[0] == ref_name for m in matched),
              f"{len(matched)} match(es)")
        fresh_faculty.close()
        await get_perception_faculty().forget_instance(ref_name)
        after_forget = PerceptionFaculty()
        await after_forget.load_instances()
        check("forgetting it is durable too",
              ref_name not in after_forget.known_instances, "gone")

    finally:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with contextlib.suppress(Exception):
                from core.learning.rule_store import get_rule_store as _grs
                await _grs().forget_domain(DOMAIN)

    passed = sum(results)
    print(f"\n==== RECOGNISE-01: {passed}/{len(results)} checks passed ====\n")
    EV.metric("checks_passed", passed, "count")
    EV.metric("checks_total", len(results), "count")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
