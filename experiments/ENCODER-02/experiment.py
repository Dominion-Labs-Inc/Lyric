#!/usr/bin/env python3
"""ENCODER-02 — does the native encoder get better as the substrate is taught?

THE QUESTION ENCODER-01 COULD NOT ANSWER. That experiment measured one corpus
size and found the native encoder behind. But a taught-only encoder has nothing
to represent until it has been taught, so a single size cannot tell "this
approach does not work" from "this approach has not been fed yet". The decision
rests entirely on the SHAPE of the curve.

  H1  The native encoder's retrieval improves monotonically with the number of
      taught propositions. A flat curve means the approach does not scale and
      teaching will not rescue it.
  H2  Its separation improves with scale.
  H3  It crosses MiniLM on retrieval at some corpus size within this range.
      MiniLM is a flat line here -- teaching does not reach it -- so a crossing
      is the honest bar.

  REGISTERED IN ADVANCE: H3 may fail while H1 and H2 hold. That would say the
  approach is sound and the corpus is too small, which is a different finding
  from the approach being wrong, and it names the size that would settle it.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, SubstrateEncoder, invented_corpus,
                          retrieval, separation)

SIZES = [5, 10, 20, 30, 40, 50]


def main():
    run = Run("ENCODER-02 — scale: does teaching make the native encoder better?", [
        "H1 native retrieval improves with taught propositions",
        "H2 native separation improves with taught propositions",
        "H3 native crosses MiniLM on retrieval within this range",
    ])
    mini = MiniLM()
    curve = {}
    rows = []
    for n in SIZES:
        props, facts, questions, subs = invented_corpus(n_subjects=n)
        nat = SubstrateEncoder().learn(props)
        nr = retrieval(nat, questions, facts)
        mr = retrieval(mini, questions, facts)
        ns = separation(nat, facts, subs)
        ms = separation(mini, facts, subs)
        curve[n] = {"props": len(props), "facts": len(facts),
                    "native_mrr": nr["mrr"], "minilm_mrr": mr["mrr"],
                    "native_sep": ns, "minilm_sep": ms}
        rows.append(f"{n:>3} subj {len(props):>4} props {len(facts):>4} facts | "
                    f"MRR nat {nr['mrr']:.3f} vs mini {mr['mrr']:.3f} | "
                    f"SEP nat {ns:+.3f} vs mini {ms:+.3f}")
    run.table("corpus                          retrieval            separation", rows)
    run.data["curve"] = curve

    nat_mrr = [curve[n]["native_mrr"] for n in SIZES]
    nat_sep = [curve[n]["native_sep"] for n in SIZES]
    run.check("H1 native retrieval improves with scale",
              nat_mrr[-1] > nat_mrr[0],
              f"{nat_mrr[0]:.3f} at {SIZES[0]} subjects -> {nat_mrr[-1]:.3f} at {SIZES[-1]}")
    run.check("H1b and does not collapse at the largest size",
              nat_mrr[-1] >= max(nat_mrr) * 0.9,
              f"largest {nat_mrr[-1]:.3f} vs best {max(nat_mrr):.3f}")
    run.check("H2 native separation improves with scale",
              nat_sep[-1] > nat_sep[0],
              f"{nat_sep[0]:+.3f} -> {nat_sep[-1]:+.3f}")
    crossed = [n for n in SIZES if curve[n]["native_mrr"] > curve[n]["minilm_mrr"]]
    run.check("H3 native crosses MiniLM on retrieval",
              bool(crossed), f"crossed at {crossed}" if crossed else "never crossed in range")
    sep_crossed = [n for n in SIZES if curve[n]["native_sep"] > curve[n]["minilm_sep"]]
    run.observe("separation crossings", f"{sep_crossed}" if sep_crossed else "never")

    trend = "rising" if nat_mrr[-1] > nat_mrr[0] else ("flat" if nat_mrr[-1] == nat_mrr[0] else "falling")
    run.finish(f"native retrieval is {trend} with scale; "
               f"{'it can overtake MiniLM' if crossed else 'it does not overtake MiniLM in this range'}")


if __name__ == "__main__":
    main()
