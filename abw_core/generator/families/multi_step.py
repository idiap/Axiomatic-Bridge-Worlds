# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Multi-step family for abstraction ladders whose value grows with depth.

Some bridges are only mildly helpful at one step and clearly helpful only after
several composed transitions. This family is built to reward that deeper,
ladder-like organization of reasoning.

The hidden bridge usually names an intermediate paired structure and then a
second abstraction built on top of it, so the payoff compounds across steps.
"""

from __future__ import annotations

from abw_core import ir
from abw_core.generator.base import WorldGenerationRequest, register_family, scoring_config
from abw_core.scorer.weights import NON_ANALOGY_WEIGHTS
from abw_core.generator.obfuscation import default_world_id
from abw_core.generator.templates import iterate_term
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_multi_step_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world that rewards building an abstraction ladder in stages.

    The visible surface provides the low-level ingredients for constructing an
    object and proving a downstream property about it, but the hidden bridge
    introduces staged abstractions that make multi-step hidden goals cheaper.
    """

    sorts = (ir.Sort("S0"), ir.Sort("S1"), ir.Sort("S2"))
    constants = (
        ir.ConstantSymbol("c0", "S0"),
        ir.ConstantSymbol("d0", "S1"),
    )
    functions = (
        ir.FunctionSymbol("f", ("S0",), "S0"),
        ir.FunctionSymbol("g", ("S1",), "S1"),
        ir.FunctionSymbol("h", ("S0", "S1"), "S2"),
    )
    predicates = (
        ir.PredicateSymbol("A", ("S0",)),
        ir.PredicateSymbol("B", ("S1",)),
        ir.PredicateSymbol("C", ("S2",)),
        ir.PredicateSymbol("R", ("S0", "S1")),
        ir.PredicateSymbol("K", ("S2",)),
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S1")
    z = ir.Variable("z", "S2")

    axioms = (
        ir.HornClause(
            name="a_step",
            variables=(x,),
            premises=(ir.Atom("A", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("A", (ir.FuncTerm("f", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="b_step",
            variables=(y,),
            premises=(ir.Atom("B", (ir.VarTerm(y),)),),
            conclusion=ir.Atom("B", (ir.FuncTerm("g", (ir.VarTerm(y),)),)),
        ),
        ir.HornClause(
            name="r_step",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom("R", (ir.FuncTerm("f", (ir.VarTerm(x),)), ir.FuncTerm("g", (ir.VarTerm(y),)))),
        ),
        ir.HornClause(
            name="construct_c",
            variables=(x, y),
            premises=(
                ir.Atom("A", (ir.VarTerm(x),)),
                ir.Atom("B", (ir.VarTerm(y),)),
                ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
            ),
            conclusion=ir.Atom("C", (ir.FuncTerm("h", (ir.VarTerm(x), ir.VarTerm(y))),)),
        ),
        ir.HornClause(
            name="c_to_k",
            variables=(z,),
            premises=(ir.Atom("C", (ir.VarTerm(z),)),),
            conclusion=ir.Atom("K", (ir.VarTerm(z),)),
        ),
    )
    visible_theorems = ()
    visible_facts = (
        ir.Fact("base_a", ir.Atom("A", (ir.ConstTerm("c0"),))),
        ir.Fact("base_b", ir.Atom("B", (ir.ConstTerm("d0"),))),
        ir.Fact("base_r", ir.Atom("R", (ir.ConstTerm("c0"), ir.ConstTerm("d0")))),
    )

    paired_good = ir.Definition(
        name="PairedGood",
        parameters=(x, y),
        body=(
            ir.Atom("A", (ir.VarTerm(x),)),
            ir.Atom("B", (ir.VarTerm(y),)),
            ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
        ),
    )
    constructed_good = ir.Definition(
        name="ConstructedGood",
        parameters=(z,),
        body=(
            ir.Atom("C", (ir.VarTerm(z),)),
            ir.Atom("K", (ir.VarTerm(z),)),
        ),
    )
    hidden_bridge = ir.Bridge(
        definitions=(paired_good, constructed_good),
        lemmas=(
            ir.HornClause(
                name="paired_step",
                variables=(x, y),
                premises=(ir.Atom("PairedGood", (ir.VarTerm(x), ir.VarTerm(y))),),
                conclusion=ir.Atom(
                    "PairedGood",
                    (ir.FuncTerm("f", (ir.VarTerm(x),)), ir.FuncTerm("g", (ir.VarTerm(y),))),
                ),
            ),
            ir.HornClause(
                name="constructed_is_k",
                variables=(x, y),
                premises=(ir.Atom("PairedGood", (ir.VarTerm(x), ir.VarTerm(y))),),
                conclusion=ir.Atom("K", (ir.FuncTerm("h", (ir.VarTerm(x), ir.VarTerm(y))),)),
            ),
            ir.HornClause(
                name="constructed_good_intro",
                variables=(x, y),
                premises=(ir.Atom("PairedGood", (ir.VarTerm(x), ir.VarTerm(y))),),
                conclusion=ir.Atom("ConstructedGood", (ir.FuncTerm("h", (ir.VarTerm(x), ir.VarTerm(y))),)),
            ),
        ),
    )

    def make_goal(name: str, steps: int, budget: int) -> ir.Goal:
        """Build one downstream property target after synchronized paired steps.

        This helper expresses the family's main difficulty knob: the deeper the
        paired transition chain, the more valuable the hidden abstraction ladder
        becomes.
        """

        left = iterate_term("f", ir.ConstTerm("c0"), steps)
        right = iterate_term("g", ir.ConstTerm("d0"), steps)
        return ir.Goal(
            name=name,
            atoms=(ir.Atom("K", (ir.FuncTerm("h", (left, right)),)),),
            budget=budget,
            description=f"Downstream K property after {steps} synchronized paired steps.",
        )

    targets_visible = (make_goal("visible_k_one", 1, request.proof_budget + 1),)
    targets_hidden = tuple(
        make_goal(f"hidden_k_{steps}", steps, request.proof_budget) for steps in request.hidden_steps
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
            "hidden_steps": list(request.hidden_steps),
        },
    )
    check_world(world)
    return world


register_family("multi_step", generate_multi_step_world)
