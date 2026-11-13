#!/usr/bin/env python3
"""The names WordNet's senses are taught under, kept beside the lessons, so a change to them is seen before it is taught.

A store is taught WordNet's senses under the names `WordNetSource._sense_names` gives them, and those names follow from
WordNet, the teacher's stated senses (`data/lessons/senses.json`) and how the English lessons use their words
(`_lesson_parts`). An edit to any of them can rename a sense, and a store already taught then holds it under the old
name: counting a degree's kind as a thing's gave "fast" to fasting, and teaching under the fixed names beside it would
have left both (2026-10-12). `data/lessons/wordnet_names.tsv.gz` holds the names the stores were taught under;
`tests/test_lesson_terms.py` fails when the names differ from it.

    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/wordnet_names.py --diff [--was logs/renamed.json]
        each sense named otherwise than the stores were taught; with --was, the file `repair_renamed_senses.py` reads
    POSTGRES_DATABASE=lyric_db ./venv_lyric/bin/python3 scripts/wordnet_names.py --write
        record the names as they are now: only once every store has been repaired to them

A SENSE IS NAMED AT THE DOOR, AND THE DOOR NAMES FROM WHAT LYRIC HOLDS (2026-11-13), so this reads a store's words
before it names anything -- about four minutes, and the store is named in POSTGRES_DATABASE. Nothing is written to
it: the agent is in shadow mode, so no background loop and no write queue runs.
"""
import argparse
import asyncio
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TAUGHT = ROOT / "data" / "lessons" / "wordnet_names.tsv.gz"


def current() -> dict:
    """`sense -> name`, as WordNet is taught now ("" for a sense not taught).

    NEEDS LYRIC'S WORDS. A sense's name is written at the door, and the door names a term from what Lyric holds
    (`lexical_normalization._held_singular`, 2026-11-13): with no words held it has only the spelling rules, which
    write "acrobatics" `acrobatic` and "Mars" `mar`. Names so written would be recorded as the names to teach
    under, and a store repaired to them. So this refuses rather than answer from spelling; `warmed()` below is
    what the command line calls first."""
    from core.learning.teaching_sources import WordNetSource
    from core.semantics.derived_reader import live_view
    if not len(live_view()):
        raise RuntimeError(
            "the senses are named at the door, which names from what Lyric holds, and this process holds none of "
            "its words: warm them first (MemoryAgent.warm_word_classes), as scripts/wordnet_names.py does")
    return {synset.name(): name for synset, name in WordNetSource()._sense_names().items()}


async def warmed() -> None:
    """Read Lyric's words into this process, so the door names a sense as the system names it."""
    import os
    for key, value in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
                       "LYRIC_SHADOW_MODE": "1"}.items():
        os.environ.setdefault(key, value)
    from core.agents.memory_agent import get_memory_agent
    agent = await get_memory_agent()
    await agent.initialize()
    held = await agent.warm_word_classes()
    print(f"{os.environ.get('POSTGRES_DATABASE', '(default)')}: {held:,} word(s) warmed", file=sys.stderr)


def taught() -> dict:
    """`sense -> name`, as the stores were taught."""
    with gzip.open(TAUGHT, "rt", encoding="utf-8") as handle:
        return dict(line.rstrip("\n").split("\t", 1) for line in handle if line.strip())


def differences(now: dict, was: dict) -> dict:
    """`sense -> (name taught under, name now)` for every sense named otherwise."""
    return {s: (was.get(s, ""), now.get(s, "")) for s in sorted(set(now) | set(was)) if was.get(s, "") != now.get(s, "")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--was", default=None, help="with --diff: write the names taught under, for the repair")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(warmed())
    now = current()
    if args.write:
        with gzip.open(TAUGHT, "wt", encoding="utf-8") as handle:
            for sense in sorted(now):
                handle.write(f"{sense}\t{now[sense]}\n")
        print(f"{len(now)} names recorded in {TAUGHT.relative_to(ROOT)}")
        return 0
    diff = differences(now, taught())
    for sense, (was, is_) in diff.items():
        print(f"{sense:30} taught as {was!r:34} named now {is_!r}")
    print(f"{len(diff)} senses named otherwise than the stores were taught")
    if args.was and diff:
        Path(args.was).write_text(json.dumps({"taught_under": {s: w for s, (w, _) in diff.items()}}, indent=1) + "\n")
        print(f"written {args.was}: scripts/repair_renamed_senses.py --was {args.was}")
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main())
