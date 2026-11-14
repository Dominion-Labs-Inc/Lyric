# ENCODER-15 — find the word from its definition: a measure that cannot saturate

**The question.** Whether a substrate-native encoder can replace `all-MiniLM-L6-v2` was settled
"MiniLM stays" on 2026-09-22 over ENCODER-01…10. That verdict cannot be trusted on retrieval,
and the series says so itself:

> The retrieval task saturates: MRR is 0.750 for both encoders at every corpus size, because each
> subject has two facts and both contain the subject, so rank 1 or 2 is forced. ENCODER-02's H1 and
> H3 are therefore **not testable** with this task. A retrieval measure with one correct answer per
> question is needed before the scale question can be answered.

**Why six facts per subject would not have fixed it.** The saturation is intrinsic, not a matter of
how many distractors there are: every question names its subject and every answer contains it, so
finding the subject is most of the job and a subject-only matcher still lands in the top k. A first
version of this experiment tried exactly that and found the store holds **one** word with six
distinct relations — WordNet is 440,058 `defined_with` edges of 586,660, so relation diversity per
word barely exists.

**The task.** Asked the other way round, it is what a dictionary does: here is a definition, which
word is it? Nothing in the question names the answer, there is one right answer, and it competes
against 299 others, so the floor is 1/300.

| | question and fact share words? | what it reads |
|---|---|---|
| TOGETHER | yes, all six defining terms | weighting only — **string overlap scores 1.000**, so this measures nothing about an encoder |
| HELD OUT | no, three terms each side | relating terms taught to stand together — string overlap falls to **0.037** |

H1, H2 and H4 are judged on HELD OUT alone. TOGETHER is kept because proving the confound is worth
a column; a score there is not evidence.

## Result (2026-11-14, `lyric_db`, 584,753 admitted propositions)

| encoder | HELD OUT p@1 | TOGETHER p@1 |
|---|---:|---:|
| word-overlap floor | 0.037 | 1.000 |
| MiniLM | 0.283 | 1.000 |
| **native** (`SubstrateEncoder`) | **0.550** | — |
| structural (`StructuralEncoder`) | 0.133 | — |

**Native retrieves nearly twice as well as the pretrained model** on a measure that cannot saturate,
taught from nothing but what the substrate was told.

**Scale, honestly.** The task's own 1,800 propositions must be taught — an encoder cannot encode
words it was never told — so at 3,800 taught the task is 47% of everything the encoder knows and at
201,800 it is 0.9%. Native reads 0.807 → 0.763 → 0.550 across those volumes: the early figure is
flattered by the corpus being mostly the task, and only the largest volume is a fair reading.
Structural rises 0.023 → 0.053 → 0.133 as it is taught more. H3 is therefore asked of each encoder
separately, and **native fails it**: asked as `any`, it passed on structural rising while native
fell, which is not the hypothesis. 4/5 checks pass.

**What this does not settle.** ENCODER-01's verdict rested on **discrimination and merge safety**,
not retrieval, and this measures neither. ENCODER-03/04/05 found that *neither* encoder is safe at
the live merge threshold, that neither tells a claim from its denial, and that neither represents
argument role. Those stand until re-measured at today's scale. Teaching `StructuralEncoder` on
200,000 propositions costs 878 s, which is also unmeasured against the 6 s weight load it replaces.

**Run**

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/ENCODER-15/experiment.py
```

Every run is saved under `results/`, never overwritten.
