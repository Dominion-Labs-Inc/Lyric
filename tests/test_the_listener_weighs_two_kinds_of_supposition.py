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

AND A THIRD KIND WAS STILL INSIDE `proposed`: a word said in another's place. `Reading.supposed` counts it as a
link proposed ("A frame's word read through another said in its place is supposed as a link is"), so a reading
that took "was" for the "is" of a frame weighed exactly as one that had to propose a link. They are different
questions -- the first supposes a WORD stands for another, the second that a FILLER belongs in a slot -- and the
first is what "The rock was heavy." turns on: it builds the tensed reading through the taught "was" frame AND
the tenseless one through the "is" frame, and took the tenseless one by 0.42 nats.

    said_for   0: 98.5%   1: 1.3%   2: 0.2%   3 or more: none

TWO LEVELS, measured over 20,446 readings of the 238 of 300 sampled lesson sentences that read more than one way:
301 readings say a word in another's place, 31 of them twice, and none three times. Two levels put all 301
together; three would hand the last 31 sightings of its own, which is too thin to learn a worth from. `proposed`
keeps its six -- taking `said_for` out moves it from 98.4/87.5/59.3/26.4/3.2/2.8 to
98.3/87.3/58.9/26.1/2.8/2.5.

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
    assert dr.LISTENING_LEVELS["said_for"] == 2, "301 of 20,446 readings, none three times: two levels"
    assert set(dr.Weighed._fields) >= {"proposed", "misplaced", "said_for"}
    assert "fit" not in dr.Weighed._fields


def test_a_reading_is_asked_for_each_kind_and_never_for_their_sum():
    source = inspect.getsource(dr.weighed)
    assert "sum(reading.supposed[2:])" not in source, "the three added together again"
    assert "reading.supposed[3] + reading.supposed[4]" in source, "misfits and apart are the one question"
    assert "reading.supposed[2] - reading.said_for" in source, "and the links proposed are another"
    weighing = inspect.getsource(dr._weighing)
    assert "misplaced = reading.misfits + reading.apart" in weighing
    # A WORD SAID IN ANOTHER'S PLACE IS ASKED APART FROM A LINK PROPOSED, so `proposed_links` no longer adds it.
    assert "reading.said_for" not in weighing.split("proposed_links =")[1].split("\n")[0]
    assert "reading.said_for" in weighing, "it is counted, as its own"
    assert "cost[0], cost[1] + cost[2]" in weighing, "a sense's own cost is split the same way"


def test_the_packed_search_carries_both_counts():
    """`_choices` works the best choice of senses out part by part over a small state, so both have to be in it."""
    assert len(dr._LEVELS) == 5
    assert dr._LEVELS == (dr.LISTENING_LEVELS["known"] - 1, dr.LISTENING_LEVELS["defined"] - 1,
                          dr.LISTENING_LEVELS["proposed"] - 1, dr.LISTENING_LEVELS["misplaced"] - 1,
                          dr.LISTENING_LEVELS["said_for"] - 1)
    assert dr._levelled((0, 0, 0, 0), (1, 1, 1, 1)) == (1, 1, 1, 1)
    # Each capped at its own last level, and one kind never spills into another.
    assert dr._levelled((9, 9, 9, 9, 9), (9, 9, 9, 9, 9)) == dr._LEVELS
    assert dr._levelled((0, 0, 5, 0, 0), (0, 0, 5, 0, 0)) == (0, 0, dr._LEVELS[2], 0, 0)
    score = inspect.getsource(dr._score_at)
    assert 'worths.get(("proposed"' in score and 'worths.get(("misplaced"' in score
    assert 'worths.get(("said_for"' in score, "the packed path weighs it too, or the two paths differ"


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
    made = dr.Weighed(reading=None, known=9, defined=9, proposed=9, misplaced=9, said_for=9,
                      activation=0.0, derivation=0.0)
    levels = dr.listening_levels(made)
    assert levels == {e: n - 1 for e, n in dr.LISTENING_LEVELS.items()}, "each capped at its own last level"
    assert dr.listening_levels(dr.Weighed(None, 0, 0, 0, 0, 0, 0.0, 0.0)) == {e: 0 for e in dr.LISTENING_LEVELS}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_word_said_in_anothers_place_is_not_counted_as_a_link_proposed():
    """`weighed` and `_weighing` must take `said_for` out of `proposed` the SAME way, or the path that counts the
    worths and the path that decides a packed utterance measure different things (`lyric_weighed_does_not_decide`).

    `Reading.supposed[2]` counts a word said in another's place among the links proposed -- its own docstring says
    so -- so `weighed`, which reads `supposed`, must subtract it where `_weighing`, which builds the count from
    its parts, simply never adds it."""
    counting = inspect.getsource(dr.weighed)
    assert "reading.supposed[2] - reading.said_for" in counting, \
        "supposed[2] counts said_for among the links proposed"
    assert "reading.said_for," in counting, "and it is passed as its own channel"
    deciding = inspect.getsource(dr._weighing)
    assert "len(reading.proposed) + (_composed_supposes" in deciding, "built from its parts, said_for not among them"


def test_the_counted_state_stays_a_small_capped_tuple():
    """`_choices` eliminates a variable at a time and keeps a few choices per counted state, so the state must stay
    a SMALL capped integer tuple computable from one reading alone. A channel that needed to rank across readings
    could not live here at all."""
    assert all(isinstance(cap, int) and 0 <= cap <= 8 for cap in dr._LEVELS)
    assert len(dr._LEVELS) == len(dr.LISTENING_LEVELS)
    # `said_for` is the reading's own and turns on no word's sense, so the per-sense states carry 0 for it.
    choices = inspect.getsource(dr._choices)
    assert "min(misplaced, _LEVELS[3]), 0)" in choices, "per-sense costs add nothing to said_for"
    assert "_LEVELS[1]), 0, 0, 0)" in choices, "nor do the facts between two words"
