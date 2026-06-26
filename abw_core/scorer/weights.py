# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Canonical composite-score weights — the single source of truth.

The composite score is the benchmark's headline number, so its weights must
have exactly one authoritative definition. Generator families build each
world's packaged `scoring_config["weights"]` from the constants here, and the
evaluator falls back to the same constants when a packaged block is absent or
partial. Packaged worlds still carry an explicit `weights` block (so a package
stays self-describing), but those blocks originate here — they are never
hand-edited independently.

Two weight profiles ship:

- `NON_ANALOGY_WEIGHTS` for definition/lemma bridge families
  (`predicate_invention`, `lemma_invention`, `invariant`, `quotient`,
  `normal_form`, `multi_step`).
- `ANALOGY_WEIGHTS` for the theory-transport (morphism) `analogy` family.

Each profile sums to 1.0.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


NON_ANALOGY_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "hidden_goal_solve_rate": 0.30,
        "proof_cost_reduction": 0.20,
        "compression_score": 0.10,
        "semantic_equivalence_score": 0.20,
        "novelty_score": 0.10,
        "minimality_score": 0.10,
    }
)

ANALOGY_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "hidden_goal_solve_rate": 0.55,
        "semantic_equivalence_score": 0.30,
        "minimality_score": 0.15,
    }
)


def composite_score(metrics: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Return the weighted sum of metric components for one weight profile.

    Only the keys named in `weights` contribute, so passing a full metrics
    dictionary (which also carries un-weighted fields such as `validity_score`
    or `candidate_size`) is safe. Validity gating is applied by the caller, not
    here.
    """

    return sum(float(metrics.get(key, 0.0)) * float(weight) for key, weight in weights.items())


def effective_weights(packaged: Mapping[str, float] | None, defaults: Mapping[str, float]) -> dict[str, float]:
    """Overlay a packaged weight block on the canonical defaults.

    This reproduces per-key fallback: any weight the package omits is taken
    from `defaults`, while explicitly packaged weights win. It keeps old or
    partial packages scorable without silently dropping to zero.
    """

    merged = {key: float(value) for key, value in defaults.items()}
    if packaged:
        merged.update({str(key): float(value) for key, value in packaged.items()})
    return merged
