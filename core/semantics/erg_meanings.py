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
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

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
#: A POSSESSIVE IS NOT AMONG THEM, though "my" is one of the words the gold calls known
#: (`pmb_meanings.KNOWN`). The PMB writes the possessive as a line of its OWN (the owner's role), so the words of
#: the thing possessed never include "my" and the gold does not mark it known -- 27 dev sentences differed from the
#: gold in that one flag and nothing else, every one of them a possessive (2026-11-02).
GIVEN_QUANTIFIERS = frozenset({"_the_q", "def_implicit_q", "pronoun_q", "proper_q",
                               "_this_q_dem", "_that_q_dem", "_these_q_dem", "_those_q_dem"})


def _quantifies(predicate: str) -> bool:
    """Whether a predicate binds a thing and says of it whether it is already known, rather than saying anything the
    meaning holds. MOST OF THEM END IN `_q` AND A DEMONSTRATIVE DOES NOT (`_that_q_dem`), so tested by the suffix
    alone every "this", "that", "these" and "those" was invisible to the pass that reads quantifiers: it took a term
    of its own, said nothing, and the thing it binds was never marked known where the gold marks it (6 dev
    sentences, 2026-11-02)."""
    return predicate.endswith("_q") or predicate.endswith("_q_dem")
#: A POSSESSIVE'S OWN QUANTIFIER IS HERE and not above: it says the thing is somebody's, which the possessive's
#: own fact already says, and it does NOT say the thing was spoken of before. Left out of both, every sentence
#: holding a possessive was said as nothing for a quantifier the bridge had no word for.
PLAIN_QUANTIFIERS = frozenset({"_a_q", "udef_q", "number_q", "idiom_q_i", "free_relative_q", "some_q", "_some_q",
                               "def_explicit_q", "def_poss_q"})
#: Quantifiers Lyric's meaning language has no words for: it has no universal quantifier at all (lab notebook (100)).
UNSAYABLE_QUANTIFIERS = frozenset({"every_q", "_every_q", "_all_q", "_each_q", "_no_q", "_both_q", "_any_q",
                                   "which_q", "_which_q", "_most_q", "_many_q", "_few_q"})

#: WHAT DENIES THE HAPPENING IT STANDS OVER. The ERG says a denial with a predicate of its own taking the happening
#: as its place (`neg ARG1`), and says "never" and "no longer" the same way (`_never_a_1 ARG1`), which is the line
#: Lyric's own reading draws ("not", "never" both negate: `propbank_roles.Said`). Read as qualities instead,
#: "Luis never approved the request." came out `has_property(?v, never)` with the approving told as so (2026-11-02).
#: "rarely" is NOT here: it says the happening is infrequent, not that it did not happen.
DENYING = frozenset({"neg", "_never_a_1", "_no+longer_a_1"})

#: WHAT THE SENTENCE DOES NOT TELL AS SO, and the status it gives what it holds back. A modal of possibility and the
#: adverbs that hedge one stand over the happening exactly as a denial does (`_may_v_modal ARG1`, `_perhaps_a_1
#: ARG1`), and what they say is what `MeaningFact.unasserted` holds: the happening is said to be possible or
#: probable -- which IS told, and is a fact of it -- while that it happened is not told at all. Read as ordinary
#: predicates, "Jordan may have disabled the account." came out as a happening named "may" with the disabling
#: itself told as so, and nothing was named as a gap, so the loss was silent (2026-11-02).
#: EVERY OTHER MODAL IS A GAP BY NAME: obligation ("must", "should") and ability ("can") are not possibility, and
#: Lyric's meaning language has no words for them, so a sentence holding one is said as nothing rather than wrongly.
HEDGING = {"_may_v_modal": "possible", "_might_v_modal": "possible", "_could_v_modal": "possible",
           "_perhaps_a_1": "possible", "_possible_a_for": "possible",
           "_probable_a_1": "probable", "_likely_a_1": "probable", "_apparent_a_1": "probable"}

#: WHAT MUST HOLD FOR THE REST TO HOLD, and whether it must hold or must not. The ERG gives every one of these the
#: same two places whatever the word writes it -- what holds (`ARG1`) and what it holds on (`ARG2`) -- so one rule
#: reads all three (`_if_x_then`, `_when_x_subord`, `_unless_p_1`). The value is what the condition says of its own
#: facts: "unless" is the condition DENIED, which is how Lyric's own reading says it (`propbank_roles.Said`:
#: "unless" a condition with `positive` False). Left unread, `if` and `when` were named gaps and the whole sentence
#: was said as nothing, over every conditional tried (2026-11-02).
CONDITIONING = {"_if_x_then": True, "_when_x_subord": True, "_unless_p_1": False}

#: WHAT SOMEONE IS ABLE TO DO rather than what they did. "can" stands over the happening as a hedge does, and what
#: it says Lyric already holds a link for (`relation_types.CAPABLE_OF`, "birds capable_of fly"), so it is read as
#: that link of the one who could do it and the doing's word -- and the doing itself is not told as so, since
#: "Luis can read the finance data." says no reading ever happened. Obligation ("must", "should") has no link in
#: the meaning language at all and stays a gap by name.
ABLE = frozenset({"_can_v_modal"})


class Mark(NamedTuple):
    """What something standing over a clause says of the facts inside it: that they hold only if something else
    does (`condition`), that the sentence does not tell them as so (`unasserted`), that they do not hold
    (`denied`). Put on each fact as it is made, never afterwards by the term it is about."""

    condition: bool = False
    unasserted: bool = False
    denied: bool = False

#: WHAT EACH OF THE GRAMMAR'S OWN PREDICATES SAYS. The ERG uses 72 of them over the PMB's dev split and they carry
#: 5,654 of its 9,324 predicate uses, so this table and the rules above are the whole bridge for the closed class.
#: A predicate whose name is here with None says nothing Lyric's language holds and is counted as a gap.
ABSTRACT: Mapping[str, Optional[str]] = {
    # a thing spoken of, by what the grammar knows of it
    "pron": "pronoun", "named": "name", "named_n": "name", "person": "person", "place_n": "place",
    "time_n": "time", "thing": "thing", "generic_entity": "thing", "ne_x": "name",
    # links Lyric holds
    "compound": "compound", "poss": "owned_by", "part_of": "part_of", "appos": "same_as", "id": "same_as",
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


#: A WORD THE ERG'S LEXICON DOES NOT HOLD, which it reads by its shape and says as `_word/tag_u_unknown`
#: (`_applauded/vbd_u_unknown`, `_groggy/jj_u_unknown`). The tag is the Penn treebank's, so it says the class.
UNKNOWN = re.compile(r"^_(?P<lemma>.+?)/(?P<tag>[a-z]+)_u_unknown$")
UNKNOWN_CLASSES = {"nn": "n", "nns": "n", "nnp": "n", "nnps": "n", "vb": "v", "vbd": "v", "vbg": "v", "vbn": "v",
                   "vbp": "v", "vbz": "v", "jj": "a", "jjr": "a", "jjs": "a", "rb": "r", "rbr": "r", "rbs": "r"}


def _lemma(predicate: str) -> Optional[Tuple[str, str, str]]:
    """An open-class predicate taken apart: its word, its class, and what the ERG says after it. None where the
    predicate is one of the grammar's own (`pron`, `compound`). A word the ERG's lexicon does not hold is read by
    the Penn tag it guessed (`UNKNOWN`), which is the class; left unread, six of the first 120 dev sentences were
    said as nothing for one word apiece."""
    strange = UNKNOWN.match(predicate)
    if strange and strange.group("tag") in UNKNOWN_CLASSES:
        return (strange.group("lemma").replace("+", " ").replace("_", " "),
                UNKNOWN_CLASSES[strange.group("tag")], "")
    found = OPEN.match(predicate)
    if not found:
        return None
    return (found.group("lemma").replace("+", " ").replace("_", " "), found.group("pos"),
            found.group("rest") or "")


#: WHAT A POSSESSIVE SAYS, by what the thing possessed IS (WordNet's own grouping of its nouns): a body part is
#: PART OF whoever it is of ("my eyes" `part_of`), a relative is a member of the family, and a thing owned is
#: `owned_by`. The PMB says all three with the same word, and said `owned_by` throughout, 67 of the dev split's
#: possessives were a link the meaning does not hold and 34 of its `part_of` links were missing. Lyric's own
#: grammar takes this from what taught sentences said of the noun's kind (`inherited("poss", ...)`); here it comes
#: from WordNet, which is the same knowledge by another road.
POSSESSED = {"noun.body": "part_of"}


def _is_phrase(nodes: Mapping[str, Any], at: Optional[str]) -> bool:
    """Whether a verb's place is filled by a PHRASE rather than by someone taking part. The ERG gives a verb a
    place for a phrase it governs and numbers it among the rest: "Jordan removed Luis from the finance team." is
    `_remove_v_1 ARG1 Jordan, ARG2 Luis, ARG3 _from_p`, where the third is the "from" phrase and no third
    participant exists. Read as one, every such sentence said somebody received something, of a term nothing else
    in the meaning mentioned (2026-11-02). What the phrase itself says is read from the preposition, which says it
    of the thing the ERG gives IT -- `_from_p ARG1 Luis`, Luis the one who came from the team."""
    if at is None or at not in nodes:
        return False
    parts = _lemma(nodes[at].predicate)
    return (parts is not None and parts[1] == "p") or nodes[at].predicate in ("loc_nonsp", "subord")


def _possesses(word: str) -> str:
    """The link a possessive makes with a thing of this word: `part_of` for a part of a body, else `owned_by`."""
    try:
        from nltk.corpus import wordnet as wn
    except Exception:
        return "owned_by"
    for sense in wn.synsets(word.replace(" ", "_"), "n")[:1]:
        return POSSESSED.get(sense.lexname(), "owned_by")
    return "owned_by"


def _comes_from(word: str) -> Optional[str]:
    """The place a quality says a thing comes from, lowered ("Korean" `korea`), or None: WordNet's pertainym of the
    quality, where what it pertains to is a location."""
    try:
        from nltk.corpus import wordnet as wn
    except Exception:
        return None
    for sense in wn.synsets(word.replace(" ", "_"), "a"):
        for lemma in sense.lemmas():
            for of_what in lemma.pertainyms():
                if of_what.synset().lexname() == "noun.location":
                    return of_what.name().replace("_", " ").lower()
    return None


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
        if _quantifies(node.predicate):
            continue
        said.append(node.id)
    term = {at: f"?v{k}" for k, at in enumerate(said)}

    # ── A REFLEXIVE STANDS FOR WHOEVER DID IT ──
    # "Tom hated himself." is a hating done to TOM, which is how the gold says it and how Lyric's own reading says
    # it (`composition`: the hating done by Tom, done to "himself"). The ERG marks the pronoun itself (`PT: refl`)
    # and otherwise leaves it a thing of its own, so read as any other pronoun it became "the one spoken of before"
    # and the sentence said Tom hated somebody else (2026-11-02). Its term is the doer's from here on.
    reflexive: Set[str] = set()
    for node in graph.nodes:
        if node.predicate != "pron" or str((node.properties or {}).get("PT", "")) != "refl":
            continue
        for other in graph.nodes:
            if node.id not in other.edges.values():
                continue
            if (_lemma(other.predicate) or ("", "", ""))[1] != "v":
                continue
            doer = other.edges.get("ARG1")
            if doer in term and doer != node.id:
                term[node.id] = term[doer]
                reflexive.add(node.id)
            break

    facts: List[MeaningFact] = []
    denied: Set[str] = set()
    counted: Dict[str, str] = {}
    #: A node -> the nodes whose words are said as one with it (`compound`), in the order said.
    joined: Dict[str, Any] = {}
    #: Happenings denied by a quantifier rather than by `neg`.
    denied_later: Set[str] = set()
    #: A term the ERG named only as an underspecified thing -> what it named it. Said only where no other fact
    #: speaks of the term.
    loose: Dict[Optional[str], str] = {}
    #: (the thing possessed, whose it is), answered once every fact saying what things are is in.
    possessives: List[Tuple[Optional[str], Optional[str]]] = []
    #: (a happening the sentence does not tell as so, the status it gives it), said once the walk is done so the
    #: status is told even where everything else about the happening is held back.
    held_back: List[Tuple[str, str]] = []
    #: (the one who could do it, the doing's word), for what "can" says (`ABLE`).
    able: List[Tuple[Optional[str], str]] = []
    #: What the ERG holds of each pronoun said to point back, so two that cannot be one thing are told apart.
    pointed_back: Set[Tuple[str, str, str]] = set()

    #: The marks of the node whose facts are being made (`Mark`), set by the walk and by each pass after it.
    marked: List[Mark] = [Mark()]

    def add(relation: str, subject: Optional[str], obj: Optional[str], given_: bool = False) -> None:
        if subject is None or obj is None:
            return
        # MARKED WHEN THE FACT IS MADE, never afterwards by the term it is about: the passes below put one thing in
        # place of another when a name, a compound or the copula says so, and each carries every mark with it,
        # where a mark put on at the end by term would have missed "If the token is invalid, the session ends."
        # -- the quality's fact is about the token, which the consequent speaks of too.
        # WHAT BOTH ALREADY KNOW IS NOT PART OF A CONDITION AND IS NOT HELD BACK: "the account" in "If Jordan
        # disables the account ..." is an account whether or not he disables it (`MeaningFact.given`: true of the
        # thing, and not news), so a given fact takes no mark.
        held = Mark() if given_ else marked[0]
        facts.append(MeaningFact(relation, subject, obj, not held.denied, held.condition, False,
                                 held.unasserted, given_))

    def of(at: Optional[str]) -> Optional[str]:
        return term.get(at) if at else None


    # ── WHAT EACH QUANTIFIER SAYS OF WHAT IT BINDS ──
    given: Set[str] = set()
    asked: Set[str] = set()
    for node in graph.nodes:
        if not _quantifies(node.predicate):
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

    # ── THE COPULA IS NOT A HAPPENING ──
    # "It's a trap!" is a thing being a trap (`instance_of`), not a doing called "be" done by one thing to another;
    # "He is ill." is a quality, which the ERG says by the adjective's own argument and needs no help. The ERG reads
    # "is" as a verb of its own (`_be_v_id`) with the subject its first place and what it is said to be its second.
    # Read as any other verb, every copular sentence came out `instance_of(?v0, be)` with two places filled.
    copula: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for node in graph.nodes:
        parts = _lemma(node.predicate)
        if parts and parts[1] == "v" and parts[0] == "be":
            copula[node.id] = (node.edges.get("ARG1"), node.edges.get("ARG2"))

    # ── TWO THINGS SAID TOGETHER ARE BOTH IN WHATEVER THEY FILL ──
    # "Tom and Mary left." is a leaving done by Tom and a leaving done by Mary, which is how the PMB says it and
    # what Lyric's language can hold; it has no term for a pair. The ERG makes the conjunction a thing of its own
    # (`_and_c ARG1 ARG2`, or `implicit_conj` where no word joins them) and fills the place with THAT, so left
    # alone 41 dev sentences were said as nothing for a word meaning "and". An "or" is NOT this: one of the two
    # holds and the meaning language marks alternatives, which is not yet said here.
    together: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for node in graph.nodes:
        parts = _lemma(node.predicate)
        joins = (parts and parts[1] == "c" and parts[0] == "and") or node.predicate == "implicit_conj"
        if joins:
            together[node.id] = (node.edges.get("ARG1"), node.edges.get("ARG2"))

    # ── WHAT STANDS OVER A CLAUSE: A DENIAL, A HEDGE, A CONDITION ──
    # THE ERG WRITES ALL THREE ALIKE, as a predicate of its own taking what it stands over as a place (`neg ARG1`,
    # `_may_v_modal ARG1`, `_if_x_then ARG2`), so one pass reads all three. AND THEY STACK: "Jordan might not be an
    # administrator." is `neg` over `_might_v_modal` over the being, and read a level at a time the denial landed on
    # the modal and the sentence came out saying Jordan IS one (2026-11-02). Each is followed through whatever
    # stands between it and the clause it finally speaks of (`governs`).
    operators: Dict[str, str] = {}
    for node in graph.nodes:
        if node.predicate in DENYING:
            operators[node.id] = "deny"
        elif node.predicate in ABLE:
            operators[node.id] = "able"
        elif node.predicate in HEDGING:
            operators[node.id] = "hedge"
        elif node.predicate in CONDITIONING:
            operators[node.id] = "condition"

    def governs(at: Optional[str]) -> Optional[str]:
        """The node an operator finally speaks of: what fills its own place (`ARG2` where it names a condition,
        else `ARG1`), followed through any operator standing between the two."""
        seen: Set[str] = set()
        while at is not None and at in operators and at not in seen:
            seen.add(at)
            at = nodes[at].edges.get("ARG2" if operators[at] == "condition" else "ARG1")
        return at if at in nodes else None

    def reaching(start: Optional[str], apart: Set[str]) -> Set[str]:
        """Every node a clause speaks of: the one it is about, what fills its places, and what fills theirs, never
        crossing into what the rest of the sentence speaks of (`apart`)."""
        found: Set[str] = set()
        edge = [start] if start is not None else []
        while edge:
            at = edge.pop()
            if at in found or at in apart or at not in nodes:
                continue
            found.add(at)
            edge.extend(nodes[at].edges.values())
        return found

    marks: Dict[str, Mark] = {}

    def mark(at: Optional[str], condition: bool = False, unasserted: bool = False, denied: bool = False) -> None:
        if at is None or at not in nodes:
            return
        was = marks.get(at, Mark())
        marks[at] = Mark(was.condition or condition, was.unasserted or unasserted, was.denied or denied)

    for standing_over, what in operators.items():
        under = governs(standing_over)
        if under is None:
            continue
        if what == "deny":
            if under in copula:
                # A COPULA IS NO HAPPENING, so there is nothing to say did not happen: "Jordan is not an
                # administrator." is the one fact `instance_of(jordan, administrator)`, not so, which is what
                # `MeaningFact.positive` holds and what Lyric's own reading of a denied link writes. Said as a
                # happening denied, the denial was `has_property(?v, false)` about a term no other fact mentioned.
                mark(under, denied=True)
            elif under in term:
                # SAID OF THE HAPPENING ALONE (`has_property(e, false)`), never of each of its facts: the gold
                # denies the speaking in "She doesn't speak Japanese.", not that she speaks anything (the note
                # under DENIALS below).
                denied.add(term[under])
        elif what == "hedge":
            # The status is a fact OF the happening and is told; that the happening happened is not told at all.
            mark(under, unasserted=True)
            if of(under):
                held_back.append((under, HEDGING[nodes[standing_over].predicate]))
        elif what == "able":
            mark(under, unasserted=True)
            doing = _lemma(nodes[under].predicate)
            if doing and doing[1] == "v":
                able.append((nodes[under].edges.get("ARG1"), doing[0]))
        else:
            # THE WHOLE CLAUSE IS THE CONDITION, not its happening alone: "If the token is invalid, the session
            # ends." says nothing at all about a happening, and `propbank_roles` says the same of Lyric's own
            # reading ("the argument's facts are a condition of the happening's"). What the consequent also speaks
            # of is left out of it, so a thing named on both sides is not made conditional by standing there.
            holds = nodes[standing_over].edges.get("ARG1")
            for one in reaching(under, reaching(holds, set())):
                mark(one, condition=True, denied=not CONDITIONING[nodes[standing_over].predicate])

    # ── EACH NODE'S OWN FACTS ──
    for node in graph.nodes:
        here = of(node.id)
        parts = _lemma(node.predicate)
        marked[0] = marks.get(node.id, Mark())
        if _quantifies(node.predicate) or node.id in copula or node.id in together or node.id in operators:
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
                # WHO IS SPOKEN OF, by the person AND the number the ERG holds of the pronoun: the speaker, the
                # listener, or the one spoken of before. SAID OF MANY ("we", "us", "you" of several), it is a group
                # one of them is a member of, which is how the PMB says it -- "We buy CDs." is a buying done by a
                # group the speaker is a member of (`has_member`), never by the speaker. Taken as the speaker
                # outright, every first-person plural sentence was one fact short and one fact wrong.
                if node.id in reflexive:
                    continue        # its term is the doer's already
                held_of = node.properties or {}
                person, number = str(held_of.get("PERS", "3")), str(held_of.get("NUM", "sg"))
                one = {"1": "?speaker", "2": "?listener"}.get(person)
                if one is None:
                    # ONE `?previous` IS ALL THE MEANING LANGUAGE HAS (`derived_reader.SITUATION_VARIABLES`), so
                    # two pronouns that cannot be the same thing cannot both be said: "He fixed it." came out as
                    # the one spoken of before fixing ITSELF, which is not what the sentence says, and the measure's
                    # own way of lining a pronoun up with the gold cannot undo a merge
                    # (`pronouns_as_unknowns`). Told apart by what the ERG holds of each, since two mentions of
                    # "he" ARE one thing and "he" and "it" are not.
                    pointed_back.add((person, number, str(held_of.get("GEND", ""))))
                    counted[node.id] = "?previous"
                elif number == "pl":
                    add("has_member", here, one)
                else:
                    counted[node.id] = one
            elif says in ("person", "place", "time", "thing"):
                # A THING ANOTHER FACT ALREADY SPEAKS OF IS NAMED NOTHING. The ERG names what it knows of an
                # underspecified thing (`person` for "nobody", `place_n` for "where", `thing`, `generic_entity`,
                # `time_n`), and the PMB leaves it unnamed: "Where did Mahatma Gandhi study?" asks `?v1` with
                # nothing said it is, and "Nobody walks in LA." says a walker, not a person. Said, each was one
                # fact more than the meaning holds, over 276 uses of the dev split.
                # BUT A TERM NO OTHER FACT MENTIONS MUST KEEP ITS NAME, or the meaning asks for something it never
                # speaks of and is no meaning at all (14 dev sentences, 2026-11-01). Decided at the end, when every
                # other fact is in.
                loose[here] = says
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
            elif says in ("year", "day", "month", "weekday", "clock"):
                # A TIME IS THE LITERAL IT SAYS ("1945", "7:30 p.m."), as the reader writes one
                # (`literals.classify_literal`) and as the lessons say a time. Left a gap, 22 dev sentences said
                # nothing for a year alone.
                if node.carg:
                    counted[node.id] = str(node.carg)
                else:
                    gaps.append(f"nothing said for:{node.predicate}")
            elif says in ("many", "greatest", "more", "degree"):
                gaps.append(f"nothing said for:{node.predicate}")
            elif says == "has_count":
                if node.carg and node.edges.get("ARG1") in term:
                    add("has_count", of(node.edges.get("ARG1")), str(node.carg))
            elif says == "owned_by":
                # WAITED FOR: what a possessive says depends on what is possessed (`_possesses`), and the fact
                # saying what that is may not be in yet when this node is reached -- asked here it was never in,
                # and every possessive came out `owned_by` however the fix was written (2026-11-01).
                possessives.append((node.edges.get("ARG1"), node.edges.get("ARG2")))
            elif says == "located_in" and nodes.get(node.edges.get("ARG2")) is not None and \
                    ABSTRACT.get(nodes[node.edges["ARG2"]].predicate) in ("time", "year", "day", "month",
                                                                          "weekday", "clock"):
                # WHEN, NOT WHERE. The ERG says a bare time with the same predicate it says a bare place with
                # (`loc_nonsp`), and what tells them apart is what fills its second place: `time_n` for "When did
                # Jordan remove Luis?", `place_n` for "Where did Gandhi study?". Read as a place throughout, every
                # question asking when came out asking where something was (2026-11-02).
                add("during", of(node.edges.get("ARG1")), of(node.edges.get("ARG2")))
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
            if rest == "modal":
                # Possibility is read above (`HEDGING`); obligation and ability are not possibility and the meaning
                # language has no words for either, so the sentence is said as nothing rather than as a happening
                # named "must" done by what it stands over.
                gaps.append(f"nothing said for:{node.predicate}")
                continue
            add("instance_of", here, word)
            for role, link in VERB_PLACES.items():
                filled = node.edges.get(role)
                if filled in term and not _is_phrase(nodes, filled):
                    add(link, here, of(filled))
        elif kind in ("a", "j"):
            # A quality is said of what it is of; a comparative or a superlative of it is a gap.
            # A QUALITY NAMING A PLACE SAYS WHERE THE THING COMES FROM, as the PMB says it: "I am Korean."
            # `comes_from(?speaker, korea)`, never a quality called "korean". WordNet says which qualities those
            # are (a pertainym whose thing is a location), which is the same knowledge Lyric's own grammar uses
            # for it (`Words.defined`, `inherited("quality", ...)`).
            about = node.edges.get("ARG1")
            whence = _comes_from(word)
            if about in term and whence:
                add("comes_from", of(about), whence)
            elif about in term:
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

    # ── WHAT THE COPULA SAID A THING TO BE ──
    # Said to be of a kind, the thing IS one of that kind, and there is no second thing: "Tom is a boy."
    # `isa(tom, boy)` where the one spoken of is named, `instance_of` where it is not, as the lessons say it.
    for was, (subject, predicated) in copula.items():
        marked[0] = marks.get(was, Mark())
        here, there = of(subject), of(predicated)
        if here is None or there is None:
            continue
        kinds = [f.obj for f in facts if f.relation == "instance_of" and f.subject == there]
        if not kinds:
            continue
        facts = [f for f in facts if not (f.relation == "instance_of" and f.subject == there)]
        add("instance_of", here, kinds[0])
        # everything else said of the second thing is said of the one it is
        facts = [MeaningFact(f.relation, here if f.subject == there else f.subject,
                             here if f.obj == there else f.obj, f.positive, f.condition, f.alternative,
                             f.unasserted, f.given) for f in facts]
        term.pop(predicated, None)

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
    # SAID OF THE MAIN HAPPENING ALONE, which the ERG names (`top`), and not of every verb in the sentence: the ERG
    # holds a tense on an embedded verb too, and said of each one a sentence of two clauses was before now twice.
    # A present happening has no time said unless it is going on (`during`), as the lessons say it.
    # FOUND THROUGH WHATEVER STANDS OVER IT: the ERG names the condition or the modal as the sentence's own top
    # (`_if_x_then`, `_may_v_modal`) and holds no time of its own on either, so taken as the main happening the
    # sentence was left with no time at all, and the first verb in the graph's order instead was the CONDITION's
    # ("If Jordan disables the account, Luis loses his access." is about the losing). The force of the sentence is
    # still the top's, since asking or telling is of the whole sentence (`held`).
    through = governs(top) if top in operators else top
    main = through if through in term and through not in copula else next(
        (at for at in term if at not in copula and at not in operators
         and (_lemma(nodes[at].predicate) or ("", "", ""))[1] == "v"), None)
    if main is not None:
        marked[0] = marks.get(main, Mark())
        held_of = nodes[main].properties or {}
        when = str(held_of.get("TENSE", "")).lower()
        if when == "past":
            add("precedes", of(main), "?now")
        elif when == "fut":
            add("follows", of(main), "?now")
        elif when == "pres" and str(held_of.get("PROG", "")) == "+":
            add("during", of(main), "?now")
        elif str(held_of.get("PERF", "")) == "+":
            # ALREADY DONE BY NOW ("have disabled"), which the ERG holds as the perfect and not as a tense: under a
            # modal the happening itself is untensed ("may have disabled" is `TENSE: untensed PERF: +`), so read by
            # tense alone every hedged happening lost its time.
            add("precedes", of(main), "?now")
    act = {"ques": "ask", "prop": "tell", "comm": "request"}.get(str(held.get("SF", "prop")).lower(), "tell")

    # ── DENIALS ──
    # SAID OF THE HAPPENING ITSELF (`has_property(e, false)`), which is how the PMB writes a denial and how Lyric
    # reads one (`spell_out`: `add("has_property", e, "false")`). Said instead by marking each of the happening's
    # facts not so, every fact of "She doesn't speak Japanese." came out denied where the gold denies only the
    # speaking.
    #: Each term's marks, by the node its term came from, so a fact made at the end by term and not by node still
    #: carries what stood over the clause: "Unless Jordan approves it ..." is a condition AND a denial.
    by_term: Dict[str, Mark] = {}
    for at, held in marks.items():
        name = counted.get(at, term.get(at))
        if name:
            by_term[name] = held
    for at in denied | {of(x) for x in denied_later if of(x)}:
        if at:
            marked[0] = by_term.get(at, Mark())
            add("has_property", at, "false")

    # ── WHAT THE SENTENCE SAYS OF WHAT IT DOES NOT TELL ──
    # The status is told, whatever is held back: "Jordan may have disabled the account." tells you that it is
    # possible, and that is a fact of the disabling like any other, so it is said plainly and takes no mark.
    marked[0] = Mark()
    for at, status in held_back:
        # SAID ONLY OF A HAPPENING THE MEANING SPEAKS OF. Over a copula there is no happening to say it of ("Jordan
        # might not be an administrator." is one fact, that he is one, not so), and said anyway the status was a
        # fact about a term nothing else mentioned -- which is no meaning at all, as a loose term is not (below).
        # The degree is lost there and `unasserted` carries what matters: the sentence does not tell it as so.
        if any(of(at) in (f.subject, f.obj) for f in facts):
            add("has_property", of(at), status)
    for doer, doing in able:
        add("capable_of", counted.get(doer, term.get(doer)) if doer else None, doing)

    def standing(at: Optional[str]) -> Optional[str]:
        """What a node stands for NOW: the name or the speaker that replaced its term, else its term. Asked as
        `of()` after the names were put in, a conjunction of two names joined two terms nothing else mentions and
        "Tom and Mary left." came out with two unknowns (2026-11-01)."""
        return counted.get(at) if at in counted else of(at)

    # ── WHAT EACH POSSESSIVE SAYS, by what is possessed ──
    marked[0] = Mark()
    for whose, mine in possessives:
        here = standing(whose)
        kinds = [f.obj for f in facts if f.relation == "instance_of" and f.subject == here]
        add(_possesses(kinds[0]) if kinds else "owned_by", here, standing(mine))

    # ── WHAT TWO THINGS SAID TOGETHER ARE ──
    # READ OFF THE GOLD, not guessed. Of THINGS, the pair is a GROUP and each is a member of it, and the group
    # fills the place once: "Will you and Randy join us?" is a joining done by a group the listener and Randy are
    # members of (`has_member`), never two joinings. Of HAPPENINGS, there are simply two happenings, each with its
    # own doer and its own time: "Dick played piano and Lucy sang." Said instead by putting each of the two
    # wherever the pair stood, every coordination came out as two of whatever the pair filled, and the split fell
    # from 18.0% to 16.9% (2026-11-01).
    for pair, (one, other) in together.items():
        marked[0] = marks.get(pair, Mark())
        here = standing(pair)
        ends = [standing(one), standing(other)]
        if here is None or not all(ends):
            continue
        happenings = [at for at in (one, other)
                      if at in nodes and (_lemma(nodes[at].predicate) or ("", "", ""))[1] == "v"]
        if happenings:
            continue        # two happenings stand on their own; the word joining them says nothing more
        for end in ends:
            add("has_member", here, end)

    # ── A TERM NOTHING ELSE SPEAKS OF KEEPS THE NAME THE ERG GAVE IT ──
    marked[0] = Mark()
    for at, says in loose.items():
        if at and not any(at in (f.subject, f.obj) for f in facts):
            add("instance_of", at, says)

    if len(pointed_back) > 1:
        gaps.append("nothing said for:a second one spoken of before")
    if gaps:
        return Said(None, tuple(sorted(set(gaps))))
    kept = list(dict.fromkeys(facts))
    if not kept:
        return Said(None, ("nothing said",))
    try:
        return Said(Meaning(act, tuple(kept), tuple(sorted(asked))), ())
    except ValueError as problem:
        return Said(None, (f"not a meaning: {problem}",))
