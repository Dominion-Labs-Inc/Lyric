"""Of published prose analysed by hand (UD English PUD: news and Wikipedia, held out of all Lyric learned), how many
content words the grammar's chosen reading joins to the word the analysis joins them to. Files only, no store; built
as GRAMMAR-01 builds the grammar (about five minutes), then a seeded 200 sentences (about four).

Content words are those the analysis does not mark as a preposition, a joining word, a determiner, an auxiliary, a
copula or punctuation. A reading's head that is such a word is passed up to the word it joins ("pay within 30 days":
days to pay, through "within"); a word inside one entry of several words ("United States") is right where the
analysis joins it inside the entry.

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/prose_joins.py [N]
        [--without-structure] [--shape fronted|stranded|either] [--treebank ewt-dev|gum-dev|pud-test]

`--without-structure` reads without the structure view deciding which word takes which (`Grammar._joined`), and
`--without-carried` without a preposition being carried along with the wh-phrase it opens (`Lexicon._carried`).

`--shape` draws only the sentences that FRONT a preposition with a wh-phrase ("From which port did the first failed
password come?") or STRAND one ("What can an Advanced Learner Loan help with?"), and scores the preposition's own
attachment beside the content words. That construction is 110 of UNDERSTANDS-PROSE-02's 456 questions and 13 of the
19 questions the 10-26 run on main read only in part, and the PMB dev split GRAMMAR-01 scores holds it once in 911
sentences, so nothing GRAMMAR-01 measures can see it. `--treebank` says which hand-analysed sentences to draw from
(held out of everything Lyric learned: EWT's and GUM's dev, PUD's test)."""
import random
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent))
from core.semantics import grammar as gm  # noqa: E402
from core.learning.teaching_sources import PMBDerivationSource  # noqa: E402
from words import file_structure, file_words  # noqa: E402

N = int(next((a for a in sys.argv[1:] if a.isdigit()), "200"))
treebank = ROOT / "test_data" / "syntax" / "UD_English-EWT" / "en_ewt-ud-train.conllu"
words = file_words(treebank, gm.closed_uses())
if "--without-carried" in sys.argv:
    # WITHOUT A PREPOSITION BEING CARRIED ALONG WITH THE WH-PHRASE IT OPENS (`Lexicon._carried`), so the same
    # measurement prices that rule: the preposition is left with its six modifier categories alone, as before it.
    gm.Lexicon._carried = lambda self, tokens, i, evidence: []
view = gm.GrammarView(words, structure=None if "--without-structure" in sys.argv else file_structure(treebank))
for d in PMBDerivationSource().derived():
    view.hold_derived(d)
g = view.grammar
MARKING = {"case", "mark", "cc", "det", "aux", "aux:pass", "cop", "punct", "det:predet", "cc:preconj"}


def sentences(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line:
            if rows:
                yield rows
            rows = []
        elif not line.startswith("#"):
            cols = line.split("\t")
            if cols[0].isdigit():
                rows.append((cols[1], int(cols[6]) - 1, cols[7]))


TREEBANKS = {"pud-test": ("UD_English-PUD", "en_pud-ud-test.conllu"),
             "ewt-dev": ("UD_English-EWT", "en_ewt-ud-dev.conllu"),
             "gum-dev": ("UD_English-GUM", "en_gum-ud-dev.conllu")}
asked_for = sys.argv[sys.argv.index("--treebank") + 1] if "--treebank" in sys.argv else "pud-test"
if asked_for not in TREEBANKS:
    sys.exit(f"no such hand-analysed sentences: {asked_for} (have {', '.join(sorted(TREEBANKS))})")
folder, name = TREEBANKS[asked_for]
every = list(sentences(ROOT / "test_data" / "syntax" / folder / name))

#: THE WORDS A PREPOSITION PHRASE IS FRONTED OR STRANDED BY, as a treebank writes them.
PREPOSITIONS = set(
    "about above across after against along among around at before behind below beneath beside between beyond by "
    "down during except for from in inside into near of off on onto out outside over past since through throughout "
    "to toward towards under until up upon with within without".split())
ASKING = set("what which who whom whose when where how why".split())


def shaped(rows, how: str) -> bool:
    """Whether the sentence fronts a preposition with a wh-phrase, strands one at its end, or either."""
    words = [r[0] for r in rows]
    fronted = any(a.lower() in PREPOSITIONS and b.lower() in ASKING for a, b in zip(words, words[1:]))
    stranded = len(words) > 1 and words[-1] in "?." and words[-2].lower() in PREPOSITIONS
    return {"fronted": fronted, "stranded": stranded, "either": fronted or stranded}[how]


shape = sys.argv[sys.argv.index("--shape") + 1] if "--shape" in sys.argv else None
if shape:
    if shape not in ("fronted", "stranded", "either"):
        sys.exit(f"no such shape: {shape} (fronted, stranded, either)")
    every = [rows for rows in every if shaped(rows, shape)]
    print(f"{len(every):,} sentences of {name} {shape} a preposition")
random.Random(20261026).shuffle(every)
stat = Counter()
started = time.perf_counter()
for rows in every[:N]:
    stat["sentences"] += 1
    content = [i for i, r in enumerate(rows) if r[2] not in MARKING and r[1] >= 0]
    stat["content words"] += len(content)
    reading = g.read(tuple(r[0] for r in rows))
    if reading.sign is None:
        stat["no whole"] += 1
        continue
    stat["content words read"] += len(content)
    head_of, inside, spans = {}, {}, []
    stack = [reading.sign]
    while stack:
        s = stack.pop()
        stack.extend(s.kids)
        if len(s.kids) == 2:
            a, b = s.kids
            joined = b if a.word == s.word else a
            if joined.word != s.word:
                head_of[joined.word] = s.word
        elif not s.kids and s.end - s.start > 1:
            inside.update({w: (s.start, s.end) for w in range(s.start, s.end) if w != s.head})
            spans.append((s.start, s.end))
    marking = {i for i, r in enumerate(rows) if r[2] in MARKING}
    copula = {r[1]: i for i, r in enumerate(rows) if r[2] == "cop"}
    for w in content:
        gold = rows[w][1]
        if w in inside and inside[w][0] <= gold < inside[w][1]:
            stat["right"] += 1
            continue
        h, seen = head_of.get(w), set()
        while h is not None and h in marking and h not in seen and h != copula.get(gold):
            seen.add(h)
            h = head_of.get(h)
        stat["right"] += h == gold or (h is not None and h == copula.get(gold))
    if shape:
        # THE FRONTED OR STRANDED PREPOSITION ITSELF: a marking word, so not a content word, and the one thing this
        # shape is about. Right where the reading joins it to the word the analysis joins it to.
        for i, r in enumerate(rows):
            if r[2] != "case" or r[0].lower() not in PREPOSITIONS:
                continue
            words = [x[0] for x in rows]
            is_fronted = i + 1 < len(words) and words[i + 1].lower() in ASKING
            is_stranded = i + 2 == len(words) and words[-1] in "?."
            if not (is_fronted or is_stranded):
                continue
            stat["prepositions fronted or stranded"] += 1
            # A WORD INSIDE ONE ENTRY OF SEVERAL WORDS IS RIGHT WHERE THE ANALYSIS JOINS IT INSIDE THE ENTRY, as
            # this measure already counts a content word (`inside`): a preposition carried along with the wh-phrase
            # it opens is read as one entry with it (`Lexicon._carried`), so it has no head of its own, and the
            # analysis joins it to that very wh-word.
            stat["prepositions joined right"] += (head_of.get(i) == r[1]
                                                 or any(a <= i < b and a <= r[1] < b for a, b in spans))
print(dict(stat), f"{time.perf_counter() - started:.0f}s")
print(f"joined right: {stat['right']} of {stat['content words read']} content words of the sentences read whole "
      f"({100 * stat['right'] / max(1, stat['content words read']):.1f}%), of all {stat['content words']} "
      f"({100 * stat['right'] / max(1, stat['content words']):.1f}%)")
if shape:
    held = stat["prepositions fronted or stranded"]
    print(f"the {shape} preposition joined right: {stat['prepositions joined right']} of {held} "
          f"({100 * stat['prepositions joined right'] / max(1, held):.1f}%); "
          f"{stat['no whole']} of {stat['sentences']} sentences read no whole")
