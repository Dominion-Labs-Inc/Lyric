"""GROUPS-01: whether words grouped by the company they keep, counted from raw text, help the structure reader read.

Every word of WikiText-103's raw training text (about 100 million words of Wikipedia, CC BY-SA) is put in one of a
number of groups so that the counts of which group follows which say the text best (`core/semantics/word_groups.py`:
the exchange algorithm over a class bigram model, Kneser & Ney 1993; Martin, Liermann & Ney 1998). Counted twice, 256
groups and 48, for the 100,000 most frequent words. Counts only: no model is learned, and the tables are read as they
are ("make, take, get, see, give" stand together).

Then the structure reader (`core/semantics/structure.py`) is learned from UD English EWT's training part twice: as it
is, and with each word's two groups beside it (`StructureView.grouping`), so a word it met rarely or never is weighed
by the words that stand where it does. Measured on EWT's development part and on PUD (1,000 sentences of Wikipedia
analysed by hand): classes, the share of words given the right head (UAS), the right head and relation (LAS), and UAS
on the words met fewer than ten times in training.

The bar comes from the scratch measurements that came first (lab notebook 2026-10-18: +0.9 points of UAS on both):
with the groups, UAS rises at least half a point on EWT dev and on PUD.

Files only, nothing written to any store. The tables are written to `--out` (default `data/word_groups`, which is not
in the repository) for the teaching pass to take. Run (from the Lyric folder; about half an hour):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GROUPS-01/experiment.py --raw DIR [--data DIR] [--out DIR]
with `--raw` holding WikiText-103's raw training text as parquet (`wikitext-103-raw-v1`, `text` column) and `--data`
(default `test_data/syntax`) holding `UD_English-EWT` and `UD_English-PUD`.
"""
import collections
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

#: UAS the groups add, at least, on EWT dev and on PUD.
BAR = 0.005
#: The groups counted: fine and coarse.
FINE, COARSE = 256, 48
#: A word met fewer times than this in the treebank's training part is rare.
RARE = 10


def say(*a):
    print(*a, flush=True)


def argument(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def paragraphs(directory: Path):
    """WikiText-103's text a paragraph at a time, its words as written: headings set aside, its own marks put back
    ("@-@" a hyphen standing alone, "@,@" "@.@" inside numbers)."""
    import pyarrow.parquet as pq
    for path in sorted(directory.glob("*.parquet")):
        for row in pq.read_table(path).column("text").to_pylist():
            text = row.strip()
            if text and not text.startswith("="):
                yield text.replace(" @-@ ", " - ").replace(" @,@ ", ",").replace(" @.@ ", ".").split()


def measured(view, held, met):
    out = {}
    for name, sentences in held.items():
        n = classes = heads = both = rare = rare_heads = 0
        for analysed in sentences:
            read = view.read(analysed.words)
            for i, word in enumerate(analysed.words):
                n += 1
                classes += read.classes[i] == analysed.classes[i]
                heads += read.heads[i] == analysed.heads[i]
                both += read.heads[i] == analysed.heads[i] and read.relations[i] == analysed.relations[i]
                if met[word.lower()] < RARE:
                    rare += 1
                    rare_heads += read.heads[i] == analysed.heads[i]
        out[name] = {"classes": classes / n, "UAS": heads / n, "LAS": both / n, "UAS rare": rare_heads / rare,
                     "rare": rare}
    return out


def main() -> int:
    from experiments._evidence import RunRecord
    from core.learning.teaching_sources import read_conllu
    from core.semantics.structure import StructureView
    from core.semantics.word_groups import counted_groups, grouping
    data = Path(argument("--data") or ROOT / "test_data" / "syntax")
    raw = Path(argument("--raw") or "")
    out = Path(argument("--out") or ROOT / "data" / "word_groups")
    EV = RunRecord("GROUPS-01",
                   claim="words grouped by the company they keep, counted from raw text, help the structure reader "
                         "read",
                   hypothesis=f"with each word's groups beside it, the reader learned from EWT's training part reads "
                              f"EWT dev and PUD at least {100 * BAR:.1f} points of UAS better")
    started = time.perf_counter()

    # ── the groups, counted ─────────────────────────────────────────────────────────────────────────────────────
    out.mkdir(parents=True, exist_ok=True)
    tables = {}
    for groups in (FINE, COARSE):
        tables[groups] = counted_groups(paragraphs(raw), groups, say=lambda s: say(f"  {groups} groups: {s}"))
        with open(out / f"groups_{groups}.tsv", "w", encoding="utf-8") as handle:
            for word, group in tables[groups].items():
                handle.write(f"{word}\t{group}\n")
        EV.metric(f"words given one of {groups} groups", len(tables[groups]),
                  note=f"{len(set(tables[groups].values()))} groups used; {time.perf_counter() - started:.0f}s")
    fine, coarse = tables[FINE], tables[COARSE]
    for word in ("make", "more", "whale", "blue", "because"):
        together = [w for w, g in fine.items() if g == fine.get(word)][:12]
        EV.note(f"in {word}'s group of {FINE}: {' '.join(together)}")
        say(f"  {word}: {' '.join(together)}")
    EV.check("the words are grouped", len(fine) > 50_000 and len(set(fine.values())) > FINE // 2,
             f"{len(fine):,} words in {len(set(fine.values()))} groups")

    # ── the reader, without and with them ───────────────────────────────────────────────────────────────────────
    train = list(read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"), "ud_english_ewt"))
    held = {"EWT dev": list(read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-dev.conllu"), "ewt_dev")),
            "PUD": list(read_conllu(str(data / "UD_English-PUD" / "en_pud-ud-test.conllu"), "pud"))}
    met = collections.Counter(w.lower() for a in train for w in a.words)
    found = {}
    for way in ("without groups", "with groups"):
        view = StructureView()
        for analysed in train:
            view.add(analysed)
        if way == "with groups":
            view.grouping = grouping(fine, coarse)
        view.read(("Hello", "."))
        found[way] = measured(view, held, met)
        for name, m in found[way].items():
            EV.metric(f"{name}, {way}: classes / UAS / LAS", f"{m['classes']:.2%} / {m['UAS']:.2%} / {m['LAS']:.2%}",
                      note=f"UAS on the {m['rare']:,} words met fewer than {RARE} times: {m['UAS rare']:.2%}")
            say(f"  {name}, {way}: classes {m['classes']:.2%}, UAS {m['UAS']:.2%}, LAS {m['LAS']:.2%}, "
                f"rare {m['UAS rare']:.2%}; {time.perf_counter() - started:.0f}s")
    for name in held:
        gain = found["with groups"][name]["UAS"] - found["without groups"][name]["UAS"]
        EV.check(f"{name}: the groups add at least {100 * BAR:.1f} points of UAS", gain >= BAR,
                 f"{100 * gain:+.2f} points")
    say(f"\n  run record: {EV.write()}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
