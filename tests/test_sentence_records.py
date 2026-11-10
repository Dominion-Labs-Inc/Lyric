"""A sentence recorded whole (`teaching_sources.SentenceRecord`): every layer by word position, checked, and each part
of reading given its layer of it (TRAIN-FORMAT-01). No store: the record and memory's views are built here."""
import json

from core.learning.teaching_sources import RecordFact, RecordWord, SentenceRecord
from core.semantics import grammar as gm

TEXT = "Tom chased a cat."


def _record(**changed) -> SentenceRecord:
    words = (RecordWord(0, "Tom", 0, 3, "tom", "NAME", "NNP", "Number=Sing", "n", 1, "nsubj"),
             RecordWord(1, "chased", 4, 10, "chase", "VERB", "VBD", "Mood=Ind|Tense=Past|VerbForm=Fin",
                        "(s:dcl\\np)/np", -1, "root"),
             RecordWord(2, "a", 11, 12, "a", "DETERMINER", "DT", "", "np/n", 3, "det"),
             RecordWord(3, "cat", 13, 16, "cat", "NOUN", "NN", "Number=Sing", "n", 1, "obj"),
             RecordWord(4, ".", 16, 17, ".", "PUNCTUATION", ".", "", ".", 1, "punct"))
    facts = (RecordFact("instance_of", "?v0", "chase", words=(1,)),
             RecordFact("precedes", "?v0", "?now", words=(1,)),
             RecordFact("done_by", "?v0", "tom", words=(0, 1)),
             RecordFact("done_to", "?v0", "?v1", words=(1, 3)),
             RecordFact("instance_of", "?v1", "true cat", words=(3,)))
    fields = dict(id="pmb/p00/d0001#1", text=TEXT, act="tell", words=words, facts=facts,
                  terms=(("tom", (0,)), ("?v0", (1,)), ("chase", (1,)), ("?v1", (3,)), ("true cat", (3,))),
                  tree=("rp", "s:dcl", ("ba", "s:dcl", ("lx", "np", "n", 0),
                                        ("fa", "s:dcl\\np", 1, ("fa", "np", 2, 3))), 4))
    fields.update(changed)
    return SentenceRecord(**fields)


def test_a_record_is_whole_and_reads_back_the_same():
    record = _record()
    assert record.problems() == []
    assert SentenceRecord.from_dict(json.loads(json.dumps(record.to_dict()))) == record
    assert record.meaning().canonical() == ("tell: done_by(?v0, tom) & done_to(?v0, ?v1) & instance_of(?v0, chase) & "
                                            "instance_of(?v1, true cat) & precedes(?v0, ?now)")


def test_each_layer_is_given_as_the_part_of_reading_that_learns_from_it_takes_it():
    record = _record()
    analysed = record.analysed()
    assert analysed.words == ("Tom", "chased", "a", "cat", ".") and analysed.heads == (2, 0, 4, 2, 2)
    assert analysed.relations == ("nsubj", "root", "det", "obj", "punct")
    derived = record.derived()
    assert derived.categories[1] == "(s:dcl\\np)/np" and derived.said_in == "pmb/p00/d0001" and derived.part == 1
    taught = record.taught()
    assert taught.said_in == derived.said_in, "the grammar learns a meaning with the derivation of its document"
    assert gm.align_by_anchors(("Tom", "chased", "a", "cat", "."), TEXT, taught.anchors)["true cat"] == [3]
    forms = {f.base: f.forms for f in record.forms()}
    assert forms["chase"] == (("chased", "Mood=Ind|Tense=Past|VerbForm=Fin", 1),)


def test_a_record_whose_layers_do_not_hold_together_is_said_wrong():
    assert any("no word says ?v1" in p for p in _record(terms=(("tom", (0,)), ("?v0", (1,)))).problems())
    circled = list(_record().words)
    circled[1] = RecordWord(1, "chased", 4, 10, "chase", "VERB", "VBD", "", "(s:dcl\\np)/np", 3, "root")
    problems = _record(words=tuple(circled)).problems()
    assert any("are the sentence's own" in p for p in problems) and any("circle" in p for p in problems)
    moved = list(_record().words)
    moved[3] = RecordWord(3, "cat", 12, 15, "cat", "NOUN", "NN", "", "n", 1, "obj")
    assert any("'cat' is not at 12-15" in p for p in _record(words=tuple(moved)).problems())


def test_memory_learns_each_words_class_and_name_from_a_record():
    from core.agents.memory_agent import MemoryAgent
    agent = MemoryAgent()
    index = {}
    agent._learn_record_words(_record(), index)
    assert index["chased"] == {"VERB": 1} and index["chase"] == {"VERB": 1} and index["a"] == {"DETERMINER": 1}
    assert agent.name_of("cat", "NOUN") == "true cat", "as the record's meaning names it"


def test_a_word_of_the_grammars_own_no_sentence_held_is_never_a_name():
    from core.semantics.grammar_words import HeldWords
    words = HeldWords((), gm.closed_uses(), lambda word, cls: word.lower())
    assert "NAME" not in words.uses("Who") and "wh:subject" in words.uses("Who")
    assert words.uses("Zork") == {"NAME": 1.0}


def test_a_reading_by_the_grammar_holds_what_each_word_named():
    from core.semantics.derived_reader import _said_by_words
    from tests.test_grammar import Held
    grammar = gm.Grammar(gm.Lexicon(Held()))
    read = grammar.read(gm.tokens_of("The dog chased a cat.", grammar.lexicon.words))
    said = {(" ".join(c.words), c.value) for c in _said_by_words(read)}
    assert said == {("dog", "dog"), ("chased", "chase"), ("cat", "cat")}


# ── a word recorded whole ─────────────────────────────────────────────────────────────────────────────────────────

def _word(**changed):
    from core.learning.teaching_sources import WordForm, WordPlace, WordRecord, WordSense, WordUse
    fields = dict(
        word="paint",
        forms=(WordForm("paint", "VERB", "VerbForm=Inf"), WordForm("painted", "VERB", "Tense=Past|VerbForm=Fin", 2),
               WordForm("paints", "VERB", "Number=Sing|Person=3|Tense=Pres|VerbForm=Fin", 1),
               WordForm("paint", "NOUN", "Number=Sing")),
        senses=(WordSense("paint.v.01", "VERB", "paint", "make a painting", (("create.v.03", "act create"),), 17,
                          (), ("intransitive", "transitive")),
                WordSense("paint.v.02", "VERB", "coat paint", "apply paint to", (("coat.v.01", "to coat"),), 13, (),
                          ("transitive",)),
                WordSense("paint.n.01", "NOUN", "coating paint", "a substance used as a coating",
                          (("coating.n.01", "coating"),), 7)),
        uses=(WordUse("paint.02", "create pictures with paint",
                      (WordPlace("ARG0", "artist", "PAG", ("by",), True, (("subject", "done_by"), ("by", "done_by"))),
                       WordPlace("ARG1", "art", "PPT", (), True, (("object", "done_to"),)),
                       WordPlace("ARG2", "benefactive", "GOL", ("for", "in"), False, (("pp:for", "done_for"),)))),))
    fields.update(changed)
    return WordRecord(**fields)


def test_a_word_record_is_whole_and_reads_back_the_same():
    from core.learning.teaching_sources import WordRecord
    word = _word()
    assert word.problems() == []
    assert WordRecord.from_dict(json.loads(json.dumps(word.to_dict()))) == word
    assert word.names() == {"NOUN": "coating paint", "VERB": "paint"}, "each class by its most used sense"
    assert word.frames() == {"intransitive": 17, "transitive": 30}
    assert word.links() == {("subject", "done_by"): 1, ("by", "done_by"): 1, ("object", "done_to"): 1}
    assert word.prepositions() == {("for", "done_for"): 1}, "\"in\" disagrees with the goal it is tagged: no link"


def test_a_word_record_that_does_not_hold_together_is_said_wrong():
    from core.learning.teaching_sources import WordForm
    assert any("which no sense of the word is" in p
               for p in _word(forms=_word().forms + (WordForm("painty", "ADJECTIVE"),)).problems())
    assert any("not among its forms" in p for p in _word(forms=_word().forms[1:]).problems())


def test_a_verbs_place_is_linked_only_where_its_function_and_preposition_agree():
    from core.learning.teaching_sources import _PLACE_LINKS
    assert _PLACE_LINKS[("GOL", "for")] == ("pp:for", "done_for") and ("GOL", "in") not in _PLACE_LINKS
    assert _PLACE_LINKS[("PAG", "by")] == ("by", "done_by") and _PLACE_LINKS[("PPT", "")] == ("object", "done_to")


def test_a_verbnet_frames_places_are_linked_as_the_pmb_links_their_roles():
    """Each place of a VerbNet frame, as the grammar names it and the PMB links the role VerbNet gives it
    (`_frame_places`): "at" a Patient's after "swat"; of two things after the verb the first the `second`; a Theme
    with no role of the frame doing it does the happening ("The bus collided with a truck."); an Experiencer beside a
    doer is what it is done to ("The tiger licked him.")."""
    import xml.etree.ElementTree as ET
    from core.learning.teaching_sources import _frame_places

    def places(*said: str) -> tuple:
        return _frame_places(ET.fromstring("<FRAME><SYNTAX>" + "".join(said) + "</SYNTAX></FRAME>"))
    assert places('<NP value="Agent"/>', "<VERB/>", '<LEX value="at"/>', '<NP value="Patient"/>') == (
        ("pp:at", "done_to"), ("subject", "done_by"))
    assert places('<NP value="Agent"/>', "<VERB/>", '<NP value="Recipient"/>', '<NP value="Theme"/>') == (
        ("object", "done_to"), ("second", "received_by"), ("subject", "done_by"))
    assert places('<NP value="Theme"/>', "<VERB/>", '<PREP value="against into"/>', '<NP value="Location"/>') == (
        ("pp:against", "located_in"), ("pp:into", "located_in"), ("subject", "done_by"))
    assert places('<NP value="Patient"/>', "<VERB/>") == (("subject", "done_to"),), "the one dying it is done to"
    assert places('<NP value="Agent"/>', "<VERB/>", '<NP value="Experiencer"/>') == (
        ("object", "done_to"), ("subject", "done_by")), "the one licked it is done to"
    assert places('<NP value="Experiencer"/>', "<VERB/>", '<NP value="Stimulus"/>') == (
        ("object", "done_to"), ("subject", "done_by")), "who experiences it does it, no doer said beside it"
    assert places('<NP value="Agent"/>', "<VERB/>", '<NP value="Attribute"/>') == (("subject", "done_by"),), \
        "a role with no link Lyric holds says nothing"


def test_a_verbs_frames_are_held_by_sense_and_say_each_place_by_the_places_said_with_it():
    """A verb recorded with its VerbNet frames and each sense's classes (`WordRecord.frames_said`): a sense's frames
    are its classes' and those they are part of; the word's every frame. The grammar holds them (`frames_said`),
    links a place by them (`Lexicon.places_framed`), and takes them back whole."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import HeldWords
    conative = (("pp:at", "done_to"), ("subject", "done_by"))
    hit = (("object", "done_to"), ("subject", "done_by"))
    peck = WordRecord("peck", (WordForm("peck", "VERB", "VerbForm=Inf", 3),),
                      (WordSense("peck.v.01", "VERB", "peck", "eat by pecking at", (), 2,
                                 verbnet_classes=("chew-39.2-1",)),
                       WordSense("nag.v.01", "VERB", "nag", "bother persistently", (), 1)),
                      verbnet_frames=(("chew-39.2", "NP V PP-Conative", "", "Cynthia nibbled at the carrot.", conative),
                                      ("swat-18.2", "NP V NP", "", "Paula swatted the fly.", hit)))
    assert not peck.problems(), peck.problems()
    assert WordRecord.from_dict(json.loads(json.dumps(peck.to_dict()))) == peck
    said = peck.frames_said()
    assert said["peck"] == {conative: 1}, "chew-39.2-1 is part of chew-39.2; swat-18.2 is no class of the sense"
    assert said[""] == {conative: 1, hit: 1} and "nag" not in said
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    view.hold_word(peck)
    lexicon, name = view.grammar.lexicon, view.words.name("peck", "VERB")
    # ASKED FOR THE WHOLE HAPPENING'S PLACES AT ONCE, which is the only way a frame may be read (`places_framed`:
    # a frame is one analysis of a happening, never a place at a time, which is what `Lexicon.framed` answered
    # before it was taken out).
    assert lexicon.places_framed(name, "peck", ["subject", "pp:at"]).get("pp:at") == "done_to"
    assert lexicon.places_framed(name, "nag", ["subject", "pp:at"]).get("pp:at") == "done_to", \
        "a sense with no frames of its own is read by the word's"
    # A SENSE'S OWN FRAMES ARE THE WHOLE OF WHAT IT SAYS: `peck` has the conative frame, which names no object, so
    # no object is said of it and the word's transitive frame does not reach in. `nag` has frames of none of its
    # own, and is read by the word's, object and all.
    assert lexicon.places_framed(name, "peck", ["subject", "object"]) == {"subject": "done_by"}
    assert lexicon.places_framed(name, "nag", ["subject", "object"]) == {"subject": "done_by",
                                                                        "object": "done_to"}
    assert not lexicon.taught_role(name, "subject"), "what its PropBank places say is no sentence taught"
    view.drop_word(peck)
    assert not any(lexicon.frames_said[name].values())


def test_a_wordnet_frame_is_named_as_the_grammar_names_frames():
    from core.learning.teaching_sources import _frame_named
    assert _frame_named("Somebody %s something") == "transitive"
    assert _frame_named("Somebody %s") == "intransitive"
    assert _frame_named("Somebody %s somebody something") == "ditransitive"
    assert _frame_named("Somebody %s that CLAUSE") == "that"


def test_memory_learns_a_words_forms_classes_and_names_and_the_grammar_its_frames_and_places():
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.grammar_words import HeldWords
    from core.semantics.word_forms import HeldForms
    agent, index, forms = MemoryAgent(), {}, HeldForms()
    word = _word()
    agent._learn_word_record(word, index, forms, agent.structure_view())
    assert forms.bases_of("painted") == ["paint"] and index["paints"] == {"VERB": 1}
    assert agent.name_of("paint", "VERB") == "paint" and agent.name_of("paint", "NOUN") == "coating paint"
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), agent.name_of, forms=forms))
    view.hold_word(word)
    assert dict(view.words.frames("paint")) == {"intransitive": 17.0, "transitive": 30.0}
    assert view.grammar.lexicon.learned["role"][("paint", "subject")] == {"done_by": 1}
    assert view.grammar.lexicon.learned["prep_of"][("paint", "for", "-")] == {"done_for": 1}
    view.drop_word(word)
    assert not view.words.frames("paint") and not view.grammar.lexicon.learned["role"][("paint", "subject")]


def test_a_link_held_as_its_word_gives_way_to_one_taught_saying():
    from collections import Counter
    assert gm._weighed(Counter({"done_with": 1}), "word_with") == "done_with"
    assert gm._weighed(Counter(), "word_with") == "word_with"
    assert gm._weighed(Counter({"has_purpose": 1}), "done_by") == "done_by", "a rule of the grammar's ties and stands"


def test_every_kind_of_taught_language_memory_holds_is_kept_out_of_recall():
    """What memory holds of how English goes is no knowledge of the world: every kind of language record it keeps
    (`MemoryAgent`'s tags for them) is held back from recall (`memory_filter.exemption_for`). The PMB's derivations and
    the records were left out when they were made, and "What is a wall?" read the word's record as a claim (148 s)."""
    from core.agents.memory_agent import MemoryAgent
    from core.memory.utils.memory_filter import get_memory_filter
    tags = [MemoryAgent.STRUCTURE_TAG, MemoryAgent.DERIVED_TAG, MemoryAgent.RECORD_TAG, MemoryAgent.WORD_RECORD_TAG,
            MemoryAgent.READ_ENGLISH_TAG, MemoryAgent.TAUGHT_SENTENCE_TAG, MemoryAgent.ARGUED_TAG,
            MemoryAgent.WORD_FORMS_TAG, MemoryAgent.WORD_GROUP_TAG]
    assert [t for t in tags if get_memory_filter().exemption_for(tags=["language", t]) is None] == []
    assert all(MemoryAgent.IMPORTANCE_BY_KIND.get(t) == 0.6 for t in tags[:5])


def test_memory_hands_reasoning_what_a_word_means():
    """What a thing is a kind of, as the words recorded whole say it, each with the memory of the record saying so
    (`MemoryAgent.word_kinds`); the senses a word written so may mean (`word_senses_alike`); a thing the words hold to
    be both of two (`word_held_as_both`). Told nothing of walls, "Is a wall a structure?" was handed no premise."""
    from core.agents.memory_agent import MemoryAgent
    agent = MemoryAgent()
    word = _word()
    agent._grammar_words[word.key()] = word
    agent._word_record_ids[word.key()] = "m1"
    assert agent.word_kinds("coating paint") == [("coating", "m1")]
    assert agent.word_kinds("coat paint") == [("to coat", "m1")] and agent.word_kinds("wall") == []
    assert agent.word_senses_alike("coat paint") == ["paint", "coat paint"], "the verb's senses, not the noun's"
    assert agent.word_held_as_both("to coat", "coat paint") == "coat paint"
    assert agent.word_held_as_both("coating", "to coat") is None


def test_a_word_the_analysts_marked_miswritten_is_no_form_of_it():
    from core.semantics.word_forms import forms_from_conllu
    lines = ["1\tmadea\tmake\tVERB\tVBD\tMood=Ind|Tense=Past|Typo=Yes|VerbForm=Fin\t0\troot\t_\t_\n",
             "1\tmade\tmake\tVERB\tVBD\tMood=Ind|Tense=Past|VerbForm=Fin\t0\troot\t_\t_\n"]
    (made,) = forms_from_conllu(lines, "test")
    assert [form for form, _, _ in made.forms] == ["made"]


def test_language_taught_makes_no_belief_and_is_in_no_domain(monkeypatch):
    """Language is how to read, not knowledge of the world: a word recorded whole, kept, held already or corrected, is
    held by memory and recorded in the knowledge ledger as taught, with no belief made of it and no domain. Each had
    been a belief in the `english` domain that nothing read, and each correction left one more."""
    import asyncio
    import core.database
    import core.memory
    from core.learning.unified_learning_system import UnifiedLearningSystem
    from core.memory import knowledge_ledger
    from core.reasoning import bayesian_uncertainty

    word, was = _word(), _word(senses=_word().senses[:1])

    class Memory:
        async def remember_word_records(self, items, progress=None):
            return {"kept": [(word, "m1")], "held_already": [(word, "m2")], "corrected_items": [(word, "m3", was)],
                    "remembered": 1, "already": 1, "corrected": 1, "total": 3}

    async def memory():
        return Memory()

    recorded = []

    async def record_many(db, updates):
        recorded.extend(updates)

    def no_belief():
        raise AssertionError("taught language reached the beliefs")

    monkeypatch.setattr(core.memory, "get_memory_agent", memory)
    monkeypatch.setattr(core.database, "get_database_manager", lambda: None)
    monkeypatch.setattr(knowledge_ledger, "record_many", record_many)
    monkeypatch.setattr(bayesian_uncertainty, "get_uncertainty_system", no_belief)
    counts = asyncio.run(UnifiedLearningSystem.__new__(UnifiedLearningSystem).learn_word_records(
        [word], quality=0.95))
    assert counts["remembered"] == 1 and counts["corrected"] == 1
    assert [(u.disposition.value, u.domain) for u in recorded] == [("new", None), ("updated", None)]


def test_what_a_thing_is_and_what_a_word_means_are_answers_held_not_sentences_written(monkeypatch):
    """"What is a wall?" is answered by the kind the words hold a wall to be, "What does paint mean?" by what each
    sense it is used in means: each an answer as a held relation is, said as Lyric was taught to say it or by its name
    (`_meanings_held`). They had been sentences written in the code ("A wall is a partition: ..."). A meaning is a
    happening the word "mean" names, as memory holds the word."""
    from core.agents import memory_agent
    from core.agents.autonomous.autonomous_coordinator import Understanding, _meanings_held

    class Words:
        def word_meanings(self, name):
            return [{"word": "mean"}] if name in ("mean", "signify mean") else []
    monkeypatch.setattr(memory_agent, "_memory_agent", Words())
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    paint = [{"word": "paint", "class": "VERB", "concept": "paint", "means": "make a painting", "kind": "create",
              "used": 17, "named": False},
             {"word": "paint", "class": "NOUN", "concept": "coating paint", "means": "a substance used as a coating",
              "kind": "coating", "used": 7, "named": True},
             {"word": "paint", "class": "NOUN", "concept": "rouge", "means": "makeup", "kind": "makeup", "used": 0,
              "named": False}]
    u = Understanding(sentence="What is paint?")
    u.meanings = {"coating paint": paint}
    what_is = Meaning("ask", (F("equals", "?v0", "?v1"), F("instance_of", "?v0", "coating paint")), ("?v1",))
    assert [(a.about, a.relation, a.others, a.verdict) for a in _meanings_held(u, what_is)] \
        == [("paint", "isa", ("coating",), None)]
    means = Meaning("ask", (F("done_by", "?e", "coating paint"), F("done_to", "?e", "?v1"),
                            F("instance_of", "?e", "mean")), ("?v1",))
    assert [(a.relation, a.others) for a in _meanings_held(u, means)] \
        == [("means", ("make a painting",)), ("means", ("a substance used as a coating",))]
    assert not any(a.conclusion for a in _meanings_held(u, what_is) + _meanings_held(u, means))
    described = Meaning("ask", (F("equals", "?v0", "?v1"), F("instance_of", "?v0", "coating paint"),
                                F("has_property", "?v0", "red")), ("?v1",))
    assert _meanings_held(u, described) == [], "a thing asked of more than its kind is not what the kind is"
    assert _meanings_held(u, Meaning("ask", (F("isa", "coating paint", "coating"),))) == [], "a yes or no asks nothing"
    wanting = Meaning("ask", (F("done_by", "?e", "coating paint"), F("done_to", "?e", "?v1"),
                              F("instance_of", "?e", "want")), ("?v1",))
    assert _meanings_held(u, wanting) == [], "a happening no sense of the word \"mean\" names asks no meaning"


def test_a_nouns_sense_is_the_one_the_things_around_it_bear_on():
    """Which sense of a noun a sentence means: each weighed by how often it is used and by how specific a kind it
    shares with each other thing the sentence names (`Lexicon.thing_sense_of`, from what each sense and kind covers of
    what SemCor tagged). "a second coat of paint": paint is a coating, as the coat that is a layer is."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import HeldWords
    from core.semantics.word_forms import HeldForms
    coat = WordRecord("coat", (WordForm("coat", "NOUN", "Number=Sing"),), (
        WordSense("coat.n.01", "NOUN", "coat", "an outer garment", (("garment.n.01", "garment"),
                                                                    ("covering.n.02", "artifact covering")), 29,
                  covers=(108, 419, 1675)),
        WordSense("coating.n.01", "NOUN", "coating", "a thin layer covering something",
                  (("covering.n.02", "artifact covering"),), 1, covers=(76, 1675))))
    agent, forms = MemoryAgent(), HeldForms()
    agent._learn_word_record(coat, {}, forms, agent.structure_view())
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), agent.name_of, forms=forms))
    view.hold_word(coat)
    lexicon = view.grammar.lexicon
    lexicon.words.kinds = lambda name, cls: {"coating paint": ["coating", "artifact covering"]}.get(name, [])
    assert lexicon.thing_sense_of("coat", []) == "coat", "alone, the sense most used"
    assert lexicon.thing_sense_of("coat", ["coating paint"]) == "coating", "beside paint, the coating"
    assert lexicon.thing_sense_of("coat", ["roy"]) == "coat", "beside a thing of no kind held, the sense most used"
    view.drop_word(coat)
    assert not lexicon.thing_used.get("coat")


def test_what_a_preposition_says_joining_things_is_held_by_what_it_takes():
    """What "of" says joining a thing to a thing, as STREUSLE's annotators said each use, by what it took
    (`WordRecord.joins_things`): the grammar holds each link said of the word (`prep`) and of each kind of what it
    took (`prep_to`), a time's apart."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord
    from core.semantics.grammar_words import HeldWords
    of = WordRecord("of", (WordForm("of", "PREPOSITION", "", 10),), (), used_as=(("of", "PREPOSITION:thing", 10),),
                    joins_things=(("made_of", ("cheese", "food"), 2), ("word_of", (), 5),
                                  ("part_of", ("year", "time period"), 1)))
    assert not of.problems(), of.problems()
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    view.hold_word(of)
    learned = view.grammar.lexicon.learned
    assert learned["prep"][("of", "thing", "-")] == {"word_of": 5, "made_of": 2}
    assert learned["prep"][("of", "thing", "point")] == {"part_of": 1}, "a year is a point in time"
    assert learned["prep_to"][("of", "thing", "food")] == {"made_of": 2}
    view.drop_word(of)
    assert not learned["prep"][("of", "thing", "-")]


def test_a_verb_of_several_words_is_read_as_one_where_the_clause_ends_after_it():
    """A word of several words recorded whole ("make it"): how often SemCor's annotators said its words as it, and
    apart, where the clause ends after them and where it goes on (`WordRecord.together`). Held, a verb and the word
    after it are said together as often as that, by where the clause ends (`said_together`)."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import HeldWords
    from core.semantics.word_forms import HeldForms
    make_it = WordRecord("make it", (WordForm("make it", "VERB", "VerbForm=Inf", 6),
                                     WordForm("made it", "VERB", "Tense=Past|VerbForm=Fin", 2)),
                         (WordSense("survive.v.02", "VERB", "overcome survive", "continue in existence", (), 7, (),
                                    ("intransitive",)),),
                         together=(10, 91, 5, 3))
    assert not make_it.problems(), make_it.problems()
    assert WordRecord("make it", make_it.forms, make_it.senses, together=(10, 91)).problems(), "four counts, or none"
    agent, forms = MemoryAgent(), HeldForms()
    agent._learn_word_record(make_it, {}, forms, agent.structure_view())
    words = HeldWords((), gm.closed_uses(), agent.name_of, forms=forms)
    view = gm.GrammarView(words)
    view.hold_word(make_it)
    assert words.said_together("make", "it") == (10.0, 91.0)
    assert words.said_together("make", "it", ends=True) == (5.0, 3.0)
    assert words.said_together("make", "it", ends=False) == (5.0, 88.0)


def test_research_takes_no_kind_from_a_word_that_names_none():
    """A kind is said with a noun or a name, as the treebanks use its last word (`MemoryAgent.says_a_kind`): research
    held "balancer" a kind of "into", a preposition 196 times in 201."""
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.grammar_words import HeldWords
    agent = MemoryAgent()
    words = HeldWords((), gm.closed_uses(), agent.name_of)
    words.uses = lambda w: {"into": {"PREPOSITION": 196.0, "NOUN": 2.0}, "mammal": {"NOUN": 40.0}}.get(w, {})
    agent._grammar_view = gm.GrammarView(words)
    assert not agent.says_a_kind("into")
    assert agent.says_a_kind("domestic mammal") and agent.says_a_kind("zorp"), "nothing held of it: it may"


def test_a_closed_words_forms_their_sounds_and_the_subjects_each_took_are_held_by_the_grammar():
    """A closed word recorded whole with each form's features, how each is said, the first sounds said after forms
    the analysts mark nothing apart ("a", "an"), the subjects each finite form took ("is", "am"), and how often each use
    had a doing's -ing form next and was in a question: the grammar holds every layer (`Words.sounds`,
    `said_before`, `subjects`, `doing_after`, `asking`), and takes it back whole."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, _told_apart
    from core.semantics.grammar_words import HeldWords
    from collections import Counter
    art = "Definite=Ind|PronType=Art"
    a = WordRecord("a", (WordForm("a", "DETERMINER", art, 90, ("AH0", "EY1"), (("W", 40), ("P", 30))),
                         WordForm("an", "DETERMINER", art, 12, ("AE1 N", "AH0 N"), (("AW", 6), ("AE", 5)))), ())
    be = WordRecord("be", (WordForm("is", "AUXILIARY", "Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin", 50,
                                    ("IH1 Z",), (), (("NOUN", "Number=Sing", 30), ("PRONOUN", "Number=Sing|Person=3", 15))),
                           WordForm("am", "AUXILIARY", "Mood=Ind|Number=Sing|Person=1|Tense=Pres|VerbForm=Fin", 9,
                                    ("AE1 M",), (), (("PRONOUN", "Number=Sing|Person=1", 9),))), (),
                    used_as=(("is", "be:ng", 10), ("is", "be:np", 40), ("am", "be:np", 9)),
                    used_before_doing=(("is", "be:ng", 9), ("is", "be:np", 1)), used_asking=(("is", "be:np", 4),))
    for word in (a, be):
        assert not word.problems(), word.problems()
        assert WordRecord.from_dict(json.loads(json.dumps(word.to_dict()))) == word
    assert any("no finite form" in p for p in WordRecord("be", (WordForm(
        "been", "AUXILIARY", "Tense=Past|VerbForm=Part", 3, (), (), (("NOUN", "", 1),)),), ()).problems())
    assert any("more than it was used so" in p for p in WordRecord(
        "be", be.forms, (), used_as=be.used_as, used_before_doing=(("is", "be:ng", 11),)).problems())
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    words = view.words
    for word in (a, be):
        view.hold_word(word)
    assert words.sounds("an") == ["AE1 N", "AH0 N"]
    assert words.said_before("an") == {"a": {"W": 40.0, "P": 30.0}, "an": {"AW": 6.0, "AE": 5.0}}
    assert words.said_before("is") == {}, "a form with no form said alike"
    assert words.subjects("am") == {("PRONOUN", "Number=Sing|Person=1"): 9.0}
    assert words.subjects()[("PRONOUN", "Number=Sing|Person=1")] == 9.0
    assert words.doing_after("be:ng") == (9.0, 1.0) and words.doing_after("be:np") == (1.0, 48.0)
    assert words.asking("be:np") == (4.0, 45.0)
    for word in (a, be):
        view.drop_word(word)
    assert not words.sounds("an") and not words.said_before("an") and not words.subjects()
    assert words.doing_after("be:ng") == (0.0, 0.0)
    # The sound after tells "a" from "an"; it tells nothing of two forms said before the same sounds as often.
    assert _told_apart([Counter({"W": 400, "P": 300}), Counter({"AW": 60, "AE": 50})]) > 0.9
    assert _told_apart([Counter({"W": 400, "P": 300}), Counter({"W": 40, "P": 30})]) == 0.0


def test_the_nouns_a_determiner_was_said_with_and_what_a_copula_said_things_were_are_held_by_the_grammar():
    """A determiner's record holds the nouns each form was said with, and a copula's what each form said a thing to be
    with the thing, each by class and number: the grammar holds both (`Words.nouns`, `predicated`), every such
    together, and takes them back whole."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord
    from core.semantics.grammar_words import HeldWords
    art = "Definite=Ind|PronType=Art"
    a = WordRecord("a", (WordForm("a", "DETERMINER", art, 90, nouns=(("NOUN", "Number=Sing", 80),
                                                                         ("NOUN", "Number=Plur", 2))),), ())
    be = WordRecord("be", (WordForm(
        "are", "AUXILIARY", "Mood=Ind|Number=Plur|Person=3|Tense=Pres|VerbForm=Fin", 40,
        subjects=(("NOUN", "Number=Plur", 30),),
        predicated=(("NOUN", "Number=Plur", "NOUN", "Number=Plur", 12), ("NOUN", "Number=Sing", "NOUN", "Number=Plur", 4))),
    ), ())
    for word in (a, be):
        assert not word.problems(), word.problems()
        assert WordRecord.from_dict(json.loads(json.dumps(word.to_dict()))) == word
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    words = view.words
    for word in (a, be):
        view.hold_word(word)
    assert words.nouns("a") == {("NOUN", "Number=Sing"): 80.0, ("NOUN", "Number=Plur"): 2.0}
    assert words.nouns() == words.nouns("a")
    assert words.predicated(("NOUN", "Number=Plur")) == {("NOUN", "Number=Plur"): 12.0}
    assert words.predicated() == {("NOUN", "Number=Plur"): 16.0}
    for word in (a, be):
        view.drop_word(word)
    assert not words.nouns() and not words.predicated()


def test_a_word_recorded_with_how_often_it_was_a_name_holds_its_names_apart():
    """A word recorded whole holds how often each form was a name as the treebanks used it ("Wall" of Wall Street):
    the record is whole with it, memory holds the name as a name, and of the word's ways of writing a noun is no name
    (`MemoryAgent._held_word_classes`); a word no record holds is a noun or a name, as before."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    wall = WordRecord("wall", (WordForm("wall", "NOUN", "Number=Sing", 19), WordForm("walls", "NOUN", "Number=Plur", 11),
                               WordForm("wall", "NAME", "", 1)),
                      (WordSense("wall.n.01", "NOUN", "wall", "an architectural partition", (("partition.n.01",
                                                                                              "partition"),), 5),))
    assert not wall.problems(), wall.problems()
    agent = MemoryAgent()
    agent._learn_word_record(wall, agent._word_class_index, agent.word_forms(), agent.structure_view())
    agent.pattern_inventory().word_classes = agent._word_class_index
    assert agent._held_word_classes("Wall") == {"NOUN": 19, "NAME": 1}
    assert agent._held_word_classes("Walls") == {"NOUN": 11}
    agent._word_class_index["boston"] = {"NOUN": 3}
    assert agent._held_word_classes("Boston") == {"NOUN": 3, "NAME": 3}


def test_what_an_analysed_sentence_teaches_of_a_word_its_record_carries():
    """What the grammar reads of a word only from sentences analysed (`HeldWords._count`) is carried by its record:
    how it is used written with a capital inside a sentence, what its -ing form stands as, how often its noun is said
    of a doing with no preposition, and the words said after its verb as one with it or apart; and what sentences
    taught with meanings teach of it (`means`: its clause, its places). Each is held by the grammar as a sentence's
    counts are, and taken back whole."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import HeldWords
    pick = WordRecord("pick", (WordForm("pick", "VERB", "VerbForm=Inf", 30), WordForm("picking", "VERB",
                                                                                     "VerbForm=Ger", 6),
                               WordForm("pick", "NOUN", "Number=Sing", 4), WordForm("pick", "NAME", "", 1)),
                      (WordSense("pick.v.01", "VERB", "pick", "select carefully from a group", (), 9),
                       WordSense("choice.n.02", "NOUN", "pick choice", "the person or thing chosen", (), 2)),
                      used_as=(("pick", "VERB", 30), ("picking", "VERB", 6), ("pick", "NOUN", 4)),
                      said_alone=(("pick", 1, 3),), capitalized=(("Pick", "NAME", 1),),
                      shapes=(("picking", "doing", 5), ("picking", "thing", 1)), said_of_doing=(("pick", 0, 4),),
                      said_after=(("up", 12, 1), ("the", 0, 9)),
                      means=(("clause", "VERB", (), "asserted", 2), ("role", "VERB", ("subject",), "done_by", 5)))
    assert not pick.problems(), pick.problems()
    assert any("no such table for the class" in p for p in WordRecord(
        "pick", pick.forms, pick.senses, means=(("adv", "VERB", (), "", 1),)).problems())
    assert WordRecord.from_dict(json.loads(json.dumps(pick.to_dict()))) == pick
    assert any("no verb form" in p for p in WordRecord("pick", pick.forms, pick.senses,
                                                       shapes=(("picks", "doing", 1),)).problems())
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    view.hold_word(pick)
    words = view.words
    assert words.capitalized("Pick").get("NAME") == 1.0
    assert words.verb_shapes("picking") == {"doing": 5.0, "thing": 1.0}
    assert words.bare_modifier("pick") == {"otherwise": 4.0}
    assert words.said_together(words.name("pick", "VERB"), "up") == (12.0, 1.0)
    learned = view.grammar.lexicon.learned
    assert learned["clause"][(words.name("pick", "VERB"),)]["asserted"] == 2
    assert learned["role"][(words.name("pick", "VERB"), "subject")]["done_by"] == 5
    view.drop_word(pick)
    assert not learned["clause"][(words.name("pick", "VERB"),)]
    assert not words.verb_shapes("picking") and words.said_together(words.name("pick", "VERB"), "up") == (0.0, 0.0)


def test_how_often_a_noun_is_said_bare_is_held_from_its_record():
    """A noun recorded whole with how often each form was said with nothing before it saying which, and with a word
    that does (`WordRecord.said_alone`): the grammar weighs a kind said bare by it (`Words.noun_alone`), and takes it
    back whole; a count for no noun form of the word is said wrong."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import HeldWords
    wall = WordRecord("wall", (WordForm("wall", "NOUN", "Number=Sing", 19), WordForm("walls", "NOUN", "Number=Plur", 11)),
                      (WordSense("wall.n.01", "NOUN", "wall", "an architectural partition", (("partition.n.01",
                                                                                              "partition"),), 5),),
                      said_alone=(("wall", 2, 17), ("walls", 6, 5)))
    assert not wall.problems(), wall.problems()
    assert WordRecord.from_dict(json.loads(json.dumps(wall.to_dict()))) == wall
    assert any("no noun form" in p for p in WordRecord("wall", wall.forms, wall.senses,
                                                       said_alone=(("walled", 1, 1),)).problems())
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    view.hold_word(wall)
    assert view.words.noun_alone("wall") == {"bare": 2.0, "determined": 17.0}
    view.drop_word(wall)
    assert not view.words.noun_alone("wall")


def test_a_record_made_from_its_sources_carries_every_column_of_them_or_says_why_not():
    """A word recorded from its sources says how much it carried of each column of each (`WordRecord.covered`,
    `_RECORD_COLUMNS`), and one that leaves a column unsaid is refused: a record carries everything said of its
    word, never only what a sentence was found to need."""
    from core.learning.teaching_sources import _RECORD_COLUMNS, WordForm, WordRecord, WordSense
    every = tuple((source, column, 1) for source, column in _RECORD_COLUMNS)
    wall = WordRecord("wall", (WordForm("wall", "NOUN", "Number=Sing", 20),),
                      (WordSense("wall.n.01", "NOUN", "wall", "an architectural partition"),), covered=every)
    assert not wall.problems(), wall.problems()
    without = WordRecord("wall", wall.forms, wall.senses, covered=tuple(c for c in every if c[:2] != ("UD", "HEAD")))
    assert any("HEAD" in p and "neither carried" in p for p in without.problems()), without.problems()
    assert WordRecord.from_dict(json.loads(json.dumps(wall.to_dict()))) == wall


def test_an_adjective_is_weighed_by_what_it_is_of_and_what_that_is_a_kind_of():
    """WordNet gives an adjective no kinds; its record says what it is of and what that is a kind of
    (`WordSense.pertains_to`), and the grammar holds the adjective defined with it (`GrammarView._count_word`), as
    memory holds "British" defined with the United Kingdom: "Norwegian" is weighed by Norway, a European country, a
    country, so a link learned of a country's adjective ("an Algerian author", `comes_from`) is the link of
    "Norwegian", never seen; taken back whole."""
    from collections import Counter
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import GraphKnowledge, HeldWords
    norwegian = WordRecord("norwegian", (WordForm("norwegian", "ADJECTIVE", "Degree=Pos", 3),), (
        WordSense("norwegian.a.01", "ADJECTIVE", "norway", "of or relating to Norway",
                  pertains_to=(("norway.n.01", "norway", ("european country", "country")),)),))
    assert not norwegian.problems(), norwegian.problems()
    assert WordRecord.from_dict(json.loads(json.dumps(norwegian.to_dict()))) == norwegian
    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of, GraphKnowledge()))
    words, lexicon = view.words, view.grammar.lexicon
    assert lexicon.inherited("quality", "norway", "ADJECTIVE", (), "has_property")[0] == "has_property"
    view.hold_word(norwegian)
    assert words.kinds("norway", "ADJECTIVE")[:3] == ["norway", "european country", "country"]
    lexicon.learned["quality"][("country",)] = Counter({"comes_from": 3})
    assert lexicon.inherited("quality", "norway", "ADJECTIVE", (), "has_property")[0] == "comes_from"
    view.drop_word(norwegian)
    assert words.kinds("norway", "ADJECTIVE") == []


def test_what_a_verb_took_as_an_object_reaches_the_words_layer_from_a_word_record():
    """The path a real teach takes, which the read-only stand-in bypassed: a form record carrying what stood after
    the verb (`WordForm.objects`) -> `GrammarView.hold_word` -> `Words.objects_of` and `every_object`, which is what
    `Grammar._object_agreement` asks. Counted but never carried, the table would fill only in the probe that wrote
    it by hand and would still be empty after the re-teach (lyric_db, 2026-10-30)."""
    from core.agents.memory_agent import MemoryAgent
    from core.learning.teaching_sources import WordForm, WordRecord, WordSense
    from core.semantics.grammar_words import HeldWords
    misled = WordRecord(
        "mislead",
        (WordForm("misled", "VERB", "Tense=Past|VerbForm=Fin", 7,
                  objects=(("PRONOUN", "Case=Acc|Number=Sing|Person=1", 4), ("NOUN", "Number=Sing", 3))),
         WordForm("mislead", "VERB", "VerbForm=Inf", 2)),
        (WordSense("mislead.v.01", "VERB", "mislead", "lead someone in the wrong direction", (), 5),))
    assert not misled.problems(), misled.problems()
    # The layer is written and read back the same, a record made before it being the same record.
    assert WordRecord.from_dict(json.loads(json.dumps(misled.to_dict()))) == misled
    assert WordForm.from_dict(json.loads(json.dumps(
        WordForm("mislead", "VERB", "VerbForm=Inf", 2).to_dict()))).objects == ()

    view = gm.GrammarView(HeldWords((), gm.closed_uses(), MemoryAgent().name_of))
    view.hold_word(misled)
    assert dict(view.words.objects("misled")) == {("PRONOUN", "Case=Acc|Number=Sing|Person=1"): 4.0,
                                                  ("NOUN", "Number=Sing"): 3.0}
    assert dict(view.words.objects()) == dict(view.words.objects("misled")), "every verb's, there being one"
    assert not view.words.objects("mislead"), "the form that took nothing took nothing"
    # AND IT IS GIVEN BACK, as every other counted table is, so a word dropped leaves none of it behind.
    view.drop_word(misled)
    assert not view.words.objects("misled") and not view.words.objects()
