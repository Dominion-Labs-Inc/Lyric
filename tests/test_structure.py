"""How the words of a sentence go together (`core/semantics/structure.py`): sentences analysed by hand, kept whole,
and read as memory-based learning reads them. No store: the sentences are given here."""
import pytest

from collections import Counter

from core.semantics.structure import Analysed, StructureView, words_of


def _analysed(text, classes, heads, relations, said_in=""):
    return Analysed(tuple(text.split()), tuple(classes), tuple(heads), tuple(relations), said_in)


#: "Plants take in carbon dioxide and water ." and two more like it, analysed as the English Web Treebank analyses.
PLANTS = _analysed("Plants take in carbon dioxide and water .",
                   ["NOUN", "VERB", "ADVERB", "NOUN", "NOUN", "CONJUNCTION", "NOUN", "PUNCTUATION"],
                   [2, 0, 2, 5, 2, 7, 5, 2],
                   ["nsubj", "root", "compound:prt", "compound", "obj", "cc", "conj", "punct"], "t:1")
DOGS = _analysed("Dogs eat meat and bones .",
                 ["NOUN", "VERB", "NOUN", "CONJUNCTION", "NOUN", "PUNCTUATION"],
                 [2, 0, 2, 5, 3, 2], ["nsubj", "root", "obj", "cc", "conj", "punct"], "t:2")
CATS = _analysed("Cats drink milk .", ["NOUN", "VERB", "NOUN", "PUNCTUATION"], [2, 0, 2, 2],
                 ["nsubj", "root", "obj", "punct"], "t:3")


def test_an_analysis_gives_every_word_one_head_and_the_sentence_one_root():
    with pytest.raises(ValueError):
        _analysed("Dogs bark", ["NOUN", "VERB"], [2, 0], ["nsubj"])
    with pytest.raises(ValueError):
        _analysed("Dogs bark", ["NOUN", "VERB"], [0, 0], ["root", "root"])
    with pytest.raises(ValueError):
        _analysed("Dogs bark", ["NOUN", "VERB"], [1, 0], ["nsubj", "root"])


def test_the_same_sentence_met_twice_is_two_uses_and_told_again_is_one():
    again = _analysed("Cats drink milk .", ["NOUN", "VERB", "NOUN", "PUNCTUATION"], [2, 0, 2, 2],
                      ["nsubj", "root", "obj", "punct"], "t:3")
    elsewhere = _analysed("Cats drink milk .", ["NOUN", "VERB", "NOUN", "PUNCTUATION"], [2, 0, 2, 2],
                          ["nsubj", "root", "obj", "punct"], "t:9")
    view = StructureView()
    assert view.add(CATS) and not view.add(again) and view.add(elsewhere)
    assert len(view) == 2
    assert Analysed.from_dict(CATS.to_dict()) == CATS
    assert CATS.claim().startswith('the structure of "Cats drink milk ."')


def test_a_sentence_held_reads_as_it_was_analysed():
    view = StructureView()
    for analysed in (PLANTS, DOGS, CATS):
        view.add(analysed)
    read = view.read(PLANTS.words)
    assert read.classes == PLANTS.classes
    assert read.heads == PLANTS.heads
    assert read.relations == PLANTS.relations


def test_a_phrase_is_a_word_with_all_that_depends_on_it():
    """"carbon dioxide and water" stands where one thing stands, whatever its length: the object of "take"."""
    view = StructureView()
    for analysed in (PLANTS, DOGS, CATS):
        view.add(analysed)
    read = view.read(PLANTS.words)
    assert ("obj", "dioxide", "carbon dioxide and water") in read.phrases()
    assert ("nsubj", "Plants", "Plants") in read.phrases()


def test_a_sentence_never_held_is_read_by_the_situations_it_shares():
    view = StructureView()
    for analysed in (PLANTS, DOGS, CATS):
        view.add(analysed)
    read = view.read(("Birds", "eat", "seeds", "and", "insects", "."))
    assert read.classes == ("NOUN", "VERB", "NOUN", "CONJUNCTION", "NOUN", "PUNCTUATION")
    assert read.heads == (2, 0, 2, 5, 3, 2)


def test_a_tie_is_decided_by_the_next_situation_never_by_the_names_of_the_classes():
    """"stale", never met, after "A": a word ending in "ale" there was once an adjective ("pale") and once a noun
    ("gale"); one ending in "le", an adjective twice ("pale", "little") and a noun once. The adjective, where the order
    of the classes' names gave the tie to the noun: weighed, as a class is read (`_chances`), and decided, as an
    argument's part is (`_decide`). (Read before "bun .", the whole sentence is weighed, and of these three it reads
    as "A gale blew .".)"""
    from collections import Counter
    view = StructureView()
    view.add(_analysed("A pale moon rose .", ["DETERMINER", "ADJECTIVE", "NOUN", "VERB", "PUNCTUATION"],
                       [3, 3, 4, 0, 4], ["det", "amod", "nsubj", "root", "punct"], "t:1"))
    view.add(_analysed("A gale blew .", ["DETERMINER", "NOUN", "VERB", "PUNCTUATION"], [2, 3, 0, 3],
                       ["det", "nsubj", "root", "punct"], "t:2"))
    view.add(_analysed("A little dog barked .", ["DETERMINER", "ADJECTIVE", "NOUN", "VERB", "PUNCTUATION"],
                       [3, 3, 4, 0, 4], ["det", "amod", "nsubj", "root", "punct"], "t:3"))
    assert view.classes(("A", "stale")) == ("DETERMINER", "ADJECTIVE")
    tie = [(("ale",), Counter({"NOUN": 1, "ADJECTIVE": 1})), (("le",), Counter({"ADJECTIVE": 2, "NOUN": 1}))]
    assert StructureView._decide(tie) == ("ADJECTIVE", ("le",))


def test_a_word_no_sentence_held_used_takes_a_class_memory_holds_of_it():
    """"breathes", in no sentence held: after a noun, a word ending in "es" was a noun ("bus lanes"), so by its ending
    alone it is one. Memory holds it a verb, and a class memory holds is the one taken; asked nothing, the ending
    decides as before."""
    view = StructureView()
    view.add(_analysed("The bus lanes opened .", ["DETERMINER", "NOUN", "NOUN", "VERB", "PUNCTUATION"],
                       [3, 3, 4, 0, 4], ["det", "compound", "nsubj", "root", "punct"], "t:1"))
    words = ("The", "whale", "breathes", "air", ".")
    assert view.classes(words)[2] == "NOUN"
    held = {"whale": {"NOUN": 3}, "breathes": {"VERB": 2}}
    view.held_classes = lambda word: held.get(word.lower(), {})
    assert view.classes(words)[1:3] == ("NOUN", "VERB")


def test_what_memory_holds_of_a_word_weighs_over_how_words_written_like_it_were_used():
    """A word no sentence held, that memory holds a noun 25 times, a name once and a verb 3 times, is a noun though
    the one sentence held began with a name ("Roy"): what memory holds of the word is the word's own, as a tagger's
    lexicon gives a word it lists its own tags (Brants 2000). Taken only to bound the classes, a capital first was a
    name, as "Roy" was ("Picture is a representation.", lyric_dev2, 2026-10-28)."""
    view = StructureView()
    view.add(_analysed("Roy fastened the medal .", ["NAME", "VERB", "DETERMINER", "NOUN", "PUNCTUATION"],
                       [2, 0, 4, 2, 2], ["nsubj", "root", "det", "obj", "punct"], "t:1"))
    words = ("Picture", "is", "a", "representation", ".")
    held = {"picture": {"NOUN": 25, "NAME": 1, "VERB": 3}}
    view.held_classes = lambda word: held.get(word.lower(), {})
    assert view.classes(words)[0] == "NOUN"
    held["picture"] = {"NAME": 25, "NOUN": 1}
    assert view.classes(words)[0] == "NAME", "a word memory holds a name is one"


def test_a_word_recorded_with_its_names_apart_holds_a_noun_as_a_noun():
    """Of a way of writing a word whose classes were counted with its names apart (a word recorded whole, as the
    treebanks' analysts count a proper noun apart), what memory holds as a noun is no name; of any other, a noun is
    still the treebank's noun or its name ("Boston" is a noun in WordNet)."""
    from core.semantics.structure import held_classes

    class Inventory:
        word_classes = {"picture": {"NOUN": 25, "NAME": 1, "VERB": 3}, "boston": {"NOUN": 3}}

        @staticmethod
        def names_of_shape(word):
            return []
    of = held_classes(Inventory(), {"picture"})
    assert of("Picture") == {"NOUN": 25, "NAME": 1, "VERB": 3}
    assert of("Boston") == {"NOUN": 3, "NAME": 3}


def test_what_memory_holds_of_a_word_is_read_through_the_shapes_it_learned():
    """A word memory holds no class of is read as the held word it is a shape of ("breathes" as `breathe`); classes
    without net evidence are no classes; the word-class view's MODAL is the treebank's AUXILIARY, and its NOUN the
    treebank's noun or name ("Boston" is a noun in WordNet)."""
    from core.semantics.structure import held_classes

    class Inventory:
        word_classes = {"breathe": {"VERB": 4, "NOUN": -1}, "can": {"MODAL": 9, "NOUN": 2}}

        @staticmethod
        def names_of_shape(word):
            return ["breathe"] if word == "breathes" else []
    of = held_classes(Inventory())
    assert of("breathes") == {"VERB": 4}
    assert of("Can") == {"AUXILIARY": 9, "NOUN": 2, "NAME": 2}
    assert of("zorp") == {}


def test_mains_structure_view_asks_what_memory_holds_of_a_word():
    """Memory's own structure view asks the reader's word-class view, as it is when asked, of a word no sentence held
    used: measured better both ways on main (2026-10-16 (10))."""
    from core.agents.memory_agent import MemoryAgent
    agent = MemoryAgent()
    view = agent.structure_view()
    assert view.held_classes("whale") == {}
    agent.pattern_inventory().word_classes = {"whale": {"NOUN": 2}}
    assert view.held_classes("Whale") == {"NOUN": 2, "NAME": 2}


def test_pieces_are_written_as_a_treebank_writes_them():
    assert words_of(["It", "doesn", "'t", "change", "."]) == ("It", "does", "n't", "change", ".")
    assert words_of(["We", "can", "'t", "."]) == ("We", "ca", "n't", ".")
    assert words_of(["Tom", "'s", "dog"]) == ("Tom", "'s", "dog")


def test_a_treebank_is_read_with_its_classes_named_as_lyric_names_them(tmp_path):
    from core.learning.teaching_sources import read_conllu
    conllu = tmp_path / "t.conllu"
    conllu.write_text(
        "# sent_id = s-1\n"
        "# text = I don't know Tom.\n"
        "1\tI\tI\tPRON\tPRP\t_\t4\tnsubj\t_\t_\n"
        "2-3\tdon't\t_\t_\t_\t_\t_\t_\t_\t_\n"
        "2\tdo\tdo\tAUX\tVBP\t_\t4\taux\t_\t_\n"
        "3\tn't\tnot\tPART\tRB\t_\t4\tadvmod\t_\t_\n"
        "4\tknow\tknow\tVERB\tVB\t_\t0\troot\t_\t_\n"
        "4.1\tknown\tknow\tVERB\tVBN\t_\t_\t_\t4:conj\t_\n"
        "5\tTom\tTom\tPROPN\tNNP\t_\t4\tobj\t_\tSpaceAfter=No\n"
        "6\t.\t.\tPUNCT\t.\t_\t4\tpunct\t_\t_\n\n", encoding="utf-8")
    (analysed,) = list(read_conllu(str(conllu), "test"))
    assert analysed.words == ("I", "do", "n't", "know", "Tom", ".")
    assert analysed.classes == ("PRONOUN", "AUXILIARY", "PARTICLE", "VERB", "NAME", "PUNCTUATION")
    assert analysed.heads == (4, 4, 4, 0, 4, 4)
    assert analysed.said_in == "test:s-1"


def test_words_keeping_the_same_company_are_counted_into_one_group():
    """Counted over sentences alone, the words that stand where each other stand share a group: "cat" and "dog",
    "runs" and "sleeps", "the" and "a"; and the three groups are apart (`word_groups.counted_groups`)."""
    from core.semantics.word_groups import counted_groups
    said = ["the cat runs .", "the dog runs .", "the cat sleeps .", "the dog sleeps .", "a cat runs .", "a dog sleeps ."]
    group = counted_groups([s.split() for s in said] * 10, 5, 100, 12)
    assert group["cat"] == group["dog"] and group["runs"] == group["sleeps"] and group["the"] == group["a"]
    assert len({group["cat"], group["runs"], group["the"], group["."]}) == 4


def test_another_treebank_is_taught_under_its_own_source(tmp_path):
    """`TreebankSource.of("gum")` teaches GUM's training and development parts, never its test part, each sentence
    under GUM's own name, so what it taught can be found by it (its licence is not EWT's)."""
    from core.learning.teaching_sources import TreebankSource
    folder = tmp_path / "UD_English-GUM"
    folder.mkdir()
    sentence = "# sent_id = {0}\n1\tDogs\tdog\tNOUN\t_\t_\t2\tnsubj\t_\t_\n2\tbark\tbark\tVERB\t_\t_\t0\troot\t_\t_\n\n"
    for part in ("train", "dev", "test"):
        (folder / f"en_gum-ud-{part}.conllu").write_text(sentence.format(part))
    source = TreebankSource.of("gum", str(tmp_path))
    taught = list(source.analysed())
    assert [a.said_in for a in taught] == ["ud_english_gum:train", "ud_english_gum:dev"]
    assert source.provenance().source_id == "ud_english_gum" and TreebankSource.of("ewt").name == "ud_english_ewt"


def test_word_groups_are_taught_as_counted_and_held_as_the_files_group(tmp_path):
    """`WordGroupsSource` teaches each group of each count GROUPS-01 wrote, its words the most frequent first; the
    groups held (`WordGroups`) group a sentence's words as the files do, coarse beside fine, a word in neither
    ungrouped."""
    from core.learning.teaching_sources import WordGroupsSource
    from core.semantics.word_groups import WordGroup, WordGroups, grouping, read_groups
    (tmp_path / "groups_4.tsv").write_text("the\t1\ncat\t2\ndog\t2\nruns\t3\n")
    (tmp_path / "groups_2.tsv").write_text("the\t1\ncat\t1\ndog\t1\nruns\t1\n")
    taught = list(WordGroupsSource(data=str(tmp_path)).word_groups())
    assert [(g.of, g.group, g.words) for g in taught] == [
        (2, 1, ("the", "cat", "dog", "runs")), (4, 1, ("the",)), (4, 2, ("cat", "dog")), (4, 3, ("runs",))]
    held = WordGroups()
    for group in taught:
        held.hold(WordGroup.from_dict(group.to_dict()))
    files = grouping(read_groups(str(tmp_path / "groups_4.tsv")), read_groups(str(tmp_path / "groups_2.tsv")))
    words = ("The", "dog", "runs", "home")
    assert list(held.grouping()(words)) == list(files(words)) == [("1", "1"), ("1", "2"), ("1", "3"), ("?", "?")]
    assert WordGroups().grouping() is None and "\n" in taught[0].said()


def test_memory_keeps_a_word_group_once_and_the_reader_weighs_words_by_it():
    """`MemoryAgent.remember_word_groups`, the store stood in for: kept, one memory with the group whole; given again,
    held already; and the structure view stands the groups held beside each word from then on."""
    import asyncio
    from types import SimpleNamespace
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.word_groups import WordGroup
    group = WordGroup("text", 4, 2, ("cat", "dog"))
    agent = MemoryAgent()
    agent._word_classes_warm = True
    stored = []

    async def store_memory(**kwargs):
        stored.append(kwargs)
        return True, f"m{len(stored)}"

    async def rows_tagged(tag):
        return [SimpleNamespace(memory_id=f"m{k}", metadata=s["source_context"])
                for k, s in enumerate(stored, 1) if tag in s["tags"]]
    agent.store_memory, agent._rows_tagged = store_memory, rows_tagged
    assert agent.structure_view().grouping is None
    first = asyncio.run(agent.remember_word_groups([group]))
    assert (first["remembered"], first["already"]) == (1, 0) and first["kept"] == [(group, "m1")]
    assert stored[0]["source_context"] == {"word_group": group.to_dict()} and len(agent.word_groups()) == 1
    assert list(agent.structure_view().grouping(("Dogs", "dog"))) == [("?", "?"), ("2", "2")]
    again = asyncio.run(agent.remember_word_groups([group]))
    assert (again["remembered"], again["already"]) == (0, 1) and len(stored) == 1
    assert again["held_already"] == [(group, "m1")]
    warmed = asyncio.run(agent._word_group_memories())
    assert len(warmed) == 1 and list(warmed.grouping()(("cat",))) == [("2", "2")]


CONLLU_FORMS = (
    "# sent_id = 1\n"
    "1\tThe\tthe\tDET\tDT\tDefinite=Def\t2\tdet\t_\t_\n"
    "2\tcompany\tcompany\tNOUN\tNN\tNumber=Sing\t3\tnsubj\t_\t_\n"
    "3\thired\thire\tVERB\tVBD\tTense=Past|VerbForm=Fin\t0\troot\t_\t_\n"
    "4\tthree\tthree\tNUM\tCD\t_\t5\tnummod\t_\t_\n"
    "5\tengineers\tengineer\tNOUN\tNNS\tNumber=Plur\t3\tobj\t_\t_\n"
    "6\t.\t.\tPUNCT\t.\t_\t3\tpunct\t_\t_\n\n"
    "# sent_id = 2\n"
    "1\tThey\tthey\tPRON\tPRP\t_\t2\tnsubj\t_\t_\n"
    "2\thire\thire\tVERB\tVBP\tTense=Pres\t0\troot\t_\t_\n\n")


def test_a_treebank_teaches_the_forms_its_words_are_written_in(tmp_path):
    """`TreebankSource.word_forms`: each open-class word written other than its base, with what form it is, from the
    lemma and features columns (a closed class's forms and a word written as its base give nothing); held, a form is
    read as its base ("hired", `hire`)."""
    from core.learning.teaching_sources import TreebankSource
    from core.semantics.word_forms import HeldForms, WordForms
    folder = tmp_path / "UD_English-EWT"
    folder.mkdir()
    (folder / "en_ewt-ud-train.conllu").write_text(CONLLU_FORMS)
    forms = list(TreebankSource.of("ewt", str(tmp_path)).word_forms())
    assert [(f.base, f.word_class, f.forms) for f in forms] == [
        ("engineer", "NOUN", (("engineers", "Number=Plur", 1),)),
        ("hire", "VERB", (("hired", "Tense=Past|VerbForm=Fin", 1),))]
    assert forms[1].counted_from == "ud_english_ewt" and WordForms.from_dict(forms[1].to_dict()) == forms[1]
    assert "\n" in forms[1].said()
    held = HeldForms()
    for item in forms:
        held.hold(item)
    assert held.bases_of("Hired") == ["hire"] and held.bases_of("hire") == []


def test_memory_keeps_word_forms_and_reads_a_word_by_them():
    """`MemoryAgent.remember_word_forms`, the store stood in for: one memory a base word, held once; the language view
    then reads "hired", which no filler holds, as the held `hire` (`names_of_shape`), and a verb is named so for the
    composer (`name_of`)."""
    import asyncio
    from types import SimpleNamespace
    from core.agents.memory_agent import MemoryAgent
    from core.semantics.derived_reader import Lexical
    from core.semantics.sentence_machine import Piece
    from core.semantics.word_forms import WordForms
    item = WordForms("hire", "VERB", (("hired", "Tense=Past|VerbForm=Fin", 6),), "ud_english_ewt")
    agent = MemoryAgent()
    agent._word_classes_warm = True
    view = agent.pattern_inventory()
    view.add(Lexical((Piece("hire", False),), "hire"))
    view.word_classes = {"hire": {"VERB": 5}}
    stored = []

    async def store_memory(**kwargs):
        stored.append(kwargs)
        return True, f"m{len(stored)}"

    async def rows_tagged(tag):
        return [SimpleNamespace(memory_id=f"m{k}", metadata=s["source_context"])
                for k, s in enumerate(stored, 1) if tag in s["tags"]]
    agent.store_memory, agent._rows_tagged = store_memory, rows_tagged
    assert "hire" not in view.names_of_shape("hired")
    first = asyncio.run(agent.remember_word_forms([item]))
    assert (first["remembered"], first["already"]) == (1, 0) and stored[0]["source_context"] == {"word_forms": item.to_dict()}
    assert "hire" in view.names_of_shape("hired") and agent.name_of("hired", "VERB") == "hire"
    again = asyncio.run(agent.remember_word_forms([item]))
    assert (again["remembered"], again["already"]) == (0, 1) and len(stored) == 1
    warmed = asyncio.run(agent._word_form_memories())
    assert warmed.bases_of("hired") == ["hire"]


def test_how_a_word_recorded_whole_was_joined_weighs_its_joins_and_is_taken_back():
    """What a word's record says of how it was joined in sentences no sentence held here holds
    (`StructureView.hold_joins`, `WordRecord.joined_as`) weighs a join of the word as those sentences would, and a
    record taken back takes it with it: "blue" before "hat" is joined to it more surely once a record says an
    adjective before a noun was joined to it every time it was met so."""
    from core.semantics.structure import _Pairs
    view = StructureView()
    view.add(Analysed(("Roy", "sleeps", "."), ("NAME", "VERB", "PUNCTUATION"), (2, 0, 2), ("nsubj", "root", "punct")))
    laid = _Pairs.laid(("She", "wears", "a", "blue", "hat", "."),
                       ("PRONOUN", "VERB", "DETERMINER", "ADJECTIVE", "NOUN", "PUNCTUATION"))

    def blue_to_hat() -> float:
        view._work_out()
        return view._pairs.chance(laid, 5, 4)
    before = blue_to_hat()
    joined = (("dependent word", _Pairs._situation(laid, 5, 4, "dependent word"), 12, 12),)
    said = (("dependent word", _Pairs._relation_situations(laid, 5, 4)[1], "amod", 12),)
    view.hold_joins(joined, said)
    assert blue_to_hat() > before + 0.3, (before, blue_to_hat())
    assert view._pairs.relation(laid, 5, 4) == "amod"
    view.hold_joins(joined, said, times=-1)
    assert blue_to_hat() == pytest.approx(before)


def test_one_sentence_added_counts_in_rather_than_every_sentence_counted_again():
    """A sentence held once the tables are worked out is COUNTED IN (`StructureView.add`): the pair counts, the step
    counts and what the classes say come out as they do when every sentence is counted again, because every one of
    them is a count of one sentence and a count is added to.

    Discarding them instead cost 110.3 s over 18,681 sentences -- 119,873,793 situations worked out to arrive at
    what was already held -- and it was discarded on every single sentence added (lyric_db, 2026-11-12).

    AND THE ONE THING IT DOES NOT BRING IS THE ONE THING STATED: a start counts each sentence as READING gives its
    words their classes as well, from folds built out of all the others (`_as_read`), which cannot be had for one
    sentence without re-reading every sentence. So the counts differ by exactly the read selves of what was added,
    and this adds those by hand to show that the difference is only ever that."""
    from core.semantics.structure import FOLDS, _Pairs
    held = [Analysed(("Roy", "sleeps", "."), ("NAME", "VERB", "PUNCTUATION"), (2, 0, 2),
                     ("nsubj", "root", "punct"), said_in=f"s{k}") for k in range(FOLDS + 2)]
    last = Analysed(("Ann", "sleeps", "."), ("NAME", "VERB", "PUNCTUATION"), (2, 0, 2),
                    ("nsubj", "root", "punct"), said_in="last")

    counted_again = StructureView()
    for analysed in held + [last]:
        counted_again.add(analysed)
    counted_again._work_out()

    added_in = StructureView()
    for analysed in held:
        added_in.add(analysed)
    added_in._work_out()                      # worked out WITHOUT the last one…
    assert added_in._ready
    added_in.add(last)                        # …which is then counted in, and nothing is discarded
    assert added_in._ready, "holding one more sentence must not throw every count away"

    laid = _Pairs.laid(last.words, last.classes)
    assert added_in._pairs.relation(laid, 2, 1) == counted_again._pairs.relation(laid, 2, 1) == "nsubj"
    assert added_in._classes.met("ann") or added_in._classes.met("Ann")
    assert added_in._classes.read(last.words) == counted_again._classes.read(last.words)

    # THE COUNTS AGREE ONCE THE READ SELVES OF WHAT WAS ADDED ARE COUNTED IN TOO, and the read selves are the
    # whole of the difference: nothing else is missing and nothing is counted twice.
    read_selves = [a for a in StructureView._as_read(list(counted_again._held.values()))
                   if a.key() not in counted_again._held]
    assert read_selves, "this store must read a word it has not met as another class, or it proves nothing"
    for analysed in read_selves:
        if analysed.projective():
            for situations, step in added_in._steps_of(analysed):
                for level, situation in zip(added_in._steps, situations):
                    level.setdefault(situation, Counter())[step] += 1
    for level, again in zip(added_in._steps, counted_again._steps):
        assert level == again, "a sentence counted in must leave the step counts the counts of every sentence held"
