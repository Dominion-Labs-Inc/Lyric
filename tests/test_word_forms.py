"""English word forms taught from WordNet: each verb sense's forms, as real text writes them, said of the doer its own
frames give it, in the frames the lessons say a doing in."""
import pytest

from core.learning.teaching_sources import WordNetExamplesSource, WordNetSource


@pytest.fixture(scope="module")
def wordnet():
    return WordNetSource()


@pytest.mark.parametrize("verb, past, under_way, now", [
    ("run", "ran", "running", "runs"),            # as Brown writes them
    ("stop", "stopped", "stopping", "stops"),
    ("compile", "compiled", "compiling", "compiles"),
    ("stroll", "strolled", "strolling", "strolls"),
    ("abet", "abetted", "abetting", "abets"),     # as WordNet lists them
    ("reread", "reread", "rereading", "rereads"),  # a compound of a verb whose past no change makes
    ("overeat", None, "overeating", "overeats"),  # "overate" WordNet cannot read back: no past, never "overeated"
    ("have", "had", "having", "has"),             # tagged apart in Brown, and verbs all the same
    ("redo", "redid", "redoing", "redoes"),
])
def test_a_verb_is_written_in_each_form_as_the_nearest_evidence_writes_it(wordnet, verb, past, under_way, now):
    assert [wordnet._verb_written(verb, form) for form in ("past", "under way", "now")] == [past, under_way, now]


def test_each_verb_sense_is_said_in_its_forms_of_the_doer_its_frames_give_it():
    """Someone ("Somebody ----s": stroll), someone to something (parse), nothing (the weather: drizzle), something
    ("Something ----s": bloom); a sense with none of these ("Somebody ----s Adjective": seem) in none."""
    senses = ("stroll.v.01", "parse.v.01", "drizzle.v.01", "bloom.v.01", "seem.v.01")
    said = {r.sentence: r.meaning.canonical() for r in WordNetSource(parts=("v",), senses=senses).records(
        examples_only=True) if r.forms}
    assert said["Tom strolled."] == "tell: done_by(?v0, tom) & instance_of(?v0, stroll) & precedes(?v0, ?now)"
    assert said["Tom is strolling."] == "tell: done_by(?v0, tom) & during(?v0, ?now) & instance_of(?v0, stroll)"
    assert said["Tom strolls."] == "tell: done_by(?v0, tom) & instance_of(?v0, stroll)"
    assert said["Tom parsed them."] == ("tell: done_by(?v0, tom) & done_to(?v0, ?previous) & instance_of(?v0, parse) & "
                                        "precedes(?v0, ?now)")
    assert said["It drizzled."] == "tell: instance_of(?v0, rain drizzle) & precedes(?v0, ?now)"
    assert said["It bloomed."] == "tell: done_by(?v0, ?previous) & instance_of(?v0, bloom) & precedes(?v0, ?now)"
    assert not any("seem" in sentence for sentence in said)


def test_wordnet_s_examples_are_examples_only_and_of_their_part_only():
    """For a store that holds WordNet's facts: its examples of English and none of its facts again. Of verbs, their
    forms and their kinds said as rules ("To stroll is to walk."), and no noun's plural."""
    records = list(WordNetExamplesSource(parts=("v",)).records())
    assert records and all(record.example for record in records)
    assert any(record.forms for record in records) and any(record.sentence is None for record in records)
    assert not any(record.relation == "isa" and record.forms for record in records), "no plural is a verb's"


def test_wordnet_s_usage_is_taught_alone_and_of_its_parts_only():
    """How often WordNet's words were met naming each sense (SemCor), of the parts asked for and nothing else: a
    source with no records, counted all the same (`vocabulary_only`)."""
    from core.learning.teaching_sources import WordNetUsageSource
    source = WordNetUsageSource(parts=("v",))
    assert source.vocabulary_only and not list(source.records())
    used = {(word, sense): (times, forms) for word, sense, times, forms in source.usage()}
    met = {key: times for key, (times, _) in used.items()}
    assert met[("compile", "store roll up")] == 3
    # A verb's count is of it in every form, and its forms come with it, as the lessons write them.
    assert set(used[("compile", "store roll up")][1]) == {"compiled", "compiling", "compiles"}
    assert "had" in used[next(key for key in used if key[0] == "have")][1]
    assert not any(sense == "dog" for (_, sense) in met), "no noun's sense among a verb's"
