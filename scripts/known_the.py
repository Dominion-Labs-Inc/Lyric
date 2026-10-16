#!/usr/bin/env python3
"""Rewrite english_01-39 by docs/TEACHING.md §12d: "the X" names a particular thing already known.

Each "the" is followed to the word the meaning holds as a term. A term held where a thing stands (a fact's subject,
or the object of a link between things) is the known thing: it becomes a variable, `given instance_of(?tN, X)` is
added, and every fact naming the thing names the variable (an `isa` said of it becomes `instance_of`). A term held only
where a kind is said of something ("Tom, the teacher": `isa(tom, teacher)`) stays. KIND lists the sentences where "the
X" is the kind itself (rule 2). The known thing is inside an "if" or what someone said where every fact naming it
is.

Used once on 2026-10-06 to rewrite english_01-39 (1,060 sentences), and by experiments whose expected meanings
were written before §12d (`rewrite`, `known`).

Run with --write to write the lessons; without it, it reports:
    ./venv_lyric/bin/python3 scripts/known_the.py"""
import json, sys, re
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.semantics.sentence_machine import form_of
from core.semantics.derived_reader import Meaning

#: Rule 2: "the X" is the kind. (sentence, term)
KIND = {("Every bird except the penguin can fly.", "penguin")}
#: Objects that are kinds, qualities or abilities said of a thing, not things.
KIND_OBJECT = {"isa", "instance_of", "has_property", "capable_of", "synonym_of", "antonym_of", "has_count",
               "has_rank", "has_degree", "greatest_of", "least_of"}
IRREGULAR = {"men": "man", "women": "woman", "children": "child", "mice": "mouse", "geese": "goose", "feet": "foot",
             "teeth": "tooth", "people": "person", "fish": "fish", "sheep": "sheep", "deer": "deer"}


def singulars(word):
    out = [word]
    if word in IRREGULAR:
        out.append(IRREGULAR[word])
    if word.endswith("ies"):
        out.append(word[:-3] + "y")
    if word.endswith("es"):
        out.append(word[:-2])
    if word.endswith("s"):
        out.append(word[:-1])
    return out


def rewrite(sentence, meaning):
    words = [p.text for p in form_of(sentence)]
    low = [w.lower() for w in words]
    facts = [list(f) for f in meaning["facts"]]
    terms = {str(t) for f in facts for t in f[1:3]}

    def entity(term):
        return any(f[1] == term or (f[2] == term and f[0] not in KIND_OBJECT) for f in facts)

    found, unresolved = [], []
    for i, w in enumerate(low):
        if w != "the":
            continue
        term = None
        for j in range(i + 1, min(i + 4, len(low))):
            if not re.match(r"^[a-z][a-z'-]*$", low[j]):
                break
            pair = " ".join(low[j:j + 2])
            for cand in ([pair] if j + 1 < len(low) else []) + singulars(low[j]):
                if cand in terms:
                    term = cand
                    break
            if term:
                break
        if term is None:
            unresolved.append(" ".join(words[i:i + 3]))
            continue
        if (sentence, term) in KIND or not entity(term):
            continue
        if term not in found:
            found.append(term)
    heads = _known_heads(low, facts)
    if not found:
        if not heads:
            return None, unresolved
        new = dict(meaning, facts=_given(facts, heads))
        Meaning.from_dict(new)          # refuses what the meaning language cannot hold
        return new, unresolved
    used = {str(t) for f in facts for t in f[1:3] if str(t).startswith("?")}
    names = {}
    n = 0
    for term in found:
        while f"?t{n}" in used:
            n += 1
        names[term] = f"?t{n}"
        used.add(f"?t{n}")
    out = []
    for term in found:
        # Inside an "if", or inside what someone said, where every fact naming it is: the known thing is part of
        # what the condition or the saying holds, as a filler's facts are where its place is (`_composed`).
        uses = [f for f in facts if term in (f[1], f[2])]
        condition = all(len(f) > 4 and f[4] for f in uses)
        unasserted = all(len(f) > 6 and f[6] for f in uses)
        out.append(["instance_of", names[term], term, True, condition, False, unasserted, True])
    for f in facts:
        rel, s, o, pos, *flags = f
        s2 = names.get(s, s)
        o2 = o if (rel in KIND_OBJECT and o in names and s not in names) else names.get(o, o) if rel not in KIND_OBJECT else o
        if rel == "isa" and s in names:
            rel = "instance_of"
        out.append([rel, s2, o2, pos, *flags])
    new = dict(meaning, facts=_given(out, heads))
    Meaning.from_dict(new)          # refuses what the meaning language cannot hold
    return new, unresolved


#: What a "the" before a thing the lesson already wrote as a variable does not make known (rule 4): its rank ("the
#: fourth book"), its being the most of its kind ("the tallest boy"), or a function's value ("the sine of zero").
NOT_A_THING = {"has_rank", "greatest_of", "least_of", "has_argument"}


def _known_heads(low, facts):
    """The things a "the" names that the lesson wrote as a variable of their kind, `instance_of(?v, X)`, without
    marking them known (rule 1): "the small cup", "the dog that barked", "the house where Tom lived". The first
    pass followed "the" only to a term the meaning held as a constant, so these were left as some cup, some dog.
    Left as written: rule 4 (`NOT_A_THING`), and "of the" before a group ("Some of the cats", "One of the dogs"),
    which is part of a known group and waits on how a part of one is written."""
    # Every thing written as a variable of its kind, known or not: the noun a "the" governs is the first word after
    # it that names one, or a term the meaning holds outright, and the search stops there. Not stopping at a thing
    # already known, "The dog barks." went on to "barks" and made the barking known.
    kinds = {}
    for f in facts:
        if f[0] == "instance_of" and str(f[1]).startswith("?"):
            kinds.setdefault(str(f[2]), []).append((str(f[1]), bool(len(f) > 7 and f[7])))
    # A term the meaning holds outright as a thing is the first pass's; one it holds as a quality said of a thing
    # ("small" in "the small cup") is a word before the noun, and the search goes on past it.
    terms = {str(t) for f in facts for t in (f[1], f[2]) if not str(t).startswith("?")
             and (f[1] == t or f[0] not in KIND_OBJECT)}
    heads = []
    for i, w in enumerate(low):
        if w != "the" or (i > 0 and low[i - 1] == "of"):
            continue
        for j in range(i + 1, min(i + 4, len(low))):
            if not re.match(r"^[a-z][a-z'-]*$", low[j]):
                break
            candidates = ([" ".join(low[j:j + 2])] if j + 1 < len(low) else []) + singulars(low[j])
            hit = next((kinds[c] for c in candidates if c in kinds), None)
            if hit is None:
                if any(c in terms for c in candidates):
                    break                    # a term held outright: the first pass's
                continue
            for var, given in hit:
                if not given and var not in heads \
                        and not any(f[0] in NOT_A_THING and var in (str(f[1]), str(f[2])) for f in facts):
                    heads.append(var)
            break
    return heads


def _given(facts, heads):
    """The facts, with each head's `instance_of` marked known (`given`, the eighth place)."""
    out = []
    for f in facts:
        f = list(f)
        if f[0] == "instance_of" and str(f[1]) in heads:
            f = f + [False] * (8 - len(f)) if len(f) < 8 else f
            f[7] = True
        out.append(f)
    return out


def known(sentence, meaning):
    """A meaning written before §12d, as it is written now: `meaning` a Meaning; returned the same when nothing in
    the sentence is a known thing."""
    new, _ = rewrite(sentence, meaning.to_dict())
    return Meaning.from_dict(new) if new is not None else meaning


def rewrite_file(path, write):
    """One lesson file by the same rule: the sentences changed, as (sentence, before, after)."""
    lesson = json.loads(Path(path).read_text())
    changed = []
    for record in lesson["records"]:
        new, _ = rewrite(record["sentence"], record["meaning"])
        if new is not None:
            changed.append((record["sentence"], record["meaning"]["facts"], new["facts"]))
            record["meaning"] = new
    if write and changed:
        Path(path).write_text(json.dumps(lesson, indent=1, ensure_ascii=False) + "\n")
    return changed


if __name__ == "__main__":
    write = "--write" in sys.argv
    if "--file" in sys.argv:
        for sentence, before, after in rewrite_file(sys.argv[sys.argv.index("--file") + 1], write):
            print(f"{sentence}\n    {before}\n -> {after}")
        sys.exit(0)
    changed = Counter()
    unresolved_all = Counter()
    for n in range(1, 40):
        path = ROOT / "data" / "lessons" / f"english_{n:02d}.json"
        lesson = json.loads(path.read_text())
        for record in lesson["records"]:
            new, unresolved = rewrite(record["sentence"], record["meaning"])
            for u in unresolved:
                unresolved_all[u.lower()] += 1
            if new is not None:
                changed[n] += 1
                record["meaning"] = new
        if write:
            path.write_text(json.dumps(lesson, indent=1, ensure_ascii=False) + "\n")
    print("changed", sum(changed.values()), dict(sorted(changed.items())))
    print("'the' not followed to a term:", sum(unresolved_all.values()), unresolved_all.most_common(60))
