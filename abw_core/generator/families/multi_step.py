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
from abw_core.generator.variation import schema_metadata, seeded_rng
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_multi_step_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world that rewards building an abstraction ladder in stages.

    The visible surface provides the low-level ingredients for constructing an
    object and proving a downstream property about it, but the hidden bridge
    introduces staged abstractions that make multi-step hidden goals cheaper.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        left_names = ("A",)
        right_names = ("B",)
        downstream_names = ("C", "K")
        base_count = 1
        noise_count = 0
        goal_depths = tuple(request.hidden_steps)
    else:
        left_names = tuple(f"A{i}" for i in range(rng.randint(1, 3)))
        right_names = tuple(f"B{i}" for i in range(rng.randint(1, 3)))
        downstream_names = tuple(f"C{i}" for i in range(rng.randint(2, 4)))
        base_count = rng.randint(1, 2)
        noise_count = rng.randint(0, 2)
        available_depths = list(range(2, max(3, request.max_term_depth) + 1))
        goal_count = min(len(available_depths), rng.randint(2, 3))
        goal_depths = tuple(sorted(rng.sample(available_depths, goal_count)))

    sorts = (ir.Sort("S0"), ir.Sort("S1"), ir.Sort("S2"))
    constants = tuple(ir.ConstantSymbol(f"c{i}", "S0") for i in range(base_count)) + tuple(
        ir.ConstantSymbol(f"d{i}", "S1") for i in range(base_count)
    )
    functions = (
        ir.FunctionSymbol("f", ("S0",), "S0"),
        ir.FunctionSymbol("g", ("S1",), "S1"),
        ir.FunctionSymbol("h", ("S0", "S1"), "S2"),
    )
    predicates = tuple(ir.PredicateSymbol(name, ("S0",)) for name in left_names) + tuple(
        ir.PredicateSymbol(name, ("S1",)) for name in right_names
    ) + tuple(ir.PredicateSymbol(name, ("S2",)) for name in downstream_names) + (
        ir.PredicateSymbol("R", ("S0", "S1")),
    ) + tuple(ir.PredicateSymbol(f"Noise{i}", ("S0",)) for i in range(noise_count))
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S1")
    z = ir.Variable("z", "S2")

    pair_atoms = tuple(ir.Atom(name, (ir.VarTerm(x),)) for name in left_names) + tuple(
        ir.Atom(name, (ir.VarTerm(y),)) for name in right_names
    ) + (ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),)
    axioms = tuple(
        ir.HornClause(
            name=f"{name.lower()}_step",
            variables=(x,),
            premises=(ir.Atom(name, (ir.VarTerm(x),)),),
            conclusion=ir.Atom(name, (ir.FuncTerm("f", (ir.VarTerm(x),)),)),
        )
        for name in left_names
    ) + tuple(
        ir.HornClause(
            name=f"{name.lower()}_step",
            variables=(y,),
            premises=(ir.Atom(name, (ir.VarTerm(y),)),),
            conclusion=ir.Atom(name, (ir.FuncTerm("g", (ir.VarTerm(y),)),)),
        )
        for name in right_names
    ) + (
        ir.HornClause(
            name="r_step",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom("R", (ir.FuncTerm("f", (ir.VarTerm(x),)), ir.FuncTerm("g", (ir.VarTerm(y),)))),
        ),
        ir.HornClause(
            name="construct_c",
            variables=(x, y),
            premises=pair_atoms,
            conclusion=ir.Atom(downstream_names[0], (ir.FuncTerm("h", (ir.VarTerm(x), ir.VarTerm(y))),)),
        ),
    ) + tuple(
        ir.HornClause(
            name=f"{downstream_names[index].lower()}_to_{downstream_names[index + 1].lower()}",
            variables=(z,),
            premises=(ir.Atom(downstream_names[index], (ir.VarTerm(z),)),),
            conclusion=ir.Atom(downstream_names[index + 1], (ir.VarTerm(z),)),
        )
        for index in range(len(downstream_names) - 1)
    ) + tuple(
        ir.HornClause(
            name=f"noise_{index}_step",
            variables=(x,),
            premises=(ir.Atom(f"Noise{index}", (ir.VarTerm(x),)),),
            conclusion=ir.Atom(f"Noise{index}", (ir.FuncTerm("f", (ir.VarTerm(x),)),)),
        )
        for index in range(noise_count)
    )
    visible_theorems = ()
    visible_facts = tuple(
        ir.Fact(f"base_{name.lower()}_{index}", ir.Atom(name, (ir.ConstTerm(f"c{index}"),)))
        for index in range(base_count)
        for name in left_names
    ) + tuple(
        ir.Fact(f"base_{name.lower()}_{index}", ir.Atom(name, (ir.ConstTerm(f"d{index}"),)))
        for index in range(base_count)
        for name in right_names
    ) + tuple(
        ir.Fact(
            f"base_r_{index}",
            ir.Atom("R", (ir.ConstTerm(f"c{index}"), ir.ConstTerm(f"d{index}"))),
        )
        for index in range(base_count)
    ) + tuple(
        ir.Fact(f"noise_{index}", ir.Atom(f"Noise{index}", (ir.ConstTerm("c0"),)))
        for index in range(noise_count)
    )

    paired_good = ir.Definition(
        name="PairedGood",
        parameters=(x, y),
        body=pair_atoms,
    )
    constructed_good = ir.Definition(
        name="ConstructedGood",
        parameters=(z,),
        body=(
            ir.Atom(downstream_names[0], (ir.VarTerm(z),)),
            ir.Atom(downstream_names[-1], (ir.VarTerm(z),)),
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
                name="constructed_is_final",
                variables=(x, y),
                premises=(ir.Atom("PairedGood", (ir.VarTerm(x), ir.VarTerm(y))),),
                conclusion=ir.Atom(
                    downstream_names[-1],
                    (ir.FuncTerm("h", (ir.VarTerm(x), ir.VarTerm(y))),),
                ),
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
            atoms=(ir.Atom(downstream_names[-1], (ir.FuncTerm("h", (left, right)),)),),
            budget=budget,
            description=f"Downstream K property after {steps} synchronized paired steps.",
        )

    targets_visible = (make_goal("visible_k_one", 1, request.proof_budget + 1),)
    targets_hidden = tuple(make_goal(f"hidden_k_{steps}", steps, request.proof_budget) for steps in goal_depths)

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
            "hidden_steps": list(goal_depths),
            **schema_metadata(
                request.family,
                {
                    "left_condition_count": len(left_names),
                    "right_condition_count": len(right_names),
                    "downstream_chain_length": len(downstream_names),
                    "base_pair_count": base_count,
                    "noise_count": noise_count,
                    "goal_depths": list(goal_depths),
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("multi_step", generate_multi_step_world)
