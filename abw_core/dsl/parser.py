# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Recursive-descent parser for the supported ABW DSL layers.

The parser is the authoritative implementation of the shipped surface syntax,
covering the Horn-clause core plus rewrites, nested theories, and morphisms.
The code stays intentionally direct: statement keywords dispatch explicitly so a
future editor can see where each DSL layer enters the typed IR without mentally
reconstructing a parser generator's tables.
"""

from __future__ import annotations

from abw_core import ir

from .lexer import Token, tokenize


class ParseError(ValueError):
    """Raised when a DSL snippet does not match the supported grammar."""


class Parser:
    """Parse ABW source text into the typed intermediate representation.

    The parser keeps only a token cursor plus a handful of recursive helpers.
    That small state footprint matters because the grammar is intentionally
    close to the research notation, and most changes to the language arrive as
    "one more statement form" rather than as a wholesale syntax redesign.
    """

    def __init__(self, source: str) -> None:
        self.tokens = tokenize(source)
        self.index = 0

    @property
    def current(self) -> Token:
        """Return the token currently under the parser cursor."""

        return self.tokens[self.index]

    def peek(self, offset: int = 1) -> Token:
        """Inspect a later token without consuming it."""

        return self.tokens[self.index + offset]

    def advance(self) -> Token:
        """Consume and return the current token."""

        token = self.current
        self.index += 1
        return token

    def match(self, kind: str, value: str | None = None) -> bool:
        """Consume the current token when it matches the expected shape."""

        token = self.current
        if token.kind != kind:
            return False
        if value is not None and token.value != value:
            return False
        self.advance()
        return True

    def expect(self, kind: str, value: str | None = None) -> Token:
        """Consume one token or raise a position-rich parse error."""

        token = self.current
        if token.kind != kind or (value is not None and token.value != value):
            suffix = f" {value!r}" if value is not None else ""
            raise ParseError(f"Expected {kind}{suffix} at offset {token.position}, found {token.value!r}.")
        return self.advance()

    def expect_identifier(self) -> str:
        """Consume one identifier token and return its text."""

        return self.expect("IDENT").value

    def parse_document(self, stop_kinds: set[str] | None = None) -> ir.Document:
        """Parse a statement block into one IR document.

        `stop_kinds` lets the same top-level dispatcher handle nested theory
        bodies without introducing a second block parser.
        """

        stop_kinds = stop_kinds or {"EOF"}

        sorts: list[ir.Sort] = []
        constants: list[ir.ConstantSymbol] = []
        functions: list[ir.FunctionSymbol] = []
        predicates: list[ir.PredicateSymbol] = []
        rewrites: list[ir.RewriteRule] = []
        axioms: list[ir.HornClause] = []
        lemmas: list[ir.HornClause] = []
        theorems: list[ir.HornClause] = []
        definitions: list[ir.Definition] = []
        facts: list[ir.Fact] = []
        goals: list[ir.Goal] = []
        theories: list[ir.Theory] = []
        morphisms: list[ir.SignatureMorphism] = []

        # Keyword dispatch is spelled out rather than data-driven so each DSL
        # layer remains obvious in code review and easy to extend locally.
        while self.current.kind not in stop_kinds:
            keyword = self.expect_identifier()
            if keyword == "sort":
                sorts.append(ir.Sort(self.expect_identifier()))
            elif keyword == "const":
                name = self.expect_identifier()
                self.expect("COLON")
                constants.append(ir.ConstantSymbol(name, self.expect_identifier()))
            elif keyword == "func":
                name = self.expect_identifier()
                self.expect("COLON")
                first_sort = self.expect_identifier()
                input_sorts = [first_sort]
                while self.match("COMMA"):
                    input_sorts.append(self.expect_identifier())
                if self.match("ARROW"):
                    output_sort = self.expect_identifier()
                    functions.append(ir.FunctionSymbol(name, tuple(input_sorts), output_sort))
                elif len(input_sorts) == 1:
                    # The surface accepts `func c : S` as a constant shorthand
                    # because many benchmark worlds describe nullary symbols in
                    # that style.
                    constants.append(ir.ConstantSymbol(name, first_sort))
                else:
                    raise ParseError(f"Function {name!r} is missing an output sort.")
            elif keyword == "pred":
                name = self.expect_identifier()
                self.expect("COLON")
                predicates.append(ir.PredicateSymbol(name, self.parse_type_list()))
            elif keyword == "rewrite":
                name = self.parse_optional_label(keyword) or f"rewrite_{len(rewrites)}"
                rewrites.append(self.parse_rewrite(name))
            elif keyword in {"axiom", "lemma", "theorem"}:
                name = self.parse_optional_label(keyword)
                clause = self.parse_clause(name or f"{keyword}_{len(axioms) + len(lemmas) + len(theorems)}")
                if keyword == "axiom":
                    axioms.append(clause)
                elif keyword == "lemma":
                    lemmas.append(clause)
                else:
                    theorems.append(clause)
            elif keyword == "fact":
                name = self.parse_optional_label(keyword) or f"fact_{len(facts)}"
                facts.append(ir.Fact(name, self.parse_atom({})))
            elif keyword == "goal":
                name = self.parse_optional_label(keyword) or f"goal_{len(goals)}"
                goals.append(ir.Goal(name, self.parse_atom_conjunction({})))
            elif keyword == "define":
                definitions.append(self.parse_definition())
            elif keyword == "theory":
                theories.append(self.parse_theory())
            elif keyword == "morphism":
                morphisms.append(self.parse_morphism())
            else:
                raise ParseError(f"Unknown statement keyword {keyword!r} at offset {self.current.position}.")

        return ir.Document(
            sorts=tuple(sorts),
            constants=tuple(constants),
            functions=tuple(functions),
            predicates=tuple(predicates),
            rewrites=tuple(rewrites),
            axioms=tuple(axioms),
            lemmas=tuple(lemmas),
            theorems=tuple(theorems),
            definitions=tuple(definitions),
            facts=tuple(facts),
            goals=tuple(goals),
            theories=tuple(theories),
            morphisms=tuple(morphisms),
        )

    def parse_optional_label(self, keyword: str) -> str | None:
        """Parse the mandatory colon and optional `name:` label slot.

        ABW statements use one consistent `keyword label?: ...` shape so the
        parser can remain deterministic and statement-oriented.
        """

        if self.current.kind == "IDENT" and self.peek().kind == "COLON":
            label = self.advance().value
            self.expect("COLON")
            return label
        if self.current.kind == "COLON":
            self.advance()
            return None
        raise ParseError(f"Expected ':' after {keyword} statement at offset {self.current.position}.")

    def parse_type_list(self) -> tuple[str, ...]:
        """Parse a comma-separated sort list."""

        items = [self.expect_identifier()]
        while self.match("COMMA"):
            items.append(self.expect_identifier())
        return tuple(items)

    def parse_typed_variables(self, terminators: set[str]) -> tuple[ir.Variable, ...]:
        """Parse `name:Sort` bindings until a terminator token is reached.

        The caller provides the stop set because the same variable syntax
        appears in quantifiers and definition heads.
        """

        variables: list[ir.Variable] = []
        while self.current.kind == "IDENT" and self.peek().kind == "COLON":
            name = self.expect_identifier()
            self.expect("COLON")
            sort = self.expect_identifier()
            variables.append(ir.Variable(name, sort))
            if self.match("COMMA"):
                continue
            if self.current.kind in terminators:
                break
        return tuple(variables)

    def parse_clause(self, name: str) -> ir.HornClause:
        """Parse one Horn clause with an optional universal quantifier prefix."""

        variables: tuple[ir.Variable, ...] = ()
        if self.current.kind == "IDENT" and self.current.value == "forall":
            self.advance()
            variables = self.parse_typed_variables({"DOT"})
            self.expect("DOT")
        scope = {variable.name: variable for variable in variables}
        atoms = self.parse_atom_conjunction(scope)
        if self.match("ARROW"):
            conclusion = self.parse_atom(scope)
            premises = atoms
        else:
            # A clause without `->` is treated as a single-atom fact-like rule.
            # For multi-atom conjunctions we force the author to be explicit so
            # the proof direction never depends on hidden parser conventions.
            if len(atoms) != 1:
                raise ParseError("Horn clauses without '->' must contain exactly one atom.")
            premises = ()
            conclusion = atoms[0]
        return ir.HornClause(name=name, variables=variables, premises=premises, conclusion=conclusion)

    def parse_definition(self) -> ir.Definition:
        """Parse one conjunctive bridge definition."""

        name = self.expect_identifier()
        self.expect("LPAREN")
        parameters = self.parse_typed_variables({"RPAREN"})
        self.expect("RPAREN")
        self.expect("DEFINE")
        scope = {parameter.name: parameter for parameter in parameters}
        return ir.Definition(name=name, parameters=parameters, body=self.parse_atom_conjunction(scope))

    def parse_rewrite(self, name: str) -> ir.RewriteRule:
        """Parse one rewrite rule, inferring placeholder variables as needed.

        Rewrites intentionally omit an explicit quantifier surface. Placeholder
        variables are introduced on demand so a compact rule such as
        `rewrite step: f(x) -> g(x)` can be written without extra boilerplate.
        """

        implicit_variables: dict[str, ir.Variable] = {}
        lhs = self.parse_term({}, implicit_variables)
        self.expect("ARROW")
        rhs = self.parse_term({}, implicit_variables)
        return ir.RewriteRule(name=name, lhs=lhs, rhs=rhs)

    def parse_theory(self) -> ir.Theory:
        """Parse one nested theory block."""

        name = self.expect_identifier()
        self.expect("LBRACE")
        document = self.parse_document(stop_kinds={"RBRACE"})
        self.expect("RBRACE")
        return ir.Theory(name=name, document=document)

    def parse_morphism(self) -> ir.SignatureMorphism:
        """Parse one theory-to-theory symbol mapping."""

        name = self.expect_identifier()
        self.expect("COLON")
        source_theory = self.expect_identifier()
        self.expect("ARROW")
        target_theory = self.expect_identifier()
        self.expect("LBRACE")
        mapping: dict[str, str] = {}
        while self.current.kind != "RBRACE":
            source_name = self.expect_identifier()
            self.expect("ARROW")
            target_name = self.expect_identifier()
            mapping[source_name] = target_name
        self.expect("RBRACE")
        return ir.SignatureMorphism(
            name=name,
            source_theory=source_theory,
            target_theory=target_theory,
            mapping=mapping,
        )

    def parse_atom_conjunction(self, scope: dict[str, ir.Variable]) -> tuple[ir.Atom, ...]:
        """Parse one `a & b & c` conjunction of atoms."""

        atoms = [self.parse_atom(scope)]
        while self.match("AND"):
            atoms.append(self.parse_atom(scope))
        return tuple(atoms)

    def parse_atom(self, scope: dict[str, ir.Variable]) -> ir.Atom:
        """Parse one predicate atom or equality atom.

        Equality is recognized after the potential call head so the same syntax
        can express both `P(x)` and `f(x) = g(x)` without a separate term-first
        parsing pass.
        """

        name = self.expect_identifier()
        if self.match("LPAREN"):
            arguments: list[ir.Term] = []
            if not self.match("RPAREN"):
                arguments.append(self.parse_term(scope))
                while self.match("COMMA"):
                    arguments.append(self.parse_term(scope))
                self.expect("RPAREN")
            if self.match("EQUAL"):
                lhs = ir.FuncTerm(name, tuple(arguments))
                rhs = self.parse_term(scope)
                return ir.Atom("=", (lhs, rhs))
            return ir.Atom(name, tuple(arguments))

        if self.match("EQUAL"):
            lhs = self.term_from_name(name, scope, None)
            rhs = self.parse_term(scope)
            return ir.Atom("=", (lhs, rhs))

        return ir.Atom(name, ())

    def parse_term(
        self,
        scope: dict[str, ir.Variable],
        implicit_variables: dict[str, ir.Variable] | None = None,
    ) -> ir.Term:
        """Parse one term in the current variable scope.

        Terms stay intentionally permissive at parse time; symbol-kind
        validation belongs to the typechecker, which has access to the full
        signature and can report richer semantic errors.
        """

        name = self.expect_identifier()
        if self.match("LPAREN"):
            arguments: list[ir.Term] = []
            if not self.match("RPAREN"):
                arguments.append(self.parse_term(scope, implicit_variables))
                while self.match("COMMA"):
                    arguments.append(self.parse_term(scope, implicit_variables))
                self.expect("RPAREN")
            return ir.FuncTerm(name, tuple(arguments))
        return self.term_from_name(name, scope, implicit_variables)

    def term_from_name(
        self,
        name: str,
        scope: dict[str, ir.Variable],
        implicit_variables: dict[str, ir.Variable] | None,
    ) -> ir.Term:
        """Resolve an identifier as a scoped variable, implicit variable, or constant.

        This is where parser-time name resolution stops. Anything not bound in
        the local syntactic scope becomes either an implicit rewrite variable or
        a constant term candidate for the later typechecking phase to validate.
        """

        variable = scope.get(name)
        if variable is not None:
            return ir.VarTerm(variable)
        if implicit_variables is not None:
            implicit = implicit_variables.get(name)
            if implicit is None:
                implicit = ir.Variable(name, "_")
                implicit_variables[name] = implicit
            return ir.VarTerm(implicit)
        return ir.ConstTerm(name)


def parse_document(source: str) -> ir.Document:
    """Parse one whole DSL document with the default top-level stop rule."""

    return Parser(source).parse_document()


def parse_statement_block(source: str) -> ir.Document:
    """Parse a free-standing DSL statement block.

    This alias exists to make call sites read naturally when the input text is
    a block fragment rather than a named on-disk ABW document.
    """

    return parse_document(source)
