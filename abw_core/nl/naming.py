# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Deterministic naming for ABW NL outputs."""

from __future__ import annotations

from dataclasses import dataclass

from abw_core import ir


SORT_WORDS = ["mav", "ren", "tal", "nesh", "lume", "vorn"]
FUNCTION_WORDS = ["shift", "lift", "glide", "turn", "seal", "flick"]


@dataclass(frozen=True)
class NamingScheme:
    """Deterministic lexical choices for one world's NL rendering."""

    sorts: dict[str, str]
    functions: dict[str, str]
    predicates: dict[str, str]
    constants: dict[str, str]


def build_naming(signature: ir.Signature) -> NamingScheme:
    """Assign stable NL labels to the symbols in one world signature.

    Sorts, functions, and constants keep the existing neutral naming strategy so
    the packaged text stays readable without depending on outside semantics.
    Predicates are treated differently: the NL track preserves their formal
    lexicalization directly, even when the names are short letter-like symbols
    such as `P`, `R`, or `Q`.
    """

    sorts = {sort.name: SORT_WORDS[index % len(SORT_WORDS)] for index, sort in enumerate(signature.sorts)}
    functions = {function.name: FUNCTION_WORDS[index % len(FUNCTION_WORDS)] for index, function in enumerate(signature.functions)}
    predicates = {predicate.name: predicate.name for predicate in signature.predicates}
    per_sort_counts = {sort.name: 0 for sort in signature.sorts}
    constants: dict[str, str] = {}
    for constant in signature.constants:
        count = per_sort_counts[constant.sort]
        per_sort_counts[constant.sort] += 1
        constants[constant.name] = f"{sorts[constant.sort]}-{count}"
    return NamingScheme(sorts=sorts, functions=functions, predicates=predicates, constants=constants)
