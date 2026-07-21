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
from abw_core.generator.variation import schema_metadata, seeded_rng
from abw_core.scorer.weights import ANALOGY_WEIGHTS
from abw_core.typecheck import check_world


def generate_analogy_world(request: WorldGenerationRequest) -> ir.World:
    """Generate the shipped analogy world.

    The visible payload contains two parallel micro-theories. Their local proof
    patterns are intentionally symmetric so the interesting hidden object is the
    morphism that transports a theorem from one side to the other.
    """

    rng = seeded_rng(request.family, request.seed)
    if request.seed == 7:
        chain_length = 2
        base_count = 1
        distractor_count = 0
        theorem_count = 1
        left_predicates = ("LP", "LQ")
        right_predicates = ("RP", "RQ")
        left_functions = ("lf", "lg")
        right_functions = ("rf", "rg")
    else:
        chain_length = rng.randint(2, 4)
        base_count = rng.randint(1, 3)
        distractor_count = rng.randint(0, 3)
        theorem_count = rng.randint(1, min(2, chain_length))
        left_predicates = tuple(f"LP{i}" for i in range(chain_length))
        right_predicates = tuple(f"RP{i}" for i in range(chain_length))
        left_functions = tuple(f"lf{i}" for i in range(chain_length))
        right_functions = tuple(f"rf{i}" for i in range(chain_length))

    lx = ir.Variable("x", "L0")
    ry = ir.Variable("y", "R0")

    def apply_functions(term: ir.Term, names: tuple[str, ...]) -> ir.Term:
        for name in names:
            term = ir.FuncTerm(name, (term,))
        return term

    def cycle_theorem(
        *,
        side: str,
        variable: ir.Variable,
        predicates: tuple[str, ...],
        functions: tuple[str, ...],
        start: int,
    ) -> ir.HornClause:
        ordered_functions = tuple(functions[(start + offset) % chain_length] for offset in range(chain_length))
        return ir.HornClause(
            name=f"{side}_cycle_{start}",
            variables=(variable,),
            premises=(ir.Atom(predicates[start], (ir.VarTerm(variable),)),),
            conclusion=ir.Atom(predicates[start], (apply_functions(ir.VarTerm(variable), ordered_functions),)),
        )

    left_distractor_predicates = tuple(f"LD{i}" for i in range(distractor_count))
    right_distractor_predicates = tuple(f"RD{i}" for i in range(distractor_count))
    left_distractor_functions = tuple(f"ldf{i}" for i in range(distractor_count))
    right_distractor_functions = tuple(f"rdf{i}" for i in range(distractor_count))

    left_axioms = tuple(
        ir.HornClause(
            name=f"left_step_{index}",
            variables=(lx,),
            premises=(ir.Atom(left_predicates[index], (ir.VarTerm(lx),)),),
            conclusion=ir.Atom(
                left_predicates[(index + 1) % chain_length],
                (ir.FuncTerm(left_functions[index], (ir.VarTerm(lx),)),),
            ),
        )
        for index in range(chain_length)
    ) + tuple(
        ir.HornClause(
            name=f"left_decoy_{index}",
            variables=(lx,),
            premises=(ir.Atom(left_distractor_predicates[index], (ir.VarTerm(lx),)),),
            conclusion=ir.Atom(
                left_distractor_predicates[index],
                (ir.FuncTerm(left_distractor_functions[index], (ir.VarTerm(lx),)),),
            ),
        )
        for index in range(distractor_count)
    )
    right_axioms = tuple(
        ir.HornClause(
            name=f"right_step_{index}",
            variables=(ry,),
            premises=(ir.Atom(right_predicates[index], (ir.VarTerm(ry),)),),
            conclusion=ir.Atom(
                right_predicates[(index + 1) % chain_length],
                (ir.FuncTerm(right_functions[index], (ir.VarTerm(ry),)),),
            ),
        )
        for index in range(chain_length)
    ) + tuple(
        ir.HornClause(
            name=f"right_decoy_{index}",
            variables=(ry,),
            premises=(ir.Atom(right_distractor_predicates[index], (ir.VarTerm(ry),)),),
            conclusion=ir.Atom(
                right_distractor_predicates[index],
                (ir.FuncTerm(right_distractor_functions[index], (ir.VarTerm(ry),)),),
            ),
        )
        for index in range(distractor_count)
    )

    left_theory = ir.Theory(
        name="Left",
        document=ir.Document(
            sorts=(ir.Sort("L0"),),
            constants=tuple(ir.ConstantSymbol(f"l{i}", "L0") for i in range(base_count)),
            functions=tuple(ir.FunctionSymbol(name, ("L0",), "L0") for name in left_functions + left_distractor_functions),
            predicates=tuple(ir.PredicateSymbol(name, ("L0",)) for name in left_predicates + left_distractor_predicates),
            axioms=left_axioms,
            theorems=tuple(
                cycle_theorem(
                    side="left",
                    variable=lx,
                    predicates=left_predicates,
                    functions=left_functions,
                    start=index,
                )
                for index in range(theorem_count)
            ),
            facts=tuple(
                ir.Fact(f"left_seed_{index}", ir.Atom(left_predicates[0], (ir.ConstTerm(f"l{index}"),)))
                for index in range(base_count)
            )
            + tuple(
                ir.Fact(f"left_decoy_seed_{index}", ir.Atom(name, (ir.ConstTerm("l0"),)))
                for index, name in enumerate(left_distractor_predicates)
            ),
        ),
    )
    right_theory = ir.Theory(
        name="Right",
        document=ir.Document(
            sorts=(ir.Sort("R0"),),
            constants=tuple(ir.ConstantSymbol(f"r{i}", "R0") for i in range(base_count)),
            functions=tuple(ir.FunctionSymbol(name, ("R0",), "R0") for name in right_functions + right_distractor_functions),
            predicates=tuple(ir.PredicateSymbol(name, ("R0",)) for name in right_predicates + right_distractor_predicates),
            axioms=right_axioms,
            facts=tuple(
                ir.Fact(f"right_seed_{index}", ir.Atom(right_predicates[0], (ir.ConstTerm(f"r{index}"),)))
                for index in range(base_count)
            )
            + tuple(
                ir.Fact(f"right_decoy_seed_{index}", ir.Atom(name, (ir.ConstTerm("r0"),)))
                for index, name in enumerate(right_distractor_predicates)
            ),
        ),
    )

    mapping = {"L0": "R0"}
    mapping.update({f"l{index}": f"r{index}" for index in range(base_count)})
    mapping.update(dict(zip(left_functions, right_functions)))
    mapping.update(dict(zip(left_predicates, right_predicates)))
    mapping.update(dict(zip(left_distractor_functions, right_distractor_functions)))
    mapping.update(dict(zip(left_distractor_predicates, right_distractor_predicates)))
    hidden_bridge = ir.Bridge(
        mappings=(
            ir.SignatureMorphism(
                name="M",
                source_theory="Left",
                target_theory="Right",
                mapping=mapping,
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
            theorem.name: {
                "baseline_cost": None,
                "gold_cost": 1,
                "budget": 1,
            }
            for theorem in left_theory.document.theorems
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
            **schema_metadata(
                request.family,
                {
                    "chain_length": chain_length,
                    "base_count": base_count,
                    "distractor_mapping_count": distractor_count,
                    "transported_theorem_count": theorem_count,
                },
            ),
        },
    )
    check_world(world)
    return world


register_family("analogy", generate_analogy_world)
