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
    assert argued.said() == '"Tom kicked the ball ."\n"kicked": "Tom" fact:done_by, "ball" fact:done_to'
    view = ax.ArgumentStructureView()
    view.learn(argued)
    assert view.arguments(("Rex", "kicked", "the", "box", "."), classes, heads, relations, 1) == \
        {0: "fact:done_by", 3: "fact:done_to"}


def test_memory_keeps_an_annotated_sentence_once_and_folds_it_into_its_view():
    """`MemoryAgent.remember_argued`, the store stood in for: kept, one memory with the annotation whole, and held by
    the argument view; given again, held already."""
    import asyncio
    from types import SimpleNamespace
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.structure import Analysed
    argued = ax.Argued.of(Analysed(("Tom", "kicked", "the", "ball", "."),
                                   ("NAME", "VERB", "DETERMINER", "NOUN", "PUNCTUATION"), (2, 0, 4, 2, 2),
                                   ("nsubj", "root", "det", "obj", "punct"), "t:1"),
                          {1: {0: "fact:done_by", 3: "fact:done_to"}}, {})
    agent = MemoryAgent()
    agent._word_classes_warm = True
    stored = []

    async def store_memory(**kwargs):
        stored.append(kwargs)
        return True, f"m{len(stored)}"

    async def rows_tagged(tag):
        return [SimpleNamespace(memory_id=f"m{k}", metadata=s["source_context"])
                for k, s in enumerate(stored, 1) if tag in s["tags"]]
    agent.store_memory, agent._rows_tagged = store_memory, rows_tagged
    first = asyncio.run(agent.remember_argued([argued]))
    assert (first["remembered"], first["already"]) == (1, 0) and first["kept"] == [(argued, "m1")]
    assert stored[0]["source_context"] == {"argued": argued.to_dict()} and len(agent.argument_view()) == 1
    again = asyncio.run(agent.remember_argued([argued]))
    assert (again["remembered"], again["already"]) == (0, 1) and len(stored) == 1
    assert again["held_already"] == [(argued, "m1")] and "\n" in stored[0]["content"]
