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
from abw_core.generator.templates import iterate_term
from abw_core.generator.variation import schema_metadata, seeded_rng
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_quotient_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose bridge relies on quotient-style reasoning.

    The hidden bridge introduces representative-oriented predicates and lemmas
    so downstream goals can be expressed through canonical class members rather
    than every raw term variant separately.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        property_names = ("Good",)
        normalizer_names = ("norm",)
        transition_names = ("step",)
        base_count = 1
        alias_count = 0
        step_goal_depth = 1
        tag_count = 0
    else:
        property_names = tuple(f"Good{i}" for i in range(rng.randint(1, 4)))
        normalizer_names = ("norm",)
        transition_names = ("step",)
        base_count = rng.randint(1, 2)
        alias_count = rng.randint(0, 3)
        step_goal_depth = rng.randint(1, 2)
        tag_count = rng.randint(0, 3)

    sorts = (ir.Sort("S0"),)
    constants = tuple(ir.ConstantSymbol(f"c{i}", "S0") for i in range(base_count)) + tuple(
        ir.ConstantSymbol(f"a{i}", "S0") for i in range(alias_count)
    )
    functions = tuple(
        ir.FunctionSymbol(name, ("S0",), "S0") for name in normalizer_names + transition_names
    )
    predicates = tuple(ir.PredicateSymbol(name, ("S0",)) for name in property_names) + (
        ir.PredicateSymbol("R", ("S0", "S0")),
    ) + tuple(ir.PredicateSymbol(f"Tag{i}", ("S0",)) for i in range(tag_count))
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S0")
    z = ir.Variable("z", "S0")
    quotient_term_depth = min(request.max_term_depth, 3)

    equivalence_axioms = (
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
    )
    axioms = equivalence_axioms + tuple(
        ir.HornClause(
            name=f"{normalizer}_related",
            variables=(x,),
            premises=(),
            conclusion=ir.Atom("R", (ir.VarTerm(x), ir.FuncTerm(normalizer, (ir.VarTerm(x),)))),
        )
        for normalizer in normalizer_names
    ) + tuple(
        ir.HornClause(
            name=f"{property_name.lower()}_respects_r",
            variables=(x, y),
            premises=(
                ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
                ir.Atom(property_name, (ir.VarTerm(x),)),
            ),
            conclusion=ir.Atom(property_name, (ir.VarTerm(y),)),
        )
        for property_name in property_names
    ) + tuple(
        ir.HornClause(
            name=f"{transition}_respects_r",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom(
                "R",
                (
                    ir.FuncTerm(transition, (ir.VarTerm(x),)),
                    ir.FuncTerm(transition, (ir.VarTerm(y),)),
                ),
            ),
        )
        for transition in transition_names
    )
    visible_facts = tuple(
        ir.Fact(
            f"base_{property_name.lower()}_{index}",
            ir.Atom(property_name, (ir.ConstTerm(f"c{index}"),)),
        )
        for index in range(base_count)
        for property_name in property_names
    ) + tuple(
        ir.Fact(
            f"alias_{index}",
            ir.Atom("R", (ir.ConstTerm("c0"), ir.ConstTerm(f"a{index}"))),
        )
        for index in range(alias_count)
    ) + tuple(
        ir.Fact(f"tag_{index}", ir.Atom(f"Tag{index}", (ir.ConstTerm("c0"),)))
        for index in range(tag_count)
    )
    visible_theorems = ()

    same_class = ir.Definition(
        name="SameClass",
        parameters=(x, y),
        body=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
    )
    representative_definitions = tuple(
        ir.Definition(
            name="Representative" if request.seed == 7 else f"Representative{index}",
            parameters=(x,),
            body=(ir.Atom("=", (ir.FuncTerm(normalizer, (ir.VarTerm(x),)), ir.VarTerm(x))),),
        )
        for index, normalizer in enumerate(normalizer_names)
    )
    hidden_bridge = ir.Bridge(
        definitions=(same_class,) + representative_definitions,
        lemmas=tuple(
            ir.HornClause(
                name=f"{property_name.lower()}_{normalizer}_transfer",
                variables=(x,),
                premises=(ir.Atom(property_name, (ir.VarTerm(x),)),),
                conclusion=ir.Atom(property_name, (ir.FuncTerm(normalizer, (ir.VarTerm(x),)),)),
            )
            for property_name in property_names
            for normalizer in normalizer_names
        )
        + tuple(
            ir.HornClause(
                name=f"{transition}_class",
                variables=(x, y),
                premises=(ir.Atom("SameClass", (ir.VarTerm(x), ir.VarTerm(y))),),
                conclusion=ir.Atom(
                    "SameClass",
                    (
                        ir.FuncTerm(transition, (ir.VarTerm(x),)),
                        ir.FuncTerm(transition, (ir.VarTerm(y),)),
                    ),
                ),
            )
            for transition in transition_names
        ),
    )

    targets_visible = (
        ir.Goal(
            name="visible_good_norm",
            atoms=(
                ir.Atom(
                    property_names[0],
                    (ir.FuncTerm(normalizer_names[0], (ir.ConstTerm("c0"),)),),
                ),
            ),
            budget=request.proof_budget + 1,
            description="Representative inherits goodness.",
        ),
    )
    targets_hidden = tuple(
        ir.Goal(
            name=f"hidden_{property_name.lower()}_{normalizer}",
            atoms=(
                ir.Atom(property_name, (ir.FuncTerm(normalizer, (ir.ConstTerm("c0"),)),)),
            ),
            budget=request.proof_budget,
            description="Good transfers to the chosen representative.",
        )
        for property_name in property_names
        for normalizer in normalizer_names
    ) + tuple(
        ir.Goal(
            name=f"hidden_{transition}_class",
            atoms=(
                ir.Atom(
                    "R",
                    (
                        iterate_term(transition, ir.ConstTerm("c0"), step_goal_depth),
                        iterate_term(
                            transition,
                            ir.FuncTerm(normalizer_names[0], (ir.ConstTerm("c0"),)),
                            step_goal_depth,
                        ),
                    ),
                ),
            ),
            budget=request.proof_budget,
            description="Stepping preserves equivalence classes through representatives.",
        )
        for transition in transition_names
    )

    baseline = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms,
        max_term_depth=quotient_term_depth,
    )
    with_bridge = build_closure(
        extend_signature_with_definitions(signature, hidden_bridge.definitions),
        facts=visible_facts,
        clauses=axioms + hidden_bridge.lemmas,
        definitions=hidden_bridge.definitions,
        max_term_depth=quotient_term_depth,
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
            "max_term_depth": quotient_term_depth,
            "dsl_version": "abw-dsl-v1",
            **schema_metadata(
                request.family,
                {
                    "property_count": len(property_names),
                    "normalizer_count": len(normalizer_names),
                    "transition_count": len(transition_names),
                    "base_count": base_count,
                    "alias_count": alias_count,
                    "step_goal_depth": step_goal_depth,
                    "public_tag_count": tag_count,
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("quotient", generate_quotient_world)
