"""Reading by English's grammar (`core/semantics/grammar.py`): each word's category and meaning, combined by general
rules. The words here are held in the test (`Held`), as memory would hold them; nothing is learned, so every link is
the grammar's own."""
from typing import Dict, Mapping, Optional, Sequence, Tuple

import pytest

from core.semantics import grammar as gm

NOUNS = {"dog": "dog", "dogs": "dog", "cat": "cat", "ball": "ball", "whale": "whale", "whales": "whale",
         "mammal": "mammal", "mammals": "mammal", "bird": "bird", "birds": "bird", "valve": "valve", "tank": "tank",
         "shirt": "shirt", "account": "account", "park": "park", "card": "card", "cards": "card", "credit": "credit"}
VERBS = {"chased": "chase", "chase": "chase", "barked": "bark", "bark": "bark", "barks": "bark", "fly": "fly",
         "unbuttoned": "unbutton", "locked": "lock", "kick": "kick", "kicked": "kick", "sleeps": "sleep",
         "began": "begin", "working": "work", "work": "work", "fell": "fall", "chain": "chain", "chained": "chain"}
#: "chained" is held as a verb's participle and as an adjective of its own, as memory holds a word WordNet gives both
#: (`chain.v.01`, `chained.s.01`).
ADJECTIVES = {"closed": "closed", "full": "full", "red": "red", "happy": "happy", "chained": "chained",
              "fed": "fed"}
PREPOSITIONS = ("in", "on", "from")
FORMS = {"chased": {"past": 5.0, "participle": 1.0}, "barked": {"past": 5.0}, "unbuttoned": {"past": 2.0},
         "locked": {"participle": 4.0, "past": 2.0}, "kicked": {"past": 3.0}, "began": {"past": 5.0},
         "fell": {"past": 5.0}, "chained": {"participle": 4.0, "past": 2.0}}
FRAMES = {"chase": {"transitive": 9.0}, "chain": {"transitive": 9.0}, "bark": {"intransitive": 9.0},
          "fly": {"intransitive": 9.0},
          "unbutton": {"transitive": 9.0}, "lock": {"transitive": 9.0}, "kick": {"transitive": 9.0},
          "sleep": {"intransitive": 9.0}, "begin": {"ing": 6.0, "to": 3.0}, "work": {"intransitive": 9.0},
          "fall": {"intransitive": 9.0}}


#: Words memory holds as one word of several ("'fed up' is used as an adjective.", `WordNetSource._word_classes`),
#: each under the name it is held by and the kind of word it is held as.
KNOWN = {("fed", "up"): {"ADJECTIVE": "disgusted"}, ("at", "last"): {"ADVERB": "finally"},
         ("credit", "card"): {"NOUN": "credit card"}}


class Held(gm.Words):
    """A few words, as memory would hold them."""

    def known_words(self, words: Sequence[str]) -> Mapping[str, str]:
        return KNOWN.get(tuple(w.lower() for w in words), {})

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

    def lexeme(self, word: str, cls: str) -> str:
        # The names above are the words each form is of.
        return self.name(word, cls)

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


def test_a_participle_says_a_quality_where_memory_holds_the_word_as_an_adjective(grammar):
    """A word spelled as a verb's participle says a quality of the thing where memory holds the word as an adjective
    too ("Is the dog chained?", `chained.s.01`); where a doer is said with it, the passive; and a word memory holds
    only as the verb's form says the passive whatever stands with it ("The valve is locked."). Of the words written as
    a participle the PMB's gold says a quality, 95% are of a word WordNet holds as an adjective
    (`GRAMMAR-01/diagnostics/participles.py`); lab notebook (78)."""
    assert read(grammar, "Is the dog chained?") == (
        "ask: given instance_of(?v0, dog) & has_property(?v0, chained)")
    assert read(grammar, "The dog was chained by a cat.") == (
        "tell: done_by(?v0, ?v1) & done_to(?v0, ?v2) & given instance_of(?v2, dog) & instance_of(?v0, chain) & "
        "instance_of(?v1, cat) & precedes(?v0, ?now)")
    assert read(grammar, "The valve is locked.") == (
        "tell: done_to(?v0, ?v1) & given instance_of(?v1, valve) & instance_of(?v0, lock)")


def test_an_inverted_passive_question(grammar):
    assert read(grammar, "Was the account locked?") == (
        "ask: done_to(?v0, ?v1) & given instance_of(?v1, account) & instance_of(?v0, lock) & precedes(?v0, ?now)")


def test_a_denied_happening(grammar):
    assert read(grammar, "The dog did not bark.") == (
        "tell: done_by(?v0, ?v1) & given instance_of(?v1, dog) & has_property(?v0, false) & instance_of(?v0, bark) "
        "& precedes(?v0, ?now)")


def test_words_joined_by_hyphens_are_one_word_where_memory_holds_one_and_their_words_where_it_holds_none():
    # Held as one in some spelling: "bullet-proof" as `bulletproof`, "state-of-the-art" as written. Held in none:
    # "happy-red" is "happy" and "red", where it was a word nothing names (`Lexicon.hyphened`).
    whole = {"bulletproof": "ADJECTIVE", "state-of-the-art": "ADJECTIVE"}

    class Hyphened(Held):
        def uses(self, word: str) -> Mapping[str, float]:
            return {whole[word.lower()]: 10.0} if word.lower() in whole else super().uses(word)

        def spelled(self, word: str) -> Optional[str]:
            w = word.lower()
            return next((s for s in (w, w.replace("-", "")) if s in whole), None)
    g = gm.Grammar(gm.Lexicon(Hyphened()))
    barked = ("tell: done_by(?v0, ?v1) & given instance_of(?v1, dog) & {} & instance_of(?v0, bark) & "
              "precedes(?v0, ?now)")
    assert read(g, "The bullet-proof dog barked.") == barked.format("has_property(?v1, bulletproof)")
    assert read(g, "The state-of-the-art dog barked.") == barked.format("has_property(?v1, state-of-the-art)")
    assert read(g, "The happy-red dog barked.") == read(g, "The happy red dog barked.") == barked.format(
        "has_property(?v1, happy) & has_property(?v1, red)")


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


def test_words_joined_by_hyphens_are_held_as_memory_spells_them():
    from core.semantics.grammar_words import GraphKnowledge, HeldWords
    held = {"bulletproof": {"ADJECTIVE": 1.0}, "ice cream": {"NOUN": 1.0}, "know-how": {"NOUN": 1.0}}
    words = HeldWords((), gm.closed_uses(), lambda word, cls: word.lower(),
                      GraphKnowledge(classes=lambda w: held.get(w.lower(), {})))
    assert [words.spelled(w) for w in ("bullet-proof", "ice-cream", "Know-how", "novel-based")] == [
        "bulletproof", "ice cream", "know-how", None]


def _derived(pairs: Sequence[Tuple[str, str]], tags: Sequence[str], tree=(), said_in: str = "",
             text: str = "") -> gm.Derived:
    """A sentence derived by hand: its words with the categories the bank gives them, and their parts of speech; its
    text as written (its words with a space between them where none is given)."""
    words = tuple(w for w, _ in pairs)
    text = text or " ".join(words)
    spans, at = [], 0
    for w in words:
        k = text.find(w, at)
        spans.append((k, k + len(w)))
        at = k + len(w)
    n = len(words)
    return gm.Derived(text, words, tuple(c for _, c in pairs), tuple(tags), tuple(w.lower() for w in words),
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
    # Named by the entry its category is most exactly: "very" before a quality (`S[adj]`) is a degree, never the
    # adverb of a doing whose `S[F]` is alike to it too (`_exactness`).
    smooth = _derived([("The", "np/n"), ("sea", "n"), ("was", "(s:dcl\\np)/(s:adj\\np)"),
                       ("very", "(s:adj\\np)/(s:adj\\np)"), ("smooth", "s:adj\\np")], ["DT", "NN", "VBD", "RB", "JJ"])
    assert lexicon.uses_derived(smooth)[3] == ("ADVERB:degree", "")


def test_a_doing_is_the_head_of_what_a_thing_raised_over_it_takes(grammar):
    # "nothing" after a verb is raised over the doing (`(S\NP)\((S\NP)/NP)`): the doing heads what they make, as a
    # modifier's does, and "The dog" is joined to "chased", never to "nothing" (`_takes_its_head`).
    tokens = gm.tokens_of("The dog chased nothing.", grammar.lexicon.words)
    reading = grammar.read(tokens)
    assert reading.sign.head == 2 and "has_property(?v0, false)" in reading.meaning.canonical()
    assert all(s.head == 2 for s in grammar.chart(tokens)[(2, 4)].values() if str(s.cat).startswith("(S[dcl]"))
    assert gm._takes_its_head(gm.parse_category("S/(S\\NP)")) and not gm._takes_its_head(gm.parse_category("NP/N"))


def test_a_kind_of_a_kind_is_the_kind_said_and_no_thing_of_its_own(grammar):
    # "this kind of cat": a kind of cat (the PMB's `InstanceOf`), no cat and no "kind"; asked, the kind is asked.
    assert "isa(?v2, cat)" in read(grammar, "The dog chased this kind of cat.")
    assert read(grammar, "What kind of cat did the dog chase?").endswith("isa(?v2, cat) & precedes(?v0, ?now) ? ?v2")
    assert "instance_of(?v2, cat)" in read(grammar, "The dog chased a cat.")


def test_a_time_of_the_clock_is_one_time_its_half_of_the_day_where_its_words_say_it(grammar):
    # "six o'clock", "8:00", "7:15 a.m.", "5 p.m.": one time each, as times are written (`literals`).
    times = {"The dog barked at six o'clock.": "6:00", "The dog barked at 8:00.": "8:00",
             "The dog barked at 7:15 a.m.": "7:15 a.m.", "The dog barked at 5 p.m.": "5:00 p.m."}
    for text, written in times.items():
        tokens = gm.tokens_of(text, grammar.lexicon.words)
        at = tokens.index("at") + 1
        assert grammar.lexicon._clock_time(tokens, at) == (len(tokens) - 1, written), text
    assert grammar.lexicon._clock_time(gm.tokens_of("Six dogs barked.", grammar.lexicon.words), 0) is None


def test_what_a_thing_is_said_not_to_be_is_denied_with_its_qualities(grammar):
    # "Tom is not a happy dog.": no happy dog, so not happy either; said of Tom, the quality was told as so.
    assert "not has_property(?v0, happy)" in read(grammar, "Tom is not a happy dog.")
    assert "& has_property(?v0, happy)" in read(grammar, "Tom is a happy dog.")


def test_a_degree_word_grades_the_quality_or_the_doings_quality_it_is_said_of():
    # "very happy": a degree of happiness, the dog's, that is very (the PMB's and the lessons' way); "barked very
    # loudly": a degree of the barking's loudness.
    class Graded(Held):
        def uses(self, word: str) -> Mapping[str, float]:
            w = word.lower()
            if w == "very":
                return {"ADVERB:degree": 50.0, "ADVERB": 2.0}
            return {"ADVERB": 10.0} if w == "loudly" else super().uses(word)
    g = gm.Grammar(gm.Lexicon(Graded()))
    assert read(g, "The dog is very happy.") == (
        "tell: given instance_of(?v0, dog) & has_degree(?v0, ?v1) & has_property(?v1, very) & instance_of(?v1, happy)")
    assert read(g, "The dog barked very loudly.") == (
        "tell: done_by(?v0, ?v1) & given instance_of(?v1, dog) & has_degree(?v0, ?v2) & has_property(?v2, very) & "
        "instance_of(?v0, bark) & instance_of(?v2, loudly) & precedes(?v0, ?now)")
    assert "has_property(?v0, loudly)" in read(g, "The dog barked loudly.")


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


def test_a_verbs_places_are_learned_from_the_sentence_as_derived():
    """Where a taught sentence's derivation by hand is held (the same document), what fills each of a verb's places is
    as the derivation says, the link as the meaning says (`Grammar._learn_places_derived`), and the reading's own
    places for that verb are not counted again; learned without it, from the reading, as before."""
    from core.semantics.composition import TaughtSentence
    from core.semantics.derived_reader import Meaning, MeaningFact as F
    meaning = Meaning("tell", (F("instance_of", "?v0", "chase"), F("done_by", "?v0", "tom"),
                               F("done_to", "?v0", "?v1"), F("instance_of", "?v1", "cat", given=True),
                               F("precedes", "?v0", "?now")))
    taught = TaughtSentence("Tom chased the cat.", meaning, "pmb/p00/d0001",
                            (("?v0", ((4, 10, "head", ()),)), ("?v1", ((15, 18, "head", ()),)),
                             ("tom", ((0, 3, "head", ()),))))
    derived = _derived([("Tom", "n"), ("chased", "(s:dcl\\np)/np"), ("the", "np/n"), ("cat", "n"), (".", ".")],
                       ["NNP", "VBD", "DT", "NN", "."],
                       ("rp", "s:dcl", ("ba", "s:dcl", ("lx", "np", "n", 0), ("fa", "s:dcl\\np", 1, ("fa", "np", 2, 3))),
                        4), "pmb/p00/d0001", "Tom chased the cat.")
    view = gm.GrammarView(Held())
    view.hold_derived(derived)
    view.hold(taught)
    view.learn_waiting()
    roles = [c for c in view._counted[taught.key()] if c[0] == "role"]
    assert sorted(roles) == [("role", ("chase", "object"), "done_to"), ("role", ("chase", "subject"), "done_by")]
    tokens = gm.tokens_of(taught.sentence, view.words)
    counted = []
    placed = view.grammar._learn_places_derived(tokens, meaning, gm.align_by_anchors(tokens, taught.sentence,
                                                                                    taught.anchors),
                                                [derived], taught.sentence, counted)
    assert placed == {1} and sorted(counted) == roles, "the derivation placed the verb's places"
    view.grammar.unlearn(counted)
    alone = gm.GrammarView(Held())
    alone.hold(taught)
    alone.learn_waiting()
    assert sorted(c for c in alone._counted[taught.key()] if c[0] == "role") == sorted(roles)


def test_which_word_takes_which_is_decided_by_how_the_structure_view_joins_them():
    """Two readings of the same words read as surely ("in the park" of the chasing, or of the cat) are chosen between
    by how likely the structure view makes each join (`Grammar._joined`, `StructureView.joins`), each phrase by the
    word it is about as the treebanks join them ("in the park": park); with none held, as the chart built them."""
    import math

    import numpy as np

    class Joins:
        """A structure view that joins "park" to one word, and less likely to any other."""

        def __init__(self, head: str):
            self.head = head

        def __len__(self) -> int:
            return 1

        def joins(self, words):
            n = len(words)
            classes = tuple("PREPOSITION" if w.lower() in PREPOSITIONS else "DETERMINER" if w.lower() == "the"
                            else "NOUN" for w in words)
            weighed = np.full((n + 1, n + 1), math.log(0.5))
            park = words.index("park")
            for h in range(n):
                weighed[h + 1, park + 1] = 0.0 if words[h] == self.head else math.log(0.01)
            return classes, weighed
    said = "tell: done_by(?v0, ?v1) & done_to(?v0, ?v2) & given instance_of(?v1, dog) & given instance_of(?v2, cat) " \
           "& given instance_of(?v3, park) & instance_of(?v0, chase) & precedes(?v0, ?now) & "
    for head, where in ((None, "word_in(?v0, ?v3)"), ("chased", "word_in(?v0, ?v3)"), ("cat", "word_in(?v2, ?v3)")):
        g = gm.Grammar(gm.Lexicon(Held()))
        g.structure = Joins(head) if head else None
        assert read(g, "The dog chased the cat in the park.") == said + where, head


class Speaking(Held):
    """The words above, with memory's words for each thing (`Words.words_for`): every form held of it."""

    def words_for(self, name: str, cls: str):
        held = {"NOUN": NOUNS, "VERB": VERBS, "ADJECTIVE": ADJECTIVES}.get(cls, {})
        return [w for w, n in held.items() if n == name]


BE = {"is", "am", "are", "'s", "'m", "'re", "was", "were", "be", "been", "being"}


def test_a_meaning_is_said_only_in_sentences_the_grammar_reads_back_to_it():
    """`Grammar.say`: the grammar a sentence is read by, used the other way; a sentence said only where reading it
    gives exactly the meaning said, a kind said of a kind with one word saying `be` ("is" and "'s" both say it, the
    one said only as surely as it is read), never a question's word in a telling; nothing said of a thing no word is
    held for."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    meaning = gm.Meaning("tell", (gm.MeaningFact("isa", "dog", "mammal"),))
    said = g.say(meaning)
    assert said
    for sentence in said:
        assert read(g, sentence) == meaning.canonical(), sentence
        words = gm.tokens_of(sentence, g.lexicon.words)
        assert sum(1 for w in words if w.lower() in BE) == 1, sentence
        assert sentence.endswith(".")
    assert g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "griffin", "mammal"),))) == []


def test_a_happening_is_said_with_its_doer_and_what_it_was_done_to():
    """A sentence read, said again: the meaning it read to said by the same grammar, read back to the same meaning."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    told = g.read(gm.tokens_of("Tom chased a cat.", g.lexicon.words)).meaning
    said = g.say(told)
    assert said and all(read(g, s) == told.canonical() for s in said)
    assert "Tom chased a cat." in said


class Sounding(Speaking):
    """The words above, and an owl, with how each is said, the first sounds "a" and "an" were said before, the
    subjects each form of "be" took, and what form each noun is, as words recorded whole hold them."""

    SOUNDS = {"owl": ["AW1 L"], "bird": ["B ER1 D"], "dog": ["D AO1 G"], "dogs": ["D AO1 G Z"],
              "mammal": ["M AE1 M AH0 L"], "mammals": ["M AE1 M AH0 L Z"]}
    BEFORE = {"a": {"B": 50.0, "D": 40.0, "M": 30.0, "Y": 5.0}, "an": {"AW": 10.0, "AE": 12.0, "IH": 9.0}}
    SUBJECTS = {"is": {("NOUN", "Number=Sing"): 100.0, ("PRONOUN", "Number=Sing|Person=3"): 50.0},
                "'s": {("NOUN", "Number=Sing"): 20.0, ("PRONOUN", "Number=Sing|Person=3"): 60.0},
                "am": {("PRONOUN", "Number=Sing|Person=1"): 40.0},
                "'m": {("PRONOUN", "Number=Sing|Person=1"): 40.0},
                "are": {("NOUN", "Number=Plur"): 80.0, ("PRONOUN", "Person=2"): 30.0},
                "'re": {("PRONOUN", "Person=2"): 30.0}}

    USES = {"a": {"det": 100.0}, "an": {"det": 100.0}, "is": {"be:np": 60.0, "be:adj": 40.0},
            "'s": {"be:np": 15.0, "be:adj": 10.0}, "am": {"be:np": 10.0, "be:adj": 20.0},
            "'m": {"be:np": 10.0, "be:adj": 20.0}, "are": {"be:np": 40.0, "be:adj": 40.0},
            "'re": {"be:np": 10.0, "be:adj": 20.0}}

    def uses(self, word: str) -> Mapping[str, float]:
        w = word.lower()
        return {"NOUN": 10.0} if w == "owl" else self.USES.get(w) or super().uses(word)

    def noun_alone(self, word: str) -> Mapping[str, float]:
        # As the treebanks say nouns: one alone seldom, many alone often.
        return {"bare": 20.0, "determined": 10.0} if self.plural(word) else {"bare": 1.0, "determined": 30.0}

    def name(self, word: str, cls: str) -> str:
        return "owl" if word.lower() == "owl" else super().name(word, cls)

    def words_for(self, name: str, cls: str):
        return ["owl"] if name == "owl" and cls == "NOUN" else super().words_for(name, cls)

    def sounds(self, word: str):
        return self.SOUNDS.get(word.lower(), [])

    def said_before(self, word: str):
        return self.BEFORE if word.lower() in self.BEFORE else {}

    def subjects(self, word=None):
        if word is None:
            every: Dict = {}
            for held in self.SUBJECTS.values():
                for k, n in held.items():
                    every[k] = every.get(k, 0.0) + n
            return every
        return self.SUBJECTS.get(word.lower(), {})

    #: Each form of "be" with its number and person, as its record holds them.
    BE_FEATURES = {"is": "Number=Sing|Person=3", "'s": "Number=Sing|Person=3", "am": "Number=Sing|Person=1",
                   "'m": "Number=Sing|Person=1", "are": "Number=Plur|Person=3", "'re": "Person=2"}

    def form_features(self, word: str, cls: str):
        w = word.lower()
        if cls == "AUXILIARY" and w in self.BE_FEATURES:
            return {"Mood=Ind|" + self.BE_FEATURES[w] + "|Tense=Pres|VerbForm=Fin": 1.0}
        if cls != "NOUN" or (w not in NOUNS and w != "owl"):
            return {}
        return {"Number=Plur" if self.plural(w) else "Number=Sing": 1.0}


def test_a_or_an_is_said_as_the_word_after_it_is_said():
    """Of the forms of "a" the analysts mark nothing apart, the one said before the word after it, by its first sound
    (`Lexicon._sound_after`): "an owl", "a bird"; read, "a owl" is read less surely than "an owl"."""
    g = gm.Grammar(gm.Lexicon(Sounding()))
    said = g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "owl", "bird"),)))
    assert said and said[0].startswith("An owl "), said[:5]
    # Saying stops once it has said enough (`SAID_AT_MOST`): "an bird", less sure, is said after "a bird" or never.
    assert "An owl is an bird." not in said or said.index("An owl is a bird.") < said.index("An owl is an bird."), \
        said[:8]
    assert not any(s.startswith("A owl ") for s in said), said[:8]
    sure = {text: g.read(gm.tokens_of(text, g.lexicon.words)).sign.score
            for text in ("An owl is a bird.", "A owl is a bird.")}
    assert sure["An owl is a bird."] > sure["A owl is a bird."]


def test_a_subject_agrees_with_its_verb_as_the_subjects_it_took():
    """A subject weighed with its verb's finite form by the subjects that form took (`Grammar._agreement`): "a dog
    am" is read less surely than "a dog is", and what is said of a dog being a mammal first says it agreeing."""
    g = gm.Grammar(gm.Lexicon(Sounding()))
    sure = {text: g.read(gm.tokens_of(text, g.lexicon.words)).sign.score
            for text in ("A dog is a mammal.", "A dog am a mammal.", "Dogs are mammals.", "Dogs is mammals.")}
    assert sure["A dog is a mammal."] > sure["A dog am a mammal."]
    assert sure["Dogs are mammals."] > sure["Dogs is mammals."]
    said = g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "dog", "mammal"),)))
    first = gm.tokens_of(said[0], g.lexicon.words)
    assert ("dogs" in [w.lower() for w in first]) == any(w.lower() in ("are", "'re") for w in first), said[:5]
    assert not any(w.lower() in ("am", "'m") for w in first), said[:5]


class Agreeing(Sounding):
    """The words above, with the nouns "a" and "an" were said with, and the things said to be what a copula said they
    were, as words recorded whole hold them."""

    NOUNS_OF = {"a": {("NOUN", "Number=Sing"): 300.0, ("NOUN", "Number=Plur"): 6.0},
                "an": {("NOUN", "Number=Sing"): 40.0, ("NOUN", "Number=Plur"): 1.0},
                "the": {("NOUN", "Number=Sing"): 400.0, ("NOUN", "Number=Plur"): 100.0}}
    PREDICATED = {("NOUN", "Number=Sing"): {("NOUN", "Number=Sing"): 90.0, ("NOUN", "Number=Plur"): 5.0},
                  ("NOUN", "Number=Plur"): {("NOUN", "Number=Plur"): 30.0, ("NOUN", "Number=Sing"): 2.0}}

    def nouns(self, word=None):
        if word is None:
            every: Dict = {}
            for held in self.NOUNS_OF.values():
                for k, n in held.items():
                    every[k] = every.get(k, 0.0) + n
            return every
        return self.NOUNS_OF.get(word.lower(), {})

    def predicated(self, said=None):
        if said is None:
            every: Dict = {}
            for held in self.PREDICATED.values():
                for k, n in held.items():
                    every[k] = every.get(k, 0.0) + n
            return every
        return self.PREDICATED.get(said, {})


def test_a_determiner_agrees_with_its_noun_and_a_thing_with_what_it_is_said_to_be():
    """A determiner weighed with its noun by the nouns it was said with, and a thing with what it is said to be by the
    things said to be such (`Grammar._met`), wherever the two first stand together: "a mammals" is read less surely
    than "a mammal" though "is a" is composed before the noun; "Dogs are a mammal." less surely than "Dogs are
    mammals."; what is said first of a dog being a mammal agrees throughout."""
    g = gm.Grammar(gm.Lexicon(Agreeing()))
    sure = {text: g.read(gm.tokens_of(text, g.lexicon.words)).sign.score
            for text in ("A dog is a mammal.", "A dog is a mammals.", "Dogs are mammals.", "Dogs are a mammal.")}
    assert sure["A dog is a mammal."] > sure["A dog is a mammals."] + 1.0, sure
    assert sure["Dogs are mammals."] > sure["Dogs are a mammal."] + 1.0, sure
    said = g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "dog", "mammal"),)))
    assert said[0] in ("A dog is a mammal.", "Dogs are mammals."), said[:5]


def test_a_finite_verb_is_kept_apart_by_its_form_until_its_subject_is_taken():
    """Saying keeps "is" and "are" apart while their subject is yet to come, as the subject is weighed with the form:
    a dog being a mammal is said "A dog is a mammal." and "Dogs are mammals.", each form with the subject it agrees
    with. Packed by meaning alone, one form was kept for every subject ("The medal were painted.", 2026-10-28)."""
    g = gm.Grammar(gm.Lexicon(Agreeing()))
    said = g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "dog", "mammal"),)))
    assert "A dog is a mammal." in said and "Dogs are mammals." in said, said[:8]


def test_the_speakers_verb_is_their_word_in_any_form_and_their_noun_as_they_wrote_it():
    """The speaker's own words (`named`) are said before others: a verb as any of its forms, its subject and time
    choosing which ("chase" asked, "chased" said of a chasing before now); a noun as written, its form saying how
    many ("cat" asked, never "cats" said of one cat)."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    told = g.read(gm.tokens_of("Tom chased a cat.", g.lexicon.words)).meaning
    said = g.say(told, named={"chase": "chase", "cat": "cat"})
    assert said and "chased" in said[0].split() and "did" not in said[0].split(), said[:5]
    assert not any("cats" in s for s in said[:said.index("Tom chased a cat.") + 1]), said[:8]


def test_another_is_one_of_a_kind_not_one_given_and_is_said_only_so():
    """"Another" is one of a kind that is not the one of it given (Heim 1982; the Parallel Meaning Bank's `NEQ`):
    "Tom chased another cat." is a cat chased, a cat known, the two not one, and is said back of that meaning, first;
    of a dog being a mammal, "another" is never said. Saying nothing, it was read as "a"."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    told = g.read(gm.tokens_of("Tom chased another cat.", g.lexicon.words)).meaning
    facts = {(f.relation, f.positive, f.given) for f in told.facts}
    assert ("equals", False, False) in facts and ("instance_of", True, True) in facts, told.canonical()
    assert told.canonical() != read(g, "Tom chased a cat.")
    said = g.say(told)
    assert said and said[0] == "Tom chased another cat.", said[:5]
    assert not any("another" in s for s in g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "dog", "mammal"),))))


def test_any_is_one_of_a_kind_only_where_denied_asked_or_supposed():
    """"Any" is read as a thing of its kind where a denial, a question or an "if" takes it (Ladusaw 1979; the
    Parallel Meaning Bank's "Tom didn't break any laws."), as "a" is; told with none of these, the meaning language
    has no words for it, so it is never said for "a"."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    assert read(g, "Did Tom chase any cat?") == read(g, "Did Tom chase a cat?")
    assert g.read(gm.tokens_of("Tom did not chase any cat.", g.lexicon.words)).meaning is not None
    assert g.read(gm.tokens_of("Tom chased any cat.", g.lexicon.words)).meaning is None
    told = g.read(gm.tokens_of("Tom chased a cat.", g.lexicon.words)).meaning
    assert not any("any" in s.split() for s in g.say(told))


def test_some_is_a_thing_of_its_kind_and_never_the_kind():
    """"Some" is a thing of its kind, as "a" is (the Parallel Meaning Bank writes "I want some potatoes." as it writes
    "a potato"), and never the kind: "Some dogs bark." tells of some dogs, where "Dogs bark." tells of dogs, and what
    a thing is said to be with "some" is no kind it is of (Partee 1987). In saying, it says nothing a meaning holds,
    as "a" does."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    assert read(g, "Tom chased some dogs.") == read(g, "Tom chased a dog.")
    some_dogs = g.read(gm.tokens_of("Some dogs bark.", g.lexicon.words)).meaning
    assert any(f.relation == "instance_of" and f.obj == "dog" and gm.is_variable(f.subject) for f in some_dogs.facts)
    assert some_dogs.canonical() != read(g, "Dogs bark.")
    assert "isa(" not in read(g, "Whales are some mammals.") and "isa(" in read(g, "Whales are mammals.")
    some = next(e for _, e in g.lexicon.entries(("some", "dogs"), 0) if e.label == "det")
    assert gm._says_of(some, some_dogs) == {}


class Awarding(Speaking):
    """The words above and "medal", which names a thing whose name is two words (`award decoration`), memory's words
    for it found however the name is written (`MemoryAgent.words_for`)."""

    def uses(self, word: str) -> Mapping[str, float]:
        return {"NOUN": 10.0} if word.lower() == "medal" else super().uses(word)

    def name(self, word: str, cls: str) -> str:
        return "award decoration" if word.lower() == "medal" and cls == "NOUN" else super().name(word, cls)

    def words_for(self, name: str, cls: str):
        if cls == "NOUN" and name.replace("_", " ") == "award decoration":
            return ["medal"]
        return super().words_for(name, cls)


def test_a_name_memorys_store_writes_joined_is_said_as_reading_writes_it():
    """An answer is told of what memory's store holds, a thing's kind named as the store writes it, joined
    (`award_decoration`); a sentence said is read back to reading's name (`award decoration`). Compared as written,
    no sentence was the meaning, nothing was said, and "What did Roy fasten?" was answered "Medal." (TRAIN-FORMAT-01,
    lyric_dev2, 2026-10-28)."""
    g = gm.Grammar(gm.Lexicon(Awarding()))
    told = gm.Meaning("tell", (gm.MeaningFact("done_by", "?v0", "tom"), gm.MeaningFact("done_to", "?v0", "?k0"),
                               gm.MeaningFact("instance_of", "?k0", "award_decoration", given=True),
                               gm.MeaningFact("instance_of", "?v0", "chase"), gm.MeaningFact("precedes", "?v0", "?now")))
    said = g.say(told)
    assert said and said[0] == "Tom chased the medal.", said[:5]


def test_a_word_saying_nothing_is_said_only_where_something_needs_it():
    """Of the words saying nothing, one leaving what it takes as it was ("the" before a name, NP.x/NP.x; "then") is
    never needed to say anything, and is not said (`_leaves_as_is`, Carroll et al. 1999); one making what it takes
    another thing ("that" making a clause one that is taken, "to" a doing one that follows a verb) still may be. Read,
    "the" before a name is read as before."""
    assert gm._leaves_as_is(gm.parse_category("NP.x/NP.x")) and gm._leaves_as_is(gm.parse_category("S[F].a/S[F].a"))
    assert not gm._leaves_as_is(gm.parse_category("S[em].c/S[dcl].c"))
    assert not gm._leaves_as_is(gm.parse_category("(S[to].e\\NP.x)/(S[b].e\\NP.x)"))
    g = gm.Grammar(gm.Lexicon(Speaking()))
    told = g.read(gm.tokens_of("Tom chased a cat.", g.lexicon.words)).meaning
    said = g.say(told)
    assert "Tom chased a cat." in said
    assert not any(" the " in f" {s.lower()} " for s in said), [s for s in said if "the" in s.lower()][:3]
    assert read(g, "The Tom chased a cat.") == told.canonical()


def test_a_doing_of_five_facts_is_said_kay_binding():
    """KAY BINDING: each word put in bound to the meaning's terms ("in" to the chasing and the park), what can never be
    completed dropped, a word taking what no word can make not offered: "Tom chased a cat in the park." is said, every
    sentence reading back to it (unbound, it was never said: 131,665 items after 90 s)."""
    g = gm.Grammar(gm.Lexicon(Speaking()))
    told = g.read(gm.tokens_of("Tom chased a cat in the park.", g.lexicon.words)).meaning
    said = g.say(told)
    assert "Tom chased a cat in the park." in said, said[:6]
    assert all(read(g, s) == told.canonical() for s in said)


def test_a_verbs_place_is_what_its_frame_says_by_the_places_said_with_it():
    """A verb's places linked as the frames of the sense read say, by the places said with it (`Lexicon.framed`,
    VerbNet's frames, as the PMB's roles are): falling is done to the one falling ("NP:Patient V"); "in" after
    "chase" where to, as the frame said with a thing chased and "in" says; a verb no frame is held of by the
    grammar's own links; and what a sentence taught said of the verb's place stands over its frames."""
    g = gm.Grammar(gm.Lexicon(Held()))
    lexicon = g.lexicon
    assert read(g, "The dog fell.") == (
        "tell: done_by(?v0, ?v1) & given instance_of(?v1, dog) & instance_of(?v0, fall) & precedes(?v0, ?now)")
    lexicon.sense_used["fall"]["fall"] = 3
    lexicon.frames_said["fall"]["fall"][(("subject", "done_to"),)] = 1
    assert read(g, "The dog fell.") == (
        "tell: done_to(?v0, ?v1) & given instance_of(?v1, dog) & instance_of(?v0, fall) & precedes(?v0, ?now)")
    lexicon.sense_used["chase"]["chase"] = 3
    lexicon.frames_said["chase"]["chase"][(("object", "done_to"), ("pp:in", "moves_to"), ("subject", "done_by"))] = 1
    lexicon.frames_said["chase"]["chase"][(("object", "done_to"), ("subject", "done_by"))] = 1
    assert read(g, "The dog chased the cat in the park.") == (
        "tell: done_by(?v0, ?v1) & done_to(?v0, ?v2) & given instance_of(?v1, dog) & given instance_of(?v2, cat) & "
        "given instance_of(?v3, park) & instance_of(?v0, chase) & moves_to(?v0, ?v3) & precedes(?v0, ?now)")
    assert "word_in(?v0, ?v2)" in read(g, "The dog barked in the park.")
    lexicon.learned["role"][("fall", "subject")]["done_by"] += 1
    assert lexicon.taught_role("fall", "subject") and not lexicon.taught_role("chase", "subject")
    assert read(g, "The dog fell.").startswith("tell: done_by(?v0, ?v1)")


def test_words_memory_knows_as_one_word_are_read_as_the_kind_it_knows_them_as(grammar):
    """Several words memory holds as one word are read as one, of whatever kind it holds them as: a thing ("credit
    card"), a quality ("fed up", `fed_up.a.01`, named `disgusted`), an adverb ("at last", `at_last.r.01`). Of the
    PMB's gold train documents, 1,166 concepts are one word of several that is not a name — 747 things, 238 verbs,
    105 adverbs, 76 qualities — and WordNet spells every one of them as one word, so memory taught from it holds them
    all (`GRAMMAR-01/diagnostics/several_words.py`); lab notebook (79). The quality and the adverb were read as
    their words apart until then, the rule offering a thing alone."""
    assert read(grammar, "The dog is fed up.") == (
        "tell: given instance_of(?v0, dog) & has_property(?v0, disgusted)")
    assert read(grammar, "The dog barked at last.") == (
        "tell: done_by(?v0, ?v1) & given instance_of(?v1, dog) & has_property(?v0, finally) & "
        "instance_of(?v0, bark) & precedes(?v0, ?now)")
    assert read(grammar, "The dog chased a credit card.") == (
        "tell: done_by(?v0, ?v1) & done_to(?v0, ?v2) & given instance_of(?v1, dog) & instance_of(?v0, chase) & "
        "instance_of(?v2, credit card) & precedes(?v0, ?now)")


def test_saying_keeps_how_surely_each_sentence_it_says_reads_back():
    """`Grammar.say`'s `how_surely`: a sentence is kept where it reads back to exactly the meaning, which asks whether
    and never how surely, so the number reading already made at the deciding place was thrown away. Each sentence said
    now carries the share of its whole readings which is the meaning asked for (`Reading.sure`), the sentence said
    first at the head, and a sentence nothing else can be read from stands above one of several readings."""
    g = gm.Grammar(gm.Lexicon(Sounding()))
    told = gm.Meaning("tell", (gm.MeaningFact("isa", "owl", "bird"),))
    how_surely: dict = {}
    said = g.say(told, how_surely=how_surely)
    assert said, "nothing said, so there is nothing to be sure of"
    # Every sentence said is reported, in the order they are said, and no other.
    assert list(how_surely) == said, (list(how_surely)[:4], said[:4])
    # A share of the whole readings is a share: never outside it, and never nothing where a sentence was said.
    assert all(0.0 < sure <= 1.0 for sure in how_surely.values()), how_surely
    # It is the reading's own number, not one made here: reading the sentence back says the same.
    for text in said[:3]:
        assert abs(g.read(gm.tokens_of(text, g.lexicon.words)).sure - how_surely[text]) < 1e-9, text
    # Asked for nothing, nothing is filled, and saying is unchanged.
    assert g.say(told) == said


def test_how_surely_is_not_filled_where_nothing_is_said():
    """Nothing said is not something said unsurely: `how_surely` is emptied, and `why` says why instead."""
    g = gm.Grammar(gm.Lexicon(Sounding()))
    how_surely: dict = {"left": 0.5}
    why: dict = {}
    assert g.say(gm.Meaning("tell", (gm.MeaningFact("isa", "griffin", "mammal"),)),
                 why=why, how_surely=how_surely) == []
    assert how_surely == {}, how_surely
    assert why.get("why"), why


def test_reading_says_which_words_memory_does_not_hold():
    """`Reading.unheld` and `words_not_held`: reading is permissive on purpose -- a word nobody taught is read by
    reading the sentence around it -- but it was silent, so a sentence of words never seen looked exactly like one of
    words taught. "This sparkles." read whole at 0.915 sure with `sparkles` a concept minted from its own letters
    (lyric_db, 2026-10-30). `sure` is the reading's share of every whole reading, which is sureness about STRUCTURE;
    nothing said how much of the sentence memory holds, and now the reading itself does."""
    g = gm.Grammar(gm.Lexicon(Sounding()))
    words = g.lexicon.words

    def unheld(text: str) -> tuple:
        return g.read(gm.tokens_of(text, words)).unheld

    # A WORD NEVER TAUGHT IS NAMED, and the grammar's own closed-class words beside it are not: they are held.
    assert "sparkles" in unheld("This sparkles.")
    assert "this" not in unheld("This sparkles."), "a determiner the grammar states is held"
    # Each word once, in the order first met, so the first thing unheld is the first thing unheld.
    said = unheld("Zib zib zarquon.")
    assert said == tuple(dict.fromkeys(said)), said
    assert said.index("zib") < said.index("zarquon"), said
    # Nothing that is not spelled in letters is a word to hold: punctuation and figures are never named.
    for token in unheld("Zarquon 42, zarquon!"):
        assert token.isalpha(), token
    # READING IS UNCHANGED: naming what it does not hold neither refuses the sentence nor alters its meaning.
    with_unknown = g.read(gm.tokens_of("This sparkles.", words))
    assert with_unknown.unheld, "the control of this test is that the word is indeed unheld"
    assert with_unknown.sign is not None, "a word never taught is still read by reading the sentence"
    # ONE AUTHORITY: what the reading reports is what the function says of the very same words.
    tokens = gm.tokens_of("This sparkles.", words)
    assert gm.words_not_held(tokens, g.lexicon) == with_unknown.unheld


def test_a_sentence_that_reads_no_whole_says_the_word_nothing_holds():
    """Why a sentence did not read is worth the word it turned on: a reading that reads no whole now says which of
    its words memory does not hold, where before the two causes -- a grammar that cannot join them and a word nobody
    taught -- arrived as one sentence of English with nothing to tell them apart."""
    g = gm.Grammar(gm.Lexicon(Sounding()))
    words = g.lexicon.words
    reading = g.read(gm.tokens_of("Zarquon blerf zib quux glorp wibble frob.", words))
    if reading.sign is None:
        assert "no word held for" in reading.why, reading.why
        assert reading.unheld, "nothing was named as unheld, so the why would be empty of them"
        for word in reading.unheld[:3]:
            assert word in reading.why, (word, reading.why)
    else:
        # Read whole after all, which is reading being permissive; the words are still named.
        assert reading.unheld, reading.unheld


def test_a_form_saying_nothing_of_a_feature_is_no_evidence_of_having_none():
    """`Grammar._features`: a word's forms are weighed against each other to decide what form it is where it stands
    (`standing_as` takes the case it is written with most, `taking_subject` the person and number), and a form held
    with no features at all was weighed in beside the ones that state them.

    Every pronoun is held twice on a taught store: once as stated (`CLOSED_PARADIGM`: "I" is
    `Case=Nom|Number=Sing|Person=1`) and once under the base a sentence recorded whole gives it, the PMB lemmatising
    "I" as `speaker` and "they" as `person`, with no features whatever -- one each. The tie settled on no case at
    all, so every pronoun was packed with every other and only the most often written survived: "I is intelligent.",
    "Him is intelligent.", "Ourselves is intelligent.", while "You are intelligent." came out right because "you" is
    the one pronoun with no case to get wrong (lyric_db, 2026-10-30)."""

    class TwoWays(Held):
        """A word held both with its features and without them, as a stated form and a record's base leave it."""

        def __init__(self, held: Mapping[str, Mapping[str, float]]):
            self._held = held

        def subjects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
            # Something, so that the features subjects agree by are known and `_features` does not short out.
            return {("PRONOUN", "Case=Nom|Number=Sing|Person=1"): 9.0, ("NOUN", "Number=Sing"): 9.0}

        def form_features(self, word: str, cls: str) -> Mapping[str, float]:
            return self._held.get(word.lower(), {})

    def features_of(held, token, cls="PRONOUN"):
        g = gm.Grammar(gm.Lexicon(TwoWays(held)))
        g._tokens = (token,)
        g._agreeing = {}
        return dict(g._features(cls, 0))

    both = {"me": {"Case=Acc|Number=Sing|Person=1": 1.0, "": 1.0}}
    # THE FEATURELESS FORM IS DROPPED where another form of the word as this class states features.
    assert features_of(both, "me") == {"Case=Acc|Number=Sing|Person=1": 1.0}

    # AND KEPT where nothing states any: a word of which memory holds only a featureless form is unchanged, so this
    # neither invents a feature nor silences a word whose forms were never analysed.
    only_bare = {"me": {"": 3.0}}
    assert features_of(only_bare, "me") == {"": 3.0}

    # Held of no form at all, nothing is reported, which is what `_agreed` reads as no form of the word.
    assert features_of({}, "me") == {}

    # Features outside the ones subjects agree by are dropped as before, and a form left with nothing by THAT is
    # still dropped beside a form that keeps something: `PronType` is no part of agreeing.
    paradigm = {"i": {"Case=Nom|Number=Sing|Person=1|PronType=Prs": 1.0, "PronType=Prs": 1.0}}
    assert features_of(paradigm, "i") == {"Case=Nom|Number=Sing|Person=1": 1.0}


def test_a_subject_form_no_verb_ever_took_is_evidence_against_not_no_evidence():
    """`Grammar._agreed`: how well a word agrees with the verb it stands before is its share of that verb's subjects
    against its share of all of them. A form no subject anywhere was ever written with had a share of nothing, which
    was passed over -- and a word none of whose forms was ever a subject came back the same nothing as a word with no
    verb to weigh it against at all.

    So every accusative pronoun agreed with every verb as well as it is possible to agree: of the 11,295 subjects
    main holds, three are accusative, and "him", "them", "us", "itself" and "whom" are in none of them. "Him is
    intelligent." was said of a man being intelligent, ranked above "He is intelligent." (lyric_db, 2026-10-30)."""

    class Subjects(Held):
        """Subjects as memory holds them: nominative pronouns and nouns, and never an accusative one."""

        def subjects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
            every = {("PRONOUN", "Case=Nom|Number=Sing|Person=3"): 1800.0,
                     ("PRONOUN", "Case=Nom|Number=Plur|Person=3"): 500.0,
                     ("NOUN", "Number=Sing"): 2900.0}
            if word is None:
                return every
            # As a store holds a copula: mostly subjects of its own number, a few of the other (a plural subject
            # written with a singular verb is in the treebanks), and never an accusative one.
            return {("PRONOUN", "Case=Nom|Number=Sing|Person=3"): 230.0,
                    ("PRONOUN", "Case=Nom|Number=Plur|Person=3"): 5.0,
                    ("NOUN", "Number=Sing"): 300.0} if word == "is" else {}

        def form_features(self, word: str, cls: str) -> Mapping[str, float]:
            return {"he": {"Case=Nom|Number=Sing|Person=3": 1.0},
                    "him": {"Case=Acc|Number=Sing|Person=3": 1.0},
                    "they": {"Case=Nom|Number=Plur|Person=3": 1.0}}.get(word.lower(), {})

    def agreed(subject, verb="is"):
        g = gm.Grammar(gm.Lexicon(Subjects()))
        g._tokens, g._agreeing = (subject,), {}
        words = g.lexicon.words
        return g._agreed(words.subjects(verb), words.subjects(), "PRONOUN", 0)

    # THE SUBJECT THE VERB TOOK agrees best, and the one of another number less well: both are weighed.
    assert agreed("he") > agreed("they"), "a verb's own subjects must tell its number apart"
    # THE ONE NO SUBJECT EVER WAS is weighed against, not passed over: it is the worst of the three, by a wide
    # margin, where before it was 0.0 -- the best score there is, and the very number a word with no verb to weigh
    # it against comes back with.
    assert agreed("him") < agreed("they") - 1.0, (agreed("him"), agreed("they"))
    assert agreed("him") < -1.0, "an accusative subject still scores as well as it is possible to score"
    # AGREEING IS STILL NEVER BETTER THAN NOTHING, so a reading is never rewarded for having a subject at all.
    assert agreed("he") <= 0.0


def test_a_verb_no_subject_was_held_of_is_weighed_by_the_verbs_written_as_it_is():
    """`Grammar._subjects_like`: agreement is weighed from the subjects the very word took, and main holds a subject
    of 19 finite forms. For every other verb there was nothing to weigh, so each subject's share of this verb's
    subjects came out as its share of all subjects and agreed perfectly, whatever it was -- no evidence scored as
    agreeing, once more.

    Of a person reeking, "The people stinks." was said above "The person stinks." ("stinks" taking no subject memory
    holds, though memory holds it as a third person singular). What a form says of its subject is held of the form,
    so the verbs written as it is are what is left to weigh it by (lyric_db, 2026-10-30)."""

    class Few(Held):
        """One finite form with subjects, and another written as it is with none of its own."""

        def subjects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
            every = {("NOUN", "Number=Sing"): 2900.0, ("NOUN", "Number=Plur"): 1300.0}
            if word is None:
                return every
            return {("NOUN", "Number=Sing"): 400.0} if word == "barks" else {}

        def took_subjects(self) -> Tuple[str, ...]:
            return ("barks",)

        def form_features(self, word: str, cls: str) -> Mapping[str, float]:
            if cls == "NOUN":
                return {"person": {"Number=Sing": 9.0}, "people": {"Number=Plur": 9.0}}.get(word.lower(), {})
            return {"barks": {"Mood=Ind|Number=Sing|Person=3|VerbForm=Fin": 5.0},
                    "stinks": {"Mood=Ind|Number=Sing|Person=3|VerbForm=Fin": 1.0},
                    "stink": {"VerbForm=Inf": 1.0}}.get(word.lower(), {})

    def agreed(subject, verb):
        g = gm.Grammar(gm.Lexicon(Few()))
        g._tokens, g._agreeing = (subject,), {}
        words = g.lexicon.words
        return g._agreed(words.subjects(verb) or g._subjects_like(verb), words.subjects(), "NOUN", 0)

    # WRITTEN AS A VERB WITH SUBJECTS, a verb with none of its own is weighed by what those took.
    assert gm.Grammar(gm.Lexicon(Few()))._agrees_as("stinks") == \
        gm.Grammar(gm.Lexicon(Few()))._agrees_as("barks"), "the two are written as the same form"
    assert agreed("person", "stinks") > agreed("people", "stinks") + 1.0, \
        (agreed("person", "stinks"), agreed("people", "stinks"))
    # And it is weighed as the verb it is written as is, neither better nor worse.
    assert agreed("person", "stinks") == pytest.approx(agreed("person", "barks"))

    # A FORM WRITTEN AS NOTHING ELSE IS is weighed by nothing, rather than by whatever else has no subjects: an
    # infinitive takes no subject, so nothing of the finite forms' subjects is borrowed for it.
    g = gm.Grammar(gm.Lexicon(Few()))
    g._tokens, g._agreeing = ("person",), {}
    assert g._subjects_like("stink") == {}


def test_the_one_grammar_word_a_thing_is_said_by_is_found_whatever_the_thing_is():
    """`Grammar._said_by`: the word saying a thing is what agreement weighs and what keeps a thing apart by its case
    (`standing_as`). It found a grammar word only where the thing was the speaker or the listener, so a pronoun
    standing for a group the speaker is one of -- "we", "us", "ourselves", which say a thing of their own that the
    speaker is a member of, not a term of the situation -- was never found at all.

    None of the three was ever weighed against a verb or kept apart from the others by its case, so they packed
    together and the surest alone was said: of the speaker and another being intelligent, "Ourselves is intelligent."
    was all there was, and it was the one reading, said at 1.000 (lyric_db, 2026-10-30)."""
    g = gm.Grammar(gm.Lexicon(Held()))
    g._tokens = ("we", "are", "happy")

    def said_by(pieces, ref):
        return g._said_by(pieces, ref)

    # A GROUP THE SPEAKER IS ONE OF: the one grammar word it is said by is found, though the thing is a variable.
    group = [("word", "we", "GRAMMAR", 0, 1), ("fact", "has_member", 7, "?speaker", "-")]
    assert said_by(group, 7) == ("PRONOUN", 0)
    # THE SPEAKER ITSELF, as before: nothing that was found is lost.
    assert said_by([("word", "i", "GRAMMAR", 0, 1)], "?speaker") == ("PRONOUN", 0)
    assert said_by([("word", "you", "GRAMMAR", 0, 1)], "?listener") == ("PRONOUN", 0)
    # A THING SAID BY MORE THAN ONE WORD is not taken for one of them: "the" is no word the group is said by.
    assert said_by([("word", "the", "GRAMMAR", 0, 1), ("word", "dogs", "NOUN", 1, 2)], 7) is None
    # NOR A STRETCH OF SEVERAL WORDS where the thing is a term of the situation and neither is the one saying it.
    assert said_by([("word", "we", "GRAMMAR", 0, 1), ("word", "are", "GRAMMAR", 1, 2)], "?speaker") is None
    # A NOUN IS STILL THE NOUN, not the determiner before it.
    assert said_by([("word", "the", "GRAMMAR", 0, 1), ("word", "dog", "NOUN", 1, 2), ("kind", 7, 1)], 7) == ("NOUN", 1)
