"""Every kind of taught language reaches something that reads or says, or is recorded as reaching nothing.

TEACHING THAT LANDS AND CHANGES NO READING IS NOT TEACHING. A lesson can be stated by a source, dispatched by the
pass, written by the one learning path, counted in the report and exempt from judging — all of which
`tests/test_teaching_path.py` and `tests/test_language_tags_agree.py` hold — and still change nothing about how a
sentence is read or what is said back, because no reader asks for it. That is the half those files do not cover.

WHAT THE READERS ASK FOR is five questions, and they are asked of memory by name (`core/semantics/derived_reader.py`:
`pattern_inventory`, `said_selection`, `grammar_view`, `listening_evidence`, `coarse_senses`), with two more asked by
hearing and the voice (`core/perception/perception_faculty.py`) and the conversation's own
(`core/agents/autonomous/autonomous_coordinator.py`). Most kinds reach a reading inside one of those answers rather
than by a question of their own: word groups and the sentences analysed by hand become the structure view, and the
structure view is part of `grammar_view`. So each kind is recorded here with the question its memory reaches a
reading through, and the questions are read out of the readers themselves rather than listed by hand.

A kind reaching nothing is recorded in `NOT_ASKED` with what is known about why. That is a finding, not a pass: it
is written down so it cannot be mistaken for wiring, and the test says so when one is wired up at last.
"""
import inspect
import io
import re

import core.memory.utils.memory_filter as memory_filter
from core.agents.memory_agent import MemoryAgent
from core.semantics import derived_reader

#: The files that read and say, and therefore the only places a question of memory makes a reading change.
READERS = (
    "core/semantics/derived_reader.py",
    "core/perception/perception_faculty.py",
    "core/agents/autonomous/autonomous_coordinator.py",
)

#: Every kind of taught language, and what it reaches a reading or a saying through.
#:
#: The value is a question a reader asks of memory, or a function of the reader that reads the kind back by another
#: route, and a word on how the kind gets there. Verified by reading the code, 2026-10-29.
ANSWERS = {
    "language_pattern": ("pattern_inventory", "the constructions themselves, and what says a meaning (`say`)"),
    "word_class": ("pattern_inventory", "the index, stood where a class's part stands (`of_its_class`)"),
    "heard_after": ("pattern_inventory", "what was heard after what (`PatternInventory.hear`)"),
    "word_forms": ("pattern_inventory", "the forms a written word is a form of (`held_forms`), and `HeldWords`"),
    "said_of": ("said_selection", "what each word is said of, asked when a sentence can be taken more than one way"),
    "word_group": ("grammar_view", "each word's groups beside it in the structure view (`StructureView.grouping`)"),
    "analysed_sentence": ("grammar_view", "the structure view, which `HeldWords` is built from"),
    "taught_sentence": ("grammar_view", "learned from by the grammar (`GrammarView.hold`)"),
    "derived_sentence": ("grammar_view", "what each word takes beside the words around it (`hold_derived`)"),
    "sentence_record": ("grammar_view", "each layer of the record into the view that learns from it (`hold_use`)"),
    "word_record": ("grammar_view", "each word as memory holds it (`hold_word`), and `word_meanings`"),
    "read_english": ("grammar_view", "what reading taught of how words are used (`hold_read`)"),
    "pronunciation": ("stated_pronunciations", "how a word is said, for hearing it and for saying it"),
    "listening": ("derived_reader._held_listening_counts",
                  "the counts are beliefs the one memory is named by, weighed when a sentence reads more than one "
                  "way (`weighed`); the memory itself holds no counts, which is why no question asks it for any"),
}

#: Kinds whose memory reaches no reader, with what is known about why. Each is teaching that lands and is read by
#: nothing, so it belongs in the record and not in a comment.
NOT_ASKED = {
    "argued_sentence": (
        "argument_view",
        "which phrases are a happening's arguments, read back as `ArgumentStructureView` and handed to "
        "`CompositionView` -- the composer replaced on 2026-10-20, whose decisions where no remembered sentence "
        "looked like the sentence were wrong one time in three (`core/semantics/grammar.py`, first paragraph). The "
        "live path composes through `GrammarView.compose_sentence`, and neither `grammar.py` nor `derived_reader.py` "
        "mentions an argument anywhere. 10,495 of them are held on the main store and they change no reading; they "
        "are what experiments/COMPOSE-01 and PMB-01 measure."),
}


def _register():
    for obj in vars(memory_filter).values():
        if isinstance(obj, type) and hasattr(obj, "TAUGHT_LANGUAGE_TAGS"):
            return set(obj.TAUGHT_LANGUAGE_TAGS)
    raise AssertionError("no filter declares the register of taught language")


def _what_the_readers_ask():
    """Every question the reading and saying code asks of memory, read out of the readers themselves."""
    asked = set()
    for path in READERS:
        source = io.open(path, encoding="utf-8").read()
        asked |= set(re.findall(r"\b(?:agent|memory|_memory_agent|_agent)\.([a-z][a-z_]*)\(", source))
    return asked


def test_every_kind_of_taught_language_is_decided_about():
    """The register and this file name the same kinds, so a kind added to one lands here."""
    register, decided = _register(), set(ANSWERS) | set(NOT_ASKED)
    assert not sorted(register - decided), (
        "these kinds of language are taught and nobody has said what reads them back; if nothing does, that is a "
        f"finding and belongs in NOT_ASKED: {sorted(register - decided)}")
    assert not sorted(decided - register), (
        f"these are not kinds of taught language any more: {sorted(decided - register)}")
    assert not set(ANSWERS) & set(NOT_ASKED)


def test_every_kind_reaches_a_reading_through_a_question_a_reader_really_asks():
    """The guard: a reader that stops asking takes every kind that reached a reading through it down with it."""
    asked = _what_the_readers_ask()
    unasked = sorted(tag for tag, (question, _why) in ANSWERS.items() if "." not in question and question not in asked)
    assert not unasked, (
        "these kinds reach a reading through a question no reader asks any more, so they are taught and read by "
        f"nothing: {unasked}")


def test_every_question_is_one_memory_really_answers():
    """A question named here that memory does not answer is a route that was never there."""
    missing = sorted(tag for tag, (question, _why) in ANSWERS.items()
                     if "." not in question and not hasattr(MemoryAgent, question))
    assert not missing, f"memory answers no such question: {missing}"
    for tag, (question, _why) in ANSWERS.items():
        if "." in question:
            module, name = question.split(".", 1)
            assert module == "derived_reader" and hasattr(derived_reader, name), (
                f"{tag} is said to be read back by {question}, which does not exist")


def test_what_reaches_no_reader_still_names_a_view_and_still_reaches_no_reader():
    """The finding, held as a finding.

    It fails BOTH ways on purpose: if the view stops existing the record is stale, and if a reader starts asking for
    it the finding is fixed and belongs in ANSWERS instead. Either way someone looks.
    """
    asked = _what_the_readers_ask()
    for tag, (view, why) in NOT_ASKED.items():
        assert hasattr(MemoryAgent, view), f"{tag} is recorded as reaching only {view}, which no longer exists"
        assert view not in asked, (
            f"{view} is asked for by a reader now, so {tag} reaches a reading at last: move it to ANSWERS with the "
            f"question that reaches it. What was recorded here: {why}")


def test_the_one_reply_path_says_what_the_grammar_and_the_constructions_say():
    """Responding: one `say`, which asks the grammar first and the constructions taught second.

    Both are fed by taught language (`ANSWERS`), so what is said changes with what was taught. Held because the
    reply used to fall through to an introspection dump for every question that was not a yes/no.
    """
    said = inspect.getsource(derived_reader.say)
    assert "grammar_view" in said, "the one say no longer asks the grammar it reads by"
    assert "_said_whole" in said, "the one say no longer says what the constructions taught say"


def test_reading_and_saying_are_one_view_that_carries_what_things_are():
    """The knowledge half is INSIDE saying, not upstream of it.

    A reply's content is what `understand()` resolved against the store (`Understanding.known`), and the grammar it
    is said with is the same cached view reading uses: `read` and `say` are two methods on one object, built once a
    warm with what memory holds of things. Held because the first version of (85) said reading needed the knowledge
    half in a place that read as though responding did not have it.
    """
    from core.semantics.grammar import GrammarView
    for question in ("read", "say"):
        assert callable(getattr(GrammarView, question, None)), (
            f"the view no longer answers {question}; reading and saying would be two paths")
    built = inspect.getsource(MemoryAgent.grammar_view)
    assert "if self._grammar_view is None" in built, (
        "the grammar view is no longer one per warm, so what reads and what says could differ")
    assert "GraphKnowledge" in built, (
        "the grammar is no longer given what memory holds of things (`isa`, `instance of`), which it asks of every "
        "word it reads")
    linked = inspect.getsource(MemoryAgent.link_concepts)
    assert "hear_kind" in linked, (
        "a link stored no longer reaches the live view, so what things are would wait for the next warm")
