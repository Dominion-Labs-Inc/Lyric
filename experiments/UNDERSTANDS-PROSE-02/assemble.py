"""Joins the drawn texts and the questions written for them into texts.json, after checking each question: an answer
asked for is said in the text (a log's count is counted from its lines instead), and no question says its own answer."""
import json
import re
import sys
from pathlib import Path

import questions

HERE = Path(__file__).parent


def said(gold, text):
    """Whether `gold` is said in `text` where a word begins (a number only whole), as the run scores a reply."""
    start = r"(?<![0-9A-Za-z.,])" if gold[0].isdigit() else r"(?<![0-9A-Za-z])"
    end = r"(?![0-9])" if gold[-1].isdigit() else ""
    return re.search(start + re.escape(gold.lower()) + end, text.lower()) is not None


texts = json.loads((HERE / "texts_raw.json").read_text())
faults = []
for t in texts:
    whole = " ".join(t["text"])
    t["questions"] = [{"q": q, "answer": a} for q, a in questions.Q[t["name"]]]
    for q, a in questions.Q[t["name"]]:
        if isinstance(a, list):
            counted = t["kind"] == "security log" and q.startswith("How many")
            if not counted and not any(said(g, whole) for g in a):
                faults.append(f"{t['name']}: no answer to {q!r} is in the text: {a}")
            echoed = [g for g in a if said(g, q)]
            if echoed:
                faults.append(f"{t['name']}: {q!r} says its own answer {echoed}")
        elif a not in ("yes", "no"):
            faults.append(f"{t['name']}: {q!r} answered {a!r}")
print("\n".join(faults) or "every question checked")
(HERE / "texts.json").write_text(json.dumps(texts, indent=1, ensure_ascii=False))
sys.exit(1 if faults else 0)
