# READ-LONG-01: how long the reader takes on long sentences with no punctuation

**Why.** Phase 0 of `docs/research/ENGLISH_CURRICULUM.md` sets a bar before the words are taught: a 60-word sentence
with no punctuation reads, or is found not to read, in under 5 seconds. SPEECH-06 found 44- to 55-word heard
sentences that did not finish reading in over 70 minutes.

**What it measures** (`measure.py`, the sandbox's language as taught, its store only read): the time `read_text`
takes on a sentence cut to 8, 12, 16, 20, 25, 30, 40 and 60 words, and whether it reads whole, on two kinds of text:
- LibriSpeech test-clean transcripts (words the sandbox may not hold);
- run-on speech of words the lessons teach: taught statements with their marks and capitals taken away, one after
  another (`--run-on`).

**Run:** `./venv_lyric/bin/python3 experiments/READ-LONG-01/measure.py [--run-on]`

**Runs:**

- **2026-10-05, first measurement** (`measure.log`, `measure_run_on.log`), while english_01–31 were being taught into
  main on the same machine:

  | words | transcripts | run-on (1) | run-on (2) |
  |---|---|---|---|
  | 20 | 0.05 s, 0.52 s | 0.38 s | 0.07 s |
  | 40 | 0.18 s, 1.32 s | 2.07 s | 0.20 s |
  | 60 | 0.46 s, 3.04 s | 6.05 s | 0.45 s |

  - Reading is bounded: time grows about as the square of the length, and every length finished. One of the six
    60-word sentences took over 5 seconds, measured under load.
  - **No run-on text read whole, at any length.** "a robin is a bird a sparrow is a bird ..." is four statements, and
    the reader takes speech with no marks as one sentence: it does not find where one statement ends and the next
    begins. SPEECH-06's 70 minutes were spent finding those ends by reading every stretch of the sentence
    (`read_text(parts=True)`, about 4 minutes a sentence).
