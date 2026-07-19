# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Controlled natural-language bridge candidates and deterministic conversion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from abw_core import ir
from abw_core.dsl.parser import parse_document
from abw_core.dsl.printer import format_document
from abw_core.nl.naming import NamingScheme, build_naming


CONVERTER_VERSION = "abw-controlled-nl-v1"
CONTROLLED_NL_GRAMMAR_VERSION = "abw-cnl-bridge-v1"
INVALID_CONVERSION_CANDIDATE = "lemma nld_conversion_failed: ConversionFailed"

CONTROLLED_NL_OUTPUT_CONTRACT = """## Controlled natural-language output contract
Return only controlled natural-language bridge blocks. Do not return ABW DSL, JSON, Markdown fences, or an explanation.

Use these exact block shapes, with one field per line and a blank line between blocks.

Definition block:
Definition "short natural name"
For every: x is a mav object; y is a ren object
Means: A holds of x; B holds of y; R holds between x and y

Lemma block:
Lemma "short natural name"
For every: x is a mav object; y is a ren object
When: A holds of x; R holds between x and y
Then: B holds of y

Mapping block:
Mapping "short natural name"
From theory: Left
To theory: Right
Pairs:
- object kind mav corresponds to object kind ren
- named object mav-0 corresponds to named object ren-0
- operation shift corresponds to operation glide
- relation LP corresponds to relation RP

Rules:
- Use only object-kind, object, operation, relation, and theory labels present in the public natural-language view.
- Separate multiple conditions with semicolons. Do not use semicolons inside a term.
- Write unary terms as `the shift of x` and binary terms as `the seal of x and y`.
- Write equality as `the shift of x equals x`.
- A Definition name introduces a relation with that natural name; later blocks may use it with `holds of` or `holds between`.
- Use Definition and Lemma blocks for non-analogy worlds. Use exactly one Mapping block for analogy worlds.
- Do not add headings, bullets outside Pairs, comments, or prose before or after the blocks."""


class ControlledNLConversionError(ValueError):
    """Raised when a candidate is outside the declared controlled language."""


@dataclass(frozen=True)
class TheoryVocabulary:
    """Public symbol vocabulary for one named nested theory."""

    name: str
    signature: ir.Signature
    naming: NamingScheme


@dataclass(frozen=True)
class CandidateVocabulary:
    """Public vocabulary used by the deterministic NL-to-DSL converter."""

    signature: ir.Signature
    naming: NamingScheme
    theories: tuple[TheoryVocabulary, ...] = ()

    @classmethod
    def from_public_artifacts(cls, signature_path: str | Path, axioms_path: str | Path) -> "CandidateVocabulary":
        """Build converter vocabulary from public formal artifacts after generation."""

        signature_payload = json.loads(Path(signature_path).read_text(encoding="utf-8"))
        signature = ir.Signature(
            sorts=tuple(ir.Sort(row["name"]) for row in signature_payload["sorts"]),
            constants=tuple(ir.ConstantSymbol(row["name"], row["sort"]) for row in signature_payload["constants"]),
            functions=tuple(
                ir.FunctionSymbol(row["name"], tuple(row["input_sorts"]), row["output_sort"])
                for row in signature_payload["functions"]
            ),
            predicates=tuple(
                ir.PredicateSymbol(row["name"], tuple(row["input_sorts"]))
                for row in signature_payload["predicates"]
            ),
        )
        document = parse_document(Path(axioms_path).read_text(encoding="utf-8"))
        return cls.from_signature(signature, theories=document.theories)

    @classmethod
    def from_signature(
        cls,
        signature: ir.Signature,
        *,
        theories: Iterable[ir.Theory] = (),
    ) -> "CandidateVocabulary":
        """Build converter vocabulary from a public signature and public theories."""

        theory_rows = tuple(theories)
        if not theory_rows:
            return cls(signature=signature, naming=build_naming(signature))

        combined = ir.Signature(
            sorts=tuple(sort for theory in theory_rows for sort in theory.document.sorts),
            constants=tuple(constant for theory in theory_rows for constant in theory.document.constants),
            functions=tuple(function for theory in theory_rows for function in theory.document.functions),
            predicates=tuple(predicate for theory in theory_rows for predicate in theory.document.predicates),
        )
        combined_naming = build_naming(combined)
        theory_vocabularies = tuple(
            TheoryVocabulary(
                name=theory.name,
                signature=theory.document.signature(),
                naming=NamingScheme(
                    sorts={sort.name: combined_naming.sorts[sort.name] for sort in theory.document.sorts},
                    constants={
                        constant.name: combined_naming.constants[constant.name]
                        for constant in theory.document.constants
                    },
                    functions={
                        function.name: combined_naming.functions[function.name]
                        for function in theory.document.functions
                    },
                    predicates={
                        predicate.name: combined_naming.predicates[predicate.name]
                        for predicate in theory.document.predicates
                    },
                ),
            )
            for theory in theory_rows
        )
        return cls(signature=signature, naming=build_naming(signature), theories=theory_vocabularies)


@dataclass(frozen=True)
class ConversionResult:
    """Result of deterministic controlled-NL conversion."""

    status: str
    candidate_dsl: str | None
    errors: tuple[str, ...]
    converter_version: str
    grammar_version: str
    converter_sha256: str
    raw_candidate_sha256: str

    def to_metadata(self) -> dict[str, object]:
        """Return the JSON-compatible conversion record stored in reports."""

        return {
            "status": self.status,
            "candidate_dsl": self.candidate_dsl,
            "errors": list(self.errors),
            "converter_version": self.converter_version,
            "grammar_version": self.grammar_version,
            "converter_sha256": self.converter_sha256,
            "raw_candidate_sha256": self.raw_candidate_sha256,
        }


@dataclass(frozen=True)
class _Block:
    kind: str
    natural_name: str
    fields: dict[str, str]
    pairs: tuple[str, ...] = ()


@dataclass(frozen=True)
class _FunctionSpec:
    surface: str
    symbol: ir.FunctionSymbol


@dataclass(frozen=True)
class _PredicateSpec:
    surface: str
    formal_name: str
    input_sorts: tuple[str, ...]


def converter_source_sha256() -> str:
    """Hash this converter implementation for report-level provenance."""

    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _normalized(text: str) -> str:
    return " ".join(text.strip().split())


def _key(text: str) -> str:
    return _normalized(text).casefold()


def _humanize_identifier(name: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name.replace("_", " "))
    return _normalized(spaced).casefold()


def _candidate_identifier(natural_name: str, *, prefix: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", natural_name)
    if not words:
        raise ControlledNLConversionError(f"{prefix} name must contain at least one letter or digit.")
    stem = "".join(word[:1].upper() + word[1:].lower() for word in words)
    return f"Cand{prefix}{stem}"


def _parse_blocks(raw_candidate: str) -> tuple[_Block, ...]:
    lines = raw_candidate.strip().splitlines()
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip() == "```":
        lines.pop()

    header_re = re.compile(r'^(Definition|Lemma|Mapping)\s+"([^"]+)"\s*$')
    blocks: list[_Block] = []
    kind: str | None = None
    natural_name = ""
    fields: dict[str, str] = {}
    pairs: list[str] = []
    current_field: str | None = None
    in_pairs = False

    def finish() -> None:
        nonlocal kind, natural_name, fields, pairs, current_field, in_pairs
        if kind is not None:
            blocks.append(_Block(kind, natural_name, dict(fields), tuple(pairs)))
        kind = None
        natural_name = ""
        fields = {}
        pairs = []
        current_field = None
        in_pairs = False

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line == "```":
            continue
        header = header_re.fullmatch(line)
        if header:
            finish()
            kind, natural_name = header.group(1), _normalized(header.group(2))
            continue
        if kind is None:
            raise ControlledNLConversionError(
                f"Line {line_number} is outside a Definition, Lemma, or Mapping block: {line!r}."
            )
        if in_pairs and line.startswith("- "):
            pairs.append(_normalized(line[2:]))
            continue
        field_match = re.fullmatch(r"([A-Za-z ]+):\s*(.*)", line)
        if field_match:
            field_name = _normalized(field_match.group(1)).casefold()
            field_value = _normalized(field_match.group(2))
            if field_name in fields:
                raise ControlledNLConversionError(f"Duplicate field {field_name!r} in {kind} {natural_name!r}.")
            fields[field_name] = field_value
            current_field = field_name
            in_pairs = field_name == "pairs"
            continue
        if in_pairs and pairs:
            pairs[-1] = _normalized(pairs[-1] + " " + line)
            continue
        if current_field is not None:
            fields[current_field] = _normalized(fields[current_field] + " " + line)
            continue
        raise ControlledNLConversionError(f"Unrecognized line {line_number} in {kind} {natural_name!r}: {line!r}.")
    finish()
    if not blocks:
        raise ControlledNLConversionError("Candidate does not contain a controlled natural-language bridge block.")
    return tuple(blocks)


def _split_semicolon_items(text: str, *, field_name: str) -> tuple[str, ...]:
    items = tuple(item.strip() for item in text.split(";") if item.strip())
    if not items:
        raise ControlledNLConversionError(f"{field_name} must contain at least one item.")
    return items


class _Resolver:
    def __init__(
        self,
        signature: ir.Signature,
        naming: NamingScheme,
        *,
        invented_predicates: dict[str, tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        self.sorts = {_key(surface): formal for formal, surface in naming.sorts.items()}
        self.constants = {
            _key(naming.constants[symbol.name]): (symbol.name, symbol.sort)
            for symbol in signature.constants
        }
        self.functions = tuple(
            sorted(
                (_FunctionSpec(naming.functions[symbol.name], symbol) for symbol in signature.functions),
                key=lambda item: len(item.surface),
                reverse=True,
            )
        )
        predicates = [
            _PredicateSpec(naming.predicates[symbol.name], symbol.name, symbol.input_sorts)
            for symbol in signature.predicates
        ]
        for surface, (formal_name, input_sorts) in (invented_predicates or {}).items():
            predicates.append(_PredicateSpec(surface, formal_name, input_sorts))
        seen: set[str] = set()
        for predicate in predicates:
            predicate_key = _key(predicate.surface)
            if predicate_key in seen:
                raise ControlledNLConversionError(f"Ambiguous relation label {predicate.surface!r}.")
            seen.add(predicate_key)
        self.predicates = tuple(sorted(predicates, key=lambda item: len(item.surface), reverse=True))
        self.sort_surface = dict(naming.sorts)
        self.constant_surface = dict(naming.constants)
        self.function_surface = dict(naming.functions)
        self.predicate_surface = dict(naming.predicates)
        self.invented_surface = {
            formal_name: surface for surface, (formal_name, _) in (invented_predicates or {}).items()
        }

    def parse_variables(self, text: str) -> dict[str, ir.Variable]:
        variables: dict[str, ir.Variable] = {}
        for item in _split_semicolon_items(text, field_name="For every"):
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*) is an? (.+) object", item)
            if match is None:
                raise ControlledNLConversionError(
                    f"Variable declaration must look like `x is a mav object`: {item!r}."
                )
            variable_name, sort_surface = match.groups()
            sort_name = self.sorts.get(_key(sort_surface))
            if sort_name is None:
                raise ControlledNLConversionError(f"Unknown public object kind {sort_surface!r}.")
            if variable_name in variables:
                raise ControlledNLConversionError(f"Duplicate variable {variable_name!r}.")
            variables[variable_name] = ir.Variable(variable_name, sort_name)
        return variables

    def parse_term(
        self,
        text: str,
        variables: dict[str, ir.Variable],
        *,
        expected_sort: str | None = None,
    ) -> tuple[ir.Term, str]:
        normalized = _normalized(text)
        variable = variables.get(normalized)
        if variable is not None:
            if expected_sort is not None and variable.sort != expected_sort:
                raise ControlledNLConversionError(
                    f"Variable {normalized!r} has kind {variable.sort}, expected {expected_sort}."
                )
            return ir.VarTerm(variable), variable.sort

        constant = self.constants.get(_key(normalized))
        if constant is not None:
            formal_name, sort_name = constant
            if expected_sort is not None and sort_name != expected_sort:
                raise ControlledNLConversionError(
                    f"Named object {normalized!r} has kind {sort_name}, expected {expected_sort}."
                )
            return ir.ConstTerm(formal_name), sort_name

        for function in self.functions:
            prefix = f"the {_key(function.surface)} of "
            if not _key(normalized).startswith(prefix):
                continue
            if expected_sort is not None and function.symbol.output_sort != expected_sort:
                continue
            remainder = normalized[len(prefix) :]
            if len(function.symbol.input_sorts) == 1:
                argument, _ = self.parse_term(
                    remainder,
                    variables,
                    expected_sort=function.symbol.input_sorts[0],
                )
                return ir.FuncTerm(function.symbol.name, (argument,)), function.symbol.output_sort
            if len(function.symbol.input_sorts) == 2:
                for split_match in re.finditer(r" and ", remainder):
                    left_text = remainder[: split_match.start()]
                    right_text = remainder[split_match.end() :]
                    try:
                        left, _ = self.parse_term(
                            left_text,
                            variables,
                            expected_sort=function.symbol.input_sorts[0],
                        )
                        right, _ = self.parse_term(
                            right_text,
                            variables,
                            expected_sort=function.symbol.input_sorts[1],
                        )
                    except ControlledNLConversionError:
                        continue
                    return ir.FuncTerm(function.symbol.name, (left, right)), function.symbol.output_sort
        raise ControlledNLConversionError(f"Cannot resolve controlled natural-language term {text!r}.")

    def parse_atom(self, text: str, variables: dict[str, ir.Variable]) -> ir.Atom:
        normalized = _normalized(text)
        for equality_match in re.finditer(r" equals ", normalized):
            try:
                left, left_sort = self.parse_term(normalized[: equality_match.start()], variables)
                right, _ = self.parse_term(
                    normalized[equality_match.end() :],
                    variables,
                    expected_sort=left_sort,
                )
            except ControlledNLConversionError:
                continue
            return ir.Atom("=", (left, right))

        normalized_key = _key(normalized)
        for predicate in self.predicates:
            label = _key(predicate.surface)
            arity = len(predicate.input_sorts)
            if arity == 0 and normalized_key == f"{label} holds":
                return ir.Atom(predicate.formal_name, ())
            if arity == 1 and normalized_key.startswith(f"{label} holds of "):
                term_text = normalized[len(f"{predicate.surface} holds of ") :]
                term, _ = self.parse_term(term_text, variables, expected_sort=predicate.input_sorts[0])
                return ir.Atom(predicate.formal_name, (term,))
            if arity == 2 and normalized_key.startswith(f"{label} holds between "):
                terms_text = normalized[len(f"{predicate.surface} holds between ") :]
                for split_match in re.finditer(r" and ", terms_text):
                    try:
                        left, _ = self.parse_term(
                            terms_text[: split_match.start()],
                            variables,
                            expected_sort=predicate.input_sorts[0],
                        )
                        right, _ = self.parse_term(
                            terms_text[split_match.end() :],
                            variables,
                            expected_sort=predicate.input_sorts[1],
                        )
                    except ControlledNLConversionError:
                        continue
                    return ir.Atom(predicate.formal_name, (left, right))
        raise ControlledNLConversionError(f"Cannot resolve controlled natural-language condition {text!r}.")

    def render_term(self, term: ir.Term) -> str:
        if isinstance(term, ir.VarTerm):
            return term.variable.name
        if isinstance(term, ir.ConstTerm):
            return self.constant_surface[term.name]
        if isinstance(term, ir.FuncTerm):
            label = self.function_surface[term.name]
            arguments = [self.render_term(argument) for argument in term.args]
            if len(arguments) == 1:
                return f"the {label} of {arguments[0]}"
            if len(arguments) == 2:
                return f"the {label} of {arguments[0]} and {arguments[1]}"
        raise ControlledNLConversionError(f"Unsupported term in controlled-NL renderer: {term!r}.")

    def render_atom(self, atom: ir.Atom) -> str:
        if atom.predicate == "=" and len(atom.terms) == 2:
            return f"{self.render_term(atom.terms[0])} equals {self.render_term(atom.terms[1])}"
        label = self.invented_surface.get(atom.predicate, self.predicate_surface.get(atom.predicate))
        if label is None:
            raise ControlledNLConversionError(f"Unknown relation {atom.predicate!r} in candidate renderer.")
        if not atom.terms:
            return f"{label} holds"
        if len(atom.terms) == 1:
            return f"{label} holds of {self.render_term(atom.terms[0])}"
        if len(atom.terms) == 2:
            return (
                f"{label} holds between {self.render_term(atom.terms[0])} "
                f"and {self.render_term(atom.terms[1])}"
            )
        raise ControlledNLConversionError(f"Only nullary, unary, and binary relations are supported: {atom!r}.")


def _parse_mapping(block: _Block, vocabulary: CandidateVocabulary) -> ir.SignatureMorphism:
    required = {"from theory", "to theory", "pairs"}
    missing = sorted(required - set(block.fields))
    if missing:
        raise ControlledNLConversionError(
            f"Mapping {block.natural_name!r} is missing field(s): {', '.join(missing)}."
        )
    theories = {_key(theory.name): theory for theory in vocabulary.theories}
    source = theories.get(_key(block.fields["from theory"]))
    target = theories.get(_key(block.fields["to theory"]))
    if source is None or target is None:
        raise ControlledNLConversionError("Mapping From theory and To theory must name public theories.")
    if not block.pairs:
        raise ControlledNLConversionError(f"Mapping {block.natural_name!r} must contain at least one pair.")

    category_maps = {
        "object kind": (source.naming.sorts, target.naming.sorts),
        "named object": (source.naming.constants, target.naming.constants),
        "operation": (source.naming.functions, target.naming.functions),
        "relation": (source.naming.predicates, target.naming.predicates),
    }
    mapping: dict[str, str] = {}
    for pair in block.pairs:
        matched = False
        for category, (source_names, target_names) in category_maps.items():
            marker = f"{category} "
            separator = f" corresponds to {category} "
            if not _key(pair).startswith(marker) or separator not in _key(pair):
                continue
            source_surface, target_surface = re.split(
                re.escape(separator),
                pair[len(marker) :],
                maxsplit=1,
                flags=re.IGNORECASE,
            )
            source_lookup = {_key(surface): formal for formal, surface in source_names.items()}
            target_lookup = {_key(surface): formal for formal, surface in target_names.items()}
            source_formal = source_lookup.get(_key(source_surface))
            target_formal = target_lookup.get(_key(target_surface))
            if source_formal is None or target_formal is None:
                raise ControlledNLConversionError(f"Unknown public symbol in mapping pair {pair!r}.")
            if source_formal in mapping:
                raise ControlledNLConversionError(f"Duplicate source symbol in mapping pair {pair!r}.")
            mapping[source_formal] = target_formal
            matched = True
            break
        if not matched:
            raise ControlledNLConversionError(f"Malformed mapping pair {pair!r}.")
    return ir.SignatureMorphism(
        name=_candidate_identifier(block.natural_name, prefix="Map"),
        source_theory=source.name,
        target_theory=target.name,
        mapping=mapping,
    )


def _convert_or_raise(raw_candidate: str, vocabulary: CandidateVocabulary) -> str:
    blocks = _parse_blocks(raw_candidate)
    definitions = [block for block in blocks if block.kind == "Definition"]
    lemmas = [block for block in blocks if block.kind == "Lemma"]
    mappings = [block for block in blocks if block.kind == "Mapping"]
    if mappings and (definitions or lemmas):
        raise ControlledNLConversionError("Mapping blocks cannot be mixed with Definition or Lemma blocks.")

    invented: dict[str, tuple[str, tuple[str, ...]]] = {}
    definition_variables: dict[str, dict[str, ir.Variable]] = {}
    base_resolver = _Resolver(vocabulary.signature, vocabulary.naming)
    for block in definitions:
        for_every = block.fields.get("for every")
        if not for_every:
            raise ControlledNLConversionError(f"Definition {block.natural_name!r} is missing `For every`.")
        variables = base_resolver.parse_variables(for_every)
        surface_key = _key(block.natural_name)
        if surface_key in invented:
            raise ControlledNLConversionError(f"Duplicate Definition name {block.natural_name!r}.")
        invented[surface_key] = (
            _candidate_identifier(block.natural_name, prefix="Rel"),
            tuple(variable.sort for variable in variables.values()),
        )
        definition_variables[surface_key] = variables

    resolver = _Resolver(vocabulary.signature, vocabulary.naming, invented_predicates=invented)
    converted_definitions: list[ir.Definition] = []
    for block in definitions:
        means = block.fields.get("means")
        if not means:
            raise ControlledNLConversionError(f"Definition {block.natural_name!r} is missing `Means`.")
        variables = definition_variables[_key(block.natural_name)]
        body = tuple(
            resolver.parse_atom(item, variables)
            for item in _split_semicolon_items(means, field_name="Means")
        )
        converted_definitions.append(
            ir.Definition(
                name=invented[_key(block.natural_name)][0],
                parameters=tuple(variables.values()),
                body=body,
            )
        )

    converted_lemmas: list[ir.HornClause] = []
    for block in lemmas:
        for_every = block.fields.get("for every")
        when = block.fields.get("when")
        then = block.fields.get("then")
        if not for_every or not when or not then:
            raise ControlledNLConversionError(
                f"Lemma {block.natural_name!r} requires `For every`, `When`, and `Then`."
            )
        variables = resolver.parse_variables(for_every)
        premises = tuple(
            resolver.parse_atom(item, variables)
            for item in _split_semicolon_items(when, field_name="When")
        )
        conclusions = _split_semicolon_items(then, field_name="Then")
        if len(conclusions) != 1:
            raise ControlledNLConversionError(f"Lemma {block.natural_name!r} must have exactly one Then condition.")
        converted_lemmas.append(
            ir.HornClause(
                name=_candidate_identifier(block.natural_name, prefix="Lemma"),
                variables=tuple(variables.values()),
                premises=premises,
                conclusion=resolver.parse_atom(conclusions[0], variables),
            )
        )

    converted_mappings = tuple(_parse_mapping(block, vocabulary) for block in mappings)
    document = ir.Document(
        definitions=tuple(converted_definitions),
        lemmas=tuple(converted_lemmas),
        morphisms=converted_mappings,
    )
    candidate_dsl = format_document(document).strip()
    if not candidate_dsl:
        raise ControlledNLConversionError("Candidate did not produce any scoreable bridge statements.")
    parse_document(candidate_dsl)
    return candidate_dsl


def convert_controlled_nl(raw_candidate: str, vocabulary: CandidateVocabulary) -> ConversionResult:
    """Convert one controlled-NL candidate without semantic repair or inference."""

    raw_hash = hashlib.sha256(raw_candidate.encode("utf-8")).hexdigest()
    try:
        candidate_dsl = _convert_or_raise(raw_candidate, vocabulary)
    except (ControlledNLConversionError, KeyError, ValueError) as error:
        return ConversionResult(
            status="failed",
            candidate_dsl=None,
            errors=(str(error),),
            converter_version=CONVERTER_VERSION,
            grammar_version=CONTROLLED_NL_GRAMMAR_VERSION,
            converter_sha256=converter_source_sha256(),
            raw_candidate_sha256=raw_hash,
        )
    return ConversionResult(
        status="converted",
        candidate_dsl=candidate_dsl,
        errors=(),
        converter_version=CONVERTER_VERSION,
        grammar_version=CONTROLLED_NL_GRAMMAR_VERSION,
        converter_sha256=converter_source_sha256(),
        raw_candidate_sha256=raw_hash,
    )


def _render_variable_declarations(variables: tuple[ir.Variable, ...], resolver: _Resolver) -> str:
    return "; ".join(f"{variable.name} is a {resolver.sort_surface[variable.sort]} object" for variable in variables)


def render_controlled_nl_candidate(document: ir.Document, vocabulary: CandidateVocabulary) -> str:
    """Render a formal exemplar candidate into the controlled natural language."""

    invented = {
        _key(_humanize_identifier(definition.name)): (
            definition.name,
            tuple(parameter.sort for parameter in definition.parameters),
        )
        for definition in document.definitions
    }
    resolver = _Resolver(vocabulary.signature, vocabulary.naming, invented_predicates=invented)
    blocks: list[str] = []
    for definition in document.definitions:
        surface = _humanize_identifier(definition.name)
        blocks.append(
            "\n".join(
                (
                    f'Definition "{surface}"',
                    f"For every: {_render_variable_declarations(definition.parameters, resolver)}",
                    f"Means: {'; '.join(resolver.render_atom(atom) for atom in definition.body)}",
                )
            )
        )
    for lemma in document.lemmas + document.theorems:
        blocks.append(
            "\n".join(
                (
                    f'Lemma "{_humanize_identifier(lemma.name)}"',
                    f"For every: {_render_variable_declarations(lemma.variables, resolver)}",
                    f"When: {'; '.join(resolver.render_atom(atom) for atom in lemma.premises)}",
                    f"Then: {resolver.render_atom(lemma.conclusion)}",
                )
            )
        )
    theories = {theory.name: theory for theory in vocabulary.theories}
    for mapping in document.morphisms:
        source = theories.get(mapping.source_theory)
        target = theories.get(mapping.target_theory)
        if source is None or target is None:
            raise ControlledNLConversionError("Candidate mapping refers to a theory outside the public view.")
        source_categories = {
            **{name: ("object kind", source.naming.sorts[name]) for name in source.naming.sorts},
            **{name: ("named object", source.naming.constants[name]) for name in source.naming.constants},
            **{name: ("operation", source.naming.functions[name]) for name in source.naming.functions},
            **{name: ("relation", source.naming.predicates[name]) for name in source.naming.predicates},
        }
        target_categories = {
            **{name: ("object kind", target.naming.sorts[name]) for name in target.naming.sorts},
            **{name: ("named object", target.naming.constants[name]) for name in target.naming.constants},
            **{name: ("operation", target.naming.functions[name]) for name in target.naming.functions},
            **{name: ("relation", target.naming.predicates[name]) for name in target.naming.predicates},
        }
        pair_lines = []
        for source_name, target_name in mapping.mapping.items():
            source_category, source_surface = source_categories[source_name]
            target_category, target_surface = target_categories[target_name]
            if source_category != target_category:
                raise ControlledNLConversionError("Candidate mapping crosses public symbol categories.")
            pair_lines.append(
                f"- {source_category} {source_surface} corresponds to {target_category} {target_surface}"
            )
        blocks.append(
            "\n".join(
                (
                    f'Mapping "{_humanize_identifier(mapping.name)}"',
                    f"From theory: {mapping.source_theory}",
                    f"To theory: {mapping.target_theory}",
                    "Pairs:",
                    *pair_lines,
                )
            )
        )
    if not blocks:
        raise ControlledNLConversionError("Formal exemplar does not contain a supported bridge statement.")
    return "\n\n".join(blocks) + "\n"
