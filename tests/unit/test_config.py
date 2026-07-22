# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Validation tests for dataset-generation configuration loading.

The configuration layer is the bridge between human-edited YAML presets and the
deterministic generator runtime. These checks focus on rejecting underspecified
presets before they can produce ambiguous or partial datasets.
"""

from pathlib import Path

import pytest

from abw_core.config import load_config, manifest_payload


PAPER_CORE_FAMILIES = (
    "predicate_invention",
    "lemma_invention",
    "analogy",
    "invariant",
    "quotient",
    "normal_form",
    "multi_step",
)


def test_load_config_rejects_empty_family_list(tmp_path: Path) -> None:
    config_path = tmp_path / "empty_families.yaml"
    config_path.write_text(
        "families: []\n"
        "splits:\n"
        "  train: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="at least one family"):
        load_config(config_path)


def test_load_config_rejects_missing_splits(tmp_path: Path) -> None:
    config_path = tmp_path / "missing_splits.yaml"
    config_path.write_text("families: [predicate_invention]\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least one split"):
        load_config(config_path)


def test_load_config_parses_backend_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "solver_profile.yaml"
    config_path.write_text(
        "families: [predicate_invention]\n"
        "splits:\n"
        "  train: 1\n"
        "prover_backend:\n"
        "  name: subprocess\n"
        "  command: [python3, -m, abw_core.prover.z3_driver]\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.prover_backend_name == "subprocess"
    assert config.prover_backend_command == ("python3", "-m", "abw_core.prover.z3_driver")


def test_load_config_expands_examples_per_family(tmp_path: Path) -> None:
    config_path = tmp_path / "balanced.yaml"
    config_path.write_text(
        "families: [predicate_invention, lemma_invention]\n"
        "views: [formal, natural_language]\n"
        "splits:\n"
        "  dev:\n"
        "    examples_per_family: 3\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.splits == {"dev": 6}
    assert config.split_examples_per_family == {"dev": 3}
    assert config.split_start_seeds is None
    assert config.views == ("formal", "natural_language")


def test_manifest_payload_uses_runtime_output_override(tmp_path: Path) -> None:
    config_path = tmp_path / "dataset.yaml"
    config_path.write_text(
        "dataset_name: demo\n"
        "families: [predicate_invention]\n"
        "splits:\n"
        "  train: 1\n",
        encoding="utf-8",
    )

    config = load_config(config_path)
    manifest = manifest_payload(config, {"train": 1}, output_dir=tmp_path / "exported")

    assert manifest["output_dir"] == str(tmp_path / "exported")
    assert manifest["views"] == ["formal", "natural_language"]


def test_core_family_default_dsl_version_is_current_public_surface(tmp_path: Path) -> None:
    config_path = tmp_path / "core_family.yaml"
    config_path.write_text(
        "dataset_name: core-demo\n"
        "families: [predicate_invention]\n"
        "splits:\n"
        "  train: 1\n",
        encoding="utf-8",
    )

    config = load_config(config_path)
    manifest = manifest_payload(config, {"train": 1})

    assert config.dsl_version == "abw-dsl-v1"
    assert manifest["dsl_version"] == "abw-dsl-v1"


def test_seeded_v2_config_uses_disclosure_families() -> None:
    config_path = Path(__file__).resolve().parents[2] / "configs" / "paper_core_seeded_v2.yaml"

    config = load_config(config_path)

    assert config.families == PAPER_CORE_FAMILIES
    assert config.split_examples_per_family == {"dev": 5, "test_public": 50}
    assert config.split_start_seeds == {"dev": 4100, "test_public": 3114}
    assert config.splits["dev"] == 35
    assert config.splits["test_public"] == 350
    assert config.output_dir == "dataset/abw-formal-nl-core"
