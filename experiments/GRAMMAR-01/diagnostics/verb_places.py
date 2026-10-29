"""WHAT EACH PLACE OF A VERB SAYS, against the PMB's gold (2026-10-29, lab notebook (77)): each place of each verb of
the PMB's gold documents of a split (the role written on the verb's line, linked as the PMB's meanings link it,
`pmb_meanings.HAPPENING_ROLES`, a Theme alone who does it), named as the grammar names it (the thing before the verb its
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
marked on the verb's line, a `pp:`. A verb after a form of "be" or "get" is set apart as passive. From the Lyric folder:

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


def gold_link(role: str, doers: bool):
    return "done_by" if role == "Theme" and not doers else pm.HAPPENING_ROLES.get(role)


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


def main(split: str) -> None:
    ids = pm.split_ids(pmb / "split" / "en" / split / ("gold.sbn" if split == "train" else "standard.sbn"))
    stats = collections.defaultdict(collections.Counter)
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
            doers = any(r in pm.DOERS for r, _ in c.roles)
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
            senses = [x for x in wn.synsets(lemma, "v") if any(l.name().lower() == lemma for l in x.lemmas())]
            most_used = max(senses, key=lambda x: sum(l.count() for l in x.lemmas() if l.name().lower() == lemma)
                            ).name() if senses else c.sense
            for slot, role in placed:
                gold = gold_link(role, doers)
                if gold is None:
                    continue
                a = now(lemma, slot)
                by_sense, every = frames(lemma, c.sense)
                b = framed(by_sense, slots, slot, a)
                w = framed(every, slots, slot, a)
                mu = framed(frames(lemma, most_used)[0], slots, slot, a)
                s = stats[("passive:" if passive else "") + ("pp" if slot.startswith("pp:") else slot)]
                s["n"] += 1
                s["now"] += a == gold
                s["sense"] += (b if b is not None else a) == gold
                s["sense, word"] += (b if b is not None else w if w is not None else a) == gold
                s["most used sense"] += (mu if mu is not None else a) == gold
    print(f"{n_docs} documents ({split}); each verb place linked as the PMB links it, by:")
    for kind, s in sorted(stats.items(), key=lambda x: -x[1]["n"]):
        n = s["n"]
        print(f"  {kind:16} {n:5}  " + "  ".join(f"{way} {s[way] / n:6.1%}" for way in
                                                 ("now", "sense", "sense, word", "most used sense")))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "train")
