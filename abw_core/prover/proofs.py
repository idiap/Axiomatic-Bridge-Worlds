# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Proof-trace helpers for bounded ABW Horn reasoning."""

from __future__ import annotations

from dataclasses import dataclass

from abw_core import ir
from abw_core.prover.rewrite import normalize_atom


@dataclass(frozen=True)
class Derivation:
    """One proof record for a derived atom in the bounded closure."""

    atom: ir.Atom
    rule_name: str | None
    rule_kind: str
    premises: tuple[ir.Atom, ...]
    step_cost: int
    total_cost: int


def missing_goal_atoms(
    derivations: dict[ir.Atom, Derivation],
    atoms: tuple[ir.Atom, ...],
    rewrites: tuple[ir.RewriteRule, ...] = (),
) -> tuple[ir.Atom, ...]:
    """Return the goal atoms that are still absent from the bounded closure."""

    return tuple(atom for atom in atoms if normalize_atom(atom, rewrites) not in derivations)


def goal_cost(
    derivations: dict[ir.Atom, Derivation],
    atoms: tuple[ir.Atom, ...],
    rewrites: tuple[ir.RewriteRule, ...] = (),
) -> int | None:
    """Count the distinct positive proof steps needed to support a goal."""

    if missing_goal_atoms(derivations, atoms, rewrites):
        return None

    positive_steps: set[tuple[str, str, tuple[str, ...]]] = set()
    visited: set[ir.Atom] = set()

    def visit(atom: ir.Atom) -> None:
        atom = normalize_atom(atom, rewrites)
        if atom in visited:
            return
        visited.add(atom)
        derivation = derivations[atom]
        if derivation.step_cost > 0 and derivation.rule_name is not None:
            positive_steps.add(
                (
                    derivation.rule_name,
                    derivation.rule_kind,
                    tuple(str(premise.to_dict()) for premise in derivation.premises),
                )
            )
        for premise in derivation.premises:
            visit(premise)

    for atom in atoms:
        visit(atom)
    return len(positive_steps)
