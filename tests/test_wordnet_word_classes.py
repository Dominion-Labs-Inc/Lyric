"""WordNet states every class it holds a word in, and each verb, quality and adverb of several words; held so, the
grammar reads the words as one word of that kind.

Taught one class each, the class tagged most, "research" was no verb and "Research photosynthesis." read as
nothing; no verb of several words was held, and "Look up photosynthesis." read as nothing (lyric_dev, 2026-10-24).
Stated for verbs alone, main held nothing at all for "fed up", "in vain" or "at last" (lyric_db, 2026-10-29): a
noun of several words is named by its facts, where a quality has no fact to be named in.
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


def test_a_verb_a_quality_or_an_adverb_of_several_words_is_stated_and_a_noun_is_not():
    classes = WordNetSource()._word_classes()
    for verb in ("look up", "find out", "sign up"):
        assert classes[verb] == ("VERB",), (verb, classes.get(verb))
    for quality in ("fed up", "in love", "out of print"):
        assert classes[quality] == ("ADJECTIVE",), (quality, classes.get(quality))
    for adverb in ("kind of", "in vain", "at last"):
        assert classes[adverb] == ("ADVERB",), (adverb, classes.get(adverb))
    assert "credit card" not in classes, "a noun of several words is named by its facts' words"
    # A QUALITY'S OR AN ADVERB'S WORDS HOLD NO PRONOUN ("to it" `thereto`), which stands for whatever was spoken of;
    # taught with the rest the 80 of them cost a sentence of GRAMMAR-01's 231 (lyric_dev2, 2026-10-29). A verb's may
    # be frozen into the verb, and the verbs are stated as they have been since (73).
    for held in ("to it", "on it", "as it is", "in his own right", "one hundred"):
        assert held not in classes, held
    assert classes["get it"] == ("VERB",), classes.get("get it")
    stated = set(WordNetClassesSource().word_classes())
    assert {("research", "NOUN"), ("research", "VERB"), ("look up", "VERB"),
            ("fed up", "ADJECTIVE"), ("in vain", "ADVERB")} <= stated


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
