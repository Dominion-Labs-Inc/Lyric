# SPEECH-04: the substrate hears a word by the sounds it is made of

**Claim.** Taught the sounds words are made of by hearing sentences told which sound is said when, and how the lesson
words are said, the substrate hears a word said by a speaker it never heard by its sounds, and a word it names
firmly is the word said.

**Why.** SPEECH-03 measured offline that hearing by sounds carries a word to an untaught voice far more often than
whole-word matching (`docs/research/HEARING_BY_PHONES.md`). This builds it into the substrate:
- `coord.learn_phones`: a lesson of sounds is a hearing, told which phone is said when; its trace keeps frames of
  each phone (`speech.phones_example`) at half precision, with each frame's phone.
- `PronunciationSource` (CMU Pronouncing Dictionary, Brown usage) through the one teaching pass;
  `learn_pronunciations` keeps each as a memory, as a word class is kept.
- The faculty reads both back from memory. The hearing process keeps the taught sounds between hearings and is
  sent only new lessons.
- `speech.find_words_by_phones` gives the same spans the whole-word finder gives. Where sounds are taught, a stretch
  is heard by them.

**What it checks** (sandbox):

| | Property |
|---|---|
| A | dev-clean sentences heard through `learn_phones`: none refused; each a hearing in the shared mind tagged as spoken sounds; its trace keeps exactly the frames measured, with their phones |
| B | every pronunciation the source states is kept, as told |
| C | a fresh faculty reads every frame and every pronunciation back |
| D | MSWC lesson words said alone and LibriSpeech test-clean sentences, by untaught speakers, heard through the faculty's `sense` (nothing kept): a word named firmly is the word said; more words named right than whole words were (4 of 200) |
| E | everything the run wrote is removed; main untouched |

**Run** (from the Lyric folder; needs the recordings SPEECH-02 and SPEECH-03 fetch):

```
./venv_lyric/bin/python3 experiments/SPEECH-04/experiment.py [--every 8] [--sentences 40]
```

**First run (`20261003T183310Z`, 10/11), every eighth dev-clean sentence taught.**
- **Taught right:** 338 lessons of sounds, none refused, each a hearing in the shared mind, traces exact (78,984
  frames); 1,451 pronunciations of 1,178 words kept as told; a fresh faculty reads all of it back; everything
  removed; main untouched. About two seconds a lesson.
- **Heard:** of 198 MSWC words said alone, none named right, 2 named wrongly (neither firmly), 196 not named; of 789
  words in 40 test-clean sentences, 14 heard. No firm name was wrong.
- **Why so little:** a name needs the best word to fit at least 0.5 a frame ahead of any other (`PHONE_CLEAR`, where
  names were right 84.5% of the time on dev-other), and the near-misses were handed on only when two or three words
  fit nearly as well. Here many did, so nothing reached the listener. The ear now hands each uncertain span's best
  three words, and the sentence's likeliest ways, best first (`speech.ranked_texts`).
- An earlier start at every second sentence was stopped after 35 lessons (about 11 seconds a lesson while it ran);
  what it wrote was removed by its own times.
