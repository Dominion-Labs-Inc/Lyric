#!/usr/bin/env python3
"""The semantic type of a relation, kept apart from the words that expressed it.

    THE MACHINE READS A SPAN. THIS SAYS WHAT THE SPAN MEANS. THE ALGEBRA SAYS
    WHAT MAY BE INFERRED FROM IT.

`sentence_machine` recovers a predicate SPAN -- the tokens "made of", "lives
in", "is a" -- as pure syntax. It must not decide what that span MEANS: whether
`made of` is the same KIND of relation as `is a` is a fact about the world, not
about token positions, and collapsing every predicate into one "is" edge is
exactly the contamination that poisons inference at scale (`oak -is-> wood`
chaining into `oak -is-> animal`).

This is the semantic authority for that decision, a sibling of `genericity`
(which owns whether a sentence speaks of a KIND). It maps a surface predicate to
a typed `SemanticRelation`, and it records for each type the algebraic
properties the reasoner needs -- transitivity, inheritance down ISA, symmetry,
inverse. It NEVER performs inference; `core.reasoning.relation_algebra` consumes
these properties. Keeping the properties WITH the type, and the inference apart,
is the same split as reader/ingress/reasoning.

    A TYPE IS A CLAIM, AND A CLAIM NEEDS A SOURCE.

Every mapping records where it came from. The surface->type table below is a
CURATED linguistic mapping (`source="curated_lexical_map"`); a teacher or an
imported ontology may add mappings with their own provenance. An unrecognised
predicate is not forced into a taxonomic edge -- it becomes `RELATED_TO`, which
carries the surface verb and licenses NO inference, so an unknown relation is
inert rather than contaminating.

NO MODEL IS INVOLVED. The mapping is data; the classification is a lookup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SemanticRelation(Enum):
    """The relation a proposition asserts, by KIND.

    Distinct from `core.reasoning.bayesian_uncertainty.RelationType`, which types
    how BELIEFS relate (supports/contradicts). This types how CONCEPTS relate.
    """

    # ── taxonomic ────────────────────────────────────────────────────────
    ISA = "isa"                    # kind -> superkind: robin ISA bird
    INSTANCE_OF = "instance_of"    # individual -> kind: Fido INSTANCE_OF dog

    # ── mereological (part / whole / membership) ─────────────────────────
    PART_OF = "part_of"            # wheel PART_OF car
    HAS_PART = "has_part"          # car HAS_PART wheel   (inverse of PART_OF)
    MEMBER_OF = "member_of"        # robin MEMBER_OF flock
    HAS_MEMBER = "has_member"      # flock HAS_MEMBER robin
    HAS_COUNT = "has_count"        # a group HAS_COUNT 3: how many there are
    HAS_ADDEND = "has_addend"      # 21 HAS_ADDEND 20, 21 HAS_ADDEND 1: "twenty-one"
    HAS_FACTOR = "has_factor"      # 200 HAS_FACTOR 2, 200 HAS_FACTOR 100: "two hundred"
    HAS_RANK = "has_rank"          # the first dog HAS_RANK 1: its place in an order
    # Arithmetic said in words: each operation's value is a thing, and each number it is made of stands in its
    # own place, so "two plus two" is the sum whose augend is 2 and whose addend is 2 -- two facts, not one said
    # twice -- and "seven minus four" is not "four minus seven".
    EQUALS = "equals"              # two plus three EQUALS 5: the same number (symmetric)
    HAS_AUGEND = "has_augend"      # 2 + 3 HAS_AUGEND 2: the number added to (HAS_ADDEND 3 is the one added)
    HAS_MINUEND = "has_minuend"    # 7 - 4 HAS_MINUEND 7: the number taken from
    HAS_SUBTRAHEND = "has_subtrahend"  # 7 - 4 HAS_SUBTRAHEND 4: the number taken away
    HAS_MULTIPLICAND = "has_multiplicand"  # 3 × 4 HAS_MULTIPLICAND 3: the number multiplied (HAS_FACTOR 4: by)
    HAS_DIVIDEND = "has_dividend"  # 12 / 3 HAS_DIVIDEND 12: the number divided
    HAS_DIVISOR = "has_divisor"    # 12 / 3 HAS_DIVISOR 3: the number it is divided by
    HAS_BASE = "has_base"          # 2^10 HAS_BASE 2: the number raised to a power
    HAS_EXPONENT = "has_exponent"  # 2^10 HAS_EXPONENT 10: the power it is raised to
    HAS_RADICAND = "has_radicand"  # √16 HAS_RADICAND 16: the number a root is taken of
    HAS_INDEX = "has_index"        # √16 HAS_INDEX 2: which root, square (2) or cube (3)
    HAS_ARGUMENT = "has_argument"  # the sine of x HAS_ARGUMENT x: what a function is applied to

    # ── compositional (substance) ────────────────────────────────────────
    MADE_OF = "made_of"            # cabinet MADE_OF wood
    MATERIAL_OF = "material_of"    # wood MATERIAL_OF cabinet (inverse)

    # ── spatial ──────────────────────────────────────────────────────────
    LOCATED_IN = "located_in"      # robin LOCATED_IN nest (contextual)
    CONTAINS = "contains"          # nest CONTAINS robin (inverse)
    LOCATED_AT = "located_at"      # meeting LOCATED_AT office
    ADJACENT_TO = "adjacent_to"    # kitchen ADJACENT_TO hall (symmetric)
    NEAR = "near"                  # house NEAR river: close, not touching (symmetric)
    ABOVE = "above"                # lamp ABOVE table
    BELOW = "below"                # cat BELOW table (inverse)
    LEFT_OF = "left_of"            # cup LEFT_OF plate
    RIGHT_OF = "right_of"          # plate RIGHT_OF cup (inverse)
    IN_FRONT_OF = "in_front_of"    # car IN_FRONT_OF house
    BEHIND = "behind"              # house BEHIND car (inverse)
    BETWEEN = "between"            # dog BETWEEN a group whose members it is between

    # ── attribute / property ─────────────────────────────────────────────
    HAS_PROPERTY = "has_property"  # snow HAS_PROPERTY white
    PROPERTY_OF = "property_of"    # white PROPERTY_OF snow (inverse)
    HAS_DEGREE = "has_degree"      # dog HAS_DEGREE d, d INSTANCE_OF big: how big the dog is
    EXCEEDS = "exceeds"            # one degree EXCEEDS another: "bigger than"
    GREATEST_OF = "greatest_of"    # a degree GREATEST_OF dog: the most of it among dogs
    HAS_MEASURE = "has_measure"    # a degree of long HAS_MEASURE two meters: how much it is

    # ── causal / conditional ─────────────────────────────────────────────
    CAUSES = "causes"              # rain CAUSES wetness
    CAUSED_BY = "caused_by"        # wetness CAUSED_BY rain (inverse)
    ENABLES = "enables"            # key ENABLES opening
    PREVENTS = "prevents"          # lock PREVENTS opening
    REQUIRES = "requires"          # combustion REQUIRES oxygen
    REQUIRED_BY = "required_by"    # oxygen REQUIRED_BY combustion (inverse)

    # ── functional / productive ──────────────────────────────────────────
    USED_FOR = "used_for"          # hammer USED_FOR driving_nails
    HAS_FUNCTION = "has_function"  # heart HAS_FUNCTION pumping_blood
    PRODUCES = "produces"          # tree PRODUCES oxygen
    PRODUCED_BY = "produced_by"    # oxygen PRODUCED_BY tree (inverse)
    CREATES = "creates"            # carpenter CREATES cabinet

    # ── behavioural / possessive ─────────────────────────────────────────
    EATS = "eats"                  # robin EATS insects
    EATEN_BY = "eaten_by"          # insects EATEN_BY robin (inverse)
    OWNS = "owns"                  # person OWNS car
    OWNED_BY = "owned_by"          # car OWNED_BY person (inverse)

    # ── lexical / definitional ───────────────────────────────────────────
    SYNONYM_OF = "synonym_of"      # (symmetric)
    ANTONYM_OF = "antonym_of"      # (symmetric)
    DEFINED_AS = "defined_as"      # function DEFINED_AS reusable_block
    DERIVED_FROM = "derived_from"  # oxidation DERIVED_FROM oxygen

    # ── temporal ─────────────────────────────────────────────────────────
    PRECEDES = "precedes"          # ignition PRECEDES combustion
    FOLLOWS = "follows"            # combustion FOLLOWS ignition (inverse)
    DURING = "during"              # a running DURING now: at the same time as
    # ── event participants ───────────────────────────────────────────────
    DONE_BY = "done_by"            # tying DONE_BY listener: who did the event
    DONE_TO = "done_to"            # tying DONE_TO shoe: what it was done to
    DONE_WITH = "done_with"        # cutting DONE_WITH knife: what it was done with
    MOVES_TO = "moves_to"          # a going TO: where the event ends
    MOVES_INTO = "moves_into"      # into: ends inside it
    MOVES_ONTO = "moves_onto"      # onto: ends on it
    MOVES_FROM = "moves_from"      # from: where the event starts
    MOVES_OUT_OF = "moves_out_of"  # out of: starts inside it
    MOVES_THROUGH = "moves_through"# through it
    MOVES_ACROSS = "moves_across"  # across it
    MOVES_OVER = "moves_over"      # over it
    MOVES_AROUND = "moves_around"  # around it
    MOVES_TOWARD = "moves_toward"  # toward it, not always reaching it
    MOVES_UP = "moves_up"          # up it
    MOVES_DOWN = "moves_down"      # down it
    LASTS_UNTIL = "lasts_until"    # an event and the time it lasts until
    LASTS_SINCE = "lasts_since"    # an event and the time it has lasted since
    LASTS_FOR = "lasts_for"        # an event and how long it lasts
    DONE_FOR = "done_for"          # an event and whom it was done for
    RECEIVED_BY = "received_by"    # a giving RECEIVED_BY Rex: who gets what the event passes
    HAS_PURPOSE = "has_purpose"      # an event and the event it is meant to bring about
    ABOUT = "about"                # a thing and what it is about
    SIMILAR_TO = "similar_to"      # a thing and what it is like
    OTHER_THAN = "other_than"      # someone OTHER_THAN Tom: "someone else" (symmetric)
    NAMED = "named"                # the speaker NAMED tom: "My name is Tom."
    COMES_FROM = "comes_from"      # the speaker COMES_FROM paris: "I am from Paris."
    STATE_OF = "state_of"          # a being open STATE_OF door: whose state it is

    # ── dispositional ────────────────────────────────────────────────────
    CAPABLE_OF = "capable_of"      # a disposition/ability: birds CAPABLE_OF fly

    # ── the honest fallback ──────────────────────────────────────────────
    RELATED_TO = "related_to"      # an unrecognised verb: inert, licenses nothing


class Transitivity(Enum):
    """Whether A -r-> B -r-> C entails A -r-> C.

    The middle state is the important one: some relations (PART_OF, LOCATED_IN)
    ARE transitive in some ontologies/contexts and not others, and assuming they
    always chain is exactly the contamination this whole layer exists to stop.
    ONTOLOGY_DEFINED means "only when a context explicitly licenses it" -- the
    conservative default is NOT to chain.
    """
    ALWAYS = "always"                    # logically safe (ISA)
    NEVER = "never"                      # chaining is unsound
    ONTOLOGY_DEFINED = "ontology_defined"  # licensed only in context


class EvidenceBehavior(Enum):
    """What a relation licenses the reasoning layer to DERIVE from an observation.
    Kept beside the type so the knowledge layer never has to guess."""
    LOGICAL_DERIVATION = "logical_derivation"   # transitive closure (ISA)
    INHERITANCE = "inheritance"                 # passes down ISA (HAS_PART, EATS)
    INVERSE_DERIVATION = "inverse_derivation"   # the inverse edge may be derived
    ONTOLOGY_DEFINED = "ontology_defined"       # only a context may license it
    NONE = "none"                               # observation stands alone


@dataclass(frozen=True)
class RelationSpec:
    """One relation type, its surface forms, and the algebra it licenses.

    The algebraic properties are what the reasoner reads; nothing here reasons.
      transitivity -- ALWAYS / NEVER / ONTOLOGY_DEFINED (see Transitivity)
      inheritable  -- A ISA B, B r C |= A r C           (r inherits down a kind)
      symmetric    -- A r B          |= B r A
      inverse      -- the relation of B r' A, DERIVABLE (not observed) from A r B
      generic_safe -- a bare indefinite subject may be read as a universal law
                      about the KIND, rather than one existential situation.
    """

    name: SemanticRelation
    #: Surface predicates that map here. Longest-match wins, so "is made of"
    #: beats "is". CURATED; provenance recorded on every classification.
    surface_forms: FrozenSet[str]
    inverse: Optional[SemanticRelation] = None
    transitivity: Transitivity = Transitivity.NEVER
    inheritable: bool = False
    symmetric: bool = False
    generic_safe: bool = True
    gloss: str = ""

    @property
    def transitive(self) -> bool:
        """Back-compat: chains WITHOUT a context only when ALWAYS transitive."""
        return self.transitivity is Transitivity.ALWAYS

    def evidence_behaviors(self) -> "FrozenSet[EvidenceBehavior]":
        """Everything this relation licenses the reasoner to derive."""
        out = set()
        if self.transitivity is Transitivity.ALWAYS:
            out.add(EvidenceBehavior.LOGICAL_DERIVATION)
        elif self.transitivity is Transitivity.ONTOLOGY_DEFINED:
            out.add(EvidenceBehavior.ONTOLOGY_DEFINED)
        if self.inheritable:
            out.add(EvidenceBehavior.INHERITANCE)
        if self.inverse is not None:
            out.add(EvidenceBehavior.INVERSE_DERIVATION)
        return frozenset(out) or frozenset({EvidenceBehavior.NONE})


#: THE ONTOLOGY. Conservative by construction: a flag is set only where the
#: inference it licenses is sound for the type in general, because a wrong
#: composition rule contaminates every chain that touches it, and the whole
#: point of typing relations is to stop that.
_SPECS: Tuple[RelationSpec, ...] = (
    # taxonomic
    RelationSpec(SemanticRelation.ISA,
                 frozenset({"is a", "is an", "are a", "are", "is kind of",
                            "is a kind of", "is type of", "is a type of",
                            "is sort of", "is a sort of", "isa"}),
                 transitivity=Transitivity.ALWAYS, gloss="subsumption between kinds"),
    RelationSpec(SemanticRelation.INSTANCE_OF,
                 frozenset({"is instance of", "is an instance of",
                            "is the", "instance of"}),
                 gloss="an individual falls under a kind"),
    # mereological
    RelationSpec(SemanticRelation.PART_OF,
                 frozenset({"is part of", "part of", "is a part of"}),
                 inverse=SemanticRelation.HAS_PART, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 gloss="proper part of a whole"),
    RelationSpec(SemanticRelation.HAS_PART,
                 frozenset({"has part", "has a", "have", "has", "consists of",
                            "is made up of", "comprises"}),
                 inverse=SemanticRelation.PART_OF, inheritable=True,
                 gloss="a whole has a part"),
    RelationSpec(SemanticRelation.MEMBER_OF,
                 frozenset({"is member of", "is a member of", "member of",
                            "belongs to"}),
                 inverse=SemanticRelation.HAS_MEMBER,
                 gloss="an element of a collection (NOT transitive)"),
    RelationSpec(SemanticRelation.HAS_MEMBER,
                 frozenset({"has member", "has members", "includes"}),
                 inverse=SemanticRelation.MEMBER_OF,
                 gloss="a collection has an element"),
    # compositional
    RelationSpec(SemanticRelation.MADE_OF,
                 frozenset({"is made of", "made of", "made from",
                            "is made from", "composed of", "is composed of",
                            "built from", "is built from", "consists of"}),
                 inverse=SemanticRelation.MATERIAL_OF,
                 gloss="substance a thing is composed of (does NOT imply ISA)"),
    RelationSpec(SemanticRelation.MATERIAL_OF,
                 frozenset({"is material of", "material of"}),
                 inverse=SemanticRelation.MADE_OF),
    # spatial
    RelationSpec(SemanticRelation.LOCATED_IN,
                 frozenset({"is in", "in", "lives in", "located in",
                            "is located in", "found in", "is found in",
                            "inside", "resides in", "sits in", "dwells in"}),
                 inverse=SemanticRelation.CONTAINS, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 generic_safe=False,
                 gloss="containment location (contextual, not a kind law)"),
    RelationSpec(SemanticRelation.CONTAINS,
                 frozenset({"contains", "holds", "encloses"}),
                 inverse=SemanticRelation.LOCATED_IN, generic_safe=False),
    RelationSpec(SemanticRelation.LOCATED_AT,
                 frozenset({"is at", "at", "located at", "is located at",
                            "on", "is on", "on top of", "sits on", "rests on"}),
                 generic_safe=False),
    RelationSpec(SemanticRelation.ADJACENT_TO,
                 frozenset({"next to", "adjacent to", "beside", "near",
                            "borders", "is next to", "is adjacent to"}),
                 symmetric=True, generic_safe=False),
    # Where one thing is against another, as sight finds it too (`left_of` and
    # `above` between the regions of a picture). NO SURFACE FORMS: the English
    # for them is learned from lessons. Each has its inverse; none chains unless
    # a context licenses it, since "above" held of places, not kinds, is contextual.
    RelationSpec(SemanticRelation.ABOVE, frozenset(), inverse=SemanticRelation.BELOW,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="higher than another thing"),
    RelationSpec(SemanticRelation.BELOW, frozenset(), inverse=SemanticRelation.ABOVE,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="lower than another thing"),
    RelationSpec(SemanticRelation.LEFT_OF, frozenset(), inverse=SemanticRelation.RIGHT_OF,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="to the left of another thing"),
    RelationSpec(SemanticRelation.RIGHT_OF, frozenset(), inverse=SemanticRelation.LEFT_OF,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="to the right of another thing"),
    RelationSpec(SemanticRelation.IN_FRONT_OF, frozenset(), inverse=SemanticRelation.BEHIND,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="nearer the one looking than another thing"),
    RelationSpec(SemanticRelation.BEHIND, frozenset(), inverse=SemanticRelation.IN_FRONT_OF,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="farther from the one looking than another thing"),
    RelationSpec(SemanticRelation.BETWEEN, frozenset(), generic_safe=False,
                 gloss="between the members of a group"),
    RelationSpec(SemanticRelation.NEAR, frozenset(), symmetric=True, generic_safe=False,
                 gloss="close to another thing, not touching it"),
    # How many there are of a group ("three dogs": a group of dogs, and 3). The
    # count is a number, a term of its own; nothing chains through it.
    RelationSpec(SemanticRelation.HAS_COUNT, frozenset(), generic_safe=False,
                 gloss="how many members a group has"),
    # A number English builds from numbers: "twenty-one" is the number whose
    # addends are 20 and 1, "two hundred" the one whose factors are 2 and 100.
    # A meaning is written one way with each such number as its value (21, 200).
    RelationSpec(SemanticRelation.HAS_ADDEND, frozenset(), generic_safe=False,
                 gloss="a number and one of the numbers it is the sum of"),
    RelationSpec(SemanticRelation.HAS_FACTOR, frozenset(), generic_safe=False,
                 gloss="a number and one of the numbers it is the product of"),
    RelationSpec(SemanticRelation.HAS_RANK, frozenset(), generic_safe=False,
                 gloss="a thing and its place in an order"),
    # Arithmetic said in words: an operation's value and the numbers it is made of, each in its own place. The
    # symbolic mathematics faculty works these out; nothing chains through them. NO SURFACE FORMS: learned.
    RelationSpec(SemanticRelation.EQUALS, frozenset(), symmetric=True,
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="two values that are the same number"),
    RelationSpec(SemanticRelation.HAS_AUGEND, frozenset(), generic_safe=False,
                 gloss="a sum and the number added to"),
    RelationSpec(SemanticRelation.HAS_MINUEND, frozenset(), generic_safe=False,
                 gloss="a difference and the number taken from"),
    RelationSpec(SemanticRelation.HAS_SUBTRAHEND, frozenset(), generic_safe=False,
                 gloss="a difference and the number taken away"),
    RelationSpec(SemanticRelation.HAS_MULTIPLICAND, frozenset(), generic_safe=False,
                 gloss="a product and the number multiplied"),
    RelationSpec(SemanticRelation.HAS_DIVIDEND, frozenset(), generic_safe=False,
                 gloss="a quotient and the number divided"),
    RelationSpec(SemanticRelation.HAS_DIVISOR, frozenset(), generic_safe=False,
                 gloss="a quotient and the number it is divided by"),
    RelationSpec(SemanticRelation.HAS_BASE, frozenset(), generic_safe=False,
                 gloss="a power and the number raised"),
    RelationSpec(SemanticRelation.HAS_EXPONENT, frozenset(), generic_safe=False,
                 gloss="a power and the power it is raised to"),
    RelationSpec(SemanticRelation.HAS_RADICAND, frozenset(), generic_safe=False,
                 gloss="a root and the number it is taken of"),
    RelationSpec(SemanticRelation.HAS_INDEX, frozenset(), generic_safe=False,
                 gloss="a root and which root it is"),
    RelationSpec(SemanticRelation.HAS_ARGUMENT, frozenset(), generic_safe=False,
                 gloss="a function's value and what the function is applied to"),
    # attribute
    RelationSpec(SemanticRelation.HAS_PROPERTY,
                 frozenset({"has property", "is"}),   # bare copula + adjective
                 inverse=SemanticRelation.PROPERTY_OF, inheritable=True,
                 gloss="a quality of the subject"),
    RelationSpec(SemanticRelation.PROPERTY_OF,
                 frozenset({"is property of", "property of"}),
                 inverse=SemanticRelation.HAS_PROPERTY),
    # Comparison by degrees: a thing has a degree of a property, and degrees of
    # one property are compared. "The dog is bigger than the cat." is the dog's
    # degree of big exceeding the cat's. NO SURFACE FORMS: learned from lessons.
    RelationSpec(SemanticRelation.HAS_DEGREE, frozenset(), generic_safe=False,
                 gloss="a thing and its degree of a property"),
    RelationSpec(SemanticRelation.EXCEEDS, frozenset(),
                 transitivity=Transitivity.ONTOLOGY_DEFINED, generic_safe=False,
                 gloss="one degree of a property, or one number, more than another"),
    RelationSpec(SemanticRelation.GREATEST_OF, frozenset(), generic_safe=False,
                 gloss="a degree the most of its property among the things of a kind"),
    # "two meters long": the degree of long, and the amount it measures.
    RelationSpec(SemanticRelation.HAS_MEASURE, frozenset(), generic_safe=False,
                 gloss="a degree and the amount it measures"),
    # causal
    RelationSpec(SemanticRelation.CAUSES,
                 frozenset({"causes", "cause", "leads to", "results in",
                            "brings about", "induces"}),
                 inverse=SemanticRelation.CAUSED_BY, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 gloss="one thing brings another about"),
    RelationSpec(SemanticRelation.CAUSED_BY,
                 frozenset({"is caused by", "caused by", "results from",
                            "due to", "stems from"}),
                 inverse=SemanticRelation.CAUSES),
    RelationSpec(SemanticRelation.ENABLES,
                 frozenset({"enables", "allows", "permits", "facilitates"})),
    RelationSpec(SemanticRelation.PREVENTS,
                 frozenset({"prevents", "stops", "blocks", "inhibits"})),
    RelationSpec(SemanticRelation.REQUIRES,
                 frozenset({"requires", "needs", "depends on", "presupposes"}),
                 inverse=SemanticRelation.REQUIRED_BY, inheritable=True),
    RelationSpec(SemanticRelation.REQUIRED_BY,
                 frozenset({"is required by", "required by"}),
                 inverse=SemanticRelation.REQUIRES),
    # functional
    RelationSpec(SemanticRelation.USED_FOR,
                 frozenset({"is used for", "used for", "used to", "for"}),
                 inheritable=True, gloss="purpose the thing serves"),
    RelationSpec(SemanticRelation.HAS_FUNCTION,
                 frozenset({"functions as", "serves as", "acts as",
                            "has function", "is used as"}),
                 inheritable=True),
    RelationSpec(SemanticRelation.PRODUCES,
                 frozenset({"produces", "generates", "yields", "emits",
                            "gives off"}),
                 inverse=SemanticRelation.PRODUCED_BY,
                 gloss="a thing yields an output (does NOT imply ISA)"),
    RelationSpec(SemanticRelation.PRODUCED_BY,
                 frozenset({"is produced by", "produced by"}),
                 inverse=SemanticRelation.PRODUCES),
    RelationSpec(SemanticRelation.CREATES,
                 frozenset({"creates", "makes", "builds", "constructs",
                            "manufactures", "assembles"}),
                 gloss="an agent brings an artefact into being"),
    # behavioural / possessive
    RelationSpec(SemanticRelation.EATS,
                 frozenset({"eats", "eat", "feeds on", "preys on", "consumes"}),
                 inverse=SemanticRelation.EATEN_BY, inheritable=True),
    RelationSpec(SemanticRelation.EATEN_BY,
                 frozenset({"is eaten by", "eaten by"}),
                 inverse=SemanticRelation.EATS),
    RelationSpec(SemanticRelation.OWNS,
                 frozenset({"owns", "possesses"}),
                 inverse=SemanticRelation.OWNED_BY, generic_safe=False),
    RelationSpec(SemanticRelation.OWNED_BY,
                 frozenset({"is owned by", "owned by", "belongs to"}),
                 inverse=SemanticRelation.OWNS, generic_safe=False),
    # lexical
    RelationSpec(SemanticRelation.SYNONYM_OF,
                 frozenset({"means", "is synonym of", "same as",
                            "is the same as", "is synonymous with"}),
                 symmetric=True, transitivity=Transitivity.ONTOLOGY_DEFINED),
    RelationSpec(SemanticRelation.ANTONYM_OF,
                 frozenset({"is opposite of", "antonym of",
                            "is the opposite of", "opposite of"}),
                 symmetric=True),
    RelationSpec(SemanticRelation.DEFINED_AS,
                 frozenset({"is defined as", "defined as", "refers to",
                            "denotes"})),
    RelationSpec(SemanticRelation.DERIVED_FROM,
                 frozenset({"is derived from", "derived from", "comes from",
                            "originates from"})),
    # temporal
    RelationSpec(SemanticRelation.PRECEDES,
                 frozenset({"precedes", "comes before", "is before"}),
                 inverse=SemanticRelation.FOLLOWS, transitivity=Transitivity.ONTOLOGY_DEFINED,
                 generic_safe=False),
    RelationSpec(SemanticRelation.FOLLOWS,
                 frozenset({"follows", "comes after", "is after"}),
                 inverse=SemanticRelation.PRECEDES, generic_safe=False),
    RelationSpec(SemanticRelation.DURING, frozenset(), generic_safe=False,
                 gloss="an event or state at the same time as another, or as a time"),
    # event participants. "Tie your shoe." is a tying, done by the listener, done
    # to the shoe, and no other kind can say who did an event or what it was done
    # to. NO SURFACE FORMS: which English says them is learned, not written here.
    # Nothing chains through them, nothing inherits them and neither has an
    # inverse, so a participant stays a fact about that one event.
    RelationSpec(SemanticRelation.DONE_BY, frozenset(), generic_safe=False,
                 gloss="an event and who did it"),
    RelationSpec(SemanticRelation.DONE_TO, frozenset(), generic_safe=False,
                 gloss="an event and what it was done to"),
    RelationSpec(SemanticRelation.DONE_WITH, frozenset(), generic_safe=False,
                 gloss="an event and what it was done with"),
    # Where an event goes, when, how long, for whom, and what a thing is about or
    # like. Each a kind of its own, as English tells "into the house" from "to the
    # house". NO SURFACE FORMS: learned from lessons.
    RelationSpec(SemanticRelation.MOVES_TO, frozenset(), generic_safe=False,
                 gloss="a going TO: where the event ends"),
    RelationSpec(SemanticRelation.MOVES_INTO, frozenset(), generic_safe=False,
                 gloss="into: ends inside it"),
    RelationSpec(SemanticRelation.MOVES_ONTO, frozenset(), generic_safe=False,
                 gloss="onto: ends on it"),
    RelationSpec(SemanticRelation.MOVES_FROM, frozenset(), generic_safe=False,
                 gloss="from: where the event starts"),
    RelationSpec(SemanticRelation.MOVES_OUT_OF, frozenset(), generic_safe=False,
                 gloss="out of: starts inside it"),
    RelationSpec(SemanticRelation.MOVES_THROUGH, frozenset(), generic_safe=False,
                 gloss="through it"),
    RelationSpec(SemanticRelation.MOVES_ACROSS, frozenset(), generic_safe=False,
                 gloss="across it"),
    RelationSpec(SemanticRelation.MOVES_OVER, frozenset(), generic_safe=False,
                 gloss="over it"),
    RelationSpec(SemanticRelation.MOVES_AROUND, frozenset(), generic_safe=False,
                 gloss="around it"),
    RelationSpec(SemanticRelation.MOVES_TOWARD, frozenset(), generic_safe=False,
                 gloss="toward it, not always reaching it"),
    RelationSpec(SemanticRelation.MOVES_UP, frozenset(), generic_safe=False,
                 gloss="up it"),
    RelationSpec(SemanticRelation.MOVES_DOWN, frozenset(), generic_safe=False,
                 gloss="down it"),
    RelationSpec(SemanticRelation.LASTS_UNTIL, frozenset(), generic_safe=False,
                 gloss="an event and the time it lasts until"),
    RelationSpec(SemanticRelation.LASTS_SINCE, frozenset(), generic_safe=False,
                 gloss="an event and the time it has lasted since"),
    RelationSpec(SemanticRelation.LASTS_FOR, frozenset(), generic_safe=False,
                 gloss="an event and how long it lasts"),
    RelationSpec(SemanticRelation.DONE_FOR, frozenset(), generic_safe=False,
                 gloss="an event and whom it was done for"),
    RelationSpec(SemanticRelation.RECEIVED_BY, frozenset(), generic_safe=False,
                 gloss="an event and who receives what it passes"),
    RelationSpec(SemanticRelation.HAS_PURPOSE, frozenset(), generic_safe=False,
                 gloss="an event and the event it is meant to bring about"),
    RelationSpec(SemanticRelation.ABOUT, frozenset(), generic_safe=False,
                 gloss="a thing and what it is about"),
    RelationSpec(SemanticRelation.SIMILAR_TO, frozenset(), generic_safe=False, symmetric=True,
                 gloss="a thing and what it is like"),
    # "someone else", "the other dog". Denied of an unknown, as "Nothing is in
    # the box." denies it of anything: "Only Tom can swim." is that nothing
    # other than Tom can.
    RelationSpec(SemanticRelation.OTHER_THAN, frozenset(), generic_safe=False, symmetric=True,
                 gloss="a thing and one it is not"),
    # What a thing is called, and where it is from: "My name is Tom.", "I am from Paris.".
    RelationSpec(SemanticRelation.NAMED, frozenset(), generic_safe=False,
                 gloss="a thing and the name it is called by"),
    RelationSpec(SemanticRelation.COMES_FROM, frozenset(), generic_safe=False,
                 gloss="a thing and the place it comes from"),
    # A state, as an event is: "The door was open." is a state of being open,
    # the door's, before now. What holds now is said as it always was
    # (`has_property`); a state is a thing of its own only where it has a time.
    RelationSpec(SemanticRelation.STATE_OF, frozenset(), generic_safe=False,
                 gloss="a state and whose it is"),
    # dispositional
    RelationSpec(SemanticRelation.CAPABLE_OF,
                 frozenset({"can", "is able to", "able to", "can do",
                            "is capable of", "capable of"}),
                 inheritable=True,
                 gloss="a disposition/ability the subject has (inherits down ISA)"),
    # fallback
    RelationSpec(SemanticRelation.RELATED_TO, frozenset(),
                 generic_safe=False, gloss="unrecognised: licenses no inference"),
)

SPEC: Dict[SemanticRelation, RelationSpec] = {s.name: s for s in _SPECS}

#: A kind by its own name: `synonym_of`, `done_by`. The name is the store's, not
#: English, which is why `classify` resolves it before any phrase is looked up.
_BY_NAME: Dict[str, SemanticRelation] = {r.value: r for r in SemanticRelation}

#: surface phrase -> type, built once from the specs. Longest phrase wins so a
#: specific construction is never shadowed by a copula it contains.
_SURFACE: Dict[str, SemanticRelation] = {}
for _s in _SPECS:
    for _form in _s.surface_forms:
        # A surface form claimed by two types is a conflict, not a silent
        # last-writer-wins: record the FIRST and log the collision so the table
        # stays inspectable.
        if _form in _SURFACE and _SURFACE[_form] is not _s.name:
            logger.warning("relation surface %r maps to both %s and %s; keeping %s",
                           _form, _SURFACE[_form].value, _s.name.value,
                           _SURFACE[_form].value)
            continue
        _SURFACE[_form] = _s.name

_MAX_WORDS = max((len(f.split()) for f in _SURFACE), default=1)

# Word classes the bare copula "is" resolves to when disambiguation is available.
NOUN, ADJECTIVE, VERB = "NOUN", "ADJECTIVE", "VERB"


@dataclass(frozen=True)
class TypedRelation:
    """The result of classifying a predicate span."""

    relation: SemanticRelation
    surface: str                 # the span as read
    matched: str                 # the surface form that matched (or "")
    source: str                  # provenance of the mapping
    generic: bool                # is this asserted about a kind?

    @property
    def spec(self) -> RelationSpec:
        return SPEC[self.relation]


def _normalize(span: str) -> str:
    return " ".join(str(span).replace("_", " ").lower().split())


DETERMINER = "DETERMINER"


def complement_class(surface: str, class_evidence) -> Optional[str]:
    """What class a COPULAR COMPLEMENT is being used as, from the surface and
    what the substrate has observed about its words. None = no opinion.

    `class_evidence(word) -> Dict[str, int]`, the observed counts per class.

    WHY THE MAJORITY CLASS IS THE WRONG QUESTION. `classify` needs to know what
    the complement IS HERE, and the obvious answer -- the word's most-observed
    class -- gets it backwards for exactly the words that matter. Measured on the
    live vocabulary: `white` is ADJECTIVE 1 / NOUN 12, `red` 2 / 7, `closed` 1 /
    NOUN 8 / VERB 3, because a dictionary has many noun senses for a colour and
    one adjective sense. Asking "what is this word usually" therefore answers
    NOUN for every colour and every state, and "snow is white" becomes a KIND
    edge -- which `isa` then carries transitively into everything under snow.

    STRUCTURE DECIDES, EVIDENCE PERMITS. A complement introduced by a DETERMINER
    is a noun phrase and so a kind: "a robin is A BIRD". A BARE complement is
    predicative, and is a property when the substrate has ever observed its head
    as an adjective at all: "snow is WHITE", "inheritance is X-LINKED RECESSIVE".
    The determiner test is syntax, which is what this substrate reads; the
    evidence test only has to permit, not to win a vote.

    A bare complement whose head has never been observed as an adjective yields
    None, and `classify` keeps ISA -- the copula's default relational reading.
    """
    words = str(surface or "").replace("_", " ").strip().split()
    if not words:
        return None
    if len(words) > 1 and _observed(class_evidence(words[0].lower()), DETERMINER):
        # Introduced by a determiner: a noun phrase, hence a kind.
        return NOUN
    if _observed(class_evidence(words[-1].lower()), ADJECTIVE):
        return ADJECTIVE
    return None


def _observed(evidence, word_class: str) -> bool:
    """Whether `evidence` says this word has been seen in `word_class`.

    Two shapes reach here and both are legitimate: the memory authority answers
    with COUNTS per class, and `genericity._word_classes` answers with the set of
    classes the evidence is already net-positive for. Counts must be positive to
    count as an observation — a class that has been leaned on and failed more
    often than it succeeded is one the substrate tried and lost, not one it saw.
    """
    if not evidence:
        return False
    getter = getattr(evidence, "get", None)
    if getter is not None:
        try:
            return float(getter(word_class, 0) or 0) > 0
        except (TypeError, ValueError):
            return word_class in evidence
    return word_class in evidence


def classify(span: str, *,
             object_word_class: Optional[str] = None,
             generic: bool = True,
             source: str = "curated_lexical_map") -> TypedRelation:
    """Type a predicate span. Never guesses beyond the table.

    The bare copula is genuinely ambiguous and is resolved only where the
    evidence to resolve it is present: `is` + an ADJECTIVE object is
    HAS_PROPERTY, `is` + a NOUN is ISA, and with no word-class hint it stays ISA
    (the copula's most common relational reading) rather than inventing a
    property. An unrecognised predicate is RELATED_TO, which licenses nothing.
    """
    norm = _normalize(span)
    words = norm.split()

    # A KIND'S OWN NAME RESOLVES TO THE KIND. A relation read back from the store
    # arrives as its kind's name, and a kind needs no English phrase to be
    # recognised as itself. Measured before this: `synonym_of` resolved to
    # RELATED_TO, because its name was not among its phrases, and a kind with no
    # phrases at all could not be named.
    by_name = _BY_NAME.get(norm.replace(" ", "_"))
    if by_name is not None:
        return TypedRelation(by_name, span, by_name.value, "relation_kind",
                             generic and SPEC[by_name].generic_safe)

    # Longest-match over the surface table.
    match: Optional[str] = None
    for n in range(min(_MAX_WORDS, len(words)), 0, -1):
        cand = " ".join(words[:n])
        if cand in _SURFACE:
            match = cand
            break
        # also allow the whole span to match a multiword form not anchored at 0
        if n == len(words) and norm in _SURFACE:
            match = norm
            break

    # VERB + PARTICLE. "sat on", "rests on", "jumps over" put the relation in a
    # trailing preposition the leading verb is not part of the table for. When
    # the anchored match fails, a span whose LAST token is itself a known form
    # (a preposition/particle) is that relation -- the cat SAT ON the mat is
    # LOCATED_AT the mat. Kept deliberately narrow (last token only, and only a
    # single-word form) so a genuine dropped-noun-phrase span, whose last word
    # is a noun and not in the table, still declines rather than being typed.
    if match is None and len(words) > 1 and words[-1] in _SURFACE:
        match = words[-1]

    if match is None:
        return TypedRelation(SemanticRelation.RELATED_TO, span, "", source, generic)

    rel = _SURFACE[match]

    # Disambiguate the bare copula with a word-class hint when there is one.
    # ONLY an ADJECTIVE object makes it HAS_PROPERTY; a NOUN, a VERB, or no hint
    # at all reads as ISA -- the copula's default relational reading -- never a
    # property invented from a non-adjective. (A VERB object arises for a
    # no-copula sentence whose empty span defaults to "is", e.g. "the pump
    # runs"; it must not be read as a property.)
    if match in ("is", "are"):
        rel = (SemanticRelation.HAS_PROPERTY
               if object_word_class == ADJECTIVE else SemanticRelation.ISA)

    generic_result = generic and SPEC[rel].generic_safe
    return TypedRelation(rel, span, match, source, generic_result)


def get_spec(relation: SemanticRelation) -> RelationSpec:
    return SPEC[relation]


def all_surface_forms() -> Dict[str, SemanticRelation]:
    """The full curated table, for inspection and for teaching new mappings."""
    return dict(_SURFACE)


__all__ = ["SemanticRelation", "Transitivity", "EvidenceBehavior",
           "RelationSpec", "TypedRelation", "SPEC",
           "classify", "get_spec", "all_surface_forms",
           "NOUN", "ADJECTIVE", "VERB", "DETERMINER",
           "complement_class"]
