# SPEECH-05: a trained ear for sounds, and words found by Lyric

**Claim.** A trained phone recogniser that reports only which of 39 English sounds were said (no words, no language
model), with Lyric's own pronunciations, word search and listener, hears words said by people Lyric was never
taught by well enough to follow a sentence.

**Why.** Model-free hearing tells English sounds apart about half the time (SPEECH-02 to -04,
`docs/research/HEARING_BY_PHONES.md`): 34% of words in a sentence. On 2026-10-03 the teammate who holds the session
read model-free as "no LLM, nothing that takes intelligence away from Lyric". A recogniser that only senses sounds
holds no knowledge; words, meaning, memory and learning stay Lyric's. The owner declined added learned parameters on
2026-09-30; this reading is the teammate's, and is recorded as such.

**The recogniser.** `vitouphy/wav2vec2-xls-r-300m-timit-phoneme` (Apache-2.0; wav2vec2 XLS-R, fine-tuned on TIMIT's
phones; 315 million parameters; runs on the Mac's GPU). Every 20 ms it reports how much each of 39 sounds was said,
or nothing new (its blank). Its sounds are written as the CMU Pronouncing Dictionary writes them (TIMIT joins AO
with AA and ZH with SH; its flap is a T or a D).

**Offline** (no store written):

| Measure | Lyric's own frame matching (SPEECH-03) | Recogniser, read frame by frame (`offline_recogniser.py`) | Recogniser, read as it reports (`offline_ctc.py`) |
|---|---|---|---|
| A. words cut from untaught speakers' sentences, best fit among about 1,000 | 51.9% | 70.4% | **89.0%** of 3,149 |
| A. named where the best fits clearly ahead (log margin 10) | | | **779 of 779 right** (at 5: 2,223 of 2,254) |
| B. MSWC lesson words said alone, people's own microphones, among 900 | about 22% | 25.3% | **51.0%** of 300 |
| C. the lessons' sentences put together from one clip a word, each a new voice; listener choosing | 0 of 100 | 0 of 100 | 5 of 100; 184 of 453 words |

"Read as it reports": each word is scored by how likely the recogniser is to have reported its sounds in order with
blanks between (connectionist temporal classification; Graves et al. 2006), and a sentence is divided into words in
one pass over the words' sounds in that form, each word entered at a cost of its share of real text.

**Whole sentences, one speaker, no word boundary given** (`offline_sentences.py`; 146 LibriSpeech test-clean
sentences, 3,185 words; candidates the lesson words and every word said, 1,863):

| Usage weighed | Words right | Word errors | Taken for another, left out, put in |
|---|---|---|---|
| 0.5 | **78.2%** | 27.4% | 646, 48, 180 |
| 1.0 | 76.9% | 27.1% | 612, 125, 127 |
| 2.0 | 62.0% | 39.0% | 684, 527, 32 |

Said "the dull light fell more faintly upon the page whereon another equation began"; heard "the dull light fell
more faintly upon the page where on another equation began". Most words taken for another sound the same ("past"
for "passed", "to" for "two", "new" for "knew"): what the listener settles by which makes sense, where the reader
knows the words.

**Known limits:** words said alone through people's own microphones (B, 51%) are far below words in sentences (A,
89%): the recogniser was trained on read speech in a studio, and one short word gives it little to go on. C puts a
new voice and microphone on every word.

## In the substrate

Built in behind `LYRIC_SPEECH` (off unless "on") and `LYRIC_EAR` ("recogniser" unless "off"):

- `core/perception/phone_recogniser.py` is the ear's sense of which sounds were said.
  - It loads once in hearing's process, from this machine only. It is loaded from its folder in the substrate's model cache (`HF_HOME`), because given its name `AutoProcessor` asks huggingface.co for a file even with `local_files_only`.
  - Recordings longer than 30 s are heard in pieces.
- `speech.find_words_by_marks` and `heard_by_marks` do the rest: Lyric's pronunciations in the recogniser's form (`SaidInMarks`), the one-pass word search (`_mark_decode`), and each span's word or near-misses for the listener.
- In `senses.listen` the ear uses, in order: the recogniser; else the sounds taught (SPEECH-04); else the words taught whole.

`experiment.py`, sandbox. It teaches the pronunciations of the lesson words and of every word of the sentences heard, 2,257 ways of 1,863 words. It then hears through the faculty's own `sense`.

| Run | Checks | What it found |
|---|---|---|
| `20261003T215032Z` | 5/8 | The faculty kept `said`, `heard_text` and `spoken_by`, and dropped `heard_texts`. Every word not clearly one word came out as "..." (single words 67 of 300, sentences 60.5%), and the live loop's listener had never been handed the ways (also SPEECH-04's 0 "among words that sound alike"). Fixed in `_speech_content`. |
| `20261003T220404Z` | **7/8** | Below. |

In `20261003T220404Z`, after the fix, the ear hears the whole recording and times each word by its sounds as the search placed them:

| Measure | Result | Lyric's own sounds (SPEECH-04) |
|---|---|---|
| Whole sentences, untaught speakers, words right in the likeliest way | **76.7%** of 3,185 (offline 78.2%) | 14 of 789 |
| Taken for another, left out, put in | 693, 48, 180 | |
| MSWC words said alone, through people's own microphones, right in the likeliest way | **142 of 300** (47.3%) | 0 of 198 |
| Named firmly in sentences | 557, of which **16 wrong** (2.9%) | |
| Seconds to hear a sentence; a word | 0.92; 0.28 | 0.19 a word |
| Pronunciations kept and read back | 2,257 of 2,257 | |
| Sandbox after, main | nothing left; main 290,096 rows before and after | |

Said "they knew no north no south no east no west they stood positively by"; heard "they knew know north know south nice no west stood positively by the constitution". Most of what is taken for another is a word that sounds the same ("to" for "two", "are" for "or", "know" for "no").

**A firm name is right 97.1% of the time, not always (the one failed check).** The margins were measured offline on spans where the words were said (779 of 779 right at 10). The word search's own spans differ (`offline_spans.py`):

- The recogniser marked no sound for an ending: "accompany" for "accompanied by", "move" for "moved".
- Two words sound as one: "handsome" for "and some", "within" for "with an", "everyone" for "every one".
- A span is a piece of a long word: "contain" in "self contained".

Testing the name on its span stretched by up to 80 ms at either end leaves 8 of 512 wrong, so it was not adopted. These are what sound alone cannot settle; the sentence settles them.

**The listener does not yet settle them.** It chose in 12 of 143 sentences and could not in 131. LibriSpeech's sentences mostly do not read in Lyric's reader, and where every way reads the evidence rarely tells them apart. Where it chose, 70 words were right against 81 in the likeliest way.

Offline studies on the way:

- `offline_alone.py`: words said alone, the same 300 clips, among 1,863 words.
  - Told it is one word: 49.0%.
  - The whole clip divided into words: 47.0%.
  - Only the stretch loud enough: 43.0%.
  - The whole clip's marks, divided over that stretch: 46.7%.
- `offline_spans.py`: the stretched-span test above, not adopted.

**Known limits:**

- The listener as above.
- A word not taught is heard as the nearest word taught: "clergyman's" was not among the candidates.
- Candidates were the lesson words and the words of the sentences heard; more words taught means more words to be confused with.
