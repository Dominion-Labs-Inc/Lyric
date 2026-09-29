# Teaching Architecture — MERGED INTO `docs/TEACHING.md`

This was a second canonical teaching document, and two canonical documents about
one subject is the same defect the subject itself is about. Its content lives in
[`docs/TEACHING.md`](../TEACHING.md) as of 2026-09-20.

**What moved, and where:**

| was here | now |
|---|---|
| the one teaching path, the fan-out's four stores | §3 |
| sourcing from offline dumps | §7, and `core/learning/teaching_sources.py` |
| the session checklist, detached runs, verify-after-flush | §10 |
| failure modes | §10 |
| **source hygiene — never admit crowd `isa` as reasoning edges** | §9, and now ENFORCED in code by `TeachingPass._guard_reasoning_edges` |

**Two of its rules were themselves defects and did not survive the merge.** It
prescribed backfilling beliefs "via direct `observe_claim`" — which is how the
learning authority came to be bypassed by `teach_conceptnet_beliefs.py` — and it
listed *"Reinforcement on re-teach: 0.9926 → 0.9995"* as a verified reference
number, when that was the double-counting since repaired across 34,774 beliefs.
Both are corrected in §10.

Its `file:line` anchors had also drifted (`learn_fact:2111` is now `:2840`),
which is the cost of a living document nothing runs against. The teaching
pipeline now has experiments that do: `PIPELINE-01`, `POS-01`, `IDEMPOTENT-01`,
`REMEMBER-01`, `ATTEST-01`.
