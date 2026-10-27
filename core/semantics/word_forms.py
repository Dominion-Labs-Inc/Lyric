"""The forms a word is written in, as treebanks analysed by hand show them: "came" is a form of `come`, "hired" of
`hire`, "largest" of `large`. Each word of a Universal Dependencies treebank is given its base form (its lemma) and
what form it is in (its features: `Tense=Past|VerbForm=Fin`); kept here for each base word and class, every form the
treebank wrote it in and how often.

The reader goes by them for a word it holds nothing of (`PatternInventory.names_of_shape`): a form the treebank
showed of a word memory holds is that word, before any change Lyric found productive in its own fillers, which
"-ed" was never (its slots hold verbs in every form, so "exhale" in a slot that also held "barked" counted against it;
lab notebook 2026-10-19). Of the words of UD's English treebanks, 2,237 were known only by their base form so (2.3% of
the words read), "called", "took", "hired", "locked" among them.

Read from files only; held by memory as one memory a base word (`MemoryAgent.remember_word_forms`).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

#: The classes whose words take forms a reader must undo: the open classes. A closed class's forms ("me", "been")
#: are the constructions' own words.
OPEN_CLASSES = {"NOUN": "NOUN", "VERB": "VERB", "ADJ": "ADJECTIVE", "ADV": "ADVERB"}


def _written(word: str) -> bool:
    """A word as words are written: letters, with a hyphen or an apostrophe inside."""
    return word.replace("-", "").replace("'", "").isalpha()


@dataclass(frozen=True)
class WordForms:
    """One word, by its base form and class, and the forms a treebank wrote it in: each with what form it is (the
    treebank's features) and how often it was met so."""

    base: str
    word_class: str
    forms: Tuple[Tuple[str, str, int], ...]
    counted_from: str = ""

    def key(self) -> str:
        return f"{self.counted_from}:{self.word_class}:{self.base}"

    def claim(self) -> str:
        """What it was taught as, as the knowledge ledger records it: the word written in these forms."""
        return f"the forms {self.word_class.lower()} {self.base!r} is written in ({self.counted_from})"

    def said(self) -> str:
        """The word and its forms, said plainly over two lines, so memory keeps it as a record and never reads it as
        a claim (`_readable_claim`)."""
        return f"Forms of the {self.word_class.lower()} \"{self.base}\" in {self.counted_from}:\n" + \
            ", ".join(f"{form} ({features or 'as written'})" for form, features, _ in self.forms)

    def to_dict(self) -> Dict[str, Any]:
        return {"base": self.base, "class": self.word_class, "counted_from": self.counted_from,
                "forms": [list(f) for f in self.forms]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WordForms":
        return cls(str(data["base"]), str(data["class"]),
                   tuple((str(f), str(feats), int(n)) for f, feats, n in data["forms"]), str(data.get("counted_from", "")))


def forms_from_conllu(lines: Iterable[str], counted_from: str) -> List[WordForms]:
    """Every word of the open classes in CoNLL-U lines, by its base form and class, with each form it was written
    in other than the base itself, lowered; a word written only as its base gives nothing. A WORD THE ANALYSTS MARKED
    MISWRITTEN (`Typo=Yes`) is no form of its word: "madea" and "makke" were taught forms of `make`, read as none
    (TRAIN-FORMAT-02, lyric_dev2, 2026-10-26)."""
    met: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 6 or not cols[0].isdigit():
            continue
        form, base, upos, features = cols[1].lower(), cols[2].lower(), cols[3], cols[5]
        word_class = OPEN_CLASSES.get(upos)
        if word_class is None or form == base or not _written(form) or not _written(base) \
                or "Typo=Yes" in features.split("|"):
            continue
        met[(base, word_class)][(form, "" if features == "_" else features)] += 1
    return [WordForms(base, word_class, tuple((form, features, n) for (form, features), n in counts.most_common()),
                      counted_from)
            for (base, word_class), counts in sorted(met.items())]


class HeldForms:
    """The word forms memory holds: for a written word, the base words it is a form of, the most met first."""

    def __init__(self) -> None:
        self._held: Dict[str, WordForms] = {}
        self._bases: Dict[str, Counter] = defaultdict(Counter)
        self._written: Optional[Dict[str, List[Tuple[str, str, str, int]]]] = None

    def __len__(self) -> int:
        return len(self._held)

    def hold(self, item: WordForms) -> None:
        old = self._held.get(item.key())
        if old is not None:
            for form, _, n in old.forms:
                self._bases[form][old.base] -= n
        self._held[item.key()] = item
        self._written = None
        for form, _, n in item.forms:
            self._bases[form][item.base] += n

    def bases_of(self, word: str) -> List[str]:
        """The base words `word` is a form of, the one it was most often a form of first."""
        return [base for base, n in self._bases.get(word.lower(), Counter()).most_common() if n > 0]

    def items(self) -> List[WordForms]:
        """Every word's forms held."""
        return list(self._held.values())

    def forms_of(self, word: str) -> List[Tuple[str, str, str, int]]:
        """What `word` is a form of: each (base word, class, what form it is, how often met so)."""
        if self._written is None:
            self._written = defaultdict(list)
            for item in self._held.values():
                for form, features, n in item.forms:
                    self._written[form].append((item.base, item.word_class, features, n))
        return list(self._written.get(word.lower(), ()))
