"""The records a vocabulary is taught from: PMB gold sentences recorded whole, and the words they use recorded whole.

Writes a file only, never a store. The derivation is release 4.0.0's gold (checked by hand), the meaning release
5.1.0's; 5.1.0's dev and test documents are held out by the source and never taught, which is what GRAMMAR-01
measures on. `HOW_MANY` documents (0 for all of the split), words first in the file as teaching takes them
(`teaching.py`'s dispatch runs `word_records` before `sentence_records`; TRAIN-FORMAT-02: words before sentences).

THE VOCABULARY IS KEYED BY BASE, NOT BY WHAT A SENTENCE CALLS THE LEMMA. The PMB's gold annotation sometimes writes
the lemma as the form -- `ran`, `sucks`, `wiped` -- and a record asked for a form holds no forms at all, UD's rows
being keyed by base, so it is refused for "no form" and the word's real base is never taught at all. Measured on 182
words of 62 gold sentences: 8 refused, 4 of them punctuation and 4 of them this (2026-10-30). The base is WordNet's
own (`morphy`, asked for the class the sentence used the word as), which is the same authority the record takes its
senses from. Punctuation and symbols are not asked for at all: `ClosedClassSource` states their class, and a sentence
recorded whole skips them when it teaches classes (`MemoryAgent._learn_record_words`).
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path("/Users/stefan/Dominion Labs/Lyric")
sys.path.insert(0, str(ROOT))
HOW_MANY = int(os.environ.get("HOW_MANY", "100"))
#: Stop after the vocabulary and write nothing: the sentences cost almost nothing to record and the words cost
#: seconds to minutes each, so how many words a set of sentences needs is asked on its own, before committing to
#: building them (`run`, the heaviest verb in WordNet, took longer alone than 182 other words together).
VOCABULARY_ONLY = os.environ.get("VOCABULARY_ONLY", "").lower() in ("1", "yes", "true")
OUT = Path(os.environ["OUT"]) if not VOCABULARY_ONLY else None
#: A previous build's file whose WORD records are taken as they stand. A word's record is built from the word and
#: from WordNet alone, never from what a sentence means, so a change to the MEANINGS leaves every one of them as it
#: was: keeping a pronoun's gender left 3875 words and 190 bases both unchanged (2026-10-30). Rebuilding the
#: meanings then costs the sentence pass alone, seconds against the better part of an hour for 3,875 words. May be
#: the file being written: it is read whole before anything is written.
REUSE = Path(os.environ["REUSE"]) if os.environ.get("REUSE") else None
#: Where the vocabulary comes from: `pmb` (the gold documents' own words, the default) or `treebank` (every open-class
#: lemma of a UD treebank, no sentences). The treebank path records WORDS ONLY, because the sentences of a treebank
#: are taught as structure by `teach.py --source treebank` reading the file itself, not as records -- and the words
#: have to be held before that pass runs ("a sentence teaches how known words go together, never a word it does not
#: hold", `WordRecord`).
VOCABULARY = os.environ.get("VOCABULARY", "pmb")
#: The treebank whose vocabulary to record (VOCABULARY=treebank).
TREEBANK = Path(os.environ.get("TREEBANK") or ROOT / "test_data" / "syntax" / "UD_English-EWT" / "en_ewt-ud-train.conllu")
#: How often a lemma must be used in it to be recorded at all; 1 records every one of them.
FLOOR = int(os.environ.get("FLOOR", "1"))
#: Write only the words `REUSE` does NOT hold. For the treebank path, where the store already holds every word of the
#: file being reused, a pass over the whole of it would re-offer thousands of records the store answers `already` to;
#: what is wanted is the new vocabulary alone. The PMB path leaves this off: its OUT must hold the whole corpus.
NEW_ONLY = os.environ.get("NEW_ONLY", "").lower() in ("1", "yes", "true")

#: UD's open classes, and which WordNet part to ask for a lemma's base. A name (PROPN) has no WordNet entry to ask
#: about, so it is taken as written -- and is recorded, and refused where it holds nothing, rather than guessed at.
UD_WORDNET_PART = {"NOUN": "n", "VERB": "v", "ADJ": "a", "ADV": "r", "PROPN": None}


def _treebank_vocabulary(wn) -> dict:
    """Every open-class lemma of `TREEBANK`, under the same base the PMB path keys by (`wn.morphy`), with how often
    the treebank uses it. Reads the file and nothing else."""
    used: dict = {}
    taken = 0
    with open(TREEBANK, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            columns = line.rstrip("\n").split("\t")
            if len(columns) < 10 or "-" in columns[0] or "." in columns[0]:
                continue        # a multiword token's range, or an inserted empty node
            lemma, word_class = columns[2], columns[3]
            if word_class not in UD_WORDNET_PART or lemma in ("_", ""):
                continue
            taken += 1
            written = lemma.lower()
            part = UD_WORDNET_PART[word_class]
            base = (wn.morphy(written, part) or written).lower() if part else written
            used[base] = used.get(base, 0) + 1
    kept = {word: n for word, n in used.items() if n >= FLOOR}
    print(f"{TREEBANK.name}: {taken} open-class words, {len(used)} distinct under their base, "
          f"{len(kept)} used at least {FLOOR}x", flush=True)
    return kept

#: The WordNet part of speech for each class a sentence uses a word as, for asking WordNet the word's base. The
#: classes absent here (NAME, and every closed class) have no WordNet entry to ask about.
WORDNET_PART = {"VERB": "v", "NOUN": "n", "ADJECTIVE": "a", "ADVERB": "r"}

#: Classes no word record is asked for: their class is stated by `ClosedClassSource` and a sentence recorded whole
#: teaches nothing of them, so a record could only ever be refused for holding no forms.
NOT_RECORDED = {"PUNCTUATION", "SYMBOL"}


def main():
    from core.learning.teaching_sources import WordNetSource, record_of_pmb, word_record_of
    from core.semantics import pmb_meanings as pm
    from core.semantics.composition import TaughtSentence
    from nltk.corpus import wordnet as wn
    pmb51 = ROOT / "test_data" / "semantics" / "pmb" / "pmb-5.1.0"
    pmb40 = ROOT / "test_data" / "semantics" / "pmb" / "pmb-4.0.0"
    held_out = set()
    for split in ("dev", "test"):
        for name in ("standard", "long"):
            f = pmb51 / "split" / "en" / split / f"{name}.sbn"
            if f.exists():
                held_out.update(pm.split_ids(f))
    print(f"held out {len(held_out)} dev and test documents, never taught", flush=True)
    sense_names = WordNetSource()._sense_names()

    def sense_name(sense):
        try:
            return sense_names.get(wn.synset(sense)) or None
        except Exception:
            return None

    ids = [d for d in pm.split_ids(pmb51 / "split" / "en" / "train" / "gold.sbn") if d not in held_out]
    print(f"train gold {len(ids)} documents after holding out", flush=True)
    if HOW_MANY:
        ids = ids[:HOW_MANY]
    if VOCABULARY == "treebank":
        # NOT ONE SENTENCE IS RECORDED HERE. The vocabulary is the treebank's, read below; its sentences are taught
        # as structure from the file itself, after these words are held.
        ids = []
    at = time.time()
    records, why = [], {"no derivation": 0, "several sentences": 0, "no meaning": 0, "refused": 0}
    for n, doc_id in enumerate(ids, 1):
        document = pm.read_document(pmb51 / "data" / "en" / "gold" / doc_id)
        said = pm.meaning_of(document, sense_name) if document is not None else None
        if said is None or said.meaning is None:
            why["no meaning"] += 1
            continue
        # The meaning's terms placed in the sentence as `PMBSource.taught_sentences` places them: the record's
        # builder takes a `TaughtSentence`, whose anchors are pairs, not the `Said` whose anchors are a mapping.
        anchors = []
        for term, places in said.anchors.items():
            lines = tuple((c.span[0], c.span[1], how, c.marked)
                          for c, how in ((document.concepts[k], how) for k, how in places) if c.span)
            if lines:
                anchors.append((term, lines))
        taught = TaughtSentence(document.text, said.meaning, f"pmb/{doc_id}", tuple(anchors))
        derivations = pm.read_derivations(pmb40 / "data" / "en" / "gold" / doc_id)
        if not derivations:
            why["no derivation"] += 1
            continue
        if len(derivations) > 1:
            why["several sentences"] += 1
            continue
        try:
            record = record_of_pmb(derivations[0], taught, split="train")
        except Exception as e:
            why["refused"] += 1
            if why["refused"] <= 3:
                print(f"  {doc_id}: {type(e).__name__} {e}", flush=True)
            continue
        problems = record.problems() if hasattr(record, "problems") else []
        if problems:
            why["refused"] += 1
            if why["refused"] <= 3:
                print(f"  {doc_id}: {problems[:2]}", flush=True)
            continue
        records.append(record)
        if n % 250 == 0:
            print(f"  {n} of {len(ids)}: {len(records)} recorded, {time.time() - at:.0f}s", flush=True)
    print(f"sentences recorded whole {len(records)} of {len(ids)} in {time.time() - at:.0f}s; {why}", flush=True)

    # EVERY WORD THE SENTENCES USE, UNDER ITS BASE. What a sentence calls the lemma is taken as the base only where
    # WordNet knows no better: `ran` written as the lemma of `ran` is `run`, whose record holds `ran` as a form.
    vocabulary, instead = {}, {}
    for record in records:
        for word in record.words:
            # A record's words are held as objects and written out as mappings, so take either.
            get = word.get if isinstance(word, dict) else (lambda k, w=word: getattr(w, k, None))
            written = str(get("lemma") or get("form") or "").lower()
            word_class = str(get("word_class") or get("class") or "").upper()
            if not written or word_class in NOT_RECORDED:
                continue
            part = WORDNET_PART.get(word_class)
            base = (wn.morphy(written, part) or written).lower() if part else written
            if base != written:
                instead[written] = base
            vocabulary[base] = vocabulary.get(base, 0) + 1
    print(f"{len(vocabulary)} distinct words in them; {len(instead)} taken under a base the sentence did not give "
          f"({sorted(instead.items())[:8]})", flush=True)
    if VOCABULARY == "treebank":
        vocabulary = _treebank_vocabulary(wn)
    if VOCABULARY_ONLY:
        once = sum(1 for n in vocabulary.values() if n == 1)
        print(f"{once} of them used once, {len(vocabulary) - once} more than once; "
              f"the ten most used: {sorted(vocabulary.items(), key=lambda kv: -kv[1])[:10]}", flush=True)
        return
    held = {}
    if REUSE:
        with open(REUSE, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    was = json.loads(line)
                    if "word" in was:
                        held[was["word"]] = was
        print(f"{len(held)} word records held from {REUSE}, built again only for a word it does not hold", flush=True)
    print("recording each whole", flush=True)
    at = time.time()
    word_records, failed, refused = [], {}, {}
    for n, word in enumerate(sorted(vocabulary, key=lambda w: -vocabulary[w]), 1):
        if word in held:
            if not NEW_ONLY:
                word_records.append(held[word])
            continue
        try:
            record = word_record_of(word)
        except Exception as e:
            failed[word] = f"{type(e).__name__} {e}"
            continue
        problems = record.problems()
        if problems:
            refused[word] = problems[:2]
            continue
        word_records.append(record)
        if n % 250 == 0:
            print(f"  {n} of {len(vocabulary)}: {len(word_records)} recorded, {time.time() - at:.0f}s", flush=True)
    print(f"words recorded whole {len(word_records)} of {len(vocabulary)} in {time.time() - at:.0f}s "
          f"({sum(1 for w in word_records if isinstance(w, dict))} held from a previous build); "
          f"{len(refused)} did not hold together, {len(failed)} could not be built", flush=True)
    for word, problems in sorted(refused.items())[:20]:
        print(f"  refused {word!r}: {problems}", flush=True)
    for word, trouble in sorted(failed.items())[:20]:
        print(f"  failed  {word!r}: {trouble}", flush=True)

    # WRITTEN BESIDE AND MOVED OVER, so a build that dies part way leaves the file it was asked to replace whole --
    # which is also what lets `REUSE` be `OUT` itself.
    part = OUT.with_name(OUT.name + ".part")
    with open(part, "w", encoding="utf-8") as handle:
        for record in word_records:
            handle.write(json.dumps(record if isinstance(record, dict) else record.to_dict()) + "\n")
        for record in records:
            handle.write(json.dumps(record.to_dict()) + "\n")
    os.replace(part, OUT)
    print(f"wrote {OUT} -- {OUT.stat().st_size / 1e6:.1f} MB, "
          f"{len(word_records)} word + {len(records)} sentence records", flush=True)


main()
