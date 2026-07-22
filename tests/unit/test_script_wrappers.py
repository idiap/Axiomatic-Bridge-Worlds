# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Regression tests for the thin script wrappers around the main CLI.

The repository keeps a few convenience scripts for ergonomic entrypoints. These
checks make sure each wrapper forwards into the canonical CLI rather than
drifting into a second, inconsistent code path.
"""

import runpy
import sys
from pathlib import Path

import pytest

import abw_core.cli


@pytest.mark.parametrize(
    ("script_name", "argv", "expected_command"),
    [
        ("score_candidate.py", ["score_candidate.py", "--world", "demo-world"], "score-candidate"),
        ("validate_world.py", ["validate_world.py", "--world", "demo-world"], "validate-world"),
        (
            "run_benchmark.py",
            ["run_benchmark.py", "--dataset", "demo-dataset", "--target-command", "python"],
            "run-benchmark",
        ),
    ],
)
def test_script_wrapper_routes_into_cli(monkeypatch, script_name: str, argv: list[str], expected_command: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    calls = []

    def fake_main(argv):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(abw_core.cli, "main", fake_main)
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(repo_root / "scripts" / script_name), run_name="__main__")

    assert error.value.code == 0
    assert calls == [[expected_command, *argv[1:]]]
