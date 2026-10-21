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


class Knowledge:
    """What memory holds of things, as the grammar asks it. Every answer is plain where nothing is held."""

    def kinds(self, name: str, cls: str) -> List[str]:
        """What the word's thing is a kind of, nearest first; for an adjective, what its definition is written with
        and what that is a kind of."""
        return []

    def is_person(self, name: str) -> bool:
        return False

    def is_time(self, term: str) -> Optional[str]:
        return None

    def capitalized(self, word: str) -> Mapping[str, float]:
        return {}

    def known_name(self, words: Sequence[str]) -> Optional[str]:
        return None

    def known_verb(self, words: Sequence[str]) -> Optional[str]:
        return None

    def classes(self, word: str) -> Mapping[str, float]:
        """The kinds of word memory holds the word as, for a word no sentence held used."""
        return {}


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

    `known_name(words)` and `known_verb(words)` ask `names(words, cls)` (memory's names of several words)."""

    def __init__(self, classes: Optional[Callable[[str], Mapping[str, float]]] = None,
                 names: Optional[Callable[[Sequence[str], str], Optional[str]]] = None):
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

    def is_person(self, name: str) -> bool:
        return "person" in self.kinds(name, "NOUN")

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

    def known_name(self, words: Sequence[str]) -> Optional[str]:
        return self._names(words, "NOUN") if self._names is not None else None

    def known_verb(self, words: Sequence[str]) -> Optional[str]:
        return self._names(words, "VERB") if self._names is not None else None

    def classes(self, word: str) -> Mapping[str, float]:
        return dict(self._classes(word)) if self._classes is not None else {}


class HeldWords(Words):
    """How each word is used, counted from the analysed sentences given (`structure.Analysed`), each use signed as
    the grammar's entries name them (`closed`: each grammar word's uses), each word named by `name_of(word, class)`,
    and what memory holds of things (`knowledge`)."""

    def __init__(self, analysed: Iterable, closed: Mapping[str, Set[str]], name_of: Callable[[str, str], str],
                 knowledge: Optional[Knowledge] = None, forms: Optional[Any] = None):
        self.closed = {w: set(u) for w, u in closed.items()}
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
        self.knowledge = knowledge or Knowledge()
        self.form_uses: Dict[str, Counter] = defaultdict(Counter)
        self.forms: Dict[str, Counter] = defaultdict(Counter)
        self.verb_frames: Dict[str, Counter] = defaultdict(Counter)
        self.shapes: Dict[str, Counter] = defaultdict(Counter)
        self.alone: Dict[str, Counter] = defaultdict(Counter)
        self.plurals: Dict[str, Counter] = defaultdict(Counter)
        self.relatives: Counter = Counter()
        self.written: Dict[str, Counter] = defaultdict(Counter)
        self.purposes: Counter = Counter()
        self.particles: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        self.adjective_places: Counter = Counter()
        self._names: Dict[Tuple[str, str], str] = {}
        self._uses: Dict[str, Mapping[str, float]] = {}
        self.sentences = 0
        for sentence in analysed:
            self._count(sentence)
            self.sentences += 1
        self.alike: Dict[Tuple[str, str], Counter] = defaultdict(Counter)
        for what, table in (("uses", self.form_uses), ("forms", self.forms), ("shapes", self.shapes),
                            ("alone", self.alone)):
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
        if key not in self._names:
            base = self.lexeme(word, cls)
            held = base != word.lower() or bool(self.knowledge.classes(base).get(cls))
            self._names[key] = base if held else self.name_of(word, cls)
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
        for i in range(n):
            if classes[i] in MARKS:
                continue
            form = words[i].lower()
            use = self.use_of(words, classes, heads, relations, under, asks, i)
            self.form_uses[form][use] += 1
            if i > 0 and words[i][:1].isupper() and words[i - 1] not in ('"', ":", "``"):
                # As written, inside a sentence: "Norwegian" before a town, "Bill" a name.
                self.written[words[i]][use.split(":")[0]] += 1
            if classes[i] in ("VERB", "AUXILIARY"):
                self.forms[form][self._form_of(words, classes, heads, relations, under, i)] += 1
            if classes[i] == "VERB":
                self.verb_frames[self._name(words[i], "VERB")][_frame_of([relations[k] for k in under[i]])] += 1
                if i + 1 < n and classes[i + 1] not in MARKS:
                    together = heads[i + 1] == i + 1 and relations[i + 1] == "compound:prt"
                    self.particles[(self._name(words[i], "VERB"), words[i + 1].lower())][together] += 1
                if form.endswith("ing") or self._form_of(words, classes, heads, relations, under, i) == "participle":
                    self.shapes[form][_shape_of(relations[i])] += 1
            if classes[i] == "NOUN" and not relations[i].startswith("compound"):
                determined = any(relations[k] in ("det", "det:poss", "nmod:poss") for k in under[i])
                self.alone[form]["determined" if determined else "bare"] += 1
                self.plurals[form][form != self._name(words[i], "NOUN") and form.endswith("s")] += 1
            if words[i].lower() in self.closed and "to:inf" in self.closed[words[i].lower()] \
                    and classes[i] == "PARTICLE" and heads[i]:
                self.purposes[relations[heads[i] - 1].split(":")[0] == "advcl"] += 1
            if classes[i] == "ADJECTIVE" and relations[i] == "amod" and heads[i]:
                self.adjective_places[heads[i] - 1 < i] += 1
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
            return "comp" if h is not None and relations[h] == "ccomp" else "sub"
        if cls == "PREPOSITION" and h is not None:
            if relations[h] == "obl:agent":
                return "case:agent"
            up = heads[h] - 1 if heads[h] else None
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

    def bare_relatives(self) -> Tuple[float, float]:
        return float(self.relatives[False]), float(self.relatives[True])

    def to_purposes(self) -> Tuple[float, float]:
        return float(self.purposes[True]), float(self.purposes[False])

    def adjectives_after(self) -> Tuple[float, float]:
        return float(self.adjective_places[True]), float(self.adjective_places[False])

    def said_together(self, verb: str, word: str) -> Tuple[float, float]:
        held = self.particles.get((verb, word.lower()), {})
        return float(held.get(True, 0)), float(held.get(False, 0))

    def plural(self, word: str) -> bool:
        said = [n for _, cls, features, n in self._forms_of(word) if cls == "NOUN" and "Number=Plur" in features]
        if said:
            return True
        held = self.plurals.get(word.lower())
        return bool(held) and held[True] > held[False]

    def known_name(self, words: Sequence[str]) -> Optional[str]:
        return self.knowledge.known_name(words)

    def known_verb(self, words: Sequence[str]) -> Optional[str]:
        return self.knowledge.known_verb(words)

    def kinds(self, name: str, cls: str) -> List[str]:
        return self.knowledge.kinds(name, cls)

    def is_person(self, name: str) -> bool:
        return self.knowledge.is_person(name)

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


def _frame_of(relations: Sequence[str]) -> str:
    """A verb's frame from the relations of the words under it."""
    rels = {r.split(":")[0] for r in relations}
    if "ccomp" in rels:
        return "that"
    if "xcomp" in rels:
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
