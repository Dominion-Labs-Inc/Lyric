"""Of published prose analysed by hand (UD English PUD: news and Wikipedia, held out of all Lyric learned), how many
content words the grammar's chosen reading joins to the word the analysis joins them to. Files only, no store; built
as GRAMMAR-01 builds the grammar (about five minutes), then a seeded 200 sentences (about four).

Content words are those the analysis does not mark as a preposition, a joining word, a determiner, an auxiliary, a
copula or punctuation. A reading's head that is such a word is passed up to the word it joins ("pay within 30 days":
days to pay, through "within"); a word inside one entry of several words ("United States") is right where the
analysis joins it inside the entry.

    PYTHONPATH="$PWD" ./venv_lyric/bin/python3 experiments/GRAMMAR-01/diagnostics/prose_joins.py [N] [--without-structure]

`--without-structure` reads without the structure view deciding which word takes which (`Grammar._joined`)."""
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


every = list(sentences(ROOT / "test_data" / "syntax" / "UD_English-PUD" / "en_pud-ud-test.conllu"))
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
    head_of, inside = {}, {}
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
print(dict(stat), f"{time.perf_counter() - started:.0f}s")
print(f"joined right: {stat['right']} of {stat['content words read']} content words of the sentences read whole "
      f"({100 * stat['right'] / max(1, stat['content words read']):.1f}%), of all {stat['content words']} "
      f"({100 * stat['right'] / max(1, stat['content words']):.1f}%)")
