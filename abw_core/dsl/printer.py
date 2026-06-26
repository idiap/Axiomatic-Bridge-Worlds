# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Pretty-printer for the supported ABW DSL layers."""

from __future__ import annotations

from abw_core import ir


def format_term(term: ir.Term) -> str:
    """Render one IR term back into DSL syntax."""

    if isinstance(term, ir.VarTerm):
        return term.variable.name
    if isinstance(term, ir.ConstTerm):
        return term.name
    if isinstance(term, ir.FuncTerm):
        return f"{term.name}({', '.join(format_term(argument) for argument in term.args)})"
    raise TypeError(f"Unsupported term type: {type(term)!r}")


def format_atom(atom: ir.Atom) -> str:
    """Render one atom, including equality atoms, into DSL syntax."""

    if atom.predicate == "=" and len(atom.terms) == 2:
        return f"{format_term(atom.terms[0])} = {format_term(atom.terms[1])}"
    if not atom.terms:
        return atom.predicate
    return f"{atom.predicate}({', '.join(format_term(term) for term in atom.terms)})"


def format_clause(clause: ir.HornClause, keyword: str | None = None) -> str:
    """Render one Horn clause with an optional leading statement keyword."""

    quantifier = ""
    if clause.variables:
        quantifier = "forall " + " ".join(f"{variable.name}:{variable.sort}" for variable in clause.variables) + ". "
    body = format_atom(clause.conclusion)
    if clause.premises:
        body = f"{' & '.join(format_atom(atom) for atom in clause.premises)} -> {format_atom(clause.conclusion)}"
    prefix = ""
    if keyword is not None:
        prefix = f"{keyword} {clause.name}: "
    return prefix + quantifier + body


def format_definition(definition: ir.Definition) -> str:
    """Render one bridge definition into DSL syntax."""

    params = ", ".join(f"{parameter.name}:{parameter.sort}" for parameter in definition.parameters)
    body = " & ".join(format_atom(atom) for atom in definition.body)
    return f"define {definition.name}({params}) := {body}"


def format_rewrite(rule: ir.RewriteRule) -> str:
    """Render one rewrite rule into DSL syntax."""

    return f"rewrite {rule.name}: {format_term(rule.lhs)} -> {format_term(rule.rhs)}"


def format_fact(fact: ir.Fact) -> str:
    """Render one named fact into DSL syntax."""

    return f"fact {fact.name}: {format_atom(fact.atom)}"


def format_goal(goal: ir.Goal) -> str:
    """Render one named goal into DSL syntax."""

    body = " & ".join(format_atom(atom) for atom in goal.atoms)
    return f"goal {goal.name}: {body}"


def format_morphism(morphism: ir.SignatureMorphism) -> str:
    """Render one signature morphism block into DSL syntax."""

    lines = [f"morphism {morphism.name} : {morphism.source_theory} -> {morphism.target_theory} {{"]
    lines.extend(f"  {source} -> {target}" for source, target in sorted(morphism.mapping.items()))
    lines.append("}")
    return "\n".join(lines)


def format_theory(theory: ir.Theory) -> str:
    """Render one nested theory block into DSL syntax."""

    body = format_document(theory.document).rstrip()
    lines = [f"theory {theory.name} {{"]
    if body:
        lines.extend(f"  {line}" for line in body.splitlines())
    lines.append("}")
    return "\n".join(lines)


def format_document(document: ir.Document) -> str:
    """Render one whole IR document into the canonical DSL surface."""

    lines: list[str] = []
    lines.extend(f"sort {sort.name}" for sort in document.sorts)
    lines.extend(f"const {constant.name} : {constant.sort}" for constant in document.constants)
    lines.extend(
        f"func {function.name} : {', '.join(function.input_sorts)} -> {function.output_sort}"
        for function in document.functions
    )
    lines.extend(
        f"pred {predicate.name} : {', '.join(predicate.input_sorts)}" for predicate in document.predicates
    )
    lines.extend(format_rewrite(rule) for rule in document.rewrites)
    lines.extend(format_clause(clause, "axiom") for clause in document.axioms)
    lines.extend(format_clause(clause, "lemma") for clause in document.lemmas)
    lines.extend(format_clause(clause, "theorem") for clause in document.theorems)
    lines.extend(format_definition(definition) for definition in document.definitions)
    lines.extend(format_fact(fact) for fact in document.facts)
    lines.extend(format_goal(goal) for goal in document.goals)
    lines.extend(format_theory(theory) for theory in document.theories)
    lines.extend(format_morphism(morphism) for morphism in document.morphisms)
    return "\n".join(lines) + ("\n" if lines else "")
