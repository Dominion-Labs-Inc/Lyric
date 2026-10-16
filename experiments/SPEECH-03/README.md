# SPEECH-03: a word heard as the sounds it is made of

**Claim.** Taught the sounds words are made of, from forty speakers, and nothing of the words themselves, the ear's
measurements name a word said in a sentence by a speaker it never heard more often than whole-word matching does
with sixty speakers teaching each word.

**Why.** SPEECH-02 taught the lessons' words by hearing and measured that a whole word carries from one voice to
another about four times in ten at best. This is the research before anything is built
(`docs/research/HEARING_BY_PHONES.md`).

**What it does.** Offline: no store and no substrate. Nothing is trained (`phones.py`):
- **Taught:** frames of each phone, cut by LibriSpeech's aligned phoneme times (dev-clean, 40 speakers), up to 400
  of a phone from one speaker. A frame is the log energy in each of the ear's 26 speech bands with the channel
  removed, their change, and the same of the frames out to 60 ms either side.
- **Heard:** a frame sounds like the phones its 25 nearest taught frames are.
- **Words:** a stretch is fitted to each candidate word's phones in order, as the CMU Pronouncing Dictionary gives
  them, and the word that fits best is the word heard. Words said the same ("two", "to") are one to the ear.

| | Checked |
|---|---|
| A | a frame said by an untaught speaker is given its phone more often measured with the frames around it than as the ear measures a word |
| B | of the lessons' 100 most-used words, the one that fits best is the word said, for words cut from untaught speakers' sentences, more often than whole-word matching reached with sixty speakers a word (38.3%); and it is among the best five three times in four |
| C | measured, not checked: the same for MSWC's words said alone through other microphones |

**Run** (from the Lyric folder; needs the recordings SPEECH-02 fetches, `nltk`'s `cmudict`, and
`data/speech/librispeech_alignments/{dev_clean,test_clean}.parquet`):

```
./venv_lyric/bin/python3 experiments/SPEECH-03/experiment.py
./venv_lyric/bin/python3 experiments/SPEECH-03/offline_frames.py
```

`TEACH=dev_clean,dev_other` teaches from 73 speakers. `offline_frames.py` compares ways of measuring a frame.

**Results** (`results/<UTC timestamp>.json`, `.md` and transcript):

| Run | Taught from | Frames right | Words in sentences: best fit | Best five | MSWC alone: best fit | Best five |
|---|---|---|---|---|---|---|
| `20261003T154529Z` and `20261003T155215Z`, 3/3, the same to the last word | 40 speakers, 565,618 frames | 48.6% (the ear's word measure 32.4%) | 54.9% | 80.1% | 21.0% | 44.3% |
| `20261003T155918Z`, 3/3 | 73 speakers, 1,032,307 frames | 49.0% | 56.1% | 78.5% | 21.7% | 46.7% |

The first run (`20261003T153810Z`, 3/3, 52.8% best fit) has no record: it was deleted with the results folder
before the rerun. It showed a fault: the taught frames were chosen in an order that changed from one process to the
next, and the word figure moved between 52.8% and 58.1% (the unrecorded study before it). They are chosen in one
order now, and the two runs above agree to the last word.

| `20261003T164034Z`, 3/3, each phone at least 3 frames | 40 speakers | 48.6% | 61.8% (the very word 59.8%) | 85.0% | 22.0% | 47.0% |

**A phone lasts at least three frames.** Of 192,830 phones aligned in dev-clean none is shorter. Fitted with no
such floor, a stretch hopped through a word's sounds a frame at a time (`phones.SHORTEST`, `chained`).

**Whole sentences, no word boundaries given** (`offline_connected.py`: 60 test-clean utterances, 1,180 words said;
every word said and every lesson word a candidate, 1,306). A one-pass search over the candidate words' phones, each
word entered at a cost of its share of the Brown corpus, weighed against the sounds:

| Usage weighed | Without the floor: words right | With it | Taken for another, left out, put in (with it) |
|---|---|---|---|
| 0 | 27.6% | 27.4% | 856, 1, 1,286 |
| 2 | | **34.2%** | 748, 28, 249 |
| 4 | 26.7% | 29.9% | 729, 98, 79 |
| 6–8 | 15.5% | 22.0% | 630, 290, 12 |

Said "the dull light fell more faintly upon the page whereon"; heard "the go like so more face a upon the page were
on".

**Teaching the sounds again from words heard through people's microphones** (`offline_mswc.py`). Each MSWC teaching
clip (dev and train speakers, never a test speaker) is fitted to its word's phones with what is taught
(`Taught.align`); its frames are kept as taught, each with the phone the fit gives it. Nothing is trained.

| Taught from | MSWC words alone | Words in LibriSpeech sentences |
|---|---|---|
| LibriSpeech, 40 speakers | 22.0% (best five 47.0%) | 61.8% (85.0%) |
| and MSWC clips, 20 speakers a word (28,863 frames) | 32.7% (59.7%) | 61.0% (86.2%) |
| and MSWC clips, 50 speakers a word (71,205 frames) | 37.7% (67.0%) | 61.0% (87.8%) |

The clips are of the same 100 words that are heard, said by other speakers: it is what teaching the lesson words by
hearing would do. Whole-word matching with sixty speakers a word reached 38.3% on the same clips; by sounds, Lyric
reaches it and also hears, at 61%, words in sentences no one taught it as words.

**Frequency warping per utterance** (`offline_warp.py`; each heard utterance measured on a frequency axis stretched by
0.88 to 1.12, the factor kept the one under which its frames agree most clearly with the taught ones): 48.5%
against 48.6% as measured. With 40 speakers of both sexes taught, the nearest frames already span the voices.

**Ways of measuring a frame** (`offline_frames.py`, every seventh frame of 292 test utterances, 180,665 taught
frames):

| A frame measured as | Right |
|---|---|
| 12 cepstra and their change (the ear's measure for words) | 31.3% |
| with the frames 40 ms either side | 41.7% |
| 26 band energies and their change | 34.7% |
| with the frames 40 ms either side | 44.9% |
| with the frames 60 ms either side | 45.2% |
| with the frames 80 ms, 120 ms either side | 43.5%, 39.4% |
| three times the taught frames (565,618) | 48.3% |
| each measure over its spread; acceleration; 10 or 50 nearest | no better |

**Known limits:**
- The word's boundaries are given, and there are 100 candidate words. Connected speech with the lessons' 900 words
  is not measured yet.
- Other microphones are far behind. A word said alone must be measured over its own frames (3.3% over the clip,
  21% over the word), and one short word is too little to tell a microphone from the word.
- RASTA in place of the running mean is worse (47.2% in sentences).
- The phone times are a machine aligner's; the speech is read aloud.

**How far ahead the best word must fit for a name to be right** (`offline_margins.py`, through the substrate's own
`core/perception/speech.py`; every second dev-clean sentence taught as a lesson of sounds, 317,296 frames, ten a
phone a lesson; candidates the lesson words and every word said, about 1,000):

| Margin a frame | dev-other: named | right | test-clean: named | right |
|---|---|---|---|---|
| any | 4,344 | 27.9% | 3,149 | 47.8% |
| 0.25 | 15.1% | 61.8% | 25.0% | 79.9% |
| 0.5 | 2.5% | 84.5% | 6.3% | 88.8% |
| 0.6 | 1.1% | 85.4% | 2.5% | 93.8% |
| 1.0 | 0.1% | 5 of 5 | 0.2% | 5 of 6 |

No margin makes a name certain. `PHONE_CLEAR` is 0.5 and a name is firm from 1.0. With twenty frames a phone a lesson
the taught frames were a million and a sentence of seven seconds took ten to hear; with ten, 317,296.

**The lessons' own sentences, chosen by the listener** (`offline_listener.py`): 100 lesson sentences of three to
seven words, each put together from untaught speakers' recordings of its words (one clip a word: MSWC, and
LibriSpeech for short words); heard by sounds (317,296 taught frames, the 900 lesson words); where not every word is
clear, the 27 likeliest ways handed to `derived_reader.heard_which`, read with the sandbox's reader and memory.

- **0 of 100 sentences heard as said; 2 of 453 words right.** The listener chose in 10 and could not in 90: no way
  read.
- e.g. "It is hot." heard "its says an bus"; "Ice is cold." heard "bright bat says an by".
- A word from a new voice is among its best three about a third of the time, so in a sentence of five the right way
  is almost never among the 27, and the listener has nothing true to choose.

**A voice the sounds were taught from** (`offline_same_speaker.py`; five dev-clean speakers, the sounds taught from
half each speaker's sentences, heard on the other half; about 1,000 candidate words):

| Taught from | Best fit right | Named (margin 0.5), right | Firm, right |
|---|---|---|---|
| the speaker's half, beside every second sentence of the 39 others | 46.6% of 3,082 | 154 (5.0%), 142 | 6, 6 |
| the speaker's half alone (about 7,000 frames) | 34.3% of 3,080 | 61 (2.0%), 54 | 4, 4 |

The speaker's own frames are 2% of what is taught beside the others, and alone they are too few. Whose voice it is
is not what caps hearing: telling English sounds apart by the nearest taught frames is right about half the time
for anyone.

**The band the sounds are heard over, and how a frame's phones are weighed** (`offline_margins.py` on test-clean,
about 1,000 candidate words; frames given their phone from `offline_frames.py`):

| Band | Weighed by | Frames right | Best fit right | Named at 0.5, right |
|---|---|---|---|---|
| 100–3,800 Hz (the telephone band words are matched in) | share of nearest frames | 45.0% | 47.8% | 6.3%, 88.8% |
| 100–3,800 Hz | the share over the phone's share of all frames (Bourlard and Morgan 1994) | | 30.7% | 2.6%, 68.3% |
| **100–7,600 Hz** | **share of nearest frames** | **47.0%** | **51.9%** | **7.8%, 93.5%** |
| 100–7,600 Hz | the share over the phone's share | | 34.2% | 3.2%, 83.0% |
| 100–7,600 Hz, 40 bands | share | 47.2% | | |

The sounds are now heard over 100–7,600 Hz (`speech.PHONE_BAND`); words said whole keep the telephone band. Dividing
by how common a phone is was taken out.

**A sound compared whole with stored examples** (`offline_templates.py`; template matching after De Wachter et al.
2007; 600 phone segments of test-clean by their aligned times, 100 examples of each phone from dev-clean, the 3
nearest by dynamic time warping): **37.5%** of segments given their phone, against **52.7%** by summing their
frames' nearest taught frames. Most often confused: R as ER, T as P, AH as OW. Comparing a whole sound with a
hundred examples carries less than comparing each frame, with its neighbours, against three hundred thousand.
