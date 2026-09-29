#!/usr/bin/env python3
"""ENCODER-09 — interference: does teaching something new damage what was learned?

A substrate that keeps learning must not degrade at what it already knew. For a
pretrained encoder this cannot happen -- teaching never reaches it, which is
both its safety and the reason it can never improve. For the native encoder,
every new proposition changes the association table and the inverse-frequency
weights GLOBALLY, so a newly taught domain can in principle move terms in an
old one. That is catastrophic interference, and it would be disqualifying.

  H1  Retrieval in domain A does not fall after domain B is taught.
  H2  Separation in domain A does not fall after domain B is taught.
  H3  Damage does not accumulate: after five further domains, A still holds.
  H4  The newly taught domain is itself learned (a control -- an encoder that
      learned nothing new would trivially pass H1-H3).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (Run, SubstrateEncoder, invented_corpus, real_corpus,
                          retrieval, separation)


def main():
    run = Run("ENCODER-09 — interference: does new teaching damage old knowledge?", [
        "H1 retrieval in the first domain survives teaching a second",
        "H2 separation in the first domain survives teaching a second",
        "H3 damage does not accumulate over five further domains",
        "H4 the newly taught domain is itself learned (control)",
    ])
    a_props, a_facts, a_q, a_subs = invented_corpus(n_subjects=10, offset=0)
    b_props, b_facts, b_q, b_subs = invented_corpus(n_subjects=10, offset=10)
    c_props, c_facts, c_q, c_subs = invented_corpus(n_subjects=10, offset=20)
    d_props, d_facts, d_q, d_subs = invented_corpus(n_subjects=10, offset=30)
    e_props, e_facts, e_q, e_subs = invented_corpus(n_subjects=10, offset=40)
    r_props, r_facts, r_q, r_subs = real_corpus()

    stages = [
        ("A alone", a_props),
        ("A + B", a_props + b_props),
        ("A + B + C", a_props + b_props + c_props),
        ("A..D", a_props + b_props + c_props + d_props),
        ("A..E", a_props + b_props + c_props + d_props + e_props),
        ("A..E + real", a_props + b_props + c_props + d_props + e_props + r_props),
    ]

    rows, data = [], {}
    for label, props in stages:
        enc = SubstrateEncoder().learn(props)
        r = retrieval(enc, a_q, a_facts)
        s = separation(enc, a_facts, a_subs)
        data[label] = {"a_mrr": r["mrr"], "a_p1": r["p_at_1"], "a_sep": s,
                       "props": len(props)}
        rows.append(f"{label:14} ({len(props):>3} props taught)  "
                    f"domain-A MRR {r['mrr']:.3f}  P@1 {r['p_at_1']:.3f}  SEP {s:+.3f}")
    run.table("taught so far                      performance ON DOMAIN A", rows)
    run.data["stages"] = data

    base = data["A alone"]
    after_b = data["A + B"]
    final = data["A..E + real"]

    run.check("H1 domain-A retrieval survives a second domain",
              after_b["a_mrr"] >= base["a_mrr"] - 1e-9,
              f"{base['a_mrr']:.3f} -> {after_b['a_mrr']:.3f}")
    run.check("H2 domain-A separation survives a second domain",
              after_b["a_sep"] >= base["a_sep"] - 0.02,
              f"{base['a_sep']:+.3f} -> {after_b['a_sep']:+.3f}")
    run.check("H3 no accumulated damage after five further domains",
              final["a_mrr"] >= base["a_mrr"] - 1e-9,
              f"{base['a_mrr']:.3f} -> {final['a_mrr']:.3f} over "
              f"{base['props']} -> {final['props']} propositions")
    run.check("H3b separation does not accumulate damage",
              final["a_sep"] >= base["a_sep"] - 0.05,
              f"{base['a_sep']:+.3f} -> {final['a_sep']:+.3f}")

    full = SubstrateEncoder().learn(stages[-1][1])
    rb = retrieval(full, b_q, b_facts)
    run.check("H4 control — the later-taught domain is itself learned",
              rb["mrr"] > 0.4, f"domain-B MRR {rb['mrr']:.3f} after teaching everything")
    run.data["domain_b_after_all"] = rb

    drift = final["a_sep"] - base["a_sep"]
    run.finish(f"domain-A separation moved {drift:+.3f} across "
               f"{final['props'] - base['props']} newly taught propositions")


if __name__ == "__main__":
    main()
