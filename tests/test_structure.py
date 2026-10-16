"""How the words of a sentence go together (`core/semantics/structure.py`): sentences analysed by hand, kept whole,
and read as memory-based learning reads them. No store: the sentences are given here."""
import pytest

from core.semantics.structure import Analysed, StructureView, words_of


def _analysed(text, classes, heads, relations, said_in=""):
    return Analysed(tuple(text.split()), tuple(classes), tuple(heads), tuple(relations), said_in)


#: "Plants take in carbon dioxide and water ." and two more like it, analysed as the English Web Treebank analyses.
PLANTS = _analysed("Plants take in carbon dioxide and water .",
                   ["NOUN", "VERB", "ADVERB", "NOUN", "NOUN", "CONJUNCTION", "NOUN", "PUNCTUATION"],
                   [2, 0, 2, 5, 2, 7, 5, 2],
                   ["nsubj", "root", "compound:prt", "compound", "obj", "cc", "conj", "punct"], "t:1")
DOGS = _analysed("Dogs eat meat and bones .",
                 ["NOUN", "VERB", "NOUN", "CONJUNCTION", "NOUN", "PUNCTUATION"],
                 [2, 0, 2, 5, 3, 2], ["nsubj", "root", "obj", "cc", "conj", "punct"], "t:2")
CATS = _analysed("Cats drink milk .", ["NOUN", "VERB", "NOUN", "PUNCTUATION"], [2, 0, 2, 2],
                 ["nsubj", "root", "obj", "punct"], "t:3")


def test_an_analysis_gives_every_word_one_head_and_the_sentence_one_root():
    with pytest.raises(ValueError):
        _analysed("Dogs bark", ["NOUN", "VERB"], [2, 0], ["nsubj"])
    with pytest.raises(ValueError):
        _analysed("Dogs bark", ["NOUN", "VERB"], [0, 0], ["root", "root"])
    with pytest.raises(ValueError):
        _analysed("Dogs bark", ["NOUN", "VERB"], [1, 0], ["nsubj", "root"])


def test_the_same_sentence_met_twice_is_two_uses_and_told_again_is_one():
    again = _analysed("Cats drink milk .", ["NOUN", "VERB", "NOUN", "PUNCTUATION"], [2, 0, 2, 2],
                      ["nsubj", "root", "obj", "punct"], "t:3")
    elsewhere = _analysed("Cats drink milk .", ["NOUN", "VERB", "NOUN", "PUNCTUATION"], [2, 0, 2, 2],
                          ["nsubj", "root", "obj", "punct"], "t:9")
    view = StructureView()
    assert view.add(CATS) and not view.add(again) and view.add(elsewhere)
    assert len(view) == 2
    assert Analysed.from_dict(CATS.to_dict()) == CATS
    assert CATS.claim().startswith('the structure of "Cats drink milk ."')


def test_a_sentence_held_reads_as_it_was_analysed():
    view = StructureView()
    for analysed in (PLANTS, DOGS, CATS):
        view.add(analysed)
    read = view.read(PLANTS.words)
    assert read.classes == PLANTS.classes
    assert read.heads == PLANTS.heads
    assert read.relations == PLANTS.relations


def test_a_phrase_is_a_word_with_all_that_depends_on_it():
    """"carbon dioxide and water" stands where one thing stands, whatever its length: the object of "take"."""
    view = StructureView()
    for analysed in (PLANTS, DOGS, CATS):
        view.add(analysed)
    read = view.read(PLANTS.words)
    assert ("obj", "dioxide", "carbon dioxide and water") in read.phrases()
    assert ("nsubj", "Plants", "Plants") in read.phrases()


def test_a_sentence_never_held_is_read_by_the_situations_it_shares():
    view = StructureView()
    for analysed in (PLANTS, DOGS, CATS):
        view.add(analysed)
    read = view.read(("Birds", "eat", "seeds", "and", "insects", "."))
    assert read.classes == ("NOUN", "VERB", "NOUN", "CONJUNCTION", "NOUN", "PUNCTUATION")
    assert read.heads == (2, 0, 2, 5, 3, 2)


def test_a_tie_is_decided_by_the_next_situation_never_by_the_names_of_the_classes():
    """"stale", never met, after "A": a word ending in "ale" there was once an adjective ("pale") and once a noun
    ("gale"); one ending in "le", an adjective twice ("pale", "little"). The adjective, where the order of the
    classes' names gave the tie to the noun."""
    view = StructureView()
    view.add(_analysed("A pale moon rose .", ["DETERMINER", "ADJECTIVE", "NOUN", "VERB", "PUNCTUATION"],
                       [3, 3, 4, 0, 4], ["det", "amod", "nsubj", "root", "punct"], "t:1"))
    view.add(_analysed("A gale blew .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                       ["det", "nsubj", "root", "punct"], "t:2"))
    view.add(_analysed("A little dog barked .", ["DETERMINER", "ADJECTIVE", "NOUN", "VERB", "PUNCTUATION"],
                       [3, 3, 4, 0, 4], ["det", "amod", "nsubj", "root", "punct"], "t:3"))
    assert view.classes(("A", "stale", "bun", "."))[:2] == ("DETERMINER", "ADJECTIVE")


def test_pieces_are_written_as_a_treebank_writes_them():
    assert words_of(["It", "doesn", "'t", "change", "."]) == ("It", "does", "n't", "change", ".")
    assert words_of(["We", "can", "'t", "."]) == ("We", "ca", "n't", ".")
    assert words_of(["Tom", "'s", "dog"]) == ("Tom", "'s", "dog")


def test_a_treebank_is_read_with_its_classes_named_as_lyric_names_them(tmp_path):
    from core.learning.teaching_sources import read_conllu
    conllu = tmp_path / "t.conllu"
    conllu.write_text(
        "# sent_id = s-1\n"
        "# text = I don't know Tom.\n"
        "1\tI\tI\tPRON\tPRP\t_\t4\tnsubj\t_\t_\n"
        "2-3\tdon't\t_\t_\t_\t_\t_\t_\t_\t_\n"
        "2\tdo\tdo\tAUX\tVBP\t_\t4\taux\t_\t_\n"
        "3\tn't\tnot\tPART\tRB\t_\t4\tadvmod\t_\t_\n"
        "4\tknow\tknow\tVERB\tVB\t_\t0\troot\t_\t_\n"
        "4.1\tknown\tknow\tVERB\tVBN\t_\t_\t_\t4:conj\t_\n"
        "5\tTom\tTom\tPROPN\tNNP\t_\t4\tobj\t_\tSpaceAfter=No\n"
        "6\t.\t.\tPUNCT\t.\t_\t4\tpunct\t_\t_\n\n", encoding="utf-8")
    (analysed,) = list(read_conllu(str(conllu), "test"))
    assert analysed.words == ("I", "do", "n't", "know", "Tom", ".")
    assert analysed.classes == ("PRONOUN", "AUXILIARY", "PARTICLE", "VERB", "NAME", "PUNCTUATION")
    assert analysed.heads == (4, 4, 4, 0, 4, 4)
    assert analysed.said_in == "test:s-1"
