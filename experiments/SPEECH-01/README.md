# SPEECH-01 — spoken words and voices, taught by example, heard by the substrate

**Finding (2026-09-28).** With no model anywhere, the substrate:
- was taught eight spoken words (five recordings each) and three voices (two recordings
  each) by HEARING them, told what each was. Every lesson is a hearing like any other,
  remembered as one: the same memory, saying what it taught, with its trace keeping the
  example measured for matching, and it can be heard again in the mind;
- read them all back, exactly, into a fresh faculty;
- then heard a taught speaker's phrase through `coordinator.hear()`: two of its three words
  were named and the third was left unknown ("... one four"), in the speaker's voice, every
  sound heard as a voice.

What was said and by whom was admitted, believed (0.97–0.99), remembered in words, judged
ACT, and handed over as an experience. A system sound was no voice and said nothing. A clip's
sound track was heard on the clip. A faculty taught nothing heard no words.

Over real phrases, every firm reading was right:
- 21 of 24 taught words were named, none wrongly;
- one of eight untaught words was given a name, weakly;
- four strangers were each heard as a voice and named as no one.

**A correction, then a rebuild (same day).** At first a taught example was its own kind of
memory: SEMANTIC, measurements only, never heard through `hear`, and not hearable again.
The rule is that voice and sound memories are kept with speech and hearing, the same
memories. So a lesson is now heard through `hear`'s own act (`coord.learn_word`,
`coord.learn_voice`), and section A checks it is the same memory as any hearing.

**The run found two defects. Both are fixed at the root.**

| defect | what it did | fix |
|---|---|---|
| **room hiss was accepted as a spoken word** | `learn_word` refused only an example with fewer than three frames. A recording of nothing but room quiet was kept as the word "quiet". Its measurements lay near the middle of every other word's, so it won everywhere: "three" in the phrase, a submarine's ping and the clip's sound track were all heard to say "quiet". | an example must rise above a room hearing hears it rest in (`speech.rises_from_a_room`, hearing's own segmentation); otherwise it is refused and nothing is kept |
| **whose voice needed a second of voiced speech, a guess** | the floor was set from two points (single words vs 4–6 word stretches). Three spoken digits (0.83 s voiced, a clear 0.67 ratio) were never judged. | measured by amount of voicing over all 20 trios of taught people: under 0.4 s, 14% of strangers were named and 10 taught people named wrongly; from 0.4 s on, ~1% and none wrongly. The floor is 0.4 s |

**Properties checked** (30):

| # | property |
|---|---|
| A | each example is heard through `hear`'s own act and remembered as a hearing (tags `sound`, `hearing` + `spoken_word`/`voice`, the word or person in its record, through `hear`); its trace keeps the example measured for matching, never the recording; it can be heard again in the mind (`recollect`); a recording of room quiet is refused and nothing is kept |
| B | a fresh faculty reads every taught word and voice back from memory, every example, bit for bit |
| C | a taught speaker's phrase is heard as the taught words, in order, none wrongly, in that speaker's voice; each voiced sound `isa voice` with its support |
| D | `said <word>` and `spoken_by <person>` are in the concept graph and held as beliefs; the sound `isa voice` |
| E | the hearing's memory says what was said, in words, and keeps a trace of the sound, never the recording |
| F | each word said and whose voice is a claim judged by the acceptance band, with a posterior |
| G | the hearing waits in the experience pool with what was said in it |
| H | a system sound (Submarine) is no voice, and nothing is said in it |
| I | words said in a video's sound track are on the clip's percept |
| J | the same speech heard by a faculty taught nothing has no words, no voice and no one's voice |
| K | 8 phrases (24 taught words), 4 stretches of untaught words, 4 strangers: taught words heard (≥ half; offline 64–75%); no firm name given to a word not said, to an untaught word, or to a stranger |

**How to read K.** The accuracy numbers were measured offline before this run, on 720 words in
240 phrases and on every trio of taught voices (see `core/perception/speech.py`). The thresholds
here are those measurements, not values fitted to this run. A reading AT the cut is weak by its
own account (its support says so) and may be wrong as often as that support admits. A FIRM
reading (support ≥ 0.5) must be right. That is the same rule HEAR-01 applies to pitch and onset.

**Known limits, stated rather than hidden.**
- An untaught word that sounds like a taught one is heard as it ("nine", never taught, was
  named "five" at ratios just inside the cut). No distance test separates it; teaching the word
  does.
- With only two voices taught, strangers pass as one of them (9 in 36). With three or more they
  rarely do, and a stranger named at all is named weakly.
- Machine voices (macOS speech) mostly fall outside the voices taught from people.

Recordings: the Free Spoken Digit Dataset (`test_data/fsdd`, CC BY-SA 4.0). They are presented
as a live buffer presents speech, with room quiet at −60 dBFS around them, built into
`stimuli/` on first run from a fixed seed. The macOS system sounds stand for sounds that are not
a voice.

Run (sandbox store): `./venv_torin/bin/python3 experiments/SPEECH-01/experiment.py`
