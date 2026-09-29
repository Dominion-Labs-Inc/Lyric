# GATE-01 — the constitution is the live gate, and it holds under pressure

**What it tests.** Everything before this judged acts the constitution was *shown*. This judges acts the
substrate actually makes: every check goes through `tool_registry.execute_tool`, the single point every
tool call in the system passes through. Nothing calls `judge` directly except where the README says so.

That was the open item behind "capability 1 is not done". The absorption benchmark (BENCHMARKS §1.3)
measured parity with the gate being replaced — 0 regressions, 6 gains — by calling `constitution.judge(...)`
itself. **Parity is a licence to swap a gate; it is not evidence the gate works where it runs.** The input
screen in particular had never once run inside a real tool execution.

**Being refused is not the claim.** The claim is that the act did not *happen*, so every refusal is checked
against the world: the file is not on disk, the directory is untouched. A gate that returns a refusal while
the side effect lands is worse than no gate — it reports success at stopping something it did not stop.

## Sections

| Section | What it establishes |
|---|---|
| A · it IS the gate | tripwires on the retired security systems record **0 consultations** during real tool calls; one constitution; the allowed act hands its reading back |
| B · refuses, nothing runs | keylogger / reverse shell / cron persistence — refused, and **no artifact on disk** |
| C · what the laws allow | looking is never refused for want of a reason; a real read reaches the ledger (so the law it enforces can be satisfied); a change with **no intent behind it is replanned** |
| D · fails CLOSED | constitution unreachable → refused; judging breaks mid-flight → BLOCK Law 5; an argument that cannot be read → BLOCK Law 3. Nothing written in any case |
| E · cannot be talked around | authority-claiming prose inside the payload; an intent id in the *arguments*; a forged intent; **concurrent acts under different intents**; path escapes (plain, URL-encoded, double-encoded); SQL, including in a nested argument |
| F · intent at the gate | the real drive path moves a file through the gate, and the act **names the intent reasoning recorded** — the gate sees *why*, not just what |
| G · cost | judging every act |

**Run** (from the Lyric folder):

```
./venv_lyric/bin/python3 experiments/GATE-01/experiment.py
```

**Results.** Every run is saved in `results/` (JSON + `.md`). Latest: 2026-09-17, **25/25**
(`results/20260917T055313Z.md`), stable across consecutive runs. Gate cost: **~0.01 ms/act**.

**2026-09-28: 25/25.** The hand-written filesystem domain was deleted. This now plans over an operator the substrate learned from its own acts in `tools:path` (taught by `experiments/fs_move_teach.py` if the store has none), and states its goal in perception's words: `KIND(<path>, Ffile)`, and `¬KIND(...)` for "no longer there".

## What wiring the gate exposed

Two defects that could only appear once the constitution governed real acts:

1. **A refusal was being recorded as evidence against the rule.** The gate refused a move, the world
   therefore did not change, and `verify_effects` read that as the *operator* being wrong — refuting
   `rule_399de8f89089`, a validated MOVE_FILE operator four experiments plan over, in a single call. The
   substrate punished its own knowledge for its own law's refusal. A refusal now returns through the same
   door as every other authority failure: nothing observed, nothing recorded, rule untouched.
2. **The reading ledger was written on one path only.** `_note_file_account` was called from
   `_execute_operation` and nowhere else, so the substrate's own proved work recorded nothing it read or
   wrote — and Law 2, which refuses an act on a file with no current reading, could never be satisfied by
   the drive path. The ledger update now lives on the constitution (which owns it) and is called at the
   single point every act passes: **judged before, noted after.**

And one inconsistency inside the constitution: **Law 4 did not exempt investigate-class acts**, so a
reading taken to satisfy Law 2 was replanned for "not being the proved act" — one law refusing the act the
other law requires. Law 2's transparency test already carried that exemption; Law 4 now does too.

## What the laws mean on the live path

- **An act is permitted when it IS the act reasoning proved** (Law 4), or when it is investigate-class.
  There is no learned `WRITE_FILE` operator bound to a tool, so the substrate cannot write files outside a
  proved route. What it may do grows by learning operators — which is the point, not a limitation to work
  around.
- **Looking needs no intent.** Reading is how an account is established, so Law 2 exempts it; otherwise
  nothing could ever satisfy the law that requires having read.
- **A redirect is only reachable for a proved act.** An unexplained irreversible removal is stopped by
  Law 2 before Law 3 is ever asked whether a recoverable form exists.

## What is real here, and what is not

Real: the constitution, the tool registry, the intent authority, the planning engine, the rule store, the
binding registry, real tools acting on real files, real Postgres. Refusals are checked against the
filesystem, not against the gate's own report.

Three substitutions, all observational or deliberate fault injection, each stated where it is used:

- **tripwires** on the retired security systems — the real accessors are kept and called through; this only
  records that they were reached.
- `get_constitution` and `_consequence` are made to raise, to prove the gate fails closed. Both are
  restored immediately.
- Three checks call `judge_act` directly rather than `execute_tool`: an `intent_id` in the arguments, a
  self-referential argument, and a nested SQL value. None is a valid parameter of any tool, so through
  `execute_tool` they would be rejected by parameter validation before the gate and would prove nothing
  about it. The README says so rather than letting the run imply otherwise.
