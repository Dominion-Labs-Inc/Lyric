"""Spoken examples of the lesson words the Multilingual Spoken Words Corpus does not hold, cut from LibriSpeech.

MSWC keeps no word shorter than three letters, nor contractions: "is", "a", "of", "to", "it", "in", "I", "isn't".
LibriSpeech (CC BY 4.0) holds read English with every word's start and end, aligned by the Montreal Forced Aligner
(`gilkeyio/librispeech-alignments`, which carries the audio too). Each such word is cut out of the sentences it is
said in, up to `PER_WORD` speakers: from dev-clean to teach, from test-clean to hear, so no speaker is in both. The
clips land in `data/speech/librispeech_words/<split>/<word>/`, which git ignores.

    ./venv_lyric/bin/python3 experiments/SPEECH-02/cut_librispeech.py
"""
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "data" / "speech" / "librispeech_alignments"
OUT = ROOT / "data" / "speech" / "librispeech_words"
MSWC = ROOT / "data" / "speech" / "mswc_en" / "index.json"
SPLITS = {"dev": "dev_clean", "test": "test_clean"}
PER_WORD = 10


def main() -> int:
    import numpy as np
    import pyarrow.parquet as pq
    import soundfile as sf
    sys.path.insert(0, str(Path(__file__).parent))
    from fetch_mswc import lesson_words
    held = {entry["word"] for entry in json.loads(MSWC.read_text()).values()} if MSWC.exists() else set()
    wanted = {w for w in lesson_words() if w not in held}
    print(f"{len(wanted)} lesson words MSWC does not hold: {sorted(wanted)}")
    index = {}
    for split, name in SPLITS.items():
        table = pq.read_table(SOURCE / f"{name}.parquet", columns=["id", "sex", "words", "audio"])
        speakers = defaultdict(set)
        for row in table.to_pylist():
            speaker = row["id"].split("-")[0]
            hits = [(k, w) for k, w in enumerate(row["words"]) if w["word"] in wanted
                    and speaker not in speakers[w["word"]] and len(speakers[w["word"]]) < PER_WORD]
            if not hits:
                continue
            y, rate = sf.read(io.BytesIO(row["audio"]["bytes"]))
            for k, w in hits:
                if speaker in speakers[w["word"]]:
                    continue
                first, last = int(w["start"] * rate), int(w["end"] * rate)
                if last - first < int(0.05 * rate):
                    continue
                speakers[w["word"]].add(speaker)
                path = OUT / split / w["word"] / f"{row['id']}_{k}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(str(path), np.asarray(y[first:last], dtype=np.float32), rate)
                index[str(path.relative_to(OUT))] = {"word": w["word"], "speaker": speaker,
                                                      "gender": {"M": "MALE", "F": "FEMALE"}.get(row["sex"], row["sex"]),
                                                      "utterance": row["id"], "start": w["start"], "end": w["end"]}
        print(f"  {split}: {sum(len(s) for s in speakers.values())} clips of {len(speakers)} words")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(index, indent=1))
    found = {entry["word"] for entry in index.values()}
    print(f"lesson words with no clip anywhere: {sorted(wanted - found)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
