# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Analogy-family generation built around hidden theory morphisms.

This family packages two tiny visible theories that share the same structural
shape but use different symbol vocabularies. The hidden bridge is not a new
predicate or lemma inside one theory; it is a signature morphism that explains
how proofs transport from the left theory to the right one. That makes the
family the ABW runtime's first "analogy as structure-preserving translation"
task rather than another within-theory invention problem.

Limitations
-----------
- The analogy is intentionally exact and local, not fuzzy or semantic in the
  broad cognitive-science sense.
- The hidden bridge is a typed morphism, so the task lives inside explicit
  structural alignment rather than free-form metaphor.
"""

from __future__ import annotations

from abw_core import ir
from abw_core.generator.base import WorldGenerationRequest, register_family, scoring_config
from abw_core.generator.obfuscation import default_world_id
from abw_core.scorer.weights import ANALOGY_WEIGHTS
from abw_core.typecheck import check_world


def generate_analogy_world(request: WorldGenerationRequest) -> ir.World:
    """Generate the shipped analogy world.

    The visible payload contains two parallel micro-theories. Their local proof
    patterns are intentionally symmetric so the interesting hidden object is the
    morphism that transports a theorem from one side to the other.
    """

    lx = ir.Variable("x", "L0")
    ry = ir.Variable("y", "R0")

    # The left theory serves as the source of the transported theorem.
    left_theory = ir.Theory(
        name="Left",
        document=ir.Document(
            sorts=(ir.Sort("L0"),),
            constants=(ir.ConstantSymbol("l0", "L0"),),
            functions=(
                ir.FunctionSymbol("lf", ("L0",), "L0"),
                ir.FunctionSymbol("lg", ("L0",), "L0"),
            ),
            predicates=(
                ir.PredicateSymbol("LP", ("L0",)),
                ir.PredicateSymbol("LQ", ("L0",)),
            ),
            axioms=(
                ir.HornClause(
                    name="l1",
                    variables=(lx,),
                    premises=(ir.Atom("LP", (ir.VarTerm(lx),)),),
                    conclusion=ir.Atom("LQ", (ir.FuncTerm("lf", (ir.VarTerm(lx),)),)),
                ),
                ir.HornClause(
                    name="l2",
                    variables=(lx,),
                    premises=(ir.Atom("LQ", (ir.VarTerm(lx),)),),
                    conclusion=ir.Atom("LP", (ir.FuncTerm("lg", (ir.VarTerm(lx),)),)),
                ),
            ),
            theorems=(
                ir.HornClause(
                    name="left_two_step",
                    variables=(lx,),
                    premises=(ir.Atom("LP", (ir.VarTerm(lx),)),),
                    conclusion=ir.Atom("LP", (ir.FuncTerm("lg", (ir.FuncTerm("lf", (ir.VarTerm(lx),)),)),)),
                ),
            ),
            facts=(ir.Fact("left_seed", ir.Atom("LP", (ir.ConstTerm("l0"),))),),
        ),
    )

    # The right theory mirrors the same proof skeleton under a renamed
    # vocabulary, so the benchmark pressure lands on discovering the mapping.
    right_theory = ir.Theory(
        name="Right",
        document=ir.Document(
            sorts=(ir.Sort("R0"),),
            constants=(ir.ConstantSymbol("r0", "R0"),),
            functions=(
                ir.FunctionSymbol("rf", ("R0",), "R0"),
                ir.FunctionSymbol("rg", ("R0",), "R0"),
            ),
            predicates=(
                ir.PredicateSymbol("RP", ("R0",)),
                ir.PredicateSymbol("RQ", ("R0",)),
            ),
            axioms=(
                ir.HornClause(
                    name="r1",
                    variables=(ry,),
                    premises=(ir.Atom("RP", (ir.VarTerm(ry),)),),
                    conclusion=ir.Atom("RQ", (ir.FuncTerm("rf", (ir.VarTerm(ry),)),)),
                ),
                ir.HornClause(
                    name="r2",
                    variables=(ry,),
                    premises=(ir.Atom("RQ", (ir.VarTerm(ry),)),),
                    conclusion=ir.Atom("RP", (ir.FuncTerm("rg", (ir.VarTerm(ry),)),)),
                ),
            ),
            facts=(ir.Fact("right_seed", ir.Atom("RP", (ir.ConstTerm("r0"),))),),
        ),
    )

    # The hidden bridge is a structure-preserving dictionary between the two
    # theories. Evaluation can then ask whether the candidate recovered that
    # transport story rather than only another local theorem.
    hidden_bridge = ir.Bridge(
        mappings=(
            ir.SignatureMorphism(
                name="M",
                source_theory="Left",
                target_theory="Right",
                mapping={
                    "L0": "R0",
                    "l0": "r0",
                    "lf": "rf",
                    "lg": "rg",
                    "LP": "RP",
                    "LQ": "RQ",
                },
            ),
        )
    )

    # The proof fixture names the intended downstream use of the mapping:
    # transporting the left-side two-step theorem into the right theory.
    world = ir.World(
        world_id=request.world_id or default_world_id(request.family, request.seed),
        family=request.family,
        signature=ir.Signature(sorts=()),
        axioms=(),
        visible_theorems=(),
        visible_facts=(),
        targets_visible=(),
        targets_hidden=(),
        hidden_bridge=hidden_bridge,
        theories=(left_theory, right_theory),
        proof_fixtures={
            "transport_left_two_step": {
                "baseline_cost": None,
                "gold_cost": 1,
                "budget": 1,
            }
        },
        scoring_config=scoring_config(
            request,
            weights=ANALOGY_WEIGHTS,
            include_proof_budget=False,
        ),
        metadata={
            "seed": request.seed,
            "max_term_depth": request.max_term_depth,
            "dsl_version": "abw-dsl-v2",
        },
    )
    check_world(world)
    return world


register_family("analogy", generate_analogy_world)
