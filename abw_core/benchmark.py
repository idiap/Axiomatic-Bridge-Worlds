# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Benchmark-task orchestration for evaluating external target systems on ABW.

The per-world evaluator already knows how to judge one ABW candidate against
one packaged world. This module lifts that local evaluator into a dataset-level
benchmark contract that an external system can participate in with a simple
stdin or stdout interface.

Core idea
---------
For each packaged world in the selected slice:

1. expose only the public artifacts to the target system
2. collect the candidate it emits
3. score that candidate against the hidden bridge and hidden targets
4. aggregate the results into report-ready metrics

This file therefore plays the role of benchmark harness rather than theorem
prover. It is the layer that turns a symbolic world generator plus evaluator
into a repeatable task surface for external systems.

Concrete example
----------------
A target adapter might receive a payload containing:
- paths to `signature.json`, `axioms.abw`, and public NL artifacts
- public metadata such as the family and seed

It then returns either raw ABW text or JSON of the form:

    {"candidate": "...abw text...", "metadata": {...}}

The benchmark runner scores that submission and folds it into dataset-level
metrics such as `primary_score`, coverage, latency, and family breakdowns.

Paper-style framing
-------------------
One compact way to describe this module is:

    The benchmark should evaluate systems on public problem statements while
    preserving one stable hidden scoring surface and one stable aggregation
    rule across the whole dataset.

That is why the request payload, failure handling, and aggregation logic are
all centralized here rather than scattered across scripts.

Limitations
-----------
- The runner is cooperative, not security-hard. A target process with broader
  filesystem access could still read private artifacts directly.
- Aggregation is deliberately simple and deterministic; it does not attempt
  confidence intervals or statistical significance testing.
- This file assumes packaged ABW worlds on disk rather than a remote dataset
  service.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any, Sequence

from abw_core.scorer import evaluate_candidate


BENCHMARK_PROTOCOL_VERSION = "abw_target_v1"
MAX_CAPTURE_CHARS = 4000
MAX_CANDIDATE_EXCERPT_CHARS = 4000
METRIC_KEYS = (
    "validity_score",
    "hidden_goal_solve_rate",
    "proof_cost_reduction",
    "compression_score",
    "semantic_equivalence_score",
    "novelty_score",
    "minimality_score",
    "candidate_size",
    "total_score",
)


@dataclass(frozen=True)
class BenchmarkWorldRef:
    """Reference one packaged world inside a benchmark slice.

    The benchmark loop repeatedly needs the same minimal identity bundle:
    which split the world belongs to, which family it instantiates, which world
    id names it, and where its packaged files live on disk.
    """

    split: str
    family: str
    world_id: str
    root: Path


@dataclass(frozen=True)
class TargetInvocationResult:
    """Capture one target invocation and the interpreted result surface.

    The benchmark needs more than raw stdout. It also needs timing, return
    status, decoded metadata, and compact excerpts that can be surfaced later
    in debugging reports without storing arbitrary large process output.
    """

    status: str
    duration_seconds: float
    returncode: int | None
    candidate_text: str | None
    response_metadata: Any
    error: str | None
    stderr_excerpt: str | None = None
    stdout_excerpt: str | None = None


def _truncate_text(text: str, *, limit: int = MAX_CAPTURE_CHARS) -> str:
    """Bound captured process output so benchmark reports stay inspectable.

    Large stderr dumps are useful during debugging but terrible inside stored
    reports. This helper preserves the existence of the message while keeping
    the artifact size manageable.
    """

    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _load_json(path: Path) -> Any:
    """Load one UTF-8 JSON artifact used by the benchmark harness.

    The file intentionally keeps JSON reads tiny and explicit because the
    benchmark relies on a small set of stable on-disk structured artifacts.
    """

    return json.loads(path.read_text(encoding="utf-8"))


def _dataset_manifest(dataset_root: Path) -> dict[str, Any] | None:
    """Return the dataset manifest when the selected root provides one.

    Some benchmark runs are launched from a full dataset root, while others may
    point directly at one packaged world. Returning `None` when no manifest is
    present lets both workflows share the same benchmark entrypoint.
    """

    manifest_path = dataset_root / "manifest.json"
    if not manifest_path.exists():
        return None
    payload = _load_json(manifest_path)
    return payload if isinstance(payload, dict) else None


def _world_metadata(world_root: Path) -> dict[str, Any]:
    """Load the public metadata for one packaged world.

    This metadata is part of the target-facing request because it contains
    public generation context such as family identity and depth settings.
    """

    metadata_path = world_root / "metadata.json"
    payload = _load_json(metadata_path)
    if not isinstance(payload, dict):
        raise ValueError(f"World metadata at {metadata_path} must be a JSON object.")
    return payload


def _required_artifact(path: Path) -> str:
    """Resolve one required public artifact into the target-facing payload.

    The benchmark contract communicates paths rather than inlining file
    contents. This helper keeps those paths absolute and fails early when a
    supposedly public artifact is missing from the package.
    """

    if not path.exists():
        raise ValueError(f"Missing required benchmark artifact: {path}")
    return str(path.resolve())


def _public_artifacts(world_root: Path) -> dict[str, dict[str, str]]:
    """Build the explicit public artifact surface exposed to target systems.

    The harness separates the world into formal and natural-language sections so
    adapters do not need to guess which files are intended for public use.
    """

    formal = world_root / "formal"
    nl = world_root / "nl"
    return {
        "formal": {
            "signature": _required_artifact(formal / "signature.json"),
            "axioms": _required_artifact(formal / "axioms.abw"),
            "visible_facts": _required_artifact(formal / "visible_facts.abw"),
            "visible_theorems": _required_artifact(formal / "visible_theorems.abw"),
            "targets_visible": _required_artifact(formal / "targets_visible.abw"),
        },
        "nl": {
            "problem": _required_artifact(nl / "problem.md"),
            "examples": _required_artifact(nl / "examples.md"),
            "theorem_cards": _required_artifact(nl / "theorem_cards.md"),
            "nl_alignment": _required_artifact(nl / "nl_alignment.json"),
        },
    }


def _request_payload(world: BenchmarkWorldRef) -> dict[str, Any]:
    """Assemble the protocol payload sent to one target-system invocation.

    The payload is intentionally self-describing: it includes protocol version,
    task name, world identity, public artifact locations, and output-shape
    guidance so external integrations can stay simple and explicit.
    """

    metadata = _world_metadata(world.root)
    return {
        "protocol_version": BENCHMARK_PROTOCOL_VERSION,
        "task_name": "axiomatic_bridge_worlds",
        "world_id": world.world_id,
        "split": world.split,
        "family": world.family,
        "public_artifacts": _public_artifacts(world.root),
        "metadata": metadata,
        "expected_output": {
            "preferred": {"candidate": "<abw text>", "metadata": {}},
            "compatibility_mode": "stdout may also be raw ABW candidate text",
        },
    }


def _zero_metrics() -> dict[str, float]:
    """Return the zero-filled metric frame for failed benchmark attempts.

    Benchmark aggregation is defined over the requested slice, not only over
    successful worlds. This helper provides the consistent all-zero metric
    scaffold used when no valid candidate could be scored.
    """

    return {key: 0.0 for key in METRIC_KEYS}


def _blank_score(error_message: str) -> dict[str, Any]:
    """Build a score-shaped failure payload for integration-side breakdowns.

    This lets invocation failures, malformed target outputs, and scorer-side
    exceptions all occupy the same structural slot in the final report.
    """

    return {
        "valid": False,
        "errors": [error_message],
        "metrics": _zero_metrics(),
        "goals": [],
        "counterexamples": [],
    }


def _decode_target_output(stdout_text: str) -> tuple[str | None, Any, str | None]:
    """Interpret target stdout under the benchmark's compatibility contract.

    The preferred contract is structured JSON, but raw candidate text is still
    accepted for lightweight adapters and quick experiments. The return value
    separates candidate text, optional metadata, and protocol errors so the
    caller can record failures cleanly.
    """

    payload = stdout_text.strip()
    if not payload:
        return None, None, "Target system produced no stdout payload."
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return payload, None, None
    if isinstance(decoded, str):
        return decoded, None, None
    if not isinstance(decoded, dict):
        return None, decoded, "Target stdout JSON must be either a string or an object."
    candidate = decoded.get("candidate")
    if not isinstance(candidate, str) or not candidate.strip():
        return None, decoded.get("metadata"), "Target stdout JSON must include a non-empty string field `candidate`."
    return candidate, decoded.get("metadata"), None


def _invoke_target(
    world: BenchmarkWorldRef,
    *,
    target_command: Sequence[str],
    timeout_seconds: float,
) -> TargetInvocationResult:
    """Run the evaluated system on one public benchmark instance.

    This function owns the operational boundary between ABW and the external
    system under evaluation. It serializes the public request, enforces the
    timeout, captures output, and normalizes common failure modes into one
    typed result object.
    """

    request = json.dumps(_request_payload(world))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(target_command),
            input=request,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        duration = time.monotonic() - started
        return TargetInvocationResult(
            status="launch_error",
            duration_seconds=duration,
            returncode=None,
            candidate_text=None,
            response_metadata=None,
            error=str(error),
        )
    except subprocess.TimeoutExpired as error:
        duration = time.monotonic() - started
        stdout_text = error.stdout if isinstance(error.stdout, str) else ""
        stderr_text = error.stderr if isinstance(error.stderr, str) else ""
        return TargetInvocationResult(
            status="timeout",
            duration_seconds=duration,
            returncode=None,
            candidate_text=None,
            response_metadata=None,
            error=f"Target system timed out after {timeout_seconds:.2f}s.",
            stdout_excerpt=_truncate_text(stdout_text) if stdout_text else None,
            stderr_excerpt=_truncate_text(stderr_text) if stderr_text else None,
        )

    duration = time.monotonic() - started
    stderr_excerpt = _truncate_text(completed.stderr) if completed.stderr else None
    stdout_excerpt = _truncate_text(completed.stdout) if completed.stdout else None
    if completed.returncode != 0:
        return TargetInvocationResult(
            status="nonzero_exit",
            duration_seconds=duration,
            returncode=completed.returncode,
            candidate_text=None,
            response_metadata=None,
            error=f"Target system exited with status {completed.returncode}.",
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
        )

    candidate_text, response_metadata, decode_error = _decode_target_output(completed.stdout)
    if decode_error is not None:
        return TargetInvocationResult(
            status="invalid_output",
            duration_seconds=duration,
            returncode=completed.returncode,
            candidate_text=None,
            response_metadata=response_metadata,
            error=decode_error,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
        )
    return TargetInvocationResult(
        status="ok",
        duration_seconds=duration,
        returncode=completed.returncode,
        candidate_text=candidate_text,
        response_metadata=response_metadata,
        error=None,
        stderr_excerpt=stderr_excerpt,
    )


def _candidate_digest(candidate_text: str | None) -> str | None:
    """Hash the submitted candidate so reports can identify repeats compactly.

    The benchmark report wants a stable submission fingerprint without bloating
    the artifact by embedding full candidate text for every world.
    """

    if candidate_text is None:
        return None
    return hashlib.sha256(candidate_text.encode("utf-8")).hexdigest()


def _candidate_artifact(candidate_text: str | None) -> dict[str, Any]:
    """Return the report-side raw candidate payload and compact excerpt.

    Benchmark reports are reproducibility artifacts, so they preserve the exact
    candidate text emitted by the target process. The bounded excerpt gives
    downstream inspectors a small field for tables and failure summaries
    without re-parsing the full text.
    """

    if candidate_text is None:
        return {"candidate_text": None, "candidate_excerpt": None}
    return {
        "candidate_text": candidate_text,
        "candidate_excerpt": _truncate_text(candidate_text, limit=MAX_CANDIDATE_EXCERPT_CHARS),
    }


def discover_worlds(
    dataset_root: str | Path,
    *,
    splits: Sequence[str] = (),
    families: Sequence[str] = (),
    world_id_contains: str | None = None,
    limit: int | None = None,
) -> tuple[BenchmarkWorldRef, ...]:
    """Discover packaged worlds from either a dataset root or one world root.

    This dual behavior makes the benchmark harness useful in two modes:
    full-dataset evaluation and ad hoc one-world debugging. The returned tuple
    is already normalized into the small `BenchmarkWorldRef` shape used by the
    runner.
    """

    root = Path(dataset_root).resolve()
    requested_splits = {str(item) for item in splits}
    requested_families = {str(item) for item in families}
    world_id_filter = str(world_id_contains) if world_id_contains else None

    if (root / "formal").is_dir() and (root / "nl").is_dir():
        metadata = _world_metadata(root)
        family = str(metadata.get("family", root.parent.name))
        if requested_families and family not in requested_families:
            return ()
        world_id = str(metadata.get("world_id", root.name))
        if world_id_filter and world_id_filter not in world_id:
            return ()
        split = root.parent.parent.name if root.parent.parent != root.parent else "adhoc"
        if requested_splits and split not in requested_splits:
            return ()
        worlds = (BenchmarkWorldRef(split=split, family=family, world_id=world_id, root=root),)
        return worlds[:limit] if limit is not None else worlds

    if not root.exists():
        raise ValueError(f"Benchmark dataset root does not exist: {root}")

    discovered: list[BenchmarkWorldRef] = []
    for split_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        split = split_dir.name
        if requested_splits and split not in requested_splits:
            continue
        for family_dir in sorted(path for path in split_dir.iterdir() if path.is_dir()):
            family = family_dir.name
            if requested_families and family not in requested_families:
                continue
            for world_dir in sorted(path for path in family_dir.iterdir() if path.is_dir()):
                if not (world_dir / "formal").is_dir():
                    continue
                if world_id_filter and world_id_filter not in world_dir.name:
                    continue
                discovered.append(
                    BenchmarkWorldRef(
                        split=split,
                        family=family,
                        world_id=world_dir.name,
                        root=world_dir.resolve(),
                    )
                )
                if limit is not None and len(discovered) >= limit:
                    return tuple(discovered)
    if not discovered:
        raise ValueError(f"No packaged benchmark worlds were found under {root}.")
    return tuple(discovered)


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Return the simple percentile summary used for latency reporting.

    The benchmark only needs a lightweight latency readout, so a ceiling-based
    percentile is enough and keeps the aggregation rules easy to explain.
    """

    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _aggregate_records(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one scored slice into the benchmark summary structure.

    This is the dataset-level scoring rule for ABW benchmark reports. It
    combines semantic metrics, validity, coverage, and latency into the summary
    shape later consumed by the LaTeX renderer and any downstream analysis.

    Important design choice:
    failed worlds stay in the denominator. That keeps the benchmark honest
    about reliability rather than rewarding systems that only succeed when they
    manage to produce a valid answer.
    """

    count = len(records)
    durations = [float(record["target"]["duration_seconds"]) for record in records]
    completed = sum(1 for record in records if record["status"] == "scored")
    failed_invocations = sum(1 for record in records if record["status"] == "invocation_failed")
    scoring_failures = sum(1 for record in records if record["status"] == "scoring_failed")
    valid_submissions = sum(1 for record in records if bool(record["score"]["valid"]))
    invalid_submissions = completed - valid_submissions

    summary: dict[str, Any] = {
        "num_worlds": count,
        "attempted": count,
        "completed": completed,
        "failed_invocations": failed_invocations,
        "scoring_failures": scoring_failures,
        "valid_submissions": valid_submissions,
        "invalid_submissions": invalid_submissions,
        "coverage": (completed / count) if count else 0.0,
        "mean_latency_seconds": (sum(durations) / count) if count else 0.0,
        "p95_latency_seconds": _percentile(durations, 0.95),
    }
    for metric_key in METRIC_KEYS:
        mean_value = (
            sum(float(record["score"]["metrics"].get(metric_key, 0.0)) for record in records) / count if count else 0.0
        )
        summary[f"mean_{metric_key}"] = mean_value
    summary["primary_score"] = summary["mean_total_score"]
    return summary


def _group_summary(records: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    """Aggregate the benchmark slice by a grouping key such as split or family.

    The returned mapping powers the familiar per-split and per-family summary
    tables found in the benchmark report surface.
    """

    labels = sorted({str(record[key]) for record in records})
    return {
        label: _aggregate_records([record for record in records if record[key] == label])
        for label in labels
    }


def run_benchmark(
    dataset_root: str | Path,
    *,
    target_command: Sequence[str],
    splits: Sequence[str] = (),
    families: Sequence[str] = (),
    world_id_contains: str | None = None,
    limit: int | None = None,
    timeout_seconds: float = 60.0,
    backend_name: str | None = None,
    backend_command: Sequence[str] = (),
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run one target system across a packaged dataset and return the full report.

    This is the main public benchmark entrypoint. It discovers the selected
    worlds, invokes the target once per world, routes candidate text through
    the evaluator, records per-world artifacts, and finally emits a benchmark
    report that can be serialized directly or rendered into LaTeX.
    """

    root = Path(dataset_root).resolve()
    worlds = discover_worlds(
        root,
        splits=splits,
        families=families,
        world_id_contains=world_id_contains,
        limit=limit,
    )
    records: list[dict[str, Any]] = []
    for world in worlds:
        # Each world is treated as an independent protocol round so the final
        # report can localize crashes, malformed outputs, and scoring failures.
        invocation = _invoke_target(
            world,
            target_command=target_command,
            timeout_seconds=timeout_seconds,
        )
        integration_error = invocation.error
        status = "invocation_failed"
        if invocation.candidate_text is not None:
            try:
                score = evaluate_candidate(
                    world.root,
                    invocation.candidate_text,
                    backend_name=backend_name,
                    backend_command=tuple(backend_command),
                )
            except Exception as error:  # noqa: BLE001
                integration_error = f"Scoring failed: {error}"
                score = _blank_score(integration_error)
                status = "scoring_failed"
            else:
                status = "scored"
        else:
            score = _blank_score(integration_error or "Target system did not produce a candidate.")

        records.append(
            {
                "world_id": world.world_id,
                "split": world.split,
                "family": world.family,
                "world_root": str(world.root),
                "status": status,
                "integration_error": integration_error,
                "candidate_sha256": _candidate_digest(invocation.candidate_text),
                "candidate_size_chars": len(invocation.candidate_text) if invocation.candidate_text is not None else 0,
                **_candidate_artifact(invocation.candidate_text),
                "target": {
                    "status": invocation.status,
                    "returncode": invocation.returncode,
                    "duration_seconds": invocation.duration_seconds,
                    "stderr_excerpt": invocation.stderr_excerpt,
                    "stdout_excerpt": invocation.stdout_excerpt,
                    "response_metadata": invocation.response_metadata,
                },
                "score": score,
            }
        )

    report = {
        "task": {
            "name": "axiomatic_bridge_worlds",
            "protocol_version": BENCHMARK_PROTOCOL_VERSION,
        },
        "dataset": {
            "root": str(root),
            "manifest": _dataset_manifest(root),
            "selected_splits": list(splits),
            "selected_families": list(families),
            "limit": limit,
        },
        "target": {
            "command": list(target_command),
            "timeout_seconds": timeout_seconds,
        },
        "scoring": {
            "backend_override": {
                "name": backend_name,
                "command": list(backend_command),
            }
            if backend_name is not None
            else None
        },
        "summary": _aggregate_records(records),
        "by_split": _group_summary(records, "split"),
        "by_family": _group_summary(records, "family"),
        "worlds": records,
    }

    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
