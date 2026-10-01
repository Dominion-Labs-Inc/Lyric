# TUNES-01 — a song known when someone else hums it

**What it tests.** A song taught by hearing one person hum it is known when another person hums it, in their
own key and at their own pace, with no model: how the melody goes (`music.tune_line`, from hearing's own
pitch track) is followed against every taught tune (`music.tunes_heard`: subsequence dynamic time warping
over semitones, the taught line advancing at half to twice the pace, the best of 13 keys and then quarter
semitones around it). A tune is named only when it follows the heard line clearly better than any other.

**Data.** HumTrans (Liu et al. 2023, [Hugging Face](https://huggingface.co/datasets/dadinghh2/HumTrans), CC BY-NC
4.0, research use only): hums of 1,000 song segments by ten people, each with the segment's MIDI. Only the
official VALID (50 tunes, 765 hums) and TEST (55 tunes, 769 hums) splits and one hum each of 300 TRAIN tunes
were fetched, by range requests into the 14.7 GB archive (`remote_zip.py`, `fetch_subset.py`), into
`test_data/music/humtrans/wav/`. The MIR-QBSH server (mirlab.org) did not answer.

**How.** One hum of every tune in a split is taught (its first singer's first take), with the 300 TRAIN tunes
taught as tunes never hummed; every other hum of the split is heard. Settings were chosen on VALID; TEST was heard
once. "Untaught": the split's hums heard against the other split and the 300, none of their own tunes taught, so
every naming is wrong. "Half": the middle half of each hum, as when part of a song is hummed.

**Run** (from the Lyric folder; pitch tracks are cached in `test_data/music/humtrans/pitch/`):

    ./venv_lyric/bin/python3 experiments/TUNES-01/features.py
    ./venv_lyric/bin/python3 experiments/TUNES-01/qbh_eval.py --split TEST --refine 10 \
        --shifts=-6,-5,-4,-3,-2,-1,0,1,2,3,4,5,6 [--crop 0.5] [--untaught] [--dump out.json]

`qbh_eval.py`'s line and cost are the substrate's own: checked equal to `music.tune_line` and `music._follow`
on real hums (same lines, cost 0.929792 both).

## Result (2026-09-29)

TEST, 711 hums against 355 taught tunes, named at `TUNE_RATIO` 0.75:

| | right first | first five | named | right when named |
|---|---|---|---|---|
| whole hums | 95.1% | 96.5% | 85.1% | 100.0% |
| half of a hum | 84.0% | 93.1% | 59.5% | 99.3% |

766 hums of tunes never taught, against 350 taught: 0.1% of whole hums and 2.3% of half hums named as some song.

VALID, the settings chosen: whole hums 93.0% right first (small key search 91.3%); half hums 81.1% with the wide
key search and refinement, 77.6% wide alone, 55.7% with a small key search, 36.0% measuring the taught line from
a median over a window the hum's length (dropped).

How well a hum follows a tune does not decide on its own: at a cost where 26% of hums matched their own tune,
0.9% of untaught hums matched some taught one. So a tune needs a rival to be named, as a spoken word does; one
song taught alone is not named from a hum.

Logs and each query's costs are in `results/`.
