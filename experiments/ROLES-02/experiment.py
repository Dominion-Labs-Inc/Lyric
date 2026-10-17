"""ROLES-02: which phrases are a happening's arguments, and what each is said in, end to end.

ROLES-01 gave the arguments and measured what each is said in. Here nothing is given but the predicate: of the words
that may head one of its arguments (`argument_structure.candidates`), the view learned from PropBank's training part
(each candidate that heads none said as `NONE`) says which head one and what each is said in. Measured on the
held-out parts (dev, test) over UD's structure and over the structure Lyric's reader gives: of the arguments found,
how many are PropBank's (precision); of PropBank's, how many were found (recall); both with their head word only, and
with what it is said in too.

Run (from the Lyric folder; reads files only, about ten minutes):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/ROLES-02/experiment.py [--data DIR]
with `DIR` (default `test_data/syntax`) holding `propbank-release`, `propbank-frames` and `UD_English-EWT`.
"""
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def say(*a):
    print(*a, flush=True)


def main() -> int:
    from experiments._evidence import RunRecord
    from core.learning.teaching_sources import propbank_roles_of_frames, read_conllu, read_propbank_ewt
    from core.semantics import argument_structure as ax
    from core.semantics.structure import StructureView
    data = Path(sys.argv[sys.argv.index("--data") + 1]) if "--data" in sys.argv else ROOT / "test_data" / "syntax"
    EV = RunRecord("ROLES-02",
                   claim="which phrases are a happening's arguments, and what each is said in, found end to end",
                   hypothesis="learned from PropBank's training part with the candidates that head no argument, the "
                              "view finds the held-out arguments and says them, over UD's structure and over "
                              "Lyric's own (no bar: measured)")
    started = time.perf_counter()
    roles = propbank_roles_of_frames(str(data / "propbank-frames" / "frames"))
    sentences = list(read_propbank_ewt(str(data / "propbank-release"), str(data / "UD_English-EWT")))
    say(f"{len(sentences):,} sentences read, {time.perf_counter() - started:.0f}s")

    def arguments(words, predicates):
        return ax.taught_arguments(words, predicates, roles)

    view = ax.ArgumentStructureView()
    met = Counter()
    for part, _, _, words, predicates in sentences:
        if part != "train":
            continue
        forms, classes = [w.form for w in words], [w.word_class for w in words]
        heads, relations = [w.head for w in words], [w.relation for w in words]
        gold, left = arguments(words, predicates)
        for at, args in gold.items():
            candidates = ax.candidates(heads, at)
            met["arguments"] += len(args)
            met["among the candidates"] += sum(1 for head in args if head in candidates)
            for candidate in candidates:
                if candidate not in left[at]:
                    view.add(ax.situations(forms, classes, heads, relations, at, ax.phrase(candidate, heads)),
                             args.get(candidate, ax.NONE))
    covered = met["among the candidates"] / met["arguments"]
    EV.metric("training: arguments whose head is among the candidates", round(covered, 4), unit="fraction")
    EV.metric("candidates learned from", len(view), unit="candidates")
    say(f"training: {covered:.1%} of the arguments' heads among the candidates; {len(view):,} candidates")

    structure = StructureView()
    for analysed in read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"), "ud_english_ewt"):
        structure.add(analysed)
    for part in ("dev", "test"):
        counts = {way: Counter() for way in ("UD's structure", "Lyric's structure")}
        for got_part, _, _, words, predicates in sentences:
            if got_part != part:
                continue
            forms = [w.form for w in words]
            read = structure.read(tuple(forms))
            ways = {"UD's structure": ([w.word_class for w in words], [w.head for w in words],
                                       [w.relation for w in words]),
                    "Lyric's structure": (list(read.classes), list(read.heads), list(read.relations))}
            gold, left = arguments(words, predicates)
            for way, (classes, heads, relations) in ways.items():
                n = counts[way]
                for at, args in gold.items():
                    found = {head: said for head, said in view.arguments(forms, classes, heads, relations, at).items()
                             if head not in left[at]}
                    n["in PropBank"] += len(args)
                    n["found"] += len(found)
                    n["heads right"] += sum(1 for head in found if head in args)
                    n["said right"] += sum(1 for head, said in found.items() if args.get(head) == said)
        for way, n in counts.items():
            say(f"{part}, over {way}: {n['in PropBank']:,} arguments, {n['found']:,} found")
            for what in ("heads right", "said right"):
                precision, recall = n[what] / n["found"], n[what] / n["in PropBank"]
                f1 = 2 * precision * recall / (precision + recall)
                EV.metric(f"{part}, over {way}: {what}, F1", round(f1, 4), unit="fraction",
                          note=f"precision {precision:.4f}, recall {recall:.4f}")
                say(f"    {what:12} precision {precision:.1%}  recall {recall:.1%}  F1 {f1:.1%}")
    EV.check("the view learned from every training predicate's candidates", len(view) > 0, f"{len(view):,}")
    (HERE / "results").mkdir(exist_ok=True)
    say(f"\n  run record: {EV.write()}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
