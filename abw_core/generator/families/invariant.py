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
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_invariant_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose bridge is a preserved multi-predicate invariant.

    The visible rules make each component predicate propagate separately. The
    hidden bridge packages the fact that the triple travels together as one
    reusable preserved property.
    """

    sorts = (ir.Sort("S0"),)
    constants = (ir.ConstantSymbol("s0", "S0"),)
    functions = (ir.FunctionSymbol("step", ("S0",), "S0"),)
    predicates = (
        ir.PredicateSymbol("A", ("S0",)),
        ir.PredicateSymbol("B", ("S0",)),
        ir.PredicateSymbol("C", ("S0",)),
        ir.PredicateSymbol("Noise", ("S0",)),
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")

    axioms = (
        ir.HornClause(
            name="a_step",
            variables=(x,),
            premises=(ir.Atom("A", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("A", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="b_step",
            variables=(x,),
            premises=(ir.Atom("B", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("B", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="c_step",
            variables=(x,),
            premises=(ir.Atom("C", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("C", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="noise_step",
            variables=(x,),
            premises=(ir.Atom("Noise", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("Noise", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        ),
    )
    visible_theorems = (
        ir.HornClause(
            name="ab_step",
            variables=(x,),
            premises=(ir.Atom("A", (ir.VarTerm(x),)), ir.Atom("B", (ir.VarTerm(x),))),
            conclusion=ir.Atom("A", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
        ),
    )
    visible_facts = (
        ir.Fact("base_a", ir.Atom("A", (ir.ConstTerm("s0"),))),
        ir.Fact("base_b", ir.Atom("B", (ir.ConstTerm("s0"),))),
        ir.Fact("base_c", ir.Atom("C", (ir.ConstTerm("s0"),))),
        ir.Fact("noise", ir.Atom("Noise", (ir.ConstTerm("s0"),))),
    )

    stable_definition = ir.Definition(
        name="StableTriple",
        parameters=(x,),
        body=(
            ir.Atom("A", (ir.VarTerm(x),)),
            ir.Atom("B", (ir.VarTerm(x),)),
            ir.Atom("C", (ir.VarTerm(x),)),
        ),
    )
    stable_lemma = ir.HornClause(
        name="stable_step",
        variables=(x,),
        premises=(ir.Atom("StableTriple", (ir.VarTerm(x),)),),
        conclusion=ir.Atom("StableTriple", (ir.FuncTerm("step", (ir.VarTerm(x),)),)),
    )
    hidden_bridge = ir.Bridge(definitions=(stable_definition,), lemmas=(stable_lemma,))

    def make_goal(name: str, steps: int, budget: int) -> ir.Goal:
        """Build one preserved-state target at a chosen transition depth.

        The family's hidden targets all ask for the same bundled invariant after
        different numbers of steps, which is why this helper is shared.
        """

        term = iterate_term("step", ir.ConstTerm("s0"), steps)
        return ir.Goal(
            name=name,
            atoms=(
                ir.Atom("A", (term,)),
                ir.Atom("B", (term,)),
                ir.Atom("C", (term,)),
            ),
            budget=budget,
            description=f"Stable predicate bundle after {steps} transitions.",
        )

    targets_visible = (make_goal("visible_stable_step", 1, request.proof_budget + 1),)
    targets_hidden = tuple(
        make_goal(f"hidden_stable_{steps}", steps, request.proof_budget) for steps in request.hidden_steps
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
            "hidden_steps": list(request.hidden_steps),
        },
    )
    check_world(world)
    return world


register_family("invariant", generate_invariant_world)
