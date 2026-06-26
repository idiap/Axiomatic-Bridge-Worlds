# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Typed intermediate representation for Axiomatic Bridge Worlds.

This module defines the authoritative typed surface the rest of the runtime
builds on: the Horn-clause core plus equational rewrite rules, named theories,
and signature morphisms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Sort:
    """One sort declaration in the ABW signature."""

    name: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the sort into a JSON-friendly payload."""

        return {"name": self.name}


@dataclass(frozen=True)
class ConstantSymbol:
    """One named constant symbol with its declared sort."""

    name: str
    sort: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the constant symbol into a JSON-friendly payload."""

        return {"name": self.name, "sort": self.sort}


@dataclass(frozen=True)
class FunctionSymbol:
    """One function symbol signature in the ABW world."""

    name: str
    input_sorts: tuple[str, ...]
    output_sort: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the function symbol into a JSON-friendly payload."""

        return {
            "name": self.name,
            "input_sorts": list(self.input_sorts),
            "output_sort": self.output_sort,
        }


@dataclass(frozen=True)
class PredicateSymbol:
    """One predicate symbol signature in the ABW world."""

    name: str
    input_sorts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the predicate symbol into a JSON-friendly payload."""

        return {"name": self.name, "input_sorts": list(self.input_sorts)}


@dataclass(frozen=True)
class Variable:
    """One typed logical variable."""

    name: str
    sort: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the variable into a JSON-friendly payload."""

        return {"name": self.name, "sort": self.sort}


class Term:
    """Common interface for typed terms."""

    def substitute(self, mapping: dict[str, "Term"]) -> "Term":
        """Return the term produced by applying a variable substitution."""

        raise NotImplementedError

    def variables(self) -> tuple[Variable, ...]:
        """Return the variables that occur inside the term."""

        raise NotImplementedError

    def depth(self) -> int:
        """Return the maximum function-nesting depth inside the term."""

        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """Serialize the term into a JSON-friendly payload."""

        raise NotImplementedError


@dataclass(frozen=True)
class VarTerm(Term):
    """A term that refers directly to a bound variable."""

    variable: Variable

    def substitute(self, mapping: dict[str, Term]) -> Term:
        """Replace the variable when the substitution map provides a binding."""

        return mapping.get(self.variable.name, self)

    def variables(self) -> tuple[Variable, ...]:
        """Return the one variable mentioned by this term."""

        return (self.variable,)

    def depth(self) -> int:
        """Return the term depth contributed by a plain variable."""

        return 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the variable term into a JSON-friendly payload."""

        return {"kind": "var", "variable": self.variable.to_dict()}


@dataclass(frozen=True)
class ConstTerm(Term):
    """A term that refers to a declared constant symbol."""

    name: str

    def substitute(self, mapping: dict[str, Term]) -> Term:
        """Leave constant terms unchanged under substitution."""

        return self

    def variables(self) -> tuple[Variable, ...]:
        """Return the variables mentioned by this constant term."""

        return ()

    def depth(self) -> int:
        """Return the term depth contributed by a constant."""

        return 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the constant term into a JSON-friendly payload."""

        return {"kind": "const", "name": self.name}


@dataclass(frozen=True)
class FuncTerm(Term):
    """A term formed by applying a function symbol to argument terms."""

    name: str
    args: tuple[Term, ...]

    def substitute(self, mapping: dict[str, Term]) -> Term:
        """Apply a substitution recursively through the argument terms."""

        return FuncTerm(self.name, tuple(argument.substitute(mapping) for argument in self.args))

    def variables(self) -> tuple[Variable, ...]:
        """Return the variables appearing anywhere inside the term."""

        variables: list[Variable] = []
        for argument in self.args:
            variables.extend(argument.variables())
        return tuple(variables)

    def depth(self) -> int:
        """Return the maximum nesting depth below this function application."""

        return 1 + max((argument.depth() for argument in self.args), default=0)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the function term into a JSON-friendly payload."""

        return {"kind": "func", "name": self.name, "args": [argument.to_dict() for argument in self.args]}


@dataclass(frozen=True)
class Atom:
    """A predicate application or equality atom."""

    predicate: str
    terms: tuple[Term, ...]

    def substitute(self, mapping: dict[str, Term]) -> "Atom":
        """Apply a substitution recursively through the atom's terms."""

        return Atom(self.predicate, tuple(term.substitute(mapping) for term in self.terms))

    def variables(self) -> tuple[Variable, ...]:
        """Return the variables mentioned across the atom's terms."""

        variables: list[Variable] = []
        for term in self.terms:
            variables.extend(term.variables())
        return tuple(variables)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the atom into a JSON-friendly payload."""

        return {"predicate": self.predicate, "terms": [term.to_dict() for term in self.terms]}


@dataclass(frozen=True)
class HornClause:
    """A named Horn clause with optional universally quantified variables."""

    name: str
    variables: tuple[Variable, ...]
    premises: tuple[Atom, ...]
    conclusion: Atom

    def substitute(self, mapping: dict[str, Term]) -> "HornClause":
        """Apply a substitution through the clause premises and conclusion."""

        return HornClause(
            self.name,
            self.variables,
            tuple(atom.substitute(mapping) for atom in self.premises),
            self.conclusion.substitute(mapping),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the Horn clause into a JSON-friendly payload."""

        return {
            "name": self.name,
            "variables": [variable.to_dict() for variable in self.variables],
            "premises": [premise.to_dict() for premise in self.premises],
            "conclusion": self.conclusion.to_dict(),
        }


@dataclass(frozen=True)
class RewriteRule:
    """A named term rewrite used by normal-form style worlds."""

    name: str
    lhs: Term
    rhs: Term

    def to_dict(self) -> dict[str, Any]:
        """Serialize the rewrite rule into a JSON-friendly payload."""

        return {
            "name": self.name,
            "lhs": self.lhs.to_dict(),
            "rhs": self.rhs.to_dict(),
        }


@dataclass(frozen=True)
class Definition:
    """A conjunctive bridge predicate definition."""

    name: str
    parameters: tuple[Variable, ...]
    body: tuple[Atom, ...]

    def head_atom(self) -> Atom:
        """Return the synthetic head atom introduced by the definition."""

        return Atom(self.name, tuple(VarTerm(parameter) for parameter in self.parameters))

    def to_dict(self) -> dict[str, Any]:
        """Serialize the definition into a JSON-friendly payload."""

        return {
            "name": self.name,
            "parameters": [parameter.to_dict() for parameter in self.parameters],
            "body": [atom.to_dict() for atom in self.body],
        }


@dataclass(frozen=True)
class Fact:
    """A named ground atom packaged as visible evidence."""

    name: str
    atom: Atom

    def to_dict(self) -> dict[str, Any]:
        """Serialize the fact into a JSON-friendly payload."""

        return {"name": self.name, "atom": self.atom.to_dict()}


@dataclass(frozen=True)
class Goal:
    """A named target conjunction with an optional proof budget hint."""

    name: str
    atoms: tuple[Atom, ...]
    budget: int | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the goal into a JSON-friendly payload."""

        return {
            "name": self.name,
            "atoms": [atom.to_dict() for atom in self.atoms],
            "budget": self.budget,
            "description": self.description,
        }


@dataclass(frozen=True)
class SignatureMorphism:
    """A structure-preserving mapping between two named theories."""

    name: str
    source_theory: str
    target_theory: str
    mapping: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the morphism into a JSON-friendly payload."""

        return {
            "name": self.name,
            "source_theory": self.source_theory,
            "target_theory": self.target_theory,
            "mapping": dict(sorted(self.mapping.items())),
        }


@dataclass(frozen=True)
class Bridge:
    """The hidden bridge object a candidate is trying to reconstruct."""

    definitions: tuple[Definition, ...] = ()
    lemmas: tuple[HornClause, ...] = ()
    mappings: tuple[SignatureMorphism, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the hidden bridge into a JSON-friendly payload."""

        return {
            "definitions": [definition.to_dict() for definition in self.definitions],
            "lemmas": [lemma.to_dict() for lemma in self.lemmas],
            "mappings": [mapping.to_dict() for mapping in self.mappings],
        }


@dataclass(frozen=True)
class Signature:
    """The declared symbol table for one world or document."""

    sorts: tuple[Sort, ...]
    constants: tuple[ConstantSymbol, ...] = ()
    functions: tuple[FunctionSymbol, ...] = ()
    predicates: tuple[PredicateSymbol, ...] = ()

    def sort_names(self) -> set[str]:
        """Return the set of declared sort names."""

        return {sort.name for sort in self.sorts}

    def constant_map(self) -> dict[str, ConstantSymbol]:
        """Return constant symbols keyed by their public names."""

        return {constant.name: constant for constant in self.constants}

    def function_map(self) -> dict[str, FunctionSymbol]:
        """Return function symbols keyed by their public names."""

        return {function.name: function for function in self.functions}

    def predicate_map(self) -> dict[str, PredicateSymbol]:
        """Return predicate symbols keyed by their public names."""

        return {predicate.name: predicate for predicate in self.predicates}

    def all_symbol_names(self) -> set[str]:
        """Return every declared symbol name across the signature."""

        return (
            self.sort_names()
            | set(self.constant_map())
            | set(self.function_map())
            | set(self.predicate_map())
        )

    def with_predicate(self, predicate: PredicateSymbol) -> "Signature":
        """Return a copy of the signature extended by one predicate symbol."""

        return Signature(
            sorts=self.sorts,
            constants=self.constants,
            functions=self.functions,
            predicates=self.predicates + (predicate,),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the signature into a JSON-friendly payload."""

        return {
            "sorts": [sort.to_dict() for sort in self.sorts],
            "constants": [constant.to_dict() for constant in self.constants],
            "functions": [function.to_dict() for function in self.functions],
            "predicates": [predicate.to_dict() for predicate in self.predicates],
        }


@dataclass(frozen=True)
class Document:
    """A self-contained bundle of ABW declarations and statements."""

    sorts: tuple[Sort, ...] = ()
    constants: tuple[ConstantSymbol, ...] = ()
    functions: tuple[FunctionSymbol, ...] = ()
    predicates: tuple[PredicateSymbol, ...] = ()
    rewrites: tuple[RewriteRule, ...] = ()
    axioms: tuple[HornClause, ...] = ()
    lemmas: tuple[HornClause, ...] = ()
    theorems: tuple[HornClause, ...] = ()
    definitions: tuple[Definition, ...] = ()
    facts: tuple[Fact, ...] = ()
    goals: tuple[Goal, ...] = ()
    theories: tuple["Theory", ...] = ()
    morphisms: tuple[SignatureMorphism, ...] = ()

    def signature(self) -> Signature:
        """Return the declared symbol signature for the document."""

        return Signature(
            sorts=self.sorts,
            constants=self.constants,
            functions=self.functions,
            predicates=self.predicates,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the document into a JSON-friendly payload."""

        return {
            "sorts": [sort.to_dict() for sort in self.sorts],
            "constants": [constant.to_dict() for constant in self.constants],
            "functions": [function.to_dict() for function in self.functions],
            "predicates": [predicate.to_dict() for predicate in self.predicates],
            "rewrites": [rewrite.to_dict() for rewrite in self.rewrites],
            "axioms": [clause.to_dict() for clause in self.axioms],
            "lemmas": [clause.to_dict() for clause in self.lemmas],
            "theorems": [clause.to_dict() for clause in self.theorems],
            "definitions": [definition.to_dict() for definition in self.definitions],
            "facts": [fact.to_dict() for fact in self.facts],
            "goals": [goal.to_dict() for goal in self.goals],
            "theories": [theory.to_dict() for theory in self.theories],
            "morphisms": [morphism.to_dict() for morphism in self.morphisms],
        }


@dataclass(frozen=True)
class Theory:
    """A named subtheory embedded inside a larger document or world."""

    name: str
    document: Document

    def to_dict(self) -> dict[str, Any]:
        """Serialize the theory into a JSON-friendly payload."""

        return {"name": self.name, "document": self.document.to_dict()}


@dataclass(frozen=True)
class World:
    """The packaged ABW world consumed by generation, scoring, and sessions."""

    world_id: str
    family: str
    signature: Signature
    axioms: tuple[HornClause, ...]
    visible_theorems: tuple[HornClause, ...]
    visible_facts: tuple[Fact, ...]
    targets_visible: tuple[Goal, ...]
    targets_hidden: tuple[Goal, ...]
    hidden_bridge: Bridge
    rewrites: tuple[RewriteRule, ...] = ()
    theories: tuple[Theory, ...] = ()
    visible_morphisms: tuple[SignatureMorphism, ...] = ()
    proof_fixtures: dict[str, Any] = field(default_factory=dict)
    scoring_config: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_clauses(self) -> tuple[HornClause, ...]:
        """Return the public rule set used during visible reasoning."""

        return self.axioms + self.visible_theorems

    def public_document(self) -> Document:
        """Project the world onto the public document surface given to solvers."""

        return Document(
            sorts=self.signature.sorts,
            constants=self.signature.constants,
            functions=self.signature.functions,
            predicates=self.signature.predicates,
            rewrites=self.rewrites,
            axioms=self.axioms,
            theorems=self.visible_theorems,
            facts=self.visible_facts,
            goals=self.targets_visible,
            theories=self.theories,
            morphisms=self.visible_morphisms,
        )


def definition_predicates(definitions: tuple[Definition, ...]) -> tuple[PredicateSymbol, ...]:
    """Lift definition heads into predicate-symbol declarations."""

    return tuple(
        PredicateSymbol(definition.name, tuple(parameter.sort for parameter in definition.parameters))
        for definition in definitions
    )
