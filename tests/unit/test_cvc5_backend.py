# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Behavioral tests for the optional cvc5-backed finite-model diagnostics.

The local closure engine is intentionally lightweight, so these tests make sure
the stronger cvc5 path catches vacuous unsound clauses and false goals that the
least-model closure alone cannot disprove.
"""

import sys

import pytest

pytest.importorskip("cvc5")

import abw_core.prover.cvc5_driver as cvc5_driver
import abw_core.prover.cvc5_finite_models as cvc5_finite_models
from abw_core.dsl import parse_document
from abw_core.prover import BackendConfig, find_clause_counterexamples_with_backend, find_goal_countermodel_with_backend
from abw_core.typecheck import build_signature, check_document


def test_cvc5_backend_finds_vacuous_unsound_clause_beyond_local_closure() -> None:
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
    cvc5_counterexamples = find_clause_counterexamples_with_backend(
        signature=extended_signature,
        facts=document.facts,
        base_clauses=document.axioms,
        definitions=candidate.definitions,
        clause=candidate.lemmas[0],
        backend=BackendConfig(name="cvc5"),
    )

    assert local == ()
    assert cvc5_counterexamples
    assert cvc5_counterexamples[0]["clause"] == "bad"
    assert cvc5_counterexamples[0]["backend"] == "cvc5"
    assert "finite model" in cvc5_counterexamples[0]["message"]


def test_cvc5_backend_returns_finite_countermodel_payload() -> None:
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
        backend=BackendConfig(name="cvc5"),
    )

    assert countermodel is not None
    assert countermodel["backend"] == "cvc5"
    assert countermodel["model_kind"] == "finite"
    assert countermodel["false_atoms"][0]["predicate"] == "A"


def test_cvc5_subprocess_driver_matches_direct_backend_shape() -> None:
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
        backend=BackendConfig(name="subprocess", command=(sys.executable, "-m", "abw_core.prover.cvc5_driver")),
    )

    assert delegated
    assert delegated[0]["backend"] == "cvc5"
    assert callable(cvc5_driver.main)
    assert cvc5_finite_models.cvc5_is_available()
