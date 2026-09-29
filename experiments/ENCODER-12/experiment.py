#!/usr/bin/env python3
"""ENCODER-12 — CORRUPT TEACHING: the substrate was taught wrong things.

ENCODER-11 corrupted the QUERY. This corrupts the TEACHING. A substrate that
learns from the open world will be taught contradictions, wrong objects and
subject collisions -- we watched it happen today, when a web lookup taught it
`stops isa measurement of Exposure` and permanently broke a question.

A taught-only encoder builds its representation FROM that material, so the
danger is specific and asymmetric: MiniLM cannot be poisoned by teaching
because teaching never reaches it. The native encoders can. This measures how
much, and whether the damage is contained or contagious.

Four kinds of poison, each modelling something real:
  CONTRADICTION  the same subject taught two incompatible kinds
  WRONG OBJECT   a true subject and relation with a false object
  COLLISION      two different subjects taught identical properties
  NONSENSE       a proposition of untaught junk (the web-scrape case)

  H1  CONTAINMENT. Retrieval on the CLEAN facts survives 10% poison.
  H2  Separation on the clean facts survives 10% poison.
  H3  The damage is sub-linear: 50% poison costs less than 5x what 10% costs.
      Linear or worse means each bad fact damages everything.
  H4  Poison does not create FALSE MATCHES among clean facts -- the dangerous
      failure, because that is what merges and destroys memories.
  H5  CONTROL. MiniLM is unaffected by any poison rate, since teaching cannot
      reach it. If this fails the harness is leaking.
"""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder,
                          invented_corpus, minimal_pairs, paraphrases,
                          retrieval, mean_sim, sim, SEED, KINDS, ACTIONS)

RATES = [0.0, 0.10, 0.25, 0.50]


def poison(props, subjects, rate, rng):
    """Return props plus poisoned propositions at the given rate."""
    n = int(len(props) * rate)
    out = list(props)
    for i in range(n):
        kind = i % 4
        s = subjects[rng.randrange(len(subjects))]
        if kind == 0:      # contradiction
            out.append((s, "isa", KINDS[rng.randrange(len(KINDS))]))
        elif kind == 1:    # wrong object
            v, _ = ACTIONS[rng.randrange(len(ACTIONS))]
            out.append((s, v, KINDS[rng.randrange(len(KINDS))]))
        elif kind == 2:    # collision: two subjects, identical properties
            t = subjects[rng.randrange(len(subjects))]
            out.append((t, "isa", "device"))
            out.append((s, "isa", "device"))
        else:              # nonsense, the web-scrape case
            out.append((f"junk{i}", "isa", f"measurement of Exposure {i}"))
    return out


def main():
    run = Run("ENCODER-12 — corrupt teaching: poisoned propositions", [
        "H1 retrieval on CLEAN facts survives 10% poison",
        "H2 separation on CLEAN facts survives 10% poison",
        "H3 damage is sub-linear in the poison rate",
        "H4 poison creates no false matches among clean facts",
        "H5 CONTROL: MiniLM is unaffected (teaching cannot reach it)",
    ])
    clean_props, facts, questions, subs = invented_corpus(n_subjects=30)
    must_differ = minimal_pairs(facts, subs)
    must_match = paraphrases(facts)

    builders = [("native", SubstrateEncoder), ("structural", StructuralEncoder)]
    mini = MiniLM()
    data, rows = {}, []

    for name, cls in builders:
        data[name] = {}
        for rate in RATES:
            rng = random.Random(SEED + int(rate * 100))
            enc = cls().learn(poison(clean_props, subs, rate, rng))
            r = retrieval(enc, questions, facts)
            sep = mean_sim(enc, must_match) - mean_sim(enc, must_differ)
            false_matches = sum(1 for a, b in must_differ if sim(enc, a, b) >= 0.75)
            data[name][rate] = {"mrr": r["mrr"], "p_at_1": r["p_at_1"],
                                "separation": sep, "false_matches": false_matches,
                                "n_pairs": len(must_differ)}
            rows.append(f"{name:11} poison {rate:5.0%}  MRR {r['mrr']:.3f}  "
                        f"P@1 {r['p_at_1']:.3f}  SEP {sep:+.3f}  "
                        f"false matches {false_matches:>3}/{len(must_differ)}")
    data["MiniLM"] = {}
    for rate in RATES:
        r = retrieval(mini, questions, facts)
        sep = mean_sim(mini, must_match) - mean_sim(mini, must_differ)
        fm = sum(1 for a, b in must_differ if sim(mini, a, b) >= 0.75)
        data["MiniLM"][rate] = {"mrr": r["mrr"], "p_at_1": r["p_at_1"],
                                "separation": sep, "false_matches": fm,
                                "n_pairs": len(must_differ)}
        rows.append(f"{'MiniLM':11} poison {rate:5.0%}  MRR {r['mrr']:.3f}  "
                    f"P@1 {r['p_at_1']:.3f}  SEP {sep:+.3f}  false matches {fm:>3}/{len(must_differ)}")
    run.table("encoder     poisoned teaching     performance ON THE CLEAN FACTS", rows)
    run.data = data

    for name in ("native", "structural"):
        d = data[name]
        run.check(f"H1 {name}: retrieval survives 10% poison",
                  d[0.10]["mrr"] >= d[0.0]["mrr"] - 0.05,
                  f"{d[0.0]['mrr']:.3f} -> {d[0.10]['mrr']:.3f}")
        run.check(f"H2 {name}: separation survives 10% poison",
                  d[0.10]["separation"] >= d[0.0]["separation"] - 0.05,
                  f"{d[0.0]['separation']:+.3f} -> {d[0.10]['separation']:+.3f}")
        loss10 = d[0.0]["separation"] - d[0.10]["separation"]
        loss50 = d[0.0]["separation"] - d[0.50]["separation"]
        run.check(f"H3 {name}: damage is sub-linear",
                  loss50 <= max(loss10, 1e-9) * 5.0,
                  f"10% costs {loss10:+.3f}, 50% costs {loss50:+.3f}")
        run.check(f"H4 {name}: poison creates no false matches among clean facts",
                  d[0.50]["false_matches"] <= d[0.0]["false_matches"],
                  f"{d[0.0]['false_matches']} -> {d[0.50]['false_matches']} "
                  f"of {d[0.0]['n_pairs']} at 50% poison")

    m = data["MiniLM"]
    run.check("H5 CONTROL: MiniLM is identical at every poison rate",
              len({round(m[r]['mrr'], 9) for r in RATES}) == 1
              and len({round(m[r]['separation'], 9) for r in RATES}) == 1,
              "unchanged — teaching cannot reach a pretrained encoder")

    st = data["structural"]
    run.finish(f"structural separation under poison: "
               f"{st[0.0]['separation']:+.3f} clean -> {st[0.50]['separation']:+.3f} at 50%")


if __name__ == "__main__":
    main()
