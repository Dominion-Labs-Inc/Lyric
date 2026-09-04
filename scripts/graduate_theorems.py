#!/usr/bin/env python3
"""Graduate mathematics and computer science as CHAINABLE THEOREMS.

Each entry is a real, established implication taught to the substrate as a held
rule: "if a <subject> is <ant> then it is <cons>". The substrate's held-rule
reasoner renders both sides to one atom vocabulary and lets Z3 chain them, so a
run of these forms a lattice the substrate can prove conclusions across --
`holomorphic -> analytic -> smooth -> continuous` from a single supposition,
model-free.

TWO INVARIANTS, because a false rule would teach a false theorem:
  * Every implication holds UNCONDITIONALLY at the generality stated. Where a
    theorem needs a hypothesis, the hypothesis is baked into the antecedent
    property name (`real_symmetric`, not `symmetric`; `compact_metric_space`
    scoped by subject), so the rule as written is simply true.
  * Only ONE direction is taught unless the biconditional genuinely holds. An
    equivalence (holomorphic <-> analytic) is taught both ways on purpose; an
    implication whose converse fails (independent -> uncorrelated) is taught one
    way only.

A THEOREMS entry is (subject, antecedent_property, consequent_property). The
subject is the object TYPE and scopes the lattice: `matrix`, `group`, `space`,
`formal_language`. Distinct subjects keep unrelated domains from sharing atoms.
"""

# ── MATHEMATICS ────────────────────────────────────────────────────────────

_MATH = [
    # Complex analysis -- a holomorphic function is analytic and infinitely smooth.
    ("complex function", "entire", "holomorphic"),
    ("complex function", "holomorphic", "analytic"),
    ("complex function", "analytic", "holomorphic"),
    ("complex function", "holomorphic", "infinitely differentiable"),
    ("complex function", "infinitely differentiable", "smooth"),
    ("complex function", "holomorphic", "continuous"),
    ("complex function", "holomorphic", "complex differentiable"),
    ("complex function", "complex differentiable", "holomorphic"),

    # Real analysis -- the regularity ladder.
    ("real function", "continuously differentiable", "differentiable"),
    ("real function", "differentiable", "continuous"),
    ("real function", "smooth", "continuously differentiable"),
    ("real function", "lipschitz", "uniformly continuous"),
    ("real function", "uniformly continuous", "continuous"),
    ("real function", "continuous", "borel measurable"),
    ("real function", "continuous on compact set", "uniformly continuous"),
    ("real function", "continuous on compact set", "bounded"),

    # Metric and topological spaces.
    ("metric space", "compact", "complete"),
    ("metric space", "compact", "totally bounded"),
    ("metric space", "compact", "separable"),
    ("metric space", "compact", "bounded"),
    ("metric space", "complete", "cauchy sequences converge"),

    # Functional analysis -- the space hierarchy.
    ("space", "hilbert", "banach"),
    ("space", "hilbert", "inner product space"),
    ("space", "inner product space", "normed"),
    ("space", "banach", "complete normed"),
    ("space", "complete normed", "normed"),
    ("space", "finite dimensional normed", "banach"),
    ("space", "normed", "metric"),
    ("space", "normed", "vector space"),
    ("space", "metric", "topological"),

    # Linear algebra -- matrix classes.
    ("matrix", "orthogonal", "invertible"),
    ("matrix", "orthogonal", "normal"),
    ("matrix", "unitary", "normal"),
    ("matrix", "unitary", "invertible"),
    ("matrix", "hermitian", "normal"),
    ("matrix", "real symmetric", "hermitian"),
    ("matrix", "real symmetric", "diagonalizable"),
    ("matrix", "normal", "unitarily diagonalizable"),
    ("matrix", "unitarily diagonalizable", "diagonalizable"),
    ("matrix", "positive definite", "invertible"),
    ("matrix", "invertible", "full rank"),
    ("matrix", "invertible", "nonzero determinant"),

    # Abstract algebra -- groups, rings, fields.
    ("group", "cyclic", "abelian"),
    ("group", "finite cyclic", "cyclic"),
    ("ring", "field", "integral domain"),
    ("ring", "field", "division ring"),
    ("ring", "integral domain", "commutative ring"),
    ("ring", "euclidean domain", "principal ideal domain"),
    ("ring", "principal ideal domain", "unique factorization domain"),
    ("ring", "unique factorization domain", "integral domain"),

    # Measure and probability -- one-directional where the converse fails.
    ("random variable", "independent", "uncorrelated"),
    ("random variable", "almost surely constant", "uncorrelated"),
    ("random variable", "bounded", "integrable"),
    ("random variable", "integrable", "finite expectation"),
    ("random variable", "gaussian", "absolutely continuous"),
    ("measure", "probability measure", "finite measure"),
    ("measure", "finite measure", "sigma finite"),
    ("real function", "simple", "measurable"),

    # Real analysis -- absolute continuity, bounded variation, convexity.
    ("real function", "real analytic", "smooth"),
    ("real function", "lipschitz", "absolutely continuous"),
    ("real function", "absolutely continuous", "uniformly continuous"),
    ("real function", "absolutely continuous", "bounded variation"),
    ("real function", "convex on open interval", "continuous"),
    ("real function", "monotonic", "differentiable almost everywhere"),

    # Point-set topology -- separation and countability (own subject/lattice).
    ("topological space", "metrizable", "hausdorff"),
    ("topological space", "metrizable", "normal"),
    ("topological space", "metrizable", "regular"),
    ("topological space", "metrizable", "paracompact"),
    ("topological space", "metrizable", "first countable"),
    ("topological space", "compact hausdorff", "normal"),
    ("topological space", "compact hausdorff", "regular"),
    ("topological space", "discrete", "metrizable"),
    ("topological space", "second countable", "first countable"),
    ("topological space", "second countable", "separable"),
    ("topological space", "path connected", "connected"),
    ("topological space", "compact", "limit point compact"),

    # Number systems -- the containment chain.
    ("number", "natural", "integer"),
    ("number", "integer", "rational"),
    ("number", "rational", "real"),
    ("number", "rational", "algebraic"),
    ("number", "real", "complex"),
    ("number", "algebraic", "complex"),
    ("number", "prime", "natural"),
    ("number", "prime", "integer"),

    # Linear algebra -- more matrix classes.
    ("matrix", "identity", "diagonal"),
    ("matrix", "scalar", "diagonal"),
    ("matrix", "diagonal", "triangular"),
    ("matrix", "diagonal", "symmetric"),
    ("matrix", "diagonal", "normal"),
    ("matrix", "permutation", "orthogonal"),
    ("matrix", "orthogonal", "unitary"),
    ("matrix", "real symmetric", "normal"),
    ("matrix", "involutory", "invertible"),
    ("matrix", "idempotent", "diagonalizable"),
    ("matrix", "nilpotent", "singular"),

    # Abstract algebra -- solvability ladder, more rings and fields, modules.
    ("group", "abelian", "nilpotent"),
    ("group", "nilpotent", "solvable"),
    ("group", "finite p group", "nilpotent"),
    ("group", "trivial", "cyclic"),
    ("ring", "field", "euclidean domain"),
    ("ring", "division ring", "simple ring"),
    ("ring", "boolean ring", "commutative ring"),
    ("field", "finite", "perfect"),
    ("field", "algebraically closed", "perfect"),
    ("field", "algebraically closed", "infinite"),
    ("module", "vector space", "free"),
    ("module", "free", "projective"),
    ("module", "projective", "flat"),
]

# ── COMPUTER SCIENCE ───────────────────────────────────────────────────────

_CS = [
    # Formal languages -- the Chomsky hierarchy and decidability.
    ("formal language", "finite", "regular"),
    ("formal language", "regular", "context free"),
    ("formal language", "context free", "context sensitive"),
    ("formal language", "context sensitive", "recursive"),
    ("formal language", "recursive", "recursively enumerable"),
    ("formal language", "regular", "decidable"),
    ("formal language", "context free", "decidable"),
    ("formal language", "context sensitive", "decidable"),
    ("formal language", "recursive", "decidable"),

    # Complexity -- only true inclusions.
    ("decision problem", "np complete", "np hard"),
    ("decision problem", "np complete", "in np"),
    ("decision problem", "in p", "in np"),
    ("decision problem", "in np", "in pspace"),
    ("decision problem", "in p", "in pspace"),
    ("decision problem", "in pspace", "in exptime"),
    ("decision problem", "in np", "decidable"),
    ("decision problem", "in p", "decidable"),

    # Computability -- the recursion ladder.
    ("computable function", "primitive recursive", "total recursive"),
    ("computable function", "total recursive", "partial recursive"),
    ("computable function", "total recursive", "computable"),
    ("problem", "decidable", "semidecidable"),

    # Graphs.
    ("graph", "tree", "connected"),
    ("graph", "tree", "acyclic"),
    ("graph", "tree", "bipartite"),
    ("graph", "forest", "acyclic"),
    ("graph", "complete", "connected"),
    ("graph", "hamiltonian", "connected"),
    ("graph", "bipartite", "two colorable"),
    ("graph", "planar", "four colorable"),

    # Data structures -- balance implies logarithmic operations.
    ("data structure", "avl tree", "balanced binary search tree"),
    ("data structure", "red black tree", "balanced binary search tree"),
    ("data structure", "balanced binary search tree", "logarithmic height"),
    ("data structure", "balanced binary search tree", "logarithmic search"),

    # Sorting algorithms.
    ("sorting algorithm", "merge sort", "comparison sort"),
    ("sorting algorithm", "heapsort", "comparison sort"),
    ("sorting algorithm", "quicksort", "comparison sort"),
    ("sorting algorithm", "comparison sort", "omega n log n"),
    ("sorting algorithm", "merge sort", "stable"),
    ("sorting algorithm", "insertion sort", "comparison sort"),
    ("sorting algorithm", "bubble sort", "comparison sort"),
    ("sorting algorithm", "heapsort", "n log n"),
    ("sorting algorithm", "merge sort", "n log n"),
    ("sorting algorithm", "counting sort", "stable"),

    # Complexity -- the space and time hierarchy (all true inclusions).
    ("decision problem", "in logspace", "in nlogspace"),
    ("decision problem", "in logspace", "in p"),
    ("decision problem", "in nlogspace", "in p"),
    ("decision problem", "in conp", "in pspace"),
    ("decision problem", "in exptime", "in expspace"),
    ("decision problem", "decidable", "recursively enumerable"),

    # Automata -- machine subsumption.
    ("automaton", "deterministic finite", "finite"),
    ("automaton", "deterministic finite", "nondeterministic finite"),
    ("automaton", "deterministic pushdown", "pushdown"),
    ("automaton", "finite", "pushdown"),

    # Type theory and rewriting -- normalization.
    ("calculus", "simply typed lambda calculus", "strongly normalizing"),
    ("calculus", "system f", "strongly normalizing"),
    ("calculus", "strongly normalizing", "weakly normalizing"),
    ("calculus", "strongly normalizing", "terminating"),

    # Cryptography -- security reductions (one direction).
    ("hash function", "collision resistant", "second preimage resistant"),

    # Distributed systems -- consistency-model strength.
    ("consistency model", "strict serializable", "serializable"),
    ("consistency model", "strict serializable", "linearizable"),
    ("consistency model", "linearizable", "sequentially consistent"),
    ("consistency model", "sequentially consistent", "causally consistent"),

    # Graphs -- more classes.
    ("graph", "tree", "planar"),
    ("graph", "forest", "planar"),
    ("graph", "outerplanar", "planar"),
    ("graph", "path", "tree"),
    ("graph", "star", "tree"),
    ("graph", "cycle", "connected"),
    ("graph", "cycle", "eulerian"),
    ("graph", "complete bipartite", "bipartite"),

    # Data structures -- more shapes and their guarantees.
    ("data structure", "binary heap", "complete binary tree"),
    ("data structure", "complete binary tree", "logarithmic height"),
    ("data structure", "b tree", "logarithmic height"),
    ("data structure", "sorted array", "logarithmic search"),
]

THEOREMS = _MATH + _CS
MATH = _MATH
CS = _CS


def as_rules(entries):
    """(subject, ant, cons) -> (antecedent dict, consequent dict, surface) for
    learn_rule. Relation `is` throughout: these are property predications."""
    for subject, ant, cons in entries:
        antecedent = {"subject": subject, "relation": "is", "obj": ant, "positive": True}
        consequent = {"subject": subject, "relation": "is", "obj": cons, "positive": True}
        surface = f"if a {subject} is {ant} then it is {cons}"
        yield antecedent, consequent, surface
