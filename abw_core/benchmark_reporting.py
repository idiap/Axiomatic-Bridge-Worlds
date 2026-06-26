# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Render benchmark-result JSON into LaTeX tables that read like a paper report.

The benchmark runner already emits a machine-readable JSON artifact. That JSON
is perfect for tooling, but not for readers who want to understand a run at a
glance, compare systems, or drop results into a manuscript. This module turns
that structured report into a compact human-facing document.

Conceptually, the file has three jobs:

1. read and normalize benchmark-report payloads
2. derive reader-facing summaries such as task classes and complexity bands
3. render those summaries into reusable LaTeX longtables and optional PDFs

Concrete example
----------------
Given one benchmark report, this file can produce:
- a run overview table
- a metric summary table
- split and family breakdowns
- structural-complexity slices
- a short appendix of notable failures

Given several reports, it can instead produce comparison tables by family and
split for one selected metric.

Paper-style framing
-------------------
The reporting philosophy here is:

    The benchmark harness should decide the numbers once; every later document
    should inherit those numbers rather than re-aggregate them in ad hoc ways.

That is why the LaTeX layer reuses the JSON report as the single source of
truth and restricts itself to transparent, deterministic post-processing.

Limitations
-----------
- Rich structural analyses require the packaged `world_root` directories to
  still be present when the report is rendered.
- Complexity levels are relative to the selected run, not global difficulty
  calibrations across all possible ABW corpora.
- The LaTeX renderer favors interpretability over extreme formatting freedom.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

from abw_core.benchmark import METRIC_KEYS
from abw_core.packager import load_world


DEFAULT_COMPILE_COMMAND: tuple[str, ...] = ("tectonic", "--outdir", "{outdir}", "{tex}")
FAMILY_CLASS_LABELS: Mapping[str, str] = {
    "predicate_invention": "Bridge Invention",
    "lemma_invention": "Bridge Invention",
    "multi_step": "Compositional Chaining",
    "analogy": "Analogical Transport",
    "quotient": "Equivalence-Class Reasoning",
    "normal_form": "Rewriting and Normal Forms",
    "invariant": "Invariant Discovery",
}
COMPLEXITY_LEVELS: tuple[str, ...] = ("Introductory", "Standard", "Challenging", "Frontier")

_PERCENT_FIELDS = {
    "coverage",
    "primary_score",
    "mean_total_score",
    "mean_validity_score",
    "mean_hidden_goal_solve_rate",
    "mean_proof_cost_reduction",
    "mean_compression_score",
    "mean_semantic_equivalence_score",
    "mean_novelty_score",
    "mean_minimality_score",
}

_METRIC_ROWS: tuple[tuple[str, str], ...] = (
    ("mean_validity_score", "Validity"),
    ("mean_hidden_goal_solve_rate", "Hidden goal solve"),
    ("mean_proof_cost_reduction", "Proof cost reduction"),
    ("mean_compression_score", "Compression"),
    ("mean_semantic_equivalence_score", "Semantic equivalence"),
    ("mean_novelty_score", "Novelty"),
    ("mean_minimality_score", "Minimality"),
    ("mean_candidate_size", "Candidate size"),
    ("mean_total_score", "Total score"),
)
_DESCRIPTIVE_FIELDS: tuple[tuple[str, str], ...] = (
    ("num_visible_facts", "Public facts"),
    ("num_visible_theorems", "Public theorems"),
    ("num_public_rules", "Public rules"),
    ("num_visible_targets", "Visible targets"),
    ("num_hidden_targets", "Hidden targets"),
    ("num_hidden_bridge_items", "Hidden bridge items"),
    ("num_signature_symbols", "Signature symbols"),
    ("num_public_artifacts", "Total public artifacts"),
    ("max_term_depth", "Max term depth"),
    ("max_goal_budget", "Max goal budget"),
    ("max_hidden_step", "Max hidden step"),
)
_COMPLEXITY_FIELDS: tuple[str, ...] = (
    "max_term_depth",
    "max_goal_budget",
    "max_hidden_step",
    "num_public_artifacts",
    "num_hidden_bridge_items",
    "num_signature_symbols",
)

_COMPARISON_METRIC_LABELS: Mapping[str, str] = {
    "primary_score": "Primary score",
    "mean_total_score": "Mean total score",
    "mean_validity_score": "Mean validity",
    "mean_hidden_goal_solve_rate": "Mean hidden-goal solve rate",
    "mean_proof_cost_reduction": "Mean proof-cost reduction",
    "mean_compression_score": "Mean compression score",
    "mean_semantic_equivalence_score": "Mean semantic equivalence",
    "mean_novelty_score": "Mean novelty",
    "mean_minimality_score": "Mean minimality",
    "mean_candidate_size": "Mean candidate size",
    "coverage": "Coverage",
    "mean_latency_seconds": "Mean latency (s)",
    "p95_latency_seconds": "P95 latency (s)",
}


def load_benchmark_report(path: str | Path) -> dict[str, Any]:
    """Load one benchmark report and enforce the expected top-level shape.

    The renderer assumes object-style benchmark payloads with named sections
    such as `summary`, `by_split`, and `worlds`. Validating that assumption
    early keeps later rendering code simple and predictable.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Benchmark report at {path} must be a JSON object.")
    return payload


def load_benchmark_reports(paths: Sequence[str | Path]) -> list[dict[str, Any]]:
    """Load a collection of reports for multi-run comparison rendering.

    This helper exists mainly so the comparison path and the single-report path
    share the same validation logic.
    """

    return [load_benchmark_report(path) for path in paths]


def latex_escape(value: object) -> str:
    """Escape arbitrary content for safe placement inside LaTeX table cells.

    Report values often come from file paths, command lines, or error strings.
    Escaping them here prevents rendering failures and keeps the rest of the
    module free to work in plain Python strings.
    """

    if value is None:
        return "n/a"
    text = " ".join(str(value).split())
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def _as_mapping(value: object) -> Mapping[str, Any]:
    """Defensively coerce nested report sections into mapping-like form.

    The report renderer is intentionally permissive with partially malformed
    payloads so it can still explain what went wrong. Returning an empty mapping
    instead of raising makes that degraded rendering possible.
    """

    if isinstance(value, Mapping):
        return value
    return {}


def _format_number(value: object, *, percent: bool = False) -> str:
    """Format one scalar into the small vocabulary expected in report tables.

    The point is not fancy numeric presentation. The point is consistency across
    overview, split, family, and comparison tables so readers can scan values
    without re-learning formatting rules in each section.
    """

    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and not percent:
        return str(value)
    if isinstance(value, (float, int)):
        numeric = float(value)
        if percent:
            return f"{numeric * 100.0:.1f}%"
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.3f}"
    return " ".join(str(value).split())


def _format_field(name: str, value: object) -> str:
    """Apply metric-aware display conventions to one report field.

    Some fields are proportions and should read as percentages; others are raw
    counts or latencies. This helper centralizes that distinction so tables do
    not drift into inconsistent notation.
    """

    if name in _PERCENT_FIELDS:
        return _format_number(value, percent=True)
    return _format_number(value)


def _render_longtable(column_spec: str, headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """Render one longtable block, the module's core presentation primitive.

    `longtable` is used because benchmark outputs can exceed a single page. By
    standardizing on one table constructor, the file keeps section-specific code
    focused on meaning rather than LaTeX boilerplate.
    """

    header_line = " & ".join(latex_escape(header) for header in headers) + r" \\"
    body_lines = [latex_escape(cell) for row in rows for cell in row]
    if len(body_lines) % len(headers) != 0:
        raise ValueError("Longtable rows must have the same width as the headers.")

    lines = [
        rf"\begin{{longtable}}{{{column_spec}}}",
        r"\toprule",
        header_line,
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        header_line,
        r"\midrule",
        r"\endhead",
    ]
    for index in range(0, len(body_lines), len(headers)):
        lines.append(" & ".join(body_lines[index : index + len(headers)]) + r" \\")
    lines.extend([r"\bottomrule", r"\end{longtable}"])
    return "\n".join(lines)


def _summary_rows(summary: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Turn aggregate metric payloads into the main reader-facing score table.

    The resulting rows answer the first question most readers have: how strong
    was the run overall, and where did the score come from?
    """

    rows = [("Primary score", _format_field("primary_score", summary.get("primary_score")))]
    for key, label in _METRIC_ROWS:
        rows.append((label, _format_field(key, summary.get(key))))
    return rows


def _family_class_label(family: str) -> str:
    """Map one fine-grained benchmark family into a broader conceptual class.

    Family names are precise for implementers, but papers and summaries often
    need a slightly higher level of abstraction such as "Invariant Reasoning" or
    "Analogical Transport." This helper provides that vocabulary bridge.
    """

    if family in FAMILY_CLASS_LABELS:
        return FAMILY_CLASS_LABELS[family]
    return family.replace("_", " ").title()


def _coerce_float(value: object, *, default: float = 0.0) -> float:
    """Convert a scalar to float without making rendering brittle.

    The report layer prefers a degraded but readable table over a hard crash
    when one field is malformed or absent.
    """

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, *, default: int = 0) -> int:
    """Convert a scalar to int while treating malformed metadata as recoverable.

    Structural summaries should remain best-effort even when one packaged world
    is missing or contains slightly inconsistent metadata.
    """

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _percentile(values: Sequence[float], quantile: float) -> float:
    """Compute an interpolated percentile for small report-side summaries.

    The renderer only needs lightweight descriptive statistics, so a simple
    deterministic interpolation scheme is enough and keeps dependencies minimal.
    """

    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _median(values: Sequence[float]) -> float:
    """Return the median via the shared percentile helper.

    Keeping median calculation routed through `_percentile` ensures that every
    summary statistic in this file uses the same interpolation policy.
    """

    return _percentile(values, 0.5)


def _aggregate_records(records: Sequence[Mapping[str, Any]]) -> dict[str, float | int]:
    """Aggregate per-world rows into the summary shape used across the report.

    This is the reporting counterpart of the benchmark harness aggregation. It
    lets the renderer compute class-level, complexity-level, and other derived
    slices without duplicating aggregation logic ad hoc in each section.
    """

    count = len(records)
    durations = [_coerce_float(record.get("latency_seconds")) for record in records]
    completed = sum(1 for record in records if record.get("status") == "scored")
    failed_invocations = sum(1 for record in records if record.get("status") == "invocation_failed")
    scoring_failures = sum(1 for record in records if record.get("status") == "scoring_failed")
    valid_submissions = sum(1 for record in records if bool(record.get("valid")))

    summary: dict[str, float | int] = {
        "num_worlds": count,
        "completed": completed,
        "failed_invocations": failed_invocations,
        "scoring_failures": scoring_failures,
        "valid_submissions": valid_submissions,
        "coverage": (completed / count) if count else 0.0,
        "mean_latency_seconds": (sum(durations) / count) if count else 0.0,
        "p95_latency_seconds": _percentile(durations, 0.95),
    }
    for metric_key in METRIC_KEYS:
        metric_values = [_coerce_float(_as_mapping(record.get("metrics")).get(metric_key)) for record in records]
        summary[f"mean_{metric_key}"] = (sum(metric_values) / count) if count else 0.0
    summary["primary_score"] = _coerce_float(summary.get("mean_total_score"))
    return summary


def _hidden_step_depth(metadata: Mapping[str, Any], *, fallback: int) -> int:
    """Recover one world's hidden-step depth for structural difficulty summaries.

    Hidden-step depth is one of the clearest proxies for how far a bridge has
    to reach before it pays off, so the complexity analysis tries to preserve it
    whenever the packaged metadata exposes it.
    """

    raw_steps = metadata.get("hidden_steps")
    if isinstance(raw_steps, Sequence) and not isinstance(raw_steps, str):
        steps = [_coerce_int(item, default=0) for item in raw_steps]
        steps = [step for step in steps if step > 0]
        if steps:
            return max(steps)
    return fallback


def _structural_world_summary(world_root: object) -> dict[str, Any]:
    """Load one packaged world and derive structural descriptors for reporting.

    The benchmark JSON alone tells us how a system performed. The packaged world
    directory tells us what kind of problem that performance came from: number
    of visible theorems, hidden targets, signature size, and other structural
    features used later for complexity and descriptive-statistics sections.
    """

    if not isinstance(world_root, str) or not world_root:
        return {"package_available": False, "package_error": "Missing world_root."}
    root = Path(world_root)
    if not root.exists():
        return {"package_available": False, "package_error": f"Missing world_root {root}."}

    try:
        world = load_world(root)
    except Exception as error:  # noqa: BLE001
        return {"package_available": False, "package_error": str(error)}

    public_rules = (
        len(world.axioms)
        + len(world.rewrites)
        + len(world.theories)
        + len(world.visible_morphisms)
    )
    hidden_bridge = world.hidden_bridge
    hidden_bridge_items = (
        len(hidden_bridge.definitions)
        + len(hidden_bridge.lemmas)
        + len(hidden_bridge.mappings)
    )
    goal_budgets = [
        _coerce_int(goal.budget, default=0)
        for goal in world.targets_hidden + world.targets_visible
        if goal.budget is not None
    ]
    max_goal_budget = max(goal_budgets) if goal_budgets else 0
    signature = world.signature

    return {
        "package_available": True,
        "package_error": None,
        "max_term_depth": _coerce_int(world.metadata.get("max_term_depth"), default=0),
        "max_goal_budget": max_goal_budget,
        "max_hidden_step": _hidden_step_depth(world.metadata, fallback=max_goal_budget),
        "num_visible_facts": len(world.visible_facts),
        "num_visible_theorems": len(world.visible_theorems),
        "num_public_rules": public_rules,
        "num_visible_targets": len(world.targets_visible),
        "num_hidden_targets": len(world.targets_hidden),
        "num_hidden_bridge_items": hidden_bridge_items,
        "num_signature_symbols": (
            len(signature.sorts)
            + len(signature.constants)
            + len(signature.functions)
            + len(signature.predicates)
        ),
        "num_public_artifacts": (
            len(world.visible_facts)
            + len(world.visible_theorems)
            + public_rules
            + len(world.targets_visible)
        ),
    }


def _enriched_world_records(world_records: Sequence[object]) -> list[dict[str, Any]]:
    """Attach semantic and structural context to each raw per-world record.

    Raw benchmark rows know about scores and statuses. The report needs more:
    task-class labels, structural descriptors, and a derived complexity band.
    This helper is the bridge from machine report rows to analysis-ready rows.
    """

    structural_cache: dict[str, dict[str, Any]] = {}
    enriched: list[dict[str, Any]] = []

    for raw_world in world_records:
        record = _as_mapping(raw_world)
        family = str(record.get("family", "unknown"))
        score = _as_mapping(record.get("score"))
        metrics = _as_mapping(score.get("metrics"))
        world_root = str(record.get("world_root", ""))
        if world_root not in structural_cache:
            structural_cache[world_root] = _structural_world_summary(world_root)
        enriched.append(
            {
                "world_id": str(record.get("world_id", "unknown")),
                "split": str(record.get("split", "unknown")),
                "family": family,
                "class_label": _family_class_label(family),
                "status": str(record.get("status", "unknown")),
                "valid": bool(score.get("valid")),
                "latency_seconds": _coerce_float(_as_mapping(record.get("target")).get("duration_seconds")),
                "metrics": {metric_key: _coerce_float(metrics.get(metric_key)) for metric_key in METRIC_KEYS},
                **structural_cache[world_root],
            }
        )

    available = [record for record in enriched if bool(record.get("package_available"))]
    if not available:
        return enriched

    if len({tuple(_coerce_float(record.get(field)) for field in _COMPLEXITY_FIELDS) for record in available}) == 1:
        for record in available:
            record["complexity_score"] = 0.0
            record["complexity_level"] = "Standard"
        return enriched

    bounds = {
        field: (
            min(_coerce_float(record.get(field)) for record in available),
            max(_coerce_float(record.get(field)) for record in available),
        )
        for field in _COMPLEXITY_FIELDS
    }
    scores: list[float] = []
    for record in available:
        score_value = 0.0
        for field in _COMPLEXITY_FIELDS:
            lower, upper = bounds[field]
            value = _coerce_float(record.get(field))
            if upper > lower:
                score_value += (value - lower) / (upper - lower)
        record["complexity_score"] = score_value
        scores.append(score_value)

    # Complexity bands are intentionally relative to the selected report slice,
    # so readers can see which worlds were easiest or hardest in that slice
    # without pretending that the benchmark has one absolute global difficulty.
    thresholds = (
        _percentile(scores, 0.25),
        _percentile(scores, 0.50),
        _percentile(scores, 0.75),
    )
    for record in available:
        score_value = _coerce_float(record.get("complexity_score"))
        if score_value <= thresholds[0]:
            record["complexity_level"] = COMPLEXITY_LEVELS[0]
        elif score_value <= thresholds[1]:
            record["complexity_level"] = COMPLEXITY_LEVELS[1]
        elif score_value <= thresholds[2]:
            record["complexity_level"] = COMPLEXITY_LEVELS[2]
        else:
            record["complexity_level"] = COMPLEXITY_LEVELS[3]
    return enriched


def _group_rows(groups: Mapping[str, Any]) -> list[tuple[str, str, str, str, str, str, str, str]]:
    """Turn aggregate sections into the row format used by summary tables.

    Split and family tables share the same column logic, so this helper lets the
    report describe different grouping axes with one reusable presentation path.
    """

    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for label in sorted(groups):
        summary = _as_mapping(groups[label])
        failures = int(summary.get("failed_invocations", 0)) + int(summary.get("scoring_failures", 0))
        rows.append(
            (
                str(label),
                _format_field("num_worlds", summary.get("num_worlds")),
                _format_field("completed", summary.get("completed")),
                _format_field("coverage", summary.get("coverage")),
                _format_field("primary_score", summary.get("primary_score")),
                _format_field("valid_submissions", summary.get("valid_submissions")),
                _format_field("mean_latency_seconds", summary.get("mean_latency_seconds")),
                _format_field("failed_invocations", failures),
            )
        )
    return rows


def _task_class_rows(enriched: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str, str, str, str, str, str]]:
    """Aggregate performance over broader conceptual task classes.

    Readers often care less about one specific family name than about broader
    reasoning modes such as bridge invention or analogical transport. This
    section provides that higher-level view.
    """

    labels = sorted({str(record.get("class_label", "Unknown")) for record in enriched})
    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for label in labels:
        subset = [record for record in enriched if record.get("class_label") == label]
        summary = _aggregate_records(subset)
        families = ", ".join(sorted({str(record.get("family", "unknown")) for record in subset}))
        rows.append(
            (
                label,
                families,
                _format_field("num_worlds", summary.get("num_worlds")),
                _format_field("coverage", summary.get("coverage")),
                _format_field("primary_score", summary.get("primary_score")),
                _format_field("mean_hidden_goal_solve_rate", summary.get("mean_hidden_goal_solve_rate")),
                _format_field("mean_semantic_equivalence_score", summary.get("mean_semantic_equivalence_score")),
                _format_field("mean_latency_seconds", summary.get("mean_latency_seconds")),
            )
        )
    return rows


def _complexity_rows(enriched: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str, str, str, str, str, str]]:
    """Summarize performance across the derived structural complexity buckets.

    The goal is to show whether a system's score degrades smoothly or sharply as
    packaged worlds become structurally richer within the chosen dataset slice.
    """

    available = [record for record in enriched if bool(record.get("package_available")) and record.get("complexity_level")]
    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for level in COMPLEXITY_LEVELS:
        subset = [record for record in available if record.get("complexity_level") == level]
        if not subset:
            continue
        summary = _aggregate_records(subset)
        rows.append(
            (
                level,
                _format_field("num_worlds", summary.get("num_worlds")),
                _format_field("coverage", summary.get("coverage")),
                _format_field("primary_score", summary.get("primary_score")),
                _format_field("mean_hidden_goal_solve_rate", summary.get("mean_hidden_goal_solve_rate")),
                _format_field("mean_semantic_equivalence_score", summary.get("mean_semantic_equivalence_score")),
                _format_number(sum(_coerce_float(record.get("max_term_depth")) for record in subset) / len(subset)),
                _format_number(sum(_coerce_float(record.get("num_public_artifacts")) for record in subset) / len(subset)),
            )
        )
    return rows


def _portrait_rows(enriched: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[tuple[str, ...]]]:
    """Build the class-by-complexity "challenge portrait" matrix.

    Each cell answers a compact question: for task class X at complexity level
    Y, how many worlds were present and how well did the system do on them?
    """

    available = [record for record in enriched if bool(record.get("package_available")) and record.get("complexity_level")]
    present_levels = [level for level in COMPLEXITY_LEVELS if any(record.get("complexity_level") == level for record in available)]
    if not available or not present_levels:
        return [], []

    headers = ["Task Class", *present_levels]
    rows: list[tuple[str, ...]] = []
    for class_label in sorted({str(record.get("class_label", "Unknown")) for record in available}):
        values = [class_label]
        for level in present_levels:
            subset = [
                record
                for record in available
                if record.get("class_label") == class_label and record.get("complexity_level") == level
            ]
            if not subset:
                values.append("--")
                continue
            summary = _aggregate_records(subset)
            values.append(f"{len(subset)} / {_format_field('primary_score', summary.get('primary_score'))}")
        rows.append(tuple(values))
    return headers, rows


def _descriptive_rows(enriched: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str, str, str]]:
    """Compute descriptive statistics for the packaged world population.

    These rows are about the dataset itself rather than system performance. They
    help readers calibrate what the benchmark slice looks like structurally.
    """

    available = [record for record in enriched if bool(record.get("package_available"))]
    rows: list[tuple[str, str, str, str, str]] = []
    for field, label in _DESCRIPTIVE_FIELDS:
        values = [_coerce_float(record.get(field)) for record in available]
        if not values:
            continue
        rows.append(
            (
                label,
                _format_number(sum(values) / len(values)),
                _format_number(_median(values)),
                _format_number(min(values)),
                _format_number(max(values)),
            )
        )
    return rows


def _issue_rows(worlds: Sequence[object], *, issue_limit: int) -> list[tuple[str, str, str, str, str, str]]:
    """Select the non-ideal worlds worth surfacing in the report appendix.

    A benchmark report should not only celebrate aggregate scores. It should
    also point readers to concrete failures, malformed outputs, or invalid
    submissions that explain where a run struggled.
    """

    rows: list[tuple[str, str, str, str, str, str]] = []
    for raw_world in worlds:
        world = _as_mapping(raw_world)
        status = str(world.get("status", "unknown"))
        score = _as_mapping(world.get("score"))
        if status == "scored" and bool(score.get("valid")) and not world.get("integration_error"):
            continue
        target = _as_mapping(world.get("target"))
        detail = world.get("integration_error")
        if not detail:
            errors = score.get("errors")
            if isinstance(errors, list) and errors:
                detail = errors[0]
        if not detail:
            detail = "Submission returned a non-valid score payload."
        rows.append(
            (
                str(world.get("world_id", "unknown")),
                str(world.get("split", "unknown")),
                str(world.get("family", "unknown")),
                status,
                str(target.get("status", "unknown")),
                str(detail),
            )
        )
        if len(rows) >= issue_limit:
            break
    return rows


def _selected_splits_label(dataset: Mapping[str, Any]) -> str:
    """Render the split-selection field for the run-overview section.

    This turns the benchmark runner's internal selection state into the concise
    human-facing wording used in the report header.
    """

    selected_splits = dataset.get("selected_splits")
    if isinstance(selected_splits, Sequence) and not isinstance(selected_splits, str):
        return ", ".join(str(item) for item in selected_splits) if selected_splits else "all discovered splits"
    return "all discovered splits"


def _comparison_metric_label(metric_key: str) -> str:
    """Resolve a human-readable label for the chosen comparison metric.

    Comparison reports let the user choose one metric to compare by family and
    split, but those keys should read like prose in captions and notes.
    """

    if metric_key not in _COMPARISON_METRIC_LABELS:
        supported = ", ".join(sorted(_COMPARISON_METRIC_LABELS))
        raise ValueError(f"Unsupported comparison metric {metric_key!r}. Supported metrics: {supported}.")
    return _COMPARISON_METRIC_LABELS[metric_key]


def _resolve_report_names(report_count: int, report_names: Sequence[str]) -> list[str]:
    """Validate or synthesize display labels for multi-report comparisons.

    Comparison tables are only readable if each run has a stable short name.
    This helper either checks the user-supplied names or creates deterministic
    defaults such as `run_1`, `run_2`, and so on.
    """

    if report_names and len(report_names) != report_count:
        raise ValueError("When report_names are provided, include exactly one name per report.")
    if report_names:
        return [str(name) for name in report_names]
    return [f"run_{index + 1}" for index in range(report_count)]


def _dynamic_comparison_column_spec(report_count: int) -> str:
    """Choose a LaTeX column layout that stays readable as runs are added.

    Small comparisons can afford simple right-aligned columns. Larger ones need
    constrained-width paragraph columns so the table remains printable.
    """

    if report_count <= 3:
        return r"p{0.28\linewidth}" + ("r" * report_count)
    remaining_width = max(0.10, 0.68 / report_count)
    value_columns = "".join(
        rf">{{\raggedleft\arraybackslash}}p{{{remaining_width:.2f}\linewidth}}"
        for _ in range(report_count)
    )
    return r"p{0.26\linewidth}" + value_columns


def _comparison_overview_rows(
    reports: Sequence[Mapping[str, Any]],
    report_names: Sequence[str],
) -> list[tuple[str, str, str, str, str, str, str, str]]:
    """Build the top-level overview table for several benchmark runs.

    This table is the multi-run analogue of the single-report overview section:
    it tells the reader what was run, on which dataset slice, and with what
    headline performance.
    """

    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for name, report in zip(report_names, reports):
        dataset = _as_mapping(report.get("dataset"))
        manifest = _as_mapping(dataset.get("manifest"))
        summary = _as_mapping(report.get("summary"))
        rows.append(
            (
                name,
                str(manifest.get("dataset_name", dataset.get("root", "benchmark dataset"))),
                _selected_splits_label(dataset),
                _format_field("primary_score", summary.get("primary_score")),
                _format_field("mean_validity_score", summary.get("mean_validity_score")),
                _format_field("mean_hidden_goal_solve_rate", summary.get("mean_hidden_goal_solve_rate")),
                _format_field("coverage", summary.get("coverage")),
                _format_field("mean_latency_seconds", summary.get("mean_latency_seconds")),
            )
        )
    return rows


def _comparison_group_rows(
    reports: Sequence[Mapping[str, Any]],
    *,
    group_key: str,
    metric_key: str,
) -> list[tuple[str, ...]]:
    """Build one family- or split-comparison table across several reports.

    The union of labels across all reports is used so that missing groups become
    visible rather than silently disappearing from the comparison.
    """

    labels: set[str] = set()
    for report in reports:
        groups = _as_mapping(report.get(group_key))
        labels.update(str(label) for label in groups)

    rows: list[tuple[str, ...]] = []
    for label in sorted(labels):
        values = [label]
        for report in reports:
            groups = _as_mapping(report.get(group_key))
            summary = _as_mapping(groups.get(label))
            values.append(_format_field(metric_key, summary.get(metric_key)))
        rows.append(tuple(values))
    return rows


def _single_report_body(
    report: Mapping[str, Any],
    *,
    issue_limit: int,
) -> str:
    """Render the full section body for one benchmark result document.

    The body is organized to move from general to specific:
    overview, metric means, split and family summaries, richer structural
    analyses, and finally a short appendix of problematic worlds.
    """

    dataset = _as_mapping(report.get("dataset"))
    manifest = _as_mapping(dataset.get("manifest"))
    summary = _as_mapping(report.get("summary"))
    target = _as_mapping(report.get("target"))
    scoring = _as_mapping(report.get("scoring"))
    backend_override = _as_mapping(scoring.get("backend_override"))
    worlds = report.get("worlds")
    world_records = list(worlds) if isinstance(worlds, Sequence) else []
    enriched_records = _enriched_world_records(world_records)
    available_structural = [record for record in enriched_records if bool(record.get("package_available"))]

    backend_label = "world defaults"
    if backend_override:
        backend_name = backend_override.get("name") or "unspecified"
        backend_command = backend_override.get("command")
        backend_label = str(backend_name)
        if isinstance(backend_command, Sequence) and not isinstance(backend_command, str) and backend_command:
            backend_label = f"{backend_label} via {json.dumps(list(backend_command))}"

    overview_rows = [
        ("Dataset", str(manifest.get("dataset_name", dataset.get("root", "benchmark dataset")))),
        ("Dataset version", str(manifest.get("version", "n/a"))),
        ("Dataset root", str(dataset.get("root", "n/a"))),
        ("Families", ", ".join(str(item) for item in manifest.get("families", [])) or "n/a"),
        ("Selected splits", _selected_splits_label(dataset)),
        ("World limit", "all discovered worlds" if dataset.get("limit") is None else str(dataset.get("limit"))),
        ("Target command", json.dumps(list(target.get("command", [])))),
        ("Timeout", f"{float(target.get('timeout_seconds', 0.0)):.1f}s"),
        ("Scoring backend", backend_label),
        ("Worlds requested", _format_field("num_worlds", summary.get("num_worlds"))),
        ("Completed", _format_field("completed", summary.get("completed"))),
        ("Coverage", _format_field("coverage", summary.get("coverage"))),
        ("Valid submissions", _format_field("valid_submissions", summary.get("valid_submissions"))),
        ("Invocation failures", _format_field("failed_invocations", summary.get("failed_invocations"))),
        ("Scoring failures", _format_field("scoring_failures", summary.get("scoring_failures"))),
        ("Mean latency", _format_field("mean_latency_seconds", summary.get("mean_latency_seconds")) + "s"),
        ("P95 latency", _format_field("p95_latency_seconds", summary.get("p95_latency_seconds")) + "s"),
    ]

    parts = [
        r"\section*{Run Overview}",
        _render_longtable(
            r"p{0.28\linewidth}p{0.66\linewidth}",
            ("Field", "Value"),
            overview_rows,
        ),
        r"\section*{Metric Means}",
        _render_longtable(
            r"p{0.52\linewidth}p{0.18\linewidth}",
            ("Metric", "Value"),
            _summary_rows(summary),
        ),
        r"\section*{Split Summary}",
        _render_longtable(
            r"p{0.16\linewidth}rrrrrrr",
            ("Split", "Worlds", "Done", "Coverage", "Score", "Valid", "Latency", "Failures"),
            _group_rows(_as_mapping(report.get("by_split"))),
        ),
        r"\section*{Family Summary}",
        _render_longtable(
            r"p{0.24\linewidth}rrrrrrr",
            ("Family", "Worlds", "Done", "Coverage", "Score", "Valid", "Latency", "Failures"),
            _group_rows(_as_mapping(report.get("by_family"))),
        ),
        r"\section*{Task Class Breakdown}",
        _render_longtable(
            r"p{0.18\linewidth}p{0.24\linewidth}rrrrrr",
            ("Class", "Families", "Worlds", "Coverage", "Score", "Hidden Solve", "Sem. Eq.", "Latency"),
            _task_class_rows(enriched_records),
        ),
    ]

    if available_structural:
        # These sections intentionally re-open the packaged world directories so
        # the paper report can talk about task structure, not only scores.
        if len(available_structural) == len(enriched_records):
            structural_note = (
                "Structural analyses below are computed directly from the packaged world directories "
                "referenced by the benchmark report."
            )
        else:
            structural_note = (
                f"Structural analyses below use {len(available_structural)}/{len(enriched_records)} packaged worlds "
                "whose world directories were still available when the report was rendered."
            )
        portrait_headers, portrait_rows = _portrait_rows(enriched_records)
        level_width = 0.72 / max(1, len(portrait_headers) - 1) if portrait_headers else 0.18
        parts.extend(
            [
                r"\section*{Complexity Breakdown}",
                structural_note,
                (
                    "Complexity levels are relative quartile buckets over a structural difficulty index built from "
                    "depth bounds, goal budgets, hidden-step depth, public artifact counts, hidden bridge size, "
                    "and signature size."
                ),
                _render_longtable(
                    r"p{0.18\linewidth}rrrrrrr",
                    ("Level", "Worlds", "Coverage", "Score", "Hidden Solve", "Sem. Eq.", "Mean Depth", "Mean Surface"),
                    _complexity_rows(enriched_records),
                ),
                r"\section*{Challenge Portrait}",
                "Each cell reports worlds / primary score for one task class at one complexity band.",
                _render_longtable(
                    r"p{0.24\linewidth}" + "".join(
                        f"p{{{level_width:.2f}\\linewidth}}" for _ in portrait_headers[1:]
                    ),
                    tuple(portrait_headers),
                    portrait_rows,
                ),
                r"\section*{Dataset Descriptive Statistics}",
                _render_longtable(
                    r"p{0.32\linewidth}rrrr",
                    ("Feature", "Mean", "Median", "Min", "Max"),
                    _descriptive_rows(enriched_records),
                ),
            ]
        )
    else:
        parts.extend(
            [
                r"\section*{Complexity Breakdown}",
                (
                    "Complexity and dataset-structure tables require access to the packaged world directories "
                    "referenced by the benchmark report."
                ),
            ]
        )

    parts.append(r"\section*{World Issues}")

    issue_rows = _issue_rows(world_records, issue_limit=issue_limit)
    if issue_rows:
        parts.extend(
            [
                f"Only the first {len(issue_rows)} non-ideal worlds are listed here.",
                _render_longtable(
                    r"p{0.16\linewidth}p{0.1\linewidth}p{0.18\linewidth}p{0.12\linewidth}p{0.12\linewidth}p{0.24\linewidth}",
                    ("World", "Split", "Family", "Status", "Target", "Detail"),
                    issue_rows,
                ),
            ]
        )
    else:
        parts.append("No invocation or scoring issues were recorded in the selected slice.")
    return "\n\n".join(parts)


def _comparison_report_body(
    reports: Sequence[Mapping[str, Any]],
    *,
    report_names: Sequence[str],
    comparison_metric: str,
) -> str:
    """Render the body for a report that compares several benchmark runs.

    The comparison document deliberately stays compact: first a run-overview
    table, then one family table and one split table for the chosen metric.
    That keeps cross-system comparison readable instead of drowning it in every
    possible statistic at once.
    """

    metric_label = _comparison_metric_label(comparison_metric)
    overview = _render_longtable(
        r"p{0.16\linewidth}p{0.22\linewidth}p{0.16\linewidth}rrrrr",
        ("Run", "Dataset", "Splits", "Primary", "Validity", "Hidden", "Coverage", "Latency"),
        _comparison_overview_rows(reports, report_names),
    )

    family_rows = _comparison_group_rows(reports, group_key="by_family", metric_key=comparison_metric)
    split_rows = _comparison_group_rows(reports, group_key="by_split", metric_key=comparison_metric)
    comparison_column_spec = _dynamic_comparison_column_spec(len(report_names))

    parts = [
        r"\section*{Run Comparison}",
        overview,
    ]
    if family_rows:
        parts.extend(
            [
                r"\section*{Family Comparison}",
                _render_longtable(
                    comparison_column_spec,
                    ("Family", *report_names),
                    family_rows,
                ),
                f"Entries report {metric_label.lower()} for each family.",
            ]
        )
    if split_rows:
        parts.extend(
            [
                r"\section*{Split Comparison}",
                _render_longtable(
                    comparison_column_spec,
                    ("Split", *report_names),
                    split_rows,
                ),
                f"Entries report {metric_label.lower()} for each split.",
            ]
        )
    return "\n\n".join(parts)


def _wrap_report_document(body: str, *, title: str) -> str:
    """Wrap the report body in a standalone LaTeX document preamble.

    This is the path used when the output should compile on its own rather than
    be included into a larger manuscript.
    """

    parts = [
        r"\documentclass[11pt]{article}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{array}",
        r"\usepackage{booktabs}",
        r"\usepackage{hyperref}",
        r"\usepackage{longtable}",
        r"\usepackage{textcomp}",
        r"\setlength{\LTleft}{0pt}",
        r"\setlength{\LTright}{0pt}",
        r"\begin{document}",
        rf"\section*{{{latex_escape(title)}}}",
        "This report is rendered from the machine-readable benchmark JSON output.",
        body,
        r"\end{document}",
        "",
    ]
    return "\n\n".join(parts)


def _wrap_report_fragment(body: str) -> str:
    """Wrap the report as an `\\input`-friendly LaTeX fragment.

    Fragments intentionally avoid document-class boilerplate so they can be
    embedded directly into the concept paper or other external writeups.
    """

    return "\n".join(
        [
            "% Generated by `python -m abw_core render-benchmark-report`.",
            "% Requires \\usepackage{array,booktabs,longtable,textcomp}.",
            "",
            body,
            "",
        ]
    )


def render_benchmark_reports_latex(
    reports: Sequence[Mapping[str, Any]],
    *,
    report_names: Sequence[str] = (),
    title: str | None = None,
    issue_limit: int = 20,
    comparison_metric: str = "primary_score",
    fragment: bool = False,
) -> str:
    """Render one or more benchmark reports into LaTeX.

    This is the main public rendering entrypoint. It decides whether the caller
    is asking for a single-run report or a multi-run comparison, then wraps the
    resulting body either as a standalone document or as a fragment.
    """

    if not reports:
        raise ValueError("At least one benchmark report is required.")

    if len(reports) == 1:
        body = _single_report_body(reports[0], issue_limit=issue_limit)
        default_title = "Benchmark Result Report"
    else:
        names = _resolve_report_names(len(reports), report_names)
        body = _comparison_report_body(reports, report_names=names, comparison_metric=comparison_metric)
        default_title = "Benchmark Result Comparison"

    if fragment:
        return _wrap_report_fragment(body)
    return _wrap_report_document(body, title=title or default_title)


def render_benchmark_report_latex(
    report: Mapping[str, Any],
    *,
    title: str | None = None,
    issue_limit: int = 20,
    fragment: bool = False,
) -> str:
    """Render one in-memory benchmark report into LaTeX.

    This convenience wrapper keeps the single-report path ergonomic for callers
    that already have the JSON payload loaded.
    """

    return render_benchmark_reports_latex(
        (report,),
        title=title,
        issue_limit=issue_limit,
        fragment=fragment,
    )


def write_benchmark_report_latex(
    report_path: str | Path | Sequence[str | Path],
    output_path: str | Path,
    *,
    title: str | None = None,
    issue_limit: int = 20,
    report_names: Sequence[str] = (),
    comparison_metric: str = "primary_score",
    fragment: bool = False,
) -> Path:
    """Render report JSON into a concrete `.tex` artifact on disk.

    The function handles both the single-report and multi-report cases and
    ensures the output directory exists before writing.
    """

    if isinstance(report_path, Sequence) and not isinstance(report_path, (str, Path)):
        reports = load_benchmark_reports(report_path)
    else:
        reports = [load_benchmark_report(report_path)]
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_benchmark_reports_latex(
            reports,
            report_names=report_names,
            title=title,
            issue_limit=issue_limit,
            comparison_metric=comparison_metric,
            fragment=fragment,
        ),
        encoding="utf-8",
    )
    return output


def compile_latex_report(
    tex_path: str | Path,
    *,
    pdf_output_path: str | Path | None = None,
    compile_command: Sequence[str] = DEFAULT_COMPILE_COMMAND,
) -> Path:
    """Compile one rendered LaTeX file into a PDF companion artifact.

    The renderer stays agnostic about which LaTeX engine the user prefers. It
    therefore accepts a tokenized compile command with placeholders instead of
    hard-coding one toolchain beyond the default `tectonic` profile.
    """

    if not compile_command:
        raise ValueError("compile_command must include at least one token.")

    tex = Path(tex_path).resolve()
    pdf_output = Path(pdf_output_path).resolve() if pdf_output_path is not None else tex.with_suffix(".pdf")
    outdir = pdf_output.parent.resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    uses_pdf_placeholder = any("{pdf}" in token for token in compile_command)
    expanded_command = [
        str(token).format(tex=str(tex), outdir=str(outdir), pdf=str(pdf_output))
        for token in compile_command
    ]

    try:
        subprocess.run(expanded_command, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        raise
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "").strip()
        stdout = (error.stdout or "").strip()
        detail = stderr or stdout or "no compiler output captured"
        raise RuntimeError(f"LaTeX report compilation failed: {detail}") from error

    produced_pdf = pdf_output if uses_pdf_placeholder else outdir / f"{tex.stem}.pdf"
    if not produced_pdf.exists():
        raise FileNotFoundError(f"LaTeX compiler did not produce the expected PDF artifact: {produced_pdf}")
    if produced_pdf.resolve() != pdf_output:
        shutil.copyfile(produced_pdf, pdf_output)
    return pdf_output


def render_benchmark_report_files(
    report_path: str | Path | Sequence[str | Path],
    tex_output_path: str | Path,
    *,
    title: str | None = None,
    issue_limit: int = 20,
    report_names: Sequence[str] = (),
    comparison_metric: str = "primary_score",
    fragment: bool = False,
    compile_pdf: bool = False,
    pdf_output_path: str | Path | None = None,
    compile_command: Sequence[str] = DEFAULT_COMPILE_COMMAND,
) -> dict[str, Any]:
    """Materialize the report workflow end to end for CLI-facing callers.

    This helper writes the `.tex` file and, when requested, compiles the PDF as
    well, returning a small artifact manifest that higher-level commands can
    serialize or print.
    """

    tex_path = write_benchmark_report_latex(
        report_path,
        tex_output_path,
        title=title,
        issue_limit=issue_limit,
        report_names=report_names,
        comparison_metric=comparison_metric,
        fragment=fragment,
    )
    if isinstance(report_path, Sequence) and not isinstance(report_path, (str, Path)):
        report_paths = [str(Path(path).resolve()) for path in report_path]
    else:
        report_paths = [str(Path(report_path).resolve())]
    result = {
        "report": report_paths[0],
        "reports": report_paths,
        "report_count": len(report_paths),
        "tex": str(tex_path),
    }
    if compile_pdf or pdf_output_path is not None:
        pdf_path = compile_latex_report(
            tex_path,
            pdf_output_path=pdf_output_path,
            compile_command=compile_command,
        )
        result["pdf"] = str(pdf_path)
    return result
