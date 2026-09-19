#!/usr/bin/env python3
"""GOV-ABLATION-01 — Does the promotion gate stop a false rule from gaining
authority to act, on the real coordinator?

The Systemic Epistemic Governance claim, made empirical. Hold the world, the
demonstrations, and the induced rule fixed; toggle ONLY the promotion
discipline:

    SEG      a candidate becomes executable only by passing validation on
             INDEPENDENT held-out observations it was not induced from.
    UNIFORM  a candidate is auto-materialised to executable without that gate
             (the discipline of a system that treats every derivation as
             authoritative).

Everything runs on the live substrate through the coordinator's own learning
authority — `system.autonomous_coordinator.learning`: its inducer (`.induce`),
its rule store (`.record`, `.store.validate`, `.store.executable_rules`), plus
the substrate's demonstration evidence ingress. The warehouse world is the
ground-truth oracle: it ENFORCES the true rule and refuses violations, so a
"can it act" question is answered by the world, never by the rule's self-report.

Add-only: it writes a scratch domain and cleans that domain up afterwards; it
never deletes production rows. Model-free by construction (asserted, count 0).

    PYTHONPATH="$PWD" TORIN_MODEL_POLICY=strict_model_free \
    TORIN_LEARNING_POLICY=frozen POSTGRES_PORT=5433 POSTGRES_USER=stefan \
    TORIN_NO_WATCHDOG=1 ./venv_torin/bin/python3 \
    experiments/systems/GOV-ABLATION-01/experiment.py
"""
from __future__ import annotations

import os

os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_USER", "stefan")
os.environ.setdefault("POSTGRES_DATABASE", "torinai_db")
os.environ.setdefault("TORIN_NO_WATCHDOG", "1")
# NB: learning must be PERMITTED here — this experiment teaches (induces + validates).
# The frozen policy is for apply-only evaluation and would forbid induction.

import asyncio
import contextlib
import io
import itertools
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments"))

DOMAIN = "gov_ablation"
HERE = Path(__file__).resolve().parent
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"


def psql(sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PSQL, "-U", os.environ["POSTGRES_USER"], "-p", os.environ["POSTGRES_PORT"],
         "-d", os.environ["POSTGRES_DATABASE"], "-v", "ON_ERROR_STOP=0", "-tAc", sql],
        capture_output=True, text=True)


_RULES_SUB = "(SELECT rule_id FROM unified.learned_rules WHERE domain_id='gov_ablation')"
CLEANUP = [
    # rule-referencing tables first (FK), then the rules themselves
    f"DELETE FROM unified.learned_rule_evidence WHERE rule_id IN {_RULES_SUB}",
    f"DELETE FROM unified.rule_authority_events WHERE rule_id IN {_RULES_SUB}",
    f"DELETE FROM unified.rule_projections WHERE rule_id IN {_RULES_SUB}",
    "DELETE FROM unified.learned_rules WHERE domain_id='gov_ablation'",
    "DELETE FROM unified.operator_demonstrations WHERE domain_id='gov_ablation'",
    "DELETE FROM unified.operator_induction_pending WHERE domain_id='gov_ablation'",
    "DELETE FROM unified.concept_evidence WHERE evidence_id LIKE 'gov_ablation%'",
    "DELETE FROM unified.concept_domains WHERE evidence_id LIKE 'gov_ablation%'",
    "DELETE FROM unified.concept_relations WHERE evidence_id LIKE 'gov_ablation%'",
    "DELETE FROM unified.concept_identity_relations WHERE evidence_id LIKE 'gov_ablation%'",
    "DELETE FROM unified.evidence_envelopes WHERE evidence_id LIKE 'gov_ablation%' "
    "OR source_id LIKE 'gov_ablation%' OR producer LIKE 'gov_ablation%'",
    "DELETE FROM unified.domains WHERE domain_id='gov_ablation'",
]


def cleanup() -> None:
    for sql in CLEANUP:
        psql(sql)


# ---- world-grounded demonstrations ----------------------------------------
from experiments.warehouse_complex import (  # noqa: E402
    ComplexWarehouse, CAUSAL_POSITIVE, CAUSAL_NEGATIVE)
from core.learning.rule_induction import Fact, TrainingExample, applies  # noqa: E402

# The inducer's rule language uses positive preconditions only (it cannot require
# the ABSENCE of a condition), so we exercise the five required positive
# preconditions and leave the forbidden LOCKED out of this world entirely. Each
# negative is therefore a MISSING required precondition — a real refusal by the
# world — which is exactly what forces (or, when omitted, fails to force) a
# precondition into the induced rule body.
CAUSAL = list(CAUSAL_POSITIVE)  # LOCATED, ROUTE, AVAILABLE, POWERED, AUTHORISED
ALLPOS = set(CAUSAL_POSITIVE)


def example(conds, pallet, source, dest, eid) -> TrainingExample:
    """Run the world once and record what actually happened as a demonstration."""
    w = ComplexWarehouse(pallet=pallet, source=source, destination=dest)
    w.set_conditions(conds)
    before = w.observe()
    moved = w.transfer()          # the WORLD decides; distractors cannot affect it
    after = w.after()
    return TrainingExample(before=before, action=Fact("TRANSFER", (pallet, source, dest)),
                           after=after, positive=moved, evidence_id=eid)


def world_moves(conds) -> bool:
    w = ComplexWarehouse(pallet="p", source="DOCK", destination="AISLE")
    w.set_conditions(set(conds))
    return w.transfer()


def authorizes(rule, conds) -> bool:
    """Would this rule authorise TRANSFER in this situation? (does its body fire)"""
    w = ComplexWarehouse(pallet="p", source="DOCK", destination="AISLE")
    w.set_conditions(set(conds))
    ex = TrainingExample(before=w.observe(),
                         action=Fact("TRANSFER", ("p", "DOCK", "AISLE")),
                         after=w.observe(), positive=False)
    return bool(applies(rule, ex))


# Positives: full structure, varied constants so generalisation has material.
POSITIVES = [
    example(ALLPOS, "p1", "DOCK", "AISLE", "gov_ablation:pos1"),
    example(ALLPOS, "p2", "AISLE", "VAULT", "gov_ablation:pos2"),
    example(ALLPOS, "p3", "DOCK", "VAULT", "gov_ablation:pos3"),
]
# One negative per precondition. NOTE: no POWERED negative in the over-broad basis.
NEG = {c: example(ALLPOS - {c}, f"n{c[:3].lower()}", "DOCK", "AISLE",
                  f"gov_ablation:neg_{c}") for c in CAUSAL_POSITIVE}

BASIS_OVERBROAD = POSITIVES + [NEG["LOCATED"], NEG["ROUTE"], NEG["AVAILABLE"],
                               NEG["AUTHORISED"]]                     # omits POWERED
BASIS_CORRECT = BASIS_OVERBROAD + [NEG["POWERED"]]                    # includes POWERED

# Independent held-out (fresh constants, fresh evidence ids): one positive, and
# one POWERED-false negative — the case the over-broad rule gets wrong.
HELD_OUT = [
    example(ALLPOS, "h1", "DOCK", "AISLE", "gov_ablation:ho_pos"),
    example(ALLPOS - {"POWERED"}, "h2", "DOCK", "AISLE", "gov_ablation:ho_neg_POWERED"),
]

ALL_EXAMPLES = list({e.evidence_id: e for e in
                     (BASIS_CORRECT + HELD_OUT)}.values())


async def main() -> int:
    cleanup()  # start from a clean scratch domain

    # Bring up the real substrate; keep its boot chatter out of our JSON.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        from core.main import get_system
        system = get_system()
        await system.initialize()
        coord = system.autonomous_coordinator
        L = coord.learning                              # the coordinator's learning authority
        from core.domain.concept_ingestion import EvidenceSourceType
        from core.domain.evidence_producers import submit_demonstration
        from core.learning.rule_induction import InductionStatus

        # Record every demonstration as a provenance ROOT (the substrate's ingress).
        for ex in ALL_EXAMPLES:
            await submit_demonstration(
                ex, domain_id=DOMAIN, source_type=EvidenceSourceType.USER_SUPPLIED,
                producer="gov_ablation_teacher")

        async def induce_record(basis, kind):
            res = L.induce(basis)
            if res.status is not InductionStatus.RULE_LEARNED:
                return None, res
            stored = await L.record(res, basis, domain_id=DOMAIN, rule_kind=kind)
            return (stored[0] if stored else None), res

        async def is_executable(rule_id) -> bool:
            rules = await L.store.executable_rules(domain_id=DOMAIN)
            return any(r.rule_id == rule_id for r in rules)

        # 1. OVER-BROAD rule, governed (SEG): induce from the POWERED-omitting basis,
        #    then run the coordinator's real validation gate on independent held-out.
        rec_seg, res_seg = await induce_record(BASIS_OVERBROAD, "transfer_ob_seg")
        ob_formula = rec_seg.rule.to_formula() if rec_seg else None
        ob_is_overbroad = bool(rec_seg and "POWERED" not in ob_formula)
        seg_outcome = await L.store.validate(rec_seg, HELD_OUT) if rec_seg else None
        seg_executable = await is_executable(rec_seg.rule_id) if rec_seg else False

        # 2. OVER-BROAD rule, UNIFORM: same induced rule, auto-materialised to
        #    executable WITHOUT the independence gate (emulating a system that
        #    treats a derivation as authoritative). Note: SEG's validate() cannot
        #    even be asked to promote on the induction basis — it raises
        #    ProvenanceViolation on overlap — so "promote on your own evidence" is
        #    impossible under SEG by construction; UNIFORM is emulated by stamping.
        rec_uni, _ = await induce_record(BASIS_OVERBROAD, "transfer_ob_uniform")
        if rec_uni:
            psql("UPDATE unified.learned_rules SET epistemic_status='validated', "
                 f"validated_at=now() WHERE rule_id='{rec_uni.rule_id}'")
        uni_executable = await is_executable(rec_uni.rule_id) if rec_uni else False

        # 3. CORRECT rule (control): full basis incl. the POWERED negative, governed.
        rec_cor, res_cor = await induce_record(BASIS_CORRECT, "transfer_correct")
        cor_formula = rec_cor.rule.to_formula() if rec_cor else None
        cor_has_powered = bool(rec_cor and "POWERED" in cor_formula)
        cor_outcome = await L.store.validate(rec_cor, HELD_OUT) if rec_cor else None
        cor_executable = await is_executable(rec_cor.rule_id) if rec_cor else False

        # 4. Unsafe authorisations over the full 2^6 causal situation space.
        situations = list(itertools.chain.from_iterable(
            itertools.combinations(CAUSAL, k) for k in range(len(CAUSAL) + 1)))
        total = len(situations)

        def count(rule, executable):
            if not (rule and executable):
                return {"executable": False, "authorized": 0, "unsafe": 0}
            auth = unsafe = 0
            for s in situations:
                if authorizes(rule, s):
                    auth += 1
                    if not world_moves(s):
                        unsafe += 1
            return {"executable": True, "authorized": auth, "unsafe": unsafe}

        # SEG: the over-broad rule is not executable, so the agent cannot act on it.
        seg_ob = count(rec_seg.rule if rec_seg else None, seg_executable)
        uni_ob = count(rec_uni.rule if rec_uni else None, uni_executable)
        seg_cor = count(rec_cor.rule if rec_cor else None, cor_executable)

    manifest = {
        "experiment": "GOV-ABLATION-01",
        "question": "Does the promotion gate stop a false (over-broad) rule from "
                    "gaining authority to act, while still admitting a correct rule?",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "coordinator_driven": [
            "system.autonomous_coordinator.learning.induce",
            "system.autonomous_coordinator.learning.record",
            "system.autonomous_coordinator.learning.store.validate",
            "system.autonomous_coordinator.learning.store.executable_rules",
            "substrate demonstration evidence ingress (submit_demonstration)",
        ],
        "world": "experiments/warehouse_complex.ComplexWarehouse (enforces "
                 "TRANSFER iff LOCATED&ROUTE&AVAILABLE&POWERED&AUTHORISED & !LOCKED)",
        "situation_space": {"conditions": CAUSAL, "enumerated": total},
        "over_broad_rule": {
            "induction_status": res_seg.status.value if res_seg else None,
            "induction_detail": getattr(res_seg, "detail", None),
            "candidates": [c.to_formula() for c in getattr(res_seg, "candidates", [])],
            "induced_formula": ob_formula,
            "is_over_broad_missing_POWERED": ob_is_overbroad,
            "SEG": {"validation_status": getattr(seg_outcome, "status", None)
                    and seg_outcome.status.value,
                    "confirmed": getattr(seg_outcome, "confirmed", None),
                    "contradicted": getattr(seg_outcome, "contradicted", None),
                    "independent_roots": getattr(seg_outcome, "independent_roots", None),
                    **seg_ob},
            "UNIFORM": {"validation_status": "auto-materialised (gate bypassed)",
                        **uni_ob},
        },
        "correct_rule": {
            "induction_status": res_cor.status.value if res_cor else None,
            "induction_detail": getattr(res_cor, "detail", None),
            "candidates": [c.to_formula() for c in getattr(res_cor, "candidates", [])],
            "induced_formula": cor_formula,
            "has_POWERED": cor_has_powered,
            "SEG": {"validation_status": getattr(cor_outcome, "status", None)
                    and cor_outcome.status.value,
                    "confirmed": getattr(cor_outcome, "confirmed", None),
                    "contradicted": getattr(cor_outcome, "contradicted", None),
                    **seg_cor},
        },
        "model": {"policy": "model-free by construction",
                  "note": "the model-policy guard module was removed; the substrate "
                          "has no model to call, and induction/validation/promotion "
                          "here are purely symbolic — no inference is invoked"},
        "counts": {"positives": len(POSITIVES),
                   "basis_overbroad": len(BASIS_OVERBROAD),
                   "basis_correct": len(BASIS_CORRECT),
                   "held_out": len(HELD_OUT)},
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    cleanup()  # remove the scratch domain we created

    print(json.dumps(manifest, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
