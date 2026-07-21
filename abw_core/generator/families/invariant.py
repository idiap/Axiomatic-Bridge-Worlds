# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Invariant-discovery family for preserved multi-predicate structure.

This family asks the system to notice that several predicates are not merely
true now; they stay true together under transition. The hidden bridge is the
named invariant plus the preservation lemma that makes that persistence usable.

Compared with plain predicate invention, the conceptual pressure here is on
stability across time or steps rather than on one static conjunction alone.
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


def generate_invariant_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose bridge is a preserved multi-predicate invariant.

    The visible rules make each component predicate propagate separately. The
    hidden bridge packages the fact that the triple travels together as one
    reusable preserved property.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        invariant_names = ("A", "B", "C")
        base_count = 1
        noise_count = 1
        transition_names = ("step",)
        goal_depths = tuple(request.hidden_steps)
        definition_name = "StableTriple"
    else:
        invariant_names = tuple(chr(ord("A") + index) for index in range(rng.randint(2, 5)))
        base_count = rng.randint(1, 3)
        noise_count = rng.randint(0, 3)
        transition_names = ("step", "jump")[: rng.randint(1, 2)]
        available_depths = list(range(2, max(3, request.max_term_depth) + 1))
        goal_count = min(len(available_depths), rng.randint(2, 3))
        goal_depths = tuple(sorted(rng.sample(available_depths, goal_count)))
        definition_name = "StableBundle"

    sorts = (ir.Sort("S0"),)
    constants = tuple(ir.ConstantSymbol(f"s{i}", "S0") for i in range(base_count))
    functions = tuple(ir.FunctionSymbol(name, ("S0",), "S0") for name in transition_names)
    predicates = tuple(ir.PredicateSymbol(name, ("S0",)) for name in invariant_names) + tuple(
        ir.PredicateSymbol(f"Noise{i}", ("S0",)) for i in range(noise_count)
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")

    axioms = tuple(
        ir.HornClause(
            name=f"{predicate.lower()}_{transition}",
            variables=(x,),
            premises=(ir.Atom(predicate, (ir.VarTerm(x),)),),
            conclusion=ir.Atom(predicate, (ir.FuncTerm(transition, (ir.VarTerm(x),)),)),
        )
        for transition in transition_names
        for predicate in invariant_names
    ) + tuple(
        ir.HornClause(
            name=f"noise_{index}_step",
            variables=(x,),
            premises=(ir.Atom(f"Noise{index}", (ir.VarTerm(x),)),),
            conclusion=ir.Atom(f"Noise{index}", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        )
        for index in range(noise_count)
    )
    visible_theorems = (
        ir.HornClause(
            name="ab_step",
            variables=(x,),
            premises=tuple(ir.Atom(name, (ir.VarTerm(x),)) for name in invariant_names[:2]),
            conclusion=ir.Atom(invariant_names[0], (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        ),
    )
    visible_facts = tuple(
        ir.Fact(f"base_{name.lower()}_{base}", ir.Atom(name, (ir.ConstTerm(f"s{base}"),)))
        for base in range(base_count)
        for name in invariant_names
    ) + tuple(
        ir.Fact(f"noise_{index}", ir.Atom(f"Noise{index}", (ir.ConstTerm("s0"),)))
        for index in range(noise_count)
    )

    stable_definition = ir.Definition(
        name=definition_name,
        parameters=(x,),
        body=tuple(ir.Atom(name, (ir.VarTerm(x),)) for name in invariant_names),
    )
    stable_lemmas = tuple(
        ir.HornClause(
            name=f"stable_{transition}",
            variables=(x,),
            premises=(ir.Atom(definition_name, (ir.VarTerm(x),)),),
            conclusion=ir.Atom(definition_name, (ir.FuncTerm(transition, (ir.VarTerm(x),)),)),
        )
        for transition in transition_names
    )
    hidden_bridge = ir.Bridge(definitions=(stable_definition,), lemmas=stable_lemmas)

    def make_goal(name: str, transition: str, steps: int, budget: int) -> ir.Goal:
        """Build one preserved-state target at a chosen transition depth.

        The family's hidden targets all ask for the same bundled invariant after
        different numbers of steps, which is why this helper is shared.
        """

        term = iterate_term(transition, ir.ConstTerm("s0"), steps)
        return ir.Goal(
            name=name,
            atoms=tuple(ir.Atom(predicate, (term,)) for predicate in invariant_names),
            budget=budget,
            description=f"Stable predicate bundle after {steps} transitions.",
        )

    targets_visible = (make_goal("visible_stable_step", "step", 1, request.proof_budget + 1),)
    targets_hidden = tuple(
        make_goal(f"hidden_{transition}_{steps}", transition, steps, request.proof_budget)
        for transition in transition_names
        for steps in goal_depths
    )

    baseline = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms + visible_theorems,
        max_term_depth=request.max_term_depth,
    )
    with_bridge = build_closure(
        extend_signature_with_definitions(signature, hidden_bridge.definitions),
        facts=visible_facts,
        clauses=axioms + visible_theorems + hidden_bridge.lemmas,
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
                    "invariant_width": len(invariant_names),
                    "base_count": base_count,
                    "noise_count": noise_count,
                    "transition_count": len(transition_names),
                    "goal_depths": list(goal_depths),
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("invariant", generate_invariant_world)
