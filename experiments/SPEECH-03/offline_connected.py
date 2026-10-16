"""SPEECH-03, offline: whole sentences said by untaught speakers, heard by their sounds with no word boundary given.

`experiment.py` fits a stretch whose ends are known. Speech does not come with its words marked. Here a whole
utterance is divided into words in one pass (Vintsyuk; Bridle; Ney: the search the ear's `speech._decode` already
runs over whole-word examples), over the phones of every candidate word: at each frame a word's phone goes on, or
gives way to its next phone (each lasting at least `phones.SHORTEST` frames), and a word's last phone gives way to any word's first, or to quiet.

Left to the sounds alone, the search breaks a long word into short ones that fit a little better. A word is also
more or less likely before anything is heard: how often real text uses it. Each word entered costs the log of its
share of the Brown corpus's words, weighed against the sounds by `--weight` (frames 10 ms apart say much the same
thing, so the sounds' sum counts every phone several times over).

No store and no substrate. Scored against what was said: words right, put in, left out and taken for another.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_connected.py [--utterances 60] [--weight 0 4 8 12]
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


def aligned(said, heard):
    """Words right, taken for another, left out and put in: the fewest changes that turn what was heard into what
    was said (Levenshtein 1966)."""
    n, m = len(said), len(heard)
    cost = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]
    total = lambda c: c[1] + c[2] + c[3]
    for i in range(1, n + 1):
        cost[i][0] = (0, 0, i, 0)
    for j in range(1, m + 1):
        cost[0][j] = (0, 0, 0, j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            a, b, c = cost[i - 1][j - 1], cost[i - 1][j], cost[i][j - 1]
            same = said[i - 1] == heard[j - 1]
            options = [(a[0] + same, a[1] + (not same), a[2], a[3]), (b[0], b[1], b[2] + 1, b[3]),
                       (c[0], c[1], c[2], c[3] + 1)]
            cost[i][j] = min(options, key=total)
    return cost[n][m]


def main() -> int:
    import numpy as np
    from nltk.corpus import brown, cmudict
    import phones as P
    from fetch_mswc import lesson_words
    parser = argparse.ArgumentParser()
    parser.add_argument("--utterances", type=int, default=60)
    parser.add_argument("--weight", type=float, nargs="+", default=[0.0, 4.0, 8.0, 12.0])
    args = parser.parse_args()
    started = time.time()
    taught = P.Taught()
    heard = P.utterances("test_clean", 9)[:args.utterances]
    said = cmudict.dict()
    spoken = Counter(w for _, _, _, words in heard for w, _, _ in words)
    vocabulary = sorted(w for w in set(spoken) | set(lesson_words()) if w in said
                        and all(P.plain(p) in taught.index for way in said[w] for p in way))
    unknown = sum(n for w, n in spoken.items() if w not in vocabulary)
    usage = Counter(w.lower() for w in brown.words())
    total = sum(usage[w] + 1 for w in vocabulary)
    prior = {w: float(np.log((usage[w] + 1) / total)) for w in vocabulary}

    # Every phone of every way of saying every word is a state, in order; quiet is the last state.
    phone_of, word_of, first, last, stays = [], [], [], [], []
    for w in vocabulary:
        for way in sorted({tuple(P.plain(p) for p in way) for way in said[w]}):
            first.append(len(phone_of))
            states, stay = P.chained(way, taught.index)
            phone_of += states
            stays += stay
            word_of += [w] * len(states)
            last.append(len(phone_of) - 1)
    quiet = len(phone_of)
    phone_of = np.array(phone_of + [taught.index["sil"]])
    stays = np.array(stays + [True])
    is_first = np.zeros(quiet + 1, dtype=bool)
    is_first[first] = True
    is_last = np.zeros(quiet + 1, dtype=bool)
    is_last[last] = True
    entry = np.array([prior[w] for w in word_of] + [0.0])
    everything = np.arange(quiet + 1)
    print(f"taught: {len(taught.frames)} frames; {len(heard)} utterances, {sum(spoken.values())} words said "
          f"({unknown} of words the dictionary does not hold); {len(vocabulary)} candidate words, {quiet} states "
          f"({time.time() - started:.0f} s)", flush=True)

    def decode(logp, weight):
        score = np.full(quiet + 1, -np.inf)
        begun = np.zeros(quiet + 1, dtype=int)
        ended = np.full(len(logp) + 1, -np.inf)       # the best way of having ended a word, or quiet, before frame t
        ended[0] = 0.0
        how = [None] * (len(logp) + 1)
        for t in range(len(logp)):
            on = np.concatenate([[-np.inf], score[:-1]])
            on[is_first] = -np.inf
            on[quiet] = -np.inf
            enter = np.where(is_first, ended[t] + weight * entry, -np.inf)
            enter[quiet] = ended[t]
            options = np.stack([np.where(stays, score, -np.inf), on, enter])
            choice = options.argmax(axis=0)
            began = np.stack([begun, np.concatenate([[0], begun[:-1]]), np.full(quiet + 1, t)])
            begun = began[choice, everything]
            score = options[choice, everything] + logp[t, phone_of]
            ends = np.where(is_last, score, -np.inf)
            best = int(ends.argmax())
            if ends[best] >= score[quiet]:
                ended[t + 1], how[t + 1] = ends[best], (int(begun[best]), word_of[best])
            else:
                ended[t + 1] = score[quiet]
        words, t = [], len(logp)
        while t > 0:
            if how[t] is None:
                t -= 1
            else:
                t, word = how[t]
                words.append(word)
        return words[::-1]

    posteriors = [taught.sounds_like(P.measured(bands)) for _, bands, _, _ in heard]
    print(f"heard: {sum(len(p) for p in posteriors)} frames ({time.time() - started:.0f} s)", flush=True)
    report = {}
    for weight in args.weight:
        right = other = out = put = 0
        example = None
        for (_, _, _, words), logp in zip(heard, posteriors):
            truth = [w for w, _, _ in words]
            found = decode(logp, weight)
            r, s, d, i = aligned(truth, found)
            right, other, out, put = right + r, other + s, out + d, put + i
            example = example or (" ".join(truth[:12]), " ".join(found[:12]))
        n = right + other + out
        report[weight] = {"right": right, "for another": other, "left out": out, "put in": put, "said": n}
        print(f"  usage weighed {weight:4.1f}: right {100 * right / n:.1f}% of {n} words said; taken for another "
              f"{other}, left out {out}, put in {put} ({time.time() - started:.0f} s)\n"
              f"      said:  {example[0]}\n      heard: {example[1]}", flush=True)
    (P.WORK / "offline_connected.json").write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
