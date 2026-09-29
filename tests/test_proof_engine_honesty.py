#!/usr/bin/env python3
"""The proof engine must not claim more than it checked.

Defects found by asking one question of each function: can this return a
value that makes its caller believe something happened that did not?

    verify_proof     looped over the steps with `pass` and returned
                     `proof.proved` -- the claim it was asked to check
    _smt_proof       silently ran a weaker method when Z3 was missing
    prove_theorem    reported `proved=False` from an incomplete method
                     identically to a real refutation

And one capability that did not work and now does. Natural deduction -- the
forward derivation and the proof by contradiction -- split formulas on the
substring "->", re-derived the same fact until its budget ran out in an order
set by the hash seed, never proved a goal that was already a premise, and the
contradiction strategy was a stub. It now runs on the solver's own grammar,
every step cites the steps it came from, and the checker re-derives each one.
It runs ALONGSIDE the solver, never silently instead of it.
"""

import pytest

import core.reasoning.advanced_proof_engine as engine_module
from core.reasoning.advanced_proof_engine import (CAPABILITY_UNAVAILABLE,
                                                  NEGATIVE_NOT_AUTHORITATIVE,
                                                  PROVERS_DISAGREE,
                                                  AdvancedProofEngine, LogicType,
                                                  Proof, ProofMethod, ProofStep,
                                                  Theorem)


@pytest.fixture
def engine():
    return AdvancedProofEngine()


@pytest.fixture
def syllogism():
    return Theorem(theorem_id="t1", statement="socrates_mortal",
                   premises=["socrates_human", "socrates_human -> socrates_mortal"],
                   logic_type=LogicType.PROPOSITIONAL)


def _theorem(goal, premises):
    return Theorem(theorem_id="t", statement=goal, premises=list(premises),
                   logic_type=LogicType.PROPOSITIONAL)


@pytest.fixture
def proof_by_cases():
    """Entailed; unreachable by forward derivation alone (it never learns `a` or
    `b`); reached by contradiction through modus tollens and disjunctive
    syllogism."""
    return _theorem("c", ["a | b", "a -> c", "b -> c"])


@pytest.fixture
def beyond_the_rules():
    """Entailed, but only by splitting on a case -- these rules have no split.
    The theorem a sound, incomplete method must fail on WITHOUT calling it false."""
    return _theorem("p & q", ["p | q", "p | ~q", "~p | q"])


@pytest.mark.asyncio
async def test_a_real_proof_verifies(engine, syllogism):
    proof = await engine.prove_theorem(syllogism)
    assert proof.proved
    verification = await engine.verify_proof(proof, syllogism)
    assert verification.verified and bool(verification) is True


# ---- the checker: nothing is waved through ------------------------------

@pytest.mark.asyncio
async def test_a_proof_whose_steps_do_not_follow_is_rejected(engine):
    """The case the old implementation returned True on."""
    fabricated = Proof(theorem_id="t2", proved=True, method=ProofMethod.DIRECT,
                       steps=[ProofStep(1, "a", "Premise", "given"),
                              ProofStep(2, "z", "From nothing", "modus_ponens")])
    verification = await engine.verify_proof(fabricated)
    assert not verification.verified
    assert verification.failed_step == 2


@pytest.mark.asyncio
async def test_a_step_the_checker_cannot_re_derive_blocks_verification(engine):
    """An unexamined step must never be waved through -- that is precisely what
    the previous version did for every step."""
    proof = Proof(theorem_id="t3", proved=True, method=ProofMethod.DIRECT,
                  steps=[ProofStep(1, "a", "Premise", "given"),
                         ProofStep(2, "b", "By magic", "unsupported_rule")])
    verification = await engine.verify_proof(proof)
    assert not verification.verified
    assert verification.unchecked_steps == [2]


@pytest.mark.asyncio
async def test_a_proof_claiming_success_with_no_steps_is_rejected(engine):
    proof = Proof(theorem_id="t4", proved=True, method=ProofMethod.DIRECT, steps=[])
    assert not (await engine.verify_proof(proof)).verified


@pytest.mark.asyncio
async def test_a_solver_proof_claiming_what_does_not_follow_is_rejected(engine):
    """A proof's own `proved=True` is not evidence; the solver, asked again, is."""
    not_entailed = _theorem("z", ["a"])
    fabricated = Proof(theorem_id="t", proved=True, method=ProofMethod.SMT,
                       steps=[ProofStep(1, "a", "Premise", "given")])
    verification = await engine.verify_proof(fabricated, not_entailed)
    assert not verification.verified
    assert "did not reproduce" in verification.reason


@pytest.mark.asyncio
async def test_a_tampered_derivation_step_is_caught(engine, proof_by_cases):
    import copy
    proof = await engine.prove_theorem(proof_by_cases)
    tampered = copy.deepcopy(proof)
    tampered.derivation[-2].statement = "zzz"
    verification = await engine.verify_proof(tampered, proof_by_cases)
    assert not verification.verified
    assert verification.failed_step is not None


# ---- natural deduction works, and is checkable ---------------------------

@pytest.mark.asyncio
async def test_a_chain_is_derived_with_every_step_citing_its_sources(engine):
    theorem = _theorem("c", ["a", "a -> b", "b -> c"])
    proof = await engine._natural_deduction(theorem, 100)
    assert proof.proved and proof.method is ProofMethod.DIRECT
    derived = [(s.statement, s.rule_applied, s.metadata["from"]) for s in proof.steps[3:]]
    assert derived == [("b", "modus_ponens", [1, 2]), ("c", "modus_ponens", [3, 4])]
    assert (await engine.verify_proof(proof, theorem)).verified


@pytest.mark.asyncio
async def test_a_goal_that_is_already_a_premise_is_proved(engine):
    """The old forward chainer only checked NEWLY derived facts, so this failed."""
    proof = await engine._natural_deduction(_theorem("a", ["a", "b"]), 100)
    assert proof.proved and proof.premises_used == [0]


@pytest.mark.asyncio
async def test_a_structured_antecedent_is_seen(engine):
    """`(a & b) -> c` was invisible to a matcher that split on the string "->"."""
    theorem = _theorem("c", ["(a & b) -> c", "a", "b"])
    proof = await engine._natural_deduction(theorem, 100)
    assert proof.proved
    assert (await engine.verify_proof(proof, theorem)).verified


@pytest.mark.asyncio
async def test_proof_by_contradiction_works(engine, proof_by_cases):
    """It was a stub that always returned proved=False at a made-up 0.5."""
    proof = await engine._natural_deduction(proof_by_cases, 100)
    assert proof.proved and proof.method is ProofMethod.CONTRADICTION
    assert proof.steps[-1].statement == "⊥"
    assert (await engine.verify_proof(proof, proof_by_cases)).verified


@pytest.mark.asyncio
async def test_the_derivation_is_the_same_on_every_run(engine, proof_by_cases):
    """Which pair the old chainer hit first depended on set iteration order."""
    first = await AdvancedProofEngine()._natural_deduction(proof_by_cases, 100)
    second = await AdvancedProofEngine()._natural_deduction(proof_by_cases, 100)
    shape = lambda p: [(s.statement, s.rule_applied, s.metadata.get("from")) for s in p.steps]
    assert shape(first) == shape(second)


@pytest.mark.asyncio
async def test_a_negative_from_the_incomplete_method_is_marked(engine, beyond_the_rules):
    """"I could not derive it" must not read as "it does not follow"."""
    proof = await engine._natural_deduction(beyond_the_rules, 100)
    assert proof.proved is False
    assert proof.error == NEGATIVE_NOT_AUTHORITATIVE


# ---- the two provers together --------------------------------------------

@pytest.mark.asyncio
async def test_both_provers_run_and_the_derivation_is_attached(engine, proof_by_cases):
    proof = await engine.prove_theorem(proof_by_cases)
    assert proof.proved and proof.method is ProofMethod.SMT
    assert proof.agreement == "both" and proof.derivation
    verification = await engine.verify_proof(proof, proof_by_cases)
    assert verification.verified
    assert "re-checked" in verification.reason and "solver re-run" in verification.reason


@pytest.mark.asyncio
async def test_what_lies_beyond_the_rules_is_still_proved_by_the_solver(engine,
                                                                        beyond_the_rules):
    proof = await engine.prove_theorem(beyond_the_rules)
    assert proof.proved and proof.agreement == "solver_only"
    verification = await engine.verify_proof(proof, beyond_the_rules)
    assert verification.verified and "no independent derivation" in verification.reason


@pytest.mark.asyncio
async def test_provers_that_disagree_fail_closed(engine):
    """A sound derivation and a countermodel cannot both be right. Neither wins."""
    async def countermodel(theorem, *args, **kwargs):
        return Proof(theorem_id=theorem.theorem_id, proved=False,
                     method=ProofMethod.SMT, confidence=0.0)
    engine._smt_proof = countermodel
    proof = await engine.prove_theorem(_theorem("c", ["a", "a -> c"]))
    assert proof.proved is False
    assert proof.error == PROVERS_DISAGREE and proof.agreement == "disagree"


@pytest.mark.asyncio
async def test_severing_z3_does_not_silently_run_a_weaker_prover(engine, syllogism,
                                                                 monkeypatch):
    """`_smt_proof` must report a capability fault, not degrade."""
    monkeypatch.setattr(engine_module, "_Z3_AVAILABLE", False)
    proof = await engine._smt_proof(syllogism, max_steps=10)
    assert proof.proved is False
    assert proof.error == CAPABILITY_UNAVAILABLE
    assert proof.method is ProofMethod.SMT


@pytest.mark.asyncio
async def test_without_z3_natural_deduction_proves_and_says_what_it_is(
        engine, syllogism, beyond_the_rules, monkeypatch):
    """Not a stand-in for the solver: a first-class method reporting exactly
    what it established. Its derivations are sound and re-checkable; its
    failures are marked as the non-refutations they are."""
    monkeypatch.setattr(engine_module, "_Z3_AVAILABLE", False)
    proof = await engine.prove_theorem(syllogism)
    assert proof.proved and proof.method is ProofMethod.DIRECT
    assert (await engine.verify_proof(proof, syllogism)).verified
    missed = await engine.prove_theorem(beyond_the_rules)
    assert missed.proved is False and missed.error == NEGATIVE_NOT_AUTHORITATIVE


@pytest.mark.asyncio
async def test_a_proof_produced_without_its_solver_never_verifies(engine):
    proof = Proof(theorem_id="t5", proved=True, method=ProofMethod.SMT,
                  error=CAPABILITY_UNAVAILABLE)
    verification = await engine.verify_proof(proof)
    assert not verification.verified
    assert "without its solver" in verification.reason


@pytest.mark.asyncio
async def test_an_smt_proof_cannot_be_verified_without_its_theorem(engine):
    """It carries no re-checkable steps, so there is nothing to examine."""
    proof = Proof(theorem_id="t6", proved=True, method=ProofMethod.SMT,
                  steps=[ProofStep(1, "x", "solver", "smt")])
    assert not (await engine.verify_proof(proof)).verified


# ---- falsifiability: three answers, not two -----------------------------

@pytest.mark.parametrize("claim,expected", [
    # Unbounded universals and absolutes: no finite observation settles them.
    ("This always works", False),
    ("It never fails", False),
    # Value judgements state a preference.
    ("The design is good", False),
    ("We ought to refactor", False),
    # Tautologies hold under every observation.
    ("It is raining or not raining", False),
    # Measurable directions and conditionals can be checked.
    ("Increasing X reduces Y", True),
    ("Caffeine improves recall", True),
    ("If pressure rises the valve opens", True),
    # UNDETERMINED. Not a hedge: a claim whose falsifiability cannot be
    # established should not be admitted as a scientific one, and the caller
    # cannot act on that if a guess already said True.
    ("Purple sleeps furiously", None),
    ("", None),
])
def test_falsifiability_is_three_valued(claim, expected):
    from core.reasoning.hypothesis_testing import HypothesisTestingSystem
    assert HypothesisTestingSystem()._is_falsifiable(claim) is expected


def test_the_unfalsifiable_word_list_is_actually_consulted():
    """It was declared and never read, so "this always works" -- with `always`
    named two lines above -- came back falsifiable."""
    from core.reasoning.hypothesis_testing import HypothesisTestingSystem
    system = HypothesisTestingSystem()
    for word in ("always", "never", "all", "none", "perfect", "impossible", "must"):
        assert system._is_falsifiable(f"The system {word} responds") is False, word


def test_inflected_measurable_verbs_are_recognised():
    """`\\breduce\\b` does not match "reduces"; a measurable claim was reported
    unassessable purely because of inflection."""
    from core.reasoning.hypothesis_testing import HypothesisTestingSystem
    system = HypothesisTestingSystem()
    for claim in ("X reduces Y", "X reducing Y", "X increased Y", "X improves Y"):
        assert system._is_falsifiable(claim) is True, claim
