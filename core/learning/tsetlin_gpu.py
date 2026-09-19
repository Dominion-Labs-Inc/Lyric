#!/usr/bin/env python3
"""Batched Tsetlin Machine — the same clause learner as tsetlin_machine.py, run as
tensor operations so it is fast enough to be real.

The reference machine in tsetlin_machine.py is correct but updates one example at
a time in Python, which is far too slow for image-scale data. This runs the exact
same algorithm -- clause population, polarity, weighted voting, Type I/II Tsetlin
automaton feedback, no gradients, no backprop -- but evaluates and updates a whole
mini-batch at once with tensor math, on the GPU (MPS) when available. The
automaton state is held fixed across a mini-batch and the stochastic include/
exclude moves are ACCUMULATED and applied once per batch: the standard batched-TM
update, algorithmically the same machine, just not one example at a time.

torch is used ONLY as an array library here -- no autograd, no nn.Module, no
gradients. Learning is still automaton feedback over clauses, and the clauses stay
readable.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import torch

from core.learning.tsetlin_machine import TMConfig


def pick_device(prefer: str = "mps") -> torch.device:
    if prefer == "mps" and torch.backends.mps.is_available():
        return torch.device("mps")
    if prefer == "cuda" and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class BatchTsetlinMachine:
    """Multi-class weighted Tsetlin Machine over boolean features, batched.

    Identical semantics to tsetlin_machine.TsetlinMachine; only the execution is
    batched tensor ops. Input X is boolean (n, n_features)."""

    def __init__(self, n_classes: int, n_features: int,
                 config: Optional[TMConfig] = None, device: str = "mps"):
        self.cfg = config or TMConfig()
        self.dev = pick_device(device)
        self.C = int(n_classes)
        self.o = int(n_features)
        self.L = 2 * self.o
        self.m = self.cfg.clauses_per_class
        self.N = self.cfg.n_states
        self.T = float(self.cfg.T)
        self.s = float(self.cfg.s)
        g = torch.Generator().manual_seed(self.cfg.seed)
        ta = torch.randint(self.N, self.N + 1, (self.C, self.m, self.L), generator=g)
        self.ta = ta.to(torch.int32).to(self.dev)
        self.pol = torch.where(torch.arange(self.m) % 2 == 0, 1, -1).to(torch.int32).to(self.dev)
        self.w = torch.ones((self.C, self.m), dtype=torch.int32, device=self.dev)

    def _literals(self, X: torch.Tensor) -> torch.Tensor:
        X = (X > 0).to(torch.int8)
        return torch.cat([X, 1 - X], dim=1)

    def _clause_fired(self, lit: torch.Tensor):
        """lit (B, L) -> fired (B, C, m) incl. vacuous, and include (C, m, L) bool."""
        include = self.ta > self.N
        notlit = (1 - lit).to(torch.int32)
        inc_flat = include.reshape(self.C * self.m, self.L).to(torch.int32)
        violated = notlit @ inc_flat.T                      # (B, C*m)
        fired = (violated == 0).reshape(-1, self.C, self.m)
        return fired, include

    def scores(self, X: np.ndarray) -> torch.Tensor:
        X = torch.as_tensor(X, dtype=torch.int8, device=self.dev)
        lit = self._literals(X)
        fired, include = self._clause_fired(lit)
        empty = ~include.any(-1)                            # (C, m)
        out = fired & (~empty).unsqueeze(0)                 # empty asserts nothing
        weighted = self.pol.view(1, 1, self.m) * self.w.view(1, self.C, self.m)
        return (out.to(torch.int32) * weighted).sum(-1)     # (B, C)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.scores(X).argmax(1).cpu().numpy()

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 1,
            batch: int = 128, progress=None) -> "BatchTsetlinMachine":
        X = torch.as_tensor(X, dtype=torch.int8, device=self.dev)
        y = torch.as_tensor(np.asarray(y), dtype=torch.int64, device=self.dev)
        lit_all = self._literals(X)
        n = X.shape[0]
        for ep in range(epochs):
            perm = torch.randperm(n, device=self.dev)
            for i in range(0, n, batch):
                idx = perm[i:i + batch]
                self._update(lit_all[idx], y[idx])
            if progress:
                progress(ep + 1, epochs)
        return self

    def _update(self, lit: torch.Tensor, y: torch.Tensor) -> None:
        B = lit.shape[0]
        fired_all, include = self._clause_fired(lit)         # (B,C,m), (C,m,L)

        neg = torch.randint(0, self.C - 1, (B,), device=self.dev)
        neg = neg + (neg >= y).to(torch.int64)
        ar = torch.arange(B, device=self.dev)
        b_idx = torch.cat([ar, ar])
        c_idx = torch.cat([y, neg])
        is_tgt = torch.cat([torch.ones(B, dtype=torch.bool, device=self.dev),
                            torch.zeros(B, dtype=torch.bool, device=self.dev)])
        E = 2 * B

        out_ev = fired_all[b_idx, c_idx].to(torch.int32)     # (E, m) vacuous=1
        lit_ev = lit[b_idx].to(torch.int32)                  # (E, L)
        w_ev = self.w[c_idx].to(torch.int32)                 # (E, m)
        include_ev = include[c_idx]                          # (E, m, L) bool

        class_sum = (out_ev * self.pol.view(1, self.m) * w_ev).sum(1)   # (E,)
        v = class_sum.clamp(-self.T, self.T).to(torch.float32)
        p = torch.where(is_tgt, (self.T - v) / (2 * self.T),
                        (self.T + v) / (2 * self.T))         # (E,)
        fb = torch.rand(E, self.m, device=self.dev) < p.view(E, 1)
        type_i = (self.pol.view(1, self.m) == 1) == is_tgt.view(E, 1)
        fired = out_ev.bool()

        present = (lit_ev == 1).view(E, 1, self.L)
        absent = ~present
        r = torch.rand(E, self.m, self.L, device=self.dev)
        thr_inc = (self.s - 1.0) / self.s
        thr_dec = 1.0 / self.s

        ti_fired = (fb & type_i & fired).view(E, self.m, 1)
        ti_notf = (fb & type_i & ~fired).view(E, self.m, 1)
        tii_fired = (fb & ~type_i & fired).view(E, self.m, 1)

        inc = (ti_fired & present & (r <= thr_inc)) | (tii_fired & absent & (~include_ev))
        dec = (ti_fired & absent & (r <= thr_dec)) | (ti_notf & (r <= thr_dec))
        delta = inc.to(torch.int32) - dec.to(torch.int32)    # (E, m, L)

        dw = (fb & type_i & fired).to(torch.int32) - (fb & ~type_i & fired).to(torch.int32)

        self.ta.index_add_(0, c_idx, delta)
        self.w.index_add_(0, c_idx, dw)
        self.ta.clamp_(1, 2 * self.N)
        self.w.clamp_(min=1)

    def clause_literals(self, c: int, j: int, feature_names=None):
        include = (self.ta[c, j] > self.N).cpu().numpy()
        names = feature_names or [f"f{k}" for k in range(self.o)]
        out = []
        for k in np.where(include)[0]:
            out.append(names[k] if k < self.o else f"NOT {names[k - self.o]}")
        return out


import torch.nn.functional as F


class ConvBatchTsetlinMachine(BatchTsetlinMachine):
    """Convolutional Tsetlin Machine, batched on the GPU. Same machine as
    tsetlin_machine.ConvolutionalTsetlinMachine -- clauses evaluated over every
    patch (fire if they match ANY patch), position-encoded, patch-selected
    feedback -- run as batched tensor ops so it reaches image scale."""

    def __init__(self, n_classes, image_shape, patch=(10, 10),
                 config: Optional[TMConfig] = None, device: str = "mps"):
        self.H, self.W, self.B = image_shape
        self.ph, self.pw = patch
        self.py = self.H - self.ph + 1
        self.px = self.W - self.pw + 1
        self.Q = self.py * self.px
        self.Fwin = self.ph * self.pw * self.B
        self.Fpos = (self.py - 1) + (self.px - 1)
        n_features = self.Fwin + self.Fpos
        super().__init__(n_classes, n_features, config, device)
        self._pos = self._position_bits().to(self.dev)       # (Q, Fpos) int8
        # fp16 is exact for the clause-match test: products are 0/1, the sum is
        # monotone non-decreasing, so any true count >=1 stays >=1 (exact up to
        # 2048) and a true 0 stays exactly 0 -- the `== 0` test never flips.
        # ~2x faster matmul on MPS. Falls back to fp32 on CPU where it's slower.
        self._mm = torch.float16 if self.dev.type in ("mps", "cuda") else torch.float32

    def _position_bits(self):
        pos = torch.zeros((self.Q, self.Fpos), dtype=torch.int8)
        for q in range(self.Q):
            r, c = q // self.px, q % self.px
            pos[q, :r] = 1
            pos[q, (self.py - 1):(self.py - 1) + c] = 1
        return pos

    def _patches(self, Xbits: torch.Tensor) -> torch.Tensor:
        """(B,H,W,Bbits) -> (B, Q, 2F) literals."""
        x = Xbits.permute(0, 3, 1, 2).to(torch.float32)      # (B, Bbits, H, W)
        cols = F.unfold(x, kernel_size=(self.ph, self.pw))   # (B, Bbits*ph*pw, Q)
        win = cols.transpose(1, 2).to(torch.int8)            # (B, Q, Fwin)
        pos = self._pos.unsqueeze(0).expand(win.shape[0], -1, -1)
        feat = torch.cat([win, pos], dim=2)                  # (B, Q, F)
        return torch.cat([feat, 1 - feat], dim=2)            # (B, Q, 2F)

    def _to_bits(self, X):
        X = torch.as_tensor(X, device=self.dev)
        if X.dim() == 3:                                     # (n,H,W) -> add bit axis
            X = X.unsqueeze(-1)
        return X.to(torch.int8)

    def scores(self, X):
        patches = self._patches(self._to_bits(X))            # (B,Q,2F)
        B = patches.shape[0]
        include = self.ta > self.N                           # (C,m,2F)
        empty = ~include.any(-1)                             # (C,m)
        notp = (1 - patches).reshape(B * self.Q, self.L).to(self._mm)
        out = torch.empty((B, self.C), dtype=torch.int64, device=self.dev)
        for c in range(self.C):
            violated = notp @ include[c].T.to(self._mm)       # (B*Q, m)
            fired = (violated == 0).reshape(B, self.Q, self.m).any(1)  # (B,m)
            fired = fired & (~empty[c]).unsqueeze(0)
            out[:, c] = (fired.to(torch.int32) * self.pol * self.w[c]).sum(1)
        return out

    def class_support(self, X):
        """Per-class ABSOLUTE support: the fraction of each class's positive-polarity
        clauses that actually fire on the input, in [0,1]. Returns (B, C)."""
        return self.class_evidence(X)[..., 0]

    def class_evidence(self, X):
        """Per-class raw evidence, (B, C, 3): [positive-clause support, negative-clause
        support, weighted vote]. `support` is the fraction of that polarity's clauses
        that fire (in [0,1]); `vote` is the signed weighted sum (same as `scores`).
        Exposes the pieces that a clean known-vs-unknown signal is built from — a
        genuinely recognised input strongly satisfies POSITIVE clauses AND avoids
        NEGATIVE ones, a distinction the collapsed vote/margin cannot see."""
        patches = self._patches(self._to_bits(X))
        B = patches.shape[0]
        include = self.ta > self.N
        empty = ~include.any(-1)
        notp = (1 - patches).reshape(B * self.Q, self.L).to(self._mm)
        pos = (self.pol == 1); neg = ~pos
        npos = int(pos.sum().item()) or 1; nneg = int(neg.sum().item()) or 1
        out = torch.zeros((B, self.C, 3), dtype=torch.float32, device=self.dev)
        for c in range(self.C):
            violated = notp @ include[c].T.to(self._mm)
            fired = (violated == 0).reshape(B, self.Q, self.m).any(1) & (~empty[c]).unsqueeze(0)
            firef = fired.to(torch.float32)
            out[:, c, 0] = (firef * pos.unsqueeze(0)).sum(1) / npos
            out[:, c, 1] = (firef * neg.unsqueeze(0)).sum(1) / nneg
            out[:, c, 2] = (fired.to(torch.int32) * self.pol * self.w[c]).sum(1).to(torch.float32)
        return out

    def clause_pattern(self, X):
        """(B, C*m) int8: the full clause-FIRING SIGNATURE — which clauses fired for
        every class, not how many. The uncertainty-quantification literature identifies
        this pattern as the out-of-distribution signal: a genuine member of a class
        fires that class's characteristic clauses, while structured OOD fires a
        scattered, uncharacteristic combination. The collapsed vote/support scalars
        discard exactly this, which is why they cannot separate structured OOD. This is
        the feature a model-free outlier detector (Isolation Forest / EVM) runs on."""
        patches = self._patches(self._to_bits(X))
        B = patches.shape[0]
        include = self.ta > self.N
        empty = ~include.any(-1)
        notp = (1 - patches).reshape(B * self.Q, self.L).to(self._mm)
        out = torch.zeros((B, self.C, self.m), dtype=torch.int8, device=self.dev)
        for c in range(self.C):
            violated = notp @ include[c].T.to(self._mm)
            fired = (violated == 0).reshape(B, self.Q, self.m).any(1) & (~empty[c]).unsqueeze(0)
            out[:, c] = fired.to(torch.int8)
        return out.reshape(B, self.C * self.m)

    def _evidence_margin(self, X):
        """(ev (n,C,3) numpy, margin (n,) numpy, pred (n,) numpy) — the raw evidence
        plus the relative peakedness of the winning vote. The building blocks of the
        per-class acceptance region."""
        ev = self.class_evidence(X)                          # (n,C,3)
        votes = ev[..., 2]
        pred = votes.argmax(1)
        top2 = torch.topk(votes, min(2, votes.shape[1]), dim=1).values
        gap = top2[:, 0] - (top2[:, 1] if top2.shape[1] > 1 else torch.zeros_like(top2[:, 0]))
        margin = gap / (votes.abs().max(1).values + 1e-6)
        return ev.cpu().numpy(), margin.cpu().numpy(), pred.cpu().numpy()

    def calibrate_abstention(self, X, y, *, target_retention: float = 0.99,
                             ridge: float = 1e-3, min_per_class: int = 8):
        """Fit PER-CLASS acceptance regions so abstention is calibrated to each
        class's OWN distribution of correct recognitions — not a single global
        threshold that costs real capability. For each class c, over the validation
        examples correctly predicted as c, fit the mean and (ridged) covariance of the
        evidence vector [pos_support(c), neg_support(c), vote(c), margin] and store the
        Mahalanobis distance that retains `target_retention` of them. An input whose
        evidence for its predicted class falls outside that class's region is
        abstained; the conformal p-value (fraction of calibration points at least as
        far from the mean) is the calibrated confidence. A class with fewer than
        `min_per_class` correct examples cannot be certified and is left uncalibrated
        — recognitions of it then abstain (honest: no certification, no admission).
        Stored on the model, so it persists with the mechanism. Returns #classes
        calibrated."""
        ev, margin, pred = self._evidence_margin(X)
        y = np.asarray(y)
        self.calibration = {}
        for c in range(self.C):
            mask = (pred == c) & (y == c)
            if int(mask.sum()) < min_per_class:
                continue
            feats = np.stack([ev[mask, c, 0], ev[mask, c, 1],
                              ev[mask, c, 2], margin[mask]], axis=1)   # (nc, 4)
            mu = feats.mean(0)
            cov = np.atleast_2d(np.cov(feats, rowvar=False)) + ridge * np.eye(feats.shape[1])
            # Pseudo-inverse: always defined even if a feature is degenerate for this
            # class (e.g. a class whose winning votes are near-constant), so calibration
            # never fails numerically on a real distribution.
            inv = np.linalg.pinv(cov)
            diff = feats - mu
            d = np.sqrt(np.maximum(0.0, np.einsum('ij,jk,ik->i', diff, inv, diff)))
            self.calibration[c] = {
                "mu": mu, "inv": inv,
                "d_sorted": np.sort(d),
                "thresh": float(np.quantile(d, target_retention))}
        return len(self.calibration)

    def calibrated_decision(self, X):
        """Per-input (pred_class, confidence, accepted) using the per-class regions
        from `calibrate_abstention`. confidence is the conformal p-value in [0,1]
        (1 = as central as the most typical calibration example); accepted is whether
        the input lies within its predicted class's calibrated region. An uncalibrated
        predicted class yields (c, 0.0, False) — abstain, never a blind admit."""
        cal = getattr(self, "calibration", None)
        if not cal:
            raise RuntimeError("classifier is not calibrated; call calibrate_abstention first")
        ev, margin, pred = self._evidence_margin(X)
        out = []
        for i in range(pred.shape[0]):
            c = int(pred[i])
            region = cal.get(c)
            if region is None:
                out.append((c, 0.0, False)); continue
            feat = np.array([ev[i, c, 0], ev[i, c, 1], ev[i, c, 2], margin[i]])
            diff = feat - region["mu"]
            d = float(np.sqrt(max(0.0, diff @ region["inv"] @ diff)))
            ds = region["d_sorted"]
            pval = float((ds >= d).mean())              # conformal: how central within the region
            out.append((c, pval, d <= region["thresh"]))
        return out

    def fit(self, X, y, epochs=1, batch=64, progress=None):
        Xbits = self._to_bits(X)
        y = torch.as_tensor(np.asarray(y), dtype=torch.int64, device=self.dev)
        n = Xbits.shape[0]
        for ep in range(epochs):
            perm = torch.randperm(n, device=self.dev)
            for i in range(0, n, batch):
                idx = perm[i:i + batch]
                self._update_conv(self._patches(Xbits[idx]), y[idx])
            if progress:
                progress(ep + 1, epochs)
        return self

    def _update_conv(self, patches, y):
        B = patches.shape[0]
        include = self.ta > self.N                           # (C,m,2F)
        neg = torch.randint(0, self.C - 1, (B,), device=self.dev)
        neg = neg + (neg >= y).to(torch.int64)
        notp = (1 - patches).reshape(B * self.Q, self.L).to(self._mm)
        ar = torch.arange(B, device=self.dev)

        for c in range(self.C):
            violated = notp @ include[c].T.to(self._mm)
            matches = (violated == 0).reshape(B, self.Q, self.m)   # (B,Q,m) vacuous=1
            fired_c = matches.any(1)                               # (B,m)
            ev_tgt = (y == c)
            ev_neg = (neg == c)
            if not (ev_tgt.any() or ev_neg.any()):
                continue
            # random matching-patch selection per (example, clause)
            rnd = torch.rand(B, self.Q, self.m, device=self.dev)
            rnd = torch.where(matches, rnd, torch.full_like(rnd, -1.0))
            sel_q = rnd.argmax(1)                                  # (B,m)
            sel_lit = patches[ar.unsqueeze(1), sel_q].to(torch.int32)  # (B,m,2F)

            b_idx = torch.cat([ar[ev_tgt], ar[ev_neg]])
            is_tgt = torch.cat([torch.ones(int(ev_tgt.sum()), dtype=torch.bool, device=self.dev),
                                torch.zeros(int(ev_neg.sum()), dtype=torch.bool, device=self.dev)])
            if b_idx.numel() == 0:
                continue
            self._feedback_class(c, b_idx, is_tgt, fired_c, sel_lit, include[c])

    def _feedback_class(self, c, b_idx, is_tgt, fired_c, sel_lit, include_c):
        E = b_idx.shape[0]
        out_ev = fired_c[b_idx].to(torch.int32)              # (E, m) vacuous=1
        lit_ev = sel_lit[b_idx]                              # (E, m, 2F)
        class_sum = (out_ev * self.pol * self.w[c]).sum(1)   # (E,)
        v = class_sum.clamp(-self.T, self.T).to(torch.float32)
        p = torch.where(is_tgt, (self.T - v) / (2 * self.T), (self.T + v) / (2 * self.T))
        fb = torch.rand(E, self.m, device=self.dev) < p.view(E, 1)
        type_i = (self.pol.view(1, self.m) == 1) == is_tgt.view(E, 1)
        fired = out_ev.bool()

        present = (lit_ev == 1)                              # (E, m, 2F)
        absent = ~present
        r = torch.rand(E, self.m, self.L, device=self.dev)
        thr_inc = (self.s - 1.0) / self.s
        thr_dec = 1.0 / self.s
        ti_fired = (fb & type_i & fired).unsqueeze(-1)
        ti_notf = (fb & type_i & ~fired).unsqueeze(-1)
        tii_fired = (fb & ~type_i & fired).unsqueeze(-1)
        inc = (ti_fired & present & (r <= thr_inc)) | \
              (tii_fired & absent & (~include_c.unsqueeze(0)))
        dec = (ti_fired & absent & (r <= thr_dec)) | (ti_notf & (r <= thr_dec))
        delta = (inc.to(torch.int32) - dec.to(torch.int32)).sum(0)   # (m, 2F)
        dw = ((fb & type_i & fired).to(torch.int32)
              - (fb & ~type_i & fired).to(torch.int32)).sum(0)       # (m,)
        self.ta[c] = (self.ta[c] + delta).clamp(1, 2 * self.N)
        self.w[c] = (self.w[c] + dw).clamp(min=1)
