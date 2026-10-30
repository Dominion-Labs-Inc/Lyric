"""Every kind of taught language is known to be taught language, by each list that has to know it.

Taught language is not knowledge of the world: it is how to read and how to say, read back by the readers and
never recalled as something Lyric knows. Three lists carry that distinction and must agree about it —

  1. `MemoryAgent`'s `*_TAG` constants, which name the kinds;
  2. `MemoryFilter.EXEMPT_EVENT_TAGS`, which keeps a lesson from being judged novel or complex enough to keep;
  3. the set at `memory_agent._remember`, which keeps a record of how English is used from being read as a claim.

Each has fallen behind at least once, and every time the cost was measured: the treebank's structure pass stopped
on one declined sentence (2026-10-16); word classes and pronunciations were declined and counted as skipped,
silently; 53 of the 59 memories handed to reasoning for UNDERSTANDS-PROSE-01 and -02 were examples of English, so
"Is seven odd?" was answered with "'seven' is used as an adjective." (2026-10-23); and the word "wall"'s record was
read as a claim by the grammar, 109 million combinations and 148 seconds (TRAIN-FORMAT-02, 2026-10-26).

A kind of language added without a decision about these lists is teaching that lands and then poisons reading. This
holds the decision explicit rather than remembered.
"""
import core.memory.utils.memory_filter as memory_filter
from core.agents.memory_agent import MemoryAgent
from core.semantics import derived_reader

#: The kinds of memory a teaching pass writes that are TAUGHT LANGUAGE: how to read and how to say.
TAUGHT_LANGUAGE = {
    "word_class", "word_forms", "word_group", "pronunciation", "language_pattern", "said_of", "heard_after",
    "analysed_sentence", "taught_sentence", "argued_sentence", "derived_sentence", "word_record",
    "sentence_record", "read_english",
}

#: Kinds a teaching pass writes that are NOT taught language, each with why it is recalled like anything else.
NOT_LANGUAGE = {
    "admitted_proposition": "a statement Lyric was told, which is knowledge of the world and recalled as such",
    "listening": "one memory, the one the listener's counts are beliefs about, already kept from being read as a "
                 "claim by the set at MemoryAgent._remember",
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


def test_every_kind_of_taught_language_is_exempt_from_being_judged_worth_keeping():
    exempt = set(_filter().EXEMPT_EVENT_TAGS)
    judged = sorted(TAUGHT_LANGUAGE - exempt)
    assert not judged, (
        "these are taught language and the filter would judge them novel or complex enough to keep, which is not a "
        f"question to put to a lesson: {judged}")


def test_every_kind_of_taught_language_is_named_by_a_tag_constant():
    """A tag written as a bare string somewhere is a tag the other two lists cannot be checked against."""
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
        "TAUGHT_LANGUAGE, NOT_LANGUAGE or not_a_lesson, and if it is language add it to "
        "MemoryFilter.EXEMPT_EVENT_TAGS too.")


def test_what_the_claim_reader_skips_is_language_the_filter_also_exempts():
    """The third list, at `MemoryAgent._remember`: a record of how English is used is not read as a claim.

    It names three tags where the filter names fourteen. That is not a defect in itself — a word class IS read as a
    claim deliberately — but the three it names must be language the filter agrees about, or the two lists disagree
    about the same memory.
    """
    exempt = set(_filter().EXEMPT_EVENT_TAGS)
    for tag in (MemoryAgent.HEARD_TAG, MemoryAgent.SAID_OF_TAG):
        assert tag in exempt, f"{tag} is skipped as a claim but judged for keeping"
    assert MemoryAgent.LISTENING_TAG in NOT_LANGUAGE, (
        "listening is skipped as a claim and not exempt from keeping; that is deliberate and recorded here")
