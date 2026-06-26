# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Core semantic tests for typechecking, closure building, and proof-cost logic.

These assertions pin the local proving model that the rest of the benchmark
assumes: definitions extend the signature safely, bridge predicates lower goal
cost when valid, and bounded countermodels expose real failures.
"""

from abw_core.dsl import parse_document
from abw_core.prover import build_closure, find_clause_counterexamples, find_goal_countermodel, goal_cost
from abw_core.typecheck import build_signature, check_document, extend_signature_with_definitions


def test_definition_bridge_reduces_goal_cost() -> None:
    public_document = parse_document(
        """
sort S0
sort S1
const c0 : S0
const d0 : S1
func f0 : S0 -> S0
func f1 : S1 -> S1
pred P0 : S0
pred P1 : S1
pred R : S0, S1
axiom p0_step: forall x:S0. P0(x) -> P0(f0(x))
axiom p1_step: forall y:S1. P1(y) -> P1(f1(y))
axiom r_step: forall x:S0 y:S1. R(x,y) -> R(f0(x), f1(y))
fact base_p0: P0(c0)
fact base_p1: P1(d0)
fact base_r: R(c0, d0)
goal hidden: R(f0(f0(c0)), f1(f1(d0))) & P0(f0(f0(c0))) & P1(f1(f1(d0)))
"""
    )
    signature = build_signature(public_document)
    check_document(public_document)

    baseline = build_closure(signature, public_document.facts, public_document.axioms, max_term_depth=3)
    baseline_cost = goal_cost(baseline.derivations, public_document.goals[0].atoms)
    assert baseline_cost == 6

    bridge_document = parse_document(
        """
define PairStable(x:S0, y:S1) := R(x,y) & P0(x) & P1(y)
lemma pairstable_step: forall x:S0 y:S1. PairStable(x,y) -> PairStable(f0(x), f1(y))
"""
    )
    extended_signature = extend_signature_with_definitions(signature, bridge_document.definitions)
    check_document(bridge_document, base_signature=signature)
    bridged = build_closure(
        extended_signature,
        public_document.facts,
        public_document.axioms + bridge_document.lemmas,
        definitions=bridge_document.definitions,
        max_term_depth=3,
    )
    bridged_cost = goal_cost(bridged.derivations, public_document.goals[0].atoms)
    assert bridged_cost == 2


def test_rewrite_normalization_supports_done_goals_and_equalities() -> None:
    document = parse_document(
        """
sort T
const z : T
func a : T -> T
func b : T -> T
func n : T -> T
pred Done : T
rewrite r1: a(b(x)) -> n(x)
rewrite r2: n(n(x)) -> n(x)
axiom done_n: forall x:T. Done(n(x))
goal done_goal: Done(a(b(z)))
goal eq_goal: n(n(z)) = n(z)
"""
    )
    signature = build_signature(document)
    check_document(document)
    closure = build_closure(
        signature,
        facts=document.facts,
        clauses=document.axioms,
        rewrites=document.rewrites,
        max_term_depth=3,
    )
    assert goal_cost(closure.derivations, document.goals[0].atoms, document.rewrites) == 1
    assert goal_cost(closure.derivations, document.goals[1].atoms, document.rewrites) == 0


def test_find_clause_counterexamples_returns_ground_witnesses() -> None:
    document = parse_document(
        """
sort S
const c : S
func step : S -> S
pred A : S
pred B : S
axiom a_step: forall x:S. A(x) -> A(step(x))
fact base_a: A(c)
"""
    )
    candidate = parse_document(
        """
lemma impossible_b: forall x:S. A(x) -> B(x)
"""
    )
    signature = build_signature(document)
    check_document(document)
    check_document(candidate, base_signature=signature)

    counterexamples = find_clause_counterexamples(
        signature,
        facts=document.facts,
        base_clauses=document.axioms,
        definitions=(),
        clause=candidate.lemmas[0],
        max_term_depth=2,
    )

    assert counterexamples
    assert counterexamples[0].clause_name == "impossible_b"
    assert counterexamples[0].substitution["x"].to_dict() == {"kind": "const", "name": "c"}
    assert counterexamples[0].missing_conclusion.predicate == "B"
    assert counterexamples[0].to_dict()["message"].startswith("Clause 'impossible_b' fails")


def test_find_goal_countermodel_returns_bounded_interpretation() -> None:
    document = parse_document(
        """
sort S
const c : S
pred A : S
goal missing_goal: A(c)
"""
    )
    signature = build_signature(document)
    check_document(document)

    countermodel = find_goal_countermodel(
        signature,
        facts=document.facts,
        clauses=document.axioms,
        goal_atoms=document.goals[0].atoms,
        max_term_depth=1,
        label=document.goals[0].name,
    )

    assert countermodel is not None
    payload = countermodel.to_dict()
    assert payload["label"] == "missing_goal"
    assert payload["sort_domains"]["S"] == [{"kind": "const", "name": "c"}]
    assert payload["predicate_extensions"]["A"] == []
    assert payload["false_atoms"][0]["predicate"] == "A"
