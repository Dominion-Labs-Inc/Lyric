# Research Findings — Model-Free OOD Abstention for a Tsetlin Classifier

**Date:** 2026-09-09 · **Scope:** model-free (no neural net, no LLM). Aligned toward the
SBIR "knows-when-it-doesn't-know / authoritative-state-integrity" thesis, but this is a
research record, not a proposal. Empirical arc logged in
[`LAB_NOTEBOOK.md`](LAB_NOTEBOOK.md) (2026-09-08–09).

## 1. Problem

A perceptual learner that becomes a substrate faculty must **refuse to admit unsupported
input as authoritative knowledge** — abstain on out-of-distribution (OOD) input rather than
confidently invent a category. The hard case is not random noise but *structured* OOD:
real images of other categories that partially match learned patterns. Requirement:
abstention must cost **no real capability** — genuine in-distribution (ID) recognitions must
not be thrown away to reject OOD.

## 2. What we established empirically (Tsetlin CTM, MNIST vs FashionMNIST)

Base model: model-free Convolutional Tsetlin Machine, 98.2% MNIST, no backprop.

| Method (all model-free) | FashionMNIST admitted @95% ID retention | Noise |
|---|--:|--:|
| Vote margin (relative) | ~ leaks | rejects |
| Absolute clause support | worse than margin (0.225 vs 0.150 balanced err) | — |
| **4-scalar per-class Mahalanobis** | 23.2% | 0% |
| Full clause pattern + Isolation Forest | 35.4% (IF underpowered in 4000-dim) | 0% |
| **Clause pattern → PCA → per-class Mahalanobis** | **12.5%** (best) | 0% |

**Findings.** (a) Random noise is trivially rejected by almost anything (absolute vote/
support collapses). (b) The **clause-firing pattern carries the OOD signal** (confirmed:
PCA→Mahalanobis on it beats the 4 scalars *and* raw Isolation Forest, with higher ID
retention). (c) But post-hoc score/pattern analysis **plateaus at ~12% structured-OOD leak
at 96% ID retention** — more PCA components stop helping past ~100. Digit and shirt *clause
patterns genuinely overlap*; no post-hoc reading of a trained CTM removes that residual.
(d) Corollary: the Tsetlin family is naturally better-behaved than neural nets here — it is
*less* confident off-distribution rather than overconfident (see §3).

## 3. Literature landscape (model-free methods)

**Tsetlin-native uncertainty.** The **Probabilistic Tsetlin Machine** (PTM,
[arXiv:2410.17851](https://arxiv.org/abs/2410.17851)) replaces each automaton's single state
with a *state-probability vector* updated by transition-probability matrices; K-sample
inference yields predictive entropy / mutual information. It is well-calibrated (ECE ~0.01)
and, unlike ANNs, **less confident outside the training domain** — native OOD awareness, no
neural net. "**Uncertainty Quantification in the Tsetlin Machine**"
([arXiv:2507.04175](https://arxiv.org/pdf/2507.04175)) identifies the **clause-activation
pattern** (and the class-sum = positive-minus-negative matching clauses) as the uncertainty
signal — which is exactly what our §2 result exploits and confirms.

**Conformal prediction (CP) — the principled, distribution-free abstention framework.**
CP is **model-agnostic**: it works on *any* nonconformity score (a distance, an SVM margin,
a vote count — no probabilities needed). Inductive CP / **Inductive Conformal Anomaly
Detection** splits data into proper-train + **calibration**; the only design choice is the
nonconformity measure (NCM). For a target level ε, the cutoff is the ⌈(h+1)(1−ε)⌉-th sorted
calibration score. Crucially, in the reject-option form
([arXiv:2506.21802](https://arxiv.org/abs/2506.21802)), a test point's prediction set is:
- **empty ⇒ novelty rejection** (no label conforms — *this is the OOD/"I don't know" case*),
- **singleton ⇒ accept** (one confident label),
- **double ⇒ ambiguity rejection** (near a boundary).

The guarantee is **distribution-free**: choosing ε controls the error/rejection rate with no
assumptions on the data-generating process. "OOD detection should use conformal prediction"
([arXiv:2403.11532](https://arxiv.org/abs/2403.11532)) argues this pairing directly.

**Reject-option theory.** Chow's rule (1957/1970) is the classical optimum (a confidence
threshold minimizing risk), but assumes known class distributions; the modern, assumption-
free successor is exactly CP / partial rejection (survey:
[arXiv:2107.11277](https://arxiv.org/html/2107.11277v3)).

**Classical outlier detectors** (feature-vector inputs): Isolation Forest (fast, but weak in
very high dimension — our §2 finding), One-Class SVM (RBF; scales poorly), Kernel Density,
and the **Extreme Value Machine** ([arXiv:1808.09902](https://arxiv.org/pdf/1808.09902)) —
per-class Weibull tails, kernel-free, **incremental** (fits an online substrate).

## 4. Synthesis — the recommended model-free architecture

**Inductive conformal prediction with a Tsetlin nonconformity measure.**
- **NCM (now):** the per-class Mahalanobis distance on the PCA-reduced clause-firing pattern
  (our best measured signal). **NCM (stronger, later):** PTM predictive entropy / mutual
  information — native, calibrated.
- **Calibrate** the NCM's cutoff on a held-out ID calibration set at level ε.
- **Decide** per input: empty set → **abstain (OOD)**; singleton → **admit** with the
  conformal p-value as a *calibrated* confidence; double → **abstain (ambiguous)**.

Why this is the right answer to "no capability loss": CP makes **ID retention a distribution-
free guarantee** — set ε = 0.01 and *provably* ≤1% of genuine inputs are rejected, whatever
the distribution. That is the rigorous form of "don't throw away real capability." It also
replaces our ad-hoc percentile thresholds with a principled, single-knob, calibrated rule,
and unifies novelty (empty) and ambiguity (double) rejection.

**Honest boundary.** CP does **not** lower the ~12% structured-OOD leak on its own — the leak
is bounded by the NCM's discriminative power, and the clause-pattern NCM plateaus there.
CP guarantees the *ID side* (capability) and calibrates the confidence; reducing the OOD leak
requires a **stronger NCM**: (a) PTM native uncertainty, or (b) an explicit **reject class**
(supervised "not-a-digit" boundary — pragmatic, open-set-limited), or (c) richer clause
features / coalesced TM.

## 5. Novelty & relevance

The searches surfaced **no published work combining a Tsetlin Machine with conformal
prediction or open-set/reject-option OOD**. Building conformal, distribution-free abstention
on a Tsetlin nonconformity measure therefore appears to be a **genuine, defensible research
contribution**: interpretable + model-free + *provable* calibration of "knows when it doesn't
know." This maps directly onto the SBIR evaluation axes (Epistemic Calibration, Authoritative-
State Integrity) and the DoD "assured/trusted autonomy" language.

## 6. Next experiments (in order)

1. **Wrap the current best NCM in inductive CP** — clause-pattern PCA-Mahalanobis distance as
   the nonconformity score; verify the empty-set rejection rate matches the target ε on MNIST
   (guaranteed ID retention) and measure FashionMNIST rejection. Cheap (cached model +
   patterns: `scratchpad/ood_model.pt`, `ood_patterns.npz`).
2. **Strengthen the NCM.** Prototype PTM predictive-entropy as the nonconformity measure and
   compare its FashionMNIST rejection to the clause-pattern NCM under the same CP guarantee.
3. **Reject-class baseline** for reference (train on non-digit images) — quantifies the gap
   between open-set post-hoc and supervised-boundary rejection.

## Sources
- Probabilistic Tsetlin Machine — [arXiv:2410.17851](https://arxiv.org/abs/2410.17851)
- Uncertainty Quantification in the Tsetlin Machine — [arXiv:2507.04175](https://arxiv.org/pdf/2507.04175)
- Classification with Reject Option via Conformal Prediction — [arXiv:2506.21802](https://arxiv.org/abs/2506.21802)
- OOD Detection Should Use Conformal Prediction — [arXiv:2403.11532](https://arxiv.org/abs/2403.11532)
- Machine Learning with a Reject Option: A Survey — [arXiv:2107.11277](https://arxiv.org/html/2107.11277v3)
- Extreme Value Machine (open-set, EVT) — [arXiv:1808.09902](https://arxiv.org/pdf/1808.09902)
