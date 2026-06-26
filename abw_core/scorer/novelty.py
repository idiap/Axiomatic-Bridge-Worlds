# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
#
# SPDX-FileContributor: Andre Freitas <andre.freitas@idiap.ch>
# SPDX-FileContributor: Margarita Sharkova <margarita.sharkova@idiap.ch>
# Neuro-symbolic AI Group
#
# SPDX-License-Identifier: MIT

"""Novelty heuristics for deciding whether a candidate introduces a real bridge.

In ABW, novelty does not mean "syntactically surprising." It means "this
candidate appears to carve the public world in a meaningfully new way rather
than merely renaming what was already visible." That distinction matters
because bridge-invention benchmarks are easy to game with shallow wrappers:

- define a new predicate that is just one visible predicate under a new name
- define a conjunction whose extension still behaves almost exactly like one
  already-visible relation

This module tries to discount those degenerate cases.

Core idea
---------
The scorer compares the extension of a candidate definition against visible
predicate extensions under the bounded public closure and, when available,
under nearby diagnostic closures as well. If the candidate keeps collapsing
back to an already-visible predicate across those local perturbations, it is
not treated as a very novel abstraction.

Concrete example
----------------
If the visible world already contains `R(x, y)`, then

    define PairOnly(x, y) := R(x, y)

should receive almost no novelty credit. By contrast,

    define PairStable(x, y) := R(x, y) & P0(x) & P1(y)

may deserve substantially more credit if its extension remains meaningfully
different from any single visible predicate across the diagnostic worlds.

Limitations
-----------
- This is a bounded, local heuristic. It does not prove semantic novelty.
- Novelty is only computed for definition-style candidates.
- The thresholds are intentionally hand-tuned and interpretable rather than
  learned from a large corpus.
"""

from __future__ import annotations

from itertools import product

from abw_core import ir
from abw_core.prover import ProofResult, normalize_atom


# Per-definition novelty credit tiers. These are NOT composite-score weights
# (those live in `abw_core.scorer.weights`); they are the bounded novelty value
# a single definition earns at each tier, from "exact alias of a visible
# predicate" (no credit) up to "rich mix of several visible predicates".
NOVELTY_EXACT_ALIAS = 0.0
NOVELTY_NEAR_ALIAS = 0.05
NOVELTY_LOOSE_ALIAS = 0.15
NOVELTY_WEAK_ALIAS = 0.25
NOVELTY_CONJUNCTION_EXACT_ALIAS = 0.15
NOVELTY_CONJUNCTION_NEAR_ALIAS = 0.30
NOVELTY_INVENTED_SYMBOL = 0.4
NOVELTY_SINGLE_VISIBLE = 0.55
NOVELTY_TWO_ATOM_MIX = 0.8
NOVELTY_RICH_MIX = 1.0

# Extension-overlap thresholds used to detect alias-like definitions.
OVERLAP_IDENTICAL = 0.999
OVERLAP_VERY_HIGH = 0.95
OVERLAP_HIGH = 0.80


def _term_key(term: ir.Term) -> str:
    """Serialize one ground term into a stable key for extension comparison.

    The extension computations in this file only need equality and set overlap,
    not full term structure. Converting terms into canonical string keys makes
    those overlap checks easy to cache, compare, and debug.
    """

    return str(term.to_dict())


def _jaccard(left: set[tuple[str, ...]], right: set[tuple[str, ...]]) -> float:
    """Return the overlap ratio used to compare candidate and visible meaning.

    Jaccard similarity is a natural fit here because the novelty question is
    set-based: how similar are the tuples accepted by the candidate definition
    and the tuples accepted by one visible predicate?
    """

    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def _definition_extension(
    definition: ir.Definition,
    closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
) -> set[tuple[str, ...]]:
    """Compute the tuples that satisfy one candidate definition in a closure.

    Conceptually, this is the semantics of the candidate definition restricted
    to the finite public term universe available in the current proof result.
    The extension is the key object used throughout the novelty heuristics:
    once a definition has been turned into a set of accepted tuples, it can be
    compared to visible predicate behavior in a family-agnostic way.
    """

    domains = [closure.terms_by_sort.get(parameter.sort, ()) for parameter in definition.parameters]
    if any(not domain for domain in domains):
        return set()
    extension: set[tuple[str, ...]] = set()
    for values in product(*domains):
        mapping = {parameter.name: value for parameter, value in zip(definition.parameters, values)}
        body = tuple(normalize_atom(atom.substitute(mapping), rewrites) for atom in definition.body)
        if all(atom in closure.derivations for atom in body):
            extension.add(tuple(_term_key(value) for value in values))
    return extension


def _predicate_extension(
    predicate: ir.PredicateSymbol,
    parameter_sorts: tuple[str, ...],
    closure: ProofResult,
    rewrites: tuple[ir.RewriteRule, ...],
) -> set[tuple[str, ...]]:
    """Compute the visible extension of one predicate over the same term domain.

    This is the comparison target for candidate definitions. By evaluating both
    the candidate and the visible predicate over the same bounded domains, the
    novelty check stays local, deterministic, and directly comparable.
    """

    domains = [closure.terms_by_sort.get(sort, ()) for sort in parameter_sorts]
    if any(not domain for domain in domains):
        return set()
    extension: set[tuple[str, ...]] = set()
    for values in product(*domains):
        atom = normalize_atom(ir.Atom(predicate.name, tuple(values)), rewrites)
        if atom in closure.derivations:
            extension.add(tuple(_term_key(term) for term in atom.terms))
    return extension


def _best_visible_overlap(
    definition: ir.Definition,
    visible_predicates: dict[str, ir.PredicateSymbol],
    closure: ProofResult | None,
    rewrites: tuple[ir.RewriteRule, ...],
) -> float | None:
    """Find the strongest visible-predicate match for one candidate definition.

    The candidate only competes with visible predicates of the same arity and
    sort signature. A high overlap means the candidate probably behaves like a
    renamed public relation instead of introducing a distinct grouping.
    """

    if closure is None:
        return None

    parameter_sorts = tuple(parameter.sort for parameter in definition.parameters)
    definition_extension = _definition_extension(definition, closure, rewrites)
    best_overlap = 0.0
    for predicate in visible_predicates.values():
        if predicate.input_sorts != parameter_sorts:
            continue
        best_overlap = max(
            best_overlap,
            _jaccard(
                definition_extension,
                _predicate_extension(predicate, parameter_sorts, closure, rewrites),
            ),
        )
    return best_overlap


def _single_visible_alias_score(
    definition: ir.Definition,
    visible_predicates: dict[str, ir.PredicateSymbol],
    closure: ProofResult | None,
    rewrites: tuple[ir.RewriteRule, ...],
    diagnostic_closures: tuple[ProofResult, ...] = (),
) -> float | None:
    """Assign novelty credit when the candidate is a one-atom visible wrapper.

    This branch exists because single-atom aliases are the clearest failure
    mode for bridge invention. If the candidate body is just one visible atom,
    the novelty score should be near zero unless diagnostic perturbations reveal
    surprisingly different behavior.
    """

    if len(definition.body) != 1:
        return None
    only_atom = definition.body[0]
    if only_atom.predicate not in visible_predicates or only_atom.predicate == "=":
        return None

    overlaps = [
        overlap
        for overlap in (
            _best_visible_overlap(definition, visible_predicates, active_closure, rewrites)
            for active_closure in (closure,) + diagnostic_closures
        )
        if overlap is not None
    ]
    if not overlaps:
        return None
    best_overlap = sum(overlaps) / len(overlaps)

    # The thresholds are intentionally steep: direct aliases should be almost
    # novelty-free unless the diagnostic worlds genuinely separate them.
    if best_overlap >= OVERLAP_IDENTICAL:
        return NOVELTY_EXACT_ALIAS
    if best_overlap >= OVERLAP_VERY_HIGH:
        return NOVELTY_NEAR_ALIAS
    if best_overlap >= OVERLAP_HIGH:
        return NOVELTY_LOOSE_ALIAS
    return NOVELTY_WEAK_ALIAS


def _visible_conjunction_alias_score(
    definition: ir.Definition,
    visible_predicates: dict[str, ir.PredicateSymbol],
    closure: ProofResult | None,
    rewrites: tuple[ir.RewriteRule, ...],
    diagnostic_closures: tuple[ProofResult, ...] = (),
) -> float | None:
    """Discount conjunctions that still behave like one visible public concept.

    Some weak candidates are not single-atom aliases; they are conjunctions
    whose extension nevertheless tracks an already-visible predicate almost
    perfectly. This branch catches that softer failure mode.
    """

    if not definition.body:
        return None
    if any(atom.predicate == "=" or atom.predicate not in visible_predicates for atom in definition.body):
        return None

    overlaps = [
        overlap
        for overlap in (
            _best_visible_overlap(definition, visible_predicates, active_closure, rewrites)
            for active_closure in (closure,) + diagnostic_closures
        )
        if overlap is not None
    ]
    if not overlaps:
        return None
    best_overlap = sum(overlaps) / len(overlaps)
    if best_overlap >= OVERLAP_IDENTICAL:
        return NOVELTY_CONJUNCTION_EXACT_ALIAS
    if best_overlap >= OVERLAP_VERY_HIGH:
        return NOVELTY_CONJUNCTION_NEAR_ALIAS
    return None


def novelty_score(
    definitions: tuple[ir.Definition, ...],
    world: ir.World,
    closure: ProofResult | None = None,
    *,
    rewrites: tuple[ir.RewriteRule, ...] = (),
    diagnostic_closures: tuple[ProofResult, ...] = (),
) -> float:
    """Score whether candidate definitions look like real new abstractions.

    The returned score is an average over definition-level novelty judgments.
    The heuristic proceeds in tiers:

    1. exact reuse of a visible predicate name gets zero credit
    2. single visible aliases get almost no credit
    3. conjunctions that still mimic one visible predicate get discounted
    4. definitions that compose several visible predicates get more credit
    5. larger, genuinely mixed abstractions receive the highest bounded score

    This makes novelty interpretable: the scorer is not rewarding obscurity, it
    is rewarding the appearance of a useful new grouping.
    """

    if not definitions:
        return 0.0
    visible_predicates = world.signature.predicate_map()
    scores: list[float] = []
    for definition in definitions:
        if definition.name in visible_predicates:
            scores.append(NOVELTY_EXACT_ALIAS)
            continue

        alias_score = _single_visible_alias_score(
            definition,
            visible_predicates,
            closure,
            rewrites,
            diagnostic_closures=diagnostic_closures,
        )
        if alias_score is not None:
            scores.append(alias_score)
            continue

        conjunction_alias_score = _visible_conjunction_alias_score(
            definition,
            visible_predicates,
            closure,
            rewrites,
            diagnostic_closures=diagnostic_closures,
        )
        if conjunction_alias_score is not None:
            scores.append(conjunction_alias_score)
            continue

        if any(atom.predicate not in visible_predicates and atom.predicate != "=" for atom in definition.body):
            scores.append(NOVELTY_INVENTED_SYMBOL)
            continue

        visible_body_predicates = {atom.predicate for atom in definition.body if atom.predicate != "="}
        if len(visible_body_predicates) <= 1:
            scores.append(NOVELTY_SINGLE_VISIBLE)
            continue
        if len(definition.body) == 2:
            scores.append(NOVELTY_TWO_ATOM_MIX)
            continue
        scores.append(NOVELTY_RICH_MIX)
    return sum(scores) / len(scores)
