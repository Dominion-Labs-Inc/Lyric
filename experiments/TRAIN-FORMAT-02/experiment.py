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
    ("Roy painted the medal for Tom.", ["instance_of(?e, paint)", "done_for(?e, tom)", "done_to(?e, ?x)"]),
    # WHICH SENSE, by what fills its places, as the hand-tagged data says: WordNet's own example of `coat paint` is
    # "We painted the rooms yellow", and SemCor's porch was coated; SemCor's annotators tagged "paint pictures" the
    # sense "make a painting of" (`represent paint`).
    ("Roy painted the wall.", ["instance_of(?e, coat paint)", "done_to(?e, ?x)", "instance_of(?x, wall)",
                               "precedes(?e, ?now)"]),
    ("Roy painted a picture.", ["instance_of(?e, represent paint)", "done_to(?e, ?x)", "instance_of(?x, picture)"]),
    # "for" with a verb no record joined it to: what the word itself says.
    ("Roy fastened the medal for Tom.", ["instance_of(?e, fasten)", "done_for(?e, tom)", "done_to(?e, ?x)"]),
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
    # ON THE SANDBOX LINE, NEVER THE MAIN STORE: the run needs a store holding the taught records and nothing
    # borrowed, which only an emptied sandbox gives (`scripts/reset_dev_store.py` empties `lyric_dev`; `lyric_dev2`
    # is the other sandbox and was where this ran first).
    EV.check("the run is on a sandbox store, never the main one",
             os.environ.get("POSTGRES_DATABASE", "") in ("lyric_dev", "lyric_dev2"),
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
             json.dumps(problems)[:400], reads=("word", "forms", "senses"))
    EV.check("each word record written and read back is the same record",
             all(WordRecord.from_dict(json.loads(json.dumps(w.to_dict()))) == w for w in words))
    # NOTE: that check reads no layer. It holds that the FORMAT survives being written and read back, which is a
    # different property from a part of reading reading a layer, and counting it as coverage would mark every
    # layer verified while nothing read one.

    # ── memory ──
    held = await agent._word_record_memories()
    EV.check("memory holds each taught word as one memory, the record as taught",
             sorted(w.key() for _, w in held) == sorted(w.key() for w in words), f"{len(held)} held")
    EV.check("memory reads none of them as a claim about the world",
             all(not (row.metadata or {}).get("facts") for row, _ in held))
    # A word WordNet has (a noun, a verb, ...) is held with its senses; a word it has none of ("for", "the") with its
    # uses, and a preposition with what it says joining a doing to a thing ("for", checked below) or a thing to a
    # thing ("of"). "the" is no preposition and joins nothing (it was taken for one, 2026-10-28). WordNet gives kinds
    # to nouns and verbs only (its adjectives and adverbs are ordered by likeness and opposites, not kinds): "some",
    # whose senses are WordNet's adjective and adverb, is a kind of nothing (2026-10-28).
    EV.check("memory holds each word's senses, what each means and, of a noun or a verb, what it is a kind of; a word "
             "WordNet has none of, its uses, and a preposition what it says",
             all(any(s.means and (s.kind_of or s.word_class not in ("NOUN", "VERB")) for s in w.senses) if w.senses else
                 (w.used_as and (w.joins or w.joins_things
                                 or not any(f.word_class == "PREPOSITION" for f in w.forms))) for _, w in held))

    # ── each part of reading ──
    forms = agent.word_forms()
    unformed = [(f.form, w.word) for w in words for f in w.forms if w.word not in forms.bases_of(f.form)]
    EV.check("each form is held a form of its word (\"painted\", \"paints\", \"painting\" of paint)", not unformed,
             str(unformed), reads=("forms",))
    unclassed = [(f.form, f.word_class) for w in words for f in w.forms
                 if not agent.word_classes(f.form).get(f.word_class)]
    EV.check("memory knows each form's class (\"paint\" a verb and a noun, \"painted\" a verb)", not unclassed,
             str(unclassed), reads=("forms",))
    lexicon = agent.grammar_view().grammar.lexicon
    unused = [(form, use, n, dict(lexicon.words.form_uses.get(form, {}))) for w in words for form, use, n in w.used_as
              if lexicon.words.form_uses.get(form, {}).get(use, 0) < n]
    EV.check("the grammar holds how the treebanks used each form, as its entries name the uses (\"for\" a "
             "preposition, a subordinator)", not unused, str(unused)[:300], reads=("used_as",))
    unjoined = [(w.word, link, n) for w in words for link, n in w.joins
                if lexicon.learned["prep"].get((w.word, "event", "-"), {}).get(link, 0) < n]
    EV.check("the grammar holds what each preposition says joining a doing to a thing (\"for\" done_for, "
             "has_purpose)", not unjoined, str(unjoined), reads=("joins",))
    misnamed = [(w.word, cls, agent.name_of(w.word, cls), name) for w in words for cls, name in w.names().items()
                if agent.name_of(w.word, cls) != name]
    EV.check("the word names, as each class, what its most used sense of the class means (the verb `paint`, the noun "
             "`coating paint`)", not misnamed, str(misnamed), reads=("senses",))
    view = agent.grammar_view()
    held_words = view.grammar.lexicon.words
    EV.check("English's grammar holds each word", all(w.key() in view._words for w in words), f"{len(view._words)}", reads=("word",))
    joined = {s.id: (s.roleset, s.verbnet) for w in words for s in w.senses if s.word_class == "VERB"}
    EV.check("each verb sense PropBank and VerbNet say is the word's carries its PropBank sense and its places "
             "(paint.v.01 paint.02 create pictures, paint.v.02 paint.01 put paint on a surface, paint.v.03 paint.03 "
             "depict)", all(not s.roleset or s.places for w in words for s in w.senses)
             and any(r for r, _ in joined.values()), json.dumps(joined), reads=("senses", "rolesets"))
    unkinded = [(s.concept, s.word_class, [k for _, k in s.kind_of], held_kinds)
                for w in words for s in w.senses
                for held_kinds in [view.grammar.lexicon.words.kinds(s.concept, s.word_class)]
                if not all(k in held_kinds for _, k in s.kind_of if k)]
    EV.check("the grammar knows what each sense is a kind of (`coating paint` a coating, the verb `paint` an act "
             "of creating), as it asks deciding a link", not unkinded, str(unkinded)[:300], reads=("senses",))
    for w in words:
        if not any(s.word_class == "VERB" for s in w.senses):
            continue
        name = held_words.name(w.word, "VERB")
        forms_of = {form: dict(held_words.verb_forms(form)) for form in {f.form for f in w.forms
                                                                         if f.word_class == "VERB"}}
        EV.check(f"the grammar reads each form of {w.word!r} as the form of its verb it is",
                 all(forms_of.get(f.form, {}).get(_verb_form(f.features)) for f in w.forms
                     if f.word_class == "VERB" and _verb_form(f.features)), json.dumps(forms_of), reads=("forms",))
        frames = dict(held_words.frames(name))
        EV.check(f"the grammar holds the frames {w.word!r} is used in ({', '.join(w.frames())})",
                 all(frames.get(f, 0) >= n for f, n in w.frames().items()), json.dumps(frames),
                 reads=("verbnet_frames",))
        # A doer after "by" the grammar reads by the subject's link: shown by reading "... was painted by Roy." below.
        places = [(slot, link) for slot, link in w.links() if slot != "by"]
        roles = {slot: dict(view.grammar.lexicon.learned["role"].get((name, slot), {})) for slot, _ in places}
        EV.check(f"the grammar holds what each place of {w.word!r} says "
                 f"({', '.join(f'{s} {l}' for s, l in places)})",
                 all(roles.get(slot, {}).get(link, 0) > 0 for slot, link in places), json.dumps(roles),
                 reads=("rolesets",))
        after = {p: dict(view.grammar.lexicon.learned["prep_of"].get((name, p, "-"), {})) for p, _ in w.prepositions()}
        EV.check(f"the grammar holds what a preposition after {w.word!r} says "
                 f"({', '.join(f'{p} {l}' for p, l in w.prepositions())})",
                 all(after.get(p, {}).get(link, 0) > 0 for p, link in w.prepositions()), json.dumps(after),
                 reads=("rolesets",))

    # ── how each form is said, the subjects each finite form took ──
    unsaid = [(f.form, w.word) for w in words for f in w.forms if f.sounds
              and not set(f.sounds) <= set(held_words.sounds(f.form))]
    EV.check("the grammar holds how each form is said (\"wall\" W AO1 L)", not unsaid, str(unsaid)[:300], reads=("forms",))
    alike = {f.form for w in words for f in w.forms if f.before}
    unalike = [form for form in alike if len(held_words.said_before(form)) < 2]
    EV.check("the grammar holds which forms are said alike and the first sounds said after each (\"a\" and \"an\")",
             alike and not unalike, f"{sorted(alike)}; not held: {unalike}", reads=("forms",))
    untaken = [(f.form, w.word) for w in words for f in w.forms
               if f.subjects and not held_words.subjects(f.form)]
    EV.check("the grammar holds the subjects each finite form took (\"is\" nouns, \"am\" I)", not untaken,
             str(untaken)[:300], reads=("forms",))

    # ── what each word means, and each word read back in its own examples ──
    unmeant = [w.word for w in words if w.senses and not agent.word_meanings(w.word)]
    EV.check("memory says what each word means, every sense with its definition and kind (`word_meanings`)",
             not unmeant, str(unmeant), reads=("senses",))
    reviews = {w.word: view.review_word(w) for w in words}
    every = sum(len(s.examples) for w in words for s in w.senses)
    EV.check("each word is read back in every example of every sense", sum(len(r) for r in reviews.values()) == every,
             f"{sum(len(r) for r in reviews.values())} of {every}")
    known_all = [r for rs in reviews.values() for r in rs if not r["unknown"]]
    missed = [(r["example"], r["sense"]) for r in known_all if not (r["read"] and r["in_sense"])]
    EV.check(f"every example whose words are all taught ({len(known_all)}) is read whole, the word in its sense",
             not missed, str(missed)[:300])
    unknown = sorted({u for rs in reviews.values() for r in rs for u in r["unknown"]})
    say(f"  examples: {every}; read {sum(r['read'] for rs in reviews.values() for r in rs)}, in their sense "
        f"{sum(r['in_sense'] for rs in reviews.values() for r in rs)}; words not yet taught: {', '.join(unknown)}")
    EV.note(f"words the examples hold that nothing taught holds yet: {', '.join(unknown)}")

    # ── sentences never taught ──
    for sentence, wanted in READ:
        unknown = [t for t in sentence.rstrip(".").split()[1:] if t.lower() in ("for",)
                   and "PREPOSITION" not in agent.word_classes(t.lower())]
        if unknown:
            # A SENTENCE WITH A WORD NOT YET TAUGHT tests that word, not this one: "for" is no preposition to a store
            # taught only "paint" and one sentence (its only use the grammar's own, "a tool for cutting").
            say(f"  {sentence}\n    not tested: {', '.join(unknown)} not taught yet")
            EV.note(f"{sentence!r} not tested: {', '.join(unknown)} not taught yet")
            continue
        reading = view.read(sentence)
        got = reading.meaning.canonical() if reading.meaning is not None else f"(not read: {reading.why})"
        right = reading.meaning is not None and holds(reading.meaning, wanted) and not any(
            holds(reading.meaning, [w]) for w in NOT_READ.get(sentence, []))
        say(f"  {sentence}\n    read: {got}")
        EV.check(f"{sentence!r} is read: {' & '.join(wanted)}", right, got)

    # ── saying what the words mean, by the grammar they are read by ──
    from core.semantics.derived_reader import Meaning, MeaningFact
    for better, worse in (("A wall is a partition.", "A wall am a partition."),
                          # Of taught words only: "partitions" is none, and was read a quality in one and a thing
                          # in the other (2026-10-28).
                          ("Pictures are representations.", "Pictures is representations."),
                          ("A picture is a representation.", "An picture is a representation.")):
        sure = {text: view.read(text) for text in (better, worse)}
        scores = {text: r.sign.score if r.sign is not None else None for text, r in sure.items()}
        EV.check(f"{better!r} is read more surely than {worse!r}", None not in scores.values()
                 and scores[better] > scores[worse], json.dumps(scores))
    said = view.say(Meaning("tell", (MeaningFact("isa", "wall", "partition"),)))
    say(f"  said of a wall being a partition, first: {said[:6]}")
    EV.check("a wall being a partition is said first as English says it: \"A wall is a partition.\"",
             bool(said) and said[0] == "A wall is a partition.", json.dumps(said[:6]))

    # ── reasoning over what the words mean ──
    # The yes of each question below is scored through the front door (`texts.json`, "kinds"); here, that reasoning
    # is handed the words' meanings as premises, and what must NOT follow does not.
    from core.agents.autonomous.autonomous_coordinator import get_conversation
    told = get_conversation("tf02_reasoning_wall", remembers=False)
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        await told.understand("Roy painted the wall.", look_up=False)
        premises = await told._held_premises("Is a wall a structure?", await told.resolve("Is a wall a structure?"),
                                             None)
    wall_id = agent._word_record_ids.get(next(w.key() for w in words if w.word == "wall"))
    handed = [(p.statement, p.provenance_kind, p.provenance) for p in premises]
    EV.check("the reasoning owner is handed what the words mean, each premise from the word record saying it "
             "(\"wall\": a partition, a structure, an artifact)",
             ("wall_structure", "word", wall_id) in handed and ("wall_partition", "word", wall_id) in handed,
             str(handed)[:300])

    async def asked(conversation, question):
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            u = await conversation.understand(question, look_up=False)
        return u

    for question in ("Is a wall a substance?", "Did Roy coat the picture?", "Did Roy make something?"):
        u = await asked(told, question)
        EV.check(f"told \"Roy painted the wall.\", {question!r} is no yes (a wall is no substance; no picture was "
                 f"coated; a coating is no making)", not any(a.verdict for a in u.answers or []), repr(u.reply))
    u = await asked(told, "Is a structure a wall?")
    EV.check("\"Is a structure a wall?\" is answered by what the words hold to be both, a wall being a structure, "
             "and no yes", [(a.about, a.relation, tuple(a.others), a.verdict) for a in u.answers]
             == [("wall", "isa", ("structure",), None)], repr(u.reply))
    u = await asked(told, "Is a picture a wall?")
    EV.check("\"Is a picture a wall?\", neither held a kind of the other, is answered by what each is, and no yes "
             "or no", sorted((a.about, tuple(a.others), a.verdict) for a in u.answers)
             == [("picture", ("representation",), None), ("wall", ("partition",), None)], repr(u.reply))
    replies = [(await asked(told, q)).reply for q in ("Did Roy coat the wall?", "Is a structure a wall?")]
    EV.check("no reply says it holds nothing of a word taught", not any("nothing for" in r for r in replies),
             repr(replies))
    painted = get_conversation("tf02_reasoning_picture", remembers=False)
    await asked(painted, "Roy painted a picture.")
    u = await asked(painted, "Did Roy coat the picture?")
    EV.check("told \"Roy painted a picture.\", \"Did Roy coat the picture?\" is no yes (painting a picture is a "
             "making, no coating)", not any(a.verdict for a in u.answers or []), repr(u.reply))
    EV.write()
    return EV.failed


async def main() -> int:
    failed = await store_checks()
    say(f"\nstore and parts of reading: {'all held' if not failed else f'{failed} failed'}")
    import experiment as prose
    return max(failed, await prose.main("TRAIN-FORMAT-02", HERE, CLAIM))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
