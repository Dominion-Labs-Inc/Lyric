"""SPEECH-03, offline: the sounds taught again from words heard through people's own microphones.

The phones were taught from read audiobooks, and words said alone through Common Voice's microphones are heard far
worse (22%) than words in LibriSpeech's sentences (62%). Lyric learns a word by hearing it said and being told which
word it was. Here each MSWC teaching clip (dev and train, never a test speaker) is fitted to its word's phones with
what is already taught (`Taught.align`), each frame takes the phone the fit gives it, and those frames are kept as
taught too. Nothing is trained: more examples are kept, each with the phone its own fit says. Then the MSWC test
clips and LibriSpeech's sentence words are heard again.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_mswc.py [--words 100] [--speakers 20 50]
"""
import argparse
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


def main() -> int:
    import numpy as np
    from nltk.corpus import cmudict
    from core.perception import hearing as H
    from core.perception import speech as SP
    import phones as P
    from clips import clips, present
    from fetch_mswc import lesson_words
    parser = argparse.ArgumentParser()
    parser.add_argument("--words", type=int, default=100)
    parser.add_argument("--speakers", type=int, nargs="+", default=[20, 50])
    args = parser.parse_args()
    started = time.time()
    rng = np.random.default_rng(20261003)
    said = cmudict.dict()
    used = lesson_words()
    available = clips(set(used), max(args.speakers), 3)
    words = [w for w in sorted(used, key=lambda w: (-used[w], w))
             if w in available and len(available[w]["heard"]) == 3 and w in said][:args.words]
    ways = {w: [[P.plain(p) for p in way] for way in said[w]] for w in words}
    work = REPO / "experiments" / "SPEECH-02" / "work" / "offline"

    def word_frames(clip, role, w, k):
        y = np.asarray(H.decode(str(present(clip["path"], work / role / w / f"{k}.wav", rng))), dtype=np.float64)
        lo, hi, _ = SP._extent(y)
        return P.measured(P.energies(y)[lo:hi])

    tests = [(w, word_frames(c, "heard", w, k)) for w in words for k, c in enumerate(available[w]["heard"])]
    sentences = []
    per = Counter()
    for _, bands, _, spoken in P.utterances("test_clean", 9):
        frames = None
        for word, lo, hi in spoken:
            if word in ways and per[word] < 5 and hi - lo >= 5:
                per[word] += 1
                frames = P.measured(bands) if frames is None else frames
                sentences.append((word, frames[lo:hi + 1]))
    said_as = {w: {tuple(way) for way in ws} for w, ws in ways.items()}
    alike = lambda a, b: bool(said_as[a] & said_as[b])

    def score(taught, heard):
        near = top5 = 0
        for w, frames in heard:
            logp = taught.sounds_like(frames)
            fits = {c: max(taught.fit(logp, way) for way in ways[c]) for c in words}
            order = sorted(fits, key=fits.get, reverse=True)
            near += alike(order[0], w)
            top5 += any(alike(o, w) for o in order[:5])
        return round(100 * near / len(heard), 1), round(100 * top5 / len(heard), 1)

    report = {}
    taught = P.Taught()
    print(f"taught from LibriSpeech: {len(taught.frames)} frames ({time.time() - started:.0f} s)", flush=True)
    report["LibriSpeech only"] = {"MSWC alone": score(taught, tests), "in sentences": score(taught, sentences)}
    print(f"  LibriSpeech only: MSWC words alone {report['LibriSpeech only']['MSWC alone']}, "
          f"in sentences {report['LibriSpeech only']['in sentences']} ({time.time() - started:.0f} s)", flush=True)
    done = 0
    for speakers in sorted(args.speakers):
        kept, names, refused = [], [], 0
        for w in words:
            for k, clip in enumerate(available[w]["teach"][done:speakers], start=done):
                frames = word_frames(clip, "teach", w, k)
                logp = taught.sounds_like(frames)
                best = max(ways[w], key=lambda way: taught.fit(logp, way))
                phones = taught.align(logp, best)
                if phones is None:
                    refused += 1
                    continue
                labels = np.array(phones, dtype=object)
                for phone in sorted(set(labels)):
                    at = np.flatnonzero(labels == phone)
                    for i in rng.choice(at, size=min(len(at), 4), replace=False):
                        kept.append(frames[i])
                        names.append(phone)
        taught.add(np.array(kept), names)
        done = speakers
        report[f"with MSWC, {speakers} speakers a word"] = {"MSWC alone": score(taught, tests),
                                                           "in sentences": score(taught, sentences),
                                                           "frames added": len(kept), "clips too short": refused}
        print(f"  with MSWC teaching clips, {speakers} speakers a word ({len(taught.frames)} frames, "
              f"{refused} too short): MSWC words alone {report[f'with MSWC, {speakers} speakers a word']['MSWC alone']}, "
              f"in sentences {report[f'with MSWC, {speakers} speakers a word']['in sentences']} "
              f"({time.time() - started:.0f} s)", flush=True)
    (P.WORK / "offline_mswc.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
