# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Normal-form family for rewrite-aware abstraction in ABW.

These worlds are built so that the interesting reasoning does not happen on the
raw surface syntax alone. Rewriting collapses several surface terms into a more
canonical form, and the hidden bridge names the normal-form viewpoint that
makes that collapse conceptually useful.

This family is where ABW's rewrite support becomes part of the abstraction
story rather than a side feature of the prover.
"""

from __future__ import annotations

from abw_core import ir
from abw_core.generator.base import WorldGenerationRequest, register_family, scoring_config
from abw_core.scorer.weights import NON_ANALOGY_WEIGHTS
from abw_core.generator.obfuscation import default_world_id
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_normal_form_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one rewrite-heavy world whose bridge captures normal forms.

    The visible theory already proves some `Done` facts after rewriting, but
    the hidden bridge is the compact abstraction that says "this term is already
    in normal form," which then supports downstream reasoning more directly.
    """

    sorts = (ir.Sort("T"),)
    constants = (ir.ConstantSymbol("z", "T"),)
    functions = (
        ir.FunctionSymbol("a", ("T",), "T"),
        ir.FunctionSymbol("b", ("T",), "T"),
        ir.FunctionSymbol("n", ("T",), "T"),
    )
    predicates = (ir.PredicateSymbol("Done", ("T",)),)
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "T")

    rewrites = (
        ir.RewriteRule(
            name="r1",
            lhs=ir.FuncTerm("a", (ir.FuncTerm("b", (ir.VarTerm(ir.Variable("x", "_")),)),)),
            rhs=ir.FuncTerm("n", (ir.VarTerm(ir.Variable("x", "_")),)),
        ),
        ir.RewriteRule(
            name="r2",
            lhs=ir.FuncTerm("b", (ir.FuncTerm("a", (ir.VarTerm(ir.Variable("x", "_")),)),)),
            rhs=ir.FuncTerm("n", (ir.VarTerm(ir.Variable("x", "_")),)),
        ),
        ir.RewriteRule(
            name="r3",
            lhs=ir.FuncTerm("n", (ir.FuncTerm("n", (ir.VarTerm(ir.Variable("x", "_")),)),)),
            rhs=ir.FuncTerm("n", (ir.VarTerm(ir.Variable("x", "_")),)),
        ),
    )
    axioms = (
        ir.HornClause(
            name="done_n",
            variables=(x,),
            premises=(),
            conclusion=ir.Atom("Done", (ir.FuncTerm("n", (ir.VarTerm(x),)),)),
        ),
    )
    visible_theorems = (
        ir.HornClause(
            name="visible_done_ab",
            variables=(x,),
            premises=(),
            conclusion=ir.Atom("Done", (ir.FuncTerm("a", (ir.FuncTerm("b", (ir.VarTerm(x),)),)),)),
        ),
    )
    visible_facts = ()

    normal_definition = ir.Definition(
        name="Normal",
        parameters=(x,),
        body=(ir.Atom("=", (ir.FuncTerm("n", (ir.VarTerm(x),)), ir.VarTerm(x))),),
    )
    hidden_bridge = ir.Bridge(
        definitions=(normal_definition,),
        lemmas=(
            ir.HornClause(
                name="done_after_normalize",
                variables=(x,),
                premises=(ir.Atom("Normal", (ir.VarTerm(x),)),),
                conclusion=ir.Atom("Done", (ir.VarTerm(x),)),
            ),
        ),
    )

    targets_visible = (
        ir.Goal(
            name="visible_done_ab_z",
            atoms=(ir.Atom("Done", (ir.FuncTerm("a", (ir.FuncTerm("b", (ir.ConstTerm("z"),)),)),)),),
            budget=request.proof_budget,
            description="A single reducible term already known to finish.",
        ),
    )
    targets_hidden = (
        ir.Goal(
            name="hidden_done_ab_nested",
            atoms=(ir.Atom("Done", (ir.FuncTerm("n", (ir.FuncTerm("a", (ir.FuncTerm("b", (ir.ConstTerm("z"),)),)),)),)),),
            budget=request.proof_budget,
            description="Nested reducible term that collapses to a normal form.",
        ),
        ir.Goal(
            name="hidden_done_ba",
            atoms=(ir.Atom("Done", (ir.FuncTerm("b", (ir.FuncTerm("a", (ir.ConstTerm("z"),)),)),)),),
            budget=request.proof_budget,
            description="Symmetric reducible term that lands in the same normal family.",
        ),
    )

    baseline = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms + visible_theorems,
        rewrites=rewrites,
        max_term_depth=request.max_term_depth,
    )
    with_bridge = build_closure(
        extend_signature_with_definitions(signature, hidden_bridge.definitions),
        facts=visible_facts,
        clauses=axioms + visible_theorems + hidden_bridge.lemmas,
        definitions=hidden_bridge.definitions,
        rewrites=rewrites,
        max_term_depth=request.max_term_depth,
    )
    proof_fixtures = {
        goal.name: {
            "baseline_cost": goal_cost(baseline.derivations, goal.atoms, rewrites),
            "gold_cost": goal_cost(with_bridge.derivations, goal.atoms, rewrites),
            "budget": goal.budget,
        }
        for goal in targets_hidden
    }

    world = ir.World(
        world_id=request.world_id or default_world_id(request.family, request.seed),
        family=request.family,
        signature=signature,
        rewrites=rewrites,
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


register_family("normal_form", generate_normal_form_world)
