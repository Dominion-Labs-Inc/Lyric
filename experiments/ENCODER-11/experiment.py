#!/usr/bin/env python3
"""ENCODER-11 — NOISY ENVIRONMENT: degraded surface at increasing rates.

Real input is not clean. People mistype, OCR substitutes characters, transcripts
drop punctuation, systems mangle whitespace and case. An encoder that only works
on clean text is a laboratory result.

This does not test one perturbation -- ENCODER-07 did that. It tests a DOSE
CURVE: as the corruption rate rises from 0% to 50% of characters, where does
each encoder break, and does it break gracefully or fall off a cliff?

  H1  At 10% character corruption every encoder keeps claims above the 0.5
      recall floor. This is ordinary typing.
  H2  Degradation is graceful -- no encoder loses more than 0.25 similarity
      between consecutive noise levels. A cliff means an unpredictable failure.
  H3  Discrimination survives noise: a noisy claim still does not match a
      DIFFERENT claim. Losing recall is recoverable; gaining a false match
      destroys a memory.
  H4  The structural encoder degrades more slowly than MiniLM, because a
      corrupted word costs it one dimension among many rather than shifting a
      whole dense vector.
"""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder,
                          invented_corpus, real_corpus, sim, SEED)

RECALL_FLOOR = 0.5
RATES = [0.0, 0.05, 0.10, 0.20, 0.35, 0.50]
KEYBOARD = {"a": "s", "e": "r", "i": "o", "o": "p", "n": "m", "t": "y",
            "r": "t", "s": "d", "l": "k", "c": "v", "m": "n", "u": "i"}


def corrupt(text, rate, rng):
    out = []
    for ch in text:
        if ch.isalpha() and rng.random() < rate:
            roll = rng.random()
            if roll < 0.4 and ch.lower() in KEYBOARD:
                out.append(KEYBOARD[ch.lower()])       # adjacent-key slip
            elif roll < 0.7:
                continue                                # dropped character
            else:
                out.append(ch.upper() if ch.islower() else ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def main():
    run = Run("ENCODER-11 — noisy environment: a dose curve of surface corruption", [
        "H1 ordinary typing noise (10%) keeps claims above the recall floor",
        "H2 degradation is graceful, never a cliff",
        "H3 discrimination survives noise (a noisy claim matches no OTHER claim)",
        "H4 the structural encoder degrades more slowly than MiniLM",
    ])
    ip, ifacts, _, isubs = invented_corpus(n_subjects=30)
    rp, rfacts, _, rsubs = real_corpus()
    props, facts = ip + rp, ifacts + rfacts

    mini = MiniLM()
    nat = SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    encoders = [("MiniLM", mini), ("native", nat), ("structural", st)]

    data = {name: {} for name, _ in encoders}
    rows = []
    for name, enc in encoders:
        for rate in RATES:
            rng = random.Random(SEED + int(rate * 1000))
            self_scores, cross_scores = [], []
            for i, f in enumerate(facts):
                noisy = corrupt(f, rate, rng)
                self_scores.append(sim(enc, f, noisy))
                other = facts[(i + 13) % len(facts)]
                cross_scores.append(sim(enc, other, noisy))
            m = lambda xs: sum(xs) / max(1, len(xs))
            below = sum(1 for s in self_scores if s < RECALL_FLOOR)
            confused = sum(1 for s, c in zip(self_scores, cross_scores) if c >= s)
            data[name][rate] = {"self": m(self_scores), "cross": m(cross_scores),
                                "below_floor": below, "confused": confused,
                                "n": len(facts)}
            rows.append(f"{name:11} {rate:5.0%}  self {m(self_scores):.3f}  "
                        f"other {m(cross_scores):.3f}  below floor {below:>3}/{len(facts)}  "
                        f"confused {confused:>3}")
    run.table("encoder     noise   matches itself   matches ANOTHER claim", rows)
    run.data = data

    for name, _ in encoders:
        d = data[name]
        run.check(f"H1 {name}: survives 10% character corruption",
                  d[0.10]["below_floor"] == 0,
                  f"{d[0.10]['below_floor']}/{d[0.10]['n']} below floor at 10% noise")
        worst_drop = max(d[RATES[i]]["self"] - d[RATES[i + 1]]["self"]
                         for i in range(len(RATES) - 1))
        run.check(f"H2 {name}: degrades gracefully, no cliff",
                  worst_drop <= 0.25, f"largest single-step drop {worst_drop:.3f}")
        run.check(f"H3 {name}: noise never makes a claim match a different one",
                  all(d[r]["confused"] == 0 for r in RATES),
                  f"confusions by rate: {[d[r]['confused'] for r in RATES]}")

    st_loss = data["structural"][0.0]["self"] - data["structural"][0.35]["self"]
    mini_loss = data["MiniLM"][0.0]["self"] - data["MiniLM"][0.35]["self"]
    run.check("H4 structural degrades more slowly than MiniLM (0% -> 35%)",
              st_loss < mini_loss,
              f"structural lost {st_loss:.3f}, MiniLM lost {mini_loss:.3f}")
    run.observe("cost asymmetry",
                "losing recall under noise is recoverable; a FALSE match under "
                "noise merges and destroys a memory")
    run.finish(f"at 35% corruption: structural {data['structural'][0.35]['self']:.3f}, "
               f"MiniLM {data['MiniLM'][0.35]['self']:.3f}, "
               f"native {data['native'][0.35]['self']:.3f}")


if __name__ == "__main__":
    main()
