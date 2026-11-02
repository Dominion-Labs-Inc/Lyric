"""WHY A SENTENCE READ THE WAY IT DID, every decision of the reading and what decided it.

A reading already records each link it spelled out and where it came from (`Reading.decided`: what decided, of what,
by what -- "own" the word's own uses, "kind" what memory holds it a kind of, "frame" its verb's frames, "rule" the
grammar's own link -- and the fact it made). Nothing printed it, so a reading that came out wrong was traced by hand,
one probe at a time, which is how a night went on the `with` of "Roy painted the medal with paint." (2026-11-02).
This prints it, and beside it the two decisions that are made from a word recorded whole and nowhere else to be seen:

- EACH HAPPENING'S PLACES, as its verb's frames say them read as one analysis (`Lexicon.places_framed`): the frames
  held of the sense the sentence means and of the word, how well each fits the places said, and the link each place
  was given. A frame is a whole analysis of a happening, so the frames at the best fit are shown together.
- EACH THING'S SENSE, as what the word names most often and what the doing was seen done to say it
  (`Lexicon.thing_sense_of`): every sense with how often it is used, the most specific kind it shares with anything
  the doing was seen with, how many of those uses are of that kind, and what each contributes. ONE TAGGED USE IS ONE
  USE: this is where the single coating of a slope in SemCor read the wall of "Roy coated the wall." a geological
  formation.

From the Lyric folder, on any store (it reads, it writes nothing):

    PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 \\
        experiments/TRAIN-FORMAT-02/diagnostics/how_it_read.py "Roy painted the medal with paint."
"""
import asyncio
import contextlib
import io
import math
import os
import sys

sys.path.insert(0, os.getcwd())

SENTENCES = ("Roy painted the medal with paint.", "Roy painted the wall.", "Did Roy coat the wall?")


def say(*a):
    os.write(1, (" ".join(str(x) for x in a) + "\n").encode())


def places_said(reading, verb: str):
    """The places a verb was said with in this reading, as its role decisions name them."""
    return [of.split(":", 1)[1] for what, of, _how, _fact in reading.decided
            if what == "role" and of.split(":", 1)[0] == verb]


def frames_of(lexicon, reading, verb: str, sense: str) -> None:
    """The frames held of a verb, how each fits the places said, and the one analysis they gave."""
    held = lexicon.frames_said.get(verb) or {}
    slots = places_said(reading, verb)
    if not held:
        say(f"      no frames held of {verb!r}: every place falls to the grammar's own link")
        return
    for key in ([sense] if sense in held else []) + [""]:
        frames = held.get(key) or {}
        if not frames:
            continue
        fits, best = lexicon._frame_fit(frames, slots)
        say(f"      {len(frames)} frame(s) of {key or 'the word'!r}, over the places said {slots}:")
        for frame, n in sorted(frames.items(), key=lambda kv: (-(fits[kv[0]] == best), -kv[1])):
            say(f"          {'BEST FIT' if fits[frame] == best else '        '} x{n} fit {fits[frame]}  "
                f"{dict(frame)}")
    say(f"      the one analysis: {lexicon.places_framed(verb, sense, slots)}")


def sense_of_thing(lexicon, name: str, doing: str, meant: str, slot: str) -> None:
    """Every sense of a thing, how often it is used, and what the place of the doing it fills says of it."""
    used = lexicon.thing_used.get(name) or {}
    if len(used) < 2:
        say(f"      {name!r} names one thing; no sense to choose")
        return
    covers = {c: lexicon.thing_covers.get(name, {}).get(c, {}) for c in used}
    everything = max((n for held in covers.values() for n in held.values()), default=0)
    total = sum(used.values())
    seen = {f: n for (sl, f), n in (lexicon.sense_seen.get(doing, {}).get(meant) or {}).items() if sl == slot}
    of_kind = {f: {f} | set(lexicon.words.kinds(f, "NOUN")) for f in seen}
    was = {level for kinds in of_kind.values() for level in kinds}
    say(f"      {name!r} fills the {slot} of {meant!r}, which was seen there with {seen or 'nothing'}")
    rows = []
    for c in used:
        shared = min((covers[c][level] for level in was if level in covers[c]), default=everything)
        at = next((level for level in was if level in covers[c] and covers[c][level] == shared), None)
        uses = sum(n for f, n in seen.items() if at in of_kind[f])
        every = sum(seen.values())
        prior = math.log(used[c] / total)
        bonus = math.log(everything / shared) * (uses + 0.5) / (every + 0.5 * len(used)) \
            if everything and shared and shared < everything else 0.0
        rows.append((prior + bonus, c, used[c], at, shared, uses, prior, bonus))
    for score, c, n, at, shared, uses, prior, bonus in sorted(rows, reverse=True):
        say(f"          {c:28} used {n:4}  used-often {prior:6.2f}  shared kind {str(at):24} "
            f"covers {shared:6}  of {uses} use(s)  says {bonus:5.2f}  -> {score:6.2f}")


async def main(sentences) -> int:
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
        view = agent.grammar_view()
    lexicon = view.grammar.lexicon
    say(f"store {os.environ.get('POSTGRES_DATABASE', '')}; {len(view._words)} word(s) in English's grammar")
    for text in sentences:
        say(f"\n=== {text!r}")
        reading = view.read(text)
        if reading.meaning is None:
            say(f"  NOT READ: {reading.why}")
            continue
        say(f"  read: {reading.meaning.canonical()}")
        if reading.unheld:
            say(f"  words memory does not hold: {', '.join(reading.unheld)}")
        say("  every decision, and what decided it:")
        for what, of, how, fact in reading.decided:
            said = f"{fact.relation}({fact.subject}, {fact.obj})" if fact is not None else "-"
            say(f"      {what:8} {of:34} by {how:10} {said}")
        verbs = {of.split(":", 1)[0] for what, of, _h, _f in reading.decided if what == "role"}
        meant = {f.obj: f.subject for f in reading.meaning.facts if f.relation == "instance_of"}
        for verb in sorted(verbs):
            sense = next((s for s in meant if s == verb or lexicon.sense_used.get(verb, {}).get(s)), verb)
            say(f"  the places of {verb!r}, read as {sense!r}:")
            frames_of(lexicon, reading, verb, sense)
        for what, of, how, _fact in reading.decided:
            if what != "sense" or how not in ("seen", "around"):
                continue
            doing = next(iter(sorted(verbs)), "")
            sense = next((s for s in meant if lexicon.sense_used.get(doing, {}).get(s)), doing)
            say(f"  the sense of {of!r}:")
            sense_of_thing(lexicon, of, doing, sense, "object")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or SENTENCES)))
