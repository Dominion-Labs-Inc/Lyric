#!/usr/bin/env python3
"""A Tsetlin Machine: the substrate's clause learner, scaled up.

The substrate already learns a SINGLE conjunctive clause per category by
anti-unification (`induce_category`). That is the right family and the wrong
scale: one conjunction cannot represent a concept that is a DISJUNCTION of
conditions (XOR, "a red circle OR a blue square"), and it does not improve with
more data. A Tsetlin Machine keeps the clause -- a conjunction of literals over a
boolean input -- but learns a POPULATION of them, half arguing FOR a class and
half AGAINST, each with a WEIGHT, and classifies by their VOTE. It is trained not
by gradient descent but by Tsetlin automata: each literal in each clause is a
small finite-state machine that is rewarded toward INCLUDE or EXCLUDE by two
feedback rules. No backpropagation, no matrix calculus, pure code -- and the
learned clauses remain readable, so the machine can still say WHY.

This is the same epistemic object the substrate already reasons over -- a clause
-- learned at a scale that reaches real classification, while staying legible and
able to abstain when the vote is not decisive.

Reference: O.-C. Granmo, "The Tsetlin Machine" (2018); weighted clauses after
Phoulady et al. This is an independent numpy implementation, not a wrapper.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np


@dataclass
class TMConfig:
    clauses_per_class: int = 100     # more clauses -> more capacity
    T: int = 15                      # vote margin target; shapes feedback pressure
    s: float = 3.9                   # specificity; higher -> finer, sparser clauses
    n_states: int = 100             # automaton depth per literal (include if > n_states)
    weighted: bool = True            # clauses carry an integer vote weight
    seed: int = 0


class TsetlinMachine:
    """Multi-class weighted Tsetlin Machine over boolean features.

    Input X is a boolean matrix (n_examples, n_features). Internally each feature
    contributes two LITERALS -- itself and its negation -- so a clause can require
    a feature to be present OR absent. Each class owns `clauses_per_class` clauses,
    alternating polarity (+ argues for the class, - argues against); the class
    score is the weighted vote, and the prediction is the highest-scoring class.
    """

    def __init__(self, n_classes: int, n_features: int,
                 config: Optional[TMConfig] = None):
        self.cfg = config or TMConfig()
        self.C = int(n_classes)
        self.o = int(n_features)
        self.L = 2 * self.o
        self.m = self.cfg.clauses_per_class
        self.N = self.cfg.n_states
        self.rng = np.random.default_rng(self.cfg.seed)
        # Tsetlin automaton state per (class, clause, literal), in [1, 2N].
        # A literal is INCLUDED in a clause when its state exceeds N. Initialised
        # just below the boundary so clauses start empty and grow by evidence.
        self.ta = self.rng.integers(self.N, self.N + 1,
                                    size=(self.C, self.m, self.L)).astype(np.int32)
        # Clause polarity: even clauses vote FOR the class, odd vote AGAINST.
        self.pol = np.where(np.arange(self.m) % 2 == 0, 1, -1).astype(np.int32)
        self.w = np.ones((self.C, self.m), dtype=np.int32)

    # -- literals & clause evaluation --------------------------------------

    def _literals(self, X: np.ndarray) -> np.ndarray:
        X = (np.asarray(X) > 0).astype(np.int8)
        return np.concatenate([X, 1 - X], axis=1)   # (n, 2o)

    def _clause_outputs(self, ta_c: np.ndarray, lit: np.ndarray):
        """Outputs of one class's clauses on one literal vector.

        A clause fires (output 1) iff every literal it INCLUDES is 1. A clause
        that includes nothing is vacuously true. Returns (outputs, include mask,
        empty mask)."""
        include = ta_c > self.N                     # (m, L)
        violated = (include & (lit == 0)).any(axis=1)
        empty = ~include.any(axis=1)
        out = (~violated).astype(np.int8)           # vacuous-true when empty
        return out, include, empty

    def _class_scores(self, lit: np.ndarray, eval_mode: bool) -> np.ndarray:
        scores = np.zeros(self.C, dtype=np.int64)
        for c in range(self.C):
            out, _, empty = self._clause_outputs(self.ta[c], lit)
            if eval_mode:
                out = out.copy(); out[empty] = 0     # an empty clause asserts nothing
            scores[c] = int(np.sum(self.pol * self.w[c] * out))
        return scores

    # -- inference ---------------------------------------------------------

    def scores(self, X: np.ndarray) -> np.ndarray:
        lit = self._literals(X)
        return np.stack([self._class_scores(lit[i], eval_mode=True)
                         for i in range(lit.shape[0])])

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.argmax(self.scores(X), axis=1)

    def predict_with_abstention(self, X: np.ndarray, margin: int = 1):
        """Predict, but return -1 (abstain) when the top two class votes are
        within `margin` -- the honest 'I am not sure' the substrate keeps."""
        S = self.scores(X)
        order = np.argsort(-S, axis=1)
        top = order[:, 0]
        gap = S[np.arange(len(S)), order[:, 0]] - S[np.arange(len(S)), order[:, 1]]
        return np.where(gap >= margin, top, -1)

    # -- training ----------------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 1,
            progress=None) -> "TsetlinMachine":
        lit_all = self._literals(X)
        y = np.asarray(y).astype(int)
        n = X.shape[0]
        for ep in range(epochs):
            for idx in self.rng.permutation(n):
                lit = lit_all[idx]
                target = y[idx]
                self._feedback(target, lit, target_class=True)
                neg = int(self.rng.integers(self.C - 1))
                if neg >= target:
                    neg += 1
                self._feedback(neg, lit, target_class=False)
            if progress:
                progress(ep + 1, epochs)
        return self

    def _feedback(self, c: int, lit: np.ndarray, target_class: bool) -> None:
        out, include, empty = self._clause_outputs(self.ta[c], lit)
        out_train = out.copy(); out_train[empty] = 1
        class_sum = int(np.sum(self.pol * self.w[c] * out_train))
        v = np.clip(class_sum, -self.cfg.T, self.cfg.T)
        if target_class:
            p = (self.cfg.T - v) / (2 * self.cfg.T)
        else:
            p = (self.cfg.T + v) / (2 * self.cfg.T)
        chosen = np.where(self.rng.random(self.m) < p)[0]
        for j in chosen:
            positive_clause = self.pol[j] == 1
            # Type I reinforces clauses that should recognise the class; Type II
            # makes clauses that should NOT fire more discriminative.
            type_i = positive_clause == target_class
            if type_i:
                self._type_i(c, j, lit, int(out_train[j]))
            else:
                self._type_ii(c, j, lit, int(out_train[j]), include[j])

    def _type_i(self, c: int, j: int, lit: np.ndarray, cout: int) -> None:
        ta = self.ta[c, j]
        s = self.cfg.s
        r = self.rng.random(self.L)
        if cout == 1:
            if self.cfg.weighted:
                self.w[c, j] += 1
            inc = (lit == 1) & (r <= (s - 1) / s)      # present literal -> include
            dec = (lit == 0) & (r <= 1.0 / s)          # absent literal -> forget
            ta[inc] = np.minimum(ta[inc] + 1, 2 * self.N)
            ta[dec] = np.maximum(ta[dec] - 1, 1)
        else:
            dec = r <= 1.0 / s                          # clause missed -> forget
            ta[dec] = np.maximum(ta[dec] - 1, 1)

    def _type_ii(self, c: int, j: int, lit: np.ndarray, cout: int,
                 include: np.ndarray) -> None:
        if cout != 1:
            return
        if self.cfg.weighted and self.w[c, j] > 1:
            self.w[c, j] -= 1
        # Include a literal that is 0 and currently excluded, so this clause stops
        # firing on this (wrong) pattern -- the discriminative move.
        add = (lit == 0) & (~include)
        ta = self.ta[c, j]
        ta[add] = np.minimum(ta[add] + 1, 2 * self.N)

    # -- interpretability --------------------------------------------------

    def clause_literals(self, c: int, j: int, feature_names=None) -> List[str]:
        """The literals clause j of class c INCLUDES -- a readable conjunction."""
        include = self.ta[c, j] > self.N
        names = feature_names or [f"f{k}" for k in range(self.o)]
        out = []
        for k in np.where(include)[0]:
            if k < self.o:
                out.append(names[k])
            else:
                out.append(f"NOT {names[k - self.o]}")
        return out


# --- Convolutional Tsetlin Machine ---------------------------------------

def booleanize(images: np.ndarray, thresholds=(0.33, 0.66)) -> np.ndarray:
    """Turn float images into boolean bit-planes by thermometer encoding.

    images: (n, H, W) or (n, H, W, ch), values in [0, 1]. Each channel becomes
    len(thresholds) bit-planes (1 where intensity exceeds each threshold), so a
    clause can require "this pixel is at least this bright". Returns (n, H, W, B).
    """
    x = np.asarray(images, dtype=np.float32)
    if x.ndim == 3:
        x = x[..., None]
    planes = [(x >= t).astype(np.int8) for t in thresholds]      # each (n,H,W,ch)
    stacked = np.concatenate(planes, axis=-1)                    # (n,H,W,ch*T)
    return stacked


class ConvolutionalTsetlinMachine(TsetlinMachine):
    """A Tsetlin Machine whose clauses are CONVOLUTIONAL: each clause is evaluated
    on every patch of the image and fires if it matches ANY patch, giving
    translation invariance -- a clause learns a local pattern once and detects it
    wherever it appears. Feedback is applied on a patch the clause actually
    matched. Everything else -- polarity, weighted voting, Type I/II automaton
    feedback, abstention, readable clauses -- is inherited unchanged.
    """

    def __init__(self, n_classes: int, image_shape: Tuple[int, int, int],
                 patch: Tuple[int, int] = (10, 10),
                 config: Optional[TMConfig] = None):
        self.H, self.W, self.B = image_shape
        self.ph, self.pw = patch
        self.py = self.H - self.ph + 1               # patch rows
        self.px = self.W - self.pw + 1               # patch cols
        self.Q = self.py * self.px
        self.Fwin = self.ph * self.pw * self.B
        self.Fpos = (self.py - 1) + (self.px - 1)    # position thermometer
        n_features = self.Fwin + self.Fpos
        super().__init__(n_classes, n_features, config)
        self._pos = self._position_bits()            # (Q, Fpos)

    def _position_bits(self) -> np.ndarray:
        pos = np.zeros((self.Q, self.Fpos), dtype=np.int8)
        q = 0
        for r in range(self.py):
            for c in range(self.px):
                pos[q, :r] = 1                                   # y thermometer
                pos[q, (self.py - 1):(self.py - 1) + c] = 1      # x thermometer
                q += 1
        return pos

    def _patch_literals(self, img_bits: np.ndarray) -> np.ndarray:
        """One image (H,W,B) -> (Q, 2F) literals for all patches."""
        from numpy.lib.stride_tricks import sliding_window_view
        win = sliding_window_view(img_bits, (self.ph, self.pw), axis=(0, 1))
        # win: (py, px, B, ph, pw) -> (Q, Fwin)
        win = win.transpose(0, 1, 3, 4, 2).reshape(self.Q, self.Fwin)
        feat = np.concatenate([win, self._pos], axis=1)          # (Q, F)
        return np.concatenate([feat, 1 - feat], axis=1).astype(np.int8)  # (Q, 2F)

    def _clause_match(self, ta_c: np.ndarray, patch_lit: np.ndarray):
        """(m,) fired, and (m,Q) per-patch match mask, for one class."""
        include = (ta_c > self.N).astype(np.int32)               # (m, 2F)
        notlit = (1 - patch_lit).astype(np.int32)                # (Q, 2F)
        violated = include @ notlit.T                            # (m, Q)
        matches = violated == 0                                  # (m, Q)
        fired = matches.any(axis=1)
        return fired, matches

    def scores(self, X: np.ndarray) -> np.ndarray:
        Xb = booleanize(X) if X.ndim == 3 or (X.ndim == 4 and X.shape[-1] not in (self.B,)) else np.asarray(X)
        out = np.zeros((Xb.shape[0], self.C), dtype=np.int64)
        for i in range(Xb.shape[0]):
            pl = self._patch_literals(Xb[i])
            for c in range(self.C):
                include = self.ta[c] > self.N
                empty = ~include.any(axis=1)
                fired, _ = self._clause_match(self.ta[c], pl)
                fired = fired.copy(); fired[empty] = False        # eval: empty asserts nothing
                out[i, c] = int(np.sum(self.pol * self.w[c] * fired))
        return out

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 1, progress=None):
        Xb = booleanize(X) if X.ndim == 3 else np.asarray(X)
        y = np.asarray(y).astype(int)
        n = Xb.shape[0]
        for ep in range(epochs):
            for idx in self.rng.permutation(n):
                pl = self._patch_literals(Xb[idx])
                self._feedback_conv(int(y[idx]), pl, target_class=True)
                neg = int(self.rng.integers(self.C - 1))
                if neg >= y[idx]:
                    neg += 1
                self._feedback_conv(neg, pl, target_class=False)
            if progress:
                progress(ep + 1, epochs)
        return self

    def _feedback_conv(self, c: int, patch_lit: np.ndarray, target_class: bool):
        fired, matches = self._clause_match(self.ta[c], patch_lit)
        class_sum = int(np.sum(self.pol * self.w[c] * fired))     # empty clause fires (vacuous)
        v = np.clip(class_sum, -self.cfg.T, self.cfg.T)
        p = (self.cfg.T - v) / (2 * self.cfg.T) if target_class \
            else (self.cfg.T + v) / (2 * self.cfg.T)
        for j in np.where(self.rng.random(self.m) < p)[0]:
            type_i = (self.pol[j] == 1) == target_class
            if type_i:
                if fired[j]:
                    q = self.rng.choice(np.where(matches[j])[0])
                    self._type_i(c, j, patch_lit[q], 1)
                else:
                    self._type_i(c, j, patch_lit[0], 0)           # forget path (patch unused)
            else:
                if fired[j]:
                    q = self.rng.choice(np.where(matches[j])[0])
                    include = self.ta[c, j] > self.N
                    self._type_ii(c, j, patch_lit[q], 1, include)
