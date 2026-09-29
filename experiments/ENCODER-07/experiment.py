#!/usr/bin/env python3
"""ENCODER-07 — robustness: does the same claim, typed differently, still match?

A person teaching the substrate will not type identically twice. If a trivial
perturbation moves a claim below the recall floor, the substrate forgets what it
was told over a capital letter -- and nothing reports it.

The perturbations are the ones that actually occur, not adversarial noise:
casing, trailing punctuation, a doubled space, a single-character typo, a
filler word, and British/American spelling.

  H1  Every perturbation keeps the claim above the 0.5 recall floor.
  H2  Perturbation moves similarity by less than 0.15 on average -- stability,
      not merely staying above a line.
  H3  A typo in the SUBJECT is the worst case for the native encoder, because
      a misspelled taught term becomes an untaught one. Registered in advance
      as the expected weakness.
"""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder, invented_corpus,
                          real_corpus, sim)

RECALL_FLOOR = 0.5


def typo_subject(f):
    m = re.match(r"A (\w+) ", f)
    if not m or len(m.group(1)) < 4:
        return f
    s = m.group(1)
    return f.replace(s, s[:2] + s[3:], 1)          # drop one character


def typo_object(f):
    parts = f.rstrip(".").split()
    if len(parts) < 4 or len(parts[-1]) < 4:
        return f
    parts[-1] = parts[-1][:2] + parts[-1][3:]
    return " ".join(parts) + "."


PERTURBATIONS = [
    ("upper case", lambda f: f.upper()),
    ("no full stop", lambda f: f.rstrip(".")),
    ("doubled spaces", lambda f: f.replace(" ", "  ")),
    ("filler word", lambda f: f.replace("A ", "A certain ", 1)),
    ("typo in object", typo_object),
    ("typo in subject", typo_subject),
]


def main():
    run = Run("ENCODER-07 — robustness: the same claim, typed differently", [
        "H1 every perturbation stays above the 0.5 recall floor",
        "H2 mean similarity shift under perturbation is under 0.15",
        "H3 a typo in the SUBJECT is the native encoder's worst case (registered)",
    ])
    ip, ifacts, _, _ = invented_corpus(n_subjects=25)
    rp, rfacts, _, _ = real_corpus()
    props, facts = ip + rp, ifacts + rfacts

    mini, nat = MiniLM(), SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    data = {}
    rows = []
    for name, enc in (("MiniLM", mini), ("native", nat), ("structural", st)):
        data[name] = {}
        for label, fn in PERTURBATIONS:
            scores = [sim(enc, f, fn(f)) for f in facts]
            mean = sum(scores) / max(1, len(scores))
            below = sum(1 for s in scores if s < RECALL_FLOOR)
            data[name][label] = {"mean": mean, "below_floor": below, "n": len(scores)}
            rows.append(f"{name:8} {label:18} mean {mean:.3f}  below floor {below}/{len(scores)}")
    run.table("encoder   perturbation        similarity to the original", rows)
    run.data = data

    for name in ("MiniLM", "native", "structural"):
        worst = min(data[name].items(), key=lambda kv: kv[1]["mean"])
        total_below = sum(v["below_floor"] for v in data[name].values())
        mean_shift = sum(1 - v["mean"] for v in data[name].values()) / len(PERTURBATIONS)
        run.check(f"H1 {name}: no perturbation drops a claim below the recall floor",
                  total_below == 0, f"{total_below} claim(s) fell below {RECALL_FLOOR}; "
                                    f"worst: {worst[0]} at {worst[1]['mean']:.3f}")
        run.check(f"H2 {name}: mean shift under perturbation is under 0.15",
                  mean_shift < 0.15, f"mean shift {mean_shift:.3f}")

    nat_worst = min(data["native"].items(), key=lambda kv: kv[1]["mean"])[0]
    run.check("H3 a subject typo is the native encoder's worst case (as registered)",
              nat_worst == "typo in subject", f"worst was: {nat_worst}")
    run.observe("why it matters",
                "a misspelled taught term becomes an untaught one, and an untaught "
                "term carries no representation at all")
    run.finish(f"native worst case: {nat_worst} "
               f"({data['native'][nat_worst]['mean']:.3f})")


if __name__ == "__main__":
    main()
