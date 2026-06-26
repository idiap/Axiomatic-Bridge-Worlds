# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Core runtime for Axiomatic Bridge Worlds.

The package is built around a deterministic Horn-logic core. The formal world
is authoritative; NL rendering, packaging, and scoring all build on top of the
same typed IR and bounded prover.

The names re-exported here are the stable top-level API: generate a world,
package and load it, score a candidate bridge, and run the benchmark. Lower-level
helpers remain reachable through their submodules. `ir` is imported first because
every other module builds on the typed IR.
"""

from . import ir
from .config import load_config
from .generator import WorldGenerationRequest, generate_world, registered_families
from .packager import export_public_dataset, load_world, package_world, validate_package
from .scorer import evaluate_candidate
from .benchmark import run_benchmark

__all__ = [
    "ir",
    "WorldGenerationRequest",
    "generate_world",
    "registered_families",
    "load_world",
    "package_world",
    "export_public_dataset",
    "validate_package",
    "evaluate_candidate",
    "run_benchmark",
    "load_config",
]
__version__ = "0.1.0"
