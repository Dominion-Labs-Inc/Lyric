#!/usr/bin/env python3
"""ENCODER-08 — the untaught-term fix: does an explicit unknown signal work?

ENCODER-01 registered H5 in advance and it was confirmed: the native encoder
treats a term it was never taught as CONTRIBUTING NOTHING, so two sentences
differing only in an untaught word encode almost identically (0.872 against
0.699 for taught subjects -- worse than the case it was supposed to beat).

The principle is right everywhere else in this substrate: an honest gap rather
than a guess. Here it is exactly wrong. "I have never been taught this word" is
INFORMATION, and it should push two texts apart.

This tests the fix -- a dedicated dimension per unknown term -- and, just as
importantly, whether it costs anything elsewhere. A fix that repairs
discrimination by making everything dissimilar has fixed nothing.

  H1  With the fix, untaught-subject pairs score LOWER than taught-subject pairs
      -- restoring the ordering that H5 showed inverted.
  H2  The fix does not degrade retrieval.
  H3  The fix does not degrade paraphrase similarity.
  H4  The fix lowers the false-merge rate at the live threshold.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (Run, SubstrateEncoder, invented_corpus, real_corpus,
                          minimal_pairs, untaught_pairs, paraphrases,
                          retrieval, mean_sim, sim)

LIVE_THRESHOLD = 0.75


def main():
    run = Run("ENCODER-08 — the untaught-term fix", [
        "H1 untaught pairs score LOWER than taught pairs, with the fix",
        "H2 retrieval is not degraded",
        "H3 paraphrase similarity is not degraded",
        "H4 the false-merge rate falls at the live threshold",
    ])
    ip, ifacts, iq, isubs = invented_corpus(n_subjects=30)
    rp, rfacts, rq, rsubs = real_corpus()
    props, facts = ip + rp, ifacts + rfacts
    questions, subs = iq + rq, isubs + rsubs

    plain = SubstrateEncoder().learn(props)
    fixed = SubstrateEncoder(unknown_marks=True).learn(props)

    taught = minimal_pairs(facts, subs)
    untaught = untaught_pairs(facts)
    para = paraphrases(facts)

    rows, data = [], {}
    for name, enc in (("native", plain), ("native+unk", fixed)):
        r = retrieval(enc, questions, facts)
        t = mean_sim(enc, taught)
        u = mean_sim(enc, untaught)
        p = mean_sim(enc, para)
        fm = sum(1 for a, b in taught + untaught if sim(enc, a, b) >= LIVE_THRESHOLD)
        data[name] = {"mrr": r["mrr"], "p_at_1": r["p_at_1"], "taught_pair": t,
                      "untaught_pair": u, "paraphrase": p,
                      "false_merges": fm, "n_pairs": len(taught) + len(untaught)}
        rows.append(f"{name:12} MRR {r['mrr']:.3f}  taught-swap {t:.3f}  "
                    f"untaught-swap {u:.3f}  parap {p:.3f}  "
                    f"false merges {fm}/{len(taught)+len(untaught)}")
    run.table("encoder      retrieval   subject swapped (taught / untaught)   paraphrase", rows)
    run.data = data

    f, pl = data["native+unk"], data["native"]
    run.check("H1 with the fix, an untaught subject reads as MORE different",
              f["untaught_pair"] < f["taught_pair"],
              f"untaught {f['untaught_pair']:.3f} vs taught {f['taught_pair']:.3f}")
    run.check("H1b without the fix the ordering is inverted (the defect)",
              pl["untaught_pair"] > pl["taught_pair"],
              f"untaught {pl['untaught_pair']:.3f} vs taught {pl['taught_pair']:.3f}")
    run.check("H2 retrieval is not degraded",
              f["mrr"] >= pl["mrr"] - 1e-9, f"{pl['mrr']:.3f} -> {f['mrr']:.3f}")
    run.check("H3 paraphrase similarity is not degraded",
              f["paraphrase"] >= pl["paraphrase"] - 0.05,
              f"{pl['paraphrase']:.3f} -> {f['paraphrase']:.3f}")
    run.check("H4 the false-merge count falls",
              f["false_merges"] < pl["false_merges"],
              f"{pl['false_merges']} -> {f['false_merges']} of {f['n_pairs']} pairs")

    run.finish("the unknown-term signal "
               + ("repairs the inversion at no measured cost"
                  if f["untaught_pair"] < f["taught_pair"] and f["mrr"] >= pl["mrr"]
                  else "does not fully repair the defect"))


if __name__ == "__main__":
    main()
