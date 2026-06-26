# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Public proving surface for the bounded ABW reasoning runtime.

This package exports the small proof-and-model toolkit that the rest of ABW
leans on: closure construction, clause counterexamples, goal countermodels,
rewrite normalization, diagnostic-model generation, and optional backend-aware
adapters.

Conceptually, this package is not trying to be a general theorem prover. It is
the bounded reasoning substrate underneath the benchmark. Its job is to make
ABW worlds inspectable, reproducible, and locally debuggable.

Concrete example
----------------
- The scorer uses `build_closure_with_backend` and `goal_cost` to decide
  whether a bridge makes hidden targets cheaper.
- Session tooling uses countermodel helpers to answer public diagnostic queries.
- Morphism validation uses clause-counterexample helpers to reject invalid
  structures with grounded evidence.

Paper-style framing
-------------------
The proving layer embodies a simple ABW design choice:

    prefer a bounded, transparent proof substrate that exposes useful evidence
    over a stronger but opaque engine that would be harder to debug locally.

Limitations
-----------
- The exported operations are bounded by finite term depth and packaged world
  structure.
- Solver integrations are diagnostic extensions, not claims of complete proof
  search.
- This namespace is curated for the rest of the runtime; it is not a promise
  that every internal proving submodule is stable as public API.
"""

from .backends import (
    BackendConfig,
    build_closure_with_backend,
    cvc5_backend_command,
    find_clause_counterexamples_with_backend,
    find_goal_countermodel_with_backend,
    z3_backend_command,
    validate_clause_soundness_with_backend,
)
from .countermodels import BoundedCountermodel, countermodel_for_atoms, find_goal_countermodel
from .horn import ClauseCounterexample, ProofResult, build_closure, find_clause_counterexamples, validate_clause_soundness
from .models import DiagnosticModel, public_diagnostic_models
from .proofs import Derivation, goal_cost, missing_goal_atoms
from .rewrite import match_term, normalize_atom, normalize_term
from .cvc5_finite_models import cvc5_is_available
from .z3_finite_models import z3_is_available

__all__ = [
    "BackendConfig",
    "BoundedCountermodel",
    "ClauseCounterexample",
    "cvc5_backend_command",
    "cvc5_is_available",
    "DiagnosticModel",
    "Derivation",
    "ProofResult",
    "build_closure",
    "build_closure_with_backend",
    "countermodel_for_atoms",
    "find_clause_counterexamples",
    "find_clause_counterexamples_with_backend",
    "find_goal_countermodel",
    "find_goal_countermodel_with_backend",
    "goal_cost",
    "match_term",
    "missing_goal_atoms",
    "normalize_atom",
    "normalize_term",
    "public_diagnostic_models",
    "validate_clause_soundness",
    "validate_clause_soundness_with_backend",
    "z3_backend_command",
    "z3_is_available",
]
