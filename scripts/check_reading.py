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

QUIET = io.StringIO()


def say(*a: Any) -> None:
    print(*a, flush=True)


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
    from core.semantics.grammar import RULES
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
    say(f"  rules {RULES!r}, {len(dr.live_view()):,} construction(s) held")
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
        at = time.time()
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            doing = await coordinator.doing_said(said)
        out[said] = {"doing": doing, "seconds": round(time.time() - at, 1)}
    return out


async def opposites() -> Dict[str, Any]:
    """Whether each pair is answered, which is what pricing senses on one scale was for."""
    from core.semantics import derived_reader as dr
    out: Dict[str, Any] = {}
    for one, other in PAIRS:
        said = f"Is {one} the opposite of {other}?"
        at = time.time()
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            utterances = dr.read_text(said)
            readings = tuple(utterances[0].readings) if utterances else ()
            chosen = await dr.heard(readings) if readings else None
        answered = chosen is not None and any(
            f.relation == "antonym_of" and {f.subject, f.obj} == {one, other} for f in chosen.meaning.facts)
        out[said] = {"answered": answered,
                     "read": chosen.meaning.canonical() if chosen is not None else None,
                     "seconds": round(time.time() - at, 1)}
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
    talk = get_conversation("check_reading", remembers=False)
    out: Dict[str, Any] = {}
    for said in PROSE:
        at = time.time()
        with contextlib.redirect_stdout(QUIET), contextlib.redirect_stderr(QUIET):
            utterances = dr.read_text(said)
            readings = tuple(utterances[0].readings) if utterances else ()
            chosen = await dr.heard(readings) if readings else None
            understood = await talk.understand(said, look_up=False)
        out[said] = {"read": chosen.meaning.canonical() if chosen is not None else None,
                     "readings": len(readings),
                     "reply": (getattr(understood, "reply", "") or "")[:120],
                     "seconds": round(time.time() - at, 1)}
    return out


def compare(was: Dict[str, Any], now: Dict[str, Any]) -> Tuple[int, int, int]:
    """Each case said against what was recorded of it: as recorded, better, or worse."""
    kept = better = worse = 0

    def verdict(label: str, old: Any, new: Any, improved: Optional[bool]) -> None:
        nonlocal kept, better, worse
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
            worse += 1
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
    return kept, better, worse


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
    now = {"descriptions": await descriptions(coordinator, None if args.record
                                              else sorted(was["descriptions"])),
           "opposites": await opposites(),
           "prose": await prose()}
    say(f"\n  {len(now['descriptions'])} description(s), {len(now['opposites'])} pair(s), "
        f"{len(now['prose'])} prose sentence(s) read in {time.time()-at:.0f}s")

    if args.record:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps(now, indent=2, sort_keys=True) + "\n")
        say(f"\n  recorded to {baseline}")
        for group in ("descriptions", "opposites", "prose"):
            say(f"\n  {group.upper()}")
            for said, what in now[group].items():
                plain = {k: v for k, v in what.items() if k != "seconds"}
                say(f"    {said[:66]!r:68s} {plain}")
        say(f"\n  ({time.time()-t0:.0f}s all told)")
        return 0

    kept, better, worse = compare(was, now)
    say(f"\n  {kept} as recorded, {better} better, {worse} worse"
        f"   ({time.time()-t0:.0f}s all told, against 4,742s for the whole sweep)")
    return 1 if worse else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
