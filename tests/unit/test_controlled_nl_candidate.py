# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Contract tests for true Natural-Language Direct candidates."""

from __future__ import annotations

from pathlib import Path

import pytest

from abw_core import ir
from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.nl.controlled_candidate import (
    INVALID_CONVERSION_CANDIDATE,
    CandidateVocabulary,
    convert_controlled_nl,
    render_controlled_nl_candidate,
)
from abw_core.nl.render import render_world
from abw_core.packager import package_world
from abw_core.scorer import evaluate_candidate


PAPER_FAMILIES = (
    "predicate_invention",
    "lemma_invention",
    "analogy",
    "invariant",
    "quotient",
    "normal_form",
    "multi_step",
)


def _candidate_document(world: ir.World) -> ir.Document:
    return ir.Document(
        definitions=world.hidden_bridge.definitions,
        lemmas=world.hidden_bridge.lemmas,
        morphisms=world.hidden_bridge.mappings,
    )


@pytest.mark.parametrize("family", PAPER_FAMILIES)
def test_gold_bridge_round_trips_through_controlled_nl(family: str, tmp_path: Path) -> None:
    world = generate_world(WorldGenerationRequest(family=family, seed=23))
    world_root = package_world(world, tmp_path / family / world.world_id)
    vocabulary = CandidateVocabulary.from_public_artifacts(
        world_root / "formal" / "signature.json",
        world_root / "formal" / "axioms.abw",
    )

    controlled_nl = render_controlled_nl_candidate(_candidate_document(world), vocabulary)
    conversion = convert_controlled_nl(controlled_nl, vocabulary)

    assert conversion.status == "converted"
    assert conversion.candidate_dsl is not None
    assert conversion.errors == ()
    score = evaluate_candidate(world_root, conversion.candidate_dsl)
    assert score["valid"] is True


def test_conversion_failure_is_explicit_and_has_no_dsl(tmp_path: Path) -> None:
    world = generate_world(WorldGenerationRequest(family="invariant", seed=11))
    world_root = package_world(world, tmp_path / world.world_id)
    vocabulary = CandidateVocabulary.from_public_artifacts(
        world_root / "formal" / "signature.json",
        world_root / "formal" / "axioms.abw",
    )

    conversion = convert_controlled_nl("The bridge is probably stable.", vocabulary)

    assert conversion.status == "failed"
    assert conversion.candidate_dsl is None
    assert conversion.errors
    failed_score = evaluate_candidate(world_root, INVALID_CONVERSION_CANDIDATE)
    assert failed_score["valid"] is False
    assert failed_score["metrics"]["total_score"] == 0.0

def test_renderer_exposes_rewrites_and_nested_theories() -> None:
    normal_world = generate_world(WorldGenerationRequest(family="normal_form", seed=29))
    analogy_world = generate_world(WorldGenerationRequest(family="analogy", seed=31))

    normal_rendering = render_world(normal_world)
    analogy_rendering = render_world(analogy_world)

    assert "rewrites to" in normal_rendering.problem_md
    assert "### Theory Left" in analogy_rendering.problem_md
    assert "### Theory Right" in analogy_rendering.problem_md
    assert "Operation:" in analogy_rendering.problem_md
    assert "Theory Theorems" in analogy_rendering.theorem_cards_md
