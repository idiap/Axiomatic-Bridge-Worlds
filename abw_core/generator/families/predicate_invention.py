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
from abw_core.generator.variation import schema_metadata, seeded_rng
from abw_core.prover import build_closure, goal_cost
from abw_core.typecheck import check_world, extend_signature_with_definitions


def generate_predicate_invention_world(request: WorldGenerationRequest) -> ir.World:
    """Generate one world whose hidden bridge is a conjunctive invented predicate.

    The generated world is designed so that the repeated low-level conjunction
    really is useful on downstream goals. Optional distractors make the visible
    surface less toy-like without changing the intended hidden abstraction.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        left_predicates = ("P0",)
        right_predicates = ("P1",)
        pair_count = 1
        noise_count = 2 if request.include_distractors else 0
        goal_depths = tuple(request.hidden_steps)
        legacy_distractors = request.include_distractors
    else:
        left_predicates = tuple(f"P{i}" for i in range(rng.randint(1, 3)))
        right_predicates = tuple(
            f"P{i}" for i in range(len(left_predicates), len(left_predicates) + rng.randint(1, 3))
        )
        pair_count = rng.randint(1, 3)
        noise_count = rng.randint(0, 4) if request.include_distractors else 0
        available_depths = list(range(2, max(3, request.max_term_depth) + 1))
        goal_count = min(len(available_depths), rng.randint(2, 3))
        goal_depths = tuple(sorted(rng.sample(available_depths, goal_count)))
        legacy_distractors = False

    sorts = (ir.Sort("S0"), ir.Sort("S1"))
    constants = tuple(ir.ConstantSymbol(f"c{i}", "S0") for i in range(pair_count)) + tuple(
        ir.ConstantSymbol(f"d{i}", "S1") for i in range(pair_count)
    )
    functions = (ir.FunctionSymbol("f0", ("S0",), "S0"), ir.FunctionSymbol("f1", ("S1",), "S1"))
    predicates = tuple(ir.PredicateSymbol(name, ("S0",)) for name in left_predicates) + tuple(
        ir.PredicateSymbol(name, ("S1",)) for name in right_predicates
    ) + (ir.PredicateSymbol("R", ("S0", "S1")),)

    if legacy_distractors:
        distractor_predicates, distractor_axioms, distractor_facts, distractor_theorems = (
            predicate_invention_distractors()
        )
    else:
        distractor_predicates = tuple(
            ir.PredicateSymbol(f"N{i}", ("S0" if i % 2 == 0 else "S1",)) for i in range(noise_count)
        )
        distractor_axioms = tuple(
            ir.HornClause(
                name=f"noise_{i}_step",
                variables=(ir.Variable("u", "S0" if i % 2 == 0 else "S1"),),
                premises=(
                    ir.Atom(
                        f"N{i}",
                        (ir.VarTerm(ir.Variable("u", "S0" if i % 2 == 0 else "S1")),),
                    ),
                ),
                conclusion=ir.Atom(
                    f"N{i}",
                    (
                        ir.FuncTerm(
                            "f0" if i % 2 == 0 else "f1",
                            (ir.VarTerm(ir.Variable("u", "S0" if i % 2 == 0 else "S1")),),
                        ),
                    ),
                ),
            )
            for i in range(noise_count)
        )
        distractor_facts = tuple(
            ir.Fact(
                f"noise_{i}_base",
                ir.Atom(f"N{i}", (ir.ConstTerm("c0" if i % 2 == 0 else "d0"),)),
            )
            for i in range(noise_count)
        )
        distractor_theorems = ()
    signature = ir.Signature(
        sorts=sorts,
        constants=constants,
        functions=functions,
        predicates=predicates + (distractor_predicates if request.include_distractors else ()),
    )

    x = ir.Variable("x", "S0")
    y = ir.Variable("y", "S1")

    axioms = tuple(
        ir.HornClause(
            name=f"{name.lower()}_step",
            variables=(x,),
            premises=(ir.Atom(name, (ir.VarTerm(x),)),),
            conclusion=ir.Atom(name, (ir.FuncTerm("f0", (ir.VarTerm(x),)),)),
        )
        for name in left_predicates
    ) + tuple(
        ir.HornClause(
            name=f"{name.lower()}_step",
            variables=(y,),
            premises=(ir.Atom(name, (ir.VarTerm(y),)),),
            conclusion=ir.Atom(name, (ir.FuncTerm("f1", (ir.VarTerm(y),)),)),
        )
        for name in right_predicates
    ) + (
        ir.HornClause(
            name="r_step",
            variables=(x, y),
            premises=(ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),),
            conclusion=ir.Atom("R", (ir.FuncTerm("f0", (ir.VarTerm(x),)), ir.FuncTerm("f1", (ir.VarTerm(y),)))),
        ),
    ) + (distractor_axioms if request.include_distractors else ())

    bridge_atoms = (
        ir.Atom("R", (ir.VarTerm(x), ir.VarTerm(y))),
    ) + tuple(ir.Atom(name, (ir.VarTerm(x),)) for name in left_predicates) + tuple(
        ir.Atom(name, (ir.VarTerm(y),)) for name in right_predicates
    )
    visible_theorems = (
        ir.HornClause(
            name="visible_pair_step",
            variables=(x, y),
            premises=bridge_atoms,
            conclusion=ir.Atom("R", (ir.FuncTerm("f0", (ir.VarTerm(x),)), ir.FuncTerm("f1", (ir.VarTerm(y),)))),
        ),
    ) + (distractor_theorems if request.include_distractors else ())

    visible_facts = tuple(
        ir.Fact(f"base_{name.lower()}_{index}", ir.Atom(name, (ir.ConstTerm(f"c{index}"),)))
        for index in range(pair_count)
        for name in left_predicates
    ) + tuple(
        ir.Fact(f"base_{name.lower()}_{index}", ir.Atom(name, (ir.ConstTerm(f"d{index}"),)))
        for index in range(pair_count)
        for name in right_predicates
    ) + tuple(
        ir.Fact(
            f"base_r_{index}",
            ir.Atom("R", (ir.ConstTerm(f"c{index}"), ir.ConstTerm(f"d{index}"))),
        )
        for index in range(pair_count)
    ) + (distractor_facts if request.include_distractors else ())

    aligned_definition = ir.Definition(
        name="Aligned",
        parameters=(x, y),
        body=bridge_atoms,
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
            atoms=(ir.Atom("R", (left, right)),)
            + tuple(ir.Atom(name, (left,)) for name in left_predicates)
            + tuple(ir.Atom(name, (right,)) for name in right_predicates),
            budget=budget,
            description=f"Low-level synchronized state after {steps} transition steps.",
        )

    targets_visible = (make_goal("visible_step_1", 1, request.proof_budget),)
    targets_hidden = tuple(make_goal(f"hidden_step_{steps}", steps, request.proof_budget) for steps in goal_depths)

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
            "hidden_steps": list(goal_depths),
            "include_distractors": request.include_distractors,
            **schema_metadata(
                request.family,
                {
                    "left_predicate_count": len(left_predicates),
                    "right_predicate_count": len(right_predicates),
                    "base_pair_count": pair_count,
                    "noise_predicate_count": noise_count,
                    "goal_depths": list(goal_depths),
                    "legacy_distractors": legacy_distractors,
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("predicate_invention", generate_predicate_invention_world)
