# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""End-to-end checks for the public model-evaluation commands."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TARGET = REPO_ROOT / "scripts" / "example_target_system.py"
GOLD_CANDIDATE = REPO_ROOT / "examples" / "predicate_invention" / "gold_candidate.abw"


def _generate_dataset(tmp_path: Path) -> Path:
    config_path = tmp_path / "dataset.yaml"
    dataset_root = tmp_path / "dataset"
    config_path.write_text(
        """
dataset_name: public_evaluation_smoke
version: 0.2.0
families: [predicate_invention]
splits:
  dev:
    examples_per_family: 1
    start_seed: 7
  test_public:
    examples_per_family: 1
    start_seed: 29
""".strip()
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core",
            "generate-dataset",
            "--config",
            str(config_path),
            "--output",
            str(dataset_root),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return dataset_root


def test_cli_generates_and_scores_a_seeded_world(tmp_path: Path) -> None:
    dataset_root = _generate_dataset(tmp_path)
    world_root = dataset_root / "dev" / "predicate_invention" / "abw_dev_0000"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core",
            "score-candidate",
            "--world",
            str(world_root),
            "--candidate",
            str(GOLD_CANDIDATE),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(completed.stdout)
    assert report["valid"] is True
    assert report["metrics"]["hidden_goal_solve_rate"] > 0.0


def test_cli_runs_a_conditioned_benchmark(tmp_path: Path) -> None:
    dataset_root = _generate_dataset(tmp_path)
    results_path = tmp_path / "ct_results.json"
    prompt_condition = "zero_shot_cross_track_nl_to_formal"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core",
            "run-benchmark",
            "--dataset",
            str(dataset_root),
            "--split",
            "test_public",
            "--prompt-condition",
            prompt_condition,
            "--target-command",
            sys.executable,
            "--target-command",
            str(EXAMPLE_TARGET),
            "--output",
            str(results_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(results_path.read_text(encoding="utf-8"))
    assert report["target"]["prompt_condition"] == prompt_condition
    assert report["summary"]["num_worlds"] == 1
    assert report["summary"]["contract_failures"] == 0
    assert report["worlds"][0]["target"]["response_metadata"]["prompt_condition"] == prompt_condition


def test_run_experiment_writes_a_condition_consistent_manifest(tmp_path: Path) -> None:
    dataset_root = _generate_dataset(tmp_path)
    results_path = tmp_path / "nld_results.json"
    manifest_path = tmp_path / "nld_manifest.json"
    prompt_condition = "zero_shot_natural_language_direct"

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_experiment.py"),
            "--dataset-root",
            str(dataset_root),
            "--split",
            "test_public",
            "--prompt-condition",
            prompt_condition,
            "--target-command",
            sys.executable,
            "--target-command",
            str(EXAMPLE_TARGET),
            "--output",
            str(results_path),
            "--manifest-output",
            str(manifest_path),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    results = json.loads(results_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert results["target"]["prompt_condition"] == prompt_condition
    assert results["summary"]["contract_failures"] == 0
    assert manifest["run"]["prompt_condition"] == prompt_condition
