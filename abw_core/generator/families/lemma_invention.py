# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Lemma-invention family for reusable shortcut theorems.

This family shifts the bridge burden away from new predicates and toward new
derived rules. The visible world already contains the raw ingredients for a
multi-hop derivation, but the hidden bridge is the compact theorem that says
the whole chain can be treated as one reusable step.

Conceptually, this family measures whether a system notices repeated proof
patterns even when no new named predicate is required.
"""

from __future__ import annotations

from abw_core import ir
from abw_core.generator.base import WorldGenerationRequest, register_family, scoring_config
from abw_core.scorer.weights import NON_ANALOGY_WEIGHTS
from abw_core.generator.obfuscation import default_world_id
from abw_core.generator.templates import iterate_term
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world


def generate_lemma_invention_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose hidden bridge is a reusable shortcut lemma.

    The world exposes a visible chain of implications and a couple of partial
    shortcut theorems, but the most valuable missing object is the composed
    theorem that collapses the full chain.
    """

    sorts = (ir.Sort("S0"),)
    constants = (ir.ConstantSymbol("c0", "S0"),)
    functions = (
        ir.FunctionSymbol("f", ("S0",), "S0"),
        ir.FunctionSymbol("g", ("S0",), "S0"),
        ir.FunctionSymbol("h", ("S0",), "S0"),
    )
    predicates = (
        ir.PredicateSymbol("A", ("S0",)),
        ir.PredicateSymbol("B", ("S0",)),
        ir.PredicateSymbol("C", ("S0",)),
        ir.PredicateSymbol("D", ("S0",)),
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")

    axioms = (
        ir.HornClause(
            name="a_to_b",
            variables=(x,),
            premises=(ir.Atom("A", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("B", (ir.FuncTerm("f", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="b_to_c",
            variables=(x,),
            premises=(ir.Atom("B", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("C", (ir.FuncTerm("g", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="c_to_d",
            variables=(x,),
            premises=(ir.Atom("C", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("D", (ir.FuncTerm("h", (ir.VarTerm(x),)),)),
        ),
    )
    visible_theorems = (
        ir.HornClause(
            name="a_to_c",
            variables=(x,),
            premises=(ir.Atom("A", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("C", (ir.FuncTerm("g", (ir.FuncTerm("f", (ir.VarTerm(x),)),)),)),
        ),
        ir.HornClause(
            name="b_to_d",
            variables=(x,),
            premises=(ir.Atom("B", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("D", (ir.FuncTerm("h", (ir.FuncTerm("g", (ir.VarTerm(x),)),)),)),
        ),
    )
    visible_facts = (
        ir.Fact("base_a", ir.Atom("A", (ir.ConstTerm("c0"),))),
        ir.Fact("base_a_shifted", ir.Atom("A", (ir.FuncTerm("f", (ir.ConstTerm("c0"),)),))),
    )

    hidden_bridge = ir.Bridge(
        lemmas=(
            ir.HornClause(
                name="chain3",
                variables=(x,),
                premises=(ir.Atom("A", (ir.VarTerm(x),)),),
                conclusion=ir.Atom(
                    "D",
                    (ir.FuncTerm("h", (ir.FuncTerm("g", (ir.FuncTerm("f", (ir.VarTerm(x),)),)),)),),
                ),
            ),
        )
    )

    def make_goal(name: str, seed_term: ir.Term, budget: int) -> ir.Goal:
        """Build one downstream shortcut target from a chosen seed term.

        Reusing this helper keeps the visible and hidden targets aligned on the
        same composed-chain pattern while varying only the starting position.
        """

        return ir.Goal(
            name=name,
            atoms=(
                ir.Atom(
                    "D",
                    (ir.FuncTerm("h", (ir.FuncTerm("g", (ir.FuncTerm("f", (seed_term,)),)),)),),
                ),
            ),
            budget=budget,
            description="Shortcut theorem for the composed f/g/h propagation chain.",
        )

    targets_visible = (make_goal("visible_chain", ir.ConstTerm("c0"), request.proof_budget + 1),)
    targets_hidden = (
        make_goal("hidden_chain_base", ir.ConstTerm("c0"), request.proof_budget),
        make_goal("hidden_chain_shifted", iterate_term("f", ir.ConstTerm("c0"), 1), request.proof_budget),
    )

    baseline = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms + visible_theorems,
        max_term_depth=request.max_term_depth,
    )
    with_bridge = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms + visible_theorems + hidden_bridge.lemmas,
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


register_family("lemma_invention", generate_lemma_invention_world)
