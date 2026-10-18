"""STRUCTURE-03: whether more hand-analysed English raises the structure reader, and the counted word groups beside it.

The structure reader (`core/semantics/structure.py`) learned from UD English EWT's training part alone, then with UD's
other English treebanks beside it, each as the teaching pass takes it (`TreebankSource.of`, `TREEBANKS`: GUM, LinES,
ParTUT, Atis and ESL Spoken, their training and development parts, each under its own source), and last with each
word's counted groups too (`experiments/GROUPS-01`'s tables, `core/semantics/word_groups.py`). Measured on EWT's
development part, PUD (1,000 sentences of Wikipedia analysed by hand) and GUM's test part, which no reader here learns
from: classes, the share of words given the right head (UAS) and the right head and relation (LAS).

The bars come from the scratch measurements that came first (lab notebook 2026-10-18; EWT dev +1.9 and GUM test +3.8
points of UAS with every treebank): with every treebank the teaching pass takes, UAS rises at least 1.5 points on EWT
dev and 3 on GUM's test; the groups beside them raise it on all three.

Files only, nothing written to any store. Run (from the Lyric folder; about an hour on two cores):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-03/experiment.py [--data DIR] [--groups DIR]
        [--processes P]
with `--data` (default `test_data/syntax`) holding `UD_English-EWT`, `UD_English-PUD` and each treebank of `TREEBANKS`,
and `--groups` (default `data/word_groups`) GROUPS-01's `groups_256.tsv` and `groups_48.tsv`.
"""
import multiprocessing
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

#: Each reader measured: its name, the treebanks it learns from, and whether the groups stand beside the words.
READERS = [
    ("EWT alone", ("ewt",), False),
    ("EWT, Atis, ESL Spoken (CC BY-SA)", ("ewt", "atis", "eslspok"), False),
    ("EWT and GUM", ("ewt", "gum"), False),
    ("every treebank", ("ewt", "gum", "lines", "partut", "atis", "eslspok"), False),
    ("every treebank, with groups", ("ewt", "gum", "lines", "partut", "atis", "eslspok"), True),
]
#: UAS every treebank adds at least: on EWT dev, on GUM's test.
BAR_DEV, BAR_GUM = 0.015, 0.03
DATA = GROUPS = None


def say(*a):
    print(*a, flush=True)


def argument(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def table(path: Path):
    with open(path, encoding="utf-8") as handle:
        return {word: int(group) for word, group in (line.rstrip("\n").split("\t") for line in handle)}


def measure(reader):
    """One reader learned and read the held-out sentences with: classes, UAS and LAS on each."""
    from core.learning.teaching_sources import TreebankSource, read_conllu
    from core.semantics.structure import StructureView
    from core.semantics.word_groups import grouping
    name, treebanks, grouped = reader
    started = time.perf_counter()
    view = StructureView()
    learned = 0
    for treebank in treebanks:
        for analysed in TreebankSource.of(treebank, str(DATA)).analysed():
            learned += bool(view.add(analysed))
    if grouped:
        view.grouping = grouping(table(GROUPS / "groups_256.tsv"), table(GROUPS / "groups_48.tsv"))
    view.read(("Hello", "."))
    held = {"EWT dev": DATA / "UD_English-EWT" / "en_ewt-ud-dev.conllu",
            "PUD": DATA / "UD_English-PUD" / "en_pud-ud-test.conllu",
            "GUM test": DATA / "UD_English-GUM" / "en_gum-ud-test.conllu"}
    out = {}
    for test, path in held.items():
        n = classes = heads = both = 0
        for analysed in read_conllu(str(path), test):
            read = view.read(analysed.words)
            for i in range(len(analysed.words)):
                n += 1
                classes += read.classes[i] == analysed.classes[i]
                heads += read.heads[i] == analysed.heads[i]
                both += read.heads[i] == analysed.heads[i] and read.relations[i] == analysed.relations[i]
        out[test] = (classes / n, heads / n, both / n)
    say(f"  {name}: {learned:,} sentences; " + "; ".join(
        f"{t} UAS {u:.2%} LAS {l:.2%}" for t, (_, u, l) in out.items()) + f"; {time.perf_counter() - started:.0f}s")
    return name, learned, out


def main() -> int:
    global DATA, GROUPS
    from experiments._evidence import RunRecord
    from core.learning.teaching_sources import TREEBANKS
    DATA = Path(argument("--data") or ROOT / "test_data" / "syntax")
    GROUPS = Path(argument("--groups") or ROOT / "data" / "word_groups")
    processes = int(argument("--processes", 2))
    EV = RunRecord("STRUCTURE-03",
                   claim="more hand-analysed English raises the structure reader, and the counted word groups "
                         "beside it raise it further",
                   hypothesis=f"with every treebank the teaching pass takes, UAS rises at least {100 * BAR_DEV:.1f} "
                              f"points on EWT dev and {100 * BAR_GUM:.0f} on GUM's test; the groups raise it on all "
                              f"three")
    missing = [f"{TREEBANKS[t][0]}" for t in TREEBANKS if not (DATA / TREEBANKS[t][0]).is_dir()]
    EV.check("every treebank is on disk", not missing, ", ".join(missing) or f"under {DATA}")
    EV.check("the groups are on disk", (GROUPS / "groups_256.tsv").exists() and (GROUPS / "groups_48.tsv").exists(),
             str(GROUPS))
    if missing:
        say(f"  missing: {', '.join(missing)}")
        say(f"\n  run record: {EV.write()}")
        return 1
    for treebank, (folder, parts, licence) in TREEBANKS.items():
        EV.note(f"{folder}: {', '.join(parts)}; {licence}")
    with multiprocessing.get_context("fork").Pool(processes) as pool:
        found = {name: (learned, out) for name, learned, out in pool.imap(measure, READERS)}
    for name, (learned, out) in found.items():
        for test, (classes, uas, las) in out.items():
            EV.metric(f"{test}, {name}: classes / UAS / LAS", f"{classes:.2%} / {uas:.2%} / {las:.2%}",
                      note=f"learned from {learned:,} sentences")
    base, every, grouped = found["EWT alone"][1], found["every treebank"][1], found["every treebank, with groups"][1]
    for test, bar in (("EWT dev", BAR_DEV), ("GUM test", BAR_GUM)):
        gain = every[test][1] - base[test][1]
        EV.check(f"{test}: every treebank adds at least {100 * bar:.1f} points of UAS", gain >= bar,
                 f"{100 * gain:+.2f} points")
    for test in base:
        gain = grouped[test][1] - every[test][1]
        EV.check(f"{test}: the groups beside every treebank raise UAS", gain > 0, f"{100 * gain:+.2f} points")
    say(f"\n  run record: {EV.write()}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
