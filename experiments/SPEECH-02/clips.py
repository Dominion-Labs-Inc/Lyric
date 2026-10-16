"""The recordings SPEECH-02 teaches from and hears, and how each is presented to the ear.

Both the experiment and its offline study (`offline_naming.py`) take clips from here, so they hear the same."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEECH = REPO / "data" / "speech"
SOURCES = {"mswc": SPEECH / "mswc_en", "librispeech": SPEECH / "librispeech_words"}
QUIET_DB = -60.0          # the room's floor, as SPEECH-01


def clips(words, examples: int, heard: int) -> dict:
    """`word -> {"teach": [...], "heard": [...]}`: clip paths with speaker and source, the teaching ones from the
    sources' dev split and then train, the heard ones from test, so no speaker teaches and is heard. A word in both sources is
    taken from MSWC, whose clips are of the word said alone."""
    out = {}
    for source, root in SOURCES.items():
        index_path = root / "index.json"
        if not index_path.exists():
            continue
        for rel, entry in sorted(json.loads(index_path.read_text()).items()):
            split = rel.split("/", 1)[0]
            word = entry["word"]
            if word not in words or (word in out and out[word]["source"] != source):
                continue
            slot = out.setdefault(word, {"source": source, "teach": [], "heard": []})
            role = "heard" if split == "test" else "teach"
            limit = examples if role == "teach" else heard
            if len(slot[role]) < limit:
                slot[role].append({"path": root / rel, "speaker": entry["speaker"], "gender": entry.get("gender")})
    return out


#: Where a clip's loudest moment is brought before the room goes around it.
PEAK_DB = -12.0


def present(path: Path, out: Path, rng) -> Path:
    """A clip as a live buffer presents speech: 0.3 s of room quiet either side, at the hearing's own rate.

    THE CLIP AT ONE LEVEL FIRST. How loud a recording is is how it was framed, and the ear does not hear it as what
    was said (`hearing`: level is a property, never a kind). The rooms here are one level, -60 dB, so a speaker
    recorded quietly (LibriSpeech 1993, the whole sentence about -44 dB) said "of" barely above the room put around
    it, and the lesson was refused as nothing said. Each clip's loudest moment is brought to `PEAK_DB` first."""
    import numpy as np
    import soundfile as sf
    from core.perception import hearing as H
    if not out.exists():
        y = H.decode(str(path))
        peak = float(np.abs(y).max()) if len(y) else 0.0
        if peak > 0:
            y = y * (10 ** (PEAK_DB / 20) / peak)
        quiet = lambda s: rng.normal(0, 10 ** (QUIET_DB / 20), int(s * H.SR))
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), np.clip(np.concatenate([quiet(0.3), y, quiet(0.3)]), -1, 1).astype(np.float32), H.SR)
    return out
