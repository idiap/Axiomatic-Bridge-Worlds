# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# SPDX-License-Identifier: MIT

"""Tests for public-only few-shot exemplar construction."""

from __future__ import annotations

from pathlib import Path

from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.nl.controlled_candidate import CandidateVocabulary, convert_controlled_nl
from abw_core.packager import package_world
from abw_core.scorer import evaluate_candidate
from scripts.build_few_shot_exemplar_bank import build_exemplar_bank
from scripts.model_target import render_few_shot_exemplars


def _dataset(tmp_path: Path) -> tuple[Path, Path]:
    dataset_root = tmp_path / "dataset"
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=23))
    world_root = package_world(
        world,
        dataset_root / "dev" / "predicate_invention" / world.world_id,
    )
    return dataset_root, world_root


def test_formal_exemplar_is_valid_after_private_label_normalization(tmp_path: Path) -> None:
    dataset_root, world_root = _dataset(tmp_path)

    bank = build_exemplar_bank(
        dataset_root=dataset_root,
        split="dev",
        families=("predicate_invention",),
        exemplars_per_family=1,
        view_condition="formal_direct",
    )

    candidate = bank["exemplars"][0]["candidate"]
    assert evaluate_candidate(world_root, candidate)["valid"] is True


def test_nld_exemplar_round_trips_to_a_valid_candidate(tmp_path: Path) -> None:
    dataset_root, world_root = _dataset(tmp_path)

    bank = build_exemplar_bank(
        dataset_root=dataset_root,
        split="dev",
        families=("predicate_invention",),
        exemplars_per_family=1,
        view_condition="natural_language_direct",
    )
    vocabulary = CandidateVocabulary.from_public_artifacts(
        world_root / "formal" / "signature.json",
        world_root / "formal" / "axioms.abw",
    )
    conversion = convert_controlled_nl(bank["exemplars"][0]["candidate"], vocabulary)

    assert conversion.status == "converted"
    assert conversion.candidate_dsl is not None
    assert evaluate_candidate(world_root, conversion.candidate_dsl)["valid"] is True


def test_family_few_shot_rendering_selects_two_matching_examples() -> None:
    bank = {
        "exemplars": [
            {
                "id": "predicate-example",
                "family": "predicate_invention",
                "public_nl_view": "PREDICATE PUBLIC VIEW",
                "candidate": "PREDICATE CANDIDATE",
            },
            {
                "id": "lemma-example",
                "family": "lemma_invention",
                "public_nl_view": "LEMMA PUBLIC VIEW",
                "candidate": "LEMMA CANDIDATE",
            },
            {
                "id": "lemma-example-2",
                "family": "lemma_invention",
                "public_nl_view": "SECOND LEMMA PUBLIC VIEW",
                "candidate": "SECOND LEMMA CANDIDATE",
            },
        ]
    }

    rendered = render_few_shot_exemplars(
        bank,
        view_key="public_nl_view",
        family="lemma_invention",
        expected_count=2,
    )

    assert "LEMMA PUBLIC VIEW" in rendered
    assert "LEMMA CANDIDATE" in rendered
    assert "SECOND LEMMA PUBLIC VIEW" in rendered
    assert "SECOND LEMMA CANDIDATE" in rendered
    assert "PREDICATE PUBLIC VIEW" not in rendered
    assert "PREDICATE CANDIDATE" not in rendered
