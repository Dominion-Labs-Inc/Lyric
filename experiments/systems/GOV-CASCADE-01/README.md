# GOV-CASCADE-01 — Does one injected error contaminate authority over derivation depth?

*A systems experiment on the live substrate. It is the empirical counterpart of
the non-autonomous-escalation separation (Proposition 7(ii)): under the governed
discipline an injected error stays contained as the chain deepens; under uniform
auto-materialisation it compounds.*

## Question

Proposition 7 says an internal error can propagate arbitrarily within the soft
tier yet cannot, by derivation alone, cross into authority — crossing requires a
fresh, independent promotion. The uniform variant, which treats every derivation
as authoritative, has no such bound: one error is a valid basis for the next, and
authoritative errors compound without limit.

This measures that difference on the running substrate. A chain of conclusions is
derived from a single unsupported (false) root C0: each C_i is derived from
C_{i-1}, so every conclusion traces to that one root — it shares C0's causal
lineage and carries no support independent of it. We then count how many chain
conclusions reach **authoritative** confidence (posterior ≥ the 0.95 acceptance
bar) as the chain deepens, toggling only the independence discipline.

Everything runs through the coordinator: the belief store
(`system.autonomous_coordinator.learning.create_belief / update_belief /
get_belief`) and the coordinator's own independence collapse
(`_independent_groundings`, the Evidence model — the same rule measured in the
paper's correlated-evidence table). Model-free by construction; no inference is
invoked. The posteriors are the substrate's, read back after each update.

## Method

- **SEG** — confirmations that share a causal lineage collapse to their strongest
  before compounding, so a conclusion supported only by the (correlated) chain
  gets exactly one grounding no matter how deep the chain.
- **UNIFORM** — each derivation is counted as an independent confirmation, so the
  chain compounds.

At depth *i*, conclusion C_i has accumulated *i* mutually-correlated confirmations
from the chain rooted at C0. contamination(k) = number of chain conclusions that
are authoritative at depth ≤ k.

## Result

Acceptance bar 0.95; chain depth 6; each confirmation strength 0.9.

| depth | SEG posterior | SEG groundings | SEG auth? | UNIFORM posterior | UNIFORM groundings | UNIFORM auth? |
|---|---|---|---|---|---|---|
| 1 | 0.7242 | 1 | no | 0.7242 | 1 | no |
| 2 | 0.7242 | 1 | no | 0.9750 | 2 | **yes** |
| 3 | 0.7242 | 1 | no | 0.9983 | 3 | **yes** |
| 4 | 0.7242 | 1 | no | 0.9999 | 4 | **yes** |
| 5 | 0.7242 | 1 | no | 1.0000 | 5 | **yes** |
| 6 | 0.7242 | 1 | no | 1.0000 | 6 | **yes** |

**Contamination by depth**
```
SEG      : [0, 0, 0, 0, 0, 0]     authoritative conclusions total: 0
UNIFORM  : [0, 1, 2, 3, 4, 5]     authoritative conclusions total: 5
```

Under SEG the injected error contaminates authority not at all: every conclusion
in the chain collapses to a single grounding and holds at 0.724, below the bar,
however deep the chain runs. Under uniform the identical chain compounds past the
bar from depth 2 and contaminates authority linearly with derivation depth. The
per-step posteriors (0.724 single grounding, 0.975 / 0.998 / → 1.0 compounding)
are the same figures the correlated-evidence table reports; the new content here
is the contamination **trajectory**.

## What this does NOT establish

- **This is the belief-tier realisation.** "Authoritative" is operationalised as
  posterior ≥ the 0.95 acceptance bar and "contained" as below it. It measures the
  independence-collapse discipline — the one rule behind the correlated-evidence
  table — acting over a chain, not a second mechanism.
- **The chain is a controlled construction.** Each conclusion is supported only by
  the correlated chain rooted at C0, which is what isolates the propagation
  question. It is not a full multi-rule forward-chaining cascade over the
  authoritative concept graph; that larger realisation is future work.
- **UNIFORM is the counterfactual** (independence off), not a second real mode of
  the substrate.
- The linear growth is over a depth-6 chain; the point is the qualitative
  separation (flat 0 vs. rising) and that both agree at depth 1, not the slope.

## Method (run)

```
PYTHONPATH="$PWD" POSTGRES_PORT=5433 POSTGRES_USER=stefan LYRIC_NO_WATCHDOG=1 \
  ./venv_lyric/bin/python3 experiments/systems/GOV-CASCADE-01/experiment.py
```

Add-only and self-cleaning: it writes beliefs in a scratch domain (`gov_cascade`)
and deletes them afterward; it never touches production beliefs. Results are
written to `manifest.json`.
