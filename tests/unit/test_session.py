# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Coverage for the bounded interactive refinement session workflow.

Sessions are the public-facing diagnostic loop for candidate iteration. These
tests verify budgeting, transcript recording, public validation paths, and the
new equivalence or structural-query surfaces without exposing hidden answers.
"""

import json

from abw_core.generator import WorldGenerationRequest, generate_world
from abw_core.packager import package_world
from abw_core.session import finish_session, load_session, run_session_query, start_session


GOLD_CANDIDATE = """
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
"""

MORPHISM_CANDIDATE = """
morphism Guess : Left -> Right {
  L0 -> R0
  l0 -> r0
  lf -> rf
  lg -> rg
  LP -> RP
  LQ -> RQ
}
"""

BAD_CANDIDATE = """
define PairOnly(x:S0, y:S1) := R(x,y)
lemma paironly_bad: forall x:S0 y:S1. PairOnly(x,y) -> PairOnly(f0(x), y)
"""


def _write_candidate(path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_start_session_uses_world_interactive_defaults(tmp_path) -> None:
    world = generate_world(WorldGenerationRequest(family="predicate_invention", seed=7))
    world_root = package_world(world, tmp_path / "world")

    started = start_session(world_root, tmp_path / "session")
    state = load_session(tmp_path / "session")

    assert started["query_budget"] == 20
    assert started["countermodels_enabled"] is True
    assert state.world_id == world.world_id
    assert state.queries_used == 0
    assert len(state.transcript) == 1


def test_validate_query_reports_counterexamples_and_consumes_budget(tmp_path) -> None:
    world_root = package_world(
        generate_world(WorldGenerationRequest(family="predicate_invention", seed=7)),
        tmp_path / "world",
    )
    session_root = tmp_path / "session"
    candidate_path = tmp_path / "bad_candidate.abw"
    _write_candidate(candidate_path, BAD_CANDIDATE)

    start_session(world_root, session_root, query_budget=2)
    response = run_session_query(session_root, kind="validate", candidate_path=candidate_path)
    state = load_session(session_root)

    assert response["accepted"] is True
    assert response["queries_used"] == 1
    assert response["remaining_queries"] == 1
    assert response["response"]["valid"] is False
    assert response["response"]["counterexamples"][0]["clause"] == "paironly_bad"
    assert state.queries_used == 1


def test_examples_query_and_finish_session_track_efficiency(tmp_path) -> None:
    world_root = package_world(
        generate_world(WorldGenerationRequest(family="predicate_invention", seed=7)),
        tmp_path / "world",
    )
    session_root = tmp_path / "session"
    candidate_path = tmp_path / "gold_candidate.abw"
    _write_candidate(candidate_path, GOLD_CANDIDATE)

    start_session(world_root, session_root, query_budget=2)
    examples = run_session_query(
        session_root,
        kind="examples",
        candidate_path=candidate_path,
        predicate="PairStable",
        limit=3,
    )
    finished = finish_session(session_root, candidate_path=candidate_path)
    closed = run_session_query(session_root, kind="examples", predicate="P0", limit=1)

    assert examples["accepted"] is True
    assert examples["response"]["valid"] is True
    assert examples["response"]["examples"]
    assert finished["final_report"]["valid"] is True
    assert finished["exploration_efficiency_score"] == 0.5
    assert closed["accepted"] is False
    assert "closed" in closed["error"]


def test_examples_query_keeps_limit_error_even_with_candidate(tmp_path) -> None:
    world_root = package_world(
        generate_world(WorldGenerationRequest(family="predicate_invention", seed=7)),
        tmp_path / "world",
    )
    session_root = tmp_path / "session"
    candidate_path = tmp_path / "gold_candidate.abw"
    _write_candidate(candidate_path, GOLD_CANDIDATE)

    start_session(world_root, session_root, query_budget=2)
    response = run_session_query(
        session_root,
        kind="examples",
        candidate_path=candidate_path,
        predicate="PairStable",
        limit=0,
    )

    assert response["accepted"] is True
    assert response["response"]["valid"] is False
    assert "positive --limit" in response["response"]["errors"][0]


def test_countermodel_query_returns_public_model_and_budget_exhaustion_is_logged(tmp_path) -> None:
    world_root = package_world(
        generate_world(WorldGenerationRequest(family="multi_step", seed=7)),
        tmp_path / "world",
    )
    session_root = tmp_path / "session"

    start_session(world_root, session_root, query_budget=1)
    response = run_session_query(
        session_root,
        kind="countermodel",
        atoms_text="A(f(f(f(f(f(c0))))))",
    )
    exhausted = run_session_query(
        session_root,
        kind="countermodel",
        atoms_text="A(c0)",
    )
    transcript_lines = (session_root / "transcript.jsonl").read_text(encoding="utf-8").strip().splitlines()
    final_entry = json.loads(transcript_lines[-1])

    assert response["accepted"] is True
    assert response["response"]["valid"] is True
    assert response["response"]["countermodel"] is not None
    assert exhausted["accepted"] is False
    assert exhausted["error"] == "Query budget exhausted."
    assert final_entry["response"]["accepted"] is False


def test_equivalence_query_reports_public_stability(tmp_path) -> None:
    world_root = package_world(
        generate_world(WorldGenerationRequest(family="predicate_invention", seed=7)),
        tmp_path / "world",
    )
    session_root = tmp_path / "session"
    candidate_path = tmp_path / "gold_candidate.abw"
    _write_candidate(candidate_path, GOLD_CANDIDATE)

    start_session(world_root, session_root, query_budget=2)
    response = run_session_query(session_root, kind="equivalence", candidate_path=candidate_path)

    assert response["accepted"] is True
    assert response["response"]["valid"] is True
    assert response["response"]["stability_score"] > 0.5
    assert response["response"]["model_reports"]


def test_validate_query_supports_morphism_candidates(tmp_path) -> None:
    world_root = package_world(
        generate_world(WorldGenerationRequest(family="analogy", seed=7)),
        tmp_path / "world",
    )
    session_root = tmp_path / "session"
    candidate_path = tmp_path / "morphism_candidate.abw"
    _write_candidate(candidate_path, MORPHISM_CANDIDATE)

    start_session(world_root, session_root, query_budget=2)
    response = run_session_query(session_root, kind="validate", candidate_path=candidate_path)

    assert response["accepted"] is True
    assert response["response"]["valid"] is True
    assert response["response"]["candidate_shape"]["morphisms"] == 1
    assert response["response"]["transport_reports"][0]["valid"] is True
