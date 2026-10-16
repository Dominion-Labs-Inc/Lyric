"""SPEECH-05, offline: a trained phone recogniser as the ear's sense of which sounds were said, and everything else
Lyric's own.

Model-free hearing tells English sounds apart about half the time (SPEECH-03), too seldom to hear a sentence. A
phone recogniser (wav2vec2 XLS-R, fine-tuned on TIMIT's phones: `vitouphy/wav2vec2-xls-r-300m-timit-phoneme`,
Apache-2.0) reports, every 20 ms, how much each of 39 English sounds was said. It holds no words and no language
model, and takes no intelligence from Lyric (the reading of the rule, 2026-10-03). Here its sounds replace Lyric's
frame matching (`speech.find_words_by_phones`, `sounds`), and the rest is as before: how each word is said (CMU
Pronouncing Dictionary), the one-pass word search, and the listener choosing what makes sense
(`derived_reader.heard_which`).

No store is written. The same three measures Lyric's own frame matching was taken on:
  A  words cut from untaught speakers' LibriSpeech test-clean sentences, among the lesson words and every word said
     (SPEECH-03 `offline_margins.py`: 51.9% best fit);
  B  MSWC's lesson words said alone through people's own microphones, among the 900 lesson words (about 22%);
  C  the lessons' own sentences, each word by an untaught voice, heard and chosen by the listener (0 of 100).

    ./venv_lyric/bin/python3 experiments/SPEECH-05/offline_recogniser.py [--sentences 100]
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
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-03"))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"
MODEL = "vitouphy/wav2vec2-xls-r-300m-timit-phoneme"

#: The recogniser's sounds, written in the IPA, as the CMU Pronouncing Dictionary writes them. TIMIT's 39 join "ɔ"
#: with "ɑ" and "ʒ" with "ʃ", so AO and ZH take those; the flap "ɾ" is a T or a D.
AS_CMU = {"AA": ["ɑ"], "AO": ["ɑ"], "AE": ["æ"], "AH": ["ə"], "AW": ["aʊ"], "AY": ["aɪ"], "B": ["b"], "CH": ["ʧ"],
          "D": ["d", "ɾ"], "DH": ["ð"], "EH": ["ɛ"], "ER": ["ɝ"], "EY": ["eɪ"], "F": ["f"], "G": ["g"], "HH": ["h"],
          "IH": ["ɪ"], "IY": ["i"], "JH": ["ʤ"], "K": ["k"], "L": ["l"], "M": ["m"], "N": ["n"], "NG": ["ŋ"],
          "OW": ["oʊ"], "OY": ["ɔɪ"], "P": ["p"], "R": ["ɹ"], "S": ["s"], "SH": ["ʃ"], "T": ["t", "ɾ"], "TH": ["θ"],
          "UH": ["ʊ"], "UW": ["u"], "V": ["v"], "W": ["w"], "Y": ["j"], "Z": ["z"], "ZH": ["ʃ"]}


class Index:
    """The phones words are said in, for `speech.SaidAs`: the dictionary's 39 and quiet."""

    def __init__(self):
        from core.perception import speech as SP
        self.phones = sorted(AS_CMU) + [SP.QUIET]
        self.index = {p: i for i, p in enumerate(self.phones)}
        self.size = 1


class Recogniser:
    """How much each of the dictionary's phones sounds said in every 10 ms of a recording, from the phone
    recogniser: of what is said in each of its 20 ms frames (the share not its blank), each sound's part."""

    def __init__(self, index: Index):
        import numpy as np
        import torch
        from transformers import AutoModelForCTC, AutoProcessor
        self.np, self.torch = np, torch
        self.processor = AutoProcessor.from_pretrained(MODEL)
        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = AutoModelForCTC.from_pretrained(MODEL).to(self.device).eval()
        vocab = self.processor.tokenizer.get_vocab()
        self.columns = np.zeros((self.model.config.vocab_size, len(index.phones)), dtype=np.float32)
        for phone, sounds in AS_CMU.items():
            for sound in sounds:
                self.columns[vocab[sound], index.index[phone]] = 1.0
        self.sounds_at = [vocab[s] for s in {s for each in AS_CMU.values() for s in each}]
        self.quiet = index.index["sil"]

    def __call__(self, y):
        """`y` at the hearing's rate (22,050 Hz) -> log of each phone a 10 ms frame, on the ear's grid."""
        from scipy.signal import resample_poly
        from core.perception import hearing as H
        from core.perception import speech as SP
        np, torch = self.np, self.torch
        y16 = resample_poly(np.asarray(y, dtype=np.float64), 16000, H.SR).astype(np.float32)
        inputs = self.processor(y16, sampling_rate=16000, return_tensors="pt").input_values.to(self.device)
        with torch.no_grad():
            probs = torch.softmax(self.model(inputs).logits[0], dim=-1).float().cpu().numpy()
        said = probs[:, self.sounds_at].sum(axis=1, keepdims=True) + 1e-6
        share = probs @ self.columns / said
        share[:, self.quiet] = 1.0 / share.shape[1]
        frames = int(len(y) // SP._HOP) + 1
        at = np.minimum((np.arange(frames) * SP._HOP / H.SR / 0.02).astype(int), len(share) - 1)
        return np.log(share[at] + 1e-4)


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
    args = parser.parse_args()
    started = time.time()
    index = Index()
    hear = Recogniser(index)
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    used = lesson_words()
    print(f"recogniser on {hear.device} ({time.time() - started:.0f} s)", flush=True)
    report = {}

    # ── A. words in untaught speakers' sentences ──
    table = pq.read_table(ALIGNED / "test_clean.parquet", columns=["words", "audio"]).to_pylist()
    right = n = 0
    margins = []
    for k, row in enumerate(table):
        if k % 18:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        spoken = [(w["word"], int(w["start"] * H.SR / SP._HOP), int(np.ceil(w["end"] * H.SR / SP._HOP)))
                  for w in row["words"] if w["word"] in said]
        vocabulary = set(used) | {w for w, _, _ in spoken}
        words = SP.SaidAs({w: [" ".join(way) for way in said[w]] for w in vocabulary if w in said},
                          {w: usage[w] for w in vocabulary}, index)
        logp = hear(y)
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
    curve = [(cut, sum(1 for m, _ in margins if m >= cut), sum(ok for m, ok in margins if m >= cut))
             for cut in (0.0, 0.25, 0.5, 1.0, 2.0)]
    report["A words in sentences"] = {"right": f"{right}/{n}", "curve (cut, named, right)": curve}
    print(f"  A. words in untaught speakers' sentences: best fit right {100 * right / n:.1f}% of {n}; "
          f"named and right at each margin: {curve} ({time.time() - started:.0f} s)", flush=True)

    # ── B. MSWC words said alone ──
    lesson_said = SP.SaidAs({w: [" ".join(way) for way in said[w]] for w in used if w in said},
                            {w: usage[w] for w in used}, index)
    available = clips(set(used), 1, 3)
    top = [w for w in sorted(used, key=lambda w: (-used[w], w))
           if w in available and len(available[w]["heard"]) == 3 and w in lesson_said.word_index][:100]
    rng = np.random.default_rng(20261003)
    right = n = 0
    for w in top:
        for k, c in enumerate(available[w]["heard"]):
            path = present(c["path"], REPO / "experiments" / "SPEECH-02" / "work" / "offline" / "heard" / w / f"{k}.wav", rng)
            y = np.asarray(H.decode(str(path)), dtype=np.float64)
            lo, hi, _ = SP._extent(y)
            logp = hear(y)[lo:hi]
            fits = SP._phone_fits(logp, lesson_said)
            best = lesson_said.words[int(np.argmax(fits))]
            right += lesson_said.alike(best, w)
            n += 1
    report["B MSWC words alone"] = f"{right}/{n}"
    print(f"  B. MSWC words said alone, among {len(lesson_said.words)} lesson words: best fit right "
          f"{100 * right / n:.1f}% of {n} ({time.time() - started:.0f} s)", flush=True)

    # ── C. the lessons' sentences, the listener choosing ──
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
    tally = Counter()
    right_words = total_words = 0
    shown = []
    for n_, (sentence, words) in enumerate(picked):
        parts = [H.decode(str(present(available[w]["heard"][0]["path"],
                                      REPO / "experiments" / "SPEECH-03" / "work" / "listener" / f"{n_}_{k}_{w}.wav", rng)))
                 for k, w in enumerate(words)]
        y = np.concatenate(parts)
        heard = SP.heard_by_phones(y, index, lesson_said, sounds=hear)
        ways = heard.get("heard_texts") or []
        text = heard.get("heard_text") or ""
        if ways:
            choice = await dr.heard_which(ways)
            text = choice or text
            tally["the listener chose" if choice else "the listener could not choose"] += 1
        got = text.replace("...", " ").split()
        right_words += sum(1 for a, b in zip(got, words) if a == b) if len(got) == len(words) else \
            sum(1 for w in set(got) if w in words)
        total_words += len(words)
        tally["heard exactly"] += got == list(words)
        if len(shown) < 10:
            shown.append((sentence, text))
    report["C lesson sentences"] = {"exact": tally["heard exactly"], "of": len(picked),
                                    "words right": f"{right_words}/{total_words}", "tally": dict(tally), "shown": shown}
    print(f"  C. the lessons' sentences: heard exactly {tally['heard exactly']} of {len(picked)}; words right "
          f"{right_words} of {total_words}; {dict(tally)} ({time.time() - started:.0f} s)", flush=True)
    for sentence, text in shown:
        print(f"      said: {sentence!r:44s} heard: {text!r}", flush=True)
    (HERE / "work").mkdir(exist_ok=True)
    (HERE / "work" / "offline_recogniser.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
