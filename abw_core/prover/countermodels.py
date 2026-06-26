# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Bounded Herbrand-style countermodels for failed ABW goals.

The Horn prover computes the least model over the bounded generated term
universe. When a goal atom is absent from that closure, the closure itself is a
finite countermodel under the closed-world reading used by this runtime. This
module packages that model into a stable JSON-friendly shape for diagnostics
and later interactive refinement loops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from abw_core import ir
from abw_core.prover.horn import ProofResult, build_closure
from abw_core.prover.rewrite import normalize_atom


@dataclass(frozen=True)
class BoundedCountermodel:
    """A bounded public model showing why one or more atoms are false."""

    label: str
    sort_domains: dict[str, tuple[ir.Term, ...]]
    predicate_extensions: dict[str, tuple[tuple[ir.Term, ...], ...]]
    true_atoms: tuple[ir.Atom, ...]
    false_atoms: tuple[ir.Atom, ...]
    derived_atom_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bounded countermodel into a JSON-friendly payload."""

        return {
            "label": self.label,
            "sort_domains": {
                sort: [term.to_dict() for term in terms]
                for sort, terms in self.sort_domains.items()
            },
            "predicate_extensions": {
                predicate: [[term.to_dict() for term in terms] for terms in extension]
                for predicate, extension in self.predicate_extensions.items()
            },
            "true_atoms": [atom.to_dict() for atom in self.true_atoms],
            "false_atoms": [atom.to_dict() for atom in self.false_atoms],
            "derived_atom_count": self.derived_atom_count,
        }


def _term_key(term: ir.Term) -> str:
    return str(term.to_dict())


def _atom_key(atom: ir.Atom) -> str:
    return str(atom.to_dict())


def _extension_key(terms: tuple[ir.Term, ...]) -> tuple[str, ...]:
    return tuple(_term_key(term) for term in terms)


def _predicate_extensions(
    signature: ir.Signature,
    closure: ProofResult,
) -> dict[str, tuple[tuple[ir.Term, ...], ...]]:
    grouped: dict[str, set[tuple[ir.Term, ...]]] = {
        predicate.name: set()
        for predicate in signature.predicates
    }
    for atom in closure.derivations:
        if atom.predicate == "=":
            continue
        grouped.setdefault(atom.predicate, set()).add(atom.terms)
    return {
        predicate: tuple(sorted(extension, key=_extension_key))
        for predicate, extension in sorted(grouped.items())
    }


def countermodel_for_atoms(
    signature: ir.Signature,
    closure: ProofResult,
    atoms: tuple[ir.Atom, ...],
    *,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    label: str = "",
) -> BoundedCountermodel | None:
    """Build a bounded countermodel when one or more focus atoms are missing."""

    normalized_atoms = tuple(normalize_atom(atom, rewrites) for atom in atoms)
    true_atoms = tuple(atom for atom in normalized_atoms if atom in closure.derivations)
    false_atoms = tuple(atom for atom in normalized_atoms if atom not in closure.derivations)
    if not false_atoms:
        return None
    derived_atom_count = sum(1 for atom in closure.derivations if atom.predicate != "=")
    return BoundedCountermodel(
        label=label,
        sort_domains=closure.terms_by_sort,
        predicate_extensions=_predicate_extensions(signature, closure),
        true_atoms=tuple(sorted(true_atoms, key=_atom_key)),
        false_atoms=tuple(sorted(false_atoms, key=_atom_key)),
        derived_atom_count=derived_atom_count,
    )


def find_goal_countermodel(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    goal_atoms: tuple[ir.Atom, ...],
    *,
    definitions: tuple[ir.Definition, ...] = (),
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    label: str = "",
) -> BoundedCountermodel | None:
    """Return the least-model countermodel for a failed bounded goal."""

    closure = build_closure(
        signature,
        facts=facts,
        clauses=clauses,
        definitions=definitions,
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    )
    return countermodel_for_atoms(
        signature,
        closure,
        goal_atoms,
        rewrites=rewrites,
        label=label,
    )
