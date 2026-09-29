# OPERATOR-REMOVAL-01 — learning to remove a file

**What it tests.** Whether the substrate can learn a removal operator from its own deletions:
- it deletes real files through its own tool path, which watches each act: the self perceives what is
  at the path before and after, and files what happened (`experiments/fs_remove_teach.py` chooses which
  removals to show: ones that work, and ones aimed where the file is not);
- the learning authority induces the rule from what was filed, and it goes into the real rule store;
- the rule is then validated against removals it was not learned from;
- reasoning can plan a removal (a goal that a file no longer be there), and the constitution allows the
  proved removal of a file that injures nobody, while a user's credential is not simply removed.

It matters for governance: until this operator existed, the constitution had no real irreversible act to
judge.

**One check changed with the vocabulary (2026-09-28).** "It did not invent a precondition" expected none
at all, because under `FILE_IN` nothing could contradict an unguarded removal. The self's perception
states each file's `SIZE`, and a rule that takes a size away has to read it from somewhere, so the check
is now "it requires nothing but what it removes": every precondition is a fact the removal deletes.

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/OPERATOR-REMOVAL-01/experiment.py
```

**Results.** Every run is saved in `results/`. Record: `docs/research/BENCHMARKS.md` §2.1. The run
writes to the real rule store.
- 2026-09-16: 18/18, rule `rule_b053f38a9158` (`REMOVE_FILE(?f, ?d) ⊖ FILE_IN(?f, ?d)`) on the
  hand-written filesystem domain, with the removal then redirected (`results/20260916T155819Z.md`).
- 2026-09-28: 22/22 on the derived domain, rule `DELETE_FILE(?X0) ∧ SIZE(?X0, ?X1) ⊖ KIND(?X0, Ffile) ∧
  SIZE(?X0, ?X1)`, validated by 4 removals it was not induced from; the planner proves
  `DELETE_FILE(<the file>)` for the goal that it be gone.
- 2026-09-28, later: 19/22 (`results/20260928T154245Z.md`). The same rule is learned and validated. But after a
  sandbox reset `MOVE_FILE` was taught before `DELETE_FILE`, and the planner tries operators in the order they were
  learned: it proves `MOVE_FILE(<the file>, <its folder>)` for the goal that the file be gone. The learned move
  cannot require a free destination (absence is not perceived), and the tool refuses a move onto an existing
  directory. The constitution finds `delete_file` has no proved route and replans (Law 4). With the rules in the
  other order, the same state and goal give `DELETE_FILE(<the file>)`. Open.
- 2026-09-28, with absence perceived: 19/22 (`results/20260928T163838Z.md`). A move is now learned to need a free
  destination, so moving the file onto its folder is no longer planned. With a free place known, the planner moves
  the file there instead of removing it: "not a file at this path" is what the goal says, and a move satisfies it.
  Open: a removal goal has to be about the file itself, which needs the file's identity to be perceived.
- 2026-09-28, with identity perceived: **22/22** (`results/20260928T173320Z.md`), with MOVE_FILE taught before
  DELETE_FILE, the order that failed. The self perceives which thing is at a path (device, inode, birth time); a
  move keeps it and a delete takes it away. The removal is asked for as the file being gone everywhere
  (`¬IDENTITY(?where, <it>)`), which no move satisfies, so the planner proves `DELETE_FILE(<the file>)`.
