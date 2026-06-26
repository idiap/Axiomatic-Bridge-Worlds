# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Summarize paired robustness benchmark reports."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_METRICS = (
    "validity_score",
    "hidden_goal_solve_rate",
    "total_score",
)


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}.")
    return payload


def _metric(record: Mapping[str, Any], metric: str) -> float:
    score = record.get("score", {})
    metrics = score.get("metrics", {}) if isinstance(score, Mapping) else {}
    if not isinstance(metrics, Mapping):
        return 0.0
    try:
        return float(metrics.get(metric, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _world_index(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    worlds = report.get("worlds", [])
    if not isinstance(worlds, list):
        return {}
    return {
        str(record.get("world_id")): record
        for record in worlds
        if isinstance(record, Mapping) and record.get("world_id") is not None
    }


def _paired_metric_drops(
    original_report: Mapping[str, Any],
    perturbed_report: Mapping[str, Any],
    *,
    metrics: Sequence[str],
) -> dict[str, Any]:
    original = _world_index(original_report)
    perturbed = _world_index(perturbed_report)
    paired_ids = sorted(set(original) & set(perturbed))
    rows: dict[str, dict[str, float]] = {}
    for metric in metrics:
        original_values = [_metric(original[world_id], metric) for world_id in paired_ids]
        perturbed_values = [_metric(perturbed[world_id], metric) for world_id in paired_ids]
        drops = [original_value - perturbed_value for original_value, perturbed_value in zip(original_values, perturbed_values)]
        rows[metric] = {
            "mean_original": sum(original_values) / len(original_values) if original_values else 0.0,
            "mean_perturbed": sum(perturbed_values) / len(perturbed_values) if perturbed_values else 0.0,
            "mean_drop": sum(drops) / len(drops) if drops else 0.0,
            "min_drop": min(drops) if drops else 0.0,
            "max_drop": max(drops) if drops else 0.0,
        }
    return {
        "paired_worlds": len(paired_ids),
        "unpaired_original_worlds": sorted(set(original) - set(perturbed)),
        "unpaired_perturbed_worlds": sorted(set(perturbed) - set(original)),
        "metrics": rows,
    }


def _merge_reports(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    worlds: list[Mapping[str, Any]] = []
    for report in reports:
        report_worlds = report.get("worlds", [])
        if isinstance(report_worlds, list):
            worlds.extend(record for record in report_worlds if isinstance(record, Mapping))
    return {"worlds": [dict(record) for record in worlds]}


def _outcome_counts(report: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    worlds = report.get("worlds", [])
    if not isinstance(worlds, list):
        return counts
    for record in worlds:
        if not isinstance(record, Mapping):
            continue
        if record.get("status") != "scored":
            target = record.get("target", {})
            target_status = str(target.get("status", "unknown")) if isinstance(target, Mapping) else "unknown"
            outcome = f"invocation_failed:{target_status}"
        else:
            score = record.get("score", {})
            outcome = "valid" if isinstance(score, Mapping) and score.get("valid") else "invalid_candidate"
        counts[outcome] = counts.get(outcome, 0) + 1
    return dict(sorted(counts.items()))


def _has_invocation_failures(counts: Mapping[str, int]) -> bool:
    return any(key.startswith("invocation_failed:") and value > 0 for key, value in counts.items())


def _metric_row(row: Mapping[str, Any], metric: str) -> Mapping[str, Any]:
    metrics = row.get("metrics", {})
    if not isinstance(metrics, Mapping):
        return {}
    value = metrics.get(metric, {})
    return value if isinstance(value, Mapping) else {}


def _report_path(entry: Mapping[str, Any]) -> Path | None:
    value = entry.get("report")
    return Path(value) if isinstance(value, str) and value else None


def summarize_robustness_plan(
    plan: Mapping[str, Any],
    *,
    metrics: Sequence[str] = DEFAULT_METRICS,
) -> dict[str, Any]:
    """Summarize completed reports from a generic robustness plan."""

    original_by_family: dict[str, dict[str, Any]] = {}
    missing_reports: list[dict[str, Any]] = []
    for run in plan.get("original_runs", []):
        if not isinstance(run, Mapping):
            continue
        family = str(run.get("family"))
        path = _report_path(run)
        if path is None or not path.exists():
            missing_reports.append({"role": "original", "family": family, "report": str(path) if path else None})
            continue
        original_by_family[family] = _load_json(path)

    rows: list[dict[str, Any]] = []
    perturbed_by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for run in plan.get("runs", []):
        if not isinstance(run, Mapping):
            continue
        family = str(run.get("family"))
        perturbation = str(run.get("perturbation"))
        original = original_by_family.get(family)
        path = _report_path(run)
        if original is None:
            missing_reports.append({"role": "original", "family": family, "perturbation": perturbation})
            continue
        if path is None or not path.exists():
            missing_reports.append(
                {"role": "perturbed", "family": family, "perturbation": perturbation, "report": str(path) if path else None}
            )
            continue
        perturbed = _load_json(path)
        analysis = _paired_metric_drops(original, perturbed, metrics=metrics)
        analysis.update(
            {
                "perturbation": perturbation,
                "family": family,
                "original_report": str(_report_path(next(item for item in plan.get("original_runs", []) if isinstance(item, Mapping) and str(item.get("family")) == family))),
                "perturbed_report": str(path),
                "original_outcome_counts": _outcome_counts(original),
                "perturbed_outcome_counts": _outcome_counts(perturbed),
            }
        )
        analysis["paper_usable"] = (
            analysis["paired_worlds"] > 0
            and not analysis["unpaired_original_worlds"]
            and not analysis["unpaired_perturbed_worlds"]
            and not _has_invocation_failures(analysis["perturbed_outcome_counts"])
        )
        rows.append(analysis)
        perturbed_by_kind.setdefault(perturbation, []).extend(_world_index(perturbed).values())

    merged_original = _merge_reports(list(original_by_family.values()))
    aggregate_by_perturbation = {
        perturbation: _paired_metric_drops(merged_original, {"worlds": [dict(record) for record in records]}, metrics=metrics)
        for perturbation, records in sorted(perturbed_by_kind.items())
    }
    quality_failures: list[str] = []
    if missing_reports:
        quality_failures.append(f"{len(missing_reports)} report(s) are missing")
    bad_rows = [row for row in rows if not row.get("paper_usable")]
    if bad_rows:
        quality_failures.append(f"{len(bad_rows)} paired robustness row(s) failed the usability gate")
    return {
        "analysis": "abw_generic_robustness_summary",
        "experiment": plan.get("experiment"),
        "base_dataset_root": plan.get("base_dataset_root"),
        "split": plan.get("split"),
        "families": plan.get("families"),
        "perturbations": plan.get("perturbations"),
        "target_command": plan.get("target_command"),
        "metrics": list(metrics),
        "completed_report_count": len(rows),
        "missing_report_count": len(missing_reports),
        "rows": rows,
        "aggregate_by_perturbation": aggregate_by_perturbation,
        "quality_gate": {
            "paper_usable": not quality_failures,
            "failures": quality_failures,
            "note": "Drops are original-minus-perturbed and require matched world ids plus scored target outputs.",
        },
        "missing_reports": missing_reports,
    }


def write_csv(summary: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "perturbation",
        "family",
        "paired_worlds",
        "paper_usable",
        "validity_score_mean_original",
        "validity_score_mean_perturbed",
        "validity_score_mean_drop",
        "hidden_goal_solve_rate_mean_original",
        "hidden_goal_solve_rate_mean_perturbed",
        "hidden_goal_solve_rate_mean_drop",
        "total_score_mean_original",
        "total_score_mean_perturbed",
        "total_score_mean_drop",
        "original_report",
        "perturbed_report",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary.get("rows", []):
            if not isinstance(row, Mapping):
                continue
            output_row = {
                "perturbation": row.get("perturbation"),
                "family": row.get("family"),
                "paired_worlds": row.get("paired_worlds"),
                "paper_usable": row.get("paper_usable"),
                "original_report": row.get("original_report"),
                "perturbed_report": row.get("perturbed_report"),
            }
            for metric in DEFAULT_METRICS:
                metric_values = _metric_row(row, metric)
                for key in ("mean_original", "mean_perturbed", "mean_drop"):
                    output_row[f"{metric}_{key}"] = metric_values.get(key, 0.0)
            writer.writerow(output_row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize a generic ABW robustness benchmark plan.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output")
    parser.add_argument("--metric", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    metrics = tuple(args.metric or DEFAULT_METRICS)
    summary = summarize_robustness_plan(_load_json(args.plan), metrics=metrics)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if args.csv_output:
        write_csv(summary, Path(args.csv_output))
    print(
        json.dumps(
            {
                "output": str(output),
                "csv_output": args.csv_output,
                "completed_report_count": summary["completed_report_count"],
                "missing_report_count": summary["missing_report_count"],
                "paper_usable": summary["quality_gate"]["paper_usable"],
            },
            indent=2,
        )
    )
    return 0 if summary["quality_gate"]["paper_usable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
