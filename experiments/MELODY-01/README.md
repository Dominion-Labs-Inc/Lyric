# MELODY-01 — the melody of a full mix, and a song known from it

**What it tests.** Which line of a full mix is the melody, read with no model (`music.melody_of_mix`), and whether
a song taught from its mix is then known from its melody sung alone (`music.tunes_heard`, with octaves forgiven
for a tune read from a mix).

**Data.** MDB-melody-synth (Salamon et al. 2017, [Zenodo 1481168](https://zenodo.org/records/1481168), CC BY-NC
4.0, research use only): 65 MedleyDB mixes whose melody track was resynthesised to an exact f0, with the melody
track alone. Songs sorted by name, alternate ones DEV (33) and TEST (32). Kept in `test_data/music/MDB-melody-synth/`;
nothing of it is copied into the repository.

**How.**
- Frames: the first 60 s of each song, on a 10 ms grid. Pitch right means within 50 cents of the annotation, over
  the frames with melody; "either octave" forgives octave errors. Melody found (VR) and false alarms (VFA) are the
  voicing. Overall (OA) is frames right in both voicing and pitch.
- End to end: each song taught from its whole mix (its tune from `melody_of_mix`, kept as read from a mix). Each is
  then heard as 20 s of its melody track alone, from the middle of where it sings, against all the split's songs.
  "Never taught": the split's melodies heard against the other split's songs, so any naming is wrong.

**Run** (from the Lyric folder):

    ./venv_lyric/bin/python3 experiments/MELODY-01/melody_eval.py --split TEST --method core_mix --seconds 60
    ./venv_lyric/bin/python3 experiments/MELODY-01/tune_from_mix_core.py --split TEST

`core_mix` and `tune_from_mix_core.py` run the substrate's own code. `melody_methods.py` holds every variant tried
on DEV.

## Result (2026-09-29)

TEST, heard once:

| | pitch right | either octave | melody found | false alarms | overall |
|---|---|---|---|---|---|
| frames, first 60 s of 32 songs | 47.2% | 52.7% | 68.5% | 27.8% | 56.6% |

| end to end, 32 songs taught from their mixes | right first | named | right when named |
|---|---|---|---|
| heard as 20 s of the melody sung alone | 59.4% | 40.6% | 100% |
| melodies of 32 songs never taught | — | 3.1% (1) | 0% |

DEV, the way there (first 60 s of 33 songs; pitch right / either octave / overall):

| | pitch | octave | overall |
|---|---|---|---|
| YIN on the mix (what hearing did) | 11.4% | 26.5% | 29.6% |
| strongest salience, 8 harmonics | 41.5% | 54.1% | (all voiced) |
| ... 20 harmonics, magnitudes square-rooted | 49.0% | 62.4% | |
| contours and melody selection (Salamon & Gomez 2012), voicing NU -0.6 | 44.6% | 56.3% | 50.3% |
| ... with a 150 Hz high-pass first | 47.1% | 60.1% | 53.0% |
| ... harmonic/percussive separation first (dropped) | 45.7% | 53.9% | 52.0% |
| Viterbi path through the salience, 0.01 per 10 cents (all voiced) | 58.6% | 69.7% | |
| ... voiced at the song's median path salience (**kept**) | 45.3% | 52.2% | 56.9% |

The true pitch was the strongest salience peak in 55.5% of melody frames, and among the five strongest in 81.0%.
The contour selection had fallen below the strongest peak; the Viterbi path is above it.

End to end on DEV, taught from the mix: 27.3% right first with plain matching, 60.6% with octaves forgiven (contours).
The Viterbi path with its voicing gives 63.6% right first and 39.4% named, all right. Taught from the clean melody
track instead, the ceiling is 97% right first (100% with octaves forgiven). So the extraction, not the matching, is
what limits it.

Forgiving octaves is kept to tunes read from a mix. On 200 VALID hums of TUNES-01 it cost a little: whole hums 91.5%
to 90.5% right first, and half hums 97.3% to 95.7% right when named.
