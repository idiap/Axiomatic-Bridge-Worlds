# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.packager import load_world, package_world
from scripts.build_paired_difficulty_dataset import build_seeded_v2_dataset


def test_c0_c6_are_derived_from_packaged_source_world(tmp_path: Path) -> None:
    source_root = tmp_path / "paper_core_seeded_v2"
    source_world = generate_world(
        WorldGenerationRequest(
            family="predicate_invention",
            seed=3114,
            world_id="source_world",
            hidden_steps=(2, 3),
        )
    )
    package_world(source_world, source_root / "test_public" / source_world.family / source_world.world_id)

    output = tmp_path / "difficulty"
    manifest = build_seeded_v2_dataset(
        output_root=output,
        source_dataset_root=source_root,
        source_split="test_public",
        families=("predicate_invention",),
        examples_per_family=1,
        overwrite=False,
        validate=True,
    )

    assert manifest["world_count"] == 7
    assert {item["source_world_id"] for item in manifest["worlds"]} == {"source_world"}
    c0 = load_world(output / "test_public" / "predicate_invention" / "abw_paired_predicate_invention_00_c0_clean")
    assert c0.hidden_bridge == source_world.hidden_bridge
    assert c0.metadata["paired_difficulty_base_key"] == "predicate_invention:source_world"
