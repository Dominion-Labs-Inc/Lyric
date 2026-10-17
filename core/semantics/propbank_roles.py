"""PropBank's roles in Lyric's meaning language: for each argument PropBank gives a predicate, the fact it is said in.

PropBank (CC BY-SA 4.0) says which phrase fills which role of which predicate: ARG0 and ARG1 (who did it, what it was
done to), ARG2 to ARG5 (each predicate's own frame names them), and the modifiers (ARGM-TMP when, ARGM-LOC where, ...).
Lyric's meaning language says the same in its link kinds (`relation_types.SemanticRelation`): a happening is
`instance_of` its kind, `done_by` who did it, `done_to` what it was done to, `received_by`, `done_with`, `moves_to`,
`located_in`, `during`, `has_purpose`, and so on. This maps every label PropBank's annotations of the English Web
Treebank use, every function tag and VerbNet role its frame files give a numbered argument, and every word that begins
a modifier whose kind the label alone does not settle, to one of:

  a FACT in a link kind the meaning language has, said of the happening or of another argument;
  a RULE, where what fills the argument settles the kind: an adjective `has_property`, a noun `isa`
    (`predicated`), a person `received_by` and a place `moves_to` (`goal`);
  NOTHING, where the argument states nothing of its own: "please" is the act, the light verb of "take a walk" leaves
    the walk the happening, "really" and "well" say how it is said;
  NEEDS, where the meaning language has no kind or term for it yet, named so it can be decided.

The kinds and terms are the ones the lessons already say these things in: "can" is `capable_of` ("Rex can swim."),
"would" `has_property(?v, hypothetical)`, "may" `has_property(?v, allowed)` ("May I open the box?"), "on the table"
`located_at`, "in the city" `located_in`, "with a key" `done_with`, "has a bike" `owns`, "needs a cup" `requires`.

NOTHING IS GUESSED. A label, role or word this does not name is not mapped (`said` gives None), and
`experiments/PROPBANK-01` counts and lists every one on the whole treebank.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple, Union

#: What a fact is said of, and what it says of it: the happening the predicate names (`event`), what fills this
#: argument (`argument`), what fills the predicate's own proto-patient or the thing a quality is said of (`theme`), its
#: proto-agent (`doer`), the moment of speaking (`now`), or a term the grammar names itself (`=hypothetical`).
PLACES = ("event", "argument", "theme", "doer", "now")


@dataclass(frozen=True)
class Said:
    """How one argument is said. `how` is one of:

      fact       a fact in `kind`, of `of` and `to` (`PLACES`, or `=term`), not so where `positive` is False, not told
                 as so where `unasserted` (what someone says, wants, or may do);
      rule       the kind is settled by what fills the argument (`RULES`), named in `rule`;
      negates    the happening's facts are said not so ("not", "never");
      condition  the argument's facts are a condition of the happening's ("if", "unless" with `positive` False);
      act        what the speaker wants done (`kind`: tell, ask, request), as "please" makes a request;
      happening  a happening of the speaker's to the listener, of kind `kind` (a greeting, thanks, an apology);
      same       the argument stands for another and takes its role (a relative pronoun, a continued argument);
      other side the other side of a fact another argument's entry names (`PREDICATES`: "parts" of `consist.01`);
      nothing    the argument states nothing of its own;
      needs      the meaning language has no kind or term for it yet (`needs` names it)."""

    how: str
    kind: str = ""
    of: str = "event"
    to: str = "argument"
    positive: bool = True
    unasserted: bool = False
    rule: str = ""
    needs: str = ""


def speaker_does(kind: str) -> Said:
    """A happening of the speaker's, to the listener, as the lessons teach greeting and thanking: "Hello." is a
    `greet` done by the speaker, done to the listener."""
    return Said("happening", kind, of="speaker", to="listener")


def fact(kind: str, of: str = "event", to: str = "argument", *, positive: bool = True,
         unasserted: bool = False) -> Said:
    return Said("fact", kind, of, to, positive, unasserted)


def rule(name: str) -> Said:
    return Said("rule", rule=name)


def needs(what: str) -> Said:
    return Said("needs", needs=what)


NOTHING = Said("nothing")
SAME = Said("same")
NEGATES = Said("negates")

#: What the rules decide between, by what fills the argument (its class, as the structure reader gives it).
RULES: Mapping[str, str] = {
    "predicated": "an adjective `has_property` of the theme; a noun `isa` (of a kind) or `instance_of` (of a "
                  "particular); a name `named`",
    "goal": "a person, a name or a pronoun `received_by`; a clause `has_purpose`; a place `moves_to`",
    "pivot": "set by the predicate: what it owns (`owns`), holds (`contains`), needs (`requires`); else its doer",
    "quality": "an adjective predicate is a quality: `has_property` of its first argument, the adjective its term",
    "only": "the happening, and no other than the argument did it: the fact, and the same fact `other_than` it not so",
    "each other": "each fact said both ways round",
    "addressed": "who is spoken to: a name `named` of the listener, a word for a person `instance_of` of it",
    "according": "what the argument says: a saying `done_by` it, the happening its `done_to`, not told as so",
}

#: The gaps: what the meaning language has no kind or term for yet. The first two are terms of the grammar's own, as
#: `allowed` and `hypothetical` are (`has_property` of the happening); the last is a link between what two sentences
#: tell, which a meaning, one sentence's, cannot hold.
NEEDS: Mapping[str, str] = {
    "possible": "what may or might be so (\"might\", \"maybe\", \"probably\"): a term like `hypothetical`",
    "necessary": "what must or should be done (\"must\", \"should\", \"have to\"): a term like `allowed`",
    "between sentences": "how one sentence's telling stands to the one before (\"but\", \"so\", \"then\", "
                         "\"or\"): contrast, result, sequence, alternative",
    "felt": "what the speaker feels as they say it (\"wow\", \"ugh\", \"lol\", \"oops\"): the acts are tell, ask "
            "and request, and a feeling is none of them",
}

# ── the modifiers ────────────────────────────────────────────────────────────────────────────────────────────────

#: ARGM labels, and the labels that are not roles of their own. A label whose kind the words settle is a rule named
#: for its label (`by_word`).
LABELS: Mapping[str, Said] = {
    "ARGM-TMP": rule("time"),
    "ARGM-LOC": rule("place"),
    "ARGM-DIR": rule("direction"),
    "ARGM-GOL": rule("goal"),
    "ARGM-MNR": rule("manner"),
    "ARGM-EXT": rule("extent"),
    "ARGM-MOD": rule("modal"),
    "ARGM-ADV": rule("adverbial"),
    "ARGM-DIS": rule("discourse"),
    "ARGM-CXN": rule("comparison"),
    "ARGM-CAU": fact("caused_by"),
    "ARGM-PRP": fact("has_purpose"),
    "ARGM-PNC": fact("has_purpose"),
    "ARGM-NEG": NEGATES,
    # An adjective said of a happening a noun names: "a quick decision".
    "ARGM-ADJ": fact("has_property"),
    # A secondary predication: "painted the door red", red of the door.
    "ARGM-PRD": fact("has_property", of="theme"),
    # The noun of a light verb names the happening: "take a walk" is a walk.
    "ARGM-PRR": fact("instance_of"),
    "ARGM-LVB": NOTHING,
    # Who did it with them did it too: "went to the park with Kim".
    "ARGM-COM": fact("done_by"),
    "ARGM-REC": rule("each other"),
    # Direct speech: what was said, not told as so.
    "ARG1-DSP": fact("done_to", unasserted=True),
    # The causer of a caused happening: "made him run".
    "ARGA": fact("done_by"),
    # A particle of the predicate ("check out"): part of the predicate, not an argument.
    "C-V": NOTHING,
}


def label_of(name: str) -> Tuple[str, str]:
    """A label as PropBank writes it, apart into what it is and how it stands: "R-ARG0" is ARG0 standing for its
    antecedent (a relative pronoun), "C-ARG1" the continuation of an ARG1 written apart. ("ARG0", "R")."""
    match = re.fullmatch(r"(?:([RC])-)?(.+)", name)
    return match.group(2), match.group(1) or ""


# ── the numbered arguments ───────────────────────────────────────────────────────────────────────────────────────

#: VerbNet's thematic roles, as PropBank's frame files link each numbered argument to them (VerbNet 3.4).
VERBNET: Mapping[str, Said] = {
    "agent": fact("done_by"),
    "causer": fact("done_by"),
    "affector": fact("done_by"),
    # A second doer: "Tom talked with Kim", both talked.
    "co_agent": fact("done_by"),
    # Who sees, likes or knows does it, as the lessons say it: "Rex saw her." is a seeing done by Rex.
    "experiencer": fact("done_by"),
    "patient": fact("done_to"),
    "theme": fact("done_to"),
    "co_patient": fact("done_to"),
    "co_theme": fact("done_to"),
    "stimulus": fact("done_to"),
    "reflexive": fact("done_to"),
    # What is begun, tried or wanted: a happening of its own, not told as so ("Rex wants to swim").
    "eventuality": fact("done_to", unasserted=True),
    "predicate": fact("done_to", unasserted=True),
    "pivot": rule("pivot"),
    "topic": fact("about"),
    "recipient": fact("received_by"),
    "beneficiary": fact("done_for"),
    "instrument": fact("done_with"),
    "destination": rule("goal"),
    "goal": rule("goal"),
    "source": fact("moves_from"),
    "initial_location": fact("moves_from"),
    "initial_state": fact("moves_from"),
    "trajectory": fact("moves_through"),
    "location": rule("place"),
    "attribute": rule("predicated"),
    "result": rule("predicated"),
    "product": fact("creates"),
    "material": fact("made_of", of="theme"),
    "value": fact("has_measure"),
    "asset": fact("has_measure"),
    "extent": fact("has_measure"),
    "duration": fact("lasts_for"),
    "precondition": fact("requires"),
    "subeventuality": fact("part_of", of="argument", to="event"),
    "circumstance": fact("has_property"),
}

#: The frame files' VerbNet roles as some are misspelled there.
_VERBNET_WRITTEN = {"co-agent": "co_agent", "co-patient": "co_patient", "co-theme": "co_theme", "ptient": "patient",
                    "intial_state": "initial_state", "initial-state": "initial_state",
                    "initial-location": "initial_location", "experiencer??": "experiencer"}

#: PropBank's function tags, for a numbered argument VerbNet gives no role.
FUNCTION_TAGS: Mapping[str, Said] = {
    "PAG": fact("done_by"),
    "PPT": fact("done_to"),
    "PRD": rule("predicated"),
    "GOL": rule("goal"),
    "DIR": rule("direction"),
    "LOC": rule("place"),
    "CAU": fact("caused_by"),
    "MNR": rule("manner"),
    "PRP": fact("has_purpose"),
    "EXT": rule("extent"),
    "TMP": rule("time"),
    "COM": fact("done_by"),
    "ADJ": fact("has_property"),
    "ADV": fact("has_property"),
    # The two ends of a spatial relation: who faces and what is faced, the near thing and what it is near.
    "SE1": fact("done_by"),
    "SE2": fact("done_to"),
    # A barrier crossed.
    "AXSP": fact("moves_across"),
    "DOM": fact("about"),
    "PRT": NOTHING,
}

#: The roles of predicates the frame files do not hold (PropBank's own convention: ARG0 is the proto-agent, ARG1 the
#: proto-patient).
BY_NUMBER: Mapping[str, Said] = {"ARG0": fact("done_by"), "ARG1": fact("done_to")}

# ── predicates said in a link kind of their own ──────────────────────────────────────────────────────────────────

#: Predicates the meaning language says without a happening: each argument's place in one fact (`of`/`to` naming the
#: arguments), or `predicated` (`be.01`: "Whales are mammals."), or nothing (an auxiliary, the "there is" of `be.02`,
#: whose thing's own facts are all it says). An argument not named here is said as any other.
PREDICATES: Mapping[str, Mapping[str, Said]] = {
    "have.03": {"ARG0": fact("owns", of="argument", to="ARG1")},   # "Rex has a bike."; a part `has_part`
    "own.01": {"ARG0": fact("owns", of="argument", to="ARG1")},
    "possess.01": {"ARG0": fact("owns", of="argument", to="ARG1")},
    "belong.01": {"ARG1": fact("owns", of="argument", to="ARG0")},
    "need.01": {"ARG0": fact("requires", of="argument", to="ARG1")},  # "Rex needs a cup."
    "require.01": {"ARG0": fact("requires", of="argument", to="ARG1"), "ARG2": needs("necessary")},
    "contain.01": {"ARG0": fact("contains", of="argument", to="ARG1")},
    "include.01": {"ARG2": fact("has_member", of="argument", to="ARG1")},
    "consist.01": {"ARG1": fact("has_part", of="argument", to="ARG2")},
    "cause.01": {"ARG0": fact("causes", of="argument", to="ARG1")},
    "equal.01": {"ARG1": fact("equals", of="argument", to="ARG2")},
    "exceed.01": {"ARG0": fact("exceeds", of="argument", to="ARG1"), "ARG2": fact("has_measure")},
    "resemble.01": {"ARG1": fact("similar_to", of="argument", to="ARG2")},
    "precede.01": {"ARG1": fact("precedes", of="argument", to="ARG2")},
    "follow.01": {"ARG1": fact("follows", of="argument", to="ARG2")},
    "able.01": {"ARG1": fact("capable_of", of="argument", to="ARG2")},  # "Rex can swim."
    "close.10": {"ARG1": fact("near", of="argument", to="ARG2")},
    "be.01": {"ARG2": rule("predicated")},
    "become.01": {"ARG2": rule("predicated")},
    "get.03": {"ARG2": rule("predicated")},
    "name.01": {"ARG2": fact("named", of="ARG1")},
    "call.01": {"ARG2": fact("named", of="ARG1")},
    "mean.01": {"ARG1": fact("defined_as", of="argument", to="ARG2")},
    "cost.01": {"ARG2": fact("has_measure", of="ARG1")},
    "weigh.01": {"ARG3": fact("has_measure", of="ARG1")},
    "have.11": {"ARG1": NOTHING},   # "have yet to": fixed
    # Every verb-specific role the treebank uses that the frame files give no VerbNet role, by what the frame file
    # says it is: a price or a value `has_measure`, a subject matter or a domain `about`, a means `done_with`.
    **{r: {a: fact("has_measure")} for r, a in (
        ("offer.01", "ARG2"), ("deal.01", "ARG3"), ("receive.01", "ARG3"), ("run.03", "ARG2"),
        ("stretch.01", "ARG2"), ("average.01", "ARG2"), ("bid.01", "ARG2"), ("cheap.02", "ARG3"),
        ("come.05", "ARG3"), ("pick_up.04", "ARG3"), ("rank.01", "ARG4"), ("sale.05", "ARG3"))},
    "worth.01": {"ARG2": fact("has_measure", of="theme")},
    **{r: {a: fact("about")} for r, a in (
        ("quote.01", "ARG3"), ("recommend.01", "ARG4"), ("wrong.02", "ARG2"), ("differ.02", "ARG3"),
        ("instruct.01", "ARG3"), ("beat.03", "ARG2"), ("lucky.02", "ARG2"), ("contest.02", "ARG2"),
        ("give.16", "ARG2"), ("overcharge.01", "ARG3"), ("score.01", "ARG3"), ("advanced.02", "ARG2"),
        ("alike.05", "ARG2"), ("broad.02", "ARG2"), ("call.10", "ARG1"), ("cap.01", "ARG3"),
        ("conviction.02", "ARG2"), ("cover.01", "ARG3"), ("decide.01", "ARG3"), ("fortunate.01", "ARG2"),
        ("lie.08", "ARG3"), ("misunderstand.01", "ARG3"), ("moderate.01", "ARG2"), ("progress.01", "ARG2"),
        ("rate.01", "ARG3"), ("refund.01", "ARG3"), ("safe.01", "ARG2"), ("sue.02", "ARG2"),
        ("unfortunate.01", "ARG2"))},
    **{r: {a: fact("done_with")} for r, a in (
        ("treat.04", "ARG2"), ("carry.01", "ARG3"), ("encase.01", "ARG2"), ("make_up.16", "ARG2"),
        ("upholster.01", "ARG2"))},
    **{r: {a: fact("done_to")} for r, a in (
        ("concentrate.01", "ARG2"), ("endure.01", "ARG2"), ("take.25", "ARG2"))},
    "common.01": {"ARG2": fact("done_for")},
    "auction.02": {"ARG4": fact("done_for")},
    "compose.01": {"ARG2": fact("has_part", of="theme")},
    "exclude.01": {"ARG2": fact("has_member", of="argument", to="theme", positive=False)},
    "pale.02": {"ARG2": fact("exceeds", of="argument", to="theme")},
    "superior.01": {"ARG2": fact("exceeds", of="theme")},
    "project.02": {"ARG2": rule("predicated")},
    "save.02": {"ARG2": fact("moves_from")},
    "starve.01": {"ARG2": fact("requires", of="theme")},
    "time.01": {"ARG2": fact("lasts_for")},
    "bump.02": {"ARG5": fact("moves_toward")},
    "zoom.02": {"ARG2": fact("moves_toward")},
    # Senses the frame files do not hold, by how the treebank uses them: "took place" and "changes hands" are fixed
    # ("place" and "hands" say nothing of their own), "has nothing to do with" says how much two things are
    # connected, and what is checked is said as checked ("check if they had it": not told as so).
    "take.14": {"ARG2": NOTHING},
    "change.02": {"ARG2": NOTHING},
    "do.04": {"ARG2": rule("connected")},
    "check.01": {"ARG2": rule("checked")},
}

#: How an argument of a predicate the frame files do not hold is said, past ARG0 and ARG1: by the preposition that
#: begins it, which says its part in English ("for" whom, "with" what, "about" what).
PREPOSITIONS: Mapping[str, Said] = {
    "for": fact("done_for"), "to": rule("goal"), "into": fact("moves_into"), "onto": fact("moves_onto"),
    "in": fact("located_in"), "at": fact("located_at"), "on": fact("located_at"), "with": fact("done_with"),
    "from": fact("moves_from"), "about": fact("about"), "regarding": fact("about"), "concerning": fact("about"),
    "of": fact("about"), "against": fact("done_to"), "by": fact("done_by"), "through": fact("moves_through"),
}

#: The other side of a fact another argument's entry names (`to="ARG2"`): said in that fact, not apart.
OTHER_SIDE = Said("other side")

#: Predicates that are no happening: an auxiliary says the tense of the verb it stands with ("have" of "have seen":
#: `precedes` now), `be.02` that its thing is ("There were three dogs."), and "have to" what must be done.
NO_HAPPENING: Mapping[str, Said] = {
    "be.03": NOTHING, "have.01": NOTHING, "do.01": NOTHING, "be.02": NOTHING,
    "have.02": needs("necessary"),
}


def predicate(roleset: str, part_of_speech: str = "") -> Optional[Said]:
    """How a predicate itself is said, where it is not a happening of its kind: an auxiliary, `be.02` or a light verb
    says nothing; an adjective is a quality (`quality`). None for a happening."""
    if roleset in NO_HAPPENING:
        return NO_HAPPENING[roleset]
    if roleset.endswith(".LV"):
        return NOTHING
    if part_of_speech.startswith("JJ"):
        return rule("quality")
    return None


# ── what the words settle ────────────────────────────────────────────────────────────────────────────────────────

#: Each rule named for a label: the word that begins the argument, lowercased, to how it is said, and how what no
#: word names is said (None: not mapped).
_FREQUENCY = ("always", "often", "usually", "sometimes", "frequently", "occasionally", "rarely", "seldom",
              "normally", "generally", "typically", "constantly", "repeatedly", "regularly", "daily", "weekly",
              "monthly", "yearly", "annually", "twice", "again", "ever", "every", "each")
WORDS: Mapping[str, Tuple[Mapping[str, Said], Union[None, Said, Mapping[str, Said]]]] = {
    "time": ({**{w: fact("precedes") for w in ("before", "prior", "ago", "previously", "earlier", "formerly")},
              **{w: fact("follows") for w in ("after", "afterwards", "afterward", "later", "next", "subsequently",
                                              "once")},
              **{w: fact("lasts_since") for w in ("since",)},
              **{w: fact("lasts_until") for w in ("until", "till", "til", "by", "up")},
              **{w: fact("lasts_for") for w in ("for", "throughout", "within")},
              **{w: fact("has_property") for w in _FREQUENCY},
              "never": NEGATES},
             fact("during")),
    "place": ({**{w: fact("located_in") for w in ("in", "inside", "within", "into", "among", "amongst",
                                                   "amid", "throughout")},
               **{w: fact("located_in", positive=False) for w in ("outside", "out")},
               **{w: fact("above") for w in ("above", "over", "atop", "upstairs")},
               **{w: fact("below") for w in ("below", "under", "beneath", "underneath", "downstairs")},
               **{w: fact("behind") for w in ("behind",)},
               **{w: fact("in_front_of") for w in ("front", "before")},
               **{w: fact("near") for w in ("near", "beside", "besides", "next", "close", "nearby", "alongside",
                                            "around", "by")},
               **{w: fact("between") for w in ("between",)},
               "in front": fact("in_front_of")},
              fact("located_at")),
    "direction": ({**{w: fact("moves_toward") for w in ("to", "toward", "towards", "forward", "forwards",
                                                         "ahead", "back", "home", "onward", "on")},
                   "into": fact("moves_into"), "onto": fact("moves_onto"), "out": fact("moves_out_of"),
                   **{w: fact("moves_through") for w in ("through", "via", "along", "thru")},
                   "across": fact("moves_across"), "over": fact("moves_over"),
                   **{w: fact("moves_around") for w in ("around", "round", "about")},
                   **{w: fact("moves_up") for w in ("up", "upward", "upwards", "upstairs")},
                   **{w: fact("moves_down") for w in ("down", "downward", "downwards", "downstairs")},
                   **{w: fact("moves_from") for w in ("from", "away", "off", "out of")}},
                  fact("moves_toward")),
    "manner": ({**{w: fact("done_with") for w in ("with", "by", "via", "using", "through", "use")},
                "without": fact("done_with", positive=False),
                **{w: fact("similar_to") for w in ("like", "as", "unlike")}},
               fact("has_property")),
    "extent": ({w: fact("has_degree") for w in ("very", "so", "too", "really", "highly", "extremely", "pretty",
                                                "quite", "completely", "fully", "totally", "much", "more", "most",
                                                "less", "least", "super", "rather", "somewhat", "slightly", "barely",
                                                "hardly", "entirely", "absolutely", "incredibly", "enough",
                                                "further", "far", "even", "almost", "nearly", "fairly", "all",
                                                "deeply", "greatly", "seriously", "terribly", "how")},
               fact("has_measure")),
    "modal": ({**{w: fact("follows", to="now") for w in ("will", "'ll", "ll", "-ll", "wo", "wil", "willl",
                                                          "shall", "shal", "gonna")},
               **{w: fact("capable_of", of="doer", to="event") for w in ("can", "ca", "could", "cant")},
               **{w: fact("has_property", to="=hypothetical") for w in ("would", "'d", "d", "woud", "wud",
                                                                        "woul", "ould")},
               **{w: needs("possible") for w in ("may", "might", "mite")},
               **{w: needs("necessary") for w in ("must", "should", "shoul", "ought", "shld", "need")}},
              None),
    "discourse": ({**{w: Said("act", "request") for w in ("please", "pls", "plz", "pl", "pleasseee")},
                   **{w: speaker_does("greet") for w in ("hi", "hello", "hey", "yo")},
                   **{w: speaker_does("thank") for w in ("thanks", "thank", "thx")},
                   **{w: speaker_does("apologize") for w in ("sorry", "sry")},
                   # What adds, answers, fills a pause or points ahead states nothing of its own.
                   **{w: NOTHING for w in ("also", "too", "and", "amd", "&", "plus", "further", "furthermore",
                                           "additionally", "likewise", "besides", "moreover", "yes", "yeah", "yea",
                                           "yep", "ya", "aye", "ye$", "no", "nope", "ok", "okay", "alright", "sure",
                                           "right", "well", "like", "just", "even", "again", "now", "there", "as",
                                           "um", "uh", "em", "ummmm", "hmm", "hmmm", "hmmmmmm", "o", "btw", "fyi",
                                           "i.e.", "ie", "say", "kind", "actually", "indeed", "seriously",
                                           "whatever", "overall", "by the", "of course", "for example",
                                           "for instance", "in addition", "in fact", "at least", "to be")},
                   **{w: fact("has_property") for w in ("unfortunately", "fortunately", "understandably",
                                                        "hopefully")},
                   **{w: needs("possible") for w in ("maybe", "perhaps")},
                   "imo": rule("according"),
                   **{w: needs("between sentences") for w in ("but", "however", "though", "although", "yet",
                                                              "instead", "otherwise", "nevertheless", "whereas",
                                                              "nonetheless", "so", "therefore", "thus", "hence",
                                                              "accordingly", "consequently", "then", "finally",
                                                              "lastly", "second", "next", "or", "either",
                                                              "neither", "anyway", "anyways", "anyhow",
                                                              "on the", "after all", "in contrast")},
                   **{w: needs("felt") for w in ("lol", "lols", "haha", "hehe", "heh", "ha", "wow", "omg", "ugh",
                                                 "ewww", "sigh", "oops", "jeez", "sheesh", "shucks", "heck", "hell",
                                                 "christ", "fcking", "yum", "grrrrrrr", "huh", "oh", "ohh", "lo",
                                                 "good", "great")}},
                  {"NAME": rule("addressed"), "NOUN": rule("addressed"), "PRONOUN": rule("addressed"),
                   "INTERJECTION": needs("felt")}),
    "comparison": ({**{w: fact("exceeds") for w in ("than", "then", "more", "less", "too", "larger", "smaller",
                                                    "better", "worse", "lower", "higher", "far", "much", "rather",
                                                    "sooo", "so", "to", "for", "enough")},
                    **{w: fact("equals") for w in ("as", "same")},
                    "instead": fact("other_than"),
                    "that": fact("causes")},
                   None),
    "connected": ({"nothing": NEGATES}, fact("has_degree")),
    "checked": ({w: fact("done_to", unasserted=True) for w in ("if", "whether")}, fact("done_to")),
    "adverbial": ({**{w: Said("condition") for w in ("if", "provided", "providing", "assuming", "whether", "in case",
                                                     "once", "whenever", "wherever")},
                   "unless": Said("condition", positive=False),
                   **{w: fact("has_property", to="=unexpected") for w in ("although", "though", "even", "despite",
                                                                          "regardless", "whereas", "notwithstanding",
                                                                          "nevertheless", "nonetheless", "still",
                                                                          "yet", "anyway", "however")},
                   **{w: fact("caused_by") for w in ("because", "since", "given", "due", "thanks", "cause", "cuz",
                                                     "bc", "coz", "considering", "seeing")},
                   **{w: fact("causes") for w in ("so", "therefore", "thus", "hence", "consequently")},
                   **{w: fact("has_purpose") for w in ("to", "in order", "so that")},
                   **{w: fact("during") for w in ("while", "when", "whilst", "during", "as", "meanwhile")},
                   **{w: fact("follows") for w in ("then", "after", "afterwards", "later")},
                   **{w: fact("precedes") for w in ("before",)},
                   "only": rule("only"), "just": NOTHING,
                   **{w: NOTHING for w in ("also", "too", "really", "actually", "basically", "literally",
                                           "seriously", "honestly", "definitely", "certainly", "clearly",
                                           "obviously", "simply", "totally", "truly", "indeed", "especially",
                                           "particularly", "mainly", "mostly", "generally", "all", "both",
                                           "either", "again", "at least", "in fact", "of course", "for example",
                                           "for instance", "in addition", "besides", "otherwise", "anyhow")},
                   **{w: needs("possible") for w in ("probably", "maybe", "perhaps", "possibly", "likely",
                                                     "apparently", "presumably", "supposedly", "hopefully")},
                   "according": rule("according"),
                   "instead": fact("other_than"), "except": fact("other_than"), "besides": fact("other_than")},
                  fact("has_property")),
}

def by_word(name: str, words: Tuple[str, ...], first_class: str = "") -> Optional[Said]:
    """How a modifier whose kind its words settle is said (`WORDS`), by the words that begin it (two read as one
    first: "in order", "of course"), else by the class of its first word where the rule says so by class (a name
    beginning a discourse marker is who is spoken to); None when the rule names neither."""
    table, otherwise = WORDS[name]
    lowered = tuple(w.lower() for w in words)
    if len(lowered) > 1 and " ".join(lowered[:2]) in table:
        return table[" ".join(lowered[:2])]
    if lowered and lowered[0] in table:
        return table[lowered[0]]
    if isinstance(otherwise, Mapping):
        return otherwise.get(first_class)
    return otherwise


def verbnet_role(written: str) -> str:
    """A VerbNet role as the frame files write it, spelled as VerbNet spells it."""
    written = written.strip().lower()
    return _VERBNET_WRITTEN.get(written, written)


def said(label: str, *, roleset: str = "", function_tag: str = "", verbnet: Tuple[str, ...] = (),
         words: Tuple[str, ...] = (), first_class: str = "") -> Optional[Said]:
    """How an argument PropBank labels so is said in the meaning language: by the predicate where it is said in a
    link kind of its own (`PREDICATES`), by the label for a modifier (`LABELS`), and for a numbered argument by its
    VerbNet role, else its function tag, else PropBank's own convention for ARG0 and ARG1. Where that is a rule the
    words settle, the words that begin the argument settle it (`by_word`). A relative pronoun or a continuation is
    `SAME`: it takes the role of the argument it stands for. None when nothing here maps it."""
    def settled(found: Optional[Said]) -> Optional[Said]:
        if found is not None and found.how == "rule" and found.rule in WORDS:
            return by_word(found.rule, words, first_class)
        return found
    if label in LABELS:
        return settled(LABELS[label])
    base, stands = label_of(label)
    if stands:
        return SAME
    if roleset in PREDICATES:
        entries = PREDICATES[roleset]
        if base in entries:
            return settled(entries[base])
        if any(base in (found.of, found.to) for found in entries.values()):
            return OTHER_SIDE
    if base in LABELS:
        return settled(LABELS[base])
    if not re.fullmatch(r"ARG\d", base):
        return None
    for role in verbnet:
        role = verbnet_role(role)
        if role in VERBNET:
            return settled(VERBNET[role])
    if function_tag.upper() in FUNCTION_TAGS:
        return settled(FUNCTION_TAGS[function_tag.upper()])
    if base in BY_NUMBER:
        return BY_NUMBER[base]
    if not function_tag and words:
        return PREPOSITIONS.get(words[0].lower())
    return None


def kinds_used() -> Dict[str, int]:
    """Every link kind this maps to, and how many entries name it: each must be one the meaning language has."""
    out: Dict[str, int] = {}

    def note(found: Said) -> None:
        if found.how == "fact" and found.kind:
            out[found.kind] = out.get(found.kind, 0) + 1
    for found in (*LABELS.values(), *VERBNET.values(), *FUNCTION_TAGS.values(), *BY_NUMBER.values(),
                  *PREPOSITIONS.values()):
        note(found)
    for roles in PREDICATES.values():
        for found in roles.values():
            note(found)
    for table, otherwise in WORDS.values():
        for found in table.values():
            note(found)
        for found in (otherwise.values() if isinstance(otherwise, Mapping) else (otherwise,) if otherwise else ()):
            note(found)
    return out
