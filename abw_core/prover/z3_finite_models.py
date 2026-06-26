# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Optional Z3-backed finite-model search for ABW diagnostic queries.

The shipped local prover computes the bounded least model and proof traces used
for scoring. This module serves a different role: it searches for finite
first-order models over the bounded term palette, which can expose clause
counterexamples that the least-model check cannot witness. That makes it a
useful external-solver upgrade without pretending to replace the derivation
graph the scorer already depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from itertools import count, product
from typing import Any, Iterator

from abw_core import ir
from abw_core.prover.countermodels import BoundedCountermodel
from abw_core.prover.horn import build_closure
from abw_core.prover.rewrite import normalize_atom

_MODEL_TOKEN = count()


@dataclass(frozen=True)
class _Encoding:
    """Finite-model search state for one signature and bounded term palette."""

    z3: Any
    solver: Any
    signature: ir.Signature
    terms_by_sort: dict[str, tuple[ir.Term, ...]]
    sort_values: dict[str, tuple[Any, ...]]
    term_values: dict[ir.Term, Any]
    function_decls: dict[str, Any]
    predicate_decls: dict[str, Any]


def z3_is_available() -> bool:
    """Return whether the optional Z3 Python bindings can be imported."""

    try:
        importlib.import_module("z3")
    except ImportError:
        return False
    return True


def require_z3() -> Any:
    """Import the optional Z3 bindings or raise a user-facing guidance error."""

    try:
        return importlib.import_module("z3")
    except ImportError as error:  # pragma: no cover - exercised through call sites
        raise RuntimeError(
            "The `z3` backend requires the optional `z3-solver` dependency. "
            "Install it with `python -m uv sync --extra validation` "
            "or `python -m pip install z3-solver`."
        ) from error


def _normalized_fact(fact: ir.Fact, rewrites: tuple[ir.RewriteRule, ...]) -> ir.Fact:
    return ir.Fact(fact.name, normalize_atom(fact.atom, rewrites))


def _normalized_clause(clause: ir.HornClause, rewrites: tuple[ir.RewriteRule, ...]) -> ir.HornClause:
    return ir.HornClause(
        name=clause.name,
        variables=clause.variables,
        premises=tuple(normalize_atom(atom, rewrites) for atom in clause.premises),
        conclusion=normalize_atom(clause.conclusion, rewrites),
    )


def _normalized_definition(definition: ir.Definition, rewrites: tuple[ir.RewriteRule, ...]) -> ir.Definition:
    return ir.Definition(
        name=definition.name,
        parameters=definition.parameters,
        body=tuple(normalize_atom(atom, rewrites) for atom in definition.body),
    )


def _bounded_term_palette(
    signature: ir.Signature,
    rewrites: tuple[ir.RewriteRule, ...],
    max_term_depth: int,
) -> dict[str, tuple[ir.Term, ...]]:
    palette = build_closure(
        signature,
        facts=(),
        clauses=(),
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    ).terms_by_sort
    domains: dict[str, tuple[ir.Term, ...]] = {}
    for sort in signature.sorts:
        terms = palette.get(sort.name, ())
        if not terms:
            terms = (ir.ConstTerm(f"model_{sort.name.lower()}_0"),)
        domains[sort.name] = terms
    return domains


def _encode(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    rewrites: tuple[ir.RewriteRule, ...],
    max_term_depth: int,
) -> _Encoding:
    z3 = require_z3()
    token = next(_MODEL_TOKEN)
    terms_by_sort = _bounded_term_palette(signature, rewrites, max_term_depth)
    solver = z3.Solver()
    solver.set("timeout", 15000)

    sort_refs: dict[str, Any] = {}
    sort_values: dict[str, tuple[Any, ...]] = {}
    term_values: dict[ir.Term, Any] = {}
    for sort_name, terms in terms_by_sort.items():
        sort_ref, values = z3.EnumSort(
            f"ABW_{sort_name}_{token}",
            [f"abw_{token}_{sort_name}_{index}" for index in range(len(terms))],
        )
        sort_refs[sort_name] = sort_ref
        sort_values[sort_name] = tuple(values)
        for term, value in zip(terms, values):
            term_values[term] = value

    function_decls = {
        function.name: z3.Function(
            function.name,
            *(sort_refs[sort] for sort in function.input_sorts),
            sort_refs[function.output_sort],
        )
        for function in signature.functions
    }
    predicate_decls = {
        predicate.name: z3.Function(
            predicate.name,
            *(sort_refs[sort] for sort in predicate.input_sorts),
            z3.BoolSort(),
        )
        for predicate in signature.predicates
    }

    encoding = _Encoding(
        z3=z3,
        solver=solver,
        signature=signature,
        terms_by_sort=terms_by_sort,
        sort_values=sort_values,
        term_values=term_values,
        function_decls=function_decls,
        predicate_decls=predicate_decls,
    )

    normalized_facts = tuple(_normalized_fact(fact, rewrites) for fact in facts)
    normalized_clauses = tuple(_normalized_clause(clause, rewrites) for clause in clauses)
    normalized_definitions = tuple(_normalized_definition(definition, rewrites) for definition in definitions)

    for fact in normalized_facts:
        solver.add(_atom_expr(fact.atom, {}, encoding))

    for definition in normalized_definitions:
        for _, env in _ground_environments(definition.parameters, encoding):
            body = [_atom_expr(atom, env, encoding) for atom in definition.body]
            solver.add(_atom_expr(definition.head_atom(), env, encoding) == encoding.z3.And(body))

    for clause in normalized_clauses:
        for _, env in _ground_environments(clause.variables, encoding):
            premises = [_atom_expr(atom, env, encoding) for atom in clause.premises]
            conclusion = _atom_expr(clause.conclusion, env, encoding)
            if premises:
                solver.add(encoding.z3.Implies(encoding.z3.And(premises), conclusion))
            else:
                solver.add(conclusion)

    return encoding


def _ground_environments(
    variables: tuple[ir.Variable, ...],
    encoding: _Encoding,
) -> Iterator[tuple[dict[str, ir.Term], dict[str, Any]]]:
    if not variables:
        yield {}, {}
        return
    domains = [tuple(zip(encoding.terms_by_sort[variable.sort], encoding.sort_values[variable.sort])) for variable in variables]
    for values in product(*domains):
        term_mapping = {
            variable.name: term
            for variable, (term, _) in zip(variables, values)
        }
        env = {
            variable.name: element
            for variable, (_, element) in zip(variables, values)
        }
        yield term_mapping, env


def _term_expr(term: ir.Term, env: dict[str, Any], encoding: _Encoding) -> Any:
    if isinstance(term, ir.VarTerm):
        return env[term.variable.name]
    if isinstance(term, ir.ConstTerm):
        for constant in encoding.signature.constants:
            if constant.name == term.name:
                return encoding.term_values[ir.ConstTerm(constant.name)]
        if term in encoding.term_values:
            return encoding.term_values[term]
        raise ValueError(f"Unknown constant term {term.name!r} in Z3 translation.")
    if isinstance(term, ir.FuncTerm):
        return encoding.function_decls[term.name](*(_term_expr(argument, env, encoding) for argument in term.args))
    raise TypeError(f"Unsupported term type {type(term)!r}.")


def _atom_expr(atom: ir.Atom, env: dict[str, Any], encoding: _Encoding) -> Any:
    if atom.predicate == "=":
        left, right = atom.terms
        return _term_expr(left, env, encoding) == _term_expr(right, env, encoding)
    predicate = encoding.predicate_decls[atom.predicate]
    arguments = tuple(_term_expr(term, env, encoding) for term in atom.terms)
    return predicate(*arguments) if arguments else predicate()


def _model_truth(model: Any, expr: Any, z3: Any) -> bool:
    return z3.is_true(model.eval(expr, model_completion=True))


def _predicate_extensions(encoding: _Encoding, model: Any) -> dict[str, tuple[tuple[ir.Term, ...], ...]]:
    extensions: dict[str, tuple[tuple[ir.Term, ...], ...]] = {}
    for predicate in encoding.signature.predicates:
        tuples: list[tuple[ir.Term, ...]] = []
        domains = [tuple(zip(encoding.terms_by_sort[sort], encoding.sort_values[sort])) for sort in predicate.input_sorts]
        for values in product(*domains) if domains else [()]:
            terms = tuple(term for term, _ in values)
            exprs = tuple(expr for _, expr in values)
            expr = encoding.predicate_decls[predicate.name](*exprs) if exprs else encoding.predicate_decls[predicate.name]()
            if _model_truth(model, expr, encoding.z3):
                tuples.append(terms)
        extensions[predicate.name] = tuple(tuples)
    return extensions


def _countermodel_payload(
    label: str,
    goal_atoms: tuple[ir.Atom, ...],
    encoding: _Encoding,
    model: Any,
) -> dict[str, Any] | None:
    truth_values = [
        _model_truth(model, _atom_expr(atom, {}, encoding), encoding.z3)
        for atom in goal_atoms
    ]
    true_atoms = tuple(atom for atom, truth in zip(goal_atoms, truth_values) if truth)
    false_atoms = tuple(atom for atom, truth in zip(goal_atoms, truth_values) if not truth)
    if not false_atoms:
        return None
    predicate_extensions = _predicate_extensions(encoding, model)
    countermodel = BoundedCountermodel(
        label=label,
        sort_domains=encoding.terms_by_sort,
        predicate_extensions=predicate_extensions,
        true_atoms=true_atoms,
        false_atoms=false_atoms,
        derived_atom_count=sum(len(extension) for extension in predicate_extensions.values()),
    )
    payload = countermodel.to_dict()
    payload["backend"] = "z3"
    payload["model_kind"] = "finite"
    return payload


def find_goal_countermodel_via_z3(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    goal_atoms: tuple[ir.Atom, ...],
    *,
    definitions: tuple[ir.Definition, ...] = (),
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    label: str = "",
) -> dict[str, Any] | None:
    """Search for a finite model where at least one queried atom is false."""

    normalized_goals = tuple(normalize_atom(atom, rewrites) for atom in goal_atoms)
    encoding = _encode(
        signature,
        facts=facts,
        clauses=clauses,
        definitions=definitions,
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    )
    goal_exprs = tuple(_atom_expr(atom, {}, encoding) for atom in normalized_goals)
    if not goal_exprs:
        return None
    encoding.solver.push()
    encoding.solver.add(encoding.z3.Or([encoding.z3.Not(expr) for expr in goal_exprs]))
    result = encoding.solver.check()
    if result != encoding.z3.sat:
        encoding.solver.pop()
        return None
    model = encoding.solver.model()
    payload = _countermodel_payload(label, normalized_goals, encoding, model)
    encoding.solver.pop()
    return payload


def find_clause_counterexamples_via_z3(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    base_clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    clause: ir.HornClause,
    *,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    max_term_depth: int = 3,
    limit: int = 4,
) -> tuple[dict[str, Any], ...]:
    """Search for finite-model clause counterexamples over the bounded term palette."""

    normalized_clause = _normalized_clause(clause, rewrites)
    encoding = _encode(
        signature,
        facts=facts,
        clauses=base_clauses,
        definitions=definitions,
        rewrites=rewrites,
        max_term_depth=max_term_depth,
    )
    counterexamples: list[dict[str, Any]] = []
    for substitution, env in _ground_environments(normalized_clause.variables, encoding):
        encoding.solver.push()
        premises = tuple(_atom_expr(atom, env, encoding) for atom in normalized_clause.premises)
        conclusion = _atom_expr(normalized_clause.conclusion, env, encoding)
        if premises:
            encoding.solver.add(encoding.z3.And(premises))
        encoding.solver.add(encoding.z3.Not(conclusion))
        result = encoding.solver.check()
        if result == encoding.z3.sat:
            grounded_premises = tuple(atom.substitute(substitution) for atom in normalized_clause.premises)
            missing_conclusion = normalized_clause.conclusion.substitute(substitution)
            rendered_substitution = {
                name: term.to_dict()
                for name, term in substitution.items()
            }
            counterexamples.append(
                {
                    "clause": normalized_clause.name,
                    "substitution": rendered_substitution,
                    "premises": [atom.to_dict() for atom in grounded_premises],
                    "missing_conclusion": missing_conclusion.to_dict(),
                    "message": (
                        f"Clause {normalized_clause.name!r} fails in one finite model for substitution "
                        f"{rendered_substitution}: premises can hold while {missing_conclusion.to_dict()} does not."
                    ),
                    "backend": "z3",
                    "model_kind": "finite",
                }
            )
            if len(counterexamples) >= limit:
                encoding.solver.pop()
                break
        encoding.solver.pop()
    return tuple(counterexamples)
