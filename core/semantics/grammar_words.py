"""What memory holds of each word, as the grammar asks it (`grammar.Words`).

HOW EACH WORD IS USED is counted from the sentences memory holds analysed by hand (a treebank's, `structure.Analysed`:
each word's class, the word it depends on and as what), each use signed as the grammar's own entries name their uses
(`data/grammar/english.json`: "is" before a doing is `be:ng`, "who" asking for a doer `wh:subject`), never by a list
of English words here: a word is a form of "be" because the grammar reads it as one. Counted once, when the sentences
are given (`HeldWords`).

WHAT A WORD'S THING IS comes from what memory holds of things (`Knowledge`): what each is a kind of, which are
particular ones (a name: "Lincoln" an instance of a president), what an adjective's definition is written with
("British": the United Kingdom). `GraphKnowledge` holds those links in this process, given once from the store (or, in
an experiment, from WordNet), so a sentence is read without waiting on the store.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from core.semantics.grammar import Words

#: The classes of words a treebank's analysis gives, as the grammar's kinds of word; any other is a grammar word's.
KINDS = {"NOUN": "NOUN", "NAME": "NAME", "VERB": "VERB", "ADJECTIVE": "ADJECTIVE", "ADVERB": "ADVERB",
         "NUMERAL": "NUMERAL", "PREPOSITION": "PREPOSITION"}
#: The endings a form of each class is written with, which a change may undo.
INFLECTED = {"NOUN": ("s", "i", "a", "en", "ae"), "VERB": ("s", "d", "ing", "n", "t"), "ADJECTIVE": ("er", "est", "r", "st"),
             "ADVERB": ("er", "est")}
#: Classes a treebank gives to marks, not words.
MARKS = ("PUNCTUATION", "SYMBOL", "OTHER")

#: How a treebank marks a thing said of a doing with no preposition before it: UD's `obl:unmarked`, which its earlier
#: releases split into `obl:tmod` (a time) and `obl:npmod`.
_BARE_OF_A_DOING = frozenset({"obl:unmarked", "obl:tmod", "obl:npmod"})


class Knowledge:
    """What memory holds of things, as the grammar asks it. Every answer is plain where nothing is held."""

    def kinds(self, name: str, cls: str) -> List[str]:
        """What the word's thing is a kind of, nearest first; for an adjective, what its definition is written with
        and what that is a kind of."""
        return []

    def defined(self, name: str) -> List[str]:
        """What a thing held as a kind of nothing (an adjective's sense) is defined with, as memory holds it: "British"
        the United Kingdom, "Norwegian" Norway."""
        return []

    def is_person(self, name: str, particular: bool = False) -> Optional[bool]:
        """Whether the thing is a person: True; False where memory holds what it is and a person is not among it;
        None where memory holds nothing of what it is. `particular`: one thing called by this name ("Bill"), judged
        by what it is held one of, never by the kinds a word written the same names ("bill", a beak)."""
        return None

    def is_time(self, term: str) -> Optional[str]:
        return None

    def capitalized(self, word: str) -> Mapping[str, float]:
        return {}

    def known_words(self, words: Sequence[str]) -> Mapping[str, str]:
        """EACH KIND OF WORD MEMORY HOLDS THESE WORDS AS ONE WORD OF, with the name it holds them under: "credit
        card" a thing, "fed up" a quality, "kind of" an adverb, "pass away" a verb. Nothing where it holds none."""
        return {}

    def known_name(self, words: Sequence[str]) -> Optional[str]:
        return self.known_words(words).get("NOUN")

    def known_verb(self, words: Sequence[str]) -> Optional[str]:
        return self.known_words(words).get("VERB")

    def classes(self, word: str) -> Mapping[str, float]:
        """The kinds of word memory holds the word as, for a word no sentence held used."""
        return {}

    def add(self, subject: str, relation: str, obj: str) -> None:
        """A link memory has just taken in (`isa`, `instance_of`, `defined_with`); held where links are held."""


def _concept(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_")


def _plain(name: str) -> str:
    return str(name).replace("_", " ")


#: The kinds of time memory holds, by name: a point in it, or a stretch of it.
POINTS = frozenset({"calendar_day", "day", "calendar_month", "month", "season", "time_of_day", "day_of_the_week",
                    "date", "year", "point", "time_point"})
STRETCHES = frozenset({"time_period", "time_unit", "period", "duration"})


class GraphKnowledge(Knowledge):
    """What memory holds of things, held in this process: each thing's links (`isa`, `instance of`, `defined with`)
    as the store holds them (`add`), what is held of word classes and names asked of `classes`, `names`.

    `known_words(words)` asks `names(words)` (each kind of word memory holds several words as, with its name)."""

    def __init__(self, classes: Optional[Callable[[str], Mapping[str, float]]] = None,
                 names: Optional[Callable[[Sequence[str]], Mapping[str, str]]] = None):
        self._isa: Dict[str, List[str]] = defaultdict(list)
        self._instance: Dict[str, List[str]] = defaultdict(list)
        self._defined: Dict[str, List[str]] = defaultdict(list)
        self._classes = classes
        self._names = names
        self._kinds: Dict[Tuple[str, str], List[str]] = {}

    def add(self, subject: str, relation: str, obj: str) -> None:
        relation = relation.replace(" ", "_")
        table = {"isa": self._isa, "instance_of": self._instance, "defined_with": self._defined}.get(relation)
        if table is not None:
            table[_concept(subject)].append(_concept(obj))
            self._kinds = {}

    def defined(self, name: str) -> List[str]:
        return [_plain(w) for w in self._defined.get(_concept(name), [])]

    def discard(self, subject: str, relation: str, obj: str) -> None:
        """A link taken back (a word recorded otherwise since): once, as it was added once."""
        relation = relation.replace(" ", "_")
        table = {"isa": self._isa, "instance_of": self._instance, "defined_with": self._defined}.get(relation)
        held = table.get(_concept(subject)) if table is not None else None
        if held and _concept(obj) in held:
            held.remove(_concept(obj))
            self._kinds = {}

    def __len__(self) -> int:
        return sum(len(v) for v in self._isa.values()) + sum(len(v) for v in self._instance.values())

    def _up(self, start: Sequence[str]) -> List[str]:
        out: List[str] = []
        seen = set(start)
        frontier = list(start)
        while frontier:
            nxt = []
            for c in frontier:
                for k in list(self._isa.get(c, ())) + list(self._instance.get(c, ())):
                    if k not in seen:
                        seen.add(k)
                        out.append(k)
                        nxt.append(k)
            frontier = nxt
        return out

    def kinds(self, name: str, cls: str) -> List[str]:
        key = (_concept(name), cls)
        if key not in self._kinds:
            if cls == "ADJECTIVE":
                written = self._defined.get(key[0], [])
                found = [w for w in written if w in self._isa or w in self._instance]
                self._kinds[key] = [_plain(k) for k in found + self._up(found)]
            else:
                self._kinds[key] = [_plain(k) for k in self._up([key[0]])]
        return self._kinds[key]

    def is_person(self, name: str, particular: bool = False) -> Optional[bool]:
        if particular:
            held = list(self._instance.get(_concept(name), ()))
            kinds = [_plain(k) for k in held + self._up(held)]
        else:
            kinds = [_plain(_concept(name))] + self.kinds(name, "NOUN")
            if len(kinds) == 1:
                return None
        if not kinds:
            return None
        return "person" in kinds

    def is_time(self, term: str) -> Optional[str]:
        from core.semantics.literals import classify_literal
        if re.fullmatch(r"1[0-9]{3}|20[0-9]{2}", term):
            return "point"
        literal = classify_literal(term)
        if literal is not None and literal.kind in ("time", "date"):
            return "point"
        above = {_concept(k) for k in self.kinds(term, "NOUN")} | {_concept(term)}
        if above & POINTS:
            return "point"
        if above & STRETCHES:
            return "stretch"
        return None

    def capitalized(self, word: str) -> Mapping[str, float]:
        c = _concept(word)
        out: Dict[str, float] = {}
        if self._instance.get(c):
            out["NAME"] = float(len(self._instance[c]))
        if self._isa.get(c) and c not in self._instance:
            out["NOUN"] = float(len(self._isa[c]))
        return out

    def known_words(self, words: Sequence[str]) -> Mapping[str, str]:
        return dict(self._names(words)) if self._names is not None else {}

    def classes(self, word: str) -> Mapping[str, float]:
        return dict(self._classes(word)) if self._classes is not None else {}


class HeldWords(Words):
    """How each word is used, counted from the analysed sentences given (`structure.Analysed`), each use signed as
    the grammar's entries name them (`closed`: each grammar word's uses), each word named by `name_of(word, class)`,
    and what memory holds of things (`knowledge`)."""

    def __init__(self, analysed: Iterable, closed: Mapping[str, Set[str]], name_of: Callable[[str, str], str],
                 knowledge: Optional[Knowledge] = None, forms: Optional[Any] = None,
                 recorded: Optional[Callable[[str, str], Optional[str]]] = None,
                 written_for: Optional[Callable[[str, str], List[str]]] = None,
                 used_for: Optional[Callable[[str, str], Mapping[str, float]]] = None):
        self.closed = {w: set(u) for w, u in closed.items()}
        #: What memory writes for a thing as a word of a class (`MemoryAgent.words_for`): the other way from `name_of`.
        self.written_for = written_for
        #: How often memory holds each of those words used for that thing (`MemoryAgent.used_for`), which is what
        #: `written_for` orders by: what saying weighs a word for a thing by.
        self.used_by = used_for
        #: What a word recorded whole, or a sentence recorded whole, names a word as a class (`MemoryAgent.recorded_name`):
        #: before any other name (`_name`).
        self.recorded = recorded
        self.name_of = name_of
        #: The forms memory holds words written as (`word_forms.HeldForms`: `forms_of(word)` gives base, class,
        #: features, how often): "came" the past of `come`, "whales" the plural of `whale`.
        self.held_forms = forms
        #: The changes of spelling the forms held make, by class: what a form ends in that its base does not, and
        #: what the base ends in instead ("ged" -> "g": "logged" a form of `log`; "s" -> "": "absorbs" of `absorb`),
        #: the most made first. A word whose forms are not held is a form of the word a change makes of it, where
        #: memory holds that word as a word of the class.
        self.changes: Dict[str, Counter] = defaultdict(Counter)
        for item in (forms.items() if forms is not None and hasattr(forms, "items") else ()):
            for form, features, n in item.forms:
                if "Typo=Yes" in features:
                    continue
                k = 0
                while k < min(len(form), len(item.base)) and form[k] == item.base[k]:
                    k += 1
                if k and form[k:]:
                    self.changes[item.word_class][(form[k:], item.base[k:])] += n
        # Knowledge holding nothing yet is still the knowledge to hold in: `knowledge or Knowledge()` took an empty
        # `GraphKnowledge` (it has a length) for none, and in a store that held no concepts every kind taken in after
        # went nowhere (lyric_dev2, 2026-10-26).
        self.knowledge = knowledge if knowledge is not None else Knowledge()
        self.form_uses: Dict[str, Counter] = defaultdict(Counter)
        #: Each use, how often in a sentence that asks (True) and in one that tells (False), every word together.
        self.asked: Dict[str, Counter] = defaultdict(Counter)
        #: Each use, how often the word after it is a doing's -ing form (True) and how often not, every word together.
        self.before_doing: Dict[str, Counter] = defaultdict(Counter)
        self.forms: Dict[str, Counter] = defaultdict(Counter)
        self.verb_frames: Dict[str, Counter] = defaultdict(Counter)
        self.shapes: Dict[str, Counter] = defaultdict(Counter)
        self.alone: Dict[str, Counter] = defaultdict(Counter)
        #: Each noun and name: how often it heads a thing said of a doing with no preposition (`modifier`: "One
        #: morning the dog ran."), and how often it is used otherwise.
        self.bare: Dict[str, Counter] = defaultdict(Counter)
        self.plurals: Dict[str, Counter] = defaultdict(Counter)
        self.relatives: Counter = Counter()
        self.written: Dict[str, Counter] = defaultdict(Counter)
        self.purposes: Counter = Counter()
        #: Sentences that tell: an order (True: its doing's doer unsaid, "Read the links.") or one saying its doer.
        self.ordered: Counter = Counter()
        self.particles: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        #: Of those, where the clause ended after the two, for a verb of several words recorded whole ("We made it!":
        #: `make it` 5 of 8 times so in SemCor, 5 of 93 where words go on, "made it clear").
        self.particles_ending: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        #: Where an adjective is said of a thing, after it or before it, by whether words follow the adjective in
        #: its phrase ("greater than 1"): `(followed, after)`.
        self.adjective_places: Counter = Counter()
        #: How words joined by a hyphen are used, by kind of word ("high-level" before a noun, its modifier).
        self.hyphened: Counter = Counter()
        #: From words recorded whole (`GrammarView.hold_word`): each form's ways of being said; of forms the analysts
        #: mark nothing apart ("a", "an"), the forms said alike with each and the first sounds said after each; of a
        #: finite form, its subjects by class and the features they share with verbs; every finite form's together;
        #: of a determiner, the nouns it was said with, and every determiner's together; of what a copula said a thing
        #: to be (by its class and those features), the things, every such together.
        self.said: Dict[str, Counter] = defaultdict(Counter)
        self.said_alike: Dict[str, Counter] = defaultdict(Counter)
        self.sounds_after: Dict[str, Counter] = defaultdict(Counter)
        self.subjects_of: Dict[str, Counter] = defaultdict(Counter)
        self.every_subject: Counter = Counter()
        self.nouns_of: Dict[str, Counter] = defaultdict(Counter)
        self.every_noun: Counter = Counter()
        self.predicated_of: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        self.every_predicated: Counter = Counter()
        self.objects_of: Dict[str, Counter] = defaultdict(Counter)
        self.every_object: Counter = Counter()
        self._names: Dict[Tuple[str, str], str] = {}
        self._uses: Dict[str, Mapping[str, float]] = {}
        self.sentences = 0
        for sentence in analysed:
            self._count(sentence)
            self.sentences += 1
        self.alike: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        for what, table in (("uses", self.form_uses), ("forms", self.forms), ("shapes", self.shapes),
                            ("alone", self.alone), ("bare", self.bare)):
            for form, counts in table.items():
                for ending in {form[-3:], form[-2:]}:
                    self.alike[(what, ending)].update(counts)
        for counts in self.verb_frames.values():
            self.alike[("frames", "")].update(counts)

    # ── counting ──
    def _name(self, word: str, cls: str) -> str:
        """A word's name as a word of this class: the word it is a form of (`lexeme`: "built" `build`, "whales"
        `whale`), as WordNet's links name the sense of a word used most (`build`, never `physique`: memory's names
        for a word, `MemoryAgent.name_of`, give a sense another word names, and "air" was `line airline`); for a word
        no form or held word gives, as memory names it."""
        key = (word.lower(), cls)
        if key not in self._names and self.recorded is not None:
            # AS A RECORD NAMES IT, where one does: "medal" as the record's meaning names it, `award decoration`. A
            # word memory held as the class was named by itself first, whatever the record said.
            named = self.recorded(word, cls) or self.recorded(self.lexeme(word, cls), cls)
            if named:
                self._names[key] = named
        if key not in self._names:
            base = self.lexeme(word, cls)
            held = base != word.lower() or bool(self.knowledge.classes(base).get(cls))
            # A WORD OF A CLASS WORDNET DOES NOT NAME IS THE WORD IT IS: memory names a word by WordNet's senses, and
            # WordNet has no prepositions, so the name it gave was another word's sense. On main "for" was `forget`,
            # "in" `inch`, "of" `inactive off` and "to" `excessive`, and what each says was learned under that name
            # (2026-10-21).
            self._names[key] = base if held or (cls not in INFLECTED and cls != "NAME") else self.name_of(word, cls)
        return self._names[key]

    def lexeme(self, word: str, cls: str) -> str:
        """The word `word` is a form of, as a word of this class: the one memory holds it a form of ("whales":
        `whale`, "built": `build`); else the one a change the held forms make gives, where memory holds that word as
        one of the class ("logged": `log`, "detects": `detect`); else the word itself."""
        w = word.lower()
        bases = Counter()
        for base, of_class, _, n in self._forms_of(w):
            if of_class == cls:
                bases[base] += n
        if bases:
            return bases.most_common(1)[0][0]
        if cls in INFLECTED and w.endswith(INFLECTED[cls]):
            # A word memory holds as a word of the class is that word, unless a change makes of it a word memory
            # holds so more firmly ("experiments", held from a lesson, is `experiment`; "physics" stays). Only an
            # ending a form of the class is written with is undone ("eighteen" is no form of `eight`).
            itself = self.knowledge.classes(w).get(cls, 0.0)
            for (removed, add), _ in self.changes.get(cls, Counter()).most_common():
                if not w.endswith(removed) or len(w) - len(removed) < 2:
                    continue
                base = w[:len(w) - len(removed)] + add
                if base == w:
                    continue
                held = self.knowledge.classes(base).get(cls, 0.0) or (
                    0.5 if not itself and self.form_uses.get(base, {}).get(cls) else 0.0)
                if held > itself:
                    return base
        return w

    def _forms_of(self, word: str) -> Sequence[Tuple[str, str, str, int]]:
        """What memory holds the word a form of, a misspelling aside (the treebank wrote "air" for `airway` once)."""
        if self.held_forms is None:
            return ()
        return [f for f in self.held_forms.forms_of(word) if "Typo=Yes" not in f[2]]

    def _family(self, word: str) -> str:
        """Which of the grammar's verbs a grammar word is a form of, by its uses: be, have, do, a modal, or none."""
        uses = self.closed.get(word.lower(), ())
        for family in ("be", "have"):
            if any(u.startswith(family + ":") for u in uses):
                return family
        if "do" in uses or "do:q" in uses:
            return "do"
        if "modal" in uses:
            return "modal"
        return ""

    def _count(self, sentence) -> None:
        words, classes, heads, relations = sentence.words, sentence.classes, sentence.heads, sentence.relations
        n = len(words)
        under: Dict[int, List[int]] = defaultdict(list)
        for i, h in enumerate(heads):
            if h:
                under[h - 1].append(i)
        asks = words[-1] == "?"
        roots = [i for i, h in enumerate(heads) if not h]
        if len(roots) == 1 and not asks:
            # AN ORDER is a doing whose doer is unsaid and nothing helps it ("Read the links.", not "Done." nor "Is
            # it?"); a sentence whose doing says who does it is none. What is neither (a heading, a name) is not
            # counted.
            said = {relations[k].split(":")[0] for k in under[roots[0]]}
            if said & {"nsubj", "csubj", "expl"}:
                self.ordered[False] += 1
            elif classes[roots[0]] == "VERB" and not said & {"aux", "cop"}:
                self.ordered[True] += 1
        for i in range(n):
            if words[i] == "-" and 0 < i < n - 1 and words[i - 1].isalpha() and words[i + 1].isalpha():
                # WORDS JOINED BY A HYPHEN are one word, used as the one of them the rest of the sentence hangs on is;
                # one modifying the noun after it is a modifier, as the grammar reads one: "a high-level language".
                pair = (i - 1, i + 1)
                head = next((k for k in pair if not heads[k] or heads[k] - 1 not in pair), i + 1)
                outer = heads[head] - 1 if heads[head] else None
                if relations[head].split(":")[0] in ("amod", "compound") and outer is not None and outer > i \
                        and classes[outer] in ("NOUN", "NAME"):
                    self.hyphened["ADJECTIVE"] += 1
                else:
                    self.hyphened[self.use_of(words, classes, heads, relations, under, asks, head).split(":")[0]] += 1
            if classes[i] in MARKS:
                continue
            form = words[i].lower()
            use = self.use_of(words, classes, heads, relations, under, asks, i)
            self.form_uses[form][use] += 1
            self.asked[use][asks] += 1
            self.before_doing[use][i + 1 < n and classes[i + 1] == "VERB" and words[i + 1].lower().endswith("ing")] += 1
            if i > 0 and words[i][:1].isupper() and words[i - 1] not in ('"', ":", "``"):
                # As written, inside a sentence: "Norwegian" before a town, "Bill" a name.
                self.written[words[i]][use.split(":")[0]] += 1
            if classes[i] in ("VERB", "AUXILIARY"):
                self.forms[form][self._form_of(words, classes, heads, relations, under, i)] += 1
            if classes[i] == "VERB":
                doing = any(relations[k].split(":")[0] == "xcomp" and classes[k] == "VERB"
                            and words[k].lower().endswith("ing") for k in under[i])
                self.verb_frames[self._name(words[i], "VERB")][
                    _frame_of([relations[k] for k in under[i]], doing)] += 1
                if i + 1 < n and classes[i + 1] not in MARKS:
                    together = heads[i + 1] == i + 1 and relations[i + 1] == "compound:prt"
                    self.particles[(self._name(words[i], "VERB"), words[i + 1].lower())][together] += 1
                if form.endswith("ing") or self._form_of(words, classes, heads, relations, under, i) == "participle":
                    self.shapes[form][_shape_of(relations[i])] += 1
            if classes[i] in ("NOUN", "NAME") and not relations[i].startswith("compound"):
                # A THING SAID OF A DOING WITH NO PREPOSITION ("One morning the dog ran."): the treebank's
                # `obl:unmarked`, `obl:tmod` and `obl:npmod` in its earlier releases.
                self.bare[form]["modifier" if relations[i] in _BARE_OF_A_DOING else "otherwise"] += 1
            if classes[i] == "NOUN" and not relations[i].startswith("compound"):
                determined = any(relations[k] in ("det", "det:poss", "nmod:poss") for k in under[i])
                self.alone[form]["determined" if determined else "bare"] += 1
                self.plurals[form][form != self._name(words[i], "NOUN") and form.endswith("s")] += 1
            if words[i].lower() in self.closed and "to:inf" in self.closed[words[i].lower()] \
                    and classes[i] == "PARTICLE" and heads[i]:
                self.purposes[relations[heads[i] - 1].split(":")[0] == "advcl"] += 1
            if classes[i] == "ADJECTIVE" and relations[i] == "amod" and heads[i]:
                followed = any(k > i and classes[k] not in MARKS for k in under[i])
                self.adjective_places[(followed, heads[i] - 1 < i)] += 1
            if relations[i].startswith("acl:relcl"):
                marked = any(any(u.startswith("rel:") for u in self.closed.get(words[k].lower(), ()))
                             and k < i for k in under[i])
                self.relatives[marked] += 1

    def use_of(self, words, classes, heads, relations, under, asks: bool, i: int) -> str:
        """How the word at i is used where the sentence has it, named as the grammar's entries name their uses, or
        as the kind of word it is."""
        word, cls, relation = words[i].lower(), classes[i], relations[i]
        h = heads[i] - 1 if heads[i] else None
        kids = under.get(i, [])
        uses = self.closed.get(word, set())
        family = self._family(word)
        if family and (cls in ("AUXILIARY", "VERB")):
            head_kids = under.get(h, []) if h is not None and relation in ("aux", "aux:pass", "cop") else kids
            subject = next((k for k in head_kids if relations[k] in ("nsubj", "nsubj:pass", "expl")), None)
            q = "q:" if subject is not None and subject > i and asks else ""
            if family == "be":
                if relation == "aux":
                    return f"be:{q}ng" if h is not None and words[h].lower().endswith("ing") else f"be:{q}aux"
                if relation == "aux:pass":
                    return f"be:{q}pss"
                if relation == "cop" and h is not None:
                    if classes[h] == "ADJECTIVE":
                        return f"be:{q}adj"
                    if any(relations[k] == "case" for k in under.get(h, [])) or classes[h] == "ADVERB":
                        return f"be:{q}pp"
                    return f"be:{q}np"
                if any(relations[k] == "expl" for k in kids):
                    there = next(k for k in kids if relations[k] == "expl")
                    asked = "q:" if there > i and asks else ""
                    return f"be:{asked}there:pp" if any(relations[k].startswith("obl") for k in kids) else \
                        f"be:{asked}there"
                return f"be:{q}pp"
            if family == "have":
                return f"have:{q}perfect" if relation == "aux" else "have:owns"
            if family == "do":
                if relation == "aux":
                    return "do:q" if q else ("do" if subject is not None else "do:order")
                return "VERB"
            return "modal:q" if q else "modal"
        if relation == "cc":
            return "conj"
        if "neg" in uses and relation in ("advmod", "neg"):
            return "neg"
        if cls in ("PRONOUN", "DETERMINER", "ADVERB") and h is not None and relations[h].startswith("acl:relcl") \
                and any(u.startswith("rel:") for u in uses):
            return "rel:subject" if relation.startswith("nsubj") else "rel:object"
        if asks and any(u.startswith("wh:") for u in uses):
            if relation == "det":
                return "wh:det"
            if relation.startswith("nsubj"):
                return "wh:subject"
            if cls == "ADVERB":
                return "wh:adverb"
            return "wh:object"
        if relation in ("det", "det:poss") or (relation == "nmod:poss" and cls in ("PRONOUN", "DETERMINER")):
            return "det"
        if relation == "expl":
            return "expl"
        if cls == "PRONOUN":
            return "pron"
        if cls == "PARTICLE" and "to:inf" in uses:
            return "to:inf"
        if cls == "PARTICLE" and "poss" in uses:
            return "poss"
        if relation == "compound:prt":
            return "PARTICLE"
        if cls == "SUBORDINATOR":
            if "mark:purpose" in uses and relation == "mark" and h is not None and classes[h] == "VERB" \
                    and words[h].lower().endswith("ing") and relations[h].startswith("acl"):
                # "a place for getting an education": what the thing is for (`mark:purpose`).
                return "mark:purpose"
            return "comp" if h is not None and relations[h] == "ccomp" else "sub"
        if cls == "PREPOSITION" and h is not None:
            if relations[h] == "obl:agent":
                return "case:agent"
            up = heads[h] - 1 if heads[h] else None
            if "case:part" in uses and relations[h].startswith("nmod") and up is not None and classes[up] == "NUMERAL":
                return "case:part"
            if relations[h].startswith("nmod") or relations[h] == "acl":
                return "PREPOSITION:thing"
            if any(relations[k] == "cop" for k in under.get(h, [])):
                return "PREPOSITION:said"
            if up is not None and classes[up] == "ADJECTIVE":
                return "PREPOSITION:quality"
            return "PREPOSITION"
        if cls == "ADVERB" and h is not None and classes[h] in ("ADJECTIVE", "ADVERB") and relation == "advmod":
            return "ADVERB:degree"
        if cls == "NUMERAL" and relation != "nummod":
            # "Two of them": that many of them, said by the numeral and what its "of" names (`case:part`).
            if any(relations[k].startswith("nmod") and any(
                    relations[c] == "case" and "case:part" in self.closed.get(words[c].lower(), ())
                    for c in under.get(k, [])) for k in kids):
                return "NUMERAL:partitive"
            return "NUMERAL:alone"
        if cls == "NOUN" and relation == "compound":
            return "NOUN:compound"
        if cls == "ADJECTIVE" and relation == "amod":
            return "ADJECTIVE:before"
        return KINDS.get(cls, "GRAMMAR")

    def _form_of(self, words, classes, heads, relations, under, i: int) -> str:
        """Which form of its verb the word at i is, as the sentence uses it: -ing, a participle (after "have" or
        "be" passive, or before a thing), the third person, the base (after a modal, "do", "to", or ordering), the
        present, or the past."""
        word = words[i].lower()
        kids = under.get(i, [])
        if word.endswith("ing"):
            return "ing"
        if any(relations[k] in ("aux:pass", "nsubj:pass") for k in kids) or relations[i] in ("amod", "acl") or any(
                relations[k] == "aux" and self._family(words[k]) == "have" for k in kids):
            return "participle"
        name = self._name(words[i], "VERB")
        if word == name:
            if any(relations[k] in ("aux", "mark") for k in kids) or not any(
                    relations[k].startswith("nsubj") for k in kids):
                return "base"
            return "present"
        if word.endswith("s") and not word.endswith("ss"):
            return "third"
        return "past"

    # ── as the grammar asks ──
    def uses(self, word: str) -> Mapping[str, float]:
        if word not in self._uses:
            self._uses[word] = self._uses_of(word)
        return self._uses[word]

    def _uses_of(self, word: str) -> Mapping[str, float]:
        w = word.lower()
        counts = {c: float(n) for c, n in self.form_uses.get(w, {}).items()}
        held = {c: n for c, n in self.knowledge.classes(word).items() if c in KINDS.values()}
        for c in ("NOUN", "VERB", "ADJECTIVE", "ADVERB"):
            # A form of a word memory holds as a word of a class is one too ("Whales", "logged").
            if c not in held and self.lexeme(word, c) != w:
                held[c] = 0.0
        if not counts:
            if not held and self.closed.get(w):
                # A WORD OF THE GRAMMAR'S OWN no sentence held is used as the grammar uses it, capitalised or not:
                # "Who" opening "Who fastened the medal?" was a name, in a store taught one sentence that had no
                # "who" (TRAIN-FORMAT-01, lyric_dev2, 2026-10-26).
                return {c: 0.0 for c in self.closed[w]}
            if not held and word[:1].isupper():
                # A capitalised word nothing holds is a name.
                return {"NAME": 1.0}
            if held:
                return {c: 0.0 for c in held}
            return {c: 0.0 for c in self.like(w, "uses") if c in ("NOUN", "VERB", "ADJECTIVE", "ADVERB", "NUMERAL")}
        for c in held:
            counts.setdefault(c, 0.0)
        return counts

    def name(self, word: str, cls: str) -> str:
        if cls == "NUMERAL":
            from core.semantics.literals import classify_literal
            literal = classify_literal(word)
            if literal is not None and literal.kind == "cardinal":
                return literal.canonical
        return self._name(word, cls)

    def spelled(self, word: str) -> Optional[str]:
        parts = word.lower().split("-")
        for spelled in dict.fromkeys(("-".join(parts), "".join(parts), " ".join(parts))):
            # Held as a word: a sentence held used it, memory holds it as a word of a class, or it is a form of one
            # ("window-sills", of `windowsill`).
            if self.form_uses.get(spelled) or self.knowledge.classes(spelled) or any(
                    self.lexeme(spelled, c) != spelled for c in ("NOUN", "VERB", "ADJECTIVE", "ADVERB")):
                return spelled
        return None

    def verb_forms(self, word: str) -> Mapping[str, float]:
        """How often the word is each form of its verb: as the forms memory holds say (their features), else as the
        sentences held use it."""
        held: Counter = Counter()
        for _, cls, features, n in self._forms_of(word):
            if cls == "VERB":
                held[_verb_form(features)] += n
        if held:
            return {f: float(n) for f, n in held.items() if f}
        return {f: float(n) for f, n in self.forms.get(word.lower(), {}).items()}

    def frames(self, name: str) -> Mapping[str, float]:
        return {f: float(n) for f, n in self.verb_frames.get(name, {}).items()}

    def like(self, word: str, what: str) -> Mapping[str, float]:
        if what == "frames":
            return self.alike[("frames", "")]
        w = word.lower()
        if what == "uses" and "-" in w.strip("-"):
            # A word joined by a hyphen is used as words joined by a hyphen are, not as words ending as its last
            # part does: "high-level" is no noun as "level" is, and read as one, "a high-level, general-purpose
            # programming language" was two things (UNDERSTANDS-PROSE-01 on main, 2026-10-21).
            return self.hyphened
        three = self.alike.get((what, w[-3:]))
        if three and sum(three.values()) >= 50:
            return three
        return self.alike.get((what, w[-2:]), {})

    def verb_shapes(self, word: str) -> Mapping[str, float]:
        return {k: float(n) for k, n in self.shapes.get(word.lower(), {}).items()}

    def degree(self, word: str) -> Optional[str]:
        said = Counter()
        for _, cls, features, n in self._forms_of(word):
            if cls == "ADJECTIVE":
                said["more" if "Degree=Cmp" in features else "most" if "Degree=Sup" in features else ""] += n
        return said.most_common(1)[0][0] or None if said else None

    def noun_alone(self, word: str) -> Mapping[str, float]:
        return {k: float(n) for k, n in self.alone.get(word.lower(), {}).items()}

    def bare_modifier(self, word: str) -> Mapping[str, float]:
        return {k: float(n) for k, n in self.bare.get(word.lower(), {}).items()}

    def hear_read(self, uses: Iterable[Tuple[str, str]], verbs: Iterable[Tuple[str, str, str, str]],
                  weight: float) -> None:
        """How a sentence Lyric read used its words, counted beside the treebank's uses, as much as the reading was
        sure (`GrammarView._learn_from_reading`): each word's use, and words written alike (`like`); each verb's form
        and frame. A word met only in reading is a word of the kind it was read as from then on."""
        if weight <= 0:
            return
        touched = set()
        for form, use in uses:
            self.form_uses[form][use] += weight
            for ending in {form[-3:], form[-2:]}:
                self.alike[("uses", ending)][use] += weight
            touched.add(form)
        for form, name, verb_form, frame in verbs:
            self.forms[form][verb_form] += weight
            self.verb_frames[name][frame] += weight
            self.alike[("frames", "")][frame] += weight
        if touched:
            self._uses = {w: u for w, u in self._uses.items() if w.lower() not in touched}

    def hear_kind(self, subject: str, relation: str, kind: str) -> None:
        self.knowledge.add(subject, relation, kind)

    def bare_relatives(self) -> Tuple[float, float]:
        return float(self.relatives[False]), float(self.relatives[True])

    def doing_after(self, use: str) -> Tuple[float, float]:
        held = self.before_doing.get(use, {})
        return float(held.get(True, 0)), float(held.get(False, 0))

    def asking(self, use: str) -> Tuple[float, float]:
        held = self.asked.get(use, {})
        return float(held.get(True, 0)), float(held.get(False, 0))

    def to_purposes(self) -> Tuple[float, float]:
        return float(self.purposes[True]), float(self.purposes[False])

    def orders(self) -> Tuple[float, float]:
        return float(self.ordered[True]), float(self.ordered[False])

    def adjectives_after(self, followed: bool = False) -> Tuple[float, float]:
        return (float(self.adjective_places[(followed, True)]), float(self.adjective_places[(followed, False)]))

    def said_together(self, verb: str, word: str, ends: Optional[bool] = None) -> Tuple[float, float]:
        held = self.particles.get((verb, word.lower()), {})
        one, apart = float(held.get(True, 0)), float(held.get(False, 0))
        ending = self.particles_ending.get((verb, word.lower()))
        if ends is None or not ending:
            return one, apart
        one_ending, apart_ending = float(ending.get(True, 0)), float(ending.get(False, 0))
        return (one_ending, apart_ending) if ends else (one - one_ending, apart - apart_ending)

    def plural(self, word: str) -> bool:
        said = [n for _, cls, features, n in self._forms_of(word) if cls == "NOUN" and "Number=Plur" in features]
        if said:
            return True
        held = self.plurals.get(word.lower())
        return bool(held) and held[True] > held[False]

    def sounds(self, word: str) -> List[str]:
        return [way for way, n in self.said.get(word.lower(), {}).items() if n > 0]

    def said_before(self, word: str) -> Mapping[str, Mapping[str, float]]:
        alike = [form for form, n in self.said_alike.get(word.lower(), {}).items() if n > 0]
        return {form: {s: float(n) for s, n in self.sounds_after.get(form, {}).items() if n > 0} for form in alike}

    def subjects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
        held = self.every_subject if word is None else self.subjects_of.get(word.lower(), {})
        return {k: float(n) for k, n in held.items() if n > 0}

    def took_subjects(self) -> Tuple[str, ...]:
        return tuple(word for word, held in self.subjects_of.items() if any(n > 0 for n in held.values()))

    def nouns(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
        held = self.every_noun if word is None else self.nouns_of.get(word.lower(), {})
        return {k: float(n) for k, n in held.items() if n > 0}

    def predicated(self, said: Optional[Tuple[str, str]] = None) -> Mapping[Tuple[str, str], float]:
        held = self.every_predicated if said is None else self.predicated_of.get(said, {})
        return {k: float(n) for k, n in held.items() if n > 0}

    def objects(self, word: Optional[str] = None) -> Mapping[Tuple[str, str], float]:
        held = self.every_object if word is None else self.objects_of.get(word.lower(), {})
        return {k: float(n) for k, n in held.items() if n > 0}

    def form_features(self, word: str, cls: str) -> Mapping[str, float]:
        out: Counter = Counter()
        for _, of_class, features, n in self._forms_of(word):
            if of_class == cls:
                out[features] += n
        return {f: float(n) for f, n in out.items() if n > 0}

    def known_words(self, words: Sequence[str]) -> Mapping[str, str]:
        return self.knowledge.known_words(words)

    def known_name(self, words: Sequence[str]) -> Optional[str]:
        return self.knowledge.known_name(words)

    def known_verb(self, words: Sequence[str]) -> Optional[str]:
        return self.knowledge.known_verb(words)

    def words_for(self, name: str, cls: str) -> List[str]:
        return list(self.written_for(name, cls)) if self.written_for is not None else []

    def used_for(self, name: str, cls: str) -> Mapping[str, float]:
        return dict(self.used_by(name, cls)) if self.used_by is not None else {}

    def kinds(self, name: str, cls: str) -> List[str]:
        return self.knowledge.kinds(name, cls)

    def defined(self, name: str) -> List[str]:
        return self.knowledge.defined(name)

    def is_person(self, name: str, particular: bool = False) -> Optional[bool]:
        return self.knowledge.is_person(name, particular)

    def is_time(self, term: str) -> Optional[str]:
        return self.knowledge.is_time(term)

    def capitalized(self, word: str) -> Mapping[str, float]:
        """How the word written capitalised inside a sentence is used ("Norwegian" an adjective, "Bill" a name), and
        what memory holds it to be: a particular one (a name) or a kind."""
        out = {c: float(n) for c, n in self.written.get(word, {}).items() if c in KINDS.values()}
        for c, n in self.knowledge.capitalized(word).items():
            out[c] = out.get(c, 0.0) + n
        return out


def _verb_form(features: str) -> str:
    """Which form of its verb a treebank's features say a word is."""
    f = set(features.split("|"))
    if "VerbForm=Ger" in f or ("VerbForm=Part" in f and "Tense=Pres" in f):
        return "ing"
    if "VerbForm=Part" in f:
        return "participle"
    if "VerbForm=Fin" in f and "Tense=Past" in f:
        return "past"
    if "Person=3" in f and "Tense=Pres" in f:
        return "third"
    if "VerbForm=Inf" in f:
        return "base"
    if "Tense=Pres" in f:
        return "present"
    return ""


def _frame_of(relations: Sequence[str], doing: bool = False) -> str:
    """A verb's frame from the relations of the words under it; `doing`, the clause it takes is said by an -ing word
    ("began working on Python"), whose doer is the verb's own as a "to" clause's is ("began to work"). Counted as a
    "to" clause, no reading took it, and "began working" was a beginning of some work no one did."""
    rels = {r.split(":")[0] for r in relations}
    if "ccomp" in rels:
        return "that"
    if "xcomp" in rels:
        if doing and "obj" not in rels:
            return "ing"
        return "told to" if "obj" in rels else "to"
    if "iobj" in rels and "obj" in rels:
        return "ditransitive"
    if "obj" in rels or "nsubj:pass" in relations:
        return "transitive"
    return "intransitive"


def _shape_of(relation: str) -> str:
    """How a doing said by an -ing or -ed word stands: as a thing, after a thing it tells of, before one, or as a
    doing."""
    if relation.split(":")[0] in ("nsubj", "obj", "iobj", "obl", "nmod", "csubj"):
        return "thing"
    if relation.split(":")[0] == "acl" and not relation.startswith("acl:relcl"):
        return "after"
    if relation == "amod":
        return "before"
    return "doing"
