"""ENGLISH-01, survey: how EWT's web English uses each mark Phase 1 teaches, before its lessons are written.

For each mark: how many sentences of EWT's training part use it, and how the people who annotated EWT related the
mark to the words around it (its `deprel`, and the relation of the word it attaches to), with an example of each
use. The training part is for writing the lessons; dev and test stay held out for measuring them.

    ./venv_lyric/bin/python3 experiments/ENGLISH-01/survey.py
"""
from collections import Counter, defaultdict
from pathlib import Path

EWT = Path(__file__).resolve().parents[2] / "data" / "bulk" / "ud_english_ewt"
MARKS = [".", "?", "!", ",", ":", ";", '"', "'", "-", "--", "(", ")", "...", "/"]


def sentences(part):
    text, tokens = None, []
    for line in (EWT / f"en_ewt-ud-{part}.conllu").read_text().splitlines():
        if line.startswith("# text = "):
            text = line[len("# text = "):]
        elif not line.strip():
            if text is not None:
                yield text, tokens
            text, tokens = None, []
        elif not line.startswith("#"):
            cols = line.split("\t")
            if cols[0].isdigit():
                tokens.append(cols)


def main():
    rows = list(sentences("train"))
    using = Counter()
    uses = defaultdict(Counter)
    examples = {}
    for text, tokens in rows:
        heads = {t[0]: t for t in tokens}
        seen = set()
        for t in tokens:
            form, deprel, head = t[1], t[7], t[6]
            mark = form if form in MARKS else ("'" if form in ("'s", "n't", "'m", "'re", "'ve", "'ll", "'d") else None)
            if form in ('``', "''", "“", "”"):
                mark = '"'
            if mark is None:
                continue
            seen.add(mark)
            to = heads.get(head)
            use = f"{deprel} of {to[7] if to else 'root'}" if mark != "'" else f"{form} ({deprel})"
            uses[mark][use] += 1
            examples.setdefault((mark, use), text)
        using.update(seen)
    print(f"{len(rows)} training sentences")
    for mark in MARKS:
        if not using[mark]:
            continue
        print(f"\n{mark!r}: in {using[mark]} sentences")
        for use, n in uses[mark].most_common(8):
            print(f"   {n:6d}  {use:28s} e.g. {examples[(mark, use)][:110]}")


main()
