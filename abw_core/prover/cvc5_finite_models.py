# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Optional cvc5-backed finite-model search for ABW diagnostic queries.

This backend plays the same role as the Z3 integration: it does not replace the
local proof-cost engine, but it does strengthen diagnostic queries by searching
for finite first-order models over the bounded term palette that ABW already
uses for local reasoning and packaging.
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

    cvc5: Any
    solver: Any
    signature: ir.Signature
    terms_by_sort: dict[str, tuple[ir.Term, ...]]
    sort_refs: dict[str, Any]
    term_values: dict[ir.Term, Any]
    function_decls: dict[str, Any]
    predicate_decls: dict[str, Any]


def cvc5_is_available() -> bool:
    """Return whether the optional cvc5 Python bindings can be imported."""

    try:
        importlib.import_module("cvc5")
    except ImportError:
        return False
    return True


def require_cvc5() -> Any:
    """Import the optional cvc5 bindings or raise a user-facing guidance error."""

    try:
        return importlib.import_module("cvc5")
    except ImportError as error:  # pragma: no cover - exercised through call sites
        raise RuntimeError(
            "The `cvc5` backend requires the optional `cvc5` dependency. "
            "Install it with `python -m uv sync --extra validation` "
            "or `python -m pip install cvc5`."
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


def _ground_environments(
    variables: tuple[ir.Variable, ...],
    encoding: _Encoding,
) -> Iterator[tuple[dict[str, ir.Term], dict[str, Any]]]:
    if not variables:
        yield {}, {}
        return
    domains = [tuple((term, encoding.term_values[term]) for term in encoding.terms_by_sort[variable.sort]) for variable in variables]
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


def _and_term(solver: Any, cvc5: Any, terms: list[Any]) -> Any:
    if not terms:
        return solver.mkBoolean(True)
    if len(terms) == 1:
        return terms[0]
    return solver.mkTerm(cvc5.Kind.AND, *terms)


def _or_term(solver: Any, cvc5: Any, terms: list[Any]) -> Any:
    if not terms:
        return solver.mkBoolean(False)
    if len(terms) == 1:
        return terms[0]
    return solver.mkTerm(cvc5.Kind.OR, *terms)


def _encode(
    signature: ir.Signature,
    facts: tuple[ir.Fact, ...],
    clauses: tuple[ir.HornClause, ...],
    definitions: tuple[ir.Definition, ...],
    rewrites: tuple[ir.RewriteRule, ...],
    max_term_depth: int,
) -> _Encoding:
    cvc5 = require_cvc5()
    token = next(_MODEL_TOKEN)
    terms_by_sort = _bounded_term_palette(signature, rewrites, max_term_depth)

    solver = cvc5.Solver()
    solver.setLogic("ALL")
    solver.setOption("produce-models", "true")

    sort_refs: dict[str, Any] = {}
    term_values: dict[ir.Term, Any] = {}
    for sort_name, terms in terms_by_sort.items():
        datatype_decl = solver.mkDatatypeDecl(f"ABW_{sort_name}_{token}")
        constructor_names: list[str] = []
        for index in range(len(terms)):
            ctor_name = f"abw_{token}_{sort_name}_{index}"
            constructor_names.append(ctor_name)
            datatype_decl.addConstructor(solver.mkDatatypeConstructorDecl(ctor_name))
        sort_ref = solver.mkDatatypeSort(datatype_decl)
        sort_refs[sort_name] = sort_ref
        datatype = sort_ref.getDatatype()
        for term, ctor_name in zip(terms, constructor_names):
            term_values[term] = solver.mkTerm(
                cvc5.Kind.APPLY_CONSTRUCTOR,
                datatype.getConstructor(ctor_name).getTerm(),
            )

    function_decls: dict[str, Any] = {}
    for function in signature.functions:
        if not function.input_sorts:
            function_decls[function.name] = solver.mkConst(sort_refs[function.output_sort], function.name)
            continue
        function_decls[function.name] = solver.mkConst(
            solver.mkFunctionSort([sort_refs[sort] for sort in function.input_sorts], sort_refs[function.output_sort]),
            function.name,
        )

    predicate_decls: dict[str, Any] = {}
    for predicate in signature.predicates:
        if not predicate.input_sorts:
            predicate_decls[predicate.name] = solver.mkConst(solver.getBooleanSort(), predicate.name)
            continue
        predicate_decls[predicate.name] = solver.mkConst(
            solver.mkFunctionSort([sort_refs[sort] for sort in predicate.input_sorts], solver.getBooleanSort()),
            predicate.name,
        )

    encoding = _Encoding(
        cvc5=cvc5,
        solver=solver,
        signature=signature,
        terms_by_sort=terms_by_sort,
        sort_refs=sort_refs,
        term_values=term_values,
        function_decls=function_decls,
        predicate_decls=predicate_decls,
    )

    normalized_facts = tuple(_normalized_fact(fact, rewrites) for fact in facts)
    normalized_clauses = tuple(_normalized_clause(clause, rewrites) for clause in clauses)
    normalized_definitions = tuple(_normalized_definition(definition, rewrites) for definition in definitions)

    for fact in normalized_facts:
        solver.assertFormula(_atom_expr(fact.atom, {}, encoding))

    for definition in normalized_definitions:
        for _, env in _ground_environments(definition.parameters, encoding):
            body = [_atom_expr(atom, env, encoding) for atom in definition.body]
            solver.assertFormula(
                _atom_expr(definition.head_atom(), env, encoding).eqTerm(_and_term(solver, cvc5, body))
            )

    for clause in normalized_clauses:
        for _, env in _ground_environments(clause.variables, encoding):
            premises = [_atom_expr(atom, env, encoding) for atom in clause.premises]
            conclusion = _atom_expr(clause.conclusion, env, encoding)
            if premises:
                solver.assertFormula(solver.mkTerm(cvc5.Kind.IMPLIES, _and_term(solver, cvc5, premises), conclusion))
            else:
                solver.assertFormula(conclusion)

    return encoding


def _term_expr(term: ir.Term, env: dict[str, Any], encoding: _Encoding) -> Any:
    if isinstance(term, ir.VarTerm):
        return env[term.variable.name]
    if isinstance(term, ir.ConstTerm):
        for constant in encoding.signature.constants:
            if constant.name == term.name:
                return encoding.term_values[ir.ConstTerm(constant.name)]
        if term in encoding.term_values:
            return encoding.term_values[term]
        raise ValueError(f"Unknown constant term {term.name!r} in cvc5 translation.")
    if isinstance(term, ir.FuncTerm):
        function = encoding.function_decls[term.name]
        if not term.args:
            return function
        return encoding.solver.mkTerm(
            encoding.cvc5.Kind.APPLY_UF,
            function,
            *(_term_expr(argument, env, encoding) for argument in term.args),
        )
    raise TypeError(f"Unsupported term type {type(term)!r}.")


def _atom_expr(atom: ir.Atom, env: dict[str, Any], encoding: _Encoding) -> Any:
    if atom.predicate == "=":
        left, right = atom.terms
        return _term_expr(left, env, encoding).eqTerm(_term_expr(right, env, encoding))
    predicate = encoding.predicate_decls[atom.predicate]
    if not atom.terms:
        return predicate
    arguments = tuple(_term_expr(term, env, encoding) for term in atom.terms)
    return encoding.solver.mkTerm(encoding.cvc5.Kind.APPLY_UF, predicate, *arguments)


def _model_truth(encoding: _Encoding, expr: Any) -> bool:
    value = encoding.solver.getValue(expr)
    if not value.isBooleanValue():
        raise TypeError("Expected a Boolean cvc5 model value.")
    return bool(value.getBooleanValue())


def _predicate_extensions(encoding: _Encoding) -> dict[str, tuple[tuple[ir.Term, ...], ...]]:
    extensions: dict[str, tuple[tuple[ir.Term, ...], ...]] = {}
    for predicate in encoding.signature.predicates:
        tuples: list[tuple[ir.Term, ...]] = []
        domains = [encoding.terms_by_sort[sort] for sort in predicate.input_sorts]
        for terms in product(*domains) if domains else [()]:
            if terms:
                expr = encoding.solver.mkTerm(
                    encoding.cvc5.Kind.APPLY_UF,
                    encoding.predicate_decls[predicate.name],
                    *(encoding.term_values[term] for term in terms),
                )
            else:
                expr = encoding.predicate_decls[predicate.name]
            if _model_truth(encoding, expr):
                tuples.append(tuple(terms))
        extensions[predicate.name] = tuple(tuples)
    return extensions


def _countermodel_payload(
    label: str,
    goal_atoms: tuple[ir.Atom, ...],
    encoding: _Encoding,
) -> dict[str, Any] | None:
    truth_values = [_model_truth(encoding, _atom_expr(atom, {}, encoding)) for atom in goal_atoms]
    true_atoms = tuple(atom for atom, truth in zip(goal_atoms, truth_values) if truth)
    false_atoms = tuple(atom for atom, truth in zip(goal_atoms, truth_values) if not truth)
    if not false_atoms:
        return None
    predicate_extensions = _predicate_extensions(encoding)
    countermodel = BoundedCountermodel(
        label=label,
        sort_domains=encoding.terms_by_sort,
        predicate_extensions=predicate_extensions,
        true_atoms=true_atoms,
        false_atoms=false_atoms,
        derived_atom_count=sum(len(extension) for extension in predicate_extensions.values()),
    )
    payload = countermodel.to_dict()
    payload["backend"] = "cvc5"
    payload["model_kind"] = "finite"
    return payload


def find_goal_countermodel_via_cvc5(
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
    goal_exprs = [_atom_expr(atom, {}, encoding) for atom in normalized_goals]
    if not goal_exprs:
        return None
    encoding.solver.push()
    encoding.solver.assertFormula(_or_term(encoding.solver, encoding.cvc5, [expr.notTerm() for expr in goal_exprs]))
    result = encoding.solver.checkSat()
    if not result.isSat():
        encoding.solver.pop()
        return None
    payload = _countermodel_payload(label, normalized_goals, encoding)
    encoding.solver.pop()
    return payload


def find_clause_counterexamples_via_cvc5(
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
        premises = [_atom_expr(atom, env, encoding) for atom in normalized_clause.premises]
        conclusion = _atom_expr(normalized_clause.conclusion, env, encoding)
        if premises:
            encoding.solver.assertFormula(_and_term(encoding.solver, encoding.cvc5, premises))
        encoding.solver.assertFormula(conclusion.notTerm())
        result = encoding.solver.checkSat()
        if result.isSat():
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
                    "backend": "cvc5",
                    "model_kind": "finite",
                }
            )
            encoding.solver.pop()
            if len(counterexamples) >= limit:
                break
            continue
        encoding.solver.pop()
    return tuple(counterexamples)
