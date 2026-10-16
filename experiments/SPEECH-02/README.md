# SPEECH-02: the lessons' own words, taught by hearing them said

**Claim.** The words the English lessons are written in can be taught to the substrate by hearing them said. Each
lesson is kept as a hearing in the shared mind and read back exactly. Said by people it was never taught by, a word
it names firmly is the word said.

**Why.** SPEECH-01 taught eight digits from one speaker. Lyric's reader holds about 900 words from the 30 lessons,
and a heard sentence reaches the reader only when every word in it was heard. Before spoken words are taught to the
main model, the teaching itself has to be right: nothing refused that was said, nothing kept in the wrong place,
and every lesson read back exactly. How well taught words are then heard is measured beside it.

**Recordings.** Fetched once into `data/speech/` (ignored by git; datasets are never pushed).
- **Multilingual Spoken Words Corpus** (MLCommons, CC BY 4.0): one-second clips of single words cut from Common
  Voice, split by speaker. `fetch_mswc.py` keeps up to 10 speakers per lesson word from dev (to teach) and from test
  (to hear), reading each 300 MB shard as it streams.
- **LibriSpeech** (CC BY 4.0), word times from the Montreal Forced Aligner (`gilkeyio/librispeech-alignments`): for
  the lesson words MSWC does not keep, words shorter than three letters and contractions ("is", "a", "of", "isn't").
  `cut_librispeech.py` cuts them from dev-clean (to teach) and test-clean (to hear).

Both corpora's word boundaries were cut by a machine aligner. No model runs in Lyric; the labels act as a teacher's.

**What it checks.**

| | Property |
|---|---|
| A | every example is heard through `learn_word` and kept as a hearing of its own, in the shared mind, tagged a spoken word, saying which word it taught; its trace keeps exactly what was measured; no real word said is refused; the word taught is one the reader holds; the rows teaching wrote are listed |
| B | a fresh faculty reads every taught word back, every example, exactly |
| C | the same words said by untaught speakers, heard by the faculty's own `sense` (nothing kept): a firm reading (support at least 0.5) is right; named, named wrongly and unnamed are measured |
| D | everything the run wrote is removed from the sandbox; the main model's store is untouched |

**Run** (from the Lyric folder; sandbox):

```
./venv_lyric/bin/python3 experiments/SPEECH-02/fetch_mswc.py
./venv_lyric/bin/python3 experiments/SPEECH-02/cut_librispeech.py
./venv_lyric/bin/python3 experiments/SPEECH-02/experiment.py [--words 100] [--examples 3] [--heard 2]
```

**Results:** `results/<UTC timestamp>.json`, `.md` and transcript.

**First run (`20261003T123729Z`, 8/12): 100 words, 3 speakers each to teach, 2 untaught to hear.**
- **Taught right:** 299 lessons, each a hearing in the shared mind saying its word, every trace exact, every word
  one the reader holds, all 299 read back exactly by a fresh faculty.
- **One real word refused:** "of" from LibriSpeech speaker 1993, "nothing rose above the room". That speaker reads
  quietly (the sentence about -44 dB), and the harness put every clip in one -60 dB room, so the word stood 9 dB
  above it. The ear does not hear loudness as what was said, so each clip is now brought to one level (-12 dB
  peak) before the room goes around it. The error was the harness's.
- **Teaching writes far more than lessons, by design.** 300 lessons wrote 1,070–1,170 concepts, about 4,500
  relations and 4,500 beliefs, 1,500–1,700 aliases and 3,900 evidence rows. A lesson is a hearing like any other,
  and a hearing's measurements go into the graph as observations, each pitch and level a quantity of its own.
- **The cleanup left 564 concepts and their aliases, evidence and identity links behind.** It removed only rows
  carrying the run's mark, which a hearing's measurements do not carry. It now removes every row written after the
  run began, table by table (no other writer runs in the sandbox), and the first run's leftovers were removed by
  its own start and end times.
- **Hearing untaught speakers:** 4 of 200 named right, 6 wrongly (one firmly: "blue" as "ball"), 190 not named.

**Second run (`20261003T125738Z`, 10/12), with both fixes.** Every teaching check passes: 300 of 300 taught, none
refused, all read back exactly, everything the run wrote removed, main untouched. Hearing: 4 of 200 right, 4 wrong,
one of them firm ("twelve" as "a"), 192 not named.

**Why so few are named (offline, `offline_naming.py`, `offline_features.py`).** The ear's measurements and
distance, on the same clips, with nothing stored:

| Teaching speakers a word | The right word is nearest | In the nearest five | Named by the ratio test |
|---|---|---|---|
| 3 | 21.7% | 45.3% | 4 of 300 |
| 5 | 19.3% | 48.7% | 4 of 300 |
| 10 | 24.3% | 53.0% | 2 of 300 |

Chance is 1%. The ratio test is right to refuse: the measurements barely carry from one speaker to another. None of
four classical alternatives does better (cepstral variance normalisation, with acceleration, cepstra alone, a
lifter: 15–19% nearest at 10 speakers). A word's distance taken as the mean of its 3 nearest examples does: 29.0%
nearest, 61.7% in the nearest five. The ear was built and measured with the same speaker teaching and speaking
(SPEECH-01, FSDD digits).

**More speakers, k nearest, and frequency warping (offline, `offline_speakers.py`, `offline_vtln.py`).** MSWC's
train split adds up to 50 speakers a word (60 with dev). 100 words, 3 untaught speakers each:

| Teaching speakers a word | Decided by | The right word is nearest | In the nearest five |
|---|---|---|---|
| 10 | nearest example | 22.3% | 49.0% |
| 20 | nearest example | 27.7% | 54.7% |
| 20 | 3 nearest | 30.0% | 63.0% |
| 20 | 3 nearest, best of 7 frequency warps | 38.3% | 64.7% |
| 60 | 3 nearest | 37.7% | 69.0% |
| 60 | 5 nearest | 38.3% | 70.0% |

Frequency warping (vocal tract length normalisation; Lee and Rose 1996: the heard word measured on a frequency axis
stretched by 0.88 to 1.12, the best fit kept) gives what 40 more speakers give. Neither brings words said by people
the ear was not taught by within reach: whole-word comparison tops out near 40% on 100 words, and the ratio test,
which names only a clear winner, names 1–2%. Short words cut from running speech add a hazard: the decoder split
the last 80 ms of "twelve" off and named it "a" firmly (`offline_firm.py`: with 10 speakers a word, 18 spans of
about 1,000 heard words are named at all, one firmly, so there is not yet enough to measure a length floor).

**What it means.** Teaching spoken words is correct: every lesson is kept where it belongs and read back exactly.
Hearing them is not: the ear knows a word from the voices that taught it (SPEECH-01, 64–77% for a taught speaker),
not from voices it never heard. The research step next is to hear the sounds words are made of rather than whole
words: phones taught from LibriSpeech's aligned phonemes (40 speakers in dev-clean), and a word matched as its
sequence of phones from a pronouncing dictionary. Nothing in that is learned beyond what is taught; it is the
same comparison of what was heard with what was taught, at the level of sounds.
