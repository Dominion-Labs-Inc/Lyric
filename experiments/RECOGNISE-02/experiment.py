#!/usr/bin/env python3
"""RECOGNISE-02 — two recognition paths, in parallel, over one teaching.

The substrate names what it sees by applying rules it induced (RECOGNISE-01).
That path is exact, legible and learns from two examples, and it has a hard
ceiling: anti-unification keeps ONE conjunction per category, so a category that
is a DISJUNCTION of conditions -- "a red circle OR a blue square" -- cannot be
represented at all. It reports `multiple_hypotheses` and waits for a
demonstration that will never come, because no single conjunction is right.

A Tsetlin clause population is the same family at a different scale: many
weighted clauses arguing for and against a class, decided by vote. It represents
disjunction, improves with data, abstains when the vote is not decisive, and
needs far more examples to say anything at all.

Neither replaces the other. Keeping both is what lets either be removed without
the substrate losing the ability to name what it sees.

  A  ONE TEACHING   the same labelled blobs, admitted by sight, feed both paths.
  B  THE CEILING    a disjunctive category defeats anti-unification, and the
                    clause population learns it.
  C  IN PARALLEL    one act of sight, both paths naming, through one gate and
                    one judgement.
  D  DECLINING      a vote always has a winner, so "none of these" has to be a
                    class the machine can argue FOR — and when it wins, nothing
                    is named.
  E  DERIVED        a classifier reading the substrate's own symbols is drawing a
                    conclusion, not making an observation, and enters as one.
  F  LEGIBLE        the population can say WHY, in the same vocabulary sight
                    measured in.
  G  INDEPENDENT    remove either path and the other still names.
  H  DURABLE        a trained population survives the process WITH its encoder.

Run: ./venv_torin/bin/python3 experiments/RECOGNISE-02/experiment.py
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
               "POSTGRES_DATABASE": "torinai_db", "TORIN_NO_WATCHDOG": "1",
               "TORIN_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from experiments._evidence import RunRecord  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
STIM = HERE / "stimuli"
COLOURS = {"red": (0, 0, 255), "blue": (255, 0, 0), "green": (0, 170, 0),
           "yellow": (0, 215, 255)}

EV = RunRecord(
    "RECOGNISE-02",
    claim=("The substrate carries two independent recognition paths over one "
           "teaching: induced rules, exact and few-shot; and a Tsetlin clause "
           "population, which represents what a single conjunction cannot. Both "
           "name blobs through one gate and one judgement, and either can be "
           "removed with the other still naming."),
    hypothesis=("If the two paths were really one capability wearing two coats, "
                "a category that defeats anti-unification would defeat the "
                "population too. A disjunctive category is the discriminating "
                "case: one conjunction cannot express it, a clause population "
                "can, and that is the whole reason for keeping both."))

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
    STIM.mkdir(exist_ok=True)
    buf = io.StringIO()
    tag = uuid.uuid4().hex[:6]
    DOMAIN = f"recog2{tag}"
    #: A DISJUNCTIVE category: red circles AND blue squares are both `token`.
    TOKEN = f"token{tag}"
    CLF = f"blobs_{tag}"

    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        from core.database import get_database_manager
        from core.learning.rule_store import get_rule_store
        from core.reasoning.bayesian_uncertainty import get_uncertainty_system
        from core.reasoning.concept_graph_reasoning import (
            instance_predicates, observed_instance_features)
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        db = get_database_manager()
        await db.initialize()

    n = [0]

    async def blob_of(image_name: str) -> str:
        rows = await db.execute_query(
            "SELECT cr.target_surface FROM unified.concept_relations cr "
            "JOIN unified.concepts c ON cr.source_concept_id = c.concept_id "
            "WHERE c.name = $1 AND cr.relation = 'contains'",
            (image_name,), fetch_all=True) or []
        return str(rows[0]["target_surface"]) if rows else ""

    async def see(shape: str, colour: str, radius: int, *, clf=None) -> str:
        n[0] += 1
        name = f"recog2_{tag}_{n[0]}"
        path = STIM / f"{name}.png"
        draw(path, shape, colour, radius)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            percept = await coord.see(str(path), source=name, domain=DOMAIN,
                                      recognize=clf, actor_identity=None)
            await get_uncertainty_system().drain_writes()
        # The substrate names a percept from the image's own content digest, so
        # the label handed in is no longer the concept's name. Ask, don't rebuild.
        return await blob_of(percept.source if percept else name)

    try:
        # ── A. ONE TEACHING ─────────────────────────────────────────────────
        print("\n== A. The same labelled blobs, admitted by sight, feed both ==")
        reds = [await see("circle", "red", r) for r in (46, 58, 72, 88)]
        blues = [await see("square", "blue", r) for r in (46, 58, 72, 88)]
        others = [await see("triangle", "green", r) for r in (46, 58, 72, 88)]
        others += [await see("circle", "yellow", r) for r in (58, 88)]
        check("every example entered through sight",
              all(reds) and all(blues) and all(others),
              f"{len(reds)} red circle(s), {len(blues)} blue square(s), "
              f"{len(others)} other(s)")
        EV.metric("examples", len(reds) + len(blues) + len(others), "count")

        # ── B. THE CEILING ──────────────────────────────────────────────────
        print("\n== B. A disjunctive category defeats one conjunction ==")
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            induced = await coord.learning.induce_category(
                TOKEN, positives=reds + blues, negatives=others, domain=DOMAIN)
        status = induced.status.value
        check("anti-unification cannot represent 'red circle OR blue square'",
              induced.rule is None,
              f"status={status}, rule={induced.rule}")
        EV.metric("induction_status_on_disjunction", status, "status")

        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            trained = await coord.learning.train_clause_classifier(
                CLF, {TOKEN: reds + blues}, others=others, domain=DOMAIN,
                epochs=60)
        check("the clause population learns the same category",
              trained["training_accuracy"] >= 0.9,
              f"accuracy {trained['training_accuracy']} over "
              f"{trained['examples']} example(s), {len(trained['vocabulary'])} "
              f"feature(s)")
        EV.metric("clause_training_accuracy", trained["training_accuracy"], "ratio")
        EV.metric("vocabulary", len(trained["vocabulary"]), "features")
        check("with an explicit class for 'none of these'",
              trained["reject_label"] is not None,
              f"classes: {trained['classes']}")

        # ── C. IN PARALLEL ──────────────────────────────────────────────────
        print("\n== C. One act of sight, both paths naming ==")
        # A held-out member of each disjunct.
        held_red = await see("circle", "red", 64, clf=CLF)
        held_blue = await see("square", "blue", 64, clf=CLF)
        red_names = await instance_predicates(db, held_red)
        blue_names = await instance_predicates(db, held_blue)
        check("the clause population named a held-out red circle, unasked",
              TOKEN in red_names, f"{held_red} isa {TOKEN}"
              if TOKEN in red_names else f"held {sorted(red_names)}")
        check("and a held-out blue square — the other disjunct",
              TOKEN in blue_names, f"{held_blue} isa {TOKEN}"
              if TOKEN in blue_names else f"held {sorted(blue_names)}")
        obs_red, _ = await observed_instance_features(db, held_red)
        check("naming it did not make the name a feature of it",
              TOKEN not in obs_red, f"observed: {sorted(obs_red)}")

        # ── D. DECLINING ────────────────────────────────────────────────────
        print("\n== D. A vote that lands on 'none of these' names nothing ==")
        held_other = await see("triangle", "green", 64, clf=CLF)
        other_names = await instance_predicates(db, held_other)
        check("a thing of no taught category is not named one",
              TOKEN not in other_names,
              f"held {sorted(other_names) or 'nothing'}")
        obs_other, _ = await observed_instance_features(db, held_other)
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            declined = await coord.learning.recognize(
                CLF, obs_other, held_other, domain=DOMAIN)
        check("the machine returns nothing rather than a wrong name",
              declined is None, "declined")

        # ── E. DERIVED, NOT OBSERVED ────────────────────────────────────────
        print("\n== E. A classifier reading symbols concludes, it does not observe ==")
        rows = await db.execute_query(
            "SELECT ee.source_type, ee.producer, ee.derived_from "
            "FROM unified.concept_relations cr "
            "JOIN unified.concepts c1 ON cr.source_concept_id = c1.concept_id "
            "JOIN unified.evidence_envelopes ee ON ee.evidence_id = cr.evidence_id "
            "WHERE c1.name = $1 AND cr.target_surface = $2",
            (held_red, TOKEN), fetch_all=True) or []
        src = str(rows[0]["source_type"]) if rows else ""
        producer = str(rows[0]["producer"]) if rows else ""
        check("it entered as a derivation", src == "induced_rule",
              f"{src} from {producer}")
        import json as _json
        lineage = rows[0]["derived_from"] if rows else "[]"
        lineage = _json.loads(lineage) if isinstance(lineage, str) else (lineage or [])
        check("declaring the observations it read", len(lineage) > 0,
              f"{len(lineage)} root(s)")

        # ── F. LEGIBLE ──────────────────────────────────────────────────────
        print("\n== F. The population can say why, in sight's own vocabulary ==")
        token_clauses = trained["clauses"].get(TOKEN) or []
        check("it states the clauses that argue for the class",
              bool(token_clauses), f"{len(token_clauses)} shown")
        vocab = set(trained["vocabulary"])
        literals = {lit.replace("NOT ", "").strip()
                    for c in token_clauses for lit in c.split("&")}
        check("in the terms the faculty measured, not opaque indices",
              bool(literals) and literals <= vocab,
              "; ".join(token_clauses[:2]) or "none")
        check("and the vocabulary IS what sight measures",
              {"circle", "square"} & vocab == {"circle", "square"},
              f"{sorted(vocab)}")

        # ── G. INDEPENDENT ──────────────────────────────────────────────────
        print("\n== G. Remove either path and the other still names ==")
        # A category the RULE path can carry (one conjunction), taught alongside.
        SOLO = f"solo{tag}"
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            solo = await coord.learning.induce_category(
                SOLO, positives=blues[:2], negatives=others[:2], domain=DOMAIN)
        # `rule` is None whenever more than one hypothesis survives, and that is
        # the design: the store keeps a VERSION SPACE for a later demonstration
        # to collapse, rather than picking one at induction time. Two blue
        # squares against two green triangles differ in every feature, so
        # `square`, `vivid_blue` and `medium` each separate them and all three
        # are kept. What matters here is that the rule path learned something it
        # can name with — which it did, unanimously, below.
        check("a non-disjunctive category is still learned by the rules",
              bool(solo.candidates),
              f"{len(solo.candidates)} hypothesis/es ({solo.status.value}): "
              + "; ".join(str(c) for c in solo.candidates[:3]))
        # NO classifier on this sighting: the rule path alone.
        rules_only = await see("square", "blue", 52)
        rules_only_names = await instance_predicates(db, rules_only)
        check("with NO classifier attached, the rules still name",
              SOLO in rules_only_names,
              f"{rules_only} isa {SOLO}" if SOLO in rules_only_names
              else f"held {sorted(rules_only_names)}")
        # Rules gone, classifier alone.
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            await get_rule_store().forget_domain(DOMAIN)
        clf_only = await see("circle", "red", 52, clf=CLF)
        clf_only_names = await instance_predicates(db, clf_only)
        check("with every rule deleted, the clause population still names",
              TOKEN in clf_only_names,
              f"{clf_only} isa {TOKEN}" if TOKEN in clf_only_names
              else f"held {sorted(clf_only_names)}")
        check("and the rule path is genuinely gone, not merely quiet",
              SOLO not in clf_only_names,
              f"{SOLO} absent — its rule was deleted")

        # ── H. DURABLE ──────────────────────────────────────────────────────
        print("\n== H. A trained population survives WITH its encoder ==")
        # Into the STORE, where the classifier lives -- and read back by an
        # authority that never trained it, as the next process would.
        from core.learning.unified_learning_system import (
            FeatureEncoder, UnifiedLearningSystem)
        saved = await coord.learning.save_classifiers()
        check("the mechanism persists", saved >= 1, f"{saved} classifier(s)")
        fresh = UnifiedLearningSystem()
        restored = await fresh.load_classifiers()
        check("a fresh authority restores it", fresh.has_clause_classifier(CLF),
              f"{restored} classifier(s) in the store")
        check("with its feature vocabulary intact",
              fresh.clause_classifier_vocabulary(CLF) == trained["vocabulary"],
              f"{len(trained['vocabulary'])} feature(s)")
        entry = fresh._clause_classifiers[CLF]
        check("and a REBUILT encoder, not None — it can read an instance",
              isinstance(entry.get("encode"), FeatureEncoder),
              type(entry.get("encode")).__name__)
        check("its rejection class survived too",
              entry.get("reject_label") == trained["reject_label"],
              str(entry.get("reject_label")))
        bits = entry["encode"](obs_red)
        check("and it encodes the same instance the same way",
              list(bits) == list(FeatureEncoder(trained["vocabulary"])(obs_red)),
              f"{int(sum(bits))} bit(s) set")

    finally:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with contextlib.suppress(Exception):
                await get_rule_store().forget_domain(DOMAIN)
        # The trained classifier is this run's fixture: out of the store too.
        from core.database import get_database_manager
        await get_database_manager().execute_query(
            "DELETE FROM unified.clause_classifiers WHERE name = $1", (CLF,))

    passed = sum(results)
    print(f"\n==== RECOGNISE-02: {passed}/{len(results)} checks passed ====\n")
    EV.metric("checks_passed", passed, "count")
    EV.metric("checks_total", len(results), "count")
    EV.write()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
