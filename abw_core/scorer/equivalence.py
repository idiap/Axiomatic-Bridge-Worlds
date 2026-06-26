# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Bounded semantic-equivalence helpers for ABW candidate scoring.

The earlier scorer matched hidden and candidate bridge items only in one
direction. That was enough for the first slice, but it let extra unmatched
candidate structure slip through with too little penalty. This module now uses
symmetrical matching and also folds visible-goal agreement into the diagnostic
suite so equivalence has to survive more than one closure snapshot.
"""

from __future__ import annotations

from itertools import product

from abw_core import ir
from abw_core.prover import (
    BackendConfig,
    ProofResult,
    build_closure_with_backend,
    goal_cost,
    normalize_atom,
    public_diagnostic_models,
)
from abw_core.typecheck import extend_signature_with_definitions


def _substitutions(variables: tuple[ir.Variable, ...], terms_by_sort: dict[str, tuple[ir.Term, ...]]):
    if not variables:
        yield {}
        return
    domains = [terms_by_sort[variable.sort] for variable in variables]
    for values in product(*domains):
        yield {variable.name: value for variable, value in zip(variables, values)}


def _jaccard(left: set[object], right: set[object]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def _average(values: list[float]) -> float:
    if not values:
        return 1.0
    return sum(values) / len(values)


def _parameter_signature(definition: ir.Definition) -> tuple[str, ...]:
    return tuple(parameter.sort for parameter in definition.parameters)


def _definition_extension(
    definition: ir.Definition,
    closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
) -> set[tuple[str, ...]]:
    extension: set[tuple[str, ...]] = set()
    domains = [closure.terms_by_sort[parameter.sort] for parameter in definition.parameters]
    for values in product(*domains):
        mapping = {parameter.name: value for parameter, value in zip(definition.parameters, values)}
        head = normalize_atom(definition.head_atom().substitute(mapping), rewrites)
        if head in closure.derivations:
            extension.add(tuple(str(term.to_dict()) for term in head.terms))
    return extension


def _match_definition_semantics_one_way(
    source_definitions: tuple[ir.Definition, ...],
    target_definitions: tuple[ir.Definition, ...],
    source_closure: ProofResult,
    target_closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
) -> tuple[float, dict[str, str]]:
    if not source_definitions and not target_definitions:
        return 1.0, {}
    if not source_definitions or not target_definitions:
        return 0.0, {}

    source_extensions = [_definition_extension(definition, source_closure, rewrites) for definition in source_definitions]
    target_extensions = [_definition_extension(definition, target_closure, rewrites) for definition in target_definitions]

    candidates: list[tuple[float, int, int]] = []
    for source_index, source_definition in enumerate(source_definitions):
        source_signature = _parameter_signature(source_definition)
        for target_index, target_definition in enumerate(target_definitions):
            if source_signature != _parameter_signature(target_definition):
                continue
            score = _jaccard(source_extensions[source_index], target_extensions[target_index])
            candidates.append((score, source_index, target_index))

    matched_source: set[int] = set()
    matched_target: set[int] = set()
    mapping: dict[str, str] = {}
    total = 0.0
    for score, source_index, target_index in sorted(candidates, reverse=True):
        if source_index in matched_source or target_index in matched_target:
            continue
        matched_source.add(source_index)
        matched_target.add(target_index)
        total += score
        mapping[target_definitions[target_index].name] = source_definitions[source_index].name
    return total / len(source_definitions), mapping


def match_definition_semantics(
    gold_definitions: tuple[ir.Definition, ...],
    candidate_definitions: tuple[ir.Definition, ...],
    gold_closure: ProofResult,
    candidate_closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
) -> tuple[float, dict[str, str]]:
    """Match candidate definitions to gold definitions by bounded extension overlap."""

    forward_score, mapping = _match_definition_semantics_one_way(
        gold_definitions,
        candidate_definitions,
        gold_closure,
        candidate_closure,
        rewrites,
    )
    reverse_score, _ = _match_definition_semantics_one_way(
        candidate_definitions,
        gold_definitions,
        candidate_closure,
        gold_closure,
        rewrites,
    )
    return 0.5 * (forward_score + reverse_score), mapping


def _translate_atom(atom: ir.Atom, predicate_mapping: dict[str, str]) -> ir.Atom:
    if atom.predicate == "=":
        return atom
    return ir.Atom(predicate_mapping.get(atom.predicate, atom.predicate), atom.terms)


def _clause_consequence_set(
    clause: ir.HornClause,
    closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
    predicate_mapping: dict[str, str] | None = None,
) -> set[str]:
    predicate_mapping = predicate_mapping or {}
    consequences: set[str] = set()
    for mapping in _substitutions(clause.variables, closure.terms_by_sort):
        premises = tuple(normalize_atom(atom.substitute(mapping), rewrites) for atom in clause.premises)
        if all(atom in closure.derivations for atom in premises):
            conclusion = normalize_atom(clause.conclusion.substitute(mapping), rewrites)
            consequences.add(str(_translate_atom(conclusion, predicate_mapping).to_dict()))
    return consequences


def _match_clause_semantics_one_way(
    source_clauses: tuple[ir.HornClause, ...],
    target_clauses: tuple[ir.HornClause, ...],
    source_closure: ProofResult,
    target_closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
    predicate_mapping: dict[str, str],
) -> float:
    if not source_clauses and not target_clauses:
        return 1.0
    if not source_clauses or not target_clauses:
        return 0.0

    source_sets = [_clause_consequence_set(clause, source_closure, rewrites) for clause in source_clauses]
    target_sets = [
        _clause_consequence_set(clause, target_closure, rewrites, predicate_mapping) for clause in target_clauses
    ]

    candidates: list[tuple[float, int, int]] = []
    for source_index, source_clause in enumerate(source_clauses):
        for target_index, target_clause in enumerate(target_clauses):
            if len(source_clause.variables) != len(target_clause.variables):
                continue
            score = _jaccard(source_sets[source_index], target_sets[target_index])
            candidates.append((score, source_index, target_index))

    matched_source: set[int] = set()
    matched_target: set[int] = set()
    total = 0.0
    for score, source_index, target_index in sorted(candidates, reverse=True):
        if source_index in matched_source or target_index in matched_target:
            continue
        matched_source.add(source_index)
        matched_target.add(target_index)
        total += score
    return total / len(source_clauses)


def match_clause_semantics(
    gold_clauses: tuple[ir.HornClause, ...],
    candidate_clauses: tuple[ir.HornClause, ...],
    gold_closure: ProofResult,
    candidate_closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
    predicate_mapping: dict[str, str],
) -> float:
    """Match candidate clauses to gold clauses by bounded consequence overlap."""

    forward_score = _match_clause_semantics_one_way(
        gold_clauses,
        candidate_clauses,
        gold_closure,
        candidate_closure,
        rewrites,
        predicate_mapping,
    )
    reverse_score = _match_clause_semantics_one_way(
        candidate_clauses,
        gold_clauses,
        candidate_closure,
        gold_closure,
        rewrites,
        {},
    )
    return 0.5 * (forward_score + reverse_score)


def visible_goal_agreement_score(
    goals: tuple[ir.Goal, ...],
    gold_closure: ProofResult,
    candidate_closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
) -> float | None:
    """Compare visible-goal behavior between two closures."""

    if not goals:
        return None
    scores: list[float] = []
    for goal in goals:
        gold_cost = goal_cost(gold_closure.derivations, goal.atoms, rewrites)
        candidate_cost = goal_cost(candidate_closure.derivations, goal.atoms, rewrites)
        if gold_cost is None and candidate_cost is None:
            scores.append(1.0)
            continue
        if gold_cost is None or candidate_cost is None:
            scores.append(0.0)
            continue
        gold_within_budget = goal.budget is None or gold_cost <= goal.budget
        candidate_within_budget = goal.budget is None or candidate_cost <= goal.budget
        distance = abs(gold_cost - candidate_cost)
        cost_agreement = max(0.0, 1.0 - (distance / max(gold_cost, candidate_cost, 1)))
        score = 0.4
        if gold_within_budget == candidate_within_budget:
            score += 0.3
        score += 0.3 * cost_agreement
        scores.append(score)
    return _average(scores)


def _semantic_component_score(
    world: ir.World,
    candidate: ir.Document,
    gold_closure: ProofResult,
    candidate_closure: ProofResult,
) -> float:
    components: list[float] = []
    predicate_mapping: dict[str, str] = {}
    if world.hidden_bridge.definitions or candidate.definitions:
        definition_score, predicate_mapping = match_definition_semantics(
            world.hidden_bridge.definitions,
            candidate.definitions,
            gold_closure,
            candidate_closure,
            world.rewrites,
        )
        components.append(definition_score)
    if world.hidden_bridge.lemmas or candidate.lemmas or candidate.theorems:
        clause_score = match_clause_semantics(
            world.hidden_bridge.lemmas,
            candidate.lemmas + candidate.theorems,
            gold_closure,
            candidate_closure,
            world.rewrites,
            predicate_mapping,
        )
        components.append(clause_score)
    goal_score = visible_goal_agreement_score(
        world.targets_visible,
        gold_closure,
        candidate_closure,
        world.rewrites,
    )
    if goal_score is not None:
        components.append(goal_score)
    if not components:
        return 0.0
    return sum(components) / len(components)


def semantic_equivalence_score(
    world: ir.World,
    candidate: ir.Document,
    candidate_signature: ir.Signature,
    candidate_closure: ProofResult,
    *,
    backend: BackendConfig | None = None,
) -> float:
    """Compare hidden and candidate bridges across the public model suite.

    The original implementation only inspected the packaged world itself. This
    pass keeps that baseline but also checks nearby public worlds produced by
    small ablations of visible facts or visible theorems. A candidate that only
    looks equivalent because of an accident in the original packaged world
    should now score lower than one that remains aligned across the suite.
    """

    backend = backend or BackendConfig()
    max_term_depth = int(world.metadata.get("max_term_depth", 3))
    gold_signature = extend_signature_with_definitions(world.signature, world.hidden_bridge.definitions)
    gold_closure = build_closure_with_backend(
        gold_signature,
        facts=world.visible_facts,
        clauses=world.public_clauses() + world.hidden_bridge.lemmas,
        definitions=world.hidden_bridge.definitions,
        rewrites=world.rewrites,
        max_term_depth=max_term_depth,
        backend=backend,
    )

    baseline_score = _semantic_component_score(world, candidate, gold_closure, candidate_closure)

    suite_scores: list[float] = []
    for model in public_diagnostic_models(world)[1:]:
        gold_diagnostic_closure = build_closure_with_backend(
            gold_signature,
            facts=model.facts,
            clauses=model.clauses + world.hidden_bridge.lemmas,
            definitions=world.hidden_bridge.definitions,
            rewrites=model.rewrites,
            max_term_depth=model.max_term_depth,
            backend=backend,
        )
        candidate_diagnostic_closure = build_closure_with_backend(
            candidate_signature,
            facts=model.facts,
            clauses=model.clauses + candidate.lemmas + candidate.theorems,
            definitions=candidate.definitions,
            rewrites=model.rewrites,
            max_term_depth=model.max_term_depth,
            backend=backend,
        )
        suite_scores.append(
            _semantic_component_score(
                world,
                candidate,
                gold_diagnostic_closure,
                candidate_diagnostic_closure,
            )
        )

    if not suite_scores:
        return baseline_score
    return 0.5 * baseline_score + 0.5 * (sum(suite_scores) / len(suite_scores))
