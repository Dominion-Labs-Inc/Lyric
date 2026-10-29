"""WHEN SEVERAL WORDS ARE ONE CONCEPT, against the PMB's gold (2026-10-29, lab notebook (79)): every concept of the
PMB's gold documents of a split whose words are several, what shape they are, and what each way of deciding would
give — against every run of words that is not one concept, which is what a way must not call one; and the link the
gold makes where a name stands right before a thing ("IKEA furniture").

A concept's own words are the words its span covers that no tighter span covers and that the line does not mark as
words of the sentence's grammar ("*the* European Constitution*.*", "*a* ring", "fist fighting *in*"). Where two or
more are left, the gold makes one concept of several words. A word the line marks is counted back in where the words
with it are one word of the language and the words without it are not, because a verb's particle is marked as a word
of the grammar and is part of the verb ("filled *out*" `fill_out.v.03`, "cleaned *up*", "rake *in*").

Two kinds are told apart, because only the first is a word of the language and the second is the annotation lumping
a word of the grammar or an adverb into a span:

- ONE WORD OF THE LANGUAGE: the line carries a `Name` of several words ("European Constitution", "Tomoyuki Ogura"),
  or WordNet's own sense spells the words joined as one of its lemmas ("prime minister" `prime_minister.n.02`,
  "disco music" `disco_music.n.01`, "fist fighting" `fistfight.v.01`, "fed up" `fed_up.a.01`);
- WORDS THE SPAN LUMPS: "Call again." (`call.v.03`, the adverb inside the verb's span), "insured with"
  (`insure.v.03`), "Is he Canadian too?" (`be.v.03`).

and by shape: a NAME (a `Name` of several words, or every word capitalised), a NOUN, a VERB, a QUALITY, an ADVERB,
a NUMBER OR A TIME (its words digits: "5 30", "50 000", handled by the clock in lab notebook (76)).

The ways of deciding, each counted by how many of the gold's concepts of several words it catches and how many of
what it calls one are ones:

- `capitalised`: every word of the run is capitalised, the sentence's first word counted only where the treebank
  writes it as a name at least as often as anything else (`Lexicon._mostly_name`, which asks memory the same);
  counted again split by whether the treebank writes every word of the run as a name, which is what the grammar
  scores a run by today (`Lexicon._together`: the run is as sure as each of its words is a name), against the runs
  whose words it writes otherwise ("the European Constitution": "European" an adjective, "Constitution" a noun);
- `wordnet, as written`: the words joined are a lemma of some WordNet sense ("prime_minister", "disco_music");
- `wordnet, the last word's base`: the same with the last word as its base ("ran away" `run_away`), which is how a
  verb of several words is spelled in WordNet;
- `wordnet, run together`: the words with nothing between them, as English writes a compound it has worn down
  ("goal keeper" `goalkeeper`, "cell phone" `cellphone`, "fist fighting" `fistfight` by its last word's base);
- `wordnet, any spelling`: any of the three, which is what memory holds of the words it is taught from WordNet
  (`WordNetSource._word_classes` teaches a word of several words as one, asked by `GraphKnowledge.known_name`);
- `capitalised or wordnet`: either, the two being the grammar's own two rules for words read as one
  (`Lexicon._together`: "words memory knows as one thing", `_name_runs`).

From the Lyric folder:

    ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/several_words.py train
"""
import collections, os, re, sys
from pathlib import Path

ROOT = Path(os.getcwd())
sys.path.insert(0, str(ROOT))
from nltk.corpus import wordnet as wn
from core.learning import teaching_sources as ts
from core.semantics import pmb_meanings as pm

pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
WORD = re.compile(r"[A-Za-z0-9']+(?:-[A-Za-z0-9']+)*")
#: The longest run of words the grammar reads as one (`Lexicon._together`).
LONGEST = 3
WAYS = ("capitalised", "capitalised, its words written as names", "capitalised, its words written otherwise",
        "wordnet, as written", "wordnet, the last word's base", "wordnet, run together", "wordnet, any spelling",
        "capitalised or wordnet")
SHAPES = ("a name", "a noun", "a verb", "a quality", "an adverb", "a number or a time", "otherwise")
#: The links a thing's own roles make, as the conversion reads them where `HAPPENING_ROLES` does not
#: (`pmb_meanings.meaning_of`): what made it, where it is from, what it is part of, whose it is.
LINKS = {"Creator": "creates", "Source": "comes_from", "Sub": "has_member", "SubOf": "member_of",
         "PartOf": "part_of", "Part": "has_part", "User": "owned_by", "Owner": "owned_by", "Role": "isa"}


def words_of(text: str):
    """Each word of the text with where it is, a hyphened word one."""
    return [(m.group(0), m.start(), m.end()) for m in WORD.finditer(text)]


_held: dict = {}


def in_wordnet(words) -> bool:
    """Whether WordNet holds the words joined as one word."""
    joined = "_".join(w.lower() for w in words)
    if joined not in _held:
        _held[joined] = bool(wn.synsets(joined))
    return _held[joined]


def based(words):
    """The words with the last as its base, where WordNet gives one ("fist fighting" -> "fist fight")."""
    last = words[-1].lower()
    for pos in ("v", "n", "a"):
        base = wn.morphy(last, pos)
        if base and base != last:
            return list(words[:-1]) + [base]
    return None


def treebank_names() -> set:
    """Each word the treebank writes as a name at least as often as anything else (UD English EWT's training part,
    which is what the words memory holds are counted from), as `Lexicon._mostly_name` asks of memory."""
    counts: dict = collections.defaultdict(collections.Counter)
    for analysed in ts.read_conllu(ts.EWT_TRAIN, "ewt"):
        for word, cls in zip(analysed.words, analysed.classes):
            counts[word.lower()][cls] += 1
    return {w for w, held in counts.items()
            if held.get("NAME", 0) >= sum(n for c, n in held.items() if c != "NAME")}


def ways_of(words, opens: bool, names: set) -> dict:
    """Each way of deciding whether these words are one concept. `opens`: the run opens the sentence, where a capital
    says nothing unless the word is written as a name anyway."""
    capitalised = all(w[:1].isupper() for w in words) \
        and not (opens and words[0].lower() not in names)
    written = in_wordnet(words)
    base = based(words)
    by_base = base is not None and in_wordnet(base)
    run = in_wordnet(["".join(words)]) or (base is not None and in_wordnet(["".join(base)]))
    held = written or by_base or run
    theirs = all(w.lower() in names for w in words)
    return {"capitalised": capitalised,
            "capitalised, its words written as names": capitalised and theirs,
            "capitalised, its words written otherwise": capitalised and not theirs,
            "wordnet, as written": written,
            "wordnet, the last word's base": by_base, "wordnet, run together": run,
            "wordnet, any spelling": held, "capitalised or wordnet": capitalised or held}


def shape_of(part: str, words, named: bool) -> str:
    """What the gold makes of the words."""
    if all(w.replace(":", "").replace(".", "").isdigit() for w in words) or part == "x":
        return "a number or a time"
    if named or all(w[:1].isupper() for w in words):
        return "a name"
    return {"n": "a noun", "v": "a verb", "a": "a quality", "s": "a quality",
            "r": "an adverb"}.get(part, "otherwise")


def spelled_so(senses, words) -> bool:
    """Whether one of the gold's own senses for these words spells them as one of its lemmas, in any spelling. The
    senses are the line's own and those of the span-less lines its roles point at, which is where the gold puts what
    the words name ("prime minister" `person.n.01` with a `Role` at `prime_minister.n.02`). A verb of several words
    carries its form on the first word and WordNet spells it on the base ("filled out" `fill_out.v.03`, "fell in
    love" `fall_in_love.v.01`), so the first word's verb is a spelling too; memory needs none of this, holding the
    forms of a word of several words as it holds a word's ("grew up" under `grow up`, `WordRecord.forms`)."""
    said = [list(words)]
    base = based(words)
    if base is not None:
        said.append(base)
    first = wn.morphy(words[0].lower(), "v")
    if first and first != words[0].lower():
        said += [[first] + list(ws[1:]) for ws in list(said)]
    spellings = {join.join(w.lower() for w in ws) for ws in said for join in ("_", "")}
    for sense in senses:
        try:
            lemmas = wn.synset(sense).lemmas()
        except Exception:
            continue
        if any(l.name().lower() in spellings for l in lemmas):
            return True
    return False


def senses_for(d, c):
    """The gold's senses for a line: its own, and those of the span-less lines its roles point at."""
    out = [c.sense]
    k = d.concepts.index(c)
    for _, v in c.roles:
        if pm._POINTER.match(v) and 0 <= k + int(v) < len(d.concepts):
            other = d.concepts[k + int(v)]
            if other.span is None:
                out.append(other.sense)
    return out


def own_words(d, written):
    """Each concept's own words: those its span covers that no tighter span covers, less the words of the grammar it
    marks. Keyed by where they are, valued (concept, its part of speech, its own words, and its own words with the
    grammar words the line marks counted back in)."""
    spans = []
    for c in d.concepts:
        m = pm._SENSE.match(c.sense)
        if m and c.span is not None:
            spans.append((c, m.group("part")))
    mine: dict = collections.defaultdict(list)
    for w, a, b in written:
        over = [(c, part) for c, part in spans if c.span[0] <= a and b <= c.span[1]]
        if not over:
            continue
        c, part = min(over, key=lambda x: (x[0].span[1] - x[0].span[0], x[0].span[0]))
        mine[id(c)].append((w, a, b))
    out = {}
    for c, part in spans:
        got = mine.get(id(c), [])
        marked = collections.Counter(w.lower() for w in c.marked)
        kept = []
        for w, a, b in got:
            if marked[w.lower()]:
                marked[w.lower()] -= 1
                continue
            kept.append((w, a, b))
        if kept:
            out[tuple(a for _, a, _ in kept)] = (c, part, [w for w, _, _ in kept], [w for w, _, _ in got])
    return out


def main(split: str) -> None:
    ids = pm.split_ids(pmb / "split" / "en" / split / ("gold.sbn" if split == "train" else "standard.sbn"))
    names = treebank_names()
    shapes: dict = collections.defaultdict(collections.Counter)
    runs: dict = collections.defaultdict(collections.Counter)
    before: collections.Counter = collections.Counter()
    capitals: collections.Counter = collections.Counter()
    in_runs: collections.Counter = collections.Counter()
    examples: dict = collections.defaultdict(list)
    n_docs = 0
    for doc_id in ids:
        d = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        if d is None:
            continue
        n_docs += 1
        written = words_of(d.text)
        one = own_words(d, written)
        of_word = {a: (c, part) for at, (c, part, _, _) in one.items() for a in at}
        opens = written[0][1] if written else -1
        for at, (c, part, mine, with_marked) in one.items():
            senses = senses_for(d, c)
            # A VERB'S PARTICLE IS MARKED as a word of the grammar and is part of the verb ("filled *out*").
            if len(with_marked) > len(mine) and spelled_so(senses, with_marked) and not spelled_so(senses, mine):
                mine = with_marked
            if len(mine) < 2:
                continue
            # A NAME OF SEVERAL WORDS IS ONE VALUE of the line, under `Name` or under `EQU` ("His name is
            # Tomoyuki Ogura.": `name.n.01 EQU "Tomoyuki Ogura"`).
            named = any(v.startswith('"') and " " in v.strip('"') for _, v in c.roles)
            shape = shape_of(part, mine, named)
            kind = "one word of the language" if named or spelled_so(senses, mine) else "words the span lumps"
            s = shapes[(shape, kind)]
            s["n"] += 1
            s[f"{len(mine)} words" if len(mine) < 4 else "4 words or more"] += 1
            if any("-" in w for w in mine):
                s["with a hyphen"] += 1
            for way, yes in ways_of(mine, at[0] == opens, names).items():
                s[f"{way}: caught"] += yes
            if len(examples[(shape, kind)]) < 10:
                examples[(shape, kind)].append((" ".join(mine), c.sense))
        # Every run of words the sentence says, against the concepts: what a way must not call one concept.
        for k in range(len(written)):
            for length in range(2, LONGEST + 1):
                if k + length > len(written):
                    break
                mine = [w for w, _, _ in written[k:k + length]]
                at = tuple(a for _, a, _ in written[k:k + length])
                got = one.get(at)
                is_one = got is not None and len(got[2]) == length
                r = runs[length]
                r["n"] += 1
                r["one concept"] += is_one
                for way, yes in ways_of(mine, k == 0, names).items():
                    r[f"{way}: said"] += yes
                    r[f"{way}: caught"] += yes and is_one
        # EVERY RUN OF CAPITALISED WORDS the sentence says, and what the gold makes of it and of its words.
        for k in range(len(written) - 1):
            if k and written[k - 1][0][:1].isupper():
                continue        # counted at the run's first word
            end = k
            while end + 1 < len(written) and written[end + 1][0][:1].isupper():
                end += 1
            if end == k or (k == 0 and written[k][0].lower() not in names):
                continue
            mine = [w for w, _, _ in written[k:end + 1]]
            at = tuple(a for _, a, _ in written[k:end + 1])
            got = one.get(at)
            if got is not None and len(got[2]) == len(mine):
                capitals["one concept of them all"] += 1
            else:
                each = [of_word.get(a) for a in at]
                named = [c is not None and any(v.startswith('"') for _, v in c[0].roles) for c in each]
                capitals["every word a name of its own" if all(named)
                          else "no word a name" if not any(named) else "a name and another kind of word"] += 1
            for a in at:
                here = of_word.get(a)
                if here is None:
                    in_runs["no concept says it"] += 1
                elif any(v.startswith('"') for _, v in here[0].roles):
                    in_runs["a name"] += 1
                else:
                    in_runs[{"n": "a thing", "v": "a doing", "a": "a quality", "s": "a quality",
                             "r": "an adverb"}.get(here[1], "otherwise")] += 1
        # A NAME RIGHT BEFORE A THING ("IKEA furniture", "Boeing headquarters"): one concept, or which link.
        by_start = {at[0]: (c, part, mine) for at, (c, part, mine, _) in one.items()}
        for k in range(len(written) - 1):
            w, a, b = written[k]
            nxt, a2, _ = written[k + 1]
            if not (w[:1].isupper() and nxt[:1].islower()) or (k == 0 and w.lower() not in names):
                continue
            here, there = by_start.get(a), by_start.get(a2)
            if here is None or there is None or here is there:
                before["one concept or no two things"] += 1
                continue
            if not any(r == "Name" for r, _ in here[0].roles) or there[1] != "n":
                continue
            # The link the second's line makes to the first (a role pointing back at it).
            k_here, k_there = d.concepts.index(here[0]), d.concepts.index(there[0])
            links = [LINKS.get(r, pm.HAPPENING_ROLES.get(r, r)) for r, v in there[0].roles
                     if pm._POINTER.match(v) and k_there + int(v) == k_here]
            links += [LINKS.get(r, pm.HAPPENING_ROLES.get(r, r)) for r, v in here[0].roles
                      if pm._POINTER.match(v) and k_here + int(v) == k_there]
            before[links[0] if links else "no link between them"] += 1
    print(f"{n_docs} documents ({split}); every concept of several words the gold makes, by shape:")
    for (shape, kind), s in sorted(shapes.items(), key=lambda x: (SHAPES.index(x[0][0]), -x[1]["n"])):
        print(f"  {shape}, {kind} {s['n']}  " + ", ".join(
            f"{k} {s[k]} ({s[k] / s['n']:.0%})" for k in ("2 words", "3 words", "4 words or more", "with a hyphen")
            if s[k]))
        for way in WAYS:
            print(f"      {way:32} catches {s[f'{way}: caught']:5} of {s['n']:5} "
                  f"({s[f'{way}: caught'] / s['n']:5.1%})")
    print("\nand every run of words the sentences say, of which each way must call one concept only those that are:")
    for length, r in sorted(runs.items()):
        print(f"  {length} words side by side {r['n']}  one concept {r['one concept']} "
              f"({r['one concept'] / r['n']:.1%})")
        for way in WAYS:
            said, caught = r[f"{way}: said"], r[f"{way}: caught"]
            print(f"      {way:32} calls {said:6} one, of them {caught:5} are"
                  + (f" ({caught / said:5.1%})" if said else ""))
    total = sum(capitals.values())
    print(f"\nwhat the gold makes of a run of capitalised words ({total}):")
    for which, n in capitals.most_common():
        print(f"  {which:40} {n:5} ({n / total:5.1%})")
    total = sum(in_runs.values())
    print(f"\nand of each word inside such a run ({total}):")
    for which, n in in_runs.most_common():
        print(f"  {which:40} {n:5} ({n / total:5.1%})")
    total = sum(before.values())
    print(f"\na name right before a thing, the link the gold makes ({total}):")
    for link, n in before.most_common():
        print(f"  {link:32} {n:5} ({n / total:5.1%})")
    print("\nwhat they look like:")
    for (shape, kind), got in sorted(examples.items(), key=lambda x: SHAPES.index(x[0][0])):
        print(f"  {shape}, {kind}: " + "; ".join(f"{w!r} {s}" for w, s in got[:8]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "train")
