"""SPEECH-03, offline: a sound compared whole with stored examples of each phone (template matching; De Wachter,
Matton, Demuynck, Wambacq, Moors and Van Compernolle 2007), against a frame compared with stored frames.

Nothing is trained: the examples are kept as they were said. Taught: every second dev-clean sentence; each phone
said in it is a template, its frames as the ear measures them for sounds (band energies less the channel, and their
change), up to `PER_PHONE` templates of each phone, spread over the speakers. Heard: phone segments of a ninth of
test-clean, by its aligned times (other speakers), each given:
  - by frames: the phone most of its frames' nearest taught frames are (`speech.PhoneLibrary`, summed over it);
  - by templates: the phone whose `K` nearest templates lie nearest, by dynamic time warping (`speech.warp`).

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_templates.py
"""
import io
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
PER_PHONE = int(os.environ.get("PER_PHONE", 300))
K = int(os.environ.get("K", 3))
SEGMENTS = int(os.environ.get("SEGMENTS", 3000))


def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import speech as SP
    rng = np.random.default_rng(20261003)
    started = time.time()

    def utterances(split, every):
        table = pq.read_table(ALIGNED / f"{split}.parquet", columns=["id", "phonemes", "audio"])
        for k, row in enumerate(table.to_pylist()):
            if k % every:
                continue
            y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
            y = resample_poly(y, H.SR, rate) if rate != H.SR else y
            bands = SP.band_energies(y)
            plain = bands - SP._running_mean(bands)
            frames = np.concatenate([plain, np.gradient(plain, axis=0)], axis=1).astype(np.float32)
            told = "|".join(f"{p['phoneme']} {p['start']:.3f} {p['end']:.3f}"
                            for p in row["phonemes"] if p["phoneme"] != "spn")
            segments = [(SP.plain_phone(p["phoneme"]), int(np.ceil(p["start"] * H.SR / SP._HOP)),
                         int(p["end"] * H.SR / SP._HOP)) for p in row["phonemes"] if p["phoneme"] != "spn"]
            yield row["id"].split("-")[0], y, frames, told, segments

    library = SP.PhoneLibrary()
    templates = defaultdict(list)
    for speaker, y, frames, told, segments in utterances("dev_clean", 2):
        library.add(*SP.phones_example(y, told))
        for phone, lo, hi in segments:
            if hi - lo + 1 >= SP.SHORTEST_PHONE:
                templates[phone].append((speaker, frames[lo:hi + 1]))
    kept = {}
    for phone, found in templates.items():
        order = rng.permutation(len(found))[:PER_PHONE]
        kept[phone] = [found[i][1] for i in order]
    phones = sorted(kept)
    print(f"taught: {library.size} frames; {sum(len(v) for v in kept.values())} templates of {len(phones)} phones "
          f"({time.time() - started:.0f} s)", flush=True)

    heard = []
    for speaker, y, frames, told, segments in utterances("test_clean", 9):
        logp = library.sounds_like(SP.phone_frames(SP.band_energies(y)))
        for phone, lo, hi in segments:
            if hi - lo + 1 >= SP.SHORTEST_PHONE and phone in kept:
                heard.append((phone, frames[lo:hi + 1], logp[lo:hi + 1]))
    pick = rng.permutation(len(heard))[:SEGMENTS]
    heard = [heard[i] for i in pick]
    print(f"heard: {len(heard)} phone segments ({time.time() - started:.0f} s)", flush=True)

    by_frames = by_templates = 0
    confused = Counter()
    for n, (phone, frames, logp) in enumerate(heard):
        summed = logp.sum(axis=0)
        by_frames += library.phones[int(summed.argmax())] == phone
        cost = {p: float(np.mean(sorted(SP.warp(frames, t) for t in kept[p])[:K])) for p in phones}
        best = min(cost, key=cost.get)
        by_templates += best == phone
        if best != phone:
            confused[(phone, best)] += 1
        if (n + 1) % 500 == 0:
            print(f"   {n + 1}: by frames {100 * by_frames / (n + 1):.1f}%, by templates "
                  f"{100 * by_templates / (n + 1):.1f}% ({time.time() - started:.0f} s)", flush=True)
    n = len(heard)
    print(f"  phone segments given their phone: by frames {100 * by_frames / n:.1f}%, by templates "
          f"{100 * by_templates / n:.1f}% of {n}; templates most often take {confused.most_common(8)}", flush=True)
    (HERE / "work" / "offline_templates.json").write_text(json.dumps(
        {"segments": n, "by frames": by_frames, "by templates": by_templates, "per phone": PER_PHONE, "k": K}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
