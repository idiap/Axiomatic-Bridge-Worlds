# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Small reusable helpers for ABW world templates."""

from __future__ import annotations

from abw_core import ir


def iterate_term(function_name: str, base: ir.Term, steps: int) -> ir.Term:
    """Apply one unary function symbol repeatedly to build a term ladder."""

    term = base
    for _ in range(steps):
        term = ir.FuncTerm(function_name, (term,))
    return term


def unary_clause(name: str, variable: ir.Variable, premise_predicate: str, conclusion_predicate: str, function_name: str) -> ir.HornClause:
    """Build a common unary step clause used across several families."""

    premise = ir.Atom(premise_predicate, (ir.VarTerm(variable),))
    conclusion = ir.Atom(conclusion_predicate, (ir.FuncTerm(function_name, (ir.VarTerm(variable),)),))
    return ir.HornClause(name=name, variables=(variable,), premises=(premise,), conclusion=conclusion)
