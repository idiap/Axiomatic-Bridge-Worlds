# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Summarize C0-C6 paired difficulty-shape benchmark reports."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_METRICS = (
    "validity_score",
    "hidden_goal_solve_rate",
    "semantic_equivalence_score",
    "total_score",
)


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _metric(record: Mapping[str, Any], metric: str) -> float:
    score = record.get("score", {})
    metrics = score.get("metrics", {}) if isinstance(score, Mapping) else {}
    return _number(metrics.get(metric)) if isinstance(metrics, Mapping) else 0.0


def _metadata(record: Mapping[str, Any]) -> Mapping[str, Any]:
    world_root = record.get("world_root")
    if not isinstance(world_root, str):
        return {}
    metadata_path = Path(world_root) / "metadata.json"
    if not metadata_path.exists():
        return {}
    payload = _load_json(metadata_path)
    return payload if isinstance(payload, Mapping) else {}


def _report_paths(reports: Sequence[str], report_dir: str | None) -> list[Path]:
    paths = [Path(report) for report in reports]
    if report_dir:
        directory = Path(report_dir)
        paths.extend(sorted(directory.glob("*_report.json")))
    if not paths:
        raise ValueError("Provide at least one --report or --report-dir.")
    return paths


def _report_name(path: Path, names: Sequence[str], index: int) -> str:
    if index < len(names):
        return names[index]
    stem = path.stem
    return stem[:-7] if stem.endswith("_report") else stem


def _shape_row(report_name: str, report_path: Path, record: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = _metadata(record)
    level_id = metadata.get("paired_difficulty_level_id")
    if not isinstance(level_id, str):
        return None
    row = {
        "report_name": report_name,
        "report_path": str(report_path),
        "world_id": record.get("world_id"),
        "family": record.get("family"),
        "base_key": metadata.get("paired_difficulty_base_key", record.get("world_id")),
        "difficulty_level_index": int(metadata.get("paired_difficulty_level_index", 0)),
        "difficulty_level_id": level_id,
        "difficulty_level_label": metadata.get("paired_difficulty_level_label", level_id),
        "requested_controls": metadata.get("paired_difficulty_requested_controls", []),
        "status": record.get("status"),
        "valid": bool(record.get("score", {}).get("valid")) if isinstance(record.get("score"), Mapping) else False,
    }
    for metric in DEFAULT_METRICS:
        row[metric] = _metric(record, metric)
    return row


def _with_clean_drops(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baselines: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        if int(row["difficulty_level_index"]) == 0:
            baselines[(str(row["report_name"]), str(row["base_key"]))] = {
                metric: float(row[metric]) for metric in DEFAULT_METRICS
            }
    enriched: list[dict[str, Any]] = []
    for row in rows:
        baseline = baselines.get((str(row["report_name"]), str(row["base_key"])), {})
        updated = dict(row)
        for metric in DEFAULT_METRICS:
            updated[f"{metric}_clean_baseline"] = baseline.get(metric, float(row[metric]))
            updated[f"{metric}_drop_from_c0"] = updated[f"{metric}_clean_baseline"] - float(row[metric])
        enriched.append(updated)
    return enriched


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _group_summary(rows: Sequence[dict[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(tuple(str(row.get(key, "")) for key in keys), []).append(row)
    summary_rows: list[dict[str, Any]] = []
    for key_values, group_rows in grouped.items():
        first = group_rows[0]
        summary = {key: value for key, value in zip(keys, key_values)}
        summary.update(
            {
                "difficulty_level_index": first["difficulty_level_index"],
                "difficulty_level_id": first["difficulty_level_id"],
                "difficulty_level_label": first["difficulty_level_label"],
                "n": len(group_rows),
                "valid_rate": _mean([1.0 if row["valid"] else 0.0 for row in group_rows]),
            }
        )
        for metric in DEFAULT_METRICS:
            summary[f"mean_{metric}"] = _mean([float(row[metric]) for row in group_rows])
            summary[f"mean_{metric}_drop_from_c0"] = _mean(
                [float(row[f"{metric}_drop_from_c0"]) for row in group_rows]
            )
        summary_rows.append(summary)
    return sorted(
        summary_rows,
        key=lambda row: (
            str(row.get("report_name", "")),
            str(row.get("family", "")),
            int(row.get("difficulty_level_index", 0)),
        ),
    )


def summarize_reports(paths: Sequence[Path], *, names: Sequence[str] = ()) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    skipped_records = 0
    for index, report_path in enumerate(paths):
        report = _load_json(report_path)
        if not isinstance(report, Mapping):
            continue
        report_name = _report_name(report_path, names, index)
        worlds = report.get("worlds", [])
        if not isinstance(worlds, list):
            continue
        for record in worlds:
            if not isinstance(record, Mapping):
                skipped_records += 1
                continue
            row = _shape_row(report_name, report_path, record)
            if row is None:
                skipped_records += 1
                continue
            rows.append(row)
    rows = _with_clean_drops(rows)
    return {
        "analysis": "abw_paired_difficulty_shape_summary",
        "reports": [str(path) for path in paths],
        "num_rows": len(rows),
        "skipped_records": skipped_records,
        "by_level": _group_summary(rows, ("report_name", "difficulty_level_id")),
        "by_family_level": _group_summary(rows, ("report_name", "family", "difficulty_level_id")),
        "rows": rows,
    }


def write_csv(summary: Mapping[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "report_name",
        "family",
        "base_key",
        "world_id",
        "difficulty_level_index",
        "difficulty_level_id",
        "difficulty_level_label",
        "valid",
        "status",
        "total_score",
        "total_score_clean_baseline",
        "total_score_drop_from_c0",
        "validity_score",
        "hidden_goal_solve_rate",
        "semantic_equivalence_score",
        "requested_controls",
        "report_path",
    ]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in summary.get("rows", []):
            if isinstance(row, Mapping):
                writer.writerow({field: row.get(field, "") for field in fieldnames})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize C0-C6 ABW difficulty-shape reports.")
    parser.add_argument("--report", action="append", default=[])
    parser.add_argument("--report-dir")
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--csv-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _report_paths(args.report, args.report_dir)
    summary = summarize_reports(paths, names=tuple(args.name))
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
                "num_rows": summary["num_rows"],
                "skipped_records": summary["skipped_records"],
            },
            indent=2,
        )
    )
    return 0 if summary["num_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
