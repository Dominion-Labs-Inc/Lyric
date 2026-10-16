"""SPEECH-05, offline: whole sentences said by one untaught speaker, no word boundary given, heard by the phone
recogniser's sounds and divided into words by Lyric (`offline_ctc.decode`), against what was said: words right,
taken for another, left out and put in (Levenshtein), over the lesson words and every word said in them.

    ./venv_lyric/bin/python3 experiments/SPEECH-05/offline_sentences.py [--weight 0.5 1 2]
"""
import argparse
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-03"))


def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from nltk.corpus import brown, cmudict
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from fetch_mswc import lesson_words
    from offline_connected import aligned
    from offline_ctc import ALIGNED, Marks, Words, decode
    parser = argparse.ArgumentParser()
    parser.add_argument("--weight", type=float, nargs="+", default=[0.5, 1.0, 2.0])
    args = parser.parse_args()
    started = time.time()
    marks = Marks()
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    table = pq.read_table(ALIGNED / "test_clean.parquet", columns=["words", "audio"]).to_pylist()
    heard = []
    for k, row in enumerate(table):
        if k % 18:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        heard.append(([w["word"] for w in row["words"] if w["word"] != "<unk>"],
                      marks(resample_poly(y, H.SR, rate) if rate != H.SR else y)))
    vocabulary = set(lesson_words()) | {w for truth, _ in heard for w in truth}
    words = Words({w: [" ".join(way) for way in said[w]] for w in vocabulary if w in said},
                  {w: usage[w] for w in vocabulary}, marks)
    unknown = sum(1 for truth, _ in heard for w in truth if w not in words.ways)
    print(f"{len(heard)} sentences, {sum(len(t) for t, _ in heard)} words said ({unknown} not in the dictionary); "
          f"{len(words.words)} candidate words ({time.time() - started:.0f} s)", flush=True)
    report = {}
    for weight in args.weight:
        right = other = out = put = 0
        shown = []
        for truth, logp in heard:
            found = [w for _, _, w in decode(logp, words, marks, weight)]
            r, s, d, i = aligned(truth, found)
            right, other, out, put = right + r, other + s, out + d, put + i
            if len(shown) < 4:
                shown.append((" ".join(truth[:14]), " ".join(found[:14])))
        n = right + other + out
        report[weight] = {"right": right, "for another": other, "left out": out, "put in": put, "said": n}
        print(f"  usage weighed {weight}: right {100 * right / n:.1f}% of {n} words; word errors "
              f"{100 * (other + out + put) / n:.1f}% (for another {other}, left out {out}, put in {put}) "
              f"({time.time() - started:.0f} s)", flush=True)
        for truth, found in shown[:3]:
            print(f"      said:  {truth}\n      heard: {found}", flush=True)
    (HERE / "work").mkdir(exist_ok=True)
    (HERE / "work" / "offline_sentences.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
