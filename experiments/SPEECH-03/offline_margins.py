"""SPEECH-03, offline: how far ahead the best word must fit for a name given by the sounds to be right.

Through the substrate's own functions (`core/perception/speech.py`): every second dev-clean sentence is a lesson of sounds
(`phones_example`, told its aligned phones), held in a `PhoneLibrary`. Word stretches said by dev-other speakers
(neither teaching nor heard in the experiment) are fitted against every lesson word and the word said
(`_phone_fits`). For each, the margin a frame by which the best word fits ahead of the best word said differently,
and whether the best is the word said. The cuts `PHONE_CLEAR` (a name is given) and `PHONE_RESOLVED` (fully
resolved) are read off these, and the same is reported on test-clean to see they hold.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_margins.py
"""
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"


def rows(split, every):
    import pyarrow.parquet as pq
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    table = pq.read_table(ALIGNED / f"{split}.parquet", columns=["id", "words", "phonemes", "audio"])
    for k, row in enumerate(table.to_pylist()):
        if k % every:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        yield row, (resample_poly(y, H.SR, rate) if rate != H.SR else y)


def told(row):
    return "|".join(f"{p['phoneme']} {p['start']:.3f} {p['end']:.3f}" for p in row["phonemes"] if p["phoneme"] != "spn")


def main() -> int:
    import numpy as np
    from nltk.corpus import brown, cmudict
    from core.perception import speech as SP
    from core.perception import hearing as H
    from fetch_mswc import lesson_words
    started = time.time()
    library = SP.PhoneLibrary()
    for row, y in rows("dev_clean", 2):
        frames, labels = SP.phones_example(y, told(row))
        library.add(frames, labels)
    print(f"taught: {library.size} frames of {len(library.phones)} phones as lessons ({time.time() - started:.0f} s)",
          flush=True)
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    report = {}
    import os
    splits = [(n, int(e)) for n, e in (x.split(":") for x in os.environ.get("SPLITS", "dev_other:12,test_clean:18").split(","))]
    for split, every in splits:
        samples = []
        for row, y in rows(split, every):
            spoken = [(w["word"], int(w["start"] * H.SR / SP._HOP), int(np.ceil(w["end"] * H.SR / SP._HOP)))
                      for w in row["words"] if w["word"] in said]
            vocabulary = set(lesson_words()) | {w for w, _, _ in spoken}
            told_as = {w: [" ".join(way) for way in said[w]] for w in vocabulary if w in said}
            words = SP.SaidAs(told_as, {w: usage[w] for w in told_as}, library)
            logp = library.sounds_like(SP.phone_frames(SP.band_energies(y)))
            for word, lo, hi in spoken:
                if hi - lo < SP.SHORTEST_PHONE or word not in words.word_index:
                    continue
                fits = SP._phone_fits(logp[lo:hi + 1], words)
                order = [words.words[i] for i in np.argsort(-fits) if np.isfinite(fits[i])]
                best = order[0]
                rival = next((w for w in order if not words.alike(w, best)), None)
                margin = (fits[words.word_index[best]] - fits[words.word_index[rival]]) / (hi - lo + 1)
                samples.append((float(margin), words.alike(best, word)))
        samples.sort(key=lambda s: -s[0])
        right = sum(ok for _, ok in samples)
        print(f"== {split}: {len(samples)} word stretches, best fit right {100 * right / len(samples):.1f}% "
              f"({time.time() - started:.0f} s)", flush=True)
        curve = []
        for cut in (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0):
            named = [ok for m, ok in samples if m >= cut]
            if named:
                curve.append((cut, len(named), round(100 * sum(named) / len(named), 1)))
                print(f"   margin >= {cut:4.2f}: {len(named):5d} named ({100 * len(named) / len(samples):.1f}%), "
                      f"right {100 * sum(named) / len(named):.1f}%", flush=True)
        report[split] = {"stretches": len(samples), "best fit right": right, "curve": curve}
    (HERE / "work" / "offline_margins.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
