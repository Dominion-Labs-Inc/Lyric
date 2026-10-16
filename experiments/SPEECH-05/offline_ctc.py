"""SPEECH-05, offline: the phone recogniser's sounds read as it reports them, a sharp mark for each sound said with
"nothing new" (its blank) between (connectionist temporal classification; Graves, Fernández, Gomez and Schmidhuber
2006), and words found from them by Lyric: how each is said (CMU Pronouncing Dictionary), the word search, and the
listener choosing what makes sense.

`offline_recogniser.py` read every 20 ms as if a sound filled it, and so read mostly noise between the marks. Here:
  A, B  a stretch whose ends are known is scored against each candidate word by how likely the recogniser is to have
        reported that word's sounds, in order, with blanks between (`torch.nn.functional.ctc_loss`);
  C     a sentence is divided into words in one pass over the words' sounds in that form (each sound, a blank before
        and after it, a blank skipped between two different sounds), each word entered at a cost of its share of real
        text weighed by `--weight`; each span is then scored as in A, named where one word clearly fits best, and the
        likeliest ways handed to the listener (`speech.ranked_texts`, `derived_reader.heard_which`).

No store is written; the sandbox is read for the listener.

    ./venv_lyric/bin/python3 experiments/SPEECH-05/offline_ctc.py [--sentences 100] [--weight 0.5 1 2]
"""
import argparse
import asyncio
import io
import json
import os
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
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
STEP = 0.02                       # the recogniser's frames, in seconds


class Marks:
    """The recogniser's report for a recording, as log-probabilities over the dictionary's 39 phones and the blank
    (the last column), every 20 ms; the flap counts as T and as D, AO is "ɑ" and ZH "ʃ", as TIMIT's 39 join them."""

    def __init__(self):
        import numpy as np
        import torch
        from transformers import AutoModelForCTC, AutoProcessor
        from offline_recogniser import AS_CMU, MODEL
        self.np, self.torch = np, torch
        self.processor = AutoProcessor.from_pretrained(MODEL)
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = AutoModelForCTC.from_pretrained(MODEL).to(self.device).eval()
        vocab = self.processor.tokenizer.get_vocab()
        self.phones = sorted(AS_CMU)
        self.index = {p: i for i, p in enumerate(self.phones)}
        self.blank = len(self.phones)
        columns = np.zeros((self.model.config.vocab_size, len(self.phones) + 1), dtype=np.float32)
        for phone, sounds in AS_CMU.items():
            for sound in sounds:
                columns[vocab[sound], self.index[phone]] = 1.0
        for token in ("[PAD]", " ", "|"):
            columns[vocab[token], self.blank] = 1.0
        self.columns = columns

    def __call__(self, y):
        from scipy.signal import resample_poly
        from core.perception import hearing as H
        np, torch = self.np, self.torch
        y16 = resample_poly(np.asarray(y, dtype=np.float64), 16000, H.SR).astype(np.float32)
        inputs = self.processor(y16, sampling_rate=16000, return_tensors="pt").input_values.to(self.device)
        with torch.no_grad():
            probs = torch.softmax(self.model(inputs).logits[0], dim=-1).float().cpu().numpy()
        return np.log(probs @ self.columns + 1e-8)


class Words:
    """The candidate words, each way of saying it as phone indices, for scoring and for the search."""

    def __init__(self, said_as, used, marks):
        import numpy as np
        from core.perception import speech as SP
        self.ways = {}
        for word, ways in said_as.items():
            for way in ways:
                seq = tuple(marks.index[SP.plain_phone(p)] for p in way.split())
                self.ways.setdefault(word, set()).add(seq)
        self.words = sorted(self.ways)
        self.flat = [(w, seq) for w in self.words for seq in sorted(self.ways[w])]
        total = sum(used.get(w, 0) + 1 for w in self.words)
        self.share = {w: float(np.log((used.get(w, 0) + 1) / total)) for w in self.words}

    def alike(self, a, b):
        return bool(self.ways.get(a, set()) & self.ways.get(b, set()))


def scores(logp, words, marks):
    """How likely the stretch `logp` is to report each candidate word: the best of its ways (CTC, summed over every
    way of placing its sounds and blanks)."""
    import numpy as np
    import torch
    seqs = [seq for _, seq in words.flat]
    T = len(logp)
    lp = torch.tensor(logp, dtype=torch.float32).unsqueeze(1).repeat(1, len(seqs), 1)
    targets = torch.tensor([p for seq in seqs for p in seq], dtype=torch.long)
    loss = torch.nn.functional.ctc_loss(lp, targets, torch.full((len(seqs),), T, dtype=torch.long),
                                        torch.tensor([len(s) for s in seqs], dtype=torch.long),
                                        blank=marks.blank, reduction="none", zero_infinity=False)
    out = {}
    for (word, _), value in zip(words.flat, (-loss).numpy()):
        out[word] = max(out.get(word, -np.inf), float(value))
    return out


def decode(logp, words, marks, weight):
    """How a sentence divides into words: one pass over every way of saying every candidate word in CTC form
    (blank, sound, blank, sound, ..., blank), a word entered from where the last ended at the cost of its share of
    real text times `weight`. `(first frame, last frame, word)` spans."""
    import numpy as np
    sym, word_of, first, last, skip = [], [], [], [], []
    for word, seq in words.flat:
        states = [marks.blank]
        for p in seq:
            states += [p, marks.blank]
        start = len(sym)
        for k, s in enumerate(states):
            sym.append(s)
            word_of.append(word)
            # A sound may follow the sound two states back directly, skipping the blank, when the two differ.
            skip.append(k >= 2 and s != marks.blank and states[k - 2] != s)
        first += [start, start + 1]
        last += [start + len(states) - 1, start + len(states) - 2]
    n = len(sym)
    sym = np.array(sym)
    skip = np.array(skip)
    is_first = np.zeros(n, dtype=bool)
    is_first[first] = True
    starts = np.zeros(n, dtype=bool)
    starts[first[::2]] = True
    is_last = np.zeros(n, dtype=bool)
    is_last[last] = True
    entry = np.array([words.share[w] for w in word_of])
    score = np.full(n, -np.inf)
    begun = np.zeros(n, dtype=int)
    ended = np.full(len(logp) + 1, -np.inf)
    ended[0] = 0.0
    how = [None] * (len(logp) + 1)
    every = np.arange(n)
    for t in range(len(logp)):
        one = np.concatenate([[-np.inf], score[:-1]])
        one[starts] = -np.inf
        two = np.concatenate([[-np.inf, -np.inf], score[:-2]])
        two[~skip] = -np.inf
        enter = np.where(is_first, ended[t] + weight * entry, -np.inf)
        options = np.stack([score, one, two, enter])
        choice = options.argmax(axis=0)
        began = np.stack([begun, np.concatenate([[0], begun[:-1]]), np.concatenate([[0, 0], begun[:-2]]),
                          np.full(n, t)])
        begun = began[choice, every]
        score = options[choice, every] + logp[t, sym]
        ends = np.where(is_last, score, -np.inf)
        best = int(ends.argmax())
        ended[t + 1], how[t + 1] = ends[best], (int(begun[best]), word_of[best])
    spans, t = [], len(logp)
    while t > 0 and how[t] is not None:
        start, word = how[t]
        spans.append((start, t - 1, word))
        t = start
    return spans[::-1]


async def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from nltk.corpus import brown, cmudict
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import speech as SP
    from clips import clips, present
    from fetch_mswc import lesson_words
    from offline_listener import lesson_sentences
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=int, default=100)
    parser.add_argument("--weight", type=float, nargs="+", default=[0.5, 1.0, 2.0])
    args = parser.parse_args()
    started = time.time()
    marks = Marks()
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    used = lesson_words()
    as_said = lambda vocabulary: {w: [" ".join(way) for way in said[w]] for w in vocabulary if w in said}
    report = {}

    # ── A ──
    table = pq.read_table(ALIGNED / "test_clean.parquet", columns=["words", "audio"]).to_pylist()
    right = n = 0
    margins = []
    for k, row in enumerate(table):
        if k % 18:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        spoken = [(w["word"], int(w["start"] / STEP), int(np.ceil(w["end"] / STEP))) for w in row["words"]
                  if w["word"] in said]
        vocabulary = set(used) | {w for w, _, _ in spoken}
        words = Words(as_said(vocabulary), {w: usage[w] for w in vocabulary}, marks)
        logp = marks(y)
        for word, lo, hi in spoken:
            if hi - lo < 1:
                continue
            got = scores(logp[lo:hi + 1], words, marks)
            order = sorted(got, key=got.get, reverse=True)
            best = order[0]
            rival = next((w for w in order if not words.alike(w, best)), None)
            ok = words.alike(best, word)
            right += ok
            n += 1
            margins.append((got[best] - got[rival], ok))
    curve = [(cut, sum(1 for m, _ in margins if m >= cut), sum(ok for m, ok in margins if m >= cut))
             for cut in (0.0, 2.0, 5.0, 10.0, 20.0)]
    report["A"] = {"right": f"{right}/{n}", "curve": curve}
    print(f"  A. words in untaught speakers' sentences: best fit right {100 * right / n:.1f}% of {n}; named and "
          f"right at each margin (log): {curve} ({time.time() - started:.0f} s)", flush=True)

    # ── B ──
    lesson = Words(as_said(used), {w: usage[w] for w in used}, marks)
    available = clips(set(used), 1, 3)
    top = [w for w in sorted(used, key=lambda w: (-used[w], w))
           if w in available and len(available[w]["heard"]) == 3 and w in lesson.ways][:100]
    rng = np.random.default_rng(20261003)
    right = n = 0
    for w in top:
        for k, c in enumerate(available[w]["heard"]):
            path = present(c["path"], REPO / "experiments" / "SPEECH-02" / "work" / "offline" / "heard" / w / f"{k}.wav", rng)
            got = scores(marks(H.decode(str(path))), lesson, marks)
            best = max(got, key=got.get)
            right += lesson.alike(best, w)
            n += 1
    report["B"] = f"{right}/{n}"
    print(f"  B. MSWC words said alone, among {len(lesson.words)} lesson words: best fit right {100 * right / n:.1f}% "
          f"of {n} ({time.time() - started:.0f} s)", flush=True)

    # ── C ──
    from core.database import get_database_manager
    from core.memory import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr
    await get_database_manager().initialize()
    await get_uncertainty_system().load_from_db()
    await (await get_memory_agent()).language_view()
    available = clips(set(used), 1, 1)
    picked = lesson_sentences(available)
    rng = np.random.default_rng(20261003)
    picked = [picked[i] for i in sorted(rng.choice(len(picked), size=min(args.sentences, len(picked)), replace=False))]
    heard_marks = []
    for n_, (sentence, spoken) in enumerate(picked):
        parts = [H.decode(str(present(available[w]["heard"][0]["path"],
                                      REPO / "experiments" / "SPEECH-03" / "work" / "listener" / f"{n_}_{k}_{w}.wav", rng)))
                 for k, w in enumerate(spoken)]
        heard_marks.append(marks(np.concatenate(parts)))
    for weight in args.weight:
        tally = Counter()
        right_words = total_words = 0
        shown = []
        for (sentence, spoken), logp in zip(picked, heard_marks):
            spans = []
            for lo, hi, _ in decode(logp, lesson, marks, weight):
                got = scores(logp[lo:hi + 1], lesson, marks)
                order = sorted(got, key=got.get, reverse=True)
                best = order[0]
                near = []
                for w in order:
                    if not any(lesson.alike(w, o) for o in near):
                        near.append(w)
                    if len(near) == SP.PHONE_CANDIDATES:
                        break
                frames = hi - lo + 1
                margin = got[near[0]] - got[near[1]] if len(near) > 1 else float("inf")
                span = {"word": None, "starts_at": lo * STEP, "ends_at": (hi + 1) * STEP}
                if margin >= 5.0:
                    span.update(word=best, standing=1.0)
                else:
                    span["close"] = near
                    span["behind"] = [round((got[near[0]] - got[w]) / max(frames, 1) / 2, 3) for w in near]
                spans.append(span)
            text = SP.said_text(spans)
            ways = SP.ranked_texts(spans) if any(s.get("close") for s in spans) else []
            if ways:
                choice = await dr.heard_which(ways)
                text = choice or ways[0]
                tally["the listener chose" if choice else "the listener could not choose; the likeliest way"] += 1
            got_words = text.replace("...", " ").split()
            right_words += sum(1 for a, b in zip(got_words, spoken) if a == b) if len(got_words) == len(spoken) \
                else sum(1 for w in set(got_words) if w in spoken)
            total_words += len(spoken)
            tally["heard exactly"] += got_words == list(spoken)
            if len(shown) < 10:
                shown.append((sentence, text))
        report[f"C weight {weight}"] = {"exact": tally["heard exactly"], "of": len(picked),
                                        "words right": f"{right_words}/{total_words}", "tally": dict(tally),
                                        "shown": shown}
        print(f"  C. the lessons' sentences, usage weighed {weight}: heard exactly {tally['heard exactly']} of "
              f"{len(picked)}; words right {right_words} of {total_words}; {dict(tally)} "
              f"({time.time() - started:.0f} s)", flush=True)
        for sentence, text in shown[:6]:
            print(f"      said: {sentence!r:44s} heard: {text!r}", flush=True)
    (HERE / "work").mkdir(exist_ok=True)
    (HERE / "work" / "offline_ctc.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
