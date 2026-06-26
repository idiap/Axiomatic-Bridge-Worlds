# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Quotient-style family built around equivalence-class reasoning.

This family asks the system to move from surface objects to better
representatives. The visible world exposes an equivalence-like relation and
rules that respect it, while the hidden bridge packages the idea that reasoning
can be organized around representatives or equivalence classes.

It is the ABW family closest to "same underlying object, different surface
form" reasoning.
"""

from __future__ import annotations

from abw_core import ir
from abw_core.generator.base import WorldGenerationRequest, register_family, scoring_config
from abw_core.scorer.weights import NON_ANALOGY_WEIGHTS
from abw_core.generator.obfuscation import default_world_id
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_quotient_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose bridge relies on quotient-style reasoning.

    The hidden bridge introduces representative-oriented predicates and lemmas
    so downstream goals can be expressed through canonical class members rather
    than every raw term variant separately.
    """

    sorts = (ir.Sort("S0"),)
    constants = (ir.ConstantSymbol("c0", "S0"),)
    functions = (
        ir.FunctionSymbol("norm", ("S0",), "S0"),
        ir.FunctionSymbol("step", ("S0",), "S0"),
    )
    predicates = (
        ir.PredicateSymbol("Good", ("S0",)),
        ir.PredicateSymbol("R", ("S0", "S0")),
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S0")
    z = ir.Variable("z", "S0")

    axioms = (
        ir.HornClause(
            name="r_refl",
            variables=(x,),
            premises=(),
            conclusion=ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(x))),
        ),
        ir.HornClause(
            name="r_sym",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom("R", (ir.VarTerm(y), ir.VarTerm(x))),
        ),
        ir.HornClause(
            name="r_trans",
            variables=(x, y, z),
            premises=(
                ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
                ir.Atom("R", (ir.VarTerm(y), ir.VarTerm(z))),
            ),
            conclusion=ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(z))),
        ),
        ir.HornClause(
            name="norm_related",
            variables=(x,),
            premises=(),
            conclusion=ir.Atom("R", (ir.VarTerm(x), ir.FuncTerm("norm", (ir.VarTerm(x),)))),
        ),
        ir.HornClause(
            name="good_respects_r",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))), ir.Atom("Good", (ir.VarTerm(x),))),
            conclusion=ir.Atom("Good", (ir.VarTerm(y),)),
        ),
        ir.HornClause(
            name="step_respects_r",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom("R", (ir.FuncTerm("step", (ir.VarTerm(x),)), ir.FuncTerm("step", (ir.VarTerm(y),)))),
        ),
    )
    visible_facts = (ir.Fact("base_good", ir.Atom("Good", (ir.ConstTerm("c0"),))),)
    visible_theorems = ()

    same_class = ir.Definition(
        name="SameClass",
        parameters=(x, y),
        body=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
    )
    representative = ir.Definition(
        name="Representative",
        parameters=(x,),
        body=(ir.Atom("=", (ir.FuncTerm("norm", (ir.VarTerm(x),)), ir.VarTerm(x))),),
    )
    hidden_bridge = ir.Bridge(
        definitions=(same_class, representative),
        lemmas=(
            ir.HornClause(
                name="good_transfer",
                variables=(x,),
                premises=(ir.Atom("Good", (ir.VarTerm(x),)),),
                conclusion=ir.Atom("Good", (ir.FuncTerm("norm", (ir.VarTerm(x),)),)),
            ),
            ir.HornClause(
                name="step_class",
                variables=(x, y),
                premises=(ir.Atom("SameClass", (ir.VarTerm(x), ir.VarTerm(y))),),
                conclusion=ir.Atom(
                    "SameClass",
                    (ir.FuncTerm("step", (ir.VarTerm(x),)), ir.FuncTerm("step", (ir.VarTerm(y),))),
                ),
            ),
        ),
    )

    targets_visible = (
        ir.Goal(
            name="visible_good_norm",
            atoms=(ir.Atom("Good", (ir.FuncTerm("norm", (ir.ConstTerm("c0"),)),)),),
            budget=request.proof_budget + 1,
            description="Representative inherits goodness.",
        ),
    )
    targets_hidden = (
        ir.Goal(
            name="hidden_good_norm",
            atoms=(ir.Atom("Good", (ir.FuncTerm("norm", (ir.ConstTerm("c0"),)),)),),
            budget=request.proof_budget,
            description="Good transfers to the chosen representative.",
        ),
        ir.Goal(
            name="hidden_step_class",
            atoms=(
                ir.Atom(
                    "R",
                    (ir.FuncTerm("step", (ir.ConstTerm("c0"),)), ir.FuncTerm("step", (ir.FuncTerm("norm", (ir.ConstTerm("c0"),)),))),
                ),
            ),
            budget=request.proof_budget,
            description="Stepping preserves equivalence classes through representatives.",
        ),
    )

    baseline = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms,
        max_term_depth=request.max_term_depth,
    )
    with_bridge = build_closure(
        extend_signature_with_definitions(signature, hidden_bridge.definitions),
        facts=visible_facts,
        clauses=axioms + hidden_bridge.lemmas,
        definitions=hidden_bridge.definitions,
        max_term_depth=request.max_term_depth,
    )
    proof_fixtures = {
        goal.name: {
            "baseline_cost": goal_cost(baseline.derivations, goal.atoms),
            "gold_cost": goal_cost(with_bridge.derivations, goal.atoms),
            "budget": goal.budget,
        }
        for goal in targets_hidden
    }

    world = ir.World(
        world_id=request.world_id or default_world_id(request.family, request.seed),
        family=request.family,
        signature=signature,
        axioms=axioms,
        visible_theorems=visible_theorems,
        visible_facts=visible_facts,
        targets_visible=targets_visible,
        targets_hidden=targets_hidden,
        hidden_bridge=hidden_bridge,
        proof_fixtures=proof_fixtures,
        scoring_config=scoring_config(request, weights=NON_ANALOGY_WEIGHTS),
        metadata={
            "seed": request.seed,
            "max_term_depth": request.max_term_depth,
            "dsl_version": "abw-dsl-v1",
        },
    )
    check_world(world)
    return world


register_family("quotient", generate_quotient_world)
