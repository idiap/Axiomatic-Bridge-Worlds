# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Validate and run one ABW model evaluation experiment.

Evaluates one target model adapter command against a packaged paper-core
dataset through the benchmark protocol, then writes JSON results and a
manifest describing the run. Works for any prompt condition (formal direct,
natural-language direct, or cross-track NL-to-formal) and any target adapter
command supplied via `--target-command` — the script does not hard-code a
model, provider, or prompt condition. `--prompt-condition` and
`--exemplar-bank` are recorded as run metadata only; if your adapter needs to
know them, pass them as part of `--target-command`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from abw_core.benchmark import discover_worlds, run_benchmark
from abw_core.packager import validate_package


DEFAULT_DATASET_ROOT = REPO_ROOT / "dataset" / "abw-formal-nl-core"
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts"
PROMPT_CONDITION_TO_TRACK = {
    "zero_shot_formal_direct": "formal_direct",
    "few_shot_formal_direct": "formal_direct",
    "family_few_shot_formal_direct": "formal_direct",
    "zero_shot_natural_language_direct": "natural_language_direct",
    "few_shot_natural_language_direct": "natural_language_direct",
    "family_few_shot_natural_language_direct": "natural_language_direct",
    "zero_shot_cross_track_nl_to_formal": "cross_track",
    "few_shot_cross_track_nl_to_formal": "cross_track",
    "family_few_shot_cross_track_nl_to_formal": "cross_track",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and run one model against a packaged ABW dataset."
    )
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT))
    parser.add_argument(
        "--target-command",
        action="append",
        required=True,
        default=[],
        help="Repeat once per token to define the evaluated model's adapter command, "
        "e.g. --target-command python --target-command scripts/model_target.py",
    )
    parser.add_argument(
        "--model-label",
        default="model",
        help="Human-readable tag used only to name default output files and the experiment id.",
    )
    parser.add_argument("--output", help="Defaults to artifacts/<track>/<model-label>_results.json")
    parser.add_argument("--manifest-output", help="Defaults to artifacts/<track>/<model-label>_manifest.json")
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--family", action="append", default=[])
    parser.add_argument("--world-id-contains")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument(
        "--prompt-condition",
        default="zero_shot_formal_direct",
        help="Free-text run label recorded in the manifest and used for the output directory, "
        "e.g. zero_shot_cross_track_nl_to_formal.",
    )
    parser.add_argument("--exemplar-bank", help="Optional exemplar-bank path recorded in the manifest.")
    return parser


def _validate_dataset(
    dataset_root: Path,
    *,
    splits: tuple[str, ...],
    families: tuple[str, ...],
    world_id_contains: str | None,
    limit: int | None,
) -> dict[str, object]:
    worlds = discover_worlds(
        dataset_root,
        splits=splits,
        families=families,
        world_id_contains=world_id_contains,
        limit=limit,
    )
    failures: list[dict[str, object]] = []
    for world in worlds:
        report = validate_package(world.root)
        if not report.get("valid", False):
            failures.append({"world_id": world.world_id, "world_root": str(world.root), "report": report})
    return {"valid": not failures, "num_worlds": len(worlds), "failures": failures}


def _git_commit() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return None
    return completed.stdout.strip() or None


def _safe_experiment_fragment(value: str) -> str:
    return value.replace(":", "_").replace("/", "_").replace("-", "_").replace(".", "_")


def _write_manifest(
    path: Path,
    *,
    dataset_root: Path,
    results_path: Path,
    selected_splits: tuple[str, ...],
    selected_families: tuple[str, ...],
    world_id_contains: str | None,
    limit: int | None,
    timeout_seconds: float,
    prompt_condition: str,
    exemplar_bank: str | None,
    target_command: tuple[str, ...],
    model_label: str,
    experiment_id: str,
    validation: dict[str, object],
    summary: dict[str, object],
) -> dict[str, object]:
    manifest = {
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_label": model_label,
        "dataset": {
            "root": str(dataset_root),
            "selected_splits": list(selected_splits),
            "selected_families": list(selected_families),
            "world_id_contains": world_id_contains,
            "limit": limit,
        },
        "run": {
            "timeout_seconds": timeout_seconds,
            "prompt_condition": prompt_condition,
            "exemplar_bank": exemplar_bank,
            "target_command": list(target_command),
            "git_commit": _git_commit(),
        },
        "outputs": {
            "results": str(results_path),
        },
        "validation": validation,
        "summary": summary,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dataset_root = Path(args.dataset_root)
    target = tuple(args.target_command)
    track = PROMPT_CONDITION_TO_TRACK.get(args.prompt_condition, args.prompt_condition)
    model_fragment = _safe_experiment_fragment(args.model_label)
    experiment_id = f"abw_{track}_{model_fragment}"

    run_dir = DEFAULT_ARTIFACTS_ROOT / track
    results_path = Path(args.output) if args.output else run_dir / f"{model_fragment}_results.json"
    manifest_path = (
        Path(args.manifest_output) if args.manifest_output else run_dir / f"{model_fragment}_manifest.json"
    )

    selected_splits = tuple(args.split) if args.split else ("test_public",)
    selected_families = tuple(args.family) if args.family else ()

    validation = _validate_dataset(
        dataset_root,
        splits=selected_splits,
        families=selected_families,
        world_id_contains=args.world_id_contains,
        limit=args.limit,
    )
    if not validation["valid"]:
        print(json.dumps({"validation": validation}, indent=2), file=sys.stderr)
        return 1

    results = run_benchmark(
        dataset_root,
        target_command=target,
        splits=selected_splits,
        families=selected_families,
        world_id_contains=args.world_id_contains,
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
        output_path=results_path,
    )

    payload: dict[str, object] = {
        "dataset_root": str(dataset_root),
        "validation": validation,
        "results": str(results_path),
        "summary": results["summary"],
    }
    manifest = _write_manifest(
        manifest_path,
        dataset_root=dataset_root,
        results_path=results_path,
        selected_splits=selected_splits,
        selected_families=selected_families,
        world_id_contains=args.world_id_contains,
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
        prompt_condition=args.prompt_condition,
        exemplar_bank=args.exemplar_bank,
        target_command=target,
        model_label=args.model_label,
        experiment_id=experiment_id,
        validation=validation,
        summary=results["summary"],
    )
    payload["manifest"] = str(manifest_path)
    payload["experiment_id"] = manifest["experiment_id"]
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
