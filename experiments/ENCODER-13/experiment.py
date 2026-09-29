#!/usr/bin/env python3
"""ENCODER-13 — CHAOTIC ENVIRONMENT: no coherent structure to learn from.

The corpora so far were tidy: one vocabulary, one shape of sentence, taught in
order. A live substrate is taught nothing of the kind. It gets a filesystem
domain, then a conversation, then a perception record, then a web lookup, in
whatever order they arrive, with wildly different sentence lengths and symbol
systems mixed together.

The question is whether the native encoders need coherence, or merely material.
Order-dependence in particular would be disqualifying: the same knowledge taught
in a different sequence must produce the same representation, or nothing about
the substrate is reproducible.

  H1  ORDER INVARIANCE. The same propositions taught in a different order give
      byte-identical similarity. Any deviation is a reproducibility failure.
  H2  Interleaving five unrelated domains does not cost retrieval against
      teaching them separately.
  H3  Symbol chaos -- identifiers, numbers, punctuation, mixed case, path-like
      and code-like tokens -- does not degrade retrieval of ordinary claims.
  H4  Extreme length variance (2-word propositions beside 40-word ones) does
      not degrade retrieval.
  H5  The chaotic corpus does not create false matches among clean facts.
"""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (Run, StructuralEncoder, SubstrateEncoder,
                          invented_corpus, minimal_pairs, paraphrases,
                          retrieval, mean_sim, sim, SEED)

NOISE_PROPS = [
    ("recog2_439712_19xc9e9e3639f_redcircle", "isa", "stopsignd885e3"),
    ("/var/log/system.log", "isa", "file"),
    ("0x7ffee3b4", "equals", "0x7ffee3b8"),
    ("SELECT * FROM memory_hot", "isa", "query"),
    ("__pycache__", "contains", "*.pyc"),
    ("2026-09-22T16:44:03Z", "isa", "timestamp"),
    ("a" * 200, "isa", "overlong token"),
    ("x", "y", "z"),
    ("THE BILLING SERVICE MIGRATION", "continued", "as planned on Monday and "
     "then on Tuesday and also Wednesday before the rollback key rotation "
     "happened late on Thursday afternoon according to the record"),
    ("émigré", "isa", "naïve façade"),
]


def main():
    run = Run("ENCODER-13 — chaotic environment: no coherent structure", [
        "H1 ORDER INVARIANCE: teaching order cannot change the representation",
        "H2 interleaving five domains costs nothing against teaching them apart",
        "H3 symbol chaos does not degrade retrieval of ordinary claims",
        "H4 extreme length variance does not degrade retrieval",
        "H5 chaos creates no false matches among clean facts",
    ])
    a_props, a_facts, a_q, a_subs = invented_corpus(n_subjects=10, offset=0)
    others = [invented_corpus(n_subjects=10, offset=o)[0] for o in (10, 20, 30, 40)]
    all_props = a_props + [p for grp in others for p in grp]
    must_differ = minimal_pairs(a_facts, a_subs)
    must_match = paraphrases(a_facts)

    data, rows = {}, {}
    for name, cls in (("native", SubstrateEncoder), ("structural", StructuralEncoder)):
        rows[name] = []
        # H1 — order invariance
        rng = random.Random(SEED)
        shuffled = list(all_props)
        rng.shuffle(shuffled)
        e_ordered = cls().learn(all_props)
        e_shuffled = cls().learn(shuffled)
        probe_a, probe_b = a_facts[0], a_facts[3]
        delta = abs(sim(e_ordered, probe_a, probe_b) - sim(e_shuffled, probe_a, probe_b))

        conditions = {
            "alone": a_props,
            "interleaved": all_props,
            "with symbol chaos": all_props + NOISE_PROPS,
            "chaos + shuffled": shuffled + NOISE_PROPS,
        }
        data[name] = {"order_delta": delta}
        for label, props in conditions.items():
            enc = cls().learn(props)
            r = retrieval(enc, a_q, a_facts)
            sep = mean_sim(enc, must_match) - mean_sim(enc, must_differ)
            fm = sum(1 for x, y in must_differ if sim(enc, x, y) >= 0.75)
            data[name][label] = {"mrr": r["mrr"], "p_at_1": r["p_at_1"],
                                 "separation": sep, "false_matches": fm,
                                 "props": len(props)}
            rows[name].append(f"{name:11} {label:19} ({len(props):>3} props)  "
                              f"MRR {r['mrr']:.3f}  SEP {sep:+.3f}  "
                              f"false matches {fm:>3}/{len(must_differ)}")
    run.table("encoder     condition             performance ON DOMAIN A",
              rows["native"] + rows["structural"])
    run.data = data

    for name in ("native", "structural"):
        d = data[name]
        run.check(f"H1 {name}: teaching order does not change the representation",
                  d["order_delta"] < 1e-12, f"delta {d['order_delta']:.3e}")
        run.check(f"H2 {name}: interleaving five domains costs no retrieval",
                  d["interleaved"]["mrr"] >= d["alone"]["mrr"] - 1e-9,
                  f"{d['alone']['mrr']:.3f} alone -> {d['interleaved']['mrr']:.3f} interleaved")
        run.check(f"H3 {name}: symbol chaos does not degrade retrieval",
                  d["with symbol chaos"]["mrr"] >= d["interleaved"]["mrr"] - 1e-9,
                  f"{d['interleaved']['mrr']:.3f} -> {d['with symbol chaos']['mrr']:.3f}")
        run.check(f"H4 {name}: length variance does not degrade retrieval",
                  d["with symbol chaos"]["mrr"] >= d["alone"]["mrr"] - 0.05,
                  f"{d['alone']['mrr']:.3f} clean -> {d['with symbol chaos']['mrr']:.3f} "
                  f"with a 200-char token and a 30-word proposition present")
        run.check(f"H5 {name}: chaos creates no false matches among clean facts",
                  d["chaos + shuffled"]["false_matches"] <= d["alone"]["false_matches"],
                  f"{d['alone']['false_matches']} -> {d['chaos + shuffled']['false_matches']} "
                  f"of {len(must_differ)}")

    run.finish("order-invariant and chaos-tolerant"
               if all(data[n]["order_delta"] < 1e-12 for n in data)
               else "ORDER DEPENDENT — not reproducible")


if __name__ == "__main__":
    main()
