# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Term rewriting and equality normalization for ABW DSL v1 items."""

from __future__ import annotations

from abw_core import ir


def match_term(
    pattern: ir.Term,
    subject: ir.Term,
    bindings: dict[str, ir.Term] | None = None,
) -> dict[str, ir.Term] | None:
    """Match a rewrite pattern term against a subject term."""

    bindings = dict(bindings or {})

    if isinstance(pattern, ir.VarTerm):
        existing = bindings.get(pattern.variable.name)
        if existing is None:
            bindings[pattern.variable.name] = subject
            return bindings
        return bindings if existing == subject else None

    if type(pattern) is not type(subject):
        return None

    if isinstance(pattern, ir.ConstTerm):
        return bindings if pattern.name == subject.name else None

    if isinstance(pattern, ir.FuncTerm):
        if pattern.name != subject.name or len(pattern.args) != len(subject.args):
            return None
        for pattern_arg, subject_arg in zip(pattern.args, subject.args):
            matched = match_term(pattern_arg, subject_arg, bindings)
            if matched is None:
                return None
            bindings = matched
        return bindings

    return None


def _rewrite_top(term: ir.Term, rules: tuple[ir.RewriteRule, ...]) -> ir.Term | None:
    for rule in rules:
        bindings = match_term(rule.lhs, term)
        if bindings is not None:
            return rule.rhs.substitute(bindings)
    return None


def normalize_term(term: ir.Term, rules: tuple[ir.RewriteRule, ...], *, max_steps: int = 64) -> ir.Term:
    """Normalize a term by repeatedly applying rewrite rules to fixed point."""

    if not rules:
        return term

    if isinstance(term, ir.FuncTerm):
        current: ir.Term = ir.FuncTerm(
            term.name,
            tuple(normalize_term(argument, rules, max_steps=max_steps) for argument in term.args),
        )
    else:
        current = term

    steps = 0
    while steps < max_steps:
        rewritten = _rewrite_top(current, rules)
        if rewritten is None:
            return current
        if isinstance(rewritten, ir.FuncTerm):
            current = ir.FuncTerm(
                rewritten.name,
                tuple(normalize_term(argument, rules, max_steps=max_steps) for argument in rewritten.args),
            )
        else:
            current = rewritten
        steps += 1
    raise ValueError("Rewrite normalization exceeded the configured step limit.")


def normalize_atom(atom: ir.Atom, rules: tuple[ir.RewriteRule, ...]) -> ir.Atom:
    """Normalize every term inside an atom and canonicalize equality order."""

    normalized_terms = tuple(normalize_term(term, rules) for term in atom.terms)
    if atom.predicate == "=" and len(normalized_terms) == 2:
        ordered = tuple(sorted(normalized_terms, key=lambda term: str(term.to_dict())))
        return ir.Atom("=", ordered)
    return ir.Atom(atom.predicate, normalized_terms)
