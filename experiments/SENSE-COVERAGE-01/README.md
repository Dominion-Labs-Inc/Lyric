# SENSE-COVERAGE-01: every sense of a word reaches the listener

**Claim.** The reader reports every sense of a word wherever the word stands; how well a sense fits there (whether its
word was taught in that place, stood where the place's own words stand, is written as they are) is the listener's
evidence (`derived_reader.meant`), never a reason to leave the sense out.

**Why.** A sense the reader does not report cannot be taken, however much memory knows of it. On 2026-10-01 the
computer's mouse, the bird's wing, the elephant's trunk and a synonym's every sense were each found missing from the
listener's choices, one at a time, each for a structural accident (a link learned in the "an" twin of a frame, a word
never seen beside the lessons' words, a synonym judged like an irregular form). This experiment finds that kind of
miss for every word at once, so it is found by a check and not by tracing (`docs/research/WORD_SENSES.md`, §4.1 and
§4.6).

**What it does.** For every word the store holds with two or more senses, it builds a sentence through each frame the
word was taught in (any of its senses), the frame's other places filled with words taught there, reads it, and
checks which of the word's senses are reported:

| Section | Checks |
|---|---|
| A | Each sense is reported in the frames its own word was taught in |
| B | In the frames its other senses were taught in, no sense is left out for how well it fits there. A sense not reported is counted by why: no reading of it (its concept cannot stand there, as a verb's sense in a noun's place), another reading of the whole sentence was taken (a sentence taught with its meaning), its words would name one thing twice ("A tour is a turn.", both `go`), or it read loosely or took new names (another reading of the words) |
| C | The store is the sandbox |

Runs on the sandbox (`lyric_dev`) as it stands: the database, the beliefs and the memory agent are read; the
substrate is not started and nothing is written.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/SENSE-COVERAGE-01/experiment.py
```

**Runs:**
- 2026-10-01 (`results/20261001T203422Z.json`), on the sandbox SENSE-01 `--k-only --fresh` left, after the reader
  keeps every sense of the words read (`_read_pieces`) and the listener weighs how a sense fits (`meant`):
  **3/3.** 72 words; A 474/474; B: of 812 checks, 72 not reported, none for how well it fits: 63 no reading of it,
  8 another reading of the sentence, 1 a thing named twice. Earlier runs the same evening refined the experiment's own
  counting (a sense named by a frame's own word, "A ?slot0 is an amphibian.", counts as reported; only the word's own
  readings are weighed).

- 2026-10-02 (`results/20261002T020607Z.json`), on the sandbox K's fresh run left (one concept per sense): **3/3.**
  1,420 words; A 6,820/6,820; B: of 12,233 checks, 3,216 not reported, none for how well it fits (3,193 no reading
  of it, 23 another reading of the sentence). The probe now writes a word as it is written inside a sentence: a first
  run wrote "Black" and "State" with capitals, which read as names, and counted 10 misses of its own.

**Known limits.**
- The sandbox holds english_01–28 and K's words' WordNet records; full WordNet will hold far more words and places.
- A sentence is built only where every other place has a fully written word taught there.
