"""Splits UNDERSTANDS-PROSE-02's 50 texts into a half fixed against and a half kept unseen, by rule, written to
split.json.

Each kind's five texts are drawn by a fixed seed; the kinds, in the order texts.json holds them, give three and two of
their texts to the half fixed against by turns (three first), so each half holds 25 texts and every kind has two or
three in each. A text whose answers were already traced to a cause before the split (44: "Journal."; 50: the
description of the office answered "Yes.") is fixed against by rule, before the draw, and counts among its kind's.
Every text's run had been seen as printed before the split; the half kept unseen is unseen in that none of its
answers was traced, and none is looked into until the fixes are done and it is run once.
"""
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
SEED = 20261022
TRACED = (44, 50)

texts = json.loads((HERE / "texts.json").read_text())
kinds = list(dict.fromkeys(t["kind"] for t in texts))
draw = random.Random(SEED)
fit, held = [], []
for turn, kind in enumerate(kinds):
    numbers = [n for n, t in enumerate(texts, 1) if t["kind"] == kind]
    forced = [n for n in numbers if n in TRACED]
    rest = [n for n in numbers if n not in TRACED]
    draw.shuffle(rest)
    taken = forced + rest[:(3 if turn % 2 == 0 else 2) - len(forced)]
    fit += taken
    held += [n for n in numbers if n not in taken]
split = {"seed": SEED, "traced": list(TRACED), "fit": sorted(fit), "held": sorted(held)}
assert len(split["fit"]) == len(split["held"]) == len(texts) // 2
(HERE / "split.json").write_text(json.dumps(split, indent=1) + "\n")
for half in ("fit", "held"):
    chosen = [texts[n - 1] for n in split[half]]
    print(f"{half}: {len(chosen)} texts, {sum(len(t['text']) for t in chosen)} sentences, "
          f"{sum(len(t['questions']) for t in chosen)} questions: {split[half]}")
