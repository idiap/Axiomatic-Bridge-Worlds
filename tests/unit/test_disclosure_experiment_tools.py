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

from scripts.difficulty_shape_summary import summarize_reports
from scripts.robustness_plan import build_robustness_plan
from scripts.robustness_summary import summarize_robustness_plan


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _record(world_id: str, *, total: float, valid: bool = True) -> dict[str, object]:
    return {
        "world_id": world_id,
        "status": "scored",
        "target": {"status": "ok"},
        "score": {
            "valid": valid,
            "metrics": {
                "validity_score": 1.0 if valid else 0.0,
                "hidden_goal_solve_rate": total / 2.0,
                "semantic_equivalence_score": total,
                "total_score": total,
            },
        },
    }


def test_robustness_plan_is_model_agnostic() -> None:
    plan = build_robustness_plan(
        base_dataset_root=Path("datasets/paper_core"),
        perturbed_dataset_root=Path("artifacts/perturbed"),
        report_dir=Path("artifacts/robustness"),
        split="test_public",
        families=("analogy",),
        perturbations=("alpha_renaming",),
        target_command=("python", "scripts/generic_model_target.py"),
        timeout_seconds=42.0,
        limit_per_family=3,
    )

    assert plan["target_command"] == ["python", "scripts/generic_model_target.py"]
    assert plan["generation_steps"][0]["command"][:2] == ["python", "scripts/generate_perturbed_dataset.py"]
    assert len(plan["original_runs"]) == 1
    assert len(plan["runs"]) == 1
    command = plan["runs"][0]["command"]
    assert "run-benchmark" in command
    assert "--family" in command
    assert "--target-command=python" in command
    assert "--target-command=scripts/generic_model_target.py" in command


def test_robustness_summary_pairs_original_and_perturbed_reports(tmp_path: Path) -> None:
    original = _write_json(tmp_path / "original_report.json", {"worlds": [_record("w0", total=0.8)]})
    perturbed = _write_json(tmp_path / "perturbed_report.json", {"worlds": [_record("w0", total=0.5)]})
    plan = {
        "experiment": "abw_generic_robustness",
        "split": "test_public",
        "families": ["analogy"],
        "perturbations": ["alpha_renaming"],
        "target_command": ["python", "adapter.py"],
        "original_runs": [{"family": "analogy", "report": str(original)}],
        "runs": [{"family": "analogy", "perturbation": "alpha_renaming", "report": str(perturbed)}],
    }

    summary = summarize_robustness_plan(plan)

    row = summary["rows"][0]
    assert summary["quality_gate"]["paper_usable"] is True
    assert row["paired_worlds"] == 1
    assert row["metrics"]["total_score"]["mean_original"] == 0.8
    assert row["metrics"]["total_score"]["mean_perturbed"] == 0.5
    assert row["metrics"]["total_score"]["mean_drop"] == 0.30000000000000004


def test_difficulty_shape_summary_groups_c0_c6_rows(tmp_path: Path) -> None:
    base = tmp_path / "dataset" / "test_public" / "analogy"
    c0_root = base / "world_c0"
    c6_root = base / "world_c6"
    _write_json(
        c0_root / "metadata.json",
        {
            "paired_difficulty_level_index": 0,
            "paired_difficulty_level_id": "c0_clean",
            "paired_difficulty_level_label": "Recoverable base",
            "paired_difficulty_base_key": "analogy:00",
            "paired_difficulty_requested_controls": [],
        },
    )
    _write_json(
        c6_root / "metadata.json",
        {
            "paired_difficulty_level_index": 6,
            "paired_difficulty_level_id": "c6_stress_boundary",
            "paired_difficulty_level_label": "Stress boundary",
            "paired_difficulty_base_key": "analogy:00",
            "paired_difficulty_requested_controls": ["stress_boundary"],
        },
    )
    report = _write_json(
        tmp_path / "c0_c6_report.json",
        {
            "worlds": [
                {**_record("world_c0", total=0.9), "family": "analogy", "world_root": str(c0_root)},
                {**_record("world_c6", total=0.4), "family": "analogy", "world_root": str(c6_root)},
            ]
        },
    )

    summary = summarize_reports([report], names=("demo",))

    assert summary["num_rows"] == 2
    assert [row["difficulty_level_id"] for row in summary["by_level"]] == ["c0_clean", "c6_stress_boundary"]
    c6_row = next(row for row in summary["rows"] if row["difficulty_level_id"] == "c6_stress_boundary")
    assert c6_row["total_score_clean_baseline"] == 0.9
    assert c6_row["total_score_drop_from_c0"] == 0.5
