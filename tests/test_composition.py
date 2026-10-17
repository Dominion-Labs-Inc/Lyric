"""Composing what a sentence means from how its words go together (`core/semantics/composition.py`). No store: the
sentences, their structure and their taught meanings are given here."""
from core.semantics import composition as cp
from core.semantics.derived_reader import Meaning, MeaningFact as F

NAMES = {"barked": "bark", "ran": "run", "dogs": "dog"}


def _name(word, cls):
    return NAMES.get(word.lower(), word.lower())


def _laid(text, classes, heads, relations, known=lambda words: False):
    return cp.lay(text.split(), classes, heads, relations, _name, known)


#: "The dog barked ." and "The dog is big .", as the English Web Treebank analyses them, with their taught meanings.
BARKED = (_laid("The dog barked .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                ["det", "nsubj", "root", "punct"]),
          Meaning("tell", (F("instance_of", "?t0", "dog", given=True), F("instance_of", "?v0", "bark"),
                           F("done_by", "?v0", "?t0"), F("precedes", "?v0", "?now"))))
BIG = (_laid("The dog is big .", ["DETERMINER", "NOUN", "AUXILIARY", "ADJECTIVE", "PUNCTUATION"], [2, 4, 4, 0, 4],
             ["det", "nsubj", "cop", "root", "punct"]),
       Meaning("tell", (F("instance_of", "?t0", "dog", given=True), F("has_property", "?t0", "big"))))


def test_a_run_of_words_joined_as_compound_is_one_name():
    laid = _laid("The Eiffel Tower was built .", ["DETERMINER", "NAME", "NAME", "AUXILIARY", "VERB", "PUNCTUATION"],
                 [3, 3, 5, 5, 0, 5], ["det", "compound", "nsubj:pass", "aux:pass", "root", "punct"])
    assert laid.names[1:3] == ("", "eiffel tower")


def test_an_adjective_and_its_noun_are_one_name_only_where_memory_knows_the_two():
    classes, heads, relations = ["DETERMINER", "ADJECTIVE", "NOUN"], [3, 3, 0], ["det", "amod", "root"]
    assert _laid("the blue whale", classes, heads, relations).names[1:] == ("blue", "whale")
    known = _laid("the blue whale", classes, heads, relations, lambda words: list(words) == ["blue", "whale"])
    assert known.names[1:] == ("", "blue whale")


def test_a_lesson_is_aligned_to_the_words_of_its_sentence():
    aligned = cp.align(*BARKED)
    assert aligned.stands == {1: "known", 2: "thing"}
    assert aligned.pairs == {(1, 2): ("done_by:<",)}
    assert aligned.ones == {2: ("precedes:>?now",)}


def test_a_sentence_standing_as_a_lesson_does_is_composed_as_it_was_taught():
    """"The cat ran ." stands as "The dog barked ." does: a running, by the known cat, before now."""
    view = cp.CompositionView()
    view.learn(*BARKED)
    composed = view.compose(_laid("The cat ran .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                                  ["det", "nsubj", "root", "punct"]))
    want = Meaning("tell", (F("instance_of", "?a", "cat", given=True), F("instance_of", "?e", "run"),
                            F("done_by", "?e", "?a"), F("precedes", "?e", "?now")))
    assert composed.canonical() == want.canonical()


def test_where_the_lessons_say_nothing_a_relation_says_its_own_sense():
    """No lesson holds an adjective on a noun: "big" before "cat" says what an adjective on a noun does, a quality of
    it (`RELATION_SENSES`)."""
    view = cp.CompositionView()
    view.learn(*BARKED)
    view.learn(*BIG)
    composed = view.compose(_laid("The big cat barked .", ["DETERMINER", "ADJECTIVE", "NOUN", "VERB", "PUNCTUATION"],
                                  [3, 3, 4, 0, 4], ["det", "amod", "nsubj", "root", "punct"]))
    assert F("has_property", "?x2", "big") in composed.facts


def test_a_sentence_taught_with_its_meaning_is_held_whole_and_read_when_the_view_is_next_asked():
    """Held whole (`hold`), a lesson is read and laid out by the view's own reader when the view is next worked out,
    as memory reads it at warm: with the structure and names memory has then."""
    taught = cp.TaughtSentence("The dog barked.", BARKED[1], "english_01")
    assert cp.TaughtSentence.from_dict(taught.to_dict()) == taught
    laid_out = {"The dog barked.": BARKED[0],
                "The cat ran.": _laid("The cat ran .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                                      ["det", "nsubj", "root", "punct"])}
    view = cp.CompositionView(lay_out=laid_out.get)
    view.hold(taught)
    composed = view.compose_sentence("The cat ran.")
    assert F("instance_of", "?x2", "run") in composed.facts and F("done_by", "?x2", "?x1") in composed.facts
    assert view.compose_sentence("Nothing laid out.") is None


def test_an_utterance_no_frame_reads_is_composed_only_where_composing_is_on(monkeypatch):
    """`read_text` leaves "The cat ran." unread where nothing taught reads it; with `COMPOSING` on, it is read by the
    composer memory holds, as one reading marked composed."""
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr
    view = cp.CompositionView(lay_out=lambda sentence: _laid(
        "The cat ran .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3], ["det", "nsubj", "root", "punct"]))
    view.learn(*BARKED)

    class Agent:
        def composition_view(self):
            return view
    monkeypatch.setattr(memory, "_memory_agent", Agent())
    monkeypatch.setattr(dr, "COMPOSING", False)
    assert not dr.read_text("The cat ran.", dr.PatternInventory())[0].readings
    monkeypatch.setattr(dr, "COMPOSING", True)
    reading, = dr.read_text("The cat ran.", dr.PatternInventory())[0].readings
    want = Meaning("tell", (F("instance_of", "?a", "cat", given=True), F("instance_of", "?e", "run"),
                            F("done_by", "?e", "?a"), F("precedes", "?e", "?now")))
    assert reading.composed and not reading.constructions
    assert reading.meaning.canonical() == want.canonical()


def test_a_composed_meaning_of_known_things_alone_is_no_reading(monkeypatch):
    """"Is the valve closed?" composed as the valve alone (given instance_of(?x2, valve)) asks nothing: the utterance
    is left unread, as it is where nothing is composed."""
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr

    class View:
        def compose_sentence(self, sentence):
            return Meaning("ask", (F("instance_of", "?x2", "valve", given=True),))

    class Agent:
        def composition_view(self):
            return View()
    monkeypatch.setattr(memory, "_memory_agent", Agent())
    monkeypatch.setattr(dr, "COMPOSING", True)
    assert not dr.read_text("Is the valve closed?", dr.PatternInventory())[0].readings


def test_a_word_is_named_as_memory_names_it():
    """"flies" names what the filler taught for it names (the lessons' `dipterous insect fly`); a word memory holds
    nothing of names itself."""
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.derived_reader import Lexical
    from core.semantics.sentence_machine import Piece
    agent = MemoryAgent()
    agent.pattern_inventory().add(Lexical((Piece("Flies", False),), "dipterous insect fly"))
    assert agent.name_of("flies", "NOUN") == "dipterous insect fly"
    assert agent.name_of("Cat", "NOUN") == "cat"
