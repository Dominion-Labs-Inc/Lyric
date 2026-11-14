# ENCODER series — should a substrate-native encoder replace all-MiniLM-L6-v2?

**The question.** Every semantic judgement the substrate makes runs through a pretrained
sentence encoder: what gets recalled, whether an output answers a question, which concepts
are near each other — and which memories get **merged and destroyed**. That judgement comes
from weights trained on web text, not from anything the substrate was taught. On 2026-09-22
it merged "A zorbic filters brine." into "A marnic filters brine." and deleted one.

Ten experiments, each asking something different. Shared harness: `experiments/_encoder_lib.py`.

| # | Asks | Result |
|---|---|---|
| ENCODER-01 | Retrieval, separation, ablations, two vocabularies | 5/12 — native has **not** earned the job |
| ENCODER-02 | Does it improve as the substrate is taught? | 2/4 — separation rises, retrieval flat, never crosses |
| ENCODER-03 | Merge safety: which destroys fewer memories? | 1/3 — **neither is safe at the live threshold** |
| ENCODER-04 | A claim versus its denial | 2/6 — **both fail**; 71/80 denials merge-eligible |
| ENCODER-05 | Argument role: who did what to whom | 0/6 — **both are bags of words** |
| ENCODER-06 | Polysemy: one word, two taught senses | 4/5 — both separate senses; MiniLM margin wider |
| ENCODER-07 | Robustness to typing variation | 4/5 — **native wins**; MiniLM loses 11/80 claims to a typo |
| ENCODER-08 | Does an explicit unknown-term signal fix ENCODER-01's H5? | 2/5 — **no**, and it costs paraphrase |
| ENCODER-09 | Does new teaching damage old knowledge? | 5/5 — no catastrophic interference |
| ENCODER-10 | Cost and determinism in the acting path | 6/7 — **native wins**: 0.004 ms vs 4.445 ms, no cold start |
| ENCODER-11 | Noisy input, a dose curve to 50% corruption | 3 — at 35%: **native 0.613**, MiniLM 0.418, structural 0.263 |
| ENCODER-12 | Poisoned teaching, four kinds | 8 — structural separation holds: +0.832 clean → +0.831 at 50% |
| ENCODER-13 | Chaotic, interleaved, out-of-order teaching | 10 — **order-invariant and chaos-tolerant** |
| ENCODER-14 | Plausible falsehoods beside every truth | 9 — **native hallucinates 0.0%** over 29 trials |
| ENCODER-15 | Retrieval that cannot saturate: the word from its definition | 4/5 — **native 0.550 against MiniLM 0.283**, floor 0.037 |

**Decision: MiniLM stays — UNDER REVIEW as of 2026-11-14.** The native encoder loses on
discrimination and merge safety, which are the judgements that destroy data when wrong. That
decision was taken over 01…10 alone; 11…14 were run the same day and never entered this table,
and ENCODER-15 answers the retrieval question this README said was unanswerable.

**What has changed since.** ENCODER-15 built the measure the limitation below asks for -- one
correct answer per question, no subject handed over -- and on it a representation taught from
nothing but the substrate's own propositions retrieves at **0.550 against MiniLM's 0.283**, against
a word-overlap floor of 0.037. 11…14 add that native is the most robust under corrupted input, the
least poisonable, order-invariant, and the least hallucinating of the three. Discrimination and
merge safety are still MiniLM's, and still the reason the model is in place: re-measuring
ENCODER-03/04/05 at today's scale (584,753 admitted propositions, against a fraction of that in
September) is what decides whether the model comes out or is demoted to a first-pass filter.

**Three findings matter more than the comparison.**

1. **The live merge threshold destroys memories.** At 0.75 the incumbent false-merges 10% of
   distinct claims. At 0.90 it false-merges 0% and still catches 93.3% of true duplicates
   (ENCODER-03).
2. **Neither encoder can tell a claim from its denial** (ENCODER-04, 0.851 / 0.987 against a
   0.75 gate).
3. **Neither encoder represents argument role** (ENCODER-05, 0.980 / 1.000 for A-verb-B against
   B-verb-A).

Together these say the merge gate **cannot be decided by a vector**. Polarity and structure have
to come from the reader, which this substrate has and the merge path does not consult — the same
shape as the `about_the_same_thing` guard that recall already uses and the write path lacked.

**Where the native encoder is genuinely better:** 1115× cheaper per encode, no 6-second weight
load, exactly reproducible across instances, no interference as teaching accumulates, and stable
under the typing variation that costs MiniLM 11 of 80 claims. That is a cheap first-pass filter,
not a semantic judge.

**Known limitation of this series.** The retrieval task saturates: MRR is 0.750 for both encoders
at every corpus size, because each subject has two facts and both contain the subject, so rank 1
or 2 is forced. ENCODER-02's H1 and H3 are therefore **not testable** with this task and should
not be read as evidence either way. A retrieval measure with one correct answer per question is
needed before the scale question can be answered.

**Run**

```
./venv_lyric/bin/python3 experiments/ENCODER-01/experiment.py     # and -02 … -10
```

Every run is saved under each experiment's `results/`, never overwritten.
