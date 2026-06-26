# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Round-trip coverage for the disclosure ABW DSL surface.

This module keeps the lexer, parser, and pretty-printer aligned on the shipped
grammar slice used by the seven disclosed families, including rewrites,
theories, and morphisms in the same document.
"""

from abw_core.dsl import format_document, parse_document


def test_round_trip_supported_document() -> None:
    source = """
sort T
const z : T
func a : T -> T
func n : T -> T
pred Done : T
rewrite collapse: a(z) -> n(z)
axiom done_n: forall x:T. Done(n(x))
define Normal(x:T) := n(x) = x
fact base: Done(n(z))
goal hidden: n(z) = z
theory Left {
  sort L0
  const l0 : L0
  func lf : L0 -> L0
  pred LP : L0
  theorem keep: forall x:L0. LP(x) -> LP(lf(x))
}
morphism M : Left -> Left {
  L0 -> L0
  l0 -> l0
  lf -> lf
  LP -> LP
}
"""
    document = parse_document(source)
    rendered = format_document(document)
    reparsed = parse_document(rendered)
    assert reparsed == document
