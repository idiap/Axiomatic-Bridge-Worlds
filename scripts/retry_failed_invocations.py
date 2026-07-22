# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Retry failed ABW benchmark invocations inside existing JSON result files.

This is intentionally narrower than a full experiment rerun: it finds records
whose benchmark status is not ``scored``, invokes the same target command on
only those world roots, replaces those records, and recomputes JSON summaries.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from abw_core.benchmark import _aggregate_records, _group_summary, run_benchmark


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _localize_repo_path(value: str) -> str:
    """Map stale absolute paths from another checkout onto this repository."""

    normalized = value
    marker = "/theory-creation/"
    if marker in normalized:
        suffix = normalized.split(marker, 1)[1]
        candidate = REPO_ROOT / suffix
        if candidate.exists():
            return str(candidate)
    return normalized


def _iter_report_paths(values: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        expanded = sorted(REPO_ROOT.glob(value)) if any(ch in value for ch in "*?[]") else []
        if expanded:
            paths.extend(path for path in expanded if path.is_file())
        else:
            path = _resolve(value)
            if not path.exists():
                raise FileNotFoundError(path)
            paths.append(path)
    return sorted(dict.fromkeys(path.resolve() for path in paths))


def _target_command(report: Mapping[str, Any]) -> tuple[str, ...]:
    target = report.get("target")
    if not isinstance(target, Mapping):
        raise ValueError("Report has no target object")
    command = target.get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise ValueError("Report target.command must be a string list")
    localized = list(command)
    for index, part in enumerate(localized):
        part = _localize_repo_path(part)
        localized[index] = part
    return tuple(localized)


def _set_command_option(command: tuple[str, ...], option: str, value: str) -> tuple[str, ...]:
    """Return command with one CLI option replaced or appended."""

    parts = list(command)
    if option in parts:
        index = parts.index(option)
        if index + 1 < len(parts):
            parts[index + 1] = value
        else:
            parts.append(value)
    else:
        parts.extend([option, value])
    return tuple(parts)


def _target_timeout(report: Mapping[str, Any], override: float | None) -> float:
    if override is not None:
        return override
    target = report.get("target")
    if isinstance(target, Mapping):
        value = target.get("timeout_seconds")
        if isinstance(value, (int, float)):
            return float(value)
    return 900.0


def _target_evaluation_contract(report: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Recover the original condition contract for a failed-world retry."""

    target = report.get("target")
    if not isinstance(target, Mapping):
        return None, None
    prompt_condition = target.get("prompt_condition")
    exemplar_bank = target.get("exemplar_bank")
    if prompt_condition is not None and not isinstance(prompt_condition, str):
        raise ValueError("Report target.prompt_condition must be a string or null")
    if exemplar_bank is not None and not isinstance(exemplar_bank, str):
        raise ValueError("Report target.exemplar_bank must be a string or null")
    return prompt_condition, exemplar_bank


def _manifest_path_for_report(report_path: Path) -> Path:
    name = report_path.name
    if name.endswith("_results.json"):
        return report_path.with_name(name[: -len("_results.json")] + "_manifest.json")
    if name.endswith("_report.json"):
        return report_path.with_name(name[: -len("_report.json")] + "_manifest.json")
    return report_path.with_name(report_path.stem + "_manifest.json")


def _backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".retry_backup_{stamp}")
    shutil.copyfile(path, backup)
    return backup


def _refresh_report_summaries(report: dict[str, Any], records: list[Any]) -> None:
    report["summary"] = _aggregate_records(records)
    report["by_split"] = _group_summary(records, "split")
    report["by_family"] = _group_summary(records, "family")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.retry_tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def retry_report(
    report_path: Path,
    *,
    timeout_seconds: float | None,
    target_max_tokens: int | None,
    target_max_output_tokens: int | None,
    target_context_tokens: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    report = _load_json(report_path)
    records = report.get("worlds")
    if not isinstance(records, list):
        raise ValueError(f"Report has no worlds list: {report_path}")

    failed_indices = [
        index
        for index, record in enumerate(records)
        if isinstance(record, Mapping) and record.get("status") != "scored"
    ]
    result: dict[str, Any] = {
        "report": str(report_path),
        "failed_before": len(failed_indices),
        "attempts": [],
        "dry_run": dry_run,
    }
    if not failed_indices:
        return result

    command = _target_command(report)
    if target_max_tokens is not None:
        command = _set_command_option(command, "--max-tokens", str(target_max_tokens))
    if target_max_output_tokens is not None:
        command = _set_command_option(command, "--max-output-tokens", str(target_max_output_tokens))
    if target_context_tokens is not None:
        command = _set_command_option(command, "--context-tokens", str(target_context_tokens))
    timeout = _target_timeout(report, timeout_seconds)
    prompt_condition, exemplar_bank = _target_evaluation_contract(report)
    if dry_run:
        result["world_ids"] = [records[index].get("world_id") for index in failed_indices if isinstance(records[index], Mapping)]
        return result

    backup = _backup(report_path)
    result["backup"] = str(backup)

    for attempt_number, index in enumerate(failed_indices, start=1):
        record = records[index]
        if not isinstance(record, Mapping):
            continue
        world_id = record.get("world_id")
        print(
            f"RETRY START {attempt_number}/{len(failed_indices)} world={world_id}",
            flush=True,
        )
        world_root = record.get("world_root")
        if not isinstance(world_root, str):
            result["attempts"].append(
                {
                    "index": index,
                    "world_id": record.get("world_id"),
                    "status": "skipped",
                    "reason": "missing world_root",
                }
            )
            print(
                f"RETRY SKIP {attempt_number}/{len(failed_indices)} world={world_id} reason=missing_world_root",
                flush=True,
            )
            continue
        world_root = _localize_repo_path(world_root)
        retry = run_benchmark(
            world_root,
            target_command=command,
            timeout_seconds=timeout,
            prompt_condition=prompt_condition,
            exemplar_bank=exemplar_bank,
        )
        retry_records = retry.get("worlds", [])
        if not isinstance(retry_records, list) or len(retry_records) != 1:
            raise RuntimeError(f"Retry did not produce exactly one record for {world_root}")
        replacement = retry_records[0]
        replacement_target = replacement.get("target")
        target_status = replacement_target.get("status") if isinstance(replacement_target, Mapping) else None
        records[index] = replacement
        result["attempts"].append(
            {
                "index": index,
                "world_id": replacement.get("world_id"),
                "old_status": record.get("status"),
                "new_status": replacement.get("status"),
                "target_status": target_status,
            }
        )

        # Persist each completed world so a preemption or timeout loses at most
        # the in-flight invocation rather than the entire family repair.
        _refresh_report_summaries(report, records)
        _write_json_atomic(report_path, report)
        failed_remaining = sum(
            1
            for item in records
            if isinstance(item, Mapping) and item.get("status") != "scored"
        )
        print(
            "RETRY DONE "
            f"{attempt_number}/{len(failed_indices)} world={replacement.get('world_id')} "
            f"status={replacement.get('status')} "
            f"target_status={target_status} "
            f"failed_remaining={failed_remaining}",
            flush=True,
        )

    _refresh_report_summaries(report, records)
    failed_after = sum(
        1
        for record in records
        if isinstance(record, Mapping) and record.get("status") != "scored"
    )
    repair_record = {
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_backup": str(backup),
        "failed_before": len(failed_indices),
        "failed_after": failed_after,
        "attempts": result["attempts"],
    }
    history = report.setdefault("retry_history", [])
    if isinstance(history, list):
        history.append(repair_record)
    _write_json_atomic(report_path, report)

    manifest_path = _manifest_path_for_report(report_path)
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        manifest["summary"] = report["summary"]
        repairs = manifest.setdefault("retry_history", [])
        if isinstance(repairs, list):
            repairs.append(repair_record)
        _write_json_atomic(manifest_path, manifest)
        result["manifest"] = str(manifest_path)

    result["failed_after"] = failed_after
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        action="append",
        required=True,
        help="JSON results path or glob relative to repo root.",
    )
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("--target-max-tokens", type=int)
    parser.add_argument("--target-max-output-tokens", type=int)
    parser.add_argument("--target-context-tokens", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-log")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report_paths = _iter_report_paths(args.results)
    results = [
        retry_report(
            path,
            timeout_seconds=args.timeout_seconds,
            target_max_tokens=args.target_max_tokens,
            target_max_output_tokens=args.target_max_output_tokens,
            target_context_tokens=args.target_context_tokens,
            dry_run=args.dry_run,
        )
        for path in report_paths
    ]
    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "report_count": len(report_paths),
        "attempted_retry_count": sum(len(result.get("attempts", [])) for result in results),
        "results": results,
    }
    if args.output_log:
        output = _resolve(args.output_log)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
