# RECALL-01 — remembering is rebuilding, for what was heard and what was seen

**Finding (2026-09-28).** The substrate remembers what it meets as traces, not copies, and
`recollect(memory_id)` rebuilds them in the mind.

- **A hearing** is kept as each sound's shape over time: 24-band envelope, pitch, periodicity,
  loudness at every hop, and where it rose. That is 6.4% of the JFK recording, 2.6% over 19
  recordings. The recording itself is not kept.
- **A seeing** is kept as a gist of about 4–6 kB: the scene at 128 pixels, plus the three most
  prominent things at 96 pixels each, with their outlines. The photograph is still stored
  beside it, as before (its removal was not asked for). `recollect` never reads it.

Rebuilt from memory, after the file was deleted:

| what comes back | result |
|---|---|
| firmly read pitchedness, register, onset of a rebuilt sound | 24/24 |
| pitch within 5% | 12/12 |
| loudness within 3 dB | 13/13 |
| number of sounds | 8/8 recordings |
| a clean picture's things | all |
| a real frame's things (4K daylight, dusk, sunrise, night) | 5/6 |
| a real frame's dominant hue | 4/4 |

**Properties checked** (11):

| # | property |
|---|---|
| A | a hearing's memory holds a trace (`application/x-npz`) and no recording |
| B | with the source file deleted, the sound and the picture still come back: they are rebuilt from memory |
| C | the rebuilt sound is heard as the same: firmly read pitchedness, register and onset agree in at least 90% of readings, pitch within 5%, loudness within 3 dB |
| D | a clean picture's things all come back; on real footage at least half of a picture's things, and its dominant hue in all but one |
| E | a memory that met nothing rebuilds nothing |

**How the two traces were chosen — by measurement, not taste.** Scratch batteries on 19 real
recordings and 12 pictures (10 real frames) came first.

*Sound:*
- A first trace sampled pitch per frame. A single frame's pitch slips onto harmonics (a low note
  read 79, 158, 318 Hz) and the rebuild then sounded unpitched.
- That led to:
  - a pitch tracker that chooses a continuous path (pYIN's threshold prior, no learned model);
  - folding of harmonic slips;
  - a 5-frame median;
  - loudness remembered at every hop;
  - the moment each sound rose.

*Picture:*
- Painting each region flat in its average colour over a 32-pixel layout found only 10 of 25
  things again and invented more than it found: on real footage a region is a fragment.
- The scene small plus the attended things in detail found 16–17 of 25. The ceiling is 20/24:
  what the describer finds of its own things when the same frame is merely re-encoded.

**The trap in measuring it.**
- **Asking whether the rebuilt thing is perceived as the same** is the test. Comparing pixels
  or samples would reward copying.
- **Near-cut readings flip by their own account.** A reading whose support says it sits on a
  cut is a coin flip, so C counts firmly read ones and reports all readings as metrics.
- **The rebuilt test card shows one thing beyond the original:** its thin black frame. At full
  resolution it is not a thing to the describer; remembered soft, it becomes a grey band that
  is. This is recorded as a metric, not a failure: it was in the picture.

**Known limits** (in the run, not hidden):
- A breathy sound's pitch can be ambiguous by an octave. Blow reads 196 Hz where pYIN reads
  397 Hz.
- A sound beginning at a recording's very first sample has no heard onset, so none is claimed.

**Run** (sandbox store; boots the full system; everything written is removed by nonce and by
memory id):

```
POSTGRES_DATABASE=torinai_dev ./venv_torin/bin/python3 experiments/RECALL-01/experiment.py
```

**Results.** `results/<UTC timestamp>.json` and `.md`.
- First run: 10/11. The card check demanded identity, not what its hypothesis said.
- `20260928T151333Z`: 11/11. 320 tagged rows written, 0 left.
