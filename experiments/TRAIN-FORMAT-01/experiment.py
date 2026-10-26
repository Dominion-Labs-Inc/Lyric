"""TRAIN-FORMAT-01: one sentence recorded whole teaches every part of Lyric's reading, in a store that held nothing.

Claim. A sentence recorded with every layer by word position (`teaching_sources.SentenceRecord`), taught through the
one teaching path (`scripts/teach.py --source records`), is held by memory as one memory, and every part of reading
learns its layer from it: the structure reader its words and what each is joined to, the forms held each word's
form, English's grammar its derivation and its meaning. Read back, the sentence means what it was taught to mean;
asked of through Lyric's front door, what it said is answered.

Run on `lyric_dev2` (an instance that held nothing before the records were taught), after teaching:

    PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 scripts/teach.py --source records \\
        --records experiments/TRAIN-FORMAT-01/records.jsonl
    PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-01/experiment.py

Part one checks the store and each part of reading (read only); part two tells and asks the texts of `texts.json` as
UNDERSTANDS-PROSE-01's harness does (a conversation of its own, held not to remember)."""
import asyncio
import contextlib
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "experiments" / "UNDERSTANDS-PROSE-01"))

CLAIM = ("a sentence recorded whole, every layer by word position, taught through the one teaching path, is held as "
         "one memory, every part of reading learns its layer from it, it is read back as taught, and what it said is "
         "answered through the front door")


def say(*a):
    print(*a, flush=True)


async def store_checks() -> int:
    from experiments._evidence import RunRecord
    from core.learning.teaching_sources import RecordSource, SentenceRecord
    EV = RunRecord("TRAIN-FORMAT-01", claim=CLAIM, hypothesis="every check holds", results_dir=HERE / "results")
    EV.check("the run is on lyric_dev2", os.environ.get("POSTGRES_DATABASE") == "lyric_dev2",
             os.environ.get("POSTGRES_DATABASE", ""))
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from core.agents.memory_agent import get_memory_agent
        agent = await get_memory_agent()
        await agent.initialize()
        await agent.warm_word_classes()
        await agent.stop_memory_loops()
    EV.check("the store is the one it says", await EV.verify_database() is not None, f"{EV.verified_database}")
    path = HERE / "records.jsonl"
    records = list(RecordSource(str(path)).sentence_records())
    say(f"{len(records)} taught record(s) in {path.name}")

    # ── the records ──
    problems = {r.id: r.problems() for r in records if r.problems()}
    EV.check("every record is whole: every layer of every word, the derivation combining every word once, every "
             "term of the meaning said by a word of the sentence, every fact with the words saying it", not problems,
             json.dumps(problems)[:400])
    EV.check("each record written and read back is the same record",
             all(SentenceRecord.from_dict(json.loads(json.dumps(r.to_dict()))) == r for r in records))

    # ── memory ──
    held = await agent._record_memories()
    held_keys = sorted(r.key() for _, r in held)
    EV.check("memory holds each taught record as one memory, the record as taught",
             held_keys == sorted(r.key() for r in records), f"{len(held)} held")
    EV.check("memory reads none of them as a claim about the world",
             all(not (row.metadata or {}).get("facts") for row, _ in held))

    # ── each part of reading ──
    structure = agent.structure_view()
    EV.check("the structure reader holds each record's words, classes and what each is joined to",
             all(r.analysed().key() in structure for r in records), f"{len(structure)} analysed")
    forms = agent.word_forms()
    unformed = [(w.form, w.lemma) for r in records for w in r.words
                if w.word_class not in ("PUNCTUATION", "SYMBOL") and w.lemma.lower() not in forms.bases_of(w.form)]
    EV.check("each word's form is held a form of its base (\"fastened\" of fasten)", not unformed, str(unformed))
    unclassed = [(w.form, w.word_class) for r in records for w in r.words if w.word_class not in
                 ("PUNCTUATION", "SYMBOL") and not agent.word_classes(w.form.lower()).get(w.word_class)]
    EV.check("memory knows each word's class as the record uses it (the conversation asks it whether a word is "
             "known)", not unclassed, str(unclassed))
    from core.semantics.derived_reader import is_variable
    misnamed = []
    for r in records:
        said = dict(r.terms)
        for f in r.facts:
            words = said.get(f.subject) or ()
            if f.relation == "instance_of" and f.positive and not is_variable(f.obj) and len(words) == 1:
                w = r.words[words[0]]
                if w.word_class in ("NOUN", "NAME") and agent.name_of(w.form, w.word_class) != f.obj:
                    misnamed.append((w.form, agent.name_of(w.form, w.word_class), f.obj))
    EV.check("each word names what the record's meaning names it (\"medal\": award decoration)", not misnamed,
             str(misnamed))
    view = agent.grammar_view()
    EV.check("English's grammar holds each record's derivation", all(r.derived().key() in view._derived
                                                                     for r in records), f"{len(view._derived)}")
    lexicon = view.grammar.lexicon
    uncounted = [w.form for r in records for w in r.words
                 if w.word_class != "PUNCTUATION" and not lexicon.derived["uses"].get(w.form.lower())]
    EV.check("what each word takes beside the words around it is counted from the derivation", not uncounted,
             str(uncounted))
    for r in records:
        reading = view.read(r.text)
        got = reading.meaning.canonical() if reading.meaning is not None else f"(not read: {reading.why})"
        say(f"  read back: {r.text}\n    taught: {r.meaning().canonical()}\n    read:   {got}")
        EV.check(f"{r.text!r} is read back as its taught meaning", got == r.meaning().canonical(), got)
    EV.check("English's grammar learned from each record's meaning",
             all(r.taught().key() in view._counted for r in records), f"{len(view._counted)} learned")
    learned = {(table, key, link) for table, keyed in lexicon.learned.items() for key, links in keyed.items()
               for link, n in links.items() if n > 0}
    for r in records:
        for f in r.facts:
            marks = [r.words[k].lemma for k in f.words if r.words[k].word_class == "PREPOSITION"]
            for mark in marks:
                EV.check(f"the preposition {mark!r} was learned as saying {f.relation}",
                         any(mark in [str(x) for x in (key if isinstance(key, tuple) else (key,))] and link == f.relation
                             for _, key, link in learned), str(sorted(learned))[:300])
    EV.write()
    return EV.failed


async def main() -> int:
    failed = await store_checks()
    say(f"\nstore and parts of reading: {'all held' if not failed else f'{failed} failed'}")
    import experiment as prose
    return max(failed, await prose.main("TRAIN-FORMAT-01", HERE, CLAIM))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
