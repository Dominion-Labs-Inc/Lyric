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
    #: A term the ERG named only as an underspecified thing -> what it named it. Said only where no other fact
    #: speaks of the term.
    loose: Dict[Optional[str], str] = {}
    #: (the thing possessed, whose it is), answered once every fact saying what things are is in.
    possessives: List[Tuple[Optional[str], Optional[str]]] = []

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
        if node.predicate.endswith("_q") or node.id in copula or node.id in together:
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
                held_of = node.properties or {}
                person, number = str(held_of.get("PERS", "3")), str(held_of.get("NUM", "sg"))
                one = {"1": "?speaker", "2": "?listener"}.get(person)
                if one is None:
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
    main = top if top in term and top not in copula else next(
        (at for at in term if at not in copula and (_lemma(nodes[at].predicate) or ("", "", ""))[1] == "v"), None)
    if main is not None:
        held_of = nodes[main].properties or {}
        when = str(held_of.get("TENSE", "")).lower()
        if when == "past":
            add("precedes", of(main), "?now")
        elif when == "fut":
            add("follows", of(main), "?now")
        elif when == "pres" and str(held_of.get("PROG", "")) == "+":
            add("during", of(main), "?now")
    act = {"ques": "ask", "prop": "tell", "comm": "request"}.get(str(held.get("SF", "prop")).lower(), "tell")

    # ── DENIALS ──
    # SAID OF THE HAPPENING ITSELF (`has_property(e, false)`), which is how the PMB writes a denial and how Lyric
    # reads one (`spell_out`: `add("has_property", e, "false")`). Said instead by marking each of the happening's
    # facts not so, every fact of "She doesn't speak Japanese." came out denied where the gold denies only the
    # speaking.
    for at in denied | {of(x) for x in denied_later if of(x)}:
        if at:
            add("has_property", at, "false")

    def standing(at: Optional[str]) -> Optional[str]:
        """What a node stands for NOW: the name or the speaker that replaced its term, else its term. Asked as
        `of()` after the names were put in, a conjunction of two names joined two terms nothing else mentions and
        "Tom and Mary left." came out with two unknowns (2026-11-01)."""
        return counted.get(at) if at in counted else of(at)

    # ── WHAT EACH POSSESSIVE SAYS, by what is possessed ──
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
    for at, says in loose.items():
        if at and not any(at in (f.subject, f.obj) for f in facts):
            add("instance_of", at, says)

    if gaps:
        return Said(None, tuple(sorted(set(gaps))))
    kept = list(dict.fromkeys(facts))
    if not kept:
        return Said(None, ("nothing said",))
    try:
        return Said(Meaning(act, tuple(kept), tuple(sorted(asked))), ())
    except ValueError as problem:
        return Said(None, (f"not a meaning: {problem}",))
