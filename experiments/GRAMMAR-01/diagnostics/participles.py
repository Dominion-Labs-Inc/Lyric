"""WHAT A PARTICIPLE SAYS, against the PMB's gold (2026-10-29, lab notebook (78)): each word of the PMB's gold
documents of a split written as a participle or an -ing form and standing where either a quality or a doing may stand,
what the gold says it is, and what each way of deciding gives.

The gold says one of four things of the word's span: a QUALITY (its sense an adjective: "Is the dog chained?"
`chained.a.01`, "a developed country" `developed.a.02`, "really thrilling" `thrilling.a.01`), a DOING DONE TO the
thing before it (a verb whose Patient or lone Theme is that thing: "I've been stung by a hornet." `sting.v.02`), a
DOING THE THING DOES (a verb with a doer: "Riding a horse" `ride.v.01`, "The phone is ringing."), or a THING (a
noun: "the opening"). Where it says nothing of the span, the word is of the sentence's grammar and is not counted.

Where the word stands is read from the text, and only the places where either may stand are counted: after a form of
"be" or "get" (an adverb allowed between: "is chained", "is really thrilling"), after "been" or "being", after a form
of "have", before a noun the gold names with a word of the grammar before it ("a developed country", "the escaped
robber"), or opening the sentence. A word standing anywhere else is not counted: after a thing, a word written as a
participle is as often the sentence's own verb ("Tom composed a sonnet.", "He fixed it."), which no spelling tells
apart from a thing's participle ("a book written by Tom"). Said with it: whether a "by" phrase follows, and whether a
thing the gold names follows with no preposition between.

The ways of deciding whether the word says a quality, each counted by how many of the gold's qualities it catches
and how many of what it calls qualities are ones (the words are nine in ten no quality, so how often a way is simply
right says little):

- `uses`: how the treebank's sentences use the very word (UD English EWT's training part, which is what the words
  memory holds are counted from): a quality where it is written as an adjective more often than as a verb;
- `an adjective once`: a quality where the treebank writes it as an adjective at all;
- `wordnet`: a quality where WordNet holds an adjective sense spelled as the word ("chained" `chained.s.01`,
  "stung" `annoyed.s.01`), which is what memory holds of a word no sentence it has read used;
- `uses, else wordnet`: the treebank's where it uses the word, WordNet's where it does not;
- `wordnet, nothing said with it`: WordNet's sense, and nothing said with the word that a quality does not take (no
  "by" phrase after it, no thing after it with no preposition between);
- `wordnet or an adjective once, nothing said with it`: the same, the treebank's adjective counted beside the sense.

From the Lyric folder:

    ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/participles.py train
"""
import collections, os, re, sys
from pathlib import Path

ROOT = Path(os.getcwd())
sys.path.insert(0, str(ROOT))
from nltk.corpus import wordnet as wn
from core.learning import teaching_sources as ts
from core.semantics import pmb_meanings as pm

pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
PREPS = ts._PREPOSITIONS_WRITTEN
BE = {"was", "were", "is", "are", "be", "am", "'s", "'re", "'m", "get", "got", "gets", "getting", "gotten"}
BEEN = {"been", "being"}
HAVE = {"have", "has", "had", "'ve", "'s", "'d"}
WORD = re.compile(r"[A-Za-z']+")
#: Written as a participle or an -ing form: the word is not its verb's plain form and is spelled as one of its forms.
ENDS = ("ing", "ed", "en", "n", "t", "d")


def words_of(text: str):
    """Each word of the text with where it is."""
    return [(m.group(0), m.start(), m.end()) for m in WORD.finditer(text)]


_verb: dict = {}


def verb_of(word: str):
    """The verb the word is a form of, where it is written as a participle or an -ing form and not as the verb
    itself ("chained" of `chain`, "stung" of `sting`; "chain" of nothing)."""
    low = word.lower()
    if low not in _verb:
        lemmas = {l for l in (wn.morphy(low, "v"),) if l} | {
            l.name().lower() for s in wn.synsets(low, "v") for l in s.lemmas() if l.name().lower() == low}
        said = next((l for l in sorted(lemmas) if l != low), None)
        _verb[low] = said if said and low.endswith(ENDS) else None
    return _verb[low]


_adjective: dict = {}


def adjective(word: str) -> bool:
    """Whether WordNet holds an adjective sense spelled as the word."""
    low = word.lower()
    if low not in _adjective:
        _adjective[low] = any(l.name().lower() == low for s in wn.synsets(low) if s.pos() in ("a", "s")
                              for l in s.lemmas())
    return _adjective[low]


def treebank_uses() -> dict:
    """How often each word of the treebank's training sentences is written as an adjective and as a verb."""
    counts: dict = collections.defaultdict(collections.Counter)
    for analysed in ts.read_conllu(ts.EWT_TRAIN, "ewt"):
        for word, cls in zip(analysed.words, analysed.classes):
            if cls in ("ADJECTIVE", "VERB"):
                counts[word.lower()][cls] += 1
    return counts


def main(split: str) -> None:
    ids = pm.split_ids(pmb / "split" / "en" / split / ("gold.sbn" if split == "train" else "standard.sbn"))
    uses = treebank_uses()
    stats: dict = collections.defaultdict(collections.Counter)
    ways = ("uses", "an adjective once", "wordnet", "uses, else wordnet", "wordnet, nothing said with it",
            "wordnet or an adjective once, nothing said with it")
    n_docs = 0
    for doc_id in ids:
        d = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        if d is None:
            continue
        n_docs += 1
        said = {}
        for c in d.concepts:
            m = pm._SENSE.match(c.sense)
            if m and c.span is not None:
                said.setdefault(c.span, []).append((c, m))
        spoken = sorted(said)
        text = d.text
        written = words_of(text)
        for k, (word, start, end) in enumerate(written):
            lemma = verb_of(word)
            if lemma is None:
                continue
            here = next((s for s in spoken if s[0] <= start and end <= s[1]), None)
            if here is None:
                continue        # of the sentence's grammar: "been", "going to"
            c, m = said[here][0]
            part = m.group("part")
            before = [w.lower() for w, _, _ in words_of(text[:start])]
            after = words_of(text[end:])
            nouns = {s for s in spoken for c2, m2 in said[s] if m2.group("part") == "n"}
            follows = next((s for s in nouns if s[0] >= end), None)
            by = next((w.lower() for w, _, _ in after[:1] if w.lower() == "by"), None)
            thing = follows is not None and not any(
                w.lower() in PREPS for w, a, _ in after if end + a < follows[0])
            near = [w for w in before if w not in ("really", "very", "so", "quite", "too", "n't", "not")]
            # A WORD OF THE GRAMMAR BEFORE IT ("a", "the", "hard-"), said by no line of its own but the word's: inside
            # what the noun after it says, not the sentence's own verb with its subject before it. A line's words are
            # the determiner with them ("*a* developed"), so its own line does not count.
            marks = bool(k) and not any(s[0] <= written[k - 1][1] and written[k - 1][2] <= s[1]
                                        for s in spoken if s != here)
            # A QUESTION PUTS ITS "BE" FIRST ("Is the dog chained?"), the subject between it and the word.
            asked = text.rstrip().endswith("?") and before and before[0] in BE | BEEN and end >= len(text.rstrip()) - 1
            stands = ("after be" if (near and near[-1] in BE) or asked else "after been" if near and near[-1] in BEEN
                      else "after have" if near and near[-1] in HAVE
                      else "before a noun" if follows is not None and follows[0] <= end + 1 and marks
                      else "opening" if not before else "")
            if not stands:
                continue
            if part in ("a", "s"):
                says = "quality"
            elif part == "n":
                says = "thing"
            elif part == "v":
                doers = any(r in pm.DOERS for r, _ in c.roles)
                done_to = any(pm.HAPPENING_ROLES.get(r) == "done_to" and pm._POINTER.match(v)
                              and 0 <= d.concepts.index(c) + int(v) < len(d.concepts)
                              and (d.concepts[d.concepts.index(c) + int(v)].span or (end, end))[1] <= start
                              for r, v in c.roles)
                says = "done to it" if done_to and not doers else "a doing"
            else:
                says = "otherwise"
            s = stats[(stands, "-ing" if word.lower().endswith("ing") else "-ed")]
            s["n"] += 1
            s[says] += 1
            held = uses.get(word.lower(), {})
            an_adjective, a_verb = held.get("ADJECTIVE", 0), held.get("VERB", 0)
            alone = by is None and not thing
            quality = {
                "uses": an_adjective > a_verb,
                "an adjective once": an_adjective > 0,
                "wordnet": adjective(word),
                "uses, else wordnet": an_adjective > a_verb if held else adjective(word),
                "wordnet, nothing said with it": alone and adjective(word),
                "wordnet or an adjective once, nothing said with it": alone and (an_adjective > 0
                                                                                 or adjective(word)),
            }
            for way in ways:
                s[f"{way}: said"] += quality[way]
                s[f"{way}: caught"] += quality[way] and says == "quality"
    print(f"{n_docs} documents ({split}); each word written as a participle or an -ing form where the gold says "
          f"what it is; of the gold's qualities, how many each way catches, and of what it calls qualities, how many "
          f"are ones:")
    for (stands, spelled), s in sorted(stats.items(), key=lambda x: -x[1]["n"]):
        n, qualities = s["n"], s["quality"]
        print(f"  {stands} ({spelled}) {n}  gold: " + ", ".join(
            f"{says} {s[says]} ({s[says] / n:.0%})" for says in ("quality", "done to it", "a doing", "thing")
            if s[says]))
        for way in ways:
            caught, said = s[f"{way}: caught"], s[f"{way}: said"]
            print(f"      {way:52} caught {caught:4} of {qualities:4}"
                  + (f" ({caught / qualities:5.1%})" if qualities else " " * 8)
                  + f", of {said:4} called qualities"
                  + (f" {caught / said:5.1%} are" if said else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "train")
