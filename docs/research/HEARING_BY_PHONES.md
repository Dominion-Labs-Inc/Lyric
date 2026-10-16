# Hearing words said by anyone

Research note, 2026-10-03. It follows SPEECH-02, which taught the lessons' own words by hearing and measured how
they are heard from speakers the ear was never taught by. Nothing here is built into the substrate yet.

## 1. The problem, as measured

The ear knows a spoken word by comparing what it hears with examples it was taught, whole word against whole word
(`core/perception/speech.py`). SPEECH-01 measured it with one speaker teaching and speaking: 64–77% of words named,
under 1% wrongly.

SPEECH-02 (`experiments/SPEECH-02/`) taught the lessons' 100 most-used words from the Multilingual Spoken Words
Corpus and heard them from other speakers:

| | Result |
|---|---|
| Teaching (300 lessons) | correct: each a hearing in the shared mind with its word, read back exactly, none refused |
| Words named, from untaught speakers | 4 of 200 |
| The right word is the nearest, 3 to 10 teaching speakers | 20–24% |
| With 60 speakers a word and the 5 nearest examples | 38% |
| With frequency warping (20 speakers, 3 nearest) | 38% |

Chance is 1%. The ratio test, which names a word only when it clearly wins, is right to refuse. A whole word does
not carry from one voice to another often enough, and four classical changes to what is measured do no better.

## 2. What is known

- **Whole-word templates across speakers** need many speakers a word, clustered, and a decision by the nearest few
  (Rabiner, Levinson, Rosenberg and Wilpon 1979): about 90% on 54 words over the telephone, with 100 speakers a
  word. Every word needs its own hundred speakers.
- **Words are made of a few dozen sounds.** A language's words are sequences of about 40 phones, and every speaker
  says each phone thousands of times. A pronouncing dictionary gives each word's phones (the CMU Pronouncing
  Dictionary: 123,455 words; 900 of the lessons' 904).
- **A frame is known by its neighbours.** A phone is told from another by how it is come to and left; a frame
  measured with the frames around it carries that (Furui 1986).
- **Nearest neighbours** decide a class from examples with nothing trained (Fix and Hodges 1951).
- **A stretch is fitted to a sequence of sounds** by the best way of giving each sound some of the frames, in order
  (Viterbi 1967; the same one-pass search the ear's connected-word decoder already uses, after Vintsyuk, Bridle
  and Ney).
- **A speaker's vocal tract length** moves every resonance by about one factor; measuring on a stretched frequency
  axis and keeping the best fit undoes it (Lee and Rose 1996).
- **RASTA** removes what stays still in each band over time (Hermansky and Morgan 1994).

## 3. What the substrate already has

| Needed | In Lyric |
|---|---|
| Speech-band energies every 10 ms, the channel removed | `speech._cepstrum`, `_running_mean` |
| Where speech is in a recording | `hearing.segment`, `speech._extent` |
| One-pass decoding of a stretch into taught units, with pauses | `speech._decode` |
| A lesson as a hearing, its trace keeping what was measured | `coord.learn_word`, `PerceptionFaculty.hold_lesson` |
| Words that sound alike handed to the listener to choose among | `speech._alike`, `derived_reader.heard_which` |
| A heard sentence read and answered as typed text is | `live.py` to `handle_user_request` |
| A teaching pipeline that takes a lexicon as a source | `TeachingPass`, `teaching_sources.py` |

## 4. Measured so far (offline, `experiments/SPEECH-03/`)

Phones taught from LibriSpeech's aligned phoneme times (dev-clean, 40 speakers), heard from test-clean (40 other
speakers). Nothing is trained: a heard frame is compared with the taught frames, and its 25 nearest say which phone
it sounds like.

**Frames given their phone** (40 classes; every seventh frame of 292 utterances):

| A frame measured as | Right |
|---|---|
| 12 cepstra and their change (the ear's measure for words) | 31.3% |
| the same, with the frames 40 ms either side | 41.7% |
| 26 band energies and their change | 34.7% |
| the same, with the frames 40 ms either side | 44.9% |
| the same, 60 ms either side | 45.2% |
| the same, 60 ms either side, three times the taught frames (566,000) | 48.3–48.6% |
| divided by each measure's spread; acceleration; 80–120 ms either side | no better |

**Words** (which of the lessons' 100 most-used words fits a stretch best, by its phones in the dictionary):

| Heard | Taught from | The word said, or one said the same, fits best | In the best five |
|---|---|---|---|
| words cut from untaught speakers' sentences (246) | 40 speakers | 54.9% | 80.1% |
| the same | 73 speakers (with dev-other) | 56.1% | 78.5% |
| MSWC words said alone, other microphones (300) | 40 speakers | 21.0% | 44.3% |
| the same | 73 speakers | 21.7% | 46.7% |

SPEECH-03 `20261003T155215Z` and `20261003T155918Z`, 3/3 each. None of these words was taught as a word: only the
40 sounds were. For comparison, whole-word matching reached 38% on the MSWC words with 60 speakers of each word.
More voices change little at this size. "two" heard as "to" counts as heard: they are said the same, and which was
meant is the listener's to choose.

**With each phone lasting at least three frames** (none in the alignments is shorter): words cut from sentences
61.8% (best five 85.0%); MSWC words alone 22.0% (`20261003T164034Z`).

**Whole sentences, no boundaries given** (60 utterances, 1,180 words, 1,306 candidate words, `offline_connected.py`):
34.2% of the words right at best, with each word entered at a cost of its share of real text. Most errors are words
taken for others that sound near them ("the go like so more face" for "the dull light fell more faintly").

**Taught again from words heard through people's microphones** (`offline_mswc.py`): MSWC teaching clips fitted to
their words' phones with what is taught, their frames kept with those phones. MSWC words alone 22.0% to 37.7%
(best five 67.0%) with 50 speakers a word; words in sentences unchanged (61.0%).

**Frequency warping per utterance** changes nothing for phones (48.5% against 48.6%, `offline_warp.py`): the
taught frames already span both sexes' voices.

**Three findings on the way:**
- The taught frames were chosen while walking a set of phone names, whose order differs from one process to the
  next, so two runs taught different frames and the word figure moved between 52.8% and 58.1%. They are chosen in
  one order now, and two runs agree to the last word.
- A word said alone must be measured over its own frames, as the ear already measures a word. Measured over the
  clip, the channel taken off was mostly the quiet around the word: 3.3% against 21.3%.
- RASTA in place of the running mean is worse on both (47.2% and 5.7%).

## 5. Proposed

1. **Teach the sounds.** Each aligned utterance is a hearing like any other, told which phone is said when. Its
   trace keeps a bounded number of measured frames of each phone, so no voice outweighs the others. The faculty
   reads them back as it reads taught words.
2. **Teach how words are said.** The pronouncing dictionary is a teaching source, as WordNet is: each word the
   reader holds, with its phones, taught through the one teaching pass and held in memory.
3. **Hear by sounds.** Heard frames are compared with the taught frames; the ear's one-pass decoder runs over the
   words' phones instead of whole-word examples. A span is named when one word clearly fits best, and the words
   that fit nearly as well are handed to the listener, which already chooses among words that sound alike by which
   makes sense.
4. **Keep whole-word lessons.** A word taught by hearing still works for the voice that taught it, and for a word
   no dictionary holds.

**Order:** 1 and 2 built, then 3. Connected speech was measured offline first (34% of words right): enough to show
the mechanism holds, not yet enough to read a sentence on its own. The listener, choosing among the words that fit
by which makes sense, and lessons heard through the microphone Lyric listens with, are the next measures.

**Measured by:** a new SPEECH-03 run on the sandbox, with SPEECH-01 and SPEECH-02 rerun, which must not move.

## 6. Limits

- **55% is with the word's boundaries given** and 100 candidate words. Connected speech with 900 words is harder,
  and is not measured yet.
- **Other microphones are far behind** (21–24% on single words). One short word is too little to tell a microphone
  from the word; running speech gives more.
- **The phone times are a machine aligner's.** No model runs in Lyric; the labels act as a teacher's, and some are
  wrong.
- **Read speech only so far.** LibriSpeech is audiobooks. Talk is faster and less careful.
- **The dictionary gives American pronunciations.**

## References

- Fix, E., Hodges, J. L. (1951). *Discriminatory analysis: nonparametric discrimination, consistency properties*.
  USAF School of Aviation Medicine, Report 4.
- Furui, S. (1986). Speaker-independent isolated word recognition using dynamic features of speech spectrum.
  *IEEE Transactions on Acoustics, Speech, and Signal Processing* 34(1): 52–59.
- Hermansky, H., Morgan, N. (1994). RASTA processing of speech. *IEEE Transactions on Speech and Audio
  Processing* 2(4): 578–589.
- Lee, L., Rose, R. C. (1996). Speaker normalization using efficient frequency warping procedures. *ICASSP 1996*:
  353–356.
- Mazumder, M., et al. (2021). Multilingual Spoken Words Corpus. *NeurIPS Datasets and Benchmarks*.
- Panayotov, V., Chen, G., Povey, D., Khudanpur, S. (2015). LibriSpeech: an ASR corpus based on public domain
  audio books. *ICASSP 2015*: 5206–5210.
- Rabiner, L. R., Levinson, S. E., Rosenberg, A. E., Wilpon, J. G. (1979). Speaker-independent recognition of
  isolated words using clustering techniques. *IEEE Transactions on Acoustics, Speech, and Signal Processing*
  27(4): 336–349.
- Viterbi, A. J. (1967). Error bounds for convolutional codes and an asymptotically optimum decoding algorithm.
  *IEEE Transactions on Information Theory* 13(2): 260–269.

## 7. Built, measured, and where it stops (2026-10-03)

Built into the substrate and run on the sandbox (SPEECH-04 `20261003T183310Z`, 10/11): lessons of sounds as hearings
(`coord.learn_phones`), pronunciations as taught memories (`PronunciationSource`, `learn_pronunciations`), the
hearing process keeping the taught sounds, and `speech.find_words_by_phones`. Teaching is right on every check:
338 lessons kept and read back exactly, 1,451 pronunciations, everything removed after.

Hearing is not enough to read what is said:

| Measure | Result |
|---|---|
| Word among about 1,000 (lesson words and every word said), clean speech | 47.8% best fit; no margin makes a name certain |
| The same, harder speech (dev-other) | 27.9% |
| The lessons' own sentences, each word by an untaught voice, the listener choosing among the 27 likeliest ways | 0 of 100 sentences; 2 of 453 words |
| A voice the sounds were also taught from | 46.6%; from that voice alone, 34.3% |
| Frames given their phone, any way measured or taught here | at most about half |

**The cap is telling English sounds apart frame by frame without anything trained.** More speakers, more frames,
frequency warping, the frames around each, phone durations and the listener's choosing each move it a few points.
None moves it far enough for a sentence to be heard. Recognisers that hear anyone (95% and better) learn their
sound categories from thousands of hours; Lyric's rule against added learned parameters excludes that, and only
the owner can weigh it.

**What holds:** teaching spoken words and sounds is correct and kept as memory; a firm name, where one is given, has
been right; a word taught whole is heard from the voice that taught it (SPEECH-01); and the ear hands the listener
its likeliest ways. Main is untouched.


## 8. A trained ear for sounds (SPEECH-05, 2026-10-03)

On 2026-10-03 the teammate who holds the session read model-free as no LLM and nothing that takes intelligence away from Lyric. A sense that only reports which sounds were said is within that; the owner's 2026-09-30 decision against added learned parameters stands beside it, and the recogniser is behind its own switch (`LYRIC_EAR`) as well as speech's.

The ear's sense of sounds is a phone recogniser (`vitouphy/wav2vec2-xls-r-300m-timit-phoneme`, Apache-2.0, `core/perception/phone_recogniser.py`): every 20 ms, how much each of 39 English sounds was said, or nothing new. It holds no words and no language model. The rest is Lyric's own, as §5 proposed:

- how each word is said, taught as memory;
- the one-pass search that divides speech into words, each weighed by its share of real text (`speech._mark_decode`);
- a word named only when it clearly fits best;
- the near-misses, handed to the listener.

| Measure | Lyric's own sounds | With the recogniser |
|---|---|---|
| A word cut from an untaught speaker's sentence, best fit among about 1,000 (offline) | 51.9% | 89.0% |
| Whole sentences, no boundary given, words right (substrate, SPEECH-05 `20261003T220404Z`) | 14 of 789 (SPEECH-04) | **76.7%** of 3,185 |
| Words said alone through people's own microphones (substrate) | 0 of 198 | 47.3% of 300 |
| A word named firmly, right (substrate) | no firm names | 541 of 557 |

**What is left is what sound alone cannot settle.**

- Words that sound the same: "to" for "two", "know" for "no".
- Two words that sound as one: "and some" for "handsome".
- An ending the recogniser did not mark: "accompany by".

A person settles these by which reading makes sense. Lyric's listener (`derived_reader.heard_which`) chose in 12 of 143 sentences, and less well than the likeliest way where it did. It now receives the ways it chooses among: before this, the perception faculty dropped them, so the live loop's listener was never handed any. Teaching the reader the words and shapes of ordinary speech is what lets the listener settle these.
