#!/usr/bin/env python3
"""Reading a sentence into structure. SEMANTICS OWNS THIS.

MOVED OUT OF `core/reasoning/neural_bridge.py` on 2026-08-24, where 619 lines of
English patterns had grown inside the reasoning module. Reasoning should CONSUME
a reading, not implement one, and language is this faculty's job -- the learned
reader, the lexicon, the claim shapes and the sentence machine all already live
here.

WHAT THIS IS, AND WHAT IT IS NOT. These are hand-written patterns: English
written into the code. The substrate's own reading is LEARNED -- sentences taught
with their meaning, held in memory as patterns and read by `derived_reader`.
Every caller of this module switches to that reading in one step, and then this
module goes (docs/research/SHAPES_CHANGE_MAP.md, step 3). Until then it reads
what it always read, and `clause_atom` below stays the one place clause parts
become a solver atom.

WHAT A READING IS. A sentence in, a structure out, or None. It decides only WHAT
a sentence relates -- never whether the formal grammar can carry that relation,
which is genericity's separate stage, and never how to render it for a solver,
which is the reasoning side's job.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.semantics import lexical_normalization as _lexical
from core.semantics.genericity import (ADJECTIVE, Genericity, blame,
                                       classify_genericity, depending,
                                       unrepresentable_reason, _word_class)

logger = logging.getLogger(__name__)


class SentenceReader:
    """Turns a bounded slice of English into structure. Needs no model."""

    _ARTICLES = ("a ", "an ", "the ")
    _DETERMINER = r"(?:(?P<det>a|an|the)\s+)?"
    #: `am` is included so a first-person self-statement reads ("I am a plumber").
    #: It is unambiguous — `am` only ever follows a first-person subject — so it
    #: never changes how a world fact reads.
    _COPULA = r"(?:is|are|am)"
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
    #: Subject and verb stay single tokens (the verb is anchored by the lexicon
    #: below), but the OBJECT may be a short noun phrase, not just one word:
    #: "a farmer has twelve sheep", "she bought 12 apples", "the pump moves cold
    #: water". Up to four tokens (digits allowed, so a quantity survives), an
    #: optional leading determiner or number kept inside the object. Still
    #: anchored on a known verb, so an all-unknown run reads as nothing.
    #: A SUBJECT MAY BE NAMED RELATIONALLY: "the resistance OF a component
    #: depends on charge" is a claim about the component's resistance, and a
    #: single-token subject slot cannot hold it.
    #: Either a relationally-named subject ("the reusable block OF code", "the
    #: resistance OF a component") or a single token. The of-phrase is a
    #: separate alternative rather than an optional tail, so the plain case is
    #: NOT widened: a greedy multi-word subject is what made "The water filter
    #: works" read `filter` as the action.
    _SVO_SUBJ = (r"(?P<subject>[\w'-]+(?:\s+[\w'-]+){0,2}\s+of\s+"
                 r"(?:(?:a|an|the)\s+)?[\w'-]+|[\w'-]+)")
    _SVO = re.compile(
        rf"^{_DETERMINER}{_SVO_SUBJ}\s+(?P<verb>[\w'-]+)\s+"
        rf"(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+(?:\s+[\w'-]+){{0,3}}?)"
        # A TRAILING PREPOSITIONAL PHRASE MODIFIES THE CLAIM; it is not part of
        # what the verb reaches. "a device moves fluid through a pipe" is about
        # fluid, and reading the object as `fluid through a pipe` names a thing
        # that does not exist and that no other sentence about fluid can meet.
        r"(?:\s+(?:in|on|at|by|under|inside|outside|above|below|over|near|"
        r"behind|beside|within|atop|beneath|among|around|through|before|after|"
        r"during|to|from|into|onto|with|for)\s+.*)?$",
        re.IGNORECASE)
    #: Prepositions that name a RELATION between two things when they stand
    #: after the copula ("X is PREP Y"). Spatial AND temporal/associative: "at
    #: noon", "before dawn", "over the river", "by Tolkien" are relations, not
    #: classes -- restricting this to spatial prepositions filed "the meeting is
    #: at noon" as the class `at_noon`. `to`/`from`/`into`/`onto` are left OUT on
    #: purpose: "the goal is to win" is an infinitive, not a locative, and reading
    #: it as `goal --to--> win` is worse than not reading it.
    _PREPOSITIONS = ("in", "on", "at", "by", "under", "inside", "outside",
                     "above", "below", "over", "near", "behind", "beside",
                     "within", "atop", "beneath", "among", "around", "through",
                     "before", "after", "during")
    _PREPOSITIONAL = re.compile(
        rf"^(?P<prep>{'|'.join(_PREPOSITIONS)})\s+"
        r"(?:(?:a|an|the)\s+)?(?P<object>[\w'-]+(?:\s+[\w'-]+)*)$",
        re.IGNORECASE)
    #: An adverb standing BETWEEN a subject and its verb. "a percept ALSO
    #: feeds the emotional state" read `also` as the relation and then refused,
    #: so an ordinary claim was lost to one word.
    #:
    #: THIS WAS A LIST OF TWENTY-FOUR WORDS WRITTEN HERE. English has thousands
    #: -- WordNet alone settles the class of 3,276 -- so the list could only
    #: ever cover the ones somebody thought of, and the reader was blind to
    #: every other adverb in the language. The class is taught now, like every
    #: other class, so this asks what the substrate has learned instead of what
    #: was typed.
    def _drop_preverbal_adverb(self, sentence: str) -> str:
        """`a percept also feeds X` -> `a percept feeds X`, or the sentence.

        A word is dropped only where the substrate has OBSERVED it as an
        adverb. A word it knows nothing about is left alone -- dropping an
        unknown word to make a sentence parse is guessing, and the reading that
        followed would rest on it."""
        from core.semantics.genericity import _word_classes
        words = sentence.split()
        for i, word in enumerate(words):
            if i == 0:
                continue
            bare = word.strip(",").lower()
            classes = _word_classes(bare)
            # ONLY an adverb. A word that is also a noun or a verb here is
            # doing that job -- "the report RUNS" must not lose its verb.
            if "ADVERB" in classes and not (classes - {"ADVERB"}):
                return " ".join(words[:i] + words[i + 1:])
        return sentence

    _SV = re.compile(
        rf"^{_DETERMINER}{_SVO_SUBJ}\s+(?P<verb>[\w'-]+)$",
        re.IGNORECASE)
    #: `the battle happened in 1066`, `water flows through the pipe`. An action
    #: with a prepositional phrase -- a subject, a verb, and the thing the verb
    #: reaches THROUGH a preposition. The copular locative (`the cup is in the
    #: box`) is already read above; this is its lexical-verb counterpart, and it
    #: is where a date or a number most naturally appears in a sentence ("in
    #: 1066", "on 2026-08-26"). The object admits digits, dots, slashes and
    #: hyphens so a literal survives, and runs to at most three words.
    _SVO_PREP = re.compile(
        rf"^{_DETERMINER}{_SVO_SUBJ}\s+(?P<verb>[\w'-]+)\s+"
        rf"(?P<prep>in|on|at|by|under|inside|above|below|near|behind|through|"
        rf"over|during|into|onto|from|to)\s+"
        rf"(?:(?:a|an|the)\s+)?(?P<object>[\w./'-]+(?:\s+[\w./'-]+){{0,2}})$",
        re.IGNORECASE)
    #: A COMPARATIVE relates two things on a scale: "iron is heavier than
    #: aluminium" is not a claim that iron is a kind of `heavier than
    #: aluminium`. The scale and the standard are both carried -- the relation
    #: is `heavier than` and the object is what it is measured against -- so the
    #: claim can be reasoned with rather than stored as a name. Matched BEFORE
    #: `_FACT`, whose trailing `.+` would otherwise swallow `than` and all.
    _COMPARATIVE = re.compile(
        rf"^{_DETERMINER}{_SUBJ}\s+{_COPULA}\s+(?P<scale>[\w'-]+)\s+than\s+"
        r"(?:(?:a|an|the)\s+)?(?P<standard>[\w\s'-]+)$", re.IGNORECASE)
    #: MODALITY IS PART OF THE CLAIM, not a word to refuse. "a pump CAN fail"
    #: says something weaker than "a pump fails", and reading it as the latter
    #: would put a claim in front of the solver that the sentence never made.
    #: The modal is kept IN the relation, so `pump_can_fail` and `pump_fail` are
    #: different atoms and neither is mistaken for the other.
    _MODALS = ("can", "could", "may", "might", "must", "shall", "should",
               "will", "would")
    _MODAL_CLAIM = re.compile(
        rf"^{_DETERMINER}{_SUBJ}\s+(?P<modal>{'|'.join(_MODALS)})\s+"
        r"(?P<verb>[\w'-]+)(?:\s+(?:(?:a|an|the)\s+)?(?P<object>[\w\s'-]+))?$",
        re.IGNORECASE)
    #: A QUANTIFIER scopes a claim; it is not part of the subject. "most birds
    #: can fly" is a claim about birds, and reading `most birds` as the thing it
    #: is about invents a kind that does not exist. `all`/`every`/`no` are NOT
    #: here -- they are universals and are read above, with their own meaning.
    _QUANTIFIERS = ("most", "some", "many", "several", "few", "certain")
    _QUANTIFIED = re.compile(
        rf"^(?P<quant>{'|'.join(_QUANTIFIERS)})\s+(?P<rest>.+)$", re.IGNORECASE)
    #: A PASSIVE names the same event as its active, with the roles in the other
    #: order: "the letter was written by Alice" and "Alice wrote the letter" are
    #: one claim, not two, and storing the surface order would file the letter
    #: as the thing that did the writing.
    _PASSIVE_BY = re.compile(
        rf"^{_DETERMINER}(?P<patient>[\w'-]+(?:\s+[\w'-]+){{0,3}}?)\s+"
        r"(?:is|are|was|were)\s+(?P<participle>[\w'-]+)\s+by\s+"
        r"(?:(?:a|an|the)\s+)?(?P<agent>[\w\s'-]+)$", re.IGNORECASE)
    #: `The pump was replaced` -- a passive with no agent named. The event is
    #: still asserted of the patient, so the claim is kept with the voice IN the
    #: relation rather than lost. `is`/`are` are deliberately absent: "the vault
    #: is locked" is a state already read as a property, and routing it here
    #: would change a reading that is correct.
    _PASSIVE_STATE = re.compile(
        rf"^{_DETERMINER}(?P<patient>[\w'-]+(?:\s+[\w'-]+){{0,3}}?)\s+"
        r"(?P<aux>was|were)\s+(?P<participle>[\w'-]+)$", re.IGNORECASE)
    #: `Paris the capital of France is on the Seine` -- a name, then another
    #: name for the same thing, then what is said of it. Two claims, and the
    #: appositive is the one a reader loses first.
    _APPOSITION = re.compile(
        r"(?i)^(?P<head>[\w'-]+)\s+(?P<appos>(?:a|an|the)\s+[\w\s'-]+?)\s+"
        r"(?P<rest>(?:is|are|was|were)\s+.+)$")
    #: A complement that carries its own relative clause: `a device THAT moves
    #: fluid`. The head names the kind; the tail says something about the kind.
    _COMPLEMENT_RELATIVE = re.compile(
        r"(?i)^(?P<subject>.+?)\s+(?P<cop>is|are)\s+(?P<head>(?:a|an|the)\s+[\w\s'-]+?)\s+"
        r"(?P<rel>that|which|whose)\s+(?P<inner>.+)$")
    #: `The vault holds gold and silver` / `The valve opens and closes` -- one
    #: subject, a coordinated object or a coordinated verb.
    _OBJECT_COORD = re.compile(
        r"(?i)^(?P<lead>.+?)\s+(?P<a>[\w'-]+)\s+and\s+(?P<b>[\w'-]+)$")
    #: `Alice gave Bob a book` -- ONE verb reaching TWO things: what was given
    #: and who it went to. English marks the theme with a determiner and leaves
    #: the recipient bare, which is the only signal available without a frame
    #: for the verb, so the determiner is what this keys on.
    _DITRANSITIVE = re.compile(
        r"(?i)^(?:(?:a|an|the)\s+)?(?P<subject>[\w'-]+(?:\s+[\w'-]+){0,2}?)\s+"
        # NOT a copula: "the cup is in the box" is a relation, not a giving.
        r"(?!(?:is|are|am|was|were)\b)(?P<verb>[\w'-]+)\s+"
        # The proper-noun alternative is case-SENSITIVE -- under the pattern's
        # own `(?i)`, `[A-Z]` matched every word, and "the cup is IN the box"
        # parsed as a gift to something called `in`.
        r"(?P<recipient>(?:a|an|the)\s+[\w'-]+|(?-i:[A-Z][\w'-]*))\s+"
        r"(?P<theme>(?:a|an|the)\s+[\w'-]+)$")
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
    #: A statement is never an interrogative. A trailing '?' or a leading WH /
    #: auxiliary opener marks a question, which `_parse_goal` handles -- the
    #: statement reader must refuse it so "What is a memristor?" is never stored
    #: as the fact `what isa memristor`. Declaratives never open with these.
    _INTERROGATIVE = re.compile(
        r"(?i)^(?:what|where|who|whom|whose|why|when|which|how|"
        r"is|are|was|were|do|does|did|can|could|will|would|should|has|have|had)\b")

    #: Words that MARK STRUCTURE THIS READER CANNOT CARRY. A relative pronoun
    #: opens a clause inside a noun phrase; a coordinator makes a sentence state
    #: more than one claim; `than` heads a comparative; a subordinator joins two
    #: claims. None of these can be represented as one (subject, relation,
    #: object), so a sentence containing one must be REFUSED rather than matched.
    #:
    #: MEASURED, AND THIS IS WHY IT EXISTS. `_FACT` is `^det? SUBJ is (.+)$` and
    #: that `.+` is unbounded, so everything after a copula became the property:
    #:   "There is no longer any path from the substrate to a generative model."
    #:      -> subject `there`
    #:   "Scientists believe the universe is expanding."
    #:      -> subject `scientists believe the universe`
    #:   "Iron is heavier than aluminium."   -> property `heavier than aluminium`
    #: The NLU suite measured a 58.3% false-positive rate on structures the
    #: reader cannot represent, and 17% of real prose "read" as atoms like
    #: `there_no_longer_any_path_from_the_substrate_to_a_generative_model`. Each
    #: one becomes a premise the solver cannot doubt.
    #:
    #: `if`/`then` are absent deliberately: a conditional IS representable and is
    #: read above this guard. Prepositions are absent too -- "the cup is in the
    #: box" is a relation the reader carries.
    #: MEASURED PER CLASS, not guessed: modals, passive auxiliaries and
    #: non-universal quantifiers each produced a specific confident misreading
    #: (`valve_may_stick`, `letter_was_written_by_alice`, `some_metal_rust`).
    #: The universals all/every/no are absent because the reader DOES represent
    #: them, above this guard.
    #: `France's capital` -- a thing named by its relation to another thing.
    _POSSESSIVE = re.compile(r"(?i)^(?P<owner>[\w-]+)'s?\s+(?P<owned>.+)$")

    def _possessive_subject(self, phrase: str) -> str:
        """`France's capital` -> `capital of France`.

        A POSSESSIVE NAMES A THING BY ANOTHER THING, and the two are not
        interchangeable: read as written it produced a subject called `frances
        capital`, an atom for a thing that does not exist and that no other
        sentence about France could ever meet. Turning it into the relational
        phrase keeps both names present and separable."""
        phrase = str(phrase).strip()
        match = self._POSSESSIVE.match(phrase)
        if not match:
            return phrase
        return f"{match.group('owned').strip()} of {match.group('owner').strip()}"

    def _complement_clause(self, sentence: str) -> Optional[str]:
        """The inner claim of `SUBJ VERB <clause>`, or None.

        `Scientists believe the universe is expanding` -> `the universe is
        expanding`. A DETERMINER OPENS A NOUN PHRASE, so one standing inside
        what was matched as the subject means the match ran across a clause
        boundary and the real subject starts at that determiner. Read whole, the
        sentence produced a claim about a thing called `scientists believe the
        universe`.

        The OUTER claim -- that scientists believe it -- is not returned,
        because a claim whose object is another claim has no representation
        here. What is returned is the part that is separately true.
        """
        match = self._FACT.match(sentence)
        if not match:
            return None
        words = match.group("subject").split()
        for i in range(1, len(words)):
            if words[i].lower() in ("a", "an", "the"):
                return " ".join(words[i:]) + sentence[match.end("subject"):]
        return None

    #: `Dogs and cats are mammals` -- ONE predicate over TWO subjects.
    _SUBJECT_COORD = re.compile(
        r"(?i)^(?:(?:a|an|the)\s+)?(?P<a>[\w'-]+(?:\s+[\w'-]+){0,2}?)\s+(?:and|or)\s+"
        r"(?:(?:a|an|the)\s+)?(?P<b>[\w'-]+(?:\s+[\w'-]+){0,2}?)\s+"
        r"(?P<rest>(?:is|are|was|were)\s+.+)$")

    def _distribute_subject(self, clause: str) -> List[str]:
        """`Dogs and cats are mammals` -> two claims, one per subject.

        A COORDINATED SUBJECT IS NOT A NAME. Read whole it produced the atom
        `dogs_and_cat_mammal` -- a single thing called "dogs and cats", which
        nothing else the substrate ever reads about dogs could meet. The
        predicate is shared, so it is said of each conjunct separately, which is
        exactly what the sentence says.
        """
        match = self._SUBJECT_COORD.match(str(clause).strip().rstrip(".!?"))
        if not match:
            return [clause]
        rest = match.group("rest")
        return [f"{match.group('a')} {rest}", f"{match.group('b')} {rest}"]

    def _appositive_clauses(self, clause: str) -> List[str]:
        """`Paris the capital of France is on the Seine` -> two claims.

        AN APPOSITIVE IS A SECOND NAME, not part of the first. Read whole, the
        subject became `paris the capital of france` -- one atom naming a thing
        no other sentence could ever refer to, and the sentence's own claim
        about the Seine went with it."""
        match = self._APPOSITION.match(str(clause).strip().rstrip(".!?"))
        if not match:
            return [clause]
        head = match.group("head")
        return [f"{head} is {match.group('appos')}",
                f"{head} {match.group('rest')}"]

    def _complement_relative_clauses(self, clause: str) -> List[str]:
        """`A pump is a device that moves fluid` -> the kind, and what the kind
        does. The relative tail is a claim about the COMPLEMENT, not about the
        subject, and dropping it loses the half of a definition that says what
        the thing is for."""
        match = self._COMPLEMENT_RELATIVE.match(str(clause).strip().rstrip(".!?"))
        if not match:
            return [clause]
        head = match.group("head").strip()
        bare = re.sub(r"(?i)^(?:a|an|the)\s+", "", head)
        inner = match.group("inner").strip()
        if match.group("rel").lower() == "whose":
            # `a component whose resistance depends on charge` -- the claim is
            # about the component's resistance, which is named relationally.
            owned, _, rest = inner.partition(" ")
            return [f"{match.group('subject')} {match.group('cop')} {head}",
                    f"{owned} of {bare} {rest}".strip()]
        return [f"{match.group('subject')} {match.group('cop')} {head}",
                f"{bare} {inner}"]

    def _distribute_tail_coordination(self, clause: str) -> List[str]:
        """`The vault holds gold and silver` -> two claims; `The valve opens and
        closes` -> two claims. A coordinator at the END of a clause shares
        everything before it, so each conjunct is said with that shared lead."""
        text = str(clause).strip().rstrip(".!?")
        match = self._OBJECT_COORD.match(text)
        if not match:
            return [clause]
        lead, a, b = match.group("lead"), match.group("a"), match.group("b")
        if self._COPULA_RE.search(lead):
            return [clause]        # `X is A and B` is the complement path
        words = lead.split()
        if len(words) >= 2:        # a shared verb: `the vault holds` + gold/silver
            return [f"{lead} {a}", f"{lead} {b}"]
        return [f"{lead} {a}", f"{lead} {b}"]

    def _ditransitive_clauses(self, clause: str) -> List[str]:
        """`Alice gave Bob a book` -> what was given, and who it went to.

        Read as a plain SVO the object became `Bob a book` -- one thing, named
        after two. The recipient is restated with the preposition English uses
        for it when the order is the other way round ("gave a book TO Bob"), so
        both claims are ordinary readings rather than a new arity."""
        match = self._DITRANSITIVE.match(str(clause).strip().rstrip(".!?"))
        if not match:
            return [clause]
        subject, verb = match.group("subject"), match.group("verb")
        return [f"{subject} {verb} {match.group('theme')}",
                f"{subject} {verb} to {match.group('recipient')}"]

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
        """Classify one sentence, or return None if it is outside the slice.

        ATTESTATION IS NOT WIRED, AND THIS IS THE GAP.

        Word classes are now DERIVED, at warm time, from the substrate's own
        memories of what it was taught: a class is supported by however many
        taught propositions imply it. That gives evidence FOR a class and no
        route for evidence AGAINST -- the lexicon's `confirm`/`refute`, which
        this method used to drive, went with the store.

        It is left unbuilt rather than half-built. The obvious shape is to
        remember a failed reading as the experience it is, but a failed parse
        is common and individually worthless, and writing one record per
        failure is how memory filled with telemetry the last time. Choosing
        that is a decision about what belongs in memory, not a detail to settle
        inside the reader.

        `depending()` still runs, so what a reading leaned on is still
        collected and the hook has somewhere to attach when the question is
        settled.
        """
        with depending() as leaned_on:
            return self._read_statement(text)

    def _read_statement(self, text: str) -> Optional[Dict[str, Any]]:
        """The reading itself. Wrapped by `_parse_statement`, which attests it."""
        sentence = text.strip().rstrip(".")
        if not sentence:
            return None

        # A QUESTION is not a statement: refuse it here so it is never read as a
        # fact (see `_INTERROGATIVE`). The query path reads it through `_parse_goal`.
        if text.strip().endswith("?") or self._INTERROGATIVE.match(sentence):
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

        # A QUANTIFIER scopes the claim; the claim under it is read normally.
        # Read FIRST so "most birds can fly" reaches the modal reading below
        # instead of being refused for a subject that is not a kind.
        match = self._QUANTIFIED.match(sentence)
        if match:
            inner = self._read_statement(match.group("rest"))
            if inner is not None:
                inner = dict(inner)
                inner["quantifier"] = match.group("quant").lower()
                return inner
            return None

        # A COMPARATIVE, before `_FACT` swallows `than` into the complement.
        match = self._COMPARATIVE.match(sentence)
        if match:
            return {"kind": "relation",
                    "subject": self._possessive_subject(match.group("subject")),
                    "preposition": f"{match.group('scale').lower()} than",
                    "object": match.group("standard").strip()}

        # A PASSIVE with a named agent, before `_FACT` reads the participle as a
        # property of the patient. The roles go back in their active order.
        match = self._PASSIVE_BY.match(sentence)
        if match:
            return {"kind": "svo",
                    "subject": match.group("agent").strip(),
                    "verb": match.group("participle").lower(),
                    "object": self._possessive_subject(match.group("patient"))}

        # MODALITY, kept in the relation so a possibility is never stored as a
        # fact. Before `_FACT` only so "the tank might overflow" is not read as
        # a subject called "the tank might".
        match = self._PASSIVE_STATE.match(sentence)
        if match:
            return {"kind": "sv",
                    "subject": self._possessive_subject(match.group("patient")),
                    "verb": f"{match.group('aux').lower()} "
                            f"{match.group('participle').lower()}"}

        match = self._MODAL_CLAIM.match(sentence)
        if match:
            relation = f"{match.group('modal').lower()} {match.group('verb').lower()}"
            subject = self._possessive_subject(match.group("subject"))
            obj = (match.group("object") or "").strip()
            if obj:
                return {"kind": "svo", "subject": subject, "verb": relation,
                        "object": obj}
            return {"kind": "sv", "subject": subject, "verb": relation}

        # A SUBJECT THAT SPANS A CLAUSE BOUNDARY carries an inner claim.
        inner = self._complement_clause(sentence)
        if inner is not None:
            read = self._read_statement(inner)
            if read is not None:
                return read

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
        from core.semantics.genericity import _word_classes
        from core.semantics.lexical_normalization import deinflect_verb

        # MEMBERSHIP, NOT IDENTITY.
        #
        # This asked `_word_class(verb)` for THE class of the word, and a word
        # that is honestly two things has no such answer: `filter` is a thing
        # and also something one does, and so is `separates`, `blocks`, `runs`.
        # A single-answer lookup either picks one and is wrong half the time or
        # -- when the evidence is even -- answers nothing at all, and the
        # sentence stops reading. What the verb slot needs to know is not what
        # the word IS, it is whether the substrate has ever seen it used as an
        # action, which is a question polysemy does not spoil.
        seen = _word_classes(verb)
        if "VERB" in seen:
            return True
        if any("VERB" in _word_classes(base) for base in deinflect_verb(verb)):
            return True
        # An adjective in the verb slot is never the action, and neither is an
        # adverb -- an adverb MODIFIES the action, so a sentence read with one
        # in the relation slot states a claim nobody made.
        if "ADJECTIVE" in seen or "ADVERB" in seen:
            return False
        # Observed ONLY as a thing: the pattern almost certainly mis-split, as
        # it does on "The water filter works" -- greedy subject, `filter` taken
        # for the action. Rejecting is what stops that reading.
        if "NOUN" in seen:
            return False
        # Observed, and never as an action: a determiner, preposition, pronoun,
        # conjunction or auxiliary is a word the substrate KNOWS, and knows is
        # not a verb. This fell through to the unknown-word case below, so an
        # imperative with a noun-like first word read as a statement:
        # "Read the maintenance note" -> subject `Read`, verb `the` -- a telling,
        # answered from memory, and the work asked for was never done.
        if seen:
            return False
        # Never observed at all. THE KNOWN WORDS AROUND IT IDENTIFY THE VERB:
        # the thing the sentence is about anchors the word after it as the
        # action, which is how a learner meets a new verb. No anchor, no
        # reading -- this never guesses from an all-unknown sentence.
        return "NOUN" in _word_classes(self._subject_head(subject))

    def _subject_head(self, subject: str) -> str:
        """The HEAD noun of a subject phrase.

        `_reads_as_verb` asks whether the subject is a known NOUN, and it asked
        it of the WHOLE phrase -- so "the resistance of a component" was looked
        up as one word, found nothing, and the sentence stopped reading. An
        English noun phrase is headed by the last word of its core, and a
        post-modifier introduced by `of` elaborates the head rather than
        replacing it."""
        core = re.split(r"(?i)\s+of\s+", str(subject or "").strip())[0]
        words = [w for w in core.split() if w.lower() not in ("a", "an", "the")]
        return words[-1] if words else str(subject or "").strip()

    #: A complement may name a kind or a property. It may NOT contain a
    #: preposition (that heads a phrase of its own), another copula, a
    #: coordinator, or a relative pronoun -- each opens structure a single
    #: (subject, relation, object) cannot hold. Four content words is the widest
    #: noun phrase the store itself admits as a name; past that it is a clause.
    _COMPLEMENT_BREAKS = frozenset(
        {"is", "are", "am", "was", "were", "be", "been", "being",
         "and", "or", "but", "than", "that", "which", "who", "whom", "whose",
         "not",
         # A WH-WORD OPENS A CLAUSE. "this is HOW the substrate forgets" is not
         # a thing called "how the substrate forgets".
         "how", "what", "where", "when", "why", "whether",
         # Prepositions absent from `_PREPOSITIONS` (which lists only the ones
         # that can BE a relation). "an INPUT to drift" read as a kind named
         # "input to drift".
         # `of` is NOT here, and `_NP_TAIL` says why: it belongs to NAMES --
         # "the capital of France", "the ring of integers", "the field of
         # fractions". Listing it made a compound name unreadable, so an
         # appositive like "Paris the capital of France" lost the half of the
         # sentence that says what Paris IS. The four-content-word bound below
         # is what stops a genuine run-on, not a ban on the commonest word in
         # English naming.
         "to", "from", "with", "for", "into", "onto", "about", "per"}
    )
    _MAX_COMPLEMENT_WORDS = 4

    #: A bare pronoun or demonstrative NAMES NOTHING. "This is temperament
    #: forming" and "it is an INPUT" file claims about things called `this` and
    #: `it`, which no later sentence can ever be about. English resolves these
    #: from context the reader does not carry, so a claim anchored on one is not
    #: a claim about the world.
    #: ONLY words that POINT, never words that name. `each`, `one`, `both` and
    #: `note` were here and each of them can head a real subject -- "Each element
    #: has a single authority" is an ordinary claim and was being refused for the
    #: determiner in front of it.
    _EMPTY_SUBJECTS = frozenset({
        "this", "that", "these", "those", "it", "they", "there", "here",
        "he", "she", "we", "you", "i", "who", "what", "which",
        "something", "anything", "everything", "nothing",
        "someone", "anyone", "everyone", "none",
    })

    def _names_something(self, subject: str) -> bool:
        """Does the subject NAME a thing, or only point at one?"""
        words = [w for w in str(subject or "").strip().lower().split()
                 if w not in ("a", "an", "the")]
        return bool(words) and words[0] not in self._EMPTY_SUBJECTS

    def _is_bounded_complement(self, prop: str) -> bool:
        """Is what follows the copula a PHRASE, or the rest of the sentence?"""
        text = str(prop or "").strip()
        if not text:
            return False
        # A PREPOSITIONAL COMPLEMENT IS A RELATION, NOT A RUN-ON. "the cup is IN
        # the box" relates two things through the preposition and is read by
        # `_PREPOSITIONAL` below; bounding it away took the locative reading with
        # it, and with that the named existential decline of "a robin is in the
        # yard" -- which turned a negative control into a false proof.
        if self._PREPOSITIONAL.match(text):
            return True
        # An em-dash, colon or semicolon starts a new breath; what follows is
        # elaboration, not part of the complement.
        if any(mark in text for mark in ("—", "–", ":", ";")):
            return False
        words = [w.strip(",.").lower() for w in text.split() if w.strip(",.")]
        if any(w in self._COMPLEMENT_BREAKS or w in self._PREPOSITIONS
               for w in words):
            return False
        content = [w for w in words if w not in ("a", "an", "the")]
        return 0 < len(content) <= self._MAX_COMPLEMENT_WORDS

    #: "a TYPE of Y" names a Y. The classifier noun says what kind of thing the
    #: subject is and adds nothing to it, and it cost the complement two of its
    #: four words: "A peristaltic pump is a type of positive displacement pump"
    #: -- the way a definition most often opens -- read nothing at all, while
    #: "... is a positive displacement pump" read.
    _CLASSIFIER_OF = re.compile(
        r"(?i)^(?:a|an|one)\s+(?:type|kind|sort|variety|class|species)\s+of\s+(?P<rest>.+)$")
    #: What may follow a participle that narrows the noun before it.
    _NARROWING_NEXT = frozenset(
        ("in", "on", "at", "by", "for", "to", "as", "with", "from", "into", "of"))

    def _complement_head(self, prop: str) -> str:
        """The noun phrase a copular complement names, without what only narrows it.

        Three things lengthen a complement without changing what the subject IS:
          * a classifier -- "a type of Y", "a kind of Y" -- which names a Y;
          * a participle after the noun that narrows it -- "a pump USED FOR
            pumping fluids", "an animal FOUND IN Africa" -- a Y of a certain
            sort, still a Y;
          * a relative clause after the noun -- "a pump THAT can move fluids".
        Both are set aside, and the bound on the complement then judges the noun
        phrase itself. A participle BEFORE the noun ("a reinforced concrete
        beam") is not followed by a preposition and is left where it is; only a
        word observed as a verb, in a participle form, followed by a preposition,
        ends the phrase."""
        from core.semantics.genericity import _word_classes
        from core.semantics.lexical_normalization import deinflect_verb

        text = " ".join(str(prop or "").split())
        classified = self._CLASSIFIER_OF.match(text)
        if classified:
            text = f"a {classified.group('rest')}"
        words = text.split()
        for index in range(2, len(words) - 1):
            word = words[index].lower().strip(",")
            # A RELATIVE CLAUSE after the noun narrows it the same way: "a
            # rotary positive displacement pump THAT can move fluids" is a pump.
            if word in ("that", "which", "who"):
                return " ".join(words[:index]).rstrip(",")
            if not word.endswith(("ed", "en", "ing")):
                continue
            if words[index + 1].lower().strip(",") not in self._NARROWING_NEXT:
                continue
            if any("VERB" in _word_classes(base) for base in deinflect_verb(word)):
                return " ".join(words[:index]).rstrip(",")
        return text

    def _read_copular(self, match, *, negated: bool) -> Dict[str, Any]:
        """Classify a copular sentence BEFORE deciding how to represent it.

        The article alone is not a quantification cue. Reading "a" as universal
        turns "A robin is in the yard" into a law about all robins, so the
        proposition type is decided first and the representation follows from
        it.
        """
        subject = self._possessive_subject(match.group("subject"))
        prop = match.group("prop")
        determiner = match.groupdict().get("det")

        # A COMPLEMENT IS A PHRASE, NOT A REMAINDER. `_FACT` ends in `(.+)$`, so
        # whatever followed the copula became the property however long and
        # however structured it was:
        #   "Cognition is one body — not a bus between independent services."
        #      -> property `one body — not a bus between independent services`
        #   "There is no longer any path from the substrate to a generative model."
        #      -> property `no longer any path from the substrate to a generative model`
        # Each was stored as a class a thing belongs to. Bounding the complement
        # is what separates reading a claim from swallowing the rest of the line.
        # NONE, NOT A NODE WITH kind=None. Callers test `if not node`, and a
        # dict is truthy -- an empty-kind node travelled on as though it were a
        # reading.
        prop = self._complement_head(prop)
        if not self._is_bounded_complement(prop):
            return None
        if not self._names_something(subject):
            return None

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
            # THE CLASS IS WHAT REFUSED, SO THE CLASS IS WHAT IS ON TRIAL. If
            # `subject` really is an adjective this refusal is correct and the
            # entry survives being doubted once; if it was recorded ADJECTIVE in
            # error -- which bulk teaching did to every `isa` parent it saw --
            # then a perfectly ordinary sentence just failed because of it, and
            # that is precisely the evidence REFUTED is defined by.
            blame(subject, ADJECTIVE,
                  "read as the subject of a fact though observed ADJECTIVE")
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
                blame(other, ADJECTIVE,
                      "read as the object of a preposition though observed "
                      "ADJECTIVE")
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

        # WHAT THE COMPLEMENT IS *HERE*, NOT WHAT THE WORD USUALLY IS.
        #
        # This asked `_word_class(prop) == "NOUN"` — the word's MAJORITY class —
        # and refused the property reading outright. That is the same SUBTRACTIVE
        # failure `_word_class`'s own docstring records as the reason the lexicon
        # file was deleted ("`A filter separates particles.` read correctly while
        # `separates` was unknown and stopped reading once the file called it a
        # noun"), arriving again from memory instead of a file.
        #
        # Why the majority is the wrong question, measured on the live
        # vocabulary: `white` is ADJECTIVE 1 / NOUN 12, `red` 2/7, `closed`
        # 1/NOUN 8/VERB 3 — a dictionary has many noun senses for a colour and
        # one adjective sense. So the better the substrate learned a word, the
        # more certainly it concluded NOUN, and `Snow is white.` / `The circuit
        # is closed.` / `The vault is cold and heavy.` all read BEFORE the
        # vocabulary was warm and read NOTHING after it. The substrate got worse
        # at English by learning more of it.
        #
        # `complement_class` asks the question this branch actually needs, on the
        # structure first: a complement opened by a DETERMINER is a noun phrase
        # and so a kind; a BARE complement is predicative and is a property when
        # its head has EVER been observed as an adjective. Evidence permits, it
        # does not win a vote. A bare word never observed as an adjective but
        # observed as a noun is still refused — the original intent, kept.
        from core.semantics.relation_types import complement_class as _complement
        from core.semantics.genericity import NOUN as _NOUN, _word_classes
        if _complement(prop, _word_classes) is None and _word_class(prop) == _NOUN:
            # THE CLASS IS WHAT REFUSED, SO THE CLASS IS WHAT IS ON TRIAL — the
            # same rule the sibling branches above already follow, and the one
            # thing this branch never did. Without it the refusal was SILENT:
            # `depending()` came back with `blamed=[]`, nothing argued the class
            # down, and a word wrongly filed as a noun blocked every ordinary
            # sentence about it forever.
            blame(prop, _NOUN,
                  "read as a property though observed only as a NOUN")
            return {"kind": "unsupported",
                    "reason": "a noun cannot be a property",
                    "genericity": "n/a", "cue": f"{prop} is a known noun"}

        # A MODIFIED NOUN-PHRASE complement still names a kind by its head noun.
        # The genericity classifier only reads a bare "a/an NOUN" as denoting a
        # kind, so "X is an electrical component" was dropped as ambiguous and
        # the definitional sentence read as nothing. Classify by the head, but
        # keep the FULL class name (minus any elaborating tail) as the predicate
        # -- so "abelian group" survives and is never flattened to "group".
        class_np = self._head_np(prop)
        head = self._np_head(prop)
        classify_prop = f"a {head}" if head else class_np
        reading = classify_genericity(subject, classify_prop, determiner)

        if reading.genericity is Genericity.GENERIC_KIND:
            # A claim about a KIND. `_normalize` strips the complement's
            # article downstream, so "a bird" becomes the predicate `bird`.
            return {
                "kind": "universal",
                "p": subject,
                "q": class_np,
                "negated": negated,
                "genericity": reading.genericity.value,
                "cue": reading.cue,
                "transformations": list(reading.transformations),
            }

        if reading.genericity is Genericity.INSTANCE:
            return {
                "kind": "fact",
                "subject": subject,
                "prop": class_np,
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
        # "How many X ...?" -- a COUNT question: the unknown is a quantity. Parsed
        # so the counted kind (and any trailing relation) is available; the
        # substrate answers it only where it can enumerate, otherwise honest gap.
        hm = re.match(r"(?i)^how\s+many\s+(?P<x>[\w'-]+(?:\s+[\w'-]+){0,3}?)"
                      r"(?:\s+(?P<rest>.+?))?\s*\??\s*$", text.strip())
        if hm:
            return {"kind": "count", "target": hm.group("x").strip(),
                    "rest": (hm.group("rest") or "").strip() or None, "obj": None}
        # "Where/When is X?" -- a locative or temporal query: the unknown is the
        # place or time X stands in, so it is an OPEN goal keyed on that relation.
        wq = re.match(r"(?i)^(?P<w>where|when)\s+(?:is|are|was|were)\s+"
                      r"(?:an?\s+|the\s+)?(?P<x>.+?)\s*\??\s*$", text.strip())
        if wq:
            rel = "location" if wq.group("w").lower() == "where" else "time"
            return {"kind": "open", "subject": wq.group("x").strip(),
                    "relation": rel, "obj": None}
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
        # A SPACE BEFORE PUNCTUATION MEANS NOTHING IN ENGLISH, and extracted text
        # is full of it: a fetched page arrives as "A peristaltic pump , also
        # known as a roller pump , is ...", and every comma-set structure below
        # (appositives, relatives) looks for the comma against its word.
        text = re.sub(r"[ \t]+([,.;:!?])", r"\1", str(text))
        # A newline ends a unit too: extracted text arrives one paragraph/heading
        # per line, and a heading or list item often carries no full stop.
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", str(text).strip()):
            for segment in self._split_clauses(sentence):
              for clause in self._decompose(segment):
                # AN EMBEDDED RELATIVE WITH NO COMMA. "the pump that failed was
                # replaced" is two claims about the pump, and neither is
                # reachable while the sentence is read whole.
                embedded = self._EMBEDDED_RELATIVE.match(clause)
                candidates = [clause]
                if embedded:
                    candidates = self._relative_clauses(
                        embedded.group("head").strip(),
                        embedded.group("inner").strip())
                # A SHARED PREDICATE is said of each coordinated subject.
                candidates = [d for c in candidates
                              for d in self._distribute_subject(c)]
                for split in (self._appositive_clauses,
                              self._complement_relative_clauses,
                              self._ditransitive_clauses,
                              self._distribute_tail_coordination):
                    candidates = [d for c in candidates for d in split(c)]
                for candidate in candidates:
                  node = self._parse_statement(candidate)
                  if not node:
                    # ONE ADVERB SHOULD NOT COST A CLAIM. Tried only after the
                    # sentence as written has been refused, so nothing that
                    # already read can change its reading.
                    stripped = self._drop_preverbal_adverb(candidate)
                    node = (self._parse_statement(stripped)
                            if stripped != candidate else None)
                  if not node:
                    continue
                  for cp in self._expand_conjuncts(node):
                    # A CLASSIFICATION names a KIND, not a paragraph.
                    if str(cp.get("relation", "")).lower() in ("is", "are") and cp.get("obj"):
                        cp["obj"] = self._head_np(cp["obj"])
                    key = (str(cp.get("subject") or "").lower(), str(cp.get("relation", "")).lower(),
                           str(cp.get("obj") or "").lower(), cp.get("positive", True))
                    if key not in seen:
                        seen.add(key)
                        out.append(cp)
        return out

    #: Post-modifiers that continue a description but are not part of a class
    #: NAME. `of` is deliberately absent -- it belongs to names ("ring of
    #: integers", "field of fractions").
    _NP_TAIL = re.compile(
        r"(?i)(?:,|\s+(?:with|which|that|whose|having|where|containing|used|so|"
        r"in which|such that|defined|consisting|equipped|denoted|written|"
        r"relating|representing|describing|comprising|connecting|linking|"
        r"formed|based|derived|introduced|invented|characterized)\b)")

    def _head_np(self, phrase: str) -> str:
        """The head noun phrase of a complement -- the class -- without the
        relative/prepositional tail that elaborates rather than names it."""
        return self._NP_TAIL.split(str(phrase), 1)[0].strip() or str(phrase).strip()

    def _np_head(self, phrase: str) -> Optional[str]:
        """The HEAD noun of a determiner-led noun-phrase complement, or None if
        `phrase` is not one. "an electrical component" -> "component";
        "a non-linear two-terminal electrical component relating charge" ->
        "component". A determiner marks the complement as naming a KIND (an NP),
        which is what separates it from a bare adjective property ("mechanically
        flexible", no determiner -> None). English NP heads are final, so after
        dropping the elaborating tail the head is the last word of the core.

        Used ONLY to decide representability: the genericity classifier
        recognises a bare "a/an NOUN" as denoting a kind but drops a MODIFIED NP
        as ambiguous, so a definitional "X is an electrical component" read as
        nothing. The full class name is kept for the stored fact -- the head is
        never substituted for it -- so "abelian group" is not flattened to
        "group"."""
        core = self._head_np(phrase)
        m = re.match(r"(?i)^(?:a|an|the)\s+(.+)$", core)
        if not m:
            return None
        words = m.group(1).split()
        return words[-1] if words else None

    #: Words that JOIN two claims. Splitting on one yields both sides as
    #: clauses; the relation BETWEEN them ("because", "although") is not
    #: represented, and that is stated rather than hidden -- two claims read is
    #: strictly more than one sentence refused, and the causal link was never
    #: representable either way.
    _SUBORDINATORS = re.compile(
        r"(?i)(?:^|\s)(?:because|although|though|whereas|while|unless|since|"
        r"whenever|wherever|when|if)\s+")
    #: A parenthetical is an aside, not part of the claim carrying it.
    _PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
    #: A breath break. What follows elaborates; each side is read on its own.
    _BREATH = re.compile(r"\s*[—–:;]\s*")
    #: `HEAD <relative> REST` with no comma: "the pump that failed was replaced".
    _EMBEDDED_RELATIVE = re.compile(
        r"(?i)^(?P<head>(?:the |a |an )?[\w'-]+(?:\s+[\w'-]+){0,2})\s+"
        r"(?P<rel>which|who|that|whose)\s+(?P<inner>.+)$")

    def _split_clauses(self, sentence: str) -> List[str]:
        """One sentence into the CLAUSES it carries, before any of them is read.

        THIS IS WHERE LENGTH IS WON OR LOST. A twenty-five word sentence is not
        one claim and cannot be read as one; refusing it loses the two or three
        perfectly ordinary claims inside it. Measured before this existed: 0 of
        86 sentences of 19 words or more produced any reading at all, because
        every one of them carried a coordinator, a relative pronoun or a
        subordinate clause and the single-clause reader correctly refused the
        lot.

        Segmentation is a SEPARATE question from reading, and keeping them apart
        is what lets the reader stay strict: this decides where one claim ends,
        and the reader then judges each piece on its own merits, refusing the
        pieces that are still not claims.
        """
        text = self._PARENTHETICAL.sub(" ", str(sentence).strip().rstrip(".!?"))
        pieces = [p.strip() for p in self._BREATH.split(text) if p.strip()]

        out: List[str] = []
        for piece in pieces:
            # A subordinator joins two claims; both sides are kept.
            parts = [p.strip(" ,") for p in self._SUBORDINATORS.split(piece)]
            for part in (p for p in parts if p):
                out.extend(self._split_coordinated_clauses(part))
        return out or [text]

    #: Where a relative clause ENDS and the main predicate resumes. "the valve
    #: which LEAKED *is* closed" -- the main clause picks up at the copula or
    #: auxiliary that follows the relative's own verb.
    _MAIN_RESUMES = re.compile(
        r"(?i)^(?P<inner>.+?)\s+(?P<main>(?:is|are|am|was|were|has|have|had)\b.*)$")

    def _relative_clauses(self, head: str, inner: str) -> List[str]:
        """`the valve` + `leaked is closed` -> two claims about the valve.

        BOTH, NOT ONE GLUED TOGETHER. Offering `the valve leaked is closed` as a
        single candidate let it read as one atom `valve_leaked_closed`, which
        states neither of the two things the sentence says. A relative clause
        makes a claim about the head and the main clause makes another; the
        whole point of pulling it apart is that each is separately true.
        """
        split = self._MAIN_RESUMES.match(inner)
        if not split:
            # No main predicate after the relative: the sentence is the relative
            # clause itself ("the pump that failed"), which states one claim.
            return [f"{head} {inner}"]
        return [f"{head} {split.group('inner').strip()}",
                f"{head} {split.group('main').strip()}"]

    def _split_coordinated_clauses(self, piece: str) -> List[str]:
        """`X is A and Y is B` -> two clauses; `X is A and B` is left alone.

        A coordinator joins two CLAUSES only when each side can stand as one.
        The complement case ("a whale is a mammal and a vertebrate") is the
        existing `_decompose` path and is left to it, so this never splits a
        conjunction that shares its subject.
        """
        for joiner in (" and ", " or ", " but "):
            head, sep, tail = piece.partition(joiner)
            if not sep:
                continue
            if self._COPULA_RE.search(head) and self._COPULA_RE.search(tail):
                return (self._split_coordinated_clauses(head.strip())
                        + self._split_coordinated_clauses(tail.strip()))
        return [piece.strip()]

    _COPULA_RE = re.compile(r"(?i)(?:^|\s)(?:is|are|am|was|were)(?:\s|$)")

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
        # extraction that is the ISA edge whale->mammal. A NEGATED universal ("no
        # mammal is a bird") is the disjointness edge mammal-/->bird, kept as a
        # negative ISA so the reasoner can refute an instance: rex isa mammal and
        # mammal is-not a bird ⊢ rex is not a bird. clause_parts deliberately
        # leaves universals to the formal side, so read_all lifts the edge here.
        if (node or {}).get("kind") == "universal":
            return [{"subject": node["p"], "relation": "is", "obj": node["q"],
                     "positive": not node.get("negated", False)}]
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
