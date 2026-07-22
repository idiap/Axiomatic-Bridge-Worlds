# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Build a model-agnostic robustness benchmark plan.

The disclosure branch keeps robustness as a public benchmark workflow rather
than a paper-run provider script. This planner emits the commands needed to:

1. build conservative perturbed copies of a packaged ABW dataset
2. run the same target adapter on the original and perturbed datasets
3. save paired benchmark JSON results for later analysis
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "abw_robustness" / "robustness_plan.json"
DEFAULT_RESULTS_DIR = REPO_ROOT / "artifacts" / "abw_robustness"
DEFAULT_PERTURBED_ROOT = REPO_ROOT / "artifacts" / "abw_perturbed"
PAPER_FAMILIES = (
    "predicate_invention",
    "lemma_invention",
    "analogy",
    "invariant",
    "quotient",
    "normal_form",
    "multi_step",
)
PERTURBATIONS = (
    "alpha_renaming",
    "axiom_order_shuffle",
    "nl_paraphrase",
    "distractor_insertion",
)


def _shell_join(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _safe_name(value: str) -> str:
    return value.replace("/", "_").replace(":", "_").replace("-", "_")


def _perturbation_command(base_dataset_root: Path, perturbed_dataset_root: Path, perturbation: str) -> list[str]:
    return [
        "python",
        "scripts/generate_perturbed_dataset.py",
        "--source",
        str(base_dataset_root),
        "--output",
        str(perturbed_dataset_root / perturbation),
        "--perturbation",
        perturbation,
    ]


def _benchmark_command(
    *,
    dataset_root: Path,
    results_path: Path,
    split: str,
    family: str,
    target_command: Sequence[str],
    timeout_seconds: float,
    limit: int | None,
    prover_backend: str | None,
    backend_command: Sequence[str],
) -> list[str]:
    command = [
        "python",
        "-m",
        "abw_core",
        "run-benchmark",
        "--dataset",
        str(dataset_root),
        "--split",
        split,
        "--family",
        family,
        "--timeout-seconds",
        str(timeout_seconds),
        "--output",
        str(results_path),
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])
    if prover_backend:
        command.extend(["--prover-backend", prover_backend])
    command.extend(f"--backend-command={token}" for token in backend_command)
    command.extend(f"--target-command={token}" for token in target_command)
    return command


def _run_entry(
    *,
    role: str,
    dataset_root: Path,
    results_dir: Path,
    split: str,
    family: str,
    target_command: Sequence[str],
    timeout_seconds: float,
    limit_per_family: int | None,
    prover_backend: str | None,
    backend_command: Sequence[str],
    perturbation: str | None = None,
) -> dict[str, Any]:
    stem_parts = [role]
    if perturbation:
        stem_parts.append(_safe_name(perturbation))
    stem_parts.extend([_safe_name(split), _safe_name(family)])
    results_path = results_dir / ("_".join(stem_parts) + "_results.json")
    command = _benchmark_command(
        dataset_root=dataset_root,
        results_path=results_path,
        split=split,
        family=family,
        target_command=target_command,
        timeout_seconds=timeout_seconds,
        limit=limit_per_family,
        prover_backend=prover_backend,
        backend_command=backend_command,
    )
    return {
        "role": role,
        "status": "runnable",
        "split": split,
        "family": family,
        "perturbation": perturbation,
        "dataset_root": str(dataset_root),
        "results": str(results_path),
        "command": command,
        "shell": _shell_join(command),
    }


def build_robustness_plan(
    *,
    base_dataset_root: Path,
    perturbed_dataset_root: Path,
    results_dir: Path,
    split: str,
    families: Sequence[str],
    perturbations: Sequence[str],
    target_command: Sequence[str],
    timeout_seconds: float,
    limit_per_family: int | None,
    prover_backend: str | None = None,
    backend_command: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a generic paired robustness run plan."""

    if not target_command:
        raise ValueError("target_command must contain at least one command token.")
    unknown_families = sorted(set(families) - set(PAPER_FAMILIES))
    if unknown_families:
        raise ValueError(f"Unsupported family in robustness plan: {', '.join(unknown_families)}.")
    unknown_perturbations = sorted(set(perturbations) - set(PERTURBATIONS))
    if unknown_perturbations:
        raise ValueError(f"Unsupported perturbation in robustness plan: {', '.join(unknown_perturbations)}.")

    generation_steps = [
        {
            "role": "generate_perturbation",
            "status": "runnable",
            "perturbation": perturbation,
            "output_root": str(perturbed_dataset_root / perturbation),
            "command": command,
            "shell": _shell_join(command),
        }
        for perturbation in perturbations
        for command in [_perturbation_command(base_dataset_root, perturbed_dataset_root, perturbation)]
    ]
    original_runs = [
        _run_entry(
            role="original",
            dataset_root=base_dataset_root,
            results_dir=results_dir,
            split=split,
            family=family,
            target_command=target_command,
            timeout_seconds=timeout_seconds,
            limit_per_family=limit_per_family,
            prover_backend=prover_backend,
            backend_command=backend_command,
        )
        for family in families
    ]
    runs = [
        _run_entry(
            role="perturbed",
            perturbation=perturbation,
            dataset_root=perturbed_dataset_root / perturbation,
            results_dir=results_dir,
            split=split,
            family=family,
            target_command=target_command,
            timeout_seconds=timeout_seconds,
            limit_per_family=limit_per_family,
            prover_backend=prover_backend,
            backend_command=backend_command,
        )
        for perturbation in perturbations
        for family in families
    ]
    return {
        "experiment": "abw_generic_robustness",
        "base_dataset_root": str(base_dataset_root),
        "perturbed_dataset_root": str(perturbed_dataset_root),
        "results_dir": str(results_dir),
        "split": split,
        "families": list(families),
        "perturbations": list(perturbations),
        "target_command": list(target_command),
        "timeout_seconds": timeout_seconds,
        "limit_per_family": limit_per_family,
        "scoring_backend": {
            "name": prover_backend,
            "command": list(backend_command),
        }
        if prover_backend
        else None,
        "generation_steps": generation_steps,
        "original_runs": original_runs,
        "runs": runs,
        "execution_note": (
            "Run generation_steps first, then original_runs and runs. Every benchmark command uses the "
            "public run-benchmark target adapter protocol and can evaluate any model exposed through the "
            "provided target command."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a generic ABW robustness benchmark plan.")
    parser.add_argument("--base-dataset-root", required=True)
    parser.add_argument("--perturbed-dataset-root", default=str(DEFAULT_PERTURBED_ROOT))
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--split", default="test_public")
    parser.add_argument("--family", action="append", default=[])
    parser.add_argument("--perturbation", action="append", default=[])
    parser.add_argument("--target-command", action="append", required=True, default=[])
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--limit-per-family", type=int)
    parser.add_argument("--prover-backend")
    parser.add_argument("--backend-command", action="append", default=[])
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    families = tuple(args.family or PAPER_FAMILIES)
    perturbations = tuple(args.perturbation or PERTURBATIONS)
    plan = build_robustness_plan(
        base_dataset_root=Path(args.base_dataset_root),
        perturbed_dataset_root=Path(args.perturbed_dataset_root),
        results_dir=Path(args.results_dir),
        split=args.split,
        families=families,
        perturbations=perturbations,
        target_command=tuple(args.target_command),
        timeout_seconds=args.timeout_seconds,
        limit_per_family=args.limit_per_family,
        prover_backend=args.prover_backend,
        backend_command=tuple(args.backend_command),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "generation_steps": len(plan["generation_steps"]),
                "original_runs": len(plan["original_runs"]),
                "perturbed_runs": len(plan["runs"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
