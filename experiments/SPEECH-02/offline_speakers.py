"""SPEECH-02, offline: how naming words said by untaught speakers grows with the speakers each word is taught from,
decided by a word's k nearest examples (Rabiner, Levinson, Rosenberg and Wilpon 1979).

No store and no substrate. The ear's own measurements and distance, on the top `--words` lesson words, each heard
from 3 test speakers, against up to 60 teaching speakers (MSWC dev, then train). Scored: the right word is nearest,
and among the nearest five, with each word's distance the mean of its k nearest examples.

    ./venv_lyric/bin/python3 experiments/SPEECH-02/offline_speakers.py [--words 100]
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
SPEAKERS = (3, 10, 20, 40, 60)


def main() -> int:
    import numpy as np
    from core.perception import hearing as H
    from core.perception import speech as SP
    from clips import clips, present
    from fetch_mswc import lesson_words
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=100)
    args = parser.parse_args()
    used = lesson_words()
    available = clips(set(used), max(SPEAKERS), 3)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w))
             if w in available and len(available[w]["teach"]) >= max(SPEAKERS) and len(available[w]["heard"]) == 3]
    words = words[:args.words]
    rng = np.random.default_rng(20261003)
    work = HERE / "work" / "offline"
    started = time.time()
    taught = {w: [SP.word_features(H.decode(str(present(c["path"], work / "teach" / w / f"{k}.wav", rng))))
                  for k, c in enumerate(available[w]["teach"])] for w in words}
    heard = [(w, SP.word_features(H.decode(str(present(c["path"], work / "heard" / w / f"{k}.wav", rng)))))
             for w in words for k, c in enumerate(available[w]["heard"])]
    print(f"{len(words)} words with {max(SPEAKERS)} teaching speakers each, {len(heard)} heard; "
          f"measured in {time.time() - started:.0f} s", flush=True)
    started = time.time()
    distance = [{w: [SP.warp(f, e) for e in ex] for w, ex in taught.items()} for _, f in heard]
    print(f"distances in {time.time() - started:.0f} s", flush=True)
    report = {}
    for speakers in SPEAKERS:
        for k in (1, 3, 5):
            if k > speakers:
                continue
            near = top5 = 0
            for (said, _), d in zip(heard, distance):
                per = {w: float(np.mean(sorted(ds[:speakers])[:k])) for w, ds in d.items()}
                order = sorted(per, key=per.get)
                near += order[0] == said
                top5 += said in order[:5]
            report[f"{speakers} speakers, k={k}"] = (round(100 * near / len(heard), 1),
                                                    round(100 * top5 / len(heard), 1))
            print(f"  {speakers:2d} speakers a word, k={k}: nearest {100 * near / len(heard):.1f}%, "
                  f"in the nearest five {100 * top5 / len(heard):.1f}%", flush=True)
    (HERE / "work" / "offline_speakers.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
