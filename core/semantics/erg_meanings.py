"""The English Resource Grammar's meanings said in Lyric's meaning language.

THE ENGLISH RESOURCE GRAMMAR (`delph-in/erg`, MIT) is a grammar of English written by hand over more than twenty
years: 225 syntactic and 70 lexical rules, with a lexicon, giving Minimal Recursion Semantics (Copestake, Flickinger,
Pollard and Sag 2005). ACE (MIT) parses with it. NEITHER IS A MODEL. It reads 98.7% of the PMB's dev split, where
Lyric's own grammar reads 891 of the 911 it attempts and gets 42.4% of their meanings right whole
(GRAMMAR-01 20261028T111052Z, lab notebook (101)).

READ FROM ELEMENTARY DEPENDENCY STRUCTURES (`delphin.eds`), not from MRS: an EDS is the same meaning with scope
dropped and every argument pointing straight at the node that fills it, which is the shape Lyric's facts already
have. Scope is the one thing Lyric's meaning language cannot hold at all, so nothing is lost by dropping it that was
not lost anyway -- and what IS lost is named (`Said.gaps`), never guessed.

WHAT IS NOT YET SAID IS NAMED, as `pmb_meanings` names it: a sentence holding any of it is said as nothing, so
nothing is ever taught a meaning that is not the sentence's. The ERG says things Lyric's meaning language has no
words for -- a universal quantifier (`every_q`), a noun's number, the perfect against the progressive, a
nominalization, an ellipsis -- and each is a gap by name.

The ERG's predicates are its OWN inventory (`_chase_v_1`), not WordNet's, and Lyric names a concept by its WordNet
sense (`chase`, `foodstuff egg`). The lemma is taken here and the sense is not chosen, which is exactly what
GRAMMAR-01's "senses aside" measure sets aside on both sides; a whole integration needs a bridge from the ERG's
predicates to WordNet's senses, and that is more than this table.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from core.semantics.derived_reader import Meaning, MeaningFact
from core.semantics.pmb_meanings import Said
from core.semantics.relation_types import worded

#: An open-class predicate: `_lemma_pos` and what else the ERG writes after it (`_dog_n_1`, `_in_p_loc`,
#: `_book_n_of`). A multi-word lemma is joined by `+` (`_ice+cream_n_1`).
OPEN = re.compile(r"^_(?P<lemma>.+?)_(?P<pos>[nvajrpqcxi])(?:_(?P<rest>.+))?$")

#: WHAT A PREPOSITION SAYS, by what the ERG's own predicate calls it: the grammar has already decided whether the
#: word is locative, temporal, directional or stative, which is the decision Lyric makes by weighing six competing
#: categories at the preposition and gets wrong (lab notebook (101)).
PREPOSITION_KINDS = {"loc": "located_in", "temp": "during", "dir": "moves_to", "state": "has_property"}

#: Prepositions whose own predicate names the link, whatever the kind said after it.
PREPOSITION_WORDS = {"of": "part_of", "about": "about", "for": "done_for", "with": "done_with",
                     "from": "moves_from", "by": "done_by", "to": "moves_to", "into": "moves_to",
                     "onto": "moves_to", "through": "moves_through", "in": "located_in", "on": "located_in",
                     "at": "located_in", "near": "located_in", "inside": "located_in", "outside": "located_in",
                     "above": "located_in", "below": "located_in", "under": "located_in", "over": "located_in",
                     "behind": "located_in", "beside": "located_in", "between": "located_in"}

#: A VERB'S PLACES, as the ERG numbers them: its first argument does it, its second is what it is done to, its third
#: who receives it. The ERG's `ARG1` is the proto-agent of its own lexicon, which is what PropBank's `ARG0` is and
#: what Lyric reads as `done_by` (`propbank_roles.BY_NUMBER`).
VERB_PLACES = {"ARG1": "done_by", "ARG2": "done_to", "ARG3": "received_by", "ARG4": "received_by"}

#: A QUANTIFIER THAT SAYS THE THING IS ALREADY KNOWN (`given`): "the dog" is a dog the speaker and listener both
#: know, where "a dog" is one not known before. The rest say nothing Lyric's language holds, and `every_q` says
#: something it cannot hold at all.
GIVEN_QUANTIFIERS = frozenset({"_the_q", "def_explicit_q", "def_implicit_q", "pronoun_q", "proper_q", "def_poss_q"})
PLAIN_QUANTIFIERS = frozenset({"_a_q", "udef_q", "number_q", "idiom_q_i", "free_relative_q", "some_q", "_some_q"})
#: Quantifiers Lyric's meaning language has no words for: it has no universal quantifier at all (lab notebook (100)).
UNSAYABLE_QUANTIFIERS = frozenset({"every_q", "_every_q", "_all_q", "_each_q", "_no_q", "_both_q", "_any_q",
                                   "which_q", "_which_q", "_most_q", "_many_q", "_few_q"})

#: WHAT EACH OF THE GRAMMAR'S OWN PREDICATES SAYS. The ERG uses 72 of them over the PMB's dev split and they carry
#: 5,654 of its 9,324 predicate uses, so this table and the rules above are the whole bridge for the closed class.
#: A predicate whose name is here with None says nothing Lyric's language holds and is counted as a gap.
ABSTRACT: Mapping[str, Optional[str]] = {
    # a thing spoken of, by what the grammar knows of it
    "pron": "pronoun", "named": "name", "named_n": "name", "person": "person", "place_n": "place",
    "time_n": "time", "thing": "thing", "generic_entity": "thing", "ne_x": "name",
    # links Lyric holds
    "compound": "compound", "poss": "owned_by", "part_of": "part_of", "appos": "equals", "id": "equals",
    "loc_nonsp": "located_in", "measure": "has_measure", "meas_np": "has_measure", "card": "has_count",
    "ord": "has_count", "much-many_a": "many", "neg": "not", "superl": "greatest", "more_comp": "more",
    "comp": "more", "comp_equal": "equals", "times": "has_count", "abstr_deg": "degree",
    "subord": None, "parg_d": None,
    # said of a happening or a thing, held as the word it was said with where no link kind names it
    "unspec_manner": None, "manner": None, "unspec_adj": None,
    # what the meaning language has no words for yet
    "nominalization": None, "ellipsis": None, "ellipsis_ref": None, "ellipsis_expl": None,
    "implicit_conj": None, "unknown": None, "fw_seq": None, "discourse": None, "prpstn_to_prop": None,
    "yofc": "year", "dofm": "day", "mofy": "month", "dofw": "weekday", "numbered_hour": "clock",
    "basic_numbered_hour": "clock", "season": None, "holiday": None, "interval": None, "interval_p_end": None,
    "focus_d": None, "part_of_x": "part_of", "of_p": "part_of", "eventuality": None, "nonsp_manner": None,
    "elliptical_n": None, "generic_nom": None, "prpstn_to_prop_rel": None, "abstr_lex_dom": None,
}


def _lemma(predicate: str) -> Optional[Tuple[str, str, str]]:
    """An open-class predicate taken apart: its word, its class, and what the ERG says after it. None where the
    predicate is one of the grammar's own (`pron`, `compound`)."""
    found = OPEN.match(predicate)
    if not found:
        return None
    return (found.group("lemma").replace("+", " ").replace("_", " "), found.group("pos"),
            found.group("rest") or "")


def meaning_of(graph: Any) -> Said:
    """What the ERG read, said in Lyric's meaning language (`Said`), or None with the gaps that keep it from being
    said. `graph` is an Elementary Dependency Structure (`delphin.eds.EDS`), as `delphin.eds.from_mrs` makes one of
    what ACE parsed."""
    gaps: List[str] = []
    nodes = {node.id: node for node in graph.nodes}

    # ── WHICH NODES STAND FOR SOMETHING THE MEANING SPEAKS OF ──
    # A quantifier stands for nothing: it says of the thing it binds whether it is already known. Everything else
    # that a fact can be about gets a term, numbered as it is said, so two readings of one sentence name alike.
    said: List[str] = []
    for node in graph.nodes:
        if node.predicate.endswith("_q"):
            continue
        said.append(node.id)
    term = {at: f"?v{k}" for k, at in enumerate(said)}

    facts: List[MeaningFact] = []
    denied: Set[str] = set()
    counted: Dict[str, str] = {}
    #: A node -> the nodes whose words are said as one with it (`compound`), in the order said.
    joined: Dict[str, Any] = {}
    #: Happenings denied by a quantifier rather than by `neg`.
    denied_later: Set[str] = set()

    def add(relation: str, subject: Optional[str], obj: Optional[str], given_: bool = False) -> None:
        if subject is None or obj is None:
            return
        facts.append(MeaningFact(relation, subject, obj, given=given_))

    def of(at: Optional[str]) -> Optional[str]:
        return term.get(at) if at else None


    # ── WHAT EACH QUANTIFIER SAYS OF WHAT IT BINDS ──
    given: Set[str] = set()
    asked: Set[str] = set()
    for node in graph.nodes:
        if not node.predicate.endswith("_q"):
            continue
        bound = node.edges.get("BV")
        if node.predicate in GIVEN_QUANTIFIERS:
            if bound in term:
                given.add(term[bound])
        elif node.predicate in UNSAYABLE_QUANTIFIERS:
            # "which" asks which one; every other unsayable quantifier is a gap, the universal one above all.
            if node.predicate in ("which_q", "_which_q"):
                if bound in term:
                    asked.add(term[bound])
            elif node.predicate in ("_no_q", "_nobody_q", "_nothing_q"):
                # "Nobody walks in LA.": there is no walker, which Lyric and the PMB both say by denying the
                # happening the thing is a place of.
                for other in graph.nodes:
                    if bound in other.edges.values() and of(other.id) is not None:
                        denied_later.add(other.id)
            else:
                gaps.append(f"quantifier:{node.predicate}")
        elif node.predicate not in PLAIN_QUANTIFIERS:
            gaps.append(f"quantifier:{node.predicate}")

    # ── WHAT IS DENIED ──
    # The ERG marks a denial with its own predicate over the happening (`neg ARG1`), where Lyric marks the facts of
    # the happening themselves as not so.
    for node in graph.nodes:
        if node.predicate == "neg":
            under = node.edges.get("ARG1")
            if under in term:
                denied.add(term[under])

    # ── EACH NODE'S OWN FACTS ──
    for node in graph.nodes:
        here = of(node.id)
        parts = _lemma(node.predicate)
        if node.predicate.endswith("_q"):
            continue
        if parts is None:
            # ── the grammar's own predicates ──
            says = ABSTRACT.get(node.predicate, "missing")
            if says == "missing":
                gaps.append(f"predicate:{node.predicate}")
                continue
            if says is None:
                gaps.append(f"nothing said for:{node.predicate}")
                continue
            if says == "name":
                # A name is itself, lowered, as the lessons say a name (`pmb_meanings`).
                if node.carg and here:
                    counted[node.id] = str(node.carg).lower()
            elif says == "pronoun":
                # WHO IS SPOKEN OF: the speaker, the listener, or the one spoken of before. The ERG says which by
                # the person it holds of the pronoun; it does not say which thing before, and neither does Lyric.
                person = (node.properties or {}).get("PERS")
                counted[node.id] = {"1": "?speaker", "2": "?listener"}.get(str(person), "?previous")
            elif says in ("person", "place", "time", "thing"):
                # A THING THE SENTENCE SAYS NOTHING OF IS NAMED NOTHING. The ERG names what it knows of an
                # underspecified thing (`person` for "nobody", `place_n` for "where", `thing`, `generic_entity`,
                # `time_n`), and the PMB leaves it unnamed: "Where did Mahatma Gandhi study?" asks `?v1` with
                # nothing said it is, and "Nobody walks in LA." says a walker, not a person. Said, each was one
                # fact more than the meaning holds, in 276 of the dev split's predicate uses. The term stays; only
                # the naming goes.
                pass
            elif says == "compound":
                # TWO WORDS NAMING ONE THING ARE ONE THING with one name, as Lyric reads them ("Mahatma Gandhi",
                # "ice cream"); the ERG says two things joined, the second word's thing the head (`ARG1`) and the
                # first its modifier (`ARG2`). Joined here in the order they are said. This is the ERG's third most
                # used predicate of its own (317 of the dev split's uses), so left a gap it costs every sentence
                # with a name of two words.
                head, modifier = node.edges.get("ARG1"), node.edges.get("ARG2")
                if head is not None and modifier is not None:
                    joined[head] = joined.get(modifier, modifier), joined.get(head, head)
            elif says == "not":
                continue
            elif says in ("many", "greatest", "more", "degree", "year", "day", "month", "weekday", "clock"):
                gaps.append(f"nothing said for:{node.predicate}")
            elif says == "has_count":
                if node.carg and node.edges.get("ARG1") in term:
                    add("has_count", of(node.edges.get("ARG1")), str(node.carg))
            else:
                add(says, of(node.edges.get("ARG1")), of(node.edges.get("ARG2")))
            continue

        word, kind, rest = parts
        if kind == "q":
            continue
        if kind == "n":
            add("instance_of", here, word, given_=here in given)
            for role, link in (("ARG1", "part_of"),):
                if node.edges.get(role) in term:
                    add(link, here, of(node.edges[role]))
        elif kind == "v":
            add("instance_of", here, word)
            for role, link in VERB_PLACES.items():
                filled = node.edges.get(role)
                if filled in term:
                    add(link, here, of(filled))
        elif kind in ("a", "j"):
            # A quality is said of what it is of; a comparative or a superlative of it is a gap.
            about = node.edges.get("ARG1")
            if about in term:
                add("has_property", of(about), word)
            elif about is not None:
                gaps.append(f"quality of nothing:{node.predicate}")
        elif kind == "r":
            about = node.edges.get("ARG1")
            if about in term:
                add("has_property", of(about), word)
        elif kind == "p":
            # ── A PREPOSITION, by what the ERG's own predicate calls it ──
            link = PREPOSITION_KINDS.get(rest.split("_")[0]) if rest else None
            if link is None:
                link = PREPOSITION_WORDS.get(word, worded(word))
            if link == "has_property":
                add("has_property", of(node.edges.get("ARG1")), word)
            else:
                add(link, of(node.edges.get("ARG1")), of(node.edges.get("ARG2")))
        else:
            gaps.append(f"class:{node.predicate}")

    # ── TWO WORDS SAYING ONE THING, JOINED ──
    # A name of two words is one name ("Mahatma Gandhi" `mahatma gandhi`); two nouns naming one thing are one thing
    # named by both words ("ice cream"). The word said first comes first, and the modifier's own facts go, since
    # there is only one thing.
    for head, pair in joined.items():
        modifier, _ = pair if isinstance(pair, tuple) else (pair, head)
        while isinstance(modifier, tuple):
            modifier = modifier[0]
        if head in counted and modifier in counted:
            counted[head] = f"{counted[modifier]} {counted[head]}"
            counted.pop(modifier, None)
            term.pop(modifier, None)
            continue
        was, now = of(modifier), of(head)
        if was is None or now is None:
            continue
        said_as = [f.obj for f in facts if f.relation == "instance_of" and f.subject in (was, now)]
        first = [f.obj for f in facts if f.relation == "instance_of" and f.subject == was]
        last = [f.obj for f in facts if f.relation == "instance_of" and f.subject == now]
        if not (first and last):
            continue
        name = f"{first[0]} {last[0]}"
        facts = [f for f in facts if not (f.relation == "instance_of" and f.subject == was)]
        facts = [MeaningFact(f.relation, f.subject, name if (f.relation == "instance_of" and f.subject == now)
                             else f.obj, f.positive, f.condition, f.alternative, f.unasserted, f.given)
                 for f in facts]
        # everything said of the modifier is said of the one thing
        facts = [MeaningFact(f.relation, now if f.subject == was else f.subject,
                             now if f.obj == was else f.obj, f.positive, f.condition, f.alternative,
                             f.unasserted, f.given) for f in facts]
        term.pop(modifier, None)

    # ── WHAT A NAME OR A PRONOUN STANDS FOR, put in place of its term ──
    for at, name in counted.items():
        was = term.get(at)
        if was is None:
            continue
        facts = [MeaningFact(f.relation, name if f.subject == was else f.subject,
                             name if f.obj == was else f.obj, f.positive, f.condition, f.alternative,
                             f.unasserted, f.given) for f in facts]
        asked = {name if a == was else a for a in asked}
        denied = {name if d == was else d for d in denied}

    # ── WHEN IT WAS, AND WHAT THE SPEAKER WANTS ──
    top = graph.top
    held = dict((nodes[top].properties or {})) if top in nodes else {}
    tense = str(held.get("TENSE", "")).lower()
    for at in list(term):
        node = nodes[at]
        if _lemma(node.predicate) and _lemma(node.predicate)[1] == "v":
            when = str((node.properties or {}).get("TENSE", "")).lower()
            if when == "past":
                add("precedes", of(at), "?now")
            elif when == "fut":
                add("follows", of(at), "?now")
            elif when == "pres" and str((node.properties or {}).get("PROG", "")) == "+":
                add("during", of(at), "?now")
    act = {"ques": "ask", "prop": "tell", "comm": "request"}.get(str(held.get("SF", "prop")).lower(), "tell")

    # ── DENIALS ──
    # SAID OF THE HAPPENING ITSELF (`has_property(e, false)`), which is how the PMB writes a denial and how Lyric
    # reads one (`spell_out`: `add("has_property", e, "false")`). Said instead by marking each of the happening's
    # facts not so, every fact of "She doesn't speak Japanese." came out denied where the gold denies only the
    # speaking.
    for at in denied | {of(x) for x in denied_later if of(x)}:
        if at:
            add("has_property", at, "false")

    if gaps:
        return Said(None, tuple(sorted(set(gaps))))
    kept = list(dict.fromkeys(facts))
    if not kept:
        return Said(None, ("nothing said",))
    try:
        return Said(Meaning(act, tuple(kept), tuple(sorted(asked))), ())
    except ValueError as problem:
        return Said(None, (f"not a meaning: {problem}",))
