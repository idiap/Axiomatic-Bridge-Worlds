# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Integration coverage for the command-line interface and subprocess entrypoints.

These tests treat the CLI like an external user would: spawn it in a fresh
process, generate worlds or sessions on disk, and confirm that the published
commands produce stable JSON payloads and packaged artifacts.
"""

import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_cli_generate_and_score(tmp_path) -> None:
    world_root = tmp_path / "tiny_world"
    generate = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "7",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    generated = json.loads(generate.stdout)
    assert generated["output"] == str(world_root)

    score = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "score-candidate",
            "--world",
            str(world_root),
            "--candidate",
            "examples/predicate_invention/gold_candidate.abw",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(score.stdout)
    assert report["valid"] is True
    assert report["metrics"]["hidden_goal_solve_rate"] > 0.0

    delegated = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "score-candidate",
            "--world",
            str(world_root),
            "--candidate",
            "examples/predicate_invention/gold_candidate.abw",
            "--prover-backend",
            "subprocess",
            "--backend-command",
            sys.executable,
            "--backend-command=-m",
            "--backend-command=abw_core.prover.subprocess_driver",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    delegated_report = json.loads(delegated.stdout)
    assert delegated_report["valid"] is True
    assert delegated_report["metrics"]["total_score"] == report["metrics"]["total_score"]


def test_cli_run_benchmark_against_example_target_system(tmp_path) -> None:
    config_path = tmp_path / "benchmark_dataset.yaml"
    dataset_root = tmp_path / "benchmark_dataset"
    results_path = tmp_path / "benchmark_results.json"
    config_path.write_text(
        """
dataset_name: benchmark_smoke
version: 0.2.0
families: [predicate_invention, analogy]
splits:
  train: 2
start_seed: 11
max_term_depth: 3
proof_budget: 3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-dataset",
            "--config",
            str(config_path),
            "--output",
            str(dataset_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "run-benchmark",
            "--dataset",
            str(dataset_root),
            "--target-command",
            sys.executable,
            "--target-command",
            str((Path.cwd() / "scripts" / "example_target_system.py").resolve()),
            "--output",
            str(results_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(run.stdout)
    results = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["output"] == str(results_path)
    assert results["dataset"]["manifest"]["output_dir"] == str(dataset_root)
    assert results["summary"]["num_worlds"] == 2
    assert results["summary"]["completed"] == 2
    assert results["summary"]["valid_submissions"] == 2
    assert results["summary"]["primary_score"] > 0.0
    assert results["by_family"]["predicate_invention"]["completed"] == 1
    assert results["by_family"]["analogy"]["completed"] == 1

def test_cli_can_export_public_only_dataset(tmp_path) -> None:
    dataset_root = tmp_path / "dataset"
    public_root = tmp_path / "dataset_public"
    config_path = tmp_path / "dataset.yaml"
    config_path.write_text(
        """
dataset_name: benchmark_smoke
version: 0.2.0
families: [predicate_invention]
splits:
  train: 1
start_seed: 11
max_term_depth: 3
proof_budget: 3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-dataset",
            "--config",
            str(config_path),
            "--output",
            str(dataset_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    exported = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "export-public-dataset",
            "--dataset",
            str(dataset_root),
            "--output",
            str(public_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(exported.stdout)
    manifest = json.loads((public_root / "manifest.json").read_text(encoding="utf-8"))
    world_root = next((public_root / "train" / "predicate_invention").iterdir())

    assert payload["output"] == str(public_root.resolve())
    assert manifest["public_export"] is True
    assert manifest["output_dir"] == str(public_root)
    assert not (world_root / "formal" / "targets_hidden.abw").exists()
    assert not (world_root / "formal" / "hidden_bridge.json").exists()
    assert not (world_root / "nl" / "hidden_bridge_private.md").exists()
    assert (world_root / "formal" / "axioms.abw").exists()
    assert (world_root / "nl" / "problem.md").exists()


def test_cli_run_benchmark_reports_target_failures(tmp_path) -> None:
    config_path = tmp_path / "benchmark_dataset.yaml"
    dataset_root = tmp_path / "benchmark_dataset"
    report_path = tmp_path / "benchmark_report.json"
    config_path.write_text(
        """
dataset_name: benchmark_smoke
version: 0.2.0
families: [predicate_invention]
splits:
  train: 1
start_seed: 11
max_term_depth: 3
proof_budget: 3
""".strip()
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-dataset",
            "--config",
            str(config_path),
            "--output",
            str(dataset_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "run-benchmark",
            "--dataset",
            str(dataset_root),
            "--target-command",
            sys.executable,
            "--target-command=-c",
            "--target-command=import sys; sys.exit(2)",
            "--output",
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["num_worlds"] == 1
    assert report["summary"]["completed"] == 0
    assert report["summary"]["failed_invocations"] == 1
    assert report["summary"]["primary_score"] == 0.0
    assert report["worlds"][0]["status"] == "invocation_failed"
    assert report["worlds"][0]["score"]["valid"] is False


def test_cli_generate_dataset_entrypoint(tmp_path) -> None:
    output_root = tmp_path / "dataset"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-dataset",
            "--config",
            "tests/fixtures/smoke.yaml",
            "--output",
            str(output_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(run.stdout)
    manifest_path = Path(payload["manifest"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["splits"] == {"dev": 7, "test_public": 7}
    assert manifest["examples_per_family"] == {"dev": 1, "test_public": 1}
    assert manifest["views"] == ["formal", "natural_language"]
    assert manifest["families"] == [
        "predicate_invention",
        "lemma_invention",
        "analogy",
        "invariant",
        "quotient",
        "normal_form",
        "multi_step",
    ]
    assert manifest["interactive"] == {"enabled": True, "query_budget": 20, "countermodels": True}


def test_generate_dataset_packages_backend_profile_into_worlds(tmp_path) -> None:
    config_path = tmp_path / "solver_dataset.yaml"
    output_root = tmp_path / "solver_dataset"
    config_path.write_text(
        """
dataset_name: solver_dataset
version: 0.2.0
families: [predicate_invention]
splits:
  train: 1
start_seed: 77
max_term_depth: 3
proof_budget: 3
prover_backend:
  name: subprocess
  command: [python3, -m, abw_core.prover.z3_driver]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-dataset",
            "--config",
            str(config_path),
            "--output",
            str(output_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    scoring = json.loads(
        (
            output_root
            / "train"
            / "predicate_invention"
            / "abw_train_0000"
            / "formal"
            / "scoring_config.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["prover_backend"] == {
        "name": "subprocess",
        "command": ["python3", "-m", "abw_core.prover.z3_driver"],
    }
    assert scoring["prover_backend"] == {
        "name": "subprocess",
        "command": ["python3", "-m", "abw_core.prover.z3_driver"],
    }


def test_generate_dataset_honors_split_examples_and_start_seeds(tmp_path) -> None:
    config_path = tmp_path / "balanced_dataset.yaml"
    output_root = tmp_path / "balanced_dataset"
    config_path.write_text(
        """
dataset_name: balanced_dataset
version: 0.2.0
families: [predicate_invention, lemma_invention]
splits:
  dev:
    examples_per_family: 1
    start_seed: 11
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
            "abw_core.cli",
            "generate-dataset",
            "--config",
            str(config_path),
            "--output",
            str(output_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8"))
    dev_metadata = json.loads(
        (output_root / "dev" / "predicate_invention" / "abw_dev_0000" / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    test_metadata = json.loads(
        (
            output_root
            / "test_public"
            / "predicate_invention"
            / "abw_test_public_0000"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )

    assert manifest["splits"] == {"dev": 2, "test_public": 2}
    assert manifest["examples_per_family"] == {"dev": 1, "test_public": 1}
    assert manifest["split_start_seeds"] == {"dev": 11, "test_public": 29}
    assert dev_metadata["seed"] == 11
    assert test_metadata["seed"] == 29
    assert manifest["diversity"]["schema_unique_per_family"] == {
        "predicate_invention": 2,
        "lemma_invention": 2,
    }
    assert manifest["diversity"]["content_unique_per_family"] == {
        "predicate_invention": 2,
        "lemma_invention": 2,
    }
    assert manifest["diversity"]["public_content_unique_per_family"] == {
        "predicate_invention": 2,
        "lemma_invention": 2,
    }
    assert manifest["diversity"]["schema_overlap_across_splits_per_family"] == {
        "predicate_invention": 0,
        "lemma_invention": 0,
    }


def test_module_entrypoint_supports_python_m_abw_core(tmp_path) -> None:
    world_root = tmp_path / "tiny_world"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "7",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(run.stdout)
    assert payload["output"] == str(world_root)


def test_score_candidate_reports_counterexamples_for_bad_lemma(tmp_path) -> None:
    world_root = tmp_path / "tiny_world"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "7",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    candidate_path = tmp_path / "bad_candidate.abw"
    candidate_path.write_text(
        """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_bad: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), y)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    score = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "score-candidate",
            "--world",
            str(world_root),
            "--candidate",
            str(candidate_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(score.stdout)
    assert report["valid"] is False
    assert report["counterexamples"]
    assert report["counterexamples"][0]["clause"] == "paironly_bad"


def test_cli_countermodel_goal_reports_bounded_model_for_failed_goal(tmp_path) -> None:
    world_root = tmp_path / "multi_step_world"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "multi_step",
            "--seed",
            "7",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "countermodel-goal",
            "--world",
            str(world_root),
            "--atoms",
            "A(f(f(f(f(f(c0))))))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    assert payload["proved"] is False
    assert payload["countermodel"] is not None
    assert payload["countermodel"]["label"] == "probe"
    assert payload["countermodel"]["false_atoms"]


def test_cli_score_candidate_supports_z3_backend(tmp_path) -> None:
    pytest.importorskip("z3")

    world_root = tmp_path / "tiny_world_z3"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "11",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    candidate_path = tmp_path / "bad_candidate_z3.abw"
    candidate_path.write_text(
        """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_bad: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), y)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "score-candidate",
            "--world",
            str(world_root),
            "--candidate",
            str(candidate_path),
            "--prover-backend",
            "z3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    assert payload["valid"] is False
    assert payload["counterexamples"]
    assert payload["counterexamples"][0]["backend"] == "z3"
    assert payload["counterexamples"][0]["model_kind"] == "finite"


def test_cli_score_candidate_supports_cvc5_backend(tmp_path) -> None:
    pytest.importorskip("cvc5")

    world_root = tmp_path / "tiny_world_cvc5"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "11",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    candidate_path = tmp_path / "bad_candidate_cvc5.abw"
    candidate_path.write_text(
        """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_bad: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), y)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "score-candidate",
            "--world",
            str(world_root),
            "--candidate",
            str(candidate_path),
            "--prover-backend",
            "cvc5",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    assert payload["valid"] is False
    assert payload["counterexamples"]
    assert payload["counterexamples"][0]["backend"] == "cvc5"
    assert payload["counterexamples"][0]["model_kind"] == "finite"


def test_cli_countermodel_goal_returns_none_when_goal_is_proved(tmp_path) -> None:
    world_root = tmp_path / "tiny_world"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "11",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "countermodel-goal",
            "--world",
            str(world_root),
            "--goal",
            "hidden_step_2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    assert payload["proved"] is True
    assert payload["countermodel"] is None


def test_cli_session_lifecycle(tmp_path) -> None:
    world_root = tmp_path / "tiny_world"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "7",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    bad_candidate = tmp_path / "bad_candidate.abw"
    bad_candidate.write_text(
        """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_bad: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), y)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    session_root = tmp_path / "interactive_session"

    started = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "start-session",
            "--world",
            str(world_root),
            "--output",
            str(session_root),
            "--query-budget",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    started_payload = json.loads(started.stdout)
    assert started_payload["query_budget"] == 2

    validate = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "session-query",
            "--session",
            str(session_root),
            "--kind",
            "validate",
            "--candidate",
            str(bad_candidate),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    validate_payload = json.loads(validate.stdout)
    assert validate_payload["accepted"] is True
    assert validate_payload["response"]["valid"] is False
    assert validate_payload["response"]["counterexamples"][0]["clause"] == "paironly_bad"

    examples = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "session-query",
            "--session",
            str(session_root),
            "--kind",
            "examples",
            "--candidate",
            "examples/predicate_invention/gold_candidate.abw",
            "--predicate",
            "PairStable",
            "--limit",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    examples_payload = json.loads(examples.stdout)
    assert examples_payload["accepted"] is True
    assert len(examples_payload["response"]["examples"]) == 2
    assert examples_payload["remaining_queries"] == 0

    exhausted = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "session-query",
            "--session",
            str(session_root),
            "--kind",
            "countermodel",
            "--atoms",
            "P0(c0)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    exhausted_payload = json.loads(exhausted.stdout)
    assert exhausted_payload["accepted"] is False
    assert exhausted_payload["error"] == "Query budget exhausted."

    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "finish-session",
            "--session",
            str(session_root),
            "--candidate",
            "examples/predicate_invention/gold_candidate.abw",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    finished_payload = json.loads(finished.stdout)
    assert finished_payload["final_report"]["valid"] is True
    assert finished_payload["exploration_efficiency_score"] == 0.0
    assert (session_root / "session.json").exists()
    assert (session_root / "transcript.jsonl").exists()
    assert (session_root / "final_report.json").exists()


def test_cli_session_equivalence_query(tmp_path) -> None:
    world_root = tmp_path / "tiny_world"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "generate-world",
            "--family",
            "predicate_invention",
            "--seed",
            "7",
            "--output",
            str(world_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    session_root = tmp_path / "interactive_session"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "start-session",
            "--world",
            str(world_root),
            "--output",
            str(session_root),
            "--query-budget",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-m",
            "abw_core.cli",
            "session-query",
            "--session",
            str(session_root),
            "--kind",
            "equivalence",
            "--candidate",
            "examples/predicate_invention/gold_candidate.abw",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    assert payload["accepted"] is True
    assert payload["response"]["valid"] is True
    assert payload["response"]["stability_score"] > 0.5
