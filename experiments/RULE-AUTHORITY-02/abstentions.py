#!/usr/bin/env python3
"""Why Lyric held no rule in settled conjunction worlds (C3's abstentions), from a run's frozen files.

The evaluator scores what Lyric ended with and nothing else. This asks Lyric's own question again, offline: for each
settled conjunction world with three or more successes that did not end exact, the basis `_judge_signature` built
after the last act (every act, the latest success held back, the actionless cases, the relevance frame) is induced
once more, then with the held-back success returned and then without the frame. Its outcome is checked against the
status the run recorded, so a world whose replay disagrees is counted, not explained.

Run:  ./venv_lyric/bin/python3 experiments/RULE-AUTHORITY-02/abstentions.py experiments/RULE-AUTHORITY-02/results/<run>_run
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from core.learning.rule_induction import Fact, RuleInducer, TrainingExample  # noqa: E402
from core.learning.unified_learning_system import _bounded_basis, _relevant_frame  # noqa: E402


def examples(world):
    acts, still = [], []
    for k, o in enumerate(world["observations"]):
        action = Fact.parse(o["action"]) if o["action"] else None
        ex = TrainingExample(before=tuple(Fact.parse(f) for f in o["before"]), action=action,
                             after=tuple(Fact.parse(f) for f in o["after"]),
                             positive=action is not None and set(o["after"]) != set(o["before"]),
                             evidence_id=f"o{k}")
        (acts if action else still).append(ex)
    return acts, still


def main():
    run = Path(sys.argv[1])
    scored = json.loads((run / "evaluation.json").read_text())["worlds"]
    final = {a["world"]: a["statuses"][-1] for a in map(json.loads, open(run / "answers.jsonl"))}
    abstained = {w["world"] for w in scored if w["family"] == "conjunction" and w["evidence"] == "determined"
                 and w["successes"] >= 3 and not w["exact"]}
    tally, disagree = Counter(), 0
    for i, line in enumerate(open(run / "worlds_public.jsonl")):
        if i not in abstained:
            continue
        acts, still = examples(json.loads(line))
        basis = list(acts)
        if sum(e.positive for e in basis) >= 3:
            basis.pop(max(j for j, e in enumerate(basis) if e.positive))
        replay = RuleInducer().induce(_relevant_frame(_bounded_basis(basis, still)))
        status = final[i]
        disagree += not (replay.status.value == status
                         or (replay.status.value == "rule_learned" and status.startswith("operator")))
        tally[status] += 1
        if status == "multiple_hypotheses":
            whole = RuleInducer().induce(_relevant_frame(_bounded_basis(acts, still))).status.value
            tally["multiple: the held-back success decides it"] += whole == "rule_learned"
            tally["multiple: a rival needs no act"] += any(c.action is None for c in replay.candidates)
        elif status == "no_rule":
            tally[f"no_rule: without the frame, {RuleInducer().induce(_bounded_basis(basis, still)).status.value}"] += 1
    print(f"{len(abstained)} worlds, replay disagrees with the run in {disagree}")
    for key, n in sorted(tally.items()):
        print(f"  {n:4d}  {key}")


if __name__ == "__main__":
    main()
