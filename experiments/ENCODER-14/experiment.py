#!/usr/bin/env python3
"""ENCODER-14 — HALLUCINATION-PRONE ENVIRONMENT: plausible falsehoods.

This is how a substrate hallucinates. It does not invent text -- it has no
generator. It recalls a memory that LOOKS like the answer and is not, and then
answers from it with full confidence. The encoder is the component that decides
which memory looks like the answer.

So the environment is seeded with plausible falsehoods: for every true fact, a
variant that is well-formed, on-topic, and WRONG. "A marnic filters brine" sits
beside "A marnic filters sediment", "A threlp filters brine", "A marnic blocks
brine". Every one is a sentence a careless teacher might have written.

  H1  Asked its question, the TRUE fact outranks every plausible falsehood.
      This is the hallucination rate: how often a lie wins.
  H2  The true fact is not merely first but SEPARATED -- a margin over the best
      falsehood, so a small perturbation cannot flip the answer.
  H3  A wrong-object variant ("filters sediment") is caught. It shares subject
      and relation; only the object is false.
  H4  A wrong-subject variant ("A threlp filters brine") is caught. It shares
      everything but what the claim is about.
  H5  A wrong-relation variant ("A marnic blocks brine") is caught.

  H3-H5 are separated because they fail for DIFFERENT reasons and an encoder
  can be strong on one and blind on another.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, StructuralEncoder, SubstrateEncoder,
                          invented_corpus, cos_for)


def main():
    run = Run("ENCODER-14 — hallucination-prone: plausible falsehoods beside the truth", [
        "H1 the true fact outranks every plausible falsehood",
        "H2 it wins by a margin, not by a hair",
        "H3 a wrong-OBJECT variant is caught",
        "H4 a wrong-SUBJECT variant is caught",
        "H5 a wrong-RELATION variant is caught",
    ])
    props, facts, questions, subs = invented_corpus(n_subjects=30)

    # For each true fact, three plausible falsehoods.
    WRONG_OBJ = ["sediment", "vapour", "residue", "backflow", "condensate"]
    WRONG_REL = ["blocks", "holds", "drains", "cools", "seals"]
    trials = []
    for i, (q, truth) in enumerate(questions):
        if " is a " in truth:
            continue                       # build the action facts only
        import re
        m = re.match(r"A (\w+) (\w+) (.+)\.", truth)
        if not m:
            continue
        subj, rel, obj = m.groups()
        other_subj = subs[(i + 7) % len(subs)]
        if other_subj == subj:
            continue
        # THE FALSEHOOD MUST ACTUALLY BE FALSE. The wrong-object list is drawn
        # from the same pool as the true objects, so for 4 subjects in 30 the
        # "falsehood" was the taught fact restated -- and the measured
        # hallucination rate was exactly those 4. The harness was generating
        # truths and scoring them as lies.
        wrong_obj = next((w for w in WRONG_OBJ if w != obj), None)
        if wrong_obj is None:
            continue
        wrong_rel = next((w for w in WRONG_REL if w != rel), None)
        if wrong_rel is None:
            continue
        trials.append({
            "question": q, "truth": truth,
            "wrong_object": f"A {subj} {rel} {wrong_obj}.",
            "wrong_subject": f"A {other_subj} {rel} {obj}.",
            "wrong_relation": f"A {subj} {wrong_rel} {obj}.",
        })

    mini = MiniLM()
    nat = SubstrateEncoder().learn(props)
    st = StructuralEncoder().learn(props)
    encoders = [("MiniLM", mini), ("native", nat), ("structural", st)]

    KINDS = ("wrong_object", "wrong_subject", "wrong_relation")
    data, rows = {}, []
    for name, enc in encoders:
        cos = cos_for(enc)
        beaten = {k: 0 for k in KINDS}
        hallucinations, margins = 0, []
        for t in trials:
            qv = enc.encode(t["question"])
            s_true = cos(qv, enc.encode(t["truth"]))
            worst = -1.0
            for k in KINDS:
                s_false = cos(qv, enc.encode(t[k]))
                if s_true > s_false:
                    beaten[k] += 1
                worst = max(worst, s_false)
            margins.append(s_true - worst)
            if worst >= s_true:
                hallucinations += 1
        n = max(1, len(trials))
        data[name] = {"trials": n, "hallucinations": hallucinations,
                      "hallucination_rate": hallucinations / n,
                      "mean_margin": sum(margins) / n,
                      **{k: beaten[k] / n for k in KINDS}}
        rows.append(f"{name:11} hallucinated {hallucinations:>3}/{n}  "
                    f"({hallucinations/n:5.1%})  margin {sum(margins)/n:+.3f}  | "
                    f"obj {beaten['wrong_object']/n:5.1%}  "
                    f"subj {beaten['wrong_subject']/n:5.1%}  "
                    f"rel {beaten['wrong_relation']/n:5.1%}")
    run.table(f"encoder     a falsehood outranked the truth   |  caught, by kind "
              f"({len(trials)} trials)", rows)
    run.data = data

    for name, _ in encoders:
        d = data[name]
        run.check(f"H1 {name}: the truth always outranks the falsehoods",
                  d["hallucinations"] == 0,
                  f"{d['hallucinations']}/{d['trials']} questions answered with a falsehood")
        run.check(f"H2 {name}: it wins by a margin (>= 0.05)",
                  d["mean_margin"] >= 0.05, f"mean margin {d['mean_margin']:+.3f}")
        run.check(f"H3 {name}: wrong-OBJECT variants caught",
                  d["wrong_object"] == 1.0, f"{d['wrong_object']:.1%} caught")
        run.check(f"H4 {name}: wrong-SUBJECT variants caught",
                  d["wrong_subject"] == 1.0, f"{d['wrong_subject']:.1%} caught")
        run.check(f"H5 {name}: wrong-RELATION variants caught",
                  d["wrong_relation"] == 1.0, f"{d['wrong_relation']:.1%} caught")

    best = min(data, key=lambda k: data[k]["hallucination_rate"])
    run.finish(f"lowest hallucination rate: {best} at "
               f"{data[best]['hallucination_rate']:.1%} over {len(trials)} trials")


if __name__ == "__main__":
    main()
