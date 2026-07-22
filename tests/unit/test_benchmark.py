# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Unit coverage for the dataset-level benchmark orchestration layer."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from abw_core.benchmark import BENCHMARK_PROTOCOL_VERSION, discover_worlds, run_benchmark
from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.packager import package_world


def _packaged_dataset(tmp_path: Path) -> Path:
    """Create a one-world packaged dataset for benchmark-level tests."""

    dataset_root = tmp_path / "dataset"
    world = generate_world(
        WorldGenerationRequest(
            family="predicate_invention",
            seed=7,
            world_id="abw_train_0000",
        )
    )
    package_world(world, dataset_root / "train" / "predicate_invention" / "abw_train_0000")
    return dataset_root


def test_discover_worlds_finds_packaged_dataset_worlds(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)

    worlds = discover_worlds(dataset_root)

    assert len(worlds) == 1
    assert worlds[0].split == "train"
    assert worlds[0].family == "predicate_invention"
    assert worlds[0].world_id == "abw_train_0000"


def test_discover_worlds_can_filter_by_family(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)

    worlds = discover_worlds(dataset_root, families=("predicate_invention",))

    assert len(worlds) == 1
    assert worlds[0].family == "predicate_invention"


def test_discover_worlds_rejects_family_filter_with_no_matches(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)

    with pytest.raises(ValueError, match="No packaged benchmark worlds"):
        discover_worlds(dataset_root, families=("lemma_invention",))


def test_run_benchmark_accepts_raw_candidate_stdout(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)
    report_path = tmp_path / "benchmark_report.json"
    candidate_path = (Path.cwd() / "examples" / "predicate_invention" / "gold_candidate.abw").resolve()

    report = run_benchmark(
        dataset_root,
        target_command=(
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                f"sys.stdout.write(Path(r'{candidate_path}').read_text(encoding='utf-8'))"
            ),
        ),
        output_path=report_path,
    )

    written = json.loads(report_path.read_text(encoding="utf-8"))
    record = report["worlds"][0]
    written_record = written["worlds"][0]
    assert report["task"]["protocol_version"] == BENCHMARK_PROTOCOL_VERSION
    assert report["summary"]["num_worlds"] == 1
    assert report["summary"]["completed"] == 1
    assert report["summary"]["valid_submissions"] == 1
    assert record["candidate_text"] == candidate_path.read_text(encoding="utf-8").strip()
    assert record["candidate_excerpt"] == record["candidate_text"]
    assert written_record["candidate_text"] == record["candidate_text"]
    assert written["summary"]["primary_score"] == report["summary"]["primary_score"]


def test_run_benchmark_records_null_candidate_text_for_invocation_failure(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)

    report = run_benchmark(
        dataset_root,
        target_command=(sys.executable, "-c", "import sys; sys.exit(2)"),
    )

    record = report["worlds"][0]
    assert record["status"] == "invocation_failed"
    assert record["candidate_text"] is None
    assert record["candidate_excerpt"] is None
    assert record["candidate_sha256"] is None
    assert record["candidate_size_chars"] == 0


def test_run_benchmark_forwards_and_verifies_evaluation_contract(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)
    candidate_path = (Path.cwd() / "examples" / "predicate_invention" / "gold_candidate.abw").resolve()
    prompt_condition = "zero_shot_cross_track_nl_to_formal"

    report = run_benchmark(
        dataset_root,
        target_command=(
            sys.executable,
            "-c",
            (
                "import json,sys; from pathlib import Path; request=json.load(sys.stdin); "
                f"candidate=Path(r'{candidate_path}').read_text(encoding='utf-8'); "
                "json.dump({'candidate': candidate, 'metadata': request['evaluation']}, sys.stdout)"
            ),
        ),
        prompt_condition=prompt_condition,
    )

    assert report["target"]["prompt_condition"] == prompt_condition
    assert report["summary"]["contract_failures"] == 0
    assert report["worlds"][0]["status"] == "scored"
    assert report["worlds"][0]["target"]["response_metadata"] == {
        "prompt_condition": prompt_condition,
        "exemplar_bank": None,
    }


def test_run_benchmark_rejects_adapter_condition_mismatch(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)
    candidate_path = (Path.cwd() / "examples" / "predicate_invention" / "gold_candidate.abw").resolve()

    report = run_benchmark(
        dataset_root,
        target_command=(
            sys.executable,
            "-c",
            (
                "import json,sys; from pathlib import Path; json.load(sys.stdin); "
                f"candidate=Path(r'{candidate_path}').read_text(encoding='utf-8'); "
                "json.dump({'candidate': candidate, 'metadata': "
                "{'prompt_condition': 'zero_shot_formal_direct', 'exemplar_bank': None}}, sys.stdout)"
            ),
        ),
        prompt_condition="zero_shot_cross_track_nl_to_formal",
    )

    record = report["worlds"][0]
    assert record["status"] == "contract_failed"
    assert record["score"]["metrics"]["total_score"] == 0.0
    assert report["summary"]["completed"] == 0
    assert report["summary"]["contract_failures"] == 1
    assert "expected 'zero_shot_cross_track_nl_to_formal'" in record["integration_error"]


def test_run_benchmark_rejects_exemplar_bank_without_condition(tmp_path: Path) -> None:
    dataset_root = _packaged_dataset(tmp_path)

    with pytest.raises(ValueError, match="requires a declared prompt condition"):
        run_benchmark(
            dataset_root,
            target_command=(sys.executable, "-c", "pass"),
            exemplar_bank="configs/examples.json",
        )
