#!/usr/bin/env python3
"""ENCODER-05 — argument role: does either encoder know who did what to whom?

"A pump moves liquid" and "A liquid moves pump" contain the same words in a
different structure and mean different things -- one of them nothing at all.
An encoder that scores them identically is a bag of words, and the substrate
would merge a claim with its own inverse.

This is the sharpest available test of whether an encoder represents STRUCTURE
or merely CONTENT, and the substrate has a reader that produces structure, so
the answer decides whether the vector should be doing this job at all.

  H1  Role-swapped pairs score below the merge threshold (0.75).
  H2  Role swap is scored as MORE different than a subject swap. Exchanging
      two arguments changes the claim completely; changing one noun leaves a
      well-formed claim about something else.
  H3  A distractor with the same words but no relation ("pump liquid moves")
      does not score as the original.
"""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder, invented_corpus,
                          real_corpus, minimal_pairs, sim)

LIVE_THRESHOLD = 0.75


def role_swap(fact):
    m = re.match(r"A (\w+) (\w+) (?:a |an |the )?(.+?)\.?$", fact)
    if not m or m.group(2) == "is":
        return None
    return f"A {m.group(3)} {m.group(2)} {m.group(1)}."


def scramble(fact):
    m = re.match(r"A (\w+) (\w+) (?:a |an |the )?(.+?)\.?$", fact)
    if not m or m.group(2) == "is":
        return None
    return f"{m.group(1)} {m.group(3)} {m.group(2)}"


def main():
    run = Run("ENCODER-05 — argument role: who did what to whom", [
        "H1 role-swapped pairs fall below the merge threshold",
        "H2 a role swap reads as MORE different than a subject swap",
        "H3 a word-scramble does not score as the original",
    ])
    ip, ifacts, _, isubs = invented_corpus(n_subjects=25)
    rp, rfacts, _, rsubs = real_corpus()
    props, facts, subs = ip + rp, ifacts + rfacts, isubs + rsubs

    swaps = [(f, role_swap(f)) for f in facts if role_swap(f)]
    scr = [(f, scramble(f)) for f in facts if scramble(f)]
    subj = minimal_pairs(facts, subs)

    mini, nat = MiniLM(), SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    rows, data = [], {}
    for name, enc in (("MiniLM", mini), ("native", nat), ("structural", st)):
        sw = [sim(enc, a, b) for a, b in swaps]
        sc = [sim(enc, a, b) for a, b in scr]
        sj = [sim(enc, a, b) for a, b in subj]
        m = lambda xs: sum(xs) / max(1, len(xs))
        over = sum(1 for x in sw if x >= LIVE_THRESHOLD)
        data[name] = {"role_swap_mean": m(sw), "scramble_mean": m(sc),
                      "subject_swap_mean": m(sj), "role_swaps_merge_eligible": over,
                      "n": len(sw)}
        rows.append(f"{name:8} role-swap {m(sw):.3f}  scramble {m(sc):.3f}  "
                    f"subject-swap {m(sj):.3f} | {over}/{len(sw)} inversions merge-eligible")
    run.table("encoder   A-verb-B vs B-verb-A   scrambled   subject swapped", rows)
    run.data = data

    for name in ("MiniLM", "native", "structural"):
        d = data[name]
        run.check(f"H1 {name}: inversions fall below the merge threshold",
                  d["role_swaps_merge_eligible"] == 0,
                  f"{d['role_swaps_merge_eligible']}/{d['n']} inversions score >= {LIVE_THRESHOLD}")
        run.check(f"H2 {name}: a role swap reads as more different than a subject swap",
                  d["role_swap_mean"] < d["subject_swap_mean"],
                  f"role {d['role_swap_mean']:.3f} vs subject {d['subject_swap_mean']:.3f}")
        run.check(f"H3 {name}: a scramble does not read as the original",
                  d["scramble_mean"] < LIVE_THRESHOLD,
                  f"scramble {d['scramble_mean']:.3f}")

    bag = all(data[n]["role_swap_mean"] >= LIVE_THRESHOLD for n in data)
    run.finish("BOTH encoders are bags of words at the argument level — structure "
               "must come from the reader, not the vector"
               if bag else "at least one encoder represents argument role")


if __name__ == "__main__":
    main()
