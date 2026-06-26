# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Tokenization helpers for the ABW DSL.

The lexer keeps the surface deliberately small: it strips comments and
whitespace, preserves byte offsets for error reporting, and emits just enough
token kinds for the handwritten parser. Keyword recognition is deferred to the
parser so new DSL statements can often be added without widening the lexical
alphabet.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


# Token order matters. Multi-character operators must appear before their
# single-character prefixes, and comments must be consumed before generic
# mismatch handling so error offsets stay stable.
TOKEN_PATTERN = re.compile(
    r"""
    (?P<COMMENT>\#.*)
    |(?P<ARROW>->)
    |(?P<DEFINE>:=)
    |(?P<EQUAL>=)
    |(?P<AND>&)
    |(?P<LBRACE>\{)
    |(?P<RBRACE>\})
    |(?P<LPAREN>\()
    |(?P<RPAREN>\))
    |(?P<COMMA>,)
    |(?P<COLON>:)
    |(?P<DOT>\.)
    |(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    |(?P<NEWLINE>\n)
    |(?P<WS>[ \t\r]+)
    |(?P<MISMATCH>.)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    """One lexical unit in the ABW DSL source stream.

    `position` stores the byte offset in the original source so later parse and
    type errors can point back to the author's text without tracking line state
    in the lexer itself.
    """

    kind: str
    value: str
    position: int


class LexError(ValueError):
    """Raised when the DSL tokenizer sees an unexpected character."""


def tokenize(source: str) -> list[Token]:
    """Convert DSL source text into the token stream consumed by the parser.

    Newlines are ignored because the current ABW surface is punctuation-driven
    rather than indentation-sensitive. An explicit EOF sentinel is appended so
    the parser can use ordinary token lookahead at end of input.
    """

    tokens: list[Token] = []
    for match in TOKEN_PATTERN.finditer(source):
        kind = match.lastgroup or "MISMATCH"
        value = match.group()
        if kind in {"COMMENT", "WS", "NEWLINE"}:
            continue
        if kind == "MISMATCH":
            raise LexError(f"Unexpected character {value!r} at offset {match.start()}.")
        tokens.append(Token(kind, value, match.start()))
    # EOF as a real token keeps the recursive-descent helpers simple and avoids
    # repeated index-boundary branches across the parser.
    tokens.append(Token("EOF", "", len(source)))
    return tokens
