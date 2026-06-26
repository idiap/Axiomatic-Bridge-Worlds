# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Behavioral tests for the optional Z3-backed finite-model diagnostics.

Like the cvc5 coverage, these tests confirm that the stronger bounded-model
backend can reject clauses and goals that look harmless under the local closure
alone, while staying compatible with the ABW backend adapter contract.
"""

import sys

import pytest

pytest.importorskip("z3")

import abw_core.prover.z3_driver as z3_driver
import abw_core.prover.z3_finite_models as z3_finite_models
from abw_core.dsl import parse_document
from abw_core.prover import BackendConfig, find_clause_counterexamples_with_backend, find_goal_countermodel_with_backend
from abw_core.typecheck import build_signature, check_document


def test_z3_backend_finds_vacuous_unsound_clause_beyond_local_closure() -> None:
    document = parse_document(
        """
sort S
const c : S
pred A : S
pred B : S
"""
    )
    candidate = parse_document(
        """
lemma bad: forall x:S. A(x) -> B(x)
"""
    )
    signature = build_signature(document)
    check_document(document)
    extended_signature = check_document(candidate, base_signature=signature)

    local = find_clause_counterexamples_with_backend(
        signature=extended_signature,
        facts=document.facts,
        base_clauses=document.axioms,
        definitions=candidate.definitions,
        clause=candidate.lemmas[0],
    )
    z3_counterexamples = find_clause_counterexamples_with_backend(
        signature=extended_signature,
        facts=document.facts,
        base_clauses=document.axioms,
        definitions=candidate.definitions,
        clause=candidate.lemmas[0],
        backend=BackendConfig(name="z3"),
    )

    assert local == ()
    assert z3_counterexamples
    assert z3_counterexamples[0]["clause"] == "bad"
    assert z3_counterexamples[0]["backend"] == "z3"
    assert "finite model" in z3_counterexamples[0]["message"]


def test_z3_backend_returns_finite_countermodel_payload() -> None:
    document = parse_document(
        """
sort S
const c : S
pred A : S
goal probe: A(c)
"""
    )
    signature = build_signature(document)
    check_document(document)

    countermodel = find_goal_countermodel_with_backend(
        signature=signature,
        facts=document.facts,
        clauses=document.axioms,
        goal_atoms=document.goals[0].atoms,
        label="probe",
        backend=BackendConfig(name="z3"),
    )

    assert countermodel is not None
    assert countermodel["backend"] == "z3"
    assert countermodel["model_kind"] == "finite"
    assert countermodel["false_atoms"][0]["predicate"] == "A"


def test_z3_subprocess_driver_matches_direct_backend_shape() -> None:
    document = parse_document(
        """
sort S
const c : S
pred A : S
pred B : S
"""
    )
    candidate = parse_document(
        """
lemma bad: forall x:S. A(x) -> B(x)
"""
    )
    signature = build_signature(document)
    check_document(document)
    extended_signature = check_document(candidate, base_signature=signature)

    delegated = find_clause_counterexamples_with_backend(
        signature=extended_signature,
        facts=document.facts,
        base_clauses=document.axioms,
        definitions=candidate.definitions,
        clause=candidate.lemmas[0],
        backend=BackendConfig(name="subprocess", command=(sys.executable, "-m", "abw_core.prover.z3_driver")),
    )

    assert delegated
    assert delegated[0]["backend"] == "z3"
    assert callable(z3_driver.main)
    assert z3_finite_models.z3_is_available()
