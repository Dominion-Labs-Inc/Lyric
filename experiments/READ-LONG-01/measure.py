"""READ-LONG-01, measuring: how long the reader takes on a sentence as it grows, with no punctuation, as speech
arrives. Two kinds, each cut to each length, the sandbox's language as taught, its store only read:
  - LibriSpeech test-clean transcripts (words the sandbox may not hold);
  - run-on speech of words the lessons teach: taught statements, their marks and capitals taken away, one after
    another ("the dog ran to the house the cat is on the mat ...").
Each line is printed as the sentence finishes, so the growth shows before any length that does not finish.

    ./venv_lyric/bin/python3 experiments/READ-LONG-01/measure.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("POSTGRES_DATABASE", "lyric_dev")
LENGTHS = (8, 12, 16, 20, 25, 30, 40, 60)


def transcripts():
    import pyarrow.parquet as pq
    table = pq.read_table(REPO / "data" / "speech" / "librispeech_alignments" / "test_clean.parquet",
                          columns=["words"]).to_pylist()
    return [" ".join(w["word"].lower() for w in row["words"] if w["word"]) for row in table]


def run_on(count: int = 2):
    """Taught statements, unmarked and joined, `count` texts of 60+ words."""
    import json
    import re
    lessons = sorted((REPO / "data" / "lessons").glob("english_[0-9][0-9].json"))
    told = [r["sentence"] for path in lessons for r in json.loads(path.read_text())["records"]
            if r["meaning"]["act"] == "tell" and r["sentence"].endswith(".")]
    words = [w for sentence in told for w in re.sub(r"[^\w\s']", " ", sentence).lower().split()]
    size = max(LENGTHS)
    return [" ".join(words[k * size * 7:(k * 7 + 1) * size]) for k in range(count)]


async def main():
    from core.database import get_database_manager
    from core.memory import get_memory_agent
    from core.reasoning.bayesian_uncertainty import get_uncertainty_system
    from core.semantics import derived_reader as dr
    manager = get_database_manager()
    await manager.initialize()
    await manager.assert_database_identity("lyric_dev")
    await get_uncertainty_system().load_from_db()
    await (await get_memory_agent()).language_view()
    kinds = [("transcript", [t for t in transcripts() if len(t.split()) >= max(LENGTHS)][:2])]
    if "--run-on" in sys.argv:
        kinds = [("run-on", run_on())]
    for kind, texts in kinds:
      for text in texts:
        for n in LENGTHS:
            sentence = " ".join(text.split()[:n])
            start = time.perf_counter()
            utterances = dr.read_text(sentence)
            took = time.perf_counter() - start
            whole = bool(utterances) and all(u.understood for u in utterances)
            print(f"{kind}: {n:3d} words  {took:8.2f} s  read whole: {whole}  | {sentence[:90]}", flush=True)


asyncio.run(main())
