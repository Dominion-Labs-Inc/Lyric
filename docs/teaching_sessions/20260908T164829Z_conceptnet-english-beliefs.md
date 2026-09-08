# Teaching session — conceptnet-english-beliefs
*2026-09-08T16:48:29.171314+00:00 · ConceptNet 5.7.0 (offline) · belief backfill (batched + flushed) · model-free (no LLM)*

## Taught
- English IsA propositions: **221,203** → one Bayesian belief each (`observe_claim`, source `taught`)
- Batch size: 5,000 · flushed per batch · Elapsed: 50.6s

## Beliefs: prior → after

| Store | Prior | After | Δ |
|---|--:|--:|--:|
| Beliefs (`general`) | 28,588 | 191,019 | +162,431 |
| Beliefs (all) | 33,114 | 195,646 | +162,532 |

Concepts for these facts were already admitted (256k in the store); this session establishes the graded belief over each. Per-word lexicon enrichment was intentionally skipped here (it was the bottleneck of the prior single-batch run) and can be run separately.

---
