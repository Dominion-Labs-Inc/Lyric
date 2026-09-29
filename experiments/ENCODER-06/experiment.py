#!/usr/bin/env python3
"""ENCODER-06 — polysemy: one surface word, two taught meanings.

`filter` is a thing and something one does. `bank`, `plant`, `charge` and
`current` each name two unrelated things. A substrate taught both senses must
keep them apart, or a question about one recalls the other, and the merge gate
collapses two unrelated facts into one row.

MiniLM has a single fixed vector per word regardless of sense. The native
encoder builds a term from the company it keeps, so IN PRINCIPLE two senses
taught in different company should pull apart -- this measures whether they do.

  H1  Two senses of one word, taught in different company, score below the
      merge threshold.
  H2  The native encoder separates senses better than MiniLM, because its
      representation comes from what each sense was taught alongside.
  H3  Same-sense pairs still score HIGH -- separating senses must not be
      achieved by making everything dissimilar.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import MiniLM, Run, StructuralEncoder, SubstrateEncoder, sim

LIVE_THRESHOLD = 0.75

#: (word, sense-A propositions, sense-B propositions, A sentence, B sentence, A' same-sense)
POLYSEMOUS = [
    ("bank", [("bank", "isa", "riverside"), ("bank", "borders", "river"),
              ("bank", "holds", "silt")],
             [("bank", "isa", "institution"), ("bank", "holds", "deposits"),
              ("bank", "issues", "loans")],
     "The bank borders the river.", "The bank issues loans.",
     "The bank holds silt from the river."),
    ("plant", [("plant", "isa", "organism"), ("plant", "grows", "leaves"),
               ("plant", "needs", "sunlight")],
              [("plant", "isa", "factory"), ("plant", "assembles", "engines"),
               ("plant", "employs", "workers")],
     "The plant grows leaves.", "The plant assembles engines.",
     "The plant needs sunlight to grow."),
    ("charge", [("charge", "isa", "electricity"), ("charge", "flows", "wires")],
               [("charge", "isa", "fee"), ("charge", "appears", "invoices")],
     "The charge flows through wires.", "The charge appears on invoices.",
     "The charge is electricity in wires."),
    ("current", [("current", "isa", "flow"), ("current", "moves", "water")],
                [("current", "isa", "present"), ("current", "describes", "today")],
     "The current moves the water.", "The current describes today.",
     "The current is a flow of water."),
    ("filter", [("filter", "isa", "device"), ("filter", "removes", "particles")],
               [("filter", "isa", "action"), ("filter", "selects", "records")],
     "The filter removes particles.", "The filter selects records.",
     "The filter is a device removing particles."),
]


def main():
    run = Run("ENCODER-06 — polysemy: one word, two taught senses", [
        "H1 two senses of one word score below the merge threshold",
        "H2 the native encoder separates senses better than MiniLM",
        "H3 same-sense pairs still score high",
    ])
    props = []
    for _, a, b, *_ in POLYSEMOUS:
        props += a + b

    mini, nat = MiniLM(), SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    rows, data = [], {}
    for name, enc in (("MiniLM", mini), ("native", nat), ("structural", st)):
        cross, same, detail = [], [], []
        for word, _a, _b, sa, sb, sa2 in POLYSEMOUS:
            c = sim(enc, sa, sb)
            s = sim(enc, sa, sa2)
            cross.append(c); same.append(s)
            detail.append({"word": word, "cross_sense": c, "same_sense": s})
        m = lambda xs: sum(xs) / max(1, len(xs))
        over = sum(1 for x in cross if x >= LIVE_THRESHOLD)
        data[name] = {"cross_sense_mean": m(cross), "same_sense_mean": m(same),
                      "margin": m(same) - m(cross),
                      "senses_merge_eligible": over, "n": len(cross), "per_word": detail}
        rows.append(f"{name:8} cross-sense {m(cross):.3f}  same-sense {m(same):.3f}  "
                    f"margin {m(same)-m(cross):+.3f} | {over}/{len(cross)} sense pairs merge-eligible")
    run.table("encoder   different senses   same sense   margin", rows)
    run.data = data

    for name in ("MiniLM", "native", "structural"):
        d = data[name]
        run.check(f"H1 {name}: different senses fall below the merge threshold",
                  d["senses_merge_eligible"] == 0,
                  f"{d['senses_merge_eligible']}/{d['n']} sense pairs score >= {LIVE_THRESHOLD}")
        run.check(f"H3 {name}: same-sense pairs still score high",
                  d["same_sense_mean"] >= 0.60, f"{d['same_sense_mean']:.3f}")
    run.check("H2 native separates senses better than MiniLM",
              data["native"]["margin"] > data["MiniLM"]["margin"],
              f"native margin {data['native']['margin']:+.3f} vs "
              f"MiniLM {data['MiniLM']['margin']:+.3f}")

    for word in [p["word"] for p in data["native"]["per_word"]]:
        n = next(x for x in data["native"]["per_word"] if x["word"] == word)
        m = next(x for x in data["MiniLM"]["per_word"] if x["word"] == word)
        run.observe(f"{word}", f"cross-sense native {n['cross_sense']:.3f} / "
                               f"MiniLM {m['cross_sense']:.3f}")
    run.finish(f"sense separation margin: native {data['native']['margin']:+.3f}, "
               f"MiniLM {data['MiniLM']['margin']:+.3f}")


if __name__ == "__main__":
    main()
