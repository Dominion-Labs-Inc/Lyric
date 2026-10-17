"""ROLES-01: argument-structure constructions, learned over phrases, say each argument's part.

Learned from PropBank's annotations of the English Web Treebank's training part (with UD's words and structure),
each argument said in the meaning language by `propbank_roles`; read on the held-out parts (dev, test), the
arguments given, twice: over UD's own structure (how well the constructions do where the structure is right) and over
the structure Lyric's reader gives (`StructureView`, learned from the same training part): how well they do as
Lyric reads. Measured: the share of arguments said in the fact PropBank's role maps to, against the path alone.

Run (from the Lyric folder; reads files only, a few minutes):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/ROLES-01/experiment.py [--data DIR]
with `DIR` (default `test_data/syntax`) holding `propbank-release`, `propbank-frames` and `UD_English-EWT`.
"""
import json
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
    from core.semantics import propbank_roles as pr
    from core.semantics.structure import StructureView
    data = Path(sys.argv[sys.argv.index("--data") + 1]) if "--data" in sys.argv else ROOT / "test_data" / "syntax"
    EV = RunRecord("ROLES-01",
                   claim="argument-structure constructions learned over phrases say each argument's part",
                   hypothesis="learned from PropBank's training part, they say the held-out arguments' parts in the "
                              "meaning language better than the path alone does, over UD's structure and over "
                              "Lyric's own (no bar: measured)")
    started = time.perf_counter()
    roles = propbank_roles_of_frames(str(data / "propbank-frames" / "frames"))
    sentences = list(read_propbank_ewt(str(data / "propbank-release"), str(data / "UD_English-EWT")))
    say(f"{len(sentences):,} sentences read, {time.perf_counter() - started:.0f}s")

    def arguments(words, predicates):
        """Each argument of a happening, and what the mapping says it in (a relative pronoun or a continuation
        takes its argument's part and is left to it)."""
        for found in predicates:
            if pr.predicate(found.roleset, found.tag) is not None:
                continue
            for label, spans in found.arguments:
                base, stands = pr.label_of(label)
                if stands:
                    continue
                tag, verbnet = roles.get((found.roleset, base), ("", ()))
                for span in spans:
                    said = pr.said(label, roleset=found.roleset, function_tag=tag, verbnet=verbnet,
                                   words=tuple(w.form for w in words[span[0]:span[0] + 2]),
                                   first_class=words[span[0]].word_class)
                    if said is None:
                        continue
                    if said.how == "rule" and said.rule == "pivot":
                        said = pr.fact("done_by")   # a pivot not said by its predicate is its doer (`RULES`)
                    yield found.at, span, ":".join(x for x in (said.how, said.kind or said.rule or said.needs,
                                                               "" if said.positive else "not") if x)

    view = ax.ArgumentStructureView()
    by_path = defaultdict(Counter)
    for part, _, _, words, predicates in sentences:
        if part != "train":
            continue
        forms, classes = [w.form for w in words], [w.word_class for w in words]
        heads, relations = [w.head for w in words], [w.relation for w in words]
        for at, span, said in arguments(words, predicates):
            view.add(ax.situations(forms, classes, heads, relations, at, span), said)
            by_path[ax.path(at, ax.head_of(span, heads), heads, relations)][said] += 1
    EV.metric("arguments learned from", len(view), unit="arguments")
    say(f"learned from {len(view):,} arguments")

    structure = StructureView()
    for analysed in read_conllu(str(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"), "ud_english_ewt"):
        structure.add(analysed)
    for part in ("dev", "test"):
        counts = Counter()
        wrong = Counter()
        for got_part, _, _, words, predicates in sentences:
            if got_part != part:
                continue
            forms = [w.form for w in words]
            gold = ([w.word_class for w in words], [w.head for w in words], [w.relation for w in words])
            read = structure.read(tuple(forms))
            own = (list(read.classes), list(read.heads), list(read.relations))
            for at, span, said in arguments(words, predicates):
                counts["arguments"] += 1
                on_gold = view.said(ax.situations(forms, *gold, at, span))
                on_own = view.said(ax.situations(forms, *own, at, span))
                alone = by_path.get(ax.path(at, ax.head_of(span, gold[1]), gold[1], gold[2]))
                counts["gold structure"] += on_gold == said
                counts["Lyric's structure"] += on_own == said
                counts["path alone"] += bool(alone) and alone.most_common(1)[0][0] == said
                if on_own != said:
                    wrong[(said, on_own)] += 1
        n = counts["arguments"]
        say(f"{part}: {n:,} arguments")
        EV.metric(f"{part} arguments", n, unit="arguments")
        for way in ("gold structure", "Lyric's structure", "path alone"):
            EV.metric(f"{part}: said right over {way}", round(counts[way] / n, 4), unit="fraction")
            say(f"    over {way:18} {counts[way] / n:.1%}")
        EV.metric(f"{part}: most often said wrong over Lyric's structure", 0, unit="",
                  note="; ".join(f"{a} as {b} {k}" for (a, b), k in wrong.most_common(12)))
    EV.check("the constructions learned from every training argument", len(view) > 0, f"{len(view):,}")
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    path = EV.write()
    say(f"\n  run record: {path}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
