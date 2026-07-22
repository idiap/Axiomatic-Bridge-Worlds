# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# SPDX-License-Identifier: MIT

"""Tests for resumable failed-invocation repairs."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import retry_failed_invocations as retry_script


def _record(world_root: Path, *, status: str) -> dict[str, object]:
    return {
        "world_id": world_root.name,
        "world_root": str(world_root),
        "split": "test_public",
        "family": "quotient",
        "status": status,
        "target": {"status": "ok" if status == "scored" else "error", "duration_seconds": 0.0},
        "score": {"valid": status == "scored", "metrics": {}},
    }


def test_retry_report_checkpoints_each_completed_world(tmp_path: Path, monkeypatch, capsys) -> None:
    report_path = tmp_path / "quotient_report.json"
    world_roots = (tmp_path / "world-a", tmp_path / "world-b")
    report_path.write_text(
        json.dumps(
            {
                "target": {"command": ["dummy-target"], "timeout_seconds": 30.0},
                "worlds": [_record(path, status="invocation_failed") for path in world_roots],
            }
        ),
        encoding="utf-8",
    )
    calls = 0

    def fake_run_benchmark(world_root: str, **_kwargs) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            checkpoint = json.loads(report_path.read_text(encoding="utf-8"))
            assert [record["status"] for record in checkpoint["worlds"]] == ["scored", "invocation_failed"]
        return {"worlds": [_record(Path(world_root), status="scored")]}

    monkeypatch.setattr(retry_script, "run_benchmark", fake_run_benchmark)

    result = retry_script.retry_report(
        report_path,
        timeout_seconds=None,
        target_max_tokens=None,
        target_max_output_tokens=8000,
        target_context_tokens=None,
        dry_run=False,
    )

    repaired = json.loads(report_path.read_text(encoding="utf-8"))
    assert calls == 2
    assert result["failed_after"] == 0
    assert [record["status"] for record in repaired["worlds"]] == ["scored", "scored"]
    assert not report_path.with_name(f".{report_path.name}.retry_tmp").exists()
    output = capsys.readouterr().out
    assert "RETRY START 1/2 world=world-a" in output
    assert "RETRY DONE 2/2 world=world-b status=scored target_status=ok failed_remaining=0" in output
