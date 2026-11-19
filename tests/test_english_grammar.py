#!/usr/bin/env python3
"""ENGLISH'S GRAMMAR AS LYRIC IS TAUGHT IT, not as a file it reads.

`data/grammar/english.json` is read straight off disk by `grammar.Lexicon`, which makes it a second authority
beside memory: a wipe could not clear it, teaching could not grow it, and no evidence could argue with it -- the
very thing said of the closed classes when they stopped being frozensets in code. These tests hold the move:

    ROWS       every way of reading and every pair the grammar states is a record (`GrammarRule`), and the
               records rebuild the lesson EXACTLY, table for table and row for row
    READING    a grammar built from the rows reads what a grammar built from the file reads, meaning for
               meaning and sign for sign

Pure: no database, no memory. The lesson is read from the tree, which is where it stays -- it is the teaching
source, read into a fresh store as `data/lessons/english_*.json` are, so a wipe clears what memory holds and
teaching reads the lesson again.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.learning.teaching_sources import EnglishGrammarSource, GrammarPair, GrammarRule, grammar_from
from core.semantics import grammar as gm

#: What the helpers below build, held by name so replacing `gm.Lexicon(` with `english_lexicon(` through
#: this file could not rewrite their own bodies into calls on themselves.
GRAMMAR_CLASSES = {"Lexicon": gm.Lexicon, "GrammarView": gm.GrammarView, "closed_uses": gm.closed_uses}


def english_lexicon(words, grammar=None):
    """The words with English's grammar. THE LESSON IS READ IN ONE PLACE
    (`teaching_sources.english_grammar`), the teaching source that teaches it into memory; `grammar.Lexicon`
    requires a grammar and reads nothing, so a store that was never taught English reads nothing and says so
    instead of falling back to the file."""
    from core.learning.teaching_sources import english_grammar
    return GRAMMAR_CLASSES["Lexicon"](words, english_grammar() if grammar is None else grammar)


def grammar_view(words, grammar=None, **rest):
    """`grammar.GrammarView` with English's grammar, read as `lexicon` reads it."""
    from core.learning.teaching_sources import english_grammar
    return GRAMMAR_CLASSES["GrammarView"](words, english_grammar() if grammar is None else grammar, **rest)


def closed_uses():
    """Each grammar word's uses, from the lesson the teaching source reads."""
    from core.learning.teaching_sources import english_grammar
    return GRAMMAR_CLASSES["closed_uses"](english_grammar())




def _rows():
    source = EnglishGrammarSource()
    return list(source.grammar_rules()), list(source.grammar_pairs())


def test_the_grammar_rebuilds_from_its_rows_exactly():
    """WHAT MEMORY HOLDS HAS TO GO BACK TO THE READER UNCHANGED, or a store reads with a grammar that is not the
    one it was taught. Every table the reader takes from the mapping (`Lexicon.__init__`: the words, the kinds of
    word, a verb's frames, what each place links, the name particles, the numbers and their scales, the phrases of
    several words and the runs read as one) is rebuilt from the records and compared with the lesson itself.

    `about` is prose for whoever reads the file and no part of the grammar; nothing reads it."""
    rules, pairs = _rows()
    assert rules and pairs
    lesson = json.loads(gm.ENGLISH.read_text(encoding="utf-8"))
    lesson.pop("about", None)
    rebuilt = grammar_from(rules, pairs)
    assert set(rebuilt) == set(lesson), f"tables differ: {sorted(set(rebuilt) ^ set(lesson))}"
    for table in sorted(lesson):
        assert rebuilt[table] == lesson[table], f"{table} does not rebuild"
    # A record says itself, and keeps its identity: one way of reading one thing.
    ways = {r.identity() for r in rules}
    assert len(ways) == len(rules), "two records of one way of reading one thing"
    assert all(r.key() and r.said() for r in rules)
    assert GrammarRule.from_dict(rules[0].to_dict()) == rules[0]
    assert GrammarPair.from_dict(pairs[0].to_dict()) == pairs[0]


def test_a_grammar_built_from_the_rows_reads_what_the_file_reads():
    """THE MOVE IS SOUND ONLY IF NOTHING MOVES. The same sentences are read by a grammar given the file and by one
    given the rows, and both the meaning taken and the whole chart are compared: a reading lost or gained is a
    capability lost or gained and may not pass unnoticed.

    The words are the base `Words`, which holds no counts, so what is compared is the grammar's own tables and
    nothing a store happens to know."""
    rules, pairs = _rows()
    from_file = gm.Grammar(english_lexicon(gm.Words()))
    from_rows = gm.Grammar(english_lexicon(gm.Words(), grammar_from(rules, pairs)))
    said = ["The dog chased a cat.", "A dog is a mammal.", "Every dog is a mammal.", "Must you help me?",
            "Could you help me?", "What did the dog chase?", "The dog did not bark.", "No dog barked.",
            "The dog chased a cat and a bird.", "The cat chased the dog that barked.", "Chase the cat, Tom.",
            "The dog's bone is red.", "The dog has barked.", "Is a whale a mammal?",
            "The dog chased the cat in the park.", "Where did the dog go?", "There is a dog in the park.",
            "No one barked.", "How many dogs barked?", "The dog chased all."]
    for text in said:
        read = []
        signs = []
        for g in (from_file, from_rows):
            tokens = gm.tokens_of(text, g.lexicon.words)
            got = g.read(tokens)
            read.append(got.meaning.canonical() if got is not None and got.meaning is not None else None)
            signs.append(sum(len(held) for cell in g.charts(tokens).values() for held in cell.values()))
        assert read[0] == read[1], f"{text!r} reads {read[1]!r} from the rows and {read[0]!r} from the file"
        assert signs[0] == signs[1], f"{text!r}: {signs[0]} signs from the file, {signs[1]} from the rows"


def test_every_way_the_grammar_states_is_a_record_of_one_of_its_tables():
    """A table nobody carries is a table lost in the move, so each is named here and each has rows."""
    rules, pairs = _rows()
    assert {r.table for r in rules} == {"words", "classes", "verbs", "together"}
    assert {p.table for p in pairs} == {"linking", "phrases", "numbers", "number_scales", "wordnet_frames",
                                        "name_particles", "verbs.frames"}
    assert len({p.identity() for p in pairs}) == len(pairs), "two records of one pair"
    assert all(p.key() and p.said() and p.claim() for p in pairs)
    # "must" is the sentinel of this work: it held one of a modal's three ways and read no question at all.
    must = sorted(r.use for r in rules if r.of == "must")
    assert must == ["modal", "modal:q"], must


def test_memory_knows_which_kind_of_thing_each_grammar_memory_holds():
    """A MEMORY KEPT WHOLE IS READ BACK BY THE FIELD IT WAS KEPT UNDER (`MemoryAgent._whole_item`), and a field
    the dispatcher does not know falls through to a taught sentence. Both kinds were missing from it, and the
    teaching run against lyric_dev died on `KeyError: 'sentence'` -- but only on the CORRECTION path, where a rule
    already held is taught again and memory asks what it said before. A first run looked clean and the second
    broke, which is the shape of defect that reaches a store before anybody sees it (2026-11-18)."""
    from core.agents.memory_agent import MemoryAgent
    rules, pairs = _rows()
    assert MemoryAgent._whole_item("grammar_rule", rules[0].to_dict()) == rules[0]
    assert MemoryAgent._whole_item("grammar_pair", pairs[0].to_dict()) == pairs[0]
    # And each is kept under the tag that reads it back.
    assert MemoryAgent.GRAMMAR_RULE_TAG == "grammar_rule" and MemoryAgent.GRAMMAR_PAIR_TAG == "grammar_pair"


def test_there_is_no_grammar_to_fall_back_on():
    """ENGLISH'S GRAMMAR COMES FROM MEMORY AND FROM NOWHERE ELSE. `Lexicon`, `GrammarView` and `closed_uses` each
    read `data/grammar/english.json` whenever they were handed no grammar, so a store that held NOTHING read
    anyway and nothing anywhere said so: the one model could be empty while reading went on exactly as though it
    were full. That is what happened -- 497 ways of reading were taught into a sandbox, the model stayed empty, and
    every measurement still said reading worked.

    Each of them requires a grammar now and a caller with none fails saying why, so an empty model cannot look
    like a full one. The lesson is read in ONE place, the teaching source that teaches it in
    (`teaching_sources.english_grammar`); `scripts/teach.py --source english-grammar` is the name to teach it by,
    which it did not have when it was first taught."""
    import pytest
    from core.learning.teaching_sources import english_grammar
    for nothing in ({}, {"classes": {}}, {"words": {}}):
        with pytest.raises(ValueError, match="taught into memory"):
            gm.Lexicon(gm.Words(), nothing)
    with pytest.raises(ValueError, match="taught into memory"):
        gm.closed_uses({})
    with pytest.raises(TypeError):
        gm.Lexicon(gm.Words())             # the grammar is not an optional argument any more
    with pytest.raises(TypeError):
        gm.closed_uses()
    # And nothing in the reader opens the lesson: only the teaching source does.
    from pathlib import Path
    reader = Path("core/semantics/grammar.py").read_text(encoding="utf-8")
    assert "ENGLISH.read_text" not in reader, "the reader reads the lesson off disk again"
    assert english_grammar() is english_grammar(), "the lesson is read once"


def test_the_rules_a_sentence_is_kept_under_are_of_the_grammar_in_hand():
    """What a sentence taught was learned under has to say which grammar read it. `RULES` was a module constant
    hashed at import from the lesson's bytes, which could only be right while the file WAS the grammar: once the
    grammar is what memory holds, a grammar changed in memory looked identical across starts and every remembered
    reading would have been served as current. A key that misses what decides the answer keeps the wrong answer.

    So the key is asked of the grammar in hand (`rules_of`), and two different grammars are never kept under one
    key."""
    from core.learning.teaching_sources import english_grammar
    import copy
    lesson = english_grammar()
    assert gm.rules_of(lesson) == gm.rules_of(copy.deepcopy(lesson)), "the same grammar, the same key"
    changed = copy.deepcopy(lesson)
    changed["words"]["must"] = [row for row in changed["words"]["must"] if row.get("use") != "modal:q"]
    assert gm.rules_of(changed) != gm.rules_of(lesson), (
        "a grammar missing a way of reading is kept under the same key as one that holds it")
    assert not hasattr(gm, "RULES"), "the module constant is back"
