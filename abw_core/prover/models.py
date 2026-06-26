# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Small finite-model diagnostics for ABW semantic scoring.

The runtime still does not build arbitrary countermodels, but it now supports a
useful middle ground between one-world evaluation and a full model finder:
construct a tiny suite of nearby public worlds by ablating visible facts or
visible theorems. Semantic equivalence can then be checked across that suite so
extensions that only match in the original packaged world do not look as strong
as extensions that survive simple counterfactual perturbations.
"""

from __future__ import annotations

from dataclasses import dataclass

from abw_core import ir


@dataclass(frozen=True)
class DiagnosticModel:
    """One bounded public-world variant used for semantic diagnostics."""

    name: str
    facts: tuple[ir.Fact, ...]
    clauses: tuple[ir.HornClause, ...]
    rewrites: tuple[ir.RewriteRule, ...]
    max_term_depth: int = 3


def _model_key(model: DiagnosticModel) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(sorted(fact.name for fact in model.facts)),
        tuple(sorted(clause.name for clause in model.clauses)),
    )


def public_diagnostic_models(world: ir.World) -> tuple[DiagnosticModel, ...]:
    """Build a small suite of nearby public models for semantic checks.

    The first entry is always the original public world. Later entries drop one
    visible fact or one visible theorem at a time, plus an axioms-only view when
    visible theorems exist. These ablations are intentionally small and cheap;
    they are meant to catch accidental equivalence, not to replace a theorem
    prover or a general model generator.
    """

    max_term_depth = int(world.metadata.get("max_term_depth", 3))
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    models: list[DiagnosticModel] = []

    def add_model(name: str, facts: tuple[ir.Fact, ...], clauses: tuple[ir.HornClause, ...]) -> None:
        model = DiagnosticModel(
            name=name,
            facts=facts,
            clauses=clauses,
            rewrites=world.rewrites,
            max_term_depth=max_term_depth,
        )
        key = _model_key(model)
        if key in seen:
            return
        seen.add(key)
        models.append(model)

    public_clauses = world.public_clauses()
    add_model("baseline", world.visible_facts, public_clauses)

    if world.visible_theorems:
        add_model("axioms_only", world.visible_facts, world.axioms)
        for theorem in world.visible_theorems:
            add_model(
                f"without_theorem:{theorem.name}",
                world.visible_facts,
                world.axioms + tuple(item for item in world.visible_theorems if item.name != theorem.name),
            )

    for fact in world.visible_facts:
        add_model(
            f"without_fact:{fact.name}",
            tuple(item for item in world.visible_facts if item.name != fact.name),
            public_clauses,
        )

    return tuple(models)
