"""GRAMMAR-01: what a sentence means, read by English's grammar (`core/semantics/grammar.py`), measured where PMB-01
measured the composer.

The composer (`core/semantics/composition.py`) decided what each word stands for and what near words hold together
from the taught sentences most like the sentence read; where none was much like it (most links between words), a
coarser situation decided, wrong 9% to 75% of the time (2026-10-20). Here each word is read by its category in a
categorial grammar and the meaning built by the grammar's rules; what is learned from the taught sentences is only
what words themselves hold: the link each of a verb's places makes, what each preposition, possessive and adverb
says, what "is a" says. Same measure as PMB-01: the PMB's dev split, held out, each sentence split as Lyric splits a
sentence, compared with its meaning three ways (strict; senses aside, each kind and name a word says named as the
grammar names that word; and the one spoken of before taken as unnamed). Each whole meaning right; facts precision,
recall and F1; how many sentences the grammar read whole, and how many it gave a meaning; and of the links decided,
how many by the word's own uses, by what memory holds it a kind of, and by the grammar's rule, each with how often
right.

Learned, as memory learns (`grammar.GrammarView`), from the lessons and the PMB's gold training sentences
(`teaching_sources.PMBSource`), each aligned to its words by its source's lines or its names. Words as main holds them
(`grammar_words.HeldWords`), from UD English EWT's training part and WordNet's taught links (`words.file_words`).

Run (from the Lyric folder; a few minutes, or longer with `--with-words`):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/experiment.py [--data DIR] [--pmb DIR]
        [--with-words [--fresh-words]] [--without-structure] [--gold-categories]
`--with-words` records every word the sentences use whole, as main holds it (`teaching_sources.word_record_of`):
without them the grammar has no sense of any word apart and no PropBank places for any verb, so every word is read
under the sense it names most often and every place of a doing takes the grammar's own link. Main holds such records,
so a run without them is below what main does.
`--gold-categories` fixes each word's category to the one the PMB's own checked gold derivation gives it (release
4.0.0's `en.parse.tags`) and reads everything else as usual, so what is measured is what the grammar's RULES and what
words hold cost, APART FROM CHOOSING THE CATEGORY -- which is where most of its words go wrong (85.5% take the
derivation's category or one saying the same, `diagnostics/categories.py`). This is the same test Boxer is held to
with the gold `cat` layer, which it scores above 0.99 on, there because the gold was made by Boxer from those very
derivations; here the rules are an independent reimplementation and the target is Lyric's own meaning language, so
the number is unknown and is what says whether the grammar's rules or its choosing is the thing to work on.
The Parallel Meaning Bank: University of Groningen, annotations ODC-BY 1.0 (Abzianidze et al. 2017).
"""
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))


def say(*a):
    print(*a, flush=True)


def argument(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


def grounded(meaning, is_variable):
    """A meaning's facts with each variable put as what it is an instance of (or `?`): comparable across meanings."""
    kind = {}
    for f in meaning.facts:
        if f.relation == "instance_of" and is_variable(f.subject) and not is_variable(f.obj):
            kind.setdefault(f.subject, f.obj)
    out = Counter()
    for f in meaning.facts:
        if f.relation == "instance_of" and is_variable(f.subject):
            out[("instance_of", f.obj, f.positive)] += 1
            continue
        s = kind.get(f.subject, "?") if is_variable(f.subject) else f.subject
        o = kind.get(f.obj, "?") if is_variable(f.obj) else f.obj
        out[(f.relation, s, o, f.positive)] += 1
    return out


#: A word of a PMB 4.0.0 gold derivation: `t(Category, 'word', [from:, to:, pos:, ...])`.
LEAF = re.compile(r"t\(([^,]+?), '((?:[^'\\]|\\.)*)', \[from:(\d+), to:(\d+), pos:'([^']*)'")


def pmb_tree(text):
    """A meaning-bank category as a tree: atoms like s:dcl, np; slashes left-associative."""
    toks = re.findall(r"\(|\)|/|\\|[a-z]+(?::[a-z]+)?", text)
    at = [0]

    def primary():
        if toks[at[0]] == "(":
            at[0] += 1
            c = expr()
            at[0] += 1
            return c
        s = toks[at[0]]
        at[0] += 1
        return ("atom",) + tuple(s.split(":")) if ":" in s else ("atom", s, None)

    def expr():
        c = primary()
        while at[0] < len(toks) and toks[at[0]] in ("/", "\\"):
            s = toks[at[0]]
            at[0] += 1
            c = ("fn", c, s, primary())
        return c
    return expr()


def canon_pmb(t, feats):
    if t[0] == "atom":
        return t[1] + (":" + t[2] if feats and t[2] else "")
    return "(" + canon_pmb(t[1], feats) + t[2] + canon_pmb(t[3], feats) + ")"


def canon_lyric(c, feats):
    from core.semantics.grammar import Atom
    if isinstance(c, Atom):
        f = c.feat
        return c.base.lower() + (":" + f if feats and isinstance(f, str) and f.islower() else "")
    return "(" + canon_lyric(c.res, feats) + c.slash + canon_lyric(c.arg, feats) + ")"


def strip(s):
    return s[1:-1] if s.startswith("(") and s.endswith(")") else s


def offsets(text, tokens):
    """Each token's characters in the text, or None: how a gold derivation's words are matched to the grammar's."""
    out, at = [], 0
    for t in tokens:
        w = str(t)
        k = text.find(w, at)
        if k < 0:
            k = text.lower().find(w.lower(), at)
        if k < 0:
            out.append(None)
            continue
        out.append((k, k + len(w)))
        at = k + len(w)
    return out


def gold_categories(tags_file, text, tokens):
    """EACH TOKEN'S CATEGORY AS THE PMB'S CHECKED GOLD DERIVATION GIVES IT (release 4.0.0's `en.parse.tags`), named
    as the grammar names a category and without features: token index -> category. Marks aside. Nothing where the
    derivation's word is not one of the grammar's tokens (a word of several, a different split)."""
    out = {}
    if not tags_file.exists():
        return out
    by_span = {sp: i for i, sp in enumerate(offsets(text, tokens)) if sp}
    for c, w, a, b, _pos in LEAF.findall(tags_file.read_text(encoding="utf-8")):
        c = c.strip()
        if c in ("punct", "comma") or not any(ch.isalnum() for ch in w):
            continue
        i = by_span.get((int(a), int(b)))
        if i is not None:
            out[i] = strip(canon_pmb(pmb_tree(c), False))
    return out


def reaches(grammar, tokens, i, end, entry):
    """Every category a word read as this entry may stand as: its own, and each one the grammar's own rules make of
    it over the same words (`Grammar._unary`: a kind said bare is a thing, a doing is a thing). A gold derivation
    names the category the word STANDS AS, which is often one of these and not the entry's own."""
    try:
        sign = grammar._lexical(tokens, i, end, entry)
    except (ValueError, IndexError):
        return {strip(canon_lyric(entry.cat, False))}
    out, todo, seen = set(), [sign], set()
    while todo:
        x = todo.pop()
        k = strip(canon_lyric(x.cat, False))
        if k in seen:
            continue
        seen.add(k)
        out.add(k)
        todo.extend(u for u in grammar._unary(x) if u.start == x.start and u.end == x.end)
    return out


def senses_aside(meaning, at, names):
    """The meaning with each kind and name a word says named as the grammar names that word, as PMB-01 names them
    for the composer: a variable's kind by the word saying the kind, or where no word of its own says it (the PMB
    puts "a truck driver." on a line of its own and the kind on one with no words), the word saying the variable; a
    name or constant by the word saying it."""
    from core.semantics.derived_reader import Meaning, MeaningFact, is_variable
    first = {t: next((w for w in ws if w in names), None) for t, ws in at.items()}
    facts = []
    for f in meaning.facts:
        subject, obj = f.subject, f.obj
        if f.relation in ("instance_of",) and is_variable(subject):
            w = first.get(obj) if first.get(obj) is not None else first.get(subject)
            obj = names[w] if w is not None else obj
        else:
            if not is_variable(obj) and not obj.replace(".", "").isdigit() and first.get(obj) is not None:
                obj = names[first[obj]]
            if not is_variable(subject) and not subject.replace(".", "").isdigit() and first.get(subject) is not None:
                subject = names[first[subject]]
        facts.append(MeaningFact(f.relation, subject, obj, f.positive, f.condition, f.alternative, f.unasserted,
                                 f.given))
    try:
        return Meaning(meaning.act, tuple(dict.fromkeys(facts)), meaning.asked)
    except ValueError:
        return meaning


def pronouns_as_unknowns(meaning):
    """The meaning with the one spoken of before (`?previous`, what Lyric reads "he", "she", "this" as) an unknown,
    as the PMB writes a pronoun: a thing its sentence does not say what it is. Compared as written, "He fixed it."
    read `done_by(?v0, ?previous)` was wrong against `done_by(?v0, ?v1)`, the most common difference between what
    main read and the PMB's gold (175 of 525, 2026-10-28)."""
    from core.semantics.derived_reader import Meaning, MeaningFact
    if not any("?previous" in (f.subject, f.obj) for f in meaning.facts):
        return meaning
    taken = {t for f in meaning.facts for t in (f.subject, f.obj)}
    unknown = next(f"?v{k}" for k in range(len(taken) + 1, 10 * len(taken) + 100) if f"?v{k}" not in taken)

    def of(t):
        return unknown if t == "?previous" else t
    return Meaning(meaning.act, tuple(MeaningFact(f.relation, of(f.subject), of(f.obj), f.positive, f.condition,
                                                  f.alternative, f.unasserted, f.given) for f in meaning.facts),
                   tuple(of(a) for a in meaning.asked))


def named_by_their_words(meaning, words, senses_named):
    """The meaning with each thing it names by a sense (a kind, a quality) named by the word of the sentence it is a
    sense of (`words`: the sentence's words and each one's bases; `senses_named`: Lyric's name -> the WordNet senses
    it names): `misinform lie` and `lie` both "lie" in "You lied to me!", `foodstuff egg` and `egg` "egg". Which sense
    of the word is meant is set aside, in the gold and the reading alike; a name no word of the sentence is a sense
    of is kept. `senses_aside` names a word by its first sense instead, and counted a sense chosen from what fills
    a verb's places wrong where the word was read right (2026-10-28)."""
    from core.semantics.derived_reader import Meaning, MeaningFact, is_variable

    # A TIME OF THE CLOCK BY ITS WORDS: its half of the day only where the sentence says it ("7:15 a.m."); "at six"
    # is 6:00, the PMB's 18:00 its annotators' (2026-10-29).
    halved = any(w.rstrip(".") in ("a.m", "p.m", "am", "pm") for w in words)

    def of(t):
        if not halved and re.fullmatch(r"\d{1,2}:\d{2} [ap]\.m\.", t):
            return t.split()[0]
        if is_variable(t) or t.replace(".", "").isdigit():
            return t
        said = sorted({lemma.name().lower().replace("_", " ") for synset in senses_named.get(t, ())
                       for lemma in synset.lemmas()} & words)
        return said[0] if said else t
    try:
        return Meaning(meaning.act, tuple(dict.fromkeys(
            MeaningFact(f.relation, of(f.subject), of(f.obj), f.positive, f.condition, f.alternative, f.unasserted,
                        f.given)
            for f in meaning.facts)), meaning.asked)
    except ValueError:
        return meaning


def words_of_sentence(tokens):
    """A sentence's words as `named_by_their_words` asks for them: each word lowered, each of its bases as WordNet
    gives them, every two and three words side by side ("disco music") and the word each such run is a form of
    ("took off" `take off`, "dairy products" `dairy product`, "fell in love" `fall in love`), and words joined by
    hyphens as one word in each of its spellings ("bullet-proof", `bulletproof`, "bullet proof":
    `Lexicon.hyphened`). A word of several words is a word of the sentence as a word of one is: named by its words
    only as written, a thing the gold says by one ("took off" `take_off.v.06`) could be named by no word of the
    sentence, and the reading was scored wrong for naming another sense of the same words (2026-10-29)."""
    from nltk.corpus import wordnet as wn
    low = [str(t).lower() for t in tokens]
    out = set(low)
    for i in range(len(low)):
        end = i + 1
        while end + 1 < len(low) and low[end] == "-" and low[end - 1].isalnum() and low[end + 1].isalnum():
            end += 2
        if end > i + 1:
            parts = low[i:end:2]
            out.update(("-".join(parts), "".join(parts), " ".join(parts)))
    for w in list(out):
        for pos in ("n", "v", "a", "r"):
            base = wn.morphy(w, pos)
            if base:
                out.add(base.replace("_", " "))
    for n in (2, 3):
        for k in range(len(low) - n + 1):
            said = low[k:k + n]
            out.add(" ".join(said))
            for pos in ("v", "n", "a"):
                base = wn.morphy(said[0], pos)
                if base and base != said[0]:
                    out.add(" ".join([base] + said[1:]))
                base = wn.morphy(said[-1], pos)
                if base and base != said[-1]:
                    out.add(" ".join(said[:-1] + [base]))
    return out


def main() -> int:
    from experiments._evidence import RunRecord
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import PMBSource, WordNetSource
    from core.semantics import grammar as gm
    from core.semantics import pmb_meanings as pm
    from core.semantics.derived_reader import Meaning, MeaningFact, is_variable
    from words import file_structure, file_words
    data = Path(argument("--data") or ROOT / "test_data" / "syntax")
    pmb = Path(argument("--pmb") or ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0")
    EV = RunRecord("GRAMMAR-01",
                   claim="what a sentence means is read by English's grammar: each word's category and meaning, "
                         "combined by general rules, what words hold learned from sentences taught with meanings",
                   hypothesis="more of the PMB's held-out dev meanings are read right whole than the composer "
                              "composed (PMB-01 20261020T210127Z, learned from the lessons and the PMB's gold "
                              "training sentences: 33.6% senses aside, 16.1% strict, 40.6% with the one spoken of "
                              "before unnamed)")
    started = time.perf_counter()
    EV.check("the PMB is on disk", (pmb / "split" / "en" / "dev" / "standard.sbn").exists(), str(pmb))
    words = file_words(data / "UD_English-EWT" / "en_ewt-ud-train.conllu", gm.closed_uses())
    # The structure view decides which word takes which where the words' readings do not (`Grammar._joined`);
    # `--without-structure` reads as before it did.
    view = gm.GrammarView(words, structure=None if "--without-structure" in sys.argv else
                          file_structure(data / "UD_English-EWT" / "en_ewt-ud-train.conllu"))
    grammar = view.grammar
    say(f"words ready ({words.sentences:,} analysed sentences), {time.perf_counter() - started:.0f}s")

    # ── what each word takes beside the words around it, from the PMB's sentences derived by hand (4.0.0 gold, 5.1.0's
    # dev and test held out), as memory holds them: held before the taught sentences are learned from ──
    from core.learning.teaching_sources import PMBDerivationSource
    derived = list(PMBDerivationSource().derived())
    for item in derived:
        view.hold_derived(item)
    EV.metric("sentences derived by hand held", len(derived), unit="sentences",
              note="PMB 4.0.0 gold, release 5.1.0's dev and test documents held out")
    say(f"held {len(derived):,} sentences derived by hand, {time.perf_counter() - started:.0f}s")

    def tokens_of(sentence):
        return gm.tokens_of(sentence, words)

    # ── learned from the lessons, then the PMB's gold training sentences, as memory holds them ──
    from core.learning.teaching_sources import ListeningSource
    from core.semantics.composition import TaughtSentence
    lessons = [TaughtSentence(sentence, meaning, "lessons") for sentence, meaning in ListeningSource(tuple(
        str(p) for p in sorted((ROOT / "data" / "lessons").glob("english_[0-9][0-9].json")))).listening_pairs()]
    gold = list(PMBSource.of("gold", str(pmb)).taught_sentences())
    for taught in lessons + gold:
        view.hold(taught)
    view.learn_waiting()
    say(f"learned from {view.learned_from:,} taught sentences ({len(lessons):,} lessons, {len(gold):,} PMB gold), "
        f"{view.read_whole:,} read whole, {time.perf_counter() - started:.0f}s")
    EV.metric("taught sentences read whole (learned from)", view.read_whole, unit="sentences",
              note=f"of {view.learned_from:,}: {len(lessons):,} lessons, {len(gold):,} PMB gold training")

    # ── measured on the dev split ──
    sense_names = WordNetSource()._sense_names()

    def sense_name(sense):
        try:
            return sense_names.get(wn.synset(sense)) or None
        except Exception:
            return None
    dev = []
    #: With `--gold-categories`, each dev sentence's gold category per token (`gold_categories`).
    gold_of = []
    p4 = ROOT / "test_data" / "semantics" / "pmb" / "pmb-4.0.0" / "data" / "en" / "gold"
    listed = pm.split_ids(pmb / "split" / "en" / "dev" / "standard.sbn")
    for doc_id in listed:
        document = pm.read_document(pmb / "data" / "en" / "gold" / doc_id)
        said = pm.meaning_of(document, sense_name) if document is not None else None
        if said is None or said.meaning is None:
            continue
        tokens = tokens_of(document.text)
        anchors = tuple((t, tuple((document.concepts[k].span[0], document.concepts[k].span[1], how,
                                   document.concepts[k].marked) for k, how in at if document.concepts[k].span))
                        for t, at in said.anchors.items())
        dev.append((document.text, tokens, said.meaning, gm.align_by_anchors(tokens, document.text, anchors)))
        gold_of.append(gold_categories(p4 / doc_id / "en.parse.tags", document.text, tokens)
                       if "--gold-categories" in sys.argv else {})
    EV.metric("PMB dev sentences said whole", len(dev), unit="sentences", note=f"of {len(listed):,} listed")
    say(f"PMB dev said whole {len(dev):,} of {len(listed):,}")

    # ── EACH WORD RECORDED WHOLE, as main holds it (`--with-words`) ──
    # Without them the grammar has no sense of any word apart (`Lexicon.thing_used`, `sense_used`, `sense_seen`) and
    # no PropBank places for any verb (`frames_said`), so every thing and every doing is read under the sense its
    # word names most often and every place of a doing takes the grammar's own link. Two of the largest kinds of
    # miss in run 20261028T111052Z are exactly that: the fine-grained sense (20.6 points of whole meanings, 35 of
    # fact F1) and a doing's Co-Agent place ("Castro visits the UN." wants `done_by(?v0, un)`, 24 sentences). Main
    # holds records for 2,667 nouns and 1,430 verbs, so what is measured here without them is below what main does.
    if "--with-words" in sys.argv:
        from core.learning.teaching_sources import word_record_of, WordRecord
        # EVERY RECORD KEPT, so a second run costs its reading and not its records. Of this experiment's 3,707
        # seconds with the records, 3,674 was building them and 33 was reading the whole dev split, which made every
        # question about a fix cost an hour to answer (lab notebook (101)). Written beside and moved over, so a run
        # that dies part way leaves a whole file. `--fresh-words` builds them again.
        kept = HERE / "results" / "word_records.jsonl"
        held = {}
        if kept.exists() and "--fresh-words" not in sys.argv:
            for line in kept.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    was = json.loads(line)
                    held[was["word"]] = was
            say(f"  {len(held):,} word records held from {kept.name}")
        base = set()
        for sentence in [t.sentence for t in lessons + gold] + [text for text, _, _, _ in dev]:
            for token in tokens_of(sentence):
                low = token.lower()
                if not low.isalpha() or len(low) < 2:
                    continue
                base.update(words.lexeme(low, cls) for cls in ("NOUN", "VERB", "ADJECTIVE", "ADVERB"))
        recorded, unheld, built = 0, 0, {}
        for k, word in enumerate(sorted(base)):
            try:
                record = WordRecord.from_dict(held[word]) if word in held else word_record_of(word)
                view.hold_word(record)
                built[word] = held.get(word) or record.to_dict()
                recorded += 1
            except Exception:
                unheld += 1
            if (k + 1) % 500 == 0:
                say(f"  recorded whole {k + 1:,} of {len(base):,}, {time.perf_counter() - started:.0f}s")
        if len(built) > len(held):
            part = kept.with_name(kept.name + ".part")
            part.write_text("".join(json.dumps(r) + "\n" for r in built.values()), encoding="utf-8")
            part.replace(kept)
            say(f"  kept {len(built):,} word records in {kept.name} ({kept.stat().st_size / 1e6:.0f} MB)")
        EV.metric("words recorded whole", recorded, unit="words",
                  note=f"of {len(base):,} the sentences use; {unheld:,} WordNet holds nothing of; "
                       f"{len(held):,} held from a previous run")
        say(f"recorded whole {held:,} of {len(base):,} words, {time.perf_counter() - started:.0f}s")

    if "--gold-categories" in sys.argv:
        # ── EACH WORD READ AS THE PMB'S CHECKED GOLD DERIVATION SAYS, and nothing else ──
        # The grammar chooses each word's category itself, out of what memory holds the word used as, and that choice
        # is where most of its words go wrong: of the dev words, 85.5% take the derivation's category or one saying
        # the same (`diagnostics/categories.py`). This fixes that choice to the gold and reads everything else as
        # usual, so what is left is what the grammar's RULES and what words hold cost, apart from the choosing. A
        # token whose gold category no entry can stand as is left to the grammar, and so is every entry over more
        # than one word (a gold derivation names one category per word).
        plain = grammar.lexicon.entries
        asked = {"forced": 0, "left": 0, "unnamed": 0}

        def gold_entries(toks, i, want=None):
            out = plain(toks, i)
            if not want or i not in want:
                asked["unnamed"] += 1
                return out
            fit = [(end, e) for end, e in out
                   if end > i + 1 or want[i] in reaches(grammar, toks, i, end, e)]
            if any(end == i + 1 for end, _ in fit):
                asked["forced"] += 1
                return fit
            asked["left"] += 1
            return out
        readings = []
        for (_, tokens, _, _), want in zip(dev, gold_of):
            grammar.lexicon.entries = lambda toks, i, _w=want: gold_entries(toks, i, _w)
            readings.append(grammar.read(tokens))
        grammar.lexicon.entries = plain
        EV.metric("dev words read as the gold derivation says", asked["forced"], unit="words",
                  note=f"{asked['left']:,} whose gold category no entry stands as, left to the grammar; "
                       f"{asked['unnamed']:,} the derivation names none of")
        say(f"gold categories: {asked['forced']:,} words forced, {asked['left']:,} no entry stands as, "
            f"{asked['unnamed']:,} unnamed")
    else:
        readings = [grammar.read(tokens) for _, tokens, _, _ in dev]

    def unnamed_before(meaning):
        if meaning is None:
            return None
        rename = {"?previous": "?before"}
        return Meaning(meaning.act, tuple(MeaningFact(f.relation, rename.get(f.subject, f.subject),
                                                      rename.get(f.obj, f.obj), f.positive, f.condition,
                                                      f.alternative, f.unasserted, f.given) for f in meaning.facts),
                       tuple(rename.get(a, a) for a in meaning.asked))

    names_of = []
    for r in readings:
        names = {}
        if r.sign is not None:
            for p in r.sign.pieces:
                if p[0] == "word":
                    for k in range(p[3], p[4]):
                        names.setdefault(k, p[1])
        names_of.append(names)
    aside = [senses_aside(m, at, names) for (_, _, m, at), names in zip(dev, names_of)]
    say(f"senses aside named by the grammar's words; {time.perf_counter() - started:.0f}s")
    whole = sum(r.sign is not None for r in readings)
    meant = sum(r.meaning is not None for r in readings)
    EV.metric("dev sentences read whole by the grammar", whole, unit="sentences", note=f"of {len(dev):,}")
    EV.metric("dev sentences given a meaning", meant, unit="sentences", note=f"of {len(dev):,}")
    say(f"read whole {whole:,} of {len(dev):,}; given a meaning {meant:,}")
    out = {}
    for way, wanted in (("strict", [m for _, _, m, _ in dev]), ("senses aside", aside),
                        ("senses aside, the one spoken of before unnamed", aside)):
        right = tp = fp = fn = 0
        for r, want in zip(readings, wanted):
            got = r.meaning
            if got is not None and way.endswith("unnamed"):
                got = unnamed_before(got)
            w = grounded(want, is_variable)
            if got is None:
                fn += sum(w.values())
                continue
            right += got.canonical() == want.canonical()
            g = grounded(got, is_variable)
            tp += sum((g & w).values())
            fp += sum((g - w).values())
            fn += sum((w - g).values())
        p, rc = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        f1 = 2 * p * rc / max(p + rc, 1e-9)
        out[way] = right / len(dev)
        EV.metric(f"{way}: whole meaning right", round(right / len(dev), 4), unit="fraction",
                  note=f"{right}/{len(dev)}")
        EV.metric(f"{way}: facts precision / recall / F1", [round(p, 4), round(rc, 4), round(f1, 4)],
                  unit="fraction")
        say(f"  {way}: whole right {right:,} ({right / len(dev):.1%}); facts precision {p:.1%}, recall {rc:.1%}, "
            f"F1 {f1:.1%}")
    EV.check("more dev meanings right whole, senses aside, than the composer (PMB-01 20261020T210127Z, 33.6%)",
             out["senses aside"] > 0.336, f"{out['senses aside']:.1%}")
    EV.check("more dev meanings right whole, strict, than the composer (16.1%)", out["strict"] > 0.161,
             f"{out['strict']:.1%}")
    EV.check("more dev meanings right whole, senses aside, than each word's category chosen out of context "
             "(20261025T173519Z, 366/884, 41.4%)", out["senses aside"] > 366 / 884, f"{out['senses aside']:.1%}")
    # Of the links decided, by where the decision came from, how many the meaning holds (senses aside, grounded as
    # PMB-01 grounds facts): the word's own uses, what memory holds it a kind of, the grammar's rule.
    made, held = Counter(), Counter()
    for r, want in zip(readings, aside):
        if r.meaning is None:
            continue
        kinds = {f.subject: f.obj for f in r.meaning.facts if f.relation == "instance_of" and is_variable(f.subject)}
        w = grounded(want, is_variable)
        for _, _, how, f in r.decided:
            if f is None:
                continue
            made[how] += 1
            s_ = kinds.get(f.subject, "?") if is_variable(f.subject) else f.subject
            o_ = kinds.get(f.obj, "?") if is_variable(f.obj) else f.obj
            held[how] += w[(f.relation, s_, o_, f.positive)] > 0
    for how in ("own", "kind", "rule"):
        EV.metric(f"links decided by {how}: made / held by the meaning", [made[how], held[how]], unit="links",
                  note=f"{held[how] / max(made[how], 1):.1%} held")
        say(f"  links decided by {how}: {made[how]:,} made, {held[how]:,} held ({held[how] / max(made[how], 1):.1%})")

    # ── what was missed, and the prose ──
    why = Counter()
    missed = []
    for (text, tokens, meaning, _), r, want in zip(dev, readings, aside):
        if r.sign is None:
            why["not read whole"] += 1
        elif r.meaning is None:
            why["read, no meaning: " + r.why[:50]] += 1
        elif r.meaning.canonical() != want.canonical():
            why["read, meaning wrong"] += 1
        else:
            continue
        missed.append({"sentence": text, "meaning": want.canonical(),
                       "read": r.meaning.canonical() if r.meaning is not None else f"({r.why})"})
    for k, n in why.most_common():
        say(f"  missed: {k}: {n}")
    EV.metric("missed, by why", dict(why.most_common()), unit="sentences")
    prose = []
    for text in json.loads((ROOT / "experiments" / "UNDERSTANDS-PROSE-01" / "texts.json").read_text()):
        for sentence in text["text"] + [q["q"] for q in text.get("questions", [])]:
            r = grammar.read(tokens_of(sentence))
            prose.append({"sentence": sentence, "read": r.meaning.canonical() if r.meaning is not None else
                          f"(not read: {r.why})"})
    results = HERE / "results"
    results.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (results / f"{stamp}_prose.json").write_text(json.dumps(prose, indent=1))
    # Every sentence missed, as met: two runs are compared sentence by sentence (a sample of 300 drawn from each
    # was a different 300).
    (results / f"{stamp}_missed.json").write_text(json.dumps(missed, indent=1))
    say(f"\n  run record: {EV.write()}  ({time.perf_counter() - started:.0f}s)")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
