"""TRAIN-FORMAT-02: one word recorded whole teaches every part of Lyric's reading the word.

Claim. A word recorded with every form, every sense and how its verb is used (`teaching_sources.WordRecord`), taught
through the one teaching path (`scripts/teach.py --source records`), is held by memory as one memory, and every part
of reading learns its layer from it: the forms held each form, the word classes memory holds each form's class, what
the word names as each class, English's grammar its verb's frames and places. Sentences never taught that use the word
are then read: its past, its present, its -ing form, its passive, the verb alone, the noun; and through Lyric's front
door, what they said is answered.

Run on `lyric_dev2` after teaching (it holds the one sentence of TRAIN-FORMAT-01 too, which taught "Roy", "medal",
"the"; before the word, "Roy painted the medal." was read with "painted" a word nobody knew, no tense):

    PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 scripts/teach.py --source records \\
        --records experiments/TRAIN-FORMAT-02/records.jsonl
    PYTHONPATH="$PWD" POSTGRES_DATABASE=lyric_dev2 ./venv_lyric/bin/python3 experiments/TRAIN-FORMAT-02/experiment.py
"""
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

CLAIM = ("a word recorded whole, every form, every sense and how its verb is used, taught through the one teaching "
         "path, is held as one memory, every part of reading learns its layer from it, sentences never taught that "
         "use it are read right, and what they said is answered through the front door")

#: Sentences never taught, each with facts its reading must hold (the verb named `paint`; its time; who; what).
READ = [
    ("Roy painted the medal.", ["instance_of(?e, paint)", "precedes(?e, ?now)", "done_by(?e, roy)",
                                "done_to(?e, ?x)", "instance_of(?x, award decoration)"]),
    ("Roy paints the medal.", ["instance_of(?e, paint)", "done_by(?e, roy)", "done_to(?e, ?x)"]),
    ("Roy is painting the medal.", ["instance_of(?e, paint)", "during(?e, ?now)", "done_by(?e, roy)",
                                    "done_to(?e, ?x)"]),
    ("The medal was painted.", ["instance_of(?e, paint)", "precedes(?e, ?now)", "done_to(?e, ?x)",
                                "instance_of(?x, award decoration)"]),
    ("Roy painted.", ["instance_of(?e, paint)", "precedes(?e, ?now)", "done_by(?e, roy)"]),
    ("Roy painted the medal with paint.", ["instance_of(?e, paint)", "done_with(?e, ?y)",
                                          "instance_of(?y, coating paint)"]),
]
#: Never in the sentences before: present, -ing and passive; and "paints" never past.
NOT_READ = {"Roy paints the medal.": ["precedes(?e, ?now)"], "Roy is painting the medal.": ["precedes(?e, ?now)"]}


def say(*a):
    print(*a, flush=True)


def holds(meaning, wanted):
    """Whether a meaning holds facts of these shapes, one binding for its unknowns (`?e`, `?x`, `?y`) across them."""
    from core.semantics.derived_reader import is_variable
    facts = [(f.relation, f.subject, f.obj) for f in meaning.facts if f.positive]
    shapes = []
    for w in wanted:
        relation, rest = w.split("(", 1)
        subject, obj = (t.strip() for t in rest.rstrip(")").split(",", 1))
        shapes.append((relation, subject, obj))

    def match(at, bound):
        if at == len(shapes):
            return True
        relation, subject, obj = shapes[at]
        for r, s, o in facts:
            if r != relation:
                continue
            trial = dict(bound)
            ok = True
            for want, got in ((subject, s), (obj, o)):
                if want in ("?e", "?x", "?y"):
                    if trial.setdefault(want, got) != got or not is_variable(got):
                        ok = False
                elif want != got:
                    ok = False
            if ok and match(at + 1, trial):
                return True
        return False
    return match(0, {})


async def store_checks() -> int:
    from experiments._evidence import RunRecord
    from core.learning.teaching_sources import RecordSource, WordRecord
    from core.semantics.grammar_words import _verb_form
    EV = RunRecord("TRAIN-FORMAT-02", claim=CLAIM, hypothesis="every check holds", results_dir=HERE / "results")
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
    words = list(RecordSource(str(HERE / "records.jsonl")).word_records())
    say(f"{len(words)} taught word(s): {', '.join(w.word for w in words)}")

    # ── the record ──
    problems = {w.word: w.problems() for w in words if w.problems()}
    EV.check("every word record is whole: its forms of its senses' classes, the word itself among them, every sense "
             "named and said what it means, every place of the grammar's with what it says", not problems,
             json.dumps(problems)[:400])
    EV.check("each word record written and read back is the same record",
             all(WordRecord.from_dict(json.loads(json.dumps(w.to_dict()))) == w for w in words))

    # ── memory ──
    held = await agent._word_record_memories()
    EV.check("memory holds each taught word as one memory, the record as taught",
             sorted(w.key() for _, w in held) == sorted(w.key() for w in words), f"{len(held)} held")
    EV.check("memory reads none of them as a claim about the world",
             all(not (row.metadata or {}).get("facts") for row, _ in held))
    EV.check("memory holds each word's senses, what each means and what it is a kind of",
             all(any(s.means and s.kind_of for s in w.senses) for _, w in held))

    # ── each part of reading ──
    forms = agent.word_forms()
    unformed = [(f.form, w.word) for w in words for f in w.forms if w.word not in forms.bases_of(f.form)]
    EV.check("each form is held a form of its word (\"painted\", \"paints\", \"painting\" of paint)", not unformed,
             str(unformed))
    unclassed = [(f.form, f.word_class) for w in words for f in w.forms
                 if not agent.word_classes(f.form).get(f.word_class)]
    EV.check("memory knows each form's class (\"paint\" a verb and a noun, \"painted\" a verb)", not unclassed,
             str(unclassed))
    misnamed = [(w.word, cls, agent.name_of(w.word, cls), name) for w in words for cls, name in w.names().items()
                if agent.name_of(w.word, cls) != name]
    EV.check("the word names, as each class, what its most used sense of the class means (the verb `paint`, the noun "
             "`coating paint`)", not misnamed, str(misnamed))
    view = agent.grammar_view()
    held_words = view.grammar.lexicon.words
    EV.check("English's grammar holds each word", all(w.key() in view._words for w in words), f"{len(view._words)}")
    unkinded = [(s.concept, s.word_class, [k for _, k in s.kind_of], held_kinds)
                for w in words for s in w.senses
                for held_kinds in [view.grammar.lexicon.words.kinds(s.concept, s.word_class)]
                if not all(k in held_kinds for _, k in s.kind_of if k)]
    EV.check("the grammar knows what each sense is a kind of (`coating paint` a coating, the verb `paint` an act "
             "of creating), as it asks deciding a link", not unkinded, str(unkinded)[:300])
    for w in words:
        if not any(s.word_class == "VERB" for s in w.senses):
            continue
        name = held_words.name(w.word, "VERB")
        forms_of = {form: dict(held_words.verb_forms(form)) for form in {f.form for f in w.forms
                                                                         if f.word_class == "VERB"}}
        EV.check(f"the grammar reads each form of {w.word!r} as the form of its verb it is",
                 all(forms_of.get(f.form, {}).get(_verb_form(f.features)) for f in w.forms
                     if f.word_class == "VERB" and _verb_form(f.features)), json.dumps(forms_of))
        frames = dict(held_words.frames(name))
        EV.check(f"the grammar holds the frames {w.word!r} is used in ({', '.join(w.frames())})",
                 all(frames.get(f, 0) >= n for f, n in w.frames().items()), json.dumps(frames))
        roles = {slot: dict(view.grammar.lexicon.learned["role"].get((name, slot), {})) for slot, _ in w.links()}
        EV.check(f"the grammar holds what each place of {w.word!r} says "
                 f"({', '.join(f'{s} {l}' for s, l in w.links())})",
                 all(roles.get(slot, {}).get(link, 0) > 0 for slot, link in w.links()), json.dumps(roles))

    # ── sentences never taught ──
    for sentence, wanted in READ:
        reading = view.read(sentence)
        got = reading.meaning.canonical() if reading.meaning is not None else f"(not read: {reading.why})"
        right = reading.meaning is not None and holds(reading.meaning, wanted) and not any(
            holds(reading.meaning, [w]) for w in NOT_READ.get(sentence, []))
        say(f"  {sentence}\n    read: {got}")
        EV.check(f"{sentence!r} is read: {' & '.join(wanted)}", right, got)
    EV.write()
    return EV.failed


async def main() -> int:
    failed = await store_checks()
    say(f"\nstore and parts of reading: {'all held' if not failed else f'{failed} failed'}")
    import experiment as prose
    return max(failed, await prose.main("TRAIN-FORMAT-02", HERE, CLAIM))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
