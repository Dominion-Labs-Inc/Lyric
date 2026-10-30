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
    if VOCABULARY_ONLY:
        once = sum(1 for n in vocabulary.values() if n == 1)
        print(f"{once} of them used once, {len(vocabulary) - once} more than once; "
              f"the ten most used: {sorted(vocabulary.items(), key=lambda kv: -kv[1])[:10]}", flush=True)
        return
    print("recording each whole", flush=True)
    at = time.time()
    word_records, failed, refused = [], {}, {}
    for n, word in enumerate(sorted(vocabulary, key=lambda w: -vocabulary[w]), 1):
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
    print(f"words recorded whole {len(word_records)} of {len(vocabulary)} in {time.time() - at:.0f}s; "
          f"{len(refused)} did not hold together, {len(failed)} could not be built", flush=True)
    for word, problems in sorted(refused.items())[:20]:
        print(f"  refused {word!r}: {problems}", flush=True)
    for word, trouble in sorted(failed.items())[:20]:
        print(f"  failed  {word!r}: {trouble}", flush=True)

    with open(OUT, "w", encoding="utf-8") as handle:
        for record in word_records:
            handle.write(json.dumps(record.to_dict()) + "\n")
        for record in records:
            handle.write(json.dumps(record.to_dict()) + "\n")
    print(f"wrote {OUT} -- {OUT.stat().st_size / 1e6:.1f} MB, "
          f"{len(word_records)} word + {len(records)} sentence records", flush=True)


main()
