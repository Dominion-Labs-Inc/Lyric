"""Composing what a sentence means from how its words go together (`core/semantics/composition.py`). No store: the
sentences, their structure and their taught meanings are given here."""
from collections import Counter

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
    """By its names: the known dog is "dog", the barking "barked"; the barking done by the dog is a link of the two
    words, the upper the barking; its time a fact of the barking and now, which no word says."""
    meaning, words = cp.words_by_names(*BARKED)
    aligned = cp.align(BARKED[0], meaning, words)
    assert aligned.stands == {1: "known", 2: "thing"}
    assert aligned.links == {(2, 1): "done_by:ul"}
    assert aligned.ones == {2: "precedes:>?now"}


def test_a_meaning_is_aligned_by_the_words_its_lines_say():
    """A sentence taught with where each term is said (the Parallel Meaning Bank's lines, `TaughtSentence.anchors`)
    is aligned by them, not by names: "The hound barked." taught as a dog's barking, the dog said by "hound"."""
    laid = _laid("The hound barked .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                 ["det", "nsubj", "root", "punct"])
    meaning = Meaning("tell", (F("instance_of", "?d", "dog", given=True), F("instance_of", "?e", "bark"),
                               F("done_by", "?e", "?d"), F("precedes", "?e", "?now")))
    taught = cp.TaughtSentence("The hound barked.", meaning, "pmb", (("?d", ((0, 9, "head", ("The",)),)),
                                                                    ("?e", ((10, 16, "head", ()),))))
    assert cp.TaughtSentence.from_dict(taught.to_dict()) == taught
    words = cp.words_by_anchors(laid, taught.sentence, taught.anchors)
    assert words == {"?d": [1], "?e": [2]}
    aligned = cp.align(laid, meaning, words)
    assert aligned.stands == {1: "known", 2: "thing"} and aligned.links == {(2, 1): "done_by:ul"}


def test_a_sentence_standing_as_a_lesson_does_is_composed_as_it_was_taught():
    """"The cat ran ." stands as "The dog barked ." does: a running, by the known cat, before now."""
    view = cp.CompositionView()
    view.learn(*BARKED)
    composed = view.compose(_laid("The cat ran .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                                  ["det", "nsubj", "root", "punct"]))
    want = Meaning("tell", (F("instance_of", "?a", "cat", given=True), F("instance_of", "?e", "run"),
                            F("done_by", "?e", "?a"), F("precedes", "?e", "?now")))
    assert composed.canonical() == want.canonical()


def _told(subject, verb, negated=False):
    """"The <subject> <verb>ed ." or "The <subject> did not <verb> .", laid out as the English Web Treebank analyses
    them, with its meaning."""
    if negated:
        laid = _laid(f"The {subject} did not {verb} .", ["DETERMINER", "NOUN", "AUXILIARY", "PARTICLE", "VERB",
                                                         "PUNCTUATION"], [2, 5, 5, 5, 0, 5],
                     ["det", "nsubj", "aux", "advmod", "root", "punct"])
    else:
        laid = _laid(f"The {subject} {verb}ed .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                     ["det", "nsubj", "root", "punct"])
    return laid, Meaning("tell", (F("instance_of", "?t", subject, given=True), F("instance_of", "?e", verb),
                                  F("done_by", "?e", "?t", not negated), F("precedes", "?e", "?now", not negated)))


def test_the_words_that_deny_what_their_clause_says_are_learned():
    """No word is listed as denying: "not" is found under the words whose facts are not so, met there each time;
    "did" is met as often where they are so ("did" asks too), and is found no denying word."""
    view = cp.CompositionView()
    for subject, verb in (("dog", "bark"), ("cat", "jump"), ("bird", "walk")):
        view.learn(*_told(subject, verb, negated=True))
        view.learn(*_told(subject, verb))
    for subject, verb in (("dog", "kick"), ("cat", "kick"), ("bird", "kick")):
        view.learn(_laid(f"Did the {subject} {verb} ?", ["AUXILIARY", "DETERMINER", "NOUN", "VERB", "PUNCTUATION"],
                         [4, 3, 4, 0, 4], ["aux", "det", "nsubj", "root", "punct"]),
                   Meaning("ask", (F("instance_of", "?t", subject, given=True), F("instance_of", "?e", verb),
                                   F("done_by", "?e", "?t"), F("precedes", "?e", "?now"))))
    view._work_out()
    assert view.negators == {"not"}
    composed = view.compose(_told("fox", "jump", negated=True)[0])
    assert F("done_by", "?x4", "?x1", False) in composed.facts


def test_words_far_apart_in_the_structure_hold_no_fact_together():
    """Of two words more than two steps apart (`NEAR`), no fact is weighed, however the lessons decided pairs like
    them: "The dog of the man of the town barked." holds no fact of the barking and the town."""
    view = cp.CompositionView()
    view.learn(*BARKED)
    laid = _laid("The dog of the man of the town barked .",
                 ["DETERMINER", "NOUN", "PREPOSITION", "DETERMINER", "NOUN", "PREPOSITION", "DETERMINER", "NOUN",
                  "VERB", "PUNCTUATION"], [2, 9, 5, 5, 2, 8, 8, 5, 0, 9],
                 ["det", "nsubj", "case", "det", "nmod", "case", "det", "nmod", "root", "punct"])
    assert cp.steps(laid, 8, 7) == 3
    assert not any({f.subject, f.obj} == {"?x8", "?x7"} for f in view.compose(laid).facts)


def test_a_word_standing_for_what_another_word_does_takes_its_term():
    """"Tom washed himself.": the washing done by Tom and to him; "himself" stands for what "Tom" does, found by the
    situations (`CompositionView._same_situations`), and takes its term."""
    laid = _laid("Tom washed himself .", ["NAME", "VERB", "PRONOUN", "PUNCTUATION"], [2, 0, 2, 2],
                 ["nsubj", "root", "obj", "punct"])
    meaning = Meaning("tell", (F("instance_of", "?e", "wash"), F("done_by", "?e", "tom"), F("done_to", "?e", "tom"),
                               F("precedes", "?e", "?now")))
    aligned = cp.align(laid, meaning, {"?e": [1], "tom": [0, 2]})
    assert aligned.stands == {0: "name", 1: "thing", 2: "same"} and aligned.same == {2: 0}
    assert aligned.links == {(1, 0): "done_by:ul", (1, 2): "done_to:ul", (0, 2): "-"}
    view = cp.CompositionView()
    view.learn(laid, meaning, {"?e": [1], "tom": [0, 2]})
    rex = _laid("Rex washed himself .", ["NAME", "VERB", "PRONOUN", "PUNCTUATION"], [2, 0, 2, 2],
                ["nsubj", "root", "obj", "punct"])
    assert F("done_to", "?x1", "rex") in view.compose(rex).facts


def test_a_fact_the_facts_held_would_contradict_is_not_held():
    """One meaning: a happening is at one time; a second time composed for it is not held, and the rest of the
    meaning stands."""
    view = cp.CompositionView()
    view.learn(*BARKED)
    view._work_out()
    view._ones[("c", "VERB", "-", "subject", "root", "-")] = Counter({"precedes:>?now|follows:>?now": 9})
    composed = view.compose(_laid("The cat jumped .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                                  ["det", "nsubj", "root", "punct"]))
    times = [f for f in composed.facts if f.relation in ("precedes", "follows")]
    assert len(times) == 1 and F("done_by", "?x2", "?x1") in composed.facts


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


class _AsMemorysGrammar:
    """Memory's grammar as `_read_by_composing` asks it: one object that READS a sentence to a meaning.

    These stubs answered `compose_sentence`, which is how the composer that was replaced on 2026-10-20 was asked.
    The live path asks `agent.grammar_view().read(...)` and takes the reading's `meaning`, so the stubs raised
    AttributeError and four tests of `_read_by_composing` had been failing since. The assertions are unchanged; only
    what the stub answers to is (2026-10-30).
    """

    def __init__(self, meaning=None, compose=None):
        self._meaning, self._compose = meaning, compose
        self.sign = None

    def grammar_view(self):
        return self

    def read(self, words):
        self.meaning = self._compose(" ".join(str(w) for w in words)) if self._compose is not None else self._meaning
        return self


def test_an_utterance_no_frame_reads_is_composed_only_where_composing_is_on(monkeypatch):
    """`read_text` leaves "The cat ran." unread where nothing taught reads it; with `COMPOSING` on, it is read by the
    composer memory holds, as one reading marked composed."""
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr
    view = cp.CompositionView(lay_out=lambda sentence: _laid(
        "The cat ran .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3], ["det", "nsubj", "root", "punct"]))
    view.learn(*BARKED)

    monkeypatch.setattr(memory, "_memory_agent", _AsMemorysGrammar(compose=view.compose_sentence))
    monkeypatch.setattr(dr, "COMPOSING", False)
    assert not dr.read_text("The cat ran.", dr.PatternInventory())[0].readings
    monkeypatch.setattr(dr, "COMPOSING", True)
    reading, = dr.read_text("The cat ran.", dr.PatternInventory())[0].readings
    want = Meaning("tell", (F("instance_of", "?a", "cat", given=True), F("instance_of", "?e", "run"),
                            F("done_by", "?e", "?a"), F("precedes", "?e", "?now")))
    assert reading.composed and not reading.constructions
    assert reading.meaning.canonical() == want.canonical()


def test_a_telling_read_only_by_supposing_more_than_the_lessons_is_composed(monkeypatch):
    """`_read_forced_by_composing`: an utterance whose every reading supposes more than a lesson read as taught ever
    did (more than two links never taught, or a filler written against its slot), a telling or a question, is read by
    memory's grammar; one supposing no more than the lessons, or one the grammar reads nothing of, stays as the frames
    read it."""
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr
    composed = Meaning("tell", (F("instance_of", "?e", "breathe"), F("done_by", "?e", "whale")))

    grammar = _AsMemorysGrammar(composed)
    monkeypatch.setattr(memory, "_memory_agent", grammar)
    told = Meaning("tell", (F("has_property", "?e", "air through"),))
    pieces = (dr.Piece("Whales", True), dr.Piece("breathe", False), dr.Piece(".", False))

    def utterance(*readings):
        return dr.Utterance(pieces, readings)
    forced = dr.Reading((), (), told, proposed=("link",) * 3)
    misfit = dr.Reading((), (), told, proposed=("link",), misfits=1)
    as_taught = dr.Reading((), (), told, proposed=("link",) * 2)
    asked = dr.Reading((), (), Meaning("ask", told.facts), proposed=("link",) * 6)
    for readings in [(forced,), (misfit,), (forced, misfit), (asked,)]:
        reading, = dr._read_forced_by_composing(utterance(*readings)).readings
        assert reading.composed and reading.meaning == composed
    for readings in [(as_taught,), (forced, as_taught)]:
        assert dr._read_forced_by_composing(utterance(*readings)).readings == readings
    grammar._meaning = None       # the grammar gives it no meaning
    assert dr._read_forced_by_composing(utterance(forced)).readings == (forced,)


def test_a_question_asking_for_something_composed_asking_for_nothing_is_not_read(monkeypatch):
    """"How many engineers did the company hire?" composed as asking whether the company hired is no reading of it: a
    question opening with a question word asks for something. Asked yes or no, the same meaning is its reading."""
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr
    hired = Meaning("ask", (F("instance_of", "?e", "hire"), F("done_by", "?e", "company_1")))

    monkeypatch.setattr(memory, "_memory_agent", _AsMemorysGrammar(hired))
    monkeypatch.setattr(dr, "COMPOSING", True)
    assert not dr.read_text("How many engineers did the company hire?", dr.PatternInventory())[0].readings
    reading, = dr.read_text("Did the company hire engineers?", dr.PatternInventory())[0].readings
    assert reading.composed and reading.meaning == hired


def test_a_composed_meaning_of_known_things_alone_is_no_reading(monkeypatch):
    """"Is the valve closed?" composed as the valve alone (given instance_of(?x2, valve)) asks nothing: the utterance
    is left unread, as it is where nothing is composed."""
    from core.agents import memory_agent as memory
    from core.semantics import derived_reader as dr

    monkeypatch.setattr(memory, "_memory_agent",
                        _AsMemorysGrammar(Meaning("ask", (F("instance_of", "?x2", "valve", given=True),))))
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


def test_a_word_held_only_as_another_class_is_named_through_its_shape():
    """"hired" read as a verb is `hire`, the verb memory holds, though memory holds "hired" the adjective; read as an
    adjective it is `hired`. So a telling composed ("The company hired three engineers.") meets the question its frame
    reads ("Did the company hire engineers?"). "help" the noun stays `help`, never `aid`, another of its senses."""
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.derived_reader import Lexical
    from core.semantics.sentence_machine import Piece
    agent = MemoryAgent()
    view = agent.pattern_inventory()
    view.add(Lexical((Piece("hired", False),), "hired"))
    view.add(Lexical((Piece("hire", False),), "hire"))
    # Memory counts a word's classes by how it is written: "hired" is counted a verb too.
    view.word_classes = {"hired": {"ADJECTIVE": 3, "VERB": 1}, "hire": {"VERB": 5}}
    view.names_of_shape = lambda word: ["hire"] if word == "hired" else []
    assert agent.name_of("hired", "VERB") == "hire"
    assert agent.name_of("hired", "ADJECTIVE") == "hired"
    assert agent.name_of("hire", "VERB") == "hire"
    # Never another sense of the class in the word's place: "help" held as a verb, "aid" as a noun.
    view.add(Lexical((Piece("help", False),), "help"))
    view.add(Lexical((Piece("help", False),), "aid"))
    view.word_classes.update({"help": {"VERB": 4}, "aid": {"NOUN": 2}})
    assert agent.name_of("help", "NOUN") == "help"


def test_a_sentence_taught_again_with_a_corrected_meaning_corrects_its_memory():
    """`MemoryAgent.remember_taught_sentences`, the store stood in for: a sentence taught again from where it was
    said, with another meaning, corrects the memory holding it (one memory, saying the correction, keeping what it
    said before), and the composer's view holds the correction alone; the same sentence said elsewhere is its own."""
    import asyncio
    from types import SimpleNamespace
    from core.agents.memory_agent import MemoryAgent
    denied = Meaning("tell", (F("instance_of", "?e", "bark", False), F("done_by", "?e", "rex", False)))
    as_taught = Meaning("tell", (F("instance_of", "?e", "bark"), F("done_by", "?e", "rex"),
                                 F("has_property", "?e", "false")))
    first, again = (cp.TaughtSentence("Rex did not bark.", m, "pmb/p00/d0001") for m in (denied, as_taught))
    agent = MemoryAgent()
    agent._word_classes_warm = True
    agent.embedding_service = None
    stored = []

    async def store_memory(**kwargs):
        stored.append(dict(kwargs, metadata=kwargs["source_context"]))
        return True, f"m{len(stored)}"

    async def rows_tagged(tag):
        return [SimpleNamespace(memory_id=f"m{k}", metadata=s["metadata"]) for k, s in enumerate(stored, 1)
                if tag in s["tags"]]

    async def update_memory(memory_id, updates):
        stored[int(memory_id[1:]) - 1].update(updates)
        return True
    agent.store_memory, agent._rows_tagged, agent.update_memory = store_memory, rows_tagged, update_memory
    assert asyncio.run(agent.remember_taught_sentences([first]))["remembered"] == 1
    corrected = asyncio.run(agent.remember_taught_sentences([again]))
    assert (corrected["remembered"], corrected["corrected"]) == (0, 1)
    assert corrected["corrected_items"] == [(again, "m1", first)] and len(stored) == 1
    assert stored[0]["metadata"]["taught"] == again.to_dict() and stored[0]["content"] == again.said()
    assert stored[0]["metadata"]["superseded"][-1]["was"] == first.to_dict()
    assert agent.composition_view()._waiting == [again]
    # English's grammar, not built yet, learns from the correction alone when it is.
    assert agent._grammar_taught == [again]
    assert asyncio.run(agent.remember_taught_sentences([again]))["already"] == 1
    elsewhere = cp.TaughtSentence("Rex did not bark.", denied, "english_12")
    assert asyncio.run(agent.remember_taught_sentences([elsewhere]))["remembered"] == 1 and len(stored) == 2
