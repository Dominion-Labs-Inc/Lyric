"""Reading by English's grammar (`core/semantics/grammar.py`): each word's category and meaning, combined by general
rules. The words here are held in the test (`Held`), as memory would hold them; nothing is learned, so every link is
the grammar's own."""
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pytest

from core.semantics import grammar as gm

NOUNS = {"dog": "dog", "dogs": "dog", "cat": "cat", "ball": "ball", "whale": "whale", "whales": "whale",
         "mammal": "mammal", "mammals": "mammal", "bird": "bird", "birds": "bird", "valve": "valve", "tank": "tank",
         "shirt": "shirt", "account": "account", "park": "park"}
VERBS = {"chased": "chase", "chase": "chase", "barked": "bark", "bark": "bark", "barks": "bark", "fly": "fly",
         "unbuttoned": "unbutton", "locked": "lock", "kick": "kick", "kicked": "kick", "sleeps": "sleep",
         "began": "begin", "working": "work", "work": "work"}
ADJECTIVES = {"closed": "closed", "full": "full", "red": "red", "happy": "happy"}
PREPOSITIONS = ("in", "on", "from")
FORMS = {"chased": {"past": 5.0, "participle": 1.0}, "barked": {"past": 5.0}, "unbuttoned": {"past": 2.0},
         "locked": {"participle": 4.0, "past": 2.0}, "kicked": {"past": 3.0}, "began": {"past": 5.0}}
FRAMES = {"chase": {"transitive": 9.0}, "bark": {"intransitive": 9.0}, "fly": {"intransitive": 9.0},
          "unbutton": {"transitive": 9.0}, "lock": {"transitive": 9.0}, "kick": {"transitive": 9.0},
          "sleep": {"intransitive": 9.0}, "begin": {"ing": 6.0, "to": 3.0}, "work": {"intransitive": 9.0}}


class Held(gm.Words):
    """A few words, as memory would hold them."""

    def uses(self, word: str) -> Mapping[str, float]:
        w = word.lower()
        out: Dict[str, float] = {}
        if w in NOUNS:
            out["NOUN"] = 10.0
        if w in VERBS:
            out["VERB"] = 10.0
        if w in ADJECTIVES:
            out["ADJECTIVE"] = 10.0
        if w in PREPOSITIONS:
            out["PREPOSITION"] = 10.0
        if word[:1].isupper() and not out:
            out["NAME"] = 10.0
        return out

    def name(self, word: str, cls: str) -> str:
        w = word.lower()
        return {"NOUN": NOUNS, "VERB": VERBS, "ADJECTIVE": ADJECTIVES}.get(cls, {}).get(w, w)

    def verb_forms(self, word: str) -> Mapping[str, float]:
        return FORMS.get(word.lower(), {})

    def frames(self, name: str) -> Mapping[str, float]:
        return FRAMES.get(name, {})

    def noun_alone(self, word: str) -> Mapping[str, float]:
        return {"bare": 1.0, "determined": 1.0}

    def plural(self, word: str) -> bool:
        return word.lower().endswith("s") and word.lower() in NOUNS

    def is_person(self, name: str) -> bool:
        return False

    def capitalized(self, word: str) -> Mapping[str, float]:
        return {"NAME": 1.0}


@pytest.fixture(scope="module")
def grammar():
    return gm.Grammar(gm.Lexicon(Held()))


def read(grammar, text: str) -> Optional[str]:
    words = gm.tokens_of(text, grammar.lexicon.words)
    reading = grammar.read(words)
    return reading.meaning.canonical() if reading.meaning is not None else None


def test_a_telling_built_from_its_words(grammar):
    assert read(grammar, "The dog chased a cat.") == (
        "tell: done_by(?v0, ?v1) & done_to(?v0, ?v2) & given instance_of(?v1, dog) & instance_of(?v0, chase) & "
        "instance_of(?v2, cat) & precedes(?v0, ?now)")


def test_a_question_asks_what_is_taken_from_its_place(grammar):
    # "What" fills the place "chased" leaves open after "did the dog chase", by composition, never by a pattern.
    assert read(grammar, "What did the dog chase?") == (
        "ask: done_by(?v0, ?v1) & done_to(?v0, ?v2) & given instance_of(?v1, dog) & instance_of(?v0, chase) & "
        "precedes(?v0, ?now) ? ?v2")


def test_whom_asks_who_a_thing_was_done_to_never_who_did_it(grammar):
    # "Whom" is the object's form: "Whom did Cyrus defeat?" was read on main as asking who did the defeating
    # (done_by(?v0, ?v1) beside done_by(?v0, cyrus)), "whom" held as a subject (UNDERSTANDS-PROSE-02, 2026-10-22).
    assert [entry["use"] for entry in grammar.lexicon.closed["whom"]] == ["wh:object"]
    assert read(grammar, "Whom did the dog chase?") == read(grammar, "What did the dog chase?")


def test_an_inverted_passive_question(grammar):
    assert read(grammar, "Was the account locked?") == (
        "ask: done_to(?v0, ?v1) & given instance_of(?v1, account) & instance_of(?v0, lock) & precedes(?v0, ?now)")


def test_a_denied_happening(grammar):
    assert read(grammar, "The dog did not bark.") == (
        "tell: done_by(?v0, ?v1) & given instance_of(?v1, dog) & has_property(?v0, false) & instance_of(?v0, bark) "
        "& precedes(?v0, ?now)")


def test_his_is_the_one_before_it(grammar):
    assert read(grammar, "Tom unbuttoned his shirt.") == (
        "tell: done_by(?v0, tom) & done_to(?v0, ?v1) & instance_of(?v0, unbutton) & instance_of(?v1, shirt) & "
        "owned_by(?v1, tom) & precedes(?v0, ?now)")


def test_a_doing_an_ing_clause_says_is_done_by_the_one_who_does_the_verb(grammar):
    """"Tom began working.": the working is Tom's, as "Tom began to work." says. Read as a beginning of some work, no
    one did the working, and "Who began working on Python?" found nothing (UNDERSTANDS-PROSE-01, 2026-10-21)."""
    words = gm.tokens_of("Tom began working.", grammar.lexicon.words)
    meaning = grammar.read(words).meaning
    assert meaning is not None
    facts = {(f.relation, f.subject, f.obj) for f in meaning.facts}
    begin = next(s for r, s, o in facts if r == "instance_of" and o == "begin")
    work = next(s for r, s, o in facts if r == "instance_of" and o == "work")
    assert {("done_by", begin, "tom"), ("done_to", begin, work), ("done_by", work, "tom")} <= facts, facts
    from core.semantics.grammar_words import _frame_of
    assert _frame_of(["nsubj", "xcomp"], doing=True) == "ing"
    assert _frame_of(["nsubj", "xcomp"]) == "to"


def test_a_number_of_them_is_that_many_of_them(grammar):
    """"Two of them work in the park.": two things, part of what "them" points back to, do the working; never the
    number 2 working, part of them (UNDERSTANDS-PROSE-01, 2026-10-21)."""
    words = gm.tokens_of("Two of them work in the park.", grammar.lexicon.words)
    meaning = grammar.read(words).meaning
    assert meaning is not None
    facts = {(f.relation, f.subject, f.obj) for f in meaning.facts}
    work = next(s for r, s, o in facts if r == "instance_of" and o == "work")
    doer = next(o for r, s, o in facts if r == "done_by" and s == work)
    assert doer != "2" and {("has_count", doer, "2"), ("part_of", doer, "?previous")} <= facts, facts


def test_a_word_python_reads_as_a_number_is_no_number(grammar):
    """"nan", "inf" and "infinity" are words, though Python's `float` reads them as numbers: a sentence with one is
    read, never stopped (READ-LEARN-01, 2026-10-25)."""
    assert [gm._number(w) for w in ("nan", "Infinity", "inf", "1_000")] == [None] * 4
    assert [gm._number(w) for w in ("3,000", "2.5", "1e999")] == ["3000", "2.5", "1e999"]
    for sentence in ("My nan baked a cake.", "The list goes on to infinity."):
        grammar.read(gm.tokens_of(sentence, grammar.lexicon.words))


def test_what_is_said_of_a_kind(grammar):
    assert read(grammar, "Whales are mammals.") == "tell: isa(whale, mammal)"
    assert read(grammar, "Birds can fly.") == "tell: capable_of(bird, fly)"


def test_what_an_if_says_must_hold(grammar):
    assert read(grammar, "If the valve is closed, the tank is full.") == (
        "tell: given if instance_of(?v0, valve) & given instance_of(?v1, tank) & has_property(?v1, full) & "
        "if has_property(?v0, closed)")


def test_a_sentence_the_grammar_cannot_read_whole_is_not_read(grammar):
    words = gm.tokens_of("Chased the the.", grammar.lexicon.words)
    reading = grammar.read(words)
    assert reading.sign is None and reading.meaning is None and reading.why


def test_learned_links_replace_the_grammars_own(grammar):
    from core.semantics.derived_reader import Meaning, MeaningFact
    taught = gm.Grammar(gm.Lexicon(Held()))
    words = gm.tokens_of("The dog sleeps in the park.", taught.lexicon.words)
    meaning = Meaning("tell", (MeaningFact("instance_of", "?d", "dog", given=True),
                               MeaningFact("instance_of", "?e", "sleep"), MeaningFact("done_by", "?e", "?d"),
                               MeaningFact("instance_of", "?p", "park", given=True),
                               MeaningFact("located_in", "?e", "?p")))
    assert taught.learn(words, meaning, {"?d": [1], "?e": [2], "?p": [5]})
    assert read(grammar, "The dog sleeps in the park.").count("word_in") == 1
    assert "located_in(?v0, ?v2)" in read(taught, "The dog sleeps in the park.")


def test_a_treebanks_uses_are_signed_as_the_grammars_entries_name_them():
    """`HeldWords` counts how each word is used in sentences held analysed, each use named by the grammar's own
    entries: "is" before a doing is `be:ng`, before a thing `be:np`; "who" asking for the doer `wh:subject`. Nothing
    in the counting lists English words: "is" is a form of "be" because the grammar reads it as one."""
    from core.semantics.grammar_words import HeldWords
    from core.semantics.structure import Analysed
    held = [
        Analysed(("Tom", "is", "running", "."), ("NAME", "AUXILIARY", "VERB", "PUNCTUATION"), (3, 3, 0, 3),
                 ("nsubj", "aux", "root", "punct")),
        Analysed(("Tom", "is", "a", "dog", "."), ("NAME", "AUXILIARY", "DETERMINER", "NOUN", "PUNCTUATION"),
                 (4, 4, 4, 0, 4), ("nsubj", "cop", "det", "root", "punct")),
        Analysed(("Who", "barked", "?"), ("PRONOUN", "VERB", "PUNCTUATION"), (2, 0, 2), ("nsubj", "root", "punct")),
    ]
    words = HeldWords(held, gm.closed_uses(), lambda word, cls: VERBS.get(word.lower(), word.lower()))
    assert words.uses("is") == {"be:ng": 1.0, "be:np": 1.0}
    assert words.uses("who") == {"wh:subject": 1.0}
    assert words.uses("dog") == {"NOUN": 1.0}
    assert words.verb_forms("barked") == {"past": 1.0} and words.frames("bark") == {"intransitive": 1.0}
    assert words.noun_alone("dog") == {"determined": 1.0}


def test_a_treebanks_things_said_of_a_doing_with_no_preposition_are_counted():
    """A noun heading a thing said of a doing with no preposition before it (UD's `obl:unmarked`) is counted so, and
    every other use of a noun otherwise: what the grammar weighs reading "that morning" as when a doing was by."""
    from core.semantics.grammar_words import HeldWords
    from core.semantics.structure import Analysed
    held = [Analysed(("The", "dog", "barked", "that", "morning", "."),
                     ("DETERMINER", "NOUN", "VERB", "DETERMINER", "NOUN", "PUNCTUATION"), (2, 3, 0, 5, 3, 3),
                     ("det", "nsubj", "root", "det", "obl:unmarked", "punct"))]
    words = HeldWords(held, gm.closed_uses(), lambda word, cls: VERBS.get(word.lower(), word.lower()))
    assert words.bare_modifier("morning") == {"modifier": 1.0}
    assert words.bare_modifier("dog") == {"otherwise": 1.0}


def test_a_time_said_with_no_preposition_says_when_a_doing_was():
    """"That morning the dog barked." and "The dog barked that morning.": the morning is when the barking was
    (`during`, as the PMB's meanings say a happening's time), opening the sentence or after its doing. With no way
    to read it, "One morning the dog ran to the park." was read as a morning the dog ran to (lyric_dev,
    2026-10-24)."""

    class Timed(Held):
        def uses(self, word: str) -> Mapping[str, float]:
            return {"NOUN": 10.0} if word.lower() == "morning" else super().uses(word)

        def bare_modifier(self, word: str) -> Mapping[str, float]:
            return {"modifier": 5.0, "otherwise": 5.0} if word.lower() == "morning" else {}

        def is_time(self, term: str) -> Optional[str]:
            return "stretch" if str(term).lower() == "morning" else None

    timed = gm.Grammar(gm.Lexicon(Timed()))
    for said in ("That morning the dog barked.", "The dog barked that morning."):
        meaning = read(timed, said)
        assert meaning is not None and "during(?v0, " in meaning and "instance_of(?v0, bark)" in meaning, \
            (said, meaning)
        assert "if " not in meaning, (said, meaning)


def test_a_sentence_taught_again_corrected_is_taken_back_from_what_was_learned():
    """`GrammarView.drop` takes back what a taught sentence's reading counted, so the corrected one is learned
    alone."""
    from core.semantics.composition import TaughtSentence
    from core.semantics.derived_reader import Meaning, MeaningFact
    view = gm.GrammarView(Held())

    def taught(link):
        return TaughtSentence("The dog sleeps in the park.", Meaning("tell", (
            MeaningFact("instance_of", "?d", "dog", given=True), MeaningFact("instance_of", "?e", "sleep"),
            MeaningFact("done_by", "?e", "?d"), MeaningFact("instance_of", "?p", "park", given=True),
            MeaningFact(link, "?e", "?p"))), "lessons")
    first, again = taught("word_in"), taught("located_in")
    view.hold(first)
    view.hold(first)
    view.learn_waiting()
    assert view.learned_from == 1
    assert "word_in(?v0, ?v2)" in view.compose_sentence("The dog sleeps in the park.").canonical()
    view.drop(first)
    view.hold(again)
    assert "located_in(?v0, ?v2)" in view.compose_sentence("The dog sleeps in the park.").canonical()
    assert view.grammar.lexicon.learned["prep"][("in", "event", "-")] == {"located_in": 1}


def test_memory_reads_with_the_grammar_built_from_what_it_holds():
    """`MemoryAgent.grammar_view`: the grammar built from the sentences memory holds analysed, its links between
    things and its sentences taught with their meanings; "Lincoln" a name because memory holds him an instance."""
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.structure import Analysed, StructureView
    agent = MemoryAgent()
    agent._structure_view = StructureView()
    agent._structure_view.add(Analysed(("Tom", "chased", "a", "cat", "."),
                                       ("NAME", "VERB", "DETERMINER", "NOUN", "PUNCTUATION"), (2, 0, 4, 2, 2),
                                       ("nsubj", "root", "det", "obj", "punct")))
    agent._grammar_links = [("lincoln", "instance of", "president"), ("president", "isa", "person")]
    view = agent.grammar_view()
    assert view.words.capitalized("Lincoln").get("NAME", 0) > 0
    assert view.words.is_person("president")
    assert view.compose_sentence("Tom chased a cat.") == view.compose_sentence("Tom chased a cat.")
    assert agent.grammar_view() is view


class Ordering(Held):
    """The words above, with "fish" and "swim" both nouns and verbs, and sentences held that are orders as often as
    `ordered` says."""

    def __init__(self, ordered: float, told: float):
        self.ordered, self.told = ordered, told

    def uses(self, word: str) -> Mapping[str, float]:
        if word.lower() in ("fish", "swim"):
            return {"NOUN": 10.0, "VERB": 10.0}
        return super().uses(word)

    def frames(self, name: str) -> Mapping[str, float]:
        return {"fish": {"transitive": 9.0}, "swim": {"intransitive": 9.0}}.get(name, super().frames(name))

    def orders(self):
        return self.ordered, self.told


def test_an_order_is_a_sentence_and_said_as_often_as_orders_are():
    """An order (`S[b]\\NP`) ranks as a sentence, not as a phrase said alone; between an order and a telling, as
    often as what is said is each. "Fish swim." reads either way by its words: as seldom as orders are, it tells
    of fish swimming; were orders said as often as tellings are now, it would ask the listener to fish."""
    assert gm._rank(gm.parse_category("S[b]\\NP")) == 2 and gm._rank(gm.parse_category("NP")) == 0
    seldom = gm.Grammar(gm.Lexicon(Ordering(ordered=7.0, told=150.0)))
    often = gm.Grammar(gm.Lexicon(Ordering(ordered=150.0, told=7.0)))
    assert read(seldom, "Fish swim.") == "tell: done_by(?v0, fish) & instance_of(?v0, swim)"
    assert read(often, "Fish swim.").startswith("request:"), read(often, "Fish swim.")


def test_a_treebanks_orders_are_counted_from_who_does_the_doing():
    """A sentence whose doing has no doer said and nothing helping it is an order; one that says its doer is not;
    a question, and a heading with no doing, are neither."""
    from core.semantics.grammar_words import HeldWords
    from core.semantics.structure import Analysed
    held = [
        Analysed(("Read", "the", "links", "."), ("VERB", "DETERMINER", "NOUN", "PUNCTUATION"), (0, 3, 1, 1),
                 ("root", "det", "obj", "punct")),
        Analysed(("Tom", "barked", "."), ("NAME", "VERB", "PUNCTUATION"), (2, 0, 2), ("nsubj", "root", "punct")),
        Analysed(("Who", "barked", "?"), ("PRONOUN", "VERB", "PUNCTUATION"), (2, 0, 2), ("nsubj", "root", "punct")),
        Analysed(("UPDATE", ":"), ("NOUN", "PUNCTUATION"), (0, 1), ("root", "punct")),
    ]
    words = HeldWords(held, gm.closed_uses(), lambda word, cls: VERBS.get(word.lower(), word.lower()))
    assert words.orders() == (1.0, 1.0)


def test_what_a_happening_was_during_is_learned_a_time():
    """A sentence taught with its meaning says what its happening was during, and that is a time
    (`Lexicon.time_of`): learned from the lessons where memory holds nothing of what a morning is. A happening
    another was during ("The dog barked when the cat ran.") is no time: counted as one, `run` was."""
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    g = gm.Grammar(gm.Lexicon(Held()))
    assert g.lexicon.time_of("morning") is None
    barked = Meaning("tell", (F("instance_of", "?v0", "bark"), F("during", "?v0", "?v1"),
                              F("instance_of", "?v1", "morning")))
    g.learn(gm.tokens_of("The dog barked in the morning.", g.lexicon.words), barked, {})
    assert g.lexicon.time_of("morning") == "point"
    when = Meaning("tell", (F("instance_of", "?v0", "bark"), F("instance_of", "?v1", "run"),
                            F("done_by", "?v1", "cat"), F("during", "?v0", "?v1")))
    g.learn(gm.tokens_of("The dog barked when the cat ran.", g.lexicon.words), when, {})
    assert g.lexicon.time_of("run") is None


def test_what_a_sentence_taught_is_kept_and_not_learned_again():
    """What the grammar learned from a sentence is given once to be kept with it (`GrammarView.unkept`), and a grammar
    holding the sentence with what it taught (`hold(taught, learned)`) has learned the same, reading nothing again:
    a start no longer learns from every taught sentence anew."""
    from core.semantics.composition import TaughtSentence
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    taught = TaughtSentence("The dog barked in the morning.",
                            Meaning("tell", (F("instance_of", "?v0", "bark"), F("during", "?v0", "?v1"),
                                             F("instance_of", "?v1", "morning"))))
    first = gm.GrammarView(Held())
    first.hold(taught)
    assert first.learn_waiting() == 1
    kept = first.unkept()
    assert list(kept) == [taught.key()] and first.unkept() == {}, "each is given once"
    stored = [[table, list(key), list(link) if isinstance(link, tuple) else link] for table, key, link in kept[taught.key()]]
    second = gm.GrammarView(Held())
    second.hold(taught, stored)
    assert second.learn_waiting() == 0, "nothing is read again"
    assert second.learned_from == 1
    learned = lambda view: {t: {k: dict(c) for k, c in tab.items()} for t, tab in view.grammar.lexicon.learned.items()
                            if tab}
    assert learned(second) == learned(first)
    assert second.grammar.lexicon.time_of("morning") == "point"


def test_reading_teaches_how_words_are_used_only_where_it_may_and_once():
    """A sentence read inside `reading_teaches` adds how its reading used each word to the counts the grammar reads
    with (`HeldWords.hear_read`), as much as the reading was sure; outside it, and read a second time, it teaches
    nothing. What it taught, given to memory once (`unkept_read`) and held again (`hold_read`), counts the same."""
    from core.semantics.grammar_words import HeldWords
    from core.semantics.structure import Analysed
    held = [Analysed(("The", "dog", "barked", "."), ("DETERMINER", "NOUN", "VERB", "PUNCTUATION"), (2, 3, 0, 3),
                     ("det", "nsubj", "root", "punct")),
            Analysed(("The", "cat", "slept", "."), ("DETERMINER", "NOUN", "VERB", "PUNCTUATION"), (2, 3, 0, 3),
                     ("det", "nsubj", "root", "punct"))]

    def view():
        return gm.GrammarView(HeldWords(held, gm.closed_uses(), lambda word, cls: VERBS.get(word.lower(), word.lower())))
    reader = view()
    before = dict(reader.words.uses("dog"))
    reader.read("The dog barked.")
    assert reader.unkept_read() == [] and dict(reader.words.uses("dog")) == before, "reading outside teaches nothing"
    with gm.reading_teaches():
        reader.read("The dog barked.")
        taught = dict(reader.words.uses("dog"))
        reader.read("The dog barked.")
    assert taught.get("NOUN", 0) > before.get("NOUN", 0), (before, taught)
    assert dict(reader.words.uses("dog")) == taught, "a sentence read again teaches nothing more"
    records = reader.unkept_read()
    assert len(records) == 1 and reader.unkept_read() == []
    again = view()
    again.hold_read(records[0])
    assert dict(again.words.uses("dog")) == taught


def test_what_a_preposition_says_is_decided_by_what_its_thing_is():
    """"from" a place is where a doing came from, "from" a feeling what caused it: learned of what the taught things
    are (`prep_to`, each kind its thing is), and decided by what a new one is for a verb no sentence taught with
    "from" (`Lexicon.selected`): "The cat sleeps from the park." and "... from fear." (READ-LEARN-01, 2026-10-25)."""
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    kinds = {"park": ["place", "location"], "garden": ["place", "location"], "fear": ["feeling", "state"],
             "hunger": ["feeling", "state"]}

    class Kinds(Held):
        def uses(self, word: str) -> Mapping[str, float]:
            return {"NOUN": 10.0} if word.lower() in kinds else super().uses(word)

        def name(self, word: str, cls: str) -> str:
            return word.lower() if word.lower() in kinds else super().name(word, cls)

        def kinds(self, name: str, cls: str):
            return kinds.get(name, [])
    g = gm.Grammar(gm.Lexicon(Kinds()))

    def teach(sentence: str, link: F, what: str, given: bool) -> None:
        meaning = Meaning("tell", (F("instance_of", "?v0", "bark"), F("done_by", "?v0", "?v1"),
                                   F("instance_of", "?v1", "dog", given=True), F("precedes", "?v0", "?now"), link,
                                   F("instance_of", "?v2", what, given=given)))
        tokens = gm.tokens_of(sentence, g.lexicon.words)
        assert g.learn(tokens, meaning, gm.align_by_names(tokens, meaning, g.lexicon))
    for _ in range(2):
        teach("The dog barked from the garden.", F("moves_from", "?v0", "?v2"), "garden", True)
        teach("The dog barked from hunger.", F("causes", "?v2", "?v0"), "hunger", False)
    assert read(g, "The cat sleeps from the park.") == ("tell: done_by(?v0, ?v1) & given instance_of(?v1, cat) & "
                                                        "given instance_of(?v2, park) & instance_of(?v0, sleep) & "
                                                        "moves_from(?v0, ?v2)")
    assert read(g, "The cat sleeps from fear.") == ("tell: causes(?v0, ?v1) & done_by(?v1, ?v2) & given "
                                                    "instance_of(?v2, cat) & instance_of(?v0, fear) & "
                                                    "instance_of(?v1, sleep)")


def test_a_kind_memory_takes_in_is_known_at_once():
    """What memory has just taken a thing to be ("Harvard is a university.") is what the grammar's words hold it to
    be from then on (`Words.hear_kind`, from `MemoryAgent.link_concepts`), not from the next warm."""
    from core.semantics.grammar_words import GraphKnowledge, HeldWords
    knowledge = GraphKnowledge()
    knowledge.add("university", "isa", "institution")
    words = HeldWords((), gm.closed_uses(), lambda word, cls: word.lower(), knowledge)
    assert words.kinds("harvard", "NOUN") == []
    words.hear_kind("Harvard", "instance_of", "university")
    assert words.kinds("harvard", "NOUN") == ["university", "institution"]
    assert gm.Words().hear_kind("Harvard", "instance_of", "university") is None


def _derived(pairs: Sequence[Tuple[str, str]], tags: Sequence[str], tree=(), said_in: str = "") -> gm.Derived:
    """A sentence derived by hand: its words with the categories the bank gives them, and their parts of speech."""
    words = tuple(w for w, _ in pairs)
    spans, at = [], 0
    for w in words:
        spans.append((at, at + len(w)))
        at += len(w) + 1
    n = len(words)
    return gm.Derived(" ".join(words), words, tuple(c for _, c in pairs), tuple(tags), tuple(w.lower() for w in words),
                      ("",) * n, ((),) * n, ("",) * n, tuple(spans), tree, said_in)


def test_a_derivation_is_read_as_the_bank_writes_it(tmp_path):
    """`pmb_meanings.read_derivations`: each sentence of a document's `en.parse.tags`, its words with their categories,
    parts of speech, lemmas, senses and roles, where each is in its sentence, and how they were combined; kept whole
    and given back the same (`Derived.to_dict`)."""
    from core.semantics.pmb_meanings import read_derivations
    folder = tmp_path / "p00" / "d0001"
    folder.mkdir(parents=True)
    (folder / "en.raw").write_text("Tom isn't here. Dogs bark.\n", encoding="utf-8")
    (folder / "en.parse.tags").write_text(""":- op(601, xfx, (/)).
ccg(1,
 rp(s:dcl,
  ba(s:dcl,
   lx(np, n,
    t(n, 'Tom', [from:0, to:3, pos:'NNP', lemma:'tom', sem:'PER', wordnet:'male.n.02'])),
   fa(s:dcl\\np,
    t((s:dcl\\np)/(s:adj\\np), 'is', [from:4, to:6, pos:'VBZ', lemma:'be', sem:'NOW', wordnet:'O']),
    ba(s:adj\\np,
     t(s:adj\\np, 'here', [from:10, to:14, pos:'RB', lemma:'here', sem:'REL', wordnet:'O']),
     t((s\\np)\\(s\\np), 'n\\'t', [from:6, to:9, pos:'RB', lemma:'not', sem:'NOT', wordnet:'O'])))),
  t(., '.', [from:14, to:15, pos:'.', lemma:'.', sem:'NIL', wordnet:'O']))).
ccg(2,
 ba(s:dcl,
  lx(np, n,
   t(n, 'Dogs', [from:16, to:20, pos:'NNS', lemma:'dog', sem:'CON', wordnet:'dog.n.01'])),
  t(s:dcl\\np, 'bark', [from:21, to:25, pos:'VBP', lemma:'bark', sem:'ENS', wordnet:'bark.v.04', verbnet:['Agent']]))).
""", encoding="utf-8")
    first, second = read_derivations(folder)
    assert first.words == ("Tom", "is", "here", "n't", ".") and first.text == "Tom isn't here."
    assert first.categories[1] == "(s:dcl\\np)/(s:adj\\np)" and first.categories[4] == "."
    assert first.tags[0] == "NNP" and first.senses == ("male.n.02", "", "", "", "")
    assert first.said_in == "pmb/p00/d0001" and (first.part, second.part) == (1, 2)
    assert first.tree[0] == "rp" and first.tree[2][2] == ("lx", "np", "n", 0)
    assert second.text == "Dogs bark" and second.spans == ((0, 4), (5, 9)) and second.roles[1] == ("Agent",)
    assert gm.Derived.from_dict(first.to_dict()) == first and first.key() != second.key()


def test_a_derivations_words_are_named_as_the_grammars_entries_name_them():
    """Each word of a derivation is named by the use of the grammar's entry whose category the derivation gives it
    (`Lexicon.uses_derived`), what the bank says otherwise put as the grammar says it: a phrase of a preposition a
    verb takes ("gave milk to the cat") read as telling of the giving, so "gave" takes the milk alone; "my" before a
    relational noun ("my uncle") the grammar's determiner; a verb's frame from its category."""
    lexicon = gm.Lexicon(Held())
    gave = _derived([("Tom", "n"), ("gave", "((s:dcl\\np)/pp)/np"), ("milk", "n"), ("to", "pp/np"), ("the", "np/n"),
                     ("cat", "n"), (".", ".")], ["NNP", "VBD", "NN", "TO", "DT", "NN", "."],
                    ("rp", "s:dcl", ("ba", "s:dcl", ("lx", "np", "n", 0),
                                     ("fa", "s:dcl\\np", ("fa", "(s:dcl\\np)/pp", 1, ("lx", "np", "n", 2)),
                                      ("fa", "pp", 3, ("fa", "np", 4, 5)))), 6))
    assert lexicon.uses_derived(gave) == [("NAME", ""), ("VERB", "transitive"), ("NOUN", ""), ("PREPOSITION", ""),
                                          ("det", ""), ("NOUN", ""), None]
    uncle = _derived([("my", "np/(n/pp)"), ("uncle", "n/pp"), ("barked", "s:dcl\\np"), ("up", "pr"),
                      ("Burt~Lancaster", "n")], ["PRP$", "NN", "VBD", "RP", "NNP"])
    assert lexicon.uses_derived(uncle) == [("det", ""), ("NOUN", ""), ("VERB", "intransitive"), ("PARTICLE", ""),
                                           None]


def test_a_words_category_is_chosen_beside_the_words_around_it():
    """What the sentences derived by hand say a word takes beside the words around it decides its way
    (`Lexicon._in_context`) and a verb's frame (`_frame_evidence`): a word used as a noun more than as a verb is a
    verb after "will", a noun after "the"; a verb nothing is held of takes a thing before "the" and nothing before
    "."; a word the
    derivations never hold beside words they never hold is weighed as the treebank weighs it. A sentence derived
    otherwise since is taken back (`GrammarView.drop_derived`)."""
    class Fight(Held):
        def uses(self, word):
            return {"NOUN": 10.0, "VERB": 2.0} if word.lower() == "fight" else super().uses(word)

        def name(self, word, cls):
            return "fight" if word.lower() == "fight" else super().name(word, cls)

    view = gm.GrammarView(Fight())
    lexicon = view.grammar.lexicon
    before = lexicon._evidence(("Dogs", "will", "fight", "."), 2)
    assert before["NOUN"] > before["VERB"]
    held = [_derived([("Tom", "n"), ("will", "(s:dcl\\np)/(s:b\\np)"), ("run", "s:b\\np"), (".", ".")],
                     ["NNP", "MD", "VB", "."]),
            _derived([("Rex", "n"), ("will", "(s:dcl\\np)/(s:b\\np)"), ("sleep", "s:b\\np"), (".", ".")],
                     ["NNP", "MD", "VB", "."]),
            _derived([("the", "np/n"), ("dog", "n"), ("chased", "(s:dcl\\np)/np"), ("the", "np/n"), ("cat", "n")],
                     ["DT", "NN", "VBD", "DT", "NN"]),
            _derived([("the", "np/n"), ("cat", "n"), ("ate", "s:dcl\\np"), (".", ".")], ["DT", "NN", "VBD", "."])]
    for item in held:
        view.hold_derived(item)
        view.hold_derived(item)
    assert lexicon.derived["uses"][""]["VERB"] == 4, "each sentence is counted once"
    assert view.rules != gm.RULES
    after_will = lexicon._evidence(("Dogs", "will", "fight", "."), 2)
    assert after_will["VERB"] > after_will["NOUN"]
    after_the = lexicon._evidence(("The", "fight", "ended", "."), 1)
    assert after_the["NOUN"] > after_the["VERB"]
    unheard = lexicon._evidence(("Zoe", "saw", "fight", "here"), 2)
    assert unheard["NOUN"] > unheard["VERB"]
    taking = lexicon._frame_evidence("push", "the")
    assert taking["transitive"] > taking["intransitive"]
    alone = lexicon._frame_evidence("push", ".")
    assert alone["intransitive"] > alone["transitive"]
    for item in held:
        view.drop_derived(item)
    assert not any(lexicon.derived["uses"].values()) and view.rules == gm.RULES


def test_memory_hands_the_sentences_it_holds_derived_to_the_grammar():
    """`MemoryAgent.grammar_view` holds what memory holds derived by hand before the taught sentences, and takes what
    the grammar learned from a taught sentence before only where it was learned under the rules it holds now
    (`GrammarView.rules`)."""
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.composition import TaughtSentence
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    from core.semantics.structure import StructureView
    agent = MemoryAgent()
    agent._structure_view = StructureView()
    agent._grammar_derived = [_derived([("Tom", "n"), ("barked", "s:dcl\\np"), (".", ".")], ["NNP", "VBD", "."])]
    taught = TaughtSentence("The dog barked.", Meaning("tell", (F("instance_of", "?v0", "bark"),
                                                                 F("done_by", "?v0", "?v1"),
                                                                 F("instance_of", "?v1", "dog", given=True))))
    agent._grammar_taught = [taught]
    agent._grammar_learned = {taught.key(): ("m1", [["verb", ["bark"], ""]], gm.RULES)}
    view = agent.grammar_view()
    assert view.grammar.lexicon.derived["uses"]["barked"] == {"VERB": 1}
    assert view.learn_waiting() == 1, "learned under the rules before the derivations: learned again"
