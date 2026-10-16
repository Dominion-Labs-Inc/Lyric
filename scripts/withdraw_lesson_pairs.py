#!/usr/bin/env python3
"""Take back what english_01-40 taught through pairs the lessons no longer teach.

`learn_patterns` keys every observation by the lesson and the pair, `sha256(sentence U+001E meaning)[:16]`. The
lessons were rewritten after main learned them (docs/TEACHING.md §12d: "the X" is a known thing), so main still
holds constructions learned from the old pairs, reading "The valve is closed." as valves being closed. They were
rewritten again so each term is the concept memory holds for what the word means there (2026-10-11: "raptor" as
`bird of prey`, the opening of a door as `to open`), and the old pairs taught words naming nothing. This finds
every lesson observation whose pair the lessons no longer hold, and hands them to the learning authority
(`UnifiedLearningSystem.withdraw_pairs`): each word is withdrawn, and what rested on nothing else is let go. Teach
english_01-40 afterwards, so the rewritten pairs are learned.

Run with no substrate running on the store. Without --apply it changes nothing and reports what it would do.
Refuses lyric_db unless --main is given.

    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/withdraw_lesson_pairs.py
    POSTGRES_DATABASE=lyric_dev ./venv_lyric/bin/python3 scripts/withdraw_lesson_pairs.py --apply
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _k, _v in {"POSTGRES_PORT": "5433", "POSTGRES_USER": "stefan", "LYRIC_NO_WATCHDOG": "1",
               "LYRIC_SHADOW_MODE": "1"}.items():
    os.environ.setdefault(_k, _v)

#: The lessons whose pairs are checked, and how their observations are keyed: "english-NN:<pair>", in either case.
LESSON = re.compile(r"^english-(0[1-9]|[12][0-9]|3[0-9]|40):([0-9a-f]{16})$", re.IGNORECASE)


def taught_pairs() -> set:
    """Every pair english_01-40 teach now, keyed as `learn_patterns` keys it."""
    from core.semantics import derived_reader as dr
    keys = set()
    for n in range(1, 41):
        lesson = json.loads((ROOT / "data" / "lessons" / f"english_{n:02d}.json").read_text())
        for record in lesson["records"]:
            meaning = dr.Meaning.from_dict(record["meaning"])
            for sentence, part, *_ in dr.quoted_pairs(record["sentence"], meaning):
                keys.add(hashlib.sha256(f"{sentence}\x1e{part.canonical()}".encode("utf-8")).hexdigest()[:16])
    return keys


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="withdraw; without it, only report")
    parser.add_argument("--main", action="store_true", help="allow lyric_db")
    args = parser.parse_args()
    database = os.environ.get("POSTGRES_DATABASE", "")
    if database in ("", "lyric_db") and not args.main:
        print("refused: name a copy in POSTGRES_DATABASE, or pass --main for lyric_db")
        return 2
    from core.agents.memory_agent import get_memory_agent
    from core.learning.unified_learning_system import get_learning_authority
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr

    current = taught_pairs()
    print(f"{database}: english_01-40 teach {len(current):,} pairs now", flush=True)
    agent = await get_memory_agent()
    await agent.initialize()             # the database first: the beliefs are read from it
    us = get_uncertainty_system()
    await us.load_from_db()
    await agent.warm_word_classes()
    withdrawn = set()
    for belief in us.held_in_domain(dr.ENGLISH_DOMAIN):
        for entry in list(belief.evidence_for) + list(belief.evidence_against):
            observation = str(entry.get("observation") or "") if isinstance(entry, dict) else ""
            match = LESSON.match(observation)
            if match and match.group(2) not in current:
                withdrawn.add(observation)
    print(f"lesson observations whose pair is no longer taught: {len(withdrawn):,}", flush=True)
    counts = await get_learning_authority().withdraw_pairs(
        withdrawn, cause="lessons rewritten: english_01-40 pairs no longer taught", apply=args.apply)
    print(("withdrew" if args.apply else "would withdraw") + f": {counts}", flush=True)
    await us.drain_writes()
    await agent.stop_memory_loops()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
