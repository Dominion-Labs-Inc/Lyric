# SPLITS-01: where the words split asked of the chart, not tried

**Claim.** The reader asking the chart where the words split between a form's slots, and the grammar making only the
combinations it keeps, read every sentence exactly as before, in less time.

**Why.** Reading a page looked up stayed at full CPU: RESEARCH-WRITE-01 and TEACH-AND-DO-01 stopped at their
research step, the stack in `_slot_fillings` and `_phrase_fillings`, and in `grammar.chart`'s `_combine` (lab
notebook 2026-10-22 (36), error 7). Measured on lyric_dev (2026-10-23, `reader_profile.py` in the lab notebook entry),
the second paragraph of Wikipedia's Photosynthesis lead, read as a looked-up page is read, took 24 s; the reader's
products built only 1,280 combinations, but its coverings, every way each form could split each run of words between
its slots, numbered 1,560,913, and 786 of them had something standing in every slot. Every other covering was made
and thrown away at its first slot nothing stands in. Half the paragraph's time went to making them.

**What changed** (each keeps what is read):
- `derived_reader._coverings`: a slot's span is asked of the chart (`_slot_fillings`) as a covering reaches it, and
  only where the rest of the form can still cover the rest of the words (`row`); a covering with a slot nothing stands
  in is never made. The chart is asked of the same spans in the same order as when every covering was made and each
  slot asked in turn. `_chunkings` (spans only) is the same walk.
- `_Chart.span`: the chart keeps each run of words by a number, found once for each place in the pieces being read,
  where the run's pieces were looked up afresh at each place a covering reached (1,969,634 times for that
  paragraph).
- `Pattern.key`, `Lexical.key`, `Link.key`, `Phrase.key`: made once for each construction (1,507,624 times for that
  paragraph).
- `grammar.Sign.binding`: the grammar makes a combination's pieces, its parts' pieces with their variables bound,
  only once its chart keeps it.

**What it measures** (read only, from the store's own views, warmed from memory). Every paragraph of the
Photosynthesis lead (`photosynthesis_lead.txt`, Wikipedia, CC BY-SA 4.0, retrieved 2026-10-23; read as a page looked
up is read), every sentence and question of UNDERSTANDS-PROSE-01 and of UNDERSTANDS-PROSE-02's half fixed against
(read in parts, as a conversation reads them; the half kept unseen is not read), and every lesson sentence
(`ListeningSource`), each read both ways in one load, in turns (the first way alternates):
- now: `read_text` as it is;
- before: inside `as_before`, the reader and the grammar as they were: the old coverings (`coverings_before`), each run
  kept by its pieces (`_span`), each key made when asked, each combination's pieces made as it is made;

and compared whole: every utterance and every reading, equal and written alike (`==` and `repr`). Each way starts from
what the grammar had heard before the sentence: a word the grammar reads as a name is heard as one from then on, so a
sentence read twice can read otherwise the second time ("When needing to use this stored energy, ..." did, the reader
aside). Each lesson is also read strictly, as the learner reads a taught pair (`readings_of`), both ways. Then the
listener's choice for each utterance, the seconds each way, and that nothing was written to the store. **No bar:** it
measures.

**Run** (from the Lyric folder; starts no substrate):

```
POSTGRES_DATABASE=lyric_dev POSTGRES_PORT=5433 POSTGRES_USER=stefan PYTHONPATH="$PWD" \
    ./venv_lyric/bin/python3 experiments/SPLITS-01/experiment.py
```

`--prose-only` reads the page and the prose alone.

**Results:** `results/<UTC timestamp>.json` and `.md`, `results/run.log`; each sentence as read, in
`work/<stamp>_sentences.jsonl` (the run's working file, kept out of git).

**Runs:**

| Run | Store | Page: same, seconds now / before | Prose: same, seconds now / before | Lessons: same, strictly same, seconds now / before | Nothing written |
|---|---|---|---|---|---|
| `20261023T121713Z` | lyric_dev | 5 of 5; 25.4 s / 72.3 s | 523 of 523; 348.7 s / 1,126.7 s | 3,054 of 3,054; 3,054; 52.7 s / 70.4 s | yes |

On lyric_dev the slowest paragraph of the page reads in 7.1 s (25.9 s before) and the slowest prose sentence in 26.0 s
(95.1 s before: "Four out of the five justices voted to convict Bolsonaro on all charges, ..."). Lessons read as taught
2,913 of 3,054, as PACKED-01 on the sandbox. Run before it, the coverings change alone (stopped at 175 of 528 to
measure all four together, no record): 175 of 175 the same.

**Not yet run:** main (`lyric_db`), where the long sentences of UNDERSTANDS-PROSE-02 stalled (text 44's third,
410.7 s on 2026-10-22). `--prose-only` there reads them both ways:

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/SPLITS-01/experiment.py --prose-only
```
