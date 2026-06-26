# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Unit coverage for the LaTeX benchmark-report renderer.

These tests keep the reporting layer honest without depending on a real TeX
toolchain. They validate escaping, file emission, and the optional compile hook
through a tiny fake compiler command.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from abw_core.benchmark_reporting import (
    compile_latex_report,
    render_benchmark_report_latex,
    render_benchmark_reports_latex,
    write_benchmark_report_latex,
)
from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.packager import package_world


def _sample_report() -> dict[str, object]:
    """Build a compact but realistic benchmark report fixture."""

    return {
        "task": {"name": "axiomatic_bridge_worlds", "protocol_version": "abw_target_v1"},
        "dataset": {
            "root": "/tmp/demo_dataset",
            "manifest": {
                "dataset_name": "demo_dataset",
                "version": "0.2.0",
                "families": ["predicate_invention", "analogy"],
            },
            "selected_splits": ["test_public"],
            "limit": 2,
        },
        "target": {
            "command": ["python", "scripts/example_target_system.py"],
            "timeout_seconds": 60.0,
        },
        "scoring": {"backend_override": None},
        "summary": {
            "num_worlds": 2,
            "completed": 2,
            "failed_invocations": 0,
            "scoring_failures": 0,
            "valid_submissions": 1,
            "coverage": 1.0,
            "mean_latency_seconds": 0.45,
            "p95_latency_seconds": 0.6,
            "primary_score": 0.5,
            "mean_validity_score": 0.5,
            "mean_hidden_goal_solve_rate": 0.5,
            "mean_proof_cost_reduction": 0.25,
            "mean_compression_score": 0.75,
            "mean_semantic_equivalence_score": 1.0,
            "mean_novelty_score": 0.4,
            "mean_minimality_score": 0.8,
            "mean_candidate_size": 12.5,
            "mean_total_score": 0.5,
        },
        "by_split": {
            "test_public": {
                "num_worlds": 2,
                "completed": 2,
                "failed_invocations": 0,
                "scoring_failures": 0,
                "valid_submissions": 1,
                "coverage": 1.0,
                "mean_latency_seconds": 0.45,
                "primary_score": 0.5,
            }
        },
        "by_family": {
            "predicate_invention": {
                "num_worlds": 1,
                "completed": 1,
                "failed_invocations": 0,
                "scoring_failures": 0,
                "valid_submissions": 1,
                "coverage": 1.0,
                "mean_latency_seconds": 0.4,
                "primary_score": 1.0,
            },
            "analogy": {
                "num_worlds": 1,
                "completed": 1,
                "failed_invocations": 0,
                "scoring_failures": 0,
                "valid_submissions": 0,
                "coverage": 1.0,
                "mean_latency_seconds": 0.5,
                "primary_score": 0.0,
            },
        },
        "worlds": [
            {
                "world_id": "abw_test_public_0000",
                "split": "test_public",
                "family": "predicate_invention",
                "status": "scored",
                "integration_error": None,
                "target": {"status": "ok", "duration_seconds": 0.4},
                "score": {"valid": True, "errors": [], "metrics": {"total_score": 1.0}},
            },
            {
                "world_id": "abw_test_public_0001",
                "split": "test_public",
                "family": "analogy",
                "status": "scored",
                "integration_error": None,
                "target": {"status": "ok", "duration_seconds": 0.5},
                "score": {
                    "valid": False,
                    "errors": ["candidate uses hidden_symbol_name"],
                    "metrics": {"total_score": 0.0},
                },
            },
        ],
    }


def _package_world(tmp_path: Path, family: str, seed: int) -> Path:
    """Generate and package one small world for reporting tests."""

    world_id = f"abw_{family}_{seed}"
    world = generate_world(WorldGenerationRequest(family=family, seed=seed, world_id=world_id))
    return package_world(world, tmp_path / world_id)


def test_render_benchmark_report_latex_contains_expected_sections() -> None:
    report = _sample_report()

    rendered = render_benchmark_report_latex(report, title="Demo Report", issue_limit=5)

    assert r"\begin{document}" in rendered
    assert "Demo Report" in rendered
    assert "Split Summary" in rendered
    assert "Family Summary" in rendered
    assert "World Issues" in rendered
    assert r"demo\_dataset" in rendered
    assert r"predicate\_invention" in rendered
    assert r"hidden\_symbol\_name" in rendered


def test_render_benchmark_report_latex_adds_enriched_dataset_sections(tmp_path) -> None:
    predicate_world = _package_world(tmp_path, "predicate_invention", 11)
    analogy_world = _package_world(tmp_path, "analogy", 12)
    report = _sample_report()
    report["worlds"] = [
        {
            "world_id": "abw_predicate_invention_11",
            "split": "test_public",
            "family": "predicate_invention",
            "world_root": str(predicate_world),
            "status": "scored",
            "integration_error": None,
            "target": {"status": "ok", "duration_seconds": 0.4},
            "score": {
                "valid": True,
                "errors": [],
                "metrics": {
                    "validity_score": 1.0,
                    "hidden_goal_solve_rate": 1.0,
                    "proof_cost_reduction": 0.5,
                    "compression_score": 0.5,
                    "semantic_equivalence_score": 1.0,
                    "novelty_score": 0.4,
                    "minimality_score": 0.8,
                    "candidate_size": 9.0,
                    "total_score": 0.8,
                },
            },
        },
        {
            "world_id": "abw_analogy_12",
            "split": "test_public",
            "family": "analogy",
            "world_root": str(analogy_world),
            "status": "scored",
            "integration_error": None,
            "target": {"status": "ok", "duration_seconds": 0.5},
            "score": {
                "valid": True,
                "errors": [],
                "metrics": {
                    "validity_score": 1.0,
                    "hidden_goal_solve_rate": 1.0,
                    "proof_cost_reduction": 0.3,
                    "compression_score": 0.4,
                    "semantic_equivalence_score": 1.0,
                    "novelty_score": 0.5,
                    "minimality_score": 0.7,
                    "candidate_size": 12.0,
                    "total_score": 0.7,
                },
            },
        },
    ]

    rendered = render_benchmark_report_latex(report, title="Rich Report", issue_limit=5)

    assert "Task Class Breakdown" in rendered
    assert "Complexity Breakdown" in rendered
    assert "Challenge Portrait" in rendered
    assert "Dataset Descriptive Statistics" in rendered
    assert "Bridge Invention" in rendered
    assert "Analogical Transport" in rendered
    assert "Public facts" in rendered
    assert "Max term depth" in rendered


def test_write_benchmark_report_latex_emits_tex_file(tmp_path) -> None:
    report_path = tmp_path / "benchmark_report.json"
    output_path = tmp_path / "benchmark_report.tex"
    report_path.write_text(json.dumps(_sample_report(), indent=2) + "\n", encoding="utf-8")

    written = write_benchmark_report_latex(report_path, output_path, title="Smoke Report")

    assert written == output_path.resolve()
    content = output_path.read_text(encoding="utf-8")
    assert "Smoke Report" in content
    assert "Metric Means" in content


def test_render_benchmark_report_fragment_omits_document_wrapper() -> None:
    report = _sample_report()

    rendered = render_benchmark_report_latex(report, title="Fragment Report", fragment=True)

    assert r"\begin{document}" not in rendered
    assert "% Generated by `python -m abw_core render-benchmark-report`." in rendered
    assert "Run Overview" in rendered


def test_write_benchmark_report_latex_supports_multi_report_comparison(tmp_path) -> None:
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    output_path = tmp_path / "comparison.tex"
    left_report = _sample_report()
    right_report = _sample_report()
    right_report["summary"]["primary_score"] = 0.75
    right_report["by_family"]["analogy"]["primary_score"] = 0.5
    left_path.write_text(json.dumps(left_report, indent=2) + "\n", encoding="utf-8")
    right_path.write_text(json.dumps(right_report, indent=2) + "\n", encoding="utf-8")

    written = write_benchmark_report_latex(
        [left_path, right_path],
        output_path,
        report_names=("baseline", "solver"),
        comparison_metric="primary_score",
        fragment=True,
    )

    assert written == output_path.resolve()
    content = output_path.read_text(encoding="utf-8")
    assert "Run Comparison" in content
    assert "Family Comparison" in content
    assert "baseline" in content
    assert "solver" in content
    assert r"predicate\_invention" in content
    assert r"\begin{document}" not in content


def test_render_benchmark_reports_latex_rejects_unknown_comparison_metric() -> None:
    report = _sample_report()

    try:
        render_benchmark_reports_latex([report, report], comparison_metric="mystery_metric")
    except ValueError as error:
        assert "Unsupported comparison metric" in str(error)
    else:
        raise AssertionError("Expected ValueError for an unsupported comparison metric.")


def test_compile_latex_report_supports_custom_command(tmp_path) -> None:
    tex_path = tmp_path / "benchmark_report.tex"
    pdf_path = tmp_path / "benchmark_report.pdf"
    tex_path.write_text(r"\documentclass{article}\begin{document}ok\end{document}", encoding="utf-8")

    compile_latex_report(
        tex_path,
        pdf_output_path=pdf_path,
        compile_command=(
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[2]).write_bytes(b'%PDF-1.4\\n%% test\\n')",
            "{tex}",
            "{pdf}",
        ),
    )

    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF-1.4")
