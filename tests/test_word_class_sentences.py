"""A word class is taught to memory in real English: "an adjective", never "a adjective".

The memory a stated class lands as is a sentence the substrate holds and can recall; SENSE-01 was writing
"'able' is used as a adjective." for every WordNet adjective and adverb. A stand-in memory agent captures what
would be stored; nothing touches a store.
"""

import asyncio
from types import SimpleNamespace

import core.memory as memory
from core.learning.unified_learning_system import UnifiedLearningSystem


def test_a_word_class_is_said_with_the_article_its_name_takes(monkeypatch):
    stored = []

    async def stated_word_classes():
        return []

    async def store_memory(**kwargs):
        stored.append(kwargs["content"])
        return True, f"m{len(stored)}"

    agent = SimpleNamespace(stated_word_classes=stated_word_classes, store_memory=store_memory,
                            WORD_CLASS_TAG="word_class", _word_class_index={})

    async def get_memory_agent():
        return agent

    monkeypatch.setattr(memory, "get_memory_agent", get_memory_agent)
    learning = UnifiedLearningSystem.__new__(UnifiedLearningSystem)
    counts = asyncio.run(learning.learn_word_classes([
        ("able", "ADJECTIVE"), ("scarce", "ADVERB"), ("dog", "NOUN"),
        ("must", "MODAL"), ("oh", "INTERJECTION"), ("be", "AUXILIARY")]))

    assert counts["told"] == 6, counts
    assert stored == ["'able' is used as an adjective.", "'scarce' is used as an adverb.",
                      "'dog' is used as a noun.", "'must' is used as a modal.",
                      "'oh' is used as an interjection.", "'be' is used as an auxiliary."], stored
