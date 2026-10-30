"""Every kind of taught language is known to be taught language, by everything that has to know it.

Taught language is not knowledge of the world: it is how to read and how to say, read back by the readers and
never recalled as something Lyric knows. Two things follow from a memory being one, and until 2026-10-29 they were
decided in two places with two different lists —

  1. `MemoryFilter.EXEMPT_EVENT_TAGS` named fourteen kinds, and kept each from being judged novel or complex enough
     to keep, which is not a question to put to a lesson;
  2. a set of three at `MemoryAgent._store_memory` kept a record of how English is used from being read as a claim
     about the world.

So the same memory was taught language to one and not the other. Both now ask one register
(`MemoryFilter.TAUGHT_LANGUAGE_TAGS`, read off the table that already names every kind and why), through one
question (`MemoryAgent.taught_language`). What this file holds is that the register is right and that both
consequences still follow from it — and, for the kinds it must NOT cover, that knowledge taught is still read as a
claim.

Each list fell behind at least once, and every time the cost was measured: the treebank's structure pass stopped on
one declined sentence (2026-10-16); word classes and pronunciations were declined and counted as skipped, silently;
53 of the 59 memories handed to reasoning for UNDERSTANDS-PROSE-01 and -02 were examples of English, so "Is seven
odd?" was answered with "'seven' is used as an adjective." (2026-10-23); and the word "wall"'s record was read as a
claim by the grammar, 109 million combinations and 148 seconds (TRAIN-FORMAT-02, 2026-10-26).

A kind of language added without a decision about it is teaching that lands and then poisons reading. This holds
the decision explicit rather than remembered.
"""
import inspect

import core.memory.utils.memory_filter as memory_filter
from core.agents.memory_agent import MemoryAgent
from core.semantics import derived_reader

#: The kinds of memory a teaching pass writes that are TAUGHT LANGUAGE: how to read and how to say.
#:
#: Stated here on purpose, independently of the code, so that the register the code derives has something to be
#: wrong against. This is the only list of kinds in this file; the code's is derived from its own table.
TAUGHT_LANGUAGE = {
    "word_class", "word_forms", "word_group", "pronunciation", "language_pattern", "said_of", "heard_after",
    "analysed_sentence", "taught_sentence", "argued_sentence", "derived_sentence", "word_record",
    "sentence_record", "read_english", "listening",
}

#: Kinds a teaching pass writes that are NOT taught language, each with why it is recalled like anything else.
NOT_LANGUAGE = {
    "admitted_proposition": "a statement Lyric was told, which is knowledge of the world and recalled as such",
}


def _filter():
    for obj in vars(memory_filter).values():
        if isinstance(obj, type) and hasattr(obj, "EXEMPT_EVENT_TAGS"):
            return obj
    raise AssertionError("no filter declares EXEMPT_EVENT_TAGS")


def _tag_constants():
    tags = {name: getattr(MemoryAgent, name) for name in dir(MemoryAgent)
            if name.endswith("_TAG") and isinstance(getattr(MemoryAgent, name), str)}
    tags["derived_reader.PATTERN_TAG"] = derived_reader.PATTERN_TAG
    return tags


def test_the_pattern_tag_is_the_one_the_filter_exempts():
    """The filter's comment says a test holds them equal. This is that test."""
    assert derived_reader.PATTERN_TAG in _filter().EXEMPT_EVENT_TAGS


def test_the_register_names_every_kind_of_taught_language_and_nothing_else():
    """The register, against this file's own statement of what taught language is.

    It is derived from the exemption table rather than written out, so a kind filed under another class there, or
    one left out of it, shows up here as a difference.
    """
    register = set(_filter().TAUGHT_LANGUAGE_TAGS)
    assert not sorted(TAUGHT_LANGUAGE - register), (
        "these are taught language and the register does not name them, so they will be judged worth keeping and "
        f"read as claims: {sorted(TAUGHT_LANGUAGE - register)}")
    assert not sorted(register - TAUGHT_LANGUAGE), (
        "the register names these and this file does not call them taught language; if they are, say so above, and "
        f"if they are not they are being kept unjudged and left unread: {sorted(register - TAUGHT_LANGUAGE)}")


def test_every_kind_of_taught_language_is_exempt_from_being_judged_worth_keeping():
    """The first consequence: a lesson is kept because it was taught, never because it is novel or complex."""
    exempt = set(_filter().EXEMPT_EVENT_TAGS)
    judged = sorted(TAUGHT_LANGUAGE - exempt)
    assert not judged, (
        "these are taught language and the filter would judge them novel or complex enough to keep, which is not a "
        f"question to put to a lesson: {judged}")


def test_every_kind_of_taught_language_is_kept_from_being_read_as_a_claim():
    """The second consequence, asked the way the store path asks it, one kind at a time."""
    unread = sorted(tag for tag in TAUGHT_LANGUAGE if not MemoryAgent.taught_language(["language", tag]))
    assert not unread, (
        "these are taught language and their content would be read as a claim about the world and recalled as "
        f"knowledge: {unread}")


def test_knowledge_taught_is_still_read_as_a_claim():
    """What the register must NOT swallow. A statement Lyric was told IS a claim, and reading it is the point.

    A register that grew to cover everything a teaching pass writes would silence the claims teaching exists to
    land, which is the same defect with the sign reversed.
    """
    for tag in NOT_LANGUAGE:
        assert not MemoryAgent.taught_language([tag], {"producer": "teaching"}), (
            f"{tag} is {NOT_LANGUAGE[tag]}, and it is being skipped by the claim reader")
    assert not MemoryAgent.taught_language(["episode"], {"conclusion": "The disk filled at 02:14."})


def test_the_claim_decision_is_asked_and_not_listed_a_second_time():
    """The settlement itself: the store path asks the register, and holds no list of language tags of its own."""
    source = inspect.getsource(MemoryAgent._store_memory)
    assert "taught_language(" in source, "the store path no longer asks the one question"
    named = sorted(name for name, tag in _tag_constants().items() if tag in TAUGHT_LANGUAGE and name in source)
    assert not named, (
        f"the store path names kinds of language itself ({named}); that is the second list again, and the kinds it "
        "leaves out are the ones that get read as claims")


def test_every_kind_of_taught_language_is_named_by_a_tag_constant():
    """A tag written as a bare string somewhere is a tag the register cannot be checked against."""
    named = set(_tag_constants().values())
    assert not sorted(TAUGHT_LANGUAGE - named), f"no constant names: {sorted(TAUGHT_LANGUAGE - named)}"


def test_every_tag_constant_is_decided_about_one_way_or_the_other():
    """The guard itself: a kind added to MemoryAgent lands here until someone says which it is.

    Percepts and the substrate's own records are neither taught language nor knowledge taught, and they are not a
    teaching pass's business, so they are listed as what they are.
    """
    not_a_lesson = {
        "open": "an open question the substrate holds, its own and not taught",
        "thing": "a thing perceived, not a lesson",
        "told_but_unread": "a telling kept until it can be read, which is the telling and not language",
        "song": "sound heard", "spoken_sounds": "sound heard", "spoken_word": "sound heard",
        "voice": "a voice heard",
    }
    undecided = sorted(
        tag for tag in _tag_constants().values()
        if tag not in TAUGHT_LANGUAGE and tag not in NOT_LANGUAGE and tag not in not_a_lesson)
    assert not undecided, (
        f"a kind of memory nobody has said is taught language or is not: {undecided}. Say which in "
        "TAUGHT_LANGUAGE, NOT_LANGUAGE or not_a_lesson, and if it is language file it under taught language in "
        "MemoryFilter.EXEMPT_EVENT_TAGS, which is where the register comes from.")
