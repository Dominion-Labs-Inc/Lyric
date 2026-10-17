"""STRUCTURE-01: how the words of a sentence go together, as the main model learned it from a treebank.

The English Web Treebank's training part is taught to the store (`scripts/teach.py --source treebank`): each sentence
kept by memory as it was analysed, its standing a belief. This reads the store's own view of them (warmed from
memory, as the reader warms it) and measures, on the treebank's two parts held out from teaching:

- the class each word is used as, right;
- the word each depends on, right (UAS), and that with the relation (LAS);

then reads the prose of UNDERSTANDS-PROSE-01 and shows each sentence's phrases, and checks nothing was written.

Run (from the Lyric folder; starts no substrate, reads only):
    POSTGRES_DATABASE=lyric_db PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/STRUCTURE-01/experiment.py
"""
import asyncio
import contextlib
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
(HERE / "results").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler(HERE / "results" / "run.log", mode="w")])

TREEBANK = ROOT / "test_data" / "syntax" / "UD_English-EWT"
#: Fixed before the run, from the same method measured on the treebank's files (2026-10-16, dev): what the view read
#: from memory must reach, or what memory holds is not what was taught.
BARS = {"classes right": 0.91, "heads right (UAS)": 0.72, "heads and relations right (LAS)": 0.65}


def say(*a):
    print(*a, flush=True)


async def main() -> int:
    from experiments._evidence import RunRecord
    EV = RunRecord("STRUCTURE-01",
                   claim="the main model holds how the words of a sentence go together, learned from sentences "
                         "analysed by hand, and reads sentences it never held by it",
                   hypothesis="read from the store's own view, held-out treebank sentences reach the bars measured "
                              "for the method on the files (BARS)")
    quiet = io.StringIO()
    say("loading memory and its views (no substrate is started)…")
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        from core.database import get_unified_db
        from core.learning.teaching_sources import read_conllu
        from core.semantics.sentence_machine import form_of
        from core.semantics.derived_reader import live_view
        from core.semantics.structure import held_classes, words_of
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
        db = await get_unified_db()
        if not getattr(db, "initialized", False):
            await db.initialize()
    EV.check("the run is on the store it says", await EV.verify_database() is not None,
             f"connected to {EV.verified_database}")

    async def written():
        rows = await db.execute_query(
            "SELECT schemaname || '.' || relname AS name, n_tup_ins + n_tup_upd + n_tup_del AS n "
            "FROM pg_stat_user_tables")
        return {row["name"]: int(row["n"]) for row in rows or ()}
    before = await written()

    view = agent.structure_view()
    EV.check("memory holds the treebank's sentences as analysed", len(view) > 0, f"{len(view):,} sentences held")
    EV.metric("sentences held", len(view), unit="sentences")
    say(f"  {len(view):,} sentences held as analysed")

    # TWO WAYS, ONE LOAD: as the treebank alone decides, and with a word no sentence held used taking a class memory
    # holds of it (`StructureView.held_classes`), so the two are compared on the same view.
    asked = view.held_classes
    ways = (("treebank only", None), ("with memory's word classes", held_classes(live_view())))
    for way, held in ways:
        view.held_classes = held
        say(f"\n  {way}:")
        named = "" if held is None else f"{way}: "
        for part in ("dev", "test"):
            started = time.perf_counter()
            words = right_class = right_head = right_both = sentences = 0
            for analysed in read_conllu(str(TREEBANK / f"en_ewt-ud-{part}.conllu"), part):
                read = view.read(analysed.words)
                sentences += 1
                for i in range(len(analysed.words)):
                    words += 1
                    right_class += read.classes[i] == analysed.classes[i]
                    right_head += read.heads[i] == analysed.heads[i]
                    right_both += read.heads[i] == analysed.heads[i] and read.relations[i] == analysed.relations[i]
            values = {"classes right": right_class / words, "heads right (UAS)": right_head / words,
                      "heads and relations right (LAS)": right_both / words}
            say(f"  {part}: {sentences:,} sentences, {words:,} words, {time.perf_counter() - started:.0f}s")
            for label, value in values.items():
                EV.metric(f"{named}{part} {label}", round(value, 4), unit="fraction")
                EV.check(f"{named}{part}: {label} ≥ {BARS[label]:.0%}", value >= BARS[label], f"{value:.1%}")
                say(f"    {label:34} {value:.1%}  (bar {BARS[label]:.0%})")

    say("\nthe prose of UNDERSTANDS-PROSE-01, read (and where memory's word classes read it otherwise):")
    texts = json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text())
    shown, changed = [], 0
    kept = ("root", "nsubj", "nsubj:pass", "obj", "iobj", "obl", "conj", "acl:relcl", "nmod", "xcomp", "ccomp", "advcl")
    for text in texts:
        for sentence in text["text"]:
            reads = {}
            for way, held in ways:
                view.held_classes = held
                reads[way] = view.read(words_of(form_of(sentence)))
            alone, with_held = reads[ways[0][0]], reads[ways[1][0]]
            say(f"  {sentence}")
            for relation, head, phrase in alone.phrases():
                if relation in kept:
                    say(f"      {relation:10} {phrase}")
            if (alone.classes, alone.heads, alone.relations) != (with_held.classes, with_held.heads,
                                                                   with_held.relations):
                changed += 1
                say(f"    with memory's word classes:  " + " ".join(
                    f"{w}/{c}" for w, c in zip(with_held.words, with_held.classes)))
                for relation, head, phrase in with_held.phrases():
                    if relation in kept:
                        say(f"      {relation:10} {phrase}")
            shown.append({"sentence": sentence, **{way: {"classes": list(read.classes), "heads": list(read.heads),
                                                         "relations": list(read.relations)}
                                                   for way, read in reads.items()}})
    view.held_classes = asked
    EV.metric("prose sentences read otherwise with memory's word classes", changed, unit="sentences")
    say(f"\n  {changed} of {len(shown)} prose sentences read otherwise with memory's word classes")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (HERE / "results" / f"{stamp}_prose.json").write_text(json.dumps(shown, indent=1))

    await asyncio.sleep(1)
    after = await written()
    moved = {name: after[name] - before.get(name, 0) for name in after if after[name] != before.get(name, 0)}
    EV.check("reading wrote nothing to the store", not moved,
             "; ".join(f"{name} +{n}" for name, n in sorted(moved.items())) or "no table written to")
    path = EV.write()
    say(f"\n  run record: {path}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
