"""SPEECH-03, offline: the lessons' own sentences, said by speakers never taught by, heard by their sounds and taken
by the listener as the way of hearing them that makes sense.

No recording of the lessons' sentences exists. Each is put together from recordings of its words by untaught
speakers, one clip a word, in order: MSWC test clips (one-second clips of a word said alone, with the quiet around
it), and LibriSpeech test-clean cuts for the short words MSWC does not keep. The words are said by different people,
with pauses where the clips have them: easier to divide into words than one speaker's running speech, and harder
to hear, since every word is a new voice.

Through the substrate's own functions: every second dev-clean sentence taught as a lesson of sounds
(`speech.phones_example`); how the lesson words are said, from the CMU Pronouncing Dictionary with Brown usage
(`speech.SaidAs`); each sentence heard (`speech.heard_by_phones`); where words in it sound alike, the ways of hearing
it handed to the listener (`derived_reader.heard_which`), which reads them with the sandbox's own reader and memory,
read-only. Scored: sentences heard exactly as said; words heard right.

    ./venv_lyric/bin/python3 experiments/SPEECH-03/offline_listener.py [--sentences 100]
"""
import argparse
import asyncio
import glob
import io
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "SPEECH-02"))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
ALIGNED = REPO / "data" / "speech" / "librispeech_alignments"


def lesson_sentences(available):
    """The lessons' sentences of three to seven words, every word with an untaught speaker's recording."""
    out = []
    for path in sorted(glob.glob(str(REPO / "data" / "lessons" / "english_[0-9][0-9].json"))):
        data = json.load(open(path))
        records = data if isinstance(data, list) else data.get("records") or data.get("lessons") or []
        for record in records:
            sentence = record.get("sentence") if isinstance(record, dict) else None
            if not sentence or re.search(r"\d", sentence):
                continue
            words = [w.lower() for w in re.findall(r"[A-Za-z]+(?:'[a-z]+)?", sentence)]
            if 3 <= len(words) <= 7 and all(w in available and available[w]["heard"] for w in words):
                out.append((sentence, tuple(words)))
    return list(dict.fromkeys(out))


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=int, default=100)
    args = parser.parse_args()
    started = time.time()

    library = SP.PhoneLibrary()
    table = pq.read_table(ALIGNED / "dev_clean.parquet", columns=["phonemes", "audio"])
    for k, row in enumerate(table.to_pylist()):
        if k % 2:
            continue
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        told = "|".join(f"{p['phoneme']} {p['start']:.3f} {p['end']:.3f}"
                        for p in row["phonemes"] if p["phoneme"] != "spn")
        frames, labels = SP.phones_example(resample_poly(y, H.SR, rate) if rate != H.SR else y, told)
        library.add(frames, labels)
    print(f"taught: {library.size} frames of {len(library.phones)} phones ({time.time() - started:.0f} s)", flush=True)

    used = lesson_words()
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    words_said = SP.SaidAs({w: [" ".join(way) for way in said[w]] for w in used if w in said},
                           {w: usage[w] for w in used}, library)
    available = clips(set(used), 1, 1)
    picked = lesson_sentences(available)
    rng = np.random.default_rng(20261003)
    picked = [picked[i] for i in sorted(rng.choice(len(picked), size=min(args.sentences, len(picked)), replace=False))]
    print(f"{len(picked)} sentences; {len(words_said.words)} words the ear can hear ({time.time() - started:.0f} s)",
          flush=True)

    from core.database import get_database_manager
    from core.memory import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr
    await get_database_manager().initialize()
    await get_uncertainty_system().load_from_db()
    await (await get_memory_agent()).language_view()

    tally = Counter()
    right_words = total_words = 0
    shown = []
    work = HERE / "work" / "listener"
    for n, (sentence, words) in enumerate(picked):
        parts = []
        for k, w in enumerate(words):
            path = present(available[w]["heard"][0]["path"], work / f"{n}_{k}_{w}.wav", rng)
            parts.append(H.decode(str(path)))
        y = np.concatenate(parts)
        heard = SP.heard_by_phones(y, library, words_said)
        ways = heard.get("heard_texts") or []
        text = heard.get("heard_text") or ""
        if ways:
            choice = await dr.heard_which(ways)
            text = choice or text
            tally["the listener chose" if choice else "the listener could not choose"] += 1
        elif "..." in text or not text:
            tally["something not heard as a word"] += 1
        got = text.replace("...", " ").split()
        right_words += sum(1 for a, b in zip(got, words) if a == b) if len(got) == len(words) else \
            sum(1 for w in set(got) if w in words)
        total_words += len(words)
        exact = got == list(words)
        tally["heard exactly"] += exact
        if len(shown) < 8:
            shown.append((sentence, text, len(ways)))
    n = len(picked)
    print(f"  sentences heard exactly as said: {tally['heard exactly']} of {n}; words heard right {right_words} of "
          f"{total_words}; {dict(tally)} ({time.time() - started:.0f} s)", flush=True)
    for sentence, text, ways in shown:
        print(f"      said: {sentence!r:44s} heard: {text!r} ({ways} ways)", flush=True)
    (HERE / "work" / "offline_listener.json").write_text(json.dumps(
        {"sentences": n, "exact": tally["heard exactly"], "words right": right_words, "words": total_words,
         "tally": dict(tally), "shown": shown}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
