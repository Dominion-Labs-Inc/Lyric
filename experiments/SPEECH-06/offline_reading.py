"""SPEECH-06, offline: why the listener settles so little of what the ear hears (SPEECH-05: it chose in 12 of 143
sentences, and worse than the likeliest way where it did). The listener (`derived_reader.heard_which`) takes only
ways of hearing whose every utterance reads; so for each of SPEECH-05's 146 LibriSpeech sentences, heard as the
substrate hears them (`speech.find_words_by_marks`, `ranked_texts`):

  - does what was said read whole;
  - how many of its words the reader has at all (`PatternInventory.knows`);
  - is what was said among the ways the ear hands on;
  - how many ways read whole, and in how many sentences any does;
  - words right in the likeliest way, and in the best of the ways (what a listener choosing perfectly would get).

Reading in parts (`read_text(parts=True)`, every stretch of the sentence) took about 4 minutes a sentence for two
texts, so it is not used here.

Read with the sandbox's language as taught (its store is only read). The ways are kept in `work/ways.json`.

    ./venv_lyric/bin/python3 experiments/SPEECH-06/offline_reading.py [--sentences 146]
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
WAYS = HERE / "work" / "ways.json"


def heard_ways(most: int):
    """`[(said, likeliest, ways)]` for every 18th test-clean sentence, as SPEECH-05 heard them."""
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    from nltk.corpus import brown, cmudict
    from scipy.signal import resample_poly
    from core.perception import hearing as H
    from core.perception import phone_recogniser as PR
    from core.perception import speech as SP
    from fetch_mswc import lesson_words
    table = pq.read_table(REPO / "data" / "speech" / "librispeech_alignments" / "test_clean.parquet",
                          columns=["words", "audio"]).to_pylist()
    rows = [row for k, row in enumerate(table) if not k % 18][:most]
    said = cmudict.dict()
    usage = Counter(w.lower() for w in brown.words())
    vocabulary = set(lesson_words()) | {w["word"] for row in rows for w in row["words"]}
    known = SP.SaidInMarks({w: [" ".join(x) for x in said[w]] for w in vocabulary if w in said},
                           {w: usage[w] for w in vocabulary})
    ear = PR.recogniser()
    out = []
    for row in rows:
        y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
        y = resample_poly(y, H.SR, rate) if rate != H.SR else y
        heard = SP.heard_by_marks(np.asarray(y, dtype=np.float64), ear, known)
        ways = heard.get("heard_texts") or ([heard["heard_text"]] if heard.get("heard_text") else [])
        out.append((" ".join(w["word"] for w in row["words"] if w["word"] != "<unk>"), ways[0] if ways else "", ways))
    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentences", type=int, default=146)
    args = parser.parse_args()
    started = time.time()
    if not WAYS.exists():
        WAYS.write_text(json.dumps(heard_ways(146), indent=1))
    heard = json.loads(WAYS.read_text())[:args.sentences]
    print(f"{len(heard)} sentences heard ({time.time() - started:.0f} s)", flush=True)
    from core.database import get_database_manager
    from core.memory import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr
    from offline_connected import aligned
    await get_database_manager().initialize()
    await get_database_manager().assert_database_identity("lyric_dev")
    await get_uncertainty_system().load_from_db()
    await (await get_memory_agent()).language_view()
    tally = Counter()
    right = Counter()
    unknown = Counter()
    view = dr._live_inventory()
    for k, (truth, likeliest, ways) in enumerate(heard):
        tally["what was said reads whole"] += all(u.understood for u in dr.read_text(truth))
        words = truth.split()
        tally["words said"] += len(words)
        tally["of them, words the reader has"] += sum(1 for w in words if view.knows(w))
        unknown.update(w for w in words if not view.knows(w))
        tally["what was said is among the ways"] += truth in ways
        tally["what was said is the likeliest"] += truth == likeliest
        whole = [w for w in ways if all(u.understood for u in dr.read_text(w))]
        tally["sentences where a way reads whole"] += bool(whole)
        tally["ways that read whole"] += len(whole)
        tally["ways"] += len(ways)
        right["likeliest"] += aligned(words, likeliest.split())[0]
        right["the best of the ways"] += max((aligned(words, w.split())[0] for w in ways), default=0)
        if k % 20 == 19:
            print(f"  {k + 1} ({time.time() - started:.0f} s)", flush=True)
    n = tally["words said"]
    print(dict(tally), flush=True)
    print({k: f"{v} ({100 * v / n:.1f}%)" for k, v in right.items()}, flush=True)
    print(f"words the reader does not have at all ({len(unknown)}), most met: {unknown.most_common(40)}", flush=True)
    print(f"({time.time() - started:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
