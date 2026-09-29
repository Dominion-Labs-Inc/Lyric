#!/usr/bin/env python3
"""Scores the reader against the claims each construction SHOULD produce, on a
LIVE substrate with word classes warm.

THE BAR IS CORRECTNESS, NOT PRESENCE. An earlier version of the construction
experiment scored `n < len(sentences)` -- it PASSED when the reader read fewer
than all three, so reading nothing scored the same as reading two, and a
hand-written blocklist that refused thirteen constructions outright scored
100%. Counting readings instead of checking them fails the same way from the
other side: `Scientists believe the universe is expanding` produced a claim
about a thing called "scientists believe the universe", which is a reading and
is worthless.

So every sentence here states the claims it makes. A sentence counts only when
all of them are produced; anything extra is reported as OVER, because a reading
that invents a claim has not succeeded either.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.nlu._nlu_lib import live_substrate          # noqa: E402
from experiments.nlu.construction_claims import EXPECTED     # noqa: E402


def _norm(value):
    if value is None:
        return None
    text = re.sub(r"(?i)^(a|an|the)\s+", "", str(value).strip().lower())
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"s$", "", text)


def _claim(parts):
    return (_norm(parts.get("subject")), _norm(parts.get("relation")),
            _norm(parts.get("obj")), bool(parts.get("positive", True)))


async def main() -> int:
    async with live_substrate() as coordinator:
        from core.semantics.sentence_reader import SentenceReader
        reader = SentenceReader()
        total = correct = 0
        full = []
        gaps = []
        for name, cases in EXPECTED:
            n = 0
            detail = []
            for sentence, expected in cases:
                got = [_claim(p) for p in reader.read_all(sentence)]
                want = [(_norm(a), _norm(r), _norm(o), p) for a, r, o, p in expected]
                missing = [w for w in want if w not in got]
                over = [g for g in got if g not in want]
                if not missing:
                    n += 1
                else:
                    detail.append((sentence, missing, over))
            total += len(cases)
            correct += n
            (full if n == len(cases) else gaps).append(f"{name} {n}/{len(cases)}")
            print(f"{'OK ' if n == len(cases) else '   '}{name:24s} {n}/{len(cases)}")
            for sentence, missing, over in detail:
                print(f"     {sentence}")
                for m in missing:
                    print(f"        MISS {m}")
                for o in over:
                    print(f"        OVER {o}")
        print(f"\nCORRECT {correct}/{total} sentences across "
              f"{len(EXPECTED)} constructions")
        print(f"FULL ({len(full)}): {', '.join(full)}")
        print(f"GAPS ({len(gaps)}): {', '.join(gaps)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
