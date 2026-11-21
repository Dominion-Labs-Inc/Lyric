"""WHAT A CHANGE TO THE READER DID TO READING, in minutes instead of an hour and a quarter.

Reading is measured here by sweeping all 251 tool descriptions, the 18 opposite pairs and the prose: 4,742 s, and
serial, because two starts of this size do not fit on this machine at once. On 2026-11-12 one defect took six of
those sweeps, about eight hours of waiting, and three of the versions it took to get right were wrong in ways a
handful of sentences would have shown:

  * pricing a sense by how often it was met double-counted the listener's own activation, which breaks
    "Bats are clubs." and "To nudge is to get." -- two tests in `tests/test_derived_reading.py`, 5.86 s;
  * asking the share of the filler found rather than the word written sent a widened sense to the floor, which
    breaks the same two;
  * charging a composed reading the price of picking a thing out of 155,767 words broke EVERY bare imperative,
    and the tests could not have shown it: each builds its own view holding a handful of words, and the defect is
    a function of how many words there are. That one needed the real store -- and twelve descriptions, not 251.

So: the two tests, and then the smallest set against the live store that answers each category a reader change
can break. Every case is recorded with what the system does TODAY, the broken ones included, so a case that comes
right reports BETTER and a case that stops working reports WORSE. Nothing here is an assertion of what reading
ought to do; the baseline is a measurement, and `--record` is how it is replaced.

Reads only: no conversation remembers, the descriptions are read through the reading alone
(`AutonomousCoordinator.doing_said`, which remembers nothing), and no store is written.

WHAT EACH CASE COSTS IS RECORDED BESIDE WHAT IT SAYS, because a reader change is two questions and this answered
only one. Four quantities per case, which are the four a design whose knowledge is READ rather than frozen into
weights has to be able to show as it learns more:

    what it reads     the meaning taken, and EVERY reading built -- so a reading that stops being built is a
                      capability lost, and is reported as one, not as a faster run
    candidates        the readings handed to the listener, and the signs the grammar's chart held to make them
    latency           seconds, per case
    memory            the process's resident size, per case

A READING NO LONGER BUILT IS THE ONE THING THAT MUST NEVER PASS. Making the chart cheaper divides into mechanisms
that cannot lose a reading (sharing work, packing a cell, an A* order under an admissible bound) and mechanisms
that can (a supertagger's beam, pruning on a coarse pass, and the `how_many` beam `Grammar.charts` ALREADY runs,
whose cost is measured: 54.2% chosen right where an exhaustive chart held the right reading for 61.8%, so 7.6
points thrown away inside the chart). This file is the evidence for the first kind and the place the second kind's
ceiling is written down. It is evidence over these cases, never a proof: for an exact mechanism the proof is the
argument, and what is recorded here is that the argument held where it was looked at.

  POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 scripts/check_reading.py [--record]
      [--skip-tests] [--baseline PATH]

Exit 0 where nothing is worse, 1 where anything is.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BASELINE = Path(__file__).resolve().parent / "reading_baseline.json"

#: The two tests holding the minimal pairs that catch a sense priced by how often it was met, or asked of the
#: filler found instead of the word written. They build their own small view, so they are seconds and they say
#: nothing about how many words the store holds.
TESTS = ("test_a_word_held_in_a_shape_for_one_thing_reads_as_every_thing_its_word_names",
         "test_a_word_reads_where_its_class_stands_however_it_is_written_and_whatever_else_it_names")

#: THE DESCRIPTIONS THAT HAVE MOVED, which is why they are named rather than sampled: each read as an order on
#: 11-10 and as nothing on 11-12, and three of the eight came back on 11-12 evening.
MOVED = ("Analyze Python code structure (imports, functions, classes, etc).",
         "Apply transformations to data (select fields, rename, etc).",
         "Find TODO, FIXME, HACK, and XXX comments in code.",
         "Generate cryptographically secure random password.",
         "Sort data by field.",
         "Validate JSON data.",
         "Validate XML data.",
         "Validate YAML data.")
#: How many more are taken from the registry, in name order, so a break that takes the whole category shows here
#: and not only in the ones already known to be fragile. Pinned into the baseline, so later runs read the same.
SAMPLED = 8

#: Four of the eighteen: the two taught, and the two held pairs that came right last.
PAIRS = (("big", "small"), ("good", "bad"), ("able", "unable"), ("absolute", "relative"))

#: The prose forced composing exists for, and the three sentences that read wrongly in their own ways.
PROSE = ("A whale breathes air through a blowhole.",
         "Do whales breathe air?",
         "The rock was heavy.",
         "The note was long.",
         "Does sorted return a new list?")

#: THE SENTENCES THE COST ACTUALLY LIVES IN, which none of the above is: every case above is short, and a chart
#: is `n` cubed over its stretches with the signs in each cell squared inside, so what a reader change does to a
#: long sentence cannot be read off a short one. These two are the first two sentences of UNDERSTANDS-PROSE-02's
#: Rain text, whose turns cost 922.5 s and 925.3 s on 2026-11-17 -- the measurement that found the chart, and
#: the duplicate composing inside it. Read through the reading alone (`read_text` and `heard`), never told to a
#: conversation: a telling writes what it was told, and this file writes nothing.
LONG = ("Rain or rainfall is a form of atmospheric precipitation composed of droplets of water aerosols that have "
        "condensed from atmospheric water vapor and fall by gravity.",
        "Depending on the intensity, rain can be described as a drizzle (very light, sporadic rainfall), a shower "
        "(brief, moderate rainfall), a cloudburst (brief heavy rainfall) or a downpour (prolonged heavy or "
        "“torrential” rainfall).")

#: AND THE SAME TEXT READ AS TEXT, which is a different case and not a longer one. Every sentence of a text is
#: handed whole to held constructions and then to English's grammar before the ends the frames know are used to
#: cut it up, so a paragraph costs about what its sentences cost and reads what they read. It did not: the grammar
#: was offered a whole only where the text was ONE sentence, and a paragraph was cut at the ends frames happen to
#: know, which handed the grammar nine short utterances. Measured on 2026-11-18, before that: these four sentences
#: cost 126.5 s read as one paragraph against 405.0 s read one at a time, 0.31x -- and the cuts landed INSIDE
#: phrases, splitting "water vapor" so that 'vapor and fall by gravity.' read as vapour falling with a property
#: called "and", and reading 'on Earth.' as a count called "on". A paragraph was cheaper by understanding less of
#: it. Nothing measured either until this case was written: UNDERSTANDS-PROSE-02 reads one sentence at a time, and
#: the reading check read nothing longer than one. The frame search over the long stretches a cut-up paragraph
#: tries -- 29 of them, two of 86 and 90 pieces -- was about 22 s, so that is not where its cost went either.
#:
#: The first two sentences are LONG's two, so the record holds the same words read both ways.
PARAGRAPH = " ".join(LONG + (
    "It is also often accompanied by other weather phenomena such as strong wind (rainstorm) and lightning "
    "(thunderstorm), and may be mixed with hail/ice pellet, snow (sleet) and sandstorm (dust rain).",
    "Rain is a major component of the water cycle and is responsible for depositing most of the fresh water "
    "on Earth."))

#: How much more of a case's cost counts as a change in kind rather than the noise of a machine with other work on
#: it. Reported either way; WORSE only past this, and past it on the chart's own signs as well as on the clock,
#: since signs are what the reader decided to do and seconds are what the machine was free to do it in.
COST_IN_KIND = 2.0

QUIET = io.StringIO()

#: What the grammar's chart was asked to do since the last case (`counting`): charts built, cells held, signs kept.
#: Counted around `Grammar.charts` from here rather than inside it, so that measuring reading costs the reader
#: nothing and changes no hash of it.
_COST: Dict[str, int] = {"charts": 0, "cells": 0, "signs": 0}


@contextlib.contextmanager
def counting():
    """`Grammar.charts` tallied while this is open, and left exactly as it was afterwards."""
    from core.semantics.grammar import Grammar
    was = Grammar.charts

    def charts(self, tokens, how_many: int = 1):
        cells = was(self, tokens, how_many)
        _COST["charts"] += 1
        _COST["cells"] += len(cells)
        _COST["signs"] += sum(len(held) for cell in cells.values() for held in cell.values())
        return cells

    Grammar.charts = charts
    try:
        yield
    finally:
        Grammar.charts = was


def spent(since: Dict[str, int], at: float) -> Dict[str, Any]:
    """The four quantities for one case: what its chart cost, how long it took, and what the process held by the
    end of it. Resident size is the process's, not the case's -- a case does not own its memory -- so it is
    recorded as the level reading this case left behind, which is what grows as a store grows."""
    rss = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout
    return {"charts": _COST["charts"] - since["charts"], "cells": _COST["cells"] - since["cells"],
            "signs": _COST["signs"] - since["signs"], "seconds": round(time.time() - at, 1),
            "rss_gb": round(int(rss.strip() or 0) / 1048576, 2)}


def say(*a: Any) -> None:
    print(*a, flush=True)


def built(readings: Tuple[Any, ...]) -> List[str]:
    """EVERY MEANING THE READER BUILT of a sentence, as it writes one, in one order however they were ranked: the
    set a mechanism that cannot lose a reading must leave whole. Ranking belongs to `read`, which records the one
    the listener took; this records what there was to take."""
    return sorted({r.meaning.canonical() for r in readings if r.meaning is not None})


def run_tests() -> Tuple[bool, str]:
    """The two tests, as themselves."""
    at = time.time()
    done = subprocess.run([sys.executable, "-m", "pytest", "tests/test_derived_reading.py",
                           "-k", " or ".join(TESTS), "-q", "--no-header"],
                          cwd=str(ROOT), capture_output=True, text=True)
    last = [line for line in done.stdout.splitlines() if line.strip()]
    return done.returncode == 0, f"{(last[-1] if last else 'nothing said')}  ({time.time()-at:.1f}s)"


async def start() -> Tuple[Any, Any]:
    """Started the way a start starts it, each phase timed, because the start is most of what this costs."""
    from core.agents.memory_agent import get_memory_agent
    from core.agents.autonomous.autonomous_coordinator import AutonomousCoordinator
    import core.semantics.derived_reader as dr

    at = time.time()
    with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
        agent = await get_memory_agent()
        await agent.initialize()
    say(f"  memory            {time.time()-at:6.0f}s")
    at = time.time()
    with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
        coordinator = AutonomousCoordinator()
        await coordinator.initialize()
    say(f"  the coordinator   {time.time()-at:6.0f}s")
    at = time.time()
    with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
        ready = await coordinator.ready_to_read()
    say(f"  ready to read     {time.time()-at:6.0f}s   {ready}")
    # THE 251 DESCRIPTIONS THE START BEGAN READING ARE NOT THIS CHECK'S WORK, and they take an hour. A start
    # reads them behind itself on purpose (`ready_to_read` -> `_tool_reading_task`); left running here they
    # competed with the fourteen this check reads for, which came to 477s where the reading alone is about 70
    # (2026-11-12). Stopped, so that what this reports is its own, and nothing is remembered of it either --
    # which is what a check that writes nothing wants.
    task = getattr(coordinator, "_tool_reading_task", None)
    if task is not None and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        say("  the start's reading of all 251 descriptions stopped: it is not this check's work")

    at = time.time()
    with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
        dr.read_text("Read the contents of a file.")      # the structure worked out, once, as a first read does
    say(f"  the first read    {time.time()-at:6.0f}s")
    # The rules of the grammar memory holds, which is where the grammar comes from.
    say(f"  rules {agent.grammar_view().rules!r}, {len(dr.live_view()):,} construction(s) held")
    return agent, coordinator


async def descriptions(coordinator: Any, pinned: Optional[List[str]]) -> Dict[str, Any]:
    """What each description says the tool does, through the reading alone."""
    registry = coordinator.tool_registry
    if registry is None:
        from core.tools import get_tool_registry
        registry = coordinator.tool_registry = get_tool_registry()
    if pinned is None:
        held = {}
        for name in sorted(set(registry.tools) | set(registry.tool_factories)):
            said = coordinator.said_of(getattr(registry.get_tool(name), "description", ""))
            if said:
                held.setdefault(said, name)
        # THE NAMED ONES MATCHED ON THEIR FIRST FEW WORDS, not on the whole sentence: these were written down
        # from a sweep's own report and a description's own punctuation differs from it ("classes, etc)." against
        # "classes, etc.)."), which silently dropped two of the eight from the first baseline.
        taken: List[str] = []
        for want in MOVED:
            stem = " ".join(want.split()[:5])
            match = next((s for s in held if s.startswith(stem)), None)
            if match and match not in taken:
                taken.append(match)
            elif match is None:
                say(f"  no tool describes itself as {stem!r} any more")
        taken += [s for s in held if s not in taken][:SAMPLED]
        pinned = sorted(taken)
    out: Dict[str, Any] = {}
    for said in pinned:
        at, since = time.time(), dict(_COST)
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            doing = await coordinator.doing_said(said)
        out[said] = {"doing": doing, **spent(since, at)}
    return out


async def opposites() -> Dict[str, Any]:
    """Whether each pair is answered, which is what pricing senses on one scale was for."""
    from core.semantics import derived_reader as dr
    out: Dict[str, Any] = {}
    for one, other in PAIRS:
        said = f"Is {one} the opposite of {other}?"
        at, since = time.time(), dict(_COST)
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            utterances = dr.read_text(said)
            readings = tuple(utterances[0].readings) if utterances else ()
            chosen = await dr.heard(readings) if readings else None
        answered = chosen is not None and any(
            f.relation == "antonym_of" and {f.subject, f.obj} == {one, other} for f in chosen.meaning.facts)
        out[said] = {"answered": answered,
                     "read": chosen.meaning.canonical() if chosen is not None else None,
                     "built": built(readings), **spent(since, at)}
    return out


async def prose() -> Dict[str, Any]:
    """How the prose reads and what the door says of it. The conversation remembers nothing.

    TWO THINGS RECORDED, because neither is the other. The reply is the door's own output, all the way through
    the admission gate, which is where "The note was long." is refused. The reading is the listener's choice of
    what the sentence means (`derived_reader.heard`, the same call the descriptions go through) -- asked without
    the conversation's own activation, so that it says the same thing on two runs rather than carrying a turn's
    history into the record. `Understanding.reading` is not it: that comes from the formalizer chain and was
    empty for all five of these."""
    from core.agents.autonomous.autonomous_coordinator import get_conversation
    from core.semantics import derived_reader as dr
    talk = get_conversation("check_reading")
    out: Dict[str, Any] = {}
    for said in PROSE:
        at, since = time.time(), dict(_COST)
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            utterances = dr.read_text(said)
            readings = tuple(utterances[0].readings) if utterances else ()
            chosen = await dr.heard(readings) if readings else None
            understood = await talk.understand(said, look_up=False)
        out[said] = {"read": chosen.meaning.canonical() if chosen is not None else None,
                     "readings": len(readings), "built": built(readings),
                     "reply": (getattr(understood, "reply", "") or "")[:120],
                     **spent(since, at)}
    return out


async def paragraph() -> Dict[str, Any]:
    """THE PARAGRAPH, read as a paragraph. Its utterances are the reader's own cut of it, so what is recorded is
    every meaning it took of the whole text and how much of the text it left unread -- a cut that reads more
    stretches while saying less of what the text says is a cut that got worse, and the two numbers say which."""
    from core.semantics import derived_reader as dr
    from core.semantics.sentence_machine import surface_of
    at, since = time.time(), dict(_COST)
    with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
        out = dr.read_text(PARAGRAPH)
    readings = tuple(r for u in out for r in u.readings)
    unread = [surface_of(u.pieces)[:80] for u in out if not tuple(u.readings)]
    return {PARAGRAPH[:60]: {"utterances": len(out), "readings": len(readings), "built": built(readings),
                             "unread": len(unread), "left_unread": sorted(unread),
                             "words": len(PARAGRAPH.split()), **spent(since, at)}}


async def long_prose() -> Dict[str, Any]:
    """THE TWO LONG SENTENCES, read through the reading alone. No conversation is given them, because a telling is
    stored and this file stores nothing -- and because what these are here for is the chart, which the door would
    only add its own work on top of."""
    from core.semantics import derived_reader as dr
    out: Dict[str, Any] = {}
    for said in LONG:
        at, since = time.time(), dict(_COST)
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            utterances = dr.read_text(said)
            readings = tuple(r for u in utterances for r in u.readings)
            chosen = await dr.heard(readings) if readings else None
        out[said] = {"read": chosen.meaning.canonical() if chosen is not None else None,
                     "readings": len(readings), "built": built(readings),
                     "utterances": len(utterances), "words": len(said.split()), **spent(since, at)}
    return out


def compare(was: Dict[str, Any], now: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """Each case said against what was recorded of it: as recorded, better, worse, or CHANGED.

    CHANGED IS ITS OWN ANSWER AND NOT A WORSE ONE. A description either names a doing or names none, and a pair is
    either answered or not, so those two say which way they moved. A REPLY DOES NOT: it is a sentence, and whether
    one sentence is better than another is not something this can read. Counted as worse, the day's two real
    repairs to the reply were filed as regressions -- "Noted - All of the material rock is heavy.", one rock said
    of all rock, became "Noted - The rock is heavy." and was reported WORSE (lyric_db, 2026-11-13). So a changed
    reply is printed with both versions and counted apart, and the run still ends non-zero, because a changed reply
    is exactly the thing a person has to look at."""
    kept = better = worse = changed = 0

    def verdict(label: str, old: Any, new: Any, improved: Optional[bool]) -> None:
        nonlocal kept, better, worse, changed
        if old == new:
            kept += 1
            say(f"    as recorded  {label}")
            return
        if improved is True:
            better += 1
            say(f"    BETTER       {label}\n                   was {old!r}\n                   now {new!r}")
        elif improved is False:
            worse += 1
            say(f"    WORSE        {label}\n                   was {old!r}\n                   now {new!r}")
        else:
            changed += 1
            say(f"    CHANGED      {label}\n                   was {old!r}\n                   now {new!r}")

    say("\n  THE DESCRIPTIONS")
    for said, after in now["descriptions"].items():
        before = was["descriptions"].get(said)
        if before is None:
            say(f"    new          {said[:70]!r} -> {after['doing']!r}")
            continue
        old, new = before["doing"], after["doing"]
        verdict(f"{said[:66]!r} -> {new!r}", old, new,
                None if old and new else (bool(new) if old != new else None))

    say("\n  THE OPPOSITES")
    for said, after in now["opposites"].items():
        before = was["opposites"].get(said)
        if before is None:
            say(f"    new          {said!r} answered={after['answered']}")
            continue
        verdict(f"{said!r} answered={after['answered']}", before["answered"], after["answered"],
                after["answered"])

    say("\n  THE PROSE")
    for said, after in now["prose"].items():
        before = was["prose"].get(said)
        if before is None:
            say(f"    new          {said!r} -> {after['read']!r}")
            continue
        verdict(f"{said!r}", (before["read"], before.get("reply")),
                (after["read"], after.get("reply")), None)

    say("\n  THE LONG SENTENCES")
    for said, after in now.get("long", {}).items():
        before = (was.get("long") or {}).get(said)
        if before is None:
            say(f"    new          {said[:66]!r} -> {after['read']!r}")
            continue
        verdict(f"{said[:66]!r}", before["read"], after["read"], None)

    say("\n  THE PARAGRAPH")
    for said, after in now.get("paragraph", {}).items():
        before = (was.get("paragraph") or {}).get(said)
        if before is None:
            say(f"    new          {after['utterances']} utterance(s), {after['unread']} left unread")
            continue
        # MORE STRETCHES READ IS NOT BETTER AND FEWER IS NOT WORSE: what matters is how much of the text was left
        # unread, and which meanings it took (below). The cut itself is reported and counted apart.
        verdict(f"{after['utterances']} utterance(s), {after['unread']} left unread",
                (before["utterances"], before["unread"]), (after["utterances"], after["unread"]),
                None if after["unread"] == before["unread"] else after["unread"] < before["unread"])

    # A READING THAT STOPPED BEING BUILT IS A CAPABILITY LOST, and it is the one thing here that is never
    # CHANGED and never faster: the listener can only take what was built, so a meaning missing from this set
    # never reaches it, whatever the clock says. Reported case by case and by the meaning itself, because which
    # reading went is the whole of what a person needs to see.
    say("\n  WHAT WAS BUILT")
    for group in ("opposites", "prose", "long", "paragraph"):
        for said, after in now.get(group, {}).items():
            before = (was.get(group) or {}).get(said)
            if before is None or "built" not in before:
                continue
            gone = [m for m in before["built"] if m not in after.get("built", [])]
            fresh = [m for m in after.get("built", []) if m not in before["built"]]
            if gone:
                worse += 1
                say(f"    WORSE        {said[:60]!r} built {len(before['built'])} reading(s), now "
                    f"{len(after.get('built', []))}; NO LONGER BUILT:")
                # EVERY ONE OF THEM, never the first few: which readings went is the whole of the judgement
                # a human makes here, and a truncated list reads as a smaller loss than it is.
                for meaning in gone:
                    say(f"                   {meaning}")
            elif fresh:
                better += 1
                say(f"    BETTER       {said[:60]!r} builds {len(fresh)} more: {fresh[0][:90]}")
            else:
                kept += 1
                say(f"    as recorded  {said[:60]!r} {len(after.get('built', []))} reading(s)")

    # WHAT IT COST, BESIDE WHAT IT SAID. Reported for every case; WORSE only where it changed in kind
    # (`COST_IN_KIND`), on the chart's own signs as well as on the clock.
    say("\n  WHAT IT COST")
    for group in ("descriptions", "opposites", "prose", "long", "paragraph"):
        for said, after in now.get(group, {}).items():
            before = (was.get(group) or {}).get(said)
            if before is None or "signs" not in before:
                continue
            was_signs, now_signs = before.get("signs", 0), after.get("signs", 0)
            was_secs, now_secs = before.get("seconds", 0.0) or 0.0, after.get("seconds", 0.0) or 0.0
            dearer = (now_signs > max(was_signs, 1) * COST_IN_KIND
                      and now_secs > max(was_secs, 1.0) * COST_IN_KIND)
            # A CASE THAT BUILT NO SIGNS AND STILL BUILDS NONE IS AS RECORDED, NOT BETTER. Written
            # `now_signs * COST_IN_KIND < max(was_signs, 1)`, nothing against nothing came out 0 < 1, so every
            # case the grammar never charted reported BETTER: 5 of the 5 this said on 2026-11-18 were that, two
            # of them with the clock going the OTHER way ('The rock was heavy.' 2.0s -> 2.6s). A harness that
            # flatters is worse than none, since this file is the only thing standing between a cheaper chart and
            # a lost reading.
            cheaper = was_signs > 0 and now_signs * COST_IN_KIND < was_signs
            how = (f"{was_secs:.1f}s -> {now_secs:.1f}s, {was_signs:,} -> {now_signs:,} sign(s) in "
                   f"{after.get('charts', 0)} chart(s)")
            if dearer:
                worse += 1
                say(f"    WORSE        {said[:56]!r} {how}")
            elif cheaper:
                better += 1
                say(f"    BETTER       {said[:56]!r} {how}")
            else:
                say(f"                 {said[:56]!r} {how}")
    return kept, better, worse, changed


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true",
                        help="write what the system does now as the baseline, replacing it")
    parser.add_argument("--skip-tests", action="store_true", help="leave the two tests to pytest")
    parser.add_argument("--baseline", default=str(BASELINE))
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    t0 = time.time()
    baseline = Path(args.baseline)

    if not args.skip_tests:
        say("the two tests that hold the minimal pairs…")
        passed, how = run_tests()
        say(f"  {'passed' if passed else 'FAILED'}  {how}")
        if not passed:
            say("\n  the minimal pairs fail, so the live store has nothing to add: fix those first.")
            return 1

    say("\nstarting the way the system starts…")
    _, coordinator = await start()

    was: Dict[str, Any] = {}
    if not args.record:
        if not baseline.exists():
            say(f"\nthere is no baseline at {baseline}: run once with --record.")
            return 1
        was = json.loads(baseline.read_text())

    at = time.time()
    with counting():
        now = {"descriptions": await descriptions(coordinator, None if args.record
                                                  else sorted(was["descriptions"])),
               "opposites": await opposites(),
               "prose": await prose(),
               "long": await long_prose(),
               "paragraph": await paragraph()}
    say(f"\n  {len(now['descriptions'])} description(s), {len(now['opposites'])} pair(s), "
        f"{len(now['prose'])} prose sentence(s), {len(now['long'])} long sentence(s), "
        f"1 paragraph read in {time.time()-at:.0f}s")
    say(f"  {_COST['charts']:,} chart(s) built in all, holding {_COST['signs']:,} sign(s) "
        f"in {_COST['cells']:,} cell(s)")

    if args.record:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n")
        say(f"\n  recorded to {baseline}")
        for group in ("descriptions", "opposites", "prose", "long", "paragraph"):
            say(f"\n  {group.upper()}")
            for said, what in now[group].items():
                plain = {k: v for k, v in what.items() if k not in ("seconds", "built")}
                say(f"    {said[:66]!r:68s} {plain}")
                if what.get("built"):
                    say(f"      built {len(what['built'])}: {what['built'][0][:100]}")
        say(f"\n  ({time.time()-t0:.0f}s all told)")
        return 0

    kept, better, worse, changed = compare(was, now)
    say(f"\n  {kept} as recorded, {better} better, {worse} worse, {changed} changed"
        f"   ({time.time()-t0:.0f}s all told, against 4,742s for the whole sweep)")
    return 1 if worse or changed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
