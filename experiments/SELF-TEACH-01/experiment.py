"""SELF-TEACH-01: whether the structure reader teaches itself from raw text, keeping what its two readings agree on.

The reader (`core/semantics/structure.py`) decides a sentence's structure two ways at once: a transition beam and a
whole-tree pair model, combined. Where the two, each alone (`StructureView.readings_apart`), give the same head to
enough of a sentence's words, the combined reading is taken as confirmed. Learned from UD English EWT's training part,
the reader reads raw sentences of Wikipedia (WikiText-103, CC BY-SA), keeps those confirmed at a bar, and is learned
again from the treebank and them. Measured as the treebank's own reader is: on EWT's development part and on PUD
(1,000 sentences of Wikipedia, analysed by hand), the share of words given the right head (UAS) and the right head
and relation (LAS).

First, how far agreement can be trusted: EWT dev and PUD read the same way, each sentence's agreement against how
right its reading is. Then the reader learned again with self-taught text at several bars and sizes, against the
reader without it. The bar fixed before the run: added as much self-taught text as the treebank's training part, the
reader gains at least half of what doubling the hand-analysed text gave (3.2 points of UAS a doubling, lab notebook
2026-10-17 (13)).

Files only, nothing written to any store. Run (from the Lyric folder; about two hours on four cores):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/SELF-TEACH-01/experiment.py --raw DIR [--data DIR]
        [--sentences N] [--processes P]
with `--raw` holding WikiText-103's raw training text as parquet (`text` column; `wikitext-103-raw-v1`), and
`--data` (default `test_data/syntax`) holding `UD_English-EWT` and `UD_English-PUD`.
"""
import json
import multiprocessing
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

#: Of the doubling of hand-analysed text: 3.2 points of UAS (lab notebook 2026-10-17 (13)).
DOUBLING = 0.032
#: The agreement bars and how many confirmed sentences to add at each; `None` adds all there are.
TAUGHT = [(1.0, None), (0.9, 12544), (0.8, 12544), (0.8, 25088), (0.8, 50176), (0.7, 25088)]
BARS = (1.0, 0.9, 0.8, 0.7)
VIEW = None


def say(*a):
    print(*a, flush=True)


def argument(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def raw_sentences(directory: Path, want: int):
    """WikiText-103's text as sentences, one a line: headings set aside, its own marks put back as written ("@-@" a
    hyphen, "@,@" "@.@" inside numbers), split where a sentence ends before a capital; of 5 to 40 words, ended, with
    their brackets closed; shuffled the same way every run."""
    import pyarrow.parquet as pq
    kept = []
    for path in sorted(directory.glob("*.parquet")):
        for row in pq.read_table(path).column("text").to_pylist():
            text = row.strip()
            if not text or text.startswith("="):
                continue
            text = text.replace(" @-@ ", "-").replace(" @,@ ", ",").replace(" @.@ ", ".")
            text = re.sub(r" ([,.;:!?)%])", r"\1", text)
            text = re.sub(r"\( ", "(", text)
            text = re.sub(r" (n't|'s|'re|'ve|'ll|'d|'m)\b", r"\1", text)
            text = re.sub(r'" (.*?) "', r'"\1"', text)
            for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text):
                words = sentence.split()
                if (5 <= len(words) <= 40 and sentence[-1] in ".!?" and all(ord(ch) < 0x2000 for ch in sentence)
                        and sentence.count("(") == sentence.count(")")):
                    kept.append(sentence)
    random.Random(7).shuffle(kept)
    return kept[:want]


def read_one(sentence):
    """A raw sentence read: its words, the combined reading, and the share of its words both readings alone give the
    same head."""
    from core.semantics.sentence_machine import form_of
    from core.semantics.structure import words_of
    words = words_of(form_of(sentence))
    if not 3 <= len(words) <= 50:
        return None
    structure, beam, pairs = VIEW.readings_apart(words, VIEW.classes(words))
    share = sum(x == y for x, y in zip(beam, pairs)) / len(words)
    return words, structure.classes, structure.heads, structure.relations, round(share, 4)


def read_analysed(analysed):
    """A hand-analysed sentence read: its agreement, its length, and how many of its words have the right head."""
    structure, beam, pairs = VIEW.readings_apart(analysed.words, VIEW.classes(analysed.words))
    n = len(analysed.words)
    right = sum(h == g for h, g in zip(structure.heads, analysed.heads))
    return sum(x == y for x, y in zip(beam, pairs)) / n, n, right


def learned(treebank, taught=()):
    from core.semantics.structure import Analysed, StructureView
    view = StructureView()
    for analysed in treebank:
        view.add(analysed)
    for k, (words, classes, heads, relations, _) in enumerate(taught):
        view.add(Analysed(tuple(words), tuple(classes), tuple(heads), tuple(relations), f"wikitext:{k}"))
    view.read(("Hello", "."))
    return view


def measured(view, held):
    out = {}
    for name, sentences in held.items():
        n = heads = both = 0
        for analysed in sentences:
            read = view.read(analysed.words)
            for i in range(len(analysed.words)):
                n += 1
                heads += read.heads[i] == analysed.heads[i]
                both += read.heads[i] == analysed.heads[i] and read.relations[i] == analysed.relations[i]
        out[name] = (heads / n, both / n)
    return out


def main() -> int:
    global VIEW
    from experiments._evidence import RunRecord
    from core.learning.teaching_sources import read_conllu
    data = Path(argument("--data") or ROOT / "test_data" / "syntax")
    raw = Path(argument("--raw") or "")
    want, processes = int(argument("--sentences", 200000)), int(argument("--processes", 3))
    EV = RunRecord("SELF-TEACH-01",
                   claim="the structure reader teaches itself from raw text, keeping the readings its two ways of "
                         "reading agree on",
                   hypothesis="added as much self-taught text as the treebank's training part, the reader gains at "
                              "least half of what doubling the hand-analysed text gave")
    started = time.perf_counter()
    train = list(read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"), "ud_english_ewt"))
    held = {"EWT dev": list(read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-dev.conllu"), "ewt_dev")),
            "PUD": list(read_conllu(str(data / "UD_English-PUD" / "en_pud-ud-test.conllu"), "pud"))}
    sentences = raw_sentences(raw, want)
    EV.check("the raw text is on disk", len(sentences) > 0, f"{len(sentences):,} sentences from {raw}")
    say(f"{len(sentences):,} raw sentences, {time.perf_counter() - started:.0f}s")
    VIEW = learned(train)
    fork = multiprocessing.get_context("fork")

    # ── how far agreement can be trusted ────────────────────────────────────────────────────────────────────────
    with fork.Pool(processes) as pool:
        for name, analysed in held.items():
            found = pool.map(read_analysed, analysed, chunksize=50)
            for bar in BARS:
                kept = [(n, right) for share, n, right in found if share >= bar]
                words = sum(n for n, _ in kept)
                EV.metric(f"{name}: agreeing on ≥ {bar:.0%} of words", len(kept), unit="sentences",
                          note=f"of {len(found):,}; {words / max(1, len(kept)):.1f} words each; "
                               f"UAS {sum(r for _, r in kept) / max(1, words):.1%}")
                say(f"  {name}: agreeing on ≥ {bar:.0%}: {len(kept):,} sentences, "
                    f"{words / max(1, len(kept)):.1f} words each, UAS {sum(r for _, r in kept) / max(1, words):.1%}")

    # ── the raw text read ───────────────────────────────────────────────────────────────────────────────────────
        read = [r for r in pool.imap(read_one, sentences, chunksize=100) if r]
    say(f"{len(read):,} raw sentences read, {time.perf_counter() - started:.0f}s")
    for bar in BARS:
        kept = [r for r in read if r[4] >= bar]
        EV.metric(f"raw text: agreeing on ≥ {bar:.0%} of words", len(kept), unit="sentences",
                  note=f"of {len(read):,}; {sum(len(r[0]) for r in kept) / max(1, len(kept)):.1f} words each")

    # ── the reader learned again ────────────────────────────────────────────────────────────────────────────────
    VIEW = None
    base = measured(learned(train), held)
    for name, (uas, las) in base.items():
        EV.metric(f"{name} UAS / LAS, the treebank alone", f"{uas:.2%} / {las:.2%}")
    say(f"  treebank alone: " + "; ".join(f"{n} {u:.2%} / {l:.2%}" for n, (u, l) in base.items()))
    gains = {}
    for bar, size in TAUGHT:
        taught = [r for r in read if r[4] >= bar][:size]
        got = measured(learned(train, taught), held)
        gains[(bar, len(taught))] = got["EWT dev"][0] - base["EWT dev"][0]
        for name, (uas, las) in got.items():
            EV.metric(f"{name} UAS / LAS, + {len(taught):,} agreeing on ≥ {bar:.0%}", f"{uas:.2%} / {las:.2%}",
                      note=f"UAS {100 * (uas - base[name][0]):+.2f} points")
        say(f"  + {len(taught):,} at ≥ {bar:.0%}: " + "; ".join(
            f"{n} {u:.2%} / {l:.2%} ({100 * (u - base[n][0]):+.2f})" for n, (u, l) in got.items()))
    as_large = [gain for (bar, n), gain in gains.items() if n >= len(train)]
    EV.check("as much self-taught text as the treebank gains at least half a doubling's UAS on EWT dev",
             bool(as_large) and max(as_large) >= DOUBLING / 2,
             f"best {100 * max(as_large, default=0):+.2f} points against {100 * DOUBLING / 2:.1f}")
    say(f"\n  run record: {EV.write()}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
