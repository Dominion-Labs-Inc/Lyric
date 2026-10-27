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
    agent._learn_word_record(word, index, forms)
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
    agent._grammar_words.append(word)
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
