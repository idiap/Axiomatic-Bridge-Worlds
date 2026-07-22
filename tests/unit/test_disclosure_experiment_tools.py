# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Tests for the disclosure-facing robustness and C0-C6 helpers."""

from __future__ import annotations

import json
from pathlib import Path

from abw_core.packager import PRIVATE_WORLD_FILES, export_public_world, package_world
from scripts.build_paired_difficulty_dataset import DIFFICULTY_LEVELS, _variant_world
from scripts.robustness_plan import build_robustness_plan


def test_robustness_plan_is_model_agnostic() -> None:
    plan = build_robustness_plan(
        base_dataset_root=Path("dataset/abw-formal-nl-core"),
        perturbed_dataset_root=Path("artifacts/perturbed"),
        results_dir=Path("artifacts/robustness"),
        split="test_public",
        families=("analogy",),
        perturbations=("alpha_renaming",),
        target_command=("python", "scripts/model_target.py"),
        timeout_seconds=42.0,
        limit_per_family=3,
        prompt_condition="zero_shot_cross_track_nl_to_formal",
        exemplar_bank=None,
    )

    assert plan["target_command"] == ["python", "scripts/model_target.py"]
    assert plan["generation_steps"][0]["command"][:2] == ["python", "scripts/generate_perturbed_dataset.py"]
    assert len(plan["original_runs"]) == 1
    assert len(plan["runs"]) == 1
    command = plan["runs"][0]["command"]
    assert "run-benchmark" in command
    assert "--family" in command
    assert "--prompt-condition" in command
    assert "zero_shot_cross_track_nl_to_formal" in command
    assert "--target-command=python" in command
    assert "--target-command=scripts/model_target.py" in command


def test_paired_controls_precede_public_projection(tmp_path: Path) -> None:
    levels = {level.index: level for level in DIFFICULTY_LEVELS}
    base = _variant_world(family="predicate_invention", seed=17, base_index=0, level=levels[0])
    deep = _variant_world(family="predicate_invention", seed=17, base_index=0, level=levels[1])
    decoy = _variant_world(family="predicate_invention", seed=17, base_index=0, level=levels[4])

    # Controls act on the complete world: C1 adds a private target and C4 adds public evidence.
    assert deep.hidden_bridge == base.hidden_bridge
    assert len(deep.targets_hidden) == len(base.targets_hidden) + 1
    assert deep.targets_hidden[-1].name.endswith("_deep_5")

    decoy_names = decoy.metadata["paired_difficulty_added_symbols"]
    assert decoy_names["predicate_flag"] in {predicate.name for predicate in decoy.signature.predicates}

    full_root = package_world(decoy, tmp_path / "full")
    public_root = export_public_world(full_root, tmp_path / "public")

    assert all((full_root / path).exists() for path in PRIVATE_WORLD_FILES)
    assert all(not (public_root / path).exists() for path in PRIVATE_WORLD_FILES)
    signature = json.loads((public_root / "formal" / "signature.json").read_text(encoding="utf-8"))
    assert decoy_names["predicate_flag"] in {predicate["name"] for predicate in signature["predicates"]}
