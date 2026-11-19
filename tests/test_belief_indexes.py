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

from datetime import datetime  # noqa: E402
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


def test_the_memory_an_observation_is_of_is_not_stored_twice():
    """`MemoryAgent.hold_belief` leaves `memory_id` out of an evidence row where it is the memory the belief itself
    names, and the reads put it back (`_of_memory`), so what reads evidence sees it either way. On main 2,158,285 of
    2,182,499 evidence rows named the memory their belief already named, at 52 bytes of 345 a row (2026-10-30)."""
    import asyncio
    from core.agents.memory_agent import MemoryAgent, _of_memory

    # Left out because it is the belief's own: put back on the way out.
    assert _of_memory({"source": "taught", "quality": 0.95}, "mem_1") == {
        "source": "taught", "quality": 0.95, "memory_id": "mem_1"}
    # An observation of ANOTHER memory keeps the one it names, and one stored before this is unchanged.
    assert _of_memory({"memory_id": "mem_2"}, "mem_1")["memory_id"] == "mem_2"
    # A belief naming no memory leaves the row as it is, and the text a driver hands back is read as JSON.
    assert _of_memory({"source": "read"}, None) == {"source": "read"}
    assert _of_memory('{"source": "read"}', "mem_1") == {"source": "read", "memory_id": "mem_1"}
    # Nothing but a mapping is touched.
    assert _of_memory(None, "mem_1") is None

    rows = [{"belief_id": "b1", "supports": True, "entry": {"source": "taught"}, "memory_id": "mem_1"},
            {"belief_id": "b1", "supports": False, "entry": {"memory_id": "mem_9"}, "memory_id": "mem_1"},
            {"belief_id": "b2", "supports": True, "entry": {"source": "read"}, "memory_id": None}]

    class Store:
        def __init__(self):
            self.asked = []

        async def execute_query(self, sql, *args, **kw):
            self.asked.append(sql)
            if "e.belief_id = $1" in sql:
                return [r for r in rows if r["belief_id"] == args[0][0]]
            return rows
    store = Store()
    agent = MemoryAgent.__new__(MemoryAgent)
    agent._memory_db = lambda: store  # type: ignore[method-assign]
    for_it, against = asyncio.run(agent.belief_evidence("b1"))
    assert for_it == [{"source": "taught", "memory_id": "mem_1"}], for_it
    assert against == [{"memory_id": "mem_9"}], against
    every = asyncio.run(agent.every_belief_evidence())
    assert every["b1"][0] == [{"source": "taught", "memory_id": "mem_1"}], every["b1"]
    assert every["b2"][0] == [{"source": "read"}], every["b2"]
    # The memory is read beside the row, never guessed: both reads join the belief it belongs to.
    assert all("unified.beliefs" in sql for sql in store.asked), store.asked


def test_the_review_counts_what_bore_a_belief_out_and_changes_no_belief():
    """THE SUBSTRATE READS ITS OWN EVIDENCE BACK. Reflection is belief-graph hygiene -- decay, consistency,
    volatility, schema decay -- and not one of its steps opens `unified.belief_evidence`. So the World Model held
    1,022,193 beliefs, 99.95% of them at a confidence of 0.9 or more, alongside 1,783,544 observations of whether
    they had actually been borne out, and never once looked (lyric_db, 2026-11-19).

    A WITHDRAWAL IS NOT A FAILURE. Half of all opposing evidence carries `withdraws` -- a teaching taken back,
    whose quality is what that word was contributing so that taking it back removes exactly what it added.
    Counted as failures, the worst belief in the model read as borne out 49.4% of the time; counted rightly,
    66.1%. This test pins that distinction, because getting it wrong is what made a sound belief look broken.

    AND IT CHANGES NO BELIEF: it writes `supported`, `opposed` and `reviewed_at`, and nothing else. A belief borne
    out two times in three is a good belief that is not a certainty, and saying so is not overruling it."""
    import asyncio

    class Store:
        """A store that answers the review's one statement, standing in for Postgres."""

        def __init__(self):
            self.rows = {"b1": {"supports": [8, 0, 0]}, "b2": {"supports": [6, 3, 5]}}
            self.written = []
            self.frozen = "release"

        def schema_stores(self):
            return ["main", self.frozen]

        def is_frozen_store(self, store):
            return store == self.frozen

        async def execute_query(self, query, params=None, **kw):
            if query.strip().startswith(("ALTER", "CREATE")):
                return None
            assert "withdraws" in query, "a withdrawal must not be counted as a failure"
            assert "SET supported" in query and "opposed" in query and "reviewed_at" in query
            assert "confidence" not in query and "log_odds" not in query, "the review moves no belief"
            after, _limit = params
            take = sorted(k for k in self.rows if k > after)
            if not take:
                return []
            self.written.append((kw.get("store"), tuple(take)))
            return [{"belief_id": k} for k in take]

    system = BayesianUncertaintySystem.__new__(BayesianUncertaintySystem)
    system.unified_db = Store()
    system._beliefs_schema_ready = True

    got = asyncio.run(system.review_against_evidence(batch=10))
    assert got["reviewed"] == 2, got
    # A FROZEN RELEASE IS READ, NEVER WRITTEN: its rows are what they were when it was cut.
    assert [store for store, _ in system.unified_db.written] == ["main"], system.unified_db.written


def test_the_review_stands_down_for_a_person_and_says_where_it_stopped():
    """The review may only run in downtime. It walks in `belief_id` order so it can stop where it is and be taken
    up from there, rather than starting again and never reaching its end on a substrate that is used at all."""
    import asyncio
    from core.utils.give_way import StandDown

    class Store:
        def __init__(self):
            self.ids = [f"b{n:03d}" for n in range(200)]
            self.seen = []

        def schema_stores(self):
            return ["main"]

        def is_frozen_store(self, store):
            return False

        async def execute_query(self, query, params=None, **kw):
            if query.strip().startswith(("ALTER", "CREATE")):
                return None
            after, limit = params
            take = [k for k in self.ids if k > after][:limit]
            self.seen.extend(take)
            return [{"belief_id": k} for k in take]

    async def run():
        asyncio.get_running_loop().slow_callback_duration = 0.0    # ask at every give-way
        system = BayesianUncertaintySystem.__new__(BayesianUncertaintySystem)
        system.unified_db = Store()
        system._beliefs_schema_ready = True
        asked = {"n": 0}

        def busy_after_three():
            asked["n"] += 1
            return asked["n"] > 3

        try:
            await system.review_against_evidence(batch=10, stand_down=busy_after_three)
            raise AssertionError("it did not stand down")
        except StandDown as stood:
            stopped_at = stood.at
        done = len(system.unified_db.seen)
        assert stopped_at == system.unified_db.seen[-1], f"it said where it got to: {stopped_at}"
        assert 0 < done < 200, f"it stopped part way: {done}"

        # Taken up from there, it reviews the rest and none of what it already did.
        again = BayesianUncertaintySystem.__new__(BayesianUncertaintySystem)
        again.unified_db = Store()
        again._beliefs_schema_ready = True
        got = await again.review_against_evidence(resume_at=stopped_at, batch=1000)
        assert got["reviewed"] == 200 - done, f"it took up where it stopped: {got} after {done}"

    asyncio.run(run())


def test_the_belief_graph_is_kept_and_read_back_at_a_start():
    """EVERYTHING ELSE THE BELIEF AUTHORITY HOLDS HAS A TABLE AND THE GRAPH HAD NONE. The beliefs, their
    evidence, the known unknowns and each domain's volatility are all written and read back; which belief
    contradicts, implies or supports which was built in memory, used by the process that built it, and gone at
    the next start. So `check_belief_consistency` walked an empty dict and reported no contradiction in a store
    of a million beliefs -- not because it was broken, but because it was reading a structure nobody had saved.

    An edge is kept only where both of its beliefs are held: propagation walks beliefs, and an edge to a belief
    that is gone leads nowhere."""
    import asyncio
    from core.reasoning.bayesian_uncertainty import BeliefRelationship, RelationType

    class Store:
        def __init__(self):
            self.kept = []

        def schema_stores(self):
            return ["main", "release"]

        def is_frozen_store(self, store):
            return store == "release"

        async def execute_query(self, query, params=None, **kw):
            if query.strip().startswith(("ALTER", "CREATE")):
                return None
            if query.strip().startswith("INSERT"):
                self.kept.append((kw.get("store"), params))
                return None
            return [{"relationship_id": "rel_a", "source_belief_id": "b1", "target_belief_id": "b2",
                     "relation_type": "contradicts", "strength": 0.8, "confidence": 0.9,
                     "discovered_by": "a teacher"},
                    # An edge to a belief this start does not hold leads nowhere and is passed over.
                    {"relationship_id": "rel_gone", "source_belief_id": "b1", "target_belief_id": "b_missing",
                     "relation_type": "implies", "strength": 1.0, "confidence": 1.0, "discovered_by": "x"}]

    system = BayesianUncertaintySystem.__new__(BayesianUncertaintySystem)
    system.unified_db = Store()
    system._beliefs_schema_ready = True
    system.beliefs = {"b1": object(), "b2": object()}
    system.relationships = {}
    from collections import defaultdict
    system.forward_edges, system.backward_edges = defaultdict(set), defaultdict(set)

    loaded = asyncio.run(system.load_relationships())
    assert loaded == 1, "an edge whose beliefs are not both held is passed over"
    kept = system.relationships["rel_a"]
    assert kept.relation_type is RelationType.CONTRADICTS and kept.strength == 0.8
    assert kept.discovered_by == "a teacher"
    assert "rel_a" in system.forward_edges["b1"] and "rel_a" in system.backward_edges["b2"]

    # And writing one: the frozen release is never written.
    async def write():
        system.persistence_drops = 0
        system._write_tasks = set()
        system._save_relationship(BeliefRelationship(
            relationship_id="rel_new", source_belief_id="b1", target_belief_id="b2",
            relation_type=RelationType.SUPPORTS, strength=1.0, confidence=1.0, discovered_by="system"))
        await asyncio.gather(*list(system._write_tasks))
    asyncio.run(write())
    assert [store for store, _ in system.unified_db.kept] == ["main"], system.unified_db.kept


def test_fading_is_not_refutation_and_only_what_rests_on_nothing_is_let_go():
    """A belief that drifts to even odds has not been contradicted: nobody has spoken of it lately, which is a
    fact about the conversation and not about the world.

    This let go of any belief at even odds resting on fewer than THREE observations, and in the World Model
    993,357 of 1,022,193 beliefs rest on fewer than three -- 97.2%. While the decay clock reset at every start
    nothing reached the band and nothing was ever deleted; the moment the clock becomes real, that threshold
    would delete most of what the substrate knows for not having been mentioned. What is let go is what rests on
    NOTHING, which is the belief `is_grounded` refuses to write in the first place."""
    import inspect
    source = inspect.getsource(BayesianUncertaintySystem.apply_temporal_decay_to_all_beliefs)
    assert "_evidence_count == 0" in source, "a belief resting on an observation is kept, however far it fades"
    assert "_evidence_count < 3" not in source, "the old threshold would delete 97.2% of the World Model"


def test_time_alone_is_not_evidence_so_a_settled_domain_does_not_fade():
    """HOW FAST A DOMAIN FADES IS HOW MUCH IT MOVES, and nothing else.

    A constant 0.01 an hour was added to every domain however settled it was, and λ was floored at 0.005 so no
    domain could stop fading at all. `english` holds 98.9% of the World Model and its beliefs change by 0.00055
    on average, yet it faded at 0.01005 an hour -- 99.5% of that a constant with nothing to do with English. With
    the decay clock measuring real time, that constant would have taken 842,741 beliefs (82.4%) to "no opinion"
    in one pass. That is not modelling uncertainty about the world; it is introducing uncertainty because time
    has passed.

    A settled belief stays revisable -- by contradiction, by correction, by discovery -- and simply not by the
    clock. Measured against the World Model with each domain at what it actually moves: 842,741 -> 727."""
    system = BayesianUncertaintySystem.__new__(BayesianUncertaintySystem)
    from collections import defaultdict
    system.domain_volatility = defaultdict(lambda: 0.01)
    system.domain_belief_changes = defaultdict(list)
    system.domain_regime_shifts = defaultdict(int)
    system.stats = defaultdict(int)

    # A domain nothing moves in reaches ZERO, where the floor used to hold it at 0.005.
    system.domain_belief_changes["english"] = [0.0] * 20
    system._update_domain_volatility("english", 0.0)
    assert system.domain_volatility["english"] == 0.0, system.domain_volatility["english"]

    # One that does move still fades, in proportion to how much.
    system.domain_belief_changes["reading"] = [0.1] * 20
    system._update_domain_volatility("reading", 0.1)
    assert system.domain_volatility["reading"] > 0.0


def test_a_belief_may_hold_a_decay_rate_apart_from_its_domains():
    """A belief's own rate decides, and `None` follows its domain. The field existed and decided nothing: it was
    overwritten from the domain at every update, so no override could survive one observation, and the decay
    function asked the domain directly and never the belief."""
    import inspect
    from collections import defaultdict
    system = BayesianUncertaintySystem.__new__(BayesianUncertaintySystem)
    system.domain_volatility = defaultdict(lambda: 0.02)
    system.stats = defaultdict(int)

    settled = BayesianBelief(belief_id="b1", claim="whales are mammals", domain="english",
                             prior_probability=0.5, likelihood=0.5, posterior_probability=0.937)
    assert settled.decay_rate is None, "a belief follows its domain unless given a rate of its own"
    settled.last_evidence_time = datetime(2020, 1, 1)
    held = settled.log_odds
    settled.decay_rate = 0.0                      # this one does not fade with time at all
    assert system._apply_temporal_decay(settled) == held, "a rate of 0.0 fades by nothing, however long it is"

    drifting = BayesianBelief(belief_id="b2", claim="the queue is busy", domain="english",
                              prior_probability=0.5, likelihood=0.5, posterior_probability=0.937)
    drifting.last_evidence_time = datetime(2020, 1, 1)
    assert system._apply_temporal_decay(drifting) != drifting.log_odds, "with none of its own it follows its domain"

    # And an update does not overwrite what the belief was given.
    source = inspect.getsource(BayesianUncertaintySystem.update_belief)
    assert "belief.decay_rate = self.domain_volatility" not in source, "an update must not take the override away"
