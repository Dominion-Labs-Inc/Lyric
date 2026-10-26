"""A sentence recorded whole (`teaching_sources.SentenceRecord`): every layer by word position, checked, and each part
of reading given its layer of it (TRAIN-FORMAT-01). No store: the record and memory's views are built here."""
import json

from core.learning.teaching_sources import RecordFact, RecordWord, SentenceRecord
from core.semantics import grammar as gm

TEXT = "Tom chased a cat."


def _record(**changed) -> SentenceRecord:
    words = (RecordWord(0, "Tom", 0, 3, "tom", "NAME", "NNP", "Number=Sing", "", "n", "PER", 1, "nsubj"),
             RecordWord(1, "chased", 4, 10, "chase", "VERB", "VBD", "Mood=Ind|Tense=Past|VerbForm=Fin",
                        "chase.v.01", "(s:dcl\\np)/np", "EPS", -1, "root", ("Theme", "Agent")),
             RecordWord(2, "a", 11, 12, "a", "DETERMINER", "DT", "", "", "np/n", "DIS", 3, "det"),
             RecordWord(3, "cat", 13, 16, "cat", "NOUN", "NN", "Number=Sing", "cat.n.01", "n", "CON", 1, "obj"),
             RecordWord(4, ".", 16, 17, ".", "PUNCTUATION", ".", "", "", ".", "NIL", 1, "punct"))
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
    circled[1] = RecordWord(1, "chased", 4, 10, "chase", "VERB", "VBD", "", "", "(s:dcl\\np)/np", "", 3, "root")
    problems = _record(words=tuple(circled)).problems()
    assert any("are the sentence's own" in p for p in problems) and any("circle" in p for p in problems)
    moved = list(_record().words)
    moved[3] = RecordWord(3, "cat", 12, 15, "cat", "NOUN", "NN", "", "", "n", "", 1, "obj")
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
        uses=(WordUse("paint.01", "put paint on a surface",
                      (WordPlace("ARG0", "agent, painter", "PAG", (), "subject", "done_by"),
                       WordPlace("ARG1", "surface", "GOL", (), "object", "done_to"),
                       WordPlace("ARG2", "explicit mention of paint", "PPT"))),))
    fields.update(changed)
    return WordRecord(**fields)


def test_a_word_record_is_whole_and_reads_back_the_same():
    from core.learning.teaching_sources import WordRecord
    word = _word()
    assert word.problems() == []
    assert WordRecord.from_dict(json.loads(json.dumps(word.to_dict()))) == word
    assert word.names() == {"NOUN": "coating paint", "VERB": "paint"}, "each class by its most used sense"
    assert word.frames() == {"intransitive": 17, "transitive": 30}
    assert word.links() == {("subject", "done_by"): 1, ("object", "done_to"): 1}, "no link guessed for ARG2"


def test_a_word_record_that_does_not_hold_together_is_said_wrong():
    from core.learning.teaching_sources import WordForm
    assert any("which no sense of the word is" in p
               for p in _word(forms=_word().forms + (WordForm("painty", "ADJECTIVE"),)).problems())
    assert any("not among its forms" in p for p in _word(forms=_word().forms[1:]).problems())


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
    view.drop_word(word)
    assert not view.words.frames("paint") and not view.grammar.lexicon.learned["role"][("paint", "subject")]


def test_a_link_held_as_its_word_gives_way_to_one_taught_saying():
    from collections import Counter
    assert gm._weighed(Counter({"done_with": 1}), "word_with") == "done_with"
    assert gm._weighed(Counter(), "word_with") == "word_with"
    assert gm._weighed(Counter({"has_purpose": 1}), "done_by") == "done_by", "a rule of the grammar's ties and stands"
