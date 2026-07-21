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
from abw_core.generator.variation import schema_metadata, seeded_rng
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_normal_form_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one rewrite-heavy world whose bridge captures normal forms.

    The visible theory already proves some `Done` facts after rewriting, but
    the hidden bridge is the compact abstraction that says "this term is already
    in normal form," which then supports downstream reasoning more directly.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        constructor_names = ("a", "b")
        constant_names = ("z",)
        done_names = ("Done",)
        rewrite_pairs = (("a", "b"), ("b", "a"))
        nested_normalizers = 1
    else:
        constructor_names = ("a", "b", "c", "d")[: rng.randint(2, 4)]
        constant_names = tuple(f"z{i}" for i in range(rng.randint(1, 3)))
        done_names = tuple(f"Done{i}" for i in range(rng.randint(1, 2)))
        offset = rng.randint(1, len(constructor_names) - 1)
        pair_count = rng.randint(1, len(constructor_names))
        rewrite_pairs = tuple(
            (
                constructor_names[index],
                constructor_names[(index + offset) % len(constructor_names)],
            )
            for index in range(pair_count)
        )
        nested_normalizers = rng.randint(1, 2)

    sorts = (ir.Sort("T"),)
    constants = tuple(ir.ConstantSymbol(name, "T") for name in constant_names)
    functions = tuple(ir.FunctionSymbol(name, ("T",), "T") for name in constructor_names + ("n",))
    ready_names = tuple(name.replace("Done", "Ready") for name in done_names)
    marker_names = tuple(name.replace("Done", "Marker") for name in done_names)
    predicates = tuple(
        ir.PredicateSymbol(name, ("T",)) for name in done_names + ready_names + marker_names
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "T")

    wildcard = ir.VarTerm(ir.Variable("x", "_"))
    rewrites = tuple(
        ir.RewriteRule(
            name=f"r{index + 1}",
            lhs=ir.FuncTerm(outer, (ir.FuncTerm(inner, (wildcard,)),)),
            rhs=ir.FuncTerm("n", (wildcard,)),
        )
        for index, (outer, inner) in enumerate(rewrite_pairs)
    ) + (
        ir.RewriteRule(
            name="n_idempotent",
            lhs=ir.FuncTerm("n", (ir.FuncTerm("n", (wildcard,)),)),
            rhs=ir.FuncTerm("n", (wildcard,)),
        ),
    )
    axioms = tuple(
        ir.HornClause(
            name=f"{marker_name.lower()}_to_{ready_name.lower()}",
            variables=(x,),
            premises=(ir.Atom(marker_name, (ir.VarTerm(x),)),),
            conclusion=ir.Atom(ready_name, (ir.FuncTerm("n", (ir.VarTerm(x),)),)),
        )
        for marker_name, ready_name in zip(marker_names, ready_names)
    ) + tuple(
        ir.HornClause(
            name=f"{ready_name.lower()}_to_{done_name.lower()}",
            variables=(x,),
            premises=(ir.Atom(ready_name, (ir.VarTerm(x),)),),
            conclusion=ir.Atom(done_name, (ir.VarTerm(x),)),
        )
        for ready_name, done_name in zip(ready_names, done_names)
    )
    visible_outer, visible_inner = rewrite_pairs[0]
    visible_theorems = ()
    visible_facts = tuple(
        ir.Fact(
            f"base_{marker_name.lower()}_{index}",
            ir.Atom(marker_name, (ir.ConstTerm(constant),)),
        )
        for index, constant in enumerate(constant_names)
        for marker_name in marker_names
    )

    normal_definition = ir.Definition(
        name="Normal",
        parameters=(x,),
        body=(ir.Atom("=", (ir.FuncTerm("n", (ir.VarTerm(x),)), ir.VarTerm(x))),),
    )
    hidden_bridge = ir.Bridge(
        definitions=(normal_definition,),
        lemmas=tuple(
            ir.HornClause(
                name=f"{done_name.lower()}_normal_shortcut",
                variables=(x,),
                premises=(ir.Atom(marker_name, (ir.VarTerm(x),)),),
                conclusion=ir.Atom(done_name, (ir.FuncTerm("n", (ir.VarTerm(x),)),)),
            )
            for done_name, marker_name in zip(done_names, marker_names)
        ),
    )

    targets_visible = (
        ir.Goal(
            name="visible_done_ab_z",
            atoms=(
                ir.Atom(
                    done_names[0],
                    (
                        ir.FuncTerm(
                            visible_outer,
                            (ir.FuncTerm(visible_inner, (ir.ConstTerm(constant_names[0]),)),),
                        ),
                    ),
                ),
            ),
            budget=request.proof_budget,
            description="A single reducible term already known to finish.",
        ),
    )
    targets_hidden_list: list[ir.Goal] = []
    for pair_index, (outer, inner) in enumerate(rewrite_pairs):
        constant = constant_names[pair_index % len(constant_names)]
        term: ir.Term = ir.FuncTerm(outer, (ir.FuncTerm(inner, (ir.ConstTerm(constant),)),))
        for _ in range(nested_normalizers - 1):
            term = ir.FuncTerm("n", (term,))
        targets_hidden_list.append(
            ir.Goal(
                name=f"hidden_done_pair_{pair_index}",
                atoms=(ir.Atom(done_names[pair_index % len(done_names)], (term,)),),
                budget=request.proof_budget,
                description="Nested reducible term that collapses to a normal form.",
            )
        )
    targets_hidden = tuple(targets_hidden_list)

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
            **schema_metadata(
                request.family,
                {
                    "constructor_count": len(constructor_names),
                    "constant_count": len(constant_names),
                    "done_predicate_count": len(done_names),
                    "rewrite_pairs": [list(pair) for pair in rewrite_pairs],
                    "nested_normalizers": nested_normalizers,
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("normal_form", generate_normal_form_world)
