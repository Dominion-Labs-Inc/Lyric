"""The English lessons name each thing by the concept memory holds for what the word means there (docs/TEACHING.md
§12e). The lessons hold no facts; a term in a meaning is a name, and memory holds WordNet's senses under WordNet's
names (`WordNetSource._sense_names`). Written as the word, "An eagle is a raptor." taught that "raptor" names a thing
nothing is known of, and "Someone opened the door." an opening that is WordNet's adjective ("the opening chapter")."""
import json

import pytest
from pathlib import Path

LESSONS = Path(__file__).resolve().parents[1] / "data" / "lessons"
#: The lessons' own: the names of their people and pets, the grammar's terms (how often, whether allowed, what
#: would be, what is enough), and the reply to thanks ("You are welcome."), which WordNet has no sense of.
OWN = {"tom", "rex", "kim", "often", "usually", "allowed", "hypothetical", "enough", "welcome"}
#: Relations whose subject is a doing besides `done_*` and `moves_*`. Not how long one lasts: "two days ago" is a
#: span (`lasts_since`).
EVENT_RELATIONS = {"received_by", "has_purpose"}
#: What WordNet files a doing under, as a noun: an act, an event, a process, a saying ("Goodbye.", a farewell).
DOING_NOUNS = {"noun.act", "noun.event", "noun.process", "noun.communication", "noun.phenomenon"}


def misnamed(folder: Path):
    """Each term of the lessons in `folder` that names no sense WordNet teaches, and each kind of doing that names no
    doing: `(term, a sentence it is in, why)`."""
    from core.learning.teaching_sources import WordNetSource
    from core.semantics.cognitive_ingress import normalize_term
    from core.semantics.literals import classify_literal
    names = WordNetSource()._sense_names()
    senses = {}
    for synset, name in names.items():
        if name:
            senses.setdefault(normalize_term(name), []).append(synset)
    found = {}
    for path in sorted(folder.glob("english_[0-9][0-9].json")):
        for record in json.loads(path.read_text())["records"]:
            facts = [f for f in record["meaning"]["facts"] if len(f) >= 3]
            doings = {f[1] for f in facts if str(f[0]).startswith(("done_", "moves_")) or f[0] in EVENT_RELATIONS}
            for relation, subject, obj, *_ in facts:
                for term in (subject, obj):
                    if (not isinstance(term, str) or not term or term.startswith("?") or term.lower() in OWN
                            or classify_literal(term) is not None or any(c.isdigit() for c in term)
                            or len(term) == 1):
                        continue
                    held = senses.get(normalize_term(term))
                    if held is None:
                        found.setdefault(term, (record["sentence"], "names nothing WordNet teaches"))
                    elif (relation == "instance_of" and term == obj and subject in doings
                          and not any(s.pos() == "v" or s.lexname() in DOING_NOUNS for s in held)):
                        found.setdefault(term, (record["sentence"],
                                                f"a doing, and names only {sorted(s.lexname() for s in held)}"))
    return sorted((term, sentence, why) for term, (sentence, why) in found.items())


def test_every_lesson_term_names_a_concept_wordnet_teaches_and_a_doing_names_a_doing():
    wrong = misnamed(LESSONS)
    assert not wrong, "\n".join(f"{term!r} in {sentence!r}: {why}" for term, sentence, why in wrong)


def test_wordnet_names_its_senses_as_the_stores_were_taught():
    """WordNet's names follow from WordNet, the stated senses and how the lessons use their words, and a store keeps
    the names it was taught under. An edit that renames a sense leaves it there under its old name, and the new name
    beside it: counting a degree's kind as a thing's gave "fast" to fasting (2026-10-12). A rename is made on purpose,
    with the stores repaired to it (`scripts/repair_renamed_senses.py`) and then recorded
    (`scripts/wordnet_names.py --write`); never by an edit that happened to move it.

    THE NAMES COME FROM THE DOOR, AND THE DOOR NAMES FROM WHAT LYRIC HOLDS (2026-11-13). A process holding none
    of its words has only the spelling rules, which write "acrobatics" `acrobatic` and "apparatus" `apparatu`,
    so every sense whose name ends so would read as moved. Nothing in `tests/` warms a view -- every test
    process is `lyric_dev`, which holds no constructions -- so this is skipped where there are no words to name
    from, rather than compared against names no substrate wrote."""
    from core.semantics.derived_reader import live_view
    if not len(live_view()):
        pytest.skip("the senses are named at the door, which names from what Lyric holds, and this process holds "
                    "none of its words: the view is warmed from memory (MemoryAgent.warm_word_classes)")
    import importlib.util
    spec = importlib.util.spec_from_file_location("wordnet_names", LESSONS.parents[1] / "scripts" / "wordnet_names.py")
    names = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(names)
    moved = names.differences(names.current(), names.taught())
    assert not moved, (f"{len(moved)} senses named otherwise than the stores were taught "
                       f"(scripts/wordnet_names.py --diff):\n" + "\n".join(
                           f"  {sense}: taught as {was!r}, named now {now!r}" for sense, (was, now) in list(moved.items())[:20]))
