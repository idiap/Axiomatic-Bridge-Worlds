# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""End-to-end unit coverage for world generation and candidate scoring.

These tests sit close to the benchmark contract: generate seeded worlds across
families, score strong and weak candidates, and confirm that novelty,
equivalence, and counterexample reporting reward the intended bridge behavior.
"""

from abw_core.generator import WorldGenerationRequest, generate_world, registered_families
from abw_core.generator.variation import benchmark_content_fingerprint, public_content_fingerprint
from abw_core.scorer import evaluate_candidate


GOLD_CANDIDATE = """
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
"""

TRIVIAL_CANDIDATE = """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_step: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), f1(y))
"""

SHIFTED_ALIAS_CANDIDATE = """
define ShiftedPair(x:S0, y:S1) := R(f0(x), f1(y))
lemma shiftedpair_step: forall x:S0 y:S1. ShiftedPair(x,y) -> ShiftedPair(f0(x), f1(y))
"""

OVERSTATED_CANDIDATE = """
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
lemma pairstable_left: forall x:S0 y:S1. PairStable(x,y) -> P0(x)
"""

ROADMAP_CANDIDATES = {
    "lemma_invention": """
lemma chain3_candidate: forall x:S0. A(x) -> D(h(g(f(x))))
""",
    "invariant": """
define Preserved(x:S0) := A(x) & B(x) & C(x)
lemma preserved_step: forall x:S0. Preserved(x) -> Preserved(step(x))
""",
    "quotient": """
define Equivalent(x:S0, y:S0) := R(x,y)
define Canonical(x:S0) := norm(x) = x
lemma good_on_canonical: forall x:S0. Good(x) -> Good(norm(x))
""",
    "normal_form": """
    lemma done_after_normalize: forall x:T. Marker(x) -> Done(n(x))
""",
    "multi_step": """
define PairStable(x:S0, y:S1) := A(x) & B(y) & R(x,y)
lemma pair_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f(x), g(y))
lemma pair_to_k: forall x:S0 y:S1. PairStable(x,y) -> K(h(x,y))
""",
    "analogy": """
morphism Guess : Left -> Right {
  L0 -> R0
  l0 -> r0
  lf -> rf
  lg -> rg
  LP -> RP
  LQ -> RQ
}
""",
}


def test_generator_builds_useful_proof_fixture() -> None:
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    assert world.proof_fixtures["hidden_step_2"]["gold_cost"] < world.proof_fixtures["hidden_step_2"]["baseline_cost"]


def test_gold_candidate_scores_above_trivial_candidate() -> None:
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    gold = evaluate_candidate(world, GOLD_CANDIDATE)
    trivial = evaluate_candidate(world, TRIVIAL_CANDIDATE)
    assert gold["valid"] is True
    assert trivial["valid"] is True
    assert gold["metrics"]["total_score"] > trivial["metrics"]["total_score"]
    assert gold["metrics"]["semantic_equivalence_score"] > trivial["metrics"]["semantic_equivalence_score"]


def test_semantic_equivalence_penalizes_extra_candidate_structure() -> None:
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    gold = evaluate_candidate(world, GOLD_CANDIDATE)
    overstated = evaluate_candidate(world, OVERSTATED_CANDIDATE)
    assert overstated["valid"] is True
    assert gold["metrics"]["semantic_equivalence_score"] > overstated["metrics"]["semantic_equivalence_score"]


def test_novelty_penalizes_semantic_single_atom_aliases() -> None:
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    gold = evaluate_candidate(world, GOLD_CANDIDATE)
    alias = evaluate_candidate(world, TRIVIAL_CANDIDATE)
    shifted = evaluate_candidate(world, SHIFTED_ALIAS_CANDIDATE)
    assert alias["valid"] is True
    assert shifted["valid"] is True
    assert alias["metrics"]["novelty_score"] == 0.0
    assert shifted["metrics"]["novelty_score"] == 0.0
    assert gold["metrics"]["novelty_score"] > shifted["metrics"]["novelty_score"]


def test_roadmap_families_generate_and_score_valid_candidates() -> None:
    for family, candidate in ROADMAP_CANDIDATES.items():
        world = generate_world(WorldGenerationRequest(family=family, seed=7))
        report = evaluate_candidate(world, candidate)
        assert report["valid"] is True, (family, report["errors"])
        assert report["metrics"]["total_score"] > 0.0, family


def test_disclosure_family_registry_contains_only_paper_core_families() -> None:
    assert set(registered_families()) == {
        "analogy",
        "invariant",
        "lemma_invention",
        "multi_step",
        "normal_form",
        "predicate_invention",
        "quotient",
    }


def test_generated_world_metadata_declares_dsl_version() -> None:
    for family in registered_families():
        world = generate_world(WorldGenerationRequest(family=family, seed=7))
        assert "dsl_version" in world.metadata, family
        assert world.metadata["dsl_version"] in {"abw-dsl-v1", "abw-dsl-v2"}


def test_different_seeds_change_each_family_task_content() -> None:
    for family in registered_families():
        first = generate_world(
            WorldGenerationRequest(family=family, seed=8, max_term_depth=3, hidden_steps=(2, 3))
        )
        second = generate_world(
            WorldGenerationRequest(family=family, seed=9, max_term_depth=3, hidden_steps=(2, 3))
        )
        assert first.metadata["schema_fingerprint"] != second.metadata["schema_fingerprint"], family
        assert benchmark_content_fingerprint(first) != benchmark_content_fingerprint(second), family
        assert public_content_fingerprint(first) != public_content_fingerprint(second), family


def test_seeded_gold_bridge_reduces_at_least_one_proof_fixture() -> None:
    for family in registered_families():
        world = generate_world(
            WorldGenerationRequest(family=family, seed=8, max_term_depth=3, hidden_steps=(2, 3))
        )
        assert any(
            fixture.get("gold_cost") is not None
            and (fixture.get("baseline_cost") is None or fixture["gold_cost"] < fixture["baseline_cost"])
            for fixture in world.proof_fixtures.values()
        ), family


def test_morphism_candidate_tolerates_trailing_mapping_commas() -> None:
    world = generate_world(WorldGenerationRequest(family="analogy", seed=7))
    candidate = """
morphism Guess : Left -> Right {
  L0 -> R0,
  l0 -> r0,
  lf -> rf,
  lg -> rg,
  LP -> RP,
  LQ -> RQ
}
"""

    report = evaluate_candidate(world, candidate)

    assert report["valid"] is True, report["errors"]
    assert report["metrics"]["total_score"] > 0.0


def test_invalid_candidate_reports_structured_counterexamples() -> None:
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    report = evaluate_candidate(
        world,
        """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_bad: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), y)
""",
    )
    assert report["valid"] is False
    assert report["counterexamples"]
    first = report["counterexamples"][0]
    assert first["clause"] == "paironly_bad"
    assert first["missing_conclusion"]["predicate"] == "PairOnly"
    assert "Clause 'paironly_bad' fails" in first["message"]
