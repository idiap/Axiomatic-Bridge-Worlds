# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Shared serialization helpers for ABW runtime objects.

These helpers keep the packager and subprocess proof backends on one stable
JSON shape instead of each reimplementing slightly different adapters.
"""

from __future__ import annotations

from typing import Any

from abw_core import ir
from abw_core.prover.horn import ProofResult
from abw_core.prover.proofs import Derivation


def term_to_dict(term: ir.Term) -> dict[str, Any]:
    """Serialize one term into the shared JSON payload format."""

    return term.to_dict()


def term_from_dict(payload: dict[str, Any]) -> ir.Term:
    """Deserialize one term from the shared JSON payload format."""

    kind = payload["kind"]
    if kind == "var":
        variable = payload["variable"]
        return ir.VarTerm(ir.Variable(variable["name"], variable["sort"]))
    if kind == "const":
        return ir.ConstTerm(payload["name"])
    if kind == "func":
        return ir.FuncTerm(payload["name"], tuple(term_from_dict(argument) for argument in payload["args"]))
    raise ValueError(f"Unknown term payload kind {kind!r}.")


def atom_to_dict(atom: ir.Atom) -> dict[str, Any]:
    """Serialize one atom into the shared JSON payload format."""

    return atom.to_dict()


def atom_from_dict(payload: dict[str, Any]) -> ir.Atom:
    """Deserialize one atom from the shared JSON payload format."""

    return ir.Atom(payload["predicate"], tuple(term_from_dict(term) for term in payload["terms"]))


def clause_to_dict(clause: ir.HornClause) -> dict[str, Any]:
    """Serialize one Horn clause into the shared JSON payload format."""

    return clause.to_dict()


def clause_from_dict(payload: dict[str, Any]) -> ir.HornClause:
    """Deserialize one Horn clause from the shared JSON payload format."""

    return ir.HornClause(
        name=payload["name"],
        variables=tuple(ir.Variable(item["name"], item["sort"]) for item in payload["variables"]),
        premises=tuple(atom_from_dict(item) for item in payload["premises"]),
        conclusion=atom_from_dict(payload["conclusion"]),
    )


def rewrite_to_dict(rule: ir.RewriteRule) -> dict[str, Any]:
    """Serialize one rewrite rule into the shared JSON payload format."""

    return rule.to_dict()


def rewrite_from_dict(payload: dict[str, Any]) -> ir.RewriteRule:
    """Deserialize one rewrite rule from the shared JSON payload format."""

    return ir.RewriteRule(
        name=payload["name"],
        lhs=term_from_dict(payload["lhs"]),
        rhs=term_from_dict(payload["rhs"]),
    )


def definition_to_dict(definition: ir.Definition) -> dict[str, Any]:
    """Serialize one definition into the shared JSON payload format."""

    return definition.to_dict()


def definition_from_dict(payload: dict[str, Any]) -> ir.Definition:
    """Deserialize one definition from the shared JSON payload format."""

    return ir.Definition(
        name=payload["name"],
        parameters=tuple(ir.Variable(item["name"], item["sort"]) for item in payload["parameters"]),
        body=tuple(atom_from_dict(item) for item in payload["body"]),
    )


def fact_to_dict(fact: ir.Fact) -> dict[str, Any]:
    """Serialize one fact into the shared JSON payload format."""

    return fact.to_dict()


def fact_from_dict(payload: dict[str, Any]) -> ir.Fact:
    """Deserialize one fact from the shared JSON payload format."""

    return ir.Fact(name=payload["name"], atom=atom_from_dict(payload["atom"]))


def signature_to_dict(signature: ir.Signature) -> dict[str, Any]:
    """Serialize one signature into the shared JSON payload format."""

    return signature.to_dict()


def signature_from_dict(payload: dict[str, Any]) -> ir.Signature:
    """Deserialize one signature from the shared JSON payload format."""

    return ir.Signature(
        sorts=tuple(ir.Sort(item["name"]) for item in payload["sorts"]),
        constants=tuple(ir.ConstantSymbol(item["name"], item["sort"]) for item in payload["constants"]),
        functions=tuple(
            ir.FunctionSymbol(item["name"], tuple(item["input_sorts"]), item["output_sort"])
            for item in payload["functions"]
        ),
        predicates=tuple(ir.PredicateSymbol(item["name"], tuple(item["input_sorts"])) for item in payload["predicates"]),
    )


def derivation_to_dict(derivation: Derivation) -> dict[str, Any]:
    """Serialize one proof derivation into the shared JSON payload format."""

    return {
        "atom": atom_to_dict(derivation.atom),
        "rule_name": derivation.rule_name,
        "rule_kind": derivation.rule_kind,
        "premises": [atom_to_dict(atom) for atom in derivation.premises],
        "step_cost": derivation.step_cost,
        "total_cost": derivation.total_cost,
    }


def derivation_from_dict(payload: dict[str, Any]) -> Derivation:
    """Deserialize one proof derivation from the shared JSON payload format."""

    return Derivation(
        atom=atom_from_dict(payload["atom"]),
        rule_name=payload["rule_name"],
        rule_kind=payload["rule_kind"],
        premises=tuple(atom_from_dict(atom) for atom in payload["premises"]),
        step_cost=int(payload["step_cost"]),
        total_cost=int(payload["total_cost"]),
    )


def proof_result_to_dict(result: ProofResult) -> dict[str, Any]:
    """Serialize a proof result into the shared JSON payload format."""

    return {
        "derivations": [derivation_to_dict(derivation) for derivation in result.derivations.values()],
        "terms_by_sort": {
            sort: [term_to_dict(term) for term in terms]
            for sort, terms in result.terms_by_sort.items()
        },
    }


def proof_result_from_dict(payload: dict[str, Any]) -> ProofResult:
    """Deserialize a proof result from the shared JSON payload format."""

    derivations = [derivation_from_dict(item) for item in payload["derivations"]]
    return ProofResult(
        derivations={derivation.atom: derivation for derivation in derivations},
        terms_by_sort={
            sort: tuple(term_from_dict(term) for term in terms)
            for sort, terms in dict(payload["terms_by_sort"]).items()
        },
    )
