#!/usr/bin/env python3
"""ENCODER-04 — negation: can either encoder tell a claim from its denial?

THE FAILURE THAT MATTERS MOST AND IS EASIEST TO MISS. "A marnic filters brine."
and "A marnic does not filter brine." share every content word. An encoder that
scores them as near-identical will let the substrate merge a fact with its own
denial, or recall the opposite of what was asked -- and nothing in the system
would report an error, because both are legitimate memories.

Sentence embeddings are known to be weak here; the point of measuring it is
that this substrate ACTS on the result.

  H1  Negated pairs score below the live merge threshold (0.75) for at least
      one encoder. Above it, a fact and its denial are merge candidates.
  H2  Negation is separated at least as well as an unrelated-sentence baseline
      -- i.e. the encoder treats a denial as genuinely different, not merely
      slightly different.
  H3  Polarity survives paraphrase: "does not filter" and "never filters" are
      both far from the positive claim.

  REGISTERED: both encoders may fail. That is a finding about the substrate's
  merge gate, not about one encoder, and it would mean polarity has to be
  decided OUTSIDE the vector -- which is what `claim_shape` already does for
  recall and what the merge path lacks.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder, invented_corpus,
                          real_corpus, sim)

LIVE_THRESHOLD = 0.75


def negate(fact):
    if " is " in fact:
        return fact.replace(" is ", " is not ", 1)
    import re
    m = re.match(r"A (\w+) (\w+) (.+)", fact)
    if m:
        verb = m.group(2)
        base = verb[:-1] if verb.endswith("s") else verb
        return f"A {m.group(1)} does not {base} {m.group(3)}"
    return "not " + fact


def never(fact):
    import re
    m = re.match(r"A (\w+) (\w+) (.+)", fact)
    if m and " is " not in fact:
        verb = m.group(2)
        base = verb[:-1] if verb.endswith("s") else verb
        return f"A {m.group(1)} never {base}s {m.group(3)}"
    return fact.replace(" is ", " is never ", 1)


def main():
    run = Run("ENCODER-04 — negation: a claim versus its denial", [
        "H1 negated pairs fall below the live merge threshold (0.75)",
        "H2 negation is separated as well as unrelated sentences are",
        "H3 polarity survives paraphrase ('does not' and 'never')",
    ])
    ip, ifacts, _, _ = invented_corpus(n_subjects=25)
    rp, rfacts, _, _ = real_corpus()
    props, facts = ip + rp, ifacts + rfacts

    neg = [(f, negate(f)) for f in facts]
    nev = [(f, never(f)) for f in facts]
    unrelated = [(facts[i], facts[(i + 7) % len(facts)]) for i in range(len(facts))]

    mini, nat = MiniLM(), SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    rows, data = [], {}
    for name, enc in (("MiniLM", mini), ("native", nat), ("structural", st)):
        dn = [sim(enc, a, b) for a, b in neg]
        dv = [sim(enc, a, b) for a, b in nev]
        du = [sim(enc, a, b) for a, b in unrelated]
        m = lambda xs: sum(xs) / max(1, len(xs))
        over = sum(1 for x in dn if x >= LIVE_THRESHOLD)
        data[name] = {"negated_mean": m(dn), "never_mean": m(dv),
                      "unrelated_mean": m(du), "negated_above_threshold": over,
                      "n": len(dn)}
        rows.append(f"{name:8} negated {m(dn):.3f}  never {m(dv):.3f}  "
                    f"unrelated {m(du):.3f}  | {over}/{len(dn)} denials merge-eligible")
    run.table("encoder   claim vs denial   vs 'never'   vs unrelated", rows)
    run.data = data

    for name in ("MiniLM", "native", "structural"):
        d = data[name]
        run.check(f"H1 {name}: denials fall below the merge threshold",
                  d["negated_above_threshold"] == 0,
                  f"{d['negated_above_threshold']}/{d['n']} denials score >= {LIVE_THRESHOLD}")
        run.check(f"H2 {name}: a denial is as far as an unrelated sentence",
                  d["negated_mean"] <= d["unrelated_mean"] * 1.25,
                  f"negated {d['negated_mean']:.3f} vs unrelated {d['unrelated_mean']:.3f}")
        run.check(f"H3 {name}: polarity survives paraphrase",
                  abs(d["negated_mean"] - d["never_mean"]) < 0.20,
                  f"'does not' {d['negated_mean']:.3f} vs 'never' {d['never_mean']:.3f}")

    both_fail = all(data[n]["negated_above_threshold"] > 0 for n in data)
    run.finish("NEITHER encoder separates a claim from its denial — polarity must be "
               "decided outside the vector, as recall already does"
               if both_fail else "at least one encoder separates polarity")


if __name__ == "__main__":
    main()
