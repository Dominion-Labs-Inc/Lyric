"""SPEECH-03, offline: words said by a voice the sounds were also taught from.

Hearing by sounds carries a word to a voice never heard only about half the time (`offline_margins.py`), too seldom
for a sentence. Lyric listens to its own people, and a person can teach their own voice by reading sentences aloud.
Here, for each of five dev-clean speakers: the sounds are taught from half that speaker's sentences, beside every
second sentence of the other dev-clean speakers (`speech.phones_example`), and words cut from the speaker's OTHER
half are fitted among the lesson words and every word said (`speech._phone_fits`). Scored as `offline_margins.py`
scores: the best fit is the word said, or one said the same; and how far ahead it fits when it is right and wrong.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_same_speaker.py [--speakers 5]
"""
import argparse
import io
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
#: Taught from the speaker's own sentences alone, with no other voice (`ONLY_OWN=1`).
ONLY_OWN = bool(int(__import__("os").environ.get("ONLY_OWN", "0")))


def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from nltk.corpus import brown, cmudict
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import speech as SP
    from fetch_mswc import lesson_words
    parser = argparse.ArgumentParser()
    parser.add_argument("--speakers", type=int, default=5)
    args = parser.parse_args()
    started = time.time()
    table = pq.read_table(ALIGNED / "dev_clean.parquet", columns=["id", "words", "phonemes", "audio"]).to_pylist()
    by_speaker = defaultdict(list)
    for k, row in enumerate(table):
        by_speaker[row["id"].split("-")[0]].append(k)
    lessons = {}

    def lesson(k):
        if k not in lessons:
            row = table[k]
            y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
            y = resample_poly(y, H.SR, rate) if rate != H.SR else y
            told = "|".join(f"{p['phoneme']} {p['start']:.3f} {p['end']:.3f}"
                            for p in row["phonemes"] if p["phoneme"] != "spn")
            lessons[k] = (y, SP.phones_example(y, told))
        return lessons[k]

    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    report = {}
    speakers = sorted(by_speaker)[:args.speakers]
    totals = Counter()
    for speaker in speakers:
        mine = by_speaker[speaker]
        teach_mine, hear_mine = mine[::2], mine[1::2]
        library = SP.PhoneLibrary()
        if not ONLY_OWN:
            for k in range(0, len(table), 2):
                if table[k]["id"].split("-")[0] != speaker:
                    library.add(*lesson(k)[1])
        others = library.size
        for k in teach_mine:
            library.add(*lesson(k)[1])
        right = n = 0
        margins = []
        for k in hear_mine:
            row = table[k]
            y = lesson(k)[0]
            spoken = [(w["word"], int(w["start"] * H.SR / SP._HOP), int(np.ceil(w["end"] * H.SR / SP._HOP)))
                      for w in row["words"] if w["word"] in said]
            vocabulary = set(lesson_words()) | {w for w, _, _ in spoken}
            words = SP.SaidAs({w: [" ".join(way) for way in said[w]] for w in vocabulary if w in said},
                              {w: usage[w] for w in vocabulary}, library)
            logp = library.sounds_like(SP.phone_frames(SP.band_energies(y)))
            for word, lo, hi in spoken:
                if hi - lo < SP.SHORTEST_PHONE or word not in words.word_index:
                    continue
                fits = SP._phone_fits(logp[lo:hi + 1], words)
                order = [words.words[i] for i in np.argsort(-fits) if np.isfinite(fits[i])]
                best = order[0]
                rival = next((w for w in order if not words.alike(w, best)), None)
                ok = words.alike(best, word)
                right += ok
                n += 1
                margins.append(((fits[words.word_index[best]] - fits[words.word_index[rival]]) / (hi - lo + 1), ok))
        named = [ok for m, ok in margins if m >= SP.PHONE_CLEAR]
        firm = [ok for m, ok in margins if m >= (SP.PHONE_CLEAR + SP.PHONE_RESOLVED) / 2]
        report[speaker] = {"best fit right": f"{right}/{n}", "named": f"{sum(named)}/{len(named)}",
                           "firm": f"{sum(firm)}/{len(firm)}", "own frames": library.size - others}
        totals.update(right=right, n=n, named=len(named), named_right=sum(named), firm=len(firm), firm_right=sum(firm))
        print(f"  speaker {speaker}: {library.size - others} frames of their own beside {others}; best fit right "
              f"{100 * right / max(n, 1):.1f}% of {n}; named {len(named)}, right {sum(named)}; firm {len(firm)}, "
              f"right {sum(firm)} ({time.time() - started:.0f} s)", flush=True)
    print(f"  all: best fit right {100 * totals['right'] / totals['n']:.1f}% of {totals['n']}; named "
          f"{totals['named']} ({100 * totals['named'] / totals['n']:.1f}%), right {totals['named_right']}; firm "
          f"{totals['firm']}, right {totals['firm_right']}", flush=True)
    (HERE / "work" / "offline_same_speaker.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
