#!/usr/bin/env python3
"""Beliefs are found by claim and by domain through one index, never a scan.

With 198k beliefs a scan cost 19-40 ms on the event loop per memory store and
per completion check. It also disagreed with the index: for a claim held by
more than one belief (1,902 such claims in the store), observe_claim moved the
most recently registered belief while belief_for_claim returned the first one
it scanned -- learning updated one belief and completion read another.

Runs without an event loop, so no belief write is scheduled.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.reasoning.bayesian_uncertainty import (  # noqa: E402
    BayesianBelief, BayesianUncertaintySystem)


def _belief(system, belief_id, claim, domain):
    belief = BayesianBelief(belief_id=belief_id, claim=claim, domain=domain,
                            prior_probability=0.5, likelihood=1.0,
                            posterior_probability=0.5, entropy=1.0)
    system._register_belief(belief)
    return belief


def test_claim_reads_return_the_belief_observation_moves():
    system = BayesianUncertaintySystem()
    _belief(system, "b_old", "Water boils at 100 C", "physics")
    newer = _belief(system, "b_new", "water  boils at 100 c", "physics")
    assert system.belief_for_claim("WATER BOILS AT 100 C") is newer
    moved = system.observe_claim("water boils at 100 c", "physics")
    assert moved.belief_id == "b_new"
    assert system.belief_for_claim("water boils at 100 c").belief_id == "b_new"


def test_removing_one_holder_of_a_claim_keeps_the_other_findable():
    system = BayesianUncertaintySystem()
    older = _belief(system, "b_old", "iron rusts", "chemistry")
    _belief(system, "b_new", "iron rusts", "chemistry")
    system._unregister_belief("b_new")
    assert system.belief_for_claim("iron rusts") is older
    system._unregister_belief("b_old")
    assert system.belief_for_claim("iron rusts") is None
    assert system.beliefs_for_domain("chemistry") == []


def test_domain_reads_hold_exactly_that_domains_beliefs():
    system = BayesianUncertaintySystem()
    _belief(system, "a", "a claim", "Biology ")
    _belief(system, "b", "b claim", "biology")
    _belief(system, "c", "c claim", "physics")
    assert {b["belief_id"] for b in system.beliefs_for_domain("BIOLOGY")} == {"a", "b"}
    created = system.create_belief(claim="d claim", domain="physics")
    assert {b["belief_id"] for b in system.beliefs_for_domain("physics")} == {"c", created.belief_id}


def test_a_witness_that_withdraws_its_word_stands_on_neither_side():
    """A pair the teacher no longer teaches takes its word back (`withdraw_observation`): the opposite step, and the
    witness stands on neither side, however the index is read again. Its uses go with it; a later word counts."""
    system = BayesianUncertaintySystem()
    system.observe_claim("a glomph is fizzly", "english", supports=True, quality=0.9, observation="l1:a", uses=5)
    system.observe_claim("a glomph is fizzly", "english", supports=True, quality=0.9, observation="l1:b")
    system.observe_claim("a glomph is fizzly", "english", supports=False, quality=0.9, observation="l1:c")
    belief = system.belief_for_claim("a glomph is fizzly")
    assert (system.witnesses(belief, supports=True), system.witnesses(belief, supports=False)) == (2, 1)
    assert system.uses_for(belief) == 6
    before = belief.log_odds

    assert system.withdraw_observation("a glomph is fizzly", "l1:a") is belief
    assert (system.witnesses(belief, supports=True), system.witnesses(belief, supports=False)) == (1, 1)
    assert system.uses_for(belief) == 1
    assert belief.log_odds < before
    assert system.withdraw_observation("a glomph is fizzly", "l1:a") is None, "a word withdrawn is withdrawn once"
    assert system.withdraw_observation("a glomph is fizzly", "l1:c") is belief
    assert (system.witnesses(belief, supports=True), system.witnesses(belief, supports=False)) == (1, 0)

    belief.evidence_index = None        # read again from the evidence, for the claim first and against it after
    assert (system.witnesses(belief, supports=True), system.witnesses(belief, supports=False)) == (1, 0)
    assert system.uses_for(belief) == 1

    system.observe_claim("a glomph is fizzly", "english", supports=True, quality=0.9, observation="l1:a")
    assert system.witnesses(belief, supports=True) == 2, "a word said after the withdrawal stands"
    belief.evidence_index = None
    assert (system.witnesses(belief, supports=True), system.witnesses(belief, supports=False)) == (2, 0)


def test_a_belief_let_go_is_gone_from_what_is_held():
    system = BayesianUncertaintySystem()
    system.observe_claim("a flerm is a glomph", "english", supports=True, quality=0.9, observation="l1:a")
    belief = system.belief_for_claim("a flerm is a glomph")
    import asyncio
    asyncio.run(system.let_go(belief.belief_id))
    assert system.belief_for_claim("a flerm is a glomph") is None
    assert belief.belief_id not in {b.belief_id for b in system.held_in_domain("english")}
    assert belief.belief_id not in system._pending_writes


def test_a_word_withdrawn_takes_back_only_what_it_still_counts_for():
    """Taking back some of the words a claim rests on leaves it held as the rest hold it, never past even; taking back
    all of them leaves it even. The log-odds fade with time, so a word counts for less than the step it was given at;
    taking back whole steps put "blue" names blue, still held by others, at 0.195."""
    import time as _time
    system = BayesianUncertaintySystem()
    for observation in ("l1:a", "l1:b", "l1:c"):
        system.observe_claim('"blue" names blue', "english", supports=True, quality=0.95, observation=observation)
    belief = system.belief_for_claim('"blue" names blue')
    belief.hold(belief.log_odds * 0.3)                          # faded since, as days of decay leave it
    for entry in belief.evidence_for:
        entry["at"] = _time.time() - 3 * 24 * 3600              # all three given three days ago
    belief.evidence_index = None
    system.withdraw_observation('"blue" names blue', "l1:a")
    system.withdraw_observation('"blue" names blue', "l1:b")
    assert belief.log_odds > 0, "the word that still stands holds it"
    system.withdraw_observation('"blue" names blue', "l1:c")
    assert abs(belief.log_odds) < 1e-6, "nothing stands: even"


def test_a_word_revised_takes_back_only_what_it_still_counts_for():
    """A witness that turns its word around (`observe_claim` the other way) withdraws what its earlier word still
    counts for, as `withdraw_observation` does, and its new word counts once. Taking back the step it was given at
    left a claim other witnesses hold far past where their words and the new one put it."""
    import time as _time
    system = BayesianUncertaintySystem()
    for observation in ("l1:a", "l1:b", "l1:c"):
        system.observe_claim('"cold" names cold', "english", supports=True, quality=0.95, observation=observation)
    belief = system.belief_for_claim('"cold" names cold')
    belief.hold(belief.log_odds * 0.3)                          # faded since, as days of decay leave it
    for entry in belief.evidence_for:
        entry["at"] = _time.time() - 3 * 24 * 3600              # all three given three days ago
    belief.evidence_index = None
    held = belief.log_odds
    system.observe_claim('"cold" names cold', "english", supports=False, quality=0.95, observation="l1:a")
    standing = held * 2 / 3                                     # the two words that still stand
    assert abs(belief.log_odds - (standing - 3.0 * 0.95)) < 1e-6
    assert (system.witnesses(belief, supports=True), system.witnesses(belief, supports=False)) == (2, 1)


def test_a_word_taken_back_is_no_reversal_and_no_change_in_the_domain():
    """A witness taking back its word tells nothing new of the claim. Taking back a belief's only word leaves it at
    exactly even, not a hair past it; it is no reversal, and it does not move how fast the domain's beliefs fade.
    Counted as both, the teacher withdrawing facts it no longer taught was a regime shift each, and raised the decay
    rate of every belief in the domain (2026-10-12). A word said the other way is evidence, and counts."""
    system = BayesianUncertaintySystem()
    system.observe_claim("a flerm is a glomph", "english", supports=True, quality=0.9, observation="wordnet_3.0")
    belief = system.belief_for_claim("a flerm is a glomph")
    changes, shifts, rate = (list(system.domain_belief_changes["english"]), system.domain_regime_shifts["english"],
                             system.domain_volatility["english"])
    system.withdraw_observation("a flerm is a glomph", "wordnet_3.0")
    assert belief.log_odds == 0.0 and belief.posterior_probability == 0.5, "taken back, nothing stands: even"
    assert system.domain_regime_shifts["english"] == shifts, "no reversal"
    assert system.domain_belief_changes["english"] == changes and system.domain_volatility["english"] == rate

    system.observe_claim("a flerm is a glomph", "english", supports=True, quality=0.9, observation="l1:a")
    system.observe_claim("a flerm is a glomph", "english", supports=False, quality=0.9, observation="l1:a")
    assert belief.log_odds < 0 and system.domain_regime_shifts["english"] == shifts + 1, \
        "a witness turned around: its word the other way is evidence, and reverses the belief"


def test_learning_a_belief_is_no_change_in_its_domain():
    """A belief's first word moves it from even to where that word puts it: learning it, not the domain changing.
    Counted as volatility, a pass that taught a domain made its beliefs fade five times as fast. A later word on a
    belief already held is a change of mind, and counts."""
    system = BayesianUncertaintySystem()
    for n in range(20):
        system.observe_claim(f"a flerm {n} is a glomph", "tools", supports=True, quality=0.9, observation="l1:a")
    assert system.domain_belief_changes["tools"] == [] and system.domain_volatility["tools"] == 0.01
    system.observe_claim("a flerm 0 is a glomph", "tools", supports=False, quality=0.9, observation="l1:b")
    assert len(system.domain_belief_changes["tools"]) == 1
