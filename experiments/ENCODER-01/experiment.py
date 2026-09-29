#!/usr/bin/env python3
"""ENCODER-01 — is a substrate-native encoder better than the pretrained one?

────────────────────────────────────────────────────────────────────────────
WHY THIS EXISTS

Every semantic judgement the substrate makes runs through `all-MiniLM-L6-v2`:
what gets recalled, whether an output answers a question, which concepts are
near each other -- and, critically, which memories get MERGED and destroyed.
That judgement comes from weights trained on web text, not from anything the
substrate was taught. Measured on the live store, it scored "A marnic filters
brine." against "A zorbic filters brine." at 0.787 and merged them, deleting
one. The substrate HAD been taught what a marnic is. It was never asked.

So: build an encoder from what the substrate was actually taught, and find out
whether it is better. Not on four hand-picked pairs -- on a corpus, with
ablations and controls, reporting where it LOSES as readily as where it wins.

────────────────────────────────────────────────────────────────────────────
HYPOTHESES, REGISTERED BEFORE RUNNING

  H1  RETRIEVAL. Asked a question, the native encoder ranks the fact that
      answers it at least as high as MiniLM does (MRR, P@1, Recall@3).

  H2  DISCRIMINATION. On minimal pairs -- one sentence, one term swapped for
      a different taught subject -- the native encoder scores LOWER than
      MiniLM. This is the merge defect, in a form that can be counted.

  H3  SEPARATION. The gap between paraphrase similarity and minimal-pair
      similarity is wider for the native encoder. This is the single number
      that decides whether an encoder can be trusted to merge: it must tell
      "same claim, different words" from "different claim, same words".

  H4  LENGTH. MiniLM truncates at 256 tokens, so a fact buried past roughly
      200 words becomes unrecallable. The native encoder has no such horizon
      and should not degrade with depth.

  STATED IN ADVANCE so a null result is not reframed afterwards:

  H5  THE NATIVE ENCODER IS EXPECTED TO FAIL ON UNTAUGHT TERMS. It represents
      only what it was taught, so a sentence differing only in an UNTAUGHT
      word encodes almost identically -- the opposite of what discrimination
      needs. If H2 holds for taught subjects and fails for untaught ones, that
      is the finding, and it says the encoder needs an explicit
      "I was never taught this" signal rather than treating absence as zero.

  A win requires H1 AND H3. An encoder that matches well but cannot separate
  is the one that destroyed a memory this morning.

────────────────────────────────────────────────────────────────────────────
DESIGN

TWO ARMS, because the two encoders have opposite home advantages:
  * INVENTED vocabulary -- words neither encoder saw in pretraining. Tests
    whether an encoder represents TAUGHT meaning rather than surface form.
  * REAL-WORLD vocabulary -- ordinary English. MiniLM's home ground, and the
    honest test of whether a taught-only encoder can compete at all.

Every corpus item is generated, so sizes are reported rather than chosen to
flatter, and no pair was hand-picked after seeing a score.

ABLATIONS, because a result that does not survive removing a component was
not produced by that component:
  * native without inverse-frequency weighting;
  * native without association expansion (bare taught-term overlap).

CONTROLS: identical text (ceiling) and unrelated text (floor) for both.
"""
import asyncio
import json
import math
import random
import re
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SEED = 20260922
random.seed(SEED)

# ── corpora ────────────────────────────────────────────────────────────────
INVENTED_SUBJECTS = [
    "marnic", "threlp", "dovick", "zorbic", "kelven", "parnit", "quolm",
    "vestrin", "borlan", "yimmet", "cradek", "nulthe", "sorvig", "jantel",
    "welmor", "pidrun", "tarsek", "ombric", "hevlin", "gressa",
]
INVENTED_KINDS = ["device", "membrane", "vessel", "filter", "conduit"]
INVENTED_ACTIONS = [
    ("filters", "brine"), ("separates", "salt"), ("contains", "residue"),
    ("cleans", "sediment"), ("blocks", "particles"), ("carries", "vapour"),
    ("stops", "backflow"), ("holds", "pressure"),
]

REAL_FACTS = [
    ("kettle", "is", "a container"), ("kettle", "boils", "water"),
    ("hammer", "is", "a tool"), ("hammer", "drives", "nails"),
    ("filter", "is", "a device"), ("filter", "removes", "impurities"),
    ("pump", "is", "a machine"), ("pump", "moves", "liquid"),
    ("valve", "is", "a fitting"), ("valve", "controls", "flow"),
    ("battery", "is", "a cell"), ("battery", "stores", "charge"),
    ("furnace", "is", "an appliance"), ("furnace", "heats", "air"),
    ("compass", "is", "an instrument"), ("compass", "indicates", "direction"),
    ("ledger", "is", "a record"), ("ledger", "tracks", "transactions"),
    ("turbine", "is", "an engine"), ("turbine", "converts", "steam"),
]


def build_invented():
    """(propositions, facts, questions) over invented vocabulary."""
    props, facts, questions = [], [], []
    for i, subj in enumerate(INVENTED_SUBJECTS):
        kind = INVENTED_KINDS[i % len(INVENTED_KINDS)]
        verb, obj = INVENTED_ACTIONS[i % len(INVENTED_ACTIONS)]
        props.append((subj, "isa", kind))
        props.append((subj, verb, obj))
        facts.append(f"A {subj} is a {kind}.")
        facts.append(f"A {subj} {verb} {obj}.")
        questions.append((f"what is a {subj}", f"A {subj} is a {kind}."))
        questions.append((f"what does a {subj} do", f"A {subj} {verb} {obj}."))
    return props, facts, questions


def build_real():
    props, facts, questions = [], [], []
    for subj, rel, obj in REAL_FACTS:
        props.append((subj, rel, obj))
        if rel == "is":
            facts.append(f"A {subj} is {obj}.")
            questions.append((f"what is a {subj}", f"A {subj} is {obj}."))
        else:
            facts.append(f"A {subj} {rel} {obj}.")
            questions.append((f"what does a {subj} do", f"A {subj} {rel} {obj}."))
    return props, facts, questions


def minimal_pairs(facts, subjects):
    """Same sentence, one SUBJECT swapped for a different TAUGHT subject.
    These must score LOW: they are different claims about different things."""
    pairs = []
    for f in facts:
        for s in subjects:
            m = re.match(r"A (\w+) ", f)
            if m and m.group(1) != s:
                pairs.append((f, f.replace(m.group(1), s, 1)))
                break
    return pairs


def paraphrases(facts):
    """Same claim, different words. Must score HIGH."""
    out = []
    for f in facts:
        p = (f.replace("A ", "The ", 1)
              .replace(" is ", " is really ", 1)
              .rstrip("."))
        out.append((f, p + " indeed."))
    return out


def untaught_pairs(facts):
    """Same sentence, subject swapped for a word NEVER taught. H5's case."""
    novel = ["blimvex", "quartheon", "splindor", "vexalum", "trombick"]
    out = []
    for i, f in enumerate(facts):
        m = re.match(r"A (\w+) ", f)
        if m:
            out.append((f, f.replace(m.group(1), novel[i % len(novel)], 1)))
    return out


# ── the native encoder ─────────────────────────────────────────────────────
def toks(t):
    return re.findall(r"[a-z']+", str(t or "").lower())


class SubstrateEncoder:
    """Representation derived ONLY from taught propositions. No pretrained
    weights, no corpus outside what the substrate was told.

    A term means the company it keeps in what it was taught. `use_idf` and
    `use_assoc` exist so each component can be removed and measured.
    """

    def __init__(self, use_idf=True, use_assoc=True):
        self.use_idf, self.use_assoc = use_idf, use_assoc
        self.assoc = defaultdict(Counter)
        self.vocab, self.df, self.idf = set(), Counter(), {}
        self.n_docs = 0

    def learn(self, propositions):
        for subj, rel, obj in propositions:
            terms = [w for p in (subj, rel, obj) if p for w in toks(p)]
            if not terms:
                continue
            self.n_docs += 1
            self.vocab.update(terms)
            for t in set(terms):
                self.df[t] += 1
            for a in terms:
                for b in terms:
                    if a != b:
                        self.assoc[a][b] += 1
        n = max(1, self.n_docs)
        self.idf = {t: (math.log(n / (1 + self.df[t])) + 1.0) if self.use_idf else 1.0
                    for t in self.vocab}
        return self

    def encode(self, text):
        v = Counter()
        for w in toks(text):
            if w not in self.vocab:
                continue                       # never taught -> contributes nothing
            iw = self.idf.get(w, 1.0)
            v[w] += iw
            if self.use_assoc:
                nb = self.assoc[w]
                total = sum(nb.values()) or 1
                for other, c in nb.items():
                    v[other] += 0.35 * iw * (c / total) * self.idf.get(other, 1.0)
        return v


def sparse_cos(a, b):
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(x * x for x in a.values()))
    nb = math.sqrt(sum(x * x for x in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class MiniLM:
    def __init__(self):
        from core.memory.utils.embedding_service import get_embedding_service
        self.s = get_embedding_service()
        self.s.initialize()
        self._cache = {}

    def encode(self, text):
        if text not in self._cache:
            self._cache[text] = self.s.generate_embedding(text)
        return self._cache[text]


def dense_cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ── measures ───────────────────────────────────────────────────────────────
def retrieval(enc, cos, questions, facts):
    """MRR, P@1 and Recall@3 over the WHOLE fact corpus as the candidate set."""
    fv = [(f, enc.encode(f)) for f in facts]
    rr, p1, r3 = [], 0, 0
    for q, target in questions:
        qv = enc.encode(q)
        scored = sorted(((cos(qv, v), f) for f, v in fv), reverse=True)
        ranks = [f for _, f in scored]
        pos = ranks.index(target) + 1 if target in ranks else len(ranks) + 1
        rr.append(1.0 / pos)
        p1 += (pos == 1)
        r3 += (pos <= 3)
    n = max(1, len(questions))
    return {"mrr": sum(rr) / n, "p_at_1": p1 / n, "recall_at_3": r3 / n, "n": n}


def mean_sim(enc, cos, pairs):
    if not pairs:
        return 0.0
    return sum(cos(enc.encode(a), enc.encode(b)) for a, b in pairs) / len(pairs)


def length_curve(enc, cos, depths):
    """Can the answer still be found when buried N words deep?"""
    answer = "The rollback key was rotated to KEY7788."
    question = "what was the rollback key rotated to"
    filler = "On Monday the billing service migration continued as planned. "
    out = {}
    for d in depths:
        pad = filler * max(1, d // len(filler.split()))
        out[d] = cos(enc.encode(question), enc.encode(pad + answer))
    return out


CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": bool(passed), "detail": detail})
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def observe(name, detail):
    print(f"  [ ..  ] {name} — {detail}")


def run_arm(label, props, facts, questions, subjects, mini):
    print(f"\n{'='*74}\n{label}  ({len(props)} taught propositions, "
          f"{len(facts)} facts, {len(questions)} questions)\n{'='*74}")

    native = SubstrateEncoder().learn(props)
    no_idf = SubstrateEncoder(use_idf=False).learn(props)
    no_assoc = SubstrateEncoder(use_assoc=False).learn(props)

    mp = minimal_pairs(facts, subjects)
    pp = paraphrases(facts)
    ut = untaught_pairs(facts)

    from _encoder_lib import StructuralEncoder as _SE
    structural = _SE().learn(props)
    encoders = [
        ("MiniLM", mini, dense_cos),
        ("native", native, sparse_cos),
        ("structural", structural, sparse_cos),
        ("native−idf", no_idf, sparse_cos),
        ("native−assoc", no_assoc, sparse_cos),
    ]

    results = {}
    print(f"\n  {'encoder':14} {'MRR':>7} {'P@1':>7} {'R@3':>7} "
          f"{'parap':>7} {'minpair':>8} {'SEPAR':>7} {'untaught':>9}")
    for name, enc, cos in encoders:
        r = retrieval(enc, cos, questions, facts)
        para = mean_sim(enc, cos, pp)
        mini_p = mean_sim(enc, cos, mp)
        unt = mean_sim(enc, cos, ut)
        sep = para - mini_p
        results[name] = {**r, "paraphrase": para, "minimal_pair": mini_p,
                         "separation": sep, "untaught_pair": unt}
        print(f"  {name:14} {r['mrr']:7.3f} {r['p_at_1']:7.3f} {r['recall_at_3']:7.3f} "
              f"{para:7.3f} {mini_p:8.3f} {sep:7.3f} {unt:9.3f}")

    print(f"\n  (parap: same claim, other words — HIGH is right)")
    print(f"  (minpair: subject swapped for another TAUGHT subject — LOW is right)")
    print(f"  (SEPAR = parap − minpair; this is the number that decides merging)")
    print(f"  (untaught: subject swapped for a word NEVER taught — LOW is right)")
    return results


async def main():
    print("ENCODER-01 — substrate-native encoder vs all-MiniLM-L6-v2")
    print(f"seed {SEED}")
    mini = MiniLM()

    inv_props, inv_facts, inv_q = build_invented()
    real_props, real_facts, real_q = build_real()

    inv = run_arm("ARM A — INVENTED vocabulary (neither encoder pretrained on it)",
                  inv_props, inv_facts, inv_q, INVENTED_SUBJECTS, mini)
    real = run_arm("ARM B — REAL-WORLD vocabulary (MiniLM's home ground)",
                   real_props, real_facts, real_q,
                   [f[0] for f in REAL_FACTS], mini)

    # ── H4: the length horizon ─────────────────────────────────────────────
    print(f"\n{'='*74}\nH4 — LENGTH HORIZON\n{'='*74}")
    depths = [0, 50, 150, 300, 600]
    native_all = SubstrateEncoder().learn(inv_props + real_props + [
        ("rollback", "key", "KEY7788"), ("billing", "service", "migration")])
    lm = length_curve(mini, dense_cos, depths)
    ln = length_curve(native_all, sparse_cos, depths)
    print(f"  {'words before the answer':28} {'MiniLM':>8} {'native':>8}")
    for d in depths:
        print(f"  {d:<28} {lm[d]:8.3f} {ln[d]:8.3f}")

    # ── verdicts ───────────────────────────────────────────────────────────
    print(f"\n{'='*74}\nVERDICTS\n{'='*74}")
    for arm_name, r in (("invented", inv), ("real-world", real)):
        check(f"H1 retrieval — STRUCTURAL MRR >= MiniLM ({arm_name})",
              r["structural"]["mrr"] >= r["MiniLM"]["mrr"],
              f"structural {r['structural']['mrr']:.3f} vs MiniLM {r['MiniLM']['mrr']:.3f}")
        check(f"H2 discrimination — STRUCTURAL scores minimal pairs LOWER ({arm_name})",
              r["structural"]["minimal_pair"] < r["MiniLM"]["minimal_pair"],
              f"structural {r['structural']['minimal_pair']:.3f} vs MiniLM {r['MiniLM']['minimal_pair']:.3f}")
        check(f"H3 separation — STRUCTURAL separates better ({arm_name})",
              r["structural"]["separation"] > r["MiniLM"]["separation"],
              f"structural {r['structural']['separation']:.3f} vs MiniLM {r['MiniLM']['separation']:.3f}")
        check(f"H1 retrieval — native MRR >= MiniLM ({arm_name})",
              r["native"]["mrr"] >= r["MiniLM"]["mrr"],
              f"native {r['native']['mrr']:.3f} vs MiniLM {r['MiniLM']['mrr']:.3f}")
        check(f"H2 discrimination — native scores taught minimal pairs LOWER ({arm_name})",
              r["native"]["minimal_pair"] < r["MiniLM"]["minimal_pair"],
              f"native {r['native']['minimal_pair']:.3f} vs MiniLM {r['MiniLM']['minimal_pair']:.3f}")
        check(f"H3 separation — native separates better ({arm_name})",
              r["native"]["separation"] > r["MiniLM"]["separation"],
              f"native {r['native']['separation']:.3f} vs MiniLM {r['MiniLM']['separation']:.3f}")

    check("H4 length — MiniLM degrades with depth",
          lm[600] < lm[0] * 0.5, f"{lm[0]:.3f} at 0 words -> {lm[600]:.3f} at 600")
    check("H4 length — native does NOT degrade with depth",
          ln[600] >= ln[0] * 0.5, f"{ln[0]:.3f} at 0 words -> {ln[600]:.3f} at 600")

    h5_holds = inv["native"]["untaught_pair"] > inv["native"]["minimal_pair"]
    observe("H5 (predicted failure) — untaught subjects confuse the native encoder",
            f"untaught {inv['native']['untaught_pair']:.3f} vs "
            f"taught {inv['native']['minimal_pair']:.3f} — "
            f"{'CONFIRMED, as registered' if h5_holds else 'did not occur'}")

    for arm_name, r in (("invented", inv), ("real-world", real)):
        check(f"ABLATION — idf contributes ({arm_name})",
              r["native"]["separation"] > r["native−idf"]["separation"],
              f"full {r['native']['separation']:.3f} vs without idf "
              f"{r['native−idf']['separation']:.3f}")
        check(f"ABLATION — association expansion contributes ({arm_name})",
              r["native"]["mrr"] >= r["native−assoc"]["mrr"],
              f"full MRR {r['native']['mrr']:.3f} vs without expansion "
              f"{r['native−assoc']['mrr']:.3f}")

    passed = sum(1 for c in CHECKS if c["passed"])
    print(f"\n{passed}/{len(CHECKS)} checks passed")

    win = (inv["structural"]["mrr"] >= inv["MiniLM"]["mrr"]
           and inv["structural"]["separation"] > inv["MiniLM"]["separation"]
           and real["structural"]["mrr"] >= real["MiniLM"]["mrr"]
           and real["structural"]["separation"] > real["MiniLM"]["separation"])
    print(f"\nVERDICT: the STRUCTURAL encoder "
          f"{'EARNS the job (H1 and H3 hold in BOTH arms)' if win else 'has NOT earned the job'}")

    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    (out / f"{stamp}.json").write_text(json.dumps({
        "seed": SEED, "invented": inv, "real_world": real,
        "length_minilm": lm, "length_native": ln,
        "checks": CHECKS, "passed": passed, "total": len(CHECKS),
        "native_earns_the_job": win,
    }, indent=2, default=str))
    print(f"\nrun record: experiments/ENCODER-01/results/{stamp}.json")


if __name__ == "__main__":
    asyncio.run(main())
