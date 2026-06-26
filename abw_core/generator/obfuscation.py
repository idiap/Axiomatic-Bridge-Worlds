# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Name helpers for deterministic but semantically empty ABW surfaces."""

from __future__ import annotations


def default_world_id(family: str, seed: int) -> str:
    """Build the deterministic fallback world identifier for a family and seed."""

    return f"abw_{family}_{seed:04d}"
