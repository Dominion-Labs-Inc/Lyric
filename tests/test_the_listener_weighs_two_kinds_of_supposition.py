#!/usr/bin/env python3
"""What a reading supposed is two questions to the listener, and neither saturates where real sentences live.

`Reading.supposed` is (loose, new words, proposed, misfits, apart) and is compared IN ORDER, never added, because
the three suppositions are different kinds: a proposed link is "nothing taught says this word stands for this
thing here", while misfits and fillers apart are how badly what was put in a slot sits there. The listener added
them -- `fit = sum(supposed[2:])` -- so one `apart` bought one `proposed`:

    'Are Psalms part of Old Testament?'
      part_of(Psalms, old testament)                     supposed (2, 0, 1) -> fit 3
      has_property(?v0, old) & instance_of(?v0, legal document will) & part_of(psalms, ?v0)
                                                         supposed (3, 0, 0) -> fit 3

Both came to 3, so the channel said exactly the same of the reading through the taught `part of` frame and the
taught name as of the one that reads "Testament" for a will.

AND THE SUM SATURATED. `fit` had four levels, so everything from 3 up was one level. Measured over every reading
of the 235 of 300 sampled lesson sentences that read more than one way -- the only sentences `listening_counts`
counts, so the distribution the channel is learned on -- 74.1% of all readings sat on that top level, and the
counts held for it on 2026-11-19 were 186,351 readings that were NOT the one meant and not one that was. Three
quarters of what the listener saw carried a mark that had never once gone with the right answer.

    proposed   0: 1.6%   1: 11.0%   2: 28.2%   3: 32.8%   4: 23.2%   5 or more: 3.2%
    misplaced  0: 51.9%  1: 32.6%   2: 15.5%

So six levels and three: 96.8% of readings land on a level of their own. RENAMED rather than reshaped, because
the counts held under "fit at N" measure the three added together and `listening_worths` smooths with Laplace --
a level with no count of its own beside levels that have one is given a POSITIVE worth, so an unseen level would
read as evidence FOR. With no counts at all for a name, every level comes out `ln(1) = 0`.

Recounted over all 3,237 lesson sentences on 2026-11-20, `proposed` runs +6.38, -0.78, -3.93, -4.23, -4.96,
-5.97: monotone, which is what the old channel could not be.

Nothing here needs a store.
"""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.semantics import derived_reader as dr


def test_the_two_kinds_of_supposition_are_weighed_apart():
    assert "fit" not in dr.LISTENING_LEVELS, "the sum is what made one kind buy the other"
    assert dr.LISTENING_LEVELS["proposed"] == 6
    assert dr.LISTENING_LEVELS["misplaced"] == 3
    assert set(dr.Weighed._fields) >= {"proposed", "misplaced"}
    assert "fit" not in dr.Weighed._fields


def test_a_reading_is_asked_for_each_kind_and_never_for_their_sum():
    source = inspect.getsource(dr.weighed)
    assert "sum(reading.supposed[2:])" not in source, "the three added together again"
    assert "reading.supposed[2], reading.supposed[3] + reading.supposed[4]" in source
    weighing = inspect.getsource(dr._weighing)
    assert "misplaced = reading.misfits + reading.apart" in weighing
    assert "cost[0], cost[1] + cost[2]" in weighing, "a sense's own cost is split the same way"


def test_the_packed_search_carries_both_counts():
    """`_choices` works the best choice of senses out part by part over a small state, so both have to be in it."""
    assert len(dr._LEVELS) == 4
    assert dr._LEVELS == (dr.LISTENING_LEVELS["known"] - 1, dr.LISTENING_LEVELS["defined"] - 1,
                          dr.LISTENING_LEVELS["proposed"] - 1, dr.LISTENING_LEVELS["misplaced"] - 1)
    assert dr._levelled((0, 0, 0, 0), (1, 1, 1, 1)) == (1, 1, 1, 1)
    # Each capped at its own last level, and one kind never spills into another.
    assert dr._levelled((9, 9, 9, 9), (9, 9, 9, 9)) == dr._LEVELS
    assert dr._levelled((0, 0, 5, 0), (0, 0, 5, 0)) == (0, 0, dr._LEVELS[2], 0)
    score = inspect.getsource(dr._score_at)
    assert 'worths.get(("proposed"' in score and 'worths.get(("misplaced"' in score


def test_a_name_nothing_was_counted_under_weighs_nothing():
    """What makes the rename safe: with no counts at all, every level is worth `ln(1) = 0` -- never a positive
    worth for a level nobody has seen."""
    worths = dr.listening_worths({})
    assert set(worths) == {(e, l) for e, n in dr.LISTENING_LEVELS.items() for l in range(n)}
    assert all(w == 0.0 for w in worths.values()), worths


def test_a_level_seen_only_among_the_readings_not_meant_counts_against_it():
    """The shape the old `fit` top level had: 186,351 seen, never once the one meant."""
    counts = {("proposed", 0, True): 2000, ("proposed", 0, False): 400,
              ("proposed", 5, False): 186351}
    worths = dr.listening_worths(counts)
    assert worths[("proposed", 0)] > 0, "supposing nothing went with being right"
    assert worths[("proposed", 5)] < 0, "supposing five or more never did"


def test_every_level_of_every_channel_is_one_the_listener_can_show():
    """`listening_levels` reads each channel off the reading by name, so a channel in the table with no field on
    `Weighed` would be counted for ever at nothing."""
    made = dr.Weighed(reading=None, known=9, defined=9, proposed=9, misplaced=9, activation=0.0, derivation=0.0)
    levels = dr.listening_levels(made)
    assert levels == {e: n - 1 for e, n in dr.LISTENING_LEVELS.items()}, "each capped at its own last level"
    assert dr.listening_levels(dr.Weighed(None, 0, 0, 0, 0, 0.0, 0.0)) == {e: 0 for e in dr.LISTENING_LEVELS}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
