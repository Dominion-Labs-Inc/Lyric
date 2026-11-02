"""WHAT EACH PLACE OF A VERB SAYS, against the PMB's gold (2026-10-29, lab notebook (77)): each place of each verb of
the PMB's gold documents of a split (the role written on the verb's line, linked as the PMB's meanings link it,
`pmb_meanings.happening_link`, a Theme alone who does it), named as the grammar names it (the thing before the verb its
subject; after it, one thing its object, two the `second` and the object; one after a preposition `pp:` it), and the
link each way gives it:

- now: what word records gave before (`WordRecord.links`, PropBank's function tags summed over the word's senses, the
  grammar's own link counted once beside them);
- by the frames of the sense (`teaching_sources._frame_places`, VerbNet's frames of the classes VerbNet lists the
  gold sense in, or the classes listing the word alone where none names any sense of it), the frame giving the most of
  the places said, the fewest besides (`Lexicon.framed`), else now; the same with WordNet's most used sense of the
  word in place of the gold one (the sense reading might choose); and by the word's frames where the sense's say
  nothing.

The place is found from the text: the argument's words before the verb's, its subject; a preposition between, or
marked on the verb's line, a `pp:`. A verb after a form of "be" or "get" is set apart as passive, and its places are
counted a second way (`as the active`), each named as the active says it: its subject the verb's object, its "by" the
subject. From the Lyric folder:

    ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/verb_places.py train
"""
import collections, os, re, sys, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(os.getcwd())
sys.path.insert(0, str(ROOT))
from nltk.corpus import LazyCorpusLoader, wordnet as wn
from nltk.corpus.reader import VerbnetCorpusReader
from core.learning import teaching_sources as ts
from core.semantics import pmb_meanings as pm

vn = LazyCorpusLoader("verbnet3", VerbnetCorpusReader, r"(?!\.).*\.xml")
pmb = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
PREPS = ts._PREPOSITIONS_WRITTEN
LINKING = {"subject": "done_by", "object": "done_to", "second": "received_by"}
BE = {"was", "were", "is", "are", "be", "been", "being", "am", "'s", "get", "got", "gets", "getting"}
WORD = re.compile(r"[A-Za-z']+")


def gold_link(role: str, roles):
    return pm.happening_link(role, roles)


_propbank: dict = {}


def now(lemma: str, slot: str):
    """What word records gave: each PropBank place's slot (`_PLACE_LINKS`), counted over the word's senses."""
    if lemma not in _propbank:
        counts = collections.Counter()
        f = Path(ts.SYNTAX_DATA) / "propbank-frames" / "frames" / f"{lemma.split('_')[0]}.xml"
        try:
            rolesets = list(ET.parse(f).iter("roleset")) if f.exists() else []
        except ET.ParseError:
            rolesets = []       # check.xml and rend.xml are not well formed (propbank-frames c66e0cc)
        for rs in rolesets:
            if not str(rs.get("id", "")).startswith(lemma + "."):
                continue
            said: dict = {}
            for ex in rs.iter("example"):
                for arg in ex.iter("arg"):
                    said.setdefault(str(arg.get("type") or ""), []).append(
                        (arg.text or "").strip().split(" ")[0].lower())
            for role in rs.iter("role"):
                arg, fn = "ARG" + str(role.get("n")).upper(), str(role.get("f") or "").upper()
                firsts = said.get(arg, [])
                if any(x and x not in PREPS for x in firsts) and (fn, "") in ts._PLACE_LINKS and arg in ("ARG0", "ARG1"):
                    counts[ts._PLACE_LINKS[(fn, "")]] += 1
                for p in sorted({x for x in firsts if x in PREPS}):
                    if (fn, p) in ts._PLACE_LINKS:
                        counts[ts._PLACE_LINKS[(fn, p)]] += 1
        _propbank[lemma] = counts
    held = collections.Counter({link: n for (s, link), n in _propbank[lemma].items() if s == slot})
    default = LINKING.get(slot)
    if default:
        held[default] += 1
    if not held:
        return None
    top = max(held.values())
    return default if held[default] == top else max(held, key=held.get)


_frames: dict = {}


def frames(lemma: str, sense: str):
    """The places of each frame of the classes VerbNet lists the sense in (or, where it names no sense of the word,
    the classes listing the word), and of every class of the word."""
    if (lemma, sense) not in _frames:
        try:
            cids = vn.classids(lemma)
        except Exception:
            cids = []
        try:
            keys = {l.key().split("::")[0] for l in wn.synset(sense).lemmas() if l.name().lower() == lemma}
        except Exception:
            keys = set()
        by_sense, keyless, every, named_any = [], [], [], False
        for cid in cids:
            mkeys = {k.lstrip("?") for m in vn.vnclass(cid).iter("MEMBER") if m.get("name") == lemma
                     for k in (m.get("wn") or "").split()}
            named_any |= bool(mkeys)
            said, up = [], cid
            while up:
                try:
                    got = vn.vnclass(up).find("FRAMES")
                except Exception:
                    break
                said += [dict(p) for p in (ts._frame_places(f) for f in got.findall("FRAME")) if p]
                parent = up.rsplit("-", 1)[0]
                up = parent if parent != up and re.search(r"-\d", parent) else ""
            every += said
            if keys & mkeys:
                by_sense += said
            elif not mkeys:
                keyless += said
        _frames[(lemma, sense)] = (by_sense or (keyless if not named_any else []), every)
    return _frames[(lemma, sense)]


def framed(said: list, slots: list, slot: str, default):
    """As `Lexicon.framed`."""
    if not said:
        return None
    fits = [(sum(s in f or (s.startswith("pp:") and "pp:*" in f) for s in slots), -abs(len(f) - len(slots)))
            for f in said]
    best = max(fits)
    votes = collections.Counter()
    for f, fit in zip(said, fits):
        link = f.get(slot) or (f.get("pp:*") if slot.startswith("pp:") else None)
        if fit == best and link:
            votes[link] += 1
    if not votes:
        return None
    top = max(votes.values())
    tied = sorted(link for link, n in votes.items() if n == top)
    return default if default in tied else tied[0]


def _counted(said: list):
    """The frames as the lexicon holds them: the places of each -> how many frames say just those."""
    return collections.Counter(tuple(sorted(f.items())) for f in said)


def _chosen(frames, slots: list):
    """THE ONE FRAME THAT ANSWERS FOR THE HAPPENING: of the frames given, the one giving the most of the places said,
    the fewest besides, then the one most of them are, then by its places (so one sentence is read one way)."""
    fits = {}
    for f in frames:
        d = dict(f)
        fits[f] = (sum(s in d or (s.startswith("pp:") and "pp:*" in d) for s in slots), -abs(len(d) - len(slots)))
    best = max(fits.values())
    return min((f for f in frames if fits[f] == best), key=lambda f: (-frames[f], f))


def one_frame(by_sense: list, every: list, slots: list, slot: str, default, loose: bool = False):
    """ONE FRAME ANSWERS FOR ONE HAPPENING: every place read from the one frame chosen for the places said, and a
    preposition that frame does not name answered by another of the word's frames only where it AGREES with the
    chosen one everywhere both name a place (`loose`: and may answer with a prepositional place of its own whose
    preposition it does not name)."""
    frames = _counted(by_sense or every)
    if not frames:
        return None
    chosen = dict(_chosen(frames, slots))
    link = chosen.get(slot) or (chosen.get("pp:*") if slot.startswith("pp:") else None)
    if link:
        return link
    if not slot.startswith("pp:"):
        return None
    votes = collections.Counter()
    for other, n in _counted(every).items():
        d = dict(other)
        if any(d[s] != chosen[s] for s in set(d) & set(chosen)):
            continue
        got = d.get(slot) or (d.get("pp:*") if loose else None)
        if got:
            votes[got] += n
    if not votes:
        return None
    top = max(votes.values())
    tied = sorted(l for l, n in votes.items() if n == top)
    return default if default in tied else tied[0]


def _vote(frames, fits, best, slot: str, decided: dict, default, wild: bool):
    """The link the frames of the best fit give a place, as `framed` votes, counting only a frame that AGREES with
    the links already given (`decided`) everywhere both name a place."""
    votes = collections.Counter()
    for fr, n in frames.items():
        d = dict(fr)
        if fits[fr] != best or any(d[x] != decided[x] for x in set(d) & set(decided)):
            continue
        link = d.get(slot) or (d.get("pp:*") if wild and slot.startswith("pp:") else None)
        if link:
            votes[link] += n
    if not votes:
        return None
    top = max(votes.values())
    tied = sorted(l for l, n in votes.items() if n == top)
    return default if default in tied else tied[0]


def places_agreeing(by_sense: list, every: list, slots: list, defaults: dict, loose: bool = False):
    """EVERY PLACE OF A HAPPENING READ AS ONE ANALYSIS: each place linked as the frames of the best fit vote
    (`framed`), except that a frame speaks of a place only where it agrees with the links already given -- the
    subject first, then the object, the thing before it, and the places after a preposition, the places read most
    surely deciding the analysis the rest are read under. A preposition the sense's frames do not name is answered
    by the word's, again only by a frame agreeing with what is given (`loose`: and by a prepositional place whose
    preposition such a frame does not name)."""
    sense_frames, word_frames = _counted(by_sense), _counted(every)
    pool = sense_frames or word_frames
    if not pool:
        return {}

    def fitted(frames):
        f = {}
        for fr in frames:
            d = dict(fr)
            f[fr] = (sum(x in d or (x.startswith("pp:") and "pp:*" in d) for x in slots), -abs(len(d) - len(slots)))
        return f, max(f.values())
    fit_pool, best_pool = fitted(pool)
    fit_word, best_word = fitted(word_frames) if word_frames else ({}, None)
    decided: dict = {}
    order = [x for x in ("subject", "object", "second") if x in slots] + [x for x in slots if x.startswith("pp:")]
    for slot in order:
        if slot in decided:
            continue
        got = _vote(pool, fit_pool, best_pool, slot, decided, defaults.get(slot), True)
        if got is None and slot.startswith("pp:") and sense_frames and word_frames:
            got = _vote(word_frames, fit_word, best_word, slot, decided, defaults.get(slot), loose)
        if got:
            decided[slot] = got
    return decided


def main(split: str) -> None:
    ids = pm.split_ids(pmb / "split" / "en" / split / ("gold.sbn" if split == "train" else "standard.sbn"))
    stats = collections.defaultdict(collections.Counter)
    given = collections.defaultdict(collections.Counter)      # (place, the link the frames give) -> n, right
    n_docs = 0
    for doc_id in ids:
        d = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        if d is None:
            continue
        n_docs += 1
        cs = d.concepts
        for k, c in enumerate(cs):
            m = pm._SENSE.match(c.sense)
            if not m or m.group("part") != "v" or m.group("lemma") in ("be", "have") or c.span is None:
                continue
            lemma = m.group("lemma")
            vs, ve = c.span
            before = WORD.findall(d.text[:vs].lower())[-2:]
            verb_word = (d.text[vs:ve].split() or [""])[0].lower()
            passive = bool(before) and (before[-1] in BE or (len(before) > 1 and before[-2] in BE
                                                            and before[-1].endswith("ly"))) \
                and verb_word != lemma.split("_")[0] and not verb_word.endswith("ing")
            args = []
            for role, value in c.roles:
                if role not in pm.HAPPENING_ROLES or not pm._POINTER.match(value):
                    continue
                j = k + int(value)
                if not 0 <= j < len(cs) or cs[j].span is None:
                    continue
                om = pm._SENSE.match(cs[j].sense)
                if om and om.group("part") in ("a", "s", "r", "v"):
                    continue
                args.append((role, cs[j]))
            if not args:
                continue
            roles_said = [r for r, _ in c.roles]
            marked = [w.lower().strip(".,?!") for w in c.marked if w.lower().strip(".,?!") in PREPS]
            after = sorted([a for a in args if a[1].span[0] >= ve], key=lambda a: a[1].span[0])
            bare = [a for a in after if not any(w in PREPS for w in WORD.findall(d.text[ve:a[1].span[0]].lower()))
                    and (WORD.findall(a[1].words) or [""])[0].lower() not in PREPS]
            placed = []
            for role, o in args:
                if o.span[1] <= vs:
                    slot = "subject"
                else:
                    gap = [w.lower() for w in WORD.findall(d.text[ve:o.span[0]])]
                    first = (WORD.findall(o.words) or [""])[0].lower()
                    p = next((w for w in reversed(gap) if w in PREPS), None) or (first if first in PREPS else None)
                    if p is None and marked and after and after[0][1] is o:
                        p = marked[-1]
                    slot = f"pp:{p}" if p else ("object" if len(bare) < 2 or bare[-1][1] is o else "second")
                placed.append((slot, role))
            slots = [s for s, _ in placed]
            # A PASSIVE SAYS THE SAME PLACES AS THE ACTIVE, differently placed: its subject is the verb's object (its
            # `second` where another thing is said after it, as the grammar's entry takes them: "He was given a
            # book."), its "by" the subject. Counted as a second way of reading a passive's places.
            active = {"subject": "second" if bare else "object", "pp:by": "subject"}
            as_active = [active.get(x, x) for x in slots] if passive else slots
            senses = [x for x in wn.synsets(lemma, "v") if any(l.name().lower() == lemma for l in x.lemmas())]
            most_used = max(senses, key=lambda x: sum(l.count() for l in x.lemmas() if l.name().lower() == lemma)
                            ).name() if senses else c.sense
            defaults = {x: now(lemma, x) for x in set(slots) | set(as_active)}
            agreed = places_agreeing(*frames(lemma, c.sense), slots, defaults)
            agreed_loose = places_agreeing(*frames(lemma, c.sense), slots, defaults, loose=True)
            for slot, role in placed:
                gold = gold_link(role, roles_said)
                if gold is None:
                    continue
                a = now(lemma, slot)
                by_sense, every = frames(lemma, c.sense)
                b = framed(by_sense, slots, slot, a)
                w = framed(every, slots, slot, a)
                mu = framed(frames(lemma, most_used)[0], slots, slot, a)
                s = stats[("passive:" if passive else "") + ("pp" if slot.startswith("pp:") else slot)]
                s["n"] += 1
                s[f"gold:{gold}"] += 1
                s["now"] += a == gold
                s["sense"] += (b if b is not None else a) == gold
                s["sense, word"] += (b if b is not None else w if w is not None else a) == gold
                s["most used sense"] += (mu if mu is not None else a) == gold
                o = one_frame(by_sense, every, slots, slot, a)
                ol = one_frame(by_sense, every, slots, slot, a, loose=True)
                s["one frame"] += (o if o is not None else a) == gold
                s["one frame, pp:*"] += (ol if ol is not None else a) == gold
                s["agreeing"] += (agreed.get(slot) or a) == gold
                s["agreeing, pp:*"] += (agreed_loose.get(slot) or a) == gold
                place = ("passive:" if passive else "") + ("pp" if slot.startswith("pp:") else slot)
                if slot in ("object", "second"):
                    place += ", a place after a preposition said" if any(x.startswith("pp:") for x in slots) \
                        else ", no place after a preposition"
                g = given[(place, agreed.get(slot) or f"none ({a})")]
                g["n"] += 1
                g["right"] += (agreed.get(slot) or a) == gold
                g[f"gold:{gold}"] += 1
                if passive and slot == "subject":
                    # LYRIC'S OWN CONVENTION, read of the sentence: what the happening is done to where a doer is
                    # said with it ("I was stung by a bee."), who does it where none is ("The phone rang.",
                    # "The treaty will be signed tomorrow."), as `pmb_meanings.happening_link` says a role.
                    s["a doer said"] += ("done_to" if "pp:by" in slots else "done_by") == gold
                if not passive or slot not in active:
                    continue
                here = active[slot]
                a2 = now(lemma, here)
                b2 = framed(by_sense, as_active, here, a2)
                w2 = framed(every, as_active, here, a2)
                mu2 = framed(frames(lemma, most_used)[0], as_active, here, a2)
                s = stats[f"as the active: {slot if not slot.startswith('pp:') else 'pp'}"]
                s["n"] += 1
                s["now"] += a2 == gold
                s["sense"] += (b2 if b2 is not None else a2) == gold
                s["sense, word"] += (b2 if b2 is not None else w2 if w2 is not None else a2) == gold
                s["most used sense"] += (mu2 if mu2 is not None else a2) == gold
                o2 = one_frame(by_sense, every, as_active, here, a2)
                ol2 = one_frame(by_sense, every, as_active, here, a2, loose=True)
                s["one frame"] += (o2 if o2 is not None else a2) == gold
                s["one frame, pp:*"] += (ol2 if ol2 is not None else a2) == gold
                active_agreed = places_agreeing(*frames(lemma, c.sense), as_active, defaults)
                active_loose = places_agreeing(*frames(lemma, c.sense), as_active, defaults, loose=True)
                s["agreeing"] += (active_agreed.get(here) or a2) == gold
                s["agreeing, pp:*"] += (active_loose.get(here) or a2) == gold
    print(f"{n_docs} documents ({split}); each verb place, what the PMB links it as, and how often each way says so:")
    for kind, s in sorted(stats.items(), key=lambda x: -x[1]["n"]):
        n = s["n"]
        said = sorted(((k[5:], m) for k, m in s.items() if k.startswith("gold:")), key=lambda x: -x[1])
        print(f"  {kind:24} {n:5}  gold: " + ", ".join(f"{link} {m / n:.0%}" for link, m in said[:3]))
        print(" " * 33 + "  ".join(f"{way} {s[way] / n:6.1%}" for way in
                                   ("now", "sense", "sense, word", "one frame", "one frame, pp:*",
                                    "agreeing", "agreeing, pp:*", "most used sense",
                                    "a doer said") if way in s))


    print("\nwhat the frames give each place, read as one analysis (`agreeing`), and how often that is the gold:")
    for (place, link), g in sorted(given.items(), key=lambda x: (x[0][0], -x[1]["n"])):
        if g["n"] < 10:
            continue
        said = sorted(((k[5:], m) for k, m in g.items() if k.startswith("gold:")), key=lambda x: -x[1])
        print(f"  {place:16} {link:14} {g['n']:5}  right {g['right'] / g['n']:6.1%}   gold: "
              + ", ".join(f"{l} {m / g['n']:.0%}" for l, m in said[:3]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "train")
