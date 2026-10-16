"""SPEECH-05, offline: words named firmly in whole sentences that were not said there (38 of 567 in the substrate,
run `20261003T*` part D), and whether a firm name can be made to hold where the word search divides a sentence
wrongly.

Of the 38: 22 were the word said, timed from the blanks before it (fixed: a word is timed by its marked sounds);
12 were a span that is not one word said ("please" for "pleased", "contain" in "self contained", "within" for "with
an"); 2 pieces of a long word named as a short one; 1 over a word not taught. The margins that made names firm were
measured on spans where the words were said (`offline_ctc.py`), and the word search's own spans can be cut short.

So here a name is also tried on its span stretched by up to `k` of the recogniser's frames (20 ms each) at either
end: it holds when no word said differently fits any of those better by `need`. Each `k` and `need`: how many
words are named firmly and how many of them are wrong (not said, or one said the same, within 0.3 s of when it is
timed). Every recording heard whole, as the substrate now does.

    ./venv_lyric/bin/python3 experiments/SPEECH-05/offline_spans.py
"""
import io
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))

STRETCHES = (0, 1, 2, 3, 4)
NEEDS = (0.0, 2.5, 5.0)


def main() -> int:
    import time
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from nltk.corpus import brown, cmudict
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import phone_recogniser as PR
    from core.perception import speech as SP
    from fetch_mswc import lesson_words
    started = time.time()
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    table = pq.read_table(REPO / "data" / "speech" / "librispeech_alignments" / "test_clean.parquet",
                          columns=["id", "words", "audio"]).to_pylist()
    rows = [row for k, row in enumerate(table) if not k % 18]
    vocabulary = set(lesson_words()) | {w["word"] for row in rows for w in row["words"]}
    known = SP.SaidInMarks({w: [" ".join(x) for x in said[w]] for w in vocabulary if w in said},
                           {w: usage[w] for w in vocabulary})
    ear = PR.recogniser()

    def margin(got, word):
        others = [v for w, v in got.items() if not known.alike(w, word)]
        return got[word] - max(others) if others else float("inf")

    named = []      # (margin, worst stretched margin by k, right)
    for row in rows:
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        words = [w for w in row["words"] if w["word"] != "<unk>"]
        marks = ear.marks(y, H.SR)
        for first, last, _, _, _ in SP._mark_decode(marks, known):
            got = SP.mark_scores(marks[first:last + 1], known)
            if not got:
                continue
            best = max(got, key=got.get)
            m = margin(got, best)
            if m < SP.MARK_CLEAR:
                continue
            sounded = [t for t in range(first, last + 1) if int(marks[t].argmax()) != PR.BLANK] or [first]
            at = sounded[0] * PR.STEP
            right = any(known.alike(best, w["word"]) for w in words if w["start"] - 0.3 <= at <= w["end"] + 0.3)
            worst = {0: m}
            for k in STRETCHES[1:]:
                tried = [(max(first - k, 0), last), (first, min(last + k, len(marks) - 1))]
                worst[k] = min([worst[k - 1]] + [margin(SP.mark_scores(marks[a:b + 1], known), best)
                                                 for a, b in tried if (a, b) != (first, last)])
            named.append((m, worst, right, row["id"], best))
    print(f"{len(named)} spans named at a margin of {SP.MARK_CLEAR} ({time.time() - started:.0f} s)", flush=True)
    firm = 0.5 * (SP.MARK_CLEAR + SP.MARK_RESOLVED)
    for k in STRETCHES:
        for need in NEEDS if k else (0.0,):
            held = [(r, i, w) for m, worst, r, i, w in named if m >= firm and worst[k] >= need]
            clear = [(r, i, w) for m, worst, r, i, w in named if worst[k] >= need]
            print(f"  stretched {20 * k:3d} ms, holding by {need:4.1f}: firm {len(held)}, wrong "
                  f"{sum(1 for r, _, _ in held if not r)}; named {len(clear)}, wrong "
                  f"{sum(1 for r, _, _ in clear if not r)}"
                  + (f"; firm and wrong: {[(i, w) for r, i, w in held if not r][:8]}" if k == STRETCHES[-1] else ""),
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
