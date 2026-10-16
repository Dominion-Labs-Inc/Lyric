"""SPEECH-05, offline: why words said alone are heard right less often in the substrate (SPEECH-05 C) than offline
(`offline_ctc.py` B, 51.0%). The same 300 clips, as the experiment presented them, heard four ways:

  told one word   the recogniser's report of the whole clip, the best-fitting word among the candidates (offline B);
  whole           the whole clip's report divided into words (`speech._mark_decode`), as nothing tells it one word;
  speech only     the report of only the stretch that is speech (`speech._extent`), divided (the substrate's way);
  speech, padded  the report of the whole clip, divided only over the stretch that is speech.

Candidates: the 1,863 words SPEECH-05 teaches (the lesson words and every word of the sentences it hears).

    ./venv_lyric/bin/python3 experiments/SPEECH-05/offline_alone.py
"""
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))


def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    from nltk.corpus import brown, cmudict
    from core.perception import hearing as H
    from core.perception import phone_recogniser as PR
    from core.perception import speech as SP
    from clips import clips
    from fetch_mswc import lesson_words
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    used = lesson_words()
    table = pq.read_table(REPO / "data" / "speech" / "librispeech_alignments" / "test_clean.parquet",
                          columns=["words"]).to_pylist()
    vocabulary = set(used) | {w["word"] for k, row in enumerate(table) if not k % 18 for w in row["words"]}
    known = SP.SaidInMarks({w: [" ".join(x) for x in said[w]] for w in vocabulary if w in said},
                           {w: usage[w] for w in vocabulary})
    print(f"{len(known.words)} candidate words", flush=True)
    ear = PR.recogniser()
    available = clips(set(used), 1, 3)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w)) if w in available
             and len(available[w]["heard"]) == 3 and w in known.ways][:100]
    tally = Counter()
    pieces = Counter()
    for w in words:
        for k in range(3):
            y = np.asarray(H.decode(str(HERE / "work" / "heard" / w / f"{k}.wav")), dtype=np.float64)
            lo, hi, _ = SP._extent(y)
            whole = ear.marks(y, SP.SR)
            got = SP.mark_scores(whole, known)
            tally["told one word"] += known.alike(max(got, key=got.get), w)
            found = [x for _, _, x, _, _ in SP._mark_decode(whole, known)]
            tally["whole"] += any(known.alike(x, w) for x in found)
            pieces[len(found)] += 1
            inside = ear.marks(y[lo * SP._HOP:hi * SP._HOP], SP.SR)
            tally["speech only"] += any(known.alike(x, w) for _, _, x, _, _ in SP._mark_decode(inside, known))
            a = int(lo * SP._HOP / SP.SR / PR.STEP)
            b = int(np.ceil(hi * SP._HOP / SP.SR / PR.STEP))
            tally["speech, padded"] += any(known.alike(x, w) for _, _, x, _, _ in SP._mark_decode(whole[a:b], known))
            tally["clips"] += 1
    print({k: f"{v} ({100 * v / tally['clips']:.1f}%)" for k, v in tally.items()}, flush=True)
    print(f"words the whole clip was divided into: {dict(sorted(pieces.items()))}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
