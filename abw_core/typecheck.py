# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Typechecking and boundary validation for ABW documents and worlds."""

from __future__ import annotations

import re
from typing import Any, Iterable

from abw_core import ir


class TypecheckError(ValueError):
    """Raised when a document or world violates the ABW type discipline."""


def _ensure_unique(names: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise TypecheckError(f"Duplicate {label} name {name!r}.")
        seen.add(name)


def build_signature(document: ir.Document) -> ir.Signature:
    """Build and validate the declared signature for one document."""

    sort_names = [sort.name for sort in document.sorts]
    _ensure_unique(sort_names, "sort")
    _ensure_unique((constant.name for constant in document.constants), "constant")
    _ensure_unique((function.name for function in document.functions), "function")
    _ensure_unique((predicate.name for predicate in document.predicates), "predicate")

    known_sorts = set(sort_names)
    for constant in document.constants:
        if constant.sort not in known_sorts:
            raise TypecheckError(f"Constant {constant.name!r} refers to unknown sort {constant.sort!r}.")
    for function in document.functions:
        for sort in function.input_sorts + (function.output_sort,):
            if sort not in known_sorts:
                raise TypecheckError(f"Function {function.name!r} refers to unknown sort {sort!r}.")
    for predicate in document.predicates:
        for sort in predicate.input_sorts:
            if sort not in known_sorts:
                raise TypecheckError(f"Predicate {predicate.name!r} refers to unknown sort {sort!r}.")
    return document.signature()


def extend_signature_with_definitions(signature: ir.Signature, definitions: tuple[ir.Definition, ...]) -> ir.Signature:
    """Extend a signature with the predicate symbols introduced by definitions."""

    used_names = signature.all_symbol_names()
    extended = signature
    for definition in definitions:
        if definition.name in used_names:
            raise TypecheckError(f"Definition name {definition.name!r} conflicts with an existing symbol.")
        predicate = ir.PredicateSymbol(definition.name, tuple(parameter.sort for parameter in definition.parameters))
        extended = extended.with_predicate(predicate)
        used_names.add(definition.name)
    return extended


def _infer_term_sort(
    term: ir.Term,
    signature: ir.Signature,
    scope: dict[str, str],
    *,
    expected_sort: str | None = None,
) -> str:
    if isinstance(term, ir.VarTerm):
        variable_name = term.variable.name
        existing = scope.get(variable_name)
        declared = term.variable.sort
        if existing is None:
            inferred = expected_sort or (declared if declared != "_" else None)
            if inferred is None:
                raise TypecheckError(f"Could not infer a sort for variable {variable_name!r}.")
            scope[variable_name] = inferred
            existing = inferred
        if expected_sort is not None and existing != expected_sort:
            raise TypecheckError(
                f"Variable {variable_name!r} expected sort {expected_sort!r}, found {existing!r}."
            )
        if declared not in {"_", existing}:
            raise TypecheckError(
                f"Variable {variable_name!r} was declared as {declared!r} but inferred as {existing!r}."
            )
        return existing

    if isinstance(term, ir.ConstTerm):
        constant = signature.constant_map().get(term.name)
        if constant is None:
            raise TypecheckError(f"Unknown constant {term.name!r}.")
        if expected_sort is not None and constant.sort != expected_sort:
            raise TypecheckError(f"Constant {term.name!r} expected sort {expected_sort!r}, found {constant.sort!r}.")
        return constant.sort

    if isinstance(term, ir.FuncTerm):
        function = signature.function_map().get(term.name)
        if function is None:
            raise TypecheckError(f"Unknown function {term.name!r}.")
        if expected_sort is not None and function.output_sort != expected_sort:
            raise TypecheckError(
                f"Function {term.name!r} expected output sort {expected_sort!r}, found {function.output_sort!r}."
            )
        if len(function.input_sorts) != len(term.args):
            raise TypecheckError(
                f"Function {term.name!r} expects {len(function.input_sorts)} arguments, found {len(term.args)}."
            )
        for argument, input_sort in zip(term.args, function.input_sorts):
            _infer_term_sort(argument, signature, scope, expected_sort=input_sort)
        return function.output_sort

    raise TypecheckError(f"Unsupported term type: {type(term)!r}.")


def _check_atom(atom: ir.Atom, signature: ir.Signature, scope: dict[str, str]) -> None:
    if atom.predicate == "=":
        if len(atom.terms) != 2:
            raise TypecheckError("Equality atoms must contain exactly two terms.")
        left_sort = _infer_term_sort(atom.terms[0], signature, scope)
        _infer_term_sort(atom.terms[1], signature, scope, expected_sort=left_sort)
        return

    predicate = signature.predicate_map().get(atom.predicate)
    if predicate is None:
        raise TypecheckError(f"Unknown predicate {atom.predicate!r}.")
    if len(predicate.input_sorts) != len(atom.terms):
        raise TypecheckError(
            f"Predicate {atom.predicate!r} expects {len(predicate.input_sorts)} terms, found {len(atom.terms)}."
        )
    for term, expected_sort in zip(atom.terms, predicate.input_sorts):
        _infer_term_sort(term, signature, scope, expected_sort=expected_sort)


def check_clause(clause: ir.HornClause, signature: ir.Signature) -> None:
    """Typecheck one Horn clause against a signature."""

    scope: dict[str, str] = {}
    for variable in clause.variables:
        if variable.name in scope:
            raise TypecheckError(f"Clause {clause.name!r} repeats variable {variable.name!r}.")
        if variable.sort not in signature.sort_names():
            raise TypecheckError(f"Clause {clause.name!r} refers to unknown sort {variable.sort!r}.")
        scope[variable.name] = variable.sort
    for atom in clause.premises:
        _check_atom(atom, signature, scope)
    _check_atom(clause.conclusion, signature, scope)


def check_definition(definition: ir.Definition, base_signature: ir.Signature, full_signature: ir.Signature) -> None:
    """Typecheck one bridge definition against the base and extended signatures."""

    scope: dict[str, str] = {}
    for parameter in definition.parameters:
        if parameter.sort not in base_signature.sort_names():
            raise TypecheckError(
                f"Definition {definition.name!r} refers to unknown sort {parameter.sort!r} in its parameters."
            )
        if parameter.name in scope:
            raise TypecheckError(f"Definition {definition.name!r} repeats parameter {parameter.name!r}.")
        scope[parameter.name] = parameter.sort
    if not definition.body:
        raise TypecheckError(f"Definition {definition.name!r} must contain at least one body atom.")
    for atom in definition.body:
        if atom.predicate == definition.name:
            raise TypecheckError(f"Definition {definition.name!r} is directly recursive.")
        _check_atom(atom, full_signature, scope)


def check_goal(goal: ir.Goal, signature: ir.Signature) -> None:
    """Typecheck one goal conjunction against a signature."""

    scope: dict[str, str] = {}
    for atom in goal.atoms:
        _check_atom(atom, signature, scope)


def check_rewrite(rule: ir.RewriteRule, signature: ir.Signature) -> None:
    """Typecheck one rewrite rule and ensure it preserves sort."""

    scope: dict[str, str] = {}
    lhs_sort = _infer_term_sort(rule.lhs, signature, scope)
    _infer_term_sort(rule.rhs, signature, scope, expected_sort=lhs_sort)
    if isinstance(rule.lhs, ir.VarTerm):
        raise TypecheckError(f"Rewrite {rule.name!r} may not rewrite a bare variable.")


def build_theory_signatures(document: ir.Document) -> dict[str, ir.Signature]:
    """Typecheck and collect the named theory signatures inside a document."""

    theory_signatures: dict[str, ir.Signature] = {}
    for theory in document.theories:
        if theory.name in theory_signatures:
            raise TypecheckError(f"Duplicate theory name {theory.name!r}.")
        theory_signatures[theory.name] = check_document(theory.document)
    return theory_signatures


def _symbol_table(signature: ir.Signature) -> dict[str, tuple[str, Any]]:
    symbols: dict[str, tuple[str, Any]] = {}
    for sort in signature.sorts:
        symbols[sort.name] = ("sort", sort)
    for constant in signature.constants:
        symbols[constant.name] = ("constant", constant)
    for function in signature.functions:
        symbols[function.name] = ("function", function)
    for predicate in signature.predicates:
        symbols[predicate.name] = ("predicate", predicate)
    return symbols


def validate_morphism(
    morphism: ir.SignatureMorphism,
    theory_signatures: dict[str, ir.Signature],
    *,
    require_total: bool = False,
) -> list[str]:
    """Validate a theory morphism against the available source and target signatures."""

    errors: list[str] = []
    source_signature = theory_signatures.get(morphism.source_theory)
    target_signature = theory_signatures.get(morphism.target_theory)
    if source_signature is None:
        return [f"Morphism {morphism.name!r} refers to unknown source theory {morphism.source_theory!r}."]
    if target_signature is None:
        return [f"Morphism {morphism.name!r} refers to unknown target theory {morphism.target_theory!r}."]

    source_symbols = _symbol_table(source_signature)
    target_symbols = _symbol_table(target_signature)

    for source_name, target_name in morphism.mapping.items():
        source_entry = source_symbols.get(source_name)
        if source_entry is None:
            errors.append(f"Morphism {morphism.name!r} maps unknown source symbol {source_name!r}.")
            continue
        target_entry = target_symbols.get(target_name)
        if target_entry is None:
            errors.append(f"Morphism {morphism.name!r} maps to unknown target symbol {target_name!r}.")
            continue

        source_kind, source_symbol = source_entry
        target_kind, target_symbol = target_entry
        if source_kind != target_kind:
            errors.append(
                f"Morphism {morphism.name!r} maps {source_name!r} ({source_kind}) to {target_name!r} ({target_kind})."
            )
            continue

        if source_kind == "sort":
            continue
        if source_kind == "constant":
            mapped_sort = morphism.mapping.get(source_symbol.sort, source_symbol.sort)
            if mapped_sort != target_symbol.sort:
                errors.append(
                    f"Morphism {morphism.name!r} maps constant {source_name!r} to incompatible sort {target_symbol.sort!r}."
                )
            continue
        if source_kind == "function":
            if len(source_symbol.input_sorts) != len(target_symbol.input_sorts):
                errors.append(
                    f"Morphism {morphism.name!r} maps function {source_name!r} to {target_name!r} with different arity."
                )
                continue
            for source_sort, target_sort in zip(source_symbol.input_sorts, target_symbol.input_sorts):
                mapped_sort = morphism.mapping.get(source_sort, source_sort)
                if mapped_sort != target_sort:
                    errors.append(
                        f"Morphism {morphism.name!r} maps function {source_name!r} to incompatible input sorts."
                    )
            mapped_output = morphism.mapping.get(source_symbol.output_sort, source_symbol.output_sort)
            if mapped_output != target_symbol.output_sort:
                errors.append(
                    f"Morphism {morphism.name!r} maps function {source_name!r} to incompatible output sort."
                )
            continue
        if source_kind == "predicate":
            if len(source_symbol.input_sorts) != len(target_symbol.input_sorts):
                errors.append(
                    f"Morphism {morphism.name!r} maps predicate {source_name!r} to {target_name!r} with different arity."
                )
                continue
            for source_sort, target_sort in zip(source_symbol.input_sorts, target_symbol.input_sorts):
                mapped_sort = morphism.mapping.get(source_sort, source_sort)
                if mapped_sort != target_sort:
                    errors.append(
                        f"Morphism {morphism.name!r} maps predicate {source_name!r} to incompatible input sorts."
                    )

    if require_total:
        for symbol_name, (kind, _) in source_symbols.items():
            if kind in {"sort", "constant", "function", "predicate"} and symbol_name not in morphism.mapping:
                errors.append(f"Morphism {morphism.name!r} is missing a mapping for source {kind} {symbol_name!r}.")

    return errors


def check_document(
    document: ir.Document,
    base_signature: ir.Signature | None = None,
    *,
    theory_signatures: dict[str, ir.Signature] | None = None,
) -> ir.Signature:
    """Typecheck one full document and return its extended signature."""

    signature = build_signature(document) if base_signature is None else base_signature
    extended = extend_signature_with_definitions(signature, document.definitions)

    for rewrite in document.rewrites:
        check_rewrite(rewrite, signature)

    for definition in document.definitions:
        check_definition(definition, signature, extended)
    for clause in document.axioms + document.lemmas + document.theorems:
        check_clause(clause, extended)
    for fact in document.facts:
        _check_atom(fact.atom, extended, {})
    for goal in document.goals:
        check_goal(goal, extended)

    local_theories = dict(theory_signatures or {})
    for theory_name, theory_signature in build_theory_signatures(document).items():
        if theory_name in local_theories:
            raise TypecheckError(f"Duplicate theory name {theory_name!r}.")
        local_theories[theory_name] = theory_signature

    for morphism in document.morphisms:
        errors = validate_morphism(morphism, local_theories)
        if errors:
            raise TypecheckError("; ".join(errors))

    return extended


def check_world(world: ir.World) -> ir.Signature:
    """Typecheck the public and private surfaces of one packaged world."""

    public_document = world.public_document()
    public_signature = check_document(public_document)
    public_theories = build_theory_signatures(public_document)
    private_document = ir.Document(
        definitions=world.hidden_bridge.definitions,
        lemmas=world.hidden_bridge.lemmas,
        morphisms=world.hidden_bridge.mappings,
    )
    return check_document(private_document, public_signature, theory_signatures=public_theories)


def reject_hidden_symbol_names(source_text: str, hidden_names: set[str]) -> list[str]:
    """Return hidden bridge names that appear verbatim in a public-facing text surface."""

    if not hidden_names:
        return []
    leaks: list[str] = []
    for name in hidden_names:
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        if pattern.search(source_text):
            leaks.append(name)
    return sorted(leaks)
