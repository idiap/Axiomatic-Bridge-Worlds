# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Tests for the public condition-aware experiment runner."""

from __future__ import annotations

from pathlib import Path

from scripts import run_experiment


def test_run_experiment_forwards_declared_contract(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        run_experiment,
        "_validate_dataset",
        lambda *_args, **_kwargs: {"valid": True, "num_worlds": 1, "failures": []},
    )

    def fake_run_benchmark(*_args, **kwargs):  # noqa: ANN001, ANN202
        seen.update(kwargs)
        return {"summary": {"num_worlds": 1, "contract_failures": 0}}

    monkeypatch.setattr(run_experiment, "run_benchmark", fake_run_benchmark)
    result_path = tmp_path / "results.json"
    manifest_path = tmp_path / "manifest.json"

    exit_code = run_experiment.main(
        [
            "--dataset-root",
            str(tmp_path / "dataset"),
            "--prompt-condition",
            "family_few_shot_natural_language_direct",
            "--exemplar-bank",
            "configs/nld.json",
            "--target-command",
            "dummy-adapter",
            "--output",
            str(result_path),
            "--manifest-output",
            str(manifest_path),
        ]
    )

    assert exit_code == 0
    assert seen["prompt_condition"] == "family_few_shot_natural_language_direct"
    assert seen["exemplar_bank"] == "configs/nld.json"


def test_run_experiment_rejects_conflicting_target_flags_before_validation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def unexpected_validation(*_args, **_kwargs):  # noqa: ANN001, ANN202
        raise AssertionError("dataset validation should not run for a contradictory contract")

    monkeypatch.setattr(run_experiment, "_validate_dataset", unexpected_validation)

    exit_code = run_experiment.main(
        [
            "--dataset-root",
            str(tmp_path / "dataset"),
            "--prompt-condition",
            "zero_shot_cross_track_nl_to_formal",
            "--target-command",
            "dummy-adapter",
            "--target-command=--prompt-condition",
            "--target-command",
            "zero_shot_formal_direct",
        ]
    )

    assert exit_code == 2
    assert "conflicts with the experiment value" in capsys.readouterr().err
