"""SPEECH-02, offline: why words said by untaught speakers are not named.

No store and no substrate. The ear's own measurements (`speech.word_features`) and distance (`speech.warp`), on the
clips SPEECH-02 teaches from and hears, presented as it presents them. For each heard word, its distance to every
taught example is found once; then, with 3, 5 and 10 teaching speakers per word:
  - nearest: the word whose nearest example is nearest is the word said (no test of how clearly it won);
  - in the nearest five;
  - named by the ear's ratio test (`speech._named`), and of those, right; firm (support >= 0.5) and wrong.

    ./venv_lyric/bin/python3 experiments/SPEECH-02/offline_naming.py [--words 100] [--heard 3]
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))


def main() -> int:
    import numpy as np
    from core.perception import hearing as H
    from core.perception import speech as SP
    from clips import clips, present
    from fetch_mswc import lesson_words

    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=100)
    parser.add_argument("--heard", type=int, default=3)
    args = parser.parse_args()
    used = lesson_words()
    available = clips(set(used), 10, args.heard)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w))
             if w in available and len(available[w]["teach"]) == 10 and len(available[w]["heard"]) == args.heard]
    words = words[:args.words]
    rng = np.random.default_rng(20261003)
    work = HERE / "work" / "offline"

    def features(clip, role, word, k):
        path = present(clip["path"], work / role / word / f"{k}.wav", rng)
        return SP.word_features(H.decode(str(path)))

    started = time.time()
    taught = {w: [features(c, "teach", w, k) for k, c in enumerate(available[w]["teach"])] for w in words}
    heard = [(w, features(c, "heard", w, k)) for w in words for k, c in enumerate(available[w]["heard"])]
    print(f"{len(words)} words, {sum(len(v) for v in taught.values())} taught examples, {len(heard)} heard; "
          f"measured in {time.time() - started:.0f} s", flush=True)
    started = time.time()
    # distance[h][w] = the distances from heard word h to each of word w's ten examples, in teaching order
    distance = [{w: [SP.warp(f, e) for e in examples] for w, examples in taught.items()} for _, f in heard]
    print(f"distances in {time.time() - started:.0f} s", flush=True)

    report = {}
    for examples in (3, 5, 10):
        nearest = top5 = named = right = firm_wrong = 0
        for (said, _), d in zip(heard, distance):
            per_word = {w: min(ds[:examples]) for w, ds in d.items()}
            order = sorted(per_word, key=per_word.get)
            nearest += order[0] == said
            top5 += said in order[:5]
            name = SP._named(per_word)
            if name:
                named += 1
                right += name["word"] == said
                firm_wrong += name["word"] != said and name["standing"] >= 0.5
        n = len(heard)
        report[examples] = {"nearest is the word said": f"{nearest}/{n}", "in the nearest five": f"{top5}/{n}",
                            "named": f"{named}/{n}", "named right": f"{right}/{named or 1}",
                            "firm and wrong": firm_wrong}
        print(f"  {examples:2d} speakers a word: nearest {100 * nearest / n:.1f}%, in the nearest five "
              f"{100 * top5 / n:.1f}%, named {named}/{n} ({right} right, {firm_wrong} firm and wrong)", flush=True)
    (HERE / "work" / "offline_naming.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
