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
