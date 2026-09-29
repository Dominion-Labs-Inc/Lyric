#!/usr/bin/env python3
"""ENCODER-10 — cost and determinism: can this run in the acting path?

Recall happens inside reasoning, inside merge decisions, inside every memory
write. An encoder that is correct and slow is not usable, and one that is fast
and non-deterministic cannot be audited -- the substrate's governance rests on
the same knowledge and the same situation producing the same answer.

  H1  Encoding is deterministic: the same text encodes identically twice, and
      similarity is reproducible across encoder instances built from the same
      teaching.
  H2  Per-encode cost is under a millisecond at the corpus sizes measured.
  H3  There is no cold-start penalty for the native encoder -- no weights to
      load. MiniLM's first call pays for the model.
  H4  Cost grows sub-linearly in the amount taught (it must not become the
      bottleneck as the substrate learns).
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _encoder_lib import (MiniLM, Run, SubstrateEncoder, invented_corpus,
                          sparse_cos, dense_cos)


def timed(fn, n=200):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000.0        # ms per call


def main():
    run = Run("ENCODER-10 — cost and determinism in the acting path", [
        "H1 encoding is deterministic and reproducible across instances",
        "H2 per-encode cost is under a millisecond",
        "H3 the native encoder has no cold-start weight load",
        "H4 cost grows sub-linearly in the amount taught",
    ])
    props, facts, _, _ = invented_corpus(n_subjects=50)
    probe = facts[0]

    # cold start
    t0 = time.perf_counter()
    nat = SubstrateEncoder().learn(props)
    native_build_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    mini = MiniLM()
    _ = mini.encode("warm the model")
    minilm_cold_ms = (time.perf_counter() - t0) * 1000

    run.data["native_build_ms"] = native_build_ms
    run.data["minilm_cold_ms"] = minilm_cold_ms
    run.table("cold start", [
        f"native  build from {len(props)} taught propositions : {native_build_ms:8.1f} ms",
        f"MiniLM  load weights + first encode                 : {minilm_cold_ms:8.1f} ms",
    ])

    # determinism
    a1, a2 = nat.encode(probe), nat.encode(probe)
    nat2 = SubstrateEncoder().learn(props)
    same_instance = (a1 == a2)
    across = abs(sparse_cos(nat.encode(probe), nat.encode(facts[1]))
                 - sparse_cos(nat2.encode(probe), nat2.encode(facts[1]))) < 1e-12
    m1 = mini.encode(probe)
    m2 = mini.encode(probe + "")
    mini_det = all(abs(x - y) < 1e-9 for x, y in zip(m1, m2))
    run.check("H1 native encodes identically twice", same_instance, "exact match")
    run.check("H1b two native encoders taught the same thing agree exactly",
              across, "identical similarity to 1e-12")
    run.check("H1c MiniLM is deterministic for identical input", mini_det, "exact match")

    # per-call cost, native cache-free vs MiniLM UNCACHED
    nat_ms = timed(lambda: nat.encode(probe))
    raw = mini.s
    mini_ms = timed(lambda: raw.generate_embedding(probe), n=50)
    run.data["native_encode_ms"] = nat_ms
    run.data["minilm_encode_ms"] = mini_ms
    run.table("per-encode cost", [
        f"native : {nat_ms:7.3f} ms",
        f"MiniLM : {mini_ms:7.3f} ms   ({mini_ms/max(nat_ms,1e-9):.1f}x)",
    ])
    run.check("H2 native encode is under a millisecond", nat_ms < 1.0, f"{nat_ms:.3f} ms")
    run.check("H2b MiniLM encode is under a millisecond", mini_ms < 1.0, f"{mini_ms:.3f} ms")
    run.check("H3 native has no cold-start weight load",
              native_build_ms < minilm_cold_ms,
              f"native build {native_build_ms:.1f} ms vs MiniLM cold {minilm_cold_ms:.1f} ms")

    # scaling
    scale_rows, scaling = [], {}
    for n in (10, 25, 50):
        p, f, _, _ = invented_corpus(n_subjects=n)
        e = SubstrateEncoder().learn(p)
        ms = timed(lambda: e.encode(f[0]))
        scaling[n] = {"props": len(p), "encode_ms": ms}
        scale_rows.append(f"{len(p):>4} taught propositions -> {ms:7.3f} ms per encode")
    run.table("native cost by amount taught", scale_rows)
    run.data["scaling"] = scaling
    growth = scaling[50]["encode_ms"] / max(scaling[10]["encode_ms"], 1e-9)
    prop_growth = scaling[50]["props"] / scaling[10]["props"]
    run.check("H4 cost grows sub-linearly in the amount taught",
              growth < prop_growth,
              f"{prop_growth:.1f}x more taught -> {growth:.1f}x cost")

    run.finish(f"native {nat_ms:.3f} ms/encode, no weight load; "
               f"MiniLM {mini_ms:.3f} ms/encode, {minilm_cold_ms:.0f} ms cold start")


if __name__ == "__main__":
    main()
