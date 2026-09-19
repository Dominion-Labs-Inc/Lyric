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
