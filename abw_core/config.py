# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Configuration loading for ABW dataset and world generation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import yaml


# Baseline public DSL version for core Horn-clause worlds. Analogy upgrades to
# v2 because it uses the richer theory/morphism surface.
BASE_DSL_VERSION = "abw-dsl-v1"


@dataclass(frozen=True)
class DatasetConfig:
    """Normalized dataset-generation parameters loaded from YAML or JSON."""

    dataset_name: str
    version: str
    families: tuple[str, ...]
    splits: dict[str, int]
    split_examples_per_family: dict[str, int] | None = None
    split_start_seeds: dict[str, int] | None = None
    views: tuple[str, ...] = ("formal", "natural_language")
    dsl_version: str = BASE_DSL_VERSION
    output_dir: str = "datasets/generated"
    start_seed: int = 0
    max_term_depth: int = 3
    proof_budget: int = 3
    hidden_steps: tuple[int, ...] = (2, 3)
    include_distractors: bool = True
    interactive_enabled: bool = True
    interactive_query_budget: int = 20
    interactive_countermodels: bool = True
    prover_backend_name: str = "local"
    prover_backend_command: tuple[str, ...] = ()


def _default_dsl_version(families: tuple[str, ...]) -> str:
    if "analogy" in families:
        return "abw-dsl-v2"
    return BASE_DSL_VERSION


def _parse_views(payload: dict[str, Any]) -> tuple[str, ...]:
    raw_views = payload.get("views", ["formal", "natural_language"])
    if isinstance(raw_views, str):
        views = (raw_views,)
    else:
        views = tuple(str(item) for item in raw_views)
    if not views:
        raise ValueError("Dataset config must include at least one public view.")
    supported = {"formal", "natural_language"}
    unknown = sorted(set(views) - supported)
    if unknown:
        raise ValueError(f"Unsupported dataset view(s): {', '.join(unknown)}.")
    return views


def _parse_splits(
    splits_payload: dict[str, Any],
    family_count: int,
) -> tuple[dict[str, int], dict[str, int] | None, dict[str, int] | None]:
    splits: dict[str, int] = {}
    examples_per_family: dict[str, int] = {}
    start_seeds: dict[str, int] = {}
    for raw_name, raw_value in splits_payload.items():
        split_name = str(raw_name)
        if isinstance(raw_value, dict):
            if "start_seed" in raw_value:
                start_seeds[split_name] = int(raw_value["start_seed"])
            if "examples_per_family" in raw_value:
                per_family = int(raw_value["examples_per_family"])
                if per_family <= 0:
                    raise ValueError(f"Split {split_name!r} must request a positive examples_per_family value.")
                splits[split_name] = per_family * family_count
                examples_per_family[split_name] = per_family
                continue
            if "count" in raw_value:
                count = int(raw_value["count"])
            else:
                raise ValueError(
                    f"Split {split_name!r} must be an integer count or an object with examples_per_family."
                )
        else:
            count = int(raw_value)
        if count <= 0:
            raise ValueError(f"Split {split_name!r} must request a positive number of worlds.")
        splits[split_name] = count
    return splits, examples_per_family or None, start_seeds or None


def load_config(path: str | Path) -> DatasetConfig:
    """Load, normalize, and lightly validate a dataset-generation config file."""

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        if config_path.suffix == ".json":
            payload = json.load(handle)
        else:
            payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Dataset config must decode to an object.")
    families = tuple(payload.get("families", ["predicate_invention"]))
    if not families:
        raise ValueError("Dataset config must include at least one family.")
    default_dsl_version = _default_dsl_version(families)
    splits_payload = dict(payload.get("splits", {}))
    if not splits_payload:
        raise ValueError("Dataset config must include at least one split count.")
    split_counts, split_examples_per_family, split_start_seeds = _parse_splits(splits_payload, len(families))
    backend_payload = payload.get("prover_backend", {})
    if isinstance(backend_payload, dict):
        prover_backend_name = str(backend_payload.get("name", payload.get("prover_backend_name", "local")))
        raw_backend_command = backend_payload.get(
            "command",
            payload.get("prover_backend_command", ()),
        )
    else:
        prover_backend_name = str(payload.get("prover_backend_name", "local"))
        raw_backend_command = payload.get("prover_backend_command", ())
    if isinstance(raw_backend_command, (list, tuple)):
        prover_backend_command = tuple(str(item) for item in raw_backend_command)
    elif raw_backend_command:
        prover_backend_command = (str(raw_backend_command),)
    else:
        prover_backend_command = ()
    interactive_payload = payload.get("interactive", {})
    if isinstance(interactive_payload, dict):
        interactive_enabled = bool(interactive_payload.get("enabled", True))
        interactive_query_budget = int(interactive_payload.get("query_budget", 20))
        interactive_countermodels = bool(interactive_payload.get("countermodels", True))
    else:
        interactive_enabled = bool(payload.get("interactive_enabled", True))
        interactive_query_budget = int(payload.get("interactive_query_budget", 20))
        interactive_countermodels = bool(payload.get("interactive_countermodels", True))
    return DatasetConfig(
        dataset_name=str(payload.get("dataset_name", "axiomatic_bridge_worlds")),
        version=str(payload.get("version", "0.1.0")),
        families=families,
        splits=split_counts,
        split_examples_per_family=split_examples_per_family,
        split_start_seeds=split_start_seeds,
        views=_parse_views(payload),
        dsl_version=str(payload.get("dsl_version", default_dsl_version)),
        output_dir=str(payload.get("output_dir", "datasets/generated")),
        start_seed=int(payload.get("start_seed", 0)),
        max_term_depth=int(payload.get("max_term_depth", 3)),
        proof_budget=int(payload.get("proof_budget", 3)),
        hidden_steps=tuple(int(step) for step in payload.get("hidden_steps", [2, 3])),
        include_distractors=bool(payload.get("include_distractors", True)),
        interactive_enabled=interactive_enabled,
        interactive_query_budget=interactive_query_budget,
        interactive_countermodels=interactive_countermodels,
        prover_backend_name=prover_backend_name,
        prover_backend_command=prover_backend_command,
    )


def manifest_payload(
    config: DatasetConfig,
    split_counts: dict[str, int],
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build the dataset manifest emitted after generation completes."""

    payload: dict[str, Any] = {
        "dataset_name": config.dataset_name,
        "version": config.version,
        "splits": split_counts,
        "views": list(config.views),
        "families": list(config.families),
        "dsl_version": config.dsl_version,
        "output_dir": str(output_dir or config.output_dir),
        "interactive": {
            "enabled": config.interactive_enabled,
            "query_budget": config.interactive_query_budget,
            "countermodels": config.interactive_countermodels,
        },
        "prover_backend": {
            "name": config.prover_backend_name,
            "command": list(config.prover_backend_command),
        },
    }
    if config.split_examples_per_family is not None:
        payload["examples_per_family"] = dict(config.split_examples_per_family)
    if config.split_start_seeds is not None:
        payload["split_start_seeds"] = dict(config.split_start_seeds)
    return payload
