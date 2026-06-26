# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Distractor helpers for the predicate-invention family."""

from __future__ import annotations

from abw_core import ir


def predicate_invention_distractors() -> tuple[tuple[ir.PredicateSymbol, ...], tuple[ir.HornClause, ...], tuple[ir.Fact, ...], tuple[ir.HornClause, ...]]:
    """Return a reusable distractor bundle for predicate-invention worlds."""

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S1")
    predicates = (
        ir.PredicateSymbol("Q0", ("S0",)),
        ir.PredicateSymbol("Q1", ("S1",)),
    )
    axioms = (
        ir.HornClause(
            name="q0_step",
            variables=(x,),
            premises=(ir.Atom("Q0", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("Q0", (ir.FuncTerm("f0", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="q1_step",
            variables=(y,),
            premises=(ir.Atom("Q1", (ir.VarTerm(y),)),),
            conclusion=ir.Atom("Q1", (ir.FuncTerm("f1", (ir.VarTerm(y),)),)),
        ),
    )
    facts = (
        ir.Fact("base_q0", ir.Atom("Q0", (ir.ConstTerm("c0"),))),
        ir.Fact("base_q1", ir.Atom("Q1", (ir.ConstTerm("d0"),))),
    )
    theorems = (
        ir.HornClause(
            name="visible_q_pair_step",
            variables=(x, y),
            premises=(
                ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
                ir.Atom("Q0", (ir.VarTerm(x),)),
                ir.Atom("Q1", (ir.VarTerm(y),)),
            ),
            conclusion=ir.Atom("R", (ir.FuncTerm("f0", (ir.VarTerm(x),)), ir.FuncTerm("f1", (ir.VarTerm(y),)))),
        ),
    )
    return predicates, axioms, facts, theorems
