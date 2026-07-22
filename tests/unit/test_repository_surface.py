# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Regression checks for the public repository surface.

These tests keep the publishable-open-source scaffolding from drifting away as
the runtime evolves.
"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


DISCLOSURE_FAMILIES = {
    "analogy",
    "invariant",
    "lemma_invention",
    "multi_step",
    "normal_form",
    "predicate_invention",
    "quotient",
}


SPDX_HEADER = """# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT
"""


def test_repository_surface_files_exist() -> None:
    for relative_path in (
        "CITATION.cff",
        "DISCLOSURE.md",
        "EVALUATION.md",
        "LICENSES/MIT.txt",
        "REUSE.toml",
        ".gitattributes",
        "docs/repository_layout.md",
        "configs/README.md",
        "dataset/README.md",
        "examples/README.md",
        "scripts/README.md",
        "tests/README.md",
    ):
        assert Path(relative_path).exists(), relative_path


def test_readme_links_repository_layout_and_citation() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "[Repository Layout](docs/repository_layout.md)" in readme
    assert "[Citation Metadata](CITATION.cff)" in readme
    assert "docs/reuse_compliance.md" not in readme


def test_docs_index_links_repository_layout_and_citation() -> None:
    docs_index = Path("docs/index.md").read_text(encoding="utf-8")

    assert "[Repository Layout](repository_layout.md)" in docs_index
    assert "[Citation Metadata](../CITATION.cff)" in docs_index
    assert "reuse_compliance.md" not in docs_index


def test_contributing_carries_maintainer_reuse_guidance() -> None:
    contributing = Path("CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "REUSE.toml" in contributing
    assert "LICENSES/MIT.txt" in contributing
    assert "reuse lint" in contributing


def test_spdx_license_texts_exist_for_used_identifiers() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    license_ids: set[str] = set()
    pattern = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.-]+)")

    for line in result.stdout.splitlines():
        path = Path(line)
        if not path.exists() or path.is_dir():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        license_ids.update(pattern.findall(text))

    assert license_ids
    for license_id in license_ids:
        assert Path("LICENSES", f"{license_id}.txt").exists(), license_id
    assert not Path("LICENSE").exists()


def test_project_concepts_uses_tracked_examples_for_family_refs() -> None:
    concepts = Path("docs/project_concepts.md").read_text(encoding="utf-8")

    assert "../examples/predicate_invention/gold_candidate.abw" in concepts
    assert "datasets/generated_benchmark_1000" not in concepts


def test_disclosure_branch_does_not_track_generated_data_or_stage_artifacts() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = set(result.stdout.splitlines())
    assert not any(path.startswith("artifacts/") for path in tracked)
    assert not Path("datasets").exists()
    assert not any(path.startswith("datasets/") for path in tracked)
    assert ("configs/" + "model_" + "matrix_" + "formal_" + "direct.json") not in tracked
    assert ("scripts/" + "run_" + "formal_" + "direct_experiment.py") not in tracked
    public_scripts = {
        "build_few_shot_exemplar_bank.py",
        "build_paired_difficulty_dataset.py",
        "example_target_system.py",
        "generate_perturbed_dataset.py",
        "install_seeded_v2_dataset.py",
        "model_target.py",
        "retry_failed_invocations.py",
        "robustness_plan.py",
        "run_benchmark.py",
        "run_experiment.py",
        "score_candidate.py",
        "validate_world.py",
    }
    assert {path.name for path in Path("scripts").glob("*.py")} == public_scripts
    assert ("abw_core/" + "model_" + "matrix.py") not in tracked
    assert ("docs/" + "concept_" + "paper.tex") not in tracked
    assert ("docs/" + "concept_" + "paper.pdf") not in tracked
    assert ("docs/" + "open_source_" + "reference.md") not in tracked
    assert ("." + "git" + "lab-ci.yml") not in tracked
    platform_dir = "." + "git" + "lab/"
    assert not any(path.startswith(platform_dir) for path in tracked)
    assert {
        Path(path).stem
        for path in tracked
        if path.startswith("abw_core/generator/families/") and path.endswith(".py") and not path.endswith("__init__.py")
    } == DISCLOSURE_FAMILIES


def test_public_benchmark_surface_is_json_only() -> None:
    assert not Path("abw_core/benchmark_reporting.py").exists()
    cli_source = Path("abw_core/cli.py").read_text(encoding="utf-8")
    for removed_surface in (
        "render-benchmark-report",
        "--latex-output",
        "--pdf-output",
        "--compile-report-pdf",
    ):
        assert removed_surface not in cli_source


def test_docs_do_not_advertise_pruned_paper_or_platform_files() -> None:
    public_docs = [
        Path("README.md"),
        Path("docs/index.md"),
        Path("docs/repository_layout.md"),
        Path("docs/structured_artifacts.md"),
        Path("CONTRIBUTING.md"),
    ]

    for path in public_docs:
        text = path.read_text(encoding="utf-8")
        assert ("concept_" + "paper") not in text, path
        assert ("open_source_" + "reference") not in text, path
        assert ("docs/" + "generated") not in text, path
        assert ("Git" + "Lab") not in text, path


def test_source_and_config_files_carry_spdx_header() -> None:
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "*.py",
            "*.yaml",
            "*.yml",
            "*.toml",
            "*.ebnf",
            "Makefile",
            ".gitignore",
            ".gitattributes",
            "CITATION.cff",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tracked_paths = [Path(line) for line in result.stdout.splitlines() if line and Path(line).exists()]

    assert tracked_paths
    for path in tracked_paths:
        text = path.read_text(encoding="utf-8")
        if text.startswith("#!"):
            _, _, text = text.partition("\n")
        assert text.startswith(SPDX_HEADER), path
