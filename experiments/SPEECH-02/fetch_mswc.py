"""The spoken examples SPEECH-02 teaches and tests with, fetched from the Multilingual Spoken Words Corpus.

MSWC (MLCommons, CC BY 4.0) holds one-second clips of single English words cut from Common Voice, split by speaker
into train, dev and test. For every word the lessons use, up to `PER_WORD` clips of different speakers are kept
from dev (to teach from) and from test (to hear), and nothing else: each 300 MB shard is read as it streams and
never stored. The clips land in `data/speech/mswc_en/<split>/<word>/`, which git ignores; datasets are never
pushed.

    ./venv_lyric/bin/python3 experiments/SPEECH-02/fetch_mswc.py [dev] [test] [train] [--from=N]
"""
import csv
import glob
import json
import re
import sys
import tarfile
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "speech" / "mswc_en"
BASE = "https://huggingface.co/datasets/MLCommons/ml_spoken_words/resolve/main/data"
SHARDS = {"dev": 12, "test": 12, "train": 88}
PER_WORD = {"dev": 10, "test": 10, "train": 50}


def lesson_words() -> Counter:
    """Every word the lessons write, lowercased, with how often."""
    words: Counter = Counter()
    for path in sorted(glob.glob(str(ROOT / "data" / "lessons" / "english_[0-9][0-9].json"))):
        data = json.load(open(path))
        records = data if isinstance(data, list) else data.get("records") or data.get("lessons") or []
        for record in records:
            sentence = record.get("sentence") if isinstance(record, dict) else None
            for word in re.findall(r"[A-Za-z]+(?:'[a-z]+)?", sentence or ""):
                words[word.lower()] += 1
    return words


def chosen(split: str, wanted: set) -> dict:
    """`member name -> (word, speaker, gender)`: up to PER_WORD clips of each wanted word, each of a speaker not
    chosen for that word before, in the corpus's own order."""
    splits = OUT / "splits.tar.gz"
    if not splits.exists():
        urllib.request.urlretrieve(f"{BASE}/splits/en/splits.tar.gz", splits)
    with tarfile.open(splits) as archive:
        rows = csv.DictReader(line.decode() for line in archive.extractfile(f"{split}.csv"))
        picked, speakers = {}, defaultdict(set)
        for row in rows:
            word = row["WORD"]
            if word not in wanted or row["VALID"] != "True" or row["SPEAKER"] in speakers[word] \
                    or len(speakers[word]) >= PER_WORD[split]:
                continue
            speakers[word].add(row["SPEAKER"])
            picked[row["LINK"].replace("/", "_", 1)] = (word, row["SPEAKER"], row["GENDER"])
    return picked


def main() -> int:
    """`fetch_mswc.py [split ...]`: the splits named (all three when none), added to what was fetched before."""
    OUT.mkdir(parents=True, exist_ok=True)
    wanted = set(lesson_words())
    index_path = OUT / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    first = int(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--from=")), 0))
    splits = [a for a in sys.argv[1:] if not a.startswith("--")]
    for split, count in SHARDS.items():
        if splits and split not in splits:
            continue
        picked = chosen(split, wanted)
        # A clip already on disk is kept as it is, so a fetch that stopped goes on from the shard it reached
        # (`--from=N`) without streaming again what it had.
        for name, (word, speaker, gender) in picked.items():
            if (OUT / split / word / name).exists():
                index[f"{split}/{word}/{name}"] = {"word": word, "speaker": speaker, "gender": gender}
        kept = sum(1 for key in index if key.startswith(f"{split}/"))
        started = time.time()
        for shard in range(first, count):
            url = f"{BASE}/opus/en/{split}/audio/{shard}.tar.gz"
            for attempt in range(3):
                try:
                    # A stream that stops sending fails after a minute of nothing, and the shard is read again.
                    with urllib.request.urlopen(url, timeout=60) as stream, \
                            tarfile.open(fileobj=stream, mode="r|gz") as archive:
                        for member in archive:
                            name = member.name.lstrip("/")
                            if name not in picked or not member.isfile():
                                continue
                            word, speaker, gender = picked[name]
                            path = OUT / split / word / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(archive.extractfile(member).read())
                            if f"{split}/{word}/{name}" not in index:
                                kept += 1
                            index[f"{split}/{word}/{name}"] = {"word": word, "speaker": speaker, "gender": gender}
                    break
                except (OSError, tarfile.TarError) as error:
                    print(f"  {split} shard {shard}: {error}; reading it again", flush=True)
            else:
                raise RuntimeError(f"{split} shard {shard} could not be read in three tries")
            print(f"  {split} shard {shard}: {kept} of {len(picked)} clips kept, {time.time() - started:.0f} s",
                  flush=True)
            index_path.write_text(json.dumps(index, indent=1))
    words = Counter(entry["word"] for entry in index.values())
    print(f"{len(index)} clips of {len(words)} words; lesson words with none: "
          f"{sorted(wanted - set(words))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
