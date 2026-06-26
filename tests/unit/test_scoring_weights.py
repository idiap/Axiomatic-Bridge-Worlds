# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Guard tests for the single-source-of-truth composite-score weights.

These checks keep every shipped family's packaged weights tied to the canonical
constants in `abw_core.scorer.weights`, so the headline benchmark number cannot
drift between generators, the scorer, and the docs.
"""

from __future__ import annotations

import pytest

from abw_core.generator import WorldGenerationRequest, generate_world, registered_families
from abw_core.scorer.weights import (
    ANALOGY_WEIGHTS,
    NON_ANALOGY_WEIGHTS,
    composite_score,
    effective_weights,
)


def _canonical_for(family: str) -> dict[str, float]:
    return dict(ANALOGY_WEIGHTS if family == "analogy" else NON_ANALOGY_WEIGHTS)


def test_canonical_weight_profiles_sum_to_one() -> None:
    assert sum(NON_ANALOGY_WEIGHTS.values()) == pytest.approx(1.0)
    assert sum(ANALOGY_WEIGHTS.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("family", registered_families())
def test_packaged_family_weights_match_canonical(family: str) -> None:
    world = generate_world(WorldGenerationRequest(family=family, seed=5))
    packaged = world.scoring_config["weights"]
    assert packaged == _canonical_for(family)


def test_composite_score_ignores_unweighted_metric_keys() -> None:
    metrics = {
        "hidden_goal_solve_rate": 1.0,
        "semantic_equivalence_score": 1.0,
        "minimality_score": 1.0,
        "validity_score": 1.0,  # not a weight key; must not contribute
        "candidate_size": 99,  # not a weight key; must not contribute
    }
    assert composite_score(metrics, ANALOGY_WEIGHTS) == pytest.approx(1.0)


def test_effective_weights_overlays_partial_package_on_defaults() -> None:
    merged = effective_weights({"novelty_score": 0.42}, NON_ANALOGY_WEIGHTS)
    assert merged["novelty_score"] == 0.42  # packaged value wins
    assert merged["hidden_goal_solve_rate"] == NON_ANALOGY_WEIGHTS["hidden_goal_solve_rate"]
    # Missing package falls back entirely to canonical defaults.
    assert effective_weights(None, ANALOGY_WEIGHTS) == dict(ANALOGY_WEIGHTS)
