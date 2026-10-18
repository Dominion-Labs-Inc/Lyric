# STRUCTURE-03: more hand-analysed English, and the counted word groups, for the structure reader

**Claim.** More hand-analysed English raises the structure reader, and the counted word groups beside it raise it
further.

**Why.** Doubling the hand-analysed text the reader learns from raised it 3.2 points of UAS (lab notebook 2026-10-17
(13)); self-taught text raised it little (SELF-TEACH-01, lab notebook 2026-10-18). Universal Dependencies has more
English analysed by hand than EWT: GUM, LinES, ParTUT, Atis and ESL Spoken. This measures what each brings, as the
teaching pass takes it (`TreebankSource.of`, `TREEBANKS`: each treebank's training and development parts, under its
own source).

**What it measures** (files only, no store): the reader learned from EWT alone; with Atis and ESL Spoken (CC BY-SA, as
EWT); with GUM; with every treebank; and with every treebank and GROUPS-01's word groups. On EWT dev, PUD and GUM's
test part, which none learns from: classes, UAS, LAS.

| Bars (from the scratch measurements that came first: EWT dev +1.9, GUM test +3.8 with every treebank) | |
|---|---|
| Every treebank | UAS at least 1.5 points higher on EWT dev, 3 on GUM's test |
| The groups beside every treebank | UAS higher on all three |

Licences: EWT, Atis and ESL Spoken CC BY-SA 4.0; GUM, LinES and ParTUT CC BY-NC-SA 4.0 (non-commercial).

**Run** (from the Lyric folder; about an hour on two cores):

```
PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-03/experiment.py
```

with `test_data/syntax/` holding `UD_English-EWT`, `UD_English-PUD` and each treebank of `TREEBANKS` (`--data DIR`),
and `data/word_groups/` GROUPS-01's tables (`--groups DIR`).

**Results:** `results/<UTC timestamp>.json` and `.md`.
