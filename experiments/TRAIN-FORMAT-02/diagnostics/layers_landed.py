#!/usr/bin/env python3
"""WHAT EACH LAYER OF A WORD RECORDED WHOLE LANDS IN, read back from the grammar's own tables.

A record carries 27 layers and the checks read seven of them, so twenty went in with nothing asking whether they
came out (2026-11-02). Rather than write a check per layer -- which would re-describe where each one goes, beside
`GrammarView._count_word` which already decides it, and rot the moment a layer moves -- this holds the record and
DIFFS the grammar's tables around it. Whatever the writer wrote shows up by table and key, so the writer stays the
only authority on where a layer goes.

What it reports, per layer: how many entries the record carries, and how many rows appeared when it was held. A
layer with entries and no rows is taught and read by nothing -- the case no check could see.

BOTH HALVES OF TEACHING A WORD ARE HELD, since neither alone takes every layer: `GrammarView.hold_word` is one
half (`_count_word`, English's grammar), and `MemoryAgent._learn_word_record` is the other -- each form into the
forms held, how the word was joined into the structure view (`StructureView.hold_joins`), the classes each form is
used as into the word classes memory holds, and what the word names as each class. Measured over the first half
alone, twelve layers read as landing nowhere (2026-11-02).

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-02/diagnostics/layers_landed.py \
        [--records experiments/TRAIN-FORMAT-02/records.jsonl]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

#: Nothing is named by hand: every table each view holds is counted by name, so a layer that lands somewhere new is
#: counted the day it is written. These are only skipped -- what a view was built with, not what it holds.
SKIPPED = ("analysed", "closed", "name_of", "knowledge", "words", "structure", "lexicon", "grammar")


def _rows(table: Any) -> int:
    """How many counted rows a table holds, however deep its counters go."""
    if isinstance(table, Counter):
        return sum(1 for _ in table)
    if isinstance(table, dict):
        return sum(_rows(v) for v in table.values()) or len(table)
    if isinstance(table, (set, frozenset, list, tuple)):
        return len(table)
    return 1 if table else 0


def _tables(held: Any) -> Dict[str, int]:
    """How many rows each table a view holds has, by name (`vars`): whatever the writer wrote, counted as it stands."""
    out: Dict[str, int] = {}
    for name, value in vars(held).items():
        if name in SKIPPED or callable(value) or isinstance(value, (str, bytes, bool, int, float, type(None))):
            continue
        out[name.lstrip("_")] = _rows(value)
    return out


def _snapshot(view: Any) -> Dict[str, int]:
    """What English's grammar holds: every table on the words it reads, every table of the lexicon that reads them
    (its senses, its verbs' frames and places), and what it learned."""
    lexicon = view.grammar.lexicon
    held = _tables(lexicon.words)
    knowledge = getattr(lexicon.words, "knowledge", None)
    held["knowledge"] = _rows(getattr(knowledge, "_links", None) or getattr(knowledge, "links", None))
    for name, rows in _tables(lexicon).items():
        if name != "learned":
            held[f"lexicon.{name}"] = rows
    for table, counted in lexicon.learned.items():
        held[f"learned[{table}]"] = _rows(counted)
    return held


def _memorys(forms: Any, structure: Any, index: Dict, named: Dict) -> Dict[str, int]:
    """What memory's own views hold, the other half of teaching a word (`MemoryAgent._learn_word_record`): the forms
    held of each word, how words were joined and as what, the classes each form is used as, and what a word names as
    each class."""
    held = {"forms held": _rows(getattr(forms, "_held", None) or getattr(forms, "held", None)),
            "word classes": _rows(index), "names of a form": _rows(named)}
    for name in ("_held_joins", "_held_said"):
        held[f"structure{name}"] = _rows(getattr(structure, name, None))
    return held


def main() -> int:
    asked = argparse.ArgumentParser(description=__doc__)
    asked.add_argument("--records", default=str(ROOT / "experiments" / "TRAIN-FORMAT-02" / "records.jsonl"))
    asked.add_argument("--only", default=None, help="one word, instead of every record in the file")
    args = asked.parse_args()

    from core.learning.teaching_sources import RecordSource, WordRecord
    from core.semantics.grammar import GrammarView, closed_uses
    from core.semantics.grammar_words import GraphKnowledge, HeldWords
    from core.semantics.structure import StructureView
    from core.semantics.word_forms import HeldForms

    layers = [f.name for f in dataclasses.fields(WordRecord)]
    records = list(RecordSource(args.records).word_records())
    if args.only:
        records = [w for w in records if w.word == args.only]
    print(f"{len(records)} word record(s) from {args.records}")

    def emptied(record: Any, layer: str) -> Any:
        """The record with ONE layer emptied, its field left the kind it was (a count to 0, a run to ())."""
        was = getattr(record, layer)
        return dataclasses.replace(record, **{layer: type(was)()})

    landed: Dict[str, Counter] = {layer: Counter() for layer in layers}
    carried: Dict[str, int] = {layer: 0 for layer in layers}

    def held(record: Any) -> Dict[str, int]:
        """What is held after this record is taught into views holding nothing else, BOTH HALVES of teaching a word:
        English's grammar (`GrammarView.hold_word`) and memory's own views (`MemoryAgent._learn_word_record`)."""
        words = HeldWords(analysed=(), closed=closed_uses(), name_of=lambda w, c: w,
                          knowledge=GraphKnowledge(classes=None, names=None))
        structure = StructureView()
        view = GrammarView(words, structure=structure)
        forms, index, named = HeldForms(), {}, {}
        before = _snapshot(view) | _memorys(forms, structure, index, named)
        view.hold_word(record)
        # The other half, as `MemoryAgent._learn_word_record` does it, in its order.
        for item in record.forms_held():
            forms.hold(item)
        structure.hold_joins(record.joined_as, record.related_as)
        for written, classes in record.classes().items():
            bucket = index.setdefault(written, {})
            for cls, n in classes.items():
                bucket[cls] = bucket.get(cls, 0) + n
        for cls, name in record.names().items():
            for f in record.forms:
                if f.word_class == cls:
                    named.setdefault((f.form.lower(), cls), Counter())[name] += 1
        after = _snapshot(view) | _memorys(forms, structure, index, named)
        return {name: after[name] - before.get(name, 0) for name in after
                if after[name] != before.get(name, 0)}

    for record in records:
        whole = held(record)
        print(f"  {record.word:18} held whole: " + ", ".join(f"{k} +{v}" for k, v in sorted(whole.items())))
        for layer in layers:
            value = getattr(record, layer, None)
            n = len(value) if isinstance(value, (list, tuple, dict, set)) else (1 if value else 0)
            carried[layer] += n
            if not n or layer == "word":
                continue
            # WHAT THIS LAYER ALONE FEEDS: what stops landing when it alone is emptied.
            try:
                without = held(emptied(record, layer))
            except Exception as error:
                print(f"      {layer}: could not be emptied ({type(error).__name__}: {error})")
                continue
            for name, by in whole.items():
                lost = by - without.get(name, 0)
                if lost:
                    landed[layer][name] += lost

    print(f"\n{'layer':22} {'entries':>8} {'landed in':>10}  where")
    silent: List[str] = []
    for layer in layers:
        where = ", ".join(f"{name}" for name, _ in landed[layer].most_common(4))
        print(f"  {layer:22} {carried[layer]:>8} {len(landed[layer]):>10}  {where[:70]}")
        if carried[layer] and not landed[layer]:
            silent.append(layer)
    print(f"\nLAYERS CARRIED BY A RECORD AND LANDING NOWHERE ({len(silent)}): {', '.join(silent) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
