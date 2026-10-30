"""Everything a source can teach is taught, and the pass is what says so.

`TeachingPass.run` dispatches on method names written into it — a tuple of seven, plus `records`, `word_classes`,
`usage`, `listening_pairs`, `analysed`, `said_of` and `pronunciations` handled each on its own. That is the same
shape as the snapshot that counted eight things and missed word classes (lab notebook (82), (83)): a list kept by
hand, with nothing to make it fail when it falls behind. Checked 2026-10-29, the list is complete — every teaching
capability of all 17 sources is consumed. This holds it complete, because a source grown a new way to teach and
never asked for it is teaching that silently does not happen, which is the one thing a re-teach cannot survive.
"""
import inspect
import re
from pathlib import Path

from core.learning import teaching_sources as ts

#: Zero-argument methods on a source that are NOT something to teach, each with why.
NOT_A_LESSON = {
    "provenance": "who stated it, asked of every source by the pass itself",
    "name": "what the source is called",
    "quality": "the standing the source declares",
    "sections": "lists the cache's sections so the command line can name one (WikidataSource)",
    "stated_senses": "the senses the lessons use their words in, read by the source's own records()",
}


def _sources():
    return sorted(
        ((name, obj) for name, obj in vars(ts).items()
         if inspect.isclass(obj) and obj.__module__ == ts.__name__ and hasattr(obj, "provenance")),
        key=lambda pair: pair[0])


def _what_the_pass_asks_for():
    """The source methods `TeachingPass` consumes, read out of the pass and not listed here."""
    source = (Path(__file__).resolve().parents[1] / "core" / "learning" / "teaching.py").read_text()
    asked = set(re.findall(r'hasattr\(self\.source, "(\w+)"\)', source))
    asked |= set(re.findall(r'self\.source\.(\w+)\(', source))
    asked |= set(re.findall(r'getattr\(self\.source, "(\w+)"', source))
    asked |= set(re.findall(r'\("(\w+)", learning\.', source))      # the dispatch tuple
    return asked


def _lessons(cls):
    """What this source offers to teach: a public method needing no argument but itself."""
    offered = []
    for name, function in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_") or name in NOT_A_LESSON:
            continue
        needs = [p for p in inspect.signature(function).parameters.values()
                 if p.name != "self" and p.default is inspect.Parameter.empty]
        if not needs:
            offered.append(name)
    return offered


def test_every_source_offers_something_to_teach():
    for name, cls in _sources():
        assert _lessons(cls), f"{name} is a teaching source that teaches nothing"


def test_everything_a_source_can_teach_is_asked_for_by_the_pass():
    asked = _what_the_pass_asks_for()
    never_asked = {name: sorted(set(_lessons(cls)) - asked) for name, cls in _sources()}
    never_asked = {name: missing for name, missing in never_asked.items() if missing}
    assert not never_asked, (
        "a source can teach this and no pass ever asks for it, so teaching it cannot happen: "
        f"{never_asked}. Either wire it into TeachingPass.run or say in NOT_A_LESSON why it is not a lesson.")


def test_every_source_says_who_stated_it():
    """Provenance is how a fact keeps its standing; a source without it teaches anonymously."""
    for name, cls in _sources():
        assert callable(getattr(cls, "provenance", None)), f"{name} states no provenance"


def test_a_source_prices_everything_it_states_or_prices_each_record():
    """The contract the pass actually relies on, and it is not written anywhere else.

    Everything but `records()` is taught at `float(self.source.quality)` — one price for the whole of what the
    source states. ConceptNet has no such price and declares none: its weights run 0.5 to 4.47 on one relation, so
    every record carries its own (`quality_from_corroboration`). That is sound, and it holds only while ConceptNet
    teaches through `records()` alone. Grown a `usage()` or a `said_of()`, the pass would reach
    `float(self.source.quality)` and raise AttributeError partway through a pass that had already written — the
    failure arriving after the writing, which is the worst place for it. Checked 2026-10-29: ConceptNet teaches
    records only, and `LessonSource` sets its price per instance from the lesson file it reads.
    """
    for name, cls in _sources():
        if hasattr(cls, "quality") or "quality" in getattr(cls, "__annotations__", {}):
            continue
        beyond_records = sorted(set(_lessons(cls)) - {"records"})
        assert not beyond_records, (
            f"{name} declares no quality, so each of its records must carry its own, and it may teach through "
            f"records() alone. It also teaches {beyond_records}, which the pass prices at the source's quality "
            f"and would fail on after it had already written.")


def test_each_reason_in_not_a_lesson_still_names_something():
    """A reason kept for a method nobody has any more is a reason nobody will question."""
    everywhere = set()
    for _, cls in _sources():
        everywhere |= {n for n, _ in inspect.getmembers(cls, callable) if not n.startswith("_")}
        everywhere |= set(vars(cls))
    stale = sorted(set(NOT_A_LESSON) - everywhere)
    assert not stale, f"NOT_A_LESSON excuses methods no source has: {stale}"


def test_the_closed_classes_state_their_forms_and_what_form_each_is():
    """`CLOSED_PARADIGM`, offered through the `word_forms` layer: a class alone says "am" is a copula, which left
    saying unable to choose between "am" and "is" at all, and unable to offer "am" as a copula verb because UD
    writes it only as an auxiliary. These forms are finite and no corpus gives them, so they are stated -- the same
    reason `CLOSED_CLASSES` is stated rather than counted."""
    from core.learning.teaching_sources import CLOSED_CLASSES, CLOSED_PARADIGM, ClosedClassSource
    from core.semantics.word_forms import WordForms

    stated = {w for words in CLOSED_CLASSES.values() for w in words}
    by_base = {(base, cls): dict(forms) for base, cls, forms in CLOSED_PARADIGM}

    # THE TWO STATED TABLES AGREE: no form is stated for a word whose class is not, and no base is left out of them.
    for base, cls, forms in CLOSED_PARADIGM:
        assert base in stated, f"the paradigm states forms of {base!r}, which no closed class holds"
        for form, features in forms:
            assert form in stated, f"{form!r}, a form of {base!r}, is in no closed class"
            assert features, f"{form!r} of {base!r} says nothing of what form it is"
            for pair in features.split("|"):
                assert pair.count("=") == 1 and all(pair.split("=")), f"{features!r} of {form!r} is not UD's features"

    # THE HOLE THIS CLOSES: "am" as a copula VERB, first person singular present, which UD holds only as AUXILIARY.
    copula = by_base[("be", "VERB")]
    assert "am" in copula, "the copula still cannot be said in the first person singular"
    assert "Person=1" in copula["am"] and "Number=Sing" in copula["am"], copula["am"]
    # And the third person, so that agreement has two forms to tell apart rather than one to fall back on.
    assert "Person=3" in copula["is"] and "Number=Sing" in copula["is"], copula["is"]

    # THE OTHER HALF: case, so that a subject and an object are not the same word.
    speaker = by_base[("i", "PRONOUN")]
    assert "Case=Nom" in speaker["i"], speaker["i"]
    assert "Case=Acc" in speaker["me"], speaker["me"]
    assert "Reflex=Yes" in speaker["myself"], "a reflexive said as a plain object is how 'Myself wash myself.' read"
    assert speaker["i"] != speaker["me"], "nominative and accusative stated alike is the defect, not the fix"

    # OFFERED THROUGH THE LAYER THAT HOLDS COUNTED FORMS, so stated and counted meet as one kind of thing.
    offered = list(ClosedClassSource().word_forms())
    assert offered and all(isinstance(f, WordForms) for f in offered), offered[:1]
    assert {(f.base, f.word_class) for f in offered} == set(by_base)
    for held in offered:
        # Each form stated once: a statement that a form exists is not evidence of how often it is used.
        assert all(n == 1 for _, _, n in held.forms), held.forms
        assert held.counted_from == "closed-classes", held.counted_from
