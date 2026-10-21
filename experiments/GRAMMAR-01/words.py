"""What GRAMMAR-01 holds of each word, from files, standing in for memory, read the way main reads it.

How each word is used is counted by `grammar_words.HeldWords` from UD English EWT's training part as Lyric reads a
treebank (`teaching_sources.read_conllu`: the sentences main holds analysed), and the forms each word is written in
(`word_forms`, as main holds them: "came" the past of `come`); what each word's thing is comes from
`grammar_words.GraphKnowledge` holding WordNet's links as `WordNetSource` teaches them (`isa`, `instance_of`,
`defined_with`: the records main was taught); a word is named by WordNet's plain form (`morphy`), else as the
treebank's lemmas have it, where main asks memory (`MemoryAgent.name_of`).

WordNet's links are kept beside the treebank (`grammar_wordnet_links.pkl`, never pushed) once read: about a minute."""
from __future__ import annotations

import pickle
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Optional, Sequence

NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
NUMBERS.update({"thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
                "hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9, "trillion": 10 ** 12})
UD = {"NOUN": "NOUN", "PROPN": "NAME", "VERB": "VERB", "ADJ": "ADJECTIVE", "ADV": "ADVERB", "NUM": "NUMERAL",
      "ADP": "PREPOSITION", "AUX": "VERB"}


def file_words(ewt: Path, closed):
    """The words as GRAMMAR-01 holds them (`HeldWords`), from the treebank at `ewt` and WordNet."""
    from nltk.corpus import wordnet as wn
    from core.learning.teaching_sources import WordNetSource, read_conllu
    from core.semantics.grammar_words import GraphKnowledge, HeldWords
    lemmas: Dict = defaultdict(Counter)
    endings: Dict = defaultdict(Counter)
    with open(ewt, encoding="utf-8") as handle:
        for line in handle:
            cols = line.rstrip("\n").split("\t")
            if len(cols) == 10 and cols[0].isdigit() and cols[3] in UD:
                form, lemma, cls = cols[1].lower(), cols[2].lower(), UD[cols[3]]
                lemmas[(form, cls)][lemma] += 1
                k = 0
                while k < min(len(form), len(lemma)) and form[k] == lemma[k]:
                    k += 1
                endings[(form[-3:], cls)][(len(form) - k, lemma[k:])] += 1
    by_class = {"NOUN": wn.NOUN, "VERB": wn.VERB, "ADJECTIVE": wn.ADJ, "ADVERB": wn.ADV}

    def name_of(word: str, cls: str) -> str:
        w = word.lower()
        if w in NUMBERS and cls == "NUMERAL":
            return str(NUMBERS[w])
        if re.fullmatch(r"-?\d+(\.\d+)?", w):
            return w
        got = lemmas.get((w, cls))
        if cls == "VERB" and got:
            # A verb's form as the treebank's lemmas have it first ("found": find, "saw": see), as memory names a
            # verb by the word it is a shape of (`MemoryAgent.name_of`).
            return got.most_common(1)[0][0]
        if cls in by_class:
            found = wn.morphy(w, by_class[cls])
            if found:
                return found.replace("_", " ")
        if got:
            return got.most_common(1)[0][0]
        change = endings.get((w[-3:], cls))
        if change:
            cut, add = change.most_common(1)[0][0]
            return w[:len(w) - cut] + add
        return w

    def classes(word: str) -> Dict[str, float]:
        """The kinds of word WordNet holds this very word as (a lemma of it, as memory holds the words taught; never
        through WordNet's own undoing of forms: "giggling" is no verb held, "giggle" is)."""
        out: Dict[str, float] = {}
        w = word.lower().replace(" ", "_")
        for synset in wn.synsets(w):
            if w not in (l.lower() for l in synset.lemma_names()):
                continue
            c = {"n": "NOUN", "v": "VERB", "a": "ADJECTIVE", "s": "ADJECTIVE", "r": "ADVERB"}[synset.pos()]
            out[c] = out.get(c, 0.0) + 1.0
        return out

    def names(words: Sequence[str], cls: str) -> Optional[str]:
        words = [w.lower() for w in words]
        if cls == "NOUN":
            words = words[:-1] + [wn.morphy(words[-1], wn.NOUN) or words[-1]]
        joined = "_".join(words)
        if wn.synsets(joined, by_class[cls]):
            return joined.replace("_", " ")
        return None

    knowledge = GraphKnowledge(classes=classes, names=names)
    held = ewt.parent.parent / "grammar_wordnet_links.pkl"
    if held.exists():
        links = pickle.loads(held.read_bytes())
    else:
        links = [(r.subject, r.relation, r.obj) for r in WordNetSource().records()
                 if r.relation in ("isa", "instance_of", "defined_with")]
        held.write_bytes(pickle.dumps(links))
    for subject, relation, obj in links:
        knowledge.add(subject, relation, obj)
    from core.semantics.word_forms import HeldForms, forms_from_conllu
    forms = HeldForms()
    with open(ewt, encoding="utf-8") as handle:
        for item in forms_from_conllu(handle, "ud_english_ewt"):
            forms.hold(item)
    return HeldWords(read_conllu(str(ewt), "ud_english_ewt"), closed, name_of, knowledge, forms)
