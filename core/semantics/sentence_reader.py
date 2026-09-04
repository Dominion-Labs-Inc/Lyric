#!/usr/bin/env python3
"""Reading a sentence into structure. SEMANTICS OWNS THIS.

MOVED OUT OF `core/reasoning/neural_bridge.py` on 2026-08-24, where 619 lines of
English patterns had grown inside the reasoning module. Reasoning should CONSUME
a reading, not implement one, and language is this faculty's job -- the learned
reader, the lexicon, the claim shapes and the sentence machine all already live
here.

WHAT THIS IS, AND WHAT IT IS NOT. These are hand-written patterns, and they are
scaffolding. The substrate's own reader is DERIVED -- learned from
sentence/meaning pairs, in `derived_reader` and `reading_registry` -- and
measured broader than these on the forms both attempt, while correctly refusing
what it cannot represent. The intended direction is that the derived reading
takes over and this shrinks toward nothing.

It has not been removed because it has not been replaced: these patterns also
cover universals, conditionals, questions and conjunctions, and what share of
those the derived reading handles is unmeasured. Deleting on an unmeasured
assumption would trade working coverage for a silent gap.

WHAT A READING IS. A sentence in, a structure out, or None. It decides only WHAT
a sentence relates -- never whether the formal grammar can carry that relation,
which is genericity's separate stage, and never how to render it for a solver,
which is the reasoning side's job.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.reasoning.reasoning_interfaces import Connectivity  # noqa: F401
from core.semantics import lexical_normalization as _lexical
from core.semantics.genericity import (Genericity, classify_genericity,
                                       unrepresentable_reason, _word_class)

logger = logging.getLogger(__name__)


class SentenceReader:
    """Turns a bounded slice of English into structure. Needs no model."""

    _ARTICLES = ("a ", "an ", "the ")
    _DETERMINER = r"(?:(?P<det>a|an|the)\s+)?"
    _COPULA = r"(?:is|are)"
    #: A subject may be a MULTI-WORD name, not just one token: "the Klein
    #: four-group", "the exponential function", "Kubernetes" (a brand), "New
    #: York". Up to four space-separated tokens (each may carry an internal
    #: hyphen), matched non-greedily so it stops at the copula -- the copula is
    #: the boundary between a subject phrase and what is said of it. The
    #: four-word cap mirrors the store's admissibility (a longer run is a clause,
    #: not a name).
    _SUBJ = r"(?P<subject>[\w'-]+(?:\s+[\w'-]+){0,3}?)"
    _FACT = re.compile(
        rf"^{_DETERMINER}{_SUBJ}\s+{_COPULA}\s+(?P<prop>.+)$",
        re.IGNORECASE,
    )
    _NEGATED_FACT = re.compile(
        rf"^{_DETERMINER}{_SUBJ}\s+{_COPULA}\s+not\s+(?P<prop>.+)$",
        re.IGNORECASE,
    )
    _SVO = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<verb>[\w'-]+)\s+"
        rf"(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+)$", re.IGNORECASE)
    _PREPOSITIONS = ("in", "on", "under", "inside", "above", "below",
                     "near", "behind")
    _PREPOSITIONAL = re.compile(
        r"^(?P<prep>in|on|under|inside|above|below|near|behind)\s+"
        r"(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+(?:\s+[\w'-]+)*)$",
        re.IGNORECASE)
    _SV = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<verb>[\w'-]+)$",
        re.IGNORECASE)
    #: `the battle happened in 1066`, `water flows through the pipe`. An action
    #: with a prepositional phrase -- a subject, a verb, and the thing the verb
    #: reaches THROUGH a preposition. The copular locative (`the cup is in the
    #: box`) is already read above; this is its lexical-verb counterpart, and it
    #: is where a date or a number most naturally appears in a sentence ("in
    #: 1066", "on 2026-08-26"). The object admits digits, dots, slashes and
    #: hyphens so a literal survives, and runs to at most three words.
    _SVO_PREP = re.compile(
        rf"^{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<verb>[\w'-]+)\s+"
        rf"(?P<prep>in|on|at|by|under|inside|above|below|near|behind|through|"
        rf"over|during|into|onto|from|to)\s+"
        rf"(?:(?:a|an|the)\s+)?(?P<object>[\w./'-]+(?:\s+[\w./'-]+){{0,2}})$",
        re.IGNORECASE)
    _UNIVERSAL = re.compile(
        r"^(?:all|every)\s+(?P<p>[\w\s'-]+?)\s+(?:are|is)\s+(?P<q>[\w\s'-]+)$",
        re.IGNORECASE,
    )
    _NEGATIVE_UNIVERSAL = re.compile(
        r"^no\s+(?P<p>[\w\s'-]+?)\s+(?:are|is)\s+(?P<q>[\w\s'-]+)$", re.IGNORECASE
    )
    _CONDITIONAL = re.compile(
        r"^if\s+(?P<antecedent>.+?)[,]?\s+then\s+(?P<consequent>.+)$", re.IGNORECASE
    )
    _QUESTION = re.compile(
        rf"^is\s+{_DETERMINER}{_SUBJ}\s+(?P<prop>.+?)\s*\?*$",
        re.IGNORECASE,
    )
    #: "Does the tank overflow?" / "Do the pumps run?" — a yes/no question about
    #: an ACTION, the counterpart of `_QUESTION` for the copular form. Without it
    #: only "is X Y?" could be asked, so an action consequent could be proved but
    #: never queried.
    _DOES_QUESTION = re.compile(
        rf"^(?:does|do|did)\s+{_DETERMINER}(?P<subject>[\w'-]+)\s+(?P<verb>[\w'-]+)"
        rf"(?:\s+(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+))?\s*\?*$",
        re.IGNORECASE,
    )
    def _normalize(self, phrase: str) -> str:
        """Reduce a phrase to a snake_case atom fragment.

        Delegates orthography to the shared lexical layer. This used to be a
        private implementation that only lowercased and stripped articles,
        while concept identity normalised through a singularising one -- so the
        substrate's logic believed `men != man` while its concept store
        believed `men == man`, and the canonical syllogism could not be proved.
        """
        cleaned = phrase.strip().rstrip("?.!,")
        for article in self._ARTICLES:
            if cleaned.lower().startswith(article):
                cleaned = cleaned[len(article):]
                break
        return _lexical.normalise(cleaned)
    def _singular(self, word: str) -> str:
        """Fold a plural onto its singular via the shared morphology.

        Deliberately `singularise` and not `canonical_label`: the latter also
        strips qualifier tails and acronym restatements, which are concept-
        IDENTITY policy -- claims that lithium_iron_phosphate_battery and
        lithium_iron_phosphate are the same thing. That is synonymy, and
        synonymy must come from alias evidence, not from a string function
        applied to a logical predicate.
        """
        return _lexical.singularise(word)
    def _atom(self, subject: str, prop: str) -> str:
        return f"{self._normalize(subject)}_{self._singular(self._normalize(prop))}"
    def _parse_statement(self, text: str) -> Optional[Dict[str, Any]]:
        """Classify one sentence, or return None if it is outside the slice."""
        sentence = text.strip().rstrip(".")
        if not sentence:
            return None

        match = self._CONDITIONAL.match(sentence)
        if match:
            antecedent = self._parse_statement(match.group("antecedent"))
            consequent = self._parse_statement(match.group("consequent"))
            if not antecedent or not consequent:
                return None
            # A conditional relates two CLAIMS, and a claim need not be copular:
            # "if the pump runs then the tank overflows" has an action on each
            # side. Both sides need only be readable to a single atom (fact,
            # action, or relation); an unrepresentable side (an existential, a
            # bare preposition) still refuses, because a rule over something the
            # grammar cannot carry is not a rule it can reason with.
            if self.render_clause(antecedent) is None or \
                    self.render_clause(consequent) is None:
                return None
            return {"kind": "conditional", "antecedent": antecedent, "consequent": consequent}

        match = self._NEGATIVE_UNIVERSAL.match(sentence)
        if match:
            return {
                "kind": "universal",
                "p": match.group("p"),
                "q": match.group("q"),
                "negated": True,
            }

        match = self._UNIVERSAL.match(sentence)
        if match:
            return {
                "kind": "universal",
                "p": match.group("p"),
                "q": match.group("q"),
                "negated": False,
            }

        match = self._NEGATED_FACT.match(sentence)
        if match:
            return self._read_copular(match, negated=True)

        match = self._FACT.match(sentence)
        if match:
            return self._read_copular(match, negated=False)

        # An action reaching its object through a preposition. Tried before the
        # bare SVO/SV, since "battle happened in 1066" has a prepositional phrase
        # where SVO expects a single object. The verb is anchored the same way
        # as SVO -- a known VERB, or a known NOUN subject standing before it --
        # so nothing is read from an all-unknown sentence. The relation carries
        # the verb AND the preposition ("happened in"), which is what tells
        # `flows through` apart from `flows into`.
        match = self._SVO_PREP.match(sentence)
        if match:
            if self._reads_as_verb(match.group("subject"), match.group("verb").lower()):
                return {"kind": "svo", "subject": match.group("subject"),
                        "verb": f"{match.group('verb').lower()} {match.group('prep').lower()}",
                        "object": match.group("object")}

        # SVO / SV last, and only when the LEXICON identifies the verb.
        #
        # Tried after the copular forms because "the vault is locked" also
        # matches the SVO shape token-for-token; `is` is simply not a verb the
        # lexicon carries. Nothing here guesses: a sentence whose middle word
        # has no established class produces NO reading, which is the honest
        # answer for a word the substrate has not learned.
        for pattern, kind in ((self._SVO, "svo"), (self._SV, "sv")):
            match = pattern.match(sentence)
            if not match:
                continue
            verb = match.group("verb").lower()
            if not self._reads_as_verb(match.group("subject"), verb):
                continue
            groups = match.groupdict()
            if kind == "svo":
                return {"kind": "svo", "subject": groups["subject"],
                        "verb": verb, "object": groups["object"]}
            return {"kind": "sv", "subject": groups["subject"], "verb": verb}

        return None
    def _reads_as_verb(self, subject: str, verb: str) -> bool:
        """Whether the word in the verb slot may be read as the action.

        A KNOWN VERB is one. A known ADJECTIVE never is. A word whose de-inflected
        form is a known VERB is one too -- `chased` reads as the verb `chase`
        even though a catalogue also files `chased` as a noun -- which is what
        lets a sentence built from taught base forms read without teaching every
        tense. A known NOUN that is NOT an inflected verb is not the action.

        THE KNOWN WORDS AROUND IT IDENTIFY THE VERB. A word with no class at all
        is read as the verb only when the subject is a known NOUN: the thing the
        sentence is about anchors the word after it as the action, which is how a
        learner meets a new verb. No anchor, no reading -- this never guesses
        from an all-unknown sentence."""
        cls = _word_class(verb)
        if cls == "VERB":
            return True
        if cls == "ADJECTIVE":
            return False
        from core.semantics.lexical_normalization import deinflect_verb
        if any(_word_class(base) == "VERB" for base in deinflect_verb(verb)):
            return True
        if cls == "NOUN":
            return False
        return _word_class(subject) == "NOUN"

    def _read_copular(self, match, *, negated: bool) -> Dict[str, Any]:
        """Classify a copular sentence BEFORE deciding how to represent it.

        The article alone is not a quantification cue. Reading "a" as universal
        turns "A robin is in the yard" into a law about all robins, so the
        proposition type is decided first and the representation follows from
        it.
        """
        subject = match.group("subject")
        prop = match.group("prop")
        determiner = match.groupdict().get("det")

        # THE LEXICON DISCRIMINATES THE COPULAR FORM TOO.
        #
        # Pattern alone cannot separate "the tank is heavy" from "the cold is
        # heavy": both are `det WORD is WORD`. So both read, and noun and
        # adjective were indistinguishable -- which is why classifying the nine
        # held-out words scored 0/9 with every one fitting BOTH frames.
        #
        # A subject must not be a known ADJECTIVE, and a property must not be a
        # known NOUN. Only KNOWN classes reject: a word the substrate has not
        # learned still reads exactly as before, so this adds discrimination
        # where teaching has happened and takes none away where it has not.
        # That is what makes the frames a measurement instead of a formality.
        if _word_class(subject) == "ADJECTIVE":
            return {"kind": "unsupported",
                    "reason": "an adjective cannot be the subject of a fact",
                    "genericity": "n/a", "cue": f"{subject} is a known adjective"}
        # A PREPOSITION IS A RELATION, NOT A PROPERTY.
        #
        # "the valve is in the pump" read as `valve_in_the_pump`: one atom, with
        # the determiner inside it. Structurally false -- it says the valve has
        # a property called "in the pump", so nothing can ask what the valve is
        # in, and `valve_in_the_pump` and `valve_in_the_tank` share nothing.
        # Both things related are nouns, and the relation between them is what
        # the sentence is for.
        # A PREPOSITION WITH NOTHING TO RELATE TO IS NOT A PROPERTY.
        # "the cup is in" read as the property `in`. A relation needs both
        # things; missing one is a sentence with no reading.
        first = prop.strip().split()[0].lower() if prop.strip() else ""
        if first in self._PREPOSITIONS and not self._PREPOSITIONAL.match(prop.strip()):
            return {"kind": "unsupported",
                    "reason": "a preposition with nothing to relate to",
                    "genericity": "n/a", "cue": prop}

        relation = self._PREPOSITIONAL.match(prop.strip())
        if relation:
            other = relation.group("object")
            if _word_class(other) == "ADJECTIVE":
                return {"kind": "unsupported",
                        "reason": "a preposition relates two things, and an "
                                  "adjective is not a thing",
                        "genericity": "n/a", "cue": f"{other} is a known adjective"}

            # WHICH ONE IS IN THE YARD? A relation needs a subject that DENOTES
            # something, and an indefinite subject does not.
            #
            # This branch returned a relation without ever classifying the
            # sentence -- genericity was checked further down and never reached
            # once a preposition matched. So "A robin is in the yard" became
            # `in(robin, yard)`, reading `robin` as a named individual, when the
            # sentence says SOME robin. The existential quantification was
            # dropped silently and the result asserted something about the kind.
            #
            # That is the failure this module's genericity stage exists to
            # prevent, arriving from the other side: not "all robins are in the
            # yard" but "robin, the thing, is in the yard". EXISTENTIAL is
            # deliberately not representable -- the formal grammar has no
            # existential quantifier -- and a locative does not become
            # representable by being a relation.
            #
            # A definite or proper subject reads as INSTANCE and still works:
            # "the cup is in the top cabinet" names a cup, and that is the case
            # this pattern was added for.
            locative_reading = classify_genericity(subject, prop, determiner)
            if not locative_reading.is_representable:
                return {"kind": "unsupported",
                        "subject": subject, "prop": prop,
                        "reason": unrepresentable_reason(locative_reading.genericity),
                        "genericity": locative_reading.genericity.value,
                        "cue": locative_reading.cue}
            return {"kind": "relation", "subject": subject,
                    "preposition": relation.group("prep").lower(),
                    "object": other, "negated": negated}

        # "AND" JOINS TWO CLAIMS, IT DOES NOT NAME ONE THING.
        #
        # "the pump is hot and loud" read as `pump_hot_and_loud` -- a single
        # property whose name contains a conjunction. The sentence asserts two
        # things and the reading asserted one, so neither could be checked
        # against anything else the substrate knew about hot or about loud.
        if " and " in prop or prop.rstrip().endswith(" and"):
            if negated:
                # "not hot and loud" is genuinely ambiguous in English between
                # ~(hot & loud) and (~hot & ~loud). Refusing is the honest
                # answer; picking one would record a claim the sentence does
                # not settle.
                return {"kind": "unsupported",
                        "reason": "a negated conjunction is ambiguous",
                        "genericity": "n/a", "cue": prop}
            # Split on the word, not on " and " with spaces both sides: "hot
            # and" does not contain the padded form, so it split to ["hot and"]
            # and fell through to the plain-fact path, reading a truncated
            # sentence as the property `hot_and`.
            parts = [p.strip() for p in re.split(r"\s+and\s*", prop)]
            usable = [p for p in parts if p]
            if len(usable) != len(parts) or len(usable) < 2:
                # A side with nothing in it. The sentence was cut off, and a
                # cut-off sentence has no reading -- which is different from
                # having a reading nobody checked.
                return {"kind": "unsupported",
                        "reason": "a conjunction with an empty side",
                        "genericity": "n/a", "cue": prop}
            if all(len(p.split()) == 1 for p in usable):
                return {"kind": "conjunction", "subject": subject,
                        "properties": usable, "negated": False}
            return {"kind": "unsupported",
                    "reason": "a conjunct that is not a single property",
                    "genericity": "n/a", "cue": prop}

        if _word_class(prop) == "NOUN":
            return {"kind": "unsupported",
                    "reason": "a noun cannot be a property",
                    "genericity": "n/a", "cue": f"{prop} is a known noun"}

        reading = classify_genericity(subject, prop, determiner)

        if reading.genericity is Genericity.GENERIC_KIND:
            # A claim about a KIND. `_normalize` strips the complement's
            # article downstream, so "a bird" becomes the predicate `bird`.
            return {
                "kind": "universal",
                "p": subject,
                "q": prop,
                "negated": negated,
                "genericity": reading.genericity.value,
                "cue": reading.cue,
                "transformations": list(reading.transformations),
            }

        if reading.genericity is Genericity.INSTANCE:
            return {
                "kind": "fact",
                "subject": subject,
                "prop": prop,
                "negated": negated,
                "genericity": reading.genericity.value,
                "cue": reading.cue,
            }

        # UNDERSTOOD, BUT NOT REPRESENTABLE. Classification succeeded; the
        # formal grammar has no existential quantifier, and an ambiguous
        # sentence has no single reading to choose. Rendering either as an atom
        # would keep the pipeline running while discarding the quantifier.
        return {
            "kind": "unsupported",
            "subject": subject,
            "prop": prop,
            "negated": negated,
            "genericity": reading.genericity.value,
            "cue": reading.cue,
            "reason": unrepresentable_reason(reading.genericity),
        }
    def _parse_goal(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse the query, which may be phrased as a question.

        A goal carries its genericity too. "Is Tweety an animal?" asks about an
        individual; "Is a robin an animal?" asks about a KIND, and the two need
        different formalizations -- see `formalize`.
        """
        # "Is X a Y?" with X and Y possibly MULTI-WORD ("is the Klein four-group a
        # solvable group?"). Two non-greedy regex groups cannot split a multi-word
        # subject from a multi-word complement, so the split is done here: the
        # complement is what follows the LAST determiner (`a solvable group`), and
        # the subject is everything before it; with no complement-determiner
        # ("is the exponential function continuous?") the complement is the final
        # token. The subject's OWN determiner still decides genericity.
        qm = re.match(r"(?i)^(?:is|are)\s+(.+?)\s*\??\s*$", text.strip())
        if qm:
            body = qm.group(1).strip()
            subj_det_m = re.match(r"(?i)^(a|an|the)\s+", body)
            subj_det = subj_det_m.group(1) if subj_det_m else None
            if subj_det_m:
                body = body[subj_det_m.end():]
            complement_dets = list(re.finditer(r"(?i)\s+(?:a|an|the)\s+", body))
            if complement_dets:
                cut = complement_dets[-1]
                # keep the complement's determiner IN the prop ("an animal"), the
                # form genericity classifies against -- stripping it changed
                # "is a robin an animal?" from a kind-goal to ambiguous.
                subject, prop = body[:cut.start()].strip(), body[cut.start():].strip()
            else:
                parts = body.rsplit(None, 1)
                subject, prop = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (body, "")
            if subject and prop:
                reading = classify_genericity(subject, prop, subj_det)
                return {
                    "kind": "fact",
                    "subject": subject,
                    "prop": prop,
                    "negated": False,
                    "genericity": reading.genericity.value,
                }
        # "Does the tank overflow?" — an action question. Rendered by the same
        # action renderer as its declarative form, so the goal atom matches a
        # consequent like "the tank overflows".
        match = self._DOES_QUESTION.match(text.strip())
        if match:
            verb = match.group("verb").lower()
            groups = match.groupdict()
            if groups.get("object"):
                return {"kind": "svo", "subject": match.group("subject"),
                        "verb": verb, "object": groups["object"]}
            return {"kind": "sv", "subject": match.group("subject"), "verb": verb}
        # A WH question is OPEN -- the unknown is the answer, not the subject.
        # "what is (a) X?" asks X's class; "what eats plankton?" names a relation
        # and its object with the subject unknown. Extracted so gap detection and
        # the open reasoner have the relation to work with; the yes/no machinery
        # does not apply. why/how/when/where carry no single relation to lift and
        # fall through to the statement reader.
        wh = re.match(r"(?i)^(?:what|which|who|whom)\s+(?P<rest>.+?)\s*\??\s*$", text.strip())
        if wh:
            rest = wh.group("rest").strip()
            cop = re.match(r"(?i)^(?:is|are)\s+(?:an?\s+|the\s+)?(?P<x>.+)$", rest)
            if cop:
                return {"kind": "open", "subject": cop.group("x").strip(),
                        "relation": "is", "obj": None}
            parts = rest.split(None, 1)
            if len(parts) == 2:
                return {"kind": "open", "subject": None,
                        "relation": parts[0].lower(), "obj": parts[1].strip()}
            return None
        return self._parse_statement(text)
    def _render_relation(self, node) -> str:
        """`the valve is in the pump` -> valve_in_pump (or ~valve_in_pump).

        The determiner is dropped and the object singularised, so the atom names
        the two THINGS and the relation between them -- which is what lets
        `valve_in_pump` and `valve_in_tank` be recognised as the same question
        asked of different things.
        """
        subject = self._singular(self._normalize(node["subject"]))
        other = self._singular(self._normalize(node["object"]))
        atom = f"{subject}_{node['preposition']}_{other}"
        return f"~{atom}" if node.get("negated") else atom
    def _render_conjunction(self, node) -> List[str]:
        """`the pump is hot and loud` -> [pump_hot, pump_loud]."""
        subject = self._singular(self._normalize(node["subject"]))
        return [f"{subject}_{self._normalize(p)}" for p in node["properties"]]
    def _render_action(self, node) -> str:
        """An action sentence as a single atom.

        The object keeps its own name rather than being folded into the verb,
        so `pump_moves_water` and `pump_moves_air` are different atoms about the
        same action -- which is what lets anything downstream notice they are
        related.
        """
        subject = self._singular(self._normalize(node["subject"]))
        # Singularise the verb too, so 3rd-person agreement does not split an
        # atom: "the tank overflows" and "does the tank overflow?" must name the
        # same proposition (tank_overflow), or a provable goal reads as unmet.
        verb = self._singular(self._normalize(node["verb"]))
        if node["kind"] == "sv":
            return f"{subject}_{verb}"
        obj = self._singular(self._normalize(node["object"]))
        return f"{subject}_{verb}_{obj}"
    def _render_fact(self, node: Dict[str, Any]) -> str:
        atom = self._atom(node["subject"], node["prop"])
        return f"~{atom}" if node["negated"] else atom

    #: Words that join clauses/complements and end a subordinate insertion.
    _COORD = re.compile(r"\s+and\s+|\s+or\s+", re.IGNORECASE)
    _RELATIVE = re.compile(r"(?i)^(which|who|that|whose)\s+(.+)$")

    def read_all(self, text: str) -> List[Dict[str, Any]]:
        """Every simple proposition a possibly-COMPLEX sentence carries, as a list
        of (subject, relation, obj, positive) parts.

        A real sentence packs several claims: "the okapi, which is a mammal, is a
        herbivore" states two, "a whale is a mammal and a vertebrate" two more.
        This decomposes the sentence into simple clauses -- splitting relative
        clauses and appositives set off by commas (the subject carries into each),
        and coordinated complements -- then reads each with the ordinary
        single-clause reader. It never guesses structure it cannot see: a segment
        that does not read is dropped, not forced, so a tangled sentence yields
        the claims it can and no invented ones. Multiple sentences are read each
        in turn."""
        out: List[Dict[str, Any]] = []
        seen = set()
        for sentence in re.split(r"(?<=[.!?])\s+", str(text).strip()):
            for clause in self._decompose(sentence):
                node = self._parse_statement(clause)
                if not node:
                    continue
                for cp in self._expand_conjuncts(node):
                    key = (cp.get("subject", "").lower(), str(cp.get("relation", "")).lower(),
                           str(cp.get("obj") or "").lower(), cp.get("positive", True))
                    if key not in seen:
                        seen.add(key)
                        out.append(cp)
        return out

    def _decompose(self, sentence: str) -> List[str]:
        """Split one sentence into simple clauses that share the subject.

        `HEAD, INSERT, TAIL` where INSERT is a relative clause ("which is a
        mammal") or an appositive ("a mammal") becomes the main clause
        `HEAD TAIL` plus a claim about HEAD from INSERT. Everything else is
        returned as-is for the single-clause reader to handle (including its own
        conjunction handling)."""
        s = sentence.strip().rstrip(".!?")
        # strip a leading discourse opener: "In mathematics, X is a Y" -> "X is a Y"
        s = re.sub(r"(?i)^(in|within|in the field of|in the study of)\s+[\w\s-]+?,\s+(?=(?:the |a |an )?[\w'-])", "", s, count=1)
        m = re.match(
            r"^(?P<head>(?:the |a |an )?[\w'-]+(?:\s+[\w'-]+){0,3}),\s+(?P<insert>.+?),\s+(?P<tail>.+)$",
            s, re.IGNORECASE)
        if not m:
            # Coordinated copular complement: "HEAD is a mammal and a vertebrate"
            # -> "HEAD is a mammal", "HEAD is a vertebrate". Split only the part
            # after the copula, and only when it is not a negation (a negated
            # conjunction is genuinely ambiguous and the single-clause reader
            # already refuses it).
            cop = re.match(r"(?i)^(?P<lhs>.+?\s+(?:is|are))\s+(?P<comp>.+?(?:\s+and\s+|\s+or\s+).+)$", s)
            if cop and " not " not in f" {s.lower()} ":
                comps = [c.strip() for c in self._COORD.split(cop.group("comp")) if c.strip()]
                if len(comps) >= 2:
                    return [f"{cop.group('lhs')} {c}" for c in comps]
            return [s]
        head, insert, tail = m.group("head").strip(), m.group("insert").strip(), m.group("tail").strip()
        clauses = [f"{head} {tail}"]                       # main: "the okapi is a herbivore"
        rel = self._RELATIVE.match(insert)
        if rel:
            clauses.append(f"{head} {rel.group(2)}")       # "the okapi is a mammal"
        elif re.match(r"(?i)^(a|an|the)\s+", insert) or _word_class(insert.split()[0]) == "NOUN":
            clauses.append(f"{head} is {insert}")          # appositive: "the okapi is a small mammal"
        return clauses

    def _expand_conjuncts(self, node: Dict[str, Any]) -> List[Dict[str, Any]]:
        """One clause node -> its atomic (subject, relation, obj) parts, splitting
        a coordinated complement: "is a mammal and a vertebrate" -> two facts. A
        conjunction node (single-word properties) is expanded the same way."""
        if (node or {}).get("kind") == "conjunction":
            subj = node["subject"]
            return [{"subject": subj, "relation": "is", "obj": p, "positive": True}
                    for p in node.get("properties", [])]
        # A generic ("a whale is a mammal") reads as a UNIVERSAL; for knowledge
        # extraction that is the ISA edge whale->mammal. clause_parts deliberately
        # leaves universals to the formal side, so read_all lifts the edge here.
        if (node or {}).get("kind") == "universal" and not node.get("negated"):
            return [{"subject": node["p"], "relation": "is", "obj": node["q"],
                     "positive": True}]
        cp = self.clause_parts(node)
        if not cp:
            return []
        obj = cp.get("obj")
        if obj and self._COORD.search(obj):
            pieces = [re.sub(r"(?i)^(a|an|the)\s+", "", p.strip()).strip()
                      for p in self._COORD.split(obj)]
            return [{**cp, "obj": p} for p in pieces if p]
        return [cp]

    def clause_parts(self, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A clause as (subject, relation, object, positive) parts — the form a
        held conditional stores each side in, so a rule's clause and a stand-alone
        fact are stored the same way and later render to the same atom. A copular
        fact carries the relation "is" (dropped at atom time); an action carries
        its verb; a locative carries its preposition. Returns None for a clause
        that is not a single proposition (a conjunction, an unsupported reading)."""
        kind = (node or {}).get("kind")
        if kind == "fact":
            return {"subject": node["subject"], "relation": "is",
                    "obj": node["prop"], "positive": not node.get("negated", False)}
        if kind == "sv":
            return {"subject": node["subject"], "relation": node["verb"],
                    "obj": None, "positive": True}
        if kind == "svo":
            return {"subject": node["subject"], "relation": node["verb"],
                    "obj": node["object"], "positive": True}
        if kind == "relation":
            return {"subject": node["subject"], "relation": node["preposition"],
                    "obj": node["object"], "positive": not node.get("negated", False)}
        if kind == "open":                       # a WH question: subject may be unknown
            return {"subject": node.get("subject"), "relation": node.get("relation"),
                    "obj": node.get("obj"), "positive": True}
        return None

    def render_clause(self, node: Dict[str, Any]) -> Optional[str]:
        """One clause as a single signed atom, or None if it is not a single
        proposition (a conjunction is two, an unsupported reading is none).

        The one place that maps a clause of ANY readable kind — fact, action,
        relation — onto the atom the solver reasons over, so a conditional's
        sides render the same way a standalone claim does rather than assuming
        both are copular facts."""
        kind = (node or {}).get("kind")
        if kind == "fact":
            return self._render_fact(node)
        if kind in ("svo", "sv"):
            return self._render_action(node)
        if kind == "relation":
            return self._render_relation(node)
        return None  # conjunction (two atoms), universal, or unsupported

    #: Relations whose atom DROPS the relation, so the copula/classifier and the
    #: property become one predicate: `X is Y`, `X isa Y`, `X has_property Y` all
    #: name `x_y`. These are exactly the relations a bare copular fact is typed
    #: as, so a rule clause stored with the surface `is` and a stand-alone fact
    #: stored in the graph as `isa`/`has_property` render to the SAME atom.
    _COPULAR_RELATIONS = frozenset({
        "is", "are", "was", "were", "be", "been",
        "isa", "is_a", "instance_of", "has_property",
    })

    def clause_atom(self, subject: str, relation: str,
                    obj: Optional[str] = None, positive: bool = True
                    ) -> Optional[str]:
        """The signed atom for a clause given its STRUCTURED parts, without
        re-reading any surface English.

        This is the one vocabulary the reasoner formalizes held rules AND held
        facts into: a held conditional's stored clause parts and a concept-graph
        edge both pass through here, so `valve is closed` (a taught rule's
        antecedent) and `valve isa closed` (the graph's fact) become the same
        atom `valve_closed` and the rule fires. It reproduces exactly what
        `_render_fact` / `_render_action` / `_render_relation` produce, so an
        atom built from parts equals the atom built from a parsed node.

        Returns None when the parts are not a single representable proposition
        (missing subject/relation, or a copular clause with no complement)."""
        subject = (subject or "").strip()
        rel = (relation or "").strip()
        if not subject or not rel:
            return None
        obj = (obj or "").strip() or None
        if rel.lower().replace(" ", "_") in self._COPULAR_RELATIONS:
            if not obj:
                return None  # a copular clause needs a complement to classify
            atom = self._atom(subject, obj)              # subject_prop, copula dropped
        elif obj is None:
            atom = (f"{self._singular(self._normalize(subject))}_"
                    f"{self._singular(self._normalize(rel))}")
        else:
            atom = (f"{self._singular(self._normalize(subject))}_"
                    f"{self._singular(self._normalize(rel))}_"
                    f"{self._singular(self._normalize(obj))}")
        return atom if positive else f"~{atom}"
