"""The Parallel Meaning Bank's meanings said in Lyric's meaning language (`core/semantics/pmb_meanings.py`). No store,
no download: each document is written here in the PMB's notation (`en.raw`, `en.drs.sbn`), its comments coloured as
the release colours them (a word the line marks as of its grammar in red)."""
from core.semantics import pmb_meanings as pm
from core.semantics.derived_reader import MeaningFact as F

RED, PLAIN = "\x1b[31m", "\x1b[0m"


def _document(tmp_path, text, lines):
    """A document folder holding `text` and its meaning, one `(body, words, span)` a line; a word written `*the*`
    is marked."""
    folder = tmp_path / "p00" / "d0001"
    folder.mkdir(parents=True)
    (folder / "en.raw").write_text(text + "\n", encoding="utf-8")
    sbn = []
    for body, words, span in lines:
        comment = " ".join(f"{RED}{w[1:-1]}{PLAIN}" if w.startswith("*") else w for w in words.split())
        sbn.append(f"{body:40} % {comment} {f'[{span[0]}-{span[1]}]' if span else ''}")
    (folder / "en.drs.sbn").write_text("%%% made by hand\n" + "\n".join(sbn) + "\n", encoding="utf-8")
    return pm.read_document(folder)


def _name(sense):
    return sense.split(".")[0].replace("_", " ")


def test_each_term_is_anchored_to_the_lines_that_say_it(tmp_path):
    """"A brown dog barked.": each line keeps where its words are and which it marks; the dog's term is said by the
    dog's line, "brown" by its own."""
    doc = _document(tmp_path, "A brown dog barked.", [
        ("brown.a.01", "*A* brown", (0, 7)), ("dog.n.01 Colour -1", "dog", (8, 11)),
        ("bark.v.01 Agent -1 Time +1", "barked *.*", (12, 19)), ("time.n.08 TPR now", "", None)])
    assert doc.concepts[0].span == (0, 7) and doc.concepts[0].marked == ("A",)
    said = pm.meaning_of(doc, _name)
    assert F("has_property", "?v1", "brown") in said.meaning.facts
    assert said.anchors["?v1"] == ((1, "head"),) and said.anchors["brown"] == ((0, "head"),)


def test_when_asks_a_time_the_happening_is_during(tmp_path):
    """"When was Walt Disney born?": the question word alone asks a time (a year asked, nothing marked); the birth is
    during it, as the lessons say "When did the dog bark?". A name of two words is one name."""
    doc = _document(tmp_path, "When was Walt Disney born?", [
        ("time.n.08 YearOfCentury ?", "When", (0, 4)), ("time.n.08 TPR now", "was", (5, 8)),
        ('male.n.02 Name "Walt Disney"', "Walt Disney", (9, 20)),
        ("bear.v.02 Time -3 Time -2 Patient -1", "born *?*", (21, 26))])
    said = pm.meaning_of(doc, _name)
    assert said.gaps == ()
    assert said.meaning.act == "ask" and said.meaning.asked == ("?v0",)
    assert F("during", "?v3", "?v0") in said.meaning.facts and F("done_to", "?v3", "walt disney") in said.meaning.facts


def test_a_question_word_alone_holds_no_kind_and_one_that_names_a_kind_does(tmp_path):
    """"Where is it?": `location` is what "Where" asks for, no kind said (the lessons: `located_in(?t0, ?x)`)."""
    doc = _document(tmp_path, "Where is it?", [
        ("location.n.01 Name ?", "Where", (0, 5)),
        ("be.v.08 Theme +2 Time +1 Location -1", "is", (6, 8)), ("time.n.08 EQU now", "", None),
        ("entity.n.01", "it *?*", (9, 12))])
    said = pm.meaning_of(doc, _name)
    assert not any(f.relation == "instance_of" for f in said.meaning.facts)
    assert said.meaning.facts == (F("located_in", "?v3", "?v0"),)


def test_a_quality_held_plainly_and_its_degree_asked(tmp_path):
    """Value `+` is a quality held plainly ("This tree is tall."); Value `?` its degree asked ("How tall is it?")."""
    plain = _document(tmp_path / "a", "The tree is tall.", [
        ("tree.n.01", "*The* tree", (0, 8)), ("time.n.08 EQU now", "is", (9, 11)),
        ("tall.a.01 Time -1 Value + AttributeOf -2", "tall *.*", (12, 17))])
    assert F("has_property", "?v0", "tall") in pm.meaning_of(plain, _name).meaning.facts
    asked = pm.meaning_of(_document(tmp_path / "b", "How tall is it?", [
        ("tall.a.01 Value ? Time +1 AttributeOf +2", "*How* tall", (0, 8)), ("time.n.08 EQU now", "is", (9, 11)),
        ("entity.n.01", "it *?*", (12, 15))]), _name).meaning
    assert asked.asked == ("?d0",)
    assert {F("has_degree", "?v2", "?d0"), F("instance_of", "?d0", "tall")} <= set(asked.facts)


def test_the_one_being_the_other_is_equals_and_a_name_is_never_lost(tmp_path):
    """"The capital of France is Paris.": `equals`, as the lessons say "What is the sum of two and three?"; merged,
    Paris was lost."""
    doc = _document(tmp_path, "The capital of France is Paris.", [
        ("capital.n.06 Of +1", "*The* capital *of*", (0, 14)), ('country.n.02 Name "France"', "France", (15, 21)),
        ("be.v.02 Theme -2 Time +1 Co-Theme +2", "is", (22, 24)), ("time.n.08 EQU now", "", None),
        ('city.n.01 Name "Paris"', "Paris *.*", (25, 31))])
    facts = pm.meaning_of(doc, _name).meaning.facts
    assert F("equals", "?v0", "paris") in facts and F("instance_of", "?v0", "capital", given=True) in facts


def test_a_count_pointing_at_its_number_is_that_number(tmp_path):
    """"He has two books.": `Quantity -1` points at the line saying 2; it is no count of minus one."""
    doc = _document(tmp_path, "He bought two books.", [
        ("male.n.02", "He", (0, 2)), ("buy.v.01 Agent -1 Time +1 Theme +3", "bought", (3, 9)),
        ("time.n.08 TPR now", "", None), ("quantity.n.01 EQU 2", "two", (10, 13)),
        ("book.n.01 Quantity -1", "books *.*", (14, 19))])
    facts = pm.meaning_of(doc, _name).meaning.facts
    assert F("has_count", "?v4", "2") in facts and not any(f.obj == "-1" for f in facts)


def test_a_thing_is_known_by_the_word_before_its_qualities(tmp_path):
    """"He knocked at the closed door.": "the" is marked on the line of "closed", and the door is known."""
    doc = _document(tmp_path, "He knocked at the closed door.", [
        ("male.n.02", "He", (0, 2)), ("knock.v.01 Agent -1 Time +1 Theme +3", "knocked *at*", (3, 13)),
        ("time.n.08 TPR now", "", None), ("closed.a.01 AttributeOf +1", "*the* closed", (14, 24)),
        ("door.n.01", "door *.*", (25, 30))])
    assert F("instance_of", "?v4", "door", given=True) in pm.meaning_of(doc, _name).meaning.facts


def test_what_a_thing_is_said_to_be_is_said_of_it_alone(tmp_path):
    """"Tom is a gentleman.": `isa(tom, gentleman)`, as the lessons say "Tom is a boy."; no gentleman besides."""
    doc = _document(tmp_path, "Tom is a gentleman.", [
        ('male.n.02 Name "Tom"', "Tom", (0, 3)), ("be.v.01 Theme -1 Time +1 Co-Theme +2", "is", (4, 6)),
        ("time.n.08 EQU now", "", None), ("gentleman.n.01", "*a* gentleman *.*", (7, 19))])
    assert pm.meaning_of(doc, _name).meaning.facts == (F("isa", "tom", "gentleman"),)


def test_what_a_thing_is_said_not_to_be_is_denied_of_it_with_its_qualities(tmp_path):
    """"Edison was not a bright student.": no student and not bright, said of Edison, as "Bergen is a Norwegian town."
    says what is said of the town of Bergen; kept apart, the student was another thing, said to be one."""
    doc = _document(tmp_path, "Edison was not a bright student.", [
        ('male.n.02 Name "Edison"', "Edison", (0, 6)), ("NEGATION <1", "", None),
        ("be.v.01 Theme -1 Time +1 Co-Theme +3", "was *not*", (7, 14)), ("time.n.08 TPR now", "", None),
        ("bright.a.03 AttributeOf +2", "*a* bright", (15, 23)), ("person.n.01 Role +1", "student *.*", (24, 32)),
        ("student.n.01", "", None)])
    facts = set(pm.meaning_of(doc, _name).meaning.facts)
    assert {F("isa", "edison", "student", False), F("has_property", "edison", "bright", False)} <= facts
    assert not any(f.relation == "instance_of" for f in facts), facts


def test_the_pmbs_clock_of_24_hours_says_the_half_of_the_day():
    """"07:15" is a morning's, as "7:15 a.m." is; read as a clock written bare, it was `7:15`."""
    assert [pm._date({"ClockTime": c}) for c in ("07:15", "18:30", "00:00")] == ["7:15 a.m.", "6:30 p.m.", "12:00 a.m."]
