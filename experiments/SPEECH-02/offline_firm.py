"""SPEECH-02, offline: how long a stretch must be for a firm name given to it to be right.

The ear names each span of heard speech by the ratio test, and calls a name firm at support 0.5. In the second
run, the last 80 ms of "twelve", split off by the decoder, was named "a" firmly. Hearing already holds that how
firmly a reading is known depends on how many frames it rests on. This measures it for words: the ear's own
`find_words` on words said by untaught speakers (up to 10 a word), taught from 10 speakers a word, and every named
span with its length, support and whether it is the word said.

    ./venv_lyric/bin/python3 experiments/SPEECH-02/offline_firm.py [--words 100]
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))


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
    available = clips(set(used), 10, 10)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w))
             if w in available and len(available[w]["teach"]) >= 10 and available[w]["heard"]][:args.words]
    rng = np.random.default_rng(20261003)
    work = HERE / "work" / "offline"
    taught = {w: [SP.word_features(H.decode(str(present(c["path"], work / "teach" / w / f"{k}.wav", rng))))
                  for k, c in enumerate(available[w]["teach"][:10])] for w in words}
    started = time.time()
    spans = []
    for w in words:
        for k, c in enumerate(available[w]["heard"]):
            y = H.decode(str(present(c["path"], work / "heard" / w / f"{k}.wav", rng)))
            for s in SP.find_words(y, taught):
                if s.get("word"):
                    frames = int(round((s["ends_at"] - s["starts_at"]) * SP.SR / SP._HOP))
                    spans.append({"said": w, "named": s["word"], "support": s["standing"], "frames": frames})
    print(f"{len(words)} words; {len(spans)} named spans in {time.time() - started:.0f} s", flush=True)
    firm = [s for s in spans if s["support"] >= 0.5]
    wrong = [s for s in firm if s["named"] != s["said"]]
    print(f"firm: {len(firm)}, wrong {len(wrong)}", flush=True)
    for lo, hi in ((0, 10), (10, 15), (15, 20), (20, 30), (30, 999)):
        here = [s for s in firm if lo <= s["frames"] < hi]
        bad = [s for s in here if s["named"] != s["said"]]
        print(f"  firm spans of {lo}-{hi} frames: {len(here)}, wrong {len(bad)}: "
              f"{[(s['said'], s['named'], s['frames']) for s in bad][:6]}", flush=True)
    weak = Counter((s["named"] == s["said"]) for s in spans if s["support"] < 0.5)
    print(f"weak spans: right {weak[True]}, wrong {weak[False]}", flush=True)
    (HERE / "work" / "offline_firm.json").write_text(json.dumps(spans))
    return 0


if __name__ == "__main__":
    sys.exit(main())
