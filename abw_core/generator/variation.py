# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Deterministic seed variation and benchmark-content fingerprints."""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Mapping
from typing import Any

from abw_core import ir


GENERATOR_VERSION = "abw-seeded-v2"


def seeded_rng(family: str, seed: int) -> random.Random:
    """Return a stable family-specific RNG independent of Python hash randomization."""

    digest = hashlib.sha256(f"{GENERATOR_VERSION}:{family}:{seed}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def schema_metadata(family: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Record the structural choices that define one generated task schema."""

    normalized = json.loads(json.dumps(dict(parameters), sort_keys=True))
    encoded = json.dumps(
        {"family": family, "parameters": normalized},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "generator_version": GENERATOR_VERSION,
        "schema_parameters": normalized,
        "schema_fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def benchmark_content_fingerprint(world: ir.World) -> str:
    """Hash all score-relevant task content while excluding ids and metadata."""

    payload = {
        "family": world.family,
        "public_document": world.public_document().to_dict(),
        "hidden_targets": [goal.to_dict() for goal in world.targets_hidden],
        "hidden_bridge": world.hidden_bridge.to_dict(),
        "proof_fixtures": world.proof_fixtures,
        "scoring_config": world.scoring_config,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def public_content_fingerprint(world: ir.World) -> str:
    """Hash exactly the mathematical document exposed to the target system."""

    encoded = json.dumps(
        world.public_document().to_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
