"""PROPBANK-01: whether every role PropBank gives the English Web Treebank is said in Lyric's meaning language.

PropBank's annotations of the treebank (CC BY-SA 4.0, `propbank-release`, `data/google/ewt`) write each word as
`[WORD]`, pointing into the LDC's copy of the text; UD English EWT (CC BY-SA 4.0) holds the same sentences, so the
words are taken from it, by document, sentence and place. Each argument is mapped by `core/semantics/propbank_roles`
(the label, the predicate, the frame files' function tag and VerbNet role, and the words that begin it), and each
predicate is a happening, nothing (an auxiliary, a light verb), a quality (an adjective), or what the predicate table
says. Counted: what is said in a kind the meaning language has, by a rule, as nothing, what NEEDS a kind or term it
has not, and what nothing maps. Then each happening's kind: whether WordNet holds a sense of its word, in its part of
speech, for the reader to name it by.

Run (from the Lyric folder; reads files only, no store):
    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/PROPBANK-01/experiment.py [--data DIR]
with `DIR` (default `test_data/syntax`) holding `propbank-release`, `propbank-frames` and `UD_English-EWT`.
"""
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

#: Universal Dependencies' parts of speech by the names Lyric's classes go by (`teaching_sources._UD_CLASS`).
_CLASS = {"NOUN": "NOUN", "PROPN": "NAME", "VERB": "VERB", "AUX": "AUXILIARY", "ADJ": "ADJECTIVE", "ADV": "ADVERB",
          "PRON": "PRONOUN", "DET": "DETERMINER", "ADP": "PREPOSITION", "CCONJ": "CONJUNCTION", "SCONJ": "SUBORDINATOR",
          "PART": "PARTICLE", "NUM": "NUMERAL", "PUNCT": "PUNCTUATION", "INTJ": "INTERJECTION", "SYM": "SYMBOL",
          "X": "OTHER"}
#: WordNet's part of speech for a predicate's Penn tag.
_WORDNET_POS = {"V": "v", "N": "n", "J": "a"}


def say(*a):
    print(*a, flush=True)


def frame_roles(frames: Path):
    """(roleset, ARGn) -> (function tag, VerbNet 3.4 roles), from the frame files."""
    roles = {}
    for path in frames.glob("*.xml"):
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        for roleset in tree.iter("roleset"):
            for role in roleset.iter("role"):
                verbnet = tuple(sorted({link.text.strip().lower() for link in role.iter("rolelink")
                                        if link.get("resource") == "VerbNet" and link.get("version") == "verbnet3.4"
                                        and link.text}))
                roles[(roleset.get("id"), "ARG" + str(role.get("n")).upper())] = (role.get("f", ""), verbnet)
    return roles


def ud_sentences(folder: Path):
    """(document, index) -> [(word, class)], from UD English EWT's three parts."""
    out = {}
    for part in ("train", "dev", "test"):
        sent_id, words = None, []
        for line in open(folder / f"en_ewt-ud-{part}.conllu", encoding="utf-8"):
            if line.startswith("# sent_id"):
                sent_id = line.split("=", 1)[1].strip()
            elif not line.strip():
                found = re.match(r"[a-z]+-(.+)-(\d+)$", sent_id or "")
                if found:
                    out[(found.group(1), int(found.group(2)) - 1)] = words
                sent_id, words = None, []
            elif not line.startswith("#"):
                cols = line.split("\t")
                if cols[0].isdigit():
                    words.append((cols[1], _CLASS.get(cols[3], cols[3])))
    return out


def annotated(release: Path):
    """Each sentence PropBank annotates: (document, index, rows), each row its columns."""
    for path in sorted(release.rglob("*.gold_skel")):
        block = []
        for line in list(path.open(encoding="utf-8")) + [""]:
            cols = line.split()
            if cols:
                block.append(cols)
                continue
            if block:
                yield block[0][0].split("/")[-1].replace(".xml", ""), int(block[0][1]), block
            block = []


def main() -> int:
    from experiments._evidence import RunRecord
    from core.semantics import propbank_roles as pr
    from core.semantics.derived_reader import _KINDS
    data = Path(sys.argv[sys.argv.index("--data") + 1]) if "--data" in sys.argv else ROOT / "test_data" / "syntax"
    EV = RunRecord("PROPBANK-01",
                   claim="every role PropBank gives the English Web Treebank is said in Lyric's meaning language",
                   hypothesis="each argument maps to a fact in a link kind the meaning language has, a rule its words "
                              "settle, or nothing; what does not is a named gap (a kind or term to decide) or listed")
    used = pr.kinds_used()
    EV.check("every link kind the mapping names is one the meaning language has", all(k in _KINDS for k in used),
             f"{len(used)} kinds; not held: {sorted(k for k in used if k not in _KINDS) or 'none'}")
    started = time.perf_counter()
    roles = frame_roles(data / "propbank-frames" / "frames")
    words_of = ud_sentences(data / "UD_English-EWT")
    say(f"frame roles {len(roles):,}; UD sentences {len(words_of):,}")

    sentences = aligned = 0
    how, by_label, needs, unmapped = Counter(), defaultdict(Counter), Counter(), Counter()
    predicates, senses_missing = Counter(), Counter()
    lemmas = Counter()
    for document, index, rows in annotated(data / "propbank-release" / "data" / "google" / "ewt"):
        sentences += 1
        words = words_of.get((document, index))
        if words is None or len(words) != len(rows):
            continue
        aligned += 1
        heads = [(i, r[7], r[6], r[4]) for i, r in enumerate(rows) if r[7] != "-"]
        for k, (at, roleset, lemma, tag) in enumerate(heads):
            itself = pr.predicate(roleset, tag)
            predicates["happening" if itself is None else itself.how if itself.how != "rule" else itself.rule] += 1
            if itself is None:
                lemmas[(lemma, _WORDNET_POS.get(tag[:1], ""))] += 1
            if itself is not None and itself.how == "needs":
                needs[f"predicate: {itself.needs}"] += 1
            spans, opened = [], {}
            for i, row in enumerate(rows):
                cell = row[8 + k] if 8 + k < len(row) else "*"
                for name in re.findall(r"\(([^*()]+)\*", cell):
                    opened.setdefault(name, []).append(i)
                for _ in re.findall(r"\)", cell.split("*", 1)[-1] if "*" in cell else ""):
                    pass
            for label, starts in opened.items():
                if label == "V":
                    continue
                for start in starts:
                    base, _ = pr.label_of(label)
                    tag_f, verbnet = roles.get((roleset, base), ("", ()))
                    found = pr.said(label, roleset=roleset, function_tag=tag_f, verbnet=verbnet,
                                    words=tuple(w for w, _ in words[start:start + 2]), first_class=words[start][1])
                    category = "unmapped" if found is None else found.how
                    how[category] += 1
                    by_label[label][category] += 1
                    if found is not None and found.how == "needs":
                        needs[found.needs] += 1
                    if found is None:
                        unmapped[(label, words[start][0].lower())] += 1
    total = sum(how.values())
    say(f"read in {time.perf_counter() - started:.0f}s: {sentences:,} sentences, {aligned:,} with UD's words, "
        f"{total:,} arguments, {sum(predicates.values()):,} predicates")
    EV.metric("sentences annotated", sentences, unit="sentences")
    EV.metric("sentences with UD's words", aligned, unit="sentences")
    EV.check("PropBank's sentences take UD's words", aligned >= 0.99 * sentences, f"{aligned:,} of {sentences:,}")
    EV.metric("arguments", total, unit="arguments")
    for category in ("fact", "rule", "same", "other side", "negates", "condition", "act", "happening", "nothing",
                     "needs", "unmapped"):
        EV.metric(f"arguments: {category}", how[category], unit="arguments",
                  note=f"{how[category] / max(total, 1):.2%}")
        say(f"    {category:10} {how[category]:7,}  {how[category] / max(total, 1):6.2%}")
    said_by = total - how["needs"] - how["unmapped"]
    EV.metric("arguments said in the meaning language", round(said_by / max(total, 1), 4), unit="fraction")
    for gap, n in needs.most_common():
        EV.metric(f"needs: {gap}", n, unit="arguments")
        say(f"    needs {gap:22} {n:6,}")
    labels_unmapped = sorted(label for label, c in by_label.items() if c["unmapped"] == sum(c.values()))
    EV.check("every label is mapped", not labels_unmapped, ", ".join(labels_unmapped) or "all")
    numbered = {label: c for label, c in by_label.items() if re.fullmatch(r"ARG\d", label)}
    numbered_unmapped = sum(c["unmapped"] for c in numbered.values())
    EV.check("every numbered argument is mapped", numbered_unmapped == 0, f"{numbered_unmapped} not")
    EV.metric("arguments nothing maps", how["unmapped"], unit="arguments",
              note="; ".join(f"{label} '{word}' {n}" for (label, word), n in unmapped.most_common(40)))
    say("    not mapped: " + "; ".join(f"{label} '{word}' {n}" for (label, word), n in unmapped.most_common(40)))
    for kind, n in predicates.most_common():
        EV.metric(f"predicates: {kind}", n, unit="predicates")
    say("    predicates: " + ", ".join(f"{k} {n:,}" for k, n in predicates.most_common()))

    try:
        from nltk.corpus import wordnet as wn
        def names(lemma, pos):
            """WordNet holds a sense of the word in its part of speech; a noun predicate PropBank writes with its
            verb's lemma ("agreement" as `agree`) is named by the verb's senses as well."""
            word = lemma.replace(" ", "_")
            return bool(wn.synsets(word, pos=pos) or (pos == "n" and wn.synsets(word, pos="v")))
        held = sum(n for (lemma, pos), n in lemmas.items() if pos and names(lemma, pos))
        named = sum(n for (lemma, pos), n in lemmas.items() if pos)
        missing = Counter({f"{lemma}/{pos}": n for (lemma, pos), n in lemmas.items() if pos and not names(lemma, pos)})
        EV.metric("happenings whose word WordNet holds a sense of, in its part of speech",
                  round(held / max(named, 1), 4), unit="fraction",
                  note="not: " + ", ".join(f"{w} {n}" for w, n in missing.most_common(25)))
        say(f"    happenings WordNet names: {held / max(named, 1):.1%}; not: "
            + ", ".join(f"{w} {n}" for w, n in missing.most_common(25)))
    except LookupError as missing_data:
        EV.note(f"WordNet not on this machine: {missing_data}")

    results = HERE / "results"
    results.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    (results / f"{stamp}_by_label.json").write_text(json.dumps(
        {label: dict(c) for label, c in sorted(by_label.items(), key=lambda x: -sum(x[1].values()))}, indent=1))
    (results / f"{stamp}_unmapped.json").write_text(json.dumps(
        [{"label": label, "word": word, "arguments": n} for (label, word), n in unmapped.most_common()], indent=1))
    path = EV.write()
    say(f"\n  run record: {path}")
    return 0 if EV.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
