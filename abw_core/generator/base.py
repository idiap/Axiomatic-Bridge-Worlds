# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Family registry and request objects for world generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from abw_core import ir


@dataclass(frozen=True)
class WorldGenerationRequest:
    """Runtime knobs that shape one generated ABW world."""

    family: str
    seed: int
    world_id: str | None = None
    max_term_depth: int = 3
    proof_budget: int = 3
    hidden_steps: tuple[int, ...] = (2, 3)
    include_distractors: bool = True
    interactive_enabled: bool = True
    interactive_query_budget: int = 20
    interactive_countermodels: bool = True
    prover_backend_name: str = "local"
    prover_backend_command: tuple[str, ...] = ()


FamilyGenerator = Callable[[WorldGenerationRequest], ir.World]


_REGISTRY: dict[str, FamilyGenerator] = {}


def register_family(name: str, generator: FamilyGenerator) -> None:
    """Register one family generator under its public family name."""

    _REGISTRY[name] = generator


def registered_families() -> tuple[str, ...]:
    """Return the registered public family names in stable order."""

    return tuple(sorted(_REGISTRY))


def scoring_config(
    request: WorldGenerationRequest,
    *,
    weights: dict[str, float],
    include_proof_budget: bool = True,
) -> dict[str, object]:
    """Build the standard scoring, interaction, and backend payload for a world.

    The family generators share this helper so benchmark-wide defaults such as
    proof budgets, interactive-session limits, and packaged backend selection
    stay consistent across every world emitted from one config profile.
    """

    payload: dict[str, object] = {
        "weights": dict(weights),
        "interactive": {
            "enabled": request.interactive_enabled,
            "query_budget": request.interactive_query_budget,
            "countermodels": request.interactive_countermodels,
        },
        "prover_backend": {
            "name": request.prover_backend_name,
            "command": list(request.prover_backend_command),
        },
    }
    if include_proof_budget:
        payload["proof_budget"] = request.proof_budget
    return payload


def generate_world(request: WorldGenerationRequest) -> ir.World:
    """Dispatch one world-generation request to its registered family builder."""

    try:
        generator = _REGISTRY[request.family]
    except KeyError as error:
        raise KeyError(f"Unsupported ABW family {request.family!r}.") from error
    return generator(request)
