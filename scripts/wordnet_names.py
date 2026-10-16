#!/usr/bin/env python3
"""The names WordNet's senses are taught under, kept beside the lessons, so a change to them is seen before it is taught.

A store is taught WordNet's senses under the names `WordNetSource._sense_names` gives them, and those names follow from
WordNet, the teacher's stated senses (`data/lessons/senses.json`) and how the English lessons use their words
(`_lesson_parts`). An edit to any of them can rename a sense, and a store already taught then holds it under the old
name: counting a degree's kind as a thing's gave "fast" to fasting, and teaching under the fixed names beside it would
have left both (2026-10-12). `data/lessons/wordnet_names.tsv.gz` holds the names the stores were taught under;
`tests/test_lesson_terms.py` fails when the names differ from it.

    ./venv_lyric/bin/python3 scripts/wordnet_names.py --diff [--was logs/renamed.json]
        each sense named otherwise than the stores were taught; with --was, the file `repair_renamed_senses.py` reads
    ./venv_lyric/bin/python3 scripts/wordnet_names.py --write
        record the names as they are now: only once every store has been repaired to them
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TAUGHT = ROOT / "data" / "lessons" / "wordnet_names.tsv.gz"


def current() -> dict:
    """`sense -> name`, as WordNet is taught now ("" for a sense not taught)."""
    from core.learning.teaching_sources import WordNetSource
    return {synset.name(): name for synset, name in WordNetSource()._sense_names().items()}


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
