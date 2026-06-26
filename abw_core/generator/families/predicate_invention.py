# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Canonical predicate-invention family for ABW bridge discovery.

This is the benchmark's most direct theory-formation task: the visible world
repeats a useful bundle of low-level predicates, and the hidden bridge is a new
predicate that names that bundle plus a lemma that shows the bundle propagates.

Why this family matters
-----------------------
It is the cleanest instance of the ABW thesis that a good abstraction is often
the right intermediate predicate rather than one more low-level proof.

Concrete example
----------------
The visible world exposes coordinated facts such as `R(x, y)`, `P0(x)`, and
`P1(y)` together with transition rules. The hidden bridge packages that pattern
into something like `Aligned(x, y)`.

Limitations
-----------
- The family is intentionally small and symbolic.
- Its bridge form is conjunctive predicate invention, not arbitrary definition
  synthesis.
"""

from __future__ import annotations

from abw_core import ir
from abw_core.generator.base import WorldGenerationRequest, register_family, scoring_config
from abw_core.scorer.weights import NON_ANALOGY_WEIGHTS
from abw_core.generator.distractors import predicate_invention_distractors
from abw_core.generator.obfuscation import default_world_id
from abw_core.generator.templates import iterate_term
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_predicate_invention_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose hidden bridge is a conjunctive invented predicate.

    The generated world is designed so that the repeated low-level conjunction
    really is useful on downstream goals. Optional distractors make the visible
    surface less toy-like without changing the intended hidden abstraction.
    """

    sorts = (ir.Sort("S0"), ir.Sort("S1"))
    constants = (ir.ConstantSymbol("c0", "S0"), ir.ConstantSymbol("d0", "S1"))
    functions = (ir.FunctionSymbol("f0", ("S0",), "S0"), ir.FunctionSymbol("f1", ("S1",), "S1"))
    predicates = (
        ir.PredicateSymbol("P0", ("S0",)),
        ir.PredicateSymbol("P1", ("S1",)),
        ir.PredicateSymbol("R", ("S0", "S1")),
    )

    distractor_predicates, distractor_axioms, distractor_facts, distractor_theorems = predicate_invention_distractors()
    signature = ir.Signature(
        sorts=sorts,
        constants=constants,
        functions=functions,
        predicates=predicates + (distractor_predicates if request.include_distractors else ()),
    )

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S1")

    axioms = (
        ir.HornClause(
            name="p0_step",
            variables=(x,),
            premises=(ir.Atom("P0", (ir.VarTerm(x),)),),
            conclusion=ir.Atom("P0", (ir.FuncTerm("f0", (ir.VarTerm(x),)),)),
        ),
        ir.HornClause(
            name="p1_step",
            variables=(y,),
            premises=(ir.Atom("P1", (ir.VarTerm(y),)),),
            conclusion=ir.Atom("P1", (ir.FuncTerm("f1", (ir.VarTerm(y),)),)),
        ),
        ir.HornClause(
            name="r_step",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom("R", (ir.FuncTerm("f0", (ir.VarTerm(x),)), ir.FuncTerm("f1", (ir.VarTerm(y),)))),
        ),
    ) + (distractor_axioms if request.include_distractors else ())

    visible_theorems = (
        ir.HornClause(
            name="visible_pair_step",
            variables=(x, y),
            premises=(
                ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
                ir.Atom("P0", (ir.VarTerm(x),)),
                ir.Atom("P1", (ir.VarTerm(y),)),
            ),
            conclusion=ir.Atom("R", (ir.FuncTerm("f0", (ir.VarTerm(x),)), ir.FuncTerm("f1", (ir.VarTerm(y),)))),
        ),
    ) + (distractor_theorems if request.include_distractors else ())

    visible_facts = (
        ir.Fact("base_p0", ir.Atom("P0", (ir.ConstTerm("c0"),))),
        ir.Fact("base_p1", ir.Atom("P1", (ir.ConstTerm("d0"),))),
        ir.Fact("base_r", ir.Atom("R", (ir.ConstTerm("c0"), ir.ConstTerm("d0")))),
    ) + (distractor_facts if request.include_distractors else ())

    aligned_definition = ir.Definition(
        name="Aligned",
        parameters=(x, y),
        body=(
            ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
            ir.Atom("P0", (ir.VarTerm(x),)),
            ir.Atom("P1", (ir.VarTerm(y),)),
        ),
    )
    aligned_lemma = ir.HornClause(
        name="aligned_step",
        variables=(x, y),
        premises=(ir.Atom("Aligned", (ir.VarTerm(x), ir.VarTerm(y))),),
        conclusion=ir.Atom("Aligned", (ir.FuncTerm("f0", (ir.VarTerm(x),)), ir.FuncTerm("f1", (ir.VarTerm(y),)))),
    )
    hidden_bridge = ir.Bridge(definitions=(aligned_definition,), lemmas=(aligned_lemma,))

    def make_goal(name: str, steps: int, budget: int) -> ir.Goal:
        """Build one synchronized low-level target parameterized by step depth.

        The family reuses the same structural target pattern at several depths
        so the benchmark can ask whether the invented predicate keeps helping as
        the visible transition chain gets longer.
        """

        left = iterate_term("f0", ir.ConstTerm("c0"), steps)
        right = iterate_term("f1", ir.ConstTerm("d0"), steps)
        return ir.Goal(
            name=name,
            atoms=(
                ir.Atom("R", (left, right)),
                ir.Atom("P0", (left,)),
                ir.Atom("P1", (right,)),
            ),
            budget=budget,
            description=f"Low-level synchronized state after {steps} transition steps.",
        )

    targets_visible = (make_goal("visible_step_1", 1, request.proof_budget),)
    targets_hidden = tuple(
        make_goal(f"hidden_step_{steps}", steps, request.proof_budget) for steps in request.hidden_steps
    )

    baseline = build_closure(
        signature,
        facts=visible_facts,
        clauses=axioms + visible_theorems,
        definitions=(),
        max_term_depth=request.max_term_depth,
    )
    bridge_signature = extend_signature_with_definitions(signature, hidden_bridge.definitions)
    with_bridge = build_closure(
        bridge_signature,
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
            "include_distractors": request.include_distractors,
        },
    )
    check_world(world)
    return world


register_family("predicate_invention", generate_predicate_invention_world)
