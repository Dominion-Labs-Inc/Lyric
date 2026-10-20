# SENSES-01: a bound on the sense combinations of each grouping, against the reader with none

**Superseded (2026-10-20).** The bound was a patch: it cut what multiplied, never the multiplying. On main
it let the primes sentence's whole read finish and uncovered the rest of the cause (the 252 stretches of a
read in parts, each multiplying its slots' bracketings). The reader now keeps each word's senses together and
the listener chooses over the structure (`experiments/PACKED-01`); `SENSES_KEPT` and `LYRIC_SENSES` are gone,
and this experiment no longer runs. Kept for its records.

**Claim.** Keeping, for each grouping of the words, the N sense combinations that suppose least and were met most
often lets every sentence finish reading and changes no reading the listener chooses.

**Why.** The reader builds every reading whole, each word's every sense crossed with every other's, and keeps few.
On main a long sentence never finished: "A prime number is a natural number greater than 1 that has no divisors other
than 1 and itself." built no whole reading in ten minutes, one slot holding 25,164 fillings of 36 groupings, all
supposing the same; "The argument key is a function that is applied to each element." built 78,132 readings and
handed the listener 3,360 (lab notebook 2026-10-19 (23)). The fix agreed (handoff §0): first a measured bound, so runs
finish; then senses chosen over the sentence's structure, never multiplied out.

**What is bounded** (`derived_reader._senses_kept`, `SENSES_KEPT`, `LYRIC_SENSES=N`; 0, every one). A grouping is
how a reading or a filling goes together whichever thing each word names (`_grouping`: each frame and phrase with slots
as itself, each word and phrase of words as its words); a sense combination is what its words name (`_senses_of`), so
"Light" and "light" held apart for one thing are one. Of each grouping, the N combinations the listener would weigh
highest on what is at hand, its evidence added as `meant` adds it: how often the senses were met (`_senses_met`,
`ln(1 + uses)`), how probable the structure is (`_derivation_of`), and what the fit is worth (`listening_worths`);
first, whether it reaches the listener at all (read loosely, words taken as new names). And the one that supposes
least, besides: a reading reaches the listener when it supposes least or says what one that does says in its words
(`_read_pieces`), and the least of each part makes the least of the whole. What memory knows of each fact is not at
hand: it is asked once readings are made. Ties by the senses' names. Applied to what may stand in a slot, to the
phrases and adjuncts over each run of words, and to the whole readings, only where a sentence is read
(`_read_pieces`). Learning reads strictly and repairs read with their own charts: neither is bounded.

**What it measures** (read only, from the store's own views, warmed from memory). Every sentence and question of
UNDERSTANDS-PROSE-01 (read in parts, as a conversation reads them) and every lesson sentence (`ListeningSource`, as
the listener's counts are made), each read with no bound and with each N asked for, in one load. Of each: the readings
each utterance hands the listener, and its parts' where read in parts; the one the listener takes (`heard`, memory at
hand, no conversation before it); the seconds. For each N: how many sentences read to the same readings and the same
choice as with no bound, lessons read as taught, readings handed to the listener, seconds, and every sentence whose
choice changed (`_changed.json`). A sentence that does not finish with no bound within the run's own limit
(`--limit`, 900 s; the probe's, never the reader's) is compared on nothing, and still read and timed with each N.
**No bar:** it measures. Then it checks nothing was written.

**Run** (from the Lyric folder; starts no substrate; about 5 minutes to load on main, then every sentence read once
with no bound and once with each N):

```
POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/SENSES-01/experiment.py --senses 4,8,16
```

`--prose-only` reads the prose alone; `--resume experiments/SENSES-01/work/<stamp>_sentences.jsonl` goes on after the
last sentence a stopped run wrote.

**Results:** `results/<UTC timestamp>.json` and `.md`, and `_changed.json` (every choice a bound changed), named by
when the reading began; `results/run.log`. Each sentence as read with no bound, and with each bound its choice,
seconds and readings where they differ, is written as it is read to `work/<stamp>_sentences.jsonl`: the run's
working file, kept out of git (`experiments/*/work/`; about 9 MB for the sandbox).

**Runs:**

| Run | Store | Version | Bounds | Prose: same choice of 70 | Lessons: same choice | Lessons read as taught |
|---|---|---|---|---|---|---|
| `20261019T203029Z` | sandbox, prose only | first: held words, not senses, counted; supposing least first | 2, 4, 8 | 65, 68, 70 | | |
| `20261019T203950Z` (stopped) | sandbox | first | 4, 8, 16 | 68, 70, 70 | 1,933 of 1,933 each | 1,860 of 1,933 each |
| `20261019T205445Z` | sandbox, prose only | second: senses counted; supposing least first | 2, 4, 8 | 67, 68, 70 | | |
| `20261019T210527Z` | sandbox, prose only | third: weighed as the listener weighs, the least kept besides | 1, 2, 4, 8 | 69, 70, 70, 70 | | |
| `20261019T212510Z` | sandbox | final: the third, the least kept besides the N and never in their place | 1, 2, 4, 8 | 68, 70, 70, 70 | 3,036, 3,053, 3,054, 3,054 of 3,054 | 2,913 with no bound; 2,919, 2,912, 2,913, 2,913 |
| `20261019T214648Z` | sandbox, prose only | final, its working file moved to `work/` | 4 | 70 | | |

On the sandbox the bound saves nothing: it never explodes (all 70 prose sentences and questions read in 70 to 100 s
with no bound or with one). It shows what the bound changes: at 4, nothing; readings handed to the listener on the
lessons 24,372 with no bound, 9,136 at 4.
