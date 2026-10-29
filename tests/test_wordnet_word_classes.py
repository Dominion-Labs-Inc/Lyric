"""WordNet states every class it holds a word in, and each verb of several words; a verb held so is one to the grammar.

Taught one class each, the class tagged most, "research" was no verb and "Research photosynthesis." read as
nothing; no verb of several words was held, and "Look up photosynthesis." read as nothing (lyric_dev, 2026-10-24).
WordNet is read from NLTK's data; a stand-in memory agent holds the classes; nothing touches a store.
"""

from types import SimpleNamespace

from core.agents.memory_agent import MemoryAgent
from core.learning.teaching_sources import WordNetClassesSource, WordNetSource
from core.semantics.derived_reader import PatternInventory


def test_a_word_is_every_class_wordnet_holds_it_in_the_most_tagged_first():
    classes = WordNetSource()._word_classes()
    assert classes["research"] == ("NOUN", "VERB"), classes["research"]
    assert classes["plan"] == ("VERB", "NOUN"), classes["plan"]
    assert classes["explain"] == ("VERB",), classes["explain"]
    # A word of letters joined by hyphens is a word: none of WordNet's 5,093 was taught (2026-10-29).
    assert classes["right-handed"] == ("ADJECTIVE",) and classes["state-of-the-art"] == ("ADJECTIVE",)


def test_a_verb_of_several_words_is_a_verb_and_no_other_words_of_several_are_stated():
    classes = WordNetSource()._word_classes()
    for verb in ("look up", "find out", "sign up"):
        assert classes[verb] == ("VERB",), (verb, classes.get(verb))
    assert "credit card" not in classes, "a noun of several words is held through its facts' words"
    stated = set(WordNetClassesSource().word_classes())
    assert {("research", "NOUN"), ("research", "VERB"), ("look up", "VERB")} <= stated


def test_words_held_together_are_a_word_of_every_class_they_are_held_as():
    """What memory holds several words as together, each kind of word under the name it is held by: the grammar
    offers a word of several words as every kind it is held as, a thing ("credit card"), a quality ("fed up"), an
    adverb ("in vain"), and not as a thing alone (`Grammar._together`, lab notebook (79))."""
    index = {"look up": {"VERB": 1}, "fed up": {"ADJECTIVE": 2}, "credit card": {"NOUN": 3, "NAME": 1}}
    agent = SimpleNamespace(pattern_inventory=PatternInventory,
                            word_classes=lambda word: dict(index.get(word, {})),
                            recorded_name=lambda word, cls: None)
    assert MemoryAgent._held_names(agent, ["look", "up"]) == {"VERB": "look up"}
    assert MemoryAgent._held_names(agent, ["fed", "up"]) == {"ADJECTIVE": "fed up"}
    assert MemoryAgent._held_names(agent, ["credit", "card"]) == {"NOUN": "credit card"}
    assert MemoryAgent._held_names(agent, ["look", "down"]) == {}
