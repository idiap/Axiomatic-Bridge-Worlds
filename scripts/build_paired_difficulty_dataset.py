# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Build a paired difficulty-shape ABW dataset.

The paired design keeps the generated base world and hidden bridge fixed, then
applies one difficulty shape at a time. The shapes are ordered by expected
intervention severity, but they are not cumulative interventions: C1--C5 are
generated from the same source world with only the requested feature bundle,
while C6 combines high-intensity controls as a stress-boundary case.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from abw_core import ir
from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.generator.templates import iterate_term
from abw_core.packager import load_world, package_world, validate_package
from scripts.generate_perturbed_dataset import _alpha_rename_world


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "datasets" / "paper_core_paired_difficulty_shapes_independent"
DEFAULT_MANIFEST = "paired_difficulty_manifest.json"
SPLIT = "test_public"
PAPER_FAMILIES = (
    "predicate_invention",
    "lemma_invention",
    "invariant",
    "analogy",
    "normal_form",
    "quotient",
    "multi_step",
)
FAMILY_PRIOR_STRATA = {
    "analogy": "high_prior_performance",
    "invariant": "high_prior_performance",
    "lemma_invention": "high_prior_performance",
    "predicate_invention": "hard_prior_performance",
    "multi_step": "hard_prior_performance",
    "normal_form": "hard_prior_performance",
    "quotient": "hard_prior_performance",
}
DEFAULT_CASES = (
    "predicate:predicate_invention:abw_test_public_0070",
    "lemma:lemma_invention:abw_test_public_0099",
    "invariant:invariant:abw_test_public_0010",
    "analogy:analogy:abw_test_public_0002",
    "normal:normal_form:abw_test_public_0005",
    "quotient:quotient:abw_test_public_0102",
    "multi_step:multi_step:abw_test_public_0111",
)


@dataclass(frozen=True)
class CaseSpec:
    """One source-world case study selected from completed Stage 2 runs."""

    label: str
    family: str
    world_id: str


@dataclass(frozen=True)
class DifficultyLevel:
    """One public difficulty-shape intervention.

    C1--C5 are independently applied feature bundles sorted by expected
    intervention severity. C6 is the deliberate stress-boundary bundle.
    """

    index: int
    level_id: str
    label: str
    expected_complexity_rank: int
    public_decoy_stage: int
    deep_bridge_step: int | None
    abstraction_chain_proxy: bool
    alpha_rename_and_reorder: bool
    requested_controls: tuple[str, ...]
    feature_pattern: str
    scientific_rationale: str
    description: str


DIFFICULTY_LEVELS = (
    DifficultyLevel(
        index=0,
        level_id="c0_clean",
        label="Recoverable base",
        expected_complexity_rank=0,
        public_decoy_stage=0,
        deep_bridge_step=None,
        abstraction_chain_proxy=False,
        alpha_rename_and_reorder=False,
        requested_controls=(),
        feature_pattern="No added difficulty shape; source public world.",
        scientific_rationale=(
            "Baseline control for the same source world and hidden bridge; all shape drops are paired "
            "against this item."
        ),
        description="The source ABW world with no added paired-difficulty shape controls.",
    ),
    DifficultyLevel(
        index=1,
        level_id="c1_deep_bridge",
        label="Deep bridge",
        expected_complexity_rank=1,
        public_decoy_stage=0,
        deep_bridge_step=5,
        abstraction_chain_proxy=False,
        alpha_rename_and_reorder=False,
        requested_controls=("deep_bridge",),
        feature_pattern="Minimal hidden-side intervention: higher definition depth and larger proof gap.",
        scientific_rationale=(
            "A deeper hidden target raises proof-distance pressure while leaving the visible vocabulary "
            "largely unchanged, making this the least invasive non-base shape."
        ),
        description="Adds a deeper hidden target, increasing definition-depth pressure and proof gap.",
    ),
    DifficultyLevel(
        index=2,
        level_id="c2_wide_typed_bridge",
        label="Wide typed bridge",
        expected_complexity_rank=2,
        public_decoy_stage=1,
        deep_bridge_step=None,
        abstraction_chain_proxy=False,
        alpha_rename_and_reorder=False,
        requested_controls=("wide_typed_bridge",),
        feature_pattern="Typed-width intervention: auxiliary sort, symbols, and bound-variable surface.",
        scientific_rationale=(
            "Adding an auxiliary sort, constants, function, and predicates increases the typed search "
            "space without adding misleading rules or surface obfuscation."
        ),
        description=(
            "Adds an auxiliary sort, constants, function, and predicates to widen the typed public surface."
        ),
    ),
    DifficultyLevel(
        index=3,
        level_id="c3_multi_island_bridge",
        label="Multi-island bridge",
        expected_complexity_rank=3,
        public_decoy_stage=2,
        deep_bridge_step=None,
        abstraction_chain_proxy=False,
        alpha_rename_and_reorder=False,
        requested_controls=("wide_typed_bridge", "multi_island_bridge", "evidence_sparsity"),
        feature_pattern="Structural-sparsity intervention: typed auxiliary island with sparse public evidence.",
        scientific_rationale=(
            "A weakly connected auxiliary island adds modular search pressure after simple typed width, "
            "but before explicit wrong-attractor rules are introduced."
        ),
        description=(
            "Adds a weak auxiliary island with sparse public facts, matching the "
            "multi-island shape at the public evidence level."
        ),
    ),
    DifficultyLevel(
        index=4,
        level_id="c4_distractor_field",
        label="Distractor field",
        expected_complexity_rank=4,
        public_decoy_stage=3,
        deep_bridge_step=None,
        abstraction_chain_proxy=False,
        alpha_rename_and_reorder=False,
        requested_controls=("wide_typed_bridge", "multi_island_bridge", "distractor_field"),
        feature_pattern="Wrong-attractor intervention: auxiliary island plus Horn rules and theorem-shaped decoys.",
        scientific_rationale=(
            "Decoy closure rules introduce candidate abstractions that are locally coherent but should not "
            "solve the hidden goals, directly testing wrong-attractor pressure without surface obfuscation."
        ),
        description=(
            "Adds public Horn rules and theorem-shaped decoys, creating plausible wrong "
            "abstractions over the auxiliary island."
        ),
    ),
    DifficultyLevel(
        index=5,
        level_id="c5_abstraction_chain",
        label="Abstraction chain",
        expected_complexity_rank=5,
        public_decoy_stage=1,
        deep_bridge_step=None,
        abstraction_chain_proxy=True,
        alpha_rename_and_reorder=False,
        requested_controls=("wide_typed_bridge", "abstraction_chain"),
        feature_pattern="Compositional intervention: typed auxiliary surface with staged proxy concepts.",
        scientific_rationale=(
            "A chain of public proxy concepts increases sequential composition pressure, separating "
            "multi-step abstraction from flat typed width and from explicit decoys."
        ),
        description=(
            "Adds a staged auxiliary abstraction-chain proxy. The multi-step hard source already "
            "contains the real hidden abstraction-chain family pressure."
        ),
    ),
    DifficultyLevel(
        index=6,
        level_id="c6_stress_boundary",
        label="Stress boundary",
        expected_complexity_rank=6,
        public_decoy_stage=3,
        deep_bridge_step=5,
        abstraction_chain_proxy=True,
        alpha_rename_and_reorder=True,
        requested_controls=(
            "deep_bridge",
            "wide_typed_bridge",
            "multi_island_bridge",
            "distractor_field",
            "abstraction_chain",
            "alpha_renaming",
            "axiom_order_shuffle",
            "public_order_reversal",
            "stress_boundary",
        ),
        feature_pattern=(
            "Critical stress bundle: depth, width, sparse islands, decoys, chain pressure, and obfuscation."
        ),
        scientific_rationale=(
            "The stress-boundary shape intentionally combines depth, width, islands, decoys, chain pressure, "
            "and surface obfuscation to test when a recoverable bridge becomes underdetermined."
        ),
        description=(
            "Combines high-intensity Appendix A features with surface obfuscation, moving the "
            "instance toward the stress-boundary regime."
        ),
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decoy_names(family: str, base_index: int) -> dict[str, str]:
    prefix = f"ctrl_{family}_{base_index:02d}"
    return {
        "sort": f"AuxSort_{prefix}",
        "constant_a": f"aux_a_{prefix}",
        "constant_b": f"aux_b_{prefix}",
        "function": f"aux_step_{prefix}",
        "predicate_flag": f"AuxFlag_{prefix}",
        "predicate_rel": f"AuxRel_{prefix}",
        "variable_x": f"aux_x_{prefix}",
        "variable_y": f"aux_y_{prefix}",
    }


def _add_public_decoys(world: ir.World, *, family: str, base_index: int, stage: int) -> ir.World:
    """Return a copy of ``world`` with the requested public-decoy intensity."""

    if stage <= 0:
        return world

    names = _decoy_names(family, base_index)
    aux_sort = names["sort"]
    constant_a = ir.ConstTerm(names["constant_a"])
    constant_b = ir.ConstTerm(names["constant_b"])
    x = ir.Variable(names["variable_x"], aux_sort)
    y = ir.Variable(names["variable_y"], aux_sort)
    x_term = ir.VarTerm(x)
    y_term = ir.VarTerm(y)

    signature = ir.Signature(
        sorts=world.signature.sorts + (ir.Sort(aux_sort),),
        constants=world.signature.constants
        + (
            ir.ConstantSymbol(names["constant_a"], aux_sort),
            ir.ConstantSymbol(names["constant_b"], aux_sort),
        ),
        functions=world.signature.functions
        + (ir.FunctionSymbol(names["function"], (aux_sort,), aux_sort),),
        predicates=world.signature.predicates
        + (
            ir.PredicateSymbol(names["predicate_flag"], (aux_sort,)),
            ir.PredicateSymbol(names["predicate_rel"], (aux_sort, aux_sort)),
        ),
    )

    visible_facts = world.visible_facts
    if stage >= 2:
        visible_facts = visible_facts + (
            ir.Fact(
                f"decoy_flag_fact_{base_index:02d}",
                ir.Atom(names["predicate_flag"], (constant_a,)),
            ),
            ir.Fact(
                f"decoy_rel_fact_{base_index:02d}",
                ir.Atom(names["predicate_rel"], (constant_a, constant_b)),
            ),
        )

    axioms = world.axioms
    visible_theorems = world.visible_theorems
    if stage >= 3:
        next_x = ir.FuncTerm(names["function"], (x_term,))
        axioms = axioms + (
            ir.HornClause(
                name=f"decoy_flag_closure_{base_index:02d}",
                variables=(x,),
                premises=(ir.Atom(names["predicate_flag"], (x_term,)),),
                conclusion=ir.Atom(names["predicate_flag"], (next_x,)),
            ),
            ir.HornClause(
                name=f"decoy_rel_projects_{base_index:02d}",
                variables=(x, y),
                premises=(ir.Atom(names["predicate_rel"], (x_term, y_term,)),),
                conclusion=ir.Atom(names["predicate_flag"], (x_term,)),
            ),
        )
        visible_theorems = visible_theorems + (
            ir.HornClause(
                name=f"decoy_rel_theorem_{base_index:02d}",
                variables=(x, y),
                premises=(
                    ir.Atom(names["predicate_rel"], (x_term, y_term)),
                    ir.Atom(names["predicate_flag"], (y_term,)),
                ),
                conclusion=ir.Atom(names["predicate_flag"], (x_term,)),
            ),
        )

    return replace(
        world,
        signature=signature,
        axioms=axioms,
        visible_theorems=visible_theorems,
        visible_facts=visible_facts,
        metadata={
            **world.metadata,
            "paired_difficulty_added_decoy_stage": stage,
            "paired_difficulty_added_symbols": names,
        },
    )


def _deep_bridge_goal(world: ir.World, *, step: int) -> ir.Goal | None:
    """Build one deeper hidden goal for transition-shaped paper-core families."""

    budget = max(step, int(world.scoring_config.get("proof_budget", step)))
    if world.family == "invariant":
        term = iterate_term("step", ir.ConstTerm("s0"), step)
        return ir.Goal(
            name=f"hidden_stable_{step}",
            atoms=(ir.Atom("A", (term,)), ir.Atom("B", (term,)), ir.Atom("C", (term,))),
            budget=budget,
            description=f"Stable predicate bundle after {step} transitions.",
        )
    if world.family == "predicate_invention":
        left = iterate_term("f0", ir.ConstTerm("c0"), step)
        right = iterate_term("f1", ir.ConstTerm("d0"), step)
        return ir.Goal(
            name=f"hidden_step_{step}",
            atoms=(ir.Atom("R", (left, right)), ir.Atom("P0", (left,)), ir.Atom("P1", (right,))),
            budget=budget,
            description=f"Low-level synchronized state after {step} transition steps.",
        )
    if world.family == "multi_step":
        left = iterate_term("f", ir.ConstTerm("c0"), step)
        right = iterate_term("g", ir.ConstTerm("d0"), step)
        return ir.Goal(
            name=f"hidden_k_{step}",
            atoms=(ir.Atom("K", (ir.FuncTerm("h", (left, right)),)),),
            budget=budget,
            description=f"Downstream K property after {step} synchronized paired steps.",
        )
    if world.family == "lemma_invention":
        seed_depth = max(2, min(step - 3, 3))
        seed = iterate_term("f", ir.ConstTerm("c0"), seed_depth)
        return ir.Goal(
            name=f"hidden_chain_deep_{seed_depth}",
            atoms=(
                ir.Atom(
                    "D",
                    (ir.FuncTerm("h", (ir.FuncTerm("g", (ir.FuncTerm("f", (seed,)),)),)),),
                ),
            ),
            budget=budget,
            description=f"Deeper shortcut theorem for the composed f/g/h chain from f^{seed_depth}(c0).",
        )
    if world.family == "normal_form":
        term = ir.FuncTerm(
            "n",
            (ir.FuncTerm("n", (ir.FuncTerm("a", (ir.FuncTerm("b", (ir.ConstTerm("z"),)),)),)),),
        )
        return ir.Goal(
            name="hidden_done_deep_normalize",
            atoms=(ir.Atom("Done", (term,)),),
            budget=budget,
            description="Deeper reducible term that must collapse through the normal-form bridge.",
        )
    if world.family == "quotient":
        left = iterate_term("step", ir.ConstTerm("c0"), 2)
        right = iterate_term("step", ir.FuncTerm("norm", (ir.ConstTerm("c0"),)), 2)
        return ir.Goal(
            name="hidden_deep_step_class",
            atoms=(ir.Atom("R", (left, right)),),
            budget=budget,
            description="Deeper representative-preservation target across quotient steps.",
        )
    return None


def _add_analogy_deep_transport(world: ir.World, *, step: int) -> ir.World:
    """Add a deeper source theorem so analogy transport has a longer proof gap."""

    if world.family != "analogy":
        return world
    left_index = next((index for index, theory in enumerate(world.theories) if theory.name == "Left"), None)
    if left_index is None:
        return replace(
            world,
            metadata={
                **world.metadata,
                "paired_difficulty_deep_bridge_note": "Analogy source theory Left was unavailable.",
            },
        )

    left_theory = world.theories[left_index]
    theorem_name = f"left_deep_bridge_{step}"
    if any(theorem.name == theorem_name for theorem in left_theory.document.theorems):
        return world

    variable = ir.Variable("x", "L0")
    term: ir.Term = ir.VarTerm(variable)
    for _ in range(max(2, step // 2)):
        term = ir.FuncTerm("lg", (ir.FuncTerm("lf", (term,)),))

    theorem = ir.HornClause(
        name=theorem_name,
        variables=(variable,),
        premises=(ir.Atom("LP", (ir.VarTerm(variable),)),),
        conclusion=ir.Atom("LP", (term,)),
    )
    updated_left = replace(
        left_theory,
        document=replace(
            left_theory.document,
            theorems=left_theory.document.theorems + (theorem,),
        ),
    )
    updated_theories = tuple(
        updated_left if index == left_index else theory for index, theory in enumerate(world.theories)
    )
    proof_fixtures = {
        **world.proof_fixtures,
        f"transport_{theorem_name}": {
            "baseline_cost": None,
            "gold_cost": max(2, step // 2),
            "budget": step,
            "shape_control": "deep_bridge",
        },
    }
    return replace(
        world,
        theories=updated_theories,
        proof_fixtures=proof_fixtures,
        metadata={
            **world.metadata,
            "max_term_depth": max(int(world.metadata.get("max_term_depth", 3)), step),
            "paired_difficulty_deep_bridge_step": step,
            "paired_difficulty_deep_bridge_transport_theorem": theorem_name,
        },
    )


def _add_deep_bridge_shape(world: ir.World, *, step: int | None) -> ir.World:
    if step is None:
        return world
    if world.family == "analogy":
        return _add_analogy_deep_transport(world, step=step)
    goal = _deep_bridge_goal(world, step=step)
    if goal is None or any(existing.name == goal.name for existing in world.targets_hidden):
        return replace(
            world,
            metadata={
                **world.metadata,
                "paired_difficulty_deep_bridge_note": "Deep bridge shape not supported for this source family.",
            },
        )
    proof_fixtures = {
        **world.proof_fixtures,
        goal.name: {
            "baseline_cost": None,
            "gold_cost": None,
            "budget": goal.budget,
            "shape_control": "deep_bridge",
        },
    }
    hidden_steps = list(world.metadata.get("hidden_steps", []))
    if step not in hidden_steps:
        hidden_steps.append(step)
    return replace(
        world,
        targets_hidden=world.targets_hidden + (goal,),
        proof_fixtures=proof_fixtures,
        metadata={
            **world.metadata,
            "max_term_depth": max(int(world.metadata.get("max_term_depth", 3)), step),
            "hidden_steps": sorted(hidden_steps),
            "paired_difficulty_deep_bridge_step": step,
        },
    )


def _add_abstraction_chain_proxy(world: ir.World, *, family: str, base_index: int, enabled: bool) -> ir.World:
    if not enabled:
        return world

    names = _decoy_names(family, base_index)
    aux_sort = names["sort"]
    existing_predicates = {predicate.name for predicate in world.signature.predicates}
    stage_predicates = (
        ir.PredicateSymbol(f"AuxChain0_{family}_{base_index:02d}", (aux_sort,)),
        ir.PredicateSymbol(f"AuxChain1_{family}_{base_index:02d}", (aux_sort,)),
        ir.PredicateSymbol(f"AuxChain2_{family}_{base_index:02d}", (aux_sort,)),
    )
    new_predicates = tuple(predicate for predicate in stage_predicates if predicate.name not in existing_predicates)
    if not new_predicates:
        return world

    x = ir.Variable(f"chain_x_{family}_{base_index:02d}", aux_sort)
    x_term = ir.VarTerm(x)
    chain0, chain1, chain2 = (predicate.name for predicate in stage_predicates)
    signature = replace(world.signature, predicates=world.signature.predicates + new_predicates)
    return replace(
        world,
        signature=signature,
        visible_facts=world.visible_facts
        + (
            ir.Fact(
                f"abstraction_chain_seed_{base_index:02d}",
                ir.Atom(chain0, (ir.ConstTerm(names["constant_a"]),)),
            ),
        ),
        axioms=world.axioms
        + (
            ir.HornClause(
                name=f"abstraction_chain_0_1_{base_index:02d}",
                variables=(x,),
                premises=(ir.Atom(chain0, (x_term,)),),
                conclusion=ir.Atom(chain1, (x_term,)),
            ),
            ir.HornClause(
                name=f"abstraction_chain_1_2_{base_index:02d}",
                variables=(x,),
                premises=(ir.Atom(chain1, (x_term,)),),
                conclusion=ir.Atom(chain2, (x_term,)),
            ),
        ),
        visible_theorems=world.visible_theorems
        + (
            ir.HornClause(
                name=f"abstraction_chain_decoy_goal_{base_index:02d}",
                variables=(x,),
                premises=(ir.Atom(chain2, (x_term,)),),
                conclusion=ir.Atom(names["predicate_flag"], (x_term,)),
            ),
        ),
        metadata={
            **world.metadata,
            "paired_difficulty_abstraction_chain_proxy": True,
            "paired_difficulty_abstraction_chain_note": (
                "Public chain proxy added; real hidden abstraction-chain pressure comes from multi_step source worlds."
            ),
        },
    )


def _alpha_rename_and_reorder(world: ir.World) -> ir.World:
    """Apply a semantics-preserving public-order shuffle and alpha renaming."""

    reordered = replace(
        world,
        axioms=tuple(reversed(world.axioms)),
        visible_theorems=tuple(reversed(world.visible_theorems)),
        visible_facts=tuple(reversed(world.visible_facts)),
        targets_visible=tuple(reversed(world.targets_visible)),
        metadata={
            **world.metadata,
            "paired_difficulty_public_order": "reversed",
        },
    )
    return _alpha_rename_world(reordered)


def _base_world(
    *,
    family: str,
    seed: int,
    world_id: str,
    base_index: int,
) -> ir.World:
    request = WorldGenerationRequest(
        family=family,
        seed=seed,
        world_id=world_id,
        max_term_depth=4,
        proof_budget=4,
        hidden_steps=(2, 3, 4),
        include_distractors=False,
    )
    world = generate_world(request)
    return replace(
        world,
        metadata={
            **world.metadata,
            "paired_difficulty_experiment": "paper_core_paired_difficulty_controls",
            "paired_difficulty_control_mode": "independent_shapes",
            "paired_difficulty_base_index": base_index,
            "paired_difficulty_base_seed": seed,
            "paired_difficulty_family_prior_stratum": FAMILY_PRIOR_STRATA.get(family, "unknown"),
            "paired_difficulty_base_request": {
                "max_term_depth": request.max_term_depth,
                "proof_budget": request.proof_budget,
                "hidden_steps": list(request.hidden_steps),
                "include_distractors": request.include_distractors,
            },
        },
    )


def _source_case_world(
    *,
    source_dataset_root: Path,
    case: CaseSpec,
    level: DifficultyLevel,
    case_index: int,
) -> ir.World:
    source_world_root = source_dataset_root / SPLIT / case.family / case.world_id
    world = load_world(source_world_root)
    paired_world_id = f"abw_paired_{case.label}_{case.family}_{case.world_id}_{level.level_id}"
    return replace(
        world,
        world_id=paired_world_id,
        metadata={
            **world.metadata,
            "paired_difficulty_experiment": "paper_core_paired_difficulty_controls",
            "paired_difficulty_control_mode": "independent_shapes",
            "paired_difficulty_case_label": case.label,
            "paired_difficulty_case_index": case_index,
            "paired_difficulty_source_dataset_root": str(source_dataset_root),
            "paired_difficulty_source_world_id": case.world_id,
            "paired_difficulty_source_family": case.family,
            "paired_difficulty_family_prior_stratum": FAMILY_PRIOR_STRATA.get(case.family, "unknown"),
            "paired_difficulty_hidden_bridge_fixed": True,
        },
    )


def _variant_world(
    *,
    family: str,
    seed: int,
    base_index: int,
    level: DifficultyLevel,
) -> ir.World:
    world_id = f"abw_paired_{family}_{base_index:02d}_{level.level_id}"
    world = _base_world(family=family, seed=seed, world_id=world_id, base_index=base_index)
    world = _add_deep_bridge_shape(world, step=level.deep_bridge_step)
    world = _add_public_decoys(world, family=family, base_index=base_index, stage=level.public_decoy_stage)
    world = _add_abstraction_chain_proxy(
        world,
        family=family,
        base_index=base_index,
        enabled=level.abstraction_chain_proxy,
    )
    if level.alpha_rename_and_reorder:
        world = _alpha_rename_and_reorder(world)
    return replace(
        world,
        metadata={
            **world.metadata,
            "paired_difficulty_level_index": level.index,
            "paired_difficulty_level_id": level.level_id,
            "paired_difficulty_level_label": level.label,
            "paired_difficulty_expected_complexity_rank": level.expected_complexity_rank,
            "paired_difficulty_requested_controls": list(level.requested_controls),
            "paired_difficulty_feature_pattern": level.feature_pattern,
            "paired_difficulty_scientific_rationale": level.scientific_rationale,
            "paired_difficulty_control_description": level.description,
            "paired_difficulty_base_key": f"{family}:{base_index:02d}",
            "paired_difficulty_hidden_bridge_fixed": True,
        },
    )


def _case_variant_world(
    *,
    source_dataset_root: Path,
    case: CaseSpec,
    case_index: int,
    level: DifficultyLevel,
) -> ir.World:
    world = _source_case_world(
        source_dataset_root=source_dataset_root,
        case=case,
        level=level,
        case_index=case_index,
    )
    world = _add_deep_bridge_shape(world, step=level.deep_bridge_step)
    world = _add_public_decoys(world, family=case.family, base_index=case_index, stage=level.public_decoy_stage)
    world = _add_abstraction_chain_proxy(
        world,
        family=case.family,
        base_index=case_index,
        enabled=level.abstraction_chain_proxy,
    )
    if level.alpha_rename_and_reorder:
        world = _alpha_rename_and_reorder(world)
    return replace(
        world,
        metadata={
            **world.metadata,
            "paired_difficulty_level_index": level.index,
            "paired_difficulty_level_id": level.level_id,
            "paired_difficulty_level_label": level.label,
            "paired_difficulty_expected_complexity_rank": level.expected_complexity_rank,
            "paired_difficulty_requested_controls": list(level.requested_controls),
            "paired_difficulty_feature_pattern": level.feature_pattern,
            "paired_difficulty_scientific_rationale": level.scientific_rationale,
            "paired_difficulty_control_description": level.description,
            "paired_difficulty_base_key": f"{case.label}:{case.family}:{case.world_id}",
            "paired_difficulty_hidden_bridge_fixed": True,
        },
    )


def _parse_case_spec(spec: str) -> CaseSpec:
    parts = spec.split(":")
    if len(parts) != 3 or not all(parts):
        raise ValueError("Case specs must have the form LABEL:FAMILY:WORLD_ID.")
    label, family, world_id = parts
    if family not in PAPER_FAMILIES:
        raise ValueError(f"Unknown paper-core family in case spec: {family!r}.")
    return CaseSpec(label=label, family=family, world_id=world_id)


def build_dataset(
    *,
    output_root: Path,
    examples_per_family: int,
    start_seed: int,
    overwrite: bool,
    validate: bool,
) -> dict[str, Any]:
    if output_root.exists():
        if not overwrite:
            raise FileExistsError(f"Output root already exists: {output_root}. Use --overwrite to replace it.")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    worlds: list[dict[str, Any]] = []
    validation_failures: list[dict[str, Any]] = []
    for family_index, family in enumerate(PAPER_FAMILIES):
        for base_index in range(examples_per_family):
            seed = start_seed + family_index * 100 + base_index
            for level in DIFFICULTY_LEVELS:
                world = _variant_world(
                    family=family,
                    seed=seed,
                    base_index=base_index,
                    level=level,
                )
                world_root = output_root / SPLIT / family / world.world_id
                package_world(world, world_root)
                if validate:
                    report = validate_package(world_root)
                    if not report.get("valid", False):
                        validation_failures.append({"world_root": str(world_root), "report": report})
                worlds.append(
                    {
                        "world_id": world.world_id,
                        "split": SPLIT,
                        "family": family,
                        "base_index": base_index,
                        "base_seed": seed,
                        "base_key": f"{family}:{base_index:02d}",
                        "family_prior_stratum": FAMILY_PRIOR_STRATA.get(family, "unknown"),
                        "difficulty_level_index": level.index,
                        "difficulty_level_id": level.level_id,
                        "difficulty_level_label": level.label,
                        "expected_complexity_rank": level.expected_complexity_rank,
                        "requested_controls": list(level.requested_controls),
                        "feature_pattern": level.feature_pattern,
                        "scientific_rationale": level.scientific_rationale,
                        "description": level.description,
                        "world_root": str(world_root),
                    }
                )

    manifest = {
        "dataset_name": "paper_core_paired_difficulty_controls",
        "created_at_utc": _utc_now(),
        "version": "0.2.0",
        "control_mode": "independent_shapes",
        "split": SPLIT,
        "families": list(PAPER_FAMILIES),
        "examples_per_family": examples_per_family,
        "worlds_per_family": examples_per_family * len(DIFFICULTY_LEVELS),
        "world_count": len(worlds),
        "base_world_count": examples_per_family * len(PAPER_FAMILIES),
        "difficulty_levels": [
            {
                "index": level.index,
                "level_id": level.level_id,
                "label": level.label,
                "expected_complexity_rank": level.expected_complexity_rank,
                "requested_controls": list(level.requested_controls),
                "feature_pattern": level.feature_pattern,
                "scientific_rationale": level.scientific_rationale,
                "description": level.description,
            }
            for level in DIFFICULTY_LEVELS
        ],
        "design_note": (
            "Variants are paired by family and base_index. Each non-base variant applies one "
            "Appendix A difficulty shape to the same source world; C0--C6 are sorted by "
            "intervention severity. C1--C5 are independent feature bundles rather than "
            "cumulative controls, while C6 is the deliberate stress-boundary bundle."
        ),
        "selection_note": (
            "All seven paper-core families are included. The stratum label is inherited from prior GPT-5.5 "
            "Formal Direct family performance: analogy/invariant/lemma are high-prior, while predicate, "
            "multi-step, normal-form, and quotient are hard-prior."
        ),
        "validation": {
            "enabled": validate,
            "valid": not validation_failures,
            "failures": validation_failures,
        },
        "worlds": worlds,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output_root / DEFAULT_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_case_dataset(
    *,
    output_root: Path,
    source_dataset_root: Path,
    cases: tuple[CaseSpec, ...],
    overwrite: bool,
    validate: bool,
) -> dict[str, Any]:
    if output_root.exists():
        if not overwrite:
            raise FileExistsError(f"Output root already exists: {output_root}. Use --overwrite to replace it.")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    worlds: list[dict[str, Any]] = []
    validation_failures: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        for level in DIFFICULTY_LEVELS:
            world = _case_variant_world(
                source_dataset_root=source_dataset_root,
                case=case,
                case_index=case_index,
                level=level,
            )
            world_root = output_root / SPLIT / case.family / world.world_id
            package_world(world, world_root)
            if validate:
                report = validate_package(world_root)
                if not report.get("valid", False):
                    validation_failures.append({"world_root": str(world_root), "report": report})
            worlds.append(
                {
                    "world_id": world.world_id,
                    "split": SPLIT,
                    "case_label": case.label,
                    "case_index": case_index,
                    "family": case.family,
                    "source_world_id": case.world_id,
                    "source_dataset_root": str(source_dataset_root),
                    "base_key": f"{case.label}:{case.family}:{case.world_id}",
                    "family_prior_stratum": FAMILY_PRIOR_STRATA.get(case.family, "unknown"),
                    "difficulty_level_index": level.index,
                    "difficulty_level_id": level.level_id,
                    "difficulty_level_label": level.label,
                    "expected_complexity_rank": level.expected_complexity_rank,
                    "requested_controls": list(level.requested_controls),
                    "feature_pattern": level.feature_pattern,
                    "scientific_rationale": level.scientific_rationale,
                    "description": level.description,
                    "world_root": str(world_root),
                }
            )

    selected_families = sorted({case.family for case in cases})
    manifest = {
        "dataset_name": "paper_core_paired_difficulty_controls",
        "created_at_utc": _utc_now(),
        "version": "0.2.0",
        "control_mode": "independent_shapes",
        "split": SPLIT,
        "source_dataset_root": str(source_dataset_root),
        "families": selected_families,
        "case_count": len(cases),
        "world_count": len(worlds),
        "difficulty_levels": [
            {
                "index": level.index,
                "level_id": level.level_id,
                "label": level.label,
                "expected_complexity_rank": level.expected_complexity_rank,
                "requested_controls": list(level.requested_controls),
                "feature_pattern": level.feature_pattern,
                "scientific_rationale": level.scientific_rationale,
                "description": level.description,
            }
            for level in DIFFICULTY_LEVELS
        ],
        "cases": [
            {
                "label": case.label,
                "family": case.family,
                "source_world_id": case.world_id,
                "family_prior_stratum": FAMILY_PRIOR_STRATA.get(case.family, "unknown"),
            }
            for case in cases
        ],
        "design_note": (
            "Variants are paired by case. Each non-base variant applies one independent Appendix A "
            "difficulty shape to the same source world; C0--C6 are sorted by intervention severity. "
            "C1--C5 are independent feature bundles rather than cumulative controls, while C6 is "
            "the deliberate stress-boundary bundle."
        ),
        "selection_note": (
            "Default cases select one source world from each paper-core family. Analogy, invariant, "
            "and lemma_invention are high-prior-performance cases; predicate_invention, normal_form, "
            "quotient, and multi_step are hard-prior-performance cases with low or invalid archived outputs."
        ),
        "validation": {
            "enabled": validate,
            "valid": not validation_failures,
            "failures": validation_failures,
        },
        "worlds": worlds,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (output_root / DEFAULT_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the paired ABW difficulty-control dataset.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--source-dataset-root", default=str(REPO_ROOT / "datasets" / "paper_core"))
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        help="Source-world case spec LABEL:FAMILY:WORLD_ID. Defaults to one easy and one hard case.",
    )
    parser.add_argument("--all-families", action="store_true", help="Generate the older all-family paired dataset.")
    parser.add_argument("--examples-per-family", type=int, default=2)
    parser.add_argument("--start-seed", type=int, default=9100)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.all_families:
        manifest = build_dataset(
            output_root=Path(args.output),
            examples_per_family=args.examples_per_family,
            start_seed=args.start_seed,
            overwrite=args.overwrite,
            validate=not args.no_validate,
        )
    else:
        case_specs = tuple(_parse_case_spec(spec) for spec in (args.case or DEFAULT_CASES))
        manifest = build_case_dataset(
            output_root=Path(args.output),
            source_dataset_root=Path(args.source_dataset_root),
            cases=case_specs,
            overwrite=args.overwrite,
            validate=not args.no_validate,
        )
    print(
        json.dumps(
            {
                "output": str(Path(args.output)),
                "world_count": manifest["world_count"],
                "case_count": manifest.get("case_count"),
                "base_world_count": manifest.get("base_world_count"),
                "validation": manifest["validation"],
            },
            indent=2,
        )
    )
    return 0 if manifest["validation"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
