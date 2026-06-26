# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Shared structural metrics for comparing ABW bridge candidates.

These helpers intentionally measure candidate quality at the level of
"representation cost" rather than at the level of theorem truth. The evaluator
already has validity and hidden-goal utility metrics. This file contributes the
orthogonal question:

    How large, compressed, and reusable does the proposed bridge look?

Why this file exists
--------------------
ABW rewards abstractions that make reasoning cheaper, but "cheaper" is not only
about proof steps. A candidate that solves a target by introducing an enormous
amount of auxiliary structure is less satisfying than one that solves the same
target with a compact definition or a short lemma. These metrics provide that
family-agnostic structural pressure.

Concrete example
----------------
- A single conjunctive predicate with two body atoms should count as smaller
  than a candidate that introduces several lemmas.
- A candidate that reduces hidden-goal proof cost from `[4, 3]` to `[2, 1]`
  should receive more credit than one that only improves `[4, 3]` to `[4, 2]`.

Limitations
-----------
- The size estimate is heuristic and symbolic. It does not measure cognitive
  difficulty directly.
- Cross-family comparability is approximate: morphism maps and lemma atoms are
  all projected into one shared notion of "candidate size."
"""

from __future__ import annotations

from abw_core import ir


def candidate_size(document: ir.Document) -> int:
    """Estimate how much formal structure a candidate introduces.

    The goal is not to compute an information-theoretic optimum. The goal is to
    provide one stable, family-agnostic notion of candidate footprint that can
    be used by minimality and compression scoring.

    The heuristic counts:
    - definition body atoms
    - lemma and theorem atoms, including each conclusion
    - explicit morphism mapping entries

    This treats "more explicit formal surface" as "larger candidate."
    """

    # The counts are intentionally coarse. They give the scorer a stable notion
    # of footprint without entangling size with proof search details.
    definition_atoms = sum(len(definition.body) for definition in document.definitions)
    lemma_atoms = sum(len(lemma.premises) + 1 for lemma in document.lemmas + document.theorems)
    morphism_entries = sum(len(morphism.mapping) for morphism in document.morphisms)
    return definition_atoms + lemma_atoms + morphism_entries


def minimality_score(document: ir.Document) -> float:
    """Convert structural size into a bounded smaller-is-better reward.

    ABW does not want minimality to dominate usefulness. This score therefore
    decays gently as the candidate grows: a tiny bridge is rewarded, but larger
    bridges are penalized smoothly rather than catastrophically.

    The returned value lives in `(0, 1]` for non-empty candidates, with the
    smallest candidate size receiving the highest score.
    """

    size = candidate_size(document)
    if size <= 0:
        return 0.0
    return 1.0 / (1.0 + max(size - 1, 0))


def proof_cost_reduction(baseline_costs: list[int], candidate_costs: list[int]) -> float:
    """Measure how much hidden-goal proof burden the candidate removes.

    The metric compares already-computed proof costs, rather than recomputing
    proofs itself. It asks: out of the total baseline proof effort visible in
    the hidden targets, what fraction disappeared once the candidate bridge was
    available?

    Important boundary:
    the metric only rewards non-negative improvements. A candidate that makes a
    goal harder does not get "negative credit"; it simply fails to earn extra
    reduction on that target.
    """

    baseline_total = sum(baseline_costs)
    if baseline_total <= 0:
        return 0.0
    improvement = sum(max(0, base - candidate) for base, candidate in zip(baseline_costs, candidate_costs))
    return improvement / baseline_total
