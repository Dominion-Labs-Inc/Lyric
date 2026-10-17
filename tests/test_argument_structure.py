"""Which phrases are a predicate's arguments, and what each is said in (`core/semantics/argument_structure.py`). No
store: the sentences and their structure are given here."""
from core.semantics import argument_structure as ax

#: "Tom wanted to leave ." as the English Web Treebank analyses it: "Tom" under "wanted", "leave" its complement.
WANTED = (("Tom", "wanted", "to", "leave", "."), ("NAME", "VERB", "PARTICLE", "VERB", "PUNCTUATION"),
          (2, 0, 4, 2, 2), ("nsubj", "root", "mark", "xcomp", "punct"))


def test_the_candidates_go_up_the_structure_from_the_predicate():
    """"Tom" is an argument of "leave" two steps up: the candidates are the predicate's dependents, then each word
    above it and that word's dependents."""
    _, _, heads, _ = WANTED
    assert ax.candidates(heads, 3) == [2, 1, 0, 4]
    assert ax.candidates(heads, 1) == [0, 3, 4]


def test_a_phrase_is_a_word_with_all_that_depends_on_it():
    _, _, heads, _ = WANTED
    assert ax.phrase(3, heads) == (2, 4)
    assert ax.phrase(1, heads) == (0, 5)


def test_the_arguments_are_the_candidates_said_in_something():
    """Learned from one sentence, each candidate said as its argument was, or `NONE`: a sentence standing so has the
    same arguments, said the same."""
    words, classes = ("Tom", "kicked", "the", "ball", "."), ("NAME", "VERB", "DETERMINER", "NOUN", "PUNCTUATION")
    heads, relations = (2, 0, 4, 2, 2), ("nsubj", "root", "det", "obj", "punct")
    said = {0: "fact:done_by", 3: "fact:done_to"}
    view = ax.ArgumentStructureView()
    for candidate in ax.candidates(heads, 1):
        view.add(ax.situations(words, classes, heads, relations, 1, ax.phrase(candidate, heads)),
                 said.get(candidate, ax.NONE))
    found = view.arguments(("Rex", "kicked", "the", "box", "."), classes, heads, relations, 1)
    assert found == said


def test_an_annotated_sentence_is_held_whole_and_learned_from():
    """An annotation is kept as it was given (`Argued`), and the view learns from it what it learns from its candidates
    one by one."""
    from core.semantics.structure import Analysed
    words, classes = ("Tom", "kicked", "the", "ball", "."), ("NAME", "VERB", "DETERMINER", "NOUN", "PUNCTUATION")
    heads, relations = (2, 0, 4, 2, 2), ("nsubj", "root", "det", "obj", "punct")
    argued = ax.Argued.of(Analysed(words, classes, heads, relations, "t:1"),
                          {1: {0: "fact:done_by", 3: "fact:done_to"}}, {})
    assert ax.Argued.from_dict(argued.to_dict()) == argued
    assert argued.said() == '"Tom kicked the ball .": "kicked": "Tom" fact:done_by, "ball" fact:done_to'
    view = ax.ArgumentStructureView()
    view.learn(argued)
    assert view.arguments(("Rex", "kicked", "the", "box", "."), classes, heads, relations, 1) == \
        {0: "fact:done_by", 3: "fact:done_to"}
