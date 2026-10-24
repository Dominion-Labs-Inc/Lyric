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


def test_a_verb_of_several_words_is_a_verb_and_no_other_words_of_several_are_stated():
    classes = WordNetSource()._word_classes()
    for verb in ("look up", "find out", "sign up"):
        assert classes[verb] == ("VERB",), (verb, classes.get(verb))
    assert "credit card" not in classes, "a noun of several words is held through its facts' words"
    stated = set(WordNetClassesSource().word_classes())
    assert {("research", "NOUN"), ("research", "VERB"), ("look up", "VERB")} <= stated


def test_words_held_together_as_a_verb_are_the_verb_the_grammar_asks_for():
    index = {"look up": {"VERB": 1}}
    agent = SimpleNamespace(pattern_inventory=PatternInventory,
                            word_classes=lambda word: dict(index.get(word, {})))
    assert MemoryAgent._held_name(agent, ["look", "up"], "VERB") == "look up"
    assert MemoryAgent._held_name(agent, ["look", "up"], "NOUN") is None
    assert MemoryAgent._held_name(agent, ["look", "down"], "VERB") is None
