# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Bounded forward chaining over a typed Horn fragment with definitions."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

from abw_core import ir
from abw_core.prover.proofs import Derivation
from abw_core.prover.rewrite import normalize_atom, normalize_term


@dataclass(frozen=True)
class ProofResult:
    """The bounded least closure plus the term domains it ranged over."""

    derivations: dict[ir.Atom, Derivation]
    terms_by_sort: dict[str, tuple[ir.Term, ...]]

    def knows(self, atom: ir.Atom) -> bool:
        """Return whether the closure derives the given atom."""

        return atom in self.derivations


@dataclass(frozen=True)
class ClauseCounterexample:
    """One grounded witness showing why a Horn clause is not sound locally."""

    clause_name: str
    substitution: dict[str, ir.Term]
    premises: tuple[ir.Atom, ...]
    missing_conclusion: ir.Atom

    def message(self) -> str:
        """Render the counterexample in a user-facing diagnostic sentence."""

        rendered_substitution = {
            name: term.to_dict()
            for name, term in self.substitution.items()
        }
        return (
            f"Clause {self.clause_name!r} fails for substitution {rendered_substitution}: "
            f"premises hold but {self.missing_conclusion.to_dict()} does not."
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the counterexample into a JSON-friendly payload."""

        return {
            "clause": self.clause_name,
            "substitution": {
                name: term.to_dict()
                for name, term in self.substitution.items()
            },
            "premises": [atom.to_dict() for atom in self.premises],
            "missing_conclusion": self.missing_conclusion.to_dict(),
            "message": self.message(),
        }


def _enumerate_terms(
    signature: ir.Signature,
    max_term_depth: int,
    rewrites: tuple[ir.RewriteRule, ...],
) -> dict[str, tuple[ir.Term, ...]]:
    by_sort: dict[str, set[ir.Term]] = {sort.name: set() for sort in signature.sorts}
    for constant in signature.constants:
        by_sort[constant.sort].add(normalize_term(ir.ConstTerm(constant.name), rewrites))

    for _ in range(max_term_depth):
        changed = False
        for function in signature.functions:
            domains = [tuple(by_sort[sort]) for sort in function.input_sorts]
            if any(not domain for domain in domains):
                continue
            for arguments in product(*domains):
                term = normalize_term(ir.FuncTerm(function.name, tuple(arguments)), rewrites)
                if term.depth() <= max_term_depth and term not in by_sort[function.output_sort]:
                    by_sort[function.output_sort].add(term)
                    changed = True
        if not changed:
            break

    return {sort: tuple(sorted(terms, key=lambda term: str(term.to_dict()))) for sort, terms in by_sort.items()}


def _substitutions(variables: tuple[ir.Variable, ...], terms_by_sort: dict[str, tuple[ir.Term, ...]]):
    if not variables:
        yield {}
        return
    domains = [terms_by_sort[variable.sort] for variable in variables]
    for values in product(*domains):
        yield {variable.name: value for variable, value in zip(variables, values)}


def _update_derivation(
    derivations: dict[ir.Atom, Derivation],
    atom: ir.Atom,
    rule_name: str | None,
    rule_kind: str,
    premises: tuple[ir.Atom, ...],
    step_cost: int,
) -> bool:
    total_cost = step_cost + sum(derivations[premise].total_cost for premise in premises)
    candidate = Derivation(
        atom=atom,
        rule_name=rule_name,
        rule_kind=rule_kind,
        premises=premises,
        step_cost=step_cost,
        total_cost=total_cost,
    )
    existing = derivations.get(atom)
    if existing is None:
        derivations[atom] = candidate
        return True
    if candidate.total_cost < existing.total_cost:
        derivations[atom] = candidate
        return True
    if candidate.total_cost == existing.total_cost and candidate.step_cost < existing.step_cost:
        derivations[atom] = candidate
        return True
    return False


def build_closure(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...] = (),
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
) -> ProofResult:
    """Compute the bounded least closure for facts, clauses, definitions, and rewrites."""

    terms_by_sort = _enumerate_terms(signature, max_term_depth=max_term_depth, rewrites=rewrites)
    derivations = {
        normalize_atom(fact.atom, rewrites): Derivation(
            atom=normalize_atom(fact.atom, rewrites),
            rule_name=fact.name,
            rule_kind="fact",
            premises=(),
            step_cost=0,
            total_cost=0,
        )
        for fact in facts
    }

    for terms in terms_by_sort.values():
        for term in terms:
            equality = ir.Atom("=", (term, term))
            derivations.setdefault(
                equality,
                Derivation(
                    atom=equality,
                    rule_name="rewrite_reflexive",
                    rule_kind="equality",
                    premises=(),
                    step_cost=0,
                    total_cost=0,
                ),
            )

    changed = True
    while changed:
        changed = False

        for definition in definitions:
            for mapping in _substitutions(definition.parameters, terms_by_sort):
                body = tuple(normalize_atom(atom.substitute(mapping), rewrites) for atom in definition.body)
                if all(atom in derivations for atom in body):
                    head = normalize_atom(definition.head_atom().substitute(mapping), rewrites)
                    changed |= _update_derivation(
                        derivations,
                        head,
                        f"define {definition.name}",
                        "definition_intro",
                        body,
                        step_cost=0,
                    )

        for definition in definitions:
            for mapping in _substitutions(definition.parameters, terms_by_sort):
                head = normalize_atom(definition.head_atom().substitute(mapping), rewrites)
                if head not in derivations:
                    continue
                for atom in definition.body:
                    body_atom = normalize_atom(atom.substitute(mapping), rewrites)
                    changed |= _update_derivation(
                        derivations,
                        body_atom,
                        f"expand {definition.name}",
                        "definition_elim",
                        (head,),
                        step_cost=0,
                    )

        for clause in clauses:
            for mapping in _substitutions(clause.variables, terms_by_sort):
                premises = tuple(normalize_atom(atom.substitute(mapping), rewrites) for atom in clause.premises)
                if all(atom in derivations for atom in premises):
                    conclusion = normalize_atom(clause.conclusion.substitute(mapping), rewrites)
                    changed |= _update_derivation(
                        derivations,
                        conclusion,
                        clause.name,
                        "clause",
                        premises,
                        step_cost=1,
                    )

    return ProofResult(derivations=derivations, terms_by_sort=terms_by_sort)


def validate_clause_soundness(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    base_clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    clause: ir.HornClause,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
) -> list[str]:
    """Check one clause against the bounded public world and return failure messages."""

    return [item.message() for item in find_clause_counterexamples(
        signature=signature,
        facts=facts,
        base_clauses=base_clauses,
        definitions=definitions,
        clause=clause,
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    )]


def find_clause_counterexamples(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    base_clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    clause: ir.HornClause,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
) -> tuple[ClauseCounterexample, ...]:
    """Return grounded witnesses for local clause failures within the bounded world.

    The witness is not a full finite model; it is a concrete bounded
    substitution where the clause premises hold in the public closure but the
    conclusion does not.
    """

    closure = build_closure(
        signature,
        facts=facts,
        clauses=base_clauses,
        definitions=definitions,
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    )
    failures: list[ClauseCounterexample] = []

    def within_depth(atom: ir.Atom) -> bool:
        return all(term.depth() <= max_term_depth for term in atom.terms)

    for mapping in _substitutions(clause.variables, closure.terms_by_sort):
        premises = tuple(normalize_atom(atom.substitute(mapping), rewrites) for atom in clause.premises)
        if not all(atom in closure.derivations for atom in premises):
            continue
        conclusion = normalize_atom(clause.conclusion.substitute(mapping), rewrites)
        if not within_depth(conclusion):
            continue
        if conclusion not in closure.derivations:
            failures.append(
                ClauseCounterexample(
                    clause_name=clause.name,
                    substitution=dict(mapping),
                    premises=premises,
                    missing_conclusion=conclusion,
                )
            )
    return tuple(failures)
