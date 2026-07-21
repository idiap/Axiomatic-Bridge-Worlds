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
from abw_core.generator.variation import schema_metadata, seeded_rng
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world


def generate_lemma_invention_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose hidden bridge is a reusable shortcut lemma.

    The world exposes a visible chain of implications and a couple of partial
    shortcut theorems, but the most valuable missing object is the composed
    theorem that collapses the full chain.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        chain_length = 3
        base_count = 1
        shortcut_profile = 3
        noise_count = 0
        include_shifted_goal = True
    else:
        chain_length = rng.randint(3, 4)
        base_count = rng.randint(1, 3)
        shortcut_profile = rng.randint(0, 3)
        noise_count = rng.randint(0, 3)
        include_shifted_goal = bool(rng.getrandbits(1)) and request.max_term_depth > chain_length

    predicate_names = tuple(chr(ord("A") + index) for index in range(chain_length + 1))
    function_names = ("f", "g", "h", "j")[:chain_length]
    sorts = (ir.Sort("S0"),)
    constants = tuple(ir.ConstantSymbol(f"c{i}", "S0") for i in range(base_count))
    functions = tuple(ir.FunctionSymbol(name, ("S0",), "S0") for name in function_names)
    predicates = tuple(ir.PredicateSymbol(name, ("S0",)) for name in predicate_names) + tuple(
        ir.PredicateSymbol(f"Noise{i}", ("S0",)) for i in range(noise_count)
    )
    signature = ir.Signature(sorts=sorts, constants=constants, functions=functions, predicates=predicates)

    x = ir.Variable("x", "S0")

    def apply_functions(term: ir.Term, names: tuple[str, ...]) -> ir.Term:
        for name in names:
            term = ir.FuncTerm(name, (term,))
        return term

    axioms = tuple(
        ir.HornClause(
            name=f"{predicate_names[index].lower()}_to_{predicate_names[index + 1].lower()}",
            variables=(x,),
            premises=(ir.Atom(predicate_names[index], (ir.VarTerm(x),)),),
            conclusion=ir.Atom(
                predicate_names[index + 1],
                (ir.FuncTerm(function_names[index], (ir.VarTerm(x),)),),
            ),
        )
        for index in range(chain_length)
    ) + tuple(
        ir.HornClause(
            name=f"noise_{index}_step",
            variables=(x,),
            premises=(ir.Atom(f"Noise{index}", (ir.VarTerm(x),)),),
            conclusion=ir.Atom(f"Noise{index}", (ir.FuncTerm("f", (ir.VarTerm(x),)),)),
        )
        for index in range(noise_count)
    )

    visible_theorem_list: list[ir.HornClause] = []
    if shortcut_profile & 1:
        visible_theorem_list.append(
            ir.HornClause(
                name="prefix_shortcut",
                variables=(x,),
                premises=(ir.Atom(predicate_names[0], (ir.VarTerm(x),)),),
                conclusion=ir.Atom(
                    predicate_names[2],
                    (apply_functions(ir.VarTerm(x), function_names[:2]),),
                ),
            )
        )
    if shortcut_profile & 2:
        visible_theorem_list.append(
            ir.HornClause(
                name="suffix_shortcut",
                variables=(x,),
                premises=(ir.Atom(predicate_names[-3], (ir.VarTerm(x),)),),
                conclusion=ir.Atom(
                    predicate_names[-1],
                    (apply_functions(ir.VarTerm(x), function_names[-2:]),),
                ),
            )
        )
    visible_theorems = tuple(visible_theorem_list)
    visible_facts = tuple(
        ir.Fact(f"base_{index}", ir.Atom(predicate_names[0], (ir.ConstTerm(f"c{index}"),)))
        for index in range(base_count)
    ) + tuple(
        ir.Fact(f"noise_{index}", ir.Atom(f"Noise{index}", (ir.ConstTerm("c0"),)))
        for index in range(noise_count)
    )
    if include_shifted_goal:
        visible_facts += (
            ir.Fact(
                "base_shifted",
                ir.Atom(predicate_names[0], (ir.FuncTerm(function_names[0], (ir.ConstTerm("c0"),)),)),
            ),
        )

    hidden_bridge = ir.Bridge(
        lemmas=(
            ir.HornClause(
                name=f"chain{chain_length}",
                variables=(x,),
                premises=(ir.Atom(predicate_names[0], (ir.VarTerm(x),)),),
                conclusion=ir.Atom(predicate_names[-1], (apply_functions(ir.VarTerm(x), function_names),)),
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
                    predicate_names[-1],
                    (apply_functions(seed_term, function_names),),
                ),
            ),
            budget=budget,
            description="Shortcut theorem for the composed f/g/h propagation chain.",
        )

    targets_visible = (make_goal("visible_chain", ir.ConstTerm("c0"), request.proof_budget + 1),)
    targets_hidden = tuple(
        make_goal(f"hidden_chain_{index}", ir.ConstTerm(f"c{index}"), request.proof_budget)
        for index in range(base_count)
    )
    if include_shifted_goal:
        targets_hidden += (
            make_goal(
                "hidden_chain_shifted",
                iterate_term(function_names[0], ir.ConstTerm("c0"), 1),
                request.proof_budget,
            ),
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
            **schema_metadata(
                request.family,
                {
                    "chain_length": chain_length,
                    "base_count": base_count,
                    "shortcut_profile": shortcut_profile,
                    "noise_count": noise_count,
                    "include_shifted_goal": include_shifted_goal,
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("lemma_invention", generate_lemma_invention_world)
