"""Reading by English's grammar (`core/semantics/grammar.py`): each word's category and meaning, combined by general
rules. The words here are held in the test (`Held`), as memory would hold them; nothing is learned, so every link is
the grammar's own."""
from typing import Dict, Mapping, Optional, Sequence

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
