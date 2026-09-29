#!/usr/bin/env python3
"""ENCODER-03 — merge safety: which encoder destroys fewer memories?

THE OPERATIONAL TASK, NOT A PROXY. Similarity in this substrate is not an
academic score: at or above a threshold, `store_memory` MERGES the incoming
memory into an existing one and the new content is gone. On 2026-09-22 that
destroyed "A zorbic filters brine." by absorbing it into "A marnic filters
brine." So the question is not which encoder scores better, it is which one
DELETES FEWER THINGS IT SHOULD HAVE KEPT.

Two error types, with very different costs:

  FALSE MERGE   two DIFFERENT claims scored above threshold. A memory is
                destroyed. Unrecoverable.
  MISSED DEDUP  two statements of the SAME claim scored below threshold. A
                duplicate row. Harmless.

  H1  At the live threshold (0.75), the native encoder makes fewer false merges.
  H2  There exists a threshold at which the native encoder makes ZERO false
      merges while still catching most duplicates.
  H3  MiniLM has no such threshold -- its false-merge and dedup curves overlap.

  Reported as a sweep, because a single threshold hides whether an encoder is
  separable at all.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder, invented_corpus,
                          real_corpus, minimal_pairs, paraphrases, sim)

LIVE_THRESHOLD = 0.75
SWEEP = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99]


def rates(enc, must_differ, must_match, t):
    fm = sum(1 for a, b in must_differ if sim(enc, a, b) >= t)
    caught = sum(1 for a, b in must_match if sim(enc, a, b) >= t)
    return (fm / max(1, len(must_differ)), caught / max(1, len(must_match)))


def main():
    run = Run("ENCODER-03 — merge safety: which encoder destroys fewer memories?", [
        "H1 native makes fewer false merges at the live threshold (0.75)",
        "H2 native has a threshold with ZERO false merges and useful dedup",
        "H3 MiniLM has no such threshold",
    ])
    ip, ifacts, _, isubs = invented_corpus(n_subjects=30)
    rp, rfacts, _, rsubs = real_corpus()
    props = ip + rp
    facts = ifacts + rfacts
    subs = isubs + rsubs

    must_differ = minimal_pairs(facts, subs)     # distinct claims — merging destroys
    must_match = paraphrases(facts)              # same claim — merging is correct

    mini, nat = MiniLM(), SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    run.data["n_must_differ"] = len(must_differ)
    run.data["n_must_match"] = len(must_match)
    print(f"\n  distinct claims that must NOT merge : {len(must_differ)}")
    print(f"  same claims that SHOULD merge       : {len(must_match)}")

    table, data = [], {}
    for name, enc in (("MiniLM", mini), ("native", nat), ("structural", st)):
        data[name] = {}
        for t in SWEEP:
            fm, dd = rates(enc, must_differ, must_match, t)
            data[name][t] = {"false_merge_rate": fm, "dedup_rate": dd}
            table.append(f"{name:8} t={t:.2f}  false-merge {fm:6.1%}  dedup caught {dd:6.1%}")
    run.table("encoder  threshold   destroyed distinct   caught duplicates", table)
    run.data["sweep"] = data

    fm_m = data["MiniLM"][LIVE_THRESHOLD]["false_merge_rate"]
    fm_n = data["native"][LIVE_THRESHOLD]["false_merge_rate"]
    fm_s = data["structural"][LIVE_THRESHOLD]["false_merge_rate"]
    run.check("H1 native destroys fewer distinct memories at the live threshold",
              fm_n < fm_m, f"native {fm_n:.1%} vs MiniLM {fm_m:.1%} false merges at 0.75")
    run.check("H1b STRUCTURAL destroys fewer distinct memories at the live threshold",
              fm_s < fm_m, f"structural {fm_s:.1%} vs MiniLM {fm_m:.1%} false merges at 0.75")
    run.check("H1c STRUCTURAL destroys nothing at the live threshold",
              fm_s == 0.0, f"structural {fm_s:.1%} false merges at 0.75")

    def safe_point(name):
        for t in SWEEP:
            d = data[name][t]
            if d["false_merge_rate"] == 0.0 and d["dedup_rate"] >= 0.5:
                return t, d
        return None, None

    tn, dn = safe_point("native")
    tm, dm = safe_point("MiniLM")
    ts, ds = safe_point("structural")
    run.check("H2b STRUCTURAL has a zero-destruction threshold that still dedups",
              ts is not None,
              f"t={ts} dedup {ds['dedup_rate']:.1%}" if ts else "no such threshold")
    run.check("H2 native has a zero-destruction threshold that still dedups",
              tn is not None,
              f"t={tn} dedup {dn['dedup_rate']:.1%}" if tn else "no such threshold")
    run.check("H3 MiniLM has no zero-destruction threshold that still dedups",
              tm is None,
              "none found" if tm is None else f"it does: t={tm} dedup {dm['dedup_rate']:.1%}")

    run.observe("cost asymmetry",
                "a false merge is unrecoverable; a missed dedup is a duplicate row")
    winner = ("native" if (fm_n < fm_m and tn is not None)
              else ("MiniLM" if tm is not None and tn is None else "neither"))
    run.finish(f"safer at the merge gate: {winner}")


if __name__ == "__main__":
    main()
